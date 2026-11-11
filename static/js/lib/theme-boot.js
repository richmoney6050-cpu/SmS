// Runs before the app so the saved look is applied on first paint (no flash of the default theme).
import { applyPrefs, loadLocal } from "./themes.js";
applyPrefs(loadLocal());
