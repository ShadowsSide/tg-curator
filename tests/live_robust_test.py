"""出错时的两种边界：
- 投稿人改稿失败（审核群的预览发不出去）不占频率限制：连续失败 5 次后，下一次照样能改
- 相册处理出错（相册不经过 aiogram 的错误处理）：和单条消息一样回复“出错了”，而不是什么都不说

用法（项目根目录下）：python tests/live_robust_test.py
复用 live_test.py 的模拟 Bot API 服务器。
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import live_test as lt  # noqa: E402
from live_media_test import user_photo  # noqa: E402
from live_test import REVIEW, USER, check, is_send, log, wait_for  # noqa: E402


def own(mid):
    return {"message_id": mid, "date": lt.now(), "chat": lt.chat(USER)}


async def user_edit(text, mid):
    """投稿人回复投稿发 /edit，返回机器人的回复（成功时先发的完整预览不算）。"""
    n = len(log); lt.pm(text, reply_to_message=own(mid))
    body = text.removeprefix("/edit ")
    return await wait_for(lambda e: is_send(e, "sendMessage", USER) and body not in e["params"].get("text", ""), since=n)


async def scenario():
    await wait_for(lambda e: e["method"] == "setMyCommands", 15, since=0)
    n = len(log); mid = lt.pm("原文")
    await wait_for(lambda e: any(is_send(e, "sendMessage", USER, p) for p in lt.PROMPTS), since=n)
    lt.cb("u:sign:1", USER, USER)
    await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, lt.CTRL), since=n)
    await asyncio.sleep(0.5)

    # 1. 预览连续 5 次发不出去：改稿都失败，但不算次数
    lt.MOCK["fail"][f"sendMessage:{REVIEW}"] = ["Bad Request: chat not found"] * 5
    replies = [await user_edit(f"/edit 第 {i} 次", mid) for i in range(5)]
    check("5 edits fail because the preview can't be sent", all(r and "没有保存" in r["params"]["text"] for r in replies),
          [r and r["params"]["text"] for r in replies])
    r = await user_edit("/edit 恢复后再改", mid)
    check("the next edit goes through: failed edits don't count toward the rate limit",
          r and "投稿已更新" in r["params"]["text"], r and r["params"]["text"])

    # 2. 相册处理出错：回复“出错了”
    lt.MOCK["fail"][f"sendMessage:{USER}"] = ["Bad Request: message to be replied not found"]
    n = len(log)
    for fid in ("A1", "A2"):
        user_photo(fid, group="gx")
    r = await wait_for(lambda e: is_send(e, "sendMessage", USER, "出错了"), since=n)
    check("an album that fails while being handled → the sender is told it didn't go through", r)


if __name__ == "__main__":
    asyncio.run(lt.main(scenario, {"REMINDER_INTERVAL_MINUTES": "0"}, allowed_errors=("处理相册失败", "修改预览发送失败")))
