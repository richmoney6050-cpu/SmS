// School-wide academic performance: classes, subjects, students, trends, declines and side-by-side comparison.
import { get } from "../lib/api.js";
import { barChart, hbarChart, lineChart } from "../lib/charts.js";
import { badge, button, card, dataTable, empty, errorToast, field, fmtNum, fmtPct, h, icon, load, mount, notice, pageHead, select, stat, ord } from "../lib/ui.js";
import { gradeBadge, studentLink } from "./common.js";

export async function render(ctx, head, body) {
  mount(head, pageHead("Academic Performance", "Calculated from saved examination marks. Missing marks are never counted as zero."));
  const first = await get("/api/command/academics");
  if (!first.exam_options.length) return mount(body, card(null, empty("No examinations yet", "Create an examination under the Examination module.", "exam")));
  const sel = select(first.exam_options.map((e) => [e.id, `${e.name} | ${e.term} ${e.year}`]), first.exam_id ?? first.exam_options[0].id);
  const out = h("div");
  const draw = () => load(out, async () => view(await get("/api/command/academics", { exam_id: sel.value }), ctx));
  sel.addEventListener("change", draw);
  mount(body, h("div", { class: "toolbar" }, field("Examination", sel)), out);
  await draw();
}

function classRow(c, i) {
  return h("li", null, h("span", { class: "badge info" }, i + 1), h("div", { class: "grow" }, h("b", null, c.class_name), h("div", { class: "tiny muted" }, `${fmtPct(c.pass_rate)} pass`)), h("b", null, fmtPct(c.average)));
}

function view(d, ctx) {
  const ex = d.exam;
  const decl = d.declining.length ? card("Classes with declining performance", h("ul", { class: "list", style: { margin: "-16px -20px -20px" } }, d.declining.map((x) => h("li", { class: "alert-item warning" }, h("span", { class: "feed-ico alert" }, icon("down")), h("div", { class: "grow" }, h("a", { href: `#/dashboard/classes/${x.class_id}` }, h("b", null, x.class_name)), h("div", { class: "small" }, `Average fell from ${fmtPct(x.from.average)} (${x.from.exam}) to ${fmtPct(x.to.average)} (${x.to.exam}).`)), badge(`-${x.drop} pts`, "bad"))))) : notice(`No class has dropped by ${d.decline_threshold} points or more since the previous examination.`, "", "check");
  if (!ex) return h("div", { class: "stack" }, decl, card(null, empty("No complete results for this examination", "Results appear here once marks are entered.", "exam")));
  const t = ex.totals, classes = ex.classes.filter((c) => c.average !== null), subj = ex.subject_performance;
  const trend = d.trends.filter((x) => x.points.length);
  const labels = [...new Map(trend.flatMap((x) => x.points).map((p) => [p.exam_id, p.exam])).values()];
  const order = [...new Map(trend.flatMap((x) => x.points).map((p) => [p.exam_id, p.exam]))];
  return h("div", { class: "stack view" },
    h("div", { class: "grid g-stats" },
      stat({ label: "School average", value: fmtPct(t.average), ico: "chart" }), stat({ label: "Pass rate", value: fmtPct(t.pass_rate), ico: "check", tone: "good" }),
      stat({ label: "Fail rate", value: fmtPct(t.fail_rate), ico: "x", tone: t.fail_rate ? "bad" : "" }), stat({ label: "Highest result", value: fmtPct(t.highest), ico: "up" }),
      stat({ label: "Lowest result", value: fmtPct(t.lowest), ico: "down" }), stat({ label: "Students assessed", value: fmtNum(t.students_assessed), ico: "users" }),
      stat({ label: "Marks lists submitted", value: `${t.subjects_submitted}/${t.subjects_total}`, ico: "exam" })),
    decl,
    h("div", { class: "grid g2" },
      card("Class performance", barChart({ title: "Class average", labels: classes.map((c) => c.class_name), series: [{ name: "Average %", values: classes.map((c) => c.average), color: "var(--s3)" }], max: 100, format: (v) => `${v}%` })),
      card("Subject performance", hbarChart({ title: "Subject average", labels: subj.map((s) => s.subject_name), series: [{ name: "Average %", values: subj.map((s) => s.average), color: "var(--s1)" }], max: 100, format: (v) => `${v}%` }))),
    h("div", { class: "grid g3" },
      card("Highest-performing classes", ex.top_classes.length ? h("ol", { class: "list", style: { margin: "-16px -20px -20px" } }, ex.top_classes.map(classRow)) : empty("No data", "", "chart")),
      card("Lowest-performing classes", ex.bottom_classes.length ? h("ol", { class: "list", style: { margin: "-16px -20px -20px" } }, ex.bottom_classes.map(classRow)) : empty("Not enough classes", "Needs at least two classes with results.", "chart")),
      card("Pass and failure", hbarChart({ title: "Pass and fail by class", labels: classes.map((c) => c.class_name), series: [{ name: "Pass %", values: classes.map((c) => c.pass_rate), color: "var(--good)" }, { name: "Fail %", values: classes.map((c) => c.fail_rate), color: "var(--crit)" }], max: 100, format: (v) => `${v}%`, rowHeight: 50 }))),
    h("div", { class: "grid g2" },
      card("Highest-performing students", dataTable({ rows: ex.top_students, columns: [
        { key: "position", label: "Pos.", align: "center", render: (s) => ord(s.position) }, { key: "student_name", label: "Student", render: (s) => studentLink(s.student_id, s.student_name) }, { key: "class_name", label: "Class" },
        { key: "average", label: "Average", align: "right", render: (s) => fmtPct(s.average) }, { key: "grade", label: "Grade", align: "center", render: (s) => gradeBadge(s.grade) }], empty: empty("No ranked students yet", "Students are ranked once every subject has marks.", "users") }), { flush: true }),
      card(`Students who need academic support (below ${ex.support_threshold ?? d.support_threshold}%)`, dataTable({ rows: ex.support_students, sortKey: "average", columns: [
        { key: "student_name", label: "Student", render: (s) => studentLink(s.student_id, s.student_name) }, { key: "class_name", label: "Class" },
        { key: "average", label: "Average", align: "right", render: (s) => fmtPct(s.average) }, { key: "subjects_done", label: "Subjects", align: "right", render: (s) => `${s.subjects_done}/${s.subjects_total}` }], empty: empty("No student is below the line", "", "check") }), { flush: true })),
    card("Performance trend by class", trend.length && order.length > 1 ? lineChart({ title: "Class average across examinations", labels: order.map(([, n]) => n), series: trend.map((x) => ({ name: x.class_name + (x.declining ? " (declining)" : ""), values: order.map(([id]) => x.points.find((p) => p.exam_id === id)?.average ?? null) })), min: 0, max: 100, format: (v) => `${v}%` }) : h("div", { class: "chart-empty" }, "Trends appear once a class has results from two or more examinations.")),
    compareCard(ctx, d));
}

