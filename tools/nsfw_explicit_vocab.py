# -*- coding: utf-8 -*-
"""성인 유지 기준 — **대놓고 성적인 어휘**의 단일 출처.

## 왜 rating 만으로는 안 되나

`explicit >= 70%` 로 재검했더니 성인 도감 911개 중 384개가 기준 아래였다. 그런데
그중에는 `anus peek`(explicit 66.3%, questionable 33.7%)처럼 **1%p 차이로 기준을
밑돈 것**이 섞여 있다. explicit 하나만 보면 questionable 에 몰린 것을 못 거른다.

사용자 판단(2026-08-02): **"대놓고 anus / areolae / vulva 이런 것만 성인 유지"**.
즉 통계가 아니라 **어휘**로 선을 긋는다. 통계는 과잉 분류를 찾는 데 썼고
(`virgin killer outfit` SFW 96% 같은 것), 최종 판정은 이름이 한다.

## 왜 이름 판정이 여기서는 맞나

앞서 "이름으로 판정하지 말라"는 교훈을 두 번 얻었다(`framed breasts` 가 성인으로
잡히고, `loli`/`shota` 체형 태그가 막힌 것). 그건 **이름으로 내용을 추정**한
경우다. 여기는 다르다 — 사용자가 "이 어휘가 들어간 것은 성인으로 취급한다"는
**정책**을 정한 것이고, 어휘 자체가 판정 대상이다.

## 경계 처리

`\\b` 로 감싸면 `nippleless`·`breastless` 가 빠진다(실측). 해부 어휘는 부분 문자열로
잡고, 짧아서 오탐이 나는 것만(`cum`) 경계를 준다.

애매하면 **성인에 남긴다.** 이동은 블러 해제를 동반해 되돌리기 어렵고, 남기는 것은
언제든 풀 수 있다.
"""
import re

# 해부 — 사용자가 예로 든 부류. 부분 문자열로 잡는다(nippleless 등).
_ANATOMY = (
    "anus", "anal", "areola", "vulva", "pussy", "penis", "nipple", "clitoris",
    "clit", "labia", "testicle", "scrotum", "foreskin", "cervix", "urethra",
    "genital", "pubic", "pubis", "vagina", "phallus", "glans", "perineum",
    "crotch", "groin", "ballsack", "cameltoe",
)
# 성인용 기구·구속구. 물건 이름이라 해부/행위 어휘에 안 걸린다(실측: hitachi magic
# wand·wooden horse·shibari 가 일반 축으로 샜다).
_TOY = (
    "dildo", "vibrator", "buttplug", "butt plug", "anal beads", "condom",
    "lube", "shibari", "bondage", "bdsm", "chastity", "cock ring",
    "magic wand", "wooden horse", "onahole", "sex toy", "sex machine",
    "gag", "leash", "collar", "harness", "nipple clamp", "pasties", "maebari",
)
# 노출 — 옷을 벗은 상태 자체. `zenra`(전라)는 일본어 표기라 영어 어휘로는 안 잡힌다.
_NUDITY = (
    "nude", "naked", "zenra", "topless", "bottomless", "breasts out",
    "breast out", "undressing", "exposed", "flashing",
)
# 행위 — 성행위·자위·삽입.
_ACT = (
    "sex", "cunnilingus", "fellatio", "paizuri", "masturbat", "penetrat",
    "insertion", "ejaculat", "orgasm", "handjob", "footjob", "blowjob",
    "cowgirl", "missionary", "doggystyle", "grinding", "humping", "fingering",
)
# 체액.
_FLUID = ("semen", "lactation", "breast milk", "urine", "precum", "squirt")

# `cum` 은 짧아서 `cucumber`·`document` 에 걸린다. 경계를 준다.
_BOUNDED = ("cum", "pee", "piss")

_PLAIN = tuple(sorted(set(_ANATOMY + _NUDITY + _ACT + _FLUID + _TOY)))
_RE_PLAIN = re.compile("|".join(re.escape(w) for w in _PLAIN), re.I)
_RE_BOUNDED = re.compile(r"\b(" + "|".join(_BOUNDED) + r")\b", re.I)


def is_explicit_vocab(tag: str) -> bool:
    """대놓고 성적인 어휘가 들어 있나 — 성인 도감에 남길 것."""
    t = str(tag or "")
    return bool(_RE_PLAIN.search(t) or _RE_BOUNDED.search(t))
