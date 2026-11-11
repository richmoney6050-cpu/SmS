// Appearance & Themes: pick a colour theme, light/dark/system mode, rainbow mode or custom colours.
// Every change is previewed live across the whole app; "Apply" saves it to the user's account.
import { put } from "../lib/api.js";
import { badge, button, card, errorToast, h, icon, mount, pageHead, toast } from "../lib/ui.js";
import { DEFAULT_CUSTOM, DEFAULT_PREFS, THEMES, applyPrefs, buildTokens, getPrefs, normalize, resolveMode, saveLocal } from "../lib/themes.js";

export async function render(ctx, view) {
  mount(view, pageHead("Appearance & Themes", "Choose how your School Management System looks. Your choice is saved to your account and follows you to any device."));
  const body = h("div", { class: "view stack" });
  mount(view, body);
  draw(ctx, body);
}

export function draw(ctx, root) {
  let saved = normalize(ctx.user?.ui_prefs || getPrefs());
  let draft = normalize(saved);
  const wrap = h("div", { class: "stack" });
  const dirty = () => JSON.stringify(draft) !== JSON.stringify(saved);

  const live = (rebuildCustom = false) => { applyPrefs(draft); refresh(rebuildCustom); };
  const revert = () => { applyPrefs(saved); };
  // Leaving the page with an unsaved preview puts the saved look back.
  const onLeave = () => { if (!document.body.contains(wrap)) { if (dirty()) revert(); window.removeEventListener("hashchange", onLeave); } };
  window.addEventListener("hashchange", () => setTimeout(onLeave, 0));

  async function save(next, message) {
    try {
      const r = await put("/api/auth/preferences", next);
      saved = normalize(r.ui_prefs); draft = normalize(saved);
      if (ctx.user) ctx.user.ui_prefs = saved;
      saveLocal(saved); applyPrefs(saved); refresh(true);
      toast(message || "Appearance saved.", "success");
    } catch (e) { errorToast(e); }
  }

  const modeBtn = (value, label, ico) => h("button", { type: "button", "aria-pressed": String(draft.mode === value), onclick: () => { draft.mode = value; live(); } }, icon(ico), label);
  const modeCard = () => card("Display mode", h("div", { class: "stack-sm" },
    h("div", { class: "seg", role: "group", "aria-label": "Display mode" }, modeBtn("light", "Light", "sun"), modeBtn("dark", "Dark", "moon"), modeBtn("system", "System default", "settings")),
    h("div", { class: "hint" }, "Light and dark work with every colour theme. System default follows your phone or computer setting."),
    (() => {
      const cb = h("input", { type: "checkbox", checked: draft.rainbow, onchange: () => { draft.rainbow = cb.checked; live(); } });
      return h("label", { class: "switch" }, cb, h("span", { class: "track" }), h("span", null, "Rainbow mode"));
    })(),
    h("div", { class: "hint" }, "Adds rainbow gradients to buttons, headings, borders and navigation highlights. Text stays on plain, readable colours.")));

  function mini(t) {
    const k = buildTokens({ theme: t.id, rainbow: draft.rainbow, custom: draft.custom || (t.custom ? DEFAULT_CUSTOM : null) }, resolveMode(draft.mode)), v = k.vars;
    const prev = h("div", { class: "prev" });
    prev.style.background = v["--bg"];
    const sb = h("div", { class: "sb" }, h("i"), h("i"), h("i"), h("i"));
    sb.style.background = v["--navy"]; sb.style.color = v["--navy-ink"];
    const bar = h("div", { class: "bar" }); bar.style.background = k.rainbow ? "linear-gradient(90deg,#d7263d,#c2410c,#a16207,#15803d,#1d4ed8,#7e22ce)" : v["--grad"];
    const tiles = h("div", { class: "row2" }, ...[0, 1, 2].map((i) => { const t1 = h("div", { class: "tile" }); t1.style.background = v["--surface"]; t1.style.borderTopColor = v[`--s${i + 1}`]; t1.style.boxShadow = `0 0 0 1px ${v["--border"]}`; return t1; }));
    const pill = h("div", { class: "pill" }); pill.style.background = k.rainbow ? "linear-gradient(90deg,#d7263d,#a16207,#15803d,#1d4ed8,#7e22ce)" : v["--grad"];
    prev.append(sb, h("div", { class: "mn" }, bar, tiles, pill));
    const sw = h("div", { class: "swatches", "aria-hidden": "true" }, ...[v["--accent"], v["--hi-fill"], v["--navy"], v["--bg"]].map((c) => { const i = h("i"); i.style.background = c; return i; }));
    return { prev, sw };
  }

  const themeCard = (t) => {
    const m = mini(t), active = draft.theme === t.id;
    return h("button", { type: "button", class: "theme-card", "aria-pressed": String(active), "aria-label": `${t.name} theme: ${t.tag}${saved.theme === t.id ? " (current)" : ""}`,
      onclick: () => { draft.theme = t.id; if (t.rainbow) draft.rainbow = true; if (t.custom && !draft.custom) draft.custom = { ...DEFAULT_CUSTOM }; live(true); } },
      m.prev, h("div", { class: "info" }, h("b", null, h("span", null, t.name), saved.theme === t.id ? badge("Current", "good") : active ? badge("Previewing", "info") : null), m.sw, h("span", { class: "tag" }, t.tag)));
  };

  const hexOk = (s) => /^#[0-9a-f]{6}$/i.test(s);
  const customCard = () => {
    if (draft.theme !== "custom") return null;
    const c = draft.custom || { ...DEFAULT_CUSTOM };
    const fields = [["primary", "Primary colour", "Main buttons and active menu items"], ["secondary", "Secondary colour", "Gradient partner and highlights"], ["background", "Background colour", "Page background (kept readable in both modes)"], ["accent", "Accent colour", "Focus rings, card edges and small highlights"]];
    return card("Create your own colours", h("div", { class: "stack-sm" },
      h("div", { class: "custom-grid" }, fields.map(([key, label, hint]) => {
        const pick = h("input", { type: "color", value: c[key], "aria-label": label });
        const txt = h("input", { type: "text", class: "input", value: c[key], maxlength: 7, "aria-label": `${label} hex code`, spellcheck: "false" });
        const set = (val) => { draft.custom = { ...(draft.custom || DEFAULT_CUSTOM), [key]: val.toLowerCase() }; live(false); };
        pick.addEventListener("input", () => { txt.value = pick.value; txt.classList.remove("invalid"); set(pick.value); });
        txt.addEventListener("input", () => { const ok = hexOk(txt.value); txt.classList.toggle("invalid", !ok); if (ok) { pick.value = txt.value; set(txt.value); } });
        return h("div", { class: "color-field" }, h("label", { class: "label" }, label), h("div", { class: "cf" }, pick, txt), h("div", { class: "tiny muted" }, hint));
      })),
      h("div", { class: "hint" }, "Text colours are adjusted automatically where needed so everything stays easy to read, whatever colours you choose.")));
  };

  const bar = () => {
    if (!dirty()) return null;
    const name = (THEMES.find((t) => t.id === draft.theme) || {}).name || "this look";
    return h("div", { class: "preview-bar", role: "region", "aria-label": "Preview" },
      h("div", null, h("b", null, "Previewing: "), `${name}${draft.rainbow ? " with rainbow mode" : ""}, ${draft.mode === "system" ? "system default" : draft.mode} mode.`, h("div", { class: "tiny muted" }, "Not saved yet. The whole website is showing this look.")),
      h("div", { class: "row" }, button("Cancel", { onClick: () => { draft = normalize(saved); live(true); } }), button("Apply", { kind: "primary", ico: "check", onClick: (e) => { e.currentTarget.disabled = true; save(draft, "Appearance applied and saved."); } })));
  };

  const hosts = { mode: h("div"), grid: h("div"), custom: h("div"), reset: h("div"), bar: h("div") };
  wrap.append(hosts.mode, hosts.grid, hosts.custom, hosts.reset, hosts.bar);
  function refresh(rebuildCustom = true) {
    mount(hosts.mode, modeCard());
    mount(hosts.grid, card("Colour themes", h("div", { class: "stack-sm" },
      h("div", { class: "hint" }, "Click a theme to preview it across the whole website. Press Apply to keep it."),
      h("div", { class: "theme-grid" }, THEMES.map(themeCard)))));
    if (rebuildCustom) mount(hosts.custom, customCard());
    mount(hosts.reset, card("Reset", h("div", { class: "row between" }, h("div", { class: "hint" }, "Go back to the default blue theme with your device's light/dark setting."),
      button("Reset to default appearance", { ico: "refresh", onClick: () => { draft = { ...DEFAULT_PREFS }; saved = normalize(saved); save({ ...DEFAULT_PREFS }, "Appearance reset to the default."); } }))));
    mount(hosts.bar, bar());
  }
  refresh();
  mount(root, wrap);
}
