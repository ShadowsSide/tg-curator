"""“按钮 + 回复”流程：✏️ 修改、💬 联系投稿人、✏️ 自定义理由、/cancel；改稿后删掉上一份修改预览。

用法（项目根目录下）：python tests/live_prompt_test.py
复用 live_test.py 的模拟 Bot API 服务器。约 15 秒。
"""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import live_test as lt  # noqa: E402
from live_test import ADMIN, REVIEW, USER, buttons, check, is_send, log, submit, wait_for  # noqa: E402

OTHER_ADMIN = 8


def reply_from(user_id, text, reply_to):
    """审核群里某人回复了一条机器人的消息。"""
    lt.push(message={"message_id": 6000 + lt.uid[0], "date": lt.now(), "chat": lt.chat(REVIEW),
                     "from": {"id": user_id, "is_bot": False, "first_name": f"U{user_id}"}, "text": text,
                     "reply_to_message": {"message_id": reply_to, "date": lt.now(), "chat": lt.chat(REVIEW),
                                          "from": {"id": 1, "is_bot": True, "first_name": "TestBot"}}})


def is_prompt(e, contains):
    return is_send(e, "sendMessage", REVIEW, contains) and "force_reply" in json.dumps(e["params"])


def deleted(since):
    """since 之后被删掉的审核群消息。"""
    return {int(i) for e in log[since:] if e["method"] == "deleteMessages"
            and str(e["params"].get("chat_id")) == str(REVIEW) for i in json.loads(str(e["params"]["message_ids"]))}


async def nothing(pred, since, wait=1.5):
    await asyncio.sleep(wait)
    return not any(pred(e) for e in log[since:])


async def edit_via_button(ctrl_id, sid, text):
    """点 ✏️ 修改 → 回复提示。返回 (当前内容, 提示, 新预览, 回执)。"""
    n = len(log); lt.cb(f"r:edit:{sid}:0", REVIEW, ADMIN, message_id=ctrl_id)
    prompt = await wait_for(lambda e: is_prompt(e, "修改后的正文"), since=n)
    echo = next((e for e in log[n:] if is_send(e, "sendMessage", REVIEW) and e is not prompt), None)
    n = len(log); lt.gm(text, reply_to=prompt["result"]["message_id"])
    done = await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, "已修改"), since=n)
    preview = next((e for e in log[n:] if is_send(e, "sendMessage", REVIEW, text) and e is not done), None)
    return echo, prompt, preview, done


