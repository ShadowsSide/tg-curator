"""审核动作：剧透 / 静音开关、发布、定时、拒绝、封禁。"""
from __future__ import annotations

import html
import logging

from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramRetryAfter
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
        return await self._toggle(sid, "spoiler", "toast_spoiler")

    async def toggle_silent(self, sid: int) -> Notice:
        return await self._toggle(sid, "silent", "toast_silent")

    async def _toggle(self, sid: int, field: str, toast: str) -> Notice:
        """切换发布选项（剧透 / 静音）。带状态条件写：发布先把状态改成 publishing 再读设置，
        晚到的切换写不进去，提示“已经开始处理”，而不是提示已切换、发出去的却是旧设置。"""
        sub = await self.db.get(sid)
        if not sub or sub.status not in OPEN_STATES:
            return notice("toast_state_locked")
        on = not getattr(sub, field)
        if not await self.db.update_if(sid, OPEN_STATES, **{field: int(on)}):
            return notice("toast_state_locked")
        await self.refresh_control(sid)
        return notice(toast, state=notice("on" if on else "off"))

    async def publish(self, sid: int, reviewer: TgUser | None = None,
                      from_states: tuple[str, ...] = OPEN_STATES,
                      version: int | None = None) -> Notice | None:
        """立即发布到频道。返回错误信息，成功返回 None。
        version：审核员点按钮时看到的内容版本；之后内容又被改过就不发（定时发布不带，按到点时的内容发）。"""
        sub = await self.db.get(sid)
        if not sub:
            return notice("sub_not_found", sid=sid)
        fields = self._review_fields(sub, reviewer, "approved")
        if not await self.db.transition(sid, from_states, "publishing", version=version, error=None, **fields):
            sub = await self.db.get(sid)
            if version is not None and sub.status in from_states and sub.version != version:
                await self.refresh_control(sid)  # 按钮换成新版本的，看过新预览后再点
                return notice("publish_stale")
            return notice("status_changed")
        await self.refresh_control(sid)

        sub = await self.db.get(sid)
        try:
            sent = await send_items(
                self.bot, self.s.channel_id, sub.items, sig=await self._signature(sub, link=False),
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
        except Exception as e:  # 无论什么错误都不能停在 publishing：那个状态下审核员什么也做不了
            log.exception("发布 #%s 失败", sid)
            await self.db.update(sid, status="failed", error=str(e)[:300])
            await self.refresh_control(sid)
            await self.refresh_stats()
            return notice("publish_failed", error=html.escape(str(e)))  # 错误原文可能带 < >，消息按 HTML 解析

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
        # 通知投稿人：第一次定时告诉他发布时间；改时间（已定时 → 另一个时间）告诉他新时间
        key = ("notify_scheduled" if sub.status == "pending"
               else "notify_rescheduled" if sub.status == "scheduled" and sub.scheduled_at != ts else None)
        fields = self._review_fields(sub, reviewer, "approved")
        if not await self.db.transition(sid, OPEN_STATES, "scheduled",
                                        scheduled_at=ts, error=None, **fields):
            return notice("status_changed")
        if key:
            await self.notify(sub, key, sid=sid, when=self.fmt(ts, await self.user_lang(sub.user_id)))
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
                               reply_to=sub.user_msg_id)
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

    async def purge_review_messages(self, user_id: int) -> Notice:
        """删除被封禁用户的全部投稿在审核群里的消息（含已发布的）；数据库里的投稿记录保留，/user 统计不变。
        按整条投稿分批，每次最多 100 条（deleteMessages 的上限）；删成功的投稿才清掉记录，失败的可以再点一次重试。
        一批里只要有一条删不掉，Telegram 就让整批失败：这时改为按投稿逐条删，一条坏消息不会连累其他稿件。
        超过 48 小时的消息 Telegram 不允许机器人删除（有删除权限也不行）：不再记录、不再重试，提示里说明要手动删。"""
        user = await self.db.get_user(user_id)
        if not user or not user.banned:
            return notice("toast_not_banned")
        traces = await self.db.review_traces(self.s.review_chat_id, user_id)
        if not traces:
            return notice("purge_nothing")
        done = failed = old = 0
        for sids, ids in _delete_batches(traces):
            if await self._delete_review_messages(ids):
                await self.db.forget_review_messages(self.s.review_chat_id, sids)
                done += len(sids)
                continue
            for sid in sids:  # 整批失败：一条一条投稿地删；这条投稿还删不掉，再一条一条消息地删
                # 只有一条投稿的批次刚刚已经整体试过了，直接逐条
                whole = len(sids) > 1 and await self._delete_review_messages(traces[sid])
                too_old = 0 if whole else await self._delete_one_by_one(sid, traces[sid])
                if too_old is None:
                    failed += 1
                    continue
                await self.db.forget_review_messages(self.s.review_chat_id, [sid])
                done += 1
                old += too_old
        note = notice("purge_too_old", n=old) if old else ""
        if failed:
            return notice("purge_partial", n=done, failed=failed, note=note)
        return notice("purge_done", n=done, note=note)

    async def _delete_review_messages(self, ids: list[int]) -> bool:
        """一次删一批（超过 100 条分几次）；有一条删不掉就整批失败，返回 False。"""
        try:
            for i in range(0, len(ids), DELETE_LIMIT):
                await self.bot.delete_messages(self.s.review_chat_id, ids[i:i + DELETE_LIMIT])
        except TelegramAPIError:
            return False
        return True

    async def _delete_one_by_one(self, sid: int, ids: list[int]) -> int | None:
        """这条投稿的消息一条一条删。返回其中有几条太旧、删不掉（Telegram 不允许，不用再试）；
        有别的错误（网络、权限等，下次可能成功）返回 None，能删的已经删掉，删不掉的记进日志，下次再试。"""
        gone, too_old, bad = [], [], {}
        for mid in ids:
            try:
                await self.bot.delete_message(self.s.review_chat_id, mid)
            except TelegramBadRequest as e:
                if "can't be deleted" in e.message:  # 机器人自己发的消息只有超过 48 小时才会这样
                    too_old.append(mid)
                    continue
                if "not found" not in e.message:  # 已经不在了（手动删过、上次删掉了）就算删掉了
                    bad[mid] = e.message
                    continue
            except TelegramAPIError as e:
                bad[mid] = str(e)
                continue
            gone.append(mid)
        if too_old:
            log.info("投稿 #%s 的消息 %s 超过 48 小时，Telegram 不允许机器人删除，需要手动删除", sid, too_old)
        if bad:
            await self.db.unlink_review_messages(gone + too_old)
            log.warning("删除审核群消息失败：投稿 #%s 的消息 %s 删不掉（%s）", sid, sorted(bad), "；".join(set(bad.values())))
            return None
        return len(too_old)

    async def unban_user(self, user_id: int) -> bool:
        if not await self.db.unban(user_id):
            return False
        await self.notify_user(user_id, t(await self.user_lang(user_id), "notify_unbanned"))
        return True


DELETE_LIMIT = 100  # deleteMessages 一次最多删 100 条


def _delete_batches(traces: dict[int, list[int]]):
    """把各条投稿的消息拼成尽量满的批次，同一条投稿不拆到两批（超过上限的单条投稿自成一批，删除时再分段）。"""
    sids: list[int] = []
    ids: list[int] = []
    for sid, mids in traces.items():
        if ids and len(ids) + len(mids) > DELETE_LIMIT:
            yield sids, ids
            sids, ids = [], []
        sids.append(sid)
        ids += mids
    if ids:
        yield sids, ids
