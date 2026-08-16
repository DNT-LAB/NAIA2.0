# -*- coding: utf-8 -*-
"""레시피 뱅크 조회 — 런타임에서 계산하지 않고 **구워둔 것을 읽는다**.

## 왜 런타임 계산을 버렸는가

`query.py` 의 온라인 경로는 게시물당 한 묶음만 지명해서 흔하면서 적합한 태그를
구조적으로 놓친다(`blush` 는 `embarrassed` 의 87.5% 인데 한 번도 지명되지 않는다).
제대로 세려면 전수 itemset 이 필요한데 그건 동기 질의에 못 넣는다(실측 앵커당
수십~수백 ms, 넓은 앵커는 초 단위).

그래서 **오프라인에서 캐고**(`tools/build_recipe_bank.py`) 여기서는 사전 조회만
한다. 실측 조회는 마이크로초 단위다.

## 앵커 규칙

뱅크는 **앵커 하나**에 대해 구워져 있다. 사용자가 여러 태그를 골랐으면 그중
하나를 앵커로 정해야 하는데, 기준은 빈도가 아니라 **응집도**다 - 결합빈도 1위
조합(`long hair+blue eyes+large breasts`)이 최악의 추천을 냈다.

여기서는 단순하게 간다: 프롬프트 태그 중 뱅크에 있는 것들을 후보로 놓고,
**레시피의 커버리지가 가장 높은 앵커**를 고른다. 뱅크에 오르려면 이미 lift 게이트와
캐릭터 편향 필터를 통과했으므로, 남은 것 중에서는 잘 맞는 쪽을 고르면 된다.

## 기권

합격 레시피가 없으면 **빈 손으로 돌아간다.** 억지로 채우지 않는다 - 넓은 seed
(`smile` 30만장)에는 흔한 조합이 존재하지 않고, 그때 뭔가를 내놓으면 반드시
니치가 나온다.
"""

from __future__ import annotations

import json
from pathlib import Path
from collections import Counter
from typing import Any, Iterable

BANK_NAME = "recipe_bank.json"


