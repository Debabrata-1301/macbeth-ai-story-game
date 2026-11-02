import type { Page, Request as BrowserRequest, TestInfo } from '@playwright/test';
import type { GameplayTurnResponse } from '../src/api/types';
import {
  characters, gameId, initialChoices, makeSummary, makeTurnResponse, makeView,
  nextChoices,
} from './fixtures';

export interface MockApiOptions {
  generationFailure?: boolean;
  characterRequestFailure?: boolean;
  turnDelayMs?: number;
}

export async function installMockApi(page: Page, options: MockApiOptions = {}) {
  const requests: Array<{ method: string; path: string; body?: unknown }> = [];
  let selectedCharacter = 'macbeth';
  let updated = false;
  let deleted = false;
  let generationFailed = Boolean(options.generationFailure);

  await page.route('**/api/v1/**', async (route) => {
    const request: BrowserRequest = route.request();
    const url = new URL(request.url());
    const method = request.method();
    const path = url.pathname;
    let body: unknown;
    try { body = request.postDataJSON(); } catch { body = undefined; }
    requests.push({ method, path, body });

    const reply = (data: unknown, status = 200) => route.fulfill({
      status,
      contentType: 'application/json',
      body: JSON.stringify(data),
    });

    if (path === '/api/v1/health') return reply({ service: 'Macbeth AI Story Game', status: 'ok' });
    if (path === '/api/v1/characters' && method === 'GET') {
      if (options.characterRequestFailure) return reply({ detail: 'Character service is unavailable.' }, 503);
      return reply(characters);
    }
    if (path === '/api/v1/games' && method === 'POST') {
      selectedCharacter = (body as { character_id: string }).character_id;
      deleted = false;
      return reply(makeView(false, selectedCharacter), 201);
    }
    if (path === '/api/v1/games' && method === 'GET') {
      return reply(deleted ? [] : [makeSummary(updated, selectedCharacter)]);
    }
    const gamePath = `/api/v1/games/${gameId}`;
    if (path === gamePath && method === 'GET') {
      if (deleted) return reply({ detail: 'Game was not found.' }, 404);
      return reply(makeView(updated, selectedCharacter));
    }
    if (path === gamePath && method === 'DELETE') {
      deleted = true;
      return route.fulfill({ status: 204 });
    }
    if (path === `${gamePath}/choices` && method === 'GET') {
      if (deleted) return reply({ detail: 'Game was not found.' }, 404);
      return reply(updated ? nextChoices : initialChoices);
    }
    if (path === `${gamePath}/turns` && method === 'POST') {
      if (options.turnDelayMs) await new Promise((resolve) => setTimeout(resolve, options.turnDelayMs));
      updated = true;
      const failed = generationFailed;
      generationFailed = false;
      return reply(makeTurnResponse(failed), failed ? 503 : 200);
    }
    if (path === `${gamePath}/narrative` && method === 'POST') {
      const result: GameplayTurnResponse = { ...makeTurnResponse(false), transition_applied: false };
      return reply(result);
    }
    return reply({ detail: `No mocked route for ${method} ${path}` }, 404);
  });

  return { requests };
}

export async function captureScreenshot(page: Page, testInfo: TestInfo, name: string) {
  const path = testInfo.outputPath(`${name}.png`);
  await page.screenshot({ path, fullPage: true });
  await testInfo.attach(name, { path, contentType: 'image/png' });
}

export async function startMockGame(page: Page, characterName = 'Macbeth') {
  await page.goto('/');
  await page.getByRole('button', { name: 'Begin a New Chronicle' }).click();
  const card = page.getByRole('article').filter({
    has: page.getByRole('heading', { name: characterName, exact: true }),
  });
  await card.getByRole('button', { name: 'Choose this campaign' }).click();
  await page.getByRole('button', { name: 'Confirm and begin' }).click();
  await page.getByRole('heading', { name: 'The Heath Before Battle' }).waitFor();
}
