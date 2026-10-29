"""等待回复的提示：点“修改”“联系投稿人”“自定义理由”“自定义时间”、媒体面板的“添加”“替换”后，机器人发一条“请回复本消息……”，
审核员回复它就执行。提示存在数据库里，机器人重启后照样能回复。具体怎么处理回复见 handlers/review.py。"""
from __future__ import annotations

import logging

from aiogram.exceptions import TelegramAPIError
from aiogram.types import ForceReply, User as TgUser

from ..db import Prompt
from ..i18n import t
from ..timeutil import now_ts

from .base import CoreBase, PROMPT_TTL, _reply_to, mention

log = logging.getLogger(__name__)

PROMPT_PLACEHOLDER = {"time": "20:30"}  # 输入框里的灰色示例


class PromptsMixin(CoreBase):
    # ---------- 等待回复的提示 ----------

    async def ask(self, sid: int, kind: str, who: TgUser, reply_to: int, arg: int = 0) -> None:
        """在审核群发一条强制回复的提示（回复在控制消息下面，看得出是哪条投稿）。
        “修改”先把当前文字（带格式）发出来，方便复制后修改。arg：替换第几个媒体。"""
        cleanup = []
        if kind == "edit":
            sub = await self.db.get(sid)
            echo = await self._send_current_text(sub, self.s.review_chat_id, reply_to) if sub else None
            cleanup = [echo.message_id] if echo else []
        prompt = await self.bot.send_message(
            self.s.review_chat_id, t(self.lang, f"prompt_{kind}", who=mention(who), n=arg),
            reply_parameters=_reply_to(reply_to),
            reply_markup=ForceReply(selective=True, input_field_placeholder=PROMPT_PLACEHOLDER.get(kind)),
        )
        await self.db.add_prompt(self.s.review_chat_id, prompt.message_id, kind, sid, who.id, cleanup, arg)

    async def get_prompt(self, chat_id: int, message_id: int) -> Prompt | None:
        return await self.db.get_prompt(chat_id, message_id)

    async def finish_prompt(self, prompt: Prompt) -> None:
        """提示用完了（完成或取消）：删掉提示消息和附带的消息，不再接受回复。"""
        await self.db.delete_prompt(prompt.chat_id, prompt.message_id)
        try:
            await self.bot.delete_messages(prompt.chat_id, [prompt.message_id, *prompt.cleanup])
        except TelegramAPIError as e:  # 已被手动删掉、超过 48 小时等：不影响
            log.info("删除提示消息失败：%s", e)

    async def prompts_of(self, chat_id: int, user_id: int) -> list[Prompt]:
        return await self.db.prompts_of(chat_id, user_id)

    async def cancel_prompt(self, prompt: Prompt) -> None:
        """/cancel：放弃提示。"""
        await self.finish_prompt(prompt)

    async def expire_prompts(self) -> None:
        for prompt in await self.db.stale_prompts(now_ts() - PROMPT_TTL):
            await self.finish_prompt(prompt)
