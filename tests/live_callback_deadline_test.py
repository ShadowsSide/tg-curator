"""按钮回应的时限：Telegram 只给按钮几秒钟回应，超时后 answerCallbackQuery 报 “query is too old”。
模拟服务器同样执行时限（测试里调成 2 秒），并且同一个按钮只能回应一次；兜底（CALLBACK_FALLBACK_SECONDS）调成 1 秒。
- 很快处理完的按钮：照常显示自己的提示，没有“处理中…”
- 确认封禁时被限流（刷新控制按钮消息要等 3 秒）：兜底先回应“处理中…”，之后的普通提示丢掉，不出“出错了”
  （控制按钮消息上的封禁和 /user 卡片上的封禁两处）
- 处理得慢、最后要弹窗的（解封一个没被封禁的人）：兜底回应之后，弹窗改成回复控制按钮消息
- 兜底的回应自己被限流：不等、不重试，只记日志；处理照常完成

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
FALLBACK = 1  # 秒
FLOOD = 3  # 秒：比时限长，等完再回应就来不及了
ERROR = "出错了"
WORKING = "处理中"


def answers(since):
    return [e for e in log[since:] if e["method"] == "answerCallbackQuery"]


def told_error(since):
    return [e for e in log[since:] if not e.get("error") and ERROR in str(e["params"].get("text", ""))]


def control_edited(ctrl, since):
    return wait_for(lambda e: e["method"] == "editMessageText" and not e.get("error")
                    and str(e["params"].get("message_id")) == str(ctrl), FLOOD + 4, since=since)


async def scenario():
    await wait_for(lambda e: e["method"] == "setMyCommands", 15, since=0)
    lt.MOCK["callback_deadline"] = DEADLINE

    # 1. 很快处理完：照常显示自己的提示
    ctrl = (await submit("封禁时被限流", 1))["result"]["message_id"]
    n = len(log); lt.cb("r:spoiler:1:0", REVIEW, ADMIN, message_id=ctrl)
    a = await wait_for(lambda e: e["method"] == "answerCallbackQuery", since=n)
    await asyncio.sleep(FALLBACK + 0.5)
    check("fast button → its own toast, answered once, no “working on it”",
          a and not a.get("error") and "剧透" in a["params"].get("text", "") and len(answers(n)) == 1,
          [e["params"] for e in answers(n)])

    # 2. 兜底的回应自己被限流：不等不重试，处理照常完成
    lt.MOCK["flood"][f"editMessageText:{REVIEW}"] = [FLOOD]
    lt.MOCK["flood"]["answerCallbackQuery:None"] = [30]
    n = len(log); lt.cb("r:silent:1:0", REVIEW, ADMIN, message_id=ctrl)
    done = await control_edited(ctrl, n)
    await asyncio.sleep(0.5)
    check("fallback answer rate limited → no waiting or retrying, the action still completes",
          done and len(answers(n)) == 1 and answers(n)[0].get("flood") and not told_error(n),
          [(e["params"].get("text"), e.get("flood")) for e in answers(n)])


    # 3. 控制按钮消息上确认封禁：刷新控制按钮消息时被限流
    lt.MOCK["flood"][f"editMessageText:{REVIEW}"] = [FLOOD]
    n = len(log); lt.cb("r:ban_ok:1:0", REVIEW, ADMIN, message_id=ctrl)
    await control_edited(ctrl, n)
    await asyncio.sleep(0.5)
    ok = [e for e in answers(n) if not e.get("error")]
    check("ban on the control panel while rate limited → answered in time with “working on it”, once",
          len(answers(n)) == 1 and ok and WORKING in ok[0]["params"].get("text", ""),
          [(e["params"].get("text"), e.get("error")) for e in answers(n)])
    check("… the later “banned” toast is dropped, no “something went wrong”",
          not told_error(n) and not [e for e in log[n:] if is_send(e, "sendMessage", REVIEW, "已封禁")],
          [e["params"].get("text") for e in told_error(n)])

    # 4. 解封一个没被封禁的人（Bob 的稿件，按钮是旧的）：慢，最后是弹窗 → 改成回复控制按钮消息
    ctrl3 = (await submit("旧的解封按钮", 2, who=BOB))["result"]["message_id"]
    lt.MOCK["flood"][f"editMessageText:{REVIEW}"] = [FLOOD]
    n = len(log); lt.cb("r:unban_ok:2:0", REVIEW, ADMIN, message_id=ctrl3)
    told = await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, "没有被封禁"), FLOOD + 4, since=n)
    check("slow button ending in an alert → answered with “working on it”, the alert becomes a reply",
          told and str((told["params"].get("reply_parameters") or {}).get("message_id")) == str(ctrl3)
          and len(answers(n)) == 1 and WORKING in answers(n)[0]["params"].get("text", ""),
          told and told["params"])

    # 5. /user 卡片上确认封禁：同样被限流
    n = len(log); lt.gm(f"/user {BOB}")
    card = await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, f"<code>{BOB}</code>"), since=n)
    cid = card and card["result"]["message_id"]
    lt.MOCK["flood"][f"editMessageText:{REVIEW}"] = [FLOOD]
    n = len(log); lt.cb(f"au:ban_ok:{BOB}", REVIEW, ADMIN, message_id=cid)
    await control_edited(cid, n)  # 刷新卡片在最后
    await asyncio.sleep(0.5)
    ok = [e for e in answers(n) if not e.get("error")]
    check("ban on the /user card while rate limited → answered in time with “working on it”, once",
          len(answers(n)) == 1 and ok and WORKING in ok[0]["params"].get("text", ""),
          [(e["params"].get("text"), e.get("error")) for e in answers(n)])
    check("… no “something went wrong”", not told_error(n), [e["params"].get("text") for e in told_error(n)])


if __name__ == "__main__":
    asyncio.run(lt.main(scenario, {"CALLBACK_FALLBACK_SECONDS": str(FALLBACK)}))
