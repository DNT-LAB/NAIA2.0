# -*- coding: utf-8 -*-
"""런타임이 읽는 데이터가 릴리즈에 실리는지 검사한다.

## 왜 필요한가

배포판은 **아무것도 빌드하지 않는다.** 그런데 런타임 코드가 빌드 입력물
(`wildcards/**` — 릴리즈 페이로드의 금지 패턴)을 직접 읽는 자리가 있었다:

    core/interactive_tag_dependency.py -> wildcards/thumb/*.txt

배포판에는 그 폴더가 없으니 '필요한 것'(전제조건)이 **조용히 빈 채로** 돌았다.
예외를 삼키는 구조라 에러도 안 났다(2026-08-04 실측: 개발 [dress, sweater] vs
배포판 [] ). 같은 이유로 `data/interactive_preset_facts.json` 은 아예 매니페스트에
없어 실리지 않았다.

그래서 **런타임이 여는 저장소 경로**를 모아 릴리즈 매니페스트와 대조한다.
새 데이터 의존이 생기면 여기서 걸린다.

## 쓰는 법

    python tools/check_runtime_data_shipped.py
    python tools/check_runtime_data_shipped.py --json

실려야 하는데 매니페스트에 없으면 exit 1.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "release_assets" / "manifests" / "release_include_exclude_draft.json"
SCAN_DIRS = ("core", "app/backend")

# 런타임 코드가 여는 저장소 상대 경로를 뽑는 패턴.
_PAT = re.compile(r'(?:repo_root|_ROOT|REPO_ROOT|ROOT)\s*/\s*"([^"]+)"'
                  r'(?:\s*/\s*"([^"]+)")?')

# 위 패턴은 루트 식별자 **바로 뒤**에 리터럴이 붙은 형태만 잡는다. 상대 경로를
# 모듈 상수로 빼고 `Path(repo_root) / CONST` 로 조립하면 통째로 샌다 — 실제로
# `data/interactive_clothing_harmony.json` 이 그렇게 새서 배포판에서 조언이
# 통째로 죽어 있었다(2026-08-13). 그래서 `Path("a") / "b" / ...` 형태도 잡는다.
_PAT_CONST = re.compile(r'Path\(\s*"([^"]+)"\s*\)((?:\s*/\s*"[^"]+")*)')
_SEG = re.compile(r'"([^"]+)"')

# 배포판에 없어도 되는 것 — 이유를 반드시 적는다.
ALLOWED_MISSING = {
    "artist_thumb": "런타임 경로로 덮어쓴다(legacy_* 는 폴백)",
    "wildcards": "런타임 와일드카드는 user-data 소관",
    "wildcards/thumb": "축 소속은 data/interactive_axis_tags.json 으로 구워 실린다",
    "ui/interactive": "레거시 최후 폴백. 실경로는 data/interactive_tags.json",
    "ui/event_preset": "레거시 폴백",
    "data/event_preset": "런타임 다운로드",
    "data/event_preset_thumbnail": "런타임 다운로드",
    "data/conditional_presets_bundled": "개발 저장소에도 없는 죽은 기본값",
    "save/conditional_presets": "사용자 저장 폴더 — 필요 시 생성",
    "path": "문자열 파싱 오탐",
    "core": "코드 디렉터리",
    "data": "디렉터리 자체",
    ".": "문자열 파싱 오탐 — 로그 경로 최후 폴백(cwd)",
    "data/tags": "런타임 다운로드 (매니페스트 exclude: local_downloaded_assets)",
    "data/tag_combo": "런타임 다운로드 — 조합 모델 번들 179MB. Interactive 를 열 때 "
                      "core/tag_combo/download.py 가 배경으로 받는다. 릴리즈 zip 에 "
                      "넣으면 289MB 가 468MB 가 된다",
    "output": "사용자 출력 폴더 — 런타임 생성",
    "save": "사용자 저장 폴더 — 런타임 생성",
}


def shipped_patterns() -> list[str]:
    d = json.loads(MANIFEST.read_text(encoding="utf-8"))
    out: list[str] = []
    for group in d.get("include", {}).values():
        out.extend(group)
    return out


def is_shipped(rel: str, patterns: list[str]) -> bool:
    for pat in patterns:
        if fnmatch.fnmatch(rel, pat) or fnmatch.fnmatch(rel, pat.rstrip("*").rstrip("/") + "/*"):
            return True
        # `data/tag_index/**` 는 폴더 자체(`data/tag_index`)도 덮는 것으로 본다 —
        # 런타임은 폴더를 열고 그 안을 훑기 때문이다.
        if pat.endswith("/**") and (rel == pat[:-3] or rel.startswith(pat[:-3] + "/")):
            return True
        if rel == pat:
            return True
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    patterns = shipped_patterns()
    found: dict[str, list[str]] = {}
    for d in SCAN_DIRS:
        for p in (ROOT / d).rglob("*.py"):
            for i, line in enumerate(p.read_text(encoding="utf-8", errors="replace")
                                     .splitlines(), 1):
                if line.lstrip().startswith("#"):
                    continue
                where = f"{p.relative_to(ROOT).as_posix()}:{i}"
                for m in _PAT.finditer(line):
                    rel = m.group(1) + ("/" + m.group(2) if m.group(2) else "")
                    found.setdefault(rel, []).append(where)
                for m in _PAT_CONST.finditer(line):
                    segs = [m.group(1), *_SEG.findall(m.group(2) or "")]
                    found.setdefault("/".join(segs), []).append(where)

    bad = []
    for rel in sorted(found):
        if rel in ALLOWED_MISSING or is_shipped(rel, patterns):
            continue
        if not (ROOT / rel).exists():      # 저장소에도 없으면 죽은 경로다
            continue
        bad.append((rel, found[rel][0]))

    if args.json:
        print(json.dumps({"referenced": {k: v[0] for k, v in sorted(found.items())},
                          "missing": [r for r, _ in bad]}, ensure_ascii=False, indent=1))
    else:
        print(f"런타임이 여는 저장소 경로 {len(found)}개 / 매니페스트 패턴 {len(patterns)}개")
        for rel, where in bad:
            print(f"  !! 릴리즈에 안 실린다: {rel}   ({where})")
        if bad:
            print("\n실어야 하면 release_include_exclude_draft.json 에 넣고,")
            print("빌드 입력물이라면 파생물을 data/ 로 구워서 런타임이 그걸 읽게 하라.")
            print("배포판에 없어도 되는 것이면 ALLOWED_MISSING 에 사유와 함께 적어라.")
        else:
            print("런타임 데이터 의존이 전부 릴리즈에 실린다.")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
