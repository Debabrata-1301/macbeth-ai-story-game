from collections import deque
from pathlib import Path

import pytest

from macbeth_game.domain.models import GameStatus
from macbeth_game.repositories.sqlite_repository import SQLiteGameRepository
from macbeth_game.services.game_service import GameService

CONTENT_DIR = Path(__file__).parents[1] / "content" / "macbeth"


@pytest.fixture
def service():
    return GameService.from_directory(CONTENT_DIR)


def test_expanded_graph_integrity_and_classification(service):
    content = service.content
    assert len(content.scenes) == 60
    assert sum(len(scene.available_choices) for scene in content.scenes.values()) == 107
    choice_ids = [choice.choice_id for scene in content.scenes.values()
                  for choice in scene.available_choices]
    assert len(choice_ids) == len(set(choice_ids))

    reachable = set()
    for campaign in content.campaigns.values():
        assert campaign.starting_scene_id in campaign.scene_ids
        assert set(campaign.scene_ids) <= set(content.scenes)
        seen = {campaign.starting_scene_id}
        queue = deque(seen)
        while queue:
            scene = content.scenes[queue.popleft()]
            for choice in scene.available_choices:
                assert choice.next_scene_id in campaign.scene_ids
                if choice.next_scene_id not in seen:
                    seen.add(choice.next_scene_id)
                    queue.append(choice.next_scene_id)
                if choice.actor_id:
                    assert choice.actor_id in content.characters
                    assert choice.actor_id in scene.participants
                for change in choice.relationship_changes:
                    source = (change.source_character_id or choice.actor_id or next(
                        campaign.playable_character_id for campaign in content.campaigns.values()
                        if scene.scene_id in campaign.scene_ids))
                    assert source != change.character_id
        assert seen == set(campaign.scene_ids)
        reachable.update(seen)
    assert reachable == set(content.scenes)
    for scene in content.scenes.values():
        if scene.is_ending:
            assert scene.ending_id
            assert scene.available_choices == []
        else:
            assert scene.available_choices, f"non-ending scene has no choices: {scene.scene_id}"
    assert len({scene.ending_id for scene in content.scenes.values() if scene.is_ending}) == 18

    for scene_id in ("act2_dagger_vision", "act3_banquo_prophecy", "act4_apparitions",
                     "act5_birnam_wood"):
        scene = content.scenes[scene_id]
        assert scene.source_classification == "canonical_adaptation"
        assert scene.source_act_id and scene.source_scene_id
    assert content.scenes["ambition_ending"].source_classification == "alternate_history"


def test_nonplayable_people_have_state_but_are_not_selectable(service):
    assert {character.character_id for character in service.list_characters()} == {
        "macbeth", "lady_macbeth", "banquo", "macduff",
    }
    state = service.start_game("macbeth")
    assert {"duncan", "malcolm", "fleance", "lady_macduff", "macduff_child"} <= state.character_states.keys()
    assert service.content.speakers["malcolm"].display_name == "Malcolm"


