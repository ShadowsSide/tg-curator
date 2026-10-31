from __future__ import annotations

import html
import time

from aiogram import F, Router
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message

from .. import entities as ent
from ..album import ALBUM_MERGE_WINDOW
from ..config import Settings
from ..core import NO_PREVIEW, Core, explicit_reply
from ..db import Prompt
from ..errors import Notice, notice
from ..permissions import ReviewerCheck, ReviewerOnly, ReviewerPolicy
from ..i18n import t
from ..keyboards import AdminUserCB, ReviewCB, route, user_confirm_kb
from ..render import dump_link_preview, extract_item, message_item, user_link
from ..timeutil import parse_time

MAX_REASON = 500
# 回复提示时这些错误可以改了再回复一次，提示保留；其他错误（比如投稿已被别人处理）提示作废
RETRYABLE = ("prompt_text_needed", "custom_time_bad", "time_past", "too_long", "text_empty",
             "media_only_photo_video", "media_replace_one", "media_too_many")
REVIEWER_MEDIA = ("pending",)  # 审核员只能在待审核时改媒体


# 按钮 → 提示的种类；FOLD 里的按钮来自面板（理由面板、媒体面板），发提示时把控制消息恢复原样
PROMPT_KIND = {"custom": "time", "edit": "edit", "creason": "reason", "madd": "madd", "mrep": "mrep"}
FOLD = ("creason", "madd", "mrep")


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


