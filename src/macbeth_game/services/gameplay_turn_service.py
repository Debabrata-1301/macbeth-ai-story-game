"""Apply deterministic player choices once, then request narration for the saved state."""

import logging
from dataclasses import dataclass

from macbeth_game.domain.models import GameState
from macbeth_game.llm.narrative import NarrativeResponse
from macbeth_game.repositories.game_repository import ConcurrentUpdate
from macbeth_game.services.game_service import (
    GameService,
    IdempotencyConflict,
)
from macbeth_game.services.narrative_orchestrator import (
    NarrativeContextError,
    NarrativeGenerationError,
    NarrativeGenerationTimeout,
    NarrativeOrchestrationError,
    NarrativeOrchestrator,
    NarrativePromptError,
    NarrativeProviderUnavailable,
    NarrativeResponseError,
    NarrativeRetrievalError,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GameplayTurnResult:
    game: GameState
    narrative: NarrativeResponse | None
    available_choices: list[dict]
    request_id: str | None
    transition_applied: bool
    replayed: bool
    generation_error_code: str | None = None
    generation_error: str | None = None


class GameplayTurnService:
    """Compose engine choice execution and narrative generation without merging their authority."""

    def __init__(self, game_service: GameService, narrative_orchestrator: NarrativeOrchestrator):
        self.game_service = game_service
        self.narrative_orchestrator = narrative_orchestrator

    @staticmethod
    def _request_event(game: GameState, request_id: str):
        return next((event for event in game.event_history
                     if event.metadata.get("request_id") == request_id), None)

    @staticmethod
    def _error_code(exc: NarrativeOrchestrationError) -> str:
        if isinstance(exc, NarrativeProviderUnavailable):
            return "ollama_unavailable"
        if isinstance(exc, NarrativeGenerationTimeout):
            return "generation_timeout"
        if isinstance(exc, NarrativeRetrievalError):
            return "narrative_retrieval_failed"
        if isinstance(exc, NarrativeGenerationError):
            return "narrative_generation_failed"
        if isinstance(exc, NarrativeResponseError):
            return "narrative_validation_failed"
        if isinstance(exc, NarrativePromptError):
            return "narrative_prompt_failed"
        if isinstance(exc, NarrativeContextError):
            return "narrative_context_failed"
        return "narrative_generation_failed"

    def _result(self, game: GameState, request_id: str | None, *, transition_applied: bool,
                replayed: bool, retry_count: int = 0) -> GameplayTurnResult:
        narrative = None
        error_code = None
        error_message = None
        try:
            narrative = self.narrative_orchestrator.generate(game.game_id, retry_count=retry_count)
        except NarrativeOrchestrationError as exc:
            error_code = self._error_code(exc)
            error_message = str(exc)
        choices = self.game_service.available_choices(game.game_id)
        current = self.game_service.get_game(game.game_id)
        if narrative is not None and current.revision != game.revision:
            # Do not pair narration from an older snapshot with a newer authoritative state.
            narrative = None
            error_code = "narrative_context_changed"
            error_message = "Game state changed while narration was being generated; retry for the current state."
            logger.warning(
                "Narrative context changed game_id=%s scene_id=%s error_category=%s "
                "exception_type=NarrativeContextError reason=game_revision_changed",
                game.game_id, game.current_scene_id, error_code,
            )
        return GameplayTurnResult(
            game=current,
            narrative=narrative,
            available_choices=choices,
            request_id=request_id,
            transition_applied=transition_applied,
            replayed=replayed,
            generation_error_code=error_code,
            generation_error=error_message,
        )

    def take_turn(self, game_id: str, choice_id: str, request_id: str) -> GameplayTurnResult:
        """Apply one available choice idempotently, then narrate the resulting current state."""
        request_id = request_id.strip()
        if not request_id or len(request_id) > 100:
            raise ValueError("request_id must contain between 1 and 100 characters")
        state = self.game_service.get_game(game_id)
        prior = self._request_event(state, request_id)
        if prior is not None:
            if prior.metadata.get("choice_id") != choice_id:
                raise IdempotencyConflict("request_id was already used for a different choice")
            # This is a retry: regenerate for the current state without replaying the transition.
            return self._result(state, request_id, transition_applied=False, replayed=True, retry_count=1)

        available = self.game_service.available_choices(game_id)
        matching = next((item for item in available if item["choice"].choice_id == choice_id), None)
        if matching is None or not matching["available"]:
            # Keep unknown, unavailable, and completed-game decisions under engine validation.
            state, applied = self.game_service.execute_choice_once(game_id, choice_id, request_id)
            return self._result(state, request_id, transition_applied=applied, replayed=not applied)

        try:
            state, applied = self.game_service.execute_choice_once(game_id, choice_id, request_id)
            replayed = not applied
        except ConcurrentUpdate:
            # A concurrent duplicate may have committed the same idempotency key first.
            state = self.game_service.get_game(game_id)
            prior = self._request_event(state, request_id)
            if prior is None:
                raise
            if prior.metadata.get("choice_id") != choice_id:
                raise IdempotencyConflict("request_id was already used for a different choice")
            applied = False
            replayed = True
        return self._result(state, request_id, transition_applied=applied, replayed=replayed)

    def regenerate_narrative(self, game_id: str) -> GameplayTurnResult:
        """Retry narration for the current state without applying any player choice."""
        state = self.game_service.get_game(game_id)
        return self._result(state, None, transition_applied=False, replayed=False, retry_count=1)
