"""审核员权限：谁可以在审核群里点按钮、用命令。

REVIEWERS 配置（逗号分隔，可组合）：
  admins        审核群的管理员和群主（默认）
  all           审核群里的所有成员
  123456,789    指定的用户 ID，例如 admins,123456 = 管理员 + 这个人
管理员身份通过 getChatMember 查询并缓存，避免每次操作都请求一次接口。
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware, Bot
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, Message, TelegramObject

from .errors import ConfigError
from .i18n import t

log = logging.getLogger(__name__)

ADMIN_TTL = 300  # 秒：“是管理员”的缓存时间
NON_ADMIN_TTL = 60  # 秒：“不是管理员”的缓存时间更短，刚被设为管理员的人很快就能用
_ADMIN_STATUSES = (ChatMemberStatus.CREATOR, ChatMemberStatus.ADMINISTRATOR)


@dataclass(frozen=True)
class ReviewerPolicy:
    everyone: bool
    admins: bool
    user_ids: frozenset[int]

    @classmethod
    def parse(cls, value: str) -> "ReviewerPolicy":
        tokens = [x.strip().lower() for x in value.split(",") if x.strip()] or ["admins"]
        ids, everyone, admins = set(), False, False
        for token in tokens:
            if token == "all":
                everyone = True
            elif token == "admins":
                admins = True
            elif token.lstrip("-").isdigit():
                ids.add(int(token))
            else:
                raise ConfigError("cfg_reviewers", value=token)
        return cls(everyone, admins, frozenset(ids))


class ReviewerCheck:
    def __init__(self, policy: ReviewerPolicy, review_chat_id: int):
        self.policy = policy
        self.review_chat_id = review_chat_id
        self._cache: dict[int, tuple[bool, float]] = {}
        self._inflight: dict[int, asyncio.Task] = {}  # 同一个人同时多次操作时，只查询一次

    async def allowed(self, bot: Bot, user_id: int, sender_chat_id: int | None = None, is_bot: bool = False) -> bool:
        p = self.policy
        # 以群身份匿名发言的只能是这个群的管理员（这时 from_user 是 Telegram 的匿名管理员机器人，要先于下面的判断）
        if sender_chat_id == self.review_chat_id:
            return p.everyone or p.admins
        if is_bot:  # 机器人不算审核员
            return False
        if p.everyone or user_id in p.user_ids:
            return True
        if not p.admins:
            return False
        return await self._is_admin(bot, user_id)

    async def _is_admin(self, bot: Bot, user_id: int) -> bool:
        cached = self._cache.get(user_id)
        if cached and cached[1] > time.monotonic():
            return cached[0]
        task = self._inflight.get(user_id)
        if task is None:
            task = asyncio.create_task(self._lookup(bot, user_id))
            self._inflight[user_id] = task
            task.add_done_callback(lambda _: self._inflight.pop(user_id, None))
        return await asyncio.shield(task)

    async def _lookup(self, bot: Bot, user_id: int) -> bool:
        try:
            member = await bot.get_chat_member(self.review_chat_id, user_id)
            is_admin = member.status in _ADMIN_STATUSES
        except TelegramAPIError as e:
            log.warning("查询 %s 的管理员身份失败：%s", user_id, e)
            return False  # 查不到时按无权限处理，且不缓存
        self._cache[user_id] = (is_admin, time.monotonic() + (ADMIN_TTL if is_admin else NON_ADMIN_TTL))
        return is_admin


class ReviewerOnly(BaseMiddleware):
    """挂在审核群路由上（内层中间件：只在匹配到处理函数后执行），没有权限就不执行处理函数。"""

    def __init__(self, check: ReviewerCheck, lang: str):
        self.check = check
        self.lang = lang

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = getattr(event, "from_user", None)
        sender_chat = getattr(event, "sender_chat", None)
        if user and await self.check.allowed(data["bot"], user.id, sender_chat.id if sender_chat else None,
                                             is_bot=user.is_bot):
            return await handler(event, data)

        denied = t(self.lang, "no_permission")
        if isinstance(event, CallbackQuery):
            await event.answer(denied, show_alert=True)
        elif isinstance(event, Message) and (event.text or "").startswith("/"):
            await event.reply(denied)  # 普通聊天消息直接忽略，只对命令给出提示
        return None
