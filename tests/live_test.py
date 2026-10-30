"""Run the real bot process (python -m bot) against a mock Telegram Bot API HTTP server.

用法（项目根目录下）：python tests/live_test.py

不需要真实的 token 和网络：启动一个模拟 Telegram Bot API 服务器，用 TELEGRAM_API_URL
指向它，运行真实的 `python -m bot` 进程，走完投稿 / 相册 / 剧透 / 静音 / 定时 / 提醒 / /no / /ban 全流程。
约 1 分钟（要等定时发布和每分钟一次的提醒真正触发）。
"""
import asyncio
import json
import re
import os
import sys
import tempfile
import time

from aiohttp import web

PROJECT = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
USER, REVIEW, CHANNEL, ADMIN = 42, -1001, -1002, 7
LINKED = -8000  # 发布频道的关联群组（评论区）
CTRL = "新投稿"  # 控制消息标题（不再显示投稿编号；测试按顺序取紧接着的那一条）
T0 = time.time()

updates: list[dict] = []
new_update = asyncio.Event()
log: list[dict] = []  # {"method", "params", "result"}
mid = [100]
uid = [0]
results = []


def now() -> int:
    return int(time.time())


def chat(cid):
    return {"id": cid, "type": "private" if cid > 0 else ("channel" if cid == CHANNEL else "supergroup")}


MOCK = {# 限流注入："方法名:chat_id" → 依次返回的 retry_after 秒数列表，每次调用消耗一个
        "flood": {},
        # 失败注入："方法名:chat_id" → 依次返回的错误描述列表（HTTP 400），每次调用消耗一个
        "fail": {},
        # 审核群管理员（getChatMember 返回 creator），其他人返回普通成员
        "admins": {7}}
markups: dict = {}  # (chat_id, message_id) → 当前按钮：和 Telegram 一样，按钮没变时编辑会报 “message is not modified”


def make_msg(chat_id):
    mid[0] += 1
    return {"message_id": mid[0], "date": now(), "chat": chat(int(chat_id))}


async def handle(request: web.Request):
    method = request.match_info["method"]
    params = {}
    if request.content_type in ("multipart/form-data", "application/x-www-form-urlencoded"):
        for k, v in (await request.post()).items():
            if isinstance(v, str) and v[:1] in "[{":
                try:
                    v = json.loads(v)
                except ValueError:
                    pass
            params[k] = v
    elif request.can_read_body:
        params = await request.json()

    m = method.lower()
    flood = MOCK["flood"].get(f"{method}:{params.get('chat_id')}")
    if flood:
        retry_after = flood.pop(0)
        log.append({"method": method, "params": params, "result": None, "error": True, "flood": retry_after,
                    "t": time.time()})
        return web.json_response({"ok": False, "error_code": 429, "parameters": {"retry_after": retry_after},
                                  "description": f"Too Many Requests: retry after {retry_after}"}, status=429)
    fail = MOCK["fail"].get(f"{method}:{params.get('chat_id')}")
    if fail:
        description = fail.pop(0)
        log.append({"method": method, "params": params, "result": None, "error": True, "t": time.time()})
        return web.json_response({"ok": False, "error_code": 400, "description": description}, status=400)
    if m == "getupdates":
        offset = int(params.get("offset") or 0)
        timeout = min(float(params.get("timeout") or 0), 2)
        updates[:] = [u for u in updates if u["update_id"] >= offset]
        if not updates:
            new_update.clear()
            try:
                await asyncio.wait_for(new_update.wait(), timeout)
            except asyncio.TimeoutError:
                pass
        return web.json_response({"ok": True, "result": updates[:]})

    if m.startswith("send") and str(params.get("chat_id")) == str(CHANNEL) and "custom_emoji" in json.dumps(
            [params.get("entities"), params.get("caption_entities"), params.get("media")]):
        log.append({"method": method, "params": params, "result": None, "error": True, "t": time.time()})
        return web.json_response({"ok": False, "error_code": 400,
                                  "description": "Bad Request: custom emoji can't be used in this chat"}, status=400)

    if m in ("editmessagereplymarkup", "editmessagetext"):
        key = (str(params.get("chat_id")), str(params.get("message_id")))
        if m == "editmessagereplymarkup" and markups.get(key) == params.get("reply_markup"):
            log.append({"method": method, "params": params, "result": None, "error": True, "t": time.time()})
            return web.json_response({"ok": False, "error_code": 400, "description":
                                      "Bad Request: message is not modified: specified new message content and reply "
                                      "markup are exactly the same as a current content and reply markup of the message"},
                                     status=400)
        markups[key] = params.get("reply_markup")

    if m == "getme":
        result = {"id": 1, "is_bot": True, "first_name": "TestBot", "username": "test_bot"}
    elif m == "getchat":
        info = {"accent_color_id": 0, "max_reaction_count": 11,
                "accepted_gift_types": {k: False for k in ("unlimited_gifts", "limited_gifts", "unique_gifts",
                                                           "premium_subscription", "gifts_from_channels")}}
        if str(params.get("chat_id")) == str(REVIEW):
            result = {**chat(REVIEW), "title": "Review", **info}
        else:
            result = {**chat(CHANNEL), "title": "Test Channel", "username": "testchan", "linked_chat_id": LINKED, **info}
    elif m == "getchatmember":
        uid_ = int(params["user_id"])
        member_user = {"id": uid_, "is_bot": False, "first_name": f"U{uid_}"}
        result = ({"status": "creator", "user": member_user, "is_anonymous": False} if uid_ in MOCK["admins"]
                  else {"status": "member", "user": member_user})
    elif m == "copymessages":
        result = [{"message_id": make_msg(params["chat_id"])["message_id"]} for _ in params["message_ids"]]
    elif m == "sendmediagroup":
        result = [make_msg(params["chat_id"]) for _ in params["media"]]
    elif m.startswith("send"):
        result = make_msg(params["chat_id"])
    else:
        result = True
    log.append({"method": method, "params": params, "result": result, "t": time.time()})
    return web.json_response({"ok": True, "result": result})


