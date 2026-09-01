/**
 * Written by the courtyard for agent '__COURTYARD_AGENT_NAME__' — the pi adapter
 * (design §7.1/§7.3, item 36). One extension per agent, regenerated on every
 * install. Do NOT commit this file: it carries the agent's hub token (chmod 600).
 *
 * It is three things at once, mirroring the Claude Code adapter:
 *  - a channel: the hub pushes each message to a local endpoint, and this
 *    extension injects it into the session via pi.sendMessage (triggerTurn wakes
 *    an idle session; deliverAs "followUp" queues politely on a busy one);
 *  - a toolbox: courtyard_send / courtyard_inbox / courtyard_peers /
 *    courtyard_ack, registered natively;
 *  - a hub adapter: attaches with a channel endpoint, heartbeats, detaches at
 *    session end. Attach retries forever, so hub/agent launch order is free.
 *
 * Deliberately thin (D14): the authority envelope and the peers listing arrive
 * rendered by the hub and are forwarded verbatim, never re-derived here.
 */
import { createServer } from "node:http";
import { randomBytes } from "node:crypto";
import { appendFileSync, mkdirSync } from "node:fs";

const HUB_URL = "__COURTYARD_HUB_URL__";
const AGENT_NAME = "__COURTYARD_AGENT_NAME__";
const TOKEN = "__COURTYARD_TOKEN__";
const HEARTBEAT_SECONDS = 5; // match the hub (D23/D28)
const LOG_DIR = ".courtyard"; // runtime artifacts only; pi runs in the project dir

