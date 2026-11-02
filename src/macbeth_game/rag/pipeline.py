"""Corpus ingestion helpers shared by CLI commands and tests."""

from pathlib import Path

from macbeth_game.rag.chunker import chunk_extraction
from macbeth_game.rag.documents import ChunkManifest, PDFExtraction, extract_pdf


def ingest_pdf(path: Path, chunk_size: int = 1200, chunk_overlap: int = 180,
               scanned_page_char_threshold: int = 40) -> tuple[PDFExtraction, ChunkManifest]:
    extraction = extract_pdf(path, scanned_page_char_threshold=scanned_page_char_threshold)
    chunks = chunk_extraction(extraction, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    manifest = ChunkManifest(source_checksums={extraction.inspection.source_filename:
                                               extraction.inspection.source_checksum},
                             chunks=chunks, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    return extraction, manifest
