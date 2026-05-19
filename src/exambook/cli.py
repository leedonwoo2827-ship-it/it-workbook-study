"""SQLD Exambook CLI.

사용 예:
  python -m exambook.cli doctor
  python -m exambook.cli ingest
  python -m exambook.cli ocr
  python -m exambook.cli topics
  python -m exambook.cli generate --total 50
  python -m exambook.cli check
  python -m exambook.cli render
  python -m exambook.cli tts
  python -m exambook.cli video
  python -m exambook.cli run-all --total 50
"""
from __future__ import annotations

import subprocess
import sys
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from .config import PROJECT_ROOT, find_tool, load_config
from .llm import TEXT_MODEL, VISION_MODEL, ensure_models

app = typer.Typer(add_completion=False, no_args_is_help=True)
console = Console()


@app.command()
def doctor() -> None:
    """필수 도구·모델 설치 상태 점검."""
    cfg = load_config()
    table = Table(title="exambook doctor")
    table.add_column("component")
    table.add_column("status")
    table.add_column("hint")

    for cmd in ["pdftoppm", "ffmpeg", "marp", "ollama"]:
        path = find_tool(cmd)
        table.add_row(cmd, "OK" if path else "MISSING", path or "")

    vw_path = PROJECT_ROOT / cfg["paths"].get("voicewright_cli", "")
    if vw_path.exists():
        table.add_row("voicewright", "OK", str(vw_path))
    else:
        global_vw = find_tool("voicewright")
        table.add_row("voicewright", "OK" if global_vw else "MISSING", global_vw or "configure paths.voicewright_cli")

    try:
        model_status = ensure_models([TEXT_MODEL, VISION_MODEL])
        for m, ok in model_status.items():
            table.add_row(f"ollama:{m}", "OK" if ok else "MISSING", "" if ok else f"ollama pull {m}")
    except Exception as e:
        table.add_row("ollama-list", "ERROR", str(e))

    console.print(table)


@app.command()
def ingest() -> None:
    """_assets PDF → data/raw_pages PNG."""
    from . import stage1_ingest
    stage1_ingest.ingest_all()


@app.command()
def ocr() -> None:
    """raw_pages → data/ocr/*.json via Qwen2.5-VL."""
    from . import stage2_ocr
    stage2_ocr.ocr_all()


@app.command()
def topics() -> None:
    """ocr → data/analysis/topic_map.json (추상 통계)."""
    from . import stage3_topic
    stage3_topic.build_topic_map()


@app.command()
def generate(total: int = 50, seed: int = 20260514, rounds: int = 1) -> None:
    """KDATA syllabus + topic_map → data/questions/Q{round}-{idx}.md (Track B).

    예:
      exambook generate --total 50                  # 1회분 50문항 → Q1-01..Q1-50
      exambook generate --total 200 --rounds 4      # 4회분 50문항씩 → Q1-01..Q4-50
    """
    from . import stage4b_generate
    stage4b_generate.generate_bank(total=total, seed=seed, rounds=rounds)


@app.command()
def variants(max_chunks: Optional[int] = None, seed: int = 20260514) -> None:
    """⚠ Track A — 개인학습용 변형. data/private/variants.json."""
    from . import stage4a_variants
    stage4a_variants.build_variants(max_chunks=max_chunks, seed=seed)


@app.command()
def check() -> None:
    """배포 전 의무 게이트 — derivative similarity check."""
    cmd = [sys.executable, str(PROJECT_ROOT / "tests" / "derivative_check.py")]
    raise SystemExit(subprocess.call(cmd))


@app.command()
def narrate(force: bool = False) -> None:
    """문항 MD → 강의자 톤 대본 사이드카 생성 (Q####.scene{1,2}.txt).

    이후 tts/video 단계가 사이드카를 자동으로 사용해 구어체로 합성.
    --force 면 mtime 무시하고 모든 사이드카 재생성.
    """
    from . import stage6a_narration
    stage6a_narration.narrate(force=force)


