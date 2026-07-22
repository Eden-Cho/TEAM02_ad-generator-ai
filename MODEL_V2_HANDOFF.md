# model-v2 인계 문서 (박민성 / 모델 파이프라인)

> 브랜치 `feature/model-v2-handoff` · 기준 커밋 `da96608` · 팀 main `ea3abbb` 기준으로 작성.
> **이 브랜치는 "운영 완성본"이 아니다.** 최신 모델 구현 + 연결 계약 + 평가 자료를 팀에 넘기는 것이
> 목적이며, 실제 생성은 **기본적으로 차단**돼 있다.

---

## 1. 담당 범위

| 구분 | 담당 | 내용 |
|---|---|---|
| 모델 설계 | 이쪽(모델) | 아키타입·씬 템플릿·이미지 슬롯/경로 결정(composite·creative_edit·t2i·passthrough) |
| 생성 | 이쪽(모델) | `run_pipeline` — 슬롯 컨텍스트(LLM) → 이미지 플랜 → 컷 생성 → 상세페이지 조립 → 썸네일 → GEO |
| 평가 | 이쪽(모델) | 제품 보존 측정(템플릿 매칭), 결함 판정, 샘플 패키지(38장) |
| 연결 계약 | **공동** | 아래 4절의 endpoint/응답 스키마 — 백엔드·프론트가 이 계약에 붙인다 |
| 서비스 운영 | 백엔드/프론트 | 인증·rate limit·ingress·배포·모니터링 (이 브랜치 범위 밖) |

---

## 2. 기존 팀 코드와 model-v2 구조 차이

**팀 기존 파일은 한 줄도 바꾸지 않았다.** 팀 main(`ea3abbb`) 대비 이 브랜치는 **추가 50파일, 수정 0파일**이다.

| | 팀 기존 | model-v2 (이번 추가) |
|---|---|---|
| 진입점 | `backend/main.py` (`main:app`) | `backend/main_v2.py` (`main_v2:app`) |
| 포트 | 8000 | **8010** |
| 모델 트리 | `model/` | `model_v2/` (팀 모델 `ae9cfc8` 시점을 벤더링, 36파일) |
| 오케스트레이터 | `app/services/pipeline_service.py` | `app/services/model_v2_pipeline.py` |
| 어댑터 | — | `app/services/model_v2_service.py` |
| 라우터 | `app/api/v1/generate.py` (`/api/...`) | `app/api/v1/model_v2.py` (`/api/model-v2/...`) |
| 프론트 | `frontend/app.py` (8501) | `frontend/model_v2_app.py`, `frontend/model_v2_demo_app.py` |

즉 **팀 서비스와 model-v2는 완전히 병렬**로 뜬다. 팀 8000번은 그대로 두고, model-v2만 8010번에서
띄워 비교·검증할 수 있다.

---

## 3. 왜 별도 worker가 필요한가 (import 충돌 근거)

팀 `model/`과 벤더링한 `model_v2/`는 **최상위 패키지명이 겹친다** — 양쪽 모두
`baseline` · `composer` · `geo` · `evaluation` 을 최상위로 노출한다.

파이썬은 한 인터프리터에서 같은 최상위 패키지명을 **한 트리만** 바인딩한다. 따라서
한 프로세스에 팀 모델과 model-v2를 동시에 올릴 수 없다. `sys.path` 순서로 바꿔치기하면
**먼저 import된 쪽이 이겨서** 어느 쪽이 살아있는지가 import 순서에 좌우된다(디버깅 불가능한 형태).

→ 해결: **별도 worker**. `main_v2.py`가 `model_v2/`를 `sys.path` 맨 앞에 두고 자기 프로세스에서만
`baseline` 등을 model_v2로 해석한다. 팀 `main:app`은 손대지 않았으므로 계속 팀 `model/`을 쓴다.

이 격리는 **독립 subprocess 회귀 테스트로 고정**돼 있다
(`tests/test_model_v2_isolation.py`): 팀 worker는 `baseline.__file__`이 `/model/baseline/` 아래,
v2 worker는 `/model_v2/baseline/` 아래임을 각각 별도 프로세스에서 resolve된 절대경로로 확인한다.

---

## 4. 연결 계약 (endpoint / 응답)

worker: `uvicorn main_v2:app --host 127.0.0.1 --port 8010` (backend/ 디렉터리에서 실행)

### 4.1 헬스

`GET /` · `GET /health` → `{"status": "ok", "service": "detail-page-generator-v2"}`

### 4.2 `GET /api/model-v2/options` — 폼 옵션 (무과금)

