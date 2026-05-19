"""Stage 6 — VoiceWright (Supertonic) 로 문항별 음성 합성.

사용자 워크플로 컨벤션 (scriptforge → voicewright → sceneweaver-capcut)에 맞춤.

매핑 규칙:
  Q0001(문항) → chapter "01"
    scene 1 = stem (문제 본문 + 보기)
    scene 2 = exp  (정답 + 해설)

VoiceWright 출력:
  <output_root>/ch{NN}/audio/ch{NN}_{scene:02d}_narration.wav
  <output_root>/ch{NN}/subtitles/ch{NN}_{scene:02d}_narration.srt + ch{NN}.srt

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


def _qid_to_chapter(qid: str) -> str:
    """문항 ID → VoiceWright chapter 번호('01'..'999').

    매핑 우선순위:
      - 회차 ID `Q{round}-{idx}` (예: Q1-01, Q4-50) → (round-1)*50 + idx
      - 순번 ID `Q0001` → 그 숫자 그대로
      - 해시 ID `Q005e89bf5f` (legacy) → 현재 list_ids() 내 순번(1-based)
    VoiceWright normalize_chapter_id 가 1-999 zero-padded 만 받기 때문에
    어떤 형태든 결정론적으로 정수 1-999 로 매핑한다.
    """
    # Q{round}-{round_idx}
    m = re.match(r"^Q(\d+)-(\d+)$", qid)
    if m:
        round_n = int(m.group(1))
        round_idx = int(m.group(2))
        chapter_num = (round_n - 1) * 50 + round_idx
        if 1 <= chapter_num <= 999:
            return f"{chapter_num:02d}"
        raise ValueError(f"chapter out of range (1-999): {qid} → {chapter_num}")

    # Q####
    m = re.match(r"^Q(\d+)$", qid)
    if m:
        n = int(m.group(1))
        if 1 <= n <= 999:
            return f"{n:02d}"

    # legacy hash ID
    all_ids = list_ids()
    if qid in all_ids:
        idx = all_ids.index(qid) + 1
        if 1 <= idx <= 999:
            return f"{idx:02d}"
        raise ValueError(f"chapter out of range (1-999): {qid} → idx {idx}")

    raise ValueError(f"invalid qid for chapter mapping: {qid}")


def _apply_pronunciation(text: str, pron: dict[str, str]) -> str:
    if not pron:
        return text
    out = text
    for kw, sub in sorted(pron.items(), key=lambda kv: -len(str(kv[0]))):
        if kw is None or sub is None:
            continue
        out = re.sub(rf"\b{re.escape(str(kw))}\b", str(sub), out, flags=re.IGNORECASE)
    return out


def build_scripts(q: Question, idx: int, voice_map: dict) -> tuple[str, str]:
    """문항 1개를 stem/exp 두 대본 문자열로 변환."""
    pron = voice_map.get("pronunciation", {}) or {}
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


# Backward compat alias
_build_scripts = build_scripts


def _audio_root() -> Path:
    cfg = load_config()
    return PROJECT_ROOT / cfg["paths"]["audio"]


def narration_path(qid: str, scene: int) -> Path:
    """VoiceWright가 떨어뜨릴 wav 경로 — Q####/scene → 절대 경로."""
    chapter = _qid_to_chapter(qid)
    return _audio_root() / f"ch{chapter}" / "audio" / f"ch{chapter}_{scene:02d}_narration.wav"


def script_override_path(qid: str, scene: int) -> Path:
    """사용자가 직접 편집한 대본이 있으면 여기에 저장된다. 있으면 자동생성 무시."""
    return md_path(qid).with_suffix(f".scene{scene}.txt")


def load_script_override(qid: str, scene: int) -> str | None:
    p = script_override_path(qid, scene)
    if p.exists():
        return p.read_text(encoding="utf-8")
    return None


def srt_path(qid: str, scene: int) -> Path:
    chapter = _qid_to_chapter(qid)
    return _audio_root() / f"ch{chapter}" / "subtitles" / f"ch{chapter}_{scene:02d}_narration.srt"


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


def _needs_rebuild(qid: str) -> bool:
    src = md_path(qid)
    if not src.exists():
        return False
    stem_wav = narration_path(qid, 1)
    exp_wav = narration_path(qid, 2)
    if not stem_wav.exists() or not exp_wav.exists():
        return True
    src_mtime = src.stat().st_mtime
    out_mtime = min(stem_wav.stat().st_mtime, exp_wav.stat().st_mtime)
    return src_mtime > out_mtime


def _synthesize_one(qid: str, voice_map: dict, force: bool) -> Path | None:
    """문항 1개의 stem + exp 두 wav를 만든다. 만든 chapter 디렉토리 반환."""
    if not force and not _needs_rebuild(qid):
        console.print(f"[dim]skip {qid} — audio up-to-date[/dim]")
        return None

    all_ids = list_ids()
    if qid not in all_ids:
        console.print(f"[yellow]skip {qid} — no source MD[/yellow]")
        return None
    idx = all_ids.index(qid) + 1
    q = read_question(qid)

    chapter = _qid_to_chapter(qid)
    auto_stem, auto_exp = build_scripts(q, idx, voice_map)

    ov1 = load_script_override(qid, 1)
    ov2 = load_script_override(qid, 2)
    pron = voice_map.get("pronunciation", {}) or {}
    stem_script = _apply_pronunciation(ov1, pron) if ov1 is not None else auto_stem
    exp_script = _apply_pronunciation(ov2, pron) if ov2 is not None else auto_exp
    if ov1 is not None or ov2 is not None:
        used_scenes = ",".join(s for s, ov in [("1", ov1), ("2", ov2)] if ov is not None)
        console.print(f"[dim]using narration sidecar for {qid} (scene {used_scenes})[/dim]")

    roles = voice_map.get("roles", {})
    stem_voice = (roles.get("stem", {}) or {}).get("voice", "F2")
    exp_voice = (roles.get("explanation", {}) or {}).get("voice", "M3")

    script_payload = {
        "chapter": chapter,
        "scenes": [
            {
                "scene": 1,
                "narration_text": stem_script,
                "voice_style": stem_voice,
            },
            {
                "scene": 2,
                "narration_text": exp_script,
                "voice_style": exp_voice,
            },
        ],
    }

    audio_root = _audio_root()
    audio_root.mkdir(parents=True, exist_ok=True)
    script_file = audio_root / f"ch{chapter}_script.json"
    script_file.write_text(json.dumps(script_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    cmd = [
        _voicewright_executable(),
        "batch",
        str(script_file),
        "--chapter", chapter,
        "--output-root", str(audio_root),
    ]
    console.print(f"[cyan]VoiceWright[/cyan] {qid} → ch{chapter} (scenes 1,2)")
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"voicewright failed for {qid}: exit {exc.returncode}") from exc
    return audio_root / f"ch{chapter}"


def synthesize(qids: list[str] | None = None, *, force: bool = False) -> Path:
    voice_map = load_voice_map()
    targets = qids or list_ids()
    for qid in targets:
        _synthesize_one(qid, voice_map, force)
    console.print(f"[green]Audio under[/green] {_audio_root()}")
    return _audio_root()


def synthesize_all() -> Path:
    return synthesize()


if __name__ == "__main__":
    synthesize_all()
