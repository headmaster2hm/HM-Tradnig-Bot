"use strict";

/* ==================================================================
   HM Bot Trader — dashboard logic (HMLINE)
   ================================================================== */

const state = {
  snapshot: null,
  history: null,
  view: "trading",
  settings: null,
};

const $ = (id) => document.getElementById(id);

const candleChart = new CandleChart($("price-chart"));
const rsiChart = new RsiChart($("rsi-chart"));
const equityChart = new EquityChart($("equity-chart"));

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
  if (v == null || Number.isNaN(v)) return "—";
  const n = Number(v);
  const s = n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return sign ? (n >= 0 ? "+" + s : s) : s;
}

function moneyClass(v) {
  if (v == null) return "";
  return v > 0 ? "money-up" : v < 0 ? "money-down" : "";
}

function fmtTime(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
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
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).error || res.statusText);
  return res.json();
}

function postJSON(path, body) {
  return api(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

/* ------------------------------------------------------------------ */
/* theme (day / night) — dark is the default                           */
/* ------------------------------------------------------------------ */
const THEME_KEY = "hm-theme";

function readTheme() {
  try {
    return localStorage.getItem(THEME_KEY) || "dark";
  } catch (e) {
    return "dark";
  }
}

function rerenderThemeAware() {
  if (state.snapshot && state.snapshot.ok) {
    candleChart.update(state.snapshot.candles || [], state.snapshot.markers || []);
    rsiChart.update(state.snapshot.indicators || [], state.snapshot.markers || []);
  }
  if (state.history) renderHistory(state.history);
  drawStrategyIllustration();
}

function applyTheme(theme, persist) {
  document.documentElement.setAttribute("data-theme", theme);
  if (persist) {
    try {
      localStorage.setItem(THEME_KEY, theme);
    } catch (e) {}
  }
  syncChartTheme();
  rerenderThemeAware();
}

$("theme-toggle").addEventListener("click", () => {
  const next = document.documentElement.getAttribute("data-theme") === "light" ? "dark" : "light";
  applyTheme(next, true);
  toast(next === "dark" ? "Night mode" : "Day mode");
});

/* ------------------------------------------------------------------ */
/* navigation                                                          */
/* ------------------------------------------------------------------ */
const VIEW_TITLES = {
  trading: "Trading",
  positions: "Positions",
  history: "History",
  backtest: "Backtest",
  strategy: "Strategy",
  settings: "Settings",
  logs: "Logs",
};

function setView(name) {
  state.view = name;
  document.querySelectorAll(".view").forEach((v) => v.classList.remove("active"));
  document.getElementById("view-" + name).classList.add("active");
  document.querySelectorAll(".rail-btn").forEach((b) =>
    b.classList.toggle("active", b.dataset.view === name)
  );
  if (name === "history") loadHistory(true);
  if (name === "settings") loadSettings();
  if (name === "strategy") drawStrategyIllustration();
}

document.getElementById("nav").addEventListener("click", (e) => {
  const btn = e.target.closest(".rail-btn");
  if (btn) setView(btn.dataset.view);
});

/* ------------------------------------------------------------------ */
/* clock                                                               */
/* ------------------------------------------------------------------ */
function tickClock() {
  const d = new Date();
  $("clock").textContent = d.toLocaleTimeString();
}
setInterval(tickClock, 1000);
tickClock();

/* ------------------------------------------------------------------ */
/* poll loop                                                           */
/* ------------------------------------------------------------------ */
async function poll() {
  if (!license || !license.activated) return;
  try {
    state.snapshot = await api("/api/state");
  } catch (err) {
    $("feed-pill").className = "tag red";
    $("feed-pill").textContent = "Offline";
    return;
  }
  renderTopbar(state.snapshot);
  renderTrading(state.snapshot);
  renderPositions(state.snapshot);
  if (state.view === "logs") renderLogs(state.snapshot);
}
setInterval(poll, 1000);

/* ------------------------------------------------------------------ */
/* topbar + statusline + rail                                          */
/* ------------------------------------------------------------------ */
function renderTopbar(s) {
  const feed = $("feed-pill");
  if (!s.ok) {
    feed.className = "tag";
    feed.textContent = "Booting…";
    return;
  }
  if (s.simulated) {
    feed.className = "tag gold";
    feed.textContent = "SIM feed";
  } else if (s.connected) {
    feed.className = "tag green";
    feed.textContent = "MT5 live";
  } else {
    feed.className = "tag red";
    feed.textContent = "MT5 offline";
  }

  const mode = $("mode-pill");
  mode.className = "tag " + (s.mode === "LIVE" ? "red" : "accent");
  mode.textContent = s.mode;

  const status = $("status-pill");
  const running = s.status === "RUNNING" && !s.paused;
  const paused = s.status === "RUNNING" && s.paused;
  status.className = "tag " + (running ? "green" : paused ? "gold" : "");
  status.textContent = running ? "Running" : paused ? "Paused" : s.status;

  const dot = $("rail-dot");
  dot.classList.toggle("ok", running);
  dot.classList.toggle("warn", paused);

  $("sl-symbol").textContent = s.symbol || "—";
  $("sl-rsi").textContent = s.rsi != null ? s.rsi.toFixed(1) : "—";
  $("sl-ema48").textContent = s.ema48 != null ? s.ema48.toFixed(2) : "—";
  $("sl-ema50").textContent = s.ema50 != null ? s.ema50.toFixed(2) : "—";
  $("sl-spread").textContent = (s.spread != null ? s.spread.toFixed(0) : "—") + " pt";
  const candles = s.candles || [];
  if (candles.length) {
    const last = candles[candles.length - 1];
    const dec = last.c >= 1000 ? 2 : last.c >= 10 ? 3 : 5;
    $("sl-last").textContent = last.c.toFixed(dec);
  }
  const msg = s.halted ? (s.risk_reason || "Halted") : s.license_account_error || "";
  $("sl-msg").textContent = msg;
  $("sl-msg").className = s.license_account_error ? "grow warn" : "grow";
}

/* ------------------------------------------------------------------ */
/* trading view                                                        */
/* ------------------------------------------------------------------ */
function renderTrading(s) {
  if (!s.ok) return;

  // stat cards
  const bal = (s.account && s.account.balance) ?? null;
  const eq = (s.account && s.account.equity) ?? null;
  const float = (s.account && s.account.profit) ?? null;
  $("st-balance").textContent = fmtMoney(bal);
  $("st-account-name").textContent = s.account ? s.account.name + " · " + s.account.server : "";
  $("st-equity").textContent = fmtMoney(eq);
  $("st-floating").textContent = "Floating " + fmtMoney(float);
  $("st-floating").className = "ssub " + (float > 0 ? "good" : float < 0 ? "warn" : "");

  $("st-day").textContent = fmtMoney(s.day_profit, true);
  $("st-day").className = "svalue " + (s.day_profit > 0 ? "money-up" : s.day_profit < 0 ? "money-down" : "");
  $("st-risk-reason").textContent = s.risk_reason || (s.halted ? "Halted" : "Risk gates OK");
  $("st-risk-reason").className = "ssub " + (s.halted ? "warn" : "good");

  $("st-winrate").textContent = (s.win_rate ?? 0).toFixed(1) + "%";
  $("st-confidence").textContent = (s.confidence ?? 0).toFixed(0) + "%";
  $("st-signal-reason").textContent = s.signal ? s.signal.reason : "Waiting for signal";

  // signal card
  const sig = s.signal;
  const big = $("signal-big");
  const kind = sig ? sig.signal : "HOLD";
  big.textContent = kind;
  big.className = "signal-big " + (kind === "BUY" ? "buy" : kind === "SELL" ? "sell" : "hold");
  $("signal-pill").className = "tag " + (kind === "BUY" ? "green" : kind === "SELL" ? "red" : "ink");
  $("signal-pill").textContent = kind === "HOLD" ? "Holding" : kind;
  $("signal-gauge").style.width = (s.confidence ?? 0) + "%";
  $("gauge-pct").textContent = (s.confidence ?? 0).toFixed(0) + "%";
  $("signal-time").textContent = sig && sig.bar_time ? "Bar " + fmtTime(sig.bar_time) : "";

  $("kv-rsi").textContent = s.rsi != null ? s.rsi.toFixed(1) : "—";
  $("kv-ema48").textContent = s.ema48 != null ? s.ema48.toFixed(2) : "—";
  $("kv-ema50").textContent = s.ema50 != null ? s.ema50.toFixed(2) : "—";
  $("kv-reason").textContent = sig ? sig.reason : "No crossover yet";

  $("kv-login").textContent = s.account ? s.account.login : "—";
  $("kv-server").textContent = s.account ? s.account.server : "—";
  $("kv-currency").textContent = s.account ? s.account.currency : "—";
  $("kv-positions").textContent = s.positions.length + " open";
  $("kv-risk").textContent = s.halted ? s.risk_reason : s.risk_reason || "OK";

  // price chip
  const candles = s.candles || [];
  if (candles.length) {
    const last = candles[candles.length - 1];
    const prev = candles.length > 1 ? candles[candles.length - 2] : null;
    const dec = last.c >= 1000 ? 2 : last.c >= 10 ? 3 : 5;
    let chip = last.c.toFixed(dec);
    let cls = "live";
    if (prev) {
      const chg = ((last.c - prev.c) / prev.c) * 100;
      chip += "  (" + (chg >= 0 ? "+" : "") + chg.toFixed(2) + "%)";
      cls = "live " + (chg >= 0 ? "money-up" : "money-down");
    }
    $("price-chip").textContent = chip;
    $("price-chip").className = cls;
    $("chart-title").textContent = "Price · " + (s.mode === "LIVE" ? "Live feed" : "Simulated feed");
  }

  // charts
  candleChart.update(candles, s.markers || []);
  rsiChart.update(s.indicators || [], s.markers || []);
  $("rsi-live").textContent =
    "RSI " + (s.rsi != null ? s.rsi.toFixed(1) : "—") +
    " · E48 " + (s.ema48 != null ? s.ema48.toFixed(2) : "—") +
    " · E50 " + (s.ema50 != null ? s.ema50.toFixed(2) : "—");

}

/* ------------------------------------------------------------------ */
/* actions                                                             */
/* ------------------------------------------------------------------ */
async function runAction(action, value) {
  const body = { action };
  if (value != null) body.ticket = value;
  try {
    await postJSON("/api/action", body);
    const label = action === "start" ? "Bot started" : action === "stop" ? "Bot stopped" : action === "close_position" ? "Position closed" : action.replace("_", " ") + " done";
    toast(label, "success");
  } catch (err) {
    toast(err.message || "Action failed", "error");
  }
  poll();
}

}

/* ------------------------------------------------------------------ */
/* positions view                                                      */
/* ------------------------------------------------------------------ */
let lastTickets = "";
function renderPositions(s) {
  const positions = s.ok ? s.positions : [];
  const tickets = positions.map((p) => p.ticket).join(",");
  $("pos-count").textContent = positions.length;
  $("pos-count").classList.toggle("show", positions.length > 0);
  $("positions-summary").textContent =
    positions.length + " open · " + (s.ok ? fmtMoney(s.account && s.account.profit) : "—");

  const body = $("positions-body");
  const candles = s.candles || [];
  const currentPrice = candles.length ? candles[candles.length - 1].c : null;

  if (!positions.length) {
    lastTickets = "";
    body.innerHTML = "";
    body.appendChild(
      el("div", "empty",
        ILLUSTRATIONS.emptyPositions +
        "<h4>No open positions</h4>" +
        "<p>When the strategy finds a signal, entries will show up here with live floating P/L.</p>"
      )
    );
    return;
  }

  if (tickets === lastTickets) {
    body.querySelectorAll("tr[data-ticket]").forEach((row) => {
      const p = positions.find((x) => String(x.ticket) === row.dataset.ticket);
      if (!p) return;
      const pl = row.querySelector(".pos-pl");
      pl.textContent = fmtMoney(p.profit, true);
      pl.className = "pos-pl " + moneyClass(p.profit);
      if (currentPrice != null) {
        const dec = p.price_open >= 1000 ? 2 : p.price_open >= 10 ? 3 : 5;
        row.querySelector(".pos-price").textContent = currentPrice.toFixed(dec);
      }
    });
    return;
  }
  lastTickets = tickets;

  const table = el("table", "tbl");
  table.innerHTML =
    "<thead><tr>" +
    "<th>Ticket</th><th>Side</th><th>Lot</th><th>Open</th><th>SL</th><th>TP</th><th>Price</th><th>P/L</th><th>Opened</th><th></th>" +
    "</tr></thead>";
  const tbody = el("tbody");
  for (const p of positions) {
    const tr = el("tr");
    tr.dataset.ticket = p.ticket;
    const dec = p.price_open >= 1000 ? 2 : p.price_open >= 10 ? 3 : 5;
    tr.innerHTML =
      "<td class='mono'>#" + p.ticket + "</td>" +
      "<td><span class='tbadge " + (p.type === "BUY" ? "buy" : "sell") + "'>" + p.type + "</span></td>" +
      "<td class='mono'>" + p.volume + "</td>" +
      "<td class='mono'>" + p.price_open.toFixed(dec) + "</td>" +
      "<td class='mono'>" + (p.sl ? p.sl.toFixed(dec) : "—") + "</td>" +
      "<td class='mono'>" + (p.tp ? p.tp.toFixed(dec) : "—") + "</td>" +
      "<td class='mono pos-price'>" + (currentPrice != null ? currentPrice.toFixed(dec) : "—") + "</td>" +
      "<td class='mono pos-pl " + moneyClass(p.profit) + "'>" + fmtMoney(p.profit, true) + "</td>" +
      "<td class='mono'>" + fmtTime(p.time) + "</td>" +
      "<td><button class='btn danger close-one' data-ticket='" + p.ticket + "'>Close</button></td>";
    tbody.appendChild(tr);
  }
  table.appendChild(tbody);
  body.innerHTML = "";
  body.appendChild(el("div", "tbl-wrap"));
  body.firstChild.appendChild(table);
}

document.addEventListener("click", (e) => {
  const btn = e.target.closest(".close-one");
  if (btn) runAction("close_position", Number(btn.dataset.ticket));
});

/* ------------------------------------------------------------------ */
/* history view                                                        */
/* ------------------------------------------------------------------ */
async function loadHistory(force) {
  if (!force && state.history) {
    renderHistory(state.history);
    return;
  }
  try {
    state.history = await api("/api/history");
    renderHistory(state.history);
  } catch (err) {
    toast("Could not load history: " + err.message, "error");
  }
}

function renderHistory(rows) {
  const closed = (rows || []).filter((r) => r.profit != null);
  const wins = closed.filter((r) => r.profit > 0);
  const losses = closed.filter((r) => r.profit <= 0);
  const net = closed.reduce((a, r) => a + r.profit, 0);
  const avgWin = wins.length ? wins.reduce((a, r) => a + r.profit, 0) / wins.length : 0;
  const avgLoss = losses.length ? losses.reduce((a, r) => a + r.profit, 0) / losses.length : 0;

  const stat = (label, value, sub, cls = "") =>
    "<div class='stat'><div class='slabel'>" + label + "</div>" +
    "<div class='svalue " + cls + "'>" + value + "</div>" +
    "<div class='ssub'>" + sub + "</div></div>";

  $("history-stats").innerHTML =
    stat("Total trades", String(closed.length), "closed") +
    stat("Wins", String(wins.length), "winning trades", "money-up") +
    stat("Losses", String(losses.length), "losing trades", "money-down") +
    stat("Net profit", fmtMoney(net, true), "all closed", net >= 0 ? "money-up" : "money-down") +
    stat("Win rate", closed.length ? ((wins.length / closed.length) * 100).toFixed(1) + "%" : "—", "hit rate") +
    stat("Avg win", fmtMoney(avgWin, true), "avg loss " + fmtMoney(avgLoss, true), avgWin >= 0 ? "money-up" : "");

  // equity curve (oldest → newest)
  const ascending = closed.slice().reverse();
  let run = 0;
  const points = ascending.map((r) => {
    run += r.profit;
    return { y: run };
  });
  equityChart.update(points);

  const body = $("history-body");
  if (!closed.length) {
    body.innerHTML = "";
    body.appendChild(
      el("div", "empty",
        ILLUSTRATIONS.emptyHistory +
        "<h4>No closed trades yet</h4>" +
        "<p>Closed trades with their profit and exit reason will appear here.</p>"
      )
    );
    return;
  }

  const table = el("table", "tbl");
  table.innerHTML =
    "<thead><tr>" +
    "<th>Ticket</th><th>Side</th><th>Lot</th><th>Entry</th><th>Exit</th><th>P/L</th><th>Result</th><th>Conf</th><th>Reason</th><th>Opened</th><th>Closed</th>" +
    "</tr></thead>";
  const tbody = el("tbody");
  for (const r of closed) {
    const dec = r.entry >= 1000 ? 2 : r.entry >= 10 ? 3 : 5;
    const profit = r.profit;
    const tr = el("tr");
    tr.innerHTML =
      "<td class='mono'>#" + r.ticket + "</td>" +
      "<td><span class='tbadge " + (r.type === "BUY" ? "buy" : "sell") + "'>" + r.type + "</span></td>" +
      "<td class='mono'>" + r.lot + "</td>" +
      "<td class='mono'>" + Number(r.entry).toFixed(dec) + "</td>" +
      "<td class='mono'>" + (r.exit != null ? Number(r.exit).toFixed(dec) : "—") + "</td>" +
      "<td class='mono " + moneyClass(profit) + "'>" + fmtMoney(profit, true) + "</td>" +
      "<td><span class='tbadge " + (profit > 0 ? "win" : "loss") + "'>" + (profit > 0 ? "WIN" : "LOSS") + "</span></td>" +
      "<td class='mono'>" + (r.confidence != null ? r.confidence.toFixed(0) + "%" : "—") + "</td>" +
      "<td>" + esc(r.reason || "—") + "</td>" +
      "<td class='mono'>" + fmtTime(r.time_open) + "</td>" +
      "<td class='mono'>" + fmtTime(r.time_close) + "</td>";
    tbody.appendChild(tr);
  }
  table.appendChild(tbody);
  body.innerHTML = "";
  body.appendChild(el("div", "tbl-wrap"));
  body.firstChild.appendChild(table);
}

$("btn-export").addEventListener("click", () => {
  window.location.href = "/api/export";
  toast("Export started — check your downloads", "success");
});

/* ------------------------------------------------------------------ */
/* backtest                                                            */
/* ------------------------------------------------------------------ */
$("btn-backtest").addEventListener("click", async () => {
  const btn = $("btn-backtest");
  const bars = $("bt-bars").value;
  btn.disabled = true;
  btn.textContent = "Running…";
  try {
    const res = await api("/api/backtest?bars=" + bars);
    renderBacktest(res, bars);
  } catch (err) {
    $("bt-results").innerHTML =
      "<div class='panel'><div class='empty'>" +
      ILLUSTRATIONS.emptyBacktest + "<h4>Backtest failed</h4><p>" + esc(err.message) + "</p></div></div>";
  } finally {
    btn.disabled = false;
    btn.textContent = "Run backtest";
  }
});

function renderBacktest(res, bars) {
  if (res.error) {
    $("bt-results").innerHTML = "<div class='panel'><div class='empty'><h4>Backtest error</h4><p>" + esc(res.error) + "</p></div></div>";
    return;
  }
  const trades = res.trades || [];
  const net = res.net_profit;
  const winRate = res.win_rate;
  const stat = (label, value, sub, cls = "") =>
    "<div class='stat'><div class='slabel'>" + label + "</div>" +
    "<div class='svalue " + cls + "'>" + value + "</div>" +
    "<div class='ssub'>" + sub + "</div></div>";

  $("bt-results").innerHTML = "";
  $("bt-results").appendChild(
    el("div", "stats auto",
      stat("Candles replayed", bars, "last " + bars + " bars") +
      stat("Signals found", String(res.signals), "BUY + SELL") +
      stat("Trades closed", String(trades.length), "round-trips") +
      stat("Net profit", fmtMoney(net, true), "at current lot size", net >= 0 ? "money-up" : "money-down") +
      stat("Win rate", winRate.toFixed(1) + "%", "closed trades")
    )
  );

  const card = el("div", "panel", "");
  card.innerHTML = "<div class='panel-head'><h3>Backtest trades</h3><span class='live'>Simulated — not real money</span></div>";
  if (!trades.length) {
    card.appendChild(
      el("div", "empty",
        ILLUSTRATIONS.emptyBacktest +
        "<h4>No round-trip trades</h4>" +
        "<p>The crossover strategy did not complete any full BUY→SELL round trip in this window.</p>"
      )
    );
  } else {
    const table = el("table", "tbl");
    table.innerHTML = "<thead><tr><th>Side</th><th>Entry</th><th>Exit</th><th>Time</th><th>P/L</th></tr></thead>";
    const tbody = el("tbody");
    for (const t of trades) {
      const dec = t.entry >= 1000 ? 2 : t.entry >= 10 ? 3 : 5;
      tbody.appendChild(
        el("tr",
          "<td><span class='tbadge " + (t.side === "BUY" ? "buy" : "sell") + "'>" + t.side + "</span></td>" +
          "<td class='mono'>" + Number(t.entry).toFixed(dec) + "</td>" +
          "<td class='mono'>" + Number(t.exit).toFixed(dec) + "</td>" +
          "<td class='mono'>" + fmtTime(t.time) + "</td>" +
          "<td class='mono " + moneyClass(t.profit) + "'>" + fmtMoney(t.profit, true) + "</td>"
        )
      );
    }
    table.appendChild(tbody);
    const wrap = el("div", "tbl-wrap");
    wrap.appendChild(table);
    card.appendChild(wrap);
  }
  $("bt-results").appendChild(card);
}

/* ------------------------------------------------------------------ */
/* settings                                                            */
/* ------------------------------------------------------------------ */
const SETTINGS_GROUPS = [
  {
    title: "License",
    fields: [
      { key: "_license_key", label: "License key", type: "text" },
      { key: "_license_account", label: "MT5 account number", type: "text" },
    ],
  },
  {
    title: "Trading",
    fields: [
      { key: "symbol", label: "Symbol", type: "text" },
      { key: "timeframe", label: "Timeframe", type: "select", options: ["M1", "M5", "M15", "M30", "H1", "H4", "D1"] },
      { key: "lot_size", label: "Lot size", type: "number", step: "0.01" },
      { key: "comment", label: "Order comment", type: "text" },
      { key: "dry_run", label: "Dry-run / paper trading", type: "check" },
      { key: "slippage", label: "Slippage (points)", type: "number" },
    ],
  },
  {
    title: "Risk management",
    fields: [
      { key: "stop_loss_points", label: "Stop loss (points)", type: "number" },
      { key: "take_profit_points", label: "Take profit (points)", type: "number" },
      { key: "trailing_stop_points", label: "Trailing stop (points)", type: "number" },
      { key: "min_confidence", label: "Min confidence %", type: "number" },
      { key: "spread_limit", label: "Spread limit (points)", type: "number" },
      { key: "cooldown_candles", label: "Cooldown (candles)", type: "number" },
      { key: "max_trades_per_day", label: "Max trades per day", type: "number" },
      { key: "daily_profit_target", label: "Daily profit target", type: "number" },
      { key: "daily_loss_limit", label: "Daily loss limit", type: "number" },
      { key: "use_risk_sizing", label: "Adaptive risk-% sizing", type: "check" },
      { key: "risk_percent", label: "Risk % per trade", type: "number", step: "0.1" },
      { key: "use_trend_filter", label: "Trend filter (EMA 200)", type: "check" },
      { key: "close_on_reverse", label: "Close on reverse signal", type: "check" },
      { key: "session_start", label: "Session start (HH:MM)", type: "text" },
      { key: "session_end", label: "Session end (HH:MM)", type: "text" },
    ],
  },
  {
    title: "Data",
    fields: [
      { key: "candle_count", label: "Candles loaded", type: "number" },
      { key: "poll_interval_ms", label: "Poll interval (ms)", type: "number" },
      { key: "magic_number", label: "Magic number", type: "number" },
    ],
  },
  {
    title: "Indicators",
    fields: [
      { key: "indicators.rsi_period", label: "RSI period", type: "number" },
      { key: "indicators.ema_fast", label: "EMA fast (on RSI)", type: "number" },
      { key: "indicators.ema_slow", label: "EMA slow (on EMA fast)", type: "number" },
      { key: "indicators.trend_ema_period", label: "Trend EMA period", type: "number" },
    ],
  },
  {
    title: "MetaTrader 5",
    fields: [
      { key: "mt5.path", label: "terminal64.exe path", type: "text" },
      { key: "mt5.login", label: "Login (0 = use logged-in terminal)", type: "number" },
      { key: "mt5.server", label: "Server", type: "text" },
      { key: "mt5.password", label: "Password (kept off disk by default)", type: "password" },
      { key: "mt5.remember_password", label: "Remember password on disk", type: "check" },
      { key: "mt5_bridge.enabled", label: "Connect through HM Bridge (desktop MT5)", type: "check" },
      { key: "mt5_bridge.url", label: "Bridge URL", type: "text" },
      { key: "mt5_bridge.token", label: "Bridge token (prefer HM_BRIDGE_TOKEN env)", type: "password" },
    ],
  },
  {
    title: "Telegram",
    fields: [
      { key: "telegram.enabled", label: "Enable Telegram alerts", type: "check" },
      { key: "telegram.bot_token", label: "Bot token", type: "password" },
      { key: "telegram.chat_id", label: "Chat ID", type: "text" },
      { key: "telegram.remember_token", label: "Remember token on disk", type: "check" },
    ],
  },
];

function getPath(obj, path) {
  return path.split(".").reduce((o, k) => (o == null ? undefined : o[k]), obj);
}
function setPath(obj, path, value) {
  const keys = path.split(".");
  let o = obj;
  for (let i = 0; i < keys.length - 1; i++) {
    o[keys[i]] = o[keys[i]] || {};
    o = o[keys[i]];
  }
  o[keys[keys.length - 1]] = value;
}

function buildSettingsForms(cfg) {
  const container = $("settings-forms");
  container.innerHTML = "";
  for (const group of SETTINGS_GROUPS) {
    const panel = el("div", "sgroup");
    panel.appendChild(el("div", "sgroup-head", group.title));
    const grid = el("div", "form-grid");
    for (const f of group.fields) {
      const value = getPath(cfg, f.key);
      const wrap = el("div", f.type === "check" ? "field check" : "field");
      if (f.type === "check") {
        const input = el("input");
        input.type = "checkbox";
        input.checked = !!value;
        input.dataset.path = f.key;
        wrap.appendChild(input);
        wrap.appendChild(el("label", "", f.label));
      } else if (f.type === "select") {
        wrap.appendChild(el("label", "", f.label));
        const select = el("select");
        for (const optVal of f.options) {
          const opt = el("option", "", optVal);
          opt.value = optVal;
          if (String(value) === optVal) opt.selected = true;
          select.appendChild(opt);
        }
        select.dataset.path = f.key;
        wrap.appendChild(select);
      } else {
        wrap.appendChild(el("label", "", f.label));
        const input = el("input");
        input.type = f.type || "text";
        input.value = value == null ? "" : value;
        if (f.step) input.step = f.step;
        input.dataset.path = f.key;
        wrap.appendChild(input);
      }
      grid.appendChild(wrap);
    }
    panel.appendChild(grid);
    container.appendChild(panel);
  }
}

function collectSettings() {
  const payload = {};
  document.querySelectorAll("#settings-forms [data-path]").forEach((input) => {
    if (input.type === "number") {
      if (input.value === "") return;
      setPath(payload, input.dataset.path, Number(input.value));
    } else if (input.type === "checkbox") {
      setPath(payload, input.dataset.path, input.checked);
    } else {
      setPath(payload, input.dataset.path, input.value);
    }
  });
  return payload;
}

async function loadSettings() {
  try {
    const [data, lic] = await Promise.all([api("/api/settings"), api("/api/license/status")]);
    state.settings = data;
    buildSettingsForms(data.config);
    /* Show current license status in the License section header */
    const groups = document.querySelectorAll(".sgroup-head");
    for (const h of groups) {
      if (h.textContent === "License") {
        if (lic.activated) {
          h.textContent = "License — active (" + (lic.key_hint || "") + ", account " + (lic.mt5_account || "?") + ")";
        } else {
          h.textContent = "License — not activated";
        }
      }
    }
    $("settings-notice").textContent = data.notices.length
      ? "⚠ " + data.notices.join(" · ")
      : "";
  } catch (err) {
    toast("Could not load settings: " + err.message, "error");
  }
}

$("btn-save-settings").addEventListener("click", async () => {
  if (!state.settings) return;
  const payload = collectSettings();

  /* Activate license if key + account were provided */
  const licKey = payload._license_key || "";
  const licAcct = payload._license_account || "";
  delete payload._license_key;
  delete payload._license_account;
  if (licKey || licAcct) {
    if (!licKey) { toast("Enter a license key to activate.", "error"); return; }
    if (!licAcct) { toast("Enter your MT5 account number.", "error"); return; }
    try {
      const res = await postJSON("/api/license/activate", { key: licKey, mt5_account: licAcct });
      toast("License activated for MT5 account " + (res.mt5_account || licAcct), "success");
    } catch (err) {
      toast("License activation failed: " + err.message, "error");
      return;
    }
  }

  const goingLive = payload.dry_run === false && state.settings.config.dry_run === true;
  if (goingLive) {
    const ok = window.confirm(
      "You are switching to LIVE trading.\n\n" +
      "Only continue if:\n" +
      "· you are using a demo or fully tested broker account\n" +
      "· stop loss (points) > 0 is set\n" +
      "· Algo Trading is enabled in MetaTrader 5\n\n" +
      "This software can lose money. Start with paper mode until you are confident."
    );
    if (!ok) return;
  }
  try {
    await postJSON("/api/settings", { config: payload });
    toast("Settings saved — engine reloaded", "success");
    state.settings = null;
    await loadSettings();
  } catch (err) {
    toast("Save failed: " + err.message, "error");
  }
});

$("btn-cancel-settings").addEventListener("click", () => {
  if (state.settings) buildSettingsForms(state.settings.config);
});

/* ------------------------------------------------------------------ */
/* logs                                                                */
/* ------------------------------------------------------------------ */
let logsPinned = true;
$("logs-box").addEventListener("scroll", () => {
  const box = $("logs-box");
  logsPinned = box.scrollHeight - box.scrollTop - box.clientHeight < 30;
});

function renderLogs(s) {
  if (!s.ok) return;
  const box = $("logs-box");
  const wasPinned = logsPinned;
  box.innerHTML = "";
  for (const line of s.logs || []) {
    const row = el("div", "log-line");
    const ts = el("span", "log-time");
    ts.textContent = new Date().toLocaleTimeString();
    row.appendChild(ts);
    row.appendChild(el("span", "log-msg", esc(line)));
    box.appendChild(row);
  }
  if (wasPinned) box.scrollTop = box.scrollHeight;
}

$("btn-clear-logs").addEventListener("click", () => {
  $("logs-box").innerHTML = "";
});

/* ------------------------------------------------------------------ */
/* strategy illustration                                               */
/* ------------------------------------------------------------------ */
function drawStrategyIllustration() {
  const canvas = $("strategy-illustration");
  const { ctx, w, h } = setupCanvas(canvas);
  ctx.clearRect(0, 0, w, h);

  const padL = 40, padR = 20, padT = 18, padB = 24;
  const pw = w - padL - padR;
  const ph = h - padT - padB;
  const n = 90;

  ctx.font = "11px 'Chakra Petch', system-ui, sans-serif";

  // band 70-30
  const yAt = (v) => padT + ph - (v / 100) * ph;
  ctx.fillStyle = CHART.band;
  ctx.fillRect(padL, yAt(70), pw, yAt(30) - yAt(70));
  ctx.strokeStyle = CHART.gridStrong;
  ctx.setLineDash([4, 4]);
  [70, 30].forEach((lv) => {
    ctx.beginPath();
    ctx.moveTo(padL, yAt(lv));
    ctx.lineTo(w - padR, yAt(lv));
    ctx.stroke();
  });
  ctx.setLineDash([]);
  ctx.fillStyle = CHART.gridLabel;
  ctx.textAlign = "right";
  ctx.fillText("70", padL - 6, yAt(70));
  ctx.fillText("30", padL - 6, yAt(30));

  // synthetic RSI series with a crossover near the end
  const rsi = [];
  let v = 45;
  for (let i = 0; i < n; i++) {
    const crossPoint = n - 26;
    const drift = i < crossPoint ? 0.18 : 0.5;
    v += (Math.random() - 0.42) * drift;
    rsi.push(Math.max(8, Math.min(92, v)));
  }

  // ema48 = smoothed rsi, ema50 = slower
  const ema = (values, alpha) => {
    const out = [values[0]];
    for (let i = 1; i < values.length; i++) out.push(out[i - 1] + alpha * (values[i] - out[i - 1]));
    return out;
  };
  const e48 = ema(rsi, 0.2);
  const e50 = ema(rsi, 0.1);

  const xAt = (i) => padL + (i + 0.5) * (pw / n);
  const drawSeries = (arr, color, width) => {
    ctx.strokeStyle = color;
    ctx.lineWidth = width;
    ctx.beginPath();
    ctx.moveTo(xAt(0), yAt(arr[0]));
    for (let i = 1; i < n; i++) ctx.lineTo(xAt(i), yAt(arr[i]));
    ctx.stroke();
  };
  ctx.lineWidth = 1;
  drawSeries(rsi, CHART.rsi, 2);
  drawSeries(e48, CHART.emaFast, 1.6);
  drawSeries(e50, CHART.emaSlow, 1.6);

  // mark the crossover
  let crossIdx = -1;
  for (let i = 1; i < n; i++) {
    if (e48[i - 1] <= e50[i - 1] && e48[i] > e50[i]) {
      crossIdx = i;
      break;
    }
  }
  if (crossIdx > 0) {
    const x = xAt(crossIdx);
    ctx.fillStyle = CHART.up;
    ctx.beginPath();
    ctx.moveTo(x, yAt(20) - 8);
    ctx.lineTo(x - 7, yAt(20));
    ctx.lineTo(x + 7, yAt(20));
    ctx.closePath();
    ctx.fill();
    ctx.fillStyle = CHART.gridLabel;
    ctx.textAlign = "center";
    ctx.fillText("EMA48 crosses EMA50 → signal", x, yAt(16) - 4);
  }
}

/* ------------------------------------------------------------------ */
/* illustrations (inline SVG, no assets)                               */
/* ------------------------------------------------------------------ */
const ILLUSTRATIONS = {
  emptyPositions:
    '<svg width="160" height="120" viewBox="0 0 160 120" fill="none">' +
    '<path d="M14 96V60l20-12 18 10 22-26 20 14" stroke="#111113" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>' +
    '<path d="M94 96V70l14-10 18 8 16-16" stroke="#2f3bff" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>' +
    '<path d="M22 28h70M22 36h44" stroke="#b8860b" stroke-width="2" stroke-linecap="round"/>' +
    '<rect x="104" y="24" width="44" height="30" stroke="#0a9e5c" stroke-width="2"/>' +
    '<circle cx="126" cy="39" r="4" fill="#0a9e5c"/>' +
    '</svg>',
  emptyHistory:
    '<svg width="160" height="120" viewBox="0 0 160 120" fill="none">' +
    '<circle cx="80" cy="58" r="40" stroke="#111113" stroke-width="2" stroke-dasharray="6 6"/>' +
    '<path d="M80 58V30" stroke="#2f3bff" stroke-width="2.5" stroke-linecap="round"/>' +
    '<path d="M80 58l26 15" stroke="#0a9e5c" stroke-width="2.5" stroke-linecap="round"/>' +
    '<circle cx="80" cy="58" r="5" fill="#111113"/>' +
    '<circle cx="106" cy="73" r="5" fill="#0a9e5c"/>' +
    '<path d="M38 88c16-7 26 7 42 0s24 5 42 0" stroke="#b8860b" stroke-width="1.5" stroke-linecap="round"/>' +
    '</svg>',
  emptyBacktest:
    '<svg width="160" height="120" viewBox="0 0 160 120" fill="none">' +
    '<path d="M16 92V56l20-12 18 10 22-26 20 16 14-10 22 14" stroke="#111113" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>' +
    '<path d="M22 100h116" stroke="#2f3bff" stroke-width="2" stroke-linecap="round"/>' +
    '<circle cx="96" cy="56" r="5" fill="#b8860b"/>' +
    '<rect x="120" y="26" width="24" height="24" stroke="#0a9e5c" stroke-width="2"/>' +
    '<path d="M126 38h12M132 32v12" stroke="#0a9e5c" stroke-width="2" stroke-linecap="round"/>' +
    '</svg>',
};

/* ------------------------------------------------------------------ */
/* resize handling                                                     */
/* ------------------------------------------------------------------ */
let resizeTimer = null;
window.addEventListener("resize", () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => {
    if (state.snapshot && state.snapshot.ok) {
      candleChart.update(state.snapshot.candles || [], state.snapshot.markers || []);
      rsiChart.update(state.snapshot.indicators || [], state.snapshot.markers || []);
    }
    if (state.history) renderHistory(state.history);
    drawStrategyIllustration();
  }, 150);
});

