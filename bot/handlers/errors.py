"""处理函数里没被处理的异常：记下日志，并告诉对方这次操作没有完成。

不处理的话，aiogram 只写一条日志：点按钮的人看到按钮一直转圈，发消息的人什么回应都收不到，会以为成功了。
"""
from __future__ import annotations

import logging

from aiogram import Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramAPIError
from aiogram.types import ErrorEvent

from ..callbacks import Answer
from ..core import Core
from ..i18n import t

log = logging.getLogger(__name__)


def build_router() -> Router:
    router = Router(name="errors")

    @router.errors()
    async def on_error(event: ErrorEvent, core: Core, answer: Answer | None = None) -> None:
        log.error("处理更新出错（update %s）", event.update.update_id, exc_info=event.exception)
        cq = event.update.callback_query
        m = event.update.message or event.update.edited_message
        chat = cq.message.chat if cq and cq.message else m.chat if m else None
        user = cq.from_user if cq else m.from_user if m else None
        if chat is None:
            return
        # 私聊用投稿人的语言，审核群用 LANGUAGE（和其他提示一样）
        text = t(core.lang_of(user) if user and chat.type == ChatType.PRIVATE else core.lang, "error_generic")
        if answer:  # 按钮：用同一个回应对象，兜底已经回应过时改成消息；回应失败只记日志，不再另发
            await answer(text, show_alert=True)
            return
        try:
            if m:
                await m.reply(text)
                return
        except TelegramAPIError as e:  # 原消息已删除等
            log.info("回复出错提示失败：%s", e)
        try:
            await core.bot.send_message(chat.id, text)
        except TelegramAPIError as e:
            log.info("发送出错提示失败：%s", e)

    return router
