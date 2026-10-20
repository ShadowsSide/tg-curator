from __future__ import annotations

import html
import re

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, ForceReply, Message

from .. import entities as ent
from ..config import Settings
from ..core import NO_PREVIEW, Core, explicit_reply, mention, topic_of
from ..i18n import join_ids, t
from ..keyboards import ReviewCB
from ..render import dump_link_preview, user_link
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


def _split_ref(args: str) -> tuple[str | None, int | None, str | None]:
    """'#12 理由' -> ('sid', 12, '理由')；'123 理由' -> ('num', 123, '理由')；不以编号开头 -> (None, None, None)。"""
    head, _, rest = args.strip().partition(" ")
    if head.startswith("#") and head[1:].isdigit():
        return "sid", int(head[1:]), _clean_reason(rest)
    if head.lstrip("-").isdigit():
        return "num", int(head), _clean_reason(rest)
    return None, None, None


async def _replied_sid(m: Message, core: Core) -> int | None:
    """命令针对的投稿：回复了投稿消息就用它；话题模式下，在投稿的话题里直接发命令也行。"""
    reply = explicit_reply(m)
    if reply:
        return await core.db.sid_by_review_message(reply.message_id)
    if topic_of(m):
        return await core.db.sid_by_review_topic(topic_of(m))
    return None


def build_router(settings: Settings) -> Router:
    router = Router(name="review")
    router.message.filter(F.chat.id == settings.review_chat_id)
    router.callback_query.filter(F.message.chat.id == settings.review_chat_id)

    # ---------- 控制按钮 ----------

    @router.callback_query(ReviewCB.filter())
    async def on_button(cq: CallbackQuery, callback_data: ReviewCB, core: Core, state: FSMContext) -> None:
        sid, action = callback_data.sid, callback_data.a
        who = cq.from_user
        lang = core.lang

        if action == "spoiler":
            await cq.answer(await core.toggle_spoiler(sid))
        elif action == "silent":
            await cq.answer(await core.toggle_silent(sid))
        elif action == "pub":
            await cq.answer(t(lang, "toast_publishing"))
            err = await core.publish(sid, reviewer=who)
            if err:
                await cq.message.answer(f"#{sid} {err}")
        elif action == "retry":
            await cq.answer(t(lang, "toast_retrying"))
            err = await core.publish(sid, reviewer=who, from_states=("failed",))
            if err:
                await cq.message.answer(f"#{sid} {err}")
        elif action == "sched":
            await core.show_schedule_picker(sid)
            await cq.answer()
        elif action == "back":
            await core.refresh_control(sid)
            await cq.answer()
        elif action == "preset":
            err = await core.schedule(sid, callback_data.v, who)
            await cq.answer(err or t(lang, "toast_scheduled", when=core.fmt(callback_data.v)), show_alert=bool(err))
        elif action == "custom":
            prompt = await cq.message.answer(
                t(lang, "custom_time_prompt", who=mention(who), sid=sid),
                reply_markup=ForceReply(selective=True, input_field_placeholder="20:30"),
            )
            await state.set_state(ScheduleInput.waiting)
            await state.update_data(sid=sid, prompt_id=prompt.message_id)
            await cq.answer()
        elif action == "unsched":
            err = await core.unschedule(sid)
            await cq.answer(err or t(lang, "toast_unscheduled"))
        elif action == "reject":
            err = await core.reject(sid, who)
            await cq.answer(err or t(lang, "toast_rejected"), show_alert=bool(err))
        elif action == "ban":
            sub = await core.db.get(sid)
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
        if sid is not None:
            reason = _clean_reason(args)
        elif explicit_reply(m):
            await m.reply(t(core.lang, "reply_to_submission"))
            return
        else:
            kind, sid, reason = _split_ref(args)
            if sid is None:
                await m.reply(t(core.lang, "usage_no"))
                return

        err = await core.reject(sid, m.from_user, reason)
        if err:
            await m.reply(err)
            return
        await m.reply(t(core.lang, "rejected_reply", sid=sid)
                      + (t(core.lang, "reason_line", reason=html.escape(reason)) if reason else ""))

    @router.message(Command("edit"))
    async def edit_cmd(m: Message, core: Core) -> None:
        # 用原始 text + entities，去掉开头的 /edit，新内容里的超链接、emoji 等格式全部保留
        body, entities = ent.strip_command(m.text or m.caption or "", ent.dump(m.entities or m.caption_entities))
        sid = await _replied_sid(m, core)
        if sid is None:
            if explicit_reply(m):
                await m.reply(t(core.lang, "reply_to_submission"))
                return
            ref = re.match(r"#?(\d+)[ \t]*\n?", body)
            if not ref:
                await m.reply(t(core.lang, "usage_edit"))
                return
            sid = int(ref.group(1))
            body, entities = ent.cut_prefix(body, entities, ref.end())

        if not body.strip():
            err = await core.show_text(sid, m.chat.id, reply_to=m.message_id)
            await m.reply(err or t(core.lang, "admin_echo_hint"))
            return

        err = await core.edit(sid, m.from_user.full_name, body, entities, dump_link_preview(m.link_preview_options))
        await m.reply(err or t(core.lang, "admin_edited", sid=sid))

    @router.message(Command("ban"))
    async def ban_cmd(m: Message, command: CommandObject, core: Core) -> None:
        args = command.args or ""
        sid = await _replied_sid(m, core)
        if sid is not None:
            user_id, reason = (await core.db.get(sid)).user_id, _clean_reason(args)
        elif explicit_reply(m):
            await m.reply(t(core.lang, "reply_to_submission"))
            return
        else:
            kind, ref, reason = _split_ref(args)
            if ref is None:
                await m.reply(t(core.lang, "usage_ban"))
                return
            if kind == "sid":
                sub = await core.db.get(ref)
                if not sub:
                    await m.reply(t(core.lang, "sub_not_found", sid=ref))
                    return
                user_id = sub.user_id
            else:
                user_id = ref

        rejected = await core.ban_user(user_id, m.from_user, reason)
        user = await core.db.get_user(user_id)
        text = t(core.lang, "banned_reply", link=user_link(user, user_id), uid=user_id)
        if reason:
            text += t(core.lang, "reason_line", reason=html.escape(reason))
        if rejected:
            text += t(core.lang, "banned_reply_rejected", n=len(rejected), ids=join_ids(core.lang, rejected))
        await m.reply(text, link_preview_options=NO_PREVIEW)

    @router.message(Command("unban"))
    async def unban_cmd(m: Message, command: CommandObject, core: Core) -> None:
        uid = _user_id_arg(command)
        if uid is None:
            sid = await _replied_sid(m, core)
            uid = (await core.db.get(sid)).user_id if sid is not None else None
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
            await m.reply(err)
            if err != t(core.lang, "time_past"):  # 时间已过：保留状态，让管理员重新输入
                await state.clear()
            return

        await state.clear()
        await m.reply(t(core.lang, "custom_time_done", sid=sid, when=core.fmt(ts)))
        try:
            await m.bot.delete_message(m.chat.id, prompt_id)
        except TelegramAPIError:
            pass

    return router
