import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ChoiceAvailability, GameplayTurnResponse, GameState, GameView, NarrativeResponse } from '../api/types';
import { getGameChoices, listCharacters, loadGame, retryNarrative, submitGameplayTurn } from '../api/client';
import { GameplayScreen } from './GameplayScreen';

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return {
    ...actual,
    getGameChoices: vi.fn(),
    listCharacters: vi.fn(),
    loadGame: vi.fn(),
    retryNarrative: vi.fn(),
    submitGameplayTurn: vi.fn(),
  };
});

const gameId = 'saved-game-42';
const firstChoice = {
  choice_id: 'press_to_forres',
  action_id: 'ride_on',
  description: 'Ride on toward Forres with Banquo.',
  prerequisites: [],
  state_flags: {},
  next_scene_id: 'weird_sisters',
  conditions: { required_flags: {}, required_alive: [], required_known_facts: [], relationship_character: null, min_trust: null, max_trust: null, min_hostility: null, max_hostility: null, minimum_attributes: {}, maximum_attributes: {} },
  character_changes: {},
  relationship_changes: [],
  grants_knowledge: [],
};
const nextChoice = { ...firstChoice, choice_id: 'heed_the_warning', description: 'Listen closely to the strange sisters.' };
const firstScene = {
  scene_id: 'heath_before_battle',
  title: 'The Heath Before Battle',
  location: 'A storm-swept heath near Forres',
  canonical_reference: 'Macbeth, Act 1, Scene 1',
  source_classification: 'alternate_history',
  source_act_id: null,
  source_scene_id: null,
  participants: ['macbeth', 'banquo'],
  summary: 'A storm gathers.',
  opening_narration: 'The storm gathers across the heath.',
  available_choices: [firstChoice],
  is_ending: false,
  ending_id: null,
};
const updatedScene = {
  ...firstScene,
  scene_id: 'weird_sisters',
  title: 'Fair Is Foul',
  location: 'A desolate heath',
  canonical_reference: 'Macbeth, Act 1, Scene 3',
  source_classification: 'canonical_adaptation',
  source_act_id: 'act_1',
  source_scene_id: 'scene_3',
  opening_narration: 'Thunder rolls over the moor.',
  available_choices: [nextChoice],
};

function makeGame(revision = 0, sceneId = 'heath_before_battle'): GameState {
  return {
    game_id: gameId,
    selected_character_id: 'macbeth',
    campaign_id: 'macbeth',
    story_mode: 'hybrid',
    perspective: 'first_person',
    current_scene_id: sceneId,
    character_states: {},
    relationships: [],
    flags: {},
    turn_number: revision,
    status: 'active',
    ending_id: null,
    revision,
    created_at: '2026-10-30T00:00:00Z',
    updated_at: '2026-10-30T00:00:00Z',
    event_history: revision > 0 ? [{
      event_id: 'event-choice-1', event_type: 'choice_made', actor_id: 'macbeth',
      scene_id: 'heath_before_battle', metadata: { choice_id: 'press_to_forres' }, timestamp: '2026-10-30T00:00:01Z',
    }] : [],
  };
}

function makeView(revision = 0, scene = revision > 0 ? updatedScene : firstScene): GameView {
  return { game: makeGame(revision, scene.scene_id), scene } as GameView;
}

const firstAvailability: ChoiceAvailability[] = [{ choice: firstChoice, available: true, reason: null }];
const updatedAvailability: ChoiceAvailability[] = [{ choice: nextChoice, available: true, reason: null }];
const narrative: NarrativeResponse = {
  narration: 'I ride beneath a sky bruised by storm.',
  dialogue: [{ speaker: 'Banquo', text: 'The day is foul and fair.' }],
  atmosphere: 'Thunder mutters across the open moor.',
  choices: [{ choice_id: 'heed_the_warning', text: 'Attend to the sisters.' }],
  source_references: [],
};

