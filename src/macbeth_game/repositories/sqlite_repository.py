"""SQLite-backed, versioned repository for authoritative game state."""

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from pydantic import ValidationError

from macbeth_game.domain.models import GameEvent, GameState
from macbeth_game.repositories.game_repository import ConcurrentUpdate, PersistenceError

SCHEMA_VERSION = 1


class SQLiteGameRepository:
    def __init__(self, database_path: Path | str):
        self.database_path = str(database_path)
        if self.database_path != ":memory:":
            Path(self.database_path).parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path, timeout=10, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        try:
            yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        try:
            with self._connection() as connection:
                version = connection.execute("PRAGMA user_version").fetchone()[0]
                if version > SCHEMA_VERSION:
                    raise PersistenceError(f"Database schema {version} is newer than supported {SCHEMA_VERSION}")
                connection.executescript("""
                    CREATE TABLE IF NOT EXISTS games (
                        game_id TEXT PRIMARY KEY,
                        selected_character_id TEXT NOT NULL,
                        current_scene_id TEXT NOT NULL,
                        story_mode TEXT NOT NULL,
                        perspective TEXT NOT NULL,
                        status TEXT NOT NULL CHECK (status IN ('active','completed','abandoned')),
                        ending_id TEXT,
                        revision INTEGER NOT NULL CHECK (revision >= 0),
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        state_json TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS game_events (
                        event_id TEXT PRIMARY KEY,
                        game_id TEXT NOT NULL REFERENCES games(game_id) ON DELETE CASCADE,
                        sequence INTEGER NOT NULL CHECK (sequence >= 0),
                        event_type TEXT NOT NULL,
                        timestamp TEXT NOT NULL,
                        event_json TEXT NOT NULL,
                        UNIQUE(game_id, sequence)
                    );
                    CREATE INDEX IF NOT EXISTS idx_game_events_game_sequence
                        ON game_events(game_id, sequence);
                    CREATE INDEX IF NOT EXISTS idx_games_updated_at ON games(updated_at);
                """)
                connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        except PersistenceError:
            raise
        except sqlite3.Error as exc:
            raise PersistenceError(f"Could not initialize local game database: {exc}") from exc

    @staticmethod
    def _state_json(state: GameState) -> str:
        return state.model_dump_json(exclude={"event_history"})

    @staticmethod
    def _insert_events(connection: sqlite3.Connection, game_id: str,
                       events: list[GameEvent], start_sequence: int) -> None:
        for offset, event in enumerate(events):
            connection.execute(
                "INSERT INTO game_events(event_id, game_id, sequence, event_type, timestamp, event_json) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (event.event_id, game_id, start_sequence + offset, event.event_type.value,
                 event.timestamp.isoformat(), event.model_dump_json()),
            )

    def save_new_game(self, state: GameState) -> None:
        try:
            with self._connection() as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    "INSERT INTO games(game_id, selected_character_id, current_scene_id, story_mode, "
                    "perspective, status, ending_id, revision, created_at, updated_at, state_json) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (state.game_id, state.selected_character_id, state.current_scene_id,
                     state.story_mode.value, state.perspective.value, state.status.value,
                     state.ending_id, state.revision, state.created_at.isoformat(),
                     state.updated_at.isoformat(), self._state_json(state)),
                )
                self._insert_events(connection, state.game_id, state.event_history, 0)
                connection.commit()
        except sqlite3.Error as exc:
            raise PersistenceError(f"Could not save new game: {exc}") from exc

    def get_game(self, game_id: str) -> GameState | None:
        try:
            with self._connection() as connection:
                row = connection.execute("SELECT state_json FROM games WHERE game_id = ?", (game_id,)).fetchone()
                if row is None:
                    return None
                event_rows = connection.execute(
                    "SELECT event_json FROM game_events WHERE game_id = ? ORDER BY sequence", (game_id,)
                ).fetchall()
            state = GameState.model_validate_json(row["state_json"])
            state.event_history = [GameEvent.model_validate_json(item["event_json"]) for item in event_rows]
            return state
        except (sqlite3.Error, ValidationError, ValueError, json.JSONDecodeError) as exc:
            raise PersistenceError(f"Could not load saved game {game_id}: {exc}") from exc

    def list_games(self) -> list[GameState]:
        try:
            with self._connection() as connection:
                rows = connection.execute(
                    "SELECT game_id FROM games ORDER BY updated_at DESC, created_at DESC"
                ).fetchall()
            games = [self.get_game(row["game_id"]) for row in rows]
            return [game for game in games if game is not None]
        except (sqlite3.Error, ValidationError, ValueError, json.JSONDecodeError) as exc:
            raise PersistenceError(f"Could not list saved games: {exc}") from exc

    def update_game(self, state: GameState, expected_revision: int,
                    new_events: list[GameEvent]) -> None:
        try:
            with self._connection() as connection:
                connection.execute("BEGIN IMMEDIATE")
                current = connection.execute(
                    "SELECT revision FROM games WHERE game_id = ?", (state.game_id,)
                ).fetchone()
                if current is None:
                    raise PersistenceError(f"Game {state.game_id} does not exist")
                if current["revision"] != expected_revision:
                    raise ConcurrentUpdate(f"Game {state.game_id} changed concurrently")
                if state.revision != expected_revision + 1:
                    raise PersistenceError("Updated game revision must increase exactly once")
                event_count = connection.execute(
                    "SELECT COUNT(*) FROM game_events WHERE game_id = ?", (state.game_id,)
                ).fetchone()[0]
                cursor = connection.execute(
                    "UPDATE games SET selected_character_id = ?, current_scene_id = ?, story_mode = ?, "
                    "perspective = ?, status = ?, ending_id = ?, revision = ?, updated_at = ?, state_json = ? "
                    "WHERE game_id = ? AND revision = ?",
                    (state.selected_character_id, state.current_scene_id, state.story_mode.value,
                     state.perspective.value, state.status.value, state.ending_id, state.revision,
                     state.updated_at.isoformat(), self._state_json(state), state.game_id, expected_revision),
                )
                if cursor.rowcount != 1:
                    raise ConcurrentUpdate(f"Game {state.game_id} changed concurrently")
                self._insert_events(connection, state.game_id, new_events, event_count)
                connection.commit()
        except (ConcurrentUpdate, PersistenceError):
            raise
        except sqlite3.Error as exc:
            raise PersistenceError(f"Could not persist game transition: {exc}") from exc

    def list_events(self, game_id: str) -> list[GameEvent] | None:
        state = self.get_game(game_id)
        return state.event_history if state else None

    def delete_game(self, game_id: str) -> bool:
        try:
            with self._connection() as connection:
                connection.execute("BEGIN IMMEDIATE")
                cursor = connection.execute("DELETE FROM games WHERE game_id = ?", (game_id,))
                connection.commit()
                return cursor.rowcount == 1
        except sqlite3.Error as exc:
            raise PersistenceError(f"Could not delete game: {exc}") from exc
