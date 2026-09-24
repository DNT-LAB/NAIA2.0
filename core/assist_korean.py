"""Assist v2 한국어 결정론 층 — Kiwi 형태소 분석 위에서 모델(E2B)이 못 하는 것을 맡는다.

- 비유(명사+같이/처럼/마냥): 그 명사는 장면에 넣지 않는다(개같이 엎드려 -> dog 아님).
- 관용구(비유 대상+동사 -> 태그): 개+엎드리/기 -> all fours. 덮을 태그(on stomach)도 함께 준다.
- 동사 사전: 한 음절·불규칙 줄기(기 -> crawling). 명사형(기기·차기·자기)은 동음이의라 사전 검색에 쓰지 않는다.
- 사전 구: 명사구·목적어+동사를 NAIA 한국어 키워드와 정확히 맞춘다(공주 안기 -> princess carry).
- 이름·방향: 캐릭터 이름(Kiwi 고유명사) + 주어/목적어/에게 + 수동형 -> 누가 누구에게.
- 인원: 사람 명사·수·'들'·묶음 명사·캐릭터 성별·'혼자' -> 이벤트 맵 인원 구획.

왜 모델에 맡기지 않나(실측 2026-09-23, 5090): E2B 는 구조(누가·무엇을·빼고)는 읽지만 '공주안기'를 hold 로,
'개같이'를 dog 로 옮긴다. 사전 힌트를 프롬프트에 넣어도 쓰지 않는다. 인원은 E2B 17/30 vs 이 층 30/30.

규칙은 ``data/assist/korean_rules.json``(긴 꼬리 — 계속 키운다). 설계·함정은 docs/ASSIST_V2_DESIGN_2026_09_23.md.
Kiwi 가 없으면(설치 전) 빈 분석을 돌려주고 모델만으로 돈다 — 기능이 죽지 않는다.
"""

from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

RULES_PATH = Path(__file__).resolve().parents[1] / "data" / "assist" / "korean_rules.json"
NOUN_TAGS = frozenset({"NNG", "NNP", "NNB", "NR", "SL", "SN"})
VERB_PREFIXES = ("VV", "VA")
FUNCTIONAL_PREFIXES = ("VV", "VA", "VX", "EC", "EF", "ETM", "ETN", "JKS", "JKO", "JKB", "JKG", "JX", "JC", "XSV",
                       "XSA", "EP")
ROLE_OF_PARTICLE = {"JKS": "S", "JKO": "O", "JKB": "D", "JKG": "G", "JX": "S", "JC": "C"}
DATIVE_FORMS = frozenset({"에게", "한테", "께", "에게서", "한테서"})
# 이름 뒤에 붙어 나오는 조사(긴 것부터) — Kiwi 가 모르는 성 뒤에서 '카나데가' 처럼 묶어 낼 때 떼어 낸다
GLUED_PARTICLES = (("에게서", "JKB"), ("한테서", "JKB"), ("에게", "JKB"), ("한테", "JKB"), ("께서", "JKS"),
                   ("이랑", "JC"), ("하고", "JC"), ("랑", "JC"), ("와", "JC"), ("과", "JC"), ("께", "JKB"),
                   ("이", "JKS"), ("가", "JKS"), ("은", "JX"), ("는", "JX"), ("을", "JKO"), ("를", "JKO"),
                   ("의", "JKG"), ("도", "JX"))
MAX_KEYWORD_TAGS = 12       # 한 키워드가 이보다 많은 태그를 가리키면 '<자세>' 같은 묶음 이름이다 — 힌트로 쓰지 않는다
CLAUSE_ENDINGS = ("고", "며", "면서", "으며", "으면서")    # 구성: 여기서 절을 자른다(뒤가 보조 용언이면 안 자른다)


def compact(text: Any) -> str:
    return re.sub(r"\s+", "", str(text or "")).lower()


def base_name(tag: str) -> str:
    """태그의 밑이름 — 괄호(변형판·작품)를 뗀다: hatsune miku (append) -> hatsune miku, yuuka (track) (blue archive) -> yuuka."""
    return re.sub(r"\s*\(.*$", "", str(tag or "")).strip() or str(tag or "")


def _one_character_family(rows: list[tuple[str, int, str]]) -> bool:
    """12개 넘는 묶음이 **한 캐릭터와 그 변형판**인가(하츠네미쿠 -> hatsune miku · hatsune miku (append) … 32개).
    1위 캐릭터와 밑이름이 같은 태그가 절반 이상이고 게시물의 80% 이상이면 그렇다.
    실측 09-24(캐릭터가 1위인 묶음 69개): 변형판 묶음 5개(하츠네미쿠·키아나카스라나·라이덴메이·브로냐자이칙·마휘핑)는
    게시물 비중 0.977~1.0, 분류 64개(캐릭터·원신캐릭터·보컬로이드캐릭터 …)는 0.657 이하이고 가족 태그가 1~3개다."""
    best: dict[str, tuple[int, str]] = {}
    for tag, count, cat in rows:
        n = max(0, int(count or 0))
        if tag not in best or n > best[tag][0]:
            best[tag] = (n, cat)
    if not best:
        return False
    top = max(best, key=lambda t: best[t][0])
    if best[top][1] != "character":
        return False
    family = [t for t in best if base_name(t) == base_name(top)]
    total = sum(n for n, _c in best.values())
    return len(family) * 2 >= len(best) and total > 0 and sum(best[t][0] for t in family) >= 0.8 * total


def load_rules(path: Path | None = None) -> dict[str, Any]:
    data = json.loads((path or RULES_PATH).read_text(encoding="utf-8"))
    if data.get("kind") != "assist_korean_rules" or data.get("schema_version") != 1:
        raise ValueError("assist korean rules: unsupported schema")
    return data


# 규칙표를 못 읽으면(배포 누락·손상) 이것으로 돈다 — 비유·관용구·인원 세기는 꺼지고 사전 구·이름·방향만 남는다.
EMPTY_RULES: dict[str, Any] = {
    "schema_version": 1, "kind": "assist_korean_rules", "simile_particles": ["같이", "처럼", "마냥", "듯이"],
    "idioms": [], "verbs": {}, "stem_prefixes": [], "nouns": {}, "people": {"female": [], "male": [], "neutral": []},
    "groups": {}, "numerals": {}, "solo_words": [], "not_names": [], "filler_stems": [], "generic_tags": [],
    "poses": [], "spatial_words": [], "passive_suffixes": ["히", "리", "기", "이"],
    "passive_exceptions": ["하", "있", "보이"],
    "companions": [], "parts": [], "viewer": {}, "keyword_block": [],
}


# ── 사전(한국어 키워드 · 캐릭터 이름) ───────────────────────────────────────


