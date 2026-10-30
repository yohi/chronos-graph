const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');

test('serializes turns and checkpoints completed submissions without duplicate events', async (t) => {
  const { startRuntime } = await import('../../plugin/runtime.js');
  const checkout = fs.mkdtempSync(path.join(os.tmpdir(), 'chronos-runtime-'));
  fs.mkdirSync(path.join(checkout, 'scripts'));
  fs.writeFileSync(path.join(checkout, 'scripts', 'agent_turn_hook.py'), '');
  t.after(() => fs.rmSync(checkout, { recursive: true, force: true }));
  const prior = {
    mode: process.env.CHRONOS_INGESTION_MODE,
    repo: process.env.CHRONOS_REPO_PATH,
    url: process.env.CHRONOS_OPENCODE_SERVER_URL,
    authorization: process.env.CHRONOS_OPENCODE_AUTHORIZATION,
  };
  process.env.CHRONOS_INGESTION_MODE = 'all';
  process.env.CHRONOS_REPO_PATH = checkout;
  process.env.CHRONOS_OPENCODE_SERVER_URL = 'http://127.0.0.1:4096';
  process.env.CHRONOS_OPENCODE_AUTHORIZATION = 'Bearer fixture-secret';
  t.after(() => {
    for (const [key, value] of [
      ['CHRONOS_INGESTION_MODE', prior.mode],
      ['CHRONOS_REPO_PATH', prior.repo],
      ['CHRONOS_OPENCODE_SERVER_URL', prior.url],
      ['CHRONOS_OPENCODE_AUTHORIZATION', prior.authorization],
    ]) {
      if (value === undefined) delete process.env[key]; else process.env[key] = value;
    }
  });
  const location = { directory: checkout };
  const session = { id: 'ses_1', projectID: 'prj_1', location };
  const idle = (id) => ({ id, type: 'idle', outcome: 'succeeded', time: { created: 1 } });
  const events = [
    { id: 'evt_a', type: 'session.execution.succeeded', created: 1, data: { sessionID: session.id }, location },
    { id: 'evt_a', type: 'session.execution.succeeded', created: 1, data: { sessionID: session.id }, location },
    { id: 'evt_b', type: 'session.execution.succeeded', created: 2, data: { sessionID: session.id }, location },
  ];
  const values = new Map();
  const submitted = [];
  let resolveDrained;
  const drained = new Promise((resolve) => { resolveDrained = resolve; });
  let resolveSubmitted;
  const allSubmitted = new Promise((resolve) => { resolveSubmitted = resolve; });
  const failures = [];
  let resolveReads;
  const readsStarted = new Promise((resolve) => { resolveReads = resolve; });
  let reads = 0;
  const client = {
    session: {
      get: async () => { reads += 1; if (reads === 2) resolveReads(); return session; },
      list: async () => ({ data: [], cursor: {} }),
    },
    message: { list: async () => ({ data: [idle('msg_a'), idle('msg_b')], cursor: {} }) },
  };
  const ctx = {
    location,
    event: { subscribe: async function* () { yield* events; resolveDrained(); } },
    storage: { get: async (key) => values.get(key), set: async (key, value) => { values.set(key, value); }, remove: async () => {}, scan: async () => ({ entries: [], cursor: undefined }) },
  };
  const cleanup = await startRuntime(ctx, {
    createClient: () => client,
    runHook: async ({ transcript, project, env }) => {
      assert.equal(env.CHRONOS_OPENCODE_AUTHORIZATION, undefined);
      submitted.push({ transcript, project });
      if (submitted.length === 2) resolveSubmitted();
    },
    onError: (error) => { failures.push(String(error)); },
  });
  await drained;
  await readsStarted;
  await Promise.race([allSubmitted, new Promise((resolve) => setTimeout(resolve, 1000))]);
  await cleanup();
  assert.deepEqual(failures, []);
  assert.deepEqual(submitted, [
    { transcript: '', project: path.basename(checkout) },
    { transcript: '', project: path.basename(checkout) },
  ]);
  assert.equal(values.get(`last-idle:${session.id}`), 'msg_b');
});

