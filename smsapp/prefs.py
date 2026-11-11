"""Per-user appearance preferences: validated here, stored as JSON in users.ui_prefs."""
import json
import re

from .util import ApiError

MODES = ("light", "dark", "system")
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
CUSTOM_KEYS = ("primary", "secondary", "background", "accent")
# Keep in step with static/js/lib/themes.js (a test compares the two lists).
THEME_IDS = (
    "blue", "red", "yellow", "black", "white", "green", "orange", "purple", "pink", "rainbow", "cyan", "teal",
    "midnight", "sunset", "ocean", "neon", "gradient", "custom", "lavender", "forest", "rose",
)
DEFAULTS = {"theme": "blue", "mode": "system", "rainbow": False, "custom": None}


def clean(d) -> dict:
    if not isinstance(d, dict):
        raise ApiError(422, "Invalid appearance settings.")
    theme = d.get("theme", DEFAULTS["theme"])
    if theme not in THEME_IDS:
        raise ApiError(422, "Unknown theme.", fields={"theme": "Choose one of the listed themes."})
    mode = d.get("mode", DEFAULTS["mode"])
    if mode not in MODES:
        raise ApiError(422, "Mode must be light, dark or system.", fields={"mode": "Invalid mode."})
    rainbow = d.get("rainbow", False)
    if not isinstance(rainbow, bool):
        raise ApiError(422, "Rainbow mode must be on or off.", fields={"rainbow": "Invalid value."})
    custom = d.get("custom")
    if custom is not None:
        if not isinstance(custom, dict):
            raise ApiError(422, "Invalid custom colours.")
        fixed = {}
        for k in CUSTOM_KEYS:
            v = custom.get(k)
            if not isinstance(v, str) or not HEX.match(v):
                raise ApiError(422, "Custom colours must be six-digit hex values such as #2563eb.", fields={f"custom.{k}": "Use a colour like #2563eb."})
            fixed[k] = v.lower()
        custom = fixed
    return {"theme": theme, "mode": mode, "rainbow": rainbow, "custom": custom}


def load(raw) -> dict | None:
    if not raw:
        return None
    try:
        return clean(json.loads(raw))
    except (ValueError, ApiError):
        return None


def dump(d: dict) -> str:
    return json.dumps(clean(d), separators=(",", ":"))
