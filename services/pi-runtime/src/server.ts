import type { IncomingMessage, ServerResponse } from "node:http";

import {
  RequestValidationError,
  parseInvocationRequest,
} from "./contracts.js";
import { executePiInvocation, type PiRuntimeMode } from "./engine.js";

const MAX_REQUEST_BYTES = 1_000_000;
const DEFAULT_ALLOWED_DEPARTMENTS = new Set([
  "tax",
  "hrss",
  "housing",
  "dept_tax",
  "dept_hr",
  "dept_market",
]);

export type PiRuntimeServiceOptions = {
  serviceToken: string;
  mode: PiRuntimeMode;
  allowedDepartmentIds?: readonly string[];
};

export type PiRuntimeService = {
  handle: (request: IncomingMessage, response: ServerResponse) => Promise<void>;
};

export function createPiRuntimeService(options: PiRuntimeServiceOptions): PiRuntimeService {
  if (options.serviceToken.length < 16) {
    throw new Error("PI_INTERNAL_SERVICE_TOKEN must be at least 16 characters.");
  }
  const allowedDepartments = new Set(options.allowedDepartmentIds ?? DEFAULT_ALLOWED_DEPARTMENTS);
  return {
    handle: async (request, response) => {
      if (!isAuthorized(request, options.serviceToken)) {
        sendJson(response, 401, { ok: false, error: { code: "unauthorized" } });
        return;
      }
      if (request.method === "GET" && request.url === "/internal/health/live") {
        sendJson(response, 200, { ok: true, live: true, runtime: "pi-agent-core" });
        return;
      }
      if (request.method === "GET" && request.url === "/internal/health/ready") {
        sendJson(response, 200, { ok: true, ready: true, mode: options.mode });
        return;
      }
      if (request.method !== "POST" || request.url !== "/internal/v1/invoke") {
        sendJson(response, 404, { ok: false, error: { code: "not_found" } });
        return;
      }
      try {
        const payload = await readJson(request);
        const invocation = parseInvocationRequest(payload);
        if (invocation.dept_id && !allowedDepartments.has(invocation.dept_id)) {
          throw new RequestValidationError("unregistered_department");
        }
        const startedAt = performance.now();
        const result = await executePiInvocation(invocation, options.mode);
        sendJson(response, 200, {
          ok: true,
          request_id: invocation.request_id,
          output_text: result.outputText,
          output_json: result.outputJson,
          provider: "faux",
          model: "zhengheng-faux-policy",
          usage: {
            input_tokens: result.inputTokens,
            output_tokens: result.outputTokens,
            total_tokens: result.totalTokens,
          },
          latency_ms: Math.round((performance.now() - startedAt) * 100) / 100,
          finish_reason: "stop",
          event_count: result.eventCount,
          error: null,
          runtime: {
            agent_engine: "pi-agent-core",
            tool_count: result.toolCount,
            mode: options.mode,
          },
        });
      } catch (error) {
        if (error instanceof RequestValidationError) {
          sendJson(response, 400, { ok: false, error: { code: error.code } });
          return;
        }
        sendJson(response, 503, { ok: false, error: { code: "runtime_unavailable" } });
      }
    },
  };
}

async function readJson(request: IncomingMessage): Promise<unknown> {
  let total = 0;
  const chunks: Buffer[] = [];
  for await (const chunk of request) {
    const buffer = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
    total += buffer.length;
    if (total > MAX_REQUEST_BYTES) {
      throw new RequestValidationError("request_too_large");
    }
    chunks.push(buffer);
  }
  try {
    return JSON.parse(Buffer.concat(chunks).toString("utf8"));
  } catch {
    throw new RequestValidationError("invalid_json");
  }
}

function isAuthorized(request: IncomingMessage, serviceToken: string): boolean {
  return request.headers["x-internal-service-token"] === serviceToken;
}

function sendJson(response: ServerResponse, status: number, payload: object): void {
  response.writeHead(status, {
    "content-type": "application/json; charset=utf-8",
    "cache-control": "no-store",
  });
  response.end(JSON.stringify(payload));
}
