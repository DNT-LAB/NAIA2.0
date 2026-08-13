"""태그 조합 추천 라우트.

    GET /api/tag-combo?tags=a,b,c[&group=1girl_solo]
    GET /api/tag-combo/groups

인원 그룹은 태그에서 유도한다(`core/tag_combo/person.py`). 사용자가 인원 설정을
바꾸면 다른 모델이 붙는다 - 그게 이 시스템의 요구사항이다.

⚠️ 질의는 **동기이고 무거울 수 있다**. 모델 첫 적재가 실측 375ms 이고 넓은 질의는
캐시에 없으면 초 단위다. async 핸들러에서 그대로 부르면 단일 워커의 이벤트 루프가
멈춘다 - 조언 라우트에서 같은 사고가 있었다. 전부 스레드로 넘긴다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse

MAX_TAGS = 24
_warned: set[str] = set()


def _log_once(msg: str) -> None:
    """같은 실패를 매 요청마다 찍지 않되, 한 번은 반드시 남긴다.

    cp949 콘솔이라 ASCII 로 접는다(한글 사용자명 경로가 섞이면 print 가 죽는다).
    """
    key = msg.split(":")[0]
    if key in _warned:
        return
    _warned.add(key)
    safe = msg.encode("ascii", "backslashreplace").decode("ascii")
    print(f"[tag-combo] {safe}")


def register_tag_combo_routes(app: FastAPI, context: Any, *,
                              run_in_thread: Any = None) -> None:
    repo_root = Path(getattr(context, "repo_root", ".") or ".")
    data_dir = repo_root / "data" / "tag_combo"
    service = None

    def _service():
        nonlocal service
        if service is None:
            from core.tag_combo.service import ComboService
            service = ComboService(data_dir)
        return service

    async def _offload(fn):
        if run_in_thread is None:
            return fn()
        return await run_in_thread(fn)

    @app.get("/api/tag-combo")
    async def tag_combo(tags: str = "", group: str = ""):   # noqa: ANN202
        names = [x.strip() for x in str(tags or "").split(",") if x.strip()][:MAX_TAGS]
        if not names:
            return JSONResponse({"group": "", "combos": [], "matched": 0})

        def _run() -> dict[str, Any]:
            try:
                return _service().recommend(names, group=group)
            except Exception as exc:      # noqa: BLE001
                # 추천이 없어도 앱은 돌아야 한다 - 그래서 200 으로 내보낸다.
                # 다만 **조용히** 삼키면 안 된다. 예전에 조언 라우트가 그렇게
                # 실패해서 배포판에서 카드가 통째로 사라진 것을 아무도 몰랐다.
                _log_once(f"recommend failed: {type(exc).__name__}: {exc}")
                return {"error": type(exc).__name__, "detail": str(exc)[:200],
                        "group": group, "combos": []}

        return JSONResponse(await _offload(_run))

    @app.get("/api/tag-combo/groups")
    async def tag_combo_groups():   # noqa: ANN202
        def _run() -> dict[str, Any]:
            try:
                svc = _service()
                got = svc.available()
                if not got:
                    # 깨끗한 체크아웃에는 모델이 없다 - 생성물이라 커밋하지 않는다.
                    # 무엇을 해야 하는지 응답과 로그 양쪽에 남긴다.
                    _log_once("no models built; run tools/build_tag_combo_models.py")
                return {"available": got, "dir": str(data_dir),
                        "built": bool(got),
                        "howToBuild": "python tools/build_tag_combo_models.py"
                                      if not got else ""}
            except Exception as exc:      # noqa: BLE001
                _log_once(f"groups failed: {type(exc).__name__}: {exc}")
                return {"available": [], "error": type(exc).__name__}

        return JSONResponse(await _offload(_run))
