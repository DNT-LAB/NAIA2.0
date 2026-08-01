# -*- coding: utf-8 -*-
"""wildcards/thumb/_bench.json 생성 — 축별 고정 베이스 + NAI 파라미터의 SSOT.

출처는 내 추측이 아니라 '사용자가 실제로 승인한 이미지의 메타데이터'다.
20260725_103742 의 각 폴더에서 프롬프트/파라미터를 뽑아 그대로 옮겼고,
아직 생성하지 않은 축(뿔/상태/귀/꼬리/날개/종족/이형)은 성격이 가장 가까운
기존 베이스를 재사용한다.

사용자 철학(관찰된 것)
  - young female 고정. mature female 은 네거티브에 명시적으로 넣어 회피한다.
  - nude + safe + rating:general 조합: 옷이 특징을 가리지 않게 하면서 등급은 안전하게.
  - bare shoulders: 목/어깨선을 열어 머리·귀·뿔이 옷에 묻히지 않게 한다.
  - head out of frame: 부위/체형 축은 얼굴을 버리고 몸통에 화소를 몰아준다.
  - 아티스트 0.38 저가중 + watercolor 0.4: 라인이 얇고 배경이 흰 균일한 톤.


## ⚠ import 만 해도 파일을 덮어쓴다

이 모듈은 함수가 아니라 **모듈 최상위에서 실행**된다. `import tools.thumb_bench_init`
한 줄로 `_bench.json` 이 재생성되고, **손으로 추가한 배치가 조용히 사라진다**
(2026-08-02 실측: job·job_male·event·mech·view_*·meta_* 등 15개가 날아갔다).
검증 목적으로 import 하지 마라 — `python -c "import ..."` 도 마찬가지다.
"""
import json
import re
from pathlib import Path

OUT = Path("wildcards/thumb/_bench.json")

ARTIST = "0.38::kanzarin, nns (sobchan), torino aqua, ixy, epi zero ::"
QUALITY = ("0.4:: watercolor (medium), no lineart ::, -1:: thick outlines, ai-generated ::, "
           "best quality, masterpiece, very absurdres, year 2024, year 2025, "
           "-1::widescreen, blurry ::")

# 남성 배치 네거티브 — 여성 톤 제어 토큰을 빼고 `furry male, manly` 를 넣는다(사용자 지시).
# 프롬프트 쪽 `-1::` 상쇄로는 반대로 넘어갔다(파일럿 8/8이 소녀가 됐다). 완전 수인과
# '아저씨' 는 네거티브로 잡는 편이 확실하다.
#   빼는 것: muscular female / {adolescent, mature female} / oldest female
#            -> 전부 '어린 여성 톤' 을 만들려고 넣은 것이라 남성 베이스에서는 방해만 된다.
#   넣는 것: furry male(머리까지 짐승) / manly(수염 난 노년)
# **빼는 것은 `muscular female` 하나뿐이다.** 처음엔 여성 토큰을 전부 뺐는데
# `{adolescent, mature female}` 가 남성 배치에서도 **유일한 나이 제어**였다 —
# 빼자 넷 다 수염 난 노년이 됐다(파일럿 4/4). 여성 토큰이라도 톤을 잡아 주므로 둔다.
MALE_NEG_DROP = ("muscular female",)


def male_negative(neg: str) -> str:
    out = neg
    for t in MALE_NEG_DROP:
        out = out.replace(t + ", ", "").replace(", " + t, "").replace(t, "")
    # `manly` 는 뺐다. 사용자 제안대로 넣어 봤더니 남성성 자체를 눌러 37장 중
    # 대부분이 소녀로 읽혔다(실측). 수인만 누르는 `furry male` 은 남긴다.
    return "furry male, " + out


# 승인된 이미지에서 그대로 뽑은 네거티브. mature female / adolescent / oldest female /
# muscular female 을 명시적으로 눌러 '어린 여성' 톤을 유지한다.
NEGATIVE = (
    "blurry, lowres, upscaled, artistic error, film grain, scan artifacts, worst quality, "
    "bad quality, jpeg artifacts, very displeasing, chromatic aberration, halftone, "
    "multiple views, logo, too many watermarks, negative space, blank page, "
    "{{{ai-generated,watermarks, text, abs, muscular female, Watermark, artist logo, "
    "patreon username, patreon logo }}}, {bad}, error, fewer, extra, missing, watermark, "
    "unfinished, displeasing, signature, extra digits, username, scan, [abstract], "
    "chromatic, bad anatomy, bad hands, low quality, normal quality, mutation, mutated, "
    "extra limb, poorly drawn hands, malformed hands, long neck, long body, extra fingers, "
    "mosaic, bad faces, bad face, bad eyes, bad feet, extra toes, western comics (style), "
    "anime screencap, anime coloring, "
    "[[[[[[bkub, chabo (fuketsudan), fuzukikai, beanis, pixel art, tsuzuri (tu-san house)]]]]]], "
    " limited palette, {adolescent, mature female}, thick outlines, blender (medium), "
    "[[[[hara (harayutaka), naxius noxy,queasy s, ringsel]]]], dorachan r, upscaled, "
    "[[[dagasi, agwing86]]], oldest female, simply drawn genitalia, unusual genitalia, text"
)

NEGATIVE_MALE = male_negative(NEGATIVE)

# 승인 이미지 메타데이터 실측값. steps/해상도는 도구가 한 번 더 상한을 강제한다.
PARAMETERS = {
    "n_samples": 1, "sampler": "k_euler_ancestral", "steps": 28, "scale": 5.4,
    "cfg_rescale": 0.28, "noise_schedule": "karras", "width": 1024, "height": 1024,
    "sm": False, "sm_dyn": False, "skip_cfg_above_sigma": 58.0,
    "params_version": 3, "legacy": False, "legacy_v3_extend": False, "legacy_uc": False,
    "add_original_image": True, "autoSmea": True, "prefer_brownian": True,
    "ucPreset": 0, "use_coords": False, "deliberate_euler_ancestral_bug": True,
    "controlnet_strength": 1, "dynamic_thresholding": False, "uncond_scale": 1.0,
}

# 프레이밍 프리셋 — <<VARY>> 는 도구가 "가중치::태그 ::" 로 치환한다.
#   HEAD  머리/얼굴/귀/뿔: 초상 + 맨어깨 + nude/safe (옷·머리에 가리지 않게)
#   TORSO 부위/체형/특징: cowboy shot + head out of frame (몸통에 화소 집중)
#   UPPER 상태/종족/피부: 상반신 (얼굴과 몸통이 같이 필요)
#   BACK  꼬리/날개: 뒤에서 — 부속물이 등/허리에 붙어 있어 정면에선 가려진다
HEAD = (f"1girl, {ARTIST}, young female, solo, front view, portrait, <<VARY>>, "
        f"bare shoulders, close-up, looking at viewer, nude, safe, rating:general, "
        f"white background, {QUALITY}")
