"""model-v2 테스트 UI — 별도 Streamlit 앱(팀 app.py와 무관, 병렬 추가).

기본 동작은 **무과금 preview**다. 실제 생성은 preview 성공 + "유료 호출을 확인했습니다" 체크가
모두 있어야 활성화되며, 입력·파일이 바뀌면 승인이 무효화되고 다시 preview를 요구한다.

실행:
    # 1) model-v2 워커(포트 8010)
    cd backend && uvicorn main_v2:app --host 0.0.0.0 --port 8010
    # 2) 이 테스트 UI (worker 주소는 MODEL_V2_BACKEND_URL, 기본 http://127.0.0.1:8010)
    streamlit run frontend/model_v2_app.py
⚠️ '상세페이지 생성'은 **유료**(LLM·이미지 API)다. preview는 무과금이다.

로직·HTTP는 model_v2_client(테스트 대상)에 있고, 이 파일은 화면 구성만 담당한다.
"""
import io

import streamlit as st
from PIL import Image

import model_v2_client as mc

st.set_page_config(page_title="model-v2 테스트 UI", layout="wide", page_icon="🧪")
st.title("🧪 model-v2 테스트 UI")
st.caption("기본은 무과금 preview. 실제 생성은 preview 성공 + 유료 확인 체크가 있어야 활성화됩니다.")


@st.cache_data(ttl=300)
def _load_options():
    res = mc.fetch_options()
    return (res.payload, None) if res.ok else (None, res.error)


opts, opt_err = _load_options()
if opt_err:
    st.error(opt_err)
    st.stop()

# ── 사이드바: 스타일·모드 ─────────────────────────────────────────────────────
st.sidebar.header("⚙️ 스타일 옵션")
selections = {}
for dim in opts.get("style_dimensions", []):
    chs = dim["choices"]
    if dim["type"] == "scale":
        selections[dim["id"]] = st.sidebar.slider(
            dim["label"], min(chs), max(chs), dim["default"])
    else:
        idx = chs.index(dim["default"]) if dim["default"] in chs else 0
        selections[dim["id"]] = st.sidebar.selectbox(dim["label"], chs, index=idx)

st.sidebar.divider()
presentation_mode = st.sidebar.radio(
    "표현 모드", ["preserve", "natural"],
    help="preserve=원본 제품 픽셀 보존 / natural=자연스러운 재구성")
product_form = st.sidebar.selectbox(
    "제품 형태 (product_form)",
    ["unknown", "solid_stick", "cream", "liquid", "powder", "solid"])
theme_name = st.sidebar.selectbox("페이지 테마", ["light", "dark"])

# ── 메인 입력 ────────────────────────────────────────────────────────────────
c1, c2 = st.columns(2)
with c1:
    product_name = st.text_input("상품명", "Apple Mac Mini M4", key="mv2_product_name")
    bc1, bc2 = st.columns(2)
    brand = bc1.text_input("브랜드", "Apple")
    price = bc2.number_input("가격 (원, 0=미입력)", min_value=0, value=0, step=1000)
    color = st.text_input("색상", "실버")
    category = st.selectbox("카테고리", opts.get("categories", []),
                            index=min(1, max(0, len(opts.get("categories", [])) - 1)))
    emphasis = st.text_input("강조 요청", "컴팩트한 크기와 강력한 성능")
    product_details = st.text_area("상세 스펙/특징", "M4 칩, 16GB 메모리, 512GB SSD", height=90)
    product_angles = st.text_input("제품 각도 (쉼표로 구분)", "정면, 후면")
    app_angles = st.text_input("사용 각도 (쉼표로 구분)", "사용장면")
    with st.expander("근거(evidence) — 선택. 성분·질감 검증 문구"):
        ev_ingredient = st.text_area("ingredient (줄바꿈으로 구분)", "")
        ev_texture = st.text_area("texture (줄바꿈으로 구분)", "")
    with st.expander("식별자 (선택)"):
        gtin = st.text_input("GTIN/바코드", "")
        sku = st.text_input("SKU", "")
with c2:
    product_uploads = st.file_uploader(
        "제품 이미지 (제품만, 여러 장)", accept_multiple_files=True,
        type=["jpg", "jpeg", "png", "webp"])
    app_uploads = st.file_uploader(
        "사용·응용 이미지 — 선택", accept_multiple_files=True,
        type=["jpg", "jpeg", "png", "webp"])


def _lines(text):
    return [x.strip() for x in (text or "").splitlines() if x.strip()]


def _csv(text):
    return [x.strip() for x in (text or "").split(",") if x.strip()]


# ── 요청 조립 ────────────────────────────────────────────────────────────────
req = {"product_name": product_name, "color": color, "category": category,
       "emphasis": emphasis, "product_details": product_details,
       "presentation_mode": presentation_mode, "product_form": product_form,
       "product_angles": _csv(product_angles), "app_angles": _csv(app_angles),
       **selections}
if brand.strip():
    req["brand"] = brand.strip()
if price > 0:
    req["price"] = int(price)
if gtin.strip():
    req["gtin"] = gtin.strip()
