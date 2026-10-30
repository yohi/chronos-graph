/** @param {ReadonlyArray<import('@opencode/client').SessionMessageInfo>} messages */
export function renderTranscript(messages) {
  return messages.flatMap((message) => {
    if (message.type === 'user') return message.text ? [`User: ${message.text}`] : [];
    if (message.type !== 'assistant') return [];
    const text = message.content.flatMap((part) => part.type === 'text' && part.text ? [part.text] : []).join('\n');
    return text ? [`Assistant: ${text}`] : [];
  }).join('\n\n');
}