TORSO = (f"1girl, {ARTIST}, young female, solo, front view, cowboy shot, <<VARY>>, "
         f"head out of frame, close-up, rating:general, white background, {QUALITY}")

# ── 성인 축 전용 베이스 ────────────────────────────────────────────────────
# 사용자 우려는 프롬프트가 아니라 **배포되는 이미지**다 — 어린 외형의 성인 이미지가
# GitHub 로 나가는 것(한국에서 불법). SFW 축은 rating:general + safe 라 무관하므로
# 그쪽 `young female` 은 그대로 두고, 성인 경로에만 성인 베이스를 못 박는다.
#
#   mature female   연령을 만드는 유일한 태그(실측: 빼거나 가슴으로 대체하면 안 움직인다)
#   medium breasts  연령이 아니라 **일관성** 담당(축 내 실루엣 고정)
#   faceless female 신원을 지운다(3/3). `head out of frame` 단독은 불안정해 함께 건다
#   close-up        사용자 사양 — "작은 썸네일 상자 안에서 무슨 행위인지만 알면 충분".
#                   프레이밍이 정보를 깎는 게 아니라 필요한 정보만 남긴다.
_ADULT_WHO = "mature female, medium breasts"
_ADULT_CONCEAL = "faceless female, head out of frame, close-up"

# 등급 2단계(사용자 사양).
#   노골적 — `-1:: rating:general ::` 로 general 을 직접 밀어낸다. 맥락 태그만으로는
#            NAI 가 안전한 쪽으로 되돌아간다(배경 축에서 배운 것과 같은 성질).
#   그 외  — questionable. 대부분이 여기 들어간다.
_RATING_EXPLICIT = "nsfw, rating:explicit, -1:: rating:general ::"
_RATING_QUEST = "rating:questionable"


def adult_base(rating: str) -> str:
    return (f"1girl, {ARTIST}, {_ADULT_WHO}, solo, front view, <<VARY>>, "
            f"{_ADULT_CONCEAL}, {rating}, white background, {QUALITY}")


# 네거티브에서 `mature female` 을 빼야 한다 — 안 빼면 포지티브와 정면으로 싸운다.
# `adolescent` 는 남긴다(밀어내는 쪽이라 방향이 맞다).
NEGATIVE_ADULT = NEGATIVE.replace("{adolescent, mature female}", "{adolescent}")
# 노골적 쪽은 `safe` 를 네거티브에 넣는다(사용자 사양).
NEGATIVE_EXPLICIT = "safe, " + NEGATIVE_ADULT

# 도감 분류 -> 등급. 목록 파일(wildcards/nsfw/<이름>.txt)과 배치 이름이 1:1 이다.
ADULT_BATCHES = {
    # 노골적 — 그림 자체가 해부·체액이다
    "nsfw_genital": "explicit",   # 43
    "nsfw_fluid":   "explicit",   # 23
    "nsfw_nipple":  "explicit",   # 18
    "nsfw_pubic":   "explicit",   # 9
    # 그 외 — 무슨 행위/무슨 옷인지만 보이면 된다
    "nsfw_exposure": "quest",     # 76
    "nsfw_breast":   "quest",     # 48
    "nsfw_butt":     "quest",     # 18
    "nsfw_bondage":  "quest",     # 3
}

# ── sensitive 등급 — 관계·종족은 옷 입은 그림으로 성립한다 ──────────────────
# `nsfw_pairing` 31개는 대부분 **행위가 아니라 라벨**이다. `yuri` 는 여성 커플이고
# `bara` 는 장르명이며 `tentacles` 는 무척추동물의 기관이다. 정의가 성인 도감에
# 있다고 해서 그림까지 성적일 이유가 없다(사용자 요청 2026-07-29).
#
# 연령 요구는 유지한다 — 등급이 낮아도 어린 외형으로 관계를 그리지 않는다.
# 은닉(faceless)은 뺀다. 노출이 없어 가릴 것이 없고, 커플은 얼굴이 보여야 읽힌다.
_RATING_SENSITIVE = "rating:sensitive"


def pair_base(who: str, extra: str = "") -> str:
    return (f"{who}, {ARTIST}, upper body, <<VARY>>, "
            f"looking at viewer, {extra}{_RATING_SENSITIVE}, white background, {QUALITY}")


# **성별을 양쪽 다 박으면 안 된다.** 첫 시도에서 `mature female, mature male` 하나로
# 묶었더니 `yuri` 에 남자가, `yaoi` 에 여자가 붙어 태그와 정면으로 싸웠다(dry-run 실측).
# 커플 종류가 곧 배치다.
#
# **이 넷은 `nsfw_run.py` 의 ORDER 에 없다.** 축(`nsfw_pairing`) 하나를 커플 종류로
# 4분할한 것이라 "배치 이름 = 목록 파일 이름" 규칙이 성립하지 않는다(그 규칙이
# `nsfw_run.pending()` 의 전제다). 그래서 러너를 거치지 않고 `thumb_bench.py` 에
# 배치 이름을 직접 줘서 돌렸고, `_todo` 는 그때 손으로 만들었다 —
# 2026-07-29 에 15장을 그렇게 생성해 팩에 반영했다(완료).
# 다시 돌릴 일이 생기면 같은 방법을 쓴다:
#     python tools/nsfw_event_anchor.py nsfw_pairing   # 앵커를 보고 커플 종류를 나눈 뒤
#     (_todo/nsfw_pair_<종류>.txt 에 태그를 적고)
#     python tools/thumb_bench.py nsfw_pair_het --out <폴더>
# Codex 리뷰 2026-07-30 이 "러너로 도달 불가"를 지적했는데, 도달 불가가 아니라
# **의도적으로 러너 밖**이다. 그 사실이 어디에도 안 적혀 있던 것이 결함이었다.
SENSITIVE_BATCHES = {
    # 남녀·이종 — 관계 자체가 두 성을 요구한다
    "nsfw_pair_het": (pair_base("1girl, 1boy, mature female, mature male", "couple, "),
                      2.5, "cowboy"),
    # 여성 커플
    # `yuri` 를 베이스에 넣지 않는다 — `implied yuri`(암시)와 정면으로 싸운다.
    "nsfw_pair_f":   (pair_base("2girls, mature female", "couple, "), 2.5, "cowboy"),
    # 남성 커플
    "nsfw_pair_m":   (pair_base("2boys, mature male", "couple, "), 2.5, "cowboy"),
    # 촉수·인외 부속 — 1인이면 성립한다
    "nsfw_pair_solo": (pair_base("1girl, mature female", ""), 2.5, "cowboy"),
}
# `pose_nsfw_face`(3)는 얼굴이 있어야 성립하므로 자동화하지 않는다 — 은닉과 모순된다.

