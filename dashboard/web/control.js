"use strict";

/* ==================================================================
   HM Control — owner panel (served only at the hidden URL)
   ================================================================== */

const $ = (id) => document.getElementById(id);
const state = { view: "overview" };

/* ------------------------------------------------------------------ */
/* helpers                                                             */
/* ------------------------------------------------------------------ */
function esc(text) {
  return String(text).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );
}

function el(tag, cls, html) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (html != null) node.innerHTML = html;
  return node;
}

function fmtMoney(v, sign = false) {
  if (v == null || Number.isNaN(Number(v))) return "—";
  const n = Number(v);
  const s = n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return sign ? (n >= 0 ? "+" + s : s) : s;
}

function fmtDT(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  return isNaN(d) ? "—" : d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

function pill(text, kind) {
  return `<span class="pill ${kind || ""}">${esc(text)}</span>`;
}

function statCard(label, value, cls) {
  const card = el("div", "stat");
  card.innerHTML = `<div class="v ${cls || ""}">${esc(value)}</div><div class="l">${esc(label)}</div>`;
  return card;
}

function rule() {
  return el("hr", "rule");
}

function smallBtn(label, fn, kind = "") {
  const b = el("button", `btn sm ${kind}`, label);
  b.onclick = async () => {
    try {
      await fn();
    } catch (ex) {
      toast(ex.message || "Action failed", "error");
    }
  };
  return b;
}

function setPath(obj, path, value) {
  const parts = path.split(".");
  let cur = obj;
  parts.forEach((p, i) => {
    if (i === parts.length - 1) cur[p] = value;
    else {
      cur[p] = cur[p] || {};
      cur = cur[p];
    }
  });
}

let toastTimer = null;
function toast(message, kind = "") {
  const t = $("toast");
  t.textContent = message;
  t.className = "toast show " + kind;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (t.className = "toast"), 3200);
}

async function api(path, options) {
  const res = await fetch(path, options);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || res.statusText || "Request failed");
  return data;
}

