"""Assist v2 앱 레이어 — 한국어 층 · 엔진(Boost v2 와 공유) · 이벤트 맵 · Fast Search 갈래를 묶는다.

요청 1건: 한국어 층(Kiwi) -> E2B 1회(한 줄 GBNF) -> 병합 -> 이벤트 맵(풀 >= 20) -> 조립.
설계·실측·함정: docs/ASSIST_V2_DESIGN_2026_09_23.md.

엔진은 Boost v2 의 llama-server 를 같이 쓴다. Assist 는 쓸 때마다 10분 임대를 쥔다 — Auto Boost 가 꺼져 있어도
그동안 엔진이 남아 다음 질문이 로드를 기다리지 않는다. 엔진·모델이 없으면 한국어 층만으로 답하고 이유를 싣는다.
"""

from __future__ import annotations

import collections
import json
import threading
import time
from pathlib import Path
from typing import Any

ASSIST_LEASE_SECONDS = 600.0
MIN_POOL = 20                 # Random 풀 최소 게시물(사용자 결정 2026-09-23) — 1건 풀은 매번 같은 것을 뽑는다
MODEL_TIMEOUT = 60.0
MODEL_MAX_TOKENS = 600        # 200 은 잘렸다(실측)
MAX_NAME_CHOICES = 8
_LOCK = threading.Lock()
_INSTALLER_LOCK = threading.Lock()
_WARM_LOCK = threading.Lock()
_GRAMMAR: str | None = None
_GENDERS: dict[str, str] | None = None


def _grammar() -> str:
    global _GRAMMAR
    if _GRAMMAR is None:
        from core.assist_v2 import compact_grammar

        _GRAMMAR = compact_grammar()
    return _GRAMMAR


def _genders(context: Any) -> dict[str, str]:
    """캐릭터 태그 -> girl/boy(`data/character_analysis.json`, 13,497명). 큰 파일이라 한 번만 읽고 작은 표만 쥔다."""
    global _GENDERS
    if _GENDERS is None:
        out: dict[str, str] = {}
        try:
            path = Path(getattr(context, "repo_root", ".")) / "data" / "character_analysis.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            for chars in data.values():
                for name, info in (chars or {}).items():
                    gender = (info or {}).get("gender")
                    if gender in ("girl", "boy"):
                        out[str(name)] = gender
        except Exception:
            pass
        _GENDERS = out
    return _GENDERS


def korean_layer(context: Any) -> Any:
    """세션 컨텍스트에 붙은 한국어 층 하나. 사전은 여기서 만들고, Kiwi 는 ``warm()`` 이 따로 올린다(수 초)."""
    with _LOCK:
        layer = getattr(context, "assist_korean_layer", None)
        if layer is not None:
            return layer
        from app.backend.server.autocomplete_commands import _ensure_kr_raw
        from core.artist_affinity import default_pack
        from core.assist_korean import KoreanLayer, build_vocab

        raw = _ensure_kr_raw(context) or {}
        pack = default_pack()
        exists = _tag_exists_fn(context, raw)
        vocab = build_vocab(raw, genders=_genders(context), character_rank=lambda tag: pack.posts(tag, "character"),
                            tag_exists=exists)
        layer = KoreanLayer(vocab)
        context.assist_korean_layer = layer
        return layer


def get_kiwi_installer(context: Any) -> Any:
    """한국어 분석기(Kiwi)를 처음 쓸 때 설치하는 것 — 세션에 하나(core.assist_kiwi, 사용자 결정 2026-09-23).
    설치가 끝나면 한국어 층을 바로 데워 첫 질문이 준비를 기다리지 않게 한다."""
    with _INSTALLER_LOCK:
        installer = getattr(context, "assist_kiwi_installer", None)
        if installer is None:
            from app.backend.server.boost_v2_service import _save_root
            from core.assist_kiwi import KiwiInstaller

            installer = KiwiInstaller(log_path=_save_root(context) / "logs" / "assist_kiwi_install.log",
                                      on_installed=lambda: korean_layer(context).warm())
            context.assist_kiwi_installer = installer
        return installer


