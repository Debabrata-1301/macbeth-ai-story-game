import { useEffect, useRef, useState } from 'react';
import {
  ApiError,
  getGameChoices,
  listCharacters,
  loadGame,
  retryNarrative,
  submitGameplayTurn,
} from '../api/client';
import type {
  CharacterDefinition,
  ChoiceAvailability,
  GameplayTurnRequest,
  GameplayTurnResponse,
  GameView,
  NarrativeResponse,
} from '../api/types';
import { ActionButton } from './ActionButton';
import { BranchChoice } from './BranchChoice';
import { CharacterStatusPanel } from './CharacterStatusPanel';
import { StoryTimeline } from './StoryTimeline';
import { campaignTitles } from '../content/characterIntroductions';

interface GameplayScreenProps {
  initialView: GameView;
  onGameUpdated: (view: GameView) => void;
  onBack: () => void;
}

function makeRequestId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function selectedCharacterName(id: string, characters: CharacterDefinition[]): string {
  return characters.find((character) => character.character_id === id)?.name ?? id.replaceAll('_', ' ');
}

function dialogueSpeakerName(id: string, characters: CharacterDefinition[]): string {
  const nonPlayableNames: Record<string, string> = {
    duncan: 'Duncan',
    weird_sisters: 'The Weird Sisters',
  };
  return nonPlayableNames[id] ?? selectedCharacterName(id, characters);
}

function generationMessage(code: string | null, detail: string | null): string {
  if (code === 'ollama_unavailable') return 'The local narrator is unavailable. Your choice is saved; you can retry the narration when it returns.';
  if (code === 'generation_timeout') return 'The narrator took too long to answer. Your choice is saved; retry narration to continue.';
  if (code === 'narrative_validation_failed') return 'The narrator’s response could not be safely used. Your choice is saved; you can ask for new narration.';
  if (code === 'narrative_retrieval_failed') return 'The source passages could not be retrieved. Your choice is saved; retry narration when the library is available.';
  return detail
    ? `Your choice is saved, but narration could not be generated: ${detail}`
    : 'Your choice is saved, but narration could not be generated. You can retry it.';
}

function requestErrorMessage(error: unknown): string {
  if (!(error instanceof ApiError)) return 'The turn could not be confirmed. Use the safe retry to check its result.';
  if (error.status === 404) return 'This saved chronicle could not be found. Return to the title and choose another session.';
  if (error.status === 409) return 'The chronicle changed before this choice was accepted. Refresh the saved state before choosing again.';
  if (error.status === 422) return 'That choice is no longer available in this scene. The current choices are being refreshed.';
  return error.message;
}

