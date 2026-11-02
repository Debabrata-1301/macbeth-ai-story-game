import type {
  CharacterDefinition,
  ChoiceAvailability,
  ChoiceDefinition,
  GameState,
  GameSummary,
  GameView,
  GameplayTurnResponse,
  NarrativeResponse,
  SceneDefinition,
} from '../src/api/types';

export const gameId = 'browser-game-42';

export const characters: CharacterDefinition[] = [
  { character_id: 'macbeth', name: 'Macbeth', role: 'Thane of Glamis', personality: ['brave', 'ambitious'], motivations: ['honor', 'power'], background: 'A celebrated Scottish thane.' },
  { character_id: 'lady_macbeth', name: 'Lady Macbeth', role: 'Noblewoman of Inverness', personality: ['resolute', 'perceptive'], motivations: ['influence', 'security'], background: 'Macbeth’s wife.' },
  { character_id: 'banquo', name: 'Banquo', role: 'Scottish general', personality: ['cautious', 'loyal'], motivations: ['honor', 'truth'], background: 'A fellow general.' },
  { character_id: 'macduff', name: 'Macduff', role: 'Thane of Fife', personality: ['dutiful', 'watchful'], motivations: ['justice', 'Scotland’s safety'], background: 'A Scottish nobleman.' },
];

const conditions = {
  required_flags: {}, required_alive: [], required_known_facts: [],
  relationship_character: null, min_trust: null, max_trust: null,
  min_hostility: null, max_hostility: null, minimum_attributes: {}, maximum_attributes: {},
};

export const firstChoice: ChoiceDefinition = {
  choice_id: 'press_to_forres', action_id: 'ride_on',
  description: 'Ride on toward Forres with Banquo.', prerequisites: [], state_flags: {},
  next_scene_id: 'weird_sisters', conditions, character_changes: {},
  relationship_changes: [], grants_knowledge: [],
};

export const secondChoice: ChoiceDefinition = {
  ...firstChoice,
  choice_id: 'search_the_heath', action_id: 'search_heath',
  description: 'Pause and study the strange lights on the heath.',
};

export const nextChoice: ChoiceDefinition = {
  ...firstChoice,
  choice_id: 'tell_banquo', action_id: 'share_prophecy',
  description: 'Tell Banquo you will take the prophecy seriously.',
  next_scene_id: 'forres_hopeful',
};

export const initialScene: SceneDefinition = {
  scene_id: 'heath_before_battle', title: 'The Heath Before Battle',
  location: 'A storm-swept heath near Forres',
  canonical_reference: 'Inspired by Act 1, Scene 1; original game text.',
  source_classification: 'alternate_history', source_act_id: null, source_scene_id: null,
  participants: ['macbeth', 'banquo'], summary: 'A storm gathers over Scotland.',
  opening_narration: 'The wind scours the heath as I ride beneath a bruised sky.',
  available_choices: [firstChoice, secondChoice], is_ending: false, ending_id: null,
};

export const nextScene: SceneDefinition = {
  ...initialScene,
  scene_id: 'weird_sisters', title: 'Fair Is Foul', location: 'A desolate heath',
  canonical_reference: 'Macbeth, Act 1, Scene 3',
  opening_narration: 'I hear the sisters name me Thane of Cawdor.',
  available_choices: [nextChoice],
};

const campaignOpenings: Record<string, { id: string; title: string; location: string; opening: string }> = {
  lady_macbeth: { id: 'lady_letter', title: 'The Letter at Inverness', location: 'Inverness Castle', opening: 'I read my husband’s letter twice.' },
  banquo: { id: 'banquo_heath', title: 'The Prophecy Shared', location: 'The heath near Forres', opening: 'The sisters promise Macbeth a crown.' },
  macduff: { id: 'macduff_fife', title: 'A Thane at Home', location: 'Fife', opening: 'The old king is dead and rumors travel fast.' },
};

export function campaignOpening(characterId: string): SceneDefinition {
  const opening = campaignOpenings[characterId];
  if (!opening) return initialScene;
  return { ...initialScene, scene_id: opening.id, title: opening.title, location: opening.location,
    participants: [characterId], summary: opening.opening, opening_narration: opening.opening,
    canonical_reference: null, source_classification: 'alternate_history', source_act_id: null,
    source_scene_id: null, available_choices: [firstChoice, secondChoice] };
}

export function makeGame(
  selectedCharacterId = 'macbeth', sceneId: string | undefined = undefined, revision = 0,
): GameState {
  const timestamp = '2026-10-30T00:00:00Z';
  return {
    game_id: gameId, selected_character_id: selectedCharacterId,
    campaign_id: selectedCharacterId,
    story_mode: 'hybrid', perspective: 'first_person', current_scene_id: sceneId ?? campaignOpening(selectedCharacterId).scene_id,
    character_states: Object.fromEntries(characters.map((character) => [character.character_id, {
      character_id: character.character_id, ambition: 0, morality: 0, suspicion: 0,
      guilt: 0, emotional_stability: 100, influence: 50, isolation: 25, resolve: 50,
      alive: true, known_facts: [],
    }])),
    relationships: [], flags: {}, turn_number: revision, status: 'active', ending_id: null,
    revision, created_at: timestamp, updated_at: timestamp,
    event_history: revision ? [{
      event_id: 'browser-event-1', event_type: 'choice_made', actor_id: selectedCharacterId,
      scene_id: initialScene.scene_id, metadata: { choice_id: firstChoice.choice_id },
      timestamp: '2026-10-30T00:00:01Z',
    }] : [],
  };
}

export const narrative: NarrativeResponse = {
  narration: 'I ride beneath a sky bruised by storm, and the sisters’ words follow me.',
  dialogue: [{ speaker: 'Banquo', text: 'The day is foul and fair.' }],
  atmosphere: 'Thunder mutters across the open moor.',
  choices: [{ choice_id: nextChoice.choice_id, text: nextChoice.description }],
  source_references: [],
};

export function makeView(updated = false, characterId = 'macbeth'): GameView {
  return {
    game: updated ? makeGame(characterId, nextScene.scene_id, 1) : makeGame(characterId),
    scene: updated ? nextScene : campaignOpening(characterId),
  };
}

export function makeSummary(updated = false, characterId = 'macbeth'): GameSummary {
  return {
    game_id: gameId,
    selected_character_id: characterId,
    campaign_id: characterId,
    current_scene_id: updated ? nextScene.scene_id : initialScene.scene_id,
    current_scene_title: updated ? nextScene.title : initialScene.title,
    status: 'active',
    revision: updated ? 1 : 0,
    turn_number: updated ? 1 : 0,
    created_at: '2026-10-30T00:00:00Z',
    updated_at: updated ? '2026-10-30T00:05:00Z' : '2026-10-30T00:00:00Z',
  };
}

export const initialChoices: ChoiceAvailability[] = [firstChoice, secondChoice]
  .map((choice) => ({ choice, available: true, reason: null }));
export const nextChoices: ChoiceAvailability[] = [{ choice: nextChoice, available: true, reason: null }];

export function makeTurnResponse(generationFailed = false): GameplayTurnResponse {
  return {
    game: makeGame('macbeth', nextScene.scene_id, 1),
    narrative: generationFailed ? null : narrative,
    available_choices: nextChoices,
    request_id: 'browser-request-1',
    transition_applied: true,
    replayed: false,
    generation_error_code: generationFailed ? 'ollama_unavailable' : null,
    generation_error: generationFailed ? 'Local Ollama service unavailable.' : null,
  };
}
