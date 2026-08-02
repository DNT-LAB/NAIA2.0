"""Interactive 모드 조언 서빙 — 태그를 고를 때 옆에 띄우는 정보.

썸네일 그리드 오른쪽 플로트가 쓰는 데이터다. 세 가지를 준다.

    전제조건   이 태그가 성립하려면 같이 있어야 하는 것 (`hugging tail` -> 꼬리)
    충돌       같이 입지 않는 의상 (`china dress` + `skirt set` = 동시 등장 0건)
    추천/비권장 같이 쓰이는 / 안 어울리는 조합

근거는 모두 실측이다:
- 전제조건 = Danbooru 공식 tag implications + Codex 검증 큐레이션
  (`core/interactive_tag_dependency.py`)
- 충돌·추천·비권장 = 의상 프리셋 `gsq_1girl_solo` 파티션 통계
  (`data/interactive_clothing_harmony.json`, tools/build_clothing_harmony.py)

라우트:
    GET /api/interactive-advice?tag=<태그>       한 태그
    GET /api/interactive-advice/batch?tags=a,b   여러 태그(쉼표 구분, 최대 40개)
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse

HARMONY_RELATIVE = Path("data") / "interactive_clothing_harmony.json"
MAX_BATCH = 40


class _HarmonyPack:
    """조합 규칙 캐시. mtime 이 바뀌면 다시 읽는다(빌더 재실행 반영)."""

    def __init__(self, repo_root: Path):
        self._path = Path(repo_root) / HARMONY_RELATIVE
        self._lock = threading.Lock()
        self._data: dict[str, Any] = {}
        self._mtime: float | None = None

    def _load_locked(self) -> None:
        try:
            stat = self._path.stat()
        except OSError:
            self._data = {}
            self._mtime = None
            return
        if self._mtime == stat.st_mtime and self._data:
            return
        try:
            self._data = json.loads(self._path.read_text(encoding="utf-8"))
            self._mtime = stat.st_mtime
        except (OSError, ValueError):
            self._data = {}
            self._mtime = None

    def get(self) -> dict[str, Any]:
        with self._lock:
            self._load_locked()
            return self._data


def _dependency_index():
    """전제조건 인덱스. 태그 DB 로딩이 무거우므로 실패해도 조언은 계속 나가게 한다."""
    try:
        from core.interactive_tag_dependency import get_dependency_index
        return get_dependency_index()
    except Exception:      # noqa: BLE001 - 조언은 있으면 좋은 부가 정보다
        return None


def _advise_one(tag: str, harmony: dict[str, Any], dep) -> dict[str, Any]:
    t = str(tag or "").strip()
    out: dict[str, Any] = {"tag": t, "requires": [], "hint": "",
                           "conflict": [], "recommend": [], "avoid": [],
                           "region": "", "regionLabel": ""}
    if not t:
        return out
    if dep is not None:
        try:
            adv = dep.advise(t)
            out["requires"] = [{"axis": r.axis, "label": r.label, "tag": r.tag,
                                "strong": r.strong} for r in adv.requires]
            out["hint"] = adv.hint_ko
            out["specialize"] = adv.specialize[:6]
            out["similar"] = adv.similar[:6]
        except Exception:  # noqa: BLE001
            pass
    # 표시용으로만 자른다. 선택 집합 안의 충돌 판정은 /conflicts 가 전량을 본다.
    out["conflict"] = list(harmony.get("conflict", {}).get(t, ()))[:12]
    # 추천은 점수 순 상위만 주면 같은 부위 변형이 줄줄이 나온다
    # (`sweater` -> ribbed sweater / turtleneck sweater / off-shoulder sweater ...).
    # 부위별로 묶어 보내서 화면이 서로 다른 부위를 고루 보여줄 수 있게 한다.
    rec = list(harmony.get("recommend", {}).get(t, ()))
    region_of = harmony.get("region", {})
    weak_of = harmony.get("region_weak", {})
    labels = harmony.get("region_labels", {})
    groups: dict[str, list[str]] = {}
    for cand in rec:
        r = region_of.get(cand) or weak_of.get(cand) or ""
        groups.setdefault(r, []).append(cand)
    out["recommend"] = rec[:12]                 # 하위 호환(평면 목록)
    out["recommendGroups"] = [
        {"region": r, "label": labels.get(r, "기타"), "tags": v[:8]}
        for r, v in sorted(groups.items(), key=lambda kv: -len(kv[1]))
    ]
    out["avoid"] = list(harmony.get("avoid", {}).get(t, ()))[:5]
    region = harmony.get("region", {}).get(t, "")
    out["region"] = region
    out["regionLabel"] = harmony.get("region_labels", {}).get(region, "")
    return out


def register_interactive_advice_routes(app: FastAPI, context: Any, *,
                                       run_in_thread: Any = None) -> None:
    """조언 라우트.

    ⚠️ 여기서 하는 일은 **동기이고 무겁다**. `_dependency_index()` 는 첫 호출에서
    태그 DB 17만 건을 읽어 올린다(실측 2.7초). async 핸들러 안에서 그대로 부르면
    단일 워커의 이벤트 루프가 그동안 통째로 멈춘다 — 생성 요청도 WebSocket 갱신도
    함께 굳는다. 그래서 전부 스레드로 넘긴다(Codex 리뷰 2026-08-03).
    """
    repo_root = Path(getattr(context, "repo_root", ".") or ".")
    pack = _HarmonyPack(repo_root)

    async def _offload(fn):
        """동기 작업을 스레드에서 돌린다. 주입이 없으면(구 호출부) 그대로 실행."""
        if run_in_thread is None:
            return fn()
        return await run_in_thread(fn)

    @app.get("/api/interactive-advice")
    async def interactive_advice(tag: str = ""):   # noqa: ANN202
        return JSONResponse(
            await _offload(lambda: _advise_one(tag, pack.get(), _dependency_index())))

    @app.get("/api/interactive-advice/batch")
    async def interactive_advice_batch(tags: str = ""):   # noqa: ANN202
        names = [x.strip() for x in str(tags or "").split(",") if x.strip()][:MAX_BATCH]

        def _run() -> dict[str, Any]:
            # 인덱스 로딩 자체가 목적인 워밍업 요청(빈 tags)도 여기를 지난다.
            harmony, dep = pack.get(), _dependency_index()
            return {"items": [_advise_one(n, harmony, dep) for n in names]}

        return JSONResponse(await _offload(_run))

    @app.get("/api/interactive-advice/conflicts")
    async def interactive_advice_conflicts(tags: str = ""):   # noqa: ANN202
        """선택된 태그 집합 안에서 서로 충돌하는 쌍만 낸다 — 경고 배지용."""
        names = [x.strip() for x in str(tags or "").split(",") if x.strip()][:MAX_BATCH]
        table = (await _offload(pack.get)).get("conflict", {})
        seen, pairs = set(), []
        for a in names:
            for b in table.get(a, ()):
                if b in names:
                    key = tuple(sorted((a, b)))
                    if key not in seen:
                        seen.add(key)
                        pairs.append({"a": key[0], "b": key[1]})
        return JSONResponse({"pairs": pairs})
