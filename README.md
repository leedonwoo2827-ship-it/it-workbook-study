# Exambook

IT 자격증(SQLD) 자동출제 + 슬라이드 영상 제작 파이프라인. 로컬 LLM(Qwen2.5) + VoiceWright TTS + Marp + ffmpeg.

> 상세 문서: [docs/workflow.md](docs/workflow.md) (전체 워크플로우) · [docs/cli.md](docs/cli.md) (CLI 명령 가이드)

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

```bash
.venv\Scripts\activate
python -m exambook.cli doctor                  # 도구·모델 점검
python -m exambook.cli run-all --total 50      # 전체 1회분 자동
```

문항당 편집·부분 재빌드:

```bash
# data/questions/Q0042.md 직접 편집 후
python -m exambook.cli rebuild Q0042           # 그 문항만 슬라이드→음성→영상 재생성
python -m exambook.cli list                    # 현재 문항 목록
```
