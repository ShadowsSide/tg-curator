"""后台任务：到点发布定时投稿、清理过期草稿、定时发送审核统计。"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from aiogram.exceptions import TelegramAPIError

from ..i18n import t
from ..timeutil import now_ts, start_of_today

from .base import CoreBase, SCHEDULER_TICK, DRAFT_TTL

log = logging.getLogger(__name__)


class SchedulerMixin(CoreBase):
    # ---------- 后台任务 ----------

    async def _scheduler_loop(self) -> None:
        while True:
            try:
                for sub in await self.db.due_scheduled(now_ts()):
                    err = await self.publish(sub.id, from_states=("scheduled",))
                    if err:
                        log.warning("定时发布 #%s：%s", sub.id, err.key)
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
