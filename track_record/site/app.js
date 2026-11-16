// Live track record page. Reads data/track_record.json and draws inline SVG.
// All text is set with textContent; nothing from the data is parsed as HTML.
"use strict";

const SVG = "http://www.w3.org/2000/svg";
const COLOR_VARS = ["--s1", "--s2", "--s3", "--s4"];
let DOC = null;

const $ = (id) => document.getElementById(id);
const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const pct = (v, dp = 1) => (v > 0 ? "+" : v < 0 ? "−" : "") + Math.abs(v).toFixed(dp) + "%";
const day = (iso) => new Date(iso + "T00:00:00Z");
const fmtDate = (iso) => day(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
const fmtMonth = (ym) => day(ym + "-01").toLocaleDateString("en-GB", { month: "short", year: "numeric", timeZone: "UTC" });

function el(tag, attrs = {}, text) {
  const n = tag.startsWith("svg:") ? document.createElementNS(SVG, tag.slice(4)) : document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
  if (text !== undefined) n.textContent = text;
  return n;
}

function niceTicks(lo, hi, n = 5) {
  if (lo === hi) { lo -= 1; hi += 1; }
  const raw = (hi - lo) / n, mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw);
  const out = [];
  for (let v = Math.floor(lo / step) * step; v <= hi + step * 1e-9; v += step) out.push(+v.toFixed(10));
  if (out[out.length - 1] < hi) out.push(out[out.length - 1] + step);
  return out;
}

// ---------- tooltip ----------
const tip = $("tip");
function showTip(evt, build) {
  tip.replaceChildren();
  build(tip);
  tip.hidden = false;
  const pad = 14, r = tip.getBoundingClientRect();
  let x = evt.clientX + pad, y = evt.clientY + pad;
  if (x + r.width > innerWidth - 8) x = evt.clientX - r.width - pad;
  if (y + r.height > innerHeight - 8) y = evt.clientY - r.height - pad;
  tip.style.left = Math.max(8, x) + "px";
  tip.style.top = Math.max(8, y) + "px";
}
const hideTip = () => { tip.hidden = true; };
function tipRow(parent, color, label, value) {
  const row = el("div", { class: "row" });
  const left = el("span");
  if (color) { const sw = el("span", { class: "swatch" }); sw.style.background = color; left.append(sw); }
  left.append(document.createTextNode(label));
  row.append(left, el("span", {}, value));
  parent.append(row);
}

// ---------- header, tiles, legend ----------
function header(doc) {
  document.title = doc.title;
  $("title").textContent = doc.title;
  $("lede").textContent = doc.lede;
  const updated = doc.generated_at ? fmtDate(doc.generated_at.slice(0, 10)) : null;
  $("meta").textContent = `${doc.since_label} ${fmtDate(doc.first_day)} · last trade ${fmtDate(doc.as_of)}` +
    (updated ? ` · updated ${updated}` : "") + " · refreshed every weekday evening";
  $("built").textContent = doc.kind === "live"
    ? "How it is built: a scheduled AWS Lambda reads the trading system's ledger with read-only access and publishes daily totals only."
    : "How it is built: after the daily backtest update, the trading system exports per-day totals that must tie out to its own books (or nothing is published); a scheduled AWS Lambda reads only that feed and rebuilds this page.";
  $("definition").textContent = doc.definition;
  $("disclaimer").textContent = doc.disclaimer;
}

function tiles(doc, colors) {
  const box = $("tiles");
  box.replaceChildren();
  doc.strategies.forEach((s, i) => {
    const m = s.summary, t = el("article", { class: "tile" });
    const name = el("div", { class: "name" });
    const sw = el("span", { class: "swatch" }); sw.style.background = colors[i];
    name.append(sw, document.createTextNode(s.name));
    t.append(name, el("div", { class: "big" }, pct(m.total_pnl_pct)),
      el("p", { class: "since" }, `since ${fmtDate(m.first_day)} · simple sum`));
    const dl = el("dl");
    const add = (k, v) => dl.append(el("dt", {}, k), el("dd", {}, v));
    add("Days traded", String(m.days_traded));
    add("Trades", String(m.trades));
    add("Winning days", `${m.win_days} of ${m.days_traded} (${m.win_day_pct.toFixed(0)}%)`);
    add("Average day", pct(m.avg_day_pct, 2));
    add("Best / worst day", `${pct(m.best_day_pct)} / ${pct(m.worst_day_pct)}`);
    add("Largest drawdown", pct(-m.max_drawdown_pct));
    t.append(dl);
    box.append(t);
  });
}

