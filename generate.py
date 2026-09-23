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
    """Собирает данные проектов: контракт (файлы) + релиз (GitHub API)."""
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
        moment = moment.astimezone(timezone.utc)
        return moment.strftime("%d.%m.%Y")
    except ValueError:
        return str(iso)


def letter_placeholder(name: str, size: str = "48") -> str:
    """Цветная буквенная заглушка по первой букве названия."""
    letter = esc(str(name).strip()[:1].upper() or "?")
    color = LETTER_COLORS[sum(str(name).encode("utf-8")) % len(LETTER_COLORS)]
    return (
        f'<span class="letter letter-{size}" style="background:{color}" '
        f'aria-hidden="true">{letter}</span>'
    )


def app_icon_html(card: dict, css_class: str, size: str = "48") -> str:
    if card["icon_missing"] or not card["store"].get("icon"):
        return letter_placeholder(card["store"]["name"], size)
    src = f'{card["slug"]}/icon{os.path.splitext(card["store"]["icon"])[1]}'
    return (f'<img class="{esc(css_class)}" src="{esc(src)}" alt="Иконка '
            f'{esc(card["store"]["name"])}" width="96" height="96">')


def buttons_html(card: dict, *, big: bool = False) -> str:
    """Кнопки скачивания по каждой платформе (варианты ассетов — с именем и размером)."""
    out = []
    for platform, assets in card["platforms"].items():
        for asset in assets:
            name = esc(asset.get("name"))
            url = esc(asset.get("browser_download_url"))
            label = PLATFORM_TITLES[platform]
            size = fmt_size(int(asset.get("size") or 0))
            cls = f"btn btn-{platform}" + (" btn-lg" if big else "")
            extra = f'<span class="btn-meta">{name} · {size}</span>' if big else ""
            out.append(
                f'<a class="{cls}" href="{url}" download data-platform="{platform}">'
                f'Скачать {esc(label)}{extra}</a>'
            )
    return "\n".join(out)


def card_html(card: dict) -> str:
    store = card["store"]
    platforms = " ".join(card["platforms"])
    badges = "".join(
        f'<span class="badge badge-{p}">{esc(PLATFORM_TITLES[p])}</span>'
        for p in card["platforms"]
    )
    return f"""    <article class="card" data-platforms="{esc(platforms)}">
      <a class="card-head" href="{esc(card['slug'])}/">
        {app_icon_html(card, 'card-icon', '64')}
        <span class="card-title">
          <span class="card-name">{esc(store['name'])}</span>
          <span class="card-version">v{esc(card['version'])} · {fmt_size(card['size'])}</span>
        </span>
      </a>
      <p class="card-desc">{esc(store['description'])}</p>
      <div class="badges">{badges}</div>
      <div class="card-actions">{buttons_html(card)}</div>
      <p class="downloads">Скачиваний: {card['downloads']:,}</p>
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
    return """<aside class="notice">
      <strong>Windows может показать предупреждение.</strong> Файл не подписан
      сертификатом, поэтому SmartScreen или антивирус предупредят при первом запуске —
      это нормально. Код открыт: можно посмотреть и собрать самостоятельно.
    </aside>"""


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
  <meta name="theme-color" content="#0f1419">
  <link rel="icon" type="image/svg+xml" href="{root}favicon.svg">
  <link rel="stylesheet" href="{root}static/css/style.css">
  {analytics}
</head>
<body>
  <header class="site-header">
    <a class="brand" href="{root}">Мои приложения</a>
    <nav class="site-nav">
      <a href="{root}">Главная</a>
      <a href="{root}about/">О проекте</a>
      <button id="theme-toggle" class="theme-toggle" type="button">Тема: {theme_label}</button>
    </nav>
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

INDEX_TEMPLATE = """    <h1>Мои приложения</h1>
    <p class="lead">Готовые приложения для скачивания: версии, размеры и кнопки — всегда свежие, из GitHub Releases.</p>
    <div class="filters" role="group" aria-label="Фильтр по платформе">
      <button class="filter is-active" type="button" data-filter="all">Все</button>
      <button class="filter" type="button" data-filter="android">Android</button>
      <button class="filter" type="button" data-filter="windows">Windows</button>
    </div>
    <div class="grid">
{cards}
    </div>
    <p class="empty" id="empty-state" hidden>Под эту платформу пока нет приложений.</p>"""

APP_TEMPLATE = """    <nav class="crumbs"><a href="{root}">Главная</a> / {name}</nav>
    <article class="app">
      <header class="app-head">
        {icon}
        <div>
          <h1>{name}</h1>
          <p class="app-meta">Версия {version} · {size} · обновлено {date}</p>
          <p class="downloads">Скачиваний: {downloads}</p>
        </div>
      </header>
      <p class="app-desc">{description}</p>
      {requirements}
      {notice}
      <section class="download">
        <h2>Скачать</h2>
        <div class="app-buttons">
{buttons}
        </div>
        <p class="sources"><a href="{repo_url}" rel="noopener">Исходники</a></p>
      </section>
      {gallery}
    </article>"""

ABOUT_TEMPLATE = """    <nav class="crumbs"><a href="{root}">Главная</a> / О проекте</h1></nav>
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
        theme_label="{theme_label}",
    )


def write_page(path: str, markup: str, theme_label: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(markup.replace("{theme_label}", theme_label))


def render_site(cards: list[dict], out_dir: str) -> list[str]:
    """Генерирует главную, страницы приложений, «О проекте», favicon, sitemap.

    Возвращает список относительных путей всех страниц (для sitemap).
    """
    if os.path.isdir(out_dir):
        shutil.rmtree(out_dir)
    os.makedirs(out_dir, exist_ok=True)
    pages: list[str] = [""]

    # --- главная -----------------------------------------------------------
    cards_html = "\n".join(card_html(card) for card in cards) or \
        "    <p class=\"empty\">Пока нет опубликованных приложений.</p>"
    index = INDEX_TEMPLATE.format(cards=cards_html)
    write_page(os.path.join(out_dir, "index.html"),
               render_page(title="Мои приложения — каталог для скачивания",
                           description="Каталог готовых приложений: версии, размеры и кнопки "
                                       "скачивания из GitHub Releases.",
                           canonical=f"{SITE_URL}/", content=index, root=""),
               "Тёмная")

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
            icon=app_icon_html(card, "app-icon", "96"),
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
                               content=app, root="../", og_type="website"),
                   "Тёмная")
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

    # --- «О проекте» --------------------------------------------------------
    write_page(os.path.join(out_dir, "about", "index.html"),
               render_page(title="О проекте — Мои приложения",
                           description="Как устроен бесплатный каталог приложений: "
                                       "автосборка из GitHub Releases и открытый код.",
                           canonical=f"{SITE_URL}/about/", content=ABOUT_TEMPLATE.format(root="../"),
                           root="../"),
               "Тёмная")
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
    cards = collect_projects(entries, token)

    if args.json:
        slim = [{k: v for k, v in card.items()
                 if k not in ("store", "project_dir", "assets", "screenshots")}
                | {"platforms": {p: [a["name"] for a in variants]
                                 for p, variants in card["platforms"].items()}}
                for card in cards]
        json.dump(slim, sys.stdout, ensure_ascii=False, indent=2, default=str)
        print()
        return 0

    pages = render_site(cards, args.out)
    print(f"projects: {len(cards)}, pages: {len(pages)}, out: {args.out}")
    for card in cards:
        print(f"  {card['slug']}: v{card['version']} "
              f"({', '.join(PLATFORM_TITLES[p] for p in card['platforms'])})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
