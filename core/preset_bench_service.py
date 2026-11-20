"""Lazy catalog and thumbnail lookups for the preset bench."""
from __future__ import annotations

import base64
from collections import defaultdict
import hashlib
import json
import logging
from pathlib import Path
import re
import threading

from core.outfit_tag_semantics import OutfitTagSemantics, POOLS
from core.preset_thumb_key import head_for, preset_thumb_key
from core.preset_thumbs import (
    KINDS, PRESET_THUMBS_INDEX_NAME, installed_signature, mark_corrupt, open_preset_thumbs, preset_thumbs_path,
)
from core.style_variants import is_webp


ROOT = Path(__file__).resolve().parents[1]
_LOG = logging.getLogger(__name__)
_FIELDS = ("id", "pool", "seed", "tags", "rank", "score", "layers", "support_by_rating", "side")
BROWSE_TAXONOMY_NAME = "preset_browse_taxonomy.json"
# 세트 id -> 거의 늘 함께 나오는 몸 태그(tools/build_preset_cooccur.py 가 굽는다 - 벤치가 메인에 싣는다).
COOCCUR_NAME = "preset_cooccur.json"
COOCCUR_SCHEMA = "naia.preset_cooccur.v1"
# 의상 세트 id -> [이름 붙은 옷차림 태그, 비율](tools/build_preset_outfit_concepts.py 가 굽는다 - 검색 '교복' 이
# school uniform · serafuku 비율이 높은 세트를 찾는다. 사용자 11-20).
CONCEPTS_NAME = "preset_outfit_concepts.json"
CONCEPTS_SCHEMA = "naia.preset_outfit_concepts.v1"
# 검색 결과 차례 - 이름이 맞음 > 이름 붙은 옷차림 > 설명 · 키워드에만 나옴(사용자 11-20 '교복' 맨 위에 속바지).
SEARCH_LIMIT = 200
# 성인 세트 = 근거 게시물의 절반 이상이 explicit - 벤치가 메인에 nsfw 를 붙인다(사용자 11-20).
ADULT_EXPLICIT_SHARE = 0.5
# 표에 아직 없는 시드(팩을 다시 구운 뒤 표를 안 고쳤을 때)가 숨지 않게 맨 끝에 모아 보인다.
UNSORTED_LABEL = "분류 전"
# 풀 "" = 그 갈래의 모든 풀을 한 목록으로(벤치에서 인원 선택을 없앴다 - 사용자 11-20).
# 같은 시드 · 같은 태그 세트는 앞 풀 것 하나만 남긴다. 차례 = 여성(연결은 girl_boy) 먼저.
ALL_POOLS = ""
_POOL_PRIORITY = {"female": 0, "male": 1, "girl_boy": 0, "girl_girl": 1, "boy_boy": 2}
# 모든 풀 목록에 섞지 않고 맨 끝 별도 대분류로 빼는 세트(사용자 11-20 - 남남은 싫어하는 사람이 많다).
# 갈래 -> (대분류 이름, 통째로 빼는 풀). yaoi 내용 세트(태그 · 시드에 YAOI_TAGS)도 어느 풀이든 함께 뺀다
# (빌더의 장르 거르개를 빠져나온 'implied yaoi' - 2인 자세 · 1인 이벤트 남성 풀에 있다).
# 뺀 세트는 가상 풀 APART_POOL 에 모인다. 그 대분류의 소분류 = 탐색 분류표의 대분류 이름.
# 화면은 대분류의 `pool` 로 세트를 받고, 검색 결과도 뺀 세트는 pool = APART_POOL 로 보인다.
SEPARATE = {"link": ("남남", ("boy_boy",)), "event": ("남남", ())}
YAOI_TAGS = frozenset({"yaoi", "implied yaoi", "bara"})
APART_POOL = "apart"
# 후타나리 세트도 같은 갈래에서 따로 - '남남' 다음 맨 끝 대분류(사용자 11-20). 남남이 먼저 가져간다.
# 판정 = 태그(futanari · futa with female · futa on male …) 또는 공출현 표의 futanari 목록(85% 이상).
FUTA_POOL = "futa"
FUTA_LABEL = "후타나리"
_FUTA_TAG = re.compile(r"\bfuta(nari)?\b")
# 따로 뺀 대분류 차례(목록 맨 끝에 이 차례로) - (가상 풀, 이름).
APART_GROUPS = ((APART_POOL, SEPARATE["link"][0]), (FUTA_POOL, FUTA_LABEL))
_SUBJECTS = ("girl", "boy", "other")


