"""Local passage retrieval with source provenance and overlap deduplication."""

from macbeth_game.rag.documents import RetrievalPassage, RetrievalResult
from macbeth_game.rag.embeddings import EmbeddingProvider
from macbeth_game.rag.vector_store import FAISSVectorStore


class RetrievalError(RuntimeError):
    """A query could not be completed against the local corpus."""


class RAGRetriever:
    def __init__(self, embedding_provider: EmbeddingProvider, vector_store: FAISSVectorStore,
                 minimum_relevance: float = 0.35):
        self.embedding_provider = embedding_provider
        self.vector_store = vector_store
        self.minimum_relevance = minimum_relevance

    @staticmethod
    def _substantially_overlaps(left: str, right: str) -> bool:
        lnorm, rnorm = " ".join(left.lower().split()), " ".join(right.lower().split())
        if lnorm in rnorm or rnorm in lnorm:
            return True
        left_words, right_words = set(lnorm.split()), set(rnorm.split())
        if len(left_words) < 12 or len(right_words) < 12:
            return False
        union = left_words | right_words
        return bool(union) and len(left_words & right_words) / len(union) >= 0.82

    def retrieve(self, query: str, top_k: int = 4, *, act_id: str | None = None,
                 scene_id: str | None = None, min_relevance: float | None = None) -> RetrievalResult:
        query = query.strip()
        if not query:
            raise ValueError("query must not be empty")
        if top_k < 1:
            raise ValueError("top_k must be at least 1")
        metadata = self.vector_store.load_metadata()
        model_name = self.embedding_provider.model_name
        if metadata.embedding_model != model_name:
            raise RetrievalError(
                f"Configured embedding model {model_name!r} does not match index model {metadata.embedding_model!r}"
            )
        embedding = self.embedding_provider.embed_query(query)
        cutoff = self.minimum_relevance if min_relevance is None else min_relevance
        limit = min(len(metadata.chunks), top_k * 4)
        scope_used = "global"
        candidates = self.vector_store.search(embedding, top_k=limit, embedding_model=model_name,
                                              act_id=act_id, scene_id=scene_id)
        candidates = [(chunk, score) for chunk, score in candidates if score >= cutoff]
        if act_id and scene_id and not candidates:
            candidates = self.vector_store.search(embedding, top_k=limit, embedding_model=model_name,
                                                  act_id=act_id)
            candidates = [(chunk, score) for chunk, score in candidates if score >= cutoff]
            scope_used = "act_fallback"
        elif act_id and scene_id:
            scope_used = "scene"
        elif act_id:
            scope_used = "act"
        passages: list[RetrievalPassage] = []
        for chunk, score in candidates:
            if any(p.source_filename == chunk.source_filename
                   and p.act_id == chunk.act_id and p.scene_id == chunk.scene_id
                   and self._substantially_overlaps(p.text, chunk.text) for p in passages):
                continue
            passages.append(RetrievalPassage(
                chunk_id=chunk.chunk_id, text=chunk.text,
                source_filename=chunk.source_filename, source_checksum=chunk.source_checksum,
                page_start=chunk.page_start, page_end=chunk.page_end,
                act_id=chunk.act_id, scene_id=chunk.scene_id, score=score,
            ))
            if len(passages) >= top_k:
                break
        return RetrievalResult(query=query, passages=passages, embedding_model=model_name,
                               vector_dimension=metadata.vector_dimension, metric=metadata.metric,
                               scope_used=scope_used, minimum_relevance=cutoff)
