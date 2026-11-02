from pathlib import Path

import pytest

from macbeth_game.domain.models import CharacterState, RelationshipState
from macbeth_game.engine.conditions import choice_rejection_reason
from macbeth_game.engine.content import load_story_content
from macbeth_game.repositories.sqlite_repository import SQLiteGameRepository
from macbeth_game.services.game_service import GameService, UnavailableChoice

CONTENT = Path(__file__).parents[1] / "content" / "macbeth"


def test_psychology_defaults_and_ranges():
    state = CharacterState(character_id="macbeth")
    assert (state.fear, state.stress, state.hope, state.confidence) == (10, 10, 50, 50)
    with pytest.raises(ValueError):
        CharacterState(character_id="macbeth", fear=101)


def test_accepted_choice_records_authored_psychology_memory_and_event_provenance(tmp_path):
    repository = SQLiteGameRepository(tmp_path / "simulation.sqlite3")
    service = GameService.from_directory(CONTENT, repository)
    game = service.start_game("lady_macbeth")
    result = service.execute_choice(game.game_id, "lady_macbeth_ambition", request_id="ambition-once")
    assert result.character_states["lady_macbeth"].ambition == 82
    assert len(result.memories) == 1
    memory = result.memories[0]
    event = result.event_history[-1]
    assert memory.character_id == "lady_macbeth"
    assert memory.event_id == event.event_id
    assert memory.campaign_id == "lady_macbeth"
    assert event.metadata["psychological_changes_applied"]["lady_macbeth"]["ambition"] == 12
    assert event.metadata["character_state_changes_applied"]["lady_macbeth"]["ambition"] == 82

    resumed = GameService.from_directory(CONTENT, SQLiteGameRepository(repository.database_path))
    loaded = resumed.get_game(game.game_id)
    assert loaded.character_states["lady_macbeth"].ambition == 82
    assert loaded.memories == result.memories
    replayed, applied = resumed.execute_choice_once(game.game_id, "lady_macbeth_ambition", "ambition-once")
    assert not applied
    assert replayed.character_states["lady_macbeth"].ambition == 82
    assert replayed.memories == result.memories


def test_private_secret_and_memories_are_campaign_local_and_visibility_scoped(tmp_path):
    service = GameService.from_directory(CONTENT, SQLiteGameRepository(tmp_path / "private.sqlite3"))
    lady = service.start_game("lady_macbeth")
    other = service.start_game("macduff")
    for choice in ("lady_macbeth_ambition", "lady_macbeth_prepare", "lady_macbeth_conceal"):
        lady = service.execute_choice(lady.game_id, choice)
    secret = next(item for item in lady.commitments if item.commitment_id == "lady_duncan_deed")
    assert secret.status == "active"
    assert secret.owner_id == "lady_macbeth" and secret.participant_ids == ["macbeth"]
    assert all(item.campaign_id == "lady_macbeth" for item in lady.memories)
    assert service.get_game(other.game_id).commitments == []
    assert service.get_game(other.game_id).memories == []


def test_broken_family_promise_has_directional_relationship_and_psychology_cost(tmp_path):
    service = GameService.from_directory(CONTENT, SQLiteGameRepository(tmp_path / "breach.sqlite3"))
    game = service.start_game("macduff")
    for choice in ("macduff_investigate", "macduff_warn", "macduff_depart"):
        game = service.execute_choice(game.game_id, choice)
    promise = next(item for item in game.commitments if item.commitment_id == "macduff_household_safety")
    assert promise.status == "broken"
    assert promise.resolved_event_id == game.event_history[-1].event_id
    relation = next(item for item in game.relationships
                    if item.character_a == "lady_macduff" and item.character_b == "macduff")
    assert relation.trust == -20 and relation.hostility == 20
    assert game.character_states["macduff"].guilt >= 20
    assert game.character_states["macduff"].stress >= 20


def test_banquo_suspicion_is_not_a_confirmed_fact(tmp_path):
    service = GameService.from_directory(CONTENT, SQLiteGameRepository(tmp_path / "knowledge.sqlite3"))
    game = service.start_game("banquo")
    for choice in ("banquo_investigate", "banquo_warn", "banquo_challenge"):
        game = service.execute_choice(game.game_id, choice)
    banquo = game.character_states["banquo"]
    suspicion = next(item for item in banquo.uncertain_knowledge if item.category == "suspicion")
    assert suspicion.confirmed_event_id is None
    assert suspicion.resolved_by_fact == "macbeth_arranged_banquo_ambush"
    assert "macbeth_arranged_banquo_ambush" not in banquo.known_facts
    game = service.execute_choice(game.game_id, "banquo_escape")
    game = service.execute_choice(game.game_id, "banquo_testify")
    banquo = game.character_states["banquo"]
    assert "macbeth_arranged_banquo_ambush" in banquo.known_facts
    assert suspicion.confirmed_event_id is None  # The pre-transition state is an independent snapshot.
    stored_suspicion = next(item for item in banquo.uncertain_knowledge if item.content == suspicion.content)
    assert stored_suspicion.confirmed_event_id == game.event_history[-1].event_id
    historical_memory = next(item for item in game.memories if item.character_id == "banquo"
                             and item.event_id == stored_suspicion.source_event_id)
    assert historical_memory.certainty == "confirmed"
    assert "later confirmed by evidence" in historical_memory.summary
    assert game.event_history[-1].metadata["knowledge_observations_confirmed"][0]["fact"] == \
        "macbeth_arranged_banquo_ambush"


def test_directional_relationship_threshold_changes_choice_availability():
    service = GameService.from_directory(CONTENT)
    game = service.start_game("macbeth")
    choice = next(choice for scene in service.content.scenes.values()
                  for choice in scene.available_choices if choice.choice_id == "honor_banquo")
    game.flags["macbeth_crowned"] = True
    assert choice_rejection_reason(choice, game).startswith("Requires trust")
    game.relationships.append(RelationshipState(character_a="macbeth", character_b="banquo", trust=10))
    assert choice_rejection_reason(choice, game) is None
    game.relationships[0].character_a = "banquo"
    game.relationships[0].character_b = "macbeth"
    assert choice_rejection_reason(choice, game).startswith("Requires trust")


def test_rejected_commitment_choice_does_not_change_state(tmp_path):
    service = GameService.from_directory(CONTENT, SQLiteGameRepository(tmp_path / "reject.sqlite3"))
    game = service.start_game("lady_macbeth")
    game = service.execute_choice(game.game_id, "lady_macbeth_caution")
    game = service.execute_choice(game.game_id, "lady_macbeth_oppose")
    before = game.model_copy(deep=True)
    with pytest.raises(UnavailableChoice):
        service.execute_choice(game.game_id, "lady_macbeth_reveal")
    after = service.get_game(game.game_id)
    assert after.revision == before.revision
    assert after.turn_number == before.turn_number
    assert [event.event_id for event in after.event_history] == [event.event_id for event in before.event_history]
    assert after.character_states == before.character_states
    assert after.relationships == before.relationships
    assert after.memories == before.memories
    assert after.commitments == before.commitments


def test_content_keeps_campaign_scene_and_choice_inventory_unchanged():
    content = load_story_content(CONTENT)
    assert len(content.scenes) == 60
    assert sum(len(scene.available_choices) for scene in content.scenes.values()) == 107
    assert len(content.campaigns) == 4
