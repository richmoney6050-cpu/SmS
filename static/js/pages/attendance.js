// Module 2: Attendance.
import { ApiError, get, post } from "../lib/api.js";
import { barChart, lineChart } from "../lib/charts.js";
import { badge, button, card, confirmDialog, dataTable, empty, errorToast, field, fmtDate, fmtNum, fmtPct, h, icon, initials, input, load, mount, notice, pageHead, rateBar, select, stat, statusBadge, tabs, toast } from "../lib/ui.js";
import { classOptions, studentLink, termOptions, yearOptions } from "./common.js";

export async function render(ctx, view) {
  const q = ctx.query();
  let active = q.get("tab") || "sheet";
  const panel = h("div", { class: "view" }), nav = h("div");
  const items = [["sheet", "Record attendance", "calendar"], ["dash", "Dashboard and reports", "chart"]];
  const drawNav = () => mount(nav, tabs(items.map(([i, l, ic]) => ({ id: i, label: l, icon: ic })), active, async (t) => { if (dirtyGuard && !(await dirtyGuard())) return; active = t; drawNav(); drawPanel(); }));
  let dirtyGuard = null;
  const drawPanel = () => { dirtyGuard = null; mount(panel, h("div")); const holder = panel.firstChild; (active === "sheet" ? sheet : dashboard)(ctx, holder, (g) => { dirtyGuard = g; }); };
  mount(view, pageHead("Attendance", "Record daily attendance and monitor attendance across classes."), nav, panel);
  drawNav(); drawPanel();
  const warn = (e) => { if (dirtyGuard && dirtyGuard.dirty?.()) { e.preventDefault(); e.returnValue = ""; } };
  window.addEventListener("beforeunload", warn);
  return () => window.removeEventListener("beforeunload", warn);
}