```json
{ "style_dimensions": [ { "id": "...", "label": "...", "type": "scale|choice",
                          "choices": [...], "default": ... } ],
  "categories": ["가전·TV", "..."],
  "export_targets": [ { "name": "...", "width": 860 } ] }
```

### 4.3 `POST /api/model-v2/preview` — **무과금 미리보기 (유료 호출 0회)**

요청: `multipart/form-data`
- `req_json` (필수, JSON **객체** 문자열)
- `product_files` (1장 이상), `app_files` (선택)

응답 200:
```json
{ "presentation_mode": "preserve|natural",
  "product_form": "unknown|solid_stick|cream|liquid|powder|solid",
  "roles": ["hero", "build", "connectivity", "lifestyle"],
  "cuts": [ { "role": "hero", "intended_path": "composite|creative_edit|t2i|passthrough",
              "angle": "정면", "scene_id": "white_studio" } ],
  "expected_calls": { "images_generate": 3, "images_edit": 0,
                      "passthrough": 1, "llm_logical_max": 5 } }
```

**preview는 LLM·이미지 API를 호출하지 않는다.** 경로 결정·씬 선택은 순수 함수라 비용이 없다.
`expected_calls`는 실제 생성 시 발생할 호출 수의 사전 고지용이다(`llm_logical_max`는 논리 상한).

### 4.4 `POST /api/model-v2/generate-detail-page` — **유료 (기본 차단)**

요청: `multipart/form-data` — `req_json`, `theme_name`(기본 `"light"`), `product_files`, `app_files`(선택)

응답 200:
```json
{ "detail_page": "<base64 PNG>", "main": "<base64 JPEG>",
  "gallery": ["<base64 JPEG>", "..."], "seconds": 158.2,
  "geo_html": "<html>...", "structured_data": [ ... ], "faq": [ {"q":"","a":""} ],
  "warnings": ["..."], "trace": { "generations": [ ... ] } }
```
- `evaluation` 은 **선택 필드** — `MODEL_V2_SCORING`이 켜졌을 때만 포함(팀 scorer 결과 무손실 전달).
- **기본 상태에서는 이 endpoint가 503으로 차단된다** (6절 참조).

### 4.5 오류 응답

| 상황 | 코드 | 응답 |
|---|---|---|
| 유료 비활성(기본) | 503 | 고정 문구 |
| JSON/필드 형식 오류 | 400 | 고정 문구 |
| 업로드 수·크기 초과 | 400 | 고정 문구 |
| 파이프라인 실패 | 500 | 고정 문구 |

오류 응답·로그·trace에 **API 키·프롬프트 원문·예외 원문·내부 경로를 넣지 않는다.**

### 4.6 환경변수

| 변수 | 기본값 | 용도 |
|---|---|---|
| `OPENAI_API_KEY` | (없음) | 워커 프로세스 env로만 주입. 없으면 실제 생성 단계에서 실패(preview는 동작) |
| `MODEL_V2_PAID_ENABLED` | **비활성** | **정확히 `1`** 일 때만 유료 생성 허용 |
| `MODEL_V2_BACKEND_URL` | `http://127.0.0.1:8010` | 테스트 UI가 바라볼 워커 주소 |
| `MODEL_V2_DEMO_ASSET_DIR` | (없음) | 데모 모드 샘플 패키지 경로 |
| `MODEL_V2_SCORING` | 비활성 | 켜면 팀 scorer 후처리 → `evaluation` 필드 |
| `MAX_UPLOAD_FILES` | 12 (상한 1000) | 업로드 파일 수 |
| `MAX_UPLOAD_MB` | 15 (상한 1024) | 파일당 크기 |

`model_v2/baseline/config.py`는 `load_dotenv(model_v2/.env, override=False)` — **프로세스 env가
`.env`보다 우선**한다. 저장소에 `model_v2/.env`는 없다(`.env.example`만).

---

## 5. API 없는 데모 실행법 (발표·시연용)

워커도, API 키도, 네트워크도 필요 없다. 사전 생성 샘플만 보여준다.

```bash
export MODEL_V2_DEMO_ASSET_DIR=/path/to/model_v2_handoff_samples_20260722
streamlit run frontend/model_v2_demo_app.py
```

- 데모 앱은 **HTTP 클라이언트를 import하지 않는다** → generate는 물론 preview도 **호출할 코드가 없다**
  (구조적 0회, `ast` 기반 import 검사로 회귀 고정).
