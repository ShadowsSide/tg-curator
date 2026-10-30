"""审核统计提醒、投稿人活跃度、个人统计、定时队列。"""
from __future__ import annotations

import asyncio
import html
import logging
from datetime import datetime

from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import InlineKeyboardMarkup

from ..i18n import t
from ..keyboards import user_card_kb
from ..render import describe, stats_text, user_link
from ..timeutil import now_ts, start_of_today, utc_offset

from .base import CoreBase, STATS_MSG_KEY, STATS_DEBOUNCE, _reason_line

log = logging.getLogger(__name__)


class StatsMixin(CoreBase):
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
        """审核状态变化时更新统计消息。不立即编辑：STATS_DEBOUNCE 秒内的多次变化合并成一次编辑。"""
        self._stats_dirty = True
        if self._stats_task is None or self._stats_task.done():
            self._stats_task = asyncio.create_task(self._stats_worker(), name="stats-refresh")

    async def _stats_worker(self) -> None:
        # 等待期间又有变化会重新置位 dirty，循环再刷新一次，保证最后的状态一定会显示出来
        while self._stats_dirty:
            self._stats_dirty = False
            await asyncio.sleep(STATS_DEBOUNCE)
            try:
                await self._refresh_stats_now()
            except Exception:
                log.exception("刷新统计消息出错")

    async def _refresh_stats_now(self) -> None:
        """就地更新当前那条统计消息（“更新于”时间随之刷新）。"""
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
        banned = ""
        if for_admin:
            user = await self.db.get_user(user_id)
            if user and user.banned:
                banned = (t(lang, "user_banned_line", when=self.fmt(user.banned_at, lang),
                            by=html.escape(user.banned_by or "")) + _reason_line(lang, user.ban_reason))
        if not s["total"]:  # 没投过稿也可能被预先封禁，管理员要看得到
            return t(lang, "no_records_admin", uid=user_id) + banned if for_admin else t(lang, "no_records_self")
        reviewed = s["published"] + s["scheduled"] + s["rejected"]
        rate = f"{(s['published'] + s['scheduled']) / reviewed * 100:.0f}%" if reviewed else "-"
        head = t(lang, "me_head")
        if for_admin:
            head = f"📈 {user_link(user, user_id)}  <code>{user_id}</code>{banned}"
        return f"{head}\n" + t(
            lang, "user_summary", total=s["total"], published=s["published"], scheduled=s["scheduled"],
            pending=s["pending"], rejected=s["rejected"], rate=rate, anonymous=s["anonymous"],
            first=self.fmt(s["first_at"], lang), last=self.fmt(s["last_at"], lang),
        )

    async def user_card(self, user_id: int) -> tuple[str, InlineKeyboardMarkup]:
        """/user 的结果：投稿人统计，下面是按当前状态显示的“封禁”或“解除封禁”按钮；
        被封禁且审核群里还有 TA 的稿件时，再加“删除稿件”按钮（显示条数）。"""
        user = await self.db.get_user(user_id)
        banned = bool(user and user.banned)
        purgeable = len(await self.db.review_traces(self.s.review_chat_id, user_id)) if banned else 0
        return (await self.user_text(user_id, for_admin=True),
                user_card_kb(user_id, banned, self.lang, purgeable))

    async def queue_text(self) -> str:
        subs = await self.db.upcoming_scheduled()
        if not subs:
            return t(self.lang, "queue_empty")
        lines = [t(self.lang, "queue_head"), ""]
        for sub in subs:
            flags = (" 🙈" if sub.spoiler else "") + (" 🔕" if sub.silent else "")
            link = self.review_link(sub)
            view = f' · <a href="{link}">{t(self.lang, "queue_view")}</a>' if link else ""
            lines.append(f"{self.fmt(sub.scheduled_at)} · {describe(sub.items, self.lang)}{flags}{view}")
        return "\n".join(lines)
