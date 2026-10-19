"""캐릭터 사전에 **Danbooru 게시물 수**와 **original 캐릭터의 작가**를 적는다(사용자 결정 2026-10-19).

작품명 가중치 규칙(`core/character_viewer_service.py` `copyright_part`)이 게시물 수로 갈린다. 그런데
  · Danbooru 스냅숏(`data/danbooru_tag_snapshot`)은 개발용이라 배포되지 않고,
  · 배포되는 `danbooru_character.character_dict_count` 는 Danbooru 수와 다르다(katou umi 228 vs 409).
그래서 수를 사전 엔트리에 박는다:

    "danbooru_posts": 409          스냅숏 post_count(별칭이면 active 별칭의 대상으로 찾는다). 못 찾으면 안 적는다.
    "artist": "fu-ta"              `original` 그룹 · 이름에 괄호가 없을 때만 - 코퍼스 최다 작가가 그 캐릭터 그림의
                                   50% 이상이면. 프롬프트에서 `usami taiga (fu-ta)` 가 된다(`original` 은 작품명이 아니다).
    "copyright": "mega man (series)"  그 캐릭터의 작품 - 프롬프트에 붙이는 작품명은 **이것**이다(그룹이 아니다 · 사용자 결정
                                   2026-10-19). 코퍼스에서 그 캐릭터와 함께 붙은 copyright 태그 최다(original 은 빼고 센다 -
                                   original 이 과반이면 "original"). 그룹 태그가 최다의 90% 이상이면 그룹(사전과 같은 이름 · 동률의
                                   상위 묶음 - `7th dragon` vs `7th dragon (series)`). 코퍼스에 없으면 그룹.
    "parent_works": ["virtual youtuber"]  웃 갈래 작품(사용자 지시 2026-10-19 - `indie virtual youtuber` 는 `virtual youtuber`
                                   의 하위인데 필터에 상위가 없었다). Danbooru 에서 `virtual youtuber` 는 copyright 가 아니라 **일반
                                   태그**라 함의로 못 잇는다 - 그 캐릭터 그림의 과반에 붙어 있으면 넣는다(`PARENT_WORK_TAGS`).
    "work_in_name": true           이름 끝 괄호가 그 작품(이름 · 줄임)이다 - `roll (mega man)` · `honoka (doa)`. 이때 프롬프트는
                                   `-0.7::copyright ::`(BA -1) · 괄호를 걷으면 `0.5::copyright ::`. 의상 · 형태 · 작가 꼬리
                                   (`(2nd costume)` · `(append)` · `(ichiri)`)는 아니다. 판정 = 아래 `work_tails`.

규약:
  · 그 두 필드만 쓴다(이미 있으면 새 값으로 갈아 끼운다 - 스냅숏을 바꾼 뒤 다시 돌리면 된다). 다른 필드는 그대로.
  · CRLF · 끝 줄바꿈 없음을 보존한다. 쓰기 전에 `.json.posts.bak` 을 남긴다.
  · 사전에 캐릭터를 병합한 뒤(`merge_character_profile_increment.py`) 다시 돌린다.

    python tools/annotate_character_posts.py                       # dry-run
    python tools/annotate_character_posts.py --apply
    python tools/annotate_character_posts.py --corpus-extra C:/VNR/DEV/tag_increment_full/buckets --apply
"""
from __future__ import annotations

import argparse
import collections
import glob
import json
import re
import shutil
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ANALYSIS_PATH = REPO_ROOT / "data" / "character_analysis.json"
SNAPSHOT_DIR = REPO_ROOT / "data" / "danbooru_tag_snapshot"
CORPUS_DIR = REPO_ROOT / "data" / "tags"
NEWLINE = "\r\n"
ORIGINAL_GROUP = "original"
ARTIST_SHARE = 0.5
# 작가 칸에 오지만 작가가 아닌 메타 태그.
NOT_ARTISTS = {"banned artist", "artist request", "anonymous", "unknown artist", "third-party edit",
               "third-party source", "ai-generated", "ai-assisted", "artist name", "commentary request"}


def danbooru_key(name: str) -> str:
    return name.strip().lower().replace(" ", "_")


_TAIL = re.compile(r"\(([^()]+)\)\s*$")
# 작품이 아닌 꼬리 - 의상 · 형태 · 시기(`(2nd costume)` · `(swimsuit)` · `(female)`). 같은 꼬리를 여럿이 써도 작품이 아니다(Codex 리뷰 17차).
_NOT_WORK = re.compile(r"\b(?:\d+(?:st|nd|rd|th)\s+)?(?:costume|outfit|uniform|swimsuit|bikini|dress|casual|pajamas|"
                       r"kimono|yukata|maid|nurse|bunny|form|ver|version|ascension|alter|young|adult|child|"
                       r"male|female|human|cosplay|racehorse|horse)\b")


