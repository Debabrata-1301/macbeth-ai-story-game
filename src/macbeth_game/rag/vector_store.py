"""Persistent FAISS cosine index with JSON metadata and validated atomic rebuilds."""

import json
import os
import shutil
import subprocess
import tempfile
from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from macbeth_game.rag.documents import DocumentChunk


class VectorStoreError(RuntimeError):
    """The local FAISS index is absent, corrupt, or incompatible."""


class IndexUnavailable(VectorStoreError):
    pass


class IndexMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: int = 1
    embedding_model: str = Field(min_length=1)
    vector_dimension: int = Field(gt=0)
    metric: str = "cosine"
    vector_ids: list[int]
    chunks: list[DocumentChunk]
    source_checksums: dict[str, str]
    index_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def _require_faiss_numpy():
    try:
        import faiss
        import numpy as np
    except ImportError as exc:
        raise VectorStoreError("FAISS retrieval requires optional dependencies: pip install -e '.[rag]'") from exc
    return faiss, np


def _sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _inherit_windows_permissions(path: Path) -> None:
    """Reset private tempfile ACLs so published artifacts inherit their parent ACL."""
    if os.name != "nt":
        return
    command = ["icacls", str(path), "/reset", "/C"]
    if path.is_dir():
        command.append("/T")
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise VectorStoreError(f"Could not apply inherited Windows permissions to staged RAG files: {result.stderr.strip()}")


