"""A shared gate to serialize requests sent to one local Ollama server."""

from threading import Lock


class InferenceGate:
    """Serialize generation and embedding calls across provider instances."""

    def __init__(self):
        self._lock = Lock()

    def __enter__(self):
        self._lock.acquire()
        return self

    def __exit__(self, _exc_type, _exc, _traceback):
        self._lock.release()