# ── 연령 신호: 가슴 태그로 대체 가능한가 (2026-07-28 실측 12장) ───────────
# 사용자 제안: `mature female` 대신 `adult female` + `medium breasts`(최대 large).
#   `adult female` — **freq 0. 데이터에 없는 태그다.** 써도 아무 일도 안 일어난다.
#   `medium breasts`(556,726) / `large breasts`(958,454) — 실재하지만 **연령을 안 잡는다**:
#     X2 medium 만        -> 가슴만 줄고 몸틀은 오히려 더 어려 보인다
#     X3 large 만         -> 가슴은 커지는데 어깨·허리 비율은 어린 채다
#                            (= '어린 몸틀 + 큰 가슴' — 피하려던 조합에 더 가깝다)
#     X4 mature + medium  -> X1(mature 단독)과 사실상 동일. mature 가 지배한다
# 결론: 연령을 만드는 것은 **몸틀**이고 그것을 움직이는 태그는 `mature female` 뿐이다.
# 가슴 태그는 연령 제어가 아니라 **일관성 제어**로는 쓸 만하다(축 전체 가슴 크기 고정).
# ── 신원 은닉: 무엇이 실제로 듣는가 (2026-07-28 실측 9장) ────────────────
# 사용자 질문: "캐릭터 외모 안 보이게 할 방법이 없을까요."
#   `head out of frame`(12,662) — 머리를 자른다. 다만 **불안정하다**: 몸통 태그에서는
#     모델이 머리를 다시 넣는다(3장 중 2장이 턱·머리카락이 남았다).
#   `faceless female`(4,955) — 머리는 두고 **이목구비를 지운다**. 3/3 성공.
#     신원을 지우는 쪽은 이것이다.
#   `mature female` — 얼굴과 무관하게 **몸이 성인으로** 바뀐다. 연령 신호는 몸이 낸다.
# 즉 얼굴을 가려도 연령은 몸이 말하므로, 둘은 대체가 아니라 **함께** 써야 한다.
# 성인 축 레시피는 wildcards/nsfw/_DEFERRED_body_nsfw.md 에 적어 뒀다(사용자 직접 실행).
# PERSONA 성격·유형: 의상·표정·머리를 **고정하지 않는다**. 그 셋이 동시에 바뀌는 것이
# 유형의 정체라, 하나라도 묶으면 태그가 표현할 통로를 잃는다.
PERSONA = (f"1girl, {ARTIST}, young female, solo, front view, cowboy shot, <<VARY>>, "
           f"looking at viewer, rating:general, white background, simple background, "
           f"{QUALITY}")
UPPER = (f"1girl, {ARTIST}, young female, solo, front view, upper body, <<VARY>>, "
         f"looking at viewer, bare shoulders, nude, safe, rating:general, "
         f"white background, {QUALITY}")
# 꼬리는 허리 아래에 붙어 있어 upper body 로는 프레임 하단에 걸린다(파일럿 실측:
# tail/cat tail 이 잘렸다). cowboy shot + tail raised 로 꼬리를 위로 들어 화면에 넣는다.
TAILV = (f"1girl, {ARTIST}, young female, solo, from behind, cowboy shot, <<VARY>>, "
         f"tail raised, bare shoulders, nude, safe, rating:general, "
         f"white background, {QUALITY}")
# 날개는 접혀 있으면 종류를 구분할 수 없다(파일럿 실측: 3장 모두 등에 접힌 채 작게 나왔다).
# spread wings 로 펼쳐 형태를 드러낸다.
WINGV = (f"1girl, {ARTIST}, young female, solo, from behind, upper body, <<VARY>>, "
         f"spread wings, bare shoulders, nude, safe, rating:general, "
         f"white background, {QUALITY}")
# nude + safe 를 빠뜨렸다가 원피스를 입고 나와 발·다리 특징(발굽/새 다리/물갈퀴)이
# 전부 가려졌다(실측 13장). 사용자 원칙 그대로 — 옷이 필수 요소를 가리면 안 된다.
FULL = (f"1girl, {ARTIST}, young female, solo, front view, full body, standing, <<VARY>>, "
        f"nude, safe, rating:general, white background, {QUALITY}")

# ── 연령 톤: `young female` 만 빼도 충분한가 (2026-07-28 실측 12장) ──────────
# 답은 **아니오**다. 파일럿 4종 × 3태그로 쟀다:
#   V1 현재                                          -> 어린 톤
#   V2 `young female` 만 제거                        -> **V1 과 사실상 동일**
#   V3 + 네거티브의 mature female / oldest female 제거 -> V2 와 사실상 동일
#   V4 포지티브를 `mature female` 로 교체             -> **명확한 성인**
# 즉 이 아티스트 세트 + `1girl` 의 기본값이 이미 어린 쪽이라, 빼는 것으로는 안 움직인다.
# 성인으로 옮기려면 **포지티브로 그렇게 말해야** 한다.
# 결론: 성인 인접 축을 만들 일이 생기면 `mature female` 베이스를 따로 둔다.
# 기존 SFW 축(9,195장)은 `young female` 로 만들어졌고 전부 rating:general + safe 다.

# ── 배경(location) ──────────────────────────────────────────────────────────
# 파일럿 25장의 결론: **`scenery` 는 실내를 죽이고 날씨를 살린다.**
#   classroom + scenery -> 하늘 그림  /  scenery 없이 -> 완벽한 교실 내부
#   snowing  + scenery -> 설산       /  scenery 없이 -> 눈사람(개념이 틀림)
# 그리고 아티스트 세트는 인물 일러스트레이터라 풍경에서 하늘·구름이 화면을 먹는다.
# `wide shot` 은 웅장한 원경으로 끌어당긴다(forest/snowing 이 둘 다 설산).
# -> 배경 축에서는 아티스트와 wide shot 을 빼고, scenery 를 축별로 켠다.
SCENERY = (f"no humans, scenery, <<VARY>>, rating:general, {QUALITY}")
# 작은 사물(railing/fence/lamppost/door)은 화면을 못 채워 NAI 가 나머지를 거대한
# 뭉게구름으로 메운다(실측: loc_place 60장 중 22장). 실내의 음식 정물과 같은 현상.
# 장소 축에는 하늘 태그가 없으므로(loc_sky 로 분리) 하늘을 직접 눌러도 안전하다.
SCENERY_OBJ = (f"no humans, scenery, <<VARY>>, "
               f"-1:: sky, cloud, cumulonimbus cloud, food, plate, cake ::, "
               f"rating:general, {QUALITY}")
