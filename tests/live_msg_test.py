"""/msg 沟通的边界情况：沟通窗口关闭、被封禁的用户、英文客户端看到的身份标签。

用法（项目根目录下）：python tests/live_msg_test.py
以 MSG_WINDOW_DAYS=0 运行（审核结束后立即关闭沟通），复用 live_test.py 的模拟 Bot API 服务器。约 10 秒。
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import live_test as lt  # noqa: E402
from live_test import ADMIN, BOB, REVIEW, USER, check, gm, is_send, log, now, pm, submit, wait_for  # noqa: E402


def reply_to(chat_id, message_id, by_bot=True):
    sender = {"id": 1, "is_bot": True, "first_name": "TestBot"} if by_bot else \
        {"id": chat_id, "is_bot": False, "first_name": "User"}
    return {"message_id": message_id, "date": now(), "chat": lt.chat(chat_id), "from": sender}


async def scenario():
    await wait_for(lambda e: e["method"] == "setMyCommands", 15, since=0)

    # 英文客户端的投稿人：看到的是 “Reviewer”，审核群里仍是中文
    ctrl = await submit("english user post", 1, BOB)
    n = len(log); gm("/msg please add a source", reply_to=ctrl["result"]["message_id"])
    e = await wait_for(lambda e: is_send(e, "sendMessage", BOB, "please add a source"), since=n)
    check("English submitter sees the reviewer as “Reviewer”", e and e["params"]["text"].startswith("💬 Reviewer:"))
    relay = e["result"]["message_id"]
    n = len(log); pm("/msg here it is", who=BOB, reply_to_message=reply_to(BOB, relay))
    e = await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, "here it is"), since=n)
    check("review group label stays in the review language", e and e["params"]["text"].startswith("💬 投稿人："))

    # 审核结束 → MSG_WINDOW_DAYS=0 时立即关闭沟通（双方都提示已关闭）
    n = len(log); gm("/no 不合适", reply_to=ctrl["result"]["message_id"])
    await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, "已拒绝"), since=n)
    await asyncio.sleep(1.2)
    n = len(log); gm("/msg 再补充一句", reply_to=ctrl["result"]["message_id"])
    e = await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, "沟通已关闭"), since=n)
    leaked = await wait_for(lambda e: is_send(e, "sendMessage", BOB, "再补充一句"), timeout=0.5, since=n)
    check("after the window closes, reviewer /msg is refused", e and not leaked)
    n = len(log); pm("/msg can I still talk?", who=BOB, reply_to_message=reply_to(BOB, relay))
    e = await wait_for(lambda e: is_send(e, "sendMessage", BOB, "messaging is closed"), since=n)
    check("after the window closes, submitter /msg is refused (in English)", e)

    # 被封禁的投稿人不能再发 /msg；审核员仍可以给他发消息（例如解释原因）
    ctrl2 = await submit("会被封禁的人", 2, USER)
    n = len(log); gm("/msg 先问一下", reply_to=ctrl2["result"]["message_id"])
    relay2 = (await wait_for(lambda e: is_send(e, "sendMessage", USER, "先问一下"), since=n))["result"]["message_id"]
    n = len(log); lt.push(message={
        "message_id": 9000 + lt.uid[0], "date": now(), "chat": lt.chat(REVIEW), "text": "/ban 刷屏",
        "entities": [{"type": "bot_command", "offset": 0, "length": 4}],
        "from": {"id": ADMIN, "is_bot": False, "first_name": "Admin"},
        "reply_to_message": {"message_id": ctrl2["result"]["message_id"], "date": now(), "chat": lt.chat(REVIEW)}})
    await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, "已封禁"), since=n)
    n = len(log); pm("/msg 为什么封我", reply_to_message=reply_to(USER, relay2))
    e = await wait_for(lambda e: is_send(e, "sendMessage", USER, "你已被禁止投稿"), since=n)
    leaked = await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, "为什么封我"), timeout=0.5, since=n)
    check("banned submitter cannot /msg", e and not leaked)


if __name__ == "__main__":
    asyncio.run(lt.main(scenario, {"MSG_WINDOW_DAYS": "0", "REMINDER_INTERVAL_MINUTES": "0"}))
