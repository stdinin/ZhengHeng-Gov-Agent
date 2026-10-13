"""Run the unchanged real integration suites in a Linux model-isolation process.

Windows native PyTorch can fail to map the CrossEncoder when system commit is
temporarily low.  This runner builds a pytest-enabled derivative of the local
CPU image and executes the same isolated pytest groups against the host's real
Mongo, Redis, OpenSearch, Milvus and Docker services.  It is not a mock path.
"""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

DEFAULT_IMAGE = "zhengheng-integration-runner:cpu"
BASE_IMAGE = "zhengheng-eval-runner:cpu"


def build_run_command(*, image: str, workspace: Path, hf_cache_dir: Path) -> list[str]:
    """Return the secret-free Docker command for one full integration acceptance run."""

    return [
        "docker",
        "run",
        "--rm",
        "--network",
        "host",
        "--entrypoint",
        "python",
        "-w",
        "/workspace",
        "-v",
        f"{workspace.resolve()}:/workspace",
        "-v",
        f"{hf_cache_dir.resolve()}:/root/.cache/huggingface:ro",
        "-e",
        "RUN_INTEGRATION=1",
        "-e",
        "HF_HUB_OFFLINE=1",
        "-e",
        "TRANSFORMERS_OFFLINE=1",
        "-e",
        "OMP_NUM_THREADS=1",
        "-e",
        "MKL_NUM_THREADS=1",
        "-e",
        "PYTHONUTF8=1",
        image,
        "scripts/run_integration.py",
    ]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default=DEFAULT_IMAGE)
    parser.add_argument("--hf-cache-dir", type=Path, default=Path.home() / ".cache/huggingface")
    parser.add_argument("--skip-build", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    workspace = Path(__file__).resolve().parents[1]
    cache = args.hf_cache_dir
    if not cache.is_dir():
        raise RuntimeError(f"Hugging Face cache directory does not exist: {cache}")
    if not args.skip_build:
        build = subprocess.run(
            [
                "docker",
                "build",
                "--tag",
                args.image,
                "--file",
                str(workspace / "deploy" / "docker" / "integration-runner.Dockerfile"),
                str(workspace),
            ],
            check=False,
        )
        if build.returncode:
            return build.returncode
    return subprocess.run(
        build_run_command(image=args.image, workspace=workspace, hf_cache_dir=cache),
        check=False,
    ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
