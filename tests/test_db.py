"""数据库升级（bot/db.py 的 MIGRATIONS / DROPPED_COLUMNS）的单元测试。
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
        assert {"msg_count", "spam_flags"} <= cols, cols  # 其他升级照常进行
        asyncio.run(upgrade(path))  # 再启动一次：列已经没了，不报错


def test_new_database_has_no_topic_columns():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "new.db")
        asyncio.run(upgrade(path))
        assert not {c for _, c in DROPPED_COLUMNS} & columns(path)


if __name__ == "__main__":
    tests = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for fn in tests:
        fn()
        print("PASS ", fn.__name__)
    print(f"\n{len(tests)}/{len(tests)} passed")
