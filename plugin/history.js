/**
 * @param {import('@opencode/client').OpenCodeClient} client
 * @param {import('@opencode/client').SessionInfo} session
 * @param {string} idleID
 * @param {AbortSignal} signal
 * @returns {Promise<import('@opencode/client').SessionMessageInfo[]>}
 */
export async function readCompletedTranscript(client, session, idleID, signal) {
  const remote = await client.session.get({ sessionID: session.id }, { signal });
  if (remote.id !== session.id || remote.projectID !== session.projectID ||
      remote.location.directory !== session.location.directory) throw new Error('session mismatch');
  const messages = [];
  const seen = new Set();
  let cursor;
  do {
    const page = await client.message.list({ sessionID: session.id, order: 'asc', limit: 100, cursor }, { signal });
    for (const message of page.data) {
      messages.push(message);
      if (message.type === 'idle' && message.id === idleID) return messages;
    }
    cursor = page.cursor.next ?? undefined;
    if (cursor && seen.has(cursor)) throw new Error('repeated history cursor');
    seen.add(cursor);
  } while (cursor);
  throw new Error('completed turn not found');
}
