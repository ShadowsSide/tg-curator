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

# 需要二次确认的操作：点按钮先显示确认面板，确认按钮的动作是 "<动作>_ok"
CONFIRMABLE = {"pub": GREEN, "reject": RED, "ban": RED}
CONFIRMED = "_ok"


def route(action: str, v: int, has_reasons: bool) -> tuple[str, str, int]:
    """审核按钮的多步流程：这次点击是先出面板，还是真正执行。返回 (步骤, 动作, v)：
      ("reasons", "reject", 0)  点“拒绝”且配置了 REJECT_TEMPLATES：先出理由面板
      ("confirm", 动作, v)       发布 / 拒绝 / 封禁：出确认面板，v（拒绝理由）原样带到确认按钮
      ("run", 动作, v)           真正执行；确认按钮的 "<动作>_ok" 已去掉后缀
    判断顺序有讲究：理由面板上选的 "reason" 要先变成 "reject" 再进确认，所以理由判断在确认之前。
    """
    if action == "reject" and has_reasons:
        return "reasons", action, 0
    if action == "reason":  # 理由面板上选了一项（配置被清空后点旧面板也一样处理）
        action = "reject"
    if action in CONFIRMABLE:
        return "confirm", action, v
    return "run", action.removesuffix(CONFIRMED), v


class UserCB(CallbackData, prefix="u"):
    a: str  # sign / anon / cancel
    sid: int


class ReviewCB(CallbackData, prefix="r"):
    a: str  # spoiler / silent / pub / sched / preset / custom / back / unsched / reject / ban / retry
    #         edit / msg / creason：发一条提示，回复它来修改稿件 / 给投稿人发消息 / 写拒绝理由
    #         pub_ok / reject_ok / ban_ok：确认面板上的“确认”，见 CONFIRMABLE
    #         reason：拒绝理由面板上选了一项
    # v：preset = 定时的时间戳；reason / reject / reject_ok = 第几个拒绝理由（从 1 开始，0 = 不附理由）
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
    if sub.status in ("pending", "scheduled", "failed"):
        rows.append([_rb(t(lang, "btn_edit"), "edit", sid), _rb(t(lang, "btn_msg"), "msg", sid)])
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


def confirm_kb(sid: int, action: str, lang: str, v: int = 0, detail: str | None = None) -> InlineKeyboardMarkup:
    """二次确认面板。v 原样带到确认按钮上；detail 显示在确认按钮里（例如拒绝理由）。"""
    label = t(lang, f"btn_confirm_{action}")
    if detail:
        label = t(lang, "btn_confirm_with", label=label, detail=detail)
    return InlineKeyboardMarkup(inline_keyboard=[
        [_rb(label, action + CONFIRMED, sid, v, style=CONFIRMABLE[action])],
        [_rb(t(lang, "btn_back"), "back", sid)],
    ])


def reasons_kb(sid: int, reasons: tuple[str, ...], lang: str) -> InlineKeyboardMarkup:
    """拒绝理由面板：每个理由一个按钮（v = 第几个，从 1 开始），再加“自定义理由”“不附理由”和“返回”。"""
    buttons = [_rb(r, "reason", sid, i) for i, r in enumerate(reasons, 1)]
    rows = [buttons[i : i + 2] for i in range(0, len(buttons), 2)]
    rows.append([_rb(t(lang, "btn_custom_reason"), "creason", sid), _rb(t(lang, "btn_no_reason"), "reason", sid, 0),
                 _rb(t(lang, "btn_back"), "back", sid)])
    return InlineKeyboardMarkup(inline_keyboard=rows)
