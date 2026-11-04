"""投稿人私聊里改稿 / 查看留下的命令和回复，每条投稿只留最近一次：下次改稿或查看时删掉上一次的。
- /edit 新内容：命令和“投稿已更新”；只发 /edit：命令、当前文字和提示；原生编辑：只记回复（原消息是投稿内容，不删）
- 失败的（比如审核员改过之后被拒）留着，也不顶掉上一次的
- 投稿原消息永远不删

用法（项目根目录下）：python tests/live_user_cleanup_test.py
复用 live_test.py 的模拟 Bot API 服务器。
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import live_test as lt  # noqa: E402
from live_media_test import photo, user_photo  # noqa: E402
from live_test import REVIEW, USER, check, gm, is_send, log, wait_for  # noqa: E402


def own(mid):
    return {"message_id": mid, "date": lt.now(), "chat": lt.chat(USER)}


def deleted(since):
    """since 之后机器人在投稿人私聊里删掉的消息。"""
    out = []
    for e in log[since:]:
        if not e.get("error") and str(e["params"].get("chat_id")) == str(USER) and e["method"] == "deleteMessages":
            out += [int(i) for i in e["params"]["message_ids"]]
    return out


def replies_to_user(since):
    return [e["result"]["message_id"] for e in log[since:] if is_send(e, "sendMessage", USER)]


async def user_edit(text, mid, marker):
    """投稿人回复自己的投稿发 /edit；返回 (命令消息, 机器人在私聊里发的文字消息)。"""
    n = len(log); cmd = lt.pm(text, reply_to_message=own(mid))
    await wait_for(lambda e: is_send(e, "sendMessage", USER, marker), since=n)
    await asyncio.sleep(0.5)
    return [cmd, *replies_to_user(n)]


async def scenario():
    await wait_for(lambda e: e["method"] == "setMyCommands", 15, since=0)
    n = len(log); mids = [user_photo(f, group="g") for f in ("A", "B")]
    await wait_for(lambda e: any(is_send(e, "sendMessage", USER, p) for p in lt.PROMPTS), since=n)
    lt.cb("u:sign:1", USER, USER)
    ctrl = (await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, lt.CTRL), since=n))["result"]["message_id"]
    await asyncio.sleep(0.5)

    n = len(log); first = await user_edit("/edit 第一次", mids[0], "投稿已更新")
    check("first /edit → command and reply stay", len(first) == 2 and not set(first) & set(deleted(n)), first)

    n = len(log); second = await user_edit("/edit 第二次", mids[0], "投稿已更新")
    check("second /edit → the first command and reply deleted, these stay",
          set(first) <= set(deleted(n)) and not set(second) & set(deleted(n)), (first, deleted(n)))

    n = len(log); view = await user_edit("/edit", mids[0], "复制、修改后")
    check("bare /edit → the previous edit's messages deleted; command, text and hint are this time's",
          set(second) <= set(deleted(n)) and len(view) == 3 and not set(view) & set(deleted(n)), (view, deleted(n)))

    # 原生编辑：原消息不删，只记“已更新”的回复
    n = len(log)
    lt.push(edited_message={"message_id": mids[1], "date": lt.now() - 5, "edit_date": lt.now(), "chat": lt.chat(USER),
                            "from": {"id": USER, "is_bot": False, "first_name": "Alice"}, "media_group_id": "g",
                            "photo": photo("B2"), "caption": "原生编辑"})
    await wait_for(lambda e: is_send(e, "sendMessage", USER, "投稿已更新"), since=n)
    await asyncio.sleep(0.5)
    native = replies_to_user(n)
    check("native edit → the previous view's messages deleted, the edited message itself kept",
          set(view) <= set(deleted(n)) and mids[1] not in deleted(n), deleted(n))

    # 审核员改过之后投稿人再改：被拒，失败的留着，也不顶掉上一次的
    m = len(log); gm("/edit 审核员改的", reply_to=ctrl)
    await wait_for(lambda e: is_send(e, "sendMessage", USER, "审核员修改了你的投稿"), since=m)
    n = len(log); refused = await user_edit("/edit 想再改", mids[0], "审核员已经修改过")
    check("refused /edit → nothing deleted", not deleted(n), deleted(n))
    n = len(log); await user_edit("/edit", mids[0], "含审核员的修改")
    check("bare /edit after that → only the last successful one (native edit reply) is deleted",
          set(native) <= set(deleted(n)) and not set(refused) & set(deleted(n)), (native, refused, deleted(n)))
    check("the submission's own messages were never deleted", not set(mids) & set(deleted(0)), deleted(0))


if __name__ == "__main__":
    asyncio.run(lt.main(scenario, {"REMINDER_INTERVAL_MINUTES": "0"}))
