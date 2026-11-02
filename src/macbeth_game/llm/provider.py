"""Provider contract shared by local text-generation backends."""

from typing import Protocol


class LLMError(RuntimeError):
    """Generation failed or the provider returned an invalid response."""


class LLMUnavailable(LLMError):
    """The configured local model service could not be reached."""


class LLMTimeout(LLMError):
    """The local model service did not respond before the request timeout."""


class LLMModelError(LLMError):
    """The configured model is missing or rejected the request."""


class LLMResponseError(LLMError):
    """Ollama returned malformed or empty generated content."""


class LLMProvider(Protocol):
    """Minimal synchronous contract; callers own prompt and output validation."""

    model_name: str

    def check_connection(self) -> bool: ...

    def generate(self, prompt: str, *, temperature: float = 0.7,
                 max_tokens: int = 512) -> str: ...
