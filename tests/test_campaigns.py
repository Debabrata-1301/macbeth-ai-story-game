from pathlib import Path

import pytest

from macbeth_game.domain.models import GameState, GameStatus
from macbeth_game.engine.conditions import choice_rejection_reason
from macbeth_game.engine.content import load_story_content
from macbeth_game.repositories.sqlite_repository import SQLiteGameRepository
from macbeth_game.services.game_service import (
    CompletedGame,
    GameService,
    InvalidCharacter,
    UnavailableChoice,
)

CONTENT = Path(__file__).parents[1] / "content" / "macbeth"


@pytest.fixture
def service(tmp_path):
    return GameService.from_directory(CONTENT, SQLiteGameRepository(tmp_path / "campaigns.sqlite3"))


@pytest.mark.parametrize(("character", "campaign", "scene"), [
    ("macbeth", "macbeth", "heath_before_battle"),
    ("lady_macbeth", "lady_macbeth", "lady_letter"),
    ("banquo", "banquo", "banquo_heath"),
    ("macduff", "macduff", "macduff_fife"),
])
def test_campaign_initialization_and_identity_persist(service, character, campaign, scene):
    game = service.start_game(character)
    assert (game.campaign_id, game.current_scene_id) == (campaign, scene)
    assert service.get_game(game.game_id).campaign_id == campaign
    assert service.get_scene(game.game_id).scene_id == scene
    assert service.content.campaigns[campaign].playable_character_id == character
    resumed = GameService.from_directory(
        CONTENT, SQLiteGameRepository(service.repository.database_path),
    ).get_game(game.game_id)
    assert resumed.campaign_id == campaign
    assert resumed.revision == game.revision
    assert resumed.event_history == game.event_history


def test_campaign_identity_cannot_be_assigned_to_another_protagonist(service):
    with pytest.raises(InvalidCharacter):
        service.start_game("banquo", campaign_id="macduff")


def test_four_fresh_games_open_as_four_distinct_campaigns(service):
    protagonists = ("macbeth", "lady_macbeth", "banquo", "macduff")
    games = [service.start_game(character_id) for character_id in protagonists]
    assert len({game.campaign_id for game in games}) == 4
    assert len({game.current_scene_id for game in games}) == 4
    assert len({service.get_scene(game.game_id).opening_narration for game in games}) == 4
    first_decisions = []
    for character_id, game in zip(protagonists, games):
        campaign = service.content.campaigns[game.campaign_id]
        assert campaign.playable_character_id == character_id
        assert game.current_scene_id == campaign.starting_scene_id
        available = [row["choice"].choice_id for row in service.available_choices(game.game_id)
                     if row["available"]]
        assert len(available) >= 1
        assert all(choice_id.startswith(character_id) for choice_id in available) if character_id != "macbeth" else True
        first_decisions.append(tuple(available))
    assert len(set(first_decisions)) == 4


def test_lady_macbeth_has_independent_agency_and_alternate_endings(service):
    game = service.start_game("lady_macbeth")
    for choice in ("lady_macbeth_ambition", "lady_macbeth_prepare", "lady_macbeth_conceal",
                   "lady_macbeth_protect", "lady_macbeth_warn_banquo", "lady_macbeth_escape"):
        game = service.execute_choice(game.game_id, choice)
    assert game.ending_id == "lady_survival"
    assert game.status is GameStatus.COMPLETED
    assert game.character_states["lady_macbeth"].guilt > 0
    assert game.character_states["lady_macbeth"].emotional_stability < 100
    assert service.available_choices(game.game_id) == []


def test_lady_macbeth_can_prevent_regicide_and_cannot_choose_incompatible_coverup(service):
    game = service.start_game("lady_macbeth")
    for choice in ("lady_macbeth_caution", "lady_macbeth_oppose"):
        game = service.execute_choice(game.game_id, choice)
    available = {row["choice"].choice_id: row["available"]
                 for row in service.available_choices(game.game_id)}
    assert available["lady_macbeth_stop"] is True
    assert available["lady_macbeth_conceal"] is False
    game = service.execute_choice(game.game_id, "lady_macbeth_stop")
    assert game.ending_id == "lady_duncan_spared"


def test_lady_macbeth_can_change_banquos_fate_and_the_ghost_branch(service):
    game = service.start_game("lady_macbeth")
    for choice in ("lady_macbeth_ambition", "lady_macbeth_prepare", "lady_macbeth_conceal",
                   "lady_macbeth_protect"):
        game = service.execute_choice(game.game_id, choice)
    game = service.execute_choice(game.game_id, "lady_macbeth_betray_banquo")
    assert game.current_scene_id == "lady_ghost"
    assert not game.character_states["banquo"].alive
    assert service.available_choices(game.game_id)[0]["available"]
    game = service.execute_choice(game.game_id, "lady_macbeth_name_ghost")
    assert game.current_scene_id == "lady_crisis"

    safe = service.start_game("lady_macbeth")
    for choice in ("lady_macbeth_ambition", "lady_macbeth_prepare", "lady_macbeth_conceal",
                   "lady_macbeth_protect", "lady_macbeth_spare_banquo"):
        safe = service.execute_choice(safe.game_id, choice)
    assert safe.character_states["banquo"].alive
    assert safe.current_scene_id == "lady_crisis"


