// SentinelOps dashboard. No framework and no build step.
// SECURITY: telemetry-derived text (log messages, release labels, error strings) is untrusted.
// Every element is built with createElement/textContent via h(); there is no innerHTML anywhere.
"use strict";

const $ = (sel) => document.querySelector(sel);
const state = { token: sessionStorage.getItem("sentinel_token") || "", actor: localStorage.getItem("sentinel_actor") || "",
                selected: null, incidents: [], timer: null, signature: "", contracts: [] };

function h(tag, props, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (v === false || v == null) continue;
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v);
  }
  for (const kid of kids.flat(Infinity)) {
    if (kid === null || kid === undefined || kid === false) continue;
    el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return el;
}
const badge = (text, kind) => h("span", { class: `badge ${kind || text}` }, text);
const fmtTime = (iso) => (iso ? new Date(iso).toLocaleString() : "");

function setStatus(message, isError) {
  const el = $("#status");
  el.textContent = message || "";
  el.className = "status" + (isError ? " error" : "");
}

async function api(path, { method = "GET", body, actor } = {}) {
  const headers = { authorization: `Bearer ${state.token}` };
  if (body !== undefined) headers["content-type"] = "application/json";
  if (actor) headers["x-actor"] = state.actor;
  const res = await fetch(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    const code = (data && (data.error || data.detail)) || `HTTP ${res.status}`;
    const reasons = data && data.reasons ? `: ${data.reasons.join("; ")}` : "";
    throw new Error(`${typeof code === "string" ? code : JSON.stringify(code)}${reasons}`);
  }
  return data;
}

async function run(label, fn) {
  try {
    setStatus(`${label}...`);
    await fn();
    setStatus(`${label}: done`);
    await refresh(true);
  } catch (err) {
    setStatus(`${label} failed: ${err.message}`, true);
  }
}

function requireActor() {
  if (!state.actor) throw new Error("enter your name in the header first (it is recorded in the audit trail)");
}

// ---- rendering ---------------------------------------------------------------------------

function renderList() {
  const nav = $("#list");
  nav.replaceChildren();
  if (!state.incidents.length) {
    nav.append(h("p", { class: "muted" }, "No incidents. Press 'Analyze now' after traffic has been ingested."));
    return;
  }
  for (const inc of state.incidents) {
    nav.append(h("button", {
      class: "item", type: "button", "aria-current": String(inc.id === state.selected),
      onclick: () => { state.selected = inc.id; state.signature = ""; render(); },
    }, h("div", {}, badge(inc.severity), badge(inc.status)), h("div", {}, inc.title),
       h("div", { class: "note" }, fmtTime(inc.started_at))));
  }
}

function evidenceList(evidence) {
  if (!evidence.length) return h("p", { class: "note" }, "No evidence recorded.");
  return h("ul", { class: "evidence" }, evidence.map((e) => h("li", {},
    badge(e.relation), h("span", { class: "note" }, ` strength ${e.strength} | ${e.created_by} | ${e.source_refs.length} source event(s) `),
    h("div", {}, e.explanation))));
}

function hypothesisCard(h_, incident) {
  const history = h_.score_history || [];
  return h("article", { class: `card ${h_.status}` },
    h("div", { class: "row" }, h("strong", {}, h_.title), badge(h_.status), badge(`score ${h_.score}`, "neutral")),
    h("div", { class: "note" }, `Ranking heuristic ${h_.score_version}, not a probability. Next test: ${h_.next_test_id}`),
    evidenceList(h_.evidence),
    history.length ? h("details", {}, h("summary", {}, `Score history (${history.length})`),
      h("ul", { class: "evidence" }, history.map((x) => h("li", {}, `${x.score} (${x.status}) before: ${x.reason}`)))) : null);
}

function diagnosticsSection(inc) {
  const runs = inc.diagnostic_runs || [];
  return [
    h("h3", {}, "Diagnostic tests (read-only)"),
    h("div", { class: "row" },
      h("button", { type: "button", onclick: () => run("Investigation", async () => { await api(`/api/v1/incidents/${inc.id}/investigate`, { method: "POST", body: { budget: 3 } }); }) }, "Run investigation"),
      h("span", { class: "note" }, "Tries to disprove the leading cause, then re-ranks.")),
    runs.length ? h("table", {}, h("thead", {}, h("tr", {}, ...["Test", "Outcome", "Result"].map((t) => h("th", {}, t)))),
      h("tbody", {}, runs.map((r) => h("tr", {}, h("td", {}, h("code", {}, r.test_id)), h("td", {}, badge(r.outcome)), h("td", {}, r.explanation)))))
      : h("p", { class: "note" }, "No tests run yet."),
  ];
}