def _order(row):
    return min(row["rank"].values()), -max(row["score"].values()), row["id"]


def is_adult(support_by_rating):
    total = sum(support_by_rating.values())
    return bool(total) and support_by_rating.get("e", 0) / total >= ADULT_EXPLICIT_SHARE


def load_cooccur(path, pack_sha256):
    """(세트 id -> 덧붙일 몸 태그, 후타나리 세트 id 모음). 파일이 없거나 · 틀리거나 · 다른 팩으로 구운 것이면
    빈 값(기능만 꺼진다 - 후타나리는 태그 판정만 남는다)."""
    try:
        data = json.loads(Path(path).read_bytes())
    except (OSError, ValueError):
        _LOG.info("Preset co-occurrence table unavailable")
        return {}, frozenset()
    if data.get("schema") != COOCCUR_SCHEMA or data.get("build", {}).get("event_presets_sha256") != pack_sha256:
        _LOG.warning("Preset co-occurrence table does not match the event pack - ignored")
        return {}, frozenset()
    adds = {set_id: [str(tag) for tag in tags] for set_id, tags in (data.get("sets") or {}).items()}
    return adds, frozenset(str(set_id) for set_id in data.get("futanari") or ())


def load_concepts(path, pack_sha256):
    """의상 세트 id -> [(옷차림 태그, 비율)] (비율 높은 차례). 없거나 · 틀리거나 · 다른 팩으로 구운 것이면 빈 값."""
    try:
        data = json.loads(Path(path).read_bytes())
    except (OSError, ValueError):
        _LOG.info("Preset outfit concept table unavailable")
        return {}
    if data.get("schema") != CONCEPTS_SCHEMA or data.get("build", {}).get("outfit_presets_sha256") != pack_sha256:
        _LOG.warning("Preset outfit concept table does not match the outfit pack - ignored")
        return {}
    return {str(set_id): [(str(tag), float(share)) for tag, share in rows] for set_id, rows in (data.get("sets") or {}).items()}


def is_futa(row, futa_ids=frozenset()):
    return row["id"] in futa_ids or any(_FUTA_TAG.search(tag) for tag in (row["seed"], *row["tags"]))


def is_apart(row):
    """따로 뺀 대분류(남남)에 갈 세트인가 - 통째로 빼는 풀이거나 yaoi 내용."""
    spec = SEPARATE.get(row["kind"])
    return bool(spec) and (row["pool"] in spec[1] or row["seed"] in YAOI_TAGS or not YAOI_TAGS.isdisjoint(row["tags"]))


def apart_pool(row):
    """따로 뺀 대분류의 가상 풀 - 남남(APART_POOL) · 후타나리(FUTA_POOL) · 아니면 ""."""
    if row["kind"] not in SEPARATE:
        return ""
    if is_apart(row):
        return APART_POOL
    return FUTA_POOL if row.get("futa") else ""


_HANGUL = re.compile("[가-힣]")
_PRIMARY_NAME = re.compile(r"<primary>\s*:\s*(.+)$")


def _translation(translations, tag):
    return (translations or {}).get(tag.casefold().replace("\\(", "(").replace("\\)", ")"), {})


