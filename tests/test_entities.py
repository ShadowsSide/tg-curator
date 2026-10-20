"""entity 偏移计算（UTF-16）的单元测试。用法：python tests/test_entities.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bot import entities as ent  # noqa: E402


def test_u16len():
    assert ent.u16len("abc") == 3
    assert ent.u16len("中文") == 2
    assert ent.u16len("🔥") == 2          # emoji 在 UTF-16 里是代理对
    assert ent.u16len("👨‍👩‍👧") == 8      # ZWJ 组合 emoji


def test_strip_command_keeps_formatting():
    text = "/edit 🔥 新的说明 https://x.y"
    entities = [
        {"type": "bot_command", "offset": 0, "length": 5},
        {"type": "custom_emoji", "offset": 6, "length": 2, "custom_emoji_id": "1"},
        {"type": "bold", "offset": 9, "length": 4},
        {"type": "url", "offset": 14, "length": 11},
    ]
    body, out = ent.strip_command(text, entities)
    assert body == "🔥 新的说明 https://x.y"
    assert out == [
        {"type": "custom_emoji", "offset": 0, "length": 2, "custom_emoji_id": "1"},
        {"type": "bold", "offset": 3, "length": 4},
        {"type": "url", "offset": 8, "length": 11},
    ]
    assert body.encode("utf-16-le")[3 * 2:(3 + 4) * 2].decode("utf-16-le") == "新的说明"  # 按 UTF-16 落点


def test_strip_command_with_bot_name_and_newline():
    body, out = ent.strip_command("/edit@my_bot\n第二行", [{"type": "italic", "offset": 13, "length": 3}])
    assert body == "第二行" and out == [{"type": "italic", "offset": 0, "length": 3}]


def test_cut_prefix_clips_entity_spanning_cut():
    body, out = ent.cut_prefix("#12 粗体", [{"type": "bold", "offset": 0, "length": 6}], 4)
    assert body == "粗体" and out == [{"type": "bold", "offset": 0, "length": 2}]


def test_join_shifts_signature_entities_by_utf16():
    text, out = ent.join(
        "A🔥", [{"type": "custom_emoji", "offset": 1, "length": 2, "custom_emoji_id": "9"}],
        "投稿人：Alice", [{"type": "text_link", "offset": 4, "length": 5, "url": "https://t.me/alice"}],
    )
    assert text == "A🔥\n\n投稿人：Alice"
    assert out[1] == {"type": "text_link", "offset": 9, "length": 5, "url": "https://t.me/alice"}
    # 用 UTF-16 截取验证落点
    u16 = text.encode("utf-16-le")
    assert u16[9 * 2:(9 + 5) * 2].decode("utf-16-le") == "Alice"


def test_join_empty_parts():
    assert ent.join("", [], "sig", [{"type": "bold", "offset": 0, "length": 3}]) == (
        "sig", [{"type": "bold", "offset": 0, "length": 3}])
    assert ent.join("body", [], "", []) == ("body", [])


def test_without_custom_emoji():
    es = [{"type": "custom_emoji", "offset": 0, "length": 2}, {"type": "bold", "offset": 3, "length": 1}]
    assert ent.without_custom_emoji(es) == [{"type": "bold", "offset": 3, "length": 1}]


if __name__ == "__main__":
    tests = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for t in tests:
        t()
        print("PASS ", t.__name__)
    print(f"{len(tests)}/{len(tests)} passed")