/* ------------------------------------------------------------------ */
/* license gate                                                        */
/* ------------------------------------------------------------------ */
let license = null;

async function checkLicense() {
  license = await api("/api/license/status");
  return license;
}

function showLicenseGate() {
  if (!license) return;
  const amount = $("license-price");
  amount.textContent = new Intl.NumberFormat(undefined, {
    style: "currency",
    currency: license.currency || "USD",
  }).format(license.price || 0);
  $("license-currency").textContent = license.currency || "USD";

  const pay = $("license-pay");
  const alternate = $("license-alternate");
  if (license.payment_url) {
    pay.href = license.payment_url;
    pay.classList.remove("hidden");
    alternate.classList.add("hidden");
  } else {
    pay.classList.add("hidden");
    alternate.classList.remove("hidden");
  }
  $("license-overlay").hidden = false;
  loadPaymentAddresses();
}

/* crypto payment (HMPyWeb3Kit deposit addresses) ---------------------- */
async function loadPaymentAddresses() {
  const box = $("license-crypto");
  if (!box) return;
  try {
    box.hidden = true;
    const res = await api("/api/payment/addresses");
    if (!res || !res.ok || !res.btc || !res.usdt) throw new Error(res && res.error);
    $("pay-btc-addr").textContent = res.btc.address || "—";
    $("pay-usdt-addr").textContent = res.usdt.address || "—";
    box.hidden = false;
  } catch (err) {
    box.hidden = true;
    console.warn("Crypto addresses unavailable:", err);
  }
}

