from backend.app.domain.documents import DocumentVersionStatus
from backend.app.harness.citations import CitationCheck, Evidence, render_cited_answer
from backend.app.harness.state import AnswerClaim


def test_citation_renderer_uses_only_active_evidence_and_stable_reference_ids() -> None:
    evidence = [
        Evidence(
            chunk_id="chunk_1",
            document_id="doc_1",
            version_id="ver_1",
            title="小规模纳税人增值税政策",
            department="税务",
            status=DocumentVersionStatus.ACTIVE,
            text="第一条：符合条件的小规模纳税人享受优惠。",
            source_url="https://example.test/policy",
        )
    ]

    answer, citations = render_cited_answer("根据现行政策，符合条件的主体可享受优惠。", evidence)

    assert answer.endswith("[C1]")
    assert citations[0].id == "C1"
    assert citations[0].chunk_id == "chunk_1"
    assert CitationCheck().validate(answer, citations, evidence).passed is True


def test_citation_check_rejects_archived_evidence_even_if_it_appears_in_answer() -> None:
    evidence = [
        Evidence(
            chunk_id="chunk_archived",
            document_id="doc_1",
            version_id="ver_old",
            title="已废止文件",
            department="税务",
            status=DocumentVersionStatus.ARCHIVED,
            text="旧规定",
        )
    ]

    result = CitationCheck().validate("旧规定 [C1]", [], evidence)

    assert result.passed is False
    assert "ARCHIVED" in result.warnings[0]


def test_citation_renderer_keeps_only_claim_referenced_evidence_with_stable_ids() -> None:
    evidence = [
        Evidence(
            chunk_id="chunk_1",
            document_id="doc_1",
            version_id="ver_1",
            title="不相关的现行文件",
            department="税务",
            status=DocumentVersionStatus.ACTIVE,
            text="第一份现行政策。",
        ),
        Evidence(
            chunk_id="chunk_2",
            document_id="doc_2",
            version_id="ver_2",
            title="实际支持结论的现行文件",
            department="税务",
            status=DocumentVersionStatus.ACTIVE,
            text="第二份现行政策。",
        ),
    ]
    claims = [AnswerClaim(text="结论由第二份文件支持。", citation_ids=["C2"])]

    answer, citations = render_cited_answer(
        "结论由第二份文件支持。",
        evidence,
        claims=claims,
    )

    assert answer.endswith("[C2]")
    assert "[C1]" not in answer
    assert [citation.id for citation in citations] == ["C2"]
    assert [citation.chunk_id for citation in citations] == ["chunk_2"]
    assert CitationCheck().validate(answer, citations, evidence, claims=claims).passed is True


def test_citation_check_rejects_document_numbers_absent_from_retrieved_evidence() -> None:
    evidence = [
        Evidence(
            chunk_id="chunk_1",
            document_id="doc_1",
            version_id="ver_1",
            title="增值税优惠公告",
            department="税务",
            status=DocumentVersionStatus.ACTIVE,
            text="符合条件的主体可以享受优惠。",
            document_number="示例〔2026〕1号",
        )
    ]
    claims = [AnswerClaim(text="依据伪造〔2026〕99号可享受优惠。", citation_ids=["C1"])]
    answer, citations = render_cited_answer(claims[0].text, evidence, claims=claims)

    result = CitationCheck().validate(answer, citations, evidence, claims=claims)

    assert result.passed is False
    assert any("document number" in warning.lower() for warning in result.warnings)


def test_citation_check_requires_warning_text_for_partially_effective_evidence() -> None:
    evidence = [
        Evidence(
            chunk_id="chunk_warning",
            document_id="doc_warning",
            version_id="ver_warning",
            title="部分有效文件",
            department="税务",
            status=DocumentVersionStatus.ACTIVE_WITH_WARNING,
            text="本文件仅部分条款仍有效。",
        )
    ]
    claims = [AnswerClaim(text="可以享受优惠。", citation_ids=["C1"])]
    answer, citations = render_cited_answer(claims[0].text, evidence, claims=claims)

    result = CitationCheck().validate(answer, citations, evidence, claims=claims)

    assert result.passed is False
    assert any("时效性警告" in warning for warning in result.warnings)
