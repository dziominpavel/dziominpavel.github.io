#!/usr/bin/env python3
"""Тесты проверки верхнего блока секции [Unreleased] в scripts/check-version.py.

Запуск: py tests/test_check_version.py

Песочница самодостаточна: копия скрипта кладётся во временный проект
(CHANGELOG.md + файл версии), скрипт гоняется как в реальной самопроверке —
по нему проверяются настоящие коды возврата и вывод, без pytest.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "check-version.py"

PASS = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS
    assert cond, f"{name}: {detail}"
    PASS += 1
    print(f"ok: {name}")


def make_project(changelog: str, version: str | None = "1.5.2") -> Path:
    """Временный проект: копия скрипта, CHANGELOG.md, файл версии."""
    tmp = Path(tempfile.mkdtemp(prefix="check-version-"))
    (tmp / "scripts").mkdir()
    shutil.copy(SCRIPT, tmp / "scripts" / "check-version.py")
    (tmp / "CHANGELOG.md").write_text(changelog, encoding="utf-8")
    if version is not None:
        (tmp / "version").write_text(version + "\n", encoding="utf-8")
    return tmp


def run_check(project: Path) -> tuple[int, str]:
    """Запуск самопроверки скрипта. Возвращает (код, вывод UTF-8)."""
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.run(
        [sys.executable, str(project / "scripts" / "check-version.py")],
        capture_output=True,
        cwd=str(project),
        env=env,
        timeout=60,
    )
    out = proc.stdout.decode("utf-8", "replace")
    out += proc.stderr.decode("utf-8", "replace")
    return proc.returncode, out


def cleanup(project: Path) -> None:
    shutil.rmtree(project, ignore_errors=True)


def expect_fail(name: str, changelog: str, needle: str, version: str | None = "1.5.2") -> None:
    project = make_project(changelog, version)
    try:
        rc, out = run_check(project)
        check(f"{name}: код 1", rc == 1, out)
        check(f"{name}: сообщение", needle in out, out)
    finally:
        cleanup(project)


def expect_ok(name: str, changelog: str, version: str | None = "1.5.2") -> None:
    project = make_project(changelog, version)
    try:
        rc, out = run_check(project)
        check(f"{name}: код 0", rc == 0, out)
    finally:
        cleanup(project)


# --------------------------------------------------- негативные фикстуры блока

def test_prose_block() -> None:
    expect_fail(
        "проза вместо блока",
        "# Changelog\n\n## [Unreleased]\n\nЭто связная проза, а не формат блока.\n"
        "\n### Исправлено\n\n- что-то исправлено\n",
        "не жирная метка и не буллет",
    )


def test_wrapped_bullet() -> None:
    expect_fail(
        "обёрнутый буллет",
        "# Changelog\n\n## [Unreleased]\n\n- первый буллет, который\n"
        "  автор завернул на вторую строку\n\n### Исправлено\n\n- что-то исправлено\n",
        "не жирная метка и не буллет",
    )


def test_long_line() -> None:
    expect_fail(
        "строка длиннее 140",
        "# Changelog\n\n## [Unreleased]\n\n- " + "x" * 150 + "\n",
        "строка длиннее 140",
    )


def test_backtick() -> None:
    expect_fail(
        "символ backtick",
        "# Changelog\n\n## [Unreleased]\n\n- правка с упоминанием `tools/static`\n",
        "запрещён внутри блока",
    )


def test_labels_without_bullets() -> None:
    expect_fail(
        "только метки без буллетов",
        "# Changelog\n\n## [Unreleased]\n\n**Добавлено**\n\n**Исправлено**\n"
        "\n### Добавлено\n\n- что-то добавлено\n",
        "нет ни одного буллета",
    )


def test_section_starts_with_categories() -> None:
    expect_fail(
        "секция с пунктами начинается с ###",
        "# Changelog\n\n## [Unreleased]\n\n### Исправлено\n\n- что-то исправлено\n",
        "нет верхнего блока",
    )


# --------------------------------------------------- позитивные фикстуры блока

def test_valid_block_labels_and_bullets() -> None:
    expect_ok(
        "валидный блок: метки и буллеты",
        "# Changelog\n\n## [Unreleased]\n\n**Добавлено**\n\n- что-то добавлено\n\n"
        "**Исправлено**\n\n- что-то исправлено\n\n### Исправлено\n\n- деталь\n",
    )


def test_bullets_only() -> None:
    expect_ok(
        "блок только из буллетов",
        "# Changelog\n\n## [Unreleased]\n\n- первая доработка\n- вторая доработка\n",
    )


def test_empty_unreleased() -> None:
    project = make_project(
        "# Changelog\n\n## [Unreleased]\n\n## [1.0.0]\n\n- старое изменение\n",
        "1.0.0",
    )
    try:
        rc, out = run_check(project)
        check("пустая секция: код 0", rc == 0, out)
        check("пустая секция: подсказка NO_BUMP", "NO_BUMP" in out, out)
    finally:
        cleanup(project)


def test_historical_sections_untouched() -> None:
    expect_ok(
        "исторические секции не проверяются",
        "# Changelog\n\n## [Unreleased]\n\n- валидный буллет\n\n## [1.0.0]\n\n"
        "Прозаическая историческая секция без блока в формате контракта.\n",
        "1.0.0",
    )


def test_static_track() -> None:
    # Без файла версии самопроверка трактует проект как статический —
    # проверка блока обязана работать и для него.
    expect_ok(
        "статический трек: блок валиден",
        "# Changelog\n\n## [Unreleased]\n\n**Изменено**\n\n- что-то изменено\n",
        version=None,
    )


# --------------------------------------------------- регресс существующего поведения

def test_version_desync() -> None:
    expect_fail(
        "рассинхрон version и секции",
        "# Changelog\n\n## [Unreleased]\n\n- валидный буллет\n\n## [1.6.0]\n\n- релиз\n",
        "рассинхрон",
        version="1.7.0",
    )


def test_first_section_not_unreleased() -> None:
    expect_fail(
        "первая секция не [Unreleased]",
        "# Changelog\n\n## [1.0.0]\n\n- старое изменение\n",
        "первая секция должна быть",
    )


def main() -> int:
    if not SCRIPT.exists():
        print(f"SKIP: нет {SCRIPT}")
        return 0

    test_prose_block()
    test_wrapped_bullet()
    test_long_line()
    test_backtick()
    test_labels_without_bullets()
    test_section_starts_with_categories()
    test_valid_block_labels_and_bullets()
    test_bullets_only()
    test_empty_unreleased()
    test_historical_sections_untouched()
    test_static_track()
    test_version_desync()
    test_first_section_not_unreleased()
    print(f"ALL PASS ({PASS} проверок)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
