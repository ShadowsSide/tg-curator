"""停止时的等待（core.shutdown）：等处理函数做完；等太久就取消，不会一直卡住。
用法：python tests/test_shutdown.py
"""
import asyncio
import os
import re
import sys
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from aiogram import Dispatcher  # noqa: E402

from bot.core import Core, base  # noqa: E402


def core():
    return Core(None, None, SimpleNamespace(language="zh", album_delay=0))


async def waits_for_handlers():
    done = []

    async def handler():
        await asyncio.sleep(0.05)
        done.append(1)
    await core().shutdown({asyncio.create_task(handler())})
    assert done == [1]


async def gives_up_after_the_limit():
    base.SHUTDOWN_WAIT = 0.05
    stuck = asyncio.create_task(asyncio.sleep(60))
    await asyncio.wait_for(core().shutdown({stuck}), 2)
    assert stuck.cancelled()


def test_dispatcher_exposes_running_tasks():
    assert isinstance(Dispatcher()._handle_update_tasks, set)  # __main__ 依赖这个私有属性


def test_grace_period_longer_than_wait():
    with open(os.path.join(ROOT, "docker-compose.yml"), encoding="utf-8") as f:
        grace = int(re.search(r"stop_grace_period: (\d+)s", f.read()).group(1))
    assert grace > base.SHUTDOWN_WAIT


if __name__ == "__main__":
    test_dispatcher_exposes_running_tasks()
    test_grace_period_longer_than_wait()
    asyncio.run(waits_for_handlers())
    asyncio.run(gives_up_after_the_limit())
    print("ok")
