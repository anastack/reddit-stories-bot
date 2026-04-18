from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from bot import (
    RedditStory,
    TranslatedStory,
    build_telegram_messages,
    load_config,
    load_posted_ids,
    post_to_telegram,
    save_posted_ids,
)


def load_prepared_posts(prepared_dir: Path) -> list[Path]:
    if not prepared_dir.exists():
        return []
    return sorted(
        path for path in prepared_dir.glob("*.json") if not path.name.startswith("_")
    )


def load_prepared_post(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def archive_post(path: Path, archive_dir: Path, data: dict) -> Path:
    archive_dir.mkdir(parents=True, exist_ok=True)
    data["status"] = "posted"
    data["posted_at"] = datetime.now(timezone.utc).isoformat()
    archived_path = archive_dir / path.name
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    shutil.move(str(path), str(archived_path))
    return archived_path


def get_messages_for_publish(data: dict, config) -> list[str]:
    source = data.get("source")
    title = data.get("title")
    body = data.get("body")

    if isinstance(source, dict) and isinstance(title, str) and isinstance(body, str):
        try:
            story = RedditStory(
                post_id=str(source.get("post_id", data.get("post_id", ""))),
                title=str(source.get("title", title)),
                text=str(source.get("text", "")),
                score=int(source.get("score", 0)),
                comments=int(source.get("comments", 0)),
                created_utc=float(source.get("created_utc", 0)),
                trash_score=float(source.get("trash_score", 0)),
                author=str(source.get("author", "")),
                subreddit=str(source.get("subreddit", "")),
                permalink=str(source.get("permalink", "")),
            )
            translated = TranslatedStory(title=title, body=body)
            messages = build_telegram_messages(translated, story, config.telegram_max_chars)
            data["messages"] = messages
            data["format_version"] = 2
            return messages
        except (TypeError, ValueError):
            pass

    messages = data.get("messages")
    if not isinstance(messages, list) or not all(isinstance(item, str) for item in messages):
        return []
    return messages


def publish_prepared_posts(config, limit: int | None = None) -> int:
    posted_ids = load_posted_ids(config.state_file)
    prepared_paths = load_prepared_posts(config.prepared_posts_dir)

    if not prepared_paths:
        print("No prepared posts found.")
        return 0

    max_posts = limit if limit is not None else config.posts_per_run
    posted_count = 0
    for path in prepared_paths:
        if posted_count >= max_posts:
            break

        data = load_prepared_post(path)
        post_id = str(data.get("post_id", ""))
        if not post_id:
            print(f"Skipping prepared file without post_id: {path}")
            continue
        if post_id in posted_ids:
            archived_path = archive_post(path, config.posted_posts_dir, data)
            print(f"Already posted, archived duplicate: {archived_path}")
            continue

        messages = get_messages_for_publish(data, config)
        if not messages:
            print(f"Skipping prepared file without valid messages: {path}")
            continue

        print(f"Posting prepared story {post_id}: {data.get('title', path.name)}")
        post_to_telegram(messages, config)
        posted_ids.add(post_id)
        save_posted_ids(config.state_file, posted_ids)
        archived_path = archive_post(path, config.posted_posts_dir, data)
        posted_count += 1
        print(f"Posted and archived: {archived_path}")

    if posted_count == 0:
        print("No prepared posts were published.")
    return posted_count


def main() -> None:
    config = load_config()
    publish_prepared_posts(config)


if __name__ == "__main__":
    main()
