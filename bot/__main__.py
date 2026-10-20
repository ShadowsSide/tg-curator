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
from .i18n import LANGS, PRIVATE_COMMANDS, REVIEW_COMMANDS


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
    await set_commands(bot, settings.review_chat_id, settings.language)

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
