#!/usr/bin/env python3
"""Юнит-тесты генератора витрины: контракт, реестр, авто-детект платформ.

Запуск: python tests/test_generate.py
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import re
import sys
import tempfile
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from generate import (  # noqa: E402
    SITE_URL,
    collect_web_projects,
    detect_platforms,
    fetch_path_commit_date,
    fetch_web_commit_date,
    fmt_date,
    head_commit_date,
    load_registry,
    load_web_registry,
    release_card,
    render_site,
    sort_by_date,
    validate_project,
)


def make_project(root: str, *, name="FogMap", description="Трекер", icon="assets/icon.png",
                 screenshots=3, extra_fields=None, create_icon=True) -> str:
    """Создаёт валидный (или подающийся на дефекты) проект в песочнице."""
    proj = os.path.join(root, "fogmap")
    os.makedirs(proj, exist_ok=True)
    os.makedirs(os.path.join(proj, "assets"), exist_ok=True)
    if create_icon:
        with open(os.path.join(proj, icon), "wb") as fh:
            fh.write(b"\x89PNG fake")
    shots_dir = os.path.join(proj, "screenshots")
    os.makedirs(shots_dir, exist_ok=True)
    for i in range(screenshots):
        with open(os.path.join(shots_dir, f"shot{i + 1}.png"), "wb") as fh:
            fh.write(b"\x89PNG fake")
    fields = {"name": name, "description": description, "icon": icon,
              "requirements": "Android 8+"}
    if extra_fields:
        fields.update(extra_fields)
    lines = [f"{key}: {value}" for key, value in fields.items()]
    with open(os.path.join(proj, "store.yaml"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return proj


def test_validate_ok():
    with tempfile.TemporaryDirectory() as tmp:
        proj = make_project(tmp)
        store, problems = validate_project(proj, "fogmap")
        assert problems == [], problems
        assert store["name"] == "FogMap"
        assert store["_screenshots"] == ["shot1.png", "shot2.png", "shot3.png"]
    print("ok: валидный проект проходит без предупреждений")


def test_validate_broken_no_crash():
    """Битый проект -> (None, проблемы), исключений нет (4.2: ноль падений)."""
    with tempfile.TemporaryDirectory() as tmp:
        # а) нет обязательных полей
        proj = os.path.join(tmp, "a")
        os.makedirs(proj)
        with open(os.path.join(proj, "store.yaml"), "w", encoding="utf-8") as fh:
            fh.write("name: Только имя\n")
        store, problems = validate_project(proj, "a")
        assert store is None
        assert any("description" in p for p in problems)
        assert any("'icon'" in p for p in problems)

        # б) битый YAML
        proj = os.path.join(tmp, "b")
        os.makedirs(proj)
        with open(os.path.join(proj, "store.yaml"), "w", encoding="utf-8") as fh:
            fh.write("name: [незакрытая\n")
        store, problems = validate_project(proj, "b")
        assert store is None and problems

        # в) нет store.yaml
        proj = os.path.join(tmp, "c")
        os.makedirs(proj)
        store, problems = validate_project(proj, "c")
        assert store is None and "нет store.yaml" in problems[0]

        # г) лишние поля и битый путь иконки -> НЕ валит сборку:
        #    лишние поля -> warning, отсутствие ФАЙЛА иконки -> буквенный плейсхолдер
        #    (store-catalog: «иконка не найдена -> плейсхолдер, витрина не падает»)
        with tempfile.TemporaryDirectory() as tmp2:
            proj = make_project(tmp2, extra_fields={"version": "1.2.3", "platforms": "android"},
                                icon="assets/нет-такого.png", create_icon=False)
            store, problems = validate_project(proj, "d")
            assert store is not None and problems == [], (store, problems)
            assert store["_icon_missing"] is True

        # д) поле icon отсутствует вовсе -> skip (обязательное поле контракта)
        with tempfile.TemporaryDirectory() as tmp2b:
            proj = os.path.join(tmp2b, "noicon")
            os.makedirs(proj)
            os.makedirs(os.path.join(proj, "screenshots"))
            for i in range(3):
                open(os.path.join(proj, "screenshots", f"s{i}.png"), "wb").close()
            with open(os.path.join(proj, "store.yaml"), "w", encoding="utf-8") as fh:
                fh.write("name: X\ndescription: Y\n")
            store, problems = validate_project(proj, "noicon")
            assert store is None and any("'icon'" in p for p in problems)

        # е) мало скриншотов
        with tempfile.TemporaryDirectory() as tmp3:
            proj = make_project(tmp3, screenshots=2)
            store, problems = validate_project(proj, "e")
            assert store is None and any("скриншотов" in p for p in problems)
    print("ok: битый контракт -> skip + warning; битая иконка -> плейсхолдер; без исключений")


def test_registry_slug_validation():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "registry.yaml")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(
                "projects:\n"
                "  fogmap:\n"
                "    repo: dziominpavel/FogMap\n"
                "  Bad_Slug:\n"
                "    repo: dziominpavel/Bad\n"
                "  yandex-music:\n"
                "    repo: dziominpavel/YandexMusicDownloader\n"
                "  broken:\n"
                "    repo: нет-слэша\n"
            )
        entries = load_registry(path)
        assert [e["slug"] for e in entries] == ["fogmap", "yandex-music"]
    print("ok: некорректные ключи repo отбрасываются, корректные сохраняются")


def test_detect_platforms_variants_and_unknown():
    """4.3: мультиассетный релиз -> два варианта Windows, неизвестный ассет отсутствует."""
    assets = [
        {"name": "FogMap-1.5.1.apk", "size": 100, "browser_download_url": "u1"},
        {"name": "YandexMusicDownloader-2.0.0-win-x64.zip", "size": 200, "browser_download_url": "u2"},
        {"name": "YandexMusicDownloader-2.0.0-win-arm64.zip", "size": 210, "browser_download_url": "u3"},
        {"name": "InstagrammTracker-1.0.0-win-x64.exe", "size": 300, "browser_download_url": "u4"},
        {"name": "source-code.zip", "size": 1, "browser_download_url": "u5"},
        {"name": "checksums.txt", "size": 1, "browser_download_url": "u6"},
    ]
    platforms = detect_platforms(assets)
    assert len(platforms["android"]) == 1
    windows_names = [a["name"] for a in platforms["windows"]]
    assert windows_names == [
        "YandexMusicDownloader-2.0.0-win-x64.zip",
        "YandexMusicDownloader-2.0.0-win-arm64.zip",
        "InstagrammTracker-1.0.0-win-x64.exe",
    ], windows_names
    assert not any("source-code" in n or "checksums" in n for n in windows_names)
    print("ok: мультиассет -> варианты одной платформы, неизвестные ассеты игнорируются")


def test_release_card_json():
    """4.1: карточка из releases.latest содержит версию, размер, дату, ссылки."""
    entry = {"slug": "fogmap", "repo": "dziominpavel/FogMap"}
    release = {
        "tag_name": "v1.5.1",
        "published_at": "2026-09-23T20:00:00Z",
        "html_url": "https://github.com/dziominpavel/FogMap/releases/tag/v1.5.1",
        "assets": [
            {"name": "FogMap-1.5.1.apk", "size": 64369516, "download_count": 7,
             "browser_download_url": "https://github.com/.../FogMap-1.5.1.apk"},
        ],
    }
    card = release_card(entry, release)
    assert card["version"] == "1.5.1"
    assert card["size"] == 64369516
    assert card["date"] == "2026-09-23T20:00:00Z"
    assert card["downloads"] == 7
    assert card["url"].endswith("v1.5.1")
    assert card["assets"][0]["browser_download_url"].endswith(".apk")
    print("ok: JSON карточки (версия, размер, дата, ссылки, счётчик)")


def _fake_web_clone(repo: str, dest: str, token=None) -> bool:
    """Фейковый клон web-источника: контракт web/ + данные index.json."""
    web = os.path.join(dest, "web")
    os.makedirs(web, exist_ok=True)
    with open(os.path.join(web, "index.html"), "w", encoding="utf-8") as fh:
        fh.write("<!DOCTYPE html>\n<html lang=\"ru\"><head><meta charset=\"utf-8\">"
                 "<title>Демо-веб</title></head><body>Демо-веб</body></html>\n")
    with open(os.path.join(web, "style.css"), "w", encoding="utf-8") as fh:
        fh.write("body { color: #222; }\n")
    data = os.path.join(dest, "data")
    os.makedirs(data, exist_ok=True)
    with open(os.path.join(data, "index.json"), "w", encoding="utf-8") as fh:
        json.dump({"updated": "2026-01-15T00:00:00Z", "models": []}, fh)
    return True


def test_web_registry_and_publish_success():
    """3.5: успешный web-источник -> карточка на главной + страница + URL в sitemap."""
    import generate as gen
    orig_clone = gen.clone_project
    with tempfile.TemporaryDirectory() as tmp:
        # a) реестр: валидные записи проходят, битые отбрасываются с WARN
        reg_path = os.path.join(tmp, "registry.yaml")
        with open(reg_path, "w", encoding="utf-8") as fh:
            fh.write(
                "projects:\n"
                "  fogmap:\n"
                "    repo: dziominpavel/FogMap\n"
                "web:\n"
                "  demo-web:\n"
                "    repo: demo/Source\n"
                "    title: Демо-веб\n"
                "    description: Веб-демо для теста.\n"
                "    data: data/index.json\n"
                "  Bad_Slug:\n"
                "    repo: demo/Source\n"
                "    title: X\n"
                "    description: Y\n"
                "  no-meta:\n"
                "    repo: demo/Source\n"
                "  bad-repo:\n"
                "    repo: без-слэша\n"
                "    title: X\n"
                "    description: Y\n"
            )
        with contextlib.redirect_stderr(io.StringIO()) as err:
            web_entries = load_web_registry(reg_path)
        assert [e["slug"] for e in web_entries] == ["demo-web"], web_entries
        assert "WARN" in err.getvalue()

        # b) успешный источник -> карточка (дата из index.json:updated)
        work = os.path.join(tmp, "work")
        os.makedirs(work)
        # сверка updated не ходит в сеть: коммит-дата = updated (совпадение)
        orig_fetch_path = gen.fetch_path_commit_date
        gen.clone_project = _fake_web_clone
        gen.fetch_path_commit_date = (
            lambda repo, path, token=None: "2026-01-15T00:00:00Z")
        try:
            web_cards = collect_web_projects(web_entries, workdir=work)
        finally:
            gen.clone_project = orig_clone
            gen.fetch_path_commit_date = orig_fetch_path
        assert len(web_cards) == 1, web_cards
        card = web_cards[0]
        assert card["slug"] == "demo-web"
        assert card["date"] == "2026-01-15T00:00:00Z"
        assert card["icon"] is None
        assert card["data_file"] == "data/index.json"
        # регрессия fmt_date: календарная дата без таймзоны не уходит на день назад
        assert fmt_date("2026-10-02") == "02.10.2026", fmt_date("2026-10-02")

        # c) рендер: страница /apps/<slug>/, карточка, URL, данные рядом
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        cwd = os.getcwd()
        os.chdir(root)
        try:
            out = os.path.join(tmp, "site")
            urls = render_site([], web_cards, out)
        finally:
            os.chdir(cwd)

        assert f"{SITE_URL}/apps/demo-web/" in urls, urls
        assert os.path.isfile(os.path.join(out, "apps", "demo-web", "index.html"))
        assert os.path.isfile(os.path.join(out, "apps", "demo-web", "index.json"))
        with open(os.path.join(out, "index.html"), encoding="utf-8") as fh:
            home = fh.read()
        assert 'data-filter="web"' in home  # сегмент Web в фильтре главной
        assert 'href="apps/demo-web/"' in home
        assert "Открыть в браузере" in home
        assert '<span class="card-meta">Обновлено 15.01.2026</span>' in home
        # дата стоит в шапке под именем — там же, где у скачиваемых карточек
        start = home.index('<article class="card" data-platforms="web"')
        block = home[start:start + 1500]  # вся карточка заметно короче окна
        assert block.index("card-meta") < block.index("card-desc")
        # слота статистики у web-карточки нет — пустой параграф не выводится
        assert "card-stats" not in home
        assert '<article class="card" data-platforms="web"' in home  # тот же .card
        assert 'class="web-card"' not in home  # отдельного класса больше нет
        assert 'chip chip-web">Web</span>' in home  # чип и сегмент — латиницей
        assert "Веб-приложения" not in home  # отдельной секции больше нет
        with open(os.path.join(out, "sitemap.xml"), encoding="utf-8") as fh:
            sitemap = fh.read()
        assert f"<loc>{SITE_URL}/apps/demo-web/</loc>" in sitemap

        # д) запись без поля data: файл данных не копируется, дата — из fallback
        # (HEAD клона, иначе дата сборки), но не из index.json:updated
        entries_no_data = [dict(entry) for entry in web_entries]
        entries_no_data[0].pop("data")
        gen.clone_project = _fake_web_clone
        orig_fetch = gen.fetch_web_commit_date
        orig_head = gen.head_commit_date
        gen.fetch_web_commit_date = lambda repo, token=None: None
        gen.head_commit_date = lambda project_dir: "2026-09-28T12:00:00Z"
        try:
            cards_no_data = collect_web_projects(entries_no_data, workdir=work)
        finally:
            gen.clone_project = orig_clone
            gen.fetch_web_commit_date = orig_fetch
            gen.head_commit_date = orig_head
        assert cards_no_data[0]["data_file"] is None
        assert cards_no_data[0]["date"] == "2026-09-28T12:00:00Z"
        os.chdir(root)
        try:
            out2 = os.path.join(tmp, "site2")
            render_site([], cards_no_data, out2)
        finally:
            os.chdir(cwd)
        assert os.path.isfile(os.path.join(out2, "apps", "demo-web", "index.html"))
        assert not os.path.isfile(os.path.join(out2, "apps", "demo-web", "index.json"))
    print("ok: web-источник -> карточка на главной, страница /apps/ и URL в sitemap")


def test_web_publish_broken_source():
    """3.5: битый источник -> skip без исключения (clone fail / нет web/index.html)."""
    import generate as gen
    orig_clone = gen.clone_project
    with tempfile.TemporaryDirectory() as tmp:
        entries = [{"slug": "ghost", "repo": "demo/Ghost",
                    "title": "Призрак", "description": "Не собирается."}]
        work = os.path.join(tmp, "work")
        os.makedirs(work)

        # а) клон не удался -> пусто, без исключений
        #    (WARN в этом пути печатает сам clone_project — существующий код)
        gen.clone_project = lambda repo, dest, token=None: False
        try:
            result = collect_web_projects(entries, workdir=work)
        finally:
            gen.clone_project = orig_clone
        assert result == []

        # б) клон есть, но web/index.html отсутствует -> WARN + skip
        def fake_clone_no_index(repo, dest, token=None):
            os.makedirs(os.path.join(dest, "web"), exist_ok=True)
            return True
        gen.clone_project = fake_clone_no_index
        try:
            with contextlib.redirect_stderr(io.StringIO()) as err2:
                result = collect_web_projects(entries, workdir=work)
        finally:
            gen.clone_project = orig_clone
        assert result == []
        assert "WARN" in err2.getvalue() and "index.html" in err2.getvalue()

        # в) битая запись реестра (нет title/description) -> skip, без исключений
        with tempfile.TemporaryDirectory() as tmp2:
            reg_path = os.path.join(tmp2, "registry.yaml")
            with open(reg_path, "w", encoding="utf-8") as fh:
                fh.write("web:\n  x:\n    repo: a/b\n")
            with contextlib.redirect_stderr(io.StringIO()):
                assert load_web_registry(reg_path) == []
    print("ok: битый web-источник -> skip + warning, без исключений")


def test_sort_by_date_desc():
    """Порядок витрины: от свежей даты к старой, без даты — в конец."""
    cards = [
        {"slug": "old", "date": "2026-01-01T10:00:00Z"},
        {"slug": "new", "date": "2026-05-01T10:00:00Z"},
        {"slug": "mid", "date": "2026-03-01T10:00:00Z"},
        {"slug": "none", "date": None},
        {"slug": "bare", "date": "2026-04-01"},  # календарная дата без таймзоны
    ]
    ordered = sort_by_date(cards)
    assert [c["slug"] for c in ordered] == ["new", "bare", "mid", "old", "none"], ordered
    # исходный список не мутируется (render_site вызывается повторно)
    assert [c["slug"] for c in cards] == ["old", "new", "mid", "none", "bare"]
    print("ok: sort_by_date — по убыванию даты, без даты в конец, без мутаций")


def _fake_release_card(slug: str, date, project_dir: str) -> dict:
    """Минимальная карточка скачиваемого приложения для рендера в песочнице."""
    return {
        "slug": slug, "repo": f"demo/{slug}", "version": "1.0.0", "size": 1000,
        "date": date, "downloads": 0, "url": "https://example.com/rel",
        "assets": [{"name": f"{slug}.zip", "size": 1000, "download_count": 0,
                    "browser_download_url": "https://example.com/x.zip"}],
        "store": {"name": slug.capitalize(), "description": "Описание приложения."},
        "icon_missing": False, "screenshots": [], "project_dir": project_dir,
        "platforms": {"windows": [{"name": f"{slug}.zip", "size": 1000,
                                   "browser_download_url": "https://example.com/x.zip"}]},
    }


def _fake_web_card(slug: str, date, project_dir: str) -> dict:
    web_dir = os.path.join(project_dir, f"web-{slug}")
    os.makedirs(web_dir, exist_ok=True)
    with open(os.path.join(web_dir, "index.html"), "w", encoding="utf-8") as fh:
        fh.write("<!DOCTYPE html>\n<html lang=\"ru\"><title>X</title></html>\n")
    return {"slug": slug, "repo": f"demo/{slug}", "title": slug.capitalize(),
            "description": "Описание веб-приложения.", "date": date,
            "icon": None, "data_file": None, "project_dir": project_dir,
            "web_dir": web_dir}


def test_fetch_web_commit_date():
    """Дата web без data: парсинг commits?path=web, пусто/сбой -> None."""
    import generate as gen
    orig_api = gen.github_api
    try:
        gen.github_api = lambda path, token=None: [
            {"commit": {"committer": {"date": "2026-09-28T12:00:00Z"},
                        "author": {"date": "2026-09-27T12:00:00Z"}}}]
        assert fetch_web_commit_date("demo/Repo") == "2026-09-28T12:00:00Z"

        gen.github_api = lambda path, token=None: []
        with contextlib.redirect_stderr(io.StringIO()):
            assert fetch_web_commit_date("demo/Repo") is None

        def boom(path, token=None):
            raise urllib.error.HTTPError(path, 403, "rate", None, None)
        gen.github_api = boom
        with contextlib.redirect_stderr(io.StringIO()):
            assert fetch_web_commit_date("demo/Repo") is None
    finally:
        gen.github_api = orig_api
    with tempfile.TemporaryDirectory() as tmp:
        assert head_commit_date(tmp) is None
    print("ok: коммит-дата web/ — парсинг и fallback без падений")


def test_collect_web_date_from_commit():
    """Ветка без data: дата из коммита web/, ветка с data — из updated."""
    import generate as gen
    orig_clone = gen.clone_project
    orig_fetch = gen.fetch_web_commit_date
    with tempfile.TemporaryDirectory() as tmp:
        work = os.path.join(tmp, "work")
        os.makedirs(work)
        gen.clone_project = _fake_web_clone
        gen.fetch_web_commit_date = lambda repo, token=None: "2026-09-28T12:00:00Z"
        # сверка updated не ходит в сеть: коммит-дата = updated (совпадение)
        orig_fetch_path = gen.fetch_path_commit_date
        gen.fetch_path_commit_date = (
            lambda repo, path, token=None: "2026-01-15T00:00:00Z")
        try:
            no_data = collect_web_projects(
                [{"slug": "plain", "repo": "demo/Source",
                  "title": "Плейн", "description": "Без данных."}], workdir=work)
            with_data = collect_web_projects(
                [{"slug": "withdata", "repo": "demo/Source",
                  "title": "С данными", "description": "С данными.",
                  "data": "data/index.json"}], workdir=work)
        finally:
            gen.clone_project = orig_clone
            gen.fetch_web_commit_date = orig_fetch
            gen.fetch_path_commit_date = orig_fetch_path
        assert no_data[0]["date"] == "2026-09-28T12:00:00Z", no_data
        assert with_data[0]["date"] == "2026-01-15T00:00:00Z", with_data
    print("ok: web без data — дата коммита, web с data — updated без изменений")


def test_fetch_path_commit_date():
    """1.2: path уходит в запрос к API, ошибка/пусто -> None, без вывода."""
    import generate as gen
    orig_api = gen.github_api
    seen = {}

    def api(path, token=None):
        seen["path"] = path
        return [{"commit": {"committer": {"date": "2026-10-07T21:00:00Z"},
                            "author": {"date": "2026-10-07T20:00:00Z"}}}]

    err_empty = io.StringIO()
    err_http = io.StringIO()
    try:
        gen.github_api = api
        assert fetch_path_commit_date(
            "demo/Repo", "data/index.json") == "2026-10-07T21:00:00Z"
        # path попадает в запрос ровно как объявлен (без перекодирования)
        assert seen["path"] == ("/repos/demo/Repo/commits"
                                "?path=data/index.json&per_page=1"), seen

        gen.github_api = lambda path, token=None: []
        with contextlib.redirect_stderr(err_empty):
            assert fetch_path_commit_date("demo/Repo", "data/index.json") is None

        def boom(path, token=None):
            raise urllib.error.HTTPError(path, 403, "rate", None, None)
        gen.github_api = boom
        with contextlib.redirect_stderr(err_http):
            assert fetch_path_commit_date("demo/Repo", "data/index.json") is None
    finally:
        gen.github_api = orig_api
    # D4: недоступность коммит-даты — не повод шуметь в логе сборки
    assert err_empty.getvalue() == "", err_empty.getvalue()
    assert err_http.getvalue() == "", err_http.getvalue()
    print("ok: fetch_path_commit_date — path в запросе, сбой/пусто -> None молча")


def test_data_updated_consistency():
    """2.2: расхождение -> WARN, совпадение/недоступность -> тишина, без data: -> без сверки."""
    import generate as gen
    orig_clone = gen.clone_project
    orig_fetch_path = gen.fetch_path_commit_date
    orig_fetch_web = gen.fetch_web_commit_date
    # _fake_web_clone пишет в data/index.json updated = 2026-01-15T00:00:00Z
    entry = {"slug": "withdata", "repo": "demo/Source",
             "title": "С данными", "description": "С данными.",
             "data": "data/index.json"}
    try:
        gen.clone_project = _fake_web_clone
        with tempfile.TemporaryDirectory() as tmp:
            work = os.path.join(tmp, "work")
            os.makedirs(work)

            # а) расхождение (updated=15.01, коммит=16.01) -> WARN со слагом
            #    и обеими датами; дата карточки остаётся updated
            gen.fetch_path_commit_date = (
                lambda repo, path, token=None: "2026-01-16T09:30:00Z")
            with contextlib.redirect_stderr(io.StringIO()) as err_mismatch:
                cards = collect_web_projects([dict(entry)], workdir=work)
            out = err_mismatch.getvalue()
            assert cards[0]["date"] == "2026-01-15T00:00:00Z", cards
            assert "WARN" in out and "withdata" in out, out
            assert "2026-01-15" in out and "2026-01-16" in out, out

            # б) даты совпадают (разное время в пределах одного дня) -> тишина
            gen.fetch_path_commit_date = (
                lambda repo, path, token=None: "2026-01-15T23:59:00Z")
            with contextlib.redirect_stderr(io.StringIO()) as err_match:
                cards = collect_web_projects([dict(entry)], workdir=work)
            assert "WARN" not in err_match.getvalue(), err_match.getvalue()
            assert cards[0]["date"] == "2026-01-15T00:00:00Z", cards

            # в) коммит-дата недоступна -> сверка пропускается молча
            gen.fetch_path_commit_date = lambda repo, path, token=None: None
            with contextlib.redirect_stderr(io.StringIO()) as err_none:
                cards = collect_web_projects([dict(entry)], workdir=work)
            assert "WARN" not in err_none.getvalue(), err_none.getvalue()
            assert cards[0]["date"] == "2026-01-15T00:00:00Z", cards

            # г) запись без data: -> сверка не вызывается, дата — из коммита web/
            def forbidden(repo, path, token=None):
                raise AssertionError(f"сверка вызвана у записи без data: ({path})")
            gen.fetch_path_commit_date = forbidden
            gen.fetch_web_commit_date = (
                lambda repo, token=None: "2026-09-28T12:00:00Z")
            plain = {k: v for k, v in entry.items() if k != "data"}
            plain["slug"] = "plain"
            cards = collect_web_projects([plain], workdir=work)
            assert cards[0]["date"] == "2026-09-28T12:00:00Z", cards
            assert cards[0]["data_file"] is None, cards
    finally:
        gen.clone_project = orig_clone
        gen.fetch_path_commit_date = orig_fetch_path
        gen.fetch_web_commit_date = orig_fetch_web
    print("ok: сверка updated — расхождение WARN, тишина при совпадении/сбое")


def test_render_home_sorted_by_date():
    """Главная: единая лента скачиваемые + web по дате (новое сверху)."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cwd = os.getcwd()
    with tempfile.TemporaryDirectory() as tmp:
        cards = [
            _fake_release_card("alpha", "2026-01-01T10:00:00Z", tmp),
            _fake_release_card("beta", "2026-05-01T10:00:00Z", tmp),
            _fake_release_card("gamma", "2026-03-01T10:00:00Z", tmp),
            _fake_release_card("undated", None, tmp),
        ]
        web_cards = [
            _fake_web_card("web-old", "2026-01-02", tmp),
            _fake_web_card("web-new", "2026-04-01", tmp),
        ]
        os.chdir(root)
        try:
            out = os.path.join(tmp, "site")
            render_site(cards, web_cards, out)
        finally:
            os.chdir(cwd)
        with open(os.path.join(out, "index.html"), encoding="utf-8") as fh:
            home = fh.read()
        order = re.findall(r'class="card-head" href="([^"]+)/"', home)
        assert order == ["beta", "apps/web-new", "gamma",
                         "apps/web-old", "alpha", "undated"], order
        # дата подписана и стоит рядом с версией; в строке счётчиков — только счётчик
        assert "· обновлено 01.05.2026" in home, home
        assert "<span>Скачиваний: 0</span>" in home, home
        assert home.count("01.05.2026") == 1, "дата дублируется в строке счётчиков"
        # у web та же дата — в card-meta под именем, а не в строке после описания
        assert '<span class="card-meta">Обновлено 01.04.2026</span>' in home, home
    print("ok: главная — единая лента по дате, новое сверху, старое внизу")


if __name__ == "__main__":
    test_validate_ok()
    test_validate_broken_no_crash()
    test_registry_slug_validation()
    test_detect_platforms_variants_and_unknown()
    test_release_card_json()
    test_web_registry_and_publish_success()
    test_web_publish_broken_source()
    test_sort_by_date_desc()
    test_fetch_web_commit_date()
    test_collect_web_date_from_commit()
    test_fetch_path_commit_date()
    test_data_updated_consistency()
    test_render_home_sorted_by_date()
    print("ALL PASS")
