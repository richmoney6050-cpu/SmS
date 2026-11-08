// Teacher Monitoring: who has done what, kept honest about what the system can and cannot know.
import { get } from "../lib/api.js";
import { badge, button, card, dataTable, empty, field, fmtDateTime, h, icon, input, load, mount, notice, pageHead, select, stat, statusBadge } from "../lib/ui.js";
import { activityFeed, backLink, classLink, when } from "./common.js";

export async function render(ctx, head, body, id) {
  return id ? detail(ctx, head, body, Number(id)) : list(ctx, head, body);
}

async function list(ctx, head, body) {
  const d = await get("/api/command/teachers");
  mount(head, pageHead("Teacher Monitoring", "All teachers, their assignments, and what they have recorded."));
  const q = input({ type: "search", placeholder: "Search teacher, ID, class or subject", "aria-label": "Search teachers" });
  const flt = select([["", "All teachers"], ["tasks", "With outstanding tasks"], ["att", "Attendance not recorded"], ["marks", "Marks not submitted"]], "");
  const holder = h("div");
  const columns = [
    { key: "full_name", label: "Teacher", render: (t) => h("div", null, h("a", { href: `#/dashboard/teachers/${t.id}` }, h("b", null, t.full_name)), h("div", { class: "tiny muted" }, t.staff_id), !t.is_active ? badge("Deactivated", "bad") : null) },
    { key: "classes", label: "Classes", sortValue: (t) => t.classes.join(","), render: (t) => (t.classes.length ? h("div", { class: "pill-row" }, t.assignments.filter((a, i, arr) => arr.findIndex((x) => x.class_id === a.class_id) === i).map((a) => h("a", { class: "badge info", href: `#/dashboard/classes/${a.class_id}` }, a.class_name, a.is_class_teacher ? " (class teacher)" : ""))) : h("span", { class: "muted" }, "None")) },
    { key: "subjects", label: "Subjects", sortValue: (t) => t.subjects.length, render: (t) => (t.subjects.length ? h("span", { class: "small", title: t.subjects.join(", ") }, t.subjects.slice(0, 3).join(", "), t.subjects.length > 3 ? ` +${t.subjects.length - 3} more` : "") : h("span", { class: "muted" }, "-")) },
    { key: "last_login_at", label: "Last website login", render: (t) => when(t.last_login_at) },
    { key: "last_record_at", label: "Last saved record", render: (t) => (t.last_record_at ? h("div", null, h("div", { class: "small" }, t.last_record_text), h("div", { class: "tiny muted" }, when(t.last_record_at))) : h("span", { class: "muted" }, "No records yet")) },
    { key: "attendance_status", label: "Attendance today", render: (t) => statusBadge(t.attendance_status) },
    { key: "marks_status", label: "Marks submission", render: (t) => h("div", null, statusBadge(t.marks_status), t.marks_progress.total ? h("div", { class: "tiny muted" }, `${t.marks_progress.submitted} of ${t.marks_progress.total} lists`) : null) },
    { key: "outstanding", label: "Outstanding", align: "right", sortValue: (t) => t.outstanding.length, render: (t) => (t.outstanding.length ? badge(`${t.outstanding.length} task${t.outstanding.length === 1 ? "" : "s"}`, t.outstanding.some((o) => o.overdue) ? "bad" : "warn", "clock") : badge("None", "good", "check")) },
  ];
  const draw = () => {
    const text = q.value.trim().toLowerCase();
    const rows = d.teachers.filter((t) => (!text || [t.full_name, t.staff_id, ...t.classes, ...t.subjects].join(" ").toLowerCase().includes(text))
      && (!flt.value || (flt.value === "tasks" && t.outstanding.length) || (flt.value === "att" && ["missing", "partial"].includes(t.attendance_status)) || (flt.value === "marks" && ["pending", "partial"].includes(t.marks_status))));
    mount(holder, card(null, dataTable({ columns, rows, sortKey: "full_name", onRow: (t) => { location.hash = `#/dashboard/teachers/${t.id}`; }, empty: empty("No teachers match", "Try a different search or filter.", "search") }), { flush: true }));
  };
  q.addEventListener("input", draw); flt.addEventListener("change", draw);
  mount(body, h("div", { class: "stack" }, notice(d.note, "", "info"), h("div", { class: "toolbar", style: { marginBottom: 0 } }, h("div", { class: "search" }, icon("search"), q), field("Show", flt)), holder));
  draw();
}

