"""베이스라인 파이프라인 오케스트레이션 (CLI).

실행 예)
    python -m baseline.pipeline --check        # API 호출 없이 설정/입력만 점검 (비용 0)
    python -m baseline.pipeline --skip-image   # 프롬프트+카피만 (텍스트 비용만)
    python -m baseline.pipeline --first-only    # 첫 컷 1장만 생성 (이미지 최소 비용)
    python -m baseline.pipeline                 # 전체 (image/ 폴더 사진 자동 사용)
    python -m baseline.pipeline --image image/keyboard.jpg
"""
import argparse
import json
import time
from pathlib import Path

import baseline.config as config
from baseline import copy_generator, image_generator, prompt_generator, renderer
from baseline.section_templates import clamp_count, resolve_slots
from baseline.style_presets import build_style_context


def _image_list(product_image_path: str | None) -> list[str]:
    """슬롯에 매핑할 제품 사진 목록. --image 지정 시 그 한 장만."""
    if product_image_path:
        return [product_image_path]
    return [str(p) for p in config.find_product_images()]


def check(request_path: str, product_image_path: str | None = None) -> None:
    """API 호출 없이 설정·입력을 점검한다 (비용 0)."""
    req = json.loads(Path(request_path).read_text(encoding="utf-8"))
    ctx = build_style_context(req)
    images = _image_list(product_image_path)
    n = clamp_count(req.get("num_images", 3))
    slots = resolve_slots(n, images)
    key = config.OPENAI_API_KEY

    print("=== 사전 점검 (--check, API 호출 없음) ===")
    print(f"OPENAI_API_KEY : {'설정됨 (' + key[:6] + '...)' if key else '❌ 비어있음 (.env에 입력 필요)'}")
    print(f"TEXT_MODEL     : {config.TEXT_MODEL}")
    print(f"IMAGE_MODEL    : {config.IMAGE_MODEL}")
    print(f"출력 크기      : {ctx['size']}")
    print(f"장수(num_images): {n}")
    print(f"제품 사진 {len(images)}장 → 슬롯 매핑:")
    for i, s in enumerate(slots, 1):
        mapped = Path(s["image_path"]).name if s["image_path"] else "(없음 → t2i)"
        print(f"   {i}. {s['role']:10s} [{s['mode']:4s}] ← {mapped}")
    print(f"이미지 키워드  : {len(ctx['image_keywords'])}개")
    print("→ 문제 없으면 --skip-image 또는 --first-only 로 실제 테스트하세요.")


def run(request_path: str, product_image_path: str | None = None,
        skip_image: bool = False, first_only: bool = False,
        name: str = "result") -> list[Path]:
    req = json.loads(Path(request_path).read_text(encoding="utf-8"))
    images = _image_list(product_image_path)

    # 스타일 선택값 -> 이미지 키워드 / 카피 지시문 / 출력 크기 (레지스트리)
    ctx = build_style_context(req)
    n = clamp_count(req.get("num_images", 3))
    slots = resolve_slots(n, images)
    print(f"0) size={ctx['size']}, 제품사진 {len(images)}장, image_keywords={len(ctx['image_keywords'])}개")

    print("1) 이미지 스펙 생성 (prompt_generator)...")
    specs = prompt_generator.generate(req, ctx["image_keywords"], slots)
    for s in specs:
        src = Path(s["image_path"]).name if s.get("image_path") else "t2i"
        print(f"   - [{s['role']}/{s['mode']}] ← {src} | {s['prompt'][:55]}...")

    print("2) 카피 문구 생성 (copy_generator)...")
    copies = copy_generator.generate(req, specs, ctx["copy_directives"])
    for c in copies:
        print(f"   - {c.get('headline', '')} / {c.get('sub', '')} / {c.get('points', [])}")

    if skip_image:
        print("\nskip_image=True → 이미지 생성을 건너뜁니다. (텍스트 로직만 확인)")
        return []

    if first_only:
        specs, copies = specs[:1], copies[:1]
        print("\nfirst_only=True → 첫 컷 1장만 생성합니다. (이미지 비용 최소)")

    outputs: list[Path] = []
    for i, (spec, copy) in enumerate(zip(specs, copies), start=1):
        print(f"3) 이미지 {i}/{len(specs)} 생성 (mode={spec['mode']})...")
        t = time.time()
        img = image_generator.generate_image(spec, spec.get("image_path"), ctx["size"])
        img = renderer.render(img, copy, spec.get("text_zone", "bottom"))
        out = config.OUTPUT_DIR / f"{name}_{i}_{spec['role']}.png"
        img.save(out)
        print(f"   저장: {out}  ({time.time() - t:.1f}s)")
        outputs.append(out)

    print(f"\n완료 — {len(outputs)}장 생성됨 → {config.OUTPUT_DIR}")
    return outputs


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--request",
                   default=str(Path(__file__).parent / "sample_request.json"),
                   help="요청 JSON 경로")
    p.add_argument("--image", default=None,
                   help="제품 사진 경로 (기본: image/ 폴더 자동 탐색)")
    p.add_argument("--skip-image", action="store_true",
                   help="이미지 생성 없이 텍스트 로직만 테스트 (텍스트 비용만)")
    p.add_argument("--first-only", action="store_true",
                   help="첫 컷 1장만 생성 (이미지 비용 최소)")
    p.add_argument("--check", action="store_true",
                   help="API 호출 없이 설정/입력만 점검 (비용 0)")
    p.add_argument("--name", default="result",
                   help="출력 파일명 접두어 (예: --name exp01 → exp01_1_hero.png)")
    a = p.parse_args()

    if a.check:
        check(a.request, a.image)
    else:
        run(a.request, a.image, a.skip_image, a.first_only, a.name)
