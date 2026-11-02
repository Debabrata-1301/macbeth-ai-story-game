import type { CharacterDefinition, ChoiceDefinition } from '../api/types';

interface BranchChoiceProps {
  choice: ChoiceDefinition;
  index: number;
  characters: CharacterDefinition[];
  disabled: boolean;
  onChoose: (choiceId: string) => void;
}

function nameFor(characterId: string, characters: CharacterDefinition[]): string {
  return characters.find((character) => character.character_id === characterId)?.name
    ?? characterId.replaceAll('_', ' ');
}

function immediateEffects(choice: ChoiceDefinition, characters: CharacterDefinition[]): string[] {
  const effects: string[] = [];
  for (const [characterId, changes] of Object.entries(choice.character_changes)) {
    for (const [attribute, value] of Object.entries(changes)) {
      const formattedValue = String(value);
      effects.push(`${nameFor(characterId, characters)} · ${attribute.replaceAll('_', ' ')} → ${formattedValue}`);
    }
  }
  for (const change of choice.relationship_changes) {
    const name = nameFor(change.character_id, characters);
    if (change.trust !== 0) effects.push(`Trust with ${name} ${change.trust > 0 ? '+' : ''}${change.trust}`);
    if (change.hostility !== 0) effects.push(`Hostility with ${name} ${change.hostility > 0 ? '+' : ''}${change.hostility}`);
  }
  return effects;
}

export function BranchChoice({ choice, index, characters, disabled, onChoose }: BranchChoiceProps) {
  const effects = immediateEffects(choice, characters);

  return (
    <article className="choice-option">
      <button
        className="story-choice"
        type="button"
        aria-label={`Path ${index + 1}: ${choice.description}`}
        disabled={disabled}
        onClick={() => onChoose(choice.choice_id)}
      >
        <span className="story-choice__number" aria-hidden="true">{String(index + 1).padStart(2, '0')}</span>
        <span>{choice.description}</span>
        <span className="story-choice__arrow" aria-hidden="true">→</span>
      </button>
      {effects.length > 0 && (
        <aside className="choice-effects" aria-label="Immediate effects recorded by the game">
          <span>Immediate recorded effect</span>
          <ul>{effects.map((effect) => <li key={effect}>{effect}</li>)}</ul>
        </aside>
      )}
    </article>
  );
}
