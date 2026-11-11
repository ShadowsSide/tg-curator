"""控制按钮消息上的“已修改”：带最新一份修改后预览的链接，改过不止一次时显示次数。
- 没改过：没有“已修改”
- 第一次改：“已修改（…）”，链接指向这次的预览，不显示次数
- 第二次改：“已修改 2 次”，链接换成新的预览（上一份预览已删掉）

用法（项目根目录下）：python tests/live_edit_link_test.py
复用 live_test.py 的模拟 Bot API 服务器。
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import live_test as lt  # noqa: E402
from live_test import REVIEW, check, edit_cmd, is_send, log, submit, wait_for  # noqa: E402

CHAT = str(REVIEW).removeprefix("-100")


def last_control(ctrl, since):
    edits = [e for e in log[since:] if e["method"] == "editMessageText" and not e.get("error")
             and str(e["params"].get("message_id")) == str(ctrl)]
    return edits[-1]["params"]["text"] if edits else ""


async def edit(text, ctrl):
    """审核员 /edit，返回这次修改后的预览（回复控制按钮消息、内容是新文字）的消息编号。"""
    n = len(log)
    await edit_cmd(f"/edit {text}", ctrl)
    preview = next((e for e in log[n:] if is_send(e, "sendMessage", REVIEW, text)
                    and str((e["params"].get("reply_parameters") or {}).get("message_id")) == str(ctrl)), None)
    return n, preview and preview["result"]["message_id"]


async def scenario():
    await wait_for(lambda e: e["method"] == "setMyCommands", 15, since=0)
    sent = await submit("改稿链接", 1)
    ctrl = sent["result"]["message_id"]
    check("not edited → no “edited” line", "已修改" not in sent["params"]["text"], sent["params"]["text"])

    n, p1 = await edit("第一次修改", ctrl)
    text = last_control(ctrl, n)
    check("first edit → “edited” with a link to this edit's preview, no count",
          p1 and f'href="https://t.me/c/{CHAT}/{p1}">查看最新版本' in text and "已修改（" in text, (p1, text))

    n, p2 = await edit("第二次修改", ctrl)
    text = last_control(ctrl, n)
    check("second edit → “edited 2 times”, the link moves to the new preview",
          p2 and p2 != p1 and "已修改 2 次" in text and f"/c/{CHAT}/{p2}\"" in text and f"/{p1}\"" not in text,
          (p1, p2, text))


if __name__ == "__main__":
    asyncio.run(lt.main(scenario, {"REMINDER_INTERVAL_MINUTES": "0"}))
