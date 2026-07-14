from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

CONFIG_DIR = Path(__file__).resolve().parent.parent.parent / "config"


def load_yaml(name: str) -> dict[str, Any]:
    path = CONFIG_DIR / name
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_sources() -> dict[str, Any]:
    return load_yaml("sources.yaml")


def load_topics() -> dict[str, Any]:
    return load_yaml("topics.yaml")
