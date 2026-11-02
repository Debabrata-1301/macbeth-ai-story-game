"""Deterministic psychology, directional relationship, memory and commitment effects."""

from uuid import uuid4

from macbeth_game.domain.models import (
    CharacterMemory,
    ChoiceDefinition,
    GameState,
    KnowledgeObservation,
    NarrativeCommitment,
    RelationshipState,
)

PSYCHOLOGICAL_ATTRIBUTES = {
    "ambition", "morality", "suspicion", "guilt", "emotional_stability", "influence",
    "isolation", "resolve", "fear", "stress", "hope", "confidence",
}
MEMORY_LIMIT_PER_CHARACTER = 100


def _relationship(state: GameState, source_id: str, target_id: str) -> RelationshipState:
    if source_id == target_id:
        raise ValueError("a character cannot have a relationship with themselves")
    existing = next((item for item in state.relationships
                     if item.character_a == source_id and item.character_b == target_id), None)
    if existing is None:
        existing = RelationshipState(character_a=source_id, character_b=target_id)
        state.relationships.append(existing)
    return existing


def _memory(state: GameState, *, event_id: str, character_id: str, category: str,
            summary: str, source: str, importance: int, turn: int,
            related: list[str], visibility: str = "private", certainty: str = "confirmed",
            emotional_significance: int = 0) -> str:
    # A character gets at most one copy of each event-memory, even if a caller retries a commit.
    existing = next((item for item in state.memories
                     if item.event_id == event_id and item.character_id == character_id
                     and item.category == category and item.summary == summary), None)
    if existing:
        return existing.memory_id
    memory_id = str(uuid4())
    state.memories.append(CharacterMemory(
        memory_id=memory_id, character_id=character_id, campaign_id=state.campaign_id,
        event_id=event_id, category=category, summary=summary[:600], source=source,
        certainty=certainty, importance=importance, created_turn=turn, visibility=visibility,
        related_characters=[item for item in dict.fromkeys(related) if item != character_id],
        emotional_significance=max(-100, min(100, emotional_significance)),
    ))
    owned = [item for item in state.memories if item.character_id == character_id]
    if len(owned) > MEMORY_LIMIT_PER_CHARACTER:
        remove_count = len(owned) - MEMORY_LIMIT_PER_CHARACTER
        to_remove = sorted(owned, key=lambda item: (item.importance, item.created_turn))[:remove_count]
        remove_ids = {item.memory_id for item in to_remove}
        state.memories = [item for item in state.memories if item.memory_id not in remove_ids]
    return memory_id


def _commitment_effects(state: GameState, choice: ChoiceDefinition, *, actor_id: str,
                        event_id: str, turn: int) -> list[dict[str, str]]:
    changed: list[dict[str, str]] = []
    for directive in choice.commitment_effects:
        existing = next((item for item in state.commitments
                         if item.commitment_id == directive.commitment_id), None)
        if directive.optional and directive.action != "create" and (existing is None or existing.status != "active"):
            continue
        if directive.action == "create":
            owner_id = directive.owner_id or actor_id
            state.commitments.append(NarrativeCommitment(
                commitment_id=directive.commitment_id, kind=directive.kind, owner_id=owner_id,
                participant_ids=list(dict.fromkeys(directive.participant_ids)), summary=directive.summary,
                visibility=directive.visibility, audience_ids=list(dict.fromkeys(directive.audience_ids)),
                created_event_id=event_id, created_turn=turn,
            ))
            changed.append({"commitment_id": directive.commitment_id, "status": "active"})
        elif existing is not None:
            status = {"fulfill": "fulfilled", "breach": "broken", "reveal": "revealed"}[directive.action]
            existing.status = status
            existing.resolved_event_id = event_id
            changed.append({"commitment_id": directive.commitment_id, "status": status})
            if directive.action == "breach" and existing.kind == "promise":
                for participant_id in existing.participant_ids:
                    if participant_id == existing.owner_id:
                        continue
                    relationship = _relationship(state, participant_id, existing.owner_id)
                    relationship.trust = max(-100, relationship.trust - 20)
                    relationship.hostility = min(100, relationship.hostility + 20)
                    relationship.respect = max(0, relationship.respect - 10)
                owner_state = state.character_states[existing.owner_id]
                owner_state.guilt = min(100, owner_state.guilt + 5)
                owner_state.stress = min(100, owner_state.stress + 10)
            if directive.action == "reveal" and existing.kind == "secret":
                recipients = existing.audience_ids or existing.participant_ids
                if existing.visibility == "public":
                    recipients = list(state.character_states)
                for recipient in recipients:
                    state.character_states[recipient].known_facts.add(existing.summary)
        for participant_id in (([directive.owner_id or actor_id, *directive.participant_ids,
                                 *directive.audience_ids]) if directive.action == "create"
                               else ([existing.owner_id, *existing.participant_ids,
                                      *existing.audience_ids] if existing else [actor_id])):
            if participant_id in state.character_states:
                _memory(state, event_id=event_id, character_id=participant_id,
                        category="promise" if directive.kind == "promise" else "secret",
                        summary=directive.summary, source=choice.choice_id, importance=85,
                        turn=turn, related=[actor_id, *directive.participant_ids],
                        visibility=directive.visibility,
                        emotional_significance=12 if directive.action == "create" else -20)
    return changed


