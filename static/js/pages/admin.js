// Supporting functions: users and permissions, assignments, school setup, grading, settings, audit log, backups.
// These are reached from the user menu, not the sidebar.
import { ApiError, del, download, get, post, put, upload } from "../lib/api.js";
import { applyErrors, badge, button, card, confirmDialog, dataTable, empty, errorToast, field, fmtDate, fmtDateTime, fmtNum, h, input, load, modal, mount, named, notice, pageHead, select, tabs, toast, debounce, icon } from "../lib/ui.js";
import { ago } from "../lib/ui.js";

const TABS = [
  { id: "users", label: "Users and permissions", icon: "key", perm: ["users.manage", "roles.manage"], fn: () => usersTab },
  { id: "assignments", label: "Teaching assignments", icon: "swap", perm: ["assignments.manage"], fn: () => assignmentsTab },
  { id: "setup", label: "School setup", icon: "school", perm: ["setup.manage"], fn: () => setupTab },
  { id: "grading", label: "Grading scales", icon: "list", perm: ["grading.manage"], fn: () => gradingTab },
  { id: "settings", label: "Settings and branding", icon: "settings", perm: ["settings.manage"], fn: () => settingsTab },
  { id: "audit", label: "Audit log", icon: "shield", perm: ["audit.view"], fn: () => auditTab },
  { id: "backups", label: "Backups", icon: "database", perm: ["backups.manage"], fn: () => backupsTab },
];

export async function render(ctx, view, params) {
  const avail = TABS.filter((t) => ctx.canAny(...t.perm));
  let active = avail.find((t) => t.id === params[0])?.id || avail[0]?.id;
  if (!active) return mount(view, pageHead("Administration"), card(null, empty("No access", "Your account has no administration permissions.", "shield")));
  const nav = h("div"), panel = h("div", { class: "view" });
  const drawNav = () => mount(nav, tabs(avail.map((t) => ({ id: t.id, label: t.label, icon: t.icon })), active, (id) => { location.hash = `#/admin/${id}`; }));
  mount(view, pageHead("Administration", "Accounts, permissions, school setup, settings, audit trail and backups."), nav, panel);
  drawNav();
  await avail.find((t) => t.id === active).fn()(ctx, panel);
}

const yesNo = (v) => (v ? badge("Active", "good") : badge("Inactive", ""));
const dlg = (title, form, submitLabel, onSubmit, size = "md") => {
  const m = modal({ title, size, body: form, actions: [h("button", { class: "btn", type: "button", onclick: () => m.close() }, "Cancel"), button(submitLabel, { kind: "primary", onClick: async () => {
    applyErrors(form, null);
    try { await onSubmit(m); } catch (e) { applyErrors(form, e); if (!(e instanceof ApiError) || !e.fields) errorToast(e); }
  } })] });
  form.addEventListener("submit", (e) => e.preventDefault());
  return m;
};
const val = (f, k) => f[k].querySelector("input,select,textarea");
const ck = (label, checked) => { const cb = h("input", { type: "checkbox", checked: !!checked }); return { cb, node: h("label", { class: "check" }, cb, label) }; };

