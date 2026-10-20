from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from aiogram.enums import ButtonStyle
from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from .db import Submission
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


def user_choice_kb(sid: int) -> InlineKeyboardMarkup:
    def b(text: str, a: str, style: ButtonStyle | None = None) -> InlineKeyboardButton:
        return InlineKeyboardButton(text=text, callback_data=UserCB(a=a, sid=sid).pack(), style=style)

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [b("👤 署名投稿", "sign", BLUE), b("🕶 匿名投稿", "anon", BLUE)],
            [b("取消", "cancel")],
        ]
    )


def control_kb(sub: Submission) -> InlineKeyboardMarkup | None:
    sid = sub.id
    rows: list[list[InlineKeyboardButton]] = []
    if sub.status in ("pending", "scheduled", "failed"):
        options = [
            _rb(f"{'🔕' if sub.silent else '🔔'} 静音：{'开' if sub.silent else '关'}", "silent", sid,
                style=_toggle(sub.silent))
        ]
        if sub.spoilerable:
            options.insert(0, _rb(f"🙈 剧透：{'开' if sub.spoiler else '关'}", "spoiler", sid,
                                  style=_toggle(sub.spoiler)))
        rows.append(options)
    if sub.status == "pending":
        rows.append([_rb("✅ 立即发布", "pub", sid, style=GREEN), _rb("⏰ 定时发布", "sched", sid, style=BLUE)])
        rows.append([_rb("❌ 拒绝", "reject", sid, style=RED), _rb("🚫 封禁投稿人", "ban", sid, style=RED)])
    elif sub.status == "scheduled":
        rows.append([_rb("🚀 立即发布", "pub", sid, style=GREEN), _rb("⏰ 改时间", "sched", sid, style=BLUE)])
        rows.append([_rb("↩️ 取消定时", "unsched", sid), _rb("❌ 拒绝", "reject", sid, style=RED)])
    elif sub.status == "failed":
        rows.append([_rb("🔁 重试发布", "retry", sid, style=GREEN), _rb("❌ 拒绝", "reject", sid, style=RED)])
    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


def schedule_kb(sid: int, presets: tuple[str, ...], tz: ZoneInfo) -> InlineKeyboardMarkup:
    now = datetime.now(tz)
    buttons = [
        _rb("+1 小时", "preset", sid, int((now + timedelta(hours=1)).timestamp()), style=BLUE),
        _rb("+3 小时", "preset", sid, int((now + timedelta(hours=3)).timestamp()), style=BLUE),
    ]
    for hhmm in presets:
        dt = next_occurrence(hhmm, tz, now)
        day = "今天" if dt.date() == now.date() else "明天"
        buttons.append(_rb(f"{day} {dt:%H:%M}", "preset", sid, int(dt.timestamp()), style=BLUE))

    rows = [buttons[i : i + 3] for i in range(0, len(buttons), 3)]
    rows.append([_rb("✏️ 自定义时间", "custom", sid), _rb("« 返回", "back", sid)])
    return InlineKeyboardMarkup(inline_keyboard=rows)