INTERIOR = (f"no humans, scenery, indoors, <<VARY>>, "
            f"-1:: food, plate, still life, cake, sky, cloud ::, "
            f"rating:general, {QUALITY}")
# 실내 템플릿은 세 번 고쳤다. `no humans` 만 두면 NAI 가 빈 화면을 못 견디고 **음식
# 정물**을 채운다 — 실측으로 40장 중 12장이 접시 그림이었다(wooden floor/tiles/
# kitchen/floor/brick floor/restaurant/cafe...). `indoors` 를 더해도 안 되고
# `wide shot` 도 안 됐다. `-1:: food, plate, still life, cake ::` 로 직접 상쇄해야 멎는다.
# `scenery` 를 다시 넣은 이유는 표면 태그(wooden floor)를 "그 바닥을 가진 공간"으로
# 끌어올리기 위해서다 — library/locker room 이 선 그림에서 실제 공간으로 바뀌었다.
# 그런데 `scenery` 를 넣자 이번엔 **하늘**이 들어왔다(40장 중 14장). 음식을 눌렀더니
# 구름으로 바뀐 것이다 — 빈 공간을 무엇으로 채우느냐의 문제라 **둘 다 눌러야** 한다.
# 이것이 배경 섹션의 핵심 교훈이다: 태그가 화면을 못 채우면 NAI 는 자기 기본값으로
# 메우고, 그 기본값은 맥락마다 다르다(실내=음식 정물, 실외=뭉게구름).

# 배경 '처리'(white/gradient background, *theme)는 반대로 **주체가 필요하다** —
# 무엇 뒤에 있는지를 말하는 태그라 인물 없이는 의미가 없다. 여기선 아티스트를 쓴다.
BACKDR = (f"1girl, {ARTIST}, young female, solo, front view, upper body, <<VARY>>, "
          f"looking at viewer, white shirt, rating:general, {QUALITY}")


# ── 사물 / 동물 / 효과 ──────────────────────────────────────────────────────
# 사물은 주체다 — 흰 배경에 물건 하나(특징 슬롯 방식). 배경 섹션과 반대 상황이다.
# 다만 같은 교훈이 적용된다: 화면을 못 채우면 기본값이 들어온다. 사물 축은 하늘·정물
# 둘 다 눌러야 하는데, **음식 축만은 예외**다(음식이 주제인데 음식을 누를 수 없다).
OBJTPL = (f"no humans, <<VARY>>, simple background, white background, "
          f"-1:: sky, cloud, food, plate, cake ::, rating:general, {QUALITY}")
FOODTPL = (f"no humans, <<VARY>>, simple background, white background, "
           f"-1:: sky, cloud ::, rating:general, {QUALITY}")
# 가구는 방 맥락이 있어야 크기가 읽힌다. 탈것은 실외.
ROOMTPL = (f"no humans, indoors, <<VARY>>, "
           f"-1:: food, plate, cake, sky, cloud ::, rating:general, {QUALITY}")
VEHTPL = (f"no humans, <<VARY>>, simple background, "
          f"-1:: food, plate, cake ::, rating:general, {QUALITY}")
# 동물은 흰 배경 단독. 상호작용(animal on head)은 자세 슬롯 소속이다.
ANITPL = (f"no humans, <<VARY>>, simple background, white background, "
          f"-1:: food, plate, cake, sky, cloud ::, rating:general, {QUALITY}")
# 효과·기호·색조는 **주체가 있어야 보인다**. `monochrome` 을 빈 화면에 걸면
# 흑백 아무것도 아닌 그림이 된다 — 배경 처리 축과 같은 성격이다.
FXTPL = (f"1girl, {ARTIST}, young female, solo, front view, upper body, <<VARY>>, "
         f"looking at viewer, white shirt, rating:general, {QUALITY}")


def male(tpl: str) -> str:
    """남성 배치 — 1girl/young female 을 바꾼다. 이것만 바꿔야 나머지 톤이 유지된다."""
    return tpl.replace("1girl, ", "1boy, ", 1).replace("young female", "mature male", 1)


# 남성 종족 전용. 여섯 번 재서 남은 조합이다(파일럿 30장).
#   · `1boy, mature male, male focus` — `young male` 은 네거티브의 `{adolescent}` 와
#     부딪혀 8/8 이 소녀가 됐다. 성인 남성으로 잡는다.
#   · `animal ears` 명시 — 없으면 `wolf boy` 가 귀를 통째로 잃었다.
#   · `-1:: furry ... ::` — 완전 수인(머리까지 짐승)은 프롬프트 상쇄만 듣는다.
#     네거티브의 `furry male` 만으로는 4/4 가 사자·늑대 머리 그대로였다.
#   · `-1:: beard, facial hair, old ::` — 이게 없으면 5/5 가 수염 난 중년이 된다.
#     `mature male` 은 나이를 위로 끌기 때문이다.
#   · 네거티브에서 `manly` 는 **뺐다**. 사용자 제안대로 넣었더니 남성성 자체를 눌러
#     37장 대부분이 소녀로 읽혔다(전량 실측). `furry male` 만 남긴다.
_NOFUR = "-1:: furry, furry male, snout, animal nose, body fur ::"
MALE_SPECIES = (f"1boy, {ARTIST}, mature male, male focus, solo, front view, upper body, "
                f"<<VARY>>, animal ears, looking at viewer, bare shoulders, nude, safe, "
                f"{_NOFUR}, -1:: beard, facial hair, old ::, "
                f"rating:general, white background, {QUALITY}")