def push(**kw):
    uid[0] += 1
    updates.append({"update_id": uid[0], **kw})
    new_update.set()


BOB = 43


def pm(text=None, who=USER, **extra):
    name = "Alice" if who == USER else "Bob"
    d = {"message_id": 10 + uid[0], "date": now(), "chat": chat(who),
         "from": {"id": who, "is_bot": False, "first_name": name, "username": name.lower(),
                  "language_code": "zh-hans" if who == USER else "en"}}
    if text is not None:
        d["text"] = text
        if text.startswith("/"):
            d["entities"] = [{"type": "bot_command", "offset": 0, "length": len(text.split()[0])}]
    d.update(extra)
    push(message=d)
    return d["message_id"]


def pm_edit(message_id, text, entities=None, who=USER):
    """投稿人用 Telegram 自带的“编辑”修改了之前发的消息。"""
    name = "Alice" if who == USER else "Bob"
    push(edited_message={"message_id": message_id, "date": now() - 5, "edit_date": now(), "chat": chat(who),
                         "from": {"id": who, "is_bot": False, "first_name": name, "username": name.lower()},
                         "text": text, "entities": entities or []})


def gm(text, reply_to=None, entities=None):
    d = {"message_id": 5000 + uid[0], "date": now(), "chat": chat(REVIEW),
         "from": {"id": ADMIN, "is_bot": False, "first_name": "Admin"}, "text": text}
    if text.startswith("/"):
        d["entities"] = [{"type": "bot_command", "offset": 0, "length": len(text.split()[0])}] + (entities or [])
    if reply_to:
        d["reply_to_message"] = {"message_id": reply_to, "date": now(), "chat": chat(REVIEW),
                                 "from": {"id": 1, "is_bot": True, "first_name": "TestBot"}}
    push(message=d)


def cb(data, chat_id, from_id, message_id=999):
    push(callback_query={"id": str(uid[0]), "chat_instance": "x", "data": data,
                         "from": {"id": from_id, "is_bot": False, "first_name": "Admin" if from_id == ADMIN else "Alice"},
                         "message": {"message_id": message_id, "date": now(), "chat": chat(chat_id)}})


async def wait_for(pred, timeout=10.0, since=None):
    start = since if since is not None else len(log)
    deadline = time.time() + timeout
    while time.time() < deadline:
        for e in log[start:]:
            if pred(e):
                return e
        await asyncio.sleep(0.05)
    return None


def check(name, ok, detail=""):
    results.append((name, bool(ok)))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  — {detail}" if detail else ""), flush=True)


def is_send(e, method, chat_id, contains=None):
    return (not e.get("error") and e["method"].lower() == method.lower() and str(e["params"].get("chat_id")) == str(chat_id)
            and (contains is None or contains in json.dumps(e["params"], ensure_ascii=False)))


def styles(e):
    kb = (e["params"].get("reply_markup") or {}).get("inline_keyboard", [])
    return {b["text"]: b.get("style") for row in kb for b in row}


def buttons(e):
    """按钮文字 → callback_data。"""
    kb = (e["params"].get("reply_markup") or {}).get("inline_keyboard", [])
    return {b["text"]: b["callback_data"] for row in kb for b in row}


