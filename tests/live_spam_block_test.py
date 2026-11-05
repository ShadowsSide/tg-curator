"""投稿防垃圾测试（SPAM_ACTION=block）：命中时拦下不让提交，不透露命中的词；修改后可以重新提交。

用法（项目根目录下）：python tests/live_spam_block_test.py
复用 live_test.py 的模拟 Bot API 服务器。
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import live_test as lt  # noqa: E402
from live_test import REVIEW, USER, check, is_send, log, wait_for  # noqa: E402
from live_spam_test import choose, draft  # noqa: E402


async def scenario():
    await wait_for(lambda e: e["method"] == "setMyCommands", 15, since=0)

    # 1. 命中关键词 → 拦下：提示投稿人修改，不说是哪个词，审核群里什么都没有
    mid = await draft("好资源，请加微信领取")
    ctrl, toast = await choose(1)
    msg = toast and toast["params"].get("text", "")
    check("keyword hit (block mode) → refused, keyword not revealed, nothing sent to review",
          not ctrl and msg and "不允许的词语" in msg and "加微信" not in msg and toast["params"].get("show_alert"), msg)

    # 2. 投稿人用 Telegram 的“编辑”改掉 → 再选投稿方式就能提交
    n = len(log); lt.pm_edit(mid, "好资源，私聊领取")
    await wait_for(lambda e: is_send(e, "sendMessage", USER), since=n)
    ctrl, _ = await choose(1)
    check("after editing out the keyword the same draft can be submitted, not flagged",
          ctrl and "疑似垃圾" not in ctrl["params"]["text"], ctrl and ctrl["params"]["text"])

    # 3. 没启用链接上限时链接不受限制
    await draft("https://a.example https://b.example", entities=[
        {"type": "url", "offset": 0, "length": 17}, {"type": "url", "offset": 18, "length": 17}])
    ctrl, _ = await choose(2)
    check("MAX_LINKS unset → links are not limited", ctrl)

    # 4. 先提交干净的内容，再用 Telegram 的“编辑”改成命中关键词的：不保存，审核群看不到
    mid = await draft("干净的投稿")
    ctrl, _ = await choose(3)
    n = len(log); lt.pm_edit(mid, "干净的投稿，加微信领取")
    told = await wait_for(lambda e: is_send(e, "sendMessage", USER, "不允许的词语"), since=n)
    await asyncio.sleep(0.5)
    check("edit after submitting adds a keyword (block mode) → not saved, nothing new in review",
          told and "加微信" not in told["params"]["text"]
          and not [e for e in log[n:] if is_send(e, "sendMessage", REVIEW, "加微信")])

    # 5. 投稿人用 /edit 回复自己的投稿改成命中的内容：同样拦下
    n = len(log); lt.pm("/edit 改成加微信", reply_to_message={"message_id": mid, "date": lt.now(), "chat": lt.chat(USER)})
    check("/edit by the submitter adding a keyword → refused",
          await wait_for(lambda e: is_send(e, "sendMessage", USER, "不允许的词语"), since=n)
          and not [e for e in log[n:] if is_send(e, "sendMessage", REVIEW, "加微信")])

    # 6. 审核员自己改成带这个词的内容：不拦（审核员可信）
    n = len(log); lt.gm("/edit 审核员写的：加微信", reply_to=ctrl["result"]["message_id"])
    check("reviewer edit containing the keyword → allowed, preview sent",
          await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, "审核员写的"), since=n))


if __name__ == "__main__":
    asyncio.run(lt.main(scenario, {"SPAM_KEYWORDS": "加微信", "SPAM_ACTION": "block", "REMINDER_INTERVAL_MINUTES": "0"}))
