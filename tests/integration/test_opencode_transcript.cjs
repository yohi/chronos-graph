const assert = require('node:assert/strict');
const test = require('node:test');

test('renders original user and assistant text without internal content', async () => {
  const { renderTranscript } = await import('../../plugin/transcript.js');
  const messages = [
    { type: 'user', text: 'hello' },
    { type: 'assistant', content: [
      { type: 'reasoning', text: 'private' },
      { type: 'text', text: 'hi', native: { secret: 'private' } },
      { type: 'tool', state: { output: 'private' } },
    ] },
    { type: 'compaction', summary: 'not conversation' },
    { type: 'idle', outcome: 'succeeded' },
  ];
  assert.equal(renderTranscript(messages), 'User: hello\n\nAssistant: hi');
});

test('preserves multiline and Japanese text and skips empty messages', async () => {
  const { renderTranscript } = await import('../../plugin/transcript.js');
  assert.equal(renderTranscript([
    { type: 'user', text: '' },
    { type: 'user', text: 'こんにちは\n世界' },
    { type: 'assistant', content: [{ type: 'text', text: '' }] },
  ]), 'User: こんにちは\n世界');
});
