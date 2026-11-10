// UI helpers. All DOM is built with textContent / attributes, never innerHTML, so user data cannot inject markup.
import { ApiError } from "./api.js";

const SVG_NS = "http://www.w3.org/2000/svg";

/** h("div", {class:"x", onclick: fn, "aria-label": "y"}, "text", node, [children]) */
export function h(tag, props, ...kids) {
  const node = document.createElement(tag);
  if (props) {
    for (const [k, v] of Object.entries(props)) {
      if (v === null || v === undefined || v === false) continue;
      if (k === "class") node.className = v;
      else if (k === "dataset") Object.assign(node.dataset, v);
      else if (k === "style" && typeof v === "object") Object.assign(node.style, v);
      else if (k.startsWith("on") && typeof v === "function") node.addEventListener(k.slice(2).toLowerCase(), v);
      else if (k === "value") node.value = v;
      else if (k === "checked" || k === "disabled" || k === "selected" || k === "readOnly" || k === "required" || k === "multiple") node[k] = !!v;
      else node.setAttribute(k, v === true ? "" : v);
    }
  }
  append(node, kids);
  return node;
}
export function append(node, kids) {
  for (const k of kids.flat(Infinity)) {
    if (k === null || k === undefined || k === false) continue;
    node.append(k instanceof Node ? k : document.createTextNode(String(k)));
  }
  return node;
}
export const clear = (node) => { while (node.firstChild) node.removeChild(node.firstChild); return node; };
export const mount = (node, ...kids) => append(clear(node), kids);

