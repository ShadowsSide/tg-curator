"""二次确认按钮和审核员判断的单元测试。用法：python tests/test_confirm.py"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bot.i18n import LANGS  # noqa: E402
from bot.keyboards import CONFIRMABLE, CONFIRMED, ReviewCB, confirm_kb  # noqa: E402
from bot.permissions import ReviewerCheck, ReviewerPolicy  # noqa: E402

REVIEW = -1001


def test_confirm_kb_has_confirm_and_back():
    for lang in LANGS:
        for action in CONFIRMABLE:
            rows = confirm_kb(123456789, action, lang).inline_keyboard
            confirm, back = rows[0][0], rows[1][0]
            assert ReviewCB.unpack(confirm.callback_data) == ReviewCB(a=action + CONFIRMED, sid=123456789)
            assert ReviewCB.unpack(back.callback_data).a == "back"
            assert confirm.style == CONFIRMABLE[action]


def test_confirmed_actions_fit_callback_limit():
    # Telegram 限制 callback_data 最多 64 字节
    for action in CONFIRMABLE:
        assert len(ReviewCB(a=action + CONFIRMED, sid=2**31, v=2**31).pack().encode()) <= 64


def test_confirmed_action_maps_back_to_original():
    for action in CONFIRMABLE:
        assert (action + CONFIRMED).removesuffix(CONFIRMED) == action
        assert action + CONFIRMED not in CONFIRMABLE  # 确认后的动作不会再弹一次确认


def _allowed(policy, user_id, sender_chat_id=None, is_bot=False):
    check = ReviewerCheck(ReviewerPolicy.parse(policy), REVIEW)
    # 这些分支都不需要查询 Telegram（bot=None）
    return asyncio.run(check.allowed(None, user_id, sender_chat_id, is_bot=is_bot))


def test_bots_are_never_reviewers():
    assert not _allowed("all", 66, is_bot=True)
    assert not _allowed("66", 66, is_bot=True)
    assert not _allowed("admins", 66, is_bot=True)


def test_anonymous_admin_still_allowed():
    # 以群身份发言时 from_user 是匿名管理员机器人（is_bot=True），按管理员处理
    assert _allowed("admins", 1087968824, REVIEW, is_bot=True)
    assert _allowed("all", 1087968824, REVIEW, is_bot=True)
    assert not _allowed("55", 1087968824, REVIEW, is_bot=True)


def test_humans_unchanged():
    assert _allowed("all", 99)
    assert _allowed("admins,55", 55)
    assert not _allowed("55", 99)


if __name__ == "__main__":
    tests = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for fn in tests:
        fn()
        print("PASS ", fn.__name__)
    print(f"{len(tests)}/{len(tests)} passed")
