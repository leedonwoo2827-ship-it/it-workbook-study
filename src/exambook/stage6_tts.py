"""Stage 6 — VoiceWright (Supertonic) 로 문항별 음성 합성.

각 문항당 두 wav:
  build/audio/{qid}_stem.wav      (문제 본문 + 보기 ①②③④)
  build/audio/{qid}_exp.wav       (정답 + 해설)

idempotent: 입력 MD mtime <= 출력 wav mtime 이면 스킵.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from rich.console import Console

from .config import PROJECT_ROOT, find_tool, load_config, load_voice_map
from .questions_io import list_ids, md_path, read_question
from .schemas import Question

console = Console()


def _apply_pronunciation(text: str, pron: dict[str, str]) -> str:
    out = text
    for kw, sub in sorted(pron.items(), key=lambda kv: -len(kv[0])):
        out = re.sub(rf"\b{re.escape(kw)}\b", sub, out, flags=re.IGNORECASE)
    return out


def _build_scripts(q: Question, idx: int, total: int, voice_map: dict) -> tuple[str, str]:
    pron = voice_map.get("pronunciation", {})
    circled = ["①", "②", "③", "④"]

    stem_lines = [f"{idx}번 문제."]
    stem_lines.append(_apply_pronunciation(q.stem, pron))
    if q.sql_snippet:
        stem_lines.append("다음 SQL 문을 참고하세요.")
        stem_lines.append(_apply_pronunciation(q.sql_snippet, pron))
    stem_lines.append("보기.")
    for i, c in enumerate(q.choices):
        stem_lines.append(f"{circled[i]}번. {_apply_pronunciation(c, pron)}")

    exp_lines = [
        f"정답은 {circled[q.answer_index]}번 입니다.",
        "해설을 설명해 드리겠습니다.",
        _apply_pronunciation(q.explanation, pron),
    ]
    return "\n".join(stem_lines), "\n".join(exp_lines)


def _voicewright_executable() -> str:
    cfg = load_config()
    configured = cfg["paths"].get("voicewright_cli")
    if configured:
        path = PROJECT_ROOT / configured
        if path.exists():
            return str(path)
    found = find_tool("voicewright")
    if not found:
        raise RuntimeError(
            "voicewright CLI not found. Install from "
            "https://github.com/leedonwoo2827-ship-it/voicewright"
        )
    return found


def _needs_rebuild(qid: str, audio_dir: Path) -> bool:
    src = md_path(qid)
    if not src.exists():
        return False
    stem_wav = audio_dir / f"{qid}_stem.wav"
    exp_wav = audio_dir / f"{qid}_exp.wav"
    if not stem_wav.exists() or not exp_wav.exists():
        return True
    src_mtime = src.stat().st_mtime
    out_mtime = min(stem_wav.stat().st_mtime, exp_wav.stat().st_mtime)
    return src_mtime > out_mtime


def synthesize(qids: list[str] | None = None, *, force: bool = False) -> Path:
    cfg = load_config()
    voice_map = load_voice_map()
    roles = voice_map["roles"]
    audio_dir = PROJECT_ROOT / cfg["paths"]["audio"]
    audio_dir.mkdir(parents=True, exist_ok=True)

    all_ids = list_ids()
    targets = qids or all_ids
    total = len(all_ids)

    batch_items: list[dict] = []
    for qid in targets:
        if qid not in all_ids:
            console.print(f"[yellow]skip {qid} — no source MD[/yellow]")
            continue
        if not force and not _needs_rebuild(qid, audio_dir):
            console.print(f"[dim]skip {qid} — audio up-to-date[/dim]")
            continue
        idx = all_ids.index(qid) + 1
        q = read_question(qid)
        stem_script, exp_script = _build_scripts(q, idx, total, voice_map)
        stem_out = audio_dir / f"{q.id}_stem.wav"
        exp_out = audio_dir / f"{q.id}_exp.wav"

        batch_items.append({
            "id": f"{q.id}_stem",
            "text": stem_script,
            "voice": roles["stem"]["voice"],
            "speed": roles["stem"].get("speed", 1.0),
            "output": str(stem_out),
        })
        batch_items.append({
            "id": f"{q.id}_exp",
            "text": exp_script,
            "voice": roles["explanation"]["voice"],
            "speed": roles["explanation"].get("speed", 1.0),
            "output": str(exp_out),
        })

    if not batch_items:
        console.print("[green]all audio up-to-date[/green]")
        return audio_dir

    batch_json = audio_dir / "_batch.json"
    batch_json.write_text(json.dumps({"items": batch_items}, ensure_ascii=False, indent=2), encoding="utf-8")
    console.print(f"[cyan]VoiceWright batch[/cyan] {len(batch_items)} clips")
    subprocess.run([_voicewright_executable(), "batch", str(batch_json)], check=True)
    console.print(f"[green]Audio written under[/green] {audio_dir}")
    return audio_dir


def synthesize_all() -> Path:
    return synthesize()


if __name__ == "__main__":
    synthesize_all()