def korean_tag_name(record):
    """태그 사전 항목 -> 목록에 보일 한글 이름. 없으면 "" (화면은 영문 태그를 그대로 보인다).

    keywords_kr 의 차례: <primary>:이름 > [이름] > 첫 한글 키워드 > <라벨>(흔히 윗분류지만 가끔 그 태그 이름).
    벤치 목록 2,036개 중 2,030개가 이름을 얻는다(11-20 실측 - 빠지는 것은 이모티콘 · 사전에 없는 태그).
    """
    items = [x.strip() for x in str((record or {}).get("keywords_kr") or "").split(",") if x.strip()]
    for item in items:
        match = _PRIMARY_NAME.match(item)
        if match and _HANGUL.search(match.group(1)):
            return match.group(1).strip()
    for item in items:
        if item.startswith("[") and item.endswith("]") and _HANGUL.search(item):
            return item.strip("[]").strip()
    for item in items:
        if not item.startswith(("<", "[")) and ":" not in item and _HANGUL.search(item):
            return item
    for item in items:
        if item.startswith("<") and item.endswith(">") and _HANGUL.search(item):
            return item.strip("<>").strip()
    return ""


def _names(record):
    """사전 항목의 이름 · 별칭(keywords_kr 의 <primary>:이름 · [이름] · 맨 키워드) - <라벨>(윗분류)은 이름이 아니다."""
    out = []
    for item in (x.strip() for x in str((record or {}).get("keywords_kr") or "").split(",")):
        match = _PRIMARY_NAME.match(item)
        if match:
            out.append(match.group(1).strip())
        elif item.startswith("[") and item.endswith("]"):
            out.append(item.strip("[]").strip())
        elif item and not item.startswith("<") and ":" not in item:
            out.append(item)
    return [name.casefold() for name in out if name]


def _name_hit(query, tag, record):
    return query in tag.casefold() or any(query in name for name in _names(record))


def _text_hit(query, record):
    record = record or {}
    return (query in str(record.get("description") or record.get("desc") or "").casefold()
            or query in str(record.get("keywords_kr") or "").casefold())


def _distinct_tags(row, siblings):
    """형제 세트 가운데 이 세트에만 있는 태그 - 화면의 siblingTags(presetBenchModel.mjs)와 같은 규칙."""
    sets = [other for other in siblings if isinstance(other.get("tags"), (list, tuple))]
    if len(sets) < 2:
        return []
    count = defaultdict(int)
    for other in sets:
        for tag in set(other["tags"]):
            count[tag] += 1
    return [tag for tag in row["tags"] if count[tag] == 1]


def name_subject(text, find_by_tag):
    """캐릭터 칸 글 -> 인원 태그의 성별(girl · boy · other) · 근거.

    1) 글에 직접 쓴 1girl / 1boy 태그 - 사용자가 정한 것이 이긴다(성전환 등)
       (캐릭터 즉시 생성과 같은 판정 - cowboy shot 은 boy 가 아니다)
    2) 쉼표로 나눈 태그 가운데 캐릭터 사전에 있는 이름의 `gender`(rem (re:zero) -> girl)
    3) 모르면 빈 값 - 화면은 girl 로 본다(캐릭터 뷰어의 옛 기본값).
    """
    from core.character_instant_service import detect_subject

    detected = detect_subject(text)
    known = ""
    for tag in (part.strip() for part in str(text or "").split(",")):
        hit = find_by_tag(tag) if tag else None
        gender = str((hit[1] or {}).get("gender") or "").strip().lower() if hit else ""
        if gender in _SUBJECTS:
            if not detected:
                return {"gender": gender, "source": "character", "name": tag}
            known = tag
            break
    if detected:
        # 성별은 쓴 태그가 이기되, 이름 있는 캐릭터인지(name)는 따로 알린다 - 의상 뒤 alternate costume(Codex 리뷰 11-20).
        return {"gender": detected[1:], "source": "tags", "name": known}
    return {"gender": "", "source": "", "name": ""}


