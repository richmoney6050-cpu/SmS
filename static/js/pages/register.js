// Weekly term register: class set-up, typed roster, Mon-Fri 1/0 grid with autosave, week and term totals, warnings.
import { ApiError, get, post, put } from "../lib/api.js";
import { badge, button, card, confirmDialog, empty, errorToast, field, fmtDate, fmtPct, h, icon, input, load, modal, mount, notice, applyErrors, named, select, stat, toast } from "../lib/ui.js";

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri"];
const tone = (p) => (p === null || p === undefined ? "" : p >= 90 ? "good" : p >= 75 ? "warn" : "bad");
const shortDate = (iso) => { const d = new Date(iso + "T00:00:00"); return d.toLocaleDateString(undefined, { day: "numeric", month: "short" }); };

export function registerTab(ctx, root, setGuard) {
  const state = { cls: null, term: null, week: null, view: "week" };
  const out = h("div"), bar = h("div", { class: "toolbar" });
  mount(root, bar, out);
  let context, pending = new Map(), timer = null, saving = false, data = null;
  const status = h("span", { class: "savebar", role: "status", "aria-live": "polite" }, "All changes saved");
  const setStatus = (cls, text) => { status.className = "savebar " + cls; status.textContent = text; };
  const guard = async () => { await flush(); return pending.size === 0; };
  guard.dirty = () => pending.size > 0;
  setGuard(guard);

  async function boot() {
    await load(out, async () => {
      context = await get("/api/register/context");
      const q = ctx.query();
      state.cls = Number(q.get("class")) || context.classes[0]?.id || null;
      state.term = Number(q.get("term")) || context.terms.find((t) => t.is_current)?.id || context.terms[0]?.id || null;
      drawBar();
      return h("div");
    });
    await loadRegister();
  }

  function drawBar() {
    const cls = select(context.classes.map((c) => [c.id, c.name]), state.cls, { "aria-label": "Class" });
    const term = select(context.terms.map((t) => [t.id, `${t.name} ${t.year_name}${t.is_current ? " (current)" : ""}`]), state.term, { "aria-label": "Term" });
    cls.addEventListener("change", async () => { await flush(); state.cls = Number(cls.value); state.week = null; await loadRegister(); });
    term.addEventListener("change", async () => { await flush(); state.term = Number(term.value); state.week = null; await loadRegister(); });
    mount(bar, field("Class", cls), field("Term", term),
      context.can_create_class ? button("New class", { ico: "plus", onClick: () => classDialog() }) : null,
      state.cls && context.can_create_class ? button("Class settings", { ico: "settings", onClick: () => classDialog(context.classes.find((c) => c.id === state.cls)) }) : null,
      h("span", { class: "grow" }), status);
  }

  async function loadRegister() {
    if (!state.cls) {
      return mount(out, card(null, empty("No class yet", context.can_create_class ? "Create your first class to start taking attendance." : "You have not been assigned to a class.", "school",
        context.can_create_class ? button("Create a class", { kind: "primary", ico: "plus", onClick: () => classDialog() }) : null)));
    }
    if (!state.term) return mount(out, card(null, empty("No term set up", "Add an academic year and term under Administration, then return here.", "calendar")));
    await load(out, async () => {
      data = await get("/api/register", { class_id: state.cls, term_id: state.term });
      const cur = data.weeks.find((w) => w.current);
      if (!state.week) state.week = cur ? cur.week : (data.weeks.find((w) => w.held_days)?.week ?? 1);
      return draw();
    });
  }

  // ---------------------------------------------------------- views
  function draw() {
    const c = data.class, tot = data.class_term, expected = c.expected_total;
    const needsNames = data.students.length < (expected || 0);
    const parts = [];
    parts.push(statsRow());
    if (data.warnings.length) parts.push(warningCards());
    if (needsNames || !data.students.length) parts.push(rosterSetup());
    if (data.students.length) parts.push(registerCard());
    return h("div", { class: "stack" }, parts);
  }

  function statsRow() {
    const c = data.class, tot = data.class_term, expected = c.expected_total;
    return h("div", { class: "grid g-stats", "data-k": "stats" },
      stat({ label: "Students", value: data.students.length + (expected ? ` / ${expected}` : ""), sub: `${tot.girls} girls, ${tot.boys} boys`, ico: "users", tone: "teal" }),
      stat({ label: "Class attendance (term)", value: fmtPct(tot.percent), sub: `${tot.held_days} school days held`, ico: "chart", tone: tone(tot.percent) || "" }),
      stat({ label: "Present marks", value: tot.present, ico: "check", tone: "good" }),
      stat({ label: "Absent marks", value: tot.absent, ico: "x", tone: tot.absent ? "warn" : "" }),
      stat({ label: "Absence warnings", value: data.warnings.length, sub: `at ${data.warning_threshold}+ absences`, ico: "alert", tone: data.warnings.length ? "bad" : "" }));
  }

  function warningCards() {
    return h("div", { class: "stack" }, data.warnings.map((w) => h("div", { class: "warn-card" },
      h("b", null, w.message), h("div", { class: "small" }, `${w.full_name} - ${w.class_name} - ${w.absences} absences - attendance ${fmtPct(w.percent)}`),
      h("div", { class: "small muted" }, "Absent on: " + w.dates.map(shortDate).join(", ")))));
  }

  function rosterSetup() {
    const c = data.class, girls = data.students.filter((s) => s.gender === "female"), boys = data.students.filter((s) => s.gender === "male");
    const gRows = Math.max(c.expected_girls ?? 0, girls.length), bRows = Math.max(c.expected_boys ?? 0, boys.length);
    const mk = (list, n, label) => Array.from({ length: n }, (_, i) => {
      const s = list[i];
      const el = h("input", { class: "name-in", type: "text", maxlength: 120, placeholder: `${label} ${i + 1}: type a name (e.g. Ama Serwaa Boateng)`, "aria-label": `${label} ${i + 1} name`, value: s ? `${s.first_name} ${s.middle_name} ${s.surname}`.replace(/\s+/g, " ").trim() : "" });
      el.dataset.id = s ? s.id : "";
      return el;
    });
    const gIn = mk(girls, gRows, "Girl"), bIn = mk(boys, bRows, "Boy");
    const save = button("Save names and sort register", { kind: "primary", ico: "check", onClick: async () => {
      try {
        const pick = (arr) => arr.map((e) => ({ id: e.dataset.id ? Number(e.dataset.id) : null, name: e.value.trim() }));
        const r = await put(`/api/register/classes/${state.cls}/roster`, { girls: pick(gIn), boys: pick(bIn) });
        toast(`${r.created} added, ${r.updated} updated. The register is now sorted: girls first, then boys, alphabetically.`, "success");
        await loadRegister();
      } catch (e) { errorToast(e); }
    } });
    return card(`Class list for ${c.name}`, h("div", { class: "stack" },
      notice("Type the names in any order. When you save, the register puts the girls first and then the boys, each in alphabetical order by surname. Use \"First Middle Surname\" or \"Surname, First Middle\".", "", "info"),
      h("div", { class: "grid g2" },
        h("div", { class: "stack" }, h("h3", null, `Girls (${gRows})`), h("div", { class: "setup-rows" }, gIn)),
        h("div", { class: "stack" }, h("h3", null, `Boys (${bRows})`), h("div", { class: "setup-rows" }, bIn))),
      h("div", null, save)));
  }

  function registerCard() {
    const nav = h("div", { class: "tabs", role: "tablist", "aria-label": "Weeks" },
      data.weeks.map((w) => h("button", { role: "tab", "aria-selected": state.view === "week" && state.week === w.week ? "true" : "false", onclick: () => { state.view = "week"; state.week = w.week; refreshView(); } },
        `Week ${w.week}`, w.current ? h("span", { class: "count", style: { background: "var(--teal)" } }, "now") : null)),
      h("button", { role: "tab", "aria-selected": state.view === "term" ? "true" : "false", onclick: () => { state.view = "term"; refreshView(); } }, icon("chart"), "Term summary"));
    const body = h("div");
    const wk = h("div", { class: "row small muted" });
    const weeksCtl = context.can_set_weeks ? button(`Term length: ${data.term.weeks} weeks`, { sm: true, ico: "edit", onClick: weeksDialog }) : badge(`${data.term.weeks} weeks`, "");
    const dl = h("div", { class: "row" },
      button("Print", { sm: true, ico: "printer", onClick: () => window.print() }),
      weeksCtl);
    function refreshView() {
      mount(nav, ...Array.from(nav.children));
      nav.querySelectorAll("button").forEach((b, i) => b.setAttribute("aria-selected", (state.view === "week" && i === state.week - 1) || (state.view === "term" && i === data.weeks.length) ? "true" : "false"));
      mount(body, state.view === "term" ? termTable() : weekTable(state.week));
      nav.querySelector('[aria-selected="true"]')?.scrollIntoView({ block: "nearest", inline: "center" });
    }
    refreshView();
    return h("section", { class: "card" },
      h("div", { class: "card-h" }, h("div", null, h("h2", null, `${data.class.name} - ${data.term.name} ${data.term.year_name}`), h("div", { class: "small muted" }, data.class.teacher ? `Class teacher: ${data.class.teacher}` : "No class teacher assigned")), dl),
      h("div", { class: "card-b" }, h("div", { class: "stack" },
        !data.can_edit ? notice("You can view this register but not change it.", "", "info") : notice("Type 1 for present and 0 for absent. Days that have not happened yet are locked. Changes save automatically.", "", "info"),
        nav, body, wk)));
  }

  function weekTable(w) {
    const wk = data.weeks[w - 1];
    const head1 = h("tr", null, h("th", { class: "namecol", rowspan: 2 }, "Name"), h("th", { colspan: 5, class: "wkhead" }, `Week ${w}`), h("th", { rowspan: 2 }, "Week total"), h("th", { rowspan: 2 }, "Week %"),
      h("th", { rowspan: 2 }, "Term present"), h("th", { rowspan: 2 }, "Term absent"), h("th", { rowspan: 2 }, "Weeks attended"), h("th", { rowspan: 2 }, "Term %"));
    const head2 = h("tr", null, DAYS.map((d, i) => h("th", { title: fmtDate(wk.dates[i]) }, h("div", null, d), h("div", { style: { fontWeight: 500, textTransform: "none" } }, shortDate(wk.dates[i])))));
    const body = h("tbody");
    let section = null;
    const widthCols = 12;
    data.students.forEach((s) => {
      if (s.section !== section) { section = s.section; body.append(h("tr", { class: "section " + section.toLowerCase() }, h("td", { colspan: widthCols }, section))); }
      const sw = s.weeks[w - 1];
      const cells = DAYS.map((_, i) => {
        const iso = wk.dates[i], future = wk.future[i], v = sw.cells[i];
        const el = h("input", { class: "cell " + (v === 1 ? "p1" : v === 0 ? "p0" : ""), type: "text", inputmode: "numeric", maxlength: 1, autocomplete: "off", value: v === null ? "" : String(v),
          "aria-label": `${s.display_name}, ${DAYS[i]} ${shortDate(iso)}`, disabled: future || !data.can_edit, title: future ? "This day has not happened yet" : "" });
        el.dataset.sid = s.id; el.dataset.date = iso; el.dataset.row = s.id; el.dataset.col = i;
        el.addEventListener("input", () => onCell(el, s, wk));
        el.addEventListener("keydown", (e) => navKey(e, el));
        el.addEventListener("focus", () => el.select());
        return h("td", null, el);
      });
      const tr = h("tr", { dataset: { sid: s.id } }, h("td", { class: "namecol" }, s.display_name), cells,
        h("td", { class: "tot", "data-k": "wt" }, sw.present), h("td", { class: "pcell " + tone(sw.percent), "data-k": "wp" }, fmtPct(sw.percent)),
        h("td", { class: "tot", "data-k": "tp" }, s.term.present), h("td", { class: "tot", "data-k": "ta" }, s.term.absent),
        h("td", { class: "tot", "data-k": "wa" }, `${s.term.weeks_attended}/${data.term.weeks}`), h("td", { class: "pcell " + tone(s.term.percent), "data-k": "tpc" }, fmtPct(s.term.percent)));
      body.append(tr);
    });
    const cw = data.class_weeks[w - 1];
    body.append(h("tr", { class: "section", "data-k": "csum" }, h("td", { colspan: widthCols }, `Class summary, week ${w}: ${cw.present} present, ${cw.absent} absent, ${fmtPct(cw.percent)} attendance (${cw.held_days} day${cw.held_days === 1 ? "" : "s"} held)`)));
    return h("div", { class: "reg-wrap" }, h("table", { class: "reg" }, h("thead", null, head1, head2), body));
  }

  function termTable() {
    const head = h("tr", null, h("th", { class: "namecol" }, "Name"), data.weeks.map((w) => h("th", { title: `Week ${w.week}` }, `W${w.week}`)),
      h("th", null, "Present"), h("th", null, "Absent"), h("th", null, "Weeks attended"), h("th", null, "Days missed"), h("th", null, "Overall %"));
    const body = h("tbody");
    let section = null;
    data.students.forEach((s) => {
      if (s.section !== section) { section = s.section; body.append(h("tr", { class: "section " + section.toLowerCase() }, h("td", { colspan: data.weeks.length + 6 }, section))); }
      body.append(h("tr", null, h("td", { class: "namecol" }, s.display_name), s.weeks.map((w) => h("td", { class: "tot" }, w.present + w.absent ? w.present : "")),
        h("td", { class: "tot" }, s.term.present), h("td", { class: "tot" }, s.term.absent), h("td", { class: "tot" }, `${s.term.weeks_attended}/${data.term.weeks}`), h("td", { class: "tot" }, s.term.days_missed),
        h("td", { class: "pcell " + tone(s.term.percent) }, fmtPct(s.term.percent))));
    });
    body.append(h("tr", { class: "section" }, h("td", { colspan: data.weeks.length + 6 }, `Class: ${data.class_term.present} present, ${data.class_term.absent} absent, overall ${fmtPct(data.class_term.percent)} across ${data.class_term.held_days} school days held`)));
    return h("div", { class: "reg-wrap" }, h("table", { class: "reg" }, h("thead", null, head), body));
  }

  // ---------------------------------------------------------- cell handling
  function onCell(el, s, wk) {
    const v = el.value.trim();
    el.classList.remove("bad");
    if (v !== "" && v !== "0" && v !== "1") {
      el.value = ""; el.classList.add("bad");
      toast("Attendance accepts only 1 (present) or 0 (absent).", "warn", 2500);
      setTimeout(() => el.classList.remove("bad"), 1200);
      return;
    }
    el.classList.toggle("p1", v === "1"); el.classList.toggle("p0", v === "0");
    pending.set(`${el.dataset.sid}|${el.dataset.date}`, { student_id: Number(el.dataset.sid), date: el.dataset.date, value: v === "" ? null : Number(v) });
    recalcRow(el.closest("tr"), s, wk);
    setStatus("saving", "Saving...");
    clearTimeout(timer); timer = setTimeout(flush, 700);
    if (v !== "") focusCell(Number(el.dataset.col) + 1, el);
  }
  function recalcRow(tr, s, wk) {
    const vals = Array.from(tr.querySelectorAll("input.cell")).map((i) => i.value);
    const p = vals.filter((x) => x === "1").length, a = vals.filter((x) => x === "0").length;
    tr.querySelector('[data-k="wt"]').textContent = p;
    const wp = tr.querySelector('[data-k="wp"]'); wp.textContent = p + a ? fmtPct(Math.round((p / (p + a)) * 1000) / 10) : "-";
  }
  function focusCell(col, from) {
    const tr = from.closest("tr");
    if (col <= 4) tr.querySelectorAll("input.cell")[col]?.focus();
    else { let n = tr.nextElementSibling; while (n && !n.querySelector("input.cell")) n = n.nextElementSibling; n?.querySelectorAll("input.cell")[0]?.focus(); }
  }
  function navKey(e, el) {
    const tr = el.closest("tr"), col = Number(el.dataset.col);
    const move = (r, c) => { const t = r?.querySelectorAll("input.cell:not(:disabled)"); r && t && (t[Math.min(c, t.length - 1)] || t[0])?.focus(); };
    const next = (n, dir) => { let x = n; do { x = dir > 0 ? x.nextElementSibling : x.previousElementSibling; } while (x && !x.querySelector("input.cell")); return x; };
    if (e.key === "ArrowRight") { e.preventDefault(); tr.querySelectorAll("input.cell")[col + 1]?.focus(); }
    else if (e.key === "ArrowLeft") { e.preventDefault(); tr.querySelectorAll("input.cell")[col - 1]?.focus(); }
    else if (e.key === "ArrowDown" || e.key === "Enter") { e.preventDefault(); const n = next(tr, 1); if (n) n.querySelectorAll("input.cell")[col]?.focus(); }
    else if (e.key === "ArrowUp") { e.preventDefault(); const n = next(tr, -1); if (n) n.querySelectorAll("input.cell")[col]?.focus(); }
    else if (e.key === "Backspace" || e.key === "Delete") { /* default clears the cell, then input event saves it */ }
  }

  async function flush() {
    clearTimeout(timer);
    if (saving || !pending.size) return;
    saving = true;
    const batch = Array.from(pending.entries());
    try {
      const r = await put("/api/register/marks", { class_id: state.cls, term_id: state.term, cells: batch.map(([, v]) => v) });
      batch.forEach(([k, v]) => { if (pending.get(k) === v) pending.delete(k); });
      applyServer(r);
      setStatus(pending.size ? "saving" : "saved", pending.size ? "Saving..." : `Saved ${new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`);
      ctx.refreshAlertCount?.();
    } catch (e) {
      setStatus("error", e instanceof ApiError ? e.message : "Could not save. Retrying when you type again.");
      if (e instanceof ApiError && e.status >= 400 && e.status < 500) { pending.clear(); errorToast(e); await loadRegister(); }
    } finally {
      saving = false;
      if (pending.size) timer = setTimeout(flush, 1200);
    }
  }
  function applyServer(r) {
    if (!data) return;
    data.class_weeks = r.class_weeks; data.class_term = r.class_term; data.warnings = r.warnings;
    r.students.forEach((u) => { const s = data.students.find((x) => x.id === u.id); if (s) { s.term = { ...s.term, ...u.term }; u.weeks.forEach((w, i) => Object.assign(s.weeks[i], w)); } });
    const st = out.querySelector('[data-k="stats"]'); if (st) st.replaceWith(statsRow());
    const old = out.querySelector(".warn-card")?.parentElement; if (old) { if (data.warnings.length) old.replaceWith(warningCards()); else old.remove(); } else if (data.warnings.length) out.querySelector('[data-k="stats"]')?.after(warningCards());
    if (state.view === "week") {
      const cs = out.querySelector('[data-k="csum"] td'), cw = data.class_weeks[state.week - 1];
      if (cs && cw) cs.textContent = `Class summary, week ${state.week}: ${cw.present} present, ${cw.absent} absent, ${fmtPct(cw.percent)} attendance (${cw.held_days} day${cw.held_days === 1 ? "" : "s"} held)`;
      const tr = (sid) => out.querySelector(`tr[data-sid="${sid}"]`);
      data.students.forEach((s) => {
        const row = tr(s.id); if (!row) return;
        row.querySelector('[data-k="tp"]').textContent = s.term.present; row.querySelector('[data-k="ta"]').textContent = s.term.absent;
        row.querySelector('[data-k="wa"]').textContent = `${s.term.weeks_attended}/${data.term.weeks}`;
        const t = row.querySelector('[data-k="tpc"]'); t.textContent = fmtPct(s.term.percent); t.className = "pcell " + tone(s.term.percent);
        const w = s.weeks[state.week - 1], wp = row.querySelector('[data-k="wp"]'); wp.className = "pcell " + tone(w.percent);
      });
    }
  }

  // ---------------------------------------------------------- dialogs
  function classDialog(existing) {
    const name = named("name", field("Class name", input({ value: existing?.name || "", maxlength: 60, placeholder: "e.g. Primary 4A" }), { required: true }));
    const total = named("total", field("Total number of students", input({ type: "number", min: 1, max: 300, value: existing?.expected_total ?? "" }), { required: true }));
    const boys = named("boys", field("Number of boys", input({ type: "number", min: 0, max: 300, value: existing?.expected_boys ?? "" }), { required: true }));
    const girls = named("girls", field("Number of girls", input({ type: "number", min: 0, max: 300, value: existing?.expected_girls ?? "" }), { required: true }));
    const hint = h("div", { class: "small muted", "aria-live": "polite" });
    const form = h("form", { class: "stack", novalidate: true }, name, h("div", { class: "form-grid" }, total, boys, girls), hint);
    const num = (f) => Number(f.querySelector("input").value || 0);
    const check = () => { const ok = num(boys) + num(girls) === num(total); hint.textContent = ok ? `${num(girls)} girls + ${num(boys)} boys = ${num(total)} students.` : `Boys + girls = ${num(boys) + num(girls)}, which does not match the total (${num(total)}).`; hint.style.color = ok ? "var(--good-ink)" : "var(--crit-ink)"; };
    [total, boys, girls].forEach((f) => f.querySelector("input").addEventListener("input", check)); check();
    const m = modal({ title: existing ? "Class settings" : "Create a class", size: "sm", body: form, actions: [
      h("button", { class: "btn", type: "button", onclick: () => m.close() }, "Cancel"),
      button(existing ? "Save" : "Create class", { kind: "primary", onClick: async () => {
        applyErrors(form, null);
        const body = { name: name.querySelector("input").value, total: num(total), boys: num(boys), girls: num(girls) };
        try {
          const r = existing ? await put(`/api/register/classes/${existing.id}`, body) : await post("/api/register/classes", body);
          m.close(); state.cls = r.class.id; await ctx.refreshMeta?.(); await boot();
          toast(existing ? "Class updated." : "Class created. Now type the students' names.", "success");
        } catch (e) { applyErrors(form, e); if (!(e instanceof ApiError)) errorToast(e); }
      } })] });
  }

  function weeksDialog() {
    const weeks = named("weeks", field("Number of weeks in this term", input({ type: "number", min: 1, max: 30, value: data.term.weeks }), { required: true, hint: "Week 1 to the number you choose will appear in the register." }));
    const form = h("form", { class: "stack", novalidate: true }, weeks);
    const m = modal({ title: "Term length", size: "sm", body: form, actions: [
      h("button", { class: "btn", type: "button", onclick: () => m.close() }, "Cancel"),
      button("Save", { kind: "primary", onClick: async () => {
        applyErrors(form, null);
        try { await put("/api/register/term-weeks", { term_id: state.term, weeks: Number(weeks.querySelector("input").value) }); m.close(); await boot(); toast("Term length saved.", "success"); }
        catch (e) { applyErrors(form, e); if (!(e instanceof ApiError)) errorToast(e); }
      } })] });
  }
  boot();
}
