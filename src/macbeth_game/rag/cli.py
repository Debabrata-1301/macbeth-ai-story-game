"""Explicit local-only corpus ingestion, index building, and search commands."""

import argparse
import os
import tempfile
from pathlib import Path

from macbeth_game.core.settings import Settings
from macbeth_game.rag.documents import ChunkManifest, PDFExtractionError, extract_pdf, file_sha256
from macbeth_game.rag.embeddings import EmbeddingError, OllamaEmbeddingClient
from macbeth_game.rag.pipeline import ingest_pdf
from macbeth_game.rag.retriever import RAGRetriever, RetrievalError
from macbeth_game.rag.vector_store import FAISSVectorStore, VectorStoreError


def _settings() -> Settings:
    return Settings()


def _write_manifest(path: Path, manifest: ChunkManifest) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(manifest.model_dump_json(indent=2))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    finally:
        Path(temporary_name).unlink(missing_ok=True)


def _print_report(extraction, manifest_path: Path | None = None) -> None:
    report = extraction.inspection
    print(f"Source: {report.source_path}")
    print(f"Pages: {report.page_count}; pages with extractable text: {report.pages_with_text}")
    print(f"Extracted characters: {report.extracted_char_count:,}")
    print(f"Likely scanned pages: {report.likely_scanned_pages or 'none detected'}")
    if manifest_path:
        print(f"Stable chunks: {manifest_path}")
    for warning in report.warnings:
        print(f"Warning: {warning}")


def ingest_main() -> None:
    settings = _settings()
    parser = argparse.ArgumentParser(description="Extract and chunk the local Macbeth PDF; no embeddings are generated.")
    parser.add_argument("--source", type=Path, default=settings.pdf_source_path)
    parser.add_argument("--output", type=Path, default=settings.rag_chunks_path)
    parser.add_argument("--chunk-size", type=int, default=settings.rag_chunk_size)
    parser.add_argument("--overlap", type=int, default=settings.rag_chunk_overlap)
    parser.add_argument("--inspect-only", action="store_true", help="inspect PDF text without writing chunks")
    args = parser.parse_args()
    try:
        if args.inspect_only:
            extraction = extract_pdf(args.source, settings.rag_scanned_page_char_threshold)
            _print_report(extraction)
            return
        extraction, manifest = ingest_pdf(args.source, args.chunk_size, args.overlap,
                                          settings.rag_scanned_page_char_threshold)
        if not manifest.chunks:
            raise PDFExtractionError("No non-empty text chunks were extracted; index was not changed.")
        _write_manifest(args.output, manifest)
        _print_report(extraction, args.output)
        print(f"Chunk count: {len(manifest.chunks)}")
    except (PDFExtractionError, OSError, ValueError) as exc:
        parser.error(str(exc))


def build_index_main() -> None:
    settings = _settings()
    parser = argparse.ArgumentParser(description="Embed local chunks with Ollama and build the local FAISS index.")
    parser.add_argument("--chunks", type=Path, default=settings.rag_chunks_path)
    parser.add_argument("--index-dir", type=Path, default=settings.faiss_index_dir)
    parser.add_argument("--metadata", type=Path, default=settings.rag_metadata_path)
    parser.add_argument("--model", default=settings.embedding_model)
    parser.add_argument("--batch-size", type=int, default=settings.embedding_batch_size)
    args = parser.parse_args()
    try:
        manifest = ChunkManifest.model_validate_json(args.chunks.read_text(encoding="utf-8"))
        for source_name, expected_checksum in manifest.source_checksums.items():
            if source_name == settings.pdf_source_path.name and settings.pdf_source_path.is_file():
                actual = file_sha256(settings.pdf_source_path)
                if actual != expected_checksum:
                    raise ValueError("Source PDF changed since ingestion; rerun the ingest command.")
        if not manifest.chunks:
            raise ValueError("Chunk manifest is empty; ingest the PDF first.")
        if args.batch_size < 1:
            raise ValueError("batch size must be positive")
        embedder = OllamaEmbeddingClient(settings.ollama_base_url, args.model,
                                         settings.ollama_timeout_seconds,
                                         keep_alive=settings.ollama_keep_alive)
        vectors: list[list[float]] = []
        for start in range(0, len(manifest.chunks), args.batch_size):
            batch = manifest.chunks[start:start + args.batch_size]
            vectors.extend(embedder.embed_documents([chunk.text for chunk in batch]))
            print(f"Embedded {min(start + len(batch), len(manifest.chunks))}/{len(manifest.chunks)} chunks")
        store = FAISSVectorStore(args.index_dir, args.metadata)
        metadata = store.build(manifest.chunks, vectors, args.model)
        print(f"Built {len(manifest.chunks)} vectors ({metadata.vector_dimension} dimensions) in {args.index_dir}")
        print(f"Metadata: {args.metadata}; model: {args.model}; metric: {metadata.metric}")
    except (OSError, ValueError, EmbeddingError, VectorStoreError) as exc:
        parser.error(str(exc))


def search_main() -> None:
    settings = _settings()
    parser = argparse.ArgumentParser(description="Search the local Macbeth FAISS index using local Ollama embeddings.")
    parser.add_argument("query", help="Natural-language question or search phrase")
    parser.add_argument("--top-k", type=int, default=settings.rag_default_top_k)
    parser.add_argument("--index-dir", type=Path, default=settings.faiss_index_dir)
    parser.add_argument("--metadata", type=Path, default=settings.rag_metadata_path)
    parser.add_argument("--model", default=settings.embedding_model)
    args = parser.parse_args()
    try:
        embedder = OllamaEmbeddingClient(settings.ollama_base_url, args.model,
                                         settings.ollama_timeout_seconds,
                                         keep_alive=settings.ollama_keep_alive)
        retriever = RAGRetriever(embedder, FAISSVectorStore(args.index_dir, args.metadata))
        result = retriever.retrieve(args.query, args.top_k)
        for number, passage in enumerate(result.passages, start=1):
            location = ", ".join(value for value in (passage.act_id, passage.scene_id,
                                                       f"page {passage.page_start}" if passage.page_start else None)
                                  if value) or "location unknown"
            print(f"[{number}] score={passage.score:.4f} {passage.source_filename} ({location})")
            print(passage.text)
            print()
        if not result.passages:
            print("No matching passages.")
    except (OSError, ValueError, EmbeddingError, RetrievalError, VectorStoreError) as exc:
        parser.error(str(exc))
