# Tasks: release-notes-from-changelog

## 1. Норма и документация

- [x] 1.1 Дописать в `docs/versioning.md` раздел о формате секции: саммари (2–5 буллетов для пользователя) до первой строки `###`, инженерские детали ниже; заметки GitHub-Release = блок до `###`. Verify: `Select-String -Path docs/versioning.md -Pattern 'саммари'` находит раздел, текст не противоречит разделу про категории.
- [x] 1.2 Внести то же правило в `docs/agents-versioning-block.md` внутри маркеров `<!-- versioning:begin -->` / `<!-- versioning:end -->` (блок раскатывается в AGENTS дочерних проектов рассылкой). Verify: блок содержит начало и конец маркеров, `powershell -ExecutionPolicy Bypass -File scripts/sync-release.ps1` в режиме плана не показывает дивергенцию по этому файлу.
- [x] 1.3 Добавить пункт в `## [Unreleased]` корневого `CHANGELOG.md` (заметки релизов берутся из секции changelog, саммари — до `###`). Verify: `python scripts/check-version.py` завершается с кодом 0.

## 2. Эталон release-скрипта

- [x] 2.1 Добавить в `scripts/release.ps1` вырезание заметок из прочитанного changelog: от строки `## [<Version>]` до следующей строки `## `, срез по первой строке `###`; если `###` нет — вся секция. Verify: покрыто тестами группы 3.
- [x] 2.2 Поставить гейт в фазу `-Prepare`: `Fail` с подсказкой (добавить пользовательское саммари выше первой `###`), когда в теле `[Unreleased]` нет текста до первой `###`; отказ происходит до записи файлов. Verify: тест `test_prepare_refuses_missing_summary` проходит, `version` и `CHANGELOG.md` остаются без изменений.
- [x] 2.3 На фазе публикации: записать заметки во временный файл UTF-8 без BOM, передать `gh release create $Tag ... --notes-file <file>`, тому же текстом задать `-m` тега, удалить временный файл в `finally`; при пустых заметках — `Fail` без создания тега. Verify: тест группы 3 сверяет содержимое переданного файла и код выхода.
- [x] 2.4 Обновить шапку-комментарий `scripts/release.ps1` (описание фаз и заметок) и поднять `$SCRIPT_VERSION` до `1.3.0`. Verify: `Select-String -Path scripts/release.ps1 -Pattern '\$SCRIPT_VERSION = "1.3.0"'` даёт совпадение.

## 3. Тесты release-конвейера

- [x] 3.1 В фикстурах `tests/test_release_phases.py` научить фейковый `gh` дописывать свои аргументы и содержимое файла из `--notes-file` в постоянный лог фикстуры. Verify: существующие тесты группы по публикации по-прежнему проходят.
- [x] 3.2 Дополнить фикстуры `[Unreleased]` строкой саммари там, где готовится релиз (сейчас они начинаются с `### Исправлено`). Verify: `python tests/test_release_phases.py` завершается с кодом 0.
- [x] 3.3 Добавить тест гейта: `[Unreleased]` только из категорий → подготовка откажется, файлы `version`/`CHANGELOG.md` не изменятся, тег не появится. Verify: `python tests/test_release_phases.py` показывает новый тест `ok:`.
- [x] 3.4 Добавить тест заметок: секция с кириллицей, `—` и `≥` → тело релиза равно блоку до первой `###` байт в байт, `-m` тега равно ему же. Verify: `python tests/test_release_phases.py` завершается с кодом 0.

## 4. Рассылка копий

- [x] 4.1 Расслать эталон `scripts/release.ps1` во все 7 репозиториев штатным `scripts/sync-release.ps1` (копии коммитятся и пушатся этим же скриптом). Verify: в `C:\projects\<проект>\release.ps1` каждого из 7 проектов `$SCRIPT_VERSION = "1.3.0"`, а содержимое совпадает с эталоном (`fc`/`Compare-Object` не показывает расхождений).

## 5. Одноразовые правки

- [x] 5.1 В `CHANGELOG.md` FogMap удалить второй `## [Unreleased]` (между секциями `1.2.0` и `1.1.0`) вместе с двумя буллетами-дублями `fix-eco-signal-loss` и `first-launch-visibility`. Verify: `Select-String -Path CHANGELOG.md -Pattern '^## \['` возвращает ровно один `## [Unreleased]`, секции `1.2.0` и `1.5.0` не изменились.
- [x] 5.2 Пробный бэкфилл: залить тело секции в последний релиз FogMap (`gh release edit v1.6.0 --notes-file <temp>`, текст секции целиком, UTF-8 без BOM). Verify: `gh release view v1.6.0 --repo dziominpavel/FogMap --json body` возвращает непустой `body`, а `releases/latest` по-прежнему указывает на `v1.6.0`.
- [x] 5.3 Бэкфилл остальных 10 релизов (FogMap v1.5.2, v1.5.1; YandexMusicDownloader 2; ChargeForecast 2; по одному в GymProgress, VoiceMind, Wishlot, InstagramTracker) от свежих к старым. Verify: по каждому тегу `gh release view --json body` непустой, `gh release list` не изменил порядок и метку `Latest`.

## 6. Контроль

- [x] 6.1 Прогнать полный набор корневых проверок: `python tests/test_generate.py`, `python tests/test_release_phases.py`, `python scripts/check-version.py`. Verify: все три завершаются с кодом 0.
- [x] 6.2 Провалидировать change: `openspec validate release-notes-from-changelog --strict`. Verify: команда завершается с кодом 0 без предупреждений.
