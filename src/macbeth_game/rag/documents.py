"""Typed source, page, chunk, and ingestion report contracts."""

import re
from hashlib import sha256
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator


class RAGModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PageSection(RAGModel):
    page_number: int = Field(ge=1)
    act_id: str | None = None
    scene_id: str | None = None
    text: str = Field(min_length=1)


class ExtractedPage(RAGModel):
    page_number: int = Field(ge=1)
    sections: list[PageSection] = Field(default_factory=list)
    text_char_count: int = Field(ge=0)
    likely_scanned: bool = False


class DocumentChunk(RAGModel):
    chunk_id: str = Field(min_length=1, max_length=100)
    source_filename: str = Field(min_length=1)
    source_checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    page_start: int | None = Field(default=None, ge=1)
    page_end: int | None = Field(default=None, ge=1)
    act_id: str | None = None
    scene_id: str | None = None
    chunk_index: int = Field(ge=0)
    text: str = Field(min_length=1)
    metadata: dict[str, str | int | float | bool | None] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_page_range(self):
        if self.page_start and self.page_end and self.page_end < self.page_start:
            raise ValueError("page_end must be greater than or equal to page_start")
        return self


class ChunkManifest(RAGModel):
    schema_version: int = 1
    source_checksums: dict[str, str]
    chunks: list[DocumentChunk]
    chunk_size: int = Field(gt=0)
    chunk_overlap: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_manifest(self):
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("chunk_overlap must be smaller than chunk_size")
        if len({chunk.chunk_id for chunk in self.chunks}) != len(self.chunks):
            raise ValueError("chunk IDs must be unique")
        observed: dict[str, str] = {}
        for chunk in self.chunks:
            observed[chunk.source_filename] = chunk.source_checksum
        if observed != self.source_checksums:
            raise ValueError("manifest source checksums must match chunk provenance")
        return self


class PDFInspection(RAGModel):
    source_path: str
    source_filename: str
    source_checksum: str
    page_count: int = Field(ge=0)
    extracted_char_count: int = Field(ge=0)
    pages_with_text: int = Field(ge=0)
    likely_scanned_pages: list[int] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class PDFExtraction(RAGModel):
    inspection: PDFInspection
    pages: list[ExtractedPage]


class RetrievalPassage(RAGModel):
    chunk_id: str
    text: str
    source_filename: str
    source_checksum: str
    page_start: int | None = None
    page_end: int | None = None
    act_id: str | None = None
    scene_id: str | None = None
    score: float = Field(description="Cosine similarity score; not a probability.")


class RetrievalResult(RAGModel):
    query: str
    passages: list[RetrievalPassage]
    embedding_model: str
    vector_dimension: int = Field(gt=0)
    metric: str = "cosine"
    scope_used: str = "global"
    minimum_relevance: float = Field(default=0.0, ge=-1.0, le=1.0)


class PDFExtractionError(RuntimeError):
    """The local PDF could not be read or yielded inadequate text."""


def file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def clean_pdf_text(text: str) -> str:
    """Normalize whitespace while preserving line and paragraph boundaries."""
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\u00a0", " ")
    text = re.sub(r"[\t\f\v ]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


_ROMAN = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5}


def _act_scene_sections(page_text: str, page_number: int, current_act: str | None,
                        current_scene: str | None) -> tuple[list[PageSection], str | None, str | None]:
    act_re = re.compile(r"^ACT\s+(I{1,3}|IV|V|\d+)\b", re.IGNORECASE)
    scene_re = re.compile(r"^SCENE\s+(I{1,3}|IV|V|\d+)\b", re.IGNORECASE)
    sections: list[PageSection] = []
    active_lines: list[str] = []

    def flush() -> None:
        text = clean_pdf_text("\n".join(active_lines))
        if text:
            sections.append(PageSection(page_number=page_number, act_id=current_act,
                                        scene_id=current_scene, text=text))
        active_lines.clear()

    for line in page_text.splitlines():
        normalized = line.strip().upper().rstrip(".: ")
        act_match = act_re.match(normalized)
        scene_match = scene_re.match(normalized)
        if act_match:
            flush()
            raw = act_match.group(1).upper()
            current_act = f"act_{_ROMAN.get(raw, raw)}"
            current_scene = None
        elif scene_match:
            flush()
            raw = scene_match.group(1).upper()
            current_scene = f"scene_{_ROMAN.get(raw, raw)}"
        active_lines.append(line)
    flush()
    return sections, current_act, current_scene


def extract_pdf(path: Path, scanned_page_char_threshold: int = 40) -> PDFExtraction:
    """Extract page-preserving text and report likely image-only pages; never performs OCR."""
    if not path.is_file():
        raise PDFExtractionError(f"PDF source does not exist: {path}")
    try:
        import pymupdf
    except ImportError as exc:
        raise PDFExtractionError("PDF extraction requires the optional RAG dependencies: pip install -e '.[rag]'") from exc
    checksum = file_sha256(path)
    try:
        document = pymupdf.open(path)
        if document.is_encrypted and not document.authenticate(""):
            document.close()
            raise PDFExtractionError("The PDF is encrypted and cannot be opened without a password")
        pages: list[ExtractedPage] = []
        current_act: str | None = None
        current_scene: str | None = None
        scanned: list[int] = []
        warnings: list[str] = []
        total_chars = 0
        pages_with_text = 0
        for page_number, page in enumerate(document, start=1):
            raw_text = page.get_text("text", sort=True)
            cleaned = clean_pdf_text(raw_text)
            total_chars += len(cleaned)
            if cleaned:
                pages_with_text += 1
            image_count = len(page.get_images(full=True))
            likely_scanned = len(cleaned) < scanned_page_char_threshold and image_count > 0
            if likely_scanned:
                scanned.append(page_number)
            sections, current_act, current_scene = _act_scene_sections(
                cleaned, page_number, current_act, current_scene)
            pages.append(ExtractedPage(page_number=page_number, sections=sections,
                                       text_char_count=len(cleaned), likely_scanned=likely_scanned))
        document.close()
    except PDFExtractionError:
        raise
    except Exception as exc:
        raise PDFExtractionError(f"Could not extract PDF {path}: {exc}") from exc
    if not pages or total_chars == 0:
        raise PDFExtractionError(f"PDF contains no extractable text: {path}. It may be scanned; OCR is not enabled.")
    if scanned:
        warnings.append(f"Likely scanned or text-poor pages: {', '.join(map(str, scanned))}; no OCR was run.")
    if total_chars < 200:
        warnings.append("Extracted text is unusually short; check whether the PDF is scanned or incomplete.")
    inspection = PDFInspection(source_path=str(path), source_filename=path.name,
                               source_checksum=checksum, page_count=len(pages),
                               extracted_char_count=total_chars, pages_with_text=pages_with_text,
                               likely_scanned_pages=scanned, warnings=warnings)
    return PDFExtraction(inspection=inspection, pages=pages)
