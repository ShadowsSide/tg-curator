from __future__ import annotations

import html

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, ForceReply, Message

from .. import entities as ent
from ..config import Settings
from ..core import NO_PREVIEW, Core, explicit_reply, mention, topic_of
from ..permissions import ReviewerCheck, ReviewerOnly, ReviewerPolicy
from ..i18n import t
from ..keyboards import CONFIRMABLE, CONFIRMED, ReviewCB
from ..render import dump_link_preview, message_item, user_link
from ..timeutil import parse_time

MAX_REASON = 500


class ScheduleInput(StatesGroup):
    waiting = State()


def _user_id_arg(command: CommandObject) -> int | None:
    arg = (command.args or "").strip()
    return int(arg) if arg.lstrip("-").isdigit() else None


def _clean_reason(text: str) -> str | None:
    text = text.strip()
    return text[:MAX_REASON] or None


def _split_user(args: str) -> tuple[int | None, str | None]:
    """'/ban 123456 理由'：开头是用户 ID 时返回 (用户ID, 理由)，否则 (None, None)。"""
    head, _, rest = args.strip().partition(" ")
    if head.lstrip("-").isdigit():
        return int(head), _clean_reason(rest)
    return None, None


async def _replied_sid(m: Message, core: Core) -> int | None:
    """命令针对的投稿：回复了投稿消息就用它；话题模式下，在投稿的话题里直接发命令也行。"""
    reply = explicit_reply(m)
    if reply:
        return await core.sid_for_review_message(reply.message_id)
    if topic_of(m):
        return await core.sid_for_review_topic(topic_of(m))
    return None


