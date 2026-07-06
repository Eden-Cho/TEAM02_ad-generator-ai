import torch
from diffusers import StableDiffusionPipeline
from deep_translator import GoogleTranslator
from io import BytesIO
from schemas import AdRequest

class AIService:
    def __init__(self):
        self.pipe = None

    def load_model(self):
        print("🤖 [Backend] 로컬 GPU에 Stable Diffusion 모델 탑재 시작...")
        model_id = "runwayml/stable-diffusion-v1-5"
        
        # RTX 3060 최적화 세팅
        self.pipe = StableDiffusionPipeline.from_pretrained(
            model_id, 
            torch_dtype=torch.float16
        )
        self.pipe = self.pipe.to("cuda")
        print(f"🟢 [Backend] GPU 서빙 가동 성공: {torch.cuda.get_device_name(0)}")

    def translate_prompt(self, prompt: str) -> str:
        original = prompt.strip()
        has_korean = any(ord('가') <= ord(char) <= ord('힣') for char in original)
        
        if has_korean:
            print("🔄 [Backend] 한글 프롬프트 감지 -> 영어로 자동 번역 중...")
            return GoogleTranslator(source='ko', target='en').translate(original)
        return original

    def generate_as_stream(self, request: AdRequest) -> BytesIO:
        # 1. 한글 자동 번역
        translated_prompt = self.translate_prompt(request.prompt)
        
        # 2. AI 이미지 생성 연산 (RTX 3060 가동)
        print(f"🚀 [Backend] AI 이미지 생성 연산 시작: {translated_prompt}")
        result = self.pipe(translated_prompt, num_inference_steps=request.steps).images[0]
        
        # 3. 💾 물리 저장 없이 메모리(RAM) 내에서 바이너리 스트림으로 바로 변환
        img_io = BytesIO()
        result.save(img_io, 'PNG')
        img_io.seek(0)
        
        return img_io

# 전역 싱글톤 인스턴스 생성
ai_service = AIService()