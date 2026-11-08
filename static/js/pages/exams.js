// Module 3: Examination and grading.
import { ApiError, del, get, post, put } from "../lib/api.js";
import { barChart, hbarChart } from "../lib/charts.js";
import { applyErrors, badge, button, card, confirmDialog, dataTable, empty, errorToast, field, fmtDate, fmtNum, fmtPct, h, icon, input, load, modal, mount, named, notice, pageHead, select, stat, statusBadge, tabs, toast } from "../lib/ui.js";
import { compareCard } from "./acadmon.js";
import { backLink, classOptions, gradeBadge, studentLink, termOptions, yearOptions } from "./common.js";

export async function render(ctx, view, params) {
  return params[0] ? examPage(ctx, view, Number(params[0])) : list(ctx, view);
}

// ------------------------------------------------------------ list
async function list(ctx, view) {
  const meta = ctx.meta;
  let active = "exams";
  const panel = h("div", { class: "view" }), nav = h("div");
  const actions = ctx.can("exams.manage") ? button("Create examination", { kind: "primary", ico: "plus", onClick: () => createDialog(ctx, () => drawPanel()) }) : null;
  const items = [["exams", "Examinations", "exam"], ["compare", "Compare performance", "chart"]];
  const drawNav = () => mount(nav, tabs(items.map(([i, l, ic]) => ({ id: i, label: l, icon: ic })), active, (t) => { active = t; drawNav(); drawPanel(); }));
  async function drawPanel() {
    if (active === "compare") return load(panel, async () => { const r = await get("/api/exams"); return compareCard(ctx, { exam_options: r.exams.map((e) => ({ id: e.id, name: e.name })) }); });
    const term = select(termOptions(meta), ""), year = select(yearOptions(meta), "");
    const out = h("div");
    const draw = () => load(out, async () => {
      const r = await get("/api/exams", { term_id: term.value, year_id: term.value ? "" : year.value });
      return card(null, dataTable({ rows: r.exams, sortKey: "start_date", sortDir: "desc", onRow: (e) => { location.hash = `#/exams/${e.id}`; }, columns: [
        { key: "name", label: "Examination", render: (e) => h("div", null, h("a", { href: `#/exams/${e.id}` }, h("b", null, e.name)), h("div", { class: "tiny muted" }, `${e.term_name} | ${e.year_name}`)) },
        { key: "start_date", label: "Starts", render: (e) => fmtDate(e.start_date) },
        { key: "marks_due_date", label: "Marks due", render: (e) => h("div", null, fmtDate(e.marks_due_date), e.overdue ? h("div", null, badge("Overdue", "bad", "alert")) : null) },
        { key: "max_total", label: "Total marks", align: "right" },
        { key: "components", label: "Components", sortable: false, render: (e) => h("div", { class: "small" }, e.components.map((c) => `${c.name} (${c.max_marks})`).join(" + ")) },
        { key: "progress", label: "Marks lists", sortValue: (e) => e.progress.submitted / (e.progress.subjects || 1), render: (e) => h("div", null, `${e.progress.submitted}/${e.progress.subjects} submitted`, h("div", { class: "bar " + (e.progress.submitted === e.progress.subjects ? "good" : ""), style: { marginTop: "4px" } }, h("i", { style: { width: (e.progress.subjects ? (e.progress.submitted / e.progress.subjects) * 100 : 0) + "%" } }))) },
        { key: "status", label: "Status", render: (e) => badge(e.status === "open" ? "Open" : "Closed", e.status === "open" ? "good" : "") },
      ], empty: empty("No examinations yet", ctx.can("exams.manage") ? "Create the first examination for this term." : "Examinations involving your classes will appear here.", "exam", actions) }), { flush: true });
    });
    [term, year].forEach((x) => x.addEventListener("change", draw));
    mount(panel, h("div", { class: "toolbar" }, field("Academic term", term), field("Academic year", year)), out);
    await draw();
  }
  mount(view, pageHead("Examination", "Create examinations, enter marks, and review results.", actions), nav, panel);
  drawNav(); await drawPanel();
}

