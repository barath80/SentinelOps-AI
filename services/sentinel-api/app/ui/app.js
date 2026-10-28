// SentinelOps dashboard. No framework and no build step.
// SECURITY: telemetry-derived text (log messages, release labels, error strings) is untrusted.
// Every element is built with createElement/textContent via h(); there is no innerHTML anywhere.
"use strict";

const $ = (sel) => document.querySelector(sel);
// mode: "operators" (sign in; identity and role come from the session) or "shared_token" (legacy).
const state = { mode: "operators", token: sessionStorage.getItem("sentinel_token") || "", actor: sessionStorage.getItem("sentinel_actor") || "",
                role: sessionStorage.getItem("sentinel_role") || "", selected: null, incidents: [], timer: null, signature: "",
                contracts: [], prevention: [] };

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
  if (actor && state.mode === "shared_token") headers["x-actor"] = state.actor; // operators: the server knows who you are
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
  if (!state.actor) throw new Error(state.mode === "operators" ? "sign in first" : "enter your name in the header first (it is recorded in the audit trail)");
}

function propagationSection(inc) {
  const p = inc.summary.propagation;
  if (!p) return null;
  if (!p.traced) return [h("h3", {}, "Failure propagation"), h("p", { class: "note" }, "No request traces were recorded, so only the routes themselves are observed.")];
  const c = p.earliest_containment;
  const anomalous = p.edges.filter((e) => e.anomalous);
  return [h("h3", {}, "Failure propagation"),
    p.order.length ? h("div", { class: "chain" }, p.order.map((n, i) => [i ? h("span", { class: "arrow" }, "then") : null, badge(n, "warn")])) : null,
    c ? h("p", {}, badge(`contain at ${c.node}`, "good"), ` ${c.how}. `, h("span", { class: "note" }, c.reason)) : null,
    anomalous.length ? h("table", {}, h("thead", {}, h("tr", {}, ...["Edge", "Symptom", "Baseline", "Incident", "Onset"].map((t) => h("th", {}, t)))),
      h("tbody", {}, anomalous.map((e) => h("tr", {}, h("td", {}, `${e.from} to ${e.to}`), h("td", {}, e.symptom || ""),
        h("td", {}, `${e.baseline_median_ms} ms, ${Math.round(e.baseline_failure_share * 100)}% failed`),
        h("td", {}, `${e.recent_median_ms} ms, ${Math.round(e.recent_failure_share * 100)}% failed`), h("td", {}, fmtTime(e.onset)))))) : null,
    h("p", { class: "note" }, `${p.model_version}. ${p.note}`)];
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
      h("button", { type: "button", onclick: () => run("Investigation", async () => { await api(`/api/v1/incidents/${inc.id}/investigate`, { method: "POST", body: { budget: 4 } }); }) }, "Run investigation"),
      h("span", { class: "note" }, "Tries to disprove the leading cause, then re-ranks.")),
    runs.length ? h("table", {}, h("thead", {}, h("tr", {}, ...["Test", "Outcome", "Result"].map((t) => h("th", {}, t)))),
      h("tbody", {}, runs.map((r) => h("tr", {}, h("td", {}, h("code", {}, r.test_id)), h("td", {}, badge(r.outcome)), h("td", {}, r.explanation)))))
      : h("p", { class: "note" }, "No tests run yet."),
  ];
}

function rehearsalBlock(c) {
  const r = c.contract.rehearsal;
  if (!r) return null;
  return h("div", {}, h("h3", {}, "Rehearsal (simulation)"),
    h("p", {}, badge(r.outcome), r.reason),
    h("p", { class: "note" }, `${r.model_version}. ${r.label}`));
}

function rollbackBlock(c) {
  const rb = c.rollback_run;
  if (!rb) return null;
  return h("p", {}, badge(`rollback ${rb.status}`, rb.status === "succeeded" ? "good" : "bad"),
    h("span", { class: "note" }, ` ${rb.template} by ${rb.requested_by}${rb.reason ? ": " + rb.reason : ""}. The incident stays open; undoing a change is not a recovery.`));
}

