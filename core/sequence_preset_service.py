"""Sequence (MVP) — 검증된 실제 parent-child 이벤트 그룹을 검색·서빙.

Dev0714 ``turbo_event_sequence`` 의 EventSearcher 모델을 헤드리스로 옮긴 것. 골격을
합성하지 않고, 채굴된 실제 그룹(parent + children = 한 시퀀스)을 **날것 그대로** 서빙한다.
변주(구체 행위/자세/의상/배경)는 데이터에 내재하므로 별도 합성·큐레이션이 없다.

데이터: ``data/sequence_preset/events_v1.parquet`` (tools/sequence_preset/build_events.py 산출).
  그룹 1행 = {group_id, peak_rating, frame_count, search_tags(전 프레임 태그 합집합),
  frames(JSON: [{i,id,rating,stage,tags}], stage 에스컬레이션 순)}.
  최소 필터(age_flag / 진짜 만화·멀티뷰 / ≥7컷)는 빌드 단계에서 이미 적용됨.

서빙:
  - search(): 태그 include/exclude + peak rating + 프레임 수로 그룹 검색(사용자 주도).
  - sequence(): 그룹 펼침 — 프레임별 미리보기.
  - generation_sources(): 프레임별 source_row → 라우트가 generate_from_source_row(PE 경유)로 생성.
정체성(artist/character/style)은 생성 시 PE 파이프라인이 공급한다.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

import pandas as pd

_log = logging.getLogger(__name__)

DATASET_RELPATH = Path("sequence_preset") / "events_v1.parquet"

RATING_SUFFIX_TAGS = {
    "g": "rating:general",
    "s": "rating:sensitive",
    "q": "rating:questionable",
    "e": "rating:explicit",
}
RATING_ORDER = {"g": 0, "s": 1, "q": 2, "e": 3}
RATING_LABELS = {"g": "General", "s": "Sensitive", "q": "Questionable", "e": "Explicit"}

STAGE_LABELS = {
    "baseline_presentation": "일상", "tease_exposure": "노출", "solo_stimulation": "솔로",
    "partnered_contact": "접촉", "oral_manual": "오럴", "penetration": "삽입",
    "release": "절정", "aftermath": "여운",
}

_MAX_LIMIT = 120

# 인원-카운트 태그 (g/s 검색 정규화용)
_GS_GIRL_COUNT = {"1girl", "2girls", "3girls", "4girls", "5girls", "6+girls", "multiple_girls"}
_GS_BOY_COUNT = {"1boy", "2boys", "3boys", "4boys", "5boys", "6+boys", "multiple_boys"}
_GS_PERSON_COUNT = _GS_GIRL_COUNT | _GS_BOY_COUNT


class SequencePresetService:
    """이벤트 그룹 데이터셋 로드 + 태그 검색 + 그룹 펼침 + 프레임 source_row 산출."""

    def __init__(self, repo_root: Path | str, *, data_root: Path | str | None = None):
        self.repo_root = Path(repo_root)
        self.data_root = Path(data_root) if data_root is not None else self.repo_root / "data"
        runtime_ds = self.data_root / DATASET_RELPATH
        repo_ds = self.repo_root / "data" / DATASET_RELPATH
        self.dataset_path = runtime_ds if runtime_ds.exists() else repo_ds

        self._df: Optional[pd.DataFrame] = None
        self._padded: Optional[pd.Series] = None       # " <search_tags> " (정확토큰 매칭용)
        self._person_padded: Optional[pd.Series] = None  # " <person cats> " (인원 OR 필터용)
        self._idx: dict[int, int] = {}                  # group_id -> row position
        self._load_error = ""
        self._load_ok = False                            # 로드 성공+데이터 有 (실패/빈 구분, Codex)

    # ------------------------------------------------------------------
    # 로드
    # ------------------------------------------------------------------

    def reload(self) -> bool:
        """다운로드 완료 등으로 데이터가 새로 생긴 경우 강제 재로드."""
        return self._ensure_loaded(force=True)

    def _ensure_loaded(self, *, force: bool = False) -> bool:
        # 성공 로드만 캐시 단축. 실패/미설치는 매번 재시도 → 다운로드/파일생성 후 자동 인식
        # (Codex: 실패가 ok=true 로 뒤집히지 않음 / sticky-failure 도 방지).
        if self._df is not None and self._load_ok and not force:
            return True
        # 다운로드 후 재로드 대비: 매 로드 시 경로 재확인 (runtime data_dir 우선, repo fallback)
        runtime_ds = self.data_root / DATASET_RELPATH
        self.dataset_path = runtime_ds if runtime_ds.exists() else (self.repo_root / "data" / DATASET_RELPATH)
        self._load_error = ""
        self._load_ok = False
        if not self.dataset_path.exists():
            self._load_error = f"Sequence dataset not found: {self.dataset_path}"
            self._df = pd.DataFrame(columns=["group_id", "peak_rating", "frame_count",
                                             "search_tags", "frames"])
            return False
        try:
            df = pd.read_parquet(self.dataset_path)
        except Exception as exc:  # 손상 등
            self._load_error = f"Sequence dataset load failed: {exc}"
            self._df = pd.DataFrame(columns=["group_id", "peak_rating", "frame_count",
                                             "search_tags", "frames"])
            return False
        df = df.reset_index(drop=True)
        df["group_id"] = df["group_id"].astype("int64")
        df["frame_count"] = df["frame_count"].astype("int64")
        df["peak_rating"] = df["peak_rating"].astype(str)
        df["search_tags"] = df["search_tags"].astype(str)
        df = self._filter_gs_coherent(df).reset_index(drop=True)  # g/s 여성-인원 비일관 그룹 드롭
        self._df = df
        self._padded = " " + df["search_tags"] + " "
        if "person" in df.columns:
            df["person"] = df["person"].astype(str)
            self._person_padded = " " + df["person"] + " "
        else:
            self._person_padded = None
        self._idx = {int(g): i for i, g in enumerate(df["group_id"].values)}
        self._load_ok = len(df) > 0
        return self._load_ok

    @staticmethod
    def _filter_gs_coherent(df: pd.DataFrame) -> pd.DataFrame:
        """g/s 그룹 중 **여성(주체) 인원이 프레임마다 다른** 비일관 변주덤프를 드롭.

        g/s 는 danbooru sibling 변주셋이라, 여성 인원이 바뀌는 건 의미있는 진행이 아니라
        '부모의 잡다한 자식들'(예: 1girl 프레임 + 6+girls 프레임)이다. 이게 union 검색에서
        '1girl' 에 6+girls 그룹을 끌어와 카드가 엉킨다. → 전 프레임 girl-count 가 동일한
        그룹만 유지(측정상 g/s 의 95%). 남성(파트너) 추가는 진행으로 허용(boy 변화는 무관).
        q/e(검증 진행, 여캐 상수)는 전량 유지. 로드 시 적용 — 파일/재업로드 불필요.
        """
        if "frames" not in df.columns or not len(df):
            return df
        peaks = df["peak_rating"].tolist()
        frames_col = df["frames"].tolist()
        keep = [True] * len(df)
        for i in range(len(df)):
            if peaks[i] not in ("g", "s"):
                continue  # q/e 유지
            try:
                frames = json.loads(frames_col[i])
            except Exception:
                keep[i] = False  # 손상은 드롭
                continue
            girl_sigs = {frozenset(t for t in fr.get("tags", []) if t in _GS_GIRL_COUNT)
                         for fr in frames}
            if len(girl_sigs) > 1:
                keep[i] = False  # 여성 인원 비일관 → 드롭
        return df[pd.Series(keep, index=df.index)]

    # ------------------------------------------------------------------
    # 입력 파싱
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_terms(value: Any) -> list[str]:
        """쉼표 구분 태그 → 정규화(소문자, 내부 공백→밑줄) 토큰 목록. danbooru 형태."""
        if isinstance(value, list):
            raw = value
        else:
            raw = str(value or "").split(",")
        out: list[str] = []
        for t in raw:
            tok = str(t).strip().lower().replace(" ", "_")
            if tok:
                out.append(tok)
        return out

    @staticmethod
    def _safe_int(value: Any, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    # ------------------------------------------------------------------
    # 공개 API
    # ------------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        ok = self._ensure_loaded()  # 캐시 사용 — status 폴링마다 62MB 재로드 금지 (Codex G)
        df = self._df if self._df is not None else pd.DataFrame()
        peak = (df["peak_rating"].value_counts().to_dict() if len(df) else {})
        return {
            "ok": ok,
            "datasetPath": str(self.dataset_path),
            "error": self._load_error if not ok else "",
            "groupCount": int(len(df)),
            "peakDistribution": {k: int(v) for k, v in peak.items()},
            "ratings": [r for r in ("e", "q", "s", "g") if r in peak],
            "dataAvailability": {"data": "ready" if ok else "missing"},
        }

    def search(self, payload: dict[str, Any]) -> dict[str, Any]:
        """태그 검색 → 매칭 그룹 요약(페이지네이션). 사용자 주도 검색."""
        payload = payload if isinstance(payload, dict) else {}
        self._ensure_loaded()
        df = self._df
        if df is None or len(df) == 0:
            return {"ok": False, "total": 0, "groups": [], "status": self.status()}

        include = self._parse_terms(payload.get("include"))
        exclude = self._parse_terms(payload.get("exclude"))
        ratings = [r for r in (payload.get("ratings") or []) if r in RATING_ORDER]
        person = [str(p).strip().lower() for p in (payload.get("person") or []) if str(p).strip()]
        cuts = [c for c in (self._safe_int(c, 0) for c in (payload.get("frameCounts") or [])) if c > 0]
        min_frames = self._safe_int(payload.get("minFrames"), 0)  # 0 = 하한 없음 (데이터가 이미 ≥2)
        max_frames = self._safe_int(payload.get("maxFrames"), 0)  # 0 = 무제한
        limit = max(1, min(_MAX_LIMIT, self._safe_int(payload.get("limit"), 60)))
        offset = max(0, self._safe_int(payload.get("offset"), 0))
        randomize = bool(payload.get("random"))

        hits = df[self._build_mask(df, include, exclude, ratings, person, cuts, min_frames, max_frames)]
        total = int(len(hits))
        if randomize and total:
            hits = hits.sample(min(limit, total))
        else:
            # 프레임 많은(풍부한) 그룹 먼저, 그다음 peak 높은 순
            hits = hits.assign(_ro=hits["peak_rating"].map(RATING_ORDER).fillna(0)) \
                       .sort_values(["frame_count", "_ro", "group_id"],
                                    ascending=[False, False, True])
            hits = hits.iloc[offset:offset + limit]

        groups = [self._group_summary(row) for _, row in hits.iterrows()]
        return {
            "ok": True,
            "total": total,
            "offset": 0 if randomize else offset,
            "limit": limit,
            "groups": groups,
            "status": {"groupCount": int(len(df))},
        }

    def _build_mask(self, df, include, exclude, ratings, person, cuts, min_frames, max_frames):
        """검색/랜덤픽 공통 매칭 마스크 (정확토큰 contains + rating + person OR + 컷)."""
        mask = pd.Series(True, index=df.index)
        for t in include:
            mask &= self._padded.str.contains(" " + t + " ", regex=False)
        for t in exclude:
            mask &= ~self._padded.str.contains(" " + t + " ", regex=False)
        if ratings:
            mask &= df["peak_rating"].isin(ratings)
        if person and self._person_padded is not None:
            pmask = pd.Series(False, index=df.index)
            for p in person:
                pmask |= self._person_padded.str.contains(" " + p + " ", regex=False)
            mask &= pmask  # 인원은 선택 칩 OR (등급/태그와는 AND)
        if cuts:
            mask &= df["frame_count"].isin(cuts)  # 컷 멀티선택 (정확 일치)
        else:
            if min_frames > 0:
                mask &= df["frame_count"] >= min_frames
            if max_frames > 0:
                mask &= df["frame_count"] <= max_frames
        return mask

    def pick_random_group(self, payload: dict[str, Any], *, exclude_group_id: Any = None) -> dict[str, Any]:
        """검색 필터(payload)에 매칭되는 **전체 셋**에서 그룹 1개를 무작위로 뽑는다(표시 60건 아님).
        Auto Gen 연속 시퀀스의 다음 라운드 선택용. exclude_group_id 로 직전 그룹 즉시 반복 회피."""
        payload = payload if isinstance(payload, dict) else {}
        self._ensure_loaded()
        df = self._df
        if df is None or len(df) == 0:
            return {"ok": False, "total": 0, "groupId": None, "error": self._load_error or "no data"}
        include = self._parse_terms(payload.get("include"))
        exclude = self._parse_terms(payload.get("exclude"))
        ratings = [r for r in (payload.get("ratings") or []) if r in RATING_ORDER]
        person = [str(p).strip().lower() for p in (payload.get("person") or []) if str(p).strip()]
        cuts = [c for c in (self._safe_int(c, 0) for c in (payload.get("frameCounts") or [])) if c > 0]
        min_frames = self._safe_int(payload.get("minFrames"), 0)
        max_frames = self._safe_int(payload.get("maxFrames"), 0)
        hits = df[self._build_mask(df, include, exclude, ratings, person, cuts, min_frames, max_frames)]
        total = int(len(hits))
        if total == 0:
            return {"ok": False, "total": 0, "groupId": None, "error": "no matching groups"}
        pool = hits
        if exclude_group_id is not None and total > 1:
            pool = hits[hits["group_id"] != int(exclude_group_id)]
            if len(pool) == 0:
                pool = hits
        one = pool.sample(1).iloc[0]
        return {"ok": True, "total": total, "groupId": int(one["group_id"])}

    def _group_summary(self, row: pd.Series) -> dict[str, Any]:
        frames = self._load_frames(row)
        peak = str(row["peak_rating"])
        # 카드 미리보기 = 마지막(절정) 프레임의 대표 scene 태그
        last_tags = frames[-1]["tags"] if frames else []
        return {
            "groupId": int(row["group_id"]),
            "peakRating": peak,
            "peakLabel": RATING_LABELS.get(peak, peak),
            "frameCount": int(row["frame_count"]),
            "person": str(row.get("person", "") or "").split(),
            "stages": [f["stage"] for f in frames],
            "preview": ", ".join(t.replace("_", " ") for t in last_tags[:10]),
        }

    @staticmethod
    def _load_frames(row: pd.Series) -> list[dict[str, Any]]:
        try:
            frames = json.loads(row["frames"])
        except Exception as exc:  # 손상 frames JSON — search 요약은 견고하게 [], 단 경고 로깅 (Codex)
            _log.warning("Sequence: corrupt frames JSON for group %s: %s", row.get("group_id"), exc)
            return []
        return frames if isinstance(frames, list) else []

    def _find_group(self, group_id: int) -> tuple[pd.Series, list[dict[str, Any]]]:
        self._ensure_loaded()
        pos = self._idx.get(int(group_id))
        if pos is None:
            raise KeyError(f"Sequence group not found: {group_id}")
        row = self._df.iloc[pos]
        return row, self._load_frames(row)

    def sequence(self, payload: dict[str, Any]) -> dict[str, Any]:
        """그룹 펼침 — 프레임별 (rating, stage, 미리보기 프롬프트)."""
        payload = payload if isinstance(payload, dict) else {}
        group_id = self._safe_int(payload.get("groupId"), -1)
        if group_id < 0:
            raise ValueError("groupId is required.")
        row, frames = self._find_group(group_id)
        if not frames:  # 손상된 frames JSON = 데이터 오류로 표면화 (Codex E, 빈 성공 금지)
            raise RuntimeError(f"Sequence group {group_id} has no valid frames (corrupt data).")
        out_frames = [{
            "index": f.get("i", i),
            "rating": f.get("rating", row["peak_rating"]),
            "stage": f.get("stage", ""),
            "stageLabel": STAGE_LABELS.get(f.get("stage", ""), f.get("stage", "")),
            "preview": self._frame_general(f.get("tags", []), f.get("rating", row["peak_rating"])),
        } for i, f in enumerate(frames)]
        return {
            "ok": True,
            "group": self._group_summary(row),
            "frames": out_frames,
        }

    @staticmethod
    def _frame_general(tags: list[str], rating: str) -> str:
        """프레임 프롬프트 = 실제 scene 태그(공백형, 중복 제거) + rating suffix.
        정체성(artist/character/style)은 생성 시 PE 파이프라인이 공급."""
        out: list[str] = []
        seen: set[str] = set()
        for t in tags:
            disp = str(t).replace("_", " ").strip()
            key = disp.lower()
            if disp and key not in seen:
                seen.add(key)
                out.append(disp)
        suffix = RATING_SUFFIX_TAGS.get(rating, "")
        if suffix and suffix.lower() not in seen:
            out.append(suffix)
        return ", ".join(out)

    def generation_sources(self, payload: dict[str, Any]) -> dict[str, Any]:
        """generate 요청 → 프레임별 source_row. enqueue 는 라우트가 수행 (Refine/Event Preset 패턴)."""
        payload = payload if isinstance(payload, dict) else {}
        group_id = self._safe_int(payload.get("groupId"), -1)
        if group_id < 0:
            raise ValueError("groupId is required.")
        row, frames = self._find_group(group_id)
        if not frames:  # 손상 데이터 표면화 (Codex E)
            raise RuntimeError(f"Sequence group {group_id} has no valid frames (corrupt data).")
        total = len(frames)
        sources: list[dict[str, Any]] = []
        for i, f in enumerate(frames):
            rating = f.get("rating", str(row["peak_rating"]))
            general = self._frame_general(f.get("tags", []), rating)
            sources.append({
                "sourceRow": {
                    "general": general,
                    "rating": rating,
                    "sequence_group_id": int(group_id),
                    "sequence_frame_index": i,
                    "sequence_frame_total": total,
                },
                "index": i,
                "stage": f.get("stage", ""),
                "rating": rating,
                "prompt": general,
            })
        return {
            "ok": True,
            "groupId": int(group_id),
            "groupName": f"group #{group_id}",
            "peakRating": str(row["peak_rating"]),
            "total": total,
            "sources": sources,
        }