function legend(doc, colors) {
  const box = $("legend");
  box.replaceChildren();
  doc.strategies.forEach((s, i) => {
    const item = el("span"), sw = el("span", { class: "swatch" });
    sw.style.background = colors[i];
    item.append(sw, document.createTextNode(s.name));
    box.append(item);
  });
}

// ---------- cumulative line chart ----------
function cumulative(doc, colors) {
  const box = $("cum");
  box.replaceChildren();
  const W = Math.max(320, box.clientWidth), H = W < 560 ? 240 : 300;
  const m = { l: 56, r: W < 560 ? 12 : 120, t: 12, b: 28 };
  const pw = W - m.l - m.r, ph = H - m.t - m.b;
  const t0 = day(doc.first_day).getTime(), t1 = day(doc.as_of).getTime();
  const vals = doc.strategies.flatMap((s) => s.days.map((d) => d.cum_pct)).concat([0]);
  const ticks = niceTicks(Math.min(...vals), Math.max(...vals));
  const y0 = ticks[0], y1 = ticks[ticks.length - 1];
  const X = (iso) => m.l + ((day(iso).getTime() - t0) / Math.max(1, t1 - t0)) * pw;
  const Y = (v) => m.t + (1 - (v - y0) / (y1 - y0)) * ph;
  const svg = el("svg:svg", { viewBox: `0 0 ${W} ${H}`, width: W, height: H });

  for (const v of ticks) {
    svg.append(el("svg:line", { class: v === 0 ? "baseline" : "gridline", x1: m.l, x2: m.l + pw, y1: Y(v), y2: Y(v) }));
    svg.append(el("svg:text", { x: m.l - 8, y: Y(v) + 4, "text-anchor": "end" }, (v > 0 ? "+" : "") + v + "%"));
  }
  // month ticks on the x axis
  const start = day(doc.first_day);
  for (let d = new Date(Date.UTC(start.getUTCFullYear(), start.getUTCMonth() + 1, 1)); d.getTime() <= t1; d.setUTCMonth(d.getUTCMonth() + 1)) {
    const iso = d.toISOString().slice(0, 10), x = X(iso);
    if (W < 560 && d.getUTCMonth() % 2) continue;
    svg.append(el("svg:text", { x, y: H - 8, "text-anchor": "middle" }, d.toLocaleDateString("en-GB", { month: "short", timeZone: "UTC" })));
  }

  // each series starts from 0 on the day before its first trade, and runs flat to as_of
  const lastY = [];
  doc.strategies.forEach((s, i) => {
    const pts = [[X(s.days[0].date), Y(0)], ...s.days.map((d) => [X(d.date), Y(d.cum_pct)])];
    pts.push([X(doc.as_of), Y(s.summary.total_pnl_pct)]);
    const path = pts.map((p, k) => (k ? "L" : "M") + p[0].toFixed(1) + "," + p[1].toFixed(1)).join("");
    svg.append(el("svg:path", { d: path, fill: "none", stroke: colors[i], "stroke-width": 2, "stroke-linejoin": "round" }));
    lastY.push({ i, y: Y(s.summary.total_pnl_pct), s });
  });

  // direct end labels, nudged apart so they never overlap
  if (W >= 560) {
    lastY.sort((a, b) => a.y - b.y);
    for (let k = 1; k < lastY.length; k++) lastY[k].y = Math.max(lastY[k].y, lastY[k - 1].y + 16);
    for (const { s, y } of lastY) {
      svg.append(el("svg:text", { class: "label", x: m.l + pw + 8, y: y + 4 }, `${s.name.replace(" day", "")} ${pct(s.summary.total_pnl_pct, 0)}`));
    }
  }

  // crosshair + tooltip: value of every series on the hovered date (last known running sum)
  const cross = el("svg:line", { class: "cross", y1: m.t, y2: m.t + ph, visibility: "hidden" });
  const dots = doc.strategies.map((_, i) => el("svg:circle", { r: 4, fill: colors[i], stroke: css("--surface"), "stroke-width": 2, visibility: "hidden" }));
  svg.append(cross, ...dots);
  const hit = el("svg:rect", { x: m.l, y: m.t, width: pw, height: ph, fill: "transparent" });
  const allDates = [...new Set(doc.strategies.flatMap((s) => s.days.map((d) => d.date)))].sort();
  hit.addEventListener("pointermove", (evt) => {
    const r = svg.getBoundingClientRect(), x = ((evt.clientX - r.left) / r.width) * W;
    let best = allDates[0];
    for (const d of allDates) if (Math.abs(X(d) - x) < Math.abs(X(best) - x)) best = d;
    cross.setAttribute("x1", X(best)); cross.setAttribute("x2", X(best)); cross.setAttribute("visibility", "visible");
    showTip(evt, (t) => {
      t.append(el("div", { class: "t-date" }, fmtDate(best)));
      doc.strategies.forEach((s, i) => {
        const known = s.days.filter((d) => d.date <= best);
        const v = known.length ? known[known.length - 1].cum_pct : null;
        const dot = dots[i];
        if (v === null) { dot.setAttribute("visibility", "hidden"); tipRow(t, colors[i], s.name, "not started"); return; }
        dot.setAttribute("cx", X(best)); dot.setAttribute("cy", Y(v)); dot.setAttribute("visibility", "visible");
        const today = s.days.find((d) => d.date === best);
        tipRow(t, colors[i], s.name, pct(v) + (today ? ` (day ${pct(today.pnl_pct)})` : ""));
      });
    });
  });
  hit.addEventListener("pointerleave", () => {
    hideTip(); cross.setAttribute("visibility", "hidden");
    dots.forEach((d) => d.setAttribute("visibility", "hidden"));
  });
  svg.append(hit);
  box.append(svg);
}

