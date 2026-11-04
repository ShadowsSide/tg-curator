"""投稿人操作频率限制（bot/throttle.py）。用法：python tests/test_throttle.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bot.throttle import Throttle  # noqa: E402


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def hit(th, user_id):
    """一次成功的操作：先查，没超过就记下（和 core 里的用法一样）。"""
    wait = th.wait(user_id)
    if not wait:
        th.record(user_id)
    return wait


def test_limit_within_window():
    clock = Clock()
    th = Throttle(limit=3, window=60, clock=clock)
    for _ in range(3):  # 第 0、10、20 秒各一次
        assert hit(th, 1) == 0
        clock.now += 10
    assert hit(th, 1) == 30  # 第 30 秒：最早那次 30 秒后才过期
    assert hit(th, 2) == 0  # 别人不受影响
    clock.now += 30
    assert hit(th, 1) == 0  # 第 60 秒：最早那次过期了，又能用一次（被拒的那次不算数）
    assert hit(th, 1) == 10  # 剩下最早的是第 10 秒那次


def test_wait_alone_doesnt_count():
    """只查不记：操作失败（没有 record）不占次数。"""
    th = Throttle(limit=2, window=60, clock=Clock())
    for _ in range(5):
        assert th.wait(1) == 0
    th.record(1)
    th.record(1)
    assert th.wait(1) > 0


def test_prune_forgets_idle_users():
    clock = Clock()
    th = Throttle(limit=3, window=60, clock=clock)
    th.record(1)
    clock.now += 30
    th.record(2)
    clock.now += 31
    th.prune()
    assert list(th._recent) == [2]


if __name__ == "__main__":
    tests = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for fn in tests:
        fn()
        print("PASS ", fn.__name__)
    print(f"{len(tests)}/{len(tests)} passed")
