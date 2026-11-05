"""并发：两个操作在 await 之间交错时，结果仍然正确。用临时 SQLite 和假的 bot，在关键的 await 之间插入另一个操作。
用法：python tests/test_concurrency.py
"""
import asyncio
import functools
import os
import sys
import tempfile
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import bot.core.editing as editing  # noqa: E402
from bot.config import load_settings  # noqa: E402
from bot.core import Core  # noqa: E402
from bot.core.review import ReviewMixin  # noqa: E402
from bot.db import DB  # noqa: E402

TEXT = [{"type": "text", "text": "a", "entities": []}]


class Interleave:
    """包住 DB：第 n 次调用 method 返回之后，先执行一次 hook（模拟这时另一个操作插进来）。"""

    def __init__(self, db, method, hook, n=1):
        self._db, self._method, self._hook, self._left = db, method, hook, n

    def __getattr__(self, name):
        attr = getattr(self._db, name)
        if name != self._method:
            return attr

        async def wrapped(*a, **kw):
            result = await attr(*a, **kw)
            self._left -= 1
            if self._left == 0:
                await self._hook()
            return result
        return wrapped


async def noop(*_, **__):
    return None


def with_db(fn):
    @functools.wraps(fn)
    def run():
        async def go(path):
            db = DB(path)
            await db.connect()
            try:
                await fn(db)
            finally:
                await db.close()
        with tempfile.TemporaryDirectory() as d:
            asyncio.run(go(os.path.join(d, "c.db")))
    return run


def review_core(db):
    core = SimpleNamespace(db=db, refresh_control=noop)
    if hasattr(ReviewMixin, "_toggle"):  # 旧代码没有它（反向验证时）
        core._toggle = functools.partial(ReviewMixin._toggle, core)
    return core


@with_db
async def test_toggle_after_publish_started_is_refused(db):
    """切换剧透 / 静音时刚好有人点了发布：发布已经读过设置，晚到的切换不能写进去，也不能提示“已切换”。"""
    for toggle, field in ((ReviewMixin.toggle_spoiler, "spoiler"), (ReviewMixin.toggle_silent, "silent")):
        sid = await db.create_draft(42, TEXT)
        await db.update(sid, status="pending")

        async def publish_starts():
            assert await db.transition(sid, ("pending",), "publishing")
        got = await toggle(review_core(Interleave(db, "get", publish_starts)), sid)
        assert got.key == "toast_state_locked", (field, got)
        assert getattr(await db.get(sid), field) == 0, field


@with_db
async def test_toggle_while_open_still_works(db):
    sid = await db.create_draft(42, TEXT)
    await db.update(sid, status="scheduled")
    got = await ReviewMixin.toggle_spoiler(review_core(db), sid)
    assert got.key == "toast_spoiler" and got.params["state"].key == "on", got
    assert (await db.get(sid)).spoiler == 1
    got = await ReviewMixin.toggle_spoiler(review_core(db), sid)
    assert got.params["state"].key == "off" and (await db.get(sid)).spoiler == 0, got



class FakeBot:
    """只记下删了哪些消息；发预览由 send_items 的替身负责。"""

    def __init__(self):
        self.deleted = []

    async def delete_messages(self, chat_id, ids):
        self.deleted.extend(ids)


def real_core(db):
    env = {"BOT_TOKEN": "123:abc", "CHANNEL_ID": "@chan", "REVIEW_CHAT_ID": "-1001", "ALBUM_DELAY": "0.1"}
    old = dict(os.environ)
    os.environ.update(env)
    try:
        settings = load_settings()
    finally:
        os.environ.clear()
        os.environ.update(old)
    core = Core(FakeBot(), db, settings)
    for name in ("refresh_control", "send_user_preview", "notify", "refresh_user_kb"):
        setattr(core, name, noop)
    return core


def fake_previews(start=1000):
    """send_items 的替身：每次“发出”一条预览，消息编号递增。"""
    counter = [start]

    async def send_items(*_, **__):
        counter[0] += 1
        return [SimpleNamespace(message_id=counter[0])]
    return send_items


