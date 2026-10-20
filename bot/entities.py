"""消息格式（MessageEntity）处理。

投稿内容保存的是 Telegram 原始的 text + entities，发送时原样带回去（不经过 HTML/Markdown 转换），
这样超链接、粗体、引用、剧透文字、自定义 emoji、日期时间等所有格式（包括以后新增的类型）都能保持不变。

注意：entity 的 offset/length 以 UTF-16 code unit 计，emoji 等字符在 Python 里占 1 个字符，
在 UTF-16 里可能占 2 个，所以拼接/截取时必须按 UTF-16 计算。
"""
from __future__ import annotations

import re
from typing import Any

Entity = dict[str, Any]

_COMMAND = re.compile(r"^/\w+(?:@\w+)?[ \t]*\n?")


def u16len(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def dump(entities) -> list[Entity]:
    """aiogram 的 MessageEntity 列表 → 可存 JSON 的 dict（保留未知字段，如 date_time 的参数）。"""
    return [e.model_dump(mode="json", exclude_none=True) for e in entities or []]


def cut_prefix(text: str, entities: list[Entity], chars: int) -> tuple[str, list[Entity]]:
    """去掉开头 chars 个（Python）字符，entities 相应平移；跨越切点的 entity 被截短。"""
    cut = u16len(text[:chars])
    out = []
    for e in entities:
        start, end = e["offset"], e["offset"] + e["length"]
        if end <= cut:
            continue
        new_start = max(start, cut)
        out.append({**e, "offset": new_start - cut, "length": end - new_start})
    return text[chars:], out


def strip_command(text: str, entities: list[Entity]) -> tuple[str, list[Entity]]:
    """'/edit@bot 新内容' → '新内容'，保留新内容里的所有格式。"""
    m = _COMMAND.match(text)
    return cut_prefix(text, entities, m.end()) if m else (text, entities)


def join(body: str, body_entities: list[Entity], tail: str, tail_entities: list[Entity],
         sep: str = "\n\n") -> tuple[str, list[Entity]]:
    """正文 + 落款，落款的 entities 平移到拼接后的位置。"""
    if not tail:
        return body, list(body_entities)
    if not body:
        return tail, list(tail_entities)
    shift = u16len(body + sep)
    return body + sep + tail, list(body_entities) + [{**e, "offset": e["offset"] + shift} for e in tail_entities]


def has_custom_emoji(entities: list[Entity]) -> bool:
    return any(e["type"] == "custom_emoji" for e in entities)


def without_custom_emoji(entities: list[Entity]) -> list[Entity]:
    """自定义 emoji 的 entity 覆盖在一个普通 emoji 字符上，去掉 entity 后会显示为对应的普通 emoji。"""
    return [e for e in entities if e["type"] != "custom_emoji"]
