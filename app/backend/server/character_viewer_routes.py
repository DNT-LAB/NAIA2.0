from __future__ import annotations

import io
import re
import threading
from copy import deepcopy
import uuid as _uuid
from typing import Any, Awaitable, Callable

from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse, Response

from core.character_viewer_service import CharacterViewerService
from core.headless_generation_service import HeadlessGenerationService
from core.web_session_context import WebSessionContext


AsyncRunner = Callable[..., Awaitable[Any]]
GenerationRunnerStarter = Callable[[WebSessionContext, set[Any]], None]


_SERVICE_LOCK = threading.RLock()


def character_viewer_service(context: WebSessionContext) -> CharacterViewerService:
    # The download worker and first thumbnail request must share the same ZIP lock.
    with _SERVICE_LOCK:
        return _character_viewer_service(context)


def _character_viewer_service(context: WebSessionContext) -> CharacterViewerService:
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


from core.character_session_history import (
    roll_name_token, _session_roster, _roll_identity, history_payload,
)
from core.character_settings import SESSION_POOL_LOCK as _HIDE_LOCK


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
    lead = [pieces.pop(0)] if pieces and pieces[0].lower() in ("girl", "boy", "other") else []
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
    pin = tuple(roster.get("pin") or ())
    if pin and pin not in present:
        roster.pop("pin", None)
        pin = ()
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
        if not pin or identity == pin:
            pool.append((100, text))
    roster["lines"] = lines
    if pool:
        manager.session_wildcards[roster["key"]] = pool
    return len(present)


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



