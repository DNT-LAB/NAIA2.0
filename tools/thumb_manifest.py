# -*- coding: utf-8 -*-
"""_manifest.json 재작성 — 축별 프레이밍/베이스와 복붙용 벤치 프롬프트를 담는다.

기존 manifest 는 축 개수가 옛 목록(12/24/63...)에 고정돼 있어 실제와 어긋났고,
프레이밍을 어디서 확인해야 하는지도 애매했다. body_type 63장이 잘못된
프레이밍(cowboy shot + head out of frame + close-up)으로 전량 재생성 대상이 된
원인이 그것이다. 여기서는 축 목록/팩을 읽어 실측값으로 다시 쓴다.
"""
import json
from pathlib import Path

OUT = Path("wildcards/thumb")
PACK = Path("data/interactive_thumbnails.json")

FRAMING = {
    "hair_style": "portrait", "bangs": "portrait", "hair_pattern": "portrait",
    "face": "portrait", "eye_pattern": "portrait", "ears": "portrait",
    "skin": "upper", "species": "upper",
    # 상태는 얼굴(홍조/눈물/침)과 몸통(땀/멍/붕대)이 함께 보여야 한다.
    "state": "upper",
    "horns": "portrait",
    # 전신은 썸네일 크기에서 소화가 안 된다(사용자 판단) -> 부위 축은 cowboy shot.
    # 승인된 body_type 31장이 이 레시피로 생성됐으므로 나머지도 같은 레시피를 쓴다.
    "body_type": "cowboy", "body_expose": "cowboy", "body_feature": "cowboy",
    "body_nonhuman": "cowboy",
    # 꼬리/날개는 부속물 전체가 프레임에 들어와야 하므로 전신을 유지한다.
    "tail": "full", "wings": "full",
    "body_nsfw": "explicit",
}
LABEL = {
    "hair_style": "머리 모양", "bangs": "앞머리", "hair_pattern": "머리 패턴",
    "face": "얼굴", "eye_pattern": "눈 패턴", "ears": "귀", "skin": "피부",
    "species": "종족", "tail": "꼬리", "wings": "날개", "body_type": "체형",
    "body_expose": "노출·강조", "body_feature": "신체 특징", "body_nsfw": "노출(성인)", "body_nonhuman": "이형 부위", "horns": "뿔", "state": "상태",
}
PACK_AXIS = {"face_eyes": "face", "face_mouth": "face", "face_etc": "face"}

# 프레이밍별 베이스. 서로 충돌하는 프레이밍 태그를 절대 섞지 않는다.
#   portrait  얼굴 위주 — 머리/얼굴/귀
#   upper     상반신   — 피부/종족(케모미미는 귀+얼굴+어깨)
#   full      전신     — 꼬리/날개/체형/부위
BASE = {
    "portrait": "portrait, close-up, front view, looking at viewer",
    "upper": "upper body, front view, looking at viewer",
    # 승인된 body_type 31장의 실제 레시피. head out of frame 으로 얼굴을 버리고
    # 몸통에 화소를 몰아준다 — 썸네일 크기에서 전신보다 판별이 낫다.
    "cowboy": "cowboy shot, head out of frame, close-up, front view",
    "full": "full body, standing, front view, looking at viewer",
    "explicit": "cowboy shot, head out of frame, close-up, front view",
}

ARTIST = "0.38::kanzarin, nns (sobchan), torino aqua, ixy, epi zero ::"
QUALITY = ("0.4:: watercolor (medium), no lineart ::, -1:: thick outlines, ai-generated ::, "
           "best quality, masterpiece, very absurdres, year 2024, year 2025, "
           "-1::widescreen, blurry ::")

def bench(framing: str, axis: str, male: bool = False) -> dict:
    who = "1boy, solo, mature male" if male else "1girl, solo, young female"
    tail = "rating:general, simple background, white background"
    body = BASE[framing]
    if framing == "explicit":
        tail = "simple background, white background, nsfw, rating:explicit"
    wc = f"_todo/{axis}_male" if male else f"_todo/{axis}"
    return {
        "prefix": f"{who}, {ARTIST}",
        "main": f"{body}, 2::__*thumb/{wc}__ ::, {tail}",
        "postfix": QUALITY,
    }

pack = json.loads(PACK.read_text(encoding="utf-8")) if PACK.exists() else {}
have = {}
for k in pack:
    ax, tag = k.split('/', 1)
    have.setdefault(ax, set()).add(tag)

axes = []
for wc in sorted(OUT.glob("*.txt")):
    ax = wc.stem
    if ax.startswith('_'):
        continue
    tags = [l.strip() for l in wc.read_text(encoding="utf-8").splitlines() if l.strip()]
    fr = FRAMING.get(ax, "portrait")
    todo_f = OUT / "_todo" / f"{ax}.txt"
    todo_m = OUT / "_todo" / f"{ax}_male.txt"
    n_f = len([l for l in todo_f.read_text(encoding="utf-8").splitlines() if l.strip()]) if todo_f.exists() else 0
    n_m = len([l for l in todo_m.read_text(encoding="utf-8").splitlines() if l.strip()]) if todo_m.exists() else 0
    entry = {
        "key": ax, "label": LABEL.get(ax, ax), "framing": fr,
        "count": len(tags), "done": len(have.get(PACK_AXIS.get(ax, ax), set())),
        "todo_female": n_f, "todo_male": n_m,
        "bench": bench(fr, ax),
    }
    if n_m:
        entry["bench_male"] = bench(fr, ax, male=True)
    axes.append(entry)

man = {
    "note": [
        "프레이밍은 축별로 다르다. bench 를 그대로 복붙해 쓴다.",
        "부위/체형 축은 cowboy shot + head out of frame — 썸네일 크기에서는 전신이 소화되지 않아",
        "얼굴을 버리고 몸통에 화소를 몰아주는 것이 판별에 유리하다(승인된 body_type 31장의 레시피).",
        "꼬리/날개는 부속물이 프레임에 다 들어와야 하므로 전신을 유지한다.",
        "베이스에 머리 길이를 고정하지 말 것 — NAI 가중치가 형태를 자동 보정한다.",
        "남성 고정 태그(수염, -boy, -man)는 1girl 베이스로 렌더되지 않는다 -> bench_male 로 따로 배치.",
        "생성 대기 목록은 wildcards/thumb/_todo/ 이며 make_todo.py 로 갱신한다(멱등).",
    ],
    "vary": "2::__*thumb/<wildcard>__ ::",
    "framing_base": BASE,
    "axes": axes,
    "palette_shape": "rect",
    "sensitive_axes": ["body_nsfw"],
}
(OUT / "_manifest.json").write_text(json.dumps(man, ensure_ascii=False, indent=2), encoding="utf-8")
tf = sum(a["todo_female"] for a in axes)
tm = sum(a["todo_male"] for a in axes)
print(f"_manifest.json 재작성: 축 {len(axes)}개 / 총 {sum(a['count'] for a in axes)}장")
print(f"  완료 {sum(a['done'] for a in axes)}  대기 여성 {tf} + 남성 {tm} = {tf+tm}")
for a in axes:
    if a["todo_female"] or a["todo_male"]:
        print(f"  {a['key']:<14} {a['framing']:<9} 여{a['todo_female']:>4} 남{a['todo_male']:>3}")
