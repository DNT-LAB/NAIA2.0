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

        # 10. 값어치 없는 씬은 기록하지 않는다 (사용자 지정)
        svc2 = InteractiveAssetsService(FakeContext(Path(tempfile.mkdtemp())))
        empty_g = {"slots": {"background": [], "fx": []},
                   "composition": {}, "composition_tags": [],
                   "free_text": "", "rating": {"mode": "single", "picks": ["none"]},
                   "fast_negative": ""}
        check("아무것도 없으면 기록 안 함", svc2.record_scene(empty_g, []), None)
        # 구도 축만 든 것도 값어치가 없다 - 사용자 표현: "축만 들어있는 데이터"
        axis_only = dict(empty_g, composition={"x": 3, "y": 1, "z": 0},
                         composition_tags=["from above", "wide shot"])
        check("구도 축만 있으면 기록 안 함", svc2.record_scene(axis_only, []), None)
        check("Rating 만 있어도 기록 안 함",
              svc2.record_scene(dict(empty_g, rating={"mode": "single",
                                                      "picks": ["explicit"]}), []), None)
        check("빈 씬은 목록에 안 남는다", len(svc2.load_scene_index()), 0)
        # 태그가 하나라도 있으면 기록한다
        check("씬 태그가 있으면 기록",
              svc2.record_scene(dict(empty_g, slots={"background": ["forest"]}), [])
              is not None, True)
        check("자유 입력만 있어도 기록",
              svc2.record_scene(dict(empty_g, free_text="masterpiece"), []) is not None, True)
        check("캐릭터 상황만 있어도 기록",
              svc2.record_scene(empty_g, situation("sitting")) is not None, True)
        check("캐릭터별 Fast 만 있어도 기록",
              svc2.record_scene(empty_g, [{"fields": {}, "neg": {}, "gender": "female",
                                           "alt": [], "gaze": [],
                                           "fast": {"p": "extra tag", "n": ""}}])
              is not None, True)

        # 11. Fast 는 담되 해시에는 넣지 않는다 (복원하지 않으므로)
        svc3 = InteractiveAssetsService(FakeContext(Path(tempfile.mkdtemp())))
        base = situation("sitting")
        with_fast = [dict(base[0], fast={"p": "extra", "n": "no extra"})]
        m1 = svc3.record_scene(globals_for("forest"), base)
        m2 = svc3.record_scene(globals_for("forest"), with_fast)
        check("Fast 만 다르면 같은 카드", m2["id"], m1["id"])
        body3 = svc3.load_scene_body(m1["id"])
        check("그래도 Fast 는 본문에 남는다",
              body3["chars"][0]["fast"], {"p": "extra", "n": "no extra"})

        # 12. 본문 정규화 — 손편집/옛 기록이 반쯤 적용되지 않게
        svc4 = InteractiveAssetsService(FakeContext(Path(tempfile.mkdtemp())))
        m4 = svc4.record_scene(
            {"slots": {"background": ["forest", "", 7]}, "composition": "깨진값",
             "free_text": None, "rating": {"mode": "random", "picks": ["safe", ""]},
             "fast_negative": 12, "모르는키": "버려야 한다"},
            [{"fields": {"자세": ["sitting", None]}, "gender": "정체불명",
              "name": "따라오면 안 된다", "preset": {"work": "x"},
              "neg": "깨진값", "alt": None, "fast": "깨진값"}])
        b4 = svc4.load_scene_body(m4["id"])
        check("빈/숫자 태그 정리", b4["globals"]["slots"]["background"], ["forest", "7"])
        # JSON null 은 태그가 되면 안 된다 - str(None) == "None" 은 공백이 아니라
        # 필터를 통과해 프롬프트에 `None` 을 실어 보낸다(Codex 7차).
        check("null 은 태그가 아니다", b4["chars"][0]["fields"]["자세"], ["sitting"])
        check("깨진 composition 은 빈 dict", b4["globals"]["composition"], {})
        check("모르는 키는 버린다", "모르는키" in b4["globals"], False)
        check("rating 은 single 로 접힌다", b4["globals"]["rating"],
              {"mode": "single", "picks": ["safe"]})
        check("fast_negative 는 문자열", b4["globals"]["fast_negative"], "12")
        check("성별은 두 값 중 하나", b4["chars"][0]["gender"], "female")
        check("이름은 본문에 안 담긴다", "name" in b4["chars"][0], False)
        check("프리셋도 안 담긴다", "preset" in b4["chars"][0], False)
        check("깨진 neg 는 빈 dict", b4["chars"][0]["neg"], {})
        check("깨진 fast 는 빈 값", b4["chars"][0]["fast"], {"p": "", "n": ""})

        # 12b. 저장한 씬(수집) — 자동 기록 위에 얹는 층
        with tempfile.TemporaryDirectory() as tmp5:
            root5 = Path(tmp5)
            s5 = InteractiveAssetsService(FakeContext(root5))
            a = s5.record_scene(globals_for("교실"), situation("sitting"))
            b = s5.record_scene(globals_for("해변"), situation("standing"))

            f = s5.create_scene_folder("학교")
            check("폴더 생성", bool(f and f["id"]), True)
            check("같은 이름은 새로 안 만든다",
                  s5.create_scene_folder("학교")["id"], f["id"])
            check("빈 이름 거부", s5.create_scene_folder("   "), None)

            saved = s5.save_scene(a["id"], "창가 역광", f["id"])
            check("저장됨", saved["saved"], True)
            check("이름", saved["name"], "창가 역광")
            check("폴더", saved["folder"], f["id"])
            check("없는 폴더는 빈값으로",
                  s5.save_scene(b["id"], "해변", "없는폴더")["folder"], "")
            check("없는 씬 저장은 None", s5.save_scene("eNOPE", "x"), None)

            # 본문에도 남는다 — 인덱스를 잃어도 살아나야 한다
            body = json.loads((root5 / "interactive_scene" / f"{a['id']}.json")
                              .read_text(encoding="utf-8"))
            check("본문에 저장 표시", body.get("saved"), True)
            check("본문에 이름", body.get("name"), "창가 역광")

            # 이름·폴더만 고친다
            s5.update_scene(a["id"], name="새 이름")
            rows5 = s5.load_scene_index()
            hit5 = next(r for r in rows5 if r["id"] == a["id"])
            check("이름 변경", hit5["name"], "새 이름")
            check("폴더는 그대로", hit5["folder"], f["id"])

            # 폴더를 지워도 씬은 남는다
            check("폴더 삭제", s5.delete_scene_folder(f["id"]), True)
            hit5 = next(r for r in s5.load_scene_index() if r["id"] == a["id"])
            check("씬은 살아남는다", hit5["saved"], True)
            check("폴더 없음으로 옮겨진다", hit5["folder"], "")

            # 2단 폴더(Finder 형) — 대 -> 소, 그 이상은 안 판다
            big = s5.create_scene_folder("장소")
            sub = s5.create_scene_folder("교실", big["id"])
            check("소카테고리의 부모", sub["parent"], big["id"])
            deep = s5.create_scene_folder("창가", sub["id"])
            check("3단은 안 만든다(한 칸 위로)", deep["parent"], big["id"])
            check("같은 이름도 부모가 다르면 별개",
                  s5.create_scene_folder("교실", "")["id"] != sub["id"], True)
            check("대카테고리 + 소카테고리 묶음",
                  s5._folder_and_children(big["id"]) >= {big["id"], sub["id"], deep["id"]}, True)
            check("소카테고리는 자기만", s5._folder_and_children(sub["id"]), {sub["id"]})

            # 대카테고리를 지우면 소카테고리도 함께, 단 **씬은 남는다**
            s5.save_scene(b["id"], "교실 씬", sub["id"])
            check("소카테고리에 담김",
                  next(r for r in s5.load_scene_index() if r["id"] == b["id"])["folder"],
                  sub["id"])
            check("대카테고리 삭제", s5.delete_scene_folder(big["id"]), True)
            ids5 = {f["id"] for f in s5.load_scene_folders()}
            check("소카테고리도 사라진다", sub["id"] in ids5, False)
            hitb = next(r for r in s5.load_scene_index() if r["id"] == b["id"])
            check("그 안의 씬은 남는다", hitb["saved"], True)
            check("폴더 없음으로 옮겨진다", hitb["folder"], "")

            # 저장한 것은 프루닝에서 살아남는다
            for i in range(SNAPSHOT_LIMIT + 5):
                s5.record_scene(globals_for("bulk2-%d" % i), situation("sitting"))
            rows5 = s5.load_scene_index()
            check("저장한 씬은 프루닝 생존",
                  any(r["id"] == a["id"] for r in rows5), True)
            check("한도는 자동 기록에만",
                  len([r for r in rows5 if not r.get("saved")]) <= SNAPSHOT_LIMIT, True)

            # 인덱스를 잃어도 저장 상태가 살아난다
            (root5 / "interactive_scene" / "index.json").write_text("{ broken",
                                                                    encoding="utf-8")
            rebuilt5 = s5.load_scene_index()
            hit5 = next((r for r in rebuilt5 if r["id"] == a["id"]), None)
            check("복구해도 저장 상태 유지", bool(hit5 and hit5.get("saved")), True)
            check("복구해도 이름 유지", hit5.get("name") if hit5 else None, "새 이름")

            # 수집에서 내리면 자동 기록으로 돌아간다(본문은 그대로)
            check("내리기", s5.unsave_scene(a["id"]), True)
            hit5 = next(r for r in s5.load_scene_index() if r["id"] == a["id"])
            check("자동 기록으로", hit5["saved"], False)
            check("본문은 살아 있다", s5.load_scene_body(a["id"]) is not None, True)

        # 13. 인덱스가 깨져도 본문에서 되짚는다
        idx = root / "interactive_scene" / "index.json"
        idx.write_text("{ broken", encoding="utf-8")
        rebuilt = svc.load_scene_index()
        check("손상 인덱스를 본문에서 복구", len(rebuilt) > 0, True)
        check("손상본을 옆으로 치운다",
              any(p.suffix == ".bak" or ".bak" in p.name
                  for p in (root / "interactive_scene").iterdir()), True)
        # **복구본을 저장했는지까지 본다.** 한 번만 읽는 검사는 이 결함을 놓친다 -
        # 저장하지 않으면 이번 호출만 복구된 것처럼 보이고, 손상본은 이미 치웠으므로
        # 다음 호출은 빈 목록이다. 그 상태에서 기록하면 옛 카드가 통째로 사라진다
        # (Codex 7차 · 실측: 1회차 3 -> 2회차 0 -> 기록 후 1).
        check("복구본이 두 번째 읽기에도 남는다", len(svc.load_scene_index()), len(rebuilt))
        svc.record_scene(globals_for("복구 후 새 씬"), situation("sitting"))
        check("복구 후 기록해도 옛 카드가 안 사라진다",
              len(svc.load_scene_index()) >= len(rebuilt), True)

        # 14. 본문 하나가 깨져도 나머지는 살린다
        with tempfile.TemporaryDirectory() as tmp2:
            root2 = Path(tmp2)
            svc5 = InteractiveAssetsService(FakeContext(root2))
            for i in range(3):
                svc5.record_scene(globals_for("ok-%d" % i), situation("sitting"))
            sroot = root2 / "interactive_scene"
            # 파싱은 되지만 모양이 깨진 본문 - int()/len() 이 터지던 자리
            (sroot / "ebroken0000000001.json").write_text(
                json.dumps({"id": "ebroken0000000001", "created_at": "어제",
                            "globals": {"slots": {"background": "문자열"}},
                            "chars": "리스트가 아님"}), encoding="utf-8")
            (sroot / "index.json").write_text("{ broken", encoding="utf-8")
            got = svc5.load_scene_index()
            check("깨진 본문이 있어도 멀쩡한 것은 복구", len(got) >= 3, True)

    print()
    if FAILED:
        print("실패 %d건: %s" % (len(FAILED), ", ".join(FAILED)))
        return 1
    print("전부 통과")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
