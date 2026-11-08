"""Configuration, read from environment variables (optionally from a .env file)."""
import os
import secrets
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _flag(name: str, default: str = "0") -> bool:
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes", "on")


def build_config(overrides: dict | None = None) -> dict:
    _load_dotenv(BASE_DIR / ".env")
    env = os.environ.get("SMS_ENV", "development").strip().lower()
    data_dir = Path(os.environ.get("SMS_DATA_DIR", str(BASE_DIR / "data")))

    cfg = {
        "ENV": env,
        "SECRET_KEY": os.environ.get("SMS_SECRET_KEY") or os.environ.get("SECRET_KEY", ""),
        "DATA_DIR": str(data_dir),
        "DATABASE_PATH": os.environ.get("SMS_DATABASE_PATH", str(data_dir / "sms.db")),
        "UPLOAD_DIR": os.environ.get("SMS_UPLOAD_DIR", str(data_dir / "uploads")),
        "BACKUP_DIR": os.environ.get("SMS_BACKUP_DIR", str(data_dir / "backups")),
        "LOG_DIR": os.environ.get("SMS_LOG_DIR", str(data_dir / "logs")),
        "SESSION_IDLE_MINUTES": int(os.environ.get("SMS_SESSION_IDLE_MINUTES", "60")),
        "SESSION_MAX_HOURS": int(os.environ.get("SMS_SESSION_MAX_HOURS", "12")),
        "AUTO_BACKUP": _flag("SMS_AUTO_BACKUP", "1"),
        "BACKUP_KEEP": int(os.environ.get("SMS_BACKUP_KEEP", "14")),
        "TRUST_PROXY": _flag("SMS_TRUST_PROXY", "0"),
        "MAX_UPLOAD_MB": int(os.environ.get("SMS_MAX_UPLOAD_MB", "5")),
        # Cookies are Secure in production unless explicitly relaxed (plain-HTTP intranet).
        "COOKIE_SECURE": env == "production" and not _flag("SMS_INSECURE_COOKIES", "0"),
        "NOW_OVERRIDE": None,  # tests only
    }
    if overrides:
        cfg.update(overrides)

    import hashlib
    import logging

    log = logging.getLogger("sms.config")
    if not cfg["SECRET_KEY"]:
        # Never refuse to start just because the key was forgotten: keep a persistent random key in the
        # data folder so sessions survive restarts. Production should still set SECRET_KEY explicitly.
        key_file = Path(cfg["DATA_DIR"]) / (".generated_secret" if cfg["ENV"] == "production" else ".dev_secret")
        key_file.parent.mkdir(parents=True, exist_ok=True)
        if not key_file.exists():
            key_file.write_text(secrets.token_hex(32))
        cfg["SECRET_KEY"] = key_file.read_text().strip()
        if cfg["ENV"] == "production":
            log.warning("SECRET_KEY is not set; using a generated key stored in %s. Set SECRET_KEY in the environment.", key_file)
    elif len(cfg["SECRET_KEY"]) < 32:
        # A short key is stretched to a fixed-length key so the app still starts; a longer random key is better.
        log.warning("SECRET_KEY is shorter than 32 characters. Use a random value of 32+ characters.")
        cfg["SECRET_KEY"] = hashlib.sha256(cfg["SECRET_KEY"].encode()).hexdigest()
    return cfg
