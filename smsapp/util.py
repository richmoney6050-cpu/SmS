"""Shared helpers: errors, validation, dates."""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from flask import current_app, request


class ApiError(Exception):
    def __init__(self, status: int, message: str, code: str | None = None, fields: dict | None = None):
        super().__init__(message)
        self.status = status
        self.message = message
        self.code = code
        self.fields = fields or {}


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ------------------------------------------------------------------ request body
def body() -> dict:
    data = request.get_json(silent=True)
    if data is None:
        if request.content_length:
            raise ApiError(400, "The request body must be valid JSON.")
        return {}
    if not isinstance(data, dict):
        raise ApiError(400, "The request body must be a JSON object.")
    return data


_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class V:
    """Collects validation errors so the user sees every problem at once."""

    def __init__(self, data: dict):
        self.d = data
        self.err: dict[str, str] = {}
        self.out: dict = {}

    def _missing(self, key):
        v = self.d.get(key)
        return v is None or (isinstance(v, str) and not v.strip())

    def str(self, key, label=None, required=True, min_len=1, max_len=200, pattern=None, pattern_msg=None, default=None):
        label = label or key.replace("_", " ").capitalize()
        if self._missing(key):
            if required:
                self.err[key] = f"{label} is required."
            else:
                self.out[key] = default
            return self
        v = self.d[key]
        if not isinstance(v, str):
            self.err[key] = f"{label} must be text."
            return self
        v = v.strip()
        if _CONTROL.search(v):
            self.err[key] = f"{label} contains invalid characters."
        elif len(v) < min_len:
            self.err[key] = f"{label} must be at least {min_len} characters."
        elif len(v) > max_len:
            self.err[key] = f"{label} must be at most {max_len} characters."
        elif pattern and not re.fullmatch(pattern, v):
            self.err[key] = pattern_msg or f"{label} has an invalid format."
        else:
            self.out[key] = v
        return self

    def int(self, key, label=None, required=True, min_value=None, max_value=None, default=None):
        label = label or key.replace("_", " ").capitalize()
        if self._missing(key):
            if required:
                self.err[key] = f"{label} is required."
            else:
                self.out[key] = default
            return self
        v = self.d[key]
        if isinstance(v, bool):
            self.err[key] = f"{label} must be a whole number."
            return self
        try:
            n = int(v) if not isinstance(v, float) or v.is_integer() else None
            if n is None:
                raise ValueError
        except (TypeError, ValueError):
            self.err[key] = f"{label} must be a whole number."
            return self
        if min_value is not None and n < min_value:
            self.err[key] = f"{label} must be at least {min_value}."
        elif max_value is not None and n > max_value:
            self.err[key] = f"{label} must be at most {max_value}."
        else:
            self.out[key] = n
        return self

    def float(self, key, label=None, required=True, min_value=None, max_value=None, default=None):
        label = label or key.replace("_", " ").capitalize()
        if self._missing(key):
            if required:
                self.err[key] = f"{label} is required."
            else:
                self.out[key] = default
            return self
        v = self.d[key]
        if isinstance(v, bool):
            self.err[key] = f"{label} must be a number."
            return self
        try:
            n = float(v)
            if n != n or n in (float("inf"), float("-inf")):
                raise ValueError
        except (TypeError, ValueError):
            self.err[key] = f"{label} must be a number."
            return self
        if min_value is not None and n < min_value:
            self.err[key] = f"{label} must be at least {min_value}."
        elif max_value is not None and n > max_value:
            self.err[key] = f"{label} must be at most {max_value}."
        else:
            self.out[key] = round(n, 2)
        return self

    def date(self, key, label=None, required=True, default=None, not_future=False, min_date=None):
        label = label or key.replace("_", " ").capitalize()
        if self._missing(key):
            if required:
                self.err[key] = f"{label} is required."
            else:
                self.out[key] = default
            return self
        try:
            d = parse_date(self.d[key])
        except ApiError:
            self.err[key] = f"{label} must be a valid date (YYYY-MM-DD)."
            return self
        if not_future and d > today():
            self.err[key] = f"{label} cannot be in the future."
        elif min_date and d < min_date:
            self.err[key] = f"{label} is too far in the past."
        else:
            self.out[key] = d.isoformat()
        return self

    def enum(self, key, choices, label=None, required=True, default=None):
        label = label or key.replace("_", " ").capitalize()
        if self._missing(key):
            if required:
                self.err[key] = f"{label} is required."
            else:
                self.out[key] = default
            return self
        v = self.d[key]
        if not isinstance(v, str) or v.strip().lower() not in choices:
            self.err[key] = f"{label} must be one of: {', '.join(choices)}."
        else:
            self.out[key] = v.strip().lower()
        return self

    def bool(self, key, default=False):
        v = self.d.get(key, default)
        self.out[key] = v in (True, 1, "1", "true", "True")
        return self

    def done(self) -> dict:
        if self.err:
            raise ApiError(422, "Please correct the highlighted fields.", code="validation", fields=self.err)
        return self.out


def parse_date(value) -> date:
    if isinstance(value, date):
        return value
    try:
        if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value.strip()):
            raise ValueError
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except ValueError:
        raise ApiError(400, "Dates must be in YYYY-MM-DD format.")


def arg_date(name: str, default: date | None = None) -> date | None:
    v = request.args.get(name)
    if not v:
        return default
    return parse_date(v)


def arg_int(name: str, default: int | None = None) -> int | None:
    v = request.args.get(name)
    if v in (None, ""):
        return default
    try:
        return int(v)
    except ValueError:
        raise ApiError(400, f"'{name}' must be a whole number.")


# ------------------------------------------------------------------ time
def school_tz():
    from . import settings

    try:
        return ZoneInfo(settings.get("timezone"))
    except Exception:
        return timezone.utc


def local_now() -> datetime:
    override = current_app.config.get("NOW_OVERRIDE")
    now = override() if callable(override) else datetime.now(timezone.utc)
    return now.astimezone(school_tz())


def today() -> date:
    return local_now().date()


def day_bounds_utc(d: date) -> tuple[str, str]:
    """UTC ISO bounds [start, end) of a local calendar day."""
    tz = school_tz()
    start = datetime(d.year, d.month, d.day, tzinfo=tz).astimezone(timezone.utc)
    end = (datetime(d.year, d.month, d.day, tzinfo=tz) + timedelta(days=1)).astimezone(timezone.utc)
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    return start.strftime(fmt), end.strftime(fmt)


def school_weekdays() -> set[int]:
    from . import settings

    out = set()
    for part in str(settings.get("school_days")).split(","):
        part = part.strip()
        if part.isdigit() and 1 <= int(part) <= 7:
            out.add(int(part))
    return out or {1, 2, 3, 4, 5}


def is_school_day(d: date) -> bool:
    return d.isoweekday() in school_weekdays()


def school_days_between(start: date, end: date) -> list[date]:
    days, d = [], start
    wk = school_weekdays()
    while d <= end:
        if d.isoweekday() in wk:
            days.append(d)
        d += timedelta(days=1)
    return days


def last_school_days(n: int, end: date | None = None) -> list[date]:
    end = end or today()
    out, d, wk = [], end, school_weekdays()
    guard = 0
    while len(out) < n and guard < 400:
        if d.isoweekday() in wk:
            out.append(d)
        d -= timedelta(days=1)
        guard += 1
    return list(reversed(out))


def pct(num, den, digits=1):
    if not den:
        return None
    return round(num / den * 100, digits)


def like(q: str) -> str:
    esc = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{esc}%"
