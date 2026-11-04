"""投稿人操作频率限制：/msg 和改稿合计每分钟最多 5 次，超出时提示等几秒，审核群收不到；审核员不受限制。

用法（项目根目录下）：python tests/live_throttle_test.py
复用 live_test.py 的模拟 Bot API 服务器。
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import live_test as lt  # noqa: E402
from live_test import REVIEW, USER, check, is_send, log, user_says, wait_for  # noqa: E402

TOO_OFTEN = "操作太频繁"




async def scenario():
    await wait_for(lambda e: e["method"] == "setMyCommands", 15, since=0)
    n = len(log); mid = lt.pm("频率测试原文")
    await wait_for(lambda e: any(is_send(e, "sendMessage", USER, p) for p in lt.PROMPTS), since=n)

    # 草稿阶段改稿不发审核群：不计数
    for i in range(6):
        await user_says(f"/edit 草稿第 {i} 版", mid)
    n = len(log); lt.cb("u:sign:1", USER, USER)
    ctrl = await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, lt.CTRL), since=n)
    check("draft edits are not limited", ctrl)

    # 提交后：3 次 /msg + 2 次改稿 = 5 次，都送到审核群
    replies = [await user_says(f"/msg 第 {i} 条留言", mid) for i in range(3)]
    replies += [await user_says(f"/edit 提交后第 {i} 版", mid) for i in range(2)]
    check("5 actions within a minute → all go through",
          all(r and TOO_OFTEN not in r["params"]["text"] for r in replies), [r and r["params"]["text"] for r in replies])

    # 第 6 次：/msg 和改稿都被拦下，审核群收不到
    n = len(log)
    msg = await user_says("/msg 第六条留言", mid)
    edit = await user_says("/edit 第六版", mid)
    await asyncio.sleep(0.5)
    check("6th action → refused with how long to wait, nothing sent to review",
          msg and TOO_OFTEN in msg["params"]["text"] and edit and TOO_OFTEN in edit["params"]["text"]
          and not [e for e in log[n:] if is_send(e, "sendMessage", REVIEW, "第六")],
          (msg and msg["params"]["text"], edit and edit["params"]["text"]))

    # 审核员不受限制
    n = len(log); lt.gm("/edit 审核员的修改", reply_to=ctrl["result"]["message_id"])
    check("reviewer edits are not limited", await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, "审核员的修改"),
                                                           since=n))


if __name__ == "__main__":
    asyncio.run(lt.main(scenario, {"REMINDER_INTERVAL_MINUTES": "0"}))
