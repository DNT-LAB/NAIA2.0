"""Verify the Portable backend tree can import everything hot-patched into it.

포터블은 릴리즈 시점 빌드라 리포보다 오래된 트리다. 개별 .py를 핫패치할 때
그 파일이 "리포에는 있지만 포터블에는 없는" 모듈을 import 하면 백엔드가
기동 즉시 ModuleNotFoundError로 죽는다(실제 사고: core/nai_model_contract).

리포와 포터블에 함께 존재하는 파일들 중 내용이 같은 것(=핫패치본)을 골라
그 import 대상이 포터블 트리에 실재하는지 정적으로 확인한다. 런타임 기동 불필요.

사용법:
    python tools/check_portable_backend_imports.py [portable_root]
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PORTABLE = REPO_ROOT / "NAIA-Portable" / "resources" / "naia-backend"
LOCAL_TOP_LEVEL = {"core", "app", "utils", "interfaces", "modules", "tabs", "ui"}


def _imported_modules(source: str) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            modules.add(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name)
    return {module for module in modules if module.split(".")[0] in LOCAL_TOP_LEVEL}


def _resolvable(portable_root: Path, module: str) -> bool:
    base = portable_root / Path(*module.split("."))
    # core/ 등은 __init__.py 없는 네임스페이스 패키지다 - 디렉터리 존재로 충분.
    return base.with_suffix(".py").exists() or base.is_dir()


def main() -> int:
    portable_root = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PORTABLE
    if not portable_root.is_dir():
        print(json.dumps({"skipped": f"portable tree not found: {portable_root}"}, ensure_ascii=False))
        return 0

    violations: list[dict[str, str]] = []
    checked = 0
    for deployed in portable_root.rglob("*.py"):
        relative = deployed.relative_to(portable_root)
        if relative.parts[0] not in LOCAL_TOP_LEVEL:
            continue
        source_file = REPO_ROOT / relative
        if not source_file.exists():
            continue
        try:
            deployed_source = deployed.read_text(encoding="utf-8")
            if deployed_source != source_file.read_text(encoding="utf-8"):
                continue  # 핫패치본이 아니라 릴리즈 원본 - 그 트리의 정합은 빌드가 보장
            modules = _imported_modules(deployed_source)
        except (OSError, SyntaxError) as exc:
            violations.append({"file": str(relative), "reason": f"unreadable: {exc}"})
            continue
        checked += 1
        for module in sorted(modules):
            if not _resolvable(portable_root, module):
                violations.append({
                    "file": str(relative),
                    "module": module,
                    "reason": "imported module is missing from the portable tree",
                })

    print(json.dumps({
        "portable_root": str(portable_root),
        "hotpatched_files_checked": checked,
        "violations": violations,
    }, ensure_ascii=False, indent=2))
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
