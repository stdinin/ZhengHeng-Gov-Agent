import pytest
from pydantic import BaseModel

from backend.app.llm.fake import FakeLLM, FakeLLMExhausted


class RouteCandidate(BaseModel):
    department_ids: list[str]


async def test_fake_llm_returns_schema_validated_fixture_by_call_name() -> None:
    llm = FakeLLM(structured_fixtures={"route": {"department_ids": ["dept_tax"]}})

    result = await llm.structured(
        system="route policies", user="增值税优惠", schema=RouteCandidate, fixture_name="route"
    )

    assert result == RouteCandidate(department_ids=["dept_tax"])


async def test_fake_llm_never_invents_an_unconfigured_response() -> None:
    llm = FakeLLM()

    with pytest.raises(FakeLLMExhausted, match="missing"):
        await llm.text(system="answer", user="question", fixture_name="answer")
