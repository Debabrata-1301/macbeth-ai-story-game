import base64
from hashlib import sha256
from itertools import pairwise
from pathlib import Path

import pymupdf
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from macbeth_game.core.settings import Settings
from macbeth_game.main import create_app
from macbeth_game.rag.chunker import chunk_extraction, stable_chunk_ids
from macbeth_game.rag.documents import (
    ChunkManifest,
    DocumentChunk,
    ExtractedPage,
    PageSection,
    PDFExtraction,
    PDFExtractionError,
    PDFInspection,
    extract_pdf,
)
from macbeth_game.rag.embeddings import EmbeddingError, OllamaEmbeddingClient, validate_embeddings
from macbeth_game.rag.retriever import RAGRetriever
from macbeth_game.rag.vector_store import FAISSVectorStore, IndexUnavailable, VectorStoreError


def _write_pdf(path: Path, pages: list[str]) -> Path:
    document = pymupdf.open()
    for text in pages:
        page = document.new_page()
        if text:
            page.insert_textbox(pymupdf.Rect(48, 48, 550, 780), text, fontsize=11)
    document.save(path)
    document.close()
    return path


def _chunk(index: int, text: str, page: int = 1, checksum: str | None = None):
    checksum = checksum or sha256(b"source").hexdigest()
    return DocumentChunk(
        chunk_id=f"chunk-{index}", source_filename="macbeth.pdf",
        source_checksum=checksum, page_start=page, page_end=page,
        act_id="act_1", scene_id="scene_1", chunk_index=index, text=text,
    )


def _sample_extraction(text: str, page: int = 1) -> PDFExtraction:
    checksum = sha256(b"synthetic source").hexdigest()
    section = PageSection(page_number=page, act_id="act_1", scene_id="scene_1", text=text)
    return PDFExtraction(
        inspection=PDFInspection(source_path="synthetic.pdf", source_filename="synthetic.pdf",
                                 source_checksum=checksum, page_count=1,
                                 extracted_char_count=len(text), pages_with_text=1),
        pages=[ExtractedPage(page_number=page, sections=[section], text_char_count=len(text))],
    )


def test_pdf_extraction_preserves_pages_and_act_scene(tmp_path):
    path = _write_pdf(tmp_path / "play.pdf", ["ACT I\nSCENE I\nThunder and lightning.\nEnter three Witches.",
                                                "ACT II\nSCENE III\nA room in the castle."])
    result = extract_pdf(path)
    assert result.inspection.page_count == 2
    assert result.inspection.extracted_char_count > 40
    assert result.inspection.likely_scanned_pages == []
    assert result.inspection.source_checksum == sha256(path.read_bytes()).hexdigest()
    first_section = next(s for s in result.pages[0].sections if s.scene_id)
    assert first_section.page_number == 1
    assert first_section.act_id == "act_1" and first_section.scene_id == "scene_1"
    second = next(s for s in result.pages[1].sections if s.scene_id)
    assert second.act_id == "act_2" and second.scene_id == "scene_3"


def test_empty_malformed_and_likely_scanned_pdf_detection(tmp_path):
    empty = _write_pdf(tmp_path / "empty.pdf", [""])
    with pytest.raises(PDFExtractionError, match="no extractable text"):
        extract_pdf(empty)
    malformed = tmp_path / "bad.pdf"
    malformed.write_bytes(b"not a pdf")
    with pytest.raises(PDFExtractionError, match="Could not extract"):
        extract_pdf(malformed)
    image_pdf = pymupdf.open()
    page = image_pdf.new_page()
    image_data = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/mN8AAAAASUVORK5CYII=")
    page.insert_image(pymupdf.Rect(0, 0, 50, 50), stream=image_data)
    scan_path = tmp_path / "scan.pdf"
    image_pdf.save(scan_path)
    image_pdf.close()
    with pytest.raises(PDFExtractionError, match="no extractable text"):
        extract_pdf(scan_path)

    mixed = pymupdf.open()
    mixed_page = mixed.new_page()
    mixed_page.insert_text((48, 48), "ACT I\nMacbeth enters.")
    scanned_page = mixed.new_page()
    scanned_page.insert_image(pymupdf.Rect(0, 0, 50, 50), stream=image_data)
    mixed_path = tmp_path / "mixed.pdf"
    mixed.save(mixed_path)
    mixed.close()
    report = extract_pdf(mixed_path)
    assert report.inspection.likely_scanned_pages == [2]
    assert "no OCR was run" in report.inspection.warnings[0]


