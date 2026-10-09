"""Run real integration groups in isolated Python processes on Windows.

The CrossEncoder is a large native PyTorch model.  Isolating model-owning
groups avoids a known Windows native crash on repeated in-process loads while
preserving every real Mongo/OpenSearch/Milvus assertion.
"""

import os
import subprocess
import sys

GROUPS = (
    (
        "foundation-document-evolution",
        (
            "backend/tests/integration/test_health_ready.py",
            "backend/tests/integration/test_auth_login.py",
            "backend/tests/integration/test_document_repository.py",
            "backend/tests/integration/test_document_api.py",
            "backend/tests/integration/test_document_indexer.py",
            "backend/tests/integration/test_document_version_e2e.py",
            "backend/tests/integration/test_memory_evolution_persistence.py",
        ),
    ),
    ("retrieval", ("backend/tests/integration/test_retrieval_backends.py",)),
    ("harness", ("backend/tests/integration/test_harness_real_retrieval.py",)),
)


def main() -> int:
    environment = os.environ | {"RUN_INTEGRATION": "1"}
    failed: list[str] = []
    for name, paths in GROUPS:
        print(f"\n=== integration group: {name} ===", flush=True)
        result = subprocess.run(
            [sys.executable, "-m", "pytest", *paths, "-q", "-rs"],
            env=environment,
            check=False,
        )
        if result.returncode:
            failed.append(name)
    if failed:
        print(f"Integration groups failed: {', '.join(failed)}", file=sys.stderr)
        return 1
    print("All isolated real integration groups passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
