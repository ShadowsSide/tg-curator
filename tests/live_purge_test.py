"""封禁后删除 TA 在审核群的稿件（🗑）：
- 控制消息：封禁后出现 🗑，要二次确认；确认后删除 TA 全部投稿（含已发布）在审核群的预览和控制消息，别人的不动
- /user 卡片：被封禁且还有稿件时显示 🗑（带条数），删完后按钮消失；删除失败提示可重试，重试成功
- 旧按钮：解封后点控制消息或卡片上的 🗑，只提示“没有被封禁”，不删除

用法（项目根目录下）：python tests/live_purge_test.py
复用 live_test.py 的模拟 Bot API 服务器。约 15 秒。
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import live_test as lt  # noqa: E402
from live_test import ADMIN, BOB, REVIEW, USER, buttons, check, gm, is_send, log, submit, wait_for  # noqa: E402

PURGE_BTN = "🗑 删除 TA 的稿件"
CONFIRM = "🗑 确认删除（审核群里 TA 的全部稿件，不可恢复）"


def edited(message_id, since):
    return wait_for(lambda e: e["method"] in ("editMessageText", "editMessageReplyMarkup")
                    and str(e["params"].get("message_id")) == str(message_id), since=since)


def toast(since, contains):
    return wait_for(lambda e: e["method"] == "answerCallbackQuery" and contains in e["params"].get("text", ""),
                    since=since)


def review_ids(marker):
    """审核群里含 marker 的消息（预览）的编号；控制消息不含稿件内容，另外取。"""
    return {e["result"]["message_id"] for e in log
            if not e.get("error") and is_send(e, "sendMessage", REVIEW, marker) and e.get("result")}


def deletes(since):
    return [e for e in log[since:] if e["method"] == "deleteMessages" and str(e["params"].get("chat_id")) == str(REVIEW)]


def deleted_ids(since):
    return {int(m) for e in deletes(since) if not e.get("error") for m in e["params"]["message_ids"]}


async def card(uid):
    n = len(log); gm(f"/user {uid}")
    return await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, f"<code>{uid}</code>"), since=n)


async def scenario():
    await wait_for(lambda e: e["method"] == "setMyCommands", 15, since=0)

    # 准备：Alice 一条已发布、一条待审核；Bob 一条待审核
    c1 = await submit("删稿一 已发布", 1)
    n = len(log); lt.cb("r:pub_ok:1:0", REVIEW, ADMIN, message_id=c1["result"]["message_id"])
    await wait_for(lambda e: is_send(e, "sendMessage", lt.CHANNEL, "删稿一"), since=n)
    c2 = await submit("删稿二 待审核", 2)
    c3 = await submit("别人的稿件", 3, who=BOB)
    ctrl2, ctrl3 = c2["result"]["message_id"], c3["result"]["message_id"]
    alice_ids = review_ids("删稿一") | review_ids("删稿二") | {c1["result"]["message_id"], ctrl2}  # 预览 + 控制消息
    bob_ids = review_ids("别人的稿件") | {ctrl3}
    check("setup: previews + control messages recorded", len(alice_ids) == 4 and len(bob_ids) == 2, (alice_ids, bob_ids))

    # 1. 控制消息上封禁 → 出现 🔓 和 🗑
    n = len(log); lt.cb("r:ban_ok:2:0", REVIEW, ADMIN, message_id=ctrl2)
    banned = await edited(ctrl2, n)
    check("ban → control message shows 🔓 + 🗑", banned and buttons(banned).get(PURGE_BTN) == "r:purge:2:0",
          banned and buttons(banned))

    # 2. 点 🗑 先确认；返回不删
    n = len(log); lt.cb("r:purge:2:0", REVIEW, ADMIN, message_id=ctrl2)
    panel = await edited(ctrl2, n)
    check("🗑 → confirm panel", panel and buttons(panel).get(CONFIRM) == "r:purge_ok:2:0", panel and buttons(panel))
    n = len(log); lt.cb("r:back:2:0", REVIEW, ADMIN, message_id=ctrl2)
    back = await edited(ctrl2, n)
    check("Back → nothing deleted", back and PURGE_BTN in buttons(back) and not deletes(n))

    # 3. 确认：删除 Alice 全部投稿（含已发布）在审核群的消息，Bob 的不动
    n = len(log); lt.cb("r:purge_ok:2:0", REVIEW, ADMIN, message_id=ctrl2)
    t = await toast(n, "已删除 TA 在审核群的 2 条稿件")
    gone = deleted_ids(n)
    check("confirm → all of Alice's review messages deleted (published one too), Bob's kept",
          t and t["params"].get("show_alert") and alice_ids <= gone and not gone & bob_ids, (gone, alice_ids, bob_ids))
    c = await card(USER)
    check("/user after deleting → no 🗑 left (only 🔓)", c and buttons(c) == {"🔓 解除封禁": f"au:unban:{USER}"},
          c and buttons(c))

    # 4. 旧按钮：Bob 封禁后解封，再点控制消息上的 🗑 → 只提示没有被封禁
    n = len(log); lt.cb("r:ban_ok:3:0", REVIEW, ADMIN, message_id=ctrl3)
    await edited(ctrl3, n)
    n = len(log); gm(f"/unban {BOB}")
    await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, "已解除封禁"), since=n)
    n = len(log); lt.cb("r:purge:3:0", REVIEW, ADMIN, message_id=ctrl3)
    t = await toast(n, "没有被封禁")
    collapsed = await edited(ctrl3, n)
    check("stale 🗑 on control message after unban → “not banned”, button removed, nothing deleted",
          t and t["params"].get("show_alert") and collapsed and PURGE_BTN not in buttons(collapsed) and not deletes(n),
          collapsed and buttons(collapsed))

    # 5. 卡片：Bob 再封禁 → 卡片有 🗑（1 条）
    n = len(log); gm(f"/ban {BOB}")
    await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, "已封禁"), since=n)
    c = await card(BOB)
    cid = c["result"]["message_id"]
    purge_n = "🗑 删除 TA 在审核群的稿件（1 条）"
    check("/user of a banned user with posts → 🗑 with count", c and buttons(c).get(purge_n) == f"au:purge:{BOB}",
          c and buttons(c))

    # 6. 卡片上删除：先确认；第一次删除失败 → 提示可重试，按钮还在
    n = len(log); lt.cb(f"au:purge:{BOB}", REVIEW, ADMIN, message_id=cid)
    panel = await edited(cid, n)
    check("card 🗑 → confirm panel", panel and buttons(panel) == {CONFIRM: f"au:purge_ok:{BOB}", "« 返回": f"au:back:{BOB}"},
          panel and buttons(panel))
    lt.MOCK["fail"][f"deleteMessages:{REVIEW}"] = ["Bad Request: message can't be deleted"]
    n = len(log); lt.cb(f"au:purge_ok:{BOB}", REVIEW, ADMIN, message_id=cid)
    t = await toast(n, "删除失败")
    after = await edited(cid, n)
    check("delete fails → alert says retry, card keeps 🗑",
          t and t["params"].get("show_alert") and after and buttons(after).get(purge_n) == f"au:purge:{BOB}",
          after and buttons(after))

    # 7. 重试成功：Bob 的消息删掉，卡片上 🗑 消失
    n = len(log); lt.cb(f"au:purge_ok:{BOB}", REVIEW, ADMIN, message_id=cid)
    t = await toast(n, "已删除 TA 在审核群的 1 条稿件")
    after = await edited(cid, n)
    check("retry → Bob's messages deleted, 🗑 gone from the card",
          t and bob_ids <= deleted_ids(n) and after and buttons(after) == {"🔓 解除封禁": f"au:unban:{BOB}"},
          after and buttons(after))

    # 8. 卡片上的旧 🗑：解封后再点 → 提示没有被封禁，卡片刷新成 🚫 封禁，不删
    n = len(log); lt.cb(f"au:unban_ok:{USER}", REVIEW, ADMIN, message_id=cid)
    await toast(n, "已解除封禁")
    n = len(log); lt.cb(f"au:purge:{USER}", REVIEW, ADMIN, message_id=cid)
    t = await toast(n, "没有被封禁")
    after = await edited(cid, n)
    check("stale card 🗑 after unban → “not banned”, card refreshed, nothing deleted",
          t and t["params"].get("show_alert") and after and buttons(after) == {"🚫 封禁": f"au:ban:{USER}"}
          and not deletes(n), after and buttons(after))


if __name__ == "__main__":
    asyncio.run(lt.main(scenario))