def _event_map(context: Any) -> Any:
    from core.event_map.random_link import ensure_event_map_service

    return ensure_event_map_service(context)


def _tag_exists_fn(context: Any, raw: dict[str, Any]):
    def exists(tag: str) -> bool:
        try:
            return _event_map(context).index().resolve(tag) is not None
        except Exception:
            return tag in raw          # 이벤트 맵이 없으면 태그 사전으로라도
    return exists


def _tag_vocab(context: Any, layer: Any) -> Any:
    from app.backend.server.autocomplete_commands import _ensure_kr_raw, search_kr_tags
    from core.assist_v2 import TagVocab

    def fuzzy(ko: str) -> list[str]:
        try:
            return [str(r.get("tag")) for r in search_kr_tags(context, ko, limit=5) if r.get("tag")]
        except Exception:
            return []

    try:
        idx = _event_map(context).index()
    except Exception:
        raw = _ensure_kr_raw(context) or {}

        def freq(tag: str) -> int:
            try:
                return int((raw.get(tag) or {}).get("freq") or 0)
            except (TypeError, ValueError):
                return 0
        return TagVocab(canonical=lambda t: t if t in raw else None, count=freq, keyword=layer.vocab.scene_tags,
                        fuzzy=fuzzy)

    def canonical(tag: str) -> str | None:
        tid = idx.resolve(tag)
        return idx.by_id[tid] if tid is not None else None

    def count(tag: str) -> int:
        tid = idx.resolve(tag)
        return int(idx.observed[tid]) if tid is not None else 0

    def role(tag: str) -> str | None:
        tid = idx.resolve(tag)
        return idx.role.get(tid) if tid is not None else None

    return TagVocab(canonical=canonical, count=count, role=role, keyword=layer.vocab.scene_tags, fuzzy=fuzzy)


def warm_assist(context: Any) -> None:
    """창을 열 때: Kiwi · 한국어 퍼지 검색 · 엔진 · 지시문 캐시를 뒤에서 데운다 — 첫 질문이 기다리지 않게.

    실측: 퍼지 검색의 첫 호출이 색인을 만드느라 약 6초, 지시문(약 1,100토큰) 첫 처리가 5090 에서 3.2초였다.
    """
    def _warm() -> None:
        try:
            korean_layer(context).warm()
        except Exception:
            pass
        try:
            from app.backend.server.autocomplete_commands import search_kr_tags

            search_kr_tags(context, "준비", limit=1)
        except Exception:
            pass
        try:
            from app.backend.server.boost_v2_service import get_boost_runtime
            from core.assist_v2 import SYSTEM_PROMPT, user_message

            runtime = get_boost_runtime(context)
            runtime.hold("assist", ASSIST_LEASE_SECONDS)
            status = runtime.status()
            if status.get("engine_exists") and status.get("model_exists") and runtime.warm():
                # 지시문을 한 번 태워 캐시에 올린다(단일 슬롯 — Boost 가 끼면 다시 비워질 수 있다)
                runtime.chat(user_message("안녕"), system=SYSTEM_PROMPT, grammar=_grammar(), max_tokens=80,
                             temperature=0.2, timeout=MODEL_TIMEOUT)
        except Exception:
            pass

    threading.Thread(target=_warm, daemon=True, name="assist-v2-warm").start()


def _warm_korean_async(context: Any) -> None:
    """한국어 층만 뒤에서 데운다(입력하는 동안 불린다 — 겹쳐 띄우지 않는다)."""
    with _WARM_LOCK:
        if getattr(context, "assist_korean_warming", False):
            return
        context.assist_korean_warming = True

    def _run() -> None:
        try:
            korean_layer(context).warm()
        except Exception:
            pass
        finally:
            context.assist_korean_warming = False

    threading.Thread(target=_run, daemon=True, name="assist-korean-warm").start()


