"""拒绝理由模板（REJECT_TEMPLATES）的单元测试。用法：python tests/test_reject_templates.py"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bot.config import _templates, load_settings  # noqa: E402
from bot.keyboards import ReviewCB, confirm_kb, reasons_kb  # noqa: E402

CJK = re.compile(r"[一-鿿]")
REQUIRED = {"BOT_TOKEN": "1:x", "CHANNEL_ID": "@c", "REVIEW_CHAT_ID": "-1001"}


def _settings(**env):
    saved = dict(os.environ)
    os.environ.update(REQUIRED)
    os.environ.pop("REJECT_TEMPLATES", None)
    os.environ.update(env)
    try:
        return load_settings()
    finally:
        os.environ.clear()
        os.environ.update(saved)


def _cbs(kb):
    return [(b.text, ReviewCB.unpack(b.callback_data)) for row in kb.inline_keyboard for b in row]


def test_parse_templates():
    assert _templates("重复投稿| 广告 ||  ") == ("重复投稿", "广告")
    assert _templates("") == ()


def test_defaults_follow_language_and_empty_disables():
    assert len(_settings(LANGUAGE="zh").reject_templates) == 4
    en = _settings(LANGUAGE="en").reject_templates
    assert en and not any(CJK.search(x) for x in en)
    assert _settings(REJECT_TEMPLATES="").reject_templates == ()
    assert _settings(REJECT_TEMPLATES="A|B").reject_templates == ("A", "B")


def test_reject_template_index_is_one_based_and_safe():
    s = _settings(REJECT_TEMPLATES="A|B")
    assert s.reject_template(1) == "A" and s.reject_template(2) == "B"
    assert s.reject_template(0) is None  # 不附理由
    assert s.reject_template(3) is None and s.reject_template(-1) is None  # 理由改少了以后点旧按钮


def test_reasons_kb():
    cbs = _cbs(reasons_kb(9, ("A", "B", "C"), "zh"))
    assert [(text, cb.a, cb.v) for text, cb in cbs[:3]] == [("A", "reason", 1), ("B", "reason", 2), ("C", "reason", 3)]
    assert (cbs[3][1].a, cbs[3][1].v) == ("reason", 0)  # 不附理由
    assert cbs[4][1].a == "back"
    assert all(cb.sid == 9 for _, cb in cbs)
    assert not any(CJK.search(text) for text, _ in _cbs(reasons_kb(9, ("A",), "en")))


def test_confirm_kb_carries_reason():
    (text, cb), _ = _cbs(confirm_kb(9, "reject", "zh", 2, "广告"))
    assert (cb.a, cb.v) == ("reject_ok", 2) and text.endswith("：广告")
    (text, _), _ = _cbs(confirm_kb(9, "reject", "en", 2, "Ads"))
    assert text.endswith(": Ads") and not CJK.search(text)


if __name__ == "__main__":
    tests = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for fn in tests:
        fn()
        print("PASS ", fn.__name__)
    print(f"{len(tests)}/{len(tests)} passed")
