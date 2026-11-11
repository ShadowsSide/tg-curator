"""按钮回应的时限：Telegram 只给按钮几秒钟回应，超时后 answerCallbackQuery 报 “query is too old”。
模拟服务器同样执行时限（测试里调成 2 秒），并且同一个按钮只能回应一次。
- 确认封禁时被限流（刷新控制按钮消息要等 3 秒）：按钮仍然在时限内回应，不出“出错了”
  （控制按钮消息上的封禁和 /user 卡片上的封禁两处）

用法（项目根目录下）：python tests/live_callback_deadline_test.py
复用 live_test.py 的模拟 Bot API 服务器。
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import live_test as lt  # noqa: E402
from live_test import ADMIN, BOB, REVIEW, check, is_send, log, submit, wait_for  # noqa: E402

DEADLINE = 2  # 秒
FLOOD = 3  # 秒：比时限长，等完再回应就来不及了
ERROR = "出错了"


def answered(since):
    """since 之后按钮的回应：成功的那次（没有就是 None）。"""
    return wait_for(lambda e: e["method"] == "answerCallbackQuery" and not e.get("error"), FLOOD + 4, since=since)


def told_error(since):
    return [e for e in log[since:] if not e.get("error") and ERROR in str(e["params"].get("text", ""))]


async def scenario():
    await wait_for(lambda e: e["method"] == "setMyCommands", 15, since=0)
    lt.MOCK["callback_deadline"] = DEADLINE

    # 1. 控制按钮消息上确认封禁：刷新控制按钮消息时被限流
    ctrl = (await submit("封禁时被限流", 1))["result"]["message_id"]
    lt.MOCK["flood"][f"editMessageText:{REVIEW}"] = [FLOOD]
    n = len(log); lt.cb("r:ban_ok:1:0", REVIEW, ADMIN, message_id=ctrl)
    a = await answered(n)
    await wait_for(lambda e: e["method"] == "editMessageText" and not e.get("error")
                   and str(e["params"].get("message_id")) == str(ctrl), FLOOD + 4, since=n)
    await asyncio.sleep(0.5)
    check("ban on the control panel while rate limited → the button is still answered in time", a,
          [(e["method"], e.get("error")) for e in log[n:] if e["method"] == "answerCallbackQuery"])
    check("ban on the control panel while rate limited → no “something went wrong”", not told_error(n),
          [e["params"].get("text") for e in told_error(n)])

    # 2. /user 卡片上确认封禁：同样被限流
    await submit("卡片封禁时被限流", 2, who=BOB)
    n = len(log); lt.gm(f"/user {BOB}")
    card = await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, f"<code>{BOB}</code>"), since=n)
    lt.MOCK["flood"][f"editMessageText:{REVIEW}"] = [FLOOD]
    n = len(log); lt.cb(f"au:ban_ok:{BOB}", REVIEW, ADMIN, message_id=card and card["result"]["message_id"])
    a = await answered(n)
    await asyncio.sleep(FLOOD + 1)
    check("ban on the /user card while rate limited → the button is still answered in time", a,
          [(e["method"], e.get("error")) for e in log[n:] if e["method"] == "answerCallbackQuery"])
    check("ban on the /user card while rate limited → no “something went wrong”", not told_error(n),
          [e["params"].get("text") for e in told_error(n)])


if __name__ == "__main__":
    asyncio.run(lt.main(scenario))
