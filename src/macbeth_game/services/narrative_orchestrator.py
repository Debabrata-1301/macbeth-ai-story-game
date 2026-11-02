"""Coordinate read-only game context, local RAG, and validated narrative generation."""

import logging
import re
from collections.abc import Sequence
from time import perf_counter

from macbeth_game.core.settings import Settings
from macbeth_game.domain.models import ChoiceDefinition, EventType, GameEvent
from macbeth_game.engine.content import StoryContent
from macbeth_game.llm.narrative import (
    NarrativeResponse,
    NarrativeValidationError,
    NarrativeValidator,
)
from macbeth_game.llm.prompts import NarrativePromptBuilder, PromptInput
from macbeth_game.llm.provider import LLMError, LLMProvider, LLMTimeout, LLMUnavailable
from macbeth_game.rag.documents import RetrievalPassage
from macbeth_game.rag.retriever import RAGRetriever
from macbeth_game.services.game_service import GameService

logger = logging.getLogger(__name__)


class NarrativeOrchestrationError(RuntimeError):
    """Base error raised while preparing or generating game narration."""


class NarrativeContextError(NarrativeOrchestrationError):
    """The game context is inconsistent or changed while it was being read."""


class NarrativeRetrievalError(NarrativeOrchestrationError):
    """Canonical source retrieval failed."""


class NarrativePromptError(NarrativeOrchestrationError):
    """The prompt could not be constructed from the current game context."""


class NarrativeGenerationError(NarrativeOrchestrationError):
    """The configured local language model failed to generate a response."""


class NarrativeProviderUnavailable(NarrativeGenerationError):
    """The local Ollama service could not be reached."""


class NarrativeGenerationTimeout(NarrativeGenerationError):
    """Ollama did not finish within the configured request timeout."""


class NarrativeResponseError(NarrativeOrchestrationError):
    """Generated output failed narrative schema or provenance validation."""

    def __init__(self, message: str, *, diagnostic_reason: str = "Narrative output violated validation rules",
                 validation_exception_type: str = "NarrativeValidationError"):
        super().__init__(message)
        self.diagnostic_reason = diagnostic_reason
        self.validation_exception_type = validation_exception_type


