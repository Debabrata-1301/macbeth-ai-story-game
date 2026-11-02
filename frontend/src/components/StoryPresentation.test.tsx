import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { ChoiceDefinition, GameState, SceneDefinition } from '../api/types';
import { BranchChoice } from './BranchChoice';
import { CharacterStatusPanel } from './CharacterStatusPanel';
import { StoryTimeline } from './StoryTimeline';

const characters = [
  { character_id: 'macbeth', name: 'Macbeth', role: 'Thane', personality: ['ambitious'], motivations: ['power'], background: 'A thane.' },
  { character_id: 'banquo', name: 'Banquo', role: 'General', personality: ['loyal'], motivations: ['honor'], background: 'A general.' },
];

const baseChoice: ChoiceDefinition = {
  choice_id: 'search_the_heath',
  action_id: 'search_heath',
  description: 'Pause and study the strange lights on the heath.',
  prerequisites: [],
  state_flags: { watched_heath: true },
  next_scene_id: 'secret_future_scene',
  conditions: { required_flags: {}, required_alive: [], required_known_facts: [], relationship_character: null, min_trust: null, max_trust: null, min_hostility: null, max_hostility: null, minimum_attributes: {}, maximum_attributes: {} },
  character_changes: { macbeth: { suspicion: 5 } },
  relationship_changes: [],
  grants_knowledge: ['future_secret'],
};

function makeGame(overrides: Partial<GameState> = {}): GameState {
  return {
    game_id: 'game-1', selected_character_id: 'macbeth', campaign_id: 'macbeth', story_mode: 'hybrid', perspective: 'first_person',
    current_scene_id: 'weird_sisters',
    character_states: { macbeth: { character_id: 'macbeth', ambition: 60, morality: 48, suspicion: 5, guilt: 0, emotional_stability: 100, influence: 50, isolation: 25, resolve: 50, alive: true, known_facts: ['witches_prophesied_kingship'] } },
    relationships: [], flags: {}, turn_number: 1, status: 'active', ending_id: null, revision: 1,
    created_at: '2026-10-30T00:00:00Z', updated_at: '2026-10-30T00:00:01Z', event_history: [],
    ...overrides,
  };
}

function makeScene(overrides: Partial<SceneDefinition> = {}): SceneDefinition {
  return {
    scene_id: 'weird_sisters', title: 'Fair Is Foul', location: 'A desolate heath',
    canonical_reference: 'Macbeth, Act 1, Scene 3 (adapted situation; original game narration).',
    source_classification: 'canonical_adaptation', source_act_id: 'act_1', source_scene_id: 'scene_3',
    participants: ['macbeth', 'banquo'], summary: 'The sisters speak.', opening_narration: 'I hear the sisters.',
    available_choices: [], is_ending: false, ending_id: null, ...overrides,
  };
}

afterEach(cleanup);

