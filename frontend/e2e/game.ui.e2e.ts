import { expect, test } from '@playwright/test';
import { captureScreenshot, installMockApi, startMockGame } from './mock-api';
import { gameId } from './fixtures';

test('welcome screen has local-service status and keyboard-visible actions', async ({ page }, testInfo) => {
  await installMockApi(page);
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'MACBETH' })).toBeVisible();
  await expect(page.getByText('A TALE OF AMBITION, BLOOD AND FATE')).toBeVisible();
  await expect(page.getByRole('status').getByText('Local backend connected')).toBeVisible();
  await page.keyboard.press('Tab');
  await expect(page.getByRole('button', { name: 'Begin a New Chronicle' })).toBeFocused();
  const focusWidth = await page.getByRole('button', { name: 'Begin a New Chronicle' }).evaluate(
    (button) => getComputedStyle(button).outlineWidth,
  );
  expect(focusWidth).not.toBe('0px');
  await captureScreenshot(page, testInfo, 'welcome-desktop');
});

test('backend unavailable is explained without pretending game actions work', async ({ page }) => {
  await installMockApi(page);
  await page.route('**/api/v1/health', (route) => route.abort());
  await page.goto('/');
  await expect(page.getByText('Backend unavailable')).toBeVisible();
  await expect(page.getByText('Start the local FastAPI service to open or continue a chronicle.')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Begin a New Chronicle' })).toBeDisabled();
});

test('all four characters are selectable one at a time and confirmation starts the selected character', async ({ page }, testInfo) => {
  const api = await installMockApi(page);
  await page.goto('/');
  await page.getByRole('button', { name: 'Begin a New Chronicle' }).click();
  await expect(page.getByRole('heading', { name: 'Choose your campaign' })).toBeVisible();
  await expect(page.locator('.character-card')).toHaveCount(4);
  await captureScreenshot(page, testInfo, 'character-selection-desktop');

  for (const name of ['Macbeth', 'Lady Macbeth', 'Banquo', 'Macduff']) {
    const card = page.getByRole('article').filter({ has: page.getByRole('heading', { name, exact: true }) });
    await card.getByRole('button', { name: /Choose this campaign|Chosen/ }).click();
    await expect(page.locator('button[aria-pressed="true"]')).toHaveCount(1);
    await expect(card.getByRole('button', { name: 'Chosen' })).toHaveAttribute('aria-pressed', 'true');
  }

  await page.getByRole('button', { name: 'Confirm and begin' }).click();
  await expect(page.getByRole('heading', { name: 'A Thane at Home' })).toBeVisible();
  const creation = api.requests.find((request) => request.method === 'POST' && request.path === '/api/v1/games');
  expect(creation?.body).toEqual({ character_id: 'macduff', story_mode: 'hybrid' });
  await captureScreenshot(page, testInfo, 'game-introduction-desktop');
});

test('gameplay accepts an engine choice once, updates the scene, and visibly confirms persistence', async ({ page }, testInfo) => {
  const api = await installMockApi(page, { turnDelayMs: 500 });
  await startMockGame(page);
  await page.getByRole('button', { name: 'Enter the story' }).click();
  await expect(page.getByRole('heading', { name: 'The Heath Before Battle' })).toBeVisible();
  await expect(page.getByText('The wind scours the heath as I ride beneath a bruised sky.')).toBeVisible();
  await expect(page.getByRole('button', { name: /Pause and study the strange lights/ })).toBeVisible();
  await captureScreenshot(page, testInfo, 'gameplay-desktop');

  const choice = page.getByRole('button', { name: /Path 1: Ride on toward Forres with Banquo/ });
  await choice.click();
  await expect(choice).toBeDisabled();
  await choice.evaluate((button) => button.dispatchEvent(new MouseEvent('click', { bubbles: true })));
  await expect(page.getByRole('heading', { name: 'Fair Is Foul' })).toBeVisible();
  await expect(page.getByText('Decision accepted. Your updated story is saved on this machine.')).toBeVisible();
  await expect(page.getByText('I ride beneath a sky bruised by storm, and the sisters’ words follow me.')).toBeVisible();
  await expect(page.getByRole('button', { name: /Tell Banquo you will take the prophecy seriously/ })).toBeVisible();
  expect(api.requests.filter((request) => request.method === 'POST' && request.path.endsWith('/turns'))).toHaveLength(1);
});

test('generation failure keeps the accepted turn and retry regenerates without another choice request', async ({ page }) => {
  const api = await installMockApi(page, { generationFailure: true });
  await startMockGame(page);
  await page.getByRole('button', { name: 'Enter the story' }).click();
  await page.getByRole('button', { name: /Path 1: Ride on toward Forres with Banquo/ }).click();
  await expect(page.getByRole('alert')).toContainText('Your choice is saved');
  await expect(page.getByRole('heading', { name: 'Fair Is Foul' })).toBeVisible();
  await page.getByRole('button', { name: 'Retry narration' }).click();
  await expect(page.getByText('I ride beneath a sky bruised by storm, and the sisters’ words follow me.')).toBeVisible();
  expect(api.requests.filter((request) => request.method === 'POST' && request.path.endsWith('/turns'))).toHaveLength(1);
  expect(api.requests.filter((request) => request.method === 'POST' && request.path.endsWith('/narrative'))).toHaveLength(1);
});

test('library lists, resumes persisted history, and confirms deletion', async ({ page }, testInfo) => {
  await installMockApi(page);
  await startMockGame(page);
  await page.getByRole('button', { name: 'Enter the story' }).click();
  await page.getByRole('button', { name: /Path 1: Ride on toward Forres with Banquo/ }).click();
  await expect(page.getByText('Decision accepted. Your updated story is saved on this machine.')).toBeVisible();
  await page.getByRole('button', { name: 'Return to chronicle cover' }).click();
  await page.getByRole('button', { name: 'Return to game library' }).click();
  await expect(page.getByRole('heading', { name: 'Your Chronicles' })).toBeVisible();
  const entry = page.locator('.library-entry');
  await expect(entry).toContainText('Macbeth');
  await expect(entry).toContainText('Fair Is Foul');
  await expect(entry).toContainText(gameId);
  await captureScreenshot(page, testInfo, 'game-library-desktop');

  await entry.getByRole('button', { name: 'Continue' }).click();
  await expect(page.getByRole('heading', { name: 'Fair Is Foul' })).toBeVisible();
  await page.getByRole('button', { name: 'Enter the story' }).click();
  await expect(page.getByRole('heading', { name: 'Story timeline' })).toBeVisible();
  await expect(page.getByText('Decision taken')).toBeVisible();
  await page.getByRole('button', { name: 'Return to chronicle cover' }).click();
  await page.getByRole('button', { name: 'Return to game library' }).click();
  await page.locator('.library-entry').getByRole('button', { name: 'Delete' }).click();
  await expect(page.getByRole('group', { name: 'Confirm deletion of Macbeth chronicle' })).toBeVisible();
  await page.getByRole('button', { name: 'Delete permanently' }).click();
  await expect(page.getByText('No saved chronicles yet.')).toBeVisible();
});

test('invalid saved identifier and character API failure show recoverable messages', async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('macbeth.current-game-id', 'deleted-game'));
  await installMockApi(page);
  await page.goto('/');
  await page.getByRole('button', { name: 'Continue Last Chronicle' }).click();
  await expect(page.getByRole('alert')).toContainText('That saved chronicle was removed');
  await expect(page.getByRole('button', { name: 'Open Game Library' })).toBeEnabled();
  await expect.poll(() => page.evaluate(() => localStorage.getItem('macbeth.current-game-id'))).toBeNull();

  await page.reload();
  await page.route('**/api/v1/characters', (route) => route.fulfill({
    status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'Character service is unavailable.' }),
  }));
  await page.getByRole('button', { name: 'Begin a New Chronicle' }).click();
  await expect(page.getByRole('alert')).toContainText('Character service is unavailable');
});