// ------------------------------------------------------------ create
function createDialog(ctx, done) {
  const meta = ctx.meta;
  if (!meta.terms.length) return toast("Add an academic year and term first (Administration > School setup).", "warn", 7000);
  const cur = meta.terms.find((t) => t.is_current) || meta.terms[0];
  const f = {
    name: named("name", field("Examination name", input({ placeholder: "e.g. Mid-Term Test", autocomplete: "off" }), { required: true })),
    term_id: named("term_id", field("Academic term", select(termOptions(meta, "").slice(1), cur.id), { required: true })),
    start_date: named("start_date", field("Starts", input({ type: "date", value: meta.today }), { required: true })),
    marks_due_date: named("marks_due_date", field("Marks due by", input({ type: "date", value: meta.today }), { required: true })),
  };
  const comps = [{ name: "Class tests", kind: "ca", max_marks: 30 }, { name: "Written exam", kind: "exam", max_marks: 70 }];
  const compBox = h("div", { class: "stack-sm" }), total = h("b");
  const drawComps = () => {
    mount(compBox, comps.map((c, i) => h("div", { class: "row", style: { flexWrap: "nowrap", alignItems: "flex-end" } },
      field("Component name", input({ value: c.name, oninput: (e) => { c.name = e.target.value; } })),
      field("Type", select([["ca", "Continuous assessment"], ["exam", "Examination"]], c.kind, { onchange: (e) => { c.kind = e.target.value; } })),
      field("Max marks", input({ type: "number", min: "1", step: "0.5", value: c.max_marks, style: { width: "100px" }, oninput: (e) => { c.max_marks = Number(e.target.value); sum(); } })),
      comps.length > 1 ? button("", { ico: "trash", sm: true, title: "Remove component", onClick: () => { comps.splice(i, 1); drawComps(); sum(); } }) : null)));
    sum();
  };
  const sum = () => { total.textContent = `Total marks: ${comps.reduce((a, c) => a + (Number(c.max_marks) || 0), 0)}`; };
  const classBoxes = meta.classes.filter((c) => c.is_active).map((c) => ({ c, cb: h("input", { type: "checkbox", checked: c.subject_ids.length > 0, disabled: c.subject_ids.length === 0 }) }));
  const form = h("form", { class: "stack", novalidate: true }, h("div", { class: "form-grid" }, ...Object.values(f)),
    h("div", null, h("div", { class: "row between" }, h("h3", null, "Marks components"), button("Add component", { sm: true, ico: "plus", onClick: () => { comps.push({ name: "", kind: "ca", max_marks: 10 }); drawComps(); } })), compBox, total),
    named("class_ids", h("div", { class: "field" }, h("span", { class: "lab" }, "Classes taking this examination"), h("div", { class: "pill-row" }, classBoxes.map(({ c, cb }) => h("label", { class: "check badge info", style: { cursor: "pointer", gap: "6px" }, title: c.subject_ids.length ? "" : "Add subjects to this class first" }, cb, c.name, c.subject_ids.length ? ` (${c.subject_ids.length} subjects)` : " (no subjects)"))), h("div", { class: "hint" }, "Every subject of the chosen classes is included. Teachers enter marks per subject."), h("div", { class: "err" }))));
  drawComps();
  const val = (k) => f[k].querySelector("input,select").value;
  const m = modal({ title: "Create examination", size: "lg", body: form, actions: [h("button", { class: "btn", onclick: () => m.close() }, "Cancel"), button("Create examination", { kind: "primary", onClick: async () => {
    applyErrors(form, null);
    try {
      const r = await post("/api/exams", { name: val("name"), term_id: Number(val("term_id")), start_date: val("start_date"), marks_due_date: val("marks_due_date"), components: comps.map((c) => ({ name: c.name, kind: c.kind, max_marks: c.max_marks })), class_ids: classBoxes.filter((x) => x.cb.checked).map((x) => x.c.id) });
      m.close(); toast(`Examination created with ${r.subject_pairs} class-subject marks lists.` + (r.skipped_classes.length ? ` Skipped (no subjects): ${r.skipped_classes.join(", ")}.` : ""), "success", 7000); location.hash = `#/exams/${r.exam_id}`; done?.();
    } catch (e) { applyErrors(form, e); if (!(e instanceof ApiError)) errorToast(e); }
  } })] });
}