async def scenario():
    await wait_for(lambda e: e["method"] == "setMyCommands", 15, since=0)
    lt.MOCK["admins"].add(OTHER_ADMIN)
    c1 = await submit("提示测试 原文", 1)
    c2 = await submit("提示测试 二", 2)
    ctrl1 = c1["result"]["message_id"]
    first_preview = c1["params"]["reply_parameters"]["message_id"]

    # 1. 控制消息上有 ✏️ 修改、💬 联系投稿人
    b = buttons(c1)
    check("control message has Edit + Message submitter buttons",
          b.get("✏️ 修改") == "r:edit:1:0" and b.get("💬 联系投稿人") == "r:msg:1:0", b)

    # 2. 点“修改”：先发当前内容，再发强制回复的提示；别的审核员回复提示不算数
    n0 = len(log); lt.cb("r:edit:1:0", REVIEW, ADMIN, message_id=ctrl1)
    prompt = await wait_for(lambda e: is_prompt(e, "修改后的正文"), since=n0)
    echo = next((e for e in log[n0:] if is_send(e, "sendMessage", REVIEW, "提示测试 原文")), None)
    check("Edit → current text echoed, then a ForceReply prompt under the control message",
          prompt and echo and prompt["params"]["reply_parameters"]["message_id"] == ctrl1)
    n = len(log); reply_from(OTHER_ADMIN, "别人改的", prompt["result"]["message_id"])
    check("another reviewer's reply to the prompt is ignored",
          await nothing(lambda e: is_send(e, "sendMessage", REVIEW, "已修改"), n))

    # 3. 点按钮的人回复：改稿、发新预览、删掉提示和当前内容
    n = len(log); lt.gm("提示测试 改一", reply_to=prompt["result"]["message_id"])
    done = await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, "已修改"), since=n)
    preview1 = next((e for e in log[n:] if is_send(e, "sendMessage", REVIEW, "提示测试 改一") and e is not done), None)
    await wait_for(lambda e: e["method"] == "deleteMessages", since=n)
    check("reply → edited, new preview posted, prompt + echo deleted",
          done and preview1 and {prompt["result"]["message_id"], echo["result"]["message_id"]} <= deleted(n),
          deleted(n))
    check("first edit deletes no preview (the original stays)", first_preview not in deleted(n0))

    # 4. 再改一次：删掉上一份修改预览，最初的预览保留；被删的预览不再能定位投稿
    n = len(log)
    _, _, preview2, done2 = await edit_via_button(ctrl1, 1, "提示测试 改二")
    await asyncio.sleep(0.5)
    gone = deleted(n)
    check("second edit → previous edited preview deleted, original preview kept",
          preview2 and done2 and preview1["result"]["message_id"] in gone and first_preview not in gone, gone)
    n = len(log); lt.gm("/no", reply_to=preview1["result"]["message_id"])
    told = await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, "回复"), since=n)
    check("deleted preview no longer maps to the submission", told and not any(
        is_send(e, "sendMessage", USER, "未通过") for e in log[n:]), told and told["params"]["text"])

    # 5. 用过的提示再回复：不再生效
    n = len(log); lt.gm("提示测试 改三", reply_to=prompt["result"]["message_id"])
    check("a finished prompt doesn't accept replies",
          await nothing(lambda e: is_send(e, "sendMessage", REVIEW, "已修改"), n))

    # 6. /cancel：回复提示发送只放弃这一个；别人的提示放弃不了；直接发送放弃自己所有的提示
    n = len(log); lt.cb("r:edit:1:0", REVIEW, ADMIN, message_id=ctrl1)
    p = await wait_for(lambda e: is_prompt(e, "/cancel"), since=n)
    n = len(log); reply_from(OTHER_ADMIN, "/cancel", p["result"]["message_id"])
    told = await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, "没有等你回复"), since=n)
    check("/cancel on someone else's prompt → not cancelled", told and p["result"]["message_id"] not in deleted(n))
    n = len(log); lt.gm("/cancel", reply_to=p["result"]["message_id"])
    told = await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, "已取消"), since=n)
    await wait_for(lambda e: e["method"] == "deleteMessages", since=n)
    check("/cancel as a reply → that prompt deleted, nothing edited",
          told and p["result"]["message_id"] in deleted(n)
          and not any(is_send(e, "sendMessage", REVIEW, "已修改") for e in log[n:]))
    n = len(log)
    lt.cb("r:edit:1:0", REVIEW, ADMIN, message_id=ctrl1)
    p1 = await wait_for(lambda e: is_prompt(e, "修改后的正文"), since=n)
    lt.cb("r:msg:1:0", REVIEW, ADMIN, message_id=ctrl1)
    p2 = await wait_for(lambda e: is_prompt(e, "转给投稿人"), since=n)
    n = len(log); lt.gm("/cancel")
    await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, "已取消"), since=n)
    await asyncio.sleep(0.5)
    check("/cancel on its own → all my open prompts dropped",
          {p1["result"]["message_id"], p2["result"]["message_id"]} <= deleted(n), deleted(n))
    n = len(log); lt.gm("/cancel")
    check("/cancel with nothing open → told so",
          await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, "没有等你回复"), since=n))

    # 7. 文字太长：提示保留，可以重新回复
    n = len(log); lt.cb("r:edit:1:0", REVIEW, ADMIN, message_id=ctrl1)
    p = await wait_for(lambda e: is_prompt(e, "修改后的正文"), since=n)
    n = len(log); lt.gm("长" * 5000, reply_to=p["result"]["message_id"])
    err = await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, "4096"), since=n)
    n = len(log); lt.gm("提示测试 改四", reply_to=p["result"]["message_id"])
    done = await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, "已修改"), since=n)
    check("too long → error, prompt kept; the next reply works", err and done)

    # 8. 联系投稿人：回复的内容以“审核员”身份转给投稿人
    n = len(log); lt.cb("r:msg:1:0", REVIEW, ADMIN, message_id=ctrl1)
    p = await wait_for(lambda e: is_prompt(e, "转给投稿人"), since=n)
    n = len(log); lt.gm("请补充来源", reply_to=p["result"]["message_id"])
    to_user = await wait_for(lambda e: is_send(e, "sendMessage", USER, "请补充来源"), since=n)
    ok = await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, "已发送给投稿人"), since=n)
    check("Message submitter → relayed as “Reviewer”", to_user and ok and "审核员" in to_user["params"]["text"])

    # 9. 自定义理由：拒绝 → ✏️ 自定义理由 → 回复理由，立即拒绝，不再确认
    ctrl2 = c2["result"]["message_id"]
    n = len(log); lt.cb("r:reject:2:0", REVIEW, ADMIN, message_id=ctrl2)
    await wait_for(lambda e: e["method"] == "editMessageReplyMarkup", since=n)
    n = len(log); lt.cb("r:creason:2:0", REVIEW, ADMIN, message_id=ctrl2)
    p = await wait_for(lambda e: is_prompt(e, "拒绝理由"), since=n)
    restored = await wait_for(lambda e: e["method"] == "editMessageText"
                              and str(e["params"].get("message_id")) == str(ctrl2), since=n)
    check("Custom reason → reason panel folded back, prompt sent", p and restored)
    n = len(log); lt.gm("图片和文字对不上", reply_to=p["result"]["message_id"])
    told = await wait_for(lambda e: is_send(e, "sendMessage", USER, "图片和文字对不上"), since=n)
    ok = await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, "已拒绝"), since=n)
    panel = [e for e in log[n:] if e["method"] == "editMessageReplyMarkup"]
    check("reply with the reason → rejected at once, submitter told the reason", told and ok and not panel)


if __name__ == "__main__":
    asyncio.run(lt.main(scenario))
