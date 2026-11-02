"""Local embedding-provider contract and Ollama HTTP API adapter."""

from math import isfinite
from typing import Protocol

try:
    import httpx
except ImportError:  # RAG is optional; importing the game API must not require this extra.
    httpx = None

from macbeth_game.llm.inference import InferenceGate


class EmbeddingError(RuntimeError):
    """Embedding service failed or returned invalid vectors."""


class EmbeddingProvider(Protocol):
    model_name: str

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...
    def embed_query(self, text: str) -> list[float]: ...


def validate_embeddings(vectors: list[list[float]], expected_count: int | None = None,
                        expected_dimension: int | None = None) -> int:
    if expected_count is not None and len(vectors) != expected_count:
        raise EmbeddingError(f"Expected {expected_count} embeddings, received {len(vectors)}")
    if not vectors:
        raise EmbeddingError("Embedding response is empty")
    dimension = len(vectors[0])
    if dimension == 0:
        raise EmbeddingError("Embedding vectors must not be empty")
    if expected_dimension is not None and dimension != expected_dimension:
        raise EmbeddingError(f"Embedding dimension changed: expected {expected_dimension}, received {dimension}")
    for vector in vectors:
        if len(vector) != dimension:
            raise EmbeddingError("Embedding vectors have inconsistent dimensions")
        if any(not isinstance(value, (int, float)) or not isfinite(value) for value in vector):
            raise EmbeddingError("Embedding vector contains a non-finite or non-numeric value")
    return dimension


class OllamaEmbeddingClient:
    """Batch embeddings via Ollama's local `/api/embed` endpoint only."""

    def __init__(self, base_url: str = "http://localhost:11434", model_name: str = "nomic-embed-text",
                 timeout_seconds: float = 120.0, keep_alive: str = "5m",
                 inference_gate: InferenceGate | None = None):
        self.base_url = base_url.rstrip("/")
        self.model_name = model_name
        self.timeout_seconds = timeout_seconds
        self.keep_alive = keep_alive
        self.inference_gate = inference_gate or InferenceGate()
        self._dimension: int | None = None

    def check_model_available(self) -> bool:
        """Verify that the configured embedding model is already installed locally."""
        if httpx is None:
            raise EmbeddingError("Local embedding support requires the optional RAG dependencies: pip install -e '.[rag]'")
        try:
            response = httpx.get(f"{self.base_url}/api/tags", timeout=self.timeout_seconds)
            response.raise_for_status()
            payload = response.json()
        except httpx.ConnectError as exc:
            raise EmbeddingError("Cannot connect to Ollama at the configured local base URL") from exc
        except httpx.TimeoutException as exc:
            raise EmbeddingError(f"Ollama embedding model check timed out after {self.timeout_seconds:g}s") from exc
        except httpx.HTTPStatusError as exc:
            raise EmbeddingError(f"Ollama model check failed: HTTP {exc.response.status_code}") from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise EmbeddingError(f"Invalid response from local Ollama: {exc}") from exc
        models = payload.get("models") if isinstance(payload, dict) else None
        if not isinstance(models, list) or any(not isinstance(item, dict) for item in models):
            raise EmbeddingError("Ollama model check returned malformed model data")
        names = {item.get("name") for item in models if isinstance(item.get("name"), str)}
        normalized_names = names | {name.removesuffix(":latest") for name in names}
        configured = self.model_name.removesuffix(":latest")
        if configured not in normalized_names:
            raise EmbeddingError(
                f"Configured local embedding model {self.model_name!r} is unavailable; "
                f"install it explicitly with `ollama pull {self.model_name}`"
            )
        return True

    def _embed(self, texts: list[str], task: str) -> list[list[float]]:
        if httpx is None:
            raise EmbeddingError("Local embedding support requires the optional RAG dependencies: pip install -e '.[rag]'")
        if not texts or any(not text.strip() for text in texts):
            raise EmbeddingError("Embedding input must contain non-empty text")
        prefix = "search_document: " if task == "document" else "search_query: "
        model_input = [f"{prefix}{text}" for text in texts] if "nomic-embed-text" in self.model_name.lower() else texts
        try:
            with self.inference_gate:
                response = httpx.post(
                    f"{self.base_url}/api/embed",
                    json={"model": self.model_name, "input": model_input,
                          "keep_alive": self.keep_alive},
                    timeout=self.timeout_seconds,
                )
                response.raise_for_status()
                payload = response.json()
        except httpx.ConnectError as exc:
            raise EmbeddingError("Cannot connect to Ollama at the configured local base URL") from exc
        except httpx.TimeoutException as exc:
            raise EmbeddingError(f"Ollama embedding request timed out after {self.timeout_seconds:g}s") from exc
        except httpx.HTTPStatusError as exc:
            detail = "model not found; pull it explicitly with `ollama pull <model>`" if exc.response.status_code == 404 else f"HTTP {exc.response.status_code}"
            raise EmbeddingError(f"Ollama embedding failed for {self.model_name}: {detail}") from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise EmbeddingError(f"Invalid response from local Ollama: {exc}") from exc
        vectors = payload.get("embeddings") if isinstance(payload, dict) else None
        if not isinstance(vectors, list):
            raise EmbeddingError("Ollama response is missing the embeddings array")
        try:
            normalized = [[float(value) for value in row] for row in vectors]
        except (TypeError, ValueError) as exc:
            raise EmbeddingError("Ollama returned malformed embedding vectors") from exc
        dimension = validate_embeddings(normalized, expected_count=len(texts), expected_dimension=self._dimension)
        self._dimension = dimension
        return normalized

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._embed(texts, "document")

    def embed_query(self, text: str) -> list[float]:
        return self._embed([text], "query")[0]