def _session_candidates(service: CharacterViewerService, payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Find 결과와 풀 합치기는 같은 검색 조건을 쓴다."""
    def values(key: str) -> list[str]:
        return [str(item) for item in payload.get(key) or [] if str(item or "").strip()]

    listed = service.build_list(
        str(payload.get("group") or CharacterViewerService.GROUP_ALL),
        str(payload.get("query") or ""), 0, 9,
        bool(payload.get("thumb_first", True)), True,
        bool(payload.get("recent_only")), bool(payload.get("favorites_only")),
        values("inc"), values("exc"),
        genders=values("genders") if "genders" in payload else values("gender"))
    return listed.get("all_items") or []


def _build_session_entries(service: CharacterViewerService, items: list[dict[str, Any]],
                           mode: str) -> list[tuple[str, tuple[str, str]]]:
    entries = []
    seen = set()
    for item in items:
        identity = (item["group"], item["character"])
        if identity in seen or service.is_hidden(*identity):
            continue
        seen.add(identity)
        built = service.build_prompt(*identity, "", {"hide_charname": False, "cosplay_enabled": False,
                                                    "auto_copyright": True}, mode)
        prompt = str(built.get("character_prompt") or "").strip()
        if prompt:
            entries.append((prompt, identity))
    return entries


def _extend_session_roster(service: CharacterViewerService, roster: dict[str, Any],
                           entries: list[tuple[str, tuple[str, str]]]) -> None:
    # 조회 중인 사전/목록은 고치지 않고 갈아 끼운다. 과거 줄의 모호성(None)도 보존한다.
    names = {token: list(owners) for token, owners in (roster.get("names") or {}).items()}
    lines = dict(roster.get("lines") or {})
    source = list(roster.get("source") or [])
    series = dict(roster.get("series") or {})
    works = dict(roster.get("works") or {})
    known = {tuple(identity) for _, identity in source}
    for line, identity in entries:
        if identity in known:
            continue
        known.add(identity)
        source.append((line, identity))
        if line in lines and lines[line] != identity:
            lines[line] = None
        else:
            lines.setdefault(line, identity)
        owners = names.setdefault(roll_name_token(line), [])
        if identity not in owners:
            owners.append(identity)
        series[identity] = _work_in_name(service, identity)
        works[identity] = _work_of(service, identity)
    # 풀 밖의 다른 작품까지 센다. 이름만으로 같은 이름의 다른 캐릭터를 확정하지 않는다.
    seen: dict[str, int] = {}
    for group, name, data in service._iter_all_chars():
        token = service.display_name(group, name, data).lower()
        seen[token] = seen.get(token, 0) + 1
    for token, owners in names.items():
        if seen.get(token, 0) > 1 and ("", "") not in owners:
            owners.append(("", ""))
    roster.update(names=names, lines=lines, source=source, series=series, works=works)


def _unique_session_key(context: WebSessionContext) -> str:
    """호출자는 _HIDE_LOCK 과 슬롯 commit 잠금을 보유한다. 다른 모드의 옛 키도 재사용하지 않는다."""
    import time as _time

    taken = set((getattr(getattr(context, "wildcard_manager", None), "session_wildcards", None) or {}).keys())
    for settings in context._character_service().settings_by_mode().values():
        for frame in (settings or {}).get("character_frames") or []:
            if isinstance(frame, dict):
                taken.update(match.strip("_") for match in re.findall(r"__\d{8}_\d{6}_cw__", str(frame.get("prompt") or "")))
    moment = _time.time()
    while True:
        candidate = _time.strftime("%Y%m%d_%H%M%S", _time.localtime(moment)) + "_cw"
        if candidate not in taken:
            return candidate
        moment += 1


def _install_session_pool(context: WebSessionContext, service: CharacterViewerService,
                          entries: list[tuple[str, tuple[str, str]]], mode: str) -> dict[str, Any]:
    """호출자는 _HIDE_LOCK 보유. Find 전체 생성과 한 명 추가가 공유하는 설치 경로."""
    from core.character_settings import _SESSION_SNAPSHOT_LOCK

    slots = context._character_service()
    with slots._commit_lock:
        kept = [(line, identity) for line, identity in entries if not service.is_hidden(*identity)]
        if not kept:
            raise _SessionPoolError(400, "담을 캐릭터가 없습니다.")
        key = _unique_session_key(context)
        roster = {"key": key, "pool_id": f"{key}#{_uuid.uuid4().hex[:12]}", "mode": mode,
                  "present": {identity for _, identity in kept}, "options": {}}
        _extend_session_roster(service, roster, kept)
        # 슬롯 서비스는 commit -> snapshot 순서다. snapshot을 먼저 잡고 서비스를 부르지 않는다.
        with _SESSION_SNAPSHOT_LOCK:
            state, made = slots.set_session_wildcard_slot(
                key, f"랜덤 · {len(kept):,}명", [line for line, _ in kept], expected_mode=mode)
            if state is None:
                raise _SessionPoolError(409, "만드는 사이 API 모드가 바뀌었습니다. 다시 눌러 주세요.")
            if not made:
                raise _SessionPoolError(400, "활성 캐릭터 슬롯이 꽉 찼습니다.")
            context.character_session_roster = roster
        return roster


class _SessionPoolError(ValueError):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def _refresh_session_pool(context: WebSessionContext, roster: dict[str, Any], manager: Any) -> int:
    """호출자는 _HIDE_LOCK 보유. 풀 변경/판 증가/라벨 저장을 기존 슬롯 잠금 순서로 묶는다."""
    from core.character_settings import _SESSION_SNAPSHOT_LOCK, bump_session_generation

    slots = context._character_service()
    with slots._commit_lock:
        with _SESSION_SNAPSHOT_LOCK:
            count = _rebuild_session_pool(roster, manager)
            bump_session_generation(context, roster["mode"])
            slots.update_session_pool_slot(roster["key"], roster["mode"], label=f"랜덤 · {count:,}명")
        return count


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
        # 사용자 썸네일 > 번들 팩 > 다운로드 확장 팩. 두 팩 모두 384px WebP라
        # grid 요청에서도 다시 줄이지 않고 해당 이미지 바이트만 돌려준다.
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
    async def api_character_viewer_groups(query: str = "", offset: int = 0, limit: int | None = None):
        try:
            return await run_in_thread(lambda: JSONResponse(
                character_viewer_service(session_context).build_groups(query, limit, offset)))
        except Exception as exc:
            return JSONResponse({"error": f"Character Viewer groups failed: {exc}"}, status_code=500)

    @app.get("/api/character-viewer/catalog")
    async def api_character_viewer_catalog():
        try:
            return await run_in_thread(lambda: JSONResponse(
                character_viewer_service(session_context).build_catalog()))
        except Exception as exc:
            return JSONResponse({"error": f"Character catalog failed: {exc}"}, status_code=500)

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
        gender: list[str] = Query(default=[]),
        compact: bool = False,
        offset: int | None = None,
        limit: int | None = None,
    ):
        try:
            group_key = str(group or CharacterViewerService.GROUP_ALL)
            return await run_in_thread(lambda: JSONResponse(
                character_viewer_service(session_context).build_list(
                    group_key, query, page, per_page, thumb_first, include_all,
                    recent_only, favorites_only, inc, exc, False, gender,
                    compact=compact, offset=offset, limit=limit)))
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
        payload = await session_pool_payload(req)
        service = character_viewer_service(session_context)
        mode = session_context.get_api_mode()

        def install() -> dict[str, Any]:
            entries = _build_session_entries(service, _session_candidates(service, payload), mode)
            with _HIDE_LOCK:
                return _install_session_pool(session_context, service, entries, mode)

        try:
            roster = await run_in_thread(install)
        except _SessionPoolError as exc:
            return JSONResponse({"error": str(exc)}, status_code=exc.status)
        except Exception as exc:
            return JSONResponse({"error": f"Session wildcard failed: {exc}"}, status_code=500)
        await broadcast_session_pool()
        from core.character_settings import read_reroll_on_generate

        return {"ok": True, "wildcard": roster["key"], "count": len(roster["present"]),
                "reroll_on_generate": bool(read_reroll_on_generate(session_context, mode))}

    async def session_pool_payload(req: Request) -> dict[str, Any]:
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        return payload if isinstance(payload, dict) else {}

    async def broadcast_session_pool() -> None:
        try:
            from app.backend.server.websocket_broadcast import broadcast_json

            await broadcast_json(clients, session_context.module_state_payload("character"))
        except Exception as exc:
            print(f"[CharacterViewer] session pool broadcast failed: {ascii(str(exc))}")

    @app.get("/api/character-viewer/session-pool")
    async def api_character_viewer_session_pool():
        service = character_viewer_service(session_context)

        def read() -> dict[str, Any]:
            service._refresh_search_sources()
            slots = session_context._character_service()
            with _HIDE_LOCK, slots._commit_lock:
                roster, manager = _session_roster(session_context)
                if roster is None:
                    return {"active": False}
                picks = list(getattr(manager, "session_picks", None) or [])
                counts: dict[tuple[str, str], int] = {}
                for line in picks:
                    identity = _roll_identity(roster, line)
                    if identity is not None:
                        counts[identity] = counts.get(identity, 0) + 1
                members = []
                for _, identity in roster["source"]:
                    if identity not in roster["present"]:
                        continue
                    try:
                        data = service._get_character(*identity)
                    except KeyError:
                        data = None
                    member = {"group": identity[0], "character": identity[1],
                              "line": _session_line_for(roster, identity), "picks": counts.get(identity, 0),
                              "gender": service.prompt_head(data) if data is not None else None,
                              "danbooru_posts": data.get("danbooru_posts") if data is not None else None,
                              "hidden": service.is_hidden(*identity)}
                    if data is None:
                        member["missing"] = True
                    elif service.has_thumbnail(*identity):
                        member["thumbnail_url"] = service._thumb_url(*identity, size="grid")
                    members.append(member)
                frames = slots.settings_for(roster["mode"]).get("character_frames") or []
                label = next((frame.get("custom_name", "") for frame in frames
                              if frame.get("session_wildcard") and f'__{roster["key"]}__' in str(frame.get("prompt") or "")), "")
                # 세션 와일드카드 창(2026-10-21): 와일드카드 이름 · 지금 출력 옵션 · 마지막으로 뽑힌 캐릭터(초록 표시).
                last = _roll_identity(roster, picks[-1]) if picks else None
                with session_context.result_store._mutation_lock:
                    history = history_payload(roster)
                return {"active": True, "key": roster["pool_id"], "label": label, "count": len(members),
                        "history_total": history["total"], "history_lost": history["lost"],
                        "total_picks": len(picks), "members": members,
                        "pin": ({"group": roster["pin"][0], "character": roster["pin"][1]}
                                if roster.get("pin") else None),
                        "wildcard": f'__{roster["key"]}__', "options": dict(roster.get("options") or {}),
                        "last_pick": {"group": last[0], "character": last[1]} if last else None}

        return await run_in_thread(read)

    async def mutate_session_pool(req: Request, action: str):
        payload = await session_pool_payload(req)
        service = character_viewer_service(session_context)
        identity = (str(payload.get("group") or "").strip(), str(payload.get("character") or "").strip())

        def apply() -> dict[str, Any]:
            slots = session_context._character_service()
            # HIDE -> commit -> snapshot. 슬롯 삭제/정규화가 상태 확인과 풀 변경 사이에 끼지 못한다.
            with _HIDE_LOCK, slots._commit_lock:
                roster, manager = _session_roster(session_context)
                if roster is not None and str(payload.get("key") or "") != roster["pool_id"]:
                    raise _SessionPoolError(409, "랜덤 슬롯이 새로 바뀌었습니다. 다시 눌러 주세요.")
                if action in ("add", "remove") and not all(identity):
                    raise _SessionPoolError(400, "group and character are required")
                if action == "add" and service.is_hidden(*identity):
                    raise _SessionPoolError(400, "숨긴 캐릭터입니다. Find [제외] 에서 되돌린 뒤 넣으세요.")
                if roster is None:
                    if action != "add":
                        raise _SessionPoolError(404, "랜덤 슬롯이 없습니다.")
                    # 낡은 풀에서 온 요청으로 지운 슬롯을 되살리지 않는다.
                    if payload.get("key"):
                        raise _SessionPoolError(409, "랜덤 슬롯이 새로 바뀌었습니다. 다시 눌러 주세요.")
                    mode = session_context.get_api_mode()
                    entries = _build_session_entries(service, [{"group": identity[0], "character": identity[1]}], mode)
                    roster = _install_session_pool(session_context, service, entries, mode)
                    return {"ok": True, "created": True, "key": roster["pool_id"], "count": 1}
                if action in ("add", "merge") and str(roster["mode"]) != str(session_context.get_api_mode()):
                    raise _SessionPoolError(409, "랜덤 슬롯을 만든 API 모드가 아닙니다. 그 모드에서 추가해 주세요.")
                present = set(roster["present"])
                if action == "clear":
                    from core.character_settings import _SESSION_SNAPSHOT_LOCK, bump_session_generation

                    with _SESSION_SNAPSHOT_LOCK:
                        slots.update_session_pool_slot(roster["key"], roster["mode"], remove=True)
                        manager.clear_session_wildcard()
                        session_context.character_session_roster = None
                        bump_session_generation(session_context, roster["mode"])
                    return {"ok": True, "count": 0}
                if action == "remove":
                    if identity not in present:
                        raise _SessionPoolError(404, "이 캐릭터는 지금 랜덤 풀에 없습니다.")
                    if len(present) == 1:
                        raise _SessionPoolError(409, "풀의 마지막 캐릭터입니다. [풀 비우기] 를 쓰세요.")
                    present.remove(identity)
                else:
                    if action == "add" and identity in present:
                        return {"ok": True, "already": True, "key": roster["pool_id"], "count": len(present)}
                    items = ([{"group": identity[0], "character": identity[1]}] if action == "add"
                             else _session_candidates(service, payload))
                    known = {tuple(owner) for _, owner in roster["source"]}
                    wanted = {(item["group"], item["character"]) for item in items
                              if not service.is_hidden(item["group"], item["character"])} - present
                    entries = _build_session_entries(service, [item for item in items
                        if (item["group"], item["character"]) in wanted - known], roster["mode"])
                    # 목록/프롬프트를 만드는 동안 모드를 바꾼 요청도 쓰기 전에 거절한다.
                    if str(roster["mode"]) != str(session_context.get_api_mode()):
                        raise _SessionPoolError(409, "만드는 사이 API 모드가 바뀌었습니다. 다시 눌러 주세요.")
                    added = (wanted & known) | {owner for _, owner in entries}
                    if action == "add" and not added:
                        raise _SessionPoolError(400, "담을 캐릭터가 없습니다.")
                    if not added:
                        return {"ok": True, "added": 0, "count": len(present)}
                    _extend_session_roster(service, roster, entries)
                    present.update(added)
                roster["present"] = present
                count = _refresh_session_pool(session_context, roster, manager)
                result = {"ok": True, "key": roster["pool_id"], "count": count}
                if action == "merge":
                    result["added"] = len(added)
                return result

        try:
            result = await run_in_thread(apply)
        except _SessionPoolError as exc:
            return JSONResponse({"error": str(exc)}, status_code=exc.status)
        except KeyError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        except Exception as exc:
            return JSONResponse({"error": f"Session pool {action} failed: {exc}"}, status_code=500)
        await broadcast_session_pool()
        return result

    @app.post("/api/character-viewer/session-pool/add")
    async def api_character_viewer_session_pool_add(req: Request):
        return await mutate_session_pool(req, "add")

    @app.post("/api/character-viewer/session-pool/remove")
    async def api_character_viewer_session_pool_remove(req: Request):
        return await mutate_session_pool(req, "remove")

    @app.post("/api/character-viewer/session-pool/merge")
    async def api_character_viewer_session_pool_merge(req: Request):
        return await mutate_session_pool(req, "merge")

    @app.post("/api/character-viewer/session-pool/clear")
    async def api_character_viewer_session_pool_clear(req: Request):
        return await mutate_session_pool(req, "clear")

    def require_session_pool(key: str):
        roster, manager = _session_roster(session_context)
        if roster is None or key != roster["pool_id"]:
            raise _SessionPoolError(409, "랜덤 슬롯이 새로 바뀌었습니다. 다시 눌러 주세요.")
        return roster, manager

    @app.post("/api/character-viewer/session-pool/pin")
    async def api_character_viewer_session_pool_pin(req: Request):
        payload = await session_pool_payload(req)

        def apply():
            from core.character_settings import _SESSION_SNAPSHOT_LOCK, bump_session_generation

            slots = session_context._character_service()
            with _HIDE_LOCK, slots._commit_lock:
                roster, manager = require_session_pool(str(payload.get("key") or ""))
                if not isinstance(payload.get("pin"), bool):
                    raise _SessionPoolError(400, "pin must be a boolean")
                identity = (str(payload.get("group") or "").strip(),
                            str(payload.get("character") or "").strip())
                if payload["pin"] and identity not in roster["present"]:
                    raise _SessionPoolError(400, "이 캐릭터는 지금 랜덤 풀에 없습니다.")
                with _SESSION_SNAPSHOT_LOCK:
                    if payload["pin"]:
                        roster["pin"] = identity
                    else:
                        roster.pop("pin", None)
                    count = _rebuild_session_pool(roster, manager)
                    bump_session_generation(session_context, roster["mode"])
                return {"ok": True, "key": roster["pool_id"], "count": count,
                        "pin": ({"group": identity[0], "character": identity[1]} if payload["pin"] else None)}

        try:
            result = await run_in_thread(apply)
        except _SessionPoolError as exc:
            return JSONResponse({"error": str(exc)}, status_code=exc.status)
        await broadcast_session_pool()
        return result

    @app.post("/api/character-viewer/session-pool/generate")
    async def api_character_viewer_session_pool_generate(req: Request):
        payload = await session_pool_payload(req)
        key = str(payload.get("key") or "")
        identity = (str(payload.get("group") or "").strip(), str(payload.get("character") or "").strip())

        def capture():
            from core.character_settings import (
                _SESSION_SNAPSHOT_LOCK, _frame_uuid, active_character_frames,
                read_character_roll_snapshot, read_frozen_character_slots, read_reroll_on_generate,
            )

            slots = session_context._character_service()
            with _HIDE_LOCK, slots._commit_lock, _SESSION_SNAPSHOT_LOCK:
                roster, _manager = require_session_pool(key)
                if not isinstance(payload.get("random"), bool):
                    raise _SessionPoolError(400, "random must be a boolean")
                if identity not in roster["present"]:
                    raise _SessionPoolError(400, "이 캐릭터는 지금 랜덤 풀에 없습니다.")
                mode = str(roster["mode"])
                if mode != str(session_context.get_api_mode()):
                    raise _SessionPoolError(409, "랜덤 슬롯을 만든 API 모드에서 생성해 주세요.")
                settings = deepcopy(slots.settings_for(mode))
                frames = active_character_frames(settings)
                target = next((frame for frame in frames if frame.get("session_wildcard")
                               and f'__{roster["key"]}__' in str(frame.get("prompt") or "")), None)
                if target is None:
                    raise _SessionPoolError(409, "캐릭터 모듈과 랜덤 슬롯을 켠 뒤 생성해 주세요.")
                line = _session_line_for(roster, identity)
                if not line.strip():
                    raise _SessionPoolError(400, "선택한 캐릭터의 출력 줄이 비어 있습니다.")
                metadata = getattr(getattr(session_context, "current_prompt_context", None), "metadata", None) or {}
                conditional_slots = metadata.get("_conditional_character_slots")
                original_frames = settings.get("character_frames") or []
                conditional = {}
                if (metadata.get("conditional_character_overrides") is not None
                        and isinstance(conditional_slots, list) and len(conditional_slots) == len(original_frames)):
                    conditional = {_frame_uuid(frame): deepcopy(value)
                                   for frame, value in zip(original_frames, conditional_slots) if isinstance(value, dict)}
                settings["character_frames"] = deepcopy(frames)
                return {"pool_id": key, "wildcard": roster["key"], "slot": _frame_uuid(target),
                        "line": line, "mode": mode, "settings": settings,
                        "snapshot": (None if read_reroll_on_generate(session_context, mode) else
                                     deepcopy(read_character_roll_snapshot(session_context, mode))),
                        "frozen": deepcopy(read_frozen_character_slots(session_context)), "conditional": conditional}

        try:
            selected = await run_in_thread(capture)
            service = _generation_service(session_context)
            # Use the normal dispatch error shape before advancing Random when no API is available.
            from core.generation_access_policy import access_policy
            from core.headless_generation_service import HeadlessGenerationDispatch

            policy = access_policy(session_context)
            if policy.blocked or not service._credential_for_mode(selected["mode"]):
                reason = policy.reason() if policy.blocked else f'{selected["mode"]} credential is not configured.'
                return JSONResponse(HeadlessGenerationDispatch(None, selected["mode"], reason).websocket_payload(),
                                    status_code=409)
            random_result = None
            if payload["random"]:
                from app.backend.server.generation_commands import handle_random_command

                # [랜덤+생성] 의 Random 은 **프롬프트만** 새로 뽑는다 - 그사이 랜덤 슬롯이 굴린 한 줄은 이 그림에 안 쓰인다
                # (이 요청은 고른 캐릭터로 나간다). 이 호출이 만드는 픽만 기록하지 않는다. 다른 동시 요청의 기록은 그대로 둔다.
                from core.wildcard_processor import suppress_session_pick_recording

                with suppress_session_pick_recording(session_context.wildcard_manager):
                    random_result = await handle_random_command(
                        None, session_context, clients,
                        {"type": "random", "random_request_id": f"session-pool-{_uuid.uuid4().hex}",
                         "force_naia_skip_generate": True},
                        start_generation_runner=start_generation_runner, enqueue=False,
                    )
                if not random_result.success:
                    return JSONResponse(random_result.websocket_payload(), status_code=409)

            def enqueue():
                # Random can await: revalidate pool/membership/mode before snapshotting and dispatch.
                selected_now = capture()
                with _HIDE_LOCK, session_context._character_service()._commit_lock:
                    roster, _manager = require_session_pool(key)
                    if identity not in roster["present"] or roster["mode"] != session_context.get_api_mode():
                        raise _SessionPoolError(409, "랜덤 슬롯이 새로 바뀌었습니다. 다시 눌러 주세요.")
                    overrides = {"_session_pool_character": selected_now, "auto_generate": False,
                                 "_remote_queue_source": "SessionPool", "_remote_queue_label": identity[1]}
                    if random_result is not None:
                        from app.backend.server.generation_runner import _reroll_random_resolution

                        _reroll_random_resolution(session_context, overrides)
                        if random_result.detected_resolution:
                            width, height = random_result.detected_resolution
                            overrides.update(width=width, height=height, resolution=f"{width} x {height}")
                    command = {"type": "generate", "api_mode": selected_now["mode"],
                               "prompt": random_result.prompt if random_result is not None else session_context.prompt_text,
                               "negative_prompt": session_context.negative_prompt_text, "overrides": overrides}
                    if random_result is not None and random_result.prompt_run_id:
                        command["prompt_run_id"] = random_result.prompt_run_id
                    return service.enqueue_remote_request(command)

            dispatch = await run_in_thread(enqueue)
        except _SessionPoolError as exc:
            return JSONResponse({"error": str(exc)}, status_code=exc.status)
        except Exception as exc:
            return JSONResponse({"error": f"Session pool generate failed: {exc}"}, status_code=500)
        if not dispatch.ok:
            return JSONResponse(dispatch.websocket_payload(), status_code=409)
        await broadcast_session_pool()
        if session_context.headless_generation_execute_enabled:
            start_generation_runner(session_context, clients)
        return dispatch.websocket_payload()

    def read_pool_history(key):
        with _HIDE_LOCK, session_context._character_service()._commit_lock:
            roster, _ = require_session_pool(key)
            with session_context.result_store._mutation_lock:
                return history_payload(roster)

    @app.get("/api/character-viewer/session-pool/history")
    async def api_character_viewer_session_pool_history(key: str = ""):
        try:
            return await run_in_thread(read_pool_history, key)
        except _SessionPoolError as exc:
            return JSONResponse({"error": str(exc)}, status_code=exc.status)

    @app.get("/api/character-viewer/session-pool/images")
    async def api_character_viewer_session_pool_images(key: str = "", group: str = "", character: str = ""):
        try:
            history = await run_in_thread(read_pool_history, key)
            identity = (group.strip(), character.strip())
            if not all(identity):
                raise _SessionPoolError(400, "group and character are required")
            from core.headless_result_service import HISTORY_ITEM_PREFIX

            items = [{"id": item["id"], "path": HISTORY_ITEM_PREFIX + item["id"],
                      "thumbnail_url": item["thumbnail_url"], "created": item["created"]}
                     for item in history["items"] if (item["group"], item["character"]) == identity]
            return {"items": items, "count": len(items)}
        except _SessionPoolError as exc:
            return JSONResponse({"error": str(exc)}, status_code=exc.status)

    @app.get("/api/character-viewer/session-pool/file")
    async def api_character_viewer_session_pool_file(key: str = "", id: str = "", size: str = "thumb"):
        # Same access policy as /api/history/image and /api/history/thumb:
        # neither existing image route has an extra loopback-only gate.
        def read():
            from pathlib import Path
            from types import SimpleNamespace
            from PIL import Image
            from core.result_image_payload_service import (
                image_media_type_for_bytes, memory_history_thumbnail_payload,
            )

            with _HIDE_LOCK, session_context._character_service()._commit_lock:
                roster, _ = require_session_pool(key)
                if size not in ("thumb", "full"):
                    raise _SessionPoolError(400, "size must be thumb or full")
                with session_context.result_store._mutation_lock:
                    entry = (roster.get("history") or {}).get(id)
                    if not entry or entry["in_memory"] or not entry["saved_path"]:
                        raise FileNotFoundError("Pool image not found")
                    path = entry["saved_path"]
            # Only the server-recorded path is used; request paths are never opened.
            raw = Path(path).read_bytes()
            if size == "full":
                return raw, image_media_type_for_bytes(raw)
            with Image.open(io.BytesIO(raw)) as opened:
                thumb = memory_history_thumbnail_payload(SimpleNamespace(image=opened))
            if not thumb:
                raise FileNotFoundError("Pool thumbnail unavailable")
            return thumb, "image/webp"

        try:
            content, media_type = await run_in_thread(read)
            return Response(content=content, media_type=media_type)
        except _SessionPoolError as exc:
            return JSONResponse({"error": str(exc)}, status_code=exc.status)
        except OSError:
            return JSONResponse({"error": "Pool image file not found"}, status_code=404)

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
            with _HIDE_LOCK, session_context._character_service()._commit_lock:
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
                        _refresh_session_pool(session_context, roster, manager)
                    result["session_count"] = len(present)
                return result

        try:
            result = await run_in_thread(apply)
            await broadcast_session_pool()
            return result
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

    @app.post("/api/character-viewer/quick-generate")
    async def api_character_viewer_quick_generate(req: Request):
        """Find 의 [생성](사용자 지시 2026-10-19) - 썸네일이 없는 캐릭터를 **Characters 탭 Generate 와 같은 사양**으로 한 장.
        저장된 Prefix · Postfix · 옵션(작품명 · 특징 자동 · 코스프레 …)으로 프롬프트를 만들고 896x1152 로 큐에 넣는다.
        나머지(모델 · 스텝 · 샘플러 · 네거티브)는 메인 생성 설정. 생성되면 그 캐릭터의 썸네일로 저장된다
        (generation_runner - 단 저장 안 함 · 캐릭터명 숨김 · 코스프레가 켜져 있으면 저장하지 않는다 → `save_blocked`)."""
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
        service = character_viewer_service(session_context)
        api_mode = session_context.get_api_mode()

        # 가상 캐릭터 슬롯(생성 설정 창 · 사용자 결정 2026-10-22)에서 고친 줄 · 네거티브가 오면 그것을 쓴다(없으면 지금처럼 만든다).
        # 추가 프롬프트(옵션 `character_extra`)는 어느 쪽이든 캐릭터 줄 뒤에 붙는다 - Find [생성] 도 같다.
        edited_prompt = payload.get("character_prompt")
        edited_uc = payload.get("character_uc")

        def build() -> tuple[dict[str, Any], dict[str, Any]]:
            options = service.load_options()
            prompt = service.build_prompt(group_key, name, "", options, api_mode)
            excluded = prompt.get("cosplay_excluded_pc")
            base = (str(edited_prompt).strip() if isinstance(edited_prompt, str) and edited_prompt.strip()
                    else str(prompt.get("character_prompt") or ""))
            extra = str(options.get("character_extra") or "").strip()
            character_prompt = ", ".join(part for part in (base.strip().rstrip(","), extra) if part)
            character_uc = (str(edited_uc) if isinstance(edited_uc, str)
                            else ", ".join(excluded) if isinstance(excluded, list) else "")
            request = {
                **options,
                "request_id": f"character-quick-{_uuid.uuid4().hex[:16]}",
                "group": group_key,
                "character": name,
                "variant": "",
                "character_prompt": character_prompt,
                "prefix": str(prompt.get("prefix") or ""),
                "postfix": str(prompt.get("postfix") or ""),
                "character_uc": character_uc,
            }
            return request, service.build_generation_overrides(request, api_mode)

        try:
            request, overrides = await run_in_thread(build)
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
        return {"ok": True, **dispatch.websocket_payload(), "request_id": request["request_id"],
                "save_blocked": bool(overrides.get("_character_viewer_snapshot", {}).get("save_blocked"))}

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
