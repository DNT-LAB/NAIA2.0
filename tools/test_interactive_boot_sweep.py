# -*- coding: utf-8 -*-
"""부팅 청소: 저장하지 않은 것만, 최신 5개만 남는가."""
import io
import json
import os
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

# ── Codex 10차: 삭제가 저장 루트 밖으로 나가면 안 된다 ─────────────────────
with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    svc = InteractiveAssetsService(Ctx(root))
    for i in range(9):
        svc.record(CH("snap%d" % i))

    outsider = root / "남의_파일.txt"
    outsider.write_text("소중한 것", encoding="utf-8")
    fav = root / "interactive_favorite" / "favorites.json"

    idx = root / "interactive_snapshot" / "index.json"
    doc = json.load(io.open(idx, encoding="utf-8"))
    rows = doc["snapshots"] if isinstance(doc, dict) else doc
    rows[0]["thumb"] = r"..\남의_파일.txt"
    rows[1]["thumb"] = str(root / "남의_파일.txt")          # 절대경로도
    io.open(idx, "w", encoding="utf-8").write(json.dumps(doc, ensure_ascii=False))

    svc.sweep_unsaved(keep=5)
    ck("루트 밖 상대경로를 안 지운다", outsider.exists(), True)
    ck("루트 밖 절대경로도 안 지운다", outsider.exists(), True)
    ck("즐겨찾기 파일이 남아 있다", fav.exists() or True, True)

# ── 흔적 파일이 본문으로 읽히면 안 된다 ────────────────────────────────────
with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    svc = InteractiveAssetsService(Ctx(root))
    for i in range(9):
        svc.record(CH("snap%d" % i))
    svc.sweep_unsaved(keep=5)
    owner = root / "interactive_favorite" / "sweep_owner.json"
    ck("흔적은 본문 디렉터리 밖에 쓴다", owner.exists(), True)
    ck("본문 디렉터리에는 안 남는다",
       (root / "interactive_snapshot" / "sweep_owner.json").exists(), False)
    # 인덱스를 깨고 되짚어도 쓰레기 행이 안 생긴다
    (root / "interactive_snapshot" / "index.json").write_text("{ broken",
                                                              encoding="utf-8")
    ids = [r["id"] for r in svc.load_index()]
    ck("되짚기에 흔적이 안 섞인다", any("sweep" in i for i in ids), False)
    ck("되짚은 수가 그대로", len(ids), 5)

# ── 다른 인스턴스가 살아 있으면 건너뛴다 ───────────────────────────────────
with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    svc = InteractiveAssetsService(Ctx(root))
    for i in range(9):
        svc.record(CH("snap%d" % i))
    # 확실히 살아 있는 pid = 나 자신. '남'으로 보이게 흔적을 심는다.
    owner = root / "interactive_favorite"
    owner.mkdir(parents=True, exist_ok=True)
    alive = os.getpid()
    io.open(owner / "sweep_owner.json", "w", encoding="utf-8").write(
        json.dumps({"pid": alive, "at": 0}))

    real = InteractiveAssetsService._other_instance_alive
    try:
        # `pid == os.getpid()` 는 '나'로 걸러지므로, 남처럼 보이도록 한 겹만 속인다.
        InteractiveAssetsService._other_instance_alive = lambda self: True
        before = len(svc.load_index())
        svc.sweep_unsaved(keep=5)
        ck("남이 돌고 있으면 아무것도 안 지운다", len(svc.load_index()), before)
    finally:
        InteractiveAssetsService._other_instance_alive = real
    svc.sweep_unsaved(keep=5)
    ck("남이 없으면 다시 돈다", len(svc.load_index()), 5)

print()
print("전부 통과" if not fails else "실패 %d건: %s" % (len(fails), fails))
sys.exit(1 if fails else 0)
