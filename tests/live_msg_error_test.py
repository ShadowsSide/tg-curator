"""/msg 送不出去时，回复里带的 Telegram 错误原文要转义：原文里有 < > 时消息按 HTML 解析会出错、整条发不出去。

用法（项目根目录下）：python tests/live_msg_error_test.py
复用 live_test.py 的模拟 Bot API 服务器，按需注入失败。
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import live_test as lt  # noqa: E402
from live_test import REVIEW, USER, check, gm, is_send, log, wait_for  # noqa: E402

ERROR = "Bad Request: can't parse <tag>"


def escaped(e):
    text = e and e["params"]["text"]
    return text and "&lt;tag&gt;" in text and "<tag>" not in text


async def scenario():
    await wait_for(lambda e: e["method"] == "setMyCommands", 15, since=0)
    n = len(log); user_msg = lt.pm("错误转义测试")
    await wait_for(lambda e: any(is_send(e, "sendMessage", USER, p) for p in lt.PROMPTS), since=n)
    lt.cb("u:sign:1", USER, USER)
    ctrl = await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, lt.CTRL), since=n)

    # 审核员 → 投稿人：送不到
    lt.MOCK["fail"][f"sendMessage:{USER}"] = [ERROR]
    n = len(log); gm("/msg 你好", reply_to=ctrl["result"]["message_id"])
    e = await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, "没能送达"), since=n)
    check("reviewer /msg undelivered → error text escaped", escaped(e), e and e["params"]["text"])

    # 投稿人 → 审核员：发不进审核群（回复的是投稿人自己的原消息）
    own = {"message_id": user_msg, "date": lt.now(), "chat": lt.chat(USER)}
    lt.MOCK["fail"][f"sendMessage:{REVIEW}"] = [ERROR]
    n = len(log); lt.pm("/msg 补充一下", reply_to_message=own)
    e = await wait_for(lambda e: is_send(e, "sendMessage", USER, "发送失败"), since=n)
    check("submitter /msg failed → error text escaped", escaped(e), e and e["params"]["text"])
    await asyncio.sleep(0.2)


if __name__ == "__main__":
    asyncio.run(lt.main(scenario, {"REMINDER_INTERVAL_MINUTES": "0"}))