function contractCard(c) {
  const actions = [];
  const path = `/api/v1/recovery-contracts/${c.id}`;
  if (c.state === "AWAITING_APPROVAL") {
    const comment = h("input", { type: "text", placeholder: "comment (optional)", maxlength: "500" });
    const rehearsalFailed = c.contract.rehearsal && c.contract.rehearsal.outcome === "fail";
    const ack = rehearsalFailed ? h("input", { type: "checkbox", id: `ack-${c.id}` }) : null;
    actions.push(comment,
      ack ? h("label", { class: "note", for: `ack-${c.id}` }, ack, " I have read the failed rehearsal and still approve") : null,
      h("button", { type: "button", onclick: () => run("Approve", async () => { requireActor(); await api(`${path}/approve`, { method: "POST", actor: true, body: { decision: "approve", comment: comment.value, acknowledge_rehearsal_failure: Boolean(ack && ack.checked) } }); }) }, "Approve"),
      h("button", { type: "button", class: "danger", onclick: () => run("Reject", async () => { requireActor(); await api(`${path}/approve`, { method: "POST", actor: true, body: { decision: "reject", comment: comment.value } }); }) }, "Reject"));
  }
  if (c.state === "AWAITING_APPROVAL" || c.state === "READY_FOR_ACTION")
    actions.push(h("button", { type: "button", class: "secondary", onclick: () => run("Rehearse", async () => { requireActor(); await api(`${path}/rehearse`, { method: "POST", actor: true }); }) }, "Re-run rehearsal"));
  if (c.state === "READY_FOR_ACTION")
    actions.push(h("button", { type: "button", onclick: () => run("Execute", async () => { requireActor(); await api(`${path}/execute`, { method: "POST", actor: true }); }) }, "Execute action"));
  if (c.state === "VERIFYING")
    actions.push(h("button", { type: "button", onclick: () => run("Verify", async () => { requireActor(); const r = await api(`${path}/verify`, { method: "POST", actor: true }); setStatus(`Verification: ${r.outcome}. ${r.reason}`); }) }, "Check verification"));
  if ((c.state === "FAILED" || c.state === "INCONCLUSIVE") && c.contract.pre_action_snapshot) {
    const why = h("input", { type: "text", placeholder: "reason for rollback", maxlength: "500" });
    actions.push(why, h("button", { type: "button", class: c.contract.rollback_recommended ? "danger" : "secondary",
      onclick: () => run("Rollback", async () => { requireActor(); await api(`${path}/rollback`, { method: "POST", actor: true, body: { reason: why.value } }); }) },
      c.contract.rollback_recommended ? "Roll back (recommended: a guardrail was breached)" : "Roll back"));
  }

  const win = c.contract.verification_window;
  const pol = c.contract.policy;
  return h("article", { class: "card" },
    h("div", { class: "row" }, h("strong", {}, c.action_template), badge(c.state), badge(c.outcome === "pending" ? "outcome pending" : c.outcome, c.outcome)),
    h("div", { class: "note" }, `Environment ${c.environment}. Proposed by ${c.proposed_by}. Policy ${pol.version}: blast radius ${pol.blast_radius.risk_label}`
      + (pol.blast_radius.dependents.length ? ` (reaches ${pol.blast_radius.dependents.join(", ")})` : "") + "."),
    c.contract.warnings.length ? h("p", {}, c.contract.warnings.map((w) => badge(w, "warn"))) : null,
    rehearsalBlock(c),
    h("h3", {}, "Success conditions and guardrails"),
    h("ul", { class: "evidence" }, [...c.contract.success_conditions.map((p) => ["success", p]), ...c.contract.safety_guardrails.map((p) => ["guardrail", p])]
      .map(([kind, p]) => h("li", {}, badge(kind, "neutral"), `${p.sli}(${p.route}) ${p.op} ${p.threshold} (needs ${p.min_samples}+ samples)`))),
    win ? h("p", { class: "note" }, `Verification window ${fmtTime(win.start)} to ${fmtTime(win.end)}. The action having run is not evidence of recovery; only measured telemetry in this window decides.`) : null,
    c.verifications.length ? h("div", {}, h("h3", {}, "Verification"), ...c.verifications.map((v) => h("div", {}, h("p", {}, badge(v.outcome), v.reason),
      h("table", {}, h("thead", {}, h("tr", {}, ...["Kind", "Predicate", "Measured", "Samples", "Result"].map((t) => h("th", {}, t)))),
        h("tbody", {}, v.predicates.map((p) => h("tr", {}, h("td", {}, p.kind), h("td", {}, p.description), h("td", {}, p.value ?? "n/a"), h("td", {}, p.samples), h("td", {}, badge(p.status === "met" ? "pass" : p.status === "unmet" ? "fail" : "inconclusive", p.status === "met" ? "pass" : p.status === "unmet" ? "fail" : "inconclusive")))))))) ) : null,
    rollbackBlock(c),
    h("div", { class: "row" }, actions),
    h("details", {}, h("summary", {}, `Audit trail (${c.transitions.length})`),
      h("ul", { class: "evidence" }, c.transitions.map((t) => h("li", {}, `${fmtTime(t.at)}: ${t.from || "start"} to ${t.to} by ${t.actor} (${t.policy_version})${t.note ? " - " + t.note : ""}`)))));
}

