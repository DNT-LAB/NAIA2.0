from __future__ import annotations

import io
import re
import threading
import uuid as _uuid
from typing import Any, Awaitable, Callable

from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse, Response

from core.character_viewer_service import CharacterViewerService
from core.headless_generation_service import HeadlessGenerationService
from core.web_session_context import WebSessionContext


AsyncRunner = Callable[..., Awaitable[Any]]
GenerationRunnerStarter = Callable[[WebSessionContext, set[Any]], None]


def character_viewer_service(context: WebSessionContext) -> CharacterViewerService:
    service = getattr(context, "character_viewer_service", None)
    if service is None:
        paths = context.runtime_paths
        save_root = paths.save_dir if paths is not None else None
        # 썸네일만 사용자 데이터 루트로 뺀다. `data_root` 는 넘기지 않는다 —
        # 번들 데이터(copyright_groups / character_analysis)가 리소스 트리에 있어야 해서
        # 통째로 바꾸면 탭이 죽는다(CharacterViewerService.__init__ 주석 참조).
        # 포터블: <install>/user-data/data/character_thumbnails  (업데이트 때 보존되는 유일한 곳)
        # 소스   : %APPDATA%/NAIA/data/character_thumbnails
        thumbnail_root = (paths.data_dir / "character_thumbnails") if paths is not None else None
        service = CharacterViewerService(context.repo_root, save_root=save_root,
                                         thumbnail_root=thumbnail_root)
        context.character_viewer_service = service
    return service


def roll_name_token(prompt: str) -> str:
    """캐릭터 프롬프트의 이름 자리(맨 앞 `girl` 다음 낱말) - 소문자 · SD 이스케이프(`\\(`) 를 걷는다."""
    tokens = [part.strip() for part in str(prompt or "").split(",") if part.strip()]
    if tokens and tokens[0].lower() in ("girl", "boy"):
        tokens = tokens[1:]
    return tokens[0].replace("\\", "").lower() if tokens else ""


def _session_roster(context: WebSessionContext) -> tuple[dict[str, Any] | None, Any]:
    """살아 있는 세션 와일드카드의 명단(이름 낱말 -> 그룹 · 캐릭터)과 와일드카드 관리자. 죽었으면 (None, 관리자)."""
    roster = getattr(context, "character_session_roster", None)
    manager = getattr(context, "wildcard_manager", None)
    live = getattr(manager, "session_wildcards", None) or {}
    if not isinstance(roster, dict) or roster.get("key") not in live:
        return None, manager
    return roster, manager


# 숨김(파일 쓰기 + 지금 풀에서 빼기)은 한 번에 하나씩 - 동시에 둘이 같은 풀을 베껴 갈아 끼우면 서로 뺀 것을 되살린다(Codex 리뷰).
_HIDE_LOCK = threading.Lock()


def _roll_identity(roster: dict[str, Any], prompt: str) -> tuple[str, str] | None:
    """프롬프트 -> (그룹, 캐릭터). 먼저 **줄 그대로**(같은 이름이 두 작품에 있어도 갈린다 - misumi uika), 안 되면 이름 자리로 -
    단 그 이름이 명단에서 **하나뿐**일 때만(둘 이상이면 어느 쪽인지 모른다 - 틀린 쪽에 별 · 숨김을 거느니 모른다고 한다)."""
    text = str(prompt or "").strip()
    lines = roster.get("lines") or {}          # 옵션이 바뀌면 새 사전으로 갈아 끼운다(`_rebuild_session_pool`) - 이 사전은 안 바뀐다
    if text in lines:
        # 풀의 줄 그대로다. None = 출력 옵션으로 둘 이상이 같은 줄이 됐다 - 이름으로 짐작하지 않는다(Codex 리뷰 15차:
        # `girl, shirayuki hime` 가 이름 사전의 다른 작품 캐릭터로 확정됐다).
        hit = lines[text]
        return tuple(hit) if hit else None
    # 랜덤 슬롯은 `__키__` 앞 · 뒤에 글을 붙일 수 있다(`smile, __키__`) - 그림의 글 **안에** 풀의 줄이 통째로 있으면 그것(긴 줄 먼저).
    # (값이 None 인 줄 = 출력 옵션으로 줄이 같아진 둘 이상 - 모른다.)
    #    ⚠️ 쉼표 토막 단위로 이어져 있어야 하고, 그 줄의 이름이 사전에서 **하나뿐**이어야 한다 - 짧은 줄이 다른 작품 같은 이름
    #    캐릭터 줄의 앞부분과 같을 수 있다(`girl, hello kitty (character)` - sanrio · vocaloid, Codex 리뷰).
    pieces = [piece.strip() for piece in text.split(",")]
    names = roster.get("names") or {}

    def contained(line: str) -> bool:
        want = [piece.strip() for piece in line.split(",")]
        return any(pieces[at:at + len(want)] == want for at in range(len(pieces) - len(want) + 1))

    inside = [line for line in lines if line and line in text and contained(line)]
    if inside:
        best = max(inside, key=len)
        owner = lines[best]
        if not owner:
            return None                    # 출력 옵션으로 같아진 줄 - 이름으로 짐작하지 않는다(Codex 리뷰 16차)
        original = any(line == best for line, _owner in roster.get("source") or [])
        # 원래 줄이면 그 이름이 사전에서 하나뿐이어야 한다(다른 작품 같은 이름의 앞부분일 수 있다 - hello kitty).
        # 옵션을 건 줄은 풀 안에서 같아지면 이미 None 이다.
        if not original or len(names.get(roll_name_token(best)) or []) == 1:
            return tuple(owner)
        return None
    # 줄이 그대로가 아니면(사람이 고친 그림 등) 쉼표 토막마다 이름을 찾는다 - 그 이름이 사전에서 **하나뿐**일 때만.
    for piece in text.split(","):
        owners = names.get(piece.strip().replace("\\", "").lower()) or []
        if len(owners) == 1:
            return tuple(owners[0])
    return None


# ── 랜덤 슬롯 출력 옵션(사용자 지시 2026-10-19) - 뽑힌 캐릭터 줄에서 무엇을 낼지 ──────────────────────────────
#   parens         캐릭터 이름 뒤 괄호를 전부 걷는다(`hoshino (armed) (blue archive)` -> `hoshino`)
#   drop_copyright 작품명 조각(`0.5::작품 ::` · `-1::blue archive ::` · SD `(작품:0.5)` · 그대로 쓴 작품명)을 뺀다
#   drop_name      캐릭터 이름을 뺀다(그림에서 캐릭터를 되찾을 수 없다 - 사용자 이해)
#   drop_features  색 · 특징을 뺀다([이름+작품만] = 이것 · [이름만] = 이것 + drop_copyright)
SESSION_OPTION_KEYS = ("parens", "drop_copyright", "drop_name", "drop_features")
_NAI_WEIGHTED = re.compile(r"^-?[\d.]+::.+::$")
_SD_WEIGHTED = re.compile(r"^\(.+:-?[\d.]+\)$")
_NAME_PAREN = re.compile(r"\s*\\?\([^()]*\\?\)")