function contractCard(c) {
  const actions = [];
  if (c.state === "AWAITING_APPROVAL") {
    const comment = h("input", { type: "text", placeholder: "comment (optional)", maxlength: "500" });
    actions.push(comment,
      h("button", { type: "button", onclick: () => run("Approve", async () => { requireActor(); await api(`/api/v1/recovery-contracts/${c.id}/approve`, { method: "POST", actor: true, body: { decision: "approve", comment: comment.value } }); }) }, "Approve"),
      h("button", { type: "button", class: "danger", onclick: () => run("Reject", async () => { requireActor(); await api(`/api/v1/recovery-contracts/${c.id}/approve`, { method: "POST", actor: true, body: { decision: "reject", comment: comment.value } }); }) }, "Reject"));
  }
  if (c.state === "READY_FOR_ACTION")
    actions.push(h("button", { type: "button", onclick: () => run("Execute", async () => { requireActor(); await api(`/api/v1/recovery-contracts/${c.id}/execute`, { method: "POST", actor: true }); }) }, "Execute action"));
  if (c.state === "VERIFYING")
    actions.push(h("button", { type: "button", onclick: () => run("Verify", async () => { requireActor(); const r = await api(`/api/v1/recovery-contracts/${c.id}/verify`, { method: "POST", actor: true }); setStatus(`Verification: ${r.outcome}. ${r.reason}`); }) }, "Check verification"));

  const win = c.contract.verification_window;
  const pol = c.contract.policy;
  return h("article", { class: "card" },
    h("div", { class: "row" }, h("strong", {}, c.action_template), badge(c.state), badge(c.outcome === "pending" ? "outcome pending" : c.outcome, c.outcome)),
    h("div", { class: "note" }, `Environment ${c.environment}. Proposed by ${c.proposed_by}. Policy ${pol.version}: blast radius ${pol.blast_radius.risk_label}`
      + (pol.blast_radius.dependents.length ? ` (reaches ${pol.blast_radius.dependents.join(", ")})` : "") + "."),
    c.contract.warnings.length ? h("p", {}, c.contract.warnings.map((w) => badge(w, "warn"))) : null,
    h("h3", {}, "Success conditions and guardrails"),
    h("ul", { class: "evidence" }, [...c.contract.success_conditions.map((p) => ["success", p]), ...c.contract.safety_guardrails.map((p) => ["guardrail", p])]
      .map(([kind, p]) => h("li", {}, badge(kind, "neutral"), `${p.sli}(${p.route}) ${p.op} ${p.threshold} (needs ${p.min_samples}+ samples)`))),
    win ? h("p", { class: "note" }, `Verification window ${fmtTime(win.start)} to ${fmtTime(win.end)}. The action having run is not evidence of recovery; only measured telemetry in this window decides.`) : null,
    c.verifications.length ? h("div", {}, h("h3", {}, "Verification"), ...c.verifications.map((v) => h("div", {}, h("p", {}, badge(v.outcome), v.reason),
      h("table", {}, h("thead", {}, h("tr", {}, ...["Kind", "Predicate", "Measured", "Samples", "Result"].map((t) => h("th", {}, t)))),
        h("tbody", {}, v.predicates.map((p) => h("tr", {}, h("td", {}, p.kind), h("td", {}, p.description), h("td", {}, p.value ?? "n/a"), h("td", {}, p.samples), h("td", {}, badge(p.status === "met" ? "pass" : p.status === "unmet" ? "fail" : "inconclusive", p.status === "met" ? "pass" : p.status === "unmet" ? "fail" : "inconclusive")))))))) ) : null,
    h("div", { class: "row" }, actions),
    h("details", {}, h("summary", {}, `Audit trail (${c.transitions.length})`),
      h("ul", { class: "evidence" }, c.transitions.map((t) => h("li", {}, `${fmtTime(t.at)}: ${t.from || "start"} to ${t.to} by ${t.actor} (${t.policy_version})${t.note ? " - " + t.note : ""}`)))));
}

