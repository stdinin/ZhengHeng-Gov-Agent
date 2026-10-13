export const ALLOWED_NODES = new Set([
  "intent",
  "rewrite",
  "route",
  "answer",
  "verify",
  "aggregate",
  "reflect",
]);

export type InvocationMessage = {
  role: "system" | "user" | "assistant";
  content: string;
};

export type InvocationRequest = {
  request_id: string;
  trace_id: string;
  agent_id: string;
  dept_id: string | null;
  node: string;
  system_prompt: string;
  messages: InvocationMessage[];
  response_schema: JsonObject;
  timeout_ms: number;
  metadata: JsonObject;
};

export type JsonPrimitive = boolean | number | string | null;
export type JsonValue = JsonPrimitive | JsonObject | JsonValue[];
export type JsonObject = { [key: string]: JsonValue };

export class RequestValidationError extends Error {
  constructor(readonly code: string) {
    super(code);
  }
}

export function parseInvocationRequest(value: unknown): InvocationRequest {
  if (!isObject(value)) {
    throw new RequestValidationError("invalid_request");
  }
  if ("tools" in value || "tool_choice" in value) {
    throw new RequestValidationError("tools_not_allowed");
  }
  for (const field of ["shell_command", "command", "file_path", "fetch_url"]) {
    if (field in value) {
      throw new RequestValidationError("capability_not_allowed");
    }
  }

  const requestId = stringField(value, "request_id", 128);
  const traceId = stringField(value, "trace_id", 128);
  const agentId = stringField(value, "agent_id", 128);
  const node = stringField(value, "node", 32);
  if (!ALLOWED_NODES.has(node)) {
    throw new RequestValidationError("unsupported_node");
  }
  const deptIdValue = value.dept_id;
  if (deptIdValue !== null && deptIdValue !== undefined && typeof deptIdValue !== "string") {
    throw new RequestValidationError("invalid_department");
  }
  if (typeof deptIdValue === "string" && (deptIdValue.length === 0 || deptIdValue.length > 64)) {
    throw new RequestValidationError("invalid_department");
  }
  const systemPrompt = stringField(value, "system_prompt", 16_000);
  const messages = messageField(value);
  const responseSchema = objectField(value, "response_schema");
  if (JSON.stringify(responseSchema).length > 24_000) {
    throw new RequestValidationError("schema_too_large");
  }
  const timeoutMs = numberField(value, "timeout_ms");
  if (!Number.isInteger(timeoutMs) || timeoutMs < 100 || timeoutMs > 30_000) {
    throw new RequestValidationError("invalid_timeout");
  }
  const metadata = objectField(value, "metadata");
  return {
    request_id: requestId,
    trace_id: traceId,
    agent_id: agentId,
    dept_id: deptIdValue ?? null,
    node,
    system_prompt: systemPrompt,
    messages,
    response_schema: responseSchema,
    timeout_ms: timeoutMs,
    metadata,
  };
}

function messageField(value: Record<string, unknown>): InvocationMessage[] {
  if (!Array.isArray(value.messages) || value.messages.length === 0 || value.messages.length > 16) {
    throw new RequestValidationError("invalid_messages");
  }
  return value.messages.map((message) => {
    if (!isObject(message)) {
      throw new RequestValidationError("invalid_messages");
    }
    const role = stringField(message, "role", 16);
    if (role !== "system" && role !== "user" && role !== "assistant") {
      throw new RequestValidationError("invalid_messages");
    }
    return { role, content: stringField(message, "content", 16_000) };
  });
}

function stringField(value: Record<string, unknown>, name: string, maximum: number): string {
  const field = value[name];
  if (typeof field !== "string" || field.length === 0 || field.length > maximum) {
    throw new RequestValidationError(`invalid_${name}`);
  }
  return field;
}

function numberField(value: Record<string, unknown>, name: string): number {
  const field = value[name];
  if (typeof field !== "number" || !Number.isFinite(field)) {
    throw new RequestValidationError(`invalid_${name}`);
  }
  return field;
}

function objectField(value: Record<string, unknown>, name: string): JsonObject {
  const field = value[name];
  if (!isObject(field)) {
    throw new RequestValidationError(`invalid_${name}`);
  }
  return field as JsonObject;
}

export function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