// ------------------------------------------------------------ exam page
async function examPage(ctx, view, id) {
  const q = ctx.query();
  let d;
  try { d = (await get(`/api/exams/${id}`)).exam; } catch (e) { return mount(view, backLink("#/exams", "All examinations"), card(null, empty("Examination not found", e.message, "exam"))); }
  let active = q.get("class") && q.get("subject") ? "marks" : q.get("tab") || "lists";
  const panel = h("div", { class: "view" }), nav = h("div");
  let guard = null;
  const items = [["lists", "Marks entry", "edit"], ["results", "Results dashboard", "chart"], ...(ctx.can("exams.manage") ? [["setup", "Setup", "settings"]] : [])];
  const drawNav = () => mount(nav, tabs(items.map(([i, l, ic]) => ({ id: i, label: l, icon: ic })), active === "marks" ? "lists" : active, async (t) => { if (guard && !(await guard())) return; active = t; guard = null; drawNav(); drawPanel(); }));
  const reload = () => examPage(ctx, view, id);
  const drawPanel = () => {
    if (active === "marks") return marksView(ctx, panel, d, Number(q.get("class")), Number(q.get("subject")), (g) => { guard = g; }, () => { active = "lists"; history.replaceState(null, "", `#/exams/${id}`); drawNav(); drawPanel(); });
    if (active === "lists") return listsView(ctx, panel, d, (cid, sid) => { active = "marks"; q.set("class", cid); q.set("subject", sid); history.replaceState(null, "", `#/exams/${id}?class=${cid}&subject=${sid}`); drawNav(); drawPanel(); }, reload);
    if (active === "results") return resultsView(ctx, panel, d);
    return setupView(ctx, panel, d, reload);
  };
  const comps = d.components.map((c) => `${c.name} (${c.max_marks})`).join(" + ");
  mount(view, backLink("#/exams", "All examinations"), pageHead(d.name, `${d.term_name} | ${d.year_name} | total ${d.max_total} marks = ${comps}`, [badge(d.status === "open" ? "Open" : "Closed", d.status === "open" ? "good" : ""), badge(`Marks due ${fmtDate(d.marks_due_date)}`, d.overdue ? "bad" : "info", d.overdue ? "alert" : "clock")]), nav, panel);
  drawNav(); drawPanel();
  return () => { guard = null; };
}

// ---- class/subject lists
function listsView(ctx, root, d, open, reload) {
  const rows = d.subjects;
  if (!rows.length) return mount(root, card(null, empty("No class subjects in this examination", "Add classes and subjects under Setup.", "exam")));
  const cls = select([["", "All classes"], ...[...new Map(rows.map((r) => [r.class_id, r.class_name])).entries()]], "");
  const out = h("div");
  const draw = () => mount(out, card(null, dataTable({ rows: rows.filter((r) => !cls.value || String(r.class_id) === cls.value), sortKey: "class_name", columns: [
    { key: "class_name", label: "Class" }, { key: "subject_name", label: "Subject" }, { key: "teacher", label: "Teacher", render: (r) => r.teacher || h("span", { class: "muted" }, "Not assigned") },
    { key: "students", label: "Students", align: "right" }, { key: "students_with_marks", label: "With marks", align: "right" },
    { key: "status", label: "Status", render: (r) => statusBadge(r.status === "submitted" ? "submitted" : "pending") },
    { key: "act", label: "", sortable: false, render: (r) => (r.can_enter || ctx.can("exams.view") ? button(r.can_enter && r.status !== "submitted" ? "Enter marks" : "View marks", { sm: true, kind: r.can_enter ? "primary" : "", ico: r.can_enter ? "edit" : "eye", onClick: () => open(r.class_id, r.subject_id) }) : null) },
  ], empty: empty("Nothing here", "", "exam") }), { flush: true }));
  cls.addEventListener("change", draw);
  mount(root, h("div", { class: "toolbar" }, field("Class", cls)), out);
  draw();
}

