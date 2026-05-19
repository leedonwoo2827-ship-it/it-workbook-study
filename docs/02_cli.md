# Exambook CLI 가이드

다른 선생님들도 사용하실 수 있도록 정리한 CLI 명령 안내서입니다.

## 활성화

```bash
cd d:\00work\260514-exambook
.venv\Scripts\activate
```

또는 매번 풀 경로:

```bash
.venv\Scripts\python.exe -m exambook.cli <command>
```

## 명령 목록

| 명령 | 설명 |
|---|---|
| `exambook doctor` | 도구·모델 설치 상태 점검 |
| `exambook ingest` | `_assets/*.pdf` → 페이지 PNG |
| `exambook ocr` | 페이지 PNG → `data/ocr/*.json` (Qwen2.5-VL) |
| `exambook topics` | OCR → `data/analysis/topic_map.json` (추상 통계) |
| `exambook generate --total 50` | Track B 신규문항 50개 생성 → `data/questions/Q####.md` |
| `exambook variants` | ⚠ Track A 변형(개인학습용, 배포 금지) |
| `exambook check` | 의무 게이트: derivative cosine similarity 검사 |
| `exambook render` | MD → Marp 슬라이드 PNG (idempotent) |
| `exambook tts` | MD → wav (VoiceWright, idempotent) |
| `exambook video` | PNG + wav → MP4 (ffmpeg NVENC, idempotent) |
| `exambook rebuild [QID...]` | 부분 재빌드 (특정 문항만) |
| `exambook run-all --total 50` | 1~8 단계 전체 자동 실행 |
| `exambook list` | 현재 문항 목록 표시 |

## 명령별 상세

### `doctor`

```bash
exambook doctor
```

ffmpeg, pdftoppm, marp, ollama, voicewright 설치 상태와 Ollama 모델 다운로드 상태를 표로 보여줍니다.
모두 OK 가 떠야 다음 단계 진행 가능.

### `ingest`

```bash
exambook ingest
```

`_assets/` 안의 모든 PDF를 페이지별 300dpi PNG로 변환해 `data/raw_pages/<source>/page_001.png` 형태로 저장.
이미 변환된 PDF는 자동 스킵.

### `ocr`

```bash
exambook ocr
```

`data/raw_pages/` 각 페이지 PNG를 Qwen2.5-VL로 OCR. 한 페이지당 약 30초 (RTX 4070).
결과는 `data/ocr/<source>.json` (블록 단위 구조화 JSON).
2단 레이아웃과 페이지 넘김 처리는 프롬프트에 지시되어 있음.

### `topics`

```bash
exambook topics
```

OCR 결과를 Qwen2.5-7B로 분석해 **카테고리·빈도·난이도·함정 테마 같은 추상 통계만** 추출.
결과는 `data/analysis/topic_map.json`. **원문 텍스트 조각은 포함되지 않음** (저작권 가드레일).

### `generate`

```bash
exambook generate --total 50                  # 1회분 50문항 → Q1-01..Q1-50
exambook generate --total 200 --rounds 4      # 4회분 50문항씩 → Q1-01..Q4-50
exambook generate --total 100 --rounds 2 --seed 42
```

KDATA 공개 출제기준(`data/syllabus/kdata_sqld.yaml`)과 `topic_map.json` 추상 통계만 입력으로
신규 4지선다 문항을 생성. self-critique 자체검증 통과한 것만 `data/questions/Q{round}-{idx}.md`로 저장.

- **회차 ID 포맷**: `Q{round}-{round_idx:02d}` 예: `Q1-01`, `Q3-27`, `Q4-50`
- frontmatter 에 `round`, `round_idx` 필드 저장됨
- 1과목(데이터 모델링) : 2과목(SQL) = 1 : 4 비율 자동 적용 (회차마다 동일)
- 회차별로 다른 시드 사용 → 회차마다 다른 문항
- `--seed` 로 전체 재현성 확보
- 폐기(self-critique reject)된 자리는 비어둠 — 회차당 50문항 목표지만 실제 45-50개 정도 떨어질 수 있음

### 회차 ID → VoiceWright chapter 매핑

| 문항 ID | chapter (wav 디렉토리) | 영상 파일 |
|---|---|---|
| `Q1-01` ~ `Q1-50` | `ch01` ~ `ch50` | `Q1-01.mp4` ~ |
| `Q2-01` ~ `Q2-50` | `ch51` ~ `ch100` | |
| `Q3-01` ~ `Q3-50` | `ch101` ~ `ch150` | |
| `Q4-01` ~ `Q4-50` | `ch151` ~ `ch200` | ~ `Q4-50.mp4` |

