from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import signal

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import PRODUCTION, TelegramAPIServer
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, BotCommandScopeAllPrivateChats, BotCommandScopeChat

from .config import Settings, load_settings
from .core import Core
from .db import DB
from .errors import ConfigError
from .guard import ChatGuard
from .handlers import review, user
from .i18n import LANGS, PRIVATE_COMMANDS, REVIEW_COMMANDS, t
from .ratelimit import RetryAfterMiddleware

# 配置错误时写下错误说明；Dockerfile 的健康检查看到这个文件就显示 unhealthy
CONFIG_ERROR_FILE = os.getenv("CONFIG_ERROR_FILE", "/tmp/config-error")


async def set_commands(bot: Bot, review_chat_id: int, default_lang: str) -> None:
    """命令菜单按语言注册：Telegram 会根据用户客户端的语言显示对应版本，其他语言显示默认版本。"""
    def cmds(table: dict, lang: str) -> list[BotCommand]:
        return [BotCommand(command=c, description=d) for c, d in table[lang]]

    private, review = BotCommandScopeAllPrivateChats(), BotCommandScopeChat(chat_id=review_chat_id)
    await bot.set_my_commands(cmds(PRIVATE_COMMANDS, default_lang), scope=private)
    await bot.set_my_commands(cmds(REVIEW_COMMANDS, default_lang), scope=review)
    for lang in LANGS:
        await bot.set_my_commands(cmds(PRIVATE_COMMANDS, lang), scope=private, language_code=lang)
        await bot.set_my_commands(cmds(REVIEW_COMMANDS, default_lang), scope=review, language_code=lang)


def make_session(settings: Settings) -> AiohttpSession:
    """PROXY：访问 Telegram 需要代理时使用（http:// 或 socks5://）。
    TELEGRAM_API_URL：自建 Bot API 服务器（可发 2GB 文件）或测试用的模拟服务器。"""
    api = TelegramAPIServer.from_base(settings.api_url) if settings.api_url else PRODUCTION
    return AiohttpSession(api=api, proxy=settings.proxy or None)


async def run() -> None:
    settings = load_settings()
    for name in ("REVIEW_TOPICS", "USER_TOPICS"):
        if os.getenv(name):
            logging.warning("%s 已移除（话题模式不再支持），可以从配置里删掉", name)

    db = DB(settings.db_path)
    await db.connect()
    bot = Bot(
        settings.bot_token,
        session=make_session(settings),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    try:
        bot.session.middleware(RetryAfterMiddleware())  # 被限流时自动等待重试
        core = Core(bot, db, settings)
        await core.init()
        await set_commands(bot, settings.review_chat_id, settings.language)

        dp = Dispatcher(storage=MemoryStorage())
        dp["core"] = core
        # 只处理私聊和审核群；必须在所有处理函数之前，放在 update 外层中间件
        keep = {c for c in (core.channel_chat_id, core.channel_linked_chat_id) if c}  # 发布频道 + 关联群组
        dp.update.outer_middleware(ChatGuard(settings.review_chat_id, keep, settings.leave_unknown_chats))
        dp.include_routers(review.build_router(settings), user.build_router())

        core.start_background()
        try:
            # my_chat_member：机器人被拉进其他群时收到通知，才能自动退出
            allowed = sorted(set(dp.resolve_used_update_types()) | {"my_chat_member"})
            await dp.start_polling(bot, allowed_updates=allowed)
            # 停止（docker stop 发 SIGTERM）后，内存里还没收齐的相册先处理掉，免得丢失
            await core.albums.close()
        finally:
            await core.stop_background()
    finally:
        await db.close()
        await bot.session.close()


async def wait_for_fix(error: ConfigError) -> None:
    """配置错误重启也修不好：退出的话 Docker 会不停重启、刷屏，所以报一次错后待机，直到容器被停止或重建。
    服务器重启后容器照常启动，再检查一次。"""
    lang = os.getenv("LANGUAGE", "").strip().lower()
    lang = lang if lang in LANGS else "zh"
    text = t(lang, "cfg_error", msg=error.notice.text(lang))
    logging.error(text)
    with contextlib.suppress(OSError):
        with open(CONFIG_ERROR_FILE, "w", encoding="utf-8") as f:
            f.write(text + "\n")
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):  # 容器里是 1 号进程，不处理的话 docker stop 要等 10 秒强杀
        loop.add_signal_handler(sig, stop.set)
    await stop.wait()


async def main() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    with contextlib.suppress(FileNotFoundError):  # 上次留下的（容器重启后 /tmp 还在）
        os.remove(CONFIG_ERROR_FILE)
    try:
        await run()
    except ConfigError as e:
        await wait_for_fix(e)

if __name__ == "__main__":
    asyncio.run(main())
