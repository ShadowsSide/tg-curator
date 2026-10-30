from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from aiogram.enums import ButtonStyle
from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from .db import Submission
from .media import MAX_MEDIA, MEDIA_TYPES
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
CONFIRMABLE = {"pub": GREEN, "reject": RED, "ban": RED, "mrm": RED, "unban": BLUE}
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


class UserMediaCB(CallbackData, prefix="um"):
    """投稿人改图片的按钮。单独一类：给 UserCB 加字段会让旧消息上的按钮（u:sign:5）解析失败。"""
    a: str  # merge：把这份草稿的图片加到投稿 v 里；mdel：打开删除面板；mrm：删掉第 v 个；mback：收起删除面板
    sid: int
    v: int = 0


class ReviewCB(CallbackData, prefix="r"):
    a: str  # spoiler / silent / pub / sched / preset / custom / back / unsched / reject / ban / unban / retry
    #         edit / creason：发一条提示，回复它来修改稿件 / 写拒绝理由
    #         media：媒体面板；madd / mrep：发提示，回复图片视频来添加 / 替换第 v 个；mrm / mrm_ok：删除第 v 个
    #         pub_ok / reject_ok / ban_ok / unban_ok：确认面板上的“确认”，见 CONFIRMABLE
    #         reason：拒绝理由面板上选了一项
    # v：preset = 定时的时间戳；reason / reject / reject_ok = 第几个拒绝理由（从 1 开始，0 = 不附理由）
    sid: int
    v: int = 0


class AdminUserCB(CallbackData, prefix="au"):
    """/user 卡片上的按钮：按用户（不是按投稿）封禁 / 解封。单独一类，ReviewCB 的 sid 是投稿编号。"""
    a: str  # ban / unban：出确认面板；ban_ok / unban_ok：执行；back：收起确认面板
    uid: int


def user_card_kb(uid: int, banned: bool, lang: str) -> InlineKeyboardMarkup:
    """/user 卡片：没被封禁显示“封禁”，被封禁显示“解除封禁”。"""
    if banned:
        button = InlineKeyboardButton(text=t(lang, "btn_unban"), style=CONFIRMABLE["unban"],
                                      callback_data=AdminUserCB(a="unban", uid=uid).pack())
    else:
        button = InlineKeyboardButton(text=t(lang, "btn_ban_user"), style=CONFIRMABLE["ban"],
                                      callback_data=AdminUserCB(a="ban", uid=uid).pack())
    return InlineKeyboardMarkup(inline_keyboard=[[button]])


