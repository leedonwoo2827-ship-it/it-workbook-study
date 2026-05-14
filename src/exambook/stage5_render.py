"""Stage 5 — 문항당 Q####.md(canonical) → Marp .md → PNG.

- 입력: data/questions/Q####.md (사람이 편집한 정본)
- 출력: build/slides_md/Q####.md (Marp 슬라이드), build/slides_png/Q####.*.png
- 이미지: data/questions/images/Q####/*.png 가 있으면 슬라이드에 자동 임베드
- idempotent: 입력 Q####.md mtime <= 출력 png mtime 이면 스킵
"""
from __future__ import annotations

import html
import subprocess
from pathlib import Path

from rich.console import Console

from .config import PROJECT_ROOT, load_config
from .questions_io import images_dir, list_ids, md_path, read_question
from .schemas import Question

console = Console()


def _escape(text: str) -> str:
    return html.escape(text, quote=False)


def _image_block(qid: str, base_dir: Path) -> str:
    img_dir = images_dir(qid)
    if not img_dir.exists():
        return ""
    images = sorted(img_dir.glob("*"))
    if not images:
        return ""
    rels = [f"![]({img.relative_to(base_dir).as_posix()})" for img in images]
    return "\n\n" + "\n\n".join(rels) + "\n"


def _render_marp_md(q: Question, idx: int, total: int, theme: str, build_md_dir: Path) -> str:
    correct = q.answer_index
    choice_items = "\n".join(
        f'  <li class="{"correct" if i == correct else ""}">{_escape(c)}</li>'
        for i, c in enumerate(q.choices)
    )
    images = _image_block(q.id, build_md_dir)

    sql_block = ""
    if q.sql_snippet:
        sql_block = f"\n```sql\n{q.sql_snippet}\n```\n"

    md = f"""---
marp: true
theme: {theme}
paginate: true
header: 'SQLD 모의문제 ({idx}/{total})'
footer: '난이도 {q.difficulty} · {q.syllabus_ref}'
---

<!-- _class: question -->

# 문제 {idx}

<div class="stem">{_escape(q.stem)}</div>
{images}{sql_block}
<ul class="choices">
{choice_items.replace(' class=""', '')}
</ul>

---

<!-- _class: answer -->

# 정답 및 해설

<div class="answer-label">정답: {['①','②','③','④'][correct]} {_escape(q.choices[correct])}</div>

<div class="explanation">{_escape(q.explanation)}</div>
"""
    return md


def _needs_rebuild(qid: str, png_dir: Path, build_md_dir: Path) -> bool:
    src = md_path(qid)
    if not src.exists():
        return False
    out_md = build_md_dir / f"{qid}.md"
    pngs = list(png_dir.glob(f"{qid}.*.png")) + ([png_dir / f"{qid}.png"] if (png_dir / f"{qid}.png").exists() else [])
    if not out_md.exists() or not pngs:
        return True
    src_mtime = src.stat().st_mtime
    out_mtime = min([out_md.stat().st_mtime] + [p.stat().st_mtime for p in pngs])
    return src_mtime > out_mtime


def _theme_name() -> str:
    cfg = load_config()
    theme_path = PROJECT_ROOT / cfg["paths"]["marp_theme"]
    return theme_path.stem


def _resolve_marp_cli() -> list[str]:
    """marp CLI는 npm global 설치 시 .cmd shim 으로 들어가는 경우가 많아
    Python subprocess에서 직접 실행이 어려울 때가 있다. 그럴 때 cmd.exe로 우회한다."""
    from .config import find_tool
    found = find_tool("marp")
    if not found:
        raise RuntimeError("marp CLI not found. npm i -g @marp-team/marp-cli")
    if found.lower().endswith(".cmd") or found.lower().endswith(".bat"):
        return ["cmd", "/c", found]
    return [found]


def write_slides(qids: list[str] | None = None) -> Path:
    cfg = load_config()
    md_dir = PROJECT_ROOT / cfg["paths"]["slides_md"]
    md_dir.mkdir(parents=True, exist_ok=True)

    theme = _theme_name()
    all_ids = list_ids()
    target_ids = qids or all_ids
    total = len(all_ids)

    for qid in target_ids:
        if qid not in all_ids:
            console.print(f"[yellow]skip {qid} — no source MD[/yellow]")
            continue
        idx = all_ids.index(qid) + 1
        q = read_question(qid)
        marp_md = _render_marp_md(q, idx, total, theme, md_dir)
        (md_dir / f"{qid}.md").write_text(marp_md, encoding="utf-8")

    console.print(f"[green]Wrote {len(target_ids)} Marp .md files → {md_dir}[/green]")
    return md_dir


def export_png(qids: list[str] | None = None, *, force: bool = False) -> Path:
    cfg = load_config()
    md_dir = PROJECT_ROOT / cfg["paths"]["slides_md"]
    png_dir = PROJECT_ROOT / cfg["paths"]["slides_png"]
    theme_path = PROJECT_ROOT / cfg["paths"]["marp_theme"]
    scale = cfg["render"]["marp_image_scale"]
    png_dir.mkdir(parents=True, exist_ok=True)

    marp_invoke = _resolve_marp_cli()

    targets = qids or list_ids()
    for qid in targets:
        if not force and not _needs_rebuild(qid, png_dir, md_dir):
            console.print(f"[dim]skip {qid} — png up-to-date[/dim]")
            continue
        marp_md_file = md_dir / f"{qid}.md"
        if not marp_md_file.exists():
            console.print(f"[yellow]missing marp md for {qid}[/yellow]")
            continue
        out_first = png_dir / f"{qid}.png"
        cmd = marp_invoke + [
            "--theme", str(theme_path),
            "--images", "png",
            "--image-scale", str(scale),
            "--allow-local-files",
            str(marp_md_file),
            "-o", str(out_first),
        ]
        subprocess.run(cmd, check=True)
        console.print(f"[green]rendered[/green] {qid}")

    return png_dir


def render_all(qids: list[str] | None = None, *, force: bool = False) -> Path:
    write_slides(qids)
    return export_png(qids, force=force)


if __name__ == "__main__":
    render_all()
