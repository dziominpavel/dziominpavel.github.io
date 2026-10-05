## Context

См. `proposal.md` — Why. Текущее состояние: `generate.py:sort_by_date` сортирует корректно, но `render_site:736-747` сортирует `cards` и `web_cards` отдельно и склеивает (`скачиваемые + web`). Дата web без `data:` — `datetime.now(timezone.utc).date()` в `collect_web_projects:319`, поэтому при cron каждые 30 мин (`build.yml:9`) такая карточка всегда «сегодня». Клон — `git clone --depth 1`, GitHub API уже используется для `releases/latest` с `GITHUB_TOKEN`.

## Goals / Non-Goals

**Goals:**
- Честная дата web без `data:`: последний коммит папки `web/` вместо даты сборки.
- Единая лента главной: один отсортированный поток скачиваемые + web по убыванию `date`.
- Сборка не падает при недоступности коммит-даты; поведение Benchmark и скачиваемых не меняется.

**Non-Goals:**
- Не меняем формат дат, `fmt_date`, hero-статистику, `filter.js`, sitemap, контракт `store.yaml`.
- Не меняем `--json` вывод (сейчас только скачиваемые) — вне скоупа ленты.
- Не углубляем клон ради истории `web/` — используем API, а не полный `git log`.

## Decisions

### 1. Источник коммит-даты — GitHub API `GET /repos/{repo}/commits?path=web&per_page=1`
Берём `commit.commit.committer.date` первой записи. Почему API, а не `git log` в клоне: клон `--depth 1` не видит историю `web/` (если HEAD не трогал `web/`, `log -- web/` пуст), углубление клона замедляет каждую сборку; API даёт ответ по `path` без истории и укладывается в лимит (+2 запроса на сборку при 5000/час). Fallback-цепочка: `path=web` → `git log -1 --format=%cI` HEAD уже склонированного репо → `datetime.now()` + WARN. Только последний шаг сохраняет старое поведение.

### 2. Единый рендер ленты через меченые кортежи
В `render_site` строим `merged = [("app", c) for c in cards] + [("web", w) for w in web_cards]`, один раз `sort_by_date` по `.date` (оба типа — ISO-8601, лексикографика уже проверена тестом), затем dispatch `card_html` / `web_card_html` в порядке ленты. `sort_by_date` не меняем. При равных датах стабильность `sorted` сохраняет входной порядок (скачиваемые перед web) — детерминировано без нового компаратора.

### 3. Benchmark и скачиваемые без изменений
Ветка `data:` в `collect_web_projects:321-340` остаётся как есть (приоритет `updated`). `release_card:date` (`published_at`) не трогаем. Формат `card-meta` («Обновлено …» / «v… · … · обновлено …») не трогаем — обе даты уже читаются в одном месте карточки.

## Risks / Trade-offs

- [API лимит/сбой `commits?path`] → Mitigation: fallback на HEAD/now + WARN, сборка MUST NOT падать; в CI используется `GITHUB_TOKEN`.
- [Дефолтная ветка источника не `main`] → Mitigation: запрос без `sha` бьёт в дефолтную ветку API — явно `sha` не фиксируем.
- [Смешанные форматы `2026-10-05` vs `2026-10-05T...Z`] → Mitigation: существующая лексикографика уже покрыта `test_sort_by_date_desc` (календарная дата < таймстамп того же дня — приемлемо, день тот же).
- [HEAD-дата врёт при активной не-web разработке] → Mitigation: это только fallback при недоступности API, редкий кейс; основная дата — строго `path=web`.

## Migration Plan

Миграция не нужна: изменение применяется следующей cron-сборкой, статика перезаписывается. Rollback — revert change, порядок вернётся к двум группам, дата web без `data:` — к дате сборки.