// ------------------------------------------------------------ icons (simple stroke shapes)
const ICONS = {
  dashboard: '<rect x="3" y="3" width="7" height="9" rx="1"/><rect x="14" y="3" width="7" height="5" rx="1"/><rect x="14" y="12" width="7" height="9" rx="1"/><rect x="3" y="16" width="7" height="5" rx="1"/>',
  users: '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20c0-3.6 2.9-6 6.5-6s6.5 2.4 6.5 6"/><path d="M16 4.6a3.5 3.5 0 010 6.8M18 14.4c2.2.6 3.5 2.6 3.5 5.6"/>',
  user: '<circle cx="12" cy="8" r="4"/><path d="M4 21c0-4 3.6-7 8-7s8 3 8 7"/>',
  calendar: '<rect x="3" y="4.5" width="18" height="16" rx="2"/><path d="M3 9.5h18M8 2.5v4M16 2.5v4"/><path d="M9 15l2 2 4-4"/>',
  exam: '<path d="M6 3h9l4 4v14H6z"/><path d="M14 3v5h5M9 13h7M9 17h5"/>',
  chart: '<path d="M4 20V4M4 20h16"/><rect x="7.5" y="11" width="3" height="6" rx=".5"/><rect x="12.5" y="7" width="3" height="10" rx=".5"/><rect x="17" y="13" width="2.5" height="4" rx=".5"/>',
  search: '<circle cx="11" cy="11" r="6.5"/><path d="M20 20l-4.2-4.2"/>',
  plus: '<path d="M12 5v14M5 12h14"/>', edit: '<path d="M4 20h4L19 9l-4-4L4 16z"/><path d="M13.5 6.5l4 4"/>',
  trash: '<path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13M10 11v6M14 11v6"/>', x: '<path d="M6 6l12 12M18 6L6 18"/>',
  check: '<path d="M5 12.5l4.5 4.5L19 7.5"/>', alert: '<path d="M12 3.5l9.5 16.5h-19z"/><path d="M12 10v4.5M12 17.2v.1"/>',
  bell: '<path d="M6 17V11a6 6 0 0112 0v6l1.5 2h-15z"/><path d="M10 21h4"/>', sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2.5v2.5M12 19v2.5M2.5 12H5M19 12h2.5M5.3 5.3l1.8 1.8M16.9 16.9l1.8 1.8M5.3 18.7l1.8-1.8M16.9 7.1l1.8-1.8"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
  moon: '<path d="M20 14.5A8.5 8.5 0 019.5 4 8.5 8.5 0 1020 14.5z"/>', menu: '<path d="M4 6.5h16M4 12h16M4 17.5h16"/>',
  chevron: '<path d="M6 9l6 6 6-6"/>', chevronRight: '<path d="M9 6l6 6-6 6"/>', chevronLeft: '<path d="M15 6l-6 6 6 6"/>',
  logout: '<path d="M10 4H5v16h5M15 8l4 4-4 4M19 12H9"/>', settings: '<circle cx="12" cy="12" r="3"/><path d="M12 2.5v3M12 18.5v3M2.5 12h3M18.5 12h3M5.3 5.3l2.1 2.1M16.6 16.6l2.1 2.1M5.3 18.7l2.1-2.1M16.6 7.4l2.1-2.1"/>',
  shield: '<path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z"/><path d="M9 12l2 2 4-4"/>', eye: '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
  download: '<path d="M12 4v11M7 11l5 5 5-5M5 20h14"/>', printer: '<path d="M7 9V4h10v5M7 17H4v-6h16v6h-3"/><rect x="7" y="14" width="10" height="6"/>',
  refresh: '<path d="M20 11a8 8 0 00-14.5-4M4 4v4h4M4 13a8 8 0 0014.5 4M20 20v-4h-4"/>', info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5.5M12 7.8v.1"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3.5 2"/>', school: '<path d="M2.5 9.5L12 4l9.5 5.5L12 15z"/><path d="M6 12v5c0 1.5 3 3 6 3s6-1.5 6-3v-5M21.5 9.5V16"/>',
  filter: '<path d="M3 5h18l-7 8.5V20l-4-2v-4.5z"/>', up: '<path d="M12 19V5M6 11l6-6 6 6"/>', down: '<path d="M12 5v14M6 13l6 6 6-6"/>',
  file: '<path d="M6 3h9l4 4v14H6z"/><path d="M14 3v5h5"/>', key: '<circle cx="8" cy="15" r="4"/><path d="M11 12l9-9M16 6l3 3"/>', book: '<path d="M4 4.5A2.5 2.5 0 016.5 2H20v17H6.5A2.5 2.5 0 004 21.5z"/><path d="M4 21.5V4.5"/>',
  database: '<ellipse cx="12" cy="6" rx="8" ry="3"/><path d="M4 6v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3"/>',
  camera: '<path d="M4 8h3l2-3h6l2 3h3v12H4z"/><circle cx="12" cy="13.5" r="3.5"/>', upload: '<path d="M12 16V5M7 9l5-5 5 5M5 20h14"/>',
  copy: '<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V5a1 1 0 00-1-1H5a1 1 0 00-1 1v10a1 1 0 001 1h3"/>',
  swap: '<path d="M4 8h14M14 4l4 4-4 4M20 16H6M10 12l-4 4 4 4"/>', list: '<path d="M8 6h12M8 12h12M8 18h12M3.5 6h.1M3.5 12h.1M3.5 18h.1"/>', login: '<path d="M14 4h5v16h-5M9 8l-4 4 4 4M5 12h10"/>',
};
export function icon(name, extra = "") {
  const s = document.createElementNS(SVG_NS, "svg");
  s.setAttribute("viewBox", "0 0 24 24"); s.setAttribute("class", "icon " + extra); s.setAttribute("aria-hidden", "true");
  s.innerHTML = ICONS[name] || ICONS.info; // static, trusted icon markup only
  return s;
}

// ------------------------------------------------------------ formatting
let tz = "UTC";
export const setTimezone = (z) => { tz = z || "UTC"; };
export const fmtPct = (v, d = 1) => (v === null || v === undefined ? "-" : `${Number(v).toFixed(d).replace(/\.0+$/, "").replace(/(\.\d*[1-9])0+$/, "$1")}%`);
export const fmtNum = (v) => (v === null || v === undefined ? "-" : Number(v).toLocaleString());
export function fmtDate(iso) {
  if (!iso) return "-";
  const d = new Date(iso.length <= 10 ? iso + "T00:00:00" : iso);
  return d.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric", ...(iso.length > 10 ? { timeZone: tz } : {}) });
}
export function fmtDateTime(iso) {
  if (!iso) return "Never";
  return new Date(iso).toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: tz });
}
export function fmtTime(iso) {
  return iso ? new Date(iso).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", timeZone: tz }) : "-";
}
export function ago(iso) {
  if (!iso) return "never";
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  if (s < 86400 * 7) return `${Math.floor(s / 86400)} d ago`;
  return fmtDate(iso.slice(0, 10));
}
export const cap = (s) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : "");
export const initials = (name) => (name || "?").replace(/\(.*?\)/g, "").trim().split(/\s+/).filter((w) => !/^(mr|mrs|ms|dr|prof)\.?$/i.test(w)).slice(0, 2).map((w) => w[0]).join("").toUpperCase() || "?";
export const debounce = (fn, ms = 300) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };
export const rateTone = (v, thr = 75) => (v === null || v === undefined ? "" : v >= thr + 10 ? "good" : v >= thr ? "warn" : "bad");

