"""封禁后删除审核群里的稿件（core.purge_review_messages）：真实数据库 + 记录请求的假机器人。
用法：python tests/test_purge.py
"""
import asyncio
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aiogram.exceptions import TelegramBadRequest  # noqa: E402

REVIEW = -1001
TEXT = [{"type": "text", "text": "hi", "entities": []}]


TOO_OLD = "Bad Request: message can't be deleted"  # Telegram 对超过 48 小时的消息这样回答
NO_RIGHTS = "Bad Request: not enough rights to delete a message"  # 下次可能成功的错误


class FakeBot:
    """记录删除请求，行为和 Telegram 一样：
    - delete_messages：有一条删不掉（undeletable 太旧 / broken 其他原因）整批失败；找不到的跳过
    - delete_message：太旧报 can't be deleted，其他原因报 not enough rights，已经不在了报 not found"""
    def __init__(self, undeletable=(), broken=()):
        self.calls, self.undeletable, self.broken, self.deleted = [], set(undeletable), set(broken), set()

    async def delete_messages(self, chat_id, message_ids):
        self.calls.append((chat_id, list(message_ids)))
        if (self.undeletable | self.broken) & set(message_ids):
            raise TelegramBadRequest(method=None, message=TOO_OLD)
        self.deleted |= set(message_ids)
        return True

    async def delete_message(self, chat_id, message_id):
        self.calls.append((chat_id, message_id))
        if message_id in self.undeletable:
            raise TelegramBadRequest(method=None, message=TOO_OLD)
        if message_id in self.broken:
            raise TelegramBadRequest(method=None, message=NO_RIGHTS)
        if message_id in self.deleted:
            raise TelegramBadRequest(method=None, message="Bad Request: message to delete not found")
        self.deleted.add(message_id)
        return True


def _with_core(check, bot=None):
    async def run():
        os.environ.update(BOT_TOKEN="1:x", CHANNEL_ID="@c", REVIEW_CHAT_ID=str(REVIEW))
        from bot.config import load_settings
        from bot.core import Core
        from bot.db import DB
        db = DB(os.path.join(tempfile.mkdtemp(), "t.db"))
        await db.connect()
        try:
            await check(Core(bot or FakeBot(), db, load_settings()), db)
        finally:
            await db.close()
    asyncio.run(run())


async def _sub(db, user_id, status, control, linked=()):
    """一条进过审核群的投稿：控制按钮消息 control，其他属于它的审核群消息 linked（预览、改稿预览、转达）。"""
    sid = await db.create_draft(user_id, TEXT)
    await db.update(sid, status=status, review_msg_id=control)
    await db.link_review_messages(sid, [*linked, control])
    return sid


def test_purge_deletes_everything_of_the_banned_user_only():
    async def check(core, db):
        s1 = await _sub(db, 42, "published", 101, linked=(100, 102, 103))  # 预览、改稿预览、转达
        s2 = await _sub(db, 42, "rejected", 200)
        await db.add_prompt(REVIEW, 201, "edit", s2, 7, [202])  # 等待回复的提示 + 一起删的消息
        await db.add_prompt(-999, 9, "edit", s2, 7, [])  # 别的聊天里的提示：不算
        other = await _sub(db, 43, "pending", 300, linked=(299,))

        # 没被封禁：什么都不删
        assert (await core.purge_review_messages(42)).key == "toast_not_banned"
        assert core.bot.calls == []

        await db.ban(42, None, "Admin")
        res = await core.purge_review_messages(42)
        assert (res.key, res.params) == ("purge_done", {"n": 2, "note": ""}), res
        assert core.bot.calls == [(REVIEW, [100, 101, 102, 103, 200, 201, 202])], core.bot.calls
        # 投稿记录保留，只是不再指向审核群里的消息
        a, b = await db.get(s1), await db.get(s2)
        assert (a.status, a.review_msg_id, b.status, b.review_msg_id) == ("published", None, "rejected", None)
        assert await db.review_traces(REVIEW, 42) == {}
        assert await db.get_prompt(REVIEW, 201) is None and await db.get_prompt(-999, 9) is not None
        assert await db.sid_by_review_message(100) is None
        # 别人的不动
        assert await db.review_traces(REVIEW, 43) == {other: [299, 300]}
        assert (await db.get(other)).review_msg_id == 300

        # 再点一次：没有可删的
        assert (await core.purge_review_messages(42)).key == "purge_nothing"
        assert len(core.bot.calls) == 1
    _with_core(check)


