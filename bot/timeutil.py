from __future__ import annotations

import re
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


def now_ts() -> int:
    return int(time.time())


def fmt_ts(ts: int | None, tz: ZoneInfo) -> str:
    if not ts:
        return "-"
    dt = datetime.fromtimestamp(ts, tz)
    if dt.date() == datetime.now(tz).date():
        return dt.strftime("今天 %H:%M")
    return dt.strftime("%m-%d %H:%M")


def start_of_today(tz: ZoneInfo) -> int:
    now = datetime.now(tz)
    return int(now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp())


def utc_offset(tz: ZoneInfo) -> int:
    return int(datetime.now(tz).utcoffset().total_seconds())


def next_occurrence(hhmm: str, tz: ZoneInfo, now: datetime | None = None) -> datetime:
    """下一次出现的 HH:MM（今天还没到就是今天，否则明天）。"""
    now = now or datetime.now(tz)
    hour, minute = (int(x) for x in hhmm.split(":"))
    dt = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if dt <= now:
        dt += timedelta(days=1)
    return dt


_RELATIVE = re.compile(r"\+\s*(\d+)\s*(m|min|分钟?|h|小时|d|天)?", re.IGNORECASE)
_UNITS = {"m": 60, "min": 60, "分": 60, "分钟": 60, "h": 3600, "小时": 3600, "d": 86400, "天": 86400}


def parse_time(text: str, tz: ZoneInfo, now: datetime | None = None) -> int | None:
    """支持：20:30 / 10-20 09:00 / 2026-10-20 09:00 / +90m / +2h / +1d。返回 unix 时间戳。"""
    now = now or datetime.now(tz)
    text = text.strip().replace("：", ":").replace("/", "-")
    text = re.sub(r"\s+", " ", text)

    m = _RELATIVE.fullmatch(text)
    if m:
        unit = (m.group(2) or "m").lower()
        return int(now.timestamp()) + int(m.group(1)) * _UNITS[unit]

    try:
        t = datetime.strptime(text, "%H:%M")
        return int(next_occurrence(f"{t.hour}:{t.minute}", tz, now).timestamp())
    except ValueError:
        pass

    try:
        return int(datetime.strptime(text, "%Y-%m-%d %H:%M").replace(tzinfo=tz).timestamp())
    except ValueError:
        pass

    # 不带年份：默认今年，已过去则视为明年
    try:
        dt = datetime.strptime(f"{now.year}-{text}", "%Y-%m-%d %H:%M").replace(tzinfo=tz)
    except ValueError:
        return None
    if dt <= now:
        dt = dt.replace(year=now.year + 1)
    return int(dt.timestamp())
