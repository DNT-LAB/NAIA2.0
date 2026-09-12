# -*- coding: utf-8 -*-
"""이벤트 맵 빌더가 읽는 **원본 두 가지**를 같은 모양으로 감싼다.

빌드 전용이다(질의 시점에는 안 쓴다). 그래서 `core/` 가 아니라 여기 있다 -
연령 게이트의 SSOT 인 `tools/thumb_age_guard.py` 를 그대로 import 하려면
`core/` 에서 `tools/` 를 부르는 역방향 의존이 생긴다.

## 원본 둘

`scene-observed-175-v1`  (scene_events.175.sqlite3, 2.24GB)
    인계 꾸러미가 준 관측 DB. **이미 걸러진 것**이다:
      · 행 거르개로 361,480건이 빠졌다(연령 위험어 · rape/guro/scat/incest · Danger 그룹)
      · 태그 100,537개 중 14,559개만 `preset_eligible` 이라 목록(postings)이 있다
    그래서 이 원본으로 지은 맵은 어휘의 16%만 담는다.

`tag-corpus-full-175-v1` (tag_corpus.full.175.sqlite3, 2.36GB)
    원본 Parquet 175개의 **물리 행 전부**(9,127,788). 거르개도 분류도 없다.
    태그 이름·post id·rating·원본 위치만 있고 details 가 없으므로, 분류(`classify`)와
    인원 그룹(`person_group_of`)과 행 거르개(`row_blocked`)를 **여기서 다시 계산**한다.
    계산 규칙은 원본 하니스(`harness/tag_harness/scene_events.py`)를 그대로 옮긴 것이라
    `--guard source` 로 지으면 같은 게시물이 빠진다(실측으로 대조한다).

## 왜 규칙을 다시 적는가

적지 않는다. 세 SSOT 를 그대로 부른다:
  · 연령 게이트 = `tools/thumb_age_guard.py`   (같은 정규식이 세 곳에 복사돼 셋 다 틀렸던 전력)
  · 인원 그룹   = `core/tag_combo/person.py`
  · 분류표      = `data/interactive_tags.json` (인계 꾸러미의 snapshot 과 바이트 동일)
세 파일 모두 인계 꾸러미의 snapshot 과 해시가 같다는 것을 확인했다(2026-09-12).
`classify`/`RISK`/`ADULT`/`POPULATION` 만 하니스에서 옮겼다 - 그 원본은 꾸러미에만 있다.
"""
from __future__ import annotations

from array import array
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import sys

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from core.tag_combo.person import PERSON_GROUPS, person_group_of  # noqa: E402
from tools.thumb_age_guard import danger_age_hits                 # noqa: E402

SCENE_SCHEMA = "scene-observed-175-v1"
FULL_SCHEMA = "tag-corpus-full-175-v1"
RATINGS = "gsqe"
PARTITIONS = [r + "_" + p for r in RATINGS for p in PERSON_GROUPS]

TAXONOMY_PATH = REPO / "data" / "interactive_tags.json"

# ── 하니스에서 옮긴 것 (harness/tag_harness/scene_events.py) ──────────────────
# 이름을 바꾸지 않는다. 이 표가 갈라지면 두 원본으로 지은 맵을 대조할 수 없다.
AGE_EXCEPTIONS = {"lolita fashion", "gothic lolita", "sweet lolita", "babydoll"}
RISK = re.compile(r"\b(?:rape|guro|ryona|scat|feces|incest|bestial\w*|molest\w*"
                  r"|necro\w*|amputee|mutilat\w*|torture|snuff)\b", re.I)
ADULT = re.compile(r"\b(?:sex|nude|naked|nipples?|penis|pussy|vaginal|cum|semen"
                   r"|masturbat\w*|fellan?ti\w*|cunnilingus|oral|anal|asshole)\b", re.I)
META_SUBGROUPS = {"alternate", "art_style", "censoring", "colors", "metatags",
                  "quality", "scan", "subjective", "text", "year_tags"}
NONVISUAL = {"signature", "watermark", "artist name", "character name", "copyright name",
             "commentary", "translated", "dated", "commentary request",
             "translation request", "logo"}
POPULATION = {"1girl", "1boy", "2girls", "2boys", "multiple girls", "multiple boys",
              "multiple girls multiple boys", "solo"}
RELATIONS = {"height difference", "size difference", "age difference",
             "facing each other", "back-to-back", "side-by-side"}