class FAISSVectorStore:
    INDEX_FILENAME = "index.faiss"
    METADATA_FILENAME = "metadata.json"

    def __init__(self, index_directory: Path | str, metadata_path: Path | str | None = None):
        self.index_directory = Path(index_directory)
        self.metadata_path = Path(metadata_path) if metadata_path is not None else None
        if (self.metadata_path is not None
                and self.metadata_path.parent.resolve() != self.index_directory.resolve()
                and self.metadata_path.parent.resolve().is_relative_to(self.index_directory.resolve())):
            raise ValueError("metadata_path must be beside or outside the FAISS index directory")

    def _metadata_path_for(self, directory: Path) -> Path:
        if directory == self.index_directory and self.metadata_path is not None:
            return self.metadata_path
        filename = self.metadata_path.name if self.metadata_path is not None else self.METADATA_FILENAME
        return directory / filename

    def _load_directory(self, directory: Path):
        faiss, _np = _require_faiss_numpy()
        index_path = directory / self.INDEX_FILENAME
        metadata_path = self._metadata_path_for(directory)
        if not index_path.is_file() or not metadata_path.is_file():
            raise IndexUnavailable(f"No complete RAG index found in {directory}; build it first.")
        try:
            metadata = IndexMetadata.model_validate_json(metadata_path.read_text(encoding="utf-8"))
            index_hash = _sha256(index_path)
            if metadata.index_sha256 != index_hash:
                raise VectorStoreError("FAISS index checksum does not match its metadata")
            index = faiss.read_index(str(index_path))
        except VectorStoreError:
            raise
        except (OSError, RuntimeError, ValueError, ValidationError, json.JSONDecodeError) as exc:
            raise VectorStoreError(f"Could not load RAG index from {directory}: {exc}") from exc
        if metadata.schema_version != 1:
            raise VectorStoreError(f"Unsupported RAG metadata schema: {metadata.schema_version}")
        if metadata.metric != "cosine":
            raise VectorStoreError(f"Unsupported vector metric: {metadata.metric}")
        if index.metric_type != faiss.METRIC_INNER_PRODUCT:
            raise VectorStoreError("FAISS index metric does not match normalized cosine metadata")
        if index.d != metadata.vector_dimension or index.ntotal != len(metadata.chunks):
            raise VectorStoreError("FAISS dimensions/count do not match metadata")
        if len(metadata.vector_ids) != len(metadata.chunks) or len(set(metadata.vector_ids)) != len(metadata.vector_ids):
            raise VectorStoreError("FAISS vector ID mapping is invalid")
        if len({chunk.chunk_id for chunk in metadata.chunks}) != len(metadata.chunks):
            raise VectorStoreError("Chunk metadata contains duplicate stable IDs")
        if not metadata.chunks:
            raise VectorStoreError("RAG index contains no chunks")
        if not isinstance(index, faiss.IndexIDMap):
            raise VectorStoreError("FAISS index does not contain an explicit vector ID map")
        actual_ids = [int(value) for value in faiss.vector_to_array(index.id_map)]
        if actual_ids != metadata.vector_ids:
            raise VectorStoreError("FAISS stored vector IDs do not match the metadata mapping")
        expected_checksums = {chunk.source_filename: chunk.source_checksum for chunk in metadata.chunks}
        if metadata.source_checksums != expected_checksums:
            raise VectorStoreError("Source checksum metadata does not match stored chunks")
        return index, metadata

    def build(self, chunks: list[DocumentChunk], embeddings: list[list[float]],
              embedding_model: str) -> IndexMetadata:
        faiss, np = _require_faiss_numpy()
        if not chunks:
            raise VectorStoreError("Cannot build an index with no document chunks")
        if len(chunks) != len(embeddings):
            raise VectorStoreError("Chunk and embedding counts do not match")
        if len({chunk.chunk_id for chunk in chunks}) != len(chunks):
            raise VectorStoreError("Chunk IDs must be unique")
        checksums_by_source: dict[str, set[str]] = {}
        for chunk in chunks:
            checksums_by_source.setdefault(chunk.source_filename, set()).add(chunk.source_checksum)
        if any(len(checksums) != 1 for checksums in checksums_by_source.values()):
            raise VectorStoreError("Chunks from a source file must share one source checksum")
        matrix = np.asarray(embeddings, dtype=np.float32)
        if matrix.ndim != 2 or matrix.shape[0] != len(chunks) or matrix.shape[1] == 0:
            raise VectorStoreError("Embedding matrix has an invalid shape")
        if not np.isfinite(matrix).all():
            raise VectorStoreError("Embedding matrix contains NaN or infinite values")
        norms = np.linalg.norm(matrix, axis=1)
        if np.any(norms == 0):
            raise VectorStoreError("Cannot normalize a zero-length embedding")
        matrix /= norms[:, None]
        dimension = int(matrix.shape[1])
        index = faiss.IndexIDMap2(faiss.IndexFlatIP(dimension))
        vector_ids = np.arange(len(chunks), dtype=np.int64)
        index.add_with_ids(matrix, vector_ids)

        parent = self.index_directory.parent
        parent.mkdir(parents=True, exist_ok=True)
        scratch = Path(tempfile.mkdtemp(prefix=f".{self.index_directory.name}.build-", dir=parent))
        backup = parent / f".{self.index_directory.name}.backup-{uuid4().hex}"
        metadata_path = self.metadata_path
        if metadata_path is not None:
            metadata_path.parent.mkdir(parents=True, exist_ok=True)
        metadata_stage: Path | None = None
        metadata_backup = (metadata_path.with_name(f".{metadata_path.name}.backup-{uuid4().hex}")
                           if metadata_path is not None else None)
        had_old = False
        had_old_metadata = False
        installed_new = False
        try:
            index_path = scratch / self.INDEX_FILENAME
            faiss.write_index(index, str(index_path))
            with index_path.open("r+b") as handle:
                handle.flush()
                os.fsync(handle.fileno())
            metadata = IndexMetadata(
                embedding_model=embedding_model, vector_dimension=dimension,
                metric="cosine", vector_ids=list(range(len(chunks))), chunks=chunks,
                source_checksums={chunk.source_filename: chunk.source_checksum for chunk in chunks},
                index_sha256=_sha256(index_path),
            )
            scratch_metadata = self._metadata_path_for(scratch)
            _atomic_json(scratch_metadata, metadata.model_dump(mode="json"))
            # Do not touch the current valid index until the replacement fully reloads.
            self._load_directory(scratch)
            _inherit_windows_permissions(scratch)
            external_metadata = metadata_path is not None and metadata_path.parent.resolve() != self.index_directory.resolve()
            if external_metadata:
                fd, stage_name = tempfile.mkstemp(prefix=f".{metadata_path.name}.build-", dir=metadata_path.parent)
                metadata_stage = Path(stage_name)
                with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                    json.dump(metadata.model_dump(mode="json"), handle, ensure_ascii=False, indent=2)
                    handle.flush()
                    os.fsync(handle.fileno())
                _inherit_windows_permissions(metadata_stage)
            try:
                if self.index_directory.exists():
                    self.index_directory.rename(backup)
                    had_old = True
                if external_metadata and metadata_path.exists():
                    metadata_path.rename(metadata_backup)
                    had_old_metadata = True
                scratch.rename(self.index_directory)
                installed_new = True
                if external_metadata:
                    os.replace(metadata_stage, metadata_path)
                    metadata_stage = None
            except Exception:
                if metadata_path is not None and external_metadata:
                    metadata_path.unlink(missing_ok=True)
                    if had_old_metadata and metadata_backup.exists():
                        metadata_backup.rename(metadata_path)
                if installed_new and self.index_directory.exists():
                    shutil.rmtree(self.index_directory, ignore_errors=True)
                if had_old and backup.exists():
                    backup.rename(self.index_directory)
                raise
            if had_old:
                shutil.rmtree(backup, ignore_errors=True)
            if had_old_metadata:
                metadata_backup.unlink(missing_ok=True)
            return metadata
        except VectorStoreError:
            raise
        except Exception as exc:
            raise VectorStoreError(f"Could not build local FAISS index: {exc}") from exc
        finally:
            if metadata_stage is not None:
                metadata_stage.unlink(missing_ok=True)
            if scratch.exists():
                shutil.rmtree(scratch, ignore_errors=True)

    def search(self, embedding: list[float], top_k: int = 4,
               embedding_model: str | None = None, *, act_id: str | None = None,
               scene_id: str | None = None) -> list[tuple[DocumentChunk, float]]:
        if top_k < 1:
            raise ValueError("top_k must be at least 1")
        if scene_id and not act_id:
            raise ValueError("act_id is required when scene_id is supplied")
        _faiss, np = _require_faiss_numpy()
        index, metadata = self._load_directory(self.index_directory)
        if embedding_model and embedding_model != metadata.embedding_model:
            raise VectorStoreError(
                f"Query embedding model {embedding_model!r} does not match index model {metadata.embedding_model!r}"
            )
        query = np.asarray(embedding, dtype=np.float32)
        if query.ndim != 1 or query.size != metadata.vector_dimension:
            raise VectorStoreError(f"Query embedding must have dimension {metadata.vector_dimension}")
        if not np.isfinite(query).all():
            raise VectorStoreError("Query embedding contains NaN or infinite values")
        norm = float(np.linalg.norm(query))
        if norm == 0:
            raise VectorStoreError("Query embedding has zero length")
        query /= norm
        # The local corpus is small; search all vectors when filtering so a matching
        # Shakespeare section is not lost behind semantically similar other acts.
        search_count = index.ntotal if act_id else min(top_k, index.ntotal)
        scores, ids = index.search(query.reshape(1, -1), search_count)
        chunks_by_id = {vector_id: chunk for vector_id, chunk in zip(metadata.vector_ids, metadata.chunks)}
        results: list[tuple[DocumentChunk, float]] = []
        seen: set[str] = set()
        for raw_score, raw_id in zip(scores[0], ids[0]):
            vector_id = int(raw_id)
            chunk = chunks_by_id.get(vector_id)
            if chunk is None or chunk.chunk_id in seen or not float(raw_score) > -1.0e10:
                continue
            if act_id and (chunk.act_id != act_id or (scene_id and chunk.scene_id != scene_id)):
                continue
            seen.add(chunk.chunk_id)
            results.append((chunk, float(raw_score)))
        return results

    def load_metadata(self) -> IndexMetadata:
        return self._load_directory(self.index_directory)[1]
