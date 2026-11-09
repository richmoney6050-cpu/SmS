// Module 1: Manage Students.
import { ApiError, del, download, get, post, put, upload } from "../lib/api.js";
import { barChart, lineChart } from "../lib/charts.js";
import { applyErrors, badge, button, card, cap, confirmDialog, dataTable, debounce, empty, errorToast, field, fmtDate, fmtNum, fmtPct, h, icon, initials, input, load, modal, mount, named, notice, pageHead, rateBar, select, stat, tabs, textarea, toast, ord } from "../lib/ui.js";
import { attendanceMark, backLink, classOptions, gradeBadge, statusPill, yearOptions } from "./common.js";

const STATUS_TONE = { active: "good", inactive: "warn", transferred: "info", graduated: "info", withdrawn: "bad", archived: "" };

export async function render(ctx, view, params) {
  return params[0] ? profile(ctx, view, Number(params[0])) : list(ctx, view);
}

const avatar = (s, size = 38) => (s.has_photo
  ? h("img", { src: `/api/students/${s.id}/photo?v=${encodeURIComponent(s.updated_at || "")}`, alt: "", style: { width: size + "px", height: size + "px", borderRadius: "50%", objectFit: "cover", flex: "none" }, loading: "lazy", onerror: (e) => { e.target.replaceWith(h("span", { class: "avatar", style: { width: size + "px", height: size + "px" } }, initials(s.full_name))); } })
  : h("span", { class: "avatar", style: { width: size + "px", height: size + "px", fontSize: size > 50 ? "1.5rem" : ".85rem" } }, initials(s.full_name)));

