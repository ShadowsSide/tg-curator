"""话题模式：每条投稿在审核群 / 投稿人私聊里各一个话题，名称随状态变化。"""
from __future__ import annotations

import logging

from aiogram.exceptions import TelegramAPIError

from ..db import Submission
from ..i18n import t
from ..render import describe

from .base import CoreBase, STATUS_ICON, TOPIC_COLOR

log = logging.getLogger(__name__)


class TopicsMixin(CoreBase):
    # ---------- 话题模式 ----------

    def _review_topic_name(self, sub: Submission, user) -> str:
        who = (user.full_name if user and user.full_name else str(sub.user_id))
        if sub.anonymous:
            who += f" ({t(self.lang, 'topic_anon')})"
        return f"{STATUS_ICON.get(sub.status, '')} {who} · {describe(sub.items, self.lang)}"[:128]

    def _user_topic_name(self, sub: Submission, lang: str) -> str:
        text = next((it["text"] for it in sub.items if it.get("text")), "")
        snippet = " ".join(text.split())[:30] or describe(sub.items, lang)
        return f"{STATUS_ICON.get(sub.status, '')} {snippet}"[:128]

    async def _create_topic(self, chat_id: int, name: str) -> int | None:
        try:
            topic = await self.bot.create_forum_topic(chat_id, name, icon_color=TOPIC_COLOR)
            return topic.message_thread_id
        except TelegramAPIError as e:  # 没有管理话题权限等：退回普通模式
            log.warning("创建话题失败（%s），这条投稿改用普通模式", e)
            return None

    async def sync_topics(self, sid: int, review_is_fresh: bool = False) -> None:
        """状态变化后更新话题名称（前面的状态图标）；审核群里已发布/已拒绝的话题顺便关闭。
        review_is_fresh：审核话题刚按当前状态创建，不用再改名（每次改名都会在话题里留一条服务消息）。"""
        sub = await self.db.get(sid)
        if not sub or sub.status == sub.topic_status or sub.status == "publishing":
            return
        if not sub.review_topic_id and not sub.user_topic_id:
            return
        if sub.review_topic_id and not review_is_fresh:
            user = await self.db.get_user(sub.user_id)
            await self._try(self.bot.edit_forum_topic(
                self.s.review_chat_id, sub.review_topic_id, name=self._review_topic_name(sub, user)))
            if sub.status in ("published", "rejected"):
                await self._try(self.bot.close_forum_topic(self.s.review_chat_id, sub.review_topic_id))
        if sub.user_topic_id:
            lang = await self.user_lang(sub.user_id)
            await self._try(self.bot.edit_forum_topic(
                sub.user_id, sub.user_topic_id, name=self._user_topic_name(sub, lang)))
        await self.db.update(sid, topic_status=sub.status)

    @staticmethod
    async def _try(call) -> None:
        try:
            await call
        except TelegramAPIError as e:
            log.info("话题操作失败：%s", e)
