# model-v2 테스트 UI (별도 Streamlit)

팀 `frontend/app.py`(기존 백엔드용)와 **무관한 병렬 추가**다. model-v2 전용 워커
(`main_v2:app`, 포트 **8010**)의 `/api/model-v2/{options,preview,generate-detail-page}`만 사용한다.

두 가지 화면이 있다:

| 화면 | 파일 | 워커 | API 호출 |
|---|---|---|---|
| 테스트 UI (실사용) | `model_v2_app.py` | 필요 | preview 무과금 / generate 유료 |
| **데모 모드** (발표·테스트) | `model_v2_demo_app.py` | **불필요** | **0회 (구조적으로 불가)** |

## 데모 모드 — 사전 생성 샘플, API 호출 없음

발표·시연·수동 테스트용으로, **미리 생성해 둔 샘플 패키지만 표시**한다. 이 앱은 HTTP 클라이언트를
import하지 않으므로 generate는 물론 preview도 **호출할 코드 자체가 없다**. 워커도 띄울 필요가 없다.

```bash
# 샘플 패키지 경로를 주입(이미지·ZIP은 저장소에 넣지 않는다 — 외부 경로로만 전달)
export MODEL_V2_DEMO_ASSET_DIR=/path/to/model_v2_handoff_samples_20260722
streamlit run frontend/model_v2_demo_app.py
```

- 화면 전체(제목·캡션·사이드바·각 탭)에 **`사전 생성 샘플 · 실제 API 호출 없음`** 을 표시한다.
- 탭 구성: **preserve/natural 비교** (정상 대표 결과만) / **결함 개선 비교** / **패키지 정보**.
- `ERROR_DO_NOT_SHIP`(오류 참고) 결과는 **기본 화면에서 제외**되고, `결함 개선 비교` 탭의
  접힌 영역에서 경고와 함께만 보인다.
- 수정 단일 컷(v2)에는 **"전체 상세페이지 재생성 결과가 아님"** 을 명시한다.
- 패키지는 `manifest.json`을 **단일 기준**으로 **폐쇄 검증**한다. 하나라도 위반이면 **패키지
  전체를 거부**하고, **경로·해시·manifest 값·예외 원문이 없는 고정 문구**만 표시한다.

| 구분 | 검증 내용 |
|---|---|
| 무결성 | `sha256`은 64자리 소문자 hex이며 **실제 파일을 스트리밍 해싱**해 대조 · `bytes`·`image.width/height/format`을 실제 파일과 대조 · `counts.image_files`·`total_bytes`를 실제 집계와 대조 |
| 스키마 | `product`(apple/sunstick/macmini) · `mode`(preserve/natural) · `asset_type`(detail_page/main_thumbnail/gallery_cut/fix_single_cut) · `verdict`(usable_reference/review_required/error_reference_only/fixed_single_cut) · `role`(hero/build/connectivity/lifestyle/ingredient/texture/serving) · `scope`(full_result_set/single_cut_only) · `fix_stage`(before/after) — **허용값만** |
| 빈 값·타입 | `product_label`·`purpose`·`package`·`created` 비어 있지 않은 문자열 · `known_limits` 비어 있지 않은 문자열 리스트 · `warnings`·`verdict_legend` 타입·빈 값 |
| 조합 | fix cut `before`→`scope=single_cut_only`+`verdict=error_reference_only`+`full_page_regenerated=false` · `after`→`fixed_single_cut` · 전체 결과→`full_result_set`, `fix_stage`/`full_page_regenerated` 없음, `fixed_single_cut` 판정 금지 · detail/main은 role 없음, gallery/fix는 role 필수 |
| 경로·중복 | 패키지 **root 자체 심볼릭 링크 거부** · manifest·내부 심볼릭 링크 거부 · 상대경로 강제(절대경로·`..`·백슬래시·`~`) · **동일 상대경로 중복 거부** · **동일 `(product, role, fix_stage)` 수정 컷 중복 거부**(`fix_pairs`는 조용히 덮어쓰지 않는다) |

## 실행

```bash
# 0) 워커가 쓸 OpenAI 키를 **프로세스 환경변수로만** 주입
#    (실제 키는 저장소·문서·명령 기록에 남기지 말 것 — 아래는 placeholder다)
export OPENAI_API_KEY="sk-REPLACE_WITH_YOUR_OWN_KEY"

# 1) model-v2 워커 (포트 8010) — 팀 main:app(8000)과 별개
#    ⚠️ 유료 생성은 기본 차단이다. 실제로 생성하려면 아래를 명시적으로 켜야 한다:
#       export MODEL_V2_PAID_ENABLED=1
cd backend && uvicorn main_v2:app --host 127.0.0.1 --port 8010

# 2) 테스트 UI (별도 Streamlit)
#    worker 주소는 MODEL_V2_BACKEND_URL, 기본 http://127.0.0.1:8010
streamlit run frontend/model_v2_app.py
# 다른 주소면:
MODEL_V2_BACKEND_URL=http://127.0.0.1:8010 streamlit run frontend/model_v2_app.py
```

### 워커 환경변수 로딩 (확인된 동작)

- `model_v2/baseline/config.py`는 `load_dotenv(model_v2/.env, override=False)`로 설정을 읽는다.
  `override=False`이므로 **프로세스 환경변수가 `model_v2/.env`보다 우선**한다.