// ------------------------------------------------------------ recording sheet
function sheet(ctx, root, setGuard) {
  const meta = ctx.meta, q = ctx.query();
  const classes = meta.classes.filter((c) => c.is_active);
  if (!classes.length) return mount(root, card(null, empty("No classes available", ctx.can("attendance.record") ? "You have not been assigned to a class yet." : "No classes have been set up.", "school")));
  const cls = select(classes.map((c) => [c.id, c.name]), q.get("class") || classes[0].id, { "aria-label": "Class" });
  const date = input({ type: "date", value: q.get("date") || meta.today, max: meta.today, "aria-label": "Date" });
  const out = h("div");
  let marks = {}, original = {}, current = null;
  const dirty = () => current && current.can_edit && JSON.stringify(marks) !== JSON.stringify(original);
  const guard = async () => (!dirty() || (await confirmDialog({ title: "Discard unsaved attendance?", message: "You have marked students but not saved. Leaving will lose those marks.", confirmText: "Discard", danger: true })));
  guard.dirty = dirty;
  setGuard(guard);
  let lastClass = cls.value, lastDate = date.value;
  const reload = async () => { if (!(await guard())) { cls.value = lastClass; date.value = lastDate; return; } lastClass = cls.value; lastDate = date.value; await loadSheet(); };
  cls.addEventListener("change", reload); date.addEventListener("change", reload);
  const prev = button("", { ico: "chevronLeft", sm: true, title: "Previous day", onClick: () => { const d = new Date(date.value + "T00:00:00"); d.setDate(d.getDate() - 1); date.value = d.toISOString().slice(0, 10); return reload(); } });
  const next = button("", { ico: "chevronRight", sm: true, title: "Next day", onClick: () => { const d = new Date(date.value + "T00:00:00"); d.setDate(d.getDate() + 1); if (d.toISOString().slice(0, 10) > meta.today) return; date.value = d.toISOString().slice(0, 10); return reload(); } });
  mount(root, h("div", { class: "toolbar" }, field("Class", cls), field("Date", h("div", { class: "row date-nav", style: { gap: "6px", flexWrap: "nowrap" } }, prev, date, next))), out);

  async function loadSheet() {
    await load(out, async () => {
      const d = await get("/api/attendance/sheet", { class_id: cls.value, date: date.value });
      current = d; original = Object.fromEntries(d.students.filter((s) => s.status).map((s) => [s.id, s.status])); marks = { ...original };
      return sheetView(d);
    });
  }

  function sheetView(d) {
    const students = d.students;
    if (!students.length) return card(null, empty("No students in this class", "Register students under Manage Students first.", "users"));
    const counts = h("div", { class: "row", "aria-live": "polite" });
    const saveBtn = button("Save attendance", { kind: "primary", ico: "check", onClick: save });
    const rowsEl = students.map((s) => {
      const set = h("div", { class: "mark-set", role: "group", "aria-label": `Attendance for ${s.full_name}` });
      const buttons = {};
      const paint = () => Object.entries(buttons).forEach(([k, b]) => b.setAttribute("aria-pressed", marks[s.id] === k ? "true" : "false"));
      [["present", "Present", "check"], ["late", "Late", "clock"], ["absent", "Absent", "x"]].forEach(([k, label, ico]) => {
        buttons[k] = h("button", { type: "button", class: k, "aria-pressed": "false", disabled: !d.can_edit || s.moved, onclick: () => { marks[s.id] = k; paint(); tally(); } }, icon(ico), label);
        set.append(buttons[k]);
      });
      paint();
      s._paint = paint;
      return h("div", { class: "mark-row" }, h("div", { class: "row nm", style: { flexWrap: "nowrap", gap: "10px" } }, h("span", { class: "avatar" }, initials(s.full_name)), h("div", { class: "nm" }, h("b", null, studentLink(s.id, s.full_name)), h("div", { class: "tiny muted" }, s.admission_no, s.moved ? " | moved to another class" : "", s.updated_by ? ` | corrected by ${s.updated_by}` : ""))), set);
    });
    const tally = () => {
      const c = { present: 0, late: 0, absent: 0 };
      students.forEach((s) => { if (marks[s.id]) c[marks[s.id]]++; });
      const marked = c.present + c.late + c.absent, rate = marked ? Math.round(((c.present + (ctx.meta.settings.late_counts_as_present ? c.late : 0)) / marked) * 1000) / 10 : null;
      mount(counts, badge(`${c.present} present`, "good", "check"), badge(`${c.late} late`, "warn", "clock"), badge(`${c.absent} absent`, "bad", "x"), badge(`${students.length - marked} not marked`, ""), h("b", null, rate === null ? "" : `${rate}%`));
      saveBtn.disabled = !d.can_edit || marked < students.filter((s) => !s.moved).length || !dirty();
    };
    tally();
    const markAll = d.can_edit ? button("Mark everyone present", { sm: true, ico: "check", onClick: () => { students.forEach((s) => { if (!s.moved) { marks[s.id] = marks[s.id] || "present"; s._paint(); } }); tally(); } }) : null;
    const reset = d.can_edit ? button("Clear all", { sm: true, onClick: () => { students.forEach((s) => { if (!s.moved && !original[s.id]) delete marks[s.id]; else if (!s.moved) marks[s.id] = original[s.id]; s._paint(); }); tally(); } }) : null;
    async function save() {
      const records = students.filter((s) => !s.moved).map((s) => ({ student_id: s.id, status: marks[s.id] }));
      try {
        const r = await post("/api/attendance/sheet", { class_id: Number(cls.value), date: date.value, records });
        toast(r.created ? `Attendance saved for ${r.created} students.` : r.changed ? `${r.changed} correction${r.changed === 1 ? "" : "s"} saved.` : "No changes to save.", "success");
        await loadSheet();
        ctx.refreshAlertCount?.();
      } catch (e) { errorToast(e); }
    }
    return h("div", { class: "stack" },
      !d.is_school_day ? notice("This date is not a school day.", "warn", "calendar") : null,
      !d.can_edit ? notice(d.edit_reason || "This sheet is read-only.", "", "info") : null,
      d.status.state !== "missing" && d.can_edit ? notice(d.status.state === "recorded" ? "Attendance is already recorded for this date. You can correct it below." : "Attendance is partly recorded for this date.", "", "check") : null,
      h("section", { class: "card" }, h("div", { class: "card-h" }, h("div", null, h("h2", null, `${d.class.name}: ${fmtDate(d.date)}`), h("div", { class: "small muted" }, `${students.length} students | ${statusBadge(d.status.state).textContent}`)), h("div", { class: "row" }, markAll, reset)), h("div", { class: "card-b flush", style: { marginTop: "12px" } }, ...rowsEl),
        h("div", { class: "sticky-bar" }, counts, d.can_edit ? saveBtn : null)));
  }
  loadSheet();
}

// ------------------------------------------------------------ dashboard and reports
function dashboard(ctx, root) {
  const meta = ctx.meta;
  const period = select([["daily", "Daily"], ["weekly", "Weekly"], ["monthly", "Monthly"], ["term", "Academic term"], ["year", "Academic year"], ["custom", "Custom range"]], "daily");
  const date = input({ type: "date", value: meta.today, max: meta.today });
  const cls = select(classOptions(meta), "");
  const term = select(termOptions(meta, "Choose term").slice(1), meta.terms.find((t) => t.is_current)?.id || meta.terms[0]?.id || "");
  const year = select(yearOptions(meta, "").slice(1), meta.years.find((y) => y.is_current)?.id || meta.years[0]?.id || "");
  const from = input({ type: "date", value: meta.today }), to = input({ type: "date", value: meta.today, max: meta.today });
  const fDate = field("Date", date), fTerm = field("Term", term), fYear = field("Year", year), fFrom = field("From", from), fTo = field("To", to);
  const out = h("div");
  const sync = () => {
    const p = period.value;
    fDate.style.display = ["daily", "weekly", "monthly"].includes(p) ? "" : "none"; fTerm.style.display = p === "term" ? "" : "none"; fYear.style.display = p === "year" ? "" : "none";
    fFrom.style.display = fTo.style.display = p === "custom" ? "" : "none";
  };
  const draw = () => { sync(); load(out, async () => {
    const params = { period: period.value, date: date.value, class_id: cls.value, term_id: term.value, year_id: year.value, from: from.value, to: to.value };
    const [a, day] = await Promise.all([get("/api/attendance/analysis", params), get("/api/attendance/dashboard", { date: period.value === "daily" ? date.value : meta.today, class_id: cls.value })]);
    return view(a, day, period.value, ctx);
  }); };
  [period, date, cls, term, year, from, to].forEach((x) => x.addEventListener("change", draw));
  mount(root, h("div", { class: "toolbar" }, field("Report period", period), fDate, fTerm, fYear, fFrom, fTo, field("Class", cls)), out);
  draw();
}

