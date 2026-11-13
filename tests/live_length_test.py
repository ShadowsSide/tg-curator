"""落款也占长度：加上落款后超过 Telegram 限制的稿件，要在提交 / 修改时就告诉对方，不能等发送失败。

用法（项目根目录下）：python tests/live_length_test.py
复用 live_test.py 的模拟 Bot API 服务器（它和 Telegram 一样限制长度）。
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import live_test as lt  # noqa: E402
from live_test import CTRL, REVIEW, USER, check, is_send, log, pm, wait_for  # noqa: E402

SIGNED = "\n\nvia Alice"
ANON = "\n\nvia 匿名"
TOO_LONG = "内容太长"


def reviewed(since):
    return [e for e in log[since:] if is_send(e, "sendMessage", REVIEW, CTRL)]


async def draft(**kw):
    n = len(log); mid = pm(**kw)
    await wait_for(lambda e: any(is_send(e, "sendMessage", USER, p) for p in lt.PROMPTS), since=n)
    return mid


def press(data):
    return lt.press(data, USER, USER)


async def scenario():
    await wait_for(lambda e: e["method"] == "setMyCommands", 15, since=0)

    # 文字：署名放不下，匿名刚好放得下
    await draft(text="x" * (4096 - len(ANON)))
    n, answer = await press("u:sign:1")
    await asyncio.sleep(0.5)
    check("text + signature over 4096 → told at once, nothing sent to review",
          answer and TOO_LONG in answer["params"].get("text", "") and not reviewed(n), answer and answer["params"])
    n = len(log); lt.cb("u:anon:1", USER, USER)
    check("draft is kept: the shorter anonymous signature fits exactly",
          await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, CTRL), since=n))

    # 说明文字：上限 1024，改短后可以重新提交
    photo = [{"file_id": "p", "file_unique_id": "u", "width": 1, "height": 1}]
    mid = await draft(caption="c" * 1020, photo=photo)
    n, answer = await press("u:sign:2")
    await asyncio.sleep(0.5)
    check("caption + signature over 1024 → told at once, nothing sent to review",
          answer and TOO_LONG in answer["params"].get("text", "") and not reviewed(n), answer and answer["params"])
    n = len(log)
    lt.push(edited_message={"message_id": mid, "date": lt.now() - 5, "edit_date": lt.now(), "chat": lt.chat(USER),
                            "from": {"id": USER, "is_bot": False, "first_name": "Alice", "username": "alice"},
                            "caption": "c" * (1024 - len(SIGNED)), "photo": photo})
    await wait_for(lambda e: is_send(e, "sendMessage", USER), since=n)
    n = len(log); lt.cb("u:sign:2", USER, USER)
    ctrl = await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, CTRL), since=n)
    check("shortened to fit exactly → accepted", ctrl)

    # 审核员修改：同样要留出落款，超出时不保存、不发预览
    ctrl_id = ctrl["result"]["message_id"]
    n = len(log); lt.gm("/edit " + "e" * 1020, reply_to=ctrl_id)
    err = await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, TOO_LONG), since=n)
    await asyncio.sleep(0.3)
    check("reviewer edit over the limit → rejected, no new preview",
          err and not [e for e in log[n:] if e["method"] == "sendPhoto"])
    n = len(log); lt.gm("/edit " + "e" * (1024 - len(SIGNED)), reply_to=ctrl_id)
    check("reviewer edit that fits exactly → preview sent",
          await wait_for(lambda e: is_send(e, "sendPhoto", REVIEW, "via Alice"), since=n))

    # 发布：刚好在上限内的稿件能发到频道
    n = len(log); lt.cb(await lt.pub_ok(2), REVIEW, lt.ADMIN, ctrl_id)
    check("fits exactly → published", await wait_for(lambda e: is_send(e, "sendPhoto", lt.CHANNEL), since=n))


if __name__ == "__main__":
    asyncio.run(lt.main(scenario, {"REMINDER_INTERVAL_MINUTES": "0"}))
