"""Exambook 로컬 웹 UI (FastAPI).

스카이블루 파스텔 + GPT-like 미니멀 디자인.
실행:  exambook serve            # http://localhost:8000
"""
from __future__ import annotations

import json
import re
import subprocess
import uuid
from pathlib import Path

import yaml
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from ..config import PROJECT_ROOT, load_config, load_voice_map
from ..questions_io import list_ids, md_path, read_question, write_question

WEB_DIR = Path(__file__).parent
TEMPLATES = Jinja2Templates(directory=str(WEB_DIR / "templates"))


class SaveBody(BaseModel):
    raw_md: str


class RebuildBody(BaseModel):
    qids: list[str] = []
    force: bool = False
    skip_video: bool = False


class PronBody(BaseModel):
    pron: dict[str, str]


class TTSPreviewBody(BaseModel):
    text: str
    voice: str = "F2"
    speed: float = 1.0


def _cfg_path(key: str) -> Path:
    cfg = load_config()
    return PROJECT_ROOT / cfg["paths"][key]


def create_app() -> FastAPI:
    app = FastAPI(title="Exambook Studio", version="0.1.0")
    app.mount("/static", StaticFiles(directory=str(WEB_DIR / "static")), name="static")

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> HTMLResponse:
        ids = list_ids()
        cards = []
        for qid in ids:
            try:
                q = read_question(qid)
                cards.append({
                    "id": q.id,
                    "topic_id": q.topic_id,
                    "difficulty": q.difficulty,
                    "stem_preview": q.stem[:80],
                })
            except Exception as e:
                cards.append({"id": qid, "error": str(e)})
        return TEMPLATES.TemplateResponse("index.html", {"request": request, "cards": cards})

    @app.get("/q/{qid}", response_class=HTMLResponse)
    async def question_page(request: Request, qid: str) -> HTMLResponse:
        if not md_path(qid).exists():
            raise HTTPException(404, f"{qid} not found")
        text = md_path(qid).read_text(encoding="utf-8")
        ids = list_ids()
        return TEMPLATES.TemplateResponse(
            "edit.html",
            {"request": request, "qid": qid, "raw_md": text, "all_ids": ids},
        )

    @app.get("/api/q/{qid}")
    async def api_get(qid: str) -> JSONResponse:
        path = md_path(qid)
        if not path.exists():
            raise HTTPException(404)
        return JSONResponse({"id": qid, "raw_md": path.read_text(encoding="utf-8")})

    @app.put("/api/q/{qid}")
    async def api_save(qid: str, body: SaveBody) -> JSONResponse:
        path = md_path(qid)
        if not path.exists():
            raise HTTPException(404)
        path.write_text(body.raw_md, encoding="utf-8")
        try:
            q = read_question(qid)
            write_question(q, marked_modified=True)
            return JSONResponse({"ok": True, "id": qid})
        except Exception as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=400)

    @app.post("/api/rebuild")
    async def api_rebuild(body: RebuildBody) -> JSONResponse:
        from .. import stage5_render, stage6_tts, stage7_video
        ids = body.qids if body.qids else None
        try:
            stage5_render.render_all(qids=ids, force=body.force)
            stage6_tts.synthesize(qids=ids, force=body.force)
            if not body.skip_video:
                stage7_video.assemble(qids=ids, force=body.force)
            return JSONResponse({"ok": True})
        except Exception as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

    @app.get("/api/parsed/{qid}")
    async def api_parsed(qid: str) -> JSONResponse:
        try:
            q = read_question(qid)
            return JSONResponse(q.model_dump())
        except Exception as e:
            raise HTTPException(400, f"parse error: {e}")

    @app.get("/pronunciations", response_class=HTMLResponse)
    async def pronunciations_page(request: Request) -> HTMLResponse:
        ids = list_ids()
        load_voice_map.cache_clear()
        voice_map = load_voice_map()
        pron = voice_map.get("pronunciation", {})
        return TEMPLATES.TemplateResponse(
            "pronunciations.html",
            {"request": request, "pron": pron, "all_ids": ids},
        )

    @app.get("/api/pronunciations")
    async def api_get_pronunciations() -> JSONResponse:
        load_voice_map.cache_clear()
        return JSONResponse(load_voice_map().get("pronunciation", {}))

    @app.put("/api/pronunciations")
    async def api_save_pronunciations(body: PronBody) -> JSONResponse:
        path = PROJECT_ROOT / "config" / "voice_map.yaml"
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        data["pronunciation"] = body.pron
        path.write_text(
            yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        load_voice_map.cache_clear()
        return JSONResponse({"ok": True, "count": len(body.pron)})

    @app.post("/api/tts/preview")
    async def api_tts_preview(body: TTSPreviewBody) -> FileResponse:
        cfg = load_config()
        vw_path_rel = cfg["paths"].get("voicewright_cli", "")
        vw = PROJECT_ROOT / vw_path_rel
        if not vw.exists():
            raise HTTPException(500, "voicewright not installed")

        load_voice_map.cache_clear()
        voice_map = load_voice_map()
        pron = voice_map.get("pronunciation", {})
        text = body.text
        for kw, sub in sorted(pron.items(), key=lambda kv: -len(kv[0])):
            text = re.sub(rf"\b{re.escape(kw)}\b", sub, text, flags=re.IGNORECASE)

        preview_dir = PROJECT_ROOT / "build" / "previews"
        preview_dir.mkdir(parents=True, exist_ok=True)
        out_wav = preview_dir / f"preview_{uuid.uuid4().hex[:8]}.wav"

        batch = preview_dir / f"_preview_{uuid.uuid4().hex[:8]}.json"
        batch.write_text(
            json.dumps({"items": [{
                "id": "preview",
                "text": text,
                "voice": body.voice,
                "speed": body.speed,
                "output": str(out_wav),
            }]}, ensure_ascii=False),
            encoding="utf-8",
        )
        try:
            subprocess.run([str(vw), "batch", str(batch)], check=True, capture_output=True)
        except subprocess.CalledProcessError as e:
            raise HTTPException(500, f"voicewright failed: {e.stderr.decode('utf-8', 'ignore')[:300]}")
        finally:
            batch.unlink(missing_ok=True)

        if not out_wav.exists():
            raise HTTPException(500, "no wav produced")
        return FileResponse(out_wav, media_type="audio/wav")

    @app.get("/preview/slide/{qid}/{page}")
    async def preview_slide(qid: str, page: int) -> FileResponse:
        png_dir = _cfg_path("slides_png")
        candidate = png_dir / f"{qid}.{page:03d}.png"
        if not candidate.exists():
            single = png_dir / f"{qid}.png"
            if single.exists():
                candidate = single
            else:
                raise HTTPException(404, f"slide {qid}.{page:03d} not rendered yet")
        return FileResponse(candidate, media_type="image/png")

    @app.get("/preview/audio/{qid}/{kind}")
    async def preview_audio(qid: str, kind: str) -> FileResponse:
        if kind not in {"stem", "exp"}:
            raise HTTPException(400, "kind must be stem or exp")
        wav = _cfg_path("audio") / f"{qid}_{kind}.wav"
        if not wav.exists():
            raise HTTPException(404, f"audio {qid}_{kind}.wav not generated yet")
        return FileResponse(wav, media_type="audio/wav")

    @app.get("/preview/video/{qid}")
    async def preview_video(qid: str) -> FileResponse:
        mp4 = _cfg_path("videos") / f"{qid}.mp4"
        if not mp4.exists():
            raise HTTPException(404, f"video {qid}.mp4 not assembled yet")
        return FileResponse(mp4, media_type="video/mp4")

    return app


def run(host: str = "127.0.0.1", port: int = 8000, reload: bool = False) -> None:
    import uvicorn
    uvicorn.run("exambook.web.app:create_app", host=host, port=port, reload=reload, factory=True)
