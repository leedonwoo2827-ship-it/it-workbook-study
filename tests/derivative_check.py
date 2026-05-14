"""배포 전 의무 게이트.

생성된 questions.json 의 모든 문항(stem + choices)을 OCR 원문(raw_ocr/*.json)과
sentence-transformer 한국어 임베딩으로 cosine similarity 비교. threshold 이상이면
해당 문항을 폐기(또는 격리)한다.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from rich.console import Console

# 프로젝트 루트를 sys.path에 추가하여 단독 실행 가능하게
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.exambook.config import load_config  # noqa: E402
from src.exambook.questions_io import list_ids, read_question, write_question  # noqa: E402
from src.exambook.schemas import RawOCR  # noqa: E402

console = Console()


def _flatten_question_text(stem: str, choices: list[str]) -> str:
    return stem.strip() + " " + " ".join(c.strip() for c in choices)


def _flatten_ocr_chunks(raw: RawOCR, min_chars: int = 30) -> list[str]:
    chunks: list[str] = []
    for page in raw.pages:
        for block in page.blocks:
            text = block.text.strip()
            if len(text) >= min_chars:
                chunks.append(text)
    return chunks


def _load_model(name: str):
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(name)


def _encode(model, texts: list[str]) -> np.ndarray:
    return model.encode(texts, convert_to_numpy=True, normalize_embeddings=True)


def check(ocr_paths: list[Path], threshold: float, model_name: str) -> dict:
    qids = list_ids()
    if not qids:
        console.print("[red]No questions to check[/red]")
        return {"passed": True, "violations": []}

    questions = [read_question(qid) for qid in qids]

    ocr_chunks: list[str] = []
    for p in ocr_paths:
        raw = RawOCR.model_validate_json(p.read_text(encoding="utf-8"))
        ocr_chunks.extend(_flatten_ocr_chunks(raw))

    if not ocr_chunks:
        console.print("[yellow]No OCR chunks found — similarity check trivially passes[/yellow]")
        return {"passed": True, "violations": []}

    console.print(f"[cyan]Loading[/cyan] {model_name}")
    model = _load_model(model_name)

    console.print(f"[cyan]Encoding[/cyan] {len(ocr_chunks)} OCR chunks")
    ocr_emb = _encode(model, ocr_chunks)

    q_texts = [_flatten_question_text(q.stem, q.choices) for q in questions]
    console.print(f"[cyan]Encoding[/cyan] {len(q_texts)} questions")
    q_emb = _encode(model, q_texts)

    sim = q_emb @ ocr_emb.T
    max_sim = sim.max(axis=1)

    violations: list[dict] = []
    for q, score in zip(questions, max_sim):
        q.derivative_max_similarity = float(score)
        write_question(q)
        if score >= threshold:
            violations.append({
                "id": q.id,
                "max_similarity": float(score),
                "stem_preview": q.stem[:80],
            })

    return {
        "passed": len(violations) == 0,
        "violations": violations,
        "max_overall": float(max_sim.max()),
        "mean": float(max_sim.mean()),
    }


def main() -> int:
    cfg = load_config()
    default_threshold = cfg["generation"]["derivative_similarity_threshold"]
    default_model = cfg["models"]["embedding"]

    parser = argparse.ArgumentParser(description="배포 전 원본성 게이트")
    parser.add_argument("--ocr-dir", default=str(ROOT / cfg["paths"]["ocr"]))
    parser.add_argument("--threshold", type=float, default=default_threshold)
    parser.add_argument("--model", default=default_model)
    args = parser.parse_args()

    ocr_paths = sorted(Path(args.ocr_dir).glob("*.json"))
    result = check(ocr_paths, args.threshold, args.model)

    console.print(f"[cyan]max overall:[/cyan] {result.get('max_overall', 0):.3f}  mean: {result.get('mean', 0):.3f}")
    if result["passed"]:
        console.print(f"[green]PASS[/green] (threshold={args.threshold}) — 0 violations")
        return 0
    console.print(f"[red]FAIL[/red] {len(result['violations'])} violations")
    for v in result["violations"]:
        console.print(f"  {v['id']}: {v['max_similarity']:.3f}  «{v['stem_preview']}…»")
    return 2


if __name__ == "__main__":
    sys.exit(main())
