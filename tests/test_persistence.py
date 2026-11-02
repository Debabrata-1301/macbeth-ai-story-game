import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from macbeth_game.core.settings import Settings
from macbeth_game.domain.models import EventType
from macbeth_game.engine.content import load_story_content
from macbeth_game.main import create_app
from macbeth_game.repositories.game_repository import ConcurrentUpdate, PersistenceError
from macbeth_game.repositories.sqlite_repository import SQLiteGameRepository
from macbeth_game.services.game_service import GameService, InvalidChoice

CONTENT_DIR = Path(__file__).parents[1] / "content" / "macbeth"


def test_roundtrip_all_state_fields_and_events(tmp_path):
    path = tmp_path / "nested" / "story.sqlite3"
    repository = SQLiteGameRepository(path)
    service = GameService(load_story_content(CONTENT_DIR), repository=repository)
    game = service.start_game("macbeth")
    game = service.execute_choice(game.game_id, "search_the_heath")
    game = service.execute_choice(game.game_id, "tell_banquo")
    game = service.execute_choice(game.game_id, "seek_counsel")
    game = service.execute_choice(game.game_id, "heed_banquo")
    loaded = SQLiteGameRepository(path).get_game(game.game_id)
    assert loaded is not None
    assert loaded.model_dump(mode="json") == game.model_dump(mode="json")
    assert loaded.revision == 4
    assert loaded.status.value == "completed" and loaded.ending_id == "patient_path"
    assert loaded.character_states["macbeth"].suspicion == 5
    assert loaded.character_states["macbeth"].known_facts == {"witches_prophesied_kingship"}
    assert loaded.relationships[0].trust == 10
    assert loaded.flags == {"watched_heath": True, "shared_prophecy": True, "sought_counsel": True,
                            "reached_forres": True}
    assert loaded.turn_number == 4
    assert len(loaded.event_history) == 5
    assert loaded.event_history[-1].event_type is EventType.CHOICE_MADE
    assert repository.list_events(game.game_id) == loaded.event_history


def test_invalid_choice_does_not_change_persisted_game(tmp_path):
    repository = SQLiteGameRepository(tmp_path / "invalid.sqlite3")
    service = GameService(load_story_content(CONTENT_DIR), repository=repository)
    game = service.start_game("macbeth")
    before = repository.get_game(game.game_id).model_dump(mode="json")
    with pytest.raises(InvalidChoice):
        service.execute_choice(game.game_id, "tell_banquo")
    assert SQLiteGameRepository(repository.database_path).get_game(game.game_id).model_dump(mode="json") == before


def test_transaction_rolls_back_when_event_persistence_fails(tmp_path):
    path = tmp_path / "rollback.sqlite3"
    repository = SQLiteGameRepository(path)
    service = GameService(load_story_content(CONTENT_DIR), repository=repository)
    game = service.start_game("macbeth")
    before = repository.get_game(game.game_id).model_dump(mode="json")
    with repository._connection() as connection:
        connection.execute("""
            CREATE TRIGGER reject_choice_event BEFORE INSERT ON game_events
            WHEN NEW.event_type = 'choice_made'
            BEGIN SELECT RAISE(ABORT, 'forced test failure'); END
        """)
    with pytest.raises(PersistenceError, match="persist game transition"):
        service.execute_choice(game.game_id, "press_to_forres")
    loaded = SQLiteGameRepository(path).get_game(game.game_id)
    assert loaded.model_dump(mode="json") == before


def test_schema_initialization_is_idempotent_and_revision_prevents_lost_update(tmp_path):
    path = tmp_path / "revision.sqlite3"
    first_repo = SQLiteGameRepository(path)
    second_repo = SQLiteGameRepository(path)
    service = GameService(load_story_content(CONTENT_DIR), repository=first_repo)
    game = service.start_game("macbeth")
    stale = second_repo.get_game(game.game_id)
    advanced = service.execute_choice(game.game_id, "press_to_forres")
    stale.revision += 1
    with pytest.raises(ConcurrentUpdate):
        second_repo.update_game(stale, expected_revision=0, new_events=[])
    assert SQLiteGameRepository(path).get_game(game.game_id).revision == advanced.revision


def test_api_restart_recovers_saved_game_and_event_history(tmp_path):
    settings = Settings(_env_file=None, sqlite_path=tmp_path / "restart.sqlite3")
    with TestClient(create_app(settings)) as first_client:
        started = first_client.post("/api/v1/games", json={"character_id": "macbeth"}).json()
        game_id = started["game"]["game_id"]
        first_client.post(f"/api/v1/games/{game_id}/choices", json={"choice_id": "press_to_forres"})
    with TestClient(create_app(settings)) as restarted_client:
        recovered = restarted_client.get(f"/api/v1/games/{game_id}")
        assert recovered.status_code == 200
        assert recovered.json()["game"]["current_scene_id"] == "weird_sisters"
        events = restarted_client.get(f"/api/v1/games/{game_id}/events").json()
        assert len(events) == 2
        assert events[-1]["metadata"]["choice_id"] == "press_to_forres"
        assert restarted_client.get("/api/v1/health").status_code == 200


