"""修改稿件（管理员 / 投稿人共用）：/edit、Telegram 自带编辑，格式由 entities 原样保留。"""
from __future__ import annotations

from .. import spam
from ..db import OPEN_STATES, Submission
from ..entities import u16len
from ..errors import Notice, notice
from ..render import caption_index, send_items
from ..timeutil import now_ts
from .base import CoreBase


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
        if (items[index]["type"] == "text") != (new_item["type"] == "text"):
            return notice("type_change")
        items[index] = new_item
        return await self._save_edit(sub, items, editor, allowed)

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
        # 第一次修改前的原稿单独保存；状态变了（比如刚好被发布）就不改
        ok = await self.db.update_if(
            sub.id, allowed, items=items, original_items=sub.original_items or sub.items,
            edited_by=editor, edited_at=now_ts(),
            spam_flags=spam.check(items, self.s.spam_rules) or None,  # 改稿后可能加了广告链接，重新检查
        )
        if not ok:
            return notice("edit_race")
        sub = await self.db.get(sub.id)
        if sub.status != "draft":  # 草稿还没进审核群，不用发预览
            preview = await send_items(
                self.bot, self.s.review_chat_id, sub.items, sig=await self._signature(sub),
                spoiler=False, reply_to=sub.review_msg_id, thread_id=sub.review_topic_id,
            )
            await self.db.link_review_messages(sub.id, [m.message_id for m in preview])
            await self.refresh_control(sub.id)
        return None

    async def show_text(self, sid: int, chat_id: int, reply_to: int) -> Notice | None:
        """把稿件当前的文字（带格式）发出来，方便复制后修改再 /edit。"""
        sub = await self.db.get(sid)
        if not sub:
            return notice("sub_not_found", sid=sid)
        target = sub.items[caption_index(sub.items)]
        if not target.get("text"):
            return notice("no_text_to_show", sid=sid)
        only_text = {"type": "text", "text": target["text"], "entities": target.get("entities", []),
                     "link_preview": {"is_disabled": True}}
        await send_items(self.bot, chat_id, [only_text], sig=("", []), spoiler=False, reply_to=reply_to)
        return None
