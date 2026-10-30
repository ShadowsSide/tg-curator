"""修改稿件媒体的单元测试：bot/media.py 的规则、core 的 change_media / merge_draft / remove_own_media、媒体相关按钮。
用法：python tests/test_media.py
"""
import asyncio
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bot import media  # noqa: E402

BOLD = [{"type": "bold", "offset": 0, "length": 2}]


def photo(fid, text="", **kw):
    return {"type": "photo", "file_id": fid, "text": text, "entities": BOLD if text else [], "msg_id": 100, **kw}


def video(fid, **kw):
    return {"type": "video", "file_id": fid, "text": "", "entities": [], "msg_id": 101, **kw}


def text_item(t="你好世界"):
    return {"type": "text", "text": t, "entities": BOLD, "link_preview": {"is_disabled": False}, "msg_id": 50}


def err_key(result):
    items, err = result
    assert items is None and err is not None, result
    return err.key


def test_add_to_album_drops_command_caption():
    items, err = media.add([photo("a", "说明", above=True)], [photo("b", "/add 命令本身", spoiler=True), video("c")])
    assert err is None
    assert [it["file_id"] for it in items] == ["a", "b", "c"]
    assert items[0]["text"] == "说明" and items[0]["above"] is True  # 原来的说明不动
    assert items[1]["text"] == "" and items[1]["entities"] == [] and items[1]["spoiler"] is True  # 新的不带说明，保留剧透


def test_add_to_text_submission_turns_text_into_caption():
    items, err = media.add([text_item()], [photo("b", "/add"), video("c")])
    assert err is None and [it["type"] for it in items] == ["photo", "video"]
    first = items[0]
    assert first["text"] == "你好世界" and first["entities"] == BOLD  # 文字和格式原样
    assert first["msg_id"] == 50  # 原文字消息的编号：投稿人“编辑”那条文字 = 改说明
    assert "link_preview" not in first  # 链接预览不再有
    assert items[1]["text"] == ""


def test_add_limits():
    assert err_key(media.add([photo("a")], [{"type": "document", "file_id": "d"}])) == "media_only_photo_video"
    assert err_key(media.add([photo("a")], [])) == "media_only_photo_video"
    assert err_key(media.add([{"type": "animation", "file_id": "g", "text": ""}], [photo("b")])) == "media_mixed_types"
    assert err_key(media.add([{"type": "document", "file_id": "d", "text": ""}], [photo("b")])) == "media_mixed_types"
    nine = [photo(str(i)) for i in range(9)]
    assert media.add(nine, [photo("x")])[1] is None  # 正好 10 个
    assert err_key(media.add(nine, [photo("x"), photo("y")])) == "media_too_many"
    assert err_key(media.add([text_item()], [photo(str(i)) for i in range(11)])) == "media_too_many"


def test_replace_keeps_caption_and_position():
    old = [photo("a"), photo("b", "说明", above=True), video("c")]
    items, err = media.replace(old, 2, [video("NEW", spoiler=True)])
    assert err is None
    assert [it["file_id"] for it in items] == ["a", "NEW", "c"] and items[1]["type"] == "video"
    assert items[1]["text"] == "说明" and items[1]["entities"] == BOLD and items[1]["above"] is True
    assert items[1]["spoiler"] is True
    assert old[1]["file_id"] == "b"  # 不修改传进来的列表


def test_replace_limits():
    assert err_key(media.replace([text_item()], 1, [photo("x")])) == "media_none"
    assert err_key(media.replace([photo("a")], 2, [photo("x")])) == "media_bad_index"
    assert err_key(media.replace([photo("a")], 0, [photo("x")])) == "media_bad_index"
    assert err_key(media.replace([photo("a"), photo("b")], 1, [photo("x"), photo("y")])) == "media_replace_one"
    assert err_key(media.replace([photo("a")], 1, [{"type": "voice", "file_id": "v"}])) == "media_only_photo_video"


def test_remove_moves_caption_to_the_next_item():
    items, err = media.remove([photo("a", "说明", above=True), photo("b"), photo("c")], 1)
    assert err is None and [it["file_id"] for it in items] == ["b", "c"]
    assert items[0]["text"] == "说明" and items[0]["entities"] == BOLD and items[0]["above"] is True
    # 剩下的已经有说明：不再挪
    items, _ = media.remove([photo("a", "一"), photo("b", "二")], 1)
    assert [it["text"] for it in items] == ["二"]
    # 删的不是带说明的那一项：说明不动
    items, _ = media.remove([photo("a", "说明"), photo("b")], 2)
    assert [it["file_id"] for it in items] == ["a"] and items[0]["text"] == "说明"