def apply_accepted_choice(state: GameState, choice: ChoiceDefinition, *, scene_id: str,
                          scene_participants: list[str], event_id: str) -> dict:
    """Mutate a transition candidate only after choice authorization succeeds."""
    actor_id = choice.actor_id or state.selected_character_id
    turn = state.turn_number + 1
    psychology_applied: dict[str, dict[str, int]] = {}
    for character_id, deltas in choice.psychological_changes.items():
        character = state.character_states[character_id]
        applied: dict[str, int] = {}
        for attribute, delta in deltas.items():
            before = getattr(character, attribute)
            after = max(0, min(100, before + delta))
            setattr(character, attribute, after)
            applied[attribute] = after - before
        psychology_applied[character_id] = applied

    relationship_applied: list[dict[str, str | int]] = []
    for change in choice.relationship_changes:
        source_id = change.source_character_id or actor_id
        relation = _relationship(state, source_id, change.character_id)
        for attribute in ("trust", "hostility", "loyalty", "fear", "affection", "respect"):
            delta = getattr(change, attribute)
            before = getattr(relation, attribute)
            after = before + delta
            minimum = -100 if attribute == "trust" else 0
            after = max(minimum, min(100, after))
            setattr(relation, attribute, after)
        relationship_applied.append({"source_id": source_id, "target_id": change.character_id,
                                     "trust": change.trust, "hostility": change.hostility,
                                     "loyalty": change.loyalty, "fear": change.fear,
                                     "affection": change.affection, "respect": change.respect})

    knowledge_grants = {recipient: list(facts) for recipient, facts in choice.knowledge_grants.items()}
    if choice.grants_knowledge:
        knowledge_grants.setdefault(actor_id, []).extend(choice.grants_knowledge)
    observations_confirmed: list[dict[str, str]] = []
    for recipient, facts in knowledge_grants.items():
        state.character_states[recipient].known_facts.update(facts)
        for observation in state.character_states[recipient].uncertain_knowledge:
            if observation.resolved_by_fact in facts and observation.confirmed_event_id is None:
                observation.confirmed_event_id = event_id
                observations_confirmed.append({
                    "character_id": recipient, "content": observation.content,
                    "fact": observation.resolved_by_fact or "", "event_id": event_id,
                })
                for memory in state.memories:
                    if memory.character_id == recipient and memory.event_id == observation.source_event_id:
                        memory.certainty = "confirmed"
                        memory.summary = f"{memory.summary} (later confirmed by evidence)"[:600]

    observations_added: list[dict[str, str]] = []
    for directive in choice.knowledge_observations:
        observation = KnowledgeObservation(
            character_id=directive.character_id, content=directive.content,
            category=directive.category, confidence=directive.confidence, source=directive.source,
            source_event_id=event_id, created_turn=turn,
            related_characters=directive.related_characters,
            resolved_by_fact=directive.resolved_by_fact,
        )
        owner = state.character_states[directive.character_id]
        if not any(item.source_event_id == event_id and item.content == directive.content
                   for item in owner.uncertain_knowledge):
            owner.uncertain_knowledge.append(observation)
        _memory(state, event_id=event_id, character_id=directive.character_id,
                category="personal_experience", summary=directive.content, source=directive.source,
                importance=55, turn=turn, related=directive.related_characters,
                certainty=directive.category, emotional_significance=8)
        observations_added.append({"character_id": directive.character_id,
                                   "category": directive.category, "content": directive.content})

    commitments_changed = _commitment_effects(state, choice, actor_id=actor_id,
                                               event_id=event_id, turn=turn)
    actor_name = actor_id.replace("_", " ").title()
    related = [item for item in scene_participants if item != actor_id]
    memory_id = _memory(
        state, event_id=event_id, character_id=actor_id, category=choice.memory_category,
        summary=f"I chose to {choice.description[0].lower() + choice.description[1:]}",
        source=f"{scene_id}:{choice.choice_id}", importance=choice.memory_importance,
        turn=turn, related=related, visibility="private",
        emotional_significance=sum(psychology_applied.get(actor_id, {}).values()),
    )
    transferred_memory_ids: dict[str, list[str]] = {}
    for recipient, facts in knowledge_grants.items():
        if recipient == actor_id:
            continue
        transferred_memory_ids[recipient] = [
            _memory(state, event_id=event_id, character_id=recipient, category="conversation",
                    summary=f"{actor_name} told me: {fact.replace('_', ' ')}",
                    source=f"{scene_id}:{choice.choice_id}", importance=65, turn=turn,
                    related=[actor_id], visibility="private") for fact in facts
        ]

    return {
        "knowledge_grants": knowledge_grants,
        "psychological_changes_applied": psychology_applied,
        "relationship_changes_applied": relationship_applied,
        "knowledge_observations_added": observations_added,
        "knowledge_observations_confirmed": observations_confirmed,
        "commitments_changed": commitments_changed,
        "memory_ids": {actor_id: [memory_id], **transferred_memory_ids},
    }
