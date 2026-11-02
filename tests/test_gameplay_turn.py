from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from macbeth_game.core.settings import Settings
from macbeth_game.engine.content import load_story_content
from macbeth_game.llm.narrative import DialogueEntry, NarrativeChoice, NarrativeResponse
from macbeth_game.main import create_app
from macbeth_game.repositories.game_repository import ConcurrentUpdate, PersistenceError
from macbeth_game.repositories.sqlite_repository import SQLiteGameRepository
from macbeth_game.services.game_service import GameService, IdempotencyConflict, InvalidChoice
from macbeth_game.services.gameplay_turn_service import GameplayTurnService
from macbeth_game.services.narrative_orchestrator import (
    NarrativeGenerationError,
    NarrativeGenerationTimeout,
    NarrativeProviderUnavailable,
    NarrativeResponseError,
)

CONTENT_DIR = Path(__file__).parents[1] / "content" / "macbeth"


def _narrative():
    return NarrativeResponse(
        narration="I ride toward Forres beneath the storm.",
        dialogue=[DialogueEntry(speaker="Banquo", text="The night grows strange.")],
        atmosphere="Thunder rolls over the heath.",
        choices=[
            NarrativeChoice(choice_id="tell_banquo", text="Tell Banquo of the prophecy."),
            NarrativeChoice(choice_id="hide_prophecy", text="Keep the prophecy secret."),
        ],
        source_references=[],
    )


class FakeOrchestrator:
    def __init__(self, outcomes=None):
        self.outcomes = list(outcomes or [_narrative()])
        self.calls = []

    def generate(self, game_id, *, retry_count=0):
        self.calls.append(game_id)
        outcome = self.outcomes.pop(0) if len(self.outcomes) > 1 else self.outcomes[0]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


@pytest.fixture
def game_context(tmp_path):
    path = tmp_path / "turns.sqlite3"
    repository = SQLiteGameRepository(path)
    game_service = GameService(load_story_content(CONTENT_DIR), repository=repository)
    initial_state = game_service.start_game("macbeth")
    turn_service = GameplayTurnService(game_service, FakeOrchestrator())
    return path, repository, game_service, turn_service, initial_state


def test_successful_turn_persists_transition_and_returns_current_choices(game_context):
    _path, repository, game_service, turn_service, initial = game_context
    result = turn_service.take_turn(initial.game_id, "press_to_forres", "request-1")

    assert result.transition_applied is True and result.replayed is False
    assert result.game.current_scene_id == "weird_sisters"
    assert result.game.revision == initial.revision + 1
    assert result.narrative.narration.startswith("I ride")
    assert {item["choice"].choice_id for item in result.available_choices} == {
        "tell_banquo", "hide_prophecy"
    }
    saved = repository.get_game(initial.game_id)
    assert saved.current_scene_id == "weird_sisters"
    assert saved.event_history[-1].metadata["request_id"] == "request-1"
    assert len(repository.list_events(initial.game_id)) == 2
    assert game_service.get_game(initial.game_id).revision == 1


def test_invalid_choice_is_rejected_without_state_change(game_context):
    _path, _repository, game_service, turn_service, initial = game_context
    before = game_service.get_game(initial.game_id).model_dump(mode="json")
    with pytest.raises(InvalidChoice):
        turn_service.take_turn(initial.game_id, "hide_prophecy", "invalid-1")
    assert game_service.get_game(initial.game_id).model_dump(mode="json") == before


def test_duplicate_submission_does_not_apply_transition_twice(game_context):
    _path, repository, game_service, turn_service, initial = game_context
    apply_once = Mock(wraps=game_service.execute_choice_once)
    game_service.execute_choice_once = apply_once

    first = turn_service.take_turn(initial.game_id, "press_to_forres", "same-request")
    duplicate = turn_service.take_turn(initial.game_id, "press_to_forres", "same-request")

    assert apply_once.call_count == 1
    assert first.transition_applied is True
    assert duplicate.transition_applied is False and duplicate.replayed is True
    assert duplicate.game.revision == 1
    assert len(repository.list_events(initial.game_id)) == 2


def test_concurrent_duplicate_is_recovered_from_committed_request_event(game_context):
    _path, repository, game_service, turn_service, initial = game_context
    apply_once = game_service.execute_choice_once
    calls = 0

    def simulate_competing_commit(game_id, choice_id, request_id=None):
        nonlocal calls
        calls += 1
        state, applied = apply_once(game_id, choice_id, request_id)
        if applied:
            raise ConcurrentUpdate("another identical request committed first")
        return state, applied

    game_service.execute_choice_once = simulate_competing_commit
    result = turn_service.take_turn(initial.game_id, "press_to_forres", "concurrent-request")
    assert result.replayed is True and result.transition_applied is False
    assert result.game.revision == 1
    assert calls == 1
    assert len(repository.list_events(initial.game_id)) == 2


def test_reusing_request_id_for_another_choice_is_rejected(game_context):
    _path, _repository, _game_service, turn_service, initial = game_context
    turn_service.take_turn(initial.game_id, "press_to_forres", "same-request")
    with pytest.raises(IdempotencyConflict):
        turn_service.take_turn(initial.game_id, "tell_banquo", "same-request")