# 행 거르개 층. `--guard` 가 어디까지 걸지 고른다.
GUARD_LEVELS = ("source", "age", "none")
GUARD_HELP = {
    "source": "원본 관측 DB 와 같다: 연령 + 위험어 + Danger 그룹 (기본)",
    "age":    "연령 게이트만 건다. 위험어·Danger 게시물은 되살린다",
    "none":   "행 거르개를 아예 안 건다",
}

_EMOTICON = re.compile(r"[0-9oxuvtq^+@*<>;:=/\\.\-]{1,3}_[0-9oxuvtq^+@*<>;:=/\\.\-]{1,3}")
_WORD = re.compile(r"[a-z0-9가-힣]")


def normalize(value) -> str:
    """하니스(`harness/tag_harness/index.py:20`)와 **같은** 정규화.

    `core/event_map/policy.py:normalize` 와 다르다 - 저쪽은 정책 정규식용이라
    밑줄을 무조건 공백으로 바꾼다. 여기서 그러면 `>_<` 같은 표정 태그 16개가
    서로 뭉개진다(실측). 이름을 만드는 자리에서는 이 규칙을 쓴다.
    """
    text = str(value or "").strip().lower().replace(r"\(", "(").replace(r"\)", ")")
    if not _EMOTICON.fullmatch(text) and _WORD.search(text):
        text = text.replace("_", " ")
    return " ".join(text.split())


def row_blocked(tag: str, info: dict, level: str = "source") -> str | None:
    """이 태그가 달린 **행을 통째로** 버릴 이유(규칙 이름). 안 버리면 None."""
    if level == "none":
        return None
    if danger_age_hits(tag) and tag not in AGE_EXCEPTIONS:
        return "source_age"
    if level == "age":
        return None
    if RISK.search(tag):
        return "source_risk"
    if info.get("group") == "Danger":
        return "source_danger_group"
    return None


def classify(tag: str, info: dict) -> dict:
    """하니스 `classify` 를 그대로 옮긴 것. 이름·값을 바꾸지 않는다."""
    group, sub = info.get("group", "unclassified"), info.get("subgroup", "")
    role, eligible, reason = "unreviewed", False, "unknown_source_classification"
    if row_blocked(tag, info, "source"):
        reason = "source_row_guard"
    elif ADULT.search(tag) or group == "NSFW":
        reason = "outside_general_prompt_projection"
    elif tag in NONVISUAL:
        reason = "nonvisual_metadata"
    elif tag in POPULATION:
        role, eligible, reason = "population", True, "explicit_population_only"
    elif tag in RELATIONS:
        role, eligible, reason = "scene_relation", True, "relative_scene_attribute"
    elif group == "Composition_Meta":
        role = "scene_relation"
        eligible = sub not in META_SUBGROUPS and sub not in {"meta", "count"}
        reason = "visual_scene_composition" if eligible else "nonvisual_or_unreviewed_composition"
    elif group == "Expression_Action":
        role = ("actor_state"
                if sub in {"emotion", "expression", "eyes", "gender_expression",
                           "personality", "reaction", "state"} or tag.startswith("looking ")
                else "event_core")
        eligible, reason = True, "observed_action_or_state"
    elif group in {"Person_Body", "Creatures"}:
        role, eligible, reason = "actor_state", True, "general_actor_feature_not_named_identity"
    elif group in {"Food_Object", "Clothing_Wear", "Location_Background", "Culture_Misc"}:
        role, eligible, reason = "scene_object", True, "general_visual_context"
    return {"original_group": group, "original_subgroup": sub, "role": role,
            "preset_eligible": eligible, "reason": reason}


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _connect(path: Path) -> sqlite3.Connection:
    db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    db.execute("PRAGMA cache_size=-262144")
    return db


# ── 원본 어댑터 ──────────────────────────────────────────────────────────────
#
# 빌더가 쓰는 것은 이 다섯 가지뿐이다:
#   .names   {tid: 이름}
#   .details {tid: {original_subgroup, role, preset_eligible, reason, admitted_posts}}
#   .partitions [pid 순서의 분면 이름]
#   .source_block {tid: 규칙 이름}   - 행 거르개(전 등급). 원본 DB 는 이미 뺐으므로 비어 있다.
#   .rows()  -> (rid, pid, {tid...})
# `total` 은 진행률 표시에만 쓴다.