function recoverySection(inc) {
  const active = state.contracts.some((c) => ["AWAITING_APPROVAL", "READY_FOR_ACTION", "EXECUTING", "VERIFYING", "ROLLING_BACK"].includes(c.state));
  const propose = h("button", { type: "button", disabled: active || inc.status !== "open" ? "disabled" : null,
    onclick: () => run("Propose fix", async () => { requireActor(); await api("/api/v1/recovery-contracts", { method: "POST", actor: true, body: { incident_id: inc.id } }); }) }, "Propose recommended fix");
  return [h("h3", {}, "Recovery"),
    h("div", { class: "row" }, propose, h("span", { class: "note" }, "Needs a leading diagnosis. A different person must approve it.")),
    state.contracts.length ? state.contracts.map(contractCard) : h("p", { class: "note" }, "No recovery contracts.")];
}

const ATTRIBUTION_TEXT = {
  single_cause: "One cause explains every symptom.",
  multi_cause: "Different symptoms have different causes.",
  partial: "Some symptoms are explained; others are not.",
  unexplained: "No symptom has a clearly supported cause.",
};

function attributionSection(inc) {
  const a = inc.summary.attribution;
  if (!a) return null;
  return [h("h3", {}, "Attribution by symptom"),
    h("p", {}, badge(a, a === "single_cause" || a === "multi_cause" ? "good" : "warn"), ATTRIBUTION_TEXT[a] || ""),
    h("ul", { class: "evidence" }, (inc.summary.symptoms || []).map((x) => h("li", {},
      `${x.route} (${x.kind}): `, x.cause ? badge(x.cause, "good") : badge("unexplained", "warn"),
      h("span", { class: "note" }, ` best candidate ${x.top_candidate} (score ${x.top_score}), runner-up ${x.runner_up} (${x.runner_up_score})`))))];
}

function artifactCard(a) {
  const failed = a.checks.filter((c) => !c.passed);
  const buttons = [];
  if (a.review_status === "proposed") {
    buttons.push(
      h("button", { type: "button", disabled: a.checks_passed ? null : "disabled", onclick: () => run("Approve artifact", async () => { requireActor(); await api(`/api/v1/prevention-artifacts/${a.id}/review`, { method: "POST", actor: true, body: { decision: "approve" } }); }) }, "Approve"),
      h("button", { type: "button", class: "danger", onclick: () => run("Reject artifact", async () => { requireActor(); await api(`/api/v1/prevention-artifacts/${a.id}/review`, { method: "POST", actor: true, body: { decision: "reject" } }); }) }, "Reject"));
  }
  return h("article", { class: "card" },
    h("div", { class: "row" }, h("strong", {}, a.title), badge(a.type, "neutral"), badge(a.review_status, a.review_status === "approved" ? "good" : a.review_status === "rejected" ? "bad" : "warn"),
      badge(a.checks_passed ? "checks passed" : "checks failed", a.checks_passed ? "good" : "bad")),
    failed.length ? h("p", { class: "note" }, "Failed: " + failed.map((c) => `${c.name} ${c.detail}`).join("; ")) : null,
    h("div", { class: "note" }, `Linked to ${a.evidence_ids.length} evidence entr${a.evidence_ids.length === 1 ? "y" : "ies"} and contract ${a.contract_id}.${a.reviewed_by ? " Reviewed by " + a.reviewed_by + "." : ""}`),
    h("details", {}, h("summary", {}, "Show generated text (untrusted until a person has read it)"), h("pre", { class: "artifact" }, a.content)),
    h("div", { class: "row" }, buttons));
}