@with_db
async def test_two_edits_keep_only_the_latest_preview(db):
    """审核员 A、B 先后改同一条投稿，两次都保存成功，但 B 先记下自己的修改预览、A 后记：
    审核群里最后要留 B 那份（最新内容），A 那份（已过时）和最初那份修改预览都删掉。"""
    sid = await db.create_draft(42, TEXT)
    await db.update(sid, status="pending", review_msg_id=500, edit_preview=[900])
    core = real_core(db)
    editing.send_items, original = fake_previews(), editing.send_items
    try:
        async def b_edits():  # A 已保存、还没记下预览时，B 改完了整个流程
            await core._save_edit(await db.get(sid), [{**TEXT[0], "text": "B"}], "B", ("pending",),
                                  by_submitter=False)
        core.db = Interleave(db, "link_review_messages", b_edits)
        err = await core._save_edit(await db.get(sid), [{**TEXT[0], "text": "A"}], "A", ("pending",),
                                    by_submitter=False)
    finally:
        editing.send_items = original
    assert err is None, err
    sub = await db.get(sid)
    a_preview, b_preview = 1001, 1002
    assert sub.items[0]["text"] == "B" and sub.edit_preview == [b_preview], (sub.items, sub.edit_preview)
    assert set(core.bot.deleted) == {900, a_preview}, core.bot.deleted


@with_db
async def test_single_edit_replaces_previous_preview(db):
    sid = await db.create_draft(42, TEXT)
    await db.update(sid, status="pending", review_msg_id=500, edit_preview=[900])
    core = real_core(db)
    editing.send_items, original = fake_previews(), editing.send_items
    try:
        assert await core._save_edit(await db.get(sid), [{**TEXT[0], "text": "A"}], "A", ("pending",),
                                     by_submitter=False) is None
    finally:
        editing.send_items = original
    assert (await db.get(sid)).edit_preview == [1001] and core.bot.deleted == [900], core.bot.deleted


def photo(fid, msg_id, text=""):
    return {"type": "photo", "file_id": fid, "text": text, "entities": [], "msg_id": msg_id}


def album_part():
    """相册后到部分的第一条消息：只用到 reply 和发送人的名字。"""
    replies = []

    async def reply(text, **_):
        replies.append(text)
    return SimpleNamespace(reply=reply, from_user=SimpleNamespace(full_name="Alice"), replies=replies)


async def album_target(db, status):
    sid = await db.create_draft(42, [photo("A1", 1), photo("A2", 2)])
    await db.update(sid, status=status, review_msg_id=500 if status == "pending" else None)
    return sid


async def fix_caption(db, sid, status):
    """投稿人用 Telegram 的编辑改了第一张的说明（和真正的改稿一样带版本号保存）。"""
    sub = await db.get(sid)
    assert await db.update_if(sid, (status,), version=sub.version, items=[{**sub.items[0], "text": "改好的说明"},
                                                                          *sub.items[1:]])


@with_db
async def test_late_album_part_keeps_edit_made_meanwhile(db):
    """相册后到的部分并进投稿时，投稿刚被改过（读到的 target 是改之前的）：并进去之后那次修改还在。
    草稿、待审核两种都要。"""
    for status in ("draft", "pending"):
        sid = await album_target(db, status)
        stale = await db.get(sid)
        await fix_caption(db, sid, status)
        core = real_core(db)
        editing.send_items, original = fake_previews(), editing.send_items
        try:
            err = await core._join_album(stale, album_part(), [photo("A3", 3)], "zh")
        finally:
            editing.send_items = original
        assert err is None, (status, err)
        sub = await db.get(sid)
        assert [it["file_id"] for it in sub.items] == ["A1", "A2", "A3"], (status, sub.items)
        assert sub.items[0]["text"] == "改好的说明", (status, sub.items[0])
        assert sub.version == stale.version + 2, (status, sub.version)  # 改稿一次 + 并进去一次


@with_db
async def test_late_album_part_retries_when_edited_during_merge(db):
    """读到投稿之后、写入之前投稿被改了：版本对不上，重新读一次再合并，修改和后到的部分都在。"""
    sid = await album_target(db, "draft")

    async def edit_meanwhile():
        await fix_caption(db, sid, "draft")
    core = real_core(Interleave(db, "get", edit_meanwhile))
    assert await core._join_album(await db.get(sid), album_part(), [photo("A3", 3)], "zh") is None
    sub = await db.get(sid)
    assert [it["file_id"] for it in sub.items] == ["A1", "A2", "A3"] and sub.items[0]["text"] == "改好的说明", sub.items

if __name__ == "__main__":
    tests = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for fn in tests:
        fn()
        print("PASS ", fn.__name__)
    print(f"\n{len(tests)}/{len(tests)} passed")
