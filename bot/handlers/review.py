from __future__ import annotations

import html

from aiogram import F, Router
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message

from .. import entities as ent
from ..config import Settings
from ..core import NO_PREVIEW, Core, explicit_reply
from ..db import Prompt
from ..errors import Notice, notice
from ..permissions import ReviewerCheck, ReviewerOnly, ReviewerPolicy
from ..i18n import t
from ..keyboards import ReviewCB, route
from ..render import dump_link_preview, message_item, user_link
from ..timeutil import parse_time

MAX_REASON = 500
# 回复提示时这些错误可以改了再回复一次，提示保留；其他错误（比如投稿已被别人处理）提示作废
RETRYABLE = ("prompt_text_needed", "custom_time_bad", "time_past", "too_long", "text_empty")


PROMPT_KIND = {"custom": "time", "edit": "edit", "msg": "msg", "creason": "reason"}  # 按钮 → 提示的种类


def _is_owner(m: Message, prompt: Prompt) -> bool:
    """这条消息是不是点按钮的那个人发的。匿名管理员（以群的身份发言）看不出是谁，一律算数。"""
    anonymous_admin = m.sender_chat is not None and m.sender_chat.id == m.chat.id
    return m.from_user.id == prompt.user_id or anonymous_admin


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
    """命令针对的投稿：回复的那条投稿消息（预览、控制消息、转来的留言）。"""
    reply = explicit_reply(m)
    return await core.sid_for_review_message(reply.message_id) if reply else None


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
    async def on_button(cq: CallbackQuery, callback_data: ReviewCB, core: Core) -> None:
        sid = callback_data.sid
        who = cq.from_user
        lang = core.lang

        # 拒绝先选理由、发布 / 拒绝 / 封禁先确认（见 keyboards.route）；走到最后才真正执行
        step, action, v = route(callback_data.a, callback_data.v, bool(settings.reject_templates))
        if step == "reasons":
            await core.show_reject_reasons(sid)
            await cq.answer(t(lang, "toast_pick_reason"))
            return
        if step == "confirm":
            await core.show_confirm(sid, action, v)
            await cq.answer(t(lang, "toast_confirm"))
            return

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
            err = await core.schedule(sid, v, who)
            await cq.answer(err.text(lang) if err else t(lang, "toast_scheduled", when=core.fmt(v)),
                            show_alert=bool(err))
        elif action in PROMPT_KIND:  # 发一条提示，审核员回复它（见 on_prompt_reply）
            if action == "creason":
                await core.refresh_control(sid)  # 收起理由面板
            await core.ask(sid, PROMPT_KIND[action], who, cq.message.message_id)
            await cq.answer()
        elif action == "unsched":
            err = await core.unschedule(sid)
            await cq.answer(err.text(lang) if err else t(lang, "toast_unscheduled"))
        elif action == "reject":
            reason = settings.reject_template(v)
            err = await core.reject(sid, who, reason)
            # 按钮提示最多 200 字符，理由是用户配置的，可能很长
            ok = t(lang, "toast_rejected_with", reason=reason[:150]) if reason else t(lang, "toast_rejected")
            await cq.answer(err.text(lang) if err else ok, show_alert=bool(err))
        elif action == "ban":
            sub = await core.get_submission(sid)
            if not sub:
                await cq.answer(t(lang, "sub_not_found", sid=sid), show_alert=True)
                return
            rejected = await core.ban_user(sub.user_id, who)
            await cq.answer(t(lang, "toast_banned", n=len(rejected)))
        else:
            await cq.answer()

    # ---------- 回复提示 ----------

    @router.message(F.reply_to_message)
    async def on_prompt_reply(m: Message, core: Core) -> None:
        """回复了机器人的提示（“请回复本消息……”）。不是提示、不是点按钮的那个人、或者发的是命令，就交给后面的处理函数。"""
        reply = explicit_reply(m)
        prompt = await core.get_prompt(m.chat.id, reply.message_id) if reply else None
        if not prompt or not _is_owner(m, prompt) or (m.text or "").startswith("/"):
            raise SkipHandler
        err, done = await _answer_prompt(prompt, m, core)
        if err:
            await m.reply(err.text(core.lang))
            if err.key not in RETRYABLE:
                await core.finish_prompt(prompt)
            return
        await core.finish_prompt(prompt)
        await m.reply(done)

    async def _answer_prompt(prompt: Prompt, m: Message, core: Core) -> tuple[Notice | None, str]:
        """按提示的种类执行，返回 (错误, 成功时的回复)。"""
        sid, lang, who = prompt.sid, core.lang, m.from_user
        body = m.text or m.caption or ""
        entities = ent.dump(m.entities or m.caption_entities)
        if prompt.kind == "msg":
            item = message_item(m, body, entities)
            if item is None:  # 空消息或不支持的类型（比如投票）
                return notice("prompt_text_needed"), ""
            return await core.relay_to_user(sid, who, item), t(lang, "msg_sent_to_user")
        if not body.strip():
            return notice("prompt_text_needed"), ""
        if prompt.kind == "time":
            ts = parse_time(body, settings.tz)
            if ts is None:
                return notice("custom_time_bad"), ""
            return await core.schedule(sid, ts, who), t(lang, "custom_time_done", when=core.fmt(ts))
        if prompt.kind == "edit":
            err = await core.edit(sid, who.full_name, body, entities, dump_link_preview(m.link_preview_options))
            return err, t(lang, "admin_edited")
        reason = _clean_reason(body)
        return (await core.reject(sid, who, reason),
                t(lang, "rejected_reply") + t(lang, "reason_line", reason=html.escape(reason)))

    @router.message(Command("cancel"))
    async def cancel_cmd(m: Message, core: Core) -> None:
        """放弃等待回复的提示：回复某条提示发送就只放弃它，直接发送放弃自己在审核群里所有的提示。
        只能放弃自己的（匿名管理员除外），和回复提示的规则一样。"""
        reply = explicit_reply(m)
        prompt = await core.get_prompt(m.chat.id, reply.message_id) if reply else None
        if prompt:
            prompts = [prompt] if _is_owner(m, prompt) else []
        else:
            prompts = await core.prompts_of(m.chat.id, m.from_user.id)
        for p in prompts:
            await core.cancel_prompt(p)
        await m.reply(t(core.lang, "prompt_cancelled" if prompts else "prompt_none"))

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
        """审核员给投稿人发消息：回复投稿发送 /msg 内容。"""
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

    @router.message(F.reply_to_message)
    async def plain_reply(m: Message, core: Core) -> None:
        """直接回复了投稿人转来的消息但没写 /msg：提醒一下，免得以为对方收到了。"""
        reply = explicit_reply(m)
        if reply and await core.is_review_relay_message(reply.message_id):
            await m.reply(t(core.lang, "msg_hint_admin"))

    return router
