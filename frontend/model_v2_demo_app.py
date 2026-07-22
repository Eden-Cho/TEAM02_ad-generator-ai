"""model-v2 데모 모드 — 발표·테스트용. **사전 생성 샘플만 표시하고 API를 호출하지 않는다.**

실행:
    MODEL_V2_DEMO_ASSET_DIR=/path/to/samples streamlit run frontend/model_v2_demo_app.py

이 앱은 `model_v2_demo`(manifest 검증 로더)만 쓴다 — `model_v2_client`(HTTP)를 import하지
않으므로 **generate·preview를 포함한 HTTP 호출이 구조적으로 0회**다. 워커도 필요 없다.

화면 구조는 기존 model-v2 UI(사이드바 선택 + 본문 탭)를 그대로 따른다.
"""
import streamlit as st

import model_v2_demo as demo

_BANNER = "🔒 사전 생성 샘플 · 실제 API 호출 없음"

st.set_page_config(page_title="model-v2 데모 (사전 생성 샘플)", layout="wide", page_icon="🎬")
st.title("🎬 model-v2 데모 — 사전 생성 샘플")
st.caption(f"{_BANNER} — 이 화면의 모든 이미지는 미리 생성해 둔 결과이며, "
           "여기서는 LLM·이미지 API를 호출하지 않습니다.")
st.sidebar.info(_BANNER)


@st.cache_resource(show_spinner="샘플 패키지 검증 중…")
def _load():
    try:
        return demo.load_package(), None
    except demo.DemoAssetError:
        # 경로·예외 원문·manifest 내용을 노출하지 않는다 — 고정 문구만.
        import os
        if not os.getenv(demo.ENV_ASSET_DIR, "").strip():
            return None, demo.ERR_NOT_CONFIGURED
        return None, demo.ERR_INVALID_PACKAGE


pkg, err = _load()
if err:
    st.error(err)
    st.stop()

showcase = demo.showcase_assets(pkg)
prods = demo.products(pkg)
if not prods:
    st.error(demo.ERR_INVALID_PACKAGE)
    st.stop()


def _caption(a) -> str:
    bits = [a.mode]
    if a.role:
        bits.append(a.role)
    bits.append(a.asset_type)
    return " · ".join(bits)


def _limits(a):
    if a.known_limits:
        with st.expander("알려진 한계", expanded=False):
            for lim in a.known_limits:
                st.write(f"- {lim}")


# ── 사이드바: 제품·보기 선택 ─────────────────────────────────────────────────
st.sidebar.header("📦 샘플 선택")
labels = {p: lbl for p, lbl in prods}
product = st.sidebar.radio("제품", [p for p, _ in prods],
                           format_func=lambda p: labels[p], key="demo_product")
show_gallery = st.sidebar.checkbox("갤러리 컷도 보기", value=True, key="demo_show_gallery")
st.sidebar.divider()
st.sidebar.caption(f"패키지: {pkg.name}")
st.sidebar.caption(f"생성일: {pkg.created}")
st.sidebar.caption(f"전시 대상 {len(showcase)}개 · 오류 비교용 "
                   f"{len(demo.error_assets(pkg))}개 (기본 화면 제외)")

tab_cmp, tab_fix, tab_info = st.tabs(
    ["🆚 preserve / natural 비교", "🛠 결함 개선 비교", "ℹ️ 패키지 정보"])

