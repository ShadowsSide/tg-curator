# tg-submit-bot

[![docker](https://github.com/ShadowsSide/tg-submit-bot/actions/workflows/docker.yml/badge.svg)](https://github.com/ShadowsSide/tg-submit-bot/actions/workflows/docker.yml)
[![license](https://img.shields.io/github/license/ShadowsSide/tg-submit-bot)](LICENSE)
![python](https://img.shields.io/badge/python-3.12-blue)
![platform](https://img.shields.io/badge/platform-linux%2Famd64%20%7C%20linux%2Farm64-lightgrey)

**简体中文** | [English](README.en.md)

一个 Telegram 频道投稿机器人：用户私聊投稿，管理员在审核群里审核，通过后发布到频道。

基于 Python 3.12 + [aiogram 3](https://github.com/aiogram/aiogram) + SQLite，使用 Docker Compose 一键部署。采用长轮询方式运行，**不需要公网 IP，也不需要 HTTPS**。

## 功能

**投稿**
- 支持文字、图片、视频、GIF、文件、音频、语音，多图/多视频相册会自动合并成一条投稿
- 投稿人可以选择**署名**或**匿名**；无论选哪种，管理员都能看到真实投稿人
- **格式原样保留**：超链接、粗体、引用、剧透文字、代码、日期时间、emoji 等格式全部保留，发布到频道时不会走样
- 投稿人在审核结果出来之前可以**修改稿件**：直接用 Telegram 自带的“编辑”，或者**回复**自己的投稿发送 `/edit`
- **防垃圾**（可选）：关键词黑名单、链接数量上限（白名单域名不计）、新用户投稿冷却。命中时默认在控制消息上标记 ⚠️ 疑似垃圾，交给审核员判断；也可以直接拦下

**审核员与投稿人沟通**
- 审核员点控制消息上的 **💬 联系投稿人**（或用 `/msg 内容`），投稿人直接回复审核员的消息即可（或用 `/msg`），由机器人转达。投稿人看到的发送者统一是“审核员”，双方都看不到对方账号
- 文字格式原样转达，也可以带一张图片或一个文件；往来记录会保存，控制消息上显示沟通条数
- 审核中随时可以沟通；发布或拒绝后 3 天内也可以（`MSG_WINDOW_DAYS`）；被封禁的用户不能再发

**审核**
- 每条投稿在审核群里有一份预览（和频道里的最终效果一致），下面是一条带彩色按钮的控制消息
- 立即发布 · 定时发布 · 拒绝 · 封禁投稿人
- 发布选项：🙈 **剧透遮罩**、🔕 **静音发送**
- 拒绝时可以一键选择常用理由（`REJECT_TEMPLATES`）
- `/edit` 修改稿件，`/no 理由` 拒绝，`/ban 理由` 封禁。封禁时会自动拒绝该用户所有未处理的来稿
- 防止误触：立即发布、拒绝、封禁需要再点一次确认
- 防止重复操作：两个管理员同时点“发布”，也只会发布一次
- **只响应私聊和审核群**：在其他群里不会回复任何消息；被拉进其他群组或频道时会自动退出。发布频道和它的关联群组（评论区）在白名单里，不会退出

**定时与统计**
- 定时发布支持快捷按钮和自定义时间（`20:30`、`10-20 09:00`、`+2h`……），定时任务保存在数据库里，重启后不会丢失
- 定时在审核群发送统计提醒，每次审核后自动刷新：
  ```
  接受 3 拒绝 1 待审核 4
  通过率: 75.00% 审核率: 50.00%
  #审核统计 [更新于 16:03:10]
  ```
- 投稿人活跃度排行、单个投稿人统计；投稿人可以用 `/me` 查看自己的统计

**中英文界面**
- 投稿人看到的语言跟随其 Telegram 客户端（中文客户端显示中文，其他显示英文）；审核群、频道落款和统计提醒使用 `LANGUAGE` 配置的语言
- 命令菜单也按客户端语言显示

**部署**
- 提供 `linux/amd64` 和 `linux/arm64` 多架构镜像，VPS、ARM 服务器、树莓派都能用
- 支持代理（`http://`、`socks5://`）和自建 Bot API 服务器

## 工作流程

```
用户私聊发内容 ─► 选择 署名/匿名 ─► 审核群：预览 + 控制消息
                                         │
         ┌──────────────┬────────────────┼────────────────┬──────────────┐
   剧透 / 静音开关    ✏️ 修改          ✅ 立即发布       ⏰ 定时发布     ❌ 拒绝 / 🚫 封禁
                                         │                │                │
                                         ▼                ▼                ▼
                                  频道 + 通知投稿人   到点发布 + 通知    通知投稿人（附理由）
```

## 快速开始

### 1. 准备 Telegram

1. 在 [@BotFather](https://t.me/BotFather) 创建机器人，拿到 token。隐私模式保持默认开启即可
2. 把机器人设为**频道**管理员，并给它“发布消息”权限
3. 建一个**审核群**，把机器人拉进去，普通成员即可。默认只有审核群的**管理员和群主**能审核（`REVIEWERS`），其他成员点按钮或发命令会提示没有权限
4. 获取频道 ID 和审核群 ID（都是 `-100` 开头的数字）。可以借助 [@RawDataBot](https://t.me/RawDataBot) 这类机器人，或者在群里发一条消息后访问 `https://api.telegram.org/bot<token>/getUpdates` 查看。频道也可以直接填 `@用户名`

### 2. 部署

```bash
git clone https://github.com/ShadowsSide/tg-submit-bot.git
cd tg-submit-bot
cp .env.example .env        # 填写 BOT_TOKEN、CHANNEL_ID、REVIEW_CHAT_ID
docker compose up -d --build
docker compose logs -f
```

如果不想在服务器上构建，可以直接使用预构建镜像：在 `.env` 里加上

```bash
IMAGE=ghcr.io/shadowsside/tg-submit-bot:latest
```

然后执行：

```bash
docker compose pull && docker compose up -d --no-build
```

镜像标签：`latest` 对应 main 分支的最新版本；`vX.Y.Z` 是发布版本；`sha-xxxxxxx` 对应某次具体构建，方便回滚。

### 3. 更新与备份

```bash
git pull && docker compose up -d --build                         # 更新（自己构建）
docker compose pull && docker compose up -d --no-build           # 更新（预构建镜像）
docker compose cp bot:/app/data/bot.db ./backup-$(date +%F).db   # 备份数据库
```

数据库保存在 Docker 卷 `bot-data` 中，升级时会自动迁移表结构。

## 配置

所有配置都通过 `.env` 设置，完整示例见 [`.env.example`](.env.example)。

### 必填

不填无法启动。

| 变量 | 默认值 | 说明 |
|---|---|---|
| `BOT_TOKEN` | — | 机器人 token |
| `CHANNEL_ID` | — | 发布频道，填 `@username` 或 `-100…` |
| `REVIEW_CHAT_ID` | — | 审核群 ID |

### 常用

大多数部署会按需调整的选项。

| 变量 | 默认值 | 说明 |
|---|---|---|
| `LANGUAGE` | `zh` | 审核群、频道落款、统计提醒的语言：`zh` / `en` |
| `USER_LANGUAGE` | `auto` | 投稿人看到的语言：`auto` 跟随其客户端，或固定为 `zh` / `en` |
| `REVIEWERS` | `admins` | 谁可以审核：`admins` 审核群管理员和群主；`all` 审核群所有成员；也可以写用户 ID，可组合，如 `admins,123456`。机器人不算审核员 |
| `TZ` | `Asia/Shanghai` | 时区，影响定时发布和“今天”的统计范围 |
| `SIGN_TEMPLATE` | 随 `LANGUAGE`：`投稿人：{name}` / `Submitted by {name}` | 署名落款，`{name}` 会替换成投稿人链接 |
| `ANON_SIGNATURE` | 随 `LANGUAGE`：`匿名投稿` / `Anonymous submission` | 匿名落款，设为空则不加落款 |
| `REJECT_TEMPLATES` | 随 `LANGUAGE` 的 4 条默认理由 | 点“拒绝”后可选的理由，用 `\|` 分隔，如 `重复投稿\|广告`；设为空则不显示理由面板 |
| `MAX_PENDING_PER_USER` | `5` | 每人同时最多保留几条未处理投稿 |
| `SCHEDULE_PRESETS` | `09:00,12:00,18:00,21:00` | 定时面板里的快捷时间点 |
| `DEFAULT_SILENT` | `false` | 新投稿是否默认静音发送 |
| `REMINDER_INTERVAL_MINUTES` | `60` | 审核统计提醒的间隔（分钟），按整点对齐；`0` 表示关闭 |
| `REMINDER_QUIET_HOURS` | — | 免打扰时段，例如 `0-8` |
| `PROXY` | — | 代理，例如 `socks5://host:port` |
| `IMAGE` | `tg-submit-bot:latest` | 使用预构建镜像时填写 |

> 在 Docker 里运行时，`127.0.0.1` 指的是容器自己。要使用宿主机上的代理，请填宿主机 IP，或者 `host.docker.internal`（Docker Desktop）。

### 高级

防垃圾、沟通期限、统计口径等，一般保持默认即可。

| 变量 | 默认值 | 说明 |
|---|---|---|
| `SPAM_KEYWORDS` | 空 | 关键词黑名单，逗号分隔，不区分大小写；同时检查文字和链接地址 |
| `MAX_LINKS` | `0` | 每条投稿最多几个链接，`0` 不限；`LINK_WHITELIST` 里的域名不计 |
| `LINK_WHITELIST` | 空 | 不计入链接上限的域名，逗号分隔，子域名也算，如 `t.me,github.com` |
| `SPAM_ACTION` | `flag` | 命中关键词或链接上限时：`flag` 照常提交并在控制消息上标记；`block` 拦下，投稿人修改后可重新提交 |
| `NEW_USER_COOLDOWN_MINUTES` | `0` | 还没有稿件发布过的投稿人，两次提交之间至少间隔几分钟；`0` 不限 |
| `MSG_WINDOW_DAYS` | `3` | `/msg` 沟通：审核结束（发布或拒绝）后还能继续沟通的天数；审核中始终可以 |
| `LEAVE_UNKNOWN_CHATS` | `true` | 被拉进其他群组或频道时自动退出；设为 `false` 则留在群里但不响应。发布频道及其关联群组（启动时自动识别）始终保留 |
| `ALBUM_DELAY` | `1.5` | 收集相册时等待的秒数 |
| `REMINDER_ONLY_WHEN_PENDING` | `true` | 只在有待审核投稿时提醒 |
| `STATS_SCOPE` | `today` | 统计范围：`today` 时接受/拒绝只统计当天的；`all` 统计全部历史 |
| `TELEGRAM_API_URL` | — | 自建 Bot API 服务器地址，可以突破官方 API 的 20MB/50MB 文件限制 |

## 使用

### 投稿人（私聊机器人）

| 操作 | 说明 |
|---|---|
| 直接发送内容 | 开始投稿，然后选择署名或匿名。上次选的那个会标“（上次）”并排在前面，仍然要点一下 |
| 用 Telegram 的“编辑”修改原消息 | 在审核结果出来之前修改投稿，可以改文字、改格式，也可以换图 |
| 回复自己的投稿发图片 / 视频 | 选择面板上会多一个 **➕ 加到这条投稿**，点它就把新发的图片加进那条投稿；也可以照常作为新投稿。只能加到草稿或待审核的投稿里 |
| 🗑 删除图片 / 视频 | 草稿或待审核的投稿有 2 个以上图片视频时，提示消息上有这个按钮，点开选要删的那一个。审核开始后（定时、发布、拒绝）不能再改 |
| `/edit 新内容` | **必须回复**自己的投稿（或机器人关于它的提示消息）才生效，不回复不会修改任何投稿 |
| `/edit`（回复投稿） | 查看当前内容（带格式），方便复制后修改 |
| 直接回复审核员的消息 | 当作留言转给审核员（文字、图片、文件都可以），不用写 `/msg` |
| `/msg 内容` | 给审核员留言：**回复**审核员的消息或自己的投稿发送 |
| `/me` | 查看自己的投稿统计 |

### 管理员（审核群）

控制消息上的按钮：**✅ 立即发布**、**⏰ 定时发布**、**❌ 拒绝**、**🚫 封禁投稿人**、**✏️ 修改**、**💬 联系投稿人**、**🖼 媒体**，以及 **🙈 剧透**、**🔕 静音** 开关。

**✏️ 修改**、**💬 联系投稿人**、拒绝理由面板上的 **✏️ 自定义理由** 和定时面板上的 **✏️ 自定义时间**，点了之后机器人会发一条“请回复本消息……”，直接回复它就行，不用记命令：
- 只有点按钮的那个人的回复算数（匿名管理员除外）；发送 `/cancel` 放弃（回复提示发送只放弃这一个，直接发送放弃你所有等待中的提示）
- **修改**会先把当前内容（带格式）发出来，方便复制后改；改完后提示和这条内容会自动删掉
- **自定义理由**发出后立即拒绝，不再确认
- 提示存在数据库里，机器人重启后照样能回复；24 小时没回复的提示会自动删掉

**🖼 媒体**（只在待审核时有）打开媒体面板：**➕ 添加图片 / 视频**（可以一次回复一组相册）、**🔁 换第 N 个**、**🗑 删第 N 个**（要确认；只剩一个时不能删）。只支持图片和视频，一条投稿最多 10 个；含文件、GIF、音频的投稿不能用。纯文字投稿也能加图，原来的文字会变成图片的说明文字（见下面的“已知限制与风险”）。

每次修改都会发一份新的预览。审核群里只保留最初的预览和最新一份修改预览，更早的修改预览会自动删掉（超过 48 小时的消息 Telegram 不允许机器人删除，会保留）。

为防止误触，**立即发布、拒绝、封禁**点了之后会先换成“确认 / 返回”按钮，再点一次确认才执行。定时发布、重试和 `/no`、`/ban` 命令不需要确认。

点 **❌ 拒绝** 后先选理由（`REJECT_TEMPLATES`，默认：重复投稿、与频道主题不符、内容质量不足、含广告或推广；也可以选“不附理由”），确认按钮上会显示选中的理由，理由会发给投稿人。需要自定义理由时点 **✏️ 自定义理由**，或者用 `/no 理由`。

以下命令和按钮作用相同，习惯用命令的话照样可用。通过**回复**某条投稿的预览或控制消息来指定投稿。机器人不会显示投稿编号，命令也不需要编号：

| 命令 | 说明 |
|---|---|
| `/edit 新内容` | 修改正文或说明文字，格式原样保留；会重新发一份预览。原稿另外保存 |
| `/edit` | 查看当前内容（带格式） |
| `/msg 内容` | 以“审核员”身份给投稿人发消息；回复投稿人转来的消息发 `/msg` 也可以 |
| `/no [理由]` | 拒绝投稿，理由会发给投稿人 |
| `/ban [理由]` | 封禁投稿人，并自动拒绝他所有未处理的来稿 |
| `/unban <用户ID>` | 解除封禁 |
| `/stats` | 发送最新的审核统计 |
| `/queue` | 查看定时发布队列 |
| `/active [天数]` | 投稿人活跃度排行（默认 30 天） |
| `/user <用户ID>` | 查看某位投稿人 |

`/ban` 和 `/unban` 也可以直接写用户 ID（`/ban <用户ID> 理由`），用来处理没有投稿在审核中的用户，或预先封禁。`/queue` 里每条定时投稿后面有“查看”链接，点开即跳到它的控制消息。

## 已知限制与风险

**审核操作**
- **点击次数变多**：立即发布、拒绝、封禁都要二次确认，拒绝默认还要先选理由（拒绝 → 选理由 → 确认，共三次点击）。不想选理由可以设 `REJECT_TEMPLATES=`，二次确认不能关闭
- **确认面板可能被冲掉**：点了按钮还没确认时，如果投稿人改稿、有人发 `/msg` 等让控制消息刷新，按钮会变回原样，需要重新点。不会误执行
- **改了 `REJECT_TEMPLATES` 后旧面板可能对应到别的理由**：按钮里记的是理由的序号。调整理由顺序并重启后，之前打开还没点完的面板会按新顺序取理由；序号超出范围时按“不附理由”处理。改配置前最好先处理完正在拒绝的投稿
- **理由里不能有 `|`**：它是分隔符
- **审核群更容易被限流**：确认面板、理由面板都会多编辑一次控制消息，审核量大时会更早碰到 Telegram 的频率限制。机器人会自动等待重试，但操作会变慢

**修改图片视频**
- **纯文字投稿加图后**：说明文字上限从 4096 字降到 1024 字（超出时拒绝添加）；链接预览不再显示；不能再变回纯文字；帖子在频道里的样子会变（文字在图片下面）
- **替换、删除后的原图找不回来**：原稿另存了一份（`original_items`），但机器人没有恢复原稿的功能
- **投稿人改图不通知审核员**：审核群只会出现新的预览，控制消息上显示“已修改（投稿人）”
- **审核开始后投稿人手上的旧按钮还在**：点了会提示不能再改，并收起按钮

**防垃圾**
- **中文关键词会误伤**：中文没有词边界，只能按“包含”匹配，例如关键词“微信”也会命中“微信公众号推荐”。所以默认只标记（`SPAM_ACTION=flag`）；改成 `block` 前请先观察一段时间的标记结果
- **拦截时不告诉投稿人命中了哪个词**：避免照着绕过，但投稿人可能不知道该改哪里
- **只检查网址和超链接**：`@用户名`、邮箱、电话号码不算链接
- **改稿只更新标记，不拦截**：即使 `SPAM_ACTION=block`，投稿后再改稿加进关键词也只会出现标记，由审核员判断
- **冷却只针对还没有稿件发布过的人**：只要发布过一条就不再受限；按“上次提交时间”计算，被拒绝的投稿也算
- **配置写错会启动失败**：`MAX_LINKS`、`NEW_USER_COOLDOWN_MINUTES` 不是数字，或 `SPAM_ACTION` 不是 `flag` / `block` 时，机器人启动会报错退出

## 常见问题

**自定义 emoji（会员表情）发到频道后变成了普通 emoji？**
Telegram 只允许购买了 Fragment 用户名的机器人往频道发自定义 emoji。频道拒收时，机器人会自动换成对应的普通 emoji 重新发送，其他格式不受影响。

**日志里出现 `Conflict: terminated by other getUpdates request`？**
同一个 token 同时被两个进程使用了。请确保只运行一个实例；测试时请用单独的机器人。

**发布失败了怎么办？**
控制消息会显示失败原因，并提供 🔁 重试 按钮。常见原因是说明文字加上落款后超过了 Telegram 的长度限制（媒体说明 1024 字，文字 4096 字），可以先用 `/edit` 缩短后再重试。

**被 Telegram 限流了会怎样？**
机器人会按 Telegram 要求的时间自动等待并重试，不需要人工处理。如果要求等待的时间太长（超过 30 秒），正在发布的投稿会自动改为稍后定时发布，不会标记为失败。统计消息在几秒内的多次变化会合并成一次更新。

**用户发了多个 GIF，为什么变成了多条投稿？**
Telegram 不允许把 GIF 放进相册，所以每个 GIF 会单独成为一条投稿。

## 开发

需要 Python 3.10 以上版本。

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env && mkdir -p data
set -a; source .env; set +a
DB_PATH=./data/bot.db .venv/bin/python -m bot
```

测试不需要 token，也不需要联网：

```bash
.venv/bin/python tests/test_entities.py   # 单元测试：格式偏移（UTF-16）计算
.venv/bin/python tests/test_i18n.py       # 单元测试：中英文文案齐全、占位符一致
.venv/bin/python tests/test_errors.py     # 单元测试：业务层只返回提示代码，翻译在显示时进行
.venv/bin/python tests/test_structure.py  # 单元测试：处理函数不直接访问数据库，core 各模块不重复定义方法
.venv/bin/python tests/test_confirm.py    # 单元测试：确认面板、机器人不算审核员
.venv/bin/python tests/test_reject_templates.py  # 单元测试：拒绝理由的解析与面板
.venv/bin/python tests/test_spam.py       # 单元测试：关键词、链接计数与白名单
.venv/bin/python tests/test_media.py      # 单元测试：修改图片视频的规则、相关按钮
.venv/bin/python tests/test_db.py         # 单元测试：旧数据库升级（删除已移除功能的列）
.venv/bin/python tests/test_reply.py      # 单元测试：判断“回复”时忽略话题里的隐式回复
.venv/bin/python tests/live_test.py       # 端到端测试：启动模拟的 Bot API 服务器，运行真实的机器人进程（约 1 分钟）
.venv/bin/python tests/live_msg_test.py     # 端到端测试：/msg 沟通的边界情况（约 10 秒）
.venv/bin/python tests/live_flood_test.py   # 端到端测试：被限流时的自动重试与改期（约 20 秒）
.venv/bin/python tests/live_perm_test.py    # 端到端测试：审核员权限（约 20 秒）
.venv/bin/python tests/live_confirm_test.py   # 端到端测试：二次确认、默认拒绝理由（约 15 秒）
.venv/bin/python tests/live_reject_test.py    # 端到端测试：自定义拒绝理由（约 10 秒）
.venv/bin/python tests/live_buttons_test.py   # 端到端测试：重试发布、取消定时（约 10 秒）
.venv/bin/python tests/live_spam_test.py      # 端到端测试：防垃圾标记、改稿重新检查、新用户冷却（约 10 秒）
.venv/bin/python tests/live_spam_block_test.py  # 端到端测试：防垃圾拦截模式（约 10 秒）
.venv/bin/python tests/live_prompt_test.py      # 端到端测试：修改、联系投稿人、自定义理由按钮，删除旧预览（约 10 秒）
.venv/bin/python tests/live_media_test.py       # 端到端测试：审核员的媒体面板，投稿人加图、删图（约 10 秒）
.venv/bin/python tests/live_choice_test.py      # 端到端测试：记住上次选的署名 / 匿名（约 8 秒）
```

每个 PR 和推送到 `main` 时，GitHub Actions（`.github/workflows/test.yml`）会先用 pyflakes 检查代码（未定义的名字、没用到的 import 和变量等），再运行以上全部测试。本地检查：

```bash
.venv/bin/python -m pyflakes bot tests
```

### 项目结构

```
bot/
  __main__.py     启动入口
  config.py       环境变量
  db.py           SQLite 表结构、迁移与查询
  core/           业务逻辑，组合成一个 Core；处理函数只通过它访问业务和数据
    base.py         初始化、语言、通知、控制消息、给处理函数用的查询
    submissions.py  收稿、草稿、提交审核
    editing.py      修改稿件（/edit、Telegram 自带编辑）
    review.py       发布、定时、拒绝、封禁、剧透 / 静音开关
    messaging.py    /msg 沟通
    prompts.py      等待回复的提示（修改、联系投稿人、自定义理由 / 时间）
    stats.py        审核统计、活跃度、定时队列
    scheduler.py    后台任务：定时发布、清理草稿、统计提醒
  render.py       发送内容（单条 / 相册、落款、剧透、静音）与文案
  entities.py     消息格式处理（UTF-16 偏移、拼接落款）
  i18n.py         中英文界面文案
  errors.py       业务层返回的提示代码（显示时再翻译）
  guard.py        只处理私聊和审核群，自动退出其他群
  permissions.py  审核员权限（REVIEWERS）
  spam.py         投稿防垃圾：关键词、链接上限
  media.py        修改图片视频的规则：添加、替换、删除
  ratelimit.py    被限流时自动等待重试
  keyboards.py    彩色内联按钮
  album.py        相册收集
  timeutil.py     时间解析
  handlers/
    user.py       私聊：投稿、修改、/me
    review.py     审核群：按钮与命令
tests/            单元测试与端到端测试
scripts/          多架构镜像构建脚本
```

### 发布镜像（Fork 后自用）

推送到 `main` 或打 `v*` 标签时，GitHub Actions 会构建 amd64 + arm64 镜像，并发布到 `ghcr.io/<owner>/tg-submit-bot`。

如果还想同时发布到 Docker Hub，在仓库的 **Settings → Secrets and variables → Actions** 里添加变量 `DOCKERHUB_USERNAME` 和密钥 `DOCKERHUB_TOKEN`（Docker Hub 访问令牌，需要 Read & Write 权限）。

也可以在本地构建并推送：`scripts/build-multiarch.sh <镜像名:标签>`。

## License

[MIT](LICENSE)
