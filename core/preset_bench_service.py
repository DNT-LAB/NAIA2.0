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
_SUBJECTS = ("girl", "boy", "other")


def _order(row):
    return min(row["rank"].values()), -max(row["score"].values()), row["id"]


def is_adult(support_by_rating):
    total = sum(support_by_rating.values())
    return bool(total) and support_by_rating.get("e", 0) / total >= ADULT_EXPLICIT_SHARE


def load_cooccur(path, pack_sha256):
    """세트 id -> 덧붙일 몸 태그. 파일이 없거나 · 틀리거나 · 다른 팩으로 구운 것이면 빈 사전(기능만 꺼진다)."""
    try:
        data = json.loads(Path(path).read_bytes())
    except (OSError, ValueError):
        _LOG.info("Preset co-occurrence table unavailable")
        return {}
    if data.get("schema") != COOCCUR_SCHEMA or data.get("build", {}).get("event_presets_sha256") != pack_sha256:
        _LOG.warning("Preset co-occurrence table does not match the event pack - ignored")
        return {}
    return {set_id: [str(tag) for tag in tags] for set_id, tags in (data.get("sets") or {}).items()}


def is_apart(row):
    """따로 뺀 대분류(남남)에 갈 세트인가 - 통째로 빼는 풀이거나 yaoi 내용."""
    spec = SEPARATE.get(row["kind"])
    return bool(spec) and (row["pool"] in spec[1] or row["seed"] in YAOI_TAGS or not YAOI_TAGS.isdisjoint(row["tags"]))


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


def name_subject(text, find_by_tag):
    """캐릭터 칸 글 -> 인원 태그의 성별(girl · boy · other) · 근거.

    1) 글에 직접 쓴 1girl / 1boy 태그 - 사용자가 정한 것이 이긴다(성전환 등)
       (캐릭터 즉시 생성과 같은 판정 - cowboy shot 은 boy 가 아니다)
    2) 쉼표로 나눈 태그 가운데 캐릭터 사전에 있는 이름의 `gender`(rem (re:zero) -> girl)
    3) 모르면 빈 값 - 화면은 girl 로 본다(캐릭터 뷰어의 옛 기본값).
    """
    from core.character_instant_service import detect_subject

    detected = detect_subject(text)
    if detected:
        return {"gender": detected[1:], "source": "tags", "name": ""}
    for tag in (part.strip() for part in str(text or "").split(",")):
        hit = find_by_tag(tag) if tag else None
        gender = str((hit[1] or {}).get("gender") or "").strip().lower() if hit else ""
        if gender in _SUBJECTS:
            return {"gender": gender, "source": "character", "name": tag}
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
            cooccur = {}
            for pack_kind in ("outfit", "event", "expression", "scene"):
                raw = (self.data_dir / f"{pack_kind}_presets.json").read_bytes()
                pack = json.loads(raw)
                if pack_kind == "outfit":
                    self._outfit_digest = hashlib.sha256(raw).hexdigest()
                    self._outfit_slots = pack["tag_slot"]
                if pack_kind == "event":
                    cooccur = load_cooccur(self.data_dir / COOCCUR_NAME, hashlib.sha256(raw).hexdigest())
                for row in pack["sets"]:
                    kind = "outfit" if pack_kind == "outfit" else row["family"]
                    pool, seed = row["pool"], row["seed"]
                    summary = {field: row[field] for field in _FIELDS}
                    head = head_for(kind, pool)
                    summary.update(kind=kind, key=preset_thumb_key(kind, head, row["tags"]),
                                   add=cooccur.get(row["id"], []), adult=is_adult(row["support_by_rating"]))
                    if kind == "outfit":
                        summary["states"] = states.get(row["id"], {})
                    by_id[row["id"]] = summary
                    seeds[kind, pool][seed].append(summary)
            for seed_rows in seeds.values():
                for rows in seed_rows.values():
                    rows.sort(key=_order)
            for kind in {kind for kind, _ in seeds}:
                merged, apart, seen = defaultdict(list), defaultdict(list), set()
                pools = sorted((pool for k, pool in seeds if k == kind), key=lambda pool: _POOL_PRIORITY.get(pool, 9))
                for pool in pools:
                    for seed, rows in seeds[kind, pool].items():
                        for row in rows:
                            mark = (is_apart(row), seed, tuple(sorted(row["tags"])))
                            if mark not in seen:
                                seen.add(mark)
                                (apart if mark[0] else merged)[seed].append(row)
                seeds[kind, ALL_POOLS] = merged
                if kind in SEPARATE:
                    seeds[kind, APART_POOL] = apart
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
        if pool == ALL_POOLS and kind in SEPARATE:
            label, apart = SEPARATE[kind][0], APART_POOL
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
        matches = []
        translations = translations or {}
        for row in self._by_id.values():
            if kind is not None and kind != row["kind"]:
                continue
            for tag in (row["seed"], *row["tags"]):
                record = _translation(translations, tag)
                if (query in tag.casefold()
                        or query in str(record.get("description") or record.get("desc") or "").casefold()
                        or query in str(record.get("keywords_kr") or "").casefold()):
                    matches.append({"kind": row["kind"], "pool": APART_POOL if is_apart(row) else row["pool"],
                                    "seed": row["seed"],
                                    "set_id": row["id"], "matched": tag,
                                    "ko": korean_tag_name(_translation(translations, row["seed"]))})
                    break
            if len(matches) == 200:
                break
        return matches

    def related(self, tag, pool, context):
        if pool not in POOLS:
            raise ValueError("Unknown outfit pool")
        result = self.semantics.related(tag, pool=pool, context=context)
        if result is None:
            raise KeyError(tag)
        index, _ = self._thumbs()
        for group in result["groups"]:
            group["sets"] = [dict(row, has_thumb=row["key"] in index) for row in group["sets"]]
        return result

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