def transform_session_line(line: str, owner: tuple[str, str] | None, options: dict[str, Any] | None,
                           series: str = "", work: str = "") -> str:
    """풀의 원래 줄(`girl, 이름, [작품], 색, 특징…`) -> 옵션을 건 줄. 옵션이 없으면 그대로.

    series = 이름에 든 작품(엔트리 `work_in_name` 이면 그 `copyright`). 괄호를 걷으면 이름에서 작품이 사라지므로 작품명 조각을 **양수**
    `0.5::작품 ::`(SD `(작품:0.5)`)로 바꾼다(사용자 결정 2026-10-19 - `serina, 0.5::blue archive ::`). [작품명 제거] 면 안 붙인다.
    """
    if not options or not any(options.get(key) for key in SESSION_OPTION_KEYS):
        return line
    pieces = [piece.strip() for piece in str(line or "").split(",") if piece.strip()]
    lead = [pieces.pop(0)] if pieces and pieces[0].lower() in ("girl", "boy") else []
    if not pieces:
        return line
    name = pieces.pop(0)
    # 그대로 쓴 작품명 조각은 그룹 **또는 그 캐릭터의 작품**(copyright) 과 같다(shadow hearts ii - Codex 리뷰 19차).
    plain_works = {value for value in (str((owner or ("", ""))[0] or "").lower(), str(work or "").lower()) if value}
    copyright_part = None
    if pieces:
        head = pieces[0]
        if _NAI_WEIGHTED.match(head) or _SD_WEIGHTED.match(head) or head.replace("\\", "").lower() in plain_works:
            copyright_part = pieces.pop(0)
    if options.get("parens"):
        bare = name
        while True:
            stripped = _NAME_PAREN.sub("", bare)
            if stripped == bare:
                break
            bare = stripped
        if bare.strip() and bare.strip() != name and series:
            # 이름에서 작품이 빠졌다 - 작품명 조각(대개 음수)을 양수 0.5 로. 없었으면(SD 등) 새로 단다.
            is_nai = bool(lead)
            copyright_part = (f"0.5::{series} ::" if is_nai
                              else f"({series.replace('(', chr(92) + '(').replace(')', chr(92) + ')')}:0.5)")
        name = bare.strip() or name
    out = list(lead)
    if not options.get("drop_name"):
        out.append(name)
    if copyright_part and not options.get("drop_copyright"):
        out.append(copyright_part)
    if not options.get("drop_features"):
        out.extend(pieces)
    # 다 뺐으면 빈 줄이다 - 고른 제거를 조용히 되돌리지 않는다(SD 는 앞머리 `girl` 이 없어 빌 수 있다 · Codex 리뷰 17차).
    return ", ".join(out)


def _work_of(service: CharacterViewerService, owner: tuple[str, str]) -> str:
    """그 캐릭터의 작품(`copyright` · 없으면 그룹)."""
    try:
        data = service._get_character(*owner)
    except KeyError:
        return owner[0]
    return str(data.get("copyright") or owner[0] or "").strip()


def _work_in_name(service: CharacterViewerService, owner: tuple[str, str]) -> str:
    """이름 끝 괄호가 그 캐릭터의 작품이면 그 작품(`copyright`), 아니면 ''."""
    try:
        data = service._get_character(*owner)
    except KeyError:
        return ""
    if not data.get("work_in_name"):
        return ""
    work = str(data.get("copyright") or owner[0] or "").strip()
    return "" if work == CharacterViewerService.ORIGINAL_GROUP else work


def _rebuild_session_pool(roster: dict[str, Any], manager: Any) -> int:
    """풀을 원래 줄에서 다시 만든다 - 지금 풀에 있는 캐릭터(`present`)만, 지금 옵션으로. 출력 줄 -> 캐릭터 명단도 늘린다
    (같은 줄이 둘 이상의 캐릭터에서 나오면 그 줄은 None = 모른다). 돌려주는 값 = 풀의 수."""
    options = roster.get("options") or {}
    present = roster.get("present") or set()
    # ⚠️ 새 사전에 쓰고 마지막에 갈아 끼운다 - 조회(`_roll_identity`)가 잠금 없이 같은 사전을 돌고 있을 수 있다
    #    ('dictionary changed size during iteration' · Codex 리뷰 20차).
    lines = dict(roster.get("lines") or {})
    pool: list[tuple[int, str]] = []
    for line, identity in roster.get("source") or []:
        identity = tuple(identity)
        if identity not in present:
            continue
        text = transform_session_line(line, identity, options, (roster.get("series") or {}).get(identity, ""),
                                      (roster.get("works") or {}).get(identity, ""))
        if text in lines and lines[text] is not None and tuple(lines[text]) != identity:
            lines[text] = None
        else:
            lines.setdefault(text, identity)
        pool.append((100, text))
    roster["lines"] = lines
    if pool:
        manager.session_wildcards[roster["key"]] = pool
    return len(pool)


def _session_line_for(roster: dict[str, Any], identity: tuple[str, str]) -> str:
    """그 캐릭터가 지금 옵션으로 나가는 줄 - [📌 고정] 이 이 줄로 슬롯을 만든다."""
    for line, owner in roster.get("source") or []:
        if tuple(owner) == tuple(identity):
            return transform_session_line(line, tuple(owner), roster.get("options") or {},
                                          (roster.get("series") or {}).get(tuple(owner), ""),
                                          (roster.get("works") or {}).get(tuple(owner), ""))
    return ""


# [와일드카드로 저장](사용자 지시 2026-10-19) - 파일 이름에 못 쓰는 글자.
_SAVE_NAME_BAD = set('/\\:*?"<>|')


