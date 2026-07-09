"""요청(dict) + 장수 -> 이미지 생성 스펙 N개.

역할/mode/text_zone은 section_templates에서 고정되고,
GPT는 각 슬롯의 장면 프롬프트(scene)만 채운다.
text_zone(여백)·no-text 지시는 코드에서 결정론적으로 덧붙여 보장한다.

출력 계약(image_spec):
    {"role", "mode", "prompt", "text_zone"}
"""
import baseline.config as config
from baseline.llm import chat_json
from baseline.section_templates import clamp_count, resolve_slots
from baseline.style_presets import build_style_context


# text_zone(여백)을 실제로 비우도록 강제하는 결정론적 지시
TEXT_ZONE_CLAUSE = {
    "top": ("keep the entire top portion as clean empty negative space "
            "reserved for a text overlay, no objects or focal elements at the top"),
    "bottom": ("keep the entire bottom portion as clean empty negative space "
               "reserved for a text overlay, no objects or focal elements at the bottom"),
    "none": "",
}
# 모델이 이미지 안에 글자를 그리지 않도록 (텍스트는 PIL이 담당)
NO_TEXT_CLAUSE = "no text, no letters, no words, no watermark, no logo"
QUALITY_SUFFIX = "professional product photography, high detail, sharp focus, 8k"

SYSTEM_PROMPT = (
    "You are a professional product photography prompt engineer for a Korean "
    "e-commerce detail page image generator. You are given a FIXED list of image "
    "slots and must write ONE English scene prompt per slot. "
    "Output ONLY valid JSON. No markdown, no explanation."
)

USER_TEMPLATE = """[Product]
product_name: {product_name}
color: {color}
category: {category}
emphasis(강조 요청): {emphasis}
product_details(스펙/특징): {product_details}

[Style keywords — from user selections]
{style_keywords}

You must write scene prompts for these {n} FIXED slots (keep the order):
{slots_desc}

Rules for each "prompt":
1. English only.
2. Weave the style keywords into every prompt for a consistent look.
3. Follow the slot's brief.
4. For mode=edit slots: describe ONLY the background / scene / lighting.
   Do NOT describe the product itself (it is preserved from the uploaded photo).
5. For mode=t2i slots: describe the full lifestyle scene freely.
6. Do NOT add role/mode/text_zone — only the scene description.
7. Keep each prompt concise — under 40 words.

Output JSON (a list of prompt strings, same order as slots):
{{"prompts": ["slot 1 scene prompt", "slot 2 scene prompt"]}}
"""


def _assemble(scene: str, text_zone: str) -> str:
    """GPT 장면 프롬프트 + text_zone 여백 지시 + no-text + 품질 접미."""
    parts = [scene.strip().rstrip(".")]
    zone = TEXT_ZONE_CLAUSE.get(text_zone, "")
    if zone:
        parts.append(zone)
    parts.append(NO_TEXT_CLAUSE)
    parts.append(QUALITY_SUFFIX)
    return ", ".join(p for p in parts if p)


def generate(req: dict, image_keywords: list[str] | None = None,
             slots: list[dict] | None = None) -> list[dict]:
    n = clamp_count(req.get("num_images", 3))
    if slots is None:
        slots = resolve_slots(n, None)  # 사진 미지정 시 전부 t2i
    if image_keywords is None:
        image_keywords = build_style_context(req)["image_keywords"]

    slots_desc = "\n".join(
        f'{i + 1}. role={s["role"]}, mode={s["mode"]}, '
        f'text_zone={s["text_zone"]}, brief="{s["brief"]}"'
        for i, s in enumerate(slots)
    )
    user = USER_TEMPLATE.format(
        product_name=req.get("product_name", ""),
        color=req.get("color", ""),
        category=req.get("category", ""),
        emphasis=req.get("emphasis", ""),
        product_details=req.get("product_details", ""),
        style_keywords=", ".join(image_keywords),
        n=len(slots),
        slots_desc=slots_desc,
    )
    scene_prompts = chat_json(SYSTEM_PROMPT, user).get("prompts", [])

    # 골격은 템플릿에서, 프롬프트만 GPT 결과로 조립 (여백 지시는 코드가 보장)
    specs: list[dict] = []
    for i, slot in enumerate(slots):
        scene = scene_prompts[i] if i < len(scene_prompts) else slot["brief"]
        specs.append({
            "role": slot["role"],
            "mode": slot["mode"],
            "text_zone": slot["text_zone"],
            "image_path": slot.get("image_path"),
            "prompt": _assemble(scene, slot["text_zone"]),
        })
    return specs


if __name__ == "__main__":
    import json

    sample = {
        "product_name": "무선 기계식 키보드", "color": "화이트",
        "category": "전자제품", "emphasis": "타건감과 미니멀 디자인",
        "num_images": 3, "brightness": 6, "mood": "미니멀",
        "color_palette": "화이트·크림", "background": "질감 표면",
    }
    print(json.dumps(generate(sample), ensure_ascii=False, indent=2))
