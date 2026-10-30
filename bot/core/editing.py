"""修改稿件（管理员 / 投稿人共用）：/edit、Telegram 自带编辑，格式由 entities 原样保留。"""
from __future__ import annotations

import logging

from aiogram.exceptions import TelegramAPIError
from aiogram.types import Message

from .. import media, spam
from ..db import OPEN_STATES, Submission
from ..entities import u16len
from ..errors import Notice, notice
from ..render import caption_index, send_items
from ..timeutil import now_ts
from .base import CoreBase

log = logging.getLogger(__name__)


class EditingMixin(CoreBase):
    # ---------- 修改稿件（管理员 / 投稿人共用；lang 是调用方的语言） ----------

    async def edit(self, sid: int, editor: str, text: str, entities: list, link_preview: dict | None = None,
                   allowed: tuple[str, ...] = OPEN_STATES) -> Notice | None:
        """修改稿件的文字（文字投稿改正文，媒体投稿改说明文字），格式由 entities 原样保留。"""
        sub = await self.db.get(sid)
        err = self._check_editable(sub, sid, allowed)
        if err:
            return err
        items = [dict(it) for it in sub.items]
        target = items[caption_index(items)]
        is_text = target["type"] == "text"
        if is_text and not text.strip():
            return notice("text_empty")
        target["text"], target["entities"] = text, entities
        if is_text:
            target["link_preview"] = link_preview
        return await self._save_edit(sub, items, editor, allowed)

    async def replace_item(self, sid: int, index: int, new_item: dict, editor: str,
                           allowed: tuple[str, ...]) -> Notice | None:
        """投稿人用 Telegram 自带的“编辑”修改了原消息：整项替换（文字、格式、甚至换图都会同步）。"""
        sub = await self.db.get(sid)
        err = self._check_editable(sub, sid, allowed)
        if err:
            return err
        items = [dict(it) for it in sub.items]
        old = items[index]
        if old["type"] in media.MEDIA_TYPES and new_item["type"] == "text":
            # 纯文字投稿加过图：原来那条文字消息现在是第一个媒体的说明，编辑它就是改说明
            items[index] = {**old, "text": new_item["text"], "entities": new_item["entities"]}
        elif (old["type"] == "text") != (new_item["type"] == "text"):
            return notice("type_change")
        else:
            items[index] = new_item
        return await self._save_edit(sub, items, editor, allowed)

    async def change_media(self, sid: int, op: str, index: int, new_items: list[dict], editor: str,
                           allowed: tuple[str, ...], by_submitter: bool) -> Notice | None:
        """新增 / 替换 / 删除图片和视频（op = add / replace / remove），规则见 media.py。
        审核员发的媒体不记 msg_id：那是审核群里的消息编号，会和投稿人私聊里的编号混淆（投稿人“编辑”时按它找稿件）。"""
        sub = await self.db.get(sid)
        err = self._check_editable(sub, sid, allowed)
        if err:
            return err
        if not by_submitter:
            new_items = [{k: v for k, v in it.items() if k != "msg_id"} for it in new_items]
        if op == "add":
            items, err = media.add(sub.items, new_items)
        elif op == "replace":
            items, err = media.replace(sub.items, index, new_items)
        else:
            items, err = media.remove(sub.items, index)
        if err:
            return err
        err = await self._save_edit(sub, items, editor, allowed)
        if not err:
            await self.refresh_user_kb(sid)
        return err

    @staticmethod
    def _check_editable(sub: Submission | None, sid: int, allowed: tuple[str, ...]) -> Notice | None:
        if not sub:
            return notice("sub_not_found", sid=sid)
        if sub.status in allowed:
            return None
        known = ("scheduled", "publishing", "published", "rejected", "cancelled", "failed")
        return notice(f"not_editable_{sub.status if sub.status in known else 'other'}", sid=sid)

    async def _save_edit(self, sub: Submission, items: list[dict], editor: str,
                         allowed: tuple[str, ...]) -> Notice | None:
        for it in items:
            limit = 4096 if it["type"] == "text" else 1024
            if u16len(it.get("text", "")) > limit:
                return notice("too_long", n=u16len(it["text"]), limit=limit)
        # 媒体自带的剧透有变化（Telegram 编辑里开关了剧透，或加 / 换 / 删了带剧透的图）时，剧透设置跟着变；
        # 没变化就保留当前设置，不覆盖审核员手动切换的结果
        has_spoiler = any(it.get("spoiler") for it in items)
        follow = {"spoiler": int(has_spoiler)} if has_spoiler != any(it.get("spoiler") for it in sub.items) else {}
        # 第一次修改前的原稿单独保存；状态变了（比如刚好被发布）就不改
        ok = await self.db.update_if(
            sub.id, allowed, items=items, original_items=sub.original_items or sub.items,
            edited_by=editor, edited_at=now_ts(),
            spam_flags=spam.check(items, self.s.spam_rules) or None,  # 改稿后可能加了广告链接，重新检查
            **follow,
        )
        if not ok:
            return notice("edit_race")
        sub = await self.db.get(sub.id)
        if sub.status != "draft":  # 草稿还没进审核群，不用发预览
            preview = await send_items(
                self.bot, self.s.review_chat_id, sub.items, sig=await self._signature(sub, link=True),
                spoiler=False, reply_to=sub.review_msg_id,
            )
            ids = [m.message_id for m in preview]
            await self.db.link_review_messages(sub.id, ids)
            await self.db.update(sub.id, edit_preview=ids)
            await self._delete_old_preview(sub.edit_preview)
            await self.refresh_control(sub.id)
        return None

    async def _delete_old_preview(self, ids: list[int] | None) -> None:
        """改稿后删掉上一份修改后的预览，审核群里只留最初的预览（控制消息回复的就是它）和最新一份。
        删不掉（超过 48 小时、已被手动删掉）就留着，它仍然能用来回复定位投稿。"""
        if not ids:
            return
        try:
            await self.bot.delete_messages(self.s.review_chat_id, ids)
        except TelegramAPIError as e:
            log.info("删除旧预览失败：%s", e)
            return
        await self.db.unlink_review_messages(ids)

    async def show_text(self, sid: int, chat_id: int, reply_to: int) -> Notice | None:
        """把稿件当前的文字（带格式）发出来，方便复制后修改再 /edit。"""
        sub = await self.db.get(sid)
        if not sub:
            return notice("sub_not_found", sid=sid)
        if not await self._send_current_text(sub, chat_id, reply_to):
            return notice("no_text_to_show", sid=sid)
        return None

    async def _send_current_text(self, sub: Submission, chat_id: int, reply_to: int) -> Message | None:
        """发出稿件当前的正文或说明文字（带格式）；没有文字时什么也不发，返回 None。"""
        target = sub.items[caption_index(sub.items)]
        if not target.get("text"):
            return None
        only_text = {"type": "text", "text": target["text"], "entities": target.get("entities", []),
                     "link_preview": {"is_disabled": True}}
        sent = await send_items(self.bot, chat_id, [only_text], sig=("", []), spoiler=False, reply_to=reply_to)
        return sent[0]