// ============================================================ users and roles
async function usersTab(ctx, root) {
  const canUsers = ctx.can("users.manage"), canRoles = ctx.can("roles.manage");
  const me = ctx.user;
  const box = h("div", { class: "stack" });
  mount(root, box);
  async function draw() {
    await load(box, async () => {
      const [u, r] = await Promise.all([canUsers ? get("/api/users") : { users: [] }, get("/api/roles")]);
      const roles = r.roles;
      const perms = (await get("/api/permissions")).permissions;
      const usersCard = canUsers ? card("User accounts", dataTable({ rows: u.users, sortKey: "full_name", columns: [
        { key: "full_name", label: "Name", render: (x) => h("div", null, h("b", null, x.full_name), x.is_demo ? " " : null, x.is_demo ? badge("Demo", "warn") : null, h("div", { class: "tiny muted" }, x.email || "")) },
        { key: "username", label: "Username" },
        { key: "role_label", label: "Role", render: (x) => badge(x.role_label, x.role === "super_admin" ? "bad" : x.role === "headteacher" ? "info" : "") },
        { key: "staff_id", label: "Teacher ID", render: (x) => x.staff_id || h("span", { class: "muted" }, "-") },
        { key: "is_active", label: "Status", render: (x) => yesNo(x.is_active) },
        { key: "last_login_at", label: "Last sign-in", render: (x) => (x.last_login_at ? ago(x.last_login_at) : h("span", { class: "muted" }, "Never")) },
        { key: "act", label: "", sortable: false, render: (x) => h("div", { class: "row", style: { flexWrap: "nowrap" } }, button("Edit", { sm: true, ico: "edit", onClick: () => userDialog(ctx, roles, x, draw) }), button("Reset password", { sm: true, ico: "key", onClick: () => resetPw(x) })) },
      ], empty: empty("No users", "", "users") }), { flush: true, actions: button("Add user", { kind: "primary", ico: "plus", sm: true, onClick: () => userDialog(ctx, roles, null, draw) }) }) : null;
      const rolesCard = card("Roles and permissions", h("div", { class: "stack-sm" }, notice("Permissions are enforced on the server for every request. Hiding a button is never the only protection.", "", "shield"),
        dataTable({ rows: roles, sortKey: "label", columns: [
          { key: "label", label: "Role", render: (x) => h("div", null, h("b", null, x.label), h("div", { class: "tiny muted" }, x.description || "")) },
          { key: "is_system", label: "Type", render: (x) => (x.is_system ? badge("Built in", "info") : badge("Custom", "")) },
          { key: "user_count", label: "Users", align: "right" },
          { key: "permissions", label: "Permissions", align: "right", sortValue: (x) => x.permissions.length, render: (x) => `${x.permissions.length} of ${perms.length}` },
          { key: "act", label: "", sortable: false, render: (x) => canRoles ? h("div", { class: "row", style: { flexWrap: "nowrap" } }, x.name === "super_admin" ? button("View", { sm: true, ico: "eye", onClick: () => roleDialog(perms, x, draw, true) }) : button("Edit", { sm: true, ico: "edit", onClick: () => roleDialog(perms, x, draw) }),
            !x.is_system ? button("Delete", { sm: true, ico: "trash", onClick: async () => { if (!(await confirmDialog({ title: "Delete role?", message: `${x.label} will be removed.`, confirmText: "Delete", danger: true }))) return; try { await del(`/api/roles/${x.id}`); toast("Role deleted.", "success"); draw(); } catch (e) { errorToast(e); } } }) : null) : null },
        ] })), { actions: canRoles ? button("New role", { sm: true, ico: "plus", onClick: () => roleDialog(perms, null, draw) }) : null });
      return h("div", { class: "stack" }, usersCard, rolesCard);
    });
  }
  await draw();
}

function userDialog(ctx, roles, u, done) {
  const isNew = !u;
  const f = {
    username: named("username", field("Username", input({ value: u?.username || "", autocomplete: "off", disabled: !isNew }), { required: true, hint: isNew ? "Letters, numbers, dots, dashes, underscores." : "Usernames cannot be changed." })),
    full_name: named("full_name", field("Full name", input({ value: u?.full_name || "" }), { required: true })),
    email: named("email", field("Email", input({ type: "email", value: u?.email || "" }))),
    role_id: named("role_id", field("Role", select(roles.map((r) => [r.id, r.label]), u?.role_id || roles.find((r) => r.name === "teacher")?.id), { required: true })),
    phone: named("phone", field("Phone", input({ value: u?.phone || "" }))),
    staff_id: named("staff_id", field("Teacher ID", input({ value: u?.staff_id || "", placeholder: "Generated if left empty" }))),
  };
  if (isNew) f.password = named("password", field("Password", input({ type: "text", autocomplete: "off", placeholder: "Leave empty to generate a temporary password" }), { hint: "The user must change it at first sign-in." }));
  const teacher = ck("This person is a teacher (can be assigned to classes and subjects)", u ? !!u.teacher_id : true), active = ck("Account is active", u ? u.is_active : true);
  const form = h("form", { class: "stack", novalidate: true }, h("div", { class: "form-grid" }, ...Object.values(f)), teacher.node, !isNew ? active.node : null);
  dlg(isNew ? "Add user" : `Edit ${u.full_name}`, form, isNew ? "Create user" : "Save changes", async (m) => {
    const body = { full_name: val(f, "full_name").value, email: val(f, "email").value, role_id: Number(val(f, "role_id").value), phone: val(f, "phone").value, staff_id: val(f, "staff_id").value, is_teacher: teacher.cb.checked };
    if (isNew) {
      body.username = val(f, "username").value; if (val(f, "password").value) body.password = val(f, "password").value;
      const r = await post("/api/users", body); m.close(); done();
      if (r.temporary_password) tempPassword(body.username, r.temporary_password); else toast("User created.", "success");
    } else { body.is_active = active.cb.checked; await put(`/api/users/${u.id}`, body); m.close(); toast("User updated.", "success"); done(); }
  }, "lg");
}

function tempPassword(username, pw) {
  const m = modal({ title: "Temporary password", size: "sm", body: h("div", { class: "stack-sm" }, h("p", null, `Give this to ${username} securely. It is shown only once, and they must change it at their first sign-in.`), h("div", { class: "notice", style: { fontFamily: "monospace", fontSize: "1.15rem", userSelect: "all" } }, pw)),
    actions: [button("Copy", { ico: "copy", onClick: async () => { try { await navigator.clipboard.writeText(pw); toast("Copied.", "success"); } catch { toast("Copy failed. Select the text manually.", "warn"); } } }), button("Done", { kind: "primary", onClick: () => m.close() })] });
}