// ---------- daily bars, one small chart per strategy ----------
function dailyBars(doc, colors) {
  const box = $("days");
  box.replaceChildren();
  const W = Math.max(320, box.clientWidth), H = 120, m = { l: 56, r: 8, t: 8, b: 20 };
  const pw = W - m.l - m.r, ph = H - m.t - m.b;
  const t0 = day(doc.first_day).getTime(), t1 = day(doc.as_of).getTime();
  const X = (iso) => m.l + ((day(iso).getTime() - t0) / Math.max(1, t1 - t0)) * pw;
  const span = Math.max(1, (t1 - t0) / 864e5);
  const bw = Math.max(2, Math.min(10, (pw / span) * 0.7));

  doc.strategies.forEach((s, i) => {
    const wrap = el("div", { class: "mini" });
    const h3 = el("h3"), sw = el("span", { class: "swatch" }); sw.style.background = colors[i];
    h3.append(sw, document.createTextNode(s.name),
      el("span", { class: "mini-sub" }, ` · ${s.summary.days_traded} days, ${s.summary.win_days} up`));
    wrap.append(h3);
    const v = s.days.map((d) => d.pnl_pct).concat([0]);
    const ticks = niceTicks(Math.min(...v), Math.max(...v), 2);
    const y0 = ticks[0], y1 = ticks[ticks.length - 1];
    const Y = (x) => m.t + (1 - (x - y0) / (y1 - y0)) * ph;
    const svg = el("svg:svg", { viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: "img", "aria-label": `Daily result, ${s.name}` });
    for (const t of ticks) {
      svg.append(el("svg:line", { class: t === 0 ? "baseline" : "gridline", x1: m.l, x2: m.l + pw, y1: Y(t), y2: Y(t) }));
      svg.append(el("svg:text", { x: m.l - 8, y: Y(t) + 4, "text-anchor": "end" }, (t > 0 ? "+" : "") + t + "%"));
    }
    for (const d of s.days) {
      const x = X(d.date) - bw / 2, top = Y(Math.max(0, d.pnl_pct)), h = Math.max(1, Math.abs(Y(d.pnl_pct) - Y(0)));
      const bar = el("svg:rect", { x, y: top, width: bw, height: h, fill: colors[i], rx: bw >= 6 ? 2 : 0 });
      const hitW = Math.max(bw, 10);
      const hit = el("svg:rect", { x: X(d.date) - hitW / 2, y: m.t, width: hitW, height: ph, fill: "transparent" });
      hit.addEventListener("pointermove", (evt) => {
        bar.setAttribute("opacity", "0.7");
        showTip(evt, (t) => {
          t.append(el("div", { class: "t-date" }, fmtDate(d.date)));
          tipRow(t, colors[i], s.name, pct(d.pnl_pct, 2));
          tipRow(t, null, "Trades (winning)", `${d.trades} (${d.wins})`);
          tipRow(t, null, "Running sum", pct(d.cum_pct));
        });
      });
      hit.addEventListener("pointerleave", () => { bar.removeAttribute("opacity"); hideTip(); });
      svg.append(bar, hit);
    }
    wrap.append(svg);
    box.append(wrap);
  });
}