@dataclass
class KoreanVocab:
    """한국어 층이 읽는 자료. 앱에서는 서비스가 만들고, 시험에서는 작은 가짜를 넣는다."""

    keywords: dict[str, list[tuple[str, int, str]]]      # 붙여 쓴 키워드 -> [(태그, 게시물 수, 분류)]
    name_pieces: dict[str, set[str]]                      # 이름 조각·붙여 쓴 전체 이름 -> 캐릭터 태그
    genders: dict[str, str] = field(default_factory=dict)  # 캐릭터 태그 -> girl/boy
    character_rank: Callable[[str], int] = lambda _tag: 0  # 캐릭터 태그 -> 게시물 수(Artist 팩)
    tag_exists: Callable[[str], bool] = lambda _tag: True  # 이벤트 맵 어휘에 있나
    blocked_keys: set[str] = field(default_factory=set)    # 묻지 않을 키워드(규칙표 keyword_block — 쳐다보기)

    def lookup(self, span: str, *, character: bool = False) -> list[tuple[str, int]]:
        """정확 일치 키워드 -> 태그(게시물 많은 순). 묶음 이름(12개 초과)·막은 키워드는 버린다."""
        if compact(span) in self.blocked_keys:
            return []
        rows = [r for r in self.keywords.get(compact(span), []) if (r[2] == "character") == character]
        if len({r[0] for r in rows}) > MAX_KEYWORD_TAGS:
            return []
        seen: set[str] = set()
        out: list[tuple[str, int]] = []
        for tag, count, _cat in sorted(rows, key=lambda r: -r[1]):
            if tag not in seen:
                seen.add(tag)
                out.append((tag, count))
        return out

    def scene_tags(self, span: str) -> list[str]:
        return [t for t, _c in self.lookup(span) if self.tag_exists(t)]

    def name_strength(self, word: str) -> str:
        """이 낱말이 이름으로 쓰이는 정도 — 한국어 키워드에서 **가장 많이 쓰이는 항목**으로 가른다(작가 항목은 뺀다).

        'general'   캐릭터가 아닌 태그가 가장 많다(교복·트윈테일·원신·공주·고양이·사쿠라=벚꽃)
        'character' 캐릭터 태그가 가장 많다(푸리나 10,774 > inner ego 55 · 호두 · 렘 · 루피)
        'piece'     키워드엔 없고 이름 조각에만 있다(카나데 — 키워드는 **작가** kanade 뿐이었다)
        'none'      모른다.
        예전엔 캐릭터 아닌 항목이 **하나라도** 있으면 일반 낱말로 봐서 카나데(작가 이름과 겹침)·푸리나를 놓쳤다(실측 09-23).
        """
        rows = [r for r in self.keywords.get(compact(word), []) if r[2] != "artist"]
        if len({r[0] for r in rows}) > MAX_KEYWORD_TAGS:
            # 묶음 이름 — '캐릭터' 는 1,371명을 가리키는 분류다(실측: 입력칸에서 이름으로 칠해졌다).
            # 단 한 캐릭터의 변형판 묶음은 그 캐릭터 이름이다 — 안 그러면 '하츠네 미쿠' 를 한 이름으로 붙인 순간 놓친다.
            return "character" if _one_character_family(rows) else "general"
        if rows:
            return "character" if max(rows, key=lambda r: r[1])[2] == "character" else "general"
        return "piece" if self.name_pieces.get(compact(word)) else "none"

    def is_general_word(self, word: str) -> bool:
        return self.name_strength(word) == "general"

    def character_candidates(self, name: str, limit: int = 5) -> list[tuple[str, int]]:
        """전체 이름 정확 일치 + 이름 조각 일치를 **합쳐** Artist 팩 게시물 수로 줄 세운다(카나데 -> yoisaki 2,940 …).
        예전엔 정확 일치가 하나라도 있으면 조각을 안 봐서 루피 = rupee (nikke) 뿐이었다(monkey d. luffy 6,828 이 가려짐)."""
        tags = {t for t, _c in self.lookup(name, character=True)} | set(self.name_pieces.get(compact(name), ()))
        ranked = sorted(((t, int(self.character_rank(t) or 0)) for t in tags), key=lambda x: (-x[1], x[0]))
        return ranked[:limit]


def build_vocab(kr_raw: dict[str, Any], *, genders: dict[str, str] | None = None,
                character_rank: Callable[[str], int] | None = None,
                tag_exists: Callable[[str], bool] | None = None) -> KoreanVocab:
    """NAIA 한국어 태그 사전(kr_tags_raw)에서 키워드 색인과 이름 조각을 만든다.

    - 키워드는 괄호(<…> […])를 떼고 붙여 쓴 꼴로 찾는다. '님' 을 뗀 꼴도 넣는다(공주님 안기 = 공주 안기).
    - 캐릭터 이름 조각은 **한 덩어리 이름과 마지막 조각(이름)** 만 넣는다(요이사키 카나데 -> 카나데).
      가운데 조각(성·수식어)은 일반 낱말과 겹쳐 캐릭터를 잘못 부른다(교복·모습 -> 엉뚱한 캐릭터, 실측).
    """
    keywords: dict[str, list[tuple[str, int, str]]] = {}
    pieces: dict[str, set[str]] = {}
    for key, info in (kr_raw or {}).items():
        if not isinstance(info, dict):
            continue
        tag = str(info.get("_tag") or key)
        try:
            count = int(info.get("freq") or info.get("count") or 0)
        except (TypeError, ValueError):
            count = 0
        cat = str(info.get("_named_entity_category") or info.get("_cat") or "")
        for kw in str(info.get("keywords_kr") or "").split(","):
            kw = kw.strip().strip("<>[] ")
            if not kw or not re.search("[가-힣]", kw):
                continue
            keywords.setdefault(compact(kw), []).append((tag, count, cat))
            if "님" in kw:
                keywords.setdefault(compact(kw.replace("님", "")), []).append((tag, count, cat))
            if cat == "character":
                parts = kw.split()
                for piece in {parts[-1], "".join(parts)}:
                    if len(piece) >= 2:
                        pieces.setdefault(piece, set()).add(tag)
    return KoreanVocab(keywords=keywords, name_pieces=pieces, genders=dict(genders or {}),
                       character_rank=character_rank or (lambda _t: 0), tag_exists=tag_exists or (lambda _t: True))


# ── 분석 결과 ────────────────────────────────────────────────────────────────


@dataclass
class NameHit:
    form: str
    candidates: list[tuple[str, int]]
    gender: str | None

    @property
    def tag(self) -> str:
        return self.candidates[0][0] if self.candidates else ""


@dataclass
class PersonCount:
    girls: int = 0
    boys: int = 0
    unknown: int = 0
    solo: bool = False
    partition: str = "unknown"      # 이벤트 맵 인원 구획 이름 | 'unknown'
    confirm: bool = False           # 성별 모르는 사람이 섞였거나 사람이 없다 — 사용자 확인
    notes: list[str] = field(default_factory=list)

    def persons_param(self) -> str:
        """이벤트 맵 persons 인자. 한 사람은 solo 여부를 글로 못 가리므로 둘 다."""
        if self.partition in ("1girl", "1girl_solo"):
            return "1girl_solo,1girl"
        if self.partition in ("1boy", "1boy_solo"):
            return "1boy_solo,1boy"
        return "" if self.partition == "unknown" else self.partition