// ------------------------------------------------------------ list
async function list(ctx, view) {
  const meta = ctx.meta, q0 = ctx.query();
  const st = { q: "", class_id: q0.get("class") || "", gender: "", year_id: "", status: "active", sort: "name", dir: "asc", page: 1, per_page: 25 };
  const search = input({ type: "search", placeholder: "Search by name, student ID or class", "aria-label": "Search students" });
  const cls = select(classOptions(meta), st.class_id), gen = select([["", "Any gender"], ["male", "Male"], ["female", "Female"], ["other", "Other"]], "");
  const yr = select(yearOptions(meta), ""), stat_ = select([["active", "Active"], ["inactive", "Inactive"], ["transferred", "Transferred"], ["graduated", "Graduated"], ["withdrawn", "Withdrawn"], ["archived", "Archived"], ["", "Any status"]], "active");
  const out = h("div");
  const exp = (format) => () => download("/api/students/export", { ...st, status: st.status || "any", format }, `students.${format}`).catch(errorToast);
  const actions = h("div", { class: "row" },
    button("Excel", { ico: "download", sm: true, title: "Export the filtered list to Excel", onClick: exp("xlsx") }), button("PDF", { ico: "file", sm: true, onClick: exp("pdf") }), button("CSV", { sm: true, onClick: exp("csv") }),
    ctx.can("students.transfer") ? button("Promote class", { ico: "up", onClick: () => promoteDialog(ctx, () => draw()) }) : null,
    ctx.can("students.create") ? button("Import", { ico: "upload", onClick: () => importDialog(ctx, () => draw()) }) : null,
    ctx.can("students.create") ? button("Register student", { kind: "primary", ico: "plus", onClick: () => studentForm(ctx, null, () => draw()) }) : null);
  mount(view, pageHead("Manage Students", "Register, find and manage student records.", actions), h("div", { class: "toolbar" }, h("div", { class: "search" }, icon("search"), search), field("Class", cls), field("Gender", gen), field("Academic year", yr), field("Status", stat_)), out);

  async function draw() {
    Object.assign(st, { q: search.value.trim(), class_id: cls.value, gender: gen.value, year_id: yr.value, status: stat_.value });
    await load(out, async () => {
      const r = await get("/api/students", { ...st, status: st.status || "any" });
      const pages = Math.max(1, Math.ceil(r.total / st.per_page));
      const cols = [
        { key: "name", label: "Student", render: (s) => h("div", { class: "row", style: { flexWrap: "nowrap", gap: "10px" } }, avatar(s), h("div", null, h("a", { href: `#/students/${s.id}` }, h("b", null, s.full_name)), h("div", { class: "tiny muted" }, `DOB ${fmtDate(s.date_of_birth)}`))) },
        { key: "admission_no", label: "Student ID" }, { key: "class", label: "Class", render: (s) => s.class_name || h("span", { class: "muted" }, "Unassigned") },
        { key: "gender", label: "Gender", sortable: false, render: (s) => cap(s.gender) }, { key: "year", label: "Year", sortable: false, render: (s) => s.year_name || "-" },
        { key: "guardian", label: "Guardian", sortable: false, render: (s) => h("div", null, s.guardian_name, h("div", { class: "tiny muted" }, s.guardian_contact)) },
        { key: "status", label: "Status", render: (s) => badge(cap(s.status), STATUS_TONE[s.status]) },
      ];
      const table = dataTable({ columns: cols, rows: r.items, sortKey: st.sort === "name" ? "name" : st.sort, sortDir: st.dir, server: (k, d) => { st.sort = k; st.dir = d; st.page = 1; draw(); }, onRow: (s) => { location.hash = `#/students/${s.id}`; },
        empty: empty("No students found", search.value || cls.value || gen.value || yr.value ? "Try clearing a filter or search." : "Register your first student to get started.", "users", actions) });
      const pager = h("div", { class: "pager" }, h("span", { class: "small muted" }, r.total ? `Showing ${(st.page - 1) * st.per_page + 1}-${Math.min(st.page * st.per_page, r.total)} of ${fmtNum(r.total)}` : "0 students"),
        h("div", { class: "row" }, button("Previous", { sm: true, ico: "chevronLeft", disabled: st.page <= 1, onClick: () => { st.page--; draw(); } }), h("span", { class: "small" }, `Page ${st.page} of ${pages}`), button("Next", { sm: true, disabled: st.page >= pages, onClick: () => { st.page++; draw(); } })));
      return card(null, h("div", null, table, r.total > st.per_page || st.page > 1 ? pager : h("div", { class: "pager" }, h("span", { class: "small muted" }, `${fmtNum(r.total)} student${r.total === 1 ? "" : "s"}`))), { flush: true });
    });
  }
  const go = debounce(() => { st.page = 1; draw(); }, 300);
  search.addEventListener("input", go); [cls, gen, yr, stat_].forEach((x) => x.addEventListener("change", () => { st.page = 1; draw(); }));
  await draw();
}

