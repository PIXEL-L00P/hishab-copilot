"use strict";
// HishabAI front end. Plain JavaScript; all text is inserted with textContent (no innerHTML with data).

const state = { token: null, user: null, bid: null, role: null, lang: "en", plan: null, cash: null };
const $ = (id) => document.getElementById(id);

function el(tag, attrs = {}, ...children) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") n.className = v;
    else if (k === "style") n.style.cssText = v;   // CSSOM is allowed by our CSP; style attributes are not
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else n.setAttribute(k, v);
  }
  for (const c of children.flat()) {
    if (c === null || c === undefined) continue;
    n.appendChild(typeof c === "string" || typeof c === "number" ? document.createTextNode(String(c)) : c);
  }
  return n;
}

function bdt(x) {
  if (x === null || x === undefined || isNaN(x)) return "—";
  const neg = x < 0; let s = String(Math.round(Math.abs(x)));
  if (s.length > 3) {
    let head = s.slice(0, -3); const tail = s.slice(-3); const g = [];
    while (head.length > 2) { g.unshift(head.slice(-2)); head = head.slice(0, -2); }
    if (head) g.unshift(head);
    s = g.join(",") + "," + tail;
  }
  return (neg ? "-" : "") + "৳" + s;
}
const pct = (x) => (x === null || x === undefined ? "—" : (x * 100).toFixed(0) + "%");

async function api(path, opts = {}) {
  const headers = { "Content-Type": "application/json" };
  if (state.token) headers["Authorization"] = "Bearer " + state.token;
  const res = await fetch(path, { method: opts.method || "GET", headers,
    body: opts.body ? JSON.stringify(opts.body) : undefined });
  const data = await res.json().catch(() => ({}));
  if (res.status === 401 && state.token) { logout(); throw new Error("Session expired"); }
  if (!res.ok) throw new Error(data.error || ("HTTP " + res.status));
  return data;
}

// ------------------------------------------------------------------ login
document.querySelectorAll(".demo-users button").forEach((b) =>
  b.addEventListener("click", () => { $("username").value = b.dataset.u; $("password").value = b.dataset.p; }));

$("loginForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  $("loginError").textContent = "";
  try {
    const r = await api("/api/login", { method: "POST", body: { username: $("username").value, password: $("password").value } });
    state.token = r.token; state.user = r.user;
    const m = r.memberships[0];
    if (!m) throw new Error("This account is not linked to any business.");
    state.bid = m.business_id; state.role = m.role;
    $("bizName").textContent = m.role === "lender" ? r.user.full_name : m.name;
    $("roleBadge").textContent = m.role;
    $("loginView").classList.add("hidden"); $("topright").classList.remove("hidden");
    $("password").value = "";
    if (m.role === "lender") { $("lenderView").classList.remove("hidden"); loadLender(); }
    else { $("appView").classList.remove("hidden"); loadApp(); }
  } catch (err) { $("loginError").textContent = err.message; }
});

async function logout() {
  try { if (state.token) await fetch("/api/logout", { method: "POST", headers: { Authorization: "Bearer " + state.token } }); } catch (e) { /* ignore */ }
  location.reload();
}
$("logoutBtn").addEventListener("click", logout);
$("langBtn").addEventListener("click", () => {
  state.lang = state.lang === "en" ? "bn" : "en";
  $("langBtn").textContent = state.lang === "en" ? "বাংলা" : "English";
});

// ------------------------------------------------------------------ dashboard
async function loadApp() {
  const [sum, hist, fc, cash] = await Promise.all([
    api(`/api/businesses/${state.bid}/summary`), api(`/api/businesses/${state.bid}/history`),
    api(`/api/businesses/${state.bid}/forecast`), api(`/api/businesses/${state.bid}/cash`)]);
  state.cash = cash;
  renderKpis(sum.summary);
  renderAlert(cash);
  drawSales(hist.weeks.slice(-26), fc);
  drawCash(cash, null);
  $("forecastNote").textContent = `Model: ${fc.method}. Shaded area = ${fc.band || "range"}.`;
  if (state.role !== "owner") {
    $("checkBtn").title = "Accountants can run the check; only the owner can approve actions.";
  }
  refreshPending(); showTab("dues"); loadBenchmark();
}

