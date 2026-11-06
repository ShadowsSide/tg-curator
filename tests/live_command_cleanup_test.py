"""审核员的命令处理完自动删掉（CLEANUP_COMMANDS）；针对投稿的命令，回复挂在投稿的控制按钮消息下面，不挂在删掉的命令上。
/msg、/edit 保留；没权限的人发的、不是本机器人处理的命令不删；删不掉时命令照常生效。

用法（项目根目录下）：python tests/live_command_cleanup_test.py
复用 live_test.py 的模拟 Bot API 服务器。
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import live_test as lt  # noqa: E402
from live_test import REVIEW, USER, check, gm, is_send, log, submit, wait_for  # noqa: E402

STRANGER = 9  # 审核群里的普通成员，不是审核员


def deleted(mid, since):
    return any(e["method"] == "deleteMessage" and str(e["params"].get("chat_id")) == str(REVIEW)
               and str(e["params"].get("message_id")) == str(mid) and not e.get("error") for e in log[since:])


def reply_target(e):
    rp = e and e["params"].get("reply_parameters") or {}
    return str(rp.get("message_id")) if rp else None


def stranger(text):
    d = {"message_id": 8000 + lt.uid[0], "date": lt.now(), "chat": lt.chat(REVIEW), "text": text,
         "from": {"id": STRANGER, "is_bot": False, "first_name": "Stranger"},
         "entities": [{"type": "bot_command", "offset": 0, "length": len(text.split()[0])}]}
    lt.push(message=d)
    return d["message_id"]


async def settle(wait=1.0):
    await asyncio.sleep(wait)


async def scenario():
    await wait_for(lambda e: e["method"] == "setMyCommands", 15, since=0)

    # 1. 不针对投稿的命令：处理完删掉
    for cmd, marker in (("/stats", "#审核统计"), ("/queue", "定时"), ("/help", "/msg")):
        n = len(log); mid = gm(cmd)
        e = await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, marker), since=n)
        await wait_for(lambda e: e["method"] == "deleteMessage", since=n)
        check(f"{cmd} → handled, then the command is deleted", e and deleted(mid, n))

    # 2. /no 回复控制按钮消息：拒绝、删掉命令，“已拒绝”挂在控制按钮消息下面
    c1 = await submit("命令清理 一", 1)
    ctrl1 = c1["result"]["message_id"]
    n = len(log); mid = gm("/no 图片不清楚", reply_to=ctrl1)
    e = await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, "已拒绝"), since=n)
    await wait_for(lambda e: e["method"] == "deleteMessage", since=n)
    check("/no → rejected, command deleted, reply under the control panel message (not the command)",
          e and deleted(mid, n) and reply_target(e) == str(ctrl1) and "图片不清楚" in e["params"]["text"],
          e and reply_target(e))
    # 已经拒绝过的再 /no：错误提示也挂在控制按钮消息下面
    n = len(log); mid = gm("/no", reply_to=ctrl1)
    e = await wait_for(lambda e: is_send(e, "sendMessage", REVIEW) and reply_target(e) == str(ctrl1), since=n)
    await settle()
    check("/no on an already rejected one → error under the control panel message, command deleted",
          e and deleted(mid, n), e and e["params"]["text"])

    # 3. /ban、/unban 回复控制按钮消息：回复都挂在控制按钮消息下面
    c2 = await submit("命令清理 二", 2)
    ctrl2 = c2["result"]["message_id"]
    n = len(log); mid = gm("/ban 刷屏", reply_to=ctrl2)
    e = await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, "已封禁"), since=n)
    await settle()
    check("/ban → reply under the control panel message, command deleted",
          e and deleted(mid, n) and reply_target(e) == str(ctrl2), e and reply_target(e))
    n = len(log); mid = gm("/unban", reply_to=ctrl2)
    e = await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, "解除"), since=n)
    await settle()
    check("/unban → reply under the control panel message, command deleted",
          e and deleted(mid, n) and reply_target(e) == str(ctrl2), e and reply_target(e))

    # 4. 不针对投稿的命令出错：照常回复命令（回复先发，命令后删）
    n = len(log); mid = gm("/no")
    e = await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, "回复"), since=n)
    await settle()
    check("/no without a reply → usage shown as a reply to the command, then the command is deleted",
          e and reply_target(e) == str(mid) and deleted(mid, n), e and reply_target(e))

    # 5. /msg、/edit 保留
    c3 = await submit("命令清理 三", 3)
    ctrl3 = c3["result"]["message_id"]
    n = len(log); mid = gm("/msg 请补充来源", reply_to=ctrl3)
    await wait_for(lambda e: is_send(e, "sendMessage", USER, "请补充来源"), since=n)
    await settle()
    check("/msg is kept (the group's only record of what the submitter was sent)", not deleted(mid, n))
    n = len(log); mid = gm("/edit 命令清理 三改", reply_to=ctrl3)
    await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, "已修改"), since=n)
    await settle()
    check("/edit is kept (it has its own keep-the-latest cleanup)", not deleted(mid, n))

    # 6. 不是审核员发的、不是本机器人处理的：不删
    n = len(log); mid = stranger("/stats")
    await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, "权限"), since=n)
    await settle()
    check("a non-reviewer's command is not deleted", not deleted(mid, n))
    n = len(log); mid = gm("/foo"); mid2 = gm("/no@other_bot", reply_to=ctrl3)
    await settle(1.5)
    check("unknown commands and commands for another bot are not deleted",
          not deleted(mid, n) and not deleted(mid2, n) and not any(
              is_send(e, "sendMessage", REVIEW, "已拒绝") for e in log[n:]))

    # 7. 删不掉（没有删除权限）：命令照常生效，只记日志
    lt.MOCK["fail"][f"deleteMessage:{REVIEW}"] = ["Bad Request: message can't be deleted"]
    n = len(log); gm("/queue")
    e = await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, "定时"), since=n)
    failed = await wait_for(lambda e: e["method"] == "deleteMessage" and e.get("error"), since=n)
    check("delete fails → command still answered, no error", e and failed)
    await settle(0.5)


if __name__ == "__main__":
    asyncio.run(lt.main(scenario, {"REMINDER_INTERVAL_MINUTES": "0"}))
