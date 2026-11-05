"""停止（SIGTERM）时不丢状态：进行中的发布、提交、定时发布都做完才退出。

用法（项目根目录下）：python tests/live_shutdown_test.py
复用 live_test.py 的模拟 Bot API 服务器，每个场景启动一次机器人（同一个数据库）。
"""
import asyncio
import os
import sqlite3
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import live_album_restart_test as restart  # noqa: E402
import live_test as lt  # noqa: E402
from live_test import ADMIN, CHANNEL, CTRL, REVIEW, USER, check, is_send, log, results, submit, wait_for  # noqa: E402
from aiohttp import web  # noqa: E402

DB = restart.DB = os.path.join(tempfile.mkdtemp(), "bot.db")
FLOOD = 3  # 秒：Telegram 要求等待的时间，SIGTERM 就在这段时间里到达


def status(sid):
    with sqlite3.connect(DB) as conn:
        return conn.execute("SELECT status FROM submissions WHERE id=?", (sid,)).fetchone()[0]


async def flooded(method, chat, since):
    return await wait_for(lambda e: e.get("flood") is not None and e["method"] == method
                          and str(e["params"].get("chat_id")) == str(chat), timeout=20, since=since)


async def main():
    app = web.Application()
    app.router.add_route("*", "/bot{token}/{method}", lt.handle)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    try:
        # 1. 审核员点发布，发送还在等限流时收到 SIGTERM
        proc, lines, task = await restart.start(port)
        await submit("退出时发布", 1)
        lt.MOCK["flood"][f"sendMessage:{CHANNEL}"] = [FLOOD]
        n = len(log); lt.cb("r:pub_ok:1:0", REVIEW, ADMIN)
        await flooded("sendMessage", CHANNEL, n)
        took, code = await restart.stop(proc, task)
        check("SIGTERM during publish → post sent once, recorded as published, clean exit",
              len([e for e in log[n:] if is_send(e, "sendMessage", CHANNEL)]) == 1
              and status(1) == "published" and code == 0, (status(1), code, round(took, 1), lines[-5:]))
        bad = lt.unexpected_errors(lines)
        check("no errors while stopping during publish", not bad, bad[:5])

        # 2. 投稿人点提交，发到审核群还在等限流时收到 SIGTERM
        proc, lines, task = await restart.start(port)
        n = len(log); lt.pm("退出时提交")
        await wait_for(lambda e: any(is_send(e, "sendMessage", USER, p) for p in lt.PROMPTS), since=n)
        lt.MOCK["flood"][f"sendMessage:{REVIEW}"] = [FLOOD]
        n = len(log); lt.cb("u:sign:2", USER, USER)
        await flooded("sendMessage", REVIEW, n)
        took, code = await restart.stop(proc, task)
        check("SIGTERM during submit → reaches the review group with its control panel message, clean exit",
              [e for e in log[n:] if is_send(e, "sendMessage", REVIEW, CTRL)] and status(2) == "pending" and code == 0,
              (status(2), code, round(took, 1), lines[-5:]))
        bad = lt.unexpected_errors(lines)
        check("no errors while stopping during submit", not bad, bad[:5])

        # 3. 定时发布到点，发送还在等限流时收到 SIGTERM
        with sqlite3.connect(DB) as conn:
            conn.execute("UPDATE submissions SET status='scheduled', scheduled_at=1 WHERE id=2")
        lt.MOCK["flood"][f"sendMessage:{CHANNEL}"] = [FLOOD]
        n = len(log)
        proc, lines, task = await restart.start(port)
        await flooded("sendMessage", CHANNEL, n)
        took, code = await restart.stop(proc, task)
        check("SIGTERM during a scheduled publish → finishes it, recorded as published",
              len([e for e in log[n:] if is_send(e, "sendMessage", CHANNEL)]) == 1
              and status(2) == "published" and code == 0, (status(2), code, round(took, 1), lines[-5:]))
        bad = lt.unexpected_errors(lines)
        check("no errors while stopping during a scheduled publish", not bad, bad[:5])

        # 4. 没有进行中的处理：马上退出（调度循环不用等满一轮）
        proc, lines, task = await restart.start(port)
        took, code = await restart.stop(proc, task)
        check("idle bot exits at once", took < 3 and code == 0, (round(took, 1), code))
    finally:
        await runner.cleanup()
    print(f"\n{sum(ok for _, ok in results)}/{len(results)} passed in {time.time() - lt.T0:.0f}s")
    sys.exit(0 if all(ok for _, ok in results) else 1)


if __name__ == "__main__":
    asyncio.run(main())
