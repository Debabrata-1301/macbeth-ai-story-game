import type { GameView } from '../api/types';
import { ActionButton } from './ActionButton';
import { campaignObjectives, campaignTitles } from '../content/characterIntroductions';

interface GameIntroductionProps {
  session: GameView;
  storageWarning: boolean;
  onEnter: () => void;
  onBack: () => void;
}

export function GameIntroduction({ session, storageWarning, onEnter, onBack }: GameIntroductionProps) {
  return (
    <main className="page-shell introduction-shell">
      <header className="masthead" aria-label="Macbeth Chronicle">
        <span className="masthead__rule" aria-hidden="true" />
        <p className="masthead__eyebrow">The first leaf</p>
        <span className="masthead__rule" aria-hidden="true" />
      </header>
      <section className="introduction-book" aria-labelledby="introduction-title">
        <div className="ornament" aria-hidden="true"><span>✦</span></div>
        <p className="chapter-label">{campaignTitles[session.game.campaign_id] ?? 'The Macbeth Chronicle'} · {session.scene.location}</p>
        <h1 id="introduction-title">{session.scene.title}</h1>
        <p className="introduction-character">As told by {session.game.selected_character_id.replaceAll('_', ' ')}</p>
        <p className="campaign-objective"><strong>Campaign objective</strong> {campaignObjectives[session.game.campaign_id]}</p>
        <blockquote className="opening-words">{session.scene.opening_narration}</blockquote>
        <p className="introduction-placeholder">Your chronicle is saved. Enter the story when you are ready.</p>
        {storageWarning && (
          <p className="message message--error" role="status">
            The game was created, but this browser could not remember its ID for Continue.
          </p>
        )}
        <div className="introduction-actions">
          <ActionButton onClick={onEnter}>Enter the story</ActionButton>
          <ActionButton variant="secondary" onClick={onBack}>Return to game library</ActionButton>
        </div>
      </section>
    </main>
  );
}