class NarrativeOrchestrator:
    """Read game context, retrieve canonical passages, and return validated narration.

    This service only reads the GameService and RAG interfaces. It never applies choices,
    changes persistence, or builds a vector index.
    """

    def __init__(
        self,
        game_service: GameService,
        rag_retriever: RAGRetriever,
        llm_provider: LLMProvider,
        settings: Settings,
        *,
        prompt_builder: NarrativePromptBuilder | None = None,
        validator: NarrativeValidator | None = None,
    ):
        self.game_service = game_service
        self.rag_retriever = rag_retriever
        self.llm_provider = llm_provider
        self.settings = settings
        self.prompt_builder = prompt_builder or NarrativePromptBuilder()
        self.validator = validator or NarrativeValidator()
        # The prompt builder accepts at most four retrieved passages.
        self.rag_top_k = settings.narrative_retrieval_top_k

    @staticmethod
    def _validate_route_consistency(response: NarrativeResponse, state) -> None:
        """Reject a short list of explicit, high-confidence route contradictions."""
        text = " ".join([response.narration, response.atmosphere,
                          *(line.text for line in response.dialogue)]).casefold()
        flags = state.flags
        contradictions = []
        for line in response.dialogue:
            speaker_state = state.character_states.get(line.speaker)
            ghost_allowed = line.speaker == "banquo" and flags.get("banquo_ghost_seen", False)
            if speaker_state and not speaker_state.alive and not ghost_allowed:
                contradictions.append(f"dead character {line.speaker} speaks without an established ghost")
        if not flags.get("banquo_ghost_seen", False) and (
                re.search(r"\bbanquo(?:['’]s)? ghost (?:has been seen|has appeared|appeared|stands|is here)\b", text)
                or re.search(r"\b(?:i|we) (?:have )?(?:seen|saw) (?:banquo(?:['’]s)?|your) ghost\b", text)):
            contradictions.append("Banquo ghost asserted before the route establishes it")
        if flags.get("banquo_alive") is True and re.search(
                r"\bbanquo (?:is dead|was killed|lies dead|is a corpse)\b", text):
            contradictions.append("living Banquo described as dead")
        if flags.get("banquo_alive") is False and re.search(
                r"\bbanquo (?:is alive|survived|still lives)\b", text):
            contradictions.append("dead Banquo described as alive")
        if flags.get("duncan_murdered") is False and re.search(
                r"\bduncan (?:was murdered|lies dead|is dead|was slain)\b", text):
            contradictions.append("Duncan described as murdered after the player spared him")
        if flags.get("macduff_family_safe") is True and re.search(
                r"\b(?:macduff['’]s )?family (?:was murdered|was killed|lies dead)\b", text):
            contradictions.append("protected Macduff family described as killed")
        if flags.get("macduff_family_lost") is True and re.search(
                r"\b(?:macduff['’]s )?family (?:is safe|escaped safely|survived)\b", text):
            contradictions.append("lost Macduff family described as safe")
        if contradictions:
            raise NarrativeValidationError("Route consistency conflict: " + "; ".join(contradictions))

    @staticmethod
    def _timeline_context(state, scene, events: Sequence[GameEvent], character_id: str) -> dict:
        flags = state.flags

        def outcome(positive: tuple[str, ...], negative: tuple[str, ...], yes: str, no: str) -> str:
            for key in positive:
                if key in flags:
                    return yes if flags[key] else no
            if any(flags.get(key) is True for key in negative):
                return no
            return "unresolved in authoritative game state"

        return {
            "canonical_source_is_reference_not_occurrence": True,
            "scene_classification": scene.source_classification,
            "duncan": outcome(("duncan_murdered",), ("duncan_spared",), "murdered", "spared"),
            "banquo": outcome(("banquo_killed", "banquo_died", "banquo_murdered"),
                              ("banquo_alive", "banquo_spared", "banquo_survived"), "dead", "alive"),
            "banquo_ghost": "established" if flags.get("banquo_ghost_seen") else "not established",
            "fleance": outcome(("fleance_captured",), ("fleance_escaped",), "captured", "escaped"),
            "macduff_family": outcome(("macduff_family_lost",),
                                      ("macduff_family_safe", "macduff_family_hidden"), "lost", "safe or hidden"),
            "lady_macbeth": {
                "confession": bool(flags.get("lady_confessed")),
                "reconciliation": bool(flags.get("lady_reconciled")),
                "survival": "survived" if flags.get("lady_survived") else "unresolved",
            },
            "malcolm_alliance": "established" if flags.get("malcolm_macduff_alliance") else "not established",
            "ending": state.ending_id,
            "recent_player_decisions": [
                {"event_id": event.event_id, "actor": event.actor_id,
                 "choice_id": event.metadata.get("choice_id"), "summary": event.summary,
                 "visibility": event.visibility}
                for event in events[-12:]
            ],
            "warning": "Narrator-only consistency facts. Do not reveal them unless this protagonist knows them.",
        }

    @staticmethod
    def _accepted_action(events: Sequence[GameEvent], content: StoryContent,
                         character_id: str) -> ChoiceDefinition | None:
        for event in reversed(events):
            if event.event_type is not EventType.CHOICE_MADE or event.actor_id != character_id:
                continue
            scene = content.scenes.get(event.scene_id)
            choice_id = event.metadata.get("choice_id")
            choice = next((item for item in scene.available_choices
                           if item.choice_id == choice_id), None) if scene else None
            if choice is None:
                raise NarrativeContextError(
                    "The latest accepted choice event does not match authored story content"
                )
            return choice
        return None

    @staticmethod
    def _visible_history(events: Sequence[GameEvent], character_id: str) -> list[GameEvent]:
        visible: list[GameEvent] = []
        for event in events:
            can_know = (event.actor_id == character_id or event.visibility == "public"
                        or character_id in event.witness_ids or character_id in event.informed_ids
                        or character_id in event.rumoured_ids)
            if not can_know:
                continue
            safe_metadata = {
                key: value for key, value in event.metadata.items()
                if key in {"choice_id", "destination_scene_id", "acting_character_id"}
            }
            visible.append(event.model_copy(update={"metadata": safe_metadata}))
        return visible

    @staticmethod
    def _retrieval_query(campaign_id: str, character_name: str, scene_title: str, scene_summary: str,
                         canonical_reference: str | None, known_facts: Sequence[str],
                         accepted_action: ChoiceDefinition | None) -> str:
        parts = [f"Campaign: {campaign_id}", character_name, scene_title, scene_summary]
        if canonical_reference:
            parts.append(canonical_reference)
        if known_facts:
            parts.append("Character-known facts: " + "; ".join(known_facts[:20]))
        if accepted_action:
            parts.append("Accepted action: " + accepted_action.description)
        return "\n".join(parts)[:1200].strip()

    @staticmethod
    def _allowed_speakers(content: StoryContent, scene_participants: Sequence[str],
                          selected_character_id: str) -> set[str]:
        # Dialogue always uses stable IDs. Names are presentation metadata, never authorization.
        return (set(scene_participants) & set(content.speakers)) | {selected_character_id}

    @staticmethod
    def _validation_diagnostic(exc: NarrativeValidationError) -> str:
        message = str(exc)
        if message.startswith("Malformed narrative response:"):
            return "Malformed JSON or narrative schema"
        if message.startswith("Unknown dialogue speaker"):
            return "Unknown dialogue speaker ID"
        if "duplicate choice IDs" in message:
            return "Duplicate narrative choice IDs"
        if message.startswith("Unknown choice ID"):
            return "Model returned an unauthorized choice ID"
        if message.startswith("Narrative response omitted"):
            return "Model omitted an engine-authorized choice ID"
        if message.startswith("Source reference"):
            return "Source reference does not match a retrieved passage"
        return "Narrative output violated validation rules"

    def generate(self, game_id: str, *, retry_count: int = 0) -> NarrativeResponse:
        """Generate narration for the current persisted state without advancing the game."""
        started = perf_counter()
        state = self.game_service.get_game(game_id)
        character_id = state.selected_character_id
        content = self.game_service.content
        character = content.characters.get(character_id)
        scene = content.scenes.get(state.current_scene_id)
        if character is None or scene is None:
            raise NarrativeContextError("Selected character or current scene is missing from story content")

        events = self.game_service.list_events(game_id)
        visible_events = self._visible_history(events, character_id)
        accepted_action = self._accepted_action(visible_events, content, character_id)
        selected_state = state.character_states.get(character_id)
        known_facts = sorted(selected_state.known_facts) if selected_state else []

        # Delegate eligibility and prerequisites to the deterministic game service.
        available = self.game_service.available_choices(game_id)
        engine_choices = [item["choice"] for item in available if item["available"]]
        latest_state = self.game_service.get_game(game_id)
        if latest_state.revision != state.revision:
            logger.warning(
                "Narrative context changed game_id=%s scene_id=%s error_category=narrative_context_changed "
                "exception_type=NarrativeContextError reason=game_revision_changed",
                game_id, scene.scene_id,
            )
            raise NarrativeContextError("Game changed while narrative context was being read; retry")

        query = self._retrieval_query(state.campaign_id, character.name, scene.title, scene.summary,
                                      scene.canonical_reference, known_facts, accepted_action)
        try:
            retrieval_started = perf_counter()
            retrieval = self.rag_retriever.retrieve(
                query, top_k=self.rag_top_k, act_id=scene.source_act_id,
                scene_id=scene.source_scene_id,
            )
        except Exception as exc:
            logger.warning("Local RAG retrieval failed (%s)", type(exc).__name__)
            raise NarrativeRetrievalError("Could not retrieve local Macbeth source passages") from exc
        retrieval_ms = (perf_counter() - retrieval_started) * 1000
        passages: list[RetrievalPassage] = list(retrieval.passages[:4])

        character_context: list[str] = []
        if selected_state:
            character_context.extend([
                "Confirmed facts (engine-authorized): " + "; ".join(known_facts[:30]),
                "Unresolved rumours, suspicions, and beliefs (uncertain, never confirmed facts): " + "; ".join(
                    f"{item.category} ({item.confidence}%)"
                    f": {item.content}"
                    for item in selected_state.uncertain_knowledge[-12:]
                    if item.confirmed_event_id is None
                ),
                "Historical suspicions later confirmed by evidence: " + "; ".join(
                    item.content for item in selected_state.uncertain_knowledge[-12:]
                    if item.confirmed_event_id is not None
                ),
            ])
            emotional_cues = []
            for attribute, threshold, cue in (
                ("guilt", 30, "guilt is weighing heavily"), ("fear", 60, "fear is pronounced"),
                ("stress", 65, "strain is difficult to conceal"), ("hope", 65, "hope is sustaining them"),
                ("confidence", 70, "confidence is strong"), ("ambition", 75, "ambition is driving them"),
                ("resolve", 70, "resolve is firm"), ("isolation", 60, "isolation is deepening"),
            ):
                value = getattr(selected_state, attribute)
                if value >= threshold:
                    emotional_cues.append(f"{cue} ({value}/100)")
            if selected_state.emotional_stability <= 35:
                emotional_cues.append(
                    f"emotional stability is fragile ({selected_state.emotional_stability}/100)"
                )
            if emotional_cues:
                character_context.append(
                    "Current emotional cues from authoritative state: " + "; ".join(emotional_cues)
                )
        scene_people = set(scene.participants)
        memories = [item for item in state.memories
                    if item.character_id == character_id and item.campaign_id == state.campaign_id]
        memories.sort(key=lambda item: (
            item.importance * 2 + (20 if scene_people.intersection(item.related_characters) else 0)
            + max(0, 20 - (state.turn_number - item.created_turn)), item.created_turn
        ), reverse=True)
        for item in memories[:5]:
            character_context.append(
                f"Remembered {item.category} ({item.certainty}; importance {item.importance}): {item.summary}"
            )
        for item in state.commitments:
            authorized = (item.visibility == "public" or character_id == item.owner_id or
                          (item.visibility == "participants" and character_id in {
                              *item.participant_ids, *item.audience_ids,
                          }))
            relevant = bool(scene_people.intersection(item.participant_ids)) or character_id in {
                item.owner_id, *item.participant_ids, *item.audience_ids,
            }
            if authorized and relevant and item.status == "active":
                character_context.append(
                    f"Active {item.kind} ({item.status}; visibility {item.visibility}): {item.summary}"
                )
        for relation in state.relationships:
            if character_id in (relation.character_a, relation.character_b) and {
                relation.character_a, relation.character_b,
            }.intersection(scene_people):
                character_context.append(
                    f"Directional relationship {relation.character_a} to {relation.character_b}: "
                    f"trust {relation.trust}, hostility {relation.hostility}, loyalty {relation.loyalty}, "
                    f"fear {relation.fear}, affection {relation.affection}, respect {relation.respect}."
                )
        try:
            prompt_started = perf_counter()
            prompt = self.prompt_builder.build(PromptInput(
                character=character,
                scene=scene,
                game_state=state,
                accepted_action=accepted_action,
                event_history=visible_events,
                character_context=character_context[:20],
                retrieved_passages=passages,
                available_choices=engine_choices,
                timeline_context={
                    **self._timeline_context(state, scene, visible_events, character_id),
                },
                max_words=self.settings.narrative_max_words,
            ))
        except Exception as exc:
            raise NarrativePromptError("Could not build a narrative prompt from current game context") from exc
        prompt_ms = (perf_counter() - prompt_started) * 1000

        try:
            model_started = perf_counter()
            raw_output = self.llm_provider.generate(
                prompt,
                temperature=self.settings.generation_temperature,
                max_tokens=self.settings.generation_max_tokens,
            )
        except LLMUnavailable as exc:
            logger.warning("Narrative generation failed game_id=%s scene_id=%s error_category=ollama_unavailable "
                           "exception_type=%s reason=local_provider_unavailable",
                           game_id, scene.scene_id, type(exc).__name__)
            raise NarrativeProviderUnavailable("Local Ollama service is unavailable") from exc
        except LLMTimeout as exc:
            logger.warning("Narrative generation failed game_id=%s scene_id=%s error_category=generation_timeout "
                           "exception_type=%s reason=local_generation_timed_out",
                           game_id, scene.scene_id, type(exc).__name__)
            raise NarrativeGenerationTimeout("Local Ollama generation timed out") from exc
        except LLMError as exc:
            logger.warning("Narrative generation failed game_id=%s scene_id=%s "
                           "error_category=ollama_provider_failed exception_type=%s reason=provider_error",
                           game_id, scene.scene_id, type(exc).__name__)
            raise NarrativeGenerationError("Local narrative generation failed") from exc
        except Exception as exc:
            logger.warning("Narrative generation failed game_id=%s scene_id=%s "
                           "error_category=ollama_provider_failed exception_type=%s reason=provider_error",
                           game_id, scene.scene_id, type(exc).__name__)
            raise NarrativeGenerationError("Local narrative generation failed") from exc
        model_ms = (perf_counter() - model_started) * 1000

        speakers = self._allowed_speakers(content, scene.participants, character_id)
        validation_started = perf_counter()
        try:
            response = self.validator.validate(
                raw_output,
                allowed_speakers=speakers,
                engine_choices=engine_choices,
                retrieved_passages=passages,
            )
            for line in response.dialogue:
                speaker_state = state.character_states.get(line.speaker)
                if speaker_state and not speaker_state.alive:
                    ghost_allowed = line.speaker == "banquo" and state.flags.get("banquo_ghost_seen", False)
                    if not ghost_allowed:
                        raise NarrativeValidationError(
                            f"Dead character {line.speaker} cannot speak in this scene"
                        )
            self._validate_route_consistency(response, state)
            validation_ms = (perf_counter() - validation_started) * 1000
            logger.info("narrative_turn_metrics game_id=%s campaign_id=%s scene_id=%s retrieval_scope=%s "
                        "retrieval_count=%d retrieval_ms=%.1f prompt_chars=%d estimated_prompt_tokens=%d "
                        "prompt_ms=%.1f model_ms=%.1f validation_ms=%.1f retry_count=%d "
                        "output_chars=%d citations=%d total_ms=%.1f",
                        game_id, state.campaign_id, scene.scene_id, retrieval.scope_used,
                        len(passages), retrieval_ms, len(prompt), len(prompt)//4, prompt_ms, model_ms, validation_ms,
                        retry_count,
                        len(raw_output), len(response.source_references), (perf_counter()-started)*1000)
            return response
        except NarrativeValidationError as exc:
            diagnostic_reason = self._validation_diagnostic(exc)
            logger.warning(
                "Narrative validation failed game_id=%s scene_id=%s error_category=narrative_validation_failed "
                "exception_type=%s reason=%s",
                game_id, scene.scene_id, type(exc).__name__, diagnostic_reason,
            )
            raise NarrativeResponseError(
                "Generated narrative failed validation",
                diagnostic_reason=diagnostic_reason,
                validation_exception_type=type(exc).__name__,
            ) from exc
