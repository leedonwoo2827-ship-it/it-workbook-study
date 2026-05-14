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

    class ScriptBody(BaseModel):
        text: str

    @app.put("/api/script/{qid}/{scene}")
    async def api_script_save(qid: str, scene: int, body: ScriptBody) -> JSONResponse:
        from ..stage6_tts import script_override_path
        if scene not in (1, 2):
            raise HTTPException(400, "scene must be 1 or 2")
        if not md_path(qid).exists():
            raise HTTPException(404, f"{qid} not found")
        p = script_override_path(qid, scene)
        p.write_text(body.text, encoding="utf-8")
        return JSONResponse({"ok": True, "path": str(p.relative_to(PROJECT_ROOT))})

    @app.delete("/api/script/{qid}/{scene}")
    async def api_script_reset(qid: str, scene: int) -> JSONResponse:
        from ..stage6_tts import script_override_path
        if scene not in (1, 2):
            raise HTTPException(400, "scene must be 1 or 2")
        p = script_override_path(qid, scene)
        existed = p.exists()
        if existed:
            p.unlink()
        return JSONResponse({"ok": True, "removed": existed})

    @app.get("/api/script/{qid}")
    async def api_script(qid: str) -> JSONResponse:
        """TTS에 들어가는 stem/exp 대본 + 발음 변환 segment 반환.

        scenes: [{scene, label, voice, original, segments[], override_active, auto_text}]
        """
        from ..stage6_tts import (
            build_scripts,
            _qid_to_chapter,
            load_script_override,
        )
        try:
            q = read_question(qid)
        except Exception as e:
            raise HTTPException(400, f"parse error: {e}")
        load_voice_map.cache_clear()
        voice_map = load_voice_map()
        pron = voice_map.get("pronunciation", {}) or {}
        all_ids_list = list_ids()
        idx = all_ids_list.index(qid) + 1 if qid in all_ids_list else 1

        # 자동 생성 원본 (override 없을 때의 기본)
        auto_stem, auto_exp = build_scripts(q, idx, {})

        # override 있으면 그것을 원본으로 사용
        ov_stem = load_script_override(qid, 1)
        ov_exp = load_script_override(qid, 2)
        stem_orig = ov_stem if ov_stem is not None else auto_stem
        exp_orig = ov_exp if ov_exp is not None else auto_exp

        # 변환본은 위 원본에 발음 사전 적용
        def apply_pron(text: str) -> str:
            if not pron:
                return text
            out = text
            for kw, sub in sorted(pron.items(), key=lambda kv: -len(str(kv[0]))):
                if kw is None or sub is None:
                    continue
                out = re.sub(rf"\b{re.escape(str(kw))}\b", str(sub), out, flags=re.IGNORECASE)
            return out

        stem_conv = apply_pron(stem_orig)
        exp_conv = apply_pron(exp_orig)

        def segment(text: str) -> list[dict]:
            if not pron:
                return [{"text": text, "highlighted": False}]
            items = sorted(
                ((str(k), str(v)) for k, v in pron.items() if k and v),
                key=lambda kv: -len(kv[0]),
            )
            if not items:
                return [{"text": text, "highlighted": False}]
            pattern = re.compile(
                "|".join(rf"(?P<g{i}>\b{re.escape(kw)}\b)" for i, (kw, _) in enumerate(items)),
                re.IGNORECASE,
            )
            out: list[dict] = []
            pos = 0
            for m in pattern.finditer(text):
                if m.start() > pos:
                    out.append({"text": text[pos:m.start()], "highlighted": False})
                for i, (kw, sub) in enumerate(items):
                    if m.group(f"g{i}") is not None:
                        out.append({"text": sub, "highlighted": True, "original": kw})
                        break
                pos = m.end()
            if pos < len(text):
                out.append({"text": text[pos:], "highlighted": False})
            return out

        roles = voice_map.get("roles", {}) or {}
        stem_voice = (roles.get("stem", {}) or {}).get("voice", "F2")
        exp_voice = (roles.get("explanation", {}) or {}).get("voice", "M3")

        chapter = _qid_to_chapter(qid)
        return JSONResponse({
            "qid": qid,
            "chapter": chapter,
            "scenes": [
                {
                    "scene": 1,
                    "label": "문제 본문",
                    "voice": stem_voice,
                    "original": stem_orig,
                    "converted": stem_conv,
                    "segments": segment(stem_conv),
                    "override_active": ov_stem is not None,
                    "auto_text": auto_stem,
                },
                {
                    "scene": 2,
                    "label": "정답 및 해설",
                    "voice": exp_voice,
                    "original": exp_orig,
                    "converted": exp_conv,
                    "segments": segment(exp_conv),
                    "override_active": ov_exp is not None,
                    "auto_text": auto_exp,
                },
            ],
        })

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
        from ..stage6_tts import narration_path
        if kind not in {"stem", "exp", "1", "2"}:
            raise HTTPException(400, "kind must be stem|exp|1|2")
        scene = 1 if kind in {"stem", "1"} else 2
        wav = narration_path(qid, scene)
        if not wav.exists():
            raise HTTPException(404, f"audio scene {scene} not generated yet")
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
