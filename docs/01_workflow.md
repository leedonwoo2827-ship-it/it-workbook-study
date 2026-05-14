# Exambook 워크플로우 (내부·공부용)

> 본 문서는 내부 학습/공부용 메모입니다. 일정 시간 뒤 정리·삭제될 수 있습니다.

## 핵심 결정 사항

| 항목 | 선택 | 라이선스 |
|---|---|---|
| 텍스트 LLM | `qwen2.5:7b` (Ollama) | Apache-2.0 ✓ 상업가능 |
| 비전 LLM (OCR) | `qwen2.5vl:7b` (Ollama) | Apache-2.0 ✓ |
| TTS | VoiceWright (Supertone Supertonic) | MIT 코드 + OpenRAIL-M 모델 |
| 슬라이드 | Marp + Apple-style 테마 | MIT |
| 영상 | ffmpeg + NVENC (RTX 4070) | LGPL |
| 임베딩 | jhgan/ko-sroberta-multitask | 한국어 SOTA |

PC 가정: AMD Ryzen 9 7945HX, RAM 32GB, **VRAM 8GB** (RTX 4070 Laptop).
GPU에는 한 번에 LLM 하나만 상주 (`keep_alive=0`).

---

## 디렉토리 구조

```
d:\00work\260514-exambook\
├── _assets\                    출처 PDF (gitignore)
├── data\
│   ├── source_pdfs\
│   ├── raw_pages\              poppler 렌더 PNG
│   ├── ocr\                    raw_ocr.json (per source)
│   ├── syllabus\               kdata_sqld.yaml (공개 출제기준)
│   ├── analysis\               topic_map.json (추상 통계)
│   ├── questions\              ★ Q####.md (정본, 사람이 편집 가능)
│   │   ├── _index.json         생성 스냅샷
│   │   ├── Q0001.md
│   │   └── images\Q0001\…      문항당 이미지
│   └── private\                Track A 변형본 (배포 금지)
├── build\
│   ├── slides_md\              Marp .md (자동생성)
│   ├── slides_png\             1920×1080 PNG
│   ├── audio\                  Q####_stem.wav, Q####_exp.wav
│   └── videos\                 Q####.mp4, final.mp4
├── src\exambook\               파이프라인 코드
├── prompts\                    한국어 프롬프트 5종
├── themes\
│   ├── apple_style.css         애플 스타일 (기본)
│   └── sqld_exam.css           시험지 스타일
├── config\
│   ├── pipeline.yaml
│   └── voice_map.yaml
└── tools\voicewright\          VoiceWright 클론 + 모델 자산
```

---

## 워크플로우 (단계별 상세)

### PHASE 0 — 사전 준비 (1회)
- `_assets/` 에 출처 PDF 배치
- `data/syllabus/kdata_sqld.yaml` 검토/보강

### PHASE 1 — 소스 분석 (~10-30분)

| 단계 | 명령 | 모델 | 시간 (50문항 기준) |
|---|---|---|---|
| 1. PDF→PNG | `exambook ingest` | poppler | 1-2분 |
| 2. OCR | `exambook ocr` | qwen2.5vl:7b | 페이지×30초 |
| 3. 토픽 분석 | `exambook topics` | qwen2.5:7b | 1-2분 |

각 단계는 Rich progress bar로 진행률 표시.

### PHASE 2 — 신규 문항 생성 (Track B, ~10-30분)

```bash
exambook generate --total 50         # 1회분(과목1 10 + 과목2 40 자동 배분)
exambook generate --total 100        # 2회분
exambook generate --total 200        # 4회분
exambook check                       # 의무 게이트: derivative cosine ≥ 0.75 폐기
```

KDATA `weight` 비율(1:4) 자동 적용, 토픽별 batch 생성, self-critique 자체검증.

### PHASE 3 — 사람 검수·편집 (선택)

`data/questions/Q####.md` 직접 편집. 프론트매터 + 마크다운 본문:

```markdown
---
id: Q0042
topic_id: "2.6.2"
difficulty: 상
answer_index: 1
syllabus_ref: KDATA 출제기준 2과목 2.6.2
generated_by: qwen2.5:7b
modified_by: human          ← 사람이 손댄 표시 (선택)
modified_at: 2026-05-14
---

## 문제
다음 SQL의 결과로 옳은 것은?

![ERD](images/Q0042/erd.png)         ← 이미지 임베드

## 보기
1. 보기 1
2. 보기 2 (정답)
3. 보기 3
4. 보기 4

## 해설
…

## SQL
```sql
SELECT …
```
```

이미지는 `data/questions/images/Q0042/*.png`. 슬라이드에 자동 임베드.

### PHASE 4 — 멀티미디어 산출 (자동)

| 단계 | 명령 | 도구 | 시간/문항 |
|---|---|---|---|
| 6. 슬라이드 | `exambook render` | Marp + Apple 테마 | 2초 |
| 7. 음성 | `exambook tts` | VoiceWright | 3초 |
| 8. 영상 | `exambook video` | ffmpeg + NVENC | 5초 |

전부 idempotent — `mtime` 비교로 변경된 것만 재생성.

### PHASE 5 — 부분 재빌드

```bash
exambook rebuild Q0042                 # 그 문항만 → 약 10초
exambook rebuild Q0001 Q0042           # 명시한 문항들만
exambook rebuild                       # 변경된 모든 MD 자동 재빌드
exambook rebuild --force               # 전체 강제
```

---

## 시간 예상 (50문항, RTX 4070)

| 단계 | 시간 |
|---|---|
| 첫 빌드 전체 | 약 50-90분 |
| 재빌드 (1문항) | 약 10초 |
| 재빌드 (mtime 변경 없음) | 약 5초 |

---

## 저작권 가드레일 (Track A vs Track B)

| 트랙 | 입력 | 출력 위치 | 배포 가능? |
|---|---|---|---|
| **Track B** (배포용) | KDATA syllabus + `topic_map.json` 추상 통계만 | `data/questions/Q####.md` | ✓ |
| **Track A** (개인학습용 변형) | 원본 OCR 텍스트 + 변형 지시 | `data/private/variants.json` | ✗ |

- Track B 프롬프트는 원본 OCR 텍스트를 **절대 포함하지 않는다.**
- `tests/derivative_check.py` 가 한국어 sentence-transformer cosine similarity 로
  Track B 문항 vs OCR 원문 비교. **0.75 이상이면 자동 폐기.**
- Track A 결과물은 `.gitignore` + 코드 레벨 차단으로 Stage 5~7 입력 금지.

---

## 디자인 결정 노트

- **EXAONE 미사용**: 비상업 라이선스 제약. 한국어 표현이 약간 떨어져도 Apache-2.0 Qwen2.5 선택.
- **Qwen2.5-14B 미사용**: Q4 ~9GB 가 8GB VRAM에 안 들어가 CPU offload → 처리량 폭락.
- **PaddleOCR 미사용**: Qwen2.5-VL이 표·SQL 인식이 더 좋고, 후속 단계가 모두 LLM 호출이라 비전 LLM 단일 사용이 깔끔.
- **Marp 채택**: reveal.js 대비 `.md` 1개 → PNG 일관 export 가능. Python subprocess 호출 쉬움.
- **NVENC**: RTX 4070 하드웨어 인코딩, libx264 대비 ~10× 빠름.
- **테마 교체**: `themes/apple_style.css` 가 기본. 시험지 느낌 원하면 `pipeline.yaml`의
  `paths.marp_theme` 을 `themes/sqld_exam.css` 로 변경. 자체 디자인 .css 도 같은 자리에 두고 경로만 바꿈.

---

## 설치 (재참고용)

```bash
winget install Gyan.FFmpeg
winget install oschwartz10612.Poppler
npm install -g @marp-team/marp-cli
ollama pull qwen2.5:7b
ollama pull qwen2.5vl:7b

git clone https://github.com/leedonwoo2827-ship-it/voicewright tools\voicewright
cd tools\voicewright
.\.venv\Scripts\python.exe -m pip install -e ".[gpu]"
git lfs install && git clone https://huggingface.co/Supertone/supertonic-2 assets

# 프로젝트 venv
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```
