"""处理函数里没被处理的异常：点按钮的人收到“出错了”弹窗，发消息的人收到回复，日志照常记录。

用法（项目根目录下）：python tests/live_error_test.py
复用 live_test.py 的模拟 Bot API 服务器，用失败注入制造处理函数里的异常。约 8 秒。
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import live_test as lt  # noqa: E402
from live_test import CTRL, REVIEW, USER, check, is_send, log, pm, wait_for  # noqa: E402

ERROR = "出错了"


async def scenario():
    await wait_for(lambda e: e["method"] == "setMyCommands", 15, since=0)

    # 1. 按钮：提交成功后更新私聊里的提示失败 → 弹窗告诉投稿人，而不是按钮一直转圈
    n = len(log); pm("错误处理测试")
    await wait_for(lambda e: any(is_send(e, "sendMessage", USER, p) for p in lt.PROMPTS), since=n)
    lt.MOCK["fail"][f"editMessageText:{USER}"] = ["Bad Request: message to edit not found"]
    n = len(log); lt.cb("u:sign:1", USER, USER)
    answer = await wait_for(lambda e: e["method"] == "answerCallbackQuery"
                            and ERROR in (e["params"].get("text") or ""), since=n)
    check("button handler raises → alert shown to the person who pressed it",
          answer and answer["params"].get("show_alert"), answer and answer["params"])
    check("the submission itself still went to review",
          [e for e in log[n:] if is_send(e, "sendMessage", REVIEW, CTRL)])

    # 2. 消息：回复失败 → 再回复一条“出错了”
    lt.MOCK["fail"][f"sendMessage:{USER}"] = ["Bad Request: something unexpected"]
    n = len(log); pm("/start")
    check("message handler raises → sender told it didn't go through",
          await wait_for(lambda e: is_send(e, "sendMessage", USER, ERROR), since=n))


if __name__ == "__main__":
    asyncio.run(lt.main(scenario, {"REMINDER_INTERVAL_MINUTES": "0"}, allowed_errors=("处理更新出错",)))
