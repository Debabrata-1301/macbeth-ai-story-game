const SAVED_GAME_KEY = 'macbeth.current-game-id';

export function getSavedGameId(): string | null {
  try {
    return window.localStorage.getItem(SAVED_GAME_KEY);
  } catch {
    return null;
  }
}

export function rememberGameId(gameId: string): boolean {
  try {
    window.localStorage.setItem(SAVED_GAME_KEY, gameId);
    return true;
  } catch {
    return false;
  }
}

export function forgetGameId(gameId: string): boolean {
  try {
    if (window.localStorage.getItem(SAVED_GAME_KEY) === gameId) {
      window.localStorage.removeItem(SAVED_GAME_KEY);
    }
    return true;
  } catch {
    return false;
  }
}