export function GameplayScreen({ initialView, onGameUpdated, onBack }: GameplayScreenProps) {
  const [game, setGame] = useState(initialView.game);
  const [scene, setScene] = useState(initialView.scene);
  const [narrative, setNarrative] = useState<NarrativeResponse | null>(null);
  const [choices, setChoices] = useState<ChoiceAvailability[]>([]);
  const [characters, setCharacters] = useState<CharacterDefinition[]>([]);
  const [loadingChoices, setLoadingChoices] = useState(true);
  const [turnBusy, setTurnBusy] = useState(false);
  const [retryBusy, setRetryBusy] = useState(false);
  const [sceneBusy, setSceneBusy] = useState(false);
  const [requestError, setRequestError] = useState<string | null>(null);
  const [sceneError, setSceneError] = useState<string | null>(null);
  const [generationError, setGenerationError] = useState<string | null>(null);
  const [initialLoadError, setInitialLoadError] = useState<string | null>(null);
  const [transitionSaved, setTransitionSaved] = useState(false);
  const [uncertainRequest, setUncertainRequest] = useState<GameplayTurnRequest | null>(null);
  const inFlight = useRef(false);
  const gameId = initialView.game.game_id;
  const busy = turnBusy || retryBusy || sceneBusy;

  useEffect(() => {
    let active = true;
    setLoadingChoices(true);
    void Promise.allSettled([getGameChoices(gameId), listCharacters()])
      .then(([availableResult, characterResult]) => {
        if (!active) return;
        if (availableResult.status === 'rejected') {
          const cause: unknown = availableResult.reason;
          setInitialLoadError(cause instanceof ApiError && cause.status === 404
            ? 'This saved chronicle could not be found.'
            : 'The scene and its choices could not be loaded from the local game service.');
          return;
        }
        setChoices(availableResult.value);
        if (characterResult.status === 'fulfilled') setCharacters(characterResult.value);
      })
      .finally(() => { if (active) setLoadingChoices(false); });
    return () => { active = false; };
  }, [gameId]);

  async function refreshChoices() {
    setLoadingChoices(true);
    setInitialLoadError(null);
    try {
      const [available, refreshed] = await Promise.all([getGameChoices(gameId), loadGame(gameId)]);
      setChoices(available);
      setGame(refreshed.game);
      setScene(refreshed.scene);
      onGameUpdated(refreshed);
    } catch (cause) {
      setInitialLoadError(requestErrorMessage(cause));
    } finally {
      setLoadingChoices(false);
    }
  }

  async function refreshScene() {
    setSceneBusy(true);
    setSceneError(null);
    try {
      const refreshed = await loadGame(gameId);
      setScene(refreshed.scene);
      setGame((current) => refreshed.game.revision >= current.revision ? refreshed.game : current);
      onGameUpdated(refreshed);
    } catch {
      setSceneError('The turn was saved, but scene details could not be refreshed. Try refreshing them.');
    } finally {
      setSceneBusy(false);
    }
  }

  function acceptTurn(result: GameplayTurnResponse) {
    setTransitionSaved(true);
    setGame(result.game);
    onGameUpdated({ game: result.game, scene });
    setChoices(result.available_choices);
    setNarrative(result.narrative);
    setUncertainRequest(null);
    setRequestError(null);
    setInitialLoadError(null);
    setGenerationError(result.generation_error_code
      ? generationMessage(result.generation_error_code, result.generation_error)
      : null);
    void refreshScene();
  }

  async function sendTurn(request: GameplayTurnRequest) {
    if (inFlight.current) return;
    inFlight.current = true;
    setTurnBusy(true);
    setRequestError(null);
    setGenerationError(null);
    try {
      const result = await submitGameplayTurn(gameId, request);
      acceptTurn(result);
    } catch (cause) {
      setRequestError(requestErrorMessage(cause));
      if (cause instanceof ApiError && cause.status === undefined) {
        // Keep the same idempotency key. Reposting it can safely recover a lost response.
        setUncertainRequest(request);
      } else {
        setUncertainRequest(null);
        if (cause instanceof ApiError && (cause.status === 409 || cause.status === 422)) {
          void refreshChoices();
        }
      }
    } finally {
      inFlight.current = false;
      setTurnBusy(false);
    }
  }

  function choose(choiceId: string) {
    if (busy || inFlight.current || uncertainRequest || initialLoadError) return;
    void sendTurn({ choice_id: choiceId, request_id: makeRequestId() });
  }

  async function repeatUncertainTurn() {
    if (uncertainRequest) await sendTurn(uncertainRequest);
  }

  async function requestNarrativeRetry() {
    if (inFlight.current) return;
    inFlight.current = true;
    setRetryBusy(true);
    setGenerationError(null);
    try {
      const result = await retryNarrative(gameId);
      acceptTurn(result);
    } catch (cause) {
      setGenerationError(cause instanceof ApiError
        ? `Narration could not be retried: ${cause.message}`
        : 'Narration could not be retried. Your saved choice remains in place.');
    } finally {
      inFlight.current = false;
      setRetryBusy(false);
    }
  }

  const availableChoices = choices.filter((item) => item.available);
  const characterName = selectedCharacterName(game.selected_character_id, characters);
  const sceneHeading = scene.scene_id === game.current_scene_id ? scene.title : game.current_scene_id;

  return (
    <main className="page-shell gameplay-shell">
      <header className="masthead" aria-label="Macbeth Chronicle">
        <span className="masthead__rule" aria-hidden="true" />
        <p className="masthead__eyebrow">The Scottish chronicle</p>
        <span className="masthead__rule" aria-hidden="true" />
      </header>

      <section className="storybook" aria-labelledby="scene-heading">
        <header className="storybook__header">
          <div>
            <p className="storybook__series">{campaignTitles[game.campaign_id] ?? 'Macbeth'} · A Chronicle in Choices</p>
            <p className="storybook__perspective">Your perspective</p>
            <h1>{characterName}</h1>
          </div>
          <div className="storybook__session" role="status">
            <span className={`session-seal session-seal--${game.status}`} />
            <span>{game.status === 'active' ? 'Saved · Active' : `Saved · ${game.status}`}</span>
          </div>
        </header>

        {transitionSaved && (
          <p className="transition-saved" role="status">
            Decision accepted. Your updated story is saved on this machine.
          </p>
        )}

        <div className="storybook__chapter">
          <span className="chapter-rule" aria-hidden="true" />
          <div>
            <p>{scene.canonical_reference || 'Current scene'}</p>
            <span className={`source-label source-label--${scene.source_classification}`}>
              {scene.source_classification === 'alternate_history'
                ? 'Alternate-history divergence'
                : 'Shakespearean events, adapted'}
            </span>
            <h2 id="scene-heading">{sceneHeading}</h2>
            <span>{scene.location}</span>
          </div>
          <span className="chapter-rule" aria-hidden="true" />
        </div>

        <div className="storybook__body">
          <article className="story-text" aria-label="Story narration" aria-live="polite">
            {narrative ? (
              <>
                <p className="story-text__narration">{narrative.narration}</p>
                {narrative.dialogue.length > 0 && (
                  <div className="dialogue-list" aria-label="Dialogue">
                    {narrative.dialogue.map((line, index) => (
                      <blockquote className="dialogue-line" key={`${line.speaker}-${index}`}>
                        <span className="dialogue-line__speaker">{dialogueSpeakerName(line.speaker, characters)}</span>
                        <p>{line.text}</p>
                      </blockquote>
                    ))}
                  </div>
                )}
                {narrative.atmosphere && (
                  <aside className="atmosphere-note">
                    <span>In the air</span>
                    <p>{narrative.atmosphere}</p>
                  </aside>
                )}
                {narrative.source_references.length > 0 && (
                  <details className="source-references">
                    <summary>Reference passages</summary>
                    <ul>
                      {narrative.source_references.map((reference, index) => (
                        <li key={`${reference.reference_id ?? reference.source_document}-${index}`}>
                          {reference.source_document}
                          {reference.act && ` · ${reference.act.replace('_', ' ')}`}
                          {reference.scene && `, ${reference.scene.replace('_', ' ')}`}
                          {reference.page_number && ` · page ${reference.page_number}`}
                        </li>
                      ))}
                    </ul>
                  </details>
                )}
              </>
            ) : (
              <p className="story-text__narration">{scene.opening_narration}</p>
            )}
            {busy && (
              <p className="writing-status" role="status" aria-live="polite">
                {retryBusy ? 'The narrator is returning to the page…' : 'The ink is still drying…'}
              </p>
            )}
          </article>

          <div className="story-state-grid">
            <CharacterStatusPanel game={game} characters={characters} />
            <StoryTimeline game={game} scene={scene} />
          </div>

          {generationError && (
            <div className="gameplay-error" role="alert">
              <p>{generationError}</p>
              <ActionButton onClick={() => void requestNarrativeRetry()} disabled={busy}>
                {retryBusy ? 'Retrying narration…' : 'Retry narration'}
              </ActionButton>
            </div>
          )}

          {requestError && (
            <div className="gameplay-error" role="alert">
              <p>{requestError}</p>
              {uncertainRequest && (
                <ActionButton onClick={() => void repeatUncertainTurn()} disabled={busy}>
                  Check the same turn safely
                </ActionButton>
              )}
              {!uncertainRequest && (requestError.includes('choice') || requestError.includes('changed')) && (
                <ActionButton variant="secondary" onClick={() => void refreshChoices()} disabled={busy}>
                  Refresh saved scene
                </ActionButton>
              )}
            </div>
          )}

          {sceneError && (
            <div className="gameplay-error" role="status">
              <p>{sceneError}</p>
              <button className="retry-link" type="button" onClick={() => void refreshScene()} disabled={busy}>Refresh scene details</button>
            </div>
          )}

          {initialLoadError && (
            <div className="gameplay-error" role="alert">
              <p>{initialLoadError}</p>
              <ActionButton variant="secondary" onClick={() => void refreshChoices()} disabled={busy}>
                Reload this saved scene
              </ActionButton>
            </div>
          )}

          <section className="choice-panel" aria-labelledby="choices-heading">
            <div className="choice-panel__heading">
              <span className="chapter-rule" aria-hidden="true" />
              <h2 id="choices-heading">What will you do?</h2>
              <span className="chapter-rule" aria-hidden="true" />
            </div>
            {loadingChoices ? (
              <p className="choice-loading" role="status">The possible paths are being gathered…</p>
            ) : availableChoices.length > 0 ? (
              <div className="choice-list">
                {availableChoices.map(({ choice }, index) => (
                  <BranchChoice
                    choice={choice}
                    index={index}
                    characters={characters}
                    key={choice.choice_id}
                    disabled={busy || Boolean(uncertainRequest) || Boolean(generationError) || Boolean(initialLoadError)}
                    onChoose={choose}
                  />
                ))}
              </div>
            ) : (
              <p className="choice-loading">{game.status === 'completed' ? 'This chronicle has reached its ending.' : 'There are no available choices in this scene.'}</p>
            )}
          </section>

          <footer className="storybook__footer">
            <span>Turn {game.turn_number}</span>
            <span aria-hidden="true">◆</span>
            <span>Revision {game.revision}</span>
          <ActionButton variant="secondary" onClick={onBack} disabled={busy || Boolean(uncertainRequest)}>Return to chronicle cover</ActionButton>
          </footer>
        </div>
      </section>
    </main>
  );
}