if sku.strip():
    req["sku"] = sku.strip()
evidence = {}
if _lines(ev_ingredient):
    evidence["ingredient"] = _lines(ev_ingredient)
if _lines(ev_texture):
    evidence["texture"] = _lines(ev_texture)
if evidence:
    req["evidence"] = evidence

product_files = mc.read_uploads(product_uploads)
app_files = mc.read_uploads(app_uploads)
current_fp = mc.input_fingerprint(req, product_files, app_files, theme_name)

# ── 승인 상태 머신 ───────────────────────────────────────────────────────────
if "mv2_state" not in st.session_state:
    st.session_state.mv2_state = mc.initial_state()
state = st.session_state.mv2_state
# 승인 소비 후속 처리 — 직전 run에서 생성했으면 체크박스 위젯 상태도 명시적으로 false로 초기화
if st.session_state.pop("_mv2_reset_approval", False):
    st.session_state["mv2_approve_cb"] = False
mc.sync_inputs(state, current_fp)   # 입력이 바뀌었으면 preview·승인 무효화

st.divider()
pcol, _ = st.columns([1, 3])
if pcol.button("🔎 무과금 미리보기 (preview)", type="primary",
               use_container_width=True, key="mv2_preview_btn"):
    if not product_files:
        st.error("제품 이미지를 1장 이상 올려주세요.")
    else:
        res = mc.run_preview(req, product_files, app_files)
        if res.ok:
            mc.apply_preview(state, current_fp, res.payload)
        else:
            st.error(res.error)

# ── preview 결과 표시 ────────────────────────────────────────────────────────
if state.preview is not None and current_fp == state.preview_fp:
    p = state.preview
    st.subheader("① 미리보기 (무과금) — 경로·씬·예상 호출 수")
    ec = p.get("expected_calls", {})
    m = st.columns(4)
    m[0].metric("images.generate", ec.get("images_generate", 0))
    m[1].metric("images.edit", ec.get("images_edit", 0))
    m[2].metric("passthrough", ec.get("passthrough", 0))
    m[3].metric("LLM(논리 상한)", ec.get("llm_logical_max", 0))
    st.write(f"표현 모드 **{p.get('presentation_mode')}** · 제품 형태 **{p.get('product_form')}**")
    st.write("**역할:** " + ", ".join(p.get("roles", [])))
    st.table([{"역할": c.get("role"), "경로": c.get("intended_path"),
               "각도": c.get("angle"), "씬": c.get("scene_id")}
              for c in p.get("cuts", [])])

    st.subheader("② 유료 생성")
    st.warning("아래는 **유료**입니다 — LLM·이미지 API가 실제로 호출됩니다. **매 호출마다 재승인** 필요.")
    # 체크박스는 key로 상태를 보관 — 생성 시 소비되면 다음 run에서 명시적으로 false로 초기화된다.
    approved = st.checkbox("유료 호출을 확인했습니다", key="mv2_approve_cb")
    mc.set_approval(state, approved)

    gen_enabled = mc.can_generate(state, current_fp)
    if st.button("🚀 상세페이지 생성 (유료)", disabled=not gen_enabled,
                 use_container_width=True, key="mv2_gen_btn"):
        res = mc.attempt_generate(state, current_fp, req, product_files,
                                  app_files, theme_name)
        # 성공·실패 무관 — 승인은 소비됐다. 다음 run에서 체크박스도 false로 되돌린다.
        st.session_state["_mv2_reset_approval"] = True
        if not res.ok:
            st.error(res.error)
        else:
            r = res.payload                       # parse_generate로 검증·디코딩된 payload
            st.success(f"완료 — {r.get('seconds', 0)}초")
            page_bytes = r["detail_page_png"]
            t1, t2, t3 = st.tabs(["📄 상세이미지", "🖼️ 썸네일", "🔎 warnings·trace"])
            with t1:
                st.image(Image.open(io.BytesIO(page_bytes)), use_container_width=True)
                st.download_button("상세이미지 (PNG)", page_bytes,
                                   "detail_page.png", "image/png")
            with t2:
                main_bytes = r["main_jpeg"]
                st.image(Image.open(io.BytesIO(main_bytes)), width=280)
                st.download_button("메인 (JPEG)", main_bytes, "main.jpg", "image/jpeg")
                for i, gb in enumerate(r.get("gallery_jpeg", [])):
                    st.image(Image.open(io.BytesIO(gb)), caption=f"부가 {i + 1}", width=220)
                    st.download_button(f"부가 {i + 1}", gb, f"gallery_{i + 1}.jpg",
                                       "image/jpeg", key=f"g{i}")
            with t3:
                warnings = r.get("warnings", [])
                if warnings:
                    st.warning("\n".join(f"- {w}" for w in warnings))
                else:
                    st.info("warnings 없음")
                st.write("**trace**")
                st.json(r.get("trace", {}))
                if "evaluation" in r:
                    st.write("**evaluation (선택)**")
                    st.json(r["evaluation"])
else:
    st.info("먼저 무과금 미리보기를 실행하세요. 입력·파일이 바뀌면 다시 미리보기가 필요합니다.")
