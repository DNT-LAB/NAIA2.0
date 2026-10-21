# -*- coding: utf-8 -*-
"""캐릭터 사전(`data/character_analysis.json`)의 비인간 캐릭터를 `gender: "other"` 로 표시한다 (2026-10-21 · 개발 전용).

잣대 = 캐릭터 재조사(10-19)와 같다: 태그 코퍼스에서 그 캐릭터가 나온 행 중 `no humans` 비율 >= 0.3.
근거 수치 = `docs/character_pool_survey_2026_10_19/char_gender_survey.json`(rows · no_humans · girl_solo · boy_solo).
앱은 이 값으로 캐릭터 머리말을 girl / boy / other 로 고른다(`CharacterViewerService.build_prompt`).

    python tools/mark_nonhuman_characters.py            # 바꿀 목록만
    python tools/mark_nonhuman_characters.py --write    # 파일에 쓴다

파일 형식(들여쓰기 2 · CRLF · ASCII · 끝 줄바꿈 없음)을 그대로 지킨다 - 바뀐 값 외에는 바이트가 같다.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ANALYSIS = ROOT / "data" / "character_analysis.json"
SURVEY = ROOT / "docs" / "character_pool_survey_2026_10_19" / "char_gender_survey.json"
RATIO = 0.3


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()
    raw = ANALYSIS.read_bytes()
    data = json.loads(raw)
    if json.dumps(data, ensure_ascii=True, indent=2).replace("\n", "\r\n").encode("utf-8") != raw:
        raise SystemExit("형식이 예상과 다르다 - 쓰지 않는다")
    survey = json.loads(SURVEY.read_text(encoding="utf-8"))
    changed = []
    for group, chars in data.items():
        for name, entry in chars.items():
            stats = survey.get(name) or {}
            if not stats.get("rows"):
                continue
            ratio = stats.get("no_humans", 0) / stats["rows"]
            if ratio >= RATIO and entry.get("gender") != "other":
                changed.append((group, name, entry.get("gender"), round(ratio, 3)))
                entry["gender"] = "other"
    for row in changed:
        print(row)
    print("changed", len(changed))
    if args.write and changed:
        ANALYSIS.write_bytes(json.dumps(data, ensure_ascii=True, indent=2).replace("\n", "\r\n").encode("utf-8"))
        print("written", ANALYSIS)


if __name__ == "__main__":
    main()
