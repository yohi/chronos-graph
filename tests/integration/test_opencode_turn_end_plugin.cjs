const assert = require('node:assert/strict');
const { EventEmitter } = require('node:events');
const fs = require('node:fs');
const Module = require('node:module');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');

const PLUGIN = path.resolve(__dirname, '../../.opencode/plugins/chronos-turn-end.js');

function temporaryProject(mode) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'chronos-turn-end-'));
  fs.mkdirSync(path.join(root, 'scripts'), { recursive: true });
  fs.writeFileSync(path.join(root, '.env'), `CHRONOS_INGESTION_MODE=${mode}\n`);
  fs.writeFileSync(path.join(root, 'scripts', 'agent_turn_hook.py'), '# placeholder\n');
  return root;
}

function loadPluginWithSpawn(fakeSpawn) {
  const originalLoad = Module._load;
  delete require.cache[PLUGIN];
  Module._load = function load(request, parent, isMain) {
    if (request === 'node:child_process') return { spawn: fakeSpawn };
    return originalLoad.call(this, request, parent, isMain);
  };
  try {
    return require(PLUGIN);
  } finally {
    Module._load = originalLoad;
  }
}

test('session.idle sends rendered conversation to a detached turn-end hook', async (t) => {
  const project = temporaryProject('all');
  const home = fs.mkdtempSync(path.join(os.tmpdir(), 'chronos-turn-end-home-'));
  fs.mkdirSync(path.join(home, '.config', 'opencode'), { recursive: true });
  const oldHome = process.env.HOME;
  process.env.HOME = home;
  const calls = [];
  const fakeSpawn = (command, args, options) => {
    const child = new EventEmitter();
    child.stdin = {
      written: '',
      ended: false,
      write(text) { this.written += text; },
      end() { this.ended = true; },
    };
    child.unreferenced = false;
    child.unref = () => { child.unreferenced = true; };
    calls.push({ command, args, options, child });
    return child;
  };
  t.after(() => {
    process.env.HOME = oldHome;
    delete require.cache[PLUGIN];
    fs.rmSync(project, { recursive: true, force: true });
    fs.rmSync(home, { recursive: true, force: true });
  });
  const sessionCalls = [];
  const client = {
    session: {
      messages: async ({ path: messagePath }) => {
        sessionCalls.push(messagePath.id);
        return {
          data: [
            { info: { role: 'User' }, parts: [{ type: 'text', text: 'hello' }] },
            { info: { role: 'Assistant' }, parts: [{ type: 'text', text: 'hi' }] },
          ],
        };
      },
    },
  };

  const plugin = loadPluginWithSpawn(fakeSpawn);
  const server = await plugin.server({ client, directory: project });
  await server.event({ event: { type: 'session.idle', properties: { sessionID: 'session-42' } } });

  assert.deepEqual(sessionCalls, ['session-42']);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].args.at(-1), path.join(project, 'scripts', 'agent_turn_hook.py'));
  assert.equal(calls[0].options.cwd, project);
  assert.equal(calls[0].child.stdin.written, 'User: hello\n\nAssistant: hi');
  assert.equal(calls[0].child.stdin.ended, true);
  assert.equal(calls[0].options.detached, true);
  assert.equal(calls[0].child.unreferenced, true);
});

test('session.idle does not spawn the hook outside all ingestion mode', async (t) => {
  const project = temporaryProject('selective');
  const home = fs.mkdtempSync(path.join(os.tmpdir(), 'chronos-turn-end-home-'));
  fs.mkdirSync(path.join(home, '.config', 'opencode'), { recursive: true });
  const oldHome = process.env.HOME;
  process.env.HOME = home;
  let spawns = 0;
  t.after(() => {
    process.env.HOME = oldHome;
    delete require.cache[PLUGIN];
    fs.rmSync(project, { recursive: true, force: true });
    fs.rmSync(home, { recursive: true, force: true });
  });
  const plugin = loadPluginWithSpawn(() => { spawns += 1; throw new Error('must not spawn'); });
  const server = await plugin.server({
    client: { session: { messages: async () => ({ data: [] }) } },
    directory: project,
  });

  await server.event({ event: { type: 'session.idle', properties: { sessionID: 'session-42' } } });

  assert.equal(spawns, 0);
});
