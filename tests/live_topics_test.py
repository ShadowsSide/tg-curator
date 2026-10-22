"""话题模式端到端测试：审核群和投稿人私聊都按投稿分话题（REVIEW_TOPICS / USER_TOPICS）。

用法（项目根目录下）：python tests/live_topics_test.py
复用 live_test.py 的模拟 Bot API 服务器，开启话题相关能力后运行真实的机器人进程。约 10 秒。
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import live_test as lt  # noqa: E402
from live_test import ADMIN, CHANNEL, REVIEW, USER, check, is_send, log, now, wait_for  # noqa: E402


def topic_msg(chat_id, thread, text, who, **extra):
    """话题里的消息：带 message_thread_id，并隐式回复话题的第一条（创建话题的服务消息）。"""
    lt.uid[0] += 1
    sender = {"id": who, "is_bot": False, "first_name": "Admin" if who == ADMIN else "Alice",
              "language_code": "zh-hans"}
    d = {"message_id": 20000 + lt.uid[0], "date": now(), "chat": lt.chat(chat_id), "from": sender,
         "message_thread_id": thread, "is_topic_message": True,
         "reply_to_message": {"message_id": thread, "date": now(), "chat": lt.chat(chat_id),
                              "forum_topic_created": {"name": "t", "icon_color": 7322096}}}
    if text is not None:
        d["text"] = text
        if text.startswith("/"):
            d["entities"] = [{"type": "bot_command", "offset": 0, "length": len(text.split()[0])}]
    d.update(extra)
    lt.push(message=d)


def topic_cb(data, chat_id, from_id, message_id, thread):
    lt.push(callback_query={
        "id": str(lt.uid[0]), "chat_instance": "x", "data": data,
        "from": {"id": from_id, "is_bot": False, "first_name": "Admin" if from_id == ADMIN else "Alice",
                 "language_code": "zh-hans"},
        "message": {"message_id": message_id, "date": now(), "chat": lt.chat(chat_id),
                    "message_thread_id": thread, "is_topic_message": True}})


def is_call(e, method, chat_id=None):
    return e["method"].lower() == method.lower() and (chat_id is None or str(e["params"].get("chat_id")) == str(chat_id))


async def scenario():
    e = await wait_for(lambda e: e["method"] == "setMyCommands", 15, since=0)
    check("bot started with topic mode", e)

    # ---------- 1. 在私聊主界面投稿 → 私聊里新建话题，内容复制进去，提示在话题里 ----------
    n = len(log); lt.pm("话题模式第一条")
    utopic = await wait_for(lambda e: is_call(e, "createForumTopic", USER), since=n)
    copied = await wait_for(lambda e: is_call(e, "copyMessages", USER), since=n)
    prompt = await wait_for(lambda e: is_send(e, "sendMessage", USER, "请选择投稿方式"), since=n)
    t_u1 = utopic and utopic["result"]["message_thread_id"]
    check("private chat: new topic created, content copied in, prompt inside the topic",
          utopic and utopic["params"]["name"] == "📝 话题模式第一条"
          and copied and int(copied["params"]["message_thread_id"]) == t_u1
          and prompt and int(prompt["params"]["message_thread_id"]) == t_u1,
          utopic and utopic["params"]["name"])

    # ---------- 2. 提交 → 审核群新建话题，预览和控制消息都在话题里 ----------
    n = len(log); topic_cb("u:sign:1", USER, USER, prompt["result"]["message_id"], t_u1)
    rtopic = await wait_for(lambda e: is_call(e, "createForumTopic", REVIEW), since=n)
    t_r1 = rtopic and rtopic["result"]["message_thread_id"]
    ctrl1 = await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, "新投稿"), since=n)
    pv1 = await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, "话题模式第一条"), since=n)
    check("review group: one topic per submission, preview + control inside it",
          rtopic and rtopic["params"]["name"] == "⏳ Alice · 文字"
          and ctrl1 and int(ctrl1["params"]["message_thread_id"]) == t_r1
          and pv1 and int(pv1["params"]["message_thread_id"]) == t_r1, rtopic and rtopic["params"]["name"])
    ren = await wait_for(lambda e: is_call(e, "editForumTopic", USER) and e["params"].get("name", "").startswith("⏳"), since=n)
    check("submitter's topic renamed to pending", ren)

    # ---------- 3. 在审核话题里直接 /no（不回复任何消息）→ 拒绝；双方话题改名，审核话题关闭 ----------
    n = len(log); topic_msg(REVIEW, t_r1, "/no 主题不符", ADMIN)
    note = await wait_for(lambda e: is_send(e, "sendMessage", USER, "理由：主题不符"), since=n)
    check("/no inside the review topic works without replying; user notified inside their topic",
          note and int(note["params"].get("message_thread_id") or 0) == t_u1)
    r_ren = await wait_for(lambda e: is_call(e, "editForumTopic", REVIEW) and e["params"].get("name", "").startswith("❌"), since=n)
    r_close = await wait_for(lambda e: is_call(e, "closeForumTopic", REVIEW) and int(e["params"]["message_thread_id"]) == t_r1, since=n)
    u_ren = await wait_for(lambda e: is_call(e, "editForumTopic", USER) and e["params"].get("name", "").startswith("❌"), since=n)
    check("rejected: review topic renamed ❌ and closed; user topic renamed ❌", r_ren and r_close and u_ren)

    # ---------- 4. 投稿人在自己新建的空话题里投稿 → 直接用这个话题，不再新建 ----------
    own = 9000
    n = len(log); topic_msg(USER, own, "我自己开的话题里投稿", USER)
    p2 = await wait_for(lambda e: is_send(e, "sendMessage", USER, "请选择投稿方式"), since=n)
    reuse = await wait_for(lambda e: is_call(e, "editForumTopic", USER) and int(e["params"]["message_thread_id"]) == own, since=n)
    created = await wait_for(lambda e: is_call(e, "createForumTopic", USER), timeout=0.5, since=n)
    check("user's own empty topic is reused (renamed, no new topic, prompt there)",
          p2 and int(p2["params"].get("message_thread_id") or 0) == own and reuse and not created)

    n = len(log); topic_cb("u:anon:2", USER, USER, p2["result"]["message_id"], own)
    rtopic2 = await wait_for(lambda e: is_call(e, "createForumTopic", REVIEW), since=n)
    t_r2 = rtopic2 and rtopic2["result"]["message_thread_id"]
    ctrl2 = await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, "新投稿"), since=n)
    check("anonymous submission marked in review topic name", rtopic2 and "（匿名）" not in rtopic2["params"]["name"]
          and "(匿名)" in rtopic2["params"]["name"], rtopic2 and rtopic2["params"]["name"])

    # ---------- 5. 投稿人：话题里也必须回复才生效；管理员在审核话题里可直接 /edit ----------
    n = len(log); topic_msg(USER, own, "/edit 没回复", USER)
    e = await wait_for(lambda e: is_send(e, "sendMessage", USER, "请<b>回复</b>"), since=n)
    changed = await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, "没回复"), timeout=0.5, since=n)
    check("submitter /edit inside their topic without reply → not applied, asked to reply", e and not changed)
    n = len(log)
    topic_msg(USER, own, "/edit 投稿人改过的内容", USER, reply_to_message={
        "message_id": p2["result"]["message_id"], "date": now(), "chat": lt.chat(USER),
        "from": {"id": 1, "is_bot": True, "first_name": "TestBot"}})
    ok = await wait_for(lambda e: is_send(e, "sendMessage", USER, "投稿已更新"), since=n)
    pv = await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, "投稿人改过的内容"), since=n)
    check("submitter /edit replying inside their topic → new preview in the review topic",
          ok and pv and int(pv["params"]["message_thread_id"]) == t_r2)
    n = len(log); topic_msg(REVIEW, t_r2, "/edit 管理员定稿", ADMIN)
    pv = await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, "管理员定稿"), since=n)
    check("admin /edit inside the review topic (no reply)", pv and int(pv["params"]["message_thread_id"]) == t_r2)

    # ---------- 5b. /msg 沟通走各自的话题 ----------
    n = len(log); topic_msg(REVIEW, t_r2, "/msg 话题里的提问", ADMIN)
    q = await wait_for(lambda e: is_send(e, "sendMessage", USER, "话题里的提问"), since=n)
    check("reviewer /msg inside the review topic → arrives in the submitter's topic",
          q and int(q["params"].get("message_thread_id") or 0) == own)
    n = len(log)
    topic_msg(USER, own, "/msg 话题里的回答", USER, reply_to_message={
        "message_id": q["result"]["message_id"], "date": now(), "chat": lt.chat(USER),
        "from": {"id": 1, "is_bot": True, "first_name": "TestBot"}})
    a = await wait_for(lambda e: is_send(e, "sendMessage", REVIEW, "话题里的回答"), since=n)
    check("submitter /msg reply → arrives in the review topic", a and int(a["params"]["message_thread_id"]) == t_r2)

    # ---------- 6. 在话题里点发布 → 发到频道，通知进投稿人话题，审核话题 ✅ 并关闭 ----------
    n = len(log); topic_cb("r:pub:2:0", REVIEW, ADMIN, ctrl2["result"]["message_id"], t_r2)
    post = await wait_for(lambda e: is_send(e, "sendMessage", CHANNEL, "管理员定稿"), since=n)
    note = await wait_for(lambda e: is_send(e, "sendMessage", USER, "已发布到频道"), since=n)
    done = await wait_for(lambda e: is_call(e, "editForumTopic", REVIEW) and e["params"].get("name", "").startswith("✅"), since=n)
    closed = await wait_for(lambda e: is_call(e, "closeForumTopic", REVIEW) and int(e["params"]["message_thread_id"]) == t_r2, since=n)
    check("published: channel post has no topic params; user notified in their topic; review topic ✅ + closed",
          post and "message_thread_id" not in post["params"] and note
          and int(note["params"].get("message_thread_id") or 0) == own and done and closed)

    # ---------- 7. 同一状态不重复改名（避免话题里刷“已修改名称”服务消息） ----------
    renames = [e for e in log if is_call(e, "editForumTopic", REVIEW) and int(e["params"]["message_thread_id"]) == t_r2]
    check("review topic renamed only on status changes", len(renames) == 1, [e["params"]["name"] for e in renames])


if __name__ == "__main__":
    lt.MOCK.update(review_is_forum=True, bot_topics=True)
    asyncio.run(lt.main(scenario, {"REVIEW_TOPICS": "true", "USER_TOPICS": "true", "REMINDER_INTERVAL_MINUTES": "0"}))
