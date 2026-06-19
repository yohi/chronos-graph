const { spawn } = require('node:child_process');
const path = require('node:path');
const fs = require('node:fs');
const os = require('node:os');

// Debug log helper
function logDebug(msg) {
  const isDebug = !!(process.env.CHRONOS_GATE_DEBUG || process.env.NODE_DEBUG);
  if (!isDebug) return;

  let output = msg;
  if (typeof msg === 'string') {
    output = msg
      .replace(/(sk-[a-zA-Z0-9]{20,})/g, '[REDACTED_API_KEY]')
      .replace(/(bearer\s+)[a-zA-Z0-9_.-]+/ig, '$1[REDACTED_TOKEN]')
      .replace(/(authorization:\s*)[a-zA-Z0-9_.-]+/ig, '$1[REDACTED_TOKEN]');
  } else if (typeof msg === 'object' && msg !== null) {
    try {
      output = JSON.stringify(msg);
      output = output
        .replace(/(sk-[a-zA-Z0-9]{20,})/g, '[REDACTED_API_KEY]')
        .replace(/(bearer\s+)[a-zA-Z0-9_.-]+/ig, '$1[REDACTED_TOKEN]')
        .replace(/(authorization:\s*)[a-zA-Z0-9_.-]+/ig, '$1[REDACTED_TOKEN]');
    } catch {
      output = '[Unserializable Object]';
    }
  }

  try {
    const logDir = path.resolve(os.homedir() || process.env.HOME || '', '.config', 'opencode');
    const logPath = path.resolve(logDir, 'chronos-turn-end-debug.log');
    fs.appendFileSync(logPath, `[${new Date().toISOString()}] ${output}\n`);
  } catch {}
}

// Helper to manually parse a .env file and return key-value pairs
function loadEnvFile(envPath) {
  try {
    if (!fs.existsSync(envPath)) return {};
    const content = fs.readFileSync(envPath, 'utf-8');
    const env = {};
    for (const line of content.split('\n')) {
      const trimmed = line.trim();
      if (!trimmed || trimmed.startsWith('#')) continue;
      const match = trimmed.match(/^([^=]+)=(.*)$/);
      if (match) {
        const key = match[1].trim();
        let val = match[2].trim();
        if ((val.startsWith('"') && val.endsWith('"')) || (val.startsWith("'") && val.endsWith("'"))) {
          val = val.substring(1, val.length - 1);
        } else {
          const commentIndex = val.indexOf('#');
          if (commentIndex !== -1) {
            val = val.substring(0, commentIndex).trim();
          }
        }
        env[key] = val;
      }
    }
    return env;
  } catch (e) {
    logDebug(`Failed to parse .env at ${envPath}: ${e.message}`);
    return {};
  }
}

logDebug("Turn-end ingestion plugin loaded (evaluated).");


// Helper to get prioritized list of directories to look for .env
function getChronosSearchDirs(directory = null) {
  const searchDirs = [];

  if (process.env.CHRONOS_REPO_PATH) {
    const explicitDir = path.resolve(process.env.CHRONOS_REPO_PATH);
    if (fs.existsSync(explicitDir)) {
      searchDirs.push(explicitDir);
    }
  }

  if (directory) searchDirs.push(directory);

  searchDirs.push(process.cwd());
  if (process.env.PWD) searchDirs.push(process.env.PWD);

  searchDirs.push(
    path.join(os.homedir() || process.env.HOME || '', 'program', 'chronos-graph'),
    path.join(os.homedir() || process.env.HOME || '', 'chronos-graph')
  );

  const uniqueDirs = [];
  for (const dir of searchDirs) {
    if (!dir) continue;
    try {
      const resolved = path.resolve(dir);
      if (fs.existsSync(resolved) && !uniqueDirs.includes(resolved)) {
        uniqueDirs.push(resolved);
      }
    } catch (e) {
      // Ignore resolution errors for invalid paths
    }
  }

  return uniqueDirs;
}


function sanitizeMessagesData(data) {
  if (!Array.isArray(data)) return data;
  return data.map(m => {
    const role = m.info?.role || "unknown";
    const contentSummary = (m.parts ?? [])
      .map(p => p.type === "text" ? p.text : "")
      .filter(Boolean)
      .join("\n");
    const truncated = contentSummary.length > 100 ? `${contentSummary.substring(0, 100)}... [TRUNCATED]` : contentSummary;
    return { role, textLength: contentSummary.length, textPreview: truncated };
  });
}


// Global reference variables to store client/directory if initialized via function
let globalClient = null;
let globalDirectory = null;

