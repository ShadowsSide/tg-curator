from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from aiogram.enums import ButtonStyle
from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from .db import Submission
from .i18n import on_off, t
from .timeutil import next_occurrence

# 按钮颜色（Bot API 的 InlineKeyboardButton.style）：
#   SUCCESS 绿 —— 通过 / 发布
#   PRIMARY 蓝 —— 常规操作、已开启的开关
#   DANGER  红 —— 拒绝 / 封禁
#   None       —— 客户端默认样式（次要操作、关闭状态的开关）
# 不支持按钮颜色的旧版客户端会忽略 style，按默认样式显示。
GREEN, BLUE, RED = ButtonStyle.SUCCESS, ButtonStyle.PRIMARY, ButtonStyle.DANGER


class UserCB(CallbackData, prefix="u"):
    a: str  # sign / anon / cancel
    sid: int


class ReviewCB(CallbackData, prefix="r"):
    a: str  # spoiler / silent / pub / sched / preset / custom / back / unsched / reject / ban / retry
    sid: int
    v: int = 0


def _rb(text: str, a: str, sid: int, v: int = 0, style: ButtonStyle | None = None) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=ReviewCB(a=a, sid=sid, v=v).pack(), style=style)


def _toggle(on: bool) -> ButtonStyle | None:
    return BLUE if on else None


def user_choice_kb(sid: int, lang: str) -> InlineKeyboardMarkup:
    def b(text: str, a: str, style: ButtonStyle | None = None) -> InlineKeyboardButton:
        return InlineKeyboardButton(text=text, callback_data=UserCB(a=a, sid=sid).pack(), style=style)

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [b(t(lang, "btn_sign"), "sign", BLUE), b(t(lang, "btn_anon"), "anon", BLUE)],
            [b(t(lang, "btn_cancel"), "cancel")],
        ]
    )


def control_kb(sub: Submission, lang: str) -> InlineKeyboardMarkup | None:
    sid = sub.id
    rows: list[list[InlineKeyboardButton]] = []
    if sub.status in ("pending", "scheduled", "failed"):
        silent = t(lang, "btn_silent", icon="🔕" if sub.silent else "🔔", state=on_off(lang, sub.silent))
        options = [_rb(silent, "silent", sid, style=_toggle(sub.silent))]
        if sub.spoilerable:
            spoiler = t(lang, "btn_spoiler", state=on_off(lang, sub.spoiler))
            options.insert(0, _rb(spoiler, "spoiler", sid, style=_toggle(sub.spoiler)))
        rows.append(options)
    reject = _rb(t(lang, "btn_reject"), "reject", sid, style=RED)
    if sub.status == "pending":
        rows.append([_rb(t(lang, "btn_publish"), "pub", sid, style=GREEN),
                     _rb(t(lang, "btn_schedule"), "sched", sid, style=BLUE)])
        rows.append([reject, _rb(t(lang, "btn_ban"), "ban", sid, style=RED)])
    elif sub.status == "scheduled":
        rows.append([_rb(t(lang, "btn_publish_now"), "pub", sid, style=GREEN),
                     _rb(t(lang, "btn_reschedule"), "sched", sid, style=BLUE)])
        rows.append([_rb(t(lang, "btn_unschedule"), "unsched", sid), reject])
    elif sub.status == "failed":
        rows.append([_rb(t(lang, "btn_retry"), "retry", sid, style=GREEN), reject])
    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


def schedule_kb(sid: int, presets: tuple[str, ...], tz: ZoneInfo, lang: str) -> InlineKeyboardMarkup:
    now = datetime.now(tz)
    buttons = [
        _rb(t(lang, "btn_plus_hours", n=h), "preset", sid, int((now + timedelta(hours=h)).timestamp()), style=BLUE)
        for h in (1, 3)
    ]
    for hhmm in presets:
        dt = next_occurrence(hhmm, tz, now)
        day = t(lang, "today" if dt.date() == now.date() else "tomorrow")
        buttons.append(_rb(f"{day} {dt:%H:%M}", "preset", sid, int(dt.timestamp()), style=BLUE))

    rows = [buttons[i : i + 3] for i in range(0, len(buttons), 3)]
    rows.append([_rb(t(lang, "btn_custom_time"), "custom", sid), _rb(t(lang, "btn_back"), "back", sid)])
    return InlineKeyboardMarkup(inline_keyboard=rows)
