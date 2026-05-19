# Exambook

IT 자격증(SQLD) 자동출제 + 슬라이드 영상 제작 파이프라인. 로컬 LLM(Qwen2.5) + VoiceWright TTS + Marp + ffmpeg.

> 상세 문서: [docs/01_workflow.md](docs/01_workflow.md) (전체 워크플로우) · [docs/02_cli.md](docs/02_cli.md) (CLI 명령) · [docs/03_adding_other_certifications.md](docs/03_adding_other_certifications.md) (다른 자격증 추가)

## 빠른 설치

```bash
# 시스템 도구
winget install Gyan.FFmpeg oschwartz10612.Poppler
npm install -g @marp-team/marp-cli
ollama pull qwen2.5:7b qwen2.5vl:7b

# VoiceWright TTS
git clone https://github.com/leedonwoo2827-ship-it/voicewright tools/voicewright
cd tools/voicewright && python -m venv .venv && .\.venv\Scripts\python.exe -m pip install -e ".[gpu]"
git lfs install && git clone https://huggingface.co/Supertone/supertonic-2 assets
cd ../..

# 프로젝트 venv
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## 빠른 실행

CMD 창 2개를 띄웁니다.

### 창 A — 파이프라인 (위에서 아래로 한 줄씩, 프롬프트 복귀하면 다음 줄)

```bat
cd /d D:\00work\260514-exambook && chcp 65001 && .venv\Scripts\activate.bat && exambook generate --total 200 --rounds 4
exambook narrate
exambook render
exambook tts
exambook video
```

### 창 B — 웹 UI (켜두고 검수)

```bat
cd /d D:\00work\260514-exambook && chcp 65001 && .venv\Scripts\activate.bat && exambook serve
```

→ http://localhost:8000
