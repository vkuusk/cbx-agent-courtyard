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
  config: () => call("GET", "/api/config"),
  restartHub: () => call("POST", "/api/hub/restart"),
  envelope: () => call("GET", "/api/envelope"),
  fsDirs: (path) => call("GET", `/api/fs/dirs${path ? `?path=${encodeURIComponent(path)}` : ""}`),
  pickDir: (prompt) => call("POST", "/api/fs/pick-dir", { prompt }),
  agents: () => call("GET", "/api/agents"),
  createAgent: (payload) => call("POST", "/api/agents", payload),
  removeAgent: (name) => call("DELETE", `/api/agents/${encodeURIComponent(name)}`),
  patchAgent: (name, patch) => call("PATCH", `/api/agents/${encodeURIComponent(name)}`, patch),
  uninstallAgent: (name) => call("POST", `/api/agents/${encodeURIComponent(name)}/uninstall`, {}),
  installAgent: (name, workdir) =>
    call("POST", `/api/agents/${encodeURIComponent(name)}/install`, { workdir }),
  agentToken: (name) => call("GET", `/api/agents/${encodeURIComponent(name)}/token`),
  verifyDelivery: (id) => call("POST", `/api/agents/${id}/verify-delivery`),
  rotateToken: (name) => call("POST", `/api/agents/${encodeURIComponent(name)}/token`),
  lines: () => call("GET", "/api/lines"),
  line: (id) => call("GET", `/api/lines/${id}`),
  lineMessages: (id, after) =>
    call("GET", `/api/lines/${id}/messages${after ? `?after=${after}` : ""}`),
  lineThreads: (id) => call("GET", `/api/lines/${id}/threads`),
  operatorSend: (to, body) => call("POST", "/api/operator/send", { to, body }),
  closeThread: (peer) => call("POST", "/api/operator/close-thread", { peer }),
  operatorInbox: () => call("GET", "/api/operator/inbox"),
  pending: () => call("GET", "/api/gate/pending"),
  decide: (messageId, verdict, note) =>
    call("POST", `/api/gate/${messageId}`, { verdict, note: note || null }),
  setMode: (lineId, mode) => call("POST", `/api/lines/${lineId}/mode`, { mode }),
  linkAgents: (a, b) => call("POST", "/api/lines", { a, b }),
  unlinkLine: (lineId) => call("POST", `/api/lines/${lineId}/unlink`),
  release: (lineId) => call("POST", `/api/lines/${lineId}/release`),
  archiveLine: (lineId) => call("POST", `/api/lines/${lineId}/archive`),
  archives: () => call("GET", "/api/archive"),
  archive: (id) => call("GET", `/api/archive/${id}`),
  deleteArchive: (id) => call("DELETE", `/api/archive/${id}`),
  archiveExportUrl: (id) => `/api/archive/${id}/export`,
  memory: (params) => call("GET", `/api/memory?${new URLSearchParams(Object.fromEntries(Object.entries(params).filter(([, v]) => v)))}`),
  memoryRecord: (id) => call("GET", `/api/memory/${id}`),
  memoryExportUrl: (params = {}) => {
    const qs = new URLSearchParams(Object.fromEntries(Object.entries(params).filter(([, v]) => v)));
    return `/api/memory/export${qs.size ? `?${qs}` : ""}`;
  },
  pendingNotes: () => call("GET", "/api/memory/pending"),
  memoryEncoder: () => call("GET", "/api/memory/encoder"),
  writeNote: (body) => call("POST", "/api/memory/notes", body),
  decideNote: (id, verdict, note) => call("POST", `/api/memory/${id}/decide`, { verdict, note }),
  shift: () => call("GET", "/api/shift"),
  shiftStart: () => call("POST", "/api/shift/start"),
  shiftResume: () => call("POST", "/api/shift/resume"),
  shiftEnd: (force) => call("POST", "/api/shift/end", { force: Boolean(force) }),
  settings: () => call("GET", "/api/settings"),
  builtinTerminals: () => call("GET", "/api/settings/terminals"),
  patchSettings: (patch) => call("PATCH", "/api/settings", patch),
  teams: () => call("GET", "/api/teams"),
  addTeam: (charterDir, name) => call("POST", "/api/teams", { charter_dir: charterDir, name: name || null }),
  reloadTeam: (id) => call("POST", `/api/teams/${id}/reload`),
  setCurrentTeam: (id) => call("POST", "/api/teams/current", { team_id: id }),
  setTeamWorkdir: (id, agent, workdir) =>
    call("POST", `/api/teams/${id}/workdirs`, { agent, workdir }),
  removeTeam: (id) => call("DELETE", `/api/teams/${id}`),
};
