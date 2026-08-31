# -*- coding: utf-8 -*-
"""이미지 태거(WD14) 라우트 — 이미지를 받아 원격 태거의 결과를 돌려준다.

엔드포인트::

    GET  /api/tagger/info                    모델 목록·기본값·외부 전송 고지
    POST /api/tagger/analyze?general=..&character=..&model=..   (본문 = 이미지 바이트)

본문을 원시 바이트로 받는 것은 `/api/metadata/extract` 와 같은 규약이다 —
멀티파트 파서 없이 `fetch(url, {body: blob})` 하나면 된다.

⚠️ **이 경로는 사용자의 이미지를 제3자 서버로 보낸다.** 그래서 `info` 가 고지
문구를 함께 돌려준다 — 화면이 그것을 반드시 띄운다(사용자 결정 2026-08-31).

루프백 게이트는 **걸지 않는다.** 이것은 호스트의 상태를 바꾸는 동작이 아니라
사용자가 직접 누르는 기능이고, 원격에서 쓰라고 있는 앱이다(생성과 같은 성격).
번역 기록 삭제처럼 호스트 파일을 고치는 것과는 다르다.
"""
from __future__ import annotations

from typing import Any, Awaitable, Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from core.prompt_category_annotation import MAIN_CATEGORY_ORDER, _category_sets, classify
from core.wd_tagger_service import (
    DEFAULT_MODEL,
    MODEL_REPOS,
    TaggerError,
    UPLOAD_MAX_BYTES,
    tag_image,
)

AsyncRunner = Callable[..., Awaitable[Any]]

EXTERNAL_NOTICE = (
    "이미지가 외부 서버(huggingface.co)로 전송되어 분석됩니다. "
    "NAIA 밖으로 나가는 것이 곤란한 이미지에는 사용하지 마세요."
)


def _grouped_by_category(tags: list[str], context: Any) -> list[dict[str, Any]]:
    """태그를 NAIA 프롬프트 엔지니어링과 **같은 분류**로 묶는다.

    Category Annotation(`#의상:` `#표정:` …)이 쓰는 바로 그 분류기를 재사용한다 —
    태거 결과가 프롬프트 창에서 보던 것과 다른 이름으로 갈리면 사용자가 두 가지
    분류 체계를 외워야 한다.

    ⚠️ `filter_data_manager` 가 없으면(데이터 미적재) **전부 `#추가:` 로 쏟아진다.**
    그때는 빈 목록을 돌려주고 호출부가 Full Prompt 만 보이게 한다 - 전부 '추가' 인
    화면은 분류가 된 척하면서 아무것도 안 알려 준다.
    """
    manager = getattr(context, "filter_data_manager", None) if context is not None else None
    if manager is None:
        return []
    try:
        sets = _category_sets(manager)
    except Exception:
        return []
    if not sets:
        return []

    buckets: dict[str, list[str]] = {}
    for tag in tags:
        buckets.setdefault(classify(tag, sets), []).append(tag)

    out: list[dict[str, Any]] = []
    for key, marker, _attribute in MAIN_CATEGORY_ORDER:
        rows = buckets.get(key)
        if not rows:
            continue          # 빈 칸은 내보내지 않는다(주석 사양과 같다)
        out.append({
            "key": key,
            "marker": marker,
            "label": marker.strip("#:"),
            "tags": rows,
        })
    return out


def _clamp(value: Any, low: float, high: float, fallback: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    if number != number:  # NaN
        return fallback
    return max(low, min(high, number))


def register_tagger_routes(
    app: FastAPI,
    context: Any = None,
    *,
    run_in_thread: AsyncRunner,
) -> None:
    @app.get("/api/tagger/info")
    async def tagger_info():
        return {
            "models": list(MODEL_REPOS),
            "default_model": DEFAULT_MODEL,
            "default_general": 0.35,
            "default_character": 0.85,
            "max_bytes": UPLOAD_MAX_BYTES,
            # 화면이 이 문구를 띄운다. 여기(백엔드)를 SSOT 로 둬서 분리창·모바일이
            # 제각기 다른 문구를 쓰는 일이 없게 한다.
            "external_notice": EXTERNAL_NOTICE,
        }

    @app.post("/api/tagger/analyze")
    async def tagger_analyze(req: Request):
        image_bytes = await req.body()
        if not image_bytes:
            return JSONResponse({"ok": False, "error": "이미지가 없습니다."}, status_code=400)
        if len(image_bytes) > UPLOAD_MAX_BYTES:
            return JSONResponse({"ok": False, "error": "이미지가 너무 큽니다."}, status_code=413)

        params = req.query_params
        general = _clamp(params.get("general"), 0.0, 1.0, 0.35)
        character = _clamp(params.get("character"), 0.0, 1.0, 0.85)
        model = params.get("model") or DEFAULT_MODEL

        def _run():
            return tag_image(
                image_bytes,
                general_thresh=general,
                character_thresh=character,
                model_repo=model,
            )

        try:
            result = await run_in_thread(_run)
        except TaggerError as exc:
            # 사용자에게 그대로 보여도 되는 문구다 - 502 로 원인이 우리 밖임을 알린다.
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=502)
        except Exception as exc:
            return JSONResponse(
                {"ok": False, "error": f"태거 처리 중 오류: {exc}"}, status_code=500
            )
        payload = result.payload()
        ordered = [row["tag"] for row in result.character] + [row["tag"] for row in result.general]
        payload["categories"] = _grouped_by_category(ordered, context)
        return payload
