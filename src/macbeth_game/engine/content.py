"""Load and validate story definitions from version-controlled JSON."""

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from macbeth_game.domain.models import CharacterDefinition, SceneDefinition, SpeakerDefinition


class ContentError(ValueError):
    """Story files are malformed or form an invalid graph."""


class CampaignDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    campaign_id: str
    playable_character_id: str
    title: str
    objective: str
    introduction: str
    starting_scene_id: str
    scene_ids: list[str] = Field(min_length=1)
    legacy: bool = False


class StoryContent:
    def __init__(self, characters: list[CharacterDefinition], scenes: list[SceneDefinition],
                 speakers: list[SpeakerDefinition] | None = None,
                 campaigns: list[CampaignDefinition] | None = None,
                 character_effects: dict[str, dict] | None = None):
        self.all_characters = {item.character_id: item for item in characters}
        self.characters = {key: item for key, item in self.all_characters.items() if item.playable}
        self.scenes = {item.scene_id: item for item in scenes}
        self.campaigns = {item.campaign_id: item for item in (campaigns or [])}
        if len(self.all_characters) != len(characters) or len(self.scenes) != len(scenes):
            raise ContentError("Character and scene IDs must be unique")
        if campaigns and len(self.campaigns) != len(campaigns):
            raise ContentError("Campaign IDs must be unique")
        explicit_speakers = speakers or []
        self.speakers = {
            item.character_id: SpeakerDefinition(speaker_id=item.character_id, display_name=item.name)
            for item in characters
        }
        for item in explicit_speakers:
            existing = self.speakers.get(item.speaker_id)
            if existing and existing.display_name != item.display_name:
                raise ContentError(f"Speaker ID {item.speaker_id} has conflicting display metadata")
            self.speakers[item.speaker_id] = item
        choice_ids: set[str] = set()
        effect_map = character_effects or {}
        all_choice_ids = {choice.choice_id for scene in scenes for choice in scene.available_choices}
        if set(effect_map) - all_choice_ids:
            raise ContentError(f"Character effects reference unknown choices: {', '.join(sorted(set(effect_map) - all_choice_ids))}")
        for scene in scenes:
            merged_choices = []
            for choice in scene.available_choices:
                base, extension = choice.model_dump(), effect_map.get(choice.choice_id, {})
                merged = {**base, **extension}
                for list_key in ("relationship_changes", "knowledge_observations", "commitment_effects"):
                    if list_key in extension:
                        merged[list_key] = [*base.get(list_key, []), *extension[list_key]]
                if "psychological_changes" in extension:
                    psychology = {key: dict(value) for key, value in base.get("psychological_changes", {}).items()}
                    for key, value in extension["psychological_changes"].items():
                        psychology.setdefault(key, {}).update(value)
                    merged["psychological_changes"] = psychology
                if "conditions" in extension:
                    merged["conditions"] = {**base.get("conditions", {}), **extension["conditions"]}
                if "knowledge_grants" in extension:
                    grants = {key: list(value) for key, value in base.get("knowledge_grants", {}).items()}
                    for recipient, facts in extension["knowledge_grants"].items():
                        grants.setdefault(recipient, []).extend(facts)
                    merged["knowledge_grants"] = grants
                merged_choices.append(type(choice).model_validate(merged))
            scene.available_choices = merged_choices
            unknown_participants = set(scene.participants) - self.speakers.keys()
            if unknown_participants:
                raise ContentError(
                    f"Scene {scene.scene_id} references speaker IDs without metadata: "
                    f"{', '.join(sorted(unknown_participants))}"
                )
            for choice in scene.available_choices:
                if choice.choice_id in choice_ids:
                    raise ContentError(f"Choice ID {choice.choice_id} is not unique")
                choice_ids.add(choice.choice_id)
                if choice.next_scene_id not in self.scenes:
                    raise ContentError(f"Scene {scene.scene_id} references missing destination {choice.next_scene_id}")
                if choice.actor_id and choice.actor_id not in self.characters:
                    raise ContentError(f"Choice {choice.choice_id} references an unknown actor {choice.actor_id}")
                if choice.actor_id and choice.actor_id not in scene.participants:
                    raise ContentError(f"Choice {choice.choice_id} actor must participate in scene {scene.scene_id}")
                if any(c not in self.all_characters for c in choice.character_changes):
                    raise ContentError(f"Choice {choice.choice_id} changes an unknown character")
                if any(c not in self.all_characters for c in choice.knowledge_grants):
                    raise ContentError(f"Choice {choice.choice_id} grants knowledge to an unknown character")
                visibility_recipients = (set(choice.witness_character_ids)
                                         | set(choice.informed_character_ids)
                                         | set(choice.rumoured_character_ids))
                if not visibility_recipients <= self.all_characters.keys():
                    raise ContentError(f"Choice {choice.choice_id} visibility contract references an unknown character")
                if any(c not in self.all_characters for c in choice.psychological_changes):
                    raise ContentError(f"Choice {choice.choice_id} changes an unknown character's psychology")
                for observation in choice.knowledge_observations:
                    if observation.character_id not in self.all_characters or not set(observation.related_characters) <= self.all_characters.keys():
                        raise ContentError(f"Choice {choice.choice_id} observation references an unknown character")
                for directive in choice.commitment_effects:
                    references = set(directive.participant_ids) | set(directive.audience_ids)
                    if directive.owner_id:
                        references.add(directive.owner_id)
                    if not references <= self.all_characters.keys():
                        raise ContentError(f"Choice {choice.choice_id} commitment references an unknown character")
                for change in choice.relationship_changes:
                    if change.character_id not in self.all_characters:
                        raise ContentError(f"Choice {choice.choice_id} relates an unknown character")
                    if change.source_character_id and change.source_character_id not in self.all_characters:
                        raise ContentError(f"Choice {choice.choice_id} relates an unknown source character")
                    if change.source_character_id == change.character_id:
                        raise ContentError(f"Choice {choice.choice_id} creates a self-relationship")
                condition = choice.conditions
                references = set(condition.required_alive)
                if condition.relationship_character:
                    references.add(condition.relationship_character)
                if not references <= self.all_characters.keys():
                    raise ContentError(f"Choice {choice.choice_id} references an unknown character condition")
                for reference in (condition.knowledge_character_id,
                                  condition.relationship_source_character_id):
                    if reference and reference not in self.all_characters:
                        raise ContentError(f"Choice {choice.choice_id} condition references unknown character {reference}")
                if (condition.relationship_source_character_id
                        and condition.relationship_source_character_id == condition.relationship_character):
                    raise ContentError(f"Choice {choice.choice_id} condition uses a self-relationship")
                if any(set(changes) - {"ambition", "morality", "suspicion", "alive", "guilt",
                                       "emotional_stability", "influence", "isolation", "resolve",
                                       "fear", "stress", "hope", "confidence"}
                       for changes in choice.character_changes.values()):
                    raise ContentError(f"Choice {choice.choice_id} changes a protected character field")
        for campaign in self.campaigns.values():
            if campaign.playable_character_id not in self.characters:
                raise ContentError(f"Campaign {campaign.campaign_id} has no playable protagonist")
            if campaign.starting_scene_id not in campaign.scene_ids or not set(campaign.scene_ids) <= self.scenes.keys():
                raise ContentError(f"Campaign {campaign.campaign_id} has an invalid scene inventory")
            for scene_id in campaign.scene_ids:
                scene = self.scenes[scene_id]
                if campaign.playable_character_id not in scene.participants:
                    raise ContentError(
                        f"Campaign {campaign.campaign_id} protagonist is absent from scene {scene_id}"
                    )
                for choice in scene.available_choices:
                    if choice.actor_id and choice.actor_id != campaign.playable_character_id:
                        raise ContentError(
                            f"Campaign {campaign.campaign_id} choice {choice.choice_id} has another actor"
                        )
                    if choice.next_scene_id not in campaign.scene_ids:
                        raise ContentError(f"Campaign {campaign.campaign_id} choice {choice.choice_id} leaves its route")