// ---- marks entry grid
async function marksView(ctx, root, exam, classId, subjectId, setGuard, back) {
  await load(root, async () => {
    const d = await get(`/api/exams/${exam.id}/marks`, { class_id: classId, subject_id: subjectId });
    const bands = ctx.meta.grading.bands, comps = d.components, inputs = new Map(), orig = new Map();
    const gradeOf = (p) => bands.find((b) => p + 1e-9 >= b.min_percent) || bands[bands.length - 1];
    const cells = d.students.map((s) => {
      const tds = comps.map((c) => {
        const v = s.scores[c.id], el = input({ type: "number", inputmode: "decimal", min: "0", max: c.max_marks, step: "0.5", value: v === undefined ? "" : v, class: "input marks-input", "aria-label": `${s.student_name} ${c.name}`, disabled: !d.can_edit });
        inputs.set(`${s.student_id}:${c.id}`, el); orig.set(`${s.student_id}:${c.id}`, v === undefined ? "" : String(v));
        el.addEventListener("input", () => { check(el, c); recompute(s); summary(); });
        el.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); const next = inputs.get(`${d.students[d.students.indexOf(s) + 1]?.student_id}:${c.id}`); next?.focus(); next?.select(); } });
        return h("td", { class: "num" }, el);
      });
      const tot = h("td", { class: "num" }), pct = h("td", { class: "num" }), gr = h("td", { class: "c" });
      s._tot = tot; s._pct = pct; s._gr = gr;
      return h("tr", null, h("td", null, studentLink(s.student_id, s.student_name), h("div", { class: "tiny muted" }, s.admission_no)), ...tds, tot, pct, gr);
    });
    function check(el, c) {
      const raw = el.value.trim(); let bad = false;
      if (raw !== "") { const n = Number(raw); bad = !Number.isFinite(n) || n < 0 || n > c.max_marks; }
      el.classList.toggle("invalid", bad); el.title = bad ? `Enter a number from 0 to ${c.max_marks}` : "";
      return !bad;
    }
    function recompute(s) {
      let all = true, sum = 0, any = false;
      for (const c of comps) { const raw = inputs.get(`${s.student_id}:${c.id}`).value.trim(); if (raw === "" || Number.isNaN(Number(raw))) { all = false; continue; } any = true; sum += Number(raw); }
      sum = Math.round(sum * 100) / 100;
      s._tot.textContent = any ? sum : "-";
      if (all) { const p = Math.round((sum / d.max_total) * 10000) / 100, g = gradeOf(p); s._pct.textContent = fmtPct(p); mount(s._gr, gradeBadge(g.grade, !!g.is_pass)); }
      else { s._pct.textContent = "-"; mount(s._gr, any ? badge("Incomplete", "warn") : h("span", { class: "muted" }, "-")); }
    }
    const sumEl = h("div", { class: "row", "aria-live": "polite" });
    function summary() {
      let complete = 0, partial = 0; d.students.forEach((s) => { const n = comps.filter((c) => inputs.get(`${s.student_id}:${c.id}`).value.trim() !== "").length; if (n === comps.length) complete++; else if (n) partial++; });
      mount(sumEl, badge(`${complete} complete`, "good", "check"), badge(`${partial} partly entered`, partial ? "warn" : ""), badge(`${d.students.length - complete - partial} not entered`, ""));
      saveBtn.disabled = !d.can_edit || !isDirty(); submitBtn && (submitBtn.disabled = !d.can_edit || complete < d.students.length || d.students.length === 0);
    }
    const isDirty = () => [...inputs].some(([k, el]) => el.value.trim() !== orig.get(k));
    const guard = async () => (!isDirty() || (await confirmDialog({ title: "Discard unsaved marks?", message: "You have entered marks that are not saved. Leaving will lose them.", confirmText: "Discard", danger: true })));
    guard.dirty = isDirty; setGuard(guard);
    const saveBtn = button("Save marks", { kind: "primary", ico: "check", onClick: () => save(false) });
    const submitBtn = d.can_edit ? button("Submit marks list", { ico: "upload", onClick: submit }) : null;
    async function save(quiet) {
      let valid = true; d.students.forEach((s) => comps.forEach((c) => { if (!check(inputs.get(`${s.student_id}:${c.id}`), c)) valid = false; }));
      if (!valid) { toast("Some marks are not valid. Fix the highlighted boxes first.", "error"); return false; }
      const rows = d.students.map((s) => ({ student_id: s.student_id, scores: Object.fromEntries(comps.filter((c) => inputs.get(`${s.student_id}:${c.id}`).value.trim() !== orig.get(`${s.student_id}:${c.id}`)).map((c) => [c.id, inputs.get(`${s.student_id}:${c.id}`).value.trim() || null])) })).filter((r) => Object.keys(r.scores).length);
      if (!rows.length) { if (!quiet) toast("No changes to save.", "info"); return true; }
      try {
        const r = await put(`/api/exams/${exam.id}/marks`, { class_id: classId, subject_id: subjectId, rows });
        inputs.forEach((el, k) => orig.set(k, el.value.trim())); summary();
        if (!quiet) toast(`Marks saved (${r.added} added, ${r.changed} changed${r.cleared ? `, ${r.cleared} cleared` : ""}).`, "success");
        return true;
      } catch (e) {
        if (e instanceof ApiError && e.fields) Object.keys(e.fields).forEach((k) => { const el = inputs.get(k); if (el) { el.classList.add("invalid"); el.title = e.fields[k]; } });
        errorToast(e); return false;
      }
    }
    async function submit() {
      if (!(await confirmDialog({ title: "Submit this marks list?", message: `Submitting tells the school that ${d.subject.name} marks for ${d.class.name} are final. You will not be able to change them unless an administrator reopens the list.`, confirmText: "Submit marks" }))) return;
      if (!(await save(true))) return;
      try { await post(`/api/exams/${exam.id}/submit`, { class_id: classId, subject_id: subjectId }); toast("Marks submitted. The Command Centre has been updated.", "success"); setGuard(null); await marksView(ctx, root, exam, classId, subjectId, setGuard, back); ctx.refreshAlertCount?.(); } catch (e) { errorToast(e); }
    }
    const reopen = d.can_reopen ? button("Reopen for editing", { ico: "refresh", onClick: async () => { if (!(await confirmDialog({ title: "Reopen marks list?", message: "The teacher will be able to edit these marks again.", confirmText: "Reopen" }))) return; try { await post(`/api/exams/${exam.id}/reopen`, { class_id: classId, subject_id: subjectId }); toast("Marks list reopened.", "success"); setGuard(null); await marksView(ctx, root, exam, classId, subjectId, setGuard, back); } catch (e) { errorToast(e); } } }) : null;
    const st = d.stats;
    const node = h("div", { class: "stack" },
      h("div", { class: "row between" }, h("div", { class: "row" }, button("All subjects", { sm: true, ico: "chevronLeft", onClick: async () => { if (await guard()) { setGuard(null); back(); } } }), h("h2", null, `${d.subject.name} | ${d.class.name}`), statusBadge(d.status === "submitted" ? "submitted" : "pending")), reopen),
      !d.can_edit ? notice(d.edit_reason || "These marks are read-only.", "", "info") : notice("Leave a box empty if a mark has not been entered. Empty is never counted as zero. A student is graded only when every component has a mark.", "", "info"),
      h("div", { class: "grid g-stats" }, stat({ label: "Class average", value: fmtPct(st.average), ico: "chart" }), stat({ label: "Highest", value: fmtPct(st.highest), ico: "up" }), stat({ label: "Lowest", value: fmtPct(st.lowest), ico: "down" }), stat({ label: "Pass rate", value: fmtPct(st.pass_rate), ico: "check" }), stat({ label: "Marks complete", value: `${st.assessed}/${st.expected}`, ico: "users" })),
      h("section", { class: "card" }, h("div", { class: "table-wrap" }, h("table", { class: "t" }, h("thead", null, h("tr", null, h("th", null, "Student"), ...comps.map((c) => h("th", { class: "num" }, c.name, h("div", { class: "tiny", style: { textTransform: "none", letterSpacing: 0 } }, `${c.kind === "ca" ? "CA" : "Exam"} /${c.max_marks}`))), h("th", { class: "num" }, `Total /${d.max_total}`), h("th", { class: "num" }, "Score"), h("th", { class: "c" }, "Grade"))), h("tbody", null, cells))),
        h("div", { class: "sticky-bar" }, sumEl, d.can_edit ? h("div", { class: "row" }, saveBtn, submitBtn) : null)));
    d.students.forEach((s) => { recompute(s); });
    summary();
    return node;
  });
}

