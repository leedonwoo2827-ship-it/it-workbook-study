from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = PROJECT_ROOT / "config" / "pipeline.yaml"
VOICE_MAP_PATH = PROJECT_ROOT / "config" / "voice_map.yaml"


@lru_cache(maxsize=1)
def load_config() -> dict[str, Any]:
    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


@lru_cache(maxsize=1)
def load_voice_map() -> dict[str, Any]:
    with VOICE_MAP_PATH.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def project_path(relative_key: str) -> Path:
    cfg = load_config()
    return PROJECT_ROOT / cfg["paths"][relative_key]


def prompt_text(name: str) -> str:
    path = PROJECT_ROOT / "prompts" / name
    return path.read_text(encoding="utf-8")


def find_tool(name: str) -> str | None:
    """Locate an external tool. Order:
       1. config.tools.<name> (absolute path)
       2. PATH (shutil.which)
       3. None
    """
    import shutil

    cfg = load_config()
    configured = cfg.get("tools", {}).get(name)
    if configured:
        p = Path(configured)
        if p.exists():
            return str(p)

    return shutil.which(name) or shutil.which(f"{name}.exe") or shutil.which(f"{name}.cmd")
