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
    # 부상·오염: 얼굴 오염·부상(코피/얼굴 멍/침 흘림)을 몸통 배치(cowboy + head out of
    # frame)로 돌렸더니 흰 후드티만 나왔다(실측 33장 중 대부분). 얼굴 태그는 portrait 다.
    # 내 실수 — FACE_CONDITION 을 body_condition 에 합류시키면서 그 축의 프레이밍을
    # 고려하지 않았다.
    #
    # **이 목록은 손으로 적어서 또 샜다.** 오늘 `cream on face` 를 이 축으로 옮겼는데
    # 목록에 넣는 것을 잊어 cowboy + head out of frame 으로 돌아갔고, 얼굴이 프레임 밖으로
    # 나가 크림이 안 보이는 그림이 나왔다(실측). 그래서 **이름으로 파생되는 부분은 파생시킨다**
    # — 아래 `_FACE_WORD` 가 얼굴 부위를 이름에서 잡고, 남은 것(전신 증상)만 손으로 적는다.
    "body_condition": {
        "portrait": [
            # 이름에 얼굴 부위가 없어 파생으로 잡히지 않는 전신 증상.
            "snot", "snot trail", "turn pale",
            "fever", "pain", "dazed", "headache", "hangover", "dizzy", "drunk", "tipsy",
            "mouth submerged",
        ],
    },
    # 날개: 머리 날개는 portrait 로 따로 — spread wings 베이스에선 머리가 잘린다.
    "wings": {
        "portrait": ["head wings", "hair wings", "single head wing"],
    },
    # 효과: `blurry` 는 **기본 네거티브와 베이스의 `-1::widescreen, blurry ::` 양쪽에서
    # 억제된다.** 그 배치로는 아무리 돌려도 안 나오고, 실제로 이 칸은 생성된 적이 없는데도
    # 팩에 값이 있었다(축에서 제외된 태그 이미지 63장이 오분류로 들어와 있었다).
    # 억제를 걷은 `fx_effect_blurry` 배치로 가른다.
    "fx_effect": {
        "blurry": ["blurry"],
    },
    # 종족(남성): `species_male` 배치의 네거티브가 `-1:: furry, furry male, snout,
    # animal nose, body fur ::` 로 수인성을 억제한다. 그건 `cat boy` 처럼 케모미미만
    # 원하는 37개에는 맞지만, **완전 수인·반인반수인 이 둘에는 정면으로 반대다**
    # (실측: 둘 다 수인 요소 없는 맨 남성이 나왔다). 억제 없는 배치로 가른다.
    "species_male": {
        "furry": ["furry male", "monster boy"],
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
#
# **실측이 정규식을 이긴다.** 아래 정규식은 이름만 보고 추정하는 것이라 양쪽으로 틀렸다:
#   - `pectorals` / `large pectorals` / `huge pectorals` 는 male/man 이 없어 놓쳤다.
#     그래서 1girl 배치로 돌아 **남성기가 그려진 썸네일**이 팩에 들어갔다(사용자 발견).
#   - 거꾸로 `male underwear` / `male swimwear` / `pectoral cleavage` 는 실제로 여성이
#     입은 그림인데 1boy 로 보내 잘 나온 것을 갈아버린다.
# 그래서 tools/thumb_male_tags.py 의 실측 결과를 먼저 보고, 실측이 없는 것만 추정한다.
# (그 파일은 thumb_axes_build 의 생성 배치와 thumb_axes_emit 의 UI 격리도 같이 읽는다.)
from tools.thumb_male_tags import is_male_render

# 이름에 얼굴 부위가 들어가면 그 태그는 portrait 배치여야 한다. 손 목록을 대신 파생시켜
# 새 태그가 조용히 몸통 배치로 가는 것을 막는다(`cream on face` 가 그렇게 샜다).
_FACE_WORD = re.compile(
    r'\b(face|facial|mouth|nose|nostril|lip|lips|tongue|cheek|forehead|chin|jaw'
    r'|eye|eyes|eyebrow|eyelash|ear|ears|teeth|tooth|saliva|drool|snot|nosebleed)\b'
    r'|\bon face\b|\bfrom mouth\b')
DERIVED_SPLIT = {
    "body_condition": {"portrait": _FACE_WORD},
}

FACIAL_HAIR = re.compile(r'beard|mustache|stubble|goatee', re.I)
MALE_WORD = re.compile(r'(^|[\s\-])(male|man|men|boy|boys)($|[\s\-])'
                       r'|^(miniboy|strongman)|strongman', re.I)
MALE_EXTRA = {"male with breasts", "male pubic hair"}

def is_male(tag: str) -> bool:
    known = is_male_render(tag)
    if known is not None:
        return known
    t = tag.lower()
    if t in MALE_EXTRA or FACIAL_HAIR.search(t):
        return True
    # 'pac-man eyes' 같은 합성어 오탐을 막는다
    if t.startswith('pac-man'):
        return False
    return bool(MALE_WORD.search(t))

# 큐에 올리지 않기로 한 것. 성인 축은 `wildcards/nsfw/_unrendered.txt` 가 같은 일을 한다.
# 없으면 매번 "남음 N장" 으로 떠서 왜 안 만들었는지를 다시 조사하게 된다.
PARK = OUT / "_unrendered.txt"
parked: set[tuple[str, str]] = set()
if PARK.exists():
    for _l in PARK.read_text(encoding="utf-8").splitlines():
        _l = _l.strip()
        if not _l or _l.startswith("#"):
            continue
        _c = _l.split("\t")
        if len(_c) >= 2:
            parked.add((_c[0].strip(), _c[1].strip()))

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

# 화면에 뜨는 축만 골라낸다. `pose_solo`(1,592)·`pose_multi`(439) 같은 **분류기의
# 중간 산출물**은 표시 축이 아닌데도 합계에 들어가, "생성 대기 2,045장" 처럼
# 실제보다 훨씬 큰 숫자를 보고했다(2026-08-04 사용자 지적). 실제로는 그 태그들이
# 표시 축에 한 벌 더 있고 그림도 거기 있다 — 화면 빈칸은 0이었다.
_AXJS = Path("app/web/remote/js/features/interactiveAxes.mjs")
WIRED = set(re.findall(r'ref: "([a-z0-9_]+)"', _AXJS.read_text(encoding="utf-8")))
WIRED.add("face")        # face_eyes/face_parts 로 갈라지는 컨테이너
# 표시 축 키로 이미 그림이 있는 태그. 중간 산출물의 '대기'가 진짜인지 가른다.
COVERED = {t for ax in WIRED for t in have.get(PACK_AXIS.get(ax, ax), set())}

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
    tags = [t for t in tags if (ax, t) not in parked]
    fem = [t for t in tags if t not in h and not is_male(t)]
    male = [t for t in tags if is_male(t) and t not in h]
    fem.sort(key=lambda t: -F(t)); male.sort(key=lambda t: -F(t))
    # 한 축 안에서 프레이밍이 갈리면 배치를 쪼갠다 — 안 그러면 절반이 프레임 밖으로 나간다.
    # **여성 목록에만 적용하던 것을 남성 목록에도 적용한다.** `species_male` 의 남은 2장
    # (`furry male` · `monster boy`)이 그 축의 기본 네거티브(`-1:: furry, furry male ... ::`)에
    # 정면으로 막혀 수인이 아닌 맨 남성으로 나왔다(실측). 태그를 억제하는 배치로 그 태그를
    # 돌리는 것은 프레이밍 문제와 같은 종류다 — 축이 아니라 배치를 갈라야 한다.
    split_n = 0
    split = FRAMING_SPLIT.get(ax)
    # 이름으로 파생되는 부분은 파생시킨다(손 목록은 새 태그를 놓친다 — `cream on face` 실측).
    if ax in DERIVED_SPLIT:
        split = {k: list(v) for k, v in (split or {}).items()}
        for _fr, _rx in DERIVED_SPLIT[ax].items():
            _hit = [t for t in tags if _rx.search(t.lower())]
            split.setdefault(_fr, [])
            split[_fr] = sorted(set(split[_fr]) | set(_hit))
    if split:
        _all_split = {t for v in split.values() for t in v}
        for _lst in (fem, male):
            for _fr, _tags in split.items():
                _sub = [t for t in _lst if t in _tags]
                if _sub:
                    _f = TODO / f"{ax}_{_fr}.txt"
                    # fem/male 은 서로소이므로 같은 파일에 두 번 쓰이지 않는다.
                    assert not _f.exists(), f"{_f.name} 이 두 번 써진다"
                    _f.write_text("\n".join(_sub) + "\n", encoding="utf-8")
                    split_n += len(_sub)
        fem = [t for t in fem if t not in _all_split]
        male = [t for t in male if t not in _all_split]
    if fem:
        (TODO / f"{ax}.txt").write_text("\n".join(fem) + "\n", encoding="utf-8")
    if male:
        # 이미 남성 축(`species_male`)이면 접미를 겹치지 않는다 — `species_male_male.txt` 는
        # `_bench.json` 에 대응 배치가 없어 그 2장이 영영 생성되지 않았다.
        _mf = ax if ax.endswith("_male") else f"{ax}_male"
        assert not (_mf == ax and fem), \
            f"{ax}: 남성 축인데 여성 목록이 있다 — 파일이 서로를 덮는다 ({fem})"
        (TODO / f"{_mf}.txt").write_text("\n".join(male) + "\n", encoding="utf-8")
    # 분할분(split_n)을 합계에 넣지 않아 실제보다 적게 보고하던 버그를 고쳤다.
    total += len(fem) + len(male) + split_n
    rows.append((ax, len(tags), len(h), len(fem) + split_n, len(male)))

print(f"{'축':<14}{'목록':>5}{'보유':>5}{'남을것(여)':>10}{'남성':>6}")
for ax, n, hv, f_, m_ in rows:
    flag = "" if (f_ or m_) else "  DONE"
    if ax not in WIRED:
        flag += "  (미표시 축)"
    print(f"{ax:<14}{n:>5}{hv:>5}{f_:>10}{m_:>6}{flag}")

_shown = sum(f_ + m_ for ax, _n, _h, f_, m_ in rows if ax in WIRED)
_mirror = _other = 0
for ax, _n, _h, _f, _m in rows:
    if ax in WIRED:
        continue
    _pend = [t for t in ((TODO / f"{ax}.txt").read_text(encoding="utf-8").splitlines()
                         if (TODO / f"{ax}.txt").exists() else []) if t.strip()]
    _mirror += sum(1 for t in _pend if t in COVERED)
    _other += sum(1 for t in _pend if t not in COVERED)
print(f"\n화면에 빈칸으로 뜨는 것: {_shown}장  <- 이것만 생성 대상이다")
print(f"미표시 축 {_mirror + _other}장 = 표시 축에 이미 그림이 있는 사본 {_mirror}"
      f" + 표시 축에 없는 것 {_other}")
print(f"생성 대기 총 {total}장 -> {TODO}")
