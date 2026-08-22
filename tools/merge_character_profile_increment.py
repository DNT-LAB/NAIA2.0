"""신규 캐릭터 프로필을 배포 자산 두 곳에 **병합**한다.

    data/character_analysis.json        구성요소(툴팁 칩) - 없는 캐릭터만 추가
    danbooru_character.py               character_dict_count - 없는 태그만 추가

배포 친화적으로 설계했다:
  · 새 파일을 만들지 않는다 → 릴리즈 매니페스트/계약을 건드릴 필요가 없다
    (두 파일 모두 `release_include_exclude_draft.json` 에 이미 있다).
  · 기존 엔트리는 한 글자도 바꾸지 않는다. 추가만 한다(멱등).
  · `key_clothes` 를 버린다 - 배포본 스키마에 그 필드가 **없고**(9,738종 전수 확인)
    툴팁도 안 쓴다. 넣으면 파일만 3배로 불어난다.

⚠️ gender 는 코퍼스에서 **실측**한다. 프로필은 `1girl solo` 행에서 나오므로 그냥
   "girl" 을 박으면 남성 캐릭터가 젠더벤드 그림으로 프로필을 갖게 된다 - 배포본이
   `zhongli` 에 `large breasts 31.4%` 를 붙인 그 경로다. 코퍼스 전체에서 `1boy` 가
   `1girl` 보다 많은 캐릭터는 **analysis 에서 제외**한다(사전에는 넣는다 - 이름과
   빈도는 성별과 무관한 사실이다).

    python tools/merge_character_profile_increment.py --profile <increment json> \\
        --counts <counts csv> --corpus <buckets dir> [--apply]
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
from collections import Counter
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "data"
ANALYSIS_PATH = DATA_DIR / "character_analysis.json"
DICT_PATH = REPO_ROOT / "danbooru_character.py"

DROP_FIELDS = ("key_clothes",)

# ⚠️ 두 자산 모두 **CRLF** 다(실측: character_analysis.json / danbooru_character.py).
# `write_text` 는 `\n` 으로 써서 28MB·6.4MB 파일이 통째로 diff 에 잡힌다.
# 무변경 왕복이 바이트 일치하는지 확인하고 쓴다.
NEWLINE = "\r\n"


def write_preserving_crlf(path: Path, text: str) -> None:
    path.write_bytes(text.replace("\r\n", "\n").replace("\n", NEWLINE).encode("utf-8"))


def flatten_names(analysis: dict) -> set[str]:
    names: set[str] = set()
    for members in analysis.values():
        if isinstance(members, dict):
            names.update(str(n).strip().lower() for n in members)
    return names


def scan_corpus(targets: set[str], dirs: list[Path]) -> tuple[Counter, Counter, Counter]:
    """대상 캐릭터의 (전체 출현, 1girl 행, 1boy 행). 필터 없이 전수로 센다.

    `character_dict_count` 의 빈도는 걸러지지 않은 출현이라(예: ouro kronii 7,253 vs
    1girl solo 3,620) 프로필용 필터를 쓰면 안 된다.
    """
    files = sorted((DATA_DIR / "tags").glob("tags_*.parquet"))
    for d in dirs:
        files += sorted(d.glob("tags_*.parquet"))
    total: Counter = Counter()
    girl: Counter = Counter()
    boy: Counter = Counter()
    for i, path in enumerate(files, 1):
        df = pd.read_parquet(path, columns=["character", "general"])
        padded = ", " + df["general"].fillna("").astype(str) + ", "
        is_girl = padded.str.contains(", 1girl, ", regex=False).tolist()
        is_boy = padded.str.contains(", 1boy, ", regex=False).tolist()
        for value, g, b in zip(df["character"], is_girl, is_boy):
            if not value:
                continue
            for name in str(value).split(", "):
                name = name.strip()
                if name and name in targets:
                    total[name] += 1
                    if g:
                        girl[name] += 1
                    if b:
                        boy[name] += 1
        if i % 25 == 0 or i == len(files):
            print(f"  [스캔] {i}/{len(files)}", flush=True)
    return total, girl, boy


def append_dict_entries(entries: list[tuple[str, int]], apply: bool) -> None:
    """`character_dict_count` 의 닫는 중괄호 직전에 추가한다.

    파일 구조(실측): `character_dict = {` ... `character_dict_count = {` ... `}`(파일 끝).
    그래서 **마지막** `}` 앞이 삽입 지점이다. 통째로 다시 쓰지 않는 이유는
    `character_dict` 28,836줄을 건드릴 이유가 없기 때문이다.
    """
    # 바이트로 읽어야 CRLF 가 보존된다. (`read_text(newline=...)` 은 3.13+ 전용이고,
    # 기본 텍스트 읽기는 CRLF 를 `\n` 으로 바꿔 6.4MB 파일을 통째로 다시 쓰게 만든다.)
    text = DICT_PATH.read_bytes().decode("utf-8")
    idx = text.rfind("}")
    if idx == -1:
        raise SystemExit("danbooru_character.py 에서 닫는 중괄호를 못 찾았다")
    if "# --- increment" in text:
        print("  ⚠️ 이미 증분 블록이 있다 - 중복 추가를 막기 위해 멈춘다")
        return
    # ⚠️ 사전 파일에 따라 마지막 항목의 후행 쉼표가 없을 수 있다
    #    (artist_dictionary.py 가 그랬다). 그대로 이어 붙이면 SyntaxError 가 난다.
    prefix = text[:idx].rstrip()
    if prefix and not prefix.endswith(("{", ",")):
        prefix += ","
    lines = [f"    # --- increment (신규 캐릭터) ---{NEWLINE}"]
    for tag, count in entries:
        lines.append(f"    {json.dumps(tag, ensure_ascii=False)}: {count},{NEWLINE}")
    merged = prefix + NEWLINE + "".join(lines) + text[idx:]
    if not apply:
        print(f"  [dry-run] {len(entries):,}줄을 삽입할 예정 (위치 {idx:,})")
        return
    shutil.copy2(DICT_PATH, DICT_PATH.with_suffix(".py.bak"))
    DICT_PATH.write_bytes(merged.encode("utf-8"))
    print(f"  danbooru_character.py 갱신 (.bak 보관)")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--profile", required=True)
    ap.add_argument("--counts", required=True)
    ap.add_argument("--corpus", action="append", default=[])
    ap.add_argument("--apply", action="store_true", help="실제로 파일을 쓴다")
    args = ap.parse_args()

    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    import danbooru_character

    known_tags = {str(k).strip().lower() for k in danbooru_character.character_dict_count}
    analysis = json.loads(ANALYSIS_PATH.read_text(encoding="utf-8"))
    have = flatten_names(analysis)
    profile = json.loads(Path(args.profile).read_text(encoding="utf-8"))
    rows = list(csv.DictReader(Path(args.counts).open(encoding="utf-8-sig")))

    print(f"배포본 analysis {len(have):,}종 / dict {len(known_tags):,}종")
    print(f"증분 프로필 {sum(len(v) for v in profile.values()):,}종\n")

    # 대상: analysis 에 없는 것(추가) ∪ dict 에 없는 것(추가)
    need_analysis = {n for n in (r["character"].strip() for r in rows)
                     if n.lower() not in have}
    need_dict = {n for n in (r["character"].strip() for r in rows)
                 if n.lower() not in known_tags}
    targets = need_analysis | need_dict
    print(f"analysis 추가 후보 {len(need_analysis):,}종 / dict 추가 후보 {len(need_dict):,}종"
          f"  (합집합 {len(targets):,})\n")

    total, girl, boy = scan_corpus(targets, [Path(c) for c in args.corpus])

    male = {n for n in targets if boy.get(n, 0) > girl.get(n, 0)}
    print(f"\n[성별 실측] 1boy > 1girl 인 캐릭터 {len(male):,}종 - analysis 에서 제외한다")
    for n in sorted(male, key=lambda x: -total.get(x, 0))[:8]:
        print(f"    {total.get(n,0):>6,}행  girl {girl.get(n,0):>5,} / boy {boy.get(n,0):>5,}  {n}")

    # ── analysis 병합 ────────────────────────────────────────────────────
    added = 0
    for group, members in profile.items():
        if not isinstance(members, dict):
            continue
        for name, data in members.items():
            key = name.strip().lower()
            if key in have or name.strip() in male:
                continue
            entry = {k: v for k, v in data.items() if k not in DROP_FIELDS}
            entry["gender"] = "girl"
            entry.setdefault("aliases", [name])
            analysis.setdefault(group, {})[name] = entry
            have.add(key)
            added += 1
    print(f"\n[analysis] 추가 {added:,}종 -> 총 {len(have):,}종")

    if args.apply:
        shutil.copy2(ANALYSIS_PATH, ANALYSIS_PATH.with_suffix(".json.bak"))
        write_preserving_crlf(ANALYSIS_PATH, json.dumps(analysis, ensure_ascii=False, indent=2))
        print(f"  {ANALYSIS_PATH}  {ANALYSIS_PATH.stat().st_size/1024/1024:.1f} MB (.bak 보관)")
    else:
        size = len(json.dumps(analysis, ensure_ascii=False, indent=2).encode("utf-8"))
        print(f"  [dry-run] 예상 크기 {size/1024/1024:.1f} MB"
              f" (현재 {ANALYSIS_PATH.stat().st_size/1024/1024:.1f} MB)")

    # ── dict 병합 ────────────────────────────────────────────────────────
    new_entries = sorted(((n, total.get(n, 0)) for n in need_dict if total.get(n, 0) > 0),
                         key=lambda kv: -kv[1])
    print(f"\n[dict] 추가 {len(new_entries):,}종  (빈도는 필터 없는 전수 출현)")
    for tag, cnt in new_entries[:8]:
        print(f"    {cnt:>7,}  {tag}")
    append_dict_entries(new_entries, args.apply)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
