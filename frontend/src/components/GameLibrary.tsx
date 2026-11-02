import { useEffect, useState } from 'react';
import { ApiError, deleteGame, listCharacters, listGames, loadGame } from '../api/client';
import type { CharacterDefinition, GameSummary, GameView } from '../api/types';
import { campaignTitles } from '../content/characterIntroductions';
import { ActionButton } from './ActionButton';

interface GameLibraryProps {
  lastGameId: string | null;
  onContinue: (view: GameView) => void;
  onStartNew: () => void;
  onBack: () => void;
  onDeleted: (gameId: string) => void;
}

export function GameLibrary({ lastGameId, onContinue, onStartNew, onBack, onDeleted }: GameLibraryProps) {
  const [games, setGames] = useState<GameSummary[]>([]);
  const [characters, setCharacters] = useState<CharacterDefinition[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [pendingDelete, setPendingDelete] = useState<string | null>(null);

  async function refresh() {
    setLoading(true);
    setError(null);
    try {
      const savedGames = await listGames();
      setGames(savedGames);
      try {
        setCharacters(await listCharacters());
      } catch {
        setCharacters([]);
      }
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : 'The local game library could not be loaded.');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void refresh(); }, []);

  async function continueGame(gameId: string) {
    if (busyId) return;
    setBusyId(gameId);
    setError(null);
    try {
      onContinue(await loadGame(gameId));
    } catch (cause) {
      const message = cause instanceof ApiError && cause.status === 404
        ? 'This chronicle no longer exists. Refresh the library to update the list.'
        : cause instanceof ApiError ? cause.message : 'This chronicle could not be loaded.';
      setError(message);
    } finally {
      setBusyId(null);
    }
  }

  async function removeGame(gameId: string) {
    if (busyId) return;
    setBusyId(gameId);
    setError(null);
    try {
      await deleteGame(gameId);
      setGames((items) => items.filter((game) => game.game_id !== gameId));
      setPendingDelete(null);
      onDeleted(gameId);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : 'The chronicle could not be deleted.');
    } finally {
      setBusyId(null);
    }
  }

  const characterName = (id: string) => characters.find((character) => character.character_id === id)?.name
    ?? id.replaceAll('_', ' ');

  return (
    <main className="page-shell selection-shell">
      <header className="masthead" aria-label="Macbeth Chronicle">
        <span className="masthead__rule" aria-hidden="true" />
        <p className="masthead__eyebrow">The keepsake library</p>
        <span className="masthead__rule" aria-hidden="true" />
      </header>
      <section className="selection-book game-library" aria-labelledby="library-title">
        <div className="selection-heading">
          <p className="chapter-label">Saved in this local archive</p>
          <h1 id="library-title">Your Chronicles</h1>
          <p className="selection-intro">Each story is kept separately on this machine.</p>
        </div>

        {loading && <p role="status">Opening the library…</p>}
        {error && <div className="message message--error" role="alert">{error}</div>}
        {!loading && !error && games.length === 0 && (
          <div className="library-empty"><p>No saved chronicles yet.</p><p>Begin a new story to leave the first mark upon the page.</p></div>
        )}
        {!loading && games.length > 0 && (
          <ul className="library-list">
            {games.map((game) => (
              <li className="library-entry" key={game.game_id}>
                <div className="library-entry__copy">
                  <div className="library-entry__heading">
                    <h2>{characterName(game.selected_character_id)}</h2>
                    {game.game_id === lastGameId && <span className="library-last">Last here</span>}
                  </div>
                  <p className="library-scene">{game.current_scene_title}</p>
                  <p className="library-campaign">{campaignTitles[game.campaign_id] ?? 'Macbeth Chronicle'}</p>
                  <p className="library-meta">{game.status} · Turn {game.turn_number} · Last saved {new Date(game.updated_at).toLocaleString()}</p>
                  <p className="library-id">{game.game_id}</p>
                  {pendingDelete === game.game_id && (
                    <div className="library-confirm" role="group" aria-label={`Confirm deletion of ${characterName(game.selected_character_id)} chronicle`}>
                      <span>This permanently removes this story and its event history.</span>
                      <button type="button" className="text-action text-action--danger" disabled={busyId !== null} onClick={() => void removeGame(game.game_id)}>Delete permanently</button>
                      <button type="button" className="text-action" disabled={busyId !== null} onClick={() => setPendingDelete(null)}>Keep chronicle</button>
                    </div>
                  )}
                </div>
                <div className="library-entry__actions">
                  <ActionButton onClick={() => void continueGame(game.game_id)} disabled={busyId !== null}>
                    {busyId === game.game_id ? 'Opening…' : 'Continue'}
                  </ActionButton>
                  <button type="button" className="text-action text-action--danger" disabled={busyId !== null} onClick={() => setPendingDelete(game.game_id)}>
                    Delete
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}

        <div className="introduction-actions library-footer">
          <ActionButton onClick={onStartNew}>Start a New Chronicle</ActionButton>
          <ActionButton variant="secondary" onClick={onBack}>Return to main menu</ActionButton>
          <button type="button" className="retry-link" onClick={() => void refresh()} disabled={loading || busyId !== null}>Refresh library</button>
        </div>
      </section>
    </main>
  );
}
