import type { GameEvent, GameState, SceneDefinition } from '../api/types';

interface StoryTimelineProps {
  game: GameState;
  scene: SceneDefinition;
}

function eventHeading(event: GameEvent): string {
  switch (event.event_type) {
    case 'game_started': return 'Chronicle begun';
    case 'choice_made': return 'Decision taken';
    case 'scene_entered': return 'Scene entered';
    case 'character_state_changed': return 'Character state changed';
    case 'relationship_changed': return 'Relationship changed';
    case 'game_ended': return 'Chronicle ended';
  }
}

function SceneOrigin({ reference }: { reference: string | null }) {
  if (!reference) return <span className="timeline-origin timeline-origin--unknown">Source note unavailable</span>;
  if (reference.toLowerCase().includes('alternate-history')) {
    return <span className="timeline-origin timeline-origin--alternate">Alternate-history scene · {reference}</span>;
  }
  if (/alternate (dialogue|choices)|original game/i.test(reference)) {
    return <span className="timeline-origin timeline-origin--mixed">Shakespeare source with original game material · {reference}</span>;
  }
  if (/macbeth,\s*act/i.test(reference)) {
    return <span className="timeline-origin timeline-origin--source">Shakespeare reference · {reference}</span>;
  }
  return <span className="timeline-origin">Adapted framing · {reference}</span>;
}

export function StoryTimeline({ game, scene }: StoryTimelineProps) {
  const events = game.event_history;
  return (
    <section className="timeline-panel" aria-labelledby="timeline-heading">
      <div className="timeline-panel__heading">
        <span className="chapter-rule" aria-hidden="true" />
        <div>
          <p>The road taken</p>
          <h2 id="timeline-heading">Story timeline</h2>
        </div>
        <span className="chapter-rule" aria-hidden="true" />
      </div>
      <p className="timeline-panel__note">One saved path, shaped by the decisions recorded in this chronicle.</p>
      <ol className="timeline-list">
        {events.map((event) => {
          const choiceId = event.metadata.choice_id;
          const destination = event.metadata.destination_scene_id;
          return (
            <li className={`timeline-event timeline-event--${event.event_type}`} key={event.event_id}>
              <span className="timeline-event__seal" aria-hidden="true" />
              <div>
                <p className="timeline-event__type">{eventHeading(event)}</p>
                <p className="timeline-event__scene">{event.scene_id}</p>
                {typeof choiceId === 'string' && <code className="timeline-event__choice">{choiceId}</code>}
                {typeof destination === 'string' && (
                  <p className="timeline-event__transition">{event.scene_id} <span aria-label="to">→</span> {destination}</p>
                )}
              </div>
            </li>
          );
        })}
        <li className="timeline-event timeline-event--current" aria-current="step">
          <span className="timeline-event__seal" aria-hidden="true" />
          <div>
            <p className="timeline-event__type">Current story position</p>
            <p className="timeline-event__scene">{scene.title} · {scene.scene_id}</p>
            <SceneOrigin reference={scene.canonical_reference} />
          </div>
        </li>
      </ol>
      <p className="timeline-provenance-note">Past event records contain scene and choice IDs; source labels are available for the current scene only.</p>
    </section>
  );
}
