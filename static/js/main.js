// Application shell: authentication, navigation, theme, and page routing.
import { ApiError, events, get, post, put, setCsrf } from "./lib/api.js";
import { button, clear, confirmDialog, errorToast, field, h, icon, initials, input, applyErrors, named, modal, mount, setTimezone, toast, loading } from "./lib/ui.js";

const root = document.getElementById("app");
const state = { user: null, school: null, meta: null, cleanup: null, alerts: 0, navOpen: false };

const can = (p) => !!state.user && state.user.permissions.includes(p);
const canAny = (...ps) => ps.some(can);
const ctx = {
  get user() { return state.user; }, get school() { return state.school; }, get meta() { return state.meta; },
  can, canAny, navigate: (hash) => { location.hash = hash; },
  query() { const i = location.hash.indexOf("?"); return new URLSearchParams(i < 0 ? "" : location.hash.slice(i + 1)); },
  async refreshMeta() { state.meta = await get("/api/meta"); return state.meta; },
  async refreshAlertCount() { await updateBell(); },
};

// ------------------------------------------------------------ theme
function applyTheme(t) {
  if (t === "light" || t === "dark") document.documentElement.setAttribute("data-theme", t);
  else document.documentElement.removeAttribute("data-theme");
}
function currentTheme() {
  const a = document.documentElement.getAttribute("data-theme");
  return a || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
}
try { applyTheme(localStorage.getItem("sms-theme")); } catch { /* storage unavailable: follow the OS */ }
function toggleTheme() {
  const next = currentTheme() === "dark" ? "light" : "dark";
  applyTheme(next);
  try { localStorage.setItem("sms-theme", next); } catch { /* ignore */ }
  render(); // charts read CSS variables, so redraw
}