async function detail(ctx, head, body, id) {
  const d = await get(`/api/command/teachers/${id}`);
  const t = d.teacher;
  mount(head, h("div", null, backLink("#/dashboard/teachers", "All teachers"), pageHead(t.full_name, `${t.staff_id} | username ${t.username}`)));
  const feed = h("div");
  let kind = "", items = [...d.activity], more = d.has_more;
  const drawFeed = () => {
    mount(feed, activityFeed(items, { empty: "No activity yet." }));
    if (more) feed.append(h("div", { class: "pager", style: { justifyContent: "center" } }, button("Load older activity", { onClick: async () => { const r = await get(`/api/command/teachers/${id}`, { kind, before_id: items[items.length - 1].id }); items = items.concat(r.activity); more = r.has_more; drawFeed(); } })));
  };
  const filter = select([["", "Everything"], ["record", "Saved records only"], ["login", "Website logins only"]], "");
  filter.addEventListener("change", async () => { kind = filter.value; const r = await get(`/api/command/teachers/${id}`, { kind }); items = r.activity; more = r.has_more; drawFeed(); });
  drawFeed();
  const tot = d.totals, n = (...k) => k.reduce((a, x) => a + (tot[x] || 0), 0);
  mount(body, h("div", { class: "stack view" },
    notice("Website logins and saved records are shown separately. Neither confirms that the teacher is physically in a classroom.", "", "info"),
    h("div", { class: "grid g-stats" },
      stat({ label: "Last website login", value: t.last_login_at ? fmtDateTime(t.last_login_at) : "Never", ico: "login" }),
      stat({ label: "Last saved record", value: t.last_record_at ? fmtDateTime(t.last_record_at) : "None", sub: t.last_record_text, ico: "check" }),
      stat({ label: "Attendance saves", value: n("attendance_recorded", "attendance_updated"), ico: "calendar" }),
      stat({ label: "Marks saves", value: n("marks_entered", "marks_updated"), sub: `${n("marks_submitted")} lists submitted`, ico: "exam" }),
      stat({ label: "Website logins", value: n("login"), ico: "login" })),
    h("div", { class: "grid g2" },
      card("Assignments", t.assignments.length ? h("ul", { class: "list", style: { margin: "-16px -20px -20px" } }, t.assignments.map((a) => h("li", null, icon(a.is_class_teacher ? "user" : "book"), h("div", { class: "grow" }, h("a", { href: `#/dashboard/classes/${a.class_id}` }, a.class_name), h("span", { class: "muted" }, a.is_class_teacher ? " | Class teacher" : ` | ${a.subject_name}`))))) : empty("No assignments", "Assign this teacher to classes under Administration.", "swap")),
      card(`Outstanding tasks (${t.outstanding.length})`, t.outstanding.length ? h("ul", { class: "list", style: { margin: "-16px -20px -20px" } }, t.outstanding.map((o) => h("li", null, h("span", { class: "feed-ico " + (o.overdue ? "critical alert" : "alert") }, icon(o.type === "attendance" ? "calendar" : "exam")), h("div", { class: "grow" }, o.text, o.overdue ? h("div", null, badge("Overdue", "bad", "alert")) : null)))) : empty("Up to date", "No outstanding tasks.", "check"))),
    card("Activity history", h("div", null, h("div", { class: "toolbar" }, field("Show", filter)), feed))));
}