// ------------------------------------------------------------ register / edit
export function studentForm(ctx, s, done) {
  const meta = ctx.meta, editing = !!s;
  const cur = meta.years.find((y) => y.is_current);
  const f = {
    first_name: named("first_name", field("First name", input({ value: s?.first_name || "", autocomplete: "off", maxlength: 60 }), { required: true })),
    middle_name: named("middle_name", field("Middle name", input({ value: s?.middle_name || "", autocomplete: "off", maxlength: 80 }))),
    surname: named("surname", field("Surname", input({ value: s?.surname || "", autocomplete: "off", maxlength: 60 }), { required: true })),
    admission_no: named("admission_no", field("Student ID", input({ value: s?.admission_no || "", autocomplete: "off", placeholder: editing ? "" : "Generated automatically" }), { hint: editing ? "" : "Leave blank and the system creates a unique ID." })),
    date_of_birth: named("date_of_birth", field("Date of birth", input({ type: "date", value: s?.date_of_birth || "", max: meta.today }), { required: true })),
    gender: named("gender", field("Gender", select([["", "Choose..."], ["male", "Male"], ["female", "Female"], ["other", "Other"]], s?.gender || ""), { required: true })),
    class_id: editing ? null : named("class_id", field("Class", select(classOptions(meta, { all: "Choose a class..." }), ""), { required: true })),
    academic_year_id: editing ? null : named("academic_year_id", field("Academic year", select(meta.years.map((y) => [y.id, y.name]), cur?.id || meta.years[0]?.id), { required: true })),
    guardian_name: named("guardian_name", field("Parent / guardian name", input({ value: s?.guardian_name || "" }), { required: true })),
    guardian_contact: named("guardian_contact", field("Parent / guardian contact", input({ type: "tel", value: s?.guardian_contact || "", placeholder: "e.g. 0241234567" }), { required: true })),
    address: named("address", field("Residential address", input({ value: s?.address || "" }), { full: true })),
    admission_date: named("admission_date", field("Admission date", input({ type: "date", value: s?.admission_date || meta.today, max: meta.today }), { required: true })),
    status: editing ? named("status", field("Status", select(Object.keys(STATUS_TONE).map((k) => [k, cap(k)]), s.status))) : null,
    photo: named("photo", field("Photograph", input({ type: "file", accept: "image/jpeg,image/png,image/webp" }), { hint: "JPEG, PNG or WebP, up to 5 MB.", full: true })),
  };
  const form = h("form", { class: "form-grid", novalidate: true, onsubmit: (e) => { e.preventDefault(); save.click(); } }, Object.values(f).filter(Boolean));
  const val = (k) => f[k].querySelector("input,select,textarea").value;
  const save = button(editing ? "Save changes" : "Register student", { kind: "primary", onClick: async () => {
    applyErrors(form, null);
    const body = { first_name: val("first_name"), middle_name: val("middle_name"), surname: val("surname"), admission_no: val("admission_no"), date_of_birth: val("date_of_birth"), gender: val("gender"), guardian_name: val("guardian_name"), guardian_contact: val("guardian_contact"), address: val("address"), admission_date: val("admission_date") };
    if (editing) body.status = val("status"); else { body.class_id = val("class_id") ? Number(val("class_id")) : null; body.academic_year_id = Number(val("academic_year_id")) || null; }
    try {
      const r = editing ? await put(`/api/students/${s.id}`, body) : await post("/api/students", body);
      const file = f.photo.querySelector("input").files[0], id = r.student.id;
      if (file) { const fd = new FormData(); fd.append("photo", file); try { await upload(`/api/students/${id}/photo`, fd); } catch (pe) { toast(`Student saved, but the photograph was not uploaded: ${pe.message}`, "warn"); } }
      m.close(); toast(editing ? "Student updated." : `${r.student.full_name} was registered in ${r.student.class_name}.`, "success"); done?.(r.student);
    } catch (e) { applyErrors(form, e); if (!(e instanceof ApiError)) errorToast(e); }
  } });
  const m = modal({ title: editing ? "Edit student" : "Register a new student", size: "lg", body: form, actions: [h("button", { class: "btn", type: "button", onclick: () => m.close() }, "Cancel"), save] });
}

