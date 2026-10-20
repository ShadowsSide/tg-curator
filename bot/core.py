"""业务核心：投稿 → 审核 → 发布/定时 → 通知，以及后台调度和审核统计。

语言：审核群、频道相关文字用 self.lang（LANGUAGE 配置）；发给投稿人的文字用投稿人自己的语言（user_lang）。
"""
from __future__ import annotations

import asyncio
import html
import logging
from datetime import datetime

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import LinkPreviewOptions, Message, ReplyParameters, User as TgUser

from .album import AlbumCollector
from .config import Settings
from .db import DB, OPEN_STATES, Submission
from .entities import u16len
from .i18n import join_ids, normalize, on_off, t
from .keyboards import control_kb, schedule_kb, user_choice_kb
from .render import (
    caption_index, control_text, describe, extract_item, send_items, signature, stats_text, user_link,
)
from .timeutil import fmt_ts, now_ts, start_of_today, utc_offset

log = logging.getLogger(__name__)

# 话题名称前的状态图标
STATUS_ICON = {"draft": "📝", "pending": "⏳", "scheduled": "⏰", "published": "✅",
               "rejected": "❌", "failed": "⚠️", "cancelled": "🚫"}
TOPIC_COLOR = 7322096  # 蓝色（Telegram 只允许几种固定颜色）

SCHEDULER_TICK = 15  # 秒
DRAFT_TTL = 24 * 3600
STATS_MSG_KEY = "stats_msg_id"
NO_PREVIEW = LinkPreviewOptions(is_disabled=True)


def _reply_to(message_id: int | None) -> ReplyParameters | None:
    if not message_id:
        return None
    return ReplyParameters(message_id=message_id, allow_sending_without_reply=True)