function recoverySection(inc) {
  const active = state.contracts.some((c) => ["AWAITING_APPROVAL", "READY_FOR_ACTION", "EXECUTING", "VERIFYING"].includes(c.state));
  const propose = h("button", { type: "button", disabled: active || inc.status !== "open" ? "disabled" : null,
    onclick: () => run("Propose fix", async () => { requireActor(); await api("/api/v1/recovery-contracts", { method: "POST", actor: true, body: { incident_id: inc.id } }); }) }, "Propose recommended fix");
  return [h("h3", {}, "Recovery"),
    h("div", { class: "row" }, propose, h("span", { class: "note" }, "Needs a leading diagnosis. A different person must approve it.")),
    state.contracts.length ? state.contracts.map(contractCard) : h("p", { class: "note" }, "No recovery contracts.")];
}

function renderDetail() {
  const el = $("#detail");
  const inc = state.incidents.find((i) => i.id === state.selected);
  if (!inc) { el.replaceChildren(h("p", { class: "muted" }, "Select an incident.")); return; }
  const focus = document.activeElement && el.contains(document.activeElement);
  if (focus) return; // do not clobber a field the user is typing in
  const anomalies = (inc.summary.anomalies || []).map((a) => h("li", {},
    `${a.route}: ${a.kind}. Errors ${(a.recent_error_rate * 100).toFixed(0)}% (baseline ${(a.baseline_error_rate * 100).toFixed(0)}%), p95 ${Math.round(a.recent_p95_ms)} ms`
    + (a.baseline_p95_ms != null ? ` (baseline ${Math.round(a.baseline_p95_ms)} ms)` : "") + `, ${a.recent_requests} recent requests.`));
  el.replaceChildren(h("div", {},
    h("h2", {}, inc.title),
    h("div", { class: "row" }, badge(inc.severity), badge(inc.status), badge(inc.assessment === "inconclusive" ? "inconclusive: no cause is clearly supported" : "leading hypothesis", inc.assessment === "inconclusive" ? "warn" : "good")),
    h("p", { class: "note" }, `Started ${fmtTime(inc.started_at)}. Detected ${fmtTime(inc.detected_at)}.`),
    h("ul", { class: "evidence" }, anomalies),
    inc.summary.unaffected_routes && inc.summary.unaffected_routes.length ? h("p", { class: "note" }, `Unaffected: ${inc.summary.unaffected_routes.join(", ")}`) : null,
    h("h3", {}, "Hypotheses (ranked)"),
    inc.hypotheses.map((x) => hypothesisCard(x, inc)),
    diagnosticsSection(inc),
    recoverySection(inc)));
}

function render() { renderList(); renderDetail(); }

async function refresh(force) {
  if (!state.token) return;
  try {
    state.incidents = await api("/api/v1/incidents?limit=30");
    if (!state.selected && state.incidents.length) state.selected = state.incidents[0].id;
    state.contracts = state.selected ? await api(`/api/v1/recovery-contracts?incident_id=${encodeURIComponent(state.selected)}`) : [];
    const signature = JSON.stringify([state.incidents, state.contracts, state.selected]);
    if (force || signature !== state.signature) { state.signature = signature; render(); }
  } catch (err) {
    setStatus(`Refresh failed: ${err.message}`, true);
  }
}

function schedule() {
  clearInterval(state.timer);
  if ($("#auto").checked) state.timer = setInterval(() => refresh(false), 5000);
}

$("#token").value = state.token;
$("#actor").value = state.actor;
$("#connect").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  state.token = $("#token").value.trim();
  state.actor = $("#actor").value.trim();
  sessionStorage.setItem("sentinel_token", state.token); // cleared when the tab closes
  localStorage.setItem("sentinel_actor", state.actor);
  $("#analyze").disabled = !state.token;
  state.signature = "";
  setStatus("Connecting...");
  await refresh(true);
  if (!$("#status").classList.contains("error")) setStatus("Connected.");
  schedule();
});
$("#analyze").addEventListener("click", () => run("Analyze", () => api("/api/v1/incidents/analyze", { method: "POST" })));
$("#auto").addEventListener("change", schedule);
if (state.token) { $("#analyze").disabled = false; refresh(true).then(schedule); }