function makeTurnResult(overrides: Partial<GameplayTurnResponse> = {}): GameplayTurnResponse {
  return {
    game: makeGame(1, 'weird_sisters'),
    narrative,
    available_choices: updatedAvailability,
    request_id: 'request-turn-1',
    transition_applied: true,
    replayed: false,
    generation_error_code: null,
    generation_error: null,
    ...overrides,
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}

beforeEach(() => {
  vi.mocked(getGameChoices).mockReset().mockResolvedValue(firstAvailability);
  vi.mocked(listCharacters).mockReset().mockResolvedValue([
    { character_id: 'macbeth', name: 'Macbeth', role: 'Thane', personality: [], motivations: [], background: '' },
  ]);
  vi.mocked(loadGame).mockReset().mockResolvedValue(makeView(1));
  vi.mocked(retryNarrative).mockReset();
  vi.mocked(submitGameplayTurn).mockReset();
});

afterEach(cleanup);

describe('GameplayScreen', () => {
  it('renders the opening narration, character, location, and recorded decision history', async () => {
    render(<GameplayScreen initialView={makeView(1)} onGameUpdated={vi.fn()} onBack={vi.fn()} />);

    expect(await screen.findByText('Thunder rolls over the moor.')).toBeTruthy();
    expect(screen.getByRole('heading', { name: 'Macbeth' })).toBeTruthy();
    expect(screen.getByText('A desolate heath')).toBeTruthy();
    expect(screen.getByText('press_to_forres')).toBeTruthy();
  });

  it('shows the backend opening narration and available engine choices before the first turn', async () => {
    render(<GameplayScreen initialView={makeView()} onGameUpdated={vi.fn()} onBack={vi.fn()} />);

    expect(await screen.findByText('The storm gathers across the heath.')).toBeTruthy();
    expect(screen.getByRole('button', { name: /Ride on toward Forres with Banquo/ })).toBeTruthy();
  });

  it('submits the selected engine choice ID with the saved game ID and updates the scene and narrative', async () => {
    vi.mocked(submitGameplayTurn).mockResolvedValue(makeTurnResult());
    const onGameUpdated = vi.fn();
    render(<GameplayScreen initialView={makeView()} onGameUpdated={onGameUpdated} onBack={vi.fn()} />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: /Ride on toward Forres with Banquo/ }));

    expect(await screen.findByRole('heading', { name: 'Fair Is Foul' })).toBeTruthy();
    expect(screen.getByText('I ride beneath a sky bruised by storm.')).toBeTruthy();
    expect(screen.getByText('The day is foul and fair.')).toBeTruthy();
    expect(screen.getByText('Thunder mutters across the open moor.')).toBeTruthy();
    expect(screen.getByText('Decision accepted. Your updated story is saved on this machine.')).toBeTruthy();
    expect(screen.getByRole('button', { name: /Listen closely to the strange sisters/ })).toBeTruthy();
    expect(submitGameplayTurn).toHaveBeenCalledWith(gameId, {
      choice_id: 'press_to_forres', request_id: expect.any(String),
    });
    expect(onGameUpdated).toHaveBeenCalled();
  });

  it('shows only validated source provenance when the narrator returns references', async () => {
    vi.mocked(submitGameplayTurn).mockResolvedValue(makeTurnResult({
      narrative: { ...narrative, source_references: [{ source_document: 'macbeth.pdf', act: 'act_2',
        scene: 'scene_2', page_number: 18, reference_id: 'chunk-18' }] },
    }));
    render(<GameplayScreen initialView={makeView()} onGameUpdated={vi.fn()} onBack={vi.fn()} />);
    await userEvent.setup().click(await screen.findByRole('button', { name: /Ride on toward Forres with Banquo/ }));
    expect(await screen.findByText('Reference passages')).toBeTruthy();
    expect(screen.getByText(/macbeth.pdf · act 2, scene 2 · page 18/)).toBeTruthy();
  });

  it('shows loading and blocks duplicate clicks while a turn is pending', async () => {
    const pending = deferred<GameplayTurnResponse>();
    vi.mocked(submitGameplayTurn).mockReturnValue(pending.promise);
    render(<GameplayScreen initialView={makeView()} onGameUpdated={vi.fn()} onBack={vi.fn()} />);
    const choice = await screen.findByRole('button', { name: /Ride on toward Forres with Banquo/ });
    fireEvent.click(choice);
    fireEvent.click(choice);

    expect(screen.getByText(/ink is still drying/)).toBeTruthy();
    expect(submitGameplayTurn).toHaveBeenCalledOnce();
    pending.resolve(makeTurnResult());
    await screen.findByRole('heading', { name: 'Fair Is Foul' });
  });

  it('recovers narration through the retry route without submitting the choice again', async () => {
    vi.mocked(submitGameplayTurn).mockResolvedValue(makeTurnResult({
      narrative: null,
      generation_error_code: 'ollama_unavailable',
      generation_error: 'Local Ollama service is unavailable',
    }));
    vi.mocked(retryNarrative).mockResolvedValue(makeTurnResult({ transition_applied: false, replayed: false }));
    render(<GameplayScreen initialView={makeView()} onGameUpdated={vi.fn()} onBack={vi.fn()} />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: /Ride on toward Forres with Banquo/ }));
    expect((await screen.findByRole('alert')).textContent).toContain('Your choice is saved');
    expect(screen.getByText('Decision accepted. Your updated story is saved on this machine.')).toBeTruthy();
    await user.click(screen.getByRole('button', { name: 'Retry narration' }));

    expect(await screen.findByText('I ride beneath a sky bruised by storm.')).toBeTruthy();
    expect(submitGameplayTurn).toHaveBeenCalledOnce();
    expect(retryNarrative).toHaveBeenCalledWith(gameId);
  });

  it('retries an uncertain network result with the same request ID', async () => {
    const { ApiError } = await import('../api/client');
    vi.mocked(submitGameplayTurn)
      .mockRejectedValueOnce(new ApiError('Timed out', undefined, true))
      .mockResolvedValueOnce(makeTurnResult());
    render(<GameplayScreen initialView={makeView()} onGameUpdated={vi.fn()} onBack={vi.fn()} />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: /Ride on toward Forres with Banquo/ }));
    await user.click(await screen.findByRole('button', { name: 'Check the same turn safely' }));

    await screen.findByRole('heading', { name: 'Fair Is Foul' });
    const firstRequest = vi.mocked(submitGameplayTurn).mock.calls[0][1];
    const retryRequest = vi.mocked(submitGameplayTurn).mock.calls[1][1];
    expect(retryRequest).toEqual(firstRequest);
  });

  it('reports an invalid choice and reloads server-authorized choices', async () => {
    const { ApiError } = await import('../api/client');
    vi.mocked(submitGameplayTurn).mockRejectedValue(new ApiError('Choice is no longer available.', 422));
    vi.mocked(getGameChoices).mockResolvedValueOnce(firstAvailability).mockResolvedValueOnce(updatedAvailability);
    vi.mocked(loadGame).mockResolvedValue(makeView(0));
    render(<GameplayScreen initialView={makeView()} onGameUpdated={vi.fn()} onBack={vi.fn()} />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: /Ride on toward Forres with Banquo/ }));

    expect((await screen.findByRole('alert')).textContent).toContain('no longer available');
    expect(await screen.findByRole('button', { name: /Listen closely to the strange sisters/ })).toBeTruthy();
  });
});