@dataclass
class KoreanAnalysis:
    tokens: list[tuple[str, str]] = field(default_factory=list)
    stems: list[str] = field(default_factory=list)
    vehicles: set[str] = field(default_factory=set)        # 비유 대상(개·고양이)
    blocked: set[str] = field(default_factory=set)         # 장면에 넣지 않을 태그(dog …)
    covers: set[str] = field(default_factory=set)          # 관용구가 덮는 태그(on stomach)
    idiom_verbs: set[str] = field(default_factory=set)     # 관용구가 가져간 동사 줄기 — 모델 항목이 이것이면 버린다
    specific: list[str] = field(default_factory=list)      # 1순위: 관용구·사전 구·명사 규칙
    viewer: list[str] = field(default_factory=list)        # 그중 1순위 시청자 규칙(나를 째려보는 -> looking at viewer) — 구성은 덧붙인다
    verb_tags: list[str] = field(default_factory=list)     # 동사 사전·줄기 규칙(흔한 것은 뒤로)
    phrases: dict[str, str] = field(default_factory=dict)  # 붙여 쓴 구 -> 태그(모델 항목 교체용)
    verb_phrases: list[str] = field(default_factory=list)  # 그중 동사에서 나온 구의 태그(인물 사이 동작 후보)
    phrase_stems: set[str] = field(default_factory=set)    # 사전 구가 가져간 동사 줄기(안) — 모델의 '안기기' 를 버린다
    names: list[NameHit] = field(default_factory=list)
    explicit_names: set[str] = field(default_factory=set)  # {이름} — 자동 이름 정책과 별개로 사용자가 고정
    roles: tuple[str, str] | None = None                   # (하는 쪽, 당하는 쪽) — 이름 기준
    notes: list[str] = field(default_factory=list)
    available: bool = True                                 # Kiwi 로 분석했나
    tokenizer: Callable[[str], list[tuple[str, str]]] | None = field(default=None, repr=False, compare=False)
    source_text: str = field(default="", repr=False, compare=False)

    def lemmas(self) -> set[str]:
        return {f for f, t in self.tokens if t in NOUN_TAGS or t.startswith(VERB_PREFIXES)} | set(self.stems)

    def grounded(self, ko: str) -> bool:
        """모델의 한국어 조각이 요청의 내용 형태소에 근거하는가.

        완성된 활용형의 문자열 포함 여부 대신 Kiwi 의 명사·동사·형용사·파생 동사 줄기를 비교한다.
        VX(있다·싶다 등)는 후보 안에서 이미 근거가 확인된 어휘 동사·형용사에 붙은 경우만 허용한다.
        ``tokenizer`` 없는 시험/구형 호출은 저장된 형태소로 보수적인 호환 판단을 한다.
        """
        if not ko or not self.available:
            return True
        if self.source_text and compact(ko) in compact(self.source_text):
            return True                    # 원문에 똑같이 적힌 span 은 다른 형태소 분해보다 우선한다
        request_compact = compact("".join(form for form, _tag in self.tokens))
        if self.tokenizer is None:
            request_compact = compact(self.source_text) or request_compact

            def fallback(word: str) -> bool:
                k = compact(word)
                if k in request_compact:
                    return True
                stem = k[:-1] if k.endswith("기") and len(k) >= 2 else re.sub(r"다$", "", k)
                forms = {form for form, tag in self.tokens if tag in NOUN_TAGS or tag.startswith(VERB_PREFIXES)}
                if stem in forms or (len(stem) >= 2 and stem in request_compact):
                    return True
                words = str(word).split()
                return len(words) > 1 and all(fallback(part) for part in words)

            return fallback(ko)

        candidate = self.tokenizer(ko)
        request = self.tokens
        if not candidate:
            return False

        content = lambda tag: tag in NOUN_TAGS or tag.startswith(VERB_PREFIXES) or tag.startswith(("XSV", "XSA"))
        available = {(form, tag[:2]) for form, tag in request if content(tag)}
        available_forms = {form for form, tag in request if content(tag)}
        candidate_content = [(form, tag) for form, tag in candidate if content(tag)]
        if not candidate_content:
            return compact(ko) in request_compact

        matched_lexical_verb = False
        for form, tag in candidate:
            if tag.startswith("VX"):
                # 보조 용언은 앞선 어휘 동사/형용사가 요청과 맞을 때만 추가 문법으로 인정한다.
                if not matched_lexical_verb:
                    return False
                continue
            if not content(tag):
                continue
            matches = (form, tag[:2]) in available or form in available_forms
            # 한 음절 동사 명사형은 Kiwi 가 NNG 로 분석할 수 있다(젖어 떨고 -> 모델 ko '떨기').
            # 실제 요청에 같은 동사 줄기가 있을 때만 어미 '-기'를 떼어 근거로 인정한다.
            if not matches and tag in ("NNG", "NNP") and form.endswith("기"):
                stem = form[:-1]
                matches = any(src == stem and src_tag.startswith(VERB_PREFIXES) for src, src_tag in request)
            if not matches:
                return False
            if tag.startswith(VERB_PREFIXES) or tag.startswith(("XSV", "XSA")):
                matched_lexical_verb = True
        return True


@dataclass
class _Tok:
    """위치가 있는 토큰(clean_text 기준 [start, end)). 여러 토막 이름은 합쳐져 form 에 띄어 쓴 그대로 담긴다."""
    form: str
    tag: str
    start: int
    end: int


# ── 층 ─────────────────────────────────────────────────────────────────────


