"""结构约束测试。用法：python tests/test_structure.py

- 处理函数（bot/handlers）只通过 Core 的方法访问业务和数据，不直接访问数据库（core.db）
- Core 由 bot/core/ 下的几个模块组合而成，同一个方法不能在两个模块里各定义一份（后定义的会悄悄覆盖前一个）
- 按钮只通过回应对象回应（bot/callbacks.py），不直接调用 cq.answer()：否则兜底不知道已经回应过，会再回应一次
- 端到端测试等按钮回应时要认准是哪一次点击的（lt.press，或 lt.cb 返回的编号配 lt.answered）：
  只等“第一个 answerCallbackQuery”的话，上一次点击晚到的回应会被当成这一次的，测试偶发失败
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


def test_buttons_answered_only_through_the_answer_object():
    direct = re.compile(r"\b(cq|callback|callback_query|query|event)\.answer\(|AnswerCallbackQuery\(|answer_callback_query\(")
    offenders = [f"{f.relative_to(ROOT)}:{i}" for f in sorted((ROOT / "bot").rglob("*.py")) if f.name != "callbacks.py"
                 for i, line in enumerate(f.read_text().splitlines(), 1) if direct.search(line)]
    assert not offenders, offenders


def test_live_tests_wait_for_their_own_button_answer():
    # 不带任何别的条件、只看方法名的等待；带文字条件的（等某一句提示）和统计全部回应的列表不算
    bare = re.compile(r"""wait_for\(\s*lambda\s+\w+\s*:\s*\w+\[["']method["']\]\s*==\s*["']answerCallbackQuery["']\s*,""")
    offenders = [f"{f.relative_to(ROOT)}:{i}" for f in sorted((ROOT / "tests").glob("*.py"))
                 for i, line in enumerate(f.read_text().splitlines(), 1) if bare.search(line)]
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
