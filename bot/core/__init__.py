"""业务核心：投稿 → 审核 → 发布/定时 → 通知，以及后台调度和审核统计。

按功能拆在几个模块里，组合成一个 Core；处理函数只通过 Core 的方法访问业务和数据。
"""
from __future__ import annotations

from .base import NO_PREVIEW, CoreBase, explicit_reply, mention, topic_of
from .editing import EditingMixin
from .messaging import MessagingMixin
from .review import ReviewMixin
from .scheduler import SchedulerMixin
from .stats import StatsMixin
from .submissions import SubmissionsMixin
from .topics import TopicsMixin

__all__ = ["Core", "NO_PREVIEW", "explicit_reply", "mention", "topic_of"]


class Core(SubmissionsMixin, EditingMixin, ReviewMixin, MessagingMixin, TopicsMixin, StatsMixin, SchedulerMixin,
           CoreBase):
    pass
