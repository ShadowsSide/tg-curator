from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable

from aiogram.types import Message

log = logging.getLogger(__name__)


class AlbumCollector:
    """相册（media group）的每一项是单独的 update，这里等最后一项到达后 delay 秒再一起处理。"""

    def __init__(self, delay: float, on_album: Callable[[list[Message]], Awaitable[None]]):
        self.delay = delay
        self.on_album = on_album
        self._buffers: dict[str, list[Message]] = {}
        self._timers: dict[str, asyncio.Task] = {}

    def add(self, message: Message) -> None:
        key = f"{message.chat.id}:{message.media_group_id}"
        self._buffers.setdefault(key, []).append(message)
        if timer := self._timers.get(key):
            timer.cancel()
        self._timers[key] = asyncio.create_task(self._flush_later(key))

    async def _flush_later(self, key: str) -> None:
        try:
            await asyncio.sleep(self.delay)
        except asyncio.CancelledError:
            return
        # 先摘掉 timer，之后 add() 不会再 cancel 这个正在处理的任务
        self._timers.pop(key, None)
        messages = sorted(self._buffers.pop(key, []), key=lambda m: m.message_id)
        try:
            await self.on_album(messages)
        except Exception:
            log.exception("处理相册失败 %s", key)
