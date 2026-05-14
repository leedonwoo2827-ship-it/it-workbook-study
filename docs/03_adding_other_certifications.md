# 다른 자격증 추가하기

이 리포는 현재 **SQLD** 한 종목 기준으로 구성되어 있습니다. 새 자격증(예: ADP, 정보처리기사, PMS, 빅데이터분석기사 등)을 추가하는 방법은 **두 가지 전략**이 있습니다.

---

## 전략 A — 새 자격증 = 새 리포 (현재 구조 그대로 복제)

이 리포가 SQLD 전용이고, 자격증마다 별도 상품·배포 관리가 필요할 때.

### 절차

1. **GitHub 에서 이 리포를 템플릿으로 복제**

   ```powershell
   gh repo create it-workbook-adp --public --template leedonwoo2827-ship-it/it-workbook-study
   cd ..
   gh repo clone leedonwoo2827-ship-it/it-workbook-adp
   cd it-workbook-adp
   ```

   또는 GitHub 웹에서 "Use this template" 버튼 클릭.

2. **새 자격증의 출제기준 YAML 작성**

   `data/syllabus/kdata_sqld.yaml` 을 참고해 새 파일 작성:

   ```powershell
   copy data\syllabus\kdata_sqld.yaml data\syllabus\kdata_adp.yaml
   notepad data\syllabus\kdata_adp.yaml
   ```

   필드 구조는 그대로 두고, `subject`, `subjects/chapters/topics` 내용만 해당 자격증의 공식 출제기준에 맞춰 바꾸세요. KDATA 자격검정 사이트(`https://www.dataq.or.kr`)나 한국산업인력공단의 공개 출제기준 PDF를 그대로 옮기면 됩니다.

3. **pipeline.yaml 의 syllabus 경로 교체**

   `config/pipeline.yaml`:
   ```yaml
   project:
     name: ADP Exambook
     subject: ADP

   paths:
     syllabus: data/syllabus/kdata_adp.yaml
   ```

4. **(선택) 자격증별 슬라이드 테마**

   `themes/adp_style.css` 새로 만들고 `paths.marp_theme` 을 그것으로 변경. SQLD 와 다른 컬러·로고로 차별화.

5. **(선택) 발음 사전 보강**

   `config/voice_map.yaml` 의 `pronunciation` 에 자격증별 전문 용어 추가 (예: ADP 면 `R-squared` → `알스퀘어드`).

6. **이전 자격증의 문항 삭제 (충돌 방지)**

   ```powershell
   del data\questions\Q*.md
   del data\questions\_index.json -ErrorAction SilentlyContinue
   ```

7. **`_assets/` 에 새 자격증 PDF 넣고 실행**

   ```powershell
   exambook doctor
   exambook run-all --total 50
   ```

### 장단점

| 장점 | 단점 |
|---|---|
| 자격증별 독립 릴리스·배포 가능 | 파이프라인 코드 수정 시 N개 리포 동기화 필요 |
| 외부 협업자에게 자격증별 권한 분리 | 비슷한 코드가 여러 리포에 중복 |
| 상품화·라이선스 분리 용이 | |

---

## 전략 B — 1리포 다자격증 (코드 리팩토링 필요)

같은 강사가 SQLD·ADP·정보처리기사·기타 여러 자격증을 한 곳에서 운영할 때.

### 변경할 부분

`pipeline.yaml` 을 자격증별 프로파일로 분리:

```yaml
# config/pipeline.yaml
project:
  default_cert: sqld

# 자격증 공통 설정만 여기 유지 (models, video, render)
models: { text: qwen2.5:7b, vision: qwen2.5vl:7b, embedding: ... }
render: { dpi: 300, ... }
video: { encoder: h264_nvenc, ... }
```

자격증별 설정을 별도 파일로:
```
config/certs/
├── sqld.yaml         # syllabus, marp_theme, voice_map 등 cert-specific
├── adp.yaml
└── jeongcheogi.yaml
```

데이터 디렉터리도 자격증별로:
```
data/
├── syllabus/{sqld,adp,...}.yaml
├── ocr/{sqld,adp}/...
├── analysis/{sqld,adp}/topic_map.json
└── questions/{sqld,adp}/Q####.md
```

CLI에 `--cert` 글로벌 옵션 추가:
```powershell
exambook --cert sqld run-all --total 50
exambook --cert adp generate --total 30
exambook --cert sqld rebuild Q0042
```

### 코드 변경 분량 (예상)

- `src/exambook/config.py` 에 `current_cert()` 헬퍼 추가
- 모든 stage 모듈의 경로를 `paths(cert)` 로 파라미터화
- `cli.py` 에 `--cert` global option (typer Context)
- 약 4-6 시간 작업

지금 시점(SQLD 1종목, MD 1개만 있음) 이 가장 마이그레이션 비용이 낮습니다. 자격증이 3개 이상 될 가능성이 있으면 이 시점에 전환 권장.

---

## 의사결정 가이드

| 상황 | 추천 |
|---|---|
| 1-2개 자격증만 다룰 예정 | **A** (지금 그대로) |
| 5개 이상 자격증, 같은 강사가 주 사용자 | **B** (지금 리팩토링) |
| 자격증마다 외부 강사·구매자에게 별도 라이선스로 배포 | **A** |
| 파이프라인 코드 자체를 사내·공동 자산으로 운영 | **B** |

---

## 자격증별 권장 출제기준 출처 (공개 자료)

- **SQLD / SQLP** — KDATA 데이터자격검정 [https://www.dataq.or.kr](https://www.dataq.or.kr) 의 "출제기준" PDF
- **ADsP / ADP** — KDATA 같은 사이트 의 "출제기준"
- **빅데이터분석기사** — 한국데이터산업진흥원 출제기준
- **정보처리기사 / 정보처리산업기사** — 한국산업인력공단 q-net 의 출제기준
- **PMP / PMS** — PMI 공식 ECO(Examination Content Outline) — 영문이라 별도 한국어 번역 큐레이션 필요
- **AWS / Azure / GCP 자격증** — 각사 공식 Exam Guide PDF (영문, Track B 한국화 큐레이션 작업 필요)

**주의:** 출제기준 자체는 공개 자료지만, 기출문항·해설지는 출판사 저작권 보호 대상입니다. Track B 신규생성은 **출제기준만** 입력으로 받습니다(이 리포의 저작권 가드레일).

---

## 비SQL 자격증 추가 시 추가 고려사항

### 코드 비중이 낮은 자격증 (PMP, ADsP 등)
- `sql_snippet` 필드 사용 안 함 — `null` 로 두면 됨
- 슬라이드 테마에서 SQL 코드블록 스타일은 그대로 둬도 무방 (안 쓰이면 안 나옴)

### 영문 자격증 (AWS/PMP)
- 출제기준 키워드를 영문 그대로 저장 + `prompts/question_generate.ko.txt` 에 "영문 자격증 한국어 번역 출제" 지시 추가
- 발음 사전(`voice_map.yaml`) 에 영문 약어 대량 추가 필요 (S3 → 에스쓰리, EC2 → 이씨투, IAM → 아이엠 등)

### 표·다이어그램 비중 높은 자격증 (정처기 — 자료구조·다이어그램 다수)
- `data/questions/images/Q####/` 에 다이어그램 PNG 미리 만들어 임베드
- 또는 mermaid 코드 블록으로 직접 작성 (Marp 가 렌더)
