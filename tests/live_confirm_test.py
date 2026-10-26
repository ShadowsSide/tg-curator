"""二次确认测试（CONFIRM_ACTIONS，默认开启）：立即发布、拒绝、封禁要再点一次确认才执行。

用法（项目根目录下）：python tests/live_confirm_test.py
复用 live_test.py 的模拟 Bot API 服务器。约 10 秒。
"""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import live_test as lt  # noqa: E402
from live_test import ADMIN, CHANNEL, CTRL, REVIEW, USER, check, is_send, log, wait_for  # noqa: E402


async def submit(text, sid):
    n = len(log); lt.pm(text)
    await wait_for(lambda e: is_send(e, "sendMessage", USER, "请选择投稿方式"), since=n)
    n = len(log); lt.cb(f"u:sign:{sid}", USER, USER)
    return await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, CTRL), since=n)


def buttons(e):
    kb = (e["params"].get("reply_markup") or {}).get("inline_keyboard", [])
    return {b["text"]: b["callback_data"] for row in kb for b in row}


def markup_edit(ctrl, since):
    mid = str(ctrl["result"]["message_id"])
    return wait_for(lambda e: e["method"] == "editMessageReplyMarkup" and str(e["params"].get("message_id")) == mid,
                    since=since)


async def scenario():
    await wait_for(lambda e: e["method"] == "setMyCommands", 15, since=0)
    c1, c2, c3 = [await submit(f"确认测试 {i}", i) for i in (1, 2, 3)]

    # 1. 点“立即发布”：只换成确认面板，不发布
    n = len(log); lt.cb("r:pub:1:0", REVIEW, ADMIN)
    kb = await markup_edit(c1, n)
    toast = await wait_for(lambda e: e["method"] == "answerCallbackQuery" and "确认" in e["params"].get("text", ""), since=n)
    posted = await wait_for(lambda e: is_send(e, "sendMessage", CHANNEL), timeout=1.5, since=n)
    check("Publish → confirm panel (Confirm / Back), nothing published yet",
          kb and buttons(kb) == {"✅ 确认发布": "r:pub_ok:1:0", "« 返回": "r:back:1:0"} and toast and not posted,
          kb and buttons(kb))

    # 1b. 连点两下：第二下按钮没变（Telegram 报 not modified），不报错，按钮也不会一直转圈
    n = len(log); lt.cb("r:pub:1:0", REVIEW, ADMIN)
    dup = await wait_for(lambda e: e["method"] == "editMessageReplyMarkup" and e.get("error"), since=n)
    answered = await wait_for(lambda e: e["method"] == "answerCallbackQuery", since=n)
    check("double tap on Publish → 'not modified' swallowed, tap still answered", dup and answered)

    # 2. 点“返回”：恢复原来的按钮，仍然没有发布
    n = len(log); lt.cb("r:back:1:0", REVIEW, ADMIN)
    back = await wait_for(lambda e: e["method"] == "editMessageText"
                          and str(e["params"].get("message_id")) == str(c1["result"]["message_id"]), since=n)
    posted = await wait_for(lambda e: is_send(e, "sendMessage", CHANNEL), timeout=1, since=n)
    check("Back → original buttons restored, still not published",
          back and "✅ 立即发布" in buttons(back) and not posted, back and list(buttons(back)))

    # 3. 再点“立即发布”→“确认发布”：发布到频道
    n = len(log); lt.cb("r:pub:1:0", REVIEW, ADMIN)
    await markup_edit(c1, n)
    n = len(log); lt.cb("r:pub_ok:1:0", REVIEW, ADMIN)
    post = await wait_for(lambda e: is_send(e, "sendMessage", CHANNEL, "确认测试 1"), since=n)
    check("Confirm publish → published to the channel", post)

    # 4. 拒绝：第一下只出确认面板，确认后才拒绝并通知投稿人
    n = len(log); lt.cb("r:reject:2:0", REVIEW, ADMIN)
    kb = await markup_edit(c2, n)
    told = await wait_for(lambda e: is_send(e, "sendMessage", USER, "未通过"), timeout=1, since=n)
    check("Reject → confirm panel, submitter not told yet",
          kb and buttons(kb).get("❌ 确认拒绝") == "r:reject_ok:2:0" and not told, kb and buttons(kb))
    n = len(log); lt.cb("r:reject_ok:2:0", REVIEW, ADMIN)
    told = await wait_for(lambda e: is_send(e, "sendMessage", USER, "未通过"), since=n)
    check("Confirm reject → rejected, submitter notified", told)

    # 5. 封禁：第一下只出确认面板，确认后才封禁（并拒绝其未处理来稿）
    n = len(log); lt.cb("r:ban:3:0", REVIEW, ADMIN)
    kb = await markup_edit(c3, n)
    banned = await wait_for(lambda e: is_send(e, "sendMessage", USER, "禁止投稿"), timeout=1, since=n)
    check("Ban → confirm panel, nobody banned yet",
          kb and any(v == "r:ban_ok:3:0" for v in buttons(kb).values()) and not banned, kb and buttons(kb))
    n = len(log); lt.cb("r:ban_ok:3:0", REVIEW, ADMIN)
    banned = await wait_for(lambda e: is_send(e, "sendMessage", USER, "禁止投稿"), since=n)
    check("Confirm ban → submitter banned", banned)

    # 6. 已经处理过的稿件再点“确认”：不会重复执行
    n = len(log); lt.cb("r:pub_ok:1:0", REVIEW, ADMIN)
    await asyncio.sleep(1)
    again = [e for e in log[n:] if is_send(e, "sendMessage", CHANNEL)]
    check("Confirm on an already-published submission → nothing published twice", not again)

    # 7. 定时发布不需要确认：点“定时发布”直接出时间面板，选了时间直接定时
    n = len(log); lt.pm("确认测试 5", who=lt.BOB)
    await wait_for(lambda e: is_send(e, "sendMessage", lt.BOB), since=n)
    n = len(log); lt.cb("u:sign:4", lt.BOB, lt.BOB)
    c4 = await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, CTRL), since=n)
    n = len(log); lt.cb("r:sched:4:0", REVIEW, ADMIN)
    kb = await markup_edit(c4, n)
    preset = next((v for v in buttons(kb).values() if v.startswith("r:preset:")), None) if kb else None
    n = len(log); lt.cb(preset or "r:preset:4:0", REVIEW, ADMIN)
    told = await wait_for(lambda e: is_send(e, "sendMessage", lt.BOB), since=n)
    check("Schedule needs no confirmation: picker → preset → scheduled", preset and told, kb and list(buttons(kb)))

    texts = json.dumps([e["params"] for e in log if e["method"] == "editMessageReplyMarkup"], ensure_ascii=False)
    check("confirm buttons never show a submission number", "#" not in texts)


if __name__ == "__main__":
    asyncio.run(lt.main(scenario, {"REMINDER_INTERVAL_MINUTES": "0"}))
