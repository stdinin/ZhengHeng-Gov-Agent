# k6 Chat Validation

`evaluation/k6/chat.js` sends real HTTP traffic only. A request is successful only when the
chat API returns HTTP 200; `503` is an error and causes k6 thresholds to fail.
The validation profile uses the real MongoDB, Redis, OpenSearch, Milvus, local
embedding, and reranking path with FakeLLM answer generation. Its results must
be titled **Harness / Retrieval Infrastructure Performance (FakeLLM)**, not
online-LLM end-to-end performance.

After infrastructure recovery, run the documented 10 VU, 50 VU, and optional
200 VU five-minute steady scenarios, storing k6 raw JSON and summary output as
run artifacts. Pass `ACCESS_TOKEN` through the environment; never add it to the
script, shell history, or repository.
