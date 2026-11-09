// Module 4: Reports. One structured document per report; screen, print and PDF all come from it.
import { ApiError, del, download, get, put } from "../lib/api.js";
import { applyErrors, button, card, confirmDialog, empty, errorToast, field, fmtNum, h, input, load, mount, notice, pageHead, select, tabs, textarea, toast, debounce, loading } from "../lib/ui.js";
import { classOptions } from "./common.js";

const KINDS = [["student", "Student report", "users", "reports.student"], ["class", "Class report", "school", "reports.class"], ["school", "School-wide reports", "chart", "reports.school"]];

export async function render(ctx, view) {
  const q = ctx.query();
  const avail = KINDS.filter((k) => ctx.can(k[3]));
  if (!avail.length) return mount(view, pageHead("Reports"), card(null, empty("No report access", "Your account cannot generate reports.", "chart")));
  let active = avail.some((k) => k[0] === q.get("kind")) ? q.get("kind") : avail[0][0];
  const nav = h("div"), panel = h("div", { class: "view" });
  const drawNav = () => mount(nav, tabs(avail.map(([id, label, ico]) => ({ id, label, icon: ico })), active, (t) => { active = t; drawNav(); drawPanel(); }));
  const drawPanel = () => ({ student: studentTab, class: classTab, school: schoolTab })[active](ctx, panel, q);
  mount(view, pageHead("Reports", "Generate student, class and school-wide reports. View on screen, print, or download as PDF."), nav, panel);
  drawNav(); drawPanel();
}

// ------------------------------------------------------------ shared: document renderer + toolbar
function renderDoc(doc) {
  const sch = doc.school || {};
  const logo = sch.has_logo ? h("img", { src: `/api/auth/school-logo?t=${encodeURIComponent(doc.generated_at)}`, alt: "School logo" }) : null;
  const blocks = doc.blocks.map((b) => {
    const title = b.title ? h("h3", null, b.title) : null;
    if (b.type === "kv") return h("div", { class: "rsec" }, title, h("dl", { class: "def" }, b.items.map(([k, v]) => h("div", null, h("dt", null, k), h("dd", null, v === null || v === undefined || v === "" ? "-" : String(v))))));
    if (b.type === "stats") return h("div", { class: "rsec" }, title, h("div", { class: "stats" }, b.items.map((i) => h("div", null, h("b", null, i.value === null || i.value === undefined ? "-" : String(i.value)), h("span", null, i.label)))));
    if (b.type === "text") return h("div", { class: "rsec" }, title, h("p", null, b.text));
    if (b.type === "table") {
      const al = (c) => (c.align === "right" ? "num" : c.align === "center" ? "c" : "");
      return h("div", { class: "rsec" }, title, h("div", { class: "table-wrap" }, h("table", { class: "t" },
        h("thead", null, h("tr", null, b.columns.map((c) => h("th", { class: al(c) }, c.label)))),
        h("tbody", null, b.rows.length ? b.rows.map((r) => h("tr", null, b.columns.map((c) => h("td", { class: al(c) }, r[c.key] === null || r[c.key] === undefined || r[c.key] === "" ? "-" : String(r[c.key]))))) : h("tr", null, h("td", { colspan: b.columns.length, class: "muted" }, b.empty || "No data.")))),
      ), b.note ? h("div", { class: "note" }, b.note) : null);
    }
    return null;
  });
  return h("article", { class: "report", "aria-label": doc.title },
    h("div", { class: "letterhead" }, logo, h("div", null, h("h2", null, sch.name || "School"), sch.motto ? h("div", { class: "small" }, sch.motto) : null, h("div", { class: "tiny" }, [sch.address, sch.phone, sch.email].filter(Boolean).join(" | ")))),
    h("h1", null, doc.title), doc.subtitle ? h("div", { class: "muted" }, doc.subtitle) : null, ...blocks,
    h("div", { class: "foot" }, h("span", null, `Generated ${doc.generated_at} by ${doc.generated_by}`), h("span", null, doc.footer || "")));
}

