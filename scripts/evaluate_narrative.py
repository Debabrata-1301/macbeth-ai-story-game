"""Run ten repeatable real Ollama narrative scenarios on an isolated temporary save."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from time import perf_counter

from macbeth_game.core.settings import Settings
from macbeth_game.engine.content import load_story_content
from macbeth_game.llm.ollama import OllamaProvider
from macbeth_game.llm.prompts import NarrativePromptBuilder
from macbeth_game.rag.embeddings import OllamaEmbeddingClient
from macbeth_game.rag.retriever import RAGRetriever
from macbeth_game.rag.vector_store import FAISSVectorStore
from macbeth_game.repositories.sqlite_repository import SQLiteGameRepository
from macbeth_game.services.game_service import GameService
from macbeth_game.services.narrative_orchestrator import NarrativeOrchestrator, NarrativeResponseError


ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = [
    ("Macbeth before Duncan's murder", "macbeth", []),
    ("Macbeth after regicide", "macbeth", ["press_to_forres", "tell_banquo", "seek_counsel",
                                            "reject_warning", "continue_to_regicide", "proceed_with_murder"]),
    ("Macbeth facing Banquo after betrayal", "macbeth", ["press_to_forres", "tell_banquo", "seek_counsel",
        "reject_warning", "continue_to_regicide", "proceed_with_murder", "frame_chamberlains",
        "accuse_guards", "claim_crown", "isolate_banquo", "order_banquo_murder",
        "banquo_falls_fleance_escapes"]),
    ("Lady Macbeth during psychological decline", "lady_macbeth", ["lady_macbeth_ambition",
        "lady_macbeth_prepare", "lady_macbeth_conceal", "lady_macbeth_protect",
        "lady_macbeth_warn_banquo"]),
    ("Banquo suspecting Macbeth", "banquo", ["banquo_investigate", "banquo_warn"]),
    ("Banquo surviving assassination attempt", "banquo", ["banquo_investigate", "banquo_warn",
        "banquo_challenge", "banquo_escape", "banquo_testify"]),
    ("Macduff protecting his family", "macduff", ["macduff_family", "macduff_warn", "macduff_evacuate"]),
    ("Macduff seeking justice after loss", "macduff", ["macduff_investigate", "macduff_evidence",
        "macduff_depart", "macduff_justice"]),
    ("Canonical Macbeth ending", "macbeth", ["press_to_forres", "tell_banquo", "seek_counsel", "heed_banquo"]),
    ("Alternate-history Lady Macbeth ending", "lady_macbeth", ["lady_macbeth_ambition",
        "lady_macbeth_prepare", "lady_macbeth_conceal", "lady_macbeth_protect",
        "lady_macbeth_warn_banquo", "lady_macbeth_reconcile"]),
]


def main() -> None:
    settings = Settings(_env_file=None, content_dir=ROOT / "content/macbeth",
                        faiss_index_dir=ROOT / "data/faiss",
                        rag_metadata_path=ROOT / "data/faiss/metadata.json",
                        ollama_base_url="http://localhost:11434")
    content = load_story_content(settings.content_dir)
    embedding = OllamaEmbeddingClient(settings.ollama_base_url, settings.embedding_model,
                                      settings.ollama_timeout_seconds)
    retriever = RAGRetriever(embedding, FAISSVectorStore(settings.faiss_index_dir,
                                                         settings.rag_metadata_path),
                            minimum_relevance=settings.rag_min_relevance)
    provider = OllamaProvider(settings.ollama_base_url, settings.generation_model,
                              settings.ollama_timeout_seconds,
                              context_window=settings.generation_context_window,
                              keep_alive=settings.ollama_keep_alive,
                              think=settings.generation_think)
    results = []
    with tempfile.TemporaryDirectory(prefix="macbeth-phase75-eval-") as temp:
        service = GameService(content, repository=SQLiteGameRepository(Path(temp) / "evaluation.sqlite3"))
        orchestrator = NarrativeOrchestrator(
            service, retriever, provider, settings,
            prompt_builder=NarrativePromptBuilder(max_prompt_chars=settings.narrative_max_prompt_chars),
        )
        for title, character_id, route in SCENARIOS:
            game = service.start_game(character_id)
            for choice_id in route:
                game = service.execute_choice(game.game_id, choice_id)
            started = perf_counter()
            narrative = None
            first_validation_error = None
            for attempt in range(2):
                try:
                    narrative = orchestrator.generate(game.game_id)
                    break
                except NarrativeResponseError as exc:
                    if first_validation_error is None:
                        first_validation_error = exc.diagnostic_reason
                except Exception as exc:
                    first_validation_error = type(exc).__name__
                    break
            if narrative is None:
                results.append({"scenario": title, "campaign": game.campaign_id,
                                "scene_id": game.current_scene_id, "error": "NarrativeResponseError",
                                "first_validation_error": first_validation_error, "retry_count": 1})
                print(json.dumps(results[-1], ensure_ascii=False), flush=True)
                continue
            duration = perf_counter() - started
            words = len((narrative.narration + " " + " ".join(
                line.text for line in narrative.dialogue) + " " + narrative.atmosphere).split())
            results.append({"scenario": title, "campaign": game.campaign_id,
                            "scene_id": game.current_scene_id, "seconds": round(duration, 2),
                            "retry_count": int(first_validation_error is not None),
                            "first_validation_error": first_validation_error,
                            "word_count": words, "citations": len(narrative.source_references),
                            "choice_count": len(narrative.choices), "narration": narrative.narration,
                            "dialogue": [line.model_dump() for line in narrative.dialogue]})
            print(json.dumps(results[-1], ensure_ascii=False), flush=True)
    timings = [item["seconds"] for item in results if "seconds" in item]
    report = {"model": settings.generation_model, "embedding_model": settings.embedding_model,
              "scenario_count": len(results), "successful_generations": len(timings),
              "validation_failures": len(results) - len(timings),
              "mean_seconds": round(sum(timings) / len(timings), 2) if timings else None,
              "results": results}
    report_path = ROOT / "docs/phase_7_6_evaluation_results.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
