"""两名审核员几乎同时处理同一条投稿：一人确认发布、另一人确认拒绝（不等前一个按钮的回应就点）。
- 只有一方生效：要么发到频道，要么投稿人收到拒绝通知，不会两样都有
- 两个按钮都只回应一次、都在时限内，没有“出错了”
- 没生效的一方被告知：发布晚了 → 回复控制按钮消息说明状态已变化；拒绝晚了 → 弹窗说明正在发布 / 已发布 / 状态已变化
先发布、先拒绝各来几轮。

用法（项目根目录下）：python tests/live_concurrent_review_test.py
复用 live_test.py 的模拟 Bot API 服务器。
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import live_test as lt  # noqa: E402
from live_test import ADMIN, CHANNEL, REVIEW, USER, check, is_send, log, submit, wait_for  # noqa: E402

ADMIN2 = 8  # 第二名审核员（审核群管理员）
ROUNDS = 4
LATE_PUBLISH = "状态已变化"
LATE_REJECT = ("正在发布", "已发布", "状态已变化")  # 拒绝读到的还是待审核、写入时已经在发布：状态已变化


async def round_(sid, publish_first):
    ctrl = (await submit(f"并发审核 {sid}", sid))["result"]["message_id"]
    pub = await lt.pub_ok(sid)
    n = len(log)
    clicks = [(pub, ADMIN), (f"r:reject_ok:{sid}:0", ADMIN2)]
    for data, who in clicks if publish_first else clicks[::-1]:  # 连着推送，不等回应
        lt.cb(data, REVIEW, who, message_id=ctrl)
    await asyncio.sleep(2)

    posted = [e for e in log[n:] if is_send(e, "sendMessage", CHANNEL, f"并发审核 {sid}")]
    rejected = [e for e in log[n:] if is_send(e, "sendMessage", USER, "未通过审核")]
    answers = [e for e in log[n:] if e["method"] == "answerCallbackQuery"]
    errors = [e for e in log[n:] if not e.get("error") and "出错了" in str(e["params"].get("text", ""))]
    late_pub = [e for e in log[n:] if is_send(e, "sendMessage", REVIEW, LATE_PUBLISH)]
    late_rej = [e for e in answers if e["params"].get("show_alert") in (True, "true")
                and any(x in e["params"].get("text", "") for x in LATE_REJECT)]
    order = "publish first" if publish_first else "reject first"
    check(f"#{sid} ({order}) → exactly one wins (posted xor rejected)", bool(posted) != bool(rejected),
          (len(posted), len(rejected)))
    check(f"#{sid} ({order}) → both buttons answered once, in time, no “something went wrong”",
          len(answers) == 2 and not any(e.get("error") for e in answers) and not errors,
          [(e["params"].get("text"), e.get("error")) for e in answers])
    check(f"#{sid} ({order}) → the loser is told why", bool(late_rej) if posted else bool(late_pub),
          [e["params"].get("text") for e in answers] + [e["params"].get("text") for e in late_pub])
    return "published" if posted else "rejected"


async def scenario():
    await wait_for(lambda e: e["method"] == "setMyCommands", 15, since=0)
    lt.MOCK["admins"].add(ADMIN2)
    lt.MOCK["callback_deadline"] = 2
    winners = [await round_(sid, publish_first=sid % 2 == 1) for sid in range(1, ROUNDS + 1)]
    print("winners:", winners)


if __name__ == "__main__":
    asyncio.run(lt.main(scenario, {"CALLBACK_FALLBACK_SECONDS": "1", "NEW_USER_COOLDOWN_MINUTES": "0",
                                   "MAX_PENDING_PER_USER": "0"}))
