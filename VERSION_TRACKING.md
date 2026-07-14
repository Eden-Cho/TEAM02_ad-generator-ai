# 버전 정리

_최종 갱신: 2026-07-13_

## 버전 목록

| # | 버전 | 위치 | 성격 |
|---|------|------|------|
| **1** | 민성 로컬 작업본 | `project/high_service_01/` | 최신 (GPT-Image + 신규 기능) |
| **2** | 내 fork | `minseong/gpt-image-pipeline` (=`high_git/`) | 이전 스냅샷 (GPT-Image) |
| 3 | 팀 원본 main | `upstream/main` (Eden-Cho) | 참고 · 다른 팀원 (SD 기반) |
| 4 | 실험 노트북 | `high/baseline_01~06.ipynb` | 참고 · 개발 히스토리 |

> 1·2는 **같은 코드베이스**이며 1이 상위집합.

## 버전별 상세

**1. 민성 로컬 작업본 (`high_service_01`) — 최신**
- GPT-Image 파이프라인: 아키타입 6종 → 이미지 프롬프트·카피 → 이미지 생성 → 상세페이지 + 썸네일
- GEO 텍스트 레이어: Product/FAQPage JSON-LD · FAQ · 사실 가드레일 · 시맨틱 HTML
- 창의성 슬라이더: 제품 보존 ↔ 자유로운 재해석 (1~5단계)
- 폰트 크로스플랫폼 폴백: Docker(Nanum) / macOS(AppleSDGothicNeo)
- 입력 필드: brand · price · gtin · sku (선택, GEO 매칭 강화)
- 플랫폼별 규격 export: 네이버(860) · 쿠팡(780) · 고해상(1080)
- LangFuse+LangChain 관측: 텍스트 LLM(`chat_json`)을 LangChain(ChatOpenAI) 경유 + LangFuse 추적 (키 없으면 no-op)

**2. fork 푸시본 (`minseong/gpt-image-pipeline`)**
- GPT-Image 파이프라인 (위 GEO·창의성 등 신규 기능 **이전** 상태)

**3. 팀 원본 main (`upstream/main`)**
- SD 기반 팀 버전 (다른 팀원 담당)

**4. 실험 노트북 (`baseline_01~06`)**
- 개발 과정 히스토리