class RecipeBank:
    """`NRB2` 형식. 그룹 -> 앵커 -> [{tags, support, coverage, score}]."""

    def __init__(self, path: Path, *, blob: bytes | None = None):
        self.path = Path(path)
        d = json.loads(blob.decode("utf-8") if blob is not None
                       else self.path.read_text(encoding="utf-8"))
        # ⚠️ **형태가 바뀌면 번호를 올려라.** NRB2 는 `앵커 -> [레시피]` 였고
        # NRB3 는 `앵커 -> {rows, tags}` 다. 번호를 그대로 두고 형태만 바꿨더니
        # 옛 번들을 읽을 때 `'list' object has no attribute 'get'` 로 죽었다
        # (실측: 사용자 포터블의 이전 v2 번들). 형식 검사는 정확히 이걸 막으려고
        # 있는 것이라, 번호를 올리면 크래시 대신 조용한 기권이 된다.
        if d.get("format") != "NRB3":
            raise ValueError(f"알 수 없는 뱅크 형식: {d.get('format')!r}")
        self.policy: dict = d.get("policy") or {}
        self.groups: dict[str, dict[str, list]] = d.get("groups") or {}

    # ---- 조회 --------------------------------------------------------
    def anchors(self, group: str) -> dict[str, list]:
        return self.groups.get(group) or {}

    def lookup(self, tags: Iterable[str], group: str, *,
               top_k: int = 5, min_coverage: float = 0.0,
               max_tag_repeat: int = 2, flat_top: int = 12) -> dict[str, Any]:
        """프롬프트 태그로 레시피를 찾는다. 없으면 기권(빈 combos)."""
        table = self.anchors(group)
        if not table:
            return {"combos": [], "anchor": "", "abstained": True,
                    "reason": "group not in bank"}
        want = [str(t).strip().lower() for t in tags if str(t).strip()]
        have = [t for t in want if t in table]
        if not have:
            return {"combos": [], "anchor": "", "abstained": True,
                    "reason": "no anchor"}

        # 앵커 선택: 1위 레시피의 커버리지가 가장 높은 것.
        best, best_cov = "", -1.0
        for t in have:
            rows = (table[t] or {}).get("rows") or []
            if rows and rows[0].get("coverage", 0) > best_cov:
                best, best_cov = t, rows[0]["coverage"]
        if not best:
            return {"combos": [], "anchor": "", "abstained": True,
                    "reason": "empty anchor rows"}

        entry = table[best] or {}
        picked = [r for r in (entry.get("rows") or [])
                  if r.get("coverage", 0) >= min_coverage]
        # 이미 프롬프트에 있는 태그만으로 된 줄은 쓸모가 없다.
        cur = set(want)
        picked = [r for r in picked if not set(r["tags"]) <= cur]
        # ---- 줄 사이 중복 억제 ----------------------------------------
        #
        # ⚠️ **"공유 태그 2개 이상" 만으로는 부족하다.** 그 규칙은 3태그 시절에
        # 정한 것인데, 지금은 2태그 줄이 흔해서 하나만 겹쳐도 통과한다. 실제 화면
        # (사용자 지적 2026-08-16, 앵커 `embarrassed`):
        #
        #     blush, sweat       18%
        #     blush, underwear   19%
        #     blush, panties     17%
        #     blush, sweatdrop   11%
        #
        # 네 줄이 전부 `blush` 로 시작해 읽는 사람에게는 한 줄과 다를 바 없다.
        # 그래서 **태그별 등장 횟수 상한**을 함께 건다 - 같은 태그가 여러 줄을
        # 점령하지 못한다. 겹침 규칙만 강화(>=1)하면 `underwear`+`panties` 처럼
        # 서로 다른 조합인데 한 태그를 공유하는 정당한 줄까지 죽는다.
        out, seen, used = [], set(), Counter()
        for r in picked:
            s = set(r["tags"])
            if len(s & seen) >= 2:
                continue
            if any(used[t] >= max_tag_repeat for t in s):
                continue
            out.append(r)
            seen |= s
            used.update(s)
            if len(out) >= top_k:
                break
        # 화면은 묶음이 아니라 **태그 + P(태그|앵커) 나열**을 쓴다(사용자 결정
        # 2026-08-16). 묶음은 같은 태그가 여러 줄에 나와 반복으로 읽혔다.
        # 이미 프롬프트에 있는 것은 뺀다 - 있는 걸 또 권할 이유가 없다.
        flat = [x for x in (entry.get("tags") or []) if x.get("tag") not in cur]
        return {"combos": out, "tags": flat[:flat_top], "anchor": best,
                "abstained": not (out or flat),
                "reason": "" if (out or flat) else "no row passed"}


def load(dirs: Iterable[Path], bundle=None) -> RecipeBank | None:
    """느슨한 파일 -> 번들 부속 순으로 찾는다. 없으면 None(기능이 꺼진다).

    ⚠️ **번들 경로를 빼먹으면 배포판에서만 조용히 꺼진다.** 개발 환경에는 느슨한
    `recipe_bank.json` 이 있어서 잘 도는 것처럼 보이는데, 번들 파일 하나만 둔
    상태로 재보니 뱅크가 안 붙고 옛 온라인 경로로 떨어졌다 - 출력은 중복투성이
    (`apron, maid headdress, maid apron`)로, 지연은 0.5ms 에서 130ms 로 돌아갔다.
    """
    for d in dirs:
        p = Path(d) / BANK_NAME
        if p.exists():
            try:
                return RecipeBank(p)
            except (OSError, ValueError, KeyError):
                continue
    if bundle is not None:
        try:
            blob = bundle.aux("recipe_bank")
            if blob:
                return RecipeBank(Path(bundle.path), blob=blob)
        except Exception:      # noqa: BLE001 - 뱅크가 없어도 기능은 돌아야 한다
            pass
    return None