async function resetPw(u) {
  if (!(await confirmDialog({ title: "Reset password?", message: `A new temporary password will be created for ${u.full_name}. Their current sessions will be signed out.`, confirmText: "Reset password" }))) return;
  try { const r = await post(`/api/users/${u.id}/reset-password`, {}); tempPassword(u.username, r.temporary_password); } catch (e) { errorToast(e); }
}

function roleDialog(perms, role, done, readOnly = false) {
  const f = {
    label: named("label", field("Role name", input({ value: role?.label || "", disabled: !!role?.is_system }), { required: true })),
    description: named("description", field("Description", input({ value: role?.description || "", disabled: !!role?.is_system }))),
  };
  const has = new Set(role?.permissions || []);
  const groups = [...new Set(perms.map((p) => p.group))];
  const boxes = new Map();
  const sections = groups.map((g) => h("fieldset", { class: "stack-sm", style: { border: "1px solid var(--border)", borderRadius: "10px", padding: "10px 14px" } }, h("legend", { class: "small" }, h("b", null, g)),
    perms.filter((p) => p.group === g).map((p) => { const c = ck(p.label, has.has(p.code)); c.cb.disabled = readOnly; boxes.set(p.code, c.cb); return c.node; })));
  const form = h("form", { class: "stack", novalidate: true }, role?.is_system ? null : h("div", { class: "form-grid" }, ...Object.values(f)), readOnly ? notice("Super Administrators always hold every permission.", "", "info") : null, h("div", { class: "grid g2" }, sections));
  const m = modal({ title: role ? `${readOnly ? "Permissions" : "Edit role"}: ${role.label}` : "New role", size: "lg", body: form, actions: [h("button", { class: "btn", type: "button", onclick: () => m.close() }, "Close"), readOnly ? null : button("Save role", { kind: "primary", onClick: async () => {
    applyErrors(form, null);
    const body = { permissions: [...boxes].filter(([, cb]) => cb.checked).map(([c]) => c) };
    if (!role?.is_system) { body.label = val(f, "label").value; body.description = val(f, "description").value; }
    try { role ? await put(`/api/roles/${role.id}`, body) : await post("/api/roles", body); m.close(); toast("Role saved.", "success"); done(); } catch (e) { applyErrors(form, e); if (!(e instanceof ApiError) || !e.fields) errorToast(e); }
  } })] });
}

// ============================================================ assignments
async function assignmentsTab(ctx, root) {
  const box = h("div");
  mount(root, box);
  async function draw() {
    await load(box, async () => {
      const [a, t, c] = await Promise.all([get("/api/assignments"), get("/api/teachers"), get("/api/classes")]);
      const cls = c.classes.filter((x) => x.is_active);
      const noTeacher = cls.filter((x) => !a.assignments.some((y) => y.class_id === x.id && y.is_class_teacher));
      return h("div", { class: "stack" },
        notice("The class teacher records attendance for the class. A subject teacher is responsible for marks in that subject. Teachers see only the classes and subjects assigned here.", "", "info"),
        noTeacher.length ? notice(`No class teacher yet: ${noTeacher.map((x) => x.name).join(", ")}.`, "warn", "alert") : null,
        card("Teacher assignments", dataTable({ rows: a.assignments, sortKey: "class_name", columns: [
          { key: "class_name", label: "Class" }, { key: "teacher_name", label: "Teacher", render: (x) => h("div", null, x.teacher_name, h("div", { class: "tiny muted" }, x.staff_id)) },
          { key: "role", label: "Responsibility", sortValue: (x) => (x.is_class_teacher ? 0 : 1), render: (x) => (x.is_class_teacher ? badge("Class teacher", "info", "users") : badge(x.subject_name, "")) },
          { key: "act", label: "", sortable: false, render: (x) => button("Remove", { sm: true, ico: "trash", onClick: async () => { if (!(await confirmDialog({ title: "Remove assignment?", message: `${x.teacher_name} will lose access to ${x.class_name}${x.subject_name ? ` (${x.subject_name})` : ""} unless assigned elsewhere.`, confirmText: "Remove", danger: true }))) return; try { await del(`/api/assignments/${x.id}`); toast("Assignment removed.", "success"); draw(); } catch (e) { errorToast(e); } } }) },
        ], empty: empty("No assignments yet", "Assign teachers to classes so they can record attendance and marks.", "swap") }), { flush: true, actions: button("Assign teacher", { kind: "primary", sm: true, ico: "plus", onClick: () => assignDialog(ctx, t.teachers.filter((x) => x.is_active), cls, draw) }) }));
    });
  }
  await draw();
}