function postJSON(path, body) {
  return api(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

/* ------------------------------------------------------------------ */
/* dialogs                                                             */
/* ------------------------------------------------------------------ */
function openDialog({ title, sub, body, buttons = [] }) {
  closeDialog();
  const backdrop = el("div", "dialog-backdrop");
  const box = el("div", "dialog");
  box.appendChild(el("h3", "dialog-title", title));
  if (sub) box.appendChild(el("p", "dialog-sub", sub));
  box.appendChild(body);
  const row = el("div", "row-actions");
  row.style.marginTop = "18px";
  buttons.forEach((btn) => {
    const b = el("button", `btn ${btn.kind || ""}`, btn.label);
    b.onclick = async () => {
      const keep = btn.close !== false ? closeDialog : () => {};
      await btn.fn(keep);
    };
    row.appendChild(b);
  });
  box.appendChild(row);
  backdrop.appendChild(box);
  backdrop.onclick = (e) => {
    if (e.target === backdrop) closeDialog();
  };
  document.body.appendChild(backdrop);
  return backdrop;
}

function closeDialog() {
  document.querySelectorAll(".dialog-backdrop").forEach((n) => n.remove());
}

function showKeyDialog(title, key) {
  const body = el("div", "");
  body.appendChild(el("p", "muted", "Send this key to the customer. They paste it into the dashboard once to activate."));
  body.appendChild(el("div", "key-box", esc(key)));
  openDialog({
    title,
    sub: "HM-XXXX-…",
    body,
    buttons: [
      {
        label: "Copy",
        kind: "primary",
        fn: async (done) => {
          try {
            await navigator.clipboard.writeText(key);
            toast("Key copied", "success");
          } catch (e) {}
          done();
        },
      },
      { label: "Close", kind: "ghost", fn: async (done) => done() },
    ],
  });
}

/* ------------------------------------------------------------------ */
/* boot / login                                                        */
/* ------------------------------------------------------------------ */
async function boot() {
  try {
    const res = await api("/api/control/session");
    if (res.authed) showPanel();
    else showLogin();
  } catch (ex) {
    showLogin();
  }
}

function showLogin() {
  $("login-view").hidden = false;
  $("panel-view").hidden = true;
  $("login-user").focus();
}

function showPanel() {
  $("login-view").hidden = true;
  $("panel-view").hidden = false;
  switchView(state.view);
}

async function doLogin(e) {
  e.preventDefault();
  const user = $("login-user").value.trim();
  const pass = $("login-pass").value;
  const err = $("login-err");
  err.textContent = "";
  if (!user || !pass) {
    err.textContent = "Enter username and password.";
    return;
  }
  const btn = $("login-form").querySelector("button");
  btn.disabled = true;
  btn.textContent = "Checking…";
  try {
    const res = await postJSON("/api/control/login", { username: user, password: pass });
    if (!res.ok) throw new Error(res.error || "Login failed");
    $("login-pass").value = "";
    showPanel();
  } catch (ex) {
    err.textContent = ex.message || "Login failed";
  } finally {
    btn.disabled = false;
    btn.textContent = "Unlock";
  }
}

async function doLogout() {
  try {
    await postJSON("/api/control/logout", {});
  } catch (e) {}
  showLogin();
}

/* ------------------------------------------------------------------ */
/* navigation                                                          */
/* ------------------------------------------------------------------ */
const VIEWS = {
  overview: "Overview",
  settings: "Settings",
  users: "Users",
  payments: "Payments",
  keys: "License keys",
  trades: "Trades",
  logs: "Logs",
  security: "Security",
};

function switchView(view) {
  state.view = view;
  document.querySelectorAll(".nav-btn").forEach((b) => b.classList.toggle("active", b.dataset.view === view));
  $("page-title").textContent = VIEWS[view];
  const topRight = $("top-right");
  topRight.innerHTML = "";
  const content = $("content");
  content.innerHTML = `<div class="empty">Loading…</div>`;
  const renderers = {
    overview: renderOverview,
    settings: renderSettings,
    users: renderUsers,
    payments: renderPayments,
    keys: renderKeys,
    trades: renderTrades,
    logs: renderLogs,
    security: renderSecurity,
  };
  renderers[view](content, topRight);
}

/* ------------------------------------------------------------------ */
/* overview                                                            */
/* ------------------------------------------------------------------ */
async function renderOverview(content, topRight) {
  try {
    const res = await api("/api/control/overview");
    const s = res.store || {};
    const e = res.engine || {};
    const isLive = /live/i.test(e.status || "");
    const running = /running|trading|live|paper/i.test(e.status || "");

    const controls = el("div", "row-actions");
    if (!running) controls.appendChild(smallBtn("Start", () => engineAction("start")));
    if (running) {
      controls.appendChild(smallBtn("Pause", () => engineAction("pause")));
      controls.appendChild(smallBtn("Stop", () => engineAction("stop"), "danger"));
    }
    controls.appendChild(smallBtn("Reset limits", () => engineAction("reset_limits")));
    controls.appendChild(smallBtn("Close all", () => engineAction("close_all"), "danger"));
    topRight.appendChild(controls);

    content.innerHTML = "";
    const stats = [
      ["MT5 accounts", s.total_users ?? 0],
      ["Active", s.active_users ?? 0],
      ["Pending payments", s.pending_payments ?? 0],
      ["Paid payments", s.paid_payments ?? 0],
      ["Revenue", "$" + fmtMoney(s.revenue_usd)],
      ["Keys issued", s.total_keys ?? 0],
    ];
    const grid = el("div", "stat-grid");
    stats.forEach(([l, v]) => grid.appendChild(statCard(l, v, l === "Revenue" ? "up" : "")));
    content.appendChild(grid);

    const engineCard = el("div", "card");
    engineCard.appendChild(el("h3", "card-title", "Trading engine"));
    const dotCls = isLive ? "live" : running ? "warn" : "";
    const line = el("p", "", "");
    line.appendChild(el("span", "engine-dot " + dotCls));
    line.appendChild(
      document.createTextNode(
        `${e.mode || e.status || "IDLE"}${e.symbol ? " · " + e.symbol : ""}${e.connected ? " · connected" : ""}`
      )
    );
    engineCard.appendChild(line);
    const mini = el("div", "stat-grid");
    mini.appendChild(statCard("Day P/L", fmtMoney(e.day_profit)));
    mini.appendChild(statCard("Win rate", (e.win_rate ?? 0) + "%"));
    mini.appendChild(statCard("Trades today", e.trades_today ?? 0));
    mini.appendChild(statCard("Spread", e.spread ?? "—"));
    engineCard.appendChild(mini);
    content.appendChild(engineCard);

    const payCard = el("div", "card");
    payCard.appendChild(el("h3", "card-title", "Recent payments"));
    if (!res.payments || !res.payments.length) {
      payCard.appendChild(el("p", "empty", "No payments yet — create one in Payments."));
    } else {
      payCard.appendChild(paymentTable(res.payments.slice(0, 8)));
    }
    content.appendChild(payCard);
  } catch (ex) {
    content.innerHTML = "";
    content.appendChild(el("p", "empty", "Failed to load: " + esc(ex.message)));
  }
}

async function engineAction(action) {
  try {
    const res = await postJSON("/api/control/action", { action });
    if (!res.ok) throw new Error(res.error || "Action failed");
    toast("Engine: " + action, "success");
    switchView("overview");
  } catch (ex) {
    toast(ex.message, "error");
  }
}

/* ------------------------------------------------------------------ */
/* settings                                                            */
/* ------------------------------------------------------------------ */
const NUMERIC_FIELDS = new Set([
  "lot_size", "risk_percent", "stop_loss_points", "take_profit_points",
  "magic_number", "slippage", "spread_limit", "cooldown_candles",
  "max_trades_per_day", "daily_profit_target", "daily_loss_limit",
  "candle_count", "poll_interval_ms",
  "indicators.rsi_period", "indicators.ema_fast", "indicators.ema_slow",
  "mt5.login",
]);

async function renderSettings(content, topRight) {
  const saveBtn = el("button", "btn primary", "Save settings");
  topRight.appendChild(saveBtn);
  content.innerHTML = "";

  let config;
  try {
    config = (await api("/api/control/settings")).config;
  } catch (ex) {
    content.appendChild(el("p", "empty", "Failed to load settings: " + esc(ex.message)));
    return;
  }

  const form = el("div", "");
  content.appendChild(form);

  const fg = el("div", "form-grid");
  const textFields = [
    ["symbol", "Symbol", "text"],
    ["timeframe", "Timeframe", "text"],
    ["comment", "Order comment", "text"],
    ["session_start", "Session start (HH:MM)", "text"],
    ["session_end", "Session end (HH:MM)", "text"],
  ];
  const numFields = [
    ["lot_size", "Lot size"],
    ["risk_percent", "Risk %"],
    ["stop_loss_points", "Stop loss (pts)"],
    ["take_profit_points", "Take profit (pts)"],
    ["magic_number", "Magic number"],
    ["slippage", "Slippage"],
    ["spread_limit", "Spread limit"],
    ["cooldown_candles", "Cooldown candles"],
    ["max_trades_per_day", "Max trades / day"],
    ["daily_profit_target", "Daily profit target"],
    ["daily_loss_limit", "Daily loss limit"],
    ["candle_count", "Candles"],
    ["poll_interval_ms", "Poll ms"],
  ];
  const boolFields = [
    ["use_risk_sizing", "Adaptive risk % sizing"],
    ["close_on_reverse", "Close on reverse signal"],
    ["dry_run", "Dry run (paper)"],
    ["enable_notifications", "Notifications"],
    ["dark_mode", "Dark mode"],
  ];

  textFields.forEach(([key, label]) => fg.appendChild(inputField(label, key, "text", config[key])));
  numFields.forEach(([key, label]) => fg.appendChild(inputField(label, key, "number", config[key])));
  boolFields.forEach(([key, label]) => fg.appendChild(inputField(label, key, "checkbox", config[key])));
  form.appendChild(fg);

  form.appendChild(rule());
  form.appendChild(el("h3", "card-title", "Indicators"));
  const ig = el("div", "form-grid");
  ig.appendChild(inputField("RSI period", "indicators.rsi_period", "number", config.indicators && config.indicators.rsi_period));
  ig.appendChild(inputField("EMA fast", "indicators.ema_fast", "number", config.indicators && config.indicators.ema_fast));
  ig.appendChild(inputField("EMA slow", "indicators.ema_slow", "number", config.indicators && config.indicators.ema_slow));
  form.appendChild(ig);

  form.appendChild(rule());
  form.appendChild(el("h3", "card-title", "MetaTrader 5"));
  const mg = el("div", "form-grid");
  const mt5 = config.mt5 || {};
  mg.appendChild(inputField("Terminal path", "mt5.path", "text", mt5.path));
  mg.appendChild(inputField("Login", "mt5.login", "number", mt5.login));
  mg.appendChild(inputField("Password", "mt5.password", "password", mt5.password));
  mg.appendChild(inputField("Server", "mt5.server", "text", mt5.server));
  mg.appendChild(inputField("Remember password", "mt5.remember_password", "checkbox", mt5.remember_password));
  form.appendChild(mg);

  form.appendChild(rule());
  form.appendChild(el("h3", "card-title", "Telegram"));
  const tg = el("div", "form-grid");
  const tele = config.telegram || {};
  tg.appendChild(inputField("Enabled", "telegram.enabled", "checkbox", tele.enabled));
  tg.appendChild(inputField("Chat ID", "telegram.chat_id", "text", tele.chat_id));
  form.appendChild(tg);
  form.appendChild(
    el("p", "muted", "Telegram bot token is read from the HM_TELEGRAM_BOT_TOKEN environment variable (never stored on disk).")
  );

  saveBtn.onclick = async () => {
    const payload = {};
    form.querySelectorAll("[data-path]").forEach((input) => {
      let value;
      if (input.type === "checkbox") value = input.checked;
      else if (input.type === "password") value = input.value;
      else value = input.value.trim();
      if (value === "" && (input.type === "number" || input.dataset.num)) return;
      setPath(payload, input.dataset.path, value);
    });
    try {
      const res = await postJSON("/api/control/settings", { config: payload });
      if (!res.ok) throw new Error(res.error);
      toast("Settings saved — engine reloading", "success");
      switchView("settings");
    } catch (ex) {
      toast(ex.message, "error");
    }
  };
}

function inputField(label, path, type, value) {
  const f = el("label", "field");
  f.appendChild(el("span", "", label));
  const input = el("input", "input");
  input.type = type;
  input.dataset.path = path;
  if (type === "checkbox") {
    input.checked = !!value;
  } else {
    input.value = value != null ? value : "";
    if (NUMERIC_FIELDS.has(path)) input.dataset.num = "1";
  }
  f.appendChild(input);
  return f;
}

/* ------------------------------------------------------------------ */
/* users                                                               */
/* ------------------------------------------------------------------ */
async function renderUsers(content, topRight) {
  const addBtn = el("button", "btn primary", "Add user");
  addBtn.onclick = () => openUserForm(null);
  topRight.appendChild(addBtn);
  content.innerHTML = "";

  let users;
  try {
    users = (await api("/api/control/users")).users;
  } catch (ex) {
    content.appendChild(el("p", "empty", "Failed to load: " + esc(ex.message)));
    return;
  }
  if (!users.length) {
    content.appendChild(el("p", "empty", "No customers yet — add your first one."));
    return;
  }

  const card = el("div", "card");
  const tbl = el("table", "tbl");
  tbl.appendChild(el("thead", "", "<tr><th>ID</th><th>MT5 account</th><th>Email</th><th>Name</th><th>Status</th><th>Payments</th><th>Keys</th><th>Created</th><th></th></tr>"));
  const tbody = el("tbody");
  users.forEach((u) => {
    const tr = el("tr");
    const td = el("td");
    const actions = el("div", "row-actions");
    actions.appendChild(
      smallBtn(u.status === "active" ? "Disable" : "Enable", async () => {
        await setUserStatus(u.id, u.status === "active" ? "disabled" : "active");
        renderUsers($("content"), $("top-right"));
      })
    );
    actions.appendChild(smallBtn("Edit", () => openUserForm(u)));
    actions.appendChild(smallBtn("Issue key", async () => issueKey(u.id)));
    actions.appendChild(
      smallBtn("Delete", async () => {
        if (window.confirm("Delete this customer? Their payments and keys stay in history.")) {
          await postJSON("/api/control/users/delete", { id: u.id });
          toast("User deleted", "success");
          renderUsers($("content"), $("top-right"));
        }
      }, "danger")
    );
    td.appendChild(actions);
    tr.appendChild(el("td", "mono-cell", u.id));
    tr.appendChild(el("td", "mono-cell", esc(u.mt5_account || "—")));
    tr.appendChild(el("td", "", esc(u.email || "—")));
    tr.appendChild(el("td", "", esc(u.name || "—")));
    tr.appendChild(el("td", "", pill(u.status === "active" ? "active" : "disabled", u.status === "active" ? "ok" : "bad")));
    tr.appendChild(el("td", "", `${u.payment_count} (${u.paid_count} paid)`));
    tr.appendChild(el("td", "", u.key_count));
    tr.appendChild(el("td", "mono-cell", fmtDT(u.created_at)));
    tr.appendChild(td);
    tbody.appendChild(tr);
  });
  tbl.appendChild(tbody);
  const wrap = el("div", "tbl-wrap");
  wrap.appendChild(tbl);
  card.appendChild(wrap);
  content.appendChild(card);
}

async function setUserStatus(id, status) {
  await postJSON("/api/control/users/status", { id, status });
  toast("User " + status, "success");
}

async function issueKey(userId) {
  try {
    const res = await postJSON("/api/control/keys/generate", { user_id: userId });
    if (!res.ok) throw new Error(res.error);
    showKeyDialog("License key generated", res.key);
  } catch (ex) {
    toast(ex.message, "error");
  }
}

function openUserForm(user) {
  const body = el("div", "");
  body.appendChild(textField("MT5 account number (login)", "u-account", user ? user.mt5_account : "", "text"));
  body.appendChild(textField("Email (optional)", "u-email", user ? user.email : "", "email"));
  body.appendChild(textField("Name", "u-name", user ? user.name : "", "text"));
  body.appendChild(textArea("Notes", "u-notes", user ? user.notes : ""));
  openDialog({
    title: user ? "Edit user" : "Add user",
    sub: user ? `ID ${user.id}` : "The MT5 account identifies the customer — one license key per account.",
    body,
    buttons: [
      {
        label: "Save",
        kind: "primary",
        fn: async (done) => {
          const payload = {
            id: user ? user.id : undefined,
            mt5_account: $("u-account").value.trim(),
            email: $("u-email").value.trim(),
            name: $("u-name").value.trim(),
            notes: $("u-notes").value.trim(),
          };
          if (!payload.mt5_account) throw new Error("MT5 account number is required.");
          const res = await postJSON(user ? "/api/control/users/update" : "/api/control/users", payload);
          if (!res.ok) throw new Error(res.error);
          done();
          toast(user ? "User updated" : "User added", "success");
          renderUsers($("content"), $("top-right"));
        },
      },
      { label: "Cancel", kind: "ghost", fn: async (done) => done() },
    ],
  });
}

/* ------------------------------------------------------------------ */
/* payments                                                            */
/* ------------------------------------------------------------------ */
async function renderPayments(content, topRight) {
  const newBtn = el("button", "btn primary", "New payment");
  newBtn.onclick = openPaymentForm;
  topRight.appendChild(newBtn);
  content.innerHTML = "";

  let payments;
  try {
    payments = (await api("/api/control/payments")).payments;
  } catch (ex) {
    content.appendChild(el("p", "empty", "Failed to load: " + esc(ex.message)));
    return;
  }
  if (!payments.length) {
    content.appendChild(el("p", "empty", "No payments yet — create one to generate a deposit address."));
    return;
  }
  const card = el("div", "card");
  card.appendChild(paymentTable(payments));
  content.appendChild(card);
}

function paymentTable(payments) {
  const tbl = el("table", "tbl");
  tbl.appendChild(el("thead", "", "<tr><th>ID</th><th>Customer</th><th>Chain</th><th>Address</th><th>Expected</th><th>Status</th><th>Created</th><th></th></tr>"));
  const tbody = el("tbody");
  payments.forEach((p) => {
    const tr = el("tr");
    const td = el("td");
    const actions = el("div", "row-actions");
    actions.appendChild(smallBtn("Check", () => checkPayment(p), p.status === "pending" ? "" : ""));
    if (p.status === "pending") {
      actions.appendChild(smallBtn("Confirm paid", () => confirmPayment(p), "primary"));
    }
    actions.appendChild(
      smallBtn("Delete", async () => {
        if (window.confirm("Delete this payment record?")) {
          await postJSON("/api/control/payments/delete", { id: p.id });
          toast("Payment deleted", "success");
          switchView("payments");
        }
      }, "danger")
    );
    td.appendChild(actions);
    const statusPill = p.status === "paid" ? pill("paid", "ok") : p.status === "refunded" ? pill("refunded", "bad") : pill("pending", "warn");
    tr.appendChild(el("td", "mono-cell", p.id));
    tr.appendChild(el("td", "", esc(p.user_account || p.user_email || p.user_name || "—")));
    tr.appendChild(el("td", "", pill(String(p.chain || "").toUpperCase(), p.chain === "btc" ? "info" : "")));
    tr.appendChild(el("td", "mono-cell", esc(p.address || "—")));
    tr.appendChild(el("td", "", p.amount_expected != null ? `${p.amount_expected} ${p.unit || ""}` : "—"));
    tr.appendChild(el("td", "", statusPill));
    tr.appendChild(el("td", "mono-cell", fmtDT(p.created_at)));
    tr.appendChild(td);
    tbody.appendChild(tr);
  });
  tbl.appendChild(tbody);
  const wrap = el("div", "tbl-wrap");
  wrap.appendChild(tbl);
  return wrap;
}

async function openPaymentForm() {
  let users;
  try {
    users = (await api("/api/control/users")).users;
  } catch (ex) {
    toast(ex.message, "error");
    return;
  }
  if (!users.length) {
    toast("Add a customer first (Users tab)", "error");
    return;
  }
  const body = el("div", "");
  const sel = el("select", "input");
  users.forEach((u) => {
    const opt = document.createElement("option");
    opt.value = u.id;
    opt.textContent = `${u.mt5_account || u.email || u.name || "user #" + u.id}`;
    sel.appendChild(opt);
  });
  const chainSel = el("select", "input");
  ["btc", "usdt"].forEach((c) => {
    const opt = document.createElement("option");
    opt.value = c;
    opt.textContent = c === "btc" ? "Bitcoin (BTC)" : "USDT (TRC-20)";
    chainSel.appendChild(opt);
  });
  const amt = el("input", "input");
  amt.type = "number";
  amt.step = "any";
  amt.placeholder = "Amount expected (optional)";
  const notes = el("input", "input");
  notes.placeholder = "Notes (optional)";

  const f1 = el("label", "field"); f1.appendChild(el("span", "", "Customer")); f1.appendChild(sel);
  const f2 = el("label", "field"); f2.appendChild(el("span", "", "Chain")); f2.appendChild(chainSel);
  const f3 = el("label", "field"); f3.appendChild(el("span", "", "Expected amount")); f3.appendChild(amt);
  const f4 = el("label", "field"); f4.appendChild(el("span", "", "Notes")); f4.appendChild(notes);
  body.appendChild(f1); body.appendChild(f2); body.appendChild(f3); body.appendChild(f4);

  openDialog({
    title: "New crypto payment",
    sub: "A fresh deposit address is generated for this customer.",
    body,
    buttons: [
      {
        label: "Generate address",
        kind: "primary",
        fn: async (done) => {
          const payload = {
            user_id: Number(sel.value),
            chain: chainSel.value,
            amount_expected: amt.value === "" ? null : Number(amt.value),
            unit: chainSel.value === "btc" ? "BTC" : "USDT",
            notes: notes.value.trim(),
          };
          const res = await postJSON("/api/control/payments", payload);
          if (!res.ok) throw new Error(res.error || "Could not generate address");
          done();
          toast("Payment created — address generated", "success");
          switchView("payments");
        },
      },
      { label: "Cancel", kind: "ghost", fn: async (done) => done() },
    ],
  });
}

async function checkPayment(p) {
  try {
    const res = await postJSON("/api/control/payments/check", { id: p.id });
    if (!res.ok) throw new Error(res.error);
    const amount = `${res.chain.toUpperCase()} ${res.balance} ${res.unit || ""}`;
    const usd = res.balance_usd != null ? ` (≈ $${res.balance_usd})` : "";
    const body = el("div", "");
    body.appendChild(el("p", "", "Current balance for this deposit address:"));
    body.appendChild(el("div", "key-box", esc(amount + usd)));
    openDialog({
      title: "Balance check",
      sub: p.address,
      body,
      buttons: [
        { label: "Confirm paid", kind: "primary", fn: async (done) => { done(); await confirmPayment(p); } },
        { label: "Close", kind: "ghost", fn: async (done) => done() },
      ],
    });
  } catch (ex) {
    toast(ex.message, "error");
  }
}

async function confirmPayment(p) {
  const txid = window.prompt("Transaction ID (optional, e.g. a TX hash):", "") ?? "";
  try {
    const res = await postJSON("/api/control/payments/confirm", { id: p.id, txid: txid });
    if (!res.ok) throw new Error(res.error);
    showKeyDialog("Payment confirmed — license issued", res.key);
    switchView("payments");
  } catch (ex) {
    toast(ex.message, "error");
  }
}

/* ------------------------------------------------------------------ */
/* keys                                                                */
/* ------------------------------------------------------------------ */
async function renderKeys(content, topRight) {
  const genBtn = el("button", "btn primary", "Generate key");
  genBtn.onclick = openKeyForm;
  topRight.appendChild(genBtn);
  content.innerHTML = "";

  let keys;
  try {
    keys = (await api("/api/control/keys")).keys;
  } catch (ex) {
    content.appendChild(el("p", "empty", "Failed to load: " + esc(ex.message)));
    return;
  }
  if (!keys.length) {
    content.appendChild(el("p", "empty", "No keys issued yet."));
    return;
  }
  const card = el("div", "card");
  const tbl = el("table", "tbl");
  tbl.appendChild(el("thead", "", "<tr><th>Key</th><th>Customer</th><th>Status</th><th>Issued</th><th>Activated</th><th></th></tr>"));
  const tbody = el("tbody");
  keys.forEach((k) => {
    const tr = el("tr");
    const td = el("td");
    const actions = el("div", "row-actions");
    actions.appendChild(smallBtn("Copy", async () => {
      try {
        await navigator.clipboard.writeText(k.key);
        toast("Key copied", "success");
      } catch (e) {}
    }));
    if (k.status !== "revoked") {
      actions.appendChild(
        smallBtn("Revoke", async () => {
          if (window.confirm("Revoke this key? It will stop working.")) {
            await postJSON("/api/control/keys/revoke", { key: k.key });
            toast("Key revoked", "success");
            switchView("keys");
          }
        }, "danger")
      );
    }
    td.appendChild(actions);
    tr.appendChild(el("td", "mono-cell", esc(k.key)));
    tr.appendChild(el("td", "", esc(k.user_account || k.user_email || k.user_name || "—")));
    const pillCls = k.status === "active" ? "ok" : k.status === "revoked" ? "bad" : "info";
    tr.appendChild(el("td", "", pill(k.status, pillCls)));
    tr.appendChild(el("td", "mono-cell", fmtDT(k.issued_at)));
    tr.appendChild(el("td", "mono-cell", fmtDT(k.activated_at)));
    tr.appendChild(td);
    tbody.appendChild(tr);
  });
  tbl.appendChild(tbody);
  const wrap = el("div", "tbl-wrap");
  wrap.appendChild(tbl);
  card.appendChild(wrap);
  content.appendChild(card);
}

async function openKeyForm() {
  let users = [];
  try {
    users = (await api("/api/control/users")).users;
  } catch (e) {}
  const body = el("div", "");
  const sel = el("select", "input");
  const none = document.createElement("option");
  none.value = "";
  none.textContent = "— select an MT5 account —";
  sel.appendChild(none);
  users.forEach((u) => {
    const opt = document.createElement("option");
    opt.value = u.id;
    opt.textContent = `${u.mt5_account || u.email || u.name || "user #" + u.id}`;
    sel.appendChild(opt);
  });
  const f = el("label", "field");
  f.appendChild(el("span", "", "Customer (MT5 account)"));
  f.appendChild(sel);
  body.appendChild(f);
  body.appendChild(el("p", "muted", "One license key per MT5 account — the key is bound to that account. Only customers with an MT5 account set can receive a key."));
  openDialog({
    title: "Generate license key",
    sub: "Valid forever; the customer pastes it into the dashboard once, with their MT5 account number.",
    body,
    buttons: [
      {
        label: "Generate",
        kind: "primary",
        fn: async (done) => {
          if (!sel.value) throw new Error("Select the MT5 account this key is for.");
          const res = await postJSON("/api/control/keys/generate", { user_id: sel.value ? Number(sel.value) : null });
          if (!res.ok) throw new Error(res.error);
          done();
          showKeyDialog("License key generated", res.key);
          switchView("keys");
        },
      },
      { label: "Cancel", kind: "ghost", fn: async (done) => done() },
    ],
  });
}

/* ------------------------------------------------------------------ */
/* trades                                                              */
/* ------------------------------------------------------------------ */
async function renderTrades(content, topRight) {
  const refresh = el("button", "btn ghost", "Refresh");
  refresh.onclick = () => switchView("trades");
  const exportLink = el("a", "btn ghost", "Export CSV");
  exportLink.href = "/api/control/export";
  const btBtn = el("button", "btn", "Run backtest");
  topRight.appendChild(refresh);
  topRight.appendChild(exportLink);

  const bar = el("div", "bar");
  bar.appendChild(el("div", "bar-title", "Trade history"));
  const backRow = el("div", "row-line");
  const bars = el("input", "input");
  bars.type = "number";
  bars.value = "600";
  bars.style.width = "90px";
  btBtn.onclick = async () => {
    btBtn.disabled = true;
    btBtn.textContent = "Running…";
    try {
      const res = await api("/api/control/backtest?bars=" + (Number(bars.value) || 600));
      toast(`Backtest: ${res.win_rate}% win · ${res.net_profit} profit (${res.trades.length} trades)`, "success");
    } catch (ex) {
      toast(ex.message, "error");
    } finally {
      btBtn.disabled = false;
      btBtn.textContent = "Run backtest";
    }
  };
  backRow.appendChild(bars);
  backRow.appendChild(btBtn);
  bar.appendChild(backRow);
  content.appendChild(bar);

  let history;
  try {
    history = (await api("/api/control/history")).history;
  } catch (ex) {
    content.appendChild(el("p", "empty", "Failed to load: " + esc(ex.message)));
    return;
  }
  if (!history.length) {
    content.appendChild(el("p", "empty", "No trades yet."));
    return;
  }
  const card = el("div", "card");
  const tbl = el("table", "tbl");
  tbl.appendChild(el("thead", "", "<tr><th>ID</th><th>Type</th><th>Entry</th><th>Exit</th><th>Profit</th><th>Lot</th><th>Mode</th><th>Reason</th></tr>"));
  const tbody = el("tbody");
  history.forEach((t) => {
    const tr = el("tr");
    const profit = t.profit;
    tr.appendChild(el("td", "mono-cell", t.id));
    tr.appendChild(el("td", "", pill(t.type === "buy" ? "BUY" : "SELL", t.type === "buy" ? "ok" : "bad")));
    tr.appendChild(el("td", "mono-cell", t.entry != null ? t.entry : "—"));
    tr.appendChild(el("td", "mono-cell", t.exit != null ? t.exit : "—"));
    tr.appendChild(el("td", "mono-cell " + (profit > 0 ? "up" : profit < 0 ? "down" : ""), profit != null ? fmtMoney(profit, true) : "—"));
    tr.appendChild(el("td", "mono-cell", t.lot != null ? t.lot : "—"));
    tr.appendChild(el("td", "", pill(t.dry_run ? "paper" : "live", t.dry_run ? "info" : "warn")));
    tr.appendChild(el("td", "", esc(t.reason || "—")));
    tbody.appendChild(tr);
  });
  tbl.appendChild(tbody);
  const wrap = el("div", "tbl-wrap");
  wrap.appendChild(tbl);
  card.appendChild(wrap);
  content.appendChild(card);
}

/* ------------------------------------------------------------------ */
/* logs                                                                */
/* ------------------------------------------------------------------ */
async function renderLogs(content, topRight) {
  const refresh = el("button", "btn ghost", "Refresh");
  refresh.onclick = () => switchView("logs");
  topRight.appendChild(refresh);
  content.innerHTML = `<div class="empty">Loading logs…</div>`;
  let lines;
  try {
    lines = (await api("/api/control/logs")).lines || [];
  } catch (ex) {
    content.innerHTML = "";
    content.appendChild(el("p", "empty", "Failed to load: " + esc(ex.message)));
    return;
  }
  content.innerHTML = "";
  if (!lines.length) {
    content.appendChild(el("p", "empty", "No log output yet."));
    return;
  }
  content.appendChild(el("pre", "log-box", esc(lines.join("\n"))));
}

/* ------------------------------------------------------------------ */
/* security                                                            */
/* ------------------------------------------------------------------ */
async function renderSecurity(content, topRight) {
  content.innerHTML = "";
  let session;
  try {
    session = await api("/api/control/session");
  } catch (e) {}

  const info = el("div", "card");
  info.appendChild(el("h3", "card-title", "Access"));
  const rows = el("div", "");
  rows.appendChild(el("p", "", "Username: <strong>" + esc(session.username || "owner") + "</strong>"));
  const urlLine = el("p", "");
  urlLine.appendChild(document.createTextNode("Control URL: "));
  urlLine.appendChild(el("span", "mono", esc(session.control_path)));
  rows.appendChild(urlLine);
  info.appendChild(rows);
  content.appendChild(info);

  const pwCard = el("div", "card");
  pwCard.appendChild(el("h3", "card-title", "Change password"));
  const body = el("div", "");
  body.appendChild(textField("Current password", "sec-current", "", "password"));
  body.appendChild(textField("New username", "sec-user", session.username || "", "text"));
  body.appendChild(textField("New password", "sec-pass", "", "password"));
  body.appendChild(textField("Repeat new password", "sec-pass2", "", "password"));
  const save = el("button", "btn primary", "Update credentials");
  save.onclick = async () => {
    const current = $("sec-current").value;
    const username = $("sec-user").value.trim();
    const pw1 = $("sec-pass").value;
    const pw2 = $("sec-pass2").value;
    if (!username) return toast("Username required", "error");
    if (pw1 && pw1 !== pw2) return toast("Passwords do not match", "error");
    if (!current) return toast("Enter your current password", "error");
    try {
      const res = await postJSON("/api/control/password", { current, username, new_password: pw1 });
      if (!res.ok) throw new Error(res.error);
      toast("Credentials updated", "success");
      switchView("security");
    } catch (ex) {
      toast(ex.message, "error");
    }
  };
  const actions = el("div", "form-actions");
  actions.appendChild(save);
  body.appendChild(actions);
  pwCard.appendChild(body);
  content.appendChild(pwCard);

  const note = el("div", "card");
  note.appendChild(el("h3", "card-title", "Tips"));
  note.appendChild(el("p", "muted", "Keep the control URL private — it is the only entrance. Do not share it with customers. Set the payment API key via the HM_WEB3_API_KEY environment variable rather than shipping it in a distributed build."));
  content.appendChild(note);
}

/* ------------------------------------------------------------------ */
/* small form helpers                                                  */
/* ------------------------------------------------------------------ */
function textField(label, id, value, type) {
  const f = el("label", "field");
  f.appendChild(el("span", "", label));
  const input = el("input", "input");
  input.type = type || "text";
  input.id = id;
  input.value = value || "";
  f.appendChild(input);
  return f;
}

function textArea(label, id, value) {
  const f = el("label", "field");
  f.appendChild(el("span", "", label));
  const ta = el("textarea", "input");
  ta.id = id;
  ta.value = value || "";
  f.appendChild(ta);
  return f;
}

/* ------------------------------------------------------------------ */
/* init                                                                */
/* ------------------------------------------------------------------ */
$("login-form").addEventListener("submit", doLogin);
$("logout-btn").addEventListener("click", doLogout);
document.querySelectorAll(".nav-btn").forEach((b) => {
  b.addEventListener("click", () => switchView(b.dataset.view));
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") closeDialog();
});

boot();
