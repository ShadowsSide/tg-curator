"""数据库的单元测试：旧库升级（MIGRATIONS / DROPPED_COLUMNS）、等待回复的提示、按相册编号找投稿。
用法：python tests/test_db.py
"""
import asyncio
import os
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bot.db import DB, DROPPED_COLUMNS  # noqa: E402

# 话题模式时代的旧库：带话题列，没有后来加的 msg_count、spam_flags
OLD_SCHEMA = """
CREATE TABLE submissions (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, items TEXT NOT NULL,
    anonymous INTEGER NOT NULL DEFAULT 0, spoiler INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'draft',
    decision TEXT, created_at INTEGER NOT NULL, submitted_at INTEGER, reviewed_at INTEGER, reviewer_id INTEGER,
    reviewer_name TEXT, scheduled_at INTEGER, published_at INTEGER, user_msg_id INTEGER, review_msg_id INTEGER,
    channel_msg_id INTEGER, review_topic_id INTEGER, user_topic_id INTEGER, topic_status TEXT, error TEXT
);
INSERT INTO submissions(user_id, items, status, created_at, review_topic_id, user_topic_id, topic_status)
VALUES (42, '[{"type": "text", "text": "hi", "entities": []}]', 'pending', 1, 7001, 7002, 'pending');
"""


def columns(path):
    with sqlite3.connect(path) as conn:
        return {r[1] for r in conn.execute("PRAGMA table_info(submissions)")}


async def upgrade(path):
    db = DB(path)
    try:
        await db.connect()
        return await db.get(1)
    finally:
        await db.close()


def test_old_database_drops_topic_columns_and_keeps_data():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "old.db")
        with sqlite3.connect(path) as conn:
            conn.executescript(OLD_SCHEMA)
        sub = asyncio.run(upgrade(path))
        assert sub.user_id == 42 and sub.status == "pending" and sub.items[0]["text"] == "hi", sub
        cols = columns(path)
        assert not {c for _, c in DROPPED_COLUMNS} & cols, cols
        assert {"msg_count", "spam_flags", "edit_preview", "media_group_id"} <= cols, cols  # 其他升级照常进行
        assert sub.media_group_id is None, sub
        asyncio.run(upgrade(path))  # 再启动一次：列已经没了，不报错


def test_new_database_has_no_topic_columns():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "new.db")
        asyncio.run(upgrade(path))
        assert not {c for _, c in DROPPED_COLUMNS} & columns(path)


def test_prompts_survive_restart():
    """等待回复的提示存在数据库里：重启（重新连接）后还在，完成后删掉。"""
    async def run(path):
        db = DB(path)
        await db.connect()
        await db.add_prompt(-100, 55, "edit", 3, 7, [54])
        await db.close()
        db = DB(path)
        await db.connect()
        try:
            prompt = await db.get_prompt(-100, 55)
            assert (prompt.kind, prompt.sid, prompt.user_id, prompt.cleanup) == ("edit", 3, 7, [54]), prompt
            assert await db.get_prompt(-200, 55) is None  # 同一个消息编号，别的聊天
            assert [p.message_id for p in await db.stale_prompts(prompt.created_at + 1)] == [55]
            assert await db.stale_prompts(prompt.created_at) == []
            await db.delete_prompt(-100, 55)
            assert await db.get_prompt(-100, 55) is None
        finally:
            await db.close()

    with tempfile.TemporaryDirectory() as d:
        asyncio.run(run(os.path.join(d, "p.db")))


def test_find_by_album():
    """相册生成的投稿记下相册编号：只找同一个投稿人、同一个相册、since 之后的，有多条取最新一条。"""
    async def run(path):
        db = DB(path)
        await db.connect()
        try:
            photo = [{"type": "photo", "file_id": "p0"}]
            a = await db.create_draft(42, photo, media_group_id="g1")
            single = await db.create_draft(42, photo)
            await db.create_draft(43, photo, media_group_id="g1")  # 别人的相册碰巧同号
            created = (await db.get(a)).created_at
            assert (await db.find_by_album(42, "g1", created)).id == a
            assert (await db.get(single)).media_group_id is None
            assert await db.find_by_album(42, "g2", created) is None
            assert await db.find_by_album(42, "g1", created + 1) is None  # 太早的不算
            b = await db.create_draft(42, photo, media_group_id="g1")
            assert (await db.find_by_album(42, "g1", created)).id == b
        finally:
            await db.close()

    with tempfile.TemporaryDirectory() as d:
        asyncio.run(run(os.path.join(d, "a.db")))


if __name__ == "__main__":
    tests = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for fn in tests:
        fn()
        print("PASS ", fn.__name__)
    print(f"\n{len(tests)}/{len(tests)} passed")