BATCHES = {
    # 이미 승인된 레시피(메타데이터 실측)
    "hair_style":        (HEAD, 2.5, "portrait"),
    "hair_style_male":   (male(HEAD), 2.5, "portrait"),
    "bangs":             (HEAD, 2.0, "portrait"),
    "eye_pattern":       (HEAD, 2.0, "portrait"),
    "face_male":         (male(HEAD), 2.0, "portrait"),
    "body_feature":      (TORSO, 2.5, "cowboy"),
    "body_feature_male": (male(TORSO), 2.5, "cowboy"),
    # 신규 축 — 성격이 가장 가까운 베이스를 재사용
    "horns":             (HEAD, 2.5, "portrait"),   # 뿔은 머리에 난다
    "ears":              (HEAD, 2.5, "portrait"),   # 귀도 머리
    # 상태는 홍조/눈물/침/땀 = 얼굴 현상이 대부분이다. upper body 는 얼굴이 작아
    # 판별이 안 됐다(파일럿 실측: blush 가 거의 안 보였다) -> portrait.
    # 몸통·사지 상태(붕대/멍/더러운 발)는 state_body 로 쪼갠다.
    "state":             (HEAD, 2.5, "portrait"),
    "state_body":        (TORSO, 2.5, "cowboy"),
    "species":           (UPPER, 2.0, "upper"),     # 케모미미는 귀+얼굴+어깨
    # 남성 종족 36개는 여성 배치(`species`)에 섞여 여성 템플릿으로 나갔다. 결과가
    # 두 갈래로 깨졌다 — `wolf/tiger/lion boy` 는 **머리까지 짐승**(완전 수인)이고
    # `cat/dragon/fish boy` 는 **수염 난 노년 남성**이 됐다. 여성 쪽은 전부 케모미미라
    # 같은 축에 두 종류가 섞여 보인다(사용자 지적).
    #   · `mature male` 만으로는 나이가 안 잡힌다 -> `young male`(56,921) 로 바꾼다.
    #     여성의 `young female` 과 대응하는 태그다.
    #   · 완전 수인은 `-1::` 로 직접 상쇄한다. 맥락 태그로는 안 잡힌다(배경 축 교훈).
    "species_male":      (MALE_SPECIES, 2.0, "upper"),
    # 성인 축 — 베이스와 등급이 고정된다. 목록은 사용자가 `_todo/` 에 올린다.
    **{_k: (adult_base(_RATING_EXPLICIT if _t == "explicit" else _RATING_QUEST),
            2.0, "cowboy")
       for _k, _t in ADULT_BATCHES.items()},
    "skin":              (UPPER, 2.0, "upper"),
    "tail":              (TAILV, 2.5, "tail"),
    "wings":             (WINGV, 2.5, "wings"),
    "wings_portrait":    (HEAD, 2.5, "portrait"),   # head wings / hair wings 는 머리
    "body_nonhuman":          (TORSO, 2.5, "cowboy"),
    "body_nonhuman_portrait": (HEAD, 2.5, "portrait"),   # 아가미/더듬이/머리 지느러미
    "body_nonhuman_full":     (FULL, 2.5, "full"),       # 발굽/새 다리/지느러미
    "body_nonhuman_male":     (male(TORSO), 2.5, "cowboy"),
    # Vision 검수에서 태그가 렌더되지 않은 것들을 다른 시드로 한 번 더 돌린다.
    # 프레이밍은 원래 축과 같게 두고 시드만 바꾼다(--seed).
    # 성격·유형은 다른 축과 반대로 **아무것도 고정하지 않는다**. 성격은 머리·의상·
    # 표정·자세를 한꺼번에 바꾸는 게 정체성인데, 자세 템플릿의 `white shirt,
    # pleated skirt` 가 그 통로를 막고 있었다(그래도 mesugaki 는 분홍 베스트를 밀어
    # 넣었다). nude/safe 도 쓰지 않는다 — 의상 자체가 유형의 신호다.
    # cowboy: 머리·표정과 상의가 같이 보여야 유형이 읽힌다.
    "persona":           (PERSONA, 2.0, "cowboy"),   # 성격·유형(tomboy/tsundere/...)
    # 사물·동물·효과 (build_object/creature/effect_axes.py 가 축을 정한다)
    "obj_food":            (FOODTPL, 2.0, "food"),
    "obj_tool":            (OBJTPL, 2.0, "object"),
    "obj_weapon":          (OBJTPL, 2.0, "object"),
    "obj_container":       (OBJTPL, 2.0, "object"),
    "obj_tech":            (OBJTPL, 2.0, "object"),
    "obj_furniture":       (ROOMTPL, 2.0, "room"),
    "obj_vehicle":         (VEHTPL, 2.0, "vehicle"),
    "obj_play":            (OBJTPL, 2.0, "object"),
    "obj_etc":             (OBJTPL, 2.0, "object"),
    "ani_mammal":          (ANITPL, 2.0, "animal"),
    "ani_plant":         (ANITPL, 2.0, "animal"),
    "ani_bird":            (ANITPL, 2.0, "animal"),
    "ani_bug":             (ANITPL, 2.0, "animal"),
    "ani_aqua":            (ANITPL, 2.0, "animal"),
    "ani_etc":             (ANITPL, 2.0, "animal"),
    "fx_effect":           (FXTPL, 2.0, "subject"),
    "fx_symbol":           (FXTPL, 2.0, "subject"),
    "fx_tone":             (FXTPL, 2.0, "subject"),
    # 조명도 주체가 있어야 보인다 — `backlighting` 을 빈 화면에 걸면 역광이 아니라
    # 그냥 어두운 그림이 된다(색조 축과 같은 이유).
    "fx_light":            (FXTPL, 2.0, "subject"),
    # 배경 — 파일럿 25장으로 프레이밍이 세 갈래임을 확인했다(build_location_axes.py).
    "loc_backdrop":        (BACKDR, 2.0, "loc_backdrop"),
    "loc_indoor":          (INTERIOR, 2.0, "loc_interior"),
    "loc_place":           (SCENERY, 2.0, "loc_scenery"),
    "loc_object":       (SCENERY_OBJ, 2.0, "loc_object"),
    "_t_obj":            (SCENERY_OBJ, 2.0, "loc_scenery"),
    "loc_nature":          (SCENERY, 2.0, "loc_scenery"),
    "loc_water":           (SCENERY, 2.0, "loc_scenery"),
    "loc_sky":             (SCENERY, 2.0, "loc_scenery"),
    "loc_weather":         (SCENERY, 2.0, "loc_scenery"),
    "loc_time":            (SCENERY, 2.0, "loc_scenery"),
    "expression":        (HEAD, 2.5, "portrait"),    # 감정 표정
    "expression_symbol": (HEAD, 2.5, "portrait"),    # 만화 기호 표정
    "face_shape":        (HEAD, 2.5, "portrait"),    # 눈·입·눈썹 형태
    "expression_state":  (HEAD, 2.5, "portrait"),    # 홍조·눈물·침·땀 (상태 축 해체분)
    "body_condition":    (TORSO, 2.5, "cowboy"),     # 부상·붕대·오염 (상태 축 해체분)
    # 다리·발 부상(붕대 발목/무릎/발)은 cowboy shot 에서 프레임 밖이다.
    # 의상 축의 C_LOWER 와 같은 발상 — 하반신으로 내린다.
    "body_condition_lower": (FULL, 2.5, "full"),
    "body_condition_portrait": (HEAD, 2.5, "portrait"),  # 얼굴 오염·부상
    "marking":           (TORSO, 2.5, "cowboy"),      # 팔·가슴·배 문신
    "marking_portrait":  (HEAD, 2.5, "portrait"),     # 귀 피어싱 / 얼굴 표식
    "_redo_portrait":    (HEAD, 3.0, "portrait"),
    "_redo_cowboy":      (TORSO, 3.0, "cowboy"),
    "_redo_tail":        (TAILV, 3.0, "tail"),
}


