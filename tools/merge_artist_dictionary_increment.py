"""코퍼스에 있는데 자동완성 인덱스에 없는 아티스트를 `artist_dictionary.py` 에 넣는다.

아티스트는 캐릭터와 달리 부속 산출물이 없다 - `artist_dict = {태그: 빈도}` 하나가
전부고, `core/kr_tag_loader.py` 가 그걸 읽어 카테고리 `artist` 로 넣는다.

기본 하한 19 는 임의값이 아니라 **인덱스 자신의 하한**이다(실측: artist_dict 최솟값
19, p1 도 19). 그 아래는 원래 인덱스에 존재할 수 없으므로, 19 로 맞추면 "코퍼스
기준으로 인덱스를 현재 시점까지 끌어올린다" 는 뜻이 된다.

빈도 값은 코퍼스 전수 출현을 쓴다. 두 척도가 같음을 확인했다(인덱스에 있는
68,852종의 코퍼스/인덱스 비율 중앙값 1.00) - 안 맞으면 자동완성 랭킹이 뒤틀린다.

⚠️ 파일은 CRLF 다. 텍스트로 읽고 쓰면 72,299줄이 통째로 diff 에 잡힌다.

    python tools/merge_artist_dictionary_increment.py --tally <csv> [--min-count 19] [--apply]
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DICT_PATH = REPO_ROOT / "artist_dictionary.py"
MARKER = "# --- increment"
NEWLINE = "\r\n"

# Danbooru 의 artist 열에는 아티스트가 아닌 메타 태그가 섞인다. 기존 인덱스도 이걸
# 빼고 만들어졌다(실측: `banned artist` 는 artist_dict 에 없다). 코퍼스에서는
# 58,156회로 **2위(1,285)의 45배** 라 넣으면 자동완성 최상단을 차지해 버린다.
EXCLUDE = {
    "banned artist", "artist request", "anonymous artist", "unknown artist",
    "third-party edit", "self-upload", "md5 mismatch", "duplicate",
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tally", required=True,
                    help="artist_corpus_tally.csv (artist,total,shipped,increment,index)")
    ap.add_argument("--min-count", type=int, default=19,
                    help="코퍼스 전수 출현이 이 값 이상 (기본 19 = 인덱스 하한)")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    import artist_dictionary

    known = dict(artist_dictionary.artist_dict)
    floor = min(known.values()) if known else 0
    print(f"[인덱스] {len(known):,}종  최솟값 {floor}")
    if args.min_count < floor:
        print(f"  ⚠️ 하한 {args.min_count} 이 인덱스 하한 {floor} 보다 낮다"
              f" - 기존에 없던 등급을 새로 들이게 된다")

    rows = list(csv.DictReader(Path(args.tally).open(encoding="utf-8-sig")))
    new = [(r["artist"], int(r["total"])) for r in rows
           if int(r["total"]) >= args.min_count
           and r["artist"] not in known
           and r["artist"].strip().lower() not in EXCLUDE]
    new.sort(key=lambda kv: -kv[1])
    dropped = [r["artist"] for r in rows
               if int(r["total"]) >= args.min_count
               and r["artist"].strip().lower() in EXCLUDE]
    if dropped:
        print(f"[배제] 메타 태그 {len(dropped)}종: {dropped}")
    print(f"[대상] 코퍼스 {len(rows):,}종 중 추가 {len(new):,}종"
          f"  -> {len(known)+len(new):,}종")
    for tag, cnt in new[:8]:
        print(f"    {cnt:>7,}  {tag}")

    text = DICT_PATH.read_bytes().decode("utf-8")
    if MARKER in text:
        print("  ⚠️ 이미 증분 블록이 있다 - 중복 추가를 막기 위해 멈춘다")
        return 1
    idx = text.rfind("}")
    if idx == -1:
        raise SystemExit("artist_dictionary.py 에서 닫는 중괄호를 못 찾았다")

    # ⚠️ 마지막 항목에 후행 쉼표가 **없다**(실측: `"ropa (kaoliang baijiu)": 19` 뒤에
    #    바로 `}`). 그대로 이어 붙이면 SyntaxError 가 난다. 필요할 때만 쉼표를 넣는다.
    prefix = text[:idx].rstrip()
    if prefix and not prefix.endswith(("{", ",")):
        prefix += ","
    lines = [f"    {MARKER} (코퍼스 기준 신규 아티스트) ---{NEWLINE}"]
    for tag, cnt in new:
        lines.append(f"    {json.dumps(tag, ensure_ascii=False)}: {cnt},{NEWLINE}")
    merged = prefix + NEWLINE + "".join(lines) + text[idx:]

    if not args.apply:
        print(f"  [dry-run] {len(new):,}줄 삽입 예정"
              f"  크기 {len(text.encode('utf-8'))/1024/1024:.2f}"
              f" -> {len(merged.encode('utf-8'))/1024/1024:.2f} MB")
        return 0

    shutil.copy2(DICT_PATH, DICT_PATH.with_suffix(".py.bak"))
    DICT_PATH.write_bytes(merged.encode("utf-8"))
    print(f"  artist_dictionary.py 갱신"
          f"  {DICT_PATH.stat().st_size/1024/1024:.2f} MB (.bak 보관)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