// ---- results dashboard
async function resultsView(ctx, root, exam) {
  const classes = [...new Map(exam.subjects.map((r) => [r.class_id, r.class_name])).entries()];
  const cls = select([["", classes.length > 1 ? "All classes" : classes[0]?.[1] || "All"], ...(classes.length > 1 ? classes : [])], "");
  const out = h("div");
  const draw = () => load(out, async () => {
    const r = await get(`/api/exams/${exam.id}/results`, { class_id: cls.value });
    const t = r.totals, subj = r.subjects.filter((s) => s.average !== null);
    const bySubject = {}; subj.forEach((s) => { (bySubject[s.subject_name] ||= []).push(s.average); });
    const names = Object.keys(bySubject).sort();
    return h("div", { class: "stack" },
      h("div", { class: "grid g-stats" }, stat({ label: "Students assessed", value: fmtNum(t.students_assessed), ico: "users" }), stat({ label: "Highest score", value: fmtPct(t.highest), sub: r.highest_result ? `${r.highest_result.student_name} (${r.highest_result.subject_name})` : "", ico: "up" }),
        stat({ label: "Lowest score", value: fmtPct(t.lowest), sub: r.lowest_result ? `${r.lowest_result.student_name} (${r.lowest_result.subject_name})` : "", ico: "down" }), stat({ label: "Average", value: fmtPct(t.average), ico: "chart" }),
        stat({ label: "Pass", value: fmtPct(t.pass_rate), ico: "check", tone: "good" }), stat({ label: "Fail", value: fmtPct(t.fail_rate), ico: "x", tone: t.fail_rate ? "bad" : "" }), stat({ label: "Marks lists", value: `${t.subjects_submitted}/${t.subjects_total}`, sub: "submitted", ico: "exam" })),
      h("div", { class: "grid g2" },
        card("Subject performance", hbarChart({ title: "Subject averages", labels: names, series: [{ name: "Average %", values: names.map((n) => Math.round((bySubject[n].reduce((a, b) => a + b, 0) / bySubject[n].length) * 100) / 100) }], max: 100, format: (v) => `${v}%`, emptyText: "No subject has complete marks yet." })),
        card("Class performance", barChart({ title: "Class averages", labels: r.classes.filter((c) => c.average !== null).map((c) => c.class_name), series: [{ name: "Average %", values: r.classes.filter((c) => c.average !== null).map((c) => c.average), color: "var(--s3)" }], max: 100, format: (v) => `${v}%`, emptyText: "No class has complete marks yet." }))),
      card("Subjects", dataTable({ rows: r.subjects, sortKey: "class_name", columns: [{ key: "class_name", label: "Class" }, { key: "subject_name", label: "Subject" }, { key: "assessed", label: "Assessed", align: "right", render: (s) => `${s.assessed}/${s.expected}` }, { key: "average", label: "Average", align: "right", sortValue: (s) => s.average ?? -1, render: (s) => fmtPct(s.average) }, { key: "highest", label: "Highest", align: "right", render: (s) => fmtPct(s.highest) }, { key: "lowest", label: "Lowest", align: "right", render: (s) => fmtPct(s.lowest) }, { key: "pass_rate", label: "Pass %", align: "right", render: (s) => fmtPct(s.pass_rate) }, { key: "fail_rate", label: "Fail %", align: "right", render: (s) => fmtPct(s.fail_rate) }, { key: "status", label: "Marks", render: (s) => statusBadge(s.status === "submitted" ? "submitted" : "pending") }] }), { flush: true }),
      card("Individual student performance", dataTable({ rows: r.students, sortKey: "position", columns: [{ key: "class_name", label: "Class" }, { key: "position", label: "Position", align: "center", sortValue: (s) => s.position ?? 9999, render: (s) => (s.position ? `${s.position} of ${s.class_size_ranked}` : h("span", { class: "muted", title: "Ranked only when every subject has marks" }, "-")) }, { key: "student_name", label: "Student", render: (s) => studentLink(s.student_id, s.student_name) }, { key: "average", label: "Average", align: "right", sortValue: (s) => s.average ?? -1, render: (s) => fmtPct(s.average) }, { key: "grade", label: "Grade", align: "center", render: (s) => gradeBadge(s.grade) }, { key: "subjects_done", label: "Subjects complete", align: "right", render: (s) => `${s.subjects_done}/${s.subjects_total}` }], empty: empty("No results yet", "Results appear as marks are entered.", "exam") }), { flush: true }));
  });
  cls.addEventListener("change", draw);
  mount(root, classes.length > 1 ? h("div", { class: "toolbar" }, field("Class", cls)) : null, out);
  await draw();
}

