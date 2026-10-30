const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');

test('requires a safe explicit server URL only when all-mode is enabled', async (t) => {
  const { resolveOptions } = await import('../../plugin/options.js');
  const checkout = fs.mkdtempSync(path.join(os.tmpdir(), 'chronos-options-'));
  fs.mkdirSync(path.join(checkout, 'scripts'));
  fs.writeFileSync(path.join(checkout, 'scripts', 'agent_turn_hook.py'), '');
  fs.writeFileSync(path.join(checkout, '.env'), 'CHRONOS_INGESTION_MODE=all\nMCP_GATEWAY_API_KEY="checkout #secret"\nMCP_GATEWAY_URL="http://checkout-gateway"\n');
  t.after(() => fs.rmSync(checkout, { recursive: true, force: true }));
  assert.equal(resolveOptions({ CHRONOS_INGESTION_MODE: 'selective' }, checkout).mode, 'selective');
  assert.throws(() => resolveOptions({ CHRONOS_INGESTION_MODE: 'all' }, checkout), /server URL required/);
  assert.equal(resolveOptions({ CHRONOS_INGESTION_MODE: 'all', CHRONOS_OPENCODE_SERVER_URL: 'http://127.0.0.1:4096' }, checkout).mode, 'all');
  assert.throws(() => resolveOptions({ CHRONOS_INGESTION_MODE: 'all', CHRONOS_OPENCODE_SERVER_URL: 'http://example.com' }, checkout), /invalid server URL/);
  const configured = resolveOptions({
    CHRONOS_OPENCODE_SERVER_URL: 'http://127.0.0.1:4096',
    MCP_GATEWAY_URL: 'http://process-gateway',
  }, checkout);
  assert.equal(configured.childEnv.MCP_GATEWAY_API_KEY, 'checkout #secret');
  assert.equal(configured.childEnv.MCP_GATEWAY_URL, 'http://process-gateway');
});

test('selective mode does not require the Python hook in a conversation project', async (t) => {
  const { resolveOptions } = await import('../../plugin/options.js');
  const project = fs.mkdtempSync(path.join(os.tmpdir(), 'chronos-selective-'));
  t.after(() => fs.rmSync(project, { recursive: true, force: true }));
  assert.equal(resolveOptions({}, project).mode, 'selective');
});
