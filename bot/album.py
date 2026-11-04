from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable

from aiogram.types import Message

log = logging.getLogger(__name__)

# 相册后到的部分（晚于 delay 才到，已经单独处理过前面的部分）：这么久之内还会接着并进去，超过就不认了
ALBUM_MERGE_WINDOW = 10 * 60


class AlbumCollector:
    """相册（media group）的每一项是单独的 update，这里等最后一项到达后 delay 秒再一起处理。"""

    def __init__(self, delay: float, on_album: Callable[[list[Message]], Awaitable[None]],
                 on_error: Callable[[Message], Awaitable[None]] | None = None):
        self.delay = delay
        self.on_album = on_album  # 默认的处理：投稿人发来的相册当作投稿
        # 处理出错时调用（参数是相册第一项）：相册不经过 aiogram 的错误处理，要自己告诉发送的人
        self.on_error = on_error
        self._buffers: dict[str, list[Message]] = {}
        self._handlers: dict[str, Callable[[list[Message]], Awaitable[None]]] = {}
        self._explicit: set[str] = set()  # 已经由带命令的那项（如 /msg）指定了处理方式的相册，weak 的不能再改
        self._timers: dict[str, asyncio.Task] = {}  # 还在等后面几项的相册
        self._running: set[asyncio.Task] = set()  # 等待结束、正在处理的相册

    @staticmethod
    def _key(message: Message) -> str:
        return f"{message.chat.id}:{message.media_group_id}"

    def add(self, message: Message, on_album: Callable[[list[Message]], Awaitable[None]] | None = None,
            *, weak: bool = False) -> None:
        """加入相册的一项。on_album：这个相册收齐后交给谁；不填就是默认的处理。
        指定了的优先，不管先后：相册里带 /msg 的那项不一定最先到，先到的几项按默认处理登记过也要改过来。
        weak：只是猜测的处理（例如回复了审核员的消息，提醒用 /msg）：能盖过默认的，但不能盖过带命令的那项指定的。"""
        key = self._key(message)
        self._buffers.setdefault(key, []).append(message)
        if on_album and not weak:
            self._handlers[key] = on_album
            self._explicit.add(key)
        elif on_album:
            if key not in self._explicit:
                self._handlers[key] = on_album
        else:
            self._handlers.setdefault(key, self.on_album)
        if timer := self._timers.get(key):
            timer.cancel()
        self._timers[key] = asyncio.create_task(self._flush_later(key))

    def join(self, message: Message) -> bool:
        """相册正在收集中（之前的项已经 add 过）就加进去，返回 True；否则什么也不做。"""
        if self._key(message) not in self._buffers:
            return False
        self.add(message)
        return True

    async def close(self) -> None:
        """关闭前调用（这时已经不再收消息）：还在等后面几项的相册马上处理，正在处理的等它处理完。
        重启后才到的几项会并进同一条投稿（见 core 的 receive）。"""
        for timer in self._timers.values():
            timer.cancel()
        self._timers.clear()
        await asyncio.gather(*self._running, *(self._flush(key) for key in list(self._buffers)))

    async def _flush_later(self, key: str) -> None:
        try:
            await asyncio.sleep(self.delay)
        except asyncio.CancelledError:
            return
        # 先摘掉 timer，之后 add() 不会再 cancel 这个正在处理的任务
        self._timers.pop(key, None)
        task = asyncio.current_task()
        self._running.add(task)
        try:
            await self._flush(key)
        finally:
            self._running.discard(task)

    async def _flush(self, key: str) -> None:
        messages = sorted(self._buffers.pop(key, []), key=lambda m: m.message_id)
        handler = self._handlers.pop(key, self.on_album)
        self._explicit.discard(key)
        if not messages:
            return
        try:
            await handler(messages)
        except Exception:
            log.exception("处理相册失败 %s", key)
            if self.on_error:
                try:
                    await self.on_error(messages[0])
                except Exception:
                    log.exception("回复相册出错提示失败 %s", key)