async function copyAddress(e) {
  const btn = e.currentTarget;
  const text = ($(btn.dataset.copy) || {}).textContent || "";
  if (!text || text === "—") return;
  try {
    await navigator.clipboard.writeText(text);
  } catch (err) {
    const ta = el("textarea");
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    document.execCommand("copy");
    ta.remove();
  }
  const old = btn.textContent;
  btn.textContent = "Copied ✓";
  setTimeout(() => (btn.textContent = old), 1400);
}

async function checkPayment() {
  const btn = $("crypto-check");
  const status = $("crypto-status");
  btn.disabled = true;
  btn.textContent = "Checking…";
  status.textContent = "Contacting the payment API…";
  status.classList.remove("crypto-status-ok");
  const targets = [
    { chain: "btc", address: ($("pay-btc-addr") || {}).textContent || "" },
    { chain: "usdt", address: ($("pay-usdt-addr") || {}).textContent || "" },
  ];
  const received = [];
  let lastError = "";
  try {
    for (const t of targets) {
      if (!t.address || t.address === "—") continue;
      try {
        const res = await postJSON("/api/payment/check", t);
        if (!res || !res.ok) throw new Error(res && res.error);
        const amount = `${res.chain.toUpperCase()} ${res.balance ?? "—"} ${res.unit || ""}`;
        const usd = res.balance_usd != null ? ` (≈ $${res.balance_usd})` : "";
        received.push(amount + usd);
      } catch (err) {
        lastError = err.message || "Payment check failed";
      }
    }
    if (received.length) {
      status.textContent = "Received so far: " + received.join(" · ");
      status.classList.add("crypto-status-ok");
    } else {
      status.textContent = lastError || "No payment received yet — send funds, then check again.";
    }
  } finally {
    btn.disabled = false;
    btn.textContent = "Check payment";
  }
}

