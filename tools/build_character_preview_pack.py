# -*- coding: utf-8 -*-
"""캐릭터 미리보기 팩 — 사용자 썸네일이 없을 때의 **폴백**.

## 무엇을 위한 것인가

캐릭터 뷰어/프리셋 목록은 9,738명인데 사용자가 직접 만든 썸네일은 소수다(현재 40장).
나머지는 이니셜 타일만 보인다. 그래서 벤치로 뽑은 그림을 **번들 폴백**으로 깐다.

우선순위는 사용자 지정이다:

    1순위  사용자의 캐릭터 썸네일 (user-data/data/character_thumbnails/)
    2순위  이 미리보기 팩 (번들)

즉 이 팩은 사용자가 만든 것을 **덮지 않는다.** 서비스가 1순위를 먼저 보고 없을 때만 이걸 쓴다.

## 크기 — 384px / webp q72

처음에는 256 으로 정했다. **목록 칸(80px)만 보고 고른 값이라 틀렸다** — 프리셋 앵커
카드가 썸네일을 200px 로 크게 보여주게 되면서 256 은 여유가 1.28배밖에 안 남았고,
고DPI 화면에서는 그대로 확대되어 보인다. 384 면 200px 박스에 1.9배다.

    192px    눈매·옷깃 선이 뭉갠다
    256 q60  머리카락 경계에 압축 얼룩
    256 q72  목록(80px)에서는 깨끗하다. 카드(200px)에서는 여유가 없다
    384 q72  카드에서도 깨끗하다  <- 채택

전체 9,738명을 다 넣을 수는 없다. **빈도 상위 N명만** 넣는 것을 전제로 한다
(와일드카드가 빈도 내림차순이라 `char_00`~`char_02` = 상위 3,000명). 어디까지 넣을지는
`--limit` 으로 정한다.

## 어느 그림이 어느 캐릭터인가

`tools/build_character_wildcards.py` 가 내는 `wildcards/character/_lines.json`
(`와일드카드 한 줄 -> "<작품>::<캐릭터>"`)으로 역추적한다. PNG 프롬프트에 그 줄이 그대로
들어 있기 때문이다. **여기서 규칙을 다시 구현하지 않는다** — 두 곳이 갈라진다.

## 쓰는 법

    python tools/build_character_preview_pack.py .experimental/character_preview_src
    python tools/build_character_preview_pack.py <폴더> --limit 3000 --dry-run

원본 PNG 는 `.experimental/character_preview_src/` 에 둔다(gitignore 됨). 벤치 결과라
사용자의 실제 출력이 아니고 1GB 가 넘어서, `user-data/output/` 에 두면 결과 목록에
섞이고 사용자 데이터 백업에 딸려 간다. 규격을 바꾸면 원본에서 다시 인코딩하므로
**원본을 지우면 안 된다.**
"""
import argparse
import base64
import io
import json
from pathlib import Path

LINES = Path("wildcards/character/_lines.json")
OUT = Path("data/character_preview_thumbs.json")


def prompt_of(image) -> str:
    """NAI PNG 의 프롬프트. build_interactive_thumbnails 와 같은 규약."""
    info = image.info or {}
    text = str(info.get("Description") or "")
    if text:
        return text
    raw = info.get("Comment")
    if raw:
        try:
            return str((json.loads(raw) or {}).get("prompt") or "")
        except Exception:
            return ""
    return ""


