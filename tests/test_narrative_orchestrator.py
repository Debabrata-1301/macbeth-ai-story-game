import json
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from unittest.mock import Mock

import pytest

from macbeth_game.core.settings import Settings
from macbeth_game.domain.models import CharacterState, EventType, GameEvent, GameState, GameStatus
from macbeth_game.engine.content import load_story_content
from macbeth_game.llm.narrative import (
    DialogueEntry,
    NarrativeResponse,
    NarrativeValidationError,
    NarrativeValidator,
)
from macbeth_game.llm.prompts import NarrativePromptBuilder
from macbeth_game.llm.provider import LLMError
from macbeth_game.rag.documents import RetrievalPassage, RetrievalResult
from macbeth_game.repositories.sqlite_repository import SQLiteGameRepository
from macbeth_game.services.game_service import GameService
from macbeth_game.services.narrative_orchestrator import (
    NarrativeGenerationError,
    NarrativeOrchestrator,
    NarrativePromptError,
    NarrativeResponseError,
    NarrativeRetrievalError,
)

CONTENT_DIR = Path(__file__).parents[1] / "content" / "macbeth"


def test_route_consistency_rejects_unestablished_banquo_ghost():
    state = GameState(game_id="g", selected_character_id="macbeth", current_scene_id="act3_banquet",
                      flags={"banquo_alive": True, "banquo_ghost_seen": False})
    narrative = NarrativeResponse(narration="Banquo's ghost has been seen.", dialogue=[],
                                 atmosphere="A silent hall.", choices=[], source_references=[])
    with pytest.raises(NarrativeValidationError, match="ghost asserted"):
        NarrativeOrchestrator._validate_route_consistency(narrative, state)

    narrative.narration = "I have seen your ghost."
    with pytest.raises(NarrativeValidationError, match="ghost asserted"):
        NarrativeOrchestrator._validate_route_consistency(narrative, state)


def test_route_consistency_rejects_dead_character_dialogue_without_ghost_flag():
    state = GameState(game_id="g", selected_character_id="macbeth", current_scene_id="act3_banquet",
                      flags={"banquo_alive": False, "banquo_ghost_seen": False},
                      character_states={"macbeth": CharacterState(character_id="macbeth"),
                                        "banquo": CharacterState(character_id="banquo", alive=False)})
    narrative = NarrativeResponse(narration="The feast continues.",
        dialogue=[DialogueEntry(speaker="banquo", text="I remain." )], atmosphere="A silent hall.",
        choices=[], source_references=[])
    with pytest.raises(NarrativeValidationError, match="dead character banquo"):
        NarrativeOrchestrator._validate_route_consistency(narrative, state)


def _passage():
    return RetrievalPassage(
        chunk_id="rag-chunk-1", text="Thunder and lightning on the heath.",
        source_filename="macbeth_original.pdf", source_checksum=sha256(b"source").hexdigest(),
        page_start=3, page_end=3, act_id="act_1", scene_id="scene_3", score=0.94,
    )


def _narrative_json(game_service, passages, speaker="macbeth"):
    game = game_service.get_game(_game_id(game_service))
    choices = [item["choice"] for item in game_service.available_choices(game.game_id) if item["available"]]
    return json.dumps({
        "narration": "I ride through the rain beneath a darkening sky.",
        "dialogue": [{"speaker": speaker, "text": "The night is strange."}],
        "atmosphere": "Thunder shakes the heath.",
        "choices": [{"choice_id": item.choice_id, "text": item.description} for item in choices],
        "source_references": [{"source_document": passages[0].source_filename,
                               "act": passages[0].act_id, "scene": passages[0].scene_id,
                               "page_number": passages[0].page_start,
                               "reference_id": passages[0].chunk_id}],
    })


def _game_id(service):
    return service._test_game_id


class FakeRetriever:
    def __init__(self, passages=None, error=None):
        self.passages = passages or [_passage()]
        self.error = error
        self.calls = []
        self.vector_store = Mock()
        self.vector_store.build.side_effect = AssertionError("orchestrator must not rebuild FAISS")

    def retrieve(self, query, top_k=4, *, act_id=None, scene_id=None):
        self.calls.append((query, top_k, act_id, scene_id))
        if self.error:
            raise self.error
        passages = [p for p in self.passages if not act_id or (p.act_id == act_id and p.scene_id == scene_id)]
        return RetrievalResult(query=query, passages=passages, embedding_model="fake-embed",
                               vector_dimension=2, metric="cosine")


