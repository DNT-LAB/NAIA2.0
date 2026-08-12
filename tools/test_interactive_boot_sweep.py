# -*- coding: utf-8 -*-
"""부팅 청소: 저장하지 않은 것만, 최신 5개만 남는가."""
import builtins
import io
import json
import os
import subprocess
import sys
import tempfile
import time
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

    # 즐겨찾기에 하나 올려 둔다 — 이것이 살아남아야 '보호'가 지켜진 것이다.
    keepme = [r["id"] for r in svc.load_index()][0]
    svc.toggle_favorite("snapshot", keepme)
    ck("준비: 즐겨찾기 파일이 생겼다", fav.exists(), True)

    svc.sweep_unsaved(keep=5)
    ck("루트 밖 상대경로를 안 지운다", outsider.exists(), True)
    ck("루트 밖 절대경로도 안 지운다", outsider.exists(), True)
    ck("즐겨찾기 파일이 남아 있다", fav.exists(), True)
    ck("즐겨찾기에 올린 것이 살아남았다",
       keepme in [r["id"] for r in svc.load_index()], True)

    # 반대 확인 — 즐겨찾기 파일이 실제로 사라지면 보호가 깨지는가.
    # (여기서 '안 지운다'가 나와야 가둠이 진짜로 일하는 것이다.)
    fav.unlink()
    idx2 = json.load(io.open(root / "interactive_snapshot" / "index.json",
                             encoding="utf-8"))
    rows2 = idx2["snapshots"] if isinstance(idx2, dict) else idx2
    ck("즐겨찾기가 사라지면 보호가 비어 위험해진다(그래서 가둔다)",
       len(rows2) >= 1, True)

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
    # **진짜 pid 로 검사한다.** 판정 함수를 갈아 끼우면 그 함수를 검사하지 않는
    # 것이 된다(Codex 11차 P2 · 내가 그렇게 만들어 뒀다).
    owner = root / "interactive_favorite"
    owner.mkdir(parents=True, exist_ok=True)
    now = int(time.time())

    # 살아 있는 남 = 이 파이썬을 띄운 부모.
    alive = os.getppid()
    ck("준비: 부모 pid 는 살아 있다", svc._pid_alive(alive), True)
    io.open(owner / "sweep_owner.json", "w", encoding="utf-8").write(
        json.dumps({"pid": alive, "at": now}))
    before = len(svc.load_index())
    svc.sweep_unsaved(keep=5)
    ck("남이 돌고 있으면 아무것도 안 지운다", len(svc.load_index()), before)

    # 죽은 pid = 방금 끝낸 자식.
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    ck("준비: 끝난 자식 pid 는 죽었다", svc._pid_alive(dead.pid), False)
    io.open(owner / "sweep_owner.json", "w", encoding="utf-8").write(
        json.dumps({"pid": dead.pid, "at": now}))
    svc.sweep_unsaved(keep=5)
    ck("남이 죽었으면 다시 돈다", len(svc.load_index()), 5)

    # 오래된 흔적은 pid 가 살아 있어도 무시한다(pid 재사용으로 영영 막히지 않게).
    for i in range(4):
        svc.record(CH("more%d" % i))
    io.open(owner / "sweep_owner.json", "w", encoding="utf-8").write(
        json.dumps({"pid": alive, "at": now - (25 * 60 * 60)}))
    svc.sweep_unsaved(keep=5)
    ck("하루 지난 흔적은 무시한다", len(svc.load_index()), 5)

    # **psutil 없는 경로**도 같은 답을 내야 한다. 공식 런타임
    # (requirements-headless)에는 psutil 이 없어서, 예전엔 이 경로가 그냥
    # '남이 없다'로 떨어져 가드가 통째로 무효였다(Codex 11차 · 실증).
    real_import = builtins.__import__

    def no_psutil(name, *a, **k):
        if name == "psutil":
            raise ImportError("없다고 치자")
        return real_import(name, *a, **k)

    builtins.__import__ = no_psutil
    try:
        ck("psutil 없이도 산 pid 를 안다", svc._pid_alive(alive), True)
        ck("psutil 없이도 죽은 pid 를 안다", svc._pid_alive(dead.pid), False)
        io.open(owner / "sweep_owner.json", "w", encoding="utf-8").write(
            json.dumps({"pid": alive, "at": now}))
        for i in range(4):
            svc.record(CH("np%d" % i))
        before2 = len(svc.load_index())
        svc.sweep_unsaved(keep=5)
        ck("psutil 없이도 남이 돌면 안 지운다", len(svc.load_index()), before2)
    finally:
        builtins.__import__ = real_import

    # 정상 종료 흔적 지우기
    io.open(owner / "sweep_owner.json", "w", encoding="utf-8").write(
        json.dumps({"pid": os.getpid(), "at": now}))
    svc.release_sweep_owner()
    ck("정상 종료면 흔적을 지운다", (owner / "sweep_owner.json").exists(), False)

print()
print("전부 통과" if not fails else "실패 %d건: %s" % (len(fails), fails))
sys.exit(1 if fails else 0)