- 저장소에는 `model_v2/.env`가 **없다**(`model_v2/.env.example`만 있다). 따라서 위처럼 워커 실행
  전에 프로세스 env로 `OPENAI_API_KEY`를 주입해야 한다 — 주입하지 않으면
  `config.OPENAI_API_KEY`가 `None`이라 실제 생성 단계에서 실패한다(preview는 무과금이라 키 없이
  동작). 원한다면 `model_v2/.env`를 만들어 채워도 되지만, 프로세스 env가 우선한다.
- 이 UI(앱)는 키를 **아예 다루지 않는다** — UI·요청 body·오류·trace에 키가 들어가지 않는다.

### 유료 생성 폐쇄 스위치 (`MODEL_V2_PAID_ENABLED`)

워커에는 유료 경로 차단 스위치가 있고 **기본값은 비활성**이다.

- **정확히 `1`** 일 때만 활성화된다. `true`·`yes`·`on`·`0`·빈 값·오타는 전부 **비활성**이라
  실수로 켜지지 않는다.
- 비활성 상태에서 `POST /api/model-v2/generate-detail-page`는 **순수 ASGI 미들웨어**가
  **body를 읽기 전에** 고정 문구 **503**으로 끊는다 → multipart 파싱·임시파일 저장·
  `run_pipeline`·LLM·이미지 API에 **도달하지 않는다**(엔드포인트 진입 자체가 없다).
- trailing slash·쿼리스트링·URL 인코딩(`%2D`)·점 세그먼트 변형도 **유료 실행으로 우회되지 않는다**
  (정규화 후 게이트에 걸려 503, 라우트가 없는 변형은 404). 회귀 테스트로 고정돼 있다.
- `preview`·`options`·`/health`는 무과금이라 스위치와 무관하게 그대로 동작한다.

### 바인딩 주소

기본 실행은 **`127.0.0.1:8010`(로컬 전용)** 이다. `0.0.0.0`은 모든 인터페이스에 노출되므로,
**앞단에 인증·접근 제한(reverse proxy·방화벽·게이트웨이)이 있을 때만** 사용한다. 이 워커 자체에는
토큰 인증이 없다 — 유료 스위치는 비용 사고 방지용이지 접근 제어가 아니다.

## ⚠️ 유료 고지

- **미리보기(preview)는 무과금**이다 — 역할·경로·씬·예상 호출 수만 계산한다.
- **상세페이지 생성은 유료**다 — LLM·이미지 API가 실제로 호출되며, **매 호출마다 재승인**이
  필요하다. "유료 호출을 확인했습니다" 체크는 **1회용**이다 — 생성 시 소비되고, 성공·실패와
  무관하게 다음 호출에는 다시 체크해야 한다(연속 클릭·재실행으로 1회 승인이 2회 생성되지 않음).
- 생성 버튼은 **preview 성공 + 유료 확인 체크**가 모두 있어야 활성화된다.
- 입력·파일·테마가 바뀌면 승인·preview가 무효화되고 **다시 preview**가 필요하다.
- API 키·토큰은 UI·요청 body에 넣지 않는다(워커가 자체 프로세스 환경에서만 사용).

## 구성

- `frontend/model_v2_client.py` — 순수 로직·HTTP 헬퍼(Streamlit 비의존, **단위 테스트 대상**):
  worker 주소 결정, 멀티파트 조립(순서·이름·바이트 보존), 입력 지문, 승인 상태 머신
  (`can_generate`/`attempt_generate` — 승인 1회 소비), 응답 폐쇄 검증(`parse_preview`/
  `parse_generate` — PNG·JPEG 실제 디코딩), 고정 오류 문구(URL·body·경로·예외 원문·Traceback 비노출).
- `frontend/model_v2_app.py` — 화면 구성만(위 헬퍼 호출).
- `frontend/model_v2_demo.py` — 데모 자산 로더·manifest 폐쇄 검증(**HTTP 클라이언트 미import** —
  `ast` 기반 import 검사로 회귀 고정).
- `frontend/model_v2_demo_app.py` — 데모 화면(위 로더만 호출).
- 검증(실제 호출 0회, 전부 mock):
  - `python -m unittest tests.test_model_v2` — 워커 계약 + 유료 폐쇄 스위치.
  - `python -m unittest tests.test_model_v2_ui` — 순수 client(게이트·검증·오류 비노출).
  - `python -m unittest tests.test_model_v2_app` — 실제 app 배선(Streamlit AppTest).
  - `python -m unittest tests.test_model_v2_demo` — 데모 로더 보안 검증 + 데모 app 배선.
- Streamlit 버전 차이는 **feature-detect**로 처리한다(1.51.0처럼 AppTest가 `file_uploader.upload`나
  image 엘리먼트를 지원하지 않으면 **해당 테스트만 사유를 명시해 skip**하고 나머지는 그대로 실행).
- 위젯 폭은 **`width="stretch"`** 를 쓴다. 1.51.0·1.59.0 **양쪽이 지원**하는 것을 실측 확인했고
  (`use_container_width` 폐기 경고 없음), 경고 부재는 회귀 테스트로 고정돼 있다.
