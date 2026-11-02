import { spawnSync } from 'node:child_process';
import { existsSync, mkdtempSync, rmSync } from 'node:fs';
import { delimiter, isAbsolute, join, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createServer } from 'node:net';
import { tmpdir } from 'node:os';

const frontendDir = resolve(fileURLToPath(new URL('..', import.meta.url)));
const cli = resolve(frontendDir, 'node_modules', '@playwright', 'test', 'cli.js');
const args = process.argv.slice(2);
const localMode = args.includes('--local');
const playwrightArgs = args.filter((arg) => arg !== '--local');
const env = { ...process.env, ...(localMode ? { PLAYWRIGHT_MODE: 'local' } : {}) };
delete env.NO_COLOR;
delete env.FORCE_COLOR;

async function getFreePort() {
  const server = createServer();
  await new Promise((resolvePromise, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', resolvePromise);
  });
  const port = server.address().port;
  await new Promise((resolvePromise, reject) => server.close((error) => error ? reject(error) : resolvePromise()));
  return port;
}

function resolveBackendPython() {
  if (env.PLAYWRIGHT_PYTHON) return { command: env.PLAYWRIGHT_PYTHON, args: [] };

  const projectRoot = resolve(frontendDir, '..');
  const candidates = [];
  const add = (command, args = []) => {
    if (command) candidates.push({ command, args });
  };
  const venv = process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python';
  if (env.VIRTUAL_ENV) add(join(env.VIRTUAL_ENV, venv));
  add(join(projectRoot, '.venv', venv));
  if (env.PYTHON) add(env.PYTHON);

  // A pytest.exe on PATH identifies the Python installation used by the project's test runner.
  if (process.platform === 'win32') {
    for (const entry of (env.PATH || '').split(delimiter)) {
      const scriptsDir = entry.trim().replace(/^"|"$/g, '');
      const pytestExe = join(scriptsDir, 'pytest.exe');
      if (existsSync(pytestExe)) add(resolve(scriptsDir, '..', 'python.exe'));
    }
  }
  add('python');
  add('python3');
  if (process.platform === 'win32') {
    add('py', ['-3.13']);
    add('py', ['-3.12']);
    add('py', ['-3.11']);
  }

  const pythonPath = [resolve(projectRoot, 'src'), env.PYTHONPATH].filter(Boolean).join(delimiter);
  const failures = [];
  for (const candidate of candidates) {
    const result = spawnSync(candidate.command, [
      ...candidate.args, '-c', 'import fastapi, uvicorn',
    ], {
      cwd: projectRoot,
      env: { ...env, PYTHONPATH: pythonPath },
      encoding: 'utf8',
      windowsHide: true,
    });
    if (!result.error && result.status === 0) return candidate;
    failures.push(`${candidate.command} ${candidate.args.join(' ')}: ${result.stderr || result.error?.message || 'backend dependencies unavailable'}`);
  }
  throw new Error(
    'No Python interpreter with FastAPI and Uvicorn was found. Activate the project .venv, '
    + 'install the backend requirements there, or set PLAYWRIGHT_PYTHON to that interpreter.\n'
    + failures.join('\n'),
  );
}

if (localMode) {
  const backendPython = resolveBackendPython();
  env.PLAYWRIGHT_PYTHON = backendPython.command;
  env.PLAYWRIGHT_PYTHON_ARGS = JSON.stringify(backendPython.args);
  env.PLAYWRIGHT_API_PORT = String(await getFreePort());
  env.PLAYWRIGHT_VITE_PORT = String(await getFreePort());
  env.VITE_API_PROXY_TARGET = `http://127.0.0.1:${env.PLAYWRIGHT_API_PORT}`;
  env.PLAYWRIGHT_VITE_URL = `http://127.0.0.1:${env.PLAYWRIGHT_VITE_PORT}`;
}

const tempDatabaseRoot = localMode ? mkdtempSync(join(tmpdir(), 'macbeth-game-playwright-')) : null;
const tempDatabase = tempDatabaseRoot ? join(tempDatabaseRoot, 'phase66-playwright.sqlite3') : null;
if (tempDatabase && tempDatabaseRoot) {
  const safeRoot = resolve(tmpdir()) + sep;
  if (!resolve(tempDatabaseRoot).startsWith(safeRoot)) throw new Error('Refusing to create a Playwright database outside the system temp directory.');
  env.SQLITE_PATH = tempDatabase;
  console.log(`Playwright local mode uses isolated SQLite: ${tempDatabase}`);
  console.log(`Playwright local mode uses backend Python: ${env.PLAYWRIGHT_PYTHON}`);
}

const result = spawnSync(process.execPath, [cli, 'test', ...playwrightArgs], {
  cwd: frontendDir,
  env,
  stdio: 'inherit',
});

if (tempDatabaseRoot) {
  const resolvedTempRoot = resolve(tempDatabaseRoot);
  const safeRoot = resolve(tmpdir()) + sep;
  if (!resolvedTempRoot.startsWith(safeRoot)) throw new Error('Refusing to remove a Playwright database outside the system temp directory.');
  rmSync(resolvedTempRoot, { recursive: true, force: true });
}

process.exit(result.status ?? 1);