# ── 의상 슬롯 템플릿 ────────────────────────────────────────────────────────
# 특징 축의 핵심 장치는 `nude, safe` 였다 — 옷이 특징을 가리지 않게 하고 NAI 가 필수
# 요소에만 집중하게 만든다. **의상은 옷이 주제이므로 이 장치를 쓸 수 없다.**
#
# 대체 장치가 '대조 의상(control garment)'이다. `pleated skirt` 를 찍을 때 상의를
# 지정하지 않으면 NAI 가 매번 다른 상의를 그려서 그리드 전체가 시각적으로 시끄러워진다.
# 변하지 않는 쪽을 고정하면 변하는 쪽(=축의 태그)만 눈에 남는다.
#
# 프레이밍은 사용자 지침을 따른다: "썸네일 크기로는 full body 소화가 불가능" ->
# 기본은 cowboy shot 이고, 다리·신발만 하반신으로 내린다.
#   ⚠️ 원피스·제복·전통은 기장이 정체성인데 cowboy shot 은 밑단을 잘라낸다.
#   `short dress` / `long dress` 는 구분되지 않는다(34개 중 2개). 사용자 판단 대기.
_CQ = "rating:general, white background, simple background"
# 상의·소매·손: 상반신. 하의가 보이지 않아 대조 의상이 필요 없다.
C_UPPER = (f"1girl, {ARTIST}, young female, solo, front view, upper body, <<VARY>>, "
           f"looking at viewer, {_CQ}, {QUALITY}")
# 모자·머리장식·목·안경: 초상. 흰 셔츠로 목선을 고정해 장식만 달라지게 한다.
C_HEAD = (f"1girl, {ARTIST}, young female, solo, front view, portrait, <<VARY>>, "
          f"white shirt, close-up, looking at viewer, {_CQ}, {QUALITY}")
# 하의·속옷·수영복·상태·디테일·무늬: cowboy shot. 하의 축에는 흰 셔츠를 고정한다.
C_TORSO = (f"1girl, {ARTIST}, young female, solo, front view, cowboy shot, <<VARY>>, "
           f"looking at viewer, {_CQ}, {QUALITY}")
C_BOTTOM = (f"1girl, {ARTIST}, young female, solo, front view, cowboy shot, <<VARY>>, "
            f"white shirt, looking at viewer, {_CQ}, {QUALITY}")
# 다리·신발: 하반신. 주름치마 + 흰 셔츠를 고정해 다리·발만 달라지게 한다.
C_LOWER = (f"1girl, {ARTIST}, young female, solo, front view, lower body, standing, "
           f"<<VARY>>, pleated skirt, white shirt, {_CQ}, {QUALITY}")
# 원피스·한벌·전통·제복·겉옷·갑옷: cowboy shot(사용자 규칙). 대조 의상 없음.
C_OUTFIT = (f"1girl, {ARTIST}, young female, solo, front view, cowboy shot, <<VARY>>, "
            f"looking at viewer, {_CQ}, {QUALITY}")

CLOTH_BATCHES = {
    "cloth_top":         (C_UPPER, 2.0, "cloth_upper"),
    "cloth_sleeve":      (C_UPPER, 2.0, "cloth_upper"),
    "cloth_handwear":    (C_UPPER, 2.0, "cloth_upper"),
    "cloth_headwear":    (C_HEAD, 2.0, "cloth_head"),
    "cloth_hairacc":     (C_HEAD, 2.0, "cloth_head"),
    "cloth_neck":        (C_HEAD, 2.0, "cloth_head"),
    "cloth_eyewear":     (C_HEAD, 2.0, "cloth_head"),
    "cloth_bottom":      (C_BOTTOM, 2.0, "cloth_bottom"),
    "cloth_under":       (C_TORSO, 2.0, "cloth_torso"),
    "cloth_swim":        (C_TORSO, 2.0, "cloth_torso"),
    "cloth_state":       (C_TORSO, 2.0, "cloth_torso"),
    "cloth_detail":      (C_TORSO, 2.0, "cloth_torso"),
    "cloth_pattern":     (C_TORSO, 2.0, "cloth_torso"),
    "cloth_accessory":   (C_TORSO, 2.0, "cloth_torso"),
    # 소형 장신구는 portrait 다. 192px 크롭에서 귀걸이는 약 15px 라 cowboy 로는
    # 화소가 없어 시드로도 해결되지 않는다 — 파일럿에서 portrait 은 통과했다.
    "cloth_small":       (C_HEAD, 2.0, "cloth_head"),
    # 액세서리 축을 부위로 쪼개며 신설. 벨트는 허리, 가방은 손에 들거나 메므로
    # 둘 다 cowboy shot 이면 프레임에 들어온다.
    "cloth_waist":       (C_TORSO, 2.0, "cloth_torso"),
    "cloth_carried":     (C_TORSO, 2.0, "cloth_torso"),
    "cloth_legwear":     (C_LOWER, 2.0, "cloth_lower"),
    "cloth_footwear":    (C_LOWER, 2.0, "cloth_lower"),
    "cloth_dress":       (C_OUTFIT, 2.0, "cloth_outfit"),
    "cloth_outer":       (C_OUTFIT, 2.0, "cloth_outfit"),
    "cloth_traditional": (C_OUTFIT, 2.0, "cloth_outfit"),
    "cloth_uniform":     (C_OUTFIT, 2.0, "cloth_outfit"),
    "cloth_style":       (C_OUTFIT, 2.0, "cloth_outfit"),
    "cloth_armor":       (C_OUTFIT, 2.0, "cloth_outfit"),
    # Vision 검수에서 렌더되지 않은 태그를 다른 시드로 다시 돌리는 배치.
    # 2026-07-26 예약 실행이 만들었는데 init 에 없어서 _bench.json 재생성 때
    # 정의가 날아갔다. 프레이밍은 원래 축과 같게 두고 --seed 로만 바꾼다.
    "_redo_cloth_portrait": (C_HEAD, 2.0, "cloth_head"),
    "_redo_cloth_torso":    (C_TORSO, 2.0, "cloth_torso"),
    "_redo_cloth_upper":    (C_UPPER, 2.0, "cloth_upper"),
    # 작은 액세서리(귀걸이·반지·팔찌)가 cowboy shot 에서 안 보인다는 판단으로
    # 만들어진 파일럿. 부위 재분할로 근본 해결됐지만 검증용으로 남긴다.
    "_pilot_acc_portrait":  (C_HEAD, 2.0, "cloth_head"),
    # 파일럿 전용(축당 3장). 프레이밍 실패를 싸게 잡는다 — 특징 슬롯에서 파일럿 27장이
    # 축 단위 실패 3건을 잡아 수백 장을 절약했다.
    "_pilot_upper":      (C_UPPER, 2.0, "cloth_upper"),
    "_pilot_head":       (C_HEAD, 2.0, "cloth_head"),
    "_pilot_bottom":     (C_BOTTOM, 2.0, "cloth_bottom"),
    "_pilot_torso":      (C_TORSO, 2.0, "cloth_torso"),
    "_pilot_lower":      (C_LOWER, 2.0, "cloth_lower"),
    "_pilot_outfit":     (C_OUTFIT, 2.0, "cloth_outfit"),
}
# cloth_nsfw 는 의도적으로 없다 — body_nsfw 와 같이 사람이 직접 한다.
BATCHES.update(CLOTH_BATCHES)