describe('branch and story presentation', () => {
  it('submits the unchanged engine choice ID and shows only backend-provided immediate effects', () => {
    const onChoose = vi.fn();
    render(<BranchChoice choice={baseChoice} index={0} characters={characters} disabled={false} onChoose={onChoose} />);
    fireEvent.click(screen.getByRole('button', { name: /Pause and study/ }));

    expect(onChoose).toHaveBeenCalledWith('search_the_heath');
    expect(screen.getByText('Macbeth · suspicion → 5')).toBeTruthy();
    expect(screen.queryByText('secret_future_scene')).toBeNull();
    expect(screen.queryByText('future secret')).toBeNull();
    expect(screen.queryByText('watched heath')).toBeNull();
  });

  it('shows recorded relationship deltas when present', () => {
    const choice = { ...baseChoice, character_changes: {}, relationship_changes: [{ character_id: 'banquo', trust: 10, hostility: 0 }] };
    render(<BranchChoice choice={choice} index={1} characters={characters} disabled={false} onChoose={vi.fn()} />);
    expect(screen.getByText('Trust with Banquo +10')).toBeTruthy();
  });

  it('renders only state attributes and values supplied for the selected character', () => {
    render(<CharacterStatusPanel game={makeGame()} characters={characters} />);
    expect(screen.getByText('Ambition')).toBeTruthy();
    expect(screen.getByRole('meter', { name: 'Ambition' }).getAttribute('value')).toBe('60');
    expect(screen.getByText('Morality')).toBeTruthy();
    expect(screen.getByRole('meter', { name: 'Morality' }).getAttribute('value')).toBe('48');
    expect(screen.getByText('Suspicion')).toBeTruthy();
    expect(screen.getByText('Living')).toBeTruthy();
    expect(screen.queryByText(/Fear|Reputation|Political influence|Loyalty/)).toBeNull();
    expect(screen.getByText('witches prophesied kingship')).toBeTruthy();
  });

  it('does not invent values when optional character state is absent', () => {
    render(<CharacterStatusPanel game={makeGame({ character_states: {} })} characters={characters} />);
    expect(screen.getByText('No character state is recorded for this save.')).toBeTruthy();
    expect(screen.queryByRole('meter')).toBeNull();
    expect(screen.queryByText('Ambition')).toBeNull();
  });

  it('shows recorded trust and hostility for relationships involving the selected character', () => {
    const game = makeGame({ relationships: [{ character_a: 'macbeth', character_b: 'banquo', trust: 10, hostility: 0 }] });
    render(<CharacterStatusPanel game={game} characters={characters} />);
    expect(screen.getByText('Recorded ties')).toBeTruthy();
    expect(screen.getByText('Banquo')).toBeTruthy();
    expect(screen.getByText('Trust +10')).toBeTruthy();
    expect(screen.getByText('Hostility 0')).toBeTruthy();
  });

  it('keeps the open character journal scoped to the selected character and campaign', () => {
    const game = makeGame({
      memories: [
        { memory_id: 'own-memory', character_id: 'macbeth', campaign_id: 'macbeth', event_id: 'e1', category: 'decision', summary: 'I trusted Banquo.', source: 'choice', certainty: 'confirmed', importance: 70, created_turn: 1, visibility: 'private', related_characters: ['banquo'], emotional_significance: 10 },
        { memory_id: 'other-save', character_id: 'macbeth', campaign_id: 'banquo', event_id: 'e2', category: 'secret', summary: 'Campaign from another save.', source: 'choice', certainty: 'confirmed', importance: 90, created_turn: 2, visibility: 'private', related_characters: [], emotional_significance: 0 },
      ],
      commitments: [
        { commitment_id: 'hidden-promise', kind: 'secret', owner_id: 'banquo', participant_ids: ['fleance'], summary: 'Banquo’s private plan.', visibility: 'private', audience_ids: [], created_event_id: 'e3', created_turn: 2, status: 'active', resolved_event_id: null },
      ],
    });
    render(<CharacterStatusPanel game={game} characters={characters} />);
    fireEvent.click(screen.getByText('Character journal'));
    expect(screen.getByText(/I trusted Banquo\./)).toBeTruthy();
    expect(screen.queryByText('Campaign from another save.')).toBeNull();
    expect(screen.queryByText('Banquo’s private plan.')).toBeNull();
  });

  it('shows only persisted decision events, transitions, and the marked current alternate scene', () => {
    const game = makeGame({ event_history: [
      { event_id: 'start', event_type: 'game_started', actor_id: 'macbeth', scene_id: 'heath_before_battle', metadata: {}, timestamp: '2026-10-30T00:00:00Z' },
      { event_id: 'decision', event_type: 'choice_made', actor_id: 'macbeth', scene_id: 'heath_before_battle', metadata: { choice_id: 'search_the_heath', destination_scene_id: 'weird_sisters' }, timestamp: '2026-10-30T00:00:01Z' },
    ] });
    const scene = makeScene({ canonical_reference: 'Alternate-history scene created for this game; it is not Shakespeare’s canonical text.' });
    render(<StoryTimeline game={game} scene={scene} />);

    expect(screen.getByText('Chronicle begun')).toBeTruthy();
    expect(screen.getByText('Decision taken')).toBeTruthy();
    expect(document.querySelector('.timeline-event__transition')?.textContent).toContain('heath_before_battle');
    expect(document.querySelector('.timeline-event__transition')?.textContent).toContain('weird_sisters');
    expect(screen.getByText('search_the_heath')).toBeTruthy();
    expect(screen.getByText(/Alternate-history scene/)).toBeTruthy();
    expect(screen.getByText('One saved path, shaped by the decisions recorded in this chronicle.')).toBeTruthy();
  });

  it('marks a supplied source reference that also contains original game material as mixed', () => {
    const scene = makeScene({ canonical_reference: 'Inspired by Act 1, Scene 1; this atmospheric framing is original game text.' });
    render(<StoryTimeline game={makeGame()} scene={scene} />);
    expect(screen.getByText(/Shakespeare source with original game material/)).toBeTruthy();
    expect(screen.queryByText(/^Shakespeare reference/)).toBeNull();
  });
});
