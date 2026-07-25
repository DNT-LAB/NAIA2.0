# -*- coding: utf-8 -*-
"""아직 생성되지 않은 썸네일 배치 목록을 만든다 — wildcards/thumb/_todo/.

팩(data/interactive_thumbnails.json)에 이미 있는 키를 빼고, 남은 것을
'베이스 프롬프트가 같은 것끼리' 파일로 묶는다. 배치를 돌린 뒤 다시 실행하면
줄어든 목록이 다시 써진다(멱등).

베이스 구분:
  <axis>.txt        여성 베이스 (1girl)
  <axis>_male.txt   남성 베이스 (1boy) — 1girl 로는 렌더되지 않는 태그
                    수염 계열은 이미 생성됐어도 재생성 대상이다(소녀 얼굴에
                    수염만 얹힌 불량이 실측으로 확인됐다).
프레이밍은 _manifest.json 의 axis_framing 을 따른다.
"""
import json, re
from pathlib import Path
from core.kr_tag_loader import load_kr_tag_records

OUT = Path("wildcards/thumb")
TODO = OUT / "_todo"
PACK = Path("data/interactive_thumbnails.json")

raw = load_kr_tag_records().raw
F = lambda t: int((raw.get(t) or {}).get('freq', 0) or 0)

# 표시 축 -> 팩 축 (얼굴 표시 그룹은 모두 face/* 를 읽는다)
PACK_AXIS = {"face_eyes": "face", "face_mouth": "face", "face_etc": "face"}

# 한 축 안에서 프레이밍이 갈리는 태그 — 별도 배치로 뽑는다.
# 이형 부위는 머리 부속(아가미/더듬이/머리 지느러미)과 다리·발(발굽/새 다리)이 섞여 있어
# cowboy shot(head out of frame) 하나로는 절반이 프레임 밖이 된다.
FRAMING_SPLIT = {
    # 상태: 얼굴 현상(홍조/눈물/땀)은 portrait, 몸통·사지(붕대/멍/더러운 발)는 cowboy.
    "state": {
        # bandage over one eye / steaming body 는 몸통 배치에서 실패했다(실측):
        # 안대는 눈에 있어 head out of frame 이면 프레임 밖이고, 김은 몸 전체에서
        # 올라오는데 하복부 클로즈업이 나왔다 -> 얼굴 배치(state)로 되돌린다.
        "body": ["bandages", "wet clothes", "bandaged arm", "injury",
                 "bandaged leg", "stitches", "blood on hands", "soaking feet", "bruise",
                 "bandaged hand", "sweaty armpits", "cuts",
                 "bite mark", "scratches", "slap mark", "hickey", "blood on arm",
                 "blood on leg", "dirty feet", "whip marks", "blood on chest",
                 "broken arm", "dirty hands", "broken leg", "bleeding"],
    },
    # 날개: 머리 날개는 portrait 로 따로 — spread wings 베이스에선 머리가 잘린다.
    "wings": {
        "portrait": ["head wings", "hair wings", "single head wing"],
    },
    # 표식: 얼굴·머리(귀 피어싱/이마 문신/입술)는 portrait, 몸통(팔·가슴·배 문신)은 cowboy.
    "marking": {
        "portrait": ["ear piercing", "neck tattoo", "animal ear piercing", "eyebrow piercing",
                     "lip piercing", "star facial mark", "heart facial mark", "teardrop tattoo",
                     "forehead tattoo", "flower over eye", "joestar birthmark", "ear birthmark",
                     "tongue tattoo", "head tattoo", "lipstick mark on face", "lip ring",
                     "labret piercing", "spiked ear piercing", "ear bar", "eyeliner",
                     "lipstick mark on neck", "collarbone piercing", "horn piercing"],
    },
    "body_nonhuman": {
        "portrait": ["gills", "blowhole", "antennae", "moth antennae", "head fins",
                     "neck fur", "chest tuft", "third eye on chest", "core",
                     "extra breasts", "male with breasts", "fluff", "spines"],
        "full": ["hooves", "animal feet", "bird legs", "digitigrade", "webbed feet",
                 "cat feet", "pawpads", "talons", "reverse-jointed legs", "no feet",
                 "multiple legs", "sharp toenails", "dorsal fin", "shark fin", "fins"],
    },
}

