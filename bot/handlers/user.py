from __future__ import annotations

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message

from .. import entities as ent
from ..core import Core, explicit_reply
from ..db import SUBMITTER_EDITABLE
from ..i18n import t
from ..keyboards import UserCB, UserMediaCB, user_media_kb
from ..render import dump_link_preview, extract_item, message_item

def build_router() -> Router:
    router = Router(name="user")
    router.message.filter(F.chat.type == ChatType.PRIVATE)
    router.callback_query.filter(F.message.chat.type == ChatType.PRIVATE)
    router.edited_message.filter(F.chat.type == ChatType.PRIVATE)

    @router.message(CommandStart())
    @router.message(Command("help"))
    async def start(m: Message, core: Core) -> None:
        await core.touch(m.from_user)
        await m.answer(t(core.lang_of(m.from_user), "welcome"))

    @router.message(Command("me"))
    async def me(m: Message, core: Core) -> None:
        await m.answer(await core.user_text(m.from_user.id, for_admin=False, lang=core.lang_of(m.from_user)))

    @router.message(Command("edit"))
    async def edit_cmd(m: Message, core: Core) -> None:
        uid = m.from_user.id
        lang = core.lang_of(m.from_user)
        body, entities = ent.strip_command(m.text or m.caption or "", ent.dump(m.entities or m.caption_entities))

        # 必须回复要修改的那条投稿（投稿内容本身，或机器人关于它的提示消息）才生效
        reply = explicit_reply(m)
        if not reply:
            await m.reply(t(lang, "u_edit_reply_needed"))
            return
        found = await core.find_user_message(uid, reply.message_id)
        if not found:
            await m.reply(t(lang, "u_edit_reply_own"))
            return
        sid = found[0]

        sub = await core.get_submission(sid)
        if not sub or sub.user_id != uid:
            await m.reply(t(lang, "u_edit_not_found"))
            return
        if not body.strip():
            err = await core.show_text(sid, m.chat.id, reply_to=m.message_id)
            await m.reply(err.text(lang) if err else t(lang, "u_edit_echo_hint"))
            return

        err = await core.edit(sid, _editor(core, m), body, entities, dump_link_preview(m.link_preview_options),
                              allowed=SUBMITTER_EDITABLE)
        await m.reply(err.text(lang) if err else _edited_text(lang, sid, sub.status))

    @router.message(Command("msg"))
    async def msg_cmd(m: Message, core: Core) -> None:
        """投稿人给审核员发消息：必须回复审核员的消息或自己的投稿。"""
        lang = core.lang_of(m.from_user)
        body, entities = ent.strip_command(m.text or m.caption or "", ent.dump(m.entities or m.caption_entities))
        reply = explicit_reply(m)
        found = await core.find_user_message(m.from_user.id, reply.message_id) if reply else None
        if not found:
            await m.reply(t(lang, "msg_usage_user"))
            return
        await _relay(m, core, found[0], body, entities)

    @router.edited_message()
    async def native_edit(m: Message, core: Core) -> None:
        """投稿人用 Telegram 自带的“编辑”改了投稿的原消息。"""
        found = await core.find_user_message(m.from_user.id, m.message_id)
        if not found or found[1] is None:
            return  # 不是投稿内容（比如普通聊天、命令），忽略
        sid, index = found
        new_item = extract_item(m)
        if new_item is None:
            return
        sub = await core.get_submission(sid)
        lang = core.lang_of(m.from_user)
        err = await core.replace_item(sid, index, new_item, _editor(core, m), SUBMITTER_EDITABLE)
        await m.reply(err.text(lang) if err else _edited_text(lang, sid, sub.status))

    @router.message(F.media_group_id)
    async def album_part(m: Message, core: Core) -> None:
        core.albums.add(m)

    @router.message()
    async def single(m: Message, core: Core) -> None:
        if m.text and m.text.startswith("/"):
            await m.answer(t(core.lang_of(m.from_user), "unknown_cmd"))
            return
        # 直接回复了沟通消息（审核员转来的，或自己之前的留言）：当作留言转给审核员，而不是一条新投稿
        reply = explicit_reply(m)
        sid = await core.sid_for_relay_message(m.from_user.id, reply.message_id) if reply else None
        if sid:
            await _relay(m, core, sid, m.text or m.caption or "", ent.dump(m.entities or m.caption_entities),
                         empty="unsupported")  # 贴纸等不能转达的类型
            return
        await core.receive([m])

    @router.callback_query(UserMediaCB.filter())
    async def media_buttons(cq: CallbackQuery, callback_data: UserMediaCB, core: Core) -> None:
        """投稿人自己改图片：把新发的图片加到旧投稿（merge）、删除面板（mdel / mrm / mback）。"""
        sid, a, v, uid = callback_data.sid, callback_data.a, callback_data.v, cq.from_user.id
        lang = core.lang_of(cq.from_user)
        editor = t(core.lang, "submitter_label", name=cq.from_user.full_name)
        if a == "merge":
            err = await core.merge_draft(sid, uid, editor)
            if not err:
                await cq.message.edit_text(t(lang, "merged"))
            await cq.answer(err.text(lang) if err else t(lang, "merged_toast"), show_alert=bool(err))
            return
        if a == "mrm":
            err = await core.remove_own_media(sid, uid, v, editor)  # 成功时按钮由 core 恢复
            await cq.answer(err.text(lang) if err else t(lang, "toast_media_removed", n=v), show_alert=bool(err))
            if not err:
                return
        sub = await core.get_submission(sid)
        if not sub or sub.user_id != uid:
            await cq.answer(t(lang, "u_edit_not_found"), show_alert=True)
            return
        # 打开删除面板；返回、删除失败、或者已经不能改了（审核开始后点旧按钮）：恢复成当前状态的按钮
        panel = a == "mdel" and sub.status in SUBMITTER_EDITABLE
        try:
            await cq.message.edit_reply_markup(
                reply_markup=user_media_kb(sub, lang) if panel else await core.user_keyboard(sub, lang))
        except TelegramBadRequest as e:
            if "not modified" not in str(e):
                raise
        if a == "mdel" and not panel:
            await cq.answer(t(lang, "media_locked"), show_alert=True)
        elif a != "mrm":
            await cq.answer()

    @router.callback_query(UserCB.filter())
    async def choice(cq: CallbackQuery, callback_data: UserCB, core: Core) -> None:
        sid = callback_data.sid
        lang = core.lang_of(cq.from_user)
        if callback_data.a == "cancel":
            err = await core.cancel_draft(sid, cq.from_user.id)
            if not err:
                await cq.message.edit_text(t(lang, "cancelled"))
            await cq.answer(err.text(lang) if err else t(lang, "cancelled"))
            return

        anonymous = callback_data.a == "anon"
        err = await core.submit(sid, cq.from_user.id, anonymous)
        if err:
            await cq.answer(err.text(lang), show_alert=True)
            return
        mode = t(lang, "mode_anon" if anonymous else "mode_signed")
        await cq.message.edit_text(t(lang, "submitted", mode=mode, sid=sid),
                                   reply_markup=await core.user_keyboard(await core.get_submission(sid), lang))
        await cq.answer(t(lang, "submitted_toast"))

    return router


async def _relay(m: Message, core: Core, sid: int, body: str, entities: list, empty: str = "msg_empty") -> None:
    """投稿人的留言（/msg 或直接回复审核员）转给审核群。empty：没有可转达的内容时的提示。"""
    lang = core.lang_of(m.from_user)
    item = message_item(m, body, entities)
    if item is None:
        await m.reply(t(lang, empty))
        return
    err = await core.relay_to_review(sid, m.from_user, item, m.message_id)
    await m.reply(err.text(lang) if err else t(lang, "msg_sent_to_review"))


def _edited_text(lang: str, sid: int, status: str) -> str:
    return t(lang, "edited_draft") if status == "draft" else t(lang, "edited_pending", sid=sid)


def _editor(core: Core, m: Message) -> str:
    """控制消息上“已修改（谁）”的显示，用审核群的语言。"""
    return t(core.lang, "submitter_label", name=m.from_user.full_name)
