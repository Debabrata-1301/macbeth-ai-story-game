import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError, getHealth, listCharacters, loadGame, startGame } from './api/client';
import type { CharacterDefinition, GameView } from './api/types';
import { ActionButton } from './components/ActionButton';
import { CharacterSelection } from './components/CharacterSelection';
import { GameIntroduction } from './components/GameIntroduction';
import { GameplayScreen } from './components/GameplayScreen';
import { GameLibrary } from './components/GameLibrary';
import { HealthStatus } from './components/HealthStatus';
import { forgetGameId, getSavedGameId, rememberGameId } from './sessionStorage';

type Screen = 'welcome' | 'library' | 'selection' | 'introduction' | 'gameplay';

function WelcomeScreen({
  online,
  busy,
  savedGameId,
  error,
  onStart,
  onContinue,
  onLibrary,
  onCheckHealth,
}: {
  online: boolean | null;
  busy: 'continue' | null;
  savedGameId: string | null;
  error: string | null;
  onStart: () => void;
  onContinue: () => void;
  onLibrary: () => void;
  onCheckHealth: () => void;
}) {
  return (
    <main className="page-shell">
      <header className="masthead" aria-label="Macbeth Chronicle">
        <span className="masthead__rule" aria-hidden="true" />
        <p className="masthead__eyebrow">A branching chronicle</p>
        <span className="masthead__rule" aria-hidden="true" />
      </header>

      <section className="book" aria-labelledby="page-title">
        <div className="book__gutter" aria-hidden="true" />
        <div className="book__page">
          <div className="book__topline">
            <span>Inverness · Scotland</span>
            <HealthStatus online={online} />
          </div>

          <div className="ornament" aria-hidden="true"><span>✦</span></div>
          <p className="chapter-label">The Scottish tragedy</p>
          <h1 id="page-title" className="welcome-title">MACBETH</h1>
          <p className="subtitle welcome-subtitle">A TALE OF AMBITION, BLOOD AND FATE</p>

          <div className="title-rule" aria-hidden="true"><span>❧</span></div>

          <div className="intro-copy">
            <p className="illuminated">When the heath is troubled and the future speaks in riddles, one choice may alter the course of Scotland.</p>
            <p>Enter a story inspired by Shakespeare’s tragedy, where the old words cast long shadows over new paths.</p>
          </div>

          <div className="actions" aria-label="Chronicle actions">
            <ActionButton onClick={onStart} disabled={online === false || busy !== null}>
              Begin a New Chronicle
            </ActionButton>
            <ActionButton
              variant="secondary"
              onClick={onContinue}
              disabled={online === false || !savedGameId || busy !== null}
            >
              {busy === 'continue' ? 'Finding your place…' : 'Continue Last Chronicle'}
            </ActionButton>
            <ActionButton variant="secondary" onClick={onLibrary} disabled={online === false || busy !== null}>
              Open Game Library
            </ActionButton>
          </div>
          {!savedGameId && <p className="action-note">Continue becomes available after this browser starts a chronicle.</p>}
          {online === false && (
            <div className="connection-note">
              <p className="action-note">Start the local FastAPI service to open or continue a chronicle.</p>
              <button className="retry-link" type="button" onClick={onCheckHealth}>Check the connection again</button>
            </div>
          )}
          {error && <div className="message message--error" role="alert">{error}</div>}

          <footer className="page-footer">
            <span>Act I</span>
            <span className="page-footer__diamond" aria-hidden="true">◆</span>
            <span>Choose with care</span>
          </footer>
        </div>
      </section>

      <p className="colophon">A local story · Kept on your own machine</p>
    </main>
  );
}

