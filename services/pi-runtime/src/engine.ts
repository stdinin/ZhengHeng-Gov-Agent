import { Agent } from "@earendil-works/pi-agent-core";
import { createFauxCore, fauxAssistantMessage } from "@earendil-works/pi-ai";

import type { InvocationRequest, JsonObject, JsonValue } from "./contracts.js";

export type PiRuntimeMode = "faux";

export type PiInvocationResult = {
  outputJson: JsonValue;
  outputText: string;
  inputTokens: number;
  outputTokens: number;
  totalTokens: number;
  toolCount: number;
  eventCount: number;
};

/**
 * Execute the official Pi Agent loop with an intentionally tool-free faux transport.
 *
 * This mode is solely a deterministic internal-validation profile. It exercises the
 * same Agent + pi-ai stream boundary as a configured provider without accepting any
 * executable tool declaration from the caller.
 */
export async function executePiInvocation(
  request: InvocationRequest,
  mode: PiRuntimeMode,
): Promise<PiInvocationResult> {
  if (mode !== "faux") {
    throw new Error("unsupported_runtime_mode");
  }
  const expected = fauxFixtureForRequest(request);
  const faux = createFauxCore({
    models: [{ id: "zhengheng-faux-policy", name: "ZhengHeng Faux Policy" }],
  });
  faux.setResponses([fauxAssistantMessage(JSON.stringify(expected))]);

  const agent = new Agent({
    initialState: {
      systemPrompt: request.system_prompt,
      model: faux.getModel(),
      thinkingLevel: "off",
      tools: [],
    },
    streamFn: faux.streamSimple,
    toolExecution: "sequential",
  });
  let assistantText: string | undefined;
  let eventCount = 0;
  agent.subscribe((event) => {
    eventCount += 1;
    if (event.type === "message_end" && event.message.role === "assistant") {
      assistantText = event.message.content
        .filter((content) => content.type === "text")
        .map((content) => content.text)
        .join("");
    }
  });

  const prompt = request.messages.map((message) => `[${message.role}] ${message.content}`).join("\n\n");
  await promptWithTimeout(agent, prompt, request.timeout_ms);
  if (agent.state.tools.length !== 0) {
    throw new Error("tool_invariant_violated");
  }
  if (!assistantText) {
    throw new Error("empty_pi_response");
  }
  const outputJson: unknown = JSON.parse(assistantText);
  return {
    outputJson: outputJson as JsonValue,
    outputText: assistantText,
    inputTokens: 0,
    outputTokens: 0,
    totalTokens: 0,
    toolCount: agent.state.tools.length,
    eventCount,
  };
}

/**
 * Keep the no-provider validation profile deterministic without letting a
 * schema-shaped placeholder become a policy-routing decision.  The fixture is
 * deliberately limited to query-preserving rewrite and static keyword routing;
 * it never generates a policy fact, calls a tool, or changes the supplied
 * evidence.  Production providers keep using the same Pi invocation contract.
 */
function fauxFixtureForRequest(request: InvocationRequest): JsonValue {
  const schema = request.response_schema;
  const properties = isObject(schema.properties) ? schema.properties : {};
  const query = queryFromMessages(request.messages.map((message) => message.content));

  if (request.node === "rewrite" && "queries" in properties) {
    return { queries: [query], used_fallback: false };
  }
  if (request.node === "route" && "routes" in properties) {
    const departments = departmentsForQuery(query);
    return {
      routes: (departments.length > 0 ? departments : ["other"]).map((departmentId) => ({
        department_id: departmentId,
        score: departmentId === "other" ? 0 : 1,
        reason: "deterministic faux routing fixture",
      })),
      routing_uncertain: departments.length === 0,
      used_fallback: false,
    };
  }
  return exampleFromSchema(schema, schema, request.node);
}

function queryFromMessages(contents: string[]): string {
  const joined = contents.join("\n");
  const marker = "query=";
  const index = joined.lastIndexOf(marker);
  if (index >= 0) {
    const candidate = joined.slice(index + marker.length).trim();
    if (candidate.length > 0) {
      return candidate;
    }
  }
  return contents.at(-1)?.trim() || "";
}

function departmentsForQuery(query: string): string[] {
  const rules: Array<[string, string[]]> = [
    ["tax", ["税", "增值税", "个税", "纳税", "发票"]],
    ["hrss", ["社保", "社会保险", "就业", "劳动", "人才"]],
    ["housing", ["住房", "公积金", "房屋", "租赁"]],
  ];
  return rules
    .filter(([, keywords]) => keywords.some((keyword) => query.includes(keyword)))
    .map(([departmentId]) => departmentId);
}

