"""Assist v2 앱 레이어 — 한국어 층 · 엔진(Boost v2 와 공유) · 이벤트 맵 · Fast Search 갈래를 묶는다.

요청 1건: 한국어 층(Kiwi) -> E2B 1회(한 줄 GBNF) -> 병합 -> 이벤트 맵(풀 >= 20) -> 조립.
설계·실측·함정: docs/ASSIST_V2_DESIGN_2026_09_23.md.

엔진은 Boost v2 의 llama-server 를 같이 쓴다. Assist 는 쓸 때마다 10분 임대를 쥔다 — Auto Boost 가 꺼져 있어도
그동안 엔진이 남아 다음 질문이 로드를 기다리지 않는다. 엔진·모델이 없으면 한국어 층만으로 답하고 이유를 싣는다.
"""

from __future__ import annotations

import collections
import json
import re
import threading
import time
from pathlib import Path
from typing import Any, Iterable

ASSIST_LEASE_SECONDS = 600.0
MIN_POOL = 20                 # Random 풀 최소 게시물(사용자 결정 2026-09-23) — 1건 풀은 매번 같은 것을 뽑는다
# 등급 게이트: 고른 등급(G·S)의 게시물 비중이 이보다 낮은 태그는 뺀다(0.2% = 500건에 1건 미만). 실측 09-24 G 비중:
# looking at penis 0.07% · groping 0.08% · nipples 0.13% · nude 0.19% / bound wrists 4.6% · cleavage 2.7% · meat 63%
RATING_GATE = {"g": 0.002, "s": 0.002}
RATING_GATE_MIN_POSTS = 50    # 이보다 적게 달린 태그는 비중을 믿지 않는다(두고 본다)
# [생성](가상 프롬프트 한 장)에 붙이는 등급 태그 — 고른 등급대로 메인 끝에(사용자 지정 2026-09-26)
GENERATE_RATING_TAGS = {"g": ("safe", "rating:general"), "s": ("rating:sensitive",),
                        "q": ("nsfw", "rating:questionable"), "e": ("nsfw", "rating:explicit")}
MAX_PREFERENCE = 400          # 고급 설정의 User Preference(등급마다 영어 한두 문장) 글자 수 상한
MODEL_TIMEOUT = 60.0
MODEL_MAX_TOKENS = 600        # 200 은 잘렸다(실측)
MAX_NAME_CHOICES = 8
MAX_VIRTUAL_CHARACTERS = 6
MAX_FOLLOWUP_MAIN = 4000      # 이어 고치기가 받는 메인 프롬프트 글자 수 상한
# 직접 모드(_direct)가 모델 태그에서 가려내는 것 — 인원 태그(인원 칸이 정한다) · 품질 · 등급 태그(싣지 않는다)
_PEOPLE_TAG = re.compile(r"\d+\+?(?:girl|boy|other)s?|multiple (?:girls|boys|others)|solo|no humans")
# 이어 고치기: 캐릭터 이름 바로 뒤가 이것이면 그 칸은 고칠 대상이 아니다(공백을 뺀 글에서 — '나히다는 그대로 두고')
_SPARE_TAILS = ("는그대로", "은그대로", "그대로", "말고", "는말고", "은말고", "빼고", "는빼고", "은빼고", "는두고", "은두고",
                "제외", "는제외", "은제외")
# 괄호가 든 사전 이름 꼴(nahida (genshin impact)) — 이어 고치기가 뺄 수 있는 괄호 조각은 이것뿐(가중치 (x) · (x:1.2) 는 아니다)
_QUALIFIED_TAG = re.compile(r"[^(){}\[\]:]+ \([^(){}\[\]:]+\)")
_QUALITY_TAGS = frozenset({"masterpiece", "best quality", "high quality", "amazing quality", "very aesthetic",
                           "absurdres", "highres", "nsfw", "sfw", "safe", "explicit", "questionable", "sensitive",
                           "general", "rating:general", "rating:sensitive", "rating:questionable", "rating:explicit"})
_LOCK = threading.Lock()
_INSTALLER_LOCK = threading.Lock()
_WARM_LOCK = threading.Lock()
_RECOVER_LOCK = threading.Lock()   # 미번역 되살리기의 사전 원형 색인(세션에 한 번, 수 초) — _LOCK 을 오래 쥐지 않게 따로
_GRAMMAR: str | None = None
_GENDERS: dict[str, str] | None = None
_PROFILES: dict[str, tuple[str, dict[str, Any]]] | None = None


def _grammar() -> str:
    global _GRAMMAR
    if _GRAMMAR is None:
        from core.assist_v2 import compact_grammar

        _GRAMMAR = compact_grammar()
    return _GRAMMAR


def _load_character_analysis(context: Any) -> None:
    """`data/character_analysis.json`(13,497명)을 한 번만 읽고 작은 표 둘만 쥔다 — 성별 · (작품, 외모 칸)."""
    global _GENDERS, _PROFILES
    if _GENDERS is not None and _PROFILES is not None:
        return
    genders: dict[str, str] = {}
    profiles: dict[str, tuple[str, dict[str, Any]]] = {}
    try:
        path = Path(getattr(context, "repo_root", ".")) / "data" / "character_analysis.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        for work, chars in data.items():
            for name, info in (chars or {}).items():
                if not isinstance(info, dict):
                    continue
                if info.get("gender") in ("girl", "boy"):
                    genders[str(name)] = info["gender"]
                profiles[str(name)] = (str(work), {k: info.get(k) for k in ("personal_color", "characteristics",
                                                                          "breast_size", "gender")})
    except Exception:
        pass
    _GENDERS, _PROFILES = genders, profiles


def _genders(context: Any) -> dict[str, str]:
    """캐릭터 태그 -> girl/boy."""
    _load_character_analysis(context)
    return _GENDERS or {}


def _character_profile(context: Any, tag: str) -> tuple[str | None, dict[str, Any] | None]:
    """캐릭터 태그 -> (작품 이름, 외모 칸(personal_color · characteristics · breast_size · gender)). 없으면 (None, None)."""
    _load_character_analysis(context)
    return (_PROFILES or {}).get(tag, (None, None))


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
        try:
            from app.backend.server.boost_v2_service import _save_root

            names_cache = _save_root(context) / "cache" / "assist_kiwi_names.json"
        except Exception:
            names_cache = None
        layer = KoreanLayer(vocab, cache_path=names_cache)          # Kiwi 가 모르는 이름 목록을 저장해 두고 다시 쓴다
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
    from core.assist_korean import compact
    from core.assist_v2 import TagVocab

    def fuzzy(ko: str) -> list[str]:
        try:
            return [str(r.get("tag")) for r in search_kr_tags(context, ko, limit=5) if r.get("tag")]
        except Exception:
            return []

    def senses(ko: str) -> list[str]:
        # 사전의 그 말이 가리키는 일반 태그 전부 — 영문으로 적은 말의 한국어 옮김인가 확인용(core/assist_v2.merge)
        return [name for name, _n, cat in layer.vocab.keywords.get(compact(ko), []) if not cat]

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
                        fuzzy=fuzzy, senses=senses)

    def canonical(tag: str) -> str | None:
        tid = idx.resolve(tag)
        return idx.by_id[tid] if tid is not None else None

    def count(tag: str) -> int:
        tid = idx.resolve(tag)
        return int(idx.observed[tid]) if tid is not None else 0

    def role(tag: str) -> str | None:
        tid = idx.resolve(tag)
        return idx.role.get(tid) if tid is not None else None

    return TagVocab(canonical=canonical, count=count, role=role, keyword=layer.vocab.scene_tags, fuzzy=fuzzy,
                    senses=senses)


def warm_assist(context: Any) -> None:
    """창을 열 때: Kiwi · 한국어 퍼지 검색 · 엔진 · 지시문 캐시를 뒤에서 데운다 — 첫 질문이 기다리지 않게.

    실측: 퍼지 검색의 첫 호출이 색인을 만드느라 약 6초, 지시문(약 1,100토큰) 첫 처리가 5090 에서 3.2초였다.
    """
    def _warm_choose() -> None:
        # 고르기 준비물 — 사전 키워드 원형 색인(약 3초) · 후보 도구(영문 낱말 색인 0.5초). 엔진 데우기와 나란히 간다
        # (고르기는 모델의 첫 답 뒤에 쓰인다 — 늦으면 색인 잠금에서 기다린다)
        try:
            layer = korean_layer(context)
            _lemma_index(context, layer).build()
            vocab = _tag_vocab(context, layer)
            _compose_tools(context, layer, vocab)
            _ko_dict_index(context, layer, vocab)        # 미번역 되살리기 — 사전 설명 · 키워드 원형 색인(수 초)
        except Exception:
            pass

    def _warm() -> None:
        try:
            korean_layer(context).warm()
        except Exception:
            pass
        threading.Thread(target=_warm_choose, daemon=True, name="assist-v2-warm-choose").start()
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
                             timeout=MODEL_TIMEOUT)
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
    out = {"ok": True, "ready": layer.ready(), **layer.name_spans(text, use_kiwi=layer.ready())}
    if not out["ready"] and layer.error:
        out["error"] = layer.error          # Kiwi 가 없다(설치 전) — 화면이 다시 묻지 않는다
    return out


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
    from core.assist_korean import symbols_as_words

    text = symbols_as_words(text)            # '? 마크를' -> '물음표를' — 한국어 층 · 모델 · 사전이 같은 낱말을 본다(09-26)
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
    # 직역 도구(사용자 제안 09-25) — 켜면 요청을 과장 없이 영어로 한 번 옮겨 경로 호출에 넘긴다. 벤치로 견주는 동안 기본은 끔
    literal = bool(payload.get("literal", False))
    # 다듬기 도구(사용자 제안 09-25) — 원문 + 태그로 고치고 보강하고 장면 문장 하나(메인 = 태그들, 문장). 기본 켬
    refine = bool(payload.get("refine", True))
    # 미번역 낱말 되살리기(09-26 첫 마일스톤, core/assist_recover) — 거구 · 주인 · 교배 처럼 어떤 태그도 설명 못 한 말. 기본 켬
    recover = bool(payload.get("recover", True))
    # 고급 설정의 User Preference(사용자 지정 09-26) — 화면이 고른 등급의 것만 보낸다. 다듬기가 이 방향으로 고친다
    preference = " ".join(str(payload.get("preference") or "").split())[:MAX_PREFERENCE]
    # [NAIA 추론 파이프라인 미사용](사용자 지정 09-28) — 요청을 E2B 에 한 번 주어 태그 + 문장만(_direct)
    direct = bool(payload.get("direct", False))
    return {"text": text, "rating": rating, "persons": persons, "previous": previous, "api_mode": api_mode,
            "choices": choices, "not_names": not_names, "literal": literal, "refine": refine, "recover": recover,
            "preference": preference, "direct": direct, "followup": _parse_followup(payload.get("followup"))}


def _parse_followup(raw: Any) -> dict[str, Any] | None:
    """[이어 고치기](사용자 지정 09-28) — 받은 결과: 메인(고친 글 그대로) · 캐릭터 칸 · 이전 풀의 제외 · 인원 인자."""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise AssistError("이어 고치기 요청이 잘못됐습니다.")
    main = str(raw.get("main") or "").strip()
    if not main:
        raise AssistError("고칠 결과가 없습니다 — 먼저 찾아 주세요.")
    if len(main) > MAX_FOLLOWUP_MAIN:
        raise AssistError(f"메인 프롬프트는 {MAX_FOLLOWUP_MAIN}자까지 고칠 수 있습니다.")
    chars = raw.get("characters") or []
    if not isinstance(chars, list) or len(chars) > MAX_VIRTUAL_CHARACTERS or not all(
            isinstance(c, dict) and isinstance(c.get("prompt", ""), str) and len(c.get("prompt") or "") <= 600
            for c in chars):
        raise AssistError("캐릭터 프롬프트가 잘못됐습니다.")
    names = raw.get("names") or []
    if not isinstance(names, list) or len(names) > MAX_NAME_CHOICES * 2 or not all(
            isinstance(n, str) and len(n) <= 120 for n in names):
        raise AssistError("이름 목록이 잘못됐습니다.")
    # sentence = 받은 결과의 문장(메인 끝을 가를 힌트) · names = 고른 캐릭터 태그(메인에 적혀도 뺄 수 없다 — WebUI · 직접 모드)
    return {"main": main, "characters": [dict(c) for c in chars],
            "exclude": str(raw.get("exclude") or "")[:1000], "persons": str(raw.get("persons") or "")[:200],
            "sentence": str(raw.get("sentence") or "")[:600], "names": [n.strip() for n in names if n.strip()]}


