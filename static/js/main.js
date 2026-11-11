// Application shell: authentication, navigation, theme, and page routing.
import { ApiError, events, get, post, put, setCsrf } from "./lib/api.js";
import { button, clear, confirmDialog, errorToast, field, h, icon, initials, input, applyErrors, named, modal, mount, setTimezone, toast, loading, notice } from "./lib/ui.js";
import { applyPrefs, getPrefs, isDark, saveLocal } from "./lib/themes.js";

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
const currentTheme = () => (isDark() ? "dark" : "light");
// Quick light/dark switch in the top bar. The colour theme the user picked is kept; only the mode changes.
async function toggleTheme() {
  const p = getPrefs();
  p.mode = isDark() ? "light" : "dark";
  applyPrefs(p); saveLocal(p);
  if (state.user) { state.user.ui_prefs = p; put("/api/auth/preferences", p).catch(() => {}); render(); } else showAuth();
}
// After sign-in the account's saved appearance wins over whatever this browser last used.
function applySavedAppearance() {
  const p = state.user?.ui_prefs;
  if (p) { applyPrefs(p); saveLocal(p); }
}

// ------------------------------------------------------------ routes
const ROUTES = {
  dashboard: { label: "Dashboard", icon: "dashboard", load: () => import("./pages/dashboard.js"), perm: () => true },
  students: { label: "Manage Students", icon: "users", load: () => import("./pages/students.js"), perm: () => can("students.view") },
  attendance: { label: "Attendance", icon: "calendar", load: () => import("./pages/attendance.js"), perm: () => can("attendance.view") },
  exams: { label: "Examination", icon: "exam", load: () => import("./pages/exams.js"), perm: () => can("exams.view") },
  reports: { label: "Reports", icon: "chart", load: () => import("./pages/reports.js"), perm: () => canAny("reports.student", "reports.class", "reports.school") },
  appearance: { label: "Appearance & Themes", icon: "palette", load: () => import("./pages/appearance.js"), perm: () => true, hidden: true },
  admin: { label: "Administration", icon: "settings", load: () => import("./pages/admin.js"), perm: () => canAny("users.manage", "roles.manage", "assignments.manage", "setup.manage", "grading.manage", "settings.manage", "audit.view", "backups.manage"), hidden: true },
};
const parseHash = () => { const p = (location.hash.replace(/^#\/?/, "") || "dashboard").split("?")[0].split("/").filter(Boolean).map(decodeURIComponent); return { name: p[0] || "dashboard", params: p.slice(1) }; };

function dashboardLabel() { return can("command.view") ? "Command Centre" : "My Dashboard"; }

// ------------------------------------------------------------ boot
async function boot() {
  try {
    const me = await get("/api/auth/me");
    setCsrf(me.csrf); state.school = me.school; setTimezone(me.school.timezone);
    if (me.user) { state.user = me.user; await afterSignIn(); } else showAuth();
  } catch (e) {
    mount(root, h("div", { class: "empty", style: { marginTop: "20vh" } }, h("h3", null, "Cannot reach the server"), h("p", null, e.message), button("Try again", { kind: "primary", onClick: () => location.reload() })));
  }
}

async function afterSignIn() {
  applySavedAppearance();
  state.meta = await get("/api/meta");
  setCsrf((await get("/api/auth/me")).csrf);
  document.title = `${state.school.name} | School Management`;
  if (state.user.must_change_password) return forcePasswordChange();
  render();
  updateBell();
}

events.addEventListener("auth", () => { if (state.user) { state.user = null; toast("Your session has ended. Please sign in again.", "warn"); get("/api/auth/me").then((me) => { setCsrf(me.csrf); showAuth(); }); } });
events.addEventListener("password", () => { if (state.user) { state.user.must_change_password = true; forcePasswordChange(); } });
events.addEventListener("csrf", async () => { try { const me = await get("/api/auth/me"); setCsrf(me.csrf); toast("Your session token was refreshed. Please repeat your last action.", "warn"); } catch { /* ignore */ } });
window.addEventListener("hashchange", () => { if (state.user && !state.user.must_change_password) { state.navOpen = false; render(); } });

// ------------------------------------------------------------ auth screens
function logoNode(cls) {
  return h("div", { class: cls }, state.school?.has_logo ? h("img", { src: "/api/auth/school-logo?v=" + Date.now(), alt: "" }) : initials(state.school?.name || "S"));
}

const themeBtn = () => h("button", { class: "btn ghost sm theme-float", type: "button", "aria-label": "Switch between light and dark mode", onclick: toggleTheme }, icon(currentTheme() === "dark" ? "sun" : "moon"), currentTheme() === "dark" ? "Light mode" : "Dark mode");

function showWelcomePage() {
  mount(root, h("div", { class: "welcome" }, themeBtn(),
    h("div", { class: "welcome-card" },
      h("div", { class: "welcome-logo" }, logoNode("logo-lg")),
      h("h1", null, "Welcome to School Management System"),
      h("p", null, "A smarter and simpler way to manage students, attendance, examinations and school reports."),
      h("div", { class: "welcome-actions" },
        h("a", { class: "btn primary lg", href: "#/login" }, icon("login"), "Sign In"),
        h("a", { class: "btn lg", href: "#/register" }, icon("plus"), "Create Account")),
      h("ul", { class: "welcome-points" }, ["Students and classes", "Weekly attendance registers", "Examinations and positions", "Report cards and school-wide monitoring"].map((t) => h("li", null, icon("check"), t))))));
}

function authLayout(title, subtitle, form) {
  mount(root, h("div", { class: "auth" }, themeBtn(),
    h("div", { class: "auth-hero" },
      h("div", { class: "row" }, logoNode("logo-lg"), h("div", null, h("b", { style: { fontSize: "1.2rem" } }, state.school?.name || "School"), state.school?.motto ? h("div", { class: "small", style: { color: "var(--navy-muted)" } }, state.school.motto) : null)),
      h("div", null, h("h1", null, "Every class, every record, one clear view."), h("p", null, "Student records, attendance, examinations and reports in one secure place, with a central command centre for school leaders.")),
      h("div", { class: "small", style: { color: "var(--navy-muted)" } }, "Authorised staff only. Activity is recorded.")),
    h("div", { class: "auth-pane" }, h("div", { class: "auth-card stack" }, h("div", null, h("h1", null, title), h("p", { class: "muted", style: { marginTop: "6px" } }, subtitle)), form))));
}

const RULES = [["At least 10 characters", (v) => v.length >= 10], ["An uppercase letter (A-Z)", (v) => /[A-Z]/.test(v)], ["A lowercase letter (a-z)", (v) => /[a-z]/.test(v)],
  ["A number (0-9)", (v) => /\d/.test(v)], ["A symbol such as ! # $ %", (v) => /[^A-Za-z0-9\s]/.test(v)]];

/** Password input with show/hide, live rule checklist and a strength bar. */
function passwordField(label, name, { rules = false, autocomplete = "new-password" } = {}) {
  const inp = input({ type: "password", autocomplete, required: true });
  const toggle = h("button", { type: "button", "aria-label": "Show password", onclick: () => { const show = inp.type === "password"; inp.type = show ? "text" : "password"; toggle.textContent = show ? "Hide" : "Show"; toggle.setAttribute("aria-label", show ? "Hide password" : "Show password"); } }, "Show");
  const f = named(name, field(label, h("div", { class: "pw-wrap" }, inp, toggle), { required: true }));
  const bar = h("i"), meter = h("div", { class: "strength", "aria-hidden": "true" }, bar), list = h("ul", { class: "rules" }, RULES.map(([t]) => h("li", null, t))), label2 = h("div", { class: "small muted" });
  if (rules) {
    f.append(meter, label2, list);
    inp.addEventListener("input", () => {
      const v = inp.value, ok = RULES.map(([, t]) => t(v)), n = ok.filter(Boolean).length + (v.length >= 14 ? 1 : 0);
      list.querySelectorAll("li").forEach((li, i) => li.classList.toggle("ok", ok[i]));
      bar.style.width = (v ? Math.max(8, (n / 6) * 100) : 0) + "%";
      bar.style.background = n <= 2 ? "var(--crit)" : n <= 4 ? "var(--warn)" : "var(--good)";
      label2.textContent = v ? (n <= 2 ? "Weak password" : n <= 4 ? "Getting there" : n === 5 ? "Strong password" : "Very strong password") : "";
    });
  }
  return { node: f, input: inp };
}

function copyButton(text, label = "Copy") {
  return h("button", { class: "btn sm", type: "button", onclick: async (e) => { try { await navigator.clipboard.writeText(text); e.currentTarget.textContent = "Copied"; } catch { toast("Copy is not available here. Select the text and copy it.", "warn"); } } }, icon("copy"), label);
}

function authRoute() { const name = location.hash.replace(/^#\/?/, "").split("?")[0]; return ["register", "forgot", "reset", "verify", "login"].includes(name) ? name : "welcome"; }
function hashToken() { const i = location.hash.indexOf("?"); return new URLSearchParams(i < 0 ? "" : location.hash.slice(i + 1)).get("token") || ""; }

function showAuth() {
  state.user = null; state.cleanup?.(); state.cleanup = null;
  const r = authRoute();
  document.title = "School Management System";
  ({ welcome: showWelcomePage, login: showLogin, register: showRegister, forgot: showForgot, reset: showReset, verify: showVerify }[r])();
}
window.addEventListener("hashchange", () => { if (!state.user) showAuth(); });

function showLogin() {
  const user = named("username", field("Username", input({ autocomplete: "username", autocapitalize: "none", spellcheck: "false", required: true, placeholder: "e.g. johnmensah01" }), { required: true }));
  const pw = passwordField("Password", "password", { autocomplete: "current-password" });
  const submit = h("button", { class: "btn primary", type: "submit", style: { width: "100%" } }, icon("login"), "Sign in");
  const form = h("form", { class: "stack", novalidate: true, onsubmit: async (e) => {
    e.preventDefault(); applyErrors(form, null);
    submit.setAttribute("aria-busy", "true");
    try {
      const r = await post("/api/auth/login", { username: user.querySelector("input").value, password: pw.input.value });
      setCsrf(r.csrf); state.user = r.user; state.school = r.school; setTimezone(r.school.timezone);
      location.hash = "";
      await afterSignIn();
    } catch (err) { applyErrors(form, err); if (!(err instanceof ApiError)) errorToast(err); pw.input.value = ""; }
    finally { submit.removeAttribute("aria-busy"); }
  } }, user, pw.node, submit,
  h("div", { class: "linkrow" }, h("a", { href: "#/forgot" }, "Forgot password?"), h("a", { href: "#/register" }, "Register your school")));
  authLayout("Sign in", "Use the username created for you when you registered (for example johnmensah01).", form);
  user.querySelector("input").focus();
}

function showRegister() {
  const school = named("school_name", field("School name", input({ required: true, maxlength: 120, autocomplete: "organization" }), { required: true }));
  const full = named("full_name", field("Full name", input({ required: true, maxlength: 120, autocomplete: "name" }), { required: true }));
  const preview = h("div", { class: "username-preview", "aria-live": "polite" }, "Your username will appear here");
  const email = named("email", field("Email (optional)", input({ type: "email", autocomplete: "email" }), { hint: "Used for password reset links and verification where the server supports email." }));
  const pw = passwordField("Password", "password", { rules: true });
  const pw2 = passwordField("Confirm password", "confirm_password");
  let username = "", t;
  const update = () => { clearTimeout(t); const v = full.querySelector("input").value.trim(); if (v.length < 2) { preview.textContent = "Your username will appear here"; username = ""; return; }
    t = setTimeout(async () => { try { const r = await get("/api/auth/username-preview", { full_name: v }); username = r.username; preview.textContent = ""; preview.append("Your username: ", h("b", null, r.username)); } catch { /* shown on submit */ } }, 250); };
  full.querySelector("input").addEventListener("input", update);
  const submit = h("button", { class: "btn primary", type: "submit", style: { width: "100%" } }, "Create my school account");
  const form = h("form", { class: "stack", novalidate: true, onsubmit: async (e) => {
    e.preventDefault(); applyErrors(form, null);
    if (pw.input.value !== pw2.input.value) { applyErrors(form, new ApiError(422, "", "validation", { confirm_password: "The two passwords do not match." })); return; }
    submit.setAttribute("aria-busy", "true");
    try {
      const r = await post("/api/auth/register", { school_name: school.querySelector("input").value, full_name: full.querySelector("input").value, email: email.querySelector("input").value,
        password: pw.input.value, confirm_password: pw2.input.value, username });
      setCsrf(r.csrf); state.user = r.user; state.school = r.school; setTimezone(r.school.timezone);
      showWelcome(r);
    } catch (err) { applyErrors(form, err); if (!(err instanceof ApiError)) errorToast(err); }
    finally { submit.removeAttribute("aria-busy"); }
  } }, school, full, preview, email, pw.node, pw2.node, submit, h("div", { class: "linkrow" }, h("span", { class: "muted" }, "Already registered?"), h("a", { href: "#/login" }, "Sign in")));
  authLayout("Register your school", "Create your school's private workspace in a minute. You will be its Headmaster / School Administrator.", form);
  school.querySelector("input").focus();
}

function showWelcome(r) {
  const body = h("div", { class: "stack" },
    h("p", null, "Your school workspace is ready. Write down your sign-in details now:"),
    h("div", null, h("div", { class: "small muted" }, "Your username"), h("div", { class: "code-box" }, r.username), h("div", { style: { marginTop: "6px" } }, copyButton(r.username))),
    h("div", null, h("div", { class: "small muted" }, "Your recovery code (shown only once)"), h("div", { class: "code-box" }, r.recovery_code), h("div", { style: { marginTop: "6px" } }, copyButton(r.recovery_code)),
      h("p", { class: "small muted", style: { marginTop: "6px" } }, "If you ever forget your password, this code lets you set a new one. Keep it somewhere safe.")),
    r.verification_sent ? notice("We sent a confirmation link to your email address.", "", "info") : (r.email_enabled ? null : notice("Email is not set up on this server, so email verification is switched off. Your account works normally.", "", "info")),
    h("button", { class: "btn primary", type: "button", style: { width: "100%" }, onclick: async () => { location.hash = ""; await afterSignIn(); toast("Welcome! Start by creating your classes under Attendance, or add teachers under Administration.", "success", 9000); } }, "Continue to my dashboard"));
  authLayout("Account created", state.school.name, body);
}

function showForgot() {
  const user = named("username", field("Username", input({ autocomplete: "username", autocapitalize: "none", required: true }), { required: true }));
  const msg = h("div");
  const form = h("form", { class: "stack", novalidate: true, onsubmit: async (e) => {
    e.preventDefault(); applyErrors(form, null);
    try { const r = await post("/api/auth/forgot-password", { username: user.querySelector("input").value }); mount(msg, notice(r.message, "good", "check")); }
    catch (err) { applyErrors(form, err); if (!(err instanceof ApiError)) errorToast(err); }
  } }, user, button("Send reset link", { kind: "primary", type: "submit" }), msg,
  h("div", { class: "linkrow" }, h("a", { href: "#/reset" }, "I have a recovery code"), h("a", { href: "#/login" }, "Back to sign in")));
  authLayout("Forgot your password?", "Enter your username. If email is set up for your account we will send a reset link. Teachers can also ask their School Administrator to reset it.", form);
}

function showReset() {
  const token = hashToken();
  const user = named("username", field("Username", input({ autocomplete: "username", autocapitalize: "none" }), { required: !token }));
  const code = named("recovery_code", field("Recovery code", input({ autocapitalize: "characters", placeholder: "XXXX-XXXX-XXXX-XXXX" }), { required: !token }));
  const pw = passwordField("New password", "new_password", { rules: true });
  const pw2 = passwordField("Confirm new password", "confirm_password");
  const form = h("form", { class: "stack", novalidate: true, onsubmit: async (e) => {
    e.preventDefault(); applyErrors(form, null);
    try {
      const r = await post("/api/auth/reset-password", { token, username: user.querySelector("input").value, recovery_code: code.querySelector("input").value, new_password: pw.input.value, confirm_password: pw2.input.value });
      mount(root, h("div", { class: "auth" }, h("div", { class: "auth-pane", style: { gridColumn: "1 / -1" } }, h("div", { class: "auth-card stack" }, h("h1", null, "Password changed"),
        h("p", null, "You can now sign in with your new password."),
        r.new_recovery_code ? h("div", null, h("div", { class: "small muted" }, "Your new recovery code (the old one no longer works)"), h("div", { class: "code-box" }, r.new_recovery_code), h("div", { style: { marginTop: "6px" } }, copyButton(r.new_recovery_code))) : null,
        h("a", { class: "btn primary", href: "#/login" }, "Go to sign in")))));
    } catch (err) { applyErrors(form, err); if (!(err instanceof ApiError)) errorToast(err); }
  } }, token ? null : user, token ? null : code, pw.node, pw2.node, button("Set new password", { kind: "primary", type: "submit" }), h("a", { href: "#/login" }, "Back to sign in"));
  authLayout("Set a new password", token ? "Choose a new password for your account." : "Enter your username and the recovery code you saved when you registered.", form);
}

async function showVerify() {
  const token = hashToken();
  authLayout("Confirming your email", "", h("div", { class: "loading" }, h("span", { class: "spinner" }), "Please wait..."));
  let body;
  try { await post("/api/auth/verify-email", { token }); body = h("div", { class: "stack" }, notice("Your email address is confirmed. Thank you.", "good", "check"), h("a", { class: "btn primary", href: "#/login" }, "Continue")); }
  catch (e) { body = h("div", { class: "stack" }, notice(e.message, "bad", "alert"), h("a", { class: "btn", href: "#/login" }, "Back to sign in")); }
  authLayout("Email confirmation", "", body);
}

function forcePasswordChange() {
  const cur = named("current_password", field("Temporary password", input({ type: "password", autocomplete: "current-password" }), { required: true }));
  const nw = named("new_password", field("New password", input({ type: "password", autocomplete: "new-password" }), { required: true, hint: "At least 10 characters with upper and lower case letters, a number and a symbol." }));
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
  showAuth();
}

// ------------------------------------------------------------ change password dialog
function changePasswordDialog() {
  const cur = named("current_password", field("Current password", input({ type: "password", autocomplete: "current-password" }), { required: true }));
  const nw = named("new_password", field("New password", input({ type: "password", autocomplete: "new-password" }), { required: true, hint: "At least 10 characters with upper and lower case letters, a number and a symbol." }));
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
        link("Appearance and themes", "palette", "#/admin/appearance"),
        can("audit.view") ? link("Audit log", "shield", "#/admin/audit") : null,
        can("backups.manage") ? link("Backups", "database", "#/admin/backups") : null,
        h("hr")] : null,
      link("Appearance & themes", "palette", "#/appearance"),
      act(currentTheme() === "dark" ? "Switch to light mode" : "Switch to dark mode", currentTheme() === "dark" ? "sun" : "moon", toggleTheme),
      act("Change password", "key", changePasswordDialog),
      act("Sign out", "logout", signOut));
    wrap.append(menu);
    setTimeout(() => document.addEventListener("click", outside, true), 0);
  } }, h("span", { class: "avatar" }, initials(state.user.full_name)), h("span", { class: "who" }, h("b", null, state.user.full_name.replace(/\(.*?\)/g, "").trim()), h("span", null, state.user.role_label)), icon("chevron"));
  wrap.append(btn);
  return wrap;
}

