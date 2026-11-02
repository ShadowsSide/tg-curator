"""投稿人用相册 /msg（说明里写 /msg）：整组转达给审核员，其余几项不会变成新投稿；
带 /msg 的那项不在最前面也一样。审核员回复转来的任何一张都能定位到这条投稿。

用法（项目根目录下）：python tests/live_msg_album_test.py
复用 live_test.py 的模拟 Bot API 服务器。约 8 秒。
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import live_test as lt  # noqa: E402
from live_test import REVIEW, USER, check, gm, is_send, log, wait_for  # noqa: E402


def photo(fid):
    return [{"file_id": fid, "file_unique_id": fid, "width": 10, "height": 10}]


async def scenario():
    await wait_for(lambda e: e["method"] == "setMyCommands", 15, since=0)
    n = len(log); user_msg = lt.pm("相册留言测试")
    await wait_for(lambda e: any(is_send(e, "sendMessage", USER, p) for p in lt.PROMPTS), since=n)
    lt.cb("u:sign:1", USER, USER)
    await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, lt.CTRL), since=n)

    # 三张图的相册，/msg 写在第二张的说明里；回复的是自己的投稿
    reply = {"message_id": user_msg, "date": lt.now(), "chat": lt.chat(USER)}
    n = len(log)
    lt.pm(None, photo=photo("A1"), media_group_id="g1", reply_to_message=reply)
    text = "/msg 补充三张图"
    lt.pm(None, photo=photo("A2"), media_group_id="g1", reply_to_message=reply, caption=text,
          caption_entities=[{"type": "bot_command", "offset": 0, "length": 4}])
    lt.pm(None, photo=photo("A3"), media_group_id="g1", reply_to_message=reply)

    group = await wait_for(lambda e: is_send(e, "sendMediaGroup", REVIEW), since=n)
    media = group["params"]["media"] if group else []
    check("whole album relayed to the review group, label on the captioned item",
          len(media) == 3 and [m["media"] for m in media] == ["A1", "A2", "A3"]
          and media[1].get("caption", "").startswith("💬 投稿人：") and "补充三张图" in media[1]["caption"]
          and not media[0].get("caption"), media)
    ok = await wait_for(lambda e: is_send(e, "sendMessage", USER, "已发送给审核员"), since=n)
    await asyncio.sleep(1)
    acks = [e for e in log[n:] if is_send(e, "sendMessage", USER, "已发送给审核员")]
    drafts = [e for e in log[n:] if any(is_send(e, "sendMessage", USER, p) for p in lt.PROMPTS)]
    check("submitter told once, no new draft from the other photos", ok and len(acks) == 1 and not drafts,
          [e["params"]["text"] for e in log[n:] if is_send(e, "sendMessage", USER)])

    # 审核员直接回复转来的第三张（没写 /msg）：提示用 /msg，说明认得出这是转来的消息
    third = group["result"][2]["message_id"]
    n = len(log); gm("好的", reply_to=third)
    check("reviewer replying to any relayed photo is recognised",
          await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, "/msg"), since=n))
    check("control message counts one conversation, not three",
          await wait_for(lambda e: e["method"] == "editMessageText" and "沟通 1 条" in e["params"].get("text", ""),
                         since=0)
          and not [e for e in log if "沟通 3 条" in str(e["params"].get("text", ""))])


if __name__ == "__main__":
    asyncio.run(lt.main(scenario, {"REMINDER_INTERVAL_MINUTES": "0"}))
