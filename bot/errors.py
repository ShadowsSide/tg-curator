"""业务层的结果提示：只带文案代码和参数，不带语言。

core 返回 Notice（或 None 表示成功），由处理函数在显示时按对方的语言翻译：
审核群用 LANGUAGE，私聊用投稿人的语言。判断是哪种情况时比较 key，不比较文字。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .i18n import t


@dataclass(frozen=True)
class Notice:
    key: str
    params: dict[str, Any] = field(default_factory=dict)

    def text(self, lang: str) -> str:
        # 参数本身也可以是 Notice（例如“开 / 关”），用同一种语言一起翻译
        params = {k: v.text(lang) if isinstance(v, Notice) else v for k, v in self.params.items()}
        return t(lang, self.key, **params)


def notice(key: str, **params: Any) -> Notice:
    return Notice(key, params)