function searchBox() {
  const inp = h("input", { class: "input", type: "search", placeholder: "Search students, teachers, classes, exams...", "aria-label": "Global search", autocomplete: "off" });
  const pop = h("div", { class: "search-pop", role: "listbox", hidden: true });
  const wrap = h("div", { class: "topsearch", id: "topsearch" }, inp, pop);
  const href = (r) => ({ student: `#/students/${r.id}`, class: can("command.view") ? `#/dashboard/classes/${r.id}` : `#/attendance?class=${r.id}`, attendance: `#/attendance?class=${r.id}`,
    teacher: `#/dashboard/teachers/${r.id}`, exam: `#/exams/${r.id}`, report: "#/reports" }[r.type] || "#/dashboard");
  const LABEL = { student: "Students", class: "Classes", attendance: "Attendance", teacher: "Teachers", exam: "Examinations", report: "Reports" };
  const close = () => { pop.hidden = true; };
  let seq = 0, t;
  inp.addEventListener("input", () => {
    clearTimeout(t); const q = inp.value.trim();
    if (q.length < 2) return close();
    t = setTimeout(async () => {
      const n = ++seq;
      try {
        const r = await get("/api/search", { q });
        if (n !== seq) return;
        clear(pop);
        if (!r.results.length) pop.append(h("div", { class: "small muted", style: { padding: "10px" } }, "No matches."));
        let last = "";
        for (const x of r.results) {
          if (x.type !== last) { pop.append(h("div", { class: "grp" }, LABEL[x.type] || x.type)); last = x.type; }
          pop.append(h("a", { href: href(x), onclick: () => { close(); inp.value = ""; wrap.classList.remove("open"); } }, h("span", null, x.title), h("small", null, x.subtitle)));
        }
        pop.hidden = false;
      } catch { /* search is optional */ }
    }, 250);
  });
  inp.addEventListener("keydown", (e) => { if (e.key === "Escape") { close(); inp.blur(); } });
  document.addEventListener("click", (e) => { if (!wrap.contains(e.target) && e.target.id !== "searchbtn") close(); });
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
        h("div", { class: "title grow" }, titleFor), searchBox(),
        h("button", { class: "icon-btn", id: "searchbtn", "aria-label": "Search", title: "Search", onclick: () => { const t = document.getElementById("topsearch"); t.classList.toggle("open"); t.querySelector("input").focus(); } }, icon("search")), bell,
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