function view(a, day, period, ctx) {
  const t = a.totals, thr = a.thresholds.poor_rate;
  const classesRated = a.by_class.filter((c) => c.rate !== null);
  const dayCols = [
    { key: "class_name", label: "Class", render: (c) => c.class_name }, { key: "registered", label: "Registered", align: "right" }, { key: "recorded", label: "Recorded", align: "right" },
    { key: "present", label: "Present", align: "right" }, { key: "late", label: "Late", align: "right" }, { key: "absent", label: "Absent", align: "right" },
    { key: "rate", label: "Attendance", sortValue: (c) => c.rate ?? -1, render: (c) => (c.rate === null ? h("span", { class: "muted" }, "Not recorded") : rateBar(c.rate, thr)) },
  ];
  return h("div", { class: "stack view" },
    h("div", { class: "grid g-stats" },
      stat({ label: `Registered students (${fmtDate(day.date)})`, value: fmtNum(day.registered), ico: "users" }), stat({ label: "Present", value: fmtNum(day.present), ico: "check", tone: "good" }),
      stat({ label: "Absent", value: fmtNum(day.absent), ico: "x", tone: day.absent ? "bad" : "" }), stat({ label: "Late", value: fmtNum(day.late), ico: "clock" }),
      stat({ label: "Overall attendance", value: fmtPct(day.rate), sub: day.not_recorded ? `${day.not_recorded} not yet recorded` : "", ico: "calendar" })),
    card(`Class attendance on ${fmtDate(day.date)}`, dataTable({ columns: dayCols, rows: day.classes, sortKey: "class_name", empty: empty("No classes", "", "school") }), { flush: true }),
    h("div", { class: "grid g-stats" }, stat({ label: `${a.label}: attendance`, value: fmtPct(t.rate), sub: `${fmtDate(a.from)} to ${fmtDate(a.to)}`, ico: "chart" }), stat({ label: "Present", value: fmtNum(t.present), ico: "check" }), stat({ label: "Late", value: fmtNum(t.late), ico: "clock" }), stat({ label: "Absent", value: fmtNum(t.absent), ico: "x" }), stat({ label: "Records", value: fmtNum(t.total), ico: "list" })),
    h("div", { class: "grid g2" },
      card("Attendance by class", barChart({ title: "Attendance rate by class", labels: classesRated.map((c) => c.class_name), series: [{ name: "Attendance %", values: classesRated.map((c) => c.rate) }], max: 100, format: (v) => `${v}%`, threshold: thr, thresholdLabel: `${thr}% minimum`, emptyText: "No records in this period." })),
      card("Attendance trend", lineChart({ title: "Daily attendance rate", labels: a.series.map((p) => fmtDate(p.date).replace(/, \d{4}$/, "")), series: [{ name: "Attendance %", values: a.series.map((p) => p.rate) }], min: 0, max: 100, format: (v) => `${v}%`, emptyText: "No records in this period." }))),
    h("div", { class: "grid g2" },
      card(`Frequently absent (${a.thresholds.frequent_absences}+ absences)`, dataTable({ rows: a.frequent_absentees, sortKey: "absent", sortDir: "desc", columns: [{ key: "full_name", label: "Student", render: (s) => studentLink(s.student_id, s.full_name) }, { key: "class_name", label: "Class" }, { key: "absent", label: "Absences", align: "right" }, { key: "rate", label: "Attendance", align: "right", render: (s) => fmtPct(s.rate) }], empty: empty("None", "No student has reached the limit.", "check") }), { flush: true }),
      card(`Poor attendance (below ${thr}%)`, dataTable({ rows: a.poor_attendance_students, sortKey: "rate", columns: [{ key: "full_name", label: "Student", render: (s) => studentLink(s.student_id, s.full_name) }, { key: "class_name", label: "Class" }, { key: "total", label: "Days", align: "right" }, { key: "rate", label: "Attendance", align: "right", render: (s) => fmtPct(s.rate) }], empty: empty("None", "Nobody is below the threshold.", "check") }), { flush: true })));
}
