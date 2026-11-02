from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from macbeth_game.core.settings import Settings
from macbeth_game.domain.models import (
    GameStatus,
    RelationshipState,
)
from macbeth_game.engine.conditions import rejection_reason
from macbeth_game.engine.content import ContentError, StoryContent, load_story_content
from macbeth_game.main import create_app
from macbeth_game.services.game_service import (
    CompletedGame,
    GameNotFound,
    GameService,
    InvalidCharacter,
    InvalidChoice,
    UnavailableChoice,
)

CONTENT_DIR = Path(__file__).parents[1] / "content" / "macbeth"


@pytest.fixture
def service():
    return GameService.from_directory(CONTENT_DIR)


def test_content_loads_and_graph_is_validated():
    content = load_story_content(CONTENT_DIR)
    assert set(content.characters) == {"macbeth", "lady_macbeth", "banquo", "macduff"}
    assert set(content.speakers) == {*content.all_characters, "weird_sisters"}
    assert "duncan" not in content.characters and "weird_sisters" not in content.characters
    assert "weird_sisters" in content.scenes["weird_sisters"].participants
    assert "ambition_ending" in content.scenes
    with pytest.raises(ContentError, match="missing destination"):
        StoryContent(list(content.characters.values()), [content.scenes["heath_before_battle"]])


def test_story_content_rejects_participants_without_speaker_metadata():
    content = load_story_content(CONTENT_DIR)
    scene = content.scenes["patient_ending"].model_copy(update={
        "participants": ["macbeth", "unregistered_ghost"],
    })
    with pytest.raises(ContentError, match="speaker IDs without metadata"):
        StoryContent(list(content.characters.values()), [scene])


def test_ending_scene_cannot_authorize_new_choices(service):
    ending = service.content.scenes["ambition_ending"]
    choice = service.content.scenes["solitary_road"].available_choices[0]
    with pytest.raises(ValueError, match="ending scenes cannot offer"):
        type(ending).model_validate({**ending.model_dump(), "available_choices": [choice]})


def test_start_list_and_current_scene(service):
    assert len(service.list_characters()) == 4
    state = service.start_game("banquo")
    assert state.selected_character_id == "banquo"
    assert state.campaign_id == "banquo"
    assert state.turn_number == 0 and len(state.event_history) == 1
    assert service.get_scene(state.game_id).scene_id == "banquo_heath"
    with pytest.raises(InvalidCharacter):
        service.start_game("duncan")
    with pytest.raises(GameNotFound):
        service.get_game("missing")


@pytest.mark.parametrize("character_id", ["macbeth", "lady_macbeth", "banquo", "macduff"])
def test_all_playable_characters_keep_selection_and_can_execute_displayed_opening_choices(
    service, character_id
):
    state = service.start_game(character_id)
    assert service.get_game(state.game_id).selected_character_id == character_id
    displayed = [item for item in service.available_choices(state.game_id) if item["available"]]
    starting_scenes = {"macbeth": "heath_before_battle", "lady_macbeth": "lady_letter",
                       "banquo": "banquo_heath", "macduff": "macduff_fife"}
    assert state.current_scene_id == starting_scenes[character_id]
    assert len(displayed) >= (2 if character_id != "lady_macbeth" else 1)

    for item in displayed:
        independent = service.start_game(character_id)
        transition = service.execute_choice(independent.game_id, item["choice"].choice_id)
        assert transition.selected_character_id == character_id
        assert transition.current_scene_id != starting_scenes[character_id]
        assert all(pair.character_a != pair.character_b for pair in transition.relationships)


def test_branches_relationship_flags_and_events(service):
    state = service.start_game("macbeth")
    state = service.execute_choice(state.game_id, "search_the_heath")
    assert state.flags["watched_heath"] is True
    assert state.character_states["macbeth"].suspicion == 5
    state = service.execute_choice(state.game_id, "tell_banquo")
    assert state.current_scene_id == "forres_hopeful"
    assert state.character_states["macbeth"].known_facts == {"witches_prophesied_kingship"}
    assert state.character_states["banquo"].known_facts == {"witches_prophesied_kingship"}
    assert state.relationships[0].trust == 10
    assert {state.relationships[0].character_a, state.relationships[0].character_b} == {"macbeth", "banquo"}
    assert state.turn_number == 2 and len(state.event_history) == 3
    assert service.available_choices(state.game_id)[0]["available"]
    state = service.execute_choice(state.game_id, "seek_counsel")
    assert state.current_scene_id == "banquo_counsel"
    assert service.execute_choice(state.game_id, "heed_banquo").ending_id == "patient_path"


def test_alternate_branch_and_completed_game_rejection(service):
    first = service.start_game("macbeth")
    second = service.start_game("macbeth")
    first = service.execute_choice(first.game_id, "press_to_forres")
    first = service.execute_choice(first.game_id, "tell_banquo")
    second = service.execute_choice(second.game_id, "press_to_forres")
    second = service.execute_choice(second.game_id, "hide_prophecy")
    assert first.current_scene_id == "forres_hopeful"
    assert second.current_scene_id == "forres_shadowed"
    second = service.execute_choice(second.game_id, "leave_for_inverness")
    second = service.execute_choice(second.game_id, "end_in_isolation")
    assert second.status is GameStatus.COMPLETED
    assert service.available_choices(second.game_id) == []
    with pytest.raises(CompletedGame):
        service.execute_choice(second.game_id, "anything")


