"""限流（429）测试：自动等待重试、限流太久时改为稍后发布、统计消息合并更新。

用法（项目根目录下）：python tests/live_flood_test.py
复用 live_test.py 的模拟 Bot API 服务器，按需注入 429 响应。约 20 秒。
"""
import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import live_test as lt  # noqa: E402
from live_test import ADMIN, CHANNEL, CTRL, REVIEW, USER, check, is_send, log, wait_for  # noqa: E402


async def submit(text, sid):
    n = len(log); lt.pm(text)
    await wait_for(lambda e: is_send(e, "sendMessage", USER, "请选择投稿方式"), since=n)
    n = len(log); lt.cb(f"u:sign:{sid}", USER, USER)
    return await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, CTRL), since=n)


def floods(since, method, chat):
    return [e for e in log[since:] if e.get("flood") is not None and e["method"] == method
            and str(e["params"].get("chat_id")) == str(chat)]


async def scenario():
    await wait_for(lambda e: e["method"] == "setMyCommands", 15, since=0)
    ctrls = [await submit(f"限流测试 {i}", i) for i in (1, 2, 3, 4)]

    # 1. 发布到频道时被短暂限流 → 自动等待后重试成功，不会标记为失败
    lt.MOCK["flood"][f"sendMessage:{CHANNEL}"] = [2]
    n = len(log); t0 = time.time(); lt.cb("r:pub_ok:1:0", REVIEW, ADMIN)
    post = await wait_for(lambda e: is_send(e, "sendMessage", CHANNEL, "限流测试 1"), timeout=15, since=n)
    failed = [e for e in log[n:] if e["method"] == "editMessageText" and "发布失败" in e["params"].get("text", "")]
    check("short 429 on publish → waits ~2s, retries, post goes out, not marked failed",
          post and floods(n, "sendMessage", CHANNEL) and not failed and post["t"] - t0 >= 2,
          post and f"{post['t'] - t0:.1f}s")

    # 2. 被限流太久（超过原地等待上限）→ 改为稍后自动发布，状态是“已定时”而不是“发布失败”
    lt.MOCK["flood"][f"sendMessage:{CHANNEL}"] = [120]
    n = len(log); lt.cb("r:pub_ok:2:0", REVIEW, ADMIN)
    msg = await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, "限流"), since=n)
    ctrl_sched = await wait_for(lambda e: e["method"] == "editMessageText"
                                and str(e["params"].get("message_id")) == str(ctrls[1]["result"]["message_id"])
                                and "定时发布" in e["params"].get("text", ""), since=n)
    failed = [e for e in log[n:] if e["method"] == "editMessageText" and "发布失败" in e["params"].get("text", "")]
    check("long 429 on publish → postponed and shown as scheduled, admin told why, not failed",
          msg and ctrl_sched and not failed, msg and msg["params"]["text"])

    # 3. 审核群里的操作（编辑控制消息）被限流 → 同样自动重试
    lt.MOCK["flood"][f"editMessageText:{REVIEW}"] = [1]
    n = len(log); lt.cb("r:silent:3:0", REVIEW, ADMIN)
    e = await wait_for(lambda e: is_send(e, "editMessageText", REVIEW, "静音发送：🔕 开"), timeout=10, since=n)
    check("429 on editing the control message → retried and applied", e and floods(n, "editMessageText", REVIEW))

    # 4. 统计消息：短时间内多次审核只编辑一次，并且显示最终数字
    n = len(log); lt.gm("/stats")
    stats = await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, "#审核统计"), since=n)
    sid_stats = stats["result"]["message_id"]
    await asyncio.sleep(4)  # 让 /stats 前积累的刷新先完成
    n = len(log)
    lt.gm("/no 一", reply_to=ctrls[2]["result"]["message_id"])
    lt.gm("/no 二", reply_to=ctrls[3]["result"]["message_id"])
    await asyncio.sleep(5)
    edits = [e for e in log[n:] if e["method"] == "editMessageText" and str(e["params"].get("message_id")) == str(sid_stats)]
    check("several quick review actions → stats message edited once, with the final numbers",
          len(edits) == 1 and "拒绝 2" in edits[0]["params"]["text"], [e["params"]["text"].split("\n")[0] for e in edits])


if __name__ == "__main__":
    asyncio.run(lt.main(scenario, {"REMINDER_INTERVAL_MINUTES": "0"}))
