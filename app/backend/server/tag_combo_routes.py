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

import threading
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
    service = None
    # ⚠️ 지연 생성에 **락이 필요하다.** 없으면 콜드 스타트에서 동시에 들어온 첫
    # 요청들이 각자 ComboService 를 만들고, 각 서비스가 자기 BundleDownloader 를
    # 들고 179MB 를 동시에 받는다. 다운로더의 "한 번에 하나" 락은 인스턴스
    # 안에서만 유효해서 이걸 못 막는다. 게다가 같은 `.part` 에 여러 스레드가
    # 쓰면 파일이 깨져 sha256 이 어긋나고, 그걸 지우고 또 받는다.
    # (Codex 게이트: 동시 첫 요청 20건 -> ComboService 20개 생성 실증)
    service_lock = threading.Lock()

    def _service():
        nonlocal service
        if service is not None:
            return service
        with service_lock:
            if service is None:
                from core.tag_combo.service import ComboService, resolve_dirs
                # 받는 곳은 런타임 data_dir(포터블=user-data, 소스=%APPDATA%),
                # 찾는 곳은 저장소도 포함. 저장소만 보면 소스 실행이 179MB 를
                # git 트리 안에 받고, 포터블은 업데이트가 지우는 자리에 받는다.
                rp = getattr(context, "runtime_paths", None)
                target, search = resolve_dirs(repo_root, getattr(rp, "data_dir", None))
                service = ComboService(target, search_dirs=search)
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
                # 뱅크 상태를 함께 낸다. 뱅크가 없으면 기능이 죽는 게 아니라
                # **조용히 옛 온라인 경로로 내려앉는다** - 그건 눈에 보여야 한다.
                bank_ok = svc.bank() is not None
                return {"available": got, "dir": str(svc.dir),
                        "searchDirs": [str(d) for d in svc.search_dirs],
                        "built": bool(got),
                        "bank": bank_ok,
                        "bankError": "" if bank_ok else svc.bank_error(),
                        "howToBuild": "python tools/build_tag_combo_models.py"
                                      if not got else ""}
            except Exception as exc:      # noqa: BLE001
                _log_once(f"groups failed: {type(exc).__name__}: {exc}")
                return {"available": [], "error": type(exc).__name__}

        return JSONResponse(await _offload(_run))

    @app.post("/api/tag-combo/download")
    async def tag_combo_download(retry: bool = False):   # noqa: ANN202
        """Interactive 를 열 때 프론트가 한 번 부른다.

        이미 있거나 받는 중이면 아무것도 하지 않는다 - 재진입/여러 탭에서 반복
        호출해도 안전하다. 179MB 라 **배경으로** 받고 상태만 돌려준다.

        `retry=true` 는 사용자가 명시적으로 [다시 시도] 를 눌렀을 때만이다.
        실패 상태는 저절로 풀리지 않는다 - 자동 재시도로 179MB 를 반복해서
        긁으면 안 되기 때문이다.
        """
        def _run() -> dict[str, Any]:
            try:
                return _service().ensure_bundle(retry=bool(retry))
            except Exception as exc:      # noqa: BLE001
                _log_once(f"download start failed: {type(exc).__name__}: {exc}")
                return {"state": "error", "error": type(exc).__name__}

        return JSONResponse(await _offload(_run))

    @app.get("/api/tag-combo/download/status")
    async def tag_combo_download_status():   # noqa: ANN202
        def _run() -> dict[str, Any]:
            try:
                return _service().download_status()
            except Exception as exc:      # noqa: BLE001
                return {"state": "error", "error": type(exc).__name__}

        return JSONResponse(await _offload(_run))