def assist_names(context: Any, payload: Any) -> dict[str, Any]:
    """입력하는 동안 칠할 캐릭터 이름(모델 없이, 1ms 안팎). 후보가 여럿이면 화면이 사용자에게 목록을 보인다.

    준비(사전 수 초 · Kiwi 수 초)를 기다리지 않는다 — 안 됐으면 뒤에서 데우고 ready=false. 중괄호 이름은
    사전만 있으면 Kiwi 없이도 찾는다."""
    from core.assist_v2 import MAX_TEXT

    text = str((payload or {}).get("text") or "")[:MAX_TEXT] if isinstance(payload, dict) else ""
    layer = getattr(context, "assist_korean_layer", None)
    if layer is None or not layer.ready():
        _warm_korean_async(context)
    if layer is None:
        return {"ok": True, "ready": False, "names": [], "spans": []}
    return {"ok": True, "ready": layer.ready(), **layer.name_spans(text, use_kiwi=layer.ready())}


def assist_status(context: Any) -> dict[str, Any]:
    from app.backend.server.boost_v2_service import get_boost_runtime

    layer = getattr(context, "assist_korean_layer", None)
    try:
        status = get_boost_runtime(context).status()
    except Exception as exc:
        status = {"error": str(exc)}
    try:
        kiwi = get_kiwi_installer(context).snapshot()
    except Exception as exc:
        kiwi = {"installed": False, "error": str(exc)}
    return {
        "ok": True,
        "engine_ready": bool(status.get("engine_exists")),
        "model_ready": bool(status.get("model_exists")),
        "running": bool(status.get("running")),
        "korean_ready": bool(layer is not None and layer.ready()),
        "korean_error": getattr(layer, "error", None) if layer is not None else None,
        "kiwi": kiwi,              # 설치 전이면 화면이 [설치(약 90MB)]를 보인다 — 없어도 Assist 는 모델만으로 돈다
        "leases": status.get("leases"),
    }


# ── 요청 ─────────────────────────────────────────────────────────────────────


class AssistError(ValueError):
    pass


def _parse_payload(context: Any, payload: Any) -> dict[str, Any]:
    from core.assist_v2 import MAX_TEXT, RATINGS

    if not isinstance(payload, dict):
        raise AssistError("요청 형식이 잘못됐습니다.")
    text = str(payload.get("text") or "").strip()
    if not text:
        raise AssistError("무엇을 찾을지 적어 주세요.")
    if len(text) > MAX_TEXT:
        raise AssistError(f"요청은 {MAX_TEXT}자까지입니다.")
    rating = str(payload.get("rating") or "g").strip().lower()
    if rating not in RATINGS:
        raise AssistError("등급은 G/S/Q/E 중 하나입니다.")
    persons = payload.get("persons") or {"mode": "auto"}
    if not isinstance(persons, dict) or persons.get("mode") not in ("auto", "manual"):
        raise AssistError("인원 설정이 잘못됐습니다.")
    if persons["mode"] == "manual":
        try:
            girls, boys = int(persons.get("girls") or 0), int(persons.get("boys") or 0)
        except (TypeError, ValueError) as exc:
            raise AssistError("인원 수가 잘못됐습니다.") from exc
        if not (0 <= girls <= 9 and 0 <= boys <= 9) or girls + boys == 0:
            raise AssistError("인원은 여성·남성 합쳐 1~9명입니다.")
        persons = {"mode": "manual", "girls": girls, "boys": boys}
    previous = payload.get("previous")
    if previous is not None and not isinstance(previous, dict):
        previous = None
    # 사용자가 이름 후보 목록에서 고른 것(이름 -> 캐릭터 태그). 화면이 요청마다 다시 보낸다(기억이 짧다).
    raw_names = payload.get("names") or {}
    if not isinstance(raw_names, dict) or len(raw_names) > MAX_NAME_CHOICES or not all(
            isinstance(k, str) and isinstance(v, str) and 0 < len(k.strip()) <= 40 and 0 < len(v.strip()) <= 120
            for k, v in raw_names.items()):
        raise AssistError("이름 선택이 잘못됐습니다.")
    from core.assist_korean import clean_text

    choices = {clean_text(k).strip(): v.strip() for k, v in raw_names.items()}
    # 사용자가 '이름 아님' 으로 고른 낱말(호두를 먹는 -> 호두는 캐릭터가 아니다)
    raw_not = payload.get("not_names") or []
    if not isinstance(raw_not, list) or len(raw_not) > MAX_NAME_CHOICES or not all(
            isinstance(x, str) and 0 < len(x.strip()) <= 40 for x in raw_not):
        raise AssistError("이름 선택이 잘못됐습니다.")
    not_names = sorted({clean_text(x).strip() for x in raw_not})
    api_mode = str(payload.get("api_mode") or "")
    if not api_mode:
        try:
            api_mode = str(context.get_api_mode())
        except Exception:
            api_mode = str(getattr(context, "current_api_mode", "NAI") or "NAI")
    return {"text": text, "rating": rating, "persons": persons, "previous": previous, "api_mode": api_mode,
            "choices": choices, "not_names": not_names}


