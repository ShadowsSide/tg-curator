"""投稿人私聊里找投稿、改投稿的几种边界：
- 纯文字投稿加了图：“编辑”那张图是换图，说明（来自原文字消息）保留；回复那张图发 /edit 找得到投稿
- 回复机器人的“已加到你之前的投稿里”“投稿已更新”发 /edit 也找得到投稿
- 说明里写 /edit 的相册：只改文字，回复里说明图片没用上，其余几张不会变成新投稿
- 用相册直接回复审核员的消息（没写 /msg）：提醒用 /msg，不当成新投稿

用法（项目根目录下）：python tests/live_user_find_test.py
复用 live_test.py 的模拟 Bot API 服务器。
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import live_test as lt  # noqa: E402
from live_media_test import photo, user_photo  # noqa: E402
from live_test import BOB, REVIEW, USER, buttons, check, gm, is_send, log, wait_for  # noqa: E402

UPDATED = "投稿已更新"


def own(mid):
    return {"message_id": mid, "date": lt.now(), "chat": lt.chat(USER)}


def bot_reply(mid):
    return {"message_id": mid, "date": lt.now(), "chat": lt.chat(USER),
            "from": {"id": lt.BOT_ID, "is_bot": True, "first_name": "TestBot"}}


def new_drafts(since):
    return [e for e in log[since:] if any(is_send(e, "sendMessage", USER, p) for p in lt.PROMPTS)]


async def user_edit(text, reply):
    """投稿人回复 reply 发 /edit，返回机器人的回复。"""
    n = len(log); lt.pm(text, reply_to_message=reply)
    return await wait_for(lambda e: is_send(e, "sendMessage", USER), since=n)


async def scenario():
    await wait_for(lambda e: e["method"] == "setMyCommands", 15, since=0)
    n = len(log); text_mid = lt.pm("原文字")
    await wait_for(lambda e: any(is_send(e, "sendMessage", USER, p) for p in lt.PROMPTS), since=n)
    lt.cb("u:sign:1", USER, USER)
    ctrl = (await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, lt.CTRL), since=n))["result"]["message_id"]
    await asyncio.sleep(0.5)

    # 纯文字投稿加图
    n = len(log); pic = user_photo("P1", reply_to=text_mid)
    draft = await wait_for(lambda e: is_send(e, "sendMessage", USER) and "um:merge" in str(e["params"]), since=n)
    merged_msg = draft and draft["result"]["message_id"]
    n = len(log); lt.cb(buttons(draft).get("➕ 加到这条投稿", "") if draft else "", USER, USER, message_id=merged_msg)
    await wait_for(lambda e: e["method"] == "answerCallbackQuery" and "已添加" in e["params"].get("text", ""), since=n)
    await asyncio.sleep(0.5)

    r = await user_edit("/edit 回复已添加改的", bot_reply(merged_msg))
    check("/edit replying to “Added to your earlier submission” → finds the submission",
          r and UPDATED in r["params"]["text"], r and r["params"]["text"])
    done = r and r["result"]["message_id"]

    r = await user_edit("/edit 回复投稿已更新改的", bot_reply(done))
    check("/edit replying to the bot's “Updated” reply → finds the submission",
          r and UPDATED in r["params"]["text"], r and r["params"]["text"])

    n = len(log)
    lt.push(edited_message={"message_id": pic, "date": lt.now() - 5, "edit_date": lt.now(), "chat": lt.chat(USER),
                            "from": {"id": USER, "is_bot": False, "first_name": "Alice"}, "photo": photo("P2")})
    p = await wait_for(lambda e: e["method"] == "sendPhoto" and str(e["params"].get("chat_id")) == str(REVIEW), since=n)
    check("Edit on the added photo → photo swapped, caption from the text message kept",
          p and p["params"]["photo"] == "P2" and "回复投稿已更新改的" in (p["params"].get("caption") or ""),
          p and p["params"])

    r = await user_edit("/edit 回复图片改的", own(pic))
    check("/edit replying to the added photo → finds the pending submission (not the cancelled draft)",
          r and UPDATED in r["params"]["text"], r and r["params"]["text"])

    # 说明里写 /edit 的相册（换 Bob：Alice 一分钟内已经改了 5 次，再改会被频率限制拦下；Bob 是英文客户端）
    n = len(log); bob_mid = lt.pm("Bob text", who=BOB)
    await wait_for(lambda e: any(is_send(e, "sendMessage", BOB, p) for p in lt.PROMPTS), since=n)
    lt.cb("u:sign:3", BOB, BOB)
    await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, lt.CTRL), since=n)
    n = len(log)
    lt.pm(None, who=BOB, reply_to_message={**own(bob_mid), "chat": lt.chat(BOB)}, media_group_id="ge",
          photo=photo("E1"), caption="/edit album text")
    lt.pm(None, who=BOB, media_group_id="ge", photo=photo("E2"))
    r = await wait_for(lambda e: is_send(e, "sendMessage", BOB, "weren't used"), since=n)
    await asyncio.sleep(1)
    check("album captioned /edit → text changed, says the 2 photos weren't used, no new draft",
          r and "Updated" in r["params"]["text"] and "The 2 photo" in r["params"]["text"]
          and not [e for e in log[n:] if any(is_send(e, "sendMessage", BOB, p) for p in lt.PROMPTS)],
          r and r["params"]["text"])

    # 用相册直接回复审核员的消息
    n = len(log); gm("/msg 请补充图片", reply_to=ctrl)
    relay = await wait_for(lambda e: is_send(e, "sendMessage", USER, "请补充图片"), since=n)
    n = len(log)
    for fid in ("R1", "R2"):
        user_photo(fid, reply_to=relay["result"]["message_id"], group="gr")
    hint = await wait_for(lambda e: is_send(e, "sendMessage", USER, "/msg"), since=n)
    await asyncio.sleep(1)
    hints = [e for e in log[n:] if is_send(e, "sendMessage", USER, "/msg")]
    check("album replying to a reviewer message → one /msg hint, no new draft",
          hint and len(hints) == 1 and not new_drafts(n), [e["params"].get("text") for e in log[n:]])


if __name__ == "__main__":
    asyncio.run(lt.main(scenario, {"REMINDER_INTERVAL_MINUTES": "0"}))