class KoreanLayer:
    """Kiwi 하나를 쥔다. 사용자 사전(캐릭터 이름·사람 명사)을 넣은 모델은 준비에 수 초 — ``warm()`` 을 먼저 부른다."""

    def __init__(self, vocab: KoreanVocab, rules: dict[str, Any] | None = None,
                 kiwi_factory: Callable[[], Any] | None = None) -> None:
        self.vocab = vocab
        self.error: str | None = None
        self.rules_error: str | None = None
        if rules is None:
            try:
                rules = load_rules()
            except Exception as exc:
                rules, self.rules_error = EMPTY_RULES, f"{type(exc).__name__}: {exc}"
        self.rules = rules
        self._kiwi_factory = kiwi_factory
        self._kiwi: Any = None
        self._lock = threading.Lock()
        self._tok_lock = threading.Lock()   # 분석 줄 세우기(tokenize 주석 참조)
        self._noun_cache: dict[str, bool] = {}
        self.user_words = 0
        r = self.rules
        self._female = set(r["people"]["female"])
        self._male = set(r["people"]["male"])
        self._neutral = set(r["people"]["neutral"])
        self._groups = {k: tuple(v) for k, v in r["groups"].items()}
        self._numerals = dict(r["numerals"])
        self._simile = set(r["simile_particles"])
        self._filler = set(r["filler_stems"])
        self._not_names = set(r["not_names"])
        # 사전 1순위가 일상어 뜻과 어긋나는 키워드 — 사전 구·구성 후보·모델 항목 교체가 모두 이 lookup 을 거친다
        vocab.blocked_keys |= {compact(k) for k in r.get("keyword_block") or ()}

    # -- Kiwi 준비 --------------------------------------------------------
    def ready(self) -> bool:
        return self._kiwi is not None

    def warm(self) -> bool:
        """Kiwi 를 만든다(한 번). 실패하면 이유를 남기고 False — 분석은 빈 결과로 내려간다."""
        if self._kiwi is not None:
            return True
        with self._lock:
            if self._kiwi is not None:
                return True
            try:
                self._kiwi = self._kiwi_factory() if self._kiwi_factory else self._build_kiwi()
                self.error = None
            except Exception as exc:  # 설치 전·모델 손상 — 앱은 산다
                self.error = f"{type(exc).__name__}: {exc}"
                return False
        return True

    def _build_kiwi(self) -> Any:
        from kiwipiepy import Kiwi

        # ⚠️ 사용자 낱말을 넣은 뒤 첫 분석에서 Kiwi 가 모델을 다시 만든다 — '확인 -> 추가' 를 번갈아 하면
        #    낱말마다 재구성이 일어나 몇 시간이 걸린다(실측: 멈춤). 확인은 따로 끝내고 추가는 몰아서 한다.
        checker = Kiwi()

        def unknown_name(word: str) -> bool:
            if not re.fullmatch(r"[가-힣]{2,}", word) or self.vocab.is_general_word(word):
                return False          # 공주·벚꽃 같은 일반 낱말을 고유명사로 넣으면 문장이 부서진다
            toks = checker.tokenize(word)
            if len(toks) == 1 and toks[0].form == word:
                return False          # Kiwi 가 이미 아는 말
            return not all(t.tag.startswith(FUNCTIONAL_PREFIXES) for t in toks)   # 하고 = 하/VV + 고/EC

        # ⚠️ 키워드의 앞 조각(성)은 넣지 않는다 — 성만이 아니라 '메이드가·고용한·검은·같은' 같은 문장 조각이 섞여 있어
        #    고유명사로 넣으면 '메이드가' 가 한 덩어리가 되는 식으로 문장이 부서진다(실측 09-24, 1,700개 중 수백 개).
        #    성 뒤에서 조사가 붙어 나오는 것(카나데가)은 _unglue 가, 성이 쪼개지는 것은 _merge_names 가 맡는다.
        names = [w for w in self.vocab.name_pieces if unknown_name(w)]
        people = [w for w in (self._female | self._male | self._neutral | set(self._groups))
                  if re.fullmatch(r"[가-힣]{2,}", w)]
        kiwi = Kiwi()
        for word in names:
            kiwi.add_user_word(word, "NNP", 0)
        for word in people:
            kiwi.add_user_word(word, "NNG", 0)
        kiwi.tokenize("준비")     # 모델 구성을 여기서 한 번
        self.user_words = len(names) + len(people)
        return kiwi

    def tokenize(self, text: str) -> list[tuple[str, str]]:
        return [(t.form, t.tag) for t in self._tokens(text)]

    def raw_tokens(self, text: str) -> list[tuple[str, str]]:
        """Kiwi 날것(조사 떼기·이름 붙이기 없음) — 사전 키워드 원형 색인용.
        이름 붙이기까지 하면 일반 키워드 5만 개에 52초, 날것은 2.4초였다(실측 09-25)."""
        if not self.warm():
            return []
        with self._tok_lock:
            return [(t.form, t.tag) for t in self._kiwi.tokenize(clean_text(text))]

    def _tokens(self, text: str) -> list["_Tok"]:
        """clean_text 한 글의 토큰(위치 포함). 붙은 조사를 떼고(_unglue) 이름 토막을 붙인다(_merge_names) —
        여러 토막 이름(나토리 사나)이 **토큰 하나**가 되어 방향·인원 세기·칠하기가 한 사람으로 본다."""
        cleaned = clean_text(text)
        if not self.warm():
            return []
        # Kiwi 는 네이티브 확장이고, 여러 파이썬 스레드가 한 인스턴스를 동시에 불러도 된다는 보장이 없다
        # (문서는 num_workers 내부 병렬만 말한다). 라우트는 스레드 풀에서 도니 요청 둘이 겹칠 수 있다 —
        # 네이티브 경합은 백엔드를 통째로 죽인다. 문장당 0.3ms 라 줄 세워도 비용이 없다.
        with self._tok_lock:
            raw = [(t.form, t.tag, t.start, t.start + t.len) for t in self._kiwi.tokenize(cleaned)]
        toks: list[_Tok] = []
        for form, tag, start, end in raw:
            toks.extend(self._unglue(_Tok(form, tag, start, end)))
        return self._merge_names(toks, cleaned)

    def _unglue(self, tok: "_Tok") -> list["_Tok"]:
        """'카나데가'/NNP → 카나데 + 가. Kiwi 가 모르는 성 뒤의 이름을 조사까지 묶어 낸다(실측 09-24:
        오토노세 카나데가 · 하츠네 미쿠가). **통째로는 이름이 아니고, 앞부분이 이름일 때만** 가른다."""
        if tok.tag not in ("NNP", "NNG") or tok.end - tok.start != len(tok.form):
            return [tok]
        if self.vocab.character_candidates(tok.form, limit=1):
            return [tok]
        for particle, ptag in GLUED_PARTICLES:
            stem = tok.form[:-len(particle)]
            if tok.form.endswith(particle) and len(stem) >= 2 and stem not in self._not_names \
                    and self.vocab.character_candidates(stem, limit=1) and not self.vocab.is_general_word(stem):
                cut = tok.start + len(stem)
                return [_Tok(stem, "NNP", tok.start, cut), _Tok(particle, ptag, cut, tok.end)]
        return [tok]

    def _split_last_syllable(self, window: list["_Tok"]) -> bool:
        """창의 끝이 조사인데 사실 이름 끝 글자인가 — Kiwi 가 '사나' 를 사/NNG + 나/JC 로 뗐다(여러 줄 글, 실측 09-24).
        조사 앞 토막이 **제 이름이 아닐 때만**(사) 붙인다 — 시로 + 이(주격) 처럼 앞 토막이 이름이면 조사다(시로이 아님)."""
        last, before = window[-1], window[-2]
        return (last.tag.startswith("J") and len(last.form) == 1
                and before.tag in ("NNP", "NNG") and not self.vocab.character_candidates(before.form, limit=1))

    def _merge_names(self, toks: list["_Tok"], cleaned: str) -> list["_Tok"]:
        """이름 토막을 붙여 전체 이름 하나로(나토리 + 사나 -> '나토리 사나' -> natori sana, 오토노세 + 카나데).
        긴 것부터. ⚠️ 붙인 꼴이 **전체 이름으로 사전에 있을 때만** — 안 그러면 '나토리' 가 따로 칸코레의
        natori 로 잡혀 인물이 셋이 됐다(사용자 제보 09-24). 교복 소녀 같은 이웃 명사는 안 붙는다.
        양 끝만 명사면 가운데는 무엇이든 된다 — Kiwi 가 이름 끝 글자를 조사로 뗀다(키아나 카스라나 -> 키아 + 나/JC + 카스라나,
        실측). 붙인 **글자 그대로**가 전체 이름일 때만이라 '유우카와 유즈' 같은 이웃은 붙지 않는다."""
        out: list[_Tok] = []
        i = 0
        while i < len(toks):
            merged, size = None, 1
            for size in (4, 3, 2):
                window = toks[i:i + size]
                if len(window) < size or window[0].tag not in ("NNP", "NNG"):
                    continue
                if window[-1].tag not in ("NNP", "NNG") and not self._split_last_syllable(window):
                    continue
                surface = cleaned[window[0].start:window[-1].end]
                joined = compact(surface)
                # 일반 낱말로 더 많이 쓰이는 꼴은 안 붙인다 — '고양이 귀' 는 한 캐릭터의 별칭이기도 하지만 cat ears 다(실측)
                if joined in self._not_names or self.vocab.is_general_word(joined) \
                        or not self.vocab.character_candidates(joined, limit=1):
                    continue
                merged = _Tok(surface, "NNP", window[0].start, window[-1].end)
                break
            if merged is not None:
                out.append(merged)
                i += size
            else:
                out.append(toks[i])
                i += 1
        return out

    # -- 분석 -------------------------------------------------------------
    def analyze(self, text: str) -> KoreanAnalysis:
        toks = self.tokenize(text)
        if not toks:
            return KoreanAnalysis(available=False, notes=[f"kiwi 없음: {self.error}"] if self.error else [])
        out = KoreanAnalysis(tokens=toks, stems=_stems(toks))
        out.tokenizer = self.tokenize
        out.source_text = clean_text(text)
        forms = [f for f, _t in toks]
        # 비유: 명사 + 같이/처럼/마냥
        for i, (form, tag) in enumerate(toks):
            if tag in NOUN_TAGS and i + 1 < len(toks) and toks[i + 1][0] in self._simile:
                out.vehicles.add(form)
                out.blocked.update(t for t, _c in self.vocab.lookup(form)[:3])
                out.notes.append(f"비유:{form}{toks[i + 1][0]}")
        stems = set(out.stems)
        for idiom in self.rules["idioms"]:
            hit_v = out.vehicles & set(idiom["vehicles"])
            hit_s = stems & set(idiom["verbs"])
            if hit_v and hit_s:
                for tag in idiom["tags"]:
                    if tag not in out.specific and self.vocab.tag_exists(tag):
                        out.specific.append(tag)
                out.covers.update(idiom["covers"])
                out.idiom_verbs.update(hit_s)
                out.notes.append(f"관용구:{'/'.join(sorted(hit_v))}+{'/'.join(sorted(hit_s))}->{idiom['tags']}")
        for noun, tags in self.rules["nouns"].items():
            if noun in forms:
                for tag in tags:
                    if tag not in out.specific and self.vocab.tag_exists(tag):
                        out.specific.append(tag)
        # 몸 부위 + 묶는 동사(손목이 … 묶여 -> bound wrists) — 사용자 요청 09-24 에서 tied up · tying 만 나왔다
        for rule in self.rules.get("parts") or ():
            hit = _part_hit(toks, rule)
            if hit:
                for tag in rule.get("tags") or ():
                    if tag not in out.specific and self.vocab.tag_exists(tag):
                        out.specific.append(tag)
                out.covers.update(rule.get("covers") or ())
                out.notes.append(f"부위:{hit}->{rule.get('tags')}")
        # 나를·저에게 + 보는 동사 -> looking at viewer — 1인칭은 그림을 보는 사람이다(나를 째려보는)
        for tag in _viewer_tags(toks, self.rules.get("viewer") or {}):
            if tag not in out.specific and self.vocab.tag_exists(tag):
                out.specific.append(tag)
                out.viewer.append(tag)
                out.notes.append(f"시청자:{tag}")
        consumed: set[str] = set()          # 사전 구가 가져간 동사 줄기 — 동사 사전으로 한 번 더 넣지 않는다
        spans = _phrase_spans(toks, self._filler, self.rules["passive_suffixes"], self.rules["passive_exceptions"])
        # 제 꼴(수동 꼴) 그대로 사전에 있는 동사는 능동 꼴을 묻지 않는다 — 묶여 -> 묶이기(tied up) 인데 묶기(tying)가
        # 따라 들어왔다(사용자 요청 09-24). 실측: 두 꼴이 다 키워드인 쌍 15개 모두 제 꼴이 맞다(먹이기 feeding / 먹기 eating
        # food · 흔들리기 swinging / 흔들기 shaking). 제 꼴의 태그가 규칙에 덮여도(bound wrists) 능동 꼴로 새지 않는다.
        span_rows = [(span, kind, stem, self.vocab.scene_tags(span)) for span, kind, stem in spans]
        own_hit = {stem for _span, kind, stem, tags in span_rows
                   if kind in ("verb", "verb_object", "verb_arg") and tags}
        for span, kind, stem, tags in span_rows:
            if stem and stem in out.idiom_verbs:
                continue                    # 관용구가 가져간 동사(개같이 엎드리기 -> all fours, on stomach 아님)
            if kind == "active" and stem in own_hit:
                continue
            if kind == "verb_arg":
                continue                    # 논항이 있는 절의 맨 동사는 모호하므로 모델 근거로만 남긴다
            if kind == "active" and self._lexical_noun(span.split()[-1]):
                continue                    # 능동 꼴이 따로 있는 명사다 — 눈물 고인 -> 고이 -> 고기 = meat(사용자 제보 09-24)
            if not tags or tags[0] in out.blocked or tags[0] in out.covers:
                continue                    # 1순위가 막혔으면 2순위(face in pillow)로 새지 않는다
            if compact(span) not in out.phrases:
                out.phrases[compact(span)] = tags[0]
                if kind != "noun":
                    consumed.add(stem)
                    if tags[0] not in out.verb_phrases:
                        out.verb_phrases.append(tags[0])
        out.phrase_stems = consumed
        for tag in out.phrases.values():
            if tag not in out.specific:
                out.specific.append(tag)
        for stem in out.stems:
            for prefix, tag in self.rules["stem_prefixes"]:
                if stem.startswith(prefix) and tag not in out.verb_tags and self.vocab.tag_exists(tag):
                    out.verb_tags.append(tag)
            if stem in consumed:
                continue
            tag = self.rules["verbs"].get(stem)
            if tag and tag not in out.covers and tag not in out.verb_tags and tag not in out.specific \
                    and self.vocab.tag_exists(tag):
                out.verb_tags.append(tag)
                out.notes.append(f"동사:{stem}->{tag}")
        out.names = self._names(toks)
        # {호두} 처럼 감싼 것은 일반 낱말이어도 이름으로 찾는다 — 인물 칸 차례는 글에 나온 차례
        for form, _start, _end in braced_names(text):
            out.explicit_names.add(form)
            if all(h.form != form for h in out.names):
                hit = self.name_hit(form, explicit=True)
                if hit and hit.candidates:
                    out.names.append(hit)
                    out.notes.append(f"이름(중괄호):{form}")
        cleaned = clean_text(text)
        out.names.sort(key=lambda h: (cleaned.find(h.form) if h.form in cleaned else len(cleaned)))
        out.roles = self._roles(toks, {n.form for n in out.names})
        return out

    def _lexical_noun(self, word: str) -> bool:
        """Kiwi 가 낱말을 통째로 명사 하나로 읽나(고기 · 모기 · 감기 · 열기) — 동사 명사형(안기 = 안/VV + 기/ETN)이 아니다.
        수동형(고이·모이)에서 이/히/리/기 를 떼어 만든 능동 꼴이 이런 명사와 겹친다."""
        if word not in self._noun_cache:
            with self._tok_lock:
                toks = self._kiwi.tokenize(word) if self._kiwi is not None else []
            self._noun_cache[word] = (len(toks) == 1 and toks[0].tag in ("NNG", "NNP")
                                      and toks[0].form == word)
        return self._noun_cache[word]

    def _names(self, toks: list[tuple[str, str]]) -> list[NameHit]:
        """Kiwi 가 고유명사로 본 것 중 캐릭터 이름. 일반 낱말(트윈테일)·작품명(원신)은 뺀다 — 별칭 조각과 겹친다(실측).
        일반 낱말이기도 한 이름(호두)은 모델이 인물로 적었을 때만 받는다(``name_hit``)."""
        hits: list[NameHit] = []
        for i, (form, tag) in enumerate(toks):
            if not self._auto_name_like(toks, i) or any(h.form == form for h in hits):
                continue
            cands = self.vocab.character_candidates(form)
            if cands:
                hits.append(NameHit(form, cands, self.vocab.genders.get(cands[0][0])))
        return hits

    def _name_like(self, form: str, tag: str) -> bool:
        """이 낱말을 이름으로 볼까. 고유명사(NNP)면 캐릭터·이름 조각, 일반 명사(NNG)면 캐릭터가 가장 많이 쓰일 때만
        (Kiwi 는 같은 이름을 문맥 따라 NNP·NNG 로 붙인다 — 푸리나의 = NNG, 원신 푸리나 = NNP, 실측)."""
        if form in self._not_names:
            return False
        if len(compact(form)) < 2:
            return False
        strength = self.vocab.name_strength(form)
        return (tag == "NNP" and strength in ("character", "piece")) or (tag == "NNG" and strength == "character")

    def _auto_name_like(self, toks: list[tuple[str, str]], index: int) -> bool:
        form, tag = toks[index]
        return self._name_like(form, tag) and self._name_context_allowed(toks, index)

    def _name_context_allowed(self, toks: list[tuple[str, str]], index: int) -> bool:
        form, tag = toks[index]
        # 공간 관계 명사 + 처소격 조사는 문장 성분으로 읽는다(책상 위에 놓인 … -> 위 이름 오검출).
        # 같은 어휘의 중괄호 표기는 name_hit(explicit=True) 경로에서 보존한다.
        if form in set(self.rules.get("spatial_words") or ()) and tag != "NNP":
            prev = toks[index - 1] if index else ("", "")
            nxt = toks[index + 1] if index + 1 < len(toks) else ("", "")
            if nxt[1] == "JKB" or prev[1] in NOUN_TAGS:
                return False
        # 사람 역할 낱말은 조사가 붙어 장면 속 보통명사로 쓰일 때 후보에서 뺀다.
        # 단독 검색 '선생'은 실제 캐릭터 키워드일 수 있어 일반 이름처럼 허용한다.
        if tag == "NNG" and form in self._female | self._male | self._neutral:
            # 역할/사람 일반명사는 단독 검색일 때만 동음 캐릭터 이름으로 허용한다.
            # 조사 인접 여부만 검사하면 "웃는 선생", "선생 모습" 같은 장면 문맥이 새어 나간다.
            if len(toks) != 1 or index != 0:
                return False
        return True

    def roles_for(self, analysis: KoreanAnalysis, names: Iterable[str]) -> tuple[str, str] | None:
        """최종 인물 목록(모델이 적은 이름 포함)으로 방향을 다시 잰다 — Kiwi 가 이름으로 안 본 인물도 들어온다."""
        return self._roles(analysis.tokens, {clean_text(n).strip() for n in names if n})

    # -- 구성(여러 줄 요청): 절 가르기 -----------------------------------------
    def clauses(self, text: str) -> list[str]:
        """설명 한 줄을 시각 요소 하나씩의 절로 — 쉼표·마침표 + 연결 어미(-고·-며·-면서) + '채로' + 장소 '에서'.

        ⚠️ 연결 어미 뒤가 보조 용언이면 자르지 않는다('보고 있음' 은 한 동작이다). Kiwi 가 없으면 구두점으로만.
        """
        out: list[str] = []
        for piece in re.split(r"[,.·;\n]+", clean_text(text)):
            piece = piece.strip()
            if not piece:
                continue
            toks = self._tokens(piece) if self.warm() else []
            cut = 0
            for i, tok in enumerate(toks):
                nxt = toks[i + 1] if i + 1 < len(toks) else None
                ending = tok.tag == "EC" and tok.form in CLAUSE_ENDINGS and nxt is not None \
                    and not nxt.tag.startswith("VX")
                while_state = tok.tag == "JKB" and tok.form == "로" and i > 0 and toks[i - 1].form == "채"
                # 장소 조사 '에서' 뒤(무대 위에서 | 노래하는) — 장소와 동작은 다른 요소다. '에' 는 자르지 않는다(머리 위에 올림)
                place = tok.tag == "JKB" and tok.form == "에서" and nxt is not None and not nxt.tag.startswith("VX")
                if (ending or while_state or place) and piece[cut:tok.end].strip():
                    out.append(piece[cut:tok.end].strip())
                    cut = tok.end
            if piece[cut:].strip():
                out.append(piece[cut:].strip())
        return out

    def is_relation_clause(self, clause: str, names: Iterable[str]) -> bool:
        """인물 사이의 절인가 — 이름이 둘 이상이거나, 이름 뒤가 을/를·의·와·에게(목적·소유·접속·여격).
        그런 절(나토리 사나를 공주안기 한 채로 · 카나데에게 안긴채로)은 방향과 동작을 한국어 층이 맡는다.
        '하츠네 미쿠가 무대에서 노래하는' 처럼 이름이 주어일 뿐이면 인물 사이가 아니다."""
        packed = {compact(n) for n in names if n}
        if not packed or not self.warm():
            return False
        toks = self._tokens(clause)
        hits = 0
        for i, tok in enumerate(toks):
            if compact(tok.form) not in packed:
                continue
            hits += 1
            nxt = toks[i + 1] if i + 1 < len(toks) else None
            if nxt is not None and (nxt.tag in ("JKO", "JKG", "JC")
                                    or (nxt.tag == "JKB" and nxt.form in DATIVE_FORMS)):
                return True
        return hits >= 2

    def name_hit(self, form: str, *, explicit: bool = False,
                 analysis: KoreanAnalysis | None = None) -> NameHit | None:
        form = clean_text(form).strip()
        if not form or form in self._not_names:
            return None
        if not explicit and len(compact(form)) < 2:
            return None
        if not explicit and analysis is not None:
            token_forms = analysis.tokens
            occurrences = [i for i, (surface, _tag) in enumerate(token_forms) if compact(surface) == compact(form)]
            if occurrences and not any(self._name_context_allowed(token_forms, i) for i in occurrences):
                return None
        cands = self.vocab.character_candidates(form)
        return NameHit(form, cands, self.vocab.genders.get(cands[0][0])) if cands else None

    # -- 이름 고르기(사용자) ---------------------------------------------------
    PICK_LIMIT = 8

    def candidate_list(self, form: str) -> list[dict[str, Any]]:
        """이름 하나의 후보(게시물 많은 순) — 화면의 고르기 목록."""
        return [{"tag": t, "posts": n, "gender": self.vocab.genders.get(t)}
                for t, n in self.vocab.character_candidates(clean_text(form).strip(), limit=self.PICK_LIMIT)]

    def choose(self, hit: NameHit | None, choices: dict[str, str] | None) -> NameHit | None:
        """사용자가 목록에서 고른 캐릭터를 맨 앞으로 — 게시물 수 순위보다 사용자의 선택(모델에 묻지 않는다).
        목록에 없는 태그는 무시한다(낡은 선택·조작)."""
        if hit is None or not choices or hit.form not in choices:
            return hit
        want = choices[hit.form]
        cands = list(hit.candidates)
        if want not in [t for t, _n in cands]:
            cands = self.vocab.character_candidates(hit.form, limit=self.PICK_LIMIT)
            if want not in [t for t, _n in cands]:
                posts = int(self.vocab.character_rank(want) or 0)
                if posts <= 0:
                    return hit                # 게시물이 없는 태그 = 있는 캐릭터가 아니다
                cands = [(want, posts)] + cands   # 목록 밖에서 찾아 고른 캐릭터(원피스 루피)
        picked = [c for c in cands if c[0] == want] + [c for c in cands if c[0] != want]
        return NameHit(hit.form, picked, self.vocab.genders.get(want))

    def name_spans(self, text: str, *, use_kiwi: bool = True) -> dict[str, Any]:
        """입력하는 동안 칠할 이름(모델 없이). 위치는 **원문** 기준(중괄호 포함).

        - Kiwi 고유명사 중 캐릭터 이름 — ``_names`` 와 같은 규칙(일반 낱말·작품명 제외). ``use_kiwi=False`` 거나
          Kiwi 가 아직 없으면 건너뛴다(입력마다 수 초짜리 준비를 기다리지 않는다).
        - {…} 로 감싼 것은 일반 낱말이어도 이름으로 찾는다 — Kiwi 없이도 된다. 못 찾으면 found=False(점선).
        반환: {names: [{form, found, source, tag, candidates[]}], spans: [{start, end, form}]}
        """
        raw = str(text or "")
        names: dict[str, dict[str, Any]] = {}
        spans: list[dict[str, Any]] = []
        taken: list[tuple[int, int]] = []

        def add(form: str, start: int, end: int, source: str) -> None:
            if form not in names:
                cands = self.candidate_list(form)
                names[form] = {"form": form, "found": bool(cands), "source": source,
                               "tag": cands[0]["tag"] if cands else "", "candidates": cands}
            spans.append({"start": start, "end": end, "form": form})
            taken.append((start, end))

        for form, start, end in braced_names(raw):
            if form not in self._not_names:
                add(form, start, end, "brace")
        if use_kiwi and self._kiwi is not None:
            _cleaned, index = _clean_with_index(raw)
            tokens = self._tokens(raw)
            token_forms = [(tok.form, tok.tag) for tok in tokens]
            for i, tok in enumerate(tokens):           # 붙은 조사를 떼고 이름 토막을 붙인 토큰(나토리 사나 = 하나)
                form = tok.form
                if not self._auto_name_like(token_forms, i):
                    continue
                if tok.end > len(index) or tok.end <= tok.start:
                    continue
                start, end = index[tok.start], index[tok.end - 1] + 1
                if raw[start:end] != form:            # 위치가 어긋나면(드문 글자) 그 자리 근처에서 다시 찾는다
                    found = raw.find(form, max(0, start - 2))
                    if found < 0:
                        continue
                    start, end = found, found + len(form)
                if any(a <= start < b for a, b in taken):
                    continue                          # 중괄호로 이미 잡은 자리
                if self.vocab.character_candidates(form, limit=1):
                    add(form, start, end, "auto")
        spans.sort(key=lambda s: s["start"])
        order = list(dict.fromkeys(s["form"] for s in spans))
        return {"names": [names[f] for f in order], "spans": spans}

    def _roles(self, toks: list[tuple[str, str]], names: set[str]) -> tuple[str, str] | None:
        """이름 사이의 방향. 주어(이/가/은/는) -> 목적어(을/를)·소유(의)·에게. 수동형(안겨서·꼬집히는)이면 뒤집는다."""
        subj = obj = dat = gen = None
        passive = False
        suffixes = tuple(self.rules["passive_suffixes"])
        exceptions = set(self.rules["passive_exceptions"])
        for i, (form, tag) in enumerate(toks):
            if tag in NOUN_TAGS and form in names:
                nxt = toks[i + 1] if i + 1 < len(toks) else ("", "")
                role = ROLE_OF_PARTICLE.get(nxt[1], "")
                if role == "D" and nxt[0] not in DATIVE_FORMS:
                    role = ""
                if role in ("S", "C") and subj is None:
                    subj = form
                elif role == "O":
                    obj = form
                elif role == "D":
                    dat = form
                elif role == "G":
                    gen = form
            elif tag.startswith(VERB_PREFIXES) and subj and dat and len(form) > 1 \
                    and form.endswith(suffixes) and form not in exceptions:
                passive = True
        if passive:
            return (dat, subj)
        target = obj or gen or dat
        return (subj, target) if subj and target and subj != target else None

    # -- 인원 -------------------------------------------------------------
    def count_persons(self, analysis: KoreanAnalysis, extra_names: Iterable[str] = (),
                      choices: dict[str, str] | None = None, not_names: Iterable[str] = ()) -> PersonCount:
        """요청에 나온 사람을 센다. 성별 모르는 사람(사람·친구)이 있거나 아무도 없으면 confirm.
        ``choices`` = 사용자가 목록에서 고른 캐릭터(이름 -> 태그) — 그 캐릭터의 성별로 센다.
        ``not_names`` = 사용자가 '이름 아님' 으로 고른 낱말(호두를 먹는) — 사람으로 세지 않는다."""
        choices = choices or {}
        rejected = set(not_names)
        pc = PersonCount()
        toks = analysis.tokens
        if not toks:
            pc.confirm = True
            return pc
        extra = {clean_text(n).strip() for n in extra_names if n}
        phrase_nouns: set[str] = set()
        for span in analysis.phrases:          # '공주 안기' 의 공주는 사람이 아니다
            for form, tag in toks:
                if tag in NOUN_TAGS and form in span and span != compact(form):
                    phrase_nouns.add(form)
        pc.solo = any(f in self.rules["solo_words"] for f, _t in toks)
        seen: set[str] = set()
        last_group = -9
        for i, (form, tag) in enumerate(toks):
            if tag not in NOUN_TAGS or form in seen or form in phrase_nouns:
                continue
            nxt = toks[i + 1] if i + 1 < len(toks) else ("", "")
            if nxt[0] in self._simile:
                continue
            if form in self._groups:
                if i - last_group == 1:        # 쌍둥이 자매 = 한 묶음
                    last_group = i
                    continue
                gg, bb = self._groups[form]
                pc.girls, pc.boys = pc.girls + gg, pc.boys + bb
                seen.add(form)
                last_group = i
                pc.notes.append(f"{form}={gg}g{bb}b")
                continue
            gender = None
            if form in self._female:
                gender = "girl"
            elif form in self._male:
                gender = "boy"
            elif form in self._neutral:
                explicit = form in choices or (form in analysis.explicit_names
                                               and any(h.form == form and h.candidates for h in analysis.names))
                if explicit or (self.vocab.name_strength(form) == "character"
                                and self._name_context_allowed(toks, i)):
                    hit = self.choose(self.name_hit(form, explicit=explicit, analysis=analysis), choices)
                    gender = (hit.gender if hit else None) or "unknown"
                else:
                    gender = "unknown"
            elif form not in rejected and form not in self._not_names and (
                    form in choices or form in analysis.explicit_names
                    or (form in extra and self._name_context_allowed(toks, i))
                    or self._auto_name_like(toks, i)):
                # 트윈테일(일반 낱말이자 별칭 조각)은 모델이 인물로 적지 않는 한 사람으로 세지 않는다
                explicit = form in analysis.explicit_names or form in choices
                if len(compact(form)) < 2 and not explicit:
                    continue
                hit = self.choose(self.name_hit(form, explicit=explicit, analysis=analysis), choices)
                gender = (hit.gender if hit else None) or ("unknown" if form in extra else None)
            if gender is None:
                continue
            seen.add(form)
            n = self._count_near(toks, i) or 1
            if gender == "girl":
                pc.girls += n
            elif gender == "boy":
                pc.boys += n
            else:
                pc.unknown += n
            pc.notes.append(f"{form}x{n}:{gender}")
        total = pc.girls + pc.boys + pc.unknown
        pc.partition = partition_of(pc.girls, pc.boys, pc.solo or total == 1)
        pc.confirm = bool(pc.unknown) or pc.partition == "unknown"
        return pc

    def _count_near(self, toks: list[tuple[str, str]], i: int) -> int | None:
        """앞쪽(두 소녀·세 명의 소녀·2명의 소녀) 또는 뒤쪽(소녀 둘·소녀 두 명·소녀들) 수."""
        for back in range(1, 4):
            if i - back < 0:
                break
            form, tag = toks[i - back]
            if form in self._numerals:
                return self._numerals[form]
            if tag == "SN" and form.isdigit():
                return int(form)
            if form not in ("명", "의", "사람") and tag not in ("NNB", "JKG"):
                break
        if i + 1 < len(toks):
            form, tag = toks[i + 1]
            if form in self._numerals:
                return self._numerals[form]
            if tag == "SN" and form.isdigit():
                return int(form)
            if form == "들" and tag.startswith("XSN"):
                return 3
        return None


