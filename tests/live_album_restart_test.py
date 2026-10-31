"""重启时正在收集的相册：
- 相册收到一半就收到 SIGTERM（docker stop）：已经到的几项马上作为草稿处理，投稿人收到“请选择投稿方式”，然后正常退出
- 重启后才到的几项并进同一条草稿，提示改成新的数量；重启前已经收到的项再收到一次，不会重复加进去
- 相册已经收齐、正在处理（提示被限流，还在等）时收到 SIGTERM：等它处理完再退出

用法（项目根目录下）：python tests/live_album_restart_test.py
复用 live_test.py 的模拟 Bot API 服务器，启动两次机器人（同一个数据库）。约 20 秒。
"""
import asyncio
import json
import os
import signal
import sqlite3
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import live_test as lt  # noqa: E402
from live_test import PROJECT, PROMPTS, USER, check, is_send, log, results, wait_for  # noqa: E402
from aiohttp import web  # noqa: E402

DELAY = 3.0  # ALBUM_DELAY：比 SIGTERM 之前等的时间长，保证停止时相册还在收集
DB = os.path.join(tempfile.mkdtemp(), "bot.db")


def rows():
    with sqlite3.connect(DB) as conn:
        return [(status, [it["msg_id"] for it in json.loads(items)]) for status, items in
                conn.execute("SELECT status, items FROM submissions ORDER BY id")]


def album(ids, group="g-restart"):
    """投稿人相册里的几项（消息编号 ids），放进同一次 getUpdates。"""
    for i in ids:
        lt.uid[0] += 1
        lt.updates.append({"update_id": lt.uid[0], "message": {
            "message_id": i, "date": lt.now(), "chat": lt.chat(USER), "media_group_id": group,
            "from": {"id": USER, "is_bot": False, "first_name": "Alice", "language_code": "zh-hans"},
            "photo": [{"file_id": f"p{i}", "file_unique_id": f"p{i}", "width": 1, "height": 1}]}})
    lt.new_update.set()


async def start(port):
    env = {**os.environ, "BOT_TOKEN": "123:TEST", "CHANNEL_ID": str(lt.CHANNEL), "REVIEW_CHAT_ID": str(lt.REVIEW),
           "TELEGRAM_API_URL": f"http://127.0.0.1:{port}", "DB_PATH": DB, "ALBUM_DELAY": str(DELAY),
           "PYTHONUNBUFFERED": "1"}
    n = len(log)
    proc = await asyncio.create_subprocess_exec(sys.executable, "-m", "bot", cwd=PROJECT, env=env,
                                                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    lines = []

    async def pump():
        async for line in proc.stdout:
            lines.append(line.decode().rstrip())
    task = asyncio.create_task(pump())
    await wait_for(lambda e: e["method"] == "setMyCommands", 15, since=n)
    await asyncio.sleep(0.3)
    return proc, lines, task


async def stop(proc, task):
    """模拟 docker stop：发 SIGTERM，10 秒内没退出就强杀。返回 (用了几秒, 退出码)。"""
    proc.send_signal(signal.SIGTERM)
    t = time.time()
    try:
        await asyncio.wait_for(proc.wait(), 10)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
    await task
    return time.time() - t, proc.returncode


async def main():
    app = web.Application()
    app.router.add_route("*", "/bot{token}/{method}", lt.handle)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    try:
        proc, lines, task = await start(port)
        n = len(log)
        album([401, 402, 403])
        await asyncio.sleep(1)  # 已经取走（下一次 getUpdates 确认了），但还没等满 ALBUM_DELAY
        took, code = await stop(proc, task)
        prompt = [e for e in log[n:] if any(is_send(e, "sendMessage", USER, p) for p in PROMPTS)]
        check("SIGTERM mid-album: the 3 photos become a draft, submitter gets the prompt, clean exit",
              rows() == [("draft", [401, 402, 403])] and len(prompt) == 1 and "3 张图片" in prompt[0]["params"]["text"]
              and code == 0 and took < 5, (rows(), len(prompt), code, round(took, 1), lines[-5:]))
        bad = lt.unexpected_errors(lines)
        check("no errors while shutting down", not bad, bad[:5])

        proc, lines, task = await start(port)
        n = len(log)
        album([403, 404, 405])  # 403 重启前已经收到过
        await asyncio.sleep(DELAY + 1.5)
        edits = [e["params"]["text"] for e in log[n:]
                 if e["method"] == "editMessageText" and str(e["params"].get("chat_id")) == str(USER)]
        prompt = [e for e in log[n:] if any(is_send(e, "sendMessage", USER, p) for p in PROMPTS)]
        check("after restart: the rest joins the same draft (no duplicate), the prompt says 5 photos",
              rows() == [("draft", [401, 402, 403, 404, 405])] and not prompt and edits and "5 张图片" in edits[-1],
              (rows(), len(prompt), edits))
        bad = lt.unexpected_errors(lines)
        check("no errors after restart", not bad, bad[:5])

        lt.MOCK["flood"][f"sendMessage:{USER}"] = [2]
        n = len(log)
        album([501, 502], group="g-busy")
        await asyncio.sleep(DELAY + 0.5)  # 已经收齐，正在等限流结束后发提示
        took, code = await stop(proc, task)
        prompt = [e for e in log[n:] if any(is_send(e, "sendMessage", USER, p) for p in PROMPTS)]
        check("SIGTERM while an album is being handled: waits for it, prompt sent, clean exit",
              rows()[-1] == ("draft", [501, 502]) and len(prompt) == 1 and code == 0,
              (rows()[-1:], len(prompt), code, round(took, 1), lines[-5:]))
        bad = lt.unexpected_errors(lines)
        check("no errors while shutting down a busy bot", not bad, bad[:5])
    finally:
        await runner.cleanup()
    print(f"\n{sum(ok for _, ok in results)}/{len(results)} passed in {time.time() - lt.T0:.0f}s")
    sys.exit(0 if all(ok for _, ok in results) else 1)


if __name__ == "__main__":
    asyncio.run(main())