def _session_save_lines(service: CharacterViewerService, roster: dict[str, Any]) -> list[str]:
    """[와일드카드로 저장] 이 쓸 줄 - 지금 풀에 있는 캐릭터(숨긴 것은 빠진다)를 **지금 출력 옵션**으로(사용자 결정 2026-10-19).
    풀(`_rebuild_session_pool`)과 같은 줄이다 - 저장한 파일을 쓰면 세션 슬롯과 같은 분포가 나온다."""
    options = roster.get("options") or {}
    present = roster.get("present") or set()
    lines: list[str] = []
    for line, identity in roster.get("source") or []:
        identity = tuple(identity)
        # 풀에서 빠진 것(숨김)은 물론, 다른 화면에서 숨겼지만 아직 풀에 남은 것도 뺀다.
        if identity not in present or service.is_hidden(*identity):
            continue
        text = transform_session_line(line, identity, options, (roster.get("series") or {}).get(identity, ""),
                                      (roster.get("works") or {}).get(identity, "")).strip()
        # 출력 옵션으로 줄이 비면 뺀다 - 와일드카드 파일은 빈 줄을 버린다(전부 비면 저장을 거절한다 · Codex 재리뷰).
        if text:
            lines.append(text)
    return lines


def _clean_save_name(name: str) -> str:
    clean = str(name or "").strip()
    if clean.lower().endswith(".txt"):
        clean = clean[:-4].strip()
    if not clean or clean.startswith(".") or any(ch in _SAVE_NAME_BAD for ch in clean):
        raise ValueError("이름에 / \\ : * ? \" < > | 는 쓸 수 없습니다.")
    return clean


def _roll_item(service: CharacterViewerService, roster: dict[str, Any], prompt: str) -> dict[str, Any] | None:
    hit = _roll_identity(roster, prompt)
    if not hit:
        return None
    group_key, name = hit
    try:
        data = service._get_character(group_key, name)
    except KeyError:
        return None
    return {"group": group_key, "character": name, "danbooru_posts": data.get("danbooru_posts"),
            "favorite": service.is_favorite(group_key, name), "hidden": service.is_hidden(group_key, name),
            "line": _session_line_for(roster, (group_key, name))}


def _generation_service(context: WebSessionContext) -> HeadlessGenerationService:
    service = getattr(context, "headless_generation_service", None)
    if service is None:
        service = HeadlessGenerationService(context)
        context.headless_generation_service = service
    return service


def _image_media_type(image_bytes: bytes) -> str:
    if image_bytes.startswith(b"\xff\xd8"):
        return "image/jpeg"
    if image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if image_bytes.startswith(b"RIFF") and image_bytes[8:12] == b"WEBP":
        return "image/webp"
    return "application/octet-stream"


def character_viewer_thumbnail_payload(
    context: WebSessionContext,
    group: str,
    character: str,
    variant: str = "",
    size: str = "",
) -> tuple[bytes, str, str]:
    """``(bytes, media_type, source_kind)`` — kind 는 ``"user"`` / ``"fallback"``.

    kind 를 같이 돌려주는 이유는 **캐시 정책이 출처마다 달라야** 하기 때문이다.
    사용자 썸네일은 덮어써지는 가변물이고 남의 눈에 띄면 안 되는 개인 이미지지만,
    번들 폴백은 릴리즈에 딸려오는 불변물이라 길게 캐시해도 된다.
    """
    service = character_viewer_service(context)
    group = str(group or "")
    character = str(character or "")
    variant = str(variant or "")
    try:
        path = service.thumbnail_path(group, character, variant)
    except FileNotFoundError:
        # **1순위는 사용자가 만든 썸네일, 2순위가 번들 미리보기 팩이다**(사용자 지정).
        # 여기까지 왔다는 것은 1순위가 없다는 뜻이라 폴백을 준다. 폴백은 이미 256px webp 라
        # 다시 줄이지 않는다 — grid 요청(384px)보다 작지만 목록 칸이 80px 이라 충분하다.
        raw = service.preview_thumb(group, character, variant)
        if raw is None:
            raise
        return raw, "image/webp", "fallback"
    size_key = str(size or "").strip().lower()
    if size_key == "grid":
        cache = getattr(context, "character_viewer_grid_thumb_cache", None)
        if not isinstance(cache, dict):
            cache = {}
            context.character_viewer_grid_thumb_cache = cache
        stat = path.stat()
        cache_key = (str(path), stat.st_mtime_ns, stat.st_size, size_key)
        cached = cache.get(cache_key)
        if cached is not None:
            # 캐시는 (bytes, media_type) 만 담는다 — 여기까지 온 것은 사용자 파일 경로다.
            return cached[0], cached[1], "user"
        from PIL import Image

        with Image.open(path) as image:
            image.thumbnail((384, 384), Image.Resampling.BILINEAR)
            if image.mode not in ("RGB", "RGBA"):
                image = image.convert("RGB")
            buffer = io.BytesIO()
            image.save(buffer, "WEBP", quality=72, method=0)
        payload = (buffer.getvalue(), "image/webp")
        if len(cache) > 256:
            cache.clear()
        cache[cache_key] = payload
        return payload[0], payload[1], "user"

    raw = path.read_bytes()
    return raw, _image_media_type(raw), "user"


