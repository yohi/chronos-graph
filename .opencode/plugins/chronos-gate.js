const { spawn } = require('node:child_process');
const path = require('node:path');
const fs = require('node:fs');

// Debug log helper
function logDebug(msg) {
  try {
    fs.appendFileSync(path.join(process.env.HOME, '.config', 'opencode', 'chronos-gate-debug.log'), `[${new Date().toISOString()}] ${msg}\n`);
  } catch (e) {}
}

logDebug("Plugin script loaded (evaluated).");

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
        let key = match[1].trim();
        let val = match[2].trim();
        if ((val.startsWith('"') && val.endsWith('"')) || (val.startsWith("'") && val.endsWith("'"))) {
          val = val.substring(1, val.length - 1);
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


// Core logic for tool evaluation
async function evaluateTool(toolCall) {
  return new Promise((resolve, reject) => {
    const http = require('node:http');
    const postData = JSON.stringify(toolCall);
    
    const options = {
      hostname: '127.0.0.1',
      port: 9100,
      path: '/evaluate',
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Content-Length': Buffer.byteLength(postData)
      },
      timeout: 45000
    };

    const req = http.request(options, (res) => {
      let data = '';
      res.on('data', (chunk) => {
        data += chunk;
      });
      res.on('end', () => {
        if (res.statusCode !== 200) {
          reject(new Error(`Server returned status code ${res.statusCode}: ${data}`));
          return;
        }
        try {
          const result = JSON.parse(data);
          logDebug(`evaluateTool raw output (http): ${JSON.stringify(result)}`);
          if (result.decision === 'allow') {
            resolve({ status: 'allow' });
          } else {
            resolve({
              status: 'deny',
              reason: result.reason,
              decision: result.decision,
              ask_message: result.ask_message
            });
          }
        } catch (e) {
          reject(new Error(`Failed to parse response: ${e.message}. Data: ${data}`));
        }
      });
    });

    req.on('error', (e) => {
      reject(e);
    });

    req.on('timeout', () => {
      req.destroy();
      reject(new Error('Evaluation request timed out after 45000ms'));
    });

    req.write(postData);
    req.end();
  });
}

// Global reference variables to store client/directory if initialized via function
let globalClient = null;
let globalDirectory = null;
let globalInput = null;
if (!global.__chronos_active_evaluations) {
  global.__chronos_active_evaluations = new Set();
}
const activeEvaluations = global.__chronos_active_evaluations;

// Helper to show TUI toast message with slight delay to ensure TUI layer is ready
function showToast(message, variant = "info") {
  if (!globalClient) return;
  setTimeout(async () => {
    try {
      await globalClient.tui.showToast({
        body: {
          title: "Chronos Gate",
          message: message,
          variant: variant,
          duration: 3000
        }
      });
    } catch (e) {
      logDebug(`Failed to show toast: ${e.message}`);
    }
  }, 500);
}

let isSpawning = false;

