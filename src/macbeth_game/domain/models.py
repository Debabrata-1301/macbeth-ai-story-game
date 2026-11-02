"""Validated domain contracts for the Macbeth narrative game."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StoryMode(StrEnum):
    CANONICAL = "canonical"
    ALTERNATE = "alternate"
    HYBRID = "hybrid"


class NarrativePerspective(StrEnum):
    FIRST_PERSON = "first_person"


class GameStatus(StrEnum):
    ACTIVE = "active"
    COMPLETED = "completed"
    ABANDONED = "abandoned"


class EventType(StrEnum):
    GAME_STARTED = "game_started"
    CHOICE_MADE = "choice_made"
    SCENE_ENTERED = "scene_entered"
    CHARACTER_STATE_CHANGED = "character_state_changed"
    RELATIONSHIP_CHANGED = "relationship_changed"
    GAME_ENDED = "game_ended"


class DomainModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CharacterDefinition(DomainModel):
    character_id: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=120)
    role: str = Field(min_length=1, max_length=160)
    personality: list[str] = Field(min_length=1)
    motivations: list[str] = Field(min_length=1)
    background: str = Field(min_length=1)
    playable: bool = True


class SpeakerDefinition(DomainModel):
    """Stable narration/dialogue identity; NPC speakers are not playable characters."""

    speaker_id: str = Field(min_length=1, max_length=80)
    display_name: str = Field(min_length=1, max_length=120)


class CharacterState(DomainModel):
    character_id: str = Field(min_length=1, max_length=80)
    ambition: int = Field(default=50, ge=0, le=100)
    morality: int = Field(default=50, ge=0, le=100)
    suspicion: int = Field(default=0, ge=0, le=100)
    guilt: int = Field(default=0, ge=0, le=100)
    emotional_stability: int = Field(default=100, ge=0, le=100)
    influence: int = Field(default=50, ge=0, le=100)
    isolation: int = Field(default=25, ge=0, le=100)
    resolve: int = Field(default=50, ge=0, le=100)
    fear: int = Field(default=10, ge=0, le=100)
    stress: int = Field(default=10, ge=0, le=100)
    hope: int = Field(default=50, ge=0, le=100)
    confidence: int = Field(default=50, ge=0, le=100)
    alive: bool = True
    known_facts: set[str] = Field(default_factory=set)
    uncertain_knowledge: list["KnowledgeObservation"] = Field(default_factory=list)


class KnowledgeObservation(DomainModel):
    character_id: str
    content: str = Field(min_length=1, max_length=500)
    category: Literal["rumour", "suspicion", "belief"]
    confidence: int = Field(default=50, ge=0, le=100)
    source: str = Field(min_length=1, max_length=200)
    source_event_id: str
    created_turn: int = Field(ge=0)
    related_characters: list[str] = Field(default_factory=list)
    resolved_by_fact: str | None = None
    confirmed_event_id: str | None = None


class KnowledgeObservationDirective(DomainModel):
    character_id: str
    content: str = Field(min_length=1, max_length=500)
    category: Literal["rumour", "suspicion", "belief"]
    confidence: int = Field(default=50, ge=0, le=100)
    source: str = Field(min_length=1, max_length=200)
    related_characters: list[str] = Field(default_factory=list)
    resolved_by_fact: str | None = None


class CommitmentDirective(DomainModel):
    action: Literal["create", "fulfill", "breach", "reveal"]
    optional: bool = False
    commitment_id: str = Field(min_length=1, max_length=100)
    kind: Literal["promise", "secret"]
    owner_id: str | None = None
    participant_ids: list[str] = Field(default_factory=list)
    summary: str = Field(min_length=1, max_length=500)
    visibility: Literal["private", "participants", "public"] = "participants"
    audience_ids: list[str] = Field(default_factory=list)


class NarrativeCommitment(DomainModel):
    commitment_id: str
    kind: Literal["promise", "secret"]
    owner_id: str
    participant_ids: list[str]
    summary: str
    visibility: Literal["private", "participants", "public"]
    audience_ids: list[str] = Field(default_factory=list)
    created_event_id: str
    created_turn: int = Field(ge=0)
    status: Literal["active", "fulfilled", "broken", "revealed"] = "active"
    resolved_event_id: str | None = None


class CharacterMemory(DomainModel):
    memory_id: str
    character_id: str
    campaign_id: str
    event_id: str
    category: Literal["personal_experience", "conversation", "promise", "secret",
                      "betrayal", "family_event", "political_event", "loss", "decision"]
    summary: str = Field(min_length=1, max_length=600)
    source: str = Field(min_length=1, max_length=200)
    certainty: Literal["confirmed", "rumour", "suspicion", "belief"] = "confirmed"
    importance: int = Field(default=40, ge=0, le=100)
    created_turn: int = Field(ge=0)
    visibility: Literal["private", "participants", "public"] = "private"
    related_characters: list[str] = Field(default_factory=list)
    emotional_significance: int = Field(default=0, ge=-100, le=100)


class ChoiceDefinition(DomainModel):
    choice_id: str = Field(min_length=1, max_length=100)
    action_id: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=1000)
    # None means the selected player character performs the action.
    actor_id: str | None = Field(default=None, min_length=1, max_length=80)
    prerequisites: list[str] = Field(default_factory=list)
    state_flags: dict[str, bool] = Field(default_factory=dict)
    next_scene_id: str | None = Field(default=None, min_length=1, max_length=100)
    conditions: "ChoiceConditions" = Field(default_factory=lambda: ChoiceConditions())
    character_changes: dict[str, dict[str, int | bool]] = Field(default_factory=dict)
    relationship_changes: list["RelationshipChange"] = Field(default_factory=list)
    grants_knowledge: list[str] = Field(default_factory=list)
    knowledge_grants: dict[str, list[str]] = Field(default_factory=dict)
    psychological_changes: dict[str, dict[str, int]] = Field(default_factory=dict)
    knowledge_observations: list[KnowledgeObservationDirective] = Field(default_factory=list)
    commitment_effects: list[CommitmentDirective] = Field(default_factory=list)
    memory_category: Literal["personal_experience", "conversation", "promise", "secret",
                             "betrayal", "family_event", "political_event", "loss", "decision"] = "decision"
    memory_importance: int = Field(default=40, ge=0, le=100)
    event_visibility: Literal["private", "participants", "public"] = "private"
    witness_character_ids: list[str] = Field(default_factory=list)
    informed_character_ids: list[str] = Field(default_factory=list)
    rumoured_character_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def psychology_effects_are_bounded(self):
        allowed = {"ambition", "morality", "suspicion", "guilt", "emotional_stability",
                   "influence", "isolation", "resolve", "fear", "stress", "hope", "confidence"}
        for character_id, changes in self.psychological_changes.items():
            if not character_id or set(changes) - allowed:
                raise ValueError("psychological effects reference an unsupported character or attribute")
            if any(not -100 <= value <= 100 for value in changes.values()):
                raise ValueError("psychological effect deltas must be between -100 and 100")
        return self


class ChoiceConditions(DomainModel):
    required_flags: dict[str, bool] = Field(default_factory=dict)
    required_alive: list[str] = Field(default_factory=list)
    required_known_facts: list[str] = Field(default_factory=list)
    knowledge_character_id: str | None = Field(default=None, min_length=1, max_length=80)
    relationship_character: str | None = None
    relationship_source_character_id: str | None = Field(default=None, min_length=1, max_length=80)
    min_trust: int | None = Field(default=None, ge=-100, le=100)
    max_trust: int | None = Field(default=None, ge=-100, le=100)
    min_hostility: int | None = Field(default=None, ge=0, le=100)
    max_hostility: int | None = Field(default=None, ge=0, le=100)
    minimum_attributes: dict[str, int] = Field(default_factory=dict)
    maximum_attributes: dict[str, int] = Field(default_factory=dict)
    min_loyalty: int | None = Field(default=None, ge=0, le=100)
    min_fear: int | None = Field(default=None, ge=0, le=100)
    min_respect: int | None = Field(default=None, ge=0, le=100)

    @model_validator(mode="after")
    def relationship_target_required(self):
        if any(value is not None for value in (self.min_trust, self.max_trust,
                                                self.min_hostility, self.max_hostility, self.min_loyalty,
                                                self.min_fear, self.min_respect)) and not self.relationship_character:
            raise ValueError("relationship_character is required for relationship thresholds")
        return self

    @model_validator(mode="after")
    def attribute_thresholds_valid(self):
        allowed = {"ambition", "morality", "suspicion", "guilt", "emotional_stability",
                   "influence", "isolation", "resolve", "fear", "stress", "hope", "confidence"}
        if (set(self.minimum_attributes) | set(self.maximum_attributes)) - allowed:
            raise ValueError("attribute thresholds reference an unsupported character attribute")
        if any(not 0 <= value <= 100 for value in (*self.minimum_attributes.values(),
                                                    *self.maximum_attributes.values())):
            raise ValueError("attribute thresholds must be between 0 and 100")
        return self


class RelationshipChange(DomainModel):
    character_id: str = Field(min_length=1, max_length=80)
    # None means the acting character. Explicit sources allow authored effects such as
    # Macbeth trusting Banquo even when a different playable perspective is selected.
    source_character_id: str | None = Field(default=None, min_length=1, max_length=80)
    trust: int = Field(default=0, ge=-100, le=100)
    hostility: int = Field(default=0, ge=-100, le=100)
    loyalty: int = Field(default=0, ge=-100, le=100)
    fear: int = Field(default=0, ge=-100, le=100)
    affection: int = Field(default=0, ge=-100, le=100)
    respect: int = Field(default=0, ge=-100, le=100)


class SceneDefinition(DomainModel):
    scene_id: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=200)
    location: str = Field(min_length=1, max_length=200)
    canonical_reference: str | None = None
    source_classification: Literal["canonical_adaptation", "alternate_history"] = "canonical_adaptation"
    source_act_id: str | None = Field(default=None, pattern=r"^act_[1-5]$")
    source_scene_id: str | None = Field(default=None, pattern=r"^scene_[1-9][0-9]*$")
    participants: list[str] = Field(default_factory=list)
    summary: str = Field(min_length=1)
    opening_narration: str = Field(min_length=1)
    available_choices: list[ChoiceDefinition] = Field(default_factory=list)
    is_ending: bool = False
    ending_id: str | None = None

    @model_validator(mode="after")
    def ending_metadata_consistent(self):
        if self.source_scene_id and not self.source_act_id:
            raise ValueError("source_act_id is required when source_scene_id is supplied")
        if self.is_ending and not self.ending_id:
            raise ValueError("ending_id is required for an ending scene")
        if self.is_ending and self.available_choices:
            raise ValueError("ending scenes cannot offer further choices")
        if not self.is_ending and self.ending_id:
            raise ValueError("ending_id is only valid for an ending scene")
        return self


class RelationshipState(DomainModel):
    character_a: str = Field(min_length=1, max_length=80)
    character_b: str = Field(min_length=1, max_length=80)
    trust: int = Field(default=0, ge=-100, le=100)
    hostility: int = Field(default=0, ge=0, le=100)
    loyalty: int = Field(default=0, ge=0, le=100)
    fear: int = Field(default=0, ge=0, le=100)
    affection: int = Field(default=0, ge=0, le=100)
    respect: int = Field(default=0, ge=0, le=100)

    @model_validator(mode="after")
    def distinct_pair(self):
        if self.character_a == self.character_b:
            raise ValueError("a relationship must be between two distinct characters")
        return self


class GameEvent(DomainModel):
    event_id: str = Field(min_length=1, max_length=100)
    event_type: EventType
    actor_id: str = Field(min_length=1, max_length=80)
    scene_id: str = Field(min_length=1, max_length=100)
    metadata: dict[str, Any] = Field(default_factory=dict)
    # Older event JSON has no visibility contract. Its default is intentionally conservative:
    # only the actor can be assumed to know what happened.
    visibility: Literal["private", "participants", "public", "unknown"] = "unknown"
    witness_ids: list[str] = Field(default_factory=list)
    informed_ids: list[str] = Field(default_factory=list)
    rumoured_ids: list[str] = Field(default_factory=list)
    summary: str | None = Field(default=None, max_length=600)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("timestamp")
    @classmethod
    def require_aware_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        return value.astimezone(UTC)


class GameState(DomainModel):
    game_id: str = Field(min_length=1, max_length=100)
    selected_character_id: str = Field(min_length=1, max_length=80)
    # Missing in Phase 7.1/7.2 save JSON; the default preserves the original Macbeth-led route.
    campaign_id: str = Field(default="macbeth", min_length=1, max_length=80)
    story_mode: StoryMode = StoryMode.HYBRID
    perspective: NarrativePerspective = NarrativePerspective.FIRST_PERSON
    current_scene_id: str = Field(min_length=1, max_length=100)
    character_states: dict[str, CharacterState] = Field(default_factory=dict)
    relationships: list[RelationshipState] = Field(default_factory=list)
    memories: list[CharacterMemory] = Field(default_factory=list)
    commitments: list[NarrativeCommitment] = Field(default_factory=list)
    flags: dict[str, bool] = Field(default_factory=dict)
    turn_number: int = Field(default=0, ge=0)
    status: GameStatus = GameStatus.ACTIVE
    ending_id: str | None = None
    revision: int = Field(default=0, ge=0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    event_history: list[GameEvent] = Field(default_factory=list)

    @field_validator("created_at", "updated_at")
    @classmethod
    def require_aware_utc_timestamps(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("game timestamps must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def selected_character_has_state(self):
        if self.character_states and self.selected_character_id not in self.character_states:
            raise ValueError("selected character must have a character state when states are provided")
        if self.status == GameStatus.COMPLETED and not self.ending_id:
            raise ValueError("completed games require an ending_id")
        return self


# Resolve forward references now that all choice-related contracts are defined.
ChoiceDefinition.model_rebuild()
CharacterState.model_rebuild()


class DialogueLine(DomainModel):
    speaker_id: str = Field(min_length=1, max_length=80)
    text: str = Field(min_length=1, max_length=3000)


class ProposedConsequences(DomainModel):
    state_changes: dict[str, dict[str, int | bool | str]] = Field(default_factory=dict)
    flags: dict[str, bool] = Field(default_factory=dict)


class NarrativeOutput(DomainModel):
    narration: str = Field(min_length=1, max_length=10000)
    dialogue: list[DialogueLine] = Field(default_factory=list)
    available_choices: list[ChoiceDefinition] = Field(default_factory=list)
    proposed_consequences: ProposedConsequences = Field(default_factory=ProposedConsequences)
