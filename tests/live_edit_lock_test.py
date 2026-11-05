"""审核员改过稿之后，投稿人不能再改（/edit、原生编辑、加到这条投稿、删除图片都不行），只能 /msg：
- 审核员第一次改稿时通知投稿人一次（以后再改不通知），投稿人的“删除图片”按钮收起
- 投稿人改稿被拒，回复说明原因、指引 /msg；审核群收不到新预览
- 只发 /edit 查看当前内容不受影响；审核员只切换静音等开关不算改稿

用法（项目根目录下）：python tests/live_edit_lock_test.py
复用 live_test.py 的模拟 Bot API 服务器。
"""
import asyncio
import os
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import live_test as lt  # noqa: E402
from bot.media import media_ref  # noqa: E402
from live_media_test import buttons, photo, user_photo  # noqa: E402
from live_test import ADMIN, REVIEW, USER, check, gm, is_send, log, own, user_says, wait_for  # noqa: E402

DB = os.path.join(tempfile.mkdtemp(), "bot.db")
LOCKED = "审核员已经修改过"
NOTIFIED = "审核员修改了你的投稿"


def version(sid):
    with sqlite3.connect(DB) as conn:
        return conn.execute("SELECT version FROM submissions WHERE id=?", (sid,)).fetchone()[0]



def previews(since):
    return [e for e in log[since:] if not e.get("error") and str(e["params"].get("chat_id")) == str(REVIEW)
            and e["method"] in ("sendMediaGroup", "sendPhoto", "sendMessage") and "#审核统计" not in str(e["params"])
            and "已修改" not in str(e["params"])]



async def submit_album(sid, group, files):
    n = len(log)
    mids = [user_photo(f, group=group) for f in files]
    draft = await wait_for(lambda e: any(is_send(e, "sendMessage", USER, p) for p in lt.PROMPTS), since=n)
    lt.cb(f"u:sign:{sid}", USER, USER)
    ctrl = await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, lt.CTRL), since=n)
    await asyncio.sleep(0.5)
    return mids, draft["result"]["message_id"], ctrl["result"]["message_id"]


async def scenario():
    await wait_for(lambda e: e["method"] == "setMyCommands", 15, since=0)
    mids, prompt, ctrl = await submit_album(1, "g1", ["A", "B"])

    # 审核员改稿之前，投稿人能改
    r = await user_says("/edit 投稿人自己的说明", mids[0])
    check("before a reviewer edit → submitter can edit", r and "投稿已更新" in r["params"]["text"], r and r["params"]["text"])

    # 审核员第一次改稿：投稿人收到一次通知，“删除图片”收起
    n = len(log); gm("/edit 审核员改过的说明", reply_to=ctrl)
    note = await wait_for(lambda e: is_send(e, "sendMessage", USER, NOTIFIED), since=n)
    kb = await wait_for(lambda e: e["method"] == "editMessageReplyMarkup" and str(e["params"].get("chat_id")) == str(USER),
                        since=n)
    check("first reviewer edit → submitter notified, told about /msg and /edit",
          note and "/msg" in note["params"]["text"] and "/edit" in note["params"]["text"], note and note["params"]["text"])
    check("first reviewer edit → submitter's Remove photo button goes away",
          kb and not any(v.startswith("um:mdel") for v in buttons(kb).values()), kb and kb["params"])

    n = len(log); gm("/edit 审核员又改了一次", reply_to=ctrl)
    await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, "已修改"), since=n)
    await asyncio.sleep(0.5)
    check("later reviewer edits → no more notices",
          not [e for e in log[n:] if is_send(e, "sendMessage", USER, NOTIFIED)])

    # 投稿人的四种改法都被拒，审核群收不到新预览
    n = len(log)
    r = await user_says("/edit 想覆盖审核员", mids[0])
    check("/edit after a reviewer edit → refused, pointed to /msg",
          r and LOCKED in r["params"]["text"] and "/msg" in r["params"]["text"], r and r["params"]["text"])

    lt.push(edited_message={"message_id": mids[1], "date": lt.now() - 5, "edit_date": lt.now(), "chat": lt.chat(USER),
                            "from": {"id": USER, "is_bot": False, "first_name": "Alice"}, "media_group_id": "g1",
                            "photo": photo("B2"), "caption": "原生编辑"})
    r = await wait_for(lambda e: is_send(e, "sendMessage", USER, LOCKED), since=len(log) - 1)
    check("native edit after a reviewer edit → refused", r)

    m = len(log); user_photo("NEW", reply_to=mids[0])
    draft = await wait_for(lambda e: is_send(e, "sendMessage", USER) and "um:merge" in str(e["params"]), since=m)
    m = len(log); lt.cb(buttons(draft)["➕ 加到这条投稿"] if draft else "", USER, USER,
                        message_id=draft and draft["result"]["message_id"])
    t = await wait_for(lambda e: e["method"] == "answerCallbackQuery" and LOCKED in e["params"].get("text", ""), since=m)
    check("Add to that submission after a reviewer edit → refused", t, draft and buttons(draft))

    m = len(log); lt.cb(f"um:mrm:1:{media_ref(1, version(1))}", USER, USER, message_id=prompt)
    t = await wait_for(lambda e: e["method"] == "answerCallbackQuery" and LOCKED in e["params"].get("text", ""), since=m)
    check("Remove a photo after a reviewer edit → refused", t)
    await asyncio.sleep(0.5)
    check("nothing the submitter tried reached the review group", not previews(n), [e["method"] for e in previews(n)])

    # 只发 /edit 查看当前内容：不拦，发回完整预览（含审核员的修改），说明不能再改；不发供复制的文字
    n = len(log); lt.pm("/edit", reply_to_message=own(mids[0]))
    r = await wait_for(lambda e: is_send(e, "sendMediaGroup", USER, "审核员又改了一次"), since=n)
    hint = await wait_for(lambda e: is_send(e, "sendMessage", USER, "含审核员的修改"), since=n)
    check("bare /edit still shows the current content (full preview), says it's locked",
          r and hint and not [e for e in log[n:] if is_send(e, "sendMessage", USER, "审核员又改了一次")])

    # 审核员只切换静音：不算改稿，投稿人照样能改
    mids2, _, ctrl2 = await submit_album(3, "g2", ["C", "D"])
    n = len(log); lt.cb("r:silent:3:0", REVIEW, ADMIN, message_id=ctrl2)
    await wait_for(lambda e: e["method"] == "answerCallbackQuery", since=n)
    r = await user_says("/edit 开关之后改", mids2[0])
    check("reviewer only toggled Silent → submitter can still edit",
          r and "投稿已更新" in r["params"]["text"], r and r["params"]["text"])


if __name__ == "__main__":
    asyncio.run(lt.main(scenario, {"REMINDER_INTERVAL_MINUTES": "0", "DB_PATH": DB}))
