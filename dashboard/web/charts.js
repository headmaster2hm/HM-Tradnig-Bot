"use strict";

/* HM Bot Trader â€” dependency-free canvas charts */

function setupCanvas(canvas) {
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  const w = Math.max(1, rect.width);
  const h = Math.max(1, rect.height);
  canvas.width = Math.round(w * dpr);
  canvas.height = Math.round(h * dpr);
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  return { ctx, w, h };
}

const CHART = {
  up: "#0a9e5c",
  down: "#e5484d",
  grid: "rgba(17,17,19,0.07)",
  gridStrong: "rgba(17,17,19,0.18)",
  gridLabel: "#8a8a90",
  crosshair: "rgba(17,17,19,0.4)",
  rsi: "#2f3bff",
  emaFast: "#b8860b",
  emaSlow: "#8a8a90",
  band: "rgba(47,59,255,0.06)",
  equity: "#2f3bff",
  equityFade: "rgba(47,59,255,0.28)",
  equityFadeLow: "rgba(47,59,255,0.02)",
};

function cssVar(name, fallback) {
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v || fallback;
}

/* Pull chart colors from the active theme (dark is default). */
function syncChartTheme() {
  CHART.up = cssVar("--up", CHART.up);
  CHART.down = cssVar("--down", CHART.down);
  CHART.grid = cssVar("--chart-grid", CHART.grid);
  CHART.gridStrong = cssVar("--chart-grid-strong", CHART.gridStrong);
  CHART.gridLabel = cssVar("--chart-grid-label", CHART.gridLabel);
  CHART.crosshair = cssVar("--chart-crosshair", CHART.crosshair);
  CHART.rsi = cssVar("--accent", CHART.rsi);
  CHART.emaFast = cssVar("--gold", CHART.emaFast);
  CHART.emaSlow = cssVar("--muted", CHART.emaSlow);
  CHART.band = cssVar("--chart-band", CHART.band);
  CHART.equity = cssVar("--accent", CHART.equity);
  CHART.equityFade = cssVar("--chart-equity-fade", CHART.equityFade);
  CHART.equityFadeLow = cssVar("--chart-equity-fade-low", CHART.equityFadeLow);
}
syncChartTheme();

function priceDecimals(price) {
  if (price >= 1000) return 2;
  if (price >= 10) return 3;
  return 5;
}

function roundLabel(value, decimals) {
  return Number(value).toFixed(decimals);
}

/* ------------------------------------------------------------------ */
/* Candlestick chart                                                   */
/* ------------------------------------------------------------------ */
class CandleChart {
  constructor(canvas) {
    this.canvas = canvas;
    this.data = [];
    this.markers = [];
    this.hover = -1;
    this.tooltip = document.createElement("div");
    this.tooltip.className = "chart-tooltip";
    document.body.appendChild(this.tooltip);

    canvas.addEventListener("mousemove", (e) => {
      const rect = canvas.getBoundingClientRect();
      this.hover = this.idxAtX(e.clientX - rect.left);
      this.render();
      this.showTooltip(e.clientX, e.clientY);
    });
    canvas.addEventListener("mouseleave", () => {
      this.hover = -1;
      this.render();
      this.hideTooltip();
    });
  }

  idxAtX(x) {
    const rect = this.canvas.getBoundingClientRect();
    const padL = 64, padR = 14;
    const pw = Math.max(1, rect.width - padL - padR);
    const n = this.data.length;
    if (!n) return -1;
    const step = pw / n;
    let i = Math.floor((x - padL) / step);
    i = Math.max(0, Math.min(n - 1, i));
    return i;
  }

  hideTooltip() {
    this.tooltip.style.display = "none";
  }

