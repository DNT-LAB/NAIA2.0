# -*- coding: utf-8 -*-
"""생성 배치를 컨택트시트로 묶는다 — 태그와 이미지가 맞는지 눈으로/Vision 으로 검수.

썸네일은 192px 로 축소돼 팩에 들어가므로, 검수도 '축소 후'에 해야 실사용과 같은
판별 난이도가 된다. 그래서 여기서도 실제 팩과 같은 크롭·크기를 적용한다.

사용
    python tools/thumb_sheet.py <폴더> [--cols 6] [--size 200] [--out sheet.png]
    python tools/thumb_sheet.py <폴더> --pack     # 팩과 같은 192px 중앙크롭으로
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(ROOT))
# 정규식을 두 벌 적어 두었더니 한쪽만 고쳐질 판이었다 — 팩 빌더가 SSOT 다.
# (음수 가중치 제외를 빌더에서만 고치면 이 도구는 계속 `-1::...blurry ::` 를 축으로 읽는다.)
from tools.build_interactive_thumbnails import WEIGHT_RE   # noqa: E402
WILDCARD_DIR = ROOT / "wildcards" / "thumb"


def axis_tags() -> dict[str, str]:
    table = {}
    for path in WILDCARD_DIR.glob("*.txt"):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                table.setdefault(line.strip().lower(), path.stem)
    return table


def prompt_of(image) -> str:
    info = image.info or {}
    desc = info.get("Description") or ""
    if desc:
        return desc
    try:
        return json.loads(info.get("Comment") or "{}").get("prompt", "") or ""
    except Exception:
        return ""


def main() -> int:
    ap = argparse.ArgumentParser(description="썸네일 배치 컨택트시트")
    ap.add_argument("folder")
    ap.add_argument("--cols", type=int, default=6)
    ap.add_argument("--size", type=int, default=200)
    ap.add_argument("--out", default="")
    ap.add_argument("--pack", action="store_true",
                    help="팩과 같은 192px 중앙 정사각 크롭(위쪽 편향)으로 축소해 보여준다")
    ap.add_argument("--max", type=int, default=60, help="시트 한 장에 담을 최대 장수")
    args = ap.parse_args()

    from PIL import Image, ImageDraw

    known = axis_tags()
    root = Path(args.folder)
    files = sorted(root.rglob("*.png"))
    if not files:
        print(f"PNG 가 없습니다: {root}")
        return 1

    items = []
    for path in files:
        image = Image.open(path)
        tag = next((m for m in WEIGHT_RE.findall(prompt_of(image))
                    if m.lower() in known), None)
        items.append((tag or f"?{path.stem}", image.convert("RGB")))

    sheets = [items[i:i + args.max] for i in range(0, len(items), args.max)]
    out_base = Path(args.out) if args.out else root.parent / f"{root.name}_sheet.png"
    written = []
    for si, chunk in enumerate(sheets):
        cols, S, LB = args.cols, args.size, 18
        rows = (len(chunk) + cols - 1) // cols
        sheet = Image.new("RGB", (cols * S, rows * (S + LB)), "white")
        draw = ImageDraw.Draw(sheet)
        for i, (tag, image) in enumerate(chunk):
            x, y = (i % cols) * S, (i // cols) * (S + LB)
            w, h = image.size
            side = min(w, h)
            # 팩 빌더와 같은 크롭: 중앙 정사각, 위쪽으로 편향(얼굴이 살아남게)
            top = (h - side) // 3
            crop = image.crop(((w - side) // 2, top, (w - side) // 2 + side, top + side))
            if args.pack:
                crop = crop.resize((192, 192)).resize((S, S), Image.NEAREST)
            else:
                crop = crop.resize((S, S))
            sheet.paste(crop, (x, y))
            draw.text((x + 3, y + S + 3), tag[:30], fill="black")
        dst = out_base if len(sheets) == 1 else out_base.with_stem(f"{out_base.stem}_{si + 1}")
        sheet.save(dst)
        written.append(dst)
        print(f"{dst}  ({len(chunk)}장, {sheet.size[0]}x{sheet.size[1]})")

    unknown = [t for t, _ in items if t.startswith("?")]
    if unknown:
        print(f"!! 축 태그를 못 찾은 {len(unknown)}장: {unknown[:8]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
