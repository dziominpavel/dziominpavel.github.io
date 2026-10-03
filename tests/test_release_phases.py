#!/usr/bin/env python3
"""Юнит-тесты двухфазного release-скрипта (capability app-release-pipeline).

Запуск: python tests/test_release_phases.py

Песочница самодостаточна и не ходит в сеть:
- фикстурный git-репозиторий с файлами version/CHANGELOG.md/store.yaml/dist;
- локальный «remote», в пути которого есть github.com (проходит регэксп скрипта);
- gh-shim на первом месте PATH: `gh auth status` -> 0, всё остальное -> 1,
  поэтому публикация доходит до тега и откатывается, не создавая реальный релиз.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "release.ps1"

PASS = 0


def find_shell() -> list[str] | None:
    """Аргументы запуска PowerShell, либо None, если шелла нет."""
    exe = shutil.which("powershell") or shutil.which("pwsh")
    if not exe:
        return None
    args = [exe, "-NoProfile"]
    if Path(exe).name.lower().startswith("powershell"):
        args += ["-ExecutionPolicy", "Bypass"]
    args += ["-Command"]
    return args


SHELL = find_shell()


def run_release(app: Path, *flags: str) -> tuple[int, str]:
    """Запуск release.ps1 в песочнице. Возвращает (код, вывод UTF-8)."""
    assert SHELL is not None, "PowerShell недоступен"
    script = str(app / "release.ps1")
    inner = f"& '{script}'"
    if flags:
        inner += " " + " ".join(flags)
    cmd = SHELL + [
        "[Console]::OutputEncoding=[Text.Encoding]::UTF8; "
        f"{inner}; exit $LASTEXITCODE"
    ]
    env = dict(os.environ)
    env["PATH"] = str(app.parent / "bin") + os.pathsep + env.get("PATH", "")
    proc = subprocess.run(
        cmd, capture_output=True, env=env, cwd=str(app), timeout=180,
    )
    out = proc.stdout.decode("utf-8", errors="replace")
    out += proc.stderr.decode("utf-8", errors="replace")
    return proc.returncode, out


def git(app: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=str(app), capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=60,
    )
    # strip только переводов строк: у git status --porcelain первая строка
    # начинается с пробела (XY = " M"), общий strip сломал бы разбор.
    return proc.stdout.strip("\r\n")


def write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8", newline="\n")


def changelog(unreleased_body: str, version: str = "1.5.2") -> str:
    return (
        "## [Unreleased]\n"
        f"{unreleased_body}"
        f"\n## [{version}] — 2026-09-23 (PATCH)\n"
        "\n### Исправлено\n"
        "- Предыдущий релиз\n"
    )


def make_fixture(unreleased_body: str, *, dirty: bool = False) -> Path:
    """Фикстурный проект с удалённым «remote», локальным bin/ и gh-shim."""
    tmp = Path(tempfile.mkdtemp(prefix="rel-phase-"))
    app = tmp / "app"
    app.mkdir()
    bin_dir = tmp / "bin"
    bin_dir.mkdir()

    # gh-shim: `auth` -> 0, остальное -> 1 (публикация падает до создания релиза)
    if os.name == "nt":
        shim = bin_dir / "gh.cmd"
        # cmd.exe надёжнее с CRLF, поэтому пишем байты
        shim.write_bytes(
            b"@echo off\r\n"
            b'if "%1"=="auth" exit /b 0\r\n'
            b"echo gh-shim blocked: %*\r\n"
            b"exit /b 1\r\n"
        )
    else:
        shim = bin_dir / "gh"
        write(shim, '#!/bin/sh\nif [ "$1" = "auth" ]; then exit 0; fi\necho "gh-shim blocked: $*" >&2\nexit 1\n')
        shim.chmod(0o755)

    shutil.copy(SCRIPT, app / "release.ps1")
    write(app / "version", "1.5.2")
    write(app / "CHANGELOG.md", changelog(unreleased_body))
    write(app / "store.yaml", "name: Тест\nicon: icon.png\n")
    (app / "icon.png").write_bytes(b"\x89PNG fake")
    dist = app / "dist"
    dist.mkdir()
    (dist / "app-1.5.2.apk").write_bytes(b"apk")

    # remote с github.com в пути — регэксп `github\.com[:/]` должен пройти
    remote = tmp / "github.com" / "zzz-no-such-owner" / "app.git"
    remote.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "--bare", "-q", str(remote)], check=True)

    git(app, "init", "-q")
    git(app, "config", "user.email", "test@example.com")
    git(app, "config", "user.name", "test")
    git(app, "add", "-A")
    git(app, "commit", "-qm", "init")
    git(app, "remote", "add", "origin", str(remote).replace("\\", "/"))

    if dirty:
        write(app / "notes.txt", "незакоммиченная работа\n")
    return app


def cleanup(app: Path) -> None:
    shutil.rmtree(app.parent, ignore_errors=True)


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS
    assert cond, f"{name}: {detail}"
    PASS += 1
    print(f"ok: {name}")


# ---------------------------------------------------------------- фаза подготовки

def test_prepare_refuses_empty_unreleased() -> None:
    app = make_fixture("\n### Исправлено\n")
    try:
        rc, out = run_release(app, "-Prepare")
        check("пустой Unreleased -> отказ", rc == 1 and "Нет накопленных" in out, out)
        check("файлы не тронуты", (app / "version").read_text(encoding="utf-8").strip() == "1.5.2")
        check("тег не создан", git(app, "tag", "--list") == "")
    finally:
        cleanup(app)


def test_prepare_refuses_dirty_tree() -> None:
    app = make_fixture("### Исправлено\n- Фикс\n", dirty=True)
    try:
        rc, out = run_release(app, "-Prepare")
        check("грязное дерево -> отказ", rc == 1 and "не чистое" in out, out)
        check("грязное дерево: версия не изменена",
              (app / "version").read_text(encoding="utf-8").strip() == "1.5.2")
    finally:
        cleanup(app)


def test_prepare_levels() -> None:
    cases = [
        ("только фиксы -> PATCH", "### Исправлено\n- Краш\n", (), "1.5.3"),
        ("фиксы + фича -> MINOR", "### Исправлено\n- Краш\n\n### Добавлено\n- Экспорт\n", (), "1.6.0"),
        ("BREAKING -> MAJOR", "### Изменено\n- **BREAKING:** смена формата\n", (), "2.0.0"),
        ("-Major -> MAJOR", "### Исправлено\n- Краш\n", ("-Major",), "2.0.0"),
        ("без категорий -> MINOR", "- Просто пункт\n", (), "1.6.0"),
        ("Изменено -> MINOR", "### Изменено\n- Поведение\n", (), "1.6.0"),
    ]
    for name, body, flags, expected in cases:
        app = make_fixture(body)
        try:
            rc, out = run_release(app, "-Prepare", *flags)
            version = (app / "version").read_text(encoding="utf-8").strip()
            check(name, rc == 0 and version == expected, f"rc={rc} version={version} {out}")
        finally:
            cleanup(app)


def test_prepare_has_no_side_effects() -> None:
    app = make_fixture("### Добавлено\n- Экспорт\n")
    try:
        head_before = git(app, "rev-parse", "HEAD")
        rc, out = run_release(app, "-Prepare")
        status = git(app, "status", "--porcelain")
        check("подготовка успешна", rc == 0, out)
        check("HEAD не изменился", git(app, "rev-parse", "HEAD") == head_before)
        check("тег не создан", git(app, "tag", "--list") == "")
        check("изменены ровно два файла",
              sorted(line[3:] for line in status.splitlines() if line.strip())
              == ["CHANGELOG.md", "version"], status)
        sections = [ln for ln in (app / "CHANGELOG.md").read_text(encoding="utf-8").splitlines()
                    if ln.startswith("## ")]
        check("свёрнутая секция сразу после Unreleased",
              len(sections) >= 2 and sections[1].startswith("## [1.6.0]"), str(sections[:3]))
        check("[Unreleased] остался первым",
              (app / "CHANGELOG.md").read_text(encoding="utf-8").startswith("## [Unreleased]"))
    finally:
        cleanup(app)


# ---------------------------------------------------------------- фаза публикации

def test_publish_refuses_without_prepare() -> None:
    app = make_fixture("### Добавлено\n- Экспорт\n")
    try:
        rc, out = run_release(app)
        check("непустой Unreleased -> отказ", rc == 1 and "-Prepare" in out, out)
        check("тег не создан", git(app, "tag", "--list") == "")
    finally:
        cleanup(app)


def test_publish_refuses_dirty_files() -> None:
    app = make_fixture("### Добавлено\n- Экспорт\n")
    try:
        rc, _ = run_release(app, "-Prepare")
        assert rc == 0
        write(app / "notes.txt", "работа не закоммичена\n")
        rc, out = run_release(app)
        check("чужие изменения -> отказ", rc == 1 and "Незакоммиченные" in out, out)
        check("бамп не закоммичен", git(app, "log", "-1", "--pretty=%s") == "init")
        check("тег не создан", git(app, "tag", "--list") == "")
    finally:
        cleanup(app)


def test_publish_refuses_version_desync() -> None:
    app = make_fixture("### Добавлено\n- Экспорт\n")
    try:
        rc, _ = run_release(app, "-Prepare")
        assert rc == 0
        (app / "version").write_text("9.9.9", encoding="ascii")
        rc, out = run_release(app)
        check("рассинхрон -> отказ", rc == 1 and "Рассинхрон" in out, out)
        check("тег не создан", git(app, "tag", "--list") == "")
    finally:
        cleanup(app)


def test_publish_commits_bump_then_rolls_back_failed_tag() -> None:
    """Полный прогон до тега: коммит бампа проходит, публикация падает на gh-shim,
    тег откатывается. Реальный релиз не создаётся."""
    app = make_fixture("### Добавлено\n- Экспорт\n")
    try:
        rc, _ = run_release(app, "-Prepare")
        assert rc == 0
        rc, out = run_release(app)
        check("gh-shim оборвал публикацию", rc == 1 and "gh release create" in out, out)
        check("бамп закоммичен",
              git(app, "log", "-1", "--pretty=%s") == "release: 1.6.0 (MINOR)",
              git(app, "log", "-1", "--pretty=%s"))
        head_cl = git(app, "show", "HEAD:CHANGELOG.md")
        check("HEAD содержит секцию новой версии", "## [1.6.0]" in head_cl)
        check("локальный тег откатился", git(app, "tag", "--list") == "")
        remote = app.parent / "github.com" / "zzz-no-such-owner" / "app.git"
        tags = subprocess.run(
            ["git", "--git-dir", str(remote), "tag", "--list"],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=60,
        ).stdout.strip()
        check("тег не ушёл в remote", tags == "", tags)
    finally:
        cleanup(app)


def main() -> int:
    if SHELL is None:
        print("SKIP: PowerShell/pwsh не найден")
        return 0
    if not SCRIPT.exists():
        print(f"SKIP: нет {SCRIPT}")
        return 0

    test_prepare_refuses_empty_unreleased()
    test_prepare_refuses_dirty_tree()
    test_prepare_levels()
    test_prepare_has_no_side_effects()
    test_publish_refuses_without_prepare()
    test_publish_refuses_dirty_files()
    test_publish_refuses_version_desync()
    test_publish_commits_bump_then_rolls_back_failed_tag()
    print(f"ALL PASS ({PASS} проверок)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
