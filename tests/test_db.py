"""数据库的单元测试：新库的建表语句、旧库升级（MIGRATIONS / DROPPED_COLUMNS）、等待回复的提示、按相册编号找投稿。
用法：python tests/test_db.py
"""
import asyncio
import os
import sqlite3
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from types import SimpleNamespace  # noqa: E402
from zoneinfo import ZoneInfo  # noqa: E402

from bot.core.stats import StatsMixin  # noqa: E402
from bot.db import DB, DROPPED_COLUMNS, MIGRATIONS, SCHEMA  # noqa: E402

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
        assert {"msg_count", "spam_flags", "edit_preview", "media_group_id", "version"} <= cols, cols  # 其他升级照常进行
        assert sub.media_group_id is None, sub
        asyncio.run(upgrade(path))  # 再启动一次：列已经没了，不报错


def test_new_database_has_no_topic_columns():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "new.db")
        asyncio.run(upgrade(path))
        assert not {c for _, c in DROPPED_COLUMNS} & columns(path)


def test_create_table_has_every_migrated_column():
    """新库只靠 CREATE TABLE 就该有全部的列；MIGRATIONS 只给旧库补列（否则新库的表结构要靠升级才完整）。"""
    con = sqlite3.connect(":memory:")
    con.executescript(SCHEMA)
    missing = [(table, col) for table, col, _ in MIGRATIONS
               if col not in {row[1] for row in con.execute(f"PRAGMA table_info({table})")}]
    con.close()
    assert not missing, missing


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


def test_version_guards_content_changes():
    """内容版本：带 version 的更新只在版本没变时生效，并把版本加 1；发布时版本不符就不改状态。"""
    async def run(path):
        db = DB(path)
        await db.connect()
        try:
            sid = await db.create_draft(42, [{"type": "text", "text": "a", "entities": []}])
            await db.update(sid, status="pending")
            assert (await db.get(sid)).version == 0
            assert await db.update_if(sid, ("pending",), version=0, edited_by="x")
            assert (await db.get(sid)).version == 1
            assert not await db.update_if(sid, ("pending",), version=0, edited_by="y")  # 基于旧版本：不覆盖
            assert (await db.get(sid)).edited_by == "x"
            assert await db.update_if(sid, ("pending",), spoiler=1)  # 不带 version：照旧，不加版本
            assert (await db.get(sid)).version == 1
            assert not await db.transition(sid, ("pending",), "publishing", version=0)
            assert (await db.get(sid)).status == "pending"
            assert await db.transition(sid, ("pending",), "publishing", version=1)
        finally:
            await db.close()

    with tempfile.TemporaryDirectory() as d:
        asyncio.run(run(os.path.join(d, "v.db")))


def test_failed_publish_not_counted_as_approved():
    """发布失败的稿件 decision 仍是 approved：统计里不算通过，算待处理（等审核员重试）；重试成功后才算通过。"""
    async def run(path):
        db = DB(path)
        await db.connect()
        try:
            item = [{"type": "text", "text": "a", "entities": []}]
            ok, failed, pending = [await db.create_draft(42, item) for _ in range(3)]
            await db.update(ok, status="published", decision="approved", reviewed_at=10, submitted_at=1)
            await db.update(failed, status="failed", decision="approved", reviewed_at=10, submitted_at=1)
            await db.update(pending, status="pending", submitted_at=1)
            assert await db.review_counts(0) == (1, 0, 2)
            assert (await db.activity(0, 0))[0]["approved"] == 1
            await db.update(failed, status="published")  # 重试成功
            assert await db.review_counts(0) == (2, 0, 1)
            assert (await db.activity(0, 0))[0]["approved"] == 2
        finally:
            await db.close()

    with tempfile.TemporaryDirectory() as d:
        asyncio.run(run(os.path.join(d, "s.db")))


def test_interrupted_publish_shown_in_review_language():
    """发布中途重启：error 里存标记，控制按钮消息按审核群的语言显示（英文审核群不出现中文）。"""
    from zoneinfo import ZoneInfo
    from bot.render import control_text

    async def run(path):
        db = DB(path)
        await db.connect()
        try:
            sid = await db.create_draft(42, [{"type": "text", "text": "a", "entities": []}])
            await db.update(sid, status="publishing", submitted_at=1)
            await db.reset_stuck_publishing()
            sub = await db.get(sid)
            assert sub.status == "failed"
            en = control_text(sub, None, ZoneInfo("UTC"), None, "en")
            zh = control_text(sub, None, ZoneInfo("UTC"), None, "zh")
            assert "restarted while publishing" in en and "程序重启" not in en, en
            assert "发布过程中程序重启" in zh, zh
        finally:
            await db.close()

    with tempfile.TemporaryDirectory() as d:
        asyncio.run(run(os.path.join(d, "r.db")))


