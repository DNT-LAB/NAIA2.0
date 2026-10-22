# -*- coding: utf-8 -*-
"""캐릭터가 **주 그룹 말고도** 들어갈 그룹(추가 소속)을 뽑는다 - 개발 전용(런타임 import 없음).

왜: 그룹 키(`character_analysis.json` 의 맨 위 키)가 단부루 **우산 작품**인 경우가 많아
하위 작품 그룹이 비어 보인다(사용자 제보 2026-10-22). 예: 마키세 크리스는 `science adventure` 에 있고
`steins;gate` 그룹에는 3명뿐이다. 사용자 결정: 한 캐릭터가 **여러 그룹**에 나와도 된다.

정체성(`주그룹::이름` - 썸네일 · 즐겨찾기 · 숨김 · 프리셋 · 확장 팩 키)은 그대로 둔다. 이 파일은
**덧붙이기만** 한다 - 도감 · `copyright_groups.json` 은 손대지 않는다.

주 그룹 G 인 캐릭터의 추가 그룹 =
  (a) G 를 (함의로, 거슬러 올라가며) 함의하는 하위 작품 C 중 그 캐릭터 코퍼스 행의 30% 이상 · 5행 이상(여럿 가능)
  (b) 엔트리의 `copyright` 가 G 와 다르고 `original` 이 아니면 그것
  (c) G 와 (a)(b) 각각의 웃 작품(함의) 중 **이미 그룹 키인 것**만
G 자신 · `original` 은 넣지 않는다. 그 그룹에 같은 이름의 다른 레코드가 이미 있으면 넣지 않는다.
새로 생기는 그룹이 1명뿐이면 넣지 않는다 - 길잡이로 쓸모가 없고 etc(1명 작품 묶음)만 어지럽힌다.

    python tools/build_character_group_membership.py --extra "C:/VNR/DEV/tag_increment_full/buckets"

⚠️ 코퍼스 배포본은 2025-09 에서 끝난다 - 최신 작품(엔드필드 등)은 증분 버킷(--extra)이 있어야 잡힌다.
"""
from __future__ import annotations

import argparse
import glob
import json
import time
from collections import Counter, defaultdict
from pathlib import Path

import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
ORIGINAL = "original"
MIN_SHARE = 0.3
MIN_ROWS = 5
SPOT_CHECK = {
    "steins;gate": ["makise kurisu", "shiina mayuri", "amane suzuha", "hiyajou maho", "kiryuu moeka",
                    "urushibara luka", "akiha rumiho", "okabe rintarou"],
    "arknights: endfield": ["perlica (arknights)", "endministrator (arknights)", "chen qianyu (arknights)",
                            "yvonne (arknights)", "gilberta (arknights)", "angelina (endfield) (arknights)",
                            "xaihi (arknights)", "avywenna (arknights)", "ember (arknights)",
                            "snowshine (arknights)"],
}


def load_parents(path: Path) -> dict[str, set[str]]:
    table = pq.read_table(path, columns=["antecedent_name", "consequent_name", "status"]).to_pydict()
    parents: dict[str, set[str]] = defaultdict(set)
    for child, parent, status in zip(table["antecedent_name"], table["consequent_name"], table["status"]):
        if status == "active" and child and parent:
            parents[str(child).replace("_", " ")].add(str(parent).replace("_", " "))
    return parents


def load_aliases(path: Path) -> tuple[dict[str, str], set[frozenset[str]]]:
    """(활성 별칭 -> 대표 이름, 별칭으로 이어진 적 있는 짝 - 지운 것 포함).

    엔트리 `copyright` 가 그 그룹의 옛 이름 · 다른 표기일 때가 있다(`yuruyuri` 그룹의 `yuru yuri` 11명 ·
    `saki (manga)` 그룹의 `saki` 26명). 그대로 두면 같은 작품 그룹이 둘로 보인다 - 별칭이면 같은 것으로 본다."""
    table = pq.read_table(path, columns=["antecedent_name", "consequent_name", "status"]).to_pydict()
    active: dict[str, str] = {}
    pairs: set[frozenset[str]] = set()
    for old, new, status in zip(table["antecedent_name"], table["consequent_name"], table["status"]):
        if not old or not new:
            continue
        old, new = str(old).replace("_", " "), str(new).replace("_", " ")
        pairs.add(frozenset((old, new)))
        if status == "active":
            active[old] = new
    return active, pairs


