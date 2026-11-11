import { THEMES, audit, DEFAULT_CUSTOM } from "../../static/js/lib/themes.js";
const fails = [];
const customs = [null, DEFAULT_CUSTOM, { primary: "#ffee00", secondary: "#ffffff", background: "#ffffff", accent: "#ffee00" }, { primary: "#000000", secondary: "#111111", background: "#000000", accent: "#222222" }, { primary: "#ff0000", secondary: "#00ff00", background: "#ffff00", accent: "#00ffff" }];
for (const t of THEMES) for (const mode of ["light", "dark"]) for (const rainbow of [false, true]) for (const custom of t.id === "custom" ? customs : [null]) {
  const bad = audit({ theme: t.id, rainbow, custom }, mode);
  if (bad.length) fails.push(`${t.id}/${mode}${rainbow ? "/rainbow" : ""}${custom ? "/" + custom.primary : ""}: ${bad.join("; ")}`);
}
console.log(fails.length ? fails.join("\n") : "ALL OK");
process.exit(fails.length ? 1 : 0);
