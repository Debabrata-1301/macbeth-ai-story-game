"""Synchronous text generation through a locally running Ollama service."""

import logging
from time import perf_counter

try:
    import httpx
except ImportError:  # Keep importing the game API independent of optional integrations.
    httpx = None

from macbeth_game.llm.inference import InferenceGate
from macbeth_game.llm.provider import (
    LLMError,
    LLMModelError,
    LLMResponseError,
    LLMTimeout,
    LLMUnavailable,
)

logger = logging.getLogger(__name__)


class OllamaProvider:
    """Adapter for Ollama's local `/api/generate` endpoint."""

    def __init__(self, base_url: str = "http://localhost:11434", model_name: str = "qwen3:4b",
                 timeout_seconds: float = 120.0, context_window: int = 4096,
                 keep_alive: str = "5m", inference_gate: InferenceGate | None = None,
                 think: bool = False):
        self.base_url = base_url.rstrip("/")
        self.model_name = model_name
        self.timeout_seconds = timeout_seconds
        self.context_window = context_window
        self.keep_alive = keep_alive
        self.think = think
        self.inference_gate = inference_gate or InferenceGate()

    def _require_httpx(self):
        if httpx is None:
            raise LLMError("Local generation requires httpx; install the project runtime dependencies")

    def check_connection(self) -> bool:
        """Return whether the configured local Ollama service responds to `/api/tags`."""
        self._require_httpx()
        try:
            response = httpx.get(f"{self.base_url}/api/tags", timeout=self.timeout_seconds)
            response.raise_for_status()
            payload = response.json()
        except httpx.ConnectError as exc:
            raise LLMUnavailable("Cannot connect to Ollama at the configured local base URL") from exc
        except httpx.TimeoutException as exc:
            raise LLMTimeout(f"Ollama connection check timed out after {self.timeout_seconds:g}s") from exc
        except httpx.HTTPStatusError as exc:
            raise LLMModelError(f"Ollama connection check failed: HTTP {exc.response.status_code}") from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise LLMResponseError(f"Invalid response from local Ollama: {exc}") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("models"), list):
            raise LLMResponseError("Ollama connection check returned malformed model data")
        return True

    def check_model_available(self) -> bool:
        """Verify the configured generation model is already installed locally."""
        self._require_httpx()
        try:
            response = httpx.get(f"{self.base_url}/api/tags", timeout=self.timeout_seconds)
            response.raise_for_status()
            payload = response.json()
        except httpx.ConnectError as exc:
            raise LLMUnavailable("Cannot connect to Ollama at the configured local base URL") from exc
        except httpx.TimeoutException as exc:
            raise LLMTimeout(f"Ollama model check timed out after {self.timeout_seconds:g}s") from exc
        except httpx.HTTPStatusError as exc:
            raise LLMModelError(f"Ollama model check failed: HTTP {exc.response.status_code}") from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise LLMResponseError(f"Invalid response from local Ollama: {exc}") from exc
        models = payload.get("models") if isinstance(payload, dict) else None
        if not isinstance(models, list) or any(not isinstance(item, dict) for item in models):
            raise LLMResponseError("Ollama model check returned malformed model data")
        names = {item.get("name") for item in models if isinstance(item.get("name"), str)}
        normalized_names = names | {name.removesuffix(":latest") for name in names}
        configured = self.model_name.removesuffix(":latest")
        if configured not in normalized_names:
            raise LLMModelError(
                f"Configured local generation model {self.model_name!r} is unavailable; "
                f"install it explicitly with `ollama pull {self.model_name}`"
            )
        return True

    def generate(self, prompt: str, *, temperature: float = 0.7, max_tokens: int = 512) -> str:
        self._require_httpx()
        if not prompt.strip():
            raise ValueError("prompt must not be empty")
        if not 0 <= temperature <= 2:
            raise ValueError("temperature must be between 0 and 2")
        if max_tokens < 1:
            raise ValueError("max_tokens must be positive")
        started = perf_counter()
        try:
            with self.inference_gate:
                response = httpx.post(
                    f"{self.base_url}/api/generate",
                    json={"model": self.model_name, "prompt": prompt, "stream": False,
                          "format": "json",
                          "keep_alive": self.keep_alive, "think": self.think,
                          "options": {"temperature": temperature, "num_predict": max_tokens,
                                      "num_ctx": self.context_window}},
                    timeout=self.timeout_seconds,
                )
                response.raise_for_status()
                payload = response.json()
        except httpx.ConnectError as exc:
            raise LLMUnavailable("Cannot connect to Ollama at the configured local base URL") from exc
        except httpx.TimeoutException as exc:
            raise LLMTimeout(f"Ollama generation timed out after {self.timeout_seconds:g}s") from exc
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                detail = f"model {self.model_name!r} was not found; pull it explicitly with `ollama pull {self.model_name}`"
            else:
                detail = f"HTTP {exc.response.status_code}"
            raise LLMModelError(f"Ollama generation failed: {detail}") from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise LLMResponseError(f"Invalid response from local Ollama: {exc}") from exc
        generated = payload.get("response") if isinstance(payload, dict) else None
        if not isinstance(generated, str) or not generated.strip():
            raise LLMResponseError("Ollama response is missing non-empty generated text")
        generated = generated.strip()
        logger.info("Ollama generation completed model=%s prompt_chars=%d output_chars=%d elapsed_ms=%.1f",
                    self.model_name, len(prompt), len(generated), (perf_counter() - started) * 1000)
        return generated
