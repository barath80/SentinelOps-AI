// SentinelOps dashboard. No framework and no build step.
// SECURITY: telemetry-derived text (log messages, release labels, error strings) is untrusted.
// Every element is built with createElement/createElementNS and textContent via h() and s();
// there is no innerHTML anywhere, and the CSP forbids inline script and every outside host.
"use strict";

const $ = (sel) => document.querySelector(sel);
const SVG = "http://www.w3.org/2000/svg";
const store = {
  get: (k) => { try { return sessionStorage.getItem(k) || ""; } catch { return ""; } },
  set: (k, v) => { try { if (v) sessionStorage.setItem(k, v); else sessionStorage.removeItem(k); } catch { /* private mode */ } },
  pref: (k, v) => { try { if (v === undefined) return localStorage.getItem(k); localStorage.setItem(k, v); return v; } catch { return null; } },
};
const state = {
  mode: "operators", token: store.get("sentinel_token"), actor: store.get("sentinel_actor"), role: store.get("sentinel_role"),
  timer: null, signature: "", lastOverview: null,
};
const ROLES = ["viewer", "responder", "approver", "admin"];
const can = (role) => state.mode === "shared_token" || ROLES.indexOf(state.role) >= ROLES.indexOf(role);

// ---- DOM helpers ----------------------------------------------------------------------------

