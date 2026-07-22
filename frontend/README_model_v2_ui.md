# model-v2 테스트 UI (별도 Streamlit)

팀 `frontend/app.py`(기존 백엔드용)와 **무관한 병렬 추가**다. model-v2 전용 워커
(`main_v2:app`, 포트 **8010**)의 `/api/model-v2/{options,preview,generate-detail-page}`만 사용한다.

## 실행

```bash
# 0) 워커가 쓸 OpenAI 키를 **프로세스 환경변수로만** 주입
#    (실제 키는 저장소·문서·명령 기록에 남기지 말 것 — 아래는 placeholder다)
export OPENAI_API_KEY="sk-REPLACE_WITH_YOUR_OWN_KEY"

# 1) model-v2 워커 (포트 8010) — 팀 main:app(8000)과 별개
cd backend && uvicorn main_v2:app --host 0.0.0.0 --port 8010

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
- 검증(실제 호출 0회, 전부 mock):
  - `python -m unittest tests.test_model_v2_ui` — 순수 client(게이트·검증·오류 비노출).
  - `python -m unittest tests.test_model_v2_app` — 실제 app 배선(Streamlit AppTest).
