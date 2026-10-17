#!/usr/bin/env python3
"""Тесты валидатора витрины: скоупинг проверок store/приложения (D6).

Запуск: python tests/test_validate_site.py
"""

from __future__ import annotations

import contextlib
import io
import os
import pathlib
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from validate_site import SITE, main  # noqa: E402

STORE_PAGE = """<!DOCTYPE html>
<html lang="ru" data-theme="dark">
<head>
<meta charset="utf-8">
<meta name="description" content="Описание.">
<meta property="og:title" content="Название">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="icon" href="favicon.svg">
<link rel="stylesheet" href="static/style.css">
<title>Страница</title>
</head>
<body>
<nav><a href="./">Главная</a> <a href="about/">О проекте</a></nav>
<script src="static/js/theme.js" defer></script>
</body>
</html>
"""

# Страница приложения: чужой UI — store-chrome (og/favicon/nav/theme.js) не нужен.
APP_PAGE = """<!DOCTYPE html>
<html lang="ru" data-theme="dark">
<head><meta charset="utf-8"><title>Приложение</title></head>
<body><h1>Слепок консоли</h1></body>
</html>
"""

FAVICON = '<svg xmlns="http://www.w3.org/2000/svg"><text>М</text></svg>'


def _write(path: pathlib.Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _make_site(root: pathlib.Path, *, store_page: str = STORE_PAGE,
               app_page: str = APP_PAGE, deep_page: str = APP_PAGE,
               sitemap_urls: list[str] | None = None) -> pathlib.Path:
    _write(root / "index.html", store_page)
    _write(root / "about" / "index.html", store_page)
    _write(root / "apps" / "demo" / "index.html", app_page)
    _write(root / "apps" / "demo" / "deep" / "index.html", deep_page)
    _write(root / "favicon.svg", FAVICON)
    urls = sitemap_urls or [f"{SITE}/", f"{SITE}/about/", f"{SITE}/apps/demo/"]
    entries = "\n".join(f"  <url><loc>{u}</loc></url>" for u in urls)
    _write(root / "sitemap.xml",
           '<?xml version="1.0" encoding="UTF-8"?>\n'
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
           f"{entries}\n</urlset>\n")
    return root


def _run(root: pathlib.Path) -> tuple[int, str]:
    with contextlib.redirect_stdout(io.StringIO()) as out:
        code = main(str(root))
    return code, out.getvalue()


def test_scope_positive():
    """Store-страницы — полный chrome; приложения — общие проверки; D6 sitemap."""
    with tempfile.TemporaryDirectory() as tmp:
        root = _make_site(pathlib.Path(tmp))
        code, out = _run(root)
        assert code == 0, out
        flat = out.replace(os.sep, "/")
        assert "apps/demo/deep/index.html: OK" in flat
        assert "sitemap: OK" in out
    print("ok: store + приложение + глубокая подстраница -> ALL OK")


def test_app_page_scope():
    """Приложению store-chrome не нужен, но lang=ru, остатки и баланс — обязательны."""
    with tempfile.TemporaryDirectory() as tmp:
        # Минимальная страница приложения проходит: нет og/favicon/nav/theme — ок.
        root = _make_site(pathlib.Path(tmp))
        code, out = _run(root)
        assert code == 0, out
        assert "!! нет обязательного блока" not in out

        # Без lang=ru страница приложения падает (общая проверка).
        root2 = pathlib.Path(tmp) / "no-lang"
        _make_site(root2, app_page=APP_PAGE.replace('<html lang="ru"', "<html"))
        code2, out2 = _run(root2)
        assert code2 == 1, out2
        assert "нет обязательного блока: lang=ru" in out2

        # Шаблонный остаток на глубокой подстранице приложения ловится.
        root3 = pathlib.Path(tmp) / "leftover"
        _make_site(root3, deep_page=APP_PAGE.replace("<h1>", "<h1>{slug} "))
        code3, out3 = _run(root3)
        assert code3 == 1, out3
        assert "{slug}" in out3

        # Сломанный баланс тегов на странице приложения ловится.
        root4 = pathlib.Path(tmp) / "broken"
        _make_site(root4, app_page=APP_PAGE.replace("</body>", "</div></body>"))
        code4, out4 = _run(root4)
        assert code4 == 1, out4
    print("ok: приложение — только общие проверки; lang/остатки/баланс ловятся")


def test_store_page_full_chrome():
    """У store-страницы пропавший theme.js/og:title — FAIL."""
    with tempfile.TemporaryDirectory() as tmp:
        broken = STORE_PAGE.replace("static/js/theme.js", "static/js/app.js")
        root = _make_site(pathlib.Path(tmp), store_page=broken)
        code, out = _run(root)
        assert code == 1, out
        assert "нет обязательного блока: theme.js" in out
    print("ok: store-странице без theme.js — FAIL")


def test_sitemap_scope():
    """Sitemap: landing приложения обязателен, глубокая подстраница — лишняя."""
    with tempfile.TemporaryDirectory() as tmp:
        # Нет landing приложения в sitemap -> FAIL.
        root = _make_site(pathlib.Path(tmp),
                          sitemap_urls=[f"{SITE}/", f"{SITE}/about/"])
        code, out = _run(root)
        assert code == 1, out
        assert "sitemap FAIL" in out

        # Глубокая подстраница в sitemap — лишний URL -> FAIL.
        root2 = pathlib.Path(tmp) / "deep"
        _make_site(root2, sitemap_urls=[f"{SITE}/", f"{SITE}/about/",
                                        f"{SITE}/apps/demo/",
                                        f"{SITE}/apps/demo/deep/"])
        code2, out2 = _run(root2)
        assert code2 == 1, out2
        assert "sitemap FAIL" in out2
    print("ok: sitemap — landing приложения обязателен, глубокая подстраница лишняя")


if __name__ == "__main__":
    test_scope_positive()
    test_app_page_scope()
    test_store_page_full_chrome()
    test_sitemap_scope()
    print("ALL PASS")
