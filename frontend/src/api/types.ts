export type StoryMode = 'canonical' | 'alternate' | 'hybrid';
export type NarrativePerspective = 'first_person';
export type GameStatus = 'active' | 'completed' | 'abandoned';
export type EventType =
  | 'game_started'
  | 'choice_made'
  | 'scene_entered'
  | 'character_state_changed'
  | 'relationship_changed'
  | 'game_ended';

export interface CharacterState {
  character_id: string;
  ambition: number;
  morality: number;
  suspicion: number;
  guilt: number;
  emotional_stability: number;
  influence: number;
  isolation: number;
  resolve: number;
  fear?: number;
  stress?: number;
  hope?: number;
  confidence?: number;
  alive: boolean;
  known_facts: string[];
  uncertain_knowledge?: KnowledgeObservation[];
}

export interface KnowledgeObservation { character_id: string; content: string; category: 'rumour' | 'suspicion' | 'belief'; confidence: number; source: string; source_event_id: string; created_turn: number; related_characters: string[]; resolved_by_fact?: string | null; confirmed_event_id?: string | null; }
export interface CharacterMemory { memory_id: string; character_id: string; campaign_id: string; event_id: string; category: string; summary: string; source: string; certainty: string; importance: number; created_turn: number; visibility: string; related_characters: string[]; emotional_significance: number; }
export interface NarrativeCommitment { commitment_id: string; kind: 'promise' | 'secret'; owner_id: string; participant_ids: string[]; summary: string; visibility: 'private' | 'participants' | 'public'; audience_ids: string[]; created_event_id: string; created_turn: number; status: 'active' | 'fulfilled' | 'broken' | 'revealed'; resolved_event_id: string | null; }

export interface RelationshipState {
  character_a: string;
  character_b: string;
  trust: number;
  hostility: number;
  loyalty?: number;
  fear?: number;
  affection?: number;
  respect?: number;
}

export interface GameEvent {
  event_id: string;
  event_type: EventType;
  actor_id: string;
  scene_id: string;
  metadata: Record<string, unknown>;
  timestamp: string;
}

export interface GameState {
  game_id: string;
  selected_character_id: string;
  campaign_id: string;
  story_mode: StoryMode;
  perspective: NarrativePerspective;
  current_scene_id: string;
  character_states: Record<string, CharacterState>;
  relationships: RelationshipState[];
  memories?: CharacterMemory[];
  commitments?: NarrativeCommitment[];
  flags: Record<string, boolean>;
  turn_number: number;
  status: GameStatus;
  ending_id: string | null;
  revision: number;
  created_at: string;
  updated_at: string;
  event_history: GameEvent[];
}

export interface ChoiceConditions {
  required_flags: Record<string, boolean>;
  required_alive: string[];
  required_known_facts: string[];
  knowledge_character_id?: string | null;
  relationship_character: string | null;
  relationship_source_character_id?: string | null;
  min_trust: number | null;
  max_trust: number | null;
  min_hostility: number | null;
  max_hostility: number | null;
  minimum_attributes: Record<string, number>;
  maximum_attributes: Record<string, number>;
}

export interface RelationshipChange {
  character_id: string;
  source_character_id?: string | null;
  trust: number;
  hostility: number;
}

export interface ChoiceDefinition {
  choice_id: string;
  action_id: string;
  description: string;
  actor_id?: string | null;
  prerequisites: string[];
  state_flags: Record<string, boolean>;
  next_scene_id: string | null;
  conditions: ChoiceConditions;
  character_changes: Record<string, Record<string, number | boolean>>;
  relationship_changes: RelationshipChange[];
  grants_knowledge: string[];
  knowledge_grants?: Record<string, string[]>;
}

export interface SceneDefinition {
  scene_id: string;
  title: string;
  location: string;
  canonical_reference: string | null;
  source_classification: 'canonical_adaptation' | 'alternate_history';
  source_act_id: string | null;
  source_scene_id: string | null;
  participants: string[];
  summary: string;
  opening_narration: string;
  available_choices: ChoiceDefinition[];
  is_ending: boolean;
  ending_id: string | null;
}

export interface GameView {
  game: GameState;
  scene: SceneDefinition;
}

export interface GameSummary {
  game_id: string;
  selected_character_id: string;
  campaign_id: string;
  current_scene_id: string;
  current_scene_title: string;
  status: GameStatus;
  revision: number;
  turn_number: number;
  created_at: string;
  updated_at: string;
}

export interface StartGameRequest {
  character_id: string;
  story_mode?: StoryMode;
}

export interface HealthResponse {
  service: string;
  status: string;
}

export interface CharacterDefinition {
  character_id: string;
  name: string;
  role: string;
  personality: string[];
  motivations: string[];
  background: string;
}

export interface NarrativeDialogueEntry {
  speaker: string;
  text: string;
}

export interface NarrativeChoice {
  choice_id: string;
  text: string;
}

export interface NarrativeSourceReference {
  source_document: string;
  act: string | null;
  scene: string | null;
  page_number: number | null;
  reference_id: string | null;
}

export interface NarrativeResponse {
  narration: string;
  dialogue: NarrativeDialogueEntry[];
  atmosphere: string;
  choices: NarrativeChoice[];
  source_references: NarrativeSourceReference[];
}

export interface ChoiceAvailability {
  choice: ChoiceDefinition;
  available: boolean;
  reason: string | null;
}

export interface GameplayTurnRequest {
  choice_id: string;
  request_id: string;
}

export interface GameplayTurnResponse {
  game: GameState;
  narrative: NarrativeResponse | null;
  available_choices: ChoiceAvailability[];
  request_id: string | null;
  transition_applied: boolean;
  replayed: boolean;
  generation_error_code: string | null;
  generation_error: string | null;
}