@pytest.mark.parametrize(("character_id", "route", "ending_id"), [
    ("macbeth", ("press_to_forres", "tell_banquo", "seek_counsel", "heed_banquo"), "patient_path"),
    ("lady_macbeth", ("lady_macbeth_ambition", "lady_macbeth_prepare", "lady_macbeth_conceal",
                       "lady_macbeth_protect", "lady_macbeth_warn_banquo", "lady_macbeth_escape"),
     "lady_survival"),
    ("banquo", ("banquo_investigate", "banquo_warn", "banquo_challenge", "banquo_escape",
                 "banquo_testify"), "banquo_survived"),
    ("macduff", ("macduff_family", "macduff_warn", "macduff_evacuate", "macduff_justice",
                 "macduff_duel"), "scotland_freed"),
])
def test_each_campaign_can_save_resume_and_complete_after_api_restart(
        tmp_path, character_id, route, ending_id):
    settings = Settings(_env_file=None, sqlite_path=tmp_path / f"{character_id}.sqlite3")
    split = len(route) // 2
    with TestClient(create_app(settings)) as first_client:
        started = first_client.post("/api/v1/games", json={"character_id": character_id})
        assert started.status_code == 201
        game_id = started.json()["game"]["game_id"]
        for choice_id in route[:split]:
            response = first_client.post(f"/api/v1/games/{game_id}/choices", json={"choice_id": choice_id})
            assert response.status_code == 200
        saved = first_client.get(f"/api/v1/games/{game_id}").json()["game"]
        assert saved["turn_number"] == split

    with TestClient(create_app(settings)) as resumed_client:
        loaded = resumed_client.get(f"/api/v1/games/{game_id}")
        assert loaded.status_code == 200
        assert loaded.json()["game"]["campaign_id"] == character_id
        for choice_id in route[split:]:
            response = resumed_client.post(f"/api/v1/games/{game_id}/choices", json={"choice_id": choice_id})
            assert response.status_code == 200
        final = resumed_client.get(f"/api/v1/games/{game_id}").json()["game"]
        assert final["status"] == "completed"
        assert final["ending_id"] == ending_id
        assert final["turn_number"] == len(route)
        assert resumed_client.get(f"/api/v1/games/{game_id}/choices").json() == []
        events = resumed_client.get(f"/api/v1/games/{game_id}/events").json()
        assert len(events) == len(route) + 1


def test_legacy_event_without_visibility_metadata_loads_conservatively(tmp_path):
    path = tmp_path / "legacy-events.sqlite3"
    repository = SQLiteGameRepository(path)
    service = GameService(load_story_content(CONTENT_DIR), repository=repository)
    game = service.start_game("macbeth")
    event = game.event_history[0].model_dump(mode="json")
    for key in ("visibility", "witness_ids", "informed_ids", "rumoured_ids", "summary"):
        event.pop(key, None)
    with repository._connection() as connection:
        connection.execute("UPDATE game_events SET event_json = ? WHERE game_id = ?",
                           (json.dumps(event), game.game_id))
    recovered = SQLiteGameRepository(path).get_game(game.game_id)
    assert recovered is not None
    assert recovered.event_history[0].visibility == "unknown"
    assert recovered.event_history[0].witness_ids == []


def test_api_hides_persistence_details_and_keeps_state_on_storage_failure(tmp_path):
    path = tmp_path / "api-failure.sqlite3"
    settings = Settings(_env_file=None, sqlite_path=path)
    with TestClient(create_app(settings)) as client:
        started = client.post("/api/v1/games", json={"character_id": "macbeth"}).json()
        game_id = started["game"]["game_id"]
        repository = SQLiteGameRepository(path)
        with repository._connection() as connection:
            connection.execute("""
                CREATE TRIGGER reject_api_choice BEFORE INSERT ON game_events
                WHEN NEW.event_type = 'choice_made'
                BEGIN SELECT RAISE(ABORT, 'private database detail'); END
            """)
        response = client.post(f"/api/v1/games/{game_id}/choices", json={"choice_id": "press_to_forres"})
        assert response.status_code == 503
        assert response.json() == {"detail": "Game storage is temporarily unavailable."}
        saved = client.get(f"/api/v1/games/{game_id}").json()["game"]
        assert saved["current_scene_id"] == "heath_before_battle"
        assert saved["turn_number"] == 0


def test_missing_game_is_missing_and_delete_cascades_events(tmp_path):
    repository = SQLiteGameRepository(tmp_path / "delete.sqlite3")
    service = GameService(load_story_content(CONTENT_DIR), repository=repository)
    game = service.start_game("macbeth")
    assert SQLiteGameRepository(repository.database_path).get_game("missing") is None
    assert repository.delete_game(game.game_id)
    assert repository.list_events(game.game_id) is None


def test_game_library_lists_multiple_games_and_deletes_through_api(tmp_path):
    settings = Settings(_env_file=None, sqlite_path=tmp_path / "library.sqlite3")
    with TestClient(create_app(settings)) as client:
        first = client.post("/api/v1/games", json={"character_id": "macbeth"}).json()["game"]
        second = client.post("/api/v1/games", json={"character_id": "banquo"}).json()["game"]
        client.post(f"/api/v1/games/{first['game_id']}/choices", json={"choice_id": "press_to_forres"})

        listed = client.get("/api/v1/games")
        assert listed.status_code == 200
        games = listed.json()
        assert {game["game_id"] for game in games} == {first["game_id"], second["game_id"]}
        advanced = next(game for game in games if game["game_id"] == first["game_id"])
        assert advanced["current_scene_title"] == "Fair Is Foul"
        assert advanced["revision"] == 1
        assert advanced["updated_at"] >= advanced["created_at"]

        deleted = client.delete(f"/api/v1/games/{first['game_id']}")
        assert deleted.status_code == 204
        assert {game["game_id"] for game in client.get("/api/v1/games").json()} == {second["game_id"]}
        assert client.get(f"/api/v1/games/{first['game_id']}/events").status_code == 404
        assert client.delete(f"/api/v1/games/{first['game_id']}").status_code == 404
