from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from rich.console import Console

from .config import PROJECT_ROOT, load_config, prompt_text
from .llm import TEXT_MODEL, chat_text, parse_json, unload
from .schemas import RawOCR, Topic, TopicMap

console = Console()


def _ocr_to_text_chunks(raw: RawOCR, chunk_pages: int = 4) -> list[str]:
    chunks: list[str] = []
    buffer: list[str] = []
    for i, page in enumerate(raw.pages, start=1):
        page_text_parts = [f"[페이지 {page.page}]"]
        for block in page.blocks:
            page_text_parts.append(block.text)
        buffer.append("\n".join(page_text_parts))
        if i % chunk_pages == 0:
            chunks.append("\n\n".join(buffer))
            buffer = []
    if buffer:
        chunks.append("\n\n".join(buffer))
    return chunks


def _topics_from_chunk(chunk: str, system_prompt: str) -> list[Topic]:
    raw = chat_text(
        prompt=chunk,
        system=system_prompt,
        json_mode=True,
        keep_alive="5m",
    )
    try:
        data = parse_json(raw)
    except Exception as exc:
        console.print(f"[red]topic chunk JSON parse failed: {exc}[/red]")
        return []

    out: list[Topic] = []
    for t in data.get("topics", []):
        try:
            out.append(Topic(**t))
        except Exception as exc:
            console.print(f"[yellow]invalid topic: {exc}[/yellow]")
    return out


def _merge_topics(all_topics: list[Topic]) -> list[Topic]:
    grouped: dict[str, list[Topic]] = defaultdict(list)
    for t in all_topics:
        grouped[t.id].append(t)

    merged: list[Topic] = []
    for tid, group in grouped.items():
        ref = group[0]
        total_freq = sum(t.frequency for t in group)
        themes: list[str] = []
        for t in group:
            for th in t.common_distractor_themes:
                if th not in themes:
                    themes.append(th)
        merged.append(
            Topic(
                id=ref.id,
                과목=ref.과목,
                대분류=ref.대분류,
                중분류=ref.중분류,
                소분류=ref.소분류,
                난이도=ref.난이도,
                format=ref.format,
                frequency=total_freq,
                common_distractor_themes=themes,
            )
        )
    return merged


def build_topic_map() -> Path:
    cfg = load_config()
    ocr_dir = PROJECT_ROOT / cfg["paths"]["ocr"]
    out_path = PROJECT_ROOT / cfg["paths"]["topic_map"]
    out_path.parent.mkdir(parents=True, exist_ok=True)

    system_prompt = prompt_text("topic_extract.ko.txt")
    all_topics: list[Topic] = []
    for ocr_file in sorted(ocr_dir.glob("*.json")):
        raw = RawOCR.model_validate_json(ocr_file.read_text(encoding="utf-8"))
        console.print(f"[cyan]Analyzing[/cyan] {ocr_file.name}")
        chunks = _ocr_to_text_chunks(raw)
        for idx, chunk in enumerate(chunks, start=1):
            console.print(f"  chunk {idx}/{len(chunks)}")
            all_topics.extend(_topics_from_chunk(chunk, system_prompt))

    merged = _merge_topics(all_topics)
    topic_map = TopicMap(subject="SQLD", topics=merged)
    out_path.write_text(topic_map.model_dump_json(indent=2), encoding="utf-8")
    console.print(f"[green]Wrote {out_path} ({len(merged)} topics)[/green]")

    unload(TEXT_MODEL)
    return out_path


if __name__ == "__main__":
    build_topic_map()