// Core event handler
async function handleEvent(event) {
  try {
    logDebug(`Received event: ${event.type}`);
    if (event.client && !globalClient) {
      globalClient = event.client;
    }
    if (event.directory && !globalDirectory) {
      globalDirectory = event.directory;
    }

    // Handle Session Idle -> Auto Ingest Log
    if (event.type === "session.idle") {
      const sessionId = event.properties?.sessionID;
      if (!sessionId) return;

      logDebug(`Ingesting log for session: ${sessionId}`);

      const clientObj = globalClient || event.client;
      if (!clientObj) {
        logDebug("Cannot ingest: client object is not initialized.");
        return;
      }

      const messages = await clientObj.session.messages({ path: { id: sessionId } });
      logDebug(`Raw messages.data: ${JSON.stringify(sanitizeMessagesData(messages.data))}`);
      const text = messages.data
        .map((m) => {
          const role = m.info?.role || "unknown";
          const parts = (m.parts ?? [])
            .map((p) => p.type === "text" ? p.text : "")
            .filter(Boolean)
            .join("\n");
          return `${role}: ${parts}`;
        })
        .join("\n\n");

      const validSearchDirs = getChronosSearchDirs(event.directory || globalDirectory);

      let projectDir = path.join(__dirname, "..", "..");
      const dirVal = globalDirectory || event.directory;
      if (dirVal && typeof dirVal === 'string') {
        const resolved = path.resolve(dirVal);
        if (resolved.startsWith('/') && !resolved.includes('..')) {
          projectDir = resolved;
        }
      }

      let loadedEnv = {};
      for (const dir of validSearchDirs) {
        const envPath = path.join(dir, '.env');
        if (fs.existsSync(envPath)) {
          const tempEnv = loadEnvFile(envPath);
          if (tempEnv.STORAGE_BACKEND || tempEnv.CHRONOS_INGESTION_MODE || tempEnv.MCP_GATEWAY_API_KEY) {
            projectDir = dir;
            loadedEnv = tempEnv;
            break;
          }
        }
      }
      if (loadedEnv && Object.keys(loadedEnv).length === 0 && process.env.CHRONOS_REPO_PATH) {
        projectDir = process.env.CHRONOS_REPO_PATH;
        const repoEnvPath = path.join(projectDir, '.env');
        if (fs.existsSync(repoEnvPath)) {
          loadedEnv = loadEnvFile(repoEnvPath);
        }
      }

      const script = path.join(projectDir, "scripts", "agent_turn_hook.py");

      const localVenvPython = path.join(projectDir, '.venv', 'bin', 'python');
      let pythonPath = 'python';
      let spawnArgs = [script];

      if (fs.existsSync(localVenvPython)) {
        pythonPath = localVenvPython;
        logDebug(`Using venv python for hook: ${pythonPath}`);
      } else {
        const localBinUv = path.join(os.homedir() || process.env.HOME || '', '.local', 'bin', 'uv');
        const uvPath = fs.existsSync(localBinUv) ? localBinUv : 'uv';
        pythonPath = uvPath;
        spawnArgs = ["run", "python", script];
        logDebug(`Using uv python fallback for hook: ${pythonPath} run python`);
      }

      const localBinDir = path.join(os.homedir() || process.env.HOME || '', '.local', 'bin');
      const currentPath = process.env.PATH || '';
      const newPath = currentPath.includes(localBinDir) ? currentPath : `${localBinDir}:${currentPath}`;

      let errLog = null;
      try {
        const errLogPath = path.join(os.homedir() || process.env.HOME || '', '.config', 'opencode', 'turn-end-spawn-error.log');
        errLog = fs.openSync(errLogPath, 'a');

        const child = spawn(pythonPath, spawnArgs, {
          cwd: projectDir,
          detached: true,
          stdio: ["pipe", "ignore", errLog],
          env: {
            ...process.env,
            ...loadedEnv,
            PATH: newPath
          },
        });
        child.on("error", (err) => {
          logDebug(`agent_turn_hook spawn error event: ${err.message}`);
          if (errLog !== null) {
            try { fs.closeSync(errLog); errLog = null; } catch {}
          }
        });
        child.on("close", (code) => {
          if (code === 0) {
            logDebug("Log ingestion process completed successfully.");
          } else {
            logDebug(`Log ingestion process exited with code ${code}.`);
          }
          if (errLog !== null) {
            try { fs.closeSync(errLog); errLog = null; } catch {}
          }
        });
        child.stdin.write(text, "utf-8");
        child.stdin.end();
        child.unref();
        logDebug("Log ingestion process spawned successfully.");
      } catch (spawnError) {
        logDebug(`Failed to spawn agent_turn_hook.py: ${spawnError.message}`);
        if (errLog !== null) {
          try { fs.closeSync(errLog); errLog = null; } catch {}
        }
      }
    }
  } catch (eventError) {
    logDebug(`Error inside event handler: ${eventError.message}`);
  }
}

// --------------------------------------------------------------------------
// OpenCode Plugin Specification compliant export
// --------------------------------------------------------------------------
module.exports = {
  id: "@yohi/opencode-plugin-chronos-turn-end",
  server: async (input, _options) => {
    logDebug("Turn-end plugin activation function (init) called.");
    if (input) {
      globalClient = input.client;
      globalDirectory = input.directory;
    }

    return {
      event: async ({ event }) => {
        const ev = event.event || event;
        await handleEvent(ev);
      }
    };
  }
};
