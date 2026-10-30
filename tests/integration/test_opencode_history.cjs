const assert = require('node:assert/strict');
const test = require('node:test');

test('reads all pages through the completed idle marker', async () => {
  const { readCompletedTranscript } = await import('../../plugin/history.js');
  const session = { id: 'ses_test', projectID: 'prj_test', location: { directory: '/work' } };
  const client = {
    session: { get: async () => session },
    message: { list: async ({ cursor }) => cursor
      ? { data: [{ type: 'idle', id: 'idle1' }, { type: 'user', text: 'next' }], cursor: {} }
      : { data: [{ type: 'user', text: 'first' }], cursor: { next: 'next' } } },
  };
  const result = await readCompletedTranscript(client, session, 'idle1', new AbortController().signal);
  assert.deepEqual(result.map((message) => message.type), ['user', 'idle']);
});

test('refuses a server reporting a different session directory', async () => {
  const { readCompletedTranscript } = await import('../../plugin/history.js');
  const session = { id: 'ses_test', projectID: 'prj_test', location: { directory: '/work' } };
  const client = { session: { get: async () => ({ ...session, location: { directory: '/other' } }) } };
  await assert.rejects(readCompletedTranscript(client, session, 'idle1', new AbortController().signal), /session mismatch/);
});
