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


class FakeContext:
    """서비스가 쓰는 최소한의 계약만 흉내낸다."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.session_timestamp = "20260806_101112"

    def _save_path(self, *parts) -> Path:
        return self.root.joinpath(*[str(p) for p in parts])


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
            "dest_path": str(dest),
            "use_session_folder": True,
        })
        ids = [b["input_id"] for b in saved["bindings"]]
        check("중복/불량 항목이 걸러진다", ids == ["mouse:forward", "key:F3"], str(ids))
        check("액션 목록이 계약대로", tuple(saved["actions"]) == VIEWER_ACTIONS)
        rel = [b for b in saved["bindings"] if b["input_id"] == "key:F3"][0]
        check("상대 경로는 거부된다(빈 문자열로)", rel["dest_path"] == "", rel["dest_path"])

        print("\n[영속]")
        again = HeadlessViewerBindingService(FakeContext(root)).load()
        check("다시 읽어도 같다", again["bindings"] == saved["bindings"])
        path = svc.settings_path()
        check("설정 파일이 save 경로에 생긴다", path.is_file() and path.name == "viewer_bindings.json")

        print("\n[손상 복구]")
        path.write_text("{ 이건 JSON 이 아니다", encoding="utf-8")
        check("깨진 파일이면 기본값으로 시작한다", svc.load()["bindings"] == [])
        svc.save({"bindings": saved["bindings"], "dest_path": str(dest), "use_session_folder": True})

        print("\n[대상 폴더]")
        binding = svc.find_binding("mouse:forward")
        check("input_id 로 바인딩을 찾는다", binding is not None and binding["action"] == "copy")
        resolved = svc.resolve_dest_dir(binding)
        check("세션 하위 폴더가 붙는다", resolved.name == ctx.session_timestamp, str(resolved))
        check("폴더가 실제로 만들어진다", resolved.is_dir())

        svc.save({"bindings": saved["bindings"], "dest_path": str(dest), "use_session_folder": False})
        check("끄면 세션 폴더가 안 붙는다",
              svc.resolve_dest_dir(svc.find_binding("mouse:forward")).resolve() == dest.resolve())

        svc.save({"bindings": [{"input_id": "key:F5", "action": "copy"}],
                  "dest_path": "", "use_session_folder": False})
        try:
            svc.resolve_dest_dir(svc.find_binding("key:F5"))
            check("경로가 하나도 없으면 거절한다", False, "예외가 안 났다")
        except ValueError:
            check("경로가 하나도 없으면 거절한다", True)

        print("\n[복사 / 이동]")
        src_dir = root / "src"
        src_dir.mkdir()
        src = src_dir / "shot.png"
        src.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 40)
        svc.save({"bindings": [
            {"input_id": "mouse:forward", "action": "copy", "dest_path": str(dest)},
            {"input_id": "mouse:back", "action": "move", "dest_path": str(dest)},
        ], "dest_path": "", "use_session_folder": False})

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