class SceneSource:
    """이미 걸러진 관측 DB. 제출판 2종(policy/nopolicy)을 만든 그 원본이다."""

    kind = "scene"

    def __init__(self, path: Path, *, guard: str = "source", limit_rows: int = 0):
        self.path = path
        self.db = _connect(path)
        self.meta = {k: json.loads(v) for k, v in self.db.execute("SELECT key,value FROM metadata")}
        if self.meta.get("schema") != SCENE_SCHEMA or self.meta.get("state") != "ready":
            raise SystemExit("관측 DB 가 아니거나 ready 가 아니다: %s" % path)
        if guard != "source":
            raise SystemExit("관측 DB 는 이미 거른 것이라 --guard %s 를 적용할 수 없다.\n"
                             "  거르개를 열려면 Full 코퍼스(%s)를 원본으로 줘라." % (guard, FULL_SCHEMA))
        self.limit_rows = limit_rows
        self.names = {i: n for i, n in self.db.execute("SELECT id,name FROM tags")}
        self.details = {i: json.loads(d) for i, d in self.db.execute("SELECT id,details FROM tags")}
        self.partitions = [n for _, n in sorted(
            (pid, name) for pid, name, *_ in self.db.execute("SELECT * FROM partitions"))]
        self.source_block: dict[int, str] = {}
        self.total = self.db.execute("SELECT MAX(id) FROM records").fetchone()[0] or 0
        if limit_rows:
            self.total = min(self.total, limit_rows)

    @property
    def source_meta(self) -> dict:
        return {"path": str(self.path), "schema": self.meta.get("schema"),
                "source_manifest_sha256": self.meta.get("source_manifest_sha256"),
                "source_audit": self.meta.get("audit"),
                "row_guard": "원본 DB 가 빌드 때 이미 걸렀다(361,480건). 여기서는 못 연다",
                "vocabulary_scope": "preset_eligible + outside_general_prompt_projection 만"}

    def rows(self):
        sql = "SELECT id,partition,tags FROM records ORDER BY id"
        if self.limit_rows:
            sql += " LIMIT %d" % self.limit_rows
        for rid, pid, blob in self.db.execute(sql):
            a = array("I")
            a.frombytes(blob)
            yield rid, pid, set(a)

    def close(self) -> None:
        self.db.close()


class FullCorpusSource:
    """거르지 않은 Full 코퍼스. 분류·인원 그룹·행 거르개를 여기서 계산한다."""

    kind = "full"

    def __init__(self, path: Path, *, guard: str = "source", limit_rows: int = 0):
        if guard not in GUARD_LEVELS:
            raise SystemExit("--guard 는 %s 중 하나여야 한다" % ", ".join(GUARD_LEVELS))
        self.path = path
        self.guard = guard
        self.limit_rows = limit_rows
        self.db = _connect(path)
        self.meta = {k: json.loads(v) for k, v in self.db.execute("SELECT key,value FROM metadata")}
        if self.meta.get("schema") != FULL_SCHEMA or self.meta.get("state") != "ready":
            raise SystemExit("Full 코퍼스가 아니거나 ready 가 아니다: %s" % path)

        taxonomy = {normalize(k): v for k, v in
                    json.loads(TAXONOMY_PATH.read_text(encoding="utf-8")).items()}
        self.taxonomy_sha256 = digest(TAXONOMY_PATH)

        # 1) general 어휘를 정규화해 접는다. 원본은 표기를 보존하므로 `\(^o^)/` 처럼
        #    정규화하면 겹치는 이름이 있다 - 겹치면 앞 id 로 모으고 개수를 더한다.
        self.names: dict[int, str] = {}
        self.details: dict[int, dict] = {}
        self.source_block: dict[int, str] = {}
        self.remap: dict[int, int] = {}          # 원본 tag id -> 내 tid
        by_name: dict[str, int] = {}
        merged = 0
        for raw_id, raw_name, card in self.db.execute(
                "SELECT id,name,cardinality FROM tags WHERE field='general'"):
            name = normalize(raw_name)
            if not name:
                continue
            tid = by_name.get(name)
            if tid is None:
                tid = by_name[name] = len(by_name)
                info = taxonomy.get(name, {})
                desc = classify(name, info)
                desc["admitted_posts"] = 0
                self.names[tid] = name
                self.details[tid] = desc
                rule = row_blocked(name, info, guard)
                if rule:
                    self.source_block[tid] = rule
            else:
                merged += 1
            self.details[tid]["admitted_posts"] += card
            self.remap[raw_id] = tid
        self.merged_names = merged
        self.population_ids = {t for t, n in self.names.items() if n in POPULATION}
        self.partitions = list(PARTITIONS)
        self.total = self.db.execute("SELECT MAX(id) FROM records").fetchone()[0] or 0
        if limit_rows:
            self.total = min(self.total, limit_rows)
        self.audit = {"invalid_rating": 0, "empty_general": 0, "rows": 0}

    @property
    def source_meta(self) -> dict:
        return {"path": str(self.path), "schema": self.meta.get("schema"),
                "source_manifest_sha256": self.meta.get("source_manifest_sha256"),
                "source_audit": self.meta.get("audit"),
                "row_guard": "%s - %s" % (self.guard, GUARD_HELP[self.guard]),
                "row_guard_tags": len(self.source_block),
                "vocabulary_scope": "general 전부 %d개(정규화로 접은 이름 %d개)"
                                    % (len(self.names), self.merged_names),
                "taxonomy": {"path": "data/interactive_tags.json", "sha256": self.taxonomy_sha256},
                "recomputed": ["classify", "person_group_of", "row_blocked"],
                "row_audit": self.audit}

    def rows(self):
        """(rid, pid, {tid...}). rid 는 원본의 물리 행 번호를 그대로 쓴다."""
        remap = self.remap
        population = self.population_ids
        names = self.names
        sql = "SELECT id,rating,general FROM records ORDER BY id"
        if self.limit_rows:
            sql += " LIMIT %d" % self.limit_rows
        base = {p: PERSON_GROUPS.index(p) for p in PERSON_GROUPS}
        other = base["other"]
        for rid, rating, blob in self.db.execute(sql):
            self.audit["rows"] += 1
            if not rating or len(rating) != 1 or rating not in RATINGS:
                self.audit["invalid_rating"] += 1
                continue
            a = array("I")
            a.frombytes(blob)
            tags = {remap[t] for t in a if t in remap}
            if not tags:
                self.audit["empty_general"] += 1
                # rating 은 멀쩡하므로 분면은 제대로 매긴다(본문만 빈다).
                yield rid, RATINGS.index(rating) * 13 + other, tags
                continue
            group = person_group_of(names[t] for t in tags & population)
            yield rid, RATINGS.index(rating) * 13 + base.get(group, other), tags

    def close(self) -> None:
        self.db.close()


