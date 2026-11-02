import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import App from './App';

const profiles = [
  { character_id: 'macbeth', name: 'Macbeth', role: 'Thane of Glamis', personality: ['brave', 'ambitious'], motivations: ['honor', 'power'], background: 'A celebrated Scottish thane.' },
  { character_id: 'lady_macbeth', name: 'Lady Macbeth', role: 'Noblewoman of Inverness', personality: ['resolute', 'perceptive'], motivations: ['influence', 'security'], background: 'Macbeth’s wife.' },
  { character_id: 'banquo', name: 'Banquo', role: 'Scottish general', personality: ['cautious', 'loyal'], motivations: ['honor', 'truth'], background: 'A fellow general.' },
  { character_id: 'macduff', name: 'Macduff', role: 'Thane of Fife', personality: ['dutiful', 'watchful'], motivations: ['justice', 'Scotland’s safety'], background: 'A Scottish nobleman.' },
];

const gameView = (selectedCharacterId: string) => ({
  game: { game_id: 'local-game-123', selected_character_id: selectedCharacterId },
  scene: {
    scene_id: 'heath_before_battle',
    title: 'The Heath Before Battle',
    location: 'A storm-swept heath near Forres',
    opening_narration: 'The storm gathers across the heath.',
  },
});

function jsonResponse(body: unknown, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: async () => body };
}

describe('character selection flow', () => {
  const storage = new Map<string, string>();

  beforeEach(() => {
    storage.clear();
    Object.defineProperty(window, 'localStorage', {
      configurable: true,
      value: {
        get length() { return storage.size; },
        key: (index: number) => [...storage.keys()][index] ?? null,
        getItem: (key: string) => storage.get(key) ?? null,
        setItem: (key: string, value: string) => { storage.set(key, String(value)); },
        removeItem: (key: string) => storage.delete(key),
        clear: () => storage.clear(),
      } as Storage,
    });
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it('sends the selected character once, remembers the returned game, and opens the introduction', async () => {
    const requests: Array<{ url: string; init?: RequestInit }> = [];
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      requests.push({ url, init });
      if (url.endsWith('/health')) return jsonResponse({ service: 'Macbeth AI Story Game', status: 'ok' });
      if (url.endsWith('/characters')) return jsonResponse(profiles);
      if (url.endsWith('/games') && init?.method === 'POST') {
        await new Promise((resolve) => setTimeout(resolve, 20));
        return jsonResponse(gameView('banquo'), 201);
      }
      throw new Error(`Unexpected request: ${url}`);
    }));

    const user = userEvent.setup();
    render(<App />);
    await user.click(await screen.findByRole('button', { name: 'Begin a New Chronicle' }));
    const banquoCard = screen.getByRole('heading', { name: 'Banquo' }).closest('article') as HTMLElement;
    await user.click(within(banquoCard).getByRole('button', { name: 'Choose this campaign' }));
    const confirm = screen.getByRole('button', { name: 'Confirm and begin' });
    fireEvent.click(confirm);
    fireEvent.click(confirm);

    expect(await screen.findByRole('heading', { name: 'The Heath Before Battle' })).toBeTruthy();
    const createRequests = requests.filter((request) => request.url.endsWith('/games') && request.init?.method === 'POST');
    expect(createRequests).toHaveLength(1);
    expect(JSON.parse(String(createRequests[0].init?.body))).toEqual({ character_id: 'banquo', story_mode: 'hybrid' });
    expect(window.localStorage.getItem('macbeth.current-game-id')).toBe('local-game-123');
    expect(screen.getByText('Your chronicle is saved. Enter the story when you are ready.')).toBeTruthy();
  });

  it('shows a creation error without losing the current selection', async () => {
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith('/health')) return jsonResponse({ service: 'Macbeth AI Story Game', status: 'ok' });
      if (url.endsWith('/characters')) return jsonResponse(profiles);
      if (url.endsWith('/games') && init?.method === 'POST') {
        return jsonResponse({ detail: 'Unknown playable character.' }, 422);
      }
      throw new Error(`Unexpected request: ${url}`);
    }));

    const user = userEvent.setup();
    render(<App />);
    await user.click(await screen.findByRole('button', { name: 'Begin a New Chronicle' }));
    const macduffCard = screen.getByRole('heading', { name: 'Macduff' }).closest('article') as HTMLElement;
    await user.click(within(macduffCard).getByRole('button', { name: 'Choose this campaign' }));
    await user.click(screen.getByRole('button', { name: 'Confirm and begin' }));

    expect((await screen.findByRole('alert')).textContent).toContain('Unknown playable character.');
    expect(screen.getByRole('button', { name: 'Chosen' }).getAttribute('aria-pressed')).toBe('true');
    expect(screen.getByRole('button', { name: 'Confirm and begin' }).hasAttribute('disabled')).toBe(false);
  });

  it('clears a deleted last-game identifier and leaves the library available', async () => {
    storage.set('macbeth.current-game-id', 'deleted-save');
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith('/health')) return jsonResponse({ service: 'Macbeth AI Story Game', status: 'ok' });
      if (url.endsWith('/games/deleted-save')) return jsonResponse({ detail: 'Game was not found.' }, 404);
      throw new Error(`Unexpected request: ${url}`);
    }));

    const user = userEvent.setup();
    render(<App />);
    await user.click(await screen.findByRole('button', { name: 'Continue Last Chronicle' }));
    expect((await screen.findByRole('alert')).textContent).toContain('That saved chronicle was removed');
    expect(window.localStorage.getItem('macbeth.current-game-id')).toBeNull();
    expect(screen.getByRole('button', { name: 'Open Game Library' }).hasAttribute('disabled')).toBe(false);
  });
});
