// Thin fetch wrapper over the hub REST API. Errors carry the hub's machine-readable code.

export class ApiError extends Error {
  constructor(status, code, message) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

async function call(method, path, body) {
  const resp = await fetch(path, {
    method,
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (resp.ok) return resp.json();
  let error = { code: "http_error", message: `${resp.status} ${resp.statusText}` };
  try {
    error = (await resp.json()).error ?? error;
  } catch { /* non-JSON error body */ }
  throw new ApiError(resp.status, error.code, error.message);
}

export const api = {
  agents: () => call("GET", "/api/agents"),
  createAgent: (payload) => call("POST", "/api/agents", payload),
  removeAgent: (name) => call("DELETE", `/api/agents/${encodeURIComponent(name)}`),
  lines: () => call("GET", "/api/lines"),
  line: (id) => call("GET", `/api/lines/${id}`),
  lineMessages: (id, after) =>
    call("GET", `/api/lines/${id}/messages${after ? `?after=${after}` : ""}`),
  operatorSend: (to, body) => call("POST", "/api/operator/send", { to, body }),
  operatorInbox: () => call("GET", "/api/operator/inbox"),
  addNote: (lineId, target, body) =>
    call("POST", `/api/lines/${lineId}/note`, { target, body }),
  pending: () => call("GET", "/api/gate/pending"),
  decide: (messageId, verdict, note) =>
    call("POST", `/api/gate/${messageId}`, { verdict, note: note || null }),
  setMode: (lineId, mode) => call("POST", `/api/lines/${lineId}/mode`, { mode }),
  release: (lineId) => call("POST", `/api/lines/${lineId}/release`),
};