def open_source(path: Path, *, guard: str = "source", limit_rows: int = 0):
    """스키마를 읽어 맞는 어댑터를 돌려준다."""
    db = _connect(path)
    try:
        row = db.execute("SELECT value FROM metadata WHERE key='schema'").fetchone()
        schema = json.loads(row[0]) if row else None
    finally:
        db.close()
    if schema == SCENE_SCHEMA:
        return SceneSource(path, guard=guard, limit_rows=limit_rows)
    if schema == FULL_SCHEMA:
        return FullCorpusSource(path, guard=guard, limit_rows=limit_rows)
    raise SystemExit("모르는 원본 스키마다: %r\n  아는 것: %s / %s"
                     % (schema, SCENE_SCHEMA, FULL_SCHEMA))


def _audit_main() -> None:
    """태그 층 감사만 찍는다(행은 안 훑는다). `python tools/event_map_sources.py <db>`"""
    import argparse
    from collections import Counter
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="원본의 태그 분류를 세어 본다")
    ap.add_argument("source")
    ap.add_argument("--guard", choices=GUARD_LEVELS, default="source")
    args = ap.parse_args()
    src = open_source(Path(args.source).resolve(), guard=args.guard)
    print("원본 : %s (%s)" % (src.path, src.kind))
    print("태그 : %s" % format(len(src.names), ","))
    reason = Counter(d.get("reason") for d in src.details.values())
    inc = Counter()
    for tid, d in src.details.items():
        inc[d.get("reason")] += d.get("admitted_posts") or 0
    total_inc = sum(inc.values()) or 1
    print()
    print("%-42s %8s %14s %7s" % ("reason", "태그", "태그-게시물", "비중"))
    for k, n in reason.most_common():
        print("%-42s %8s %14s %6.2f%%"
              % (k, format(n, ","), format(inc[k], ","), 100 * inc[k] / total_inc))
    print()
    role = Counter(d.get("role") for d in src.details.values())
    print("role : " + "  ".join("%s=%s" % (k, format(v, ",")) for k, v in role.most_common()))
    if src.source_block:
        rules = Counter(src.source_block.values())
        print("행 거르개 태그 : " + "  ".join("%s=%s" % (k, format(v, ","))
                                              for k, v in rules.most_common()))
    src.close()


if __name__ == "__main__":
    _audit_main()