# ── 자세 슬롯 템플릿 ────────────────────────────────────────────────────────
# 자세는 특징·의상과 다르다. 옷은 `nude, safe` 를 못 쓰고, 자세는 **몸 전체가 곧
# 정보**라 손짓 말고는 전신이 필요하다. 사용자 규칙("full body 는 썸네일에서 소화
# 불가")과 충돌하지만, `sitting` 을 cowboy 로 찍으면 앉았는지 서 있는지 알 수 없어
# 이미지가 아예 무의미해진다. 전신 축은 작게 보이는 대가를 감수한다.
#
# 옷은 흰 셔츠+주름치마로 고정한다 — 자세가 변수이므로 의상이 매번 달라지면
# 그리드가 시끄럽고, 나체로 두면 등급이 튄다.
_PQ = "rating:general, white background, simple background"
_POUTFIT = "white shirt, pleated skirt"
P_HEAD = (f"1girl, {ARTIST}, young female, solo, front view, portrait, <<VARY>>, "
          f"{_POUTFIT}, close-up, looking at viewer, {_PQ}, {QUALITY}")
P_UPPER = (f"1girl, {ARTIST}, young female, solo, front view, upper body, <<VARY>>, "
           f"{_POUTFIT}, looking at viewer, {_PQ}, {QUALITY}")
P_TORSO = (f"1girl, {ARTIST}, young female, solo, front view, cowboy shot, <<VARY>>, "
           f"{_POUTFIT}, looking at viewer, {_PQ}, {QUALITY}")
P_FULL = (f"1girl, {ARTIST}, young female, solo, front view, full body, <<VARY>>, "
          f"{_POUTFIT}, {_PQ}, {QUALITY}")

# 다인원 축(`_m`)은 **상대가 있어야 자세가 성립한다**. 그런데 처음엔 위 솔로 템플릿을
# 그대로 물려서 `1girl, solo` 로 찍었고, NAI 는 `solo` 를 이겨내지 못했다 — 실측:
# `hug` 은 인형을 안은 1인, `piggyback` 은 혼자 허리 숙인 그림이 나왔다.
# 자세 축을 개별/글로벌로 가른 이유 자체를 템플릿이 뒤집고 있었다.
#
# 인원 구성은 최신 10개 parquet 실측상 girl+boy 41~57% / 2girls 29~47% 로 우열이
# 없다. 데이터가 답을 주지 않으므로 솔로 축과 화면 톤을 맞추는 쪽으로 `2girls` 고정.
# `looking at viewer` 는 뺀다 — 둘이 서로에게 하는 동작이 주제고, 둘 다 정면을
# 보면 상호작용이 죽는다.
_PDUO = "2girls, multiple girls"
PM_UPPER = (f"{_PDUO}, {ARTIST}, young female, front view, upper body, <<VARY>>, "
            f"{_POUTFIT}, {_PQ}, {QUALITY}")
PM_TORSO = (f"{_PDUO}, {ARTIST}, young female, front view, cowboy shot, <<VARY>>, "
            f"{_POUTFIT}, {_PQ}, {QUALITY}")
PM_FULL = (f"{_PDUO}, {ARTIST}, young female, front view, full body, <<VARY>>, "
           f"{_POUTFIT}, {_PQ}, {QUALITY}")

# 축 목록을 손으로 나열하면 새 축(pose_leg)이 빠지고 없어진 축(pose_arm_2)이 남는다 —
# 탐색기 서브그룹에서 이미 같은 실수로 259개를 흘렸다. 축 정의에서 파생시키고 검증한다.
_PSOLO_TPL = {"portrait": (P_HEAD, "pose_portrait"), "upper": (P_UPPER, "pose_upper"),
              "cowboy": (P_TORSO, "pose_cowboy"), "full": (P_FULL, "pose_full")}
# 다인원에는 portrait 이 없다. 파일럿에서 `headpat` 은 상대가 손만 남고 `spitting` 은
# 받는 쪽이 화면 밖으로 잘렸다 — close-up 크롭에 두 사람이 안 들어간다.
# 얼굴 축이라도 다인원이면 upper body 로 올린다. 1024 안에 머리 둘이면 입·손은 충분히 읽힌다.
_PMULTI_TPL = {"portrait": (PM_UPPER, "pose_upper"), "upper": (PM_UPPER, "pose_upper"),
               "cowboy": (PM_TORSO, "pose_cowboy"), "full": (PM_FULL, "pose_full")}
# `_m` 은 접미사로만 판정한다. `in ax` 로 보면 pose_mo|u|th 의 `_m` 에 걸린다.
_RE_MULTI = re.compile(r"_m(_\d+)?$")

_pose_spec = json.loads(Path("wildcards/thumb/_pose_axes.json").read_text(encoding="utf-8"))
POSE_BATCHES = {
    # 렌더가 안 된 자세 태그의 시드 재시도. **프레이밍·템플릿은 원래 축과 같게 두고
    # 시드만 바꾼다** — 다르게 두면 개선이 시드 덕인지 템플릿 덕인지 알 수 없다.
    # 의상 섹션에서 30장 재생성 중 19장이 이 방식으로 살아났다.
    "_redo_pose_display": (P_TORSO, 2.0, "pose_cowboy"),
    # 파일럿 — 프레이밍 4종 x 3장.
    "_pilot_pose_head":  (P_HEAD, 2.0, "pose_portrait"),
    "_pilot_pose_upper": (P_UPPER, 2.0, "pose_upper"),
    "_pilot_pose_torso": (P_TORSO, 2.0, "pose_cowboy"),
    "_pilot_pose_full":  (P_FULL, 2.0, "pose_full"),
}
for _ax, _fr in sorted(_pose_spec["framing"].items()):
    if not (Path("wildcards/thumb") / f"{_ax}.txt").exists():
        continue                      # n-way 분할에서 안 쓰인 슬롯
    _tpl, _key = (_PMULTI_TPL if _RE_MULTI.search(_ax) else _PSOLO_TPL)[_fr]
    POSE_BATCHES[_ax] = (_tpl, 2.0, _key)

