// Dashboard: the Central Command Centre for leaders, a simple task dashboard for teachers.
import { del, get, post } from "../lib/api.js";
import { barChart, lineChart } from "../lib/charts.js";
import { badge, button, card, dataTable, empty, errorToast, fmtDate, fmtNum, fmtPct, h, icon, load, loading, mount, notice, pageHead, rateBar, select, field, input, textarea, confirmDialog, stat, statusBadge, tabs, toast, ago, fmtDateTime } from "../lib/ui.js";
import { ALERT_LABELS, activityFeed, alertLink, classLink, sevIcon, sevTone, when } from "./common.js";

const TABS = [
  ["overview", "Overview", "dashboard"], ["classes", "Class Monitoring", "school"], ["teachers", "Teacher Monitoring", "users"],
  ["attendance", "Attendance", "calendar"], ["academics", "Academic Performance", "chart"], ["activity", "Activity Feed", "list"], ["alerts", "Alerts", "bell"],
];

export async function render(ctx, view, params) {
  if (!ctx.can("command.view")) return renderTeacher(ctx, view);
  const [tab = "overview", id] = params;
  const alertCount = (await get("/api/command/alerts", { status: "open" }).catch(() => ({ items: [] }))).items.length;
  const head = h("div");
  const body = h("div", { class: "view" });
  const nav = tabs(TABS.map(([i, l, ic]) => ({ id: i, label: l, icon: ic, count: i === "alerts" && alertCount ? alertCount : 0 })), tab, (t) => { location.hash = "#/dashboard/" + (t === "overview" ? "" : t); });
  mount(view, head, nav, body);
  const refreshers = [];
  const cleanup = () => refreshers.forEach((t) => clearInterval(t));
  if (tab === "overview" || !TABS.some((t) => t[0] === tab)) { await overview(ctx, head, body, refreshers); return cleanup; }
  if (tab === "activity") { mount(head, pageHead("Activity Feed", "Important activity across the school, newest first.")); await activity(ctx, body); return cleanup; }
  if (tab === "alerts") { mount(head, pageHead("Alerts", "Issues that need attention. Each unresolved issue appears once and clears itself when fixed.")); await alertsView(ctx, body); return cleanup; }
  const file = { classes: "classmon.js", teachers: "teachermon.js", attendance: "attmon.js", academics: "acadmon.js" }[tab];
  const m = await import(`./${file}`);
  await m.render(ctx, head, body, id);
  return cleanup;
}

