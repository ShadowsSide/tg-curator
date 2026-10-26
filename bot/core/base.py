"""Core 的公共部分：初始化、生命周期、语言、通知、控制消息，以及各模块共用的常量和工具函数。

语言：审核群、频道相关文字用 self.lang（LANGUAGE 配置）；发给投稿人的文字用投稿人自己的语言（user_lang）。
"""
from __future__ import annotations

import asyncio
import html
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import InlineKeyboardMarkup, LinkPreviewOptions, Message, ReplyParameters, User as TgUser

from ..album import AlbumCollector
from ..config import Settings
from ..db import DB, Submission, User
from ..i18n import normalize, t
from ..keyboards import confirm_kb, control_kb, reasons_kb, schedule_kb
from ..render import control_text, signature
from ..timeutil import fmt_ts

log = logging.getLogger(__name__)

# 话题名称前的状态图标
STATUS_ICON = {"draft": "📝", "pending": "⏳", "scheduled": "⏰", "published": "✅",
               "rejected": "❌", "failed": "⚠️", "cancelled": "🚫"}
TOPIC_COLOR = 7322096  # 蓝色（Telegram 只允许几种固定颜色）

SCHEDULER_TICK = 15  # 秒
DRAFT_TTL = 24 * 3600
STATS_MSG_KEY = "stats_msg_id"
STATS_DEBOUNCE = 3  # 秒：统计消息在这段时间内的多次更新合并成一次编辑（减少审核群里的请求，避免限流）
POSTPONE_MARGIN = 5  # 秒：发布被限流时，在 Telegram 要求的等待时间之后再多留一点余量
NO_PREVIEW = LinkPreviewOptions(is_disabled=True)


def _reply_to(message_id: int | None) -> ReplyParameters | None:
    if not message_id:
        return None
    return ReplyParameters(message_id=message_id, allow_sending_without_reply=True)


class CoreBase:
    def __init__(self, bot: Bot, db: DB, settings: Settings):
        self.bot = bot
        self.db = db
        self.s = settings
        self.lang = settings.language
        self.review_topics = settings.review_topics
        self.user_topics = settings.user_topics
        self.albums = AlbumCollector(settings.album_delay, self.receive)
        self.channel_post_base: str | None = None
        self.channel_chat_id: int | None = None
        self.channel_linked_chat_id: int | None = None  # 发布频道的关联群组（评论区）
        self._stats_lock = asyncio.Lock()
        self._stats_dirty = False
        self._stats_task: asyncio.Task | None = None
        self._tasks: list[asyncio.Task] = []

    # ---------- lifecycle ----------

    async def init(self) -> None:
        chat = await self.bot.get_chat(self.s.channel_id)
        self.channel_chat_id = chat.id
        self.channel_linked_chat_id = chat.linked_chat_id
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
        if self._stats_task:
            self._tasks.append(self._stats_task)
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

    # ---------- 给处理函数用的查询：处理函数只经过 Core，不直接访问数据库 ----------

    async def get_submission(self, sid: int) -> Submission | None:
        return await self.db.get(sid)

    async def get_user(self, user_id: int) -> User | None:
        return await self.db.get_user(user_id)

    async def sid_for_review_message(self, message_id: int) -> int | None:
        """审核群里这条消息（预览、控制消息、转来的 /msg）属于哪条投稿。"""
        return await self.db.sid_by_review_message(message_id)

    async def sid_for_review_topic(self, thread_id: int) -> int | None:
        return await self.db.sid_by_review_topic(thread_id)

    async def find_user_message(self, user_id: int, message_id: int) -> tuple[int, int | None] | None:
        """投稿人私聊里这条消息属于哪条投稿：(投稿, 第几项) 或 (投稿, None)。"""
        return await self.db.find_by_user_message(user_id, message_id)

    async def sid_for_relay_message(self, user_id: int, message_id: int) -> int | None:
        return await self.db.sid_by_relay_message(user_id, message_id)

    async def is_review_relay_message(self, message_id: int) -> bool:
        return await self.db.is_review_relay_message(message_id)

    # ---------- helpers ----------

    def post_url(self, sub: Submission) -> str | None:
        if sub.channel_msg_id and self.channel_post_base:
            return f"{self.channel_post_base}{sub.channel_msg_id}"
        return None

    def review_link(self, sub: Submission) -> str | None:
        """审核群里这条投稿控制消息的链接（群成员可点开跳转），代替投稿编号来指认投稿。"""
        if not sub.review_msg_id:
            return None
        chat = str(self.s.review_chat_id).removeprefix("-100")
        return f"https://t.me/c/{chat}/{sub.review_msg_id}"

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
        await self._swap_control_kb(sid, schedule_kb(sid, self.s.schedule_presets, self.s.tz, self.lang))

    async def show_confirm(self, sid: int, action: str, v: int = 0) -> None:
        """发布 / 拒绝 / 封禁的二次确认：把控制消息的按钮换成“确认 / 返回”。拒绝时 v 是选的理由。"""
        detail = self.s.reject_template(v) if action == "reject" else None
        await self._swap_control_kb(sid, confirm_kb(sid, action, self.lang, v, detail))

    async def show_reject_reasons(self, sid: int) -> None:
        await self._swap_control_kb(sid, reasons_kb(sid, self.s.reject_templates, self.lang))

    async def _swap_control_kb(self, sid: int, kb: InlineKeyboardMarkup) -> None:
        """只换控制消息的按钮（定时面板、确认面板），文字不变；点“返回”时由 refresh_control 恢复。"""
        sub = await self.db.get(sid)
        if not sub or not sub.review_msg_id:
            return
        try:
            await self.bot.edit_message_reply_markup(
                chat_id=self.s.review_chat_id, message_id=sub.review_msg_id, reply_markup=kb,
            )
        except TelegramBadRequest as e:
            if "not modified" not in str(e):  # 连点两下：面板已经是这个样子
                raise


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
