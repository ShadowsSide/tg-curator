<!-- prettier-ignore -->
<div align="center">

# Curator

[![docker](https://img.shields.io/github/actions/workflow/status/ShadowsSide/tg-curator/docker.yml?branch=DEV&style=flat-square&label=build)](https://github.com/ShadowsSide/tg-curator/actions/workflows/docker.yml)
![python](https://img.shields.io/badge/Python-3.12-3776ab?style=flat-square&logo=python&logoColor=white)
[![aiogram](https://img.shields.io/badge/aiogram-3-2ca5e0?style=flat-square&logo=telegram&logoColor=white)](https://github.com/aiogram/aiogram)
![platform](https://img.shields.io/badge/platform-amd64%20%7C%20arm64-lightgrey?style=flat-square)
[![license](https://img.shields.io/github/license/ShadowsSide/tg-curator?style=flat-square)](LICENSE)

A Telegram channel submission bot: users send posts in a private chat, admins review them in a review group, and approved posts are published to the channel.

[简体中文](README.md) | **English**

[How it works](#how-it-works) · [Features](#features) · [Quick start](#quick-start) · [Configuration](#configuration) · [Usage](#usage) · [FAQ](#faq) · [Development](#development)

</div>

Curator is built with Python 3.12, [aiogram 3](https://github.com/aiogram/aiogram) and SQLite, and deploys with a single Docker Compose command. It uses long polling, so **you don't need a public IP or HTTPS**; a VPS, an ARM server or a Raspberry Pi all work.

> [!TIP]
> You only need three values to start: the bot token, the channel ID and the review group ID. Jump to [Quick start](#quick-start) and you'll be running in a few minutes. For an English setup, start from `.env.en.example`, which sets `LANGUAGE=en`.

## How it works

```
                           User sends content in a private chat
                                        ▼
                             Choose signed / anonymous
                                        ▼
                    Review group: preview + control panel message
                                        │
      Before deciding: 🙈 Spoiler · 🔕 Silent · ✏️ Edit · 🖼 Media; /msg the submitter
                                        │
            ┌───────────────────────────┼───────────────────────────┐
      ✅ Publish now              ⏰ Schedule                ❌ Reject / 🚫 Ban
            ▼                           ▼                           ▼
  Channel + notify submitter   Published on time + notify   Notify submitter (with reason)
```

## Features

- **Accepts almost anything**: text, photos, videos, GIFs, files, audio and voice; albums become one submission, even when Telegram delivers them in batches
- **Formatting kept intact**: links, bold, quotes, spoiler text, code, dates and custom emoji look the same in the channel
- **Signed or anonymous**: the channel signature is *via* name or *via* Anonymous; admins always see the real submitter
- **Edits before review**: submitters can use Telegram's "Edit", reply with `/edit`, or add and remove photos, and get a full preview after each change. Once a reviewer has edited a submission, the submitter can't change it anymore, so a reviewer's changes are never silently overwritten
- **Everything in the review group**: each submission gets a preview and a control panel message to publish now or later, reject (with ready-made reasons), ban, edit text and media, and toggle spoiler and silent mode
- **Anonymous two-way messaging**: both sides use `/msg` and the bot relays it; submitters only ever see “Reviewer”, and neither side sees the other's account
- **Safe against mistakes**: publishing, rejecting and banning need a second tap; two admins tapping Publish at once publish only once; what gets published is always the version a reviewer saw
- **Spam checks (optional)**: keyword blacklist, link limit and a cooldown for new users, which flag or block a submission; submitters' `/msg` and edits are rate-limited
- **Scheduling and stats**: scheduled posts live in the database and survive restarts; the review group gets a periodic summary that refreshes after each review and has a button that jumps to the longest-waiting submission, plus activity rankings and per-user stats
- **English and Chinese**: submitters see the language of their Telegram app; the review group and channel use `LANGUAGE`
- **Easy to run**: amd64 / arm64 images, proxy and self-hosted Bot API server support; a configuration mistake logs one clear line instead of a restart loop

## Quick start

### 1. Set up Telegram

1. Create a bot with [@BotFather](https://t.me/BotFather) and get its token. Leave privacy mode on (the default)
2. Make the bot an admin of your **channel** with the "Post messages" permission
3. Create a **review group**, add the bot and make it an admin with only the "Delete messages" permission (used to delete reviewers' commands once handled, clean up their edit messages and delete a banned user's posts; reviewing works without it, and the log warns at startup). By default only the group's admins and owner can review (see `REVIEWERS`)
4. Get the channel ID and the review group ID (both are numbers starting with `-100`): open the channel or group in [Telegram Web](https://web.telegram.org/a/), and the number after `#` in the address bar is the ID. You can also forward a message from the channel or group to [@RawDataBot](https://t.me/RawDataBot). The channel can also be given as `@username`

> [!NOTE]
> `https://api.telegram.org/bot<token>/getUpdates` isn't a good way to find IDs: while the bot is running it has already fetched the messages, so you only get an empty `"result":[]`, and with privacy mode on the bot doesn't receive ordinary group messages anyway.

> [!IMPORTANT]
> The review group must be a **supergroup**. If its ID doesn't start with `-100`, it's a basic group: in the group settings, make "Chat history for new members" visible, and the group is upgraded to a supergroup. Then get the ID again.

### 2. Deploy

The server only needs two files; the prebuilt image `ghcr.io/shadowsside/tg-curator` is used by default:

```bash
mkdir tg-curator && cd tg-curator
curl -fsSLO https://raw.githubusercontent.com/ShadowsSide/tg-curator/main/docker-compose.yml
curl -fsSL https://raw.githubusercontent.com/ShadowsSide/tg-curator/main/.env.en.example -o .env
nano .env                  # fill in BOT_TOKEN, CHANNEL_ID, REVIEW_CHAT_ID
docker compose up -d
docker compose logs -f
```

The configuration is checked at startup. If a required value is missing, the token is wrong, the channel or review group can't be found, the two IDs are swapped, or the bot can't post to the channel, the log shows one "Configuration error: …" line and the container is marked `unhealthy`. The bot doesn't run and doesn't restart in a loop; fix `.env`, then run `docker compose up -d` again. Network problems aren't configuration errors: the container restarts and retries.

While running, the bot writes a heartbeat regularly. If it stops for more than 5 minutes (the bot is stuck), the container is also marked `unhealthy`. Docker only marks it and doesn't restart it; run `docker compose restart` yourself (save the logs first if you can). `docker compose ps` shows the health status; to see the reason:

```bash
docker inspect --format '{{range .State.Health.Log}}{{.Output}}{{end}}' $(docker compose ps -q bot)
```

| Image tag | Contents |
|---|---|
| `latest` | Latest release (updated when a `v*` tag is pushed) |
| `dev` | The DEV branch, for trying features before they're merged; may be unstable |
| `vX.Y.Z` | A pinned version; to roll back, set `IMAGE` to the previous version |

Set `IMAGE` in `.env` to use another tag or image. To build from source, clone the repository and run `docker compose -f docker-compose.yml -f docker-compose.build.yml up -d --build`.

### 3. Updating and backups

> [!WARNING]
> **Back up the database before updating.** Upgrades migrate the schema automatically, and some versions drop columns that are no longer used; those can't be recovered.

```bash
docker compose cp bot:/app/data/bot.db ./backup-$(date +%F).db   # back up the database
docker compose pull && docker compose up -d && docker image prune -f   # update to the latest image and remove old ones
```

`docker image prune -f` only removes old images no container is using; the running one is never deleted. Every update leaves an old image of one or two hundred MB behind, so keep it on small VPSes and Raspberry Pis; leave it out if you want to keep the previous version around for a quick offline rollback. `docker system df` shows how much space images take.

The bot also backs up the database automatically once a day (04:00 by default, keeping the last 7; see `BACKUP_TIME` and `BACKUP_KEEP`) into `/app/data/backups/` on the same volume, and posts a silent message to the review group whether it worked or not. This protects against mistakes and columns dropped by upgrades, but it lives on the same volume as the database, so it doesn't survive a lost volume or disk; copy it elsewhere now and then if it matters. To copy the backups out and restore one:

```bash
docker compose cp bot:/app/data/backups ./backups   # copy the automatic backups to the current directory
docker compose stop bot && docker compose cp ./backups/bot-2026-11-12.db bot:/app/data/bot.db && docker compose start bot   # restore one of them
```

The database lives in the Docker volume `bot-data`. When stopping or updating, the bot finishes publishing in progress (up to 45 seconds) before exiting, so keep `stop_grace_period: 60s` in `docker-compose.yml`. When a new version changes `docker-compose.yml`, download it again before updating.

## Configuration

Everything is configured in `.env`. See [`.env.en.example`](.env.en.example) for a full example, grouped the same way as below ([`.env.example`](.env.example) is the Chinese version).

### Required

| Variable | Description |
|---|---|
| `BOT_TOKEN` | The bot token |
| `CHANNEL_ID` | Channel to publish to: `@username` or `-100…` |
| `REVIEW_CHAT_ID` | Review group ID (must be a supergroup, starts with `-100`) |

### Common

Options most deployments adjust as needed.

| Variable | Default | Description |
|---|---|---|
| `LANGUAGE` | `zh` | Language of the review group, channel signatures and review summary: `zh` / `en` |
| `USER_LANGUAGE` | `auto` | Language submitters see: `auto` follows their Telegram app, or fix it to `zh` / `en` |
| `TZ` | `Asia/Shanghai` | Time zone for scheduling and for what counts as "today" in stats |
| `REVIEWERS` | `admins` | Who can review: `admins` = review group admins and owner; `all` = every member; or user IDs, combinable, e.g. `admins,123456`. Bots never count as reviewers |
| `REJECT_TEMPLATES` | 4 default reasons, depends on `LANGUAGE` | Reasons offered after tapping Reject, separated by `\|`, e.g. `Duplicate\|Ads`; set it to empty to skip the reason panel |
| `SCHEDULE_PRESETS` | `09:00,12:00,18:00,21:00` | Quick time buttons in the schedule panel |
| `DEFAULT_SILENT` | `false` | Whether new submissions are published silently by default |
| `MAX_PENDING_PER_USER` | `5` | Maximum open submissions per user at a time, `0` for no limit; adding photos to your own submission by replying isn't limited |
| `REMINDER_INTERVAL_MINUTES` | `60` | Interval of the review summary, aligned to the clock; `0` turns it off |
| `REMINDER_QUIET_HOURS` | — | Quiet hours with no summaries, e.g. `0-8` |
| `BACKUP_TIME` | `04:00` | Time of day (in `TZ`) for the automatic database backup; the review group gets a silent message whether it worked or not |
| `BACKUP_KEEP` | `7` | How many automatic backups to keep; `0` turns automatic backups off |
| `PROXY` | — | Proxy, e.g. `socks5://host:port` |
| `IMAGE` | `ghcr.io/shadowsside/tg-curator:latest` | Set this to use another image, e.g. a pinned version, your fork's image or one on Docker Hub |

> [!TIP]
> Inside Docker, `127.0.0.1` means the container itself. To use a proxy running on the host, use the host's IP address or `host.docker.internal` (Docker Desktop).

### Advanced

Spam checks, messaging window, stats scope and so on; the defaults are usually fine.

| Variable | Default | Description |
|---|---|---|
| `SPAM_KEYWORDS` | empty | Keyword blacklist, comma-separated, case-insensitive; checks both the text and link addresses |
| `SPAM_ACTION` | `flag` | On a keyword or link-limit hit: `flag` = submit as usual and mark the control panel message; `block` = refuse it, the submitter can edit and resubmit |
| `MAX_LINKS` | `0` | Maximum links per submission, `0` = no limit; domains in `LINK_WHITELIST` don't count |
| `LINK_WHITELIST` | empty | Domains that don't count toward the link limit, comma-separated, subdomains included, e.g. `t.me,github.com` |
| `NEW_USER_COOLDOWN_MINUTES` | `0` | Submitters with nothing published yet must wait this many minutes between submissions; `0` = no limit |
| `REMINDER_ONLY_WHEN_PENDING` | `true` | Only post the summary when something is waiting for review |
| `STATS_SCOPE` | `today` | `today`: accepted/rejected counts cover today only; `all`: all time |
| `MSG_WINDOW_DAYS` | `3` | `/msg`: days after a submission is published or rejected during which messaging stays open; always open during review |
| `LEAVE_UNKNOWN_CHATS` | `true` | Leave any other group or channel the bot is added to; `false` stays but never responds. The publishing channel and its linked discussion group (detected at startup) are always kept |
| `ALBUM_DELAY` | `1.5` | Seconds to wait while collecting the parts of an album |
| `CALLBACK_FALLBACK_SECONDS` | `3` | If a button takes longer than this many seconds, it shows “Working on it…” first (Telegram only gives a button a few seconds to respond) and the result follows |
| `TELEGRAM_API_URL` | — | Self-hosted Bot API server, which lifts the official 20 MB / 50 MB file limits |

## Usage

### Submitters (private chat with the bot)

Send your content to the bot, then choose signed or anonymous (your previous choice is shown first). Until the review starts (scheduled, published or rejected), you can still change it:

| Action | Description |
|---|---|
| Edit the original message with Telegram's "Edit" | Changes the text or formatting, or even swaps the photo |
| Reply to your submission with `/edit new content` | Replaces the text. It must be a **reply** to the submission or the bot's message about it; otherwise nothing is changed |
| Reply to your submission with just `/edit` | Sends a full preview of the submission as it will be published; while you can still edit, also the formatted text to copy and change. Works after the review starts and after a reviewer edit too |
| Reply to your submission with a photo / video | The choice panel gets an extra **➕ Add to that submission** button. This works even at the open-submission limit (`MAX_PENDING_PER_USER`), but then the photos can't be submitted as a new submission |
| 🗑 Remove a photo / video | Shown on the bot's message when there are 2 or more photos/videos. Deleting a photo from the chat isn't synced: Telegram doesn't tell bots about deletions in private chats |
| Reply to a reviewer's message or your submission with `/msg message` | Messages the reviewers; formatting is kept, and a photo or file can be attached |
| `/me` | Your submission stats |

After each successful edit the bot sends the latest full preview. Older previews, and your edit commands and the bot's replies, are kept only for the latest edit; your original submission messages are never deleted. The first time a reviewer edits your submission the bot tells you; from then on you can't change it and can only use `/msg`.

### Reviewers (review group)

Each submission gets a preview in the review group (exactly as it will look in the channel), followed by a control panel message:

| Button | What it does |
|---|---|
| ✅ Publish now · ⏰ Schedule | Scheduling offers quick times and custom ones (`20:30`, `10-20 09:00`, `+2h`, `+1d`, …) |
| ❌ Reject · 🚫 Ban submitter | Pick a ready-made reason (`REJECT_TEMPLATES`) or write one; the reason is sent to the submitter. Banning rejects all their open submissions |
| ✏️ Edit | The bot posts the current content with formatting to copy; reply to its prompt to make the change |
| 🖼 Media | While pending: add (an album reply works too), replace or remove photos and videos, up to 10; text submissions can get photos too |
| 🙈 Spoiler · 🔕 Silent | Publishing toggles; Spoiler is on by default when the submitter used a spoiler |
| 🔓 Unban · 🗑 Delete their posts | Shown once the submitter is banned; deletes the review group messages of all their submissions, database records are kept |

Publish now, Reject, Ban and Unban act on the second tap. Prompts waiting for a reply only accept the person who tapped the button; send `/cancel` to give up. Every edit posts a new preview; the review group keeps only the original preview, the latest edited preview, and the messages and “Edited” confirmation of the latest edit (failed ones stay so you can see why).

If you prefer commands, send them as a **reply** to a submission's preview or control panel message; no submission numbers needed:

| Command | Description |
|---|---|
| `/edit new content` · `/edit` | Change the text (formatting kept, original saved) · show the current content |
| `/msg message` | Message the submitter as “Reviewer” |
| `/no [reason]` | Reject |
| `/ban [reason]` · `/unban <user ID>` | Ban · unban; `/ban <user ID> reason` supports banning in advance (nothing pending / never submitted) |
| `/user <user ID>` | Show a contributor, with Ban / Unban buttons below |
| `/stats` · `/queue` · `/active [days]` | Review summary · scheduled posts · activity ranking (default 30 days) |
| `/cancel` | Drop prompts waiting for your reply |

Commands are deleted once handled (needs the "Delete messages" permission); results about a submission are posted as a reply to its control panel message. `/msg` and `/edit` are kept: the first is the group's only record of what the submitter was sent, the second keeps only the latest one.

## FAQ

**The log says `Conflict: terminated by other getUpdates request`?**
The same token is being used by two processes at once.

> [!IMPORTANT]
> Run only one instance per token, and use a separate bot for testing.

**What if publishing fails?**
The control panel message shows the reason and a 🔁 Retry button; failed scheduled posts also get a separate alert. The usual cause is that the bot lost the "Post messages" permission in the channel.

**What happens when Telegram rate-limits the bot?**
The bot waits and retries automatically. If Telegram asks for more than 30 seconds, a post being published is rescheduled for a bit later instead of being marked as failed.

**Custom emoji turn into regular emoji in the channel?**
Telegram only lets bots with a Fragment username post custom emoji to channels. When the channel refuses them, the bot resends with the matching regular emoji.

**Why can't some messages be deleted?**
Telegram doesn't let bots delete messages older than 48 hours, not even as an admin. Those messages stay; an admin can delete them by hand if needed.

**A user sent several GIFs. Why did they become separate submissions?**
Telegram doesn't allow GIFs in albums, so each GIF becomes its own submission.

<details>
<summary><b>Known limitations</b></summary>

**Reviewing**
- Publishing and rejecting (as well as banning and unbanning) always need a second tap, to avoid accidental taps; rejecting asks for a reason first by default (set `REJECT_TEMPLATES=` to skip it and reject without a reason)
- If the control panel message refreshes while a confirm panel is open (the submitter edits, a new `/msg` arrives), the buttons reset and you tap again; nothing runs by mistake
- After reordering `REJECT_TEMPLATES` and restarting, reason panels opened earlier pick reasons by the new order and may pick the wrong one
- After `/unban`, old 🔓 / 🗑 buttons don't disappear by themselves; they go away when tapped

**Photos and videos**
- Once a text submission gets photos, its caption limit drops from 4096 to 1024 characters, the link preview goes away, and it can't become text-only again
- The original is saved, but there's no feature to restore it

**Spam checks**
- Keywords match as substrings, which can catch innocent text (especially in Chinese, which has no word boundaries), so the default only flags (`SPAM_ACTION=flag`)
- Blocked submitters aren't told which word matched; `@usernames`, emails and phone numbers don't count as links
- Submitters' `/msg` and post-submission edits are limited to 5 per minute in total; not configurable, and reset on restart
- Rejected submissions also count toward the new-user cooldown's "last submitted"

**Albums**
- The bot waits `ALBUM_DELAY` seconds to collect an album; a crash or power loss in those seconds loses the parts that already arrived
- If the submission a late part would join is already under review, cancelled, or would exceed 10 items, the late part becomes a separate submission and the reason is shown
- A reviewer's album reply to Replace only uses the first item; late parts on the reviewer side are kept in memory only and are lost on restart

</details>

## Development

Requires Python 3.12 (the same as the image and CI):

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt -r requirements-dev.txt
cp .env.en.example .env && mkdir -p data
set -a; source .env; set +a
DB_PATH=./data/bot.db .venv/bin/python -m bot
```

Tests need no token and no network. `tests/test_*.py` are unit tests; `tests/live_*.py` are end-to-end tests that start a mock Bot API server and run the real bot process. Each file is a standalone script with a description at the top. Run all tests and the static check (end-to-end tests run in parallel, as many at a time as there are CPU cores, or set it with `-j`; about 2.5 minutes with 8):

```bash
.venv/bin/python tests/run_all.py
.venv/bin/python -m pyflakes bot tests
```

GitHub Actions runs the same checks on pushes to `DEV`, on tags and on PRs from other branches, and only builds images when they pass (PRs from `DEV` reuse the result of the push, and `main` is only updated through such PRs, so it is not tested again).

<details>
<summary><b>Project layout</b></summary>

```
bot/
  __main__.py     entry point
  config.py       environment variables
  db.py           SQLite schema, migrations and queries
  core/           business logic, combined into one Core; handlers only go through it
    base.py         setup, languages, notifications, control panel messages, queries for handlers
    submissions.py  receiving, drafts, submitting for review
    editing.py      editing submissions (/edit, Telegram's Edit)
    review.py       publish, schedule, reject, ban, spoiler / silent toggles
    messaging.py    /msg relaying
    prompts.py      prompts waiting for a reply (edit, custom reason / time, add / replace media)
    stats.py        review summary, activity, schedule queue
    scheduler.py    background jobs: scheduled publishing, draft cleanup, reminders
  render.py       sending content (single / album, signature, spoiler, silent) and texts
  entities.py     message formatting (UTF-16 offsets, appending the signature)
  i18n.py         English and Chinese UI texts
  errors.py       notice codes returned by the core (translated when shown)
  guard.py        only handles private chats and the review group, leaves other chats
  permissions.py  reviewer permissions (REVIEWERS)
  spam.py         spam checks: keywords, link limit
  media.py        rules for changing photos and videos: add, replace, remove
  ratelimit.py    waits and retries when rate-limited
  throttle.py     rate limit for submitters' /msg and edits
  keyboards.py    colored inline buttons
  album.py        album collection
  timeutil.py     time parsing
  handlers/
    user.py       private chat: submitting, editing, /me
    review.py     review group: buttons and commands
    errors.py     unhandled exceptions: log and tell the user
tests/            unit and end-to-end tests
scripts/          multi-arch image build script
```

</details>

### Publishing your own image (for a fork)

Pushes to `DEV` and `v*` tags make Actions build amd64 + arm64 images and publish them to `ghcr.io/<owner>/tg-curator` (pushes to `main` trigger nothing; update `main` through PRs from `DEV`). Set `IMAGE=ghcr.io/<owner>/tg-curator:latest` in `.env` to deploy it; `latest` only exists after your first `v*` tag, so use `:dev` until then.

To publish to Docker Hub as well, add the variable `DOCKERHUB_USERNAME` and the secret `DOCKERHUB_TOKEN` (with Read & Write access) under the repository's **Settings → Secrets and variables → Actions**. You can also build and push locally with `scripts/build-multiarch.sh <image:tag>`.
