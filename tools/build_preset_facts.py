# -*- coding: utf-8 -*-
"""이벤트 프리셋 아카이브에서 '측정된 사실'을 뽑아 작은 캐시로 만든다.

원본은 `user-data/data/event_preset/naia_prompt_preset` (403MB ZIP)이다. 런타임이
매번 40개 파티션 parquet 을 읽을 수는 없으므로 필요한 두 가지만 추출해 둔다.

  1. 인원 구성별 post_count -> solo 비율
     파티션이 `{등급}_{인원구성}` 으로 나뉘어 있다(g/s/q/e × 13구성).
     solo(1girl_solo, 1boy_solo) 합계와 multi(2인 이상) 합계의 비를 낸다.
     이것이 "이 행동이 혼자서 되는가"에 대한 **측정값**이다 — 추론이 아니다.

  2. dependency_rules (Danbooru 공식 tag implications 6,679 + 공기 유도 142)
     `hugging tail -> tail` 같은 전제조건. confidence 1.0 이 대부분이다.

실행:
    python tools/build_preset_facts.py
    -> data/interactive_preset_facts.json
"""
import io
import json
import zipfile
from collections import defaultdict
from pathlib import Path

import pandas as pd

ARCHIVE_CANDIDATES = [
    Path("user-data/data/event_preset/naia_prompt_preset"),
    Path("data/event_preset/naia_prompt_preset"),
    Path("ui/event_preset/naia_prompt_preset"),
]
OUT = Path("data/interactive_preset_facts.json")

# 혼자인 구성 / 둘 이상인 구성. `1girl`(solo 표기 없음)은 다른 인물이 있을 수도
# 없을 수도 있어 어느 쪽에도 넣지 않는다 — 신호를 흐린다.
SOLO_PARTS = {"1girl_solo", "1boy_solo"}
MULTI_PARTS = {"1girl_1boy", "1girl_multiple_boys", "2girls", "multiple_girls",
               "1boy_multiple_girls", "2boys", "multiple_boys",
               "multiple_girls_multiple_boys"}
MIN_POSTS = 50      # 표본이 적으면 비율이 요동친다


def find_archive() -> Path:
    for p in ARCHIVE_CANDIDATES:
        if p.exists():
            return p
    raise SystemExit(f"프리셋 아카이브를 찾지 못했습니다: {ARCHIVE_CANDIDATES}")


def main() -> int:
    src = find_archive()
    z = zipfile.ZipFile(src)
    solo: dict[str, int] = defaultdict(int)
    multi: dict[str, int] = defaultdict(int)
    parts = 0
    for name in z.namelist():
        if not name.endswith("/event_catalog.parquet"):
            continue
        part = name.split("/")[1]
        person = part[part.index("_") + 1:]
        tgt = solo if person in SOLO_PARTS else multi if person in MULTI_PARTS else None
        if tgt is None:
            continue
        df = pd.read_parquet(io.BytesIO(z.read(name)))
        for tag, cnt in zip(df["event_tag"], df["post_count"]):
            tgt[tag] += int(cnt)
        parts += 1

    person: dict[str, dict] = {}
    for tag in set(solo) | set(multi):
        s, m = solo.get(tag, 0), multi.get(tag, 0)
        if s + m < MIN_POSTS:
            continue
        person[tag] = {"solo": s, "multi": m, "share": round(s / (s + m), 4)}

    dep = pd.read_parquet(io.BytesIO(z.read("base/dependency_rules.parquet")))
    rules: dict[str, list] = defaultdict(list)
    for r in dep.itertuples(index=False):
        rules[str(r.child_tag)].append({
            "parent": str(r.parent_tag),
            "conf": round(float(r.confidence), 3),
            "support": int(r.support),
            "type": str(r.rule_type),
        })
    for k in rules:
        rules[k].sort(key=lambda d: (-d["conf"], -d["support"]))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "source": str(src).replace("\\", "/"),
        "partitions": parts,
        "min_posts": MIN_POSTS,
        "person": person,
        "implications": rules,
    }, ensure_ascii=False), encoding="utf-8")
    size = OUT.stat().st_size / 1048576
    print(f"파티션 {parts}개 집계")
    print(f"  인원 실측 {len(person)}개 태그")
    print(f"  전제 규칙 {len(rules)}개 태그 / {len(dep)}행")
    print(f"저장: {OUT} ({size:.1f}MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