async def _banned_submitter(core: Core, sid: int) -> bool:
    sub = await core.get_submission(sid)
    user = await core.get_user(sub.user_id) if sub else None
    return bool(user and user.banned)


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
        if step == "confirm" and action in ("unban", "purge") and not await _banned_submitter(core, sid):
            # 早就解封了（比如用了 /unban），控制消息上的按钮是旧的：不出确认面板，直接收起
            await core.refresh_control(sid)
            await cq.answer(t(lang, "toast_not_banned"), show_alert=True)
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
            if action in FOLD:
                await core.refresh_control(sid)
            await core.ask(sid, PROMPT_KIND[action], who, cq.message.message_id, v)
            await cq.answer()
        elif action == "media":
            err = await core.show_media_panel(sid)
            await cq.answer(err.text(lang) if err else None, show_alert=bool(err))
        elif action == "mrm":
            err = await core.change_media(sid, "remove", v, [], who.full_name, REVIEWER_MEDIA, by_submitter=False)
            if err:
                await core.refresh_control(sid)  # 收起确认面板
            await cq.answer(err.text(lang) if err else t(lang, "toast_media_removed", n=v), show_alert=bool(err))
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
        elif action == "unban":
            sub = await core.get_submission(sid)
            ok = bool(sub) and await core.unban_user(sub.user_id)
            await core.refresh_control(sid)
            await cq.answer(t(lang, "toast_unbanned" if ok else "toast_not_banned"), show_alert=not ok)
        elif action == "purge":
            sub = await core.get_submission(sid)
            res = await core.purge_review_messages(sub.user_id) if sub else notice("sub_not_found", sid=sid)
            await core.refresh_control(sid)  # 删成功时这条控制消息已经没了（不会再刷新）；没删掉就收起确认面板
            await cq.answer(res.text(lang), show_alert=True)
        else:
            await cq.answer()

    @router.callback_query(AdminUserCB.filter())
    async def on_user_card(cq: CallbackQuery, callback_data: AdminUserCB, core: Core) -> None:
        """/user 卡片上的封禁 / 解封 / 删除稿件：先确认；状态已经变了（别人刚封禁 / 解封过）就只刷新卡片。"""
        uid, a, lang = callback_data.uid, callback_data.a, core.lang
        action = a.removesuffix("_ok")
        user = await core.get_user(uid)
        banned = bool(user and user.banned)
        toast, alert = None, False
        if action in ("ban", "unban") and banned == (action == "ban"):  # 已经是想要的状态了
            toast, alert = t(lang, "toast_already_banned" if banned else "toast_not_banned"), True
        elif action == "purge" and not banned:  # 删除只对被封禁的人；已经被解封了，按钮是旧的
            toast, alert = t(lang, "toast_not_banned"), True
        elif a in ("ban", "unban", "purge"):
            await cq.message.edit_reply_markup(reply_markup=user_confirm_kb(uid, a, lang))
            await cq.answer(t(lang, "toast_confirm"))
            return
        elif a == "ban_ok":
            rejected = await core.ban_user(uid, cq.from_user)
            toast, alert = t(lang, "toast_banned", n=len(rejected)), False
        elif a == "unban_ok":
            await core.unban_user(uid)
            toast, alert = t(lang, "toast_unbanned"), False
        elif a == "purge_ok":
            res = await core.purge_review_messages(uid)
            toast, alert = res.text(lang), res.key != "purge_done"
        text, kb = await core.user_card(uid)
        try:
            await cq.message.edit_text(text, reply_markup=kb, link_preview_options=NO_PREVIEW)
        except TelegramBadRequest as e:
            if "not modified" not in str(e):
                raise
        await cq.answer(toast, show_alert=bool(toast) and alert)

    # ---------- 回复提示 ----------

    @router.message(F.reply_to_message)
    async def on_prompt_reply(m: Message, core: Core) -> None:
        """回复了机器人的提示（“请回复本消息……”）。不是提示、不是点按钮的那个人、或者发的是命令，就交给后面的处理函数。"""
        reply = explicit_reply(m)
        prompt = await core.get_prompt(m.chat.id, reply.message_id) if reply else None
        if not prompt or not _is_owner(m, prompt) or (m.text or "").startswith("/"):
            raise SkipHandler
        if prompt.kind in ("madd", "mrep"):
            if m.media_group_id:  # 回复的是相册：收齐所有项再一起处理
                core.albums.add(m, lambda messages: _answer_media(prompt, messages, core, album=m.media_group_id))
            else:
                await _answer_media(prompt, [m], core)
            return
        await _finish(prompt, m, core, *await _answer_prompt(prompt, m, core))

    # 已经处理过的“添加 / 替换”相册：相册编号 → (回复的提示, 到期时间)。后到的部分（晚于 ALBUM_DELAY）靠它接着处理。
    # 只记在内存里：重启后才到的部分不认
    answered: dict[str, tuple[Prompt, float]] = {}

    @router.message(F.media_group_id)
    async def album_rest(m: Message, core: Core) -> None:
        """相册里没带回复的其余项（如果有）：并进正在收集的那个相册；
        相册前面的部分已经处理过（这几项晚到了）：同一个人发的就接着处理。"""
        if core.albums.join(m):
            return
        prompt, until = answered.get(m.media_group_id, (None, 0))
        if not prompt or until < time.monotonic() or not _is_owner(m, prompt):
            raise SkipHandler
        core.albums.add(m, lambda messages: _answer_late_media(prompt, messages, core))

    async def _finish(prompt: Prompt, m: Message, core: Core, err: Notice | None, done: str) -> None:
        """回复提示的结果：成功就删掉提示；出错时能改了再试的保留提示，其他的作废。"""
        if err:
            await m.reply(err.text(core.lang))
            if err.key not in RETRYABLE:
                await core.finish_prompt(prompt)
            return
        await core.finish_prompt(prompt)
        await m.reply(done)

    async def _answer_media(prompt: Prompt, messages: list[Message], core: Core, album: str | None = None) -> None:
        """回复了“添加 / 替换”的提示：发来的图片视频（可以是相册）加进投稿或换掉第 arg 个。"""
        first = messages[0]
        err = await _apply_media(prompt, messages, "add" if prompt.kind == "madd" else "replace", core)
        if album:
            now = time.monotonic()
            for key in [k for k, (_, until) in answered.items() if until < now]:
                del answered[key]
            answered[album] = (prompt, now + ALBUM_MERGE_WINDOW)
        await _finish(prompt, first, core, err, t(core.lang, "admin_edited"))

    async def _answer_late_media(prompt: Prompt, messages: list[Message], core: Core) -> None:
        """“添加 / 替换”相册后到的部分：添加就接着加进去；替换只能用一张，告诉审核员这几张没用上。"""
        first, n = messages[0], len(messages)
        if prompt.kind == "mrep":
            await first.reply(t(core.lang, "media_late_unused", n=n))
            return
        err = await _apply_media(prompt, messages, "add", core)
        await first.reply(t(core.lang, "media_late_failed", n=n, reason=err.text(core.lang)) if err
                          else t(core.lang, "media_late_added", n=n))

    async def _apply_media(prompt: Prompt, messages: list[Message], op: str, core: Core) -> Notice | None:
        items = [extract_item(x) for x in messages]
        if any(it is None or it["type"] == "text" for it in items):
            return notice("media_only_photo_video")
        return await core.change_media(prompt.sid, op, prompt.arg, items, messages[0].from_user.full_name,
                                       REVIEWER_MEDIA, by_submitter=False)

    async def _answer_prompt(prompt: Prompt, m: Message, core: Core) -> tuple[Notice | None, str]:
        """按提示的种类执行，返回 (错误, 成功时的回复)。"""
        sid, lang, who = prompt.sid, core.lang, m.from_user
        body = m.text or m.caption or ""
        entities = ent.dump(m.entities or m.caption_entities)
        if prompt.kind not in PROMPT_KIND.values():
            # 已经去掉的提示种类（例如以前的“联系投稿人”提示）：作废，不能落到下面的“拒绝理由”分支
            return notice("msg_usage_admin"), ""
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
        text, kb = await core.user_card(uid)
        await m.answer(text, reply_markup=kb, link_preview_options=NO_PREVIEW)

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
        if sid is not None and sid not in rejected:  # 回复的那条（已发布 / 已拒绝）也显示“解除封禁”
            await core.refresh_control(sid)
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
        sid = await _replied_sid(m, core) if uid is None else None
        if sid is not None:
            uid = (await core.get_submission(sid)).user_id
        if uid is None:
            await m.reply(t(core.lang, "usage_unban"))
            return
        if not await core.unban_user(uid):
            await m.reply(t(core.lang, "not_banned", uid=uid))
            return
        if sid is not None:  # 收起回复的那条控制消息上的“解除封禁”；别的控制消息上的旧按钮点了再收起
            await core.refresh_control(sid)
        await m.reply(t(core.lang, "unbanned_reply", uid=uid))

    @router.message(F.reply_to_message)
    async def plain_reply(m: Message, core: Core) -> None:
        """直接回复了投稿人转来的消息但没写 /msg：提醒一下，免得以为对方收到了。"""
        reply = explicit_reply(m)
        if reply and await core.is_review_relay_message(reply.message_id):
            await m.reply(t(core.lang, "msg_hint_admin"))

    return router
