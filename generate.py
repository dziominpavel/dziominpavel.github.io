#!/usr/bin/env python3
"""Генератор статики витрины «Мои приложения» (Python, без фреймворков).

Источники данных:
- registry.yaml   — реестр проектов (слаг -> репозиторий);
- GitHub API      — releases/latest: версия, размер, дата, ссылки,
                    download_count (токен: переменная GITHUB_TOKEN);
- git clone (deep=1) — store.yaml, иконка, screenshots/ каждого проекта.

Инварианты (capabilities store-data-contract / store-catalog):
- битый проект (нет полей, битый YAML) -> skip + warning, сборка НЕ падает;
- файл иконки не найден -> буквенный плейсхолдер (витрина не падает);
- проект без релиза или без ассетов -> полностью скрыт;
- поле platforms/version в store.yaml -> лишнее, но не валит сборку.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from datetime import datetime, timezone

import yaml

REGISTRY_PATH = "registry.yaml"
DEFAULT_OUT_DIR = "_site"
SITE_URL = "https://dziominpavel.github.io"
GOATCOUNTER_SITE_ID = ""  # заполняется в задаче 5.3 (аккаунт владельца)
SLUG_RE = re.compile(r"^[a-z0-9-]+$")
# Относительный путь к файлу данных внутри клонированного web-источника.
DATA_PATH_RE = re.compile(r"^[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)*$")
REQUIRED_FIELDS = ("name", "description", "icon")
FORBIDDEN_FIELDS = ("version", "platforms")
GITHUB_API = "https://api.github.com"

# Авто-детект платформ по маскам ассетов (D5): поле platforms не используется.
PLATFORM_MASKS = (
    ("android", re.compile(r"\.apk$", re.I)),
    ("windows", re.compile(r"\.exe$", re.I)),
    ("windows", re.compile(r"-win.*\.zip$", re.I)),
)
PLATFORM_TITLES = {"android": "Android", "windows": "Windows"}
LETTER_COLORS = ("#2563eb", "#7c3aed", "#059669", "#d97706", "#dc2626", "#0891b2", "#db2777")


# ==========================================================================
# 4.1: реестр + GitHub API
# ==========================================================================

def load_registry(path: str = REGISTRY_PATH) -> list[dict]:
    """Читает registry.yaml: валидирует слаги [a-z0-9-], битые ключи пропускает."""
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    projects = data.get("projects") or {}
    entries: list[dict] = []
    for slug, record in projects.items():
        if not isinstance(slug, str) or not SLUG_RE.match(slug):
            print(f"[WARN] registry: ключ {slug!r} не соответствует [a-z0-9-] — пропущен",
                  file=sys.stderr)
            continue
        repo = record.get("repo") if isinstance(record, dict) else record
        if not isinstance(repo, str) or repo.count("/") != 1:
            print(f"[WARN] registry[{slug}]: некорректный repo {repo!r} — пропущена запись",
                  file=sys.stderr)
            continue
        entries.append({"slug": slug, "repo": repo})
    return entries


def load_web_registry(path: str = REGISTRY_PATH) -> list[dict]:
    """Читает секцию `web:` (D3/D6): slug [a-z0-9-], repo, title, description.

    Записи без GitHub Release и скриншотов; битые ключи/поля -> skip + warning.
    """
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    web = data.get("web") or {}
    if not isinstance(web, dict):
        print("[WARN] registry: секция web: не маппинг — проигнорирована", file=sys.stderr)
        return []
    entries: list[dict] = []
    for slug, record in web.items():
        if not isinstance(slug, str) or not SLUG_RE.match(slug):
            print(f"[WARN] registry: ключ web-записи {slug!r} не соответствует "
                  f"[a-z0-9-] — пропущен", file=sys.stderr)
            continue
        if not isinstance(record, dict):
            print(f"[WARN] registry[web:{slug}]: запись не маппинг — пропущена",
                  file=sys.stderr)
            continue
        repo = record.get("repo")
        if not isinstance(repo, str) or repo.count("/") != 1:
            print(f"[WARN] registry[web:{slug}]: некорректный repo {repo!r} — "
                  f"запись пропущена", file=sys.stderr)
            continue
        title = record.get("title")
        description = record.get("description")
        if not isinstance(title, str) or not title.strip() or \
                not isinstance(description, str) or not description.strip():
            print(f"[WARN] registry[web:{slug}]: нет title/description — запись "
                  f"пропущена", file=sys.stderr)
            continue
        # Опциональный файл данных (Benchmark: data/index.json) — рядом со
        # страницей; дата карточки берётся из его поля updated (D1/D3).
        data_file = record.get("data")
        if data_file is not None and (not isinstance(data_file, str)
                                      or not DATA_PATH_RE.match(data_file)
                                      or ".." in data_file):
            print(f"[WARN] registry[web:{slug}]: поле data {data_file!r} — "
                  f"игнорируется (ожидается относительный путь)", file=sys.stderr)
            data_file = None
        entries.append({"slug": slug, "repo": repo,
                        "title": title.strip(), "description": description.strip(),
                        "data": data_file})
    return entries


def github_api(path: str, token: str | None = None) -> dict | list:
    req = urllib.request.Request(
        f"{GITHUB_API}{path}",
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "store-generator",
            **({"Authorization": f"Bearer {token}"} if token else {}),
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def fetch_latest_release(repo: str, token: str | None = None) -> dict | None:
    """releases/latest или None (404 = релизов нет; прочие ошибки = skip + warning)."""
    try:
        return github_api(f"/repos/{repo}/releases/latest", token)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        print(f"[WARN] {repo}: GitHub API {exc.code} — проект пропущен", file=sys.stderr)
        return None
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        print(f"[WARN] {repo}: ошибка запроса ({exc}) — проект пропущен", file=sys.stderr)
        return None


def release_card(entry: dict, release: dict) -> dict:
    """Карточка данных из релиза: версия, размер, дата, ссылки, счётчик."""
    assets = release.get("assets") or []
    return {
        "slug": entry["slug"],
        "repo": entry["repo"],
        "version": (release.get("tag_name") or "").lstrip("v"),
        "size": sum(int(a.get("size") or 0) for a in assets),
        "date": release.get("published_at") or release.get("created_at"),
        "downloads": sum(int(a.get("download_count") or 0) for a in assets),
        "url": release.get("html_url"),
        "assets": assets,
    }


# ==========================================================================
# 4.3: авто-детект платформ
# ==========================================================================

def detect_platforms(assets: list[dict]) -> dict[str, list[dict]]:
    """*.apk -> Android, *.exe / *-win*.zip -> Windows; неизвестное игнорируется."""
    platforms: dict[str, list[dict]] = {}
    for asset in assets:
        name = asset.get("name") or ""
        for platform, mask in PLATFORM_MASKS:
            if mask.search(name):
                platforms.setdefault(platform, []).append(asset)
                break
        else:
            print(f"[INFO] ассет {name!r} не распознан — игнорируется", file=sys.stderr)
    return platforms


# ==========================================================================
# 4.2: контракт store.yaml / скриншотов (skip + warning, ноль падений)
# ==========================================================================

def validate_project(project_dir: str, slug: str) -> tuple[dict | None, list[str]]:
    """Валидирует store.yaml. Возвращает (данные | None, проблемы).

    Проблемы -> проект skip'ится. Отсутствие ФАЙЛА иконки проблемой не считается:
    витрина обязана показать буквенный плейсхолдер и не падать (store-catalog).
    """
    problems: list[str] = []
    store_path = os.path.join(project_dir, "store.yaml")
    if not os.path.isfile(store_path):
        return None, [f"{slug}: нет store.yaml"]
    try:
        with open(store_path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
    except yaml.YAMLError as exc:
        return None, [f"{slug}: store.yaml не парсится ({exc})"]
    if not isinstance(data, dict):
        return None, [f"{slug}: store.yaml — не маппинг полей"]

    for field in REQUIRED_FIELDS:
        if not data.get(field):
            problems.append(f"{slug}: нет обязательного поля {field!r}")
    for field in FORBIDDEN_FIELDS:
        if field in data:
            print(f"[WARN] {slug}: лишнее поле {field!r} — значение не используется "
                  f"(версия/платформы берутся из релиза)", file=sys.stderr)

    icon = str(data.get("icon") or "")
    data["_icon_missing"] = bool(icon) and not os.path.isfile(os.path.join(project_dir, icon))
    if data["_icon_missing"]:
        print(f"[WARN] {slug}: файл иконки {icon!r} не найден — будет буквенный плейсхолдер",
              file=sys.stderr)

    shots_dir = os.path.join(project_dir, "screenshots")
    shots = [f for f in sorted(os.listdir(shots_dir))
             if f.lower().endswith((".png", ".jpg", ".jpeg", ".webp"))] \
        if os.path.isdir(shots_dir) else []
    if not (3 <= len(shots) <= 5):
        problems.append(f"{slug}: скриншотов {len(shots)}, ожидается 3–5")

    if problems:
        return None, problems
    data["_screenshots"] = shots
    return data, []


# ==========================================================================
# Клонирование проектов (файлы контракта — без расхода квоты GitHub API)
# ==========================================================================

def clone_project(repo: str, dest: str, token: str | None = None) -> bool:
    url = f"https://github.com/{repo}.git"
    if token:
        url = f"https://x-access-token:{token}@github.com/{repo}.git"
    try:
        subprocess.run(
            ["git", "clone", "--depth", "1", "--quiet", url, dest],
            check=True, capture_output=True, text=True, timeout=300,
        )
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        detail = getattr(exc, "stderr", None) or exc
        print(f"[WARN] {repo}: clone не удался ({detail}) — проект пропущен", file=sys.stderr)
        return False


def collect_projects(entries: list[dict], token: str | None = None,
                     workdir: str | None = None) -> list[dict]:
    """Собирает данные проектов: контракт (файлы) + релиз (GitHub API).

    workdir — общий каталог клонов; его удаляет вызывающий ПОСЛЕ рендера
    (иконки/скриншоты копируются в витрину из клонов).
    """
    collected: list[dict] = []
    tmp_root = workdir or tempfile.mkdtemp(prefix="store-build-")
    for entry in entries:
        slug, repo = entry["slug"], entry["repo"]
        project_dir = os.path.join(tmp_root, slug)
        if not clone_project(repo, project_dir, token):
            continue
        store, problems = validate_project(project_dir, slug)
        for problem in problems:
            print(f"[WARN] {problem}", file=sys.stderr)
        if store is None:
            continue
        release = fetch_latest_release(repo, token)
        if not release or not release.get("assets"):
            print(f"[INFO] {slug}: релиза нет или он без ассетов — скрыт", file=sys.stderr)
            continue
        card = release_card(entry, release)
        card["store"] = {k: v for k, v in store.items() if not k.startswith("_")}
        card["icon_missing"] = store.get("_icon_missing", False)
        card["screenshots"] = store.get("_screenshots") or []
        card["project_dir"] = project_dir
        card["platforms"] = detect_platforms(card["assets"])
        if not card["platforms"]:
            print(f"[WARN] {slug}: ни один ассет не распознан — скрыт", file=sys.stderr)
            continue
        collected.append(card)
    if workdir is None:
        # Вызывающий не просил каталог — удаляем сами (рендер из него невозможен).
        shutil.rmtree(tmp_root, ignore_errors=True)
    return collected


def collect_web_projects(entries: list[dict], token: str | None = None,
                         workdir: str | None = None) -> list[dict]:
    """Собирает web-записи (D1/D6): клон источника + контракт папки web/.

    Успехом считается только наличие web/index.html — из него потом растут
    страница, карточка на главной и URL в sitemap (skip + warning при неудаче).
    """
    collected: list[dict] = []
    tmp_root = workdir or tempfile.mkdtemp(prefix="web-build-")
    for entry in entries:
        slug = entry["slug"]
        # web-клон в отдельном пространстве имён: slug может совпадать
        # с записью секции projects (instagram-tracker).
        project_dir = os.path.join(tmp_root, f"web-{slug}")
        if not clone_project(entry["repo"], project_dir, token):
            continue
        web_dir = os.path.join(project_dir, "web")
        if not os.path.isfile(os.path.join(web_dir, "index.html")):
            print(f"[WARN] {entry['repo']}: в web/ нет index.html — "
                  f"веб-приложение {slug!r} пропущено", file=sys.stderr)
            continue

        # Дата обновления: updated из объявленного файла данных (Benchmark),
        # иначе — дата сборки витрины (D3).
        date = datetime.now(timezone.utc).date().isoformat()
        data_file = entry.get("data")
        if data_file:
            data_path = os.path.join(project_dir, *data_file.split("/"))
            if os.path.isfile(data_path):
                try:
                    with open(data_path, encoding="utf-8") as fh:
                        updated = json.load(fh).get("updated")
                    if updated:
                        date = str(updated)
                    else:
                        print(f"[WARN] {slug}: в {data_file} нет поля updated — "
                              f"дата берётся как дата сборки", file=sys.stderr)
                except (json.JSONDecodeError, OSError, AttributeError) as exc:
                    print(f"[WARN] {slug}: {data_file} не читается ({exc}) — "
                          f"дата берётся как дата сборки", file=sys.stderr)
            else:
                print(f"[WARN] {slug}: файл данных {data_file} в источнике нет — "
                      f"не копируется, дата — дата сборки", file=sys.stderr)
                data_file = None
        else:
            data_file = None

        # Иконка карточки: web/icon.* (опционально; нет — буквенный плейсхолдер).
        icon = next((name for name in sorted(os.listdir(web_dir))
                     if name.startswith("icon.")
                     and name.lower().endswith((".png", ".svg", ".webp", ".jpg", ".jpeg"))),
                    None)

        collected.append({
            "slug": slug,
            "repo": entry["repo"],
            "title": entry["title"],
            "description": entry["description"],
            "date": date,
            "icon": icon,
            "data_file": data_file,
            "project_dir": project_dir,
            "web_dir": web_dir,
        })
        print(f"[INFO] web:{slug}: статика web/ готова к публикации", file=sys.stderr)
    if workdir is None:
        shutil.rmtree(tmp_root, ignore_errors=True)
    return collected


# ==========================================================================
# Оформление: форматирование и разметка
# ==========================================================================

def esc(value) -> str:
    return html.escape(str(value or ""), quote=True)


def fmt_size(size: int) -> str:
    size = float(size)
    for unit in ("Б", "КБ", "МБ", "ГБ"):
        if size < 1024 or unit == "ГБ":
            if unit == "Б":
                return f"{size:.0f} {unit}"
            text = f"{size:.1f} {unit}"
            return text.replace(".0 ", " ")
        size /= 1024
    return f"{size:.1f} ГБ"


def fmt_date(iso: str | None) -> str:
    if not iso:
        return "—"
    try:
        moment = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        if moment.tzinfo is None:
            # Календарная дата без таймзоны: astimezone() трактовал бы её как
            # локальное время и при выводе в UTC уводил на день назад.
            return moment.strftime("%d.%m.%Y")
        return moment.astimezone(timezone.utc).strftime("%d.%m.%Y")
    except ValueError:
        return str(iso)


def plural_apps(count: int) -> str:
    """Склонение существительного после числа: 1 приложение, 2 приложения, 5 приложений."""
    if count % 10 == 1 and count % 100 != 11:
        return "приложение"
    if 2 <= count % 10 <= 4 and not 12 <= count % 100 <= 14:
        return "приложения"
    return "приложений"


def letter_placeholder(name: str, size: str = "48") -> str:
    """Цветная буквенная заглушка по первой букве названия."""
    letter = esc(str(name).strip()[:1].upper() or "?")
    color = LETTER_COLORS[sum(str(name).encode("utf-8")) % len(LETTER_COLORS)]
    return (
        f'<span class="letter letter-{size}" style="background:{color}" '
        f'aria-hidden="true">{letter}</span>'
    )


def app_icon_html(card: dict, css_class: str, size: str = "48", root: str = "") -> str:
    if card["icon_missing"] or not card["store"].get("icon"):
        return letter_placeholder(card["store"]["name"], size)
    src = f'{root}{card["slug"]}/icon{os.path.splitext(card["store"]["icon"])[1]}'
    return (f'<img class="{esc(css_class)}" src="{esc(src)}" alt="Иконка '
            f'{esc(card["store"]["name"])}" width="96" height="96">')


SOURCES_SVG = (
    '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" '
    'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
    '<path d="M14 5h5v5"/><path d="M19 5l-8 8"/>'
    '<path d="M19 14v4a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1h4"/></svg>'
)


def buttons_html(card: dict, *, big: bool = False) -> str:
    """Кнопки скачивания по каждой платформе (варианты ассетов — с именем и размером).

    Первая кнопка — primary CTA, остальные — secondary. Мета (имя файла · размер)
    показывается всегда на странице приложения и на карточке, когда у платформы
    несколько вариантов ассета.
    """
    items = [(platform, asset)
             for platform, assets in card["platforms"].items()
             for asset in assets]
    out = []
    for index, (platform, asset) in enumerate(items):
        name = esc(asset.get("name"))
        url = esc(asset.get("browser_download_url"))
        label = esc(PLATFORM_TITLES[platform])
        size = fmt_size(int(asset.get("size") or 0))
        show_meta = big or len(card["platforms"][platform]) > 1
        kind = "btn-primary" if index == 0 else "btn-secondary"
        cls = f"btn {kind}" + (" btn-lg" if big else "")
        meta = f'<span class="btn-meta">{name} · {size}</span>' if show_meta else ""
        out.append(
            f'<a class="{cls}" href="{url}" download data-platform="{platform}">'
            f'<span class="btn-label">Скачать {label}</span>{meta}</a>'
        )
    return "\n".join(out)


def card_html(card: dict) -> str:
    store = card["store"]
    platforms = " ".join(card["platforms"])
    chips = "".join(
        f'<span class="chip chip-{p}">{esc(PLATFORM_TITLES[p])}</span>'
        for p in card["platforms"]
    )
    repo_url = esc(f"https://github.com/{card['repo']}")
    return f"""    <article class="card" data-platforms="{esc(platforms)}">
      <a class="card-head" href="{esc(card['slug'])}/">
        {app_icon_html(card, 'card-icon', '64')}
        <span class="card-title">
          <span class="card-name">{esc(store['name'])}</span>
          <span class="card-meta">v{esc(card['version'])} · {fmt_size(card['size'])}</span>
        </span>
      </a>
      <div class="chips">{chips}</div>
      <p class="card-desc">{esc(store['description'])}</p>
      <p class="card-stats"><span>Скачиваний: {card['downloads']:,}</span>
        <span aria-hidden="true">·</span><span>{fmt_date(card['date'])}</span></p>
      <div class="card-actions">
        {buttons_html(card)}
        <a class="icon-btn" href="{repo_url}" rel="noopener"
           aria-label="Исходники {esc(store['name'])} на GitHub"
           title="Исходники на GitHub">{SOURCES_SVG}</a>
      </div>
    </article>"""


def web_icon_html(web_card: dict) -> str:
    """Иконка web-карточки: web/icon.* (уже скопирован в apps/<slug>/) или заглушка."""
    if not web_card.get("icon"):
        return letter_placeholder(web_card["title"], "64")
    src = f'apps/{web_card["slug"]}/{web_card["icon"]}'
    return (f'<img class="card-icon" src="{esc(src)}" alt="Иконка '
            f'{esc(web_card["title"])}" width="96" height="96">')


def web_card_html(web_card: dict) -> str:
    """Карточка веб-приложения (store-web-apps: без версии, размера и счётчика).

    Макет консистентен с .card: head (иконка+название) → chips → описание →
    строка статистики (дата обновления) → действия; head ссылается на страницу.
    Карточка рендерится в общей сетке .grid после скачиваемых приложений."""
    url = esc(f'apps/{web_card["slug"]}/')
    repo_url = esc(f"https://github.com/{web_card['repo']}")
    return f"""      <article class="web-card">
        <a class="card-head" href="{url}">
          {web_icon_html(web_card)}
          <span class="card-title">
            <span class="card-name">{esc(web_card['title'])}</span>
          </span>
        </a>
        <div class="chips"><span class="chip chip-web">Web</span></div>
        <p class="card-desc">{esc(web_card['description'])}</p>
        <p class="card-stats"><span>Обновлено {fmt_date(web_card['date'])}</span></p>
        <div class="card-actions">
          <a class="btn btn-primary" href="{url}">Открыть в браузере</a>
          <a class="icon-btn" href="{repo_url}" rel="noopener"
             aria-label="Исходники {esc(web_card['title'])} на GitHub"
             title="Исходники на GitHub">{SOURCES_SVG}</a>
        </div>
      </article>"""


def gallery_html(card: dict) -> str:
    items = []
    for shot in card["screenshots"]:
        src = f"screenshots/{esc(shot)}"
        items.append(
            f'<a class="shot" href="{src}" target="_blank" rel="noopener">'
            f'<img src="{src}" alt="Скриншот {esc(card['store']['name'])}" loading="lazy"></a>'
        )
    if not items:
        return ""
    return '<section class="gallery"><h2>Скриншоты</h2>\n      <div class="shots">\n      \
' + "\n      ".join(items) + "\n      </div>\n    </section>"


def windows_notice_html(card: dict) -> str:
    if "windows" not in card["platforms"]:
        return ""
    return """<div class="notice">
      <strong>Windows может показать предупреждение.</strong> Файл не подписан
      сертификатом, поэтому SmartScreen или антивирус предупредят при первом запуске —
      это нормально. Код открыт: можно посмотреть и собрать самостоятельно.
    </div>"""


# ==========================================================================
# Шаблоны страниц
# ==========================================================================

BASE_TEMPLATE = """<!DOCTYPE html>
<html lang="ru" data-theme="dark">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <meta name="description" content="{description}">
  <link rel="canonical" href="{canonical}">
  <meta property="og:title" content="{title}">
  <meta property="og:description" content="{description}">
  <meta property="og:type" content="{og_type}">
  <meta property="og:url" content="{canonical}">
  <meta name="color-scheme" content="dark light">
  <meta name="theme-color" content="#0a0b10">
  <link rel="icon" type="image/svg+xml" href="{root}favicon.svg">
  <script>try{{var t=localStorage.getItem('theme');var d=document.documentElement;d.dataset.theme=(t==='light'?'light':'dark');d.style.colorScheme=d.dataset.theme;var m=document.querySelector('meta[name=theme-color]');if(m){{m.setAttribute('content',d.dataset.theme==='dark'?'#0a0b10':'#f4f6fa')}}}}catch(e){{}}</script>
  <link rel="stylesheet" href="{root}static/css/style.css">
  {analytics}