function App() {
  const [screen, setScreen] = useState<Screen>('welcome');
  const [selectionReturnScreen, setSelectionReturnScreen] = useState<'welcome' | 'library'>('welcome');
  const [online, setOnline] = useState<boolean | null>(null);
  const [savedGameId, setSavedGameId] = useState<string | null>(() => getSavedGameId());
  const [session, setSession] = useState<GameView | null>(null);
  const [storageWarning, setStorageWarning] = useState(false);
  const [welcomeError, setWelcomeError] = useState<string | null>(null);
  const [characters, setCharacters] = useState<CharacterDefinition[]>([]);
  const [charactersLoading, setCharactersLoading] = useState(false);
  const [charactersError, setCharactersError] = useState<string | null>(null);
  const [selectedCharacterId, setSelectedCharacterId] = useState<string | null>(null);
  const [selectionBusy, setSelectionBusy] = useState(false);
  const [selectionError, setSelectionError] = useState<string | null>(null);
  const [characterLoadAttempt, setCharacterLoadAttempt] = useState(0);
  const [continuing, setContinuing] = useState(false);
  const createLock = useRef(false);

  const checkHealth = useCallback(async () => {
    try {
      const health = await getHealth();
      setOnline(health.status === 'ok');
    } catch {
      setOnline(false);
    }
  }, []);

  useEffect(() => {
    void checkHealth();
  }, [checkHealth]);

  useEffect(() => {
    if (screen !== 'selection') return;
    let active = true;
    setCharactersLoading(true);
    setCharactersError(null);
    void listCharacters()
      .then((items) => {
        if (active) {
          setCharacters(items);
          setOnline(true);
        }
      })
      .catch((cause: unknown) => {
        if (active) {
          setCharactersError(cause instanceof ApiError ? cause.message : 'The company of characters could not be fetched.');
          setOnline(false);
        }
      })
      .finally(() => {
        if (active) setCharactersLoading(false);
      });
    return () => { active = false; };
  }, [screen, characterLoadAttempt]);

  function openCharacterSelection(returnTo: 'welcome' | 'library' = 'welcome') {
    setSelectionReturnScreen(returnTo);
    setSelectedCharacterId(null);
    setSelectionError(null);
    setScreen('selection');
  }

  async function confirmCharacter() {
    if (!selectedCharacterId || createLock.current) return;
    createLock.current = true;
    setSelectionBusy(true);
    setSelectionError(null);
    try {
      const created = await startGame({ character_id: selectedCharacterId, story_mode: 'hybrid' });
      setSession(created);
      setSavedGameId(created.game.game_id);
      setStorageWarning(!rememberGameId(created.game.game_id));
      setOnline(true);
      setScreen('introduction');
    } catch (cause) {
      setSelectionError(cause instanceof ApiError ? cause.message : 'The new chronicle could not be created.');
      setOnline(false);
    } finally {
      createLock.current = false;
      setSelectionBusy(false);
    }
  }

  async function continueChronicle() {
    if (!savedGameId || continuing) return;
    setContinuing(true);
    setWelcomeError(null);
    try {
      const loaded = await loadGame(savedGameId);
      setSession(loaded);
      setStorageWarning(false);
      setSavedGameId(loaded.game.game_id);
      setOnline(true);
      setScreen('introduction');
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 404) {
        forgetGameId(savedGameId);
        setSavedGameId(null);
        setWelcomeError('That saved chronicle was removed. Open the game library to choose another.');
        setOnline(true);
      } else {
        setWelcomeError(cause instanceof ApiError ? cause.message : 'The saved chronicle could not be loaded.');
        setOnline(false);
      }
    } finally {
      setContinuing(false);
    }
  }

  function continueFromLibrary(view: GameView) {
    setSession(view);
    setSavedGameId(view.game.game_id);
    setStorageWarning(!rememberGameId(view.game.game_id));
    setOnline(true);
    setScreen('introduction');
  }

  function handleGameDeleted(gameId: string) {
    if (savedGameId === gameId) {
      forgetGameId(gameId);
      setSavedGameId(getSavedGameId());
    }
  }

  if (screen === 'library') {
    return (
      <GameLibrary
        lastGameId={savedGameId}
        onContinue={continueFromLibrary}
        onStartNew={() => openCharacterSelection('library')}
        onBack={() => setScreen('welcome')}
        onDeleted={handleGameDeleted}
      />
    );
  }

  if (screen === 'selection') {
    return (
      <CharacterSelection
        characters={characters}
        selectedId={selectedCharacterId}
        busy={selectionBusy}
        loading={charactersLoading}
        charactersError={charactersError}
        submitError={selectionError}
        onSelect={(characterId) => {
          setSelectedCharacterId(characterId);
          setSelectionError(null);
        }}
        onConfirm={() => void confirmCharacter()}
        backLabel={selectionReturnScreen === 'library' ? 'Back to game library' : 'Back to welcome'}
        onBack={() => setScreen(selectionReturnScreen)}
        onRetry={() => setCharacterLoadAttempt((attempt) => attempt + 1)}
      />
    );
  }

  if (screen === 'introduction' && session) {
    return (
      <GameIntroduction
        session={session}
        storageWarning={storageWarning}
        onEnter={() => setScreen('gameplay')}
        onBack={() => setScreen('library')}
      />
    );
  }

  if (screen === 'gameplay' && session) {
    return (
      <GameplayScreen
        initialView={session}
        onGameUpdated={(view) => setSession(view)}
        onBack={() => setScreen('introduction')}
      />
    );
  }

  return (
    <WelcomeScreen
      online={online}
      busy={continuing ? 'continue' : null}
      savedGameId={savedGameId}
      error={welcomeError}
      onStart={openCharacterSelection}
      onContinue={() => void continueChronicle()}
      onLibrary={() => setScreen('library')}
      onCheckHealth={() => void checkHealth()}
    />
  );
}

export default App;
