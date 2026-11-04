"""用相册 /msg（说明里写 /msg）：整组转达，带 /msg 的那项不在最前面也一样。
投稿人 → 审核员：其余几项不会变成新投稿，审核员回复转来的任何一张都能定位到这条投稿；
审核员 → 投稿人：其余几项不会丢；不写 /msg 直接用相册回复转来的消息，只提醒一次。

用法（项目根目录下）：python tests/live_msg_album_test.py
复用 live_test.py 的模拟 Bot API 服务器。约 8 秒。
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import live_test as lt  # noqa: E402
from live_test import ADMIN, REVIEW, USER, check, gm, is_send, log, wait_for  # noqa: E402


def photo(fid):
    return [{"file_id": fid, "file_unique_id": fid, "width": 10, "height": 10}]


def admin_photo(fid, group, reply_to, caption=None):
    """审核员在审核群回复一条机器人的消息，发相册的一项。"""
    d = {"message_id": 7000 + lt.uid[0], "date": lt.now(), "chat": lt.chat(REVIEW),
         "from": {"id": ADMIN, "is_bot": False, "first_name": "Admin"}, "photo": photo(fid), "media_group_id": group,
         "reply_to_message": {"message_id": reply_to, "date": lt.now(), "chat": lt.chat(REVIEW),
                              "from": {"id": 1, "is_bot": True, "first_name": "TestBot"}}}
    if caption:
        d.update(caption=caption, caption_entities=[{"type": "bot_command", "offset": 0, "length": 4}])
    lt.push(message=d)


async def scenario():
    await wait_for(lambda e: e["method"] == "setMyCommands", 15, since=0)
    n = len(log); user_msg = lt.pm("相册留言测试")
    await wait_for(lambda e: any(is_send(e, "sendMessage", USER, p) for p in lt.PROMPTS), since=n)
    lt.cb("u:sign:1", USER, USER)
    ctrl = await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, lt.CTRL), since=n)

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
    check("control panel message counts one conversation, not three",
          await wait_for(lambda e: e["method"] == "editMessageText" and "沟通 1 条" in e["params"].get("text", ""),
                         since=0)
          and not [e for e in log if "沟通 3 条" in str(e["params"].get("text", ""))])
    # 审核员回复控制按钮消息发相册，/msg 写在第二张：整组转给投稿人，标签在第二张
    n = len(log)
    admin_photo("B1", "g2", ctrl["result"]["message_id"])
    admin_photo("B2", "g2", ctrl["result"]["message_id"], caption="/msg 这是参考图")
    group = await wait_for(lambda e: is_send(e, "sendMediaGroup", USER), since=n)
    media = group["params"]["media"] if group else []
    check("reviewer album relayed whole to the submitter, label on the captioned item",
          [m["media"] for m in media] == ["B1", "B2"] and media[1].get("caption", "").startswith("💬 审核员：")
          and "这是参考图" in media[1]["caption"], media)
    await asyncio.sleep(1)
    acks = [e for e in log[n:] if is_send(e, "sendMessage", REVIEW, "已发送给投稿人")]
    check("reviewer told once", len(acks) == 1, len(acks))

    # 审核员不写 /msg、直接用两张图的相册回复转来的消息：提醒一次，不转达
    n = len(log)
    admin_photo("C1", "g3", third)
    admin_photo("C2", "g3", third)
    await asyncio.sleep(1.5)
    hints = [e for e in log[n:] if is_send(e, "sendMessage", REVIEW, "/msg")]
    leaked = [e for e in log[n:] if str(e["params"].get("chat_id")) == str(USER)]
    check("plain album reply to a relayed message → one hint, nothing relayed", len(hints) == 1 and not leaked,
          (len(hints), [e["method"] for e in leaked]))


if __name__ == "__main__":
    asyncio.run(lt.main(scenario, {"REMINDER_INTERVAL_MINUTES": "0"}))
