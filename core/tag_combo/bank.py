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
    """`NRB3` 형식. 그룹 -> 앵커 -> {rows: [{tags, support, coverage, score}],
    tags: [{tag, p, lift}]}. 화면은 `tags`, 앵커 선택은 `rows` 를 쓴다."""

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
            # 문구는 ASCII 로 둔다 - 이 메시지는 백엔드 print() 로 흘러가고
            # 콘솔은 cp949 다(프로젝트 규약).
            raise ValueError(f"unknown bank format: {d.get('format')!r}, want NRB3")
        self.policy: dict = d.get("policy") or {}
        self.groups: dict[str, dict[str, list]] = d.get("groups") or {}

    # ---- 조회 --------------------------------------------------------
    def anchors(self, group: str) -> dict[str, list]:
        return self.groups.get(group) or {}

    def lookup(self, tags: Iterable[str], group: str, *,
               top_k: int = 5, min_coverage: float = 0.0,
               max_tag_repeat: int = 2, flat_top: int = 12,
               flat_min_p: float = 0.01, prefer: str = "") -> dict[str, Any]:
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
        #
        # ⚠️ **`rows` 만 보면 안 된다.** 화면은 이제 `tags`(평면 나열)를 그리는데,
        # 묶음이 하나도 안 나온 앵커가 4,999개(9.01%)나 있다 - 그것들은 평면
        # 태그를 16개씩 갖고도 여기서 `best` 가 못 돼 통째로 기권했다(실측:
        # `dark background` 는 tags 16개를 갖고 abstained=true). `blush` 를
        # 놓쳤던 지명 병목과 **같은 모양의 버그**다(Codex 지적).
        #
        # 묶음이 있는 앵커를 여전히 우선한다 - 그게 더 강한 신호다. 아무도 없을
        # 때만 평면 신호(1위 태그의 P)로 고른다. 그래서 기존 출력은 한 글자도
        # 안 바뀐다.
        #
        # **화면이 보고 있는 태그가 있으면 그게 기준이다.** 커버리지로 고르면 옆
        # 카드('함께 쓰는 것', `seedTag = inspecting || lastPicked`)와 기준이 갈려
        # 나란히 놓인 두 카드가 서로 다른 태그를 말한다 - 사용자 지적 2026-08-16:
        # 팝업에서 `wide hips` 를 눌렀는데 조합 카드는 `thick thighs` 에 눌러앉았다.
        #
        # ⚠️ **지정한 것이 앵커가 아니면 기권한다. 다른 태그로 갈아타지 않는다.**
        # 처음엔 조용히 자동 선택으로 돌아가게 했는데, 그게 더 나빴다(사용자 지적
        # 2026-08-17): `triple amputee` 를 살펴보는데 카드는 `thick thighs` 를
        # 말하고 있었다. 모르는 것에 대해 **남의 답을 내놓는 것**이라, 사용자는
        # 그 숫자가 지금 보는 태그의 것이라고 읽는다. 모르면 비우는 것이 맞다.
        #
        # `prefer` 를 안 준 호출(API 직접 사용 등)은 예전대로 자동 선택이다.
        best, best_cov = "", -1.0
        pref = str(prefer or "").strip().lower()
        if pref:
            e = table.get(pref) or {}
            if e.get("rows") or e.get("tags"):
                best = pref
            else:
                return {"combos": [], "tags": [], "anchor": "", "abstained": True,
                        "reason": "anchor not in bank"}
        for t in (have if not best else []):
            rows = (table[t] or {}).get("rows") or []
            if rows and rows[0].get("coverage", 0) > best_cov:
                best, best_cov = t, rows[0]["coverage"]
        if not best:
            for t in have:
                flat = (table[t] or {}).get("tags") or []
                if flat and flat[0].get("p", 0) > best_cov:
                    best, best_cov = t, flat[0]["p"]
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
        #
        # 바닥을 건다: `0%` 라고 적힌 칩은 사용자에게 아무 말도 하지 않는다.
        # 실측 573,003칩 중 0% 로 반올림되는 것 380개(0.07%), 1% 미만 712개
        # (0.12%). 1% 바닥이면 그게 다 사라지고 목록이 통째로 비는 앵커는 10개뿐
        # 이다(5% 바닥은 9,177칩·66앵커를 날린다 - 사용자는 개수를 **늘려** 달라
        # 했으므로 거기까지 자르지 않는다).
        flat = [x for x in (entry.get("tags") or [])
                if x.get("tag") not in cur and x.get("p", 0) >= flat_min_p]
        return {"combos": out, "tags": flat[:flat_top], "anchor": best,
                "abstained": not (out or flat),
                "reason": "" if (out or flat) else "no row passed"}


def load(dirs: Iterable[Path], bundle=None) -> RecipeBank | None:
    """느슨한 파일 -> 번들 부속 순으로 찾는다. 없으면 None(기능이 꺼진다).

    ⚠️ **번들 경로를 빼먹으면 배포판에서만 조용히 꺼진다.** 개발 환경에는 느슨한
    `recipe_bank.json` 이 있어서 잘 도는 것처럼 보이는데, 번들 파일 하나만 둔
    상태로 재보니 뱅크가 안 붙고 옛 온라인 경로로 떨어졌다 - 출력은 중복투성이
    (`apron, maid headdress, maid apron`)로, 지연은 0.5ms 에서 130ms 로 돌아갔다.

    ⚠️ **"없다" 와 "있는데 못 읽는다" 를 구분한다.** 없으면 `None`(기능이 꺼질
    뿐), 있는데 못 읽으면 **올린다**. 예전엔 둘 다 조용히 `None` 이라, 형식이
    안 맞는 번들을 만나도 아무 말 없이 옛 온라인 경로로 내려앉았다 - 추천이 다시
    니치해지는데 로그 한 줄 없었다(Codex 실증: 반환 None, stdout 빈 문자열).
    """
    errs = []
    for d in dirs:
        p = Path(d) / BANK_NAME
        if p.exists():
            try:
                return RecipeBank(p)
            except (OSError, ValueError, KeyError) as exc:
                errs.append(f"{p.name}@{Path(d).name}: {type(exc).__name__}: {exc}")
    if bundle is not None:
        try:
            blob = bundle.aux("recipe_bank")
            if blob:
                return RecipeBank(Path(bundle.path), blob=blob)
        except Exception as exc:      # noqa: BLE001
            errs.append(f"bundle aux: {type(exc).__name__}: {exc}")
    if errs:
        raise ValueError("; ".join(errs)[:300])
    return None
