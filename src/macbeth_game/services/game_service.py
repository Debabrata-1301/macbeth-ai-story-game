"""Application service for local in-memory game sessions."""

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError

from macbeth_game.domain.models import (
    CharacterState,
    EventType,
    GameEvent,
    GameState,
    GameStatus,
    KnowledgeObservation,
    SceneDefinition,
    StoryMode,
)
from macbeth_game.engine.character_simulation import apply_accepted_choice
from macbeth_game.engine.conditions import choice_rejection_reason
from macbeth_game.engine.content import StoryContent, load_story_content
from macbeth_game.repositories.game_repository import GameRepository, InMemoryGameRepository


class GameServiceError(Exception):
    """Base error for game operations."""


class GameNotFound(GameServiceError):
    pass


class InvalidChoice(GameServiceError):
    pass


class UnavailableChoice(GameServiceError):
    pass


class CompletedGame(GameServiceError):
    pass


class InvalidCharacter(GameServiceError):
    pass


class IdempotencyConflict(GameServiceError):
    """A request ID was already used for a different player choice."""


class GameService:
    def __init__(self, content: StoryContent, opening_scene_id: str = "heath_before_battle",
                 repository: GameRepository | None = None):
        self.content = content
        self.opening_scene_id = opening_scene_id
        if opening_scene_id not in content.scenes:
            raise ValueError(f"Unknown opening scene: {opening_scene_id}")
        self.repository = repository or InMemoryGameRepository()

    @classmethod
    def from_directory(cls, directory: Path, repository: GameRepository | None = None) -> "GameService":
        return cls(load_story_content(directory), repository=repository)

    def list_characters(self):
        return list(self.content.characters.values())

    def get_campaign(self, campaign_id: str):
        return self.content.campaigns.get(campaign_id)

    def _hydrate_character_states(self, state: GameState) -> GameState:
        """Add newly-authored NPC state in memory when loading legacy saves."""
        for character_id in self.content.all_characters:
            state.character_states.setdefault(character_id, CharacterState(character_id=character_id))
        return state

    def start_game(self, character_id: str, story_mode: StoryMode = StoryMode.HYBRID,
                   campaign_id: str | None = None) -> GameState:
        if character_id not in self.content.characters:
            raise InvalidCharacter(f"Unknown playable character: {character_id}")
        campaign_id = campaign_id or next(
            (campaign.campaign_id for campaign in self.content.campaigns.values()
             if campaign.playable_character_id == character_id), character_id)
        campaign = self.content.campaigns.get(campaign_id)
        if self.content.campaigns and (campaign is None or campaign.playable_character_id != character_id):
            raise InvalidCharacter(f"Campaign {campaign_id} does not belong to {character_id}")
        campaign = campaign or type("LegacyCampaign", (), {
            "campaign_id": "macbeth", "starting_scene_id": self.opening_scene_id,
            "scene_ids": list(self.content.scenes),
        })()
        game_id = str(uuid4())
        now = datetime.now(UTC)
        state = GameState(
            game_id=game_id,
            selected_character_id=character_id,
            campaign_id=campaign_id,
            story_mode=story_mode,
            current_scene_id=campaign.starting_scene_id,
            character_states={key: CharacterState(character_id=key) for key in self.content.all_characters},
            event_history=[GameEvent(event_id=str(uuid4()), event_type=EventType.GAME_STARTED,
                                     actor_id=character_id, scene_id=campaign.starting_scene_id,
                                     timestamp=now)],
        )
        self.repository.save_new_game(state)
        return self._hydrate_character_states(state.model_copy(deep=True))

    def get_game(self, game_id: str) -> GameState:
        state = self.repository.get_game(game_id)
        if state is None:
            raise GameNotFound(f"Game {game_id} was not found")
        return self._hydrate_character_states(state.model_copy(deep=True))

    def list_games(self) -> list[GameState]:
        return self.repository.list_games()

    def delete_game(self, game_id: str) -> bool:
        return self.repository.delete_game(game_id)

    def get_scene(self, game_id: str) -> SceneDefinition:
        return self.content.scenes[self.get_game(game_id).current_scene_id]

    def list_events(self, game_id: str) -> list[GameEvent]:
        events = self.repository.list_events(game_id)
        if events is None:
            raise GameNotFound(f"Game {game_id} was not found")
        return events

    def available_choices(self, game_id: str) -> list[dict]:
        state = self.get_game(game_id)
        if state.status is GameStatus.COMPLETED:
            return []
        campaign = self.content.campaigns.get(state.campaign_id)
        if self.content.campaigns and (campaign is None or state.current_scene_id not in campaign.scene_ids):
            return []
        scene = self.content.scenes[state.current_scene_id]
        return [{"choice": choice, "available": (reason := choice_rejection_reason(choice, state)) is None,
                 "reason": reason} for choice in scene.available_choices]

    def execute_choice(self, game_id: str, choice_id: str, request_id: str | None = None) -> GameState:
        state, _applied = self.execute_choice_once(game_id, choice_id, request_id)
        return state

    def execute_choice_once(self, game_id: str, choice_id: str,
                            request_id: str | None = None) -> tuple[GameState, bool]:
        """Apply a choice at most once for request_id; return state and whether it was applied now."""
        if request_id is not None:
            request_id = request_id.strip()
            if not request_id or len(request_id) > 100:
                raise ValueError("request_id must contain between 1 and 100 characters")
        current = self.repository.get_game(game_id)
        if current is None:
            raise GameNotFound(f"Game {game_id} was not found")
        current = self._hydrate_character_states(current)
        if request_id is not None:
            prior = next((event for event in current.event_history
                          if event.metadata.get("request_id") == request_id), None)
            if prior is not None:
                if prior.metadata.get("choice_id") != choice_id:
                    raise IdempotencyConflict("request_id was already used for a different choice")
                return current.model_copy(deep=True), False
        if current.status is not GameStatus.ACTIVE:
            raise CompletedGame(f"Game {game_id} is {current.status.value}")
        scene = self.content.scenes[current.current_scene_id]
        choice = next((item for item in scene.available_choices if item.choice_id == choice_id), None)
        if choice is None:
            raise InvalidChoice(f"Choice {choice_id} is not available in scene {scene.scene_id}")
        reason = choice_rejection_reason(choice, current)
        if reason:
            raise UnavailableChoice(reason)
        campaign = self.content.campaigns.get(current.campaign_id)
        if self.content.campaigns and (campaign is None or current.current_scene_id not in campaign.scene_ids
                or choice.next_scene_id not in campaign.scene_ids):
            raise UnavailableChoice("This choice is outside the saved campaign route")
        # Calculate and validate on a copy. Repository CAS commits state and event atomically.
        candidate = current.model_copy(deep=True)
        event_id = str(uuid4())
        pre_choice_states = {key: value.model_dump() for key, value in candidate.character_states.items()}
        try:
            for character_id, changes in choice.character_changes.items():
                old = candidate.character_states[character_id]
                candidate.character_states[character_id] = CharacterState.model_validate(
                    {**old.model_dump(), **changes})
            simulation_metadata = apply_accepted_choice(
                candidate, choice, scene_id=scene.scene_id,
                scene_participants=scene.participants, event_id=event_id,
            )
        except (ValidationError, KeyError, ValueError) as exc:
            raise UnavailableChoice(f"Authored consequences are invalid: {exc}") from exc
        candidate.flags.update(choice.state_flags)
        for recipient_id in choice.rumoured_character_ids:
            recipient = candidate.character_states[recipient_id]
            recipient.uncertain_knowledge.append(KnowledgeObservation(
                character_id=recipient_id,
                content=choice.description[:500],
                category="rumour",
                confidence=25,
                source="Rumour from a game event; not established fact",
                source_event_id=event_id,
                created_turn=candidate.turn_number + 1,
                related_characters=[candidate.selected_character_id],
            ))
        candidate.current_scene_id = choice.next_scene_id
        destination = self.content.scenes[candidate.current_scene_id]
        if destination.is_ending:
            candidate.status = GameStatus.COMPLETED
            candidate.ending_id = destination.ending_id
        candidate.turn_number += 1
        timestamp = datetime.now(UTC)
        event_metadata = {"choice_id": choice.choice_id, "destination_scene_id": destination.scene_id,
                          "acting_character_id": choice.actor_id or candidate.selected_character_id,
                          "granted_knowledge": choice.grants_knowledge,
                          **simulation_metadata}
        event_metadata["character_state_changes_applied"] = {
            character_id: {
                key: value for key, value in candidate.character_states[character_id].model_dump().items()
                if key != "character_id" and pre_choice_states.get(character_id, {}).get(key) != value
            }
            for character_id in candidate.character_states
            if any(key != "character_id" and pre_choice_states.get(character_id, {}).get(key) != value
                   for key, value in candidate.character_states[character_id].model_dump().items())
        }
        if request_id is not None:
            event_metadata["request_id"] = request_id
        event = GameEvent(event_id=event_id, event_type=EventType.CHOICE_MADE,
                          actor_id=candidate.selected_character_id, scene_id=scene.scene_id,
                          metadata=event_metadata, timestamp=timestamp,
                          visibility=choice.event_visibility,
                          witness_ids=choice.witness_character_ids,
                          informed_ids=sorted(({target for targets in choice.knowledge_grants.values()
                                               for target in targets} | set(choice.informed_character_ids))
                                              - {candidate.selected_character_id}),
                          rumoured_ids=choice.rumoured_character_ids,
                          summary=choice.description[:600])
        candidate.event_history.append(event)
        candidate.revision = current.revision + 1
        candidate.updated_at = timestamp
        candidate = GameState.model_validate(candidate.model_dump())
        self.repository.update_game(candidate, expected_revision=current.revision, new_events=[event])
        return candidate.model_copy(deep=True), True


def default_service(content_dir: Path, repository: GameRepository | None = None) -> GameService:
    return GameService.from_directory(content_dir, repository=repository)
