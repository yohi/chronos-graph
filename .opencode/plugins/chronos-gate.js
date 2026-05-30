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

    proc.stdin.write(JSON.stringify(toolCall));
    proc.stdin.end();

    let output = '';
    proc.stdout.on('data', (data) => { output += data; });
    
    proc.on('close', (code) => {
      if (code !== 0) return reject(new Error('Evaluation failed'));
      const result = JSON.parse(output);
      
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

      const script = path.join('/home/y_ohi/program/chronos-graph', "scripts/agent_turn_hook.py");
      const child = spawn("python", [script, "--content", text], {
        detached: true,
        stdio: "ignore",
        env: { ...process.env },
      });
      child.unref();
    },
  };
};

module.exports = { OnBeforeToolExecute, ChronosTurnEnd };
