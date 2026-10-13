import { createServer } from "node:http";

import { createPiRuntimeService } from "./server.js";

const port = Number.parseInt(process.env.PI_RUNTIME_PORT ?? "8090", 10);
const serviceToken = process.env.PI_INTERNAL_SERVICE_TOKEN;
if (!serviceToken) {
  throw new Error("PI_INTERNAL_SERVICE_TOKEN is required.");
}
if (process.env.PI_RUNTIME_MODE && process.env.PI_RUNTIME_MODE !== "faux") {
  throw new Error("Only the deterministic faux Pi Runtime profile is currently configured.");
}
if (!Number.isInteger(port) || port < 1 || port > 65_535) {
  throw new Error("PI_RUNTIME_PORT must be a valid TCP port.");
}

const service = createPiRuntimeService({ serviceToken, mode: "faux" });
const server = createServer(service.handle);
server.listen(port, "0.0.0.0", () => {
  process.stdout.write(`pi-runtime listening on ${port}\n`);
});

for (const signal of ["SIGINT", "SIGTERM"] as const) {
  process.once(signal, () => server.close(() => process.exit(0)));
}
