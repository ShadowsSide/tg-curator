"""README 中英文同步测试：两份 README 结构一致，配置变量和命令都和代码对得上。用法：python tests/test_readme.py

- 标题层级、表格行、代码块数量一致（英文版开头多一段语言说明，不算）
- 配置表的分组和每组的变量、顺序一致，并且正好是 bot/config.py 读取的变量（加 compose 用的 IMAGE）
- 审核群和私聊的命令表都列出了机器人注册的命令（/start、/help 除外）
"""
import os
import pathlib
import re
import sys

ROOT = pathlib.Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, str(ROOT))

from bot.i18n import PRIVATE_COMMANDS, REVIEW_COMMANDS  # noqa: E402

ZH = (ROOT / "README.md").read_text(encoding="utf-8").split("\n")
EN = (ROOT / "README.en.md").read_text(encoding="utf-8").split("\n")
# 只在 README 里说明、代码里不读的变量；以及只在开发说明里出现、不放进配置表的变量
EXTRA_VARS = {"IMAGE"}
UNLISTED_VARS = {"DB_PATH"}
TRIVIAL_COMMANDS = {"start", "help"}


def section(lines, start, stop):
    return lines[lines.index(start):lines.index(stop)]


def shape(lines):
    """每行的“骨架”：标题层级、表格行（只留第一列的命令名或变量名）、代码块、引用、列表。"""
    out = []
    for line in lines:
        if m := re.match(r"(#+) ", line):
            out.append(m.group(1))
        elif m := re.match(r"\| `/?([A-Za-z_]+)", line):
            out.append("|" + m.group(1))
        elif line.startswith("|"):
            out.append("|")
        elif line.startswith("```"):
            out.append("```")
        elif m := re.match(r"(>|-|\d+\.) ", line):
            out.append(m.group(1))
    return out


def config_groups(lines, start, stop):
    groups = []
    for line in section(lines, start, stop):
        if line.startswith("### "):
            groups.append([])
        elif m := re.match(r"\| `([A-Z_]+)`", line):
            groups[-1].append(m.group(1))
    return groups


def commands(lines, start, stop):
    return {m.group(1) for line in section(lines, start, stop) if (m := re.match(r"\| `/([a-z]+)", line))}


def test_same_shape():
    en = shape(EN)
    en.remove(">")  # 英文版开头的语言说明
    assert shape(ZH) == en


def test_config_groups_match_and_cover_config_py():
    zh = config_groups(ZH, "## 配置", "## 使用")
    en = config_groups(EN, "## Configuration", "## Usage")
    assert zh == en and len(zh) == 3, (zh, en)
    src = (ROOT / "bot" / "config.py").read_text(encoding="utf-8")
    read = set(re.findall(r'(?:_env|os\.environ\.get)\("([A-Z_]+)"', src))
    listed = [v for g in zh for v in g]
    assert len(listed) == len(set(listed)), "a variable is listed twice"
    assert set(listed) == read - UNLISTED_VARS | EXTRA_VARS, set(listed) ^ (read - UNLISTED_VARS | EXTRA_VARS)


def test_command_tables_list_registered_commands():
    for lines, priv, admin, end in [(ZH, "### 投稿人", "### 管理员", "## 已知限制"),
                                    (EN, "### Submitters", "### Admins", "## Known limitations")]:
        priv = next(l for l in lines if l.startswith(priv))
        admin = next(l for l in lines if l.startswith(admin))
        end = next(l for l in lines if l.startswith(end))
        for registered, (a, b) in [(PRIVATE_COMMANDS, (priv, admin)), (REVIEW_COMMANDS, (admin, end))]:
            want = {c for c, _ in registered["zh"]} - TRIVIAL_COMMANDS
            missing = want - commands(lines, a, b)
            assert not missing, f"{a}: missing {missing}"


if __name__ == "__main__":
    tests = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for fn in tests:
        fn()
        print("PASS ", fn.__name__)
    print(f"{len(tests)}/{len(tests)} passed")