def test_batches_keep_each_submission_together_and_respect_the_100_limit():
    async def check(core, db):
        await db.ban(42, None, "Admin")
        for k in range(3):  # 3 条投稿，每条 60 条消息：拼不进同一批
            await _sub(db, 42, "rejected", 1000 * (k + 1), linked=range(1000 * (k + 1) + 1, 1000 * (k + 1) + 60))
        big = await _sub(db, 42, "rejected", 9000, linked=range(9001, 9150))  # 一条投稿 150 条消息：分两次删
        small = await _sub(db, 42, "rejected", 9500, linked=(9501,))
        res = await core.purge_review_messages(42)
        sizes = [len(ids) for _, ids in core.bot.calls]
        assert (res.key, res.params) == ("purge_done", {"n": 5, "note": ""}), res
        assert sizes == [60, 60, 60, 100, 50, 2], sizes
        assert all(len(ids) <= 100 for _, ids in core.bot.calls)
        assert (await db.get(big)).review_msg_id is None and (await db.get(small)).review_msg_id is None
    _with_core(check)


def test_failed_batch_is_kept_for_retry():
    """一条投稿里有消息因为别的原因（权限等）删不掉：这条投稿逐条删，能删的删掉，剩下的留着重试；别的投稿照常删。"""
    async def check(core, db):
        await db.ban(42, None, "Admin")
        s1 = await _sub(db, 42, "rejected", 100, linked=range(101, 160))
        s2 = await _sub(db, 42, "published", 200, linked=range(201, 260))
        res = await core.purge_review_messages(42)
        assert (res.key, res.params) == ("purge_partial", {"n": 1, "failed": 1, "note": ""}), res
        assert (await db.get(s2)).review_msg_id is None
        assert core.bot.deleted == set(range(100, 160)) - {130} | set(range(200, 260)), "能删的都删了"
        assert await db.review_traces(REVIEW, 42) == {s1: [100, 130]}  # 控制按钮消息编号还记着，重试时会找不到，算删掉
        core.bot.broken = set()
        res = await core.purge_review_messages(42)  # 重试：只剩删不掉的那条和控制按钮消息
        assert (res.key, res.params) == ("purge_done", {"n": 1, "note": ""}), res
        assert await db.review_traces(REVIEW, 42) == {}
    _with_core(check, FakeBot(broken={130}))


def test_one_bad_message_does_not_block_the_whole_batch():
    """好几条投稿拼成一批：其中一条有删不掉的消息，其他投稿逐条投稿地删掉，不受连累。"""
    async def check(core, db):
        await db.ban(42, None, "Admin")
        good = [await _sub(db, 42, "rejected", 100 * k, linked=(100 * k + 1,)) for k in range(1, 4)]
        bad = await _sub(db, 42, "rejected", 900, linked=(901,))
        res = await core.purge_review_messages(42)
        assert (res.key, res.params) == ("purge_partial", {"n": 3, "failed": 1, "note": ""}), res
        assert [(await db.get(s)).review_msg_id for s in good] == [None] * 3
        assert list(await db.review_traces(REVIEW, 42)) == [bad]
        assert 900 in core.bot.deleted and 901 not in core.bot.deleted
    _with_core(check, FakeBot(broken={901}))


def test_too_old_messages_are_forgotten_not_retried():
    """超过 48 小时的消息 Telegram 不允许删：能删的删掉，太旧的不再记录，提示里说有几条要手动删；再点就没有可删的了。"""
    async def check(core, db):
        await db.ban(42, None, "Admin")
        old = await _sub(db, 42, "rejected", 100, linked=(101, 102))
        new = await _sub(db, 42, "published", 200, linked=(201,))
        res = await core.purge_review_messages(42)
        assert res.key == "purge_done" and res.params["n"] == 2 and res.params["note"].params == {"n": 2}, res
        assert core.bot.deleted == {102, 200, 201}
        assert await db.review_traces(REVIEW, 42) == {}
        assert (await db.get(old)).review_msg_id is None and (await db.get(new)).review_msg_id is None
        assert res.text("zh") == ("已删除 TA 在审核群的 2 条稿件。其中 2 条消息超过 48 小时，"
                                  "Telegram 不允许机器人删除，需要管理员手动删除")
        assert (await core.purge_review_messages(42)).key == "purge_nothing"
    _with_core(check, FakeBot(undeletable={100, 101}))


def test_purge_texts_in_both_languages():
    from bot.errors import notice
    assert notice("purge_partial", n=1, failed=2, note="").text("zh").startswith("已删除 1 条稿件；2 条删除失败")
    assert "couldn't be deleted" in notice("purge_partial", n=1, failed=2, note="").text("en")
    assert "older than 48 hours" in notice("purge_done", n=1, note=notice("purge_too_old", n=3)).text("en")


if __name__ == "__main__":
    tests = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for fn in tests:
        fn()
        print("PASS ", fn.__name__)
    print(f"\n{len(tests)}/{len(tests)} passed")
