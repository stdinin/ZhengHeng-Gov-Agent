from backend.app.ingestion.chunker import chunk_text


def test_chunker_keeps_markdown_heading_provenance_and_deterministic_ids() -> None:
    text = "# 第一章\n总则内容。\n\n## 第一节\n甲条内容。\n\n## 第二节\n乙条内容。"

    first = chunk_text(document_id="doc_1", version_id="ver_1", text=text, max_chars=40)
    second = chunk_text(document_id="doc_1", version_id="ver_1", text=text, max_chars=40)

    assert [chunk.id for chunk in first] == [chunk.id for chunk in second]
    assert first[1].heading_path == ["第一章", "第一节"]
    assert all(chunk.document_id == "doc_1" and chunk.version_id == "ver_1" for chunk in first)


def test_chunker_splits_long_policy_text_without_losing_or_reordering_characters() -> None:
    text = "第一条：" + "甲" * 80

    chunks = chunk_text(document_id="doc_1", version_id="ver_1", text=text, max_chars=30)

    assert len(chunks) >= 3
    assert "".join(chunk.text for chunk in chunks) == text
    assert [chunk.ordinal for chunk in chunks] == list(range(1, len(chunks) + 1))
