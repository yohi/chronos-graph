const { spawn } = require('child_process');
const path = require('path');

async function OnBeforeToolExecute(toolCall) {
  return new Promise((resolve, reject) => {
    const policyPath = process.env.CHRONOS_EVALUATOR_POLICY_PATH || path.join(process.env.HOME, '.config', 'opencode', 'intents.yaml');

    const proc = spawn('uvx', [
      '--quiet',
      '--from', 'context-store-mcp[all] @ git+https://github.com/yohi/chronos-graph.git',
      'chronos-mcp-gateway', 'evaluate', '--json-io',
      '--policy-path', policyPath
    ]);

    const timeout = setTimeout(() => {
      proc.kill();
      reject(new Error('Evaluation timed out after 10000ms'));
    }, 10000);

    proc.on('error', (err) => {
      clearTimeout(timeout);
      reject(err);
    });

    proc.stdin.write(JSON.stringify(toolCall));
    proc.stdin.end();

    let output = '';
    const MAX_BUFFER = 65536;
    proc.stdout.on('data', (data) => {
      if (output.length + data.length > MAX_BUFFER) {
        clearTimeout(timeout);
        proc.kill();
        reject(new Error('Evaluation output buffer exceeded limit'));
        return;
      }
      output += data;
    });
    
    proc.on('close', (code) => {
      clearTimeout(timeout);
      if (code !== 0) {
        return reject(new Error(`Evaluation failed with exit code ${code}. Output: ${output}`));
      }
      
      let result;
      try {
        result = JSON.parse(output);
      } catch (parseError) {
        return reject(new Error(`Failed to parse evaluation output as JSON. Code: ${code}. Output: ${output}. Error: ${parseError.message}`));
      }
      
      if (result.decision === 'allow') {
        resolve({ status: 'allow' });
      } else {
        resolve({ status: 'deny', reason: result.reason });
      }
    });
  });
}

const ChronosTurnEnd = async ({ client, directory }) => {
  return {
    event: async ({ event }) => {
      if (event.type !== "session.idle") return;
      const sessionId = event.properties?.sessionID;
      if (!sessionId) return;

      const messages = await client.session.messages.list({ path: { id: sessionId } });
      const text = messages.data
        .map((m) => {
          const parts = (m.parts ?? [])
            .map((p) => p.type === "text" ? p.text : "")
            .filter(Boolean)
            .join("\n");
          return `${m.role}: ${parts}`;
        })
        .join("\n\n");

      const baseDir = directory || '/home/y_ohi/program/chronos-graph';
      const script = path.join(baseDir, "scripts", "agent_turn_hook.py");
      const child = spawn("python", [script], {
        detached: true,
        stdio: ["pipe", "ignore", "ignore"],
        env: { ...process.env },
      });
      child.stdin.write(text, "utf-8");
      child.stdin.end();
      child.unref();
    },
  };
};

module.exports = { OnBeforeToolExecute, ChronosTurnEnd };
