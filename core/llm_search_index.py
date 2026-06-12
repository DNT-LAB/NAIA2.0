"""LLM 어시스트 전용 태그 검색 인덱스 — autocomplete(UI 계약)와 완전 분리.

배경(사용자 진단, 2026-06-12): Ollama 어시스트의 모든 태그 오염(pen→penis,
자위→penile masturbation, head→heads together, looking at phone 21위)의 단일
뿌리는 LLM 개념→태그 검색이 UI 타이핑 보조용 autocomplete 인덱스(prefix/substring
매칭 + 빈도 랭킹 + 한국어 키워드 색인)를 재사용하는 것이다. 이 모듈은 LLM 파이프라인
전용 검색을 새로 깐다. `core/tag_search_index.py`(UI)는 불변.

설계 (호출부 실측 + 설계 패널 3 + Codex 인스펙션 반영):
- 어시스트 서비스는 검색 rows를 count 내림차순으로 재정렬하고(retriever 점수도
  count 지배) 정규화 정확일치 스캔으로 태그를 검증한다 → **검색기 랭킹은 자문일
  뿐, 무엇을 배제하느냐가 계약이다**. 잡음을 1행이라도 반환하면 count로 enum
  상단까지 승격될 수 있다.
- Exact 레인: 정규화 일치 직행 + 파생키(despaced/하이픈 변형) + 쿼리 프로브
  (원형/despaced/인접 토큰쌍 결합/±s,es 변형)로 컴파운드 양방향 브릿지
  ("cell phone"↔cellphone, "v neck"↔v-neck, "thigh high socks"→thighhighs).
  prefix 매칭 없이 복합어 recall을 보존한다(retriever 역사 교훈: whole-word
  데모션이 windowsill 류를 밀어 recall 회귀).
- 부분 레인: 태그명 토큰 whole-word 스테밍 역색인. 쿼리 토큰 스템과 후보 토큰
  스템의 완전 일치만 — pen→penis(스템 peni)가 구조적으로 불가능하다.
  랭킹 = 커버리지 우선(다단어 직접 표현 > 고빈도 단일겹침), 커버리지 1 티어는
  매칭 스템별 라운드로빈(한 단어 패밀리의 limit 독식 방지).
- exact 히트는 최상단 고정 후 부분 레인으로 limit까지 충전 — exact 단독 반환은
  개념당 후보 enum(12)을 굶겨 LLM 선택 다양성을 죽인다(패널 B #1).
- 빌드 배제: 고유명(_cat artist/character/copyright + 영문 prefix + 한국어
  엔티티 group), 괄호 태그, count≤0(알리아스/사어 행 — "clouds" 류). 단
  미디어/아티스트 정보 메타 group(parody/meme/animated/signature)은 엔티티명이
  아니므로 보존 — `_validate_tag`의 현행 통과 동작 유지(개념 후보에서는
  retriever 카테고리 게이트가 거른다).

쿼리는 영어 전용(한국어는 래퍼 `search_llm_tags`가 구 검색으로 위임). 한국어
키워드·설명은 색인하지 않는다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from core.named_entity_groups import is_generic_char_attribute

__all__ = ["LLMSearchIndex", "normalize_query", "stem_token", "query_stems"]


def normalize_query(value: Any) -> str:
    """태그/쿼리 정규화 — core.tag_axis_registry.normalize_tag와 동일 규칙.
    (모든 searcher 호출부의 비교 정규화 `lower().replace("_", " ")`와 일치.
    하이픈은 보존 — 하이픈 브릿지는 파생키/프로브가 담당.)"""
    return " ".join(str(value or "").replace("_", " ").strip().lower().split())


# 부분 레인 스톱워드 — 최소만(패널 A #4). over/under/near/from은 실태그의 의미
# 토큰("bent over" 66k, "from behind" 256k, "under table")이라 제외하면 안 된다.
# 관사/전치사 대부분은 len<3 규칙이 자동으로 거른다(a/an/of/at/on/in/by/to).
_STOPWORDS = frozenset({"the", "and", "with"})

# ing/ed 제거 후 남는 자음 중복 축약 대상("sitting"→sitt→sit, "hugging"→hugg→hug).
# l/r/s 제외 — "falling"→fall(원형 fall과 일치 필요), "earring"→earr(신체 "ear"와
# 별개 패밀리 유지), "kissing"→kiss(kiss와 일치 필요).
_COLLAPSE_DOUBLES = frozenset("bdgmnpt")
_MIN_TOKEN = 3
_TOKEN_SPLIT_RE = re.compile(r"[\s\-]+")


def _collapse_double(w: str) -> str:
    if len(w) >= 3 and w[-1] == w[-2] and w[-1] in _COLLAPSE_DOUBLES:
        return w[:-1]
    return w


def _is_sibilant_es(w: str) -> bool:
    """진성 -es 복수(치찰음 뒤): kisses/boxes/beaches/bushes. roses/poses/vases 류
    (-e+s, 단일 s)는 제외 — s-strip→e-strip 체인이 rose↔roses를 합동시킨다.
    (단일 -ses를 포함시키면 roses→"ros" vs rose→"rose"로 갈라진다.)"""
    if not w.endswith("es") or len(w) < 4:
        return False
    return w.endswith("sses") or w[-3] in "xz" or w[-4:-2] in ("ch", "sh")


def stem_token(word: str) -> str:
    """경량 스테머 — **fixpoint 반복(≤3회)**(패널 A #1).

    단일패스 순차는 -ing 명사 복수형 클래스에서 비합동이었다: earrings→s→"earring"
    에서 멈추는데 earring→ing→"earr"라 같은 단어가 다른 스템이 된다(leggings/
    stockings/paintings 동형 — 신설계는 stem 일치=멤버십이라 recall 버그).
    반복 적용으로 earrings→earring→earr ≡ earring→earr 합동을 보장한다.

    규칙(반복당 첫 매치만): ies→y, ion 제거(어간≥4 — masturbating↔masturbation,
    penetrating↔penetration 합동), 치찰음-es 제거(어간≥3), ed/ing 제거(어간≥3,
    자음 중복 축약), s 제거(len>3, ss 제외), e 제거(**len>4** — "huge"(4)가
    "hug"(3)로 무너져 hug 쿼리에 huge breasts가 합류하던 실측 충돌 차단;
    rose↔roses는 s→e 체인 양쪽 가드로 여전히 합동).
    불변: pen→"pen" ≠ penis→"peni" ≠ pencil/penguin — prefix 오염 구조적 차단.
    """
    w = str(word).lower()
    for _ in range(3):
        if len(w) >= 5 and w.endswith("ies"):
            w = w[:-3] + "y"
            continue
        if len(w) - 3 >= 4 and w.endswith("ion"):
            w = w[:-3]
            continue
        if _is_sibilant_es(w) and len(w) - 2 >= 3:
            w = w[:-2]
            continue
        if w.endswith("ed") and len(w) - 2 >= 3:
            w = _collapse_double(w[:-2])
            continue
        if w.endswith("ing") and len(w) - 3 >= 3:
            w = _collapse_double(w[:-3])
            continue
        if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
            w = w[:-1]
            continue
        if len(w) > 4 and w.endswith("e"):
            w = w[:-1]
            continue
        break
    return w


def _tokens(text: str) -> list[str]:
    """정규화 텍스트의 의미 토큰(len≥3, 스톱워드 제외). 하이픈도 분리(패널 A #2:
    하이픈 태그 1,385개 — v-neck/x-ray — 가 공백 split만으론 도달 불가)."""
    return [
        tok
        for tok in _TOKEN_SPLIT_RE.split(text)
        if len(tok) >= _MIN_TOKEN and tok not in _STOPWORDS
    ]


def query_stems(text: str) -> set[str]:
    """정규화 텍스트의 의미 토큰 스템 집합."""
    return {stem_token(tok) for tok in _tokens(normalize_query(text))}


def _surface_variants(norm: str) -> list[str]:
    """표면형 변형(하이픈/공백 제거 조합) — exact 레인 파생키·프로브 공용."""
    variants = [norm]
    if "-" in norm:
        spaced = " ".join(norm.replace("-", " ").split())
        dehyph = norm.replace("-", "")
        variants.extend(v for v in (spaced, dehyph) if v)
    if " " in norm:
        variants.extend(v.replace(" ", "") for v in list(variants) if " " in v)
    seen: set[str] = set()
    out: list[str] = []
    for v in variants:
        if v and v not in seen:
            seen.add(v)
            out.append(v)
    return out


# 고유명(엔티티명) group 배제 마커. 영문 prefix는 dict 소스(artist/character/
# copyright), 한국어는 KR_tags의 카테고리 경로. ⚠️ retriever의 마커보다 의도적으로
# 좁다 — '미디어'/'아티스트'(정보)는 parody/meme/animated/signature 같은 정당한
# 메타 태그를 품고 있어 빌드 배제하면 _validate_tag 통과 동작이 회귀한다(실측
# 522행 중 엔티티명 ~440행만 배제). 개념 후보의 미디어류 차단은 retriever
# `_PROPER_NOUN_MARKERS`(아티스트/미디어 포함)가 현행대로 수행한다.
_PROPER_EN_PREFIXES = ("artist", "character", "copyright")
_PROPER_KR_MARKERS = ("작가", "캐릭터", "저작권", "작품", "시리즈", "창작자", "버튜버")
_PROPER_CATS = frozenset({"artist", "character", "copyright"})


@dataclass(frozen=True)
class _Rec:
    tag: str          # 정규화 표시형(구 searcher도 정규화 태그를 반환했다)
    count: int
    desc: str
    group: str
    cat: str
    stems: tuple[str, ...]   # 태그명 토큰 스템(중복 제거, 순서 보존)
    tokens: frozenset[str]   # 태그명 리터럴 토큰(서브랭크: 리터럴 > 굴절 변형)
    n_tokens: int            # 의미 토큰 수(잉여 토큰 패널티 기준)


def _rec_count(info: Mapping[str, Any]) -> int:
    try:
        return int(info.get("freq", info.get("count", 0)) or 0)
    except (TypeError, ValueError):
        return 0


def _excluded(norm: str, info: Mapping[str, Any]) -> bool:
    if str(info.get("_cat") or "").strip().lower() in _PROPER_CATS:
        return True
    group = str(info.get("group") or "").strip().lower()
    if group.startswith(_PROPER_EN_PREFIXES):
        return True
    for marker in _PROPER_KR_MARKERS:
        if marker in group:
            # "캐릭터 > 직업/종족/유형/속성/..." generic 인물·생물·속성은 고유명이 아니다
            # — cheerleader/nurse/ninja/futanari/dark elf/twins 등 ~150 태그가 named
            # 캐릭터로 오배제되던 것 차단(감사 2026-06-12). franchise(캐릭터>포켓몬/Fate)는
            # leaf가 화이트리스트 밖이라 그대로 배제.
            if marker == "캐릭터" and is_generic_char_attribute(group, norm):
                continue
            return True
    if "(" in norm and ")" in norm:
        return True
    if _rec_count(info) <= 0:
        return True
    return False


class LLMSearchIndex:
    """LLM 개념→danbooru 태그 검색. row 계약은 구 searcher와 동일:
    {tag, count, desc, group, cat} (group/desc/count는 병합 레코드 원문 — retriever
    음식·고유명 게이트와 1586행 count 정렬이 소비한다). 빌드 후 read-only(스레드 안전).

    `built_from`: 빌드 원천(`context.kr_tags_raw`)의 identity. 데이터 마이그레이션/
    태그 아카이브 교체가 kr_tags_raw를 리셋하면 ensure 래퍼가 identity 불일치로
    재빌드한다(패널 B #4 — 스테일 인덱스 자가 무효화).
    """

    def __init__(self, records: Iterable[_Rec], *, built_from: Any = None):
        self._recs: list[_Rec] = list(records)
        self.built_from = built_from
        # exact 레인: 정규화 키 → rec 인덱스. 실태그(원형) 키가 파생키(despaced/
        # 하이픈 변형)를 항상 이기고, 같은 계급 충돌은 count 높은 쪽이 이긴다.
        exact: dict[str, int] = {}
        derived: dict[str, int] = {}
        for i, rec in enumerate(self._recs):
            prev = exact.get(rec.tag)
            if prev is None or rec.count > self._recs[prev].count:
                exact[rec.tag] = i
            for variant in _surface_variants(rec.tag)[1:]:
                dprev = derived.get(variant)
                if dprev is None or rec.count > self._recs[dprev].count:
                    derived[variant] = i
        for key, i in derived.items():
            if key not in exact:
                exact[key] = i
        self._exact = exact
        # 부분 레인: 토큰 스템 → rec 인덱스 튜플(역색인).
        postings: dict[str, list[int]] = {}
        for i, rec in enumerate(self._recs):
            for st in set(rec.stems):
                postings.setdefault(st, []).append(i)
        self._postings: dict[str, tuple[int, ...]] = {
            st: tuple(ids) for st, ids in postings.items()
        }

    # ------------------------------------------------------------------
    # 빌드
    # ------------------------------------------------------------------

    @classmethod
    def from_raw_tag_records(
        cls,
        records: Mapping[str, Mapping[str, Any]],
        *,
        built_from: Any = None,
    ) -> "LLMSearchIndex":
        """`core.kr_tag_loader.load_kr_tag_records` 병합 레코드에서 빌드.
        (autocomplete `TagSearchIndex.from_raw_tag_records`와 동일 원천 — 태그
        공간이 같아 recall 기준선이 보존된다. 다른 것은 배제와 매칭뿐.)"""
        best: dict[str, Mapping[str, Any]] = {}
        for key, info in (records or {}).items():
            if not isinstance(info, Mapping):
                continue
            norm = normalize_query(str(info.get("_tag", "") or info.get("tag", "") or key))
            if not norm:
                continue
            prev = best.get(norm)
            if prev is None or _rec_count(info) > _rec_count(prev):
                best[norm] = info

        recs: list[_Rec] = []
        for norm, info in best.items():
            if _excluded(norm, info):
                continue
            tokens = _tokens(norm)
            stems: list[str] = []
            for tok in tokens:
                st = stem_token(tok)
                if st not in stems:
                    stems.append(st)
            recs.append(_Rec(
                tag=norm,
                count=_rec_count(info),
                desc=str(info.get("description", "") or info.get("desc", "") or ""),
                group=str(info.get("group", "") or ""),
                cat=str(info.get("_cat", "") or ""),
                stems=tuple(stems),
                tokens=frozenset(tokens),
                n_tokens=len(tokens),
            ))
        return cls(recs, built_from=built_from)

    # ------------------------------------------------------------------
    # 검색
    # ------------------------------------------------------------------

    def search(self, query: str, limit: int = 12) -> list[dict[str, Any]]:
        """searcher 계약: (query, limit) → [{tag, count, desc, group, cat}].

        exact 히트(원형/하이픈·despaced 변형/인접쌍 결합/±s,es)를 최상단에 고정하고
        나머지를 부분 레인(커버리지 랭킹 + cov-1 스템별 라운드로빈)으로 채운다.
        어떤 prefix/substring 매칭도 하지 않는다. 정렬은 limit와 무관해
        results(q,k) == results(q,N)[:k] 프리픽스 안정성이 성립한다.
        """
        try:
            lim = int(limit)
        except (TypeError, ValueError):
            lim = 12
        q = normalize_query(query)
        if not q or lim <= 0:
            return []

        out: list[dict[str, Any]] = []
        seen: set[str] = set()

        for probe in self._exact_probes(q):
            idx = self._exact.get(probe)
            if idx is None:
                continue
            rec = self._recs[idx]
            if rec.tag in seen:
                continue
            seen.add(rec.tag)
            out.append(self._row(rec))
            if len(out) >= lim:
                return out

        q_stems = query_stems(q)
        if q_stems:
            q_tokens = frozenset(_tokens(q))
            candidate_ids: set[int] = set()
            for st in q_stems:
                candidate_ids.update(self._postings.get(st, ()))
            multi: list[tuple[int, int, int, int, str, int]] = []
            single: dict[str, list[tuple[int, int, int, str, int]]] = {}
            for idx in candidate_ids:
                rec = self._recs[idx]
                if rec.tag in seen:
                    continue
                matched_stems = q_stems.intersection(rec.stems)
                matched = len(matched_stems)
                if matched <= 0:
                    continue
                extra = max(0, rec.n_tokens - matched)
                # 리터럴 토큰 우선(Codex R1 F2): 쿼리 토큰과 글자 그대로 일치
                # ("head"⊂head tilt)가 굴절 변형("heads"⊂heads together)보다 위 —
                # 사고 태그(heads together)가 단일 스템 쿼리의 top-12를 점유하지
                # 못하게 한다(리터럴 매칭이 다수라 변형 매칭은 자연 강등).
                literal = len(q_tokens & rec.tokens)
                if matched >= 2:
                    # 커버리지 desc → 잉여 asc → 리터럴 desc → count desc → 태그명
                    multi.append((-matched, extra, -literal, -rec.count, rec.tag, idx))
                else:
                    single.setdefault(next(iter(matched_stems)), []).append(
                        (extra, -literal, -rec.count, rec.tag, idx)
                    )
            multi.sort()
            ordered_ids = [item[5] for item in multi]
            if single:
                # cov-1 티어: 매칭 스템별 버킷 라운드로빈(패널 A #5) — 쿼리 토큰
                # 순서대로 인터리브해 look-패밀리(viewer 3.7M 등) 한 패밀리가
                # limit를 독식하고 phone-패밀리를 축출하는 것을 막는다.
                bucket_order = [
                    stem_token(tok) for tok in _tokens(q)
                ]
                ordered_buckets = []
                seen_buckets: set[str] = set()
                for st in bucket_order + sorted(single):
                    if st in single and st not in seen_buckets:
                        seen_buckets.add(st)
                        ordered_buckets.append(sorted(single[st]))
                pos = [0] * len(ordered_buckets)
                remaining = sum(len(b) for b in ordered_buckets)
                while remaining > 0:
                    for bi, bucket in enumerate(ordered_buckets):
                        if pos[bi] < len(bucket):
                            ordered_ids.append(bucket[pos[bi]][4])
                            pos[bi] += 1
                            remaining -= 1
            for idx in ordered_ids:
                rec = self._recs[idx]
                if rec.tag in seen:
                    continue
                seen.add(rec.tag)
                out.append(self._row(rec))
                if len(out) >= lim:
                    break
        return out

    def stats(self) -> dict[str, int]:
        return {
            "records": len(self._recs),
            "exact_keys": len(self._exact),
            "stems": len(self._postings),
        }

    # ------------------------------------------------------------------

    @staticmethod
    def _exact_probes(q: str) -> list[str]:
        """정확일치 프로브: 원형 → 하이픈/despaced 변형 → 인접 토큰쌍 결합 →
        각 프로브의 ±s/es 변형(패널 A #3 — "thigh high socks"→"thighhigh"+s).
        프로브는 exact_map 조회 전용이라 변형이 실태그가 아니면 그냥 미스다."""
        base = _surface_variants(q)
        if " " in q:
            toks = q.split()
            for a, b in zip(toks, toks[1:]):
                pair = a + b
                if pair not in base:
                    base.append(pair)
        probes = list(base)
        for p in base:
            if len(p) < _MIN_TOKEN:
                continue
            for v in (p + "s", p + "es"):
                probes.append(v)
            if p.endswith("es") and len(p) - 2 >= _MIN_TOKEN:
                probes.append(p[:-2])
            if p.endswith("s") and len(p) - 1 >= _MIN_TOKEN:
                probes.append(p[:-1])
        seen: set[str] = set()
        ordered: list[str] = []
        for p in probes:
            if p and p not in seen:
                seen.add(p)
                ordered.append(p)
        return ordered

    @staticmethod
    def _row(rec: _Rec) -> dict[str, Any]:
        return {
            "tag": rec.tag,
            "count": rec.count,
            "desc": rec.desc,
            "group": rec.group,
            "cat": rec.cat,
        }