음성 파일은 `build/audio/ch{NN}/audio/ch{NN}_{scene:02d}_narration.wav`,
영상은 `build/videos/Q{round}-{idx}.mp4`.

### `check`

```bash
exambook check
```

⚠ **배포 전 의무 게이트.** 모든 Track B 문항을 OCR 원문과 한국어 sentence-transformer cosine similarity 로 비교.
0.75 이상이면 자동 폐기 표시. 위반 0건이어야 다음 단계 진행 가능.

### `render`

```bash
exambook render                   # 전체 (변경된 것만 자동감지)
exambook render --force           # 전체 강제 재렌더
```

`data/questions/Q####.md` → `build/slides_md/Q####.md` → `build/slides_png/Q####.001.png`, `Q####.002.png`.
한 문항당 2장 (문제 슬라이드 + 정답/해설 슬라이드).
테마는 `config/pipeline.yaml` 의 `paths.marp_theme` 으로 변경 가능 (`apple_style.css` 기본).

### `tts`

```bash
exambook tts                      # 전체 (변경된 것만)
exambook tts --force
```

각 문항당 2개 wav:
- `Q####_stem.wav` — "1번 문제. (본문) 보기. ①번. ... ②번. ..."
- `Q####_exp.wav` — "정답은 ③번입니다. 해설을 설명해 드리겠습니다. ..."

`config/voice_map.yaml` 에서 음성·속도 조정. SQL 키워드는 `pronunciation` 사전에 따라 한글 발음으로 치환.

### `video`

```bash
exambook video                    # 전체 (변경된 것만)
exambook video --force
```

각 문항별 mp4 + `build/videos/final.mp4` 전체 합본.
ffmpeg `h264_nvenc` 로 RTX 4070 하드웨어 인코딩.

### `rebuild`

```bash
exambook rebuild Q0042                    # Q0042 한 문항만 재빌드 (slides → audio → video)
exambook rebuild Q0001 Q0042 Q0100        # 명시한 문항들만
exambook rebuild                          # 변경된 모든 MD 자동 감지
exambook rebuild --force                  # 전체 강제 재빌드
exambook rebuild Q0042 --skip-video       # 영상 제외하고 슬라이드+음성까지만
```

mtime 비교로 idempotent. 입력 MD가 출력 mp4 보다 새로우면만 재생성.

### `list`

```bash
exambook list
```

`data/questions/` 안의 모든 Q####.md 를 id·topic·난이도·정답번호로 표 출력.

### `variants` (⚠ Track A — 배포 금지)

```bash
exambook variants                       # 모든 OCR 청크에서 변형 생성
exambook variants --max-chunks 5        # 빠른 테스트
```

원본 OCR 텍스트를 변형해 개인학습용 문항 생성. `data/private/variants.json` 에만 저장됨.
**절대 배포·외부 공유 금지.**

### `run-all`

```bash
exambook run-all --total 50              # 표준 실행
exambook run-all --total 100 --skip-check # derivative 검사 생략
```

1(ingest) → 2(ocr) → 3(topics) → 4b(generate) → 5(check) → 6(render) → 7(tts) → 8(video)
순차 자동 실행. derivative check 실패 시 자동 중단.

## 흔한 패턴

### 처음 전체 빌드

```bash
exambook doctor
exambook run-all --total 50
# 산출물: build/videos/final.mp4
```

### 한 문항만 손보고 영상까지 갱신

```bash
# data/questions/Q0042.md 편집 (VS Code 등)
exambook rebuild Q0042
# 약 10초 안에 build/videos/Q0042.mp4 갱신
```

### 모든 슬라이드 테마만 바꾸기

```bash
# config/pipeline.yaml 의 paths.marp_theme 을 새 css 로 교체
exambook render --force
exambook video --force
```

### 정답 발음 사전 보강 후 음성만 재생성

```bash
# config/voice_map.yaml 의 pronunciation 섹션 수정
exambook tts --force
exambook video --force
```

## 문제 해결

- **`doctor` 에서 MISSING**: 해당 도구 설치 후 새 터미널에서 재시도. PATH 갱신 안 됐을 수 있음.
- **GPU 메모리 부족**: `ollama ps` 로 다른 모델이 상주 중인지 확인 후 `ollama stop <model>`.
- **Marp PNG 안 나옴**: 처음 1회 Chromium 자동 다운로드 (~150MB) 1-2분 대기.
- **VoiceWright 음성 어색**: `config/voice_map.yaml` 의 `pronunciation` 사전에 키워드 추가.
- **derivative_check 실패**: 해당 문항 ID 의 MD 를 사람이 재작성하거나 `exambook generate --seed <다른값>` 으로 재생성.