// Generic report runner: fetches the document and shows it with Print / PDF actions
function runner(url, params, fallback, extra) {
  const out = h("div", { class: "stack" });
  const bar = h("div", { class: "row no-print", style: { justifyContent: "flex-end" } });
  const holder = h("div");
  async function run() {
    mount(holder, loading("Generating report..."));
    mount(bar);
    try {
      const r = await get(url, params());
      mount(holder, renderDoc(r.report));
      extra?.(r.report, holder);
      mount(bar,
        button("Print", { ico: "printer", onClick: () => window.print() }),
        button("Excel", { ico: "download", onClick: async (e) => {
          const b = e.currentTarget; b.disabled = true;
          try { await download(url, { ...params(), format: "xlsx" }, `${fallback}.xlsx`); toast("Excel file downloaded.", "success"); } catch (err) { errorToast(err); } finally { b.disabled = false; }
        } }),
        button("Download PDF", { kind: "primary", ico: "download", onClick: async (e) => {
          const b = e.currentTarget; b.disabled = true;
          try { await download(url, { ...params(), format: "pdf" }, `${fallback}.pdf`); toast("PDF downloaded.", "success"); } catch (err) { errorToast(err); } finally { b.disabled = false; }
        } }));
    } catch (e) { mount(holder, notice(e instanceof ApiError ? e.message : "The report could not be generated.", "bad", "alert")); }
  }
  mount(out, bar, holder);
  return { node: out, run, clear: () => { mount(holder); mount(bar); } };
}

const examOptions = async (classId) => {
  const r = await get("/api/exams");
  const list = classId ? r.exams.filter((e) => e.class_ids?.includes(Number(classId)) ?? true) : r.exams;
  return [["", "Latest available"], ...list.map((e) => [e.id, `${e.name} | ${e.term_name} ${e.year_name}`])];
};

// ------------------------------------------------------------ student report
function studentTab(ctx, root, q) {
  let chosen = null;
  const search = input({ type: "search", placeholder: "Search by name or admission number", autocomplete: "off", "aria-label": "Find student" });
  const results = h("div", { class: "pill-row" }), exam = select([["", "Latest available"]], ""), holder = h("div");
  const sel = h("div", { class: "small muted" }, "No student chosen.");
  const rep = runner("/api/reports/student/" + "0", () => ({}), "report");
  let current = null;

  async function show() {
    if (!chosen) return;
    const url = `/api/reports/report-card/${chosen.id}`;
    current = runner(url, () => ({ exam_id: exam.value }), `student-report-${chosen.admission_no || chosen.id}`, (doc, node) => remarksEditor(doc, node, show, ctx));
    mount(holder, current.node); await current.run();
  }
  async function pick(s) {
    chosen = s; mount(sel, h("b", null, s.full_name), ` (${s.admission_no})`, s.class_name ? ` | ${s.class_name}` : ""); mount(results);
    try { const opts = await examOptions(); mount(exam, ...opts.map(([v, l]) => h("option", { value: v }, l))); } catch { /* optional */ }
    show();
  }
  const find = debounce(async () => {
    const t = search.value.trim();
    if (t.length < 2) return mount(results);
    try {
      const r = await get("/api/students", { q: t, per_page: 8 });
      mount(results, r.items.length ? r.items.map((s) => h("button", { class: "btn sm", type: "button", onclick: () => pick(s) }, `${s.full_name} (${s.admission_no})`)) : h("span", { class: "muted small" }, "No matching student."));
    } catch (e) { errorToast(e); }
  }, 250);
  search.addEventListener("input", find);
  exam.addEventListener("change", show);
  mount(root, card(null, h("div", { class: "stack-sm" }, h("div", { class: "toolbar", style: { marginBottom: 0 } }, field("Student", search), field("Examination", exam)), results, sel)), holder);
  if (q.get("student")) get(`/api/students/${q.get("student")}`).then((r) => pick({ id: r.student.id, full_name: r.student.full_name, admission_no: r.student.admission_no, class_name: r.student.class_name })).catch(() => {});
  else mount(holder, card(null, empty("Choose a student", "Search above to generate a student report.", "users")));
}

