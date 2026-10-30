import path from 'node:path';
import fs from 'node:fs';

const HOOK_ENV = new Set([
  'CHRONOS_INGESTION_MODE',
  'MCP_GATEWAY_URL',
  'MCP_GATEWAY_API_KEY',
  'MCP_INTENT',
  'MCP_HOOK_TIMEOUT_SECONDS',
  'MCP_HOOK_SSE_TIMEOUT_SECONDS',
  'MCP_HOOK_MAX_LOG_BYTES',
  'LOG_LEVEL',
]);

/** @param {string} checkout @param {NodeJS.ProcessEnv} processEnvironment @returns {NodeJS.ProcessEnv} */
function checkoutEnvironment(checkout, processEnvironment) {
  /** @type {NodeJS.ProcessEnv} */
  const values = {};
  const envPath = path.join(checkout, '.env');
  if (!fs.existsSync(envPath)) return { ...processEnvironment };
  const content = fs.readFileSync(envPath, 'utf8');
  for (const line of content.split(/\r?\n/)) {
    const match = line.match(/^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$/);
    if (!match || !HOOK_ENV.has(match[1])) continue;
    const raw = match[2].trim();
    const quoted = raw.match(/^(['"])(.*)\1(?:\s+#.*)?$/);
    const value = quoted ? quoted[2] : raw.replace(/\s+#.*$/, '').trim();
    values[match[1]] = value;
  }
  return { ...values, ...processEnvironment };
}

/** @param {NodeJS.ProcessEnv} env @param {string} sessionDirectory */
export function resolveOptions(env, sessionDirectory) {
  const checkout = path.resolve(env.CHRONOS_REPO_PATH ?? sessionDirectory);
  const childEnv = checkoutEnvironment(checkout, env);
  const mode = (childEnv.CHRONOS_INGESTION_MODE ?? 'selective').trim().toLowerCase();
  const serverURL = env.CHRONOS_OPENCODE_SERVER_URL;
  const authorization = env.CHRONOS_OPENCODE_AUTHORIZATION;
  if (mode === 'all') {
    if (!fs.existsSync(path.join(checkout, 'scripts', 'agent_turn_hook.py'))) throw new Error('hook not found');
    if (!serverURL) throw new Error('server URL required');
    const url = new URL(serverURL);
    const loopback = ['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname);
    if (url.username || url.password || (url.protocol !== 'https:' && !(url.protocol === 'http:' && loopback))) {
      throw new Error('invalid server URL');
    }
    return { mode, checkout, serverURL: url.toString(), authorization, childEnv };
  }
  return { mode, checkout, serverURL, authorization, childEnv };
}