// Side-by-side comparison of chosen classes, across chosen examinations
export function compareCard(ctx, d) {
  const classes = ctx.meta.classes.filter((c) => c.is_active);
  const chosen = new Set(classes.map((c) => c.id));
  const boxes = classes.map((c) => { const cb = h("input", { type: "checkbox", checked: true }); cb.addEventListener("change", () => { cb.checked ? chosen.add(c.id) : chosen.delete(c.id); draw(); }); return h("label", { class: "check badge info", style: { cursor: "pointer", gap: "6px" } }, cb, c.name); });
  const scope = select([["recent", "Last 4 examinations"], ["term", "Current term"], ["year", "Current year"], ...d.exam_options.map((e) => [`e${e.id}`, `Only: ${e.name}`])], "recent");
  const subjects = select([["", "All subjects"], ...ctx.meta.subjects.map((s) => [s.id, s.name])], "");
  const out = h("div");
  async function draw() {
    if (!chosen.size) return mount(out, h("div", { class: "chart-empty" }, "Choose at least one class."));
    const params = { class_ids: [...chosen].join(","), subject_id: subjects.value };
    const cur = ctx.meta.terms.find((t) => t.is_current);
    if (scope.value === "term" && cur) params.term_id = cur.id;
    else if (scope.value === "year" && cur) params.year_id = cur.year_id;
    else if (scope.value.startsWith("e")) params.exam_ids = scope.value.slice(1);
    await load(out, async () => {
      const r = await get("/api/exams/compare", params);
      if (!r.exams.length) return h("div", { class: "chart-empty" }, "No examinations to compare.");
      const names = r.classes.filter((c) => chosen.has(c.id));
      const series = r.exams.map((e) => ({ name: e.name, values: names.map((c) => e.classes.find((x) => x.class_id === c.id)?.average ?? null) }));
      const pass = r.exams.map((e) => ({ name: e.name, values: names.map((c) => e.classes.find((x) => x.class_id === c.id)?.pass_rate ?? null) }));
      return h("div", { class: "stack" },
        h("div", { class: "grid g2" }, h("div", null, h("h3", null, "Average score"), barChart({ title: "Average score by class and examination", labels: names.map((c) => c.name), series, max: 100, format: (v) => `${v}%`, categoryLabel: "Class" })),
          h("div", null, h("h3", null, "Pass rate"), barChart({ title: "Pass rate by class and examination", labels: names.map((c) => c.name), series: pass, max: 100, format: (v) => `${v}%`, categoryLabel: "Class" }))),
        r.declining.length ? notice("Declining: " + r.declining.slice(0, 5).map((x) => `${x.class_name}${x.subject_name ? " " + x.subject_name : ""} (-${x.drop} pts)`).join("; "), "warn", "down") : null);
    });
  }
  [scope, subjects].forEach((x) => x.addEventListener("change", draw));
  draw();
  return card("Compare classes side by side", h("div", { class: "stack" }, h("div", { class: "pill-row" }, boxes), h("div", { class: "toolbar", style: { marginBottom: 0 } }, field("Examinations", scope), field("Subject", subjects)), out));
}