def test_chunking_overlap_metadata_stability_and_size():
    text = "ACT I\nSCENE I\n" + " ".join(f"word{i}" for i in range(180))
    extraction = _sample_extraction(text, page=7)
    chunks = chunk_extraction(extraction, chunk_size=180, chunk_overlap=30)
    repeated = chunk_extraction(extraction, chunk_size=180, chunk_overlap=30)
    assert len(chunks) > 2
    assert [item.chunk_id for item in chunks] == [item.chunk_id for item in repeated]
    assert stable_chunk_ids(chunks)
    assert all(0 < len(item.text) <= 180 for item in chunks)
    assert all(item.page_start == item.page_end == 7 for item in chunks)
    assert all(item.source_checksum == extraction.inspection.source_checksum for item in chunks)
    assert all(item.act_id == "act_1" and item.scene_id == "scene_1" for item in chunks)
    assert any(set(a.text.split()) & set(b.text.split()) for a, b in pairwise(chunks))
    with pytest.raises(ValueError):
        chunk_extraction(extraction, chunk_size=100, chunk_overlap=100)


def test_rag_configuration_and_manifest_validation():
    settings = Settings(_env_file=None)
    assert settings.pdf_source_path == Path("content/macbeth/source/macbeth_original.pdf")
    assert settings.embedding_model == "nomic-embed-text"
    assert settings.rag_chunk_size == 1200 and settings.rag_chunk_overlap == 180
    with pytest.raises(ValidationError, match="smaller than"):
        Settings(_env_file=None, rag_chunk_size=500, rag_chunk_overlap=500)
    with pytest.raises(ValidationError, match="source checksums"):
        ChunkManifest(source_checksums={}, chunks=[_chunk(0, "text")], chunk_size=200, chunk_overlap=10)


def test_embedding_validation_and_ollama_document_query_prefixes(monkeypatch):
    calls = []

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"embeddings": [[1, 0], [0, 1]] if len(calls[-1]["input"]) == 2 else [[1, 0]]}

    def fake_post(url, json, timeout):
        calls.append({"url": url, "input": json["input"], "model": json["model"],
                      "timeout": timeout, "keep_alive": json["keep_alive"]})
        return Response()

    monkeypatch.setattr("httpx.post", fake_post)
    embedder = OllamaEmbeddingClient(model_name="nomic-embed-text")
    assert embedder.embed_documents(["A speech", "Another speech"]) == [[1.0, 0.0], [0.0, 1.0]]
    assert calls[-1]["input"] == ["search_document: A speech", "search_document: Another speech"]
    assert embedder.embed_query("Who speaks?") == [1.0, 0.0]
    assert calls[-1]["input"] == ["search_query: Who speaks?"]
    assert calls[0]["url"] == "http://localhost:11434/api/embed"
    assert calls[0]["keep_alive"] == "5m"
    assert validate_embeddings([[0.1, 0.2], [0.3, 0.4]], expected_count=2) == 2
    with pytest.raises(EmbeddingError, match="inconsistent"):
        validate_embeddings([[1.0], [1.0, 2.0]])
    with pytest.raises(EmbeddingError, match="non-finite"):
        validate_embeddings([[float("nan")]])


def test_embedding_model_availability_requires_existing_local_model(monkeypatch):
    class Response:
        def __init__(self, names):
            self.names = names

        def raise_for_status(self):
            pass

        def json(self):
            return {"models": [{"name": name} for name in self.names]}

    names = ["qwen3:4b"]
    monkeypatch.setattr("macbeth_game.rag.embeddings.httpx.get",
                        lambda *_args, **_kwargs: Response(names))
    embedder = OllamaEmbeddingClient(model_name="nomic-embed-text")
    with pytest.raises(EmbeddingError, match="nomic-embed-text.*unavailable"):
        embedder.check_model_available()
    names.append("nomic-embed-text:latest")
    assert embedder.check_model_available()


def test_ollama_dimension_mismatch_is_rejected(monkeypatch):
    dimensions = iter([2, 3])

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"embeddings": [[1.0] * next(dimensions)]}

    monkeypatch.setattr("httpx.post", lambda *args, **kwargs: Response())
    embedder = OllamaEmbeddingClient(model_name="other-embed-model")
    assert len(embedder.embed_query("first")) == 2
    with pytest.raises(EmbeddingError, match="dimension changed"):
        embedder.embed_query("second")