async function promptWithTimeout(agent: Agent, prompt: string, timeoutMs: number): Promise<void> {
  let timer: NodeJS.Timeout | undefined;
  try {
    await Promise.race([
      agent.prompt(prompt),
      new Promise<never>((_, reject) => {
        timer = setTimeout(() => {
          agent.abort();
          reject(new Error("pi_runtime_timeout"));
        }, timeoutMs);
      }),
    ]);
  } finally {
    if (timer) {
      clearTimeout(timer);
    }
  }
}

function exampleFromSchema(
  schema: JsonObject,
  root: JsonObject,
  node: string,
  path: string[] = [],
): JsonValue {
  const resolved = resolveSchema(schema, root);
  if ("const" in resolved) {
    return jsonValue(resolved.const);
  }
  if (Array.isArray(resolved.enum) && resolved.enum.length > 0) {
    return jsonValue(resolved.enum[0]);
  }
  if (Array.isArray(resolved.anyOf)) {
    const candidate = resolved.anyOf
      .filter(isSchema)
      .find((entry) => resolveSchema(entry, root).type !== "null");
    if (candidate) {
      return exampleFromSchema(candidate, root, node, path);
    }
  }
  if (Array.isArray(resolved.oneOf) && resolved.oneOf.length > 0 && isSchema(resolved.oneOf[0])) {
    return exampleFromSchema(resolved.oneOf[0], root, node, path);
  }
  if (Array.isArray(resolved.allOf) && resolved.allOf.length > 0 && isSchema(resolved.allOf[0])) {
    return exampleFromSchema(resolved.allOf[0], root, node, path);
  }
  if (resolved.type === "array") {
    const item = isSchema(resolved.items) ? resolved.items : {};
    const minimum = typeof resolved.minItems === "number" ? Math.max(0, resolved.minItems) : 0;
    const length = node === "answer" && path.at(-1) === "claims" ? Math.max(1, minimum) : minimum;
    return Array.from({ length }, () => exampleFromSchema(item, root, node, path));
  }
  if (resolved.type === "integer") {
    return schemaMinimum(resolved, 1);
  }
  if (resolved.type === "number") {
    return schemaMinimum(resolved, 1);
  }
  if (resolved.type === "boolean") {
    if (node === "verify" && path.at(-1) === "contradiction") {
      return false;
    }
    return true;
  }
  if (resolved.type === "object" || isObject(resolved.properties)) {
    const output: JsonObject = {};
    const properties = isObject(resolved.properties) ? resolved.properties : {};
    const required = Array.isArray(resolved.required)
      ? resolved.required.filter((name): name is string => typeof name === "string")
      : Object.keys(properties);
    const names = node === "answer" && "claims" in properties
      ? [...new Set([...required, "claims"])]
      : required;
    for (const name of names) {
      const property = properties[name];
      if (isSchema(property)) {
        output[name] = exampleFromSchema(property, root, node, [...path, name]);
      }
    }
    return output;
  }
  if (node === "answer" && path.at(-1) === "citation_ids") {
    return "C1";
  }
  if (node === "answer" && path.at(-1) === "answer") {
    return "Runtime fixture answer [C1]";
  }
  return `${node}-result`;
}

function resolveSchema(schema: JsonObject, root: JsonObject): JsonObject {
  if (typeof schema.$ref !== "string" || !schema.$ref.startsWith("#/$defs/")) {
    return schema;
  }
  const definitionName = schema.$ref.slice("#/$defs/".length);
  const definitions = root.$defs;
  if (!isObject(definitions) || !isSchema(definitions[definitionName])) {
    throw new Error("unresolvable_schema_reference");
  }
  return definitions[definitionName];
}

function schemaMinimum(schema: JsonObject, fallback: number): number {
  return typeof schema.minimum === "number" ? Math.max(fallback, schema.minimum) : fallback;
}

function jsonValue(value: unknown): JsonValue {
  if (
    value === null ||
    typeof value === "string" ||
    typeof value === "number" ||
    typeof value === "boolean"
  ) {
    return value;
  }
  throw new Error("schema_const_is_not_json_primitive");
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isSchema(value: unknown): value is JsonObject {
  return isObject(value);
}
