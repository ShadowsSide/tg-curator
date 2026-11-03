"""修改稿件（管理员 / 投稿人共用）：/edit、Telegram 自带编辑，格式由 entities 原样保留。"""
from __future__ import annotations

import logging

from aiogram.exceptions import TelegramAPIError
from aiogram.types import Message

from .. import media, spam
from ..db import OPEN_STATES, Submission
from ..errors import Notice, notice
from ..render import caption_index, send_items
from ..timeutil import now_ts
from .base import CoreBase

log = logging.getLogger(__name__)


class EditingMixin(CoreBase):
    # ---------- 修改稿件（管理员 / 投稿人共用；lang 是调用方的语言） ----------

    async def edit(self, sid: int, editor: str, text: str, entities: list, link_preview: dict | None = None,
                   allowed: tuple[str, ...] = OPEN_STATES, by_submitter: bool = False) -> Notice | None:
        """修改稿件的文字（文字投稿改正文，媒体投稿改说明文字），格式由 entities 原样保留。
        by_submitter：投稿人自己改的，要过垃圾拦截（审核员改的不拦）。"""
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
        return await self._save_edit(sub, items, editor, allowed, by_submitter=by_submitter)

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
        return await self._save_edit(sub, items, editor, allowed, by_submitter=True)

    async def change_media(self, sid: int, op: str, index: int, new_items: list[dict], editor: str,
                           allowed: tuple[str, ...], by_submitter: bool, version: int | None = None) -> Notice | None:
        """新增 / 替换 / 删除图片和视频（op = add / replace / remove），规则见 media.py。
        审核员发的媒体不记 msg_id：那是审核群里的消息编号，会和投稿人私聊里的编号混淆（投稿人“编辑”时按它找稿件）。
        version：按钮 / 提示上的序号是按这个内容版本排的；之后内容又被改过，序号可能指向另一张，就不改。"""
        sub = await self.db.get(sid)
        err = self._check_editable(sub, sid, allowed)
        if err:
            return err
        if version is not None and sub.version != version:
            return notice("media_stale")
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
        err = await self._save_edit(sub, items, editor, allowed, by_submitter=by_submitter)
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
                         allowed: tuple[str, ...], *, by_submitter: bool) -> Notice | None:
        # 审核员改过之后投稿人再改，会悄悄盖掉审核员的修改（/edit、原生编辑都是整段替换），只能 /msg 沟通
        if by_submitter and sub.reviewer_edited:
            return notice("locked_by_reviewer")
        # 审核员第一次改稿（草稿还没进审核群，不算）：锁住投稿人的修改，并告诉他一次
        locking = not by_submitter and sub.status != "draft" and not sub.reviewer_edited
        err = await self._length_error(sub, items, signed=sub.status != "draft")
        if err:
            return err
        # 改稿后可能加了广告链接，重新检查；SPAM_ACTION=block 时投稿人不能靠“先提交、后改稿”绕过拦截
        hits = spam.check(items, self.s.spam_rules)
        err = self._spam_blocked(hits) if by_submitter else None
        if not err and by_submitter and sub.status != "draft":  # 草稿还没进审核群，改多少次都不发消息
            err = self._too_often(sub.user_id)
        if err:
            return err
        # 先发预览再保存：预览发不出去就不改稿件，否则审核员可能发布没看过的内容
        preview = None
        if sub.status != "draft":  # 草稿还没进审核群，不用发预览
            try:
                preview = await send_items(
                    self.bot, self.s.review_chat_id, items, sig=await self._signature(sub, link=True),
                    spoiler=False, reply_to=sub.review_msg_id,
                )
            except TelegramAPIError:
                log.exception("投稿 #%s 的修改预览发送失败，修改未保存", sub.id)
                return notice("edit_preview_failed")
        ids = [m.message_id for m in preview or []]
        # 媒体自带的剧透有变化（Telegram 编辑里开关了剧透，或加 / 换 / 删了带剧透的图）时，剧透设置跟着变；
        # 没变化就保留当前设置，不覆盖审核员手动切换的结果
        has_spoiler = any(it.get("spoiler") for it in items)
        follow = {"spoiler": int(has_spoiler)} if has_spoiler != any(it.get("spoiler") for it in sub.items) else {}
        # 第一次修改前的原稿单独保存；状态变了（比如刚好被发布）就不改
        ok = await self.db.update_if(
            sub.id, allowed, version=sub.version, items=items, original_items=sub.original_items or sub.items,
            edited_by=editor, edited_at=now_ts(),
            spam_flags=hits or None,
            **follow, **({"reviewer_edited": 1} if locking else {}),
        )
        if not ok:
            await self._delete_old_preview(ids)  # 这份预览的内容没有保存，不能留在审核群里
            fresh = await self.db.get(sub.id)
            # 状态没变、内容版本变了：别人刚改过，这次是基于旧内容改的，保存会把那次修改盖掉
            changed = fresh and fresh.status == sub.status and fresh.version != sub.version
            return notice("edit_conflict" if changed else "edit_race")
        sub = await self.db.get(sub.id)
        if ids:
            await self.db.link_review_messages(sub.id, ids)
            await self.db.update(sub.id, edit_preview=ids)
            await self._delete_old_preview(sub.edit_preview)
            await self.refresh_control(sub.id)
        if by_submitter:  # 投稿人自己的聊天里只有他当初发的那几条，看不出改完的样子
            await self.send_user_preview(sub.id)
        if locking:  # 版本锁保证同一版本只有一次保存成功，所以只会通知一次
            await self.notify(sub, "notify_reviewer_edited")
            await self.refresh_user_kb(sub.id)  # 收起“删除图片”
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

    async def send_user_preview(self, sid: int, reply_to: int | None = None) -> None:
        """在投稿人私聊里发出投稿当前的完整内容（发布时的样子；草稿还没选署名，不带落款），删掉上一份。
        回复这份预览发 /edit、/msg、图片也能找到这条投稿（见 db.find_by_user_message）。"""
        sub = await self.db.get(sid)
        if not sub:
            return
        sig = await self._signature(sub, link=False) if sub.status != "draft" else ("", [])
        try:
            sent = await send_items(self.bot, sub.user_id, sub.items, sig=sig, spoiler=sub.spoiler,
                                    reply_to=reply_to or sub.user_msg_id)
        except TelegramAPIError as e:  # 投稿人拉黑了机器人等：只是看不到预览，不影响改稿
            log.info("给投稿人发 #%s 的预览失败：%s", sid, e)
            return
        await self.db.update(sid, user_preview=[m.message_id for m in sent])
        if sub.user_preview:
            try:
                await self.bot.delete_messages(sub.user_id, sub.user_preview)
            except TelegramAPIError as e:  # 超过 48 小时、已被投稿人删掉
                log.info("删除投稿人 #%s 的旧预览失败：%s", sid, e)

    async def show_text(self, sid: int, chat_id: int, reply_to: int) -> tuple[Notice | None, int | None]:
        """把稿件当前的文字（带格式）发出来，方便复制后修改再 /edit。返回 (错误, 发出的消息)。"""
        sub = await self.db.get(sid)
        if not sub:
            return notice("sub_not_found", sid=sid), None
        sent = await self._send_current_text(sub, chat_id, reply_to)
        if not sent:
            return notice("no_text_to_show", sid=sid), None
        return None, sent.message_id

    async def _send_current_text(self, sub: Submission, chat_id: int, reply_to: int) -> Message | None:
        """发出稿件当前的正文或说明文字（带格式）；没有文字时什么也不发，返回 None。"""
        target = sub.items[caption_index(sub.items)]
        if not target.get("text"):
            return None
        only_text = {"type": "text", "text": target["text"], "entities": target.get("entities", []),
                     "link_preview": {"is_disabled": True}}
        sent = await send_items(self.bot, chat_id, [only_text], sig=("", []), spoiler=False, reply_to=reply_to)
        return sent[0]