# 렌더 축이 아닌 중간 산출물. 분류 결과(solo/multi/drop)와 보류한 성인 축이
# 축과 같은 `pose_*` 접두를 쓴다 — 의존성 힌트에서 `pose_solo` 가 축 이름으로
# 샜던 것과 같은 뿌리다. 글로브로 조용히 거르지 않고 이름을 적어 의도를 남긴다.
# 축 판정은 emit 이 내는 인덱스가 SSOT 다(tools/thumb_axis_index.py). 성인 자세는
# 사용자가 직접 만들므로 배치 정의 대상이 아니라 여기서만 추가로 뺀다.
from tools.thumb_axis_index import is_axis  # noqa: E402

_POSE_USER_OWNED = {"pose_nsfw", "pose_nsfw_face"}
_pose_files = {p.stem for p in Path("wildcards/thumb").glob("pose_*.txt")
               if is_axis(p.stem)} - _POSE_USER_OWNED
_uncovered = _pose_files - set(POSE_BATCHES)
assert not _uncovered, f"배치 정의가 없는 자세 축: {sorted(_uncovered)}"
BATCHES.update(POSE_BATCHES)
BATCHES.update(SENSITIVE_BATCHES)


bench = {
    "note": [
        "축별 고정 베이스의 SSOT. tools/thumb_bench.py 가 이 파일을 읽는다.",
        "<<VARY>> 자리에 '가중치::태그 ::' 가 들어간다.",
        "파라미터/네거티브는 사용자가 승인한 이미지 메타데이터에서 뽑은 실측값이다.",
        "young female 고정 + 네거티브의 {adolescent, mature female} 로 성인 여성 톤을 회피한다.",
        "nude + safe 조합은 옷이 특징을 가리지 않게 하면서 등급을 안전하게 유지한다.",
        "body_nsfw 는 의도적으로 뺐다 — 명시적 성적 이미지 생성은 사람이 직접 한다.",
    ],
    "defaults": {"model": "nai-diffusion-4-5-full", "weight": 2.0,
                 "negative": NEGATIVE, "parameters": PARAMETERS},
    # `_male` 배치만 네거티브를 갈아 끼운다(thumb_bench 가 spec.negative 를 먼저 본다).
    "batches": {k: ({"template": t, "weight": w, "framing": f}
                    | ({"negative": NEGATIVE_MALE} if "_male" in k else {})
                    | ({"negative": NEGATIVE_EXPLICIT
                        if ADULT_BATCHES.get(k) == "explicit" else NEGATIVE_ADULT}
                       if k in ADULT_BATCHES else {}))
                for k, (t, w, f) in BATCHES.items()},
}
# 성인 배치가 어린 외형 태그를 갖는 일은 없어야 한다. 손으로 고쳐도 여기서 죽는다.
# (`young female` 은 태그 DB 의 Danger 그룹 — "미성년 외모의 여성 캐릭터가 묘사됨")
# `diaper` 도 넣는다 — 성인 기저귀 취향이 따로 있긴 하나, 성적 맥락에서는
# 유아화로 읽히고 이 프로젝트의 우려(한국 법)와 정면으로 닿는다.
# 런타임 가드와 **같은 출처**를 쓴다. 전에는 이 목록이 thumb_bench.py 에도 복사돼
# 있었고 둘 다 같은 구멍이었다(Codex 리뷰 2026-07-30).
from tools.thumb_age_guard import danger_age_hits  # noqa: E402
for _k in ADULT_BATCHES:
    _spec = bench["batches"].get(_k)
    if not _spec:
        continue
    _bad = danger_age_hits(_spec["template"])
    assert not _bad, f"성인 배치 {_k} 에 어린 외형 태그: {_bad}"
    assert "mature female" in _spec["template"], f"성인 배치 {_k} 에 mature female 이 없다"
    # 등급이 빠지면 NAI 가 안전한 쪽으로 되돌아가 무엇을 만들었는지 알 수 없어진다.
    assert ("rating:explicit" in _spec["template"]
            or "rating:questionable" in _spec["template"]), f"성인 배치 {_k} 에 등급이 없다"
    # 은닉 3종은 사용자 사양이다 — 하나라도 빠지면 얼굴이 돌아온다.
    for _c in ("faceless female", "head out of frame", "close-up"):
        assert _c in _spec["template"], f"성인 배치 {_k} 에 은닉 태그 없음: {_c}"

# sensitive 배치도 연령은 같은 기준으로 막는다. 등급이 낮다고 느슨해지지 않는다.
for _k in SENSITIVE_BATCHES:
    _spec = bench["batches"][_k]
    _bad = danger_age_hits(_spec["template"])
    assert not _bad, f"sensitive 배치 {_k} 에 어린 외형 태그: {_bad}"
    # 남성 커플 배치에는 `mature female` 이 있으면 안 된다 — 연령 요구지 성별 요구가
    # 아니다. 둘 중 하나는 반드시 있어야 한다.
    assert ("mature female" in _spec["template"]
            or "mature male" in _spec["template"]), f"sensitive 배치 {_k} 에 연령 태그가 없다"
    assert "rating:sensitive" in _spec["template"], f"sensitive 배치 {_k} 에 등급이 없다"
    # 노출 태그가 섞이면 등급이 무의미해진다. thumb_bench 가 요청 직전에 또 본다.
    for _bad_tag in ("nude", "naked", "rating:explicit", "rating:questionable"):
        assert _bad_tag not in _spec["template"], f"sensitive 배치 {_k} 에 {_bad_tag}"

OUT.write_text(json.dumps(bench, ensure_ascii=False, indent=2), encoding="utf-8")

todo = sorted(p.stem for p in Path("wildcards/thumb/_todo").glob("*.txt"))
missing = [t for t in todo if t not in BATCHES]
print(f"_bench.json: 배치 정의 {len(BATCHES)}개 / _todo 파일 {len(todo)}개")
if missing:
    print(f"!! 정의 없는 배치 {len(missing)}개: {missing}")
else:
    print("모든 _todo 배치에 정의가 있습니다.")
for k in todo:
    if k in BATCHES:
        n = len([l for l in (Path('wildcards/thumb/_todo') / f'{k}.txt')
                 .read_text(encoding='utf-8').splitlines() if l.strip()])
        print(f"  {k:<26}{n:>4}장  {BATCHES[k][2]:<9}{BATCHES[k][1]}::")
