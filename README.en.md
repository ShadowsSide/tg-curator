# Curator

[![docker](https://github.com/ShadowsSide/tg-curator/actions/workflows/docker.yml/badge.svg)](https://github.com/ShadowsSide/tg-curator/actions/workflows/docker.yml)
[![license](https://img.shields.io/github/license/ShadowsSide/tg-curator)](LICENSE)
![python](https://img.shields.io/badge/python-3.12-blue)
![platform](https://img.shields.io/badge/platform-linux%2Famd64%20%7C%20linux%2Farm64-lightgrey)

[简体中文](README.md) | **English**

[Features](#features) · [How it works](#how-it-works) · [Quick start](#quick-start) · [Configuration](#configuration) · [Usage](#usage) · [Known limitations and risks](#known-limitations-and-risks) · [FAQ](#faq) · [Development](#development) · [License](#license)

**Curator** is a Telegram channel submission bot: users send posts to the bot in a private chat, admins review them in a review group, and approved posts are published to the channel.

Built with Python 3.12 + [aiogram 3](https://github.com/aiogram/aiogram) + SQLite, deployed with a single Docker Compose command. It uses long polling, so **you don't need a public IP or HTTPS**.

> The bot speaks **English and Chinese**. Submitters see the language of their Telegram app (Chinese for Chinese clients, English otherwise); the review group, channel signatures and the review summary use `LANGUAGE`. For an English setup, start from `.env.en.example`, which sets `LANGUAGE=en`.

## Features

**Submitting**
- Text, photos, videos, GIFs, files, audio and voice messages. Albums of several photos or videos are merged into one submission
- Submitters choose to post **signed** (with their name) or **anonymously**. Either way, admins can always see who sent it. Their previous choice is shown first
- **Formatting is kept exactly as sent**: links, bold, quotes, spoiler text, code, date/time and emoji all come through to the channel unchanged
- Submitters can **edit their post** until the review starts, either with Telegram's built-in "Edit" or by **replying** to it with `/edit`; they can also **add or remove photos** (reply to their submission with a photo to add it)
- **Spam checks** (optional): keyword blacklist, a link limit (whitelisted domains don't count) and a cooldown for new submitters. By default a hit only puts a ⚠️ Possible spam note on the control message for reviewers to judge; it can also block the submission

**Reviewer ↔ submitter messaging**
- Reviewers tap **💬 Message submitter** on the control message (or use `/msg message`); submitters simply reply to the reviewer's message (or use `/msg`). The bot relays it. Submitters always see the sender as “Reviewer”; neither side sees the other's account
- Formatting is kept, and a single photo or file can be attached; the conversation is stored and the control message shows the message count
- Possible any time during review, and for 3 days after it's published or rejected (`MSG_WINDOW_DAYS`); banned users can't send

**Reviewing**
- Each submission gets a preview in the review group (exactly what the channel will show), followed by a control message with colored buttons
- Publish now · Schedule · Reject · Ban submitter
- Publishing options: 🙈 **spoiler** (blur the media) and 🔕 **silent** (subscribers get a notification without sound)
- Pick a common reject reason with one tap (`REJECT_TEMPLATES`)
- **✏️ Edit**, **💬 Message submitter**, **✏️ Custom reason / time**: tap the button, then just reply to the bot's prompt, no commands to remember; send `/cancel` to give up
- **🖼 Media**: while pending, add, replace or remove photos and videos (up to 10); text submissions can get photos too
- Commands work as well: `/edit` to change a post, `/no reason` to reject, `/ban reason` to ban. Banning also rejects every open submission from that user
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

**English and Chinese**
- Submitters see the language of their Telegram app (Chinese clients get Chinese, everyone else English); the review group, channel signatures and the review summary use the `LANGUAGE` setting
- The command menu is shown in the client's language too

**Deployment**
- Multi-arch images for `linux/amd64` and `linux/arm64`: works on regular VPSes, ARM servers and Raspberry Pi
- Proxy support (`http://`, `socks5://`) and support for a self-hosted Bot API server

## How it works

```
                               User sends content
                                        ▼
                           Chooses signed / anonymous
                                        ▼
                     Review group: preview + control message
                                        │
Before deciding: 🙈 Spoiler · 🔕 Silent · ✏️ Edit · 🖼 Media · 💬 Message submitter
                                        │
            ┌───────────────────────────┼───────────────────────────┐
     ✅ Publish now                ⏰ Schedule             ❌ Reject / 🚫 Ban
            ▼                           ▼                           ▼
  Channel + notify user          Publish on time        Notify user (with reason)
```

## Quick start

### 1. Set up Telegram

1. Create a bot with [@BotFather](https://t.me/BotFather) and copy its token. Leave privacy mode on (the default)
2. Make the bot an admin of your **channel** with permission to post messages
3. Create a **review group** and add the bot as a regular member. By default only the group's **admins and owner** can review (`REVIEWERS`); other members get a “no permission” notice
4. Find the channel ID and review group ID (both are numbers starting with `-100`). You can use a bot such as [@RawDataBot](https://t.me/RawDataBot), or send a message in the group and open `https://api.telegram.org/bot<token>/getUpdates`. For the channel you can also use its `@username`

### 2. Deploy

```bash
git clone https://github.com/ShadowsSide/tg-curator.git
cd tg-curator
cp .env.en.example .env     # fill in BOT_TOKEN, CHANNEL_ID and REVIEW_CHAT_ID (LANGUAGE=en is already set)
docker compose up -d --build
docker compose logs -f
```

To use the prebuilt image instead of building on your server, add this to `.env`:

```bash
IMAGE=ghcr.io/shadowsside/tg-curator:latest
```

and run:

```bash
docker compose pull && docker compose up -d --no-build
```

Image tags: `latest` is the newest build of the main branch, `vX.Y.Z` are releases, and `sha-xxxxxxx` points to a specific build, which is handy for rolling back.

### 3. Updating and backups

**Back up the database before updating**: upgrades migrate the schema automatically, and some versions drop columns that are no longer used, which can't be undone.

```bash
docker compose cp bot:/app/data/bot.db ./backup-$(date +%F).db   # 1. back up the database
git pull && docker compose up -d --build                         # 2. update (build yourself)
docker compose pull && docker compose up -d --no-build           # 2. or: update (prebuilt image)
```

The database lives in the `bot-data` Docker volume.

## Configuration

Everything is configured in `.env`. See [`.env.en.example`](.env.en.example) for a full example, grouped the same way as below ([`.env.example`](.env.example) is the Chinese version).

### Required

The bot won't start without these.

| Variable | Default | Description |
|---|---|---|
| `BOT_TOKEN` | — | The bot token |
| `CHANNEL_ID` | — | Channel to publish to: `@username` or `-100…` |
| `REVIEW_CHAT_ID` | — | Review group ID |

### Common

Options most deployments adjust as needed.

| Variable | Default | Description |
|---|---|---|
| `LANGUAGE` | `zh` | Language of the review group, channel signatures and review summary: `zh` / `en` |
| `USER_LANGUAGE` | `auto` | Language submitters see: `auto` follows their Telegram app, or fix it to `zh` / `en` |
| `REVIEWERS` | `admins` | Who can review: `admins` = review group admins and owner; `all` = every member; or user IDs, combinable, e.g. `admins,123456`. Bots never count as reviewers |
| `TZ` | `Asia/Shanghai` | Time zone for scheduling and for what counts as "today" in stats |
| `SIGN_TEMPLATE` | depends on `LANGUAGE`: `Submitted by {name}` / `投稿人：{name}` | Signature for signed posts; `{name}` becomes a link to the submitter |
| `ANON_SIGNATURE` | depends on `LANGUAGE`: `Anonymous submission` / `匿名投稿` | Signature for anonymous posts; set it to empty for none |
| `REJECT_TEMPLATES` | 4 default reasons, depends on `LANGUAGE` | Reasons offered after tapping Reject, separated by `\|`, e.g. `Duplicate\|Ads`; set it to empty to skip the reason panel |
| `MAX_PENDING_PER_USER` | `5` | Maximum open submissions per user at a time |
| `SCHEDULE_PRESETS` | `09:00,12:00,18:00,21:00` | Quick time buttons in the schedule panel |
| `DEFAULT_SILENT` | `false` | Whether new submissions are published silently by default |
| `REMINDER_INTERVAL_MINUTES` | `60` | Interval of the review summary, aligned to the clock; `0` turns it off |
| `REMINDER_QUIET_HOURS` | — | Quiet hours with no summaries, e.g. `0-8` |
| `PROXY` | — | Proxy, e.g. `socks5://host:port` |
| `IMAGE` | `tg-curator:latest` | Set this when using a prebuilt image |

> Inside Docker, `127.0.0.1` means the container itself. To use a proxy running on the host, use the host's IP address or `host.docker.internal` (Docker Desktop).

### Advanced

Spam checks, messaging window, stats scope and so on; the defaults are usually fine.

| Variable | Default | Description |
|---|---|---|
| `SPAM_KEYWORDS` | empty | Keyword blacklist, comma-separated, case-insensitive; checks both the text and link addresses |
| `MAX_LINKS` | `0` | Maximum links per submission, `0` = no limit; domains in `LINK_WHITELIST` don't count |
| `LINK_WHITELIST` | empty | Domains that don't count toward the link limit, comma-separated, subdomains included, e.g. `t.me,github.com` |
| `SPAM_ACTION` | `flag` | On a keyword or link-limit hit: `flag` = submit as usual and mark the control message; `block` = refuse it, the submitter can edit and resubmit |
| `NEW_USER_COOLDOWN_MINUTES` | `0` | Submitters with nothing published yet must wait this many minutes between submissions; `0` = no limit |
| `MSG_WINDOW_DAYS` | `3` | `/msg`: days after a submission is published or rejected during which messaging stays open; always open during review |
| `LEAVE_UNKNOWN_CHATS` | `true` | Leave any other group or channel the bot is added to; `false` stays but never responds. The publishing channel and its linked discussion group (detected at startup) are always kept |
| `ALBUM_DELAY` | `1.5` | Seconds to wait while collecting the parts of an album |
| `REMINDER_ONLY_WHEN_PENDING` | `true` | Only post the summary when something is waiting for review |
| `STATS_SCOPE` | `today` | `today`: accepted/rejected counts cover today only; `all`: all time |
| `TELEGRAM_API_URL` | — | Self-hosted Bot API server, which lifts the official 20 MB / 50 MB file limits |

## Usage

### Submitters (private chat with the bot)

| Action | Description |
|---|---|
| Send any content | Starts a submission, then choose signed or anonymous. Your previous choice is marked “(last time)” and shown first; you still tap it |
| Edit the original message with Telegram's "Edit" | Changes the submission until the review starts (scheduled, published, rejected): text, formatting, or even the image |
| Reply to your submission with a photo / video | The choice panel gets an extra **➕ Add to that submission** button that adds the new photos to it; or submit them as a new submission as usual. Only drafts and pending submissions can take more |
| 🗑 Remove a photo / video | Shown on the bot's message while a draft or pending submission has 2 or more photos/videos; tap it and pick the one to remove. Nothing can be changed once the review has started (scheduled, published, rejected) |
| `/edit new content` | Only works as a **reply** to your submission (or the bot's message about it); without a reply nothing is changed |
| `/edit` (as a reply) | Shows the current content with formatting, so you can copy and change it |
| Reply to the reviewer's message | Sent to the reviewers as a message (text, a photo or a file), no `/msg` needed |
| `/msg message` | Message the reviewers: **reply** to the reviewer's message or your submission |
| `/me` | Your submission stats |

### Admins (review group)

Buttons on the control message: **✅ Publish now**, **⏰ Schedule**, **❌ Reject**, **🚫 Ban submitter**, **✏️ Edit**, **💬 Message submitter**, **🖼 Media**, plus the **🙈 Spoiler** and **🔕 Silent** toggles.

#### Reply prompts

**✏️ Edit**, **💬 Message submitter**, **✏️ Custom reason** on the reason panel and **✏️ Custom time** on the schedule panel post a “please reply to this message…” prompt. Just reply to it, no commands to remember:
- Only the reply of whoever tapped the button counts (anonymous admins excepted); send `/cancel` to give up (as a reply to a prompt it drops that one; on its own it drops all your open prompts)
- **Edit** first posts the current content with formatting so you can copy and change it; the prompt and that copy are deleted once you're done
- **Custom reason** rejects as soon as you send the reason, with no extra confirmation
- Prompts are stored in the database, so they still work after a restart; prompts left unanswered for 24 hours are deleted

#### Changing photos and videos

**🖼 Media** (only while pending) opens the media panel: **➕ Add photo / video** (an album reply works too), **🔁 Replace N** and **🗑 Remove N** (asks to confirm; the last one can't be removed). Photos and videos only, at most 10 per submission; submissions with a file, GIF or audio can't use it. A text submission can get photos too: its text becomes their caption (see “Known limitations and risks” below).

Every edit posts a new preview. The review group keeps only the original preview and the latest edited one; older edited previews are deleted (Telegram doesn't let bots delete messages older than 48 hours, so those stay).

#### Confirmation and reject reasons

To avoid accidental taps, **Publish now, Reject and Ban** first switch to “Confirm / Back” buttons and only act on the second tap. Scheduling, retrying and the `/no` and `/ban` commands need no confirmation.

**❌ Reject** first asks for a reason (`REJECT_TEMPLATES`; defaults: Duplicate, Off-topic, Low quality, Advertising; or “No reason”). The confirm button shows the chosen reason, and the reason is sent to the submitter. For a reason of your own, tap **✏️ Custom reason** or use `/no reason`.

#### Commands

The commands below do the same as the buttons, for those who prefer commands. Use them by **replying** to a submission's preview or control message. The bot never shows submission numbers, and no command needs one:

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
| `/cancel` | Drops prompts waiting for your reply: as a reply to a prompt it drops that one; on its own it drops all of yours |

`/ban` and `/unban` also accept a user ID (`/ban <user ID> reason`) for users with nothing under review, or to ban someone in advance. Each scheduled post in `/queue` has a “view” link that jumps to its control message.

## Known limitations and risks

**Review actions**
- **More taps**: Publish now, Reject and Ban always need a second tap, and Reject first asks for a reason by default (Reject → reason → Confirm, three taps). Set `REJECT_TEMPLATES=` to skip the reason; the confirmation itself can't be turned off
- **The confirm panel can be reset**: if the control message refreshes while you're about to confirm (the submitter edits, someone sends `/msg`, …), the buttons go back to normal and you need to tap again. Nothing runs by accident
- **Changing `REJECT_TEMPLATES` can shift old panels**: buttons store the reason's position. After reordering the reasons and restarting, a panel opened before the restart picks the reason by the new order; an out-of-range position means “No reason”. Finish any rejection in progress before changing it
- **Reasons can't contain `|`**: it's the separator
- **The review group hits rate limits sooner**: the confirm and reason panels each edit the control message once more, so with heavy review traffic Telegram's limits come sooner. The bot waits and retries automatically, but actions get slower

**Changing photos and videos**
- **Adding photos to a text submission**: the text limit drops from 4096 to 1024 characters (longer text can't take photos), the link preview goes away, it can't turn back into plain text, and the post looks different in the channel (text under the photos)
- **Replaced or removed photos can't be brought back**: the original is stored (`original_items`), but the bot has no way to restore it
- **Reviewers aren't notified when a submitter changes photos**: a new preview appears and the control message shows “edited (submitter)”
- **Submitters keep the old button after the review starts**: tapping it explains that nothing can be changed any more and removes the button

**Spam checks**
- **Chinese keywords can over-match**: Chinese has no word boundaries, so keywords match as substrings (e.g. “微信” also matches “微信公众号推荐”). That's why the default only flags (`SPAM_ACTION=flag`); watch the flags for a while before switching to `block`
- **Blocking doesn't tell the submitter which word matched**: so it can't be dodged on purpose, but the submitter may not know what to change
- **Only URLs and hyperlinks count as links**: `@usernames`, emails and phone numbers don't
- **Edits only update the flags, never block**: even with `SPAM_ACTION=block`, adding a keyword by editing after submitting just shows a flag for reviewers
- **The cooldown only applies to submitters with nothing published yet**: one published post lifts it; it counts from the last submission, rejected ones included
- **Bad values stop the bot from starting**: a non-number in `MAX_LINKS` or `NEW_USER_COOLDOWN_MINUTES`, or a `SPAM_ACTION` other than `flag` / `block`, makes the bot exit with an error at startup

**Other**
- **An album being collected during a restart is lost or split**: the items of an album arrive separately, and the bot waits `ALBUM_DELAY` seconds in memory to collect them. If it restarts within those seconds, the items that already arrived are lost and the ones arriving after the restart become a separate submission. The submitter needs to send it again

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

Requires Python 3.12 (the version the Docker image and CI use).

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt -r requirements-dev.txt
cp .env.en.example .env && mkdir -p data
set -a; source .env; set +a
DB_PATH=./data/bot.db .venv/bin/python -m bot
```

The tests need no token and no network access. `tests/test_*.py` are unit tests; `tests/live_*.py` are end-to-end tests that run the real bot process against a mock Bot API server. Each file is a standalone script you can run on its own, and its opening docstring says what it covers. To run them all (about 4 minutes):

```bash
for f in tests/test_*.py tests/live_*.py; do .venv/bin/python "$f" || echo "FAILED: $f"; done
```

GitHub Actions (`.github/workflows/test.yml`) first checks the code with pyflakes (undefined names, unused imports and variables, …), then runs all the tests on every pull request and every push to `main`. To check locally:

```bash
.venv/bin/python -m pyflakes bot tests
```

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
    prompts.py      reply prompts (Edit, Message submitter, custom reason / time)
    stats.py        review summary, activity, scheduled queue
    scheduler.py    background jobs: scheduled publishing, draft cleanup, summary reminders
  render.py       sending content (single / album, signature, spoiler, silent) and message texts
  entities.py     message formatting (UTF-16 offsets, appending the signature)
  i18n.py         English and Chinese UI texts
  errors.py       notice codes returned by the business logic (translated when shown)
  guard.py        only handle private chats and the review group; leave other groups
  permissions.py  reviewer permissions (REVIEWERS)
  spam.py         spam checks: keywords, link limit
  media.py        rules for changing photos and videos: add, replace, remove
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

On every push to `main` or `v*` tag, GitHub Actions builds amd64 + arm64 images and publishes them to `ghcr.io/<owner>/tg-curator`.

To publish to Docker Hub as well, add the variable `DOCKERHUB_USERNAME` and the secret `DOCKERHUB_TOKEN` (a Docker Hub access token with Read & Write permission) under **Settings → Secrets and variables → Actions** in your repository.

You can also build and push locally: `scripts/build-multiarch.sh <image:tag>`.

## License

[MIT](LICENSE)
