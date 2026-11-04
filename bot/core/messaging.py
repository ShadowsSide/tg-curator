"""沟通（/msg）：审核员 ↔ 投稿人，由机器人转达，双方都看不到对方账号。"""
from __future__ import annotations

import html

from aiogram.exceptions import TelegramAPIError
from aiogram.types import User as TgUser

from .. import entities as ent
from ..db import Submission
from ..entities import u16len
from ..errors import Notice, notice
from ..i18n import t
from ..render import caption_index, send_items
from ..timeutil import now_ts
from .base import CoreBase


class MessagingMixin(CoreBase):
    # ---------- 沟通（/msg）：审核员 ↔ 投稿人，由机器人转达，双方都看不到对方账号 ----------

    def msg_blocked(self, sub: Submission) -> Notice | None:
        """审核中随时可以沟通；发布或拒绝后 MSG_WINDOW_DAYS 天内也可以；还没提交的草稿不行。"""
        if sub.status in ("draft", "cancelled"):
            return notice("msg_not_submitted")
        if sub.status in ("published", "rejected"):
            ended = sub.published_at if sub.status == "published" else sub.reviewed_at
            if ended and now_ts() - ended > self.s.msg_window_days * 86400:
                return notice("msg_closed", days=self.s.msg_window_days)
        return None

    @staticmethod
    def _labeled(items: list[dict], label: str) -> list[dict]:
        """在内容前面加上加粗的“💬 审核员：/ 投稿人：”，原有格式整体后移，保持不变。
        相册加在说明文字那一项前面，和发送时承载说明的是同一项。"""
        i = caption_index(items)
        label_entities = [{"type": "bold", "offset": 0, "length": u16len(label)}]
        text, entities = ent.join(label, label_entities, items[i].get("text", ""), items[i].get("entities", []),
                                  sep="\n")
        return [*items[:i], {**items[i], "text": text, "entities": entities}, *items[i + 1:]]

    async def relay_to_user(self, sid: int, reviewer: TgUser, items: list[dict]) -> Notice | None:
        """审核员 → 投稿人：以“审核员”的身份发到投稿人那条投稿下面。items：一条，或相册的每一项。"""
        sub = await self.db.get(sid)
        if not sub:
            return notice("sub_not_found")
        err = self.msg_blocked(sub)
        if err:
            return err
        lang = await self.user_lang(sub.user_id)
        try:
            sent = await send_items(
                self.bot, sub.user_id, self._labeled(items, t(lang, "msg_from_reviewer")), sig=("", []),
                spoiler=any(it.get("spoiler") for it in items), reply_to=sub.user_msg_id,
            )
        except TelegramAPIError as e:
            return notice("msg_undelivered", error=html.escape(str(e)))  # 错误原文可能带 < >，消息按 HTML 解析
        await self.db.log_message(sid, "to_user", reviewer.id, reviewer.full_name,
                                  [(it, m.message_id, None) for it, m in zip(items, sent)])
        await self.refresh_control(sid)
        return None

    async def relay_to_review(self, sid: int, user: TgUser, items: list[dict], user_msg_ids: list[int]) -> Notice | None:
        """投稿人 → 审核员：发到审核群，回复在这条投稿的控制按钮消息下面。items：一条，或相册的每一项。"""
        sub = await self.db.get(sid)
        if not sub or sub.user_id != user.id:
            return notice("u_edit_not_found")
        db_user = await self.db.get_user(user.id)
        if db_user and db_user.banned:
            return notice("banned")
        err = self.msg_blocked(sub) or self._too_often(user.id)
        if err:
            return err
        try:
            sent = await send_items(
                self.bot, self.s.review_chat_id, self._labeled(items, t(self.lang, "msg_from_submitter")),
                sig=("", []), spoiler=any(it.get("spoiler") for it in items), reply_to=sub.review_msg_id,
            )
        except TelegramAPIError as e:
            return notice("msg_failed", error=html.escape(str(e)))  # 错误原文可能带 < >，消息按 HTML 解析
        self.throttle.record(user.id)  # 发出去了才算一次
        # 审核员回复这条转来的消息发 /msg，就能定位到这条投稿
        await self.db.link_review_messages(sid, [m.message_id for m in sent])
        await self.db.log_message(sid, "to_review", user.id, user.full_name,
                                  [(it, u, r.message_id) for it, u, r in zip(items, user_msg_ids, sent)])
        await self.refresh_control(sid)
        return None
