from __future__ import annotations

import re
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


def now_ts() -> int:
    return int(time.time())


def fmt_ts(ts: int | None, tz: ZoneInfo, lang: str = "zh", now: datetime | None = None) -> str:
    """今天：今天 HH:MM；今年：MM-DD HH:MM；其他年份带上年份，免得定到明年的看起来像今年。"""
    if not ts:
        return "-"
    dt = datetime.fromtimestamp(ts, tz)
    now = now or datetime.now(tz)
    if dt.date() == now.date():
        return f"{'今天' if lang == 'zh' else 'today'} {dt:%H:%M}"
    return dt.strftime("%m-%d %H:%M" if dt.year == now.year else "%Y-%m-%d %H:%M")


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
MAX_AHEAD = 3650 * 86400  # 相对时间最多 10 年：再大就超出日期范围，显示时间时会出错


class TimeTooFar(ValueError):
    """相对时间超过 MAX_AHEAD：格式是对的，只是太远，提示要和“看不懂”分开，免得以为不支持 +Nd。"""


def parse_time(text: str, tz: ZoneInfo, now: datetime | None = None) -> int | None:
    """支持：20:30 / 10-20 09:00 / 2026-10-20 09:00 / +90m / +2h / +1d。返回 unix 时间戳；看不懂返回 None。
    相对时间超过 MAX_AHEAD 时抛出 TimeTooFar。"""
    now = now or datetime.now(tz)
    text = text.strip().replace("：", ":").replace("/", "-")
    text = re.sub(r"\s+", " ", text)

    m = _RELATIVE.fullmatch(text)
    if m:
        unit = (m.group(2) or "m").lower()
        ahead = int(m.group(1)) * _UNITS[unit]
        if ahead > MAX_AHEAD:
            raise TimeTooFar(text)
        return int(now.timestamp()) + ahead

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
        try:
            dt = dt.replace(year=now.year + 1)
        except ValueError:  # 闰年的 02-29 已经过了：明年没有这一天
            return None
    return int(dt.timestamp())