</head>
<body>
  <header class="site-header">
    <div class="site-header-inner">
      <a class="brand" href="{root}"><span class="brand-mark" aria-hidden="true">М</span>Мои приложения</a>
      <nav class="site-nav" aria-label="Навигация">
        <a href="{root}">Главная</a>
        <a href="{root}about/">О проекте</a>
        <button id="theme-toggle" class="theme-toggle" type="button" aria-label="Переключить тему" title="Переключить тему">
          <svg class="tt-icon tt-sun" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>
          <svg class="tt-icon tt-moon" viewBox="0 0 24 24" aria-hidden="true"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg>
        </button>
      </nav>
    </div>
  </header>
  <main class="site-main">
{content}
  </main>
  <footer class="site-footer">
    <p>Бесплатный каталог · <a href="{root}about/">О проекте</a> ·
       <a href="https://github.com/dziominpavel" rel="noopener">GitHub</a></p>
  </footer>
  <script src="{root}static/js/theme.js" defer></script>
  {scripts}
</body>
</html>
"""

INDEX_TEMPLATE = """    <section class="hero">
      <div class="hero-text">
        <h1>Мои приложения</h1>
        <p class="lead">Готовые приложения для скачивания: версии, размеры и кнопки — всегда свежие, из GitHub Releases.</p>
      </div>
      <ul class="hero-stats" aria-label="Статистика каталога">
        <li><strong class="stat-num">{total}</strong><span class="stat-label">{total_word}</span></li>
        <li><strong class="stat-num">{android}</strong><span class="stat-label">Android</span></li>
        <li><strong class="stat-num">{windows}</strong><span class="stat-label">Windows</span></li>
      </ul>
    </section>
    <div class="filters" role="group" aria-label="Фильтр каталога">
      <button class="filter is-active" type="button" data-filter="all">Все <span class="filter-count">{all_count}</span></button>
      <button class="filter" type="button" data-filter="android">Android <span class="filter-count">{android}</span></button>
      <button class="filter" type="button" data-filter="windows">Windows <span class="filter-count">{windows}</span></button>{web_filter}
    </div>
    <div class="grid">
{cards}
    </div>
    <p class="empty" id="empty-state" hidden>Под эту платформу пока нет приложений.</p>"""

APP_TEMPLATE = """    <nav class="crumbs"><a href="{root}">Главная</a> / {name}</nav>
    <div class="app">
      <div class="app-main">
        <header class="app-head">
          {icon}
          <div>
            <h1>{name}</h1>
            <p class="app-meta">Версия {version} · {size} · обновлено {date}</p>
            <p class="card-stats">Скачиваний: {downloads}</p>
          </div>
        </header>
        <p class="app-desc">{description}</p>
        {requirements}
        {gallery}
      </div>
      <aside class="download" aria-label="Скачивание">
        <h2>Скачать</h2>
        <div class="app-buttons">
{buttons}
        </div>
        {notice}
        <p class="sources"><a href="{repo_url}" rel="noopener">Исходники на GitHub</a></p>
      </aside>
    </div>"""

ABOUT_TEMPLATE = """    <nav class="crumbs"><a href="{root}">Главная</a> / О проекте</nav>
    <h1>О проекте</h1>
    <p class="lead">«Мои приложения» — бесплатный каталог моих приложений: описания,
    системные требования, скриншоты и кнопки скачивания.</p>
    <h2>Откуда данные</h2>
    <p>Каталог собирается автоматически: версия, размер, дата и счётчик скачиваний
    берутся из GitHub Releases каждого проекта, описания и иконки — из файлов
    самого проекта. Ручная работа не нужна: выпустил релиз — витрина обновилась.</p>
    <h2>Почему всё так</h2>
    <p>Только бесплатные сервисы (GitHub Pages, GitHub Actions), никаких платных
    подписок и cookie-баннеров. Сайт открыт: исходники витрины —
    <a href="https://github.com/dziominpavel/dziominpavel.github.io" rel="noopener">репозиторий
    dziominpavel.github.io</a>. Код самих приложений тоже открыт.</p>
    <h2>Связаться</h2>
    <p>Вопросы и идеи — через <a href="https://github.com/dziominpavel" rel="noopener">профиль
    на GitHub</a>.</p>"""

FAVICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
  <rect width="64" height="64" rx="14" fill="#2563eb"/>
  <text x="32" y="44" font-family="system-ui, sans-serif" font-size="36" font-weight="700"
        text-anchor="middle" fill="#ffffff">М</text>
</svg>
"""