class PresetBenchService:
    def __init__(self, runtime_paths, *, data_dir=ROOT / "data", thumbs_path=None):
        self.data_dir = Path(data_dir)
        self.thumbs_path = Path(thumbs_path) if thumbs_path is not None else preset_thumbs_path(runtime_paths)
        self.semantics = OutfitTagSemantics(self.data_dir / "outfit_presets.json",
                                            self.data_dir / "outfit_tag_index.json",
                                            pack_source=self._outfit_pack)
        self._load_lock = threading.Lock()
        self._by_id = None
        self.thumbs_lock = threading.RLock()
        self._signature = object()
        self._index = {}

    def _load(self):
        with self._load_lock:
            if self._by_id is not None:
                return
            states = json.loads((self.data_dir / "outfit_states.json").read_bytes())["by_set"]
            by_id = {}
            seeds = defaultdict(lambda: defaultdict(list))
            cooccur, futa_ids = {}, frozenset()
            for pack_kind in ("outfit", "event", "expression", "scene"):
                raw = (self.data_dir / f"{pack_kind}_presets.json").read_bytes()
                pack = json.loads(raw)
                if pack_kind == "outfit":
                    self._outfit_digest = hashlib.sha256(raw).hexdigest()
                    self._outfit_slots = pack["tag_slot"]
                    self._concepts = load_concepts(self.data_dir / CONCEPTS_NAME, self._outfit_digest)
                if pack_kind == "event":
                    cooccur, futa_ids = load_cooccur(self.data_dir / COOCCUR_NAME, hashlib.sha256(raw).hexdigest())
                for row in pack["sets"]:
                    kind = "outfit" if pack_kind == "outfit" else row["family"]
                    pool, seed = row["pool"], row["seed"]
                    summary = {field: row[field] for field in _FIELDS}
                    head = head_for(kind, pool)
                    summary.update(kind=kind, key=preset_thumb_key(kind, head, row["tags"]),
                                   add=cooccur.get(row["id"], []), adult=is_adult(row["support_by_rating"]),
                                   futa=is_futa(row, futa_ids))
                    if kind == "outfit":
                        summary["states"] = states.get(row["id"], {})
                    by_id[row["id"]] = summary
                    seeds[kind, pool][seed].append(summary)
            for seed_rows in seeds.values():
                for rows in seed_rows.values():
                    rows.sort(key=_order)
            for kind in {kind for kind, _ in seeds}:
                lists = {ALL_POOLS: defaultdict(list), **{key: defaultdict(list) for key, _ in APART_GROUPS}}
                seen = set()
                pools = sorted((pool for k, pool in seeds if k == kind), key=lambda pool: _POOL_PRIORITY.get(pool, 9))
                for pool in pools:
                    for seed, rows in seeds[kind, pool].items():
                        for row in rows:
                            mark = (apart_pool(row), seed, tuple(sorted(row["tags"])))
                            if mark not in seen:
                                seen.add(mark)
                                lists[mark[0]][seed].append(row)
                seeds[kind, ALL_POOLS] = lists[ALL_POOLS]
                if kind in SEPARATE:
                    for key, _ in APART_GROUPS:
                        seeds[kind, key] = lists[key]
            # 탐색 분류(대분류 > 소분류 > 시드 · 게시물 수)는 빌더 칸(tag_slot)과 별개인 손으로 고른 표다.
            # 갈래 다섯 모두 표가 있어야 한다(11-20 v3 + 의상).
            browse = json.loads((self.data_dir / BROWSE_TAXONOMY_NAME).read_bytes())
            if browse.get("schema") != "naia.preset_browse_taxonomy.v1" or set(KINDS) - set(browse["families"]):
                raise ValueError("Unknown preset browse taxonomy schema")
            self._browse = browse["families"]
            self._seeds = seeds
            self._by_id = by_id

    def _outfit_pack(self):
        self._load()
        rows = (row for row in self._by_id.values() if row["kind"] == "outfit")
        return {"sets": rows, "tag_slot": self._outfit_slots}, self._outfit_digest

    def _thumbs(self):
        with self.thumbs_lock:
            path = self.thumbs_path
            signature = installed_signature(path)
            if signature != self._signature:
                self._signature = signature
                self._index = {}
                if signature is None:
                    _LOG.info("Preset thumbnail pack unavailable")
                else:
                    try:
                        _, self._index = open_preset_thumbs(path, cache_path=path.parent / PRESET_THUMBS_INDEX_NAME)
                    except OSError:
                        self._signature = None  # Transient access failures retry on the next request.
                        _LOG.info("Preset thumbnail pack temporarily unavailable")
                    except (ValueError, KeyError, TypeError) as exc:
                        mark_corrupt(path, signature)
                        _LOG.warning("Invalid preset thumbnail pack: %s", ascii(str(exc)))
            return self._index, signature

    def _pool(self, kind, pool):
        if kind not in KINDS:
            raise ValueError("Unknown preset kind")
        self._load()
        if (kind, pool) not in self._seeds:
            raise ValueError("Unknown pool for preset kind")
        return self._seeds[kind, pool]

    def catalog(self, kind, pool, translations=None):
        """대분류 > 소분류 > 시드(게시물 수 차례). 그 풀에 세트가 없는 시드 · 빈 소분류 · 빈 대분류는 뺀다.

        `ko` = 목록에 보일 한글 이름(사용자 지시 11-20 - 목록은 한글만, 영문은 툴팁). 프롬프트에 싣는 것은 늘 `seed`.
        """
        seeds = self._pool(kind, pool)
        index, _ = self._thumbs()

        def entry(seed, posts, source=seeds):
            rows = source[seed]
            return {"seed": seed, "sets": len(rows), "with_thumb": sum(row["key"] in index for row in rows),
                    "posts": posts, "ko": korean_tag_name(_translation(translations, seed))}

        groups, placed = [], set()
        for category in self._browse[kind]:
            subs = []
            for sub in category["subcategories"]:
                items = [entry(tag, posts) for tag, posts in sub["tags"] if tag in seeds]
                placed.update(item["seed"] for item in items)
                if items:
                    subs.append({"name": sub["name"], "seeds": items})
            if subs:
                groups.append({"slot": category["category"], "label": category["category"], "subs": subs,
                               "seeds": [item for sub in subs for item in sub["seeds"]]})
        rest = sorted(set(seeds) - placed, key=lambda seed: _order(seeds[seed][0]))
        if rest:
            items = [entry(seed, None) for seed in rest]
            groups.append({"slot": UNSORTED_LABEL, "label": UNSORTED_LABEL,
                           "subs": [{"name": UNSORTED_LABEL, "seeds": items}], "seeds": items})
        for apart, label in (APART_GROUPS if pool == ALL_POOLS and kind in SEPARATE else ()):
            source = self._seeds[kind, apart]
            subs, placed = [], set()
            for category in self._browse[kind]:
                tags = sorted(((tag, posts) for sub in category["subcategories"] for tag, posts in sub["tags"]
                               if tag in source), key=lambda item: -(item[1] or 0))
                items = [entry(tag, posts, source) for tag, posts in tags if tag not in placed]
                placed.update(item["seed"] for item in items)
                if items:
                    subs.append({"name": category["category"], "seeds": items})
            rest = sorted(set(source) - placed, key=lambda seed: _order(source[seed][0]))
            if rest:
                subs.append({"name": UNSORTED_LABEL, "seeds": [entry(seed, None, source) for seed in rest]})
            if subs:
                groups.append({"slot": label, "label": label, "pool": apart, "subs": subs,
                               "seeds": [item for sub in subs for item in sub["seeds"]]})
        return {"kind": kind, "pool": pool, "groups": groups}

    def sets(self, kind, pool, seed):
        rows = self._pool(kind, pool).get(seed, ())
        index, _ = self._thumbs()
        return {"kind": kind, "pool": pool, "seed": seed,
                "sets": [dict(row, has_thumb=row["key"] in index) for row in rows]}

    def set_info(self, set_id):
        self._load()
        return self._by_id[set_id]

    def search(self, q, kind=None, translations=None):
        if kind is not None and kind not in KINDS:
            raise ValueError("Unknown preset kind")
        query = q.strip().casefold()
        if not query:
            return []
        self._load()
        translations = translations or {}
        concept_ok = {}

        def concept_hit(tag):
            if tag not in concept_ok:
                record = _translation(translations, tag)
                concept_ok[tag] = _name_hit(query, tag, record) or _text_hit(query, record)
            return concept_ok[tag]

        # 세트마다 (차례, 점수, 맞은 태그): 0 = 시드의 영문이나 한글 이름 · 별칭이 맞음(똑같으면 점수 2),
        # 1 = 이름 붙은 옷차림(교복 -> school uniform · serafuku)이 이 세트에서 차지하는 비율, 또는 곁 태그의 이름이
        #     맞음(점수 0.5 - '교복 재킷' blazer 를 곁들인 세트가 세라복 세트를 밀어내지 않게),
        # 2 = 설명 · 키워드에만 나옴(속바지 '여학생 교복에서 흔히 보임').
        found = []
        for row in self._by_id.values():
            if kind is not None and kind != row["kind"]:
                continue
            tags = (row["seed"], *row["tags"])
            seed_record = _translation(translations, row["seed"])
            hit = None
            if _name_hit(query, row["seed"], seed_record):
                exact = query in (row["seed"].casefold(), *_names(seed_record))
                hit = (0, 2.0 if exact else 1.0, row["seed"])
            if hit is None:
                concept = next(((share, tag) for tag, share in self._concepts.get(row["id"], ()) if concept_hit(tag)), None)
                other = next(((0.5, tag) for tag in row["tags"] if _name_hit(query, tag, _translation(translations, tag))), None)
                best = max(filter(None, (concept, other)), default=None, key=lambda item: item[0])
                hit = (1, *best) if best else None
            if hit is None:
                hit = next(((2, 0.0, tag) for tag in tags if _text_hit(query, _translation(translations, tag))), None)
            if hit is not None:
                found.append((row, *hit))
        # 화면은 시드로 묶는다 - 묶음의 차례 = 가장 좋은 세트의 (차례, 점수) · 그다음 맞은 세트 수.
        best, count = {}, defaultdict(int)
        for row, tier, score, _ in found:
            key = row["seed"]
            count[key] += 1
            best[key] = min(best.get(key, (9, 0.0)), (tier, -score))
        found.sort(key=lambda item: (*best[item[0]["seed"]], -count[item[0]["seed"]], item[0]["seed"], item[1], -item[2]))
        return [{"kind": row["kind"], "pool": apart_pool(row) or row["pool"], "seed": row["seed"],
                 "set_id": row["id"], "matched": tag, "ko": korean_tag_name(_translation(translations, row["seed"]))}
                for row, _, _, tag in found[:SEARCH_LIMIT]]

    def related(self, tag, pool, context):
        if pool not in POOLS:
            raise ValueError("Unknown outfit pool")
        result = self.semantics.related(tag, pool=pool, context=context)
        if result is None:
            raise KeyError(tag)
        index, _ = self._thumbs()
        self._load()
        siblings = self._seeds.get(("outfit", pool), {})
        for group in result["groups"]:
            group["sets"] = [self._related_row(row, index, siblings) for row in group["sets"]]
        return result

    def _related_row(self, row, index, siblings):
        """관련 의상 한 장 = 관련 행 그대로(rank · score 형식 유지) + 일반 목록의 생성 요약(add · adult)
        + 일반 목록(같은 풀 · 같은 시드)과 같은 형제 기준 distinct(Codex 리뷰 11-20)."""
        base = self._by_id.get(row.get("id"))
        if base is None:
            return dict(row, has_thumb=row["key"] in index)
        return dict(row, add=base["add"], adult=base["adult"], has_thumb=row["key"] in index,
                    distinct=_distinct_tags(base, siblings.get(base["seed"], ())))

    def thumbnail(self, key, if_none_match):
        with self.thumbs_lock:
            index, signature = self._thumbs()
            if key not in index:
                raise KeyError(key)
            etag = f'"{signature[0][:16]}-{key}"'
            if etag == if_none_match:
                return etag, None
            try:
                # Preserve the distinction between a temporary range read
                # failure and invalid bytes. __getitem__ folds both into KeyError.
                data = base64.b64decode(index._read(key), validate=True)
                if not is_webp(data):
                    raise ValueError("Invalid WebP")
            except (KeyError, OSError):
                self._signature = None
                raise KeyError(key) from None
            except ValueError as exc:
                self._index = {}
                mark_corrupt(self.thumbs_path, signature)
                _LOG.warning("Invalid preset thumbnail: %s", ascii(str(exc)))
                raise KeyError(key) from exc
            return etag, data
