from __future__ import annotations

import json
import math
import os
import re
import time
from email.utils import parsedate_to_datetime
from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable
from xml.etree import ElementTree

try:
    import praw
except ImportError:
    praw = None
import requests
from dotenv import load_dotenv


OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
THREADS_GRAPH_URL = "https://graph.threads.net/v1.0"


@dataclass(frozen=True)
class Config:
    reddit_source_mode: str
    reddit_client_id: str
    reddit_client_secret: str
    reddit_user_agent: str
    reddit_subreddits: list[str]
    reddit_time_filters: list[str]
    reddit_scan_limit: int
    reddit_min_score: int
    reddit_min_comments: int
    reddit_max_post_age_days: int
    reddit_min_title_interest: float
    reddit_trash_title_keywords: list[str]
    reddit_excluded_authors: set[str]
    openrouter_api_key: str
    openrouter_model: str
    openrouter_site_url: str | None
    openrouter_app_name: str
    telegram_bot_token: str
    telegram_channel_id: str
    threads_enabled: bool
    threads_access_token: str
    threads_user_id: str
    threads_max_chars: int
    posts_per_run: int
    telegram_max_chars: int
    state_file: Path
    prepared_posts_dir: Path
    posted_posts_dir: Path
    daily_post_limit: int
    daily_interval_min_minutes: int
    daily_interval_max_minutes: int
    daily_start_hour: int
    daily_timezone: str
    daily_state_file: Path


@dataclass(frozen=True)
class RedditStory:
    post_id: str
    title: str
    text: str
    score: int
    comments: int
    created_utc: float
    trash_score: float
    author: str
    subreddit: str
    permalink: str


@dataclass(frozen=True)
class TranslatedStory:
    title: str
    body: str


@dataclass(frozen=True)
class FeedStory:
    post_id: str
    title: str
    text: str
    created_utc: float
    author: str
    subreddit: str
    permalink: str
    links: list[str]