// ---- setup
function setupView(ctx, root, d, reload) {
  const f = {
    name: named("name", field("Examination name", input({ value: d.name }), { required: true })),
    start_date: named("start_date", field("Starts", input({ type: "date", value: d.start_date }), { required: true })),
    marks_due_date: named("marks_due_date", field("Marks due by", input({ type: "date", value: d.marks_due_date }), { required: true })),
    status: named("status", field("Status", select([["open", "Open (marks can be entered)"], ["closed", "Closed (locked for teachers)"]], d.status))),
  };
  const comps = d.components.map((c) => ({ ...c }));
  const compBox = h("div", { class: "stack-sm" });
  const drawComps = () => mount(compBox, comps.map((c, i) => h("div", { class: "row", style: { flexWrap: "nowrap", alignItems: "flex-end" } },
    field("Component", input({ value: c.name, oninput: (e) => { c.name = e.target.value; } })), field("Type", select([["ca", "Continuous assessment"], ["exam", "Examination"]], c.kind, { onchange: (e) => { c.kind = e.target.value; } })),
    field("Max marks", input({ type: "number", min: "1", step: "0.5", value: c.max_marks, style: { width: "100px" }, oninput: (e) => { c.max_marks = Number(e.target.value); } })),
    comps.length > 1 ? button("", { ico: "trash", sm: true, onClick: () => { comps.splice(i, 1); drawComps(); } }) : null)));
  drawComps();
  const form = h("form", { class: "stack", novalidate: true }, h("div", { class: "form-grid" }, ...Object.values(f)), h("div", null, h("div", { class: "row between" }, h("h3", null, "Marks components"), button("Add component", { sm: true, ico: "plus", onClick: () => { comps.push({ id: null, name: "", kind: "ca", max_marks: 10 }); drawComps(); } })), compBox,
    d.subjects.some((s) => s.status === "submitted") ? notice("Some marks are already submitted. Reopen them before adding or removing components.", "warn", "alert") : null));
  const val = (k) => f[k].querySelector("input,select").value;
  const saveBtn = button("Save changes", { kind: "primary", ico: "check", onClick: async () => {
    applyErrors(form, null);
    try { await put(`/api/exams/${d.id}`, { name: val("name"), start_date: val("start_date"), marks_due_date: val("marks_due_date"), status: val("status"), components: comps.map((c) => ({ id: c.id, name: c.name, kind: c.kind, max_marks: c.max_marks })) }); toast("Examination updated.", "success"); reload(); }
    catch (e) { applyErrors(form, e); if (!(e instanceof ApiError)) errorToast(e); }
  } });
  const pairs = card("Classes and subjects in this examination", h("div", { class: "stack-sm" }, dataTable({ rows: d.subjects, sortKey: "class_name", columns: [{ key: "class_name", label: "Class" }, { key: "subject_name", label: "Subject" }, { key: "status", label: "Marks", render: (r) => statusBadge(r.status === "submitted" ? "submitted" : "pending") },
    { key: "act", label: "", sortable: false, render: (r) => button("Remove", { sm: true, ico: "trash", onClick: async () => { if (!(await confirmDialog({ title: "Remove from examination?", message: `${r.subject_name} for ${r.class_name} will no longer be part of this examination.`, confirmText: "Remove", danger: true }))) return; try { await del(`/api/exams/${d.id}/subjects/${r.id}`); toast("Removed.", "success"); reload(); } catch (e) { errorToast(e); } } }) }] }),
    button("Add class and subject", { ico: "plus", onClick: () => addPairDialog(ctx, d, reload) })), { flush: true });
  const danger = card("Delete examination", h("div", { class: "row between" }, h("p", { class: "muted" }, "Only possible while no marks have been entered."), button("Delete examination", { kind: "danger", ico: "trash", onClick: async () => { if (!(await confirmDialog({ title: "Delete examination?", message: `${d.name} will be deleted. This cannot be undone.`, confirmText: "Delete", danger: true }))) return; try { await del(`/api/exams/${d.id}`); toast("Examination deleted.", "success"); location.hash = "#/exams"; } catch (e) { errorToast(e); } } })));
  mount(root, h("div", { class: "stack" }, card("Examination details", h("div", { class: "stack" }, form, h("div", null, saveBtn))), pairs, danger));
}