def make_ancestors(parents):
    memo: dict[str, frozenset[str]] = {}

    def ancestors(tag: str) -> frozenset[str]:
        if tag not in memo:
            seen, stack = set(), [tag]
            while stack:
                for parent in parents.get(stack.pop(), ()):
                    if parent not in seen and parent != tag:
                        seen.add(parent)
                        stack.append(parent)
            memo[tag] = frozenset(seen)
        return memo[tag]
    return ancestors


def scan_corpus(files: list[str], names: set[str]):
    rows: Counter = Counter()
    copyrights: dict[str, Counter] = defaultdict(Counter)
    for path in files:
        table = pq.read_table(path, columns=["copyright", "character"]).to_pydict()
        for cp, ch in zip(table["copyright"], table["character"]):
            if not ch:
                continue
            works = {x.strip() for x in (cp or "").split(",") if x.strip()}
            for name in {x.strip() for x in ch.split(",") if x.strip()}:
                if name in names:
                    rows[name] += 1
                    for work in works:
                        copyrights[name][work] += 1
    return rows, copyrights


def build(analysis: dict, parents, rows, copyrights, aliases=None):
    ancestors = make_ancestors(parents)
    active, pairs = aliases or ({}, set())
    groups = {g for g, chars in analysis.items() if isinstance(chars, dict) and not g.startswith("_")}
    extra: dict[str, dict[str, str]] = {}           # "G::name" -> {group: 이유 a/b/c}
    for group in sorted(groups):
        for name, data in analysis[group].items():
            if not isinstance(data, dict):
                continue
            found: dict[str, str] = {}
            total = rows.get(name, 0)
            if total:
                for work, count in copyrights[name].items():
                    if work != group and count >= MIN_ROWS and count / total >= MIN_SHARE and group in ancestors(work):
                        found.setdefault(work, "a")
            own = str(data.get("copyright") or "").strip()
            own = active.get(own, own)
            if own and own != group and own != ORIGINAL and frozenset((own, group)) not in pairs:
                found.setdefault(own, "b")
            for base in (group, *list(found)):
                for parent in ancestors(base):
                    if parent in groups:
                        found.setdefault(parent, "c")
            found.pop(group, None)
            found.pop(ORIGINAL, None)
            # 그 그룹에 같은 이름(다른 레코드)이 이미 있으면 겹쳐 보이게 하지 않는다.
            found = {g: why for g, why in found.items() if name not in (analysis.get(g) or {})}
            if found:
                extra[f"{group}::{name}"] = found
    # 새 그룹이 1명뿐이면 버린다.
    members: Counter = Counter(g for found in extra.values() for g in found)
    lonely = {g for g, count in members.items() if g not in groups and count < 2}
    for key in list(extra):
        extra[key] = {g: why for g, why in extra[key].items() if g not in lonely}
        if not extra[key]:
            del extra[key]
    return extra, groups, lonely


