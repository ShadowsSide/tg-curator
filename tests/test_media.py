"""修改稿件媒体（bot/media.py：/add、/replace、/remove；core 的 change_media）的单元测试。
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


if __name__ == "__main__":
    tests = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for fn in tests:
        fn()
        print("PASS ", fn.__name__)
    print(f"{len(tests)}/{len(tests)} passed")
