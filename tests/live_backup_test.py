"""每天自动备份数据库：到 BACKUP_TIME 时在数据库旁边的 backups/ 里生成当天的备份，只留 BACKUP_KEEP 份，审核群静音收到提醒。
BACKUP_TIME 设成下一分钟（最多等一分多钟）；失败时的提醒见 test_backup.py。

用法（项目根目录下）：python tests/live_backup_test.py
复用 live_test.py 的模拟 Bot API 服务器。
"""
import asyncio
import os
import sqlite3
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import live_test as lt  # noqa: E402
from live_test import REVIEW, TMP, check, is_send, wait_for  # noqa: E402

TZ = ZoneInfo("Asia/Shanghai")  # 和 live_test.main 里的 TZ 一样
DB = os.path.join(TMP, "bot.db")
BACKUPS = os.path.join(TMP, "backups")
now = datetime.now(TZ)
AT = (now + timedelta(minutes=2 if now.second > 50 else 1)).replace(second=0, microsecond=0)  # 机器人启动要几秒，留出余量


async def scenario():
    await wait_for(lambda e: e["method"] == "setMyCommands", 15, since=0)
    await lt.submit("备份里要有这条", 1)
    wait = (AT - datetime.now(TZ)).total_seconds() + 15
    done = await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, "已自动备份"), timeout=wait, since=0)
    today = f"bot-{AT:%Y-%m-%d}.db"
    check("at BACKUP_TIME → silent message in the review group with the file name",
          done and done["params"].get("disable_notification") in (True, "true") and today in done["params"]["text"],
          done and done["params"])
    files = sorted(os.listdir(BACKUPS))
    check("only the newest BACKUP_KEEP backups are left, other files untouched",
          files == ["bot-2000-01-02.db", today, "keep-me.txt"], files)
    with sqlite3.connect(os.path.join(BACKUPS, today)) as conn:
        found = conn.execute("SELECT items FROM submissions WHERE id=1").fetchone()
    check("the backup holds the current data", found and "备份里要有这条" in found[0], found)


if __name__ == "__main__":
    os.makedirs(BACKUPS)
    for name in ("bot-2000-01-01.db", "bot-2000-01-02.db", "keep-me.txt"):
        open(os.path.join(BACKUPS, name), "w").close()
    asyncio.run(lt.main(scenario, {"DB_PATH": DB, "BACKUP_TIME": f"{AT:%H:%M}", "BACKUP_KEEP": "2",
                                   "REMINDER_INTERVAL_MINUTES": "0"}))
