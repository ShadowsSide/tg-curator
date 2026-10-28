"""修改稿件里的媒体：新增（/add）、替换（/replace）、删除（/remove）。纯函数，不访问数据库和网络。

只处理图片和视频（能放进同一个相册的类型）：
- 新增：追加到末尾，最多 MAX_MEDIA 个。纯文字投稿也能加：原来的文字（含格式）变成第一个媒体的说明文字，
  链接预览不再有；说明文字最多 1024 字，超出时由 core 的保存步骤拒绝
- 替换：换掉第 index 个媒体（从 1 开始），原来那一项的说明文字、“说明在上方”保持不变
- 删除：删掉第 index 个媒体；不能删到一个都不剩。被删的那一项带着说明文字时，说明移到剩下的第一项
新加入的媒体不带说明文字（发命令那条消息的说明是命令本身）。
返回 (新的 items, None)，或者 (None, 提示) 表示不能这样改。
"""
from __future__ import annotations

from typing import Any

from .errors import Notice, notice

MEDIA_TYPES = ("photo", "video")
MAX_MEDIA = 10  # Telegram 相册最多 10 项

Items = list[dict[str, Any]]


def _bare(item: dict[str, Any]) -> dict[str, Any]:
    """新加入的媒体：去掉说明文字。"""
    return {**item, "text": "", "entities": [], "above": False}


def _check_new(new: Items) -> Notice | None:
    if not new or any(it["type"] not in MEDIA_TYPES for it in new):
        return notice("media_only_photo_video")
    return None


def _check_existing(items: Items) -> Notice | None:
    if any(it["type"] not in MEDIA_TYPES for it in items):
        return notice("media_mixed_types")
    return None


def _check_index(items: Items, index: int) -> Notice | None:
    if not 1 <= index <= len(items):
        return notice("media_bad_index", n=index, count=len(items))
    return None


def is_text(items: Items) -> bool:
    return len(items) == 1 and items[0]["type"] == "text"


def add(items: Items, new: Items) -> tuple[Items | None, Notice | None]:
    err = _check_new(new)
    if err:
        return None, err
    if is_text(items):
        # 纯文字投稿加图：文字（含格式）变成第一个媒体的说明文字。保留原文字消息的 msg_id，
        # 投稿人以后用 Telegram 的“编辑”改那条文字，就是改这段说明（见 core/editing.replace_item）
        text = items[0]
        first = {**_bare(new[0]), "text": text.get("text", ""), "entities": text.get("entities", []),
                 "msg_id": text.get("msg_id")}
        result = [first, *(_bare(it) for it in new[1:])]
    else:
        err = _check_existing(items)
        if err:
            return None, err
        result = [*items, *(_bare(it) for it in new)]
    if len(result) > MAX_MEDIA:
        return None, notice("media_too_many", max=MAX_MEDIA)
    return result, None


def replace(items: Items, index: int, new: Items) -> tuple[Items | None, Notice | None]:
    if is_text(items):
        return None, notice("media_none")
    err = _check_new(new) or _check_existing(items) or _check_index(items, index)
    if err:
        return None, err
    if len(new) != 1:
        return None, notice("media_replace_one")
    old = items[index - 1]
    keep = {"text": old.get("text", ""), "entities": old.get("entities", []), "above": old.get("above", False)}
    result = list(items)
    result[index - 1] = {**new[0], **keep}
    return result, None


def remove(items: Items, index: int) -> tuple[Items | None, Notice | None]:
    if is_text(items):
        return None, notice("media_none")
    err = _check_existing(items) or _check_index(items, index)
    if err:
        return None, err
    if len(items) == 1:
        return None, notice("media_last_one")
    gone = items[index - 1]
    result = [it for i, it in enumerate(items) if i != index - 1]
    if gone.get("text") and not any(it.get("text") for it in result):
        # 说明文字跟着被删的那一项走了：移到剩下的第一项，免得说明（和频道落款的位置）丢失
        result[0] = {**result[0], "text": gone["text"], "entities": gone.get("entities", []),
                     "above": gone.get("above", False)}
    return result, None
