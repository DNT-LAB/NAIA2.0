# -*- coding: utf-8 -*-
"""씬(이벤트) 기록 저장소 검증.

캐릭터 스냅샷과 **단위가 다르다**: 생성 1회 = 캐릭터 N장이지만 씬은 1장이다.
같은 씬이면 새로 쌓지 않고 갱신하며, 갱신된 것은 목록 **끝으로** 옮겨진다
(자리가 곧 최신순이라 프루닝이 앞쪽부터 지운다).

해시는 **복원이 실제로 적용하는 것만** 본다 — 씬 값 전부 + 프론트가 정체성을
걷어낸 뒤 보낸 캐릭터의 '상황'. 그래야 되돌리면 똑같아지는 두 기록이 한 장이 된다.

캐릭터 쪽 저장소를 건드리지 않는지도 함께 본다(트리가 다르다).
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.interactive_assets_service import (  # noqa: E402
    SNAPSHOT_LIMIT,
    InteractiveAssetsService,
)

FAILED: list[str] = []


def check(label: str, got, want) -> None:
    ok = got == want
    if not ok:
        FAILED.append(label)
    print(("  ok    " if ok else "  FAIL  ") + label
          + ("" if ok else "\n          got  = %r\n          want = %r" % (got, want)))


class FakeContext:
    def __init__(self, root: Path) -> None:
        self._root = root

    def _save_path(self, name: str) -> Path:
        p = self._root / name
        p.mkdir(parents=True, exist_ok=True)
        return p


def globals_for(background: str, free: str = "") -> dict:
    return {
        "slots": {"background": [background], "fx": []},
        "composition": {"angle": "eye level"},
        "composition_tags": ["wide shot"],
        "free_text": free,
        "rating": {"mode": "single", "picks": ["none"]},
        "fast_negative": "",
    }


def situation(pose: str) -> list[dict]:
    """프론트가 정체성을 걷어낸 뒤 보내는 모양 — 이름/머리/눈얼굴이 없다."""
    return [{"fields": {"자세": [pose], "의상": ["school uniform"]},
             "neg": {}, "gender": "female", "alt": [], "gaze": [],
             "fast": {"p": "", "n": ""}}]


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        svc = InteractiveAssetsService(FakeContext(root))

        # 1. 생성 1회 = 씬 1장
        a = svc.record_scene(globals_for("forest"), situation("sitting"))
        check("생성 한 번에 씬 카드 하나", len(svc.load_scene_index()), 1)
        check("id 는 e 로 시작한다", str(a["id"])[:1], "e")

        # 2. 같은 씬은 새로 쌓지 않는다
        again = svc.record_scene(globals_for("forest"), situation("sitting"))
        check("같은 씬은 갱신", len(svc.load_scene_index()), 1)
        check("같은 씬이면 같은 id", again["id"], a["id"])

        # 3. 씬 값이 다르면 새 카드
        b = svc.record_scene(globals_for("city"), situation("sitting"))
        check("배경이 다르면 새 카드", len(svc.load_scene_index()), 2)

        # 4. 캐릭터의 '상황'이 다르면 새 카드
        svc.record_scene(globals_for("forest"), situation("standing"))
        check("자세가 다르면 새 카드", len(svc.load_scene_index()), 3)

        # 5. 갱신된 것이 목록 끝으로 간다(자리가 최신순)
        svc.record_scene(globals_for("forest"), situation("sitting"))
        check("갱신본이 맨 뒤", svc.load_scene_index()[-1]["id"], a["id"])

        # 6. 본문이 자기 완결이다 — 씬 값과 상황을 모두 담는다
        body = svc.load_scene_body(a["id"])
        check("본문에 씬 값", (body or {}).get("globals", {}).get("slots", {}).get("background"),
              ["forest"])
        check("본문에 캐릭터 상황",
              (body or {}).get("chars", [{}])[0].get("fields", {}).get("자세"), ["sitting"])
        check("본문에 정체성이 없다",
              "캐릭터" in ((body or {}).get("chars", [{}])[0].get("fields") or {}), False)

        # 7. 캐릭터 저장소를 건드리지 않는다
        check("캐릭터 인덱스는 비어 있다", svc.load_index(), [])
        check("씬 트리가 따로 있다", (root / "interactive_scene" / "index.json").exists(), True)

        # 8. 삭제
        check("삭제", svc.delete_scene(b["id"]), True)
        check("두 번 눌러도 조용하다", svc.delete_scene(b["id"]), False)
        check("본문도 사라진다", (root / "interactive_scene" / f"{b['id']}.json").exists(), False)

        # 9. 즐겨찾기 대상이 된다 + 프루닝에서 보호된다
        keep = svc.load_scene_index()[0]["id"]
        check("씬을 즐겨찾기로", svc.toggle_favorite("scene", keep), True)
        for i in range(SNAPSHOT_LIMIT + 5):
            svc.record_scene(globals_for("bulk-%d" % i), situation("sitting"))
        rows = svc.load_scene_index()
        check("한도를 넘지 않는다", len(rows) <= SNAPSHOT_LIMIT, True)
        check("즐겨찾기는 살아남는다", any(r["id"] == keep for r in rows), True)

        # 10. 인덱스가 깨져도 본문에서 되짚는다
        idx = root / "interactive_scene" / "index.json"
        idx.write_text("{ broken", encoding="utf-8")
        rebuilt = svc.load_scene_index()
        check("손상 인덱스를 본문에서 복구", len(rebuilt) > 0, True)
        check("손상본을 옆으로 치운다",
              any(p.suffix == ".bak" or ".bak" in p.name
                  for p in (root / "interactive_scene").iterdir()), True)

    print()
    if FAILED:
        print("실패 %d건: %s" % (len(FAILED), ", ".join(FAILED)))
        return 1
    print("전부 통과")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
