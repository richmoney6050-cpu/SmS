// Class Monitoring: every class at a glance, and a complete read-only class view for supervisors.
import { get } from "../lib/api.js";
import { barChart, hbarChart } from "../lib/charts.js";
import { badge, card, dataTable, empty, errorToast, field, fmtNum, fmtPct, h, icon, input, load, mount, notice, pageHead, rateBar, select, stat, statusBadge, tabs, ago, fmtDate, fmtDateTime, load as loadInto } from "../lib/ui.js";
import { activityFeed, attendanceMark, backLink, gradeBadge, studentLink, when } from "./common.js";

export async function render(ctx, head, body, id) {
  if (id) return classView(ctx, head, body, Number(id));
  return list(ctx, head, body);
}

async function list(ctx, head, body) {
  const d = await get("/api/command/classes");
  mount(head, pageHead("Class Monitoring", `Every class in the school${d.is_school_day ? ` | attendance is due by ${d.deadline}` : " | today is not a school day"}`));
  const q = input({ type: "search", placeholder: "Search class or teacher", "aria-label": "Search classes" });
  const st = select([["", "Any attendance status"], ["missing", "Attendance missing"], ["partial", "Partly recorded"], ["recorded", "Recorded"]], "");
  const grid = h("div");
  const draw = () => {
    const text = q.value.trim().toLowerCase();
    const items = d.classes.filter((c) => (!text || c.name.toLowerCase().includes(text) || (c.teacher || "").toLowerCase().includes(text)) && (!st.value || c.attendance.state === st.value));
    if (!items.length) return mount(grid, card(null, empty("No classes match", "Try a different search or filter.", "search")));
    mount(grid, h("div", { class: "class-grid" }, items.map(classCard)));
  };
  q.addEventListener("input", draw); st.addEventListener("change", draw);
  mount(body, h("div", { class: "toolbar" }, h("div", { class: "search" }, icon("search"), q), field("Attendance", st)), grid);
  draw();
}

function classCard(c) {
  const a = c.attendance, e = c.exam;
  return h("article", { class: "card class-card" },
    h("div", { class: "top" }, h("div", null, h("h3", null, c.name), h("div", { class: "small muted" }, c.teacher ? `Class teacher: ${c.teacher}` : h("span", { style: { color: "var(--crit-ink)" } }, "No class teacher assigned"))), h("span", { class: "badge info" }, icon("users"), `${c.students} students`)),
    h("div", null, h("div", { class: "row between" }, h("span", { class: "tiny muted" }, "Attendance today"), statusBadge(a.state)), a.rate !== null ? rateBar(a.rate) : h("div", { class: "small muted" }, "Nothing recorded yet"),
      a.recorded ? h("div", { class: "tiny muted" }, `${a.present} present | ${a.late} late | ${a.absent} absent`) : null),
    h("div", null, h("div", { class: "row between" }, h("span", { class: "tiny muted" }, e ? `Examination: ${e.exam_name}` : "Examination"), e ? statusBadge(e.status) : statusBadge("none")),
      e ? h("div", { class: "small" }, h("b", null, fmtPct(e.average)), " class average", e.pass_rate !== null ? ` | ${fmtPct(e.pass_rate)} pass` : "", h("div", { class: "tiny muted" }, `${e.submitted} of ${e.subjects} subjects submitted`)) : h("div", { class: "small muted" }, "No examination set up")),
    h("div", { class: "small" }, h("div", { class: "tiny muted" }, "Latest teacher activity"), c.last_activity ? [c.last_activity.text, h("div", { class: "tiny muted" }, when(c.last_activity.at))] : h("span", { class: "muted" }, "No activity recorded")),
    h("a", { class: "btn primary", href: `#/dashboard/classes/${c.id}`, "aria-label": `View class ${c.name}` }, icon("eye"), "VIEW CLASS"));
}

// ------------------------------------------------------------ the class view
async function classView(ctx, head, body, id, examId) {
  const d = await get(`/api/command/classes/${id}`, { exam_id: examId });
  const att = d.attendance, c = d.class;
  const classTeacher = d.teachers.find((t) => t.is_class_teacher);
  mount(head, h("div", null, backLink("#/dashboard/classes", "All classes"), pageHead(c.name, `${c.students} students | ${classTeacher ? "Class teacher: " + classTeacher.full_name : "No class teacher assigned"}`, [h("a", { class: "btn", href: `#/reports?kind=class&class=${id}` }, icon("chart"), "Class report")])));
  let active = "overview";
  const panel = h("div", { class: "view" });
  const items = [["overview", "Overview", "dashboard"], ["students", "Students and attendance", "users"], ["subjects", "Subjects", "book"], ["exam", "Examination results", "exam"], ["activity", "Teacher activity", "list"], ["gaps", "Missing or incomplete", "alert"]];
  const nav = h("div");
  const drawNav = () => mount(nav, tabs(items.map(([i, l, ic]) => ({ id: i, label: l, icon: ic, count: i === "gaps" ? d.gaps.length : 0 })), active, (t) => { active = t; drawNav(); drawPanel(); }));
  const drawPanel = () => mount(panel, { overview, students, subjects, exam, activity, gaps }[active](d, ctx, id));
  drawNav(); drawPanel();
  mount(body, nav, panel);
  // expose a re-render for the exam selector
  body.reload = (eid) => classView(ctx, head, body, id, eid);
  body.activeTab = () => active;
  window.__classViewBody = body;
}