def _norm(text: str) -> str:
    text = re.sub(r"\(series\)|\bseries\b|\(franchise\)|\(game\)", " ", text.lower())
    return re.sub(r"[^a-z0-9]+", "", text)


# 웃 갈래 작품 - 일반 태그로 붙는 묶음 작품. 그 캐릭터 그림에서 이 비율 이상이면 그 작품에도 든다.
PARENT_WORK_TAGS = {"virtual youtuber": 0.5}


def character_copyrights(names: set[str], extra_dirs: list[Path]) -> dict[str, collections.Counter]:
    """캐릭터 -> 함께 붙은 copyright 태그 수(코퍼스 전수). 키 "__rows__" = 그 캐릭터가 나온 행 수,
    "__general__:<태그>" = `PARENT_WORK_TAGS` 의 일반 태그가 붙은 행 수."""
    import pyarrow.parquet as pq

    paths = sorted(glob.glob(str(CORPUS_DIR / "tags_*.parquet")))
    for folder in extra_dirs:
        paths += sorted(glob.glob(str(folder / "tags_*.parquet")))
    counts: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for path in paths:
        table = pq.read_table(path, columns=["character", "copyright", "general"])
        for chars, cps, gen in zip(table.column("character").to_pylist(), table.column("copyright").to_pylist(),
                                   table.column("general").to_pylist()):
            if not chars:
                continue
            hits = [c.strip() for c in chars.split(",") if c.strip() in names]
            if not hits:
                continue
            tags = [c.strip() for c in (cps or "").split(",") if c.strip()]
            general = f", {gen or ''},"
            parents = [tag for tag in PARENT_WORK_TAGS if f", {tag}," in general]
            for name in hits:
                counts[name]["__rows__"] += 1
                for tag in tags:
                    counts[name][tag] += 1
                for tag in parents:
                    counts[name]["__general__:" + tag] += 1
    print(f"[작품] 버킷 {len(paths)} · 코퍼스에 나온 캐릭터 {len(counts):,}")
    return counts


def choose_copyright(group: str, counts: collections.Counter | None) -> str:
    """그 캐릭터의 작품(머리말 `copyright` 규칙)."""
    if group == ORIGINAL_GROUP:
        return ORIGINAL_GROUP
    if not counts or not counts.get("__rows__"):
        return group
    rows = counts["__rows__"]
    if counts.get(ORIGINAL_GROUP, 0) * 2 > rows:
        return ORIGINAL_GROUP
    # "__" 로 시작하는 키는 센 수가 아니라 표식이다(행 수 · 웃 갈래 일반 태그) - 작품 후보에서 뺀다.
    ranked = [(tag, n) for tag, n in counts.most_common() if not tag.startswith("__") and tag != ORIGINAL_GROUP]
    if not ranked:
        return group
    top_tag, top_n = ranked[0]
    if counts.get(group, 0) >= 0.9 * top_n:
        return group
    return top_tag


