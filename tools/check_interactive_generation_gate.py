"""Interactive 생성 요청에 Prompt Fixed / WC Solo 가 새지 않는지 검증한다.

배경(실측 2026-08-11): 프론트는 두 옵션의 체크박스를 **표시만** 비활성화한다
(app.js 의 INTERACTIVE_BLOCKED_OPTIONS - set_option 은 전 클라이언트에 broadcast 되고
영속되므로 저장값을 끄면 다른 탭까지 꺼진다). 그래서 Interactive 를 켜기 **전에**
켜 뒀다면 저장값은 켜진 채 남고, `_normalized_params` 의
`params.update(self.context.get_options())` 가 그걸 매 요청에 싣는다.

실제 피해는 `wildcard_standalone` 이었다 - `_source_row()` 가 사용자의 실제 행 대신
빈 행("wildcard_standalone")을 돌려줘 프롬프트 런 기록이 출처를 잃었다. 이미지 자체
(프롬프트·해상도·스텝)는 영향 없었다. Auto Gen 연쇄는 `interactive_mode_request`
마커만으로 이미 끊긴다(게이트가 거기서 더 하는 일은 없다).

수정은 `core/headless_generation_service.py:_normalized_params` 에서 마커가 붙은
요청에만 `apply_interactive_generation_gate` 를 거는 것이다. 이 게이트는 **모든**
클라이언트(Electron·LAN 탭·headless CLI)에 걸리므로 프론트 한 곳에 의존하지 않는다.

tests/ 는 .gitignore 대상이라 게이트가 체크아웃에 남지 않으므로 추적되는 tools/ 에 둔다.

사용법:
    python tools/check_interactive_generation_gate.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pandas as pd  # noqa: E402

from core.auto_generation_flags import (  # noqa: E402
    AUTO_GENERATE_SUPPRESSED_FLAGS,
    apply_interactive_generation_gate,
)
from core.headless_generation_service import HeadlessGenerationService  # noqa: E402
from core.web_session_context import (  # noqa: E402
    InMemoryTokenManager,
    WebSessionContext,
)

# 사용자가 Interactive 를 켜기 전에 켜 뒀을 법한 상태.
LEAKY_OPTIONS = {"prompt_fixed": True, "wildcard_standalone": True, "auto_generate": True}
SOURCE_ROW_NAME = "danbooru_row"


def _request_params(overrides: dict) -> tuple[dict, str]:
    """옵션이 켜진 세션에서 요청 하나를 만들고 (params, source_row 이름) 을 돌려준다."""
    with tempfile.TemporaryDirectory() as td:
        manager = InMemoryTokenManager({"nai_token": "pst-check-token"})
        context = WebSessionContext(token_manager=manager, repo_root=Path(td))
        context.secure_token_manager = manager
        context.current_source_row = pd.Series(
            {"general": "1girl, solo", "character": "hatsune miku",
             "copyright": "vocaloid", "artist": "", "meta": ""},
            name=SOURCE_ROW_NAME,
        )
        # get_options() 는 사본을 돌려준다 - 실제 저장소는 set_option 이다.
        for key, value in LEAKY_OPTIONS.items():
            context.set_option(key, value)

        service = HeadlessGenerationService(context)
        dispatch = service.enqueue_remote_request(
            {
                "type": "generate",
                "prompt": "1girl, long hair, blue eyes",
                "negative_prompt": "lowres",
                # 무료 조건(Steps 28 + 1MP 미만)이지만 enqueue 만 하므로 API 는 안 나간다.
                "overrides": dict(overrides, steps=28, width=832, height=1216),
            },
            enqueue=False,
        )
        if not dispatch.ok:
            raise RuntimeError(dispatch.blocked_reason)
        return dispatch.request.params, str(getattr(dispatch.request.source_row, "name", ""))


# (라벨, overrides, 게이트가 걸려야 하는가)
CASES = (
    ("interactive marker", {"interactive_mode_request": True}, True),
    ("interactive marker as string", {"interactive_mode_request": "true"}, True),
    ("plain generate", {}, False),
    ("studio request", {"studio_request": True}, False),
    ("marker explicitly false", {"interactive_mode_request": False}, False),
)


def main() -> int:
    violations: list[dict] = []

    for label, overrides, gated in CASES:
        params, row_name = _request_params(overrides)
        expected_flag = not gated          # 게이트가 걸리면 False, 아니면 저장값(True)
        expected_row = SOURCE_ROW_NAME if gated else "wildcard_standalone"
        for key in ("prompt_fixed", "wildcard_standalone"):
            if bool(params.get(key)) is not expected_flag:
                violations.append({
                    "case": label, "key": key,
                    "expected": expected_flag, "actual": bool(params.get(key)),
                    "reason": "gate applied to the wrong requests"
                              if not gated else "conflicting flag leaked into Interactive",
                })
        if row_name != expected_row:
            violations.append({
                "case": label, "key": "source_row",
                "expected": expected_row, "actual": row_name,
                "reason": "wildcard_standalone replaced the user's source row",
            })
        # 게이트가 마커를 없던 요청에 새로 붙이면 Auto Gen 연쇄가 통째로 멈춘다.
        if not gated and params.get("interactive_mode_request"):
            violations.append({
                "case": label, "key": "interactive_mode_request",
                "expected": False, "actual": True,
                "reason": "gate stamped the marker onto a non-Interactive request",
            })

    # 게이트 자체의 계약: 저장 옵션을 건드리지 않고 params 만 고친다.
    probe = {"prompt_fixed": True, "wildcard_standalone": True, "seed": 42}
    out = apply_interactive_generation_gate(probe)
    if out is not probe:
        violations.append({"case": "gate purity", "key": "identity",
                           "reason": "gate must mutate and return the same dict"})
    if out.get("seed") != 42:
        violations.append({"case": "gate purity", "key": "seed",
                           "reason": "unrelated params must survive"})

    if "interactive_mode_request" not in AUTO_GENERATE_SUPPRESSED_FLAGS:
        violations.append({"case": "auto gen", "key": "interactive_mode_request",
                           "reason": "marker must stay in AUTO_GENERATE_SUPPRESSED_FLAGS"})

    print(json.dumps({"cases_checked": len(CASES), "violations": violations},
                     ensure_ascii=False, indent=2))
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
