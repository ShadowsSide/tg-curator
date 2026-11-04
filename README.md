<!-- prettier-ignore -->
<div align="center">

# Curator

[![docker](https://img.shields.io/github/actions/workflow/status/ShadowsSide/tg-curator/docker.yml?style=flat-square&label=build)](https://github.com/ShadowsSide/tg-curator/actions/workflows/docker.yml)
![python](https://img.shields.io/badge/Python-3.12-3776ab?style=flat-square&logo=python&logoColor=white)
[![aiogram](https://img.shields.io/badge/aiogram-3-2ca5e0?style=flat-square&logo=telegram&logoColor=white)](https://github.com/aiogram/aiogram)
![platform](https://img.shields.io/badge/platform-amd64%20%7C%20arm64-lightgrey?style=flat-square)
[![license](https://img.shields.io/github/license/ShadowsSide/tg-curator?style=flat-square)](LICENSE)

Telegram 频道投稿机器人：用户私聊投稿，管理员在审核群里审核，通过后发布到频道。

**简体中文** | [English](README.en.md)

[功能](#功能) · [快速开始](#快速开始) · [配置](#配置) · [使用](#使用) · [常见问题](#常见问题) · [开发](#开发)

</div>

在媒体或互联网语境中，curator 可译为“内容策展人”，指筛选、整理并推荐有价值信息的人。

Curator 基于 Python 3.12、[aiogram 3](https://github.com/aiogram/aiogram) 和 SQLite，用 Docker Compose 一条命令部署。它以长轮询方式运行，**不需要公网 IP，也不需要 HTTPS**，VPS、ARM 服务器、树莓派都能用。

> [!TIP]
> 从零开始只需要三个值：机器人 token、频道 ID、审核群 ID。跳到[快速开始](#快速开始)，几分钟就能跑起来。

## 工作流程

```
                                 用户私聊发内容
                                        ▼
                                选择 署名 / 匿名
                                        ▼
                             审核群：预览 + 控制按钮消息
                                        │
       审核前可调整：🙈 剧透 · 🔕 静音 · ✏️ 修改 · 🖼 媒体；/msg 联系投稿人
                                        │
            ┌───────────────────────────┼───────────────────────────┐
       ✅ 立即发布                 ⏰ 定时发布              ❌ 拒绝 / 🚫 封禁
            ▼                           ▼                           ▼
    频道 + 通知投稿人            到点发布 + 通知          通知投稿人（附理由）
```

## 功能

- **什么都能投**：文字、图片、视频、GIF、文件、音频、语音；相册自动合并成一条投稿，分几批送达的相册也能并上
- **格式原样保留**：超链接、粗体、引用、剧透文字、代码、日期时间、自定义 emoji 发到频道时不走样
- **署名或匿名**：频道落款是 *via* 名字 或 *via* 匿名；管理员始终能看到真实投稿人
- **审核前可以改稿**：投稿人用 Telegram 自带的“编辑”、回复投稿发 `/edit`、加图删图，每次改完都会收到完整预览；审核员改过之后投稿人不能再改，免得悄悄盖掉审核员的修改
- **审核群一站式处理**：每条投稿一份预览加一条控制按钮消息，可以立即或定时发布、拒绝（可选常用理由）、封禁、修改文字和图片视频、切换剧透与静音
- **双向匿名沟通**：双方用 `/msg` 由机器人转达，投稿人只看到“审核员”，双方都看不到对方账号
- **不怕误操作**：发布、拒绝、封禁需要二次确认；两人同时点发布只发一次；发布的一定是审核员看过的版本
- **防垃圾（可选）**：关键词黑名单、链接数量上限、新用户冷却，命中后标记或直接拦下；投稿人的 `/msg` 和改稿有频率限制
- **定时与统计**：定时任务存在数据库里，重启不丢；审核群定时收到统计，审核后自动刷新；有活跃度排行和个人统计
- **中英文界面**：投稿人按 Telegram 客户端语言显示，审核群和频道用 `LANGUAGE` 指定的语言
- **部署省心**：amd64 / arm64 镜像，支持代理和自建 Bot API 服务器；配置写错时日志里只有一行清楚的提示，不会反复重启

## 快速开始

### 1. 准备 Telegram

1. 在 [@BotFather](https://t.me/BotFather) 创建机器人，拿到 token。隐私模式保持默认开启即可
2. 把机器人设为**频道**管理员，并给它“发布消息”权限
3. 建一个**审核群**，把机器人拉进去，普通成员即可。默认只有审核群的管理员和群主能审核（见 `REVIEWERS`）
4. 获取频道 ID 和审核群 ID（都是 `-100` 开头的数字），可以借助 [@RawDataBot](https://t.me/RawDataBot)，或者在群里发一条消息后访问 `https://api.telegram.org/bot<token>/getUpdates` 查看。频道也可以直接填 `@用户名`

> [!IMPORTANT]
> 审核群必须是**超级群**。ID 不是 `-100` 开头说明是普通群：在群设置里把“对新成员显示聊天记录”改为可见，群就会升级为超级群，再重新获取 ID。

### 2. 部署

服务器上只需要两个文件，默认使用预构建镜像 `ghcr.io/shadowsside/tg-curator`：

```bash
mkdir tg-curator && cd tg-curator
curl -fsSLO https://raw.githubusercontent.com/ShadowsSide/tg-curator/main/docker-compose.yml
curl -fsSL https://raw.githubusercontent.com/ShadowsSide/tg-curator/main/.env.example -o .env
nano .env                  # 填写 BOT_TOKEN、CHANNEL_ID、REVIEW_CHAT_ID
docker compose up -d
docker compose logs -f
```

启动时会检查配置。必填项没填、token 不对、找不到频道或审核群、两个 ID 填反、机器人没有发布权限时，日志里会出现一行“配置错误：……”，容器显示 `unhealthy`，机器人不运行也不会反复重启；改好 `.env` 后再执行 `docker compose up -d`。网络不通不算配置错误，容器会自动重启重试。

| 镜像标签 | 内容 |
|---|---|
| `latest` | main 分支的最新版本 |
| `dev` | DEV 分支，还没合并的新功能，可能不稳定 |
| `vX.Y.Z` | 发布版本 |
| `sha-xxxxxxx` | 某次具体构建，方便回滚 |

在 `.env` 里设置 `IMAGE` 可以换标签或换成别的镜像。想从源码构建：clone 仓库后执行 `docker compose -f docker-compose.yml -f docker-compose.build.yml up -d --build`。

### 3. 更新与备份

> [!WARNING]
> **更新前先备份数据库。** 升级时会自动迁移表结构，有的版本会删除不再使用的列，删了不能恢复。

```bash
docker compose cp bot:/app/data/bot.db ./backup-$(date +%F).db   # 备份数据库
docker compose pull && docker compose up -d                      # 更新到最新镜像
```

数据库保存在 Docker 卷 `bot-data` 中。停止或更新时，机器人会先做完正在进行的发布（最多 45 秒）再退出，所以 `docker-compose.yml` 里的 `stop_grace_period: 60s` 不要删；新版本改了 `docker-compose.yml` 时，更新前也要重新下载它。

## 配置

所有配置都写在 `.env` 里，完整示例见 [`.env.example`](.env.example)，分组和下面一致（英文版：[`.env.en.example`](.env.en.example)）。

### 必填

| 变量 | 说明 |
|---|---|
| `BOT_TOKEN` | 机器人 token |
| `CHANNEL_ID` | 发布频道，填 `@username` 或 `-100…` |
| `REVIEW_CHAT_ID` | 审核群 ID（必须是超级群，`-100` 开头） |

### 常用

大多数部署会按需调整的选项。

| 变量 | 默认值 | 说明 |
|---|---|---|
| `LANGUAGE` | `zh` | 审核群、频道落款、统计提醒的语言：`zh` / `en` |
| `USER_LANGUAGE` | `auto` | 投稿人看到的语言：`auto` 跟随其客户端，或固定为 `zh` / `en` |
| `TZ` | `Asia/Shanghai` | 时区，影响定时发布和“今天”的统计范围 |
| `REVIEWERS` | `admins` | 谁可以审核：`admins` 审核群管理员和群主；`all` 审核群所有成员；也可以写用户 ID，可组合，如 `admins,123456`。机器人不算审核员 |
| `REJECT_TEMPLATES` | 随 `LANGUAGE` 的 4 条默认理由 | 点“拒绝”后可选的理由，用 `\|` 分隔，如 `重复投稿\|广告`；设为空则不显示理由面板 |
| `SCHEDULE_PRESETS` | `09:00,12:00,18:00,21:00` | 定时面板里的快捷时间点 |
| `DEFAULT_SILENT` | `false` | 新投稿是否默认静音发送 |
| `MAX_PENDING_PER_USER` | `5` | 每人同时最多保留几条未处理投稿；回复自己的投稿加图不受限制 |
| `REMINDER_INTERVAL_MINUTES` | `60` | 审核统计提醒的间隔（分钟），按整点对齐；`0` 表示关闭 |
| `REMINDER_QUIET_HOURS` | — | 免打扰时段，例如 `0-8` |
| `PROXY` | — | 代理，例如 `socks5://host:port` |
| `IMAGE` | `ghcr.io/shadowsside/tg-curator:latest` | 换成其他镜像时填写，例如固定版本、自己 fork 的镜像或 Docker Hub 上的镜像 |

> [!TIP]
> 在 Docker 里运行时，`127.0.0.1` 指的是容器自己。要使用宿主机上的代理，请填宿主机 IP，或者 `host.docker.internal`（Docker Desktop）。

### 高级

防垃圾、沟通期限、统计口径等，一般保持默认即可。

| 变量 | 默认值 | 说明 |
|---|---|---|
| `SPAM_KEYWORDS` | 空 | 关键词黑名单，逗号分隔，不区分大小写；同时检查文字和链接地址 |
| `SPAM_ACTION` | `flag` | 命中关键词或链接上限时：`flag` 照常提交并在控制按钮消息上标记；`block` 拦下，投稿人修改后可重新提交 |
| `MAX_LINKS` | `0` | 每条投稿最多几个链接，`0` 不限；`LINK_WHITELIST` 里的域名不计 |
| `LINK_WHITELIST` | 空 | 不计入链接上限的域名，逗号分隔，子域名也算，如 `t.me,github.com` |
| `NEW_USER_COOLDOWN_MINUTES` | `0` | 还没有稿件发布过的投稿人，两次提交之间至少间隔几分钟；`0` 不限 |
| `REMINDER_ONLY_WHEN_PENDING` | `true` | 只在有待审核投稿时提醒 |
| `STATS_SCOPE` | `today` | 统计范围：`today` 时接受/拒绝只统计当天的；`all` 统计全部历史 |
| `MSG_WINDOW_DAYS` | `3` | `/msg` 沟通：审核结束（发布或拒绝）后还能继续沟通的天数；审核中始终可以 |
| `LEAVE_UNKNOWN_CHATS` | `true` | 被拉进其他群组或频道时自动退出；设为 `false` 则留在群里但不响应。发布频道及其关联群组（启动时自动识别）始终保留 |
| `ALBUM_DELAY` | `1.5` | 收集相册时等待的秒数 |
| `TELEGRAM_API_URL` | — | 自建 Bot API 服务器地址，可以突破官方 API 的 20MB/50MB 文件限制 |

## 使用

### 投稿人（私聊机器人）

直接把内容发给机器人，再选择署名或匿名（上次选的排在前面）。投稿后，在审核开始（定时、发布、拒绝）之前都可以修改：

| 操作 | 说明 |
|---|---|
| 用 Telegram 的“编辑”改原消息 | 改文字、格式，也可以换图 |
| 回复自己的投稿发 `/edit 新内容` | 替换文字。**必须回复**投稿或机器人关于它的提示，否则不会改任何投稿 |
| 回复自己的投稿只发 `/edit` | 收到投稿现在的完整预览（发布后的样子）；还能改时另发一条带格式的文字，方便复制后修改。审核开始后、审核员改过之后也能看 |
| 回复自己的投稿发图片 / 视频 | 选择面板上会多一个 **➕ 加到这条投稿**。到了投稿上限（`MAX_PENDING_PER_USER`）也能加，但不能再作为新投稿提交 |
| 🗑 删除图片 / 视频 | 有 2 个以上图片视频时出现在提示消息上。直接删除聊天里的图片不会同步，Telegram 不会把私聊里的删除告诉机器人 |
| 回复审核员的消息或自己的投稿发 `/msg 内容` | 给审核员留言，文字格式原样转达，也可以带图片或文件 |
| `/me` | 查看自己的投稿统计 |

每次改稿成功，机器人都会发来最新的完整预览；旧预览、改稿时的命令和回复只保留最近一次，投稿的原消息不会删。审核员第一次改稿时会通知投稿人，之后投稿人就不能再改，只能用 `/msg` 沟通。

### 审核员（审核群）

每条投稿在审核群里有一份预览（和频道里的效果一致），下面是一条控制按钮消息：

| 按钮 | 作用 |
|---|---|
| ✅ 立即发布 · ⏰ 定时发布 | 定时支持快捷时间和自定义（`20:30`、`10-20 09:00`、`+2h`、`+1d`……） |
| ❌ 拒绝 · 🚫 封禁投稿人 | 拒绝时可选常用理由（`REJECT_TEMPLATES`）或自定义，理由会发给投稿人；封禁会拒绝 TA 所有未处理的投稿 |
| ✏️ 修改 | 机器人先发出当前内容（带格式）方便复制，直接回复它的提示就能改 |
| 🖼 媒体 | 待审核时添加（可以一次回复一组相册）、替换、删除图片和视频，最多 10 个；纯文字投稿也能加图 |
| 🙈 剧透 · 🔕 静音 | 发布选项开关；投稿人自己加了剧透时默认打开 |
| 🔓 解除封禁 · 🗑 删除 TA 的稿件 | 投稿人被封禁后出现；删除的是审核群里 TA 所有投稿的消息，数据库记录保留 |

立即发布、拒绝、封禁、解除封禁需要再点一次确认。需要回复的提示只认点按钮的那个人，发 `/cancel` 放弃。每次修改都会发新预览，审核群里只保留最初的预览、最新一份修改预览，以及最近一次改稿的消息和“已修改”确认（没改成功的留着，方便看原因）。

习惯用命令的话，**回复**投稿的预览或控制按钮消息发送即可，不需要投稿编号：

| 命令 | 说明 |
|---|---|
| `/edit 新内容` · `/edit` | 修改文字（格式保留，原稿另存）· 查看当前内容 |
| `/msg 内容` | 以“审核员”身份给投稿人发消息 |
| `/no [理由]` | 拒绝 |
| `/ban [理由]` · `/unban <用户ID>` | 封禁 · 解封；`/ban <用户ID> 理由` 可以封禁没有投稿在审核中的人 |
| `/user <用户ID>` | 查看投稿人，结果下面有封禁 / 解封按钮 |
| `/stats` · `/queue` · `/active [天数]` | 审核统计 · 定时队列 · 活跃度排行（默认 30 天） |
| `/cancel` | 放弃等你回复的提示 |

## 常见问题

**日志里出现 `Conflict: terminated by other getUpdates request`？**
同一个 token 同时被两个进程使用了。

> [!IMPORTANT]
> 同一个 token 只能运行一个实例，测试时请用单独的机器人。

**发布失败了怎么办？**
控制按钮消息会显示失败原因，并提供 🔁 重试 按钮；定时发布失败时还会单独提醒。最常见的原因是机器人失去了频道的“发布消息”权限。

**被 Telegram 限流了会怎样？**
机器人会按要求自动等待重试。要求等待超过 30 秒时，正在发布的投稿会改为稍后定时发布，不会标记为失败。

**自定义 emoji 发到频道后变成了普通 emoji？**
Telegram 只允许拥有 Fragment 用户名的机器人往频道发自定义 emoji，频道拒收时机器人会换成对应的普通 emoji 重发。

**为什么有些消息删不掉？**
Telegram 不允许机器人删除超过 48 小时的消息，设为管理员也不行。这类消息会保留，需要时由管理员手动删除。

**用户发了多个 GIF，为什么变成了多条投稿？**
Telegram 不允许把 GIF 放进相册，每个 GIF 都会单独成为一条投稿。

<details>
<summary><b>已知限制</b></summary>

**审核**
- 二次确认不能关闭；拒绝默认还要先选理由，不想选可以设 `REJECT_TEMPLATES=`。理由里不能有 `|`
- 确认面板打开期间控制按钮消息被刷新（投稿人改稿、有新的 `/msg`）时，按钮会变回原样，需要重新点，不会误执行
- 调整 `REJECT_TEMPLATES` 的顺序并重启后，之前打开还没点完的理由面板会按新顺序取理由
- 用 `/unban` 解封后，旧消息上的 🔓 / 🗑 按钮不会自动消失，点了才会收起
- 确认面板和理由面板会多编辑一次消息，审核量大时更早碰到 Telegram 的频率限制，操作会变慢

**修改图片视频**
- 纯文字投稿加图后，说明文字上限从 4096 字降到 1024 字，链接预览不再显示，也不能再变回纯文字
- 原稿另存了一份，但没有恢复原稿的功能
- 投稿人改图不单独通知审核员，审核群只会出现新的预览，控制按钮消息上显示“已修改（投稿人）”

**防垃圾**
- 中文没有词边界，关键词按“包含”匹配，容易误伤，所以默认只标记（`SPAM_ACTION=flag`）
- 拦截时不告诉投稿人命中了哪个词；`@用户名`、邮箱、电话号码不算链接；审核员自己改的稿不拦截
- 投稿人的 `/msg` 和提交后的改稿合计每分钟最多 5 次，不能配置，重启后清零
- 新用户冷却只针对还没有稿件发布过的人，被拒绝的投稿也计入“上次提交时间”

**相册**
- 机器人收齐相册要等 `ALBUM_DELAY` 秒，恰好在这几秒内崩溃或断电，已到达的几项会丢失
- 晚到的部分 10 分钟内会并进同一条投稿；那条投稿已经开始审核、已取消，或者加起来超过 10 项时，会单独成为一条投稿并说明原因
- 审核员用相册回复“替换”时只用第一张；审核员这边晚到的部分只记在内存里，重启后会丢失

</details>

## 开发

需要 Python 3.12（和镜像、CI 一致）：

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env && mkdir -p data
set -a; source .env; set +a
DB_PATH=./data/bot.db .venv/bin/python -m bot
```

测试不需要 token，也不需要联网。`tests/test_*.py` 是单元测试；`tests/live_*.py` 是端到端测试，会启动模拟的 Bot API 服务器并运行真实的机器人进程。每个文件都能单独运行，开头写了它测什么。运行全部测试（约 10 分钟）和静态检查：

```bash
for f in tests/test_*.py tests/live_*.py; do .venv/bin/python "$f" || echo "FAILED: $f"; done
.venv/bin/python -m pyflakes bot tests
```

GitHub Actions 在每个 PR、推送到 `main` / `DEV` 和打标签时运行同样的检查，通过后才构建镜像。

<details>
<summary><b>项目结构</b></summary>

```
bot/
  __main__.py     启动入口
  config.py       环境变量
  db.py           SQLite 表结构、迁移与查询
  core/           业务逻辑，组合成一个 Core；处理函数只通过它访问业务和数据
    base.py         初始化、语言、通知、控制按钮消息、给处理函数用的查询
    submissions.py  收稿、草稿、提交审核
    editing.py      修改稿件（/edit、Telegram 自带编辑）
    review.py       发布、定时、拒绝、封禁、剧透 / 静音开关
    messaging.py    /msg 沟通
    prompts.py      等待回复的提示（修改、自定义理由 / 时间、媒体添加 / 替换）
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
  throttle.py     投稿人 /msg 和改稿的频率限制
  keyboards.py    彩色内联按钮
  album.py        相册收集
  timeutil.py     时间解析
  handlers/
    user.py       私聊：投稿、修改、/me
    review.py     审核群：按钮与命令
    errors.py     没被处理的异常：记日志并告诉对方
tests/            单元测试与端到端测试
scripts/          多架构镜像构建脚本
```

</details>

### 发布自己的镜像（Fork 后）

推送到 `main`、`DEV` 或打 `v*` 标签时，Actions 会构建 amd64 + arm64 镜像并发布到 `ghcr.io/<owner>/tg-curator`。部署时在 `.env` 里设置 `IMAGE=ghcr.io/<owner>/tg-curator:latest` 才会用上它。

想同时发布到 Docker Hub，在仓库的 **Settings → Secrets and variables → Actions** 里添加变量 `DOCKERHUB_USERNAME` 和密钥 `DOCKERHUB_TOKEN`（需要 Read & Write 权限）。也可以在本地构建并推送：`scripts/build-multiarch.sh <镜像名:标签>`。
