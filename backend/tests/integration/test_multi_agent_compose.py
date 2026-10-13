"""Real HTTP validation for the opt-in V1.1 Compose multi-agent profile.

This test deliberately has no fake retriever, in-memory repository, or mocked
department client.  It is opt-in because it requires the real Compose profile,
the seeded V1.1 fixture, MongoDB, OpenSearch, Milvus, Redis and Pi Runtime.
The Pi service may be configured with its deterministic ``faux`` provider, but
all department retrieval and parent/child trace assertions are real services.
"""

from __future__ import annotations

import os
from uuid import uuid4

import httpx
import pytest


def _configuration() -> tuple[str, str, str]:
    base_url = os.getenv("V11_MULTI_AGENT_BASE_URL")
    if not base_url:
        pytest.skip("V1.1 Compose multi-agent profile is not configured")
    return (
        base_url.rstrip("/"),
        os.getenv("V11_MULTI_AGENT_EMAIL", "user@example.local"),
        os.getenv("V11_MULTI_AGENT_PASSWORD", "demo-user"),
    )


def _login(client: httpx.Client, email: str, password: str) -> dict[str, str]:
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    response.raise_for_status()
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _chat(
    client: httpx.Client, *, headers: dict[str, str], query: str, trace_id: str
) -> dict[str, object]:
    response = client.post(
        "/api/v1/chat",
        headers={**headers, "X-Trace-Id": trace_id},
        json={"query": query, "session_id": trace_id},
    )
    response.raise_for_status()
    return response.json()


@pytest.mark.integration
def test_v11_multi_agent_profile_uses_real_scoped_retrieval_and_trace_hierarchy() -> None:
    """MA-01/02/03/08 against the actual Compose services and fixture corpus."""

    base_url, email, password = _configuration()
    with httpx.Client(base_url=base_url, timeout=45) as client:
        headers = _login(client, email, password)

        single_trace_id = f"v11-it-single-{uuid4()}"
        single = _chat(
            client,
            headers=headers,
            query="税务登记怎么办理？",
            trace_id=single_trace_id,
        )
        assert single["status"] == "SUCCESS"
        assert single["orchestration"] == {
            "mode": "single",
            "requested_departments": ["tax"],
            "completed_departments": ["tax"],
            "failed_departments": [],
            "partial": False,
            "fanout": 1,
        }
        assert single["citations"]
        assert {citation["department"] for citation in single["citations"]} == {"tax"}

        cross_trace_id = f"v11-it-cross-{uuid4()}"
        cross = _chat(
            client,
            headers=headers,
            query="税务登记、社保参保和住房公积金如何办理？",
            trace_id=cross_trace_id,
        )
        assert cross["status"] == "SUCCESS"
        assert cross["orchestration"]["mode"] == "multi"
        assert cross["orchestration"]["fanout"] == 3
        assert cross["orchestration"]["partial"] is False
        assert {citation["department"] for citation in cross["citations"]} == {
            "tax",
            "hrss",
            "housing",
        }

        root = client.get(f"/api/v1/traces/{cross_trace_id}", headers=headers)
        root.raise_for_status()
        root_trace = root.json()
        assert root_trace["execution_mode"] == "multi_agent"
        assert root_trace["selected_departments"] == ["housing", "hrss", "tax"]
        assert len(root_trace["child_trace_ids"]) == 3
        assert root_trace["final_verification"]["passed"] is True

        children = []
        for child_trace_id in root_trace["child_trace_ids"]:
            child = client.get(f"/api/v1/traces/{child_trace_id}", headers=headers)
            child.raise_for_status()
            children.append(child.json())
        assert {child["dept_id"] for child in children} == {"tax", "hrss", "housing"}
        assert all(child["parent_trace_id"] == cross_trace_id for child in children)
        assert all(
            child["retrieval_metadata"]["canonical_candidate_count"] >= 1
            for child in children
        )
