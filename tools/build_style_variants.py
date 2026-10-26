"""Thumb A|B 팝업용 변형 그림 묶음(JSON)을 굽는다 - HF 에 올려 지연 다운로드한다(사용자 결정 2026-10-26).

입력 = C:/VNR/DEV/261026 의 생성 결과(tools/build_style_thumbnails.py 와 같은 곳) + data/taglist/style_meta_tags.json(v3).
출력 = <out>/NAIA_style_variants_261026.json  - 이 저장소의 규칙대로 JSON(캐릭터 확장 팩과 같은 모양 · 사용자 지시).
서버는 캐릭터 팩처럼 `thumbs` 의 바이트 위치만 색인해(core/character_preview_index.PreviewKeyIndex) 필요한 그림만 꺼낸다 -
그래서 작은 `index` 를 **`thumbs` 앞에** 둔다(통째로 파싱하지 않고 앞부분만 읽을 수 있게).

  {"note": [...], "version": 1, "size": 768, "quality": 85, "format": "webp",
   "bases": {"preset": {"gt": "preset/__gt__"}, "bare": {"gt": "bare/__gt__"}},
   "index": {"<tag>": {"base": "preset|bare",
                       "variants": [{"col": "uc5", "place": "uc", "weight": 5, "key": "preset/<slug>__uc5"}, ...]}},
   "thumbs": {"preset/<slug>__uc5": "<base64 WebP 768px q85>", ..., "preset/__gt__": "...", "bare/__gt__": "..."}}
  variants 의 차례 = UC(가중치 큰 것부터) -> POS(작은 것부터). 음수 POS(-1 / -0.5)는 맨 끝.
  place: "uc" = 네거티브에 w::tag :: · "pos" = 프롬프트 끝에 w::tag :: · "front" = 프롬프트 맨 앞(가중치 없음, 단일)

  python tools/build_style_variants.py [--src C:/VNR/DEV/261026] [--out C:/VNR/DEV/261026/style_variants] [--workers 8]
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import re
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
META_PATH = ROOT / "data" / "taglist" / "style_meta_tags.json"
PACK_NAME = "NAIA_style_variants_261026.json"
SIZE, QUALITY = 768, 85
COL_RE = re.compile(r"^(uc|pos_[pm]|front_p)(\d+(?:_\d+)?)$")


def slug(tag: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", tag.lower()).strip("_")


def parse_col(col: str) -> tuple[str, float] | None:
    """파일 이름의 칸 -> (place, weight). uc5 · uc2_5 · uc0_25 · pos_p1 · pos_m0_5 · front_p1."""
    m = COL_RE.match(col)
    if not m:
        return None
    head, num = m.group(1), float(m.group(2).replace("_", "."))
    if head == "uc":
        return "uc", num
    if head == "front_p":
        return "front", num
    return "pos", -num if head == "pos_m" else num


def order_key(v: dict) -> tuple:
    if v["place"] == "uc":
        return (0, -v["weight"])
    if v["place"] == "front":
        return (1, 0)
    return (1, v["weight"]) if v["weight"] > 0 else (2, -v["weight"])


def encode(path: str) -> bytes:
    image = Image.open(path).convert("RGB")
    if image.size != (SIZE, SIZE):
        image = image.resize((SIZE, SIZE), Image.LANCZOS)
    buffer = io.BytesIO()
    image.save(buffer, "WEBP", quality=QUALITY, method=4)
    return buffer.getvalue()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--src", default=r"C:\VNR\DEV\261026")
    parser.add_argument("--out", default=r"C:\VNR\DEV\261026\style_variants")
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    src, out = Path(args.src), Path(args.out)
    roots = {"preset": src / "thumb_run", "bare": src / "thumb_run_bare"}
    meta = json.loads(META_PATH.read_text(encoding="utf-8"))
    assert meta.get("version") == 3

    index = {"tags": {}}
    jobs: list[tuple[str, str]] = [(str(roots[b] / "gt.png"), f"{b}/__gt__") for b in roots]
    for cat in meta["categories"].values():
        base = cat["base"]
        root = roots[base]
        for tag in cat["tags"]:
            variants = []
            for path in sorted(root.glob(f"*/{slug(tag)}__*.png")):
                if "_discarded" in path.parts or "grids" in path.parts:
                    continue
                col = path.stem.split("__", 1)[1]
                parsed = parse_col(col)
                if parsed is None:
                    continue
                place, weight = parsed
                key = f"{base}/{slug(tag)}__{col}"
                weight = int(weight) if weight == int(weight) else weight
                variants.append({"col": col, "place": place, "weight": weight, "key": key})
                jobs.append((str(path), key))
            variants.sort(key=order_key)
            index["tags"][tag] = {"base": base, "variants": variants}
    missing_p1 = [t for t, v in index["tags"].items() if not any(x["col"] in ("pos_p1", "front_p1") for x in v["variants"])]
    print(f"tags {len(index['tags'])} · images {len(jobs)} · no POS1 {missing_p1}")
    assert not missing_p1

    out.mkdir(parents=True, exist_ok=True)
    tmp = out / (PACK_NAME + ".part")
    head = {
        "note": ["Thumb A|B 변형 그림 묶음(HF 지연 다운로드 · tools/build_style_variants.py).",
                 "index = 태그별 기준과 변형 목록 · thumbs = 키 -> base64 WebP 768px q85."],
        "version": 1, "size": SIZE, "quality": QUALITY, "format": "webp",
        "bases": {b: {"gt": f"{b}/__gt__"} for b in roots},
        "index": index["tags"],
    }
    with ProcessPoolExecutor(max_workers=args.workers) as pool, open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(head, ensure_ascii=False)[:-1] + ', "thumbs": {')
        for n, ((_, key), data) in enumerate(zip(jobs, pool.map(encode, [p for p, _ in jobs], chunksize=8)), 1):
            fh.write(("" if n == 1 else ", ") + json.dumps(key) + ": " + json.dumps(base64.b64encode(data).decode("ascii")))
            if n % 200 == 0:
                print(f"  {n}/{len(jobs)}", flush=True)
        fh.write("}}\n")
    json.loads(tmp.read_text(encoding="utf-8"))          # 깨진 JSON 을 올리지 않게 한 번 통째로 읽어 본다
    final = out / PACK_NAME
    tmp.replace(final)
    print(f"wrote {final} {final.stat().st_size / 1e6:.1f}MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