function assignDialog(ctx, teachers, classes, done) {
  if (!teachers.length) return toast("Create a teacher account first (Users and permissions).", "warn", 6000);
  const subjOf = (cid) => (classes.find((c) => String(c.id) === String(cid))?.subject_ids || []).map((id) => ctx.meta.subjects.find((s) => s.id === id)).filter(Boolean);
  const f = {
    teacher_id: named("teacher_id", field("Teacher", select(teachers.map((t) => [t.id, `${t.full_name} (${t.staff_id})`]), teachers[0].id), { required: true })),
    class_id: named("class_id", field("Class", select(classes.map((c) => [c.id, c.name]), classes[0]?.id), { required: true })),
    subject_id: named("subject_id", field("Subject", select([], ""), { required: true })),
  };
  const cls = ck("Class teacher (records attendance for the whole class)", false);
  const fillSubjects = () => { const s = val(f, "subject_id"); mount(s, ...subjOf(val(f, "class_id").value).map((x) => h("option", { value: x.id }, x.name))); f.subject_id.style.display = cls.cb.checked ? "none" : ""; };
  val(f, "class_id").addEventListener("change", fillSubjects); cls.cb.addEventListener("change", fillSubjects); fillSubjects();
  const form = h("form", { class: "stack", novalidate: true }, ...Object.values(f), cls.node);
  dlg("Assign teacher", form, "Assign", async (m) => {
    await post("/api/assignments", { teacher_id: Number(val(f, "teacher_id").value), class_id: Number(val(f, "class_id").value), is_class_teacher: cls.cb.checked, subject_id: cls.cb.checked ? null : Number(val(f, "subject_id").value) || null });
    m.close(); toast("Teacher assigned.", "success"); await ctx.refreshMeta?.(); done();
  }, "sm");
}

// ============================================================ school setup
async function setupTab(ctx, root) {
  const box = h("div", { class: "stack" });
  mount(root, box);
  async function draw() {
    await load(box, async () => {
      const [y, c, s] = await Promise.all([get("/api/years"), get("/api/classes"), get("/api/subjects")]);
      await ctx.refreshMeta?.();
      const after = async () => { await draw(); };
      const yearsCard = card("Academic years and terms", h("div", { class: "stack" }, y.years.length ? y.years.map((yr) => h("div", { class: "stack-sm", style: { borderBottom: "1px solid var(--border)", paddingBottom: "12px" } },
        h("div", { class: "row between" }, h("div", { class: "row" }, h("b", null, yr.name), yr.is_current ? badge("Current", "good", "check") : null, h("span", { class: "small muted" }, `${fmtDate(yr.start_date)} to ${fmtDate(yr.end_date)}`)),
          h("div", { class: "row" }, !yr.is_current ? button("Make current", { sm: true, onClick: async () => { try { await post(`/api/years/${yr.id}/set-current`, {}); toast("Current year updated.", "success"); after(); } catch (e) { errorToast(e); } } }) : null,
            button("Edit", { sm: true, ico: "edit", onClick: () => yearDialog(yr, after) }),
            button("Add term", { sm: true, ico: "plus", onClick: () => termDialog(y.years, yr, null, after) }),
            button("", { sm: true, ico: "trash", title: "Delete year", onClick: async () => { if (!(await confirmDialog({ title: "Delete academic year?", message: `${yr.name} and its terms will be deleted. This only works if nothing uses them.`, confirmText: "Delete", danger: true }))) return; try { await del(`/api/years/${yr.id}`); toast("Year deleted.", "success"); after(); } catch (e) { errorToast(e); } } }))),
        yr.terms.length ? h("div", { class: "pill-row" }, yr.terms.map((t) => h("span", { class: "badge " + (t.is_current ? "good" : "info"), style: { gap: "6px" } }, `${t.name}: ${fmtDate(t.start_date)} to ${fmtDate(t.end_date)}`,
          !t.is_current ? h("button", { class: "linklike", type: "button", title: "Make current term", onclick: async () => { try { await post(`/api/terms/${t.id}/set-current`, {}); toast("Current term updated.", "success"); after(); } catch (e) { errorToast(e); } } }, "set current") : h("span", null, "(current)"),
          h("button", { class: "linklike", type: "button", onclick: () => termDialog(y.years, yr, t, after) }, "edit"),
          h("button", { class: "linklike", type: "button", onclick: async () => { if (!(await confirmDialog({ title: "Delete term?", message: `${t.name} will be deleted if nothing uses it.`, confirmText: "Delete", danger: true }))) return; try { await del(`/api/terms/${t.id}`); toast("Term deleted.", "success"); after(); } catch (e) { errorToast(e); } } }, "delete")))) : h("div", { class: "small muted" }, "No terms yet."))) : empty("No academic years", "Add an academic year, then its terms. Examinations belong to terms.", "calendar")),
        { actions: button("Add academic year", { kind: "primary", sm: true, ico: "plus", onClick: () => yearDialog(null, after) }) });
      const classesCard = card("Classes", dataTable({ rows: c.classes, sortKey: "name", columns: [
        { key: "name", label: "Class" }, { key: "level", label: "Level", render: (x) => x.level || h("span", { class: "muted" }, "-") }, { key: "student_count", label: "Students", align: "right" },
        { key: "subjects", label: "Subjects", sortValue: (x) => x.subject_ids.length, render: (x) => `${x.subject_ids.length}` }, { key: "is_active", label: "Status", render: (x) => yesNo(x.is_active) },
        { key: "act", label: "", sortable: false, render: (x) => h("div", { class: "row", style: { flexWrap: "nowrap" } }, button("Edit", { sm: true, ico: "edit", onClick: () => classDialog(x, after) }), button("Subjects", { sm: true, ico: "list", onClick: () => classSubjects(x, s.subjects, after) }),
          button("", { sm: true, ico: "trash", title: "Delete class", onClick: async () => { if (!(await confirmDialog({ title: "Delete class?", message: `${x.name} can only be deleted if it has no students or records. Otherwise deactivate it by editing.`, confirmText: "Delete", danger: true }))) return; try { await del(`/api/classes/${x.id}`); toast("Class deleted.", "success"); after(); } catch (e) { errorToast(e); } } })) },
      ], empty: empty("No classes", "", "school") }), { flush: true, actions: button("Add class", { kind: "primary", sm: true, ico: "plus", onClick: () => classDialog(null, after) }) });
      const subjectsCard = card("Subjects", dataTable({ rows: s.subjects, sortKey: "name", columns: [
        { key: "name", label: "Subject" }, { key: "code", label: "Code", render: (x) => x.code || h("span", { class: "muted" }, "-") }, { key: "is_active", label: "Status", render: (x) => yesNo(x.is_active) },
        { key: "act", label: "", sortable: false, render: (x) => h("div", { class: "row", style: { flexWrap: "nowrap" } }, button("Edit", { sm: true, ico: "edit", onClick: () => subjectDialog(x, after) }),
          button("", { sm: true, ico: "trash", title: "Delete subject", onClick: async () => { if (!(await confirmDialog({ title: "Delete subject?", message: `${x.name} can only be deleted if it is not used. Otherwise deactivate it by editing.`, confirmText: "Delete", danger: true }))) return; try { await del(`/api/subjects/${x.id}`); toast("Subject deleted.", "success"); after(); } catch (e) { errorToast(e); } } })) },
      ], empty: empty("No subjects", "", "list") }), { flush: true, actions: button("Add subject", { kind: "primary", sm: true, ico: "plus", onClick: () => subjectDialog(null, after) }) });
      return h("div", { class: "stack" }, yearsCard, h("div", { class: "grid g2" }, classesCard, subjectsCard));
    });
  }
  await draw();
}

