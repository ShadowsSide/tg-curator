"""读取配置（bot/config.py）：填错时抛出 ConfigError，带中英文说明；填对时正常读取。用法：python tests/test_config.py
启动后待机、健康检查文件、Telegram 核对见 live_config_test.py。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bot.config import load_settings  # noqa: E402
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
    }
    for name, (value, key) in cases.items():
        got, zh, en = error(**{name: value})
        assert got == key, (name, got)
        assert name in zh and name in en, (zh, en)


if __name__ == "__main__":
    tests = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for fn in tests:
        fn()
        print("PASS ", fn.__name__)
    print(f"\n{len(tests)}/{len(tests)} passed")
