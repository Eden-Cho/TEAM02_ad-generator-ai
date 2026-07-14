# 연동 가이드 (팀 공유용) — 프론트 ↔ 백엔드

GPT-Image 기반 상세페이지 생성 서비스의 **프론트가 받아야 할 것 / 백엔드가 처리하는 것** 정리.

---

## 아키텍처 한눈에

```
[Streamlit 프론트]  --(HTTP)-->  [FastAPI 백엔드]  --(import)-->  [model/ 파이프라인]
  frontend/app.py                 backend/                        baseline·composer
   입력·표시                       API·오케스트레이션                프롬프트·카피·이미지·조립
```

- 텍스트: `gpt-5-mini` / 이미지: `gpt-image-1-mini` (팀 키는 이 두 모델만 접근 가능)
- 업로드/결과는 **서버에 저장 안 함**(임시폴더 자동삭제 — 휘발성)

## 실행
```bash
cd backend && uvicorn main:app --reload     # http://localhost:8000
streamlit run frontend/app.py               # http://localhost:8501
```

---

## 엔드포인트

### 1) `GET /api/options` — 스타일 옵션·카테고리
프론트가 사이드바/카테고리 드롭다운을 그리기 위해 앱 시작 시 호출.

**응답 (JSON)**
```json
{
  "style_dimensions": [
    {"id": "brightness", "label": "밝기", "type": "scale",  "default": 4, "choices": [1,2,3,4,5,6,7]},
    {"id": "mood",       "label": "무드", "type": "choice", "default": "미니멀", "choices": ["미니멀","럭셔리", ...]}
  ],
  "categories": ["가전·TV", "컴퓨터·노트북·조립PC", ...],
  "export_targets": [ {"name": "네이버 스마트스토어", "width": 860},
                      {"name": "쿠팡", "width": 780}, {"name": "고해상 (1080)", "width": 1080} ]
}
```
- `type="scale"` → 슬라이더, `type="choice"` → 드롭다운.
- `export_targets` → 상세이미지를 마켓별 폭으로 **리사이즈 다운로드**(한 번 생성 → 여러 마켓). 프론트가 버튼 렌더.

### 2) `POST /api/generate-detail-page` — 상세페이지 생성
**요청 (multipart/form-data)**

| 필드 | 형식 | 설명 |
|------|------|------|
| `req_json` | Form(str) | 제품정보 + 스타일 선택을 담은 **JSON 문자열** (아래 표) |
| `theme_name` | Form(str) | `light` / `dark` |
| `product_files` | File(다중) | **제품 단독 사진** (필수, 1장 이상) |
| `app_files` | File(다중) | **손·사용장면 사진** (선택) |

**`req_json` 필드**

| 키 | 예시 | 비고 |
|----|------|------|
| `product_name` | "Apple Mac Mini M4" | 상품명 |
| `color` | "실버" | 색상 |
| `category` | "컴퓨터·노트북·조립PC" | → 내부에서 아키타입 자동 매핑 |
| `emphasis` | "손바닥만 한 컴팩트 크기" | 강조 요청 |
| `product_details` | "M4 칩, 16GB, 512GB SSD…" | 스펙(카피·스펙표 재료) |
| `brand` *(선택)* | "Apple" | GEO JSON-LD `brand` — 없으면 생략 |
| `price` *(선택)* | 890000 | GEO JSON-LD `offers`(원) — 없으면 생략 |
| `gtin` / `sku` *(선택)* | "0195…" / "MMINI-M4" | 식별자 — AI 검색 매칭 강화, 없으면 생략 |
| `site_spec` | "네이버 스마트스토어" | 출력 규격·상세폭 결정 |
| `copy_tone` | "프리미엄" | 카피 톤 |
| `brightness` | 6 | 1(어둡게)~7(밝게) |
| `color_palette` | "화이트·크림" | 색조 |
| `background` | "질감 표면" | 배경 유형 |
| `mood` | "미니멀" | 무드 |
| `prop_density` | 3 | 1~5 소품 밀도 |
| `season` | "무관" | 시즌감 |
| `target_audience` | "직장인" | 타깃 |
| `positioning` | 3 | 1(가성비)~5(프리미엄) |

> `style_dimensions`의 `id`가 곧 `req_json`의 키입니다. `/api/options` 값으로 그대로 채우면 됨.