def load_story_content(directory: Path) -> StoryContent:
    try:
        raw_characters = json.loads((directory / "characters.json").read_text(encoding="utf-8"))
        raw_scenes = json.loads((directory / "scenes.json").read_text(encoding="utf-8"))
        campaign_scenes_path = directory / "campaign_scenes.json"
        if campaign_scenes_path.exists():
            raw_scenes.extend(json.loads(campaign_scenes_path.read_text(encoding="utf-8")))
        speakers_path = directory / "speakers.json"
        raw_speakers = json.loads(speakers_path.read_text(encoding="utf-8")) if speakers_path.exists() else []
        campaigns_path = directory / "campaigns.json"
        raw_campaigns = json.loads(campaigns_path.read_text(encoding="utf-8")) if campaigns_path.exists() else []
        effects_path = directory / "character_effects.json"
        effects = json.loads(effects_path.read_text(encoding="utf-8")) if effects_path.exists() else {}
        return StoryContent(
            [CharacterDefinition.model_validate(item) for item in raw_characters],
            [SceneDefinition.model_validate(item) for item in raw_scenes],
            [SpeakerDefinition.model_validate(item) for item in raw_speakers],
            [CampaignDefinition.model_validate(item) for item in raw_campaigns], effects,
        )
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        raise ContentError(f"Unable to load story content from {directory}: {exc}") from exc
