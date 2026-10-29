"""投稿防垃圾：关键词黑名单、链接数量上限（白名单域名不计）。纯函数，不访问数据库和网络。

检查结果是命中项列表，每项是可存 JSON 的 dict，显示时再按语言翻译（render.spam_line）：
  {"k": "keyword", "word": "加微信"}
  {"k": "links", "n": 3, "max": 2}
没有命中时返回空列表。新用户冷却是按投稿时间判断的，在 core/submissions.py 里。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

LINK_TYPES = ("url", "text_link")


@dataclass(frozen=True)
class SpamRules:
    keywords: tuple[str, ...] = ()  # 已转成小写
    max_links: int = 0  # 0 = 不限
    whitelist: tuple[str, ...] = ()  # 域名，已转成小写；子域名也算（t.me 包括 www.t.me）

    @classmethod
    def parse(cls, keywords: str, max_links: int, whitelist: str) -> "SpamRules":
        def split(value: str) -> tuple[str, ...]:
            return tuple(x.strip().lower() for x in value.replace("，", ",").split(",") if x.strip())

        return cls(split(keywords), max(max_links, 0), split(whitelist))

    @property
    def enabled(self) -> bool:
        return bool(self.keywords or self.max_links)


def _u16_slice(text: str, offset: int, length: int) -> str:
    """按 UTF-16 偏移截取（entity 的 offset/length 以 UTF-16 计）。"""
    raw = text.encode("utf-16-le")
    return raw[offset * 2:(offset + length) * 2].decode("utf-16-le", errors="ignore")


def links(items: list[dict[str, Any]]) -> list[str]:
    """稿件里所有链接：Telegram 自动识别的网址（url）和超链接（text_link）。"""
    out = []
    for it in items:
        text = it.get("text") or ""
        for e in it.get("entities") or []:
            if e.get("type") == "url":
                out.append(_u16_slice(text, e["offset"], e["length"]))
            elif e.get("type") == "text_link" and e.get("url"):
                out.append(e["url"])
    return out


def host(url: str) -> str:
    try:
        return (urlsplit(url if "://" in url else "http://" + url).hostname or "").lower()
    except ValueError:  # 无法解析的网址按“不在白名单”处理
        return ""


def whitelisted(url: str, whitelist: tuple[str, ...]) -> bool:
    h = host(url)
    return bool(h) and any(h == d or h.endswith("." + d) for d in whitelist)


def check(items: list[dict[str, Any]], rules: SpamRules) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    if not rules.enabled:
        return hits
    # 关键词同时查文字和链接地址（超链接的地址不在文字里）
    haystack = "\n".join([*(it.get("text") or "" for it in items), *links(items)]).lower()
    for word in rules.keywords:
        if word in haystack:
            hits.append({"k": "keyword", "word": word})
    if rules.max_links:
        n = sum(1 for url in links(items) if not whitelisted(url, rules.whitelist))
        if n > rules.max_links:
            hits.append({"k": "links", "n": n, "max": rules.max_links})
    return hits