// ------------------------------------------------------------ profile
async function profile(ctx, view, id) {
  let d;
  try { d = await get(`/api/students/${id}`); } catch (e) { return mount(view, backLink("#/students", "All students"), card(null, empty("Student not found", e.message, "users"))); }
  const s = d.student;
  let active = "personal";
  const panel = h("div", { class: "view" }), nav = h("div");
  const reload = () => profile(ctx, view, id);
  const actions = [
    ctx.canAny("reports.student") ? h("a", { class: "btn", href: `#/reports?kind=student&student=${id}` }, icon("chart"), "Report") : null,
    ctx.can("students.edit") ? button("Edit", { ico: "edit", onClick: () => studentForm(ctx, { ...s }, reload) }) : null,
    ctx.can("students.transfer") && s.status === "active" ? button("Transfer", { ico: "swap", onClick: () => transferDialog(ctx, s, reload) }) : null,
    ctx.can("students.edit") && s.status !== "archived" ? button("Archive", { ico: "database", onClick: async () => { if (await confirmDialog({ title: "Archive student?", message: `${s.full_name} will be hidden from class lists and registers. All their records are kept and you can restore them at any time.`, confirmText: "Archive" })) { try { await post(`/api/students/${s.id}/archive`); toast("Student archived.", "success"); reload(); } catch (e) { errorToast(e); } } } }) : null,
    ctx.can("students.edit") && s.status === "archived" ? button("Restore", { ico: "refresh", onClick: async () => { try { await post(`/api/students/${s.id}/restore`); toast("Student restored.", "success"); reload(); } catch (e) { errorToast(e); } } }) : null,
    ctx.can("students.edit") && s.status !== "archived" ? button(s.status === "active" ? "Deactivate" : "Reactivate", { ico: s.status === "active" ? "x" : "check", onClick: () => statusAction(s, reload) }) : null,
    ctx.can("students.delete") ? button("Delete", { kind: "danger", ico: "trash", onClick: () => deleteAction(s) }) : null,
  ];
  const items = [["personal", "Personal", "user"], ["admission", "Admission", "file"], ["class", "Class", "school"], ["attendance", "Attendance", "calendar"], ["exams", "Examination results", "exam"], ["summary", "Performance summary", "chart"]];
  const drawNav = () => mount(nav, tabs(items.map(([i, l, ic]) => ({ id: i, label: l, icon: ic })), active, (t) => { active = t; drawNav(); drawPanel(); }));
  const drawPanel = () => mount(panel, panels[active]());
  const kv = (rows) => h("dl", { class: "def" }, rows.map(([k, v]) => h("div", null, h("dt", null, k), h("dd", null, v ?? "-"))));
  const panels = {
    personal: () => card("Personal information", kv([["Full name", s.full_name], ["Gender", cap(s.gender)], ["Date of birth", fmtDate(s.date_of_birth)], ["Parent / guardian", s.guardian_name], ["Guardian contact", s.guardian_contact], ["Residential address", s.address]])),
    admission: () => card("Admission information", kv([["Admission number", s.admission_no], ["Admission date", fmtDate(s.admission_date)], ["Status", badge(cap(s.status), STATUS_TONE[s.status])], ["Registered", fmtDate((s.created_at || "").slice(0, 10))]])),
    class: () => h("div", { class: "stack" }, card("Current class", kv([["Class", s.class_name ? h("a", { href: ctx.can("command.view") ? `#/dashboard/classes/${s.class_id}` : `#/students?class=${s.class_id}` }, s.class_name) : "Unassigned"], ["Academic year", s.year_name], ["In this class since", fmtDate(s.class_since)], ["Class teacher", d.class_teacher ? `${d.class_teacher.full_name} (${d.class_teacher.staff_id})` : "Not assigned"]])),
      card("Class history", dataTable({ rows: d.class_history, columns: [{ key: "class_name", label: "Class" }, { key: "year_name", label: "Year" }, { key: "start_date", label: "From", render: (r) => fmtDate(r.start_date) }, { key: "end_date", label: "To", render: (r) => (r.is_current ? badge("Current", "good") : fmtDate(r.end_date)) }] }), { flush: true })),
    attendance: () => attendancePanel(d),
    exams: () => examsPanel(d),
    summary: () => summaryPanel(d),
  };
  drawNav(); drawPanel();
  mount(view, backLink("#/students", "All students"), h("div", { class: "page-head" }, h("div", { class: "row", style: { flexWrap: "nowrap" } }, avatar(s, 72), h("div", null, h("h1", null, s.full_name), h("div", { class: "row", style: { marginTop: "6px" } }, badge(s.admission_no, "info"), s.class_name ? badge(s.class_name, "") : null, badge(cap(s.status), STATUS_TONE[s.status])))), h("div", { class: "row" }, actions)), nav, panel);
}

