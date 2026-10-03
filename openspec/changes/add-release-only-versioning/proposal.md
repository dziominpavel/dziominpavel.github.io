# Proposal: add-release-only-versioning

## Why

Версии перестали что-то значить: `version` в 4 Android-проектах бампается на каждой Gradle-сборке (`GymProgress` 1.0.634, `VoiceMind` 0.1.132), а витрина показывает это число как версию приложения для скачивания. Правила версионирования нет как единого документа — оно разъезжается по `AGENTS.md` проектов, в двух случаях прямо противоречит практике (`hours-bridge`: «патч — каждое изменение»), changelog есть только у `FogMap`. Кроме того, формула `versionCode = 2e9 + major*10000 + minor*100 + patch` в 4 Android-проектах сломана при `patch > 99`: переход на значимый номер (`1.1.0`) даёт `versionCode` ниже текущего, и Android отклонит обновление — то есть серьёзный бамп сейчас физически невозможен.

## What Changes

- **Версия = релиз.** Единственное место, где меняется файл `version`, — release-скрипт. Между релизами изменения копятся в секции `## [Unreleased]` файла `CHANGELOG.md`; промежуточных версий не существует ни как тега, ни как релиза, ни как числа на витрине.
- **`CHANGELOG.md` обязателен во всех проектах** (12 репозиториев), заполняется в момент правок, а не при релизе: пункт в `[Unreleased]` — часть работы над изменением. Бэкфилл текущей истории — уровень «сводная секция + секция на каждый существующий тег».
- **Знания только в корне.** Новый файл `versioning.yaml` в корне — единственный список всех проектов с треком (`release`/`static`), файлом версии и путём changelog. Дети получают от корня только собственные файлы и ничего не знают о соседях.
- **Единый эталон и канал разноса.** `docs/versioning.md` и `scripts/check-version.py` лежат в корне и разносятся детьм тем же механизмом, что уже разносит `release.ps1` (`sync-release.ps1` + `registry.yaml`).
- **`release.ps1` расширяется**: классифицирует `[Unreleased]`, сворачивает секцию, записывает файл `version`, сверяет верхнюю секцию changelog с версией до создания тега.
- **Два трека:** релизный (7 приложений + `hours-bridge` с бампом по команде владельца) и статический (`Benchmark`, `PersonalData`, `TempProject`, сама витрина — версия заморожена, changelog обязателен).
- **BREAKING**: автобамп `VERSION_PATCH` на Gradle-сборке прекращается; `versionCode` переводится на монотонную схему от счёта коммитов, `versionName` берётся из файла `version`.
- **BREAKING**: правило в `AGENTS.md` `hours-bridge` («патч — каждое изменение») переписывается, его спека `app-version` в том репозитории правится отдельной задачей.

## Capabilities

### New Capabilities
- `versioning-policy`: политика версии и changelog для всех проектов владельца — источник истины (файл `version`), обязательный `CHANGELOG.md` с секцией `[Unreleased]`, бамп только на релизе, два трека, распределение знаний (корень знает всех, дети — только себя), бэкфилл и заполнение в момент правок.
- `app-release-pipeline`: в этой дельте — новые требования о том, что release-скрипт производит бамп (сворачивает `[Unreleased]`, записывает `version`, проверяет рассинхрон с changelog). Основная спека capability ещё не синкнута (лежит как дельта в change `add-app-store`), поэтому дельта additive и не переписывает его требования.

### Modified Capabilities
<!-- нет: openspec/specs/ содержит только .gitkeep; существующие capability пока не синхронизированы -->

## Impact

- **Корень (`dziominpavel.github.io`):** новый `versioning.yaml`, `docs/versioning.md`, `scripts/check-version.py`; правка `scripts/release.ps1` (бамп + сверка changelog) и `scripts/sync-release.ps1` (разнос нового набора файлов).
- **7 репозиториев приложений** (`FogMap`, `ChargeForecast`, `GymProgress`, `VoiceMind`, `Wishlot`, `YandexMusicDownloader`, `instagram-tracker`): `CHANGELOG.md`, блок правил в `AGENTS.md`, копия `docs/versioning.md` + `scripts/check-version.py`.
- **4 Android-проекта** (`GymProgress`, `ChargeForecast`, `VoiceMind`, `Wishlot`): `app/build.gradle.kts` — отказ от автобампа, новый расчёт `versionCode` (сохранение монотонности относительно текущих значений), `versionName` из файла `version`.
- **`hours-bridge`:** `CHANGELOG.md`, переписанный раздел `## Версионирование` в `AGENTS.md`, правка спеки `openspec/specs/app-version/spec.md` в его собственном репозитории.
- **Статический трек** (`Benchmark`, `PersonalData`, `TempProject`, витрина): `CHANGELOG.md`; у `Benchmark` — фиксация `pyproject.toml` версии.
- **Витрина как продукт:** не меняется — `generate.py` уже читает `releases/latest`, промежуточные версии ей недоступны по построению; поле `history` в `store.yaml` остаётся в резерве и не заполняется (отображение changelog на витрине — вне scope).