def register_character_viewer_routes(
    app: FastAPI,
    session_context: WebSessionContext,
    *,
    run_in_thread: AsyncRunner,
    clients: set[Any],
    start_generation_runner: GenerationRunnerStarter,
) -> None:
    @app.get("/api/character-viewer/state")
    async def api_character_viewer_state():
        try:
            state = await run_in_thread(character_viewer_service(session_context).state)
            state["generation_delay_ms"] = 500
            return state
        except Exception as exc:
            return JSONResponse({"error": f"Character Viewer state failed: {exc}"}, status_code=500)

    @app.get("/api/character-viewer/groups")
    async def api_character_viewer_groups(query: str = ""):
        try:
            return await run_in_thread(character_viewer_service(session_context).build_groups, query)
        except Exception as exc:
            return JSONResponse({"error": f"Character Viewer groups failed: {exc}"}, status_code=500)

    @app.get("/api/character-viewer/list")
    async def api_character_viewer_list(
        group: str = "",
        query: str = "",
        page: int = 0,
        per_page: int = 48,
        thumb_first: bool = True,
        include_all: bool = False,
        recent_only: bool = False,
        favorites_only: bool = False,
        inc: list[str] = Query(default=[]),
        exc: list[str] = Query(default=[]),
    ):
        try:
            group_key = str(group or CharacterViewerService.GROUP_ALL)
            return await run_in_thread(
                character_viewer_service(session_context).build_list,
                group_key,
                query,
                page,
                per_page,
                thumb_first,
                include_all,
                recent_only,
                favorites_only,
                # Find [특징 검색] - 검색(inc) · 제외(exc) 낱말. 작품은 `work:<이름>`(사용자 지시 2026-10-19).
                inc,
                exc,
            )
        except Exception as exc:
            return JSONResponse({"error": f"Character Viewer list failed: {exc}"}, status_code=500)

    @app.get("/api/character-viewer/feature-suggest")
    async def api_character_viewer_feature_suggest(q: str = "", limit: int = 20):
        """Find [특징 검색] 자동완성 - 캐릭터 데이터에 있는 낱말(색 · 특징 · 가슴 · 작품)만.

        한글로 치면 메인 자동완성과 같은 태그 사전(`search_kr_tags` - 한국어 태그 사전 + 작품 · 캐릭터 이름 색인)이
        태그로 바꾸고, 그중 이 데이터에 있는 것만 남긴다(사용자 지시 2026-10-19: 한글 입력).
        """
        import re as _re

        text = str(q or "").strip()
        if not text:
            return {"rows": []}
        service = character_viewer_service(session_context)
        try:
            if _re.search(r"[가-힣ㄱ-ㅎㅏ-ㅣ]", text):
                from app.backend.server.autocomplete_commands import search_kr_tags, warm_tag_index_in_background

                # 태그 사전 색인이 아직이면 기다리지 않는다(Codex 리뷰: 첫 한글 검색이 15초) - 뒤에서 만들게 하고
                # '준비 중' 을 곧바로 돌려준다. 화면이 잠시 뒤 다시 묻는다(메인 자동완성의 pending 과 같은 뜻).
                if getattr(session_context, "tag_search_index", None) is None \
                        or int(getattr(session_context, "_tag_index_warming", 0) or 0) > 0:
                    await run_in_thread(warm_tag_index_in_background, session_context)
                    return {"rows": [], "pending": True}

                rows = await run_in_thread(search_kr_tags, session_context, text, 200)
                tags = [str(row.get("tag") or "") for row in rows]
                found = await run_in_thread(service.feature_suggest, text, tags, 50)
                # 띄어 쓰지 않은 말(분홍머리)은 사전이 못 찾는다 - 못 찾았으면 둘로 나눠 다시 찾는다(분홍 머리).
                compact = text.replace(" ", "")
                if not found["rows"] and len(compact) >= 3 and " " not in text:
                    for cut in range(1, len(compact)):
                        rows = await run_in_thread(search_kr_tags, session_context,
                                                   f"{compact[:cut]} {compact[cut:]}", 200)
                        tags += [str(row.get("tag") or "") for row in rows]
                    found = await run_in_thread(service.feature_suggest, text, tags, 50)
                # 사전의 차례는 낱말 뜻의 가까움이라 흔한 것이 뒤로 밀린다(분홍 -> pink hair 가 11번째) - 이 데이터의
                # 캐릭터 수가 많은 순으로 다시 세운다.
                ordered = sorted(found["rows"], key=lambda row: -int(row.get("count") or 0))
                return {"rows": ordered[:max(1, min(50, int(limit or 20)))]}
            return await run_in_thread(service.feature_suggest, text, None, limit)
        except Exception as exc:
            return JSONResponse({"error": f"Character feature suggest failed: {exc}"}, status_code=500)

    @app.post("/api/character-viewer/session-wildcard")
    async def api_character_viewer_session_wildcard(req: Request):
        """Find [현재 결과 -> 랜덤 와일드카드](사용자 지시 2026-10-19).

        지금 [캐릭터 · 작품] 의 결과 **전부**(이름 검색 + 필터)를 세션 와일드카드(파일이 없는 와일드카드)로 만들고
        그것을 쓰는 슬롯을 하나 넣는다(앞의 세션 슬롯은 바꾼다). 값 = [+ 슬롯] 이 넣는 프롬프트 그대로.
        슬롯 · 와일드카드 · 뽑힌 캐릭터는 히스토리에 남지 않는다(`character_settings` · `wildcard_processor`).
        """
        import time as _time

        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        query = str(payload.get("query") or "")
        inc = [str(item) for item in payload.get("inc") or [] if str(item or "").strip()]
        exc = [str(item) for item in payload.get("exc") or [] if str(item or "").strip()]
        service = character_viewer_service(session_context)
        mode = session_context.get_api_mode()

        names: dict[str, list[tuple[str, str]]] = {}
        # 줄 -> 캐릭터. 같은 줄이 둘 이상의 캐릭터에서 나오면 None(모름) - 작품을 copyright 로 통일하면 서로 다른 그룹의 같은
        # 캐릭터가 똑같은 줄이 된다(shiranui mai - street fighter · fatal fury · Codex 리뷰 19차). 풀에는 둘 다 남는다.
        line_owner: dict[str, tuple[str, str] | None] = {}
        entries: list[tuple[str, tuple[str, str]]] = []

        def build() -> list[str]:
            listed = service.build_list(CharacterViewerService.GROUP_ALL, query, 0, 9, True, True, False, False,
                                        inc, exc)
            lines: list[str] = []
            for item in listed.get("all_items") or []:
                built = service.build_prompt(item["group"], item["character"], "",
                                             {"hide_charname": False, "cosplay_enabled": False,
                                              "auto_copyright": True}, mode)
                prompt = str(built.get("character_prompt") or "").strip()
                if prompt:
                    lines.append(prompt)
                    # 디버그 줄이 뽑힌 줄 · 그림의 프롬프트에서 캐릭터를 되찾는 명단(이름 자리 -> 그룹 · 캐릭터).
                    identity = (item["group"], item["character"])
                    entries.append((prompt, identity))
                    if prompt in line_owner and line_owner[prompt] != identity:
                        line_owner[prompt] = None
                    else:
                        line_owner.setdefault(prompt, identity)
                    owners = names.setdefault(roll_name_token(prompt), [])
                    if identity not in owners:
                        owners.append(identity)
            return lines

        try:
            lines = await run_in_thread(build)
            # 이름이 사전의 **다른 작품에도** 있으면 이름만으로는 못 가린다 - 그 이름 자리는 줄이 그대로 맞을 때만 쓴다(Codex 리뷰).
            # (풀 밖의 같은 이름 캐릭터가 그림에 있으면 풀 안의 것으로 잘못 짚는다.)
            # ⚠️ 셀 때도 **프롬프트에 실리는 이름**으로 센다 - original 은 `이름 (작가)` 로 실려 다른 작품의 같은 글자 이름과
            #    겹칠 수 있다(lokulo-chan - Codex 리뷰).
            def mark_shared() -> None:
                seen: dict[str, int] = {}
                for group, name, data in service._iter_all_chars():
                    token = service.display_name(group, name, data).lower()
                    seen[token] = seen.get(token, 0) + 1
                for token, owners in names.items():
                    if seen.get(token, 0) > 1:
                        owners.append(("", ""))      # 둘 이상 = 이름만으로는 모른다
            await run_in_thread(mark_shared)
        except Exception as exc_:
            return JSONResponse({"error": f"Session wildcard failed: {exc_}"}, status_code=500)
        if not lines:
            return JSONResponse({"error": "담을 캐릭터가 없습니다."}, status_code=400)
        from core.character_settings import read_reroll_on_generate

        key = ""

        def unique_key() -> str:
            """초 단위 키가 이미 쓰이고 있으면(같은 초의 다른 풀 · 다른 모드에 남은 옛 슬롯) 1초씩 민다 - 키가 같으면 옛 슬롯이
            새 풀에 이어 붙었다(Codex 리뷰 29차). 풀 갈아 끼우기는 모두 `_HIDE_LOCK` 안이라 여기서 고른 키는 겹치지 않는다."""
            taken: set[str] = set((getattr(getattr(session_context, "wildcard_manager", None), "session_wildcards", None)
                                   or {}).keys())
            for settings in session_context._character_service().settings_by_mode().values():
                for frame in (settings or {}).get("character_frames") or []:
                    if isinstance(frame, dict):
                        taken.update(match.strip("_") for match in re.findall(r"__\d{8}_\d{6}_cw__", str(frame.get("prompt") or "")))
            moment = _time.time()
            while True:
                candidate = _time.strftime("%Y%m%d_%H%M%S", _time.localtime(moment)) + "_cw"
                if candidate not in taken:
                    return candidate
                moment += 1

        def install() -> tuple[bool, list[str]]:
            # 숨김과 같은 잠금 - 목록을 만든 뒤 그사이 숨긴 캐릭터를 여기서 한 번 더 뺀다(Codex 리뷰). 명단도 이 안에서 건다.
            nonlocal key
            with _HIDE_LOCK:
                kept_entries = [(line, identity) for line, identity in entries if not service.is_hidden(*identity)]
                kept = [line for line, _identity in kept_entries]
                if not kept:
                    return False, kept
                key = unique_key()
                # 와일드카드 등록과 슬롯 넣기는 서비스가 한 잠금 안에서 한다(Codex 리뷰). 줄을 만든 모드가 아니면 넣지 않는다.
                _state, made_ = session_context._character_service().set_session_wildcard_slot(
                    key, f"랜덤 · {len(kept):,}명", kept, expected_mode=mode)
                if _state is None:
                    raise ValueError("만드는 사이 API 모드가 바뀌었습니다. 다시 눌러 주세요.")
                if made_:
                    session_context.character_session_roster = {
                        "key": key, "names": names, "lines": dict(line_owner),
                        # 풀마다 하나뿐인 표 - 와일드카드 키는 초 단위라 같은 초에 만든 두 풀이 같은 키를 쓴다. 화면이 옵션 · 고정
                        # 요청에 이것을 실어 보내고 서버가 지금 풀과 맞춰 본다(Codex 리뷰 28차).
                        "pool_id": f"{key}#{_uuid.uuid4().hex[:12]}",
                        # 줄을 만든 모드 - [📌 고정] 은 이 모드에서만(다른 모드에 그 꼴의 줄을 넣지 않는다 · Codex 리뷰 30차).
                        "mode": mode,
                        # 원래 줄(옵션을 걸기 전) · 지금 풀에 있는 캐릭터 · 출력 옵션 - 옵션 · 숨김이 풀을 이것으로 다시 만든다.
                        "source": list(kept_entries),
                        "present": {identity for _line, identity in kept_entries},
                        "options": {},
                        # 이름에 든 작품(`work_in_name` 일 때 그 캐릭터의 `copyright`) - [괄호 제거] 때 작품명 조각을 +0.5 로.
                        "series": {identity: _work_in_name(service, identity) for _line, identity in kept_entries},
                        # 그 캐릭터의 작품(`copyright`) - 줄에서 작품명 조각을 가릴 때 그룹과 함께 본다(Codex 리뷰 19차).
                        "works": {identity: _work_of(service, identity) for _line, identity in kept_entries},
                    }
                return made_, kept

        try:
            made, lines = await run_in_thread(install)
        except ValueError as exc_:
            return JSONResponse({"error": str(exc_)}, status_code=409)
        if not lines:
            return JSONResponse({"error": "담을 캐릭터가 없습니다."}, status_code=400)
        if not made:
            return JSONResponse({"error": "활성 캐릭터 슬롯이 꽉 찼습니다."}, status_code=400)
        try:
            from app.backend.server.websocket_broadcast import broadcast_json

            await broadcast_json(clients, session_context.module_state_payload("character"))
        except Exception as exc_:
            print(f"[CharacterViewer] session wildcard broadcast failed: {ascii(str(exc_))}")
        return {"ok": True, "wildcard": key, "count": len(lines),
                "reroll_on_generate": bool(read_reroll_on_generate(session_context, mode))}

    @app.post("/api/character-viewer/session-roll")
    async def api_character_viewer_session_roll(req: Request):
        """랜덤 캐릭터 디버그 줄(사용자 지시 2026-10-19) - 세션 와일드카드가 뽑은 캐릭터.

        `prompts` 를 주면 **그 그림**의 캐릭터 프롬프트에서 찾는다(히스토리를 누른 때). 안 주면 **마지막으로 뽑힌 것**
        (Random · 생성 때). 세션 와일드카드가 없으면 `active: false`.
        `slot` = 랜덤 슬롯이 그 그림의 몇 번째 캐릭터인가(0부터) - 그 자리를 먼저 본다. 고정 슬롯의 캐릭터가 마침 풀에 있어도
        그것을 랜덤 캐릭터로 보이지 않게(Codex 리뷰). 그 자리에서 못 찾을 때만(옛 그림의 배치가 다르다) 나머지를 본다.
        """
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        prompts = payload.get("prompts")
        ids = payload.get("ids")
        service = character_viewer_service(session_context)

        def session_slot_index(image_ids: list[str] | None) -> int:
            """그 그림에서 랜덤 슬롯의 자리.

            그림이 슬롯 id(`_executed_character_ids` = 슬롯 uuid)를 들고 있으면 **그 그림의 차례**로 찾는다 - 지금 슬롯 차례로
            세면 그 뒤에 슬롯을 끄거나 옮긴 옛 그림에서 옆 캐릭터를 짚는다(Codex 리뷰). 없으면 -2(그 그림엔 이 랜덤 슬롯이 없다).
            id 가 없는 그림(디스크의 PNG)만 지금 차례로 센다 - 생성과 같은 `active_character_frames`(주석 · Connect 규칙까지).
            """
            from core.character_settings import _active_frame_slot_ids, active_character_frames

            settings = session_context._character_service().settings_for(session_context.get_api_mode())
            frames = active_character_frames(settings)
            slot_ids = _active_frame_slot_ids(frames)
            at = next((index for index, frame in enumerate(frames) if frame.get("session_wildcard")), -1)
            if image_ids:
                # 그림의 id 는 **지금 나가는지와 상관없이** 그 슬롯의 uuid 로 찾는다 - 그 뒤 슬롯을 꺼도(음소거) 옛 그림의
                # 캐릭터는 찾아야 한다(Codex 리뷰).
                from core.character_settings import _frame_uuid

                owns = {str(_frame_uuid(frame) or "") for frame in (settings or {}).get("character_frames") or []
                        if isinstance(frame, dict) and frame.get("session_wildcard")}
                return next((index for index, value in enumerate(image_ids) if value and value in owns), -2)
            return at

        def resolve() -> dict[str, Any]:
            roster, manager = _session_roster(session_context)
            if roster is None:
                return {"active": False}
            count = len((manager.session_wildcards or {}).get(roster["key"]) or [])
            if isinstance(prompts, list):
                texts = [str(text) for text in prompts]
                image_ids = [str(value) for value in ids] if isinstance(ids, list) and ids else None
                slot = session_slot_index(image_ids)
                if image_ids is not None:
                    # 그림이 자기 차례를 말한다 - 그 자리 하나만 본다(다른 자리의 고정 캐릭터를 짚지 않는다).
                    order = [texts[slot]] if 0 <= slot < len(texts) else []
                else:
                    order = ([texts[slot]] if 0 <= slot < len(texts) else []) + texts
                item = next((found for found in (_roll_item(service, roster, text) for text in order) if found), None)
                return {"active": True, "key": roster["pool_id"], "count": count, "source": "image", "item": item,
                        "options": dict(roster.get("options") or {})}
            picks = list(getattr(manager, "session_picks", None) or [])
            item = _roll_item(service, roster, picks[-1]) if picks else None
            # 뽑혔는데 못 가렸다 = 출력 옵션으로 줄이 같아졌거나(괄호 제거 · 이름 빼기) 이름이 없다 - 화면이 그렇게 말한다.
            return {"active": True, "key": roster["pool_id"], "count": count, "source": "last", "item": item,
                    "unresolved": bool(picks) and not item,
                    "options": dict(roster.get("options") or {})}

        try:
            return await run_in_thread(resolve)
        except Exception as exc:
            return JSONResponse({"error": f"Session roll failed: {exc}"}, status_code=500)

    @app.post("/api/character-viewer/session-options")
    async def api_character_viewer_session_options(req: Request):
        """랜덤 슬롯 출력 옵션(사용자 지시 2026-10-19 - 슬롯 아래 줄). 풀을 원래 줄에서 다시 만든다. 수명 = 그 슬롯(풀)."""
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        options = {key: bool(payload.get(key)) for key in SESSION_OPTION_KEYS}
        # 어느 풀에 거는가 - 그사이 새 풀로 바뀌었으면 거절한다(옛 풀의 요청이 새 풀 옵션을 바꾸지 않게 · Codex 리뷰 15차).
        pool_key = str(payload.get("key") or "")
        # 화면이 보고 있는 캐릭터 - 새 옵션으로 그 캐릭터가 나갈 줄을 함께 돌려준다(미리보기 · [📌 고정]).
        shown = (str(payload.get("group") or ""), str(payload.get("character") or ""))

        def apply() -> dict[str, Any]:
            with _HIDE_LOCK:
                roster, manager = _session_roster(session_context)
                if roster is None:
                    raise KeyError("랜덤 슬롯이 없습니다.")
                if pool_key != roster["pool_id"]:
                    raise ValueError("랜덤 슬롯이 새로 바뀌었습니다. 다시 눌러 주세요.")
                roster["options"] = options
                # 풀을 다시 만들고 판을 올리며 스냅샷을 버리는 것을 한 잠금 안에서 - 그 전에 시작한 굴림이 옛 줄을 되살리지 못한다
                # (Codex 리뷰 17 · 31 · 32 · 33차). 버리는 것은 풀을 만든 모드의 스냅샷이다.
                from core.character_settings import _SESSION_SNAPSHOT_LOCK, bump_session_generation

                with _SESSION_SNAPSHOT_LOCK:
                    count = _rebuild_session_pool(roster, manager)
                    bump_session_generation(session_context, roster.get("mode") or session_context.get_api_mode())
                return {"ok": True, "key": roster["pool_id"], "options": dict(options), "count": count,
                        "line": _session_line_for(roster, shown) if all(shown) else ""}

        try:
            result = await run_in_thread(apply)
        except KeyError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=409)
        except Exception as exc:
            return JSONResponse({"error": f"Session options failed: {exc}"}, status_code=500)
        # 스냅샷을 버렸다 - 패널의 '굴린 값' 표시도 맞춘다.
        try:
            from app.backend.server.websocket_broadcast import broadcast_json

            await broadcast_json(clients, session_context.module_state_payload("character"))
        except Exception as exc_:
            print(f"[CharacterViewer] session options broadcast failed: {ascii(str(exc_))}")
        return result

    @app.post("/api/character-viewer/session-pin")
    async def api_character_viewer_session_pin(req: Request):
        """[📌 고정] - 보이는 캐릭터를 지금 옵션의 줄로 맨 아래 슬롯에 켜고 랜덤 슬롯을 끈다(넣어졌을 때만 끈다)."""
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        pool_key = str(payload.get("key") or "")
        identity = (str(payload.get("group") or ""), str(payload.get("character") or ""))
        service = character_viewer_service(session_context)

        def apply() -> tuple[dict[str, Any], bool]:
            with _HIDE_LOCK:
                roster, _manager = _session_roster(session_context)
                if roster is None or pool_key != roster["pool_id"]:
                    raise ValueError("랜덤 슬롯이 새로 바뀌었습니다. 다시 눌러 주세요.")
                line = _session_line_for(roster, identity)
                if not line:
                    raise ValueError("이 캐릭터는 지금 랜덤 풀에 없습니다.")
                state, placed = session_context._character_service().pin_session_character(
                    line, identity[1], expected_mode=roster.get("mode"))
                if state is None:
                    raise ValueError("랜덤 슬롯을 만든 API 모드가 아닙니다. 그 모드에서 고정해 주세요.")
                return state, placed

        try:
            state, placed = await run_in_thread(apply)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=409)
        except Exception as exc:
            return JSONResponse({"error": f"Session pin failed: {exc}"}, status_code=500)
        try:
            from app.backend.server.websocket_broadcast import broadcast_json

            await broadcast_json(clients, session_context.module_state_payload("character"))
        except Exception as exc_:
            print(f"[CharacterViewer] session pin broadcast failed: {ascii(str(exc_))}")
        if not placed:
            return JSONResponse({"error": f"활성 캐릭터 슬롯이 꽉 차 고정하지 못했습니다."}, status_code=409)
        return {"ok": True, "character": identity[1]}

    @app.get("/api/character-viewer/session-save")
    async def api_character_viewer_session_save_info():
        """[와일드카드로 저장] 팝업 - 저장될 인원 수와 와일드카드 폴더 목록(와일드카드 관리 모듈의 Browse Files 와 같은 것)."""
        service = character_viewer_service(session_context)

        def info() -> dict[str, Any]:
            roster, _manager = _session_roster(session_context)
            if roster is None:
                raise KeyError("랜덤 슬롯이 없습니다.")
            return {"key": roster["pool_id"], "count": len(_session_save_lines(service, roster)),
                    "tree": session_context._wildcard_service().scan_tree()}

        try:
            return await run_in_thread(info)
        except KeyError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        except Exception as exc:
            return JSONResponse({"error": f"Session save info failed: {exc}"}, status_code=500)

    @app.post("/api/character-viewer/session-save")
    async def api_character_viewer_session_save(req: Request):
        """[와일드카드로 저장] - 지금 세션 풀(숨김 뺀 인원 · 지금 출력 옵션의 줄)을 와일드카드 파일로 쓴다.
        폴더는 최상층 폴더 하나 또는 비움(= 최상층). ⚠️ 같은 폴더에 같은 이름이 있으면 덮지 않고 거절한다(사용자 지정).
        랜덤 슬롯은 그대로 둔다(사용자 결정)."""
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        pool_key = str(payload.get("key") or "")
        folder = str(payload.get("folder") or "").strip().strip("/\\")
        service = character_viewer_service(session_context)

        def apply() -> dict[str, Any]:
            name = _clean_save_name(str(payload.get("name") or ""))
            if folder and (any(ch in _SAVE_NAME_BAD for ch in folder) or folder.startswith(".")):
                raise ValueError("폴더를 다시 고르세요.")
            wildcards = session_context._wildcard_service()
            with _HIDE_LOCK:
                roster, _manager = _session_roster(session_context)
                if roster is None or pool_key != roster["pool_id"]:
                    raise LookupError("랜덤 슬롯이 새로 바뀌었습니다. 다시 열어 주세요.")
                lines = _session_save_lines(service, roster)
            if not lines:
                raise ValueError("저장할 줄이 없습니다. 출력 옵션(이름만 · 캐릭터명 제거 등)을 확인하세요.")
            if folder:
                folder_path = wildcards.validate_path(folder)
                if folder_path is None or not folder_path.is_dir():
                    raise ValueError("그 폴더가 없습니다. 목록을 새로 열어 주세요.")
            rel = f"{folder}/{name}.txt" if folder else f"{name}.txt"
            target = wildcards.validate_path(rel)
            if target is None:
                raise ValueError("저장할 수 없는 위치입니다.")
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                # 'x' = 있으면 실패 - 확인과 쓰기 사이에 같은 이름이 생겨도 덮지 않는다.
                with target.open("x", encoding="utf-8", newline="\n") as handle:
                    handle.write("\n".join(lines) + "\n")
            except FileExistsError:
                raise FileExistsError("이 폴더에 같은 이름이 있습니다.") from None
            wildcards.reload_manager()
            return {"ok": True, "path": rel, "wildcard": f"__{rel[:-4]}__", "count": len(lines)}

        try:
            return await run_in_thread(apply)
        except FileExistsError as exc:
            return JSONResponse({"error": str(exc), "exists": True}, status_code=409)
        except LookupError as exc:
            return JSONResponse({"error": str(exc)}, status_code=409)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except Exception as exc:
            return JSONResponse({"error": f"Session save failed: {exc}"}, status_code=500)

    @app.get("/api/character-viewer/hidden")
    async def api_character_viewer_hidden_list():
        """Find 의 [제외] 목록 - 숨긴 캐릭터들."""
        try:
            return {"items": await run_in_thread(character_viewer_service(session_context).hidden_items)}
        except Exception as exc:
            return JSONResponse({"error": f"Character hidden list failed: {exc}"}, status_code=500)

    @app.post("/api/character-viewer/hidden")
    async def api_character_viewer_hidden(req: Request):
        """숨김을 켜고 끈다. 켤 때는 지금 세션 와일드카드에서도 뺀다 - 그대로 두면 숨긴 캐릭터가 계속 뽑힌다.
        (되돌려도 지금 와일드카드에 다시 넣지는 않는다 - 다음에 만드는 와일드카드부터 들어간다.)"""
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        group_key = str(payload.get("group") or "").strip()
        name = str(payload.get("character") or "").strip()
        if not group_key or not name:
            return JSONResponse({"error": "group and character are required"}, status_code=400)
        on = bool(payload.get("hidden", True))
        service = character_viewer_service(session_context)

        def apply() -> dict[str, Any]:
            with _HIDE_LOCK:
                roster, manager = _session_roster(session_context)
                identity = (group_key, name)
                present = roster.get("present") if roster is not None else None
                # 풀의 마지막 캐릭터는 못 숨긴다 - 비우면 슬롯이 '__키__' 를 그대로 내보낸다. 숨겼다고 해 놓고 계속 뽑히는
                # 것보다 거절이 낫다(Codex 리뷰). 저장도 하지 않는다.
                if on and present is not None and identity in present and len(present) == 1:
                    raise ValueError("랜덤 풀의 마지막 캐릭터라 숨길 수 없습니다. 슬롯을 지운 뒤 숨기세요.")
                result = service.set_hidden(group_key, name, on)
                # 풀 갈아 끼우기도 이 잠금 안이라(install) 그사이 풀이 바뀌지 않는다. 숨기면 풀에서 빼고 원래 줄로 다시 만든다.
                if on and present is not None:
                    if identity in present:
                        present.discard(identity)
                        _rebuild_session_pool(roster, manager)
                    result["session_count"] = len(present)
                return result

        try:
            return await run_in_thread(apply)
        except KeyError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=409)
        except Exception as exc:
            return JSONResponse({"error": f"Character hide failed: {exc}"}, status_code=500)

    @app.post("/api/character-viewer/favorite")
    async def api_character_viewer_favorite(req: Request):
        """도감 즐겨찾기를 켜고 끈다.

        ⚠️ 두 화면(캐릭터 탭 · 캐릭터 모듈 검색 탭)이 **같은 목록**을 본다. 저장소를
           하나로 두는 것이 이 라우트의 요점이다 - 나누면 한쪽에서 별을 켜고 다른 쪽에서
           안 보이는 상태가 된다.
        """
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        group_key = str(payload.get("group") or "").strip()
        name = str(payload.get("character") or "").strip()
        if not group_key or not name:
            return JSONResponse({"error": "group and character are required"}, status_code=400)
        favorite = bool(payload.get("favorite", True))
        try:
            return await run_in_thread(
                character_viewer_service(session_context).set_favorite,
                group_key,
                name,
                favorite,
            )
        except KeyError:
            return JSONResponse({"error": f"Character not found: {group_key}::{name}"},
                                status_code=404)
        except Exception as exc:
            return JSONResponse({"error": f"Character Viewer favorite failed: {exc}"},
                                status_code=500)

    @app.post("/api/character-viewer/detail")
    async def api_character_viewer_detail(req: Request):
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        try:
            return await run_in_thread(
                character_viewer_service(session_context).build_detail,
                str(payload.get("group") or ""),
                str(payload.get("character") or ""),
                str(payload.get("variant") or ""),
                payload.get("options") if isinstance(payload.get("options"), dict) else {},
                session_context.get_api_mode(),
            )
        except KeyError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        except Exception as exc:
            return JSONResponse({"error": f"Character Viewer detail failed: {exc}"}, status_code=500)

    @app.post("/api/character-viewer/prompt")
    async def api_character_viewer_prompt(req: Request):
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        try:
            return await run_in_thread(
                character_viewer_service(session_context).build_prompt,
                str(payload.get("group") or ""),
                str(payload.get("character") or ""),
                str(payload.get("variant") or ""),
                payload.get("options") if isinstance(payload.get("options"), dict) else payload,
                session_context.get_api_mode(),
            )
        except KeyError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        except Exception as exc:
            return JSONResponse({"error": f"Character Viewer prompt failed: {exc}"}, status_code=500)

    @app.post("/api/character-viewer/options")
    async def api_character_viewer_options(req: Request):
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        try:
            return await run_in_thread(character_viewer_service(session_context).save_options, payload)
        except Exception as exc:
            return JSONResponse({"error": f"Character Viewer options failed: {exc}"}, status_code=500)

    @app.get("/api/character-preset")
    async def api_character_preset(group: str = "", character: str = ""):
        # Interactive 캐릭터 프리셋 팝업이 여는 **단 한 번의 요청**이다.
        # 슬롯 배정표(data/character_presets.json)와 태그 사전 카드에 필요한
        # 설명/분류/빈도(tag_lookup_info)를 여기서 합쳐 준다 — 팝업 하나에 왕복을
        # 두 번 하지 않기 위해서다. 둘 다 순수 조회라 상태를 바꾸지 않는다.
        def _payload() -> dict[str, Any]:
            service = character_viewer_service(session_context)
            data = service.character_preset(group, character)
            # 순환 import 를 피하려고 함수 안에서 가져온다(같은 패키지의 다른 라우트 모듈).
            from app.backend.server.prompt_tools_routes import tag_lookup_info

            info: dict[str, Any] = {}
            try:
                looked = tag_lookup_info(session_context, data["name"])
            except Exception:
                looked = {}
            if isinstance(looked, dict) and looked.get("tag"):
                details = looked.get("character_details")
                info = {
                    "tag": looked.get("tag", ""),
                    "count": looked.get("count", 0),
                    "desc": looked.get("desc", ""),
                    "group": " > ".join(
                        part for part in (looked.get("group"), looked.get("subgroup")) if part
                    ),
                    "cat": looked.get("cat", ""),
                    "details": details if isinstance(details, dict) else {},
                }
            data["info"] = info
            return data

        try:
            return await run_in_thread(_payload)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except FileNotFoundError as exc:
            # 사전이 안 깔린 배포. 팝업이 이유를 그대로 보여줄 수 있게 문구를 살린다.
            return JSONResponse({"error": str(exc)}, status_code=503)
        except KeyError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        except Exception as exc:
            return JSONResponse({"error": f"Character preset failed: {exc}"}, status_code=500)

    @app.get("/api/character-viewer/thumbnail")
    async def api_character_viewer_thumbnail(
        group: str = "", character: str = "", variant: str = "", size: str = "", v: str = ""
    ):
        # `v` 는 캐시 버스트용 판(revision)이라 서버가 읽지 않는다. `_thumb_url` 이
        # 파일 mtime/크기로 만들어 붙이므로 **내용이 바뀌면 URL 이 바뀐다**.
        # 선례: `/api/prompt-engineering/preset-thumbnail` 이 같은 방식을 쓴다.
        try:
            image_bytes, media_type, source_kind = await run_in_thread(
                character_viewer_thumbnail_payload,
                session_context,
                group,
                character,
                variant,
                size,
            )
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except (FileNotFoundError, KeyError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        except Exception as exc:
            return JSONResponse({"error": f"Character Viewer thumbnail failed: {exc}"}, status_code=500)
        # 사용자 썸네일은 개인 이미지이자 가변물이라 `private`. 번들 폴백은 릴리즈에
        # 딸려오는 불변물이라 길게 캐시한다. **헤더만으로는 부족하다** — URL 이 그대로면
        # 신선한 캐시가 서버에 닿지도 않아 새 헤더를 받을 기회조차 없다. 위의 `v=` 와
        # 짝이어야 뜻이 산다.
        cache_control = (
            "private, max-age=3600" if source_kind == "user" else "public, max-age=86400"
        )
        return Response(
            content=image_bytes,
            media_type=media_type,
            headers={"Cache-Control": cache_control},
        )

    @app.post("/api/character-viewer/thumbnail/delete")
    async def api_character_viewer_thumbnail_delete(req: Request):
        # 확인 없이 즉시 삭제(사용자 지시). 파일 + index.json 항목을 함께 지운다.
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        try:
            result = await run_in_thread(
                character_viewer_service(session_context).delete_thumbnail,
                str(payload.get("group") or ""),
                str(payload.get("character") or ""),
                str(payload.get("variant") or ""),
            )
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except Exception as exc:
            return JSONResponse(
                {"error": f"Character Viewer thumbnail delete failed: {exc}"}, status_code=500
            )
        return {"ok": True, **result}

    @app.post("/api/character-viewer/generate")
    async def api_character_viewer_generate(req: Request):
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        try:
            overrides = await run_in_thread(
                character_viewer_service(session_context).build_generation_overrides,
                payload,
                session_context.get_api_mode(),
            )
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except KeyError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        dispatch = await run_in_thread(
            _generation_service(session_context).enqueue_remote_request,
            {"type": "generate", "overrides": overrides},
        )
        if not dispatch.ok:
            return JSONResponse(dispatch.websocket_payload(), status_code=409)
        if session_context.headless_generation_execute_enabled:
            start_generation_runner(session_context, clients)
        return {"ok": True, **dispatch.websocket_payload()}
