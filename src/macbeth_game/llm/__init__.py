"""Local language-model provider integrations."""

from macbeth_game.llm.inference import InferenceGate
from macbeth_game.llm.ollama import OllamaProvider
from macbeth_game.llm.provider import (
    LLMError,
    LLMModelError,
    LLMProvider,
    LLMResponseError,
    LLMTimeout,
    LLMUnavailable,
)

__all__ = ["InferenceGate", "LLMError", "LLMModelError", "LLMProvider",
           "LLMResponseError", "LLMTimeout", "LLMUnavailable", "OllamaProvider"]