def build_router(settings: Settings) -> Router:
    router = Router(name="review")
    router.message.filter(F.chat.id == settings.review_chat_id)
    router.callback_query.filter(F.message.chat.id == settings.review_chat_id)
    # 只有审核员能用审核群里的按钮和命令（REVIEWERS 配置）
    guard = ReviewerOnly(ReviewerCheck(ReviewerPolicy.parse(settings.reviewers), settings.review_chat_id),
                         settings.language)
    router.message.middleware(guard)
    router.callback_query.middleware(guard)

    # ---------- 控制按钮 ----------

    @router.callback_query(ReviewCB.filter())
    async def on_button(cq: CallbackQuery, callback_data: ReviewCB, core: Core, state: FSMContext) -> None:
        sid, action = callback_data.sid, callback_data.a
        who = cq.from_user
        lang = core.lang

        # 发布 / 拒绝 / 封禁：先显示确认面板，点“确认”（<动作>_ok）才真正执行
        if action in CONFIRMABLE and settings.confirm_actions:
            await core.show_confirm(sid, action)
            await cq.answer(t(lang, "toast_confirm"))
            return
        action = action.removesuffix(CONFIRMED)

        if action == "spoiler":
            await cq.answer((await core.toggle_spoiler(sid)).text(lang))
        elif action == "silent":
            await cq.answer((await core.toggle_silent(sid)).text(lang))
        elif action == "pub":
            await cq.answer(t(lang, "toast_publishing"))
            err = await core.publish(sid, reviewer=who)
            if err:
                await cq.message.reply(err.text(lang))  # 回复在这条投稿的控制消息下面
        elif action == "retry":
            await cq.answer(t(lang, "toast_retrying"))
            err = await core.publish(sid, reviewer=who, from_states=("failed",))
            if err:
                await cq.message.reply(err.text(lang))
        elif action == "sched":
            await core.show_schedule_picker(sid)
            await cq.answer()
        elif action == "back":
            await core.refresh_control(sid)
            await cq.answer()
        elif action == "preset":
            err = await core.schedule(sid, callback_data.v, who)
            await cq.answer(err.text(lang) if err else t(lang, "toast_scheduled", when=core.fmt(callback_data.v)),
                            show_alert=bool(err))
        elif action == "custom":
            prompt = await cq.message.reply(  # 回复在控制消息下面，看得出是哪条投稿
                t(lang, "custom_time_prompt", who=mention(who), sid=sid),
                reply_markup=ForceReply(selective=True, input_field_placeholder="20:30"),
            )
            await state.set_state(ScheduleInput.waiting)
            await state.update_data(sid=sid, prompt_id=prompt.message_id)
            await cq.answer()
        elif action == "unsched":
            err = await core.unschedule(sid)
            await cq.answer(err.text(lang) if err else t(lang, "toast_unscheduled"))
        elif action == "reject":
            err = await core.reject(sid, who)
            await cq.answer(err.text(lang) if err else t(lang, "toast_rejected"), show_alert=bool(err))
        elif action == "ban":
            sub = await core.get_submission(sid)
            if not sub:
                await cq.answer(t(lang, "sub_not_found", sid=sid), show_alert=True)
                return
            rejected = await core.ban_user(sub.user_id, who)
            await cq.answer(t(lang, "toast_banned", n=len(rejected)))
        else:
            await cq.answer()

    # ---------- 命令 ----------

    @router.message(Command("help"))
    async def help_(m: Message, core: Core) -> None:
        await m.answer(t(core.lang, "review_help"))

    @router.message(Command("stats"))
    async def stats(m: Message, core: Core) -> None:
        await core.post_stats()

    @router.message(Command("queue"))
    async def queue(m: Message, core: Core) -> None:
        await m.answer(await core.queue_text())

    @router.message(Command("active"))
    async def active(m: Message, command: CommandObject, core: Core) -> None:
        arg = (command.args or "").strip()
        days = int(arg) if arg.isdigit() and int(arg) > 0 else 30
        await m.answer(await core.activity_text(days), link_preview_options=NO_PREVIEW)

    @router.message(Command("user"))
    async def user(m: Message, command: CommandObject, core: Core) -> None:
        uid = _user_id_arg(command)
        if uid is None:
            await m.answer(t(core.lang, "usage_user"))
            return
        await m.answer(await core.user_text(uid, for_admin=True), link_preview_options=NO_PREVIEW)

    @router.message(Command("no"))
    async def reject_cmd(m: Message, command: CommandObject, core: Core) -> None:
        args = command.args or ""
        sid = await _replied_sid(m, core)
        if sid is None:
            await m.reply(t(core.lang, "reply_to_submission" if explicit_reply(m) else "usage_no"))
            return
        reason = _clean_reason(args)

        err = await core.reject(sid, m.from_user, reason)
        if err:
            await m.reply(err.text(core.lang))
            return
        await m.reply(t(core.lang, "rejected_reply")
                      + (t(core.lang, "reason_line", reason=html.escape(reason)) if reason else ""))

    @router.message(Command("edit"))
    async def edit_cmd(m: Message, core: Core) -> None:
        # 用原始 text + entities，去掉开头的 /edit，新内容里的超链接、emoji 等格式全部保留
        body, entities = ent.strip_command(m.text or m.caption or "", ent.dump(m.entities or m.caption_entities))
        sid = await _replied_sid(m, core)
        if sid is None:
            await m.reply(t(core.lang, "reply_to_submission" if explicit_reply(m) else "usage_edit"))
            return

        if not body.strip():
            err = await core.show_text(sid, m.chat.id, reply_to=m.message_id)
            await m.reply(err.text(core.lang) if err else t(core.lang, "admin_echo_hint"))
            return

        err = await core.edit(sid, m.from_user.full_name, body, entities, dump_link_preview(m.link_preview_options))
        await m.reply(err.text(core.lang) if err else t(core.lang, "admin_edited"))

    @router.message(Command("msg"))
    async def msg_cmd(m: Message, core: Core) -> None:
        """审核员给投稿人发消息：回复投稿（或在投稿的话题里）发送 /msg 内容。"""
        body, entities = ent.strip_command(m.text or m.caption or "", ent.dump(m.entities or m.caption_entities))
        sid = await _replied_sid(m, core)
        if sid is None:
            await m.reply(t(core.lang, "reply_to_submission" if explicit_reply(m) else "msg_usage_admin"))
            return
        item = message_item(m, body, entities)
        if item is None:
            await m.reply(t(core.lang, "msg_empty"))
            return
        err = await core.relay_to_user(sid, m.from_user, item)
        await m.reply(err.text(core.lang) if err else t(core.lang, "msg_sent_to_user"))

    @router.message(Command("ban"))
    async def ban_cmd(m: Message, command: CommandObject, core: Core) -> None:
        args = command.args or ""
        sid = await _replied_sid(m, core)
        if sid is not None:
            user_id, reason = (await core.get_submission(sid)).user_id, _clean_reason(args)
        elif explicit_reply(m):
            await m.reply(t(core.lang, "reply_to_submission"))
            return
        else:
            user_id, reason = _split_user(args)
            if user_id is None:
                await m.reply(t(core.lang, "usage_ban"))
                return

        rejected = await core.ban_user(user_id, m.from_user, reason)
        user = await core.get_user(user_id)
        text = t(core.lang, "banned_reply", link=user_link(user, user_id), uid=user_id)
        if reason:
            text += t(core.lang, "reason_line", reason=html.escape(reason))
        if rejected:
            text += t(core.lang, "banned_reply_rejected", n=len(rejected))
        await m.reply(text, link_preview_options=NO_PREVIEW)

    @router.message(Command("unban"))
    async def unban_cmd(m: Message, command: CommandObject, core: Core) -> None:
        uid = _user_id_arg(command)
        if uid is None:
            sid = await _replied_sid(m, core)
            uid = (await core.get_submission(sid)).user_id if sid is not None else None
        if uid is None:
            await m.reply(t(core.lang, "usage_unban"))
            return
        if not await core.unban_user(uid):
            await m.reply(t(core.lang, "not_banned", uid=uid))
            return
        await m.reply(t(core.lang, "unbanned_reply", uid=uid))

    # ---------- 自定义定时：等待管理员回复时间 ----------

    @router.message(ScheduleInput.waiting, F.text)
    async def on_time_input(m: Message, state: FSMContext, core: Core) -> None:
        data = await state.get_data()
        sid, prompt_id = data["sid"], data.get("prompt_id")

        # 只接受对提示消息的回复，避免把群里其他聊天当成时间
        if not m.reply_to_message or m.reply_to_message.message_id != prompt_id:
            return

        if m.text.strip().lower() in ("取消", "cancel"):
            await state.clear()
            await m.reply(t(core.lang, "custom_time_cancelled"))
            return

        ts = parse_time(m.text, settings.tz)
        if ts is None:
            await m.reply(t(core.lang, "custom_time_bad"))
            return

        err = await core.schedule(sid, ts, m.from_user)
        if err:
            await m.reply(err.text(core.lang))
            if err.key != "time_past":  # 时间已过：保留状态，让管理员重新输入
                await state.clear()
            return

        await state.clear()
        await m.reply(t(core.lang, "custom_time_done", sid=sid, when=core.fmt(ts)))
        try:
            await m.bot.delete_message(m.chat.id, prompt_id)
        except TelegramAPIError:
            pass

    @router.message(F.reply_to_message)
    async def plain_reply(m: Message, core: Core) -> None:
        """直接回复了投稿人转来的消息但没写 /msg：提醒一下，免得以为对方收到了。"""
        reply = explicit_reply(m)
        if reply and await core.is_review_relay_message(reply.message_id):
            await m.reply(t(core.lang, "msg_hint_admin"))

    return router
