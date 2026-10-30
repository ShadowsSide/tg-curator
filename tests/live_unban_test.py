"""封禁 / 解封按钮：
- 控制消息：封禁后显示 🔓 解除封禁，要二次确认；解封后通知投稿人、收起按钮。
  用 /unban 解封后，别的控制消息上留下的旧按钮点了只提示“没有被封禁”并收起，不出确认面板。
- /user 卡片：按当前状态显示 🚫 封禁 或 🔓 解除封禁，都要确认，执行后卡片原地刷新；
  状态已经被别人改了就只刷新卡片；没投过稿的人也能预先封禁；非审核员点不了。

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

    # 7. /user 卡片：没被封禁 → 🚫 封禁
    c3 = await submit("卡片封禁会拒绝这条", 3)
    n = len(log); gm(f"/user {USER}")
    card = await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, f"<code>{USER}</code>"), since=n)
    card_id = card["result"]["message_id"]
    check("/user → card with 🚫 Ban", card and buttons(card) == {"🚫 封禁": f"au:ban:{USER}"}, card and buttons(card))

    # 8. 点“封禁”先确认；返回不封禁
    n = len(log); lt.cb(f"au:ban:{USER}", REVIEW, ADMIN, message_id=card_id)
    panel = await ctrl_edit(card_id, n)
    check("card Ban → confirm panel", panel and buttons(panel) == {
        "🚫 确认封禁（同时拒绝其所有未处理来稿）": f"au:ban_ok:{USER}", "« 返回": f"au:back:{USER}"},
        panel and buttons(panel))
    n = len(log); lt.cb(f"au:back:{USER}", REVIEW, ADMIN, message_id=card_id)
    back = await ctrl_edit(card_id, n)
    check("card Back → card again, still 🚫 Ban", back and buttons(back) == {"🚫 封禁": f"au:ban:{USER}"},
          back and buttons(back))

    # 9. 确认封禁：卡片显示已封禁和 🔓；通知投稿人；未处理的来稿被拒，控制消息出现 🔓
    n = len(log); lt.cb(f"au:ban_ok:{USER}", REVIEW, ADMIN, message_id=card_id)
    t = await toast(n, "已封禁")
    told = await wait_for(lambda e: is_send(e, "sendMessage", USER, "禁止投稿"), since=n)
    after = await ctrl_edit(card_id, n)
    ctrl3 = await ctrl_edit(c3["result"]["message_id"], n)
    check("card confirm Ban → banned, submitter told, card shows banned + 🔓, open submission rejected with 🔓",
          t and "1" in t["params"]["text"] and told and after and "已封禁" in after["params"].get("text", "")
          and buttons(after) == {"🔓 解除封禁": f"au:unban:{USER}"}
          and ctrl3 and buttons(ctrl3) == {"🔓 解除封禁": "r:unban:3:0"}, after and buttons(after))

    # 10. 非审核员点卡片按钮：没有权限，什么都不变
    n = len(log); lt.cb(f"au:unban_ok:{USER}", REVIEW, 7777, message_id=card_id)
    denied = await toast(n, "没有审核权限")
    told = await wait_for(lambda e: is_send(e, "sendMessage", USER, "投稿权限已恢复"), timeout=0.5, since=n)
    check("non-reviewer taps the card → no permission, nothing changes", denied and not told)

    # 11. 卡片上解封：确认后通知投稿人，卡片回到 🚫 封禁
    n = len(log); lt.cb(f"au:unban:{USER}", REVIEW, ADMIN, message_id=card_id)
    panel = await ctrl_edit(card_id, n)
    n = len(log); lt.cb(f"au:unban_ok:{USER}", REVIEW, ADMIN, message_id=card_id)
    t = await toast(n, "已解除封禁")
    told = await wait_for(lambda e: is_send(e, "sendMessage", USER, "投稿权限已恢复"), since=n)
    after = await ctrl_edit(card_id, n)
    check("card Unban (after confirm) → unbanned, submitter told, card back to 🚫 Ban",
          panel and buttons(panel).get("🔓 确认解封（会通知投稿人）") == f"au:unban_ok:{USER}"
          and t and told and after and buttons(after) == {"🚫 封禁": f"au:ban:{USER}"}, after and buttons(after))

    # 12. 状态被别人改了：/ban 之后再点卡片上的旧“封禁”→ 提示已封禁，卡片刷新成 🔓，不出确认面板、不再通知
    n = len(log); gm(f"/ban {USER}")
    await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, "已封禁"), since=n)
    n = len(log); lt.cb(f"au:ban:{USER}", REVIEW, ADMIN, message_id=card_id)
    t = await toast(n, "已经被封禁")
    after = await ctrl_edit(card_id, n)
    check("stale card Ban → “already banned” alert, card refreshed to 🔓, no confirm panel",
          t and t["params"].get("show_alert") and after and buttons(after) == {"🔓 解除封禁": f"au:unban:{USER}"},
          after and buttons(after))

    # 13. 没投过稿的人：卡片也能预先封禁，封禁后卡片写明已封禁
    stranger = 555
    n = len(log); gm(f"/user {stranger}")
    card = await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, "没有投稿记录"), since=n)
    n = len(log); lt.cb(f"au:ban_ok:{stranger}", REVIEW, ADMIN, message_id=card["result"]["message_id"])
    after = await ctrl_edit(card["result"]["message_id"], n)
    check("no-records user → card can pre-ban; card then says banned",
          buttons(card) == {"🚫 封禁": f"au:ban:{stranger}"} and after and "已封禁" in after["params"]["text"]
          and buttons(after) == {"🔓 解除封禁": f"au:unban:{stranger}"}, after and after["params"])


if __name__ == "__main__":
    asyncio.run(lt.main(scenario))
