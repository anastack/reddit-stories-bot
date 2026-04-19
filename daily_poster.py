from __future__ import annotations

import json
import random
import time
from datetime import datetime, time as datetime_time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from bot import load_config
from post_prepared import load_prepared_posts, publish_prepared_posts
from prepare_posts import prepare_new_posts


def load_daily_state(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def save_daily_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def schedule_timezone(config) -> ZoneInfo:
    return ZoneInfo(config.daily_timezone)


def now_in_schedule_timezone(config) -> datetime:
    return datetime.now(schedule_timezone(config))


def today_key(config) -> str:
    return now_in_schedule_timezone(config).date().isoformat()


def daily_start_at(value: datetime, config) -> datetime:
    start_hour = min(max(config.daily_start_hour, 0), 23)
    return datetime.combine(
        value.date(),
        datetime_time(hour=start_hour),
        tzinfo=value.tzinfo,
    )


def seconds_until_today_start(config) -> int:
    now = now_in_schedule_timezone(config)
    start = daily_start_at(now, config)
    return max(int((start - now).total_seconds()), 0)


def seconds_until_next_day_start(config) -> int:
    now = now_in_schedule_timezone(config)
    tomorrow = now + timedelta(days=1)
    start = daily_start_at(tomorrow, config)
    return max(int((start - now).total_seconds()), 60)


def sleep_between_posts(config) -> None:
    min_minutes = max(config.daily_interval_min_minutes, 1)
    max_minutes = max(config.daily_interval_max_minutes, min_minutes)
    seconds = random.randint(min_minutes * 60, max_minutes * 60)
    print(f"Waiting {seconds // 60} minutes before the next post.")
    time.sleep(seconds)


def ensure_prepared_posts(config) -> None:
    prepared_paths = load_prepared_posts(config.prepared_posts_dir)
    if prepared_paths:
        return

    print("No prepared posts in queue. Preparing new stories.")
    prepare_new_posts(config)


def main() -> None:
    print("Daily poster started.")

    while True:
        config = load_config()
        seconds = seconds_until_today_start(config)
        if seconds > 0:
            print(
                f"Waiting until {config.daily_start_hour:02d}:00 "
                f"{config.daily_timezone} before posting."
            )
            time.sleep(seconds)
            continue

        state = load_daily_state(config.daily_state_file)
        key = today_key(config)

        if state.get("date") != key:
            state = {"date": key, "posted_count": 0}
            save_daily_state(config.daily_state_file, state)

        posted_count = int(state.get("posted_count", 0))
        if posted_count >= config.daily_post_limit:
            seconds = seconds_until_next_day_start(config)
            print(
                f"Daily limit reached: {posted_count}/{config.daily_post_limit}. "
                f"Sleeping until the next posting window."
            )
            time.sleep(seconds)
            continue

        ensure_prepared_posts(config)
        published = publish_prepared_posts(config, limit=1)

        if published:
            state["posted_count"] = posted_count + published
            save_daily_state(config.daily_state_file, state)
            if state["posted_count"] >= config.daily_post_limit:
                continue
            sleep_between_posts(config)
            continue

        print("Nothing was published. Waiting 30 minutes before retry.")
        time.sleep(30 * 60)


if __name__ == "__main__":
    main()
