# k6 Chat Validation

`k6/chat.js` sends real HTTP traffic only. It does not supply a fake result and must not be used to claim performance until the API, MongoDB, Redis, OpenSearch, Milvus, and LLM dependencies are available.

After infrastructure recovery, run the documented 10 VU, 50 VU, and optional 200 VU steady scenarios, storing k6 JSON output as a run artifact. Pass `ACCESS_TOKEN` through the environment; never add it to the script, shell history, or repository.
