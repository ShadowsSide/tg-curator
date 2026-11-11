"""自动备份数据库（bot/backup.py、db.DB.backup、core 的 backup_now / _backup_loop）。
用法：python tests/test_backup.py
到点真的备份、审核群收到提醒见 live_backup_test.py。
"""
import asyncio
import contextlib
import os
import sqlite3
import sys
import tempfile
from types import SimpleNamespace
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bot.backup import backup_dir, human_size, make_backup, prune  # noqa: E402
from bot.core.scheduler import SchedulerMixin  # noqa: E402
from bot.db import DB  # noqa: E402


def run(coro):
    return asyncio.run(coro)


async def open_db(folder):
    db = DB(os.path.join(folder, "bot.db"))
    await db.connect()
    try:
        await db.conn.execute("CREATE TABLE note(text TEXT)")
        await db.conn.execute("INSERT INTO note VALUES ('Alice')")
        await db.conn.commit()
    except BaseException:
        await db.close()  # 不关的话 aiosqlite 的线程会让进程卡住不退出
        raise
    return db


def test_backup_is_a_consistent_copy_and_old_ones_are_pruned():
    async def go():
        folder = tempfile.mkdtemp()
        db = await open_db(folder)
        try:
            backups = backup_dir(db.path)
            os.makedirs(backups)
            for day in ("2000-01-01", "2000-01-02", "2000-01-03"):  # 以前的备份
                open(os.path.join(backups, f"bot-{day}.db"), "wb").close()
            open(os.path.join(backups, "notes.txt"), "w").close()  # 别的文件不动
            name, size = await make_backup(db, db.path, 2, "2026-11-12")
            path = os.path.join(backups, name)
            with contextlib.closing(sqlite3.connect(path)) as conn:  # with sqlite3.connect 不会关闭连接
                assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
                assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
                assert conn.execute("SELECT text FROM note").fetchone()[0] == "Alice"
            assert size == os.path.getsize(path) > 0
            assert sorted(os.listdir(backups)) == ["bot-2000-01-03.db", "bot-2026-11-12.db", "notes.txt"], os.listdir(backups)
            await make_backup(db, db.path, 2, "2026-11-12")  # 同一天再备份：覆盖，不多出一份
            assert sorted(os.listdir(backups)) == ["bot-2000-01-03.db", "bot-2026-11-12.db", "notes.txt"], os.listdir(backups)
        finally:
            await db.close()
    run(go())


def test_failed_backup_keeps_the_old_file_and_leaves_no_temp_file():
    async def go():
        folder = tempfile.mkdtemp()
        db = await open_db(folder)
        target = os.path.join(folder, "copy.db")
        with open(target, "wb") as f:
            f.write(b"old backup")
        real = db.conn.backup

        async def broken(*a, **kw):
            raise sqlite3.OperationalError("disk I/O error")
        db.conn.backup = broken
        try:
            await db.backup(target)
        except sqlite3.OperationalError:
            pass
        else:
            raise AssertionError("should raise")
        finally:
            db.conn.backup = real
            await db.close()
        assert open(target, "rb").read() == b"old backup" and not os.path.exists(target + ".tmp")
    run(go())


def test_prune_and_size():
    folder = tempfile.mkdtemp()
    for day in ("2026-01-01", "2026-01-02", "2026-01-03"):
        open(os.path.join(folder, f"bot-{day}.db"), "wb").close()
    assert prune(folder, 3) == [] and prune(folder, 1) == ["bot-2026-01-01.db", "bot-2026-01-02.db"]
    assert (human_size(10), human_size(300 * 1024), human_size(5 * 1024 * 1024 + 1)) == ("1 KB", "300 KB", "5.0 MB")


class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, **kw):
        self.sent.append((chat_id, text, kw))


def fake_core(db, db_path, keep=7):
    s = SimpleNamespace(db_path=db_path, backup_keep=keep, backup_time="04:00", tz=ZoneInfo("Asia/Shanghai"),
                        review_chat_id=-1001)
    return SimpleNamespace(db=db, s=s, lang="zh", bot=FakeBot())


def test_backup_now_reports_success_and_failure_silently():
    async def go():
        folder = tempfile.mkdtemp()
        db = await open_db(folder)
        try:
            core = fake_core(db, db.path)
            await SchedulerMixin.backup_now(core)
            (chat, text, kw), = core.bot.sent
            assert chat == -1001 and "已自动备份" in text and "保留最近 7 份" in text and kw.get("disable_notification")

            broken = tempfile.mkdtemp()  # backups 的位置被一个普通文件占了：建不了目录
            open(os.path.join(broken, "backups"), "w").close()
            core = fake_core(db, os.path.join(broken, "bot.db"))
            await SchedulerMixin.backup_now(core)  # 不抛出：后台循环要继续，明天再试
            (chat, text, kw), = core.bot.sent
            assert "备份失败" in text and kw.get("disable_notification"), text
        finally:
            await db.close()
    run(go())


def test_backup_off_when_keep_is_zero():
    async def go():
        core = fake_core(None, "/nonexistent/bot.db", keep=0)
        await asyncio.wait_for(SchedulerMixin._backup_loop(core), 1)  # 直接返回，不等到点
        assert core.bot.sent == []
    run(go())


if __name__ == "__main__":
    tests = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for fn in tests:
        fn()
        print("PASS ", fn.__name__)
    print(f"{len(tests)}/{len(tests)} passed")