function yearDialog(y, done) {
  const f = { name: named("name", field("Name", input({ value: y?.name || "", placeholder: "e.g. 2026/2027" }), { required: true })), start_date: named("start_date", field("Starts", input({ type: "date", value: y?.start_date || "" }), { required: true })), end_date: named("end_date", field("Ends", input({ type: "date", value: y?.end_date || "" }), { required: true })) };
  const cur = ck("Make this the current year", false);
  const form = h("form", { class: "stack", novalidate: true }, ...Object.values(f), !y ? cur.node : null);
  dlg(y ? "Edit academic year" : "Add academic year", form, "Save", async (m) => {
    const b = { name: val(f, "name").value, start_date: val(f, "start_date").value, end_date: val(f, "end_date").value };
    y ? await put(`/api/years/${y.id}`, b) : await post("/api/years", { ...b, is_current: cur.cb.checked });
    m.close(); toast("Saved.", "success"); done();
  }, "sm");
}
function termDialog(years, year, t, done) {
  const f = { name: named("name", field("Term name", input({ value: t?.name || "", placeholder: "e.g. Term 1" }), { required: true })), start_date: named("start_date", field("Starts", input({ type: "date", value: t?.start_date || "" }), { required: true })), end_date: named("end_date", field("Ends", input({ type: "date", value: t?.end_date || "" }), { required: true })) };
  const cur = ck("Make this the current term", false);
  const form = h("form", { class: "stack", novalidate: true }, h("p", { class: "muted" }, `Academic year: ${year.name} (${fmtDate(year.start_date)} to ${fmtDate(year.end_date)})`), ...Object.values(f), !t ? cur.node : null);
  dlg(t ? "Edit term" : "Add term", form, "Save", async (m) => {
    const b = { year_id: year.id, name: val(f, "name").value, start_date: val(f, "start_date").value, end_date: val(f, "end_date").value };
    t ? await put(`/api/terms/${t.id}`, b) : await post("/api/terms", { ...b, is_current: cur.cb.checked });
    m.close(); toast("Saved.", "success"); done();
  }, "sm");
}
function classDialog(c, done) {
  const f = { name: named("name", field("Class name", input({ value: c?.name || "", placeholder: "e.g. Primary 5" }), { required: true })), level: named("level", field("Level", input({ value: c?.level || "", placeholder: "e.g. Primary" }))) };
  const act = ck("Class is active", c ? c.is_active : true);
  const form = h("form", { class: "stack", novalidate: true }, ...Object.values(f), c ? act.node : null);
  dlg(c ? "Edit class" : "Add class", form, "Save", async (m) => {
    const b = { name: val(f, "name").value, level: val(f, "level").value };
    c ? await put(`/api/classes/${c.id}`, { ...b, is_active: act.cb.checked }) : await post("/api/classes", b);
    m.close(); toast("Saved.", "success"); done();
  }, "sm");
}
function subjectDialog(s, done) {
  const f = { name: named("name", field("Subject name", input({ value: s?.name || "" }), { required: true })), code: named("code", field("Code", input({ value: s?.code || "", maxlength: 12 }))) };
  const act = ck("Subject is active", s ? s.is_active : true);
  const form = h("form", { class: "stack", novalidate: true }, ...Object.values(f), s ? act.node : null);
  dlg(s ? "Edit subject" : "Add subject", form, "Save", async (m) => {
    const b = { name: val(f, "name").value, code: val(f, "code").value };
    s ? await put(`/api/subjects/${s.id}`, { ...b, is_active: act.cb.checked }) : await post("/api/subjects", b);
    m.close(); toast("Saved.", "success"); done();
  }, "sm");
}
function classSubjects(c, subjects, done) {
  const has = new Set(c.subject_ids);
  const boxes = subjects.filter((s) => s.is_active || has.has(s.id)).map((s) => ({ s, ...ck(s.name, has.has(s.id)) }));
  const form = h("form", { class: "stack-sm" }, boxes.length ? boxes.map((b) => b.node) : h("p", { class: "muted" }, "Add subjects first."));
  dlg(`Subjects taught in ${c.name}`, form, "Save subjects", async (m) => { await put(`/api/classes/${c.id}/subjects`, { subject_ids: boxes.filter((b) => b.cb.checked).map((b) => b.s.id) }); m.close(); toast("Subjects updated.", "success"); done(); }, "sm");
}