async function loadBenchmark() {
  const box = $("benchmark");
  try {
    const b = await api(`/api/businesses/${state.bid}/benchmark`);
    if (!b.available) { box.replaceChildren(el("p", { class: "muted" }, b.message)); return; }
    $("benchNote").textContent = `${b.privacy} Overall you do better than about ${b.overall_percentile}% of them. ${b.data_note}`;
    const rows = b.metrics.filter((m) => m.available).map((m) => el("tr", {},
      el("td", {}, m.label, m.tip ? el("div", { class: "tip" }, "→ " + m.tip) : ""),
      el("td", { class: "num" }, m.you_display), el("td", { class: "num" }, m.median_display),
      el("td", {}, el("div", { class: "rankbar " + m.status }, el("span", { style: `width:${m.percentile_rank}%` })),
        el("div", { class: "muted small" }, `better than ${m.percentile_rank}%`)),
      el("td", {}, el("span", { class: "status " + m.status }, m.status))));
    box.replaceChildren(el("table", {}, el("tr", {}, el("th", {}, "Measure"), el("th", { class: "num" }, "You"),
      el("th", { class: "num" }, "Peer median"), el("th", {}, "Rank"), el("th", {}, "")), rows));
  } catch (e) { box.textContent = "Error: " + e.message; }
}

function renderKpis(s) {
  const k = [
    ["Cash in hand", bdt(s.cash_balance), `runway ≈ ${s.cash_runway_weeks ?? "—"} weeks`],
    ["Sales, last 12 weeks", bdt(s.sales_last_12_weeks), `vs last year ${s.sales_growth_yoy_12w === null ? "—" : (s.sales_growth_yoy_12w * 100).toFixed(1) + "%"}`],
    ["Gross margin", pct(s.gross_margin_estimate), "estimated from stock purchases"],
    ["Break-even sales", bdt(s.break_even_monthly_sales), "per month"],
    ["Debt coverage (DSCR)", s.dscr ?? "—", `instalments ${bdt(s.debt_service_monthly)}/month`],
    ["Overdue customer dues", bdt(s.receivables_overdue), `${s.overdue_customers} customer(s)`],
  ];
  $("kpis").replaceChildren(...k.map(([l, v, sub]) =>
    el("div", { class: "kpi" }, el("div", { class: "label" }, l), el("div", { class: "value" }, v), el("div", { class: "sub" }, sub))));
}

function renderAlert(cash) {
  const e = cash.expected, lvl = cash.alert_level;
  $("alertBox").className = "alert " + lvl;
  const titles = { critical: "Cash shortfall ahead", warning: "Cash is getting tight", healthy: "Cash flow looks healthy" };
  $("alertTitle").textContent = titles[lvl];
  const wk = e.first_negative_week || e.first_below_buffer_week;
  $("alertText").textContent = lvl === "healthy"
    ? `Lowest expected balance in the next 8 weeks: ${bdt(e.min_cash)}.`
    : `Expected to drop below ${lvl === "critical" ? "zero" : "your safety buffer"} in the week of ${e.weeks[wk - 1].week_start}; lowest ${bdt(e.min_cash)} in week ${e.min_cash_week}.`;
}

// ------------------------------------------------------------------ SVG charts
const NS = "http://www.w3.org/2000/svg";
function svg(tag, attrs) { const n = document.createElementNS(NS, tag); for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v); return n; }

function chartFrame(container, xs, yMin, yMax) {
  const W = 560, H = 250, L = 56, R = 12, T = 12, B = 30;
  const root = svg("svg", { viewBox: `0 0 ${W} ${H}`, role: "img" });
  const sx = (i) => L + (i * (W - L - R)) / Math.max(xs.length - 1, 1);
  const sy = (v) => T + ((yMax - v) * (H - T - B)) / (yMax - yMin || 1);
  for (let k = 0; k <= 4; k++) {
    const v = yMin + ((yMax - yMin) * k) / 4, y = sy(v);
    root.appendChild(svg("line", { x1: L, x2: W - R, y1: y, y2: y, stroke: "#e5ebe6" }));
    const t = svg("text", { x: L - 6, y: y + 4, "text-anchor": "end" }); t.textContent = Math.abs(v) >= 1e5 ? (v / 1e5).toFixed(1) + "L" : Math.round(v / 1e3) + "k"; root.appendChild(t);
  }
  xs.forEach((d, i) => { if (i % Math.ceil(xs.length / 6) === 0 || i === xs.length - 1) {
    const t = svg("text", { x: sx(i), y: H - 10, "text-anchor": "middle" }); t.textContent = d.slice(5); root.appendChild(t); } });
  container.replaceChildren(root);
  return { root, sx, sy };
}
const path = (pts) => pts.map((p, i) => (i ? "L" : "M") + p[0].toFixed(1) + "," + p[1].toFixed(1)).join(" ");

