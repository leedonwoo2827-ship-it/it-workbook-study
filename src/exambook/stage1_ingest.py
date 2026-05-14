from __future__ import annotations

import subprocess
from pathlib import Path

from rich.console import Console

from .config import PROJECT_ROOT, find_tool, load_config

console = Console()


def _source_id(pdf: Path) -> str:
    return pdf.stem.replace(" ", "_")


def render_pdf(pdf_path: Path, dpi: int | None = None) -> Path:
    cfg = load_config()
    dpi = dpi or cfg["render"]["dpi"]

    source_id = _source_id(pdf_path)
    out_dir = PROJECT_ROOT / cfg["paths"]["raw_pages"] / source_id
    out_dir.mkdir(parents=True, exist_ok=True)

    if any(out_dir.glob("page_*.png")):
        console.print(f"[yellow]raw_pages already exist for {source_id}, skipping render[/yellow]")
        return out_dir

    pdftoppm = find_tool("pdftoppm")
    if not pdftoppm:
        raise RuntimeError("pdftoppm not found. Install Poppler: winget install oschwartz10612.Poppler")

    out_prefix = out_dir / "page"
    cmd = [pdftoppm, "-r", str(dpi), "-png", str(pdf_path), str(out_prefix)]
    console.print(f"[cyan]Rendering[/cyan] {pdf_path.name} @ {dpi}dpi → {out_dir}")
    subprocess.run(cmd, check=True)

    for png in out_dir.glob("page-*.png"):
        idx = png.stem.split("-")[-1].zfill(3)
        png.rename(out_dir / f"page_{idx}.png")

    rendered = sorted(out_dir.glob("page_*.png"))
    console.print(f"[green]Rendered {len(rendered)} pages[/green]")
    return out_dir


def ingest_all(assets_dir: Path | None = None) -> list[Path]:
    cfg = load_config()
    assets_dir = assets_dir or (PROJECT_ROOT / cfg["paths"]["assets"])

    pdfs = sorted(assets_dir.glob("*.pdf"))
    if not pdfs:
        console.print(f"[red]No PDFs found under {assets_dir}[/red]")
        return []

    out_dirs: list[Path] = []
    for pdf in pdfs:
        out_dirs.append(render_pdf(pdf))
    return out_dirs


if __name__ == "__main__":
    ingest_all()
