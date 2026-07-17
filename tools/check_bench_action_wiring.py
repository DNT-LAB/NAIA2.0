"""Verify every data-action button in the character asset benches has a handler.

실사고(2026-07-17): 인라인 폼 코드를 인덱스 범위로 잘라내면서 무관한
`else if (action === 'open-bench') openBench();` 등 14개 핸들러가 함께 삭제됐다.
버튼은 남고 배선만 사라져 "+ 바리에이션 추가"가 죽었는데, node --check(문법)도
pytest(백엔드)도 계약 게이트(라우트)도 이를 잡지 못했다.

정적 문자열 검사라 오탐이 없고 즉시 돈다. tests/ 는 .gitignore 대상이라 게이트가
체크아웃에 남지 않으므로(Codex 리뷰) 추적되는 tools/ 에 둔다.

사용법:
    python tools/check_bench_action_wiring.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TARGETS = (
    "app/web/remote/js/features/characterAssetTab.mjs",
    "app/web/remote/js/features/characterCreationBench.mjs",
)
# 사라지면 기능이 통째로 죽는 액션 - 버튼과 핸들러가 함께 삭제돼도 잡힌다.
REQUIRED_ACTIONS = {
    "app/web/remote/js/features/characterAssetTab.mjs": (
        "select", "select-variation", "refresh", "open-create", "open-bench",
        "staged-new", "staged-variation", "staged-cancel",
        "apply-c1", "apply-c1-cr", "apply-c1-inset", "apply-add",
        "rename", "prompt-edit", "prompt-edit-save", "prompt-edit-cancel",
        "delete-character", "delete-variation", "promote",
        "bench-close", "bench-mode", "bench-generate", "bench-save",
        "bench-enhance", "bench-discard", "bench-pick", "bench-random-outfit",
        "bench-prompt-source",
        "bench-custom-open", "bench-custom-close", "bench-custom-apply", "bench-custom-reset",
        "bench-custom-fold",
    ),
    "app/web/remote/js/features/characterCreationBench.mjs": (
        "create-close", "create-generate", "create-save", "create-save-variation",
        "create-discard", "create-pick", "create-prompt-source", "create-prefill-c1",
        "create-prefill-selected", "create-random-roll", "create-random-generate",
        "create-random-gender", "create-open-reference", "create-open-inpaint",
        "create-ref-upload", "create-ref-paste", "create-ref-storage", "create-ref-remove",
        "create-mask-close", "create-mask-clear", "create-mask-mode", "create-mask-unpin",
        "create-pin-unpin",
        "create-custom-open", "create-custom-close", "create-custom-apply", "create-custom-reset",
        "create-custom-fold",
    ),
}

ACTION_MARKUP_RE = re.compile(r'data-action="([a-z0-9-]+)"')
ACTION_HANDLER_RE = re.compile(r"action === '([a-z0-9-]+)'")


def main() -> int:
    violations: list[dict[str, str]] = []
    total = 0
    for relative in TARGETS:
        path = REPO_ROOT / relative
        if not path.is_file():
            violations.append({"file": relative, "reason": "target file is missing"})
            continue
        source = path.read_text(encoding="utf-8")
        declared = set(ACTION_MARKUP_RE.findall(source))
        handled = set(ACTION_HANDLER_RE.findall(source))
        total += len(declared)
        for action in sorted(declared - handled):
            violations.append({
                "file": relative, "action": action,
                "reason": "button exists but no handler branch",
            })
        for action in sorted(handled - declared):
            violations.append({
                "file": relative, "action": action,
                "reason": "handler exists but no button renders it",
            })
        for action in REQUIRED_ACTIONS.get(relative, ()):
            if action not in handled:
                violations.append({
                    "file": relative, "action": action,
                    "reason": "required action lost (button+handler deleted together?)",
                })

    print(json.dumps({"actions_checked": total, "violations": violations}, ensure_ascii=False, indent=2))
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
