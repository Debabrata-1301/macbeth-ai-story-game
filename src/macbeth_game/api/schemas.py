"""HTTP request and response contracts."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from macbeth_game.domain.models import (
    CharacterDefinition,
    ChoiceDefinition,
    GameEvent,
    GameState,
    GameStatus,
    SceneDefinition,
    StoryMode,
)
from macbeth_game.llm.narrative import NarrativeResponse
from macbeth_game.rag.documents import RetrievalResult


class StartGameRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    character_id: str
    story_mode: StoryMode = StoryMode.HYBRID
    campaign_id: str | None = None


class ChoiceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    choice_id: str


class TurnRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    choice_id: str = Field(min_length=1, max_length=100)
    request_id: str = Field(min_length=1, max_length=100)

    @field_validator("choice_id", "request_id")
    @classmethod
    def strip_required_values(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value


class GameView(BaseModel):
    game: GameState
    scene: SceneDefinition


class GameSummary(BaseModel):
    game_id: str
    selected_character_id: str
    campaign_id: str = "macbeth"
    current_scene_id: str
    current_scene_title: str
    status: GameStatus
    revision: int
    turn_number: int
    created_at: datetime
    updated_at: datetime


class ChoiceAvailability(BaseModel):
    choice: ChoiceDefinition
    available: bool
    reason: str | None = None


class GameplayTurnResponse(BaseModel):
    game: GameState
    narrative: NarrativeResponse | None = None
    available_choices: list[ChoiceAvailability]
    request_id: str | None = None
    transition_applied: bool
    replayed: bool
    generation_error_code: str | None = None
    generation_error: str | None = None


class RAGSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1, max_length=2000)
    top_k: int | None = Field(default=None, ge=1, le=50)

    @field_validator("query")
    @classmethod
    def validate_query(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("query must not be empty")
        return value


__all__ = ["CharacterDefinition", "ChoiceAvailability", "ChoiceRequest", "GameEvent", "GameView",
           "GameplayTurnResponse", "RAGSearchRequest", "RetrievalResult", "StartGameRequest",
           "TurnRequest"]