# 1girl 베이스로는 렌더되지 않는다.
FACIAL_HAIR = re.compile(r'beard|mustache|stubble|goatee', re.I)
MALE_WORD = re.compile(r'(^|[\s\-])(male|man|men|boy|boys)($|[\s\-])'
                       r'|^(miniboy|strongman)|strongman', re.I)
MALE_EXTRA = {"pectoral cleavage", "male with breasts", "male pubic hair"}

def is_male(tag: str) -> bool:
    t = tag.lower()
    if t in MALE_EXTRA or FACIAL_HAIR.search(t):
        return True
    # 'pac-man eyes' 같은 합성어 오탐을 막는다
    if t.startswith('pac-man'):
        return False
    return bool(MALE_WORD.search(t))

pack = json.loads(PACK.read_text(encoding="utf-8")) if PACK.exists() else {}
have = {}
for k in pack:
    ax, tag = k.split('/', 1)
    have.setdefault(ax, set()).add(tag)

# 기존 _todo 는 매번 비운다(다 끝난 축의 파일이 남아 헷갈리지 않게)
TODO.mkdir(exist_ok=True)
for old in TODO.glob("*.txt"):
    if old.stem.startswith("_"):
        continue        # _redo_* 같은 손으로 만든 재검수 배치는 보존한다
    old.unlink()

rows, total = [], 0
for wc in sorted(OUT.glob("*.txt")):
    ax = wc.stem
    if ax.startswith('_'):
        continue
    tags = [l.strip() for l in wc.read_text(encoding="utf-8").splitlines() if l.strip()]
    h = have.get(PACK_AXIS.get(ax, ax), set())
    # 수염 계열은 한때 1girl 베이스로 잘못 생성돼(소녀 얼굴에 수염만 얹힘) 팩에 있어도
    # 강제 재생성 대상이었다. 1boy/mature male 로 다시 뽑아 들어갔으므로 이제는 다른
    # 축과 같게 '팩에 없는 것만' 남긴다.
    fem = [t for t in tags if t not in h and not is_male(t)]
    male = [t for t in tags if is_male(t) and t not in h]
    fem.sort(key=lambda t: -F(t)); male.sort(key=lambda t: -F(t))
    # 한 축 안에서 프레이밍이 갈리면 배치를 쪼갠다 — 안 그러면 절반이 프레임 밖으로 나간다.
    split_n = 0
    split = FRAMING_SPLIT.get(ax)
    if split and fem:
        for _fr, _tags in split.items():
            _sub = [t for t in fem if t in _tags]
            if _sub:
                (TODO / f"{ax}_{_fr}.txt").write_text("\n".join(_sub) + "\n", encoding="utf-8")
                split_n += len(_sub)
        fem = [t for t in fem if not any(t in v for v in split.values())]
    if fem:
        (TODO / f"{ax}.txt").write_text("\n".join(fem) + "\n", encoding="utf-8")
    if male:
        (TODO / f"{ax}_male.txt").write_text("\n".join(male) + "\n", encoding="utf-8")
    # 분할분(split_n)을 합계에 넣지 않아 실제보다 적게 보고하던 버그를 고쳤다.
    total += len(fem) + len(male) + split_n
    rows.append((ax, len(tags), len(h), len(fem) + split_n, len(male)))

print(f"{'축':<14}{'목록':>5}{'보유':>5}{'남을것(여)':>10}{'남성':>6}")
for ax, n, hv, f_, m_ in rows:
    flag = "" if (f_ or m_) else "  DONE"
    print(f"{ax:<14}{n:>5}{hv:>5}{f_:>10}{m_:>6}{flag}")
print(f"\n생성 대기 총 {total}장 -> {TODO}")