PROMPTS = ("请选择投稿方式", "How would you like")  # “选择投稿方式”提示：中文客户端 / 其他客户端


async def submit(text, sid, who=USER):
    """投稿人发一条文字投稿并选“署名”。返回审核群里控制消息的 sendMessage 记录（没进审核群时为 None）。
    其他测试文件共用；本文件的场景里另有一个带额外检查的同名局部函数。"""
    n = len(log); pm(text, who=who)
    await wait_for(lambda e: any(is_send(e, "sendMessage", who, p) for p in PROMPTS), since=n)
    n = len(log); cb(f"u:sign:{sid}", who, who)
    return await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, CTRL), since=n)


async def scenario():
    e = await wait_for(lambda e: e["method"] == "setMyCommands" and e["params"].get("language_code") == "en", 15, since=0)
    check("bot started; command menus registered per language", e and any(
        c.get("command") == "start" and c.get("description") == "Start submitting" for c in e["params"]["commands"]))

    # 0. 只响应私聊和审核群：其他群里不回复，并自动退出
    OTHER, ADDED, KICKED = -5000, -6000, -7000

    def other_msg(chat_id, text):
        lt_msg = {"message_id": 30000 + uid[0], "date": now(), "chat": chat(chat_id), "text": text,
                  "from": {"id": USER, "is_bot": False, "first_name": "Alice"}}
        if text.startswith("/"):
            lt_msg["entities"] = [{"type": "bot_command", "offset": 0, "length": len(text.split()[0])}]
        push(message=lt_msg)

    def member_update(chat_id, old, new):
        bot_user = {"id": 1, "is_bot": True, "first_name": "TestBot"}
        push(my_chat_member={"chat": chat(chat_id), "date": now(),
                             "from": {"id": USER, "is_bot": False, "first_name": "Alice"},
                             "old_chat_member": {"status": old, "user": bot_user},
                             "new_chat_member": {"status": new, "user": bot_user,
                                                 **({"until_date": 0} if new == "kicked" else {})}})

    n = len(log)
    for text in ("/start", "/stats", "/help", "hello bot"):
        other_msg(OTHER, text)
    left = await wait_for(lambda e: e["method"] == "leaveChat" and str(e["params"]["chat_id"]) == str(OTHER), since=n)
    await asyncio.sleep(0.5)
    replies = [e for e in log[n:] if e["method"].lower().startswith("send") and str(e["params"].get("chat_id")) == str(OTHER)]
    check("unknown group: no replies at all, bot leaves", left and not replies, [e["method"] for e in replies])
    n = len(log); member_update(ADDED, "left", "member")
    e = await wait_for(lambda e: e["method"] == "leaveChat" and str(e["params"]["chat_id"]) == str(ADDED), since=n)
    check("added to another group → leaves immediately", e)
    n = len(log); member_update(KICKED, "member", "kicked")
    e = await wait_for(lambda e: e["method"] == "leaveChat" and str(e["params"]["chat_id"]) == str(KICKED), timeout=1, since=n)
    check("removed from a group → does not try to leave again", not e)
    n = len(log); member_update(LINKED, "left", "member"); other_msg(LINKED, "/start"); other_msg(LINKED, "/stats")
    await asyncio.sleep(1.5)
    acted = [e["method"] for e in log[n:] if str(e["params"].get("chat_id")) == str(LINKED)]
    check("channel's linked discussion group is whitelisted: bot stays, still silent", not acted, acted)

    # 1. 文字投稿 → 选匿名
    n = len(log); pm("Hello <b>world</b>", entities=[{"type": "bold", "offset": 0, "length": 5}])
    e = await wait_for(lambda e: is_send(e, "sendMessage", USER, "请选择投稿方式"), since=n)
    check("text submission prompt with colored buttons", e and styles(e).get("👤 署名投稿") == "primary", styles(e) if e else "")
    n = len(log); cb("u:anon:1", USER, USER)
    ctrl1 = await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, CTRL), since=n)
    s = styles(ctrl1) if ctrl1 else {}
    check("control msg colors", s.get("✅ 立即发布") == "success" and s.get("❌ 拒绝") == "danger"
          and s.get("⏰ 定时发布") == "primary" and s.get("🔔 静音：关") is None, s)

    # 2. 相册 → 署名 → 剧透 + 静音 → 立即发布
    n = len(log)
    for i in range(2):
        pm(None, media_group_id="g1", caption="album" if i == 0 else None,
           photo=[{"file_id": f"p{i}", "file_unique_id": f"u{i}", "width": 1, "height": 1}])
    e = await wait_for(lambda e: is_send(e, "sendMessage", USER, "2 张图片"), since=n)
    check("album of 2 merged into one submission", e)
    n = len(log); cb("u:sign:2", USER, USER)
    e = await wait_for(lambda e: is_send(e, "sendMediaGroup", REVIEW), since=n)
    check("album preview in review group", e and len(e["params"]["media"]) == 2)
    ctrl2 = await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, CTRL), since=n)
    n = len(log); cb("r:spoiler:2:0", REVIEW, ADMIN); cb("r:silent:2:0", REVIEW, ADMIN)
    e = await wait_for(lambda e: e["method"] == "editMessageText" and "静音发送：🔕 开" in e["params"].get("text", "")
                       and "剧透遮罩：🙈 开" in e["params"].get("text", ""), since=n)
    check("spoiler + silent toggled", e)
    n = len(log); cb("r:pub_ok:2:0", REVIEW, ADMIN)
    e = await wait_for(lambda e: is_send(e, "sendMediaGroup", CHANNEL), since=n)
    ok = e and all(m.get("has_spoiler") for m in e["params"]["media"]) and str(e["params"].get("disable_notification")).lower() == "true"
    check("published to channel with spoiler + silent (real HTTP payload)", ok,
          e and {"has_spoiler": [m.get("has_spoiler") for m in e["params"]["media"]],
                 "disable_notification": e["params"].get("disable_notification")})
    e = await wait_for(lambda e: is_send(e, "sendMessage", USER, "已发布到频道"), since=n)
    check("user notified with post link", e and "t.me/testchan/" in e["params"]["text"])

    # 3. 自定义定时 +1m → 后台调度器真实发布
    n = len(log); cb("r:custom:1:0", REVIEW, ADMIN)
    prompt = await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, "发布时间"), since=n)
    check("custom time prompt (ForceReply)", prompt and "force_reply" in json.dumps(prompt["params"]))
    n = len(log); gm("+1m", reply_to=prompt["result"]["message_id"])
    e = await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, "将于"), since=n)
    check("schedule +1m accepted", e)
    scheduled_at = time.time()

    # 4. 再来两条投稿：一条 /no 带理由，一条用于 /ban 自动拒绝
    async def submit(text, sid, who=USER):
        n = len(log); pm(text, who=who)
        prompt_marker = "请选择投稿方式" if who == USER else "How would you like to submit it"
        e = await wait_for(lambda e: is_send(e, "sendMessage", who, prompt_marker), since=n)
        if who == BOB:
            check("English client → English prompt and buttons",
                  e and styles(e).get("👤 Signed") == "primary" and styles(e).get("🕶 Anonymous") == "primary",
                  e and styles(e))
        n = len(log); cb(f"u:sign:{sid}", who, who)
        return await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, CTRL), since=n)

    ctrl3 = await submit("post three", 3)
    ctrl4 = await submit("post four", 4, who=BOB)
    n = len(log); gm("/no 内容重复", reply_to=ctrl3["result"]["message_id"])
    e = await wait_for(lambda e: is_send(e, "sendMessage", USER, "理由：内容重复"), since=n)
    check("/no with reason → user notified", e)
    n = len(log); gm("/ban 发广告", reply_to=ctrl4["result"]["message_id"])
    e = await wait_for(lambda e: is_send(e, "sendMessage", BOB, "You are not allowed to submit"), since=n)
    check("/ban → Bob notified in English, his 1 pending submission auto-rejected", e and "1 pending" in e["params"]["text"],
          e and e["params"]["text"].replace("\n", " | "))
    ban_reply = await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, "已封禁"), since=n)
    check("review group stays Chinese for the same ban", ban_reply and "已自动拒绝" in ban_reply["params"]["text"])
    n = len(log); pm("still here", who=BOB)
    e = await wait_for(lambda e: is_send(e, "sendMessage", BOB, "Reason: 发广告"), since=n)
    check("banned user blocked with reason (English)", e)

    # 5. 格式保真：超链接 / 粗体 / 引用 / 日期时间 / 自定义 emoji / emoji 代理对 / 链接预览设置
    def u16(t):
        return len(t.encode("utf-16-le")) // 2

    def norm(es):
        return sorted((json.dumps(e, sort_keys=True, ensure_ascii=False) for e in es or []))

    rich = "🔥 热门 文章链接 ✨\n引用一段话\n时间 2026-10-19"
    rich_ents = [
        {"type": "custom_emoji", "offset": 0, "length": 2, "custom_emoji_id": "5368324170671202286"},
        {"type": "bold", "offset": 3, "length": 2},
        {"type": "text_link", "offset": 6, "length": 4, "url": "https://example.com/a?b=1&c=<2>"},
        {"type": "blockquote", "offset": 14, "length": 5},
        {"type": "date_time", "offset": 23, "length": 10, "unix_time": 1792368000, "date_time_format": "wD"},
    ]
    assert rich.encode("utf-16-le")[6 * 2:10 * 2].decode("utf-16-le") == "文章链接"
    n = len(log); pm(rich, entities=rich_ents, link_preview_options={"is_disabled": True})
    await wait_for(lambda e: is_send(e, "sendMessage", USER, "请选择投稿方式"), since=n)
    n = len(log); cb("u:sign:5", USER, USER)
    pv = await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, "热门"), since=n)
    check("review preview keeps all entities incl. custom emoji + date_time",
          pv and set(norm(rich_ents)) <= set(norm(pv["params"].get("entities"))) and "parse_mode" not in pv["params"],
          pv and pv["params"].get("entities"))
    n = len(log); cb("r:pub_ok:5:0", REVIEW, ADMIN)
    rejected = await wait_for(lambda e: e.get("error") and str(e["params"].get("chat_id")) == str(CHANNEL), since=n)
    pub = await wait_for(lambda e: is_send(e, "sendMessage", CHANNEL, "热门"), since=n)
    sig_text = "via Alice"  # 落款：斜体的 via + 不带链接的名字
    want_text = rich + "\n\n" + sig_text
    want_ents = [e for e in rich_ents if e["type"] != "custom_emoji"] + [
        {"type": "italic", "offset": u16(rich + "\n\n"), "length": 3}]
    check("channel rejected custom emoji → bot retried with plain emoji", rejected and pub)
    check("channel post: exact text + entities (UTF-16 offsets) + signature link",
          pub and pub["params"]["text"] == want_text and norm(pub["params"].get("entities")) == norm(want_ents),
          pub and {"text_ok": pub["params"]["text"] == want_text, "got": pub["params"].get("entities")})
    check("link preview setting preserved", pub and (pub["params"].get("link_preview_options") or {}).get("is_disabled"))

    # 6. 图片：说明在上方 + 用户自带剧透 → /edit 改说明（新格式）→ 发布
    n = len(log)
    pm(None, caption="旧说明 old", caption_entities=[{"type": "italic", "offset": 0, "length": 3}],
       show_caption_above_media=True, has_media_spoiler=True,
       photo=[{"file_id": "pX", "file_unique_id": "uX", "width": 1, "height": 1}])
    await wait_for(lambda e: is_send(e, "sendMessage", USER, "请选择投稿方式"), since=n)
    n = len(log); cb("u:anon:6", USER, USER)
    ctrl6 = await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, CTRL), since=n)
    check("user's own media spoiler kept as default", ctrl6 and "剧透遮罩：🙈 开" in ctrl6["params"]["text"])

    edit_cmd = "/edit 🎉 新的说明，详见官网"
    # 管理员消息里的格式：自定义 emoji、粗体“说明”、“官网”超链接
    edit_ents = [{"type": "custom_emoji", "offset": 6, "length": 2, "custom_emoji_id": "777"},
                 {"type": "bold", "offset": 11, "length": 2},
                 {"type": "text_link", "offset": 16, "length": 2, "url": "https://example.org"}]
    assert edit_cmd.encode("utf-16-le")[16 * 2:18 * 2].decode("utf-16-le") == "官网"
    n = len(log); gm(edit_cmd, reply_to=ctrl6["result"]["message_id"], entities=edit_ents)
    ok_msg = await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, "已修改"), since=n)
    new_pv = await wait_for(lambda e: is_send(e, "sendPhoto", REVIEW), since=n)
    body = "🎉 新的说明，详见官网"
    shifted = [{**e, "offset": e["offset"] - 6} for e in edit_ents]
    anon_via = {"type": "italic", "offset": u16(body + "\n\n"), "length": 3}
    check("/edit → confirmation + new preview replying to control msg",
          ok_msg and new_pv and new_pv["params"]["caption"] == body + "\n\nvia 匿名"
          and norm(new_pv["params"].get("caption_entities")) == norm(shifted + [anon_via])
          and new_pv["params"].get("reply_parameters", {}).get("message_id") == ctrl6["result"]["message_id"],
          new_pv and {"caption": new_pv["params"].get("caption"), "ents": new_pv["params"].get("caption_entities")})
    e = await wait_for(lambda e: e["method"] == "editMessageText" and "✏️ 已修改（Admin" in e["params"].get("text", ""),
                       since=n)
    check("control msg shows edited marker", e)

    n = len(log); gm("/edit", reply_to=ctrl6["result"]["message_id"])
    e = await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, "详见官网") and "\n\n" not in e["params"]["text"],
                       since=n)
    check("/edit without text echoes current caption with formatting", e and norm(e["params"].get("entities")) == norm(shifted))

    n = len(log); cb("r:pub_ok:6:0", REVIEW, ADMIN)
    pub6 = await wait_for(lambda e: is_send(e, "sendPhoto", CHANNEL), since=n)
    p6 = pub6["params"] if pub6 else {}
    check("edited photo published: new caption, formatting, caption-above, spoiler",
          p6.get("caption") == body + "\n\nvia 匿名"
          and norm(p6.get("caption_entities")) == norm([x for x in shifted if x["type"] != "custom_emoji"] + [anon_via])
          and str(p6.get("show_caption_above_media")).lower() == "true" and str(p6.get("has_spoiler")).lower() == "true",
          p6)

    n = len(log); gm("/no 3 想按编号拒绝")
    e = await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, "用法"), since=n)
    check("/no with a number but no reply → usage, number not used as a submission ID", e)
    n = len(log); gm("/edit 改不了")
    e = await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, "用法"), since=n)
    check("/edit without reply or id → usage", e)
    n = len(log); gm("/edit 已经发布了", reply_to=ctrl2["result"]["message_id"])
    e = await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, "不能修改"), since=n)
    check("/edit on published submission refused", e)

    # 7. 投稿人自己修改
    n = len(log); src = pm("原始内容 v1")
    prompt7 = await wait_for(lambda e: is_send(e, "sendMessage", USER, "请选择投稿方式"), since=n)
    # 7a. 草稿阶段用 Telegram 自带编辑
    n = len(log); pm_edit(src, "草稿改过 v1b")
    e = await wait_for(lambda e: is_send(e, "sendMessage", USER, "确认无误后"), since=n)
    check("native edit while draft → updated, no review preview yet", e and not await wait_for(
        lambda e: is_send(e, "sendMessage", REVIEW, "v1b"), timeout=0.5, since=n))
    n = len(log); cb("u:sign:7", USER, USER)
    ctrl7 = await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, CTRL), since=n)
    pv = await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, "草稿改过 v1b"), since=n)
    check("submitted draft carries the edited text", ctrl7 and pv)

    # 7b. 待审核阶段用 Telegram 自带编辑，带超链接
    n = len(log); pm_edit(src, "修改后 v2 看这里", [{"type": "text_link", "offset": 7, "length": 3, "url": "https://ex.am/p"}])
    ok = await wait_for(lambda e: is_send(e, "sendMessage", USER, "投稿已更新"), since=n)
    pv = await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, "修改后 v2"), since=n)
    mark = await wait_for(lambda e: e["method"] == "editMessageText" and "✏️ 已修改（投稿人 Alice" in e["params"].get("text", ""), since=n)
    check("native edit while pending → user told, admins get new preview + marker",
          ok and pv and mark and pv["params"]["reply_parameters"]["message_id"] == ctrl7["result"]["message_id"]
          and {"type": "text_link", "offset": 7, "length": 3, "url": "https://ex.am/p"} in pv["params"]["entities"])

    # 7c. /edit 回复机器人的提示消息
    n = len(log); pm("/edit v3 新版本", reply_to_message={"message_id": prompt7["result"]["message_id"], "date": now(),
                                                       "chat": chat(USER), "from": {"id": 1, "is_bot": True, "first_name": "TestBot"}})
    ok = await wait_for(lambda e: is_send(e, "sendMessage", USER, "投稿已更新"), since=n)
    pv = await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, "v3 新版本"), since=n)
    check("/edit replying to bot prompt", ok and pv)

    def reply_to(message_id, by_bot):
        sender = {"id": 1, "is_bot": True, "first_name": "TestBot"} if by_bot else \
            {"id": USER, "is_bot": False, "first_name": "Alice"}
        return {"message_id": message_id, "date": now(), "chat": chat(USER), "from": sender}

    # 7d. 不回复 → 不生效，提示必须回复（即使只有一条可改的投稿）
    n = len(log); pm("/edit 不回复就想改")
    e = await wait_for(lambda e: is_send(e, "sendMessage", USER, "请<b>回复</b>"), since=n)
    changed = await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, "不回复就想改"), timeout=0.5, since=n)
    check("submitter /edit without reply → not applied, asked to reply", e and not changed)
    n = len(log); pm("/edit")
    e = await wait_for(lambda e: is_send(e, "sendMessage", USER, "请<b>回复</b>"), since=n)
    check("submitter /edit alone without reply → asked to reply", e)

    # 7e. 回复自己发的原消息 /edit → 生效；回复后只发 /edit → 返回当前内容
    n = len(log); pm("/edit 2024年总结", reply_to_message=reply_to(src, by_bot=False))
    pv = await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, "2024年总结"), since=n)
    check("/edit replying to own original message works; numbers are just text", pv)
    n = len(log); pm("/edit", reply_to_message=reply_to(src, by_bot=False))
    e = await wait_for(lambda e: is_send(e, "sendMessage", USER, "2024年总结") and "投稿人" not in e["params"]["text"], since=n)
    check("replying with just /edit echoes current content", e)

    # 7f. 发布后再改 → 拒绝
    n = len(log); cb("r:pub_ok:7:0", REVIEW, ADMIN)
    await wait_for(lambda e: is_send(e, "sendMessage", CHANNEL, "2024年总结"), since=n)
    n = len(log); pm_edit(src, "发布后偷偷改")
    e = await wait_for(lambda e: is_send(e, "sendMessage", USER, "已经发布，不能修改"), since=n)
    check("edit after publish refused", e and not await wait_for(
        lambda e: is_send(e, "sendMessage", REVIEW, "偷偷改"), timeout=0.5, since=n))
    n = len(log); pm("/edit 也不行", reply_to_message=reply_to(prompt7["result"]["message_id"], by_bot=True))
    e = await wait_for(lambda e: is_send(e, "sendMessage", USER, "已经发布，不能修改"), since=n)
    check("/edit by reply after publish → refused with reason", e)

    # 7g. 审核员 ↔ 投稿人沟通（/msg）
    n = len(log); src_m = pm("需要沟通的投稿")
    pr = await wait_for(lambda e: is_send(e, "sendMessage", USER, "请选择投稿方式"), since=n)
    n = len(log); cb("u:sign:8", USER, USER)  # 内部编号，只在按钮数据里用
    ctrl_m = await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, CTRL), since=n)

    ask = "/msg 请补充出处 链接"
    n = len(log); gm(ask, reply_to=ctrl_m["result"]["message_id"],
                     entities=[{"type": "text_link", "offset": 11, "length": 2, "url": "https://ex.am/src"}])
    assert ask.encode("utf-16-le")[11 * 2:13 * 2].decode("utf-16-le") == "链接"
    to_user = await wait_for(lambda e: is_send(e, "sendMessage", USER, "审核员"), since=n)
    sent_ok = await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, "已发送给投稿人"), since=n)
    label = "💬 审核员："
    want = [{"type": "bold", "offset": 0, "length": u16(label)},
            {"type": "text_link", "offset": u16(label + "\n请补充出处 "), "length": 2, "url": "https://ex.am/src"}]
    check("reviewer /msg → submitter gets it as “审核员”, formatting kept, under their submission",
          to_user and sent_ok and to_user["params"]["text"] == label + "\n请补充出处 链接"
          and norm(to_user["params"].get("entities")) == norm(want)
          and to_user["params"]["reply_parameters"]["message_id"] == pr["result"]["message_id"]
          and "Admin" not in to_user["params"]["text"], to_user and to_user["params"])
    cnt = await wait_for(lambda e: e["method"] == "editMessageText" and "💬 沟通 1 条" in e["params"].get("text", ""), since=n)
    check("control message shows message count", cnt)

    n = len(log); gm("/msg 没回复")
    e = await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, "用法"), since=n)
    check("reviewer /msg without reply → usage", e)

    relay_id = to_user["result"]["message_id"]
    n = len(log); pm("直接回复不带命令", reply_to_message=reply_to(relay_id, by_bot=True))
    hint = await wait_for(lambda e: is_send(e, "sendMessage", USER, "<code>/msg</code>"), since=n)
    new_sub = await wait_for(lambda e: is_send(e, "sendMessage", USER, "请选择投稿方式"), timeout=0.5, since=n)
    leaked = await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, "直接回复不带命令"), timeout=0.5, since=n)
    check("submitter plain reply to reviewer → hint to use /msg; not relayed, not a new submission",
          hint and not new_sub and not leaked)

    n = len(log); pm("/msg 出处是官网", reply_to_message=reply_to(relay_id, by_bot=True))
    to_rev = await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, "出处是官网"), since=n)
    ok = await wait_for(lambda e: is_send(e, "sendMessage", USER, "已发送给审核员"), since=n)
    check("submitter /msg by reply → reviewers get it under the control message",
          to_rev and ok and to_rev["params"]["text"].startswith("💬 投稿人：")
          and to_rev["params"]["reply_parameters"]["message_id"] == ctrl_m["result"]["message_id"])

    n = len(log); gm("直接回复投稿人", reply_to=to_rev["result"]["message_id"])
    e = await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, "要回复投稿人"), since=n)
    check("reviewer plain reply to a relayed message → hint", e)
    n = len(log); gm("/msg 收到，谢谢", reply_to=to_rev["result"]["message_id"])
    e = await wait_for(lambda e: is_send(e, "sendMessage", USER, "收到，谢谢"), since=n)
    check("reviewer /msg replying to the relayed message reaches the submitter", e)

    n = len(log); pm("/msg 不回复")
    e = await wait_for(lambda e: is_send(e, "sendMessage", USER, "请<b>回复</b>审核员的消息"), since=n)
    check("submitter /msg without reply → asked to reply", e)
    n = len(log); pm("/msg 回复原投稿也行", reply_to_message=reply_to(src_m, by_bot=False))
    e = await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, "回复原投稿也行"), since=n)
    check("submitter /msg replying to their own submission also works", e)

    # 8. 等后台任务：定时发布（调度器每 15 秒检查）+ 每分钟统计提醒
    print("… waiting for scheduler + reminder loops (up to ~100s)", flush=True)
    e = await wait_for(lambda e: is_send(e, "sendMessage", CHANNEL, "Hello"), timeout=100, since=0)
    check("scheduler published the scheduled post on time", e,
          e and f"{e['t'] - scheduled_at:.0f}s after scheduling (+1m target, 15s tick)")
    e = await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, "#审核统计"), timeout=70, since=0)
    check("reminder loop posted stats on its own", e, e and e["params"]["text"].replace("\n", " | "))


