"""按钮回应对象和兜底中间件（bot/callbacks.py），以及限流中间件不等按钮回应（bot/ratelimit.py）。
用法：python tests/test_callbacks.py"""
import asyncio
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter  # noqa: E402
from aiogram.methods import AnswerCallbackQuery, SendMessage  # noqa: E402

from bot.callbacks import Answer, CallbackAnswerMiddleware  # noqa: E402
from bot.ratelimit import RetryAfterMiddleware  # noqa: E402


class FakeCQ:
    """记录回应和发出的消息。gate：设置后 answer() 要等它放行，用来构造“回应还在路上”的时刻。"""

    def __init__(self, fail=None, reply_fails=False):
        self.answers, self.sent, self.fail, self.gate = [], [], fail, None
        self.data = "x"
        cq = self

        class Msg:
            chat = SimpleNamespace(id=-100)

            async def reply(self, text):
                if reply_fails:
                    raise TelegramBadRequest(method=None, message="message to be replied not found")
                cq.sent.append(("reply", text))

        async def send_message(chat_id, text):
            cq.sent.append(("send", chat_id, text))

        self.message = Msg()
        self.bot = SimpleNamespace(send_message=send_message)

    async def answer(self, text=None, show_alert=False):
        if self.gate:
            await self.gate.wait()
        if self.fail:
            raise self.fail
        self.answers.append((text, show_alert))


def run(coro):
    return asyncio.run(coro)


def test_answers_once():
    async def go():
        cq = FakeCQ()
        a = Answer(cq)
        await a("已切换", False)
        await a("又一次", False)  # 普通提示：丢掉
        await a()
        assert cq.answers == [("已切换", False)] and not cq.sent
    run(go())


def test_later_alert_becomes_a_reply_then_a_message_if_gone():
    async def go():
        cq = FakeCQ()
        a = Answer(cq)
        await a.fallback("处理中…")
        await a("已封禁", False)  # 普通提示丢掉
        await a("已经被别人处理了", True)  # 弹窗改成回复
        assert cq.answers == [("处理中…", False)] and cq.sent == [("reply", "已经被别人处理了")]
        gone = FakeCQ(reply_fails=True)  # 按钮所在的消息已经删掉了：单独发
        b = Answer(gone)
        await b.fallback("处理中…")
        await b("出错了", True)
        assert gone.sent == [("send", -100, "出错了")]
    run(go())


def test_fallback_and_handler_racing_send_one_answer():
    """兜底和处理函数几乎同时回应：第一个请求还在路上（gate 没放行）时第二个到了，也只发一次。"""
    async def go():
        for first in ("fallback", "handler"):
            cq = FakeCQ()
            cq.gate = asyncio.Event()
            a = Answer(cq)
            calls = [a.fallback("处理中…"), a("已发布", False)]
            tasks = [asyncio.create_task(c) for c in (calls if first == "fallback" else calls[::-1])]
            await asyncio.sleep(0)  # 两个都开始了，第一个卡在 gate
            cq.gate.set()
            await asyncio.gather(*tasks)
            assert len(cq.answers) == 1, (first, cq.answers)
    run(go())


def test_failed_answer_is_logged_not_raised():
    async def go():
        for err in (TelegramBadRequest(method=None, message="query is too old"),
                    TelegramRetryAfter(method=None, message="Too Many Requests", retry_after=5)):
            a = Answer(FakeCQ(fail=err))
            await a("x", True)  # 不抛出：交给错误处理的话，它的回应同样会失败
            assert a.answered
    run(go())


def middleware(after=0.05):
    return CallbackAnswerMiddleware(after, lambda cq: "zh")


def test_fast_handler_no_fallback():
    async def go():
        cq = FakeCQ()

        async def handler(event, data):
            await data["answer"]("已切换", False)

        await middleware()(handler, SimpleNamespace(callback_query=cq), {})
        await asyncio.sleep(0.1)  # 计时器取消了，不会再回应
        assert cq.answers == [("已切换", False)]
    run(go())


def test_slow_handler_gets_fallback_then_toast_dropped():
    async def go():
        cq = FakeCQ()
        release = asyncio.Event()

        async def handler(event, data):
            await release.wait()  # 卡住，直到兜底已经回应
            await data["answer"]("已封禁", False)
            await data["answer"]("确认期间被别人处理了", True)

        task = asyncio.create_task(middleware(after=0.01)(handler, SimpleNamespace(callback_query=cq), {}))
        while not cq.answers:
            await asyncio.sleep(0.005)
        release.set()
        await task
        assert cq.answers == [("处理中…", False)], cq.answers
        assert cq.sent == [("reply", "确认期间被别人处理了")]
    run(go())


def test_unanswered_handler_gets_empty_answer_but_errors_are_left_to_error_handler():
    async def go():
        cq = FakeCQ()

        async def silent(event, data):
            return None

        await middleware()(silent, SimpleNamespace(callback_query=cq), {})
        assert cq.answers == [(None, False)]

        cq2, data = FakeCQ(), {}

        async def boom(event, data):
            raise RuntimeError("boom")

        try:
            await middleware()(boom, SimpleNamespace(callback_query=cq2), data)
        except RuntimeError:
            pass
        else:
            raise AssertionError("exception should propagate to the error handler")
        assert cq2.answers == []  # 没有抢先回应：错误处理用同一个回应对象说明出错了
        await data["answer"]("出错了", True)
        assert cq2.answers == [("出错了", True)]
        await asyncio.sleep(0.1)  # 计时器已取消
        assert len(cq2.answers) == 1
    run(go())


def test_non_callback_updates_untouched():
    async def go():
        data = {}

        async def handler(event, data):
            return "ok"

        assert await middleware()(handler, SimpleNamespace(callback_query=None), data) == "ok"
        assert "answer" not in data
    run(go())


def test_ratelimit_doesnt_wait_for_callback_answers():
    async def go():
        mw = RetryAfterMiddleware()
        calls = []

        async def flooded(bot, method):
            calls.append(type(method).__name__)
            raise TelegramRetryAfter(method=method, message="Too Many Requests", retry_after=1)

        loop = asyncio.get_running_loop()
        start = loop.time()
        try:
            await mw(flooded, None, AnswerCallbackQuery(callback_query_id="1"))
        except TelegramRetryAfter:
            pass
        else:
            raise AssertionError("should raise right away")
        assert calls == ["AnswerCallbackQuery"] and loop.time() - start < 0.5

        calls.clear()
        attempts = iter([True, False])

        async def once(bot, method):  # 其他请求照常等待重试
            calls.append(type(method).__name__)
            if next(attempts):
                raise TelegramRetryAfter(method=method, message="Too Many Requests", retry_after=0)
            return "sent"

        assert await mw(once, None, SendMessage(chat_id=1, text="x")) == "sent" and len(calls) == 2
    run(go())


if __name__ == "__main__":
    tests = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for fn in tests:
        fn()
        print("PASS ", fn.__name__)
    print(f"{len(tests)}/{len(tests)} passed")
