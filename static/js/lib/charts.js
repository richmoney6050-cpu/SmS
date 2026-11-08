// Small dependency-free SVG chart library. Colours come from CSS variables so light/dark themes both work.
// Rules: one y-axis, thin marks, legend whenever there are 2+ series, hover tooltips, and a hidden data table.
import { h } from "./ui.js";

const NS = "http://www.w3.org/2000/svg";
const s = (tag, attrs = {}, ...kids) => {
  const n = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) if (v !== null && v !== undefined) n.setAttribute(k, v);
  for (const k of kids.flat()) if (k) n.append(k);
  return n;
};
const colorOf = (series, i) => series.color || `var(--s${(i % 8) + 1})`;

function niceMax(v) {
  if (!(v > 0)) return 1;
  const pow = 10 ** Math.floor(Math.log10(v));
  for (const m of [1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10]) if (v <= m * pow) return m * pow;
  return 10 * pow;
}
function ticks(max, n = 4) { return Array.from({ length: n + 1 }, (_, i) => (max / n) * i); }
const trunc = (t, n) => (String(t).length > n ? String(t).slice(0, Math.max(1, n - 1)) + "…" : String(t));

function shell(opts, draw) {
  const root = h("div", { class: "chart-wrap" });
  const legend = (opts.series || []).length >= 2 ? h("div", { class: "legend" }, opts.series.map((se, i) => h("span", null, h("i", { style: { background: colorOf(se, i) } }), se.name))) : null;
  const holder = h("div", { class: "chart" });
  const tip = h("div", { class: "chart-tip", style: { display: "none" } });
  holder.append(tip);
  // Hidden table so the same numbers are available to assistive technology.
  const fmt = opts.format || ((v) => v);
  const table = h("table", { class: "sr-only" }, h("caption", null, opts.title || "Chart data"),
    h("thead", null, h("tr", null, h("th", null, opts.categoryLabel || "Category"), (opts.series || []).map((se) => h("th", null, se.name)))),
    h("tbody", null, (opts.labels || []).map((l, i) => h("tr", null, h("td", null, l), (opts.series || []).map((se) => h("td", null, se.values[i] === null || se.values[i] === undefined ? "no data" : fmt(se.values[i])))))));
  root.append(...[legend, holder, table].filter(Boolean));
  let svg, last = 0;
  const render = () => {
    const w = Math.max(240, Math.floor(holder.clientWidth || root.clientWidth || 600));
    if (w === last && svg) return;
    last = w;
    svg?.remove();
    svg = draw(w, tip, holder);
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", opts.title || "Chart");
    holder.prepend(svg);
  };
  const showTip = (x, y, title, rows) => {
    tip.replaceChildren(h("b", null, title), ...rows.map((r) => h("div", { class: "r" }, h("span", null, r.color ? h("i", { style: { background: r.color } }) : null, r.name), h("b", { style: { margin: 0 } }, r.value))));
    tip.style.display = "block";
    const hw = holder.clientWidth;
    tip.style.left = Math.min(Math.max(x, 70), hw - 70) + "px";
    tip.style.top = Math.max(y, 54) + "px";
  };
  const hideTip = () => { tip.style.display = "none"; };
  root.tipApi = { showTip, hideTip };
  // Draw after attachment so widths are real; re-draw on resize.
  requestAnimationFrame(() => {
    render();
    if (typeof ResizeObserver !== "undefined") {
      let t; new ResizeObserver(() => { clearTimeout(t); t = setTimeout(() => { if (root.isConnected) render(); }, 80); }).observe(holder);
    }
  });
  return { root, showTip, hideTip, tip };
}

