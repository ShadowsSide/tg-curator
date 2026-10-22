"""业务层提示（Notice）测试：core 只返回代码，翻译留给显示的地方。用法：python tests/test_errors.py"""
import ast
import os
import pathlib
import sys

ROOT = pathlib.Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, str(ROOT))

from bot.errors import Notice, notice  # noqa: E402
from bot.i18n import LANGS, T  # noqa: E402

CORE = ROOT / "bot" / "core.py"


def _functions(tree):
    return [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]


def test_notice_methods_never_return_translated_text():
    """返回值标注为 Notice 的方法里，不允许出现 return t(...)（那是把翻译又放回了业务层）。"""
    tree = ast.parse(CORE.read_text())
    offenders = []
    for fn in _functions(tree):
        if fn.returns is None or "Notice" not in ast.unparse(fn.returns):
            continue
        for node in ast.walk(fn):
            if isinstance(node, ast.Return) and isinstance(node.value, ast.Call) \
                    and isinstance(node.value.func, ast.Name) and node.value.func.id == "t":
                offenders.append(f"{fn.name}:{node.lineno}")
    assert not offenders, offenders
    assert sum(1 for fn in _functions(tree) if fn.returns is not None and "Notice" in ast.unparse(fn.returns)) >= 15


def test_every_notice_key_exists_in_both_languages():
    """代码里 notice("...") 用到的每个代码都要在文案表里，且中英文都有。"""
    keys = set()
    for path in (ROOT / "bot").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "notice":
                arg = node.args[0]
                if isinstance(arg, ast.Constant):
                    keys.add(arg.value)
                elif isinstance(arg, ast.JoinedStr):  # f"not_editable_{...}"：检查所有可能的取值
                    prefix = arg.values[0].value
                    assert any(k.startswith(prefix) for k in T), prefix
                elif isinstance(arg, ast.Name):  # 变量（例如 reject 里按状态选的 key）由下面的 reject_* 检查覆盖
                    continue
    keys |= {k for k in T if k.startswith(("reject_", "not_editable_"))}
    missing = [k for k in keys if k not in T or set(T[k]) != set(LANGS)]
    assert not missing, missing
    assert len(keys) >= 20


def test_notice_renders_per_language_including_nested():
    n = notice("toast_spoiler", state=notice("on"))
    assert n.text("zh") == "剧透遮罩：开"
    assert n.text("en") == "Spoiler: on"
    assert notice("time_past").key == "time_past"  # 判断用 key，不用翻译后的文字
    assert Notice("sub_not_found").text("en") == "This submission doesn't exist"


if __name__ == "__main__":
    tests = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for fn in tests:
        fn()
        print("PASS ", fn.__name__)
    print(f"{len(tests)}/{len(tests)} passed")
