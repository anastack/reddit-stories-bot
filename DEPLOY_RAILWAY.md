# Deploy to Railway

This project is configured to run on Railway as a long-running worker.

## What Runs

Railway starts:

```bash
python daily_poster.py
```

The worker publishes up to `DAILY_POST_LIMIT` stories per day. Between posts it waits a random interval from `DAILY_INTERVAL_MIN_MINUTES` to `DAILY_INTERVAL_MAX_MINUTES`.

If there are no prepared posts in the queue, the worker prepares new stories first.

## Railway Setup

1. Push this repository to GitHub.
2. Create a new Railway project from the GitHub repo.
3. Set these Railway variables:

```env
REDDIT_SOURCE_MODE=rss
REDDIT_USER_AGENT=telegram-story-bot/1.0 by your_reddit_username
REDDIT_SUBREDDITS=AITAH,AmItheAsshole,relationship_advice,TrueOffMyChest,confession,tifu,entitledparents,pettyrevenge
REDDIT_TIME_FILTERS=week,month,year
REDDIT_SCAN_LIMIT=20
REDDIT_MIN_TITLE_INTEREST=1
REDDIT_MAX_POST_AGE_DAYS=1825
OPENROUTER_API_KEY=your_openrouter_key
OPENROUTER_MODEL=openai/gpt-4o-mini
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
TELEGRAM_CHANNEL_ID=@your_channel_or_numeric_id
THREADS_ENABLED=false
THREADS_ACCESS_TOKEN=
THREADS_USER_ID=me
THREADS_MAX_CHARS=500
POSTS_PER_RUN=3
TELEGRAM_MAX_CHARS=3900
STATE_FILE=data/posted_posts.json
PREPARED_POSTS_DIR=data/prepared_posts
POSTED_POSTS_DIR=data/posted_posts_archive
DAILY_POST_LIMIT=5
DAILY_INTERVAL_MIN_MINUTES=60
DAILY_INTERVAL_MAX_MINUTES=120
DAILY_STATE_FILE=data/daily_post_state.json
```

For RSS mode, leave `REDDIT_CLIENT_ID` and `REDDIT_CLIENT_SECRET` unset.

For Threads cross-posting, set:

```env
THREADS_ENABLED=true
THREADS_ACCESS_TOKEN=your_threads_access_token
THREADS_USER_ID=me
THREADS_MAX_CHARS=500
```

The bot publishes long stories as a chain of text posts. If `THREADS_ENABLED=false`, Threads is skipped completely.

## Persistent Storage

Railway's normal container filesystem can be replaced during redeploys. Add a Railway volume if you want to preserve:

- `data/posted_posts.json`
- `data/daily_post_state.json`
- `data/prepared_posts`
- `data/posted_posts_archive`

Mount the volume at:

```text
/app/data
```

If you do not add a volume, the bot can still run, but after redeploy it may forget which Reddit posts were already published.

## Manual Commands

Prepare posts without publishing:

```bash
python prepare_posts.py
```

Publish already prepared posts:

```bash
python post_prepared.py
```

Run the full daily worker:

```bash
python daily_poster.py
```

## Security

Do not commit `.env`. Add secrets only in Railway variables.

If a Telegram token or OpenRouter key was ever committed or shared, rotate it before deploying.