class FakeProvider:
    model_name = "fake-local-model"

    def __init__(self, output, error=None):
        self.output = output
        self.error = error
        self.calls = []

    def check_connection(self):
        return True

    def generate(self, prompt, *, temperature=0.7, max_tokens=700):
        self.calls.append((prompt, temperature, max_tokens))
        if self.error:
            raise self.error
        return self.output


class RecordingPromptBuilder:
    def __init__(self):
        self.delegate = NarrativePromptBuilder()
        self.inputs = []

    def build(self, prompt_input):
        self.inputs.append(prompt_input)
        return self.delegate.build(prompt_input)


class RecordingValidator:
    def __init__(self):
        self.delegate = NarrativeValidator()
        self.calls = []

    def validate(self, raw_output, **kwargs):
        self.calls.append((raw_output, kwargs))
        return self.delegate.validate(raw_output, **kwargs)


@pytest.fixture
def context(tmp_path):
    content = load_story_content(CONTENT_DIR)
    repository = SQLiteGameRepository(tmp_path / "orchestrator.sqlite3")
    service = GameService(content, repository=repository)
    state = service.start_game("macbeth")
    service._test_game_id = state.game_id
    return service, repository, state.game_id


def _orchestrator(service, *, retriever=None, provider=None, builder=None, validator=None,
                  settings=None):
    passages = [_passage()]
    retriever = retriever or FakeRetriever(passages)
    provider = provider or FakeProvider(_narrative_json(service, passages))
    return NarrativeOrchestrator(
        service, retriever, provider, settings or Settings(_env_file=None),
        prompt_builder=builder, validator=validator,
    )


def test_successful_orchestration_coordinates_all_existing_interfaces(context):
    service, _repository, game_id = context
    source_scene = service.get_scene(game_id)
    retriever = FakeRetriever([_passage().model_copy(update={
        "act_id": source_scene.source_act_id, "scene_id": source_scene.source_scene_id,
    })])
    provider = FakeProvider(_narrative_json(service, retriever.passages))
    builder = RecordingPromptBuilder()
    validator = RecordingValidator()
    settings = Settings(_env_file=None, generation_temperature=0.25, generation_max_tokens=450,
                        narrative_retrieval_top_k=3)
    result = NarrativeOrchestrator(service, retriever, provider, settings,
                                   prompt_builder=builder, validator=validator).generate(game_id)

    assert result.narration.startswith("I ride")
    assert retriever.calls[0][1] == 3
    assert retriever.calls[0][2:] == (None, None)
    assert "The Heath Before Battle" in retriever.calls[0][0]
    assert "Campaign: macbeth" in retriever.calls[0][0]
    assert "Macbeth" in retriever.calls[0][0]
    prompt_input = builder.inputs[0]
    assert prompt_input.character.character_id == "macbeth"
    assert prompt_input.scene.scene_id == "heath_before_battle"
    assert prompt_input.game_state.game_id == game_id
    assert prompt_input.event_history[0].event_type is EventType.GAME_STARTED
    assert prompt_input.retrieved_passages[0].chunk_id == "rag-chunk-1"
    assert len(prompt_input.available_choices) == 2
    assert "The Heath Before Battle" in provider.calls[0][0]
    assert len(provider.calls) == 1
    assert provider.calls[0][1:] == (0.25, 450)
    assert validator.calls[0][0] == provider.output
    assert result.source_references[0].reference_id == "rag-chunk-1"
    assert retriever.vector_store.build.call_count == 0