function addPairDialog(ctx, d, reload) {
  const taken = new Set(d.subjects.map((s) => `${s.class_id}:${s.subject_id}`));
  const options = [];
  ctx.meta.classes.filter((c) => c.is_active).forEach((c) => c.subject_ids.forEach((sid) => { if (!taken.has(`${c.id}:${sid}`)) options.push({ c, s: ctx.meta.subjects.find((x) => x.id === sid) }); }));
  if (!options.length) return toast("Every subject of every class is already included.", "info");
  const boxes = options.map((o) => ({ o, cb: h("input", { type: "checkbox" }) }));
  const m = modal({ title: "Add classes and subjects", size: "sm", body: h("div", { class: "stack-sm" }, boxes.map(({ o, cb }) => h("label", { class: "check" }, cb, `${o.c.name}: ${o.s.name}`))), actions: [h("button", { class: "btn", onclick: () => m.close() }, "Cancel"), button("Add selected", { kind: "primary", onClick: async () => {
    const pairs = boxes.filter((b) => b.cb.checked).map((b) => ({ class_id: b.o.c.id, subject_id: b.o.s.id }));
    if (!pairs.length) return toast("Choose at least one.", "warn");
    try { const r = await post(`/api/exams/${d.id}/subjects`, { pairs }); m.close(); toast(`${r.added} added.`, "success"); reload(); } catch (e) { errorToast(e); }
  } })] });
}