- 화면 전체에 `사전 생성 샘플 · 실제 API 호출 없음` 표시.
- 탭: **preserve/natural 비교**(정상 결과만) / **결함 개선 비교** / **패키지 정보**.
- `ERROR_DO_NOT_SHIP` 결과는 **기본 화면에서 제외**되고 결함 비교 탭의 접힌 영역에서만 보인다.
- 수정 단일 컷은 **"전체 상세페이지 재생성 결과가 아님"** 을 명시한다.

---

## 6. 실제 생성은 기본 차단 (`MODEL_V2_PAID_ENABLED`)

```bash
export MODEL_V2_PAID_ENABLED=1   # 이걸 명시적으로 켜야만 유료 생성이 열린다
```

- **정확히 `1`** 만 활성. `true`·`yes`·`on`·`0`·빈 값·오타는 전부 비활성(실수로 켜지지 않는다).
- 비활성일 때 `POST /api/model-v2/generate-detail-page`는 **순수 ASGI 미들웨어**가
  **body를 읽기 전에** 503으로 끊는다 → **multipart 파싱·임시파일 저장·`run_pipeline`·LLM·이미지 API에
  도달하지 않는다**(엔드포인트 진입 자체가 없음).
- trailing slash·쿼리스트링·URL 인코딩(`%2D`)·점 세그먼트 변형으로 **우회되지 않는다**(회귀 테스트 고정).
- `preview`·`options`·`/health`는 무과금이라 스위치와 무관하게 동작한다.

> ⚠️ 이 스위치는 **비용 사고 방지용이지 접근 제어가 아니다.** 워커 자체에 인증이 없으므로 기본
> 바인딩은 `127.0.0.1`이다. 외부 노출은 앞단 인증·rate limit·body 상한을 갖춘 프록시를 통해야 한다.

---

## 7. 테스트

무과금이며 실제 LLM·이미지 API·외부 HTTP·모델 다운로드가 **0회**다(전부 mock).

```bash
cd <repo>
python -m unittest tests.test_model_v2 tests.test_model_v2_isolation \
                   tests.test_model_v2_ui tests.test_model_v2_app tests.test_model_v2_demo
```

**현재 통과 수 (Streamlit 1.59.0 기준): 114개 전부 통과**

| 모듈 | 개수 | 내용 |
|---|---|---|
| `test_model_v2` | 16 | options·preview 무과금, generate 응답 계약, scorer 인자 계약, 업로드 상한, **유료 폐쇄 스위치** |
| `test_model_v2_isolation` | 3 | 팀/v2 worker를 **독립 subprocess**로 띄워 baseline 출처 검증 + 팀 endpoint mock 회귀 + 팀 파일 바이트 동일 |
| `test_model_v2_ui` | 27 | 승인 게이트(1회용), 응답 폐쇄 검증, 멀티파트 보존, 오류 비노출 |
| `test_model_v2_app` | 9 | 실제 Streamlit app 배선(AppTest) |
| `test_model_v2_demo` | 59 | manifest 폐쇄 계약(무결성·스키마·조합·경로/중복) + 데모 app 배선 |

**Streamlit 1.51.0** 에서도 확인함: 데모+app 모듈 **68개 실행, 통과(6개 skip)**.
skip은 그 버전 AppTest가 `file_uploader.upload`·image 엘리먼트를 지원하지 않는 항목뿐이며,
**사유를 명시해 skip**한다(조용한 전체 skip 아님). 팀 `requirements`의 `streamlit>=1.30`과 호환된다.

> 팀 저장소(`upstream/main`)에는 **테스트 파일이 없다.** 팀 기존 endpoint의 회귀는
> `test_model_v2_isolation.py`가 팀 `main`을 별도 subprocess로 import해
> `/api/generate-detail-page`를 mock으로 호출(200)하는 방식으로 커버한다.

---

## 8. 샘플 패키지 전달

저장소에는 **이미지·ZIP을 넣지 않았다**(용량·리뷰 부담). 별도 전달한다.

| 항목 | 값 |
|---|---|
| 파일명 | `model_v2_handoff_samples_20260722.zip` |
| 크기 | 26,601,320 bytes |
| 내용 | 40개 항목(이미지 38 + `README.md` + `manifest.json`) |
| SHA-256 | `28688caadf17c1fd950fe60b6c129b1c0820bb6143186587a320e54bc7d300c4` |

- 구성: 정상 대표 결과 28장 + **오류 참고 6장** + 결함 수정 전/후 단일 컷 4장(2쌍), 이미지 합계 26,882,856 bytes.
- 제품 × 모드: 사과(preserve/natural) · 썬스틱(preserve/natural) · Mac Mini(preserve/natural).
- 전달 방법: 팀 드라이브/사내 스토리지 업로드 후 링크 공유. **받는 쪽에서 SHA-256을 대조**할 것.
- 데모 UI는 이 패키지의 `manifest.json`을 단일 기준으로 **폐쇄 검증**한다(해시·바이트·해상도·형식·
  집계·스키마·필드 조합·경로 이탈/심볼릭 링크/중복). 하나라도 어긋나면 패키지 전체를 거부한다.

