"""配置错误：启动时报一行错误后待机（不退出，免得 Docker 反复重启），健康检查文件里写着同样的说明：
- 必填项没填、格式不对；Telegram 不认 token、找不到频道 / 群、两个 ID 填反、机器人不是频道管理员
- 按 LANGUAGE 显示中文或英文
- 待机时收到 SIGTERM（docker stop）马上退出
- 网络不通不算配置错误：直接退出（退出码非 0），交给 Docker 重启重试
- 正常启动时删掉上次留下的错误文件

用法（项目根目录下）：python tests/live_config_test.py
复用 live_test.py 的模拟 Bot API 服务器，每种情况启动一次机器人。约 1 分钟。
"""
import asyncio
import os
import signal
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import live_test as lt  # noqa: E402
from live_test import CHANNEL, PROJECT, REVIEW, check, results  # noqa: E402
from aiohttp import web  # noqa: E402

ERROR_FILE = os.path.join(tempfile.mkdtemp(), "config-error")
NOT_ADMIN = {"status": "member", "user": {"id": lt.BOT_ID, "is_bot": True, "first_name": "TestBot"}}
CANT_POST = {**lt.BOT_ADMIN, "can_post_messages": False}

# (名称, 额外环境变量, 模拟服务器的失败注入, 机器人在频道里的身份, 日志里应该出现的错误说明)
CASES = [
    ("CHANNEL_ID not set", {"CHANNEL_ID": ""}, {}, None, "没有填写 CHANNEL_ID"),
    ("malformed token", {"BOT_TOKEN": "abc"}, {}, None, "BOT_TOKEN 格式不对"),
    ("REVIEW_CHAT_ID not a number (English)", {"REVIEW_CHAT_ID": "-100abc", "LANGUAGE": "en"}, {}, None,
     "Configuration error: REVIEW_CHAT_ID must be a number, got '-100abc' (the bot won't run"),
    ("bad number elsewhere", {"MAX_PENDING_PER_USER": "five"}, {}, None, "MAX_PENDING_PER_USER 必须是数字"),
    ("bad time zone", {"TZ": "Mars/Base"}, {}, None, "TZ 不是有效的时区"),
    ("bad REVIEWERS", {"REVIEWERS": "admins,bob"}, {}, None, "REVIEWERS 里有无法识别的值 'bob'"),
    ("Telegram rejects the token", {}, {"getMe:None": [(401, "Unauthorized")]}, None, "Telegram 不认这个 BOT_TOKEN"),
    ("channel not found", {}, {f"getChat:{CHANNEL}": ["Bad Request: chat not found"]}, None,
     f"找不到 CHANNEL_ID 对应的频道 {CHANNEL}"),
    ("IDs swapped", {"CHANNEL_ID": str(REVIEW), "REVIEW_CHAT_ID": str(CHANNEL)}, {}, None,
     f"CHANNEL_ID={REVIEW} 不是频道"),
    ("bot not a channel admin", {}, {}, NOT_ADMIN, f"机器人不是频道 {CHANNEL} 的管理员"),
    ("channel admin without “Post messages”", {}, {}, CANT_POST, "没有“发布消息”权限"),
    ("review group not found", {}, {f"getChat:{REVIEW}": [(403, "Forbidden: bot is not a member of the group chat")]},
     None, f"找不到 REVIEW_CHAT_ID 对应的群 {REVIEW}"),
    ("review chat is a channel", {"REVIEW_CHAT_ID": "-1009999"}, {}, None, "REVIEW_CHAT_ID=-1009999 不是群组"),
]


async def start(port, extra):
    env = {**os.environ, "BOT_TOKEN": "123:TEST", "CHANNEL_ID": str(CHANNEL), "REVIEW_CHAT_ID": str(REVIEW),
           "TELEGRAM_API_URL": f"http://127.0.0.1:{port}", "DB_PATH": os.path.join(tempfile.mkdtemp(), "bot.db"),
           "CONFIG_ERROR_FILE": ERROR_FILE, "PYTHONUNBUFFERED": "1", "LANGUAGE": "zh", **extra}
    proc = await asyncio.create_subprocess_exec(sys.executable, "-m", "bot", cwd=PROJECT, env=env,
                                                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    lines = []

    async def pump():
        async for line in proc.stdout:
            lines.append(line.decode().rstrip())
    return proc, lines, asyncio.create_task(pump())


async def until(cond, timeout=15):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        await asyncio.sleep(0.05)
    return False


async def stop(proc, pump):
    """模拟 docker stop：发 SIGTERM，返回 (几秒内退出, 退出码)。"""
    if proc.returncode is None:
        proc.send_signal(signal.SIGTERM)
    t = time.time()
    try:
        await asyncio.wait_for(proc.wait(), 5)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
    await pump
    return time.time() - t, proc.returncode


async def config_error_case(port, name, extra, fail, member, expected):
    lt.MOCK["fail"] = {k: list(v) for k, v in fail.items()}
    lt.MOCK["bot_member"] = member or lt.BOT_ADMIN
    proc, lines, pump = await start(port, extra)
    logged = await until(lambda: any(expected in line for line in lines))
    await asyncio.sleep(0.5)  # 报错后应该待机，而不是退出
    alive = proc.returncode is None
    written = open(ERROR_FILE, encoding="utf-8").read() if os.path.exists(ERROR_FILE) else ""
    errors = [line for line in lines if " ERROR " in line]
    took, code = await stop(proc, pump)
    check(f"{name} → one error line, keeps waiting, health file written, SIGTERM exits",
          logged and alive and len(errors) == 1 and "Traceback" not in "\n".join(lines)
          and expected in written and written.strip() in errors[0] and took < 3 and code == 0,
          (logged, alive, errors, written, round(took, 1), code, lines[-5:]))


async def main():
    app = web.Application()
    app.router.add_route("*", "/bot{token}/{method}", lt.handle)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    try:
        for case in CASES:
            await config_error_case(port, *case)

        # 网络不通：不是配置错误，退出（非 0）交给 Docker 重启；不写错误文件
        os.remove(ERROR_FILE)
        proc, lines, pump = await start(port, {"TELEGRAM_API_URL": "http://127.0.0.1:9"})
        exited = await until(lambda: proc.returncode is not None)
        await stop(proc, pump)
        check("network error → exits with a non-zero code, no health file",
              exited and proc.returncode != 0 and not os.path.exists(ERROR_FILE), (proc.returncode, lines[-3:]))

        # 正常启动：删掉上次留下的错误文件，开始收消息
        open(ERROR_FILE, "w").write("old")
        lt.MOCK["fail"], lt.MOCK["bot_member"] = {}, lt.BOT_ADMIN
        proc, lines, pump = await start(port, {})
        polling = await until(lambda: any("Start polling" in line for line in lines))
        check("valid config → stale health file removed, bot polls",
              polling and not os.path.exists(ERROR_FILE) and proc.returncode is None, lines[-5:])
        took, code = await stop(proc, pump)
    finally:
        await runner.cleanup()
    print(f"\n{sum(ok for _, ok in results)}/{len(results)} passed in {time.time() - lt.T0:.0f}s")
    sys.exit(0 if all(ok for _, ok in results) else 1)


if __name__ == "__main__":
    asyncio.run(main())