// Helper to check gateway status and start it if offline
function checkAndStartGateway() {
  const net = require('node:net');
  const clientSocket = new net.Socket();
  clientSocket.setTimeout(1000);
  clientSocket.once('connect', () => {
    clientSocket.destroy();
    logDebug("Gateway is already running (port 9100 responds).");
    showToast("Gateway is already running (port 9100).", "success");
  }).once('error', (err) => {
    clientSocket.destroy();
    if (isSpawning) {
      logDebug("Gateway auto-start is already in progress. Skipping duplicate spawn.");
      return;
    }
    isSpawning = true;
    setTimeout(() => { isSpawning = false; }, 15000); // Reset flag after 15s
    logDebug(`Gateway is offline. Attempting auto-start: ${err.message}`);
    showToast("Gateway is offline. Auto-starting...", "warning");
    try {
      const fs = require('node:fs');
      const errLogPath = path.join(process.env.HOME, '.config', 'opencode', 'gateway-spawn-error.log');
      const errLog = fs.openSync(errLogPath, 'a');

      // Search for the project directory containing .env to resolve validation errors
      const searchDirs = [
        path.join(process.env.HOME, 'program', 'chronos-graph'),
        path.join(process.env.HOME, 'chronos-graph'),
        globalDirectory,
        process.cwd(),
        process.env.PWD
      ].filter(Boolean);

      let projectDir = null;
      let loadedEnv = {};

      for (const dir of searchDirs) {
        const envPath = path.join(dir, '.env');
        if (fs.existsSync(envPath)) {
          const tempEnv = loadEnvFile(envPath);
          // Confirm this .env belongs to chronos-graph
          if (tempEnv.STORAGE_BACKEND || tempEnv.MCP_GATEWAY_PORT || tempEnv.CHRONOS_INGESTION_MODE) {
            projectDir = dir;
            loadedEnv = tempEnv;
            logDebug(`Found correct .env in: ${dir}`);
            break;
          } else {
            logDebug(`Skipped .env in ${dir} (missing chronos-graph config keys).`);
          }
        }
      }

      if (!projectDir) {
        logDebug("Warning: Could not locate chronos-graph project directory with .env file.");
        projectDir = process.cwd() || process.env.HOME;
      }

      // Resolve executable: prefer local venv, fallback to uv run, then uvx
      const localVenvGateway = path.join(projectDir, '.venv', 'bin', 'chronos-mcp-gateway');
      let gatewayCmd = 'uvx';
      let gatewayArgs = [
        "--quiet",
        "--from", "git+https://github.com/yohi/chronos-graph.git[all]",
        "chronos-mcp-gateway", "run"
      ];

      if (fs.existsSync(localVenvGateway) || fs.existsSync(path.join(projectDir, 'pyproject.toml'))) {
        const localBinUv = path.join(process.env.HOME, '.local', 'bin', 'uv');
        const uvPath = fs.existsSync(localBinUv) ? localBinUv : 'uv';
        gatewayCmd = uvPath;
        gatewayArgs = ["run", "chronos-mcp-gateway", "run"];
        logDebug(`Using local uv run gateway: ${gatewayCmd}`);
      } else {
        const localBinUvx = path.join(process.env.HOME, '.local', 'bin', 'uvx');
        gatewayCmd = fs.existsSync(localBinUvx) ? localBinUvx : 'uvx';
        logDebug(`Using uvx fallback gateway: ${gatewayCmd}`);
      }

      // Ensure HOME/.local/bin is in PATH for the spawned environment
      const localBinDir = path.join(process.env.HOME, '.local', 'bin');
      const currentPath = process.env.PATH || '';
      const newPath = currentPath.includes(localBinDir) ? currentPath : `${localBinDir}:${currentPath}`;

      const gatewayProc = spawn(gatewayCmd, gatewayArgs, {
        cwd: projectDir,
        detached: true,
        stdio: ['ignore', errLog, errLog],
        env: {
          ...process.env,
          ...loadedEnv,
          PATH: newPath
        }
      });
      gatewayProc.on('error', (err) => {
        logDebug(`Gateway spawn error event: ${err.message}`);
        showToast(`Gateway auto-start process encountered an error: ${err.message}`, "error");
      });
      logDebug(`Gateway spawn process initialized (using: ${gatewayCmd}) in cwd: ${projectDir}.`);
      showToast("Gateway auto-start process initialized.", "info");
      gatewayProc.unref();
    } catch (spawnError) {
      logDebug(`Gateway spawn sync exception: ${spawnError.message}`);
      showToast(`Failed to initialize gateway auto-start: ${spawnError.message}`, "error");
    }
  }).connect(9100, '127.0.0.1');
}

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

    // Handle Session Creation -> Auto Start Gateway if offline
    if (event.type === "session.created") {
      checkAndStartGateway();
    }

    // Handle Permission Asked -> Auto Reply using Gateway Evaluation (Bypasses permission.ask bug)
    if (event.type === "permission.asked") {
      const props = event.properties;
      if (props && props.id) {
        if (activeEvaluations.has(props.id)) {
          logDebug(`Duplicate permission.asked event for request ${props.id}. Skipping.`);
          return;
        }
        activeEvaluations.add(props.id);
        logDebug(`Auto-evaluating permission.asked: ${props.id} for type: ${props.permission}`);
        try {
          const projectDir = path.join(process.env.HOME, 'program', 'chronos-graph');
          const contextObj = {
            intent: "default",
            agent_id: "OpenCode",
            project: projectDir
          };
          let toolCall = null;
          const permType = props.permission;

          if (permType === "mcp" || permType === "tool") {
            toolCall = {
              tool_name: props.metadata?.tool || props.patterns?.[0] || props.id,
              tool_input: props.metadata?.arguments || {},
              context: contextObj
            };
          } else if (permType === "command" || permType === "bash" || permType === "execute") {
            toolCall = {
              tool_name: "bash",
              tool_input: {
                command: props.metadata?.command || props.patterns?.[0] || ""
              },
              context: contextObj
            };
          } else {
            // Other system permissions (read, edit, etc.)
            toolCall = {
              tool_name: permType,
              tool_input: {
                path: props.patterns?.[0] || ""
              },
              context: contextObj
            };
          }

          if (toolCall) {
            logDebug(`Evaluating tool via event hook: ${toolCall.tool_name}`);
            logDebug(`toolCall payload: ${JSON.stringify(toolCall)}`);
            const result = await evaluateTool(toolCall);
            if (result.status !== 'allow') {
              if (result.decision === 'ask' && result.ask_message) {
                showToast(`Evaluation Check: ${result.ask_message}`, "warning");
              } else if (result.reason) {
                showToast(`Permission denied: ${result.reason}`, "error");
              }
            }
            
            // Dynamically resolve permission API (clientObj.permission or globalInput.sdk.permission)
            let permissionApi = null;
            if (globalInput) {
              try {
                logDebug(`globalInput ownProperties: ${Object.getOwnPropertyNames(globalInput).join(", ")}`);
                if (globalInput.sdk) {
                  logDebug(`globalInput.sdk ownProperties: ${Object.getOwnPropertyNames(globalInput.sdk).join(", ")}`);
                }
              } catch (e) {}
              permissionApi = globalInput.permission || globalInput.sdk?.permission;
            }
            const clientObj = globalClient || event.client;
            if (clientObj) {
              try {
                logDebug(`clientObj ownProperties: ${Object.getOwnPropertyNames(clientObj).join(", ")}`);
                if (clientObj.sdk) {
                  logDebug(`clientObj.sdk ownProperties: ${Object.getOwnPropertyNames(clientObj.sdk).join(", ")}`);
                }
                if (clientObj._client) {
                  logDebug(`clientObj._client ownProperties: ${Object.getOwnPropertyNames(clientObj._client).join(", ")}`);
                }
              } catch (e) {}
            }
            if (!permissionApi && clientObj) {
              permissionApi = clientObj.permission || clientObj.sdk?.permission;
            }

            const replyVal = result.status === 'allow' ? "once" : "reject";

            // Prioritize official SDK permissionApi over raw HTTP client calls
            let permissionApi = null;
            if (globalInput) {
              permissionApi = globalInput.permission || globalInput.sdk?.permission;
            }
            const clientObj = globalClient || event.client;
            if (!permissionApi && clientObj) {
              permissionApi = clientObj.permission || clientObj.sdk?.permission;
            }

            if (permissionApi) {
              logDebug(`Sending reply via SDK API: ${replyVal} for request ${props.id}`);
              await permissionApi.reply({ requestID: props.id, reply: replyVal, directory: projectDir });
              logDebug(`SDK API reply successful for request ${props.id}`);
            } else if (clientObj && clientObj._client) {
              logDebug(`Sending direct API reply (fallback): ${replyVal} for request ${props.id}`);
              try {
                await clientObj._client.post({
                  url: `/permission/${props.id}/reply`,
                  payload: {
                    reply: replyVal,
                    directory: projectDir
                  }
                });
                logDebug(`Direct API reply successful for request ${props.id}`);
              } catch (apiErr) {
                logDebug(`Direct API reply failed on permission endpoint: ${apiErr.message}. Trying permissions endpoint...`);
                try {
                  await clientObj._client.post({
                    url: `/permissions/${props.id}/reply`,
                    payload: {
                      reply: replyVal,
                      directory: projectDir
                    }
                  });
                  logDebug(`Direct API reply successful (plural) for request ${props.id}`);
                } catch (apiErr2) {
                  logDebug(`Both direct API reply endpoints failed: ${apiErr2.message}`);
                }
              }
            } else {
              logDebug("Cannot reply: neither clientObj._client nor permission API is found.");
            }
          }
        } catch (err) {
          logDebug(`Auto-evaluation error for ${props.id}: ${err.message}. Defaulting to deny for safety.`);
          showToast(`Evaluation System Error: ${err.message}`, "error");
          const clientObj = globalClient || event.client;
          const projectDir = globalDirectory || process.cwd();
          if (clientObj && clientObj._client) {
            try {
              await clientObj._client.post({
                url: "/permission/{requestID}/reply",
                params: { requestID: props.id },
                payload: {
                  reply: "reject",
                  directory: projectDir
                }
              });
            } catch (e) {
              try {
                await clientObj._client.post({
                  url: "/permissions/{requestID}/reply",
                  params: { requestID: props.id },
                  payload: {
                    reply: "reject",
                    directory: projectDir
                  }
                });
              } catch (e2) {}
            }
          } else {
            let permissionApi = null;
            if (globalInput) {
              permissionApi = globalInput.permission || globalInput.sdk?.permission;
            }
            if (!permissionApi && clientObj) {
              permissionApi = clientObj.permission || clientObj.sdk?.permission;
            }
            if (permissionApi) {
              await permissionApi.reply({ requestID: props.id, reply: "reject", directory: projectDir }).catch(() => {});
            }
          }
        } finally {
          activeEvaluations.delete(props.id);
        }
      }
    }

    // Handle Session Idle -> Auto Ingest Log
    if (event.type === "session.idle") {
      const sessionId = event.properties?.sessionID;
      if (!sessionId) return;

      logDebug(`Ingesting log for session: ${sessionId}`);
      
      // If we don't have initialized client, try to resolve it from event context if available
      const clientObj = globalClient || event.client;
      if (!clientObj) {
        logDebug("Cannot ingest: client object is not initialized.");
        return;
      }

      const messages = await clientObj.session.messages({ path: { id: sessionId } });
      logDebug(`Raw messages.data: ${JSON.stringify(messages.data)}`);
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

      // Search for the project directory containing .env
      const searchDirs = [
        globalDirectory,
        process.cwd(),
        process.env.PWD,
        path.join(process.env.HOME, 'program', 'chronos-graph'),
        path.join(process.env.HOME, 'chronos-graph')
      ].filter(Boolean);

      let projectDir = path.join(__dirname, "..", "..");
      const dirVal = globalDirectory || event.directory;
      if (dirVal && typeof dirVal === 'string') {
        const resolved = path.resolve(dirVal);
        if (resolved.startsWith('/') && !resolved.includes('..')) {
          projectDir = resolved;
        }
      }

      let loadedEnv = {};
      for (const dir of searchDirs) {
        const envPath = path.join(dir, '.env');
        if (fs.existsSync(envPath)) {
          const tempEnv = loadEnvFile(envPath);
          if (tempEnv.STORAGE_BACKEND || tempEnv.MCP_GATEWAY_PORT || tempEnv.CHRONOS_INGESTION_MODE) {
            projectDir = dir;
            loadedEnv = tempEnv;
            break;
          }
        }
      }

      const script = path.join(projectDir, "scripts", "agent_turn_hook.py");

      // Resolve python executable path: prefer .venv/bin/python, fallback to uv, then default 'python'
      const localVenvPython = path.join(projectDir, '.venv', 'bin', 'python');
      let pythonPath = 'python';
      let spawnArgs = [script];

      if (fs.existsSync(localVenvPython)) {
        pythonPath = localVenvPython;
        logDebug(`Using venv python for hook: ${pythonPath}`);
      } else {
        const localBinUv = path.join(process.env.HOME, '.local', 'bin', 'uv');
        const uvPath = fs.existsSync(localBinUv) ? localBinUv : 'uv';
        pythonPath = uvPath;
        spawnArgs = ["run", "python", script];
        logDebug(`Using uv python fallback for hook: ${pythonPath} run python`);
      }

      // Ensure HOME/.local/bin is in PATH for python/uv resolution
      const localBinDir = path.join(process.env.HOME, '.local', 'bin');
      const currentPath = process.env.PATH || '';
      const newPath = currentPath.includes(localBinDir) ? currentPath : `${localBinDir}:${currentPath}`;

      try {
        const errLogPath = path.join(process.env.HOME, '.config', 'opencode', 'gateway-spawn-error.log');
        const errLog = fs.openSync(errLogPath, 'a');

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
          const debugEnabled = process.env.DEBUG === 'true' || process.env.DEBUG === '1';
          if (debugEnabled) {
            showToast(`Failed to spawn memory ingestion: ${err.message}`, "error");
          }
        });
        child.on("close", (code) => {
          const debugEnabled = process.env.DEBUG === 'true' || process.env.DEBUG === '1';
          if (code === 0) {
            logDebug("Log ingestion process completed successfully.");
            if (debugEnabled) {
              showToast("Conversation memory saved successfully.", "success");
            }
          } else {
            logDebug(`Log ingestion process exited with code ${code}.`);
            if (debugEnabled) {
              showToast(`Failed to save conversation memory (code ${code}).`, "error");
            }
          }
        });
        child.stdin.write(text, "utf-8");
        child.stdin.end();
        child.unref();
        logDebug("Log ingestion process spawned successfully.");
      } catch (spawnError) {
        logDebug(`Failed to spawn agent_turn_hook.py: ${spawnError.message}`);
        const debugEnabled = process.env.DEBUG === 'true' || process.env.DEBUG === '1';
        if (debugEnabled) {
          showToast(`Failed to initialize memory ingestion: ${spawnError.message}`, "error");
        }
      }
    }
  } catch (eventError) {
    logDebug(`Error inside event handler: ${eventError.message}`);
  }
}