# ── 탭 1: 정상 대표 결과 (기본 화면) ─────────────────────────────────────────
with tab_cmp:
    st.info(f"{_BANNER} · 아래는 **정상 대표 결과**입니다. 오류 샘플은 여기에 없습니다.")
    modes = demo.modes_for(pkg, product)
    st.subheader(f"{labels[product]} — 상세페이지")
    cols = st.columns(len(modes)) if modes else []
    for col, mode in zip(cols, modes):
        with col:
            st.markdown(f"### {mode}")
            pages = [a for a in demo.set_assets(pkg, product, mode)
                     if a.asset_type == "detail_page"]
            for a in pages:
                st.caption(f"{_caption(a)} · 판정 `{a.verdict}`")
                st.image(str(a.abs_path), width="stretch")
                st.caption(f"{a.width}×{a.height} {a.image_format}")
                _limits(a)
            if not pages:
                st.caption("상세페이지 없음")

    if show_gallery:
        st.divider()
        st.subheader(f"{labels[product]} — 메인·갤러리 컷")
        for mode in modes:
            cuts = [a for a in demo.set_assets(pkg, product, mode)
                    if a.asset_type != "detail_page"]
            if not cuts:
                continue
            st.markdown(f"**{mode}**")
            gcols = st.columns(min(len(cuts), 4))
            for i, a in enumerate(cuts):
                with gcols[i % len(gcols)]:
                    st.image(str(a.abs_path), width="stretch")
                    st.caption(f"{_caption(a)}")
                    st.caption(a.purpose)

# ── 탭 2: 결함 개선 비교 (오류본은 여기서만) ─────────────────────────────────
with tab_fix:
    st.warning("⚠️ 이 영역에는 **결함이 있는 샘플**이 포함됩니다. 운영에 사용하지 마세요.")
    st.markdown("### 수정 전 / 수정 후 (단일 컷)")
    st.error("🚫 **수정본은 단일 컷입니다 — 전체 상세페이지 재생성 결과가 아닙니다.** "
             "해당 제품의 상세페이지 전체는 수정 전 상태 그대로입니다.")
    pairs = demo.fix_pairs(pkg)
    if not pairs:
        st.caption("비교 쌍 없음")
    for before, after in pairs:
        st.markdown(f"#### {before.product_label} — `{before.role}` 컷")
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**수정 전** (오류)")
            st.image(str(before.abs_path), width="stretch")
            st.caption(f"판정 `{before.verdict}` · {before.purpose}")
            _limits(before)
        with c2:
            st.markdown("**수정 후 (v2, 단일 컷)**")
            st.image(str(after.abs_path), width="stretch")
            st.caption(f"판정 `{after.verdict}` · {after.purpose}")
            if after.full_page_regenerated is False:
                st.caption("⚠️ 전체 상세페이지 재생성 결과가 아님 (scope: 단일 컷)")
            _limits(after)

    st.divider()
    st.markdown("### 오류 참고 세트 (운영 사용 금지)")
    errs = demo.error_assets(pkg)
    if not errs:
        st.caption("오류 참고 자산 없음")
    else:
        st.error(f"🚫 아래 {len(errs)}개는 **오류 비교용 전용**입니다. "
                 "기본 화면에서는 제외되며 운영에 사용하면 안 됩니다.")
        with st.expander("오류 참고 세트 펼쳐 보기", expanded=False):
            ecols = st.columns(3)
            for i, a in enumerate(errs):
                with ecols[i % len(ecols)]:
                    st.image(str(a.abs_path), width="stretch")
                    st.caption(f"{a.product_label} · {_caption(a)}")
                    st.caption(f"판정 `{a.verdict}`")

# ── 탭 3: 패키지 정보 ────────────────────────────────────────────────────────
with tab_info:
    st.info(_BANNER)
    st.write(f"**패키지** `{pkg.name}` · **생성일** {pkg.created}")
    if pkg.warnings:
        st.markdown("#### 패키지 경고")
        for w in pkg.warnings:
            st.warning(w)
    if pkg.verdict_legend:
        st.markdown("#### 판정 구분")
        st.table([{"판정": k, "의미": v} for k, v in pkg.verdict_legend.items()])
    st.markdown("#### 수록 자산")
    st.table([{"제품": a.product_label, "모드": a.mode, "종류": a.asset_type,
               "역할": a.role or "-", "판정": a.verdict,
               "해상도": f"{a.width}×{a.height}", "형식": a.image_format}
              for a in sorted(pkg.assets, key=lambda x: x.rel_path)])
