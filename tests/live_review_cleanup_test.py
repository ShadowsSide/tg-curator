"""审核群里改稿留下的消息，清理时的几种边界：
- 整批删除失败（机器人不是管理员时删不了审核员的消息，Telegram 让整批失败）→ 逐条删，至少删掉机器人自己发的
- 删除被封禁用户的稿件时，最近一次改稿留下的消息（审核员改过的文字、确认）也一起删掉
- 确认封禁期间这条投稿被别人处理了（拒绝）→ 封禁照样生效，控制按钮消息收起确认面板

用法（项目根目录下）：python tests/live_review_cleanup_test.py
复用 live_test.py 的模拟 Bot API 服务器。
常规的“只留最近一次”见 live_edit_cleanup_test.py。
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import live_test as lt  # noqa: E402
from live_test import ADMIN, REVIEW, buttons, check, edit_cmd, gm, is_send, log, review_deleted, submit, wait_for  # noqa: E402


async def scenario():
    await wait_for(lambda e: e["method"] == "setMyCommands", 15, since=0)
    ctrl = (await submit("清理边界", 1))["result"]["message_id"]

    # 1. 整批删除失败 → 逐条删
    first = await edit_cmd("/edit 第一次", ctrl)
    # 第一次失败给删旧预览（改稿时先删），第二次给删上一次改稿的消息
    lt.MOCK["fail"][f"deleteMessages:{REVIEW}"] = ["Bad Request: message can't be deleted"] * 2
    n = len(log); await edit_cmd("/edit 第二次", ctrl)
    singles = [int(e["params"]["message_id"]) for e in log[n:] if e["method"] == "deleteMessage" and not e.get("error")]
    check("batch delete fails → previous edit's messages deleted one by one", sorted(singles) == sorted(first),
          (singles, first))

    # 2. 封禁后删除稿件：最近一次改稿的消息也删掉
    latest = await edit_cmd("/edit 第三次", ctrl)
    await lt.press("r:ban_ok:1:0", REVIEW, ADMIN, message_id=ctrl)
    n = len(log); lt.cb("r:purge_ok:1:0", REVIEW, ADMIN, message_id=ctrl)
    await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, "已删除"), since=n)  # 按钮先回应，删完才发结果
    check("purge → the latest edit's messages (reviewer's /edit and the confirmation) deleted too",
          set(latest) <= set(review_deleted(n)), (latest, review_deleted(n)))

    # 3. 确认封禁期间被别人拒绝了：封禁照样生效，确认面板收起
    ctrl2 = (await submit("封禁确认", 2, who=lt.BOB))["result"]["message_id"]
    n = len(log); lt.cb("r:ban:2:0", REVIEW, ADMIN, message_id=ctrl2)
    await wait_for(lambda e: e["method"] == "editMessageReplyMarkup" and str(e["params"].get("message_id")) == str(ctrl2),
                   since=n)
    n = len(log); gm("/no", reply_to=ctrl2)
    await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, "已拒绝"), since=n)
    n = len(log); lt.cb("r:ban_ok:2:0", REVIEW, ADMIN, message_id=ctrl2)
    refreshed = await wait_for(lambda e: e["method"] == "editMessageText"
                               and str(e["params"].get("message_id")) == str(ctrl2), since=n)
    kb = buttons(refreshed) if refreshed else {}
    check("ban confirmed after someone else rejected it → control panel message refreshed, shows 🔓",
          "🔓 解除封禁" in kb and not any(v.endswith("_ok:2:0") for v in kb.values()), kb)


if __name__ == "__main__":
    asyncio.run(lt.main(scenario, {"REMINDER_INTERVAL_MINUTES": "0"}))
