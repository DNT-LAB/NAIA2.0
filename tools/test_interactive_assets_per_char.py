# -*- coding: utf-8 -*-
"""캐릭터 슬롯당 에셋 하나 — 기록 규칙 검증.

`record()` 가 캐릭터 수만큼 카드를 남기는지, 같은 캐릭터가 새로 쌓이지 않고
갱신되는지, 갱신된 카드가 목록 **끝으로** 옮겨지는지(자리가 곧 최신순이라
_prune 이 앞쪽부터 지운다) 본다.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.interactive_assets_service import InteractiveAssetsService  # noqa: E402

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


def char(name: str, extra: list[str] | None = None) -> dict:
    return {"id": "c-" + name, "gender": "girl",
            "fields": {"캐릭터": [name], "의상": extra or []}}


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        svc = InteractiveAssetsService(FakeContext(Path(tmp)))

        # 1. 두 명 -> 카드 두 장
        metas = svc.record([char("alice"), char("bob")])
        check("두 명이면 카드 두 장", len(metas), 2)
        check("각 카드의 char_count 는 1", [m["char_count"] for m in metas], [1, 1])
        check("요약이 캐릭터별로 갈린다",
              sorted(m["summary"] for m in metas), ["alice", "bob"])
        check("해시가 서로 다르다",
              metas[0]["prompt_hash"] != metas[1]["prompt_hash"], True)

        # 본문에 캐릭터가 한 명씩만 들어간다
        body = svc.load_body(metas[0]["id"])
        check("본문에 캐릭터 한 명", len(body["chars"]), 1)
        # 씬 값은 캐릭터 에셋에 담지 않는다(사용자 결정) — 씬은 따로 관리한다.
        check("씬 값은 담기지 않는다", "globals" in body, False)

        # 2. 같은 조합을 다시 -> 새로 쌓이지 않는다
        again = svc.record([char("alice"), char("bob")])
        check("같은 캐릭터는 새로 쌓지 않는다", len(svc.load_index()), 2)
        check("같은 id 를 돌려준다",
              sorted(m["id"] for m in again), sorted(m["id"] for m in metas))

        # 3. 한 명만 다시 -> 그 카드가 목록 끝으로 온다
        alice_id = next(m["id"] for m in metas if m["summary"] == "alice")
        bob_id = next(m["id"] for m in metas if m["summary"] == "bob")
        check("갱신 전 마지막은 bob", svc.load_index()[-1]["id"], bob_id)
        svc.record([char("alice")])
        check("alice 를 다시 쓰면 끝으로 온다", svc.load_index()[-1]["id"], alice_id)
        check("그래도 두 장뿐", len(svc.load_index()), 2)

        # 4. 다른 캐릭터를 더하면 늘어난다
        svc.record([char("carol")])
        check("새 캐릭터는 새 카드", len(svc.load_index()), 3)

        # 5. 같은 캐릭터가 한 요청에 두 번 -> 한 장
        svc.record([char("dave"), char("dave")])
        check("한 요청 안의 중복도 한 장", len(svc.load_index()), 4)

        # 6. 옷만 바뀌면 다른 캐릭터로 본다(해시가 fields 를 본다)
        svc.record([char("alice", ["dress"])])
        check("필드가 다르면 새 카드", len(svc.load_index()), 5)

        # 7. 그림은 한 장뿐이다 -- **같은 그림을 캐릭터 카드 전부에 붙인다**
        #    (사용자 결정 2026-08-07). 생성 한 번의 배선을 그대로 흉내 낸다.
        import io as _io

        from PIL import Image

        buf = _io.BytesIO()
        Image.new("RGB", (640, 960), (30, 90, 160)).save(buf, "PNG")
        shot = buf.getvalue()
        check("alice 에 붙는다", svc.attach_thumb(alice_id, shot), True)
        check("같은 그림이 bob 에도 붙는다", svc.attach_thumb(bob_id, shot), True)
        thumbs = {r["id"]: r.get("thumb") for r in svc.load_index()}
        check("둘 다 자기 파일을 갖는다",
              [bool(thumbs[alice_id]), bool(thumbs[bob_id]), thumbs[alice_id] != thumbs[bob_id]],
              [True, True, True])
        check("썸네일 파일이 실제로 있다",
              sorted(p.name for p in (Path(tmp) / "interactive_snapshot").glob("*.webp")),
              sorted([thumbs[alice_id], thumbs[bob_id]]))
        check("없는 id 는 False(예외 아님)", svc.attach_thumb("s-nope", shot), False)

        # 8. 빈 입력
        check("빈 목록이면 빈 결과", svc.record([]), [])

        # 9. Fast(추가 프롬프트/네거티브)만 다른 조합은 **다른 카드**여야 한다.
        # 예전에는 snapshot_hash 가 fast 를 안 봐서 같은 해시가 나왔고,
        # record() 가 기존 행을 찾아 본문을 덮어써 먼저 만든 조합이 사라졌다.
        base_fast = {"name": "carol", "state": "active", "gender": "female",
                     "fields": {"머리": ["twintails"]}, "alt": [], "gaze": []}
        red = svc.record([dict(base_fast, fast={"p": "holding red umbrella", "n": ""})])
        blue = svc.record([dict(base_fast, fast={"p": "holding blue umbrella", "n": ""})])
        neg = svc.record([dict(base_fast, fast={"p": "", "n": "bad hands"})])
        check("Fast 프롬프트가 다르면 다른 카드", red[0] != blue[0], True)
        check("Fast 네거티브만 달라도 다른 카드", red[0] != neg[0], True)
        same = svc.record([dict(base_fast, fast={"p": "holding red umbrella", "n": ""})])
        check("같은 Fast 면 같은 카드", same[0], red[0])
        # 하위호환: Fast 가 비었거나 아예 없으면 옛 해시와 같아야 한다
        # (안 그러면 이미 쌓인 기록이 전부 중복 판정에서 풀린다).
        no_key = svc.record([dict(base_fast)])
        empty = svc.record([dict(base_fast, fast={"p": "", "n": ""})])
        check("Fast 없음 == 빈 Fast", no_key[0], empty[0])
        check("빈 Fast 는 Fast 있는 것과 다른 카드", no_key[0] != red[0], True)

        # 인덱스가 온전한 JSON 인가
        idx = json.loads((Path(tmp) / "interactive_snapshot" / "index.json").read_text("utf-8"))
        check("인덱스 행 수가 맞는다", len(idx["snapshots"]), 9)

    print()
    if FAILED:
        print("%d건 실패: %s" % (len(FAILED), ", ".join(FAILED)))
        return 1
    print("전부 통과")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
