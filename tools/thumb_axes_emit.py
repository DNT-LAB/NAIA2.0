# -*- coding: utf-8 -*-
"""wildcards/thumb/* -> app/web/remote/js/features/interactiveAxes.mjs 생성.

와일드카드 .txt / _palette.json 이 단일 출처다. 프론트 모듈은 여기서 파생시켜
손으로 옮길 때 생기는 드리프트를 막는다.
"""
import json
import re
from pathlib import Path

SRC = Path("wildcards/thumb")
# `_m` 접미사로만 판정한다. `in ax` 로 보면 pose_mo|u|th 의 `_m` 에 걸린다.
_RE_POSE_MULTI = re.compile(r"_m(_\d+)?$")
DST = Path("app/web/remote/js/features/interactiveAxes.mjs")

palette = json.loads((SRC / "_palette.json").read_text(encoding="utf-8"))
man = json.loads((SRC / "_manifest.json").read_text(encoding="utf-8"))

# 성인 축은 생성 대상 폴더 밖에 둔다(도구가 축으로 읽어 생성 대상에 넣는 것을 막는다).
# 여기서는 **읽어야** 한다 — 안 그러면 UI 에 태그가 안 실려 빈 그리드가 된다.
NSFW_SRC = Path("wildcards/nsfw")
# 성인 축은 파이프라인이 자동 생성하지 않는다(사용자가 직접 돌린다). 그래서 그림이 없는
# 태그는 **영구 빈칸**이 된다 — `diaper` 와 재갈 4종이 그렇다(의도적 제외).
# 제외 목록을 여기 또 적지 않는다. 목록을 두 군데 적으면 갈라진다(이 프로젝트 사고의 대부분).
# **팩에 그림이 있는가**로 거른다 — 나중에 사용자가 만들면 자동으로 나타난다.
_PACK_PATH = Path("data/interactive_thumbnails.json")
_PACK_KEYS = set(json.loads(_PACK_PATH.read_text(encoding="utf-8"))) if _PACK_PATH.exists() else set()


