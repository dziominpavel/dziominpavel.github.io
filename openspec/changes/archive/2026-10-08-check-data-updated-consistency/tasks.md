# Tasks: check-data-updated-consistency

## 1. Хелпер коммит-даты по пути

- [x] 1.1 Вынести путь в параметр: создать `fetch_path_commit_date(repo, path, token=None)` на базе `fetch_web_commit_date` (GitHub API `commits?path=…&per_page=1`, возвращает ISO-дату или `None`), а `fetch_web_commit_date` сделать обёрткой с путём `web` — проверка: существующие тесты `test_fetch_web_commit_date` проходят без правок (`python tests/test_generate.py`)
- [x] 1.2 Добавить тест хелпера: параметр `path` уходит в запрос к API, ошибка/пустой ответ → `None` — проверка: новый тест в `tests/test_generate.py` зелёный

## 2. Сверка `updated` с последним коммитом данных

- [x] 2.1 В ветке `data:` в `collect_web_projects` (`generate.py:364-394`) после чтения `updated` сверять календарную дату UTC поля с датой последнего коммита файла данных: неравенство → `[WARN]` со слагом и обеими датами, `None` → сверка пропускается молча, дата карточки и код возврата не меняются — проверка: код покрыт тестами из 2.2
- [x] 2.2 Добавить сценарийные тесты: расхождение печатает WARN и карточка остаётся на `updated`; совпадение молчит; недоступный API → без WARN; запись без `data:` → сверка не вызывается — проверка: `python tests/test_generate.py` → `ALL PASS`

## 3. Контроли

- [x] 3.1 Прогнать полную сборку `python generate.py --out _site` и валидацию `python tests/validate_site.py _site` → exit 0, в логе нет WARN о сверке (у Benchmark `updated` совпадает с последним коммитом `data/`)
- [x] 3.2 Програть `python scripts/check-version.py` и `python scripts/check-commit-hygiene.py` → exit 0; `CHANGELOG.md` не трогать (внутренняя проверка, в changelog не пишется)
