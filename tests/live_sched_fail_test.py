"""定时发布没有成功时提醒审核员：回复在这条稿件的控制按钮消息下面。
定时发布成功时也静音回复一条，带帖子链接；立即发布、控制按钮消息已经没了的不发。

用法（项目根目录下）：python tests/live_sched_fail_test.py
复用 live_test.py 的模拟 Bot API 服务器。调度每 15 秒一轮，较慢，约 50 秒。
"""
import asyncio
import os
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import live_test as lt  # noqa: E402
from live_test import CHANNEL, REVIEW, check, is_send, log, submit, wait_for  # noqa: E402

DB = os.path.join(tempfile.mkdtemp(), "bot.db")
TICK = 20  # 秒：比调度间隔（15 秒）多一点


def due_now(sid):
    with sqlite3.connect(DB) as conn:
        conn.execute("UPDATE submissions SET status='scheduled', scheduled_at=1 WHERE id=?", (sid,))


def status(sid):
    with sqlite3.connect(DB) as conn:
        return conn.execute("SELECT status FROM submissions WHERE id=?", (sid,)).fetchone()[0]


def replied(ctrl, text):
    mid = ctrl["result"]["message_id"]
    return lambda e: (is_send(e, "sendMessage", REVIEW, text)
                      and (e["params"].get("reply_parameters") or {}).get("message_id") == mid)


def alert_for(ctrl):
    mid = ctrl["result"]["message_id"]
    return lambda e: (is_send(e, "sendMessage", REVIEW, "定时发布没有成功")
                      and (e["params"].get("reply_parameters") or {}).get("message_id") == mid)


async def scenario():
    await wait_for(lambda e: e["method"] == "setMyCommands", 15, since=0)

    # 1. 发布失败：提醒里带着原因（原因里的 < > 已转义，消息照常发出）
    c1 = await submit("定时失败测试", 1)
    lt.MOCK["fail"][f"sendMessage:{CHANNEL}"] = ["Bad Request: <chat> not found"]
    n = len(log); due_now(1)
    alert = await wait_for(alert_for(c1), timeout=TICK, since=n)
    check("scheduled publish fails → reviewers told under the control panel message, with the reason",
          alert and "&lt;chat&gt; not found" in alert["params"]["text"] and status(1) == "failed",
          alert and alert["params"]["text"])

    # 2. 被限流太久、改到稍后发布：同样提醒，告诉新的时间
    c2 = await submit("定时限流测试", 2)
    lt.MOCK["flood"][f"sendMessage:{CHANNEL}"] = [120]
    n = len(log); due_now(2)
    alert = await wait_for(alert_for(c2), timeout=TICK, since=n)
    check("scheduled publish postponed by a long 429 → reviewers told the new time",
          alert and "限流" in alert["params"]["text"] and status(2) == "scheduled", alert and alert["params"]["text"])

    # 3. 发布成功：不提醒失败，静音回复控制按钮消息说成功了，带帖子链接
    c3 = await submit("定时成功测试", 3)
    n = len(log); due_now(3)
    post = await wait_for(lambda e: is_send(e, "sendMessage", CHANNEL, "定时成功测试"), timeout=TICK, since=n)
    ok = await wait_for(replied(c3, "定时发布成功"), since=n)
    url = post and f"/{post['result']['message_id']}\""
    check("scheduled publish succeeds → no failure alert; a silent reply under the control panel message with the post link",
          post and ok and not [e for e in log[n:] if alert_for(c3)(e)]
          and ok["params"].get("disable_notification") in (True, "true") and url in ok["params"]["text"],
          ok and ok["params"])

    # 4. 立即发布：审核员自己点的，不发这条
    c4 = await submit("立即发布测试", 4)
    n = len(log); lt.cb(await lt.pub_ok(4), REVIEW, lt.ADMIN, message_id=c4["result"]["message_id"])
    post = await wait_for(lambda e: is_send(e, "sendMessage", CHANNEL, "立即发布测试"), since=n)
    await asyncio.sleep(1)
    check("publish now → no “scheduled post went out” message",
          post and not [e for e in log[n:] if is_send(e, "sendMessage", REVIEW, "定时发布成功")])

    # 5. 稿件在审核群的消息已经删掉了（控制按钮消息没了）：定时发布照常，不单独发成功消息
    c5 = await submit("没有控制消息", 5)
    with sqlite3.connect(DB) as conn:
        conn.execute("UPDATE submissions SET review_msg_id=NULL WHERE id=5")
    n = len(log); due_now(5)
    post = await wait_for(lambda e: is_send(e, "sendMessage", CHANNEL, "没有控制消息"), timeout=TICK, since=n)
    await asyncio.sleep(1)
    check("control panel message gone → still published, no standalone success message",
          c5 and post and not [e for e in log[n:] if is_send(e, "sendMessage", REVIEW, "定时发布成功")])


if __name__ == "__main__":
    asyncio.run(lt.main(scenario, {"DB_PATH": DB, "REMINDER_INTERVAL_MINUTES": "0"},
                        allowed_errors=("发布 #1 失败",)))
