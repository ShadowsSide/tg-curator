"""内容版本：审核员点“发布”之后稿件又被改过，确认时不发布；两次修改同时进行时，后保存的不会盖掉先保存的。

用法（项目根目录下）：python tests/live_version_test.py
复用 live_test.py 的模拟 Bot API 服务器。
"""
import asyncio
import json
import os
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import live_test as lt  # noqa: E402
from live_test import ADMIN, CHANNEL, CTRL, REVIEW, USER, check, is_send, log, pm, wait_for  # noqa: E402

DB = os.path.join(tempfile.mkdtemp(), "bot.db")


def text_of(sid):
    with sqlite3.connect(DB) as conn:
        return json.loads(conn.execute("SELECT items FROM submissions WHERE id=?", (sid,)).fetchone()[0])[0]["text"]


def buttons(e):
    kb = (e["params"].get("reply_markup") or {}).get("inline_keyboard", [])
    return [b.get("callback_data") for row in kb for b in row]


async def submit(text, sid):
    """返回 (投稿人那条消息的编号, 控制按钮消息的编号)。"""
    n = len(log); mid = pm(text)
    await wait_for(lambda e: any(is_send(e, "sendMessage", USER, p) for p in lt.PROMPTS), since=n)
    n = len(log); lt.cb(f"u:sign:{sid}", USER, USER)
    ctrl = await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, CTRL), since=n)
    return mid, ctrl["result"]["message_id"]


async def scenario():
    await wait_for(lambda e: e["method"] == "setMyCommands", 15, since=0)

    # 1. 点了“发布”（确认面板出来了），投稿人这时改了稿件：点“确认”不发布，按钮换成新版本
    mid, ctrl = await submit("审核员看过的原文", 1)
    n = len(log); lt.cb("r:pub:1:0", REVIEW, ADMIN, ctrl)
    await wait_for(lambda e: e["method"] == "editMessageReplyMarkup" and "r:pub_ok:1:0" in buttons(e), since=n)
    n = len(log); lt.pm_edit(mid, "投稿人刚改的新内容")
    await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, "投稿人刚改的新内容"), since=n)
    n = len(log); lt.cb("r:pub_ok:1:0", REVIEW, ADMIN, ctrl)
    told = await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, "又被修改过"), since=n)
    refreshed = await wait_for(lambda e: e["method"] == "editMessageText" and "r:pub:1:1" in buttons(e), since=n)
    check("confirm after the content changed → not published, reviewer told, button carries the new version",
          told and refreshed and not [e for e in log[n:] if is_send(e, "sendMessage", CHANNEL)])
    n = len(log); lt.cb("r:pub_ok:1:1", REVIEW, ADMIN, ctrl)
    check("confirm on the current version → the new content is published",
          await wait_for(lambda e: is_send(e, "sendMessage", CHANNEL, "投稿人刚改的新内容"), since=n))

    # 2. 两次修改同时进行（审核员的预览被限流，投稿人的先保存）：审核员那次不保存，不盖掉投稿人的修改
    mid, ctrl = await submit("第二条原文", 2)
    lt.MOCK["flood"][f"sendMessage:{REVIEW}"] = [2]
    n = len(log); lt.gm("/edit 审核员基于原文的修改", reply_to=ctrl)
    await wait_for(lambda e: e.get("flood") is not None, since=n)
    lt.pm_edit(mid, "投稿人同时做的修改")
    told = await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, "刚刚被别人修改过"), timeout=10, since=n)
    check("two edits at once → the later one based on old content is rejected, the first is kept",
          told and text_of(2) == "投稿人同时做的修改", text_of(2))


if __name__ == "__main__":
    asyncio.run(lt.main(scenario, {"DB_PATH": DB, "REMINDER_INTERVAL_MINUTES": "0"}))
