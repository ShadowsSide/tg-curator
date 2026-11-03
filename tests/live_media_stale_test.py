"""媒体按钮 / 提示上的序号带着内容版本：之后内容又被改过（序号可能已经指向另一张），就不执行，告诉对方先看新的预览。
- 审核员：打开面板后投稿人改了稿，再确认“删第 2 个” → 不删
- 审核员：升级前的旧按钮（只有序号）在内容改过之后 → 不删
- 审核员：“换第 1 个”的提示发出后内容被改过，再回复图片 → 不换
- 投稿人：删除面板打开后自己又改了稿，再点“删第 1 个” → 不删
- 内容没再改过时照常执行（另见 live_media_test）

用法（项目根目录下）：python tests/live_media_stale_test.py
复用 live_test.py 的模拟 Bot API 服务器。约 15 秒。
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import live_test as lt  # noqa: E402
from live_media_test import admin_media, ask, buttons, kb_edit, panel_button, photo, toast, user_photo  # noqa: E402
from live_test import ADMIN, REVIEW, USER, check, is_send, log, wait_for  # noqa: E402

STALE = "刚被改过"


def changed(since):
    """since 之后有没有发出新的预览（改稿会先发新预览）。"""
    return [e for e in log[since:] if not e.get("error") and str(e["params"].get("chat_id")) == str(REVIEW)
            and e["method"] in ("sendMediaGroup", "sendPhoto", "sendVideo")]


async def user_edit(text, mid):
    """投稿人回复自己投稿里的一张图发 /edit，改说明文字（内容版本加 1）。"""
    n = len(log); lt.pm(f"/edit {text}", reply_to_message={"message_id": mid, "date": lt.now(), "chat": lt.chat(USER)})
    await wait_for(lambda e: is_send(e, "sendMessage", USER, "已修改") or is_send(e, "sendMessage", USER, "已更新"),
                   since=n)
    await asyncio.sleep(0.3)


async def scenario():
    await wait_for(lambda e: e["method"] == "setMyCommands", 15, since=0)
    n = len(log)
    mids = [user_photo(f"P{i}", group="g") for i in (1, 2, 3)]
    draft = await wait_for(lambda e: any(is_send(e, "sendMessage", USER, p) for p in lt.PROMPTS), since=n)
    lt.cb("u:sign:1", USER, USER)
    ctrl = (await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, lt.CTRL), since=n))["result"]["message_id"]

    # 1. 审核员打开面板、点了“删第 2 个”，确认前投稿人改了稿
    rm2 = await panel_button(1, ctrl, "🗑 删第 2 个")
    await user_edit("第一次修改", mids[0])
    n = len(log); lt.cb(f"r:{rm2.replace('mrm:', 'mrm_ok:')}", REVIEW, ADMIN, message_id=ctrl)
    t = await toast(n, STALE)
    await asyncio.sleep(0.5)
    check("reviewer confirms remove after the content changed → refused, nothing removed",
          t and t["params"].get("show_alert") and not changed(n), t and t["params"])

    # 2. 升级前发出的旧按钮：v 只有序号（版本 0），内容早已改过
    n = len(log); lt.cb("r:mrm_ok:1:2", REVIEW, ADMIN, message_id=ctrl)
    t = await toast(n, STALE)
    await asyncio.sleep(0.5)
    check("old-style button after the content changed → refused, nothing removed", t and not changed(n))

    # 3. “换第 1 个”的提示发出后投稿人改了稿，再回复图片
    p = await ask(await panel_button(1, ctrl, "🔁 换第 1 个"), 1, ctrl, "换掉第 1 个")
    await user_edit("第二次修改", mids[0])
    n = len(log); admin_media(p["result"]["message_id"], photo=photo("NEW"))
    told = await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, STALE), since=n)
    await asyncio.sleep(0.5)
    check("reply to a replace prompt after the content changed → refused, nothing replaced",
          told and not changed(n), told and told["params"]["text"])

    # 4. 投稿人打开删除面板后又改了稿，再点旧面板上的“删第 1 个”
    n = len(log); lt.cb("um:mdel:1:0", USER, USER, message_id=draft["result"]["message_id"])
    panel = await kb_edit(USER, n)
    rm1 = buttons(panel).get("🗑 删第 1 个") if panel else None
    await user_edit("第三次修改", mids[0])
    n = len(log); lt.cb(rm1 or "", USER, USER, message_id=draft["result"]["message_id"])
    t = await toast(n, STALE)
    await asyncio.sleep(0.5)
    check("submitter removes from a panel opened before their own edit → refused, nothing removed",
          rm1 and t and not changed(n), rm1)

    # 5. 内容没再改过：照常删除
    rm1 = await panel_button(1, ctrl, "🗑 删第 1 个")
    n = len(log); lt.cb(f"r:{rm1.replace('mrm:', 'mrm_ok:')}", REVIEW, ADMIN, message_id=ctrl)
    t = await toast(n, "已删除第 1 个")
    await asyncio.sleep(0.3)
    check("fresh button → removed as usual", t and changed(n))


if __name__ == "__main__":
    asyncio.run(lt.main(scenario, {"REMINDER_INTERVAL_MINUTES": "0"}))
