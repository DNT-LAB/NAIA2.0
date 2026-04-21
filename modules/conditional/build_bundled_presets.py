"""번들 프리셋 5종 생성 유틸 (Sub-phase 1.6).

사용자 UC-1~UC-4 를 커버하는 예시 프리셋을 `data/conditional_presets_bundled/`
아래에 JSON 으로 생성한다. 결정론적 출력(fixed id, fixed timestamp) 을 위해
`rulebook_to_dict` 결과를 후처리한다.

실행:
    python -m modules.conditional.build_bundled_presets

주의: 이 스크립트를 재실행하면 번들 파일이 덮어쓰여진다. 사용자 편집은
`save/conditional_presets/` (user override) 에서만 수행해야 한다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import List

from modules.conditional.block_model import (
    Action,
    ConditionNode,
    Rule,
    RuleBook,
    make_and_group,
    make_char_in_leaf,
    make_or_group,
    make_rating_leaf,
    make_tag_leaf,
)
from modules.conditional.preset_io import (
    DEFAULT_BUNDLED_DIR,
    rulebook_to_dict,
)


# 결정론적 타임스탬프 — Sub-phase 1.6 완료 시점
FIXED_CREATED_AT = "2026-04-21T00:00:00"


# ============================================================================
# 각 번들 정의
# ============================================================================


def _bundle_nsfw_auto_negative() -> tuple[str, str, RuleBook]:
    """UC-4: rating 기반 자동 네거티브 주입."""
    book = RuleBook(
        rules=[
            Rule(
                kind="block",
                priority=10,
                name="Explicit → NSFW 아티팩트 네거티브",
                condition=make_rating_leaf("e", source="auto"),
                action=Action(
                    kind="append_list",
                    target="neg",
                    tags=["nsfw_artifacts", "censored", "bad_anatomy"],
                ),
            ),
            Rule(
                kind="block",
                priority=20,
                name="Questionable → 저품질 네거티브",
                condition=make_rating_leaf("q", source="auto"),
                action=Action(
                    kind="append_list",
                    target="neg",
                    tags=["low_quality", "blurry"],
                ),
            ),
        ],
        max_passes=1,
        stop_on_match=False,
    )
    return (
        "nsfw_auto_negative",
        "레이팅에 따라 네거티브 프롬프트에 아티팩트/저품질 방지 태그를 자동 주입.",
        book,
    )


def _bundle_character_duo_link() -> tuple[str, str, RuleBook]:
    """UC-1a/b: C1 의 태그 상태로 C2 토글."""
    book = RuleBook(
        rules=[
            Rule(
                kind="block",
                priority=10,
                name="C1 이 viewer 를 보면 C2 활성화",
                condition=make_char_in_leaf(1, "looking at viewer"),
                action=Action(
                    kind="char_set",
                    char_index=2,
                    char_state="enabled",
                ),
            ),
            Rule(
                kind="block",
                priority=20,
                name="C1 이 solo 태그면 C2 비활성화",
                condition=make_char_in_leaf(1, "solo"),
                action=Action(
                    kind="char_set",
                    char_index=2,
                    char_state="disabled",
                ),
            ),
        ],
        max_passes=1,
        stop_on_match=False,
    )
    return (
        "character_duo_link",
        "C1 태그에 따라 C2 를 활성/비활성화하는 2인 연동 프리셋.",
        book,
    )


def _bundle_quality_boost() -> tuple[str, str, RuleBook]:
    """rating s/g 일 때 품질 태그 prefix 주입."""
    book = RuleBook(
        rules=[
            Rule(
                kind="block",
                priority=10,
                name="Safe/General → 마스터피스 태그",
                condition=make_or_group(
                    make_rating_leaf("s", source="auto"),
                    make_rating_leaf("g", source="auto"),
                ),
                action=Action(
                    kind="append_list",
                    target="prefix",
                    tags=["masterpiece", "best quality"],
                ),
            ),
            Rule(
                kind="block",
                priority=20,
                name="landscape 포함 시 고해상도 태그",
                condition=make_tag_leaf("landscape", modifier="exact"),
                action=Action(
                    kind="append_list",
                    target="postfix",
                    tags=["highres", "detailed background"],
                ),
            ),
        ],
        max_passes=1,
        stop_on_match=False,
    )
    return (
        "quality_boost",
        "안전 레이팅 또는 풍경 태그 감지 시 품질/해상도 강조 태그를 자동 추가.",
        book,
    )


def _bundle_resolution_force() -> tuple[str, str, RuleBook]:
    """UC-2: 태그 감지 → prefix 에 resolution: 인라인 파라미터 주입.

    API 서비스가 이미 `resolution:` 인라인 파라미터를 파싱하므로 별도 훅
    변경 없이 동작한다.
    """
    book = RuleBook(
        rules=[
            Rule(
                kind="block",
                priority=10,
                condition=make_tag_leaf("landscape", modifier="exact"),
                action=Action(
                    kind="append_list",
                    target="prefix",
                    tags=["resolution:landscape"],
                ),
            ),
            Rule(
                kind="block",
                priority=20,
                condition=make_tag_leaf("portrait", modifier="exact"),
                action=Action(
                    kind="append_list",
                    target="prefix",
                    tags=["resolution:portrait"],
                ),
            ),
            Rule(
                kind="block",
                priority=30,
                condition=make_tag_leaf("square", modifier="exact"),
                action=Action(
                    kind="append_list",
                    target="prefix",
                    tags=["resolution:square"],
                ),
            ),
        ],
        max_passes=1,
        stop_on_match=True,  # 첫 매칭 후 중단 (해상도 중복 방지)
    )
    return (
        "resolution_force",
        "특정 구도 태그 감지 시 prefix 에 resolution: 인라인 파라미터 자동 주입.",
        book,
    )


def _bundle_composite_filter() -> tuple[str, str, RuleBook]:
    """UC-3: 레거시 패턴 치환 + 복수 패스 필터링 샘플."""
    book = RuleBook(
        rules=[
            Rule(
                kind="block",
                priority=10,
                name="1girl 단독 구도 → 단순 구도 표기",
                condition=make_and_group(
                    make_tag_leaf("1girl"),
                    make_tag_leaf("solo"),
                ),
                action=Action(
                    kind="append_list",
                    target="main",
                    tags=["simple_composition"],
                ),
            ),
            Rule(
                kind="block",
                priority=20,
                name="패턴 치환: bad_shirt → clean_shirt",
                condition=ConditionNode(
                    kind="group", logical="AND", children=[]
                ),
                action=Action(
                    kind="replace",
                    old_tag="__bad_shirt__",
                    new_tags=["clean_shirt"],
                ),
            ),
            Rule(
                kind="block",
                priority=30,
                name="nsfw 태그 감지 시 clean 후처리 태그",
                condition=make_tag_leaf("nsfw"),
                action=Action(
                    kind="append_list",
                    target="postfix",
                    tags=["clean"],
                ),
            ),
        ],
        max_passes=3,  # 체이닝된 규칙 수렴 허용
        stop_on_match=False,
    )
    return (
        "composite_filter",
        "AND/패턴 치환/복수 패스를 조합한 레거시 호환 필터링 샘플.",
        book,
    )


# ============================================================================
# 빌드 실행
# ============================================================================


_BUILDERS = [
    _bundle_nsfw_auto_negative,
    _bundle_character_duo_link,
    _bundle_quality_boost,
    _bundle_resolution_force,
    _bundle_composite_filter,
]


def _make_deterministic(
    data: dict, *, bundle_name: str, display_name: str, description: str
) -> dict:
    """created_at / id 를 결정론적 값으로 덮어써서 커밋 친화적으로 만든다."""
    data["name"] = display_name
    data["description"] = description
    data["created_at"] = FIXED_CREATED_AT
    for i, rule in enumerate(data.get("rules", []), start=1):
        rule["id"] = f"bundled-{bundle_name}-{i:02d}"
    return data


def build_all(target_dir: Path = None) -> List[Path]:
    """5 종 번들을 생성하여 `target_dir` 에 쓴다. 기존 파일 덮어쓰기."""
    target = Path(target_dir) if target_dir else DEFAULT_BUNDLED_DIR
    target.mkdir(parents=True, exist_ok=True)

    written: List[Path] = []
    for builder in _BUILDERS:
        bundle_name, description, book = builder()
        display_name = bundle_name.replace("_", " ").title()
        data = rulebook_to_dict(book, name=display_name, description=description)
        data = _make_deterministic(
            data,
            bundle_name=bundle_name,
            display_name=display_name,
            description=description,
        )
        path = target / f"{bundle_name}.json"
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        written.append(path)
    return written


if __name__ == "__main__":
    paths = build_all()
    print(f"번들 프리셋 {len(paths)} 종 생성:")
    for p in paths:
        print(f"  - {p}")