// ------------------------------------------------------------ overview
async function overview(ctx, head, body, refreshers) {
  const draw = async (first) => {
    let d;
    try { d = await get("/api/command/overview"); } catch (e) { if (first) throw e; return; }
    const s = d.stats, t = d.teacher_summary;
    const attTone = s.attendance_rate === null ? "" : s.attendance_rate >= 85 ? "good" : s.attendance_rate >= 75 ? "warn" : "bad";
    mount(head, pageHead("Central Command Centre", `${new Date(d.date + "T00:00:00").toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long", year: "numeric" })}${d.is_school_day ? "" : " (not a school day)"}`, [
      h("span", { class: "small muted", id: "updated" }, `Updated ${new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}${d.refresh_seconds ? ` | refreshes every ${d.refresh_seconds}s` : ""}`),
      button("Refresh", { ico: "refresh", sm: true, onClick: () => draw(false) })]));
    const stats = h("div", { class: "grid g-stats" },
      stat({ label: "Total students", value: fmtNum(s.students), ico: "users" }),
      stat({ label: "Total teachers", value: fmtNum(s.teachers), ico: "user" }),
      stat({ label: "Total classes", value: fmtNum(s.classes), ico: "school" }),
      stat({ label: "Boys", value: fmtNum(s.boys), ico: "users" }),
      stat({ label: "Girls", value: fmtNum(s.girls), ico: "users" }),
      stat({ label: "Term attendance", value: fmtPct(s.term_attendance_rate), sub: "average this term", ico: "calendar" }),
      stat({ label: "Present today", value: fmtNum(s.present_today), sub: `${fmtNum(s.late_today)} late`, ico: "check", tone: "good" }),
      stat({ label: "Absent today", value: fmtNum(s.absent_today), ico: "x", tone: s.absent_today ? "bad" : "" }),
      stat({ label: "Attendance today", value: fmtPct(s.attendance_rate), sub: s.attendance_rate === null ? "Nothing recorded yet" : "of recorded students", ico: "calendar", tone: attTone }),
      stat({ label: "Classes with attendance", value: `${s.classes_recorded}/${s.classes}`, sub: "recorded today", ico: "check" }),
      stat({ label: "Classes missing attendance", value: fmtNum(s.classes_missing), ico: "alert", tone: s.classes_missing ? "bad" : "good" }),
      stat({ label: "Academic average", value: fmtPct(s.academic_average), sub: s.academic_scope ? `${s.academic_scope} | ${fmtNum(s.academic_results)} results` : "No results yet", ico: "chart" }),
      stat({ label: "Results submitted", value: fmtNum(s.results_submitted), sub: "class-subject lists", ico: "exam", tone: "good" }),
      stat({ label: "Results pending", value: fmtNum(s.results_pending), sub: "awaiting submission", ico: "clock", tone: s.results_pending ? "warn" : "good" }),
      stat({ label: "Open alerts", value: fmtNum(d.alerts.total), sub: `${d.alerts.critical} critical | ${d.alerts.warning} warning`, ico: "bell", tone: d.alerts.critical ? "bad" : d.alerts.total ? "warn" : "good" }));
    const classesWithAtt = d.classes.filter((c) => c.attendance.rate !== null);
    const attChart = card("Attendance today by class", barChart({ title: "Attendance rate by class today", labels: classesWithAtt.map((c) => c.name), series: [{ name: "Attendance %", values: classesWithAtt.map((c) => c.attendance.rate), color: "var(--s1)" }], max: 100, format: (v) => `${v}%`, threshold: 75, thresholdLabel: "75% line", emptyText: "No class has recorded attendance yet today." }), { actions: h("a", { class: "btn sm", href: "#/dashboard/attendance" }, "Attendance monitoring") });
    const trend = card("Attendance trend (last 14 school days)", lineChart({ title: "School attendance trend", labels: d.attendance_trend.map((p) => fmtDate(p.date).replace(/, \d{4}$/, "")), series: [{ name: "Attendance %", values: d.attendance_trend.map((p) => p.rate), color: "var(--s1)" }], min: 0, max: 100, format: (v) => `${v}%`, emptyText: "No attendance has been recorded yet." }));
    const withExam = d.classes.filter((c) => c.exam && c.exam.average !== null);
    const perf = card("Class performance (latest examination)", barChart({ title: "Class average by class", labels: withExam.map((c) => c.name), series: [{ name: "Average %", values: withExam.map((c) => c.exam.average), color: "var(--s3)" }], max: 100, format: (v) => `${v}%`, emptyText: "No examination marks have been entered yet." }), { actions: h("a", { class: "btn sm", href: "#/dashboard/academics" }, "Academic performance") });
    const teacherCard = card("Teacher activity today", h("dl", { class: "kv" },
      h("dt", null, "Teachers"), h("dd", null, t.total), h("dt", null, "Logged in to the website"), h("dd", null, t.logged_in_today),
      h("dt", null, "Saved attendance or marks"), h("dd", null, t.recorded_today), h("dt", null, "With tasks outstanding"), h("dd", null, h("b", { style: { color: t.with_outstanding ? "var(--crit-ink)" : "var(--good-ink)" } }, t.with_outstanding)),
      h("dt", null, "Without class assignments"), h("dd", null, t.no_assignments)), { actions: h("a", { class: "btn sm", href: "#/dashboard/teachers" }, "Teacher monitoring") });
    const alertList = card("Needs attention", d.alerts.top.length ? h("ul", { class: "list" }, d.alerts.top.map((a) => alertRow(a, ctx))) : empty("All clear", "No open alerts right now.", "check"), { flush: true, actions: h("a", { class: "btn sm", href: "#/dashboard/alerts" }, `All alerts (${d.alerts.total})`) });
    const feed = card("Recent activity", activityFeed(d.activity, { empty: "No teacher activity yet." }), { flush: true, actions: h("a", { class: "btn sm", href: "#/dashboard/activity" }, "Full feed") });
    const ann = await announcementsCard();
    const note = notice("Website logins and saved records show what teachers have done in this system. They do not confirm that a teacher is physically teaching.", "", "info");
    mount(body, h("div", { class: "stack" }, stats, h("div", { class: "grid g-main" }, h("div", { class: "stack" }, attChart, trend, perf), h("div", { class: "stack" }, alertList, ann, teacherCard, feed)), note));
  };
  await draw(true);
  const secs = ctx.school.refresh_seconds;
  if (secs > 0) refreshers.push(setInterval(() => { if (!document.hidden && document.getElementById("updated")) draw(false); }, Math.max(15, secs) * 1000));
}

