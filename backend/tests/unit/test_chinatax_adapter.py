import pytest

from backend.app.domain.documents import DocumentVersionStatus, PolicyStatus
from backend.app.ingestion.adapters.chinatax import ChinataxAdapterError, normalize_chinatax_record


def test_chinatax_adapter_preserves_source_fields_and_governance_status() -> None:
    record = normalize_chinatax_record(
        {
            "title": "关于示例税收政策的公告",
            "content": "第一条 示例政策内容",
            "document_number": "国家税务总局公告2025年第1号",
            "aging": "部分失效",
            "issuing_department": "国家税务总局",
            "written_date": "2025-01-01",
            "url": "https://example.test/policy",
        }
    )

    assert record.status is DocumentVersionStatus.ACTIVE_WITH_WARNING
    assert record.policy_status is PolicyStatus.PARTIALLY_EFFECTIVE
    assert record.source_dataset == "salpt/chinatax-policy-corpus"
    assert record.sha256


def test_chinatax_adapter_rejects_missing_required_fields_instead_of_guessing() -> None:
    with pytest.raises(ChinataxAdapterError, match="content"):
        normalize_chinatax_record({"title": "缺少正文"})