function overview(d) {
  const att = d.attendance, ex = d.exam;
  const series = att.series.filter((p) => p.rate !== null);
  return h("div", { class: "stack" },
    h("div", { class: "grid g-stats" },
      stat({ label: "Students", value: d.class.students, ico: "users" }),
      stat({ label: "Attendance today", value: fmtPct(att.today.rate), sub: att.today.state === "missing" ? "Not recorded yet" : `${att.today.present} present, ${att.today.absent} absent`, ico: "calendar", tone: att.today.state === "missing" ? "bad" : "" }),
      stat({ label: `Attendance (${att.period_label})`, value: fmtPct(att.period.rate), sub: `${fmtNum(att.period.total)} records`, ico: "check" }),
      stat({ label: "Class average", value: fmtPct(ex?.totals.average), sub: ex ? ex.exam.name : "No examination", ico: "chart" }),
      stat({ label: "Pass rate", value: fmtPct(ex?.totals.pass_rate), sub: ex?.totals.fail_rate !== null && ex ? `${fmtPct(ex.totals.fail_rate)} fail` : "", ico: "exam" }),
      stat({ label: "Open gaps", value: d.gaps.length, ico: "alert", tone: d.gaps.length ? "warn" : "good" })),
    h("div", { class: "grid g2" },
      card("Teachers", d.teachers.length ? h("ul", { class: "list", style: { margin: "-16px -20px -20px" } }, d.teachers.map((t) => h("li", null, h("span", { class: "avatar" }, t.full_name.replace(/^(Mr|Mrs|Ms|Dr)\.?\s+/i, "")[0]), h("div", { class: "grow" }, h("b", null, t.full_name), h("div", { class: "small muted" }, t.is_class_teacher ? "Class teacher" : t.subject_name, ` | ${t.staff_id}`), h("div", { class: "tiny muted" }, "Last website login: ", when(t.last_login_at)))))) : empty("No teachers assigned", "Assign teachers under Administration.", "users")),
      card("Attendance, last 10 school days", barChart({ title: "Daily attendance rate", labels: series.map((p) => fmtDate(p.date).replace(/, \d{4}$/, "")), series: [{ name: "Attendance %", values: series.map((p) => p.rate), color: "var(--s1)" }], max: 100, format: (v) => `${v}%`, height: 220, emptyText: "No attendance recorded in the last 10 school days." }))));
}

function students(d) {
  const att = d.attendance;
  const dates = att.grid_dates;
  const cols = [
    { key: "full_name", label: "Student", render: (s) => h("div", null, studentLink(s.id, s.full_name), h("div", { class: "tiny muted" }, s.admission_no)) },
    { key: "today", label: "Today", align: "center", render: (s) => attendanceMark(s.today), sortValue: (s) => s.today || "" },
    { key: "grid", label: `Last ${dates.length} days`, sortable: false, render: (s) => h("div", { class: "row", style: { gap: "3px", flexWrap: "nowrap" } }, s.grid.map(attendanceMark)) },
    { key: "rate", label: `Attendance (${att.period_label})`, render: (s) => (s.rate === null ? h("span", { class: "muted" }, "No records") : rateBar(s.rate, att.poor_threshold)) },
    { key: "absent", label: "Absent", align: "right" }, { key: "late", label: "Late", align: "right" },
    { key: "poor", label: "", sortable: false, render: (s) => (s.poor ? badge("Poor attendance", "bad", "alert") : null) },
  ];
  return h("div", { class: "stack" }, card(`Class attendance: ${fmtPct(att.period.rate)} (${att.period_label})`, h("div", { class: "row" },
    badge(`${att.period.present} present`, "good", "check"), badge(`${att.period.late} late`, "warn", "clock"), badge(`${att.period.absent} absent`, "bad", "x"), h("span", { class: "small muted" }, "Dates run oldest to newest, left to right. P present, A absent, L late, - not recorded."))),
    card(null, dataTable({ columns: cols, rows: att.students, sortKey: "full_name", empty: empty("No students in this class", "Register students under Manage Students.", "users") }), { flush: true }));
}

