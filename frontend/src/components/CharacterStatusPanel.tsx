import type { CharacterDefinition, GameState } from '../api/types';

interface CharacterStatusPanelProps {
  game: GameState;
  characters: CharacterDefinition[];
}

function characterName(characterId: string, characters: CharacterDefinition[]): string {
  return characters.find((character) => character.character_id === characterId)?.name
    ?? characterId.replaceAll('_', ' ');
}

export function CharacterStatusPanel({ game, characters }: CharacterStatusPanelProps) {
  const selected = game.character_states[game.selected_character_id];
  if (!selected) {
    return (
      <aside className="status-panel" aria-labelledby="status-heading">
        <h2 id="status-heading">The player’s standing</h2>
        <p className="status-panel__empty">No character state is recorded for this save.</p>
      </aside>
    );
  }
  const uncertainKnowledge = selected.uncertain_knowledge ?? [];

  const attributes = [
    { label: 'Ambition', value: selected.ambition },
    { label: 'Morality', value: selected.morality },
    { label: 'Suspicion', value: selected.suspicion },
    { label: 'Guilt', value: selected.guilt },
    ...(selected.fear !== undefined ? [{ label: 'Fear', value: selected.fear }] : []),
    ...(selected.stress !== undefined ? [{ label: 'Stress', value: selected.stress }] : []),
    ...(selected.hope !== undefined ? [{ label: 'Hope', value: selected.hope }] : []),
    ...(selected.confidence !== undefined ? [{ label: 'Confidence', value: selected.confidence }] : []),
    ...(game.campaign_id === 'lady_macbeth' ? [
      { label: 'Emotional stability', value: selected.emotional_stability },
      { label: 'Influence', value: selected.influence },
      { label: 'Isolation', value: selected.isolation },
    ] : game.campaign_id === 'banquo' || game.campaign_id === 'macduff'
      ? [{ label: 'Resolve', value: selected.resolve }] : []),
  ];
  const relationships = game.relationships.filter((relationship) =>
    relationship.character_a === selected.character_id || relationship.character_b === selected.character_id);

  return (
    <aside className="status-panel" aria-labelledby="status-heading">
      <div className="status-panel__heading">
        <span className="status-sprig" aria-hidden="true">❧</span>
        <h2 id="status-heading">The player’s standing</h2>
        <span className="status-sprig" aria-hidden="true">❧</span>
      </div>
      <p className="status-panel__life">{selected.alive ? 'Living' : 'Dead'}</p>
      <div className="status-meters">
        {attributes.map(({ label, value }) => (
          <label className="status-meter" key={label}>
            <span><span>{label}</span><span>{value}</span></span>
            <meter min="0" max="100" value={value} aria-label={label}>{value}</meter>
          </label>
        ))}
      </div>
      <details className="status-facts character-journal">
        <summary>Character journal</summary>
        <section><h3>What {characterName(selected.character_id, characters)} knows</h3>
          {selected.known_facts.length ? <ul>{[...selected.known_facts].sort().map((fact) => <li key={fact}>{fact.replaceAll('_', ' ')}</li>)}</ul> : <p>No confirmed facts recorded.</p>}
        </section>
        <section><h3>Suspicions and rumours</h3>
          {uncertainKnowledge.length ? <ul>{uncertainKnowledge.map((item) => <li key={item.source_event_id + item.content}><strong>{item.category}{item.confirmed_event_id ? ' · later confirmed' : ''}</strong> · {item.content}</li>)}</ul> : <p>None recorded.</p>}
        </section>
        <section><h3>Personal memories</h3>
          {(game.memories ?? []).filter((item) => item.character_id === selected.character_id && item.campaign_id === game.campaign_id).length ? <ul>{(game.memories ?? []).filter((item) => item.character_id === selected.character_id && item.campaign_id === game.campaign_id).slice(-12).reverse().map((item) => <li key={item.memory_id}><strong>{item.category.replaceAll('_', ' ')}</strong> · {item.summary}</li>)}</ul> : <p>No defining moments recorded yet.</p>}
        </section>
        <section><h3>Promises and secrets</h3>
          {(game.commitments ?? []).filter((item) => item.status === 'active' && (item.visibility === 'public' || item.owner_id === selected.character_id || (item.visibility === 'participants' && (item.participant_ids.includes(selected.character_id) || item.audience_ids.includes(selected.character_id))))).length ? <ul>{(game.commitments ?? []).filter((item) => item.status === 'active' && (item.visibility === 'public' || item.owner_id === selected.character_id || (item.visibility === 'participants' && (item.participant_ids.includes(selected.character_id) || item.audience_ids.includes(selected.character_id))))).map((item) => <li key={item.commitment_id}><strong>{item.kind}</strong> · {item.summary}</li>)}</ul> : <p>None active.</p>}
        </section>
      </details>
      {relationships.length > 0 && (
        <div className="relationship-list" aria-label="Recorded relationships">
          <h3>Recorded ties</h3>
          {relationships.map((relationship) => {
            const otherId = relationship.character_a === selected.character_id
              ? relationship.character_b : relationship.character_a;
            return (
              <div className="relationship-row" key={`${relationship.character_a}-${relationship.character_b}`}>
                <strong>{characterName(otherId, characters)}</strong>
                <span>{relationship.character_a === selected.character_id ? 'You → ' : 'Toward you ← '}{characterName(otherId, characters)}</span>
                <span>Trust {relationship.trust > 0 ? '+' : ''}{relationship.trust}</span>
                <span>Hostility {relationship.hostility}</span>
                <span>Loyalty {relationship.loyalty ?? 0} · Affection {relationship.affection ?? 0} · Respect {relationship.respect ?? 0}</span>
              </div>
            );
          })}
        </div>
      )}
    </aside>
  );
}
