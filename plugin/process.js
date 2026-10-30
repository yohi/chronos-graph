import { spawn } from 'node:child_process';
import path from 'node:path';

/** @param {{ checkout: string, project: string, transcript: string, env: NodeJS.ProcessEnv, signal: AbortSignal }} input @param {typeof spawn} spawnProcess */
export function runTurnHook({ checkout, project, transcript, env, signal }, spawnProcess = spawn) {
  /** @type {Promise<void>} */
  return new Promise((resolve, reject) => {
    if (signal.aborted) return reject(new Error('aborted'));
    const hook = path.join(checkout, 'scripts', 'agent_turn_hook.py');
    const child = spawnProcess('uv', ['run', '--project', checkout, 'python', hook, '--strict-delivery', '--project', project], {
      cwd: checkout, env, detached: false, shell: false, stdio: ['pipe', 'ignore', 'ignore'],
    });
    let closed = false;
    /** @type {Error | undefined} */
    let stdinFailure;
    /** @type {NodeJS.Timeout | undefined} */
    let forceTimer;
    /** @type {NodeJS.Timeout | undefined} */
    let reapTimer;
    let abortStarted = false;
    const abort = () => {
      if (abortStarted) return;
      abortStarted = true;
      child.kill('SIGTERM');
      forceTimer = setTimeout(() => {
        child.kill('SIGKILL');
        reapTimer = setTimeout(() => reject(new Error('child process did not exit')), 1000);
      }, 2000);
    };
    signal.addEventListener('abort', abort, { once: true });
    child.once('error', (error) => {
      if (child.pid && !closed) {
        stdinFailure = error;
        abort();
        return;
      }
      clearTimeout(forceTimer);
      clearTimeout(reapTimer);
      signal.removeEventListener('abort', abort);
      reject(error);
    });
    child.once('close', (code) => {
      closed = true;
      clearTimeout(forceTimer);
      clearTimeout(reapTimer);
      signal.removeEventListener('abort', abort);
      if (signal.aborted) reject(new Error('aborted'));
      else if (stdinFailure) reject(stdinFailure);
      else if (code !== 0) reject(new Error('turn hook failed'));
      else resolve();
    });
    child.stdin.once('error', (error) => {
      if (closed) return;
      stdinFailure = error;
      abort();
    });
    child.stdin.end(transcript, 'utf-8');
  });
}
