"""界面文案测试：中英文都齐全、占位符一致，英文界面里不夹杂中文。用法：python tests/test_i18n.py"""
import os
import re
import string
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bot.db import Submission, User  # noqa: E402
from bot.i18n import LANGS, PRIVATE_COMMANDS, REVIEW_COMMANDS, T, normalize, t  # noqa: E402
from bot.keyboards import control_kb, schedule_kb, user_choice_kb  # noqa: E402
from bot.render import control_text, describe, stats_text  # noqa: E402

CJK = re.compile(r"[一-鿿]")
TZ = ZoneInfo("Asia/Shanghai")


def fields(text: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


def test_every_key_has_all_languages_with_same_placeholders():
    for key, entry in T.items():
        assert set(entry) == set(LANGS), f"{key}: missing {set(LANGS) - set(entry)}"
        assert fields(entry["zh"]) == fields(entry["en"]), f"{key}: placeholders differ"


def test_english_texts_have_no_chinese():
    allowed = {"default_sign", "default_anon"}  # 这两个是按语言取值，英文版本身也不含中文
    for key, entry in T.items():
        if key not in allowed:
            assert not CJK.search(entry["en"]), f"{key}: Chinese in English text"


def test_commands_match_between_languages():
    for table in (PRIVATE_COMMANDS, REVIEW_COMMANDS):
        names = {lang: [c for c, _ in table[lang]] for lang in LANGS}
        assert names["zh"] == names["en"]


def test_normalize():
    assert normalize("zh-hans") == "zh" and normalize("zh-TW") == "zh"
    assert normalize("en") == "en" and normalize("ru") == "en" and normalize("ja") == "en"
    assert normalize(None, fallback="en") == "en" and normalize("", fallback="zh") == "zh"


def _sub(status="pending", **kw):
    base = dict(
        id=7, user_id=42, items=[{"type": "photo", "file_id": "x", "text": ""}] * 2, anonymous=True,
        spoiler=True, silent=True, status=status, decision=None, created_at=0, submitted_at=0, reviewed_at=0,
        reviewer_id=1, reviewer_name="Admin", scheduled_at=int(datetime.now(TZ).timestamp()) + 3600,
        published_at=int(datetime.now(TZ).timestamp()), user_msg_id=None, review_msg_id=None, channel_msg_id=5,
        reject_reason="spam", original_items=None, edited_by="submitter Bob",
        edited_at=int(datetime.now(TZ).timestamp()), review_topic_id=None, user_topic_id=None, topic_status=None, msg_count=2,
        error="Bad Request",
    )
    base.update(kw)
    return Submission(**base)


def _texts(markup):
    return [b.text for row in markup.inline_keyboard for b in row] if markup else []


def test_english_review_ui_has_no_chinese():
    user = User(42, "bob", "Bob", True, "spam", 0, "Admin", "en", 0, 0)
    for status in ("pending", "scheduled", "publishing", "published", "rejected", "failed"):
        sub = _sub(status)
        text = control_text(sub, user, TZ, "https://t.me/c/1/5", "en")
        assert not CJK.search(text), (status, text)
        assert not any(CJK.search(x) for x in _texts(control_kb(sub, "en"))), status
    assert not any(CJK.search(x) for x in _texts(schedule_kb(7, ("09:00", "21:00"), TZ, "en")))
    assert not any(CJK.search(x) for x in _texts(user_choice_kb(7, "en")))
    stats = stats_text(3, 1, 4, datetime(2026, 1, 1, 16, 3, 10), "en")
    assert stats == "Accepted 3 Rejected 1 Pending 4\nApproval rate: 75.00% Review rate: 50.00%\n#review_stats [updated 16:03:10]"
    assert describe([{"type": "photo"}, {"type": "photo"}, {"type": "video"}], "en") == "2 photo(s), 1 video(s)"


def test_chinese_stats_format_unchanged():
    assert stats_text(0, 0, 4, datetime(2026, 1, 1, 16, 3, 10), "zh") == (
        "接受 0 拒绝 0 待审核 4\n通过率: 0.00% 审核率: 0.00%\n#审核统计 [更新于 16:03:10]")
    assert describe([{"type": "photo"}] * 3, "zh") == "3 张图片"
    assert t("zh", "ctrl_title") == "📮 <b>新投稿</b>"


def test_no_submission_numbers_in_texts():
    for key, entry in T.items():
        for lang in LANGS:
            assert "{sid}" not in entry[lang] and "{ids}" not in entry[lang], f"{key}/{lang} shows a submission number"


if __name__ == "__main__":
    tests = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for fn in tests:
        fn()
        print("PASS ", fn.__name__)
    print(f"{len(tests)}/{len(tests)} passed")
