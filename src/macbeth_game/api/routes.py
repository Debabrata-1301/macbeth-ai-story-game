"""HTTP endpoints for the deterministic game service."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse

from macbeth_game.api.schemas import (
    ChoiceAvailability,
    ChoiceRequest,
    GameplayTurnResponse,
    GameSummary,
    GameView,
    RAGSearchRequest,
    RetrievalResult,
    StartGameRequest,
    TurnRequest,
)
from macbeth_game.domain.models import CharacterDefinition, GameEvent, GameState, SceneDefinition
from macbeth_game.rag.embeddings import EmbeddingError
from macbeth_game.rag.retriever import RetrievalError
from macbeth_game.rag.vector_store import VectorStoreError
from macbeth_game.services.game_service import (
    CompletedGame,
    GameNotFound,
    GameService,
    IdempotencyConflict,
    InvalidCharacter,
    InvalidChoice,
    UnavailableChoice,
)
from macbeth_game.services.gameplay_turn_service import GameplayTurnResult, GameplayTurnService

router = APIRouter()


def get_game_service(request: Request) -> GameService:
    return request.app.state.game_service


def get_gameplay_turn_service(request: Request) -> GameplayTurnService:
    return request.app.state.gameplay_turn_service


def _turn_response(result: GameplayTurnResult) -> GameplayTurnResponse:
    return GameplayTurnResponse(
        game=result.game,
        narrative=result.narrative,
        available_choices=result.available_choices,
        request_id=result.request_id,
        transition_applied=result.transition_applied,
        replayed=result.replayed,
        generation_error_code=result.generation_error_code,
        generation_error=result.generation_error,
    )


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, (GameNotFound, InvalidCharacter)):
        code = status.HTTP_404_NOT_FOUND if isinstance(exc, GameNotFound) else 422
    elif isinstance(exc, InvalidChoice):
        code = 422
    elif isinstance(exc, (UnavailableChoice, CompletedGame, IdempotencyConflict)):
        code = status.HTTP_409_CONFLICT
    else:
        raise exc
    return HTTPException(status_code=code, detail=str(exc))


def _scene_for_player(service: GameService, state: GameState) -> dict:
    scene = service.content.scenes[state.current_scene_id]
    result = scene.model_dump(mode="json")
    character = service.content.characters[state.selected_character_id]
    campaign = service.content.campaigns.get(state.campaign_id)
    if state.selected_character_id != "macbeth" and campaign is not None and campaign.legacy:
        result["opening_narration"] = f"I am {character.name}. {scene.summary}"
    return result


@router.get("/health")
def health() -> dict[str, str]:
    return {"service": "Macbeth AI Story Game", "status": "ok"}


@router.get("/characters")
def list_characters(service: Annotated[GameService, Depends(get_game_service)]) -> list[CharacterDefinition]:
    return service.list_characters()


@router.post("/games", status_code=status.HTTP_201_CREATED, response_model=GameView)
def start_game(body: StartGameRequest, service: Annotated[GameService, Depends(get_game_service)]):
    try:
        state = service.start_game(body.character_id, body.story_mode, body.campaign_id)
        return GameView(game=state, scene=SceneDefinition.model_validate(_scene_for_player(service, state)))
    except InvalidCharacter as exc:
        raise _http_error(exc) from exc


@router.get("/games", response_model=list[GameSummary])
def list_games(service: Annotated[GameService, Depends(get_game_service)]):
    return [
        GameSummary(
            game_id=game.game_id,
            selected_character_id=game.selected_character_id,
            campaign_id=game.campaign_id,
            current_scene_id=game.current_scene_id,
            current_scene_title=service.content.scenes[game.current_scene_id].title,
            status=game.status.value,
            revision=game.revision,
            turn_number=game.turn_number,
            created_at=game.created_at,
            updated_at=game.updated_at,
        )
        for game in service.list_games()
    ]


@router.delete("/games/{game_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_game(game_id: str, service: Annotated[GameService, Depends(get_game_service)]):
    if not service.delete_game(game_id):
        raise _http_error(GameNotFound(f"Game {game_id} was not found"))


@router.get("/games/{game_id}", response_model=GameView)
def get_game(game_id: str, service: Annotated[GameService, Depends(get_game_service)]):
    try:
        state = service.get_game(game_id)
        return GameView(game=state, scene=SceneDefinition.model_validate(_scene_for_player(service, state)))
    except GameNotFound as exc:
        raise _http_error(exc) from exc


@router.get("/games/{game_id}/choices", response_model=list[ChoiceAvailability])
def get_choices(game_id: str, service: Annotated[GameService, Depends(get_game_service)]):
    try:
        service.get_game(game_id)
        return service.available_choices(game_id)
    except GameNotFound as exc:
        raise _http_error(exc) from exc


@router.post("/games/{game_id}/choices", response_model=GameView)
def make_choice(game_id: str, body: ChoiceRequest, service: Annotated[GameService, Depends(get_game_service)]):
    try:
        state = service.execute_choice(game_id, body.choice_id)
        return GameView(game=state, scene=SceneDefinition.model_validate(_scene_for_player(service, state)))
    except (GameNotFound, InvalidChoice, UnavailableChoice, CompletedGame) as exc:
        raise _http_error(exc) from exc


@router.post("/games/{game_id}/turns", response_model=GameplayTurnResponse)
def play_turn(game_id: str, body: TurnRequest,
              turn_service: Annotated[GameplayTurnService, Depends(get_gameplay_turn_service)]):
    """Apply one deterministic choice and return its generated narration when available."""
    try:
        result = turn_service.take_turn(game_id, body.choice_id, body.request_id)
        response = _turn_response(result)
        if result.generation_error_code:
            return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                                content=response.model_dump(mode="json"))
        return response
    except (GameNotFound, InvalidChoice, UnavailableChoice, CompletedGame,
            IdempotencyConflict) as exc:
        raise _http_error(exc) from exc


@router.post("/games/{game_id}/narrative", response_model=GameplayTurnResponse)
def regenerate_narrative(
    game_id: str,
    turn_service: Annotated[GameplayTurnService, Depends(get_gameplay_turn_service)],
):
    """Retry narration for the persisted current state without replaying a choice."""
    try:
        result = turn_service.regenerate_narrative(game_id)
        response = _turn_response(result)
        if result.generation_error_code:
            return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                                content=response.model_dump(mode="json"))
        return response
    except GameNotFound as exc:
        raise _http_error(exc) from exc


@router.get("/games/{game_id}/events", response_model=list[GameEvent])
def get_events(game_id: str, service: Annotated[GameService, Depends(get_game_service)]):
    try:
        return service.list_events(game_id)
    except GameNotFound as exc:
        raise _http_error(exc) from exc


@router.post("/rag/search", response_model=RetrievalResult)
def search_corpus(body: RAGSearchRequest, request: Request):
    """Retrieve local source passages; results never mutate a game session."""
    try:
        return request.app.state.rag_retriever.retrieve(
            body.query, body.top_k or request.app.state.rag_default_top_k)
    except (EmbeddingError, RetrievalError, VectorStoreError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
