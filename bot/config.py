from __future__ import annotations

import os
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from .i18n import LANGS, t
from .spam import SpamRules


def _env(name: str, default: str = "", *, required: bool = False) -> str:
    value = os.getenv(name, default).strip()
    if required and not value:
        raise RuntimeError(f"缺少环境变量 {name}")
    return value


def _bool(value: str) -> bool:
    return value.lower() in ("1", "true", "yes", "on")


def _chat_id(value: str) -> int | str:
    return int(value) if value.lstrip("-").isdigit() else value


def _templates(value: str) -> tuple[str, ...]:
    return tuple(x.strip() for x in value.split("|") if x.strip())


def _quiet_hours(value: str) -> tuple[int, int] | None:
    if not value:
        return None
    start, end = value.split("-", 1)
    return int(start) % 24, int(end) % 24


@dataclass(frozen=True)
class Settings:
    bot_token: str
    channel_id: int | str
    review_chat_id: int
    tz: ZoneInfo
    db_path: str
    album_delay: float
    max_pending_per_user: int
    sign_template: str
    anon_signature: str
    schedule_presets: tuple[str, ...]
    reminder_interval_min: int
    reminder_only_when_pending: bool
    quiet_hours: tuple[int, int] | None
    stats_scope: str
    default_silent: bool
    proxy: str
    api_url: str
    language: str  # 审核群、频道落款、统计提醒的语言
    user_language: str  # 投稿人看到的语言：auto（跟随客户端）/ zh / en
    review_topics: bool  # 审核群话题模式：每条投稿一个话题
    user_topics: bool  # 私聊话题模式：每条投稿在投稿人私聊里一个话题
    leave_unknown_chats: bool  # 被拉进私聊/审核群/发布频道以外的聊天时自动退出
    msg_window_days: int  # /msg 沟通：审核结束（发布/拒绝）后还能沟通的天数
    reviewers: str  # 谁可以审核：admins（默认）/ all / 用户 ID，可组合，见 permissions.py
    reject_templates: tuple[str, ...]  # 点“拒绝”后可选的理由；为空则不显示理由面板
    spam_rules: SpamRules  # 关键词黑名单、链接上限，见 spam.py
    spam_action: str  # 命中时：flag = 照常提交但在控制消息上标记；block = 拦下不让提交
    new_user_cooldown_min: int  # 还没有稿件发布过的投稿人，两次投稿之间至少间隔几分钟；0 = 不限

    def reject_template(self, index: int) -> str | None:
        """理由面板上的第 index 个理由（从 1 开始）；0 或超出范围 = 不附理由。"""
        return self.reject_templates[index - 1] if 0 < index <= len(self.reject_templates) else None

    def in_quiet_hours(self, hour: int) -> bool:
        if not self.quiet_hours:
            return False
        start, end = self.quiet_hours
        if start < end:
            return start <= hour < end
        return hour >= start or hour < end


def _lang(value: str, allowed: tuple[str, ...], name: str) -> str:
    value = value.lower()
    if value not in allowed:
        raise RuntimeError(f"{name} 只能是 {' / '.join(allowed)}，当前是 {value!r}")
    return value


def load_settings() -> Settings:
    language = _lang(_env("LANGUAGE", "zh"), LANGS, "LANGUAGE")
    # 落款没配置时用对应语言的默认值；配置成空字符串表示不要落款
    sign = os.environ.get("SIGN_TEMPLATE")
    anon = os.environ.get("ANON_SIGNATURE")
    reasons = os.environ.get("REJECT_TEMPLATES")  # 同上：没配置用默认理由，配置成空字符串表示不要理由面板
    return Settings(
        bot_token=_env("BOT_TOKEN", required=True),
        channel_id=_chat_id(_env("CHANNEL_ID", required=True)),
        review_chat_id=int(_env("REVIEW_CHAT_ID", required=True)),
        tz=ZoneInfo(_env("TZ", "Asia/Shanghai")),
        db_path=_env("DB_PATH", "/app/data/bot.db"),
        album_delay=float(_env("ALBUM_DELAY", "1.5")),
        max_pending_per_user=int(_env("MAX_PENDING_PER_USER", "5")),
        sign_template=sign.strip() if sign is not None else t(language, "default_sign"),
        anon_signature=anon.strip() if anon is not None else t(language, "default_anon"),
        schedule_presets=tuple(
            p.strip() for p in _env("SCHEDULE_PRESETS", "09:00,12:00,18:00,21:00").split(",") if p.strip()
        ),
        reminder_interval_min=int(_env("REMINDER_INTERVAL_MINUTES", "60")),
        reminder_only_when_pending=_bool(_env("REMINDER_ONLY_WHEN_PENDING", "true")),
        quiet_hours=_quiet_hours(_env("REMINDER_QUIET_HOURS", "")),
        stats_scope=_env("STATS_SCOPE", "today"),
        default_silent=_bool(_env("DEFAULT_SILENT", "false")),
        proxy=_env("PROXY"),
        api_url=_env("TELEGRAM_API_URL"),
        language=language,
        user_language=_lang(_env("USER_LANGUAGE", "auto"), ("auto", *LANGS), "USER_LANGUAGE"),
        review_topics=_bool(_env("REVIEW_TOPICS", "false")),
        user_topics=_bool(_env("USER_TOPICS", "false")),
        leave_unknown_chats=_bool(_env("LEAVE_UNKNOWN_CHATS", "true")),
        msg_window_days=int(_env("MSG_WINDOW_DAYS", "3")),
        reviewers=_env("REVIEWERS", "admins"),
        reject_templates=_templates(reasons if reasons is not None else t(language, "default_reject_templates")),
        spam_rules=SpamRules.parse(_env("SPAM_KEYWORDS"), int(_env("MAX_LINKS", "0")), _env("LINK_WHITELIST")),
        spam_action=_lang(_env("SPAM_ACTION", "flag"), ("flag", "block"), "SPAM_ACTION"),
        new_user_cooldown_min=max(int(_env("NEW_USER_COOLDOWN_MINUTES", "0")), 0),
    )
