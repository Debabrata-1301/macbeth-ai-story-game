"""Metadata-aware dramatic-text chunking with stable content-derived IDs."""

import re
from hashlib import sha256

from macbeth_game.rag.documents import DocumentChunk, PDFExtraction


def _split_long_unit(text: str, limit: int) -> list[str]:
    if len(text) <= limit:
        return [text]
    sentences = re.split(r"(?<=[.!?])\s+", text)
    result: list[str] = []
    current = ""
    for sentence in sentences:
        if len(sentence) > limit:
            words = sentence.split()
            word_part = ""
            for word in words:
                if len(word) > limit:
                    if word_part:
                        result.append(word_part)
                        word_part = ""
                    result.extend(word[pos:pos + limit] for pos in range(0, len(word), limit))
                elif word_part and len(word_part) + len(word) + 1 > limit:
                    result.append(word_part)
                    word_part = word
                else:
                    word_part = f"{word_part} {word}".strip()
            if word_part:
                result.append(word_part)
            continue
        if current and len(current) + len(sentence) + 1 > limit:
            result.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        result.append(current)
    return result


def _overlap_tail(text: str, overlap: int) -> str:
    if overlap <= 0:
        return ""
    tail = text[-overlap:]
    # Begin at a word boundary where possible to avoid embedding a partial word.
    boundary = tail.find(" ")
    return tail[boundary + 1:] if boundary >= 0 else tail


def chunk_extraction(extraction: PDFExtraction, chunk_size: int = 1200,
                     chunk_overlap: int = 180) -> list[DocumentChunk]:
    if chunk_size < 1 or chunk_overlap < 0 or chunk_overlap >= chunk_size:
        raise ValueError("chunk_size must be positive and chunk_overlap smaller than chunk_size")
    source = extraction.inspection.source_filename
    checksum = extraction.inspection.source_checksum
    chunks: list[DocumentChunk] = []

    for page in extraction.pages:
        for section in page.sections:
            units: list[str] = []
            for paragraph in re.split(r"\n\s*\n", section.text):
                normalized = paragraph.strip()
                if normalized:
                    units.extend(_split_long_unit(normalized, chunk_size))
            buffer = ""

            def emit(text: str, page_section) -> None:
                text = text.strip()
                if not text:
                    return
                index = len(chunks)
                stable_seed = f"{checksum}|{source}|{index}|{page_section.page_number}|{page_section.act_id}|{page_section.scene_id}|{text}"
                chunk_id = sha256(stable_seed.encode("utf-8")).hexdigest()[:32]
                chunks.append(DocumentChunk(
                    chunk_id=chunk_id, source_filename=source, source_checksum=checksum,
                    page_start=page_section.page_number, page_end=page_section.page_number,
                    act_id=page_section.act_id, scene_id=page_section.scene_id,
                    chunk_index=index, text=text,
                ))

            for unit in units:
                candidate = f"{buffer}\n\n{unit}" if buffer else unit
                if len(candidate) <= chunk_size:
                    buffer = candidate
                    continue
                emit(buffer, section)
                overlap = _overlap_tail(buffer, chunk_overlap)
                if len(overlap) + len(unit) + (2 if overlap else 0) > chunk_size:
                    overlap = overlap[-max(0, chunk_size - len(unit) - 2):] if chunk_size > len(unit) + 2 else ""
                buffer = f"{overlap}\n\n{unit}" if overlap else unit
            emit(buffer, section)
    return chunks


def stable_chunk_ids(chunks: list[DocumentChunk]) -> bool:
    ids = [chunk.chunk_id for chunk in chunks]
    return len(ids) == len(set(ids))