def clean_text(text: Any) -> str:
    """사용자가 이름을 {카나데} 처럼 감싸도 같게 읽는다."""
    return re.sub(r"[{}]", "", str(text or ""))


_BRACED = re.compile(r"\{([^{}]{1,40})\}")


def braced_names(text: Any) -> list[tuple[str, int, int]]:
    """사용자가 {호두} 처럼 감싼 것 = '이건 이름이다'. (이름, 원문 시작, 원문 끝) — 괄호 안쪽 위치."""
    out: list[tuple[str, int, int]] = []
    for m in _BRACED.finditer(str(text or "")):
        inner = m.group(1)
        name = inner.strip()
        if name:
            start = m.start(1) + (len(inner) - len(inner.lstrip()))
            out.append((name, start, start + len(name)))
    return out


def _clean_with_index(text: str) -> tuple[str, list[int]]:
    """``clean_text`` 와 같은 글 + 그 글의 각 글자가 원문 몇 번째였는지(입력칸에 칠할 위치를 되돌린다)."""
    chars: list[str] = []
    index: list[int] = []
    for i, ch in enumerate(text):
        if ch not in "{}":
            chars.append(ch)
            index.append(i)
    return "".join(chars), index


def partition_of(girls: int, boys: int, solo: bool) -> str:
    """(여성 수, 남성 수) -> 이벤트 맵 인원 구획 13칸 중 하나. 아무도 없으면 'unknown'."""
    if girls == 0 and boys == 0:
        return "unknown"
    if girls >= 2 and boys >= 2:
        return "multiple_girls_multiple_boys"
    if girls == 1 and boys >= 2:
        return "1girl_multiple_boys"
    if boys == 1 and girls >= 2:
        return "1boy_multiple_girls"
    if girls == 1 and boys == 1:
        return "1girl_1boy"
    if girls == 2 and boys == 0:
        return "2girls"
    if boys == 2 and girls == 0:
        return "2boys"
    if girls >= 3:
        return "multiple_girls"
    if boys >= 3:
        return "multiple_boys"
    if girls == 1:
        return "1girl_solo" if solo else "1girl"
    return "1boy_solo" if solo else "1boy"