def generation_request(context: Any, payload: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    """[생성] — Assist 결과를 **가상 프롬프트**로 한 장 뽑을 때 쓸 (source_row, 생성 요청 overrides).

    사용자 지정 2026-09-24: "사용자의 캐릭터 프롬프트를 간섭하면 곤란하다 — 생성할 때 가상 캐릭터 프롬프트로".
    - 메인: source_row 로 이벤트 맵 [생성] 과 같은 파이프라인(PE 앞뒤·자동 숨김)에 태운다 — 메인 칸은 그대로.
    - 캐릭터(NAI): 이 요청에만 싣는다(캐릭터 즉시 생성과 같은 길). ⚠️ late binding 을 **반드시** 막는다 — 안 막으면
      캐릭터 모듈이 사용자의 슬롯으로 덮어쓴다. Assist 가 인물을 못 찾았어도 막는다(보여 준 그대로 나가야 한다).
      좌표는 안 싣는다 — use_coords=False 로 NAI 가 배치한다(0.5/0.5 겹침 없음, api_service).
    - 한 장으로 끝난다(auto_generate=False) — Auto Gen 연쇄를 이어받지 않는다.
    """
    if not isinstance(payload, dict):
        raise AssistError("요청 형식이 잘못됐습니다.")
    tags = [t.strip() for t in str(payload.get("main") or "").split(",") if t.strip()]
    if not tags:
        raise AssistError("생성할 프롬프트가 없습니다.")
    if len(tags) > 200:
        raise AssistError("프롬프트는 200태그까지입니다.")
    rating = str(payload.get("rating") or "g").strip().lower()[:1]
    if rating not in ("g", "s", "q", "e"):
        rating = "g"
    raw_chars = payload.get("characters") or []
    if not isinstance(raw_chars, list) or len(raw_chars) > MAX_VIRTUAL_CHARACTERS or not all(
            isinstance(c, str) and len(c) <= 600 for c in raw_chars):
        raise AssistError("캐릭터 프롬프트가 잘못됐습니다.")
    characters = [c.strip() for c in raw_chars if c.strip()]
    # 등급 태그를 뒤에(사용자 지정 09-26) — 이미 적힌 것은 다시 붙이지 않는다(영문으로 nsfw 를 적었을 때)
    have = {t.lower() for t in tags}
    tags += [t for t in GENERATE_RATING_TAGS[rating] if t not in have]
    source_row = {"general": ", ".join(tags), "rating": rating,
                  "character": None, "copyright": None, "artist": None, "meta": None, "assist_combo": True}
    overrides: dict[str, Any] = {"auto_generate": False}
    if str(context.get_api_mode() or "").upper() == "NAI":
        overrides.update({
            "characters": characters,
            "uc": [""] * len(characters),               # ⚠️ characters 와 길이가 같아야 NAICharacterData 가 받는다
            "_skip_character_late_binding": True,
            "_skip_character_reference_late_binding": True,   # 레퍼런스는 사용자 슬롯의 캐릭터 것이다
        })
    return source_row, overrides


def _literal(context: Any, text: str) -> tuple[str | None, dict[str, Any]]:
    """직역 도구(core/assist_translate) — E2B 1회 · 문법 잠금 · 권장 샘플링. 같은 글은 다시 묻지 않는다(창을 연 동안 되묻기).
    실패하면 None — 부르는 쪽은 직역 없이 간다."""
    from core import assist_translate as at
    from core.assist_korean import clean_text

    key = clean_text(text).strip()
    cache = getattr(context, "assist_literal_cache", None)
    if cache is None:
        cache = context.assist_literal_cache = {}
    if key in cache:
        return cache[key], {"cached": True}
    reply, info = _chat(context, at.LITERAL_SYSTEM, at.literal_message(text), at.literal_grammar(text),
                        max_tokens=20 + at.literal_limit(text) // 2)
    en = at.parse_literal(reply) if reply is not None else None
    if en:
        if len(cache) >= 64:
            cache.pop(next(iter(cache)))
        cache[key] = en
    return en, info


def _grounded_tags(context: Any, layer: Any, text: str) -> set[str]:
    """이 요청의 낱말과 한국어 사전(키워드 원형 색인)이 이어 주는 태그 — 고르기 후보와 같은 규칙(korean_matches).
    다듬기의 빼기 보호 · 더하기 허용 판정에 쓴다."""
    from core import assist_candidates as cand
    from core.assist_korean import clean_text

    toks = layer.raw_tokens(clean_text(text))
    nouns = [f for f, t in toks if t in ("NNG", "NNP")]
    return {tag for tag, *_ in cand.korean_matches(_lemma_index(context, layer), cand.lemmas_of(toks),
                                                   layer.vocab.lookup, strict=False, nouns=nouns,
                                                   near=cand.neighbours(toks))}


def _refine(context: Any, req: dict[str, Any], merged: Any, vocab: Any, share: Any, literal: str | None,
            layer: Any, ka: Any, keep: Iterable[str] = ()) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """다듬기 도구(core/assist_refine) — 원문 + 지금 태그를 E2B 에 한 번(문법 잠금 · 권장 샘플링). 모델의 답은 제안이다.
    한국어 사전으로 확인한다(진짜 E2B 가 브이 문장에서 맞는 v 를 빼고 finger heart 를 더했다, 09-25):
    - 빼기: 지금 태그 안에서만, 사전이 요청과 이어 주는 태그 · 한국어 층 규칙 태그는 빼지 않는다.
    - 더하기: 태그 이름 그대로이고 사전이 요청과 이어 주는 것만(잡동사니 · 인원 · 제외 칸 · 등급 게이트도 지나야).
      고급 설정의 User Preference 가 있으면 그 방향의 더하기는 사전 확인 없이 받는다 — 제 문장에서 말한 것만(자기 일관성).
    - 문장은 메인 끝에(compose) — 분위기는 문장이 맡는다. 실패하면 다듬지 않고 간다."""
    from core import assist_refine as ar
    from core.assist_english import en_key
    from core.assist_v2 import _junk_tag, drop_tags, exact_english

    tags = merged.all_tags()
    if not tags:
        return None, {}
    preference = req.get("preference") or ""
    # 고른 캐릭터는 이름을 알려 준다 — 모르면 문장이 이름을 지어낸다(라크리모사 -> Lacy lingerie, 09-26)
    names = [(c.ko, c.tag, c.gender) for c in merged.characters]
    reply, info = _chat(context, ar.REFINE_SYSTEM, ar.refine_message(req["text"], tags, literal, preference, names),
                        ar.refine_grammar(), max_tokens=160)
    got = ar.parse_refine(reply) if reply is not None else None
    if got is None:
        return None, info
    grounded = _grounded_tags(context, layer, req["text"])
    typed = merged.english.keys()                    # 사용자가 영문으로 적은 것 — 빼지 않고, 이미 실리니 더하지 않는다
    # keep = 미번역 되살리기가 사전 · 이벤트 맵 근거로 고른 것 — 다듬기가 도로 빼지 않는다
    protected = grounded | set(ka.specific) | set(ka.verb_tags) | {t for t in tags if en_key(t) in typed} | set(keep)
    # 자기 일관성: 모델이 제 문장에서 말한 태그는 빼지 않는다(밤바다 -> night 를 빼며 'at night')
    removed = [t for t in got.remove if t in tags and t not in protected and not ar.mentions(t, got.sentence)]
    kept = [t for t in got.remove if t in tags and t not in removed]
    drop_tags(merged, {t: 0.0 for t in removed})
    gate = RATING_GATE.get(req["rating"])              # Q · E 는 게이트가 없다
    added: list[str] = []
    refused: list[str] = []
    for tag in got.add:
        name = exact_english(tag, vocab)
        if (not name or _junk_tag(name) or vocab.role(name) == "population" or name in merged.all_tags()
                or name in merged.exclude or name in added or name in removed or en_key(name) in typed):
            continue
        # User Preference 가 있으면 그 글이 말한 것도 받는다(Q 의 'breasts and buttocks' -> breasts · breast focus 가
        # 제 문장에 없어서 막혔다, 09-26)
        said = ar.mentions(name, got.sentence) or bool(preference and ar.mentions(name, preference))
        if (name not in grounded and not preference) or not said:
            refused.append(name)            # 사전이 요청과 안 이어 주거나(finger heart) 제 문장에 없는 것(close-up)
            continue
        s = share(name) if share and gate is not None else None
        if s is not None and s < gate:
            continue
        added.append(name)
    merged.tiers[1].extend(added)
    merged.sentence = got.sentence
    merged.log.append(f"refine:-{','.join(removed) or '없음'}+{','.join(added) or '없음'}"
                      + (f" 안뺌:{','.join(kept)}" if kept else "") + (f" 안더함:{','.join(refused)}" if refused else ""))
    return {"removed": removed, "added": added, "sentence": got.sentence}, info


def _call_model(context: Any, text: str, previous: dict[str, Any] | None,
                literal: str | None = None) -> tuple[dict[str, Any] | None, dict[str, Any]]:
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
            info["error"] = "AI 모델이 없습니다 — API 설정의 [AI 모델]에서 받아 주세요."
            info["code"] = "model_missing"
            return None, info
        resp = runtime.chat(user_message(text, previous, literal), system=SYSTEM_PROMPT, grammar=_grammar(),
                            max_tokens=MODEL_MAX_TOKENS, timeout=MODEL_TIMEOUT)
        info.update({k: resp.get(k) for k in ("elapsed", "usage", "load_seconds", "queue_wait", "gpu") if k in resp})
        if not resp.get("ok"):
            info["error"] = str(resp.get("error") or "모델 호출 실패")
            return None, info
        return parse_route(str(resp.get("text") or "")), info
    except Exception as exc:
        info["error"] = f"{type(exc).__name__}: {exc}"
        return None, info


def _rating_share(context: Any, rating: str) -> Any:
    """등급 게이트 — 태그가 달린 게시물 중 고른 등급(G·S)의 비중. Q·E 이거나 이벤트 맵이 없으면 None(게이트 없음).
    사용자 제보 09-24: G 로 고른 '나를 쳐다보는 나히다' 에 looking at penis 가 들어갔다(퍼지 검색 길) — 어느 길로
    들어오든 마지막에 여기서 걸러진다."""
    if rating not in RATING_GATE:
        return None
    try:
        service = _event_map(context)
    except Exception:
        return None

    def share(tag: str) -> float | None:
        try:
            counts = service.rating_counts(tag) or {}
        except Exception:
            return None
        total = sum(counts.values())
        return counts.get(rating, 0) / total if total >= RATING_GATE_MIN_POSTS else None
    return share


def _rating_note(rating: str, dropped: dict[str, float]) -> str:
    r = rating.upper()
    items = ", ".join(f"{tag} ({r} {s * 100:.2f}%)" for tag, s in dropped.items())
    return f"고른 등급({r}) 게시물에 거의 없는 태그라 뺐습니다: {items}."


def _with_rating_note(out: dict[str, Any], rating: str, dropped: dict[str, float]) -> None:
    if dropped:
        out["dropped"] = [{"tag": tag, "share": round(s, 5)} for tag, s in dropped.items()]
        out["message"] = " ".join(m for m in (_rating_note(rating, dropped), out.get("message")) if m)


def _senses_of(layer: Any, vocab: Any, word: str) -> list[str]:
    """사전의 그 말이 가리키는 일반 태그(게시물 많은 순, 맵 이름) — lookup 은 12개 넘게 가리키는 말(눈)을 통째로 버린다."""
    out: list[str] = []
    for name, _count, cat in sorted(layer.vocab.keywords.get(word, []), key=lambda r: -r[1]):
        tag = vocab.canonical(name) if not cat else None
        if tag and tag not in out and vocab.role(tag) != "population":
            out.append(tag)
    return out[:12]


def _sense_check(context: Any, layer: Any, ka: Any, merged: Any, vocab: Any) -> list[tuple[str, str, str]]:
    """동음이의어 뜻 검사(core/assist_senses) — 병합 직후, 등급 게이트 전(바꾼 태그도 게이트를 지난다).
    이벤트 맵이 없거나 깨지면 건너뛴다 — Assist 는 그대로 간다."""
    from core.assist_v2 import replace_tag

    try:
        from core.assist_senses import Cooccur, homonym_swaps

        index = _event_map(context).index()
        cooc = getattr(context, "assist_cooccur", None)
        if cooc is None or cooc.index is not index:
            cooc = Cooccur(index)
            context.assist_cooccur = cooc
        names = {n.form for n in ka.names}
        nouns = [f for f, t in ka.tokens if t in ("NNG", "NNP") and f not in names]
        tags = merged.all_tags() + [a for c in merged.characters for a in c.attrs]
        swaps = homonym_swaps(nouns, tags, lambda w: _senses_of(layer, vocab, w), cooc)
    except Exception:
        return []
    for word, old, new in swaps:
        replace_tag(merged, old, new)
        merged.log.append(f"sense:{word}:{old}->{new}")
    return swaps


def _lemma_index(context: Any, layer: Any) -> Any:
    """NAIA 한국어 키워드 원형 색인 — 세션에 하나(창을 열 때 뒤에서 만든다, 늦으면 첫 고르기가 약 3초 기다린다)."""
    from core.assist_candidates import KeywordLemmaIndex

    with _LOCK:
        index = getattr(context, "assist_lemma_index", None)
        if index is None:
            index = KeywordLemmaIndex(layer.vocab.keywords, layer.raw_tokens)
            context.assist_lemma_index = index
    return index


def _make_chooser(context: Any, layer: Any, ka: Any, req: dict[str, Any], route: dict[str, Any],
                  vocab: Any) -> tuple[Any, dict[str, Any]]:
    """정확히 안 풀린 모델 항목 + 모델이 안 낸 요청 명사 -> 한국어 사전 후보(+영문 묶음·순위) -> E2B 가 고른다.
    사용자 결정(09-25): '태그 검색을 해서 모델한테 정답을 한번 고르게' · 한 조각씩 번호로 단답(0 = 없음).
    고를 것이 없으면 모델을 부르지 않는다."""
    from core import assist_candidates as cand
    from core import assist_compose as ac
    from core.assist_v2 import _junk_tag

    rules = layer.rules
    state: dict[str, Any] = {"sent": [], "kept": [], "model": {}, "prep_ms": 0.0}

    def chooser(asks: list[Any]) -> list[str]:
        try:
            return _choose(asks)
        except Exception as exc:                      # 후보 찾기가 깨져도 Assist 는 산다 — 모두 예전 결과로
            state["error"] = f"{type(exc).__name__}: {exc}"
            for ask in asks:
                ask.keep, ask.picks = [], None
            return []

    def canonical(term: str) -> str | None:
        name = vocab.canonical(term)
        return name if name and not _junk_tag(name) else None

    def _choose(asks: list[Any]) -> list[str]:
        started = time.perf_counter()
        tools = _compose_tools(context, layer, vocab)
        finder = ac.TagFinder(tools)
        share = _rating_share(context, req["rating"])

        def keep(tag: str) -> bool:
            if not share:
                return True
            s = share(tag)
            return s is None or s >= RATING_GATE[req["rating"]]

        route_kos = [str(i.get("ko") or "") for key in ("include", "actions") for i in route.get(key) or []]
        stop = set(rules["not_names"]) | {w for g in rules["people"].values() for w in g} | set(rules["groups"])
        # 한국어 층이 이미 태그로 만든 원형 — 동사 규칙(앉 -> sitting) · 시청자 규칙(나를 쳐다보는 -> looking at viewer)
        layer_lemmas = {f"{s}/V" for s in ka.stems if s in rules["verbs"]
                        or any(s.startswith(p) for p, _t in rules["stem_prefixes"])}
        for r in (rules.get("viewer") or {}).get("rules") or []:
            if set(r.get("tags") or []) & set(ka.viewer or []):
                layer_lemmas |= {f"{v}/V" for v in r.get("verbs") or []}      # 첫 규칙에 '보' 가 있다(쳐다보 = 보)
        sent = cand.build_asks(asks, ka=ka, route_kos=route_kos, index=_lemma_index(context, layer),
                               tokenize=layer.tokenize, lookup=layer.vocab.lookup, keyword_tags=tools.keyword_tags,
                               rank=lambda ko, en: [(c.tag, c.en_strong, c.ko_strong) for c in finder.rank(ko, en)],
                               canonical=canonical, usable=finder.usable, keep=keep, stop=stop,
                               layer_lemmas=layer_lemmas,
                               literal=lambda t, word: ac.compact(word) in ac.own_names(
                                   tools.info(t) or {}, tools.name_claims, tools.label_uses),
                               describe=lambda t: ac._short((tools.info(t) or {}).get("description") or ""))
        state["prep_ms"] = round((time.perf_counter() - started) * 1000, 1)
        state["kept"] = [{"ko": a.ko, "en": a.en, "keep": list(a.keep)} for a in asks if a.keep]
        # 한 조각씩 번호로(0 = 없음), 앞에서 고른 것을 넘기며 차례로 — 사용자 제안(09-25). 후보가 둘 이상이면 역순으로 한 번
        # 더 묻는다(위치 치우침 — settle_order). 호출이 실패하면 거기서 멈춘다: 정순이 실패하면 그 조각부터, 역순만 실패하면
        # 그 조각은 정순 답으로 두고 뒤 조각부터 예전 결과(엔진이 죽었으면 호출마다 제한 시간을 다 기다린다 — Codex 검토 09-25)
        done = [t for a in asks for t in a.keep]
        elapsed, calls, failed = 0.0, 0, False
        for ask in sent:
            names = [t for t, _d in ask.candidates]
            answers: list[Any] = []
            for order in ([ask] if len(names) < 2 else
                          [ask, cand.Ask(ko=ask.ko, en=ask.en, candidates=list(reversed(ask.candidates)))]):
                listed = [t for t, _d in order.candidates]
                reply, info = _chat(context, cand.CHOOSE_SYSTEM, cand.choose_message(req["text"], order, done),
                                    cand.choose_grammar(len(listed)), max_tokens=4)
                elapsed += float(info.get("elapsed") or 0)
                calls += 1
                state["model"] = dict(info, elapsed=round(elapsed, 2), calls=calls)
                if reply is None:
                    failed = True
                    break
                answers.append(cand.parse_choice(reply, listed))
            if not answers:
                break
            ask.picks = cand.settle_order(answers[0], answers[1] if len(answers) > 1 else answers[0], names)
            done += ask.picks or []
            state["sent"].append({"ko": ask.ko, "en": ask.en, "source": ask.source, "keep": list(ask.keep),
                                  "candidates": names, "picks": ask.picks, "answers": answers})
            if failed:
                break
        return [t for a in sent if a.source == "extra" for t in (a.picks or [])]

    return chooser, state


def _approved_names(layer: Any, req: dict[str, Any]) -> tuple[list[Any], list[str]]:
    """인물 = 사용자가 칩에서 고른 캐릭터(이름 -> 태그)뿐이다(사용자 결정 09-25 — 자동으로 찾은 이름은 제안일 뿐).
    글에 없는 선택(창이 열린 동안 화면이 기억해 다시 보내는 옛 선택)은 건너뛴다.
    (받은 것 — 글에 나온 순서, 받지 못한 이름 — 게시물이 없는 태그: 응답 chosen=false 로 화면이 선택을 푼다)"""
    from core.assist_korean import clean_text, compact

    text = compact(clean_text(req["text"]))
    kept: list[Any] = []
    refused: list[str] = []
    for form, tag in req["choices"].items():
        key = compact(form)
        if not key or form in req["not_names"] or key not in text:
            continue
        hit = layer.approved(form, tag)
        if hit is None:
            refused.append(form)
        else:
            kept.append(hit)
    kept.sort(key=lambda h: text.find(compact(h.form)))
    return kept, refused


def _approved_for(form: str, approved: list[Any]) -> Any:
    """구성의 캐릭터 줄 이름(카나데)에 맞는 고른 캐릭터 — 성을 빼거나 붙여 적어도 같은 사람(요이사키 카나데)."""
    from core.assist_korean import compact

    key = compact(form)
    return next((h for h in approved if key and (compact(h.form) == key or key in compact(h.form)
                                                or compact(h.form) in key)), None)


def _names_out(layer: Any, chars: list[Any], refused: list[str]) -> list[dict[str, Any]]:
    """응답의 인물 — 고른 캐릭터마다 후보 전체(화면이 목록을 그린다) + 받지 못한 선택(chosen=false -> 화면이 푼다)."""
    out = [{"ko": c.ko, "tag": c.tag, "alts": c.alts, "gender": c.gender, "chosen": True,
            "candidates": layer.candidate_list(c.ko)} for c in chars]
    for form in refused:
        cands = layer.candidate_list(form)
        out.append({"ko": form, "tag": cands[0]["tag"] if cands else "", "alts": [], "gender": None, "chosen": False,
                     "candidates": cands})
    return out


def _suggested(hits: list[Any], chars: list[Any]) -> list[dict[str, Any]]:
    """고르지 않은 이름 제안(칩) — 캐릭터로 쓰지 않았다고 알린다. 고른 캐릭터와 겹치는 조각(카나데 ⊂ 요이사키 카나데)은 뺀다."""
    from core.assist_korean import compact

    taken = [compact(c.ko) for c in chars]
    out: list[dict[str, Any]] = []
    for h in hits:
        key = compact(h.form)
        if key and not any(key in t or t in key for t in taken) and h.form not in [s["ko"] for s in out]:
            out.append({"ko": h.form, "tag": h.tag})
    return out


def _direct_dictionary(context: Any, layer: Any, vocab: Any, ka: Any, rating: str) -> list[tuple[str, str]]:
    """직접 모드 ②에 곁들일 사전 이름(core/assist_direct.dictionary_names) — 이벤트 맵 이름 · 설명 있는 태그 · 이름/메타 아님 ·
    게시물 MIN_DICTIONARY_POSTS 이상 · 등급 게이트(G · S 에서 성인 태그를 알려 주지 않는다). 깨지면 줄 없이 간다."""
    from app.backend.server.autocomplete_commands import _ensure_kr_raw
    from core import assist_direct as ad
    from core.assist_compose import angle_label, is_metatag
    from core.assist_v2 import _junk_tag, rating_name

    try:
        tokens = getattr(ka, "tokens", None) or []
        if not tokens:
            return []
        lookup = layer.vocab.lookup
        index = _lemma_index(context, layer)
        raw = _ensure_kr_raw(context) or {}
        share = _rating_share(context, rating)
        if rating in RATING_GATE and share is None:
            # 이벤트 맵이 없어 등급을 못 잰다 — G · S 에 성인 태그(섹스 = sex)를 알려 줄 수 있어 줄을 뺀다(Codex 10차 F7)
            return []

        def posts(tag: str) -> int:
            try:
                return int((raw.get(tag) or {}).get("freq") or 0)
            except (TypeError, ValueError):
                return 0

        def name_of(tag: str) -> str | None:
            info = raw.get(tag)
            if not isinstance(info, dict) or not str(info.get("description") or "").strip():
                return None
            if str(info.get("_named_entity_category") or info.get("_cat") or "") in ("artist", "character",
                                                                                   "copyright", "e621"):
                return None
            if is_metatag(tag, info) or posts(tag) < ad.MIN_DICTIONARY_POSTS:
                return None
            name = vocab.canonical(tag)
            if not name or _junk_tag(name) or _PEOPLE_TAG.fullmatch(name):
                return None
            if share is not None:
                s = share(name)
                # G · S 에서 비중을 못 재면(등급 수를 못 읽음 · 색인 없음) 뺀다 — 섹스 = sex 가 G 로 갔다(Codex 11차 R4)
                if s is None or s < RATING_GATE[rating]:
                    return None
            return rating_name(name, rating)

        return ad.dictionary_names(tokens, index, lookup, name_of=name_of,
                                   label_of=lambda tag: angle_label(raw.get(tag) or {}), posts=posts)
    except Exception:
        return []


def _direct(context: Any, req: dict[str, Any], started: float) -> dict[str, Any]:
    """[NAIA 추론 파이프라인 미사용](사용자 지정 09-28) — E2B 두 번(core/assist_direct): ① 요청을 쉬운 영어 상황 문장으로
    (Q/E 등급 표시 · 규칙표 속어 풀이) ② 요청 + 그 상황으로 태그 + 영어 문장.
    한국어 층 · 경로 · 고르기 · 되살리기 · 이벤트 맵 · 다듬기를 거치지 않는다. 쓰는 것은 셋뿐:
    - 사전 이름 맞추기(smiling -> smile) — 사전에 없는 것은 적힌 그대로 싣고 알린다(unknown). 버리면 E2B 가 쓴 구
      (listening to sounds · peeking from doorway)가 다 빠져 메인이 비었다(시도 09-28). 잡동사니(품질 · 등급)만 뺀다.
    - 인원: 수동이면 그 수, 자동이면 NAIA 한국어 인원 세기(사람 낱말 · 고른 캐릭터 · ~녀/~남) — 셌으면 모델에는 정해졌다고만
      준다(모델은 테토녀 · 에겐녀 둘을 1girl, 1boy 로 셌다, 09-28). 못 셌을 때(성별 모름 · 사람 낱말 없음)만 모델이 쓴 인원 태그.
      solo 는 '혼자' · '홀로' 를 적었을 때만.
    - 고른 캐릭터(이름 칩): 인원 뒤에 그 태그 · 문장은 영어 이름으로. 캐릭터 칸은 쓰지 않는다(메인 한 줄).
    - 사전 이름 줄(09-28): ②에 요청 낱말의 사전 태그 이름을 곁들인다(온천 = onsen) — 걸러서(_direct_dictionary). 태그 검색이
      아니라 이름 알려 주기다: 고르는 것은 모델이다."""
    from core import assist_direct as ad
    from core.assist_english import people_count
    from core.assist_korean import partition_of
    from core.assist_refine import display_name
    from core.assist_v2 import PERSON_TAGS, Character, _junk_tag, _with_sentence, exact_english, rating_name

    layer = korean_layer(context)
    vocab = _tag_vocab(context, layer)
    approved, refused = _approved_names(layer, req)
    chars = [Character(h.form, h.tag, [], h.gender) for h in approved]
    solo = layer.says_solo(req["text"]) or bool(re.search(r"\bsolo\b", req["text"], re.IGNORECASE))
    manual = req["persons"]["mode"] == "manual"
    people: list[str] = []
    counted = None
    ka = layer.analyze(req["text"])
    if manual:
        g, b = req["persons"]["girls"], req["persons"]["boys"]
        people = PERSON_TAGS.get(partition_of(g, b, g + b == 1 and solo), [])
    else:
        # 자동: NAIA 한국어 인원 세기 — 성별 모르는 사람이 섞이면(사람 · 친구) 믿지 않고 모델 인원 태그로
        counted = layer.count_persons(ka, approved={c.ko: c.gender for c in chars},
                                      not_names=req["not_names"])
        if counted.partition != "unknown" and not counted.unknown:
            people = PERSON_TAGS.get(partition_of(counted.girls, counted.boys,
                                                  counted.girls + counted.boys == 1 and solo), [])
    names = [(c.ko, display_name(c.tag)) for c in chars]
    # ① 상황 — 요청을 쉬운 영어 문장으로(사용자 실험 09-28 · core/assist_direct 머리말). 실패하면 요청만으로 간다.
    # 속어 풀이 = 손으로 쓴 것(규칙표) + 위키낱말사전에서 고른 것(core/assist_slang — 성적 뜻은 Q · E 만, 짧은 낱말은 Kiwi 토막으로)
    from core import assist_slang

    words = assist_slang.hints(req["text"], req["rating"], hand=layer.rules.get("slang_glossary") or {},
                               tokens=layer.raw_tokens(req["text"]))
    sit_reply, sit_info = _chat(context, ad.SITUATION_SYSTEM,
                                ad.situation_message(req["text"], req["rating"], names, words),
                                ad.situation_grammar(), max_tokens=120)
    situation = ad.parse_situation(sit_reply)
    dictionary = _direct_dictionary(context, layer, vocab, ka, req["rating"])
    reply, info = _chat(context, ad.DIRECT_SYSTEM,
                        ad.direct_message(req["text"], req["rating"], names, ", ".join(people), situation,
                                          dictionary),
                        ad.direct_grammar(), max_tokens=320)
    got = ad.parse_direct(reply) if reply is not None else None
    out: dict[str, Any] = {"ok": True, "task": "scene", "goal": "generate", "rating": req["rating"], "direct": True,
                           "names": _names_out(layer, chars, refused), "suggested_names": [], "relations": [],
                           "model": info, "leftovers": [], "actions": [], "samples": []}
    if got is None or not got.tags:
        out["message"] = ("AI 모델이 답하지 않아 만들지 못했습니다." if reply is None
                          else "AI 모델의 답을 읽지 못했습니다 — 다시 시도해 주세요.")
        out["prompt"] = {"main": "", "characters": []}
    else:
        kept: list[str] = []
        unknown: list[str] = []
        dropped: list[str] = []
        model_people: list[str] = []
        for tag in got.tags:
            if _PEOPLE_TAG.fullmatch(tag):
                model_people.append(tag)                  # 인원 태그(1girl · solo) — 아래에서 인원 칸이 정한다
                continue
            name = exact_english(tag, vocab)
            if _junk_tag(name or tag) or tag in _QUALITY_TAGS:
                dropped.append(tag)
                continue
            if not name and tag not in {c.tag for c in chars}:
                unknown.append(tag)                       # 사전에 없는 구 — 적힌 그대로 싣는다
            kept.append(rating_name(name or tag, req["rating"]))
        if not people:                                    # 수동도 아니고 한국어 층도 못 셌다 — 모델이 쓴 인원 태그
            g, b, _said = people_count(model_people)      # 모델의 solo 는 쓰지 않는다 — 요청이 말했을 때만
            people = PERSON_TAGS.get(partition_of(g, b, g + b == 1 and solo), [])
        char_tags = [c.tag for c in chars]
        line = list(dict.fromkeys(people + char_tags + [t for t in kept if t not in people and t not in char_tags]))
        out["prompt"] = {"main": _with_sentence(", ".join(line), got.sentence), "characters": []}
        out["direct_info"] = {"tags": kept, "unknown": unknown, "dropped": dropped, "sentence": got.sentence,
                              "situation": situation, "words": [ko for ko, _en in words],
                              "dictionary": [tag for _ko, tag in dictionary]}
    g, b, _said = people_count(people)
    partition = partition_of(g, b, "solo" in people)
    out["persons"] = {"mode": "manual" if manual else "auto", "partition": partition, "girls": g, "boys": b,
                      "unknown": 0, "confirm": False, "notes": list(counted.notes) if counted else [], "param": ""}
    out["timing"] = {"situation_s": sit_info.get("elapsed"), "model_s": info.get("elapsed"),
                     "total_s": round(time.perf_counter() - started, 3)}
    return out


def _followup(context: Any, req: dict[str, Any], started: float) -> dict[str, Any]:
    """[이어 고치기](사용자 지정 09-28 — 기본은 새 검색, 이어 고치기는 따로 켠다) — 받은 결과 + 한국어 한 가지를 E2B 에 한 번
    (core/assist_followup): 뺄 태그 · 더할 태그 · 다시 쓴 문장. 인원 · 등급 정보는 주지 않는다. 모델의 답은 제안이다:
    - 빼기: 이전 태그 안에서만(문법) · 요청 낱말이 가리키는 태그만(사전 — 다듬기와 같은 _grounded_tags, 영문으로 적었으면
      그 이름). 시도에서 모델이 '비는 그치고 노을로' 에 우산 · 신호등까지 뺐다.
    - 더하기: 사전 이름 그대로 · 요청 낱말이 가리키는 것만 · 잡동사니 · 인원 아님 · 등급 게이트(G · S).
    - 인원 태그 · 캐릭터 이름 · source#/target# · 가중치 문법은 건드리지 않는다.
    - 고칠 점이 캐릭터 이름(카나데)을 말하면 그 캐릭터 칸만 고친다 — 빼기도 더하기도. 아니면 빼기는 모든 칸, 더하기는 메인.
    - 이벤트 검색은 새 태그로 다시 판다 — 인원 · 등급 · 제외는 이전 풀 그대로."""
    from core import assist_followup as af
    from core.assist_korean import clean_text, compact
    from core.assist_refine import mentions
    from core.assist_v2 import PERSON_TAGS, _junk_tag, _with_sentence, exact_english, rating_name, rating_sources

    fu = req["followup"]
    wish = req["text"]
    layer = korean_layer(context)
    vocab = _tag_vocab(context, layer)
    tags, sentence = af.split_main(fu["main"], fu["sentence"], is_tag=lambda part: bool(vocab.canonical(af.tag_key(part))))
    bags = [[t.strip() for t in re.split(r"[,\n]", str(c.get("prompt") or "")) if t.strip()] for c in fu["characters"]]
    people = {af.tag_key(t) for group in PERSON_TAGS.values() for t in group}
    names = {af.tag_key(b[0]) for b in bags if b} | {af.tag_key(n) for n in fu["names"]}

    def is_people(key: str) -> bool:                 # 3girls · 6+girls · no humans 도(Codex 8차 F3)
        return key in people or bool(_PEOPLE_TAG.fullmatch(key))

    def editable(tag: str) -> bool:
        """뺄 수 있는 조각 — 인원 · 캐릭터 이름(칸의 첫 태그 · 고른 캐릭터 — WebUI 는 메인에 적힌다) · source#/target# ·
        가중치 문법의 조각은 아니다. 쉼표로 가른 '{long hair, rain}' 의 'rain}' 을 빼면 괄호가 깨졌다(Codex 8차 F2) —
        괄호가 든 조각은 사전 이름 꼴(nahida (genshin impact))만 받는다."""
        key = af.tag_key(tag)
        if not key or is_people(key) or key in names or "#" in tag or "::" in tag or re.search(r"[{}\[\]]", tag):
            return False
        return not re.search(r"[()]", tag) or bool(_QUALIFIED_TAG.fullmatch(tag.strip()))
    removable = list(dict.fromkeys([t for t in tags if editable(t)] + [t for b in bags for t in b[1:] if editable(t)]))
    reply, info = _chat(context, af.FOLLOWUP_SYSTEM,
                        af.followup_message(tags, sentence, wish, [(b[0], b[1:]) for b in bags if b]),
                        af.followup_grammar(removable), max_tokens=320)
    got = af.parse_followup(reply, removable) if reply is not None else None
    if got is None:
        return {"ok": False, "model": info,
                "error": ("AI 모델이 답하지 않아 고치지 못했습니다." if reply is None
                          else "AI 모델의 답을 읽지 못했습니다 — 다시 시도해 주세요.")}
    try:
        index = _ko_dict_index(context, layer, vocab)
        wish_lemmas = set(index.query(wish))
    except Exception:                               # Kiwi 가 없으면 영문으로 적은 것만 가리킨다
        index, wish_lemmas = None, set()

    def pointed(tag: str) -> bool:
        """요청 낱말이 가리키나 — 사전 키워드 구절(되살리기와 같은 KoDictIndex.grounded: '머리' -> 긴 머리 · 짧은 머리,
        '비' -> rain) · 영문으로 적었나. 다듬기의 _grounded_tags 는 흔한 낱말(고양이 -> 열 개 넘는 태그)을 일부러 버려
        cat 을 못 더하고 long hair 를 못 뺐다(시도 09-28)."""
        key = af.tag_key(tag)
        name = vocab.canonical(key) or key
        # Q · E 에서 바꿔 단 이름(restrained)은 옛 이름(tied up (nonsexual))의 키워드로도 가리킨다 — '포박을 빼줘'(Codex 11차 R7)
        names = rating_sources(name, req["rating"])
        return (mentions(key, wish) or any(mentions(n, wish) for n in names[1:])
                or (index is not None and any(index.grounded(n, wish, wish_lemmas) for n in names)))
    removed = [t for t in got.remove if pointed(t)]
    kept_back = [t for t in got.remove if t not in removed]
    gone = {af.tag_key(t) for t in removed}
    # 고칠 점이 캐릭터 이름을 말하면 그 칸만(카나데만 머리를 짧게 — 두 칸 다 long hair 였는데 둘 다 뺐다, Codex 8차 F5).
    # 이름 뒤가 '만' 이면 그 칸만, '는 그대로 · 말고 · 빼고 · 두고' 면 그 칸은 아니다('나히다는 그대로 두고 카나데만' — 9차 F5)
    said = compact(clean_text(wish))
    named: set[int] = set()
    only: set[int] = set()
    spared: set[int] = set()
    for i, c in enumerate(fu["characters"]):
        key = compact(clean_text(str(c.get("ko") or "")))
        if not bags[i] or not key or key not in said:
            continue
        named.add(i)
        for m in re.finditer(re.escape(key), said):
            tail = said[m.end():]
            if tail.startswith("만"):
                only.add(i)
            if tail.startswith(_SPARE_TAILS):
                spared.add(i)
    target = only or (named - spared)
    # 이미 있는 태그는 고칠 곳 안에서만 본다 — 나히다의 short hair 때문에 카나데에게 short hair 를 못 더했다(9차 N1).
    # 대상 칸이 있으면 메인만 보고, 칸마다의 겹침은 칸에 넣을 때 따로 거른다
    scope = tags if target else tags + [x for b in bags for x in b]
    present = {af.tag_key(t) for t in scope} - gone
    share = _rating_share(context, req["rating"])
    gate = RATING_GATE.get(req["rating"])
    added: list[str] = []
    refused: list[str] = []
    unknown: list[str] = []
    for tag in got.add:
        name = exact_english(tag, vocab)
        if not name or _junk_tag(name) or vocab.role(name) == "population":
            unknown.append(tag)
            continue
        name = rating_name(name, req["rating"])      # 고른 등급의 이름으로 먼저 — 있는지 · 더했는지도 그 이름으로(Codex 11차 R8)
        if af.tag_key(name) in present or name in added:
            continue
        s = share(name) if share and gate is not None else None
        # 더하기는 요청이 가리키거나 모델이 다시 쓴 제 문장에서 말한 것(자기 일관성 — '웃는 표정' 의 smile 은 사전 키워드가
        # '웃음' 이라 원형이 어긋난다). 빼기보다 느슨하다 — 넘치는 쪽은 빼기였다(시도 8회 중 4회)
        if not (pointed(name) or any(mentions(n, got.sentence) for n in rating_sources(name, req["rating"]))) \
                or (s is not None and s < gate):
            refused.append(name)
            continue
        added.append(name)
    if target:
        new_tags = list(tags)
        new_bags = [([b[0]] + [t for t in b[1:] if af.tag_key(t) not in gone]
                     + [a for a in added if af.tag_key(a) not in {af.tag_key(x) for x in b}]) if i in target else b
                    for i, b in enumerate(bags)]
    else:
        new_tags = [t for t in tags if af.tag_key(t) not in gone] + added
        new_bags = [[b[0]] + [t for t in b[1:] if af.tag_key(t) not in gone] if b else [] for b in bags]
    chars = [{**c, "prompt": ", ".join(b)} for c, b in zip(fu["characters"], new_bags)]
    out: dict[str, Any] = {
        "ok": True, "task": "scene", "rating": req["rating"], "model": info,
        "prompt": {"main": _with_sentence(", ".join(new_tags), got.sentence or sentence), "characters": chars},
        "followup": {"removed": removed, "added": added, "kept": kept_back, "refused": refused, "unknown": unknown,
                     "sentence": got.sentence, "tags": [t for t in new_tags if not is_people(af.tag_key(t))],
                     "target": sorted(target)},
        "leftovers": [], "actions": [], "samples": [], "refine": None, "recover": None, "explain": None,
        "message": None, "pool": None,             # 풀이 없으면 None — 화면이 이전 결과의 핀을 이어 쓰지 않게
    }
    # 이벤트 검색을 새 태그로 다시 판다(인원 · 등급 · 제외는 이전 풀 그대로) — 맵이 없으면 조용히 건너뛴다
    cands = [n for n in dict.fromkeys(vocab.canonical(af.tag_key(t)) for t in new_tags)
             if n and vocab.role(n) != "population" and af.tag_key(n) not in names]
    if cands:
        exclude = [t.strip() for t in fu["exclude"].split(",") if t.strip()]
        try:
            drill = _event_map(context).drill(candidates=cands, exclude=exclude, ratings=req["rating"],
                                              persons=fu["persons"], min_posts=MIN_POOL)
            pins = list(drill.get("pins") or [])
            out["pool"] = {"pins": ",".join(pins), "exclude": ",".join(drill.get("exclude") or []),
                           "ratings": req["rating"], "persons": fu["persons"], "posts": int(drill.get("posts") or 0),
                           "trail": drill.get("trail")}
            out["leftovers"] = list(drill.get("left") or [])
        except Exception:
            out["pool"] = None
    out["timing"] = {"model_s": info.get("elapsed"), "total_s": round(time.perf_counter() - started, 3)}
    return out


def _fallback_route(ka: Any) -> dict[str, Any]:
    """모델 없이: 한국어 층이 찾은 것만으로 장면 검색."""
    return {"task": "scene" if (ka.specific or ka.verb_tags) else "other", "goal": "find", "characters": [],
            "actions": [], "include": [], "exclude": [], "name": "", "name_ko": ""}


def run_assist(context: Any, payload: Any) -> dict[str, Any]:
    from core.assist_english import en_key
    from core.assist_v2 import GUIDE, drop_tags, make_recap, merge, off_rating, swap_for_rating

    started = time.perf_counter()
    try:
        req = _parse_payload(context, payload)
    except AssistError as exc:
        return {"ok": False, "error": str(exc)}
    if req["followup"] is not None:
        return _followup(context, req, started)
    if req["direct"]:
        return _direct(context, req, started)
    from core.assist_compose import parse_segments

    segs = parse_segments(req["text"])
    if segs:                                     # main / c1 이름 - 설명 … — 프롬프트 제안 + 설명(구성)
        return _compose(context, req, segs, started)
    layer = korean_layer(context)
    t = time.perf_counter()
    layer.warm()
    ka = layer.analyze(req["text"])
    # 자동으로 찾은 이름 = 칩 제안 — 인물을 만들지 않고 문장 구조에만 쓴다(이름 낱말을 태그로 찾거나 고르기에 묻지 않는다).
    # 인물은 사용자가 고른 캐릭터뿐이다(사용자 결정 09-25). '이름 아님' 은 제안에서도 뺀다(원래 뜻으로 — 호두를 먹는).
    ka.names = [h for h in ka.names if h.form not in req["not_names"]]
    approved, refused = _approved_names(layer, req)
    korean_ms = round((time.perf_counter() - t) * 1000, 1)
    literal, literal_info = _literal(context, req["text"]) if req["literal"] else (None, {})
    route, model = _call_model(context, req["text"], req["previous"], literal=literal)
    chooser, choose_state = None, None
    vocab = _tag_vocab(context, layer)
    if route is None:
        route = _fallback_route(ka)
    else:
        chooser, choose_state = _make_chooser(context, layer, ka, req, route, vocab)
    rules = layer.rules
    merged = merge(route, ka, vocab, text=req["text"], generic=rules["generic_tags"],
                   simile_particles=rules["simile_particles"],
                   approved=approved,
                   not_names=list(rules["not_names"]) + req["not_names"], poses=rules["poses"],
                   generic_roles={w for group in rules.get("people", {}).values() for w in group},
                   roles_for=lambda names: layer.roles_for(ka, names), chooser=chooser)
    if merged.task == "other" and merged.english.keep:
        merged.task = "scene"                    # 영문 태그만 적은 요청(1girl, crying, prison cell) — 장면으로 싣는다(09-26)
        merged.log.append("task:scene(영문)")
    t_sense = time.perf_counter()
    _sense_check(context, layer, ka, merged, vocab)
    sense_ms = round((time.perf_counter() - t_sense) * 1000, 1)
    # 미번역 낱말 되살리기(09-26 첫 마일스톤) — 뜻 검사 뒤 · 등급 게이트 앞. 모델이 없으면 건너뛴다(고를 수 없다 — 지어내지 않는다)
    recover: dict[str, Any] | None = None
    t_recover = time.perf_counter()
    if req["recover"] and merged.task == "scene" and not model.get("error"):
        try:
            recover = _recover(context, req, layer, ka, merged, vocab, _persons_total(layer, ka, merged, req))
        except Exception as exc:                 # 되살리기가 깨져도 Assist 는 산다
            recover = {"units": [], "added": [], "error": f"{type(exc).__name__}: {exc}"}
    recover_s = round(time.perf_counter() - t_recover, 3)
    share = _rating_share(context, req["rating"])
    typed = merged.english.keys()                # 사용자가 영문으로 적은 것은 적힌 그대로 — 등급 게이트도 거치지 않는다
    gated = [t for t in merged.all_tags() + [a for c in merged.characters for a in c.attrs]
             + [r[1] for r in merged.relations] if en_key(t) not in typed]
    dropped = off_rating(gated, share, RATING_GATE[req["rating"]]) if share else {}
    drop_tags(merged, dropped)
    refine, refine_info = (_refine(context, req, merged, vocab, share, literal, layer, ka,
                                   keep=(recover or {}).get("added") or ())
                           if req["refine"] and merged.task == "scene" else (None, {}))
    _add_character_features(context, merged)
    swap_for_rating(merged, req["rating"])      # Q · E 의 tied up (nonsexual) -> restrained(사용자 제보 09-28)
    out: dict[str, Any] = {
        "ok": True, "task": merged.task, "goal": merged.goal, "rating": req["rating"],
        # 인물 = 고른 캐릭터(후보 전체 — 화면이 목록을 그린다) + 받지 못한 선택(chosen=false — 화면이 그 선택을 푼다)
        "names": _names_out(layer, merged.characters, refused),
        # 고르지 않은 이름 제안 — 캐릭터로 쓰지 않았다(화면: '이름을 눌러 고르면 캐릭터로 넣습니다')
        "suggested_names": _suggested(ka.names, merged.characters),
        "relations": [{"source": s, "action": a, "target": d} for s, a, d in merged.relations],
        "model": model,
        "literal": literal,
        "refine": refine,
        # 미번역 낱말 되살리기 — 덩어리마다 후보 · 답 · 고른 것(added 는 2순위 층에 실었다). 없으면 None
        "recover": recover,
        # 요청에 섞어 쓴 영문 — 적힌 그대로 실었다(keep) · 뺐다(exclude) · 인원으로 셌다(people)
        "english": {"keep": merged.english.keep, "exclude": merged.english.exclude, "people": merged.english.people},
        "trace": {"korean": ka.notes, "merge": merged.log,
                  "route": {k: v for k, v in route.items() if v not in ("", [], None)},
                  "choose": choose_state},
    }
    t = time.perf_counter()
    if merged.task == "scene":
        out.update(_scene(context, layer, ka, merged, req, vocab))
    elif merged.task == "tag":
        out.update(_tags(context, merged, route))
    elif merged.task in ("character", "artist", "wildcard", "preset"):
        out.update(_lane(context, layer, merged, route, req, ka.names))
    else:
        out["guide"] = GUIDE
    out["timing"] = {"korean_ms": korean_ms, "literal_s": literal_info.get("elapsed"),
                     "refine_s": refine_info.get("elapsed"), "model_s": model.get("elapsed"),
                     "choose_s": ((choose_state or {}).get("model") or {}).get("elapsed"),
                     "choose_prep_ms": (choose_state or {}).get("prep_ms"), "sense_ms": sense_ms,
                     "recover_s": recover_s,
                     "search_ms": round((time.perf_counter() - t) * 1000, 1),
                     "total_s": round(time.perf_counter() - started, 3)}
    if merged.task in ("scene", "tag"):
        partition = (out.get("persons") or {}).get("partition", "unknown")
        out["recap"] = make_recap(merged, partition=partition, rating=req["rating"])
    _with_rating_note(out, req["rating"], dropped)
    return out


def _add_character_features(context: Any, merged: Any) -> None:
    """고른 캐릭터마다 특징(character_analysis — 눈 · 머리 · 피부 색 · 오드아이 · 가슴 크기 …)을 캐릭터 칸 끝에
    (사용자 지정 09-26). 요청이 이미 말한 갈래(빨간 머리 · 제외한 가슴 크기)는 싣지 않는다 — core/assist_compose."""
    from core import assist_compose as ac

    have = set(merged.all_tags()) | set(merged.english.keep) | set(merged.exclude)
    for c in merged.characters:
        _work, entry = _character_profile(context, c.tag)
        c.features = ac.character_features(entry, have=have | set(c.attrs))
        if c.features:
            merged.log.append(f"features:{c.tag}->{','.join(c.features)}")


# ── 미번역 낱말 되살리기(S9d, 09-26 첫 마일스톤 — core/assist_recover) ─────────────────────────────


def _recover_entries(context: Any, layer: Any, vocab: Any) -> list[tuple[str, str, str]]:
    """사전 원형 색인에 넣을 태그 — 쓸 수 있는 것(TagFinder.usable: 설명 있음 · 작가/캐릭터/작품 아님 · 50건 이상)을
    이벤트 맵 이름으로. (태그, keywords_kr, description)."""
    from app.backend.server.autocomplete_commands import _ensure_kr_raw
    from core import assist_compose as ac

    raw = _ensure_kr_raw(context) or {}
    finder = ac.TagFinder(_compose_tools(context, layer, vocab))
    out: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for tag, info in raw.items():
        if not isinstance(info, dict) or not finder.usable(tag):
            continue
        name = vocab.canonical(tag)
        if name and name not in seen:
            seen.add(name)
            out.append((name, str(info.get("keywords_kr") or ""), str(info.get("description") or "")))
    return out


def _ko_dict_index(context: Any, layer: Any, vocab: Any) -> Any:
    """사전 설명 · 키워드 원형 색인 — 세션에 하나(창을 열 때 뒤에서 만든다, 약 2만 태그 · 수 초)."""
    from core.assist_recover import KoDictIndex

    with _RECOVER_LOCK:
        index = getattr(context, "assist_ko_dict_index", None)
        if index is None:
            if not layer.warm():                      # Kiwi 가 없으면 빈 색인을 세션 내내 쥐게 된다 — 만들지 않는다
                raise RuntimeError(f"한국어 분석기(Kiwi)가 없습니다: {layer.error}")
            started = time.perf_counter()
            index = KoDictIndex(_recover_entries(context, layer, vocab), layer.raw_tokens_many, layer.raw_tokens)
            index.seconds = round(time.perf_counter() - started, 1)
            context.assist_ko_dict_index = index
    return index


def _exact_word_index(context: Any) -> dict[str, set[str]]:
    """이벤트 맵 태그 이름의 낱말(그대로) -> 태그 — 뜻 키워드로 이름을 맞출 때. 맵이 바뀌면 다시 만든다."""
    from core.assist_recover import word_index

    try:
        idx = _event_map(context).index()
    except Exception:
        return {}
    cached = getattr(context, "assist_exact_word_index", None)
    if not cached or cached[0] is not idx:
        cached = (idx, word_index(idx.by_id.values()))      # ⚠️ by_id 는 {id: 이름}
        context.assist_exact_word_index = cached
    return cached[1]


def _recover_rank(context: Any, names: Iterable[str], pins: list[str], rating: str, count: Any,
                  scores: dict[str, float] | None = None, limit: int = 6) -> list[str]:
    """후보 줄 세우기 — 이벤트 맵 공출현 순(지금 태그 앞쪽을 핀으로 explore + 고른 등급 분면 browse, 인원 분면은 걸지 않는다:
    1girl_solo 풀에 hug from behind 가 0건이라 막혔다). scores(사전 맞춤)가 있으면 문턱에 빠진 나머지를 점수 순으로 뒤에 —
    사전의 드문 정확 일치(거구 -> giant male, 메이드 풀 0건)가 통째로 사라지지 않게. 맵이 없으면 점수 · 게시물 순."""
    import numpy as np

    names = list(dict.fromkeys(n for n in names if n))
    if not names:
        return []
    out: list[str] = []
    mapped = True
    try:
        idx = _event_map(context).index()
        mask = np.zeros(idx.n_tags, dtype=bool)
        for n in names:
            tid = idx.resolve(n)
            if tid is not None:
                mask[tid] = True
        if mask.any():
            if pins:
                ex = idx.explore(pins[:2], ratings=[rating], allowed=mask, sort="posts", limit=limit, min_posts=3)
                out += [c["tag"] for c in ex.get("candidates") or []]
            part = idx.browse(ratings=[rating], allowed=mask, limit=limit, min_posts=20)
            out += [c["tag"] for c in part.get("candidates") or [] if c["tag"] not in out]
    except Exception:
        out, mapped = [], False
    # 뜻 키워드 후보(scores 없음)는 맵이 있으면 공출현한 것만 — 평가(S2 · S9d)와 같다. 맵이 없을 때만 게시물 순으로 대신
    if scores is not None or not mapped:
        rest = sorted((n for n in names if n not in out),
                      key=lambda n: (-(scores or {}).get(n, 0.0), -int(count(n) or 0), n))
        out += rest
    return out[:limit]


def _explained_lemmas(layer: Any, ka: Any, index: Any, tags: Iterable[str], info: Any) -> set[str]:
    """요청의 어느 말을 이미 설명했나(원형 열쇠) — 지금 태그의 한국어 키워드 · 한국어 층의 사전 구 · 규칙(동사 · 관용구 ·
    몸 부위 · 시청자). 설명문은 쓰지 않는다(maid 설명의 '주인' 이 주인을 설명한 것으로 치면 되살릴 수 없다)."""
    from core.assist_recover import clean_keywords

    out: set[str] = set()
    for tag in tags:
        lem = index.keyword_lemmas(tag)
        if not lem:                                   # 색인 밖 태그(설명 없음 · 드묾)는 그 자리에서 키워드를 가른다
            lem = set(index.query(clean_keywords((info(tag) or {}).get("keywords_kr"))))
        out |= set(lem)
    for span in ka.phrases:
        out |= set(index.query(span))
    rules = layer.rules
    prefixes = [p for p, _t in rules.get("stem_prefixes") or ()]
    verbs = rules.get("verbs") or {}
    for s in ka.stems:
        if s in verbs or any(s.startswith(p) for p in prefixes):
            out.add(f"{s}/P")
    out |= {f"{s}/P" for s in set(ka.idiom_verbs) | set(ka.phrase_stems)} | {f"{v}/N" for v in ka.vehicles}
    for note in ka.notes:
        if note.startswith("부위:"):                    # 부위:손+묶이->['bound wrists']
            for form in note[3:].split("->", 1)[0].split("+"):
                out |= {f"{form}/N", f"{form}/P"}
    if ka.viewer:                                     # 나를 쳐다보는 -> looking at viewer
        out |= {f"{s}/P" for s in ka.stems if "보" in s}
    return out


def _recover(context: Any, req: dict[str, Any], layer: Any, ka: Any, merged: Any, vocab: Any,
             persons: int) -> dict[str, Any] | None:
    """미번역 낱말 되살리기(S9d) — 결과 태그가 설명하지 못한 요청의 말을 찾아(find_units) 사전 · 뜻 키워드 · 이벤트 맵으로
    후보를 모으고 제품의 번호 고르기(정순 · 역순)로 골라 2순위 층에 싣는다. 고를 것이 없으면 모델을 부르지 않는다.
    평가 · 규칙의 근거: core/assist_recover 머리말 · docs/assist_vocab_handoff/untranslated/."""
    from core import assist_candidates as cand
    from core import assist_compose as ac
    from core import assist_recover as ar
    from core.assist_candidates import GENERIC_NOUNS
    from core.assist_english import en_key
    from core.assist_korean import clean_text
    from core.assist_v2 import _junk_tag

    if not getattr(ka, "available", True):
        return None
    started = time.perf_counter()
    index = _ko_dict_index(context, layer, vocab)
    tools = _compose_tools(context, layer, vocab)
    finder = ac.TagFinder(tools)
    rules = layer.rules
    tags_now = list(dict.fromkeys(merged.all_tags() + [a for c in merged.characters for a in c.attrs]
                                  + [r[1] for r in merged.relations]))
    # 영문으로 적은 것(적힌 그대로 실린다, core/assist_english)도 이미 있는 것 — 그 뜻을 다시 찾거나 겹쳐 싣지 않는다
    typed = [t for t in (vocab.canonical(en_key(p)) for p in merged.english.keep + merged.english.exclude) if t]
    explained = _explained_lemmas(layer, ka, index, tags_now + typed, tools.info)
    names = {h.form for h in ka.names} | {c.ko for c in merged.characters}
    skip = set(GENERIC_NOUNS) | set(ar.BASIC_PEOPLE) | set(rules.get("spatial_words") or ()) | names \
        | {piece for n in names for piece in n.split()}
    text = clean_text(req["text"])
    units = ar.find_units(layer.spans(req["text"]), text, explained=explained, skip=skip,
                          people=ar.person_words(rules), stop_verbs=rules.get("filler_stems") or ())
    if not units:
        return None
    share = _rating_share(context, req["rating"])
    gate = RATING_GATE.get(req["rating"])
    present = set(tags_now) | set(merged.exclude) | set(typed)

    def ok(tag: str) -> bool:
        if not tag or tag in present or _junk_tag(tag) or not finder.usable(tag) or vocab.role(tag) == "population":
            return False
        if not ar.pair_ok(tag, persons):               # 엄마 한 사람에 mother and child
            return False
        s = share(tag) if share and gate is not None else None
        return s is None or s >= gate

    # 핀 = 지금 태그의 앞쪽 둘(층 순 · 게시물 순) — 인원 태그는 분면이지 핀이 아니다
    pins = [t for t in merged.ordered(vocab.count) if vocab.canonical(t) and vocab.role(t) != "population"][:2]
    request = set(index.query(text))
    plans = []
    for unit in units:
        matched = index.match(unit.text, keywords_only=unit.person)     # 사람 낱말은 키워드에서만(설명문 -> slave)
        # 원형 하나만 맞은 태그는 뺀다 — 비틀 -> nipple tweak(유두비틀기) · 건너편 -> misty lake(설명의 호수 건너편), 09-28
        matched = {n: s for n, s in matched.items() if index.grounded(n, unit.text, request)}
        dict_names = _recover_rank(context, [n for n in matched if ok(n)], pins, req["rating"], vocab.count,
                                   scores=matched, limit=ar.MAX_CANDIDATES)
        need_kw = not dict_names or index.completeness(unit.text, matched, keywords_only=unit.person) < 1.0
        plans.append((unit, dict_names, need_kw))
    calls = 0
    failed = None                                     # 모델 호출이 실패하면 그 뒤는 부르지 않는다(죽은 엔진은 매번 제한 시간)
    keywords: dict[str, list[str]] = {}
    kw_units = [u.text for u, _d, need in plans if need]
    if kw_units:                                      # 뜻 키워드 두 번(합집합) — 실행마다 흔들려서
        message = ar.kw_message(text, tags_now, kw_units)
        for _ in range(2):
            reply, info = _chat(context, ar.KW_SYSTEM, message, ar.kw_grammar(kw_units),
                                max_tokens=max(120, 50 * len(kw_units)))
            calls += 1
            if reply is None:
                failed = info.get("error") or "모델 호출 실패"
                break
            for unit_text, words in ar.parse_keywords(reply, kw_units).items():
                keywords[unit_text] = list(dict.fromkeys(keywords.get(unit_text, []) + words))
    windex = _exact_word_index(context) if keywords else {}
    done = list(tags_now)
    added: list[str] = []
    out_units: list[dict[str, Any]] = []
    for unit, dict_names, need_kw in plans:
        words = keywords.get(unit.text, [])
        kw_names: list[str] = []
        if need_kw and words:
            pool: set[str] = set()
            for word in words:
                for form in ar.keyword_forms(word):
                    pool |= windex.get(form, set())
            kw_names = _recover_rank(context, [n for n in pool if ok(n)], pins, req["rating"], vocab.count,
                                     limit=ar.MAX_CANDIDATES)
        listed = list(dict.fromkeys(dict_names + kw_names))[:ar.MAX_CANDIDATES]
        source = ("both" if dict_names and kw_names else "dictionary" if dict_names
                  else "keywords" if kw_names else "none")
        answers: list[Any] = []
        picks: list[str] = []
        if listed and failed is None:
            ask = cand.Ask(ko=unit.text, en=", ".join(words),
                           candidates=[(t, ac._short(str((tools.info(t) or {}).get("description") or ""))) for t in listed])
            orders = [ask] if len(listed) < 2 else [ask, cand.Ask(ko=ask.ko, en=ask.en,
                                                                  candidates=list(reversed(ask.candidates)))]
            for order in orders:
                names_in_order = [t for t, _d in order.candidates]
                reply, info = _chat(context, cand.CHOOSE_SYSTEM, cand.choose_message(req["text"], order, done),
                                    cand.choose_grammar(len(names_in_order)), max_tokens=4)
                calls += 1
                if reply is None:                     # 엔진이 없거나 죽었다 — 싣지 않는다(지어내지 않는다)
                    failed = info.get("error") or "모델 호출 실패"
                    answers = []
                    break
                answers.append(cand.parse_choice(reply, names_in_order))
            if answers:
                picks = cand.settle_order(answers[0], answers[1] if len(answers) > 1 else answers[0], listed) or []
        for tag in picks:
            if tag not in present:
                merged.tiers[1].append(tag)
                present.add(tag)
                added.append(tag)
                done.append(tag)
        merged.log.append(f"recover:{unit.text}->{','.join(picks) or '없음'}")
        out_units.append({"text": unit.text, "lemmas": unit.lemmas, "kind": unit.kind, "person": unit.person,
                          "source": source, "keywords": words, "candidates": listed, "answers": answers,
                          "picks": picks})
    return {"units": out_units, "added": added, "calls": calls, "error": failed,
            "elapsed": round(time.perf_counter() - started, 3), "index_seconds": getattr(index, "seconds", None)}


def _persons_total(layer: Any, ka: Any, merged: Any, req: dict[str, Any]) -> int:
    """되살리기의 두 사람 태그 문턱 — 지금 인원(수동이면 그 수, 자동이면 사람 낱말 · 고른 캐릭터 · 영문 인원 태그)."""
    p = _persons(layer, ka, merged, req)
    return int(p.get("girls") or 0) + int(p.get("boys") or 0) + int(p.get("unknown") or 0)


def _english_people(pc: Any, people: list[str]) -> None:
    """영문 인원 태그(2girls · 1boy · solo)를 적었으면 그 수를 받는다 — 성별마다 큰 쪽(소녀와 1boy -> 1girl, 1boy).
    인원 태그는 적힌 그대로 싣지 않는다 — 인원 칸이 구획으로 싣는다(1girl, solo 가 두 번 나오지 않게)."""
    from core.assist_english import people_count
    from core.assist_korean import partition_of

    if not people:
        return
    g, b, solo = people_count(people)
    pc.girls, pc.boys, pc.solo = max(pc.girls, g), max(pc.boys, b), pc.solo or solo
    pc.partition = partition_of(pc.girls, pc.boys, pc.solo)           # solo 는 적었을 때만(says_solo · 영문 solo)
    pc.confirm = bool(pc.unknown) or pc.partition == "unknown"
    pc.notes.append("영문:" + ",".join(people))


def _persons(layer: Any, ka: Any, merged: Any, req: dict[str, Any]) -> dict[str, Any]:
    from core.assist_korean import PersonCount, partition_of

    if req["persons"]["mode"] == "manual":
        # 여 1 로 정해도 solo 는 '혼자' · '홀로' (영문 solo)를 적었을 때만(사용자 지정 09-28)
        g, b = req["persons"]["girls"], req["persons"]["boys"]
        solo = g + b == 1 and (layer.says_solo(req["text"]) or "solo" in merged.english.people)
        pc = PersonCount(girls=g, boys=b, partition=partition_of(g, b, solo))
        return {"mode": "manual", "partition": pc.partition, "girls": g, "boys": b, "unknown": 0,
                "confirm": False, "notes": [], "param": pc.persons_param()}
    pc = layer.count_persons(ka, approved={c.ko: c.gender for c in merged.characters}, not_names=req["not_names"])
    _english_people(pc, merged.english.people)
    return {"mode": "auto", "partition": pc.partition, "girls": pc.girls, "boys": pc.boys, "unknown": pc.unknown,
            "confirm": pc.confirm, "notes": pc.notes, "param": pc.persons_param()}


def _scene(context: Any, layer: Any, ka: Any, merged: Any, req: dict[str, Any], vocab: Any) -> dict[str, Any]:
    from core.assist_english import en_key
    from core.assist_v2 import compose, exact_english

    persons = _persons(layer, ka, merged, req)
    out: dict[str, Any] = {"persons": persons}
    candidates = merged.ordered(vocab.count)
    # 영문으로 적은 태그(full body)도 풀에 꽂아 본다 — 한국어 쪽 뒤에(장면의 뼈대는 한국어 요청이다, 09-26).
    # 못 꽂혀도 프롬프트에는 적힌 그대로 실린다(compose)
    for part in merged.english.keep:
        tag = exact_english(en_key(part), vocab, verb=False)
        if tag and tag not in candidates and tag not in merged.exclude:
            candidates.append(tag)
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
        # 이벤트 맵은 선택 자산이다 — 색인을 안 받은 PC(state=missing)는 고장이 아니라 알리지 않는다(뜻 검사 · 등급 게이트 ·
        # 구성도 조용히 건너뛴다). 파일은 있는데 못 여는 것(받다 끊김 등)만 알린다(09-27 제보: 클린 사용자에게 결과마다 떴다)
        if (getattr(exc, "extra", None) or {}).get("state") != "missing":
            out["message"] = f"이벤트 맵 파일을 열지 못해 장면 태그만 실었습니다({exc})."
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
                actions = _sample_actions(service, rows, set(merged.all_tags()) | set(candidates), layer.rules)
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


def _lane(context: Any, layer: Any, merged: Any, route: dict[str, Any], req: dict[str, Any],
          suggested: list[Any] = ()) -> dict[str, Any]:
    """캐릭터·작가·와일드카드·프리셋: Fast Search 같은 갈래. 캐릭터는 한-영 색인·이름 조각·팩 순위가 먼저.
    캐릭터 찾기의 답은 사용자가 고르는 목록이라 자동 제안(suggested)도 싣는다 — 프롬프트에 들어가는 인물이 아니다."""
    import re

    from app.backend.server.fast_search_routes import SEARCHERS

    task = merged.task
    if task == "character" and (merged.characters or suggested):
        items = [{"value": c.tag, "title": c.tag, "subtitle": c.ko, "alts": c.alts, "gender": c.gender}
                 for c in merged.characters]
        items += [{"value": h.tag, "title": h.tag, "subtitle": h.form, "alts": [t for t, _n in h.candidates[1:3]],
                   "gender": h.gender} for h in suggested if h.candidates and h.tag not in [i["value"] for i in items]]
        return {"items": items}
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
            hit = layer.name_hit(q, explicit=True)
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


# ── 구성(여러 줄 요청 — main / c1 이름 - 설명) ────────────────────────────────
# 사용자 지정(2026-09-24): "Claude 같은 답을 E2B 로 — Tool Calling 으로 최대한 제한". 흐름·실측은 core/assist_compose.py ·
# 설계 문서 15절. E2B 는 두 번(영문 추측 · 엇갈린 절만 고르기), 나머지는 도구다.


def _chat(context: Any, system: str, user: str, grammar: str, max_tokens: int) -> tuple[str | None, dict[str, Any]]:
    """E2B 한 번(문법 강제). (본문 | None, 기록). 엔진·모델이 없거나 실패하면 None — 도구만으로 간다."""
    from app.backend.server.boost_v2_service import get_boost_runtime

    info: dict[str, Any] = {}
    try:
        runtime = get_boost_runtime(context)
        runtime.hold("assist", ASSIST_LEASE_SECONDS)
        status = runtime.status()
        if not status.get("engine_exists"):
            info.update(error="llama.cpp 엔진이 없습니다.", code="engine_missing")
            return None, info
        if not status.get("model_exists"):
            info.update(error="AI 모델이 없습니다 — API 설정의 [AI 모델]에서 받아 주세요.", code="model_missing")
            return None, info
        # 샘플링은 Gemma 4 권장값(core/llama_runtime.SAMPLING, 사용자 지정 09-26) — 예전엔 온도 0 으로 같은 요청에 같은
        # 추측을 샀지만 권장 밖이었다. 이제 실행마다 답이 흔들릴 수 있다 — 안정은 문법 잠금 · 사전 확인이 맡는다
        resp = runtime.chat(user, system=system, grammar=grammar, max_tokens=max_tokens, timeout=MODEL_TIMEOUT)
        info.update({k: resp.get(k) for k in ("elapsed", "usage", "load_seconds", "queue_wait", "gpu") if k in resp})
        if not resp.get("ok"):
            info["error"] = str(resp.get("error") or "모델 호출 실패")
            return None, info
        return str(resp.get("text") or ""), info
    except Exception as exc:
        info["error"] = f"{type(exc).__name__}: {exc}"
        return None, info


def _compose_tools(context: Any, layer: Any, vocab: Any) -> Any:
    """후보 찾기 도구 — NAIA 한국어 태그 사전 · 이벤트 맵 어휘(영문 낱말 색인, 세션에 한 번) · 한국어 층."""
    from app.backend.server.autocomplete_commands import _ensure_kr_raw, search_kr_tags
    from core.assist_compose import TagTools, angle_label, build_word_index, declared_names

    raw = _ensure_kr_raw(context) or {}
    counted = getattr(context, "assist_name_claims", None)
    if counted is None:     # 말 -> (제 이름으로 밝힌 태그 수, <라벨> 로 쓰는 태그 수) — <라벨> 이 제 이름인지 분류인지 가른다
        claims: dict[str, int] = {}
        labels: dict[str, int] = {}
        for info in raw.values():
            if not isinstance(info, dict):
                continue
            for name in declared_names(info):
                claims[name] = claims.get(name, 0) + 1
            label = angle_label(info)
            if label:
                labels[label] = labels.get(label, 0) + 1
        counted = (claims, labels)
        context.assist_name_claims = counted
    claims, labels = counted
    try:
        idx = _event_map(context).index()
        key, names = id(idx), list(idx.by_id.values())      # ⚠️ by_id 는 {id: 이름} — list() 는 id 만 준다
    except Exception:
        key, names = "kr", [t for t, i in raw.items() if isinstance(i, dict)
                            and not (i.get("_named_entity_category") or i.get("_cat"))]
    cached = getattr(context, "assist_word_index", None)
    if not cached or cached[0] != key:
        cached = (key, build_word_index(names))
        context.assist_word_index = cached

    def keyword_tags(key: str) -> list[str]:
        return [t for t, _n in layer.vocab.lookup(key)]

    def fuzzy(ko: str) -> list[str]:
        try:
            return [str(r.get("tag")) for r in search_kr_tags(context, ko, limit=6) if r.get("tag")]
        except Exception:
            return []

    def nouns(ko: str) -> list[str]:
        return [f for f, t in layer.tokenize(ko) if t in ("NNG", "NNP") and len(f) >= 2]

    return TagTools(canonical=vocab.canonical, count=vocab.count, info=lambda t: raw.get(t) or {},
                    keyword_tags=keyword_tags, analyze=layer.analyze, word_index=cached[1], fuzzy=fuzzy,
                    nouns=nouns, role=vocab.role, name_claims=lambda word: claims.get(word, 0),
                    label_uses=lambda word: labels.get(word, 0))


def _work_tag(tools: Any, work: str | None) -> str | None:
    """작품 이름이 NAIA 사전의 작품(copyright) 태그일 때만 캐릭터 칸에 싣는다(hololive · sana channel)."""
    if not work:
        return None
    info = tools.info(work) or {}
    return work if str(info.get("_named_entity_category") or info.get("_cat") or "") == "copyright" else None


def _index_of(form: str, names: list[str]) -> int:
    from core.assist_korean import compact

    packed = compact(form)
    return next((i for i, n in enumerate(names, 1) if compact(n) == packed), 0)


def _compose_relation(layer: Any, vocab: Any, rules: dict[str, Any], segs: list[Any], names: list[str]) -> Any:
    """인물 사이 방향·동작 — 장면 줄 먼저, 없으면 캐릭터 줄(주인을 주어로 세워서: 나토리 사나가 …에게 안긴채로).
    ⚠️ 글 전체를 한 번에 재지 않는다 — 장면 줄의 주어(카나데)와 c2 줄의 '카나데에게' 가 섞여 방향이 뒤집혔다."""
    from core.assist_compose import Relation, interaction_tag, subject_prefix

    texts = [segs[0].body] if segs and segs[0].body else []
    texts += [subject_prefix(names[seg.index - 1]) + seg.body for seg in segs[1:] if 0 < seg.index <= len(names)]
    for text in texts:
        ka = layer.analyze(text)
        roles = layer.roles_for(ka, names)
        act = interaction_tag(ka, vocab.role, rules.get("generic_tags") or (), rules.get("poses") or ())
        if not roles or not act:
            continue
        src, dst = _index_of(roles[0], names), _index_of(roles[1], names)
        if src and dst and src != dst:
            ko = next((k for k, v in ka.phrases.items() if v == act), "")
            return Relation(src, dst, act, ko)
    return None


def _compose_persons(req: dict[str, Any], chars: list[Any], people: list[str] = (), solo: bool = False) -> dict[str, Any]:
    """구성 요청의 인원 = 캐릭터 줄의 사람들(성별은 캐릭터 분석). 수동이면 그대로. people = 줄에 적은 영문 인원 태그.
    solo = 요청이 '혼자' · '홀로' 를 적었나 — 한 사람이라고 solo 가 아니다(사용자 지정 09-28)."""
    from core.assist_korean import PersonCount, partition_of

    if req["persons"]["mode"] == "manual":
        g, b = req["persons"]["girls"], req["persons"]["boys"]
        pc = PersonCount(girls=g, boys=b, partition=partition_of(g, b, g + b == 1 and (solo or "solo" in people)))
        return {"mode": "manual", "partition": pc.partition, "girls": g, "boys": b, "unknown": 0,
                "confirm": False, "notes": [], "param": pc.persons_param()}
    girls = sum(1 for c in chars if c.gender == "girl")
    boys = sum(1 for c in chars if c.gender == "boy")
    unknown = len(chars) - girls - boys
    pc = PersonCount(girls=girls, boys=boys, unknown=unknown, partition=partition_of(girls, boys, solo),
                     solo=solo)
    _english_people(pc, list(people))
    return {"mode": "auto", "partition": pc.partition, "girls": pc.girls, "boys": pc.boys, "unknown": unknown,
            "confirm": bool(unknown) or pc.partition == "unknown", "notes": pc.notes, "param": pc.persons_param()}


def _compose_evidence(context: Any, relation: Any, details: list[Any], req: dict[str, Any],
                      persons: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    """이벤트 맵 — (1) 동작과 각 태그가 **함께 달린** 게시물 수(근거) (2) Random 에 연결할 풀 (3) 실제 게시물 표본."""
    tags = list(dict.fromkeys(t for d in details for t in d.tags))
    evidence: dict[str, Any] = {"anchor_posts": 0, "with": {}}
    try:
        service = _event_map(context)
    except Exception:
        return evidence, {}, []
    try:
        if relation is not None:
            for tag in tags:
                d = service.drill(candidates=[relation.action, tag], exclude=[], ratings=req["rating"],
                                  persons=persons["param"], min_posts=1)
                trail, pins = list(d.get("trail") or []), list(d.get("pins") or [])
                if trail and pins[:1] == [relation.action]:
                    evidence["anchor_posts"] = int(trail[0])
                evidence["with"][tag] = int(trail[1]) if len(pins) > 1 and len(trail) > 1 else 0
        candidates = ([relation.action] if relation is not None else []) + tags
        drill = service.drill(candidates=candidates, exclude=[], ratings=req["rating"], persons=persons["param"],
                              min_posts=MIN_POOL)
    except Exception:
        return evidence, {}, []
    pins = list(drill.get("pins") or [])
    pool = {"pins": ",".join(pins), "exclude": "", "ratings": req["rating"], "persons": persons["param"],
            "posts": int(drill.get("posts") or 0), "trail": drill.get("trail")}
    samples: list[dict[str, Any]] = []
    if pins:
        try:
            rows = (service.sample(pins=pins, exclude=[], ratings=req["rating"], persons=persons["param"], n=3)
                    .get("samples") or [])
            samples = [{"tags": r.get("tags") or [], "prompt": r.get("prompt") or ""} for r in rows[:3]]
        except Exception:
            pass
    return evidence, pool, samples


def _first_name(layer: Any, text: str) -> str:
    """이름 칸이 비었을 때(c1 카나데가 웃는) 줄에서 처음 나온 캐릭터 이름."""
    try:
        names = layer.name_spans(text, use_kiwi=layer.ready()).get("names") or []
    except Exception:
        names = []
    return str(names[0].get("form") or "") if names else ""


def _compose(context: Any, req: dict[str, Any], segs: list[Any], started: float) -> dict[str, Any]:
    """여러 줄 요청 -> 메인·캐릭터 프롬프트 + 설명. 모델이 없으면 한국어 근거만으로(못 찾은 절은 설명에 남긴다).
    줄에 섞어 쓴 영문은 그 줄의 칸에 적힌 그대로 싣는다(core/assist_english, 09-26)."""
    from core import assist_compose as ac
    from core.assist_english import en_key, english_only, english_parts
    from core.assist_korean import compact
    from core.assist_v2 import PERSON_TAGS, off_rating, rating_name, rating_sources

    layer = korean_layer(context)
    t0 = time.perf_counter()
    layer.warm()
    vocab = _tag_vocab(context, layer)
    tools = _compose_tools(context, layer, vocab)
    finder = ac.TagFinder(tools)
    rules = layer.rules
    not_names = set(req["not_names"])
    approved, refused = _approved_names(layer, req)

    chars: list[Any] = []
    suggestions: list[Any] = []
    for seg in segs[1:]:
        name = seg.name or _first_name(layer, seg.body)
        # 캐릭터 줄의 이름도 사용자가 고른 것만 캐릭터다(09-25) — 고르지 않았으면 사람만(성별 모름 -> 인원 확인)
        hit = _approved_for(name, approved) if name and name not in not_names else None
        if hit is None and name and name not in not_names:
            guess = layer.name_hit(name, explicit=bool(seg.name))
            if guess is not None and guess.candidates:
                suggestions.append(guess)
        tag = hit.tag if hit else ""
        work, entry = _character_profile(context, tag) if tag else (None, None)
        chars.append(ac.ComposeCharacter(
            ko=name or f"캐릭터 {seg.index}", tag=tag, gender=hit.gender if hit else None,
            alts=[t for t, _n in hit.candidates[1:3]] if hit else [], work=_work_tag(tools, work),
            appearance=ac.character_features(entry)))       # 한 줄 경로와 같은 캐릭터 특징(09-26)
    names = [c.ko for c in chars]
    relation = _compose_relation(layer, vocab, rules, segs, names)

    details: list[Any] = []
    for seg in segs:
        for clause in layer.clauses(seg.body):
            if layer.is_relation_clause(clause, names):
                continue                                  # 방향·동작은 한국어 층이 맡았다(relation)
            clause = ac.strip_subject(clause, names)
            if len(compact(clause)) >= 2:
                details.append(ac.Detail(owner=seg.index, ko=clause, en=""))
    details = details[:ac.MAX_CLAUSES]
    # 줄마다 적은 영문 — 인원 태그는 인원으로, 빼라고 적은 것은 태그에서 빼고, 나머지는 그 줄의 칸에 적힌 그대로
    english = {seg.index: english_parts(seg.body) for seg in segs}
    typed = {k for e in english.values() for k in e.keys()}
    unwanted = {en_key(p) for e in english.values() for p in e.exclude}
    korean_ms = round((time.perf_counter() - t0) * 1000, 1)

    model: dict[str, Any] = {}
    subs: list[Any] = []
    if details:
        text, info = _chat(context, ac.GUESS_SYSTEM, ac.guess_message([d.ko for d in details]),
                           ac.guess_grammar(len(details)), max_tokens=60 + 30 * len(details))
        model["guess"] = info
        if text is None and info.get("error"):
            model.update(error=info["error"], code=info.get("code"))
        guesses = ac.parse_guesses(text, len(details)) if text is not None else [[] for _ in details]
        for d, found in zip(details, guesses):
            for en in found or [""]:
                subs.append(ac.Detail(owner=d.owner, ko=d.ko, en=en))
    taken: dict[tuple[int, str], set[str]] = {}
    # 고른 등급에 안 맞는 후보는 **고르기 전에** 뺀다 — 고른 뒤 게이트가 빼면 그 절이 통째로 빈다(대안이 있었는데)
    pre_share = _rating_share(context, req["rating"])
    pre_dropped: dict[str, float] = {}
    top_dropped: dict[str, float] = {}       # 그 절의 1순위가 빠진 것만 사용자에게 알린다(곁다리 후보까지 늘어놓지 않게)
    for d in subs:
        d.candidates = finder.rank(d.ko, d.en)
        if pre_share:
            off = off_rating([c.tag for c in d.candidates if en_key(c.tag) not in typed], pre_share,
                             RATING_GATE[req["rating"]])            # 영문으로 적은 것은 등급 게이트를 거치지 않는다
            if off:
                pre_dropped.update(off)
                if d.candidates[0].tag in off:
                    top_dropped[d.candidates[0].tag] = off[d.candidates[0].tag]
                d.candidates = [c for c in d.candidates if c.tag not in off]
        mine = taken.setdefault((d.owner, d.ko), set())
        ac.decide(d, taken=mine)
        mine.update(d.tags)
    asking = [d for d in subs if d.via == "ask" and d.ask]
    if asking and not model.get("error"):
        cands = [[c.tag for c in d.ask] for d in asking]
        items = [(f"{d.ko} ({d.en})" if d.en else d.ko,
                  [(c.tag, ac._short((tools.info(c.tag) or {}).get("description") or "")) for c in d.ask])
                 for d in asking]
        text, info = _chat(context, ac.CHOOSE_SYSTEM, ac.choose_message(items), ac.choose_grammar(cands),
                           max_tokens=30 + 12 * len(cands))
        model["choose"] = info
        picks = ac.parse_choice(text, cands) if text is not None else [None] * len(cands)
        for d, pick in zip(asking, picks):
            ac.apply_choice(d, pick)
    viewed: set[tuple[int, str]] = set()
    for d in subs:
        if d.via == "ask":
            ac.apply_choice(d, None)                      # 모델이 없다 — 지어내지 않는다(설명의 '못 찾음' 에 남는다)
        ac.add_companions(d, rules.get("companions") or ())
        if (d.owner, d.ko) not in viewed:                 # 절마다 한 번(같은 절의 다른 영문 추측에는 안 붙인다)
            viewed.add((d.owner, d.ko))
            ac.add_viewer(d, layer.analyze(d.ko).viewer)
    # Q · E 의 tied up (nonsexual) -> restrained — 한 줄 경로와 같은 규칙(Codex 11차 R5). 겹침 정리(dedupe) · 제외(unwanted)
    # **전에** 바꾼다 — 뒤에서 바꾸니 관계 동작과 캐릭터 칸에 같은 태그가 두 번 실리고, 뺀 태그가 되살아났다(12차 F4 · F5).
    # Q · E 엔 등급 게이트가 없어 아래 dropped 와 이름이 엇갈리지 않는다
    for d in subs:
        d.tags = list(dict.fromkeys(rating_name(t, req["rating"]) for t in d.tags))
        for c in d.candidates:
            c.tag = rating_name(c.tag, req["rating"])
    if relation is not None:
        relation.action = rating_name(relation.action, req["rating"])
    ac.dedupe(subs, relation, chars, tools.info)
    share = _rating_share(context, req["rating"])
    gated = [t for d in subs for t in d.tags] + ([relation.action] if relation is not None else [])
    dropped = (off_rating([t for t in gated if en_key(t) not in typed], share, RATING_GATE[req["rating"]])
               if share else {})
    def unwanted_tag(tag: str) -> bool:
        """영문으로 뺀 태그인가 — Q · E 에서 바꿔 단 이름은 옛 이름으로 뺀 것도(tied up (nonsexual) 빼고, Codex 13차 R2)."""
        return any(en_key(n) in unwanted for n in rating_sources(tag, req["rating"]))
    for d in subs:
        d.tags = [t for t in d.tags if t not in dropped and not unwanted_tag(t)]
    # 관계 동작도 영문으로 뺀 것이면 뺀다 — 메인과 source# · target# 에 남았다(13차 R3)
    if relation is not None and (relation.action in dropped or unwanted_tag(relation.action)):
        relation = None
    dropped = {**top_dropped, **dropped}

    persons = _compose_persons(req, chars, [p for e in english.values() for p in e.people],
                               solo=layer.says_solo(req["text"]))
    prompt = ac.assemble(people=PERSON_TAGS.get(persons["partition"], []), characters=chars, relation=relation,
                         details=subs, info=tools.info, extra={k: e.keep for k, e in english.items() if e.keep})
    t1 = time.perf_counter()
    evidence, pool, samples = _compose_evidence(context, relation, subs, req, persons)
    explain = ac.explain(characters=chars, relation=relation, details=subs, count=tools.count, info=tools.info,
                         cooccur=evidence.get("with"), anchor_posts=int(evidence.get("anchor_posts") or 0),
                         keyword_tags=tools.keyword_tags)
    # 영문만 적은 절(masterpiece)은 적힌 그대로 실렸다 — '못 찾음' 으로 알리지 않는다
    explain["missed"] = [m for m in explain.get("missed") or [] if not english_only(m.get("ko"))]
    out: dict[str, Any] = {
        "ok": True, "task": "scene", "goal": "how", "mode": "compose", "rating": req["rating"],
        "names": _names_out(layer, [c for c in chars if c.tag], refused),
        "suggested_names": _suggested(suggestions, [c for c in chars if c.tag]),
        # 관계는 두 쪽 다 고른 캐릭터일 때만 알린다 — 고르기 전의 줄은 태그가 없다(동작 태그는 메인에 남는다)
        "relations": ([{"source": chars[relation.source - 1].tag, "action": relation.action,
                        "target": chars[relation.target - 1].tag}]
                      if relation is not None and chars[relation.source - 1].tag and chars[relation.target - 1].tag
                      else []),
        "persons": persons, "prompt": prompt, "explain": explain, "pool": pool, "samples": samples,
        "model": model,
        "english": {key: list(dict.fromkeys(p for e in english.values() for p in getattr(e, key)))
                    for key in ("keep", "exclude", "people")},
        "trace": {"details": [{"who": d.owner, "ko": d.ko, "en": d.en, "tags": d.tags, "via": d.via,
                               "top": [(c.tag, round(c.score, 2)) for c in d.candidates[:3]]} for d in subs],
                  "rating_pre_dropped": pre_dropped},
    }
    model_s = sum(float((model.get(k) or {}).get("elapsed") or 0) for k in ("guess", "choose"))
    out["timing"] = {"korean_ms": korean_ms, "model_s": round(model_s, 2),
                     "search_ms": round((time.perf_counter() - t1) * 1000, 1),
                     "total_s": round(time.perf_counter() - started, 3)}
    if pool and not pool.get("pins"):             # 풀이 아예 없으면(이벤트 맵 없음) 게시물 수를 말할 수 없다
        out["message"] = "고른 등급·인원에서 이 조합의 실제 게시물이 20건이 안 됩니다 — 프롬프트는 그대로 쓸 수 있습니다."
    _with_rating_note(out, req["rating"], dropped)
    return out
