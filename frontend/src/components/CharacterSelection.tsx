import type { CharacterDefinition } from '../api/types';
import { campaignConflicts, campaignTitles, characterIntroductions } from '../content/characterIntroductions';
import { ActionButton } from './ActionButton';

interface CharacterSelectionProps {
  characters: CharacterDefinition[];
  selectedId: string | null;
  busy: boolean;
  loading: boolean;
  charactersError: string | null;
  submitError: string | null;
  onSelect: (characterId: string) => void;
  onConfirm: () => void;
  onBack: () => void;
  backLabel?: string;
  onRetry: () => void;
}

function PortraitPlaceholder({ character }: { character: CharacterDefinition }) {
  return (
    <div
      className={`portrait portrait--${character.character_id}`}
      role="img"
      aria-label={`Decorative portrait placeholder for ${character.name}`}
    >
      <span className="portrait__initial" aria-hidden="true">{character.name.slice(0, 1)}</span>
      <span className="portrait__flourish" aria-hidden="true">❧</span>
    </div>
  );
}

export function CharacterSelection({
  characters,
  selectedId,
  busy,
  loading,
  charactersError,
  submitError,
  onSelect,
  onConfirm,
  onBack,
  backLabel = 'Back to welcome',
  onRetry,
}: CharacterSelectionProps) {
  return (
    <main className="page-shell selection-shell">
      <header className="masthead" aria-label="Macbeth Chronicle">
        <span className="masthead__rule" aria-hidden="true" />
        <p className="masthead__eyebrow">Choose your campaign</p>
        <span className="masthead__rule" aria-hidden="true" />
      </header>

      <section className="selection-book" aria-labelledby="selection-title">
        <div className="selection-heading">
          <p className="chapter-label">Four lives, one Scotland</p>
          <h1 id="selection-title">Choose your campaign</h1>
          <p className="selection-intro">Each chronicle follows its protagonist’s decisions, knowledge, and consequences.</p>
        </div>

        {loading ? (
          <p className="selection-status" role="status">Gathering the company…</p>
        ) : charactersError ? (
          <div className="message message--error" role="alert">
            <p>{charactersError}</p>
            <button className="retry-link" type="button" onClick={onRetry}>Try again</button>
          </div>
        ) : (
          <div className="character-grid" role="group" aria-label="Available campaigns">
            {characters.map((character) => {
              const selected = character.character_id === selectedId;
              return (
                <article
                  key={character.character_id}
                  className={`character-card${selected ? ' character-card--selected' : ''}`}
                >
                  <PortraitPlaceholder character={character} />
                  <div className="character-card__copy">
                    <p className="character-card__role">{character.role}</p>
                    <h2>{character.name}</h2>
                    <p className="campaign-title">{campaignTitles[character.character_id]}</p>
                    <p className="character-card__intro">{characterIntroductions[character.character_id] ?? character.background}</p>
                    <p className="campaign-conflict"><strong>Central conflict</strong> {campaignConflicts[character.character_id]}</p>
                    <dl className="character-card__details">
                      <div>
                        <dt>Nature</dt>
                        <dd>{character.personality.join(' · ')}</dd>
                      </div>
                      <div>
                        <dt>Desires</dt>
                        <dd>{character.motivations.join(' · ')}</dd>
                      </div>
                    </dl>
                    <button
                      className="character-select"
                      type="button"
                      aria-pressed={selected}
                      onClick={() => onSelect(character.character_id)}
                    >
                      {selected ? 'Chosen' : 'Choose this campaign'}
                    </button>
                  </div>
                </article>
              );
            })}
          </div>
        )}

        <div className="selection-actions">
          <ActionButton variant="secondary" onClick={onBack} disabled={busy}>
            {backLabel}
          </ActionButton>
          {submitError && <div className="message message--error" role="alert">{submitError}</div>}
          <ActionButton onClick={onConfirm} disabled={!selectedId || busy || loading || Boolean(charactersError)}>
            {busy ? 'Opening the book…' : 'Confirm and begin'}
          </ActionButton>
        </div>
      </section>
    </main>
  );
}
