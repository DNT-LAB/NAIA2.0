# -*- coding: utf-8 -*-
"""성인 도감 -> 일반 축 이동 실행.

## 무엇을 옮기나

`wildcards/nsfw/_reclassify_candidates.json` 이 후보다. 판정은 두 단계였다:

  1. rating 실측으로 후보를 뽑는다 (`explicit < 70%`)
  2. 어휘 정책으로 남길 것을 거른다 (`tools/nsfw_explicit_vocab` 또는 q+e >= 90%)

여기서 **gloss 축 두 개는 제외한다.** `nsfw_etc_dark`(guro·torture·self-harm)와
`nsfw_etc_sexual`(incest·onee-loli·forced)은 사용자가 이미 "썸네일 없음 + 스킵"으로
분리해 둔 부류다. 통계상 explicit 이 낮다고 일반 축으로 풀 대상이 아니다.
실제로 그림도 없다(23개 중 1개만 보유) — 옮겨도 의미가 없다.

## 어디로 옮기나

**빼기만 하면 어느 축에도 없어 사라진다.** 일반 빌더들은 자기 서브그룹에서만
태그를 뽑으므로 NSFW 그룹 태그를 주워 가지 않는다. 그래서 받을 축을 만든다.

    cloth_revealing  노출·엿보임 의상   <- exposure · peek · censor
    body_suggestive  신체 연출          <- breast · butt · bodyjob · anatomy · adorn · genital
    pose_suggestive  밀착·상황          <- act · position · hand · oral · state · fetish · cum · pairing
    obj_restraint    구속·기구          <- toy

네 축 모두 **성인 축이 아니므로 블러가 걸리지 않는다**(사용자 지시: 이동된 것은
블러 제거). 블러는 `SENSITIVE_AXES` 로 축 단위라 축이 바뀌면 자동으로 풀린다.

## 그림은 다시 만들지 않는다

198개 중 197개가 이미 썸네일을 갖고 있다(사용자가 직접 돌린 분량). 팩 빌더는
PNG 의 가중치 블록 태그로 축을 찾으므로 **폴더와 무관하게 새 축 키로 다시 붙는다.**
`pectoral docking` 하나만 그림이 없다.

## 되돌리기

이 스크립트는 `_moved_to_sfw.txt` 를 낸다. 성인 빌더 둘이 그 목록을 읽어 제외한다.
되돌리려면 그 파일을 비우고 빌더를 다시 돌리면 된다.

사용: python tools/nsfw_reclassify.py
"""
import json
from pathlib import Path

NS = Path("wildcards/nsfw")
TH = Path("wildcards/thumb")
CAND = NS / "_reclassify_candidates.json"
MOVED = NS / "_moved_to_sfw.txt"

# 이 두 축은 옮기지 않는다(위 문서주석 참조).
GLOSS_AXES = {"nsfw_etc_dark", "nsfw_etc_sexual"}

TARGET = {
    "cloth_revealing": ("노출·엿보임 의상", ["nsfw_exposure", "nsfw_peek", "nsfw_censor"]),
    "body_suggestive": ("신체 연출", ["nsfw_breast", "nsfw_butt", "nsfw_bodyjob",
                                     "nsfw_anatomy", "nsfw_adorn", "nsfw_genital"]),
    "pose_suggestive": ("밀착·상황", ["nsfw_act", "nsfw_position", "nsfw_hand",
                                     "nsfw_oral", "nsfw_state", "nsfw_fetish",
                                     "nsfw_cum", "nsfw_pairing"]),
    "obj_restraint": ("구속·기구", ["nsfw_toy"]),
}
FRAMING = {"cloth_revealing": "cloth_outfit", "body_suggestive": "cowboy",
           "pose_suggestive": "cowboy", "obj_restraint": "cowboy"}


def main() -> int:
    doc = json.loads(CAND.read_text(encoding="utf-8"))
    cand = [c for c in doc["candidates"] if c["from"] not in GLOSS_AXES]
    src_to_target = {src: key for key, (_lb, srcs) in TARGET.items() for src in srcs}

    axes: dict[str, list[str]] = {k: [] for k in TARGET}
    unrouted = []
    for c in cand:
        key = src_to_target.get(c["from"])
        if key is None:
            unrouted.append(c)
            continue
        axes[key].append(c["tag"])
    if unrouted:
        # 조용히 버리면 태그가 사라진다. 목적지를 정하기 전에는 쓰지 않는다.
        print(f"!! 목적지 없는 원본 축 {sorted({c['from'] for c in unrouted})}")
        return 1

    for key, tags in axes.items():
        tags.sort()
        (TH / f"{key}.txt").write_text("\n".join(tags) + "\n", encoding="utf-8")
        print(f"  {key:18s} {TARGET[key][0]:14s} {len(tags):4d}개")

    moved = sorted(t for v in axes.values() for t in v)
    MOVED.write_text(
        "# 성인 도감에서 일반 축으로 옮긴 태그. 성인 빌더 둘이 이 목록을 제외한다.\n"
        "# tools/nsfw_reclassify.py 가 만든다. 되돌리려면 이 파일을 비우고 빌더를 다시 돌려라.\n"
        + "\n".join(moved) + "\n", encoding="utf-8")

    (TH / "_sfw_moved_axes.json").write_text(json.dumps({
        "note": ["성인 도감에서 옮겨 온 일반 축. tools/nsfw_reclassify.py 가 만든다.",
                 "성인 축이 아니므로 블러가 걸리지 않는다(사용자 지시)."],
        "label": {k: v[0] for k, v in TARGET.items()},
        "framing": FRAMING,
    }, ensure_ascii=False), encoding="utf-8")

    print(f"\n이동 {len(moved)}개 / 4축  -> {MOVED}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