def _verb_word(toks: list[tuple[str, str]], j: int) -> str | None:
    """j 번째가 동사면 그 줄기(명사+하 는 붙여서: 응시/NNG + 하/XSV -> 응시하). 아니면 None."""
    form, tag = toks[j]
    if tag == "XSV" and j > 0 and toks[j - 1][1] == "NNG":
        return toks[j - 1][0] + form
    return form if tag.startswith(VERB_PREFIXES) else None


def _negated(toks: list[tuple[str, str]], j: int) -> bool:
    """j 번째 동사가 부정인가 — 안/못 + 동사 · 동사 + 지(+도) + 않/못하/말(나를 보지 않고)."""
    start = j - 1 if toks[j][1] == "XSV" else j
    if start > 0 and toks[start - 1][1] == "MAG" and toks[start - 1][0] in ("안", "못"):
        return True
    after = [f for f, _t in toks[j + 1:j + 4]]
    return after[:1] == ["지"] and any(f in ("않", "못하", "말") for f in after[1:])


def _part_hit(toks: list[tuple[str, str]], rule: dict[str, Any]) -> str | None:
    """규칙표 parts — 몸 부위가 **주어·목적어**(이/가·은/는·을/를, 또는 조사 없이 바로 동사)이고 같은 절에서 묶는
    동사가 오면 '부위+동사'. ⚠️ '손으로 끈을 묶는' 의 손(으로)은 묶는 쪽이고 '손목에 리본을 묶은' 은 장식이다 —
    부위 뒤 조사를 본다. 다음 절(-고·-며)로는 넘어가지 않는다(손을 들고 리본을 묶는)."""
    nouns, verbs = set(rule.get("nouns") or ()), set(rule.get("verbs") or ())
    for i, (form, tag) in enumerate(toks):
        if tag not in ("NNG", "NNP") or form not in nouns or i + 1 >= len(toks):
            continue
        nxt = toks[i + 1][1]
        if nxt in ("JKS", "JX", "JKO"):
            start = i + 2
        elif nxt.startswith(VERB_PREFIXES):
            start = i + 1                   # 조사 없이(손목 묶인 채로)
        else:
            continue
        for j in range(start, min(len(toks), i + 9)):
            if toks[j][1] == "EC" and toks[j][0] in CLAUSE_ENDINGS:
                break
            word = _verb_word(toks, j)
            if word is not None and word in verbs and not _negated(toks, j):
                return f"{form}+{word}"
    return None