def require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def load_config() -> Config:
    load_dotenv(".env.example")
    load_dotenv(override=True)

    subreddits = [
        subreddit.strip().strip("/")
        for subreddit in os.getenv("REDDIT_SUBREDDITS", "AskReddit").split(",")
        if subreddit.strip()
    ]
    if not subreddits:
        raise RuntimeError("REDDIT_SUBREDDITS must contain at least one subreddit")

    reddit_source_mode = os.getenv("REDDIT_SOURCE_MODE", "api").strip().lower()
    if reddit_source_mode not in {"api", "rss"}:
        raise RuntimeError("REDDIT_SOURCE_MODE must be either 'api' or 'rss'")

    return Config(
        reddit_source_mode=reddit_source_mode,
        reddit_client_id=(
            require_env("REDDIT_CLIENT_ID") if reddit_source_mode == "api" else os.getenv("REDDIT_CLIENT_ID", "")
        ),
        reddit_client_secret=(
            require_env("REDDIT_CLIENT_SECRET")
            if reddit_source_mode == "api"
            else os.getenv("REDDIT_CLIENT_SECRET", "")
        ),
        reddit_user_agent=require_env("REDDIT_USER_AGENT"),
        reddit_subreddits=subreddits,
        reddit_time_filters=parse_csv(
            os.getenv("REDDIT_TIME_FILTERS", os.getenv("REDDIT_TIME_FILTER", "year,month,week,all"))
        ),
        reddit_scan_limit=int(os.getenv("REDDIT_SCAN_LIMIT", "25")),
        reddit_min_score=int(os.getenv("REDDIT_MIN_SCORE", "500")),
        reddit_min_comments=int(os.getenv("REDDIT_MIN_COMMENTS", "80")),
        reddit_max_post_age_days=int(os.getenv("REDDIT_MAX_POST_AGE_DAYS", "1825")),
        reddit_min_title_interest=float(os.getenv("REDDIT_MIN_TITLE_INTEREST", "1")),
        reddit_trash_title_keywords=parse_csv(
            os.getenv(
                "REDDIT_TRASH_TITLE_KEYWORDS",
                "aita,aitah,cheating,affair,divorce,wedding,family,parents,"
                "mother-in-law,mil,boyfriend,girlfriend,husband,wife,ex,"
                "revenge,drama,secret,lie,lied,betrayal,kicked out,cut off,"
                "inheritance,pregnant,baby,neighbor,coworker,boss,roommate",
            )
        ),
        reddit_excluded_authors=set(parse_csv(os.getenv("REDDIT_EXCLUDED_AUTHORS", ""))),
        openrouter_api_key=require_env("OPENROUTER_API_KEY"),
        openrouter_model=os.getenv("OPENROUTER_MODEL", "openai/gpt-4o-mini").strip(),
        openrouter_site_url=os.getenv("OPENROUTER_SITE_URL", "").strip() or None,
        openrouter_app_name=os.getenv("OPENROUTER_APP_NAME", "Reddit Telegram Story Bot").strip(),
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", "").strip(),
        telegram_channel_id=os.getenv("TELEGRAM_CHANNEL_ID", "").strip(),
        threads_enabled=parse_bool(os.getenv("THREADS_ENABLED", "false")),
        threads_access_token=os.getenv("THREADS_ACCESS_TOKEN", "").strip(),
        threads_user_id=os.getenv("THREADS_USER_ID", "me").strip() or "me",
        threads_max_chars=int(os.getenv("THREADS_MAX_CHARS", "500")),
        posts_per_run=int(os.getenv("POSTS_PER_RUN", "3")),
        telegram_max_chars=int(os.getenv("TELEGRAM_MAX_CHARS", "3900")),
        state_file=Path(os.getenv("STATE_FILE", "posted_posts.json")),
        prepared_posts_dir=Path(os.getenv("PREPARED_POSTS_DIR", "prepared_posts")),
        posted_posts_dir=Path(os.getenv("POSTED_POSTS_DIR", "posted_posts_archive")),
        daily_post_limit=int(os.getenv("DAILY_POST_LIMIT", "5")),
        daily_interval_min_minutes=int(os.getenv("DAILY_INTERVAL_MIN_MINUTES", "120")),
        daily_interval_max_minutes=int(os.getenv("DAILY_INTERVAL_MAX_MINUTES", "180")),
        daily_start_hour=int(os.getenv("DAILY_START_HOUR", "10")),
        daily_timezone=os.getenv("DAILY_TIMEZONE", "Europe/Moscow").strip() or "Europe/Moscow",
        daily_state_file=Path(os.getenv("DAILY_STATE_FILE", "daily_post_state.json")),
    )


def parse_csv(value: str) -> list[str]:
    return [item.strip().lower() for item in value.split(",") if item.strip()]


def parse_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def load_posted_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return set()

    if not isinstance(data, list):
        return set()
    return {str(item) for item in data}


