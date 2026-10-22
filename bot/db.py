from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterable

import aiosqlite

from .timeutil import now_ts

# 投稿状态：
#   draft      用户已发送内容，还没选署名/匿名
#   pending    待审核
#   scheduled  已通过，等待定时发布
#   publishing 正在发布（防止重复发布的中间态）
#   published  已发布到频道
#   rejected   已拒绝
#   failed     发布失败（可重试）
#   cancelled  用户取消或草稿过期
SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS users (
    user_id    INTEGER PRIMARY KEY,
    username   TEXT,
    full_name  TEXT    NOT NULL DEFAULT '',
    banned     INTEGER NOT NULL DEFAULT 0,
    ban_reason TEXT,
    banned_at  INTEGER,
    banned_by  TEXT,
    lang       TEXT,
    first_seen INTEGER NOT NULL,
    last_seen  INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS submissions (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id        INTEGER NOT NULL,
    items          TEXT    NOT NULL,
    anonymous      INTEGER NOT NULL DEFAULT 0,
    spoiler        INTEGER NOT NULL DEFAULT 0,
    silent         INTEGER NOT NULL DEFAULT 0,
    status         TEXT    NOT NULL DEFAULT 'draft',
    decision       TEXT,
    created_at     INTEGER NOT NULL,
    submitted_at   INTEGER,
    reviewed_at    INTEGER,
    reviewer_id    INTEGER,
    reviewer_name  TEXT,
    scheduled_at   INTEGER,
    published_at   INTEGER,
    user_msg_id    INTEGER,
    review_msg_id  INTEGER,
    channel_msg_id INTEGER,
    reject_reason  TEXT,
    original_items TEXT,
    edited_by      TEXT,
    edited_at      INTEGER,
    review_topic_id INTEGER,
    user_topic_id  INTEGER,
    topic_status   TEXT,
    error          TEXT
);

CREATE INDEX IF NOT EXISTS idx_sub_status ON submissions(status, scheduled_at);
CREATE INDEX IF NOT EXISTS idx_sub_user   ON submissions(user_id, submitted_at);

-- 审核群里属于某条投稿的所有消息（预览 + 控制消息），用于 /no、/ban 回复定位投稿
CREATE TABLE IF NOT EXISTS review_messages (
    message_id INTEGER PRIMARY KEY,
    sid        INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS kv (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""

# 旧库升级：表已存在时 CREATE TABLE 不会加新列，这里补上 (表, 列, DDL)
MIGRATIONS = [
    ("submissions", "silent", "ALTER TABLE submissions ADD COLUMN silent INTEGER NOT NULL DEFAULT 0"),
    ("submissions", "reject_reason", "ALTER TABLE submissions ADD COLUMN reject_reason TEXT"),
    ("users", "ban_reason", "ALTER TABLE users ADD COLUMN ban_reason TEXT"),
    ("users", "banned_at", "ALTER TABLE users ADD COLUMN banned_at INTEGER"),
    ("users", "banned_by", "ALTER TABLE users ADD COLUMN banned_by TEXT"),
    ("submissions", "original_items", "ALTER TABLE submissions ADD COLUMN original_items TEXT"),
    ("submissions", "edited_by", "ALTER TABLE submissions ADD COLUMN edited_by TEXT"),
    ("submissions", "edited_at", "ALTER TABLE submissions ADD COLUMN edited_at INTEGER"),
    ("users", "lang", "ALTER TABLE users ADD COLUMN lang TEXT"),
    ("submissions", "review_topic_id", "ALTER TABLE submissions ADD COLUMN review_topic_id INTEGER"),
    ("submissions", "user_topic_id", "ALTER TABLE submissions ADD COLUMN user_topic_id INTEGER"),
    ("submissions", "topic_status", "ALTER TABLE submissions ADD COLUMN topic_status TEXT"),
]

OPEN_STATES = ("pending", "scheduled", "failed")  # 已提交、尚未发布或拒绝
SUBMITTER_EDITABLE = ("draft", "pending")  # 投稿人自己能修改的状态：审核结果出来之前

SPOILERABLE = {"photo", "video", "animation"}


@dataclass
class User:
    user_id: int
    username: str | None
    full_name: str
    banned: bool
    ban_reason: str | None
    banned_at: int | None
    banned_by: str | None
    lang: str | None
    first_seen: int
    last_seen: int


@dataclass
class Submission:
    id: int
    user_id: int
    items: list[dict[str, Any]]
    anonymous: bool
    spoiler: bool
    silent: bool
    status: str
    decision: str | None
    created_at: int
    submitted_at: int | None
    reviewed_at: int | None
    reviewer_id: int | None
    reviewer_name: str | None
    scheduled_at: int | None
    published_at: int | None
    user_msg_id: int | None
    review_msg_id: int | None
    channel_msg_id: int | None
    reject_reason: str | None
    original_items: list[dict[str, Any]] | None  # 第一次 /edit 前的原稿
    edited_by: str | None
    edited_at: int | None
    review_topic_id: int | None  # 话题模式：审核群里这条投稿的话题
    user_topic_id: int | None  # 话题模式：投稿人私聊里这条投稿的话题
    topic_status: str | None  # 话题名称上次同步时的状态，避免重复改名
    error: str | None

    @property
    def spoilerable(self) -> bool:
        return any(i["type"] in SPOILERABLE for i in self.items)

    @classmethod
    def from_row(cls, row: aiosqlite.Row) -> "Submission":
        data = dict(row)
        data["items"] = json.loads(data["items"])
        data["original_items"] = json.loads(data["original_items"]) if data["original_items"] else None
        data["anonymous"] = bool(data["anonymous"])
        data["spoiler"] = bool(data["spoiler"])
        data["silent"] = bool(data["silent"])
        return cls(**data)


class DB:
    def __init__(self, path: str):
        self.path = path
        self.conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self.conn = await aiosqlite.connect(self.path)
        self.conn.row_factory = aiosqlite.Row
        await self.conn.executescript(SCHEMA)
        for table, column, ddl in MIGRATIONS:
            columns = {r[1] for r in await self._all(f"PRAGMA table_info({table})")}
            if column not in columns:
                await self.conn.execute(ddl)
        await self.conn.commit()

    async def close(self) -> None:
        if self.conn:
            await self.conn.close()

    async def _one(self, sql: str, params: Iterable[Any] = ()) -> aiosqlite.Row | None:
        async with self.conn.execute(sql, tuple(params)) as cur:
            return await cur.fetchone()

    async def _all(self, sql: str, params: Iterable[Any] = ()) -> list[aiosqlite.Row]:
        async with self.conn.execute(sql, tuple(params)) as cur:
            return list(await cur.fetchall())

    async def _exec(self, sql: str, params: Iterable[Any] = ()) -> int:
        cur = await self.conn.execute(sql, tuple(params))
        await self.conn.commit()
        return cur.rowcount

    # ---------- users ----------

    async def touch_user(self, user_id: int, username: str | None, full_name: str, lang: str | None = None) -> None:
        ts = now_ts()
        await self._exec(
            """INSERT INTO users(user_id, username, full_name, lang, first_seen, last_seen)
               VALUES(?, ?, ?, ?, ?, ?)
               ON CONFLICT(user_id) DO UPDATE SET
                 username=excluded.username, full_name=excluded.full_name,
                 lang=COALESCE(excluded.lang, users.lang), last_seen=excluded.last_seen""",
            (user_id, username, full_name, lang, ts, ts),
        )

    async def get_user(self, user_id: int) -> User | None:
        row = await self._one("SELECT * FROM users WHERE user_id=?", (user_id,))
        if not row:
            return None
        data = dict(row)
        data["banned"] = bool(data["banned"])
        return User(**data)

    async def ban(self, user_id: int, reason: str | None, by: str) -> None:
        """封禁；用户从没和机器人说过话也可以预先封禁。"""
        ts = now_ts()
        await self._exec(
            """INSERT INTO users(user_id, full_name, banned, ban_reason, banned_at, banned_by, first_seen, last_seen)
               VALUES(?, '', 1, ?, ?, ?, ?, ?)
               ON CONFLICT(user_id) DO UPDATE SET
                 banned=1, ban_reason=excluded.ban_reason, banned_at=excluded.banned_at, banned_by=excluded.banned_by""",
            (user_id, reason, ts, by, ts, ts),
        )

    async def unban(self, user_id: int) -> bool:
        return await self._exec(
            "UPDATE users SET banned=0, ban_reason=NULL, banned_at=NULL, banned_by=NULL WHERE user_id=? AND banned=1",
            (user_id,),
        ) == 1

    # ---------- submissions ----------

    async def create_draft(self, user_id: int, items: list[dict[str, Any]], silent: bool = False,
                           spoiler: bool = False) -> int:
        cur = await self.conn.execute(
            "INSERT INTO submissions(user_id, items, silent, spoiler, status, created_at) VALUES(?, ?, ?, ?, 'draft', ?)",
            (user_id, json.dumps(items, ensure_ascii=False), int(silent), int(spoiler), now_ts()),
        )
        await self.conn.commit()
        return cur.lastrowid

    async def get(self, sid: int) -> Submission | None:
        row = await self._one("SELECT * FROM submissions WHERE id=?", (sid,))
        return Submission.from_row(row) if row else None

    async def update(self, sid: int, **fields: Any) -> None:
        for key in ("items", "original_items"):
            if isinstance(fields.get(key), list):
                fields[key] = json.dumps(fields[key], ensure_ascii=False)
        cols = ", ".join(f"{k}=?" for k in fields)
        await self._exec(f"UPDATE submissions SET {cols} WHERE id=?", (*fields.values(), sid))

    async def update_if(self, sid: int, states: Iterable[str], **fields: Any) -> bool:
        """只在状态仍属于 states 时更新（防止修改和发布/审核同时发生）。"""
        states = tuple(states)
        for key in ("items", "original_items"):
            if isinstance(fields.get(key), list):
                fields[key] = json.dumps(fields[key], ensure_ascii=False)
        cols = ", ".join(f"{k}=?" for k in fields)
        marks = ", ".join("?" * len(states))
        return await self._exec(
            f"UPDATE submissions SET {cols} WHERE id=? AND status IN ({marks})", (*fields.values(), sid, *states)
        ) == 1

    async def find_by_user_message(self, user_id: int, message_id: int) -> tuple[int, int | None] | None:
        """用户私聊里的某条消息属于哪条投稿：
        - 是投稿内容本身 → (投稿编号, 第几项)
        - 是机器人的“请选择投稿方式 / 已提交”提示 → (投稿编号, None)"""
        row = await self._one(
            """SELECT s.id, CAST(j.key AS INTEGER) FROM submissions s, json_each(s.items) j
               WHERE s.user_id=? AND json_extract(j.value, '$.msg_id')=? ORDER BY s.id DESC LIMIT 1""",
            (user_id, message_id),
        )
        if row:
            return row[0], row[1]
        row = await self._one(
            "SELECT id FROM submissions WHERE user_id=? AND user_msg_id=? ORDER BY id DESC LIMIT 1",
            (user_id, message_id),
        )
        return (row[0], None) if row else None

    async def sid_by_review_topic(self, thread_id: int) -> int | None:
        row = await self._one("SELECT id FROM submissions WHERE review_topic_id=? ORDER BY id DESC LIMIT 1", (thread_id,))
        return row[0] if row else None

    async def sid_by_user_topic(self, user_id: int, thread_id: int) -> int | None:
        row = await self._one(
            "SELECT id FROM submissions WHERE user_id=? AND user_topic_id=? ORDER BY id DESC LIMIT 1", (user_id, thread_id)
        )
        return row[0] if row else None

    async def transition(self, sid: int, from_states: Iterable[str], to_state: str, **fields: Any) -> bool:
        """原子地把状态从 from_states 之一改成 to_state；状态不符时返回 False（防并发重复操作）。"""
        from_states = tuple(from_states)
        fields["status"] = to_state
        cols = ", ".join(f"{k}=?" for k in fields)
        marks = ", ".join("?" * len(from_states))
        changed = await self._exec(
            f"UPDATE submissions SET {cols} WHERE id=? AND status IN ({marks})",
            (*fields.values(), sid, *from_states),
        )
        return changed == 1

    async def open_by_user(self, user_id: int) -> list[Submission]:
        marks = ", ".join("?" * len(OPEN_STATES))
        rows = await self._all(
            f"SELECT * FROM submissions WHERE user_id=? AND status IN ({marks}) ORDER BY id", (user_id, *OPEN_STATES)
        )
        return [Submission.from_row(r) for r in rows]

    async def cancel_drafts_of(self, user_id: int) -> None:
        await self._exec("UPDATE submissions SET status='cancelled' WHERE user_id=? AND status='draft'", (user_id,))

    async def link_review_messages(self, sid: int, message_ids: Iterable[int]) -> None:
        await self.conn.executemany(
            "INSERT OR REPLACE INTO review_messages(message_id, sid) VALUES(?, ?)", [(m, sid) for m in message_ids]
        )
        await self.conn.commit()

    async def sid_by_review_message(self, message_id: int) -> int | None:
        row = await self._one(
            """SELECT sid FROM review_messages WHERE message_id=?
               UNION ALL SELECT id FROM submissions WHERE review_msg_id=? LIMIT 1""",
            (message_id, message_id),
        )
        return row[0] if row else None

    async def count_open_by_user(self, user_id: int) -> int:
        row = await self._one(
            "SELECT COUNT(*) FROM submissions WHERE user_id=? AND status IN ('draft', 'pending')", (user_id,)
        )
        return row[0]

    async def due_scheduled(self, ts: int) -> list[Submission]:
        rows = await self._all(
            "SELECT * FROM submissions WHERE status='scheduled' AND scheduled_at<=? ORDER BY scheduled_at", (ts,)
        )
        return [Submission.from_row(r) for r in rows]

    async def upcoming_scheduled(self, limit: int = 20) -> list[Submission]:
        rows = await self._all(
            "SELECT * FROM submissions WHERE status='scheduled' ORDER BY scheduled_at LIMIT ?", (limit,)
        )
        return [Submission.from_row(r) for r in rows]

    async def expire_drafts(self, older_than: int) -> list[Submission]:
        rows = await self._all(
            "SELECT * FROM submissions WHERE status='draft' AND created_at<?", (older_than,)
        )
        await self._exec("UPDATE submissions SET status='cancelled' WHERE status='draft' AND created_at<?", (older_than,))
        return [Submission.from_row(r) for r in rows]

    async def reset_stuck_publishing(self) -> None:
        """进程在发布中途退出时，把 publishing 标成 failed 让管理员决定是否重试。"""
        await self._exec(
            "UPDATE submissions SET status='failed', error='发布过程中程序重启，请确认频道后决定是否重试' "
            "WHERE status='publishing'"
        )

    # ---------- stats ----------

    async def review_counts(self, since: int) -> tuple[int, int, int]:
        row = await self._one(
            """SELECT
                 COALESCE(SUM(decision='approved' AND reviewed_at>=?), 0),
                 COALESCE(SUM(decision='rejected' AND reviewed_at>=?), 0),
                 COALESCE(SUM(status='pending'), 0)
               FROM submissions""",
            (since, since),
        )
        return row[0], row[1], row[2]

    async def activity(self, since: int, tz_offset: int, limit: int = 20) -> list[aiosqlite.Row]:
        return await self._all(
            """SELECT s.user_id, u.username, u.full_name, u.banned,
                      COUNT(*)                                                     AS total,
                      SUM(s.decision='approved')                                   AS approved,
                      SUM(s.decision='rejected')                                   AS rejected,
                      SUM(s.anonymous)                                             AS anonymous,
                      COUNT(DISTINCT date(s.submitted_at + ?, 'unixepoch'))        AS active_days,
                      MAX(s.submitted_at)                                          AS last_at
               FROM submissions s LEFT JOIN users u ON u.user_id = s.user_id
               WHERE s.submitted_at >= ?
               GROUP BY s.user_id
               ORDER BY total DESC, approved DESC, last_at DESC
               LIMIT ?""",
            (tz_offset, since, limit),
        )

    async def activity_totals(self, since: int) -> tuple[int, int]:
        row = await self._one(
            "SELECT COUNT(*), COUNT(DISTINCT user_id) FROM submissions WHERE submitted_at >= ?", (since,)
        )
        return row[0], row[1]

    async def user_summary(self, user_id: int) -> dict[str, int | None]:
        row = await self._one(
            """SELECT COUNT(*)                    AS total,
                      SUM(status='published')     AS published,
                      SUM(status='scheduled')     AS scheduled,
                      SUM(status='pending')       AS pending,
                      SUM(decision='rejected')    AS rejected,
                      SUM(anonymous)              AS anonymous,
                      MIN(submitted_at)           AS first_at,
                      MAX(submitted_at)           AS last_at
               FROM submissions WHERE user_id=? AND submitted_at IS NOT NULL""",
            (user_id,),
        )
        return {k: (row[k] or 0) if k not in ("first_at", "last_at") else row[k] for k in row.keys()}

    # ---------- kv ----------

    async def kv_get(self, key: str) -> str | None:
        row = await self._one("SELECT value FROM kv WHERE key=?", (key,))
        return row[0] if row else None

    async def kv_set(self, key: str, value: str | None) -> None:
        if value is None:
            await self._exec("DELETE FROM kv WHERE key=?", (key,))
        else:
            await self._exec(
                "INSERT INTO kv(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )
