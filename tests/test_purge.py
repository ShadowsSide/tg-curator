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


class FakeBot:
    """只记录 delete_messages；fail 里的调用序号（从 0 开始）抛出“没有权限”。"""
    def __init__(self, fail=()):
        self.calls, self.fail = [], set(fail)

    async def delete_messages(self, chat_id, message_ids):
        n = len(self.calls)
        self.calls.append((chat_id, list(message_ids)))
        if n in self.fail:
            raise TelegramBadRequest(method=None, message="Bad Request: message can't be deleted")
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
    """一条进过审核群的投稿：控制消息 control，其他属于它的审核群消息 linked（预览、改稿预览、转达）。"""
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
        assert (res.key, res.params) == ("purge_done", {"n": 2}), res
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
        assert (res.key, res.params) == ("purge_done", {"n": 5}), res
        assert sizes == [60, 60, 60, 100, 50, 2], sizes
        assert all(len(ids) <= 100 for _, ids in core.bot.calls)
        assert (await db.get(big)).review_msg_id is None and (await db.get(small)).review_msg_id is None
    _with_core(check)


def test_failed_batch_is_kept_for_retry():
    async def check(core, db):
        await db.ban(42, None, "Admin")
        s1 = await _sub(db, 42, "rejected", 100, linked=range(101, 160))
        s2 = await _sub(db, 42, "published", 200, linked=range(201, 260))
        res = await core.purge_review_messages(42)  # 第一批（s1）失败，第二批（s2）成功
        assert (res.key, res.params) == ("purge_partial", {"n": 1, "failed": 1}), res
        assert (await db.get(s1)).review_msg_id == 100 and (await db.get(s2)).review_msg_id is None
        assert list(await db.review_traces(REVIEW, 42)) == [s1]
        core.bot.fail = set()
        res = await core.purge_review_messages(42)  # 重试：只删剩下的
        assert (res.key, res.params) == ("purge_done", {"n": 1}), res
        assert core.bot.calls[-1][1] == list(range(100, 160))
    _with_core(check, FakeBot(fail={0}))


def test_purge_texts_in_both_languages():
    from bot.errors import notice
    assert notice("purge_partial", n=1, failed=2).text("zh").startswith("已删除 1 条稿件；2 条删除失败")
    assert "couldn't be deleted" in notice("purge_partial", n=1, failed=2).text("en")


if __name__ == "__main__":
    tests = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for fn in tests:
        fn()
        print("PASS ", fn.__name__)
    print(f"\n{len(tests)}/{len(tests)} passed")
