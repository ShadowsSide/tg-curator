"""二次确认按钮、按钮多步流程（route）和审核员判断的单元测试。用法：python tests/test_confirm.py"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bot.i18n import LANGS  # noqa: E402
from bot.keyboards import CONFIRMABLE, CONFIRMED, ReviewCB, confirm_kb, route  # noqa: E402
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


def test_route_every_review_action():
    # (按钮动作, v, 是否配置了拒绝理由) → (步骤, 动作, v)
    cases = [
        # 拒绝：有理由 → 先选理由；没理由 → 直接确认
        (("reject", 0, True), ("reasons", "reject", 0)),
        (("reject", 0, False), ("confirm", "reject", 0)),
        # 理由面板上选了一项 → 当作拒绝进确认，理由序号带到确认按钮；不能再弹一次理由面板
        (("reason", 2, True), ("confirm", "reject", 2)),
        (("reason", 0, True), ("confirm", "reject", 0)),  # 不附理由
        (("reason", 2, False), ("confirm", "reject", 2)),  # 理由配置被清空后点旧面板
        # 确认按钮 → 真正执行，去掉 _ok，v 原样
        (("reject_ok", 2, True), ("run", "reject", 2)),
        (("reject_ok", 0, False), ("run", "reject", 0)),
        (("pub", 0, True), ("confirm", "pub", 0)),
        (("pub_ok", 0, True), ("run", "pub", 0)),
        (("ban", 0, True), ("confirm", "ban", 0)),
        (("ban_ok", 0, True), ("run", "ban", 0)),
        (("mrm", 2, True), ("confirm", "mrm", 2)),  # 删除媒体：v 是第几个，原样带到确认按钮
        (("mrm_ok", 2, True), ("run", "mrm", 2)),
        (("madd", 0, True), ("run", "madd", 0)),
        (("mrep", 3, True), ("run", "mrep", 3)),
        # 其余按钮不需要确认
        (("retry", 0, True), ("run", "retry", 0)),
        (("unsched", 0, True), ("run", "unsched", 0)),
        (("sched", 0, True), ("run", "sched", 0)),
        (("preset", 1767225600, True), ("run", "preset", 1767225600)),  # v 是时间戳，不能被改动
        (("custom", 0, True), ("run", "custom", 0)),
        (("back", 0, True), ("run", "back", 0)),
        (("spoiler", 0, True), ("run", "spoiler", 0)),
        (("silent", 0, True), ("run", "silent", 0)),
        (("unknown", 0, True), ("run", "unknown", 0)),  # 未知动作交给处理函数的 else（只应答）
    ]
    for args, expected in cases:
        assert route(*args) == expected, (args, route(*args), expected)


def test_route_never_loops():
    # 任何一步之后再点出现的按钮，最多两步就到“执行”：理由面板 → 确认面板 → 执行
    for action in (*CONFIRMABLE, "reason", "retry", "sched"):
        for has_reasons in (True, False):
            step, a, v, seen = None, action, 1, []
            while step != "run":
                step, a, v = route(a, v, has_reasons)
                seen.append(step)
                # 理由面板上点的是 reason，确认面板上点的是 <动作>_ok
                a = "reason" if step == "reasons" else a + CONFIRMED if step == "confirm" else a
                assert len(seen) <= 3, (action, has_reasons, seen)


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
