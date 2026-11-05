"""容器健康检查：Dockerfile 的 HEALTHCHECK 运行 python -m bot.health，退出码非 0 时容器显示 unhealthy，
输出的那行说明在 docker inspect 里能看到。

- 配置错误：机器人写下 CONFIG_ERROR_FILE 后待机（见 __main__.wait_for_fix），这里输出它的内容
- 卡住：机器人运行时后台循环定时更新 HEARTBEAT_FILE；太久没更新说明事件循环卡住或后台循环停了
- 心跳文件还不存在：机器人还在启动，算正常（启动时会先写一次，见 __main__.main）
"""
from __future__ import annotations

import os
import sys
import time

from .i18n import LANGS, t

CONFIG_ERROR_FILE = os.getenv("CONFIG_ERROR_FILE", "/tmp/config-error")
HEARTBEAT_FILE = os.getenv("HEARTBEAT_FILE", "/tmp/heartbeat")
# 后台循环每 SCHEDULER_TICK（15 秒）一轮；一轮里发布定时投稿、被 Telegram 限流时会久一些，所以留足余量
HEARTBEAT_MAX_AGE = 300  # 秒


def log_lang() -> str:
    """日志和健康检查用的语言（LANGUAGE），配置还没读或写错时用中文。"""
    lang = os.getenv("LANGUAGE", "").strip().lower()
    return lang if lang in LANGS else "zh"


def check(config_error: str = CONFIG_ERROR_FILE, heartbeat: str = HEARTBEAT_FILE,
          now: float | None = None) -> str | None:
    """有问题时返回说明，正常返回 None。"""
    try:
        with open(config_error, encoding="utf-8") as f:
            return f.read().strip() or "config error"
    except FileNotFoundError:
        pass
    try:
        age = (time.time() if now is None else now) - os.path.getmtime(heartbeat)
    except FileNotFoundError:
        return None
    if age > HEARTBEAT_MAX_AGE:
        return t(log_lang(), "health_stale", age=int(age))
    return None


def main() -> int:
    problem = check()
    if problem:
        print(problem)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
