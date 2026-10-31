"""相册后到的部分：同一个相册的几项分两批到达、第二批晚于 ALBUM_DELAY 时，并进同一条投稿，不再拆成两条：
- 还是草稿：加进草稿，原来那条“请选择投稿方式”改成新的数量，不再发新的提示；按相册里的顺序排列，说明文字保留
- 已提交、待审核：加进去，审核群收到修改后的预览，投稿人收到“已加进刚才的投稿”
- 前一部分的提示还没发出去（被限流）时后一部分到了：等前一部分处理完再并进去
- 并不进去（超过 10 项、已经发布）：单独成为一条新投稿，提示里说明原因
- 对照：同一次 getUpdates 里返回、间隔小于 ALBUM_DELAY，本来就是一条

用法（项目根目录下）：python tests/live_album_split_test.py
复用 live_test.py 的模拟 Bot API 服务器。约 40 秒。
"""
import asyncio
import json
import os
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import live_test as lt  # noqa: E402
from live_test import ADMIN, CHANNEL, CTRL, PROMPTS, REVIEW, USER, check, is_send, log, wait_for  # noqa: E402

DELAY = 1.0  # ALBUM_DELAY
DB = os.path.join(tempfile.mkdtemp(), "bot.db")
msg_id = [300]


def rows():
    with sqlite3.connect(DB) as conn:
        return [(sid, status, json.loads(items)) for sid, status, items in
                conn.execute("SELECT id, status, items FROM submissions ORDER BY id")]


def album(group, n, caption=None):
    """投稿人相册里的 n 项，放进同一次 getUpdates。返回这些消息的编号。"""
    ids = []
    for i in range(n):
        msg_id[0] += 1
        lt.uid[0] += 1
        lt.updates.append({"update_id": lt.uid[0], "message": {
            "message_id": msg_id[0], "date": lt.now(), "chat": lt.chat(USER), "media_group_id": group,
            "from": {"id": USER, "is_bot": False, "first_name": "Alice", "username": "alice", "language_code": "zh-hans"},
            "photo": [{"file_id": f"{group}-{msg_id[0]}", "file_unique_id": f"{group}-{msg_id[0]}", "width": 1, "height": 1}],
            **({"caption": caption} if caption and i == 0 else {})}})
        ids.append(msg_id[0])
    lt.new_update.set()
    return ids


def prompts(since):
    return [e for e in log[since:] if any(is_send(e, "sendMessage", USER, p) for p in PROMPTS)]


def prompt_edits(since):
    return [e["params"]["text"].split("。")[0] for e in log[since:]
            if e["method"] == "editMessageText" and str(e["params"].get("chat_id")) == str(USER)]


async def settle():
    await asyncio.sleep(DELAY + 1.5)


async def draft_case(name, gap, split=6):
    """分两批（split 项 + 其余）发 7 项，gap 秒后发第二批；gap=None 表示 7 项一次到达。最后应该只有一条 7 项的草稿。"""
    before, n = len(rows()), len(log)
    first = album(f"g-{name}", split if gap is not None else 7, caption="seven")
    if gap is not None:
        await asyncio.sleep(gap)
        album(f"g-{name}", 7 - split)
    await settle()
    new = rows()[before:]
    ids = [it["msg_id"] for it in new[0][2]] if new else []
    check(f"{name}: one draft with all 7 photos in album order, caption kept, one prompt",
          len(new) == 1 and len(new[0][2]) == 7 and ids == sorted(ids) and ids[0] == first[0]
          and new[0][2][0].get("text") == "seven" and len(prompts(n)) == 1,
          ([(s, st, len(it)) for s, st, it in new], len(prompts(n))))
    if gap is not None and gap > DELAY:  # 间隔小于 ALBUM_DELAY 时本来就一起收齐，不用改提示
        edits = prompt_edits(n)
        check(f"{name}: the prompt now says 7 photos", edits and "7 张图片" in edits[-1], edits)
    return new[0][0] if new else None


async def scenario():
    await wait_for(lambda e: e["method"] == "setMyCommands", 15, since=0)
    await asyncio.sleep(0.3)

    # 对照：本来就是一条
    await draft_case("same batch", None)
    await draft_case("gap 0.5x", 0.5 * DELAY)
    # 晚于 ALBUM_DELAY：以前会拆成 6 + 1 两条草稿、两次提示
    await draft_case("gap 1.5x", 1.5 * DELAY)
    await draft_case("gap 3x", 3 * DELAY)

    # 前一部分的提示被限流、还没发出去时后一部分就到了：等它发出去再改成 7 张
    lt.MOCK["flood"][f"sendMessage:{USER}"] = [2]
    await draft_case("late part while the prompt is rate-limited", 1.5 * DELAY)

    # 已提交、待审核：并进去，审核群收到 7 张的新预览，告诉投稿人
    before, n = len(rows()), len(log)
    album("g-pending", 6, caption="pending")
    await settle()
    sid = rows()[before][0]
    lt.cb(f"u:sign:{sid}", USER, USER)
    await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, CTRL), since=n)
    n = len(log)
    album("g-pending", 1)
    preview = await wait_for(lambda e: is_send(e, "sendMediaGroup", REVIEW), since=n)
    told = await wait_for(lambda e: is_send(e, "sendMessage", USER, "已加进刚才的投稿"), since=n)
    await settle()
    new = rows()[before:]
    check("pending: late photo added, review group gets a 7-photo preview, submitter told, no new draft",
          len(new) == 1 and new[0][1] == "pending" and len(new[0][2]) == 7 and preview
          and len(preview["params"]["media"]) == 7 and told and not prompts(n),
          ([(s, st, len(it)) for s, st, it in new], told and told["params"]["text"]))

    # 并不进去：超过 10 项 → 单独成为一条，说明原因
    before, n = len(rows()), len(log)
    album("g-full", 6)
    await settle()
    n = len(log)
    album("g-full", 5)
    await settle()
    new = rows()[before:]
    p = prompts(n)
    check("over 10 photos: the late part becomes its own draft and the prompt says why",
          [len(it) for _, _, it in new] == [6, 5] and len(p) == 1 and "没能加进原来的投稿" in p[0]["params"]["text"]
          and "最多 10 个" in p[0]["params"]["text"], ([len(it) for _, _, it in new], [e["params"]["text"] for e in p]))

    # 并不进去：原来的投稿已经发布 → 单独成为一条
    before, n = len(rows()), len(log)
    album("g-published", 6)
    await settle()
    sid = rows()[before][0]
    lt.cb(f"u:sign:{sid}", USER, USER)
    await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, CTRL), since=n)
    lt.cb(f"r:pub_ok:{sid}:0", REVIEW, ADMIN)
    await wait_for(lambda e: is_send(e, "sendMediaGroup", CHANNEL), since=n)
    n = len(log)
    album("g-published", 1)
    await settle()
    new = rows()[before:]
    p = prompts(n)
    check("already published: the late part becomes its own draft and the prompt says why",
          [(st, len(it)) for _, st, it in new] == [("published", 6), ("draft", 1)] and len(p) == 1
          and "已经发布" in p[0]["params"]["text"], ([(st, len(it)) for _, st, it in new], [e["params"]["text"] for e in p]))


if __name__ == "__main__":
    # 每种情况的草稿都留着，MAX_PENDING_PER_USER 调大，免得碰到上限
    asyncio.run(lt.main(scenario, extra_env={"ALBUM_DELAY": str(DELAY), "DB_PATH": DB, "MAX_PENDING_PER_USER": "50"}))
