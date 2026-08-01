# -*- coding: utf-8 -*-
"""아직 그림이 없는 태그의 와일드카드 — 생성을 기다리지 않고 지금 쓸 수 있게.

## 왜 필요한가

축에 목록은 있는데 썸네일이 없는 태그가 많다. 구도 4축(89) · 기타·텍스트 4축(154) 은
아직 한 장도 안 만들었고, 성인 도감에서 과잉 분류로 풀려난 384개도 그림이 없다.
그림이 없으면 그리드에 안 뜨고, 그리드에 안 뜨면 **사용자가 그 태그를 쓸 방법이 없다.**

와일드카드는 그림이 필요 없다. 목록만 있으면 `__pending/view_shot__` 로 바로 쓴다.
생성은 나중에 해도 되고, 안 해도 된다.

## 어디서 오나

    wildcards/thumb/<축>.txt        축 목록(SSOT)
    data/interactive_thumbnails.json 이미 만든 그림
    ->  둘의 차집합이 '미생성'

**목록을 여기 다시 적지 않는다.** 이 리포에서 같은 목록을 두 군데 적어 갈라진 사고가
여러 번 났다.

## 성인/스킵은 뺀다

    wildcards/nsfw/*.txt        성인 — 여기 대상이 아니다(별도 와일드카드가 이미 있다)
    wildcards/thumb/_skip.txt   자해·자살·다크 — 생성도 사용도 하지 않는다(사용자 정책)

사용: python tools/build_pending_wildcards.py
"""
import json
from pathlib import Path

THUMB = Path("wildcards/thumb")
PACK = Path("data/interactive_thumbnails.json")
OUT = Path("wildcards/pending")
SKIP = THUMB / "_skip.txt"


def main() -> int:
    if not PACK.exists():
        raise SystemExit(f"{PACK} 가 없다.")
    pack = json.loads(PACK.read_text(encoding="utf-8"))
    have: dict[str, set[str]] = {}
    for key in pack:
        axis, _, tag = key.partition("/")
        if tag:
            have.setdefault(axis, set()).add(tag)

    # **성인은 뺀다.** 축 목록만 보면 성인 태그가 그대로 통과한다 — 실측으로
    # `view_layout` 의 `cross-section`(explicit 96.3%)이 새 나갔다(2026-08-01).
    # 축 빌더가 걸렀을 것이라고 믿으면 안 된다. 여기서 다시 잰다.
    #
    # **다만 rating 은 "Danbooru 게시물에서 어떻게 쓰였나"지 "우리가 뭘 그리나"가
    # 아니다.** 체형 축의 `shota`(explicit 77.9%)·`loli` 가 그 예다 — 게시물 통계는
    # 높지만 우리 벤치는 `rating:general` 베이스로 찍고, 실제 썸네일은 멜빵바지에
    # 풍선 든 아이와 오버사이즈 스웨터 입은 아이다(Vision 확인 2026-08-01). 이것들은
    # **체형 조절용 범용 태그**이고 사용자와 협의된 배치다(tools/thumb_age_guard.py
    # 문서주석 참조 — 거기에 이미 적혀 있었다).
    #
    # 그래서 게이트는 **`rating:general` 로 찍지 않는 축에만** 건다. 체형·외모처럼
    # 베이스가 general 로 고정된 축은 게시물 통계와 무관하다.
    RATING_EXEMPT_AXES = {"body_type", "body_feature", "persona", "face", "expression"}
    rating = {}
    rp = Path("data/tag_rating.json")
    if rp.exists():
        rating = json.loads(rp.read_text(encoding="utf-8"))["tags"]
    else:
        raise SystemExit("data/tag_rating.json 이 없다. tools/build_tag_rating.py 를 먼저 돌려라 "
                         "— 성인 판정 없이 생성 목록을 내보내지 않는다.")
    ADULT_E = 70.0

    skip = set()
    if SKIP.exists():
        skip = {l.strip() for l in SKIP.read_text(encoding="utf-8").splitlines()
                if l.strip() and not l.startswith("#")}

    # **선언된 축만 본다.** `wildcards/thumb/*.txt` 에는 축이 아닌 중간 산출물이 섞여
    # 있다(`pose_solo`·`pose_multi`·`pose_drop` — 실측 2,118개가 축인 척 잡혔다).
    # 축의 SSOT 는 `_manifest.json` 의 axes 와 `_*_axes.json` 의 label 키다.
    declared: set[str] = set()
    man = THUMB / "_manifest.json"
    if man.exists():
        declared |= {str(a.get("key")) for a in json.loads(man.read_text(encoding="utf-8")).get("axes", [])}
    for extra in THUMB.glob("_*_axes.json"):
        declared |= set(json.loads(extra.read_text(encoding="utf-8")).get("label", {}))
    declared.discard("")
    if not declared:
        raise SystemExit("축 선언을 못 읽었다. _manifest.json / _*_axes.json 확인.")

    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("*.txt"):
        old.unlink()

    rows, total, dropped_adult, shipped_adult = [], 0, [], []
    for src in sorted(THUMB.glob("*.txt")):
        if src.stem.startswith("_") or src.stem not in declared:
            continue
        tags = [l.strip() for l in src.read_text(encoding="utf-8").splitlines() if l.strip()]
        made = have.get(src.stem, set())
        adult = set() if src.stem in RATING_EXEMPT_AXES else {
            t for t in tags
            if (r := rating.get(t)) and r["n"] >= 20 and r["e"] >= ADULT_E}
        # 이 목록에서 뺀 것과, 이미 그림이 있는 것을 나눠 센다.
        # 후자는 **이미 팩에 들어가 배포되고 있다는 뜻**이라 성격이 다르다.
        dropped_adult.extend(sorted(t for t in adult if t not in made))
        shipped_adult.extend(sorted(t for t in adult if t in made))
        pending = [t for t in tags if t not in made and t not in skip and t not in adult]
        if not pending:
            continue
        (OUT / f"{src.stem}.txt").write_text("\n".join(pending) + "\n", encoding="utf-8")
        rows.append((src.stem, len(tags), len(made), len(pending)))
        total += len(pending)

    rows.sort(key=lambda r: -r[3])
    print(f"{'축':22s} {'전체':>5s} {'그림':>5s} {'미생성':>6s}")
    for axis, n, m, p in rows:
        print(f"{axis:22s} {n:5d} {m:5d} {p:6d}")
    print(f"\n미생성 {total:,}개 / 축 {len(rows)}개  -> {OUT}/")
    if dropped_adult:
        print(f"성인이라 이 목록에서 뺌 {len(dropped_adult)}개 (explicit>={ADULT_E:.0f}%): "
              + ", ".join(f'{t}({rating[t]["e"]}%)' for t in dropped_adult))
    if shipped_adult:
        print(f"  !! 일반 축에 있으면서 **이미 그림이 만들어진** 성인 태그 {len(shipped_adult)}개 "
              f"— 팩에 들어가 배포 중이다. 예: "
              + ", ".join(f'{t}({rating[t]["e"]}%)' for t in shipped_adult[:10]))
    if skip:
        print(f"스킵 목록 {len(skip)}개 제외({SKIP})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
