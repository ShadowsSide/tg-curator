"""结构约束测试。用法：python tests/test_structure.py

- 处理函数（bot/handlers）只通过 Core 的方法访问业务和数据，不直接访问数据库（core.db）
- Core 由 bot/core/ 下的几个模块组合而成，同一个方法不能在两个模块里各定义一份（后定义的会悄悄覆盖前一个）
"""
import os
import pathlib
import re
import sys

ROOT = pathlib.Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, str(ROOT))


def test_handlers_do_not_touch_the_database():
    offenders = [f"{f.name}:{i}" for f in sorted((ROOT / "bot" / "handlers").glob("*.py"))
                 for i, line in enumerate(f.read_text().splitlines(), 1) if re.search(r"\bcore\.db\b", line)]
    assert not offenders, offenders


def test_core_modules_do_not_redefine_methods():
    from bot.core import Core
    seen: dict[str, str] = {}
    clashes = []
    for cls in Core.__mro__[1:-1]:
        for name, value in vars(cls).items():
            if name.startswith("__") or not (callable(value) or isinstance(value, staticmethod)):
                continue
            if name in seen:
                clashes.append(f"{name}: {seen[name]} / {cls.__name__}")
            seen[name] = cls.__name__
    assert not clashes, clashes
    assert len(seen) >= 50


if __name__ == "__main__":
    tests = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for fn in tests:
        fn()
        print("PASS ", fn.__name__)
    print(f"{len(tests)}/{len(tests)} passed")
