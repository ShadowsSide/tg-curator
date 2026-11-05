"""定时发布的时间解析（parse_time）。用法：python tests/test_timeutil.py"""
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bot.timeutil import MAX_AHEAD, TimeTooFar, fmt_ts, parse_time  # noqa: E402

TZ = ZoneInfo("Asia/Shanghai")


def at(*args):
    return datetime(*args, tzinfo=TZ)


def test_formats():
    now = at(2026, 10, 20, 12, 0)
    assert parse_time("20:30", TZ, now) == int(at(2026, 10, 20, 20, 30).timestamp())
    assert parse_time("08:00", TZ, now) == int(at(2026, 10, 21, 8, 0).timestamp())  # 今天已过：明天
    assert parse_time("2026-12-01 09:00", TZ, now) == int(at(2026, 12, 1, 9, 0).timestamp())
    assert parse_time("10-01 09:00", TZ, now) == int(at(2027, 10, 1, 9, 0).timestamp())  # 今年已过：明年
    assert parse_time("+90m", TZ, now) == int(now.timestamp()) + 90 * 60
    assert parse_time("+2天", TZ, now) == int(now.timestamp()) + 2 * 86400
    assert parse_time("明天", TZ, now) is None


def test_leap_day_already_passed():
    """闰年的 02-29 已经过了：明年没有这一天，返回 None（提示格式不对），不能报错。"""
    now = at(2028, 3, 1, 12, 0)
    assert parse_time("02-29 09:00", TZ, now) is None
    assert parse_time("02-29 09:00", TZ, at(2028, 2, 1)) == int(at(2028, 2, 29, 9, 0).timestamp())
    assert parse_time("02-29 09:00", TZ, at(2026, 1, 1)) is None  # 平年没有 02-29


def test_huge_relative_time():
    now = at(2026, 10, 20, 12, 0)
    try:  # 格式是对的，只是太远：和“看不懂”分开，提示里说清楚
        parse_time("+999999999d", TZ, now)
        raise AssertionError("expected TimeTooFar")
    except TimeTooFar:
        pass
    assert parse_time(f"+{MAX_AHEAD // 86400}d", TZ, now) == int(now.timestamp()) + MAX_AHEAD


def test_fmt_ts_year():
    now = at(2026, 12, 20, 12, 0)
    ts = lambda *a: int(at(*a).timestamp())  # noqa: E731
    assert fmt_ts(ts(2026, 12, 20, 21, 0), TZ, "zh", now) == "今天 21:00"
    assert fmt_ts(ts(2026, 12, 20, 21, 0), TZ, "en", now) == "today 21:00"
    assert fmt_ts(ts(2026, 3, 1, 9, 5), TZ, "zh", now) == "03-01 09:05"
    # 12-20 定时 “01-05 09:00” 存的是明年：要带上年份，不然看起来像今年
    assert fmt_ts(parse_time("01-05 09:00", TZ, now), TZ, "zh", now) == "2027-01-05 09:00"
    assert fmt_ts(ts(2025, 12, 31, 23, 0), TZ, "zh", now) == "2025-12-31 23:00"
    assert fmt_ts(None, TZ, "zh", now) == "-"
    next_year = datetime.now(TZ).year + 1  # 不传 now：按当前时间
    assert fmt_ts(ts(next_year, 1, 5, 9, 0), TZ) == f"{next_year}-01-05 09:00"


if __name__ == "__main__":
    tests = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for fn in tests:
        fn()
        print("PASS ", fn.__name__)
    print(f"{len(tests)}/{len(tests)} passed")
