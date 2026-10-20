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
from ..core import NO_PREVIEW, Core, mention
from ..keyboards import ReviewCB
from ..render import dump_link_preview, user_link
from ..timeutil import fmt_ts, parse_time

HELP = (
    "🛠 <b>审核群命令</b>\n"
    "/stats 发送最新审核统计\n"
    "/queue 定时发布队列\n"
    "/active [天数] 投稿人活跃度排行（默认 30 天）\n"
    "/user &lt;用户ID&gt; 查看某位投稿人\n\n"
    "<b>拒绝 / 封禁</b>（回复投稿的预览或控制消息，理由可省略）\n"
    "/no [理由] 拒绝该投稿，理由会发给投稿人\n"
    "/ban [理由] 封禁投稿人，并自动拒绝其所有未处理来稿\n"
    "不回复时：/no &lt;投稿编号&gt; [理由] · /ban &lt;用户ID 或 #投稿编号&gt; [理由]\n"
    "/unban &lt;用户ID&gt; 解除封禁\n\n"
    "<b>修改稿件</b>（回复投稿使用，格式会原样保留）\n"
    "/edit 新内容 —— 替换文字投稿的正文 / 媒体投稿的说明文字\n"
    "/edit —— 不带内容：把当前文字（含格式）发出来，方便复制后修改\n"
    "不回复时：/edit &lt;投稿编号&gt; 新内容"
)

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
    if not m.reply_to_message:
        return None
    return await core.db.sid_by_review_message(m.reply_to_message.message_id)


