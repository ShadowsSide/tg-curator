"""发送失败后的状态：提交退回草稿、发布不卡在“发布中”、改稿预览发不出去就不保存。

用法（项目根目录下）：python tests/live_send_fail_test.py
复用 live_test.py 的模拟 Bot API 服务器，按需注入失败。约 10 秒。
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import live_test as lt  # noqa: E402
from live_test import ADMIN, CHANNEL, CTRL, REVIEW, USER, check, is_send, log, pm, submit, wait_for  # noqa: E402

KICKED = (403, "Forbidden: bot was kicked from the group chat")


async def draft(**kw):
    n = len(log); pm(**kw)
    await wait_for(lambda e: any(is_send(e, "sendMessage", USER, p) for p in lt.PROMPTS), since=n)


async def press_submit(sid):
    n = len(log); lt.cb(f"u:sign:{sid}", USER, USER)
    answer = await wait_for(lambda e: e["method"] == "answerCallbackQuery", since=n)
    return n, answer


def told_draft(answer):
    return answer and "还在草稿" in answer["params"].get("text", "")


async def scenario():
    await wait_for(lambda e: e["method"] == "setMyCommands", 15, since=0)

    # 1. 预览发不出去：退回草稿，再点一次能正常进审核群
    await draft(text="提交失败测试")
    lt.MOCK["fail"][f"sendMessage:{REVIEW}"] = [KICKED]
    n, answer = await press_submit(1)
    check("preview fails → submitter told it's still a draft", told_draft(answer), answer and answer["params"])
    await asyncio.sleep(0.3)
    check("nothing reached the review group", not [e for e in log[n:] if is_send(e, "sendMessage", REVIEW)])
    n = len(log); lt.cb("u:sign:1", USER, USER)
    ctrl = await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, CTRL), since=n)
    check("pressing again submits it", ctrl)

    # 2. 预览发出去了但控制按钮消息失败：预览收回，不留下没法操作的消息
    photo = [{"file_id": "p", "file_unique_id": "u", "width": 1, "height": 1}]
    await draft(caption="控制按钮消息失败测试", photo=photo)
    lt.MOCK["fail"][f"sendMessage:{REVIEW}"] = [KICKED]
    n, answer = await press_submit(2)
    preview = await wait_for(lambda e: is_send(e, "sendPhoto", REVIEW), since=n)
    removed = await wait_for(lambda e: e["method"] == "deleteMessages"
                             and preview["result"]["message_id"] in e["params"].get("message_ids", []), since=n)
    check("control panel message fails → preview removed, still a draft", told_draft(answer) and removed)

    # 3. 发布时控制按钮消息更新失败：照常发到频道，不卡在“发布中”
    lt.MOCK["fail"][f"editMessageText:{REVIEW}"] = [KICKED]
    n = len(log); lt.cb(await lt.pub_ok(1), REVIEW, ADMIN)
    check("control update fails during publish → still published",
          await wait_for(lambda e: is_send(e, "sendMessage", CHANNEL, "提交失败测试"), since=n))

    # 4. 改稿预览发不出去：不保存，发布的还是审核员看过的内容
    c3 = await submit("审核过的原文", 3)
    lt.MOCK["fail"][f"sendMessage:{REVIEW}"] = [KICKED]
    n = len(log); lt.gm("/edit 没人看过的新内容", reply_to=c3["result"]["message_id"])
    check("edit preview fails → editor told it wasn't saved",
          await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, "没有保存"), since=n))
    n = len(log); lt.cb(await lt.pub_ok(3), REVIEW, ADMIN)
    post = await wait_for(lambda e: is_send(e, "sendMessage", CHANNEL), since=n)
    check("publish sends the reviewed text, not the unseen edit",
          post and "审核过的原文" in post["params"]["text"] and "没人看过" not in post["params"]["text"],
          post and post["params"]["text"])

    # 5. 改稿正常时：预览和发布都是新内容
    c4 = await submit("第四条原文", 4)
    n = len(log); lt.gm("/edit 第四条新内容", reply_to=c4["result"]["message_id"])
    check("normal edit → new preview sent",
          await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, "第四条新内容"), since=n))
    n = len(log); lt.cb(await lt.pub_ok(4), REVIEW, ADMIN)
    check("normal edit → new text published",
          await wait_for(lambda e: is_send(e, "sendMessage", CHANNEL, "第四条新内容"), since=n))


if __name__ == "__main__":
    asyncio.run(lt.main(scenario, {"REMINDER_INTERVAL_MINUTES": "0"},
                        allowed_errors=("发到审核群失败", "修改预览发送失败")))
