"""审核员改稿成功后，“已修改”的确认显示几秒再删掉，审核员发的修改消息也一起删，审核群里只留预览和控制消息：
- /edit 新内容、回复“✏️ 修改”的提示：确认和审核员的消息都删
- 添加 / 替换媒体：只删确认（相册后到的部分还要回复在审核员的图片下面）
- 失败的（比如没回复投稿）留着，审核员要看原因

用法（项目根目录下）：python tests/live_edit_cleanup_test.py
复用 live_test.py 的模拟 Bot API 服务器。约 25 秒。
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import live_test as lt  # noqa: E402
from live_media_test import admin_media, ask, photo  # noqa: E402
from live_test import REVIEW, check, gm, is_send, log, submit, wait_for  # noqa: E402

TTL = 5  # bot.core.base.EDIT_ACK_TTL


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


async def scenario():
    await wait_for(lambda e: e["method"] == "setMyCommands", 15, since=0)
    ctrl = (await submit("清理测试", 1))["result"]["message_id"]

    # /edit 新内容
    n = len(log); cmd = 5000 + lt.uid[0]; gm("/edit 审核员改的", reply_to=ctrl)
    ack = await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, "已修改"), since=n)
    await asyncio.sleep(1)
    check("/edit → confirmation still shown right after", ack and not deleted(n))
    await asyncio.sleep(TTL)
    check("/edit → a few seconds later the command and the confirmation are deleted",
          ack and {cmd, ack["result"]["message_id"]} <= set(deleted(n)), deleted(n))

    # 回复“✏️ 修改”的提示
    p = await ask("edit", 1, ctrl, "回复本消息")
    n = len(log); reply_id = 5000 + lt.uid[0]; gm("提示里改的", reply_to=p["result"]["message_id"])
    ack = await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, "已修改"), since=n)
    await asyncio.sleep(TTL + 1)
    check("reply to the Edit prompt → the reply and the confirmation are deleted",
          ack and {reply_id, ack["result"]["message_id"]} <= set(deleted(n)), deleted(n))

    # 添加媒体：只删确认，审核员的图片留着
    p = await ask("madd", 1, ctrl, "要添加的图片")
    n = len(log); pic = 7000 + lt.uid[0]; admin_media(p["result"]["message_id"], photo=photo("X"))
    ack = await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, "已修改"), since=n)
    await asyncio.sleep(TTL + 1)
    check("add media → only the confirmation is deleted, the reviewer's photo stays",
          ack and ack["result"]["message_id"] in deleted(n) and pic not in deleted(n), deleted(n))

    # 失败的留着
    n = len(log); gm("/edit 没回复投稿")
    err = await wait_for(lambda e: is_send(e, "sendMessage", REVIEW), since=n)
    await asyncio.sleep(TTL + 1)
    check("failed /edit → nothing deleted", err and not deleted(n), deleted(n))


if __name__ == "__main__":
    asyncio.run(lt.main(scenario, {"REMINDER_INTERVAL_MINUTES": "0"}))
