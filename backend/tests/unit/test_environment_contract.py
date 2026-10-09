from pathlib import Path


def test_example_environment_contains_all_required_service_endpoints() -> None:
    text = Path(".env.example").read_text(encoding="utf-8")

    for name in (
        "MONGO_URI=",
        "REDIS_URL=",
        "OPENSEARCH_URL=",
        "MILVUS_HOST=",
        "MILVUS_PORT=",
    ):
        assert name in text
