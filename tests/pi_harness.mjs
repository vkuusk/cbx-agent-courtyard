// Test harness for the pi adapter extension (item 36, D32): loads the rendered
// extension with a stub `pi` object and runs it against a real hub, so the tests
// exercise the exact file install writes. Emits NDJSON events on stdout
// (tool_registered, started, sendMessage, tool_result, tool_error, shutdown) and
// accepts NDJSON commands on stdin: {"call": <tool>, "params": {...}} executes a
// registered tool; {"cmd": "shutdown"} fires session_shutdown and exits.
import { createInterface } from "node:readline";

const { default: factory } = await import(`file://${process.env.COURTYARD_EXT}`);

const handlers = new Map();
const tools = new Map();
const commands = new Map();
const out = (obj) => process.stdout.write(JSON.stringify(obj) + "\n");

const ctx = {
  hasUI: true,
  ui: {
    setStatus(key, text) {
      out({ event: "setStatus", key, text });
    },
    notify(text, level) {
      out({ event: "notify", text, level });
    },
  },
};

const pi = {
  on(event, handler) {
    handlers.set(event, handler);
  },
  registerTool(def) {
    tools.set(def.name, def);
    out({ event: "tool_registered", name: def.name });
  },
  registerCommand(name, def) {
    commands.set(name, def);
    out({ event: "command_registered", name });
  },
  registerMessageRenderer(customType) {
    out({ event: "renderer_registered", customType });
  },
  sendMessage(message, options) {
    out({ event: "sendMessage", message, options });
  },
  sendUserMessage(content, options) {
    out({ event: "sendUserMessage", content, options });
  },
};

factory(pi);
await handlers.get("session_start")?.({}, ctx);
out({ event: "started" });

const rl = createInterface({ input: process.stdin });
for await (const line of rl) {
  if (!line.trim()) continue;
  const cmd = JSON.parse(line);
  if (cmd.cmd === "shutdown") {
    await handlers.get("session_shutdown")?.({}, ctx);
    out({ event: "shutdown" });
    process.exit(0);
  }
  if (cmd.command) {
    const def = commands.get(cmd.command);
    if (def) await def.handler(cmd.args || "", ctx);
    else out({ event: "tool_error", name: cmd.command, text: "unknown command" });
    continue;
  }
  const tool = tools.get(cmd.call);
  if (!tool) {
    out({ event: "tool_error", name: cmd.call, text: "unknown tool" });
    continue;
  }
  try {
    const result = await tool.execute("tc-1", cmd.params || {});
    out({ event: "tool_result", name: cmd.call, text: result.content[0].text });
  } catch (exc) {
    out({ event: "tool_error", name: cmd.call, text: String(exc.message || exc) });
  }
}