// ============================================================ grading
async function gradingTab(ctx, root) {
  const box = h("div");
  mount(root, box);
  async function draw() {
    await load(box, async () => {
      const r = await get("/api/grading");
      await ctx.refreshMeta?.();
      return h("div", { class: "stack" }, notice("Grades are calculated from the active scale. Changing the scale changes how results display everywhere, but never changes saved marks.", "", "info"),
        h("div", { class: "row" }, button("New grading scale", { kind: "primary", ico: "plus", onClick: () => scaleDialog(null, draw) })),
        r.scales.map((s) => card(h("span", { class: "row" }, s.name, s.is_active ? badge("Active", "good", "check") : null),
          dataTable({ rows: s.bands, columns: [{ key: "min_percent", label: "From (%)", align: "right" }, { key: "grade", label: "Grade", render: (b) => h("b", null, b.grade) }, { key: "remark", label: "Remark" }, { key: "is_pass", label: "Result", render: (b) => (b.is_pass ? badge("Pass", "good") : badge("Fail", "bad")) }] }),
          { flush: true, actions: h("div", { class: "row" }, !s.is_active ? button("Make active", { sm: true, onClick: async () => { try { await post(`/api/grading/scales/${s.id}/activate`, {}); toast("Grading scale activated.", "success"); draw(); } catch (e) { errorToast(e); } } }) : null,
            button("Edit", { sm: true, ico: "edit", onClick: () => scaleDialog(s, draw) }),
            !s.is_active ? button("Delete", { sm: true, ico: "trash", onClick: async () => { if (!(await confirmDialog({ title: "Delete grading scale?", message: `${s.name} will be deleted.`, confirmText: "Delete", danger: true }))) return; try { await del(`/api/grading/scales/${s.id}`); toast("Scale deleted.", "success"); draw(); } catch (e) { errorToast(e); } } }) : null) })));
    });
  }
  await draw();
}

function scaleDialog(s, done) {
  const name = named("name", field("Scale name", input({ value: s?.name || "" }), { required: true }));
  const bands = (s?.bands || [{ min_percent: 50, grade: "P", remark: "Pass", is_pass: 1 }, { min_percent: 0, grade: "F", remark: "Fail", is_pass: 0 }]).map((b) => ({ ...b }));
  const list = h("div", { class: "stack-sm" });
  const act = ck("Make this the active scale", false);
  const draw = () => mount(list, bands.map((b, i) => h("div", { class: "row", style: { flexWrap: "nowrap", alignItems: "flex-end" } },
    field("From %", input({ type: "number", min: "0", max: "100", step: "0.5", value: b.min_percent, style: { width: "90px" }, oninput: (e) => { b.min_percent = e.target.value; } })),
    field("Grade", input({ value: b.grade, maxlength: 6, style: { width: "80px" }, oninput: (e) => { b.grade = e.target.value; } })),
    field("Remark", input({ value: b.remark || "", maxlength: 40, oninput: (e) => { b.remark = e.target.value; } })),
    h("label", { class: "check", style: { paddingBottom: "10px" } }, h("input", { type: "checkbox", checked: !!b.is_pass, onchange: (e) => { b.is_pass = e.target.checked ? 1 : 0; } }), "Pass"),
    bands.length > 1 ? button("", { sm: true, ico: "trash", title: "Remove band", onClick: () => { bands.splice(i, 1); draw(); } }) : null)));
  draw();
  const form = h("form", { class: "stack", novalidate: true }, name, h("div", null, h("div", { class: "row between" }, h("h3", null, "Grade bands"), button("Add band", { sm: true, ico: "plus", onClick: () => { bands.push({ min_percent: 0, grade: "", remark: "", is_pass: 0 }); draw(); } })), list, h("div", { class: "hint" }, "Each band starts at its minimum percentage. A score takes the highest band it reaches. Include a band starting at 0.")), !s ? act.node : null);
  dlg(s ? `Edit ${s.name}` : "New grading scale", form, "Save scale", async (m) => {
    const body = { name: val({ name }, "name").value, bands: bands.map((b) => ({ min_percent: Number(b.min_percent), grade: b.grade, remark: b.remark, is_pass: !!b.is_pass })) };
    s ? await put(`/api/grading/scales/${s.id}`, body) : await post("/api/grading/scales", { ...body, activate: act.cb.checked });
    m.close(); toast("Grading scale saved.", "success"); done();
  }, "lg");
}