function setProps(el, props) {
  for (const [k, v] of Object.entries(props || {})) {
    if (v === false || v == null) continue;
    if (k === "class") el.setAttribute("class", v);
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v);
  }
}
function append(el, kids) {
  for (const kid of kids.flat(Infinity)) {
    if (kid === null || kid === undefined || kid === false) continue;
    el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
}
function h(tag, props, ...kids) {
  const el = document.createElement(tag);
  setProps(el, props);
  append(el, kids);
  return el;
}
function s(tag, attrs, ...kids) {
  const el = document.createElementNS(SVG, tag);
  setProps(el, attrs);
  append(el, kids);
  return el;
}
const badge = (text, kind) => h("span", { class: `badge ${kind || text}` }, text);
const fmtTime = (iso) => (iso ? new Date(iso).toLocaleString() : "");
const fmtShort = (iso) => (iso ? new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "");
const pct = (x) => (x == null ? "n/a" : `${(x * 100).toFixed(x < 0.1 && x > 0 ? 1 : 0)}%`);
const ms = (x) => (x == null ? "n/a" : x >= 1000 ? `${(x / 1000).toFixed(2)} s` : `${Math.round(x)} ms`);
const humanize = (key) => String(key || "").replace(/_/g, " ");
function ago(iso) {
  if (!iso) return "";
  const sec = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (sec < 60) return "just now";
  if (sec < 3600) return `${Math.round(sec / 60)} min ago`;
  if (sec < 86400) return `${Math.round(sec / 3600)} h ago`;
  return `${Math.round(sec / 86400)} d ago`;
}

function toast(message, isError) {
  const el = h("div", { class: `toast${isError ? " error" : ""}` }, message);
  $("#toasts").append(el);
  setTimeout(() => el.remove(), isError ? 9000 : 4000);
  const st = $("#status");
  st.textContent = message;
  st.className = `status-line${isError ? " error" : ""}`;
}

// ---- API ------------------------------------------------------------------------------------

async function api(path, { method = "GET", body } = {}) {
  const headers = { authorization: `Bearer ${state.token}` };
  if (body !== undefined) headers["content-type"] = "application/json";
  if (state.mode === "shared_token" && method !== "GET") headers["x-actor"] = state.actor; // operators: the server knows who you are
  const res = await fetch(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  if (res.status === 204) return null;
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    const code = (data && (data.error || data.detail)) || `HTTP ${res.status}`;
    const reasons = data && data.reasons ? `: ${data.reasons.join("; ")}` : data && data.reason ? `: ${data.reason}` : "";
    const err = new Error(`${typeof code === "string" ? code : JSON.stringify(code)}${reasons}`);
    err.status = res.status;
    throw err;
  }
  return data;
}

async function act(label, fn) {
  try {
    const result = await fn();
    toast(`${label}: done`);
    await render(true);
    return result;
  } catch (err) {
    if (err.status === 401) { signOut(); toast("Your session ended. Sign in again.", true); return null; }
    toast(`${label} failed: ${err.message}`, true);
    return null;
  }
}

// ---- charts (SVG) -----------------------------------------------------------------------------

const CHART_W = 560; // bar charts and the propagation graph
const LINE_W = 420; // line charts sit in half-width cards

// Axis labels: whole numbers when the scale allows, otherwise one decimal (avoids "1, 1, 0, 0").
const tick = (v) => (Number.isInteger(v) || Math.abs(v) >= 10 ? String(Math.round(v)) : v.toFixed(1));

function lineChart(series, { height = 170, format = tick, onset = null, title = "", releases = [] } = {}) {
  const CHART_W = LINE_W;
  const pad = { l: 56, r: 10, t: 14, b: 24 };
  const pts = series.flatMap((x) => x.points.filter((p) => p.v != null));
  if (!pts.length) return h("p", { class: "note" }, "No data in this window.");
  const ts = series.flatMap((x) => x.points.map((p) => p.t));
  const t0 = Math.min(...ts), t1 = Math.max(...ts);
  const vmax = Math.max(...pts.map((p) => p.v), 0) * 1.1 || 1;
  const X = (t) => pad.l + ((t - t0) / Math.max(1, t1 - t0)) * (CHART_W - pad.l - pad.r);
  const Y = (v) => pad.t + (1 - v / vmax) * (height - pad.t - pad.b);
  const svg = s("svg", { class: "chart", viewBox: `0 0 ${CHART_W} ${height}`, role: "img", "aria-label": title });
  for (let i = 0; i <= 3; i++) {
    const v = (vmax / 3) * i;
    svg.append(s("line", { class: "grid-line", x1: pad.l, x2: CHART_W - pad.r, y1: Y(v), y2: Y(v) }),
      s("text", { class: "axis-text", x: pad.l - 6, y: Y(v) + 3, "text-anchor": "end" }, format(v)));
  }
  for (const frac of [0, 0.5, 1]) {
    const t = t0 + (t1 - t0) * frac;
    svg.append(s("text", { class: "axis-text", x: X(t), y: height - 6, "text-anchor": frac === 0 ? "start" : frac === 1 ? "end" : "middle" },
      fmtShort(new Date(t).toISOString())));
  }
  series.forEach((x, i) => {
    let d = "", pen = false;
    for (const p of x.points) {
      if (p.v == null) { pen = false; continue; }
      d += `${pen ? "L" : "M"}${X(p.t).toFixed(1)},${Y(p.v).toFixed(1)}`;
      pen = true;
    }
    if (d) svg.append(s("path", { class: `series line-${(i % 4) + 1}`, d }, s("title", {}, x.name)));
  });
  for (const r of releases) {
    const t = new Date(r.t).getTime();
    if (t >= t0 && t <= t1) svg.append(s("line", { class: "release", x1: X(t), x2: X(t), y1: pad.t, y2: height - pad.b }, s("title", {}, `release ${r.version} first seen`)),
      s("text", { class: "release-text", x: X(t) - 4, y: height - pad.b - 4, "text-anchor": "end" }, r.version));
  }
  if (onset) {
    const t = new Date(onset).getTime();
    if (t >= t0 && t <= t1) svg.append(s("line", { class: "onset", x1: X(t), x2: X(t), y1: pad.t, y2: height - pad.b }),
      s("text", { class: "onset-text", x: X(t) + 4, y: pad.t + 10 }, "onset"));
  }
  const legend = h("div", { class: "legend" }, series.map((x, i) => h("span", {}, h("i", { class: `swatch-${(i % 4) + 1}` }), x.name)));
  return h("div", {}, svg, legend);
}

function routeCharts(seriesData, onset) {
  const routes = Object.entries(seriesData.routes || {});
  if (!routes.length) return h("p", { class: "empty" }, "No request telemetry in this window.");
  const pick = (key) => routes.map(([route, pts]) => ({ name: route, points: pts.map((p) => ({ t: new Date(p.t).getTime(), v: p[key] })) }));
  const releases = seriesData.releases || [];
  const panel = (title, key, format) => h("div", { class: "card" }, h("h3", {}, title), lineChart(pick(key), { title, onset, format, releases }));
  return h("div", { class: "grid two" },
    panel("Requests per bucket", "requests"), panel("Error rate", "error_rate", (v) => pct(v)),
    panel("p95 latency", "p95_ms", (v) => ms(v)), panel("Throttled (429)", "throttled"));
}

function sparkline(values) {
  const w = 120, hgt = 28, clean = values.map((v) => (v == null ? 0 : v));
  const max = Math.max(...clean, 1);
  const d = clean.map((v, i) => `${i ? "L" : "M"}${((i / Math.max(1, clean.length - 1)) * w).toFixed(1)},${(hgt - 2 - (v / max) * (hgt - 4)).toFixed(1)}`).join("");
  return s("svg", { class: "chart spark", viewBox: `0 0 ${w} ${hgt}`, width: w, height: hgt, role: "img", "aria-label": "trend" },
    s("path", { class: "series line-1", d }));
}

function barChart(items, { format = (v) => v.toFixed(2), signed = false } = {}) {
  const rowH = 24, labelW = 230, w = CHART_W, hgt = items.length * rowH + 6;
  const max = Math.max(...items.map((x) => Math.abs(x.value)), 1e-9);
  const span = signed ? (w - labelW - 60) / 2 : w - labelW - 60;
  const zero = signed ? labelW + span : labelW;
  const svg = s("svg", { class: "chart", viewBox: `0 0 ${w} ${hgt}`, role: "img", "aria-label": "bar chart" });
  items.forEach((x, i) => {
    const y = i * rowH + 4, len = (Math.abs(x.value) / max) * span;
    const x0 = x.value >= 0 ? zero : zero - len;
    svg.append(s("text", { class: "bar-label", x: labelW - 8, y: y + 13, "text-anchor": "end" }, x.label),
      s("rect", { class: x.value >= 0 ? "bar-pos" : "bar-neg", x: x0, y, width: Math.max(1, len), height: rowH - 8, rx: 3 }),
      s("text", { class: "axis-text", x: x.value >= 0 ? x0 + len + 4 : x0 - 4, y: y + 12, "text-anchor": x.value >= 0 ? "start" : "end" }, format(x.value)));
  });
  return svg;
}

// Failure-propagation graph: routes left, dependencies right. Observed edges solid, inferred dashed,
// no-longer-reached dotted; anomalous nodes and edges red; the containment point outlined green.
function propagationGraph(p) {
  const left = p.nodes.filter((n) => n.kind === "route");
  if (p.edges.some((e) => e.from === "shop-web")) left.push({ id: "shop-web", kind: "service", anomalous: null });
  const right = p.nodes.filter((n) => n.kind !== "route");
  const rowH = 54, w = CHART_W, boxW = 190;
  const hgt = Math.max(left.length, right.length, 1) * rowH + 16;
  const pos = {};
  left.forEach((n, i) => { pos[n.id] = { x: 10, y: 10 + i * rowH }; });
  right.forEach((n, i) => { pos[n.id] = { x: w - boxW - 10, y: 10 + i * rowH }; });
  const containId = p.earliest_containment && p.earliest_containment.node;
  const svg = s("svg", { class: "chart", viewBox: `0 0 ${w} ${hgt}`, role: "img", "aria-label": "failure propagation graph" });
  for (const e of p.edges) {
    if (!e.to || !pos[e.from] || !pos[e.to]) continue;
    const a = pos[e.from], b = pos[e.to], ax = a.x + boxW, ay = a.y + 19, by = b.y + 19, mid = (ax + b.x) / 2;
    const tip = `${e.from} to ${e.to}: ${e.kind}${e.recent_median_ms != null ? `, median ${ms(e.baseline_median_ms)} before, ${ms(e.recent_median_ms)} now` : ""}`;
    svg.append(s("path", { class: `edge ${e.kind}${e.anomalous ? " anomalous" : ""}`, d: `M${ax},${ay} C${mid},${ay} ${mid},${by} ${b.x},${by}` }, s("title", {}, tip)));
  }
  for (const n of [...left, ...right]) {
    const cls = `node${n.anomalous ? " anomalous" : ""}${n.id === containId ? " contain" : ""}${n.anomalous === null ? " unknown" : ""}`;
    const sub = n.anomalous ? `anomalous${n.onset ? " from " + fmtShort(n.onset) : ""}` : n.anomalous === null ? "not observed" : "normal";
    svg.append(s("g", { class: cls, transform: `translate(${pos[n.id].x},${pos[n.id].y})` },
      s("rect", { width: boxW, height: 38, rx: 8 }), s("text", { x: 10, y: 16 }, n.id), s("text", { class: "sub", x: 10, y: 30 }, `${n.kind} · ${sub}`)));
  }
  return h("div", {}, svg, h("div", { class: "legend" }, h("span", {}, "solid: observed in traces"), h("span", {}, "dashed: inferred from topology"),
    h("span", {}, "dotted: called before, not reached now"), h("span", {}, "red: anomalous"), h("span", {}, "green outline: earliest containment")));
}

function waterfall(spans) {
  if (!spans.length) return h("p", { class: "note" }, "No spans recorded for this trace.");
  const total = Math.max(...spans.map((sp) => (sp.offset_ms || 0) + (sp.duration_ms || 0)), 1);
  return h("div", { class: "waterfall" }, spans.map((sp) => {
    const bar = h("span", { class: `wf-bar${sp.status === "error" ? " error" : ""}`, title: `${sp.name}: ${ms(sp.duration_ms)}` });
    bar.style.left = `${((sp.offset_ms || 0) / total) * 100}%`; // CSSOM, allowed by the CSP
    bar.style.width = `${((sp.duration_ms || 0) / total) * 100}%`;
    const name = h("span", { class: "wf-name", title: sp.name }, `${sp.name} · ${ms(sp.duration_ms)}`);
    name.style.paddingLeft = `${sp.depth * 14}px`;
    return h("div", { class: "wf-row" }, name, h("div", { class: "wf-track" }, bar));
  }));
}

// ---- drawer: any cited event or trace opens here --------------------------------------------

function openDrawer(title, ...body) {
  $("#drawer-title").textContent = title;
  $("#drawer-body").replaceChildren(...body.flat().filter(Boolean));
  $("#drawer").hidden = false;
  $("#drawer-close").focus();
}
async function openEvent(id) {
  try {
    const ev = await api(`/api/v1/telemetry/events/${encodeURIComponent(id)}`);
    openDrawer(`${ev.event_type} event`, h("p", {}, badge(ev.event_type, "info"), " ", fmtTime(ev.event_time), " · ", ev.service_name),
      ev.trace_id ? h("button", { type: "button", class: "secondary small", onclick: () => openTrace(ev.trace_id) }, "Open its trace") : null,
      h("pre", { class: "json" }, JSON.stringify(ev, null, 2)));
  } catch (err) { toast(`Cannot open event: ${err.message}`, true); }
}
async function openTrace(traceId) {
  try {
    const t = await api(`/api/v1/telemetry/traces/${encodeURIComponent(traceId)}`);
    openDrawer(`Trace ${shortId(traceId)}`, waterfall(t.spans), h("h3", {}, "Log lines in this trace"), logsTable(t.logs));
  } catch (err) { toast(`Cannot open trace: ${err.message}`, true); }
}
const refButtons = (refs) => (refs || []).slice(0, 6).map((r) =>
  h("button", { type: "button", class: "ref", title: "Open the source event", onclick: () => openEvent(r) }, r.slice(0, 8)));

function logsTable(logs) {
  if (!logs.length) return h("p", { class: "note" }, "No log lines.");
  return h("div", { class: "table-wrap" }, h("table", {},
    h("thead", {}, h("tr", {}, ["Time", "Route", "Status", "Duration", "Message", ""].map((t) => h("th", {}, t)))),
    h("tbody", {}, logs.map((e) => {
      const a = e.attributes || {};
      return h("tr", {}, h("td", {}, fmtShort(e.event_time)), h("td", {}, h("code", {}, a.route || "")),
        h("td", {}, a.status ? badge(String(a.status), a.status >= 500 ? "bad" : a.status === 429 ? "warn" : "good") : ""),
        h("td", {}, ms(a.duration_ms)), h("td", { class: "wrap" }, a.message || "", a.error ? h("div", { class: "note" }, a.error) : null),
        h("td", {}, h("button", { type: "button", class: "ref", onclick: () => openEvent(e.event_id) }, "event"),
          e.trace_id ? h("button", { type: "button", class: "ref", onclick: () => openTrace(e.trace_id) }, "trace") : null));
    }))));
}
const shortId = (id) => (id && id.length > 14 ? `${id.slice(0, 6)}…${id.slice(-6)}` : id || "");
const table = (heads, rows) => h("div", { class: "table-wrap" }, h("table", {}, h("thead", {}, h("tr", {}, heads.map((t) => h("th", {}, t)))), h("tbody", {}, rows)));

// ---- routing ------------------------------------------------------------------------------------

const NAV = [
  { id: "overview", label: "Overview" }, { id: "incidents", label: "Incidents" }, { id: "telemetry", label: "Telemetry" },
  { id: "slo", label: "SLOs" }, { id: "automation", label: "Automation" }, { id: "notifications", label: "Notifications" }, { id: "model", label: "ML model" },
  { id: "audit", label: "Audit log", role: "approver" }, { id: "operators", label: "Operators", role: "admin" },
];
function route() {
  const parts = (location.hash.replace(/^#\/?/, "") || "overview").split("/");
  return { view: parts[0] || "overview", id: parts[1] || null, tab: parts[2] || null };
}
function go(hash) { location.hash = hash; }

function renderNav() {
  const r = route(), o = state.lastOverview;
  $("#nav").replaceChildren(...NAV.filter((n) => !n.role || can(n.role)).map((n) => {
    const current = r.view === n.id || (n.id === "incidents" && r.view === "incident");
    const count = n.id === "incidents" && o ? o.open_incidents.total : 0;
    return h("button", { type: "button", class: "nav-item", "aria-current": current ? "page" : null,
      onclick: () => { go(`#/${n.id}`); $("#sidebar").classList.remove("open"); } }, n.label,
      count ? h("span", { class: "nav-count", "aria-label": `${count} open` }, count) : null);
  }), ...(state.shopUrl ? [h("a", { class: "nav-item nav-external", href: state.shopUrl, target: "_blank", rel: "noopener noreferrer",
    title: "The monitored application, in a new tab" }, "ShopSphere store", h("span", { "aria-hidden": "true" }, "↗"))] : []));
}
function renderSignals(o) {
  const items = [];
  if (o.telemetry_quality !== "ok") items.push(badge("telemetry: clock skew", "warn"));
  if (o.throttling && o.throttling.status !== "ok") items.push(badge("throttling (429)", "warn"));
  if (o.contracts.awaiting_approval) items.push(badge(`${o.contracts.awaiting_approval} awaiting approval`, "info"));
  items.push(badge(o.automation.enabled ? "automation on" : "automation off", o.automation.enabled ? "good" : "neutral"));
  $("#signals").replaceChildren(...items);
}
function page(title, sig, ...kids) {
  const el = h("div", {}, ...kids);
  el.dataset.title = title;
  el.dataset.sig = JSON.stringify(sig);
  return el;
}

async function render(force) {
  if (!state.token) return;
  const active = document.activeElement;
  const editing = active && ($("#view").contains(active) || $("#drawer").contains(active)) && /^(INPUT|SELECT|TEXTAREA)$/.test(active.tagName);
  if (editing && !force) return; // never clobber a form control in use
  const r = route();
  try {
    state.lastOverview = await api("/api/v1/overview");
    renderSignals(state.lastOverview);
    renderNav();
    const node = await (VIEWS[r.view] || VIEWS.overview)(r);
    $("#page-title").textContent = node.dataset.title || "SentinelOps";
    const signature = JSON.stringify([r, node.dataset.sig]);
    if (force || signature !== state.signature) {
      state.signature = signature;
      $("#view").replaceChildren(node);
    }
  } catch (err) {
    if (err.status === 401) { signOut(); toast("Your session ended. Sign in again.", true); return; }
    toast(`Refresh failed: ${err.message}`, true);
  }
}

// ---- views ----------------------------------------------------------------------------------------

const VIEWS = {};

function leadingOf(inc) {
  const top = inc.hypotheses[0];
  return inc.assessment === "leading_hypothesis" && top ? top : null;
}
function incidentItem(inc) {
  const lead = leadingOf(inc);
  return h("button", { type: "button", class: `incident-item ${inc.status === "resolved" ? "resolved" : inc.severity}`, onclick: () => go(`#/incident/${inc.id}/summary`) },
    h("div", { class: "row" }, badge(inc.severity), badge(inc.status), lead ? badge(humanize(lead.cause_key), "good") : badge("no clear cause yet", "warn"),
      h("span", { class: "note" }, ago(inc.started_at))),
    h("div", { class: "incident-title" }, inc.title));
}

VIEWS.overview = async () => {
  const o = state.lastOverview;
  const [incidents, series] = await Promise.all([api("/api/v1/incidents?limit=8"), api("/api/v1/telemetry/series?minutes=60&bucket_seconds=120")]);
  const kpi = (label, value, sub) => h("div", { class: "card kpi" }, h("div", { class: "label" }, label), h("div", { class: "value" }, value),
    sub ? h("div", { class: "sub" }, sub) : null);
  const sev = o.open_incidents.by_severity || {};
  const rows = o.routes.map((r) => {
    const pts = (series.routes || {})[r.route] || [];
    return h("tr", {}, h("td", {}, h("span", { class: `dot ${r.health === "ok" ? "ok" : "bad"}` }), " ", h("code", {}, r.route)),
      h("td", {}, r.requests), h("td", {}, pct(r.error_rate)), h("td", {}, ms(r.p95_ms)), h("td", {}, r.throttled || 0),
      h("td", {}, sparkline(pts.map((p) => p.requests))), h("td", {}, sparkline(pts.map((p) => p.p95_ms))));
  });
  return page("Overview", [o.routes, o.open_incidents, o.contracts, o.automation, incidents.map((i) => [i.id, i.status, i.assessment])],
    o.throttling.routes.map((t) => h("div", { class: "banner" }, `Throttling: ${t.message}.`)),
    o.telemetry_quality !== "ok" ? h("div", { class: "banner" }, "Telemetry quality: a service's clock is running ahead, so its timeline cannot be trusted.") : null,
    h("div", { class: "grid kpis" },
      kpi("Open incidents", o.open_incidents.total, Object.entries(sev).map(([k, v]) => `${v} ${k}`).join(", ") || "none"),
      kpi("Awaiting approval", o.contracts.awaiting_approval, "recovery contracts"),
      kpi("Verifying", o.contracts.verifying, "recoveries being measured"),
      kpi("Automation", o.automation.enabled ? "On" : "Off", o.automation.allowed ? "per-cause policies" : "not allowed here"),
      kpi("Telemetry", o.telemetry_quality === "ok" ? "Healthy" : "Suspect", `${o.events_last_15_min} events in 15 min`),
      kpi("Notifications", o.notifications_failed_24h ? `${o.notifications_failed_24h} failed` : "OK", "last 24 h")),
    h("div", { class: "grid two" },
      h("div", { class: "card" }, h("div", { class: "card-head" }, h("h2", {}, "Service health"), h("span", { class: "note" }, "last 15 min; trends over 60 min")),
        o.routes.length ? table(["Route", "Requests", "Errors", "p95", "429s", "Traffic", "p95 trend"], rows) : h("p", { class: "empty" }, "No traffic in the last 15 minutes.")),
      h("div", { class: "card" }, h("div", { class: "card-head" }, h("h2", {}, "Recent incidents"),
        h("button", { type: "button", class: "ghost small", onclick: () => go("#/incidents") }, "View all")),
        incidents.length ? h("div", { class: "stack" }, incidents.map(incidentItem)) : h("p", { class: "empty" }, "No incidents. Analysis runs on demand or on a schedule."))));
};

VIEWS.incidents = async () => {
  const incidents = await api("/api/v1/incidents?limit=100");
  const filter = store.pref("incident_filter") || "open";
  const shown = incidents.filter((i) => filter === "all" || i.status === filter);
  const select = h("select", { "aria-label": "Show", onchange: (e) => { store.pref("incident_filter", e.target.value); render(true); } },
    ["open", "resolved", "all"].map((v) => h("option", { value: v, selected: v === filter ? "selected" : null }, v)));
  return page("Incidents", [filter, incidents.map((i) => [i.id, i.status, i.assessment])],
    h("div", { class: "row toolbar" }, h("label", { class: "check" }, "Show ", select), h("span", { class: "note" }, `${shown.length} of ${incidents.length}`)),
    h("div", { class: "stack" }, shown.length ? shown.map(incidentItem) : h("p", { class: "empty" }, "Nothing here.")));
};

// ---- incident page ---------------------------------------------------------------------------------

const TABS = [["summary", "Summary"], ["timeline", "Timeline"], ["evidence", "Evidence"], ["telemetry", "Logs, traces, metrics"], ["diagnostics", "Diagnostics"],
  ["recovery", "Recovery"], ["model", "ML model"], ["prevention", "Prevention & label"]];
const TAB_VIEWS = {};

VIEWS.incident = async (r) => {
  const tab = r.tab || "summary";
  const id = encodeURIComponent(r.id);
  const [inc, contracts] = await Promise.all([api(`/api/v1/incidents/${id}`), api(`/api/v1/recovery-contracts?incident_id=${id}`)]);
  const lead = leadingOf(inc);
  const tabs = h("div", { class: "tabs", role: "tablist" }, TABS.map(([key, label]) =>
    h("button", { type: "button", class: "tab", role: "tab", "aria-selected": String(key === tab), onclick: () => go(`#/incident/${inc.id}/${key}`) }, label)));
  const body = await (TAB_VIEWS[tab] || TAB_VIEWS.summary)(inc, contracts);
  return page("Incident", [inc, contracts, tab],
    h("button", { type: "button", class: "ghost small", onclick: () => go("#/incidents") }, "All incidents"),
    h("div", { class: "card hero" },
      h("div", { class: "row" }, badge(inc.severity), badge(inc.status),
        badge(inc.assessment === "inconclusive" ? "inconclusive" : "leading hypothesis", inc.assessment === "inconclusive" ? "warn" : "good"),
        h("span", { class: "note" }, `started ${fmtTime(inc.started_at)} · detected ${fmtTime(inc.detected_at)}`)),
      h("h2", {}, inc.title),
      lead ? h("div", {}, h("div", { class: "note" }, "Leading cause (a ranking, not a probability)"), h("div", { class: "cause" }, lead.title))
        : h("div", { class: "note" }, "No cause is clearly supported yet. Run the investigation before acting."),
      h("div", { class: "row" }, h("button", { type: "button", class: "secondary small", onclick: () => openPostmortem(inc) }, "Postmortem draft"))),
    tabs, body);
};

function inferredNote(p) {
  const edges = p.edges.filter((e) => e.kind === "inferred");
  return edges.length ? h("p", { class: "note" }, `Inferred from the service topology, not observed in any trace (health unknown): ${edges.map((e) => `${e.from} to ${e.to}`).join(", ")}.`) : null;
}

TAB_VIEWS.summary = async (inc) => {
  const sm = inc.summary || {}, prop = sm.propagation, c = prop && prop.earliest_containment;
  const sims = await api(`/api/v1/incidents/${encodeURIComponent(inc.id)}/similar`);
  const similarCard = h("div", { class: "card" }, h("h3", {}, "Similar past incidents"),
    sims.length ? table(["Incident", "Similarity", "What it was", "Fixed by"], sims.map((x) => h("tr", {},
      h("td", { class: "wrap" }, h("button", { type: "button", class: "ref", onclick: () => go(`#/incident/${x.incident_id}/summary`) }, shortId(x.incident_id)), " ", x.title),
      h("td", {}, pct(x.similarity)), h("td", {}, x.cause ? humanize(x.cause) : "unknown", h("div", { class: "note" }, x.cause_source)),
      h("td", {}, x.resolved_by ? badge(humanize(x.resolved_by), "good") : h("span", { class: "note" }, "no verified fix")))))
      : h("p", { class: "note" }, "No earlier incident looks like this one."),
    h("p", { class: "note" }, "Matched on the incident's feature vector (the learned model's features, standardized; cosine similarity). A hint for where to look, not evidence."));
  return h("div", {}, h("div", { class: "grid two" },
    h("div", { class: "card" }, h("h3", {}, "Symptoms"),
      h("ul", { class: "evidence-list" }, (sm.anomalies || []).map((a) => h("li", {},
        h("div", {}, h("code", {}, a.route), " ", badge(a.kind, a.kind === "errors" ? "bad" : "warn")),
        h("div", { class: "note" }, `errors ${pct(a.recent_error_rate)} (baseline ${pct(a.baseline_error_rate)}) · p95 ${ms(a.recent_p95_ms)}`
          + (a.baseline_p95_ms != null ? ` (baseline ${ms(a.baseline_p95_ms)})` : "") + ` · ${a.recent_requests} recent requests`)))),
      sm.unaffected_routes && sm.unaffected_routes.length ? h("p", { class: "note" }, `Unaffected: ${sm.unaffected_routes.join(", ")}`) : null,
      sm.attribution ? h("p", {}, badge(humanize(sm.attribution), sm.attribution.endsWith("cause") ? "good" : "warn"),
        sm.unexplained_symptoms && sm.unexplained_symptoms.length ? ` unexplained: ${sm.unexplained_symptoms.join(", ")}` : "") : null,
      sm.telemetry_quality && sm.telemetry_quality.status !== "ok" ? h("p", { class: "banner" }, "Telemetry quality problem: see Telemetry > Data quality.") : null),
    h("div", { class: "card" }, h("h3", {}, "Failure propagation"),
      prop ? [c ? h("p", {}, badge(`contain at ${c.node}`, "good"), " ", c.how, h("div", { class: "note" }, c.reason)) : null,
        prop.traced ? propagationGraph(prop) : h("p", { class: "note" }, "No request traces were recorded, so only the routes themselves are observed."),
        inferredNote(prop), h("p", { class: "note" }, `${prop.model_version}. ${prop.note}`)] : h("p", { class: "note" }, "Not available."))),
    similarCard);
};

TAB_VIEWS.timeline = async (inc) => {
  const t = await api(`/api/v1/incidents/${encodeURIComponent(inc.id)}/timeline`);
  const kind = { symptom: "bad", release: "info", signal: "warn", detected: "bad", diagnostic: "neutral", recovery: "good",
    notified: "neutral", automation: "info", label: "neutral" };
  return h("div", { class: "card" }, h("h3", {}, "What happened, in order"),
    t.length ? h("ol", { class: "timeline" }, t.map((x) => h("li", {}, h("div", { class: "row" }, h("strong", {}, fmtTime(x.at)), badge(x.kind, kind[x.kind] || "neutral"),
      x.actor ? h("span", { class: "note" }, `by ${x.actor}`) : null, x.ref ? h("button", { type: "button", class: "ref", onclick: () => openEvent(x.ref) }, "source") : null),
      h("div", {}, x.text)))) : h("p", { class: "empty" }, "Nothing recorded."));
};

async function openPostmortem(inc) {
  try {
    const res = await fetch(`/api/v1/incidents/${encodeURIComponent(inc.id)}/postmortem`, { headers: { authorization: `Bearer ${state.token}` } });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const text = await res.text();
    const download = h("button", { type: "button", onclick: () => {
      const a = h("a", { href: URL.createObjectURL(new Blob([text], { type: "text/markdown" })), download: `postmortem-${inc.id.slice(0, 8)}.md` });
      document.body.append(a);
      a.click();
      a.remove();
    } }, "Download .md");
    const copy = h("button", { type: "button", class: "secondary", onclick: () => navigator.clipboard.writeText(text).then(() => toast("Copied"), () => toast("Copy failed", true)) }, "Copy");
    openDrawer("Postmortem draft", h("p", { class: "note" }, "Generated from stored evidence. A draft: review and edit before sharing."),
      h("div", { class: "row" }, download, copy), h("pre", { class: "json" }, text));
  } catch (err) { toast(`Cannot build the postmortem: ${err.message}`, true); }
}

TAB_VIEWS.evidence = async (inc) => h("div", {}, h("h3", {}, "Hypotheses (ranked)"),
  h("p", { class: "note" }, "Every claim cites the stored events it was computed from. Click an id to open the event itself."),
  inc.hypotheses.map((x) => {
    const fill = h("span", {});
    fill.style.width = `${Math.round(Math.min(1, (x.breakdown.supporting || 0) / 2) * 100)}%`;
    const history = x.score_history || [];
    return h("article", { class: `hyp ${x.status}` },
      h("div", { class: "row" }, h("strong", {}, x.title), badge(x.status), badge(`score ${x.score}`, "neutral"),
        h("span", { class: "note" }, `${x.score_version}, not a probability · next test ${x.next_test_id}`)),
      h("div", { class: "meter", title: "supporting evidence" }, fill),
      x.evidence.length ? h("ul", { class: "evidence-list" }, x.evidence.map((e) => h("li", {},
        h("div", { class: "row" }, badge(e.relation), h("span", { class: "note" }, `strength ${e.strength} · ${e.created_by}`), refButtons(e.source_refs)),
        h("div", {}, e.explanation)))) : h("p", { class: "note" }, "No evidence recorded."),
      history.length ? h("details", {}, h("summary", {}, `Score history (${history.length})`),
        h("ul", { class: "evidence-list" }, history.map((y) => h("li", {}, `${y.score} (${y.status}) before ${y.reason}`)))) : null);
  }));

TAB_VIEWS.telemetry = async (inc) => {
  const t = await api(`/api/v1/incidents/${encodeURIComponent(inc.id)}/telemetry`);
  return h("div", {}, routeCharts(t.series, t.onset),
    h("div", { class: "card" }, h("h3", {}, "Slowest traces of affected requests"),
      t.traces.length ? table(["Trace", "Route", "Duration", "Status"], t.traces.map((x) => h("tr", {},
        h("td", {}, h("button", { type: "button", class: "ref", onclick: () => openTrace(x.trace_id) }, shortId(x.trace_id))),
        h("td", {}, h("code", {}, x.route || "")), h("td", {}, ms(x.duration_ms)), h("td", {}, badge(x.status || "unset", x.status === "error" ? "bad" : "good")))))
        : h("p", { class: "note" }, "No traces recorded for these requests.")),
    h("div", { class: "card" }, h("h3", {}, "Failing and slow requests"),
      h("p", { class: "note" }, "Errors, error-type log lines, and requests slower than twice their route's baseline p95, from the onset on."),
      logsTable(t.failing_logs)));
};

TAB_VIEWS.diagnostics = async (inc) => {
  const runs = inc.diagnostic_runs || [];
  return h("div", { class: "card" },
    h("div", { class: "card-head" }, h("h3", {}, "Diagnostic tests (read-only)"),
      can("responder") ? h("button", { type: "button", onclick: () => act("Investigation", () => api(`/api/v1/incidents/${inc.id}/investigate`, { method: "POST", body: { budget: 4 } })) }, "Run investigation") : null),
    h("p", { class: "note" }, "Tries to disprove the leading cause, then tests the alternatives, and re-ranks. Nothing here changes any system."),
    runs.length ? table(["Test", "Tested cause", "Outcome", "Result", "Sources"], runs.map((x) => h("tr", {}, h("td", {}, h("code", {}, x.test_id)),
      h("td", {}, humanize(x.hypothesis_key)), h("td", {}, badge(x.outcome)), h("td", { class: "wrap" }, x.explanation), h("td", {}, refButtons(x.source_refs)))))
      : h("p", { class: "empty" }, "No tests run yet."));
};

TAB_VIEWS.recovery = async (inc, contracts) => {
  const active = contracts.some((c) => ["AWAITING_APPROVAL", "READY_FOR_ACTION", "EXECUTING", "VERIFYING", "ROLLING_BACK"].includes(c.state));
  const propose = can("responder") ? h("button", { type: "button", disabled: active || inc.status !== "open" ? "disabled" : null,
    onclick: () => act("Propose fix", () => api("/api/v1/recovery-contracts", { method: "POST", body: { incident_id: inc.id } })) }, "Propose recommended fix") : null;
  return h("div", {},
    h("div", { class: "card" }, h("div", { class: "card-head" }, h("h3", {}, "Recovery"), propose),
      h("p", { class: "note" }, "Manual path: needs a leading diagnosis; every contract is rehearsed first; a different person with the approver role approves; success is decided only by telemetry measured after the action. Automatic path: see Automation, for causes an admin opted in.")),
    contracts.length ? contracts.map(contractCard) : h("p", { class: "empty" }, "No recovery contracts."));
};

function contractCard(c) {
  const path = `/api/v1/recovery-contracts/${c.id}`;
  const actions = [];
  if (c.state === "AWAITING_APPROVAL" && can("responder")) {
    const comment = h("input", { type: "text", placeholder: "comment (optional)", maxlength: "500", "aria-label": "Approval comment" });
    const failed = c.contract.rehearsal && c.contract.rehearsal.outcome === "fail";
    const ack = failed ? h("input", { type: "checkbox", id: `ack-${c.id}` }) : null;
    actions.push(comment, ack ? h("label", { class: "check", for: `ack-${c.id}` }, ack, "I have read the failed rehearsal and still approve") : null,
      h("button", { type: "button", onclick: () => act("Approve", () => api(`${path}/approve`, { method: "POST", body: { decision: "approve", comment: comment.value, acknowledge_rehearsal_failure: Boolean(ack && ack.checked) } })) }, "Approve"),
      h("button", { type: "button", class: "danger", onclick: () => act("Reject", () => api(`${path}/approve`, { method: "POST", body: { decision: "reject", comment: comment.value } })) }, "Reject"));
  }
  if ((c.state === "AWAITING_APPROVAL" || c.state === "READY_FOR_ACTION") && can("responder"))
    actions.push(h("button", { type: "button", class: "secondary", onclick: () => act("Rehearse", () => api(`${path}/rehearse`, { method: "POST" })) }, "Re-run rehearsal"));
  if (c.state === "READY_FOR_ACTION" && can("responder"))
    actions.push(h("button", { type: "button", onclick: () => act("Execute", () => api(`${path}/execute`, { method: "POST" })) }, "Execute action"));
  if (c.state === "VERIFYING" && can("responder"))
    actions.push(h("button", { type: "button", onclick: () => act("Verify", async () => { const v = await api(`${path}/verify`, { method: "POST" }); toast(`Verification: ${v.outcome}. ${v.reason}`); }) }, "Check verification"));
  if ((c.state === "FAILED" || c.state === "INCONCLUSIVE") && c.contract.pre_action_snapshot && can("responder")) {
    const why = h("input", { type: "text", placeholder: "reason for rollback", maxlength: "500", "aria-label": "Rollback reason" });
    actions.push(why, h("button", { type: "button", class: c.contract.rollback_recommended ? "danger" : "secondary",
      onclick: () => act("Rollback", () => api(`${path}/rollback`, { method: "POST", body: { reason: why.value } })) },
      c.contract.rollback_recommended ? "Roll back (recommended: a guardrail was breached)" : "Roll back"));
  }
  const pol = c.contract.policy, r = c.contract.rehearsal, win = c.contract.verification_window;
  return h("article", { class: "card" },
    h("div", { class: "card-head" }, h("h3", {}, humanize(c.action_template)), badge(c.state), badge(c.outcome === "pending" ? "outcome pending" : c.outcome, c.outcome),
      h("span", { class: "note" }, `proposed by ${c.proposed_by} · ${c.environment} · blast radius ${pol.blast_radius.risk_label}`)),
    c.contract.warnings.length ? h("p", {}, c.contract.warnings.map((w) => badge(w, "warn"))) : null,
    r ? h("div", {}, h("h3", {}, "Rehearsal (simulation)"), h("p", {}, badge(r.outcome), " ", r.reason), h("p", { class: "note" }, `${r.model_version}. ${r.label}`)) : null,
    h("h3", {}, "Success conditions and guardrails"),
    h("ul", { class: "evidence-list" }, [...c.contract.success_conditions.map((p) => ["success", p]), ...c.contract.safety_guardrails.map((p) => ["guardrail", p])]
      .map(([kind, p]) => h("li", {}, h("div", {}, badge(kind, "neutral"), " ", h("code", {}, `${p.sli}(${p.route}) ${p.op} ${p.threshold}`), h("span", { class: "note" }, ` needs ${p.min_samples}+ samples`))))),
    win ? h("p", { class: "note" }, `Verification window ${fmtTime(win.start)} to ${fmtTime(win.end)}. The action having run is not evidence of recovery.`) : null,
    c.verifications.map((v) => h("div", {}, h("h3", {}, "Verification"), h("p", {}, badge(v.outcome), " ", v.reason),
      table(["Kind", "Predicate", "Measured", "Samples", "Result"], v.predicates.map((p) => h("tr", {}, h("td", {}, p.kind), h("td", {}, p.description),
        h("td", {}, p.value ?? "n/a"), h("td", {}, p.samples), h("td", {}, badge(p.status))))))),
    c.rollback_run ? h("p", {}, badge(`rollback ${c.rollback_run.status}`, c.rollback_run.status === "succeeded" ? "good" : "bad"),
      h("span", { class: "note" }, ` ${c.rollback_run.template} by ${c.rollback_run.requested_by}. The incident stays open; undoing a change is not a recovery.`)) : null,
    actions.length ? h("div", { class: "row" }, actions) : null,
    h("details", {}, h("summary", {}, `Audit trail (${c.transitions.length})`),
      h("ol", { class: "timeline" }, c.transitions.map((t) => h("li", {}, h("strong", {}, `${t.from || "start"} to ${t.to}`), ` by ${t.actor}`,
        h("div", { class: "note" }, `${fmtTime(t.at)} · ${t.policy_version}${t.note ? " · " + t.note : ""}`))))));
}

TAB_VIEWS.model = async (inc) => {
  const m = await api(`/api/v1/incidents/${encodeURIComponent(inc.id)}/model`);
  if (!m.available) return h("p", { class: "empty" }, m.reason);
  const probs = Object.entries(m.probabilities).slice(0, 6).map(([k, v]) => ({ label: humanize(k), value: v }));
  return h("div", { class: "grid two" },
    h("div", { class: "card" }, h("h3", {}, "Learned model (shadow)"),
      h("p", {}, badge(m.abstained ? "abstained" : humanize(m.prediction), m.abstained ? "warn" : "info"), " ",
        (() => {
          const ref = m.investigated_answer || m.rule_answer;
          const same = m.prediction === ref;
          return badge(`${same ? "agrees with" : "differs from"} the ${m.investigated_answer ? "investigation" : "rules"}`, same ? "good" : "warn");
        })()),
      h("p", { class: "note" }, `Rules at analysis: ${humanize(m.rule_answer)}. After investigation: ${m.investigated_answer ? humanize(m.investigated_answer) : "not investigated yet"}.`),
      h("p", { class: "note" }, `${m.version}. Names a cause only at ${pct(m.tau)}+ confidence. Recorded for evaluation only: it never changes the ranking, the recommendation or any action.`),
      barChart(probs, { format: (v) => pct(v) })),
    h("div", { class: "card" }, h("h3", {}, `Why: features behind "${humanize(m.top_class)}"`),
      barChart(m.explanation.map((x) => ({ label: `${humanize(x.feature)} = ${x.value}`, value: x.contribution })), { signed: true }),
      h("p", { class: "note" }, m.note)));
};

const LABELS = ["release_regression", "payment_provider_timeout", "slow_dependency", "traffic_surge", "db_pool_exhaustion",
  "cache_unavailable", "resource_saturation", "retry_storm", "unknown", "no_fault"];

TAB_VIEWS.prevention = async (inc) => {
  const arts = await api(`/api/v1/incidents/${encodeURIComponent(inc.id)}/prevention`);
  const select = h("select", { "aria-label": "True cause" }, LABELS.map((l) => h("option", { value: l, selected: inc.label && inc.label.label === l ? "selected" : null }, humanize(l))));
  const note = h("input", { type: "text", placeholder: "how you know (optional)", maxlength: "500", "aria-label": "Label note" });
  return h("div", {},
    h("div", { class: "card" }, h("div", { class: "card-head" }, h("h3", {}, "Prevention proposals"),
      can("responder") ? h("button", { type: "button", class: "secondary", disabled: inc.status === "resolved" ? null : "disabled",
        onclick: () => act("Generate prevention proposals", () => api(`/api/v1/incidents/${inc.id}/prevention`, { method: "POST" })) }, "Generate proposals") : null),
      h("p", { class: "note" }, inc.status === "resolved" ? "Cause confirmed by a verified recovery. Nothing here is run or merged automatically." : "Available once a recovery has been verified."),
      arts.map((a) => h("article", { class: "hyp" }, h("div", { class: "row" }, h("strong", {}, a.title), badge(a.type, "neutral"), badge(a.review_status),
        badge(a.checks_passed ? "checks passed" : "checks failed", a.checks_passed ? "good" : "bad")),
        h("details", {}, h("summary", {}, "Show generated text (untrusted until a person has read it)"), h("pre", { class: "artifact" }, a.content)),
        a.review_status === "proposed" && can("approver") ? h("div", { class: "row" },
          h("button", { type: "button", class: "small", disabled: a.checks_passed ? null : "disabled", onclick: () => act("Approve artifact", () => api(`/api/v1/prevention-artifacts/${a.id}/review`, { method: "POST", body: { decision: "approve" } })) }, "Approve"),
          h("button", { type: "button", class: "danger small", onclick: () => act("Reject artifact", () => api(`/api/v1/prevention-artifacts/${a.id}/review`, { method: "POST", body: { decision: "reject" } })) }, "Reject")) : null))),
    h("div", { class: "card" }, h("h3", {}, "Label the true cause"),
      inc.label ? h("p", {}, badge(humanize(inc.label.label), "good"), h("span", { class: "note" }, ` labelled by ${inc.label.labeled_by} ${fmtTime(inc.label.labeled_at)}`)) : null,
      can("responder") ? h("div", { class: "row" }, select, note, h("button", { type: "button", class: "secondary",
        onclick: () => act("Save label", () => api(`/api/v1/incidents/${inc.id}/label`, { method: "POST", body: { label: select.value, note: note.value } })) }, inc.label ? "Update label" : "Save label")) : null,
      h("p", { class: "note" }, "Labelled incidents are the evaluation set for the learned model.")));
};

// ---- telemetry explorer ----------------------------------------------------------------------------

VIEWS.telemetry = async (r) => {
  const tab = r.id || "metrics";
  const minutes = Number(store.pref("tel_minutes") || 60);
  const tabs = h("div", { class: "tabs", role: "tablist" }, [["metrics", "Metrics"], ["logs", "Logs"], ["traces", "Traces"], ["quality", "Data quality"]].map(([k, l]) =>
    h("button", { type: "button", class: "tab", role: "tab", "aria-selected": String(k === tab), onclick: () => go(`#/telemetry/${k}`) }, l)));
  const range = h("select", { "aria-label": "Time range", onchange: (e) => { store.pref("tel_minutes", e.target.value); render(true); } },
    [[15, "15 min"], [60, "1 hour"], [360, "6 hours"], [1440, "24 hours"]].map(([v, l]) => h("option", { value: v, selected: v === minutes ? "selected" : null }, l)));
  let body;
  if (tab === "logs") {
    const q = h("input", { type: "search", placeholder: "search message, error, route", "aria-label": "Search logs", value: store.pref("log_q") || "" });
    const status = h("select", { "aria-label": "Minimum status" }, [[0, "any status"], [400, "4xx and 5xx"], [429, "429 and above"], [500, "5xx only"]]
      .map(([v, l]) => h("option", { value: v, selected: String(v) === (store.pref("log_status") || "0") ? "selected" : null }, l)));
    const query = store.pref("log_q") ? `&q=${encodeURIComponent(store.pref("log_q"))}` : "";
    const logs = await api(`/api/v1/telemetry/logs?minutes=${minutes}&limit=200&min_status=${store.pref("log_status") || 0}${query}`);
    body = h("div", { class: "card" }, h("form", { class: "row toolbar", onsubmit: (e) => { e.preventDefault(); store.pref("log_q", q.value); store.pref("log_status", status.value); render(true); } },
      q, status, h("button", { type: "submit", class: "secondary" }, "Search")), logsTable(logs));
  } else if (tab === "traces") {
    const traces = await api(`/api/v1/telemetry/traces?minutes=${minutes}&limit=50`);
    body = h("div", { class: "card" }, h("p", { class: "note" }, "Slowest requests first. Open one to see where its time went."),
      traces.length ? table(["Time", "Route", "Duration", "On-CPU", "Spans", "Status", ""], traces.map((x) => h("tr", {}, h("td", {}, fmtShort(x.event_time)),
        h("td", {}, h("code", {}, x.route || "")), h("td", {}, ms(x.duration_ms)), h("td", {}, x.cpu_ms != null ? ms(x.cpu_ms) : "n/a"), h("td", {}, x.spans),
        h("td", {}, badge(x.status || "unset", x.status === "error" ? "bad" : "good")),
        h("td", {}, h("button", { type: "button", class: "ref", onclick: () => openTrace(x.trace_id) }, "waterfall")))))
        : h("p", { class: "empty" }, "No traces in this window."));
  } else if (tab === "quality") {
    const q = await api(`/api/v1/telemetry/quality?window_seconds=${minutes * 60}`);
    body = h("div", { class: "card" }, h("p", {}, badge(q.status)), q.warnings.map((w) => h("p", { class: "banner" }, w.message)),
      table(["Service", "Events", "Stamped ahead of arrival", "Median ahead"], Object.entries(q.services).map(([svc, v]) =>
        h("tr", {}, h("td", {}, svc), h("td", {}, v.events), h("td", {}, v.ahead_of_arrival), h("td", {}, `${v.median_ahead_seconds} s`)))),
      h("p", { class: "note" }, `Not checked: ${q.not_checked}.`));
  } else {
    body = routeCharts(await api(`/api/v1/telemetry/series?minutes=${minutes}&bucket_seconds=${Math.max(10, minutes)}`), null);
  }
  return page("Telemetry", [tab, minutes, Math.floor(Date.now() / 30000)], h("div", { class: "row toolbar" }, h("label", { class: "check" }, "Range ", range)), tabs, body);
};

// ---- SLOs and error budgets ----------------------------------------------------------------------------

VIEWS.slo = async () => {
  const d = await api("/api/v1/slo");
  const bar = (x) => { const fill = h("span", {}); fill.style.width = `${Math.round(x * 100)}%`; return h("div", { class: "meter", title: pct(x) }, fill); };
  return page("SLOs", d.routes, h("div", { class: "card" }, h("h2", {}, "Service level objectives"),
    h("p", { class: "note" }, `Availability target ${pct(0.99)} of requests without a 5xx, latency target p95 at most 500 ms, over 24 hours. ${d.method}. A burn rate of ${d.fast_burn_threshold}x or more over the last hour notifies the team.`),
    d.routes.length ? table(["Route", "Availability (24 h)", "Error budget left", "", "Burn rate (1 h)", "p95 (24 h)", "Within latency target"], d.routes.map((r) =>
      h("tr", {}, h("td", {}, h("code", {}, r.route)), h("td", {}, pct(r.availability_24h)), h("td", {}, pct(r.error_budget_remaining)), h("td", {}, bar(r.error_budget_remaining)),
        h("td", {}, badge(`${r.burn_rate_1h}x`, r.fast_burn ? "bad" : r.burn_rate_1h >= 1 ? "warn" : "good")),
        h("td", {}, ms(r.p95_ms_24h)), h("td", {}, pct(r.within_latency_target_24h))))) : h("p", { class: "empty" }, "No requests in the last 24 hours.")));
};

// ---- automation -------------------------------------------------------------------------------------

VIEWS.automation = async () => {
  const a = await api("/api/v1/automation");
  const admin = can("admin");
  const off = admin ? null : "disabled";
  const rows = a.policies.map((p) => {
    const mode = h("select", { "aria-label": `Mode for ${p.cause}`, disabled: off }, ["manual", "propose", "auto"].map((m) => h("option", { value: m, selected: m === p.mode ? "selected" : null }, m)));
    const risk = h("select", { "aria-label": `Max risk for ${p.cause}`, disabled: off }, ["low", "medium"].map((m) => h("option", { value: m, selected: m === p.max_risk ? "selected" : null }, m)));
    const rb = h("input", { type: "checkbox", "aria-label": `Auto rollback for ${p.cause}`, checked: p.auto_rollback ? "checked" : null, disabled: off });
    return h("tr", {}, h("td", {}, humanize(p.cause)), h("td", {}, h("code", {}, p.action), " ", badge(`risk ${p.risk}`, p.risk === "low" ? "good" : "warn")),
      h("td", {}, mode), h("td", {}, risk), h("td", {}, rb), h("td", { class: "note" }, p.updated_by || "default"),
      h("td", {}, admin ? h("button", { type: "button", class: "secondary small",
        onclick: () => act("Save policy", () => api(`/api/v1/automation/policies/${p.cause}`, { method: "PUT", body: { mode: mode.value, max_risk: risk.value, auto_rollback: rb.checked } })) }, "Save") : null));
  });
  return page("Automation", a,
    h("div", { class: "card" }, h("div", { class: "card-head" }, h("h2", {}, "Automatic remediation"), badge(a.enabled ? "on" : "off", a.enabled ? "good" : "neutral"),
      admin ? h("button", { type: "button", class: a.enabled ? "danger" : "", disabled: !a.allowed && !a.enabled ? "disabled" : null,
        onclick: () => act(a.enabled ? "Turn automation off" : "Turn automation on", () => api("/api/v1/automation", { method: "PUT", body: { enabled: !a.enabled } })) }, a.enabled ? "Turn off" : "Turn on") : null,
      admin ? h("button", { type: "button", class: "secondary", onclick: () => act("Automation pass", async () => { const res = await api("/api/v1/automation/run", { method: "POST" }); toast(`${res.steps.length} step(s)`); }) }, "Run a pass now") : null),
      h("p", { class: "note" }, `Manual is the default for every cause. Propose: SentinelOps opens the recommended contract; a person approves it. Auto: it also approves and executes, but only when the cause survived a decisive diagnostic, the rehearsal passed, the risk is within the policy, and fewer than ${a.max_actions_per_hour} actions ran in the last hour (now ${a.actions_last_hour}). Policy, production blocking, verification and the audit trail always apply.`),
      !a.allowed ? h("p", { class: "banner" }, "This deployment does not allow automation (SENTINEL_AUTOMATION_ALLOWED=false).") : null,
      table(["Cause", "Action", "Mode", "Max risk", "Auto rollback", "Set by", ""], rows)),
    h("div", { class: "card" }, h("h3", {}, "Recent automation steps"),
      a.recent_runs.length ? table(["Time", "Step", "Outcome", "Reason", "Incident"], a.recent_runs.map((x) => h("tr", {}, h("td", {}, fmtTime(x.at)), h("td", {}, x.step),
        h("td", {}, badge(x.outcome, "neutral")), h("td", { class: "wrap" }, x.reason),
        h("td", {}, h("button", { type: "button", class: "ref", onclick: () => go(`#/incident/${x.incident_id}/recovery`) }, x.incident_id.slice(0, 8))))))
        : h("p", { class: "empty" }, "No automation steps yet.")));
};

// ---- notifications -----------------------------------------------------------------------------------

VIEWS.notifications = async () => {
  const admin = can("admin");
  const [events, channels, log] = await Promise.all([api("/api/v1/notifications/events"), admin ? api("/api/v1/notifications/channels") : [],
    can("approver") ? api("/api/v1/notifications?limit=50") : []]);
  const name = h("input", { type: "text", placeholder: "e.g. #oncall", maxlength: "100", "aria-label": "Channel name", required: "required" });
  const kind = h("select", { "aria-label": "Channel kind" }, [["slack", "Slack (incoming webhook)"], ["webhook", "Generic webhook (signed JSON)"]].map(([v, l]) => h("option", { value: v }, l)));
  const url = h("input", { type: "url", placeholder: "https://hooks.slack.com/services/...", maxlength: "2000", "aria-label": "Webhook URL", required: "required" });
  const boxes = Object.entries(events).map(([k, label]) => ({ k, box: h("input", { type: "checkbox", value: k, checked: "checked" }), label }));
  const form = h("form", { class: "stack", onsubmit: (e) => {
    e.preventDefault();
    act("Add channel", async () => {
      const res = await api("/api/v1/notifications/channels", { method: "POST", body: { name: name.value, kind: kind.value, url: url.value,
        events: boxes.filter((b) => b.box.checked).map((b) => b.k) } });
      openDrawer("Channel added", h("p", {}, "Signing secret, shown once. Generic webhooks carry X-SentinelOps-Signature: sha256=HMAC(secret, body)."),
        h("pre", { class: "json" }, res.signing_secret));
    });
  } },
  h("div", { class: "row" }, h("label", { class: "field" }, "Name", name), h("label", { class: "field" }, "Kind", kind)),
  h("label", { class: "field" }, "URL (https, public address)", url),
  h("div", { class: "row" }, boxes.map((b) => h("label", { class: "check", title: b.label }, b.box, b.k))),
  h("div", {}, h("button", { type: "submit" }, "Add channel")));
  const channelRows = channels.map((c) => h("tr", {}, h("td", {}, c.name), h("td", {}, c.kind), h("td", {}, h("code", {}, c.host)),
    h("td", { class: "note" }, `${c.events.length} events`), h("td", {}, badge(c.enabled ? "enabled" : "paused", c.enabled ? "good" : "neutral")),
    h("td", {}, h("div", { class: "row" },
      h("button", { type: "button", class: "secondary small", onclick: () => act("Send test", async () => { const res = await api(`/api/v1/notifications/channels/${c.id}/test`, { method: "POST" }); toast(`sent ${res.sent}, failed ${res.failed}`); }) }, "Test"),
      h("button", { type: "button", class: "secondary small", onclick: () => act(c.enabled ? "Pause" : "Resume", () => api(`/api/v1/notifications/channels/${c.id}`, { method: "PATCH", body: { enabled: !c.enabled } })) }, c.enabled ? "Pause" : "Resume"),
      h("button", { type: "button", class: "danger small", onclick: () => act("Delete channel", () => api(`/api/v1/notifications/channels/${c.id}`, { method: "DELETE" })) }, "Delete")))));
  return page("Notifications", [channels, log.map((x) => [x.id, x.status])],
    h("div", { class: "card" }, h("h2", {}, "Tell the team"),
      h("p", { class: "note" }, "SentinelOps posts to Slack or any webhook when an incident opens, a cause is confirmed, a contract needs approval, a recovery passes or fails, a rollback runs, automation acts, requests are throttled (429), or telemetry cannot be trusted. Each message carries the evidence and a link back here."),
      admin ? null : h("p", { class: "note" }, "Only an admin can add or change channels.")),
    admin ? h("div", { class: "card" }, h("h3", {}, "Channels"),
      channels.length ? table(["Name", "Kind", "Host", "Events", "State", ""], channelRows) : h("p", { class: "note" }, "No channels yet."),
      h("h3", {}, "Add a channel"), form) : null,
    can("approver") ? h("div", { class: "card" }, h("h3", {}, "Delivery log"),
      log.length ? table(["Time", "Channel", "Event", "Status", "Attempts", "Message"], log.map((x) => h("tr", {}, h("td", {}, fmtTime(x.created_at)), h("td", {}, x.channel),
        h("td", {}, h("code", {}, x.event)), h("td", {}, badge(x.status)), h("td", {}, x.attempts, x.last_error ? h("div", { class: "note" }, x.last_error) : null),
        h("td", {}, h("details", {}, h("summary", {}, "text"), h("pre", { class: "artifact" }, x.text))))))
        : h("p", { class: "empty" }, "Nothing sent yet.")) : null);
};

// ---- model, audit, operators ---------------------------------------------------------------------------

VIEWS.model = async () => {
  const m = await api("/api/v1/models");
  const sv = m.serving, rm = m.research_model, res = (rm && rm.test_results) || {};
  return page("ML model", m, h("div", { class: "grid two" },
    h("div", { class: "card" }, h("h2", {}, "Serving model"), h("p", {}, badge(sv.version, "info"), " ", badge("shadow mode", "warn")),
      h("p", { class: "note" }, `${humanize(sv.algorithm)}. Names a cause only at ${pct(sv.tau)}+ confidence, otherwise "unknown". ${sv.mode}.`),
      h("h3", {}, `Classes (${sv.classes.length})`), h("p", { class: "row" }, sv.classes.map((c) => badge(humanize(c), "neutral"))),
      h("h3", {}, `Features (${sv.features.length})`), h("p", { class: "note" }, sv.features.map(humanize).join(", "))),
    h("div", { class: "card" }, h("h2", {}, "Research model"), rm ? [
      h("p", {}, badge(rm.version || "", "info"), " ", h("span", { class: "note" }, `${humanize(rm.algorithm)} · calibrated ${rm.calibration} · threshold ${rm.tau}`)),
      table(["Test set", "System", "Exact", "Wrong action", "Missed fixable"], Object.entries(res).map(([k, v]) => h("tr", {}, h("td", {}, k.split(" | ")[0]),
        h("td", {}, k.split(" | ")[1]), h("td", {}, pct(v.exact_accuracy)), h("td", {}, pct(v.incorrect_intervention_rate)), h("td", {}, pct(v.missed_actionable_rate))))),
      h("p", { class: "note" }, "Trained on simulated incidents; scored on real ones from the campaigns. See models/MODEL_CARD.md.")] : h("p", { class: "note" }, "Metadata not available."))));
};

VIEWS.audit = async () => {
  const rows = await api("/api/v1/audit?limit=200");
  return page("Audit log", rows.map((r) => r.at + r.action), h("div", { class: "card" },
    h("p", { class: "note" }, "Append-only: sign-ins, operator changes, notification channels, automation policies and every recovery contract transition."),
    rows.length ? table(["Time", "Actor", "Action", "Target", "Details"], rows.map((r) => h("tr", {}, h("td", {}, fmtTime(r.at)), h("td", {}, r.actor),
      h("td", {}, h("code", {}, r.action)), h("td", {}, r.target),
      h("td", { class: "note" }, Object.entries(r.details || {}).filter(([, v]) => v !== null && v !== "").map(([k, v]) => `${k}: ${typeof v === "object" ? JSON.stringify(v) : v}`).join("; ")))))
      : h("p", { class: "empty" }, "Nothing yet.")));
};

VIEWS.operators = async () => {
  const ops = await api("/api/v1/operators");
  const user = h("input", { type: "text", placeholder: "username", maxlength: "100", "aria-label": "New username", required: "required" });
  const pw = h("input", { type: "password", placeholder: "password (12+ characters)", minlength: "12", maxlength: "200", "aria-label": "New password", required: "required", autocomplete: "new-password" });
  const role = h("select", { "aria-label": "Role" }, ROLES.map((r) => h("option", { value: r, selected: r === "responder" ? "selected" : null }, r)));
  return page("Operators", ops,
    h("div", { class: "card" }, h("h2", {}, "People who can sign in"),
      h("p", { class: "note" }, "viewer reads · responder analyses, labels, proposes, executes and rolls back · approver also approves · admin also manages operators, channels and automation."),
      table(["User", "Role", "State", "Last sign-in", ""], ops.map((o) => {
        const sel = h("select", { "aria-label": `Role of ${o.username}` }, ROLES.map((r) => h("option", { value: r, selected: r === o.role ? "selected" : null }, r)));
        return h("tr", {}, h("td", {}, o.username), h("td", {}, sel), h("td", {}, badge(o.disabled ? "disabled" : "active", o.disabled ? "bad" : "good")),
          h("td", {}, o.last_login_at ? ago(o.last_login_at) : "never"),
          h("td", {}, h("div", { class: "row" },
            h("button", { type: "button", class: "secondary small", onclick: () => act("Change role", () => api(`/api/v1/operators/${o.username}`, { method: "PATCH", body: { role: sel.value } })) }, "Save role"),
            h("button", { type: "button", class: o.disabled ? "secondary small" : "danger small", onclick: () => act(o.disabled ? "Enable" : "Disable", () => api(`/api/v1/operators/${o.username}`, { method: "PATCH", body: { disabled: !o.disabled } })) }, o.disabled ? "Enable" : "Disable"))));
      }))),
    h("div", { class: "card" }, h("h3", {}, "Add an operator"),
      h("form", { class: "row", onsubmit: (e) => { e.preventDefault(); act("Add operator", () => api("/api/v1/operators", { method: "POST", body: { username: user.value.trim().toLowerCase(), password: pw.value, role: role.value } })); } },
        user, pw, role, h("button", { type: "submit" }, "Add"))));
};

// ---- session ---------------------------------------------------------------------------------------

function showShell() {
  const signedIn = Boolean(state.token);
  $("#signed-out").hidden = signedIn;
  $("#app").hidden = !signedIn;
  $("#login").hidden = signedIn || state.mode !== "operators";
  $("#connect").hidden = signedIn || state.mode !== "shared_token";
  $("#analyze").hidden = !can("responder");
  $("#whoami").textContent = !signedIn ? "" : state.mode === "operators" ? `Signed in as ${state.actor} (${state.role})` : `Acting as ${state.actor || "(no name)"}, unverified`;
}
async function signIn(token, actor, role) {
  Object.assign(state, { token, actor, role, signature: "" });
  store.set("sentinel_token", token); store.set("sentinel_actor", actor); store.set("sentinel_role", role || "");
  showShell();
  await render(true);
  schedule();
}
function signOut() {
  Object.assign(state, { token: "", actor: "", role: "" });
  ["sentinel_token", "sentinel_actor", "sentinel_role"].forEach((k) => store.set(k, ""));
  clearInterval(state.timer);
  $("#drawer").hidden = true;
  showShell();
}
function schedule() {
  clearInterval(state.timer);
  if (state.token && $("#auto").checked) state.timer = setInterval(() => render(false), 10000);
}
function applyTheme(t) {
  if (t === "light" || t === "dark") document.documentElement.setAttribute("data-theme", t);
  else document.documentElement.removeAttribute("data-theme");
}

$("#login").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const status = $("#login-status");
  status.textContent = "Signing in...";
  status.className = "status-line";
  try {
    const res = await fetch("/api/v1/auth/login", { method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ username: $("#username").value.trim(), password: $("#password").value }) });
    const data = await res.json().catch(() => null);
    $("#password").value = "";
    if (!res.ok) throw new Error((data && (data.detail || data.error)) || `HTTP ${res.status}`);
    status.textContent = "";
    await signIn(data.token, data.username, data.role);
    toast(`Signed in. Session ends ${fmtTime(data.expires_at)}.`);
  } catch (err) {
    status.textContent = `Sign-in failed: ${err.message}`;
    status.className = "status-line error";
  }
});
$("#connect").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  await signIn($("#token").value.trim(), $("#actor").value.trim(), "");
});
$("#logout").addEventListener("click", async () => {
  if (state.mode === "operators") await api("/api/v1/auth/logout", { method: "POST" }).catch(() => null);
  signOut();
});
$("#analyze").addEventListener("click", () => act("Analyze", () => api("/api/v1/incidents/analyze", { method: "POST" })));
$("#auto").addEventListener("change", schedule);
$("#menu").addEventListener("click", () => $("#sidebar").classList.toggle("open"));
$("#drawer-close").addEventListener("click", () => { $("#drawer").hidden = true; });
document.addEventListener("keydown", (e) => { if (e.key === "Escape") $("#drawer").hidden = true; });
$("#theme").addEventListener("click", () => {
  const order = ["system", "light", "dark"];
  const next = order[(order.indexOf(store.pref("theme") || "system") + 1) % order.length];
  store.pref("theme", next);
  applyTheme(next);
  toast(`Theme: ${next}`);
});
window.addEventListener("hashchange", () => { state.signature = ""; render(true); });

applyTheme(store.pref("theme"));
fetch("/api/v1/auth/mode").then((r) => r.json()).then((m) => {
  state.mode = m.mode;
  state.shopUrl = /^https?:\/\//.test(m.shop_url || "") ? m.shop_url : null;  // only ever an http(s) link
  showShell();
  if (m.mode === "operators" && !m.login_configured) $("#login-status").textContent = "Sign-in is not configured on this server (SENTINEL_SESSION_SECRET is unset).";
  if (state.token) render(true).then(schedule);
}).catch(() => { $("#signed-out").hidden = false; $("#login").hidden = false; $("#login-status").textContent = "Cannot reach the API."; });