  showTooltip(cx, cy) {
    if (this.hover < 0) return;
    const c = this.data[this.hover];
    if (!c) return;
    const dec = priceDecimals(c.c);
    const dir = c.c >= c.o ? this.upColor : this.downColor;
    this.tooltip.innerHTML =
      `<b>${esc(c.t)}</b>` +
      `<span>O <i style="color:${dir}">${c.o.toFixed(dec)}</i></span>` +
      `<span>H <i>${c.h.toFixed(dec)}</i></span>` +
      `<span>L <i>${c.l.toFixed(dec)}</i></span>` +
      `<span>C <i style="color:${dir}">${c.c.toFixed(dec)}</i></span>` +
      `<span>Vol <i>${c.v || 0}</i></span>`;
    this.tooltip.style.display = "block";
    this.tooltip.style.left = Math.min(cx + 14, window.innerWidth - 150) + "px";
    this.tooltip.style.top = Math.max(8, cy - 70) + "px";
  }

  get upColor() {
    return CHART.up;
  }
  get downColor() {
    return CHART.down;
  }

  update(data, markers) {
    this.data = data || [];
    this.markers = markers || [];
    this.render();
  }

  render() {
    if (!this.data.length) return;
    const { ctx, w, h } = setupCanvas(this.canvas);
    const padL = 64, padR = 14, padT = 10, padB = 22;
    const pw = w - padL - padR;
    const ph = h - padT - padB;
    const n = this.data.length;

    let min = Infinity, max = -Infinity;
    for (const c of this.data) {
      if (c.l < min) min = c.l;
      if (c.h > max) max = c.h;
    }
    const padPct = (max - min) * 0.08 || 1;
    min -= padPct;
    max += padPct;

    const xAt = (i) => padL + (i + 0.5) * (pw / n);
    const yAt = (p) => padT + ph - ((p - min) / (max - min)) * ph;
    const dec = priceDecimals((max + min) / 2);

    ctx.font = "11px 'Chakra Petch', system-ui, sans-serif";
    ctx.lineWidth = 1;

    // grid + price labels
    const rows = 5;
    ctx.textAlign = "right";
    ctx.textBaseline = "middle";
    for (let r = 0; r <= rows; r++) {
      const price = min + ((max - min) * r) / rows;
      const y = yAt(price);
      ctx.strokeStyle = CHART.grid;
      ctx.beginPath();
      ctx.moveTo(padL, y);
      ctx.lineTo(w - padR, y);
      ctx.stroke();
      ctx.fillStyle = CHART.gridLabel;
      ctx.fillText(roundLabel(price, dec), padL - 6, y);
    }

    // time labels
    ctx.textAlign = "center";
    ctx.textBaseline = "top";
    const labelEvery = Math.max(1, Math.ceil(n / 5));
    for (let i = 0; i < n; i += labelEvery) {
      const c = this.data[i];
      const x = xAt(i);
      ctx.strokeStyle = CHART.grid;
      ctx.beginPath();
      ctx.moveTo(x, padT);
      ctx.lineTo(x, padT + ph);
      ctx.stroke();
      ctx.fillStyle = CHART.gridLabel;
      ctx.fillText(timeLabel(c.t), x, padT + ph + 5);
    }

    // candles
    const step = pw / n;
    const cw = Math.max(1, step * 0.66);
    for (let i = 0; i < n; i++) {
      const c = this.data[i];
      const up = c.c >= c.o;
      ctx.strokeStyle = up ? CHART.up : CHART.down;
      ctx.fillStyle = up ? CHART.up : CHART.down;
      const x = xAt(i);
      const yHigh = yAt(c.h);
      const yLow = yAt(c.l);
      const yOpen = yAt(c.o);
      const yClose = yAt(c.c);
      ctx.beginPath();
      ctx.moveTo(x, yHigh);
      ctx.lineTo(x, yLow);
      ctx.stroke();
      const top = Math.min(yOpen, yClose);
      const bot = Math.max(yOpen, yClose);
      if (up) {
        ctx.fillRect(x - cw / 2, top, cw, Math.max(1, bot - top));
      } else {
        ctx.beginPath();
        ctx.rect(x - cw / 2, top, cw, Math.max(1, bot - top));
        ctx.fill();
      }
    }

    // trade markers
    for (const m of this.markers) {
      const i = this.data.findIndex(
        (c) => c.t && m.time && c.t.slice(0, 16) === m.time.slice(0, 16)
      );
      const idx = i >= 0 ? i : n - 1;
      const x = xAt(idx);
      const y = yAt(m.price);
      this.drawMarker(ctx, m, x, y);
    }

    // crosshair
    if (this.hover >= 0) {
      const c = this.data[this.hover];
      const x = xAt(this.hover);
      const y = yAt(c.c);
      ctx.strokeStyle = CHART.crosshair;
      ctx.setLineDash([4, 4]);
      ctx.beginPath();
      ctx.moveTo(x, padT);
      ctx.lineTo(x, padT + ph);
      ctx.moveTo(padL, y);
      ctx.lineTo(w - padR, y);
      ctx.stroke();
      ctx.setLineDash([]);
    }
  }