def test_faiss_add_search_roundtrip_and_metric_ordering(tmp_path):
    chunks = [
        _chunk(0, "Banquo asks who walks there."),
        _chunk(1, "The witches hail Macbeth as king."),
        _chunk(2, "Duncan arrives at the castle."),
    ]
    store = FAISSVectorStore(tmp_path / "faiss", tmp_path / "metadata.json")
    metadata = store.build(chunks, [[1, 0], [0.8, 0.2], [0, 1]], "fake-embed")
    assert metadata.vector_dimension == 2 and metadata.metric == "cosine"
    found = FAISSVectorStore(tmp_path / "faiss", tmp_path / "metadata.json").search(
        [1, 0], top_k=2, embedding_model="fake-embed")
    assert [chunk.chunk_id for chunk, _score in found] == ["chunk-0", "chunk-1"]
    assert found[0][1] > found[1][1]
    assert store.load_metadata().source_checksums == {"macbeth.pdf": chunks[0].source_checksum}
    with pytest.raises(VectorStoreError, match="does not match"):
        store.search([1, 0], embedding_model="different-model")


def test_missing_corrupt_incompatible_and_atomic_rebuild(tmp_path):
    directory = tmp_path / "index"
    store = FAISSVectorStore(directory)
    with pytest.raises(IndexUnavailable):
        store.load_metadata()
    chunks = [_chunk(0, "First passage."), _chunk(1, "Second passage.")]
    store.build(chunks, [[1, 0], [0, 1]], "fake")
    before = store.search([1, 0], embedding_model="fake")
    with pytest.raises(VectorStoreError, match="counts do not match"):
        store.build(chunks, [[0, 1]], "fake")
    assert store.search([1, 0], embedding_model="fake") == before
    metadata_path = directory / "metadata.json"
    current_hash = store.load_metadata().index_sha256
    payload = metadata_path.read_text(encoding="utf-8").replace(
        f'"index_sha256": "{current_hash}"', '"index_sha256": "' + ("0" * 64) + '"')
    metadata_path.write_text(payload, encoding="utf-8")
    with pytest.raises(VectorStoreError, match="checksum does not match"):
        store.load_metadata()
    (directory / "index.faiss").write_bytes(b"corrupt")
    payload = metadata_path.read_text(encoding="utf-8")
    from json import dumps, loads
    broken_metadata = loads(payload)
    broken_metadata["index_sha256"] = sha256((directory / "index.faiss").read_bytes()).hexdigest()
    metadata_path.write_text(dumps(broken_metadata), encoding="utf-8")
    with pytest.raises(VectorStoreError):
        store.load_metadata()


def test_source_checksum_changes_are_reflected_and_duplicate_hits_filtered(tmp_path):
    checksum_a = sha256(b"edition A").hexdigest()
    checksum_b = sha256(b"edition B").hexdigest()
    text = "A long overlapping passage about Macbeth and the witches. " * 5
    chunks = [_chunk(0, text, checksum=checksum_a), _chunk(1, text + "Again.", checksum=checksum_a)]
    store = FAISSVectorStore(tmp_path / "index")
    store.build(chunks, [[1, 0], [0.99, 0.01]], "fake")

    class FakeEmbedder:
        model_name = "fake"

        def embed_query(self, _query):
            return [1, 0]

    result = RAGRetriever(FakeEmbedder(), store).retrieve("witches and Macbeth", top_k=2)
    assert len(result.passages) == 1
    changed = [_chunk(0, text, checksum=checksum_b)]
    store.build(changed, [[1, 0]], "fake")
    assert store.load_metadata().source_checksums["macbeth.pdf"] == checksum_b


def test_vector_search_can_restrict_retrieval_to_authored_act_scene(tmp_path):
    checksum = sha256(b"source sections").hexdigest()
    chunks = [
        DocumentChunk(chunk_id="a1s1", source_filename="macbeth.pdf", source_checksum=checksum,
                      page_start=1, page_end=1, act_id="act_1", scene_id="scene_1",
                      chunk_index=0, text="Witches gather on a heath."),
        DocumentChunk(chunk_id="a2s2", source_filename="macbeth.pdf", source_checksum=checksum,
                      page_start=2, page_end=2, act_id="act_2", scene_id="scene_2",
                      chunk_index=1, text="Macbeth enters Duncan's chamber."),
        DocumentChunk(chunk_id="a2s3", source_filename="macbeth.pdf", source_checksum=checksum,
                      page_start=3, page_end=3, act_id="act_2", scene_id="scene_3",
                      chunk_index=2, text="The murder is discovered at dawn."),
    ]
    store = FAISSVectorStore(tmp_path / "section-index")
    store.build(chunks, [[1.0, 0.0], [0.9, 0.1], [0.8, 0.2]], "fake")
    exact = store.search([1.0, 0.0], top_k=1, embedding_model="fake", act_id="act_2", scene_id="scene_3")
    act_only = store.search([1.0, 0.0], top_k=2, embedding_model="fake", act_id="act_2")
    assert [chunk.chunk_id for chunk, _score in exact] == ["a2s3"]
    assert {chunk.act_id for chunk, _score in act_only} == {"act_2"}


