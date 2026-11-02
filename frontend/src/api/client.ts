import type {
  CharacterDefinition,
  ChoiceAvailability,
  GameplayTurnRequest,
  GameplayTurnResponse,
  GameView,
  GameSummary,
  HealthResponse,
  StartGameRequest,
} from './types';

const apiBase = (import.meta.env.VITE_API_BASE_URL || '/api/v1').replace(/\/$/, '');

export class ApiError extends Error {
  constructor(message: string, readonly status?: number, readonly timedOut = false) {
    super(message);
    this.name = 'ApiError';
  }
}

async function request<T>(path: string, init?: RequestInit, timeoutMs = 15_000): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${apiBase}${path}`, {
      ...init,
      headers: {
        ...(init?.body ? { 'Content-Type': 'application/json' } : {}),
        ...init?.headers,
      },
      signal: AbortSignal.timeout(timeoutMs),
    });
  } catch (cause) {
    if (cause instanceof DOMException && cause.name === 'TimeoutError') {
      throw new ApiError('The local game service took too long to respond.', undefined, true);
    }
    throw new ApiError('The local game service could not be reached. Check that the backend is running.');
  }

  if (!response.ok) {
    let message = `The game service returned an error (${response.status}).`;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === 'string') message = body.detail;
    } catch {
      // Keep the useful status message when the server returned non-JSON content.
    }
    throw new ApiError(message, response.status);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export function getHealth(): Promise<HealthResponse> {
  return request<HealthResponse>('/health');
}

export function listCharacters(): Promise<CharacterDefinition[]> {
  return request<CharacterDefinition[]>('/characters');
}

export function startGame(body: StartGameRequest): Promise<GameView> {
  return request<GameView>('/games', { method: 'POST', body: JSON.stringify(body) });
}

export function loadGame(gameId: string): Promise<GameView> {
  return request<GameView>(`/games/${encodeURIComponent(gameId)}`);
}

export function listGames(): Promise<GameSummary[]> {
  return request<GameSummary[]>('/games');
}

export async function deleteGame(gameId: string): Promise<void> {
  await request<void>(`/games/${encodeURIComponent(gameId)}`, { method: 'DELETE' });
}

export function getGameChoices(gameId: string): Promise<ChoiceAvailability[]> {
  return request<ChoiceAvailability[]>(`/games/${encodeURIComponent(gameId)}/choices`);
}

async function gameplayRequest(path: string, init?: RequestInit): Promise<GameplayTurnResponse> {
  let response: Response;
  try {
    response = await fetch(`${apiBase}${path}`, {
      ...init,
      headers: {
        ...(init?.body ? { 'Content-Type': 'application/json' } : {}),
        ...init?.headers,
      },
      signal: AbortSignal.timeout(300_000),
    });
  } catch (cause) {
    if (cause instanceof DOMException && cause.name === 'TimeoutError') {
      throw new ApiError(
        'The turn request timed out. Its result is uncertain; use the safe retry to check the same request.',
        undefined,
        true,
      );
    }
    throw new ApiError(
      'The turn request lost its connection. Its result is uncertain; use the safe retry to check the same request.',
    );
  }

  let body: unknown;
  try {
    body = await response.json();
  } catch {
    body = null;
  }

  if (response.ok || (response.status === 503 && isTurnResponse(body))) {
    return body as GameplayTurnResponse;
  }

  const detail = typeof body === 'object' && body !== null && 'detail' in body
    ? (body as { detail?: unknown }).detail
    : null;
  throw new ApiError(
    typeof detail === 'string' ? detail : `The game service returned an error (${response.status}).`,
    response.status,
  );
}

function isTurnResponse(value: unknown): value is GameplayTurnResponse {
  return typeof value === 'object' && value !== null
    && 'game' in value && 'available_choices' in value && 'transition_applied' in value;
}

export function submitGameplayTurn(gameId: string, body: GameplayTurnRequest): Promise<GameplayTurnResponse> {
  return gameplayRequest(`/games/${encodeURIComponent(gameId)}/turns`, {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

export function retryNarrative(gameId: string): Promise<GameplayTurnResponse> {
  return gameplayRequest(`/games/${encodeURIComponent(gameId)}/narrative`, { method: 'POST' });
}
