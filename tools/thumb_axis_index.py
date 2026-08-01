# -*- coding: utf-8 -*-
"""축 목록의 단일 출처 — "선언된 축이 아니면 축이 아니다".

## 왜 필요한가

`wildcards/thumb/*.txt` 에는 축이 아닌 것이 섞여 있다. `pose_solo`(1,592)·
`pose_multi`(439)·`pose_drop`(87)은 `build_pose_slots.py` 가 인원별로 가른
**중간 산출물**이고, `build_pose_axes.py` 가 이것을 읽어 78개 실제 축으로 쪼갠다.
원료가 축인 척 잡히면 같은 태그를 두 번 센다.

그래서 도구마다 `NOT_AXES` 를 선언해 뒀는데 **세 곳에 따로 적혀 있었고 이미
갈라졌다**(2026-08-02 실측):

    build_interactive_thumbnails  {pose_solo, pose_multi, pose_drop, expression_from_pose}
    thumb_bench_init              {pose_solo, pose_multi, pose_drop, pose_nsfw, pose_nsfw_face}
    build_tag_cooccurrence        {pose_solo, pose_multi, pose_drop, nsfw_heavy}
                                                                     ^^^^^^^^^^ 없어진 파일

`nsfw_heavy` 는 성적/폭력 두 분류로 갈라져 사라졌는데 목록에는 남아 있었고, 새로
생긴 `nsfw_etc_sexual`·`nsfw_etc_dark` 는 아무도 모른다. 새 도구를 만들 때마다
이 목록을 다시 적어야 한다는 것 자체가 결함이다 — 실제로 오늘 두 번 걸렸다.

## 뒤집는다

목록을 관리하는 대신 **UI 가 실제로 배선한 축**을 emit 이 파일로 낸다
(`wildcards/thumb/_axes_index.json`). emit 은 SLOTS 를 조립하면서 어떤 축이
화면에 붙는지 이미 정확히 알고 있다 — 그것을 적어 두기만 하면 된다.

    is_axis("pose_gaze")   -> True
    is_axis("pose_solo")   -> False   (중간 산출물)
    is_axis("nsfw_etc_dark") -> True  (gloss 섹션도 축이다)

## 없을 때

emit 을 한 번도 안 돌린 트리에서는 파일이 없다. 그때는 **막지 않고** 옛 규칙으로
떨어진다(`pose_solo`/`pose_multi`/`pose_drop` 제외). 빌드 순서를 강제하면 첫
빌드가 불가능해진다.
"""
from __future__ import annotations

import json
from pathlib import Path

INDEX = Path("wildcards/thumb/_axes_index.json")

# emit 을 아직 안 돌린 트리용 최소 안전망. **여기를 늘리지 마라** — 늘리고 싶으면
# emit 이 내는 목록을 고쳐야 한다(그것이 이 모듈의 존재 이유다).
_FALLBACK_NOT_AXES = frozenset({"pose_solo", "pose_multi", "pose_drop"})

_cache: dict[str, frozenset[str] | None] = {}


def declared_axes(root: Path | None = None) -> frozenset[str] | None:
    """배선된 축 이름. 인덱스가 없으면 None(호출자가 폴백을 쓴다)."""
    path = (root / INDEX) if root is not None else INDEX
    key = str(path)
    if key in _cache:
        return _cache[key]
    value: frozenset[str] | None = None
    if path.exists():
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
            names = doc.get("axes") or []
            if names:
                value = frozenset(str(n) for n in names)
        except Exception:
            value = None
    _cache[key] = value
    return value


def is_axis(name: str, root: Path | None = None) -> bool:
    """`wildcards/thumb/<name>.txt` 가 실제 축인가."""
    if name.startswith("_"):
        return False
    axes = declared_axes(root)
    if axes is None:
        return name not in _FALLBACK_NOT_AXES
    return name in axes
