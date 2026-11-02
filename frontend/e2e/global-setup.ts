import { spawn, spawnSync, type ChildProcess } from 'node:child_process';
import { delimiter, resolve } from 'node:path';
import type { FullConfig } from '@playwright/test';

const wait = (milliseconds: number) => new Promise((resolvePromise) => setTimeout(resolvePromise, milliseconds));

async function waitForService(child: ChildProcess, url: string, label: string, logs: string[], timeoutMs: number) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    if (child.exitCode !== null) throw new Error(`${label} exited before becoming ready. ${logs.join('')}`);
    try {
      const response = await fetch(url, { signal: AbortSignal.timeout(1000) });
      if (response.ok) return;
    } catch {
      // Continue polling while the local process starts.
    }
    await wait(250);
  }
  throw new Error(`${label} did not become ready within ${timeoutMs}ms. ${logs.join('')}`);
}

export default async function globalSetup(_config: FullConfig) {
  const frontendDir = process.cwd();
  const projectRoot = resolve(frontendDir, '..');
  const localMode = process.env.PLAYWRIGHT_MODE === 'local';
  const apiUrl = `http://127.0.0.1:${process.env.PLAYWRIGHT_API_PORT || '8017'}`;
  const viteUrl = process.env.PLAYWRIGHT_VITE_URL || 'http://127.0.0.1:5173';
  const python = process.env.PLAYWRIGHT_PYTHON || 'python';
  const pythonArgs: string[] = process.env.PLAYWRIGHT_PYTHON_ARGS
    ? JSON.parse(process.env.PLAYWRIGHT_PYTHON_ARGS) as string[]
    : [];
  const processes: ChildProcess[] = [];

  function launch(command: string, args: string[], cwd: string, env: NodeJS.ProcessEnv) {
    const child = spawn(command, args, { cwd, env, stdio: ['ignore', 'pipe', 'pipe'], windowsHide: true });
    const output: string[] = [];
    for (const stream of [child.stdout, child.stderr]) {
      stream?.on('data', (chunk: Buffer) => {
        output.push(chunk.toString());
        if (output.join('').length > 5000) output.shift();
      });
    }
    processes.push(child);
    return { child, output };
  }

  async function stopProcesses() {
    for (const child of processes.reverse()) {
      if (child.exitCode !== null || !child.pid) continue;
      if (process.platform === 'win32') {
        spawnSync('taskkill', ['/PID', String(child.pid), '/T', '/F'], { stdio: 'ignore', windowsHide: true });
      } else {
        try { process.kill(child.pid, 'SIGTERM'); } catch { /* Process already exited. */ }
      }
    }
    await Promise.all(processes.map((child) => new Promise<void>((resolvePromise) => {
      if (child.exitCode !== null) return resolvePromise();
      const timeout = setTimeout(() => resolvePromise(), 5000);
      child.once('exit', () => { clearTimeout(timeout); resolvePromise(); });
    })));
  }

  try {
    if (localMode) {
      console.log(`Starting isolated FastAPI with SQLITE_PATH=${process.env.SQLITE_PATH || '(unset)'}`);
      const backendEnv = {
        ...process.env,
        SQLITE_PATH: process.env.SQLITE_PATH || '',
        PYTHONPATH: [resolve(projectRoot, 'src'), process.env.PYTHONPATH].filter(Boolean).join(delimiter),
      };
      const backend = launch(python, [...pythonArgs, '-m', 'uvicorn', 'macbeth_game.main:app', '--host', '127.0.0.1', '--port', process.env.PLAYWRIGHT_API_PORT || '8017'], projectRoot, backendEnv);
      await waitForService(backend.child, `${apiUrl}/api/v1/health`, 'Isolated FastAPI service', backend.output, 120_000);
    }

    const viteCli = resolve(frontendDir, 'node_modules', 'vite', 'bin', 'vite.js');
    const frontendEnv = localMode ? { ...process.env, VITE_API_PROXY_TARGET: apiUrl } : process.env;
    const viteArgs = ['--host', '127.0.0.1', '--strictPort'];
    if (localMode) viteArgs.push('--port', process.env.PLAYWRIGHT_VITE_PORT || '5173');
    const vite = launch(process.execPath, [viteCli, ...viteArgs], frontendDir, frontendEnv);
    await waitForService(vite.child, viteUrl, 'Vite development server', vite.output, 60_000);
  } catch (error) {
    await stopProcesses();
    throw error;
  }

  return async () => {
    await stopProcesses();
  };
}