@pytest.mark.parametrize(("route", "ending"), [
    (("lady_macbeth_ambition", "lady_macbeth_prepare", "lady_macbeth_conceal",
      "lady_macbeth_protect", "lady_macbeth_warn_banquo", "lady_macbeth_confess"), "lady_confession"),
    (("lady_macbeth_ambition", "lady_macbeth_prepare", "lady_macbeth_conceal",
      "lady_macbeth_protect", "lady_macbeth_warn_banquo", "lady_macbeth_reconcile"), "lady_reconciliation"),
])
def test_lady_macbeth_additional_endings_are_reachable(service, route, ending):
    game = service.start_game("lady_macbeth")
    for choice in route:
        game = service.execute_choice(game.game_id, choice)
    assert game.ending_id == ending


def test_macduff_can_free_scotland(service):
    game = service.start_game("macduff")
    for choice in ("macduff_family", "macduff_warn", "macduff_evacuate", "macduff_justice", "macduff_duel"):
        game = service.execute_choice(game.game_id, choice)
    assert game.ending_id == "scotland_freed"


def test_banquo_controls_survival_and_fleances_future(service):
    game = service.start_game("banquo")
    for choice in ("banquo_investigate", "banquo_warn", "banquo_challenge", "banquo_sacrifice"):
        game = service.execute_choice(game.game_id, choice)
    assert game.ending_id == "fleance_escaped"
    assert game.character_states["banquo"].alive is False
    assert game.character_states["fleance"].alive is True
    assert service.available_choices(game.game_id) == []
    with pytest.raises(CompletedGame):
        service.execute_choice(game.game_id, "banquo_investigate")


def test_macduff_can_save_or_lose_family_before_rebellion(service):
    saved = service.start_game("macduff")
    for choice in ("macduff_family", "macduff_warn", "macduff_evacuate"):
        saved = service.execute_choice(saved.game_id, choice)
    assert saved.character_states["lady_macduff"].alive
    assert saved.character_states["macduff_child"].alive
    assert "family_safe" in saved.character_states["lady_macduff"].known_facts
    for choice in ("macduff_justice", "macduff_trial"):
        saved = service.execute_choice(saved.game_id, choice)
    assert saved.ending_id == "macbeth_tried"

    lost = service.start_game("macduff")
    for choice in ("macduff_investigate", "macduff_evidence", "macduff_depart"):
        lost = service.execute_choice(lost.game_id, choice)
    assert not lost.character_states["lady_macduff"].alive
    assert not lost.character_states["macduff_child"].alive
    assert lost.flags["macduff_family_lost"]


def test_banquo_survival_route_reaches_banquet_as_a_living_witness(service):
    game = service.start_game("banquo")
    for choice in ("banquo_investigate", "banquo_warn", "banquo_challenge", "banquo_escape"):
        game = service.execute_choice(game.game_id, choice)
    assert game.current_scene_id == "banquo_feast"
    assert game.character_states["banquo"].alive
    game = service.execute_choice(game.game_id, "banquo_testify")
    assert game.ending_id == "banquo_survived"
    assert game.character_states["banquo"].alive


def test_campaign_transition_cannot_enter_another_route(service):
    game = service.start_game("banquo")
    scene = service.content.scenes[game.current_scene_id]
    illegal = scene.available_choices[0].model_copy(update={"next_scene_id": "heath_before_battle"})
    service.content.scenes[scene.scene_id] = scene.model_copy(update={"available_choices": [illegal]})
    with pytest.raises(UnavailableChoice):
        service.execute_choice(game.game_id, illegal.choice_id)


def test_macbeth_suspicion_changes_banquo_murder_choice_availability(service):
    choice = next(choice for choice in service.content.scenes["act3_banquo_prophecy"].available_choices
                   if choice.choice_id == "order_banquo_murder")
    game = service.start_game("macbeth")
    low_suspicion = game.model_copy(deep=True)
    low_suspicion.character_states["macbeth"].suspicion = 10
    assert "suspicion of at least 30" in choice_rejection_reason(choice, low_suspicion)
    high_suspicion = game.model_copy(deep=True)
    high_suspicion.character_states["macbeth"].suspicion = 45
    high_suspicion.flags["banquo_watched"] = True
    assert choice_rejection_reason(choice, high_suspicion) is None


def test_legacy_state_without_campaign_field_defaults_to_original_route(service):
    old = GameState(game_id="old-save", selected_character_id="macbeth", current_scene_id="heath_before_battle")
    recovered = GameState.model_validate({k: v for k, v in old.model_dump().items() if k != "campaign_id"})
    assert recovered.campaign_id == "macbeth"
    assert service.content.campaigns[recovered.campaign_id].legacy


def test_campaign_catalog_is_explicit_and_inventories_are_disjoint():
    campaigns = load_story_content(CONTENT).campaigns
    assert set(campaigns) == {"macbeth", "lady_macbeth", "banquo", "macduff"}
    assert len({c.playable_character_id for c in campaigns.values()}) == 4
    assert len({scene for c in campaigns.values() for scene in c.scene_ids}) == sum(
        len(c.scene_ids) for c in campaigns.values())
