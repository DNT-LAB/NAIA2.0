# -*- coding: utf-8 -*-
"""이벤트 맵(Ctrl+E) 접근의 **단일 소유자**.

`core/event_map/index.py` 는 파일 하나를 읽는 리더다. 이 모듈은 그 위에서
**경로 해석 · 지연 개방 · 입력 검증 · 화면이 쓸 재료**를 책임진다. 라우트는 이것만 부른다.

## 왜 서비스를 따로 두는가

세 가지가 라우트에 들어가면 안 되기 때문이다.

1. **색인은 없을 수 있다.** 1.4GB(Full) / 744MB(상용 후보) 파일이라 기본 배포에 넣을 수
   없다. 없을 때 500 을 내면 화면이 "고장" 으로 읽는다 - `state: missing` 으로 답해야 한다.
   `core/event_corpus_index.py` 가 같은 이유로 같은 모양을 쓴다.
2. **입력 상한.** 핀 16 · 제외 32 · 표본 50 은 리더의 계약이지만, 라우트마다 다시 적으면
   갈라진다. 여기서 한 번 검증하고 안정된 `code` 로 돌려준다.
3. **화면 재료를 색인에서 뽑는다.** 등급·인원·갈래 칩 목록을 프론트에 박아 두면 색인이
   바뀔 때 갈라진다 - 시험대에서 실제로 겪었다(어휘 10만짜리 판을 열었더니 갈래 칩에
   `unreviewed` 가 없어 태그 85,007개를 걸러 볼 수가 없었다). `status()` 가 준다.

## 색인을 어디서 찾는가

앞에서 뒤로, **처음 열리는 것**을 쓴다:

    1. 환경 변수 `NAIA_EVENT_MAP_INDEX` (파일 경로 직접 지정 - 개발·검증용)
    2. `<runtime user-data>/data/event_map/event_map.naiamap`
    3. `<repo>/data/event_map/event_map.naiamap`

user-data 가 먼저다 - 내려받은 색인이 그쪽에 떨어진다. 같은 우선순위를
`app/backend/server/event_corpus_commands.py:_data_roots` 가 쓴다.
⚠️ 빈 디렉터리가 정상 데이터를 가리지 않도록 **열리는 것**을 고른다(존재만 보지 않는다).

읽기 전용으로만 연다. 이 모듈은 아무것도 쓰지 않는다.
"""
from __future__ import annotations

import bisect
import os
import threading
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

import numpy as np

from core.event_map import categories as C
from core.event_map.index import (
    MAX_EXCLUDE, MAX_PINS, MAX_SAMPLES, SCAN_CAP, EventMapIndex)

# 대분류 재료. `data/KR_tags.parquet` 의 category 를 접기 표로 접는다(사용자 결정 2026-09-12).
KR_TAGS_REL = Path("data") / "KR_tags.parquet"

ENV_PATH = "NAIA_EVENT_MAP_INDEX"
# 서브디렉터리에 두는 것을 기본으로 한다 - 나중에 같은 폴더에 설명/해시 파일이 붙는다.
FILENAMES = ("event_map/event_map.naiamap", "event_map.naiamap",
             "event_map/event_map.sqlite3")

MAX_QUERY = 80
MAX_CANDIDATES = 60
DEFAULT_CANDIDATES = 24
DEFAULT_SUGGEST = 20
MAX_SUGGEST = 40

# 화면 문구. 색인은 갈래 이름만 담으므로 번역은 여기 한 곳에 둔다.
ROLE_LABELS = {
    "event_core": "행동", "actor_state": "상태", "scene_object": "사물",
    "scene_relation": "구도", "population": "인원", "unreviewed": "미분류",
    "adult_act": "성인·행위", "adult_body": "성인·신체", "adult_object": "성인·사물",
    "adult": "성인·기타", "adult_taboo": "성인·금기", "adult_gore": "성인·고어",
    "adult_dark": "성인·다크", "adult_meta": "성인·메타",
}
LANE_LABELS = {
    "general": "일반", "adult": "성인", "unclassified": "미분류",
    "nonvisual": "메타·연출", "guarded": "거르개", "extended": "확장",
}
RATING_LABELS = {"g": "전체", "s": "약간", "q": "선정", "e": "노출"}
PERSON_LABELS = {
    "1girl_solo": "여1 단독", "1girl": "여1", "1girl_1boy": "여1 남1",
    "1girl_multiple_boys": "여1 남다수", "2girls": "여2", "multiple_girls": "여다수",
    "1boy_solo": "남1 단독", "1boy": "남1", "1boy_multiple_girls": "남1 여다수",
    "2boys": "남2", "multiple_boys": "남다수",
    "multiple_girls_multiple_boys": "여다수 남다수", "other": "기타",
}