const permissionAskHook = async (permission, output) => {
  logDebug(`permission.ask hook invoked (standalone/direct) for type: ${permission.type}`);
  try {
    let toolCall = null;
    if (permission.type === "mcp" || permission.type === "tool") {
      toolCall = {
        tool_name: permission.metadata?.tool || permission.pattern || permission.id,
        tool_input: permission.metadata?.arguments || {}
      };
    } else if (permission.type === "command" || permission.type === "bash" || permission.type === "execute") {
      toolCall = {
        tool_name: "bash",
        tool_input: {
          command: permission.metadata?.command || permission.pattern || ""
        }
      };
    } else {
      // Other system permissions (read, edit, etc.)
      toolCall = {
        tool_name: permission.type,
        tool_input: {
          path: permission.pattern || ""
        }
      };
    }

    if (toolCall) {
      logDebug(`Evaluating tool (direct hook): ${toolCall.tool_name}`);
      const result = await evaluateTool(toolCall);
      if (result.status === 'allow') {
        output.status = 'allow';
      } else {
        output.status = 'deny';
        output.reason = result.reason;
        logDebug(`Permission denied: ${result.reason}`);
        if (result.decision === 'ask' && result.ask_message) {
          showToast(`Evaluation Check: ${result.ask_message}`, "warning");
        } else if (result.reason) {
          showToast(`Permission denied: ${result.reason}`, "error");
        }
      }
    }
  } catch (err) {
    logDebug(`Evaluation error: ${err.message}. Defaulting to deny for safety.`);
    showToast(`Evaluation System Error: ${err.message}`, "error");
    output.status = 'deny';
    output.reason = `Security gate evaluation error: ${err.message}`;
  }
};

// --------------------------------------------------------------------------
// OpenCode Plugin Specification compliant export
// --------------------------------------------------------------------------
module.exports = {
  id: "@yohi/opencode-plugin-chronos-gate",
  "permission.ask": permissionAskHook,
  server: async (input, options) => {
    logDebug("Plugin activation function (init) called.");
    if (input) {
      globalClient = input.client;
      globalDirectory = input.directory;
      globalInput = input;
    }

    // Proactively check and start Gateway on plugin initialization
    try {
      checkAndStartGateway();
    } catch (err) {
      logDebug(`Error starting gateway on init: ${err.message}`);
    }

    const hooksObj = {
      // Session event lifecycle hook
      event: async ({ event }) => {
        const ev = event.event || event;
        await handleEvent(ev);
      },

      // Security Evaluation Gate hook
      "permission.ask": async (permission, output) => {
        logDebug(`permission.ask hook invoked (nested in server) for type: ${permission.type}`);
        return permissionAskHook(permission, output);
      }
    };

    // Support both w[G] and w.hooks[G] lookups
    hooksObj.hooks = hooksObj;

    return hooksObj;
  }
};

