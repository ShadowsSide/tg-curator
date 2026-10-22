"""Telegram 限流（429 Too Many Requests）时自动等待并重试。

挂在 Bot 的请求层，所有接口调用都受益（发消息、编辑、话题操作……）。
被限流的请求 Telegram 并没有执行，所以重试不会造成重复发送。
要求等待的时间超过 MAX_WAIT 时不在原地干等，直接把异常交给上层（例如发布会改为稍后自动重发）。
"""
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot
from aiogram.client.session.middlewares.base import BaseRequestMiddleware, NextRequestMiddlewareType
from aiogram.exceptions import TelegramRetryAfter
from aiogram.methods import Response, TelegramMethod
from aiogram.methods.base import TelegramType

log = logging.getLogger(__name__)

MAX_WAIT = 30  # 秒：单次最多原地等待多久
MAX_RETRIES = 3


class RetryAfterMiddleware(BaseRequestMiddleware):
    def __init__(self, max_wait: float = MAX_WAIT, max_retries: int = MAX_RETRIES):
        self.max_wait = max_wait
        self.max_retries = max_retries

    async def __call__(
        self,
        make_request: NextRequestMiddlewareType[TelegramType],
        bot: Bot,
        method: TelegramMethod[TelegramType],
    ) -> Response[TelegramType]:
        for attempt in range(self.max_retries + 1):
            try:
                return await make_request(bot, method)
            except TelegramRetryAfter as e:
                if attempt == self.max_retries or e.retry_after > self.max_wait:
                    raise
                log.warning("Telegram 限流：%s 需等待 %s 秒，第 %s 次重试",
                            type(method).__name__, e.retry_after, attempt + 1)
                await asyncio.sleep(e.retry_after + 0.5)
        raise AssertionError("unreachable")