def _viewer_tags(toks: list[tuple[str, str]], viewer: dict[str, Any]) -> list[str]:
    """규칙표 viewer — 1인칭(나·저)이 **를·에게** 로 받고 같은 절의 첫 동사가 보는·가리키는·뻗는 것이면 그 태그.
    '나는 창밖을 보는' 의 나는 장면 속 인물(주어)이라 보는 사람이 아니다. '향하'(나를 향해)는 지나간다.
    부정(나를 보지 않고 · 안 보는)은 태그를 내지 않는다."""
    pronouns = set(viewer.get("pronouns") or ())
    through = set(viewer.get("through") or ())
    out: list[str] = []
    for i, (form, tag) in enumerate(toks):
        if tag != "NP" or form not in pronouns:
            continue
        nxt = toks[i + 1] if i + 1 < len(toks) else ("", "")
        if not (nxt[1] == "JKO" or (nxt[1] == "JKB" and nxt[0] in DATIVE_FORMS)):
            continue
        for j in range(i + 2, min(len(toks), i + 8)):
            if toks[j][1] == "EC" and toks[j][0] in CLAUSE_ENDINGS:
                break
            word = _verb_word(toks, j)
            if word is None or word in through:
                continue
            if not _negated(toks, j):
                for rule in viewer.get("rules") or ():
                    if word in (rule.get("verbs") or ()):
                        out.extend(t for t in rule.get("tags") or () if t not in out)
            break
    return out