@app.command()
def render(force: bool = False) -> None:
    """data/questions/Q####.md → Marp .md → PNG (idempotent)."""
    from . import stage5_render
    stage5_render.render_all(force=force)


@app.command()
def tts(force: bool = False) -> None:
    """data/questions/Q####.md → audio/*.wav via VoiceWright (idempotent)."""
    from . import stage6_tts
    stage6_tts.synthesize(force=force)


@app.command()
def video(force: bool = False) -> None:
    """슬라이드 PNG + 음성 WAV → MP4 (NVENC, idempotent)."""
    from . import stage7_video
    stage7_video.assemble(force=force)


@app.command()
def rebuild(
    qids: Optional[list[str]] = typer.Argument(None),
    force: bool = False,
    skip_video: bool = False,
) -> None:
    """편집된 Q####.md → slides → audio → mp4 까지 부분 재빌드.

    예:
      exambook rebuild Q0001 Q0042      # 두 문항만
      exambook rebuild                  # 전체 idempotent 갱신 (변경된 것만)
      exambook rebuild --force          # 전체 강제 재빌드
    """
    from . import stage5_render, stage6_tts, stage7_video

    ids = qids if qids else None
    stage5_render.render_all(qids=ids, force=force)
    stage6_tts.synthesize(qids=ids, force=force)
    if not skip_video:
        stage7_video.assemble(qids=ids, force=force)


@app.command()
def serve(
    host: str = "127.0.0.1",
    port: int = 8000,
    reload: bool = False,
) -> None:
    """로컬 웹 UI 실행 (브라우저에서 http://localhost:{port} 접속). LAN 공유: --host 0.0.0.0"""
    from .web.app import run
    console.print(f"[bold]Exambook Studio[/bold] → http://{host}:{port}")
    run(host=host, port=port, reload=reload)


@app.command("list")
def list_questions() -> None:
    """data/questions/ 의 Q####.md 목록 출력."""
    from .questions_io import list_ids, read_question
    ids = list_ids()
    table = Table(title=f"questions ({len(ids)})")
    table.add_column("id")
    table.add_column("topic")
    table.add_column("난이도")
    table.add_column("정답")
    for qid in ids:
        try:
            q = read_question(qid)
            table.add_row(qid, q.topic_id, q.difficulty, str(q.answer_index + 1))
        except Exception as e:
            table.add_row(qid, "ERROR", str(e), "")
    console.print(table)


@app.command("run-all")
def run_all(
    total: int = 50,
    seed: int = 20260514,
    rounds: int = 1,
    narration: bool = True,
    skip_check: bool = False,
) -> None:
    """1~7 단계를 순차 실행 (Track B만).

    --rounds N 으로 회차 분할 (예: --total 200 --rounds 4).
    --narration 기본 True. 생성된 MD 를 강사 어투 대본 사이드카로 변환 후 TTS 진행.
    --no-narration 주면 시험지 그대로 읽는 옛 자동 조립 모드.
    """
    from . import (
        stage1_ingest,
        stage2_ocr,
        stage3_topic,
        stage4b_generate,
        stage5_render,
        stage6_tts,
        stage6a_narration,
        stage7_video,
    )

    stage1_ingest.ingest_all()
    stage2_ocr.ocr_all()
    stage3_topic.build_topic_map()
    stage4b_generate.generate_bank(total=total, seed=seed, rounds=rounds)

    if not skip_check:
        check_cmd = [sys.executable, str(PROJECT_ROOT / "tests" / "derivative_check.py")]
        rc = subprocess.call(check_cmd)
        if rc != 0:
            console.print("[red]derivative check failed — aborting before slide/TTS/video[/red]")
            raise SystemExit(rc)

    if narration:
        stage6a_narration.narrate()

    stage5_render.render_all()
    stage6_tts.synthesize_all()
    stage7_video.assemble_all()
    console.print("[bold green]run-all complete[/bold green]")


if __name__ == "__main__":
    app()