function drawSales(hist, fc) {
  const xs = hist.map((w) => w.week_start).concat(fc.weeks.map((w) => w.week_start));
  const vals = hist.map((w) => w.sales).concat(fc.weeks.map((w) => w.high));
  const { root, sx, sy } = chartFrame($("salesChart"), xs, 0, Math.max(...vals) * 1.08);
  const n = hist.length;
  const band = fc.weeks.map((w, i) => [sx(n + i), sy(w.high)]).concat(fc.weeks.map((w, i) => [sx(n + i), sy(w.low)]).reverse());
  root.appendChild(svg("path", { d: path(band) + " Z", fill: "#cfe3f6" }));
  root.appendChild(svg("path", { d: path(hist.map((w, i) => [sx(i), sy(w.sales)])), fill: "none", stroke: "#1b2a24", "stroke-width": 2 }));
  root.appendChild(svg("path", { d: path([[sx(n - 1), sy(hist[n - 1].sales)]].concat(fc.weeks.map((w, i) => [sx(n + i), sy(w.p50)]))),
    fill: "none", stroke: "#1f5fa8", "stroke-width": 2, "stroke-dasharray": "5 4" }));
}

function drawCash(cash, after) {
  const e = cash.expected, p = cash.pessimistic;
  const xs = e.weeks.map((w) => w.week_start);
  const all = e.weeks.map((w) => w.closing_cash).concat(p.weeks.map((w) => w.closing_cash), [e.safety_buffer, 0, e.starting_cash]);
  if (after) all.push(...after.map((w) => w.closing_cash));
  const lo = Math.min(...all), hi = Math.max(...all), pad = (hi - lo) * 0.08;
  const { root, sx, sy } = chartFrame($("cashChart"), xs, lo - pad, hi + pad);
  root.appendChild(svg("line", { x1: sx(0), x2: sx(xs.length - 1), y1: sy(0), y2: sy(0), stroke: "#b42318", "stroke-width": 1 }));
  root.appendChild(svg("line", { x1: sx(0), x2: sx(xs.length - 1), y1: sy(e.safety_buffer), y2: sy(e.safety_buffer), stroke: "#a15c07", "stroke-dasharray": "4 4" }));
  root.appendChild(svg("path", { d: path(p.weeks.map((w, i) => [sx(i), sy(w.closing_cash)])), fill: "none", stroke: "#c98b8b", "stroke-width": 1.5, "stroke-dasharray": "3 3" }));
  root.appendChild(svg("path", { d: path(e.weeks.map((w, i) => [sx(i), sy(w.closing_cash)])), fill: "none", stroke: "#1b2a24", "stroke-width": 2 }));
  if (after) root.appendChild(svg("path", { d: path(after.map((w, i) => [sx(i), sy(w.closing_cash)])), fill: "none", stroke: "#127a3a", "stroke-width": 2.5 }));
  const legend = [["#1b2a24", "Expected"], ["#c98b8b", "If sales are weak"], ["#127a3a", after ? "After plan" : null]];
  legend.filter((l) => l[1]).forEach(([c, t], i) => {
    root.appendChild(svg("rect", { x: 64 + i * 130, y: 16, width: 12, height: 3, fill: c }));
    const tx = svg("text", { x: 80 + i * 130, y: 20 }); tx.textContent = t; root.appendChild(tx);
  });
}

// ------------------------------------------------------------------ agent
$("checkBtn").addEventListener("click", async () => {
  const b = $("checkBtn"); b.disabled = true; b.textContent = "Analysing…";
  try {
    const r = await api(`/api/businesses/${state.bid}/agent/check`, { method: "POST", body: { language: state.lang } });
    $("briefing").textContent = r.briefing;
    if (r.plan) drawCash(state.cash, r.plan.projection_after);
    if (r.financing) renderFinancing(r.financing);
    refreshPending(); if (currentTab === "actions") showTab("actions");
  } catch (e) { $("briefing").textContent = "Error: " + e.message; }
  b.disabled = false; b.textContent = "Run cash check";
});

async function refreshPending() {
  const r = await api(`/api/businesses/${state.bid}/actions?status=pending_approval`);
  const box = $("pending");
  if (!r.actions.length) { box.replaceChildren(el("p", { class: "muted" }, "Nothing pending.")); return; }
  box.replaceChildren(...r.actions.map((a) => {
    const btns = state.role === "owner"
      ? el("div", { class: "btns" },
          el("button", { class: "primary", onclick: () => decide(a.id, "approve") }, "Approve"),
          el("button", { onclick: () => decide(a.id, "reject") }, "Reject"))
      : el("span", { class: "muted small" }, "Owner approval needed");
    return el("div", { class: "pending-item" },
      el("div", {}, el("span", { class: "tag t2" }, "Tier 2"), " ", a.summary,
        el("div", { class: "msg" }, (a.preview && a.preview.message) ? "Message: " + a.preview.message : "")), btns);
  }));
}

