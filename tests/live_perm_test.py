"""审核员权限测试（REVIEWERS）。

用法（项目根目录下）：python tests/live_perm_test.py
以 REVIEWERS=admins,55 运行：管理员 7 和指定用户 55 可以审核，普通成员 99 不行。约 10 秒。
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import live_test as lt  # noqa: E402
from live_test import ADMIN, CHANNEL, CTRL, REVIEW, USER, check, is_send, log, now, wait_for  # noqa: E402

from bot.permissions import ReviewerPolicy  # noqa: E402

LISTED, MEMBER = 55, 99


def group_msg(text, who, reply_to=None, sender_chat=None):
    lt.uid[0] += 1
    d = {"message_id": 40000 + lt.uid[0], "date": now(), "chat": lt.chat(REVIEW), "text": text,
         "from": {"id": who, "is_bot": False, "first_name": f"U{who}"}}
    if text.startswith("/"):
        d["entities"] = [{"type": "bot_command", "offset": 0, "length": len(text.split()[0])}]
    if reply_to:
        d["reply_to_message"] = {"message_id": reply_to, "date": now(), "chat": lt.chat(REVIEW)}
    if sender_chat:
        d["sender_chat"] = sender_chat
    lt.push(message=d)


def group_cb(data, who, message_id):
    lt.push(callback_query={"id": str(lt.uid[0]), "chat_instance": "x", "data": data,
                            "from": {"id": who, "is_bot": False, "first_name": f"U{who}"},
                            "message": {"message_id": message_id, "date": now(), "chat": lt.chat(REVIEW)}})


async def submit(text, sid):
    n = len(log); lt.pm(text)
    await wait_for(lambda e: is_send(e, "sendMessage", USER, "请选择投稿方式"), since=n)
    n = len(log); lt.cb(f"u:sign:{sid}", USER, USER)
    return await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, CTRL), since=n)


async def scenario():
    # 配置解析
    p = ReviewerPolicy.parse("admins,55")
    check("REVIEWERS parsing", p.admins and not p.everyone and p.user_ids == {55}
          and ReviewerPolicy.parse("all").everyone and ReviewerPolicy.parse("").admins)

    await wait_for(lambda e: e["method"] == "setMyCommands", 15, since=0)
    c1 = await submit("权限测试一", 1)
    c2 = await submit("权限测试二", 2)
    ctrl1, ctrl2 = c1["result"]["message_id"], c2["result"]["message_id"]

    # 普通成员：按钮弹出无权限，命令收到提示，什么都不会发生
    n = len(log); group_cb("r:pub:1:0", MEMBER, ctrl1)
    alert = await wait_for(lambda e: e["method"] == "answerCallbackQuery" and "没有审核权限" in e["params"].get("text", ""), since=n)
    posted = await wait_for(lambda e: is_send(e, "sendMessage", CHANNEL), timeout=1, since=n)
    check("non-reviewer pressing Publish → alert, nothing published", alert and not posted)
    n = len(log); group_msg("/no 我不是审核员", MEMBER, reply_to=ctrl1)
    e = await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, "没有审核权限"), since=n)
    notified = await wait_for(lambda e: is_send(e, "sendMessage", USER, "未通过"), timeout=1, since=n)
    check("non-reviewer /no → told no permission, submission untouched", e and not notified)
    n = len(log); group_msg("/stats", MEMBER)
    e = await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, "#审核统计"), timeout=1.5, since=n)
    check("non-reviewer read-only commands are blocked too", not e)
    n = len(log); group_msg("随便聊聊", MEMBER, reply_to=ctrl1)
    await asyncio.sleep(1)
    check("non-reviewer plain chat is ignored silently",
          not [x for x in log[n:] if x["method"] == "sendMessage" and str(x["params"].get("chat_id")) == str(REVIEW)])

    # 名单里的非管理员：可以审核
    n = len(log); group_msg("/no 名单里的人", LISTED, reply_to=ctrl1)
    e = await wait_for(lambda e: is_send(e, "sendMessage", USER, "名单里的人"), since=n)
    check("listed user (not an admin) can review", e)

    # 管理员：可以审核；身份查询有缓存，不会每次都请求
    n = len(log); group_cb("r:silent:2:0", ADMIN, ctrl2); group_cb("r:spoiler:2:0", ADMIN, ctrl2)
    group_cb("r:pub:2:0", ADMIN, ctrl2)
    post = await wait_for(lambda e: is_send(e, "sendMessage", CHANNEL, "权限测试二"), since=n)
    lookups = [x for x in log if x["method"] == "getChatMember" and str(x["params"]["user_id"]) == str(ADMIN)]
    check("admin can review; admin lookup cached (one getChatMember for many actions)", post and len(lookups) == 1,
          len(lookups))

    # 以群身份匿名发言的管理员
    c3 = await submit("权限测试三", 3)
    n = len(log)
    group_msg("/no 匿名管理员", 1087968824, reply_to=c3["result"]["message_id"],
              sender_chat={"id": REVIEW, "type": "supergroup", "title": "Review"})
    e = await wait_for(lambda e: is_send(e, "sendMessage", USER, "匿名管理员"), since=n)
    check("anonymous admin (posting as the group) can review", e)


if __name__ == "__main__":
    asyncio.run(lt.main(scenario, {"REVIEWERS": "admins,55", "REMINDER_INTERVAL_MINUTES": "0"}))