def write(path: Path, extra: dict[str, dict[str, str]], note: list[str]):
    lines = ["{", ' "note": ' + json.dumps(note, ensure_ascii=False) + ",", ' "extra": {']
    items = sorted(extra.items())
    for i, (key, found) in enumerate(items):
        comma = "," if i < len(items) - 1 else ""
        lines.append(f"  {json.dumps(key, ensure_ascii=False)}: {json.dumps(sorted(found), ensure_ascii=False)}{comma}")
    lines += [" }", "}"]
    path.write_bytes(("\n".join(lines) + "\n").encode("utf-8"))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--analysis", type=Path, default=ROOT / "data/character_analysis.json")
    parser.add_argument("--implications", type=Path, default=ROOT / "data/danbooru_tag_snapshot/tag_implications.parquet")
    parser.add_argument("--aliases", type=Path, default=ROOT / "data/danbooru_tag_snapshot/tag_aliases.parquet")
    parser.add_argument("--extra", action="append", default=[], help="증분 버킷 폴더(tags_*.parquet) - 여러 번 줄 수 있다")
    parser.add_argument("--output", type=Path, default=ROOT / "data/character_group_membership.json")
    args = parser.parse_args()

    started = time.time()
    analysis = json.loads(args.analysis.read_text(encoding="utf-8"))
    names = {n for g, chars in analysis.items() if isinstance(chars, dict) for n, d in chars.items() if isinstance(d, dict)}
    files = sorted(glob.glob(str(ROOT / "data" / "tags" / "tags_*.parquet")))
    for folder in args.extra:
        files.extend(sorted(glob.glob(str(Path(folder) / "tags_*.parquet"))))
    if not files:
        raise SystemExit("코퍼스가 없습니다: data/tags/tags_*.parquet")
    parents = load_parents(args.implications)
    rows, copyrights = scan_corpus(files, names)
    extra, groups, lonely = build(analysis, parents, rows, copyrights, load_aliases(args.aliases))

    note = ["추가 그룹 소속(주 그룹 말고도 이 그룹 목록에 나온다). 키 = 주그룹::이름(정체성 그대로) · 값 = 덧붙일 그룹들.",
            f"(a) 하위 작품(함의) 코퍼스 점유 {MIN_SHARE:.0%} 이상 · {MIN_ROWS}행 이상 (b) 엔트리 copyright (c) 그 웃 작품 중 이미 그룹인 것.",
            "개발 도구 tools/build_character_group_membership.py 로 생성. 런타임은 이 JSON 만 읽는다."]
    write(args.output, extra, note)

    added = Counter(g for found in extra.values() for g in found)
    reasons = Counter(why for found in extra.values() for why in found.values())
    new_groups = {g: c for g, c in added.items() if g not in groups}
    print(f"버킷 {len(files)} · {time.time() - started:.1f}s · 함의 부모 {len(parents):,}")
    print(f"추가 소속을 얻은 캐릭터 {len(extra):,} · 소속 {sum(added.values()):,} (a {reasons['a']:,} · b {reasons['b']:,} · c {reasons['c']:,})")
    print(f"새로 생긴 그룹 {len(new_groups):,} (3명 이상 {sum(1 for c in new_groups.values() if c >= 3)}) · 1명뿐이라 버린 새 그룹 {len(lonely):,}")
    print("추가 인원 많은 그룹:")
    for g, c in added.most_common(30):
        base = len(analysis.get(g) or {})
        print(f"  +{c:4d}  {g}  ({base} -> {base + c}){'  [새 그룹]' if g not in groups else ''}")
    print("새 그룹(3명 이상):")
    for g, c in sorted(new_groups.items(), key=lambda kv: -kv[1]):
        if c >= 3:
            print(f"  {c:4d}  {g}")
    print("(c) 로만 붙은 그룹 상위(함의 사슬 점검용):")
    only_c = Counter(g for found in extra.values() for g, why in found.items() if why == "c")
    for g, c in only_c.most_common(25):
        sample = [k for k, f in extra.items() if f.get(g) == "c"][:3]
        print(f"  +{c:4d}  {g}  e.g. {sample}")
    by_group = defaultdict(list)
    for key, found in extra.items():
        for g in found:
            by_group[g].append(key)
    for g, wanted in SPOT_CHECK.items():
        listed = {key.split("::", 1)[1] for key in by_group.get(g, [])} | set(analysis.get(g) or {})
        print(f"[점검] {g}: 주 {len(analysis.get(g) or {})} + 추가 {len(by_group.get(g, []))}")
        for name in wanted:
            print(f"    {'O' if name in listed else 'X'} {name}  rows={rows.get(name, 0)}")


if __name__ == "__main__":
    main()
