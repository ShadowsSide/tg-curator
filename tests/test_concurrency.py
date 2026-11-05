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


if __name__ == "__main__":
    tests = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for fn in tests:
        fn()
        print("PASS ", fn.__name__)
    print(f"\n{len(tests)}/{len(tests)} passed")