def analytics_html() -> str:
    if not GOATCOUNTER_SITE_ID:
        return "<!-- GoatCounter: site ID не задан (задача 5.3) -->"
    return (f'<script data-goatcounter="https://{GOATCOUNTER_SITE_ID}.goatcounter.com/count" '
            f'src="//gc.zgo.at/count.js" async></script>')


def render_page(*, title: str, description: str, canonical: str, content: str,
                root: str, og_type: str = "website", scripts: str = "") -> str:
    return BASE_TEMPLATE.format(
        title=esc(title),
        description=esc(description),
        canonical=esc(canonical),
        og_type=og_type,
        root=root,
        content=content,
        analytics=analytics_html(),
        scripts=scripts,
    )


def write_page(path: str, markup: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(markup)


def render_site(cards: list[dict], web_cards: list[dict], out_dir: str) -> list[str]:
    """Генерирует главную, страницы приложений, «О проекте», favicon, sitemap.

    Возвращает список относительных путей всех страниц (для sitemap).
    """
    if os.path.isdir(out_dir):
        shutil.rmtree(out_dir)
    os.makedirs(out_dir, exist_ok=True)
    pages: list[str] = [""]

    # --- главная -----------------------------------------------------------
    # Единая сетка: сначала скачиваемые приложения, затем web-карточки —
    # одним потоком, без отдельной секции.
    parts = [card_html(card) for card in cards]
    parts += [web_card_html(web_card) for web_card in web_cards]
    cards_html = "\n".join(parts) or \
        "    <p class=\"empty\">Пока нет опубликованных приложений.</p>"
    total = len(cards)
    n_android = sum(1 for c in cards if "android" in c["platforms"])
    n_windows = sum(1 for c in cards if "windows" in c["platforms"])
    # Сегмент Web: отдельный пункт фильтра для web-карточек (они видны
    # под «Все»/«Web» и скрыты под Android/Windows).
    web_filter = (
        '\n      <button class="filter" type="button" data-filter="web">'
        f'Web <span class="filter-count">{len(web_cards)}</span></button>'
        if web_cards else "")
    index = INDEX_TEMPLATE.format(cards=cards_html, total=total, android=n_android,
                                  windows=n_windows, total_word=plural_apps(total),
                                  all_count=total + len(web_cards),
                                  web_filter=web_filter)
    write_page(os.path.join(out_dir, "index.html"),
               render_page(title="Мои приложения — каталог для скачивания",
                           description="Каталог готовых приложений: версии, размеры и кнопки "
                                       "скачивания из GitHub Releases.",
                           canonical=f"{SITE_URL}/", content=index, root="",
                           scripts='<script src="static/js/filter.js" defer></script>'))

    # --- страницы приложений ----------------------------------------------
    for card in cards:
        store = card["store"]
        requirements = ""
        if store.get("requirements"):
            requirements = (f'<p class="requirements"><strong>Системные требования:</strong> '
                            f'{esc(store["requirements"])}</p>')
        app = APP_TEMPLATE.format(
            root="../",
            name=esc(store["name"]),
            icon=app_icon_html(card, "app-icon", "96", root="../"),
            version=esc(card["version"]),
            size=fmt_size(card["size"]),
            date=fmt_date(card["date"]),
            downloads=f"{card['downloads']:,}",
            description=esc(store["description"]),
            requirements=requirements,
            notice=windows_notice_html(card),
            buttons=buttons_html(card, big=True),
            repo_url=esc(f"https://github.com/{card['repo']}"),
            gallery=gallery_html(card),
        )
        write_page(os.path.join(out_dir, card["slug"], "index.html"),
                   render_page(title=f"{store['name']} — скачать для "
                                     f"{', '.join(PLATFORM_TITLES[p] for p in card['platforms'])}",
                               description=store["description"],
                               canonical=f"{SITE_URL}/{card['slug']}/",
                               content=app, root="../", og_type="website"))
        pages.append(card["slug"])

        # файлы проекта на страницу: иконка + скриншоты
        icon = store.get("icon")
        if icon and not card["icon_missing"]:
            src = os.path.join(card["project_dir"], icon)
            ext = os.path.splitext(icon)[1] or ".png"
            if os.path.isfile(src):
                shutil.copy2(src, os.path.join(out_dir, card["slug"], f"icon{ext}"))
        shots_src = os.path.join(card["project_dir"], "screenshots")
        if card["screenshots"] and os.path.isdir(shots_src):
            shots_dst = os.path.join(out_dir, card["slug"], "screenshots")
            os.makedirs(shots_dst, exist_ok=True)
            for shot in card["screenshots"]:
                shutil.copy2(os.path.join(shots_src, shot), os.path.join(shots_dst, shot))

    # --- веб-приложения: /apps/<slug>/ (D1: успех копирования = всё) --------
    for web_card in web_cards:
        dest = os.path.join(out_dir, "apps", web_card["slug"])
        shutil.copytree(web_card["web_dir"], dest)
        # Объявленный файл данных — рядом со страницей (Benchmark: index.json,
        # страница читает его локальным fetch).
        if web_card.get("data_file"):
            src = os.path.join(web_card["project_dir"], *web_card["data_file"].split("/"))
            shutil.copy2(src, os.path.join(dest, os.path.basename(web_card["data_file"])))
        pages.append(f"apps/{web_card['slug']}")

    # --- «О проекте» --------------------------------------------------------
    write_page(os.path.join(out_dir, "about", "index.html"),
               render_page(title="О проекте — Мои приложения",
                           description="Как устроен бесплатный каталог приложений: "
                                       "автосборка из GitHub Releases и открытый код.",
                           canonical=f"{SITE_URL}/about/", content=ABOUT_TEMPLATE.format(root="../"),
                           root="../"))
    pages.append("about")

    # --- статика, favicon ---------------------------------------------------
    shutil.copytree("static", os.path.join(out_dir, "static"))
    with open(os.path.join(out_dir, "favicon.svg"), "w", encoding="utf-8") as fh:
        fh.write(FAVICON_SVG)

    # --- sitemap.xml --------------------------------------------------------
    urls = [f"{SITE_URL}/{p}/" if p else f"{SITE_URL}/" for p in pages]
    entries = "\n".join(
        f"  <url><loc>{esc(url)}</loc><changefreq>daily</changefreq></url>"
        for url in urls
    )
    with open(os.path.join(out_dir, "sitemap.xml"), "w", encoding="utf-8") as fh:
        fh.write('<?xml version="1.0" encoding="UTF-8"?>\n'
                 '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
                 f"{entries}\n</urlset>\n")
    return urls


# ==========================================================================
# CLI
# ==========================================================================

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Генератор витрины «Мои приложения»")
    parser.add_argument("--json", action="store_true",
                        help="вывести собранные карточки в JSON и выйти")
    parser.add_argument("--out", default=DEFAULT_OUT_DIR, help="каталог вывода (по умолчанию _site)")
    args = parser.parse_args(argv)

    token = os.environ.get("GITHUB_TOKEN") or None
    entries = load_registry()
    web_entries = load_web_registry()
    workdir = tempfile.mkdtemp(prefix="store-build-")
    try:
        cards = collect_projects(entries, token, workdir=workdir)

        if args.json:
            slim = [{k: v for k, v in card.items()
                     if k not in ("store", "project_dir", "assets", "screenshots")}
                    | {"platforms": {p: [a["name"] for a in variants]
                                     for p, variants in card["platforms"].items()}}
                    for card in cards]
            json.dump(slim, sys.stdout, ensure_ascii=False, indent=2, default=str)
            print()
            return 0

        web_cards = collect_web_projects(web_entries, token, workdir=workdir)
        pages = render_site(cards, web_cards, args.out)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    print(f"projects: {len(cards)}, web: {len(web_cards)}, pages: {len(pages)}, "
          f"out: {args.out}")
    for card in cards:
        print(f"  {card['slug']}: v{card['version']} "
              f"({', '.join(PLATFORM_TITLES[p] for p in card['platforms'])})")
    for web_card in web_cards:
        print(f"  web:{web_card['slug']}: /apps/{web_card['slug']}/ "
              f"(обновлено {fmt_date(web_card['date'])})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
