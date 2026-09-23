#!/usr/bin/env python3
"""Проверка собранной витрины в _site/: HTML-разметка, sitemap, favicon, meta.

Запуск: python tests/validate_site.py [каталог]
Код возврата: 0 — всё ок, 1 — есть проблемы.
"""

from __future__ import annotations

import html.parser
import pathlib
import re
import sys
import xml.dom.minidom

SITE = "https://dziominpavel.github.io"
VOID = {"meta", "link", "img", "br", "hr", "input", "source"}


class Checker(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.stack: list[str] = []
        self.errors: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag not in VOID:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        if not self.stack:
            self.errors.append(f"лишний </{tag}>")
        elif self.stack[-1] == tag:
            self.stack.pop()
        else:
            self.errors.append(f"ожидался </{self.stack[-1]}>, получен </{tag}>")


def main(root: str = "_site") -> int:
    base = pathlib.Path(root)
    ok = True

    for page in sorted(base.rglob("*.html")):
        text = page.read_text(encoding="utf-8")
        leftovers = re.findall(r"\{[a-z_]+\}", text)
        checker = Checker()
        checker.feed(text)
        checker.close()
        problems = leftovers + checker.errors + checker.stack
        rel = page.relative_to(base)
        print(f"{rel}: {'OK' if not problems else f'ПРОБЛЕМЫ: {problems}'}")
        ok = ok and not problems

        required = {
            "meta charset": 'charset="utf-8"' in text,
            "meta description": 'name="description"' in text,
            "og:title": "og:title" in text,
            "viewport": 'name="viewport"' in text,
            "favicon": 'rel="icon"' in text,
            "nav: О проекте": "О проекте" in text,
            "nav: Главная": "Главная" in text,
            "theme.js": "static/js/theme.js" in text,
            "lang=ru": 'lang="ru"' in text,
            "data-theme=dark": 'data-theme="dark"' in text,
        }
        for name, good in required.items():
            if not good:
                print(f"   !! нет обязательного блока: {name}")
                ok = False

    # sitemap покрывает все страницы
    sitemap = (base / "sitemap.xml").read_text(encoding="utf-8")
    xml.dom.minidom.parseString(sitemap)  # валидный XML или исключение
    locs = set(re.findall(r"<loc>(.*?)</loc>", sitemap))
    html_pages = {f"{SITE}/{p.relative_to(base).parent.as_posix()}/" if p.parent != base else f"{SITE}/"
                  for p in base.rglob("index.html")}
    if locs != html_pages:
        print(f"sitemap FAIL: {sorted(locs)} != {sorted(html_pages)}")
        ok = False
    else:
        print(f"sitemap: OK ({len(locs)} URL)")

    # favicon отдаётся локально
    favicon = base / "favicon.svg"
    fav_text = favicon.read_text(encoding="utf-8") if favicon.exists() else ""
    if "<text" in fav_text and fav_text.strip().endswith("</svg>"):
        print("favicon.svg: OK (буквенный, локальный)")
    else:
        print("favicon.svg: FAIL")
        ok = False

    print("ALL OK" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:2]))