def _call_model(context: Any, text: str, previous: dict[str, Any] | None) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """E2B 1회. (route | None, 기록). 엔진·모델이 없거나 실패하면 route=None — 한국어 층만으로 간다."""
    from app.backend.server.boost_v2_service import get_boost_runtime
    from core.assist_v2 import SYSTEM_PROMPT, parse_route, user_message

    info: dict[str, Any] = {}
    try:
        runtime = get_boost_runtime(context)
        runtime.hold("assist", ASSIST_LEASE_SECONDS)
        status = runtime.status()
        if not status.get("engine_exists"):
            info["error"] = "llama.cpp 엔진이 없습니다."
            info["code"] = "engine_missing"
            return None, info
        if not status.get("model_exists"):
            info["error"] = "E2B 모델이 없습니다 — Auto Boost 설정에서 [모델 받기]를 눌러 주세요."
            info["code"] = "model_missing"
            return None, info
        resp = runtime.chat(user_message(text, previous), system=SYSTEM_PROMPT, grammar=_grammar(),
                            max_tokens=MODEL_MAX_TOKENS, temperature=0.2, timeout=MODEL_TIMEOUT)
        info.update({k: resp.get(k) for k in ("elapsed", "usage", "load_seconds", "queue_wait", "gpu") if k in resp})
        if not resp.get("ok"):
            info["error"] = str(resp.get("error") or "모델 호출 실패")
            return None, info
        return parse_route(str(resp.get("text") or "")), info
    except Exception as exc:
        info["error"] = f"{type(exc).__name__}: {exc}"
        return None, info


def _fallback_route(ka: Any) -> dict[str, Any]:
    """모델 없이: 한국어 층이 찾은 것만으로 장면 검색."""
    return {"task": "scene" if (ka.specific or ka.verb_tags) else "other", "goal": "find", "characters": [],
            "actions": [], "include": [], "exclude": [], "name": "", "name_ko": ""}


