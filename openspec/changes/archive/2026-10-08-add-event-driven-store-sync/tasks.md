# Tasks: add-event-driven-store-sync

## 1. Событийные триггеры витрины (`.github/workflows/build.yml`)

- [x] 1.1 Добавить в `on:` блок `repository_dispatch` с типами `app-released` и `web-updated`, не трогая существующие `schedule`/`push`/`workflow_dispatch`; проверка: `python -c "import yaml;d=yaml.safe_load(open('.github/workflows/build.yml',encoding='utf-8'));on=d.get(True) or d.get('on');assert on['repository_dispatch']['types']==['app-released','web-updated']"` завершается без ошибок
- [x] 1.2 Добавить второй слот расписания `17,47 * * * *` в `on.schedule` (страховка от проваленных cron-запусков, design D5); проверка: `python -c "import yaml;d=yaml.safe_load(open('.github/workflows/build.yml',encoding='utf-8'));on=d.get(True) or d.get('on');assert len(on['schedule'])==2"` завершается без ошибок
- [x] 1.3 Запустить workflow вручную (`workflow_dispatch`) и дождаться деплоя; проверка: последний run сборки имеет статус `success`, живая витрина отдаёт свежую статику

## 2. Релизный хук в эталоне `scripts/release.ps1`

- [x] 2.1 В фазе 10, сразу после успешного `gh release create` и до `exit 0`, добавить best-effort отправку `repository_dispatch` (`event_type=app-released`, `client_payload` = `{repo, tag}`) через `gh api -X POST repos/dziominpavel/dziominpavel.github.io/dispatches`; проверка: при ошибке отправки печатается `[WARN]`, код возврата скрипта остаётся `0`, тег и релиз не откатываются (spec «Оповещение витрины о релизе»)
- [x] 2.2 Бампить `$SCRIPT_VERSION` в `scripts/release.ps1` (минорный уровень — новая функция); проверка: `powershell -ExecutionPolicy Bypass -File scripts/sync-release.ps1` (без `-Apply`, режим плана) печатает новую версию эталона, а колонка Remote у семи проектов показывает `release.ps1: устарел`
- [x] 2.3 Расширить gh-shim в `tests/test_release_phases.py` аргументной разводкой (сейчас `auth` → 0, всё остальное → 1, плюс режим `gh_ok=True`, где всё → 0): `gh release create` → 0, `gh api ... dispatches` → 1 — и добавить проверки обеих веток оповещения (доставлено → exit 0 и печать результата; отправка падает → `[WARN]`, exit 0, тег на месте); проверка: `python tests/test_release_phases.py` завершается с кодом 0 и последней строкой `ALL PASS (...)`
- [x] 2.4 Убедиться, что генератор и валидация статики не задеты; проверка: `python generate.py --out _site && python tests/test_generate.py && python tests/validate_site.py _site` завершаются с кодом 0

## 3. Разнос release-скрипта во все репозитории

- [x] 3.1 Запустить `powershell -ExecutionPolicy Bypass -File scripts/sync-release.ps1 -Apply` (удалённый канал: `release.ps1` + `release.bat` в 7 репозиториев); проверка: скрипт завершается с `[OK] все проекты согласованы с эталоном`, а `gh api repos/<repo>/contents/release.ps1` возвращает новую `$SCRIPT_VERSION` для всех семи
- [x] 3.2 Прогнать контроли корня; проверка: `python scripts/check-version.py` и `python scripts/check-commit-hygiene.py` завершаются с кодом 0

## 4. Оповещение от web-источников

- [x] 4.1 Подготовить `.github/workflows/notify-store.yml` для обоих web-источников: триггер `push` c `paths: [web/**, data/**]` для `dziominpavel/Benchmark` и `paths: [web/**]` для `dziominpavel/InstagramTracker`; один шаг `gh api -X POST repos/dziominpavel/dziominpavel.github.io/dispatches -f event_type=web-updated` с `GH_TOKEN: ${{ secrets.STORE_DISPATCH_TOKEN }}`, `permissions: contents: read`; проверка: `python -c "import yaml;yaml.safe_load(open('notify-store.yml',encoding='utf-8'))"` проходит локально, затем файлы созданы в обоих репо (`gh api repos/<repo>/contents/.github/workflows/notify-store.yml` → 200)
- [x] 4.2 Владелец заводит classic PAT (scope `repo`) и устанавливает его как секрет `STORE_DISPATCH_TOKEN` в оба web-репозитория (`gh secret set STORE_DISPATCH_TOKEN`); проверка: `gh secret list` показывает секрет в обоих репозиториях
- [x] 4.3 Обновить README (см. 5.1) ссылкой на секрет и имена workflow, чтобы настройка была воспроизводима; проверка: в README названы `STORE_DISPATCH_TOKEN`, `notify-store.yml` и оба репозитория-источника

## 5. Документация и changelog

- [x] 5.1 Обновить `README.md`, раздел «Как это устроено»: три канала запуска сборки — оповещение после релиза, оповещение о пуше web-статики, cron-подстраховка; проверка: все три канала перечислены, порядок описан так, что настройка чужого web-источника воспроизводится без чтения кода
- [x] 5.2 Добавить пункт в `CHANGELOG.md` → `## [Unreleased]` (новая функция: витрина пересобирается по событию релиза или web-пуша); проверка: `python scripts/check-version.py` завершается с кодом 0

## 6. Сквозная проверка

- [x] 6.1 Ручной вызов `gh api -X POST repos/dziominpavel/dziominpavel.github.io/dispatches -f event_type=app-released`; проверка: в `gh run list` появляется запуск со `event=repository_dispatch` и статусом `success`, а живая витрина показывает актуальные данные (сейчас отстаёт `YandexMusicDownloader v0.1.0` при опубликованном `v0.2.0`)
- [x] 6.2 Пуш коммита, тронувшего `web/**`, в один из web-источников; проверка: запускается `notify-store.yml`, за ним появляется run витрины с `event=repository_dispatch`, дата web-карточки обновляется
- [x] 6.3 Первый после внедрения релиз любого приложения через `release.ps1`; проверка: в логе скрипта виден результат оповещения, витрина показывает новую версию без ожидания cron; при недоступном API оповещения релиз всё равно публикуется (exit 0)
- [x] 6.4 `openspec validate add-event-driven-store-sync --strict`; проверка: команда завершается без ошибок