function preventionSection(inc) {
  const generate = h("button", { type: "button", class: "secondary", disabled: inc.status === "resolved" ? null : "disabled",
    onclick: () => run("Generate prevention proposals", async () => { requireActor(); await api(`/api/v1/incidents/${inc.id}/prevention`, { method: "POST", actor: true }); }) }, "Generate prevention proposals");
  return [h("h3", {}, "Prevention proposals"),
    h("div", { class: "row" }, generate, h("span", { class: "note" }, inc.status === "resolved" ? "Cause confirmed by a verified recovery. Nothing here is run or merged automatically." : "Available once a recovery has been verified.")),
    state.prevention.length ? state.prevention.map(artifactCard) : null];
}

const LABELS = ["release_regression", "payment_provider_timeout", "slow_dependency", "traffic_surge", "db_pool_exhaustion",
  "cache_unavailable", "resource_saturation", "retry_storm", "unknown", "no_fault"];

function shadowSection(inc) {
  const sh = inc.summary.shadow_model;
  if (!sh) return null;
  const probs = Object.entries(sh.probabilities).slice(0, 3).map(([k, v]) => `${k} ${(v * 100).toFixed(0)}%`).join(", ");
  return [h("h3", {}, "Learned model (shadow)"),
    h("p", {}, badge(sh.abstained ? "abstained" : sh.prediction, sh.abstained ? "warn" : "neutral"),
      badge(sh.agrees_with_rules ? "agrees with rules" : "disagrees with rules", sh.agrees_with_rules ? "good" : "warn"),
      h("span", { class: "note" }, ` ${sh.version}: top ${probs}; names a cause only at ${(sh.tau * 100).toFixed(0)}%+ confidence.`)),
    h("p", { class: "note" }, "Recorded for evaluation only. It never changes the ranking, the recommendation or any recovery action.")];
}

function labelSection(inc) {
  const select = h("select", { "aria-label": "True cause" }, LABELS.map((l) => h("option", { value: l, selected: inc.label && inc.label.label === l ? "selected" : null }, l)));
  const note = h("input", { type: "text", placeholder: "how you know (optional)", maxlength: "500" });
  return [h("h3", {}, "Label the true cause"),
    inc.label ? h("p", {}, badge(inc.label.label, "good"), h("span", { class: "note" }, ` labelled by ${inc.label.labeled_by} ${fmtTime(inc.label.labeled_at)}${inc.label.note ? ": " + inc.label.note : ""}`)) : null,
    h("div", { class: "row" }, select, note,
      h("button", { type: "button", class: "secondary", onclick: () => run("Save label", async () => { requireActor(); await api(`/api/v1/incidents/${inc.id}/label`, { method: "POST", actor: true, body: { label: select.value, note: note.value } }); }) }, inc.label ? "Update label" : "Save label")),
    h("p", { class: "note" }, "Labelled incidents become the evaluation set for the learned model (GET /api/v1/training/labelled).")];
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
    attributionSection(inc),
    propagationSection(inc),
    shadowSection(inc),
    diagnosticsSection(inc),
    recoverySection(inc),
    preventionSection(inc),
    labelSection(inc)));
}

function render() { renderList(); renderDetail(); }