// ============================================================ settings, branding, demo data
async function settingsTab(ctx, root) {
  const box = h("div", { class: "stack" });
  mount(root, box);
  async function draw() {
    await load(box, async () => {
      const [r, demo] = await Promise.all([get("/api/settings"), get("/api/demo/status")]);
      const groups = [...new Set(r.settings.map((s) => s.group))], controls = new Map();
      const ctl = (s) => {
        const c = s.type === "bool" ? h("input", { type: "checkbox", checked: !!s.value }) : s.type === "time" ? input({ type: "time", value: s.value }) : s.type === "str" ? input({ value: s.value ?? "" }) : input({ type: "number", step: s.type === "float" ? "0.5" : "1", min: "0", value: s.value });
        controls.set(s.key, { c, s }); return s.type === "bool" ? h("label", { class: "check" }, c, s.label, s.help ? h("span", { class: "hint" }, s.help) : null) : named(s.key, field(s.label, c, { hint: s.help }));
      };
      const form = h("form", { class: "stack", novalidate: true }, groups.map((g) => h("fieldset", { class: "stack-sm", style: { border: "1px solid var(--border)", borderRadius: "10px", padding: "12px 16px" } }, h("legend", null, h("b", null, g)), h("div", { class: "form-grid" }, r.settings.filter((s) => s.group === g).map(ctl)))));
      form.addEventListener("submit", (e) => e.preventDefault());
      const save = button("Save settings", { kind: "primary", ico: "check", onClick: async () => {
        applyErrors(form, null);
        const values = {}; controls.forEach(({ c, s }, k) => { values[k] = s.type === "bool" ? c.checked : c.value; });
        try { await put("/api/settings", { values }); toast("Settings saved. Reloading to apply them.", "success"); setTimeout(() => location.reload(), 700); } catch (e) { applyErrors(form, e); if (!(e instanceof ApiError) || !e.fields) errorToast(e); }
      } });
      const logoCard = card("School logo", h("div", { class: "row" }, ctx.school?.has_logo ? h("img", { src: "/api/auth/school-logo?v=" + Date.now(), alt: "Current logo", style: { height: "64px", background: "#fff", borderRadius: "8px", padding: "4px", border: "1px solid var(--border)" } }) : h("div", { class: "muted" }, "No logo uploaded."),
        (() => { const file = h("input", { type: "file", accept: "image/png,image/jpeg,image/webp", class: "input", "aria-label": "Choose logo image" }); return h("div", { class: "row" }, file, button("Upload logo", { ico: "upload", onClick: async () => { if (!file.files[0]) return toast("Choose an image first.", "warn"); const fd = new FormData(); fd.append("logo", file.files[0]); try { await upload("/api/settings/logo", fd); toast("Logo updated. Reloading.", "success"); setTimeout(() => location.reload(), 600); } catch (e) { errorToast(e); } } })); })(),
        ctx.school?.has_logo ? button("Remove logo", { ico: "trash", onClick: async () => { try { await del("/api/settings/logo"); toast("Logo removed. Reloading.", "success"); setTimeout(() => location.reload(), 600); } catch (e) { errorToast(e); } } }) : null));
      const demoCard = card("Demonstration data", demo.present ? h("div", { class: "stack-sm" }, notice(`Demonstration data is present: ${demo.counts.students} students, ${demo.counts.teachers} accounts, ${demo.counts.classes} classes, ${demo.counts.examinations} examinations. It is fictional and labelled "Demo". Remove it before real use.`, "warn", "alert"),
        button("Remove demonstration data", { kind: "danger", ico: "trash", onClick: () => purgeDemo(draw) })) : h("p", { class: "muted" }, "No demonstration data is in this database."));
      return h("div", { class: "stack" }, logoCard, card("School settings", h("div", { class: "stack" }, form, h("div", null, save))), demoCard);
    });
  }
  await draw();
}

