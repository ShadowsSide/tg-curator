from __future__ import annotations

import os
from dataclasses import dataclass
from zoneinfo import ZoneInfo


def _env(name: str, default: str = "", *, required: bool = False) -> str:
    value = os.getenv(name, default).strip()
    if required and not value:
        raise RuntimeError(f"缺少环境变量 {name}")
    return value


def _bool(value: str) -> bool:
    return value.lower() in ("1", "true", "yes", "on")


def _chat_id(value: str) -> int | str:
    return int(value) if value.lstrip("-").isdigit() else value


def _quiet_hours(value: str) -> tuple[int, int] | None:
    if not value:
        return None
    start, end = value.split("-", 1)
    return int(start) % 24, int(end) % 24


@dataclass(frozen=True)
class Settings:
    bot_token: str
    channel_id: int | str
    review_chat_id: int
    tz: ZoneInfo
    db_path: str
    album_delay: float
    max_pending_per_user: int
    sign_template: str
    anon_signature: str
    schedule_presets: tuple[str, ...]
    reminder_interval_min: int
    reminder_only_when_pending: bool
    quiet_hours: tuple[int, int] | None
    stats_scope: str
    default_silent: bool
    proxy: str
    api_url: str

    def in_quiet_hours(self, hour: int) -> bool:
        if not self.quiet_hours:
            return False
        start, end = self.quiet_hours
        if start < end:
            return start <= hour < end
        return hour >= start or hour < end


def load_settings() -> Settings:
    return Settings(
        bot_token=_env("BOT_TOKEN", required=True),
        channel_id=_chat_id(_env("CHANNEL_ID", required=True)),
        review_chat_id=int(_env("REVIEW_CHAT_ID", required=True)),
        tz=ZoneInfo(_env("TZ", "Asia/Shanghai")),
        db_path=_env("DB_PATH", "/app/data/bot.db"),
        album_delay=float(_env("ALBUM_DELAY", "1.5")),
        max_pending_per_user=int(_env("MAX_PENDING_PER_USER", "5")),
        sign_template=_env("SIGN_TEMPLATE", "投稿人：{name}"),
        anon_signature=_env("ANON_SIGNATURE", "匿名投稿"),
        schedule_presets=tuple(
            p.strip() for p in _env("SCHEDULE_PRESETS", "09:00,12:00,18:00,21:00").split(",") if p.strip()
        ),
        reminder_interval_min=int(_env("REMINDER_INTERVAL_MINUTES", "60")),
        reminder_only_when_pending=_bool(_env("REMINDER_ONLY_WHEN_PENDING", "true")),
        quiet_hours=_quiet_hours(_env("REMINDER_QUIET_HOURS", "")),
        stats_scope=_env("STATS_SCOPE", "today"),
        default_silent=_bool(_env("DEFAULT_SILENT", "false")),
        proxy=_env("PROXY"),
        api_url=_env("TELEGRAM_API_URL"),
    )