def test_invalid_and_unavailable_choices_preserve_state(service):
    state = service.start_game("macbeth")
    original = state.model_dump(mode="json")
    with pytest.raises(InvalidChoice):
        service.execute_choice(state.game_id, "tell_banquo")
    with pytest.raises(InvalidChoice):
        service.execute_choice(state.game_id, "not_a_choice")
    assert service.get_game(state.game_id).model_dump(mode="json") == original
    # The selected branch's increased trust makes this condition valid.
    state = service.execute_choice(state.game_id, "press_to_forres")
    state = service.execute_choice(state.game_id, "tell_banquo")
    assert service.available_choices(state.game_id)[0]["available"] is True


def test_condition_flags_knowledge_and_relationship_bounds(service):
    state = service.start_game("macbeth")
    choice = service.content.scenes["forres_shadowed"].available_choices[0]
    assert rejection_reason(choice.conditions, state) is not None
    condition = choice.conditions.model_copy(update={"required_flags": {}, "required_known_facts": ["secret"]})
    assert "not learned" in rejection_reason(condition, state)
    from macbeth_game.domain.models import ChoiceConditions
    relationship_condition = ChoiceConditions(relationship_character="banquo", min_trust=1)
    assert "trust" in rejection_reason(relationship_condition, state)
    relationship_condition = ChoiceConditions(relationship_character="banquo", min_hostility=1)
    assert "hostility" in rejection_reason(relationship_condition, state)
    # Relationship limits are bounded by domain validation.
    with pytest.raises(ValueError):
        ChoiceConditions(relationship_character="banquo", min_trust=101)


def test_relationship_model_rejects_self_pair():
    with pytest.raises(ValueError, match="distinct"):
        RelationshipState(character_a="banquo", character_b="banquo")


def test_banquo_cannot_take_macbeths_tell_banquo_choice(service):
    state = service.start_game("banquo")
    assert state.campaign_id == "banquo"
    available = {item["choice"].choice_id: item for item in service.available_choices(state.game_id)}
    assert "tell_banquo" not in available
    before = service.get_game(state.game_id).model_dump(mode="json")
    with pytest.raises(InvalidChoice):
        service.execute_choice(state.game_id, "tell_banquo")
    assert service.get_game(state.game_id).model_dump(mode="json") == before


def test_available_choice_effects_use_explicit_targets_and_knowledge_recipients(service):
    state = service.start_game("banquo")
    state = service.execute_choice(state.game_id, "banquo_investigate")
    assert state.event_history[-1].actor_id == "banquo"
    assert state.character_states["macbeth"].suspicion == 0
    assert state.character_states["banquo"].suspicion == 8
    assert "heard_descendant_prophecy" in state.character_states["banquo"].known_facts


def test_lady_knowledge_recipient_controls_caution_choice(service):
    state = service.start_game("macbeth")
    state = service.execute_choice(state.game_id, "press_to_forres")
    state = service.execute_choice(state.game_id, "tell_banquo")
    state = service.execute_choice(state.game_id, "write_to_lady")
    assert "macbeth_shared_prophecy" in state.character_states["lady_macbeth"].known_facts
    assert "macbeth_shared_prophecy" in state.character_states["macbeth"].known_facts
    available = {item["choice"].choice_id: item for item in service.available_choices(state.game_id)}
    assert available["lady_counsel_caution"]["available"] is True


def test_effect_validation_is_atomic(service):
    state = service.start_game("macbeth")
    scene = service.content.scenes["heath_before_battle"]
    bad_choice = scene.available_choices[0].model_copy(
        update={"character_changes": {"macbeth": {"ambition": 101}}})
    service.content.scenes["heath_before_battle"] = scene.model_copy(
        update={"available_choices": [bad_choice, *scene.available_choices[1:]]})
    before = service.get_game(state.game_id).model_dump(mode="json")
    with pytest.raises(UnavailableChoice, match="invalid"):
        service.execute_choice(state.game_id, "press_to_forres")
    assert service.get_game(state.game_id).model_dump(mode="json") == before


def test_api_game_flow_validation_errors_and_health(tmp_path):
    settings = Settings(_env_file=None, sqlite_path=tmp_path / "api.sqlite3")
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/v1/health").status_code == 200
        assert len(client.get("/api/v1/characters").json()) == 4
        assert client.post("/api/v1/games", json={"character_id": "nope"}).status_code == 422
        assert client.post("/api/v1/games", json={"character_id": "macbeth", "state": {}}).status_code == 422
        started = client.post("/api/v1/games", json={"character_id": "macbeth", "story_mode": "hybrid"})
        assert started.status_code == 201
        game_id = started.json()["game"]["game_id"]
        assert client.get(f"/api/v1/games/{game_id}/choices").status_code == 200
        assert client.post(f"/api/v1/games/{game_id}/choices", json={"choice_id": "bad"}).status_code == 422
        assert client.get(f"/api/v1/games/{game_id}/events").json()
        assert client.get("/api/v1/games/missing").status_code == 404