def main() -> int:
    ap = argparse.ArgumentParser(description="캐릭터 미리보기 팩(폴백) 생성")
    ap.add_argument("sources", nargs="+", help="NAI PNG 폴더(들). 하위까지 훑는다")
    ap.add_argument("--size", type=int, default=384)
    ap.add_argument("--quality", type=int, default=72)
    ap.add_argument("--limit", type=int, default=0,
                    help="빈도 상위 N명까지만 담는다(0=제한 없음). 와일드카드가 빈도 "
                         "내림차순이라 _lines.json 의 등장 순서가 곧 빈도 순위다")
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    try:
        from PIL import Image
    except ImportError:
        raise SystemExit("Pillow 가 필요합니다: pip install pillow")

    if not LINES.exists():
        raise SystemExit(f"{LINES} 가 없다. tools/build_character_wildcards.py 를 먼저 돌려라.")
    doc = json.loads(LINES.read_text(encoding="utf-8"))
    line_key: dict[str, str] = doc["lines"]
    # `_lines.json` 은 빈도 내림차순으로 만들어졌다(dict 는 삽입 순서를 유지한다).
    rank = {k: i for i, k in enumerate(line_key.values())}

    out_path = Path(args.out)
    pack: dict[str, str] = {}
    if out_path.exists() and not args.dry_run:
        try:
            doc_old = json.loads(out_path.read_text(encoding="utf-8"))
            # **크기/품질이 바뀌면 증분을 쓰면 안 된다.** 이번에 다시 안 훑는 캐릭터가
            # 옛 해상도로 남아 팩 안에 두 규격이 섞인다.
            if int(doc_old.get("size", 0)) != args.size or int(doc_old.get("quality", 0)) != args.quality:
                print(f"규격 변경({doc_old.get('size')}px q{doc_old.get('quality')}"
                      f" -> {args.size}px q{args.quality}): 기존 팩을 버리고 전부 다시 만든다")
            else:
                pack = doc_old.get("thumbs") or {}
                print(f"기존 팩 {len(pack)}개 로드(증분)")
        except Exception:
            pack = {}

    files = []
    for src in args.sources:
        root = Path(src)
        if not root.exists():
            print(f"  !! 폴더 없음: {root}")
            continue
        files += sorted(root.rglob("*.png"))
    print(f"PNG {len(files)}장 검사 / 대응표 {len(line_key):,}줄")

    added = updated = 0
    unmatched: list[str] = []
    skipped_rank = 0
    for path in files:
        try:
            with Image.open(path) as image:
                image.load()
                prompt = prompt_of(image)
                key = None
                # 프롬프트 안에 와일드카드 줄이 통째로 들어 있다. 가장 긴 것부터 볼 필요는
                # 없다 — 줄이 캐릭터 태그로 시작해 서로 접두가 겹치지 않는다.
                for line, k in line_key.items():
                    if line in prompt:
                        key = k
                        break
                if not key:
                    unmatched.append(path.name)
                    continue
                if args.limit and rank.get(key, 1 << 30) >= args.limit:
                    skipped_rank += 1
                    continue
                img = image.convert("RGB")
                w, h = img.size
                if w != h:                      # 정사각 중앙 크롭(인물은 위쪽이 중요)
                    side = min(w, h)
                    img = img.crop(((w - side) // 2, (h - side) // 3,
                                    (w - side) // 2 + side, (h - side) // 3 + side))
                img = img.resize((args.size, args.size), Image.LANCZOS)
                buf = io.BytesIO()
                img.save(buf, "WEBP", quality=args.quality, method=6)
        except Exception as exc:
            print(f"  !! {path.name}: {exc}")
            continue
        enc = base64.b64encode(buf.getvalue()).decode("ascii")
        if key in pack:
            if pack[key] == enc:
                continue
            updated += 1
        else:
            added += 1
        pack[key] = enc

    print(f"\n신규 {added} / 갱신 {updated} / 매칭 실패 {len(unmatched)}"
          + (f" / 순위 밖 제외 {skipped_rank}" if skipped_rank else ""))
    if unmatched:
        print("  실패 예:", unmatched[:6])
    if args.dry_run:
        print("\n--dry-run: 쓰지 않았습니다.")
        return 0

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({
        "note": [
            "캐릭터 미리보기 팩 — 사용자 썸네일이 없을 때의 폴백(번들).",
            "우선순위: 1) user-data/data/character_thumbnails 2) 이 팩.",
            "이 팩은 사용자가 만든 것을 덮지 않는다.",
            f"{args.size}px / webp q{args.quality} — 프리셋 카드가 200px 로 크게 보여주므로"
            " 256 은 여유가 부족하다(고DPI 에서 확대되어 보인다).",
            "tools/build_character_preview_pack.py 가 만든다.",
        ],
        "size": args.size, "quality": args.quality, "count": len(pack),
        "thumbs": pack,
    }, ensure_ascii=False), encoding="utf-8")
    mb = out_path.stat().st_size / 1024 / 1024
    print(f"저장: {out_path}  ({len(pack)}개 / {mb:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
