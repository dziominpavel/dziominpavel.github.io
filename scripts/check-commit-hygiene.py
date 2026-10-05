#!/usr/bin/env python3
"""Проверка коммитов на агентские трейлеры (см. AGENTS.md, блок commit-hygiene).

Режимы:
  python scripts/check-commit-hygiene.py                 # проект текущего каталога
  python scripts/check-commit-hygiene.py --all           # все проекты из versioning.yaml
  python scripts/check-commit-hygiene.py --project KEY   # один проект из versioning.yaml

Критерий (дословно из Benchmark/.devin/rules/git.md, design D2): строка,
начинающаяся с `Co-Authored-By:` или `Generated with`. Упоминание запрета внутри
предложения трейлером не считается — проверяется только начало строки.

Находки делятся на две группы:
  VIOL  — коммит выгружен в origin (нарушение в удалённой истории, из-за него
          список Contributors на GitHub показывает ботов);
  LOCAL — коммит существует только локально (ветка/реф, не выгруженный в origin).

Обе группы — нарушение: скрипт завершается кодом 1, если найдено хоть что-то,
и кодом 0, если трейлеров нет нигде.

Проекты с `git: false` и без локальной копии пропускаются с пометкой SKIP.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# design D2: начало строки, а не любое упоминание.
# Ведущий класс `[ \t]*`, а не `\s*`: `\s` включает `\n` и перескакивает
# на предыдущую строку, из-за чего match.start() указывает мимо трейлера.
PATTERNS = [
    ("Co-Authored-By", re.compile(r"(?m)^[ \t]*Co-[Aa]uthored-[Bb]y:\s+\S")),
    ("Generated with", re.compile(r"(?m)^[ \t]*Generated with")),
]
RS = "\x1e"  # разделитель записей в выводе git log (по `%x1e`)
FS = "\x00"  # разделитель полей записи (по `%x00`)


def git(cwd: Path, args: list[str]) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} -> {proc.returncode}: {proc.stderr.strip()}"
        )
    return proc.stdout


def iter_commits(cwd: Path):
    """(хеш, сообщение) по всем рефам репозитория."""
    out = git(cwd, ["log", "--all", "--format=%H%x00%B%x1e"])
    for record in out.split(RS):
        record = record.strip("\r\n")
        if not record:
            continue
        sha, sep, msg = record.partition(FS)
        if sep:
            yield sha.strip(), msg


def remote_hashes(cwd: Path) -> set[str]:
    """Хеши, выгруженные в origin: ветки refs/remotes/* и теги refs/tags/*."""
    refs = [
        r
        for r in git(cwd, ["for-each-ref", "--format=%(refname)",
                           "refs/remotes", "refs/tags"]).splitlines()
        if r.strip()
    ]
    if not refs:
        return set()
    out = git(cwd, ["rev-list", *refs])
    return {h for h in out.split() if h}


def first_line(msg: str, match: re.Match) -> str:
    line = msg[match.start():].splitlines()[0].strip()
    return line[:100]


def check_repo(key: str, path: Path) -> dict:
    res = {"key": key, "path": path, "viol": [], "local": [], "error": None}

    if not path.exists():
        res["error"] = f"нет локальной копии: {path}"
        return res
    if not (path / ".git").exists():
        res["error"] = f"не git-репозиторий: {path}"
        return res

    try:
        remote = remote_hashes(path)
        for sha, msg in iter_commits(path):
            for name, pat in PATTERNS:
                m = pat.search(msg)
                if not m:
                    continue
                entry = (sha, name, first_line(msg, m))
                if sha in remote:
                    res["viol"].append(entry)
                else:
                    res["local"].append(entry)
                break
    except Exception as e:  # noqa: BLE001 — сообщаем, а не падаем молча
        res["error"] = str(e)
    return res


def load_manifest(path: Path) -> dict:
    import yaml

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    projects = data.get("projects")
    if not isinstance(projects, dict) or not projects:
        raise ValueError("versioning.yaml: нет секции projects")
    return projects


def project_for_cwd(projects: dict, manifest: Path) -> tuple[str, dict]:
    """Проект, которому принадлежит текущий каталог."""
    cwd = Path.cwd().resolve()
    best_key, best_cfg, best_len = None, None, -1
    for key, cfg in projects.items():
        rel = cfg.get("path", f"../{key}")
        p = (manifest.parent / rel).resolve()
        try:
            cwd.relative_to(p)
        except ValueError:
            continue
        if len(str(p)) > best_len:
            best_key, best_cfg, best_len = key, cfg, len(str(p))
    if best_key is None:
        raise ValueError(
            f"текущий каталог {cwd} не входит ни в один проект versioning.yaml "
            f"(используй --all или --project KEY)"
        )
    return best_key, best_cfg


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Проверка коммитов на агентские трейлеры"
    )
    parser.add_argument("--all", action="store_true",
                        help="все проекты из versioning.yaml")
    parser.add_argument("--project", help="ключ проекта в versioning.yaml")
    args = parser.parse_args(argv)

    manifest = ROOT / "versioning.yaml"
    if not manifest.exists():
        print("ERROR: versioning.yaml не найден рядом со скриптом", flush=True)
        return 1
    try:
        projects = load_manifest(manifest)
    except Exception as e:  # noqa: BLE001
        print(f"ERROR: {e}", flush=True)
        return 1

    selected: dict[str, dict] = {}
    if args.all:
        selected = projects
    elif args.project:
        if args.project not in projects:
            print(
                f"ERROR: проект {args.project!r} отсутствует в versioning.yaml "
                f"(есть: {', '.join(projects)})",
                flush=True,
            )
            return 1
        selected = {args.project: projects[args.project]}
    else:
        try:
            key, cfg = project_for_cwd(projects, manifest)
        except ValueError as e:
            print(f"ERROR: {e}", flush=True)
            return 1
        selected = {key: cfg}

    total_viol = total_local = skipped = 0
    for key, cfg in selected.items():
        if cfg.get("git") is False:
            print(f"SKIP  {key}: git: false в versioning.yaml")
            skipped += 1
            continue

        path = (manifest.parent / cfg.get("path", f"../{key}")).resolve()
        res = check_repo(key, path)

        if res["error"]:
            print(f"SKIP  {key}: {res['error']}")
            skipped += 1
            continue

        if not res["viol"] and not res["local"]:
            print(f"OK    {key}: трейлеров нет")
            continue

        print(f"--- {key} ({path}) ---")
        for sha, name, line in res["viol"]:
            print(f"VIOL  {sha}  [{name}]  {line}")
        for sha, name, line in res["local"]:
            print(f"LOCAL {sha}  [{name}]  {line}  (не выгружен в origin)")
        total_viol += len(res["viol"])
        total_local += len(res["local"])

    print()
    print(
        f"Итого: нарушений в выгруженной истории {total_viol}, "
        f"локальных {total_local}, пропущено {skipped}"
    )
    return 1 if (total_viol or total_local) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
