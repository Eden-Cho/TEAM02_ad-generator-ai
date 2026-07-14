import os
import time
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer
from diffusers import FluxPipeline 
from langfuse import get_client  # 🎯 랭퓨즈 로드

from model_hf.config import NEW_TEXT_MODEL, NEW_IMAGE_MODEL, DEVICE, TORCH_DTYPE, HF_TOKEN, OUTPUT_DIR

langfuse = get_client()

class NewOpenSourceEngine:
    def __init__(self):
        print(f"🔄 [model_hf] FLUX 최고존엄 엔진 초기화 중... (VRAM 절약 모드 가동)")
        self.device = DEVICE
        
        # 1. Qwen 텍스트 토크나이저만 먼저 준비
        self.tokenizer = AutoTokenizer.from_pretrained(NEW_TEXT_MODEL, token=HF_TOKEN)
        
        # 2. FLUX.1-schnell 이미지 모델 로드 및 CPU 오프로딩 주입 (VRAM 폭발 방지 핵심)
        self.image_pipe = FluxPipeline.from_pretrained(
            NEW_IMAGE_MODEL,
            torch_dtype=TORCH_DTYPE,
            token=HF_TOKEN
        )
        # 💡 GPU 메모리가 부족할 때 레이어별로 CPU와 GPU를 오가며 연산하게 만듭니다.
        if self.device == "cuda":
            self.image_pipe.enable_sequential_cpu_offload()
        else:
            self.image_pipe.to(self.device)
            
        print("✅ [model_hf] 엔진 로드 및 VRAM 최적화 완료!")

    def generate_huggingface_copy(self, product_name: str, category: str) -> str:
        """Qwen 모델 기반 고품질 광고 문구 생성 (VRAM 동적 할당 및 해제)"""
        t_start = time.time()
        
        # 💡 메모리 절약을 위해 텍스트 모델을 생성 시점에 로컬 로드 (혹은 4bit 양자화 적용 가능)
        text_model = AutoModelForCausalLM.from_pretrained(
            NEW_TEXT_MODEL,
            torch_dtype=TORCH_DTYPE,
            device_map="auto" if self.device == "cuda" else None,
            token=HF_TOKEN
        )
        
        messages = [
            {"role": "system", "content": f"당신은 {category} 마케팅 전문가입니다. 제품의 소구점을 파악해 강렬한 광고 문구 한 줄을 한글로 작성하세요."},
            {"role": "user", "content": f"제품명: {product_name} -> 광고 카피:"}
        ]
        text_input = self.tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        inputs = self.tokenizer([text_input], return_tensors="pt").to(self.device)
        
        with torch.no_grad():
            outputs = text_model.generate(**inputs, max_new_tokens=128, temperature=0.7)
        
        generated_ids = [out[len(in_pt):] for in_pt, out in zip(inputs.input_ids, outputs)]
        response_content = self.tokenizer.batch_decode(generated_ids, skip_special_tokens=True)[0].strip()
        t_end = time.time()

        # 🎯 [랭퓨즈 전송] 텍스트 생성 속도 및 토큰 추적
        langfuse.generation(
            name="hf_qwen_copy_generation",
            model=NEW_TEXT_MODEL,
            input=text_input,
            output=response_content,
            start_time=t_start,
            end_time=t_end,
            usage={
                "prompt_tokens": len(inputs.input_ids[0]),
                "completion_tokens": len(generated_ids[0])
            }
        )

        # 🧼 사용이 끝난 Qwen 모델은 즉시 VRAM에서 탈탈 털어 백수 상태로 만듭니다.
        del text_model
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            
        return response_content

    def generate_huggingface_image(self, concept_prompt: str, product_name: str) -> str:
        """FLUX.1-schnell 기반 실물급 광고 이미지 빌드"""
        t_start = time.time()
        studio_prompt = f"Professional studio product photography of {product_name}. {concept_prompt}, high-end commercial style, 8k resolution, crisp detailing"
        
        with torch.no_grad():
            raw_image = self.image_pipe(
                prompt=studio_prompt, 
                num_inference_steps=4,  # schnell 모델은 4스텝이면 충분합니다.
                guidance_scale=0.0, 
                max_sequence_length=256 
            ).images[0]
            
        timestamp = int(time.time())
        file_name = f"flux_{product_name}_{timestamp}.png"
        full_path = os.path.join(OUTPUT_DIR, file_name)
        raw_image.save(full_path)
        t_end = time.time()

        # 🎯 [랭퓨즈 전송] 이미지 생성 속도 및 단위 박제
        langfuse.generation(
            name="hf_flux_image_generation",
            model=NEW_IMAGE_MODEL,
            input=studio_prompt,
            output=full_path,
            start_time=t_start,
            end_time=t_end,
            usage={
                "prompt_tokens": 0,
                "completion_tokens": 1  # 1장 생성 명시
            }
        )
        return full_path

if __name__ == "__main__":
    # 단독 기동 테스트용 메인 블록은 기존과 동일하게 유지...
    pass