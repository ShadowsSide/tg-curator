"""统计消息（定时提醒、/stats）上的按钮：跳到等得最久的待审核投稿；审核完一条，刷新时改指下一条；全部审核完去掉按钮。

用法（项目根目录下）：python tests/live_stats_button_test.py
复用 live_test.py 的模拟 Bot API 服务器。
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import live_test as lt  # noqa: E402
from live_test import ADMIN, REVIEW, check, is_send, log, submit, wait_for  # noqa: E402

STATS = "#审核统计"
LINK = f"https://t.me/c/{str(REVIEW).removeprefix('-100')}/"


def urls(e):
    kb = (e["params"].get("reply_markup") or {}).get("inline_keyboard", []) if e else []
    return [b.get("url") for row in kb for b in row]


def stats_edit(mid, since):
    return wait_for(lambda e: e["method"] == "editMessageText" and str(e["params"].get("message_id")) == str(mid)
                    and not e.get("error"), since=since)


async def publish(sid, ctrl_id, text):
    n = len(log); lt.cb(await lt.pub_ok(sid), REVIEW, ADMIN, message_id=ctrl_id)
    await wait_for(lambda e: is_send(e, "sendMessage", lt.CHANNEL, text), since=n)
    return n


async def scenario():
    await wait_for(lambda e: e["method"] == "setMyCommands", 15, since=0)

    # 1. 没有待审核的投稿：统计消息不带按钮
    n = len(log); lt.gm("/stats")
    e = await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, STATS), since=n)
    check("nothing pending → stats message has no button", e and urls(e) == [], e and urls(e))

    # 2. 两条待审核：/stats 的按钮跳到先提交的那条的控制按钮消息
    c1 = await submit("统计按钮 一", 1)
    c2 = await submit("统计按钮 二", 2)
    ctrl1, ctrl2 = c1["result"]["message_id"], c2["result"]["message_id"]
    n = len(log); lt.gm("/stats")
    e = await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, STATS), since=n)
    stats_id = e and e["result"]["message_id"]
    check("two pending → button links to the one submitted first",
          e and urls(e) == [f"{LINK}{ctrl1}"], e and urls(e))

    # 3. 发布第一条：刷新统计消息时按钮改指第二条（编辑文字时一起带上按钮，不会被去掉）
    n = await publish(1, ctrl1, "统计按钮 一")
    e = await stats_edit(stats_id, n)
    check("first one published → refreshed stats message links to the next one",
          e and urls(e) == [f"{LINK}{ctrl2}"], e and urls(e))

    # 4. 全部审核完：刷新时去掉按钮
    n = await publish(2, ctrl2, "统计按钮 二")
    e = await stats_edit(stats_id, n)
    check("all reviewed → refreshed stats message has no button", e and urls(e) == [], e and urls(e))

    # 5. 新投稿进来：没有按钮的统计消息又带上按钮
    n = len(log); c3 = await submit("统计按钮 三", 3)
    e = await stats_edit(stats_id, n)
    check("a new submission → button comes back", e and urls(e) == [f"{LINK}{c3['result']['message_id']}"],
          e and urls(e))


if __name__ == "__main__":
    asyncio.run(lt.main(scenario, {"REMINDER_INTERVAL_MINUTES": "0"}))
