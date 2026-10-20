from __future__ import annotations

import re

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message

from .. import entities as ent
from ..core import Core, explicit_reply, topic_of
from ..db import SUBMITTER_EDITABLE
from ..i18n import join_ids, t
from ..keyboards import UserCB
from ..render import dump_link_preview, extract_item

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
        mine = await core.db.editable_by_submitter(uid)

        reply = explicit_reply(m)
        topic_sid = await core.db.sid_by_user_topic(uid, topic_of(m)) if topic_of(m) else None
        if reply:
            found = await core.db.find_by_user_message(uid, reply.message_id)
            if not found:
                await m.reply(t(lang, "u_edit_reply_own"))
                return
            sid = found[0]
        elif topic_sid:  # 私聊话题模式：在投稿自己的话题里直接 /edit
            sid = topic_sid
        else:
            # “#12 新内容”一定是编号；纯数字只有在确实是自己可修改的投稿编号时才当作编号，
            # 避免把“/edit 2024年总结”里的 2024 误认成投稿编号
            ref = re.match(r"(#?)(\d+)[ \t]*\n?", body)
            if ref and (ref.group(1) or int(ref.group(2)) in {s.id for s in mine}):
                sid = int(ref.group(2))
                body, entities = ent.cut_prefix(body, entities, ref.end())
            elif len(mine) == 1:
                sid = mine[0].id
            elif not mine:
                await m.reply(t(lang, "u_edit_none"))
                return
            else:
                await m.reply(t(lang, "u_edit_many", ids=join_ids(lang, (s.id for s in mine))))
                return

        sub = await core.db.get(sid)
        if not sub or sub.user_id != uid:
            await m.reply(t(lang, "u_edit_not_found", sid=sid))
            return
        if not body.strip():
            err = await core.show_text(sid, m.chat.id, reply_to=m.message_id, lang=lang)
            await m.reply(err or t(lang, "u_edit_echo_hint"))
            return

        err = await core.edit(sid, _editor(core, m), body, entities, dump_link_preview(m.link_preview_options),
                              allowed=SUBMITTER_EDITABLE, lang=lang)
        await m.reply(err or _edited_text(lang, sid, sub.status))

    @router.edited_message()
    async def native_edit(m: Message, core: Core) -> None:
        """投稿人用 Telegram 自带的“编辑”改了投稿的原消息。"""
        found = await core.db.find_by_user_message(m.from_user.id, m.message_id)
        if not found or found[1] is None:
            return  # 不是投稿内容（比如普通聊天、命令），忽略
        sid, index = found
        new_item = extract_item(m)
        if new_item is None:
            return
        sub = await core.db.get(sid)
        lang = core.lang_of(m.from_user)
        err = await core.replace_item(sid, index, new_item, _editor(core, m), SUBMITTER_EDITABLE, lang)
        await m.reply(err or _edited_text(lang, sid, sub.status))

    @router.message(F.media_group_id)
    async def album_part(m: Message, core: Core) -> None:
        core.albums.add(m)

    @router.message()
    async def single(m: Message, core: Core) -> None:
        if m.text and m.text.startswith("/"):
            await m.answer(t(core.lang_of(m.from_user), "unknown_cmd"))
            return
        await core.receive([m])

    @router.callback_query(UserCB.filter())
    async def choice(cq: CallbackQuery, callback_data: UserCB, core: Core) -> None:
        sid = callback_data.sid
        lang = core.lang_of(cq.from_user)
        if callback_data.a == "cancel":
            err = await core.cancel_draft(sid, cq.from_user.id, lang)
            if not err:
                await cq.message.edit_text(t(lang, "cancelled"))
            await cq.answer(err or t(lang, "cancelled"))
            return

        anonymous = callback_data.a == "anon"
        err = await core.submit(sid, cq.from_user.id, anonymous, lang)
        if err:
            await cq.answer(err, show_alert=True)
            return
        mode = t(lang, "mode_anon" if anonymous else "mode_signed")
        await cq.message.edit_text(t(lang, "submitted", mode=mode, sid=sid))
        await cq.answer(t(lang, "submitted_toast"))

    return router


def _edited_text(lang: str, sid: int, status: str) -> str:
    return t(lang, "edited_draft") if status == "draft" else t(lang, "edited_pending", sid=sid)


def _editor(core: Core, m: Message) -> str:
    """控制消息上“已修改（谁）”的显示，用审核群的语言。"""
    return t(core.lang, "submitter_label", name=m.from_user.full_name)
