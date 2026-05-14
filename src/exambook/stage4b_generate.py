"""Track B — 배포용 신규 문항 생성.

법적 핵심 모듈. 입력으로 raw_ocr.json 텍스트를 절대 받지 않는다.
입력 = KDATA 공개 출제기준(syllabus YAML) + topic_map.json 추상 통계뿐.
"""
from __future__ import annotations

import hashlib
import json
import random
from collections import Counter
from pathlib import Path
from typing import Any

import yaml
from rich.console import Console

from .config import PROJECT_ROOT, load_config, prompt_text
from .llm import TEXT_MODEL, chat_text, parse_json, unload
from .questions_io import write_question
from .schemas import Question, QuestionBank, TopicMap

console = Console()


def _load_syllabus() -> dict[str, Any]:
    cfg = load_config()
    syllabus_path = PROJECT_ROOT / cfg["paths"]["syllabus"]
    with syllabus_path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _load_topic_stats() -> dict[str, dict[str, Any]]:
    cfg = load_config()
    topic_map_path = PROJECT_ROOT / cfg["paths"]["topic_map"]
    if not topic_map_path.exists():
        console.print("[yellow]topic_map.json missing — proceeding with uniform stats[/yellow]")
        return {}
    tm = TopicMap.model_validate_json(topic_map_path.read_text(encoding="utf-8"))
    return {t.id: t.model_dump() for t in tm.topics}