// ------------------------------------------------------------ routes
const ROUTES = {
  dashboard: { label: "Dashboard", icon: "dashboard", load: () => import("./pages/dashboard.js"), perm: () => true },
  students: { label: "Manage Students", icon: "users", load: () => import("./pages/students.js"), perm: () => can("students.view") },
  attendance: { label: "Attendance", icon: "calendar", load: () => import("./pages/attendance.js"), perm: () => can("attendance.view") },
  exams: { label: "Examination", icon: "exam", load: () => import("./pages/exams.js"), perm: () => can("exams.view") },
  reports: { label: "Reports", icon: "chart", load: () => import("./pages/reports.js"), perm: () => canAny("reports.student", "reports.class", "reports.school") },
  admin: { label: "Administration", icon: "settings", load: () => import("./pages/admin.js"), perm: () => canAny("users.manage", "roles.manage", "assignments.manage", "setup.manage", "grading.manage", "settings.manage", "audit.view", "backups.manage"), hidden: true },
};
const parseHash = () => { const p = (location.hash.replace(/^#\/?/, "") || "dashboard").split("?")[0].split("/").filter(Boolean).map(decodeURIComponent); return { name: p[0] || "dashboard", params: p.slice(1) }; };

function dashboardLabel() { return can("command.view") ? "Command Centre" : "My Dashboard"; }

// ------------------------------------------------------------ boot
async function boot() {
  try {
    const me = await get("/api/auth/me");
    setCsrf(me.csrf); state.school = me.school; setTimezone(me.school.timezone);
    if (me.user) { state.user = me.user; await afterSignIn(); } else showAuth(me.needs_setup);
  } catch (e) {
    mount(root, h("div", { class: "empty", style: { marginTop: "20vh" } }, h("h3", null, "Cannot reach the server"), h("p", null, e.message), button("Try again", { kind: "primary", onClick: () => location.reload() })));
  }
}

async function afterSignIn() {
  state.meta = await get("/api/meta");
  setCsrf((await get("/api/auth/me")).csrf);
  document.title = `${state.school.name} | School Management`;
  if (state.user.must_change_password) return forcePasswordChange();
  render();
  updateBell();
}

events.addEventListener("auth", () => { if (state.user) { state.user = null; toast("Your session has ended. Please sign in again.", "warn"); get("/api/auth/me").then((me) => { setCsrf(me.csrf); showAuth(me.needs_setup); }); } });
events.addEventListener("password", () => { if (state.user) { state.user.must_change_password = true; forcePasswordChange(); } });
events.addEventListener("csrf", async () => { try { const me = await get("/api/auth/me"); setCsrf(me.csrf); toast("Your session token was refreshed. Please repeat your last action.", "warn"); } catch { /* ignore */ } });
window.addEventListener("hashchange", () => { if (state.user && !state.user.must_change_password) { state.navOpen = false; render(); } });

// ------------------------------------------------------------ auth screens
function logoNode(cls) {
  return h("div", { class: cls }, state.school?.has_logo ? h("img", { src: "/api/auth/school-logo?v=" + Date.now(), alt: "" }) : initials(state.school?.name || "S"));
}

function authLayout(title, subtitle, form) {
  mount(root, h("div", { class: "auth" },
    h("div", { class: "auth-hero" },
      h("div", { class: "row" }, logoNode("logo-lg"), h("div", null, h("b", { style: { fontSize: "1.2rem" } }, state.school?.name || "School"), state.school?.motto ? h("div", { class: "small", style: { color: "var(--navy-muted)" } }, state.school.motto) : null)),
      h("div", null, h("h1", null, "Every class, every record, one clear view."), h("p", null, "Student records, attendance, examinations and reports in one secure place, with a central command centre for school leaders.")),
      h("div", { class: "small", style: { color: "var(--navy-muted)" } }, "Authorised staff only. Activity is recorded.")),
    h("div", { class: "auth-pane" }, h("div", { class: "auth-card stack" }, h("div", null, h("h1", null, title), h("p", { class: "muted", style: { marginTop: "6px" } }, subtitle)), form))));
}

function showAuth(needsSetup) {
  state.user = null; state.cleanup?.(); state.cleanup = null;
  document.title = state.school?.name ? `Sign in | ${state.school.name}` : "Sign in";
  needsSetup ? showSetup() : showLogin();
}

function showLogin() {
  const user = named("username", field("Username", input({ autocomplete: "username", autocapitalize: "none", spellcheck: "false", required: true }), { required: true }));
  const pass = named("password", field("Password", input({ type: "password", autocomplete: "current-password", required: true }), { required: true }));
  const submit = h("button", { class: "btn primary", type: "submit", style: { width: "100%" } }, icon("login"), "Sign in");
  const form = h("form", { class: "stack", novalidate: true, onsubmit: async (e) => {
    e.preventDefault(); applyErrors(form, null);
    submit.setAttribute("aria-busy", "true");
    try {
      const r = await post("/api/auth/login", { username: user.querySelector("input").value, password: pass.querySelector("input").value });
      setCsrf(r.csrf); state.user = r.user; state.school = r.school; setTimezone(r.school.timezone);
      await afterSignIn();
    } catch (err) { applyErrors(form, err); if (!(err instanceof ApiError)) errorToast(err); pass.querySelector("input").value = ""; }
    finally { submit.removeAttribute("aria-busy"); }
  } }, user, pass, submit);
  authLayout("Sign in", "Use the account your administrator created for you.", form);
  user.querySelector("input").focus();
}

function showSetup() {
  const f = {
    school_name: named("school_name", field("School name", input({ required: true }), { required: true })),
    full_name: named("full_name", field("Your full name", input({ autocomplete: "name" }), { required: true })),
    username: named("username", field("Choose a username", input({ autocomplete: "username", autocapitalize: "none" }), { required: true })),
    password: named("password", field("Choose a password", input({ type: "password", autocomplete: "new-password" }), { required: true, hint: "At least 10 characters, with letters and numbers." })),
  };
  const form = h("form", { class: "stack", novalidate: true, onsubmit: async (e) => {
    e.preventDefault(); applyErrors(form, null);
    const body = Object.fromEntries(Object.entries(f).map(([k, v]) => [k, v.querySelector("input").value]));
    try {
      await post("/api/auth/setup", body);
      const r = await post("/api/auth/login", { username: body.username, password: body.password });
      setCsrf(r.csrf); state.user = r.user; state.school = r.school; await afterSignIn();
      toast("Welcome! Next, add your academic year, classes and teachers under Administration.", "success", 9000);
    } catch (err) { applyErrors(form, err); if (!(err instanceof ApiError)) errorToast(err); }
  } }, ...Object.values(f), h("button", { class: "btn primary", type: "submit" }, "Create administrator account"));
  authLayout("Set up your school", "Create the first Super Administrator account. This screen appears only once.", form);
}

function forcePasswordChange() {
  const cur = named("current_password", field("Temporary password", input({ type: "password", autocomplete: "current-password" }), { required: true }));
  const nw = named("new_password", field("New password", input({ type: "password", autocomplete: "new-password" }), { required: true, hint: "At least 10 characters, with letters and numbers." }));
  const form = h("form", { class: "stack", novalidate: true, onsubmit: async (e) => {
    e.preventDefault(); applyErrors(form, null);
    try {
      await post("/api/auth/change-password", { current_password: cur.querySelector("input").value, new_password: nw.querySelector("input").value });
      state.user.must_change_password = false; toast("Password changed.", "success"); render(); updateBell();
    } catch (err) { applyErrors(form, err); if (!(err instanceof ApiError)) errorToast(err); }
  } }, cur, nw, h("button", { class: "btn primary", type: "submit" }, "Change password"), h("button", { class: "btn ghost", type: "button", onclick: signOut }, "Sign out"));
  authLayout("Choose a new password", "For your security, replace the temporary password before continuing.", form);
}

async function signOut() {
  try { const r = await post("/api/auth/logout"); setCsrf(r.csrf); } catch { /* ignore */ }
  state.user = null; state.meta = null; state.alerts = 0; state.cleanup?.(); state.cleanup = null;
  const me = await get("/api/auth/me").catch(() => null);
  if (me) setCsrf(me.csrf);
  location.hash = "";
  showAuth(false);
}

// ------------------------------------------------------------ change password dialog
function changePasswordDialog() {
  const cur = named("current_password", field("Current password", input({ type: "password", autocomplete: "current-password" }), { required: true }));
  const nw = named("new_password", field("New password", input({ type: "password", autocomplete: "new-password" }), { required: true, hint: "At least 10 characters, with letters and numbers." }));
  const form = h("form", { class: "stack", novalidate: true }, cur, nw);
  const m = modal({ title: "Change password", size: "sm", body: form, actions: [
    h("button", { class: "btn", type: "button", onclick: () => m.close() }, "Cancel"),
    button("Change password", { kind: "primary", onClick: async () => {
      applyErrors(form, null);
      try { await post("/api/auth/change-password", { current_password: cur.querySelector("input").value, new_password: nw.querySelector("input").value }); toast("Password changed. Other devices were signed out.", "success"); m.close(); }
      catch (err) { applyErrors(form, err); if (!(err instanceof ApiError)) errorToast(err); }
    } })] });
}

// ------------------------------------------------------------ shell
async function updateBell() {
  if (!can("command.view")) return;
  try {
    const r = await get("/api/command/alerts", { status: "open" });
    state.alerts = r.items.length;
    const dot = document.querySelector("#bell .dot");
    const btn = document.getElementById("bell");
    if (btn) { dot?.remove(); if (state.alerts) btn.append(h("span", { class: "dot", "aria-hidden": "true" }, state.alerts > 99 ? "99+" : state.alerts)); btn.setAttribute("aria-label", `${state.alerts} open alerts`); }
  } catch { /* the bell is optional */ }
}

function navItems() {
  return ["dashboard", "students", "attendance", "exams", "reports"].filter((k) => ROUTES[k].perm()).map((k) => ({ key: k, ...ROUTES[k], label: k === "dashboard" ? dashboardLabel() : ROUTES[k].label }));
}

function userMenu() {
  const wrap = h("div", { class: "relative" });
  let open = false, menu;
  const close = () => { open = false; menu?.remove(); document.removeEventListener("click", outside, true); };
  const outside = (e) => { if (!wrap.contains(e.target)) close(); };
  const admin = ROUTES.admin.perm();
  const btn = h("button", { class: "user-btn", "aria-haspopup": "menu", "aria-expanded": "false", onclick: () => {
    if (open) return close();
    open = true; btn.setAttribute("aria-expanded", "true");
    const link = (label, ico, hash) => h("a", { href: hash, onclick: () => close() }, icon(ico), label);
    const act = (label, ico, fn) => h("button", { type: "button", onclick: () => { close(); fn(); } }, icon(ico), label);
    menu = h("div", { class: "menu", role: "menu" },
      h("div", { class: "head" }, h("b", null, state.user.full_name), h("div", { class: "small muted" }, state.user.role_label + (state.user.staff_id ? ` | ${state.user.staff_id}` : ""))),
      h("hr"),
      admin ? h("div", { class: "group" }, "Administration") : null,
      admin ? [
        canAny("users.manage", "roles.manage") ? link("Users and permissions", "key", "#/admin/users") : null,
        can("assignments.manage") ? link("Teaching assignments", "swap", "#/admin/assignments") : null,
        can("setup.manage") ? link("School setup", "school", "#/admin/setup") : null,
        can("grading.manage") ? link("Grading scales", "list", "#/admin/grading") : null,
        can("settings.manage") ? link("Settings and branding", "settings", "#/admin/settings") : null,
        can("audit.view") ? link("Audit log", "shield", "#/admin/audit") : null,
        can("backups.manage") ? link("Backups", "database", "#/admin/backups") : null,
        h("hr")] : null,
      act(currentTheme() === "dark" ? "Switch to light mode" : "Switch to dark mode", currentTheme() === "dark" ? "sun" : "moon", toggleTheme),
      act("Change password", "key", changePasswordDialog),
      act("Sign out", "logout", signOut));
    wrap.append(menu);
    setTimeout(() => document.addEventListener("click", outside, true), 0);
  } }, h("span", { class: "avatar" }, initials(state.user.full_name)), h("span", { class: "who" }, h("b", null, state.user.full_name.replace(/\(.*?\)/g, "").trim()), h("span", null, state.user.role_label)), icon("chevron"));
  wrap.append(btn);
  return wrap;
}

function shell() {
  const items = navItems();
  const current = parseHash().name;
  const sidebar = h("aside", { class: "sidebar", "aria-label": "Main navigation" },
    h("div", { class: "brand" }, h("div", { class: "brand-mark" }, state.school.has_logo ? h("img", { src: "/api/auth/school-logo", alt: "" }) : initials(state.school.name)), h("div", null, h("div", { class: "brand-name" }, state.school.name), h("div", { class: "brand-sub" }, "School Management"))),
    h("nav", { class: "nav" }, h("div", { class: "nav-label" }, "Modules"), items.map((i) => h("a", { href: "#/" + i.key, "aria-current": i.key === current ? "page" : null }, icon(i.icon), i.label))),
    h("div", { class: "sidebar-foot" }, state.school.motto || "Signed in securely"));
  const titleFor = ROUTES[current] ? (current === "dashboard" ? dashboardLabel() : ROUTES[current].label) : "Not found";
  const bell = can("command.view") ? h("a", { id: "bell", class: "icon-btn", href: "#/dashboard/alerts", "aria-label": "Alerts", title: "Alerts" }, icon("bell"), state.alerts ? h("span", { class: "dot" }, state.alerts) : null) : null;
  const app = h("div", { class: "app" + (state.navOpen ? " nav-open" : "") }, sidebar, h("div", { class: "scrim", onclick: () => { app.classList.remove("nav-open"); state.navOpen = false; } }),
    h("div", { class: "main" },
      h("header", { class: "topbar" },
        h("button", { class: "icon-btn menu-btn", "aria-label": "Open menu", onclick: () => { app.classList.toggle("nav-open"); state.navOpen = app.classList.contains("nav-open"); } }, icon("menu")),
        h("div", { class: "title grow" }, titleFor), bell,
        h("button", { class: "icon-btn", "aria-label": "Toggle dark mode", title: "Light / dark mode", onclick: toggleTheme }, icon(currentTheme() === "dark" ? "sun" : "moon")),
        userMenu()),
      h("main", { class: "content", id: "view", tabindex: "-1" })));
  mount(root, app);
  return document.getElementById("view");
}

let renderToken = 0;
async function render() {
  if (!state.user || state.user.must_change_password) return;
  state.cleanup?.(); state.cleanup = null;
  const { name, params } = parseHash();
  const view = shell();
  const route = ROUTES[name];
  if (!route) { mount(view, h("div", { class: "empty" }, h("h3", null, "Page not found"), h("p", null, "That page does not exist."), h("a", { class: "btn primary", href: "#/dashboard" }, "Go to dashboard"))); return; }
  if (!route.perm()) { mount(view, h("div", { class: "empty" }, h("div", { class: "ico" }, icon("shield")), h("h3", null, "You do not have access to this page"), h("p", null, "Ask an administrator if you need it."), h("a", { class: "btn primary", href: "#/dashboard" }, "Go to dashboard"))); return; }
  const token = ++renderToken;
  mount(view, loading());
  try {
    const mod = await route.load();
    if (token !== renderToken) return;
    clear(view);
    const cleanup = await mod.render(ctx, view, params);
    if (token !== renderToken) { cleanup?.(); return; }
    state.cleanup = typeof cleanup === "function" ? cleanup : null;
  } catch (e) {
    if (token !== renderToken) return;
    mount(view, h("div", { class: "empty" }, h("div", { class: "ico" }, icon("alert")), h("h3", null, "This page could not be loaded"), h("p", null, e instanceof ApiError ? e.message : "Unexpected error."), button("Try again", { kind: "primary", onClick: render })));
    if (!(e instanceof ApiError)) console.error(e);
  }
  view.focus({ preventScroll: true });
  window.scrollTo(0, 0);
}

boot();
