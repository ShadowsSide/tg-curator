"""剧透遮罩跟随投稿人的修改：
- 投稿人用 Telegram 自带的“编辑”给图片开 / 关剧透，控制消息上的剧透设置跟着变
- 只改说明文字（剧透没变）不覆盖审核员手动切换的结果
- 回复自己的投稿发一张带剧透的图并“加到这条投稿”，剧透也跟着打开

用法（项目根目录下）：python tests/live_spoiler_test.py
复用 live_test.py 的模拟 Bot API 服务器。约 10 秒。
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import live_test as lt  # noqa: E402
from live_test import ADMIN, REVIEW, USER, check, is_send, log, wait_for  # noqa: E402
from live_media_test import bot_msg, media_of, photo  # noqa: E402

ON, OFF = "剧透遮罩：🙈 开", "剧透遮罩：关"


def user_photo(fid, spoiler=False, caption=None, reply_to=None):
    extra = {"photo": photo(fid)}
    if spoiler:
        extra["has_media_spoiler"] = True
    if caption:
        extra["caption"] = caption
    if reply_to:
        extra["reply_to_message"] = bot_msg(USER, reply_to)
    return lt.pm(None, **extra)


def edit_photo(message_id, fid, spoiler, caption=""):
    """投稿人用 Telegram 自带的“编辑”改了之前发的图片（开关剧透 / 改说明）。"""
    d = {"message_id": message_id, "date": lt.now() - 5, "edit_date": lt.now(), "chat": lt.chat(USER),
         "from": {"id": USER, "is_bot": False, "first_name": "Alice", "username": "alice"},
         "photo": photo(fid), "caption": caption}
    if spoiler:
        d["has_media_spoiler"] = True
    lt.push(edited_message=d)


def ctrl_text(message_id, since):
    """since 之后这条控制消息被刷新后的文字。"""
    return wait_for(lambda e: e["method"] == "editMessageText" and str(e["params"].get("message_id")) == str(message_id)
                    and str(e["params"].get("chat_id")) == str(REVIEW), since=since)


async def submit_photo(fid, sid, **kw):
    n = len(log); mid = user_photo(fid, **kw)
    prompt = await wait_for(lambda e: is_send(e, "sendMessage", USER, "请选择投稿方式"), since=n)
    n = len(log); lt.cb(f"u:sign:{sid}", USER, USER, message_id=prompt["result"]["message_id"])
    ctrl = await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, "剧透遮罩"), since=n)
    return mid, prompt["result"]["message_id"], ctrl


async def scenario():
    await wait_for(lambda e: e["method"] == "setMyCommands", 15, since=0)

    # 1. 没带剧透的图片：默认关
    mid, _, ctrl = await submit_photo("P1", 1)
    cid = ctrl["result"]["message_id"]
    check("photo without spoiler → spoiler off", OFF in ctrl["params"]["text"], ctrl["params"]["text"])

    # 2. 投稿人编辑图片打开剧透 → 跟着开
    n = len(log); edit_photo(mid, "P1", spoiler=True)
    e = await ctrl_text(cid, n)
    check("submitter turns on the photo's spoiler → spoiler on", e and ON in e["params"]["text"], e and e["params"]["text"])

    # 3. 审核员手动关掉；投稿人只改说明（剧透没变）→ 保持关
    n = len(log); lt.cb("r:spoiler:1:0", REVIEW, ADMIN, message_id=cid)
    e = await ctrl_text(cid, n)
    check("reviewer turns spoiler off", e and OFF in e["params"]["text"], e and e["params"]["text"])
    n = len(log); edit_photo(mid, "P1", spoiler=True, caption="只改说明")
    e = await ctrl_text(cid, n)
    check("caption-only edit keeps the reviewer's choice (off)", e and OFF in e["params"]["text"] and "已修改" in
          e["params"]["text"], e and e["params"]["text"])

    # 4. 投稿人关掉剧透 → 关；再打开 → 开
    n = len(log); edit_photo(mid, "P1", spoiler=False, caption="只改说明")
    e = await ctrl_text(cid, n)
    check("submitter turns the photo's spoiler off → off", e and OFF in e["params"]["text"], e and e["params"]["text"])
    n = len(log); edit_photo(mid, "P1", spoiler=True, caption="只改说明")
    e = await ctrl_text(cid, n)
    check("submitter turns it on again → on", e and ON in e["params"]["text"], e and e["params"]["text"])

    # 5. 回复自己的投稿发一张带剧透的图，加到这条投稿 → 开
    _, prompt2, ctrl2 = await submit_photo("P2", 2)
    cid2 = ctrl2["result"]["message_id"]
    n = len(log); user_photo("P3", spoiler=True, reply_to=prompt2)
    ask = await wait_for(lambda e: is_send(e, "sendMessage", USER, "请选择投稿方式"), since=n)
    n = len(log); lt.cb("um:merge:3:2", USER, USER, message_id=ask["result"]["message_id"])
    e = await ctrl_text(cid2, n)
    check("add a spoilered photo to a submission → spoiler on", e and ON in e["params"]["text"], e and e["params"]["text"])

    # 6. 发布时按当前设置给媒体加剧透
    n = len(log); lt.cb("r:pub_ok:2:0", REVIEW, ADMIN, message_id=cid2)
    pub = await wait_for(lambda e: is_send(e, "sendMediaGroup", lt.CHANNEL), since=n)
    media = pub and media_of(pub)
    check("published album has the spoiler on every item", media and all(m.get("has_spoiler") for m in media), media)


if __name__ == "__main__":
    asyncio.run(lt.main(scenario))
