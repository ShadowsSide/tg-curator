"""投稿人的操作频率限制：/msg 和改稿每次都会在审核群发一条消息，不限制的话可以刷屏。

只记在内存里：重启后清零；机器人只跑一个实例，不需要共享。
"""
from __future__ import annotations

import math
import time
from collections import deque
from typing import Callable

LIMIT = 5  # 每人在 WINDOW 秒内最多这么多次（/msg 和改稿合计）
WINDOW = 60


class Throttle:
    def __init__(self, limit: int = LIMIT, window: float = WINDOW, clock: Callable[[], float] = time.monotonic):
        self.limit = limit
        self.window = window
        self.clock = clock
        self._recent: dict[int, deque[float]] = {}  # 用户 → 最近几次的时间

    def hit(self, user_id: int) -> int:
        """记一次。没超过限制返回 0（并记下这次）；超过了返回还要等几秒，这次不记。"""
        now = self.clock()
        recent = self._recent.setdefault(user_id, deque())
        while recent and recent[0] <= now - self.window:
            recent.popleft()
        if len(recent) >= self.limit:
            return max(1, math.ceil(recent[0] + self.window - now))
        recent.append(now)
        return 0

    def prune(self) -> None:
        """删掉已经过了时间窗口的用户，免得字典一直变大（调度循环定期调用）。"""
        now = self.clock()
        for user_id in [u for u, r in self._recent.items() if not r or r[-1] <= now - self.window]:
            del self._recent[user_id]
