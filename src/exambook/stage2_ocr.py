from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn

from .config import PROJECT_ROOT, load_config, prompt_text
from .llm import VISION_MODEL, chat_vision, parse_json, unload
from .schemas import OCRBlock, OCRPage, RawOCR

console = Console()


def _ocr_one_page(image_path: Path, system_prompt: str) -> list[OCRBlock]:
    user_prompt = "이 시험지 페이지를 추출하여 JSON 형식으로 반환하세요."
    raw = chat_vision(
        prompt=user_prompt,
        image_path=image_path,
        system=system_prompt,
        json_mode=True,
        keep_alive="5m",
    )
    try:
        parsed: dict[str, Any] = parse_json(raw)
    except Exception as exc:
        console.print(f"[red]JSON parse failed for {image_path.name}: {exc}[/red]")
        return []

    blocks_raw = parsed.get("blocks", [])
    blocks: list[OCRBlock] = []
    for b in blocks_raw:
        try:
            blocks.append(OCRBlock(**b))
        except Exception as exc:
            console.print(f"[yellow]invalid block in {image_path.name}: {exc}[/yellow]")
    return blocks


def ocr_source(source_dir: Path) -> Path:
    cfg = load_config()
    out_path = PROJECT_ROOT / cfg["paths"]["ocr"] / f"{source_dir.name}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if out_path.exists():
        console.print(f"[yellow]OCR already done for {source_dir.name}, skipping[/yellow]")
        return out_path

    system_prompt = prompt_text("ocr_extract.ko.txt")
    pages = sorted(source_dir.glob("page_*.png"))

    page_results: list[OCRPage] = []
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task(f"OCR {source_dir.name}", total=len(pages))
        for png in pages:
            page_num = int(png.stem.split("_")[-1])
            blocks = _ocr_one_page(png, system_prompt)
            page_results.append(OCRPage(page=page_num, blocks=blocks))
            progress.advance(task)

    raw = RawOCR(source_id=source_dir.name, pages=page_results)
    out_path.write_text(raw.model_dump_json(indent=2), encoding="utf-8")
    console.print(f"[green]Wrote {out_path}[/green]")

    unload(VISION_MODEL)
    return out_path


def ocr_all() -> list[Path]:
    cfg = load_config()
    raw_pages_root = PROJECT_ROOT / cfg["paths"]["raw_pages"]
    sources = [d for d in raw_pages_root.iterdir() if d.is_dir()]
    return [ocr_source(s) for s in sources]


if __name__ == "__main__":
    ocr_all()