def _stems(toks: list[tuple[str, str]]) -> list[str]:
    """동사 줄기. 명사+하다(관찰/NNG + 하/XSV)와 의성어+거리/대도 붙인다."""
    out: list[str] = []
    i = 0
    while i < len(toks):
        form, tag = toks[i]
        if tag == "IC":
            j, word = i, ""
            while j < len(toks) and toks[j][1] == "IC":
                word += toks[j][0]
                j += 1
            if j < len(toks) and toks[j][1] in ("XSV", "VV") and toks[j][0] in ("거리", "대", "이"):
                out.append(word + toks[j][0])
                i = j + 1
                continue
        if tag == "XSV" and i > 0 and toks[i - 1][1] in NOUN_TAGS:
            out.append(toks[i - 1][0] + form)
        if tag.startswith(VERB_PREFIXES):
            out.append(form)
        i += 1
    return out


def _phrase_spans(toks: list[tuple[str, str]], filler: set[str], passive_suffixes: list[str],
                  passive_exceptions: list[str]) -> list[tuple[str, str, str]]:
    """사전에 물어볼 구 (구, 'noun'|'verb'|'active', 동사 줄기). 명사 두세 개 묶음(띄어 쓴 꼴) · 목적어(+조사 없는 명사)+동사
    명사형 · 두 음절 넘는 동사 명사형 · 수동형의 능동 명사형('active': 안겨서 -> 안기 -> carrying).

    ⚠️ 명사 하나·한 음절 동사 명사형은 묻지 않는다 — 비·눈·폰·기기(기계)·차기(발차기)·자기(도자기) 동음이의.
    """
    spans: list[tuple[str, str, str]] = []
    seq: list[tuple[str, str, str]] = []      # (종류, 꼴, 역할)
    i = 0
    suffixes = tuple(passive_suffixes)
    exceptions = set(passive_exceptions)
    while i < len(toks):
        form, tag = toks[i]
        if tag in NOUN_TAGS:
            j, run = i, []
            while j < len(toks) and toks[j][1] in NOUN_TAGS:
                run.append(toks[j][0])
                j += 1
            for a in range(len(run)):
                for b in range(a + 2, min(len(run), a + 3) + 1):
                    spans.append((" ".join(run[a:b]), "noun", ""))
            nxt = toks[j][1] if j < len(toks) else ""
            phrase = " ".join(run)
            if nxt == "JKB" and j < len(toks):
                phrase += " " + toks[j][0]       # 소파 에 기대기 -> '소파에기대기' 키워드도 묻는다
            seq.append(("N", phrase, ROLE_OF_PARTICLE.get(nxt, "")))
            i = j
            continue
        if tag == "XSV" and i > 0 and toks[i - 1][1] in NOUN_TAGS:
            # 관찰하는 = 관찰/NNG + 하/XSV. Kiwi 가 단일 동사 줄기로 내지 않으므로 구 사전도 못 물었다.
            word = toks[i - 1][0] + form
            obj = seq[-2][1] if len(seq) > 1 and seq[-1][0] == "N" and seq[-2][0] == "N" \
                and seq[-2][2] in ("O", "D", "") else None
            if obj:
                spans.append((f"{obj} {word}기", "verb_object", word))
            # 맨 동사를 안 묻는 것은 목적어(을/를 · 조사 없음)가 있을 때만 — 장소(에서·에)는 뜻을 바꾸지 않는다
            spans.append((f"{word}기", "verb_arg" if obj and seq[-2][2] in ("O", "") else "verb", word))
            seq.append(("V", word, ""))
            i += 1
            continue
        if tag.startswith(VERB_PREFIXES) and form not in filler:
            obj = seq[-1][1] if seq and seq[-1][0] == "N" and seq[-1][2] in ("O", "D", "") else None
            # 목적격 논항과 리 어간은 능동 타동사(흘리다)일 가능성이 높다.
            # 반면 히 수동형(볼을 꼬집히다)은 몸 부위 목적격을 동반할 수 있어 이 가드 대상이 아니다.
            object_role = seq[-1][2] if seq and seq[-1][0] == "N" else ""
            passive = len(form) > 1 and form.endswith(suffixes) and form not in exceptions \
                and not (object_role == "O" and form.endswith("리"))
            stems = [form, form[:-1]] if passive else [form]      # 수동 -> 능동(꼬집히 -> 꼬집)
            for stem in stems:
                kind = "verb" if stem == form else "active"
                if obj:
                    spans.append((f"{obj} {stem}기", "verb_object" if kind == "verb" else kind, form))
                if len(stem) >= 2 or (passive and stem != form):
                    # 목적어(을/를 · 조사 없음)가 붙은 맨 동사만 안 묻는다(손을 흔들며 -> 흔들기 = shaking).
                    # 장소(길에서 뒤돌아보는 · D)는 뜻을 바꾸지 않는다 — 뒤돌아보기(looking back)를 잃었다(재생 09-24).
                    bare_kind = "verb" if passive and kind == "verb" else \
                        ("verb_arg" if obj and object_role in ("O", "") and kind == "verb" else kind)
                    spans.append((f"{stem}기", bare_kind, form))  # 수동형의 능동 명사형은 한 음절이어도(안기)
            seq.append(("V", form, ""))
        i += 1
    # 긴 구부터(머리 쓰다듬기 > 쓰다듬기) — 모델 항목 교체에서 긴 것이 이긴다
    return sorted(dict.fromkeys(spans), key=lambda s: (-len(compact(s[0])), s[0], s[2]))
