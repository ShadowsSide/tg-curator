"""每天自动备份数据库：放在数据库旁边的 backups/ 目录，每天一份（bot-YYYY-MM-DD.db），只留最近几份。
用 SQLite 的 backup 接口复制（见 db.DB.backup），运行中、WAL 模式下也能得到一致的副本；直接复制文件可能复制到写了一半的状态。
备份和数据库在同一个 Docker 卷里：防误操作、防升级删列，不防整个卷或磁盘坏掉，重要的话再复制到别处。"""
from __future__ import annotations

import os
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .db import DB

NAME = re.compile(r"bot-\d{4}-\d{2}-\d{2}\.db")  # 只清理自己生成的备份，目录里别的文件不动


def backup_dir(db_path: str) -> str:
    return os.path.join(os.path.dirname(os.path.abspath(db_path)), "backups")


async def make_backup(db: DB, db_path: str, keep: int, day: str) -> tuple[str, int]:
    """备份成 backups/bot-<day>.db（同一天再备份就覆盖），删掉超出 keep 份的旧备份。返回 (文件名, 字节数)。"""
    folder = backup_dir(db_path)
    os.makedirs(folder, exist_ok=True)
    name = f"bot-{day}.db"
    path = os.path.join(folder, name)
    await db.backup(path)
    prune(folder, keep)
    return name, os.path.getsize(path)


def prune(folder: str, keep: int) -> list[str]:
    """按日期只留最新的 keep 份，返回删掉的文件名。"""
    names = sorted(n for n in os.listdir(folder) if NAME.fullmatch(n))
    old = names[:-keep] if keep > 0 else []
    for n in old:
        os.remove(os.path.join(folder, n))
    return old


def human_size(n: int) -> str:
    if n >= 1024 * 1024:
        return f"{n / 1024 / 1024:.1f} MB"
    return f"{max(1, round(n / 1024))} KB"
