from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn

from .config import PROJECT_ROOT, load_config, prompt_text
from .llm import VISION_MODEL, chat_vision, parse_json, unload
from .schemas import OCRBlock, OCRPage, RawOCR

console = Console()

# Qwen2.5-VL은 패치 크기 14 × merge 2 = 28 픽셀 그리드를 요구한다.
# 이 단위로 정렬하지 않으면 모델 런타임에서 GGML_ASSERT 가 깨진다.
QWEN_PATCH = 28
# 최대 변 길이 — 너무 크면 VRAM 폭주, 너무 작으면 한글 OCR 정확도 하락.
# 1568 = 28 × 56, A4 비율로 봤을 때 한글이 충분히 읽힘.
QWEN_MAX_SIDE = 1568


def _prepare_image(src: Path) -> Path:
    """Qwen2.5-VL이 안전하게 처리하는 차원으로 리사이즈/패딩한 사본을 반환.

    같은 폴더에 `.ocr.png` 사이드카로 저장. 원본 raw_pages PNG는 보존.
    이미 존재하고 mtime이 원본보다 새로우면 재사용.
    """
    dst = src.with_suffix(".ocr.png")
    if dst.exists() and dst.stat().st_mtime >= src.stat().st_mtime:
        return dst

    img = Image.open(src).convert("RGB")
    w, h = img.size
    # 긴 변을 QWEN_MAX_SIDE 로 비율 유지 축소
    scale = min(QWEN_MAX_SIDE / max(w, h), 1.0)
    if scale < 1.0:
        w, h = int(w * scale), int(h * scale)
        img = img.resize((w, h), Image.LANCZOS)
    # 28 배수로 내림 (모델은 작은 쪽으로 정렬 시 정확함)
    new_w = max(QWEN_PATCH, (w // QWEN_PATCH) * QWEN_PATCH)
    new_h = max(QWEN_PATCH, (h // QWEN_PATCH) * QWEN_PATCH)
    if (new_w, new_h) != (w, h):
        img = img.crop((0, 0, new_w, new_h))
    img.save(dst, format="PNG", optimize=False)
    return dst


def _ocr_one_page(image_path: Path, system_prompt: str) -> list[OCRBlock]:
    user_prompt = "이 시험지 페이지를 추출하여 JSON 형식으로 반환하세요."
    prepared = _prepare_image(image_path)
    try:
        raw = chat_vision(
            prompt=user_prompt,
            image_path=prepared,
            system=system_prompt,
            json_mode=True,
            keep_alive="5m",
        )
    except Exception as exc:
        console.print(f"[red]OCR failed for {image_path.name}: {exc}[/red]")
        return []
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
