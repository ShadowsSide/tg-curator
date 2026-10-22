"""只处理两处的消息：私聊、审核群。其他聊天里的一切都不响应。

作为 Dispatcher 的 update 外层中间件，在所有处理函数之前执行，以后新增功能也自动受保护。
发布频道及其关联群组（评论区）在白名单里：机器人留在那里，但同样不响应。
被拉进其他群组 / 频道时，LEAVE_UNKNOWN_CHATS=true 会让机器人自动退出。
"""
from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware, Bot
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramAPIError
from aiogram.types import Chat, TelegramObject, Update

log = logging.getLogger(__name__)

# 机器人自己已经不在这个聊天里了（被移出 / 自己退出），不用再退出
_GONE = ("left", "kicked")


class ChatGuard(BaseMiddleware):
    def __init__(self, review_chat_id: int, keep_chat_ids: set[int], leave_unknown: bool):
        self.review_chat_id = review_chat_id
        self.keep_chat_ids = keep_chat_ids  # 白名单：留下但不响应
        self.leave_unknown = leave_unknown

    def allowed(self, chat: Chat) -> bool:
        return chat.type == ChatType.PRIVATE or chat.id == self.review_chat_id

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        chat: Chat | None = data.get("event_chat")
        if chat is None or self.allowed(chat):
            return await handler(event, data)

        # 白名单（发布频道、频道的关联群组）：不退出，也不处理那里的任何更新
        if chat.id in self.keep_chat_ids:
            return None

        if self.leave_unknown and not _bot_already_gone(event):
            bot: Bot = data["bot"]
            try:
                await bot.leave_chat(chat.id)
                log.warning("机器人被加入了未配置的聊天 %s（%s），已自动退出", chat.id, chat.title or chat.type)
            except TelegramAPIError as e:
                log.info("退出聊天 %s 失败：%s", chat.id, e)
        return None


def _bot_already_gone(event: TelegramObject) -> bool:
    return isinstance(event, Update) and event.my_chat_member is not None and \
        event.my_chat_member.new_chat_member.status in _GONE
