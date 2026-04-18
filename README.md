# Reddit Telegram Story Bot

Бот ищет популярные публичные истории других людей на Reddit, переводит их на русский через OpenRouter, сохраняет стиль автора, делает цепляющий заголовок, делит длинный текст на части и публикует в Telegram-канал.

## Режимы работы

Есть два режима:

- `REDDIT_SOURCE_MODE=rss` - работает без Reddit API keys. Бот читает публичные `.rss`-ленты сабреддитов. Точные `score` и число комментариев в этом режиме недоступны, поэтому популярность берется из Reddit top feeds.
- `REDDIT_SOURCE_MODE=api` - полноценный режим через Reddit API. Нужны `REDDIT_CLIENT_ID` и `REDDIT_CLIENT_SECRET`. В этом режиме бот видит `score`, количество комментариев и точнее ранжирует истории.

Для запуска без Reddit API оставьте:

```env
REDDIT_SOURCE_MODE=rss
REDDIT_CLIENT_ID=
REDDIT_CLIENT_SECRET=
```

`REDDIT_USER_AGENT` все равно нужен. Это обычная строка, по которой Reddit понимает, кто делает запрос:

```env
REDDIT_USER_AGENT=telegram-story-bot/1.0 by your_reddit_username
```

## Как выбираются истории

В API-режиме бот использует:

- `score` поста;
- количество комментариев;
- свежесть поста;
- "трешовость" и конфликтность заголовка.

В RSS-режиме бот использует:

- Reddit top feeds: `year`, `month`, `week`, `all`;
- свежесть поста;
- конфликтные слова и структуру заголовка.

Посты старше `REDDIT_MAX_POST_AGE_DAYS` отбрасываются. По умолчанию это `1825` дней, то есть примерно 5 лет.

Update-посты фильтруются отдельно: если пост выглядит как продолжение истории, бот ищет ссылку на начало. Если ссылка есть, он подтягивает начало и готовит единый пост в порядке "сначала оригинальная история, потом обновление". Если ссылки на начало нет, такой пост пропускается.

Если нужно исключить свои аккаунты или конкретных авторов, добавьте их через запятую в `REDDIT_EXCLUDED_AUTHORS`.

## Установка

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Скопируйте настройки:

```powershell
Copy-Item .env.example .env
```

Заполните `.env`:

- `OPENROUTER_API_KEY` из OpenRouter
- `TELEGRAM_BOT_TOKEN` из `@BotFather`
- `TELEGRAM_CHANNEL_ID`, например `@my_channel`
- `REDDIT_USER_AGENT`, например `telegram-story-bot/1.0 by my_reddit_name`

Для RSS-режима `REDDIT_CLIENT_ID` и `REDDIT_CLIENT_SECRET` можно оставить пустыми.

Бот должен быть администратором Telegram-канала с правом публиковать сообщения.

## Запуск

Полный цикл сразу:

```powershell
python bot.py
```

Один запуск публикует до `POSTS_PER_RUN` новых историй. Уже опубликованные посты сохраняются в `posted_posts.json`, чтобы бот не повторялся.

Раздельный режим:

```powershell
python prepare_posts.py
```

Этот скрипт ищет истории, переводит их, готовит Telegram-сообщения и сохраняет JSON-файлы в папку `prepared_posts`.

```powershell
python post_prepared.py
```

Этот скрипт берет готовые JSON-файлы из `prepared_posts`, публикует их в канал и переносит в `posted_posts_archive`.

Так можно сначала проверить готовые посты, отредактировать JSON вручную при необходимости, а потом отдельно запустить публикацию.

Если включить `THREADS_ENABLED=true`, этот же скрипт дополнительно публикует историю в Threads. Длинные истории режутся на цепочку коротких текстовых постов.

Серверный режим автопостинга:

```powershell
python daily_poster.py
```

Этот скрипт работает постоянно: публикует одну готовую историю, ждет случайную паузу между `DAILY_INTERVAL_MIN_MINUTES` и `DAILY_INTERVAL_MAX_MINUTES`, затем публикует следующую. После `DAILY_POST_LIMIT` успешных публикаций за день он засыпает до следующего дня.

Если очередь `prepared_posts` пустая, `daily_poster.py` сам запускает подготовку новых историй.

## Настройка отбора

- `REDDIT_SUBREDDITS` - сабреддиты через запятую. Для треш-историй хорошо подходят `AITAH`, `AmItheAsshole`, `relationship_advice`, `TrueOffMyChest`, `confession`, `tifu`, `entitledparents`, `pettyrevenge`.
- `REDDIT_TIME_FILTERS` - срезы Reddit top через запятую: `hour`, `day`, `week`, `month`, `year`, `all`.
- `REDDIT_SCAN_LIMIT` - сколько постов смотреть в каждом сабреддите.
- `REDDIT_MIN_SCORE` - минимальный рейтинг поста. Работает только в API-режиме.
- `REDDIT_MIN_COMMENTS` - минимальное число комментариев. Работает только в API-режиме.
- `REDDIT_MAX_POST_AGE_DAYS` - максимальный возраст поста в днях. `1825` примерно равно 5 годам.
- `REDDIT_MIN_TITLE_INTEREST` - минимальная оценка интересности заголовка. Если бот находит мало постов, поставьте `0`.
- `REDDIT_TRASH_TITLE_KEYWORDS` - слова-маркеры для конфликтных историй: отношения, измены, семья, месть, секреты, соседи, работа и так далее.
- `REDDIT_EXCLUDED_AUTHORS` - авторы, которых нужно пропускать. Можно оставить пустым.

## Настройка публикации

- `POSTS_PER_RUN` - сколько историй публиковать за один запуск.
- `OPENROUTER_MODEL` - модель OpenRouter, например `openai/gpt-4o-mini`.
- `TELEGRAM_MAX_CHARS` - лимит символов на одно сообщение. Telegram допускает до 4096, по умолчанию оставлен запас.
- `THREADS_ENABLED` - включить или выключить публикацию в Threads.
- `THREADS_ACCESS_TOKEN` - access token Threads API.
- `THREADS_USER_ID` - id Threads-пользователя, обычно можно оставить `me`.
- `THREADS_MAX_CHARS` - лимит символов на один Threads-пост.
- `PREPARED_POSTS_DIR` - папка для готовых постов после `prepare_posts.py`.
- `POSTED_POSTS_DIR` - архив опубликованных готовых постов после `post_prepared.py`.
- `DAILY_POST_LIMIT` - сколько историй публиковать в день в режиме `daily_poster.py`.
- `DAILY_INTERVAL_MIN_MINUTES` - минимальная пауза между публикациями.
- `DAILY_INTERVAL_MAX_MINUTES` - максимальная пауза между публикациями.
- `DAILY_STATE_FILE` - файл, где хранится счетчик публикаций за текущий день.

## Автопостинг по расписанию

Проще всего запускать `python bot.py` через планировщик Windows или cron. Например, каждый запуск публикует несколько новых историй и завершает работу.

## Railway

Проект готов к деплою на Railway. Railway будет запускать worker:

```powershell
python daily_poster.py
```

Подробная инструкция лежит в [DEPLOY_RAILWAY.md](DEPLOY_RAILWAY.md).
