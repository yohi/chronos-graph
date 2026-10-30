const assert = require('node:assert/strict');
const { EventEmitter } = require('node:events');
const { PassThrough } = require('node:stream');
const test = require('node:test');

test('runs the hook with conversation data on stdin and rejects failed delivery', async () => {
  const { runTurnHook } = await import('../../plugin/process.js');
  const child = new EventEmitter();
  child.stdin = new PassThrough();
  child.kill = () => true;
  const chunks = [];
  child.stdin.on('data', (chunk) => chunks.push(chunk));
  child.stdin.on('end', () => child.emit('close', 0));
  let invocation;
  const spawn = (...args) => { invocation = args; return child; };
  await runTurnHook({
    checkout: '/chronos', project: 'conversation-project', transcript: 'User: secret text',
    env: { PATH: '/bin' }, signal: new AbortController().signal,
  }, spawn);
  assert.deepEqual(invocation.slice(0, 2), [
    'uv', ['run', '--project', '/chronos', 'python', '/chronos/scripts/agent_turn_hook.py', '--strict-delivery', '--project', 'conversation-project'],
  ]);
  assert.equal(invocation[2].detached, false);
  assert.equal(invocation[2].shell, false);
  assert.equal(Buffer.concat(chunks).toString(), 'User: secret text');
});

test('does not spawn after cancellation', async () => {
  const { runTurnHook } = await import('../../plugin/process.js');
  const controller = new AbortController();
  controller.abort();
  let spawned = false;
  await assert.rejects(runTurnHook({ checkout: '/chronos', project: 'p', transcript: '', env: {}, signal: controller.signal }, () => {
    spawned = true;
    throw Error('unexpected spawn');
  }), /aborted/);
  assert.equal(spawned, false);
});

test('terminates and reaps the child after stdin failure', async () => {
  const { runTurnHook } = await import('../../plugin/process.js');
  const child = new EventEmitter();
  child.stdin = new EventEmitter();
  child.stdin.end = () => process.nextTick(() => child.stdin.emit('error', Error('broken pipe')));
  let terminated = false;
  child.kill = (signal) => {
    terminated = signal === 'SIGTERM';
    process.nextTick(() => child.emit('close', 1));
    return true;
  };
  await assert.rejects(runTurnHook({ checkout: '/chronos', project: 'p', transcript: 'x', env: {}, signal: new AbortController().signal }, () => child), /broken pipe/);
  assert.equal(terminated, true);
});
