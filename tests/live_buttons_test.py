"""其余审核按钮：🔁 重试发布、↩️ 取消定时（不需要二次确认）。

用法（项目根目录下）：python tests/live_buttons_test.py
发布失败用模拟服务器的失败注入（MOCK["fail"]）制造。复用 live_test.py 的模拟 Bot API 服务器。约 8 秒。
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import live_test as lt  # noqa: E402
from live_test import ADMIN, CHANNEL, REVIEW, buttons, check, is_send, log, submit, wait_for  # noqa: E402


def control_edit(ctrl, since, contains):
    mid = str(ctrl["result"]["message_id"])
    return wait_for(lambda e: e["method"] == "editMessageText" and str(e["params"].get("message_id")) == mid
                    and contains in e["params"]["text"], since=since)


def posts(since, text):
    return [e for e in log[since:] if is_send(e, "sendMessage", CHANNEL, text)]


async def scenario():
    await wait_for(lambda e: e["method"] == "setMyCommands", 15, since=0)
    c1 = await submit("按钮测试 1", 1)
    c2 = await submit("按钮测试 2", 2)

    # 1. 发布失败 → 状态“发布失败”，控制消息上出现“重试发布”，审核员看到原因
    lt.MOCK["fail"][f"sendMessage:{CHANNEL}"] = ["Bad Request: message is too long"]
    n = len(log); lt.cb("r:pub_ok:1:0", REVIEW, ADMIN)
    failed = await control_edit(c1, n, "发布失败")
    told = await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, "message is too long"), since=n)
    check("publish fails → marked failed with a Retry button, reviewer told why",
          failed and buttons(failed).get("🔁 重试发布") == "r:retry:1:0" and told and not posts(n, "按钮测试 1"),
          failed and buttons(failed))

    # 2. 重试发布：不需要确认，直接发布成功
    n = len(log); lt.cb("r:retry:1:0", REVIEW, ADMIN)
    post = await wait_for(lambda e: is_send(e, "sendMessage", CHANNEL, "按钮测试 1"), since=n)
    done = await control_edit(c1, n, "已发布")
    panel = [e for e in log[n:] if e["method"] == "editMessageReplyMarkup"]
    check("Retry → published right away (no confirm panel), control shows published", post and done and not panel)

    # 3. 已发布的再点“重试发布”（旧按钮）：提示状态已变化，不会重复发布
    n = len(log); lt.cb("r:retry:1:0", REVIEW, ADMIN)
    told = await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, "状态已变化"), since=n)
    check("Retry on an already-published submission → 'status changed', nothing posted twice",
          told and not posts(n, "按钮测试 1"))

    # 4. 定时 → 取消定时：回到待审核，按钮恢复成“立即发布 / 定时发布”
    n = len(log); lt.cb("r:sched:2:0", REVIEW, ADMIN)
    picker = await wait_for(lambda e: e["method"] == "editMessageReplyMarkup", since=n)
    preset = next(v for v in buttons(picker).values() if v.startswith("r:preset:"))
    n = len(log); lt.cb(preset, REVIEW, ADMIN)
    scheduled = await control_edit(c2, n, "定时")
    check("scheduled → Unschedule button shown",
          scheduled and buttons(scheduled).get("↩️ 取消定时") == "r:unsched:2:0", scheduled and buttons(scheduled))
    n = len(log); lt.cb("r:unsched:2:0", REVIEW, ADMIN)
    pending = await control_edit(c2, n, "待审核")
    toast = await wait_for(lambda e: e["method"] == "answerCallbackQuery" and "已取消定时" in e["params"].get("text", ""),
                           since=n)
    check("Unschedule → back to pending, Publish / Schedule buttons back, no confirm needed",
          pending and toast and "✅ 立即发布" in buttons(pending) and "⏰ 定时发布" in buttons(pending),
          pending and buttons(pending))

    # 5. 已经是待审核的再点“取消定时”（旧按钮）：提示状态已变化
    n = len(log); lt.cb("r:unsched:2:0", REVIEW, ADMIN)
    toast = await wait_for(lambda e: e["method"] == "answerCallbackQuery" and "状态已变化" in e["params"].get("text", ""),
                           since=n)
    check("Unschedule on a pending submission → 'status changed'", toast)


if __name__ == "__main__":
    # 发布失败时机器人会记一条 ERROR 日志（含堆栈），这是本测试预期中的
    asyncio.run(lt.main(scenario, {"REMINDER_INTERVAL_MINUTES": "0"}, allowed_errors=("发布 #1 失败",)))