def run_assist(context: Any, payload: Any) -> dict[str, Any]:
    from core.assist_v2 import GUIDE, make_recap, merge

    started = time.perf_counter()
    try:
        req = _parse_payload(context, payload)
    except AssistError as exc:
        return {"ok": False, "error": str(exc)}
    layer = korean_layer(context)
    t = time.perf_counter()
    layer.warm()
    ka = layer.analyze(req["text"])
    choices = req["choices"]
    ka.names = [layer.choose(h, choices) for h in ka.names      # 사용자가 고른 캐릭터가 게시물 수 순위를 이긴다
                if h.form not in req["not_names"]]              # '이름 아님' 은 인물에서 뺀다
    korean_ms = round((time.perf_counter() - t) * 1000, 1)
    route, model = _call_model(context, req["text"], req["previous"])
    if route is None:
        route = _fallback_route(ka)
    vocab = _tag_vocab(context, layer)
    rules = layer.rules
    merged = merge(route, ka, vocab, text=req["text"], generic=rules["generic_tags"],
                   simile_particles=rules["simile_particles"],
                   name_lookup=lambda form: layer.choose(layer.name_hit(form), choices),
                   not_names=list(rules["not_names"]) + req["not_names"], poses=rules["poses"],
                   roles_for=lambda names: layer.roles_for(ka, names))
    out: dict[str, Any] = {
        "ok": True, "task": merged.task, "goal": merged.goal, "rating": req["rating"],
        # 후보 전체를 싣는다 — 모델이 찾은 이름(호두)도 화면에서 고를 수 있게
        "names": [{"ko": c.ko, "tag": c.tag, "alts": c.alts, "gender": c.gender, "chosen": c.ko in choices,
                   "candidates": layer.candidate_list(c.ko)} for c in merged.characters],
        "relations": [{"source": s, "action": a, "target": d} for s, a, d in merged.relations],
        "model": model,
        "trace": {"korean": ka.notes, "merge": merged.log,
                  "route": {k: v for k, v in route.items() if v not in ("", [], None)}},
    }
    t = time.perf_counter()
    if merged.task == "scene":
        out.update(_scene(context, layer, ka, merged, req, vocab))
    elif merged.task == "tag":
        out.update(_tags(context, merged, route))
    elif merged.task in ("character", "artist", "wildcard", "preset"):
        out.update(_lane(context, layer, merged, route, req))
    else:
        out["guide"] = GUIDE
    out["timing"] = {"korean_ms": korean_ms, "model_s": model.get("elapsed"),
                     "search_ms": round((time.perf_counter() - t) * 1000, 1),
                     "total_s": round(time.perf_counter() - started, 3)}
    if merged.task in ("scene", "tag"):
        partition = (out.get("persons") or {}).get("partition", "unknown")
        out["recap"] = make_recap(merged, partition=partition, rating=req["rating"])
    return out


def _persons(layer: Any, ka: Any, merged: Any, req: dict[str, Any]) -> dict[str, Any]:
    from core.assist_korean import PersonCount, partition_of

    if req["persons"]["mode"] == "manual":
        g, b = req["persons"]["girls"], req["persons"]["boys"]
        pc = PersonCount(girls=g, boys=b, partition=partition_of(g, b, g + b == 1))
        return {"mode": "manual", "partition": pc.partition, "girls": g, "boys": b, "unknown": 0,
                "confirm": False, "notes": [], "param": pc.persons_param()}
    pc = layer.count_persons(ka, extra_names=[c.ko for c in merged.characters], choices=req["choices"],
                             not_names=req["not_names"])
    return {"mode": "auto", "partition": pc.partition, "girls": pc.girls, "boys": pc.boys, "unknown": pc.unknown,
            "confirm": pc.confirm, "notes": pc.notes, "param": pc.persons_param()}


def _scene(context: Any, layer: Any, ka: Any, merged: Any, req: dict[str, Any], vocab: Any) -> dict[str, Any]:
    from core.assist_v2 import compose

    persons = _persons(layer, ka, merged, req)
    out: dict[str, Any] = {"persons": persons}
    candidates = merged.ordered(vocab.count)
    if not candidates:
        out["message"] = "요청에서 장면 태그를 찾지 못했습니다. 조금 더 구체적으로 적어 주세요."
        out["prompt"] = compose(merged, pins=[], leftovers=[], actions=[], partition=persons["partition"],
                                api_mode=req["api_mode"])
        return out
    try:
        service = _event_map(context)
        drill = service.drill(candidates=candidates, exclude=merged.exclude, ratings=req["rating"],
                              persons=persons["param"], min_posts=MIN_POOL)
    except Exception as exc:
        out["message"] = f"이벤트 맵을 쓸 수 없습니다: {exc}"
        out["prompt"] = compose(merged, pins=[], leftovers=candidates, actions=[], partition=persons["partition"],
                                api_mode=req["api_mode"])
        return out
    pins, left = list(drill.get("pins") or []), list(drill.get("left") or [])
    samples, actions = [], []
    if pins:
        try:
            s = service.sample(pins=pins, exclude=merged.exclude, ratings=req["rating"], persons=persons["param"], n=8)
            rows = s.get("samples") or []
            samples = [{"tags": r.get("tags") or [], "prompt": r.get("prompt") or ""} for r in rows[:3]]
            if not merged.has_action:
                actions = _sample_actions(service, rows, set(merged.all_tags()), layer.rules)
        except Exception:
            pass
    out.update({
        "pool": {"pins": ",".join(pins), "exclude": ",".join(drill.get("exclude") or []), "ratings": req["rating"],
                 "persons": persons["param"], "posts": int(drill.get("posts") or 0), "trail": drill.get("trail")},
        "leftovers": left, "actions": actions, "samples": samples,
        "prompt": compose(merged, pins=pins, leftovers=left, actions=actions, partition=persons["partition"],
                          api_mode=req["api_mode"]),
    })
    if not pins:
        out["message"] = "고른 등급·인원에서 이 조건을 함께 만족하는 게시물이 20건이 안 됩니다. 조건을 줄여 보세요."
    return out