---

## 9. 알려진 한계 · 운영 사용 금지 결과

### 9.1 운영 사용 금지

- **썬스틱 natural 전체 세트** (`sunstick_natural_ERROR_DO_NOT_SHIP/`) — 고체 스틱 제품인데
  texture 컷에 **크림 스와치**가 렌더됐다(제형 허위표시 위험). **오류 비교용 전용.**
- **수정본(v2) 단일 컷** — 결함이 고쳐진 것은 **그 한 컷**이다. 같은 제품의 상세페이지 전체는
  수정 전 상태이며, 수정 반영 전체 재생성본은 아직 없다.

### 9.2 모델 한계

1. **실측 표본 1건** — tech 아키타입·preserve·Mac Mini 1개 제품만 전체 E2E 실측(158.2초, 이미지 generate 3회).
   다른 아키타입·배경은 무과금 테스트로만 커버.
2. **natural 모드 정확도 비보장** — 제품을 재렌더하므로 로고·포트·비율이 실물과 달라질 수 있다.
   프롬프트 지시일 뿐 결과 보장이 아니다.
3. **composite 구조 한계** — 제품이 항상 최상위 레이어라 **가림(occlusion)·손 상호작용이 원천 불가**.
   하단 부유감이 미세하게 남는 표본이 있다.
4. **누끼 경계 아티팩트** — preserve 컷 일부에서 rembg 경계가 보인다.
5. **손에 들린 제품 사진 리스크(미해결)** — 입력이 손에 든 컷이면 팔뚝까지 누끼로 잡혀 어색하게 합성된다.
   입력 사진 유형 판별이 필요하다.
6. **성능 비SLA** — 158초는 단일 실측. 컷 수·모델 지연에 비례해 변동한다.
7. **trace 일부 미계측** — `geometry`·`text_placement`는 아직 `null`.

### 9.3 이 브랜치의 한계

- 데모 UI의 무결성 검증은 **로드 시점 1회**다(이후 파일 교체는 재검증하지 않음).
- 경로 변형 차단은 클라이언트/서버가 URL을 정규화해 ASGI `path`에 넘긴다는 전제에 의존한다.
  정규화하지 않는 프록시를 앞단에 두면 별도 확인이 필요하다.
- AppTest는 모든 탭을 렌더하므로 "오류본이 기본 탭에 없음"은 위치 기반으로 단언하지 못한다
  (단위 테스트로 보장).

---

## 10. 백엔드·프론트 담당자가 결정할 후속 항목

1. **🔴 [보안·선행] `backend/.env`가 저장소에 커밋돼 있다.** 우리 브랜치가 추가한 것이 아니라
   팀 커밋 `a55fcb7`에서 들어왔고 **팀 main에 그대로 있다.** 저장소가 공개라면 **키 폐기·재발급 +
   히스토리 정리 + `.gitignore` 보강**이 필요하다. 현재 `.gitignore`는 `model/.env`와
   `backend/model_hf/.env`만 무시하고 **`backend/.env`는 무시하지 않는다.** 조치 주체는 백엔드 담당.
2. **통합 형태 결정** — model-v2를 (a) 별도 worker로 계속 둘지, (b) 팀 모델을 `model_v2` 시점으로
   올려 단일 worker로 합칠지. (b)를 택하면 이 브랜치의 벤더 트리는 제거 대상이다.
3. **유료 스위치 운영값** — 어느 환경에서 `MODEL_V2_PAID_ENABLED=1`을 켤지, 비용 상한·승인 절차.
4. **접근 제어** — 워커에 인증이 없다. 프록시 앞단의 인증·rate limit·body 상한 설계.
5. **프론트 통합** — 팀 `frontend/app.py`에 model-v2 경로를 붙일지, 테스트 UI를 별도로 유지할지.
6. **scorer 연동** — `MODEL_V2_SCORING` 기본값과 `evaluation` 필드를 UI에 노출할지.
7. **샘플 자산 보관 위치** — 이미지·ZIP은 저장소 밖이다. 팀 스토리지 경로·보존 기간 결정.
8. **배포 구성** — 현재 Docker 구성은 팀 8000/8501 기준이며 **8010 워커는 포함돼 있지 않다.**
   컨테이너화 여부는 배포 담당 결정.
