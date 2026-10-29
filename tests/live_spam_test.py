"""投稿防垃圾测试（SPAM_ACTION=flag，默认）：命中时照常提交，控制消息上标记；改稿后重新检查；新用户冷却。

用法（项目根目录下）：python tests/live_spam_test.py
拦截模式（SPAM_ACTION=block）见 live_spam_block_test.py。复用 live_test.py 的模拟 Bot API 服务器。约 10 秒。
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import live_test as lt  # noqa: E402
from live_test import ADMIN, BOB, CHANNEL, CTRL, REVIEW, USER, check, is_send, log, wait_for  # noqa: E402
from bot.entities import u16len  # noqa: E402


def url_entities(text, *urls):
    return [{"type": "url", "offset": u16len(text[:text.index(u)]), "length": u16len(u)} for u in urls]


async def draft(text, who=USER, **extra):
    """发一条投稿，等到“选择投稿方式”的提示。返回原消息 ID。"""
    n = len(log); mid = lt.pm(text, who=who, **extra)
    await wait_for(lambda e: is_send(e, "sendMessage", who), since=n)
    return mid


async def choose(sid, who=USER):
    """选“署名”。返回 (控制消息, 按钮提示)。"""
    n = len(log); lt.cb(f"u:sign:{sid}", who, who)
    toast = await wait_for(lambda e: e["method"] == "answerCallbackQuery", since=n)
    ctrl = await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, CTRL), timeout=1.5, since=n)
    return ctrl, toast


async def scenario():
    await wait_for(lambda e: e["method"] == "setMyCommands", 15, since=0)

    # 1. 关键词：照常提交，控制消息上标记
    await draft("好资源，请加微信领取")
    ctrl1, _ = await choose(1)
    check("keyword hit (flag mode) → still submitted, control message flagged",
          ctrl1 and "疑似垃圾：含关键词「加微信」" in ctrl1["params"]["text"], ctrl1 and ctrl1["params"]["text"])

    # 2. 新用户冷却：还没有稿件发布过，10 分钟内不能再提交；草稿保留
    await draft("第二条正常投稿")
    ctrl2, toast = await choose(2)
    check("new submitter within cooldown → refused with minutes to wait, nothing sent to review",
          not ctrl2 and toast and "10 分钟后再提交" in toast["params"].get("text", "") and toast["params"].get("show_alert"),
          toast and toast["params"].get("text"))

    # 3. 有稿件发布过之后不再受冷却限制；干净的稿件没有标记
    n = len(log); lt.cb("r:pub_ok:1:0", REVIEW, ADMIN)
    await wait_for(lambda e: is_send(e, "sendMessage", CHANNEL), since=n)
    ctrl2, _ = await choose(2)
    check("after a post is published, cooldown no longer applies; clean submission not flagged",
          ctrl2 and "疑似垃圾" not in ctrl2["params"]["text"], ctrl2 and ctrl2["params"]["text"])

    # 4. 链接上限：白名单域名（含子域名）不计；超链接（text_link）也算
    text = "看 https://a.example 和 t.me/chan、www.t.me/x 还有 这里"
    ents = url_entities(text, "https://a.example", "t.me/chan", "www.t.me/x") + [
        {"type": "text_link", "offset": u16len(text) - 2, "length": 2, "url": "https://b.example"}]
    bob_mid = await draft(text, who=BOB, entities=ents)
    ctrl3, _ = await choose(3, who=BOB)
    check("links over the limit (whitelisted ones not counted) → flagged with the count",
          ctrl3 and "疑似垃圾：2 个链接（上限 1）" in ctrl3["params"]["text"], ctrl3 and ctrl3["params"]["text"])

    # 5. 投稿人改稿去掉链接 → 重新检查，标记消失
    n = len(log); lt.pm_edit(bob_mid, "只留一个 t.me/chan", url_entities("只留一个 t.me/chan", "t.me/chan"), who=BOB)
    mid3 = str(ctrl3["result"]["message_id"])
    redraw = await wait_for(lambda e: e["method"] == "editMessageText" and str(e["params"].get("message_id")) == mid3, since=n)
    check("edit removes the extra links → re-checked, flag cleared",
          redraw and "疑似垃圾" not in redraw["params"]["text"], redraw and redraw["params"]["text"])

    # 6. 审核员改稿加进关键词 → 标记出现（只标记，不拦截审核员）
    n = len(log); lt.gm("/edit 现在请加微信", reply_to=ctrl3["result"]["message_id"])
    redraw = await wait_for(lambda e: e["method"] == "editMessageText" and str(e["params"].get("message_id")) == mid3
                            and "加微信" in e["params"]["text"], since=n)
    check("reviewer edit that adds a keyword → flag shown (reviewers are never blocked)", redraw)


if __name__ == "__main__":
    asyncio.run(lt.main(scenario, {"SPAM_KEYWORDS": "加微信", "MAX_LINKS": "1", "LINK_WHITELIST": "t.me",
                                   "NEW_USER_COOLDOWN_MINUTES": "10", "REMINDER_INTERVAL_MINUTES": "0"}))
