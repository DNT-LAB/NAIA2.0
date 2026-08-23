"""`copyright_groups.json` 을 `character_analysis.json` 에 맞춘다 — 없는 것만 **추가**한다.

캐릭터 탭은 두 파일을 **서로 다른 원천으로** 쓴다:

    좌측 작품 목록 · 그룹별 개수   copyright_groups.json   (`_group_counts`)
    카드 · 검색 · 헤더 총계        character_analysis.json (`_iter_all_chars`)

그래서 프로필만 늘리면 **작품별로는 도달할 수 없는 캐릭터가 쌓인다.** 실측으로
헤더 `11,890 characters` 옆에 좌측 `All 9,738` 이 떠 있었고, 차이 2,152 는 정확히
증분으로 들어온 종수였다. 그것들은 "All" 로만 보이고 작품을 눌러서는 안 나온다.

⚠️ **프로필을 늘릴 때마다 이 도구를 같이 돌려야 한다.** 안 그러면 새 캐릭터가
   늘어난 만큼 도달 불가도 늘어난다.

규약:
  · 추가만 한다. 기존 항목은 한 글자도 바꾸지 않는다(멱등).
  · 성별은 프로필의 `gender` 를 따른다. 없으면 `girl`(프로필이 `1girl solo`
    필터에서 나오므로).
  · 배열이 이미 이름순이면 정렬을 유지해 끼워 넣고, 아니면 뒤에 붙인다 —
    사람이 손대던 파일이라 원래 순서를 흐트러뜨리지 않는 편이 diff 가 읽힌다.
  · CRLF 를 보존한다(원본이 CRLF 라 `\\n` 으로 쓰면 1.2MB 가 통째로 diff 에 잡힌다).

    python tools/sync_copyright_groups.py            # dry-run
    python tools/sync_copyright_groups.py --apply
"""

from __future__ import annotations

import argparse
import json
import shutil
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "data"
GROUPS_PATH = DATA_DIR / "copyright_groups.json"
ANALYSIS_PATH = DATA_DIR / "character_analysis.json"

# ⚠️ 원본이 CRLF 다(실측 66,657줄). `write_text` 는 `\n` 으로 써서 파일이 통째로
# diff 에 잡힌다 — `merge_character_profile_increment.py` 와 같은 규약.
NEWLINE = "\r\n"

SIDES = ("girl", "boy")


def write_preserving_crlf(path: Path, text: str) -> None:
    path.write_bytes(text.replace("\r\n", "\n").replace("\n", NEWLINE).encode("utf-8"))


def existing_pairs(groups: dict) -> set[tuple[str, str]]:
    out: set[tuple[str, str]] = set()
    for key, data in groups.items():
        if str(key).startswith("_") or not isinstance(data, dict):
            continue
        for side in SIDES:
            for entry in (data.get(side) or []):
                name = entry.get("name") if isinstance(entry, dict) else entry
                if name:
                    out.add((key, str(name)))
    return out


def insert_sorted_or_append(arr: list, entry: dict) -> None:
    """이미 이름순이면 자리를 지켜 끼우고, 아니면 뒤에 붙인다."""
    names = [e.get("name", "") for e in arr if isinstance(e, dict)]
    if names == sorted(names):
        pos = 0
        while pos < len(arr) and str(arr[pos].get("name", "")) < entry["name"]:
            pos += 1
        arr.insert(pos, entry)
    else:
        arr.append(entry)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="실제로 파일을 쓴다")
    args = ap.parse_args()

    groups = json.loads(GROUPS_PATH.read_text(encoding="utf-8"))
    analysis = json.loads(ANALYSIS_PATH.read_text(encoding="utf-8"))

    have = existing_pairs(groups)
    want: list[tuple[str, str, dict]] = []
    for group_key, members in analysis.items():
        if not isinstance(members, dict):
            continue
        for name, data in members.items():
            if isinstance(data, dict) and (group_key, name) not in have:
                want.append((group_key, name, data))

    total_analysis = sum(len(v) for v in analysis.values() if isinstance(v, dict))
    print(f"프로필 {total_analysis:,}종 / 그룹 명단 {len(have):,}종")
    print(f"  추가 대상 {len(want):,}종  <- 지금 작품별로 도달 불가한 것")
    if not want:
        print("  이미 동기화돼 있다.")
        return 0

    new_groups = sorted({g for g, _, _ in want} - {k for k in groups if not str(k).startswith("_")})
    sides = Counter(str(d.get("gender") or "girl") for _, _, d in want)
    print(f"  새 작품 {len(new_groups):,}개 · 성별 " +
          " · ".join(f"{k} {v:,}" for k, v in sides.most_common()))
    print("\n  [상위 작품]")
    for grp, n in Counter(g for g, _, _ in want).most_common(8):
        print(f"    {grp[:44]:<44} {n:,}종")
    if new_groups:
        print("\n  [새 작품 표본]")
        for grp in new_groups[:8]:
            print(f"    {grp[:52]}")

    added = 0
    for group_key, name, data in want:
        side = str(data.get("gender") or "girl")
        if side not in SIDES:
            side = "girl"
        bucket = groups.setdefault(group_key, {"girl": [], "boy": []})
        if not isinstance(bucket, dict):
            continue
        # 이름과 별칭은 프로필 것을 그대로 쓴다 — 카드가 그 이름으로 뜬다.
        aliases = data.get("aliases")
        entry = {"name": name,
                 "aliases": list(aliases) if isinstance(aliases, list) and aliases else [name]}
        insert_sorted_or_append(bucket.setdefault(side, []), entry)
        added += 1

    text = json.dumps(groups, ensure_ascii=False, indent=2)
    # ⚠️ CRLF 기준으로 재야 한다. `json.dumps` 는 LF 라 그대로 비교하면 줄 수만큼
    #    작아 보여 추가를 했는데 파일이 줄어드는 것처럼 나온다.
    predicted = len(text.encode("utf-8")) + text.count("\n")
    if not args.apply:
        print(f"\n  [dry-run] {added:,}종 추가 예정 · "
              f"예상 {predicted/1024/1024:.2f} MB (현재 {GROUPS_PATH.stat().st_size/1024/1024:.2f} MB)")
        return 0

    shutil.copy2(GROUPS_PATH, GROUPS_PATH.with_suffix(".json.bak"))
    write_preserving_crlf(GROUPS_PATH, text)
    print(f"\n  {GROUPS_PATH}  {GROUPS_PATH.stat().st_size/1024/1024:.2f} MB "
          f"({added:,}종 추가, .bak 보관)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