function attendancePanel(d) {
  const a = d.attendance, sm = a.summary;
  return h("div", { class: "stack" },
    h("div", { class: "grid g-stats" }, stat({ label: "Attendance rate", value: fmtPct(sm.rate), ico: "calendar", tone: sm.rate === null ? "" : sm.rate >= 85 ? "good" : sm.rate >= 75 ? "warn" : "bad" }), stat({ label: "Present", value: sm.present, ico: "check", tone: "good" }), stat({ label: "Late", value: sm.late, ico: "clock" }), stat({ label: "Absent", value: sm.absent, ico: "x", tone: sm.absent ? "bad" : "" }), stat({ label: "Days recorded", value: sm.total, ico: "list" })),
    card("Recent attendance (last 30 records)", dataTable({ rows: a.recent, columns: [{ key: "attendance_date", label: "Date", render: (r) => fmtDate(r.attendance_date) }, { key: "class_name", label: "Class" }, { key: "status", label: "Status", render: (r) => statusPill(r.status) }], empty: empty("No attendance recorded yet", "", "calendar") }), { flush: true }));
}

function examsPanel(d) {
  if (!d.examinations.length) return card(null, empty("No examination results yet", "Results appear once teachers enter marks.", "exam"));
  return h("div", { class: "stack" }, d.examinations.map((e) => card(`${e.exam} | ${e.term} ${e.year}`, h("div", { class: "stack-sm" },
    h("div", { class: "row" }, badge(`Average ${fmtPct(e.average)}`, "info"), gradeBadge(e.grade), e.position ? badge(`Position: ${ord(e.position)}`, "good", "check") : badge("Not ranked (marks incomplete)", "")),
    dataTable({ rows: e.subjects, columns: [{ key: "subject", label: "Subject" }, { key: "ca_total", label: "Continuous assessment", align: "right", render: (r) => r.ca_total ?? "-" }, { key: "exam_total", label: "Examination", align: "right", render: (r) => r.exam_total ?? "-" },
      { key: "total", label: `Total (/${e.max_total})`, align: "right", render: (r) => (r.complete ? r.total : badge("Incomplete", "warn")) }, { key: "percent", label: "Score", align: "right", render: (r) => fmtPct(r.percent) }, { key: "grade", label: "Grade", align: "center", render: (r) => gradeBadge(r.grade, r.complete ? undefined : undefined) },
      { key: "position", label: "Position", align: "center", render: (r) => ord(r.position) }, { key: "class_average", label: "Class average", align: "right", render: (r) => fmtPct(r.class_average) }] })), { })));
}

function summaryPanel(d) {
  const p = d.performance, ex = [...d.examinations].reverse().filter((e) => e.average !== null);
  const latest = d.examinations[0];
  return h("div", { class: "stack" },
    h("div", { class: "grid g-stats" }, stat({ label: "Overall average", value: fmtPct(p.overall_average), sub: `across ${p.examinations_taken} examination${p.examinations_taken === 1 ? "" : "s"}`, ico: "chart" }),
      stat({ label: "Latest average", value: fmtPct(latest?.average), sub: latest?.exam, ico: "exam" }), stat({ label: "Latest position", value: latest?.position ? ord(latest.position) : "-", ico: "up" }),
      stat({ label: "Trend", value: p.trend === null ? "-" : `${p.trend > 0 ? "+" : ""}${p.trend}`, sub: "points since previous examination", ico: p.trend < 0 ? "down" : "up", tone: p.trend === null ? "" : p.trend < 0 ? "bad" : "good" }),
      stat({ label: "Attendance", value: fmtPct(d.attendance.summary.rate), ico: "calendar" })),
    card("Average by examination", ex.length > 1 ? lineChart({ title: "Student average by examination", labels: ex.map((e) => e.exam), series: [{ name: "Average %", values: ex.map((e) => e.average) }], min: 0, max: 100, format: (v) => `${v}%` }) : h("div", { class: "chart-empty" }, "A trend line appears after two examinations with results.")),
    latest ? card(`Subjects: ${latest.exam}`, barChart({ title: "Subject scores", labels: latest.subjects.filter((x) => x.percent !== null).map((x) => x.subject), series: [{ name: "Student", values: latest.subjects.filter((x) => x.percent !== null).map((x) => x.percent) }, { name: "Class average", values: latest.subjects.filter((x) => x.percent !== null).map((x) => x.class_average), color: "var(--s2)" }], max: 100, format: (v) => `${v}%`, emptyText: "No complete subject results yet." })) : null);
}