async function decide(id, verb) {
  try { await api(`/api/actions/${id}/${verb}`, { method: "POST" }); }
  catch (e) { alert(e.message); }
  refreshPending(); showTab(currentTab);
}

$("chatForm").addEventListener("submit", (e) => { e.preventDefault(); sendChat($("chatInput").value); });
document.querySelectorAll(".chips button").forEach((b) => b.addEventListener("click", () => sendChat(b.dataset.q)));

async function sendChat(text) {
  if (!text.trim()) return;
  $("chatInput").value = "";
  const log = $("chatLog");
  log.appendChild(el("div", { class: "bubble me" }, text));
  const wait = el("div", { class: "bubble ai" }, "…"); log.appendChild(wait); log.scrollTop = log.scrollHeight;
  try {
    const r = await api(`/api/businesses/${state.bid}/agent/chat`, { method: "POST", body: { message: text } });
    const tools = (r.tool_calls || []).map((t) => `${t.tool} → ${t.status}`).join(" · ");
    wait.replaceChildren(document.createTextNode(r.reply), tools ? el("div", { class: "tools" }, "tools: " + tools) : "");
    if (r.data && r.data.options) renderFinancing(r.data);
    refreshPending();
  } catch (e) { wait.textContent = "Error: " + e.message; }
  log.scrollTop = log.scrollHeight;
}

// ------------------------------------------------------------------ scenario + financing
$("scenarioForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = new FormData(e.target), n = (k) => Number(f.get(k) || 0);
  const body = { sales_change_pct: n("sales_change_pct"), purchase_cost_change_pct: n("purchase_cost_change_pct"),
    extra_monthly_fixed: n("extra_monthly_fixed"), one_time_cost: n("one_time_cost"), loan_amount: n("loan_amount"),
    loan_annual_rate: n("loan_rate") / 100, loan_months: Math.round(n("loan_months")) };
  try {
    const r = await api(`/api/businesses/${state.bid}/scenario`, { method: "POST", body });
    $("scenarioOut").replaceChildren(el("table", {},
      el("tr", {}, el("th", {}, ""), el("th", { class: "num" }, "Now"), el("th", { class: "num" }, "Scenario")),
      el("tr", {}, el("td", {}, "Lowest cash, next 8 weeks"), el("td", { class: "num" }, bdt(r.baseline_min_cash)), el("td", { class: "num" }, bdt(r.scenario_min_cash))),
      el("tr", {}, el("td", {}, "Monthly profit (approx.)"), el("td", { class: "num" }, bdt(r.baseline_monthly_profit)), el("td", { class: "num" }, bdt(r.scenario_monthly_profit))),
      el("tr", {}, el("td", {}, "New loan instalment"), el("td", { class: "num" }, "—"), el("td", { class: "num" }, bdt(r.new_loan_monthly_instalment)))),
      el("p", { class: r.affordable ? "ok" : "bad" }, r.affordable ? "Affordable: cash stays above the safety buffer." : "Not affordable: cash falls below the safety buffer or profit turns negative."));
  } catch (err) { $("scenarioOut").textContent = "Error: " + err.message; }
});

function renderFinancing(fin) {
  const rows = fin.options.map((o) => el("tr", {},
    el("td", {}, o.name, el("div", { class: "muted small" }, o.eligible ? o.why_eligible.join("; ") : o.why_not.join("; "))),
    el("td", {}, o.eligible ? (o.fast_enough ? el("span", { class: "ok" }, "Eligible") : el("span", { class: "muted" }, "Eligible, too slow")) : el("span", { class: "bad" }, "Not eligible")),
    el("td", { class: "num" }, o.provider_type === "supplier" ? "—" : bdt(o.monthly_instalment)),
    el("td", {}, o.indicative_rate), el("td", { class: "num" }, String(o.processing_days) + " d")));
  $("financing").replaceChildren(
    el("p", { class: "small" }, `Need: ${bdt(fin.need_amount)}${fin.needed_by ? " by " + fin.needed_by : ""}`),
    el("table", {}, el("tr", {}, el("th", {}, "Option"), el("th", {}, "Status"), el("th", { class: "num" }, "Monthly"), el("th", {}, "Rate"), el("th", { class: "num" }, "Time")), rows),
    el("p", { class: "muted small" }, fin.disclaimer));
}

