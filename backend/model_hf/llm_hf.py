"""model_hf/llm_hf.py — 로컬 Hugging Face 모델 로더 및 추론 엔진."""
import os
import time
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer, pipeline
from langfuse import get_client
from baseline._json import parse_json  # 기존의 안전한 JSON 파서 재활용

# 🎯 랭퓨즈 클라이언트 초기화 (비용 및 속도 추적용)
langfuse = get_client()

HF_MODEL_ID = os.getenv("HF_MODEL_PATH") or "가져오신_허깅페이스_모델_ID"

_hf_pipeline = None

def get_hf_pipeline():
    global _hf_pipeline
    if _hf_pipeline is None:
        print(f"[HF-Engine] 로컬 모델 로딩 중: {HF_MODEL_ID} ...", flush=True)
        t0 = time.time()
        
        device = 0 if torch.cuda.is_available() else -1
        tokenizer = AutoTokenizer.from_pretrained(HF_MODEL_ID)
        model = AutoModelForCausalLM.from_pretrained(
            HF_MODEL_ID,
            torch_dtype=torch.float16 if torch.cuda.is_available() else torch.float32,
            low_cpu_mem_usage=True
        )
        
        _hf_pipeline = pipeline(
            "text-generation",
            model=model,
            tokenizer=tokenizer,
            device=device
        )
        print(f"[HF-Engine] 로딩 완료! ({round(time.time() - t0, 1)}초)", flush=True)
    return _hf_pipeline


def chat_json_hf(system: str, user: str, retries: int = 3) -> dict:
    """로컬 모델 추론을 실행하고 결과를 랭퓨즈 대시보드에 기록합니다."""
    generator = get_hf_pipeline()
    last = None
    
    # 1. Hugging Face용 프롬프트 구조 정의 (Llama-3 스타일 예시)
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user}
    ]
    prompt = generator.tokenizer.apply_chat_template(
        messages, 
        tokenize=False, 
        add_generation_prompt=True
    )

    for attempt in range(retries + 1):
        t_start = time.time()
        try:
            # 2. 로컬에서 가벼운 텍스트 생성 연산 시작
            outputs = generator(
                prompt,
                max_new_tokens=1024,
                do_sample=True,
                temperature=0.7,
                top_p=0.9,
                pad_token_id=generator.tokenizer.eos_token_id
            )
            
            response_content = outputs[0]["generated_text"][len(prompt):].strip()
            if not response_content:
                raise ValueError("빈 응답이 반환되었습니다.")
                
            parsed_data = parse_json(response_content)
            t_end = time.time()

            # 3. 🎯 랭퓨즈에 '허깅페이스 전용 Generation' 로그를 수동으로 수집 요청
            # (수동 SDK를 써서 로컬 추론 속도 및 사용 토큰 개수 기록)
            langfuse.generation(
                name="huggingface_local_inference",
                model=HF_MODEL_ID,
                input=prompt,
                output=response_content,
                start_time=t_start,
                end_time=t_end,
                usage={
                    "prompt_tokens": len(generator.tokenizer.encode(prompt)),
                    "completion_tokens": len(generator.tokenizer.encode(response_content))
                }
            )
            return parsed_data
            
        except Exception as e:
            last = e
            if attempt < retries:
                time.sleep(2 * (attempt + 1))
                
    raise ValueError(f"HF Inference {retries + 1}회 실패 — {last}")