function subjects(d) {
  const cols = [
    { key: "name", label: "Subject" }, { key: "teacher", label: "Teacher", render: (s) => (s.teacher ? [s.teacher, !s.dedicated_teacher ? h("div", { class: "tiny muted" }, "Class teacher covers") : null] : h("span", { style: { color: "var(--crit-ink)" } }, "Not assigned")) },
    { key: "assessed", label: "Marks complete", align: "right", sortValue: (s) => s.exam?.assessed ?? -1, render: (s) => (s.exam ? `${s.exam.assessed}/${s.exam.expected}` : "-") },
    { key: "average", label: "Average", align: "right", sortValue: (s) => s.exam?.average ?? -1, render: (s) => fmtPct(s.exam?.average) },
    { key: "highest", label: "Highest", align: "right", sortValue: (s) => s.exam?.highest ?? -1, render: (s) => fmtPct(s.exam?.highest) },
    { key: "lowest", label: "Lowest", align: "right", sortValue: (s) => s.exam?.lowest ?? -1, render: (s) => fmtPct(s.exam?.lowest) },
    { key: "pass", label: "Pass %", align: "right", sortValue: (s) => s.exam?.pass_rate ?? -1, render: (s) => fmtPct(s.exam?.pass_rate) },
    { key: "status", label: "Marks list", render: (s) => (s.exam ? statusBadge(s.exam.status === "submitted" ? "submitted" : "pending") : statusBadge("none")) },
  ];
  return card(null, dataTable({ columns: cols, rows: d.subjects, sortKey: "name", empty: empty("No subjects", "Add subjects to this class under School setup.", "book") }), { flush: true });
}

function exam(d, ctx, id) {
  if (!d.exam) return card(null, empty("No examination yet", "An examination has not been set up for this class.", "exam"));
  const ex = d.exam, t = ex.totals;
  const sel = select(d.exam_options.map((e) => [e.id, e.name]), d.exam_id, { "aria-label": "Examination" });
  sel.addEventListener("change", () => window.__classViewBody.reload(Number(sel.value)).then(() => { /* keep tab */ }).catch(errorToast));
  const subj = ex.subjects.filter((s) => s.average !== null);
  return h("div", { class: "stack" },
    h("div", { class: "toolbar" }, field("Examination", sel), h("div", { class: "small muted", style: { alignSelf: "center" } }, `${ex.exam.term_name} ${ex.exam.year_name} | marks due ${fmtDate(ex.exam.marks_due_date)}`)),
    h("div", { class: "grid g-stats" }, stat({ label: "Class average", value: fmtPct(t.average), ico: "chart" }), stat({ label: "Highest", value: fmtPct(t.highest), ico: "up" }), stat({ label: "Lowest", value: fmtPct(t.lowest), ico: "down" }),
      stat({ label: "Pass rate", value: fmtPct(t.pass_rate), ico: "check", tone: "good" }), stat({ label: "Fail rate", value: fmtPct(t.fail_rate), ico: "x", tone: t.fail_rate ? "bad" : "" }), stat({ label: "Students assessed", value: t.students_assessed, sub: `of ${d.class.students}`, ico: "users" })),
    card("Subject averages", hbarChart({ title: "Average by subject", labels: subj.map((s) => s.subject_name), series: [{ name: "Average %", values: subj.map((s) => s.average), color: "var(--s3)" }], max: 100, format: (v) => `${v}%`, emptyText: "No subject has complete marks yet." })),
    card("Student results", dataTable({ rows: ex.students, sortKey: "position", columns: [
      { key: "position", label: "Pos.", align: "center", sortValue: (s) => s.position ?? 9999, render: (s) => s.position ?? "-" },
      { key: "student_name", label: "Student", render: (s) => studentLink(s.student_id, s.student_name) },
      { key: "average", label: "Average", align: "right", sortValue: (s) => s.average ?? -1, render: (s) => fmtPct(s.average) },
      { key: "grade", label: "Grade", align: "center", render: (s) => gradeBadge(s.grade) },
      { key: "subjects_done", label: "Subjects complete", align: "right", render: (s) => `${s.subjects_done}/${s.subjects_total}` },
    ], empty: empty("No results yet", "Marks have not been entered.", "exam") }), { flush: true }),
    notice("Students with missing marks are not ranked, and missing marks are never counted as zero.", "", "info"));
}

function activity(d) {
  return card("Activity for this class", activityFeed(d.activity, { empty: "No teacher has saved anything for this class yet." }), { flush: true });
}

function gaps(d) {
  if (!d.gaps.length) return card(null, empty("Nothing is missing", "Attendance and marks are up to date for this class.", "check"));
  const ico = { no_class_teacher: "user", no_subject_teacher: "user", attendance_today: "calendar", attendance_missing: "calendar", marks_pending: "exam" };
  return card(`${d.gaps.length} item${d.gaps.length === 1 ? "" : "s"} to follow up`, h("ul", { class: "list", style: { margin: "-16px -20px -20px" } }, d.gaps.map((g) => h("li", null, h("span", { class: "feed-ico alert" }, icon(ico[g.type] || "alert")), h("div", { class: "grow" }, g.text)))));
}