/** Vertical grouped bars. opts: {labels, series:[{name, values, color}], max, format, height, threshold, title} */
export function barChart(opts) {
  const fmt = opts.format || ((v) => v);
  if (!opts.labels?.length || opts.series.every((se) => se.values.every((v) => v === null || v === undefined))) return h("div", { class: "chart-empty" }, opts.emptyText || "No data to chart yet.");
  const ctrl = shell(opts, (W, tip, holder) => {
    const H = opts.height || 260, m = { l: 44, r: 10, t: 16, b: 34 };
    const iw = W - m.l - m.r, ih = H - m.t - m.b;
    const vals = opts.series.flatMap((se) => se.values.filter((v) => v !== null && v !== undefined));
    const max = opts.max || niceMax(Math.max(...vals, 0));
    const y = (v) => m.t + ih - (v / max) * ih;
    const n = opts.labels.length, band = iw / n, k = opts.series.length;
    const gw = Math.min(band * 0.72, 56 * k), bw = Math.max(4, (gw - (k - 1) * 2) / k);
    const g = s("g");
    ticks(max).forEach((t) => g.append(s("g", { class: "grid" }, s("line", { x1: m.l, x2: W - m.r, y1: y(t), y2: y(t) })), s("text", { x: m.l - 8, y: y(t) + 4, "text-anchor": "end" }, fmt(Math.round(t * 10) / 10))));
    g.append(s("line", { class: "axis", x1: m.l, x2: W - m.r, y1: y(0), y2: y(0) }));
    if (opts.threshold !== undefined) g.append(s("line", { x1: m.l, x2: W - m.r, y1: y(opts.threshold), y2: y(opts.threshold), stroke: "var(--crit)", "stroke-width": 1.5, "stroke-dasharray": "5 4" }), s("text", { x: W - m.r, y: y(opts.threshold) - 5, "text-anchor": "end", style: "fill:var(--crit-ink)" }, opts.thresholdLabel || `Threshold ${fmt(opts.threshold)}`));
    const maxChars = Math.floor(band / 6.5);
    opts.labels.forEach((lab, i) => {
      const cx = m.l + band * i + band / 2, x0 = cx - gw / 2;
      opts.series.forEach((se, si) => {
        const v = se.values[i]; if (v === null || v === undefined) return;
        const x = x0 + si * (bw + 2), top = y(v), hgt = Math.max(0, y(0) - top), r = Math.min(4, bw / 2, hgt);
        g.append(s("path", { d: `M${x},${y(0)} V${top + r} Q${x},${top} ${x + r},${top} H${x + bw - r} Q${x + bw},${top} ${x + bw},${top + r} V${y(0)} Z`, fill: colorOf(se, si) }));
        if (k === 1 && n <= 14 && bw > 14) g.append(s("text", { class: "val", x: x + bw / 2, y: top - 5, "text-anchor": "middle" }, fmt(v)));
      });
      g.append(s("text", { x: cx, y: H - m.b + 16, "text-anchor": "middle" }, trunc(lab, Math.max(4, maxChars))));
      const hit = s("rect", { class: "hit", x: m.l + band * i, y: m.t, width: band, height: ih + 4 });
      hit.addEventListener("mousemove", () => ctrl.showTip(cx, y(Math.max(...opts.series.map((se) => se.values[i] ?? 0))) - 4, lab, opts.series.map((se, si) => ({ name: se.name, color: colorOf(se, si), value: se.values[i] === null || se.values[i] === undefined ? "no data" : fmt(se.values[i]) }))));
      hit.addEventListener("mouseleave", () => ctrl.hideTip());
      g.append(hit);
    });
    return s("svg", { viewBox: `0 0 ${W} ${H}`, width: W, height: H }, g);
  });
  return ctrl.root;
}

/** Horizontal bars (long labels, rankings). opts like barChart, plus stacked:true for part-of-whole rows. */
export function hbarChart(opts) {
  const fmt = opts.format || ((v) => v);
  if (!opts.labels?.length || opts.series.every((se) => se.values.every((v) => v === null || v === undefined))) return h("div", { class: "chart-empty" }, opts.emptyText || "No data to chart yet.");
  const stacked = !!opts.stacked;
  const ctrl = shell(opts, (W, tip) => {
    const n = opts.labels.length, rowH = opts.rowHeight || (opts.series.length > 1 && !stacked ? 16 * opts.series.length + 14 : 34);
    const labelW = Math.min(150, Math.max(70, W * 0.28));
    const m = { l: labelW, r: 46, t: 6, b: 24 }, H = m.t + m.b + rowH * n, iw = W - m.l - m.r;
    const totals = opts.labels.map((_, i) => opts.series.reduce((a, se) => a + (se.values[i] || 0), 0));
    const max = opts.max || niceMax(stacked ? Math.max(...totals) : Math.max(...opts.series.flatMap((se) => se.values.map((v) => v || 0))));
    const x = (v) => m.l + (v / max) * iw;
    const g = s("g");
    ticks(max).forEach((t) => g.append(s("g", { class: "grid" }, s("line", { x1: x(t), x2: x(t), y1: m.t, y2: H - m.b })), s("text", { x: x(t), y: H - m.b + 15, "text-anchor": "middle" }, fmt(Math.round(t * 10) / 10))));
    opts.labels.forEach((lab, i) => {
      const y0 = m.t + rowH * i, k = opts.series.length;
      g.append(s("text", { x: m.l - 8, y: y0 + rowH / 2 + 4, "text-anchor": "end" }, trunc(lab, Math.floor(labelW / 6.6))));
      if (stacked) {
        let acc = 0;
        opts.series.forEach((se, si) => { const v = se.values[i] || 0; if (v <= 0) return; g.append(s("rect", { x: x(acc) + (acc ? 1 : 0), y: y0 + 8, width: Math.max(0, x(acc + v) - x(acc) - (acc ? 1 : 0)), height: rowH - 16, fill: colorOf(se, si), rx: 3 })); acc += v; });
        g.append(s("text", { class: "val", x: x(acc) + 6, y: y0 + rowH / 2 + 4 }, fmt(acc)));
      } else {
        const bh = Math.min(18, (rowH - 10) / k - 2);
        opts.series.forEach((se, si) => { const v = se.values[i]; if (v === null || v === undefined) return; const yy = y0 + 5 + si * (bh + 2); g.append(s("rect", { x: m.l, y: yy, width: Math.max(2, x(v) - m.l), height: bh, fill: colorOf(se, si), rx: 3 }), s("text", { class: "val", x: x(v) + 6, y: yy + bh / 2 + 4 }, fmt(v))); });
      }
      const hit = s("rect", { class: "hit", x: 0, y: y0, width: W, height: rowH });
      hit.addEventListener("mousemove", () => ctrl.showTip(Math.min(x(stacked ? totals[i] : Math.max(...opts.series.map((se) => se.values[i] || 0))) + 10, W - 80), y0, lab, opts.series.map((se, si) => ({ name: se.name, color: colorOf(se, si), value: se.values[i] === null || se.values[i] === undefined ? "no data" : fmt(se.values[i]) }))));
      hit.addEventListener("mouseleave", () => ctrl.hideTip());
      g.append(hit);
    });
    return s("svg", { viewBox: `0 0 ${W} ${H}`, width: W, height: H }, g);
  });
  return ctrl.root;
}

