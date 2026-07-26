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
"""
import json
from pathlib import Path

OUT = Path("wildcards/thumb/_bench.json")

ARTIST = "0.38::kanzarin, nns (sobchan), torino aqua, ixy, epi zero ::"
QUALITY = ("0.4:: watercolor (medium), no lineart ::, -1:: thick outlines, ai-generated ::, "
           "best quality, masterpiece, very absurdres, year 2024, year 2025, "
           "-1::widescreen, blurry ::")

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

def male(tpl: str) -> str:
    """남성 배치 — 1girl/young female 을 바꾼다. 이것만 바꿔야 나머지 톤이 유지된다."""
    return tpl.replace("1girl, ", "1boy, ", 1).replace("young female", "mature male", 1)

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
    "species_male":      (male(UPPER), 2.0, "upper"),
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

POSE_BATCHES = {
    "pose_action": (P_FULL, 2.0, "pose_full"),
    "pose_action_2": (P_FULL, 2.0, "pose_full"),
    "pose_action_3": (P_FULL, 2.0, "pose_full"),
    "pose_action_m": (P_FULL, 2.0, "pose_full"),
    "pose_action_m_2": (P_FULL, 2.0, "pose_full"),
    "pose_arm": (P_UPPER, 2.0, "pose_upper"),
    "pose_arm_2": (P_UPPER, 2.0, "pose_upper"),
    "pose_arm_m": (P_UPPER, 2.0, "pose_upper"),
    "pose_clothing": (P_TORSO, 2.0, "pose_cowboy"),
    "pose_clothing_2": (P_TORSO, 2.0, "pose_cowboy"),
    "pose_clothing_m": (P_TORSO, 2.0, "pose_cowboy"),
    "pose_combat": (P_FULL, 2.0, "pose_full"),
    "pose_combat_m": (P_FULL, 2.0, "pose_full"),
    "pose_display": (P_TORSO, 2.0, "pose_cowboy"),
    "pose_display_m": (P_TORSO, 2.0, "pose_cowboy"),
    "pose_face_touch": (P_HEAD, 2.0, "pose_portrait"),
    "pose_face_touch_m": (P_HEAD, 2.0, "pose_portrait"),
    "pose_gaze": (P_HEAD, 2.0, "pose_portrait"),
    "pose_hand": (P_HEAD, 2.0, "pose_portrait"),
    "pose_hand_m": (P_HEAD, 2.0, "pose_portrait"),
    "pose_holding": (P_TORSO, 2.0, "pose_cowboy"),
    "pose_holding_2": (P_TORSO, 2.0, "pose_cowboy"),
    "pose_holding_3": (P_TORSO, 2.0, "pose_cowboy"),
    "pose_holding_m": (P_TORSO, 2.0, "pose_cowboy"),
    "pose_mouth": (P_HEAD, 2.0, "pose_portrait"),
    "pose_mouth_m": (P_HEAD, 2.0, "pose_portrait"),
    "pose_posture": (P_FULL, 2.0, "pose_full"),
    "pose_posture_2": (P_FULL, 2.0, "pose_full"),
    "pose_posture_m": (P_FULL, 2.0, "pose_full"),
    # 파일럿 — 프레이밍 4종 x 3장.
    "_pilot_pose_head":  (P_HEAD, 2.0, "pose_portrait"),
    "_pilot_pose_upper": (P_UPPER, 2.0, "pose_upper"),
    "_pilot_pose_torso": (P_TORSO, 2.0, "pose_cowboy"),
    "_pilot_pose_full":  (P_FULL, 2.0, "pose_full"),
}
BATCHES.update(POSE_BATCHES)


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
    "batches": {k: {"template": t, "weight": w, "framing": f}
                for k, (t, w, f) in BATCHES.items()},
}
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
