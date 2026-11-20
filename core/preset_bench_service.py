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
# 표에 아직 없는 시드(팩을 다시 구운 뒤 표를 안 고쳤을 때)가 숨지 않게 맨 끝에 모아 보인다.
UNSORTED_LABEL = "분류 전"
# 풀 "" = 그 갈래의 모든 풀을 한 목록으로(벤치에서 인원 선택을 없앴다 - 사용자 11-20).
# 같은 시드 · 같은 태그 세트는 앞 풀 것 하나만 남긴다. 차례 = 여성(연결은 girl_boy) 먼저.
ALL_POOLS = ""
_POOL_PRIORITY = {"female": 0, "male": 1, "girl_boy": 0, "girl_girl": 1, "boy_boy": 2}
_SUBJECTS = ("girl", "boy", "other")


def _order(row):
    return min(row["rank"].values()), -max(row["score"].values()), row["id"]


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
            for pack_kind in ("outfit", "event", "expression", "scene"):
                raw = (self.data_dir / f"{pack_kind}_presets.json").read_bytes()
                pack = json.loads(raw)
                if pack_kind == "outfit":
                    self._outfit_digest = hashlib.sha256(raw).hexdigest()
                    self._outfit_slots = pack["tag_slot"]
                for row in pack["sets"]:
                    kind = "outfit" if pack_kind == "outfit" else row["family"]
                    pool, seed = row["pool"], row["seed"]
                    summary = {field: row[field] for field in _FIELDS}
                    head = head_for(kind, pool)
                    summary.update(kind=kind, key=preset_thumb_key(kind, head, row["tags"]))
                    if kind == "outfit":
                        summary["states"] = states.get(row["id"], {})
                    by_id[row["id"]] = summary
                    seeds[kind, pool][seed].append(summary)
            for seed_rows in seeds.values():
                for rows in seed_rows.values():
                    rows.sort(key=_order)
            for kind in {kind for kind, _ in seeds}:
                merged, seen = defaultdict(list), set()
                pools = sorted((pool for k, pool in seeds if k == kind), key=lambda pool: _POOL_PRIORITY.get(pool, 9))
                for pool in pools:
                    for seed, rows in seeds[kind, pool].items():
                        for row in rows:
                            mark = (seed, tuple(sorted(row["tags"])))
                            if mark not in seen:
                                seen.add(mark)
                                merged[seed].append(row)
                seeds[kind, ALL_POOLS] = merged
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

        def entry(seed, posts):
            rows = seeds[seed]
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
                    matches.append({"kind": row["kind"], "pool": row["pool"], "seed": row["seed"],
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