// ------------------------------------------------------------ actions
function transferDialog(ctx, s, done) {
  const cls = field("Move to class", select(classOptions(ctx.meta, { all: "Choose a class..." }).filter(([v]) => String(v) !== String(s.class_id)), ""), { required: true });
  const eff = field("Effective date", input({ type: "date", value: ctx.meta.today, max: ctx.meta.today }));
  const form = h("form", { class: "stack", novalidate: true }, named("class_id", cls), named("effective_date", eff), notice("Past attendance and examination records stay with the class they were recorded in.", "", "info"));
  const m = modal({ title: `Transfer ${s.full_name}`, size: "sm", body: form, actions: [h("button", { class: "btn", onclick: () => m.close() }, "Cancel"), button("Transfer", { kind: "primary", onClick: async () => {
    applyErrors(form, null);
    try { await post(`/api/students/${s.id}/transfer`, { class_id: Number(cls.querySelector("select").value) || null, effective_date: eff.querySelector("input").value }); m.close(); toast("Student transferred.", "success"); done(); }
    catch (e) { applyErrors(form, e); if (!(e instanceof ApiError)) errorToast(e); }
  } })] });
}

async function statusAction(s, done) {
  const to = s.status === "active" ? "inactive" : "active";
  if (!(await confirmDialog({ title: to === "inactive" ? "Deactivate student?" : "Reactivate student?", message: to === "inactive" ? `${s.full_name} will no longer appear in attendance sheets or marks entry. Their history is kept.` : `${s.full_name} will appear in class lists again.`, confirmText: to === "inactive" ? "Deactivate" : "Reactivate", danger: to === "inactive" }))) return;
  try { await post(`/api/students/${s.id}/status`, { status: to }); toast(`Student marked ${to}.`, "success"); done(); } catch (e) { errorToast(e); }
}

async function deleteAction(s) {
  if (!(await confirmDialog({ title: "Delete student permanently?", message: `This permanently deletes ${s.full_name} and all of their attendance and examination records. Consider deactivating instead. This cannot be undone.`, confirmText: "Delete permanently", danger: true, requireText: s.admission_no }))) return;
  try { await del(`/api/students/${s.id}`, { confirm_admission_no: s.admission_no }); toast("Student deleted.", "success"); location.hash = "#/students"; } catch (e) { errorToast(e); }
}


// ------------------------------------------------------------ import from Excel / CSV
function importDialog(ctx, done) {
  const file = input({ type: "file", accept: ".xlsx,.csv", "aria-label": "Excel or CSV file" });
  const out = h("div", { class: "stack" });
  let checked = false;
  const send = async (commit) => {
    const f = file.files[0];
    if (!f) { toast("Choose a file first.", "warn"); return null; }
    const fd = new FormData(); fd.append("file", f); fd.append("commit", commit ? "1" : "0");
    return upload("/api/students/import", fd);
  };
  const resultTable = (r) => h("div", { class: "table-wrap", style: { maxHeight: "260px", overflow: "auto" } }, h("table", { class: "t" }, h("thead", null, h("tr", null, ["Row", "Student", "Class", "Result"].map((x) => h("th", null, x)))),
    h("tbody", null, r.results.filter((x) => x.status !== "ok").slice(0, 100).map((x) => h("tr", null, h("td", null, x.row), h("td", null, x.name || "-"), h("td", null, x.class || "-"), h("td", null, badge(x.status === "duplicate" ? "Duplicate" : "Error", x.status === "duplicate" ? "warn" : "bad"), " ", x.problems.join("; ")))))));
  const check = button("Check file", { ico: "search", onClick: async () => {
    try {
      const r = await send(false); if (!r) return;
      checked = true; const sm = r.summary;
      mount(out, h("div", { class: "grid g-stats" }, stat({ label: "Rows", value: sm.rows }), stat({ label: "Ready to import", value: sm.valid, tone: "good" }), stat({ label: "Errors", value: sm.errors, tone: sm.errors ? "bad" : "" }), stat({ label: "Duplicates", value: sm.duplicates, tone: sm.duplicates ? "warn" : "" })),
        sm.errors || sm.duplicates ? resultTable(r) : null, sm.valid ? notice(`${sm.valid} student(s) will be created. Rows with errors or duplicates are skipped.`, "", "info") : notice("Nothing can be imported from this file.", "warn", "alert"));
      go.disabled = !sm.valid;
    } catch (e) { errorToast(e); }
  } });
  const go = button("Import students", { kind: "primary", ico: "upload", disabled: true, onClick: async () => {
    try { const r = await send(true); toast(`${r.summary.created} student(s) imported.`, "success"); m.close(); done?.(); } catch (e) { errorToast(e); }
  } });
  file.addEventListener("change", () => { checked = false; go.disabled = true; mount(out); });
  const body = h("div", { class: "stack" },
    h("p", null, "Upload an Excel (.xlsx) or CSV file. The first row must name the columns: First Name, Middle Name, Surname, Gender, Date of Birth, Class, Guardian Name, Guardian Contact (Student ID and Admission Date are optional)."),
    h("div", null, button("Download template", { sm: true, ico: "download", onClick: () => download("/api/students/import-template", null, "student-import-template.xlsx").catch(errorToast) })),
    field("File", file), out);
  const m = modal({ title: "Import students", size: "lg", body, actions: [h("button", { class: "btn", type: "button", onclick: () => m.close() }, "Close"), check, go] });
}

