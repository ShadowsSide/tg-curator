"""审核员回复“添加 / 替换”提示发的相册，后几项晚于 ALBUM_DELAY 才到（前面的部分已经处理、提示已经删掉）：
- 添加：后到的部分接着加进去，不管带不带回复，回复“后到的 N 个也已加进去”
- 加进去会超过 10 个：回复原因，不加
- 替换：只能用一个，后到的部分不用，回复说明
- 别的审核员发的同号相册不算

用法（项目根目录下）：python tests/live_review_album_test.py
复用 live_test.py 的模拟 Bot API 服务器。约 30 秒。
"""
import asyncio
import json
import os
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import live_test as lt  # noqa: E402
from live_media_test import ask, bot_msg, photo  # noqa: E402
from live_test import ADMIN, REVIEW, check, is_send, log, submit, wait_for  # noqa: E402

DELAY = 1.0  # ALBUM_DELAY
DB = os.path.join(tempfile.mkdtemp(), "bot.db")
OTHER = 8  # 另一位审核员


def files(sid):
    with sqlite3.connect(DB) as conn:
        items = json.loads(conn.execute("SELECT items FROM submissions WHERE id=?", (sid,)).fetchone()[0])
    return [it.get("file_id") for it in items]


def media(group, fid, reply_to=None, who=ADMIN):
    """审核员在审核群发相册里的一项（reply_to：回复的提示）。"""
    d = {"message_id": 7000 + lt.uid[0], "date": lt.now(), "chat": lt.chat(REVIEW), "media_group_id": group,
         "from": {"id": who, "is_bot": False, "first_name": "Admin"}, "photo": photo(fid)}
    if reply_to:
        d["reply_to_message"] = bot_msg(REVIEW, reply_to)
    lt.push(message=d)


def replies(since):
    """since 之后机器人在审核群的回复（不算每分钟一次的统计提醒）。"""
    return [e["params"]["text"] for e in log[since:]
            if is_send(e, "sendMessage", REVIEW) and "#审核统计" not in e["params"]["text"]]


async def split_album(prompt_id, group, first, late, late_reply=True, late_from=ADMIN):
    """先发 first 几项（都回复了提示），隔 1.5 倍 ALBUM_DELAY 再发 late 几项。返回这段时间审核群里的回复。"""
    n = len(log)
    for fid in first:
        media(group, fid, prompt_id)
    await asyncio.sleep(1.5 * DELAY)
    for fid in late:
        media(group, fid, prompt_id if late_reply else None, who=late_from)
    await asyncio.sleep(DELAY + 1.5)
    return replies(n)


async def scenario():
    await wait_for(lambda e: e["method"] == "setMyCommands", 15, since=0)
    lt.MOCK["admins"].add(OTHER)

    # 添加，后到的那项带着回复 / 没带回复
    for sid, late_reply in ((1, True), (2, False)):
        ctrl = (await submit(f"相册 {sid}", sid))["result"]["message_id"]
        p = await ask("madd", sid, ctrl, "要添加的图片")
        got = await split_album(p["result"]["message_id"], f"g{sid}", ["A", "B"], ["C"], late_reply)
        check(f"add, late part {'with' if late_reply else 'without'} a reply → all 3 added, reviewer told",
              files(sid) == ["A", "B", "C"] and got[-1].startswith("✏️ 相册后到的 1 个也已加进去"), (files(sid), got))

    # 加进去会超过 10 个：不加，回复原因
    ctrl = (await submit("相册 3", 3))["result"]["message_id"]
    p = await ask("madd", 3, ctrl, "要添加的图片")
    got = await split_album(p["result"]["message_id"], "g3", list("ABCDEFGH"), list("XYZ"), late_reply=False)
    check("add, late part would exceed 10 → not added, reviewer told why",
          files(3) == list("ABCDEFGH") and got[-1].startswith("相册后到的 3 个没有加进去") and "最多 10 个" in got[-1], (files(3), got))

    # 替换：后到的部分不用
    p = await ask("mrep:3:1", 3, ctrl, "换掉第 1 个")
    got = await split_album(p["result"]["message_id"], "g4", ["R"], ["S"], late_reply=False)
    check("replace, late part → only the first one used, reviewer told the rest wasn't",
          files(3)[0] == "R" and "S" not in files(3) and "后到的 1 个没有使用" in got[-1], (files(3), got))

    # 别的审核员发的同号相册：不算
    ctrl = (await submit("相册 4", 4))["result"]["message_id"]
    p = await ask("madd", 4, ctrl, "要添加的图片")
    got = await split_album(p["result"]["message_id"], "g5", ["A"], ["B"], late_reply=False, late_from=OTHER)
    check("late part from another reviewer → ignored", files(4) == ["A"] and len(got) == 1, (files(4), got))


if __name__ == "__main__":
    asyncio.run(lt.main(scenario, extra_env={"ALBUM_DELAY": str(DELAY), "DB_PATH": DB}))