def work_tails(analysis: dict, copyright_of: dict[tuple[str, str], str],
               counts: dict[str, collections.Counter]) -> set[tuple[str, str]]:
    """(그룹, 이름) 가운데 이름 끝 괄호가 **그 캐릭터의 작품**(이름 · 줄임)인 것.

    작품이라고 보는 경우(괄호 = q):
      · q 가 그 캐릭터의 작품(`copyright`) · 그룹 · 코퍼스 상위 작품 셋 중 하나와 이어진다(정규화해 한쪽이 다른 쪽을 품는다 -
        `(mega man)` ~ mega man (series) · `(arifureta)` ~ arifureta shokugyou de … · `(armored core vi)` ~ armored core vi: …)
      · q 가 Danbooru 작품 태그다(스냅숏 category 3)
      · 같은 그룹에서 변형이 아닌(다른 캐릭터를 함의하지 않는) 캐릭터 셋 이상이 같은 꼬리를 쓴다(`(amaburi)` · `(doa)` · `(dc)`)
    빼는 것(작품 태그가 아닐 때): 의상 · 형태 · 시기 꼬리(`_NOT_WORK`) · 작가 태그. 일반 태그(`(character)` · `(vtuber)`)는
    '여럿이 같은 꼬리' 규칙에서만 뺀다.
    """
    import pandas as pd

    tags = pd.read_parquet(SNAPSHOT_DIR / "tags.parquet", columns=["name", "category"])
    copyrights = set(tags[tags["category"] == 3]["name"])
    artists = set(tags[tags["category"] == 1]["name"])
    general = set(tags[tags["category"] == 0]["name"])      # `(character)` · `(vtuber)` 는 일반 태그 - 작품이 아니다
    characters = set(tags[tags["category"] == 4]["name"])
    imp = pd.read_parquet(SNAPSHOT_DIR / "tag_implications.parquet",
                          columns=["antecedent_name", "consequent_name", "status"])
    imp = imp[imp["status"] == "active"]
    variants = {a for a, c in zip(imp["antecedent_name"], imp["consequent_name"]) if a in characters and c in characters}
    rows = []
    shared: collections.Counter = collections.Counter()
    for group, members in analysis.items():
        if group.startswith("_") or group == ORIGINAL_GROUP or not isinstance(members, dict):
            continue
        for name in members:
            match = _TAIL.search(name)
            if not match:
                continue
            tail = match.group(1).strip()
            rows.append((group, name, tail))
            if danbooru_key(name) not in variants:
                shared[(group, tail.lower())] += 1

    def related(q: str, work: str) -> bool:
        """괄호가 그 작품의 이름 · 줄임인가 - 정규화해 한쪽이 다른 쪽의 **앞이나 끝**이다(`mega man` ~ mega man (series) ·
        `arifureta` ~ arifureta shokugyou … · `sailor moon` ~ bishoujo senshi sailor moon · `armored core vi` ~ armored core).
        가운데 낱말만 겹치는 것은 아니다(`spirit` ~ date a live: spirit pledge - 형태 꼬리 · Codex 리뷰 20차)."""
        a, b = _norm(q), _norm(work)
        if len(a) < 3 or len(b) < 3:
            return False
        short, long_ = (a, b) if len(a) <= len(b) else (b, a)
        if len(short) < 4 and short != long_:
            return False
        return long_.startswith(short) or long_.endswith(short)

    found: set[tuple[str, str]] = set()
    for group, name, tail in rows:
        q = tail.lower()
        key = q.replace(" ", "_")
        work = copyright_of.get((group, name), group)
        if work == ORIGINAL_GROUP:
            continue
        # Danbooru 작품 태그면 먼저 작품이다 - 의상 낱말이 들어 있어도(`bunny garden` · `akiba maid sensou` · Codex 리뷰 18차).
        if key in copyrights:
            found.add((group, name))
            continue
        if _NOT_WORK.search(q) or key in artists:
            continue
        own = counts.get(name) or collections.Counter()
        rows_n = own.get("__rows__", 0)
        # 상위 작품은 그 캐릭터 그림의 20% 이상인 것만 - 드문 동반 작품(`date a live: spirit pledge` 3/40)에 이어 붙지 않게
        # (`yatogami tohka (spirit)` 의 `spirit` 은 형태다 · Codex 리뷰 19차).
        top = [tag for tag, n in own.most_common(6)
               if not tag.startswith("__") and tag != ORIGINAL_GROUP and rows_n and n >= 0.2 * rows_n][:3]
        # 일반 태그 · **다른 캐릭터 이름**(`sukonbu (shirakami fubuki)`)은 '여럿이 같은 꼬리' 규칙에서 뺀다. `mega_man` ·
        # `arifureta` 도 Danbooru 에선 일반 태그(동음 구분용)라 작품과 이어지는 규칙에서는 빼면 안 된다.
        if ((shared[(group, q)] >= 3 and key not in general and key not in characters)
                or any(related(q, w) for w in [work, group, *top])
                # 그룹 이름의 괄호를 뗀 몸통과 같다(`(ado)` ~ ado (utaite)) - 짧은 이름도 같으면 그 작품이다.
                or _norm(q) == _norm(_TAIL.sub("", group))):
            found.add((group, name))
    return found


def load_posts() -> dict[str, int]:
    import pandas as pd

    tags = pd.read_parquet(SNAPSHOT_DIR / "tags.parquet", columns=["name", "post_count"])
    posts = dict(zip(tags["name"], tags["post_count"].astype(int)))
    aliases = pd.read_parquet(SNAPSHOT_DIR / "tag_aliases.parquet",
                              columns=["antecedent_name", "consequent_name", "status"])
    aliases = aliases[aliases["status"] == "active"]
    for old, new in zip(aliases["antecedent_name"], aliases["consequent_name"]):
        if old not in posts and new in posts:
            posts[old] = posts[new]
    return posts


