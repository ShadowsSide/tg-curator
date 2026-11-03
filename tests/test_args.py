"""审核群命令参数的单元测试：/user /ban /unban 的用户 ID、/active 的天数。
异常输入（²、全角数字、--5、超过 SQLite 范围的大数）不能让处理函数出错，要当成没写或写错。
用法：python tests/test_args.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aiogram.filters import CommandObject  # noqa: E402

from bot.handlers.review import MAX_ACTIVE_DAYS, _days_arg, _split_user, _user_id_arg  # noqa: E402

BAD = ["", "abc", "²", "１２３", "٣", "--5", "-5", "-1001234", "0", "007", "9" * 20, "12 34"]


def cmd(args):
    return CommandObject(prefix="/", command="x", args=args)


def test_user_id():
    assert _user_id_arg(cmd("123456")) == 123456
    assert _user_id_arg(cmd("  42 ")) == 42
    assert _user_id_arg(cmd(None)) is None
    for bad in BAD:
        assert _user_id_arg(cmd(bad)) is None, bad


def test_split_user():
    assert _split_user("123 发广告") == (123, "发广告")
    assert _split_user("123") == (123, None)
    for bad in (b for b in BAD if " " not in b):  # "12 34 理由" 就是用户 12、理由“34 理由”
        assert _split_user(f"{bad} 理由") == (None, None), bad


def test_days():
    assert _days_arg(cmd("7")) == 7
    assert _days_arg(cmd(None)) == 30
    assert _days_arg(cmd("99999")) == MAX_ACTIVE_DAYS
    for bad in ["0", "²", "１２", "-3", "abc", "9" * 30]:
        assert _days_arg(cmd(bad)) == 30, bad


if __name__ == "__main__":
    tests = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for fn in tests:
        fn()
        print("PASS ", fn.__name__)
    print(f"\n{len(tests)}/{len(tests)} passed")
