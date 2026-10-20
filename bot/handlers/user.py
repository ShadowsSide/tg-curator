from __future__ import annotations

import re

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message

from .. import entities as ent
from ..core import Core
from ..db import SUBMITTER_EDITABLE
from ..keyboards import UserCB
from ..render import dump_link_preview, extract_item

WELCOME = (
    "👋 欢迎投稿！\n\n"
    "直接把要投稿的内容发给我即可：文字、图片、视频、GIF、文件，或一次发多张图（相册）。\n"
    "发送后选择 <b>署名</b> 或 <b>匿名</b>，审核通过后会发布到频道，结果会通知你。\n\n"
    "<b>修改投稿</b>（审核结果出来之前都可以改）：\n"
    "· 直接用 Telegram 的“编辑”修改你发出的那条消息，机器人会自动同步（换图也可以）\n"
    "· 或者回复你的投稿，发送 <code>/edit 新内容</code>；只发 /edit 会把当前内容发给你，方便复制修改\n\n"
    "/me 查看我的投稿统计"
)


def build_router() -> Router:
    router = Router(name="user")
    router.message.filter(F.chat.type == ChatType.PRIVATE)
    router.callback_query.filter(F.message.chat.type == ChatType.PRIVATE)
    router.edited_message.filter(F.chat.type == ChatType.PRIVATE)

    @router.message(CommandStart())
    @router.message(Command("help"))
    async def start(m: Message, core: Core) -> None:
        await core.touch(m.from_user)
        await m.answer(WELCOME)

    @router.message(Command("me"))
    async def me(m: Message, core: Core) -> None:
        await m.answer(await core.user_text(m.from_user.id, for_admin=False))

    @router.message(Command("edit"))
    async def edit_cmd(m: Message, core: Core) -> None:
        uid = m.from_user.id
        body, entities = ent.strip_command(m.text or m.caption or "", ent.dump(m.entities or m.caption_entities))
        mine = await core.db.editable_by_submitter(uid)

        if m.reply_to_message:
            found = await core.db.find_by_user_message(uid, m.reply_to_message.message_id)
            if not found:
                await m.reply("请回复你自己发出的投稿内容，或机器人关于这条投稿的提示消息。")
                return
            sid = found[0]
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
                await m.reply("你目前没有可以修改的投稿（审核结果出来之前的投稿才能修改）。")
                return
            else:
                ids = "、".join(f"#{s.id}" for s in mine)
                await m.reply(f"你有多条待审核的投稿：{ids}。\n请回复要修改的那条，或发送 <code>/edit #编号 新内容</code>。")
                return

        sub = await core.db.get(sid)
        if not sub or sub.user_id != uid:
            await m.reply(f"没有找到你的投稿 #{sid}。")
            return
        if not body.strip():
            err = await core.show_text(sid, m.chat.id, reply_to=m.message_id)
            await m.reply(err or "↑ 这是当前内容。复制、修改后，回复你的投稿发送 <code>/edit 新内容</code>。")
            return

        err = await core.edit(sid, f"投稿人 {m.from_user.full_name}", body, entities,
                              dump_link_preview(m.link_preview_options), allowed=SUBMITTER_EDITABLE)
        await m.reply(err or _edited_text(sid, sub.status))

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
        err = await core.replace_item(sid, index, new_item, f"投稿人 {m.from_user.full_name}", SUBMITTER_EDITABLE)
        await m.reply(err or _edited_text(sid, sub.status))

    @router.message(F.media_group_id)
    async def album_part(m: Message, core: Core) -> None:
        core.albums.add(m)

    @router.message()
    async def single(m: Message, core: Core) -> None:
        if m.text and m.text.startswith("/"):
            await m.answer("未知命令。直接发送内容即可投稿，/help 查看说明。")
            return
        await core.receive([m])

    @router.callback_query(UserCB.filter())
    async def choice(cq: CallbackQuery, callback_data: UserCB, core: Core) -> None:
        sid = callback_data.sid
        if callback_data.a == "cancel":
            err = await core.cancel_draft(sid, cq.from_user.id)
            if not err:
                await cq.message.edit_text("已取消。")
            await cq.answer(err or "已取消")
            return

        anonymous = callback_data.a == "anon"
        err = await core.submit(sid, cq.from_user.id, anonymous)
        if err:
            await cq.answer(err, show_alert=True)
            return
        await cq.message.edit_text(
            f"✅ 已{'匿名' if anonymous else '署名'}提交，投稿编号 <b>#{sid}</b>。\n审核结果会通知你，请耐心等待。"
        )
        await cq.answer("已提交")

    return router


def _edited_text(sid: int, status: str) -> str:
    if status == "draft":
        return "✏️ 已更新。确认无误后请在上面选择署名或匿名提交。"
    return f"✏️ 投稿 #{sid} 已更新，审核时将使用修改后的内容。"
