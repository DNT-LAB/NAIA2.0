"""Thumb 데이터(분류표 + 썸네일)를 2026-10-26 생성 실험 결과로 다시 굽는다.

입력(C:/VNR/DEV/261026 · 개발 PC 에만 있다):
  thumb_run/<분류>/<태그>__pos_p1.png      프리셋(Standard 품질 태그 + Heavy UC) 기준 POS 1
  thumb_run/e621/<태그>__pos_p1.png        e621 고유 후보(같은 프리셋 기준)
  thumb_run_bare/<묶음>/<태그>__pos_p1.png  맨바탕(sample.png 설정) 기준 - Novel AI 공식 묶음
  thumb_run_bare/dataset/<태그>__front_p1.png  데이터셋 태그(맨 앞 · 가중치 없음 - 단일 생성)
  thumb_run/gt.png · thumb_run_bare/gt.png 두 기준의 GT
  thumb_v2_additions.json · e621_style_research/e621_only_final.json
출력:
  data/taglist/style_meta_tags.json   version 3 - 'nai_official' 이 첫 분류(소제목 sections) · 아티스트/프랜차이즈 없음
  data/taglist/style_thumbnails.json  태그 -> base64 JPEG(POS 1). 기준 GT 는 '__gt__:preset' · '__gt__:bare' 키.

사용자 결정(2026-10-26): 썸네일 = POS 1 · 아티스트/프랜차이즈 전부 버림 · Novel AI 공식 = 첫 분류 ·
품질/미학 태그는 맨바탕에서만(프리셋 중복은 버림) · tachi-e -> character image(NAI 개명) · 기준이 둘이어도 상관없음.
같은 태그가 두 분류에 있으면(visual novel cg) Novel AI 공식 쪽만 남긴다 - 썸네일이 태그 이름 하나로 저장된다.
e621 고유 후보는 따로 분류를 두지 않고 기존 분류에 나눠 넣고(E621_PLACE), 조명 · 그림자는 효과/시각에서 떼어
'조명/그림자' 분류로 모은다(사용자 지시 2026-10-26).

  python tools/build_style_thumbnails.py [--src C:/VNR/DEV/261026] [--size 512] [--quality 86] [--dry-run]
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import re
import subprocess
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
META_PATH = ROOT / "data" / "taglist" / "style_meta_tags.json"
THUMBS_PATH = ROOT / "data" / "taglist" / "style_thumbnails.json"

NAI_SECTIONS = [
    ("품질 · 미학", "quality", ["best quality", "amazing quality", "great quality", "normal quality", "bad quality",
                              "worst quality", "masterpiece", "top aesthetic", "very aesthetic", "aesthetic",
                              "displeasing", "very displeasing"]),
    ("복잡도", "complexity", ["low complexity", "medium complexity", "high complexity", "ultra complexity", "depthness"]),
    ("연도", "year", [f"year {y}" for y in range(2026, 2013, -1)]),
    ("V5 메타", "v5_meta", ["meta:novel era", "meta:golden era", "visual novel art", "visual novel bg",
                           "visual novel cg", "visual novel chibi", "visual novel sprite"]),
    ("기타", "other", ["character image", "location", "artist collaboration"]),
    ("데이터셋", "dataset", ["fur dataset", "background dataset"]),
]
DROP_FROM_STYLE = {"named_style"}
DROP_TAGS = {"tachi-e"}                     # NAI 가 character image 로 개명 - Novel AI 공식에 있다
# 조명/그림자(사용자 지시 2026-10-26): 효과/시각에서 조명 · 그림자 태그를 떼어 새 분류로 - e621 조명 태그도 여기로.
LIGHTING_FROM_EFFECTS = ["backlighting", "sidelighting", "spotlight", "shade", "shadow", "colored shadow",
                         "dim lighting", "complex lighting"]
# e621 고유 후보는 따로 분류를 두지 않고 기존 분류에 나눠 넣는다(사용자 지시 2026-10-26). 그림은 thumb_run/e621/.
E621_PLACE = {
    "era_style": ["y2k (graphic design)"],
    "art_style": ["soviet cartoon", "noir", "manga style"],
    "rendering_technique": ["realistic shading", "detailed shading", "shaded sketch", "inked",
                            "perspective-incorrect texturing", "painted background", "textured background",
                            "silhouette background"],
    "color_palette": ["gradient", "natural colors", "low contrast"],
    "lighting": ["warm lighting", "realistic lighting", "rim light", "cast shadow", "dramatic lighting", "blacklight",
                 "soft lighting", "bisexual lighting"],
    "effects": ["dripping contour"],
}


def slug(tag: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", tag.lower()).strip("_")


def encode(path: Path, size: int, quality: int) -> str:
    image = Image.open(path).convert("RGB")
    if image.size != (size, size):
        image = image.resize((size, size), Image.LANCZOS)
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=quality, optimize=True)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--src", default=r"C:\VNR\DEV\261026")
    parser.add_argument("--size", type=int, default=512)
    parser.add_argument("--quality", type=int, default=86)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--base-rev", default="b01fc776", help="원래(v2) 분류표를 읽을 git 커밋")
    args = parser.parse_args()
    src = Path(args.src)
    preset, bare = src / "thumb_run", src / "thumb_run_bare"

    # 원래 분류표(v2)는 git 에서 읽는다 - 이 도구가 쓴 v3 를 다시 읽으면 자기 출력을 입력으로 삼는다.
    old = json.loads(subprocess.run(["git", "show", f"{args.base_rev}:data/taglist/style_meta_tags.json"], cwd=ROOT,
                                    capture_output=True, check=True).stdout.decode("utf-8"))
    assert old.get("version") == 2, f"{args.base_rev} 의 분류표가 v2 가 아니다"
    additions = json.loads((src / "thumb_v2_additions.json").read_text(encoding="utf-8"))
    e621 = json.loads((src / "e621_style_research" / "e621_only_final.json").read_text(encoding="utf-8"))

    nai_tags = {t for _, _, tags in NAI_SECTIONS for t in tags}
    categories: dict[str, dict] = {}
    images: dict[str, Path] = {}
    missing: list[str] = []

    # 1) Novel AI 공식 - 맨바탕 기준
    nai_all = []
    sections = []
    for name, group, tags in NAI_SECTIONS:
        kept = []
        for tag in tags:
            col = "front_p1" if group == "dataset" else "pos_p1"
            path = bare / group / f"{slug(tag)}__{col}.png"
            if path.exists():
                images[tag] = path
                kept.append(tag)
            else:
                missing.append(f"nai_official/{tag}")
        sections.append({"name": name, "tags": kept, **({"single": True} if group == "dataset" else {})})
        nai_all += kept
    categories["nai_official"] = {
        "name": "Novel AI 공식",
        "description": "NovelAI 문서 · 내장 Memo 의 특수 태그(품질 · 미학 · 복잡도 · 연도 · V5 메타 · 데이터셋). 맨바탕 기준으로 생성",
        "base": "bare",
        "sections": sections,
        "tags": nai_all,
    }

    # 2) 기존 분류 + v2 추가 - 프리셋 기준 (아티스트/프랜차이즈 · NAI 공식과 겹치는 태그 · tachi-e 제외)
    for key, info in old["categories"].items():
        if key in DROP_FROM_STYLE:
            continue
        tags = list(info.get("tags", [])) + [row["tag"] for row in additions.get(key, [])]
        kept, seen = [], set()
        for tag in tags:
            if tag in seen or tag in nai_tags or tag in DROP_TAGS:
                continue
            seen.add(tag)
            path = preset / key / f"{slug(tag)}__pos_p1.png"
            if path.exists():
                images[tag] = path
                kept.append(tag)
            else:
                missing.append(f"{key}/{tag}")
        categories[key] = {"name": info["name"], "description": info.get("description", ""), "base": "preset", "tags": kept}

    # 3) 조명/그림자 - 효과/시각에서 떼어 색상/팔레트 바로 뒤에 둔다
    effects = categories["effects"]
    lighting = [tag for tag in LIGHTING_FROM_EFFECTS if tag in effects["tags"]]
    effects["tags"] = [tag for tag in effects["tags"] if tag not in lighting]
    ordered = {}
    for key, info in categories.items():
        ordered[key] = info
        if key == "color_palette":
            ordered["lighting"] = {"name": "조명/그림자", "description": "광원 · 조명 연출 · 그림자", "base": "preset",
                                   "tags": lighting}
    categories = ordered

    # 4) e621 고유 - 프리셋 기준(밑줄 -> 공백으로 생성했다) · 기존 분류에 나눠 넣는다
    e621_names = {row["tag"].replace("_", " ") for row in e621}
    placed = {tag for tags in E621_PLACE.values() for tag in tags}
    assert placed == e621_names, f"E621_PLACE 와 후보 목록이 다르다: {sorted(placed ^ e621_names)}"
    for key, tags in E621_PLACE.items():
        for tag in tags:
            path = preset / "e621" / f"{slug(tag)}__pos_p1.png"
            if tag in images:
                continue
            if path.exists():
                images[tag] = path
                categories[key]["tags"].append(tag)
            else:
                missing.append(f"e621/{tag}")

    meta = {
        "version": 3,
        "description": old.get("description", ""),
        "generated": "2026-10-26 생성 실험(tools/build_style_thumbnails.py)",
        "thumbnail": "POS 1 (프롬프트 끝에 1::tag ::) · 512px JPEG",
        "bases": {
            "preset": {"name": "프리셋", "gt": "__gt__:preset",
                       "note": "Standard 품질 태그 + Heavy UC · seed 1426599 · V5 Full · 18 steps · CFG 6.3 · 1024x1024"},
            "bare": {"name": "맨바탕", "gt": "__gt__:bare",
                     "note": "UC 없음 · 품질 태그 없음 · seed 1426599 · V5 Full · 18 steps · CFG 6.3 · 1024x1024"},
        },
        "sources": old.get("sources", []) + ["2026-10-26 thumb_run · thumb_run_bare · e621_style_research"],
        "categories": categories,
    }
    images["__gt__:preset"] = preset / "gt.png"
    images["__gt__:bare"] = bare / "gt.png"

    counts = {k: len(v["tags"]) for k, v in categories.items()}
    print("categories", counts, "total tags", sum(counts.values()), "images", len(images))
    print("missing", len(missing), missing[:20])
    if args.dry_run:
        return 0
    thumbs = {tag: encode(path, args.size, args.quality) for tag, path in images.items()}
    META_PATH.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    THUMBS_PATH.write_text(json.dumps(thumbs, ensure_ascii=False), encoding="utf-8", newline="\n")
    print("wrote", META_PATH, THUMBS_PATH, f"{THUMBS_PATH.stat().st_size / 1e6:.1f}MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