  drawMarker(ctx, m, x, y) {
    const r = 5;
    if (m.side === "BUY" || (m.kind === "entry" && m.side === "BUY")) {
      ctx.fillStyle = CHART.up;
      ctx.beginPath();
      ctx.moveTo(x, y - r);
      ctx.lineTo(x - r, y + r * 0.7);
      ctx.lineTo(x + r, y + r * 0.7);
      ctx.closePath();
      ctx.fill();
    } else if (m.side === "SELL") {
      ctx.fillStyle = CHART.down;
      ctx.beginPath();
      ctx.moveTo(x, y + r);
      ctx.lineTo(x - r, y - r * 0.7);
      ctx.lineTo(x + r, y - r * 0.7);
      ctx.closePath();
      ctx.fill();
    } else {
      ctx.strokeStyle = CHART.emaSlow;
      ctx.beginPath();
      ctx.arc(x, y, 3, 0, Math.PI * 2);
      ctx.stroke();
    }
  }
}

/* ------------------------------------------------------------------ */
/* RSI + EMA line chart (fixed 0â€“100 scale)                            */
/* ------------------------------------------------------------------ */
class RsiChart {
  constructor(canvas) {
    this.canvas = canvas;
    this.data = [];
    this.markers = [];
    this.hover = -1;
    this.tooltip = document.createElement("div");
    this.tooltip.className = "chart-tooltip";
    document.body.appendChild(this.tooltip);

    canvas.addEventListener("mousemove", (e) => {
      const rect = canvas.getBoundingClientRect();
      this.hover = this.idxAtX(e.clientX - rect.left);
      this.render();
      this.showTooltip(e.clientX, e.clientY);
    });
    canvas.addEventListener("mouseleave", () => {
      this.hover = -1;
      this.render();
      this.hideTooltip();
    });
  }

  idxAtX(x) {
    const rect = this.canvas.getBoundingClientRect();
    const padL = 64, padR = 14;
    const pw = Math.max(1, rect.width - padL - padR);
    const n = this.data.length;
    if (!n) return -1;
    const step = pw / n;
    let i = Math.floor((x - padL) / step);
    return Math.max(0, Math.min(n - 1, i));
  }

  hideTooltip() {
    this.tooltip.style.display = "none";
  }

  showTooltip(cx, cy) {
    if (this.hover < 0) return;
    const d = this.data[this.hover];
    if (!d) return;
    this.tooltip.innerHTML =
      `<b>${esc(d.t)}</b>` +
      `<span>RSI <i style="color:${CHART.rsi}">${d.rsi != null ? d.rsi.toFixed(1) : "â€”"}</i></span>` +
      `<span>EMA48 <i style="color:${CHART.emaFast}">${d.ema48 != null ? d.ema48.toFixed(1) : "â€”"}</i></span>` +
      `<span>EMA50 <i style="color:${CHART.emaSlow}">${d.ema50 != null ? d.ema50.toFixed(1) : "â€”"}</i></span>`;
    this.tooltip.style.display = "block";
    this.tooltip.style.left = Math.min(cx + 14, window.innerWidth - 160) + "px";
    this.tooltip.style.top = Math.max(8, cy - 60) + "px";
  }