@pytest.mark.parametrize(("path", "ending_scene", "ending_id"), [
    (("press_to_forres", "tell_banquo", "seek_counsel", "heed_banquo"), "patient_ending", "patient_path"),
    (("press_to_forres", "tell_banquo", "write_to_lady", "lady_counsel_ambition"), "ambition_ending", "ambition_path"),
    (("search_the_heath", "hide_prophecy", "leave_for_inverness", "end_in_isolation"), "solitary_ending", "solitary_path"),
    (("press_to_forres", "tell_banquo", "write_to_lady", "continue_to_regicide", "refuse_regicide"), "duncan_spared_ending", "duncan_spared"),
    (("press_to_forres", "tell_banquo", "write_to_lady", "continue_to_regicide", "proceed_with_murder", "confess_after_murder"), "macbeth_confession_ending", "macbeth_confessed"),
    (("press_to_forres", "tell_banquo", "write_to_lady", "continue_to_regicide", "proceed_with_murder", "keep_daggers", "protect_malcolm", "yield_to_malcolm"), "scotland_settlement_ending", "scotland_settlement"),
    (("press_to_forres", "tell_banquo", "write_to_lady", "continue_to_regicide", "proceed_with_murder", "frame_chamberlains", "accuse_guards", "claim_crown", "honor_banquo", "spare_banquo", "banquet_with_banquo", "summon_sisters", "question_apparitions", "spare_macduff_household", "accept_malcolm_alliance", "raise_scottish_rebellion", "care_for_lady", "retreat_dunsinane", "surrender_to_malcolm"), "macbeth_surrender_ending", "macbeth_surrendered"),
    (("press_to_forres", "tell_banquo", "write_to_lady", "continue_to_regicide", "proceed_with_murder", "frame_chamberlains", "accuse_guards", "claim_crown", "isolate_banquo", "order_banquo_murder", "banquo_falls_fleance_escapes", "banquet_ghost", "confess_banquos_ghost", "grant_macduff_leave", "trust_apparitions", "attack_macduff_household", "accept_malcolm_alliance", "raise_scottish_rebellion", "care_for_lady", "hold_dunsinane", "fight_macduff", "fight_to_death"), "tragic_tragedy_ending", "tragic_crown"),
    (("press_to_forres", "tell_banquo", "write_to_lady", "continue_to_regicide", "proceed_with_murder", "frame_chamberlains", "accuse_guards", "claim_crown", "isolate_banquo", "order_banquo_murder", "banquo_falls_fleance_escapes", "banquet_ghost", "confess_banquos_ghost", "grant_macduff_leave", "trust_apparitions", "attack_macduff_household", "accept_malcolm_alliance", "raise_scottish_rebellion", "care_for_lady", "hold_dunsinane", "fight_macduff", "escape_with_fleance"), "banquo_lineage_ending", "banquo_lineage"),
    (("press_to_forres", "tell_banquo", "write_to_lady", "continue_to_regicide", "proceed_with_murder", "frame_chamberlains", "accuse_guards", "claim_crown", "honor_banquo", "spare_banquo", "banquet_with_banquo", "summon_sisters", "question_apparitions", "spare_macduff_household", "reject_malcolm_alliance", "fracture_rebellion", "isolate_lady", "hold_dunsinane", "fight_macduff", "hold_the_crown"), "tyrant_crown_ending", "tyrant_crown"),
])
def test_authored_paths_reach_distinct_completed_endings(service, path, ending_scene, ending_id):
    game = service.start_game("macbeth")
    for choice_id in path:
        game = service.execute_choice(game.game_id, choice_id)
    assert game.current_scene_id == ending_scene
    assert game.status is GameStatus.COMPLETED
    assert game.ending_id == ending_id
    assert service.available_choices(game.game_id) == []


def test_consequences_track_murder_banquo_fleance_and_macduff_family(service):
    game = service.start_game("macbeth")
    for choice_id in ("press_to_forres", "tell_banquo", "write_to_lady", "continue_to_regicide",
                      "proceed_with_murder", "frame_chamberlains", "accuse_guards", "claim_crown",
                      "isolate_banquo", "order_banquo_murder", "banquo_falls_fleance_escapes",
                      "banquet_ghost", "confess_banquos_ghost", "grant_macduff_leave",
                      "trust_apparitions", "attack_macduff_household"):
        game = service.execute_choice(game.game_id, choice_id)
    assert game.character_states["duncan"].alive is False
    assert game.character_states["banquo"].alive is False
    assert game.character_states["fleance"].alive is True
    assert game.character_states["lady_macduff"].alive is False
    assert game.character_states["macduff_child"].alive is False
    assert game.flags["macduff_family_safe"] is False
    assert game.character_states["macduff"].suspicion > 0


def test_old_save_without_npc_states_is_hydrated_without_schema_migration(service, tmp_path):
    old = service.start_game("macbeth")
    old.character_states = {key: value for key, value in old.character_states.items()
                            if key in {"macbeth", "lady_macbeth", "banquo", "macduff"}}
    path = tmp_path / "legacy" / "game.sqlite3"
    SQLiteGameRepository(path).save_new_game(old)
    legacy_service = GameService(service.content, repository=SQLiteGameRepository(path))
    loaded = legacy_service.get_game(old.game_id)
    assert "duncan" in loaded.character_states
    assert "malcolm" in loaded.character_states
    assert legacy_service.get_game(old.game_id).revision == old.revision
    transitioned = legacy_service.execute_choice(old.game_id, "press_to_forres")
    assert "duncan" in transitioned.character_states
    assert SQLiteGameRepository(path).get_game(old.game_id).character_states["duncan"].character_id == "duncan"
