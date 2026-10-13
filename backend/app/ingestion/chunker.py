import re
from dataclasses import dataclass

_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


@dataclass(frozen=True, slots=True)
class ChunkDraft:
    id: str
    document_id: str
    version_id: str
    ordinal: int
    text: str
    heading_path: list[str]
    char_start: int
    char_end: int


@dataclass(frozen=True, slots=True)
class _Section:
    text: str
    heading_path: list[str]
    char_start: int


def _sections(text: str) -> list[_Section]:
    sections: list[_Section] = []
    heading_path: list[str] = []
    current_lines: list[str] = []
    current_path: list[str] = []
    section_start = 0
    position = 0

    def flush() -> None:
        nonlocal current_lines, current_path, section_start
        value = "".join(current_lines)
        if value:
            sections.append(_Section(value, current_path, section_start))
        current_lines = []

    for line in text.splitlines(keepends=True):
        match = _HEADING.match(line.rstrip("\r\n"))
        if match:
            flush()
            level = len(match.group(1))
            title = match.group(2)
            heading_path = heading_path[: level - 1]
            heading_path.append(title)
            current_path = list(heading_path)
            section_start = position
        elif not current_lines:
            current_path = list(heading_path)
            section_start = position
        current_lines.append(line)
        position += len(line)
    flush()
    return sections


def chunk_text(
    *, document_id: str, version_id: str, text: str, max_chars: int = 1_000
) -> list[ChunkDraft]:
    if max_chars <= 0:
        raise ValueError("max_chars must be positive.")
    if not text:
        return []

    chunks: list[ChunkDraft] = []
    for section in _sections(text):
        for offset in range(0, len(section.text), max_chars):
            value = section.text[offset : offset + max_chars]
            if not value.strip():
                continue
            ordinal = len(chunks) + 1
            chunks.append(
                ChunkDraft(
                    id=f"chunk_{version_id}_{ordinal:04d}",
                    document_id=document_id,
                    version_id=version_id,
                    ordinal=ordinal,
                    text=value,
                    heading_path=list(section.heading_path),
                    char_start=section.char_start + offset,
                    char_end=section.char_start + offset + len(value),
                )
            )
    return chunks
