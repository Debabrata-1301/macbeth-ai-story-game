import { expect, test } from '@playwright/test';

test('real local turn generates narration, persists, resumes, and deletes an isolated game', async ({ page }) => {
  test.setTimeout(180_000);
  await page.goto('/');
  await expect(page.getByText('Local backend connected')).toBeVisible({ timeout: 15_000 });
  const initialGames = await page.evaluate(async () => {
    const response = await fetch('/api/v1/games');
    return response.json() as Promise<unknown[]>;
  });
  expect(initialGames, 'the local browser API must reach the fresh isolated database').toEqual([]);

  await page.getByRole('button', { name: 'Begin a New Chronicle' }).click();
  await page.getByRole('article').filter({ has: page.getByRole('heading', { name: 'Macbeth', exact: true }) })
    .getByRole('button', { name: 'Choose this campaign' }).click();
  await page.getByRole('button', { name: 'Confirm and begin' }).click();
  await expect(page.getByRole('heading', { name: 'The Heath Before Battle' })).toBeVisible();
  await page.getByRole('button', { name: 'Enter the story' }).click();
  await expect(page.getByRole('button', { name: /Path 1:/ })).toBeVisible();

  let turnRequests = 0;
  page.on('request', (request) => {
    if (request.method() === 'POST' && request.url().endsWith('/turns')) turnRequests += 1;
  });
  const turnResponsePromise = page.waitForResponse((response) =>
    response.url().includes('/api/v1/games/') && response.url().endsWith('/turns'),
  );
  await page.getByRole('button', { name: /Path 1:/ }).click();
  const firstResponse = await turnResponsePromise;
  const firstTurn = await firstResponse.json() as {
    transition_applied: boolean;
    generation_error_code: string | null;
    narrative: { narration: string; dialogue: unknown[] } | null;
    game: { game_id: string; revision: number; turn_number: number; event_history: unknown[] };
    available_choices: unknown[];
  };
  console.log(`real turn response status=${firstResponse.status()} generation_error=${firstTurn.generation_error_code}`);
  expect(firstTurn.transition_applied).toBe(true);
  expect(firstTurn.game.revision).toBe(1);
  expect(firstTurn.game.event_history).toHaveLength(2);

  let narrativeTurn = firstTurn;
  if (firstResponse.status() === 503) {
    await expect(page.getByRole('alert')).toContainText('Your choice is saved');
    const retryResponsePromise = page.waitForResponse((response) =>
      response.url().includes('/api/v1/games/') && response.url().endsWith('/narrative'),
    );
    await page.getByRole('button', { name: 'Retry narration' }).click();
    const retryResponse = await retryResponsePromise;
    narrativeTurn = await retryResponse.json() as typeof firstTurn;
    console.log(`narrative retry response status=${retryResponse.status()} generation_error=${narrativeTurn.generation_error_code}`);
    expect(retryResponse.status(), JSON.stringify(narrativeTurn)).toBe(200);
    expect(narrativeTurn.transition_applied).toBe(false);
  } else {
    expect(firstResponse.status(), JSON.stringify(firstTurn)).toBe(200);
  }

  expect(narrativeTurn.generation_error_code).toBeNull();
  expect(narrativeTurn.narrative?.narration.trim().length).toBeGreaterThan(0);
  expect(narrativeTurn.game.revision).toBe(1);
  expect(narrativeTurn.game.turn_number).toBe(1);
  expect(narrativeTurn.game.event_history).toHaveLength(2);
  expect(narrativeTurn.available_choices.length).toBeGreaterThan(0);
  expect(turnRequests).toBe(1);

  await expect(page.getByRole('heading', { name: 'Fair Is Foul' })).toBeVisible();
  await expect(page.locator('.story-text__narration').first()).not.toBeEmpty();
  await expect(page.getByText('Decision accepted. Your updated story is saved on this machine.')).toBeVisible();
  await page.getByRole('button', { name: 'Return to chronicle cover' }).click();
  await page.getByRole('button', { name: 'Return to game library' }).click();
  const gameCard = page.locator('.library-entry').filter({ hasText: 'Fair Is Foul' });
  await expect(page.locator('.library-entry')).toHaveCount(1);
  await expect(gameCard).toContainText('Macbeth');
  await expect(gameCard).toContainText('Fair Is Foul');

  await gameCard.getByRole('button', { name: 'Continue' }).click();
  await expect(page.getByRole('heading', { name: 'Fair Is Foul' })).toBeVisible();
  await page.getByRole('button', { name: 'Enter the story' }).click();
  await expect(page.getByRole('heading', { name: 'Story timeline' })).toBeVisible();
  await expect(page.getByText('Decision taken')).toBeVisible();
  await expect(page.getByText('Revision 1')).toBeVisible();

  await page.getByRole('button', { name: 'Return to chronicle cover' }).click();
  await page.getByRole('button', { name: 'Return to game library' }).click();
  await page.locator('.library-entry').getByRole('button', { name: 'Delete' }).click();
  await page.getByRole('button', { name: 'Delete permanently' }).click();
  await expect(page.getByText('No saved chronicles yet.')).toBeVisible();
});
