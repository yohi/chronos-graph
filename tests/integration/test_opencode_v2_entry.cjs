const assert = require('node:assert/strict');
const test = require('node:test');

test('exports a V2 plugin with the stable identity and setup', async () => {
  const { default: plugin } = await import('../../.opencode/plugins/chronos-turn-end.js');
  assert.equal(plugin.id, '@yohi/opencode-plugin-chronos-turn-end');
  assert.equal(typeof plugin.setup, 'function');
});

test('selective mode does not subscribe or start ingestion', async () => {
  const { default: plugin } = await import('../../.opencode/plugins/chronos-turn-end.js');
  const old = process.env.CHRONOS_INGESTION_MODE;
  process.env.CHRONOS_INGESTION_MODE = 'selective';
  try {
    const cleanup = await plugin.setup({
      location: { directory: process.cwd() },
      event: { subscribe() { throw Error('subscribed'); } },
    });
    if (cleanup) await cleanup();
  } finally {
    if (old === undefined) delete process.env.CHRONOS_INGESTION_MODE;
    else process.env.CHRONOS_INGESTION_MODE = old;
  }
});
