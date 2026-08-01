"""Interactive 모드 특징 썸네일 팩 빌더.

NAI 생성 PNG -> 축/값 자동 분류 -> webp 리사이즈 -> 단일 JSON 팩.

생성 규칙(wildcards/thumb/_manifest.json 의 weight_template):
    베이스 프롬프트 + ``2::<축 값> ::``
따라서 PNG 메타데이터의 프롬프트에서 ``2:: ... ::`` 를 뽑으면 그 이미지가 어떤 축의
어떤 값인지 역추적할 수 있다. 축 소속은 wildcards/thumb/<axis>.txt 로 판정한다.

포맷은 기존 artist_thumbnail_*.json 과 같은 계열이다(키 -> base64 이미지).
core/artist_thumbnail_service.py 의 _image_payload_from_encoded 참고.

사용:
    python tools/build_interactive_thumbnails.py <PNG 폴더> [<폴더> ...]
      [--size 192] [--quality 82] [--out data/interactive_thumbnails.json]

여러 번 돌려도 안전하다 — 기존 팩을 읽어 새로 들어온 값만 갱신한다(증분).

## 폴더를 무엇으로 넘기는가가 결과를 바꾼다

팩은 넘긴 폴더들의 **합병**이다. 그래서 벤치 폴더만 넘기면, 사용자가 나중에 직접 만든
더 새 그림이 옛 벤치 판으로 되돌아간다(실측 94키). 방지책은 두 겹이다.

1. 같은 태그가 여러 번 나오면 **mtime 최신이 이긴다**(순서 무의존).
2. `<팩>.sources.json` 원장에 키마다 넣은 파일과 mtime 을 적고, **원장보다 오래된 파일로는
   바꾸지 않는다.** 어떤 부분집합을 넘겨도 되돌아가지 않는다.

주의: 원장은 이 기능을 붙인 뒤 실제로 넣은 키만 갖고 있다. 그 전에 들어간 레거시 키는
원장에 없어 첫 실행에서 한 번 채택된다 — 그때 `!! 기존 그림을 갈아치운 키` 보고를 읽어라.

2026-07-30 기준 썸네일용으로 쓴 폴더:

    NAIA-Portable/user-data/output/_thumb_bench       (도구 생성분)
    NAIA-Portable/user-data/output/20260730_180749    (사용자 생성분)
    NAIA-Portable/user-data/output/20260730_100105
    NAIA-Portable/user-data/output/20260729_105818
    NAIA-Portable/user-data/output/20260725_103742

**일반 생성 폴더를 전부 넘기지 마라.** 사용자의 평소 그림에도 `2::...::` 가 있어 축 태그와
우연히 맞으면 그 그림이 썸네일로 들어간다.
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

WILDCARD_DIR = REPO_ROOT / "wildcards" / "thumb"
# 성인 축은 생성 대상 폴더 밖(`wildcards/nsfw/`)에 둔다 — 거기 있으면 도구가 축으로
# 읽어 실수로 생성 대상에 들어간다. 그런데 **팩 빌더는 읽어야 한다**: 안 그러면
# 사용자가 직접 만든 그림이 분류 실패로 통째로 버려진다(실측 240장).
# 도감 이름(`nsfw_*`)만 축으로 쓴다 — 벤치 배치 이름과 1:1 이라 키가 어긋나지 않는다.
# 옛 원본 목록(body_nsfw/cloth_nsfw/pose_nsfw*)은 도감으로 갈라졌으므로 축이 아니다.
NSFW_DIR = REPO_ROOT / "wildcards" / "nsfw"
DEFAULT_OUT = REPO_ROOT / "data" / "interactive_thumbnails.json"
# 키마다 "어느 파일의 몇 시 판을 넣었는지" 를 적어 두는 원장.
# 이게 없으면 팩 결과가 **어느 폴더를 인자로 넘겼는지에 의존한다** — 벤치 폴더만 넘긴
# 실행이 사용자 폴더의 더 새 그림 94개를 옛 벤치 판으로 조용히 되돌렸다(실측).
# 원장이 있으면 어떤 부분집합을 넘겨도 "더 오래된 것으로는 바꾸지 않는다" 가 보장된다.
SOURCES_SUFFIX = ".sources.json"

# 2::tag :: / 2:: tag :: 모두 허용. 가중치 숫자는 임의(1.5/2/3...).
#
# **음수 가중치는 제외한다.** 베이스 프롬프트 끝에 `-1::widescreen, blurry ::` 와
# `-1:: thick outlines, ai-generated ::` 가 있고, 이건 '빼는' 블록이다. 그런데 예전 정규식은
# `-` 를 무시해 이것도 후보로 읽었다. 그래서 **VARY 태그가 축 목록에 없는 이미지가 전부
# `fx_effect/blurry` 로 오분류됐다** — 오늘 재분류로 축을 옮긴 태그들이 그렇게 됐고,
# `fx_effect/blurry` 썸네일이 기린 사진(`giraffe tail`)이 되어 있었다(실측).
# 실제 `blurry` 썸네일은 `2.0::blurry ::` 로 들어오므로 이 제외가 그것을 막지는 않는다.
WEIGHT_RE = re.compile(r"(?<![\d.\-])\d+(?:\.\d+)?::\s*(.+?)\s*::")
# 베이스에도 가중치 블록이 있다(0.38::아티스트 ::, -1::widescreen ::). 축 값만 골라야 하므로
# '와일드카드 목록에 있는 태그' 만 채택한다.

# 프론트의 '표시 축' -> 실제 생성 단위(팩 축). 얼굴은 표시만 3그룹으로 쪼개고
# 이미지는 모두 face/* 를 읽는다. interactiveAxes.mjs 의 PACK_AXIS 와 같은 값을 유지해야 한다.
PACK_AXIS = {"face_eyes": "face", "face_parts": "face", "face_mark": "face"}


# 축이 아닌 중간 산출물. 축과 같은 폴더에 같은 접두로 있어서 축으로 세어졌다.
# setdefault 는 알파벳 순 첫 파일이 이기므로 `pose_multi` 가 `pose_posture_m` 의
# 31개를 가로채 그 31장이 UI 에서 안 보였다. 자세 분류 결과(solo/multi/drop)와
# 표정으로 넘긴 목록이 여기 해당한다 — 글로브로 조용히 거르지 않고 이름을 적는다.
# `_` 접두 파일은 축이 아니다(작업 목록·보존 목록). 이름을 하나씩 적다가
# `_relational_meta` 를 빠뜨려 키 하나가 그 축으로 들어갔다 — 접두로 막는다.
# 축 판정은 emit 이 내는 인덱스가 SSOT 다. 목록을 여기 적으면 갈라진다 —
# 실제로 세 도구가 서로 다른 NOT_AXES 를 들고 있었다(tools/thumb_axis_index.py).
from tools.thumb_axis_index import is_axis  # noqa: E402


def load_axis_tags() -> dict[str, str]:
    """tag(소문자) -> axis. wildcards/thumb/<axis>.txt 가 출처."""
    table: dict[str, str] = {}
    if not WILDCARD_DIR.exists():
        raise SystemExit(f"와일드카드 폴더가 없습니다: {WILDCARD_DIR}")
    sources = sorted(WILDCARD_DIR.glob("*.txt"))
    # 도감 이름만(`nsfw_*`). 옛 원본 목록은 태그가 겹쳐 축을 가로챈다.
    sources += sorted(p for p in NSFW_DIR.glob("nsfw_*.txt")) if NSFW_DIR.exists() else []
    for path in sources:
        axis = path.stem
        if not is_axis(axis):
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            tag = line.strip()
            if tag:
                table.setdefault(tag.lower(), axis)
    return table


def prompt_of(image) -> str:
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


def axis_value_of(prompt: str, axis_tags: dict[str, str]) -> tuple[str, str] | None:
    """프롬프트의 가중치 블록 중 축 목록에 있는 값을 찾는다."""
    for candidate in WEIGHT_RE.findall(prompt or ""):
        # 블록 안에 쉼표로 여러 태그가 있을 수 있다(아티스트 믹스). 각각 확인.
        for part in str(candidate).split(","):
            tag = part.strip()
            axis = axis_tags.get(tag.lower())
            if axis:
                return axis, tag
    return None


def to_webp(image, size: int, quality: int) -> bytes:
    from PIL import Image

    img = image
    # 정사각 중앙 크롭 후 축소 — 그리드 셀이 정사각이라 비율 왜곡을 막는다.
    w, h = img.size
    if w != h:
        side = min(w, h)
        left = (w - side) // 2
        top = (h - side) // 3   # 인물은 상단이 중요(얼굴) -> 위쪽으로 치우쳐 크롭
        img = img.crop((left, top, left + side, top + side))
    if img.size[0] > size:
        img = img.resize((size, size), Image.LANCZOS)
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="WEBP", quality=quality, method=6)
    return buf.getvalue()


def main() -> int:
    parser = argparse.ArgumentParser(description="Interactive 특징 썸네일 팩 빌더")
    parser.add_argument("sources", nargs="*", help="NAI PNG 가 있는 폴더(들). 하위 폴더까지 훑는다")
    parser.add_argument("--prune", action="store_true",
                        help="와일드카드 목록에 없어진 키를 정리한다. 태그가 다른 축으로 "
                             "이동한 경우는 삭제하지 않고 그 축으로 키를 옮긴다(이미지 보존)")
    parser.add_argument("--size", type=int, default=192, help="정사각 한 변 픽셀 (기본 192)")
    parser.add_argument("--quality", type=int, default=82, help="webp 품질 (기본 82)")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="출력 JSON 경로")
    parser.add_argument("--dry-run", action="store_true", help="쓰지 않고 분류 결과만 출력")
    args = parser.parse_args()

    try:
        from PIL import Image
    except ImportError:
        print("Pillow 가 필요합니다: pip install pillow")
        return 2

    axis_tags = load_axis_tags()
    print(f"축 태그 사전: {len(axis_tags)}개 / {len(set(axis_tags.values()))}축")

    out_path = Path(args.out)
    pack: dict[str, str] = {}
    if out_path.exists():
        try:
            pack = json.loads(out_path.read_text(encoding="utf-8"))
            print(f"기존 팩 로드: {len(pack)}개")
        except Exception:
            pack = {}
    src_path = out_path.with_name(out_path.name + SOURCES_SUFFIX)
    ledger: dict[str, dict] = {}
    if src_path.exists():
        try:
            ledger = json.loads(src_path.read_text(encoding="utf-8"))
            print(f"소스 원장 로드: {len(ledger)}개")
        except Exception:
            ledger = {}

    # 재분류(축 이동/태그 제거)를 하면 팩에 '고아 키'가 남는다. 축을 옮긴 태그는
    # 이미지를 버리지 않고 키만 옮긴다 — 다시 생성하는 낭비를 막는다.
    orphan_moved, orphan_gone = [], []
    for key in list(pack):
        axis, _, tag = key.partition("/")
        real = PACK_AXIS.get(axis, axis)
        if axis_tags.get(tag.lower()) == real:
            continue
        dest = axis_tags.get(tag.lower())
        if dest:
            orphan_moved.append((key, f"{dest}/{tag}"))
        else:
            orphan_gone.append(key)
    if orphan_moved or orphan_gone:
        print(f"\n=== 고아 키 {len(orphan_moved) + len(orphan_gone)}개"
              f"{'' if args.prune else '  (--prune 으로 정리)'} ===")
        for src_key, dst_key in orphan_moved:
            print(f"  이동  {src_key} -> {dst_key}")
        for key in orphan_gone:
            print(f"  삭제  {key}  (축에 없는 태그)")
        if args.prune and not args.dry_run:
            for src_key, dst_key in orphan_moved:
                pack.setdefault(dst_key, pack[src_key])
                del pack[src_key]
            for key in orphan_gone:
                del pack[key]

    files: list[Path] = []
    for src in args.sources:
        root = Path(src)
        if not root.exists():
            print(f"  !! 폴더 없음, 건너뜀: {root}")
            continue
        # 축별로 하위 폴더에 나눠 담아도 되게 재귀 탐색한다(예: <출력>/hair styles/*.png).
        # 축 판정은 폴더명이 아니라 PNG 메타데이터의 2::태그 :: 로 하므로 폴더 이름은 자유다.
        files.extend(sorted(root.rglob("*.png")))
    # **한 태그에 여러 PNG 가 있으면 마지막에 읽힌 것이 이겼다.** 폴더를 어떤 순서로
    # 넘겼는지에 따라 팩이 달라졌고, 그래서 같은 태그가 실행마다 다른 그림이 될 수 있었다
    # (실측: 벤치 폴더만 다시 넣었을 때 155키가 '갱신'으로 뒤집혔다).
    # mtime 오름차순으로 정렬해 **가장 최근에 만든 것이 이기게** 고정한다 — 다시 만든 이유는
    # 앞의 것이 틀렸기 때문이므로 그게 의도에 맞고, 무엇보다 순서에 의존하지 않는다.
    files.sort(key=lambda p: (p.stat().st_mtime, str(p)))
    print(f"PNG {len(files)}장 검사  (같은 태그는 mtime 최신이 이긴다)")

    added, updated, skipped, unmatched = 0, 0, 0, []
    seen_here: dict[str, Path] = {}   # 이번 실행에서 그 키를 만든 파일
    downgraded = 0                    # 원장보다 오래되어 무시한 파일
    conflicts: list[tuple[str, str, str]] = []   # 같은 키를 두 파일이 주장
    replaced: list[str] = []                     # 팩의 기존 그림을 갈아치운 키
    per_axis: dict[str, int] = {}
    for path in files:
        try:
            with Image.open(path) as image:
                image.load()
                found = axis_value_of(prompt_of(image), axis_tags)
                if not found:
                    unmatched.append(path.name)
                    continue
                axis, tag = found
                key = f"{axis}/{tag}"
                if args.dry_run:
                    per_axis[axis] = per_axis.get(axis, 0) + 1
                    print(f"  {path.name} -> {key}")
                    continue
                blob = to_webp(image, args.size, args.quality)
        except Exception as exc:
            print(f"  !! {path.name}: {exc}")
            continue
        if args.dry_run:
            continue
        encoded = base64.b64encode(blob).decode("ascii")
        mtime = path.stat().st_mtime
        # 이번 실행 안에서 같은 키가 두 번 나오면 그건 '갱신' 이 아니라 **소스 충돌**이다.
        # 뭉개서 세면 "갱신 155" 처럼 보여서, 팩이 뒤집힌 것인지 그냥 새로 만든 것인지
        # 구별할 수 없었다. 갈라서 센다.
        if key in seen_here:
            conflicts.append((key, seen_here[key].name, path.name))
        seen_here[key] = path
        # 원장에 적힌 것보다 오래된 파일로는 바꾸지 않는다.
        prev = ledger.get(key)
        if prev and float(prev.get("mtime", 0)) > mtime:
            downgraded += 1
            continue
        if key in pack:
            if pack[key] == encoded:
                skipped += 1
                continue
            updated += 1
            replaced.append(key)
        else:
            added += 1
        pack[key] = encoded
        ledger[key] = {"src": str(path.relative_to(REPO_ROOT)) if REPO_ROOT in path.parents
                       else path.name, "mtime": mtime}
        per_axis[axis] = per_axis.get(axis, 0) + 1

    print("\n=== 축별 분류 ===")
    for axis, count in sorted(per_axis.items(), key=lambda kv: -kv[1]):
        total = sum(1 for a in axis_tags.values() if a == axis)
        print(f"  {axis:<14}{count:>4} / {total}")
    if unmatched:
        print(f"\n분류 실패 {len(unmatched)}장 (가중치 블록에 축 태그 없음): {unmatched[:8]}")

    if args.dry_run:
        print("\n--dry-run: 파일을 쓰지 않았습니다.")
        return 0

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(pack, ensure_ascii=False), encoding="utf-8")
    size_mb = out_path.stat().st_size / (1024 * 1024)
    print(f"\n팩 저장: {out_path}  ({len(pack)}키, {size_mb:.2f} MB)")
    src_path.write_text(json.dumps(ledger, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"  신규 {added} / 교체 {updated} / 동일 {skipped} / 더 오래돼 무시 {downgraded}")
    if replaced:
        # 교체는 조용히 넘기면 안 된다 — 잘 나온 그림을 덜 나온 것으로 바꿀 수 있다.
        print(f"  !! 기존 그림을 갈아치운 키 {len(replaced)}개: {replaced[:12]}")
    if conflicts:
        print(f"  !! 한 태그를 두 파일이 주장 {len(conflicts)}건 (mtime 최신이 이겼다):")
        for k, a, b in conflicts[:12]:
            print(f"       {k}: {a} -> {b}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