test('reduced motion preference is respected by the narration loading effect', async ({ page }) => {
  await installMockApi(page, { turnDelayMs: 700 });
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await startMockGame(page);
  await page.getByRole('button', { name: 'Enter the story' }).click();
  await page.getByRole('button', { name: /Path 1: Ride on toward Forres with Banquo/ }).click();
  const loading = page.getByRole('status').filter({ hasText: 'ink is still drying' });
  await expect(loading).toBeVisible();
  expect(await loading.evaluate((element) => getComputedStyle(element).animationDuration)).toBe('1e-05s');
});

test('responsive layouts remain usable without horizontal overflow and produce screen captures', async ({ page }, testInfo) => {
  const viewports = [
    { name: 'desktop', width: 1440, height: 900 },
    { name: 'tablet', width: 768, height: 1024 },
    { name: 'mobile', width: 390, height: 844 },
  ];

  for (const viewport of viewports) {
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    await installMockApi(page);
    await page.goto('/');
    await expect(page.getByRole('heading', { name: 'MACBETH' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Begin a New Chronicle' })).toBeVisible();
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await captureScreenshot(page, testInfo, `welcome-${viewport.name}-${viewport.width}x${viewport.height}`);

    await page.getByRole('button', { name: 'Begin a New Chronicle' }).click();
    await expect(page.getByRole('heading', { name: 'Choose your campaign' })).toBeVisible();
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await captureScreenshot(page, testInfo, `selection-${viewport.name}-${viewport.width}x${viewport.height}`);

    await page.getByRole('article').filter({ has: page.getByRole('heading', { name: 'Macbeth', exact: true }) })
      .getByRole('button', { name: 'Choose this campaign' }).click();
    await page.getByRole('button', { name: 'Confirm and begin' }).click();
    await expect(page.getByRole('heading', { name: 'The Heath Before Battle' })).toBeVisible();
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await captureScreenshot(page, testInfo, `introduction-${viewport.name}-${viewport.width}x${viewport.height}`);

    await page.getByRole('button', { name: 'Enter the story' }).click();
    await expect(page.getByRole('button', { name: /Path 1:/ })).toBeVisible();
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await captureScreenshot(page, testInfo, `gameplay-${viewport.name}-${viewport.width}x${viewport.height}`);

    await page.getByRole('button', { name: 'Return to chronicle cover' }).click();
    await page.getByRole('button', { name: 'Return to game library' }).click();
    await expect(page.getByRole('heading', { name: 'Your Chronicles' })).toBeVisible();
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await captureScreenshot(page, testInfo, `library-${viewport.name}-${viewport.width}x${viewport.height}`);
  }
});
