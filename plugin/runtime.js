import { OpenCode } from '@opencode/client';
import path from 'node:path';
import { readCompletedTranscript } from './history.js';
import { renderTranscript } from './transcript.js';
import { resolveOptions } from './options.js';
import { runTurnHook } from './process.js';

const TERMINAL = new Set(['session.execution.succeeded', 'session.execution.failed', 'session.execution.interrupted']);

/** @param {import('@opencode/plugin').Plugin.Context} ctx @param {{ createClient?: typeof OpenCode.make, runHook?: typeof runTurnHook, onError?: (error: unknown) => void }} [dependencies] */
export async function startRuntime(ctx, dependencies = {}) {
  const options = resolveOptions(process.env, ctx.location.directory);
  if (options.mode !== 'all') return;
  if (!options.serverURL) throw new Error('server URL required');
  const controller = new AbortController();
  const client = (dependencies.createClient ?? OpenCode.make)({
    baseUrl: options.serverURL,
    headers: options.authorization ? { Authorization: options.authorization } : undefined,
  });
  const pending = new Map();
  const queuedIdle = new Set();
  const lastIdle = new Map();
  let stopped = false;
  let initializing = true;
  /** @type {import('@opencode/client').OpenCodeEvent[]} */
  const buffered = [];
  let finishInitialization = () => {};
  /** @type {Promise<void>} */
  const initialized = new Promise((resolve) => { finishInitialization = () => resolve(); });
  /** @param {unknown} error */
  const reportError = (error) => {
    if (dependencies.onError) dependencies.onError(error);
    else process.stderr.write('ChronosGraph OpenCode turn ingestion failed\n');
  };
  /** @param {string} sessionID @param {string} idleID @param {{ directory: string } | undefined} location */
  const enqueue = async (sessionID, idleID, location) => {
    const previous = lastIdle.get(sessionID) ?? await ctx.storage.get(`last-idle:${sessionID}`);
    if (previous === idleID || queuedIdle.has(`${sessionID}:${idleID}`)) return;
    const key = `${sessionID}:${idleID}`;
    queuedIdle.add(key);
    const earlier = pending.get(sessionID) ?? Promise.resolve();
    const task = async () => {
      const historySignal = AbortSignal.any([controller.signal, AbortSignal.timeout(30_000)]);
      const session = await client.session.get({ sessionID }, { signal: historySignal });
      if (session.location.directory !== ctx.location.directory ||
          (location && location.directory !== session.location.directory)) {
        throw new Error('session location mismatch');
      }
      const history = await readCompletedTranscript(client, session, idleID, historySignal);
      const latestSession = await client.session.get({ sessionID }, { signal: historySignal });
      if (latestSession.location.directory !== session.location.directory || latestSession.projectID !== session.projectID) {
        throw new Error('session moved during ingestion');
      }
      const childEnv = { ...options.childEnv };
      delete childEnv.CHRONOS_OPENCODE_AUTHORIZATION;
      delete childEnv.CHRONOS_OPENCODE_SERVER_URL;
      await (dependencies.runHook ?? runTurnHook)({
        checkout: options.checkout,
        project: path.basename(latestSession.location.directory),
        transcript: renderTranscript(history),
        env: childEnv,
        signal: controller.signal,
      });
      await ctx.storage.set(`last-idle:${sessionID}`, idleID);
      lastIdle.set(sessionID, idleID);
    };
    const queued = earlier.catch(() => {}).then(task);
    pending.set(sessionID, queued);
    void queued.catch(reportError).finally(() => {
      queuedIdle.delete(key);
      if (pending.get(sessionID) === queued) pending.delete(sessionID);
    });
  };
  /** @param {import('@opencode/client').OpenCodeEvent} event */
  const acceptEvent = async (event) => {
    if (!TERMINAL.has(event.type) || !('sessionID' in event.data)) return;
    if (event.type === 'session.execution.interrupted' && event.data.reason !== 'user') return;
    await enqueue(event.data.sessionID, event.id.replace(/^evt_/, 'msg_'), event.location);
  };
  const reconcileSessions = async () => {
    const reconcileSignal = AbortSignal.any([controller.signal, AbortSignal.timeout(30_000)]);
    let sessionCursor;
    do {
      const page = await client.session.list(
        { directory: ctx.location.directory, limit: 100, ...(sessionCursor ? { cursor: sessionCursor } : {}) },
        { signal: reconcileSignal },
      );
      for (const session of page.data) {
        const checkpoint = await ctx.storage.get(`last-idle:${session.id}`);
        if (typeof checkpoint !== 'string') {
          const latest = await client.message.list(
            { sessionID: session.id, order: 'desc', limit: 1, type: 'idle' },
            { signal: reconcileSignal },
          );
          const marker = latest.data[0];
          if (marker?.type === 'idle') {
            await ctx.storage.set(`last-idle:${session.id}`, marker.id);
            lastIdle.set(session.id, marker.id);
          }
          continue;
        }
        /** @type {string | undefined} */
        let messageCursor = checkpoint;
        const seen = new Set();
        do {
          const messages = await client.message.list(
            { sessionID: session.id, order: 'asc', limit: 100, cursor: messageCursor, type: 'idle' },
            { signal: reconcileSignal },
          );
          for (const message of messages.data) {
            if (message.type === 'idle') await enqueue(session.id, message.id, session.location);
          }
          messageCursor = messages.cursor.next ?? undefined;
          if (messageCursor && seen.has(messageCursor)) throw new Error('repeated idle cursor');
          if (messageCursor) seen.add(messageCursor);
        } while (messageCursor);
      }
      sessionCursor = page.cursor.next ?? undefined;
    } while (sessionCursor);
  };
  /** @param {number} milliseconds @returns {Promise<void>} */
  const wait = (milliseconds) => new Promise((resolve) => {
    const finish = () => {
      clearTimeout(timer);
      controller.signal.removeEventListener('abort', finish);
      resolve();
    };
    const timer = setTimeout(finish, milliseconds);
    controller.signal.addEventListener('abort', finish, { once: true });
  });
  const consume = (async () => {
    let backoff = 250;
    while (!stopped) {
      try {
        const stream = ctx.event.subscribe({ signal: controller.signal });
        for await (const event of stream) {
          if (stopped) break;
          backoff = 250;
          if (initializing) buffered.push(event);
          else await acceptEvent(event);
        }
        if (stopped) break;
        await initialized;
        await wait(backoff);
        await reconcileSessions();
        backoff = Math.min(backoff * 2, 5000);
      } catch (error) {
        if (stopped) break;
        reportError(error);
        await initialized;
        await wait(backoff);
        try {
          await reconcileSessions();
        } catch (reconcileError) {
          reportError(reconcileError);
        }
        backoff = Math.min(backoff * 2, 5000);
      }
    }
  })();
  try {
    await reconcileSessions();
  } catch (error) {
    reportError(error);
  }
  initializing = false;
  for (const event of buffered) {
    try {
      await acceptEvent(event);
    } catch (error) {
      reportError(error);
    }
  }
  finishInitialization();
  return async () => {
    if (stopped) return;
    stopped = true;
    controller.abort();
    await Promise.allSettled([...pending.values()]);
    await Promise.allSettled([consume]);
  };
}
