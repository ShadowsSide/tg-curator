from __future__ import annotations

import asyncio
import logging
import os

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
from .handlers import review, user


async def set_commands(bot: Bot, review_chat_id: int) -> None:
    await bot.set_my_commands(
        [
            BotCommand(command="start", description="开始投稿"),
            BotCommand(command="edit", description="修改投稿（回复你的投稿）新内容"),
            BotCommand(command="me", description="我的投稿统计"),
            BotCommand(command="help", description="使用说明"),
        ],
        scope=BotCommandScopeAllPrivateChats(),
    )
    await bot.set_my_commands(
        [
            BotCommand(command="stats", description="审核统计"),
            BotCommand(command="queue", description="定时发布队列"),
            BotCommand(command="active", description="投稿人活跃度"),
            BotCommand(command="edit", description="修改稿件（回复投稿）新内容"),
            BotCommand(command="no", description="拒绝投稿（回复投稿）[理由]"),
            BotCommand(command="ban", description="封禁投稿人并拒绝其来稿 [理由]"),
            BotCommand(command="unban", description="解除封禁"),
            BotCommand(command="user", description="查看投稿人"),
            BotCommand(command="help", description="命令说明"),
        ],
        scope=BotCommandScopeChat(chat_id=review_chat_id),
    )


def make_session(settings: Settings) -> AiohttpSession:
    """PROXY：访问 Telegram 需要代理时使用（http:// 或 socks5://）。
    TELEGRAM_API_URL：自建 Bot API 服务器（可发 2GB 文件）或测试用的模拟服务器。"""
    api = TelegramAPIServer.from_base(settings.api_url) if settings.api_url else PRODUCTION
    return AiohttpSession(api=api, proxy=settings.proxy or None)


async def main() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    settings = load_settings()

    db = DB(settings.db_path)
    await db.connect()

    bot = Bot(
        settings.bot_token,
        session=make_session(settings),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    core = Core(bot, db, settings)
    await core.init()
    await set_commands(bot, settings.review_chat_id)

    dp = Dispatcher(storage=MemoryStorage())
    dp["core"] = core
    dp.include_routers(review.build_router(settings), user.build_router())

    core.start_background()
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await core.stop_background()
        await db.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
