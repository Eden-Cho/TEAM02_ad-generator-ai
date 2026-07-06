import streamlit as st
import requests

st.set_page_config(page_title="2팀 AI 광고 제작소", layout="wide", page_icon="🎨")

st.title("🎨 AI 브랜드 광고 제작소")
st.caption("텍스트를 입력하면 로컬 GPU가 연산 후 화면에 즉시 표시하며, 본 페이지를 새로고침하거나 넘어가면 이미지는 서버에 남지 않고 완전히 휘발됩니다.")

# 백엔드 API 주소
BACKEND_URL = "http://localhost:8000/api/generate-ad"

col1, col2 = st.columns([1, 1])

with col1:
    st.subheader("📋 광고 이미지 기획")
    prompt_input = st.text_area(
        "생성할 광고 컨셉을 입력하세요 (한글/영어 모두 가능):",
        value="물방울이 맺힌 시원한 제로 탄산음료 캔, 현대적인 디자인, 네온 조명, 스튜디오 광고 사진, 극도로 사실적인, 8k 해상도",
        height=150
    )
    steps = st.slider("생성 정밀도 (Inference Steps)", min_value=15, max_value=50, value=25)
    generate_btn = st.button("광고 이미지 생성하기 🚀", use_container_width=True)

with col2:
    st.subheader("🖼️ 생성된 결과물 (선택 다운로드)")
    
    if generate_btn:
        with st.spinner("백ends 서버에서 AI 이미지를 생성하여 스트리밍 중입니다..."):
            try:
                # 백엔드에 요청 전송
                payload = {"prompt": prompt_input, "steps": steps}
                response = requests.post(BACKEND_URL, json=payload, timeout=60)
                
                if response.status_code == 200:
                    # 백엔드가 보낸 바이너리 이미지를 화면에 즉시 렌더링
                    st.image(response.content, caption="생성된 임시 이미지 (미저장 상태)", use_container_width=True)
                    st.success("✨ 이미지 생성 성공! 서버에 저장되지 않은 상태이므로 필요한 경우 반드시 다운로드하세요.")
                    
                    # 💾 유저의 선택적 저장을 위한 다운로드 버튼 제공
                    st.download_button(
                        label="이 이미지 내 컴퓨터에 저장하기 💾",
                        data=response.content,
                        file_name="my_generated_ad.png",
                        mime="image/png",
                        use_container_width=True
                    )
                else:
                    st.error(f"🔴 백엔드 연산 에러 (코드: {response.status_code})")
            except Exception as e:
                st.error(f"🔴 백엔드 서버 연결 실패: {e}")
    else:
        st.info("왼쪽 기획 창에 내용을 적고 버튼을 누르면 실시간으로 계산된 결과가 여기에 나타납니다.")