# -*- coding: utf-8 -*-
"""뷰어 숏컷 바인딩 서비스 검사.

파일을 옮기고 지우는 기능이라 정규화와 경로 결정을 실물로 확인한다.
`python tools/test_viewer_bindings.py`
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.headless_viewer_binding_service import (  # noqa: E402
    HeadlessViewerBindingService,
    VIEWER_ACTIONS,
)

FAILURES: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("  PASS  " if ok else "  FAIL  ") + name + ((" -- " + detail) if detail and not ok else ""))
    if not ok:
        FAILURES.append(name)


class FakeQuicksave:
    """Ctrl+S 빠른 저장이 쓰는 폴더. 숏컷은 이제 이것을 그대로 쓴다."""

    def __init__(self, ctx: "FakeContext") -> None:
        self.ctx = ctx

    def quicksave_directory(self) -> Path:
        raw = str(self.ctx.auto_save_state.get("quicksave_dir") or "").strip()
        base = Path(raw) if raw else (self.ctx.root / "output")
        if str(self.ctx.auto_save_state.get("quicksave_folder") or "date") == "date":
            base = base / self.ctx.session_timestamp
        return base


class FakeContext:
    """서비스가 쓰는 최소한의 계약만 흉내낸다."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.session_timestamp = "20260806_101112"
        self.auto_save_state = {"quicksave_dir": "", "quicksave_folder": "date"}

    def _save_path(self, *parts) -> Path:
        return self.root.joinpath(*[str(p) for p in parts])

    def _save_service(self) -> FakeQuicksave:
        return FakeQuicksave(self)