// ------------------------------------------------------------ small components
export function badge(text, tone = "", ico) { return h("span", { class: "badge " + tone }, ico ? icon(ico) : null, text); }
export function statusBadge(state) {
  const m = {
    recorded: ["Recorded", "good", "check"], partial: ["Partly recorded", "warn", "clock"], missing: ["Not recorded", "bad", "alert"],
    not_school_day: ["Not a school day", "", "calendar"], no_students: ["No students", "", "users"],
    submitted: ["Submitted", "good", "check"], pending: ["Pending", "warn", "clock"], none: ["No exam", "", "info"],
    "n/a": ["Not applicable", "", "info"],
  };
  const [t, tone, i] = m[state] || [state, "", null];
  return badge(t, tone, i);
}
export function rateBar(value, thr = 75) {
  const tone = rateTone(value, thr);
  return h("div", { class: "rate" }, h("div", { class: "bar " + tone, role: "img", "aria-label": value === null || value === undefined ? "No data" : `${value}%` }, h("i", { style: { width: Math.max(0, Math.min(100, value ?? 0)) + "%" } })), h("b", null, fmtPct(value)));
}
export function stat({ label, value, sub, ico, tone = "" }) {
  return h("div", { class: "card stat " + tone }, h("div", { class: "label" }, ico ? h("span", { class: "ico" }, icon(ico)) : null, label), h("div", { class: "value" }, value), sub ? h("div", { class: "sub" }, sub) : null);
}
export function empty(title, text, ico = "info", action) {
  return h("div", { class: "empty" }, h("div", { class: "ico" }, icon(ico, "")), h("h3", null, title), text ? h("p", null, text) : null, action ? h("div", { style: { marginTop: "14px" } }, action) : null);
}
export const loading = (text = "Loading...") => h("div", { class: "loading", role: "status" }, h("span", { class: "spinner" }), text);
export function notice(text, tone = "", ico = "info") { return h("div", { class: "notice " + tone, role: tone === "bad" ? "alert" : null }, icon(ico), h("div", null, text)); }
export function card(title, body, { actions, flush } = {}) {
  return h("section", { class: "card" }, title || actions ? h("div", { class: "card-h" }, title ? h("h2", null, title) : h("span"), actions || null) : null, h("div", { class: "card-b" + (flush ? " flush" : "") }, body));
}
export function pageHead(title, sub, actions) {
  return h("div", { class: "page-head" }, h("div", null, h("h1", null, title), sub ? h("p", null, sub) : null), actions ? h("div", { class: "row" }, actions) : null);
}
export function tabs(items, active, onSelect) {
  const wrap = h("div", { class: "tabs", role: "tablist" });
  items.forEach((t) => wrap.append(h("button", { role: "tab", "aria-selected": t.id === active ? "true" : "false", onclick: () => onSelect(t.id) }, t.icon ? icon(t.icon) : null, t.label, t.count ? h("span", { class: "count" }, t.count) : null)));
  return wrap;
}
export function button(label, { kind = "", ico, onClick, type = "button", sm, title, disabled } = {}) {
  const b = h("button", { class: `btn ${kind} ${sm ? "sm" : ""}`.trim(), type, title, disabled }, ico ? icon(ico) : null, label);
  if (onClick) b.addEventListener("click", async (e) => {
    if (b.getAttribute("aria-busy") === "true") return;
    b.setAttribute("aria-busy", "true");
    try { await onClick(e, b); } finally { b.removeAttribute("aria-busy"); }
  });
  return b;
}

// ------------------------------------------------------------ toasts, modals, confirm
let toastHost;
export function toast(message, type = "info", ms = 4500) {
  if (!toastHost) { toastHost = h("div", { class: "toasts", role: "status", "aria-live": "polite" }); document.body.append(toastHost); }
  const t = h("div", { class: "toast " + type }, icon(type === "success" ? "check" : type === "error" ? "alert" : "info"), h("div", null, message));
  toastHost.append(t);
  setTimeout(() => t.remove(), type === "error" ? Math.max(ms, 7000) : ms);
}
export function errorToast(e) { toast(e instanceof ApiError ? e.message : "Something went wrong. Please try again.", "error"); if (!(e instanceof ApiError)) console.error(e); }