/** Multi-series line chart with crosshair + tooltip. opts: {labels, series, min, max, format, height} */
export function lineChart(opts) {
  const fmt = opts.format || ((v) => v);
  if (!opts.labels?.length || opts.series.every((se) => se.values.every((v) => v === null || v === undefined))) return h("div", { class: "chart-empty" }, opts.emptyText || "No data to chart yet.");
  const ctrl = shell(opts, (W) => {
    const H = opts.height || 260, m = { l: 44, r: 16, t: 16, b: 34 }, iw = W - m.l - m.r, ih = H - m.t - m.b;
    const vals = opts.series.flatMap((se) => se.values.filter((v) => v !== null && v !== undefined));
    const lo = opts.min !== undefined ? opts.min : Math.min(0, ...vals), hi = opts.max !== undefined ? opts.max : niceMax(Math.max(...vals));
    const n = opts.labels.length, x = (i) => m.l + (n === 1 ? iw / 2 : (iw * i) / (n - 1)), y = (v) => m.t + ih - ((v - lo) / (hi - lo || 1)) * ih;
    const g = s("g");
    ticks(hi - lo).forEach((t) => g.append(s("g", { class: "grid" }, s("line", { x1: m.l, x2: W - m.r, y1: y(lo + t), y2: y(lo + t) })), s("text", { x: m.l - 8, y: y(lo + t) + 4, "text-anchor": "end" }, fmt(Math.round((lo + t) * 10) / 10))));
    const step = Math.ceil(n / Math.max(2, Math.floor(iw / 70)));
    opts.labels.forEach((lab, i) => { if (i % step === 0 || i === n - 1) g.append(s("text", { x: x(i), y: H - m.b + 17, "text-anchor": i === 0 && n > 1 ? "start" : i === n - 1 && n > 1 ? "end" : "middle" }, trunc(lab, 12))); });
    opts.series.forEach((se, si) => {
      let d = "", pen = false;
      se.values.forEach((v, i) => { if (v === null || v === undefined) { pen = false; return; } d += `${pen ? "L" : "M"}${x(i)},${y(v)} `; pen = true; });
      g.append(s("path", { d, fill: "none", stroke: colorOf(se, si), "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round" }));
      if (n <= 20) se.values.forEach((v, i) => { if (v !== null && v !== undefined) g.append(s("circle", { cx: x(i), cy: y(v), r: 4, fill: colorOf(se, si), stroke: "var(--surface)", "stroke-width": 2 })); });
    });
    const cursor = s("line", { class: "cursor", y1: m.t, y2: m.t + ih, style: "display:none" });
    g.append(cursor);
    const hit = s("rect", { class: "hit", x: m.l - 6, y: m.t, width: iw + 12, height: ih });
    const move = (e) => {
      const r = hit.getBoundingClientRect(), px = ((e.clientX ?? e.touches?.[0]?.clientX) - r.left) / r.width * (iw + 12) - 6;
      const i = Math.max(0, Math.min(n - 1, Math.round((px / iw) * (n - 1))));
      cursor.setAttribute("x1", x(i)); cursor.setAttribute("x2", x(i)); cursor.style.display = "";
      const top = Math.min(...opts.series.map((se) => (se.values[i] === null || se.values[i] === undefined ? ih : y(se.values[i]))));
      ctrl.showTip(x(i), top - 8, opts.labels[i], opts.series.map((se, si) => ({ name: se.name, color: colorOf(se, si), value: se.values[i] === null || se.values[i] === undefined ? "no data" : fmt(se.values[i]) })));
    };
    hit.addEventListener("mousemove", move); hit.addEventListener("touchmove", move, { passive: true }); hit.addEventListener("touchstart", move, { passive: true });
    hit.addEventListener("mouseleave", () => { cursor.style.display = "none"; ctrl.hideTip(); });
    g.append(hit);
    return s("svg", { viewBox: `0 0 ${W} ${H}`, width: W, height: H }, g);
  });
  return ctrl.root;
}