**응답 (JSON)**
```json
{
  "detail_page": "<base64 PNG>",   // 긴 세로 상세이미지
  "main":        "<base64 JPG>",   // 메인 썸네일 (흰배경 1:1)
  "gallery":     ["<base64 JPG>", ...],  // 부가 썸네일 (1:1)
  "seconds":     42.3,

  // --- GEO 텍스트 레이어 (AI 검색용 부가 산출물) ---
  "geo_html":        "<시맨틱 HTML 문자열, JSON-LD 임베드>",
  "structured_data": [ { "@type": "Product", ... }, { "@type": "FAQPage", ... } ],
  "faq":             [ { "q": "...", "a": "..." }, ... ],
  "warnings":        [ "근거 없는 수치 의심: '30'", ... ]  // 사실 가드레일
}
```
> GEO 필드는 **하위호환** — 기본값(빈 문자열/빈 배열)이라 기존 프론트가 무시해도 안전.

---

## 프론트엔드가 받아야 할 것 (frontend/app.py)

1. **`GET /api/options`** → 사이드바(스타일 슬라이더/드롭다운) + 카테고리 드롭다운 렌더
2. 사용자 입력 → **`req` dict** 조립 (기본정보 + 스타일 선택값)
3. 이미지 업로드 → **multipart** 로 묶기:
   ```python
   files = [("product_files", (f.name, f.getvalue(), f.type)) for f in product_files]
   files += [("app_files", (f.name, f.getvalue(), f.type)) for f in app_files]
   requests.post(URL, data={"req_json": json.dumps(req), "theme_name": theme},
                 files=files)
   ```
4. **응답 base64 디코드 → 이미지 표시·다운로드**:
   ```python
   from PIL import Image; import base64, io
   page = Image.open(io.BytesIO(base64.b64decode(r["detail_page"])))
   ```
5. **GEO 탭** — `geo_html`(HTML 다운로드), `faq`, `structured_data`(JSON-LD) 표시, `warnings` 있으면 경고 노출

## 백엔드가 데이터에 적용하는 것 (backend/)

1. `req_json` 파싱 → `req` dict / `product_files`·`app_files` → **임시폴더 저장** (`generate.py`)
2. **`run_pipeline(req, product_paths, app_paths, theme_name)`** 실행 (`services/pipeline_service.py`):
   - `build_style_context` → 이미지 키워드·카피 지시·출력 크기·상세폭
   - `resolve_image_slots` → 사진을 아키타입 슬롯에 매핑(제품=edit, 응용=lifestyle)
   - `prompt_generator` → 컷별 이미지 프롬프트
   - `copy_generator.generate_page_copy` → 섹션별 카피(본문 포함) / `generate_page_extras` → 스펙표
   - `image_generator` → 컷별 이미지(gpt-image-1-mini)
   - `build_rich_page` → 긴 상세페이지 / `thumbnails` → 메인·부가 썸네일
   - `geo.geo_main` → **GEO 레이어**(Product·FAQPage JSON-LD, FAQ, 시맨틱 HTML, 사실 가드레일)
3. 결과 이미지 → **base64 인코딩** + GEO 텍스트 필드 → 응답 / 임시폴더 자동삭제

---

## 데이터 계약 요약 (한 줄)
- **프론트 → 백엔드**: `req_json`(제품정보 + 선택 `brand/price/gtin/sku` + 스타일 10축) + `product_files`/`app_files`(multipart)
- **백엔드 → 프론트**: `detail_page`·`main`·`gallery`(base64) + `seconds` + **GEO**(`geo_html`·`structured_data`·`faq`·`warnings`)

## GEO 텍스트 레이어 (신규)
이미지는 사람이 보지만 **AI 검색(ChatGPT·Perplexity 등)은 이미지 속 정보를 못 읽습니다.**
그래서 이미지와 별개로 **AI가 읽는 구조화 텍스트**를 함께 내보냅니다.
- `structured_data` — Product / FAQPage **JSON-LD**(schema.org), 식별자·가격·스펙·신선도(`dateModified`) 포함
- `faq` — 근거 기반 Q&A (AI가 인용하기 좋은 포맷)
- `geo_html` — 위를 임베드한 **시맨틱 HTML**(다운로드해 배포 가능)
- `warnings` — **사실 가드레일**: 입력 근거에 없는 수치를 경고. 허위 평점·가짜 인용은 **생성 안 함**(정직 원칙)
- 구현: `model/geo/geo_layer.py` · 파이프라인 5/5 이후 자동 실행

## 주의
- **API 키**: `model/.env`의 `OPENAI_API_KEY` (커밋 금지 — `.gitignore`). 각자 로컬에 입력.
- **모델**: 팀 키는 `gpt-5-mini` / `gpt-image-1-mini`만 접근 가능 (gpt-image-2는 Limit 0).
- **비용**: 생성 1회당 이미지 컷 수 × ~$0.02.