// ------------------------------------------------------------ promotion
function promoteDialog(ctx, done) {
  const meta = ctx.meta, cur = meta.years.find((y) => y.is_current);
  const from = select(classOptions(meta, { all: "Choose the class to move..." }), "");
  const toYear = select(meta.years.map((y) => [y.id, y.name + (y.is_current ? " (current)" : "")]), cur?.id);
  const toCls = select(classOptions(meta, { all: "Promote to..." }), "");
  const list = h("div", { class: "stack" });
  let students = [];
  const rows = () => mount(list, students.length ? h("div", { class: "table-wrap", style: { maxHeight: "300px", overflow: "auto" } }, h("table", { class: "t" }, h("thead", null, h("tr", null, h("th", null, "Student"), h("th", null, "Action"))),
    h("tbody", null, students.map((s) => h("tr", null, h("td", null, s.full_name), h("td", null, (s._sel = select([["promote", "Promote"], ["repeat", "Repeat class"], ["graduate", "Graduate / leave"]], "promote", { "aria-label": `Action for ${s.full_name}` })))))))) : notice("Choose a class to see its students.", "", "info"));
  from.addEventListener("change", async () => { if (!from.value) { students = []; return rows(); } try { students = (await get("/api/students", { class_id: from.value, status: "active", per_page: 200, sort: "name" })).items; rows(); } catch (e) { errorToast(e); } });
  rows();
  const go = button("Move students", { kind: "primary", ico: "up", onClick: async () => {
    if (!students.length) return toast("Choose a class with students.", "warn");
    const items = students.map((s) => ({ student_id: s.id, action: s._sel.value, to_class_id: s._sel.value === "promote" ? Number(toCls.value) || null : null }));
    if (items.some((i) => i.action === "promote" && !i.to_class_id)) return toast("Choose the class to promote to.", "warn");
    if (!(await confirmDialog({ title: "Move these students?", message: "Their old class, marks and attendance stay in their history. Only the current class changes.", confirmText: "Move" }))) return;
    try { const r = await post("/api/students/promote", { academic_year_id: Number(toYear.value), items }); toast(`${r.moved} student(s) moved.`, "success"); m.close(); done?.(); } catch (e) { errorToast(e); }
  } });
  const m = modal({ title: "Promote a class", size: "lg", body: h("div", { class: "stack" }, h("div", { class: "form-grid" }, field("From class", from), field("Into academic year", toYear), field("Promote to class", toCls)), list), actions: [h("button", { class: "btn", type: "button", onclick: () => m.close() }, "Cancel"), go] });
}
