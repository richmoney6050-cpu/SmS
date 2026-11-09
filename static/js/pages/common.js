// Helpers shared by several pages.
import { h, icon, select, field, fmtDate, ago, fmtDateTime, badge } from "../lib/ui.js";

export const classOptions = (meta, { all = "All classes", activeOnly = true } = {}) =>
  [...(all ? [["", all]] : []), ...meta.classes.filter((c) => !activeOnly || c.is_active).map((c) => [c.id, c.name])];

export const yearOptions = (meta, all = "Any year") => [["", all], ...meta.years.map((y) => [y.id, y.name + (y.is_current ? " (current)" : "")])];
export const termOptions = (meta, all = "Any term") => [["", all], ...meta.terms.map((t) => {
  const y = meta.years.find((x) => x.id === t.year_id);
  return [t.id, `${t.name} ${y ? y.name : ""}${t.is_current ? " (current)" : ""}`];
})];

export const studentLink = (id, name) => h("a", { href: `#/students/${id}` }, name);
export const classLink = (id, name) => h("a", { href: `#/dashboard/classes/${id}` }, name);

export function when(iso) {
  return iso ? h("span", { title: fmtDateTime(iso) }, ago(iso)) : h("span", { class: "muted" }, "Never");
}

export const attendanceMark = (status) => {
  const m = { present: ["P", "Present"], absent: ["A", "Absent"], late: ["L", "Late"] }[status];
  return h("span", { class: "grid-cell " + (m ? status : "none"), title: m ? m[1] : "Not recorded", role: "img", "aria-label": m ? m[1] : "Not recorded" }, m ? m[0] : "-");
};

export function statusPill(status) {
  const m = { present: ["Present", "good", "check"], absent: ["Absent", "bad", "x"], late: ["Late", "warn", "clock"] }[status];
  return m ? badge(m[0], m[1], m[2]) : badge("Not marked", "");
}

export function gradeBadge(grade, pass) {
  return grade ? h("span", { class: "badge " + (pass === false ? "bad" : pass === true ? "good" : "") }, grade) : h("span", { class: "muted" }, "-");
}

export function backLink(href, text) {
  return h("a", { class: "btn ghost sm", href, style: { marginBottom: "8px", paddingLeft: "4px" } }, icon("chevronLeft"), text);
}

export const sevTone = (s) => (s === "critical" ? "bad" : s === "warning" ? "warn" : "info");
export const sevIcon = (s) => (s === "critical" ? "alert" : s === "warning" ? "alert" : "info");

export function alertLink(a) {
  if (a.student_id) return `#/students/${a.student_id}`;
  if (a.class_id) return `#/dashboard/classes/${a.class_id}`;
  if (a.teacher_id) return `#/dashboard/teachers/${a.teacher_id}`;
  return null;
}

export const ALERT_LABELS = {
  missing_attendance: "Missing attendance", teacher_inactive: "Teacher inactive", marks_overdue: "Results overdue", marks_pending: "Results awaiting submission",
  poor_attendance: "Poor attendance", declining_performance: "Declining performance", repeated_absence: "Repeated absence", absence_warning: "Attendance warning",
};

export function activityFeed(items, { empty } = {}) {
  if (!items.length) return h("div", { class: "empty" }, h("p", null, empty || "No activity yet."));
  return h("ul", { class: "list" }, items.map((a) => {
    const kind = a.kind === "alert" ? (a.severity === "critical" ? "critical alert" : "alert") : a.kind === "login" ? "login" : "";
    const ico = a.kind === "alert" ? "alert" : a.kind === "login" ? "login" : a.action?.startsWith("attendance") ? "calendar" : "exam";
    return h("li", null, h("span", { class: "feed-ico " + kind }, icon(ico)),
      h("div", { class: "grow" }, h("div", null, a.text), h("div", { class: "tiny muted" }, a.kind === "login" ? "Website login | " : a.kind === "alert" ? "Alert | " : "Record saved | ", when(a.at))));
  }));
}