def user_confirm_kb(uid: int, action: str, lang: str) -> InlineKeyboardMarkup:
    """/user 卡片的二次确认面板，和控制消息上的确认面板用同样的文字和颜色。"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(lang, f"btn_confirm_{action}"), style=CONFIRMABLE[action],
                              callback_data=AdminUserCB(a=action + CONFIRMED, uid=uid).pack())],
        [InlineKeyboardButton(text=t(lang, "btn_back"), callback_data=AdminUserCB(a="back", uid=uid).pack())],
    ])


def _rb(text: str, a: str, sid: int, v: int = 0, style: ButtonStyle | None = None) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=ReviewCB(a=a, sid=sid, v=v).pack(), style=style)


def _toggle(on: bool) -> ButtonStyle | None:
    return BLUE if on else None


def _ub(text: str, a: str, sid: int, style: ButtonStyle | None = None) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=UserCB(a=a, sid=sid).pack(), style=style)


def _umb(text: str, a: str, sid: int, v: int = 0, style: ButtonStyle | None = None) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=UserMediaCB(a=a, sid=sid, v=v).pack(), style=style)


def media_count(items: list[dict]) -> int:
    """能逐个删除的图片视频有几个；含其他类型（文件、GIF 等）时返回 0，不提供媒体操作。"""
    if any(it["type"] not in MEDIA_TYPES for it in items):
        return 0
    return len(items)


def user_kb(sub: Submission, lang: str, last_anon: bool | None = None) -> InlineKeyboardMarkup | None:
    """投稿人私聊里那条提示消息上的按钮。
    草稿：署名 / 匿名 / 取消；回复旧投稿发的图片还多一个“加到这条投稿”（sub.merge_to）。
      last_anon：上次选的是匿名（True）还是署名（False），那个按钮标上“（上次）”并排在前面；None = 第一次投稿。
    草稿和待审核：有 2 个以上图片视频时多一个“删除图片”。其他状态没有按钮。"""
    sid = sub.id
    rows: list[list[InlineKeyboardButton]] = []
    if sub.status == "draft":
        if sub.merge_to:
            rows.append([_umb(t(lang, "btn_merge"), "merge", sid, sub.merge_to, GREEN)])
        choices = [(t(lang, "btn_sign"), "sign"), (t(lang, "btn_anon"), "anon")]
        if last_anon:
            choices.reverse()
        if last_anon is not None:
            choices[0] = (t(lang, "btn_last", label=choices[0][0]), choices[0][1])
        rows.append([_ub(text, a, sid, style=BLUE) for text, a in choices])
    if sub.status in ("draft", "pending") and media_count(sub.items) > 1:
        rows.append([_umb(t(lang, "btn_user_media"), "mdel", sid)])
    if sub.status == "draft":
        rows.append([_ub(t(lang, "btn_cancel"), "cancel", sid)])
    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


def user_media_kb(sub: Submission, lang: str) -> InlineKeyboardMarkup:
    """投稿人的删除面板：“🗑 1”“🗑 2”……（按投稿里的顺序），再加“返回”。"""
    buttons = [_umb(t(lang, "btn_media_rm", n=i), "mrm", sub.id, i) for i in range(1, len(sub.items) + 1)]
    rows = [buttons[i : i + 5] for i in range(0, len(buttons), 5)]
    rows.append([_umb(t(lang, "btn_back"), "mback", sub.id)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def control_kb(sub: Submission, lang: str, banned: bool = False) -> InlineKeyboardMarkup | None:
    """控制消息的按钮。banned：投稿人已被封禁，最后一行显示“解除封禁”。"""
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
        tools = [_rb(t(lang, "btn_edit"), "edit", sid)]  # 联系投稿人只用 /msg，不做按钮
        if sub.status == "pending":  # 审核员只能在待审核时改媒体
            tools.append(_rb(t(lang, "btn_media"), "media", sid))
        rows.append(tools)
    if banned:
        rows.append([_rb(t(lang, "btn_unban"), "unban", sid, style=BLUE)])
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


def media_kb(sub: Submission, lang: str) -> InlineKeyboardMarkup:
    """审核员的媒体面板：➕ 添加；🔁 N 替换第 N 个；🗑 N 删除第 N 个（只剩一个时不能删）；« 返回。
    纯文字投稿只有“添加”。调用前已确认只含图片视频（或纯文字）。"""
    sid, items = sub.id, sub.items
    is_text = len(items) == 1 and items[0]["type"] == "text"
    n = 0 if is_text else len(items)
    rows: list[list[InlineKeyboardButton]] = []
    if n < MAX_MEDIA:
        rows.append([_rb(t(lang, "btn_media_add"), "madd", sid, style=BLUE)])
    replace = [_rb(t(lang, "btn_media_rep", n=i), "mrep", sid, i) for i in range(1, n + 1)]
    rows += [replace[i : i + 5] for i in range(0, len(replace), 5)]
    if n > 1:
        remove = [_rb(t(lang, "btn_media_rm", n=i), "mrm", sid, i) for i in range(1, n + 1)]
        rows += [remove[i : i + 5] for i in range(0, len(remove), 5)]
    rows.append([_rb(t(lang, "btn_back"), "back", sid)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def reasons_kb(sid: int, reasons: tuple[str, ...], lang: str) -> InlineKeyboardMarkup:
    """拒绝理由面板：每个理由一个按钮（v = 第几个，从 1 开始），再加“自定义理由”“不附理由”和“返回”。"""
    buttons = [_rb(r, "reason", sid, i) for i, r in enumerate(reasons, 1)]
    rows = [buttons[i : i + 2] for i in range(0, len(buttons), 2)]
    rows.append([_rb(t(lang, "btn_custom_reason"), "creason", sid), _rb(t(lang, "btn_no_reason"), "reason", sid, 0),
                 _rb(t(lang, "btn_back"), "back", sid)])
    return InlineKeyboardMarkup(inline_keyboard=rows)
