from __future__ import annotations

import json
from typing import TYPE_CHECKING

from backend.app.agents.models import DepartmentAgentDefinition

if TYPE_CHECKING:
    from backend.app.config import Settings


class DepartmentAgentRegistry:
    """Static-only registry; V1.1 deliberately has no dynamic agent creation path."""

    def __init__(self, definitions: list[DepartmentAgentDefinition]) -> None:
        agent_ids = [definition.agent_id for definition in definitions]
        department_ids = [definition.dept_id for definition in definitions]
        if len(agent_ids) != len(set(agent_ids)):
            raise ValueError("Department agent IDs must be unique.")
        if len(department_ids) != len(set(department_ids)):
            raise ValueError("Department IDs must map to one static agent.")
        self._definitions = tuple(definitions)

    def enabled_definitions(self) -> list[DepartmentAgentDefinition]:
        return [definition for definition in self._definitions if definition.enabled]

    def get_by_department(self, dept_id: str) -> DepartmentAgentDefinition | None:
        return next(
            (
                definition
                for definition in self._definitions
                if definition.dept_id == dept_id and definition.enabled
            ),
            None,
        )


def default_department_agent_registry() -> DepartmentAgentRegistry:
    """Small, reproducible demo topology. Helm/env overrides are added at composition time."""

    return DepartmentAgentRegistry(
        [
            DepartmentAgentDefinition(
                agent_id="tax-agent",
                dept_id="tax",
                display_name="Tax Department Agent",
                base_url="http://department-tax-agent:8000",
            ),
            DepartmentAgentDefinition(
                agent_id="hrss-agent",
                dept_id="hrss",
                display_name="Human Resources and Social Security Agent",
                base_url="http://department-hrss-agent:8000",
            ),
            DepartmentAgentDefinition(
                agent_id="housing-agent",
                dept_id="housing",
                display_name="Housing Department Agent",
                base_url="http://department-housing-agent:8000",
            ),
        ]
    )


def department_agent_registry_from_settings(settings: Settings) -> DepartmentAgentRegistry:
    """Read a static env/Helm JSON override before using the reproducible demo topology."""

    raw_definitions = settings.department_agents_json
    if not raw_definitions:
        configured_urls = {
            "tax": settings.department_agent_tax_url,
            "hrss": settings.department_agent_hrss_url,
            "housing": settings.department_agent_housing_url,
        }
        return DepartmentAgentRegistry(
            [
                definition.model_copy(
                    update={
                        "base_url": configured_urls[definition.dept_id],
                        # The static registry is topology-only.  Its per-agent
                        # deadline must still honour the deployment's bounded
                        # timeout setting instead of silently retaining the
                        # 12s model default.
                        "timeout_ms": settings.department_agent_timeout_ms,
                    }
                )
                for definition in default_department_agent_registry().enabled_definitions()
            ]
        )
    try:
        decoded = json.loads(raw_definitions)
    except json.JSONDecodeError as error:
        raise ValueError("DEPARTMENT_AGENTS_JSON must contain a JSON array.") from error
    if not isinstance(decoded, list):
        raise ValueError("DEPARTMENT_AGENTS_JSON must contain a JSON array.")
    return DepartmentAgentRegistry(
        [DepartmentAgentDefinition.model_validate(item) for item in decoded]
    )
