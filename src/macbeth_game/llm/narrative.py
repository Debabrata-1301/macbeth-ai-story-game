"""Structured, validated narrative output from a local language model."""

from collections.abc import Collection, Sequence

from pydantic import Field, ValidationError, field_validator

from macbeth_game.domain.models import ChoiceDefinition, DomainModel
from macbeth_game.rag.documents import RetrievalPassage


class NarrativeValidationError(ValueError):
    """Generated narrative is malformed or violates engine-provided constraints."""


class DialogueEntry(DomainModel):
    speaker: str = Field(min_length=1, max_length=120)
    text: str = Field(min_length=1, max_length=3000)

    @field_validator("speaker", "text")
    @classmethod
    def require_non_whitespace(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value


class NarrativeChoice(DomainModel):
    choice_id: str = Field(min_length=1, max_length=100)
    text: str = Field(min_length=1, max_length=1000)

    @field_validator("choice_id", "text")
    @classmethod
    def require_non_whitespace(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value


class SourceReference(DomainModel):
    source_document: str = Field(min_length=1, max_length=240)
    act: str | None = Field(default=None, max_length=80)
    scene: str | None = Field(default=None, max_length=80)
    page_number: int | None = Field(default=None, ge=1)
    reference_id: str | None = Field(default=None, max_length=120)

    @field_validator("source_document", "act", "scene", "reference_id")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("must not be blank when provided")
        return value


class NarrativeResponse(DomainModel):
    narration: str = Field(min_length=1, max_length=10000)
    dialogue: list[DialogueEntry]
    atmosphere: str = Field(min_length=1, max_length=1500)
    choices: list[NarrativeChoice]
    source_references: list[SourceReference]

    @field_validator("narration", "atmosphere")
    @classmethod
    def require_non_whitespace(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value


class NarrativeValidator:
    """Validates LLM output against speakers, choices, and passages supplied by the caller."""

    @staticmethod
    def _reference_matches(reference: SourceReference, passage: RetrievalPassage) -> bool:
        if reference.source_document != passage.source_filename:
            return False
        if reference.reference_id is not None and reference.reference_id != passage.chunk_id:
            return False
        if reference.act is not None and reference.act != passage.act_id:
            return False
        if reference.scene is not None and reference.scene != passage.scene_id:
            return False
        if reference.page_number is not None:
            if passage.page_start is None or passage.page_end is None:
                return False
            if not passage.page_start <= reference.page_number <= passage.page_end:
                return False
        return True

    def validate(
        self,
        raw_output: str,
        *,
        allowed_speakers: Collection[str],
        engine_choices: Sequence[ChoiceDefinition],
        retrieved_passages: Sequence[RetrievalPassage],
    ) -> NarrativeResponse:
        """Parse JSON and reject any speaker, choice, or source outside supplied context."""
        try:
            response = NarrativeResponse.model_validate_json(raw_output)
        except (ValidationError, ValueError, TypeError) as exc:
            raise NarrativeValidationError(f"Malformed narrative response: {exc}") from exc

        speaker_ids = set(allowed_speakers)
        unknown_speakers = sorted({line.speaker for line in response.dialogue} - speaker_ids)
        if unknown_speakers:
            raise NarrativeValidationError(f"Unknown dialogue speaker(s): {', '.join(unknown_speakers)}")

        allowed_choices: dict[str, ChoiceDefinition] = {}
        for choice in engine_choices:
            if choice.choice_id in allowed_choices:
                raise NarrativeValidationError(
                    f"Engine supplied duplicate choice ID: {choice.choice_id}"
                )
            allowed_choices[choice.choice_id] = choice

        # A terminal response has no player actions. Ignore any model-invented ending choices;
        # the engine's empty authorized list is the only value returned to the UI.
        if not allowed_choices:
            response.choices = []
        response_ids = [choice.choice_id for choice in response.choices]
        if len(response_ids) != len(set(response_ids)):
            raise NarrativeValidationError("Narrative response contains duplicate choice IDs")
        response_id_set = set(response_ids)
        unknown_choices = response_id_set - allowed_choices.keys()
        if unknown_choices:
            raise NarrativeValidationError(
                f"Unknown choice ID(s): {', '.join(sorted(unknown_choices))}"
            )
        missing_choices = allowed_choices.keys() - response_id_set
        if missing_choices:
            raise NarrativeValidationError(
                f"Narrative response omitted engine-authorized choice(s): {', '.join(sorted(missing_choices))}"
            )

        response.source_references = [
            reference for reference in response.source_references
            if reference.reference_id is not None
            and any(self._reference_matches(reference, passage) for passage in retrieved_passages)
        ]

        # Keep the engine's choice order while retaining only model-authored display text.
        display_text = {choice.choice_id: choice.text for choice in response.choices}
        response.choices = [
            NarrativeChoice(choice_id=choice.choice_id, text=display_text[choice.choice_id])
            for choice in engine_choices
        ]
        return response
