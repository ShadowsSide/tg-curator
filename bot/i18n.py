"""界面文案（中文 / English）。

- 投稿人看到的文字：按投稿人 Telegram 客户端的语言自动选择（USER_LANGUAGE=auto），也可以固定
- 审核群、频道落款、统计提醒：使用 LANGUAGE 配置的语言
新增文案时请同时提供 zh 和 en，tests/test_i18n.py 会检查两边的占位符是否一致。
"""
from __future__ import annotations

LANGS = ("zh", "en")
DEFAULT_LANG = "zh"


def normalize(code: str | None, fallback: str = DEFAULT_LANG) -> str:
    """Telegram 的 language_code（如 zh-hans、en-US）→ zh / en。"""
    if not code:
        return fallback
    code = code.lower()
    if code.startswith("zh"):
        return "zh"
    return "en"


def t(lang: str, key: str, **kw) -> str:
    entry = T[key]
    text = entry.get(lang) or entry[DEFAULT_LANG]
    return text.format(**kw) if kw else text


def on_off(lang: str, on: bool) -> str:
    return t(lang, "on" if on else "off")


T: dict[str, dict[str, str]] = {
    # ---------- 通用 ----------
    "on": {"zh": "开", "en": "on"},
    "off": {"zh": "关", "en": "off"},
    "list_sep": {"zh": "、", "en": ", "},
    "today": {"zh": "今天", "en": "Today"},
    "tomorrow": {"zh": "明天", "en": "Tomorrow"},
    "reason_line": {"zh": "\n理由：{reason}", "en": "\nReason: {reason}"},
    "sub_not_found": {
        "zh": '这条投稿不存在',
        "en": "This submission doesn't exist",
    },
    "status_changed": {"zh": "状态已变化，请刷新", "en": "The status has changed, please refresh"},
    "sign_via": {"zh": "via", "en": "via"},  # 频道落款：via（斜体）+ 名字
    "sign_anon": {"zh": "匿名", "en": "Anonymous"},
    "default_reject_templates": {
        "zh": "重复投稿|与频道主题不符|内容质量不足|含广告或推广",
        "en": "Duplicate|Off-topic|Low quality|Advertising",
    },

    # ---------- 内容类型 ----------
    "type_text": {"zh": "文字", "en": "text"},
    "type_photo": {"zh": "{n} 张图片", "en": "{n} photo(s)"},
    "type_video": {"zh": "{n} 个视频", "en": "{n} video(s)"},
    "type_animation": {"zh": "{n} 个 GIF", "en": "{n} GIF(s)"},
    "type_document": {"zh": "{n} 个文件", "en": "{n} file(s)"},
    "type_audio": {"zh": "{n} 个音频", "en": "{n} audio file(s)"},
    "type_voice": {"zh": "{n} 条语音", "en": "{n} voice message(s)"},

    # ---------- 投稿人：私聊 ----------
    "welcome": {
        "zh": (
            "👋 欢迎投稿！\n\n"
            "直接把要投稿的内容发给我即可：文字、图片、视频、GIF、文件，或一次发多张图（相册）。\n"
            "发送后选择 <b>署名</b> 或 <b>匿名</b>，审核通过后会发布到频道，结果会通知你。\n\n"
            "<b>修改投稿</b>（审核开始之前都可以改；定时、发布、拒绝后就不能改了）：\n"
            "· 直接用 Telegram 的“编辑”修改你发出的那条消息，机器人会自动同步（换图也可以）\n"
            "· 或者<b>回复</b>你的投稿，发送 <code>/edit 新内容</code>；回复时只发 /edit 会把当前内容发给你，方便复制修改\n"
            "· 要加图：<b>回复</b>你的投稿发图片或视频，选“加到这条投稿”；要删图：点投稿下面的“删除图片 / 视频”\n\n"
            "<b>和审核员沟通</b>：<b>回复</b>审核员的消息或你的投稿，发送 <code>/msg 内容</code>\n\n"
            "/me 查看我的投稿统计"
        ),
        "en": (
            "👋 Welcome! Send me anything you'd like to submit.\n\n"
            "Text, photos, videos, GIFs, files, or several photos at once (an album) all work.\n"
            "After sending, choose <b>signed</b> or <b>anonymous</b>. Once approved, it's published to the channel "
            "and you'll be notified.\n\n"
            "<b>Editing</b> (possible until the review starts; not once it's scheduled, published or rejected):\n"
            "· Use Telegram's “Edit” on the message you sent; the bot syncs it automatically (you can even swap the image)\n"
            "· Or <b>reply</b> to your submission with <code>/edit new content</code>; replying with just /edit sends "
            "you the current content so you can copy and change it\n"
            "· To add photos, <b>reply</b> to your submission with them and choose “Add to that submission”; "
            "to remove one, tap “Remove a photo / video” under your submission\n\n"
            "<b>Talking to the reviewers</b>: <b>reply</b> to the reviewer's message or your submission with "
            "<code>/msg message</code>\n\n"
            "/me shows your submission stats"
        ),
    },
    "unknown_cmd": {
        "zh": "未知命令。直接发送内容即可投稿，/help 查看说明。",
        "en": "Unknown command. Just send me the content to submit it, or use /help.",
    },
    "banned": {"zh": "🚫 你已被禁止投稿。", "en": "🚫 You are not allowed to submit."},
    "too_many": {
        "zh": "你还有较多投稿在等待处理，请稍后再投。",
        "en": "You already have several submissions waiting. Please try again later.",
    },
    "unsupported": {
        "zh": "暂不支持这种消息类型。\n支持：文字、图片、视频、GIF、文件、音频、语音，以及多图相册。",
        "en": "This kind of message isn't supported.\n"
              "Supported: text, photos, videos, GIFs, files, audio, voice messages and albums.",
    },
    "choose_mode": {
        "zh": "收到 {desc}。请选择投稿方式：\n"
              "· <b>署名</b>：频道帖子会附上你的名字\n"
              "· <b>匿名</b>：频道里不显示你是谁（管理员仍可见）",
        "en": "Got {desc}. How would you like to submit it?\n"
              "· <b>Signed</b>: the channel post shows your name\n"
              "· <b>Anonymous</b>: the channel won't show who you are (admins can still see it)",
    },
    "btn_sign": {"zh": "👤 署名投稿", "en": "👤 Signed"},
    "btn_anon": {"zh": "🕶 匿名投稿", "en": "🕶 Anonymous"},
    "btn_last": {"zh": "{label}（上次）", "en": "{label} (last time)"},
    "btn_cancel": {"zh": "取消", "en": "Cancel"},
    "invalid_sub": {"zh": "无效的投稿", "en": "Invalid submission"},
    "spam_blocked_keyword": {
        "zh": "🚫 投稿内容包含不允许的词语，请修改后重新选择投稿方式。",
        "en": "🚫 Your submission contains words that aren't allowed. Edit it and choose a mode again.",
    },
    "spam_blocked_links": {
        "zh": "🚫 投稿里的链接太多（最多 {max} 个），请修改后重新选择投稿方式。",
        "en": "🚫 Too many links in your submission (at most {max}). Edit it and choose a mode again.",
    },
    "cooldown": {
        "zh": "⏳ 投稿太频繁了，请 {m} 分钟后再提交。",
        "en": "⏳ You're submitting too often. Please try again in {m} min.",
    },
    "already_handled": {"zh": "这条投稿已经处理过了", "en": "This submission has already been handled"},
    "cannot_cancel": {"zh": "这条投稿已经提交，无法取消", "en": "This submission was already sent and can't be cancelled"},
    "cancelled": {"zh": "已取消。", "en": "Cancelled."},
    "mode_anon": {"zh": "匿名", "en": "anonymously"},
    "mode_signed": {"zh": "署名", "en": "with your name"},
    "submitted": {
        "zh": '✅ 已{mode}提交。\n审核结果会通知你，请耐心等待。',
        "en": "✅ Submitted {mode}.\nWe'll let you know the review result.",
    },
    "submitted_toast": {"zh": "已提交", "en": "Submitted"},
    "choose_or_merge": {
        "zh": "\n\n也可以把这些图片视频<b>加到你回复的那条投稿</b>里。",
        "en": "\n\nOr <b>add these photos/videos to the submission you replied to</b>.",
    },
    "btn_merge": {"zh": "➕ 加到这条投稿", "en": "➕ Add to that submission"},
    "merged": {
        "zh": "➕ 已加到你之前的投稿里。",
        "en": "➕ Added to your earlier submission.",
    },
    "merged_toast": {"zh": "已添加", "en": "Added"},
    "btn_user_media": {"zh": "🗑 删除图片 / 视频", "en": "🗑 Remove a photo / video"},
    "media_locked": {
        "zh": "审核已经开始或结束，不能再修改图片视频了。",
        "en": "The review has already started or ended, so photos and videos can't be changed any more.",
    },
    "draft_expired": {
        "zh": "已过期，如需投稿请重新发送。",
        "en": "This has expired. Please send it again if you'd still like to submit it.",
    },
    "edited_draft": {
        "zh": "✏️ 已更新。确认无误后请在上面选择署名或匿名提交。",
        "en": "✏️ Updated. When you're happy with it, choose signed or anonymous above to submit.",
    },
    "edited_pending": {
        "zh": '✏️ 投稿已更新，审核时将使用修改后的内容。',
        "en": '✏️ Updated. The review will use the new version.',
    },
    "u_edit_reply_own": {
        "zh": "请回复你自己发出的投稿内容，或机器人关于这条投稿的提示消息。",
        "en": "Please reply to a submission you sent, or to the bot's message about it.",
    },
    "u_edit_reply_needed": {
        "zh": "请<b>回复</b>你要修改的那条投稿（或机器人关于它的提示消息），再发送 <code>/edit 新内容</code>。",
        "en": "Please <b>reply</b> to the submission you want to change (or the bot's message about it) with "
              "<code>/edit new content</code>.",
    },
    "u_edit_not_found": {
        "zh": '没有找到这条投稿。',
        "en": "Couldn't find that submission.",
    },
    "u_edit_echo_hint": {
        "zh": "↑ 这是当前内容。复制、修改后，回复你的投稿发送 <code>/edit 新内容</code>。",
        "en": "↑ This is the current content. Copy and change it, then reply to your submission with "
              "<code>/edit new content</code>.",
    },
    "submitter_label": {"zh": "投稿人 {name}", "en": "submitter {name}"},

    # ---------- 通知投稿人 ----------
    "view_post": {"zh": "查看帖子", "en": "View post"},
    "notify_published": {
        "zh": '🎉 你的投稿已发布到频道！{link}',
        "en": '🎉 Your submission has been published to the channel!{link}',
    },
    "notify_scheduled": {
        "zh": '✅ 你的投稿已通过审核，将于 {when} 发布。',
        "en": '✅ Your submission was approved and will be published {when}.',
    },
    "notify_rescheduled": {
        "zh": '🕒 你的投稿发布时间已改为 {when}。',
        "en": '🕒 Your submission will now be published {when}.',
    },
    "notify_unscheduled": {
        "zh": '⏳ 你的投稿原定的发布时间已取消，重新回到审核中，有结果后会再通知你。',
        "en": "⏳ The planned publishing time for your submission was cancelled. It's back in review; "
              "you'll be notified once there's a decision.",
    },
    "notify_rejected": {
        "zh": '😢 你的投稿未通过审核。',
        "en": '😢 Your submission was not approved.',
    },
    "notify_banned_rejected": {
        "zh": '\n你待处理的 {n} 条投稿已一并拒绝。',
        "en": '\nYour {n} pending submission(s) were rejected as well.',
    },
    "notify_unbanned": {
        "zh": "✅ 你的投稿权限已恢复，欢迎继续投稿。",
        "en": "✅ You can submit again. Welcome back!",
    },

    # ---------- 修改稿件（两边共用的错误） ----------
    "not_editable_scheduled": {
        "zh": '这条投稿已通过审核、等待发布，不能修改',
        "en": "This submission has been approved and is waiting to be published, so it can't be edited",
    },
    "not_editable_publishing": {
        "zh": '这条投稿正在发布，不能修改',
        "en": "This submission is being published right now, so it can't be edited",
    },
    "not_editable_published": {
        "zh": '这条投稿已经发布，不能修改',
        "en": "This submission has already been published, so it can't be edited",
    },
    "not_editable_rejected": {
        "zh": '这条投稿已被拒绝，不能修改',
        "en": "This submission was rejected, so it can't be edited",
    },
    "not_editable_cancelled": {
        "zh": '这条投稿已取消，不能修改',
        "en": "This submission was cancelled, so it can't be edited",
    },
    "not_editable_failed": {
        "zh": '这条投稿发布失败、等待管理员处理，不能修改',
        "en": "This submission failed to publish and is waiting for an admin, so it can't be edited",
    },
    "not_editable_other": {
        "zh": '这条投稿当前状态不能修改',
        "en": "This submission can't be edited in its current state",
    },
    "text_empty": {"zh": "文字投稿的内容不能为空", "en": "A text submission can't be empty"},
    "too_long": {
        "zh": "内容太长：{n} 字，上限 {limit}（还需留出落款的长度）",
        "en": "Too long: {n} characters, the limit is {limit} (leave room for the signature too)",
    },
    "edit_race": {
        "zh": "投稿状态刚刚发生了变化，修改未生效",
        "en": "The submission's status just changed, so the edit was not applied",
    },
    "media_only_photo_video": {"zh": "只能添加图片或视频", "en": "Only photos and videos can be added"},
    "media_mixed_types": {
        "zh": "这条投稿里有文件、音频、语音或 GIF，不能和图片视频放在一起，请重新投稿",
        "en": "This submission has a file, audio, voice message or GIF, which can't be combined with photos or videos. Please submit again",
    },
    "media_too_many": {"zh": "一条投稿最多 {max} 个图片或视频", "en": "A submission can have at most {max} photos or videos"},
    "media_bad_index": {
        "zh": "没有第 {n} 个，这条投稿共有 {count} 个图片或视频",
        "en": "There's no item {n}; this submission has {count} photo(s) or video(s)",
    },
    "media_none": {"zh": "这是文字投稿，没有可以替换或删除的图片视频", "en": "This is a text submission; there's no photo or video to replace or remove"},
    "media_replace_one": {"zh": "替换时一次只能发一个图片或视频", "en": "Send exactly one photo or video to replace with"},
    "media_last_one": {"zh": "不能删除最后一个图片或视频", "en": "The last photo or video can't be removed"},
    "media_not_pending": {
        "zh": "只有待审核的投稿能修改图片视频（已定时的请先取消定时）",
        "en": "Photos and videos can only be changed while the submission is pending (unschedule it first)",
    },
    "media_nth": {"zh": "第 {n} 个", "en": "no. {n}"},
    "toast_media_removed": {"zh": "已删除第 {n} 个", "en": "Removed no. {n}"},
    "type_change": {
        "zh": "不能把文字投稿改成媒体投稿（或反过来），请重新投稿",
        "en": "A text submission can't become a media submission (or the other way round). Please submit again",
    },
    "no_text_to_show": {
        "zh": '这条投稿没有文字，直接发送 /edit 新的说明文字 即可添加',
        "en": 'This submission has no text. Send /edit followed by a caption to add one',
    },

    # ---------- 审核：控制消息 ----------
    "ctrl_title": {
        "zh": '📮 <b>新投稿</b>',
        "en": '📮 <b>New submission</b>',
    },
    "ctrl_from": {"zh": "投稿人：{link}  <code>{uid}</code>", "en": "From: {link}  <code>{uid}</code>"},
    "ctrl_banned_tag": {"zh": "  🚫已封禁", "en": "  🚫banned"},
    "ctrl_mode_anon": {"zh": "方式：🕶 匿名", "en": "Mode: 🕶 anonymous"},
    "ctrl_mode_signed": {"zh": "方式：👤 署名", "en": "Mode: 👤 signed"},
    "ctrl_content": {"zh": "内容：{desc}", "en": "Content: {desc}"},
    "ctrl_edited": {"zh": "✏️ 已修改（{by}，{when}）", "en": "✏️ Edited ({by}, {when})"},
    "ctrl_spoiler": {"zh": "剧透遮罩：{state}", "en": "Spoiler: {state}"},
    "ctrl_silent": {"zh": "静音发送：{state}", "en": "Silent: {state}"},
    "status_pending": {"zh": "状态：⏳ 待审核", "en": "Status: ⏳ pending review"},
    "status_scheduled": {
        "zh": "状态：⏰ 定时发布 <b>{when}</b>（{by}）",
        "en": "Status: ⏰ scheduled for <b>{when}</b> ({by})",
    },
    "status_publishing": {"zh": "状态：🚀 发布中…", "en": "Status: 🚀 publishing…"},
    "status_published": {"zh": "状态：✅ 已发布 {when}（{by}）{link}", "en": "Status: ✅ published {when} ({by}){link}"},
    "view": {"zh": "查看", "en": "View"},
    "status_rejected": {"zh": "状态：❌ 已拒绝（{by}）", "en": "Status: ❌ rejected ({by})"},
    "status_failed": {"zh": "状态：⚠️ 发布失败：{error}", "en": "Status: ⚠️ failed to publish: {error}"},
    "status_other": {"zh": "状态：{status}", "en": "Status: {status}"},
    "reason_plain": {"zh": "理由：{reason}", "en": "Reason: {reason}"},

    # ---------- 审核：按钮 ----------
    "btn_spoiler": {"zh": "🙈 剧透：{state}", "en": "🙈 Spoiler: {state}"},
    "btn_silent": {"zh": "{icon} 静音：{state}", "en": "{icon} Silent: {state}"},
    "btn_publish": {"zh": "✅ 立即发布", "en": "✅ Publish now"},
    "btn_schedule": {"zh": "⏰ 定时发布", "en": "⏰ Schedule"},
    "btn_reject": {"zh": "❌ 拒绝", "en": "❌ Reject"},
    "btn_ban": {"zh": "🚫 封禁投稿人", "en": "🚫 Ban submitter"},
    "btn_publish_now": {"zh": "🚀 立即发布", "en": "🚀 Publish now"},
    "btn_reschedule": {"zh": "⏰ 改时间", "en": "⏰ Reschedule"},
    "btn_unschedule": {"zh": "↩️ 取消定时", "en": "↩️ Unschedule"},
    "btn_retry": {"zh": "🔁 重试发布", "en": "🔁 Retry"},
    "btn_plus_hours": {"zh": "+{n} 小时", "en": "+{n}h"},
    "btn_custom_time": {"zh": "✏️ 自定义时间", "en": "✏️ Custom time"},
    "btn_back": {"zh": "« 返回", "en": "« Back"},
    "btn_confirm_pub": {"zh": "✅ 确认发布", "en": "✅ Confirm publish"},
    "btn_confirm_reject": {"zh": "❌ 确认拒绝", "en": "❌ Confirm reject"},
    "btn_confirm_with": {"zh": "{label}：{detail}", "en": "{label}: {detail}"},
    "btn_no_reason": {"zh": "不附理由", "en": "No reason"},
    "btn_custom_reason": {"zh": "✏️ 自定义理由", "en": "✏️ Custom reason"},
    "btn_edit": {"zh": "✏️ 修改", "en": "✏️ Edit"},
    "btn_media": {"zh": "🖼 媒体", "en": "🖼 Media"},
    "btn_media_add": {"zh": "➕ 添加图片 / 视频", "en": "➕ Add photo / video"},
    "btn_media_rep": {"zh": "🔁 换第 {n} 个", "en": "🔁 Replace {n}"},
    "btn_media_rm": {"zh": "🗑 删第 {n} 个", "en": "🗑 Remove {n}"},
    "btn_confirm_mrm": {"zh": "🗑 确认删除", "en": "🗑 Confirm remove"},
    "btn_confirm_ban": {"zh": "🚫 确认封禁（同时拒绝其所有未处理来稿）",
                        "en": "🚫 Confirm ban (also rejects all their open submissions)"},
    "btn_unban": {"zh": "🔓 解除封禁", "en": "🔓 Unban"},
    "btn_ban_user": {"zh": "🚫 封禁", "en": "🚫 Ban"},
    "btn_confirm_unban": {"zh": "🔓 确认解封（会通知投稿人）", "en": "🔓 Confirm unban (the submitter is notified)"},

    # ---------- 审核：按钮反馈 ----------
    "toast_state_locked": {"zh": "当前状态不能修改", "en": "Can't change this in the current state"},
    "toast_spoiler": {"zh": "剧透遮罩：{state}", "en": "Spoiler: {state}"},
    "toast_silent": {"zh": "静音发送：{state}", "en": "Silent: {state}"},
    "toast_pick_reason": {
        "zh": "选择拒绝理由（自定义理由请回复 /no 理由）",
        "en": "Pick a reason (for your own, reply with /no reason)",
    },
    "toast_rejected_with": {"zh": "已拒绝：{reason}", "en": "Rejected: {reason}"},
    "toast_confirm": {"zh": "请再点一次确认，或返回", "en": "Tap again to confirm, or go back"},
    "toast_publishing": {"zh": "发布中…", "en": "Publishing…"},
    "toast_retrying": {"zh": "重试中…", "en": "Retrying…"},
    "toast_scheduled": {"zh": "已定时：{when}", "en": "Scheduled: {when}"},
    "toast_unscheduled": {"zh": "已取消定时，回到待审核", "en": "Unscheduled, back to pending review"},
    "toast_rejected": {"zh": "已拒绝（需要附理由请用 /no 回复）", "en": "Rejected (reply with /no to give a reason)"},
    "toast_unbanned": {"zh": "已解除封禁，已通知投稿人", "en": "Unbanned; the submitter has been notified"},
    "toast_not_banned": {"zh": "这个投稿人现在没有被封禁", "en": "This submitter isn't banned now"},
    "purge_done": {"zh": "已删除 TA 在审核群的 {n} 条稿件", "en": "Deleted their {n} submission(s) from the review group"},
    "purge_partial": {
        "zh": "已删除 {n} 条稿件；{failed} 条删除失败（机器人可能没有删除消息的权限），可以再试一次",
        "en": "Deleted {n} submission(s); {failed} couldn't be deleted (the bot may lack the delete-messages right). "
              "You can try again",
    },
    "purge_nothing": {"zh": "TA 在审核群里没有可删除的稿件", "en": "They have nothing left to delete in the review group"},
    "toast_already_banned": {"zh": "这个投稿人已经被封禁了", "en": "This submitter is already banned"},
    "toast_banned": {
        "zh": "已封禁，并拒绝 {n} 条未处理来稿",
        "en": "Banned; {n} open submission(s) rejected",
    },
    "publish_failed": {"zh": "发布失败：{error}", "en": "Failed to publish: {error}"},
    "publish_postponed": {
        "zh": "⏳ Telegram 正在限流，已自动改为 <b>{when}</b> 发布",
        "en": "⏳ Telegram is rate-limiting the bot; publishing was moved to <b>{when}</b>",
    },
    "time_past": {"zh": "这个时间已经过去了", "en": "That time has already passed"},
    "reject_published": {
        "zh": '这条投稿已发布，无法拒绝',
        "en": "This submission is already published and can't be rejected",
    },
    "reject_rejected": {
        "zh": '这条投稿已经被拒绝过了',
        "en": 'This submission was already rejected',
    },
    "reject_publishing": {
        "zh": '这条投稿正在发布中',
        "en": 'This submission is being published right now',
    },
    "reject_other": {
        "zh": '这条投稿当前状态无法拒绝',
        "en": "This submission can't be rejected in its current state",
    },
    "ban_default_reason": {"zh": "投稿人已被封禁", "en": "The submitter was banned"},

    # ---------- 审核：等待回复的提示（点按钮后“请回复本消息……”） ----------
    "prompt_time": {
        "zh": '{who} 请<b>回复本消息</b>输入发布时间：\n<code>20:30</code> · <code>10-20 09:00</code> · <code>2026-10-20 09:00</code> · <code>+90m</code> · <code>+2h</code>\n发送 /cancel 放弃。',
        "en": '{who} please <b>reply to this message</b> with a publish time:\n<code>20:30</code> · <code>10-20 09:00</code> · <code>2026-10-20 09:00</code> · <code>+90m</code> · <code>+2h</code>\nSend /cancel to give up.',
    },
    "prompt_edit": {
        "zh": '{who} 请<b>回复本消息</b>发送修改后的正文或说明文字，格式原样保留。上面是当前内容，可以复制后修改。\n发送 /cancel 放弃。',
        "en": '{who} please <b>reply to this message</b> with the new text or caption; formatting is kept. '
              'The current content is above, copy it and change it.\nSend /cancel to give up.',
    },
    "prompt_reason": {
        "zh": '{who} 请<b>回复本消息</b>写拒绝理由，发送后立即拒绝，理由会发给投稿人。\n发送 /cancel 放弃。',
        "en": '{who} please <b>reply to this message</b> with the reason. The submission is rejected as soon as you '
              'send it, and the reason goes to the submitter.\nSend /cancel to give up.',
    },
    "prompt_madd": {
        "zh": '{who} 请<b>回复本消息</b>发送要添加的图片或视频，可以一次发一组（相册）。一条投稿最多 10 个。\n发送 /cancel 放弃。',
        "en": '{who} please <b>reply to this message</b> with the photos or videos to add; an album works too. '
              'At most 10 per submission.\nSend /cancel to give up.',
    },
    "prompt_mrep": {
        "zh": '{who} 请<b>回复本消息</b>发送一张图片或一个视频，换掉第 {n} 个（说明文字保留）。\n发送 /cancel 放弃。',
        "en": '{who} please <b>reply to this message</b> with one photo or video to replace no. {n} '
              '(its caption is kept).\nSend /cancel to give up.',
    },
    "prompt_cancelled": {"zh": "已取消。", "en": "Cancelled."},
    "prompt_none": {"zh": "没有等你回复的操作。", "en": "Nothing is waiting for your reply."},
    "prompt_text_needed": {"zh": "请发送文字。", "en": "Please send text."},
    "custom_time_bad": {
        "zh": "看不懂这个时间 🤔 例如 <code>20:30</code>、<code>10-20 09:00</code>、<code>+2h</code>",
        "en": "I can't read that time 🤔 Try <code>20:30</code>, <code>10-20 09:00</code> or <code>+2h</code>",
    },
    "custom_time_done": {
        "zh": '⏰ 将于 <b>{when}</b> 发布。',
        "en": '⏰ Will be published <b>{when}</b>.',
    },

    # ---------- 审核：命令 ----------
    "review_help": {
        "zh": '🛠 <b>审核群命令</b>\n/stats 发送最新审核统计\n/queue 定时发布队列\n/active [天数] 投稿人活跃度排行（默认 30 天）\n/user &lt;用户ID&gt; 查看某位投稿人\n\n<b>处理投稿</b>（控制消息上的 ✏️ 修改 按钮和 /edit 作用相同；命令要回复投稿的预览或控制消息使用）\n/edit 新内容 —— 替换正文或说明文字，格式原样保留\n/edit —— 不带内容：把当前文字（含格式）发出来，方便复制后修改\n/msg 内容 —— 发消息给投稿人（以“审核员”身份），投稿人也用 /msg 回复\n/no [理由] —— 拒绝，理由会发给投稿人\n/ban [理由] —— 封禁投稿人，并自动拒绝其所有未处理来稿\n/cancel —— 放弃正在等你回复的操作（点了 修改、自定义理由 等按钮后）\n\n<b>按用户处理</b>\n/ban &lt;用户ID&gt; [理由] · /unban &lt;用户ID&gt;',
        "en": "🛠 <b>Review group commands</b>\n/stats post the latest review summary\n/queue scheduled posts\n/active [days] contributor ranking (default 30 days)\n/user &lt;user ID&gt; show one contributor\n\n<b>Handling a submission</b> (the ✏️ Edit button does the same as /edit; reply to the submission's preview or control message to use a command)\n/edit new content — replace the text or caption, keeping formatting\n/edit — on its own: show the current text with formatting so you can copy it\n/msg message — message the submitter (shown as “Reviewer”); they answer with /msg too\n/no [reason] — reject; the reason is sent to the submitter\n/ban [reason] — ban the submitter and reject all their open submissions\n/cancel — drop what's waiting for your reply (after tapping Edit, Custom reason and so on)\n\n<b>By user</b>\n/ban &lt;user ID&gt; [reason] · /unban &lt;user ID&gt;",
    },
    "no_permission": {"zh": "⛔ 你没有审核权限", "en": "⛔ You don't have reviewer permission"},
    "reply_to_submission": {
        "zh": "请回复投稿的预览或控制消息。",
        "en": "Please reply to a submission's preview or control message.",
    },
    "usage_user": {
        "zh": "用法：/user &lt;用户ID&gt;（控制消息里投稿人名字后面的数字）",
        "en": "Usage: /user &lt;user ID&gt; (the number after the submitter's name in the control message)",
    },
    "usage_no": {
        "zh": '用法：回复投稿的预览或控制消息，发送 /no [理由]',
        "en": "Usage: reply to a submission's preview or control message with /no [reason]",
    },
    "usage_edit": {
        "zh": '用法：回复投稿的预览或控制消息，发送 /edit 新内容',
        "en": "Usage: reply to a submission's preview or control message with /edit new content",
    },
    "usage_ban": {
        "zh": '用法：回复投稿发送 /ban [理由]，或 /ban &lt;用户ID&gt; [理由]',
        "en": 'Usage: reply to a submission with /ban [reason], or /ban &lt;user ID&gt; [reason]',
    },
    "usage_unban": {
        "zh": "用法：/unban &lt;用户ID&gt;，或回复该用户的投稿",
        "en": "Usage: /unban &lt;user ID&gt;, or reply to one of their submissions",
    },
    "rejected_reply": {
        "zh": '❌ 已拒绝',
        "en": '❌ Rejected',
    },
    "admin_echo_hint": {
        "zh": "↑ 这是当前内容。复制、修改后，回复这条投稿发送 <code>/edit 新内容</code>。",
        "en": "↑ This is the current content. Copy and change it, then reply to the submission with "
              "<code>/edit new content</code>.",
    },
    "admin_edited": {
        "zh": '✏️ 已修改，新的预览已发出，发布时将使用修改后的内容。',
        "en": '✏️ Edited. A new preview has been posted, and the new version will be published.',
    },
    "banned_reply": {"zh": "🚫 已封禁 {link} <code>{uid}</code>", "en": "🚫 Banned {link} <code>{uid}</code>"},
    "banned_reply_rejected": {
        "zh": '\n已自动拒绝其 {n} 条未处理来稿',
        "en": '\nAlso rejected their {n} open submission(s)',
    },
    "not_banned": {"zh": "用户 <code>{uid}</code> 没有被封禁。", "en": "User <code>{uid}</code> is not banned."},
    "unbanned_reply": {"zh": "✅ 已解除封禁 <code>{uid}</code>。", "en": "✅ Unbanned <code>{uid}</code>."},

    # ---------- 沟通（/msg） ----------
    "msg_from_reviewer": {"zh": "💬 审核员：", "en": "💬 Reviewer:"},
    "msg_from_submitter": {"zh": "💬 投稿人：", "en": "💬 Submitter:"},
    "msg_sent_to_user": {"zh": "✅ 已发送给投稿人", "en": "✅ Sent to the submitter"},
    "msg_sent_to_review": {"zh": "✅ 已发送给审核员", "en": "✅ Sent to the reviewers"},
    "msg_usage_admin": {
        "zh": "用法：回复投稿的预览或控制消息，发送 <code>/msg 内容</code>",
        "en": "Usage: reply to a submission's preview or control message with "
              "<code>/msg message</code>",
    },
    "msg_usage_user": {
        "zh": "请<b>回复</b>审核员的消息或你的投稿，发送 <code>/msg 内容</code>。",
        "en": "Please <b>reply</b> to the reviewer's message or your submission with <code>/msg message</code>.",
    },
    "msg_empty": {"zh": "请在 /msg 后面写上要说的话。", "en": "Please write your message after /msg."},
    "msg_not_submitted": {
        "zh": "这条投稿还没有提交审核，暂时不能沟通。",
        "en": "This submission hasn't been sent for review yet, so there's nobody to talk to.",
    },
    "msg_closed": {
        "zh": "这条投稿的审核已结束超过 {days} 天，沟通已关闭。",
        "en": "The review of this submission ended more than {days} day(s) ago, so messaging is closed.",
    },
    "msg_undelivered": {
        "zh": "⚠️ 没能送达投稿人（可能已屏蔽机器人）：{error}",
        "en": "⚠️ Couldn't reach the submitter (they may have blocked the bot): {error}",
    },
    "msg_failed": {"zh": "⚠️ 发送失败：{error}", "en": "⚠️ Failed to send: {error}"},
    "msg_hint_user": {
        "zh": "要回复审核员，请回复这条消息并以 <code>/msg</code> 开头，例如 <code>/msg 好的，我马上补充</code>。",
        "en": "To answer the reviewer, reply to their message starting with <code>/msg</code>, e.g. "
              "<code>/msg OK, I'll add it</code>.",
    },
    "msg_hint_admin": {
        "zh": "要回复投稿人，请回复这条消息并以 <code>/msg</code> 开头。",
        "en": "To answer the submitter, reply to this message starting with <code>/msg</code>.",
    },
    "ctrl_msgs": {"zh": "💬 沟通 {n} 条", "en": "💬 Messages: {n}"},
    "ctrl_spam_keyword": {"zh": "⚠️ 疑似垃圾：含关键词「{word}」", "en": "⚠️ Possible spam: contains “{word}”"},
    "ctrl_spam_links": {"zh": "⚠️ 疑似垃圾：{n} 个链接（上限 {max}）", "en": "⚠️ Possible spam: {n} links (limit {max})"},

    # ---------- 统计 ----------
    "stats": {
        "zh": "接受 {accepted} 拒绝 {rejected} 待审核 {pending}\n"
              "通过率: {pass_rate:.2f}% 审核率: {review_rate:.2f}%\n"
              "#审核统计 [更新于 {time}]",
        "en": "Accepted {accepted} Rejected {rejected} Pending {pending}\n"
              "Approval rate: {pass_rate:.2f}% Review rate: {review_rate:.2f}%\n"
              "#review_stats [updated {time}]",
    },
    "activity_none": {"zh": "近 {days} 天没有投稿。", "en": "No submissions in the last {days} days."},
    "activity_head": {
        "zh": "📊 <b>投稿人活跃度</b>（近 {days} 天 · {people} 人 · {total} 条）",
        "en": "📊 <b>Contributor activity</b> (last {days} days · {people} people · {total} submissions)",
    },
    "activity_anon": {"zh": " · 匿名 {n}", "en": " · anonymous {n}"},
    "activity_line": {
        "zh": "    投稿 {total} · 通过 {approved} ({rate}){anon} · 活跃 {days} 天 · 最近 {last}",
        "en": "    submitted {total} · approved {approved} ({rate}){anon} · active {days} day(s) · last {last}",
    },
    "me_head": {"zh": "📈 <b>你的投稿统计</b>", "en": "📈 <b>Your submissions</b>"},
    "no_records_self": {"zh": "还没有投稿记录。", "en": "You haven't submitted anything yet."},
    "no_records_admin": {"zh": "用户 <code>{uid}</code> 没有投稿记录。", "en": "User <code>{uid}</code> has no submissions."},
    "user_banned_line": {"zh": "\n🚫 已封禁 {when}（{by}）", "en": "\n🚫 Banned {when} ({by})"},
    "user_summary": {
        "zh": "总投稿 {total} · 已发布 {published} · 待发布 {scheduled} · 待审核 {pending} · 未通过 {rejected}\n"
              "通过率 {rate} · 匿名 {anonymous}\n"
              "首次 {first} · 最近 {last}",
        "en": "Total {total} · published {published} · scheduled {scheduled} · pending {pending} · rejected {rejected}\n"
              "Approval rate {rate} · anonymous {anonymous}\n"
              "First {first} · last {last}",
    },
    "queue_view": {"zh": '查看', "en": 'view'},
    "queue_empty": {"zh": "没有待发布的定时投稿。", "en": "No scheduled posts."},
    "queue_head": {"zh": "⏰ <b>定时发布队列</b>", "en": "⏰ <b>Scheduled posts</b>"},
}