function alertRow(a, ctx) {
  const href = alertLink(a);
  return h("li", { class: "alert-item " + a.severity, style: { opacity: a.resolved_at ? .6 : 1 } }, h("span", { class: "feed-ico " + (a.severity === "critical" ? "critical alert" : "alert") }, icon(sevIcon(a.severity))),
    h("div", { class: "grow" }, h("div", null, h("b", null, a.title)), h("div", { class: "small" }, a.message), h("div", { class: "tiny muted" }, `${ALERT_LABELS[a.type] || a.type} | raised `, when(a.created_at), a.resolved_at ? " | resolved" : "")),
    href ? h("a", { class: "btn sm", href }, "Open") : null);
}

// ------------------------------------------------------------ activity feed
async function activity(ctx, body) {
  const meta = ctx.meta;
  const kind = select([["all", "Everything"], ["record", "Saved records"], ["login", "Website logins"], ["alert", "Alerts"]], "all");
  const cls = select([["", "All classes"], ...meta.classes.map((c) => [c.id, c.name])], "");
  const list = h("div");
  const draw = () => load(list, async () => {
    const r = await get("/api/command/activity", { kind: kind.value, class_id: cls.value, limit: 60 });
    return card(null, activityFeed(r.items), { flush: true });
  });
  [kind, cls].forEach((x) => x.addEventListener("change", draw));
  mount(body, h("div", { class: "toolbar" }, field("Show", kind), field("Class", cls)), list);
  await draw();
}

// ------------------------------------------------------------ alerts
async function alertsView(ctx, body) {
  const status = select([["open", "Open"], ["resolved", "Resolved"], ["all", "All"]], "open");
  const type = select([["", "All types"], ...Object.entries(ALERT_LABELS)], "");
  const list = h("div");
  const draw = () => load(list, async () => {
    const r = await get("/api/command/alerts", { status: status.value, type: type.value });
    ctx.refreshAlertCount();
    if (!r.items.length) return card(null, empty("Nothing here", status.value === "open" ? "There are no open alerts. Everything is on track." : "No alerts match.", "check"));
    const groups = { critical: [], warning: [], info: [] };
    r.items.forEach((a) => groups[a.severity].push(a));
    return h("div", { class: "stack" }, ["critical", "warning", "info"].filter((g) => groups[g].length).map((g) => card(`${{ critical: "Critical", warning: "Warnings", info: "For your information" }[g]} (${groups[g].length})`, h("ul", { class: "list" }, groups[g].map((a) => {
      const li = alertRow(a, ctx);
      if (!a.read_at && !a.resolved_at) li.append(button("Mark read", { sm: true, onClick: async () => { await post(`/api/command/alerts/${a.id}/read`); toast("Marked as read.", "success"); draw(); } }));
      return li;
    })), { flush: true })));
  });
  [status, type].forEach((x) => x.addEventListener("change", draw));
  const markAll = button("Mark all read", { ico: "check", onClick: async () => { await post("/api/command/alerts/read-all"); toast("All alerts marked as read.", "success"); draw(); } });
  mount(body, h("div", { class: "toolbar" }, field("Status", status), field("Type", type), h("div", null, markAll)), list);
  await draw();
}

