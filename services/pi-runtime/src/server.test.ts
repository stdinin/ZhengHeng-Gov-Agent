import assert from "node:assert/strict";
import { createServer } from "node:http";
import test from "node:test";

import { createPiRuntimeService } from "./server.js";

const token = "unit-test-internal-token";

async function withService(
  run: (baseUrl: string) => Promise<void>,
): Promise<void> {
  const service = createPiRuntimeService({ serviceToken: token, mode: "faux" });
  const server = createServer(service.handle);
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  if (!address || typeof address === "string") {
    throw new Error("expected a TCP listener address");
  }
  const baseUrl = `http://127.0.0.1:${address.port}`;
  try {
    await run(baseUrl);
  } finally {
    await new Promise<void>((resolve, reject) =>
      server.close((error) => (error ? reject(error) : resolve())),
    );
  }
}

function invokePayload(): Record<string, unknown> {
  return {
    request_id: "request-pi-01",
    trace_id: "trace-pi-01",
    agent_id: "orchestrator",
    dept_id: null,
    node: "route",
    system_prompt: "Return only structured policy routing data.",
    messages: [{ role: "user", content: "请咨询个税和社会保险政策" }],
    response_schema: {
      type: "object",
      properties: {
        label: { type: "string" },
        score: { type: "number" },
        selected: { type: "boolean" },
      },
      required: ["label", "score", "selected"],
    },
    timeout_ms: 1_000,
    metadata: {},
  };
}

test("PI-01/PI-05: invoke is authenticated, tool-free, and executes the Pi Agent path", async () => {
  await withService(async (baseUrl) => {
    const response = await fetch(`${baseUrl}/internal/v1/invoke`, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "X-Internal-Service-Token": token,
      },
      body: JSON.stringify(invokePayload()),
    });

    assert.equal(response.status, 200);
    const body = (await response.json()) as {
      ok: boolean;
      request_id: string;
      output_text: string;
      provider: string;
      model: string;
      finish_reason: string;
      event_count: number;
      error: null;
      output_json: { label: string; score: number; selected: boolean };
      runtime: { agent_engine: string; tool_count: number; mode: string };
    };
    assert.equal(body.ok, true);
    assert.equal(body.request_id, "request-pi-01");
    assert.equal(body.output_text, JSON.stringify(body.output_json));
    assert.equal(body.provider, "faux");
    assert.equal(body.model, "zhengheng-faux-policy");
    assert.equal(body.finish_reason, "stop");
    assert.ok(body.event_count > 0);
    assert.equal(body.error, null);
    assert.equal(body.output_json.label, "route-result");
    assert.equal(body.output_json.score, 1);
    assert.equal(body.output_json.selected, true);
    assert.deepEqual(body.runtime, {
      agent_engine: "pi-agent-core",
      tool_count: 0,
      mode: "faux",
    });
  });
});

test("PI-01: faux route fixtures retain all static departments present in the query", async () => {
  await withService(async (baseUrl) => {
    const response = await fetch(`${baseUrl}/internal/v1/invoke`, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "X-Internal-Service-Token": token,
      },
      body: JSON.stringify({
        ...invokePayload(),
        response_schema: {
          type: "object",
          properties: {
            routes: {
              type: "array",
              items: {
                type: "object",
                properties: {
                  department_id: { type: "string" },
                  score: { type: "number" },
                  reason: { type: "string" },
                },
                required: ["department_id", "score", "reason"],
              },
            },
            routing_uncertain: { type: "boolean" },
            used_fallback: { type: "boolean" },
          },
          required: ["routes", "routing_uncertain", "used_fallback"],
        },
      }),
    });
    assert.equal(response.status, 200);
    const body = (await response.json()) as {
      output_json: { routes: Array<{ department_id: string }> };
    };
    assert.deepEqual(
      body.output_json.routes.map((route) => route.department_id),
      ["tax", "hrss"],
    );
  });
});

test("PI-05: internal token and arbitrary tool payloads are rejected", async () => {
  await withService(async (baseUrl) => {
    const unauthenticated = await fetch(`${baseUrl}/internal/health/ready`);
    assert.equal(unauthenticated.status, 401);

    const forbiddenTools = await fetch(`${baseUrl}/internal/v1/invoke`, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "X-Internal-Service-Token": token,
      },
      body: JSON.stringify({ ...invokePayload(), tools: [{ name: "shell" }] }),
    });
    assert.equal(forbiddenTools.status, 400);
    const body = (await forbiddenTools.json()) as { error: { code: string } };
    assert.equal(body.error.code, "tools_not_allowed");

    const unknownDepartment = await fetch(`${baseUrl}/internal/v1/invoke`, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "X-Internal-Service-Token": token,
      },
      body: JSON.stringify({ ...invokePayload(), dept_id: "not-registered" }),
    });
    assert.equal(unknownDepartment.status, 400);
    const unknownDepartmentBody = (await unknownDepartment.json()) as {
      error: { code: string };
    };
    assert.equal(unknownDepartmentBody.error.code, "unregistered_department");
  });
});
