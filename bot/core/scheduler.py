"""后台任务：到点发布定时投稿、清理过期草稿、定时发送审核统计。"""
from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import datetime

from aiogram.exceptions import TelegramAPIError

from ..db import Submission
from ..errors import Notice
from ..health import beat
from ..i18n import t
from ..timeutil import now_ts, start_of_today

from .base import CoreBase, SCHEDULER_TICK, DRAFT_TTL, NO_PREVIEW, _reply_to

log = logging.getLogger(__name__)


class SchedulerMixin(CoreBase):
    # ---------- 后台任务 ----------

    async def _scheduler_loop(self) -> None:
        while not self._stopping.is_set():  # 停止时不取消：正在发布的这条发完，剩下的留给下次启动
            beat()  # 健康检查（bot/health.py）看这个文件多久没更新，判断机器人是否卡住
            try:
                for sub in await self.db.due_scheduled(now_ts()):
                    if self._stopping.is_set():
                        return
                    beat()  # 一次到点的稿件很多时，一轮可能比较久
                    err = await self.publish(sub.id, from_states=("scheduled",))
                    if err:
                        log.warning("定时发布 #%s：%s", sub.id, err.key)
                        if err.key != "status_changed":  # 已经被别人处理了（撤销定时、拒绝等），不用提醒
                            await self._report_scheduled(sub, err)
                    else:
                        await self._report_scheduled_ok(sub.id)
                for sub in await self.db.expire_drafts(now_ts() - DRAFT_TTL):
                    if sub.user_msg_id:
                        try:
                            await self.bot.edit_message_text(
                                t(await self.user_lang(sub.user_id), "draft_expired"),
                                chat_id=sub.user_id, message_id=sub.user_msg_id,
                            )
                        except TelegramAPIError:
                            pass
                await self.expire_prompts()
                self.throttle.prune()
            except Exception:
                log.exception("调度循环出错")
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._stopping.wait(), SCHEDULER_TICK)

    async def _report_scheduled(self, sub: Submission, err: Notice) -> None:
        """定时发布没有成功（发布失败 / 被限流改了时间）：没人点按钮，控制按钮消息变了也没人注意，回复在它下面提醒审核员。"""
        try:
            await self.bot.send_message(
                self.s.review_chat_id, t(self.lang, "sched_publish_failed", reason=err.text(self.lang)),
                reply_parameters=_reply_to(sub.review_msg_id),
            )
        except TelegramAPIError as e:
            log.warning("提醒定时发布 #%s 失败：%s", sub.id, e)

    async def _report_scheduled_ok(self, sid: int) -> None:
        """定时发布成功：同样没人点按钮，回复在控制按钮消息下面说一声，带上帖子链接。静音发送，定时稿件多时不会每条都响。
        控制按钮消息已经没了（稿件被删除）就不发：单独一条没有上下文。"""
        sub = await self.db.get(sid)
        if not sub or not sub.review_msg_id:
            return
        url = self.post_url(sub)
        link = f'  <a href="{url}">{t(self.lang, "view_post")}</a>' if url else ""
        try:
            await self.bot.send_message(
                self.s.review_chat_id, t(self.lang, "sched_published", link=link),
                reply_parameters=_reply_to(sub.review_msg_id), disable_notification=True,
                link_preview_options=NO_PREVIEW,
            )
        except TelegramAPIError as e:
            log.warning("告知定时发布 #%s 成功失败：%s", sid, e)

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