def test_character_knowledge_and_events_are_scoped_to_selected_character(context):
    service, _repository, game_id = context
    known_state = service.get_game(game_id)
    known_state.character_states["macbeth"].known_facts.add("witches_prophesied_kingship")
    known_state.character_states["banquo"].known_facts.add("banquo_private_suspicion")
    retriever = FakeRetriever()
    provider = FakeProvider(_narrative_json(service, retriever.passages))
    original_get_game = service.get_game
    reads = 0

    def get_game_with_character_knowledge(requested_game_id):
        nonlocal reads
        reads += 1
        return known_state if reads == 1 else original_get_game(requested_game_id)

    service.get_game = get_game_with_character_knowledge
    private_event = GameEvent(event_id="private-banquo", event_type=EventType.CHOICE_MADE,
                              actor_id="banquo", scene_id="heath_before_battle",
                              metadata={"private_thought": "Macbeth suspects the crown"})
    consequence_details = GameEvent(
        event_id="own-choice-with-private-consequences", event_type=EventType.CHOICE_MADE,
        actor_id="macbeth", scene_id="heath_before_battle",
        metadata={"choice_id": "press_to_forres", "destination_scene_id": "weird_sisters",
                  "character_state_changes_applied": {"banquo": {"guilt": 99}},
                  "private_npc_guilt": "hidden_npc_guilt"},
    )
    service.list_events = Mock(return_value=[*service.list_events(game_id), private_event, consequence_details])
    prompt_builder = RecordingPromptBuilder()
    orchestrator = _orchestrator(service, retriever=retriever, provider=provider, builder=prompt_builder)
    orchestrator.generate(game_id)
    events = prompt_builder.inputs[0].event_history
    assert all(event.actor_id == "macbeth" for event in events)
    assert all(event.event_id != "private-banquo" for event in events)
    assert "private_thought" not in prompt_builder.delegate.build(prompt_builder.inputs[0])
    assert "private_npc_guilt" not in prompt_builder.delegate.build(prompt_builder.inputs[0])
    assert "hidden_npc_guilt" not in prompt_builder.delegate.build(prompt_builder.inputs[0])
    assert "witches_prophesied_kingship" in prompt_builder.inputs[0].character_context[0]
    assert "witches_prophesied_kingship" in retriever.calls[0][0]
    assert "banquo_private_suspicion" not in prompt_builder.delegate.build(prompt_builder.inputs[0])


def test_macbeths_guilt_and_banquo_history_reach_the_ghost_scene_prompt(context):
    service, _repository, game_id = context
    for choice in (
        "press_to_forres", "tell_banquo", "write_to_lady", "continue_to_regicide",
        "proceed_with_murder", "frame_chamberlains", "accuse_guards", "claim_crown",
        "isolate_banquo", "order_banquo_murder", "banquo_falls_fleance_escapes", "banquet_ghost",
    ):
        game = service.execute_choice(game_id, choice)
    assert game.current_scene_id == "act3_ghost"
    assert game.character_states["macbeth"].guilt >= 35
    relation = next(item for item in game.relationships
                    if item.character_a == "macbeth" and item.character_b == "banquo")
    assert relation.hostility >= 30

    source_scene = service.get_scene(game_id)
    retriever = FakeRetriever([_passage().model_copy(update={
        "act_id": source_scene.source_act_id, "scene_id": source_scene.source_scene_id,
    })])
    provider = FakeProvider(_narrative_json(service, retriever.passages, speaker="macbeth"))
    builder = RecordingPromptBuilder()
    NarrativeOrchestrator(service, retriever, provider, Settings(_env_file=None),
                          prompt_builder=builder).generate(game_id)
    context_lines = "\n".join(builder.inputs[0].character_context)
    assert "guilt is weighing heavily" in context_lines
    assert "Directional relationship macbeth to banquo" in context_lines
    assert "Remembered betrayal" in context_lines
    assert "Banquo" in context_lines
    assert "guilt is weighing heavily" in provider.calls[0][0]