# 命令菜单（/ 后面弹出的列表），按语言注册
PRIVATE_COMMANDS = {
    "zh": [("start", "开始投稿"), ("edit", "修改投稿（回复你的投稿）新内容"), ("msg", "给审核员留言（回复消息）内容"), ("me", "我的投稿统计"), ("help", "使用说明")],
    "en": [("start", "Start submitting"), ("edit", "Edit a submission (reply to it) new content"),
           ("msg", "Message the reviewers (reply) text"), ("me", "My submission stats"), ("help", "How to use")],
}
REVIEW_COMMANDS = {
    "zh": [("stats", "审核统计"), ("queue", "定时发布队列"), ("active", "投稿人活跃度"),
           ("edit", "修改稿件（回复投稿）新内容"), ("msg", "给投稿人发消息（回复投稿）内容"),
           ("no", "拒绝投稿（回复投稿）[理由]"),
           ("ban", "封禁投稿人并拒绝其来稿 [理由]"), ("unban", "解除封禁"), ("user", "查看投稿人"),
           ("cancel", "放弃正在等你回复的操作"), ("help", "命令说明")],
    "en": [("stats", "Review summary"), ("queue", "Scheduled posts"), ("active", "Contributor activity"),
           ("edit", "Edit a submission (reply to it) new content"), ("msg", "Message the submitter (reply) text"),
           ("no", "Reject a submission (reply to it) [reason]"),
           ("ban", "Ban the submitter and reject their posts [reason]"), ("unban", "Lift a ban"),
           ("user", "Show a contributor"), ("cancel", "Drop what's waiting for your reply"), ("help", "Command help")],
}
