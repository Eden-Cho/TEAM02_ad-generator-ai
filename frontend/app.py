"""AI 상세페이지 생성기 — Streamlit 프론트 (백엔드 API 연동 버전).

백엔드(FastAPI)에 요청을 보내 상세페이지 + 썸네일을 받아 표시한다.
"""
import base64
import io
import json

import requests
import streamlit as st
from PIL import Image

# 도커 내부 네트워크망 명세(backend 상자 이름)로 선로를 정확히 변경하는 구간이다.
BACKEND = "http://backend:8000"

st.set_page_config(page_title="AI 상세페이지 생성기", layout="wide", page_icon="🛍️")
st.title("🛍️ AI 상세페이지 생성기")
st.caption("제품 사진·정보·스타일 → 상세페이지 + 메인/부가 썸네일 (백엔드 API 연동)")


# @st.cache_data(ttl=300)
def fetch_options():
    return requests.get(f"{BACKEND}/api/options", timeout=10).json()


try:
    opts = fetch_options()
except Exception as e:
    st.error(f"백엔드({BACKEND}) 연결 실패 — 서버 상태를 확인하세요.\n\n{e}")
    st.stop()

# ---------- 사이드바: 스타일 (백엔드에서 받은 10가지 옵션으로 정렬) ----------
st.sidebar.header("⚙️ 스타일 옵션")
selections = {}

# 백엔드(style_presets) 테이블 구조 그대로 10개 옵션을 동적 생성하는 구간이다.
for dim in opts["style_dimensions"]:
    if dim["type"] == "scale":
        chs = dim["choices"]
        selections[dim["id"]] = st.sidebar.slider(dim["label"], min(chs), max(chs), dim["default"])
    else:
        chs = dim["choices"]
        idx = chs.index(dim["default"]) if dim["default"] in chs else 0
        selections[dim["id"]] = st.sidebar.selectbox(dim["label"], chs, index=idx)

# '페이지 테마'는 백엔드 파이프라인 매개변수(theme_name)와 싱크를 맞춰 격리 보관한다.
theme_name = selections.get("page_theme", "light") if "page_theme" in selections else st.sidebar.selectbox("페이지 테마", ["light", "dark"])

# ---------- 메인: 입력 ----------
c1, c2 = st.columns(2)
with c1:
    product_name = st.text_input("상품명", "Apple Mac Mini M4")
    color = st.text_input("색상", "실버")
    category = st.selectbox("카테고리", opts["categories"], index=1)
    emphasis = st.text_input("강조 요청", "손바닥만 한 컴팩트 크기와 강력한 성능")
    product_details = st.text_area(
        "상세 스펙/특징",
        "M4 칩(10코어 CPU·10코어 GPU), 16GB 통합 메모리, 512GB SSD, "
        "Thunderbolt 4 x3, USB-C, HDMI, 10Gb 이더넷, 12.7x12.7x5cm, 0.67kg",
        height=110)
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

    # 백엔드 style_presets 구조와 온전하게 융합되도록 요청 딕셔너리를 빌드한다.
    req = {"product_name": product_name, "color": color, "category": category,
           "emphasis": emphasis, "product_details": product_details, **selections}

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

    tab1, tab2 = st.tabs(["📄 상세이미지", "🖼️ 썸네일 (메인/부가)"])
    with tab1:
        st.image(page, use_container_width=True)
        st.download_button("상세이미지 다운로드 (PNG)", page_bytes,
                           "detail_page.png", "image/png", use_container_width=True)
    with tab2:
        st.write("**메인이미지** (흰배경 1:1)")
        st.image(main, width=280)
        if gallery:
            st.write("**부가이미지**")
            cols = st.columns(min(len(gallery), 4))
            for i, g in enumerate(gallery):
                cols[i % len(cols)].image(g, caption=f"부가 {i + 1}")