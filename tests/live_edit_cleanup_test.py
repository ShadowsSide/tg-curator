"""审核员改稿成功后留下的修改消息和“已修改”确认，每条投稿只留最近一次：下次改稿成功时删掉上一次的。
- /edit 新内容、回复“✏️ 修改”的提示：审核员的消息和确认都算
- 添加 / 替换媒体：只算确认（审核员的图片留着，相册后到的部分还要回复在它下面）
- 失败的（比如没回复投稿）留着，也不顶掉上一次的
- 每条投稿各留各的

用法（项目根目录下）：python tests/live_edit_cleanup_test.py
复用 live_test.py 的模拟 Bot API 服务器。约 15 秒。
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import live_test as lt  # noqa: E402
from live_media_test import admin_media, ask, photo  # noqa: E402
from live_test import REVIEW, check, gm, is_send, log, submit, wait_for  # noqa: E402

def deleted(since):
    """since 之后机器人在审核群删掉的消息。"""
    out = []
    for e in log[since:]:
        if not e.get("error") and str(e["params"].get("chat_id")) == str(REVIEW):
            if e["method"] == "deleteMessages":
                out += [int(i) for i in e["params"]["message_ids"]]
            elif e["method"] == "deleteMessage":
                out.append(int(e["params"]["message_id"]))
    return out


async def edit_cmd(text, ctrl):
    """审核员回复控制消息发 /edit，返回 (命令消息, 确认消息)。"""
    n = len(log); cmd = 5000 + lt.uid[0]; gm(text, reply_to=ctrl)
    ack = await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, "已修改"), since=n)
    await asyncio.sleep(0.5)
    return cmd, ack and ack["result"]["message_id"]


async def scenario():
    await wait_for(lambda e: e["method"] == "setMyCommands", 15, since=0)
    ctrl = (await submit("清理测试", 1))["result"]["message_id"]
    other = (await submit("另一条", 2))["result"]["message_id"]

    # 第一次 /edit：留着
    n = len(log); first = await edit_cmd("/edit 审核员改的", ctrl)
    check("first /edit → command and confirmation stay", all(first) and not deleted(n))

    # 回复“✏️ 修改”的提示：顶掉第一次的，这次的留着
    p = await ask("edit", 1, ctrl, "回复本消息")
    n = len(log); reply_id = 5000 + lt.uid[0]; gm("提示里改的", reply_to=p["result"]["message_id"])
    ack = await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, "已修改"), since=n)
    await asyncio.sleep(0.5)
    second = (reply_id, ack and ack["result"]["message_id"])
    check("next edit (Edit prompt) → the previous command and confirmation deleted, this one stays",
          set(first) <= set(deleted(n)) and not set(second) & set(deleted(n)), deleted(n))

    # 添加媒体：顶掉上一次的；这次只记确认，审核员的图片留着
    p = await ask("madd", 1, ctrl, "要添加的图片")
    n = len(log); pic = 7000 + lt.uid[0]; admin_media(p["result"]["message_id"], photo=photo("X"))
    ack = await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, "已修改"), since=n)
    await asyncio.sleep(0.5)
    third = ack and ack["result"]["message_id"]
    check("add media → previous edit's messages deleted, this confirmation stays",
          set(second) <= set(deleted(n)) and third not in deleted(n), deleted(n))
    n = len(log); await edit_cmd("/edit 加图之后再改", ctrl)
    check("next edit after adding media → only the confirmation goes, the reviewer's photo stays",
          third in deleted(n) and pic not in deleted(n), deleted(n))

    # 失败的留着，也不顶掉上一次的
    n = len(log); gm("/edit 没回复投稿")
    err = await wait_for(lambda e: is_send(e, "sendMessage", REVIEW), since=n)
    await asyncio.sleep(0.5)
    check("failed /edit → nothing deleted", err and not deleted(n), deleted(n))

    # 另一条投稿各留各的
    n = len(log); await edit_cmd("/edit 另一条的修改", other)
    check("an edit on another submission doesn't touch this one's messages", not deleted(n), deleted(n))

if __name__ == "__main__":
    asyncio.run(lt.main(scenario, {"REMINDER_INTERVAL_MINUTES": "0"}))
