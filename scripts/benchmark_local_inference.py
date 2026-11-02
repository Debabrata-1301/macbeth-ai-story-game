"""Measure local Ollama latency and payload sizes without printing prompts or output."""

import argparse
import json
import sys
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from fastapi.testclient import TestClient

from macbeth_game.core.settings import get_settings
from macbeth_game.llm.ollama import OllamaProvider
from macbeth_game.llm.provider import LLMError
from macbeth_game.main import create_app
from macbeth_game.rag.embeddings import EmbeddingError, OllamaEmbeddingClient


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog="Turn mode commits one choice to the named game. Use a disposable game for measurements.",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prompt-file", type=Path, help="UTF-8 prompt file for a generation-only sample")
    mode.add_argument("--game-id", help="Existing game ID for an end-to-end turn sample (commits a choice)")
    parser.add_argument("--choice-id", help="Choice to commit; required with --game-id")
    parser.add_argument("--request-id", help="Idempotency ID; generated if omitted for a turn sample")
    return parser


def _connection_measure(provider) -> float:
    started = perf_counter()
    provider.check_connection()
    return (perf_counter() - started) * 1000


def _run_generation(prompt_path: Path) -> int:
    settings = get_settings()
    prompt = prompt_path.read_text(encoding="utf-8")
    provider = OllamaProvider(
        settings.ollama_base_url,
        settings.generation_model,
        settings.ollama_timeout_seconds,
        context_window=settings.generation_context_window,
        keep_alive=settings.ollama_keep_alive,
        think=settings.generation_think,
    )
    started = perf_counter()
    try:
        connection_ms = _connection_measure(provider)
        provider.check_model_available()
        embedding_probe_started = perf_counter()
        OllamaEmbeddingClient(settings.ollama_base_url, settings.embedding_model,
                              settings.ollama_timeout_seconds).embed_query("Macbeth local readiness probe")
        embedding_ms = (perf_counter() - embedding_probe_started) * 1000
        generation_started = perf_counter()
        output = provider.generate(
            prompt,
            temperature=settings.generation_temperature,
            max_tokens=settings.generation_max_tokens,
        )
        generation_ms = (perf_counter() - generation_started) * 1000
    except (LLMError, EmbeddingError) as exc:
        print(json.dumps({"mode": "generation", "failure": type(exc).__name__, "error": str(exc)}))
        return 2
    print(json.dumps({
        "mode": "generation",
        "model": settings.generation_model,
        "connection_ms": round(connection_ms, 1),
        "embedding_probe_ms": round(embedding_ms, 1),
        "generation_ms": round(generation_ms, 1),
        "total_ms": round((perf_counter() - started) * 1000, 1),
        "prompt_chars": len(prompt),
        "generated_output_chars": len(output),
    }, indent=2))
    return 0


def _run_turn(game_id: str, choice_id: str, request_id: str | None) -> int:
    settings = get_settings()
    app = create_app(settings)
    with TestClient(app) as client:
        provider = client.app.state.llm_provider
        measurements: dict[str, float | int] = {}
        original_generate = provider.generate

        def measured_generate(prompt, **options):
            measurements["prompt_chars"] = len(prompt)
            started = perf_counter()
            try:
                output = original_generate(prompt, **options)
            finally:
                measurements["generation_ms"] = round((perf_counter() - started) * 1000, 1)
            measurements["generated_output_chars"] = len(output)
            return output

        provider.generate = measured_generate
        try:
            connection_ms = _connection_measure(provider)
        except LLMError as exc:
            print(json.dumps({"mode": "turn", "failure": type(exc).__name__, "error": str(exc)}))
            return 2
        started = perf_counter()
        response = client.post(
            f"{settings.api_prefix}/games/{game_id}/turns",
            json={"choice_id": choice_id, "request_id": request_id or str(uuid4())},
        )
        result = response.json()
        summary = {
            "mode": "turn",
            "model": settings.generation_model,
            "http_status": response.status_code,
            "connection_ms": round(connection_ms, 1),
            "total_turn_ms": round((perf_counter() - started) * 1000, 1),
            "request_id": result.get("request_id"),
            "transition_applied": result.get("transition_applied"),
            "generation_error_code": result.get("generation_error_code"),
            **measurements,
        }
        print(json.dumps(summary, indent=2))
        return 0 if response.status_code < 400 else 1


def main() -> int:
    args = _parser().parse_args()
    if args.game_id:
        if not args.choice_id:
            _parser().error("--choice-id is required with --game-id")
        return _run_turn(args.game_id, args.choice_id, args.request_id)
    if args.choice_id or args.request_id:
        _parser().error("--choice-id and --request-id are only valid with --game-id")
    return _run_generation(args.prompt_file)


if __name__ == "__main__":
    sys.exit(main())