def original_artists(names: set[str], extra_dirs: list[Path]) -> dict[str, str]:
    """original 캐릭터 -> 최다 작가(점유 ARTIST_SHARE 이상일 때만)."""
    import pyarrow.parquet as pq

    paths = sorted(glob.glob(str(CORPUS_DIR / "tags_*.parquet")))
    for folder in extra_dirs:
        paths += sorted(glob.glob(str(folder / "tags_*.parquet")))
    counts: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    total: collections.Counter = collections.Counter()
    for path in paths:
        table = pq.read_table(path, columns=["character", "artist"])
        for chars, artists in zip(table.column("character").to_pylist(), table.column("artist").to_pylist()):
            if not chars:
                continue
            for name in (c.strip() for c in chars.split(",")):
                if name not in names:
                    continue
                total[name] += 1
                for artist in (a.strip() for a in (artists or "").split(",") if a.strip()):
                    if artist not in NOT_ARTISTS:
                        counts[name][artist] += 1
    picked: dict[str, str] = {}
    for name in names:
        if not counts[name] or not total[name]:
            continue
        artist, hit = counts[name].most_common(1)[0]
        if hit / total[name] >= ARTIST_SHARE:
            picked[name] = artist
    print(f"[작가] 버킷 {len(paths)} · original(괄호 없음) {len(names):,} -> 작가 붙음 {len(picked):,}")
    return picked


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--corpus-extra", type=Path, action="append", default=[],
                    help="작가 집계에 더할 증분 버킷 폴더(여러 번 줄 수 있다)")
    ap.add_argument("--apply", action="store_true", help="실제로 파일을 쓴다")
    args = ap.parse_args()

    analysis = json.loads(ANALYSIS_PATH.read_bytes().decode("utf-8"))
    posts = load_posts()
    originals = {name for name in (analysis.get(ORIGINAL_GROUP) or {}) if "(" not in name}
    artists = original_artists(originals, args.corpus_extra)
    all_names = {name for group, members in analysis.items() if not group.startswith("_") and isinstance(members, dict)
                 for name in members}
    counts = character_copyrights(all_names, args.corpus_extra)
    copyright_of = {(group, name): choose_copyright(group, counts.get(name))
                    for group, members in analysis.items() if not group.startswith("_") and isinstance(members, dict)
                    for name in members}
    tails = work_tails(analysis, copyright_of, counts)
    differs = sum(1 for (group, _name), work in copyright_of.items() if work != group)
    print(f"[작품] 그룹과 다른 작품 {differs:,} · 이름에 작품이 든 캐릭터 {len(tails):,}")

    bands: collections.Counter = collections.Counter()
    changed = 0
    for group, members in analysis.items():
        if group.startswith("_") or not isinstance(members, dict):
            continue
        for name, data in members.items():
            if not isinstance(data, dict):
                continue
            before = (data.get("danbooru_posts"), data.get("artist"), data.get("copyright"), data.get("work_in_name"),
                      data.get("series"), data.get("parent_works"))
            count = posts.get(danbooru_key(name))
            if count is None:
                data.pop("danbooru_posts", None)
                bands["스냅숏에 없음"] += 1
            else:
                data["danbooru_posts"] = int(count)
                bands["<40" if count < 40 else "40-79" if count < 80 else "80-99" if count < 100
                      else "100-149" if count < 150 else "150+"] += 1
            if group == ORIGINAL_GROUP and name in artists:
                data["artist"] = artists[name]
            else:
                data.pop("artist", None)
            data.pop("series", None)                    # 옛 필드(괄호 글자) - `copyright` · `work_in_name` 으로 바뀌었다
            own = counts.get(name) or collections.Counter()
            parents = [tag for tag, share in PARENT_WORK_TAGS.items()
                       if own.get("__rows__") and own.get("__general__:" + tag, 0) >= share * own["__rows__"]
                       and tag not in (group, copyright_of[(group, name)])]
            if parents:
                data["parent_works"] = parents
            else:
                data.pop("parent_works", None)
            data["copyright"] = copyright_of[(group, name)]
            if (group, name) in tails:
                data["work_in_name"] = True
            else:
                data.pop("work_in_name", None)
            if before != (data.get("danbooru_posts"), data.get("artist"), data.get("copyright"), data.get("work_in_name"),
                          data.get("series"), data.get("parent_works")):
                changed += 1
    print("[게시물 수] " + " · ".join(f"{k} {v:,}" for k, v in sorted(bands.items())))
    print(f"[변경] 엔트리 {changed:,}")
    for name in ("usami taiga", "kuchisake-onna"):
        entry = (analysis.get(ORIGINAL_GROUP) or {}).get(name)
        if entry:
            print(f"    {name}: posts={entry.get('danbooru_posts')} artist={entry.get('artist')}")
    if not args.apply:
        print("\n  [dry-run] 쓰지 않았다 - --apply 로 쓴다")
        return 0
    shutil.copy2(ANALYSIS_PATH, ANALYSIS_PATH.with_suffix(".json.posts.bak"))
    text = json.dumps(analysis, ensure_ascii=False, indent=2)
    ANALYSIS_PATH.write_bytes(text.replace("\r\n", "\n").replace("\n", NEWLINE).encode("utf-8"))
    print(f"\n  {ANALYSIS_PATH} 갱신 (.json.posts.bak 보관)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
