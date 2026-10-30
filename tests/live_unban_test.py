"""🔓 解除封禁按钮：封禁后控制消息显示“解除封禁”，要二次确认；解封后通知投稿人、收起按钮。
用 /unban 解封后，别的控制消息上留下的旧按钮点了只提示“没有被封禁”并收起，不出确认面板。

用法（项目根目录下）：python tests/live_unban_test.py
复用 live_test.py 的模拟 Bot API 服务器。约 10 秒。
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import live_test as lt  # noqa: E402
from live_test import ADMIN, REVIEW, USER, buttons, check, gm, is_send, log, submit, wait_for  # noqa: E402


def ctrl_edit(message_id, since):
    """since 之后这条控制消息被刷新（换文字和按钮，或只换按钮）。"""
    return wait_for(lambda e: e["method"] in ("editMessageText", "editMessageReplyMarkup")
                    and str(e["params"].get("message_id")) == str(message_id), since=since)


def toast(since, contains):
    return wait_for(lambda e: e["method"] == "answerCallbackQuery" and contains in e["params"].get("text", ""),
                    since=since)


async def scenario():
    await wait_for(lambda e: e["method"] == "setMyCommands", 15, since=0)
    c1 = await submit("解封测试 一", 1)
    ctrl1 = c1["result"]["message_id"]
    check("not banned → no Unban button", not any(v.startswith("r:unban:") for v in buttons(c1).values()))

    # 1. 用按钮封禁：被拒绝的那条控制消息上出现“解除封禁”
    n = len(log); lt.cb("r:ban_ok:1:0", REVIEW, ADMIN, message_id=ctrl1)
    banned = await ctrl_edit(ctrl1, n)
    check("after ban → control message shows 🔓 Unban", banned and buttons(banned) == {"🔓 解除封禁": "r:unban:1:0"},
          banned and buttons(banned))

    # 2. 点“解除封禁”先出确认面板，返回不解封
    n = len(log); lt.cb("r:unban:1:0", REVIEW, ADMIN, message_id=ctrl1)
    panel = await ctrl_edit(ctrl1, n)
    check("Unban → confirm panel", panel and buttons(panel).get("🔓 确认解封（会通知投稿人）") == "r:unban_ok:1:0",
          panel and buttons(panel))
    n = len(log); lt.cb("r:back:1:0", REVIEW, ADMIN, message_id=ctrl1)
    back = await ctrl_edit(ctrl1, n)
    told = await wait_for(lambda e: is_send(e, "sendMessage", USER, "恢复"), timeout=0.5, since=n)
    check("Back → still banned, button still there, submitter not told",
          back and buttons(back) == {"🔓 解除封禁": "r:unban:1:0"} and not told)

    # 3. 确认：解封、通知投稿人、按钮收起
    n = len(log); lt.cb("r:unban_ok:1:0", REVIEW, ADMIN, message_id=ctrl1)
    t = await toast(n, "已解除封禁")
    told = await wait_for(lambda e: is_send(e, "sendMessage", USER, "投稿权限已恢复"), since=n)
    done = await ctrl_edit(ctrl1, n)
    check("confirm → unbanned, submitter told, button gone", t and told and done and not buttons(done),
          done and buttons(done))
    c2 = await submit("解封后可以再投稿", 2)
    check("unbanned submitter can submit again", c2)

    # 4. /ban 回复已发布的投稿：那条控制消息也显示“解除封禁”
    n = len(log); lt.cb("r:pub_ok:2:0", REVIEW, ADMIN, message_id=c2["result"]["message_id"])
    await wait_for(lambda e: is_send(e, "sendMessage", lt.CHANNEL, "解封后可以再投稿"), since=n)
    ctrl2 = c2["result"]["message_id"]
    n = len(log); gm("/ban 广告", reply_to=ctrl2)
    await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, "已封禁"), since=n)
    shown = await ctrl_edit(ctrl2, n)
    check("/ban replying to a published submission → its control message shows 🔓 Unban",
          shown and buttons(shown) == {"🔓 解除封禁": "r:unban:2:0"}, shown and buttons(shown))

    # 5. /unban 用 ID 解封：控制消息上的按钮成了旧的；点它只提示“没有被封禁”并收起，不出确认面板、不再通知
    n = len(log); gm(f"/unban {USER}")
    await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, "已解除封禁"), since=n)
    n = len(log); lt.cb("r:unban:2:0", REVIEW, ADMIN, message_id=ctrl2)
    t = await toast(n, "没有被封禁")
    gone = await ctrl_edit(ctrl2, n)
    told = await wait_for(lambda e: is_send(e, "sendMessage", USER, "投稿权限已恢复"), timeout=0.5, since=n)
    check("stale Unban button → “not banned” alert, button removed, no confirm panel, no second notice",
          t and t["params"].get("show_alert") and gone and not buttons(gone) and not told,
          gone and buttons(gone))

    # 6. /unban 回复控制消息解封：那条控制消息上的按钮立即收起
    n = len(log); gm("/ban", reply_to=ctrl2)
    await ctrl_edit(ctrl2, n)
    n = len(log); gm("/unban", reply_to=ctrl2)
    await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, "已解除封禁"), since=n)
    gone = await ctrl_edit(ctrl2, n)
    check("/unban replying to the control message → its Unban button removed at once", gone and not buttons(gone),
          gone and buttons(gone))


if __name__ == "__main__":
    asyncio.run(lt.main(scenario))