// ------------------------------------------------------------ teacher dashboard
async function renderTeacher(ctx, view) {
  const d = await get("/api/dashboard/teacher");
  const ann = await announcementsCard();
  const taskIcon = (t) => (t.type === "attendance" ? "calendar" : "exam");
  const tasks = d.tasks.length ? h("ul", { class: "list" }, d.tasks.map((t) => h("li", null, h("span", { class: "feed-ico " + (t.overdue ? "critical alert" : "alert") }, icon(taskIcon(t))), h("div", { class: "grow" }, t.text, t.overdue ? h("div", null, badge("Overdue", "bad", "alert")) : null),
    h("a", { class: "btn sm primary", href: t.type === "attendance" ? `#/attendance?class=${t.class_id}` : `#/exams/${t.exam_id}?class=${t.class_id}&subject=${t.subject_id}` }, t.type === "attendance" ? "Record" : "Enter marks")))) : empty("You are up to date", "No tasks are waiting for you.", "check");
  const classes = d.classes.length ? h("div", { class: "class-grid" }, d.classes.map((c) => h("div", { class: "card class-card" },
    h("div", { class: "top" }, h("div", null, h("h3", null, c.name), h("div", { class: "small muted" }, `${c.students} students`)), statusBadge(c.attendance.state)),
    h("div", null, h("div", { class: "tiny muted" }, "Attendance today"), rateBar(c.attendance.rate)),
    c.exam ? h("div", { class: "small" }, `${c.exam.exam_name}: `, h("b", null, fmtPct(c.exam.average)), ` average | ${c.exam.submitted}/${c.exam.subjects} subjects submitted`) : h("div", { class: "small muted" }, "No examination yet"),
    h("div", { class: "row" }, h("a", { class: "btn sm", href: `#/attendance?class=${c.id}` }, icon("calendar"), "Attendance"), h("a", { class: "btn sm", href: `#/students?class=${c.id}` }, icon("users"), "Students"))))) : empty("No classes assigned", "An administrator has not assigned you to a class yet.", "school");
  mount(view, pageHead(`Hello, ${ctx.user.full_name.split(" ").slice(0, 2).join(" ")}`, `${new Date(d.date + "T00:00:00").toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" })}${d.is_school_day ? ` | attendance is due by ${d.deadline}` : " | not a school day"}`),
    h("div", { class: "stack view" },
      h("div", { class: "grid g-stats" }, stat({ label: "My classes", value: new Set(d.assignments.map((a) => a.class_id)).size, ico: "school" }), stat({ label: "Tasks to do", value: d.tasks.length, ico: "clock", tone: d.tasks.length ? "warn" : "good" }), stat({ label: "Marks lists submitted", value: `${d.marks_progress.submitted}/${d.marks_progress.total}`, ico: "exam" })),
      ann,
      h("div", { class: "grid g-main" }, card("My tasks", tasks, { flush: true }), card("Recent activity", activityFeed(d.recent_activity, { empty: "Nothing recorded yet." }), { flush: true })),
      h("h2", null, "My classes"), classes));
}

// ------------------------------------------------------------ announcements
async function announcementsCard() {
  const body = h("div", { class: "stack-sm" });
  const draw = async () => {
    let r;
    try { r = await get("/api/announcements"); } catch { return mount(body, h("span", { class: "muted small" }, "Announcements are unavailable.")); }
    const title = input({ maxlength: 120, placeholder: "Title", "aria-label": "Announcement title" });
    const text = textarea({ rows: 3, maxlength: 2000, placeholder: "Message to staff" });
    const aud = select([["all", "Everyone"], ["teachers", "Teachers"]], "all");
    const form = r.can_post ? h("div", { class: "stack-sm" }, title, text, h("div", { class: "row" }, aud,
      button("Post", { kind: "primary", sm: true, ico: "check", onClick: async () => {
        try { await post("/api/announcements", { title: title.value, body: text.value, audience: aud.value }); toast("Announcement posted.", "success"); draw(); } catch (e) { errorToast(e); }
      } }))) : null;
    const list = r.items.length ? h("ul", { class: "list ann-list" }, r.items.map((a) => h("li", { class: "ann" },
      h("div", null, h("b", null, a.title), h("div", { class: "small" }, a.body), h("div", { class: "tiny muted" }, `${a.author_name || ""} | ${a.created_at ? fmtDate(a.created_at.slice(0, 10)) : ""}`)),
      r.can_post ? button("Delete", { sm: true, ico: "x", onClick: async () => {
        if (!(await confirmDialog({ title: "Delete announcement?", message: "It will no longer be shown to staff.", confirmText: "Delete" }))) return;
        try { await del(`/api/announcements/${a.id}`); draw(); } catch (e) { errorToast(e); }
      } }) : null))) : h("span", { class: "muted small" }, "No announcements.");
    mount(body, list, form);
  };
  await draw();
  return card("Announcements", body);
}