def test_generation_failure_keeps_saved_transition_and_retry_does_not_replay(game_context):
    _path, repository, game_service, turn_service, initial = game_context
    orchestrator = FakeOrchestrator([
        NarrativeGenerationError("Ollama offline"),
        _narrative(),
    ])
    turn_service.narrative_orchestrator = orchestrator
    apply_once = Mock(wraps=game_service.execute_choice_once)
    game_service.execute_choice_once = apply_once

    failed = turn_service.take_turn(initial.game_id, "press_to_forres", "retry-request")
    assert failed.generation_error_code == "narrative_generation_failed"
    assert failed.narrative is None
    assert failed.transition_applied is True
    assert failed.game.current_scene_id == "weird_sisters"
    assert repository.get_game(initial.game_id).revision == 1

    recovered = turn_service.take_turn(initial.game_id, "press_to_forres", "retry-request")
    assert recovered.narrative is not None
    assert recovered.transition_applied is False and recovered.replayed is True
    assert recovered.game.revision == 1
    assert apply_once.call_count == 1
    assert len(repository.list_events(initial.game_id)) == 2


def test_narrative_validation_failure_is_recoverable_and_typed(game_context):
    _path, _repository, _game_service, turn_service, initial = game_context
    turn_service.narrative_orchestrator = FakeOrchestrator([
        NarrativeResponseError("invalid output")
    ])
    result = turn_service.take_turn(initial.game_id, "press_to_forres", "invalid-narrative")
    assert result.generation_error_code == "narrative_validation_failed"
    assert result.game.current_scene_id == "weird_sisters"
    assert result.narrative is None


@pytest.mark.parametrize(("failure", "expected_code"), [
    (NarrativeProviderUnavailable("offline"), "ollama_unavailable"),
    (NarrativeGenerationTimeout("timed out"), "generation_timeout"),
])
def test_provider_unavailable_and_timeout_have_distinct_recoverable_codes(
    game_context, failure, expected_code
):
    _path, _repository, _game_service, turn_service, initial = game_context
    turn_service.narrative_orchestrator = FakeOrchestrator([failure])
    result = turn_service.take_turn(initial.game_id, "press_to_forres", f"error-{expected_code}")
    assert result.generation_error_code == expected_code
    assert result.narrative is None
    assert result.game.revision == 1


def test_persistence_failure_prevents_narration_and_does_not_claim_success(game_context, monkeypatch):
    _path, repository, _game_service, turn_service, initial = game_context
    orchestrator = Mock()
    turn_service.narrative_orchestrator = orchestrator
    monkeypatch.setattr(repository, "update_game",
                        Mock(side_effect=PersistenceError("write failed")))
    with pytest.raises(PersistenceError):
        turn_service.take_turn(initial.game_id, "press_to_forres", "storage-failure")
    orchestrator.generate.assert_not_called()
    assert repository.get_game(initial.game_id).revision == 0


def test_request_id_event_survives_save_load_compatibly(game_context):
    path, _repository, _game_service, turn_service, initial = game_context
    turn_service.take_turn(initial.game_id, "press_to_forres", "persisted-request")
    loaded = SQLiteGameRepository(path).get_game(initial.game_id)
    assert loaded.revision == 1
    assert loaded.event_history[-1].metadata["request_id"] == "persisted-request"
    retry = GameplayTurnService(
        GameService(load_story_content(CONTENT_DIR), repository=SQLiteGameRepository(path)),
        FakeOrchestrator(),
    ).take_turn(initial.game_id, "press_to_forres", "persisted-request")
    assert retry.replayed is True and retry.transition_applied is False
    assert retry.game.revision == 1


def test_narration_retry_endpoint_and_turn_api_are_recoverable(tmp_path):
    settings = Settings(_env_file=None, sqlite_path=tmp_path / "api-turn.sqlite3",
                        faiss_index_dir=tmp_path / "missing-index",
                        rag_metadata_path=tmp_path / "missing-index" / "metadata.json")
    with TestClient(create_app(settings)) as client:
        started = client.post("/api/v1/games", json={"character_id": "macbeth"}).json()
        game_id = started["game"]["game_id"]
        turn_service = client.app.state.gameplay_turn_service
        turn_service.narrative_orchestrator = FakeOrchestrator([
            NarrativeGenerationError("offline"), _narrative(), _narrative()
        ])

        failed = client.post(f"/api/v1/games/{game_id}/turns",
                             json={"choice_id": "press_to_forres", "request_id": "http-request"})
        assert failed.status_code == 503
        assert failed.json()["generation_error_code"] == "narrative_generation_failed"
        assert failed.json()["game"]["current_scene_id"] == "weird_sisters"
        assert failed.json()["transition_applied"] is True

        duplicate = client.post(f"/api/v1/games/{game_id}/turns",
                                json={"choice_id": "press_to_forres", "request_id": "http-request"})
        assert duplicate.status_code == 200
        assert duplicate.json()["replayed"] is True
        assert duplicate.json()["game"]["revision"] == 1

        regenerated = client.post(f"/api/v1/games/{game_id}/narrative")
        assert regenerated.status_code == 200
        assert regenerated.json()["transition_applied"] is False
        assert regenerated.json()["game"]["revision"] == 1
        assert len(client.get(f"/api/v1/games/{game_id}/events").json()) == 2

        invalid = client.post(f"/api/v1/games/{game_id}/turns",
                              json={"choice_id": "not-a-choice", "request_id": "http-invalid"})
        assert invalid.status_code == 422
        assert client.get("/api/v1/health").status_code == 200


def test_narrative_validation_exception_can_be_retried_without_transition(game_context):
    _path, _repository, game_service, turn_service, initial = game_context
    orchestrator = FakeOrchestrator([
        NarrativeResponseError("bad schema"), _narrative()
    ])
    turn_service.narrative_orchestrator = orchestrator
    first = turn_service.take_turn(initial.game_id, "press_to_forres", "schema-retry")
    revision = first.game.revision
    second = turn_service.regenerate_narrative(initial.game_id)
    assert first.generation_error_code == "narrative_validation_failed"
    assert second.narrative is not None
    assert game_service.get_game(initial.game_id).revision == revision == 1