def test_remove_limits():
    assert err_key(media.remove([photo("a")], 1)) == "media_last_one"
    assert err_key(media.remove([text_item()], 1)) == "media_none"
    assert err_key(media.remove([photo("a"), photo("b")], 3)) == "media_bad_index"


def _with_core(items, check, status="draft"):
    """真实的数据库 + Core（不连 Telegram：草稿状态下改稿不发任何请求），运行 check(core, db, sid)。
    无论 check 是否失败都关闭数据库：否则 aiosqlite 的线程会让进程卡住，断言失败变成超时。"""
    async def run():
        os.environ.update(BOT_TOKEN="1:x", CHANNEL_ID="@c", REVIEW_CHAT_ID="-1001")
        from bot.config import load_settings
        from bot.core import Core
        from bot.db import DB
        db = DB(os.path.join(tempfile.mkdtemp(), "t.db"))
        await db.connect()
        try:
            sid = await db.create_draft(42, items)
            if status != "draft":
                await db.update(sid, status=status)
            await check(Core(None, db, load_settings()), db, sid)
        finally:
            await db.close()
    asyncio.run(run())


def test_core_change_media_on_a_draft():
    async def check(core, db, sid):
        # 投稿人加图：保留新消息的 msg_id（以后“编辑”那条消息能找到这条投稿）
        assert await core.change_media(sid, "add", 0, [photo("p", msg_id=777)], "投稿人", ("draft", "pending"), True) is None
        sub = await db.get(sid)
        assert [it["type"] for it in sub.items] == ["photo"] and sub.items[0]["text"] == "你好世界"
        assert sub.original_items == [text_item()] and sub.edited_by == "投稿人"  # 原稿另存
        # 审核员加图：不记 msg_id（审核群的消息编号）
        assert await core.change_media(sid, "add", 0, [photo("q", msg_id=888)], "Admin", ("draft",), False) is None
        assert "msg_id" not in (await db.get(sid)).items[1]
        assert await db.find_by_user_message(42, 888) is None
        # 替换、删除
        assert await core.change_media(sid, "replace", 2, [video("v")], "Admin", ("draft",), False) is None
        assert await core.change_media(sid, "remove", 1, [], "Admin", ("draft",), False) is None
        sub = await db.get(sid)
        assert [it["file_id"] for it in sub.items] == ["v"] and sub.items[0]["text"] == "你好世界"  # 说明跟过来了
        # 规则不允许时返回提示，稿件不变
        err = await core.change_media(sid, "remove", 1, [], "Admin", ("draft",), False)
        assert err.key == "media_last_one" and (await db.get(sid)).items == sub.items
    _with_core([text_item()], check)


def test_core_change_media_respects_state():
    for status in ("published", "rejected", "scheduled"):
        async def check(core, db, sid, status=status):
            err = await core.change_media(sid, "add", 0, [photo("b")], "Admin", ("pending",), False)
            assert err and err.key == f"not_editable_{status}", (status, err)
            assert [it["file_id"] for it in (await db.get(sid)).items] == ["a"]
        _with_core([photo("a")], check, status)


def test_core_native_text_edit_after_conversion_updates_caption():
    async def check(core, db, sid):
        await core.change_media(sid, "add", 0, [photo("p", msg_id=777)], "投稿人", ("draft",), True)
        # 投稿人用 Telegram 的“编辑”改了原来那条文字消息（msg_id 50）
        assert await db.find_by_user_message(42, 50) == (sid, 0)
        new = {"type": "text", "text": "改过的说明", "entities": [], "msg_id": 50}
        assert await core.replace_item(sid, 0, new, "投稿人", ("draft",)) is None
        it = (await db.get(sid)).items[0]
        assert it["type"] == "photo" and it["file_id"] == "p" and it["text"] == "改过的说明"
    _with_core([text_item()], check)


def test_core_merge_draft_into_earlier_submission():
    """投稿人回复旧投稿发的图片：“加到这条投稿”后图片进了旧投稿，新草稿作废；
    以后“编辑”那条图片消息，找到的是旧投稿而不是作废的草稿。"""
    async def check(core, db, sid):
        draft = await db.create_draft(42, [photo("n", msg_id=900)])
        assert (await core.merge_draft(draft, 42, "投稿人")).key == "invalid_sub"  # 没有 merge_to
        await db.update(draft, merge_to=sid)
        assert (await core.merge_draft(draft, 43, "投稿人")).key == "invalid_sub"  # 不是自己的
        assert await core.merge_draft(draft, 42, "投稿人") is None
        assert [it["file_id"] for it in (await db.get(sid)).items] == ["a", "n"]
        assert (await db.get(draft)).status == "cancelled"
        assert await db.find_by_user_message(42, 900) == (sid, 1)
        assert (await core.merge_draft(draft, 42, "投稿人")).key == "already_handled"  # 连点两下
    _with_core([photo("a")], check)


