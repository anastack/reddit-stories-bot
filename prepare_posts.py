from __future__ import annotations

import json
import re
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from bot import (
    RedditStory,
    build_telegram_messages,
    collect_popular_stories,
    load_config,
    load_posted_ids,
    make_reddit_client,
    translate_story,
)


def load_prepared_ids(prepared_dir: Path) -> set[str]:
    if not prepared_dir.exists():
        return set()

    prepared_ids = set()
    for path in prepared_dir.glob("*.json"):
        if path.name.startswith("_"):
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        post_id = data.get("post_id")
        if post_id:
            prepared_ids.add(str(post_id))
    return prepared_ids


def make_prepared_filename(story: RedditStory) -> str:
    safe_title = re.sub(r"[^a-zA-Z0-9_-]+", "_", story.title.lower()).strip("_")
    safe_title = safe_title[:70] or "story"
    return f"{story.post_id}_{safe_title}.json"


def save_prepared_post(
    prepared_dir: Path,
    story: RedditStory,
    title: str,
    body: str,
    messages: list[str],
) -> Path:
    prepared_dir.mkdir(parents=True, exist_ok=True)
    path = prepared_dir / make_prepared_filename(story)
    data = {
        "prepared_at": datetime.now(timezone.utc).isoformat(),
        "post_id": story.post_id,
        "source": asdict(story),
        "title": title,
        "body": body,
        "messages": messages,
        "format_version": 2,
        "status": "prepared",
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def prepare_new_posts(config=None) -> int:
    if config is None:
        config = load_config()

    posted_ids = load_posted_ids(config.state_file)
    prepared_ids = load_prepared_ids(config.prepared_posts_dir)
    skip_ids = posted_ids | prepared_ids

    reddit = make_reddit_client(config) if config.reddit_source_mode == "api" else None
    stories = collect_popular_stories(reddit, config, skip_ids)

    if not stories:
        print("No new stories found for preparation.")
        return 0

    prepared_count = 0
    for story in stories:
        print(
            f"Preparing r/{story.subreddit}: {story.title[:90]} "
            f"(author={story.author}, score={story.score}, "
            f"comments={story.comments}, trash={story.trash_score:.2f})"
        )
        translated = translate_story(story, config)
        messages = build_telegram_messages(translated, story, config.telegram_max_chars)
        path = save_prepared_post(
            config.prepared_posts_dir,
            story,
            translated.title,
            translated.body,
            messages,
        )
        prepared_ids.add(story.post_id)
        prepared_count += 1
        print(f"Prepared {story.post_id}: {path}")

    return prepared_count


def main() -> None:
    prepare_new_posts()


if __name__ == "__main__":
    main()
