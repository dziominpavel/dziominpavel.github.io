#!/usr/bin/env python3
"""Юнит-тесты генератора витрины: контракт, реестр, авто-детект платформ.

Запуск: python tests/test_generate.py
"""

from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from generate import (  # noqa: E402
    detect_platforms,
    load_registry,
    release_card,
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


if __name__ == "__main__":
    test_validate_ok()
    test_validate_broken_no_crash()
    test_registry_slug_validation()
    test_detect_platforms_variants_and_unknown()
    test_release_card_json()
    print("ALL PASS")
