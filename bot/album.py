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
        self.on_album = on_album  # 默认的处理：投稿人发来的相册当作投稿
        self._buffers: dict[str, list[Message]] = {}
        self._handlers: dict[str, Callable[[list[Message]], Awaitable[None]]] = {}
        self._timers: dict[str, asyncio.Task] = {}

    @staticmethod
    def _key(message: Message) -> str:
        return f"{message.chat.id}:{message.media_group_id}"

    def add(self, message: Message, on_album: Callable[[list[Message]], Awaitable[None]] | None = None) -> None:
        """加入相册的一项。on_album：这个相册收齐后交给谁（第一项决定），不填就是默认的处理。"""
        key = self._key(message)
        self._buffers.setdefault(key, []).append(message)
        self._handlers.setdefault(key, on_album or self.on_album)
        if timer := self._timers.get(key):
            timer.cancel()
        self._timers[key] = asyncio.create_task(self._flush_later(key))

    def join(self, message: Message) -> bool:
        """相册正在收集中（之前的项已经 add 过）就加进去，返回 True；否则什么也不做。"""
        if self._key(message) not in self._buffers:
            return False
        self.add(message)
        return True

    async def _flush_later(self, key: str) -> None:
        try:
            await asyncio.sleep(self.delay)
        except asyncio.CancelledError:
            return
        # 先摘掉 timer，之后 add() 不会再 cancel 这个正在处理的任务
        self._timers.pop(key, None)
        messages = sorted(self._buffers.pop(key, []), key=lambda m: m.message_id)
        handler = self._handlers.pop(key, self.on_album)
        try:
            await handler(messages)
        except Exception:
            log.exception("处理相册失败 %s", key)
