# -*- coding: utf-8 -*-
"""Interactive 모드(특징 썸네일 포함)를 포터블로 동기화한다.

포터블은 `NAIA-Portable/resources/naia-backend/<repo 상대경로>` 구조로 repo 를 그대로
품고 있다. 하지만 Interactive 관련 백엔드가 한 번도 동기화된 적이 없어
(interactive_browse_index.py 부재) 파일 단위로 맞춰야 한다.

- `.py` / 데이터 변경은 **백엔드 재시작이 필요하다**. 프론트(`app/web/remote`)는 리로드로 충분.
- 기본은 --dry-run 이다. 실제 복사는 --apply 를 줘야 한다.
- 덮어쓰기 전 `.bak-<날짜>` 를 남긴다(포터블에 이미 그런 관례가 있다).

사용
    python tools/sync_portable_interactive.py                 # 무엇이 다른지만 본다
    python tools/sync_portable_interactive.py --apply --stamp 20260725
"""
from __future__ import annotations

import argparse
import filecmp
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PORTABLE = ROOT / "NAIA-Portable" / "resources" / "naia-backend"

# 재시작이 필요한 것(백엔드/데이터)과 리로드로 되는 것(프론트)을 나눠 보고한다.
BACKEND = [
    "app/backend/server/interactive_thumbnail_routes.py",
    "app/backend/server/headless_routes.py",
    "app/backend/server/autocomplete_commands.py",
    "app/backend/server/generation_runner.py",
    "core/interactive_browse_index.py",
    # 씬 기록/저장 계층. 프론트만 옮기면 저장·폴더 라우트가 없어 404 가 난다.
    "core/interactive_assets_service.py",
    "app/backend/server/interactive_assets_routes.py",
    # 부팅 청소(저장 안 한 기록 쓸어내기)를 거는 곳 - 서비스만 옮기면 안 돈다.
    "app/backend/server/headless_lifespan.py",
    "core/api_service.py",
    "data/interactive_thumbnails.json",
]
FRONTEND = [
    "app/web/remote/app.js",
    "app/web/remote/index.html",
    "app/web/remote/style.css",
    "app/web/remote/js/features/interactiveAxes.mjs",
    "app/web/remote/js/features/interactivePanel.mjs",
    "app/web/remote/js/features/interactiveScenePanel.mjs",
    "app/web/remote/js/features/interactiveAssetsPanel.mjs",
    "app/web/remote/js/features/interactiveBrowse.mjs",
    "app/web/remote/js/features/interactiveAutocomplete.mjs",
    "app/web/remote/js/features/tagAssist.mjs",
]


def state(rel: str) -> str:
    src, dst = ROOT / rel, PORTABLE / rel
    if not src.exists():
        return "SRC-MISSING"
    if not dst.exists():
        return "NEW"
    return "SAME" if filecmp.cmp(src, dst, shallow=False) else "DIFF"


def main() -> int:
    ap = argparse.ArgumentParser(description="Interactive 모드 포터블 동기화")
    ap.add_argument("--apply", action="store_true", help="실제로 복사한다(기본은 확인만)")
    ap.add_argument("--stamp", default="", help="백업 접미사에 쓸 날짜 (예: 20260725)")
    args = ap.parse_args()

    if not PORTABLE.exists():
        print(f"포터블 경로가 없습니다: {PORTABLE}")
        return 2

    todo = []
    for label, files in (("백엔드 (재시작 필요)", BACKEND), ("프론트 (리로드로 충분)", FRONTEND)):
        print(f"\n=== {label} ===")
        for rel in files:
            st = state(rel)
            mark = "  " if st == "SAME" else "->"
            print(f" {mark} [{st:11}] {rel}")
            if st in ("NEW", "DIFF"):
                todo.append(rel)

    if not todo:
        print("\n동기화할 것이 없습니다.")
        return 0
    if not args.apply:
        print(f"\n{len(todo)}개 파일이 다릅니다. 실제 복사는 --apply 를 주세요.")
        print("백엔드 파일이 포함되면 포터블 백엔드를 재시작해야 반영됩니다.")
        return 0

    copied = 0
    for rel in todo:
        src, dst = ROOT / rel, PORTABLE / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists() and args.stamp:
            backup = dst.with_name(dst.name + f".bak-{args.stamp}")
            if not backup.exists():
                shutil.copy2(dst, backup)
        shutil.copy2(src, dst)
        copied += 1
        print(f"  복사 {rel}")
    backend_touched = [r for r in todo if r in BACKEND]
    print(f"\n{copied}개 복사 완료.")
    if backend_touched:
        print(f"백엔드 {len(backend_touched)}개가 변경됐습니다 — 포터블 백엔드를 재시작하세요.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
