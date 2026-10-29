"""explicit_reply（bot/core/base.py）的单元测试：审核群开了话题功能时，话题里的隐式回复不算回复。
用法：python tests/test_reply.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aiogram.types import Message  # noqa: E402

from bot.core import explicit_reply  # noqa: E402

GROUP = {"id": -100123, "type": "supergroup", "title": "Review"}


def msg(message_id, reply_to=None, thread=None, **extra):
    data = {"message_id": message_id, "date": 0, "chat": GROUP, "text": "x", **extra}
    if reply_to:
        data["reply_to_message"] = reply_to
    if thread:
        data.update(message_thread_id=thread, is_topic_message=True)
    return Message.model_validate(data)


def test_plain_group():
    target = {"message_id": 10, "date": 0, "chat": GROUP, "text": "preview"}
    assert explicit_reply(msg(11)) is None
    assert explicit_reply(msg(11, reply_to=target)).message_id == 10


def test_forum_group():
    created = {"message_id": 5, "date": 0, "chat": GROUP, "forum_topic_created": {"name": "t", "icon_color": 0}}
    starter = {"message_id": 5, "date": 0, "chat": GROUP, "text": "topic start"}
    target = {"message_id": 10, "date": 0, "chat": GROUP, "text": "preview"}
    assert explicit_reply(msg(11, reply_to=created, thread=5)) is None  # 话题里的普通消息
    assert explicit_reply(msg(11, reply_to=starter, thread=5)) is None  # 隐式回复话题第一条
    assert explicit_reply(msg(11, reply_to=target, thread=5)).message_id == 10  # 在话题里真正回复了一条


if __name__ == "__main__":
    tests = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for fn in tests:
        fn()
        print("PASS ", fn.__name__)
    print(f"\n{len(tests)}/{len(tests)} passed")
