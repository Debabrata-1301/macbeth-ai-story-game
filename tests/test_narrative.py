import json
from copy import deepcopy
from hashlib import sha256

import pytest
from pydantic import ValidationError

from macbeth_game.domain.models import ChoiceDefinition
from macbeth_game.llm.narrative import (
    DialogueEntry,
    NarrativeChoice,
    NarrativeResponse,
    NarrativeValidationError,
    NarrativeValidator,
    SourceReference,
)
from macbeth_game.rag.documents import RetrievalPassage


def _choices():
    return [
        ChoiceDefinition(choice_id="press_on", action_id="ride_on", description="Ride on.",
                         next_scene_id="next_scene"),
        ChoiceDefinition(choice_id="search_heath", action_id="search", description="Search the heath.",
                         next_scene_id="next_scene"),
    ]


def _passages():
    return [RetrievalPassage(
        chunk_id="chunk-1", text="The heath is storm-swept.", source_filename="macbeth.pdf",
        source_checksum=sha256(b"source").hexdigest(), page_start=8, page_end=9,
        act_id="act_1", scene_id="scene_3", score=0.87,
    )]


def _payload(**updates):
    value = {
        "narration": "I ride beneath the storm and listen for Banquo.",
        "dialogue": [{"speaker": "banquo", "text": "The night grows strange."}],
        "atmosphere": "Rain lashes the heath; thunder rolls nearby.",
        "choices": [
            {"choice_id": "press_on", "text": "Ride toward Forres."},
            {"choice_id": "search_heath", "text": "Study the strange lights."},
        ],
        "source_references": [{
            "source_document": "macbeth.pdf", "act": "act_1", "scene": "scene_3",
            "page_number": 8, "reference_id": "chunk-1",
        }],
    }
    value.update(updates)
    return value


def _validate(payload, *, choices=None, passages=None):
    return NarrativeValidator().validate(
        json.dumps(payload),
        allowed_speakers={"macbeth", "banquo", "duncan", "weird_sisters"},
        engine_choices=_choices() if choices is None else choices,
        retrieved_passages=_passages() if passages is None else passages,
    )


def test_valid_narrative_response_and_structured_fields():
    response = _validate(_payload())
    assert isinstance(response, NarrativeResponse)
    assert response.narration.startswith("I ride")
    assert response.dialogue == [DialogueEntry(speaker="banquo", text="The night grows strange.")]
    assert response.choices[0] == NarrativeChoice(choice_id="press_on", text="Ride toward Forres.")
    assert response.source_references[0] == SourceReference(
        source_document="macbeth.pdf", act="act_1", scene="scene_3", page_number=8,
        reference_id="chunk-1",
    )


def test_empty_narration_is_rejected():
    with pytest.raises(NarrativeValidationError, match="Malformed narrative response"):
        _validate(_payload(narration="   "))


def test_valid_dialogue_and_unknown_speaker_rejection():
    assert _validate(_payload(dialogue=[{"speaker": "macbeth", "text": "I will go."}])).dialogue[0].speaker == "macbeth"
    with pytest.raises(NarrativeValidationError, match="Unknown dialogue speaker"):
        _validate(_payload(dialogue=[{"speaker": "Banquo", "text": "Come here."}]))


@pytest.mark.parametrize("speaker_id", ["duncan", "weird_sisters"])
def test_registered_non_playable_speaker_ids_are_valid(speaker_id):
    response = _validate(_payload(dialogue=[{"speaker": speaker_id, "text": "The hour is strange."}]))
    assert response.dialogue[0].speaker == speaker_id


def test_display_names_and_arbitrary_model_speakers_are_rejected():
    for speaker in ("Duncan", "The Weird Sisters", "ghost"):
        with pytest.raises(NarrativeValidationError, match="Unknown dialogue speaker"):
            _validate(_payload(dialogue=[{"speaker": speaker, "text": "I speak."}]))


def test_unknown_choice_id_is_rejected():
    payload = _payload(choices=[
        {"choice_id": "press_on", "text": "Go."},
        {"choice_id": "invented_choice", "text": "Fly away."},
    ])
    with pytest.raises(NarrativeValidationError, match="Unknown choice ID"):
        _validate(payload)


def test_missing_engine_authorized_choice_is_rejected():
    with pytest.raises(NarrativeValidationError, match="omitted engine-authorized choice"):
        _validate(_payload(choices=[{"choice_id": "press_on", "text": "Go."}]))


def test_duplicate_choice_ids_are_rejected():
    choices = [
        {"choice_id": "press_on", "text": "Go."},
        {"choice_id": "press_on", "text": "Go again."},
    ]
    with pytest.raises(NarrativeValidationError, match="duplicate choice IDs"):
        _validate(_payload(choices=choices))


def test_empty_engine_authorized_choices_accept_empty_narrative_choice_list():
    response = _validate(_payload(choices=[]), choices=[])
    assert response.choices == []


def test_source_reference_must_match_retrieved_passage():
    assert _validate(_payload()).source_references[0].reference_id == "chunk-1"
    invalid = [{"source_document": "other-play.pdf", "reference_id": "unknown-chunk"}]
    assert _validate(_payload(source_references=invalid)).source_references == []


@pytest.mark.parametrize("raw", ["not json", "{\"narration\":"])
def test_malformed_json_is_handled_as_validation_error(raw):
    with pytest.raises(NarrativeValidationError, match="Malformed narrative response"):
        NarrativeValidator().validate(raw, allowed_speakers=set(), engine_choices=[], retrieved_passages=[])


def test_missing_required_fields_and_unexpected_fields_are_rejected():
    incomplete = {"narration": "I wait."}
    with pytest.raises(NarrativeValidationError, match="Malformed narrative response"):
        _validate(incomplete)
    with pytest.raises(ValidationError):
        NarrativeResponse.model_validate({**_payload(), "unexpected": "ignored?"})


def test_supplied_engine_choices_are_not_mutated_and_output_uses_engine_order():
    choices = _choices()
    before = deepcopy([choice.model_dump(mode="json") for choice in choices])
    payload = _payload(choices=[
        {"choice_id": "search_heath", "text": "Look into the lights."},
        {"choice_id": "press_on", "text": "Continue toward Forres."},
    ])
    response = _validate(payload, choices=choices)
    assert [choice.choice_id for choice in response.choices] == ["press_on", "search_heath"]
    assert [choice.model_dump(mode="json") for choice in choices] == before


def test_source_reference_page_and_scene_mismatches_are_rejected():
    bad = [{"source_document": "macbeth.pdf", "scene": "scene_1", "page_number": 99,
            "reference_id": "chunk-1"}]
    assert _validate(_payload(source_references=bad)).source_references == []


def test_terminal_narrative_cannot_return_model_invented_choices():
    response = _validate(_payload(choices=[{"choice_id": "invented_next_step", "text": "Continue."}]),
                         choices=[])
    assert response.choices == []
