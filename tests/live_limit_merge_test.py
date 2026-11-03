"""投稿人未处理投稿到了上限（MAX_PENDING_PER_USER）时：
- 再发新投稿 → 被拦，提示稍后再投
- 回复自己的投稿发图 → 照常给“加到这条投稿”，点了能加进去（不占新名额）
- 这份草稿改点“署名 / 匿名”当新投稿提交 → 按上限拦，草稿留着，还能加到投稿里

用法（项目根目录下）：python tests/live_limit_merge_test.py
复用 live_test.py 的模拟 Bot API 服务器。约 10 秒。
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import live_test as lt  # noqa: E402
from live_media_test import previews, toast, user_photo  # noqa: E402
from live_test import REVIEW, USER, buttons, check, is_send, log, wait_for  # noqa: E402

TOO_MANY = "较多投稿"


async def scenario():
    await wait_for(lambda e: e["method"] == "setMyCommands", 15, since=0)
    n = len(log); mid = user_photo("A")
    await wait_for(lambda e: any(is_send(e, "sendMessage", USER, p) for p in lt.PROMPTS), since=n)
    lt.cb("u:sign:1", USER, USER)
    await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, lt.CTRL), since=n)
    await asyncio.sleep(0.5)

    n = len(log); user_photo("NEW")
    r = await wait_for(lambda e: is_send(e, "sendMessage", USER), since=n)
    check("at the limit, a new submission → refused", r and TOO_MANY in r["params"]["text"], r and r["params"]["text"])

    n = len(log); user_photo("MORE", reply_to=mid)
    draft = await wait_for(lambda e: is_send(e, "sendMessage", USER), since=n)
    kb = buttons(draft) if draft else {}
    check("at the limit, a photo replying to the submission → offered Add to that submission",
          "➕ 加到这条投稿" in kb, draft and draft["params"]["text"])

    n = len(log); lt.cb(kb.get("署名投稿") or next((v for v in kb.values() if v.startswith("u:sign")), ""), USER, USER,
                        message_id=draft and draft["result"]["message_id"])
    t = await toast(n, TOO_MANY)
    await asyncio.sleep(0.5)
    check("submitting that draft as a new one → refused by the limit, nothing sent to review",
          t and not previews(n, 1), t and t["params"])

    n = len(log); lt.cb(kb.get("➕ 加到这条投稿", ""), USER, USER, message_id=draft and draft["result"]["message_id"])
    t = await toast(n, "已添加")
    p = await wait_for(lambda e: e["method"] == "sendMediaGroup" and str(e["params"].get("chat_id")) == str(REVIEW),
                       since=n)
    check("Add to that submission → added, review group gets the 2-photo preview",
          t and p and [m["media"] for m in p["params"]["media"]] == ["A", "MORE"], p and p["params"]["media"])


if __name__ == "__main__":
    asyncio.run(lt.main(scenario, {"REMINDER_INTERVAL_MINUTES": "0", "MAX_PENDING_PER_USER": "1"}))
