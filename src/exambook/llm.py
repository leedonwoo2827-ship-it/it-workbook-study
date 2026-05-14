from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any, Iterable, Optional

import ollama


TEXT_MODEL = "qwen2.5:7b"
VISION_MODEL = "qwen2.5vl:7b"

DEFAULT_OPTIONS: dict[str, Any] = {
    "num_ctx": 8192,
    "num_gpu": 99,
    "temperature": 0.4,
}


def _client() -> ollama.Client:
    return ollama.Client()


def unload(model: str) -> None:
    try:
        _client().generate(model=model, prompt="", keep_alive=0)
    except Exception:
        pass


def chat_text(
    prompt: str,
    *,
    system: Optional[str] = None,
    model: str = TEXT_MODEL,
    options: Optional[dict[str, Any]] = None,
    keep_alive: int | str = 0,
    json_mode: bool = False,
) -> str:
    messages: list[dict[str, Any]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    opts = {**DEFAULT_OPTIONS, **(options or {})}
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "options": opts,
        "keep_alive": keep_alive,
    }
    if json_mode:
        kwargs["format"] = "json"

    resp = _client().chat(**kwargs)
    return resp["message"]["content"]


def chat_vision(
    prompt: str,
    image_path: str | Path,
    *,
    system: Optional[str] = None,
    model: str = VISION_MODEL,
    options: Optional[dict[str, Any]] = None,
    keep_alive: int | str = 0,
    json_mode: bool = True,
) -> str:
    image_bytes = Path(image_path).read_bytes()
    image_b64 = base64.b64encode(image_bytes).decode("ascii")

    messages: list[dict[str, Any]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt, "images": [image_b64]})

    opts = {**DEFAULT_OPTIONS, **(options or {})}
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "options": opts,
        "keep_alive": keep_alive,
    }
    if json_mode:
        kwargs["format"] = "json"

    resp = _client().chat(**kwargs)
    return resp["message"]["content"]


def parse_json(raw: str) -> Any:
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    return json.loads(text)


def ensure_models(models: Iterable[str]) -> dict[str, bool]:
    raw = _client().list()
    entries = raw.models if hasattr(raw, "models") else raw.get("models", [])

    installed: set[str] = set()
    for m in entries:
        if hasattr(m, "model"):
            installed.add(m.model)
        elif isinstance(m, dict):
            installed.add(m.get("model") or m.get("name", ""))
    return {m: m in installed for m in models}
