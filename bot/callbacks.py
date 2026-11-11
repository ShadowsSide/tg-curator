"""按钮回调的回应：每个按钮只能回应一次，而且要在几秒内回应（Telegram 没有公布确切时限，超时后
answerCallbackQuery 报 “query is too old”）。

处理函数通过注入的回应对象 answer(...) 回应，不直接调用 cq.answer()。CallbackAnswerMiddleware 给每个按钮
建一个回应对象，并兜底：
- 处理函数 CALLBACK_FALLBACK_SECONDS 秒还没回应（比如被限流、在等 Telegram）：先替它回应“处理中…”，免得超时
- 已经回应过之后再回应：普通提示直接丢掉（控制按钮消息本身会显示新状态），弹窗（show_alert，错误都用弹窗）
  改成一条消息，回复在按钮所在的消息下面
- 处理函数正常结束却没回应：回应一个空提示，按钮不会一直转圈
- 处理函数出错：不回应，留给错误处理（bot/handlers/errors.py）用同一个回应对象说明出错了

已知耗时的操作（发布、删除稿件、封禁）不靠兜底，开始前自己先回应。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import CallbackQuery, TelegramObject

from .i18n import t

log = logging.getLogger(__name__)


class Answer:
    """一个按钮的回应权。先检查再标记“已回应”，中间没有 await：处理函数和兜底同时要回应时，只有一方发得出去。
    回应失败（超时、按钮已失效、被限流）只记日志：这时再交给错误处理，它的回应同样会失败。"""

    def __init__(self, cq: CallbackQuery):
        self.cq = cq
        self.answered = False
        self.by_fallback = False  # 是兜底替处理函数回应的

    async def __call__(self, text: str | None = None, show_alert: bool = False) -> None:
        if self.answered:
            # 已经回应过（兜底的“处理中…”，或者处理函数先回应了“发布中…”后又出错）：弹窗改成消息，普通提示丢掉
            if text and show_alert:
                await self._as_message(text)
            return
        self.answered = True
        await self._send(text, show_alert)

    async def fallback(self, text: str | None) -> None:
        """兜底：处理函数还没回应就替它回应。"""
        if self.answered:
            return
        self.answered = self.by_fallback = True
        await self._send(text, False)

    async def _send(self, text: str | None, show_alert: bool) -> None:
        try:
            await self.cq.answer(text, show_alert=show_alert)
        except TelegramAPIError as e:
            log.info("回应按钮失败（%s）：%s", self.cq.data, e)

    async def _as_message(self, text: str) -> None:
        msg = self.cq.message
        if msg is None:  # 太旧的消息 Telegram 不给内容，不知道发到哪里
            return
        try:
            await msg.reply(text)
        except TelegramBadRequest:  # 按钮所在的消息已经删掉了（比如删除稿件），单独发
            try:
                await self.cq.bot.send_message(msg.chat.id, text)
            except TelegramAPIError as e:
                log.info("发送按钮结果失败：%s", e)
        except TelegramAPIError as e:
            log.info("发送按钮结果失败：%s", e)


class CallbackAnswerMiddleware(BaseMiddleware):
    """update 外层中间件：在 aiogram 的错误处理中间件里面，错误处理拿得到同一个回应对象（data["answer"]）。"""

    def __init__(self, after: float, lang_of: Callable[[CallbackQuery], str]):
        self.after = after
        self.lang_of = lang_of  # 兜底提示用的语言：私聊用投稿人的语言，审核群用 LANGUAGE

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        cq = getattr(event, "callback_query", None)  # update 层：只有按钮的 update 有
        if cq is None:
            return await handler(event, data)
        answer = data["answer"] = Answer(cq)
        timer = asyncio.create_task(self._fallback(answer, cq))
        try:
            result = await handler(event, data)
        finally:
            if not answer.by_fallback:  # 兜底已经在发了就让它发完，取消会打断那次请求
                timer.cancel()
        await answer()  # 处理函数没回应（或者被中间件、过滤器拦下了）：空回应，按钮不再转圈；回应过就什么都不做
        return result

    async def _fallback(self, answer: Answer, cq: CallbackQuery) -> None:
        await asyncio.sleep(self.after)
        await answer.fallback(t(self.lang_of(cq), "toast_working"))


def callback_lang(core) -> Callable[[CallbackQuery], str]:
    def lang_of(cq: CallbackQuery) -> str:
        private = cq.message is not None and cq.message.chat.type == ChatType.PRIVATE
        return core.lang_of(cq.from_user) if private else core.lang
    return lang_of
