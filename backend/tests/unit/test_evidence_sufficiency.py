from backend.app.domain.documents import DocumentVersionStatus
from backend.app.harness.citations import Evidence
from backend.app.harness.evidence_sufficiency import (
    ConstraintStatus,
    EvidenceStatus,
    EvidenceSufficiencyVerifier,
    VerifierDecision,
)


def _evidence(*, chunk_id: str, title: str, text: str = "政策正文。") -> Evidence:
    return Evidence(
        chunk_id=chunk_id,
        document_id=f"document-{chunk_id}",
        version_id=f"version-{chunk_id}",
        title=title,
        department="dept_tax",
        status=DocumentVersionStatus.ACTIVE,
        text=text,
    )


def test_verifier_accepts_an_exact_policy_identity_with_required_batch() -> None:
    result = EvidenceSufficiencyVerifier().verify(
        query="请依据《2024年车辆购置税目录（第十九批）》说明该政策的主要规定。",
        evidence=[
            _evidence(
                chunk_id="chunk-match",
                title="2024年车辆购置税目录（第十九批）",
                text="第十九批目录自2024年起执行。",
            )
        ],
    )

    assert result.decision is VerifierDecision.ANSWER
    assert result.evidence_status is EvidenceStatus.SUFFICIENT
    assert result.supporting_chunk_ids == ["chunk-match"]
    assert result.constraints.policy_identity is ConstraintStatus.SUPPORTED
    assert result.constraints.version_batch_ordinal is ConstraintStatus.SUPPORTED


def test_verifier_abstains_when_only_a_neighboring_policy_is_retrieved() -> None:
    result = EvidenceSufficiencyVerifier().verify(
        query="请依据《2018年企业所得税月（季）度预缴纳税申报表》说明主要规定。",
        evidence=[
            _evidence(
                chunk_id="chunk-neighbor",
                title="关于优化企业所得税预缴纳税申报有关事项的公告",
                text="为优化企业所得税预缴纳税申报事项，现公告如下。",
            )
        ],
    )

    assert result.decision is VerifierDecision.ABSTAIN
    assert result.evidence_status is EvidenceStatus.INSUFFICIENT
    assert result.reason_code == "POLICY_IDENTITY_UNSUPPORTED"
    assert "policy_identity" in result.unsupported_constraints
    assert result.constraints.year_date is ConstraintStatus.UNSUPPORTED


def test_verifier_maps_missing_policy_identity_to_ambiguous_abstain() -> None:
    result = EvidenceSufficiencyVerifier().verify(
        query="请说明企业所得税政策的主要规定。",
        evidence=[
            _evidence(
                chunk_id="chunk-topic",
                title="企业所得税优惠政策公告",
                text="符合条件的企业可以享受企业所得税优惠。",
            )
        ],
    )

    assert result.decision is VerifierDecision.ABSTAIN
    assert result.evidence_status is EvidenceStatus.AMBIGUOUS
    assert result.reason_code == "POLICY_IDENTITY_AMBIGUOUS"
    assert result.constraints.policy_identity is ConstraintStatus.AMBIGUOUS


def test_verifier_requires_active_evidence() -> None:
    archived = _evidence(chunk_id="chunk-archived", title="2024年车辆购置税目录（第十九批）")
    archived = Evidence(
        chunk_id=archived.chunk_id,
        document_id=archived.document_id,
        version_id=archived.version_id,
        title=archived.title,
        department=archived.department,
        status=DocumentVersionStatus.ARCHIVED,
        text=archived.text,
    )

    result = EvidenceSufficiencyVerifier().verify(
        query="请依据《2024年车辆购置税目录（第十九批）》说明该政策的主要规定。",
        evidence=[archived],
    )

    assert result.decision is VerifierDecision.ABSTAIN
    assert result.evidence_status is EvidenceStatus.INSUFFICIENT
    assert result.reason_code == "NO_ACTIVE_EVIDENCE"


def test_verifier_rejects_an_unsupported_extra_fact_constraint() -> None:
    result = EvidenceSufficiencyVerifier().verify(
        query="请依据《2024年车辆购置税目录（第十九批）》说明是否适用于2029年特别试点。",
        evidence=[
            _evidence(
                chunk_id="chunk-policy",
                title="2024年车辆购置税目录（第十九批）",
                text="第十九批目录自2024年起执行。",
            )
        ],
    )

    assert result.decision is VerifierDecision.ABSTAIN
    assert result.evidence_status is EvidenceStatus.INSUFFICIENT
    assert result.reason_code == "CORE_FACT_UNSUPPORTED"
    assert result.constraints.core_fact is ConstraintStatus.UNSUPPORTED