  update(data, markers) {
    this.data = data || [];
    this.markers = markers || [];
    this.render();
  }

  render() {
    if (!this.data.length) return;
    const { ctx, w, h } = setupCanvas(this.canvas);
    const padL = 64, padR = 14, padT = 10, padB = 22;
    const pw = w - padL - padR;
    const ph = h - padT - padB;
    const n = this.data.length;
    const min = 0, max = 100;
    const xAt = (i) => padL + (i + 0.5) * (pw / n);
    const yAt = (v) => padT + ph - ((v - min) / (max - min)) * ph;

    ctx.font = "11px 'Chakra Petch', system-ui, sans-serif";

    // oversold / overbought band fill
    ctx.fillStyle = CHART.band;
    ctx.fillRect(padL, yAt(70), pw, yAt(30) - yAt(70));

    // level lines
    ctx.textAlign = "right";
    ctx.textBaseline = "middle";
    for (const lv of [100, 85, 70, 63, 50, 39, 30, 15, 0]) {
      const y = yAt(lv);
      const major = lv === 50 || lv === 70 || lv === 30;
      ctx.strokeStyle = major ? CHART.gridStrong : CHART.grid;
      ctx.setLineDash(major ? [] : [3, 4]);
      ctx.beginPath();
      ctx.moveTo(padL, y);
      ctx.lineTo(w - padR, y);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = CHART.gridLabel;
      ctx.fillText(String(lv), padL - 6, y);
    }

    // time labels
    ctx.textAlign = "center";
    ctx.textBaseline = "top";
    const labelEvery = Math.max(1, Math.ceil(n / 5));
    for (let i = 0; i < n; i += labelEvery) {
      const d = this.data[i];
      const x = xAt(i);
      ctx.fillStyle = CHART.gridLabel;
      ctx.fillText(timeLabel(d.t), x, padT + ph + 5);
    }

    const series = [
      { key: "rsi", color: CHART.rsi, width: 1.8 },
      { key: "ema48", color: CHART.emaFast, width: 1.4 },
      { key: "ema50", color: CHART.emaSlow, width: 1.4 },
    ];
    for (const s of series) {
      ctx.strokeStyle = s.color;
      ctx.lineWidth = s.width;
      ctx.beginPath();
      let started = false;
      for (let i = 0; i < n; i++) {
        const v = this.data[i][s.key];
        if (v == null) continue;
        const x = xAt(i);
        const y = yAt(v);
        if (!started) {
          ctx.moveTo(x, y);
          started = true;
        } else {
          ctx.lineTo(x, y);
        }
      }
      ctx.stroke();
    }
    ctx.lineWidth = 1;

    // markers (RSI value at bar time)
    for (const m of this.markers) {
      const i = this.data.findIndex(
        (d) => d.t && m.time && d.t.slice(0, 16) === m.time.slice(0, 16)
      );
      const idx = i >= 0 ? i : n - 1;
      const d = this.data[idx];
      if (d.rsi == null) continue;
      const x = xAt(idx);
      const y = yAt(d.rsi);
      const r = 5;
      if (m.side === "BUY") {
        ctx.fillStyle = CHART.up;
        ctx.beginPath();
        ctx.moveTo(x, y - r);
        ctx.lineTo(x - r, y + r * 0.7);
        ctx.lineTo(x + r, y + r * 0.7);
        ctx.closePath();
        ctx.fill();
      } else if (m.side === "SELL") {
        ctx.fillStyle = CHART.down;
        ctx.beginPath();
        ctx.moveTo(x, y + r);
        ctx.lineTo(x - r, y - r * 0.7);
        ctx.lineTo(x + r, y - r * 0.7);
        ctx.closePath();
        ctx.fill();
      }
    }

    // crosshair
    if (this.hover >= 0) {
      const d = this.data[this.hover];
      const x = xAt(this.hover);
      const y = yAt(d.rsi != null ? d.rsi : 50);
      ctx.strokeStyle = CHART.crosshair;
      ctx.setLineDash([4, 4]);
      ctx.beginPath();
      ctx.moveTo(x, padT);
      ctx.lineTo(x, padT + ph);
      ctx.moveTo(padL, y);
      ctx.lineTo(w - padR, y);
      ctx.stroke();
      ctx.setLineDash([]);
    }
  }
}

