// Central theme engine. A theme is a small recipe (hue, primary, secondary, sidebar); buildTokens() turns a
// recipe plus a mode (light/dark) into the full set of CSS variables the stylesheet uses. Every text/background
// pair is contrast-corrected here, so no theme can ship unreadable text. Applying a theme only sets CSS
// variables on <html>, so switching is instant and needs no reload.

// ------------------------------------------------------------ colour maths
const clamp = (n, a = 0, b = 1) => Math.min(b, Math.max(a, n));
export const hexToRgb = (hex) => { const h = hex.replace("#", ""); return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16)); };
export const rgbToHex = (c) => "#" + c.map((v) => Math.round(clamp(v / 255) * 255).toString(16).padStart(2, "0")).join("");
export function toHsl(hex) {
  const [r, g, b] = hexToRgb(hex).map((v) => v / 255);
  const mx = Math.max(r, g, b), mn = Math.min(r, g, b), d = mx - mn, l = (mx + mn) / 2;
  let h = 0, s = 0;
  if (d) {
    s = d / (1 - Math.abs(2 * l - 1));
    h = mx === r ? ((g - b) / d) % 6 : mx === g ? (b - r) / d + 2 : (r - g) / d + 4;
    h = (h * 60 + 360) % 360;
  }
  return [h, s * 100, l * 100];
}
export function hsl(h, s, l) {
  h = ((h % 360) + 360) % 360; s = clamp(s / 100); l = clamp(l / 100);
  const k = (n) => (n + h / 30) % 12, a = s * Math.min(l, 1 - l);
  const f = (n) => l - a * Math.max(-1, Math.min(k(n) - 3, Math.min(9 - k(n), 1)));
  return rgbToHex([f(0) * 255, f(8) * 255, f(4) * 255]);
}
export const mix = (a, b, t) => { const x = hexToRgb(a), y = hexToRgb(b); return rgbToHex(x.map((v, i) => v + (y[i] - v) * t)); };
export function luminance(hex) {
  const [r, g, b] = hexToRgb(hex).map((v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}
export const contrast = (a, b) => { const x = luminance(a), y = luminance(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };
// Move fg's lightness away from bg until the contrast ratio is met (keeps the hue).
export function ensure(fg, bg, ratio = 4.5) {
  if (contrast(fg, bg) >= ratio) return fg;
  const [h, s, l] = toHsl(fg), darker = luminance(bg) > 0.35;
  for (let i = 1; i <= 50; i++) {
    const c = hsl(h, s, darker ? l - i * 2 : l + i * 2);
    if (contrast(c, bg) >= ratio) return c;
  }
  return darker ? "#000000" : "#ffffff";
}
const rgbCsv = (hex) => hexToRgb(hex).join(", ");

// ------------------------------------------------------------ theme recipes
// h/ns: hue and saturation of the neutral greys; a: primary [light, dark]; b: secondary [light, dark];
// sb: sidebar colour [light, dark]; grad3: optional third gradient stop; dbg: dark background lightness.
export const THEMES = [
  { id: "blue", name: "Blue", tag: "Clean, modern and professional", h: 220, ns: 30, a: ["#2563eb", "#5b9bff"], b: ["#06b6d4", "#38d0e8"], sb: ["#0b1f4d", "#07122e"] },
  { id: "red", name: "Red", tag: "Bold, powerful and energetic", h: 0, ns: 16, a: ["#dc2626", "#ff6b6b"], b: ["#f97316", "#ff9d5c"], sb: ["#3b0a10", "#1c0709"] },
  { id: "yellow", name: "Yellow", tag: "Bright, fresh and lively", h: 45, ns: 28, a: ["#f5b800", "#ffd23f"], b: ["#ea580c", "#fb923c"], sb: ["#2b2306", "#17130a"] },
  { id: "black", name: "Black", tag: "Premium, elegant and sophisticated", h: 240, ns: 4, a: ["#18181b", "#f4f4f5"], b: ["#d4a017", "#f5c542"], sb: ["#09090b", "#000000"], dbg: 3.5 },
  { id: "white", name: "White", tag: "Minimal, clean and simple", h: 215, ns: 12, a: ["#334155", "#cbd5e1"], b: ["#64748b", "#94a3b8"], sb: ["#ffffff", "#111418"] },
  { id: "green", name: "Green", tag: "Fresh, calm and natural", h: 150, ns: 20, a: ["#059669", "#34d399"], b: ["#65a30d", "#a3e635"], sb: ["#052e22", "#03140f"] },
  { id: "orange", name: "Orange", tag: "Vibrant, creative and youthful", h: 25, ns: 24, a: ["#ea580c", "#ff8a4c"], b: ["#f59e0b", "#fbbf24"], sb: ["#3a1405", "#1a0b04"] },
  { id: "purple", name: "Purple", tag: "Stylish, creative and luxurious", h: 270, ns: 26, a: ["#7c3aed", "#a78bfa"], b: ["#c026d3", "#e879f9"], sb: ["#25104a", "#130a28"] },
  { id: "pink", name: "Pink", tag: "Modern, playful and attractive", h: 330, ns: 26, a: ["#db2777", "#f472b6"], b: ["#a855f7", "#c084fc"], sb: ["#4a0d2c", "#240617"] },
  { id: "rainbow", name: "Rainbow", tag: "Every colour, still easy to read", h: 250, ns: 22, a: ["#5b3fd9", "#9a85ff"], b: ["#e11d8a", "#f472b6"], sb: ["#1a1240", "#0d0924"], rainbow: true },
  { id: "cyan", name: "Cyan", tag: "Fresh and futuristic", h: 190, ns: 24, a: ["#0891b2", "#22d3ee"], b: ["#3b82f6", "#60a5fa"], sb: ["#06303b", "#041a21"] },
  { id: "teal", name: "Teal", tag: "Elegant and professional", h: 175, ns: 20, a: ["#0d9488", "#2dd4bf"], b: ["#0ea5e9", "#38bdf8"], sb: ["#0a2f2c", "#051a18"] },
  { id: "midnight", name: "Midnight", tag: "Deep navy with modern blue accents", h: 228, ns: 38, a: ["#3b6cf6", "#6c8cff"], b: ["#8b5cf6", "#a78bfa"], sb: ["#070d24", "#04081a"], dbg: 5.5 },
  { id: "sunset", name: "Sunset", tag: "Orange, pink and purple", h: 15, ns: 24, a: ["#f97316", "#ff9a52"], b: ["#ec4899", "#f472b6"], sb: ["#3b1030", "#1d0818"], grad3: ["#8b5cf6", "#a78bfa"] },
  { id: "ocean", name: "Ocean", tag: "Shades of blue and turquoise", h: 200, ns: 30, a: ["#0284c7", "#38bdf8"], b: ["#14b8a6", "#2dd4bf"], sb: ["#06304d", "#031b2d"] },
  { id: "neon", name: "Neon", tag: "Electric colours with a soft glow", h: 265, ns: 30, a: ["#00c76a", "#39ff9c"], b: ["#ff2bd6", "#ff5ce6"], sb: ["#0b0b1a", "#05050d"], neon: true, dbg: 4.5 },
  { id: "gradient", name: "Gradient", tag: "Violet, blue and cyan blended", h: 250, ns: 26, a: ["#6d28d9", "#a78bfa"], b: ["#0ea5e9", "#22d3ee"], sb: ["#1b1450", "#0d0a2c"], grad3: ["#2563eb", "#60a5fa"] },
  { id: "lavender", name: "Lavender", tag: "Soft, calm and creative", h: 260, ns: 28, a: ["#7e6bd6", "#b4a7f5"], b: ["#3b82f6", "#93c5fd"], sb: ["#2a2150", "#171230"] },
  { id: "forest", name: "Forest", tag: "Deep green with a golden accent", h: 140, ns: 18, a: ["#166534", "#4ade80"], b: ["#ca8a04", "#facc15"], sb: ["#0b2a16", "#06150b"] },
  { id: "rose", name: "Rose Gold", tag: "Warm, refined and elegant", h: 355, ns: 18, a: ["#b76e79", "#e0a3ab"], b: ["#d4a373", "#e9c9a0"], sb: ["#3a2226", "#1d1113"] },
  { id: "custom", name: "Custom", tag: "Build your own colour combination", h: 220, ns: 30, a: ["#2563eb", "#5b9bff"], b: ["#06b6d4", "#38d0e8"], sb: ["#0b1f4d", "#07122e"], custom: true },
];
export const THEME_IDS = THEMES.map((t) => t.id);
export const DEFAULT_CUSTOM = { primary: "#7c3aed", secondary: "#06b6d4", background: "#f5f3ff", accent: "#f59e0b" };
export const DEFAULT_PREFS = { theme: "blue", mode: "system", rainbow: false, custom: null };
const RAINBOW = ["#ff3b3b", "#ff9a1f", "#ffd92b", "#2fd36b", "#2f7bff", "#4b3fe0", "#9b4dff"];
const RAINBOW_DEEP = ["#d7263d", "#c2410c", "#a16207", "#15803d", "#1d4ed8", "#4338ca", "#7e22ce"];

// ------------------------------------------------------------ token builder
function recipeFor(id, custom) {
  const t = THEMES.find((x) => x.id === id) || THEMES[0];
  if (!t.custom) return t;
  const c = { ...DEFAULT_CUSTOM, ...(custom || {}) };
  const [bh, bs] = toHsl(c.background);
  return { ...t, h: bh, ns: clamp(bs, 4, 40), a: [c.primary, mix(c.primary, "#ffffff", 0.3)], b: [c.secondary, mix(c.secondary, "#ffffff", 0.25)],
    sb: [hsl(toHsl(c.primary)[0], 45, 14), hsl(toHsl(c.primary)[0], 40, 7)], hi: c.accent, bgExact: c.background };
}

export function buildTokens(prefs, mode) {
  const p = { ...DEFAULT_PREFS, ...prefs };
  const dark = mode === "dark";
  const t = recipeFor(p.theme, p.custom);
  const rainbow = !!p.rainbow || !!t.rainbow;
  const h = t.h, ns = t.ns;
  // neutrals
  let n;
  if (!dark) n = { bg: hsl(h, ns, 96.5), surface: "#ffffff", s2: hsl(h, ns, 98.3), s3: hsl(h, ns, 94), border: hsl(h, ns * 0.9, 89), strong: hsl(h, ns * 0.8, 79), ink: hsl(h, Math.min(ns + 10, 40), 12), ink2: hsl(h, ns * 0.8, 30) };
  else { const d = t.dbg ?? 7; n = { bg: hsl(h, ns, d), surface: hsl(h, ns, d + 3.5), s2: hsl(h, ns, d + 5.5), s3: hsl(h, ns, d + 9), border: hsl(h, ns, d + 13), strong: hsl(h, ns, d + 22), ink: hsl(h, ns, 95), ink2: hsl(h, ns * 0.8, 78) }; }
  if (t.bgExact) {
    const L = toHsl(t.bgExact)[2];
    if ((!dark && L >= 85) || (dark && L <= 22)) n.bg = t.bgExact;
  }
  n.muted = ensure(dark ? hsl(h, ns * 0.6, 64) : hsl(h, ns * 0.55, 40), n.s3, 4.6);
  n.ink = ensure(n.ink, n.s3, 12); n.ink2 = ensure(n.ink2, n.s3, 7);
  const tint = (c) => mix(n.surface, c, dark ? 0.2 : 0.11); // hover / selected backgrounds
  // accent family
  const A0 = dark ? t.a[1] : t.a[0], B0 = dark ? t.b[1] : t.b[0], C0 = t.grad3 ? (dark ? t.grad3[1] : t.grad3[0]) : null;
  let stops = [A0, B0, C0].filter(Boolean);
  const text = contrast(A0, "#ffffff") >= 4.5 ? "#ffffff" : "#0b0f1a"; // judged on the primary colour
  // The text colour must be readable on every stop of the fill gradient.
  const fill = stops.map((c) => ensure(c, text, 4.5));
  const accent = fill[0];
  const soft = tint;
  const hover = [soft(A0), soft(B0)];
  for (const bg of hover) { n.muted = ensure(n.muted, bg, 4.6); n.ink2 = ensure(n.ink2, bg, 4.6); }
  // Text accents must stay readable on the surface, on tinted surfaces and on their own soft tint.
  const readable = (c) => ensure(ensure(ensure(c, n.surface, 4.7), n.s3, 4.7), soft(c), 4.7);
  const accent2 = readable(A0); // links / text accents
  const hi = t.hi ? (dark ? mix(t.hi, "#ffffff", 0.2) : t.hi) : B0;
  const hiText = readable(hi);
  // sidebar
  const S = dark ? t.sb[1] : t.sb[0], lightSb = luminance(S) > 0.5;
  const sbInk = lightSb ? hsl(h, ns, 16) : mix("#eef3ff", S, 0.06), sbMuted = ensure(mix(sbInk, S, 0.42), S, 4.6);
  const navy2 = mix(S, A0, lightSb ? 0.05 : 0.2);
  // hero (welcome + auth panels): always dark enough for white text
  const H = luminance(S) > 0.2 ? mix(A0, "#000000", 0.5) : S;
  const hero = [ensure(H, "#ffffff", 8), ensure(mix(H, A0, 0.38), "#ffffff", 7), ensure(mix(H, B0, 0.5), "#ffffff", 6)];
  // chart series
  const surface = n.surface;
  const base = dark ? ["#4ade80", "#fbbf24", "#f87171", "#a78bfa", "#22d3ee", "#f472b6"] : ["#16a34a", "#d97706", "#dc2626", "#7c3aed", "#0891b2", "#db2777"];
  const hueGap = (x, y) => { const d = Math.abs(toHsl(x)[0] - toHsl(y)[0]); return Math.min(d, 360 - d); };
  let series;
  if (rainbow) series = (dark ? RAINBOW : RAINBOW_DEEP.map((c, i) => (i === 2 ? "#ca8a04" : c))).concat(dark ? "#f472b6" : "#db2777");
  else {
    const s1 = ensure(A0, surface, 3), s2 = ensure(B0, surface, 3);
    const rest = base.filter((c) => hueGap(c, s1) > 22 && hueGap(c, s2) > 22);
    series = [s1, s2, ...rest, ...base].slice(0, 8);
  }
  series = series.map((c) => ensure(c, surface, 3));
  const shadowRgb = dark ? "0, 0, 0" : rgbCsv(mix(n.ink, "#000000", 0.2));
  const paperAccent = ensure(A0, "#ffffff", 4.6), paperHead = ensure(mix(A0, "#0b1220", 0.55), "#ffffff", 7);

  // Status colours (success / warning / error) keep their meaning in every theme but are made readable on every surface.
  const sem = (ink, softBg) => { const sf = dark ? softBg[1] : softBg[0]; return [ensure(ensure(ink, sf, 5), n.surface, 5), sf]; };
  const [goodInk, goodSoft] = sem(dark ? "#5fd35f" : "#006300", ["#e5f6e5", "#123420"]);
  const [warnInk, warnSoft] = sem(dark ? "#f5c75a" : "#7a5200", ["#fff4dc", "#3a2e0e"]);
  const [critInk, critSoft] = sem(dark ? "#ff8f8f" : "#a52626", ["#fdeaea", "#3d1a1d"]);
  const v = {
    "--good-ink": goodInk, "--good-soft": goodSoft, "--warn-ink": warnInk, "--warn-soft": warnSoft, "--crit-ink": critInk, "--crit-soft": critSoft,
    "--bg": n.bg, "--surface": n.surface, "--surface-2": n.s2, "--surface-3": n.s3,
    "--border": n.border, "--border-strong": n.strong, "--ink": n.ink, "--ink-2": n.ink2, "--muted": n.muted,
    "--navy": S, "--navy-2": navy2, "--navy-ink": sbInk, "--navy-muted": sbMuted, "--navy-title": lightSb ? n.ink : "#ffffff",
    "--sb-border": lightSb ? n.border : "rgba(255, 255, 255, .08)", "--sb-hover": lightSb ? "rgba(15, 23, 42, .06)" : "rgba(255, 255, 255, .09)",
    "--accent": accent, "--accent-2": accent2, "--accent-soft": soft(A0), "--on-accent": text, "--accent-rgb": rgbCsv(accent),
    "--hi": hiText, "--hi-fill": fill[1] || accent, "--hi-soft": soft(hi), "--hi-rgb": rgbCsv(hi),
    "--info-soft": soft(A0), "--info-ink": accent2,
    "--purple": fill[1] || accent, "--purple-2": hiText, "--purple-soft": soft(hi), "--purple-ink": hiText,
    "--teal": accent, "--teal-2": accent2, "--teal-soft": soft(A0), "--teal-ink": accent2,
    "--grad": `linear-gradient(135deg, ${fill.join(", ")})`,
    "--grad-primary": `linear-gradient(135deg, ${fill.join(", ")})`,
    "--grad-hero": `linear-gradient(155deg, ${hero[0]} 0%, ${hero[1]} 58%, ${hero[2]} 100%)`,
    "--grad-card": n.surface,
    "--grad-soft": `linear-gradient(135deg, ${soft(A0)}, ${soft(hi)})`,
    "--crit-badge": dark ? "#b91c1c" : "#c81e1e",
    "--shadow": `0 1px 2px rgba(${shadowRgb}, ${dark ? 0.4 : 0.06}), 0 6px 18px rgba(${shadowRgb}, ${dark ? 0.3 : 0.07})`,
    "--shadow-lg": `0 18px 50px rgba(${shadowRgb}, ${dark ? 0.6 : 0.24})`,
    "--grid": n.border, "--axis": n.strong, "--chart-muted": n.muted,
    "--paper-accent": paperAccent, "--paper-head": paperHead,
    "--glow-strength": t.neon ? (dark ? "58%" : "40%") : dark ? "34%" : "30%",
  };
  series.forEach((c, i) => { v[`--s${i + 1}`] = c; });
  return { vars: v, dark, rainbow, neon: !!t.neon, fill, text, n, accent2, sidebar: S, sbInk, sbMuted, hero, paperHead, series, hiText };
}

// ------------------------------------------------------------ accessibility audit (used by tests)
export function audit(prefs, mode) {
  const k = buildTokens(prefs, mode), v = k.vars, bad = [];
  const need = (name, fg, bg, ratio) => { const c = contrast(fg, bg); if (c < ratio) bad.push(`${name} ${c.toFixed(2)} < ${ratio}`); };
  for (const bg of ["--bg", "--surface", "--surface-2", "--surface-3"]) {
    need(`ink on ${bg}`, v["--ink"], v[bg], 7); need(`ink-2 on ${bg}`, v["--ink-2"], v[bg], 4.5);
    need(`muted on ${bg}`, v["--muted"], v[bg], 4.5); need(`link on ${bg}`, v["--accent-2"], v[bg], 4.5);
    need(`highlight text on ${bg}`, v["--hi"], v[bg], 4.5);
  }
  for (const c of k.fill) need(`on-accent on fill ${c}`, v["--on-accent"], c, 4.5);
  for (const [i, sf] of [["--good-ink", "--good-soft"], ["--warn-ink", "--warn-soft"], ["--crit-ink", "--crit-soft"]]) { need(`${i} on soft`, v[i], v[sf], 4.5); need(`${i} on surface`, v[i], v["--surface"], 4.5); }
  need("accent-soft text", v["--accent-2"], v["--accent-soft"], 4.5);
  for (const bg of ["--accent-soft", "--hi-soft"]) { need(`muted on ${bg}`, v["--muted"], v[bg], 4.5); need(`ink-2 on ${bg}`, v["--ink-2"], v[bg], 4.5); need(`ink on ${bg}`, v["--ink"], v[bg], 7); }
  need("sidebar text", v["--navy-ink"], v["--navy"], 4.5); need("sidebar muted", v["--navy-muted"], v["--navy"], 4.5);
  need("sidebar text (2)", v["--navy-ink"], v["--navy-2"], 4.5);
  need("sidebar active", v["--on-accent"], k.fill[0], 4.5);
  for (const c of k.hero) need(`white on hero ${c}`, "#ffffff", c, 4.5);
  need("report header", "#ffffff", v["--paper-head"], 4.5);
  k.series.forEach((c, i) => need(`series ${i + 1} on surface`, c, v["--surface"], 3));
  return bad;
}

// ------------------------------------------------------------ applying and saving
const LS_KEY = "sms-appearance";
let applied = [];
let mq = null;
export const systemDark = () => { try { return matchMedia("(prefers-color-scheme: dark)").matches; } catch { return false; } };
export const resolveMode = (mode) => (mode === "dark" || (mode === "system" && systemDark()) ? "dark" : "light");

export function normalize(p) {
  const o = { ...DEFAULT_PREFS, ...(p && typeof p === "object" ? p : {}) };
  if (!THEME_IDS.includes(o.theme)) o.theme = DEFAULT_PREFS.theme;
  if (!["light", "dark", "system"].includes(o.mode)) o.mode = "system";
  o.rainbow = o.rainbow === true;
  const ok = o.custom && typeof o.custom === "object" && ["primary", "secondary", "background", "accent"].every((k) => /^#[0-9a-f]{6}$/i.test(o.custom[k] || ""));
  o.custom = ok ? { ...o.custom } : null;
  return o;
}

let current = { ...DEFAULT_PREFS };
export const getPrefs = () => ({ ...current, custom: current.custom ? { ...current.custom } : null });

export function applyPrefs(p) {
  current = normalize(p);
  const mode = resolveMode(current.mode), k = buildTokens(current, mode), root = document.documentElement;
  for (const name of applied) root.style.removeProperty(name);
  applied = Object.keys(k.vars);
  for (const [name, val] of Object.entries(k.vars)) root.style.setProperty(name, val);
  root.setAttribute("data-theme", mode);
  root.setAttribute("data-palette", current.theme);
  root.setAttribute("data-rainbow", k.rainbow ? "on" : "off");
  root.setAttribute("data-neon", k.neon ? "on" : "off");
  root.style.colorScheme = mode;
  const meta = document.querySelector('meta[name="theme-color"]'); if (meta) meta.setAttribute("content", k.sidebar);
  if (!mq && typeof matchMedia === "function") {
    mq = matchMedia("(prefers-color-scheme: dark)");
    mq.addEventListener?.("change", () => { if (current.mode === "system") applyPrefs(current); });
  }
  return k;
}

export function loadLocal() {
  try {
    const raw = localStorage.getItem(LS_KEY);
    if (raw) return normalize(JSON.parse(raw));
    const legacy = localStorage.getItem("sms-theme"); // earlier releases stored only light/dark
    if (legacy === "light" || legacy === "dark") return normalize({ mode: legacy });
  } catch { /* storage unavailable */ }
  return null;
}
export function saveLocal(p) { try { localStorage.setItem(LS_KEY, JSON.stringify(normalize(p))); } catch { /* ignore */ } }
export const isDark = () => document.documentElement.getAttribute("data-theme") === "dark";