class FakeItem:
    def __init__(self, filepath: str = "", filename: str = "a.png", raw: bytes = b"") -> None:
        self.filepath = filepath
        self.filename = filename
        self.raw_bytes = raw


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="naia-vb-") as tmp:
        root = Path(tmp)
        ctx = FakeContext(root)
        svc = HeadlessViewerBindingService(ctx)
        dest = root / "dest"

        print("\n[정규화]")
        saved = svc.save({
            "bindings": [
                {"input_id": "mouse:forward", "action": "copy", "dest_path": str(dest)},
                {"input_id": "mouse:forward", "action": "move"},      # 중복 -> 버림
                {"input_id": "key:F2", "action": "nonsense"},          # 잘못된 액션 -> 버림
                {"input_id": "", "action": "copy"},                    # 빈 입력 -> 버림
                {"input_id": "key:F3", "action": "trash", "dest_path": "relative/path"},
            ],
        })
        ids = [b["input_id"] for b in saved["bindings"]]
        check("중복/불량 항목이 걸러진다", ids == ["mouse:forward", "key:F3"], str(ids))
        check("액션 목록이 계약대로", tuple(saved["actions"]) == VIEWER_ACTIONS)
        rel = [b for b in saved["bindings"] if b["input_id"] == "key:F3"][0]
        check("상대 경로는 거부된다(빈 문자열로)", rel["dest_path"] == "", rel["dest_path"])
        check("공용 폴더 설정은 더 이상 저장하지 않는다",
              "dest_path" not in saved and "use_session_folder" not in saved,
              str(sorted(saved.keys())))
        check("빠른 저장 경로를 함께 알려 준다", "quicksave_resolved" in saved)

        print("\n[영속]")
        again = HeadlessViewerBindingService(FakeContext(root)).load()
        check("다시 읽어도 같다", again["bindings"] == saved["bindings"])
        path = svc.settings_path()
        check("설정 파일이 save 경로에 생긴다", path.is_file() and path.name == "viewer_bindings.json")

        print("\n[손상 복구]")
        path.write_text("{ 이건 JSON 이 아니다", encoding="utf-8")
        check("깨진 파일이면 기본값으로 시작한다", svc.load()["bindings"] == [])
        svc.save({"bindings": saved["bindings"]})

        print("\n[대상 폴더]")
        binding = svc.find_binding("mouse:forward")
        check("input_id 로 바인딩을 찾는다", binding is not None and binding["action"] == "copy")
        resolved = svc.resolve_dest_dir(binding)
        check("바인딩에 적은 경로를 쓴다", str(resolved).startswith(str(dest)), str(resolved))
        check("세션 하위 폴더는 빠른 저장 설정을 따른다",
              resolved.name == ctx.session_timestamp, str(resolved))
        check("폴더가 실제로 만들어진다", resolved.is_dir())

        ctx.auto_save_state["quicksave_folder"] = "flat"
        check("빠른 저장이 세션 폴더를 안 쓰면 여기도 안 쓴다",
              svc.resolve_dest_dir(svc.find_binding("mouse:forward")).resolve() == dest.resolve())
        ctx.auto_save_state["quicksave_folder"] = "date"

        print("\n[빠른 저장 경로 공유]")
        # 경로를 안 적은 숏컷은 Ctrl+S 가 쓰는 그 폴더로 간다. 설정이 둘이면
        # 반드시 어긋나므로 여기에는 아예 자기 경로를 두지 않는다.
        svc.save({"bindings": [{"input_id": "key:F5", "action": "copy"}]})
        shared = svc.resolve_dest_dir(svc.find_binding("key:F5"))
        check("경로를 안 적으면 빠른 저장 폴더로 간다",
              shared.resolve() == ctx._save_service().quicksave_directory().resolve(),
              str(shared))
        picks = root / "picks"
        ctx.auto_save_state["quicksave_dir"] = str(picks)
        check("빠른 저장 경로를 바꾸면 숏컷도 따라간다",
              svc.resolve_dest_dir(svc.find_binding("key:F5")).resolve()
              == (picks / ctx.session_timestamp).resolve())
        check("알려 주는 값도 같이 바뀐다",
              svc.load()["quicksave_resolved"] == str(picks / ctx.session_timestamp))
        ctx.auto_save_state["quicksave_dir"] = ""

        print("\n[복사 / 이동]")
        src_dir = root / "src"
        src_dir.mkdir()
        src = src_dir / "shot.png"
        src.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 40)
        svc.save({"bindings": [
            {"input_id": "mouse:forward", "action": "copy", "dest_path": str(dest)},
            {"input_id": "mouse:back", "action": "move", "dest_path": str(dest)},
        ]})

        item = FakeItem(filepath=str(src))
        out = svc.copy_or_move(item, svc.find_binding("mouse:forward"))
        check("복사하면 원본이 남는다", src.is_file() and Path(out["path"]).is_file())
        check("복사본 내용이 같다", Path(out["path"]).read_bytes() == src.read_bytes())

        out2 = svc.copy_or_move(FakeItem(filepath=str(src)), svc.find_binding("mouse:forward"))
        check("같은 이름은 덮어쓰지 않고 번호를 붙인다",
              out2["path"] != out["path"] and Path(out2["path"]).is_file(),
              Path(out2["path"]).name)

        moved_item = FakeItem(filepath=str(src))
        out3 = svc.copy_or_move(moved_item, svc.find_binding("mouse:back"))
        check("이동하면 원본이 사라진다", not src.exists() and Path(out3["path"]).is_file())
        check("이동 후 항목이 새 경로를 가리킨다", moved_item.filepath == out3["path"])

        print("\n[디스크에 원본이 없을 때]")
        png = (b"\x89PNG\r\n\x1a\n" + b"1" * 32)
        mem_item = FakeItem(filepath="", filename="memory.png", raw=png)
        out4 = svc.copy_or_move(mem_item, svc.find_binding("mouse:forward"))
        check("메모리에서 새로 쓴다", out4["mode"] == "write" and Path(out4["path"]).read_bytes() == png)

        # ── Codex 리뷰에서 나온 회귀 ────────────────────────────────────────
        print("\n[대상이 원본 폴더와 같을 때]")
        # 세션 하위 폴더가 붙으면 대상은 `<dest>/<세션>` 이라 애초에 제자리가
        # 아니다 — 제자리 판정을 보려면 평면 모드여야 한다.
        ctx.auto_save_state["quicksave_folder"] = "flat"
        same_dir = root / "inplace"
        same_dir.mkdir()
        inplace = same_dir / "here.png"
        inplace.write_bytes(b"\x89PNG\r\n\x1a\n" + b"z" * 24)
        svc.save({"bindings": [
            {"input_id": "key:F1", "action": "move", "dest_path": str(same_dir)},
            {"input_id": "key:F2", "action": "copy", "dest_path": str(same_dir)},
        ]})
        r = svc.copy_or_move(FakeItem(filepath=str(inplace)), svc.find_binding("key:F1"))
        # 예전에는 _unique 가 먼저 돌아 here_2.png 를 내주고 원본 이름이 바뀌었다.
        check("제자리 이동은 아무 일도 하지 않는다",
              r["mode"] == "noop" and inplace.is_file()
              and not (same_dir / "here_2.png").exists(), str(r))
        r2 = svc.copy_or_move(FakeItem(filepath=str(inplace)), svc.find_binding("key:F2"))
        check("제자리 복사도 사본을 만들지 않는다",
              r2["mode"] == "noop" and len(list(same_dir.iterdir())) == 1,
              str(sorted(p.name for p in same_dir.iterdir())))

        print("\n[메모리 전용 항목의 이동]")
        svc.save({"bindings": [
            {"input_id": "key:F6", "action": "move", "dest_path": str(dest)},
            {"input_id": "key:F7", "action": "copy", "dest_path": str(dest)},
        ]})
        m_item = FakeItem(filepath="", filename="mem.png", raw=png)
        m_out = svc.copy_or_move(m_item, svc.find_binding("key:F6"))
        # 안 가리키면 이 항목은 계속 '미저장'(filepath 없음)이라 Save All 이 한 벌 더 쓴다.
        check("이동한 뒤에는 항목이 새 파일을 가리킨다", m_item.filepath == m_out["path"],
              repr(m_item.filepath))
        c_item = FakeItem(filepath="", filename="mem.png", raw=png)
        svc.copy_or_move(c_item, svc.find_binding("key:F7"))
        check("복사는 항목을 건드리지 않는다", c_item.filepath == "", repr(c_item.filepath))

        print("\n[상한]")
        many = [{"input_id": f"key:F{i}", "action": "copy"} for i in range(30)]
        check("바인딩 개수에 상한이 있다", len(svc.save({"bindings": many})["bindings"]) == 12)

    print()
    if FAILURES:
        print(f"실패 {len(FAILURES)}건: " + ", ".join(FAILURES))
        return 1
    print("모두 통과")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
