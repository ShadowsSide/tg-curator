"""审核动作：剧透 / 静音开关、发布、定时、拒绝、封禁。"""
from __future__ import annotations

import logging

from aiogram.exceptions import TelegramAPIError, TelegramRetryAfter
from aiogram.types import User as TgUser

from ..db import OPEN_STATES, Submission
from ..errors import Notice, notice
from ..i18n import t
from ..render import send_items
from ..timeutil import now_ts

from .base import CoreBase, POSTPONE_MARGIN, _reason_line

log = logging.getLogger(__name__)


class ReviewMixin(CoreBase):
    # ---------- 审核侧 ----------

    def _review_fields(self, sub: Submission, reviewer: TgUser | None, decision: str) -> dict:
        fields: dict = {"decision": decision}
        if reviewer:
            fields.update(reviewer_id=reviewer.id, reviewer_name=reviewer.full_name)
        if sub.decision != decision or not sub.reviewed_at:
            fields["reviewed_at"] = now_ts()
        return fields

    async def toggle_spoiler(self, sid: int) -> Notice:
        sub = await self.db.get(sid)
        if not sub or sub.status not in ("pending", "scheduled", "failed"):
            return notice("toast_state_locked")
        await self.db.update(sid, spoiler=int(not sub.spoiler))
        await self.refresh_control(sid)
        return notice("toast_spoiler", state=notice("on" if not sub.spoiler else "off"))

    async def toggle_silent(self, sid: int) -> Notice:
        sub = await self.db.get(sid)
        if not sub or sub.status not in ("pending", "scheduled", "failed"):
            return notice("toast_state_locked")
        await self.db.update(sid, silent=int(not sub.silent))
        await self.refresh_control(sid)
        return notice("toast_silent", state=notice("on" if not sub.silent else "off"))

    async def publish(self, sid: int, reviewer: TgUser | None = None,
                      from_states: tuple[str, ...] = ("pending", "scheduled", "failed")) -> Notice | None:
        """立即发布到频道。返回错误信息，成功返回 None。"""
        sub = await self.db.get(sid)
        if not sub:
            return notice("sub_not_found", sid=sid)
        fields = self._review_fields(sub, reviewer, "approved")
        if not await self.db.transition(sid, from_states, "publishing", error=None, **fields):
            return notice("status_changed")
        await self.refresh_control(sid)

        sub = await self.db.get(sid)
        try:
            sent = await send_items(
                self.bot, self.s.channel_id, sub.items, sig=await self._signature(sub),
                spoiler=sub.spoiler, silent=sub.silent,
            )
        except TelegramRetryAfter as e:
            # 等待时间太长、请求层的自动重试没能解决：频道里什么都还没发出去，改为稍后自动发布，而不是“发布失败”
            ts = now_ts() + e.retry_after + POSTPONE_MARGIN
            log.warning("发布 #%s 被限流 %s 秒，改为 %s 自动发布", sid, e.retry_after, ts)
            await self.db.update(sid, status="scheduled", scheduled_at=ts, error=None)
            await self.refresh_control(sid)
            await self.refresh_stats()
            return notice("publish_postponed", when=self.fmt(ts))
        except TelegramAPIError as e:
            log.exception("发布 #%s 失败", sid)
            await self.db.update(sid, status="failed", error=str(e)[:300])
            await self.refresh_control(sid)
            await self.refresh_stats()
            return notice("publish_failed", error=str(e))

        await self.db.update(sid, status="published", published_at=now_ts(), channel_msg_id=sent[0].message_id)
        sub = await self.db.get(sid)
        url = self.post_url(sub)
        user_lang = await self.user_lang(sub.user_id)
        link = f'\n<a href="{url}">{t(user_lang, "view_post")}</a>' if url else ""
        await self.notify(sub, "notify_published", sid=sid, link=link)
        await self.refresh_control(sid)
        await self.refresh_stats()
        return None

    async def schedule(self, sid: int, ts: int, reviewer: TgUser) -> Notice | None:
        if ts <= now_ts() + 30:
            return notice("time_past")
        sub = await self.db.get(sid)
        if not sub:
            return notice("sub_not_found", sid=sid)
        was_pending = sub.status == "pending"
        fields = self._review_fields(sub, reviewer, "approved")
        if not await self.db.transition(sid, ("pending", "scheduled", "failed"), "scheduled",
                                        scheduled_at=ts, error=None, **fields):
            return notice("status_changed")
        if was_pending:
            await self.notify(sub, "notify_scheduled", sid=sid, when=self.fmt(ts, await self.user_lang(sub.user_id)))
        await self.refresh_control(sid)
        await self.refresh_stats()
        return None

    async def unschedule(self, sid: int) -> Notice | None:
        ok = await self.db.transition(
            sid, ("scheduled",), "pending",
            scheduled_at=None, decision=None, reviewed_at=None, reviewer_id=None, reviewer_name=None,
        )
        if not ok:
            return notice("status_changed")
        # 定时时告诉过投稿人发布时间，取消了也要告诉他，免得一直等着那个时间
        await self.notify(await self.db.get(sid), "notify_unscheduled")
        await self.refresh_control(sid)
        await self.refresh_stats()
        return None

    async def _mark_rejected(self, sub: Submission, reviewer: TgUser, reason: str | None) -> bool:
        fields = self._review_fields(sub, reviewer, "rejected")
        return await self.db.transition(
            sub.id, OPEN_STATES, "rejected", scheduled_at=None, reject_reason=reason, **fields
        )

    async def reject(self, sid: int, reviewer: TgUser, reason: str | None = None) -> Notice | None:
        sub = await self.db.get(sid)
        if not sub:
            return notice("sub_not_found", sid=sid)
        if sub.status not in OPEN_STATES:
            key = {"published": "reject_published", "rejected": "reject_rejected",
                   "publishing": "reject_publishing"}.get(sub.status, "reject_other")
            return notice(key, sid=sid)
        if not await self._mark_rejected(sub, reviewer, reason):
            return notice("status_changed")
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
            text += t(lang, "notify_banned_rejected", n=len(rejected))
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