/* ------------------------------------------------------------------ */
/* Equity area chart                                                   */
/* ------------------------------------------------------------------ */
class EquityChart {
  constructor(canvas) {
    this.canvas = canvas;
    this.points = [];
  }

  update(points) {
    this.points = points || [];
    this.render();
  }

  render() {
    const { ctx, w, h } = setupCanvas(this.canvas);
    const padL = 56, padR = 14, padT = 12, padB = 22;
    const pw = w - padL - padR;
    const ph = h - padT - padB;
    const n = this.points.length;
    ctx.clearRect(0, 0, w, h);

    ctx.font = "11px 'Chakra Petch', system-ui, sans-serif";
    ctx.strokeStyle = CHART.grid;
    ctx.fillStyle = CHART.gridLabel;

    // baseline grid
    ctx.textAlign = "right";
    ctx.textBaseline = "middle";
    const rows = 4;
    for (let r = 0; r <= rows; r++) {
      const y = padT + (ph * r) / rows;
      ctx.beginPath();
      ctx.moveTo(padL, y);
      ctx.lineTo(w - padR, y);
      ctx.stroke();
    }

    if (!n) {
      ctx.textAlign = "center";
      ctx.fillText("No closed trades yet", padL + pw / 2, padT + ph / 2);
      return;
    }

    let min = Infinity, max = -Infinity;
    for (const p of this.points) {
      if (p.y < min) min = p.y;
      if (p.y > max) max = p.y;
    }
    const span = max - min || 1;
    min -= span * 0.1;
    max += span * 0.1;

    const xAt = (i) => padL + (i + 0.5) * (pw / n);
    const yAt = (v) => padT + ph - ((v - min) / (max - min)) * ph;

    // zero line
    if (min < 0 && max > 0) {
      const y0 = yAt(0);
      ctx.strokeStyle = CHART.crosshair;
      ctx.setLineDash([4, 4]);
      ctx.beginPath();
      ctx.moveTo(padL, y0);
      ctx.lineTo(w - padR, y0);
      ctx.stroke();
      ctx.setLineDash([]);
    }

    // gradient fill
    const grad = ctx.createLinearGradient(0, padT, 0, padT + ph);
    grad.addColorStop(0, CHART.equityFade);
    grad.addColorStop(1, CHART.equityFadeLow);
    ctx.beginPath();
    ctx.moveTo(xAt(0), yAt(this.points[0].y));
    for (let i = 1; i < n; i++) ctx.lineTo(xAt(i), yAt(this.points[i].y));
    ctx.lineTo(xAt(n - 1), yAt(min));
    ctx.lineTo(xAt(0), yAt(min));
    ctx.closePath();
    ctx.fillStyle = grad;
    ctx.fill();

    // line
    ctx.strokeStyle = CHART.equity;
    ctx.lineWidth = 1.8;
    ctx.beginPath();
    ctx.moveTo(xAt(0), yAt(this.points[0].y));
    for (let i = 1; i < n; i++) ctx.lineTo(xAt(i), yAt(this.points[i].y));
    ctx.stroke();
    ctx.lineWidth = 1;

    // value labels
    ctx.textAlign = "right";
    for (let r = 0; r <= rows; r++) {
      const v = max - ((max - min) * r) / rows;
      ctx.fillText(v.toFixed(2), padL - 6, padT + (ph * r) / rows);
    }
  }
}

/* ------------------------------------------------------------------ */
/* helpers                                                             */
/* ------------------------------------------------------------------ */
function timeLabel(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

function esc(text) {
  return String(text).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );
}

