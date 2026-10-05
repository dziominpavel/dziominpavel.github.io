## 1. Честная дата web без `data:`

- [x] 1.1 Добавить получение даты последнего коммита `web/` через GitHub API (`commits?path=web&per_page=1`, поле `committer.date`) с fallback-цепочкой HEAD клона → дата сборки + WARN, проверить мок-тестом парсинга и fallback при ошибке API
- [x] 1.2 Подключить новый источник даты в `collect_web_projects` только для ветки без `data:` (ветка Benchmark без изменений), проверить логом сборки: web без `data:` показывает дату коммита, а не сегодня

## 2. Единая лента главной

- [x] 2.1 Перевести `render_site` на merged-сортировку (`sort_by_date` один раз по всем карточкам с dispatch `card_html` / `web_card_html`), проверить рендером песочницы: скачиваемые и web вперемешку от новой даты к старой
- [x] 2.2 Обновить комментарии/док-строки `sort_by_date` и `render_site` (группы больше не разделяются), проверить чтением кода: нет упоминаний «web после скачиваемых»

## 3. Тесты и сверка

- [x] 3.1 Обновить `test_render_home_sorted_by_date` и добавить кейсы даты web (коммит, fallback HEAD, fallback сборка), проверить командой `python tests/test_generate.py`
- [x] 3.2 Прогнать `python tests/validate_site.py _site` на песочной сборке и `python scripts/check-version.py`, проверить exit 0 и отсутствие дублей даты в `card-stats`
