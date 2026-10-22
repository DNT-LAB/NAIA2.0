# -*- coding: utf-8 -*-
"""캐릭터 미리보기 팩 확장용 연속 생성기 (2026-10-21 · 개발 전용 · 런타임 미사용).

기존 팩(`data/character_preview_thumbs.json` 3,000장 · 08-01/02 NAIA 앱 생성)과 **같은 설정**으로
썸네일이 없는 캐릭터를 게시물 순으로 뽑아 원본 PNG 를 만든다. 팩으로 굽는 것은 빌더가 따로 한다.

    python tools/character_pack_generate.py targets [--count 5000]
    python tools/character_pack_generate.py run --lane A     # GN5 -> MYT
    python tools/character_pack_generate.py run --lane B     # BKN -> 0UY

- 대상 = `data/character_analysis.json` 중 팩에 없는 캐릭터 · `danbooru_posts` 내림차순.
- 머리말 = 성별(사전) · 비인간이면 1other: 코퍼스 `no_humans/rows >= 0.3`
  (`docs/character_pool_survey_2026_10_19/char_gender_survey.json` · 재조사와 같은 잣대).
- 캐릭터 줄 = 앱의 `CharacterViewerService.build_prompt`(Find [+ 슬롯] 과 같은 줄)에서 앞의 girl/boy 를 뗀 것.
- 계정 = 토큰 파일(라벨은 토큰 `pst-` 뒤 3글자). 한 계정 = 한 번에 한 장(NAI 429 Concurrent locked).
- 무료 대역만(28 스텝 · 1024x1024 = 1,048,576px). 계정마다 Anlas 를 처음 · 25장마다 재서 줄면 그 계정을 멈춘다.
- 이어 하기: 파일이 있으면 건너뛴다. 멈추기: 출력 폴더에 `STOP` 파일.
- 출처 기록: `manifest_<label>.jsonl` 에 키 · 파일 · 시드 · 줄 · 시각.

V5 몫(2026-10-22 · 사용자 지정 프롬프트 · V4.5F 가 모르는 2025 이후 데뷔 · 개명 · 모름):

    python tools/character_pack_generate.py v5-targets
    python tools/character_pack_generate.py run --lane A --v5 [--limit 1]

- 모델 = NAID5F-medium(`nai-diffusion-5-full-medium`) · Small 정사각 640x640 · CFG 5.
  Medium 은 14스텝 · k_euler_ancestral · karras · rescale 0 고정이고 네거티브를 안 받는다(core/nai_model_contract.py).
  4.5F 에 붙이던 추가 파라미터(skip_cfg_above_sigma · deliberate bug)는 보내지 않는다(사용자: medium 은 못 받는다).
- 이미 썸네일이 있는 캐릭터는 뺀다(포터블 user-data 의 character_thumbnails · 사용자 지시).
- 출력 = `.experimental/character_preview_src/20261022_pack_v5/`.

4.5F 추가분(2026-10-22 · 사용자 지시 "2400명 정도를 V4.5 로 더"):

    python tools/character_pack_generate.py more-targets --count 2400 --out 20261022_pack45b
    python tools/character_pack_generate.py run --lane A --out 20261022_pack45b

- 같은 순서(게시물 내림차순 · 데뷔 2025-01 전)에서 첫 5,000 다음부터 · 사용자 썸네일이 있으면 뺀다.
- 설정 · 틀은 첫 5,000 과 같다(TEMPLATE · 1024² · 28스텝). rank 는 5001 부터 이어 붙인다.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = Path(r"C:\VNR\artist_thumb_tool")
OUT = ROOT / ".experimental" / "character_preview_src" / "20261021_pack2"
TARGETS = OUT / "_targets.json"

ACCOUNTS = {"GN5": "token.txt", "BKN": "token4.txt", "MYT": "token3.txt", "0UY": "token2.txt"}
LANES = {"A": ["GN5", "MYT"], "B": ["BKN", "0UY"]}
PER_ACCOUNT = 1250

# 원본 PNG(20260801_150132/06341.png) 메타데이터 그대로.
TEMPLATE = ("{head}, 0.38::kanzarin, nns (sobchan), torino aqua, ixy, epi zero ::, solo, upper body, rating:general, "
            "front view, bust shot, 0.5::close-up, extreme close-up, top of head at edge of frame ::, {line}, "
            "0.4:: watercolor (medium), no lineart ::, -1:: thick outlines, ai-generated ::, best quality, masterpiece, "
            "very absurdres, year 2024, year 2025, -1::widescreen, blurry ::")
NEGATIVE = (
    "blurry, lowres, upscaled, artistic error, film grain, scan artifacts, worst quality, bad quality, jpeg artifacts, "
    "very displeasing, chromatic aberration, halftone, multiple views, logo, too many watermarks, negative space, "
    "blank page, {{{ai-generated,watermarks, text, abs, muscular female, Watermark, artist logo, patreon username, "
    "patreon logo }}}, {bad}, error, fewer, extra, missing, watermark, unfinished, displeasing, signature, extra digits, "
    "username, scan, [abstract], chromatic, bad anatomy, bad hands, low quality, normal quality, mutation, mutated, "
    "extra limb, poorly drawn hands, malformed hands, long neck, long body, extra fingers, mosaic, bad faces, bad face, "
    "bad eyes, bad feet, extra toes, western comics (style), anime screencap, anime coloring, [[[[[[bkub, chabo "
    "(fuketsudan), fuzukikai, beanis, pixel art, tsuzuri (tu-san house)]]]]]],  limited palette, thick outlines, "
    "blender (medium), [[[[hara (harayutaka), naxius noxy,queasy s, ringsel]]]], dorachan r, upscaled, [[[dagasi, "
    "agwing86]]], oldest female, simply drawn genitalia, unusual genitalia, text, loli")
STEPS, WIDTH, HEIGHT = 28, 1024, 1024
NONHUMAN_RATIO = 0.3
# V5 사용량(%) 바닥 멈춤 - **끔**(사용자 2026-10-22: 한도까지 다 쓴다 · 멈춤 기준은 25장마다 잰 Anlas 가 줄었을 때뿐).
# 사용량은 계속 기록만 한다. 다시 켜려면 정수(예: 1).
V5_USAGE_FLOOR = None
CLAIM_STALE_SECONDS = 900  # 공용 목록(--any)에서 잡은 표시가 이보다 오래되면 죽은 프로세스의 것으로 보고 가져간다
SLOW_SECONDS = 40         # 최근 10장 평균이 이보다 길면 할당량 소진으로 본다(평소 6~15초)

# V5 몫(사용자 지정 2026-10-22 · 2판: 구도 태그 + -1::shaded face). 빈 줄은 앱처럼 빼고,
# 빈 줄이 남기는 `, ,` 도 앱의 정리처럼 붙인다 - 나가는 글은 아래 한 줄이다.
OUT_V5 = ROOT / ".experimental" / "character_preview_src" / "20261022_pack_v5"
TEMPLATE_V5 = ("{head}, 0.38::kanzarin, nns (sobchan), torino aqua ::, 0.63::ixy ::, 0.73::epi zero ::, "
               "-0.92::artist collaboration ::, solo, upper body, rating:general, front view, bust shot, "
               "0.5::close-up, extreme close-up, top of head at edge of frame ::, {line}, year 2024, masterpiece, "
               "very aesthetic, 0.9::high complexity ::, 0.23::ultra complexity ::, -0.2::low complexity ::, "
               "0.5::white background ::, -1::shaded face ::")
V5_MODEL, V5_API_MODEL = "NAID5FM", "nai-diffusion-5-full-medium"
V5_STEPS, V5_WIDTH, V5_HEIGHT, V5_CFG = 14, 640, 640, 5.0
USER_THUMBS = ROOT / "NAIA-Portable" / "user-data" / "data" / "character_thumbnails"


def _character_line(service, survey: dict, group: str, name: str, gender: str, opts: dict) -> tuple[str, str, float]:
    """(kind, line, nonhuman_ratio) - 4.5F 몫과 V5 몫이 같은 규칙으로 줄을 만든다."""
    stats = survey.get(name) or {}
    ratio = (stats.get("no_humans", 0) / stats["rows"]) if stats.get("rows") else 0.0
    kind = "other" if (ratio >= NONHUMAN_RATIO or gender == "other") else ("boy" if gender == "boy" else "girl")
    line = str(service.build_prompt(group, name, "", opts, "NAI").get("character_prompt") or "").strip()
    parts = [p.strip() for p in line.split(",")]
    if parts and parts[0] in ("girl", "boy", "other"):
        parts = parts[1:]
    if kind != "girl":
        # 사전의 가슴 크기 · loli 치환은 여성 기준이다 - 남성 · 비인간에는 싣지 않는다(pikachu -> large breasts).
        parts = [p for p in parts if not p.endswith(("breasts", "chest")) and p != "young female"]
    return kind, ", ".join(p for p in parts if p), ratio


def build_more_targets(count: int, out_name: str) -> None:
    """첫 5,000(`20261021_pack2/_targets.json`) 다음 순번부터 `count` 명 - 같은 규칙 · 같은 순서."""
    import tempfile

    sys.path.insert(0, str(ROOT))
    from core.character_viewer_service import CharacterViewerService

    analysis = json.loads((ROOT / "data/character_analysis.json").read_text(encoding="utf-8"))
    pack = set(json.loads((ROOT / "data/character_preview_thumbs.json").read_text(encoding="utf-8"))["thumbs"])
    survey = json.loads((ROOT / "docs/character_pool_survey_2026_10_19/char_gender_survey.json").read_text(encoding="utf-8"))
    debut_doc = json.loads((ROOT / "data/character_debut.json").read_text(encoding="utf-8"))
    debut, since = debut_doc["debut"], debut_doc["recent_since"]
    first = {t["key"] for t in json.loads(TARGETS.read_text(encoding="utf-8"))["targets"]}
    have = set()
    if USER_THUMBS.is_dir():
        for f in USER_THUMBS.glob("*.webp"):
            group, _, rest = f.stem.partition("__")
            have.add(f"{group}::{rest.split('__')[0]}")
    every = sorted(((int(d.get("danbooru_posts") or 0), g, n, d.get("gender") or "girl")
                    for g, cs in analysis.items() for n, d in cs.items() if f"{g}::{n}" not in pack), reverse=True)
    rows = [r for r in every if debut.get(r[2]) and debut[r[2]] < since
            and f"{r[1]}::{r[2]}" not in first and f"{r[1]}::{r[2]}" not in have][:count]
    opts = {"hide_charname": False, "cosplay_enabled": False, "auto_copyright": True}
    accounts = ["GN5", "BKN", "MYT", "0UY"]
    out = []
    with tempfile.TemporaryDirectory() as tmp:
        service = CharacterViewerService(ROOT, save_root=Path(tmp) / "save", thumbnail_root=Path(tmp) / "th")
        for i, (posts, group, name, gender) in enumerate(rows):
            kind, line, ratio = _character_line(service, survey, group, name, gender, opts)
            # 레인 둘이 게시물 순으로 함께 내려가게 - 앞 절반은 GN5 · BKN, 뒤 절반은 MYT · 0UY 가 번갈아.
            half = i >= len(rows) // 2
            out.append({"rank": 5001 + i, "key": f"{group}::{name}", "posts": posts, "kind": kind,
                        "nonhuman_ratio": round(ratio, 3), "line": line,
                        "account": accounts[(2 if half else 0) + (i % 2)]})
    target_dir = OUT.parent / out_name
    target_dir.mkdir(parents=True, exist_ok=True)
    from collections import Counter
    (target_dir / "_targets.json").write_text(json.dumps({
        "note": "4.5F 추가분 - 첫 5,000 다음 순번(사용자 지시 2026-10-22)", "count": len(out),
        "assign": dict(Counter(t["account"] for t in out)), "targets": out,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print("more targets", len(out), dict(Counter(t["kind"] for t in out)),
          "posts", out[0]["posts"] if out else None, "->", out[-1]["posts"] if out else None, target_dir)


def extend_v5_targets() -> None:
    """V5 몫에 **나머지 전부**를 잇는다(사용자 계획 2026-10-22: 4.5F 2,400 뒤 나머지는 V5F-medium 으로 · 한 번에 올린다).

    나머지 = 사전 캐릭터 중 번들 팩 · 4.5F 5,000 · 4.5F 추가 · 지금 V5 목록 · 사용자 썸네일 어디에도 없는 것(게시물 순).
    이미 그린 항목의 계정은 그대로 두고, 아직 안 그린 항목만 네 계정에 번갈아 다시 나눈다(레인 둘이 함께 내려가게).
    """
    import tempfile

    sys.path.insert(0, str(ROOT))
    from core.character_viewer_service import CharacterViewerService

    doc = json.loads((OUT_V5 / "_targets.json").read_text(encoding="utf-8"))
    targets = doc["targets"]
    analysis = json.loads((ROOT / "data/character_analysis.json").read_text(encoding="utf-8"))
    pack = set(json.loads((ROOT / "data/character_preview_thumbs.json").read_text(encoding="utf-8"))["thumbs"])
    survey = json.loads((ROOT / "docs/character_pool_survey_2026_10_19/char_gender_survey.json").read_text(encoding="utf-8"))
    covered = set(pack) | {t["key"] for t in targets}
    for folder in ("20261021_pack2", "20261022_pack45b"):
        covered |= {t["key"] for t in json.loads((OUT.parent / folder / "_targets.json").read_text(encoding="utf-8"))["targets"]}
    if USER_THUMBS.is_dir():
        for f in USER_THUMBS.glob("*.webp"):
            group, _, rest = f.stem.partition("__")
            covered.add(f"{group}::{rest.split('__')[0]}")
    rest = sorted(((int(d.get("danbooru_posts") or 0), g, n, d.get("gender") or "girl")
                   for g, cs in analysis.items() if isinstance(cs, dict)
                   for n, d in cs.items() if isinstance(d, dict) and f"{g}::{n}" not in covered), reverse=True)
    opts = {"hide_charname": False, "cosplay_enabled": False, "auto_copyright": True}
    rank = max((t["rank"] for t in targets), default=0)
    added = []
    with tempfile.TemporaryDirectory() as tmp:
        service = CharacterViewerService(ROOT, save_root=Path(tmp) / "save", thumbnail_root=Path(tmp) / "th")
        for posts, group, name, gender in rest:
            kind, line, ratio = _character_line(service, survey, group, name, gender, opts)
            rank += 1
            added.append({"rank": rank, "key": f"{group}::{name}", "posts": posts, "kind": kind,
                          "nonhuman_ratio": round(ratio, 3), "line": line})
    targets.extend(added)
    accounts = ["GN5", "BKN", "MYT", "0UY"]
    todo = [t for t in targets if not (OUT_V5 / f"{t['rank']:05d}.png").exists()]
    half = len(todo) // 2
    for i, t in enumerate(todo):
        # 레인 A = GN5 -> MYT · 레인 B = BKN -> 0UY - 앞 절반은 GN5 · BKN, 뒤 절반은 MYT · 0UY 가 번갈아.
        t["account"] = accounts[(2 if i >= half else 0) + (i % 2)]
    from collections import Counter
    doc.update({"count": len(targets), "assign_todo": dict(Counter(t["account"] for t in todo)), "targets": targets,
                "extended": f"+{len(added)} (나머지 전부 · 2026-10-22)"})
    (OUT_V5 / "_targets.json").write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    print("v5 extended +", len(added), "total", len(targets), "todo", len(todo), dict(Counter(t["account"] for t in todo)))


def redo_in_v5() -> None:
    """4.5 로 그린 것을 V5 로 다시(사용자 결정 2026-10-22: 품질 차이 - V5 로 통일).

    대상 = 4.5F 5,000(`20261021_pack2`) · 4.5F 추가 2,400(`20261022_pack45b`) · 번들 팩 3,000(`data/character_preview_thumbs.json`).
    V5 목록 뒤에 이어 붙인다(같은 팩에 담긴다). 4.5 원본은 그 폴더에 그대로 둔다. 새 항목은 MYT · 0UY 에 번갈아.
    번들 키는 확장 팩이 번들보다 먼저 보여야 바뀐다 - 서비스 우선순위(사용자 > 확장 > 번들)와 빌드 도구(번들 키 포함)가 맞춰져 있어야 한다.
    """
    import tempfile

    sys.path.insert(0, str(ROOT))
    from core.character_viewer_service import CharacterViewerService

    doc = json.loads((OUT_V5 / "_targets.json").read_text(encoding="utf-8"))
    targets = doc["targets"]
    have = {t["key"] for t in targets}
    analysis = json.loads((ROOT / "data/character_analysis.json").read_text(encoding="utf-8"))
    survey = json.loads((ROOT / "docs/character_pool_survey_2026_10_19/char_gender_survey.json").read_text(encoding="utf-8"))
    order = []
    for folder in ("20261021_pack2", "20261022_pack45b"):
        order += [t["key"] for t in json.loads((OUT.parent / folder / "_targets.json").read_text(encoding="utf-8"))["targets"]]
    bundled = list(json.loads((ROOT / "data/character_preview_thumbs.json").read_text(encoding="utf-8"))["thumbs"])
    # 번들(게시물 상위 3,000)을 먼저 - 사용자가 가장 자주 보는 캐릭터다.
    keys = [k for k in dict.fromkeys(bundled + order) if k not in have]
    user = set()
    if USER_THUMBS.is_dir():
        for f in USER_THUMBS.glob("*.webp"):
            group, _, rest = f.stem.partition("__")
            user.add(f"{group}::{rest.split('__')[0]}")
    opts = {"hide_charname": False, "cosplay_enabled": False, "auto_copyright": True}
    rank = max((t["rank"] for t in targets), default=0)
    added, skipped = [], []
    with tempfile.TemporaryDirectory() as tmp:
        service = CharacterViewerService(ROOT, save_root=Path(tmp) / "save", thumbnail_root=Path(tmp) / "th")
        for i, key in enumerate(keys):
            group, _, name = key.partition("::")
            data = (analysis.get(group) or {}).get(name)
            # 사용자 썸네일이 있어도 뺀다 **않는다** - 이 팩은 다른 사용자에게 간다(그들에게는 이 기계의 썸네일이 없다).
            if not isinstance(data, dict):
                skipped.append(key)
                continue
            kind, line, ratio = _character_line(service, survey, group, name, data.get("gender") or "girl", opts)
            rank += 1
            added.append({"rank": rank, "key": key, "posts": int(data.get("danbooru_posts") or 0), "kind": kind,
                          "nonhuman_ratio": round(ratio, 3), "line": line, "redo_from": "v4.5",
                          "account": ("MYT", "0UY")[len(added) % 2]})
    targets.extend(added)
    from collections import Counter
    doc.update({"count": len(targets), "targets": targets,
                "redo": f"+{len(added)} (4.5 -> V5 · 번들 포함 · 2026-10-22) · 뺌 {len(skipped)}"})
    (OUT_V5 / "_targets.json").write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    print("redo +", len(added), "skipped", len(skipped), skipped[:8], dict(Counter(t["account"] for t in added)),
          "total", len(targets))


def assign_v5(accounts: list[str]) -> None:
    """아직 안 그린 V5 항목을 `accounts` 에 번갈아 다시 나눈다(그린 것은 그대로).
    사용자 2026-10-22: GN5 · BKN 의 V5 사용량을 먼저 다 쓴다 -> 멈추면 남은 것을 MYT · 0UY 로."""
    doc = json.loads((OUT_V5 / "_targets.json").read_text(encoding="utf-8"))
    todo = [t for t in doc["targets"] if not (OUT_V5 / f"{t['rank']:05d}.png").exists()]
    for i, t in enumerate(todo):
        t["account"] = accounts[i % len(accounts)]
    from collections import Counter
    doc["assign_todo"] = dict(Counter(t["account"] for t in todo))
    (OUT_V5 / "_targets.json").write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    print("v5 assigned", len(todo), doc["assign_todo"])


def build_v5_targets() -> None:
    import tempfile

    sys.path.insert(0, str(ROOT))
    from core.character_viewer_service import CharacterViewerService

    src = json.loads((OUT / "_targets_v5.json").read_text(encoding="utf-8"))["targets"]
    survey = json.loads((ROOT / "docs/character_pool_survey_2026_10_19/char_gender_survey.json").read_text(encoding="utf-8"))
    have = set()
    if USER_THUMBS.is_dir():
        for f in USER_THUMBS.glob("*.webp"):
            group, _, rest = f.stem.partition("__")
            have.add(f"{group}::{rest.split('__')[0]}")
    opts = {"hide_charname": False, "cosplay_enabled": False, "auto_copyright": True}
    out, skipped = [], []
    with tempfile.TemporaryDirectory() as tmp:
        service = CharacterViewerService(ROOT, save_root=Path(tmp) / "save", thumbnail_root=Path(tmp) / "th")
        for item in src:
            if item["key"] in have:
                skipped.append(item["key"])
                continue
            group, name = item["key"].split("::", 1)
            kind, line, ratio = _character_line(service, survey, group, name, item.get("gender") or "girl", opts)
            out.append({"rank": len(out) + 1, "key": item["key"], "posts": item.get("posts"), "kind": kind,
                        "nonhuman_ratio": round(ratio, 3), "line": line})
    accounts = ["GN5", "BKN", "MYT", "0UY"]
    quarter = -(-len(out) // 4)
    for i, item in enumerate(out):
        item["account"] = accounts[min(3, i // quarter)]
    OUT_V5.mkdir(parents=True, exist_ok=True)
    from collections import Counter
    (OUT_V5 / "_targets.json").write_text(json.dumps({
        "note": "V5 몫 - NAID5F-medium 640x640 CFG 5 (사용자 지정 프롬프트 2026-10-22)", "count": len(out),
        "skipped_user_thumbnails": skipped, "assign": dict(Counter(t["account"] for t in out)), "targets": out,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print("v5 targets", len(out), "skipped", skipped, dict(Counter(t["kind"] for t in out)))


def build_targets(count: int) -> None:
    import tempfile

    sys.path.insert(0, str(ROOT))
    from core.character_viewer_service import CharacterViewerService

    analysis = json.loads((ROOT / "data/character_analysis.json").read_text(encoding="utf-8"))
    pack = set(json.loads((ROOT / "data/character_preview_thumbs.json").read_text(encoding="utf-8"))["thumbs"])
    survey = json.loads((ROOT / "docs/character_pool_survey_2026_10_19/char_gender_survey.json").read_text(encoding="utf-8"))
    debut_doc = json.loads((ROOT / "data/character_debut.json").read_text(encoding="utf-8"))
    debut, since = debut_doc["debut"], debut_doc["recent_since"]
    # V4.5F 는 2025 초까지의 태그만 안다(사용자 지시 2026-10-21) - 그 뒤 데뷔 · 개명(값 없음) · 모름은 V5F-medium small 몫.
    every = sorted(((int(d.get("danbooru_posts") or 0), g, n, d.get("gender") or "girl")
                    for g, cs in analysis.items() for n, d in cs.items() if f"{g}::{n}" not in pack), reverse=True)
    rows = [r for r in every if debut.get(r[2]) and debut[r[2]] < since][:count]
    later = [{"key": f"{g}::{n}", "posts": p, "gender": gd, "debut": debut.get(n)}
             for p, g, n, gd in every if not (debut.get(n) and debut[n] < since)]
    opts = {"hide_charname": False, "cosplay_enabled": False, "auto_copyright": True}
    out = []
    with tempfile.TemporaryDirectory() as tmp:
        service = CharacterViewerService(ROOT, save_root=Path(tmp) / "save", thumbnail_root=Path(tmp) / "th")
        for rank, (posts, group, name, gender) in enumerate(rows, 1):
            stats = survey.get(name) or {}
            ratio = (stats.get("no_humans", 0) / stats["rows"]) if stats.get("rows") else 0.0
            kind = "other" if ratio >= NONHUMAN_RATIO else ("boy" if gender == "boy" else "girl")
            line = str(service.build_prompt(group, name, "", opts, "NAI").get("character_prompt") or "").strip()
            parts = [p.strip() for p in line.split(",")]
            if parts and parts[0] in ("girl", "boy", "other"):
                parts = parts[1:]
            if kind != "girl":
                # 사전의 가슴 크기 · loli 치환은 여성 기준이다 - 남성 · 비인간에는 싣지 않는다(pikachu -> large breasts).
                parts = [p for p in parts if not p.endswith(("breasts", "chest")) and p != "young female"]
            line = ", ".join(p for p in parts if p)
            out.append({"rank": rank, "key": f"{group}::{name}", "posts": posts, "kind": kind,
                        "nonhuman_ratio": round(ratio, 3), "line": line})
    assign = {}
    for item in out:
        r = item["rank"]
        if r <= 2 * PER_ACCOUNT:
            item["account"] = "GN5" if r % 2 else "BKN"
        else:
            item["account"] = "MYT" if r % 2 else "0UY"
        assign[item["account"]] = assign.get(item["account"], 0) + 1
    OUT.mkdir(parents=True, exist_ok=True)
    _migrate_existing(out)
    TARGETS.write_text(json.dumps({"note": __doc__.splitlines()[0], "count": len(out), "assign": assign,
                                   "debut_before": since, "targets": out}, ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT / "_targets_v5.json").write_text(json.dumps({
        "note": f"V4.5F 밖(데뷔 {since} 이후 · 개명 · 모름) - V5F-medium small 로 따로 생성", "count": len(later),
        "targets": later}, ensure_ascii=False, indent=1), encoding="utf-8")
    from collections import Counter
    print("targets", len(out), dict(Counter(t["kind"] for t in out)), assign, "->", TARGETS)
    print("v5 later", len(later))


def _migrate_existing(targets: list[dict]) -> None:
    """번호가 바뀌어도 이미 만든 그림을 버리지 않는다: 키로 새 번호에 옮기고, 새 목록 밖(V4.5 로 그리면 안 되는
    캐릭터)은 `_excluded_v45/` 로 뺀다. 매니페스트도 같이 고친다."""
    by_key = {t["key"]: t for t in targets}
    excluded = OUT / "_excluded_v45"
    stage = OUT / "_migrate"
    moves = []
    for mf in sorted(OUT.glob("manifest_*.jsonl")):
        kept = []
        for line in mf.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            src = OUT / row["file"]
            if not src.exists():
                continue
            target = by_key.get(row["key"])
            if target is None:
                excluded.mkdir(exist_ok=True)
                moves.append((src, excluded / src.name, None))
                (excluded / "manifest.jsonl").open("a", encoding="utf-8").write(json.dumps(row, ensure_ascii=False) + "\n")
                continue
            row["old_file"], row["rank"], row["file"] = row["file"], target["rank"], f"{target['rank']:05d}.png"
            moves.append((src, OUT / row["file"], row))
            kept.append(row)
        mf.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in kept), encoding="utf-8")
    # 번호가 서로 엇갈려도 덮지 않게 한 번 대기 폴더를 거친다.
    stage.mkdir(exist_ok=True)
    for i, (src, _dst, _row) in enumerate(moves):
        src.replace(stage / f"{i}.png")
    for i, (_src, dst, _row) in enumerate(moves):
        (stage / f"{i}.png").replace(dst)
    stage.rmdir()
    print("migrated", sum(1 for m in moves if m[2] is not None), "excluded", sum(1 for m in moves if m[2] is None))


def _load_client():
    sys.path.insert(0, str(TOOL))
    from core import nai_client  # type: ignore
    return nai_client


def _payload_v5(client, prompt: str, seed: int) -> dict:
    payload = client.build_payload(prompt=prompt, negative_prompt="", model="NAID5F", width=V5_WIDTH,
                                   height=V5_HEIGHT, steps=V5_STEPS, cfg_scale=V5_CFG, cfg_rescale=0.0,
                                   sampler="k_euler_ancestral", noise_schedule="karras", seed=seed)
    # 썸네일 도구의 클라이언트는 medium 을 모른다 - 같은 V5 모양(멀티파트)에 모델 이름만 바꾼다.
    payload["model"] = V5_API_MODEL
    payload["parameters"].pop("skip_cfg_above_sigma", None)      # medium 은 추가 파라미터를 못 받는다(사용자)
    return payload


def _payload(client, prompt: str, seed: int) -> dict:
    payload = client.build_payload(prompt=prompt, negative_prompt=NEGATIVE, model="NAID4.5F", width=WIDTH,
                                   height=HEIGHT, steps=STEPS, cfg_scale=5.4, cfg_rescale=0.28,
                                   sampler="k_euler_ancestral", noise_schedule="karras", seed=seed)
    params = payload["parameters"]
    params["skip_cfg_above_sigma"] = 58.0          # 원본 메타데이터 값
    params["deliberate_euler_ancestral_bug"] = True
    params["prefer_brownian"] = True
    return payload


def _log(fp, **row) -> None:
    row["t"] = time.strftime("%Y-%m-%d %H:%M:%S")
    fp.write(json.dumps(row, ensure_ascii=False) + "\n")
    fp.flush()


def _anlas(client, token: str):
    try:
        return client.fetch_subscription(token).get("anlas")
    except Exception:
        return None


def _v5_usage(client, token: str):
    try:
        usage = client.fetch_subscription(token).get("usage") or {}
        return None if usage.get("is_negative") else int(usage.get("percent"))
    except Exception:
        return None


def _claim(out_dir: Path, rank: int):
    """이 장을 잡는다(원자적 생성). 남이 잡았으면 None - 오래된 표시는 죽은 프로세스의 것이라 가져간다."""
    claim = out_dir / f"{rank:05d}.claim"
    for _ in range(2):
        try:
            fd = os.open(claim, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            return claim
        except FileExistsError:
            try:
                if time.time() - claim.stat().st_mtime < CLAIM_STALE_SECONDS:
                    return None
                claim.unlink(missing_ok=True)
            except FileNotFoundError:
                continue
    return None


def run_account(client, label: str, items: list[dict], logf, v5: bool = False, pool: bool = False) -> str:
    token = (TOOL / ACCOUNTS[label]).read_text(encoding="utf-8").strip()
    out_dir = OUT_V5 if v5 else OUT
    if not client.is_free_generation(*((V5_STEPS, V5_WIDTH, V5_HEIGHT) if v5 else (STEPS, WIDTH, HEIGHT))):
        raise SystemExit("not free band - refusing")
    start_anlas = _anlas(client, token)
    if v5:
        usage = _v5_usage(client, token)
        _log(logf, ev="v5_usage", account=label, percent=usage)
        if V5_USAGE_FLOOR is not None and usage is not None and usage <= V5_USAGE_FLOOR:
            print(f"[{label}] V5 usage {usage}% - nothing to spend, skipping", flush=True)
            return "usage_low"
    _log(logf, ev="account_start", account=label, todo=len(items), anlas=start_anlas)
    print(f"[{label}] start todo={len(items)} anlas={start_anlas}", flush=True)
    manifest = (out_dir / f"manifest_{label}.jsonl").open("a", encoding="utf-8")
    done = 0
    # 할당량 소진 감지(사용자 2026-10-22: 4.5F 버킷 = 1,200장 · 시간당 60장 회복). 소진되면 장당 시간이 분 단위로 늘어난다 -
    # 최근 10장 평균이 SLOW_SECONDS 를 넘으면 그 계정을 멈추고(bucket_empty) 남은 몫은 다른 계정에 다시 나눈다.
    recent: list[float] = []
    give_ups = 0                 # 잇달아 포기한 수 - V5 사용량이 바닥나면 모든 요청이 실패한다(그때 재시도로 시간을 태우지 않는다)
    for item in items:
        if (out_dir / "STOP").exists():
            _log(logf, ev="stop_file", account=label)
            return "stopped"
        path = out_dir / f"{item['rank']:05d}.png"
        if path.exists() and path.stat().st_size > 0:
            continue
        claim = None
        if pool:
            claim = _claim(out_dir, item["rank"])
            if claim is None:
                continue                        # 다른 계정이 그리는 중
        began_item = time.time()
        prompt = (TEMPLATE_V5 if v5 else TEMPLATE).format(head="1" + item["kind"], line=item["line"])
        seed = random.randint(1, 9_999_999_999)
        payload = (_payload_v5 if v5 else _payload)(client, prompt, seed)
        png = None
        for attempt in range(1, 6):
            began = time.time()
            try:
                # medium 은 클라이언트 표에 없다 - 전송 모양(V5 = 멀티파트)은 NAID5F 로 고른다(모델 이름은 payload 그대로).
                png = client.generate(payload, token, timeout=120, model="NAID5F" if v5 else None)
                break
            except Exception as exc:  # noqa: BLE001
                msg = str(exc)[:200]
                wait = 20 if "429" in msg else 5 * attempt
                _log(logf, ev="retry", account=label, rank=item["rank"], attempt=attempt, err=msg, took=round(time.time() - began, 1))
                print(f"[{label}] #{item['rank']} retry {attempt}: {msg[:90]}", flush=True)
                time.sleep(wait)
        if png is None:
            if claim is not None:
                claim.unlink(missing_ok=True)
            _log(logf, ev="give_up", account=label, rank=item["rank"])
            give_ups += 1
            if give_ups >= 5:
                _log(logf, ev="give_up_streak", account=label, done=done)
                print(f"[{label}] 5 give-ups in a row - quota or service problem, stopping this account", flush=True)
                return "give_up_streak"
            continue
        give_ups = 0
        tmp = path.with_suffix(".part")
        tmp.write_bytes(png)
        tmp.replace(path)
        if claim is not None:
            claim.unlink(missing_ok=True)
        done += 1
        manifest.write(json.dumps({"rank": item["rank"], "key": item["key"], "file": path.name, "seed": seed,
                                   "kind": item["kind"], "line": item["line"], "account": label,
                                   "t": time.strftime("%Y-%m-%d %H:%M:%S")}, ensure_ascii=False) + "\n")
        manifest.flush()
        if done % 25 == 0:
            now = _anlas(client, token)
            _log(logf, ev="progress", account=label, done=done, anlas=now)
            print(f"[{label}] done {done} anlas={now}", flush=True)
            if v5:
                usage = _v5_usage(client, token)
                _log(logf, ev="v5_usage", account=label, done=done, percent=usage)
                print(f"[{label}] v5 usage {usage}%", flush=True)
                if V5_USAGE_FLOOR is not None and usage is not None and usage <= V5_USAGE_FLOOR:
                    print(f"[{label}] V5 usage {usage}% <= {V5_USAGE_FLOOR}% - stopping this account", flush=True)
                    return "usage_low"
            if start_anlas is not None and now is not None and now < start_anlas:
                _log(logf, ev="anlas_dropped", account=label, start=start_anlas, now=now)
                print(f"[{label}] ANLAS DROPPED {start_anlas} -> {now} - stopping this account", flush=True)
                return "anlas_dropped"
        recent = (recent + [time.time() - began_item])[-10:]
        if len(recent) == 10 and sum(recent) / 10 > SLOW_SECONDS:
            _log(logf, ev="bucket_empty", account=label, done=done, avg=round(sum(recent) / 10, 1))
            print(f"[{label}] SLOW avg {sum(recent) / 10:.0f}s - quota likely empty, stopping this account", flush=True)
            return "bucket_empty"
        time.sleep(1.0)
    _log(logf, ev="account_done", account=label, done=done, anlas=_anlas(client, token))
    print(f"[{label}] finished new={done}", flush=True)
    return "done"


def run_lane(lane: str, limit: int | None, v5: bool = False, account: str = "", pool: bool = False) -> None:
    client = _load_client()
    out_dir = OUT_V5 if v5 else OUT
    data = json.loads((out_dir / "_targets.json").read_text(encoding="utf-8"))
    # --account = 계정 하나만(사용자 지시 2026-10-22: 4계정 동시). 같은 계정을 두 프로세스로 돌리지 말 것(429 Concurrent).
    logf = (out_dir / f"run_{account or 'lane' + lane}.jsonl").open("a", encoding="utf-8")
    for label in ([account] if account else LANES[lane]):
        # --any = 공용 목록(배정 무시 · 순번대로 · 잡기 표시로 겹치지 않게) - 사용자 2026-10-22: 계정마다 한도까지.
        items = (sorted(data["targets"], key=lambda t: t["rank"]) if pool
                 else [t for t in data["targets"] if t["account"] == label])
        if limit:
            items = items[:limit]
        result = run_account(client, label, items, logf, v5=v5, pool=pool)
        if result == "stopped":
            break


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("targets")
    t.add_argument("--count", type=int, default=5000)
    r = sub.add_parser("run")
    r.add_argument("--lane", choices=sorted(LANES), default="A")
    r.add_argument("--account", choices=sorted(ACCOUNTS), default="", help="이 계정 하나만")
    r.add_argument("--any", action="store_true", help="공용 목록 - 배정 무시하고 아무도 안 잡은 장을 그린다")
    r.add_argument("--limit", type=int, default=None, help="계정마다 앞에서 N 장만(시험)")
    r.add_argument("--v5", action="store_true", help="V5 몫(NAID5F-medium · 20261022_pack_v5)")
    r.add_argument("--out", default="", help="4.5F 출력 폴더 이름(기본 20261021_pack2)")
    sub.add_parser("v5-targets")
    sub.add_parser("v5-extend")
    sub.add_parser("v5-redo")
    asg = sub.add_parser("v5-assign")
    asg.add_argument("--accounts", required=True, help="쉼표로 - 예: GN5,BKN")
    m = sub.add_parser("more-targets")
    m.add_argument("--count", type=int, default=2400)
    m.add_argument("--out", required=True)
    a = ap.parse_args()
    if getattr(a, "out", "") and a.cmd == "run":
        global OUT
        OUT = OUT.parent / a.out
    if a.cmd == "more-targets":
        build_more_targets(a.count, a.out)
    elif a.cmd == "targets":
        build_targets(a.count)
    elif a.cmd == "v5-targets":
        build_v5_targets()
    elif a.cmd == "v5-extend":
        extend_v5_targets()
    elif a.cmd == "v5-redo":
        redo_in_v5()
    elif a.cmd == "v5-assign":
        assign_v5([x.strip() for x in a.accounts.split(",") if x.strip()])
    else:
        run_lane(a.lane, a.limit, v5=a.v5, account=a.account, pool=a.any)


if __name__ == "__main__":
    main()
