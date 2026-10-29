"""修改媒体：审核员的 🖼 媒体面板（添加 / 替换 / 删除，相册），投稿人“加到这条投稿”和删除自己的图片。

用法（项目根目录下）：python tests/live_media_test.py
复用 live_test.py 的模拟 Bot API 服务器。约 20 秒。
"""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import live_test as lt  # noqa: E402
from live_test import ADMIN, REVIEW, USER, buttons, check, is_send, log, submit, wait_for  # noqa: E402


def photo(fid):
    return [{"file_id": fid, "file_unique_id": fid, "width": 10, "height": 10}]


def bot_msg(chat_id, message_id):
    return {"message_id": message_id, "date": lt.now(), "chat": lt.chat(chat_id),
            "from": {"id": 1, "is_bot": True, "first_name": "TestBot"}}


def admin_media(reply_to, group=None, text=None, **media):
    """审核员在审核群回复一条机器人的消息，发图片 / 视频 / 文字。"""
    d = {"message_id": 7000 + lt.uid[0], "date": lt.now(), "chat": lt.chat(REVIEW),
         "from": {"id": ADMIN, "is_bot": False, "first_name": "Admin"},
         "reply_to_message": bot_msg(REVIEW, reply_to), **media}
    if text:
        d["text"] = text
    if group:
        d["media_group_id"] = group
    lt.push(message=d)


def user_photo(fid, reply_to=None, group=None):
    extra = {"photo": photo(fid)}
    if reply_to:
        extra["reply_to_message"] = bot_msg(USER, reply_to)
    if group:
        extra["media_group_id"] = group
    return lt.pm(None, **extra)


def previews(since, n_items):
    """since 之后发到审核群、含 n_items 项的预览（单张用 sendPhoto / sendVideo，多张用 sendMediaGroup）。"""
    out = []
    for e in log[since:]:
        if e.get("error") or str(e["params"].get("chat_id")) != str(REVIEW):
            continue
        if e["method"] == "sendMediaGroup" and len(media_of(e)) == n_items:
            out.append(e)
        elif n_items == 1 and e["method"] in ("sendPhoto", "sendVideo"):
            out.append(e)
    return out


def media_of(e):
    m = e["params"]["media"]
    return json.loads(m) if isinstance(m, str) else m


def group_ids(e):
    return [m["media"] for m in media_of(e)]


def kb_edit(chat_id, since):
    return wait_for(lambda e: e["method"] == "editMessageReplyMarkup" and str(e["params"].get("chat_id")) == str(chat_id),
                    since=since)


def toast(since, contains):
    return wait_for(lambda e: e["method"] == "answerCallbackQuery" and contains in e["params"].get("text", ""),
                    since=since)


async def ask(action, sid, ctrl_id, marker):
    n = len(log); lt.cb(f"r:{action}:{sid}:0" if ":" not in action else f"r:{action}", REVIEW, ADMIN, message_id=ctrl_id)
    return await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, marker)
                          and "force_reply" in json.dumps(e["params"]), since=n)


