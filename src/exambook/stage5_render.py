"""Stage 5 — 문항당 Q####.md(canonical) → Marp .md → PNG.

- 입력: data/questions/Q####.md (사람이 편집한 정본)
- 출력: build/slides_md/Q####.md (Marp 슬라이드), build/slides_png/Q####.*.png
- 이미지: data/questions/images/Q####/*.png 가 있으면 슬라이드에 자동 임베드
- idempotent: 입력 Q####.md mtime <= 출력 png mtime 이면 스킵
"""
from __future__ import annotations

import html
import re
import subprocess
from pathlib import Path

from rich.console import Console

from .config import PROJECT_ROOT, load_config
from .questions_io import images_dir, list_ids, md_path, read_question
from .schemas import Question

console = Console()


def _escape(text: str) -> str:
    return html.escape(text, quote=False)


_FENCE_RE = re.compile(r"```[a-zA-Z]*\n.*?\n```", re.DOTALL)

_NEGATIVE_MARKERS = (
    "옳지 않은", "옳지않은", "옳지 않는", "옳지않는",
    "잘못된", "틀린", "아닌 것", "아닌것",
    "올바르지 않", "맞지 않", "거리가 먼", "해당하지 않",
)

_BULLET_SPLIT_RE = re.compile(r"\n[-*]\s")

_SENTENCE_END_RE = re.compile(r"[.!?][\s\n]+")


def _is_negative_question(stem: str) -> bool:
    return any(m in stem for m in _NEGATIVE_MARKERS)


def _strip_question_sentence(text: str) -> str:
    """발문(마지막 의문문 문장) 제거. 단문 의문문이면 빈 문자열 반환.

    Korean stems often combine 지문(supporting text) + 발문(the interrogative).
    On slide 2 (정답·해설) 우리는 발문만 떼어내 지문을 남긴다.
    """
    text = text.strip()
    if not (text.endswith("?") or text.endswith("？")):
        return text
    matches = list(_SENTENCE_END_RE.finditer(text))
    if not matches:
        return ""
    return text[: matches[-1].end()].rstrip()


def _brief_explanation(text: str) -> str:
    """첫 단락 + (단락이 짧으면) 첫 bullet, 280자 캡."""
    text = text.strip()
    parts = _BULLET_SPLIT_RE.split(text, maxsplit=1)
    intro = parts[0].strip()
    if len(intro) < 80 and len(parts) > 1:
        first_bullet = parts[1].split("\n", 1)[0].strip()
        intro = f"{intro}\n• {first_bullet}"
    if len(intro) > 280:
        intro = intro[:280].rstrip() + "…"
    return intro


def _split_stem_code(stem: str) -> tuple[str, list[str]]:
    """stem 안의 ```...``` 펜스 코드블록을 추출해서 (stem 본문, [코드블록…]) 반환.

    LLM이 종종 stem 안에 SQL 코드를 박는데, `<div class="stem">…</div>` 로 감싸면
    펜스 닫는 백틱이 `</div>` 와 한 줄에 붙어 코드블록이 안 닫힘 → 뒤 페이지 전체가
    코드 안 텍스트로 흡수되어 슬라이드 분리(`---`)가 무효화됨.
    """
    blocks = _FENCE_RE.findall(stem)
    body = _FENCE_RE.sub("", stem).strip()
    return body, blocks


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

    stem_body, embedded_codes = _split_stem_code(q.stem)

    def _inner(block: str) -> str:
        # ```lang\n…\n``` 에서 본문만 추출
        lines = block.strip().splitlines()
        if len(lines) >= 2 and lines[0].startswith("```") and lines[-1].startswith("```"):
            return "\n".join(lines[1:-1]).strip()
        return block.strip()

    code_blocks: list[str] = []
    seen: set[str] = set()
    if q.sql_snippet:
        snippet = q.sql_snippet.strip()
        code_blocks.append(f"```sql\n{snippet}\n```")
        seen.add(snippet)
    for emb in embedded_codes:
        body = _inner(emb)
        if body in seen:
            continue
        seen.add(body)
        code_blocks.append(emb)
    sql_block = ("\n" + "\n\n".join(code_blocks) + "\n") if code_blocks else ""

    negative = _is_negative_question(q.stem)
    def _stmt_mark_class(i: int) -> str:
        is_true_statement = (i != correct) if negative else (i == correct)
        return "correct-mark" if is_true_statement else "wrong-mark"

    answer_choice_items = "\n".join(
        f'  <li class="{_stmt_mark_class(i)}">{_escape(c)}</li>'
        for i, c in enumerate(q.choices)
    )
    answer_stem_body = _strip_question_sentence(stem_body)
    answer_stem_html = (
        f'<div class="stem">{_escape(answer_stem_body)}</div>\n'
        if answer_stem_body else ""
    )
    brief_html = _escape(_brief_explanation(q.explanation)).replace("\n", "<br>")

    md = f"""---
marp: true
theme: {theme}
paginate: true
header: 'SQLD 모의문제 ({idx}/{total})'
footer: '난이도 {q.difficulty} · {q.syllabus_ref}'
---

<!-- _class: question -->

# 문제 {idx}

<div class="stem">{_escape(stem_body)}</div>
{images}{sql_block}
<ul class="choices">
{choice_items.replace(' class=""', '')}
</ul>

---

<!-- _class: answer -->

# 정답 및 해설

{answer_stem_html}{sql_block}
<ul class="choices">
{answer_choice_items}
</ul>

<div class="explanation">{brief_html}</div>
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