async function tryActivate() {
  const key = $("license-key").value.trim();
  const account = $("license-account").value.trim();
  const errorBox = $("license-error");
  errorBox.textContent = "";
  if (!key) {
    errorBox.textContent = "Enter your license key first.";
    return;
  }
  if (!account) {
    errorBox.textContent = "Enter the MT5 account number this license is for.";
    return;
  }
  const btn = $("license-activate");
  btn.disabled = true;
  btn.textContent = "Activating…";
  try {
    const res = await postJSON("/api/license/activate", { key, mt5_account: account });
    license = res;
    $("license-key").value = "";
    $("license-account").value = "";
    $("license-overlay").hidden = true;
    toast("Bot activated for MT5 account " + (res.mt5_account || account), "success");
    poll();
  } catch (err) {
    errorBox.textContent = err.message || "Activation failed";
  } finally {
    btn.disabled = false;
    btn.textContent = "Activate";
  }
}

async function prefillAccount() {
  try {
    const snap = await api("/api/state");
    const login = snap.account && snap.account.login;
    if (login && login !== "SIM" && $("license-account").value === "") {
      $("license-account").value = login;
    }
  } catch (e) {}
}

$("license-activate").addEventListener("click", tryActivate);
$("license-key").addEventListener("keydown", (e) => {
  if (e.key === "Enter") tryActivate();
});

const cryptoCheck = $("crypto-check");
if (cryptoCheck) cryptoCheck.addEventListener("click", checkPayment);
document.querySelectorAll(".crypto-copy").forEach((b) => {
  b.addEventListener("click", copyAddress);
});

const openPaymentModal = $("open-payment-modal");
const paymentModal = $("payment-modal");
const closePaymentModal = $("close-payment-modal");
if (openPaymentModal) {
  openPaymentModal.addEventListener("click", (e) => {
    e.preventDefault();
    if (paymentModal) paymentModal.hidden = false;
    loadPaymentAddresses();
  });
}
if (closePaymentModal) {
  closePaymentModal.addEventListener("click", () => {
    if (paymentModal) paymentModal.hidden = true;
  });
}
if (paymentModal) {
  paymentModal.addEventListener("click", (e) => {
    if (e.target === paymentModal) paymentModal.hidden = true;
  });
}
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && paymentModal && !paymentModal.hidden) paymentModal.hidden = true;
});

/* initial */
applyTheme(readTheme(), false);
checkLicense().then((lic) => {
  if (!lic.activated) {
    showLicenseGate();
    prefillAccount();
    return;
  }
  poll();
}).catch(() => {
  showLicenseGate();
  prefillAccount();
});
