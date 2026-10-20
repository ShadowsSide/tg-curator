"""把投稿内容发出去（审核群预览 / 频道），以及各种文案。"""
from __future__ import annotations

import html
import logging
from collections import Counter
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.client.default import Default
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import (
    InputMediaAudio,
    InputMediaDocument,
    InputMediaPhoto,
    InputMediaVideo,
    LinkPreviewOptions,
    Message,
    ReplyParameters,
)

from . import entities as ent
from .db import Submission, User
from .i18n import on_off, t
from .timeutil import fmt_ts

log = logging.getLogger(__name__)

def dump_link_preview(lp: LinkPreviewOptions | None) -> dict[str, Any] | None:
    """用户消息里的链接预览设置（关闭预览、大图、显示在上方等）。
    aiogram 的 LinkPreviewOptions 里未设置的字段是 Default 占位对象，不能直接 model_dump。"""
    if lp is None:
        return None
    return {k: v for k, v in lp if v is not None and not isinstance(v, Default)} or None


def extract_item(m: Message) -> dict[str, Any] | None:
    """取出可复用的 file_id，以及原始文字 + entities（不转换成 HTML，保证格式原样保留）。"""
    if m.text:
        return {"type": "text", "text": m.text, "entities": ent.dump(m.entities),
                "link_preview": dump_link_preview(m.link_preview_options), "msg_id": m.message_id}

    media = None
    if m.photo:
        media = ("photo", m.photo[-1].file_id)
    elif m.video:
        media = ("video", m.video.file_id)
    elif m.animation:  # 必须在 document 之前判断：GIF 消息同时带有 document 字段
        media = ("animation", m.animation.file_id)
    elif m.document:
        media = ("document", m.document.file_id)
    elif m.audio:
        media = ("audio", m.audio.file_id)
    elif m.voice:
        media = ("voice", m.voice.file_id)
    if not media:
        return None
    return {
        "type": media[0],
        "file_id": media[1],
        "text": m.caption or "",
        "entities": ent.dump(m.caption_entities),
        "above": bool(m.show_caption_above_media),  # 用户选了“说明文字显示在媒体上方”
        "spoiler": bool(m.has_media_spoiler),  # 用户自己给媒体加了剧透
        "msg_id": m.message_id,  # 用户私聊里的原消息，用于识别投稿人后来的修改
    }


def caption_index(items: list[dict[str, Any]]) -> int:
    """相册里承载说明文字（和落款）的那一项：第一条有文字的，没有就是第一条。"""
    return next((i for i, it in enumerate(items) if it.get("text")), 0)


def describe(items: list[dict[str, Any]], lang: str) -> str:
    counts = Counter(i["type"] for i in items)
    if list(counts) == ["text"]:
        return t(lang, "type_text")
    return t(lang, "list_sep").join(t(lang, f"type_{kind}", n=n) for kind, n in counts.items())


def user_link(user: User | None, user_id: int) -> str:
    name = html.escape(user.full_name if user and user.full_name else str(user_id))
    if user and user.username:
        return f'<a href="https://t.me/{user.username}">{name}</a>'
    return f'<a href="tg://user?id={user_id}">{name}</a>'


Signature = tuple[str, list[ent.Entity]]


def signature(sub: Submission, user: User | None, sign_template: str, anon_signature: str) -> Signature:
    """落款（纯文本 + entities）。署名时投稿人名字是可点击的链接。"""
    if sub.anonymous:
        return anon_signature, []
    if "{name}" not in sign_template:
        return sign_template, []
    prefix, _, suffix = sign_template.partition("{name}")
    name = (user.full_name if user and user.full_name else "") or str(sub.user_id)
    url = f"https://t.me/{user.username}" if user and user.username else f"tg://user?id={sub.user_id}"
    link = {"type": "text_link", "offset": ent.u16len(prefix), "length": ent.u16len(name), "url": url}
    return prefix + name + suffix, [link]


def _strip_custom_emoji(items: list[dict[str, Any]], sig: Signature) -> tuple[list[dict[str, Any]], Signature]:
    items = [{**it, "entities": ent.without_custom_emoji(it.get("entities", []))} for it in items]
    return items, (sig[0], ent.without_custom_emoji(sig[1]))


async def send_items(
    bot: Bot, chat_id: int | str, items: list[dict[str, Any]], *, sig: Signature, spoiler: bool,
    silent: bool = False, reply_to: int | None = None,
) -> list[Message]:
    """发送投稿内容；单条用对应的 send_*，多条用 send_media_group。落款加在承载说明文字的那一项后面。

    文字和格式按原始 entities 发送（parse_mode=None），保证超链接、emoji、引用等格式不变。
    自定义 emoji 只有购买了 Fragment 用户名的机器人才能发到频道；被拒绝时自动退回为对应的普通 emoji 重发。
    silent=True 时订阅者收到的是无声通知（disable_notification）。
    """
    try:
        return await _send(bot, chat_id, items, sig, spoiler, silent, reply_to)
    except TelegramBadRequest as e:
        uses_custom = any(ent.has_custom_emoji(it.get("entities", [])) for it in items) or ent.has_custom_emoji(sig[1])
        if not uses_custom:
            raise
        log.warning("发送自定义 emoji 被拒绝（%s），改用普通 emoji 重发", e.message)
        items, sig = _strip_custom_emoji(items, sig)
        return await _send(bot, chat_id, items, sig, spoiler, silent, reply_to)