class MapQueryError(Exception):
    """검증 실패. `code` 는 프론트가 분기하는 안정 문자열이다."""

    def __init__(self, code: str, message: str, **extra: Any) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.extra = extra

    def to_payload(self) -> dict[str, Any]:
        return {"ok": False, "status": "error", "code": self.code,
                "message": self.message, **self.extra}


def default_roots(context: Any) -> list[Path]:
    """`event_corpus_commands._data_roots` 와 같은 우선순위."""
    roots: list[Path] = []
    runtime_paths = getattr(context, "runtime_paths", None)
    if runtime_paths is not None:
        try:
            roots.append(Path(runtime_paths.data_dir))
        except Exception:
            pass
    repo_root = getattr(context, "repo_root", None)
    if repo_root:
        roots.append(Path(repo_root) / "data")
    return roots


class EventMapService:
    """맵 색인을 지연 개방하고 질의를 검증해 넘긴다. 스레드 안전."""

    def __init__(self, roots: Sequence[Path] | None = None,
                 kr_tags_path: Path | None = None) -> None:
        self._roots = [Path(r) for r in (roots or [])]
        self._kr_tags_path = kr_tags_path
        self._lock = threading.Lock()
        self._index: EventMapIndex | None = None
        # 대분류: 태그 id -> 갈래 순번(groups() 순서). 색인을 열 때 같이 만든다.
        self._group_arr: np.ndarray | None = None
        self._group_rows: list[dict] = []
        self._state = "unknown"
        self._message = ""
        self._path: Path | None = None
        self._tried: list[str] = []
        # suggest 용. 어휘가 10만이라 키 입력마다 전체를 훑지 않는다.
        self._sorted_names: list[str] = []

    # -- 개방 ----------------------------------------------------------------
    def _candidates(self) -> list[Path]:
        out: list[Path] = []
        env = str(os.environ.get(ENV_PATH) or "").strip().strip('"')
        if env:
            out.append(Path(env))
        for root in self._roots:
            for name in FILENAMES:
                out.append(root / name)
        # 같은 경로를 두 번 열지 않는다(user-data 와 repo 가 같은 폴더일 수 있다).
        seen: set[str] = set()
        unique = []
        for p in out:
            key = str(p)
            if key not in seen:
                seen.add(key)
                unique.append(p)
        return unique

    def index(self) -> EventMapIndex:
        """색인을 준다. 없거나 못 열면 `MapQueryError('unavailable')`."""
        idx = self._index
        if idx is not None:
            return idx
        with self._lock:
            if self._index is not None:
                return self._index
            self._tried = []
            last = ""
            for path in self._candidates():
                self._tried.append(str(path))
                if not path.is_file():
                    continue
                try:
                    idx = EventMapIndex(path)
                except Exception as exc:
                    # 존재하지만 못 여는 파일(중단된 다운로드 등)은 다음 후보로 넘어간다.
                    last = "%s: %s" % (path.name, exc)
                    self._state, self._message = "corrupt", last
                    continue
                self._index = idx
                self._path = path
                self._state, self._message = "ready", ""
                self._sorted_names = sorted(idx.by_name)
                self._load_groups(idx)
                return idx
            if self._state != "corrupt":
                self._state = "missing"
                self._message = "이벤트 맵 색인을 찾지 못했다."
            raise MapQueryError("unavailable", self._message or "이벤트 맵 색인이 없다.",
                                state=self._state, searched=self._tried)

    def _load_groups(self, idx: EventMapIndex) -> None:
        """KR_tags 의 category 를 접기 표로 접어 태그마다 갈래를 붙인다.

        parquet 이 없거나 못 읽으면 전부 `unsorted` 다 - 맵은 그래도 돈다(대분류 화면만 빈다).
        ⚠️ 정규화는 색인 쪽 `resolve` 를 쓴다 - 표기(밑줄·대소문자)가 갈리면 분류가 통째로 빈다.
        """
        groups = C.groups()
        order = {g["id"]: i for i, g in enumerate(groups)}
        unsorted = order[C.UNSORTED]
        arr = np.full(idx.n_tags, unsorted, dtype=np.int16)
        source = ""
        path = self._kr_tags_path
        if path is None:
            for root in self._roots:
                # roots 는 `<user-data>/data` · `<repo>/data` 다 - KR_tags.parquet 은 그 바로 아래.
                cand = Path(root) / KR_TAGS_REL.name
                if cand.is_file():
                    path = cand
                    break
        if path is not None and Path(path).is_file():
            try:
                import pandas as pd
                frame = pd.read_parquet(path, columns=["tag", "category"])
                hit = 0
                for tag, cat in zip(frame["tag"].astype(str), frame["category"].astype(str)):
                    tid = idx.resolve(tag)
                    if tid is None:
                        continue
                    gid, _sub = C.fold_category(cat)
                    arr[tid] = order.get(gid, unsorted)
                    hit += 1
                source = "%s (%d tags matched)" % (path, hit)
            except Exception as exc:                                  # pragma: no cover
                source = "failed: %s" % exc
        self._group_arr = arr
        counts = np.bincount(arr, minlength=len(groups))
        obs = np.bincount(arr, weights=idx.obs_arr, minlength=len(groups))
        self._group_rows = [
            {**g, "tags": int(counts[i]), "observed": int(obs[i])}
            for i, g in enumerate(groups)
        ]
        self._group_source = source

    def group_mask(self, group_ids: Iterable[str]) -> np.ndarray | None:
        """갈래 id 들 -> 태그 불리언 마스크. 모르는 id 는 무시하고, 하나도 안 남으면 None."""
        if self._group_arr is None:
            return None
        order = {g["id"]: i for i, g in enumerate(C.groups())}
        wanted = [order[g] for g in group_ids if g in order]
        if not wanted:
            return None
        return np.isin(self._group_arr, np.array(wanted, dtype=np.int16))

    def group_of(self, tid: int) -> str:
        if self._group_arr is None:
            return C.UNSORTED
        return C.groups()[int(self._group_arr[tid])]["id"]

    def invalidate(self) -> None:
        """내려받기·마이그레이션 뒤에 다시 찾게 한다."""
        with self._lock:
            idx, self._index = self._index, None
            self._state, self._message, self._path = "unknown", "", None
            self._sorted_names = []
            self._group_arr, self._group_rows = None, []
        if idx is not None:
            try:
                idx.close()
            except Exception:
                pass

    # -- 상태 ----------------------------------------------------------------
    def status(self) -> dict[str, Any]:
        """절대 예외를 내지 않는다. 화면 머리줄과 칩 목록의 재료 전부."""
        try:
            idx = self.index()
        except MapQueryError as exc:
            return {"ok": True, "state": exc.extra.get("state") or "missing",
                    "message": exc.message, "searched": exc.extra.get("searched") or [],
                    "limits": self._limits()}
        except Exception as exc:                                  # pragma: no cover
            return {"ok": True, "state": "missing", "message": str(exc),
                    "searched": self._tried, "limits": self._limits()}

        meta = idx.meta
        path = self._path or Path(idx.path)
        try:
            size = path.stat().st_size
        except OSError:
            size = 0
        ratings, persons = [], []
        for name in idx.partitions:
            r, person = name[:1], name[2:]
            if r not in ratings:
                ratings.append(r)
            if person not in persons:
                persons.append(person)
        roles: dict[str, int] = {}
        for tid in range(idx.n_tags):
            role = idx.role.get(tid) or "unreviewed"
            roles[role] = roles.get(role, 0) + 1
        return {
            "ok": True,
            "state": "ready",
            "message": "",
            "path": str(path),
            "bytes": size,
            "mb": round(size / 1048576, 1),
            "tags": idx.n_tags,
            "posts": idx.total_posts,
            "partitions": list(idx.partitions),
            "lanes": [{"id": k, "label": LANE_LABELS.get(k, k), "tags": v}
                      for k, v in sorted((meta.get("lanes") or {}).items(),
                                         key=lambda kv: -kv[1])],
            # ⚠️ 갈래 칩은 색인에서 뽑는다. 프론트에 박으면 판이 바뀔 때 갈라진다.
            "roles": [{"id": k, "label": ROLE_LABELS.get(k, k), "tags": v}
                      for k, v in sorted(roles.items(), key=lambda kv: -kv[1])],
            # 대분류(접기 표 12갈래). 첫 화면의 축이고 후보 필터다. 태그 수 0 인 갈래도 보낸다 -
            # 화면이 "없다" 를 그릴 수 있게.
            "groups": [dict(row) for row in self._group_rows],
            "group_source": getattr(self, "_group_source", ""),
            "ratings": [{"id": r, "label": RATING_LABELS.get(r, r)} for r in ratings],
            "persons": [{"id": p, "label": PERSON_LABELS.get(p, p.replace("_", " "))}
                        for p in persons],
            "build": {
                "policy_mode": meta.get("policy_mode"),
                "row_guard": meta.get("row_guard") or "source",
                "age_floor": meta.get("age_floor") or "on",
                "color_policy": meta.get("color_policy"),
                "record_width": meta.get("record_width") or 2,
                "built_at": meta.get("built_at"),
                "source_schema": (meta.get("source") or {}).get("schema"),
            },
            "limits": self._limits(),
            "note": meta.get("note") or "",
        }

    def _limits(self) -> dict[str, int]:
        return {"max_pins": MAX_PINS, "max_exclude": MAX_EXCLUDE,
                "max_samples": MAX_SAMPLES, "max_candidates": MAX_CANDIDATES,
                "max_query": MAX_QUERY, "scan_cap": SCAN_CAP}

    # -- 검증 ----------------------------------------------------------------
    def _tags(self, value: Any, *, cap: int, what: str, code: str) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            items = [p.strip() for p in value.split(",")]
        elif isinstance(value, (list, tuple)):
            items = [str(p or "").strip() for p in value]
        else:
            raise MapQueryError(code, "%s 목록의 형태가 잘못됐다." % what)
        items = [p for p in items if p]
        if len(items) > cap:
            raise MapQueryError(code, "%s는 %d개까지다." % (what, cap), limit=cap)
        if any(len(p) > MAX_QUERY for p in items):
            raise MapQueryError(code, "%s 이름이 너무 길다." % what)
        return items

    def _filters(self, idx: EventMapIndex, ratings: Any, persons: Any) -> tuple[list, list]:
        known_r = {name[:1] for name in idx.partitions}
        known_p = {name[2:] for name in idx.partitions}
        want_r = self._tags(ratings, cap=8, what="등급", code="bad_rating")
        want_p = self._tags(persons, cap=16, what="인원", code="bad_person")
        bad = [r for r in want_r if r not in known_r]
        if bad:
            raise MapQueryError("bad_rating", "모르는 등급이다: %s" % ", ".join(bad))
        bad = [p for p in want_p if p not in known_p]
        if bad:
            raise MapQueryError("bad_person", "모르는 인원 그룹이다: %s" % ", ".join(bad))
        return want_r, want_p

    @staticmethod
    def _count(value: Any, default: int, cap: int) -> int:
        try:
            n = int(value)
        except (TypeError, ValueError):
            n = default
        return max(1, min(cap, n))

    # -- 질의 ----------------------------------------------------------------
    def suggest(self, query: str, limit: int = DEFAULT_SUGGEST, *,
                kr_lookup: Callable[[str, int], Iterable[str]] | None = None) -> dict[str, Any]:
        """이름으로 태그를 찾는다. **못 꽂는 태그도 왜 못 꽂는지 붙여서** 낸다.

        `kr_lookup` 은 한글 질의를 태그 이름으로 바꿔 주는 다리다(라우트가 태그 사전
        검색기를 넣어 준다). 맵 어휘에 있는 것만 남긴다.
        """
        idx = self.index()
        raw = str(query or "").strip()
        if len(raw) > MAX_QUERY:
            raise MapQueryError("query_too_long", "검색어가 너무 길다.")
        limit = self._count(limit, DEFAULT_SUGGEST, MAX_SUGGEST)
        if not raw:
            return {"ok": True, "status": "empty", "query": raw, "items": []}

        q = raw.casefold()
        picked: list[tuple[int, str, int]] = []
        seen: set[str] = set()

        def take(name: str) -> None:
            tid = idx.by_name.get(name)
            if tid is None or name in seen:
                return
            seen.add(name)
            picked.append((idx.observed[tid], name, tid))

        # 1) 앞부분 일치. 정렬 목록에 bisect - 어휘 10만을 키 입력마다 훑지 않는다.
        names = self._sorted_names
        start = bisect.bisect_left(names, q)
        prefix = []
        for name in names[start:start + 4000]:
            if not name.startswith(q):
                break
            prefix.append(name)
        for name in prefix:
            take(name)
        # 2) 가운데 일치. 앞부분만으로 모자랄 때만 훑는다.
        if len(picked) < limit:
            for name in names:
                if q in name and name not in seen:
                    take(name)
        # 3) 한글 다리. 태그 사전이 준 이름 중 맵 어휘에 있는 것만.
        translated: list[str] = []
        if kr_lookup is not None and len(picked) < limit:
            try:
                for name in kr_lookup(raw, limit * 3):
                    tid = idx.resolve(name)
                    if tid is None or idx.by_id[tid] in seen:
                        continue
                    translated.append(idx.by_id[tid])
                    take(idx.by_id[tid])
            except Exception:
                translated = []      # 사전이 없어도 영문 검색은 계속 된다

        picked.sort(key=lambda row: (-row[0], row[1]))
        items = []
        for observed, name, tid in picked[:limit]:
            blocked = None
            if idx.color[tid]:
                blocked = "색상"
            elif not idx.eligible[tid]:
                blocked = "후보 아님"
            items.append({"tag": name, "observed": observed,
                          "role": idx.role.get(tid), "lane": idx.lane.get(tid),
                          "role_label": ROLE_LABELS.get(idx.role.get(tid) or "", ""),
                          "blocked": blocked})
        return {"ok": True, "status": "matched" if items else "no_match",
                "query": raw, "items": items, "translated": translated}

    # 색상은 앱 경로에서 **항상** 뺀다(사용자 지정 2026-09-12). 리더의 include_color 는 시험대
    # (tools/event_map_playground.py)가 연구용으로만 쓴다 - 여기서는 켤 길을 두지 않는다.
    def explore(self, *, pins: Any, exclude: Any = None, ratings: Any = None,
                persons: Any = None, roles: Any = None, groups: Any = None,
                limit: Any = DEFAULT_CANDIDATES) -> dict[str, Any]:
        idx = self.index()
        wanted = self._tags(pins, cap=MAX_PINS, what="핀", code="too_many_pins")
        if not wanted:
            raise MapQueryError("no_pins", "핀이 하나는 있어야 한다.")
        excluded = self._tags(exclude, cap=MAX_EXCLUDE, what="제외 태그",
                              code="too_many_exclude")
        want_r, want_p = self._filters(idx, ratings, persons)
        want_roles = self._tags(roles, cap=32, what="갈래", code="bad_role")
        want_groups = self._tags(groups, cap=16, what="대분류", code="bad_group")
        try:
            result = idx.explore(
                wanted, exclude=excluded, ratings=want_r, persons=want_p,
                roles=want_roles or None, allowed=self.group_mask(want_groups),
                limit=self._count(limit, DEFAULT_CANDIDATES, MAX_CANDIDATES),
                include_color=False)
        except ValueError as exc:
            raise MapQueryError("bad_request", str(exc)) from exc
        self._attach_groups(result.get("candidates") or [])
        result["ok"] = True
        return result

    def browse(self, *, group: Any, ratings: Any = None, persons: Any = None,
               limit: Any = DEFAULT_CANDIDATES) -> dict[str, Any]:
        """첫 화면: 핀 없이 대분류 하나를 골라 그 분면(인원·등급)에서 특징적인 태그를 본다."""
        idx = self.index()
        gid = str(group or "").strip()
        known = {g["id"] for g in C.groups()}
        if gid not in known:
            raise MapQueryError("bad_group", "모르는 대분류다: %s" % gid, known=sorted(known))
        want_r, want_p = self._filters(idx, ratings, persons)
        mask = self.group_mask([gid])
        if mask is None:
            raise MapQueryError("unavailable", "대분류 표를 못 만들었다(KR_tags.parquet 없음).",
                                state="ready")
        result = idx.browse(ratings=want_r, persons=want_p, allowed=mask,
                            limit=self._count(limit, DEFAULT_CANDIDATES, MAX_CANDIDATES))
        self._attach_groups(result.get("candidates") or [])
        result["group"] = gid
        result["ok"] = True
        return result

    def _attach_groups(self, candidates: list[dict]) -> None:
        idx = self._index
        if idx is None or self._group_arr is None:
            return
        for c in candidates:
            tid = idx.by_name.get(c.get("tag"))
            if tid is not None:
                c["group"] = self.group_of(tid)

    def sample(self, *, pins: Any, exclude: Any = None, ratings: Any = None,
               persons: Any = None, n: Any = 5, seed: Any = None) -> dict[str, Any]:
        """핀을 포함하는 **실제 게시물**의 태그 조합. Dev0714 Quick Search 의 랜덤과 같다."""
        idx = self.index()
        wanted = self._tags(pins, cap=MAX_PINS, what="핀", code="too_many_pins")
        if not wanted:
            raise MapQueryError("no_pins", "핀이 하나는 있어야 한다.")
        excluded = self._tags(exclude, cap=MAX_EXCLUDE, what="제외 태그",
                              code="too_many_exclude")
        want_r, want_p = self._filters(idx, ratings, persons)
        try:
            seed_value = int(seed) if seed not in (None, "") else None
        except (TypeError, ValueError):
            seed_value = None
        try:
            result = idx.sample(
                wanted, exclude=excluded, ratings=want_r, persons=want_p,
                n=self._count(n, 5, MAX_SAMPLES), include_color=False,
                seed=seed_value)
        except ValueError as exc:
            raise MapQueryError("bad_request", str(exc)) from exc
        result["ok"] = True
        return result

    def describe(self, tag: str) -> dict[str, Any]:
        idx = self.index()
        name = str(tag or "").strip()
        if not name or len(name) > MAX_QUERY:
            raise MapQueryError("bad_request", "태그 이름이 잘못됐다.")
        info = idx.describe(name)
        if info is None:
            return {"ok": True, "status": "unknown_tag", "tag": name}
        return {"ok": True, "status": "matched", **info}

    def resolve_many(self, tags: Any) -> dict[str, Any]:
        """프롬프트에 든 태그 여러 개를 한 번에 맵 어휘로 푼다(Ctrl+E 패널의 씨앗 칩).

        돌려주는 것
          items        맵에 있는 것만. 가중치(`0.8::x ::`)·아티스트·품질어는 여기서 떨어진다.
          unknown      맵에 없는 것(화면이 "왜 안 뜨나" 를 답할 수 있게).
          person_group 인원 태그(1girl·solo...)로 정한 분면. ⚠️ 인원 태그는 **핀이 아니라
                       분면 필터**로 가야 한다 - 핀으로 꽂으면 `1girl+solo` 교집합 457만건에
                       1초가 들고 후보는 잡음인데, 분면으로 보내면 112ms 에 같은 답이 나온다
                       (실측 2026-09-12). 규칙은 core/tag_combo/person.py 가 SSOT 다.
        """
        from core.tag_combo.person import person_group_of

        idx = self.index()
        wanted = self._tags(tags, cap=64, what="태그", code="too_many_tags")
        items, unknown, population = [], [], []
        seen: set[str] = set()
        for raw in wanted:
            tid = idx.resolve(raw)
            if tid is None:
                unknown.append(raw)
                continue
            name = idx.by_id[tid]
            if name in seen:
                continue
            seen.add(name)
            role = idx.role.get(tid) or "unreviewed"
            if role == "population":
                population.append(name)
            items.append({"tag": name, "observed": idx.observed[tid], "role": role,
                          "role_label": ROLE_LABELS.get(role, ""), "lane": idx.lane.get(tid),
                          "group": self.group_of(tid),
                          "color_only": bool(idx.color[tid]),
                          "pinnable": bool(idx.eligible[tid]) and not idx.color[tid]
                          and role != "population"})
        group = person_group_of(population) if population else ""
        known = {name[2:] for name in idx.partitions}
        return {"ok": True, "items": items, "unknown": unknown, "population": population,
                "person_group": group if group in known else "",
                "person_label": PERSON_LABELS.get(group, "") if group in known else ""}
