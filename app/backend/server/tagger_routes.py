# -*- coding: utf-8 -*-
"""이미지 태거(WD14) 라우트 — 이미지를 받아 원격 태거의 결과를 돌려준다.

엔드포인트::

    GET  /api/tagger/info                    모델 목록·기본값·외부 전송 고지
    POST /api/tagger/analyze?general=..&character=..&model=..   (본문 = 이미지 바이트)

본문을 원시 바이트로 받는 것은 `/api/metadata/extract` 와 같은 규약이다 —
멀티파트 파서 없이 `fetch(url, {body: blob})` 하나면 된다.

이 경로는 사용자의 이미지를 HuggingFace Space 로 보낸다. 사용자 판단으로 경고가
아니라 **출처 표시**로 다룬다 — `info` 가 `[ 웹에서 사용 : <링크> ]` 를 돌려주고
화면이 그것을 띄운다. 여전히 **문구를 못 받으면 전송하지 않는다**(어디로 가는지
안 보이는 채로 내보내지 않는다).

루프백 게이트는 **걸지 않는다.** 이것은 호스트의 상태를 바꾸는 동작이 아니라
사용자가 직접 누르는 기능이고, 원격에서 쓰라고 있는 앱이다(생성과 같은 성격).
번역 기록 삭제처럼 호스트 파일을 고치는 것과는 다르다.
"""
from __future__ import annotations

from typing import Any, Awaitable, Callable

import asyncio

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

# ⚠️ 외부 서버 왕복이 4~13초다. 제한이 없으면 여러 요청이 공유 스레드 풀을 오래
# 붙들어 **태거뿐 아니라 생성·파일 작업까지 굶는다**(Codex CONCERN).
# 남의 서버에 무례하지 않은 수준이기도 하다.
_MAX_IN_FLIGHT = 2
_in_flight = asyncio.Semaphore(_MAX_IN_FLIGHT)

# 사용자 판단 2026-08-31: "Huggingface 시스템이고 검증된 Provider라 괜찮을 것
# 같습니다. [ 웹에서 사용 : 링크 ] 형태로만 붙여주시면 될 것 같습니다."
# -> 경고 배너를 걷고 **출처 링크 한 줄**만 남긴다. 어디로 가는지는 여전히 보인다.
SPACE_URL = "https://huggingface.co/spaces/SmilingWolf/wd-tagger"
EXTERNAL_NOTICE = "웹에서 사용"


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
            "space_url": SPACE_URL,
        }

    @app.post("/api/tagger/analyze")
    async def tagger_analyze(req: Request):
        # ⚠️ **본문을 읽기 전에** 크기를 본다. `await req.body()` 로 다 받아 놓고
        #    재면 거절하기 전에 이미 메모리를 먹는다(Codex BLOCK) - 헤더가 없거나
        #    거짓일 수 있으므로 아래 실제 길이 검사도 그대로 둔다(둘 다 필요하다).
        declared = req.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > UPLOAD_MAX_BYTES:
            return JSONResponse({"ok": False, "error": "이미지가 너무 큽니다."}, status_code=413)
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

        if _in_flight.locked() and _in_flight._value <= 0:
            # 기다리게 두면 공유 풀이 막힌다 - 바로 돌려보내고 다시 누르게 한다.
            return JSONResponse(
                {"ok": False, "error": "태그 분석이 이미 진행 중입니다. 잠시 후 다시 시도하세요."},
                status_code=429)
        try:
            async with _in_flight:
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
