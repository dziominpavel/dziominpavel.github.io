#!/usr/bin/env python3
"""Генератор статики витрины «Мои приложения» (Python, без фреймворков).

Читает registry.yaml, store.yaml и скриншоты каждого проекта, версию/размер/
дату/ссылки/счётчик скачиваний получает из GitHub API (releases.latest).
Битый проект пропускается с предупреждением и не валит сборку.
"""

from __future__ import annotations

import sys

import yaml

REGISTRY_PATH = "registry.yaml"
OUTPUT_DIR = "_site"


def load_registry(path: str = REGISTRY_PATH) -> dict:
    """Возвращает маппинг «слаг -> описание записи» из registry.yaml."""
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return data.get("projects") or {}


def main() -> int:
    projects = load_registry()
    for slug, entry in projects.items():
        print(f"{slug}: {entry.get('repo')}")
    print(f"projects: {len(projects)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