def unexpected_errors(lines, allowed=()):
    """机器人日志里的错误。allowed：预期中的错误（ERROR 行里含这些文字），这条错误和它后面的堆栈都不算。"""
    bad, expected = [], False
    for line in lines:
        if " ERROR " in line or " CRITICAL " in line:
            expected = any(a in line for a in allowed)
            if not expected:
                bad.append(line)
        elif line[:1].isdigit():  # 新的一条日志（以时间开头）：之前那条错误的堆栈结束了
            expected = False
        elif "Traceback" in line and not expected:
            bad.append(line)
    return bad


async def main(scenario_fn=None, extra_env=None, allowed_errors=()):
    scenario_fn = scenario_fn or scenario
    app = web.Application()
    app.router.add_route("*", "/bot{token}/{method}", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]

    env = {**os.environ, "BOT_TOKEN": "123:TEST", "CHANNEL_ID": str(CHANNEL), "REVIEW_CHAT_ID": str(REVIEW),
           "TELEGRAM_API_URL": f"http://127.0.0.1:{port}", "DB_PATH": os.path.join(tempfile.mkdtemp(), "bot.db"),
           "ALBUM_DELAY": "0.5", "REMINDER_INTERVAL_MINUTES": "1", "REMINDER_ONLY_WHEN_PENDING": "false",
           "REMINDER_QUIET_HOURS": "", "TZ": "Asia/Shanghai", "PYTHONUNBUFFERED": "1", **(extra_env or {})}
    proc = await asyncio.create_subprocess_exec(sys.executable, "-m", "bot", cwd=PROJECT, env=env,
                                                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    bot_log = []

    async def pump():
        async for line in proc.stdout:
            bot_log.append(line.decode().rstrip())

    pump_task = asyncio.create_task(pump())
    try:
        await scenario_fn()
    except Exception as e:  # 场景中断时仍然输出机器人日志，方便排查
        import traceback
        traceback.print_exc()
        check(f"scenario aborted: {e!r}", False)
    finally:
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), 10)
        except asyncio.TimeoutError:
            proc.kill()
        await pump_task
        await runner.cleanup()

    shown = [e["params"].get(k) for e in log for k in ("text", "caption", "name")
             if isinstance(e["params"].get(k), str) and str(e["params"].get("chat_id")) != str(CHANNEL)]
    numbered = [x for x in shown if re.search(r"#\d", x)]
    check("no submission numbers shown to submitters or reviewers", not numbered, numbered[:3])

    bad = unexpected_errors(bot_log, allowed_errors)
    check("no errors in bot process log", not bad, "\n".join(bad[:10]))
    print("\n--- bot log (last 12 lines) ---")
    print("\n".join(l for l in bot_log if "Update id=" not in l)[-6000:])
    print(f"\n{sum(ok for _, ok in results)}/{len(results)} passed in {time.time() - T0:.0f}s")
    sys.exit(0 if all(ok for _, ok in results) else 1)


if __name__ == "__main__":
    asyncio.run(main())