// ---------- monthly table (also the accessible view of the numbers) ----------
function months(doc) {
  const tbl = $("months");
  tbl.replaceChildren();
  const all = [...doc.strategies, ...doc.other];
  const keys = [...new Set(all.flatMap((s) => s.months.map((m) => m.month)))].sort();
  const thead = el("thead"), hr = el("tr");
  hr.append(el("th", { scope: "col" }, "Month"));
  doc.strategies.forEach((s) => hr.append(el("th", { scope: "col" }, s.name)));
  thead.append(hr);
  const tbody = el("tbody");
  for (const k of keys) {
    const tr = el("tr");
    tr.append(el("th", { scope: "row" }, fmtMonth(k)));
    for (const s of doc.strategies) {
      const mm = s.months.find((x) => x.month === k), td = el("td");
      if (mm) { td.append(document.createTextNode(pct(mm.pnl_pct)), el("span", { class: "d" }, `${mm.days}d`)); }
      else td.textContent = "–";
      tr.append(td);
    }
    tbody.append(tr);
  }
  const tr = el("tr");
  tr.append(el("th", { scope: "row" }, "Total"));
  for (const s of doc.strategies) {
    const td = el("td");
    td.append(document.createTextNode(pct(s.summary.total_pnl_pct)), el("span", { class: "d" }, `${s.summary.days_traded}d`));
    tr.append(td);
  }
  tbody.append(tr);
  tbl.append(thead, tbody);

  const notes = doc.other.map((o) =>
    `${o.name}: ${o.summary.trades} trades on ${o.summary.days_traded} days, ${fmtDate(o.summary.first_day)} – ` +
    `${fmtDate(o.summary.last_day)}, ${pct(o.summary.total_pnl_pct)}. Not part of the three strategies; shown so every trade is counted.`);
  if (doc.left_out && doc.left_out.paper_or_not_executed) notes.push(`${doc.left_out.paper_or_not_executed} paper trades are excluded.`);
  $("other-note").textContent = notes.join(" ");
}

function render() {
  if (!DOC) return;
  const colors = COLOR_VARS.map(css);
  header(DOC); tiles(DOC, colors); legend(DOC, colors); cumulative(DOC, colors); dailyBars(DOC, colors); months(DOC);
}

fetch("data/track_record.json", { cache: "no-cache" })
  .then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); })
  .then((doc) => { DOC = doc; render(); })
  .catch(() => { $("meta").textContent = "The track record could not be loaded. Please try again later."; });

let resizeTimer;
addEventListener("resize", () => { clearTimeout(resizeTimer); resizeTimer = setTimeout(render, 150); });
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", render);
