#!/usr/bin/env python3
"""Проверка версионирования (см. docs/versioning.md).

Режимы:
  python scripts/check-version.py                 # текущий проект
  python scripts/check-version.py --all           # все проекты из versioning.yaml
  python scripts/check-version.py --project KEY   # один проект из versioning.yaml

Проверяет:
1. `CHANGELOG.md` — есть, первая секция `## ` — `## [Unreleased]`.
2. Файл версии (для релизного трека) — строгий semver MAJOR.MINOR.PATCH.
3. Рассинхрон: верхняя версионная секция CHANGELOG == файл версии.
   - теги есть, а версионной секции нет (или наоборот) -> ошибка;
   - тегов нет вообще -> версионная секция не требуется (сводная история).
4. Статический трек: только проверки changelog и формата файла версии,
   сверка с секциями не выполняется (версия заморожена).
5. Подсказка: есть ли накопленные пункты в `[Unreleased]` (решение о бампе
   принимается по ним, а не по списку изменённых путей).
6. Верхний блок секции `[Unreleased]` — часть выше первой строки `###` — по
   формат-контракту гейта release-скрипта: каждая непустая строка блока либо
   жирная метка `**…**`, либо буллет; в блоке ≥1 буллет; строка ≤140
   символов; символ '`' запрещён; секция с пунктами не начинается с `###`.
   Пустая секция (нет пунктов) не проверяется — это подсказка NO_BUMP.
   Версионные секции, включая исторические, не проверяются.

Код возврата: 0 — ок, 1 — ошибка.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
UNRELEASED_HEAD = re.compile(r"^## \[Unreleased\]\s*$")
VERSION_HEAD = re.compile(r"^## \[?(\d+\.\d+\.\d+)\]?")
ANY_HEAD = re.compile(r"^## ")
PYPROJECT_VERSION = re.compile(r'^\s*version\s*=\s*"([^"]+)"', re.MULTILINE)


class Result:
    def __init__(self) -> None:
        self.errors: list[str] = []

    def fail(self, msg: str) -> None:
        self.errors.append(msg)
        print(f"ERROR: {msg}", flush=True)


def read_version_file(path: Path) -> tuple[str | None, str | None]:
    """Возвращает (значение, ошибка)."""
    try:
        if path.name == "pyproject.toml":
            m = PYPROJECT_VERSION.search(path.read_text(encoding="utf-8"))
            if not m:
                return None, f"{path.name}: нет поля version = ..."
            return m.group(1), None
        raw = path.read_bytes().decode("ascii", errors="strict").strip()
    except (UnicodeDecodeError, OSError) as e:
        return None, f"{path.name}: не читается как ASCII-строка: {e}"
    if raw.startswith("\ufeff"):
        return None, f"{path.name}: содержит BOM"
    if "\n" in raw:
        return None, f"{path.name}: больше одной строки: {raw!r}"
    return raw, None


def has_tags(project_dir: Path) -> bool | None:
    """True/False или None, если git недоступен."""
    import subprocess

    if not (project_dir / ".git").exists():
        return None
    try:
        out = subprocess.run(
            ["git", "tag", "--list"],
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except Exception:
        return None
    if out.returncode != 0:
        return None
    return bool([t for t in out.stdout.splitlines() if t.strip()])


def unreleased_items(changelog_text: str) -> list[str]:
    """Пункты секции [Unreleased] (строки, не заголовки и не пустые)."""
    lines = changelog_text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if ANY_HEAD.match(line.strip()):
            if UNRELEASED_HEAD.match(line.strip()):
                start = i + 1
            break
    if start is None:
        return []
    items = []
    for line in lines[start:]:
        s = line.strip()
        if ANY_HEAD.match(s):
            break
        if s.startswith(("#", "---", "===", "***")) or not s:
            continue
        items.append(s)
    return items


def unreleased_block_problems(text: str) -> list[str]:
    """Проблемы верхнего блока секции [Unreleased] по формат-контракту.

    Контракт зеркалит Get-NotesBlockProblems из release.ps1 (гейт -Prepare):
    непустая строка блока — жирная метка '**…**' либо буллет '- …'; в блоке
    ≥1 буллет; строка ≤140 символов (сырая, как в гейте); символ '`'
    запрещён; секция с пунктами не начинается с '###' (блок обязателен).
    Пустая секция (нет пунктов) не проверяется — это подсказка NO_BUMP, а не
    ошибка. Проверяется только [Unreleased]: версионные секции, включая
    исторические, контракту верхнего блока не подлежат.
    """
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        s = line.strip()
        if ANY_HEAD.match(s):
            if UNRELEASED_HEAD.match(s):
                start = i + 1
            break
    if start is None:
        return []
    section: list[str] = []
    for line in lines[start:]:
        s = line.strip()
        if ANY_HEAD.match(s):
            break
        section.append(line)
    # Пункты секции — как в гейте: непустые строки, кроме '###'-категорий.
    if not [s for s in (ln.strip() for ln in section) if s and not s.startswith("###")]:
        return []
    # Блок — всё до первой строки '###' (как Get-ReleaseNotes, но без
    # обрезки пустых краёв: их отсутствие и есть «блок пуст»).
    block: list[str] = []
    for line in section:
        if line.startswith("###"):
            break
        block.append(line)
    problems: list[str] = []
    if not any(ln.strip() for ln in block):
        problems.append("нет верхнего блока: секция с пунктами начинается с ###")
        return problems
    has_bullet = False
    for raw in block:
        s = raw.strip()
        if not s:
            continue
        is_label = bool(re.match(r"^\*\*[^*]+\*\*$", s))
        is_bullet = bool(re.match(r"^-\s+\S", s))
        if is_bullet:
            has_bullet = True
        if not is_label and not is_bullet:
            problems.append(f"не жирная метка и не буллет: {raw}")
            continue
        if len(raw) > 140:
            problems.append(f"строка длиннее 140 символов ({len(raw)}): {raw}")
            continue
        if "`" in raw:
            problems.append(f"символ ```'``` запрещён внутри блока: {raw}")
    if not has_bullet:
        problems.append("в блоке нет ни одного буллета")
    return problems


def check_changelog(changelog: Path, res: Result) -> tuple[str | None, str | None]:
    """Проверяет структуру changelog. Возвращает (текст, верхняя версионная секция)."""
    if not changelog.exists():
        res.fail(f"нет {changelog.name}")
        return None, None
    try:
        # utf-8-sig: BOM в changelog допустим (Windows-редакторы),
        # в отличие от файла версии, где BOM — ошибка.
        text = changelog.read_text(encoding="utf-8-sig")
    except (UnicodeDecodeError, OSError) as e:
        res.fail(f"{changelog.name}: не читается как UTF-8: {e}")
        return None, None

    first = next((ln.strip() for ln in text.splitlines() if ANY_HEAD.match(ln.strip())), None)
    if first is None:
        res.fail(f"{changelog.name}: нет ни одной секции ## ")
        return text, None
    if not UNRELEASED_HEAD.match(first):
        res.fail(
            f"{changelog.name}: первая секция должна быть '## [Unreleased]', "
            f"фактически {first!r}"
        )
    head = next(
        (m.group(1) for ln in text.splitlines() if (m := VERSION_HEAD.match(ln.strip()))),
        None,
    )
    return text, head


def print_unreleased_hint(text: str | None) -> None:
    if text is None:
        return
    items = unreleased_items(text)
    if items:
        print(
            f"[Unreleased]: накоплено пунктов — {len(items)}. "
            "Бамп будет на следующем релизе; сейчас version не трогай."
        )
    else:
        print("[Unreleased]: пуст — бампать нечего (NO_BUMP).")


def check_project(
    label: str,
    project_dir: Path,
    track: str,
    version_file: str | None,
    changelog_name: str,
) -> Result:
    res = Result()
    print(f"--- {label} ({project_dir}) ---")
    if not project_dir.is_dir():
        res.fail("каталог проекта не найден")
        return res

    text, head = check_changelog(project_dir / changelog_name, res)
    print_unreleased_hint(text)
    if text is not None:
        for problem in unreleased_block_problems(text):
            res.fail(f"{changelog_name}: блок [Unreleased]: {problem}")

    if track == "static":
        if version_file:
            path = project_dir / version_file
            if not path.exists():
                res.fail(f"нет файла версии {version_file}")
            else:
                value, err = read_version_file(path)
                if err:
                    res.fail(err)
                elif not SEMVER.match(value or ""):
                    res.fail(f"{version_file}: не semver MAJOR.MINOR.PATCH: {value!r}")
                else:
                    print(f"version (static, заморожена): {value}")
        if head is None and text is not None:
            print("versioned head: отсутствует (статический трек — допустимо)")
        elif head:
            print(f"versioned head: {head}")
        return res

    # Релизный трек
    if not version_file:
        res.fail("релизный трек требует файл версии (version_file)")
        return res
    path = project_dir / version_file
    if not path.exists():
        res.fail(f"нет файла версии {version_file}")
        return res
    value, err = read_version_file(path)
    if err:
        res.fail(err)
        return res
    if not SEMVER.match(value or ""):
        res.fail(f"{version_file}: не semver MAJOR.MINOR.PATCH: {value!r}")
        return res
    print(f"version: {value}")

    if text is None:
        return res

    tags = has_tags(project_dir)
    if head is None:
        if tags:
            res.fail(
                f"{changelog_name}: теги есть, а версионной секции нет — "
                "сделай бэкфилл (docs/versioning.md, раздел «Первичное заполнение»)"
            )
        else:
            print("versioned head: отсутствует (тегов нет — сводная история, ок)")
        return res

    print(f"versioned head: {head}")
    if head != value:
        res.fail(
            f"рассинхрон: {version_file}={value}, верх {changelog_name}={head}. "
            "При бампе обнови оба файла за раз."
        )
    return res


def load_manifest(path: Path) -> dict:
    import yaml

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    projects = data.get("projects")
    if not isinstance(projects, dict) or not projects:
        raise ValueError("versioning.yaml: нет секции projects")
    return projects


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Проверка версионирования")
    parser.add_argument("--all", action="store_true", help="все проекты из versioning.yaml")
    parser.add_argument("--project", help="ключ проекта в versioning.yaml")
    args = parser.parse_args(argv)

    manifest = ROOT / "versioning.yaml"
    results: list[Result] = []

    if args.all or args.project:
        if not manifest.exists():
            print("ERROR: versioning.yaml не найден рядом со скриптом", flush=True)
            return 1
        try:
            projects = load_manifest(manifest)
        except Exception as e:
            print(f"ERROR: {e}", flush=True)
            return 1
        if args.project:
            if args.project not in projects:
                print(
                    f"ERROR: проект {args.project!r} отсутствует в versioning.yaml "
                    f"(есть: {', '.join(projects)})",
                    flush=True,
                )
                return 1
            projects = {args.project: projects[args.project]}

        for key, cfg in projects.items():
            rel = cfg.get("path", f"../{key}")
            project_dir = (manifest.parent / rel).resolve()
            results.append(
                check_project(
                    key,
                    project_dir,
                    cfg.get("track", "release"),
                    cfg.get("version_file"),
                    cfg.get("changelog", "CHANGELOG.md"),
                )
            )
    else:
        # Самопроверка проекта: тракт по файлам, без versioning.yaml.
        track = "static" if not (ROOT / "version").exists() and not (ROOT / "VERSION").exists() else "release"
        version_file = None
        if (ROOT / "version").exists():
            version_file = "version"
        elif (ROOT / "VERSION").exists():
            version_file = "VERSION"
        elif (ROOT / "pyproject.toml").exists():
            version_file = "pyproject.toml"
        results.append(check_project(ROOT.name, ROOT, track, version_file, "CHANGELOG.md"))

    # Подсказка по [Unreleased] печатается внутри check_project.

    bad = [r for r in results if r.errors]
    print()
    print(
        f"Итого: {len(results)} проверено, {len(results) - len(bad)} ок, "
        f"{len(bad)} с ошибками"
    )
    return 1 if bad else 0


if __name__ == "__main__":
    # Консоль Windows (cp1251) не должна падать на символах из текста
    # changelog (например, '≤'): заменяем их '?', код возврата не страдает.
    sys.stdout.reconfigure(errors="replace")
    sys.exit(main(sys.argv[1:]))
