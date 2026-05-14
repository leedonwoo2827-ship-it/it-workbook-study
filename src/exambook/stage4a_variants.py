"""Track A — 개인학습용 변형 문항 생성.

⚠️ 결과물은 data/private/ 에만 저장되고 배포 파이프라인(stage 5~7) 입력으로 사용 금지.
이 모듈은 원본 OCR 텍스트를 프롬프트에 포함한다 — 따라서 출력물은 2차적저작물 위험이 있어
사용자 PC 안에서만, 학습 목적으로만 사용된다.
"""
from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path
from typing import Any

from rich.console import Console

from .config import PROJECT_ROOT, load_config, prompt_text
from .llm import TEXT_MODEL, chat_text, parse_json, unload
from .schemas import RawOCR, VariantBank, VariantQuestion

console = Console()


VARIANT_TYPES = ["paraphrase", "number_swap", "distractor_swap", "format_shift"]


def _ocr_question_blocks(raw: RawOCR) -> list[str]:
    """OCR 텍스트를 문항 단위 청크로 단순 분할.

    빈 줄 또는 큰 간격을 기준으로 한 매우 단순한 휴리스틱. 실제 정확도는
    Track A 학습용이므로 100%일 필요는 없다.
    """
    chunks: list[str] = []
    for page in raw.pages:
        page_text_parts: list[str] = []
        for block in page.blocks:
            text = block.text.strip()
            if text:
                page_text_parts.append(text)
        if page_text_parts:
            chunks.append("\n".join(page_text_parts))
    return chunks


def _variant_one(source_chunk: str, variant_type: str, system_prompt: str, seed: int) -> list[VariantQuestion]:
    payload = {
        "source": source_chunk[:3000],
        "variant_type": variant_type,
    }
    raw = chat_text(
        prompt=json.dumps(payload, ensure_ascii=False, indent=2),
        system=system_prompt,
        options={"temperature": 0.6, "seed": seed},
        json_mode=True,
        keep_alive="5m",
    )

    try:
        data = parse_json(raw)
    except Exception as exc:
        console.print(f"[red]variant JSON parse failed: {exc}[/red]")
        return []

    out: list[VariantQuestion] = []
    for idx, item in enumerate(data.get("items", [])):
        vid_seed = f"V::{variant_type}::{seed}::{idx}"
        vid = "V" + hashlib.sha1(vid_seed.encode("utf-8")).hexdigest()[:10]
        try:
            out.append(VariantQuestion(
                id=vid,
                topic_id=item.get("topic_id", "unknown"),
                difficulty=item.get("difficulty", "중"),
                stem=item["stem"],
                choices=item["choices"],
                answer_index=int(item["answer_index"]),
                explanation=item["explanation"],
                sql_snippet=item.get("sql_snippet"),
                syllabus_ref=item.get("syllabus_ref", "개인학습용 변형"),
                generated_by=TEXT_MODEL,
                self_critique_passed=False,
                source_question_id=item.get("source_question_id"),
                variant_type=variant_type,
            ))
        except Exception as exc:
            console.print(f"[yellow]invalid variant: {exc}[/yellow]")
    return out


def build_variants(max_chunks: int | None = None, seed: int = 20260514) -> Path:
    cfg = load_config()
    ocr_dir = PROJECT_ROOT / cfg["paths"]["ocr"]
    out_path = PROJECT_ROOT / cfg["paths"]["variants_private"]
    out_path.parent.mkdir(parents=True, exist_ok=True)

    system_prompt = prompt_text("variant_generate.ko.txt")
    rng = random.Random(seed)

    all_variants: list[VariantQuestion] = []
    for ocr_file in sorted(ocr_dir.glob("*.json")):
        raw = RawOCR.model_validate_json(ocr_file.read_text(encoding="utf-8"))
        chunks = _ocr_question_blocks(raw)
        if max_chunks:
            chunks = chunks[:max_chunks]
        console.print(f"[cyan]variants[/cyan] {ocr_file.name}: {len(chunks)} chunks")

        for chunk in chunks:
            vt = rng.choice(VARIANT_TYPES)
            all_variants.extend(_variant_one(chunk, vt, system_prompt, rng.randint(1, 10**6)))

    bank = VariantBank(items=all_variants)
    out_path.write_text(bank.model_dump_json(indent=2), encoding="utf-8")
    console.print(f"[green]Wrote {len(all_variants)} variants → {out_path}[/green]")
    console.print("[red]⚠ Track A artifact — do NOT distribute, do NOT pass to stage 5+[/red]")

    unload(TEXT_MODEL)
    return out_path


if __name__ == "__main__":
    build_variants()
