from pathlib import Path


def test_container_runner_command_uses_host_network_and_never_exports_llm_credentials() -> None:
    from scripts.run_integration_container import build_run_command

    command = build_run_command(
        image="zhengheng-integration-runner:cpu",
        workspace=Path("D:/code/ZhengHeng"),
        hf_cache_dir=Path("C:/Users/XuWei/.cache/huggingface"),
    )

    assert "--network" in command
    assert command[command.index("--network") + 1] == "host"
    assert "RUN_INTEGRATION=1" in command
    assert "DEEPSEEK_API_KEY" not in " ".join(command)
    assert command[-2:] == ["zhengheng-integration-runner:cpu", "scripts/run_integration.py"]