function remarksEditor(doc, node, refresh, ctx) {
  const r = doc.remarks;
  if (!r) return;
  const tNode = textarea({ rows: 3, maxlength: 600 }); tNode.value = r.teacher || "";
  const hNode = textarea({ rows: 3, maxlength: 600 }); hNode.value = r.headmaster || "";
  const canHead = ctx.can("reports.school");
  if (!canHead) hNode.disabled = true;
  const save = async () => {
    try {
      const d = { student_id: r.student_id, exam_id: r.exam_id, comment: tNode.value };
      if (canHead) d.headmaster_comment = hNode.value;
      await put("/api/reports/remarks", d); toast("Remarks saved.", "success"); refresh();
    } catch (e) { errorToast(e); }
  };
  const box = h("div", { class: "card no-print", style: { marginTop: "14px" } }, h("div", { class: "card-b stack-sm" },
    h("h3", null, "Remarks"), h("div", { class: "hint" }, "Generated from the results until you write your own."),
    field("Class teacher's remark", tNode), field(canHead ? "Headmaster's remark" : "Headmaster's remark (headmaster only)", hNode),
    h("div", { class: "row" }, button("Save remarks", { kind: "primary", sm: true, ico: "check", onClick: save }))));
  node.parentElement ? node.parentElement.appendChild(box) : node.appendChild(box);
}

// ------------------------------------------------------------ class report
function classTab(ctx, root, q) {
  const cls = select(classOptions(ctx.meta, { all: "Choose a class" }), q.get("class") || "");
  const exam = select([["", "Latest available"]], "");
  const holder = h("div");
  let r = null;
  const show = async () => {
    if (!cls.value) return mount(holder, card(null, empty("Choose a class", "Pick a class to generate its report.", "school")));
    const name = ctx.meta.classes.find((c) => String(c.id) === cls.value)?.name || "class";
    r = runner(`/api/reports/class/${cls.value}`, () => ({ exam_id: exam.value }), `class-report-${name}`);
    mount(holder, r.node); await r.run();
  };
  cls.addEventListener("change", async () => { try { const opts = await examOptions(cls.value); mount(exam, ...opts.map(([v, l]) => h("option", { value: v }, l))); } catch { /* optional */ } show(); });
  exam.addEventListener("change", show);
  const dl = (path, ext, label) => button(label, { ico: "download", onClick: async (e) => {
    if (!cls.value) return toast("Choose a class first.", "error");
    const b = e.currentTarget; b.disabled = true;
    try { await download(`/api/reports/${path}/${cls.value}`, { exam_id: exam.value, format: ext }, `${path.replace("/", "-")}-${cls.value}.${ext}`); toast("Downloaded.", "success"); } catch (err) { errorToast(err); } finally { b.disabled = false; }
  } });
  mount(root, h("div", { class: "toolbar" }, field("Class", cls), field("Examination", exam), dl("report-cards/class", "pdf", "All report cards (PDF)"), dl("broadsheet", "pdf", "Broadsheet (PDF)"), dl("broadsheet", "xlsx", "Broadsheet (Excel)")), holder);
  if (cls.value) cls.dispatchEvent(new Event("change")); else show();
}

// ------------------------------------------------------------ school-wide reports
async function schoolTab(ctx, root) {
  await load(root, async () => {
    const { types } = await get("/api/reports/school/types");
    const kind = select(types.map((t) => [t.id, t.label]), types[0].id);
    const holder = h("div");
    const show = async () => {
      const r = runner(`/api/reports/school/${kind.value}`, () => ({}), `school-${kind.value}`);
      mount(holder, r.node); await r.run();
    };
    kind.addEventListener("change", show);
    setTimeout(show, 0);
    return h("div", { class: "stack" }, h("div", { class: "toolbar" }, field("Report type", kind)), holder);
  });
}
