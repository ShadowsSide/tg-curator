"""投稿人这边的完整预览：私聊里只有他当初发的那几条，改完看不出投稿现在的样子。
- 投稿人每次改稿成功（/edit、原生编辑、删图）后收到当前完整内容（发布时的样子，带落款；草稿不带），旧的那份删掉
- 只发 /edit：发完整预览；还能改时另发文字方便复制，审核开始后只发预览并说明
- 回复这份预览发 /msg 也能找到这条投稿

用法（项目根目录下）：python tests/live_user_preview_test.py
复用 live_test.py 的模拟 Bot API 服务器。
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import live_test as lt  # noqa: E402
from live_media_test import buttons, kb_edit, photo, user_photo  # noqa: E402
from live_test import ADMIN, CHANNEL, REVIEW, USER, check, is_send, log, own, wait_for  # noqa: E402

SIG = "via Alice"



def captions(e):
    if e["method"] == "sendMediaGroup":
        return [m.get("caption") or "" for m in e["params"]["media"]]
    return [e["params"].get("caption") or ""]


def ids(e):
    return [m["message_id"] for m in e["result"]] if isinstance(e["result"], list) else [e["result"]["message_id"]]


async def scenario():
    await wait_for(lambda e: e["method"] == "setMyCommands", 15, since=0)

    # 草稿阶段原生编辑：预览不带落款（还没选署名 / 匿名）
    n = len(log)
    mids = [user_photo(f, group="g") for f in ("A", "B", "C")]
    draft = await wait_for(lambda e: any(is_send(e, "sendMessage", USER, p) for p in lt.PROMPTS), since=n)
    prompt = draft["result"]["message_id"]
    n = len(log)
    lt.push(edited_message={"message_id": mids[0], "date": lt.now() - 5, "edit_date": lt.now(), "chat": lt.chat(USER),
                            "from": {"id": USER, "is_bot": False, "first_name": "Alice"}, "media_group_id": "g",
                            "photo": photo("A"), "caption": "草稿说明"})
    p = await wait_for(lambda e: is_send(e, "sendMediaGroup", USER), since=n)
    check("draft edit → full preview without a signature", p and captions(p)[0] == "草稿说明", p and captions(p))

    # 提交后 /edit：预览带落款，上一份删掉
    n = len(log); lt.cb("u:sign:1", USER, USER)
    await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, lt.CTRL), since=n)
    old = ids(p)
    n = len(log); lt.pm("/edit 提交后的说明", reply_to_message=own(mids[0]))
    p = await wait_for(lambda e: is_send(e, "sendMediaGroup", USER, "提交后的说明"), since=n)
    gone = await wait_for(lambda e: e["method"] == "deleteMessages" and str(e["params"].get("chat_id")) == str(USER)
                          and e["params"]["message_ids"] == old, since=n)
    check("pending /edit → preview as it'll be published (signed), old preview deleted",
          p and SIG in captions(p)[0] and gone, p and captions(p))

    # 回复这份预览发 /msg：能找到投稿
    n = len(log); lt.pm("/msg 看预览后的留言", reply_to_message={**own(ids(p)[1]), "from": {"id": 1, "is_bot": True,
                                                                                         "first_name": "TestBot"}})
    relayed = await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, "看预览后的留言"), since=n)
    check("/msg replying to the preview → relayed to the reviewers", relayed)

    # 只发 /edit（还能改）：预览 + 供复制的文字 + 提示
    n = len(log); lt.pm("/edit", reply_to_message=own(mids[0]))
    pv = await wait_for(lambda e: is_send(e, "sendMediaGroup", USER), since=n)
    text = await wait_for(lambda e: is_send(e, "sendMessage", USER, "提交后的说明"), since=n)
    hint = await wait_for(lambda e: is_send(e, "sendMessage", USER, "复制、修改后"), since=n)
    check("bare /edit while editable → full preview, then the text to copy", pv and text and hint)

    # 删图：预览少一张
    n = len(log); lt.cb("um:mdel:1:0", USER, USER, message_id=prompt)
    panel = await kb_edit(USER, n)
    n = len(log); lt.cb(buttons(panel).get("🗑 删第 3 个", "") if panel else "", USER, USER, message_id=prompt)
    p = await wait_for(lambda e: is_send(e, "sendMediaGroup", USER), since=n)
    check("remove a photo → preview has the other 2", p and [m["media"] for m in p["params"]["media"]] == ["A", "B"],
          p and p["params"]["media"])

    # 删掉的那张还留在投稿人的聊天里：回复它只发 /edit 也找得到投稿；原生编辑它不会把它加回来
    n = len(log); lt.pm("/edit", reply_to_message=own(mids[2]))
    pv = await wait_for(lambda e: is_send(e, "sendMediaGroup", USER), since=n)
    check("bare /edit replying to the removed photo → still finds the submission",
          pv and [m["media"] for m in pv["params"]["media"]] == ["A", "B"], pv and pv["params"]["media"])
    n = len(log)
    lt.push(edited_message={"message_id": mids[2], "date": lt.now() - 5, "edit_date": lt.now(), "chat": lt.chat(USER),
                            "from": {"id": USER, "is_bot": False, "first_name": "Alice"}, "media_group_id": "g",
                            "photo": photo("C2")})
    await asyncio.sleep(1)
    check("native edit of the removed photo → ignored, not added back",
          not [e for e in log[n:] if str(e["params"].get("chat_id")) == str(REVIEW) and e["method"].startswith("send")
               and "#审核统计" not in str(e["params"])])

    # 发布后只发 /edit：只发预览，说明不能再改
    n = len(log); lt.cb(await lt.pub_ok(1), REVIEW, ADMIN)
    await wait_for(lambda e: is_send(e, "sendMediaGroup", CHANNEL), since=n)
    n = len(log); lt.pm("/edit", reply_to_message=own(mids[0]))
    pv = await wait_for(lambda e: is_send(e, "sendMediaGroup", USER), since=n)
    hint = await wait_for(lambda e: is_send(e, "sendMessage", USER, "审核已经开始"), since=n)
    await asyncio.sleep(0.3)
    check("bare /edit after publishing → preview only, says it can't be changed",
          pv and hint and not [e for e in log[n:] if is_send(e, "sendMessage", USER, "复制、修改后")])


if __name__ == "__main__":
    asyncio.run(lt.main(scenario, {"REMINDER_INTERVAL_MINUTES": "0"}))
