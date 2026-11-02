import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import type { ComponentProps } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { CharacterDefinition } from '../api/types';
import { CharacterSelection } from './CharacterSelection';

const characters: CharacterDefinition[] = [
  { character_id: 'macbeth', name: 'Macbeth', role: 'Thane of Glamis', personality: ['brave', 'ambitious'], motivations: ['honor', 'power'], background: 'A celebrated Scottish thane.' },
  { character_id: 'lady_macbeth', name: 'Lady Macbeth', role: 'Noblewoman of Inverness', personality: ['resolute', 'perceptive'], motivations: ['influence', 'security'], background: 'Macbeth’s wife.' },
  { character_id: 'banquo', name: 'Banquo', role: 'Scottish general', personality: ['cautious', 'loyal'], motivations: ['honor', 'truth'], background: 'A fellow general.' },
  { character_id: 'macduff', name: 'Macduff', role: 'Thane of Fife', personality: ['dutiful', 'watchful'], motivations: ['justice', 'Scotland’s safety'], background: 'A Scottish nobleman.' },
];

afterEach(cleanup);

function renderSelection(overrides: Partial<ComponentProps<typeof CharacterSelection>> = {}) {
  const props = {
    characters,
    selectedId: null,
    busy: false,
    loading: false,
    charactersError: null,
    submitError: null,
    onSelect: vi.fn(),
    onConfirm: vi.fn(),
    onBack: vi.fn(),
    onRetry: vi.fn(),
    ...overrides,
  };
  render(<CharacterSelection {...props} />);
  return props;
}

describe('CharacterSelection', () => {
  it('renders all four backend characters and their profile details', () => {
    renderSelection();

    for (const character of characters) {
      expect(screen.getByRole('heading', { name: character.name })).toBeTruthy();
      expect(screen.getByText(character.role)).toBeTruthy();
      expect(screen.getByText(character.personality.join(' · '))).toBeTruthy();
      expect(screen.getByText(character.motivations.join(' · '))).toBeTruthy();
    }
    expect(screen.getByText('The Queen’s Conscience')).toBeTruthy();
    expect(screen.getAllByText('Central conflict')).toHaveLength(4);
    expect(screen.getByText(/prophecy makes his family a threat/)).toBeTruthy();
  });

  it('highlights exactly one selected character and enables confirmation', () => {
    const props = renderSelection({ selectedId: 'banquo' });
    const cards = screen.getByRole('group', { name: 'Available campaigns' });
    const banquoCard = screen.getByRole('heading', { name: 'Banquo' }).closest('article');
    const macduffCard = screen.getByRole('heading', { name: 'Macduff' }).closest('article');

    expect(within(cards).getAllByRole('button', { pressed: true })).toHaveLength(1);
    expect(within(banquoCard as HTMLElement).getByRole('button', { name: 'Chosen' }).getAttribute('aria-pressed')).toBe('true');
    fireEvent.click(within(macduffCard as HTMLElement).getByRole('button', { name: 'Choose this campaign' }));
    expect(props.onSelect).toHaveBeenCalledWith('macduff');
    expect(screen.getByRole('button', { name: 'Confirm and begin' }).hasAttribute('disabled')).toBe(false);
  });

  it('prevents confirmation before a character is selected', () => {
    renderSelection();
    expect(screen.getByRole('button', { name: 'Confirm and begin' }).hasAttribute('disabled')).toBe(true);
  });

  it('shows character loading failures with a retry action', () => {
    const props = renderSelection({ charactersError: 'Characters could not be loaded.' });
    expect(screen.getByRole('alert').textContent).toContain('Characters could not be loaded.');
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
    expect(props.onRetry).toHaveBeenCalledOnce();
  });
});