async def _send(bot: Bot, chat_id: int | str, items: list[dict[str, Any]], sig: Signature,
                spoiler: bool, silent: bool, reply_to: int | None) -> list[Message]:
    common: dict[str, Any] = {"disable_notification": silent, "parse_mode": None}
    if reply_to:
        common["reply_parameters"] = ReplyParameters(message_id=reply_to, allow_sending_without_reply=True)

    if len(items) == 1:
        it = items[0]
        kind = it["type"]
        text, entities = ent.join(it.get("text", ""), it.get("entities", []), *sig)
        if kind == "text":
            lp = it.get("link_preview")
            return [await bot.send_message(
                chat_id, text, entities=entities or None,
                link_preview_options=LinkPreviewOptions(**lp) if lp else None, **common,
            )]
        cap = {"caption": text or None, "caption_entities": entities or None}
        visual = {**cap, "has_spoiler": spoiler, "show_caption_above_media": it.get("above") or None}
        if kind == "photo":
            m = await bot.send_photo(chat_id, it["file_id"], **visual, **common)
        elif kind == "video":
            m = await bot.send_video(chat_id, it["file_id"], **visual, **common)
        elif kind == "animation":
            m = await bot.send_animation(chat_id, it["file_id"], **visual, **common)
        elif kind == "document":
            m = await bot.send_document(chat_id, it["file_id"], **cap, **common)
        elif kind == "audio":
            m = await bot.send_audio(chat_id, it["file_id"], **cap, **common)
        elif kind == "voice":
            m = await bot.send_voice(chat_id, it["file_id"], **cap, **common)
        else:
            raise ValueError(f"unknown item type {kind}")
        return [m]

    sig_index = caption_index(items)
    media = []
    for i, it in enumerate(items):
        text, entities = it.get("text", ""), it.get("entities", [])
        if i == sig_index:
            text, entities = ent.join(text, entities, *sig)
        cap = {"media": it["file_id"], "caption": text or None, "caption_entities": entities or None, "parse_mode": None}
        kind = it["type"]
        if kind == "photo":
            media.append(InputMediaPhoto(**cap, has_spoiler=spoiler, show_caption_above_media=it.get("above") or None))
        elif kind == "video":
            media.append(InputMediaVideo(**cap, has_spoiler=spoiler, show_caption_above_media=it.get("above") or None))
        elif kind == "document":
            media.append(InputMediaDocument(**cap))
        elif kind == "audio":
            media.append(InputMediaAudio(**cap))
        else:
            raise ValueError(f"type {kind} cannot be in an album")
    common.pop("parse_mode")
    return await bot.send_media_group(chat_id, media, **common)


def control_text(sub: Submission, user: User | None, tz: ZoneInfo, post_url: str | None, lang: str) -> str:
    """审核群里每条投稿下方的“控制消息”。"""
    lines = [
        t(lang, "ctrl_title", sid=sub.id),
        t(lang, "ctrl_from", link=user_link(user, sub.user_id), uid=sub.user_id)
        + (t(lang, "ctrl_banned_tag") if user and user.banned else ""),
        t(lang, "ctrl_mode_anon" if sub.anonymous else "ctrl_mode_signed"),
        t(lang, "ctrl_content", desc=describe(sub.items, lang)),
    ]
    if sub.edited_at:
        lines.append(t(lang, "ctrl_edited", by=html.escape(sub.edited_by or ""), when=fmt_ts(sub.edited_at, tz, lang)))
    if sub.spoilerable:
        lines.append(t(lang, "ctrl_spoiler", state=("🙈 " if sub.spoiler else "") + on_off(lang, sub.spoiler)))
    lines.append(t(lang, "ctrl_silent", state=("🔕 " if sub.silent else "") + on_off(lang, sub.silent)))

    by = html.escape(sub.reviewer_name or "")
    status = sub.status
    if status == "pending":
        lines.append(t(lang, "status_pending"))
    elif status == "scheduled":
        lines.append(t(lang, "status_scheduled", when=fmt_ts(sub.scheduled_at, tz, lang), by=by))
    elif status == "publishing":
        lines.append(t(lang, "status_publishing"))
    elif status == "published":
        link = f'  <a href="{post_url}">{t(lang, "view")}</a>' if post_url else ""
        lines.append(t(lang, "status_published", when=fmt_ts(sub.published_at, tz, lang), by=by, link=link))
    elif status == "rejected":
        lines.append(t(lang, "status_rejected", by=by))
        if sub.reject_reason:
            lines.append(t(lang, "reason_plain", reason=html.escape(sub.reject_reason)))
    elif status == "failed":
        lines.append(t(lang, "status_failed", error=html.escape(sub.error or "")))
    else:
        lines.append(t(lang, "status_other", status=status))
    return "\n".join(lines)


def stats_text(accepted: int, rejected: int, pending: int, now: datetime, lang: str) -> str:
    reviewed = accepted + rejected
    pass_rate = accepted / reviewed * 100 if reviewed else 0.0
    review_rate = reviewed / (reviewed + pending) * 100 if reviewed + pending else 0.0
    return t(lang, "stats", accepted=accepted, rejected=rejected, pending=pending,
             pass_rate=pass_rate, review_rate=review_rate, time=f"{now:%H:%M:%S}")
