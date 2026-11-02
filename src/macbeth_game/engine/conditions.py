"""Small, explicit choice prerequisite evaluator."""

from pydantic import ValidationError

from macbeth_game.domain.models import (
    CharacterState,
    ChoiceConditions,
    ChoiceDefinition,
    GameState,
)


def rejection_reason(conditions: ChoiceConditions, state: GameState, *,
                     acting_character_id: str | None = None) -> str | None:
    attribute_state = state.character_states.get(acting_character_id or state.selected_character_id)
    if attribute_state is None and (conditions.minimum_attributes or conditions.maximum_attributes):
        return "Character attribute conditions require a character state"
    for attribute, minimum in conditions.minimum_attributes.items():
        if getattr(attribute_state, attribute) < minimum:
            return f"Requires {attribute} of at least {minimum}"
    for attribute, maximum in conditions.maximum_attributes.items():
        if getattr(attribute_state, attribute) > maximum:
            return f"Requires {attribute} of at most {maximum}"
    for flag, expected in conditions.required_flags.items():
        if state.flags.get(flag, False) is not expected:
            return f"Requires story flag {flag}={str(expected).lower()}"
    for character_id in conditions.required_alive:
        character = state.character_states.get(character_id)
        if character is None or not character.alive:
            return f"Requires {character_id} to be alive"
    knowledge_character_id = conditions.knowledge_character_id or state.selected_character_id
    knowledge_state = state.character_states.get(knowledge_character_id)
    if conditions.required_known_facts and knowledge_state is None:
        return f"Knowledge owner {knowledge_character_id} has no character state"
    known = knowledge_state.known_facts if knowledge_state else set()
    for fact in conditions.required_known_facts:
        if fact not in known:
            return f"Your character has not learned {fact}"
    target = conditions.relationship_character
    if target:
        source = conditions.relationship_source_character_id or acting_character_id or state.selected_character_id
        if source == target:
            return "A character cannot have a relationship condition with themselves"
        if source not in state.character_states or target not in state.character_states:
            return "Relationship condition references a character without state"
        relationship = next((r for r in state.relationships
                             if r.character_a == source and r.character_b == target), None)
        trust = relationship.trust if relationship else 0
        hostility = relationship.hostility if relationship else 0
        if conditions.min_trust is not None and trust < conditions.min_trust:
            return f"Requires trust of at least {conditions.min_trust} with {target}"
        if conditions.max_trust is not None and trust > conditions.max_trust:
            return f"Requires trust of at most {conditions.max_trust} with {target}"
        if conditions.min_hostility is not None and hostility < conditions.min_hostility:
            return f"Requires hostility of at least {conditions.min_hostility} with {target}"
        if conditions.max_hostility is not None and hostility > conditions.max_hostility:
            return f"Requires hostility of at most {conditions.max_hostility} with {target}"
        if conditions.min_loyalty is not None and (relationship.loyalty if relationship else 0) < conditions.min_loyalty:
            return f"Requires loyalty of at least {conditions.min_loyalty} with {target}"
        if conditions.min_fear is not None and (relationship.fear if relationship else 0) < conditions.min_fear:
            return f"Requires fear of at least {conditions.min_fear} toward {target}"
        if conditions.min_respect is not None and (relationship.respect if relationship else 0) < conditions.min_respect:
            return f"Requires respect of at least {conditions.min_respect} with {target}"
    return None


def choice_rejection_reason(choice: ChoiceDefinition, state: GameState) -> str | None:
    """Validate actor, prerequisites, and consequence targets before offering a choice."""
    actor_id = choice.actor_id or state.selected_character_id
    if actor_id not in state.character_states:
        return f"Choice actor {actor_id} has no character state"
    if choice.actor_id and choice.actor_id != state.selected_character_id:
        return f"This action belongs to {choice.actor_id}"
    condition_error = rejection_reason(choice.conditions, state, acting_character_id=actor_id)
    if condition_error:
        return condition_error

    for character_id, changes in choice.character_changes.items():
        current = state.character_states.get(character_id)
        if current is None:
            return f"Character consequence target {character_id} has no state"
        try:
            CharacterState.model_validate({**current.model_dump(), **changes})
        except ValidationError:
            return f"Character consequence for {character_id} is invalid or exceeds state bounds"

    for change in choice.relationship_changes:
        source = change.source_character_id or actor_id
        target = change.character_id
        if source == target:
            return "A character cannot create a relationship with themselves"
        if source not in state.character_states or target not in state.character_states:
            return "Relationship consequence references a character without state"
        # Authored deltas saturate at the model bounds; they never make a valid choice unavailable.

    for character_id, facts in choice.knowledge_grants.items():
        if character_id not in state.character_states:
            return f"Knowledge recipient {character_id} has no character state"
        if not facts:
            return f"Knowledge grant for {character_id} must contain at least one fact"
    for character_id in choice.psychological_changes:
        if character_id not in state.character_states:
            return f"Psychological consequence target {character_id} has no character state"
    commitment_ids = {item.commitment_id: item for item in state.commitments}
    for directive in choice.commitment_effects:
        commitment = commitment_ids.get(directive.commitment_id)
        if directive.action == "create":
            if commitment is not None:
                return f"Commitment {directive.commitment_id} already exists"
        else:
            if directive.optional and (commitment is None or commitment.status != "active"):
                continue
            if commitment is None or commitment.status != "active":
                return f"Commitment {directive.commitment_id} is not active"
            if commitment.kind != directive.kind:
                return f"Commitment {directive.commitment_id} has a different kind"
            if directive.action in {"fulfill", "breach"} and actor_id != commitment.owner_id:
                return "Only the commitment owner may fulfill or breach it"
            if directive.action == "reveal" and actor_id not in {
                commitment.owner_id, *commitment.participant_ids, *commitment.audience_ids,
            }:
                return "This character is not authorized to reveal the secret"
    return None