function renderQuality(q) {
  const el = $("#quality");
  const warnings = (q && q.warnings) || [];
  el.hidden = !warnings.length;
  el.textContent = warnings.map((w) => `Telemetry problem: ${w.message}`).join(" ");
}

async function refresh(force) {
  if (!state.token) return;
  try {
    state.incidents = await api("/api/v1/incidents?limit=30");
    if (!state.selected && state.incidents.length) state.selected = state.incidents[0].id;
    state.contracts = state.selected ? await api(`/api/v1/recovery-contracts?incident_id=${encodeURIComponent(state.selected)}`) : [];
    state.prevention = state.selected ? await api(`/api/v1/incidents/${encodeURIComponent(state.selected)}/prevention`) : [];
    renderQuality(await api("/api/v1/telemetry/quality"));
    const signature = JSON.stringify([state.incidents, state.contracts, state.prevention, state.selected]);
    if (force || signature !== state.signature) { state.signature = signature; render(); }
  } catch (err) {
    if (/invalid_token|session_revoked/.test(err.message)) { signOut(); setStatus("Your session ended. Sign in again.", true); return; }
    setStatus(`Refresh failed: ${err.message}`, true);
  }
}

function schedule() {
  clearInterval(state.timer);
  if (state.token && $("#auto").checked) state.timer = setInterval(() => refresh(false), 5000);
}

function showForms() {
  const signedIn = Boolean(state.token);
  $("#login").hidden = signedIn || state.mode !== "operators";
  $("#connect").hidden = signedIn || state.mode !== "shared_token";
  $("#session").hidden = !signedIn;
  $("#analyze").disabled = !signedIn;
  $("#whoami").textContent = signedIn ? (state.mode === "operators" ? `Signed in as ${state.actor} (${state.role})` : `Acting as ${state.actor || "(no name)"}, unverified`) : "";
}

async function signIn(token, actor, role) {
  Object.assign(state, { token, actor, role, signature: "" });
  sessionStorage.setItem("sentinel_token", token); // cleared when the tab closes
  sessionStorage.setItem("sentinel_actor", actor);
  sessionStorage.setItem("sentinel_role", role || "");
  showForms();
  await refresh(true);
  schedule();
}

function signOut() {
  Object.assign(state, { token: "", actor: "", role: "", incidents: [], selected: null });
  for (const k of ["sentinel_token", "sentinel_actor", "sentinel_role"]) sessionStorage.removeItem(k);
  clearInterval(state.timer);
  $("#quality").hidden = true;
  showForms();
  render();
}

$("#login").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  setStatus("Signing in...");
  try {
    const res = await fetch("/api/v1/auth/login", { method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ username: $("#username").value.trim(), password: $("#password").value }) });
    const data = await res.json().catch(() => null);
    $("#password").value = "";
    if (!res.ok) throw new Error((data && data.detail) || `HTTP ${res.status}`);
    await signIn(data.token, data.username, data.role);
    setStatus(`Signed in. Session ends ${fmtTime(data.expires_at)}.`);
  } catch (err) {
    setStatus(`Sign-in failed: ${err.message}`, true);
  }
});
$("#connect").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  await signIn($("#token").value.trim(), $("#actor").value.trim(), "");
  if (!$("#status").classList.contains("error")) setStatus("Connected.");
});
$("#logout").addEventListener("click", async () => {
  if (state.mode === "operators") await api("/api/v1/auth/logout", { method: "POST" }).catch(() => null);
  signOut();
  setStatus("Signed out.");
});
$("#analyze").addEventListener("click", () => run("Analyze", () => api("/api/v1/incidents/analyze", { method: "POST" })));
$("#auto").addEventListener("change", schedule);

fetch("/api/v1/auth/mode").then((r) => r.json()).then((m) => {
  state.mode = m.mode;
  if (m.mode === "operators" && !m.login_configured) setStatus("Sign-in is not configured on this server (SENTINEL_SESSION_SECRET is unset).", true);
  showForms();
  if (state.token) refresh(true).then(schedule);
}).catch(() => setStatus("Cannot reach the API.", true));
