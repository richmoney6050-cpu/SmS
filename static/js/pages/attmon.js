// School-wide attendance monitoring: filter by date, class, term and year; click a class to see who is absent.
import { get } from "../lib/api.js";
import { barChart, lineChart } from "../lib/charts.js";
import { badge, card, dataTable, empty, field, fmtDate, fmtNum, fmtPct, h, icon, input, load, modal, mount, notice, pageHead, rateBar, select, stat, statusBadge } from "../lib/ui.js";
import { classOptions, studentLink, termOptions, yearOptions } from "./common.js";

export async function render(ctx, head, body) {
  const meta = ctx.meta;
  mount(head, pageHead("School-wide Attendance", "Attendance across every class, from the records teachers have saved."));
  const date = input({ type: "date", value: meta.today, max: meta.today });
  const cls = select(classOptions(meta), "");
  const term = select(termOptions(meta, "No term filter"), "");
  const year = select(yearOptions(meta, "No year filter"), "");
  const out = h("div");
  const draw = () => load(out, async () => {
    const d = await get("/api/command/attendance", { date: date.value, class_id: cls.value, term_id: term.value, year_id: !term.value ? year.value : "" });
    return view(d, date.value, ctx);
  });
  [date, cls, term, year].forEach((x) => x.addEventListener("change", draw));
  term.addEventListener("change", () => { if (term.value) year.value = ""; });
  mount(body, h("div", { class: "toolbar" }, field("Date", date), field("Class", cls), field("Academic term", term), field("Academic year", year)), out);
  await draw();
}

function view(d, date, ctx) {
  const s = d.snapshot, r = d.range, thr = d.threshold;
  const classes = s.classes.filter((c) => c.rate !== null);
  const rangeSeries = r.series;
  const tableCols = [
    { key: "class_name", label: "Class", render: (c) => h("a", { href: `#/dashboard/classes/${c.class_id}` }, c.class_name) },
    { key: "registered", label: "Students", align: "right" },
    { key: "state", label: "Status", render: (c) => statusBadge(c.state) },
    { key: "present", label: "Present", align: "right" }, { key: "late", label: "Late", align: "right" }, { key: "absent", label: "Absent", align: "right" },
    { key: "rate", label: "Attendance", sortValue: (c) => c.rate ?? -1, render: (c) => (c.rate === null ? h("span", { class: "muted" }, "-") : rateBar(c.rate, thr)) },
    { key: "view", label: "", sortable: false, render: (c) => (c.recorded ? h("button", { class: "btn sm", type: "button", onclick: () => absentees(c, date) }, icon("users"), "Who is absent") : null) },
  ];
  return h("div", { class: "stack view" },
    !d.is_school_day ? notice("The selected date is not a school day, so no attendance is expected.", "warn", "calendar") : null,
    h("div", { class: "grid g-stats" },
      stat({ label: "School attendance", value: fmtPct(s.rate), sub: fmtDate(d.date), ico: "calendar", tone: s.rate === null ? "" : s.rate >= thr + 10 ? "good" : s.rate >= thr ? "warn" : "bad" }),
      stat({ label: "Present", value: fmtNum(s.present), ico: "check", tone: "good" }), stat({ label: "Late", value: fmtNum(s.late), ico: "clock" }),
      stat({ label: "Absent", value: fmtNum(s.absent), ico: "x", tone: s.absent ? "bad" : "" }), stat({ label: "Registered", value: fmtNum(s.registered), ico: "users" })),
    h("div", { class: "grid g-main" },
      card("Class-by-class attendance", barChart({ title: "Attendance rate by class", labels: classes.map((c) => c.class_name), series: [{ name: "Attendance %", values: classes.map((c) => c.rate), color: "var(--s1)" }], max: 100, format: (v) => `${v}%`, threshold: thr, thresholdLabel: `${thr}% minimum`, emptyText: "No class has recorded attendance on this date." })),
      card(`Poor attendance (${r.label})`, d.poor_classes.length ? h("ul", { class: "list", style: { margin: "-16px -20px -20px" } }, d.poor_classes.map((c) => h("li", null, h("span", { class: "feed-ico critical alert" }, icon("alert")), h("div", { class: "grow" }, h("a", { href: `#/dashboard/classes/${c.class_id}` }, h("b", null, c.class_name)), h("div", { class: "small muted" }, `${fmtPct(c.rate)} over ${fmtNum(c.total)} records`)), badge(fmtPct(c.rate), "bad")))) : empty("No class is below the line", `Every class is at or above ${thr}%.`, "check"))),
    card(`Attendance on ${fmtDate(d.date)}`, dataTable({ columns: tableCols, rows: s.classes, sortKey: "class_name", empty: empty("No classes", "", "school") }), { flush: true }),
    card(`Trend: ${r.label} (${fmtDate(r.from)} to ${fmtDate(r.to)})`, lineChart({ title: "Daily school attendance", labels: rangeSeries.map((p) => fmtDate(p.date).replace(/, \d{4}$/, "")), series: [{ name: "Attendance %", values: rangeSeries.map((p) => p.rate), color: "var(--s1)" }], min: 0, max: 100, format: (v) => `${v}%`, emptyText: "No records in this period." })),
    h("div", { class: "grid g2" },
      card(`Frequently absent (${r.thresholds.frequent_absences}+ absences)`, dataTable({ rows: r.frequent_absentees, sortKey: "absent", sortDir: "desc", columns: [
        { key: "full_name", label: "Student", render: (s2) => studentLink(s2.student_id, s2.full_name) }, { key: "class_name", label: "Class" }, { key: "absent", label: "Absences", align: "right" }, { key: "rate", label: "Attendance", align: "right", render: (s2) => fmtPct(s2.rate) }],
        empty: empty("None", "No student has reached the repeated-absence limit.", "check") }), { flush: true }),
      card(`Students with poor attendance (below ${r.thresholds.poor_rate}%)`, dataTable({ rows: r.poor_attendance_students, sortKey: "rate", columns: [
        { key: "full_name", label: "Student", render: (s2) => studentLink(s2.student_id, s2.full_name) }, { key: "class_name", label: "Class" }, { key: "total", label: "Days", align: "right" }, { key: "rate", label: "Attendance", align: "right", render: (s2) => fmtPct(s2.rate) }],
        empty: empty("None", "No student is below the threshold.", "check") }), { flush: true })));
}

async function absentees(c, date) {
  const body = h("div");
  const m = modal({ title: `${c.class_name}: absent on ${fmtDate(date)}`, size: "lg", body });
  await load(body, async () => {
    const d = await get("/api/command/attendance/absentees", { class_id: c.class_id, date });
    const list = (title, rows, tone) => rows.length ? card(`${title} (${rows.length})`, dataTable({ rows, sortKey: "full_name", columns: [
      { key: "full_name", label: "Student", render: (s) => studentLink(s.student_id, s.full_name) }, { key: "admission_no", label: "Admission no." },
      { key: "guardian_name", label: "Guardian" }, { key: "guardian_contact", label: "Contact" }], }), { flush: true }) : null;
    if (!d.absent.length && !d.late.length) return empty("Nobody is absent or late", d.state === "missing" ? "Attendance has not been recorded for this class on this date." : "Every recorded student was present.", "check");
    return h("div", { class: "stack" }, h("div", { class: "row" }, badge(`${d.summary.present} present`, "good", "check"), badge(`${d.summary.late} late`, "warn", "clock"), badge(`${d.summary.absent} absent`, "bad", "x"), h("b", null, fmtPct(d.summary.rate))), list("Absent", d.absent), list("Late", d.late));
  });
}