class Core:
    def __init__(self, bot: Bot, db: DB, settings: Settings):
        self.bot = bot
        self.db = db
        self.s = settings
        self.lang = settings.language
        self.review_topics = settings.review_topics
        self.user_topics = settings.user_topics
        self.albums = AlbumCollector(settings.album_delay, self.receive)
        self.channel_post_base: str | None = None
        self._stats_lock = asyncio.Lock()
        self._tasks: list[asyncio.Task] = []

    # ---------- lifecycle ----------

    async def init(self) -> None:
        chat = await self.bot.get_chat(self.s.channel_id)
        if chat.username:
            self.channel_post_base = f"https://t.me/{chat.username}/"
        else:
            self.channel_post_base = f"https://t.me/c/{str(chat.id).removeprefix('-100')}/"
        await self.db.reset_stuck_publishing()

        # 话题模式的前提条件不满足时，降级为普通模式并在日志里说明，而不是启动失败
        if self.review_topics:
            review = await self.bot.get_chat(self.s.review_chat_id)
            if not review.is_forum:
                log.warning("REVIEW_TOPICS=true，但审核群没有开启话题功能，已改用普通模式")
                self.review_topics = False
        if self.user_topics:
            me = await self.bot.get_me()
            if not me.has_topics_enabled:
                log.warning("USER_TOPICS=true，但机器人没有在 @BotFather 开启话题模式，已改用普通模式")
                self.user_topics = False

    def start_background(self) -> None:
        self._tasks = [
            asyncio.create_task(self._scheduler_loop(), name="scheduler"),
            asyncio.create_task(self._reminder_loop(), name="reminder"),
        ]

    async def stop_background(self) -> None:
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)

    # ---------- 语言 ----------

    def lang_of(self, user: TgUser) -> str:
        """根据投稿人的 Telegram 客户端语言决定（USER_LANGUAGE=auto 时），否则用固定配置。"""
        if self.s.user_language != "auto":
            return self.s.user_language
        return normalize(user.language_code, fallback=self.lang)

    async def user_lang(self, user_id: int) -> str:
        """给投稿人发通知时用：取最近一次记录的语言。"""
        if self.s.user_language != "auto":
            return self.s.user_language
        user = await self.db.get_user(user_id)
        return user.lang if user and user.lang else self.lang

    def fmt(self, ts: int | None, lang: str | None = None) -> str:
        return fmt_ts(ts, self.s.tz, lang or self.lang)

    # ---------- helpers ----------

    def post_url(self, sub: Submission) -> str | None:
        if sub.channel_msg_id and self.channel_post_base:
            return f"{self.channel_post_base}{sub.channel_msg_id}"
        return None

    async def _signature(self, sub: Submission):
        user = await self.db.get_user(sub.user_id)
        return signature(sub, user, self.s.sign_template, self.s.anon_signature)

    async def notify(self, sub: Submission, key: str, **kw) -> None:
        """用投稿人自己的语言通知他，回复在他的投稿提示消息下面。"""
        lang = await self.user_lang(sub.user_id)
        await self.notify_user(sub.user_id, t(lang, key, **kw), reply_to=sub.user_msg_id, thread_id=sub.user_topic_id)

    async def notify_user(self, user_id: int, text: str, reply_to: int | None = None,
                          thread_id: int | None = None) -> None:
        try:
            await self.bot.send_message(user_id, text, reply_parameters=_reply_to(reply_to),
                                        message_thread_id=thread_id)
        except TelegramAPIError as e:  # 用户把机器人拉黑、从没启动过机器人等
            log.info("通知用户 %s 失败：%s", user_id, e)

    async def refresh_control(self, sid: int) -> None:
        await self.sync_topics(sid)
        sub = await self.db.get(sid)
        if not sub or not sub.review_msg_id:
            return
        user = await self.db.get_user(sub.user_id)
        try:
            await self.bot.edit_message_text(
                text=control_text(sub, user, self.s.tz, self.post_url(sub), self.lang),
                chat_id=self.s.review_chat_id,
                message_id=sub.review_msg_id,
                reply_markup=control_kb(sub, self.lang),
                link_preview_options=NO_PREVIEW,
            )
        except TelegramBadRequest as e:
            if "not modified" not in str(e):
                log.warning("更新控制消息 #%s 失败：%s", sid, e)

    async def show_schedule_picker(self, sid: int) -> None:
        sub = await self.db.get(sid)
        if not sub or not sub.review_msg_id:
            return
        await self.bot.edit_message_reply_markup(
            chat_id=self.s.review_chat_id,
            message_id=sub.review_msg_id,
            reply_markup=schedule_kb(sid, self.s.schedule_presets, self.s.tz, self.lang),
        )

    # ---------- 话题模式 ----------

    def _review_topic_name(self, sub: Submission, user) -> str:
        who = (user.full_name if user and user.full_name else str(sub.user_id))
        if sub.anonymous:
            who += f" ({t(self.lang, 'topic_anon')})"
        return f"{STATUS_ICON.get(sub.status, '')} #{sub.id} · {who} · {describe(sub.items, self.lang)}"[:128]

    def _user_topic_name(self, sub: Submission, lang: str) -> str:
        text = next((it["text"] for it in sub.items if it.get("text")), "")
        snippet = " ".join(text.split())[:30] or describe(sub.items, lang)
        return f"{STATUS_ICON.get(sub.status, '')} #{sub.id} · {snippet}"[:128]

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

    async def submit(self, sid: int, user_id: int, anonymous: bool, lang: str) -> str | None:
        sub = await self.db.get(sid)
        if not sub or sub.user_id != user_id:
            return t(lang, "invalid_sub")
        if not await self.db.transition(sid, ("draft",), "pending", anonymous=int(anonymous), submitted_at=now_ts()):
            return t(lang, "already_handled")
        await self._send_to_review(sid)
        await self.sync_topics(sid, review_is_fresh=True)
        await self.refresh_stats()
        return None

    async def cancel_draft(self, sid: int, user_id: int, lang: str) -> str | None:
        sub = await self.db.get(sid)
        if not sub or sub.user_id != user_id:
            return t(lang, "invalid_sub")
        if not await self.db.transition(sid, ("draft",), "cancelled"):
            return t(lang, "cannot_cancel")
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

    # ---------- 审核侧 ----------

    def _review_fields(self, sub: Submission, reviewer: TgUser | None, decision: str) -> dict:
        fields: dict = {"decision": decision}
        if reviewer:
            fields.update(reviewer_id=reviewer.id, reviewer_name=reviewer.full_name)
        if sub.decision != decision or not sub.reviewed_at:
            fields["reviewed_at"] = now_ts()
        return fields

    # ---------- 修改稿件（管理员 / 投稿人共用；lang 是调用方的语言） ----------

    async def edit(self, sid: int, editor: str, text: str, entities: list, link_preview: dict | None = None,
                   allowed: tuple[str, ...] = OPEN_STATES, lang: str | None = None) -> str | None:
        """修改稿件的文字（文字投稿改正文，媒体投稿改说明文字），格式由 entities 原样保留。"""
        lang = lang or self.lang
        sub = await self.db.get(sid)
        err = self._check_editable(sub, sid, allowed, lang)
        if err:
            return err
        items = [dict(it) for it in sub.items]
        target = items[caption_index(items)]
        is_text = target["type"] == "text"
        if is_text and not text.strip():
            return t(lang, "text_empty")
        target["text"], target["entities"] = text, entities
        if is_text:
            target["link_preview"] = link_preview
        return await self._save_edit(sub, items, editor, allowed, lang)

    async def replace_item(self, sid: int, index: int, new_item: dict, editor: str,
                           allowed: tuple[str, ...], lang: str) -> str | None:
        """投稿人用 Telegram 自带的“编辑”修改了原消息：整项替换（文字、格式、甚至换图都会同步）。"""
        sub = await self.db.get(sid)
        err = self._check_editable(sub, sid, allowed, lang)
        if err:
            return err
        items = [dict(it) for it in sub.items]
        if (items[index]["type"] == "text") != (new_item["type"] == "text"):
            return t(lang, "type_change")
        items[index] = new_item
        return await self._save_edit(sub, items, editor, allowed, lang)

    @staticmethod
    def _check_editable(sub: Submission | None, sid: int, allowed: tuple[str, ...], lang: str) -> str | None:
        if not sub:
            return t(lang, "sub_not_found", sid=sid)
        if sub.status in allowed:
            return None
        known = ("scheduled", "publishing", "published", "rejected", "cancelled", "failed")
        return t(lang, f"not_editable_{sub.status if sub.status in known else 'other'}", sid=sid)

    async def _save_edit(self, sub: Submission, items: list[dict], editor: str,
                         allowed: tuple[str, ...], lang: str) -> str | None:
        for it in items:
            limit = 4096 if it["type"] == "text" else 1024
            if u16len(it.get("text", "")) > limit:
                return t(lang, "too_long", n=u16len(it["text"]), limit=limit)
        # 第一次修改前的原稿单独保存；状态变了（比如刚好被发布）就不改
        ok = await self.db.update_if(
            sub.id, allowed, items=items, original_items=sub.original_items or sub.items,
            edited_by=editor, edited_at=now_ts(),
        )
        if not ok:
            return t(lang, "edit_race")
        sub = await self.db.get(sub.id)
        if sub.status != "draft":  # 草稿还没进审核群，不用发预览
            preview = await send_items(
                self.bot, self.s.review_chat_id, sub.items, sig=await self._signature(sub),
                spoiler=False, reply_to=sub.review_msg_id, thread_id=sub.review_topic_id,
            )
            await self.db.link_review_messages(sub.id, [m.message_id for m in preview])
            await self.refresh_control(sub.id)
        return None

    async def show_text(self, sid: int, chat_id: int, reply_to: int, lang: str | None = None) -> str | None:
        """把稿件当前的文字（带格式）发出来，方便复制后修改再 /edit。"""
        lang = lang or self.lang
        sub = await self.db.get(sid)
        if not sub:
            return t(lang, "sub_not_found", sid=sid)
        target = sub.items[caption_index(sub.items)]
        if not target.get("text"):
            return t(lang, "no_text_to_show", sid=sid)
        only_text = {"type": "text", "text": target["text"], "entities": target.get("entities", []),
                     "link_preview": {"is_disabled": True}}
        await send_items(self.bot, chat_id, [only_text], sig=("", []), spoiler=False, reply_to=reply_to)
        return None

    async def toggle_spoiler(self, sid: int) -> str:
        sub = await self.db.get(sid)
        if not sub or sub.status not in ("pending", "scheduled", "failed"):
            return t(self.lang, "toast_state_locked")
        await self.db.update(sid, spoiler=int(not sub.spoiler))
        await self.refresh_control(sid)
        return t(self.lang, "toast_spoiler", state=on_off(self.lang, not sub.spoiler))

    async def toggle_silent(self, sid: int) -> str:
        sub = await self.db.get(sid)
        if not sub or sub.status not in ("pending", "scheduled", "failed"):
            return t(self.lang, "toast_state_locked")
        await self.db.update(sid, silent=int(not sub.silent))
        await self.refresh_control(sid)
        return t(self.lang, "toast_silent", state=on_off(self.lang, not sub.silent))

    async def publish(self, sid: int, reviewer: TgUser | None = None,
                      from_states: tuple[str, ...] = ("pending", "scheduled", "failed")) -> str | None:
        """立即发布到频道。返回错误信息，成功返回 None。"""
        sub = await self.db.get(sid)
        if not sub:
            return t(self.lang, "sub_not_found", sid=sid)
        fields = self._review_fields(sub, reviewer, "approved")
        if not await self.db.transition(sid, from_states, "publishing", error=None, **fields):
            return t(self.lang, "status_changed")
        await self.refresh_control(sid)

        sub = await self.db.get(sid)
        try:
            sent = await send_items(
                self.bot, self.s.channel_id, sub.items, sig=await self._signature(sub),
                spoiler=sub.spoiler, silent=sub.silent,
            )
        except TelegramAPIError as e:
            log.exception("发布 #%s 失败", sid)
            await self.db.update(sid, status="failed", error=str(e)[:300])
            await self.refresh_control(sid)
            await self.refresh_stats()
            return t(self.lang, "publish_failed", error=e)

        await self.db.update(sid, status="published", published_at=now_ts(), channel_msg_id=sent[0].message_id)
        sub = await self.db.get(sid)
        url = self.post_url(sub)
        user_lang = await self.user_lang(sub.user_id)
        link = f'\n<a href="{url}">{t(user_lang, "view_post")}</a>' if url else ""
        await self.notify(sub, "notify_published", sid=sid, link=link)
        await self.refresh_control(sid)
        await self.refresh_stats()
        return None

    async def schedule(self, sid: int, ts: int, reviewer: TgUser) -> str | None:
        if ts <= now_ts() + 30:
            return t(self.lang, "time_past")
        sub = await self.db.get(sid)
        if not sub:
            return t(self.lang, "sub_not_found", sid=sid)
        was_pending = sub.status == "pending"
        fields = self._review_fields(sub, reviewer, "approved")
        if not await self.db.transition(sid, ("pending", "scheduled", "failed"), "scheduled",
                                        scheduled_at=ts, error=None, **fields):
            return t(self.lang, "status_changed")
        if was_pending:
            await self.notify(sub, "notify_scheduled", sid=sid, when=self.fmt(ts, await self.user_lang(sub.user_id)))
        await self.refresh_control(sid)
        await self.refresh_stats()
        return None

    async def unschedule(self, sid: int) -> str | None:
        ok = await self.db.transition(
            sid, ("scheduled",), "pending",
            scheduled_at=None, decision=None, reviewed_at=None, reviewer_id=None, reviewer_name=None,
        )
        if not ok:
            return t(self.lang, "status_changed")
        await self.refresh_control(sid)
        await self.refresh_stats()
        return None

    async def _mark_rejected(self, sub: Submission, reviewer: TgUser, reason: str | None) -> bool:
        fields = self._review_fields(sub, reviewer, "rejected")
        return await self.db.transition(
            sub.id, OPEN_STATES, "rejected", scheduled_at=None, reject_reason=reason, **fields
        )

    async def reject(self, sid: int, reviewer: TgUser, reason: str | None = None) -> str | None:
        sub = await self.db.get(sid)
        if not sub:
            return t(self.lang, "sub_not_found", sid=sid)
        if sub.status not in OPEN_STATES:
            key = {"published": "reject_published", "rejected": "reject_rejected",
                   "publishing": "reject_publishing"}.get(sub.status, "reject_other")
            return t(self.lang, key, sid=sid)
        if not await self._mark_rejected(sub, reviewer, reason):
            return t(self.lang, "status_changed")
        lang = await self.user_lang(sub.user_id)
        await self.notify_user(sub.user_id, t(lang, "notify_rejected", sid=sid) + _reason_line(lang, reason),
                               reply_to=sub.user_msg_id, thread_id=sub.user_topic_id)
        await self.refresh_control(sid)
        await self.refresh_stats()
        return None

    async def ban_user(self, user_id: int, reviewer: TgUser, reason: str | None = None) -> list[int]:
        """封禁用户，并自动拒绝其所有未处理的来稿（待审核 / 定时中 / 发布失败），草稿直接作废。
        返回被拒绝的投稿编号。"""
        await self.db.ban(user_id, reason, reviewer.full_name)
        await self.db.cancel_drafts_of(user_id)

        rejected = []
        for sub in await self.db.open_by_user(user_id):
            if await self._mark_rejected(sub, reviewer, reason or t(self.lang, "ban_default_reason")):
                rejected.append(sub.id)

        lang = await self.user_lang(user_id)
        text = t(lang, "banned") + _reason_line(lang, reason)
        if rejected:
            text += t(lang, "notify_banned_rejected", n=len(rejected), ids=join_ids(lang, rejected))
        await self.notify_user(user_id, text)

        for sid in rejected:
            await self.refresh_control(sid)
        await self.refresh_stats()
        return rejected

    async def unban_user(self, user_id: int) -> bool:
        if not await self.db.unban(user_id):
            return False
        await self.notify_user(user_id, t(await self.user_lang(user_id), "notify_unbanned"))
        return True

    # ---------- 审核统计 ----------

    async def _stats_text(self) -> str:
        since = start_of_today(self.s.tz) if self.s.stats_scope == "today" else 0
        accepted, rejected, pending = await self.db.review_counts(since)
        return stats_text(accepted, rejected, pending, datetime.now(self.s.tz), self.lang)

    async def post_stats(self) -> None:
        """发一条新的统计消息，并删掉上一条，保证群里只有一条最新的。"""
        async with self._stats_lock:
            old = await self.db.kv_get(STATS_MSG_KEY)
            msg = await self.bot.send_message(self.s.review_chat_id, await self._stats_text())
            await self.db.kv_set(STATS_MSG_KEY, str(msg.message_id))
            if old:
                try:
                    await self.bot.delete_message(self.s.review_chat_id, int(old))
                except TelegramAPIError:
                    pass

    async def refresh_stats(self) -> None:
        """审核状态变化时就地更新当前那条统计消息（“更新于”时间随之刷新）。"""
        async with self._stats_lock:
            mid = await self.db.kv_get(STATS_MSG_KEY)
            if not mid:
                return
            try:
                await self.bot.edit_message_text(
                    text=await self._stats_text(), chat_id=self.s.review_chat_id, message_id=int(mid)
                )
            except TelegramBadRequest as e:
                if "not modified" in str(e):
                    return
                log.info("统计消息无法编辑（%s），下次提醒时重发", e)
                await self.db.kv_set(STATS_MSG_KEY, None)

    async def activity_text(self, days: int) -> str:
        lang = self.lang
        since = now_ts() - days * 86400
        rows = await self.db.activity(since, utc_offset(self.s.tz))
        total, people = await self.db.activity_totals(since)
        if not rows:
            return t(lang, "activity_none", days=days)
        lines = [t(lang, "activity_head", days=days, people=people, total=total), ""]
        for i, r in enumerate(rows, 1):
            reviewed = (r["approved"] or 0) + (r["rejected"] or 0)
            rate = f"{r['approved'] / reviewed * 100:.0f}%" if reviewed else "-"
            name = user_link(await self.db.get_user(r["user_id"]), r["user_id"])
            ban = " 🚫" if r["banned"] else ""
            anon = t(lang, "activity_anon", n=r["anonymous"]) if r["anonymous"] else ""
            lines.append(f"{i}. {name}{ban}\n" + t(
                lang, "activity_line", total=r["total"], approved=r["approved"] or 0, rate=rate, anon=anon,
                days=r["active_days"], last=self.fmt(r["last_at"], lang),
            ))
        return "\n".join(lines)

    async def user_text(self, user_id: int, for_admin: bool, lang: str | None = None) -> str:
        lang = lang or self.lang
        s = await self.db.user_summary(user_id)
        if not s["total"]:
            return t(lang, "no_records_admin", uid=user_id) if for_admin else t(lang, "no_records_self")
        reviewed = s["published"] + s["scheduled"] + s["rejected"]
        rate = f"{(s['published'] + s['scheduled']) / reviewed * 100:.0f}%" if reviewed else "-"
        head = t(lang, "me_head")
        if for_admin:
            user = await self.db.get_user(user_id)
            banned = ""
            if user and user.banned:
                banned = (t(lang, "user_banned_line", when=self.fmt(user.banned_at, lang),
                            by=html.escape(user.banned_by or "")) + _reason_line(lang, user.ban_reason))
            head = f"📈 {user_link(user, user_id)}  <code>{user_id}</code>{banned}"
        return f"{head}\n" + t(
            lang, "user_summary", total=s["total"], published=s["published"], scheduled=s["scheduled"],
            pending=s["pending"], rejected=s["rejected"], rate=rate, anonymous=s["anonymous"],
            first=self.fmt(s["first_at"], lang), last=self.fmt(s["last_at"], lang),
        )

    async def queue_text(self) -> str:
        subs = await self.db.upcoming_scheduled()
        if not subs:
            return t(self.lang, "queue_empty")
        lines = [t(self.lang, "queue_head"), ""]
        for sub in subs:
            flags = (" 🙈" if sub.spoiler else "") + (" 🔕" if sub.silent else "")
            lines.append(f"{self.fmt(sub.scheduled_at)} · #{sub.id} · {describe(sub.items, self.lang)}{flags}")
        return "\n".join(lines)

    # ---------- 后台任务 ----------

    async def _scheduler_loop(self) -> None:
        while True:
            try:
                for sub in await self.db.due_scheduled(now_ts()):
                    err = await self.publish(sub.id, from_states=("scheduled",))
                    if err:
                        log.warning("定时发布 #%s：%s", sub.id, err)
                for sub in await self.db.expire_drafts(now_ts() - DRAFT_TTL):
                    if sub.user_msg_id:
                        try:
                            await self.bot.edit_message_text(
                                t(await self.user_lang(sub.user_id), "draft_expired"),
                                chat_id=sub.user_id, message_id=sub.user_msg_id,
                            )
                        except TelegramAPIError:
                            pass
                    await self.sync_topics(sub.id)
            except Exception:
                log.exception("调度循环出错")
            await asyncio.sleep(SCHEDULER_TICK)

    async def _reminder_loop(self) -> None:
        interval = self.s.reminder_interval_min * 60
        if interval <= 0:
            return
        while True:
            # 按本地时间从零点起对齐，例如 60 分钟就在整点提醒
            elapsed = now_ts() - start_of_today(self.s.tz)
            await asyncio.sleep(interval - elapsed % interval + 1)
            try:
                if self.s.in_quiet_hours(datetime.now(self.s.tz).hour):
                    continue
                _, _, pending = await self.db.review_counts(0)
                if self.s.reminder_only_when_pending and pending == 0:
                    continue
                await self.post_stats()
            except Exception:
                log.exception("审核提醒出错")


def _reason_line(lang: str, reason: str | None) -> str:
    return t(lang, "reason_line", reason=html.escape(reason)) if reason else ""


def explicit_reply(m: Message) -> Message | None:
    """用户真正“回复”的那条消息。
    话题里的每条消息都会隐式地回复话题的第一条消息（创建话题的服务消息），那不算回复。"""
    r = m.reply_to_message
    if r is None:
        return None
    if r.forum_topic_created or (m.is_topic_message and r.message_id == m.message_thread_id):
        return None
    return r


def topic_of(m: Message) -> int | None:
    return m.message_thread_id if m.is_topic_message else None


def mention(user: TgUser) -> str:
    return f'<a href="tg://user?id={user.id}">{html.escape(user.full_name)}</a>'