// ------------------------------------------------------------------ tabs
let currentTab = "dues";
document.querySelectorAll(".tabs button").forEach((b) => b.addEventListener("click", () => showTab(b.dataset.tab)));

async function showTab(tab) {
  currentTab = tab;
  document.querySelectorAll(".tabs button").forEach((b) => b.classList.toggle("active", b.dataset.tab === tab));
  const body = $("tabBody");
  try {
    if (tab === "dues") {
      const r = await api(`/api/businesses/${state.bid}/receivables`);
      body.replaceChildren(table(["Customer", "Amount", "Due", "Status", "Note (untrusted text)"], r.receivables.map((x) =>
        [x.customer_name, bdt(x.amount), x.due_date, x.status, el("span", { class: "note-untrusted" }, x.note || "")]), [1]));
    } else if (tab === "bills") {
      const r = await api(`/api/businesses/${state.bid}/payables`);
      body.replaceChildren(table(["Pay to", "For", "Amount", "Due", "Flexible", "Status"], r.payables.map((x) =>
        [x.counterparty, x.description, bdt(x.amount), x.due_date, x.flexible ? "yes" : "no", x.status]), [2]));
    } else if (tab === "outbox") {
      if (state.role !== "owner") { body.replaceChildren(el("p", { class: "muted" }, "Only the owner can view sent messages.")); return; }
      const r = await api(`/api/businesses/${state.bid}/outbox`);
      body.replaceChildren(r.outbox.length ? table(["Time", "Channel", "To", "Message"], r.outbox.map((x) => [x.created_at, x.channel, x.recipient, x.message]))
        : el("p", { class: "muted" }, "No messages sent yet. Approved reminders and requests appear here (sandbox, not real SMS)."));
    } else if (tab === "actions") {
      const r = await api(`/api/businesses/${state.bid}/actions`);
      body.replaceChildren(table(["#", "Tool", "Tier", "Status", "Time"], r.actions.map((a) =>
        [String(a.id), a.tool, el("span", { class: "tag t" + a.tier }, "Tier " + a.tier), a.status, a.created_at])));
    } else if (tab === "audit") {
      if (state.role !== "owner") { body.replaceChildren(el("p", { class: "muted" }, "Only the owner can view the audit trail.")); return; }
      const r = await api(`/api/businesses/${state.bid}/audit`);
      body.replaceChildren(el("p", { class: r.chain.valid ? "ok" : "bad" },
        r.chain.valid ? `Hash chain verified: ${r.chain.entries_checked} entries, no tampering detected.` : `Hash chain BROKEN at entry ${r.chain.broken_at_id}.`),
        table(["Time (UTC)", "Event", "Detail"], r.entries.map((x) => [x.ts.slice(0, 19).replace("T", " "), x.event, x.detail_json.slice(0, 140)])));
    }
  } catch (e) { body.textContent = "Error: " + e.message; }
}

function table(head, rows, numCols = []) {
  return el("table", {}, el("tr", {}, head.map((h, i) => el("th", { class: numCols.includes(i) ? "num" : "" }, h))),
    rows.map((r) => el("tr", {}, r.map((c, i) => el("td", { class: numCols.includes(i) ? "num" : "" }, c)))));
}

// ------------------------------------------------------------------ lender
async function loadLender() {
  const r = await api("/api/lender/reports");
  const box = $("lenderReports");
  if (!r.reports.length) { box.replaceChildren(el("p", { class: "muted" }, "No reports have been shared with you yet.")); return; }
  box.replaceChildren(...r.reports.map((x) => {
    const k = x.report.key_figures;
    return el("div", { class: "report" }, el("h3", {}, `${x.business_name} — shared ${x.created_at}`),
      table(["Figure", "Value"], [
        ["Average monthly sales", bdt(k.avg_monthly_sales_12w)], ["Gross margin (est.)", pct(k.gross_margin_estimate)],
        ["Operating cash flow / month", bdt(k.operating_cash_flow_monthly)], ["Existing debt service / month", bdt(k.debt_service_monthly)],
        ["DSCR", String(k.dscr)], ["Overdue receivables", bdt(k.receivables_overdue)], ["Open payables", bdt(k.payables_open)]]),
      x.report.peer_comparison && x.report.peer_comparison.available
        ? el("p", { class: "small" }, `Peer comparison: better than about ${x.report.peer_comparison.overall_percentile}% of ${x.report.peer_comparison.peer_count} similar shops (anonymised).`)
        : "",
      el("p", { class: "muted small" }, x.report.data_provenance + " " + x.report.limitations.join(" ")));
  }));
}