def lines(name):
    p = SRC / f"{name}.txt"
    if not p.exists() and name.startswith("nsfw_"):
        p = NSFW_SRC / f"{name}.txt"
    if not p.exists(): return []
    out = [l.strip() for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
    if name.startswith("nsfw_") and _PACK_KEYS:
        out = [t for t in out if f"{name}/{t}" in _PACK_KEYS]
    return out

# ---- 얼굴 축의 '표시용' 하위 그룹 ----
# 생성은 face.txt(228) 한 파일로 계속 돈다(순차 와일드카드 진행 중). UI 에서만 subgroup 기준으로
# 나눠 보여주고, 썸네일 이미지는 모두 팩의 face/* 키를 쓴다(packAxis).
from core.kr_tag_loader import load_kr_tag_records as _lk   # noqa: E402
import core.interactive_browse_index as _ib                 # noqa: E402
_raw2 = _lk().raw
_idx2 = _ib.InteractiveBrowseIndex(_raw2)
_F2 = lambda t: int((_raw2.get(t) or {}).get("freq", 0) or 0)
_SG2 = lambda t: str((_raw2.get(t) or {}).get("subgroup", "")).lower()
_face_all = lines("face")
# 눈 색 패턴(추가 색상이 필요한 것들). heterochromia 는 subgroup 'eyes',
# two-tone/gradient eyes 는 계층 밖이라 face.txt 에 없다 -> 별도 와일드카드로 만든다.
EYE_PATTERN = ["multicolored eyes", "heterochromia", "two-tone eyes", "gradient eyes"]
_eye_pattern = [t for t in EYE_PATTERN if t in _raw2]
_ep = SRC / "eye_pattern.txt"
_ep.write_text("\n".join(sorted(_eye_pattern, key=lambda t: -_F2(t))) + "\n", encoding="utf-8")
_eye_pattern = lines("eye_pattern")
# 남성 계열(수염)은 별도 그룹으로 뺀다. 목록은 tools/thumb_male_tags.py 가 SSOT.
# subgroup 으로 나누면 이것들이 흩어진다 — `beard` 는 face_tags 인데 `full beard` 는
# hair_styles 라서, 실제로 수염 6개(beard stubble/long beard/full beard/pencil mustache/
# thick beard/tied beard)가 **어느 표시 그룹에도 못 들어가 화면에서 사라져 있었다.**
# 남성 그룹을 태그 목록에서 직접 만들면 그 6개도 같이 회수된다.
from tools.thumb_male_tags import MALE_ONLY, MALE_EXPLICIT   # noqa: E402

_groups = {"face_eyes": [], "face_parts": [], "face_mark": [], "face_male": []}
_bucket = {"eyes_tags": "face_eyes", "face_tags": "face_parts",
           "face_meta": "face_mark", "face": "face_mark"}
for _t in _face_all:
    if _t in _eye_pattern:
        continue
    if _t in MALE_ONLY:
        _groups["face_male"].append(_t)
        continue
    _key = _bucket.get(_SG2(_t))
    if _key:
        _groups[_key].append(_t)
for _k in _groups:
    _groups[_k].sort(key=lambda t: -_F2(t))
assert _groups["face_male"], "얼굴 축의 남성 그룹이 비었다 — MALE_ONLY 와 face.txt 가 갈라졌다"

# ── 의상 탐색기 스코프 파생 ─────────────────────────────────────────────────
# 의상 슬롯의 36개 서브그룹을 두 슬롯에 빠짐없이 나눈다. 손으로 나열하면 반드시 샌다
# (실제로 19개 259개가 빠졌다 — 팬티 75·브라 45 포함).
# 기준은 thumb_clothing_build.SUB_AXIS 의 축 배정이고, 매핑이 없는 서브그룹
# (attire / 이관된 tan_marks·cosmetics / alternate·costume_props)은 '의상'으로 보낸다.
import tools.thumb_clothing_build as _cb   # noqa: E402

_GEAR_AXES = {"cloth_headwear", "cloth_hairacc", "cloth_neck", "cloth_eyewear",
              "cloth_handwear", "cloth_sleeve", "cloth_legwear", "cloth_footwear",
              "cloth_accessory", "cloth_armor"}
_BROWSE_WEAR, _BROWSE_GEAR = [], []
for _s in _idx2.subgroups("clothing"):
    _dst = _GEAR_AXES.__contains__(_cb.SUB_AXIS.get(_s["id"], ""))
    (_BROWSE_GEAR if _dst else _BROWSE_WEAR).append(_s["id"])
_missing = ({s["id"] for s in _idx2.subgroups("clothing")}
            - set(_BROWSE_WEAR) - set(_BROWSE_GEAR))
assert not _missing, f"탐색기에서 빠진 서브그룹: {_missing}"

# 자세 축은 build_pose_axes 가 정하고 _pose_axes.json 에 라벨까지 적는다. 여기서 다시
# 적으면 갈라진다 — 실제로 갈라져서 없어진 축이 남고 신설 축이 빠져 있었다.
# 개별 슬롯에는 1인 축만 온다. `_m` 은 씬의 '다인원 자세' 담당이다.
_pose_axes = json.loads((SRC / "_pose_axes.json").read_text(encoding="utf-8"))
_POSE_SECTIONS = [("thumb", _pose_axes["label"][_ax], _ax)
                  for _ax in _pose_axes["label"]
                  if (SRC / f"{_ax}.txt").exists() and not _RE_POSE_MULTI.search(_ax)]
_POSE_MULTI = [_ax for _ax in _pose_axes["label"]
               if (SRC / f"{_ax}.txt").exists() and _RE_POSE_MULTI.search(_ax)]

# 배경 축은 build_location_axes 가 정하고 `_loc_axes.json` 에 라벨까지 적는다.
# 자세와 같은 방식 — 여기서 다시 적으면 갈라진다.
_loc = json.loads((SRC / "_loc_axes.json").read_text(encoding="utf-8"))
_LOC_SECTIONS = [("thumb", _loc["label"][_ax], _ax)
                 for _ax in _loc["label"] if (SRC / f"{_ax}.txt").exists()]

# 사물·동물·효과 축도 같은 방식으로 파생시킨다(각 build_*_axes.py 가 SSOT).
def _sections(js_name):
    spec = json.loads((SRC / js_name).read_text(encoding="utf-8"))
    return [("thumb", spec["label"][a], a) for a in spec["label"]
            if (SRC / f"{a}.txt").exists()]

_OBJ_SECTIONS = _sections("_obj_axes.json")
_ANI_SECTIONS = _sections("_ani_axes.json")
_FX_SECTIONS = _sections("_fx_axes.json")
# 구도·기타텍스트. 전에는 두 슬롯 다 탐색기(트리)였다 — 그림이 한 장도 없었기 때문이다.
# 2026-08-01 에 242장을 만들어 그리드로 바꿨다. `_sections` 가 .txt 존재를 확인하므로
# 축을 지우면 여기서도 자동으로 빠진다(`view_gaze` 통합 때 그렇게 빠졌다).
# 시선(`pose_gaze`)은 자세가 아니라 구도다 — "어디를 보는가"는 프레이밍·시점과 같은
# 질문이다(사용자 판단 2026-08-01). `_pose_axes.json` 에서 오지만 구도 슬롯이 쓴다.
_GAZE_SECTION = [("thumb", "시선", "pose_gaze")]
_POSE_SECTIONS = [x for x in _POSE_SECTIONS if x[2] != "pose_gaze"]
_VIEW_SECTIONS = _sections("_view_axes.json") + _GAZE_SECTION
_META_SECTIONS = _sections("_meta_axes.json")

# 슬롯 = 사용자가 인지하는 카테고리. 그 안에 축(팔레트/슬라이더/썸네일/탐색)을 배치한다.
# 팝업이 축을 모아 보여주므로 좌측 슬롯 수를 늘리지 않는다.
SLOTS = [
    ("머리", "\\u{1F487}", "characteristic", [
        ("palette", "색", "hair_color"),
        ("slider", "길이", "hair_length"),
        ("thumb", "모양", "hair_style"),
        ("thumb", "앞머리", "bangs"),
        # 추가 색상 팔레트는 패턴 섹션 안(그리드 위)에 넣는다 — 아래에 두면 그리드에 가린다.
        ("thumb_extra", "패턴", "hair_pattern", "hair_color"),
    ]),
    ("눈·얼굴", "\\u{1F441}", "characteristic", [
        ("palette", "눈 색", "eye_color"),
        # 색 관련(오드아이/다색/그라데이션)은 머리 패턴과 같은 방식으로 분리 — 추가 색상 동반.
        ("thumb_extra", "눈 색 패턴", "eye_pattern", "eye_color"),
        ("thumb", "눈·눈썹·동공", "face_eyes"),
        ("thumb", "얼굴·입·코", "face_parts"),
        ("thumb", "표식·점", "face_mark"),
        # 수염 13개는 전부 중년 남성 나체 상반신으로 렌더됐다(실측). 다른 얼굴 요소와
        # 나란히 두면 점·주름을 고르러 온 사용자가 그걸 보게 된다 — 별도 섹션으로 뺀다.
        ("thumb", "수염(남성)", "face_male"),
        # 눈·입·눈썹의 형태는 감정이 아니라 구조다(Codex 지적) — 여기가 맞다.
        ("thumb", "눈·입 형태", "face_shape"),
        # 얼굴 썸네일 228장이 face_tags/eyes_tags/face_meta/face 를 전부 덮으므로 탐색기 제거.
    ]),
    # 표정 슬롯을 썸네일+탐색기 병행으로 승격한다. 해체한 상태 축의 감정 부수 현상
    # (blush/tears/saliva/sweatdrop)과 생리 상태를 여기로 모았다 — 데이터가 그것들을
    # expression subgroup 으로 분류하고 설명도 "부끄러움 등으로"/"긴장이나 당혹감"이다.
    # smile(1664k) 등 나머지 감정 표현은 아직 썸네일이 없어 탐색기가 담당한다.
    ("표정", "\\u{1F60A}", "expression", [
        ("thumb", "감정", "expression"),
        ("thumb", "기호 표정", "expression_symbol"),
        ("thumb", "홍조·눈물·땀", "expression_state"),
        # 성격·유형. 자세 fallback 이 `pose_display` 로 쓸어넣고 있던 것을 되돌렸다 —
        # 성격은 자세가 아니다. 태그 DB 도 `Expression_Action` 소속으로 본다.
        ("thumb", "성격·유형", "persona"),
        # 탐색기 제거: 279개 중 258개(92%)가 이미 썸네일에 있는 중복이고 전용 21개는
        # 전부 저빈도였다. 검색은 `thumb` 만 있어도 붙으므로 `scope` 도 필요 없다.
    ]),
    ("신체", "\\u{1F9CD}", "characteristic", [
        ("slider", "가슴", "breast_size"),
        ("thumb", "체형", "body_type"),
        # 남성 체형·흉근. 섞어 두면 체형을 고르러 온 사용자에게 남성 나체가 먼저 보인다.
        ("thumb", "체형(남성)", "body_type_male"),
        # colored / multicolored skin 을 고르면 그리드 위에 피부 색 팔레트가 나온다.
        ("thumb_color", "피부", "skin", "skin_color"),
        # 신체 부위는 두 성격으로 나눈다 — '부위가 보인다'(구도성) vs '그 특징이 있다'(특징성).
        ("thumb", "노출·강조", "body_expose"),
        ("thumb", "신체 특징", "body_feature"),
        # 문신·피어싱은 원래 '표식·문신' 슬롯이었다. 표식류를 정리하고 나니 축이 하나만
        # 남아 슬롯을 유지할 이유가 없다 — 몸에 새기는 영구 장식이므로 신체 특징 뒤에 붙인다.
        ("thumb", "문신·피어싱", "marking"),
        # 명시적 노출은 별도 축 + 기본 블러(호버 해제). 태그는 제공하되 눈에 먼저 안 띄게.
        # 부상은 일시적 상태라 영구 특징(신체 특징)과 섞지 않고 별도 섹션으로 둔다.
        ("thumb", "부상·오염", "body_condition"),
        # 성인 도감. 기본 블러(호버 해제) — 다른 탭과 나란히 있으므로 그냥 노출되면 안 된다.
        ("thumb", "유두(성인)", "nsfw_nipple"),
        ("thumb", "음모(성인)", "nsfw_pubic"),
        ("thumb", "성기(성인)", "nsfw_genital"),
        ("thumb", "가슴(성인)", "nsfw_breast"),
        # (`body_nsfw` 는 뺐다 — 44개 전부 '준비 중' 이었다. 도감은 wildcards/nsfw/.)
        # 탐색기 제거: 노출·강조 42 + 신체 특징 68 + 이형 37 이 body_parts/shoulders/
        # ass/hands 를 전부 덮는다. 남겨두면 같은 태그를 두 경로로 보여주게 된다.
    ]),
    ("종족·수인", "\\u{1F9EC}", "characteristic", [
        ("thumb", "종족", "species"),
        # 남성형(`cat boy` 등 37)은 별도 축이다. 한 축에 섞어 뒀더니 여성 템플릿으로
        # 전부 생성돼 **남성만 완전 수인이거나 수염 난 노년**이 되고 여성만 케모미미가
        # 됐다(사용자 지적). 베이스 인물이 다르면 프레이밍이 아니라 축을 갈라야 한다.
        ("thumb", "종족(남성)", "species_male"),
        ("thumb", "귀", "ears"),
        ("thumb", "꼬리", "tail"),
        ("thumb", "날개", "wings"),
        ("thumb", "뿔", "horns"),
        # 이형 해부(아가미/물갈퀴/짐승 발 등) — body_expose 에 섞여 있던 것을 여기로 모았다.
        ("thumb", "이형 부위", "body_nonhuman"),
        # 탐색기 제거: 종족 220 이 legendary_creatures/kemonomimi 를 덮고,
        # 귀 98 + 꼬리 93 + 날개 41 + 뿔 32 가 animal_features 를 덮는다.
    ]),
    # (옛 '표식·기타' 슬롯은 폐지됐다. browse 전용이었고 성격이 뒤섞여 있었다 — 실측 133개
    #  중 개조 11 + 이형 해부 9 는 이형 부위로, 문신/피어싱 86 은 신체 슬롯으로 옮기고,
    #  캐릭터 메타 12 는 제외했다: 성별·연령은 캐릭터 헤더 토글이 담당하고 *focus 는 구도다.)
    #
    # ── 의상 ────────────────────────────────────────────────────────────────
    # 의상 풀 4,017개를 freq>=2000 + 제외군으로 915개 23축으로 정리했다
    # (tools/thumb_clothing_build.py 가 SSOT, 근거는 tools/CLOTHING_PLAN.md).
    # 22축(성인 제외)을 팝업 하나에 담으면 스크롤이 불가능하므로 두 슬롯으로 나눈다:
    #   의상    = 몸에 입는 것
    #   소품·장식 = 부위에 차거나 거는 것
    ("의상", "\\u{1F457}", "clothing", [
        ("thumb", "상의", "cloth_top"),
        ("thumb", "하의", "cloth_bottom"),
        ("thumb", "원피스·한벌", "cloth_dress"),
        ("thumb", "겉옷", "cloth_outer"),
        ("thumb", "전통 의상", "cloth_traditional"),
        ("thumb", "제복·코스튬", "cloth_uniform"),
        ("thumb", "수영복", "cloth_swim"),
        ("thumb", "속옷", "cloth_under"),
        ("thumb", "착의 상태", "cloth_state"),
        ("thumb", "디테일·실루엣", "cloth_detail"),
        ("thumb", "무늬·프린트", "cloth_pattern"),
        ("thumb", "스타일·용도", "cloth_style"),
        ("thumb", "노출 의상(성인)", "nsfw_exposure"),
        ("thumb", "구속·기구(성인)", "nsfw_bondage"),
        # (`cloth_nsfw` 는 뺐다 — 97개 전부 '준비 중' 이었다. 도감은 wildcards/nsfw/.)
        # 썸네일이 freq>=2000 만 덮으므로 나머지 3,100개는 탐색기가 담당한다.
        # ⚠️ 목록을 손으로 적었더니 36개 서브그룹 중 19개(259개, 팬티 75·브라 45 포함)가
        #    빠져 탐색기에서 접근 불가가 됐다. 옛 의상 슬롯은 sections 가 없어 전체가
        #    보였는데 섹션을 넣으면서 좁혀버린 것이다. 아래 _BROWSE_* 로 파생시킨다.
        # 탐색기 전용 1,239개를 분해해 보니 **1,171개(95%)가 의도적 제외분**이었다
        # (저빈도 824 · 작품/캐릭터 한정 293 · 폐기·모호 17 · 근접 중복 …). 나머지도
        # 색 조합 59(팔레트로 접근) + 관계형 메타 7 이다. 즉 탐색기는 분류에서
        # 일부러 뺀 태그를 사용자에게 다시 권하고 있었다 — 트리는 뗐다.
    ]),
    ("소품·장식", "\\u{1F452}", "clothing", [
        ("thumb", "모자", "cloth_headwear"),
        ("thumb", "머리 장식", "cloth_hairacc"),
        ("thumb", "목", "cloth_neck"),
        ("thumb", "안경·마스크", "cloth_eyewear"),
        ("thumb", "손", "cloth_handwear"),
        ("thumb", "소매", "cloth_sleeve"),
        ("thumb", "다리", "cloth_legwear"),
        ("thumb", "신발", "cloth_footwear"),
        ("thumb", "허리", "cloth_waist"),
        ("thumb", "소지품", "cloth_carried"),
        # 부위가 정해지지 않는 장식(리본·보석·체인)만 남았다. 부위별 120개는
        # 각 부위 축으로 옮겼다 — 근거는 의상 프리셋 region6 매핑.
        ("thumb", "장식", "cloth_accessory"),
        # 귀걸이·반지·팔찌는 프레이밍이 다르다(portrait). 같은 축에 두면
        # cowboy 화소로는 보이지 않아 1/3이 빈 썸네일이 된다.
        ("thumb", "작은 장신구", "cloth_small"),
        ("thumb", "갑옷", "cloth_armor"),
        # 소품 탐색기는 뗐다. 남겨 둔 근거가 "동물은 축이 아예 없어 탐색기가 유일한
        # 경로다 — 축이 생기면 뗀다" 였고, 축이 생겼다(ani_* 272개). 실측으로 이 트리에
        # 남은 동물은 8개뿐이다(other_animals 3 · objects 2 · cats 1 · 나머지 2).
        # 그리고 트리가 있으면 **검색이 트리만 거르고 끝난다**(interactivePanel 1448).
        # 즉 썸네일이 가장 많은 이 슬롯(13축 1,201칸)이 검색이 안 닿는 유일한 슬롯이었다.
    ]),
    # ── 자세 ────────────────────────────────────────────────────────────────
    # **1명으로 되는 자세만** 여기 둔다. 2명 이상이 필요한 것은 씬의 '다인원 자세'가
    # 담당한다 — 판정 근거는 이벤트 프리셋 파티션의 실측 solo 비율과 태그명의
    # own/another's 다(tools/build_pose_slots.py).
    # 축 순서는 초보자가 쓰는 순서에 맞췄다: 몸 전체 -> 팔다리 -> 손 -> 얼굴 -> 물건.
    # 목록은 손으로 적지 않는다 — 적어 뒀더니 `pose_arm_2` 가 없어진 뒤에도 남고
    # 신설 `pose_leg`/`pose_body_touch` 는 빠지고 라벨은 옛 이름("얼굴·몸에 손")
    # 그대로였다. _pose_axes.json 이 축과 라벨의 SSOT 다(_POSE_SECTIONS 참조).
    ("자세", "\\u{1F3C3}", "pose_action", _POSE_SECTIONS + [
        ("thumb", "둔부(성인)", "nsfw_butt"),
        ("thumb", "체액(성인)", "nsfw_fluid"),
        # 원래 계층 탐색기를 붙였다 — "썸네일이 freq>=100 만 덮으니 나머지는 탐색기가
        # 담당한다"는 전제였다. 전제는 맞았다(100 이상은 한 개도 새지 않았다). 그래서
        # 탐색기에만 남는 것이 무엇이냐가 문제였는데, 세어 보니 쓸 수 없는 것들이었다.
        # 그래서 트리는 뗐다 — 아는 태그는 검색으로 여전히 넣을 수 있고(검색창은
        # `thumb` 섹션만 있어도 붙는다), 19축 썸네일이 볼 만한 것은 전부 덮는다.
    ]),
]

def js(v):
    return json.dumps(v, ensure_ascii=False)

out = []
out.append("// 생성 파일 — 직접 수정하지 말 것.")
out.append("// 출처: wildcards/thumb/*.txt + _palette.json (scratchpad/gen_axes_module.py 로 재생성)")
out.append("//")
out.append("// 축 입력 방식 3종:")
out.append("//   palette : 색 스와치(직사각형). 태그 하나 선택.")
out.append("//   slider  : 서열 축(길이/가슴). 단계 선택.")
out.append("//   thumb   : 시각 패턴. 썸네일 그리드(이미지 없으면 텍스트 칩으로 폴백).")
out.append("//   browse  : 3단 계층 탐색 + 검색. 지금은 쓰는 슬롯이 없다 —")
out.append("//             썸네일이 볼 만한 것을 다 덮어 트리가 중복만 남겼다.")
out.append("")
out.append(f"export const PALETTE_SHAPE = {js(palette.get('swatch_shape','rect'))};")
out.append("")
out.append("export const PALETTES = {")
for key in ("hair_color", "eye_color", "skin_color"):
    rows = palette.get(key) or []
    out.append(f"  {key}: [")
    for d in rows:
        row = d.get("row", 1)
        out.append(f"    {{tag: {js(d['tag'])}, hex: {js(d['hex'])}, row: {row}}},")
    out.append("  ],")
out.append("};")
out.append("")
out.append("export const SLIDERS = {")
for key, d in (man.get("sliders") or {}).items():
    steps = [s["tag"] for s in d["steps"]]
    extra = f", default: {js(d['default'])}" if d.get("default") else ""
    out.append(f"  {key}: {{label: {js(d['label'])}, steps: {js(steps)}{extra}}},")
out.append("};")
out.append("")
out.append("// 썸네일 축의 태그 목록. 썸네일 파일명 = <axis>/<tag를 slug 화>.webp")
out.append("export const THUMB_TAGS = {")
# 와일드카드 폴더의 .txt 를 전부 축으로 등록한다(매니페스트에 없는 신규 파일도 자동 반영).
_FRAMING_DEFAULT = {"tail": "full", "wings": "full", "body_type": "full",
                    "body_expose": "full", "species": "upper",
                    # 의상 축 — tools/thumb_bench_init.py 의 CLOTH_BATCHES 와 맞춘다.
                    # 기본값(portrait)으로 떨어지면 벤치와 어긋나 표시가 거짓이 된다.
                    "cloth_headwear": "portrait", "cloth_hairacc": "portrait",
                    "cloth_neck": "portrait", "cloth_eyewear": "portrait",
                    "cloth_top": "upper", "cloth_sleeve": "upper",
                    "cloth_handwear": "upper",
                    "cloth_legwear": "lower", "cloth_footwear": "lower",
                    "cloth_bottom": "cowboy", "cloth_under": "cowboy",
                    "cloth_swim": "cowboy", "cloth_state": "cowboy",
                    "cloth_detail": "cowboy", "cloth_pattern": "cowboy",
                    "cloth_accessory": "cowboy", "cloth_dress": "cowboy",
                    "cloth_waist": "cowboy", "cloth_carried": "cowboy",
                    "cloth_outer": "cowboy", "cloth_traditional": "cowboy",
                    "cloth_uniform": "cowboy", "cloth_style": "cowboy",
                    "cloth_armor": "cowboy", "cloth_nsfw": "explicit"}
framings = {a["key"]: a.get("framing", "portrait") for a in man.get("axes", [])}
_axis_files = sorted(p.stem for p in SRC.glob("*.txt"))
# 성인 도감(`nsfw_*`)은 폴더가 달라 위 glob 에 안 잡힌다. 배선된 것만 뒤에서 걸러진다.
_axis_files += sorted(p.stem for p in NSFW_SRC.glob("nsfw_*.txt"))
# 슬롯이 참조하지 않는 축은 내보내지 않는다. 의상 축(cloth_*, 915개)이 분류만 끝나고
# 아직 배선되지 않았는데, 그대로 등록하면 렌더되지도 않는 태그·설명을 브라우저로 보낸다.
# 슬롯에 붙이는 순간 자동으로 포함된다.
# browse 의 sec[2] 는 축 이름이 아니라 subgroup 목록(list)이다 — 섞으면 unhashable.
_referenced = {sec[2] for _, _, _, secs in SLOTS for sec in secs if sec[0] != "browse"}
# face.txt 는 슬롯이 직접 참조하지 않는다 — face_eyes/face_parts/face_mark 로 파생되고
# PACK_AXIS 가 팩 키로 되돌린다. 빼면 그 223개의 툴팁 설명이 사라진다.
_referenced.add("face")
# 다인원 자세 축은 SLOTS 가 아니라 프론트의 SCENE_SLOTS(POSE_MULTI_SECTIONS)가 참조한다.
# 여기서 빼면 씬 슬롯이 빈 그리드를 그린다.
_referenced.update(p.stem for p in SRC.glob("pose_*_m*.txt"))
# 배경 축도 SLOTS 가 아니라 프론트의 SCENE_SLOTS(LOC_SECTIONS)가 참조한다.
# 빼면 THUMB_TAGS 에 태그가 없어 씬 슬롯이 빈 그리드를 그린다 — 다인원과 같은 함정.
_referenced.update(_rf for _kind, _lb, _rf in _LOC_SECTIONS)
_referenced.update(_rf for _s in (_OBJ_SECTIONS, _ANI_SECTIONS, _FX_SECTIONS,
                                 _VIEW_SECTIONS, _META_SECTIONS)
                   for _kind, _lb, _rf in _s)
# 성인 도감 전체. 앞 8축은 노출·부위(먼저 만든 것), 뒤 16축은 행위 도감이다.
# **순서가 곧 화면 순서다** — 무엇을 고르러 왔는지에 가까운 순으로 둔다:
#   노출·부위 -> 행위 -> 체위·인원 -> 도구·장식 -> 상태·연출
_ADULT_ORDER = [
    # 노출·부위 (기존 8축)
    "nsfw_exposure", "nsfw_breast", "nsfw_butt", "nsfw_nipple",
    "nsfw_pubic", "nsfw_genital", "nsfw_anatomy", "nsfw_fluid",
    # 행위
    "nsfw_act", "nsfw_hand", "nsfw_bodyjob", "nsfw_oral",
    "nsfw_penetration", "nsfw_cum",
    # 체위·인원·관계
    "nsfw_position", "nsfw_group", "nsfw_pairing",
    # 도구·장식·구속
    "nsfw_toy", "nsfw_bondage", "nsfw_adorn",
    # 상태·연출
    "nsfw_state", "nsfw_peek", "nsfw_fetish", "nsfw_censor",
]
# 라벨은 두 도감의 JSON 을 합친다. 손으로 적으면 도감 라벨을 바꿀 때 갈라진다.
_nsfw_label = json.loads((NSFW_SRC / "_nsfw_catalog.json").read_text(encoding="utf-8"))["label"]
_nsfw_label |= json.loads(
    (NSFW_SRC / "_nsfw_act_catalog.json").read_text(encoding="utf-8"))["label"]
# 배선 누락을 조용히 넘기지 않는다 — 이미지가 있는 축이 목록에서 빠지면 죽는다.
_wired = set(_ADULT_ORDER)
_have_img = {p.stem for p in NSFW_SRC.glob("nsfw_*.txt")
             if p.stem not in ("nsfw_heavy",) and any(
                 f"{p.stem}/{t}" in _PACK_KEYS for t in lines(p.stem))}
assert not (_have_img - _wired), f"성인 축 배선 누락: {sorted(_have_img - _wired)}"
# 성인 도감 축은 SLOTS 가 아니라 프론트의 ADULT_SECTIONS 가 참조한다.
# 빼면 THUMB_TAGS 에 태그가 없어 성인 슬롯이 빈 그리드를 그린다
# — 다인원 자세·배경에서 이미 두 번 겪은 함정이다(세 번째).
_referenced.update(_ADULT_ORDER)

_skipped_axes = [k for k in _axis_files if k not in _referenced]
_axis_files = [k for k in _axis_files if k in _referenced]
# ── 축 색 지정 태그 분리 ──────────────────────────────────────────────────
# `black headwear` 는 모자가 아니라 색이다. 그리드에 옷과 나란히 두면 `beret` 과
# 같은 종류로 보인다. 지우지는 않는다 — Danbooru 에 `black hat` 이 없어 이것이
# "검은 모자"를 말하는 유일한 방법이고, CLOTH_COMBO 에도 모자 베이스가 없다.
_COLOR_MOD = {
    "black", "white", "red", "blue", "green", "yellow", "pink", "purple", "orange",
    "brown", "grey", "gray", "silver", "gold", "beige", "aqua", "navy", "tan",
    "multicolored", "two-tone", "rainbow",
    "striped", "checkered", "plaid", "patterned",
}
# 분류 우산 — 그 자체로는 그릴 대상이 아니고 '어느 부위인가'만 말한다.
_UMBRELLA = {"headwear", "footwear", "legwear", "handwear", "neckwear", "eyewear",
             "headgear", "underwear", "outerwear", "swimwear", "sleeves"}
# `cloth_pattern` 은 제외한다. 그 축은 '무늬를 옷 전체에 건다'가 정체라
# 범위가 clothes/sleeves 인 것이 오히려 맞다.
_COLOR_SKIP_AXES = {"cloth_pattern", "fx_symbol", "fx_effect", "fx_tone"}

def _is_axis_color(tag: str) -> bool:
    w = tag.split()
    return (len(w) >= 2 and w[-1] in _UMBRELLA
            and " ".join(w[:-1]) in _COLOR_MOD)

# ── 남성 계열 격리 ─────────────────────────────────────────────────────────
# 여성 위주로 쓰는 사용자가 체형 그리드를 훑다가 중년 남성 나체를 만나는 건 기능이 아니다
# (사용자 지적). 태그는 지우지 않고 **같은 탭 안의 별도 섹션**으로 뺀다 — `species` /
# `species_male` 에서 이미 쓴 방식이다. 목록은 tools/thumb_male_tags.py 가 SSOT.
# 얼굴 축은 파생 그룹(`face_male`)에서 이미 갈랐으므로 여기서는 건드리지 않는다.
_MALE_SPLIT_SKIP = {"face"}     # 표시용이 아닌 컨테이너 축(툴팁·팩 키 용도)
_male_axes: dict[str, list[str]] = {}

def _split_male(key: str, tags: list[str]) -> list[str]:
    """`key` 에서 남성 태그를 빼 `<key>_male` 로 모으고 나머지를 돌려준다."""
    if key in _MALE_SPLIT_SKIP:
        return tags
    picked = [t for t in tags if t in MALE_ONLY]
    if not picked:
        return tags
    _male_axes[f"{key}_male"] = picked
    return [t for t in tags if t not in MALE_ONLY]

axis_colors: dict[str, list[str]] = {}
for key in _axis_files:
    tags = lines(key)
    if not tags: continue
    if key not in _COLOR_SKIP_AXES:
        picked = [t for t in tags if _is_axis_color(t)]
        if picked:
            axis_colors[key] = picked
            tags = [t for t in tags if t not in set(picked)]
    tags = _split_male(key, tags)
    out.append(f"  {key}: {js(tags)},")
    framings.setdefault(key, _FRAMING_DEFAULT.get(key, "portrait"))
# 얼굴 표시 그룹은 파일이 아니라 face.txt 에서 파생된 것이라 따로 등록한다.
for _k, _v in _groups.items():
    out.append(f"  {_k}: {js(_v)},")
    framings.setdefault(_k, "portrait")
# 파생된 남성 축. 프레이밍은 원래 축을 따른다(수염은 초상, 체형은 전신).
for _k, _v in _male_axes.items():
    out.append(f"  {_k}: {js(_v)},")
    framings.setdefault(_k, framings.get(_k[: -len("_male")], "portrait"))
out.append("};")
# 배선 양방향 검사. 한쪽만 있으면 조용히 새는 것이 이 프로젝트의 상습 결함이다 —
# 섹션만 있고 태그가 없으면 빈 그리드, 태그만 있고 섹션이 없으면 태그가 화면에서 사라진다.
_male_secs = {sec[2] for _, _, _, secs in SLOTS for sec in secs
              if sec[0] != "browse" and sec[2].endswith("_male")}
_male_secs.discard("species_male")      # 이건 파생이 아니라 실제 축 파일이다.
_male_have = set(_male_axes) | {_g for _g in _groups if _g.endswith("_male")}
assert _male_secs == _male_have, (
    f"남성 축 배선 불일치 — 섹션만: {sorted(_male_secs - _male_have)}, "
    f"태그만: {sorted(_male_have - _male_secs)}")
out.append("")
out.append("// 축 전체에 거는 색·무늬(`black headwear` 류). 그리드가 아니라 그 위 한 줄에")
out.append("// 나온다 — 옷이 아니라 '그 부위의 색'이라 옷들과 나란히 놓으면 종류를 오해한다.")
out.append("// 팩 키는 축 그대로라 썸네일도 그대로 쓸 수 있다.")
out.append(f"export const AXIS_COLOR_TAGS = {js(axis_colors)};")
out.append("")
out.append("export const THUMB_FRAMING = " + js(framings) + ";")
out.append("")
# 태그 설명(호버 툴팁용). 썸네일/팔레트/슬라이더에 등장하는 태그만 담는다.
from core.kr_tag_loader import load_kr_tag_records   # noqa: E402
_raw = load_kr_tag_records().raw
_need = set()
for _k2 in _axis_files:
    _need.update(lines(_k2))
for _k in ("hair_color", "eye_color"):
    _need.update(d["tag"] for d in (palette.get(_k) or []))
for _d in (man.get("sliders") or {}).values():
    _need.update(s["tag"] for s in _d["steps"])
_desc = {}
for _t in sorted(_need):
    _m = _raw.get(_t) or {}
    _s = str(_m.get("description") or "").strip()
    if _s:
        _desc[_t] = _s
out.append("// 호버 툴팁용 태그 설명(있는 것만).")
out.append("export const TAG_DESC = " + js(_desc) + ";")
out.append("")
out.append("// 얼굴 축의 표시용 하위 그룹(THUMB_TAGS 에도 같이 등록됨).")
out.append("export const FACE_GROUPS = " + js({**{k: len(v) for k, v in _groups.items()}, "eye_pattern": len(_eye_pattern)}) + ";")
out.append("")
out.append("// 표시 축 -> 썸네일 팩 축(생성 단위). 없으면 축 이름 그대로.")
_pack_axis = {k: "face" for k in _groups}
# 파생된 남성 축은 이미지를 원래 축의 팩 키에서 가져온다(`body_type_male/beard` 같은 키는 없다).
for _k in _male_axes:
    _base = _k[: -len("_male")]
    _pack_axis[_k] = _pack_axis.get(_base, _base)
out.append("export const PACK_AXIS = " + js(_pack_axis) + ";")
out.append("")

# ---- 민감 태그 ----
# 성인 축은 축 단위로 블러한다(아래 SENSITIVE_AXES). 그 밖의 일반 축에서 블러하는 것은
# **눈 개수가 사람과 다른 것 하나뿐이다.**
#
# 이 목록은 두 번 줄었다. 처음엔 태그 이름으로 추정해 39개였고, 서브에이전트 vision
# 실측(39장)으로 7개까지 줄었다. 그러고도 과했다 — 2026-07-30 사용자 실측:
# amputee / no hands / missing limb / emaciated / 봉합·혈흔 / 체모 계열은 실제 이미지가
# 혐오 컨텐츠가 아니었다. 블러가 오히려 "여기 뭔가 끔찍한 게 있다"는 오신호를 준다.
# 이름이 자극적인 것과 화면이 자극적인 것은 다르다 — 이름으로 판정하지 말라는 교훈이
# 같은 목록에서 두 번 나왔다.
#
# 남긴 기준: 눈이 한 개거나 두 개보다 많은 것. 얼굴 그리드를 훑을 때 유일하게
# 실제로 놀라는 지점이다. (`no eyes` 는 0개이고 vision 실측에서 평범한 초상이라 제외.)
SENSITIVE = [
    "one-eyed",           # 눈 1개
    "cyclops",            # 이마 중앙에 눈 1개
    "extra eyes",         # 2개보다 많음
    "third eye",          # 이마에 세 번째 눈
    "third eye on chest", # 가슴에 세 번째 눈
    "compound eyes",      # 낱눈 다발(곤충)
]
_thumb_all = set()
for _k3 in _axis_files:
    _thumb_all.update(lines(_k3))
for _k, _v in _groups.items():
    _thumb_all.update(_v)
# NSFW 축은 태그를 나열하지 않고 축 전체를 블러한다(항목이 늘어도 자동 적용).
# 블러 대상 태그의 출처. 축 파일은 이제 `wildcards/nsfw/` 에 있다 —
# 썸네일 축 폴더에 두면 도구가 생성 대상으로 읽는다(실측 사고 4장).
SENSITIVE_SRC = Path("wildcards/nsfw")
# 도감 8축 전부. 캐릭터 슬롯에서 다른 탭과 나란히 있으므로 기본 블러가 필요하다.
SENSITIVE_AXES = sorted(p.stem for p in SENSITIVE_SRC.glob("nsfw_*.txt")) \
                 + ["body_nsfw", "cloth_nsfw"]
_sensitive = [t for t in SENSITIVE if t in _thumb_all]
_missing_sensitive = [t for t in SENSITIVE if t not in _thumb_all]
# 남성 축으로 격리했는데도 남성기가 그려져 있는 것. 격리는 '안 보고 싶으면 안 보게' 이지
# '열었더니 성기' 를 막지는 못한다. 재생성되면 tools/thumb_male_tags.py 에서 빼라.
_sensitive += [t for t in sorted(MALE_EXPLICIT) if t in _thumb_all and t not in _sensitive]
for _ax in SENSITIVE_AXES:
    _f = SENSITIVE_SRC / f"{_ax}.txt"
    if not _f.exists():
        continue
    for _t in (l.strip() for l in _f.read_text(encoding="utf-8").splitlines()):
        if _t and _t not in _sensitive:
            _sensitive.append(_t)
out.append("// 민감 태그 — 썸네일을 블러하고 호버 시 해제한다(태그는 유지).")
out.append("export const SENSITIVE_TAGS = " + js(_sensitive) + ";")
out.append("")

# 축 규칙(도메인 지식 — 관계 데이터에 없다).
# hair_pattern: multicolored hair 는 부모 태그다. 하위 패턴(two-tone/gradient/streaked...)을 하나라도
# 고르면 자동으로 붙고 그동안 해제할 수 없다. 그리고 여러 색을 지정해야 의미가 있으므로
# 그동안 머리 색 팔레트는 다중 선택(n개)으로 바뀐다.
out.append("export const AXIS_RULES = {")
out.append("  hair_pattern: {")
out.append("    parent: \"multicolored hair\",")
out.append("    multiPalette: \"hair_color\",")
out.append("    multiOn: \"parent\",")   # 부모가 붙어 있을 때 추가 색상 노출
out.append("    parentLockedHint: \"하위 패턴이 선택돼 있어 해제할 수 없습니다. 패턴을 먼저 해제하세요.\",")
out.append("  },")
# 눈: heterochromia 는 '양쪽 눈 색이 다름'이라 multicolored eyes(한 눈 안의 다색)의 하위가 아니다.
# 그래서 부모 자동 배정은 two-tone/gradient 에만 적용하고, 추가 색상은 축의 무엇이든 고르면 나온다.
out.append("  eye_pattern: {")
out.append("    parent: \"multicolored eyes\",")
out.append("    parentFor: [\"two-tone eyes\", \"gradient eyes\"],")
out.append("    multiPalette: \"eye_color\",")
out.append("    multiOn: \"any\",")
out.append("    parentLockedHint: \"하위 패턴이 선택돼 있어 해제할 수 없습니다. 패턴을 먼저 해제하세요.\",")
out.append("  },")
# 피부: colored skin = "인간에게는 부자연스러운 색의 피부"(69k)로 이색 피부의 우산 태그다.
# 색 자체(blue skin 등 10색)는 Danbooru 에서 colored skin 의 하위이고 subgroup 이 비어 있어
# 계층 밖이라 썸네일 축에 없다 -> 팔레트로 제공한다.
# colored skin 또는 multicolored skin 이 붙어 있을 때만 팔레트를 노출하고,
# multicolored skin 일 때만 추가 색상(n개)까지 허용한다.
out.append("  skin: {")
out.append("    parent: \"colored skin\",")
out.append("    parentFor: [\"multicolored skin\"],")
out.append("    mainPalette: \"skin_color\",")
out.append("    mainOn: [\"colored skin\", \"multicolored skin\"],")
out.append("    multiPalette: \"skin_color\",")
out.append("    multiOn: \"tags\",")
out.append("    multiTags: [\"multicolored skin\"],")
out.append("    parentLockedHint: \"multicolored skin 이 선택돼 있어 해제할 수 없습니다.\",")
out.append("  },")
out.append("};")
out.append("")
out.append("export const CHAR_SLOTS = [")
for label, icon, axis, sections in SLOTS:
    out.append(f"  {{key: {js(label)}, icon: '{icon}', axis: {js(axis)}, sections: [")
    for sec in sections:
        kind, secLabel, ref = sec[0], sec[1], sec[2]
        if kind == "browse":
            out.append(f"    {{kind: {js(kind)}, label: {js(secLabel)}, subgroups: {js(ref)}}},")
        elif kind == "thumb_extra":
            # 썸네일 섹션 + 그 안(그리드 위)에 붙는 추가 색상 팔레트
            out.append(f"    {{kind: 'thumb', label: {js(secLabel)}, ref: {js(ref)}, "
                       f"extraPalette: {js(sec[3])}}},")
        elif kind == "thumb_color":
            # 썸네일 섹션 + 그리드 위에 주 색상 팔레트(조건부) + 추가 색상 팔레트(조건부)
            out.append(f"    {{kind: 'thumb', label: {js(secLabel)}, ref: {js(ref)}, "
                       f"mainPalette: {js(sec[3])}, extraPalette: {js(sec[3])}}},")
        else:
            out.append(f"    {{kind: {js(kind)}, label: {js(secLabel)}, ref: {js(ref)}}},")
    out.append("  ]},")
out.append("];")
out.append("")

# 다인원 자세는 캐릭터 슬롯이 아니라 씬의 '다인원 자세' 팝업이 쓴다. 패널에 손으로
# 적어 뒀더니 신설 `pose_leg_m` 26개와 `pose_body_touch_m` 10개가 빠져, 찍어도
# 화면에 안 나오는 상태였다. 여기서 같이 내보낸다.
# 의상 분류에서 `<색> <옷>` 을 분해해 뒀는데(`_cloth_combo.json`) 색을 고를 곳이 없어서
# `white shirt`(541,974 — DB 최다 의상 태그)에 닿는 길이 계층 탐색기뿐이었다. 조합을
# 프론트로 내보내 그리드에서 고른 옷에 색을 붙일 수 있게 한다.
# 베이스마다 **확정된 색만** 낸다 — 28색을 다 열면 `green shirt` 처럼 실측으로 확인되지
# 않은 조합을 권하게 된다. 목록에 없는 색은 슬롯 입력창에 직접 쓰면 된다.
_combo = json.loads((SRC / "_cloth_combo.json").read_text(encoding="utf-8"))
_by_base: dict[str, dict[str, str]] = {}
for _tag, _v in sorted(_combo.items()):
    _by_base.setdefault(_v["base"], {})[_v["mod"]] = _tag
out.append("// 의상 색 조합. base -> {수식어: 합쳐진 태그}. tools/build_clothing_harmony 계열이")
out.append("// 아니라 thumb_clothing_build 의 분해 결과(_cloth_combo.json)가 출처다.")
out.append("export const CLOTH_COMBO = {")
for _b, _mods in sorted(_by_base.items()):
    out.append(f"  {js(_b)}: {js(_mods)},")
out.append("};")
out.append("")
out.append("// 합쳐진 태그 -> {base, mod}. 색을 바꾸거나 뗄 때 역방향으로 쓴다.")
out.append("export const CLOTH_COMBO_REV = {")
for _tag, _v in sorted(_combo.items()):
    out.append(f"  {js(_tag)}: {js([_v['base'], _v['mod']])},")
out.append("};")
out.append("")
out.append("// 씬 슬롯 '배경' 전용. 사람이 주인공이 아니라 프레이밍 전제가 다르다 —")
out.append("// 실내는 `scenery` 를 빼야 살고 날씨는 있어야 산다(파일럿 25장).")
# 색·무늬 낱말 목록. 사전 칩에서 색 조합(`black pants`·`blue jacket`)을 **가려내
# 숨기기 위한** 것이다 — 색·무늬는 팝업 상단 팔레트에 이미 있어 두 번 낼 이유가 없다.
# 값(색)은 지금 쓰지 않지만 낱말과 함께 두면 나중에 스와치가 필요할 때 바로 쓴다.
# 여기 없는 낱말은 조합으로 보지 않는다(`holding`·`implied` 처럼 색이 아닌 접두 차단).
COLOR_SWATCH = {
    "black": "#1b1b1f", "white": "#f2f2f2", "red": "#cf2b2b", "blue": "#2b7fd4",
    "green": "#3f9d54", "yellow": "#e8c53a", "pink": "#e87fae", "purple": "#8a5cc4",
    "brown": "#7a4a24", "grey": "#8a8a90", "gray": "#8a8a90", "orange": "#e08a2e",
    "aqua": "#3fc9c9", "silver": "#c3c7cc", "gold": "#d4af37", "beige": "#d9c49a",
    "navy": "#26325c", "light blue": "#8ec7ef", "dark blue": "#1e3a6b",
    "two-tone": "linear-gradient(135deg,#f2f2f2 50%,#1b1b1f 50%)",
    "multicolored": "linear-gradient(135deg,#cf2b2b,#e8c53a,#3f9d54,#2b7fd4)",
    "striped": "repeating-linear-gradient(45deg,#f2f2f2 0 3px,#2b7fd4 3px 6px)",
    "checkered": "repeating-conic-gradient(#f2f2f2 0 25%,#1b1b1f 0 50%) 0/6px 6px",
    "plaid": "repeating-linear-gradient(0deg,#8a3b3b 0 3px,#d9c49a 3px 6px)",
    "polka dot": "radial-gradient(#1b1b1f 30%,#f2f2f2 31%) 0/5px 5px",
}
out.append("// 색·무늬 낱말 -> 스와치 색. 사전 칩에서 색 조합을 가려내 숨기는 데 쓴다 —")
out.append("// 색·무늬는 팝업 상단 팔레트에 이미 있어 두 번 낼 이유가 없다.")
out.append("// 여기 없는 낱말은 조합으로 보지 않는다(`holding`·`implied` 같은 접두 차단).")
out.append("export const COLOR_SWATCH = {")
for _w, _c in COLOR_SWATCH.items():
    out.append(f"  {js(_w)}: {js(_c)},")
out.append("};")
out.append("")
_VIEW_GLOBAL = json.loads((SRC / "_view_axes.json").read_text(encoding="utf-8")).get("global", [])
out.append("// 이미지 전체에만 걸리는 구도 태그. 판정 기준: **한 이미지 안에서 두 캐릭터가**")
out.append("// **서로 다른 값을 가질 수 있는가.** `from behind` 는 가능(캐릭터별),")
out.append("// `isometric`·`female pov`·`multiple views` 는 불가(캔버스·카메라가 하나다).")
out.append("// 캐릭터 슬롯은 이것을 빼고 보여준다. 씬 슬롯은 전부 보여준다 — 캐릭터별")
out.append("// 태그도 이미지 전체에 걸 수 있기 때문이다(반대는 성립하지 않는다).")
out.append("export const VIEW_GLOBAL_TAGS = [")
for _t in _VIEW_GLOBAL:
    out.append(f"  {js(_t)},")
out.append("];")
out.append("")
# 대상 시선의 한글 라벨. 목록 자체는 `_gaze_targets.txt` 가 SSOT 다 —
# 여기에 없는 태그가 그 파일에 있으면 빌드가 실패한다(조용히 빠지면 영영 안 보인다).
# 성인 시선(`looking at genitalia` 등)은 넣지 않는다 — 성인은 별도 UI 소관이다.
GAZE_LABEL = {
    "looking at viewer": "관객(카메라)을 봄",
    "looking at another": "다른 사람을 봄",
    "looking at partner": "상대를 봄",
    "looking down at viewer": "관객을 내려다봄",
    "looking up at viewer": "관객을 올려다봄",
    "looking back at another": "뒤돌아 다른 사람을 봄",
    "looking back at partner": "뒤돌아 상대를 봄",
    "looking down at another": "다른 사람을 내려다봄",
    "looking up at another": "다른 사람을 올려다봄",
    "looking down at partner": "상대를 내려다봄",
    "looking up at partner": "상대를 올려다봄",
    "looking down at self": "자기 몸을 내려다봄",
    "looking back at self": "뒤돌아 자기를 봄",
    "looking at belly": "배를 봄",
    "looking at own belly": "자기 배를 봄",
    "sideways glance": "곁눈질",
}
_GAZE_SRC = SRC / "_gaze_targets.txt"
_GAZE = []
if _GAZE_SRC.exists():
    for _line in _GAZE_SRC.read_text(encoding="utf-8").splitlines():
        if not _line.strip() or _line.startswith("#"):
            continue
        _tag, _, _n = _line.partition("\t")
        _tag = _tag.strip()
        if _tag in GAZE_LABEL:
            _GAZE.append((_tag, GAZE_LABEL[_tag], int(_n or 0)))
out.append("// 대상 시선 — 썸네일로 구분되지 않아 그리드 대신 다중 선택 목록으로 준다.")
out.append("// `looking at another` 와 `looking at partner` 는 상대가 프레임에 없으면")
out.append("// 같아 보인다. 캐릭터 프롬프트에 들어간다(누구의 시선인지가 붙어야 산다).")
out.append("// 성인 시선은 여기 없다 — 별도 UI 소관이다.")
out.append("export const GAZE_TARGETS = [")
for _t, _lb, _n in _GAZE:
    out.append(f"  {{tag: {js(_t)}, label: {js(_lb)}, n: {_n}}},")
out.append("];")
out.append("")
out.append("export const LOC_SECTIONS = [")
for _k, _lb, _rf in _LOC_SECTIONS:
    out.append(f"  {{kind: 'thumb', label: {js(_lb)}, ref: {js(_rf)}}},")
out.append("];")
out.append("")
for _name, _secs, _ko in (("OBJ_SECTIONS", _OBJ_SECTIONS, "사물"),
                          ("ANI_SECTIONS", _ANI_SECTIONS, "동물"),
                          ("FX_SECTIONS", _FX_SECTIONS, "효과·기호"),
                          ("VIEW_SECTIONS", _VIEW_SECTIONS, "구도"),
                          ("META_SECTIONS", _META_SECTIONS, "기타·텍스트")):
    out.append(f"// 씬 슬롯 '{_ko}' 전용.")
    out.append(f"export const {_name} = [")
    for _k, _lb, _rf in _secs:
        out.append(f"  {{kind: 'thumb', label: {js(_lb)}, ref: {js(_rf)}}},")
    out.append("];")
    out.append("")

out.append("// 씬 슬롯 '다인원 자세' 전용. 2명 이상이 있어야 성립하는 축들이다.")
out.append(f"// 성인 도감 {len(_ADULT_ORDER)}축. 씬 슬롯('성인')이 쓴다 — 여기선 전부 성인이라")
out.append("// `(성인)` 을 붙이지 않는다(슬롯 이름을 그만큼 반복하는 꼴이다).")
out.append("export const ADULT_SECTIONS = [")
for _ax in _ADULT_ORDER:
    if lines(_ax):
        out.append(f"  {{kind: 'thumb', label: {js(_nsfw_label.get(_ax, _ax))}, ref: {js(_ax)}}},")
# `nsfw_heavy` 는 **썸네일을 만들지 않는다.** 금기와 평상 사이의 태그라 이미지를
# 리포로 배포하지 않기로 했다(사용자 결정 2026-07-30). 목록으로만 닿게 하는
# `kind: 'gloss'` 섹션으로 낸다 — 선택 동작은 썸네일 셀과 같다.
_HEAVY = [l.strip() for l in (NSFW_SRC / "nsfw_heavy.txt").read_text(encoding="utf-8").splitlines()
          if l.strip() and not l.startswith("#")]
if _HEAVY:
    out.append("  {kind: 'gloss', label: \"수요 태그(이미지 없음)\", ref: \"nsfw_heavy\","
               " note: \"썸네일을 만들지 않는 분류입니다. 태그와 설명만 제공합니다.\"},")
out.append("];")
out.append("")
out.append("// 이미지 없이 `태그 : 설명` 으로만 제공하는 축. `kind: 'gloss'` 섹션이 읽는다.")
out.append("export const GLOSS_TAGS = " + js({
    "nsfw_heavy": [[t, str((_raw.get(t) or {}).get("description") or "").strip()] for t in _HEAVY],
}) + ";")
out.append("")
out.append("export const POSE_MULTI_SECTIONS = [")
for _ax in _POSE_MULTI:
    out.append(f"  {{kind: 'thumb', label: {js(_pose_axes['label'][_ax])}, ref: {js(_ax)}}},")
out.append("];")
out.append("")

DST.write_text("\n".join(out) + "\n", encoding="utf-8")
print(f"생성: {DST}  ({len(out)} 줄)")
print(f"  팔레트: hair {len(palette['hair_color'])} / eye {len(palette['eye_color'])}")
print(f"  슬라이더: {list((man.get('sliders') or {}).keys())}")
tt = {a['key']: len(lines(a['key'])) for a in man.get('axes',[]) if lines(a['key'])}
print(f"  썸네일 축 {len(tt)}개 / 총 {sum(tt.values())}장: {tt}")
print(f"  슬롯 {len(SLOTS)}개: {[s[0] for s in SLOTS]}")
if _skipped_axes:
    _n = sum(len(lines(k)) for k in _skipped_axes)
    print(f"  미배선 축 {len(_skipped_axes)}개 / {_n}장 제외: {_skipped_axes}")
print(f"  민감 태그 {len(_sensitive)}개 블러" + (f" / 목록에 없어 제외: {_missing_sensitive}" if _missing_sensitive else ""))
