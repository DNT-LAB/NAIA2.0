# -*- coding: utf-8 -*-
"""부팅 청소: 저장하지 않은 것만, 최신 5개만 남는가."""
import io
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.interactive_assets_service import InteractiveAssetsService  # noqa: E402


class Ctx:
    def __init__(self, r):
        self._root = r

    def _save_path(self, n):
        p = self._root / n
        p.mkdir(parents=True, exist_ok=True)
        return p


def G(bg):
    return {"slots": {"background": [bg]}, "composition": {}, "composition_tags": [],
            "free_text": "", "rating": {"mode": "single", "picks": []},
            "fast_negative": ""}


def CH(pose):
    return [{"fields": {"자세": [pose]}, "neg": {}, "gender": "female",
             "alt": [], "gaze": [], "fast": {"p": "", "n": ""}}]


fails = []


def ck(label, got, want):
    ok = got == want
    print(("  ok    " if ok else "  FAIL  ") + label
          + ("" if ok else "   (%r != %r)" % (got, want)))
    if not ok:
        fails.append(label)


with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    svc = InteractiveAssetsService(Ctx(root))

    scenes = [svc.record_scene(G("bg%d" % i), CH("pose%d" % i)) for i in range(12)]
    snaps = []
    for i in range(12):
        snaps.extend(svc.record(CH("snap%d" % i)))

    saved = scenes[0]["id"]
    svc.save_scene(saved, "지킬 씬")
    fav_scene = scenes[1]["id"]
    svc.toggle_favorite("scene", fav_scene)
    fav_snap = snaps[0]["id"]
    svc.toggle_favorite("snapshot", fav_snap)

    print("[청소 전]", len(svc.load_scene_index()), "씬 /", len(svc.load_index()), "에셋")
    out = svc.sweep_unsaved(keep=5)
    print("[지운 수]", out)

    sc = svc.load_scene_index()
    sn = svc.load_index()
    sc_ids = [r["id"] for r in sc]
    sn_ids = [r["id"] for r in sn]

    ck("씬: 지킨 것 2 + 최신 5 = 7", len(sc), 7)
    ck("씬: 저장한 것이 남는다", saved in sc_ids, True)
    ck("씬: 즐겨찾기가 남는다", fav_scene in sc_ids, True)
    ck("씬: 남은 것은 최신 5개", [r["id"] for r in scenes[-5:]],
       [i for i in sc_ids if i not in (saved, fav_scene)])
    ck("씬: 오래된 것은 사라졌다", scenes[5]["id"] in sc_ids, False)
    ck("에셋: 즐겨찾기 1 + 최신 5 = 6", len(sn), 6)
    ck("에셋: 즐겨찾기가 남는다", fav_snap in sn_ids, True)

    # 본문 파일도 함께 지워졌는가 (인덱스만 줄고 파일이 남으면 되짚기가 되살린다)
    bodies = {p.stem for p in (root / "interactive_scene").glob("*.json")
              if p.stem not in ("index", "folders")}
    ck("씬 본문도 지워졌다", bodies, set(sc_ids))
    sbodies = {p.stem for p in (root / "interactive_snapshot").glob("*.json")
               if p.stem != "index"}
    ck("에셋 본문도 지워졌다", sbodies, set(sn_ids))

    # 되짚기(인덱스 파손)로도 되살아나지 않아야 한다
    (root / "interactive_scene" / "index.json").write_text("{ broken", encoding="utf-8")
    ck("인덱스를 깨도 지운 것은 안 돌아온다", len(svc.load_scene_index()), 7)

    # 두 번 돌려도 더 지우지 않는다
    again = svc.sweep_unsaved(keep=5)
    ck("두 번째 청소는 할 일이 없다", again, {"snapshots": 0, "scenes": 0})

    # 즐겨찾기를 못 읽으면 아무것도 안 지운다
    svc2 = InteractiveAssetsService(Ctx(root))
    (root / "interactive_favorite" / "favorites.json").write_text("{ broken",
                                                                 encoding="utf-8")
    before = len(svc2.load_scene_index())
    svc2.sweep_unsaved(keep=0)
    ck("즐겨찾기 못 읽으면 건너뛴다", len(svc2.load_scene_index()), before)

print()
print("전부 통과" if not fails else "실패 %d건: %s" % (len(fails), fails))
sys.exit(1 if fails else 0)