def save_posted_ids(path: Path, posted_ids: Iterable[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(sorted(set(posted_ids)), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def make_reddit_client(config: Config):
    if praw is None:
        raise RuntimeError("Install praw or set REDDIT_SOURCE_MODE=rss")

    return praw.Reddit(
        client_id=config.reddit_client_id,
        client_secret=config.reddit_client_secret,
        user_agent=config.reddit_user_agent,
        check_for_async=False,
    )


def collect_popular_stories(
    reddit,
    config: Config,
    posted_ids: set[str],
) -> list[RedditStory]:
    if config.reddit_source_mode == "rss":
        return collect_popular_stories_from_rss(config, posted_ids)

    if reddit is None:
        raise RuntimeError("Reddit API client is required when REDDIT_SOURCE_MODE=api")

    stories: list[RedditStory] = []
    now = time.time()

    for subreddit_name in config.reddit_subreddits:
        subreddit = reddit.subreddit(subreddit_name)
        for submission in collect_subreddit_candidates(subreddit, config):
            if submission.id in posted_ids:
                continue
            if getattr(submission, "stickied", False):
                continue
            author = str(submission.author) if submission.author else "[deleted]"
            if author.lower() in config.reddit_excluded_authors:
                continue
            if submission.score < config.reddit_min_score:
                continue
            if submission.num_comments < config.reddit_min_comments:
                continue

            age_days = (now - float(submission.created_utc)) / 86400
            if age_days > config.reddit_max_post_age_days:
                continue

            title_interest = title_interest_score(
                submission.title,
                config.reddit_trash_title_keywords,
            )
            if title_interest < config.reddit_min_title_interest:
                continue

            text = normalize_reddit_text(submission.selftext or "")
            if not text:
                continue
            if submission.over_18:
                continue

            stories.append(
                RedditStory(
                    post_id=submission.id,
                    title=submission.title.strip(),
                    text=text,
                    score=int(submission.score),
                    comments=int(submission.num_comments),
                    created_utc=float(submission.created_utc),
                    trash_score=calculate_trash_score(
                        score=int(submission.score),
                        comments=int(submission.num_comments),
                        age_days=age_days,
                        max_age_days=config.reddit_max_post_age_days,
                        title_interest=title_interest,
                    ),
                    author=author,
                    subreddit=str(submission.subreddit.display_name),
                    permalink=f"https://www.reddit.com{submission.permalink}",
                )
            )

    stories.sort(key=lambda story: story.trash_score, reverse=True)
    return stories[: config.posts_per_run]


def collect_popular_stories_from_rss(
    config: Config,
    posted_ids: set[str],
) -> list[RedditStory]:
    stories: list[RedditStory] = []
    seen_ids = set()
    now = time.time()
    stats = {
        "candidates": 0,
        "duplicates": 0,
        "excluded_authors": 0,
        "old": 0,
        "low_title_interest": 0,
        "empty_text": 0,
        "accepted": 0,
    }

    for subreddit_name in config.reddit_subreddits:
        for item in collect_rss_candidates(subreddit_name, config):
            stats["candidates"] += 1
            if item.post_id in seen_ids or item.post_id in posted_ids:
                stats["duplicates"] += 1
                continue
            seen_ids.add(item.post_id)
            if item.author.lower() in config.reddit_excluded_authors:
                stats["excluded_authors"] += 1
                continue

            age_days = (now - item.created_utc) / 86400
            if age_days > config.reddit_max_post_age_days:
                stats["old"] += 1
                continue

            title_interest = title_interest_score(item.title, config.reddit_trash_title_keywords)
            if title_interest < config.reddit_min_title_interest:
                stats["low_title_interest"] += 1
                continue

            original_post_id = item.post_id
            item = resolve_update_story(item, config)
            if item.post_id != original_post_id and item.post_id in posted_ids:
                stats["duplicates"] += 1
                continue

            text = normalize_reddit_text(item.text)
            if not text:
                stats["empty_text"] += 1
                continue

            stats["accepted"] += 1
            stories.append(
                RedditStory(
                    post_id=item.post_id,
                    title=item.title,
                    text=text,
                    score=0,
                    comments=0,
                    created_utc=item.created_utc,
                    trash_score=calculate_rss_trash_score(
                        age_days=age_days,
                        max_age_days=config.reddit_max_post_age_days,
                        title_interest=title_interest,
                    ),
                    author=item.author,
                    subreddit=item.subreddit,
                    permalink=item.permalink,
                )
            )

    stories.sort(key=lambda story: story.trash_score, reverse=True)
    print(
        "RSS selection stats: "
        + ", ".join(f"{key}={value}" for key, value in stats.items())
    )
    return stories[: config.posts_per_run]


def collect_rss_candidates(subreddit_name: str, config: Config):
    for time_filter in config.reddit_time_filters:
        url = f"https://www.reddit.com/r/{subreddit_name}/top/.rss?t={time_filter}&limit={config.reddit_scan_limit}"
        print(f"Reading RSS feed: r/{subreddit_name} top {time_filter}")
        yield from fetch_reddit_rss(url, subreddit_name, config)
        time.sleep(1.5)

    url = f"https://www.reddit.com/r/{subreddit_name}/hot/.rss?limit={config.reddit_scan_limit}"
    print(f"Reading RSS feed: r/{subreddit_name} hot")
    yield from fetch_reddit_rss(url, subreddit_name, config)
    time.sleep(1.5)


def fetch_reddit_rss(url: str, subreddit_name: str, config: Config):
    response = get_reddit_rss_response(url, config)
    if response is None:
        return

    root = ElementTree.fromstring(response.text)
    if root.tag.endswith("feed"):
        yield from parse_atom_feed(root, subreddit_name)
    else:
        yield from parse_rss_feed(root, subreddit_name)


def get_reddit_rss_response(url: str, config: Config) -> requests.Response | None:
    headers = {
        "User-Agent": config.reddit_user_agent,
        "Accept": "application/atom+xml, application/rss+xml, application/xml;q=0.9, */*;q=0.8",
    }

    for attempt in range(2):
        try:
            response = requests.get(url, headers=headers, timeout=30)
        except requests.RequestException as exc:
            print(f"Skipping RSS feed after network error: {url} ({exc})")
            return None

        if response.status_code == 429:
            retry_after = int(response.headers.get("Retry-After", "8"))
            if attempt == 0:
                print(f"Reddit rate limit for RSS feed. Waiting {retry_after}s: {url}")
                time.sleep(retry_after)
                continue
            print(f"Skipping RSS feed after rate limit: {url}")
            return None

        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            print(f"Skipping RSS feed after HTTP error: {url} ({exc})")
            return None

        return response

    return None


def parse_atom_feed(root: ElementTree.Element, subreddit_name: str):
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    for entry in root.findall("atom:entry", ns):
        title = find_text(entry, "atom:title", ns)
        content = find_text(entry, "atom:content", ns) or find_text(entry, "atom:summary", ns)
        updated = find_text(entry, "atom:updated", ns)
        author = find_text(entry, "atom:author/atom:name", ns) or "[unknown]"
        link = find_atom_link(entry) or find_text(entry, "atom:id", ns)
        yield make_story_from_feed_item(title, content, updated, author, link, subreddit_name)


def parse_rss_feed(root: ElementTree.Element, subreddit_name: str):
    for item in root.findall("./channel/item"):
        title = find_text(item, "title")
        content = find_text(item, "{http://purl.org/rss/1.0/modules/content/}encoded") or find_text(item, "description")
        created = find_text(item, "pubDate")
        author = find_text(item, "{http://purl.org/dc/elements/1.1/}creator") or "[unknown]"
        link = find_text(item, "link")
        yield make_story_from_feed_item(title, content, created, author, link, subreddit_name)


def find_text(element: ElementTree.Element, path: str, ns: dict[str, str] | None = None) -> str:
    found = element.find(path, ns or {})
    if found is None or found.text is None:
        return ""
    return found.text.strip()


def find_atom_link(entry: ElementTree.Element) -> str:
    for link in entry.findall("{http://www.w3.org/2005/Atom}link"):
        href = link.attrib.get("href", "")
        if "/comments/" in href:
            return href
    return ""


def make_story_from_feed_item(
    title: str,
    content: str,
    created: str,
    author: str,
    link: str,
    subreddit_name: str,
) -> FeedStory:
    permalink = normalize_reddit_link(link)
    post_id = extract_post_id(permalink) or str(abs(hash(permalink or title)))
    created_utc = parse_feed_datetime(created)
    text = feed_html_to_text(content)
    links = extract_reddit_links_from_html(content)

    return FeedStory(
        post_id=post_id,
        title=title.strip(),
        text=text,
        created_utc=created_utc,
        author=author.strip() or "[unknown]",
        subreddit=subreddit_name,
        permalink=permalink,
        links=links,
    )


def normalize_reddit_link(link: str) -> str:
    link = link.strip()
    if link.startswith("/"):
        return f"https://www.reddit.com{link}"
    return link


def extract_post_id(link: str) -> str:
    match = re.search(r"/comments/([^/]+)/", link)
    return match.group(1) if match else ""


class LinkExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        for name, value in attrs:
            if name.lower() == "href" and value:
                self.links.append(normalize_reddit_link(unescape(value)))


def extract_reddit_links_from_html(value: str) -> list[str]:
    parser = LinkExtractor()
    parser.feed(value or "")
    links = []
    for link in parser.links:
        if "reddit.com/r/" in link and "/comments/" in link:
            links.append(link)
    return links


def is_update_story(title: str, text: str) -> bool:
    sample = f"{title}\n{text[:600]}".lower()
    return bool(
        re.search(
            r"\b(update|final update|update\s*\d+|part\s*2|part\s*ii|"
            r"решил[аи]? написать обновление|обновление|апдейт)\b",
            sample,
        )
    )


def find_original_story_link(item: FeedStory) -> str:
    for link in item.links:
        if extract_post_id(link) and extract_post_id(link) != item.post_id:
            return link
    return ""


def resolve_update_story(item: FeedStory, config: Config) -> FeedStory:
    if not is_update_story(item.title, item.text):
        return item

    original_link = find_original_story_link(item)
    if not original_link:
        print(f"Skipping update without original story link: {item.permalink}")
        return FeedStory(
            post_id=item.post_id,
            title=item.title,
            text="",
            created_utc=item.created_utc,
            author=item.author,
            subreddit=item.subreddit,
            permalink=item.permalink,
            links=item.links,
        )

    original = fetch_reddit_json_story(original_link, config)
    if original is None or not original.text:
        print(f"Skipping update because original story could not be loaded: {item.permalink}")
        return FeedStory(
            post_id=item.post_id,
            title=item.title,
            text="",
            created_utc=item.created_utc,
            author=item.author,
            subreddit=item.subreddit,
            permalink=item.permalink,
            links=item.links,
        )

    merged_text = (
        "ОРИГИНАЛЬНАЯ ИСТОРИЯ:\n"
        f"{original.text}\n\n"
        "ОБНОВЛЕНИЕ:\n"
        f"{item.text}"
    )
    return FeedStory(
        post_id=f"{original.post_id}+{item.post_id}",
        title=f"{original.title} — обновление",
        text=merged_text,
        created_utc=item.created_utc,
        author=item.author,
        subreddit=item.subreddit,
        permalink=item.permalink,
        links=[original.permalink, *item.links],
    )


def fetch_reddit_json_story(link: str, config: Config) -> FeedStory | None:
    post_id = extract_post_id(link)
    if not post_id:
        return None

    json_url = normalize_reddit_link(link).split("?")[0].rstrip("/") + ".json"
    try:
        response = requests.get(
            json_url,
            headers={"User-Agent": config.reddit_user_agent},
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError, KeyError, IndexError) as exc:
        print(f"Could not load original Reddit JSON: {json_url} ({exc})")
        return None

    try:
        post = data[0]["data"]["children"][0]["data"]
    except (KeyError, IndexError, TypeError):
        return None

    return FeedStory(
        post_id=str(post.get("id") or post_id),
        title=str(post.get("title") or "").strip(),
        text=normalize_reddit_text(str(post.get("selftext") or "")),
        created_utc=float(post.get("created_utc") or time.time()),
        author=str(post.get("author") or "[unknown]"),
        subreddit=str(post.get("subreddit") or ""),
        permalink=normalize_reddit_link(str(post.get("permalink") or link)),
        links=[],
    )


def parse_feed_datetime(value: str) -> float:
    if not value:
        return time.time()
    try:
        return parsedate_to_datetime(value).timestamp()
    except (TypeError, ValueError):
        try:
            return time.mktime(time.strptime(value[:19], "%Y-%m-%dT%H:%M:%S"))
        except ValueError:
            return time.time()


def feed_html_to_text(value: str) -> str:
    value = unescape(value or "")
    value = re.sub(r"<br\s*/?>", "\n", value, flags=re.IGNORECASE)
    value = re.sub(r"</p\s*>", "\n\n", value, flags=re.IGNORECASE)
    value = re.sub(r"<[^>]+>", "", value)
    value = unescape(value)
    return normalize_reddit_text(value)


def calculate_rss_trash_score(
    age_days: float,
    max_age_days: int,
    title_interest: float,
) -> float:
    freshness = 1.0 - min(age_days / max(max_age_days, 1), 1.0) * 0.55
    title_bonus = 1.0 + min(title_interest, 8.0) * 0.25
    return freshness * title_bonus


def collect_subreddit_candidates(subreddit, config: Config):
    seen_ids = set()

    for time_filter in config.reddit_time_filters:
        for submission in subreddit.top(time_filter=time_filter, limit=config.reddit_scan_limit):
            if submission.id in seen_ids:
                continue
            seen_ids.add(submission.id)
            yield submission

    for submission in subreddit.hot(limit=config.reddit_scan_limit):
        if submission.id in seen_ids:
            continue
        seen_ids.add(submission.id)
        yield submission


def title_interest_score(title: str, keywords: list[str]) -> float:
    normalized = title.lower()
    score = 0.0

    for keyword in keywords:
        if keyword and keyword in normalized:
            score += 1.4

    if "?" in title:
        score += 0.6
    if any(mark in title for mark in ("!", "...")):
        score += 0.4
    if re.search(r"\b(i|my|me|we|our)\b", normalized):
        score += 0.7
    if re.search(r"\b(throwaway|confession)\b", normalized):
        score += 1.0
    if re.search(r"\b(ruined|destroyed|caught|exposed|refused|forced|left|banned)\b", normalized):
        score += 1.0
    if 45 <= len(title) <= 180:
        score += 0.5

    return score


def calculate_trash_score(
    score: int,
    comments: int,
    age_days: float,
    max_age_days: int,
    title_interest: float,
) -> float:
    # Reddit does not expose public view counts for arbitrary posts.
    # Score and comments are the best available popularity proxy.
    engagement = math.log1p(max(score, 0)) * 2.0 + math.log1p(max(comments, 0)) * 4.5
    comment_heat = min(comments / max(score, 1), 1.5)
    freshness = 1.0 - min(age_days / max(max_age_days, 1), 1.0) * 0.55
    title_bonus = 1.0 + min(title_interest, 8.0) * 0.15

    return engagement * (1.0 + comment_heat * 0.35) * freshness * title_bonus


def normalize_reddit_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def translate_story(story: RedditStory, config: Config) -> TranslatedStory:
    prompt = f"""
Ты литературный редактор русскоязычного Telegram-канала с личными историями.

Сделай не сухой дословный перевод, а готовую к публикации русскую версию истории.

Требования:
1. Сохрани все факты, хронологию, отношения между людьми и эмоциональный тон автора.
2. Пиши естественным русским языком: складно, живо, как цельный интересный рассказ.
3. Убирай англоязычную кальку. Фразы вроде AITA, MIL, OP, ex, baby shower, custody объясняй по-русски внутри текста, если они важны.
4. Не добавляй событий и выводов, которых нет в оригинале. Можно только мягко переформулировать для ясности.
5. Если в тексте есть блоки "ОРИГИНАЛЬНАЯ ИСТОРИЯ" и "ОБНОВЛЕНИЕ", сохрани эту структуру: сначала начало истории, потом обновление.
6. Не оставляй непонятные обрывки вроде "он", "она", "это" без контекста, если в русском тексте можно аккуратно уточнить по оригиналу.
7. Не упоминай Reddit, сабреддит, перевод, оригинал или английский язык.
8. Там, где автор явно эмоционален, можно сохранить короткую эмоциональную фразу капсом: "Я ПРОСТО НЕ ВЫДЕРЖАЛА", "МНЕ БЫЛО СТЫДНО", но не злоупотребляй.
9. Заголовок должен быть цепляющим, но не кликбейтным, на русском.
10. Разбей текст на короткие абзацы, чтобы его было удобно читать в Telegram.
11. Верни только JSON с полями "title" и "body".

Оригинальный заголовок:
{story.title}

Оригинальный текст:
{story.text}
""".strip()

    payload = {
        "model": config.openrouter_model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Ты сильный литературный редактор и переводчик. "
                    "Твоя задача - превращать англоязычные личные истории в живой, понятный, "
                    "цельный русский текст для Telegram, не искажая факты."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.55,
        "response_format": {"type": "json_object"},
    }
    headers = {
        "Authorization": f"Bearer {config.openrouter_api_key}",
        "Content-Type": "application/json",
    }
    if config.openrouter_site_url:
        headers["HTTP-Referer"] = config.openrouter_site_url
    if config.openrouter_app_name:
        headers["X-Title"] = config.openrouter_app_name

    response = requests.post(
        OPENROUTER_URL,
        headers=headers,
        json=payload,
        timeout=120,
    )
    response.raise_for_status()

    content = response.json()["choices"][0]["message"]["content"]
    data = json.loads(content)
    return TranslatedStory(
        title=str(data["title"]).strip(),
        body=normalize_reddit_text(str(data["body"])),
    )


def split_for_telegram(text: str, limit: int) -> list[str]:
    if len(text) <= limit:
        return [text]

    parts: list[str] = []
    remaining = text.strip()

    while remaining:
        if len(remaining) <= limit:
            parts.append(remaining)
            break

        chunk = remaining[:limit]
        split_at = max(
            chunk.rfind("\n\n"),
            chunk.rfind(". "),
            chunk.rfind("! "),
            chunk.rfind("? "),
        )
        if split_at < limit * 0.55:
            split_at = chunk.rfind(" ")
        if split_at < limit * 0.40:
            split_at = limit

        parts.append(remaining[:split_at].strip())
        remaining = remaining[split_at:].strip()

    return parts


def build_telegram_messages(
    translated: TranslatedStory,
    story: RedditStory,
    max_chars: int,
) -> list[str]:
    title = translated.title.strip()
    body = translated.body.strip()
    source_line = build_source_line(story)
    header = build_post_header(title)

    first_prefix = f"{header}\n\n"
    first_suffix = f"\n\n{source_line}"
    single_message = first_prefix + format_body_html(body) + first_suffix
    if len(single_message) <= max_chars:
        return [single_message]

    first_plain_budget = max_chars - len(first_prefix) - len("\n\nЧасть 1/99")
    regular_plain_budget = max_chars - len("\n\nЧасть 99/99") - len(f"\n\n{source_line}")
    plain_budget = max(500, min(first_plain_budget, regular_plain_budget))
    plain_parts = split_for_telegram(body, plain_budget)

    messages = []
    total = len(plain_parts)
    for index, part in enumerate(plain_parts, start=1):
        prefix = first_prefix if index == 1 else ""
        suffix = f"\n\nЧасть {index}/{total}"
        if index == total:
            suffix += f"\n\n{source_line}"
        messages.append(prefix + format_body_html(part) + suffix)

    return messages


def build_post_header(title: str) -> str:
    return f"<b>{html_escape(title)}</b>"


def build_source_line(story: RedditStory) -> str:
    subreddit = html_escape(story.subreddit)
    permalink = html_escape_attr(story.permalink)
    if permalink:
        return f"Источник: <a href=\"{permalink}\">Reddit, r/{subreddit}</a>"
    return f"Источник: Reddit, r/{subreddit}"


def format_body_html(text: str) -> str:
    paragraphs = [
        paragraph.strip()
        for paragraph in re.split(r"\n{2,}", text.strip())
        if paragraph.strip()
    ]
    if not paragraphs:
        return ""

    formatted = []
    for paragraph in paragraphs:
        escaped = html_escape(paragraph)
        escaped = emphasize_caps_phrases(escaped)
        formatted.append(escaped)
    return "\n\n".join(formatted)


def emphasize_caps_phrases(text: str) -> str:
    def repl(match: re.Match) -> str:
        phrase = match.group(0)
        if phrase.startswith("<b>") or phrase.endswith("</b>"):
            return phrase
        return f"<b>{phrase}</b>"

    return re.sub(
        r"(?<![а-яА-Яa-zA-Z])([A-ZА-ЯЁ]{3,}(?:\s+[A-ZА-ЯЁ]{3,}){0,4})(?![а-яА-Яa-zA-Z])",
        repl,
        text,
    )


def html_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def html_escape_attr(text: str) -> str:
    return html_escape(text).replace('"', "&quot;")


def post_to_telegram(messages: list[str], config: Config) -> None:
    if not config.telegram_bot_token:
        raise RuntimeError("Missing required environment variable: TELEGRAM_BOT_TOKEN")
    if not config.telegram_channel_id:
        raise RuntimeError("Missing required environment variable: TELEGRAM_CHANNEL_ID")

    url = f"https://api.telegram.org/bot{config.telegram_bot_token}/sendMessage"

    for message in messages:
        response = requests.post(
            url,
            json={
                "chat_id": config.telegram_channel_id,
                "text": message,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=30,
        )
        if not response.ok:
            raise RuntimeError(
                f"Telegram sendMessage failed: HTTP {response.status_code} {response.text}"
            )
        time.sleep(1)


def build_threads_messages(
    translated: TranslatedStory,
    story: RedditStory,
    max_chars: int,
) -> list[str]:
    source = story.permalink.strip()
    full_text = (
        f"{translated.title.strip()}\n\n"
        f"{strip_html_tags(translated.body).strip()}\n\n"
        f"Источник: {source}"
    ).strip()
    return split_for_threads(full_text, max_chars)


def split_for_threads(text: str, limit: int) -> list[str]:
    if limit < 120:
        raise RuntimeError("THREADS_MAX_CHARS must be at least 120")

    plain_parts = split_for_telegram(text, limit - len("\n\n99/99"))
    if len(plain_parts) == 1:
        return plain_parts

    total = len(plain_parts)
    messages = []
    for index, part in enumerate(plain_parts, start=1):
        suffix = f"\n\n{index}/{total}"
        messages.append(part[: limit - len(suffix)].rstrip() + suffix)
    return messages


def strip_html_tags(text: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</p\s*>", "\n\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    return unescape(text)


def post_to_threads(messages: list[str], config: Config) -> None:
    if not config.threads_enabled:
        return
    if not config.threads_access_token:
        raise RuntimeError("THREADS_ENABLED=true but THREADS_ACCESS_TOKEN is missing")
    if not config.threads_user_id:
        raise RuntimeError("THREADS_ENABLED=true but THREADS_USER_ID is missing")

    reply_to_id = None
    for message in messages:
        container_id = create_threads_text_container(message, config, reply_to_id)
        published_id = publish_threads_container(container_id, config)
        reply_to_id = published_id
        time.sleep(2)


def create_threads_text_container(
    text: str,
    config: Config,
    reply_to_id: str | None = None,
) -> str:
    payload = {
        "media_type": "TEXT",
        "text": text,
        "access_token": config.threads_access_token,
    }
    if reply_to_id:
        payload["reply_to_id"] = reply_to_id

    response = requests.post(
        f"{THREADS_GRAPH_URL}/{config.threads_user_id}/threads",
        data=payload,
        timeout=30,
    )
    if not response.ok:
        raise RuntimeError(
            f"Threads container creation failed: HTTP {response.status_code} {response.text}"
        )

    container_id = str(response.json().get("id", "")).strip()
    if not container_id:
        raise RuntimeError(f"Threads container creation returned no id: {response.text}")
    return container_id


def publish_threads_container(container_id: str, config: Config) -> str:
    response = requests.post(
        f"{THREADS_GRAPH_URL}/{config.threads_user_id}/threads_publish",
        data={
            "creation_id": container_id,
            "access_token": config.threads_access_token,
        },
        timeout=30,
    )
    if not response.ok:
        raise RuntimeError(
            f"Threads publish failed: HTTP {response.status_code} {response.text}"
        )

    published_id = str(response.json().get("id", "")).strip()
    if not published_id:
        raise RuntimeError(f"Threads publish returned no id: {response.text}")
    return published_id


def main() -> None:
    config = load_config()
    posted_ids = load_posted_ids(config.state_file)
    reddit = make_reddit_client(config) if config.reddit_source_mode == "api" else None
    stories = collect_popular_stories(reddit, config, posted_ids)

    if not stories:
        print("No new stories found.")
        return

    for story in stories:
        print(
            f"Processing r/{story.subreddit}: {story.title[:90]} "
            f"(author={story.author}, score={story.score}, "
            f"comments={story.comments}, trash={story.trash_score:.2f})"
        )
        translated = translate_story(story, config)
        messages = build_telegram_messages(translated, story, config.telegram_max_chars)
        post_to_telegram(messages, config)
        posted_ids.add(story.post_id)
        save_posted_ids(config.state_file, posted_ids)
        print(f"Posted {story.post_id} in {len(messages)} message(s).")


if __name__ == "__main__":
    main()
