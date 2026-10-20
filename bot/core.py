"""业务核心：投稿 → 审核 → 发布/定时 → 通知，以及后台调度和审核统计。"""
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
from .db import DB, OPEN_STATES, SUBMITTER_EDITABLE, Submission
from .keyboards import control_kb, schedule_kb, user_choice_kb
from .entities import u16len
from .render import (
    caption_index, control_text, describe, extract_item, send_items, signature, stats_text, user_link,
)
from .timeutil import fmt_ts, now_ts, start_of_today, utc_offset

log = logging.getLogger(__name__)

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

    def start_background(self) -> None:
        self._tasks = [
            asyncio.create_task(self._scheduler_loop(), name="scheduler"),
            asyncio.create_task(self._reminder_loop(), name="reminder"),
        ]

    async def stop_background(self) -> None:
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)

    # ---------- helpers ----------

    def post_url(self, sub: Submission) -> str | None:
        if sub.channel_msg_id and self.channel_post_base:
            return f"{self.channel_post_base}{sub.channel_msg_id}"
        return None

    async def _signature(self, sub: Submission) -> str:
        user = await self.db.get_user(sub.user_id)
        return signature(sub, user, self.s.sign_template, self.s.anon_signature)

    async def notify(self, sub: Submission, text: str) -> None:
        await self.notify_user(sub.user_id, text, reply_to=sub.user_msg_id)

    async def notify_user(self, user_id: int, text: str, reply_to: int | None = None) -> None:
        try:
            await self.bot.send_message(user_id, text, reply_parameters=_reply_to(reply_to))
        except TelegramAPIError as e:  # 用户把机器人拉黑、从没启动过机器人等
            log.info("通知用户 %s 失败：%s", user_id, e)

    async def refresh_control(self, sid: int) -> None:
        sub = await self.db.get(sid)
        if not sub or not sub.review_msg_id:
            return
        user = await self.db.get_user(sub.user_id)
        try:
            await self.bot.edit_message_text(
                text=control_text(sub, user, self.s.tz, self.post_url(sub)),
                chat_id=self.s.review_chat_id,
                message_id=sub.review_msg_id,
                reply_markup=control_kb(sub),
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
            reply_markup=schedule_kb(sid, self.s.schedule_presets, self.s.tz),
        )

    # ---------- 用户侧 ----------

    async def touch(self, user: TgUser) -> None:
        await self.db.touch_user(user.id, user.username, user.full_name)

    async def receive(self, messages: list[Message]) -> None:
        """收到用户内容（单条或整个相册），创建草稿并让用户选署名/匿名。"""
        first = messages[0]
        user = first.from_user
        await self.touch(user)

        db_user = await self.db.get_user(user.id)
        if db_user and db_user.banned:
            await first.reply("🚫 你已被禁止投稿。" + _reason_line(db_user.ban_reason))
            return
        if await self.db.count_open_by_user(user.id) >= self.s.max_pending_per_user:
            await first.reply("你还有较多投稿在等待处理，请稍后再投。")
            return

        items = [extract_item(m) for m in messages]
        if any(i is None for i in items):
            await first.reply("暂不支持这种消息类型。\n支持：文字、图片、视频、GIF、文件、音频、语音，以及多图相册。")
            return

        # 用户自己给媒体加了剧透时，默认保留剧透
        spoiler = any(i.get("spoiler") for i in items)
        sid = await self.db.create_draft(user.id, items, silent=self.s.default_silent, spoiler=spoiler)
        prompt = await first.reply(
            f"收到 {describe(items)}。请选择投稿方式：\n"
            "· <b>署名</b>：频道帖子会附上你的名字\n"
            "· <b>匿名</b>：频道里不显示你是谁（管理员仍可见）",
            reply_markup=user_choice_kb(sid),
        )
        await self.db.update(sid, user_msg_id=prompt.message_id)

    async def submit(self, sid: int, user_id: int, anonymous: bool) -> str | None:
        sub = await self.db.get(sid)
        if not sub or sub.user_id != user_id:
            return "无效的投稿"
        if not await self.db.transition(sid, ("draft",), "pending", anonymous=int(anonymous), submitted_at=now_ts()):
            return "这条投稿已经处理过了"
        await self._send_to_review(sid)
        await self.refresh_stats()
        return None

    async def cancel_draft(self, sid: int, user_id: int) -> str | None:
        sub = await self.db.get(sid)
        if not sub or sub.user_id != user_id:
            return "无效的投稿"
        if not await self.db.transition(sid, ("draft",), "cancelled"):
            return "这条投稿已经提交，无法取消"
        return None

    async def _send_to_review(self, sid: int) -> None:
        sub = await self.db.get(sid)
        user = await self.db.get_user(sub.user_id)
        # 预览就是频道里最终的样子（含落款），方便审核
        preview = await send_items(
            self.bot, self.s.review_chat_id, sub.items, sig=await self._signature(sub), spoiler=False
        )
        ctrl = await self.bot.send_message(
            self.s.review_chat_id,
            control_text(sub, user, self.s.tz, None),
            reply_markup=control_kb(sub),
            reply_parameters=_reply_to(preview[0].message_id),
            link_preview_options=NO_PREVIEW,
        )
        await self.db.update(sid, review_msg_id=ctrl.message_id)
        await self.db.link_review_messages(sid, [m.message_id for m in preview] + [ctrl.message_id])

    # ---------- 审核侧 ----------

    def _review_fields(self, sub: Submission, reviewer: TgUser | None, decision: str) -> dict:
        fields: dict = {"decision": decision}
        if reviewer:
            fields.update(reviewer_id=reviewer.id, reviewer_name=reviewer.full_name)
        if sub.decision != decision or not sub.reviewed_at:
            fields["reviewed_at"] = now_ts()
        return fields

    # ---------- 修改稿件（管理员 / 投稿人共用） ----------

    async def edit(self, sid: int, editor: str, text: str, entities: list, link_preview: dict | None = None,
                   allowed: tuple[str, ...] = OPEN_STATES) -> str | None:
        """修改稿件的文字（文字投稿改正文，媒体投稿改说明文字），格式由 entities 原样保留。"""
        sub = await self.db.get(sid)
        err = self._check_editable(sub, sid, allowed)
        if err:
            return err
        items = [dict(it) for it in sub.items]
        target = items[caption_index(items)]
        is_text = target["type"] == "text"
        if is_text and not text.strip():
            return "文字投稿的内容不能为空"
        target["text"], target["entities"] = text, entities
        if is_text:
            target["link_preview"] = link_preview
        return await self._save_edit(sub, items, editor, allowed)

    async def replace_item(self, sid: int, index: int, new_item: dict, editor: str,
                           allowed: tuple[str, ...]) -> str | None:
        """投稿人用 Telegram 自带的“编辑”修改了原消息：整项替换（文字、格式、甚至换图都会同步）。"""
        sub = await self.db.get(sid)
        err = self._check_editable(sub, sid, allowed)
        if err:
            return err
        items = [dict(it) for it in sub.items]
        if items[index]["type"] == "text" and new_item["type"] != "text" or \
                items[index]["type"] != "text" and new_item["type"] == "text":
            return "不能把文字投稿改成媒体投稿（或反过来），请重新投稿"
        items[index] = new_item
        return await self._save_edit(sub, items, editor, allowed)

    @staticmethod
    def _check_editable(sub: Submission | None, sid: int, allowed: tuple[str, ...]) -> str | None:
        if not sub:
            return f"投稿 #{sid} 不存在"
        if sub.status in allowed:
            return None
        return {
            "scheduled": f"投稿 #{sid} 已通过审核、等待发布",
            "publishing": f"投稿 #{sid} 正在发布",
            "published": f"投稿 #{sid} 已经发布",
            "rejected": f"投稿 #{sid} 已被拒绝",
            "cancelled": f"投稿 #{sid} 已取消",
            "failed": f"投稿 #{sid} 发布失败、等待管理员处理",
        }.get(sub.status, f"投稿 #{sid} 当前状态") + "，不能修改"

    async def _save_edit(self, sub: Submission, items: list[dict], editor: str,
                         allowed: tuple[str, ...]) -> str | None:
        for it in items:
            limit = 4096 if it["type"] == "text" else 1024
            if u16len(it.get("text", "")) > limit:
                return f"内容太长：{u16len(it['text'])} 字，上限 {limit}（还需留出落款的长度）"
        # 第一次修改前的原稿单独保存；状态变了（比如刚好被发布）就不改
        ok = await self.db.update_if(
            sub.id, allowed, items=items, original_items=sub.original_items or sub.items,
            edited_by=editor, edited_at=now_ts(),
        )
        if not ok:
            return "投稿状态刚刚发生了变化，修改未生效"
        sub = await self.db.get(sub.id)
        if sub.status != "draft":  # 草稿还没进审核群，不用发预览
            preview = await send_items(
                self.bot, self.s.review_chat_id, sub.items, sig=await self._signature(sub),
                spoiler=False, reply_to=sub.review_msg_id,
            )
            await self.db.link_review_messages(sub.id, [m.message_id for m in preview])
            await self.refresh_control(sub.id)
        return None

    async def show_text(self, sid: int, chat_id: int, reply_to: int) -> str | None:
        """把稿件当前的文字（带格式）发出来，方便复制后修改再 /edit。"""
        sub = await self.db.get(sid)
        if not sub:
            return f"投稿 #{sid} 不存在"
        target = sub.items[caption_index(sub.items)]
        if not target.get("text"):
            return f"投稿 #{sid} 没有文字，直接发送 /edit 新的说明文字 即可添加"
        only_text = {"type": "text", "text": target["text"], "entities": target.get("entities", []),
                     "link_preview": {"is_disabled": True}}
        await send_items(self.bot, chat_id, [only_text], sig=("", []), spoiler=False, reply_to=reply_to)
        return None

    async def toggle_spoiler(self, sid: int) -> str:
        sub = await self.db.get(sid)
        if not sub or sub.status not in ("pending", "scheduled", "failed"):
            return "当前状态不能修改"
        await self.db.update(sid, spoiler=int(not sub.spoiler))
        await self.refresh_control(sid)
        return f"剧透遮罩：{'开' if not sub.spoiler else '关'}"

    async def toggle_silent(self, sid: int) -> str:
        sub = await self.db.get(sid)
        if not sub or sub.status not in ("pending", "scheduled", "failed"):
            return "当前状态不能修改"
        await self.db.update(sid, silent=int(not sub.silent))
        await self.refresh_control(sid)
        return f"静音发送：{'开' if not sub.silent else '关'}"

    async def publish(self, sid: int, reviewer: TgUser | None = None,
                      from_states: tuple[str, ...] = ("pending", "scheduled", "failed")) -> str | None:
        """立即发布到频道。返回错误信息，成功返回 None。"""
        sub = await self.db.get(sid)
        if not sub:
            return "投稿不存在"
        fields = self._review_fields(sub, reviewer, "approved")
        if not await self.db.transition(sid, from_states, "publishing", error=None, **fields):
            return "状态已变化，请刷新"
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
            return f"发布失败：{e}"

        await self.db.update(sid, status="published", published_at=now_ts(), channel_msg_id=sent[0].message_id)
        sub = await self.db.get(sid)
        url = self.post_url(sub)
        link = f'\n<a href="{url}">查看帖子</a>' if url else ""
        await self.notify(sub, f"🎉 你的投稿 #{sid} 已发布到频道！{link}")
        await self.refresh_control(sid)
        await self.refresh_stats()
        return None

    async def schedule(self, sid: int, ts: int, reviewer: TgUser) -> str | None:
        if ts <= now_ts() + 30:
            return "这个时间已经过去了"
        sub = await self.db.get(sid)
        if not sub:
            return "投稿不存在"
        was_pending = sub.status == "pending"
        fields = self._review_fields(sub, reviewer, "approved")
        if not await self.db.transition(sid, ("pending", "scheduled", "failed"), "scheduled",
                                        scheduled_at=ts, error=None, **fields):
            return "状态已变化，请刷新"
        when = fmt_ts(ts, self.s.tz)
        if was_pending:
            await self.notify(sub, f"✅ 你的投稿 #{sid} 已通过审核，将于 {when} 发布。")
        await self.refresh_control(sid)
        await self.refresh_stats()
        return None

    async def unschedule(self, sid: int) -> str | None:
        ok = await self.db.transition(
            sid, ("scheduled",), "pending",
            scheduled_at=None, decision=None, reviewed_at=None, reviewer_id=None, reviewer_name=None,
        )
        if not ok:
            return "状态已变化，请刷新"
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
            return f"投稿 #{sid} 不存在"
        if sub.status not in OPEN_STATES:
            return {
                "published": f"投稿 #{sid} 已发布，无法拒绝",
                "rejected": f"投稿 #{sid} 已经被拒绝过了",
                "publishing": f"投稿 #{sid} 正在发布中",
            }.get(sub.status, f"投稿 #{sid} 当前状态无法拒绝")
        if not await self._mark_rejected(sub, reviewer, reason):
            return "状态已变化，请刷新"
        await self.notify(sub, f"😢 你的投稿 #{sid} 未通过审核。" + _reason_line(reason))
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
            if await self._mark_rejected(sub, reviewer, reason or "投稿人已被封禁"):
                rejected.append(sub.id)

        text = "🚫 你已被禁止投稿。" + _reason_line(reason)
        if rejected:
            text += f"\n你待处理的 {len(rejected)} 条投稿（{'、'.join(f'#{i}' for i in rejected)}）已一并拒绝。"
        await self.notify_user(user_id, text)

        for sid in rejected:
            await self.refresh_control(sid)
        await self.refresh_stats()
        return rejected

    async def unban_user(self, user_id: int) -> bool:
        if not await self.db.unban(user_id):
            return False
        await self.notify_user(user_id, "✅ 你的投稿权限已恢复，欢迎继续投稿。")
        return True

    # ---------- 审核统计 ----------

    async def _stats_text(self) -> str:
        since = start_of_today(self.s.tz) if self.s.stats_scope == "today" else 0
        accepted, rejected, pending = await self.db.review_counts(since)
        return stats_text(accepted, rejected, pending, datetime.now(self.s.tz))

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
        since = now_ts() - days * 86400
        rows = await self.db.activity(since, utc_offset(self.s.tz))
        total, people = await self.db.activity_totals(since)
        if not rows:
            return f"近 {days} 天没有投稿。"
        lines = [f"📊 <b>投稿人活跃度</b>（近 {days} 天 · {people} 人 · {total} 条）", ""]
        for i, r in enumerate(rows, 1):
            reviewed = (r["approved"] or 0) + (r["rejected"] or 0)
            rate = f"{r['approved'] / reviewed * 100:.0f}%" if reviewed else "-"
            name = user_link(await self.db.get_user(r["user_id"]), r["user_id"])
            ban = " 🚫" if r["banned"] else ""
            anon = f" · 匿名 {r['anonymous']}" if r["anonymous"] else ""
            lines.append(
                f"{i}. {name}{ban}\n"
                f"    投稿 {r['total']} · 通过 {r['approved'] or 0} ({rate}){anon}"
                f" · 活跃 {r['active_days']} 天 · 最近 {fmt_ts(r['last_at'], self.s.tz)}"
            )
        return "\n".join(lines)

    async def user_text(self, user_id: int, for_admin: bool) -> str:
        s = await self.db.user_summary(user_id)
        if not s["total"]:
            return "还没有投稿记录。" if not for_admin else f"用户 <code>{user_id}</code> 没有投稿记录。"
        reviewed = s["published"] + s["scheduled"] + s["rejected"]
        rate = f"{(s['published'] + s['scheduled']) / reviewed * 100:.0f}%" if reviewed else "-"
        head = "📈 <b>你的投稿统计</b>"
        if for_admin:
            user = await self.db.get_user(user_id)
            banned = ""
            if user and user.banned:
                banned = (f"\n🚫 已封禁 {fmt_ts(user.banned_at, self.s.tz)}（{html.escape(user.banned_by or '')}）"
                          + _reason_line(user.ban_reason))
            head = f"📈 {user_link(user, user_id)}  <code>{user_id}</code>{banned}"
        return (
            f"{head}\n"
            f"总投稿 {s['total']} · 已发布 {s['published']} · 待发布 {s['scheduled']}"
            f" · 待审核 {s['pending']} · 未通过 {s['rejected']}\n"
            f"通过率 {rate} · 匿名 {s['anonymous']}\n"
            f"首次 {fmt_ts(s['first_at'], self.s.tz)} · 最近 {fmt_ts(s['last_at'], self.s.tz)}"
        )

    async def queue_text(self) -> str:
        subs = await self.db.upcoming_scheduled()
        if not subs:
            return "没有待发布的定时投稿。"
        lines = ["⏰ <b>定时发布队列</b>", ""]
        for sub in subs:
            flags = (" 🙈" if sub.spoiler else "") + (" 🔕" if sub.silent else "")
            lines.append(f"{fmt_ts(sub.scheduled_at, self.s.tz)} · #{sub.id} · {describe(sub.items)}{flags}")
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
                                "已过期，如需投稿请重新发送。", chat_id=sub.user_id, message_id=sub.user_msg_id
                            )
                        except TelegramAPIError:
                            pass
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


def _reason_line(reason: str | None) -> str:
    return f"\n理由：{html.escape(reason)}" if reason else ""


def mention(user: TgUser) -> str:
    return f'<a href="tg://user?id={user.id}">{html.escape(user.full_name)}</a>'
