"""读取配置（bot/config.py）：填错时抛出 ConfigError，带中英文说明；填对时正常读取。用法：python tests/test_config.py
启动后待机、健康检查文件、Telegram 核对见 live_config_test.py。
"""
import asyncio
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bot.config import load_settings  # noqa: E402
from bot.core.submissions import SubmissionsMixin  # noqa: E402
from bot.errors import ConfigError  # noqa: E402

BASE = {"BOT_TOKEN": "123:abc", "CHANNEL_ID": "@chan", "REVIEW_CHAT_ID": "-1001"}


def load(**env):
    old = dict(os.environ)
    os.environ.clear()
    os.environ.update({**BASE, **env})
    try:
        return load_settings()
    finally:
        os.environ.clear()
        os.environ.update(old)


def error(**env):
    try:
        load(**env)
    except ConfigError as e:
        return e.notice.key, e.notice.text("zh"), e.notice.text("en")
    raise AssertionError(f"no ConfigError for {env}")


def test_valid_settings_load():
    s = load(ALBUM_DELAY="2.5", REMINDER_QUIET_HOURS="23-7", MAX_LINKS="3")
    assert (s.review_chat_id, s.channel_id, s.album_delay, s.quiet_hours) == (-1001, "@chan", 2.5, (23, 7))


def test_each_required_value_missing_or_blank():
    for name in BASE:
        assert error(**{name: "  "})[:2] == ("cfg_missing", f"没有填写 {name}")


def test_malformed_values():
    cases = {
        "BOT_TOKEN": ("123456", "cfg_token_format"),
        "REVIEW_CHAT_ID": ("@group", "cfg_number"),
        "ALBUM_DELAY": ("fast", "cfg_number"),
        "TZ": ("Mars/Base", "cfg_tz"),
        "REMINDER_QUIET_HOURS": ("night", "cfg_quiet_hours"),
        "LANGUAGE": ("fr", "cfg_choice"),
        "SPAM_ACTION": ("delete", "cfg_choice"),
        "STATS_SCOPE": ("todya", "cfg_choice"),
        "BACKUP_TIME": ("25:00", "cfg_clock"),
        "CALLBACK_FALLBACK_SECONDS": ("nan", "cfg_number"),
        "DEFAULT_SILENT": ("ture", "cfg_choice"),
        "REMINDER_ONLY_WHEN_PENDING": ("y", "cfg_choice"),
        "LEAVE_UNKNOWN_CHATS": ("flase", "cfg_choice"),
    }
    for name, (value, key) in cases.items():
        got, zh, en = error(**{name: value})
        assert got == key, (name, got)
        assert name in zh and name in en, (zh, en)


def test_switches():
    """开关认 true / false 和几种常见写法（不分大小写）；留空算 false。"""
    for value, want in (("true", True), ("TRUE", True), ("1", True), ("yes", True), ("on", True),
                        ("false", False), ("False", False), ("0", False), ("no", False), ("off", False), ("", False)):
        s = load(DEFAULT_SILENT=value, REMINDER_ONLY_WHEN_PENDING=value, LEAVE_UNKNOWN_CHATS=value)
        assert (s.default_silent, s.reminder_only_when_pending, s.leave_unknown_chats) == (want,) * 3, value
    s = load()
    assert (s.default_silent, s.reminder_only_when_pending, s.leave_unknown_chats) == (False, True, True)


def test_album_delay():
    """等待秒数不能是负数，也不能是 nan / inf（float 认这些写法）；0 可以。"""
    assert load(ALBUM_DELAY="0").album_delay == 0
    assert error(ALBUM_DELAY="-1")[0] == "cfg_negative"
    for value in ("nan", "inf", "-inf"):
        assert error(ALBUM_DELAY=value)[0] == "cfg_number", value


def test_quiet_hours():
    """安静时段跨零点也能用；开始和结束是同一个小时（会变成全天安静）时报错。"""
    for value, start_end in (("23-7", (23, 7)), ("0-8", (0, 8)), ("24-6", (0, 6))):
        assert load(REMINDER_QUIET_HOURS=value).quiet_hours == start_end, value
    for value in ("8-8", "0-24"):
        got, zh, en = error(REMINDER_QUIET_HOURS=value)
        assert got == "cfg_quiet_hours_same" and value in zh and value in en, (value, got)


COUNTS = ("MAX_PENDING_PER_USER", "MSG_WINDOW_DAYS", "REMINDER_INTERVAL_MINUTES", "MAX_LINKS", "NEW_USER_COOLDOWN_MINUTES",
          "BACKUP_KEEP")


def test_backup_settings():
    """备份时间默认 04:00，统一成两位数；中文冒号也认；写错（不是 HH:MM）启动时报错。"""
    s = load()
    assert (s.backup_time, s.backup_keep) == ("04:00", 7)
    for value, want in (("4:05", "04:05"), ("23：30", "23:30"), ("00:00", "00:00")):
        assert load(BACKUP_TIME=value).backup_time == want, value
    for value in ("4", "04:60", "", "noon"):
        assert error(BACKUP_TIME=value)[0] == "cfg_clock", value


def test_counts_not_negative():
    """负数启动时就报错；0 可以（投稿上限、链接数、新用户冷却不限 / 审核结束后不能再沟通 / 不发提醒）。"""
    for name in COUNTS:
        got, zh, en = error(**{name: "-1"})
        assert got == "cfg_negative" and name in zh and "负数" in zh and "negative" in en, (name, got, zh, en)
    s = load(**{name: "0" for name in COUNTS})
    assert (s.max_pending_per_user, s.msg_window_days, s.reminder_interval_min, s.new_user_cooldown_min) == (0, 0, 0, 0)


def test_max_pending_zero_is_unlimited():
    async def at_limit(limit, open_count):
        async def count_open_by_user(user_id, statuses):
            return open_count
        core = SimpleNamespace(s=SimpleNamespace(max_pending_per_user=limit),
                               db=SimpleNamespace(count_open_by_user=count_open_by_user))
        return await SubmissionsMixin._at_limit(core, 1)
    assert asyncio.run(at_limit(0, 1000)) is False  # 0：不限
    assert asyncio.run(at_limit(5, 4)) is False
    assert asyncio.run(at_limit(5, 5)) is True


if __name__ == "__main__":
    tests = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for fn in tests:
        fn()
        print("PASS ", fn.__name__)
    print(f"\n{len(tests)}/{len(tests)} passed")