def test_core_merge_respects_target_state_and_limit():
    async def check(core, db, sid):
        await db.update(sid, status="scheduled")  # 审核已经开始：投稿人不能再改
        draft = await db.create_draft(42, [photo("n")])
        await db.update(draft, merge_to=sid)
        assert (await core.merge_draft(draft, 42, "投稿人")).key == "not_editable_scheduled"
        assert (await db.get(draft)).status == "draft"  # 没加进去，草稿保留，还能作为新投稿
    _with_core([photo("a")], check)


def test_core_submitter_removes_own_media():
    async def check(core, db, sid):
        assert (await core.remove_own_media(sid, 43, 1, "x")).key == "invalid_sub"
        assert await core.remove_own_media(sid, 42, 1, "投稿人") is None
        assert [it["file_id"] for it in (await db.get(sid)).items] == ["b"]
        assert (await core.remove_own_media(sid, 42, 1, "投稿人")).key == "media_last_one"
    _with_core([photo("a"), photo("b")], check)


def test_keyboards():
    from bot.db import Submission
    from bot.keyboards import ReviewCB, UserCB, UserMediaCB, control_kb, media_kb, user_kb, user_media_kb

    def sub(items, status="pending", **kw):
        return Submission(id=5, user_id=42, items=items, anonymous=False, spoiler=False, silent=False, status=status,
                          decision=None, created_at=0, submitted_at=0, reviewed_at=0, reviewer_id=None,
                          reviewer_name=None, scheduled_at=None, published_at=None, user_msg_id=None,
                          review_msg_id=None, channel_msg_id=None, reject_reason=None, original_items=None,
                          edited_by=None, edited_at=None, msg_count=0, error=None, **kw)

    def acts(kb, cb=ReviewCB):
        """按钮 → (动作, v)。投稿人的按钮混着两类（UserCB 没有 v，记为 0）。"""
        def one(data):
            c = (UserMediaCB if data.startswith("um:") else UserCB if data.startswith("u:") else cb).unpack(data)
            return c.a, getattr(c, "v", 0)
        return [] if kb is None else [one(b.callback_data) for row in kb.inline_keyboard for b in row]

    assert acts(media_kb(sub([text_item()]), "zh")) == [("madd", 0), ("back", 0)]
    assert acts(media_kb(sub([photo("a")]), "zh")) == [("madd", 0), ("mrep", 1), ("back", 0)]  # 只剩一个不能删
    assert acts(media_kb(sub([photo("a"), video("b")]), "zh")) == [
        ("madd", 0), ("mrep", 1), ("mrep", 2), ("mrm", 1), ("mrm", 2), ("back", 0)]
    assert ("madd", 0) not in acts(media_kb(sub([photo(str(i)) for i in range(10)]), "zh"))  # 满 10 个不能再加

    # 投稿人被封禁：控制消息最后一行是“解除封禁”和“删除 TA 的稿件”，不论投稿状态；没被封禁就没有
    for status in ("pending", "scheduled", "failed", "published", "rejected"):
        assert acts(control_kb(sub([photo("a")], status), "zh", banned=True))[-2:] == [("unban", 0), ("purge", 0)], status
        assert not {("unban", 0), ("purge", 0)} & set(acts(control_kb(sub([photo("a")], status), "zh"))), status
    assert control_kb(sub([photo("a")], "published"), "zh") is None  # 已发布、没被封禁：没有按钮

    two = [photo("a"), photo("b")]
    assert acts(user_kb(sub([photo("a")], "draft"), "zh"), UserCB) == [("sign", 0), ("anon", 0), ("cancel", 0)]
    assert acts(user_kb(sub(two, "draft", merge_to=3), "zh"), UserCB) == [
        ("merge", 3), ("sign", 0), ("anon", 0), ("mdel", 0), ("cancel", 0)]
    assert acts(user_kb(sub(two, "pending"), "zh"), UserCB) == [("mdel", 0)]
    assert user_kb(sub([photo("a")], "pending"), "zh") is None  # 只有一个：没什么可删
    assert user_kb(sub(two, "scheduled"), "zh") is None  # 审核开始后不能改
    assert user_kb(sub([photo("a"), {"type": "document", "file_id": "d", "text": ""}], "pending"), "zh") is None
    assert acts(user_media_kb(sub(two), "zh"), UserCB) == [("mrm", 1), ("mrm", 2), ("mback", 0)]


if __name__ == "__main__":
    tests = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for fn in tests:
        fn()
        print("PASS ", fn.__name__)
    print(f"{len(tests)}/{len(tests)} passed")
