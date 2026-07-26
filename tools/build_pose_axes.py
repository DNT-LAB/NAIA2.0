# -*- coding: utf-8 -*-
"""자세 축 분해 — pose_solo 1,600 / pose_multi 440 을 그리드 크기 축으로 나눈다.

    python tools/build_pose_axes.py

## 왜 나누는가

한 그리드에 1,600개를 넣을 수 없다. 특징·의상 축은 150개를 상한으로 잡았고
(3x3 그리드에서 약 17스크롤) 자세도 같은 기준을 쓴다.

## 무엇을 기준으로 나누는가

이벤트 프리셋의 subgroup/subcategory 를 그대로 쓴다. 사람이 큐레이션한 분류라
내가 정규식으로 다시 나누는 것보다 정확하고, 이미 인원 판정에서 검증했다.
프리셋에 없는 태그(146개)는 이름·설명으로 보완한다.

## 프레이밍 — 자세는 특징·의상과 다르다

사용자 규칙은 "썸네일 크기로는 full body 소화가 불가능"이지만, **자세는 몸 전체가
곧 정보**라 손짓 말고는 전신이 필요하다. 그래서 축마다 다르게 잡는다.

    손짓·시선·입      portrait   손과 얼굴만 있으면 된다
    팔 위치·상체      upper      상반신
    들고 있는 것      cowboy     물건이 손에 있고 몸통이 보이면 된다
    자세·전신 동작    full       앉기/눕기/뛰기는 전신이 아니면 판별 불가

전신 축은 썸네일에서 작게 보이는 대가를 감수한다 — `sitting` 을 cowboy 로 찍으면
앉았는지 서 있는지 알 수 없어서 이미지가 아예 무의미해진다.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

OUT = Path("wildcards/thumb")
PRESET = Path("core/event_preset/event_preset_category_translations_ko.json")

# (축 key, 한글 라벨, 프레이밍, 프리셋 subcategory 목록)
AXIS_SPEC: list[tuple[str, str, str, tuple[str, ...]]] = [
    ("pose_posture", "자세", "full",
     ("sitting", "standing", "lying", "kneeling", "crouching", "leaning",
      "posture_other", "location", "pose_surface", "pose_in_container",
      "pose_resting", "pose_acrobatic")),
    ("pose_arm", "팔·다리 위치", "upper",
     ("limb_arms", "limb_body", "limb_hands", "limb_legs",
      "pose_arm_rest", "pose_feet_legs", "pose_between", "pose_on_body")),
    ("pose_hand", "손짓", "portrait",
     ("gesture_hand_sign", "gesture_pointing", "gesture_arm_raise",
      "gesture_expressive", "gesture_other")),
    ("pose_face_touch", "얼굴·몸에 손", "portrait",
     ("gesture_self_face", "gesture_self_body", "gesture_covering",
      "gesture_hair", "gesture_mouth")),
    ("pose_holding", "들고 있는 것", "cowboy",
     ("holding_tool_prop", "holding_food_drink", "holding_weapon",
      "holding_instrument", "holding_device_media", "holding_document_sign",
      "holding_misc", "holding_body_self", "holding_creature", "gesture_weapon")),
    ("pose_clothing", "옷 다루기", "cowboy",
     ("clothing_adjust", "clothing_aside", "clothing_displaced", "clothing_lift",
      "clothing_open", "clothing_other", "clothing_pull", "clothing_put_on",
      "clothing_remove", "gesture_clothing", "activity_apparel_action",
      "activity_apparel_adjustment", "activity_adjustment")),
    ("pose_action", "행동", "full",
     ("activity_locomotion", "activity_sports_athletics", "activity_performance",
      "activity_domestic_daily", "activity_creative_intellectual",
      "activity_bathing_hygiene", "activity_kinesis_magic",
      "activity_hair_body_manipulation", "activity_environmental_effect",
      "activity_communication", "activity_other", "general",
      "verb_locomotion", "verb_sleep", "verb_grooming", "verb_sports",
      "verb_work", "verb_creative", "verb_sound", "verb_other")),
    ("pose_mouth", "입·먹기", "portrait",
     ("activity_oral_action", "verb_eating_drinking")),
    ("pose_gaze", "시선", "portrait",
     ("gaze_direction", "gaze_other", "gaze_through")),
    ("pose_combat", "전투", "full",
     ("activity_combat", "combat_martial_art", "combat_ranged", "combat_strike",
      "combat_state", "combat_weapon_combat", "combat_grapple")),
    ("pose_display", "몸 보여주기", "cowboy",
     ("pose_body_display", "pose_restraint", "body_state_physical",
      "personality_physical_state", "personality_dance", "personality_archetype",
      "personality_other", "personality_social_situation", "pose_other",
      "pose_carrying")),
]
# 프리셋에 없는 태그를 이름·설명으로 배정. 위 축 중 하나로 보낸다.
FALLBACK: tuple[tuple[str, re.Pattern], ...] = (
    ("pose_posture", re.compile(r"(sitting|sit\b|standing|stand\b|lying|lie |kneel"
                                r"|crouch|squat|lean|on (floor|bed|ground|couch|chair)"
                                r"|against )")),
    ("pose_hand", re.compile(r"\b(v sign|peace|salute|thumbs|finger|hand sign|pointing"
                             r"|waving|clenched|fist|palm)\b")),
    ("pose_face_touch", re.compile(r"(hand (on|to) (own )?(face|cheek|chin|mouth|head|hair)"
                                   r"|covering|touching (own )?(face|hair))")),
    ("pose_holding", re.compile(r"^holding|holding\b|carrying")),
    ("pose_clothing", re.compile(r"(clothes|clothing|shirt|skirt|dress|panties|bra)"
                                 r"\s*(lift|pull|tug|aside|grab|removed?)|undress|dressing")),
    ("pose_gaze", re.compile(r"looking|gaze|glance|eye contact")),
    ("pose_arm", re.compile(r"\b(arm|arms|leg|legs|hand|hands|knee|foot|feet)\b")),
)
DEFAULT_AXIS = "pose_action"


def main() -> int:
    from core.kr_tag_loader import load_kr_tag_records
    _raw = load_kr_tag_records().raw

    def freq_of(t: str) -> int:
        return int((_raw.get(t) or {}).get("freq", 0) or 0)

    preset = json.loads(PRESET.read_text(encoding="utf-8"))
    by_tag = {str(v.get("tag", k)): v for k, v in preset["events"].items()}
    sub_axis: dict[str, str] = {}
    for key, _label, _fr, subs in AXIS_SPEC:
        for sub in subs:
            sub_axis[sub] = key

    total_written = 0
    for src, suffix in (("pose_solo", ""), ("pose_multi", "_m")):
        path = OUT / f"{src}.txt"
        if not path.exists():
            continue
        tags = [l.strip() for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
        axes: dict[str, list[str]] = {}
        unmatched = []
        for t in tags:
            rec = by_tag.get(t)
            sub = (rec or {}).get("subcategoryId", "").split("::")[-1]
            key = sub_axis.get(sub)
            if not key:
                for cand, pat in FALLBACK:
                    if pat.search(t):
                        key = cand
                        break
            if not key:
                key = DEFAULT_AXIS
                unmatched.append(t)
            axes.setdefault(key + suffix, []).append(t)
        print(f"\n[{src}] {len(tags)}개 -> {len(axes)}축  (규칙·기본값행 {len(unmatched)})")
        # 150 을 넘는 축은 빈도로 반 나눈다. `pose_action 395` 를 한 그리드에 넣으면
        # 44스크롤이라 초보자가 끝까지 볼 수 없다. 이름은 `<축>_2`, 라벨에 ' 2' 를 붙여
        # 자주 쓰는 쪽을 먼저 보게 한다.
        split_extra = {}
        for k in list(axes):
            v = axes[k]
            if len(v) <= 150:
                continue
            v.sort(key=lambda t: -freq_of(t))
            n = -(-len(v) // 150)          # 150 이하가 되도록 필요한 조각 수
            size = -(-len(v) // n)
            axes[k] = v[:size]
            for i in range(1, n):
                split_extra[f"{k}_{i + 1}"] = v[i * size:(i + 1) * size]
        axes.update(split_extra)
        for k, v in sorted(axes.items(), key=lambda kv: -len(kv[1])):
            mark = "  ⚠️150 초과" if len(v) > 150 else ""
            print(f"  {k:22s} {len(v):4d}{mark}")
            (OUT / f"{k}.txt").write_text("\n".join(v) + "\n", encoding="utf-8")
            total_written += len(v)

    SUF = ("", "_2", "_3", "_m", "_m_2", "_m_3")
    frames = {k + s: fr for k, _l, fr, _s in AXIS_SPEC for s in SUF}
    labels = {k + s: lb + ("(다인원)" if "_m" in s else "")
                    + ("" if s in ("", "_m") else " " + s.rsplit("_", 1)[-1])
              for k, lb, _f, _s in AXIS_SPEC for s in SUF}
    (OUT / "_pose_axes.json").write_text(json.dumps(
        {"framing": frames, "label": labels}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n총 {total_written}장 / _pose_axes.json 기록")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
