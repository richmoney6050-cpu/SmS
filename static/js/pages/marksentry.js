// Examination workflow: class -> students of that class -> one student's marks for every subject.
import { get, put } from "../lib/api.js";
import { applyErrors, badge, button, card, confirmDialog, empty, errorToast, field, fmtNum, fmtPct, h, input, load, mount, notice, select, toast } from "../lib/ui.js";
import { gradeBadge } from "./common.js";

export function entryTab(ctx) {
  const root = h("div", { class: "view stack" });
  const st = { exam: null, classId: null };
  const classes = ctx.meta.classes.filter((c) => c.is_active);

  async function pickClass() {
    mount(root, h("h2", null, "Step 1: choose a class"), h("div", { class: "hint" }, "These are the classes created under Manage Students."));
    await load(root, async () => {
      const r = await get("/api/exams");
      const open = r.exams.filter((e) => e.status === "open");
      if (!r.exams.length) return empty("No examination yet", ctx.can("exams.manage") ? "Create an examination first (use the Create examination button above)." : "Ask the administrator to create an examination.", "exam");
      const list = open.length ? open : r.exams;
      st.exam = st.exam && list.find((e) => e.id === st.exam.id) ? st.exam : list[0];
      const exam = select(list.map((e) => [e.id, `${e.name} | ${e.term_name} ${e.year_name}${e.status === "open" ? "" : " (closed)"}`]), st.exam.id);
      exam.addEventListener("change", () => { st.exam = list.find((e) => String(e.id) === exam.value); });
      const cards = classes.length ? h("div", { class: "grid g-stats class-pick" }, classes.map((c) => h("button", { type: "button", class: "card class-card", onclick: () => { st.classId = c.id; pickStudent(); } },
        h("div", { class: "card-b" }, h("b", null, c.name), h("div", { class: "small muted" }, "View students")))))
        : empty("No classes available", "Create classes under Attendance or Administration, then register students.", "school");
      return h("div", { class: "stack" }, h("h2", null, "Step 1: choose a class"), field("Examination", exam), cards);
    });
  }

  async function pickStudent() {
    await load(root, async () => {
      const d = await get(`/api/exams/${st.exam.id}/class-students`, { class_id: st.classId });
      const cls = classes.find((c) => c.id === st.classId);
      const q = input({ type: "search", placeholder: "Search by name or admission number", "aria-label": "Search students" });
      const body = h("div");
      const draw = () => {
        const t = q.value.trim().toLowerCase();
        const items = d.students.filter((s) => !t || s.name.toLowerCase().includes(t) || s.admission_no.toLowerCase().includes(t));
        mount(body, items.length ? h("div", { class: "table-wrap" }, h("table", { class: "t" },
          h("thead", null, h("tr", null, ["Student", "Admission no.", "Marks entered", ""].map((x) => h("th", null, x)))),
          h("tbody", null, items.map((s) => h("tr", { class: "clickable", onclick: () => openStudent(s.id) },
            h("td", null, h("a", { href: "javascript:void 0", onclick: (e) => { e.preventDefault(); } }, s.name)), h("td", null, s.admission_no),
            h("td", null, d.subjects ? (s.complete === d.subjects ? badge("All subjects", "good") : badge(`${s.complete} of ${d.subjects} subjects`, s.complete || s.partial ? "warn" : "")) : "-"),
            h("td", null, button("Enter marks", { sm: true, kind: "primary", onClick: (e) => { e.stopPropagation(); openStudent(s.id); } }))))))) : empty("No students found", d.students.length ? "Try a different search." : "No students are registered in this class yet. Add them under Manage Students.", "users"));
      };
      q.addEventListener("input", draw); draw();
      return h("div", { class: "stack" },
        h("div", { class: "row" }, button("All classes", { sm: true, ico: "chevronLeft", onClick: pickClass }), h("h2", null, `Step 2: ${cls ? cls.name : "Class"} | ${d.exam.name}`)),
        d.subjects ? null : notice("No subjects are assigned to this class in this examination. Add them in the examination's Setup tab.", "warn"),
        field("Find a student", q), card(null, body, { flush: true }));
    });
  }

  async function openStudent(sid) {
    await load(root, async () => {
      const d = await get(`/api/exams/${st.exam.id}/student-marks`, { class_id: st.classId, student_id: sid });
      const roster = (await get(`/api/exams/${st.exam.id}/class-students`, { class_id: st.classId })).students;
      const idx = roster.findIndex((s) => s.id === sid);
      const bands = ctx.meta.grading.bands, comps = d.components, inputs = new Map(), orig = new Map();
      const gradeOf = (p) => bands.find((b) => p + 1e-9 >= b.min_percent) || bands[bands.length - 1];
      const dirty = () => [...inputs].some(([k, el]) => el.value !== orig.get(k));
      const leave = async (fn) => { if (!dirty() || (await confirmDialog({ title: "Leave without saving?", message: "Your unsaved marks will be lost.", confirmText: "Leave" }))) fn(); };
      const rowsEls = d.subjects.map((s) => {
        const tot = h("td", { class: "num" }), gr = h("td", { class: "c" }), rem = h("td", null);
        const recompute = () => {
          let sum = 0, ok = true;
          for (const c of comps) { const el = inputs.get(`${s.subject_id}:${c.id}`); if (el.value === "" || Number.isNaN(Number(el.value))) ok = false; else sum += Number(el.value); }
          if (!ok) { tot.textContent = "-"; mount(gr, "-"); rem.textContent = "-"; return; }
          const pct = d.max_total ? sum / d.max_total * 100 : 0, b = gradeOf(pct);
          tot.textContent = `${fmtNum(sum)} / ${fmtNum(d.max_total)}`; mount(gr, gradeBadge(b.grade)); rem.textContent = b.remark || "";
        };
        const tds = comps.map((c) => {
          const v = s.scores[c.id];
          const el = input({ type: "number", inputmode: "decimal", min: "0", max: c.max_marks, step: "0.5", value: v === undefined ? "" : v, class: "input marks-input", "aria-label": `${s.subject_name} ${c.name}`, disabled: !s.can_edit });
          inputs.set(`${s.subject_id}:${c.id}`, el); orig.set(`${s.subject_id}:${c.id}`, v === undefined ? "" : String(v));
          el.addEventListener("input", () => { const n = Number(el.value); el.classList.toggle("invalid", el.value !== "" && (n < 0 || n > c.max_marks || Number.isNaN(n))); recompute(); });
          return h("td", { class: "num" }, el);
        });
        recompute();
        return h("tr", null, h("td", null, h("b", null, s.subject_name), s.can_edit ? null : h("div", { class: "tiny muted" }, s.edit_reason || "Locked")), tds, tot, gr, rem);
      });
      const editable = d.subjects.filter((s) => s.can_edit);
      const save = button("Save marks", { kind: "primary", ico: "check", disabled: !editable.length, onClick: async (e) => {
        const b = e.currentTarget; b.disabled = true;
        const subjects = editable.map((s) => ({ subject_id: s.subject_id, scores: Object.fromEntries(comps.map((c) => [String(c.id), inputs.get(`${s.subject_id}:${c.id}`).value])) }));
        try {
          const r = await put(`/api/exams/${st.exam.id}/student-marks`, { class_id: st.classId, student_id: sid, subjects });
          toast(r.added || r.changed || r.cleared ? `Marks saved for ${d.student.name}.` : "No changes to save.", "success");
          openStudent(sid);
        } catch (err) {
          if (err.fields) { for (const [k, v] of Object.entries(err.fields)) inputs.get(k)?.classList.add("invalid"); const f = Object.keys(err.fields)[0]; inputs.get(f)?.focus(); }
          errorToast(err); b.disabled = false;
        }
      } });
      const nav = (o) => roster[idx + o] ? button(o < 0 ? "Previous student" : "Next student", { sm: true, onClick: () => leave(() => openStudent(roster[idx + o].id)) }) : null;
      return h("div", { class: "stack" },
        h("div", { class: "row between" }, h("div", { class: "row" }, button("Students", { sm: true, ico: "chevronLeft", onClick: () => leave(pickStudent) }), h("h2", null, "Step 3: enter marks")), h("div", { class: "row" }, nav(-1), nav(1))),
        card(null, h("div", { class: "grid g-stats" },
          h("div", null, h("div", { class: "small muted" }, "Student"), h("b", null, d.student.name), h("div", { class: "tiny muted" }, d.student.admission_no)),
          h("div", null, h("div", { class: "small muted" }, "Class"), h("b", null, d.class.name)),
          h("div", null, h("div", { class: "small muted" }, "Examination"), h("b", null, d.exam.name), h("div", { class: "tiny muted" }, `${d.exam.term} ${d.exam.year}`)),
          h("div", null, h("div", { class: "small muted" }, "Overall (completed subjects)"), h("b", null, d.overall.percent == null ? "-" : `${fmtNum(d.overall.total)} / ${fmtNum(d.overall.max)} (${fmtPct(d.overall.percent)})`)))),
        d.subjects.length ? card(null, h("div", { class: "table-wrap" }, h("table", { class: "t marks" },
          h("thead", null, h("tr", null, [h("th", null, "Subject"), ...comps.map((c) => h("th", { class: "num" }, `${c.name} (/${fmtNum(c.max_marks)})`)), h("th", { class: "num" }, "Total"), h("th", { class: "c" }, "Grade"), h("th", null, "Remarks")])),
          h("tbody", null, rowsEls))), { flush: true }) : notice("No subjects are assigned to this class in this examination.", "warn"),
        h("div", { class: "hint" }, "Total, grade and remarks follow the school's grading scale. Leave a box empty if the mark is not available yet; it is never treated as zero."),
        h("div", { class: "row" }, save));
    });
  }

  pickClass();
  return root;
}
