# tg-submit-bot

[![docker](https://github.com/ShadowsSide/tg-submit-bot/actions/workflows/docker.yml/badge.svg)](https://github.com/ShadowsSide/tg-submit-bot/actions/workflows/docker.yml)
[![license](https://img.shields.io/github/license/ShadowsSide/tg-submit-bot)](LICENSE)
![python](https://img.shields.io/badge/python-3.12-blue)
![platform](https://img.shields.io/badge/platform-linux%2Famd64%20%7C%20linux%2Farm64-lightgrey)

[简体中文](README.md) | **English**

A Telegram channel submission bot: users send posts to the bot in a private chat, admins review them in a review group, and approved posts are published to the channel.

Built with Python 3.12 + [aiogram 3](https://github.com/aiogram/aiogram) + SQLite, deployed with a single Docker Compose command. It uses long polling, so **you don't need a public IP or HTTPS**.

> The bot speaks **English and Chinese**. Submitters see the language of their Telegram app (Chinese for Chinese clients, English otherwise); the review group, channel signatures and the review summary use `LANGUAGE`. For an English setup, set `LANGUAGE=en` in `.env`.

## Features

**Submitting**
- Text, photos, videos, GIFs, files, audio and voice messages. Albums of several photos or videos are merged into one submission
- Submitters choose to post **signed** (with their name) or **anonymously**. Either way, admins can always see who sent it
- **Formatting is kept exactly as sent**: links, bold, quotes, spoiler text, code, date/time and emoji all come through to the channel unchanged
- Submitters can **edit their post** until it has been reviewed, either with Telegram's built-in "Edit" or by **replying** to it with `/edit`
- **Spam checks** (optional): keyword blacklist, a link limit (whitelisted domains don't count) and a cooldown for new submitters. By default a hit only puts a ⚠️ Possible spam note on the control message for reviewers to judge; it can also block the submission

**Reviewer ↔ submitter messaging**
- Both sides use `/msg message` as a reply to the relevant submission or message, and the bot relays it. Submitters always see the sender as “Reviewer”; neither side sees the other's account
- Formatting is kept, and a single photo or file can be attached; the conversation is stored and the control message shows the message count
- Possible any time during review, and for 3 days after it's published or rejected (`MSG_WINDOW_DAYS`); banned users can't send

**Reviewing**
- Each submission gets a preview in the review group (exactly what the channel will show), followed by a control message with colored buttons
- Publish now · Schedule · Reject · Ban submitter
- Publishing options: 🙈 **spoiler** (blur the media) and 🔕 **silent** (subscribers get a notification without sound)
- Pick a common reject reason with one tap (`REJECT_TEMPLATES`)
- `/edit` to change a post, `/no reason` to reject, `/ban reason` to ban. Banning also rejects every open submission from that user
- Safe against accidental taps: Publish now, Reject and Ban need a second tap to confirm
- Safe against double actions: if two admins press "Publish" at the same time, the post is still published only once
- **Only answers in private chats and the review group**: it never replies in other groups, and leaves any other group or channel it's added to. The publishing channel and its linked discussion group are whitelisted and never left

**Scheduling and stats**
- Schedule with quick buttons or a custom time (`20:30`, `10-20 09:00`, `+2h`, …). Schedules are stored in the database and survive restarts
- A review summary is posted to the review group at a set interval and refreshed after each review action:
  ```
  Accepted 3 Rejected 1 Pending 4
  Approval rate: 75.00% Review rate: 50.00%
  #review_stats [updated 16:03:10]
  ```
- Contributor activity ranking and per-user stats; submitters can see their own stats with `/me`

**Topic mode** (optional, switched on separately for each side)
- **Review group**: every new submission gets its own topic holding the preview, the control message and the discussion. Inside a topic you can send `/no`, `/edit` and the other commands directly, without replying. The topic name follows the status (⏳ pending → ⏰ scheduled → ✅ published / ❌ rejected), and the topic is closed once the review is done
- **Submitter's private chat**: every submission gets its own topic, so its content, edits and review notifications stay together and separate from other submissions

**English and Chinese**
- Submitters see the language of their Telegram app (Chinese clients get Chinese, everyone else English); the review group, channel signatures and the review summary use the `LANGUAGE` setting
- The command menu is shown in the client's language too

**Deployment**
- Multi-arch images for `linux/amd64` and `linux/arm64`: works on regular VPSes, ARM servers and Raspberry Pi
- Proxy support (`http://`, `socks5://`) and support for a self-hosted Bot API server

## How it works

```
User sends content ─► chooses signed / anonymous ─► Review group: preview + control message
                                                             │
        ┌───────────────┬──────────────────┬─────────────────┼──────────────────┐
  spoiler / silent   ✏️ Edit          ✅ Publish now      ⏰ Schedule      ❌ Reject / 🚫 Ban
                                             │                 │                  │
                                             ▼                 ▼                  ▼
                                   Channel + notify user   Publish on time   Notify user (with reason)
```

## Quick start

### 1. Set up Telegram

1. Create a bot with [@BotFather](https://t.me/BotFather) and copy its token. Leave privacy mode on (the default)
2. Make the bot an admin of your **channel** with permission to post messages
3. Create a **review group** and add the bot as a regular member. By default only the group's **admins and owner** can review (`REVIEWERS`); other members get a “no permission” notice
4. Find the channel ID and review group ID (both are numbers starting with `-100`). You can use a bot such as [@RawDataBot](https://t.me/RawDataBot), or send a message in the group and open `https://api.telegram.org/bot<token>/getUpdates`. For the channel you can also use its `@username`

### 2. Deploy

```bash
git clone https://github.com/ShadowsSide/tg-submit-bot.git
cd tg-submit-bot
cp .env.example .env        # fill in BOT_TOKEN, CHANNEL_ID and REVIEW_CHAT_ID; set LANGUAGE=en for English
docker compose up -d --build
docker compose logs -f
```

To use the prebuilt image instead of building on your server, add this to `.env`:

```bash
IMAGE=ghcr.io/shadowsside/tg-submit-bot:latest
```

and run:

```bash
docker compose pull && docker compose up -d --no-build
```

Image tags: `latest` is the newest build of the main branch, `vX.Y.Z` are releases, and `sha-xxxxxxx` points to a specific build, which is handy for rolling back.

### 3. Updating and backups

```bash
git pull && docker compose up -d --build                         # update (build yourself)
docker compose pull && docker compose up -d --no-build           # update (prebuilt image)
docker compose cp bot:/app/data/bot.db ./backup-$(date +%F).db   # back up the database
```

The database lives in the `bot-data` Docker volume. Its schema is migrated automatically when you upgrade.

## Configuration

Everything is configured in `.env`. See [`.env.example`](.env.example) for a full example.

| Variable | Default | Description |
|---|---|---|
| `BOT_TOKEN` | — | **Required.** The bot token |
| `CHANNEL_ID` | — | **Required.** Channel to publish to: `@username` or `-100…` |
| `REVIEW_CHAT_ID` | — | **Required.** Review group ID |
| `LANGUAGE` | `zh` | Language of the review group, channel signatures and review summary: `zh` / `en` |
| `USER_LANGUAGE` | `auto` | Language submitters see: `auto` follows their Telegram app, or fix it to `zh` / `en` |
| `REVIEW_TOPICS` | `false` | Topic mode in the review group: the group needs topics enabled, and the bot must be an admin allowed to manage topics |
| `USER_TOPICS` | `false` | Topic mode in private chats: enable topic mode for the bot in @BotFather first |
| `REVIEWERS` | `admins` | Who can review: `admins` = review group admins and owner; `all` = every member; or user IDs, combinable, e.g. `admins,123456`. Bots never count as reviewers |
| `REJECT_TEMPLATES` | 4 default reasons, depends on `LANGUAGE` | Reasons offered after tapping Reject, separated by `\|`, e.g. `Duplicate\|Ads`; set it to empty to skip the reason panel |
| `MSG_WINDOW_DAYS` | `3` | `/msg`: days after a submission is published or rejected during which messaging stays open; always open during review |
| `LEAVE_UNKNOWN_CHATS` | `true` | Leave any other group or channel the bot is added to; `false` stays but never responds. The publishing channel and its linked discussion group (detected at startup) are always kept |
| `TZ` | `Asia/Shanghai` | Time zone for scheduling and for what counts as "today" in stats |
| `SIGN_TEMPLATE` | depends on `LANGUAGE`: `Submitted by {name}` / `投稿人：{name}` | Signature for signed posts; `{name}` becomes a link to the submitter |
| `ANON_SIGNATURE` | depends on `LANGUAGE`: `Anonymous submission` / `匿名投稿` | Signature for anonymous posts; set it to empty for none |
| `MAX_PENDING_PER_USER` | `5` | Maximum open submissions per user at a time |
| `SPAM_KEYWORDS` | empty | Keyword blacklist, comma-separated, case-insensitive; checks both the text and link addresses |
| `MAX_LINKS` | `0` | Maximum links per submission, `0` = no limit; domains in `LINK_WHITELIST` don't count |
| `LINK_WHITELIST` | empty | Domains that don't count toward the link limit, comma-separated, subdomains included, e.g. `t.me,github.com` |
| `SPAM_ACTION` | `flag` | On a keyword or link-limit hit: `flag` = submit as usual and mark the control message; `block` = refuse it, the submitter can edit and resubmit |
| `NEW_USER_COOLDOWN_MINUTES` | `0` | Submitters with nothing published yet must wait this many minutes between submissions; `0` = no limit |
| `ALBUM_DELAY` | `1.5` | Seconds to wait while collecting the parts of an album |
| `SCHEDULE_PRESETS` | `09:00,12:00,18:00,21:00` | Quick time buttons in the schedule panel |
| `DEFAULT_SILENT` | `false` | Whether new submissions are published silently by default |
| `REMINDER_INTERVAL_MINUTES` | `60` | Interval of the review summary, aligned to the clock; `0` turns it off |
| `REMINDER_ONLY_WHEN_PENDING` | `true` | Only post the summary when something is waiting for review |
| `REMINDER_QUIET_HOURS` | — | Quiet hours with no summaries, e.g. `0-8` |
| `STATS_SCOPE` | `today` | `today`: accepted/rejected counts cover today only; `all`: all time |
| `PROXY` | — | Proxy, e.g. `socks5://host:port` |
| `TELEGRAM_API_URL` | — | Self-hosted Bot API server, which lifts the official 20 MB / 50 MB file limits |
| `IMAGE` | `tg-submit-bot:latest` | Set this when using a prebuilt image |

> If topic mode can't be used (the review group has no topics, topic mode isn't enabled in BotFather, or a permission is missing), the bot falls back to normal mode and logs why.

> Inside Docker, `127.0.0.1` means the container itself. To use a proxy running on the host, use the host's IP address or `host.docker.internal` (Docker Desktop).

## Usage

### Submitters (private chat with the bot)

| Action | Description |
|---|---|
| Send any content | Starts a submission, then choose signed or anonymous |
| Edit the original message with Telegram's "Edit" | Changes the submission until it has been reviewed: text, formatting, or even the image |
| `/edit new content` | Only works as a **reply** to your submission (or the bot's message about it); without a reply nothing is changed |
| `/edit` (as a reply) | Shows the current content with formatting, so you can copy and change it |
| `/msg message` | Message the reviewers: **reply** to the reviewer's message or your submission. Replying to the reviewer without `/msg` gets a reminder |
| `/me` | Your submission stats |

### Admins (review group)

Buttons on the control message: **✅ Publish now**, **⏰ Schedule**, **❌ Reject**, **🚫 Ban submitter**, plus the **🙈 Spoiler** and **🔕 Silent** toggles.

To avoid accidental taps, **Publish now, Reject and Ban** first switch to “Confirm / Back” buttons and only act on the second tap. Scheduling, retrying and the `/no` and `/ban` commands need no confirmation.

**❌ Reject** first asks for a reason (`REJECT_TEMPLATES`; defaults: Duplicate, Off-topic, Low quality, Advertising; or “No reason”). The confirm button shows the chosen reason, and the reason is sent to the submitter. For a reason of your own, use `/no reason`.

Use the commands below by **replying** to a submission's preview or control message (with review-group topics on, just send them inside the submission's topic). The bot never shows submission numbers, and no command needs one:

| Command | Description |
|---|---|
| `/edit new content` | Changes the text or caption, keeping its formatting, and posts a new preview. The original is kept |
| `/edit` | Shows the current content with formatting |
| `/msg message` | Message the submitter as “Reviewer”; also works as a reply to a relayed submitter message |
| `/no [reason]` | Rejects the submission; the reason is sent to the submitter |
| `/ban [reason]` | Bans the submitter and rejects all their open submissions |
| `/unban <user ID>` | Lifts a ban |
| `/stats` | Posts the latest review summary |
| `/queue` | Lists scheduled posts |
| `/active [days]` | Contributor activity ranking (default: 30 days) |
| `/user <user ID>` | Shows one contributor's stats |

`/ban` and `/unban` also accept a user ID (`/ban <user ID> reason`) for users with nothing under review, or to ban someone in advance. Each scheduled post in `/queue` has a “view” link that jumps to its control message.

## Known limitations and risks

**Review actions**
- **More taps**: Publish now, Reject and Ban always need a second tap, and Reject first asks for a reason by default (Reject → reason → Confirm, three taps). Set `REJECT_TEMPLATES=` to skip the reason; the confirmation itself can't be turned off
- **The confirm panel can be reset**: if the control message refreshes while you're about to confirm (the submitter edits, someone sends `/msg`, …), the buttons go back to normal and you need to tap again. Nothing runs by accident
- **Changing `REJECT_TEMPLATES` can shift old panels**: buttons store the reason's position. After reordering the reasons and restarting, a panel opened before the restart picks the reason by the new order; an out-of-range position means “No reason”. Finish any rejection in progress before changing it
- **Reasons can't contain `|`**: it's the separator
- **The review group hits rate limits sooner**: the confirm and reason panels each edit the control message once more, so with heavy review traffic Telegram's limits come sooner. The bot waits and retries automatically, but actions get slower

**Spam checks**
- **Chinese keywords can over-match**: Chinese has no word boundaries, so keywords match as substrings (e.g. “微信” also matches “微信公众号推荐”). That's why the default only flags (`SPAM_ACTION=flag`); watch the flags for a while before switching to `block`
- **Blocking doesn't tell the submitter which word matched**: so it can't be dodged on purpose, but the submitter may not know what to change
- **Only URLs and hyperlinks count as links**: `@usernames`, emails and phone numbers don't
- **Edits only update the flags, never block**: even with `SPAM_ACTION=block`, adding a keyword by editing after submitting just shows a flag for reviewers
- **The cooldown only applies to submitters with nothing published yet**: one published post lifts it; it counts from the last submission, rejected ones included
- **Bad values stop the bot from starting**: a non-number in `MAX_LINKS` or `NEW_USER_COOLDOWN_MINUTES`, or a `SPAM_ACTION` other than `flag` / `block`, makes the bot exit with an error at startup

## FAQ

**Custom (premium) emoji turn into regular emoji in the channel. Why?**
Telegram only lets bots with a username bought on Fragment send custom emoji to channels. When the channel refuses them, the bot automatically resends the post with the matching regular emoji. All other formatting is unaffected.

**The log says `Conflict: terminated by other getUpdates request`.**
Two processes are using the same token. Make sure only one instance is running, and use a separate bot for testing.

**A post failed to publish. What now?**
The control message shows the reason and a 🔁 Retry button. A common cause is that the caption plus the signature exceeds Telegram's length limit (1024 characters for media captions, 4096 for text). Shorten it with `/edit`, then retry.

**What happens when Telegram rate-limits the bot?**
The bot waits as long as Telegram asks and retries automatically. If the wait would be too long (over 30 seconds), a post being published is automatically rescheduled for later instead of being marked failed. Several changes to the review summary within a few seconds are merged into one update.

**A user sent several GIFs and got several submissions. Why?**
Telegram doesn't allow GIFs in albums, so each GIF becomes its own submission.

## Development

Requires Python 3.10 or newer.

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env && mkdir -p data
set -a; source .env; set +a
DB_PATH=./data/bot.db .venv/bin/python -m bot
```

The tests need no token and no network access:

```bash
.venv/bin/python tests/test_entities.py   # unit tests: formatting offsets (UTF-16)
.venv/bin/python tests/test_i18n.py       # unit tests: every text exists in both languages
.venv/bin/python tests/test_errors.py     # unit tests: business logic returns notice codes, translated only when shown
.venv/bin/python tests/test_structure.py  # unit tests: handlers don't touch the database; core modules don't redefine methods
.venv/bin/python tests/test_confirm.py    # unit tests: confirm panel; bots are never reviewers
.venv/bin/python tests/test_reject_templates.py  # unit tests: reject reasons parsing and panel
.venv/bin/python tests/test_spam.py       # unit tests: keywords, link counting and whitelist
.venv/bin/python tests/live_test.py       # end-to-end: runs the real bot against a mock Bot API server (~1 minute)
.venv/bin/python tests/live_topics_test.py  # end-to-end: topic mode (~10 seconds)
.venv/bin/python tests/live_msg_test.py     # end-to-end: /msg edge cases (~10 seconds)
.venv/bin/python tests/live_flood_test.py   # end-to-end: retries and rescheduling under rate limits (~20 seconds)
.venv/bin/python tests/live_perm_test.py    # end-to-end: reviewer permissions (~20 seconds)
.venv/bin/python tests/live_confirm_test.py   # end-to-end: confirmation, default reject reasons (~15 seconds)
.venv/bin/python tests/live_reject_test.py    # end-to-end: custom reject reasons (~10 seconds)
.venv/bin/python tests/live_buttons_test.py   # end-to-end: Retry and Unschedule buttons (~10 seconds)
.venv/bin/python tests/live_spam_test.py      # end-to-end: spam flags, re-check on edit, new-user cooldown (~10 seconds)
.venv/bin/python tests/live_spam_block_test.py  # end-to-end: spam block mode (~10 seconds)
```

GitHub Actions (`.github/workflows/test.yml`) runs all of these on every pull request and every push to `main`.

### Project layout

```
bot/
  __main__.py     entry point
  config.py       environment variables
  db.py           SQLite schema, migrations and queries
  core/           business logic, combined into one Core; handlers only go through it
    base.py         setup, language, notifications, control messages, lookups for handlers
    submissions.py  receiving, drafts, sending for review
    editing.py      editing (/edit and Telegram's built-in edit)
    review.py       publish, schedule, reject, ban, spoiler / silent toggles
    messaging.py    /msg messaging
    topics.py       topic mode
    stats.py        review summary, activity, scheduled queue
    scheduler.py    background jobs: scheduled publishing, draft cleanup, summary reminders
  render.py       sending content (single / album, signature, spoiler, silent) and message texts
  entities.py     message formatting (UTF-16 offsets, appending the signature)
  i18n.py         English and Chinese UI texts
  errors.py       notice codes returned by the business logic (translated when shown)
  guard.py        only handle private chats and the review group; leave other groups
  permissions.py  reviewer permissions (REVIEWERS)
  spam.py         spam checks: keywords, link limit
  ratelimit.py    automatic waiting and retrying when rate-limited
  keyboards.py    colored inline buttons
  album.py        album collection
  timeutil.py     time parsing
  handlers/
    user.py       private chat: submitting, editing, /me
    review.py     review group: buttons and commands
tests/            unit and end-to-end tests
scripts/          multi-arch image build script
```

### Publishing images (for your own fork)

On every push to `main` or `v*` tag, GitHub Actions builds amd64 + arm64 images and publishes them to `ghcr.io/<owner>/tg-submit-bot`.

To publish to Docker Hub as well, add the variable `DOCKERHUB_USERNAME` and the secret `DOCKERHUB_TOKEN` (a Docker Hub access token with Read & Write permission) under **Settings → Secrets and variables → Actions** in your repository.

You can also build and push locally: `scripts/build-multiarch.sh <image:tag>`.

## License

[MIT](LICENSE)