def test_retriever_falls_back_to_act_only_when_exact_scene_is_irrelevant(tmp_path):
    checksum = sha256(b"source sections fallback").hexdigest()
    chunks = [
        DocumentChunk(chunk_id="other-scene", source_filename="macbeth.pdf", source_checksum=checksum,
                      page_start=1, page_end=1, act_id="act_2", scene_id="scene_3",
                      chunk_index=0, text="Murder discovered."),
        DocumentChunk(chunk_id="target", source_filename="macbeth.pdf", source_checksum=checksum,
                      page_start=2, page_end=2, act_id="act_2", scene_id="scene_4",
                      chunk_index=1, text="Banquo confronts Macbeth."),
    ]
    store = FAISSVectorStore(tmp_path / "fallback-index")
    store.build(chunks, [[0.2, 0.98], [0.99, 0.1]], "fake")

    class FakeEmbedder:
        model_name = "fake"

        def embed_query(self, _query):
            return [1.0, 0.0]

    result = RAGRetriever(FakeEmbedder(), store, minimum_relevance=0.5).retrieve(
        "Banquo confronts Macbeth", act_id="act_2", scene_id="scene_3")
    assert result.scope_used == "act_fallback"
    assert result.passages[0].chunk_id == "target"
    assert result.minimum_relevance == 0.5


def test_retriever_does_not_return_below_cutoff_passages(tmp_path):
    checksum = sha256(b"low relevance").hexdigest()
    store = FAISSVectorStore(tmp_path / "cutoff-index")
    store.build([_chunk(0, "A distant passage.", checksum=checksum)], [[0.2, 0.98]], "fake")

    class FakeEmbedder:
        model_name = "fake"

        def embed_query(self, _query):
            return [1.0, 0.0]

    result = RAGRetriever(FakeEmbedder(), store, minimum_relevance=0.5).retrieve("query")
    assert result.passages == []


def test_api_validation_search_and_health_without_index(tmp_path, monkeypatch):
    settings = Settings(_env_file=None, sqlite_path=tmp_path / "games.sqlite3",
                        faiss_index_dir=tmp_path / "not-built", rag_metadata_path=tmp_path / "not-built" / "metadata.json")
    def no_network(*_args, **_kwargs):
        raise AssertionError("application startup and missing-index search must not call Ollama")

    monkeypatch.setattr("httpx.post", no_network)
    monkeypatch.setattr("httpx.get", no_network)
    with TestClient(create_app(settings)) as client:
        gate = client.app.state.llm_provider.inference_gate
        assert client.app.state.rag_retriever.embedding_provider.inference_gate is gate
        assert client.app.state.llm_provider.context_window == settings.generation_context_window
        assert client.app.state.narrative_orchestrator.prompt_builder.max_prompt_chars == settings.narrative_max_prompt_chars
        assert client.get("/api/v1/health").status_code == 200
        assert client.get("/api/v1/characters").status_code == 200
        assert client.post("/api/v1/rag/search", json={"query": "   "}).status_code == 422
        assert client.post("/api/v1/rag/search", json={"query": "Macbeth", "top_k": 0}).status_code == 422
        unavailable = client.post("/api/v1/rag/search", json={"query": "Macbeth"})
        assert unavailable.status_code == 503
        assert "build it first" in unavailable.json()["detail"]


def test_api_retrieval_schema_with_fake_embeddings(tmp_path):
    settings = Settings(_env_file=None, sqlite_path=tmp_path / "games.sqlite3",
                        faiss_index_dir=tmp_path / "index", rag_metadata_path=tmp_path / "index" / "metadata.json")
    chunks = [_chunk(0, "The witches hail Macbeth king.")]
    FAISSVectorStore(settings.faiss_index_dir, settings.rag_metadata_path).build(
        chunks, [[1.0, 0.0]], settings.embedding_model)
    with TestClient(create_app(settings)) as client:
        client.app.state.rag_retriever.embedding_provider.embed_query = lambda _query: [1.0, 0.0]
        response = client.post("/api/v1/rag/search", json={"query": "What do the witches say?"})
        assert response.status_code == 200
        payload = response.json()
        assert payload["passages"][0]["chunk_id"] == "chunk-0"
        assert payload["passages"][0]["source_filename"] == "macbeth.pdf"
        assert payload["metric"] == "cosine"
