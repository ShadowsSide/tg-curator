"""私聊里的服务消息（置顶、自动删除计时等）不回复“不支持”；用户发来的不支持内容（贴纸）照旧回复。

用法（项目根目录下）：python tests/live_service_test.py
复用 live_test.py 的模拟 Bot API 服务器。约 5 秒。
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import live_test as lt  # noqa: E402
from live_test import USER, check, is_send, log, wait_for  # noqa: E402

UNSUPPORTED = "暂不支持"


async def scenario():
    await wait_for(lambda e: e["method"] == "setMyCommands", 15, since=0)

    n = len(log)
    lt.pm(pinned_message={"message_id": 1, "date": lt.now(), "chat": lt.chat(USER), "text": "被置顶的消息"})
    lt.pm(message_auto_delete_timer_changed={"message_auto_delete_time": 86400})
    lt.pm(write_access_allowed={"from_request": True})
    await asyncio.sleep(1.5)
    replies = [e for e in log[n:] if is_send(e, "sendMessage", USER)]
    check("service messages → no reply", not replies, [e["params"]["text"] for e in replies])

    n = len(log)
    lt.pm(sticker={"file_id": "st1", "file_unique_id": "st1", "type": "regular", "width": 512, "height": 512,
                   "is_animated": False, "is_video": False})
    check("sticker → still told it's unsupported",
          await wait_for(lambda e: is_send(e, "sendMessage", USER, UNSUPPORTED), since=n))


if __name__ == "__main__":
    asyncio.run(lt.main(scenario, {"REMINDER_INTERVAL_MINUTES": "0"}))