def test_lady_macbeth_guilt_survives_restart_and_shapes_crisis_narration_context(tmp_path):
    database = tmp_path / "lady-memory.sqlite3"
    service = GameService(load_story_content(CONTENT_DIR), repository=SQLiteGameRepository(database))
    game = service.start_game("lady_macbeth")
    service._test_game_id = game.game_id
    for choice in (
        "lady_macbeth_ambition", "lady_macbeth_prepare", "lady_macbeth_conceal",
        "lady_macbeth_protect", "lady_macbeth_warn_banquo",
    ):
        game = service.execute_choice(game.game_id, choice)
    assert game.current_scene_id == "lady_crisis"
    guilt_at_crisis = game.character_states["lady_macbeth"].guilt
    assert guilt_at_crisis >= 60

    resumed = GameService(load_story_content(CONTENT_DIR), repository=SQLiteGameRepository(database))
    resumed._test_game_id = game.game_id
    loaded = resumed.get_game(game.game_id)
    assert loaded.character_states["lady_macbeth"].guilt == guilt_at_crisis
    assert any(memory.category == "secret" and memory.event_id == loaded.event_history[3].event_id
               for memory in loaded.memories if memory.character_id == "lady_macbeth")

    source_scene = resumed.get_scene(game.game_id)
    retriever = FakeRetriever([_passage().model_copy(update={
        "act_id": source_scene.source_act_id, "scene_id": source_scene.source_scene_id,
    })])
    provider = FakeProvider(_narrative_json(resumed, retriever.passages, speaker="lady_macbeth"))
    builder = RecordingPromptBuilder()
    NarrativeOrchestrator(resumed, retriever, provider, Settings(_env_file=None),
                          prompt_builder=builder).generate(game.game_id)
    context_lines = "\n".join(builder.inputs[0].character_context)
    assert "guilt is weighing heavily" in context_lines
    assert "emotional stability is fragile" in context_lines
    assert "Remembered secret" in context_lines
    assert "guilt is weighing heavily" in provider.calls[0][0]


def test_private_macbeth_campaign_decision_does_not_cross_into_banquo_campaign(tmp_path):
    service = GameService(load_story_content(CONTENT_DIR), repository=SQLiteGameRepository(
        tmp_path / "separate-campaigns.sqlite3"))
    macbeth = service.start_game("macbeth")
    banquo = service.start_game("banquo")
    service.execute_choice(macbeth.game_id, "press_to_forres")
    macbeth = service.execute_choice(macbeth.game_id, "hide_prophecy")
    assert "witches_prophesied_kingship" in macbeth.character_states["macbeth"].known_facts

    banquo = service.get_game(banquo.game_id)
    assert banquo.campaign_id == "banquo"
    assert banquo.current_scene_id == "banquo_heath"
    assert "witches_prophesied_kingship" not in banquo.character_states["banquo"].known_facts
    assert banquo.flags == {}
    assert len(banquo.event_history) == 1

    service._test_game_id = banquo.game_id
    retriever = FakeRetriever()
    provider = FakeProvider(_narrative_json(service, retriever.passages, speaker="banquo"))
    builder = RecordingPromptBuilder()
    NarrativeOrchestrator(service, retriever, provider, Settings(_env_file=None),
                          prompt_builder=builder).generate(banquo.game_id)
    prompt = provider.calls[0][0]
    assert '"campaign_id":"banquo"' in prompt
    assert "witches_prophesied_kingship" not in prompt
    assert all(event.actor_id == "banquo" for event in builder.inputs[0].event_history)


def test_latest_accepted_action_is_resolved_from_authored_event(context):
    service, _repository, game_id = context
    accepted_event = GameEvent(event_id="accepted-1", event_type=EventType.CHOICE_MADE,
                               actor_id="macbeth", scene_id="heath_before_battle",
                               metadata={"choice_id": "press_to_forres"})
    service.list_events = Mock(return_value=[*service.list_events(game_id), accepted_event])
    retriever = FakeRetriever()
    provider = FakeProvider(_narrative_json(service, retriever.passages))
    builder = RecordingPromptBuilder()
    _orchestrator(service, retriever=retriever, provider=provider, builder=builder).generate(game_id)
    assert builder.inputs[0].accepted_action.choice_id == "press_to_forres"


def test_generation_does_not_transition_or_write_game_state(context, monkeypatch):
    service, repository, game_id = context
    before = service.get_game(game_id).model_dump(mode="json")
    transition = Mock(side_effect=AssertionError("must not execute a choice"))
    monkeypatch.setattr(service, "execute_choice", transition)
    monkeypatch.setattr(repository, "update_game", Mock(side_effect=AssertionError("must not persist")))
    monkeypatch.setattr(repository, "save_new_game", Mock(side_effect=AssertionError("must not save")))

    _orchestrator(service).generate(game_id)

    assert transition.call_count == 0
    assert service.get_game(game_id).model_dump(mode="json") == before
    repository.update_game.assert_not_called()
    repository.save_new_game.assert_not_called()