def test_expire_drafts_skips_one_submitted_meanwhile():
    """过期草稿作废和投稿人提交同时发生：刚被提交的不算过期（不会把它的提示改成“草稿已过期”）。"""
    async def run(path):
        db = DB(path)
        await db.connect()
        try:
            item = [{"type": "text", "text": "a", "entities": []}]
            stale, submitting = [await db.create_draft(42, item) for _ in range(2)]
            await db.update(stale, created_at=1)
            await db.update(submitting, created_at=1)
            # 投稿人恰好在查出过期草稿之后、作废之前点了提交
            real_all, submitted = db._all, []

            async def all_then_submit(sql, params=()):
                rows = await real_all(sql, params)
                if "status='draft'" in sql and not submitted:
                    submitted.append(await db.transition(submitting, ("draft",), "pending"))
                return rows
            db._all = all_then_submit
            got = {s.id for s in await db.expire_drafts(100)}
            submitted = submitted[0]
            # 两件事谁先都行，但结果要一致：提交成功的不在“过期”里，作废了的就没提交成功
            assert (submitting in got) != submitted, (got, submitted)
            assert stale in got and (await db.get(stale)).status == "cancelled"
        finally:
            await db.close()

    with tempfile.TemporaryDirectory() as d:
        asyncio.run(run(os.path.join(d, "e.db")))



def test_review_message_lookups_use_indexes():
    """回复审核群的消息时按 review_msg_id 定位：两张表都要走索引，不能整表扫描（旧库升级后也一样）。"""
    async def run(path):
        db = DB(path)
        await db.connect()
        try:
            for table, index in (("submissions", "idx_sub_review"), ("conversations", "idx_conv_review")):
                async with db.conn.execute(f"EXPLAIN QUERY PLAN SELECT 1 FROM {table} WHERE review_msg_id=?",
                                           (1,)) as cur:
                    plan = " ".join(str(r[-1]) for r in await cur.fetchall())
                assert index in plan, (table, plan)
        finally:
            await db.close()

    with tempfile.TemporaryDirectory() as d:
        asyncio.run(run(os.path.join(d, "i.db")))


def test_activity_links_without_extra_queries():
    """/active 的名字链接直接用查询里 JOIN 到的用户名和名字，不再逐个 get_user；每行带上用户 ID。"""
    async def run(path):
        db = DB(path)
        await db.connect()
        try:
            item = [{"type": "text", "text": "a", "entities": []}]
            await db.touch_user(1, "alice", "Alice <A>")
            await db.touch_user(2, None, "Bob")
            for uid in (1, 1, 2, 3):  # 3：没有用户记录，显示 ID
                await db.update(await db.create_draft(uid, item), status="pending", submitted_at=int(time.time()))

            async def no_get_user(*_):
                raise AssertionError("activity_text should not call get_user")
            db.get_user = no_get_user
            core = SimpleNamespace(db=db, lang="zh", s=SimpleNamespace(tz=ZoneInfo("Asia/Shanghai")),
                                   fmt=lambda ts, lang=None: "-")
            text = await StatsMixin.activity_text(core, 30)
            assert '<a href="https://t.me/alice">Alice &lt;A&gt;</a>' in text, text
            assert '<a href="tg://user?id=2">Bob</a>' in text, text
            assert '<a href="tg://user?id=3">3</a>' in text, text
            # 每行带 ID（和控制按钮消息的“投稿人：名字  ID”一样），名字点不开时也能复制 ID 发 /user
            assert '<a href="tg://user?id=2">Bob</a>  <code>2</code>' in text, text
            assert '<a href="https://t.me/alice">Alice &lt;A&gt;</a>  <code>1</code>' in text, text
        finally:
            await db.close()

    with tempfile.TemporaryDirectory() as d:
        asyncio.run(run(os.path.join(d, "a.db")))


def test_oldest_pending_is_the_longest_waiting():
    """统计消息按钮跳到的投稿：待审核里提交得最早的（不是编号最小的：草稿可能很久以后才提交）；
    没有控制按钮消息的、发布失败的、草稿都不算；审核完就轮到下一条，没有了返回 None。"""
    async def run(path):
        db = DB(path)
        await db.connect()
        try:
            item = [{"type": "text", "text": "a", "entities": []}]
            draft, late, early, no_msg, failed = [await db.create_draft(42, item) for _ in range(5)]
            await db.update(late, status="pending", submitted_at=20, review_msg_id=902)
            await db.update(early, status="pending", submitted_at=10, review_msg_id=903)
            await db.update(no_msg, status="pending", submitted_at=5)
            await db.update(failed, status="failed", submitted_at=1, review_msg_id=905)
            assert (await db.oldest_pending()).id == early
            await db.update(early, status="published")
            assert (await db.oldest_pending()).id == late
            await db.update(late, status="rejected")
            assert await db.oldest_pending() is None
        finally:
            await db.close()

    with tempfile.TemporaryDirectory() as d:
        asyncio.run(run(os.path.join(d, "o.db")))


def test_stats_button():
    """有链接时一个跳转按钮（URL 按钮，中英文）；没有待审核的就不带按钮。"""
    from bot.keyboards import stats_kb
    assert stats_kb(None, "zh") is None
    for lang, text in (("zh", "👀 查看等得最久的投稿"), ("en", "👀 Oldest pending submission")):
        [[b]] = stats_kb("https://t.me/c/123/45", lang).inline_keyboard
        assert (b.text, b.url, b.callback_data) == (text, "https://t.me/c/123/45", None)


if __name__ == "__main__":
    tests = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for fn in tests:
        fn()
        print("PASS ", fn.__name__)
    print(f"\n{len(tests)}/{len(tests)} passed")