async function purgeDemo(done) {
  const ok = await confirmDialog({ title: "Remove demonstration data?", message: "All records marked as demonstration data (students, attendance, examinations, demo accounts) will be deleted permanently. Real records are not touched. Take a backup first if unsure.", confirmText: "Remove demo data", danger: true, requireText: "REMOVE DEMO DATA" });
  if (!ok) return;
  try { const r = await post("/api/demo/purge", { confirm: "REMOVE DEMO DATA" }); toast(`Demonstration data removed (${Object.values(r.removed).reduce((a, b) => a + (typeof b === "number" ? b : 0), 0)} records).`, "success", 6000); await ctx_refresh(); done(); } catch (e) { errorToast(e); }
}
const ctx_refresh = async () => { /* meta is reloaded by the next page draw */ };

// ============================================================ audit log
async function auditTab(ctx, root) {
  const q = input({ type: "search", placeholder: "Search user, action or detail", "aria-label": "Search audit log" });
  const action = select([["", "All actions"], ["auth.", "Sign-ins"], ["user.", "Users"], ["student.", "Students"], ["attendance.", "Attendance"], ["marks.", "Marks"], ["exam.", "Examinations"], ["report.", "Reports"], ["settings.", "Settings"], ["backup.", "Backups"]], "");
  const from = input({ type: "date" }), to = input({ type: "date" });
  const out = h("div"); let page = 1;
  const draw = () => load(out, async () => {
    const r = await get("/api/audit", { q: q.value, action: action.value, from: from.value, to: to.value, page, per_page: 50 });
    const pages = Math.max(Math.ceil(r.total / r.per_page), 1);
    return card(`${fmtNum(r.total)} entries`, h("div", null, dataTable({ rows: r.items, server: true, columns: [
      { key: "created_at", label: "When", render: (x) => h("span", { title: x.created_at }, fmtDateTime(x.created_at)) }, { key: "actor_name", label: "Who", render: (x) => x.actor_name || h("span", { class: "muted" }, "System") },
      { key: "action", label: "Action", render: (x) => h("code", null, x.action) }, { key: "entity", label: "Record", render: (x) => (x.entity_type ? `${x.entity_type}${x.entity_id ? " #" + x.entity_id : ""}` : "") },
      { key: "details", label: "Details", render: (x) => h("span", { class: "small", style: { wordBreak: "break-word" } }, x.details ? String(x.details).slice(0, 240) : "") }, { key: "ip", label: "IP" }], empty: empty("No entries", "Nothing matches these filters.", "shield") }),
      h("div", { class: "row between", style: { padding: "12px 16px" } }, h("span", { class: "small muted" }, `Page ${page} of ${pages}`), h("div", { class: "row" }, button("Previous", { sm: true, disabled: page <= 1, onClick: () => { page--; draw(); } }), button("Next", { sm: true, disabled: page >= pages, onClick: () => { page++; draw(); } })))), { flush: true });
  });
  const go = () => { page = 1; draw(); };
  q.addEventListener("input", debounce(go, 300)); [action, from, to].forEach((x) => x.addEventListener("change", go));
  mount(root, h("div", { class: "toolbar" }, field("Search", q), field("Action", action), field("From", from), field("To", to)), out);
  await draw();
}

// ============================================================ backups
async function backupsTab(ctx, root) {
  const box = h("div");
  mount(root, box);
  const size = (n) => (n > 1048576 ? `${(n / 1048576).toFixed(1)} MB` : `${Math.max(Math.round(n / 1024), 1)} KB`);
  async function draw() {
    await load(box, async () => {
      const r = await get("/api/backups");
      return h("div", { class: "stack" }, notice(`${r.auto ? "A backup is made automatically once a day." : "Automatic daily backups are off."} The newest ${r.keep} backups are kept. Store copies off this server too. To restore a backup, stop the app and run: python manage.py restore <file>.`, "", "database"),
        card("Database backups", dataTable({ rows: r.backups, columns: [{ key: "name", label: "File", render: (b) => h("code", null, b.name) }, { key: "created_at", label: "Created", render: (b) => fmtDateTime(b.created_at) }, { key: "size", label: "Size", align: "right", render: (b) => size(b.size) },
          { key: "act", label: "", sortable: false, render: (b) => button("Download", { sm: true, ico: "download", onClick: async () => { try { await download(`/api/backups/${b.name}/download`, {}, b.name); } catch (e) { errorToast(e); } } }) }], empty: empty("No backups yet", "Create the first backup now.", "database") }),
          { flush: true, actions: button("Back up now", { kind: "primary", sm: true, ico: "database", onClick: async (e) => { const b = e.currentTarget; b.disabled = true; try { await post("/api/backups", {}); toast("Backup created.", "success"); draw(); } catch (err) { errorToast(err); b.disabled = false; } } }) }));
    });
  }
  await draw();
}