export default function (pi) {
  const channelToken = randomBytes(24).toString("base64url");
  let server = null;
  let endpoint = null;
  let beatTimer = null;
  let stopped = false;
  let ui = null; // captured from session_start; every use is best-effort
  let hubDown = false;

  // The delivery trail (`.courtyard/adapter.log`): the same ground truth the Claude
  // Code adapter keeps on stderr — what cracked the silent-loss incidents there.
  function log(line) {
    try {
      appendFileSync(`${LOG_DIR}/adapter.log`, `${new Date().toISOString()} ${line}\n`);
    } catch {
      /* logging must never break delivery */
    }
  }

  // Footer status: the pi equivalent of the claude-code status line (item 2), live.
  function status(text) {
    try {
      if (ui) ui.setStatus("courtyard", `⏺ ${AGENT_NAME} · courtyard · ${text}`);
    } catch {
      /* no UI in json/print modes */
    }
  }

  function notify(text, level) {
    try {
      if (ui) ui.notify(text, level);
    } catch {
      /* no UI in json/print modes */
    }
  }

  async function api(method, path, body) {
    const resp = await fetch(HUB_URL + path, {
      method,
      headers: {
        Authorization: `Bearer ${TOKEN}`,
        ...(body ? { "Content-Type": "application/json" } : {}),
      },
      body: body ? JSON.stringify(body) : undefined,
    });
    const data = resp.status === 204 ? null : await resp.json().catch(() => null);
    if (!resp.ok) {
      const detail = (data && data.error) || {};
      // Surfaced verbatim: turn violations and gate errors are written to be
      // read by the model, and softening them would defeat the backpressure.
      const err = new Error(
        `The courtyard hub refused: [${detail.code || "http_error"}] ${detail.message || resp.statusText}`,
      );
      err.code = detail.code;
      throw err;
    }
    return data;
  }

  const present = (message) => (message && message.rendered) || (message && message.body) || "";

  function deliver(message) {
    // The hub-rendered envelope, injected as a courtyard message — never as the
    // user (item 36: a peer's message must not impersonate the operator).
    pi.sendMessage(
      {
        customType: "courtyard",
        content: present(message),
        display: true,
        details: {
          from: (message && message.sender_name) || "hub",
          kind: message && message.kind,
          seq: message && message.seq,
        },
      },
      { triggerTurn: true, deliverAs: "followUp" },
    );
    log(`delivered kind=${message && message.kind} seq=${message && message.seq} id=${message && message.id}`);
  }

  async function attach() {
    return api("POST", `/api/agents/${AGENT_NAME}/attach`, {
      endpoint,
      channel_token: channelToken,
      channel_flag: "present", // this extension IS the channel; there is no flag to forget
    });
  }

  async function collectQueued() {
    const messages = await api("GET", `/api/agents/${AGENT_NAME}/inbox`);
    for (const message of messages) deliver(message);
  }

  function startServer() {
    return new Promise((resolve) => {
      server = createServer((req, res) => {
        if (req.method !== "POST" || req.headers["x-courtyard-channel-token"] !== channelToken) {
          res.writeHead(401, { "Content-Type": "application/json" });
          res.end('{"error":"bad channel token"}');
          return;
        }
        let raw = "";
        req.on("data", (chunk) => (raw += chunk));
        req.on("end", () => {
          try {
            deliver(JSON.parse(raw).message);
          } catch (exc) {
            res.writeHead(500, { "Content-Type": "application/json" });
            res.end(JSON.stringify({ error: String(exc) }));
            return;
          }
          res.writeHead(200, { "Content-Type": "application/json" });
          res.end('{"ok":true}');
        });
      });
      server.listen(0, "127.0.0.1", () => {
        endpoint = `http://127.0.0.1:${server.address().port}/`;
        resolve();
      });
    });
  }

  async function boot() {
    try {
      mkdirSync(LOG_DIR, { recursive: true });
    } catch {
      /* read-only dir: the log is optional */
    }
    await startServer();
    status("connecting…");
    // Attach retries forever, every 2 s (feedback item 12): the operator's habit
    // is agents first, hub second, and a session must never need relaunching
    // just because it won the race.
    let attempt = 0;
    while (!stopped) {
      try {
        await attach();
        break;
      } catch {
        attempt += 1;
        if (attempt === 1) {
          console.error("courtyard: hub not reachable yet, retrying every 2s");
          status("hub unreachable");
        }
        await new Promise((r) => setTimeout(r, 2000));
      }
    }
    if (stopped) return;
    status("connected");
    log(`attached as ${AGENT_NAME} (endpoint ${endpoint})`);
    beatTimer = setInterval(async () => {
      try {
        const beat = await api("POST", `/api/agents/${AGENT_NAME}/heartbeat`);
        if (hubDown) {
          hubDown = false;
          status("connected");
          notify("courtyard: hub connection restored", "info");
          log("hub connection restored");
        }
        if (beat && beat.queued) await collectQueued(); // a push failed; the pull path recovers it
      } catch (exc) {
        if (exc.code === "not_attached") {
          // hub restarted, or our channel was replaced — re-attach
          try {
            await attach();
          } catch {
            /* next beat retries */
          }
        } else if (!hubDown) {
          hubDown = true;
          status("hub unreachable");
          notify("courtyard: hub connection lost", "warning");
          log("hub connection lost");
        }
      }
    }, HEARTBEAT_SECONDS * 1000);
  }

  pi.on("session_start", async (_event, ctx) => {
    ui = ctx && ctx.ui ? ctx.ui : null;
    boot().catch((exc) => console.error(`courtyard: adapter failed to start: ${exc}`));
  });

  pi.on("session_shutdown", async () => {
    stopped = true;
    if (beatTimer) clearInterval(beatTimer);
    if (server) server.close();
    try {
      await api("POST", `/api/agents/${AGENT_NAME}/detach`);
      log("detached");
    } catch {
      /* the liveness sweep covers an unclean exit */
    }
  });

  // /courtyard in the TUI: connection state and queue at a glance, no LLM involved.
  pi.registerCommand("courtyard", {
    description: "Show this agent's courtyard connection and queued messages",
    handler: async (_args, ctx) => {
      try {
        const beat = await api("POST", `/api/agents/${AGENT_NAME}/heartbeat`);
        ctx.ui.notify(
          `courtyard: connected as ${AGENT_NAME} · ${beat.queued || 0} queued`,
          "info",
        );
      } catch (exc) {
        ctx.ui.notify(`courtyard: hub unreachable (${exc.message || exc})`, "warning");
      }
    },
  });

  // TUI rendering of courtyard messages: display-only — the model receives the
  // exact envelope either way. pi-tui resolves only inside pi; anywhere else
  // (the bare-node test harness) the import fails and default rendering stands.
  (async () => {
    try {
      const { Box, Text } = await import("@earendil-works/pi-tui");
      pi.registerMessageRenderer("courtyard", (message, { expanded, outputPad }, theme) => {
        const details = message.details || {};
        const head = theme.fg(
          "success",
          `✉ courtyard · from ${details.from || "hub"} · ${details.kind || "message"}`,
        );
        const body = expanded
          ? message.content
          : message.content.split("\n").slice(0, 12).join("\n");
        const box = new Box(outputPad, 1, (t) => theme.bg("customMessageBg", t));
        box.addChild(new Text(`${head}\n${body}`, 0, 0));
        return box;
      });
    } catch {
      /* not running inside pi: keep the default rendering */
    }
  })();

  // -- the toolbox (same names and texts as the Claude Code adapter) ---------------

  pi.registerTool({
    name: "courtyard_send",
    label: "Courtyard Send",
    description:
      "Send a message to another agent on the courtyard board — the ONLY way " +
      "anything you say reaches them (terminal output does not). Give only the " +
      "recipient and the text — the hub composes everything else. Say what the " +
      "task needs and no more: trailing offers and side questions each cost the " +
      "recipient a full exchange.",
    promptGuidelines: [
      "Use courtyard_send to answer any courtyard message; text printed in the terminal never reaches the sender.",
    ],
    parameters: {
      type: "object",
      properties: {
        to: { type: "string", description: "the recipient agent's name (see courtyard_peers)" },
        message: { type: "string", description: "what you want to say" },
      },
      required: ["to", "message"],
    },
    async execute(_toolCallId, params) {
      const to = (params.to || "").trim();
      const body = params.message || "";
      if (!to || !body.trim()) throw new Error("both `to` and `message` are required");
      const message = await api("POST", "/api/lines/send", { to, body });
      let text;
      if (message.status === "pending_gate") {
        text =
          `Held at the gate for the operator's approval (seq ${message.seq}); it has ` +
          `not reached ${to} yet. Wait — you will be told if it is returned or dropped.`;
      } else if (message.status === "delivered") {
        text =
          `Delivered to ${to} (seq ${message.seq}). This line is now awaiting their ` +
          `reply — do not send to ${to} again until they answer.`;
      } else {
        text =
          `Accepted (seq ${message.seq}); ${to} is not connected right now, so the hub ` +
          `will hand it over when they attach. The line is awaiting their reply.`;
      }
      return { content: [{ type: "text", text }], details: {} };
    },
  });

  pi.registerTool({
    name: "courtyard_inbox",
    label: "Courtyard Inbox",
    description:
      "Collect your unread courtyard messages. Messages normally arrive on their " +
      "own; use this to catch up after a restart, or when you have been told " +
      "something is waiting. Reading them marks them as delivered.",
    parameters: { type: "object", properties: {} },
    async execute() {
      const messages = await api("GET", `/api/agents/${AGENT_NAME}/inbox`);
      if (!messages.length) {
        return { content: [{ type: "text", text: "No unread courtyard messages." }], details: {} };
      }
      return {
        content: [{ type: "text", text: messages.map(present).join("\n") }],
        details: {},
      };
    },
  });

  pi.registerTool({
    name: "courtyard_peers",
    label: "Courtyard Peers",
    description:
      "List the agents on the courtyard board: name, what each one is for, what it " +
      "owns, and whether it is connected right now. Use it to decide whom to ask.",
    parameters: { type: "object", properties: {} },
    async execute() {
      const peers = await api("GET", `/api/agents/${AGENT_NAME}/peers`);
      return { content: [{ type: "text", text: peers.rendered }], details: {} };
    },
  });

  pi.registerTool({
    name: "courtyard_ack",
    label: "Courtyard Ack",
    description:
      "Confirm a courtyard delivery check. Call this only when a hub delivery-check " +
      "message hands you a token; the single call completes the check.",
    parameters: {
      type: "object",
      properties: {
        token: { type: "string", description: "the token quoted in the delivery-check message" },
      },
      required: ["token"],
    },
    async execute(_toolCallId, params) {
      const token = (params.token || "").trim();
      if (!token) throw new Error("`token` is required");
      const result = await api("POST", `/api/agents/${AGENT_NAME}/ack`, { token });
      const text = result.ok
        ? "Delivery confirmed to the hub. Nothing further is needed."
        : "That check is no longer open (it may have timed out or been superseded); " +
          "nothing further is needed.";
      return { content: [{ type: "text", text }], details: {} };
    },
  });
}
