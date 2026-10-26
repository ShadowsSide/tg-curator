"""拒绝理由模板测试：自定义 REJECT_TEMPLATES，并关闭二次确认（CONFIRM_ACTIONS=false）。

用法（项目根目录下）：python tests/live_reject_test.py
默认理由 + 二次确认的组合由 live_confirm_test.py 覆盖。复用 live_test.py 的模拟 Bot API 服务器。约 8 秒。
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import live_test as lt  # noqa: E402
from live_test import ADMIN, CTRL, REVIEW, USER, check, is_send, log, wait_for  # noqa: E402


async def submit(text, sid):
    n = len(log); lt.pm(text)
    await wait_for(lambda e: is_send(e, "sendMessage", USER, "请选择投稿方式"), since=n)
    n = len(log); lt.cb(f"u:sign:{sid}", USER, USER)
    return await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, CTRL), since=n)


def buttons(e):
    kb = (e["params"].get("reply_markup") or {}).get("inline_keyboard", [])
    return {b["text"]: b["callback_data"] for row in kb for b in row}


async def scenario():
    await wait_for(lambda e: e["method"] == "setMyCommands", 15, since=0)
    c1 = await submit("理由测试 1", 1)
    await submit("理由测试 2", 2)

    # 1. 自定义理由出现在面板上
    n = len(log); lt.cb("r:reject:1:0", REVIEW, ADMIN)
    kb = await wait_for(lambda e: e["method"] == "editMessageReplyMarkup", since=n)
    check("custom REJECT_TEMPLATES shown on the reason panel",
          kb and buttons(kb) == {"图片模糊": "r:reason:1:1", "已有类似内容": "r:reason:1:2",
                                 "不附理由": "r:reason:1:0", "« 返回": "r:back:1:0"}, kb and buttons(kb))

    # 2. 不要确认：选了理由直接拒绝（两次点击），理由发给投稿人
    n = len(log); lt.cb("r:reason:1:2", REVIEW, ADMIN)
    told = await wait_for(lambda e: is_send(e, "sendMessage", USER, "已有类似内容"), since=n)
    confirm = [e for e in log[n:] if e["method"] == "editMessageReplyMarkup"]
    toast = await wait_for(lambda e: e["method"] == "answerCallbackQuery" and "已有类似内容" in e["params"].get("text", ""),
                           since=n)
    check("CONFIRM_ACTIONS=false: picking a reason rejects right away with that reason",
          told and not confirm and toast, told and told["params"]["text"])

    # 3. 理由序号超出范围（比如改少了理由后点旧按钮）：照样拒绝，不附理由，不报错
    n = len(log); lt.cb("r:reason:2:9", REVIEW, ADMIN)
    told = await wait_for(lambda e: is_send(e, "sendMessage", USER, "未通过"), since=n)
    check("out-of-range reason index → rejected without a reason", told and "理由" not in told["params"]["text"],
          told and told["params"]["text"])

    # 4. /no 自定义理由照常可用
    c3 = await submit("理由测试 3", 3)
    n = len(log); lt.gm("/no 我自己写的理由", reply_to=c3["result"]["message_id"])
    told = await wait_for(lambda e: is_send(e, "sendMessage", USER, "我自己写的理由"), since=n)
    check("/no with a custom reason still works", told)


if __name__ == "__main__":
    asyncio.run(lt.main(scenario, {"REJECT_TEMPLATES": "图片模糊|已有类似内容", "CONFIRM_ACTIONS": "false",
                                   "REMINDER_INTERVAL_MINUTES": "0"}))
