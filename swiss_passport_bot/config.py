from __future__ import annotations

import os
import shlex
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def load_dotenv(path: Path | None = None) -> None:
    env_path = path or PROJECT_ROOT / ".env"
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key or key in os.environ:
            continue
        try:
            parsed = shlex.split(value, comments=False, posix=True)
            os.environ[key] = parsed[0] if parsed else ""
        except ValueError:
            os.environ[key] = value.strip("\"'")


def env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return int(raw)


@dataclass(frozen=True)
class Settings:
    session_url: str
    calendar_url: str | None
    telegram_bot_token: str | None
    telegram_chat_id: str | None
    lookahead_days: int
    check_interval_seconds: int
    headless: bool
    browser_executable_path: str | None
    browser_channel: str | None
    page_timeout_ms: int
    state_dir: Path
    timezone: str
    locale: str
    alert_on_errors: bool
    watchdog_stale_after_seconds: int
    watchdog_alert_interval_seconds: int

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()
        session_url = os.getenv("SESSION_URL") or os.getenv("RESERVATION_URL") or ""
        calendar_url = os.getenv("CALENDAR_URL") or None
        executable_path = os.getenv("BROWSER_EXECUTABLE_PATH") or None

        if executable_path and not Path(executable_path).exists():
            executable_path = None

        return cls(
            session_url=session_url,
            calendar_url=calendar_url,
            telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN") or None,
            telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID") or None,
            lookahead_days=env_int("LOOKAHEAD_DAYS", 31),
            check_interval_seconds=env_int("CHECK_INTERVAL_SECONDS", 3600),
            headless=env_bool("HEADLESS", True),
            browser_executable_path=executable_path,
            browser_channel=os.getenv("BROWSER_CHANNEL") or None,
            page_timeout_ms=env_int("PAGE_TIMEOUT_MS", 45000),
            state_dir=Path(os.getenv("BOT_STATE_DIR", PROJECT_ROOT / ".state")).expanduser(),
            timezone=os.getenv("TIMEZONE", "Europe/London"),
            locale=os.getenv("BROWSER_LOCALE", "en-GB"),
            alert_on_errors=env_bool("ALERT_ON_ERRORS", False),
            watchdog_stale_after_seconds=env_int("WATCHDOG_STALE_AFTER_SECONDS", 7200),
            watchdog_alert_interval_seconds=env_int("WATCHDOG_ALERT_INTERVAL_SECONDS", 21600),
        )

    def require_site_config(self) -> None:
        if not self.session_url:
            raise ValueError("Missing SESSION_URL in .env.")

    def require_telegram_config(self) -> None:
        missing = []
        if not self.telegram_bot_token:
            missing.append("TELEGRAM_BOT_TOKEN")
        if not self.telegram_chat_id:
            missing.append("TELEGRAM_CHAT_ID")
        if missing:
            raise ValueError(f"Missing {', '.join(missing)} in .env.")
