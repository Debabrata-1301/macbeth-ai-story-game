import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError, deleteGame, listCharacters, listGames, loadGame } from '../api/client';
import type { GameSummary, GameView } from '../api/types';
import { GameLibrary } from './GameLibrary';

vi.mock('../api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/client')>()),
  deleteGame: vi.fn(),
  listCharacters: vi.fn(),
  listGames: vi.fn(),
  loadGame: vi.fn(),
}));

const summaries: GameSummary[] = [
  { game_id: 'macbeth-save', selected_character_id: 'macbeth', campaign_id: 'macbeth', current_scene_id: 'heath', current_scene_title: 'Fair Is Foul', status: 'active', revision: 2, turn_number: 2, created_at: '2026-10-01T10:00:00Z', updated_at: '2026-10-02T10:00:00Z' },
  { game_id: 'banquo-save', selected_character_id: 'banquo', campaign_id: 'banquo', current_scene_id: 'heath', current_scene_title: 'The Heath Before Battle', status: 'active', revision: 0, turn_number: 0, created_at: '2026-10-03T10:00:00Z', updated_at: '2026-10-03T10:00:00Z' },
];
const authoritativeView = { game: { game_id: 'banquo-save', selected_character_id: 'banquo', event_history: [{ event_id: 'e1' }] }, scene: { title: 'The Heath Before Battle' } } as unknown as GameView;

describe('GameLibrary', () => {
  beforeEach(() => {
    vi.mocked(listGames).mockResolvedValue(summaries);
    vi.mocked(listCharacters).mockResolvedValue([
      { character_id: 'macbeth', name: 'Macbeth', role: 'Thane', personality: [], motivations: [], background: '' },
      { character_id: 'banquo', name: 'Banquo', role: 'General', personality: [], motivations: [], background: '' },
    ]);
    vi.mocked(loadGame).mockResolvedValue(authoritativeView);
    vi.mocked(deleteGame).mockResolvedValue();
  });

  afterEach(() => { cleanup(); vi.clearAllMocks(); });

  it('renders multiple saved games and marks the last saved identifier', async () => {
    render(<GameLibrary lastGameId="macbeth-save" onContinue={vi.fn()} onStartNew={vi.fn()} onBack={vi.fn()} onDeleted={vi.fn()} />);
    expect(await screen.findByText('Fair Is Foul')).toBeTruthy();
    expect(screen.getByText('The Heath Before Battle')).toBeTruthy();
    const lastGame = screen.getByText('Macbeth').closest('li') as HTMLElement;
    expect(within(lastGame).getByText('Last here')).toBeTruthy();
    expect(within(lastGame).getByText(/Last saved/)).toBeTruthy();
    expect(screen.getByText('macbeth-save')).toBeTruthy();
  });

  it('loads authoritative state and event history before continuing', async () => {
    const onContinue = vi.fn();
    render(<GameLibrary lastGameId={null} onContinue={onContinue} onStartNew={vi.fn()} onBack={vi.fn()} onDeleted={vi.fn()} />);
    await userEvent.setup().click((await screen.findAllByRole('button', { name: 'Continue' }))[0]);
    await waitFor(() => expect(loadGame).toHaveBeenCalledWith('macbeth-save'));
    expect(onContinue).toHaveBeenCalledWith(authoritativeView);
  });

  it('requires confirmation before deleting and then removes the saved game', async () => {
    const onDeleted = vi.fn();
    render(<GameLibrary lastGameId="macbeth-save" onContinue={vi.fn()} onStartNew={vi.fn()} onBack={vi.fn()} onDeleted={onDeleted} />);
    const entry = (await screen.findByText('Macbeth')).closest('li') as HTMLElement;
    await userEvent.setup().click(within(entry).getByRole('button', { name: 'Delete' }));
    expect(deleteGame).not.toHaveBeenCalled();
    await userEvent.setup().click(within(entry).getByRole('button', { name: 'Delete permanently' }));
    await waitFor(() => expect(deleteGame).toHaveBeenCalledWith('macbeth-save'));
    expect(onDeleted).toHaveBeenCalledWith('macbeth-save');
    await waitFor(() => expect(screen.queryByText('macbeth-save')).toBeNull());
  });

  it('reports an expired game when the authoritative load returns 404', async () => {
    vi.mocked(loadGame).mockRejectedValue(new ApiError('not found', 404));
    render(<GameLibrary lastGameId={null} onContinue={vi.fn()} onStartNew={vi.fn()} onBack={vi.fn()} onDeleted={vi.fn()} />);
    await userEvent.setup().click((await screen.findAllByRole('button', { name: 'Continue' }))[0]);
    expect((await screen.findByRole('alert')).textContent).toContain('This chronicle no longer exists');
  });

  it('shows an empty library and handles offline listing failures', async () => {
    vi.mocked(listGames).mockResolvedValueOnce([]);
    render(<GameLibrary lastGameId={null} onContinue={vi.fn()} onStartNew={vi.fn()} onBack={vi.fn()} onDeleted={vi.fn()} />);
    expect(await screen.findByText('No saved chronicles yet.')).toBeTruthy();
    cleanup();
    vi.mocked(listGames).mockRejectedValueOnce(new ApiError('offline'));
    render(<GameLibrary lastGameId={null} onContinue={vi.fn()} onStartNew={vi.fn()} onBack={vi.fn()} onDeleted={vi.fn()} />);
    expect((await screen.findByRole('alert')).textContent).toContain('offline');
  });

  it('keeps saved games available when optional character labels are missing', async () => {
    vi.mocked(listCharacters).mockRejectedValueOnce(new ApiError('profiles unavailable'));
    render(<GameLibrary lastGameId={null} onContinue={vi.fn()} onStartNew={vi.fn()} onBack={vi.fn()} onDeleted={vi.fn()} />);
    expect(await screen.findByText('macbeth')).toBeTruthy();
    expect(screen.getByText('Fair Is Foul')).toBeTruthy();
  });
});
