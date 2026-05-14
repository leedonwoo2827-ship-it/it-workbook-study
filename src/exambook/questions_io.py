"""문항 저장 포맷 = 문항당 Markdown 1개.

사람이 직접 편집하기 쉬운 정본은 `data/questions/Q####.md`.
하위 stage(slides, tts, video)는 이 MD를 직접 읽는다.
derivative_check 등 JSON을 요구하는 스크립트는 `to_bank()` 로 변환된 인메모리 객체를 받는다.

스키마 (YAML frontmatter):
---
id: Q0001
topic_id: "1.2.1"
difficulty: 중                   # 하/중/상
answer_index: 2                  # 0-3
syllabus_ref: KDATA 출제기준 1과목 1.2.1
generated_by: qwen2.5:7b
self_critique_passed: true
derivative_max_similarity: 0.31
sql_snippet: null                # 또는 SQL 문자열
modified_by: human               # 사람이 손댄 표시 (선택)
modified_at: 2026-05-14
---

## 문제
문제 본문...

![캡션](images/Q0001/figure_1.png)

## 보기
1. 보기 1
2. 보기 2
3. 보기 3
4. 보기 4

## 해설
해설 본문...

## SQL
```sql
SELECT * FROM dual;
```
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml

from .config import PROJECT_ROOT, load_config
from .schemas import Question, QuestionBank


SECTION_RE = re.compile(r"^##\s+(문제|보기|해설|SQL)\s*$", re.MULTILINE)
CHOICE_RE = re.compile(r"^\s*(?:\d+\.|\d+\))\s+(.+)$")


def _questions_dir() -> Path:
    cfg = load_config()
    return (PROJECT_ROOT / cfg["paths"]["questions"]).parent


def md_path(qid: str) -> Path:
    return _questions_dir() / f"{qid}.md"


def images_dir(qid: str) -> Path:
    return _questions_dir() / "images" / qid


def _split_frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    meta = yaml.safe_load(parts[1]) or {}
    body = parts[2].lstrip("\n")
    return meta, body


def _split_sections(body: str) -> dict[str, str]:
    sections: dict[str, str] = {}
    matches = list(SECTION_RE.finditer(body))
    for i, m in enumerate(matches):
        name = m.group(1)
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        sections[name] = body[start:end].strip()
    return sections


def _parse_choices(text: str) -> list[str]:
    choices: list[str] = []
    for line in text.splitlines():
        m = CHOICE_RE.match(line)
        if m:
            choices.append(m.group(1).strip())
    return choices


def _parse_sql(text: str) -> Optional[str]:
    fence = re.search(r"```(?:sql)?\s*\n(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if fence:
        return fence.group(1).strip()
    return text.strip() or None


def read_question(qid: str) -> Question:
    path = md_path(qid)
    text = path.read_text(encoding="utf-8")
    meta, body = _split_frontmatter(text)
    sections = _split_sections(body)

    stem = sections.get("문제", "").strip()
    choices = _parse_choices(sections.get("보기", ""))
    explanation = sections.get("해설", "").strip()
    sql_section = sections.get("SQL", "")
    sql_snippet = _parse_sql(sql_section) if sql_section else None

    if len(choices) != 4:
        raise ValueError(f"{qid}: expected 4 choices, found {len(choices)}")

    return Question(
        id=meta["id"],
        topic_id=meta["topic_id"],
        difficulty=meta["difficulty"],
        stem=stem,
        choices=choices,
        answer_index=int(meta["answer_index"]),
        explanation=explanation,
        sql_snippet=sql_snippet,
        syllabus_ref=meta.get("syllabus_ref", ""),
        generated_by=meta.get("generated_by", ""),
        self_critique_passed=bool(meta.get("self_critique_passed", False)),
        derivative_max_similarity=meta.get("derivative_max_similarity"),
    )


def list_ids() -> list[str]:
    return sorted(p.stem for p in _questions_dir().glob("Q*.md"))


def read_bank() -> QuestionBank:
    items = [read_question(qid) for qid in list_ids()]
    return QuestionBank(items=items)


def write_question(q: Question, *, marked_modified: bool = False) -> Path:
    qdir = _questions_dir()
    qdir.mkdir(parents=True, exist_ok=True)
    path = md_path(q.id)

    meta: dict = {
        "id": q.id,
        "topic_id": q.topic_id,
        "difficulty": q.difficulty,
        "answer_index": q.answer_index,
        "syllabus_ref": q.syllabus_ref,
        "generated_by": q.generated_by,
        "self_critique_passed": q.self_critique_passed,
    }
    if q.derivative_max_similarity is not None:
        meta["derivative_max_similarity"] = round(q.derivative_max_similarity, 4)
    if marked_modified:
        meta["modified_by"] = "human"
        meta["modified_at"] = datetime.now().strftime("%Y-%m-%d")

    yml = yaml.safe_dump(meta, allow_unicode=True, sort_keys=False).strip()
    choices_md = "\n".join(f"{i + 1}. {c}" for i, c in enumerate(q.choices))
    sql_block = f"\n## SQL\n```sql\n{q.sql_snippet.strip()}\n```\n" if q.sql_snippet else ""

    text = f"""---
{yml}
---

## 문제
{q.stem}

## 보기
{choices_md}

## 해설
{q.explanation}
{sql_block}"""
    path.write_text(text, encoding="utf-8")
    return path


def write_bank(bank: QuestionBank) -> list[Path]:
    return [write_question(q) for q in bank.items]


def modified_mtime(qid: str) -> float:
    return md_path(qid).stat().st_mtime
