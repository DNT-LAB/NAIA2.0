# -*- coding: utf-8 -*-
"""자세 태그의 '필요 인원' 판정에 대한 독립 근거 — 이벤트 프리셋 조회.

## 왜 필요한가

Interactive 모드의 자세 섹션은 태그를 두 곳에 나눠 배치한다.

  SOLO   캐릭터 1명으로 성립 -> 캐릭터별 개별 슬롯
  MULTI  2명 이상이 필요     -> 이미지 전체에 적용되는 글로벌 슬롯

이 판정을 LLM(Codex / 서브에이전트)에게 맡기면 그럴듯하지만 틀린 답이 섞인다.
`core/event_preset/event_preset_category_translations_ko.json` 은 사람이 큐레이션한
3,487개 태그 분류(22 서브그룹 / 158 하위분류)라서, 같은 질문에 대한 **독립적인 근거**가
된다. 예를 들어 `interaction_hug_embrace` 하위분류에 있는 태그는 상대가 필요하고,
`gesture_self_face` 에 있는 태그는 자기 얼굴을 만지는 것이라 혼자서 된다.

LLM 판정을 대체하지 않는다. **불일치를 표면화**해서 사람이 볼 곳을 좁힌다.

## 쓰는 법

    from core.interactive_pose_evidence import PoseEvidence
    ev = PoseEvidence()
    ev.lookup("hug")           # -> Evidence(hint='MULTI', subcategory='...hug_embrace', ...)
    ev.disagreements({"hug": "SOLO", "sitting": "SOLO"})   # -> [불일치 목록]

CLI:

    python -m core.interactive_pose_evidence --check <분류파일.md>
    python -m core.interactive_pose_evidence --tag "clothes pull"
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Literal

Hint = Literal["SOLO", "MULTI", "BOTH", ""]

PRESET_PATH = (Path(__file__).resolve().parent / "event_preset"
               / "event_preset_category_translations_ko.json")

# ── 하위분류 -> 인원 함의 ────────────────────────────────────────────────────
# 하위분류 이름과 실제 수록 태그를 대조해 손으로 매겼다. 확실한 것만 적고 나머지는
# 비워 둔다(근거 없음 = 침묵). 애매한 것을 억지로 채우면 검증기가 거짓 확신을 준다.
#
# 접두 `expression action::` / `nsfw::` 는 떼고 마지막 마디로만 매칭한다.
# ⚠️ 처음에 상호작용/접촉 계열을 통째로 MULTI 로 넣었다가 오경보가 쏟아졌다
# (Codex 2,119개 대조에서 불일치 108건, 대부분 프리셋 쪽이 아니라 내 매핑이 문제).
# 실측으로 드러난 것: 이 하위분류들은 '무엇과 접촉하는가'를 나눈 것이지
# '사람과 접촉하는가'를 나눈 것이 아니다.
#   verb_contact            hugging object(책·인형), petting(동물), grabbing own breast
#   pose_between            arm between breasts — 사람 사이가 아니라 신체 부위 사이
#   pose_on_body            food on head, animal on lap — 물건·동물이 몸에 올려진 것
#   interaction_grab_hold   pillow grab, clothes tug — 물건을 쥐는 것
#   interaction_hug_embrace hugging doll, animal hug — 인형·동물을 안는 것
#   pose_restraint          hogtie, chained wrists — 밧줄은 사람이 아니다 -> 오히려 SOLO
# 그래서 명백한 것만 남겼다. 나머지는 설명 신호에 맡긴다.
_MULTI = {
    "interaction_kiss",           # 키스는 상대가 있어야 한다
    "interaction_confrontation",  # 대치
    "interaction_communication",  # 대화
    "interaction_shared_item",    # 물건을 함께 든다
    "gesture_touch_other",        # 이름 자체가 '남을' 만지는 것
    "combat_grapple",             # 맞잡고 겨루기
    "sex_acts_pairing", "sex_acts_group", "sex_acts_penetrative",
    "sex_acts_oral", "sex_acts_coercion",
    "positions_standard", "positions_variant", "positions_multi", "positions_after",
    "bondage_domination",
}
_SOLO = {
    # 자기 몸에 하는 제스처
    "gesture_self_body", "gesture_self_face", "gesture_hair", "gesture_covering",
    "gesture_hand_sign", "gesture_pointing", "gesture_arm_raise", "gesture_mouth",
    "gesture_weapon",
    # 옷 다루기 — 사용자 지침: 혼자서도 되는 행위는 기본 1인 취급.
    #   "옷벗기, 잡아당기기 같은 1인으로도 가능한 Action은 기본적으로 1인 취급입니다."
    "gesture_clothing", "clothing_adjust", "clothing_aside", "clothing_displaced",
    "clothing_lift", "clothing_open", "clothing_other", "clothing_pull",
    "clothing_put_on", "clothing_remove",
    "activity_apparel_action", "activity_apparel_adjustment", "activity_adjustment",
    # 자세·팔다리 위치는 몸 하나로 정의된다.
    "sitting", "standing", "lying", "kneeling", "crouching", "leaning",
    "limb_arms", "limb_body", "limb_hands", "limb_legs",
    "pose_arm_rest", "pose_body_display", "pose_feet_legs", "pose_resting",
    "pose_surface", "pose_acrobatic", "pose_in_container",
    # 물건을 드는 것은 사람이 아니라 소품이다. 생물도 소품 취급한다(동물은 2번째
    # 캐릭터가 아니다).
    "holding_tool_prop", "holding_weapon", "holding_food_drink", "holding_instrument",
    "holding_device_media", "holding_document_sign", "holding_misc",
    "holding_body_self", "holding_creature",
    # 혼자 하는 활동
    "activity_locomotion", "activity_sports_athletics", "activity_bathing_hygiene",
    "activity_domestic_daily", "activity_creative_intellectual",
    "activity_performance", "activity_looking_observing", "activity_oral_action",
    "activity_hair_body_manipulation", "activity_kinesis_magic",
    "verb_locomotion", "verb_sleep", "verb_eating_drinking", "verb_grooming",
    "verb_sports", "verb_work", "verb_creative", "verb_sound",
    "combat_martial_art", "combat_ranged", "combat_strike", "combat_state",
    "combat_weapon_combat",
    "gaze_direction", "gaze_other", "gaze_through",
    "body_state_physical", "personality_dance",
    "sex_acts_masturbation", "sex_acts_breast",
    "exposure_anatomy", "exposure_nipple", "exposure_pussy", "exposure_pectoral",
    "exposure_peek_view", "exposure_censoring", "exposure_other",
    "personality_physical_state",
    # 밧줄·사슬에 묶인 자세는 혼자서 렌더된다(묶는 사람이 화면에 없어도 된다).
    "pose_restraint",
}
# 판단 근거가 되지 못하는 것들(잡동사니·양쪽 다 가능). 명시해 둬야 "빠뜨린 것"과
# "일부러 비운 것"이 구분된다.
_NEUTRAL = {
    "activity_other", "activity_combat", "activity_communication",
    "activity_environmental_effect", "general", "location",
    "gesture_expressive", "gesture_other", "verb_other", "posture_other",
    "pose_other", "pose_carrying",        # 물건이냐 사람이냐로 갈린다
    "personality_archetype", "personality_other", "personality_social_situation",
    "bondage_implied", "bondage_invitation", "bondage_other", "bondage_restraint",
    "bondage_stealth", "bondage_through_clothes",
    "sex_acts_cum", "sex_acts_other",
    "sexual_activity_body_function", "sexual_activity_bondage_gear",
    "sexual_activity_condom", "sexual_activity_cum_fluid", "sexual_activity_other",
    "sexual_activity_penis", "sexual_activity_position_state",
    "sexual_activity_taboo", "sexual_activity_testicles", "sexual_activity_toy",
    "fetish_touch_fetish",
    # 접촉 대상이 사람인지 물건인지 구분하지 않는 것들 — 위 주석 참조.
    "verb_contact", "pose_between", "pose_on_body",
    "interaction_grab_hold", "interaction_hug_embrace", "interaction_gentle_touch",
    "interaction_other", "sex_acts_manual", "sex_acts_foot_body", "fetish_touch_grope",
    # NSFW 표정·상황 — 인원수와 무관한 축(표정/시점/분위기)이라 일부러 비운다.
    "nsfw_expression_face", "nsfw_expression_other", "nsfw_expression_sound",
    "nsfw_situation_dark", "nsfw_situation_imminent", "nsfw_situation_other",
    "nsfw_situation_pov", "nsfw_situation_symbol",
}


# ── 설명 기반 신호 ──────────────────────────────────────────────────────────
# 하위분류보다 **한글 설명이 훨씬 정확한 신호**다. 실측(Codex 1,066개 분류와 대조):
#   하위분류 신호 -> 불일치 78건, 그중 다수가 프리셋 쪽 오류
#   설명 신호     -> 164개 중 160 일치, 불일치 4건 전부 정규식 과탐
# 이유는 단순하다. 하위분류는 '행위의 종류'를 나눈 것이지 '필요 인원'을 나눈 것이
# 아니다 — `pose_between` 은 사람 사이가 아니라 신체 부위 사이이고,
# `pose_on_body` 는 물건이 몸에 올려진 것이다.
#
# 과탐 3종을 실측으로 걷어냈다:
#   `상대방`  fighting stance("상대방을 위협") -> 상대는 화면 밖이다
#   `서로`    interlocked fingers("손가락을 서로 깍지") -> 자기 손끼리다
#   `타인`    jack-o' challenge("잭 오 발렌'타인의'") -> 부분일치
# 그래서 강한 표현만 남기고, `타인` 은 앞 글자가 한글이면 무시한다.
_DESC_MULTI = re.compile(
    r"(다른 사람|다른 캐릭터|다른 인물|둘 이상|두 사람|여러 사람|여러 캐릭터"
    r"|(?<![가-힣])타인|남의 |파트너|서로의 몸|상대의 몸|함께 목욕)")
_DESC_SELF = re.compile(r"(자신의|스스로|자기 |본인의|혼자)")


# "자신의 머리를 땋든 다른 사람의 머리를 땋든 상관없음" 처럼 **양쪽 다 되는** 설명이 있다.
# 이건 침묵할 게 아니라 BOTH 로 표면화해야 한다 — 아래 슬롯 배치 규칙의 근거가 된다.
def _desc_hint(desc: str) -> Hint:
    """설명에서 인원 신호를 뽑는다. 근거가 없으면 침묵한다."""
    if not desc:
        return ""
    m, s = bool(_DESC_MULTI.search(desc)), bool(_DESC_SELF.search(desc))
    if m and s:
        return "BOTH"
    if m:
        return "MULTI"
    if s:
        return "SOLO"
    return ""


def slot_of(hint: Hint) -> str:
    """인원 신호 -> 슬롯.

    판정 질문은 "애매한가"가 아니라 **"1명으로 렌더되는가"** 다.
      개별 슬롯 = 1명으로 되는 것 전부 (SOLO + BOTH)
      글로벌    = 1명으로는 불가능한 것 (MULTI)

    처음에 검토자들에게 "애매하면 MULTI" 라고 지시했는데 틀렸다. `braiding hair`
    (자기 머리를 땋든 남의 머리를 땋든)를 글로벌로 보내면 캐릭터 하나를 만드는
    초보자가 그 태그에 도달할 수 없다. 반대 방향 오류(1명으로 안 되는 태그가 개별
    슬롯에 있는 것)만이 실제로 그림을 망친다 — 모델이 유령 상대를 그려낸다.
    """
    return "global" if hint == "MULTI" else "individual"



# ── 1차 신호: 이벤트 프리셋 파티션의 실측 post_count ─────────────────────────
# `data/interactive_preset_facts.json` (tools/build_preset_facts.py 로 생성).
# 프리셋 아카이브는 `{등급}_{인원구성}` 40개 파티션으로 나뉘어 있고, 각 파티션이
# 그 구성에서 나온 실제 Danbooru post_count 를 들고 있다. 즉 "이 행동이 혼자서
# 되는가"는 **추론할 필요가 없다 — 세면 된다.**
#
#   holding hands   solo    431 / multi 103,783  ->  0.4%   MULTI
#   kiss            solo    556 / multi  64,644  ->  0.9%   MULTI
#   braiding hair   solo    280 / multi     777  -> 26.5%   BOTH
#   clothes pull    solo 46,607 / multi  29,281  -> 61.4%   SOLO
#   sitting         solo617,381 / multi 303,764  -> 67.0%   SOLO
#
# 임계값은 Codex 분류 1,842개와 대조해 잡았다(슬롯 일치율 92.6%).
FACTS_PATH = Path(__file__).resolve().parent.parent / "data" / "interactive_preset_facts.json"
SHARE_MULTI = 0.20     # 이 아래면 혼자서는 거의 안 나온다
SHARE_SOLO = 0.30      # 이 위면 혼자가 일반적이다
MIN_POSTS = 50


@lru_cache(maxsize=1)
def _facts() -> dict:
    try:
        return json.loads(FACTS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"person": {}, "implications": {}}


def measured_hint(tag: str) -> tuple[Hint, dict]:
    """실측 solo 비율 -> SOLO / BOTH / MULTI. 데이터가 없으면 빈 문자열."""
    rec = _facts().get("person", {}).get(str(tag).strip().lower())
    if not rec or (rec.get("solo", 0) + rec.get("multi", 0)) < MIN_POSTS:
        return "", {}
    r = float(rec.get("share", 0.0))
    hint: Hint = "MULTI" if r < SHARE_MULTI else ("SOLO" if r >= SHARE_SOLO else "BOTH")
    return hint, rec


@dataclass(frozen=True)
class Evidence:
    tag: str
    found: bool
    hint: Hint = ""
    hint_desc: Hint = ""
    hint_category: Hint = ""
    hint_measured: Hint = ""
    solo_share: float = -1.0
    posts: int = 0
    group: str = ""
    subgroup: str = ""
    subcategory: str = ""
    label_ko: str = ""
    desc_ko: str = ""
    nsfw: bool = False

    @property
    def reason(self) -> str:
        if not self.found:
            return "이벤트 프리셋에 없음"
        if not self.hint:
            return f"근거 없음(중립 하위분류: {self.subcategory})"
        if self.hint_measured:
            return (f"실측 근거 -> {self.hint} [{slot_of(self.hint)}] "
                    f"(solo {self.solo_share:.1%}, {self.posts:,}건)")
        src = "설명" if self.hint_desc else "하위분류"
        both = " (설명+하위분류 일치)" if (
            self.hint_desc and self.hint_desc == self.hint_category) else ""
        return f"{src} 근거 -> {self.hint} [{slot_of(self.hint)}]{both}"

    @property
    def strong(self) -> bool:
        """실측이 있으면 그것이 강한 근거다. 없으면 설명+하위분류 합의를 본다."""
        if self.hint_measured:
            return True
        return bool(self.hint_desc) and self.hint_desc == self.hint_category


class PoseEvidence:
    """이벤트 프리셋을 인원-함의 조회기로 감싼 것."""

    def __init__(self, path: Path | str | None = None):
        self._path = Path(path) if path else PRESET_PATH
        data = json.loads(self._path.read_text(encoding="utf-8"))
        self._events: dict[str, dict] = data.get("events", {})
        self._by_tag = {str(v.get("tag", k)).strip().lower(): v
                        for k, v in self._events.items()}
        # 하위분류 id 의 마지막 마디만 쓴다(`a::b::c` -> `c`).
        self._leaf = {k: k.rsplit("::", 1)[-1] for k in
                      {str(v.get("subcategoryId", "")) for v in self._events.values()}}
        unknown = {leaf for leaf in self._leaf.values()
                   if leaf and leaf not in _MULTI | _SOLO | _NEUTRAL}
        self.unmapped_subcategories = sorted(unknown)

    def lookup(self, tag: str) -> Evidence:
        t = str(tag).strip().lower()
        mh, mrec = measured_hint(t)
        rec = self._by_tag.get(t)
        if rec is None:
            # 프리셋 분류에 없어도 실측은 있을 수 있다(별도 테이블이다).
            if mh:
                return Evidence(tag=tag, found=True, hint=mh, hint_measured=mh,
                                solo_share=float(mrec.get("share", -1.0)),
                                posts=int(mrec.get("solo", 0)) + int(mrec.get("multi", 0)))
            return Evidence(tag=tag, found=False)
        sub = str(rec.get("subcategoryId", ""))
        leaf = sub.rsplit("::", 1)[-1]
        cat: Hint = "MULTI" if leaf in _MULTI else "SOLO" if leaf in _SOLO else ""
        desc = str(rec.get("krDesc", "") or "")
        dh = _desc_hint(desc)
        # 우선순위: 실측 > 설명 > 하위분류.
        # 실측은 센 것이고 나머지는 읽어서 미룬 것이다 — 셀 수 있으면 세는 쪽을 쓴다.
        hint: Hint = mh or dh or cat
        return Evidence(
            tag=tag, found=True, hint=hint, hint_desc=dh, hint_category=cat,
            hint_measured=mh,
            solo_share=float(mrec.get("share", -1.0)) if mrec else -1.0,
            posts=(int(mrec.get("solo", 0)) + int(mrec.get("multi", 0))) if mrec else 0,
            group=str(rec.get("groupId", "")),
            subgroup=str(rec.get("subgroupId", "")),
            subcategory=leaf,
            label_ko=str(rec.get("labelKo", "") or ""),
            desc_ko=str(rec.get("krDesc", "") or ""),
            nsfw=str(rec.get("groupId", "")) == "nsfw",
        )

    def disagreements(self, classification: dict[str, str],
                      strong_only: bool = False) -> list[dict]:
        """LLM 분류 {태그: SOLO|MULTI|DROP} 를 받아 프리셋과 어긋나는 것만 낸다.

        strong_only=True 면 설명과 하위분류가 **둘 다 같은 답**을 낸 것만 본다.
        사람이 볼 목록을 좁힐 때 쓴다(정밀도 우선).
        """
        out = []
        for tag, verdict in classification.items():
            ev = self.lookup(tag)
            if not ev.found or not ev.hint:
                continue
            if strong_only and not ev.strong:
                continue
            v = str(verdict).strip().upper()
            if v == "DROP":            # 버리는 판단은 인원 문제와 별개다
                continue
            # 같은 슬롯으로 가면 불일치가 아니다 — SOLO 와 BOTH 는 둘 다 개별 슬롯이다.
            if slot_of(v if v in ("SOLO", "MULTI") else "") != slot_of(ev.hint):
                out.append({"tag": tag, "llm": v, "preset": ev.hint,
                            "src": "설명" if ev.hint_desc else "하위분류",
                            "strong": ev.strong, "subcategory": ev.subcategory,
                            "label_ko": ev.label_ko, "desc_ko": ev.desc_ko[:80]})
        return out

    def coverage(self, tags: Iterable[str]) -> dict[str, int]:
        c = {"total": 0, "found": 0, "hint_solo": 0, "hint_multi": 0,
             "no_hint": 0, "strong": 0}
        for t in tags:
            c["total"] += 1
            ev = self.lookup(t)
            if not ev.found:
                continue
            c["found"] += 1
            if ev.strong:
                c["strong"] += 1
            if ev.hint == "SOLO":
                c["hint_solo"] += 1
            elif ev.hint == "MULTI":
                c["hint_multi"] += 1
            else:
                c["no_hint"] += 1
        return c


@lru_cache(maxsize=1)
def get_pose_evidence() -> PoseEvidence:
    return PoseEvidence()


# ── 분류 결과 파일 파서 ─────────────────────────────────────────────────────
# Codex / 서브에이전트가 내는 형식: `## SOLO` 헤더 아래 `TAG | 이유` 줄들.
# Codex 는 `TAG | SOLO | 이유` 형태로도 낸다 — 둘 다 받는다.
def parse_classification(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    current = ""
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            head = line.lstrip("#").strip().upper()
            if head in ("SOLO", "MULTI", "DROP"):
                current = head
            continue
        if "|" not in line:
            continue
        parts = [p.strip() for p in line.split("|")]
        tag = parts[0].strip("`* ")
        if not tag:
            continue
        verdict = ""
        for p in parts[1:]:
            if p.upper() in ("SOLO", "MULTI", "DROP"):
                verdict = p.upper()
                break
        verdict = verdict or current
        if verdict:
            result[tag] = verdict
    return result


def _main(argv: list[str]) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="자세 태그 인원 판정 검증(이벤트 프리셋 대조)")
    ap.add_argument("--tag", action="append", default=[], help="태그 하나 조회")
    ap.add_argument("--check", action="append", default=[],
                    help="분류 결과 파일(.md)을 프리셋과 대조")
    ap.add_argument("--audit", action="store_true", help="매핑되지 않은 하위분류 보고")
    a = ap.parse_args(argv)

    ev = get_pose_evidence()
    if a.audit:
        print(f"매핑되지 않은 하위분류 {len(ev.unmapped_subcategories)}개")
        for s in ev.unmapped_subcategories:
            print(f"  {s}")
    for t in a.tag:
        e = ev.lookup(t)
        print(f"[{t}] found={e.found} hint={e.hint or '-'} "
              f"sub={e.subcategory or '-'}\n   {e.label_ko}  {e.desc_ko[:70]}")
    for path in a.check:
        cls = parse_classification(Path(path).read_text(encoding="utf-8"))
        cov = ev.coverage(cls)
        bad = ev.disagreements(cls)
        print(f"\n=== {path} ===")
        print(f"  분류 {cov['total']}개 / 프리셋에 있음 {cov['found']} "
              f"(SOLO 근거 {cov['hint_solo']} · MULTI 근거 {cov['hint_multi']} "
              f"· 근거없음 {cov['no_hint']})")
        print(f"  불일치 {len(bad)}건")
        for d in sorted(bad, key=lambda x: x["preset"]):
            print(f"    {d['tag']:32s} LLM={d['llm']:5s} 프리셋={d['preset']:5s} "
                  f"[{d['subcategory']}] {d['desc_ko'][:44]}")
    if not (a.tag or a.check or a.audit):
        ap.print_help()
    return 0


if __name__ == "__main__":
    import sys
    raise SystemExit(_main(sys.argv[1:]))
