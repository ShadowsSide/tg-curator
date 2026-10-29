"""记住投稿人上次选的署名 / 匿名：下次投稿时那个按钮标“（上次）”并排在前面。

用法（项目根目录下）：python tests/live_choice_test.py
复用 live_test.py 的模拟 Bot API 服务器。约 8 秒。
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import live_test as lt  # noqa: E402
from live_test import BOB, CTRL, REVIEW, USER, check, is_send, log, pm, wait_for  # noqa: E402


def first_row(e):
    """选择面板第一行（署名 / 匿名）的按钮文字。"""
    return [b["text"] for b in e["params"]["reply_markup"]["inline_keyboard"][0]]


async def draft(text, who=USER):
    n = len(log); pm(text, who=who)
    return await wait_for(lambda e: any(is_send(e, "sendMessage", who, p) for p in lt.PROMPTS), since=n)


async def choose(sid, choice, who=USER):
    n = len(log); lt.cb(f"u:{choice}:{sid}", who, who)
    return await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, CTRL), since=n)


async def scenario():
    await wait_for(lambda e: e["method"] == "setMyCommands", 15, since=0)

    e = await draft("第一次")
    check("first submission → no “last time” mark", e and first_row(e) == ["👤 署名投稿", "🕶 匿名投稿"], e and first_row(e))
    await choose(1, "anon")

    e = await draft("第二次")
    check("after choosing anonymous → Anonymous marked and first",
          e and first_row(e) == ["🕶 匿名投稿（上次）", "👤 署名投稿"], e and first_row(e))
    await choose(2, "sign")

    e = await draft("第三次")
    check("after choosing signed → Signed marked and first",
          e and first_row(e) == ["👤 署名投稿（上次）", "🕶 匿名投稿"], e and first_row(e))
    await choose(3, "anon")

    # 取消的草稿（数据库里默认记为“署名”）不算一次选择：仍然标“匿名”
    await draft("第四次")
    n = len(log); lt.cb("u:cancel:4", USER, USER)
    await wait_for(lambda e: e["method"] == "answerCallbackQuery", since=n)
    e = await draft("第五次")
    check("a cancelled draft doesn't count as a choice",
          e and first_row(e) == ["🕶 匿名投稿（上次）", "👤 署名投稿"], e and first_row(e))

    e = await draft("another person", who=BOB)
    check("each submitter has their own (Bob: first time, English)",
          e and first_row(e) == ["👤 Signed", "🕶 Anonymous"], e and first_row(e))


if __name__ == "__main__":
    asyncio.run(lt.main(scenario))
