"""投稿防垃圾（bot/spam.py）的单元测试。用法：python tests/test_spam.py"""
import os
import re
import sys
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bot import spam  # noqa: E402
from bot.entities import u16len  # noqa: E402
from bot.render import control_text  # noqa: E402
from bot.spam import SpamRules  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_i18n import _sub  # noqa: E402

CJK = re.compile(r"[一-鿿]")


def text(t, entities=()):
    return {"type": "text", "text": t, "entities": list(entities)}


def url_entity(t, url):
    """t 里 url 那一段的 url entity（偏移按 UTF-16 计）。"""
    i = t.index(url)
    return {"type": "url", "offset": u16len(t[:i]), "length": u16len(url)}


def test_parse():
    r = SpamRules.parse(" 加微信，VX ,, ", 3, "T.me, github.com")
    assert r.keywords == ("加微信", "vx") and r.max_links == 3 and r.whitelist == ("t.me", "github.com")
    assert not SpamRules.parse("", 0, "").enabled
    assert SpamRules.parse("", -5, "").max_links == 0


def test_keywords_case_insensitive_in_text_and_caption():
    r = SpamRules.parse("加微信,vx", 0, "")
    assert spam.check([text("想要资源请加微信")], r) == [{"k": "keyword", "word": "加微信"}]
    assert spam.check([{"type": "photo", "text": "联系 VX123"}], r) == [{"k": "keyword", "word": "vx"}]
    assert spam.check([text("正常投稿")], r) == []


def test_keyword_inside_hidden_link_address():
    r = SpamRules.parse("casino", 0, "")
    item = text("点这里", [{"type": "text_link", "offset": 0, "length": 3, "url": "https://best-casino.example"}])
    assert spam.check([item], r) == [{"k": "keyword", "word": "casino"}]


def test_link_counting_with_emoji_offsets_and_whitelist():
    t = "🔥 看 https://a.example 和 t.me/chan 还有 www.t.me/x"
    ents = [url_entity(t, u) for u in ("https://a.example", "t.me/chan", "www.t.me/x")]
    assert spam.links([text(t, ents)]) == ["https://a.example", "t.me/chan", "www.t.me/x"]
    hidden = {"type": "text_link", "offset": 0, "length": 2, "url": "https://b.example/x"}
    items = [text(t, ents + [hidden])]
    assert spam.check(items, SpamRules.parse("", 1, "t.me")) == [{"k": "links", "n": 2, "max": 1}]
    assert spam.check(items, SpamRules.parse("", 2, "t.me")) == []
    assert spam.check(items, SpamRules.parse("", 3, "")) == [{"k": "links", "n": 4, "max": 3}]


def test_whitelist_does_not_match_lookalike_domains():
    assert spam.whitelisted("https://t.me/x", ("t.me",))
    assert spam.whitelisted("sub.t.me", ("t.me",))
    assert not spam.whitelisted("https://evilt.me/x", ("t.me",))
    assert not spam.whitelisted("https://t.me.evil.example/x", ("t.me",))
    assert not spam.whitelisted("http://[bad", ("t.me",))  # 解析失败按不在白名单


def test_control_text_shows_flags_in_both_languages():
    sub = _sub(spam_flags=[{"k": "keyword", "word": "<vx>"}, {"k": "links", "n": 3, "max": 1}])
    zh = control_text(sub, None, ZoneInfo("Asia/Shanghai"), None, "zh")
    assert "含关键词「&lt;vx&gt;」" in zh and "3 个链接（上限 1）" in zh  # 关键词经过 HTML 转义
    en = control_text(sub, None, ZoneInfo("Asia/Shanghai"), None, "en")
    assert "Possible spam" in en and not CJK.search(en.replace("&lt;vx&gt;", ""))
    assert "spam" not in control_text(_sub(), None, ZoneInfo("Asia/Shanghai"), None, "en").lower()


if __name__ == "__main__":
    tests = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for fn in tests:
        fn()
        print("PASS ", fn.__name__)
    print(f"{len(tests)}/{len(tests)} passed")