def _sample_actions(service: Any, rows: list[dict[str, Any]], have: set[str], rules: dict[str, Any], k: int = 2) -> list[str]:
    """요청에 행동이 없을 때만: 중간 풀의 랜덤 표본에서 행동(event_core)만 받아온다(사용자 안). 등급은 고른 것 안에서."""
    idx = service.index()
    generic, poses = set(rules["generic_tags"]), set(rules["poses"])
    counter: collections.Counter[str] = collections.Counter()
    for row in rows:
        for tag in row.get("tags") or []:
            tid = idx.resolve(tag)
            if tid is not None and idx.role.get(tid) == "event_core" and tag not in have and tag not in generic:
                counter[tag] += 1
    has_pose = bool(have & poses)
    return [t for t, n in counter.most_common() if n >= 2 and not (has_pose and t in poses)][:k]


def _tags(context: Any, merged: Any, route: dict[str, Any]) -> dict[str, Any]:
    from app.backend.server.autocomplete_commands import _ensure_kr_raw

    raw = _ensure_kr_raw(context) or {}
    rows = []
    for tag in merged.all_tags()[:8]:
        info = raw.get(tag) or {}
        try:
            count = int(info.get("freq") or info.get("count") or 0)
        except (TypeError, ValueError):
            count = 0
        rows.append({"tag": tag, "count": count,
                     "desc": str(info.get("description") or info.get("desc") or "")[:160],
                     "keywords": str(info.get("keywords_kr") or "")[:120]})
    return {"tags": rows} if rows else {"tags": [], "message": "맞는 태그를 찾지 못했습니다."}


def _lane(context: Any, layer: Any, merged: Any, route: dict[str, Any], req: dict[str, Any]) -> dict[str, Any]:
    """캐릭터·작가·와일드카드·프리셋: Fast Search 같은 갈래. 캐릭터는 한-영 색인·이름 조각·팩 순위가 먼저."""
    import re

    from app.backend.server.fast_search_routes import SEARCHERS

    task = merged.task
    if task == "character" and merged.characters:
        return {"items": [{"value": c.tag, "title": c.tag, "subtitle": c.ko, "alts": c.alts, "gender": c.gender}
                          for c in merged.characters]}
    queries = [route.get("name_ko"), route.get("name"), re.sub(r"\s*\(.*?\)\s*$", "", route.get("name") or "")]
    for item in route.get("include") or []:
        queries += [item.get("ko"), item.get("en")]
    tried: list[str] = []
    for q in queries:
        q = str(q or "").strip()
        if not q or q in tried:
            continue
        tried.append(q)
        if task == "character":
            hit = layer.name_hit(q)
            if hit and hit.candidates:
                return {"query": q, "items": [{"value": t, "title": t, "subtitle": f"{n:,}", "gender": layer.vocab.genders.get(t)}
                                              for t, n in hit.candidates]}
        try:
            opts = {"mode": req["api_mode"]} if task == "preset" else {}
            items = SEARCHERS[task](context, q, 8, opts)[0]
        except Exception:
            items = []
        if items:
            return {"query": q, "items": items}
    return {"items": [], "tried": tried, "message": "찾지 못했습니다."}