def _plan_distribution(syllabus: dict[str, Any], total: int) -> list[tuple[dict[str, Any], int]]:
    """각 과목 weight에 따라 문항 수 배분 → topic까지 round-robin."""
    subjects = syllabus["subjects"]
    weight_sum = sum(s["weight"] for s in subjects)

    plan: list[tuple[dict[str, Any], int]] = []
    for subject in subjects:
        subj_total = round(total * subject["weight"] / weight_sum)
        topics: list[dict[str, Any]] = []
        for ch in subject["chapters"]:
            for t in ch["topics"]:
                topics.append({
                    "subject_code": subject["code"],
                    "subject_name": subject["name"],
                    "chapter_code": ch["code"],
                    "chapter_name": ch["name"],
                    "topic_code": t["code"],
                    "topic_name": t["name"],
                    "keywords": t.get("keywords", []),
                })

        per_topic = max(1, subj_total // max(1, len(topics)))
        remainder = subj_total - per_topic * len(topics)
        for i, topic in enumerate(topics):
            count = per_topic + (1 if i < remainder else 0)
            if count > 0:
                plan.append((topic, count))
    return plan


def _build_user_payload(topic: dict[str, Any], count: int, stats: dict[str, Any] | None) -> str:
    payload: dict[str, Any] = {
        "출제기준": {
            "과목코드": topic["subject_code"],
            "과목명": topic["subject_name"],
            "대분류코드": topic["chapter_code"],
            "대분류명": topic["chapter_name"],
            "소분류코드": topic["topic_code"],
            "소분류명": topic["topic_name"],
            "핵심키워드": topic["keywords"],
        },
        "생성요청": {
            "문항수": count,
            "난이도혼합": ["하", "중", "상"],
        },
    }
    if stats:
        payload["과거출제통계"] = {
            "빈도": stats.get("frequency"),
            "함정테마": stats.get("common_distractor_themes", []),
        }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _gen_questions(topic: dict[str, Any], count: int, stats: dict[str, Any] | None, system_prompt: str, seed: int) -> list[Question]:
    cfg = load_config()
    user = _build_user_payload(topic, count, stats)
    raw = chat_text(
        prompt=user,
        system=system_prompt,
        options={
            "temperature": cfg["generation"]["temperature_question"],
            "seed": seed,
        },
        json_mode=True,
        keep_alive="5m",
    )

    try:
        data = parse_json(raw)
    except Exception as exc:
        console.print(f"[red]gen JSON parse failed for {topic['topic_code']}: {exc}[/red]")
        return []

    items = data.get("items", [])
    out: list[Question] = []
    for idx, item in enumerate(items):
        qid_seed = f"{topic['topic_code']}::{seed}::{idx}"
        qid = "Q" + hashlib.sha1(qid_seed.encode("utf-8")).hexdigest()[:10]
        try:
            out.append(Question(
                id=qid,
                topic_id=topic["topic_code"],
                difficulty=item.get("difficulty", "중"),
                stem=item["stem"],
                choices=item["choices"],
                answer_index=int(item["answer_index"]),
                explanation=item["explanation"],
                sql_snippet=item.get("sql_snippet"),
                syllabus_ref=item.get("syllabus_ref") or f"KDATA 출제기준 {topic['subject_code']}과목 {topic['topic_code']}",
                generated_by=TEXT_MODEL,
                self_critique_passed=False,
            ))
        except Exception as exc:
            console.print(f"[yellow]invalid question for {topic['topic_code']}: {exc}[/yellow]")
    return out


def _critique(q: Question, system_prompt: str) -> Question | None:
    payload = q.model_dump()
    payload.pop("derivative_max_similarity", None)
    raw = chat_text(
        prompt=json.dumps(payload, ensure_ascii=False),
        system=system_prompt,
        options={"temperature": 0.2},
        json_mode=True,
        keep_alive="5m",
    )
    try:
        data = parse_json(raw)
    except Exception:
        return None
    if not data.get("passed"):
        console.print(f"[yellow]critique rejected {q.id}: {data.get('issues')}[/yellow]")
        return None

    revised = data.get("revised", {})
    try:
        return Question(
            id=q.id,
            topic_id=revised.get("topic_id", q.topic_id),
            difficulty=revised.get("difficulty", q.difficulty),
            stem=revised.get("stem", q.stem),
            choices=revised.get("choices", q.choices),
            answer_index=int(revised.get("answer_index", q.answer_index)),
            explanation=revised.get("explanation", q.explanation),
            sql_snippet=revised.get("sql_snippet", q.sql_snippet),
            syllabus_ref=revised.get("syllabus_ref", q.syllabus_ref),
            generated_by=q.generated_by,
            self_critique_passed=True,
        )
    except Exception as exc:
        console.print(f"[yellow]critique parse fail {q.id}: {exc}[/yellow]")
        return None


def generate_bank(total: int = 50, seed: int = 20260514) -> Path:
    cfg = load_config()
    syllabus = _load_syllabus()
    stats_by_id = _load_topic_stats()

    gen_prompt = prompt_text("question_generate.ko.txt")
    crit_prompt = prompt_text("self_critique.ko.txt")

    rng = random.Random(seed)
    plan = _plan_distribution(syllabus, total)
    console.print(f"[cyan]Plan[/cyan]: {len(plan)} topic-buckets, target total ~{total}")

    bank: list[Question] = []
    for topic, count in plan:
        stats = stats_by_id.get(topic["topic_code"])
        topic_seed = rng.randint(1, 1_000_000)
        console.print(f"  [bold]{topic['topic_code']}[/bold] {topic['topic_name']} × {count}")
        candidates = _gen_questions(topic, count, stats, gen_prompt, topic_seed)
        for q in candidates:
            revised = _critique(q, crit_prompt)
            if revised:
                bank.append(revised)

    out_path = PROJECT_ROOT / cfg["paths"]["questions"]
    out_path.parent.mkdir(parents=True, exist_ok=True)

    for q in bank:
        write_question(q)
    out_path.write_text(QuestionBank(items=bank).model_dump_json(indent=2), encoding="utf-8")
    console.print(f"[green]Wrote {len(bank)} MD files + index {out_path}[/green]")

    counter = Counter(q.topic_id for q in bank)
    console.print(f"[dim]Per-topic distribution: {dict(counter)}[/dim]")

    unload(TEXT_MODEL)
    return out_path


if __name__ == "__main__":
    generate_bank()
