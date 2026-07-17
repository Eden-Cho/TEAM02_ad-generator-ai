"""AI 상세페이지 생성기 — Streamlit 프론트 (백엔드 API 연동 버전).

백엔드(FastAPI)에 요청을 보내 상세페이지 + 썸네일을 받아 표시한다.
실행: (1) backend에서 `uvicorn main:app --reload`  (2) `streamlit run frontend/app.py`
"""
import base64
import io
import json

import requests
import streamlit as st
from PIL import Image

BACKEND = "http://backend:8000"

st.set_page_config(page_title="AI 상세페이지 생성기", layout="wide", page_icon="🛍️")
st.title("🛍️ AI 상세페이지 생성기")
st.caption("제품 사진·정보·스타일 → 상세페이지 + 메인/부가 썸네일 (백엔드 API 연동)")


@st.cache_data(ttl=300)
def fetch_options():
    return requests.get(f"{BACKEND}/api/options", timeout=10).json()


try:
    opts = fetch_options()
except Exception as e:
    st.error(f"백엔드({BACKEND}) 연결 실패 — `uvicorn main:app --reload` 실행 여부를 확인하세요.\n\n{e}")
    st.stop()

# ---------- 사이드바: 스타일 (백엔드에서 받은 옵션으로 렌더) ----------
st.sidebar.header("⚙️ 스타일 옵션")
selections = {}
for dim in opts["style_dimensions"]:
    if dim["type"] == "scale":
        chs = dim["choices"]
        selections[dim["id"]] = st.sidebar.slider(dim["label"], min(chs), max(chs), dim["default"])
    else:
        chs = dim["choices"]
        idx = chs.index(dim["default"]) if dim["default"] in chs else 0
        selections[dim["id"]] = st.sidebar.selectbox(dim["label"], chs, index=idx)
theme_name = st.sidebar.selectbox("페이지 테마", ["light", "dark"])

# ---------- 메인: 입력 ----------
c1, c2 = st.columns(2)
with c1:
    product_name = st.text_input("상품명", "Apple Mac Mini M4")
    bc1, bc2 = st.columns(2)
    brand = bc1.text_input("브랜드", "Apple")
    price = bc2.number_input("가격 (원, 0=미입력)", min_value=0, value=0, step=1000)
    color = st.text_input("색상", "실버")
    category = st.selectbox("카테고리", opts["categories"], index=1)
    emphasis = st.text_input("강조 요청", "손바닥만 한 컴팩트 크기와 강력한 성능")
    product_details = st.text_area(
        "상세 스펙/특징",
        "M4 칩(10코어 CPU·10코어 GPU), 16GB 통합 메모리, 512GB SSD, "
        "Thunderbolt 4 x3, USB-C, HDMI, 10Gb 이더넷, 12.7x12.7x5cm, 0.67kg",
        height=110)
    with st.expander("식별자 (선택) — GEO AI 검색 매칭 강화"):
        gtin = st.text_input("GTIN/바코드", "")
        sku = st.text_input("SKU", "")
with c2:
    product_files = st.file_uploader("제품 이미지 (제품만 나온 사진, 여러 장)",
                                     accept_multiple_files=True,
                                     type=["jpg", "jpeg", "png", "webp"])
    app_files = st.file_uploader("응용·사용 이미지 (손·사용장면) — 선택",
                                 accept_multiple_files=True,
                                 type=["jpg", "jpeg", "png", "webp"])

# ---------- 생성 (백엔드 호출) ----------
if st.button("🚀 상세페이지 생성", type="primary", use_container_width=True):
    if not product_files:
        st.error("제품 이미지를 1장 이상 올려주세요.")
        st.stop()

    req = {"product_name": product_name, "color": color, "category": category,
           "emphasis": emphasis, "product_details": product_details, **selections}
    # 선택 필드는 입력됐을 때만 포함 (없으면 GEO JSON-LD에서 자동 생략 → 정직)
    if brand.strip():
        req["brand"] = brand.strip()
    if price > 0:
        req["price"] = int(price)
    if gtin.strip():
        req["gtin"] = gtin.strip()
    if sku.strip():
        req["sku"] = sku.strip()

    files = [("product_files", (f.name, f.getvalue(), f.type or "image/png"))
             for f in product_files]
    files += [("app_files", (f.name, f.getvalue(), f.type or "image/png"))
              for f in (app_files or [])]

    with st.spinner("백엔드에서 생성 중… (이미지 생성에 수십 초 걸립니다)"):
        try:
            resp = requests.post(
                f"{BACKEND}/api/generate-detail-page",
                data={"req_json": json.dumps(req), "theme_name": theme_name},
                files=files, timeout=600)
        except Exception as e:
            st.error(f"요청 실패: {e}")
            st.stop()

    if resp.status_code != 200:
        st.error(f"생성 실패 ({resp.status_code}): {resp.text[:300]}")
        st.stop()

    r = resp.json()
    st.success(f"✅ 완료 — {r['seconds']}초")

    page_bytes = base64.b64decode(r["detail_page"])
    page = Image.open(io.BytesIO(page_bytes))
    main = Image.open(io.BytesIO(base64.b64decode(r["main"])))
    gallery = [Image.open(io.BytesIO(base64.b64decode(g))) for g in r["gallery"]]

    tab1, tab2, tab3 = st.tabs(["📄 상세이미지", "🖼️ 썸네일 (메인/부가)", "🔎 GEO (AI 검색용)"])
    with tab1:
        st.image(page, use_container_width=True)
        st.download_button("상세이미지 다운로드 (원본 PNG)", page_bytes,
                           "detail_page.png", "image/png", use_container_width=True)
        targets = opts.get("export_targets", [])
        if targets:
            st.write("**플랫폼별 규격 내보내기** — 마켓별 폭으로 리사이즈 (한 번 생성 → 여러 마켓)")
            cols = st.columns(len(targets))
            for col, t in zip(cols, targets):
                w = int(t["width"])
                h = round(page.height * w / page.width)
                buf = io.BytesIO()
                page.resize((w, h)).save(buf, "PNG")
                col.download_button(f"{t['name']} ({w}px)", buf.getvalue(),
                                    f"detail_{w}.png", "image/png",
                                    use_container_width=True, key=f"exp_{w}")
    with tab2:
        st.write("**메인이미지** (흰배경 1:1)")
        st.image(main, width=280)
        if gallery:
            st.write("**부가이미지**")
            cols = st.columns(min(len(gallery), 4))
            for i, g in enumerate(gallery):
                cols[i % len(cols)].image(g, caption=f"부가 {i + 1}")
    with tab3:
        st.caption("이미지로는 AI가 못 읽는 상품 정보를, AI 검색이 읽을 수 있는 구조화 텍스트로 함께 제공합니다.")
        warnings = r.get("warnings", [])
        if warnings:
            st.warning("사실 가드레일 — 입력 근거에 없는 수치가 감지됐습니다. 확인하세요:\n\n"
                       + "\n".join(f"- {w}" for w in warnings))
        geo_html = r.get("geo_html", "")
        if geo_html:
            st.download_button("GEO 페이지 다운로드 (HTML)", geo_html.encode("utf-8"),
                               "geo_page.html", "text/html", use_container_width=True)
        faq = r.get("faq", [])
        if faq:
            st.write("**자주 묻는 질문 (FAQ)**")
            for f in faq:
                with st.expander(f.get("q", "")):
                    st.write(f.get("a", ""))
        structured_data = r.get("structured_data", [])
        if structured_data:
            st.write("**구조화 데이터 (JSON-LD)** — 검색엔진·AI가 상품을 정확히 인식")
            st.json(structured_data)
