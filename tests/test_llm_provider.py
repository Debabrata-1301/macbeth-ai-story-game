from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from time import sleep

import httpx
import pytest

from macbeth_game.core.settings import Settings
from macbeth_game.llm.inference import InferenceGate
from macbeth_game.llm.ollama import OllamaProvider
from macbeth_game.llm.provider import LLMModelError, LLMResponseError, LLMTimeout, LLMUnavailable
from macbeth_game.rag.embeddings import OllamaEmbeddingClient


def test_ollama_generation_sends_configured_model_and_limits(monkeypatch):
    calls = []

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"response": "  I hear the raven.  "}

    def fake_post(url, json, timeout):
        calls.append((url, json, timeout))
        return Response()

    monkeypatch.setattr("macbeth_game.llm.ollama.httpx.post", fake_post)
    provider = OllamaProvider("http://localhost:11434/", "qwen3:4b", 12,
                              context_window=4096, keep_alive="7m")
    assert provider.generate("Speak as Macbeth", temperature=0.4, max_tokens=300) == "I hear the raven."
    assert calls == [("http://localhost:11434/api/generate", {
        "model": "qwen3:4b", "prompt": "Speak as Macbeth", "stream": False,
        "format": "json", "keep_alive": "7m", "think": False,
        "options": {"temperature": 0.4, "num_predict": 300, "num_ctx": 4096}}, 12)]


def test_ollama_connection_check_and_unavailable(monkeypatch):
    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"models": []}

    monkeypatch.setattr("macbeth_game.llm.ollama.httpx.get", lambda *_args, **_kwargs: Response())
    provider = OllamaProvider()
    assert provider.check_connection() is True
    with pytest.raises(LLMModelError, match="qwen3:4b.*unavailable"):
        provider.check_model_available()

    class ModelsResponse(Response):
        def json(self):
            return {"models": [{"name": "qwen3:4b"}]}

    monkeypatch.setattr("macbeth_game.llm.ollama.httpx.get",
                        lambda *_args, **_kwargs: ModelsResponse())
    assert provider.check_model_available() is True

    def unavailable(*_args, **_kwargs):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr("macbeth_game.llm.ollama.httpx.post", unavailable)
    with pytest.raises(LLMUnavailable, match="Cannot connect"):
        provider.generate("A prompt")


def test_ollama_generation_timeout_and_malformed_response(monkeypatch):
    provider = OllamaProvider(timeout_seconds=2)

    def timed_out(*_args, **_kwargs):
        raise httpx.ReadTimeout("late")

    monkeypatch.setattr("macbeth_game.llm.ollama.httpx.post", timed_out)
    with pytest.raises(LLMTimeout, match="timed out after 2s"):
        provider.generate("A prompt")

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"done": True}

    monkeypatch.setattr("macbeth_game.llm.ollama.httpx.post", lambda *_args, **_kwargs: Response())
    with pytest.raises(LLMResponseError, match="missing non-empty generated text"):
        provider.generate("A prompt")


def test_generation_settings_are_configurable_and_bounded():
    settings = Settings(_env_file=None, generation_temperature=0.2, generation_max_tokens=512,
                        generation_context_window=4096, ollama_keep_alive=" 8m ",
                        generation_think=True,
                        narrative_max_prompt_chars=10000, narrative_retrieval_top_k=2,
                        ollama_timeout_seconds=90)
    assert settings.generation_temperature == 0.2
    assert settings.generation_max_tokens == 512
    assert settings.generation_context_window == 4096
    assert settings.ollama_keep_alive == "8m"
    assert settings.generation_think is True
    assert settings.narrative_max_prompt_chars == 10000
    assert settings.narrative_retrieval_top_k == 2
    assert settings.ollama_timeout_seconds == 90
    defaults = Settings(_env_file=None)
    assert defaults.generation_max_tokens == 768
    assert defaults.generation_context_window == 4096
    assert defaults.ollama_keep_alive == "5m"
    assert defaults.generation_think is False
    assert defaults.narrative_max_prompt_chars == 12000
    assert defaults.ollama_timeout_seconds == 120
    with pytest.raises(ValueError):
        Settings(_env_file=None, generation_temperature=3)
    with pytest.raises(ValueError):
        Settings(_env_file=None, generation_max_tokens=0)
    with pytest.raises(ValueError):
        Settings(_env_file=None, generation_context_window=256)
    with pytest.raises(ValueError):
        Settings(_env_file=None, narrative_max_prompt_chars=1000)
    with pytest.raises(ValueError):
        Settings(_env_file=None, ollama_keep_alive="   ")


def test_generation_and_embedding_requests_share_a_serial_gate(monkeypatch):
    stats_lock = Lock()
    active = 0
    max_active = 0

    class Response:
        def __init__(self, url):
            self.url = url

        def raise_for_status(self):
            pass

        def json(self):
            if self.url.endswith("/api/embed"):
                return {"embeddings": [[1.0, 0.0]]}
            return {"response": "A measured line."}

    def fake_post(url, **_kwargs):
        nonlocal active, max_active
        with stats_lock:
            active += 1
            max_active = max(max_active, active)
        sleep(0.02)
        with stats_lock:
            active -= 1
        return Response(url)

    monkeypatch.setattr("httpx.post", fake_post)
    gate = InferenceGate()
    generator = OllamaProvider(inference_gate=gate)
    embedder = OllamaEmbeddingClient(inference_gate=gate)
    with ThreadPoolExecutor(max_workers=4) as pool:
        tasks = [pool.submit(generator.generate, "Narrate") if index % 2 == 0
                 else pool.submit(embedder.embed_query, "Macbeth") for index in range(8)]
        [task.result() for task in tasks]
    assert max_active == 1
