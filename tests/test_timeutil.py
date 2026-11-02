"""定时发布的时间解析（parse_time）。用法：python tests/test_timeutil.py"""
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bot.timeutil import MAX_AHEAD, parse_time  # noqa: E402

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
    assert parse_time("+999999999d", TZ, now) is None
    assert parse_time(f"+{MAX_AHEAD // 86400}d", TZ, now) == int(now.timestamp()) + MAX_AHEAD


if __name__ == "__main__":
    tests = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for fn in tests:
        fn()
        print("PASS ", fn.__name__)
    print(f"{len(tests)}/{len(tests)} passed")
