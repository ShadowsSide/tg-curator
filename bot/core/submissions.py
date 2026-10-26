"""投稿人一侧：收到内容、创建草稿、提交到审核群、取消。"""
from __future__ import annotations

from aiogram.types import Message, User as TgUser

from .. import spam
from ..errors import Notice, notice
from ..i18n import t
from ..keyboards import control_kb, user_choice_kb
from ..render import control_text, describe, extract_item, send_items
from ..timeutil import now_ts

from .base import CoreBase, NO_PREVIEW, _reply_to, _reason_line


class SubmissionsMixin(CoreBase):
    # ---------- 用户侧 ----------

    async def touch(self, user: TgUser) -> None:
        await self.db.touch_user(user.id, user.username, user.full_name, self.lang_of(user))

    async def receive(self, messages: list[Message]) -> None:
        """收到用户内容（单条或整个相册），创建草稿并让用户选署名/匿名。"""
        first = messages[0]
        user = first.from_user
        lang = self.lang_of(user)
        await self.touch(user)

        db_user = await self.db.get_user(user.id)
        if db_user and db_user.banned:
            await first.reply(t(lang, "banned") + _reason_line(lang, db_user.ban_reason))
            return
        if await self.db.count_open_by_user(user.id) >= self.s.max_pending_per_user:
            await first.reply(t(lang, "too_many"))
            return

        items = [extract_item(m) for m in messages]
        if any(i is None for i in items):
            await first.reply(t(lang, "unsupported"))
            return

        # 用户自己给媒体加了剧透时，默认保留剧透
        spoiler = any(i.get("spoiler") for i in items)
        sid = await self.db.create_draft(user.id, items, silent=self.s.default_silent, spoiler=spoiler)
        text, kb = t(lang, "choose_mode", desc=describe(items, lang)), user_choice_kb(sid, lang)

        topic_id = await self._user_topic_for(sid, messages, lang) if self.user_topics else None
        if topic_id and topic_id != first.message_thread_id:
            # 新建的话题：把投稿内容复制进去（格式、相册分组都保持不变），提示消息回复在副本下面
            copies = await self.bot.copy_messages(
                user.id, user.id, [m.message_id for m in messages], message_thread_id=topic_id)
            prompt = await self.bot.send_message(
                user.id, text, reply_markup=kb, message_thread_id=topic_id,
                reply_parameters=_reply_to(copies[0].message_id if copies else None))
        else:
            prompt = await first.reply(text, reply_markup=kb)
        await self.db.update(sid, user_msg_id=prompt.message_id, user_topic_id=topic_id, topic_status="draft")

    async def _user_topic_for(self, sid: int, messages: list[Message], lang: str) -> int | None:
        """私聊话题模式：投稿人在自己新建、还没被占用的话题里发的，就用这个话题；否则新建一个。"""
        first = messages[0]
        thread = first.message_thread_id if first.is_topic_message else None
        sub = await self.db.get(sid)
        if thread and not await self.db.sid_by_user_topic(first.from_user.id, thread):
            await self._try(self.bot.edit_forum_topic(first.from_user.id, thread, name=self._user_topic_name(sub, lang)))
            return thread
        return await self._create_topic(first.from_user.id, self._user_topic_name(sub, lang))

    async def submit(self, sid: int, user_id: int, anonymous: bool) -> Notice | None:
        sub = await self.db.get(sid)
        if not sub or sub.user_id != user_id:
            return notice("invalid_sub")
        err = await self._cooldown(user_id)
        if err:
            return err
        hits = spam.check(sub.items, self.s.spam_rules)
        if hits and self.s.spam_action == "block":
            # 不告诉投稿人命中了哪个关键词，免得照着绕过；草稿保留，改了内容可以重新提交
            return notice("spam_blocked_" + hits[0]["k"], **({"max": hits[0]["max"]} if "max" in hits[0] else {}))
        if not await self.db.transition(sid, ("draft",), "pending", anonymous=int(anonymous), submitted_at=now_ts(),
                                        spam_flags=hits or None):
            return notice("already_handled")
        await self._send_to_review(sid)
        await self.sync_topics(sid, review_is_fresh=True)
        await self.refresh_stats()
        return None

    async def _cooldown(self, user_id: int) -> Notice | None:
        """新用户冷却：还没有稿件发布过的投稿人，距上次提交不足 NEW_USER_COOLDOWN_MINUTES 分钟就不能再提交。"""
        minutes = self.s.new_user_cooldown_min
        if not minutes:
            return None
        summary = await self.db.user_summary(user_id)
        if summary["published"] or not summary["last_at"]:
            return None
        wait = summary["last_at"] + minutes * 60 - now_ts()
        return notice("cooldown", m=-(-wait // 60)) if wait > 0 else None  # 向上取整到分钟

    async def cancel_draft(self, sid: int, user_id: int) -> Notice | None:
        sub = await self.db.get(sid)
        if not sub or sub.user_id != user_id:
            return notice("invalid_sub")
        if not await self.db.transition(sid, ("draft",), "cancelled"):
            return notice("cannot_cancel")
        await self.sync_topics(sid)
        return None

    async def _send_to_review(self, sid: int) -> None:
        sub = await self.db.get(sid)
        user = await self.db.get_user(sub.user_id)
        # 话题模式：每条投稿在审核群里单独一个话题
        topic_id = None
        if self.review_topics:
            topic_id = await self._create_topic(self.s.review_chat_id, self._review_topic_name(sub, user))
        # 预览就是频道里最终的样子（含落款），方便审核
        preview = await send_items(
            self.bot, self.s.review_chat_id, sub.items, sig=await self._signature(sub), spoiler=False,
            thread_id=topic_id,
        )
        ctrl = await self.bot.send_message(
            self.s.review_chat_id,
            control_text(sub, user, self.s.tz, None, self.lang),
            reply_markup=control_kb(sub, self.lang),
            reply_parameters=_reply_to(preview[0].message_id),
            link_preview_options=NO_PREVIEW,
            message_thread_id=topic_id,
        )
        await self.db.update(sid, review_msg_id=ctrl.message_id, review_topic_id=topic_id)
        await self.db.link_review_messages(sid, [m.message_id for m in preview] + [ctrl.message_id])
