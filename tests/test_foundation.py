from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from macbeth_game.core.settings import Settings
from macbeth_game.domain.models import (
    CharacterDefinition,
    CharacterState,
    ChoiceDefinition,
    EventType,
    GameEvent,
    GameState,
    GameStatus,
    NarrativePerspective,
    StoryMode,
)
from macbeth_game.main import create_app


def test_character_and_choice_validation():
    assert CharacterState(character_id="macbeth").ambition == 50
    with pytest.raises(ValidationError):
        CharacterState(character_id="macbeth", ambition=101)
    with pytest.raises(ValidationError):
        ChoiceDefinition(choice_id="", action_id="act", description="Choose")
    character = CharacterDefinition(character_id="macbeth", name="Macbeth", role="thane",
                                    personality=["brave"], motivations=["power"], background="A thane")
    assert character.name == "Macbeth"


def test_game_state_defaults_enums_and_mutable_defaults():
    game = GameState(game_id="g1", selected_character_id="macbeth", current_scene_id="s1")
    assert game.story_mode is StoryMode.HYBRID
    assert game.perspective is NarrativePerspective.FIRST_PERSON
    assert game.status is GameStatus.ACTIVE
    game.flags["x"] = True
    other = GameState(game_id="g2", selected_character_id="macbeth", current_scene_id="s1")
    assert other.flags == {}
    with pytest.raises(ValidationError):
        GameState(game_id="g", selected_character_id="m", current_scene_id="s", story_mode="unknown")
    with pytest.raises(ValidationError):
        GameState(game_id="g", selected_character_id="m", current_scene_id="s", status="unknown")


def test_event_requires_timezone_aware_timestamp():
    with pytest.raises(ValidationError):
        GameEvent(event_id="e1", event_type=EventType.GAME_STARTED, actor_id="macbeth",
                  scene_id="s1", timestamp=datetime(2020, 1, 1))


def test_settings_defaults_overrides_and_no_api_key():
    settings = Settings(_env_file=None)
    assert settings.llm_provider == "ollama"
    assert settings.generation_model == "qwen3:4b"
    assert settings.embedding_model == "nomic-embed-text"
    assert settings.ollama_base_url == "http://localhost:11434"
    assert not hasattr(settings, "api_key")
    override = Settings(_env_file=None, app_name="Test", api_prefix="v2")
    assert override.app_name == "Test" and override.api_prefix == "/v2"


def test_health_endpoint_and_import_without_ollama(tmp_path):
    client = TestClient(create_app(Settings(_env_file=None, sqlite_path=tmp_path / "health.sqlite3")))
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"service": "Macbeth AI Story Game", "status": "ok"}