def build_router(settings: Settings) -> Router:
    router = Router(name="review")
    router.message.filter(F.chat.id == settings.review_chat_id)
    router.callback_query.filter(F.message.chat.id == settings.review_chat_id)

    # ---------- 控制按钮 ----------

    @router.callback_query(ReviewCB.filter())
    async def on_button(cq: CallbackQuery, callback_data: ReviewCB, core: Core, state: FSMContext) -> None:
        sid, action = callback_data.sid, callback_data.a
        who = cq.from_user

        if action == "spoiler":
            await cq.answer(await core.toggle_spoiler(sid))
        elif action == "silent":
            await cq.answer(await core.toggle_silent(sid))
        elif action == "pub":
            await cq.answer("发布中…")
            err = await core.publish(sid, reviewer=who)
            if err:
                await cq.message.answer(f"#{sid} {err}")
        elif action == "retry":
            await cq.answer("重试中…")
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
            await cq.answer(err or f"已定时：{fmt_ts(callback_data.v, settings.tz)}", show_alert=bool(err))
        elif action == "custom":
            prompt = await cq.message.answer(
                f"{mention(who)} 请<b>回复本消息</b>输入投稿 #{sid} 的发布时间：\n"
                "<code>20:30</code> · <code>10-20 09:00</code> · <code>2026-10-20 09:00</code>"
                " · <code>+90m</code> · <code>+2h</code>\n"
                "回复「取消」放弃。",
                reply_markup=ForceReply(selective=True, input_field_placeholder="20:30"),
            )
            await state.set_state(ScheduleInput.waiting)
            await state.update_data(sid=sid, prompt_id=prompt.message_id)
            await cq.answer()
        elif action == "unsched":
            err = await core.unschedule(sid)
            await cq.answer(err or "已取消定时，回到待审核")
        elif action == "reject":
            err = await core.reject(sid, who)
            await cq.answer(err or "已拒绝（需要附理由请用 /no 回复）", show_alert=bool(err))
        elif action == "ban":
            sub = await core.db.get(sid)
            if not sub:
                await cq.answer("投稿不存在", show_alert=True)
                return
            rejected = await core.ban_user(sub.user_id, who)
            await cq.answer(f"已封禁，并拒绝 {len(rejected)} 条未处理来稿")
        else:
            await cq.answer()

    # ---------- 命令 ----------

    @router.message(Command("help"))
    async def help_(m: Message) -> None:
        await m.answer(HELP)

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
            await m.answer("用法：/user &lt;用户ID&gt;（控制消息里投稿人名字后面的数字）")
            return
        await m.answer(await core.user_text(uid, for_admin=True), link_preview_options=NO_PREVIEW)

    @router.message(Command("no"))
    async def reject_cmd(m: Message, command: CommandObject, core: Core) -> None:
        args = command.args or ""
        sid = await _replied_sid(m, core)
        if sid is not None:
            reason = _clean_reason(args)
        elif m.reply_to_message:
            await m.reply("请回复投稿的预览或控制消息。")
            return
        else:
            kind, sid, reason = _split_ref(args)
            if sid is None:
                await m.reply("用法：回复投稿后发 /no [理由]，或 /no &lt;投稿编号&gt; [理由]")
                return

        err = await core.reject(sid, m.from_user, reason)
        if err:
            await m.reply(err)
            return
        await m.reply(f"❌ 已拒绝投稿 #{sid}" + (f"\n理由：{html.escape(reason)}" if reason else ""))

    @router.message(Command("edit"))
    async def edit_cmd(m: Message, core: Core) -> None:
        # 用原始 text + entities，去掉开头的 /edit，新内容里的超链接、emoji 等格式全部保留
        body, entities = ent.strip_command(m.text or m.caption or "", ent.dump(m.entities or m.caption_entities))
        sid = await _replied_sid(m, core)
        if sid is None:
            if m.reply_to_message:
                await m.reply("请回复投稿的预览或控制消息。")
                return
            ref = re.match(r"#?(\d+)[ \t]*\n?", body)
            if not ref:
                await m.reply("用法：回复投稿后发 /edit 新内容，或 /edit &lt;投稿编号&gt; 新内容")
                return
            sid = int(ref.group(1))
            body, entities = ent.cut_prefix(body, entities, ref.end())

        if not body.strip():
            err = await core.show_text(sid, m.chat.id, reply_to=m.message_id)
            await m.reply(err or "↑ 这是当前内容。复制、修改后，回复这条投稿发送 <code>/edit 新内容</code>。")
            return

        err = await core.edit(sid, m.from_user.full_name, body, entities, dump_link_preview(m.link_preview_options))
        await m.reply(err or f"✏️ 投稿 #{sid} 已修改，新的预览已发出，发布时将使用修改后的内容。")

    @router.message(Command("ban"))
    async def ban_cmd(m: Message, command: CommandObject, core: Core) -> None:
        args = command.args or ""
        sid = await _replied_sid(m, core)
        if sid is not None:
            user_id, reason = (await core.db.get(sid)).user_id, _clean_reason(args)
        elif m.reply_to_message:
            await m.reply("请回复投稿的预览或控制消息。")
            return
        else:
            kind, ref, reason = _split_ref(args)
            if ref is None:
                await m.reply("用法：回复投稿后发 /ban [理由]，或 /ban &lt;用户ID 或 #投稿编号&gt; [理由]")
                return
            if kind == "sid":
                sub = await core.db.get(ref)
                if not sub:
                    await m.reply(f"投稿 #{ref} 不存在")
                    return
                user_id = sub.user_id
            else:
                user_id = ref

        rejected = await core.ban_user(user_id, m.from_user, reason)
        user = await core.db.get_user(user_id)
        text = f"🚫 已封禁 {user_link(user, user_id)} <code>{user_id}</code>"
        if reason:
            text += f"\n理由：{html.escape(reason)}"
        if rejected:
            text += f"\n已自动拒绝其 {len(rejected)} 条未处理来稿：{'、'.join(f'#{i}' for i in rejected)}"
        await m.reply(text, link_preview_options=NO_PREVIEW)

    @router.message(Command("unban"))
    async def unban_cmd(m: Message, command: CommandObject, core: Core) -> None:
        uid = _user_id_arg(command)
        if uid is None:
            sid = await _replied_sid(m, core)
            uid = (await core.db.get(sid)).user_id if sid is not None else None
        if uid is None:
            await m.reply("用法：/unban &lt;用户ID&gt;，或回复该用户的投稿")
            return
        if not await core.unban_user(uid):
            await m.reply(f"用户 <code>{uid}</code> 没有被封禁。")
            return
        await m.reply(f"✅ 已解除封禁 <code>{uid}</code>。")

    # ---------- 自定义定时：等待管理员回复时间 ----------

    @router.message(ScheduleInput.waiting, F.text)
    async def on_time_input(m: Message, state: FSMContext, core: Core) -> None:
        data = await state.get_data()
        sid, prompt_id = data["sid"], data.get("prompt_id")

        # 只接受对提示消息的回复，避免把群里其他聊天当成时间
        if not m.reply_to_message or m.reply_to_message.message_id != prompt_id:
            return

        if m.text.strip() in ("取消", "cancel"):
            await state.clear()
            await m.reply("已取消自定义定时。")
            return

        ts = parse_time(m.text, settings.tz)
        if ts is None:
            await m.reply("看不懂这个时间 🤔 例如 <code>20:30</code>、<code>10-20 09:00</code>、<code>+2h</code>")
            return

        err = await core.schedule(sid, ts, m.from_user)
        if err:
            await m.reply(err)
            if err != "这个时间已经过去了":
                await state.clear()
            return

        await state.clear()
        await m.reply(f"⏰ 投稿 #{sid} 将于 <b>{fmt_ts(ts, settings.tz)}</b> 发布。")
        try:
            await m.bot.delete_message(m.chat.id, prompt_id)
        except TelegramAPIError:
            pass

    return router
