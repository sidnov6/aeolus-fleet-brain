// AEOLUS API client.
// Uses the live FastAPI backend when reachable; otherwise falls back to baked
// JSON snapshots (public/api-static/) with client-side mutations, so the
// statically-deployed demo (e.g. on Vercel) stays fully interactive.

const LIVE = "/api";
const STATIC = "/api-static";

let _mode = null;                       // 'live' | 'static'
const overrides = { decisions: {}, kill: null };
let _staticApprovals = null;

async function getJSON(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url} -> ${r.status}`);
  return r.json();
}

async function detect() {
  if (_mode) return _mode;
  try {
    const r = await fetch(LIVE + "/health", { signal: AbortSignal.timeout?.(2500) });
    _mode = r.ok ? "live" : "static";
  } catch {
    _mode = "static";
  }
  return _mode;
}

async function postLive(path, body) {
  const r = await fetch(LIVE + path, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  if (!r.ok) throw new Error((await r.text()) || `${path} -> ${r.status}`);
  return r.json();
}

// ---- static-mode helpers ----
async function loadStaticApprovals() {
  if (!_staticApprovals) _staticApprovals = await getJSON(`${STATIC}/approvals.json`);
  return JSON.parse(JSON.stringify(_staticApprovals));
}
function applyDecisions(appr) {
  const queue = appr.queue.map((q) => {
    const d = overrides.decisions[q.id];
    return d ? { ...q, status: d.status, approved_by: d.approver } : q;
  });
  const realized = queue
    .filter((q) => q.status === "approved")
    .reduce((s, q) => s + (q.value_protected_eur || 0), 0);
  return {
    ...appr, queue,
    realized_value_protected_eur: Math.round(realized * 10) / 10,
    kill_switch: overrides.kill ?? appr.kill_switch,
  };
}
function syntheticAudit(base) {
  const extra = Object.entries(overrides.decisions).map(([id, d]) => ({
    timestamp: new Date().toISOString(),
    event_type: d.status === "approved" ? "ACTION_APPROVED" : "ACTION_REJECTED",
    payload: { id, approver: d.approver, value_protected_eur: d.value },
    hash: "client-" + id,
  }));
  const entries = [...(base.entries || []), ...extra];
  return { entries, verification: { valid: true, count: entries.length } };
}

// ---- public API ----
export const api = {
  async health() {
    return (await detect()) === "live" ? getJSON(LIVE + "/health") : getJSON(`${STATIC}/health.json`);
  },
  async fleet() {
    if ((await detect()) === "live") return getJSON(LIVE + "/fleet");
    const [fleet, appr] = await Promise.all([getJSON(`${STATIC}/fleet.json`), loadStaticApprovals()]);
    const applied = applyDecisions(appr);
    return { ...fleet, realized_value_protected_eur: applied.realized_value_protected_eur,
             kill_switch: applied.kill_switch };
  },
  async incident(tid) {
    return (await detect()) === "live"
      ? getJSON(`${LIVE}/incident/${tid}`)
      : getJSON(`${STATIC}/incident/${tid}.json`);
  },
  async approvals() {
    if ((await detect()) === "live") return getJSON(LIVE + "/approvals");
    return applyDecisions(await loadStaticApprovals());
  },
  async audit() {
    if ((await detect()) === "live") return getJSON(LIVE + "/audit");
    return syntheticAudit(await getJSON(`${STATIC}/audit.json`));
  },
  async decide(id, approve, note) {
    if ((await detect()) === "live")
      return postLive(`/approvals/${id}/decide`, { approve, approver: "ops-director", note });
    const appr = await loadStaticApprovals();
    const item = appr.queue.find((q) => q.id === id);
    overrides.decisions[id] = { status: approve ? "approved" : "rejected",
      approver: "ops-director", value: item?.value_protected_eur || 0 };
    return applyDecisions(appr);
  },
  async killSwitch(active) {
    if ((await detect()) === "live") return postLive("/kill-switch", { active });
    overrides.kill = active;
    return { kill_switch: active };
  },
};
