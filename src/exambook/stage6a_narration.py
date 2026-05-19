"""Stage 6a — 문항 MD → 강의자 톤 내레이션 대본 사이드카 생성.

흐름:
  data/questions/Q####.md
       ↓ Qwen2.5-7B (prompts/narration.ko.txt)
  data/questions/Q####.scene1.txt   (문제 본문 강사 어투)
  data/questions/Q####.scene2.txt   (정답 해설 강사 어투)

이후 stage6_tts 가 사이드카를 우선 읽어 VoiceWright 에 전달.

idempotent: 사이드카가 MD 보다 새로우면 스킵 (force=True 면 무시).
사용자가 웹 UI 에서 직접 편집한 사이드카는 mtime 이 최신이라 자동 보존됨.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn

from .config import PROJECT_ROOT, load_config, prompt_text
from .llm import TEXT_MODEL, chat_text, parse_json, unload
from .questions_io import list_ids, md_path, read_question
from .schemas import Question
from .stage6_tts import script_override_path

console = Console()


def _needs_narration(qid: str, scene: int) -> bool:
    sc = script_override_path(qid, scene)
    md = md_path(qid)
    if not sc.exists():
        return True
    if not md.exists():
        return False
    return md.stat().st_mtime > sc.stat().st_mtime


def _gen_one(q: Question, scene: int, system_prompt: str) -> Optional[str]:
    # answer_number 는 1-base. LLM 이 0-base 인덱스를 직접 발화하는 사고를
    # 막기 위해 사전 변환해서 던진다 (과거 incident: Q1-27 에서 "정답은 2번"
    # 으로 잘못 발화 — 실제 정답은 ③번).
    payload = {
        "scene": scene,
        "id": q.id,
        "stem": q.stem,
        "choices": q.choices,
        "answer_number": q.answer_index + 1,
        "answer_text": q.choices[q.answer_index],
        "explanation": q.explanation,
        "sql_snippet": q.sql_snippet,
        "syllabus_ref": q.syllabus_ref,
    }
    raw = chat_text(
        prompt=json.dumps(payload, ensure_ascii=False, indent=2),
        system=system_prompt,
        options={"temperature": 0.55, "num_ctx": 8192},
        json_mode=True,
        keep_alive="5m",
    )
    try:
        data = parse_json(raw)
    except Exception as exc:
        console.print(f"[red]narration JSON parse failed {q.id} scene{scene}: {exc}[/red]")
        return None
    text = (data.get("narration") or "").strip()
    if not text:
        console.print(f"[yellow]empty narration for {q.id} scene{scene}[/yellow]")
        return None
    return text


def narrate(qids: list[str] | None = None, *, force: bool = False) -> Path:
    cfg = load_config()
    questions_dir = (PROJECT_ROOT / cfg["paths"]["questions"]).parent
    system_prompt = prompt_text("narration.ko.txt")

    targets = qids or list_ids()
    if not targets:
        console.print("[yellow]no questions found[/yellow]")
        return questions_dir

    work_items: list[tuple[str, int]] = []
    for qid in targets:
        for scene in (1, 2):
            if force or _needs_narration(qid, scene):
                work_items.append((qid, scene))

    if not work_items:
        console.print("[green]all narrations up-to-date[/green]")
        return questions_dir

    created = 0
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task(f"Narration ({len(work_items)} clips)", total=len(work_items))
        for qid, scene in work_items:
            try:
                q = read_question(qid)
            except Exception as exc:
                console.print(f"[yellow]skip {qid}: {exc}[/yellow]")
                progress.advance(task)
                continue
            text = _gen_one(q, scene, system_prompt)
            if text:
                sc_path = script_override_path(qid, scene)
                sc_path.write_text(text, encoding="utf-8")
                created += 1
                console.print(f"[green]narrated[/green] {qid} scene{scene} ({len(text)} chars)")
            progress.advance(task)

    console.print(f"[green]Wrote {created}/{len(work_items)} narration sidecars → {questions_dir}[/green]")
    unload(TEXT_MODEL)
    return questions_dir


def narrate_all() -> Path:
    return narrate()


if __name__ == "__main__":
    narrate_all()