async def scenario():
    await wait_for(lambda e: e["method"] == "setMyCommands", 15, since=0)

    # ===== 审核员 =====
    c1 = await submit("媒体测试 文字", 1)
    ctrl1 = c1["result"]["message_id"]
    check("pending control message has 🖼 Media", buttons(c1).get("🖼 媒体") == "r:media:1:0", buttons(c1))

    # 1. 纯文字投稿的面板：只有“添加”和“返回”
    n = len(log); lt.cb("r:media:1:0", REVIEW, ADMIN, message_id=ctrl1)
    panel = await kb_edit(REVIEW, n)
    check("text submission → panel offers only Add + Back",
          panel and buttons(panel) == {"➕ 添加图片 / 视频": "r:madd:1:0", "« 返回": "r:back:1:0"}, panel and buttons(panel))

    # 2. 添加一张图：文字变成图片的说明
    p = await ask("madd", 1, ctrl1, "要添加的图片")
    n = len(log); admin_media(p["result"]["message_id"], photo=photo("A1"))
    done = await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, "已修改"), since=n)
    pv = [e for e in previews(n, 1) if e["method"] == "sendPhoto"]
    check("Add a photo to a text submission → photo preview with the text as caption",
          done and pv and pv[0]["params"]["photo"] == "A1" and "媒体测试 文字" in pv[0]["params"].get("caption", ""))

    # 3. 再加一个相册（两张，每张都回复了提示）：一共 3 张
    p = await ask("madd", 1, ctrl1, "要添加的图片")
    n = len(log)
    admin_media(p["result"]["message_id"], group="ga", photo=photo("A2"))
    admin_media(p["result"]["message_id"], group="ga", photo=photo("A3"))
    done = await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, "已修改"), since=n)
    await asyncio.sleep(0.3)
    pv = previews(n, 3)
    edits = [e for e in log[n:] if is_send(e, "sendMessage", REVIEW, "已修改")]
    check("Add an album → handled once, preview has all 3",
          done and len(edits) == 1 and pv and group_ids(pv[0]) == ["A1", "A2", "A3"], pv and group_ids(pv[0]))

    # 4. 删除第 2 个：先确认
    n = len(log); lt.cb("r:media:1:0", REVIEW, ADMIN, message_id=ctrl1)
    panel = await kb_edit(REVIEW, n)
    b = buttons(panel) if panel else {}
    check("3 photos → Replace 1-3 and Remove 1-3",
          b.get("🔁 换第 3 个") == "r:mrep:1:3" and b.get("🗑 删第 2 个") == "r:mrm:1:2" and len(b) == 8, b)
    n = len(log); lt.cb("r:mrm:1:2", REVIEW, ADMIN, message_id=ctrl1)
    confirm = await kb_edit(REVIEW, n)
    check("Remove → confirm panel naming the item",
          confirm and buttons(confirm).get("🗑 确认删除：第 2 个") == "r:mrm_ok:1:2", confirm and buttons(confirm))
    n = len(log); lt.cb("r:mrm_ok:1:2", REVIEW, ADMIN, message_id=ctrl1)
    t = await toast(n, "已删除第 2 个")
    await wait_for(lambda e: e["method"] == "sendMediaGroup", since=n)
    pv = previews(n, 2)
    check("confirm → removed, preview has the other 2", t and pv and group_ids(pv[0]) == ["A1", "A3"])

    # 5. 替换第 1 个：发文字不行（提示保留），再发视频
    p = await ask("mrep:1:1", 1, ctrl1, "换掉第 1 个")
    n = len(log); admin_media(p["result"]["message_id"], text="不是图片")
    err = await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, "只能添加图片或视频"), since=n)
    n = len(log)
    admin_media(p["result"]["message_id"], video={"file_id": "V1", "file_unique_id": "V1", "width": 1, "height": 1,
                                                  "duration": 1})
    await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, "已修改"), since=n)
    pv = previews(n, 2)
    media = media_of(pv[0]) if pv else []
    check("Replace with text → error, prompt kept; with a video → swapped, caption kept",
          err and media and media[0]["media"] == "V1" and media[0]["type"] == "video"
          and "媒体测试 文字" in media[0].get("caption", ""), media)

    # 6. 审核开始后（已发布）不能改：旧按钮提示原因
    c2 = await submit("媒体测试 二", 2)
    n = len(log); lt.cb("r:pub_ok:2:0", REVIEW, ADMIN, message_id=c2["result"]["message_id"])
    await wait_for(lambda e: is_send(e, "sendMessage", lt.CHANNEL, "媒体测试 二"), since=n)
    n = len(log); lt.cb("r:media:2:0", REVIEW, ADMIN, message_id=c2["result"]["message_id"])
    t = await toast(n, "只有待审核")
    check("Media on a published submission → refused with a reason", t and t["params"].get("show_alert"))

    # ===== 投稿人 =====
    # 7. 两张图的相册投稿：草稿和提交后的消息上都有“删除图片”
    n = len(log); user_photo("U1", group="gu"); user_photo("U2", group="gu")
    draft = await wait_for(lambda e: is_send(e, "sendMessage", USER, "请选择投稿方式"), since=n)
    check("album draft → Remove photo button", draft and buttons(draft).get("🗑 删除图片 / 视频") == "um:mdel:3:0",
          draft and buttons(draft))
    n = len(log); lt.cb("u:sign:3", USER, USER, message_id=draft["result"]["message_id"])
    sent = await wait_for(lambda e: e["method"] == "editMessageText" and str(e["params"].get("chat_id")) == str(USER),
                          since=n)
    check("submitted message keeps the Remove photo button",
          sent and buttons(sent) == {"🗑 删除图片 / 视频": "um:mdel:3:0"}, sent and buttons(sent))
    user_prompt = draft["result"]["message_id"]

    # 8. 回复自己的投稿再发一张：可以“加到这条投稿”
    n = len(log); user_photo("U3", reply_to=user_prompt)
    ask_merge = await wait_for(lambda e: is_send(e, "sendMessage", USER, "请选择投稿方式"), since=n)
    b = buttons(ask_merge) if ask_merge else {}
    check("reply to own submission with a photo → “Add to that submission” offered",
          b.get("➕ 加到这条投稿") == "um:merge:4:3" and "u:sign:4" in b.values()
          and "加到你回复的那条投稿" in ask_merge["params"]["text"], b)
    n = len(log); lt.cb("um:merge:4:3", USER, USER, message_id=ask_merge["result"]["message_id"])
    merged = await wait_for(lambda e: e["method"] == "editMessageText" and "已加到" in e["params"].get("text", ""),
                            since=n)
    await wait_for(lambda e: e["method"] == "sendMediaGroup", since=n)
    pv = previews(n, 3)
    check("merge → the earlier submission gets the photo, reviewers see a new preview",
          merged and pv and group_ids(pv[0]) == ["U1", "U2", "U3"], pv and group_ids(pv[0]))

    # 9. 投稿人删掉第 1 张（不需要确认）
    n = len(log); lt.cb("um:mdel:3:0", USER, USER, message_id=user_prompt)
    panel = await kb_edit(USER, n)
    check("Remove photo → numbered buttons + Back", panel and buttons(panel) == {
        "🗑 删第 1 个": "um:mrm:3:1", "🗑 删第 2 个": "um:mrm:3:2", "🗑 删第 3 个": "um:mrm:3:3", "« 返回": "um:mback:3:0"},
        panel and buttons(panel))
    n = len(log); lt.cb("um:mrm:3:1", USER, USER, message_id=user_prompt)
    t = await toast(n, "已删除第 1 个")
    await wait_for(lambda e: e["method"] == "sendMediaGroup", since=n)
    pv = previews(n, 2)
    restored = await kb_edit(USER, n)
    check("submitter removes no. 1 → reviewers see 2, buttons restored",
          t and pv and group_ids(pv[0]) == ["U2", "U3"] and restored
          and buttons(restored) == {"🗑 删除图片 / 视频": "um:mdel:3:0"}, restored and buttons(restored))

    # 10. 审核员发布后，投稿人点旧按钮：说明原因并收起按钮
    n = len(log); lt.cb("r:pub_ok:3:0", REVIEW, ADMIN)
    await wait_for(lambda e: is_send(e, "sendMessage", USER, "已发布"), since=n)
    n = len(log); lt.cb("um:mdel:3:0", USER, USER, message_id=user_prompt)
    t = await toast(n, "审核已经开始或结束")
    gone = await kb_edit(USER, n)
    check("old Remove button after publishing → told why, buttons removed",
          t and gone and not buttons(gone), gone and gone["params"])


if __name__ == "__main__":
    asyncio.run(lt.main(scenario))