def test_retrieval_failure_is_reported_with_a_typed_error(context):
    service, _repository, game_id = context
    orchestrator = _orchestrator(service, retriever=FakeRetriever(error=RuntimeError("index unavailable")))
    with pytest.raises(NarrativeRetrievalError, match="Could not retrieve"):
        orchestrator.generate(game_id)


def test_ollama_failure_is_reported_with_a_typed_error(context):
    service, _repository, game_id = context
    retriever = FakeRetriever()
    provider = FakeProvider("", error=LLMError("offline"))
    with pytest.raises(NarrativeGenerationError, match="Local narrative generation failed"):
        _orchestrator(service, retriever=retriever, provider=provider).generate(game_id)


def test_invalid_generated_narrative_is_reported_with_a_typed_error(context, caplog):
    service, _repository, game_id = context
    invalid = _narrative_json(service, [_passage()], speaker="duncan")
    orchestrator = _orchestrator(service, provider=FakeProvider(invalid))
    with pytest.raises(NarrativeResponseError, match="failed validation") as error:
        orchestrator.generate(game_id)
    assert isinstance(error.value.__cause__, NarrativeValidationError)
    assert error.value.validation_exception_type == "NarrativeValidationError"
    assert error.value.diagnostic_reason == "Unknown dialogue speaker ID"
    assert f"game_id={game_id}" in caplog.text
    assert "scene_id=heath_before_battle" in caplog.text
    assert "error_category=narrative_validation_failed" in caplog.text
    assert "exception_type=NarrativeValidationError" in caplog.text
    assert "reason=Unknown dialogue speaker ID" in caplog.text
    assert "The night is strange" not in caplog.text


@pytest.mark.parametrize(("path", "speaker_id"), [
    (("press_to_forres", "tell_banquo"), "duncan"),
    (("press_to_forres",), "weird_sisters"),
])
def test_registered_non_playable_speakers_are_authorized_only_in_participating_scenes(
    context, path, speaker_id
):
    service, _repository, game_id = context
    for choice_id in path:
        service.execute_choice(game_id, choice_id)
    retriever = FakeRetriever()
    provider = FakeProvider(_narrative_json(service, retriever.passages, speaker=speaker_id))
    result = _orchestrator(service, retriever=retriever, provider=provider).generate(game_id)
    assert result.dialogue[0].speaker == speaker_id


def test_prompt_builder_failure_is_distinct(context):
    service, _repository, game_id = context
    broken_builder = Mock()
    broken_builder.build.side_effect = ValueError("prompt limit")
    with pytest.raises(NarrativePromptError):
        _orchestrator(service, builder=broken_builder).generate(game_id)


def test_private_historical_events_do_not_change_authoritative_state(context):
    service, _repository, game_id = context
    initial = deepcopy(service.get_game(game_id).model_dump(mode="json"))
    _orchestrator(service).generate(game_id)
    final = service.get_game(game_id).model_dump(mode="json")
    assert final == initial


@pytest.mark.parametrize(("path", "ending_scene"), [
    (("press_to_forres", "tell_banquo", "seek_counsel", "heed_banquo"), "patient_ending"),
    (("press_to_forres", "tell_banquo", "write_to_lady", "lady_counsel_ambition"), "ambition_ending"),
    (("search_the_heath", "hide_prophecy", "leave_for_inverness", "end_in_isolation"), "solitary_ending"),
])
def test_terminal_scene_retry_accepts_empty_choices_and_preserves_completed_game(
    context, path, ending_scene
):
    service, _repository, game_id = context
    for choice_id in path:
        service.execute_choice(game_id, choice_id)

    completed = service.get_game(game_id)
    assert completed.status is GameStatus.COMPLETED
    assert completed.current_scene_id == ending_scene
    assert service.available_choices(game_id) == []

    retriever = FakeRetriever()
    provider = FakeProvider(_narrative_json(service, retriever.passages))
    orchestrator = _orchestrator(service, retriever=retriever, provider=provider)
    before_retry = service.get_game(game_id).model_dump(mode="json")
    response = orchestrator.generate(game_id)
    assert response.choices == []

    invented = json.loads(provider.output)
    invented["choices"] = [{"choice_id": "invented_ending_choice", "text": "Continue"}]
    provider.output = json.dumps(invented)
    response = orchestrator.generate(game_id)
    assert response.choices == []
    assert service.get_game(game_id).model_dump(mode="json") == before_retry
