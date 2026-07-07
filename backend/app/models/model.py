import torch
from diffusers import StableDiffusionPipeline
from deep_translator import GoogleTranslator
from io import BytesIO

class AIImageGenerator:
    def __init__(self):
        self.pipe = None

    def initialize_model(self):
        print("🤖 [AI Model] 로컬 GPU에 Stable Diffusion 모델 탑재 시작...")
        
        # 💡 나중에 모델을 바꾸거나 튜닝할 때 여기(model_id, 가중치 로드 등)를 수정합니다.
        model_id = "runwayml/stable-diffusion-v1-5"
        
        self.pipe = StableDiffusionPipeline.from_pretrained(
            model_id, 
            torch_dtype=torch.float16
        )
        self.pipe = self.pipe.to("cuda")
        print(f"🟢 [AI Model] GPU 서빙 가동 성공: {torch.cuda.get_device_name(0)}")

    def _translate_if_korean(self, prompt: str) -> str:
        original = prompt.strip()
        has_korean = any(ord('가') <= ord(char) <= ord('힣') for char in original)
        
        if has_korean:
            print("🔄 [AI Model] 한글 프롬프트 감지 -> 영어로 자동 번역 중...")
            return GoogleTranslator(source='ko', target='en').translate(original)
        return original

    def generate_stream(self, prompt: str, steps: int) -> BytesIO:
        # 1. 한글 번역 처리
        translated_prompt = self._translate_if_korean(prompt)
        
        # 2. AI 이미지 생성 연산 (RTX 3060 가동)
        print("🚀 [AI Model] 이미지 추론 연산 시작...")
        result = self.pipe(translated_prompt, num_inference_steps=steps).images[0]
        
        # 3. 휘발성 스트림 변환
        img_io = BytesIO()
        result.save(img_io, 'PNG')
        img_io.seek(0)
        
        return img_io

# 다른 파일에서 불러와 쓸 수 있도록 전역 인스턴스 생성
generator = AIImageGenerator()