test('reconciles completed idle messages newer than the stored checkpoint', async (t) => {
  const { startRuntime } = await import('../../plugin/runtime.js');
  const checkout = fs.mkdtempSync(path.join(os.tmpdir(), 'chronos-reconcile-'));
  fs.mkdirSync(path.join(checkout, 'scripts'));
  fs.writeFileSync(path.join(checkout, 'scripts', 'agent_turn_hook.py'), '');
  t.after(() => fs.rmSync(checkout, { recursive: true, force: true }));
  const previous = [process.env.CHRONOS_INGESTION_MODE, process.env.CHRONOS_REPO_PATH, process.env.CHRONOS_OPENCODE_SERVER_URL];
  process.env.CHRONOS_INGESTION_MODE = 'all';
  process.env.CHRONOS_REPO_PATH = checkout;
  process.env.CHRONOS_OPENCODE_SERVER_URL = 'http://127.0.0.1:4096';
  t.after(() => {
    for (const [key, value] of [['CHRONOS_INGESTION_MODE', previous[0]], ['CHRONOS_REPO_PATH', previous[1]], ['CHRONOS_OPENCODE_SERVER_URL', previous[2]]]) {
      if (value === undefined) delete process.env[key]; else process.env[key] = value;
    }
  });
  const location = { directory: checkout };
  const session = { id: 'ses_reconcile', projectID: 'prj_1', location };
  const storage = new Map([[`last-idle:${session.id}`, 'msg_old']]);
  const submitted = [];
  const client = {
    session: { get: async () => session, list: async () => ({ data: [session], cursor: {} }) },
    message: { list: async (input) => input.type === 'idle'
      ? { data: [{ id: 'msg_new', type: 'idle', outcome: 'succeeded', time: { created: 2 } }], cursor: {} }
      : { data: [
        { id: 'msg_user', type: 'user', text: 'missed turn', time: { created: 1 } },
        { id: 'msg_new', type: 'idle', outcome: 'succeeded', time: { created: 2 } },
      ], cursor: {} } },
  };
  const ctx = {
    location,
    event: { subscribe: async function* () {} },
    storage: { get: async (key) => storage.get(key), set: async (key, value) => { storage.set(key, value); }, remove: async () => {}, scan: async () => ({ entries: [], cursor: undefined }) },
  };
  const cleanup = await startRuntime(ctx, {
    createClient: () => client,
    runHook: async ({ transcript }) => { submitted.push(transcript); },
  });
  await cleanup();
  assert.deepEqual(submitted, ['User: missed turn']);
  assert.equal(storage.get(`last-idle:${session.id}`), 'msg_new');
});

test('resubscribes after the event stream closes', async (t) => {
  const { startRuntime } = await import('../../plugin/runtime.js');
  const checkout = fs.mkdtempSync(path.join(os.tmpdir(), 'chronos-reconnect-'));
  fs.mkdirSync(path.join(checkout, 'scripts'));
  fs.writeFileSync(path.join(checkout, 'scripts', 'agent_turn_hook.py'), '');
  t.after(() => fs.rmSync(checkout, { recursive: true, force: true }));
  const prior = [process.env.CHRONOS_INGESTION_MODE, process.env.CHRONOS_REPO_PATH, process.env.CHRONOS_OPENCODE_SERVER_URL];
  process.env.CHRONOS_INGESTION_MODE = 'all';
  process.env.CHRONOS_REPO_PATH = checkout;
  process.env.CHRONOS_OPENCODE_SERVER_URL = 'http://127.0.0.1:4096';
  t.after(() => {
    for (const [key, value] of [['CHRONOS_INGESTION_MODE', prior[0]], ['CHRONOS_REPO_PATH', prior[1]], ['CHRONOS_OPENCODE_SERVER_URL', prior[2]]]) {
      if (value === undefined) delete process.env[key]; else process.env[key] = value;
    }
  });
  let subscriptions = 0;
  let reconciliations = 0;
  let resolveReconnected;
  const reconnected = new Promise((resolve) => { resolveReconnected = resolve; });
  const ctx = {
    location: { directory: checkout },
    event: { subscribe: async function* ({ signal }) {
      subscriptions += 1;
      if (subscriptions === 2) resolveReconnected();
      if (subscriptions > 1) await new Promise((resolve) => signal.addEventListener('abort', resolve, { once: true }));
    } },
    storage: { get: async () => undefined, set: async () => {}, remove: async () => {}, scan: async () => ({ entries: [], cursor: undefined }) },
  };
  const cleanup = await startRuntime(ctx, {
    createClient: () => ({ session: { list: async () => { reconciliations += 1; return { data: [], cursor: {} }; } } }),
    runHook: async () => {},
  });
  await reconnected;
  await cleanup();
  assert.equal(subscriptions, 2);
  assert.equal(reconciliations, 2);
});
