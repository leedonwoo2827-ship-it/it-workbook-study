"""Stage 7 — 슬라이드 PNG + 음성 WAV → MP4 (ffmpeg + NVENC).

각 문항 = 2 슬라이드 페이지(문제, 정답/해설). Marp 의 멀티페이지 export 는
`{qid}.001.png`, `{qid}.002.png` 식으로 떨어진다.
이 두 이미지와 두 wav 를 합쳐서 문항별 mp4 한 개를 만든다.

idempotent: 입력 PNG/WAV mtime <= 출력 mp4 mtime 이면 스킵.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from rich.console import Console

from .config import PROJECT_ROOT, find_tool, load_config
from .questions_io import list_ids
from .stage6_tts import narration_path

console = Console()


def _ffmpeg() -> str:
    found = find_tool("ffmpeg")
    if not found:
        raise RuntimeError("ffmpeg not found. Install: winget install Gyan.FFmpeg")
    return found


def _find_slide_pngs(png_dir: Path, qid: str) -> tuple[Path, Path]:
    p1 = png_dir / f"{qid}.001.png"
    p2 = png_dir / f"{qid}.002.png"
    if p1.exists() and p2.exists():
        return p1, p2
    single = png_dir / f"{qid}.png"
    if single.exists():
        return single, single
    raise FileNotFoundError(f"missing slide PNGs for {qid}")


def _run_ffmpeg(cmd: list[str], context: str, timeout: int = 240) -> None:
    """ffmpeg 호출 — 실패/멈춤 시 RuntimeError.

    timeout 안에 못 끝내면 강제 종료. libx264 의 단일 슬라이드+짧은 오디오 인코딩은
    보통 30~120초 안에 끝나므로 240초면 충분.
    """
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"ffmpeg hang ({context}) — killed after {timeout}s")
    if res.returncode != 0:
        tail = "\n".join(res.stderr.splitlines()[-15:])
        raise RuntimeError(f"ffmpeg failed ({context}): {tail}")


def _segment(image: Path, audio: Path, out: Path, encoder: str, audio_codec: str, audio_bitrate: str, fps: int, pad: float) -> None:
    cmd_base = lambda enc: [
        _ffmpeg(), "-y",
        "-loop", "1", "-i", str(image),
        "-i", str(audio),
        "-af", f"apad=pad_dur={pad}",
        "-c:v", enc,
        "-tune", "stillimage" if enc == "libx264" else "hq",
        "-pix_fmt", "yuv420p",
        "-r", str(fps),
        "-c:a", audio_codec, "-b:a", audio_bitrate,
        "-shortest",
        str(out),
    ]
    try:
        _run_ffmpeg(cmd_base(encoder), f"segment {out.name} via {encoder}")
    except RuntimeError as exc:
        if encoder != "libx264":
            console.print(f"[yellow]{encoder} failed → falling back to libx264[/yellow]")
            _run_ffmpeg(cmd_base("libx264"), f"segment {out.name} via libx264 (fallback)")
        else:
            raise exc


def _concat(segments: list[Path], out: Path) -> None:
    list_file = out.parent / f"_concat_{out.stem}.txt"
    list_file.write_text(
        "\n".join(f"file '{seg.as_posix()}'" for seg in segments),
        encoding="utf-8",
    )
    cmd = [_ffmpeg(), "-y", "-f", "concat", "-safe", "0", "-i", str(list_file), "-c", "copy", str(out)]
    _run_ffmpeg(cmd, f"concat {out.name}")
    list_file.unlink(missing_ok=True)


def _needs_rebuild(qid: str, png_dir: Path, video_dir: Path) -> bool:
    seg_final = video_dir / f"{qid}.mp4"
    if not seg_final.exists():
        return True
    try:
        p1, p2 = _find_slide_pngs(png_dir, qid)
    except FileNotFoundError:
        return False
    stem_wav = narration_path(qid, 1)
    exp_wav = narration_path(qid, 2)
    if not stem_wav.exists() or not exp_wav.exists():
        return False
    inputs = [p1, p2, stem_wav, exp_wav]
    in_mtime = max(p.stat().st_mtime for p in inputs)
    return in_mtime > seg_final.stat().st_mtime


def assemble(qids: list[str] | None = None, *, force: bool = False, concat_final: bool = True) -> Path:
    cfg = load_config()
    png_dir = PROJECT_ROOT / cfg["paths"]["slides_png"]
    video_dir = PROJECT_ROOT / cfg["paths"]["videos"]
    video_dir.mkdir(parents=True, exist_ok=True)

    encoder = cfg["video"]["encoder"]
    audio_codec = cfg["video"]["audio_codec"]
    audio_bitrate = cfg["video"]["audio_bitrate"]
    fps = cfg["video"]["fps"]
    pad = cfg["video"]["pad_silence_seconds"]

    all_ids = list_ids()
    targets = qids or all_ids

    rebuilt: list[str] = []
    for qid in targets:
        if qid not in all_ids:
            console.print(f"[yellow]skip {qid} — no source MD[/yellow]")
            continue
        if not force and not _needs_rebuild(qid, png_dir, video_dir):
            console.print(f"[dim]skip {qid} — mp4 up-to-date[/dim]")
            continue
        try:
            stem_png, exp_png = _find_slide_pngs(png_dir, qid)
        except FileNotFoundError as e:
            console.print(f"[yellow]{e}[/yellow]")
            continue
        stem_wav = narration_path(qid, 1)
        exp_wav = narration_path(qid, 2)
        if not stem_wav.exists() or not exp_wav.exists():
            console.print(f"[yellow]missing audio for {qid}, skipping[/yellow]")
            continue

        seg_stem = video_dir / f"{qid}_stem.mp4"
        seg_exp = video_dir / f"{qid}_exp.mp4"
        seg_final = video_dir / f"{qid}.mp4"

        try:
            _segment(stem_png, stem_wav, seg_stem, encoder, audio_codec, audio_bitrate, fps, pad)
            _segment(exp_png, exp_wav, seg_exp, encoder, audio_codec, audio_bitrate, fps, pad)
            _concat([seg_stem, seg_exp], seg_final)
        except RuntimeError as exc:
            console.print(f"[red]Failed {qid}: {exc}[/red] — skip 후 다음 진행")
            seg_stem.unlink(missing_ok=True)
            seg_exp.unlink(missing_ok=True)
            seg_final.unlink(missing_ok=True)
            continue
        seg_stem.unlink(missing_ok=True)
        seg_exp.unlink(missing_ok=True)
        rebuilt.append(qid)
        console.print(f"[green]assembled[/green] {qid}.mp4")

    if concat_final:
        all_segments = [video_dir / f"{qid}.mp4" for qid in all_ids if (video_dir / f"{qid}.mp4").exists()]
        final = video_dir / "final.mp4"
        if all_segments:
            if force or not final.exists() or any(s.stat().st_mtime > final.stat().st_mtime for s in all_segments):
                _concat(all_segments, final)
                console.print(f"[green]Final video[/green] {final}")
            else:
                console.print(f"[dim]final.mp4 up-to-date[/dim]")
        return final

    return video_dir


def assemble_all() -> Path:
    return assemble()


if __name__ == "__main__":
    assemble_all()