export function modal({ title, body, actions = [], size = "", onClose, dismissible = true }) {
  const prevFocus = document.activeElement;
  const close = () => { overlay.remove(); document.removeEventListener("keydown", onKey); prevFocus?.focus?.(); onClose?.(); };
  const titleId = "m" + Math.random().toString(36).slice(2, 8);
  const box = h("div", { class: "modal " + size, role: "dialog", "aria-modal": "true", "aria-labelledby": titleId },
    h("div", { class: "modal-h" }, h("h2", { id: titleId }, title), dismissible ? h("button", { class: "icon-btn", "aria-label": "Close", onclick: close }, icon("x")) : null),
    h("div", { class: "modal-b" }, body), actions.length ? h("div", { class: "modal-f" }, actions) : null);
  const overlay = h("div", { class: "overlay", onmousedown: (e) => { if (e.target === overlay && dismissible) close(); } }, box);
  const onKey = (e) => {
    if (e.key === "Escape" && dismissible) close();
    if (e.key === "Tab") {
      const f = [...box.querySelectorAll('a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])')];
      if (!f.length) return;
      const first = f[0], last = f[f.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    }
  };
  document.addEventListener("keydown", onKey);
  document.body.append(overlay);
  (box.querySelector("[autofocus], input, select, textarea") || box.querySelector(".modal-f button") || box).focus?.();
  return { close, box };
}

/** Resolves true/false. `requireText` makes the user type a phrase before the button enables. */
export function confirmDialog({ title, message, confirmText = "Confirm", danger = false, requireText }) {
  return new Promise((resolve) => {
    let done = false;
    const finish = (v) => { if (!done) { done = true; resolve(v); } };
    const input = requireText ? h("input", { class: "input", "aria-label": `Type ${requireText} to confirm`, autocomplete: "off" }) : null;
    const ok = h("button", { class: "btn " + (danger ? "danger" : "primary"), disabled: !!requireText, onclick: () => { finish(true); m.close(); } }, confirmText);
    input?.addEventListener("input", () => { ok.disabled = input.value.trim() !== requireText; });
    const m = modal({
      title, size: "sm", onClose: () => finish(false),
      body: h("div", { class: "stack-sm" }, h("p", null, message), requireText ? h("p", { class: "small muted" }, `Type "${requireText}" to continue.`) : null, input),
      actions: [h("button", { class: "btn", onclick: () => m.close() }, "Cancel"), ok],
    });
  });
}

// ------------------------------------------------------------ forms
export function field(label, control, { error, hint, required, full, id } = {}) {
  const fid = id || "f" + Math.random().toString(36).slice(2, 8);
  if (control.tagName === "INPUT" || control.tagName === "SELECT" || control.tagName === "TEXTAREA") control.id = control.id || fid;
  const f = h("div", { class: "field" + (full ? " full" : "") }, h("label", { for: control.id || fid }, label, required ? h("span", { class: "req", "aria-hidden": "true" }, " *") : null), control, hint ? h("div", { class: "hint" }, hint) : null, h("div", { class: "err", role: "alert" }));
  if (error) setFieldError(f, error);
  return f;
}
export function setFieldError(f, msg) {
  f.classList.toggle("invalid", !!msg); f.querySelector(".err").textContent = msg || "";
  const c = f.querySelector(".input"); if (c) c.setAttribute("aria-invalid", msg ? "true" : "false");
}
export const input = (props = {}) => h("input", { class: "input", ...props });
export function select(options, value, props = {}) {
  const s = h("select", { class: "input", ...props }, options.map((o) => { const [v, l] = Array.isArray(o) ? o : [o, o]; return h("option", { value: v, selected: String(v) === String(value ?? "") }, l); }));
  return s;
}
export const textarea = (props = {}) => h("textarea", { class: "input", ...props });
/** Show server-side field errors on a form made of `.field` elements with data-name. */
export function applyErrors(form, err) {
  form.querySelectorAll(".field").forEach((f) => setFieldError(f, ""));
  let top = form.querySelector(".form-error"); top?.remove();
  if (!(err instanceof ApiError)) return;
  let shown = 0;
  for (const [name, msg] of Object.entries(err.fields || {})) {
    const f = form.querySelector(`.field[data-name="${CSS.escape(name)}"]`);
    if (f) { setFieldError(f, msg); shown++; }
  }
  if (!shown || err.code !== "validation") form.prepend(h("div", { class: "form-error", role: "alert" }, err.message));
  else form.querySelector(".field.invalid .input")?.focus();
}
export function named(name, f) { f.dataset.name = name; return f; }

// ------------------------------------------------------------ data table (client-side sort)
export function dataTable({ columns, rows, empty: emptyEl, onRow, sortKey, sortDir = "asc", rowClass, server }) {
  let key = sortKey, dir = sortDir, data = rows;
  const wrap = h("div", { class: "table-wrap" });
  const draw = () => {
    let list = data;
    if (!server && key) {
      const col = columns.find((c) => c.key === key);
      const val = (r) => (col.sortValue ? col.sortValue(r) : r[key]);
      list = [...data].sort((a, b) => { const x = val(a), y = val(b); if (x === y) return 0; if (x === null || x === undefined) return 1; if (y === null || y === undefined) return -1; return (typeof x === "number" && typeof y === "number" ? x - y : String(x).localeCompare(String(y), undefined, { numeric: true, sensitivity: "base" })) * (dir === "asc" ? 1 : -1); });
    }
    if (!list.length && emptyEl) return mount(wrap, emptyEl);
    const head = h("tr", null, columns.map((c) => {
      const sortable = c.sortable !== false && c.label && (c.sortable || c.key);
      const th = h("th", { class: `${sortable ? "sortable" : ""} ${c.align === "right" ? "num" : c.align === "center" ? "c" : ""}`, scope: "col", "aria-sort": key === c.key ? (dir === "asc" ? "ascending" : "descending") : null }, c.label, key === c.key ? h("span", null, dir === "asc" ? " ▲" : " ▼") : null);
      if (sortable) { th.tabIndex = 0; const go = () => { if (server) { server(c.key, key === c.key && dir === "asc" ? "desc" : "asc"); } else { dir = key === c.key && dir === "asc" ? "desc" : "asc"; key = c.key; draw(); } }; th.addEventListener("click", go); th.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); go(); } }); }
      return th;
    }));
    const body = h("tbody", null, list.map((r) => {
      const tr = h("tr", { class: (onRow ? "click " : "") + (rowClass ? rowClass(r) : "") });
      columns.forEach((c) => tr.append(h("td", { class: c.align === "right" ? "num" : c.align === "center" ? "c" : "" }, c.render ? c.render(r) : r[c.key] ?? "-")));
      if (onRow) { tr.tabIndex = 0; tr.addEventListener("click", (e) => { if (!e.target.closest("button,a,input,select")) onRow(r); }); tr.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.target.closest("button,a,input,select")) onRow(r); }); }
      return tr;
    }));
    mount(wrap, h("table", { class: "t" }, h("thead", null, head), body));
  };
  draw();
  wrap.update = (next, k, d) => { data = next; if (k !== undefined) { key = k; dir = d || dir; } draw(); };
  return wrap;
}

/** Run an async loader into a container with spinner and error state. */
export async function load(container, fn, { retry } = {}) {
  mount(container, loading());
  try { const node = await fn(); mount(container, node); return node; }
  catch (e) {
    if (e instanceof ApiError && (e.status === 401)) return;
    mount(container, h("div", { class: "empty" }, h("div", { class: "ico" }, icon("alert")), h("h3", null, "We could not load this"), h("p", null, e instanceof ApiError ? e.message : "Unexpected error."), h("div", { style: { marginTop: "14px" } }, button("Try again", { ico: "refresh", onClick: () => load(container, fn, { retry }) }))));
    if (!(e instanceof ApiError)) console.error(e);
  }
}

/** 1 -> 1st, 2 -> 2nd, 11 -> 11th. Positions are always shown like this, never as "x out of y". */
export function ord(n) {
  if (n === null || n === undefined || n === "") return "-";
  const v = Number(n); if (!Number.isFinite(v)) return String(n);
  const t = v % 100, s = t >= 11 && t <= 13 ? "th" : { 1: "st", 2: "nd", 3: "rd" }[v % 10] || "th";
  return `${v}${s}`;
}
