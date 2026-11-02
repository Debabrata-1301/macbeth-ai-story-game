"""Repository contract and isolated in-memory implementation."""

from threading import RLock
from typing import Protocol

from macbeth_game.domain.models import GameEvent, GameState


class PersistenceError(RuntimeError):
    """A game could not be safely stored or loaded."""


class ConcurrentUpdate(PersistenceError):
    """The stored revision changed since a transition was calculated."""


class GameRepository(Protocol):
    def save_new_game(self, state: GameState) -> None: ...
    def get_game(self, game_id: str) -> GameState | None: ...
    def list_games(self) -> list[GameState]: ...
    def update_game(self, state: GameState, expected_revision: int,
                    new_events: list[GameEvent]) -> None: ...
    def list_events(self, game_id: str) -> list[GameEvent] | None: ...
    def delete_game(self, game_id: str) -> bool: ...


class InMemoryGameRepository:
    """Per-instance test/development repository; production app uses SQLite."""

    def __init__(self):
        self._states: dict[str, GameState] = {}
        self._lock = RLock()

    def save_new_game(self, state: GameState) -> None:
        with self._lock:
            if state.game_id in self._states:
                raise PersistenceError(f"Game {state.game_id} already exists")
            self._states[state.game_id] = state.model_copy(deep=True)

    def get_game(self, game_id: str) -> GameState | None:
        with self._lock:
            state = self._states.get(game_id)
            return state.model_copy(deep=True) if state else None

    def list_games(self) -> list[GameState]:
        with self._lock:
            states = [state.model_copy(deep=True) for state in self._states.values()]
        return sorted(states, key=lambda state: state.updated_at, reverse=True)

    def update_game(self, state: GameState, expected_revision: int,
                    new_events: list[GameEvent]) -> None:
        with self._lock:
            existing = self._states.get(state.game_id)
            if existing is None:
                raise PersistenceError(f"Game {state.game_id} does not exist")
            if existing.revision != expected_revision:
                raise ConcurrentUpdate(f"Game {state.game_id} changed concurrently")
            if state.revision != expected_revision + 1:
                raise PersistenceError("Updated game revision must increase exactly once")
            self._states[state.game_id] = state.model_copy(deep=True)

    def list_events(self, game_id: str) -> list[GameEvent] | None:
        state = self.get_game(game_id)
        return state.event_history if state else None

    def delete_game(self, game_id: str) -> bool:
        with self._lock:
            return self._states.pop(game_id, None) is not None
