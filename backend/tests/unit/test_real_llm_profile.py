import importlib

import pytest


def test_real_llm_profile_requires_an_environment_key_without_echoing_it() -> None:
    try:
        module = importlib.import_module("scripts.run_real_llm_e2e")
    except ModuleNotFoundError:
        pytest.fail("scripts.run_real_llm_e2e must provide an explicit key guard")

    with pytest.raises(RuntimeError, match="DEEPSEEK_API_KEY"):
        module.require_deepseek_api_key({})

    assert module.require_deepseek_api_key({"DEEPSEEK_API_KEY": "test-only-key"}) == "test-only-key"
