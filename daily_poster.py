from __future__ import annotations

import json
import random
import time
from datetime import datetime, timedelta
from pathlib import Path

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


def today_key() -> str:
    return datetime.now().date().isoformat()


def seconds_until_tomorrow() -> int:
    now = datetime.now()
    tomorrow = datetime.combine(now.date() + timedelta(days=1), datetime.min.time())
    return max(int((tomorrow - now).total_seconds()), 60)


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
        state = load_daily_state(config.daily_state_file)
        key = today_key()

        if state.get("date") != key:
            state = {"date": key, "posted_count": 0}
            save_daily_state(config.daily_state_file, state)

        posted_count = int(state.get("posted_count", 0))
        if posted_count >= config.daily_post_limit:
            seconds = seconds_until_tomorrow()
            print(
                f"Daily limit reached: {posted_count}/{config.daily_post_limit}. "
                f"Sleeping until tomorrow."
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
