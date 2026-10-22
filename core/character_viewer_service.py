"""Server-side Character Viewer data and prompt helpers."""

from __future__ import annotations

import json
import math
import re
import threading
import zipfile
import zlib
from contextlib import contextmanager

from core.character_preview_pack import read_manifest
from pathlib import Path
from typing import Any
from urllib.parse import quote


class CharacterViewerService:
    GROUP_ALL = "__ALL__"
    # [최신] 토글이 남기는 데뷔 하한의 기본값. 산출물에 적힌 값이 우선한다.
    RECENT_SINCE = "2025-01"
    # 작품 칩은 이만큼만 낸다 - 줄 하나에 들어가는 수다.
    SCOPE_CHIP_LIMIT = 12
    DEFAULT_PREFIX = "1girl, artist:rento (rukeai), solo, cowboy shot, standing"
    DEFAULT_POSTFIX = (
        "simple background, white background, very aesthetic, extremely absurdres, "
        "amazing quality, masterpiece, year 2024"
    )
    TAG_REPLACE = {"loli": "young female"}
    TAG_EXCLUDE = {"mature female"}
    # 여성 기준 태그 - 머리말이 girl 이 아니면(boy · other) 싣지 않는다. 명시 집합이다: `chest` 로 끝나는 것을 다
    # 지우면 `scar on chest` 같은 특징까지 사라진다(Codex 리뷰 2026-10-21).
    FEMALE_ONLY_TAGS = frozenset({"flat chest", "small breasts", "medium breasts", "large breasts", "huge breasts",
                                  "gigantic breasts", "young female"})
    # 메인 프롬프트(Prefix)의 인원 태그 - 캐릭터 머리말과 맞춘다(girl -> 1girl · boy -> 1boy · other -> 1other).
    HEAD_COUNT_TAGS = {"girl": "1girl", "boy": "1boy", "other": "1other"}
    # Danbooru 인원 태그 전부(1girl · 2boys · 6+others · multiple girls ...) - Prefix 의 구성을 셀 때 쓴다.
    _PERSON_COUNT = re.compile(r"^(?:\d\+?(?:girls?|boys?|others?)|multiple (?:girls|boys|others))$")
    # 작품명 규칙(사용자 NAI 재현 실험 2026-10-19 · docs/character_pool_survey_2026_10_19/COPYRIGHT_WEIGHT_RULE.md).
    # 게시물 수 = 엔트리의 `danbooru_posts`(tools/annotate_character_posts.py 가 적는다).
    ORIGINAL_GROUP = "original"
    # 이름의 `(blue archive)` 가 BA 특유 화풍을 끌어온다(팬들이 그 작화로 그린다) - 음수로 상쇄한다. BA 만.
    NEGATIVE_COPYRIGHT = {"blue archive": -1.0}
    # 붙이는 작품명 = 엔트리 `copyright`(그 캐릭터의 작품 - 그룹이 아니다 · tools/annotate_character_posts.py). 이름 끝 괄호가
    # 그 작품이면(`work_in_name`) 음수로 - `roll (mega man), -0.7::mega man (series) ::`(사용자 결정 2026-10-19). BA 만 -1(위).
    # 랜덤 슬롯에서 괄호를 걷으면 +0.5 로 바뀐다.
    SERIES_TAIL_WEIGHT = -0.7
    SERIES_BARE_WEIGHT = 0.5
    THUMB_MAX_SIZE = (896, 1152)

    def __init__(
        self,
        root: Path | str,
        *,
        data_root: Path | str | None = None,
        save_root: Path | str | None = None,
        thumbnail_root: Path | str | None = None,
    ):
        self.root = Path(root)
        self.data_dir = Path(data_root) if data_root is not None else self.root / "data"
        self.save_dir = Path(save_root) if save_root is not None else self.root / "save"
        self.groups_path = self.data_dir / "copyright_groups.json"
        self.analysis_path = self.data_dir / "character_analysis.json"
        # 캐릭터 프리셋 사전(tools/build_character_presets.mjs 산출물).
        # 캐릭터마다 대표 태그를 Interactive 슬롯으로 미리 갈라 둔 것이라
        # `character_analysis.json` 과 같은 번들 데이터 루트에 있다.
        self.presets_path = self.data_dir / "character_presets.json"
        # 캐릭터가 코퍼스에 **처음 나타난 달**(tools/build_character_debut.py 산출물).
        # 코퍼스 자체(`data/tags/*.parquet` 1.4GB)는 배포본에 없고 사용자가 따로
        # 내려받는 것이라, 요약해 둔 이 파일만 번들 데이터 루트에 둔다.
        self.debut_path = self.data_dir / "character_debut.json"
        # 번들 미리보기 팩(폴백). 사용자 썸네일과 같은 성격이 아니라 **배포에 딸려오는**
        # 것이라 번들 데이터 루트에 둔다 — 업데이트 때 갱신되는 것이 맞다.
        self.preview_path = self.data_dir / "character_preview_thumbs.json"
        # **썸네일만 사용자 데이터 루트로 뺀다 — `data_root` 를 통째로 바꾸면 안 된다.**
        # `data_dir` 은 번들 파일 두 개(`copyright_groups.json` 1.2MB,
        # `character_analysis.json` 28MB)와 공유되고 그것들은 리소스 트리에 있는 것이 맞다
        # (계약상 `provisioning: bundled`). 통째로 바꾸면 `data_available()` 이 False 가 되어
        # 탭이 죽고, `find_by_tag()` 를 쓰는 캐릭터 태그 툴팁까지 전 앱에서 사라진다.
        #
        # 썸네일은 사용자가 만든 것이라 설치 트리에 있으면 안 된다:
        #   · `runtime_write_policy.json` 이 `repository data/**` 를 금지한다
        #   · 포터블 업데이터는 `user-data` 만 보존하고 `resources/` 를 통째로 교체한다
        #     (`app/electron/main/main.cjs`) -> 업데이트 1회에 썸네일이 사라지고
        #     2회째에 백업까지 지워져 영구 소실된다
        #   · 마이그레이션(`core/data_migration_service.py:67`)은 이미 `user_root/data/
        #     character_thumbnails` 로 옮겨 놨다. 읽는 쪽만 어긋나 41장이 안 보였다
        # 선례: `EventPresetService` 의 data_root/thumbnail_root 분할,
        #       `ArtistThumbnailService` 의 mode_data_root.
        self.thumb_dir = (Path(thumbnail_root) if thumbnail_root is not None
                          else self.data_dir / "character_thumbnails")
        # 예전에 앱 트리로 써 둔 것. 최초 1회만 흡수한다(아래 `_adopt_legacy_thumbs`).
        self.legacy_thumb_dir = self.root / "data" / "character_thumbnails"
        self.extension_pack_path = self.thumb_dir.parent / "character_preview" / "character_pack.zip"
        self._extension_lock = threading.RLock()
        # 옵션 저장 = 읽기 -> 고치기 -> 쓰기. 창 둘(생성 설정 창 · Characters 탭)이 동시에 보내면 앞선 쓰기가 뒤 값을 덮는다(Codex 리뷰).
        self._options_lock = threading.Lock()
        self._extension_zip: zipfile.ZipFile | None = None
        self._extension_keys: dict[str, str] | None = None
        self._extension_rev = "0"
        self.thumb_index_path = self.thumb_dir / "index.json"
        self.tags_path = self.save_dir / "character_viewer_tags.json"
        # 도감 즐겨찾기. **사용자가 고른 것**이라 썸네일과 같은 이유로 save_dir(사용자
        # 데이터)에 둔다 - 번들 data_dir 에 쓰면 업데이트 한 번에 사라진다.
        # ⚠️ 슬롯 즐겨찾기(`character_settings.py` 의 프레임 `favorite` 플래그)와 **다른
        #    것**이다. 저건 지금 쓰는 슬롯의 별표고, 이건 도감 13,497명 중 고른 것이다.
        #    같은 낱말이라 헷갈리기 쉬우니 저장소도 이름도 갈라 둔다.
        self.favorites_path = self.save_dir / "character_viewer_favorites.json"
        # 숨김(사용자 지시 2026-10-19 - 랜덤 캐릭터 디버그 줄의 [숨김]) - 앞으로 검색(Find · 랜덤 와일드카드 · 캐릭터 탭)에
        # 나오지 않는다. Find 의 [제외] 목록에서 되돌린다. 즐겨찾기와 같은 꼴 · 같은 자리(사용자 데이터).
        self.hidden_path = self.save_dir / "character_viewer_hidden.json"
        self._groups: dict[str, Any] | None = None
        self._analysis: dict[str, Any] | None = None
        self._tag_index: dict[str, tuple[str, dict[str, Any]]] | None = None
        self._thumb_index: dict[str, str] | None = None
        self._preview_rev: str | None = None
        self._presets: dict[str, Any] | None = None
        self._preview_pack: dict[str, str] | None = None
        self._debut: dict[str, str] | None = None
        self._recent_since: str = ""
        self._favorites: set[str] | None = None
        self._hidden: set[str] | None = None
        self._hidden_lock = threading.Lock()     # 겹친 저장이 같은 .tmp 를 두고 다투지 않게(Codex 리뷰)
        # 특징 검색 색인(`feature_index`) - 낱말 -> {종류, 캐릭터 수} · 캐릭터 -> 그 캐릭터의 낱말 묶음.
        self._feature_vocab: dict[str, dict[str, Any]] | None = None
        self._feature_sets: dict[tuple[str, str], frozenset[str]] | None = None
        # 작품 색인 - 캐릭터마다 든 작품(그룹 · 그 캐릭터의 `copyright` · 웃 갈래 `parent_works`)과 작품별 캐릭터 수.
        self._work_sets: dict[tuple[str, str], frozenset[str]] | None = None
        self._work_totals: dict[str, int] | None = None
        self.aliases_path = self.data_dir / "tag_index" / "named_entity_aliases.json"
        self.preview_index_cache_path = (self.thumb_dir.parent / "character_preview" / "bundle-key-index.json"
                                         if thumbnail_root is not None else None)
        self._search_index = None
        self._search_build_lock = threading.Lock()
        self._source_lock = threading.RLock()
        self._source_generation = 0
        self._search_source_files = None
        self._search_user_files = {}
        self._search_preview_file = None
        self._search_versions = dict(favorites=0, hidden=0, thumbs=0, pack=0)
        self._group_count_cache = None

    def data_available(self) -> bool:
        return self.groups_path.exists() and self.analysis_path.exists()

    def _load_json(self, path: Path, fallback: Any) -> Any:
        if not path.exists():
            return fallback
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)

    def _load_source_cache(self, attribute, path, prepare=None):
        # Loading is deliberately outside the lock: requests must not wait for warmup.
        while True:
            with self._source_lock:
                cached = getattr(self, attribute)
                if cached is not None:
                    return cached
                self._refresh_search_sources()
                generation = self._source_generation
            loaded = self._load_json(path, {})
            with self._source_lock:
                self._refresh_search_sources()
                if generation != self._source_generation:
                    continue  # A late loader must never resurrect an invalidated source.
                if getattr(self, attribute) is None:
                    setattr(self, attribute, prepare(loaded) if prepare else loaded)
                return getattr(self, attribute)

    def groups(self) -> dict[str, Any]:
        return self._load_source_cache('_groups', self.groups_path)

    def analysis(self) -> dict[str, Any]:
        return self._load_source_cache('_analysis', self.analysis_path)

    def debut_index(self) -> dict[str, str]:
        """캐릭터 이름 -> 처음 나타난 달("YYYY-MM"). 파일이 없으면 빈 사전이다.

        ⚠️ 왼쪽 끝은 잘려 있다 - 코퍼스가 2015-12 에서 시작하므로 그 이전에 데뷔한
           캐릭터는 전부 그 달로 뭉친다. [최신] 은 **반대쪽 끝**만 보므로 무관하다.
        """
        def prepare(raw):
            table = raw.get("debut") if isinstance(raw, dict) else None
            since = raw.get("recent_since") if isinstance(raw, dict) else ""
            self._recent_since = str(since or self.RECENT_SINCE)
            return table if isinstance(table, dict) else {}
        return self._load_source_cache('_debut', self.debut_path, prepare)

    def recent_since(self) -> str:
        """[최신] 이 남기는 데뷔 하한. 산출물에 적힌 값을 따른다(없으면 기본값)."""
        self.debut_index()
        return self._recent_since or self.RECENT_SINCE

    def is_recent(self, name: str) -> bool:
        debut = self.debut_index().get(str(name or ""))
        # ⚠️ 모르는 캐릭터는 **최신이 아니다.** '모름' 과 '최근' 을 뭉개면 토글이
        #    코퍼스에 없는 336명을 함께 끌고 온다(실측).
        return bool(debut) and debut >= self.recent_since()

    def character_presets(self) -> dict[str, Any]:
        """캐릭터 프리셋 사전을 **한 번만** 읽어 캐시한다.

        파일이 3.9MB(9,738명)라 프론트로 통째로 내려보내지 않는다 — 팝업 한 번에
        필요한 것은 1KB 남짓이다. 서버에서 한 건씩 꺼내 주는 쪽이 맞는 이유:

          · Remote Web 은 LAN/Cloudflared 로 휴대폰에서도 열린다. 프리셋 팝업을 한 번도
            안 여는 세션까지 4MB 를 받게 하면 첫 화면이 그만큼 늦어진다.
          · 이 서비스는 이미 `character_analysis.json`(28MB)을 같은 방식으로 물고 있다.
            파생 사전 하나가 더 붙는 것은 같은 성격의 비용이고, **처음 요청될 때까지
            읽지 않는다**(파싱 0.19s / 상주 약 24MB, 실측).
          · 프론트 캐시(IndexedDB 등)로 내리면 사전이 바뀔 때 무효화 규약을 따로 만들어야
            한다. 서버가 들고 있으면 파일을 갈아끼우고 재시작하는 것으로 끝난다.
        """
        if self._presets is None:
            data = self._load_json(self.presets_path, {})
            presets = data.get("presets") if isinstance(data, dict) else None
            self._presets = presets if isinstance(presets, dict) else {}
        return self._presets

    def presets_available(self) -> bool:
        return self.presets_path.exists()

    def character_preset(self, group_key: str, name: str) -> dict[str, Any]:
        """한 캐릭터의 슬롯 배정표. 사전에 없으면 KeyError."""
        group_key = str(group_key or "")
        name = str(name or "")
        if not group_key or not name:
            raise ValueError("group and character are required")
        if not self.presets_available():
            raise FileNotFoundError(
                "character_presets.json not installed "
                "(tools/build_character_presets.mjs 로 생성)"
            )
        entry = self.character_presets().get(f"{group_key}::{name}")
        if not isinstance(entry, dict):
            raise KeyError(f"Preset not found: {group_key}::{name}")
        return {
            "key": f"{group_key}::{name}",
            "work": str(entry.get("work") or group_key),
            "name": str(entry.get("name") or name),
            "rows": int(entry.get("rows", 0) or 0),
            "slots": entry.get("slots") if isinstance(entry.get("slots"), dict) else {},
            "off": entry.get("off") if isinstance(entry.get("off"), list) else [],
        }

    def find_by_tag(self, tag: str) -> tuple[str, dict[str, Any]] | None:
        normalized = re.sub(r"\\([()])", r"\1", str(tag or "")).strip().lower()
        if not normalized:
            return None
        if self._tag_index is None:
            index: dict[str, tuple[str, dict[str, Any]]] = {}
            try:
                analysis = self.analysis()
            except Exception:
                self._tag_index = index
                return None
            if isinstance(analysis, dict):
                for group_key, chars in analysis.items():
                    if not isinstance(chars, dict):
                        continue
                    for char_name, data in chars.items():
                        if not isinstance(data, dict):
                            continue
                        key = str(char_name or "").strip().lower()
                        if not key:
                            continue
                        current = index.get(key)
                        try:
                            total_rows = int(data.get("total_rows", 0) or 0)
                        except Exception:
                            total_rows = 0
                        try:
                            current_rows = int(current[1].get("total_rows", 0) or 0) if current else -1
                        except Exception:
                            current_rows = -1
                        if current is None or total_rows > current_rows:
                            index[key] = (str(group_key), data)
            self._tag_index = index
        return self._tag_index.get(normalized)

    def profile_summary(self, tag: str) -> dict[str, Any]:
        """태그 하나의 **구성요소** 요약. 못 찾으면 빈 dict.

        Tag Search 의 설명 칸이 쓴다 - 캐릭터에는 설명글이 없고, 대신 "어떤 특징으로
        이루어져 있는가" 가 답이다. 뷰어가 칩으로 그리는 것과 **같은 값**이다
        (`build_detail` 의 `sections.personal_color` / `characteristics`).
        """
        found = self.find_by_tag(tag)
        if not found:
            return {}
        group_key, data = found
        color, traits, _attire = self._variant_items(data, None)
        return {
            "group": str(group_key or ""),
            "gender": str(data.get("gender") or ""),
            "rows": int(data.get("total_rows", 0) or 0),
            "personal_color": [self._format_entry(entry) for entry in color],
            "characteristics": [self._format_entry(entry) for entry in traits],
        }

    def _adopt_legacy_thumbs(self) -> None:
        """앱 트리에 써 둔 옛 썸네일을 사용자 루트로 **한 번만 복사**한다.

        양쪽을 합쳐 읽지 않는 이유: DELETE 와 충돌한다. 레거시에만 있는 키를 지우면
        런타임 index 에서만 빠지고 다음 실행에서 되살아난다(툼스톤 없이는 못 막는다).
        한 번 흡수한 뒤에는 사용자 루트가 유일한 출처다.

        레거시는 지우지 않는다 — `core/data_migration_service.py` 의 비파괴 원칙과 같다.
        런타임 쪽에 index 가 이미 있으면(마이그레이션분 41장) 아무것도 하지 않는다.
        """
        try:
            if self.thumb_dir == self.legacy_thumb_dir:
                return
            if self.thumb_index_path.exists():
                return
            legacy_index = self.legacy_thumb_dir / "index.json"
            if not legacy_index.exists():
                return
            import shutil
            self.thumb_dir.mkdir(parents=True, exist_ok=True)
            for src in self.legacy_thumb_dir.glob("*.webp"):
                dst = self.thumb_dir / src.name
                if not dst.exists():
                    shutil.copy2(src, dst)
            shutil.copy2(legacy_index, self.thumb_index_path)
        except Exception:
            # 흡수 실패가 탭을 죽이면 안 된다 — 빈 index 로 계속 간다.
            pass

    def thumb_index(self) -> dict[str, str]:
        if self._thumb_index is None:
            self._adopt_legacy_thumbs()
            self._thumb_index = self._load_json(self.thumb_index_path, {})
        return self._thumb_index

    def reload_thumbnails(self) -> None:
        self._thumb_index = None
        self._invalidate_search("thumbs")

    def load_options(self) -> dict[str, Any]:
        data = self._load_json(self.tags_path, {})
        return {
            "prefix": data.get("prefix", self.DEFAULT_PREFIX),
            "postfix": data.get("postfix", self.DEFAULT_POSTFIX),
            "cosplay_enabled": bool(data.get("cosplay_enabled", False)),
            "cosplay_name": str(data.get("cosplay_name", "")),
            "auto_copyright": bool(data.get("auto_copyright", True)),
            "auto_characteristics": bool(data.get("auto_characteristics", True)),
            "hide_charname": bool(data.get("hide_charname", False)),
            "no_save": bool(data.get("no_save", False)),
            "thumb_first": bool(data.get("thumb_first", data.get("empty_thumb_only", True))),
            "empty_thumb_only": bool(data.get("empty_thumb_only", True)),
            # 가상 캐릭터 슬롯의 **추가 프롬프트**(사용자 결정 2026-10-22) - 캐릭터를 바꿔도 남는다 · 캐릭터 줄 뒤에 붙는다.
            "character_extra": str(data.get("character_extra", "")),
        }

    def save_options(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._options_lock:
            return self._save_options_locked(payload)

    def _save_options_locked(self, payload: dict[str, Any]) -> dict[str, Any]:
        current = self.load_options()
        for key in (
            "prefix",
            "postfix",
            "cosplay_name",
            "cosplay_enabled",
            "auto_copyright",
            "auto_characteristics",
            "hide_charname",
            "no_save",
            "thumb_first",
            "empty_thumb_only",
            "character_extra",
        ):
            if key in payload:
                current[key] = payload[key]
        self.save_dir.mkdir(parents=True, exist_ok=True)
        with open(self.tags_path, "w", encoding="utf-8") as handle:
            json.dump(current, handle, ensure_ascii=False, indent=2)
        return current

    def _group_counts(self) -> list[tuple[str, int]]:
        while True:
            with self._source_lock:
                self._refresh_search_sources()
                if self._group_count_cache is not None:
                    return self._group_count_cache
                generation = self._source_generation
            out: list[tuple[str, int]] = []
            for group_key, data in self.groups().items():
                if str(group_key).startswith("_") or not isinstance(data, dict):
                    continue
                total = len(data.get("girl", []) or []) + len(data.get("boy", []) or [])
                out.append((group_key, total))
            out.sort(key=lambda item: (-item[1], item[0].lower()))
            with self._source_lock:
                self._refresh_search_sources()
                if generation != self._source_generation:
                    continue  # Never publish counts from an invalidated dictionary.
                if self._group_count_cache is None:
                    self._group_count_cache = out
                return self._group_count_cache

    def state(self) -> dict[str, Any]:
        group_counts = self._group_counts()
        character_count = sum(1 for _ in self._iter_all_chars())
        thumbs = self.thumb_index()
        return {
            "available": self.data_available(),
            "group_count": len(group_counts),
            "character_count": character_count,
            "thumbnail_count": len(thumbs),
            "favorite_count": len(self.favorites()),
            "options": self.load_options(),
        }

    def build_groups(self, query: str = "", limit: int | None = None, offset: int = 0) -> dict[str, Any]:
        from core.character_search_index import normalize
        self._refresh_search_sources()
        query_text = normalize(query).lstrip("*").strip()
        terms = [t.strip().removeprefix("work:").strip() for t in query_text.split(",") if t.strip()]
        counts = self._group_counts()
        groups = [{"key": self.GROUP_ALL, "name": "All", "count": sum(c for _, c in counts)}]
        groups.extend({"key": key, "name": key, "count": count} for key, count in counts
                      if all(term in normalize(key) for term in terms))
        total = len(groups)
        offset = max(0, int(offset))
        end = None if limit is None else offset + max(0, int(limit))
        return {"items": groups[offset:end], "total": total, "offset": offset, "limit": limit}

    def _iter_all_chars(self):
        for group_key, chars in self.analysis().items():
            if not isinstance(chars, dict):
                continue
            for name, data in chars.items():
                if isinstance(data, dict):
                    yield group_key, name, data

    @staticmethod
    def _tag_search_str(data: dict[str, Any]) -> str:
        parts: list[str] = []
        for entry in data.get("personal_color", []) or []:
            if entry.get("tag"):
                parts.append(str(entry["tag"]))
        for entry in data.get("characteristics", []) or []:
            if entry.get("tag"):
                parts.append(str(entry["tag"]))
        dist = (data.get("breast_size", {}) or {}).get("distribution", []) or []
        if dist:
            top = max(dist, key=lambda entry: entry.get("count", 0))
            if top.get("tag"):
                parts.append(str(top["tag"]))
        return ", ".join(parts)

    def _matches_query(self, name: str, data: dict[str, Any], query: str) -> bool:
        raw = str(query or "").strip().lower()
        if not raw:
            return True
        exact = raw.startswith("*")
        body = raw[1:].strip() if exact else raw
        if not body:
            return True
        # 콤마로 다중어를 분리해 '모든' term이 매칭돼야 한다(AND) — 사용자 리포트: "blonde hair,
        # flat chest" 처럼 여러 태그로 검색 가능. 각 term은 공백을 포함할 수 있어 콤마로만 나눈다
        # ("blonde hair"가 "blonde"+"hair"로 쪼개지면 안 됨). 콤마가 없으면 term 1개 → 기존 단일
        # 부분문자열 동작과 동일(하위호환).
        terms = [term.strip() for term in body.split(",") if term.strip()]
        if not terms:
            return True
        display = name.lower()
        tag_str = self._tag_search_str(data).lower()
        if exact:
            tags = {part.strip().lower() for part in tag_str.split(",") if part.strip()}
            # 각 term의 선행 '*'도 허용한다(예: "*a, *b"). 쿼리 전체의 '*'로 이미 exact 모드이므로
            # term별 잔여 '*'는 떼고 정확 매칭한다(콤마 split 이 첫 '*'만 떼어내는 점 보완).
            cleaned = [term[1:].strip() if term.startswith("*") else term for term in terms]
            return all(
                bool(re.search(r"\b" + re.escape(term) + r"\b", display)) or term in tags
                for term in cleaned
                if term
            )
        return all(term in display or term in tag_str for term in terms)

    # ── 특징 검색 · 제외(사용자 지시 2026-10-19) ─────────────────────────
    #
    # Find 의 [특징 검색] 은 **이 데이터에 있는 낱말만** 고른다(Artist Thumbnail 검색칸과 같은 규칙 - 시스템이
    # 아는 태그가 아주 제한적이라 먼저 그 안에서 찾게 한다). 낱말 = 캐릭터마다
    #   · 머리 · 눈 색(`personal_color`)          -> 종류 'color'
    #   · 특징(`characteristics` - 그 캐릭터 그림의 20% 이상)  -> 'feature'
    #   · 가장 많은 가슴 크기 하나(`_tag_search_str` 와 같은 잣대) -> 'breast'
    #   · 작품(그룹 키)                            -> 'work'
    # 고른 낱말은 **정확히 같을 때만** 맞는다(부분 글자로 맞추면 '-red' 가 red eyes 까지 뺀다).

    FEATURE_KIND_LABELS = {"color": "색", "feature": "특징", "breast": "가슴", "work": "작품"}

    @staticmethod
    def _norm_feature(value: Any) -> str:
        return " ".join(str(value or "").replace("_", " ").lower().split())

    def _top_breast(self, data: dict[str, Any]) -> str:
        dist = (data.get("breast_size", {}) or {}).get("distribution", []) or []
        if not dist:
            return ""
        return self._norm_feature(max(dist, key=lambda entry: entry.get("count", 0)).get("tag"))

    def feature_index(self) -> tuple[dict[str, dict[str, Any]], dict[tuple[str, str], frozenset[str]]]:
        """(낱말 -> {kind, count}, (작품, 이름) -> 낱말 묶음). 한 번 만들어 쥔다(13,497명 · 수십 ms)."""
        if self._feature_vocab is None or self._feature_sets is None:
            vocab: dict[str, dict[str, Any]] = {}
            sets: dict[tuple[str, str], frozenset[str]] = {}
            for group_key, name, data in self._iter_all_chars():
                own: set[str] = set()
                for kind, entries in (("color", data.get("personal_color")), ("feature", data.get("characteristics"))):
                    for entry in entries or []:
                        tag = self._norm_feature(entry.get("tag") if isinstance(entry, dict) else "")
                        if tag:
                            own.add(tag)
                            vocab.setdefault(tag, {"kind": kind, "count": 0})
                breast = self._top_breast(data)
                if breast:
                    own.add(breast)
                    vocab.setdefault(breast, {"kind": "breast", "count": 0})
                for tag in own:
                    vocab[tag]["count"] += 1
                sets[(group_key, name)] = frozenset(own)
            self._feature_vocab, self._feature_sets = vocab, sets
        return self._feature_vocab, self._feature_sets

    def _work_index(self) -> tuple[dict[tuple[str, str], frozenset[str]], dict[str, int]]:
        """(캐릭터 -> 든 작품들, 작품 -> 캐릭터 수). 작품 = 그룹 + 그 캐릭터의 작품(`copyright`) + 웃 갈래(`parent_works` -
        `virtual youtuber` 처럼 하위 작품들을 묶는 것 · 사용자 지시 2026-10-19). original 은 그룹일 때만."""
        if self._work_sets is None or self._work_totals is None:
            sets: dict[tuple[str, str], frozenset[str]] = {}
            totals: dict[str, int] = {}
            for group_key, name, data in self._iter_all_chars():
                works = {self._norm_feature(group_key)}
                copyright_tag = str(data.get("copyright") or "").strip()
                if copyright_tag and copyright_tag != self.ORIGINAL_GROUP:
                    works.add(self._norm_feature(copyright_tag))
                for parent in data.get("parent_works") or []:
                    works.add(self._norm_feature(parent))
                works.discard("")
                sets[(group_key, name)] = frozenset(works)
                for work in works:
                    totals[work] = totals.get(work, 0) + 1
            self._work_sets, self._work_totals = sets, totals
        return self._work_sets, self._work_totals

    def _work_counts(self) -> dict[str, int]:
        return self._work_index()[1]

    def feature_suggest(self, query: str, ordered_tags: list[str] | None = None, limit: int = 20) -> dict[str, Any]:
        """검색칸 자동완성 - 이 데이터에 있는 낱말(색 · 특징 · 가슴 · 작품)만 낸다.

        ``ordered_tags`` 가 있으면(한글로 친 것을 태그 사전이 바꿔 준 차례) 그 차례대로 이 데이터에 있는 것만 고른다.
        없으면 친 글자로 찾는다 - 앞이 맞는 것 먼저, 그다음 중간이 맞는 것, 각각 캐릭터 수 많은 순.
        """
        self._refresh_search_sources()
        index = self._search_index or self.warm_search_index()
        if index is not None:
            vocab = index.feature_vocab
            works = {key: len(ids) for key, ids in index.works.items()}
        else:
            vocab, _sets = self.feature_index()
            works = self._work_counts()

        def row(tag: str) -> dict[str, Any] | None:
            if tag in vocab:
                kind, count = vocab[tag]["kind"], vocab[tag]["count"]
            elif tag in works:
                kind, count = "work", works[tag]
            else:
                return None
            return {"tag": tag, "kind": kind, "label": self.FEATURE_KIND_LABELS[kind], "count": count}

        limit = max(1, min(50, int(limit or 20)))
        rows: list[dict[str, Any]] = []
        if ordered_tags is not None:
            seen: set[str] = set()
            for raw in ordered_tags:
                tag = self._norm_feature(raw)
                if tag in seen:
                    continue
                seen.add(tag)
                item = row(tag)
                if item:
                    rows.append(item)
                if len(rows) >= limit:
                    break
            return {"rows": rows}
        q = self._norm_feature(query)
        if not q:
            return {"rows": []}
        names = list(vocab) + [key for key in works if key not in vocab]
        # 낱말 하나가 친 글자로 시작하면 앞줄(`ear` -> animal ears 1,689 가 ear piercing 28 보다 위), 중간이 맞으면 뒷줄.
        head = [tag for tag in names if any(word.startswith(q) for word in tag.split()) or tag.startswith(q)]
        head_set = set(head)
        middle = [tag for tag in names if q in tag and tag not in head_set]
        for bucket in (head, middle):
            items = [item for item in (row(tag) for tag in bucket) if item]
            items.sort(key=lambda item: (-item["count"], item["tag"]))
            rows.extend(items)
        return {"rows": rows[:limit]}

    def _feature_filter(self, include: list[str] | None, exclude: list[str] | None):
        """고른 낱말로 거르는 함수. 낱말이 없으면 None. ``work:`` 로 시작하면 작품이다.

        검색 줄: 특징은 **전부** 가져야 하고(AND), 작품은 그중 **하나**에 속하면 된다(한 캐릭터는 작품 하나).
        제외 줄: 특징 하나라도 가지면 빼고, 그 작품이면 뺀다.
        """
        def split(values: list[str] | None) -> tuple[set[str], set[str]]:
            tags, works = set(), set()
            for raw in values or []:
                text = str(raw or "").strip()
                if text.lower().startswith("work:"):
                    work = self._norm_feature(text[5:])
                    if work:
                        works.add(work)
                else:
                    tag = self._norm_feature(text)
                    if tag:
                        tags.add(tag)
            return tags, works

        inc_tags, inc_works = split(include)
        exc_tags, exc_works = split(exclude)
        if not (inc_tags or inc_works or exc_tags or exc_works):
            return None
        _vocab, sets = self.feature_index()

        work_sets, _totals = self._work_index()

        def keep(group_key: str, name: str) -> bool:
            own = sets.get((group_key, name), frozenset())
            # 한 캐릭터가 여러 작품에 든다(그룹 · 그 캐릭터의 작품 · 웃 갈래) - 그중 하나라도 맞으면 그 작품이다.
            works = work_sets.get((group_key, name)) or frozenset({self._norm_feature(group_key)})
            if inc_works and not (works & inc_works):
                return False
            if works & exc_works:
                return False
            return inc_tags <= own and not (exc_tags & own)

        return keep

    # ── 도감 즐겨찾기 ────────────────────────────────────────────────────
    #
    # 키는 썸네일·번들 폴백과 **같은 모양**(`group::name`)이다 - 한 캐릭터를 가리키는
    # 이름이 세 가지가 되면 어느 하나만 고치게 된다.

    def favorites(self) -> set[str]:
        if self._favorites is None:
            # ⚠️ **깨진 파일에 죽지 않는다.** 이건 사용자 데이터 루트의 파일이라
            #    중간에 전원이 나가거나 손으로 고치다 깨질 수 있는데, 그때 예외가
            #    올라가면 `build_list` 와 `state` 가 함께 죽어 **도감 탭이 통째로**
            #    안 뜬다. 별 몇 개를 잃는 것이 탭을 잃는 것보다 낫다.
            #    (번들 데이터를 읽는 `_load_json` 은 그대로 둔다 - 거기서 깨지는 것은
            #     배포가 잘못된 것이라 조용히 넘기면 안 된다.)
            try:
                raw = self._load_json(self.favorites_path, {})
            except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
                print(f"[warn] character favorites unreadable, starting empty: {exc}",
                      flush=True)
                raw = {}
            items = raw.get("favorites") if isinstance(raw, dict) else raw
            self._favorites = ({str(x) for x in items if isinstance(x, str) and x}
                               if isinstance(items, list) else set())
        return self._favorites

    def is_favorite(self, group_key: str, name: str) -> bool:
        return f"{group_key}::{name}" in self.favorites()

    def set_favorite(self, group_key: str, name: str, on: bool) -> dict[str, Any]:
        """별을 켜고 끈다. **없는 캐릭터는 거절한다** - 조용히 받아 두면 목록에 영영
        안 뜨는 유령이 쌓이고, 사용자는 즐겨찾기 수만 늘어난 것을 보게 된다."""
        self._get_character(group_key, name)          # 없으면 KeyError
        key = f"{group_key}::{name}"
        favorites = self.favorites()
        if on:
            favorites.add(key)
        else:
            favorites.discard(key)
        # ⚠️ **원자적으로 쓴다.** 곧바로 `"w"` 로 열면 쓰다 만 파일이 남을 수 있고,
        #    그 파일은 아래 `favorites()` 가 **빈 목록**으로 읽는다 - 그 뒤 별을 하나만
        #    눌러도 옛 별 전부가 그 한 개로 덮여 **영영 사라진다**(Fable 리뷰 2026-09-03).
        #    같은 파일의 `_write_thumb_index` 가 이미 tmp+replace 를 쓴다 - 그것을 따른다.
        self.save_dir.mkdir(parents=True, exist_ok=True)
        tmp_path = self.favorites_path.with_name(self.favorites_path.name + ".tmp")
        with open(tmp_path, "w", encoding="utf-8") as handle:
            json.dump({"favorites": sorted(favorites)}, handle, ensure_ascii=False, indent=1)
        tmp_path.replace(self.favorites_path)
        self._invalidate_search("favorites")
        return {
            "group": group_key,
            "character": name,
            "favorite": bool(on),
            "favorite_count": len(favorites),
        }

    # ── 숨김 ─────────────────────────────────────────────────────────────
    # 키 = 즐겨찾기와 같은 `group::name`. 깨진 파일에 죽지 않고 원자적으로 쓰는 것도 즐겨찾기와 같다.

    def hidden(self) -> set[str]:
        if self._hidden is None:
            try:
                raw = self._load_json(self.hidden_path, {})
            except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
                print(f"[warn] character hidden list unreadable, starting empty: {exc}", flush=True)
                raw = {}
            items = raw.get("hidden") if isinstance(raw, dict) else raw
            self._hidden = ({str(x) for x in items if isinstance(x, str) and x}
                            if isinstance(items, list) else set())
        return self._hidden

    def is_hidden(self, group_key: str, name: str) -> bool:
        return f"{group_key}::{name}" in self.hidden()

    def set_hidden(self, group_key: str, name: str, on: bool) -> dict[str, Any]:
        """숨김을 켜고 끈다. 없는 캐릭터는 거절한다(즐겨찾기와 같은 까닭)."""
        self._get_character(group_key, name)          # 없으면 KeyError
        key = f"{group_key}::{name}"
        with self._hidden_lock:
            hidden = set(self.hidden())
            if on:
                hidden.add(key)
            else:
                hidden.discard(key)
            self.save_dir.mkdir(parents=True, exist_ok=True)
            tmp_path = self.hidden_path.with_name(self.hidden_path.name + ".tmp")
            with open(tmp_path, "w", encoding="utf-8") as handle:
                json.dump({"hidden": sorted(hidden)}, handle, ensure_ascii=False, indent=1)
            tmp_path.replace(self.hidden_path)
            # 파일이 써진 뒤에야 메모리를 바꾼다 - 쓰다 실패하면 숨김도 없던 일이다.
            self._hidden = hidden
            self._invalidate_search("hidden")
        return {"group": group_key, "character": name, "hidden": bool(on), "hidden_count": len(hidden)}

    def hidden_items(self) -> list[dict[str, Any]]:
        """[제외] 목록 - 사전에서 사라진 키는 건너뛴다(파일에는 남긴다 - 사전이 돌아오면 다시 숨는다)."""
        items: list[dict[str, Any]] = []
        for key in sorted(self.hidden()):
            group_key, _, name = key.partition("::")
            data = (self.analysis().get(group_key) or {}).get(name)
            if not isinstance(data, dict):
                continue
            items.append({"group": group_key, "character": name,
                          "danbooru_posts": data.get("danbooru_posts"),
                          "thumbnail_url": self._thumb_url(group_key, name, size="grid")})
        return items

    def _thumb_key(self, group_key: str, name: str, variant_label: str = "") -> str:
        key = f"{group_key}::{name}"
        if variant_label:
            key += f"::{variant_label}"
        return key

    def _preview_revision(self) -> str:
        """번들 폴백 팩의 판. 앱 업데이트로 팩이 갈리면 폴백 URL 이 통째로 새로워진다."""
        if self._preview_rev is None:
            try:
                stat = self.preview_path.stat()
                self._preview_rev = f"{stat.st_mtime_ns}-{stat.st_size}"
            except OSError:
                self._preview_rev = "0"
        return self._preview_rev

    def thumbnail_source(self, group_key: str, name: str, variant_label: str = "") -> tuple[str, Path | None, str]:
        """썸네일 하나의 **실효 출처**: ``(kind, path, revision)``.

        kind 는 ``"user"`` / ``"fallback"`` / ``""``(없음). URL 의 ``v=`` 와 HTTP 캐시
        헤더가 **둘 다 여기서** 갈라진다.

        ⚠️ **revision 접두사(`u`/`p`)가 핵심이다.** mtime·크기가 우연히 같아도
        **폴백 -> 사용자 전환은 반드시 다른 URL** 이어야 한다. 그러지 않으면 브라우저가
        캐시한 폴백을 계속 쓴다 — 실제로 그래서 사용자가 만든 썸네일이 "소리없이
        사라졌다"(내용이 바뀌어도 URL 이 같은데 `max-age=3600` 이 걸려 있었다).

        ⚠️ 판정은 `has_thumbnail()` 과 **정의상 같다**(인덱스 항목이 있거나 팩에 있거나).
        인덱스가 가리키는데 파일이 없으면 그래도 ``"user"`` 를 유지한다 — 여기서만
        폴백으로 흘리면 두 값이 갈라져 `has_thumbnail=True` 인데 URL 이 빈 항목이
        생긴다(예전에 40개 중 7개). 그 경우 라우트가 404 를 주는 것은 종전과 같다.
        """
        group_key = str(group_key or "")
        name = str(name or "")
        variant_label = str(variant_label or "")
        filename = self.thumb_index().get(self._thumb_key(group_key, name, variant_label))
        if filename:
            try:
                path = self._resolve_thumb_file(str(filename))
                stat = path.stat()
            except (OSError, ValueError):
                return "user", None, "u0"
            return "user", path, f"u{stat.st_mtime_ns}-{stat.st_size}"
        # 확장 팩이 번들보다 먼저(사용자 결정 2026-10-22: 4.5 로 그린 번들 3,000 도 V5 로 통일 - 받은 사람은 V5 를 본다).
        if not variant_label and f"{group_key}::{name}" in self.extension_pack():
            return "fallback", None, f"e{self._extension_rev}"
        if not variant_label and f"{group_key}::{name}" in self.preview_pack():
            return "fallback", None, f"p{self._preview_revision()}"
        return "", None, ""

    def _thumb_url(self, group_key: str, name: str, variant_label: str = "", size: str = "") -> str:
        # 사용자 인덱스에 없어도 **번들 폴백이 있으면 URL 을 준다.** 라우트가 같은 우선순위로
        # 응답하기 때문이다. 여기서 사용자 인덱스만 보면 `has_thumbnail=True` 인데
        # `thumbnail_url` 이 빈 값인 항목이 생겨(실측 40개 중 7개) 프론트가 이니셜을 그린다.
        # 두 값은 항상 같은 판정을 써야 한다.
        kind, _path, revision = self.thumbnail_source(group_key, name, variant_label)
        if not kind:
            return ""
        params = f"group={quote(group_key, safe='')}&character={quote(name, safe='')}"
        if variant_label:
            params += f"&variant={quote(variant_label, safe='')}"
        if size:
            params += f"&size={quote(size, safe='')}"
        if revision:
            # 내용이 바뀔 때만 URL 이 바뀐다 -> 캐시를 살린 채 항상 최신을 본다.
            params += f"&v={quote(revision, safe='')}"
        return f"/api/character-viewer/thumbnail?{params}"

    def _serialize_list_item(
        self,
        index: int,
        group_key: str,
        name: str,
        data: dict[str, Any],
        thumbs: dict[str, str],
        include_thumbnail_url: bool = False,
        include_tags: bool = False,
        thumbnail_size: str = "",
    ) -> dict[str, Any]:
        item = {
            "index": int(index),
            "group": group_key,
            "character": name,
            "count": int(data.get("total_rows", 0) or 0),
            # 사용자 썸네일이 없어도 번들 폴백이 있으면 True — 그리드가 이니셜 대신
            # 그림을 청한다. 라우트가 같은 우선순위(사용자 -> 폴백)로 응답한다.
            "has_thumbnail": (self._thumb_key(group_key, name) in thumbs
                              or f"{group_key}::{name}" in self.preview_pack()
                              or f"{group_key}::{name}" in self.extension_pack()),
        }
        # 화면이 '요즘 캐릭터' 를 가릴 수 있게 함께 보낸다(모르면 빈 문자열).
        item["debut"] = self.debut_index().get(name, "")
        # 별 상태. 카드마다 따로 물으면 13,497번을 묻게 된다 - 목록에 실어 보낸다.
        item["favorite"] = f"{group_key}::{name}" in self.favorites()
        # 성별 girl / boy / other(머리말과 같은 잣대 - 화면이 줄마다 표시할 수 있게 · 2026-10-21).
        item["gender"] = self.prompt_head(data)
        if include_tags:
            item["tags"] = self._tag_search_str(data)
        if include_thumbnail_url:
            item["thumbnail_url"] = self._thumb_url(group_key, name, size=thumbnail_size)
        return item

    @staticmethod
    def _file_version(path):
        try:
            stat = path.stat()
            return (stat.st_size, stat.st_mtime_ns)
        except OSError:
            return (0, 0)

    def _invalidate_search(self, kind):
        self._search_versions[kind] += 1
        index = self._search_index
        if index is not None:
            index.invalidate(kind)

    def _refresh_search_sources(self):
        with self._source_lock:
            return self._refresh_search_sources_locked()

    def _refresh_search_sources_locked(self):
        paths = (self.analysis_path, self.groups_path, self.aliases_path, self.debut_path)
        versions = tuple(self._file_version(p) for p in paths)
        previous = self._search_source_files
        if previous is not None and previous != versions:
            self._source_generation += 1
            if previous[0] != versions[0]:
                self._analysis = None
                self._tag_index = None
                self._feature_vocab = self._feature_sets = None
                self._work_sets = self._work_totals = None
            if previous[1] != versions[1]:
                self._groups = None
            if previous[3] != versions[3]:
                self._debut = None
            self._search_index = None
            self._group_count_cache = None
        self._search_source_files = versions
        # Detect out-of-process edits as well as mutations through this service.
        for kind, path, attr in (('favorites', self.favorites_path, '_favorites'),
                                 ('hidden', self.hidden_path, '_hidden'),
                                 ('thumbs', self.thumb_index_path, '_thumb_index')):
            signature = self._file_version(path)
            old = self._search_user_files.get(kind)
            if old is not None and old != signature:
                setattr(self, attr, None)
                self._invalidate_search(kind)
            self._search_user_files[kind] = signature
        preview = self._file_version(self.preview_path)
        if self._search_preview_file is not None and preview != self._search_preview_file:
            self._preview_pack = None
            self._preview_rev = None
            self._invalidate_search('pack')
        self._search_preview_file = preview
        return versions

    def warm_search_index(self):
        from core.character_search_index import CharacterSearchIndex
        if not self._search_build_lock.acquire(blocking=False):
            return None
        try:
            with self._source_lock:
                versions = self._refresh_search_sources()
                generation = self._source_generation
            if self._search_index is None:
                built = CharacterSearchIndex(self, versions)
                # Invalidation and publication share the same generation and lock.
                with self._source_lock:
                    self._refresh_search_sources()
                    if generation == self._source_generation:
                        self._search_index = built
                        # Drop temporary legacy postings built during warmup.
                        self._feature_vocab = self._feature_sets = None
                        self._work_sets = self._work_totals = None
            return self._search_index
        finally:
            self._search_build_lock.release()

    def build_catalog(self):
        self._refresh_search_sources()
        index = self._search_index or self.warm_search_index()
        if index is None:
            return {'pending': True, 'version': None, 'groups': [], 'table': []}
        return index.catalog

    def build_list(self, group_key=GROUP_ALL, query='', page=0, per_page=48,
                   thumb_first=True, include_all=False, recent_only=False,
                   favorites_only=False, include=None, exclude=None, include_hidden=False,
                   genders=None, compact=False, offset=None, limit=None):
        self._refresh_search_sources()
        index = self._search_index or self.warm_search_index()
        args = (group_key, query, page, per_page, thumb_first, include_all and not compact, recent_only,
                favorites_only, include, exclude, include_hidden, genders)
        if index is not None:
            return index.build_list(self, *args, compact=compact, offset=offset, limit=limit)
        result = self._legacy_build_list(*args)
        if offset is not None or limit is not None:
            # The old path still serves requests while startup warmup is building.
            full = self._legacy_build_list(group_key, query, page, per_page, thumb_first,
                True, recent_only, favorites_only, include, exclude, include_hidden, genders)
            start = max(0, int(offset)) if offset is not None else result['page'] * result['per_page']
            size = result['per_page'] if limit is None else max(0, min(1000, int(limit)))
            result['items'] = [self._serialize_list_item(i, row['group'], row['character'],
                self._get_character(row['group'], row['character']), self.thumb_index(),
                include_thumbnail_url=True, thumbnail_size='grid')
                for i, row in enumerate(full['all_items'][start:start+size], start)]
            result.update(offset=start, limit=size)
        if compact:
            result.pop('all_items', None)
            result.update(pending=True, ids=None, catalog_version=None,
                          catalog_url='/api/character-viewer/catalog')
        return result

    def _legacy_build_list(
        self,
        group_key: str = GROUP_ALL,
        query: str = "",
        page: int = 0,
        per_page: int = 48,
        thumb_first: bool = True,
        include_all: bool = False,
        recent_only: bool = False,
        favorites_only: bool = False,
        include: list[str] | None = None,
        exclude: list[str] | None = None,
        include_hidden: bool = False,
        genders: list[str] | None = None,
    ) -> dict[str, Any]:
        if group_key == self.GROUP_ALL:
            chars = list(self._iter_all_chars())
        else:
            chars = [
                (group_key, name, data)
                for name, data in (self.analysis().get(group_key, {}) or {}).items()
                if isinstance(data, dict)
            ]
        chars = [item for item in chars if self._matches_query(item[1], item[2], query)]
        # 숨긴 캐릭터는 검색에 나오지 않는다(사용자 지시 2026-10-19) - 되돌리는 곳은 Find 의 [제외] 목록이다.
        hidden = set() if include_hidden else self.hidden()
        if hidden:
            chars = [item for item in chars if f"{item[0]}::{item[1]}" not in hidden]
        feature_keep = self._feature_filter(include, exclude)
        if feature_keep is not None:
            chars = [item for item in chars if feature_keep(item[0], item[1])]
        if recent_only:
            chars = [item for item in chars if self.is_recent(item[1])]
        if favorites_only:
            # ⚠️ 걸러 낸 뒤에도 **작품 칩은 아래에서 이 목록으로 다시 센다** - 즐겨찾기만
            #    보는 중에는 즐겨찾기 안의 작품만 칩으로 떠야 한다.
            favorites = self.favorites()
            chars = [item for item in chars if f"{item[0]}::{item[1]}" in favorites]
        # 성별(사용자 지시 2026-10-21 · 화면은 나중 - 지금은 백엔드만). 값 = girl / boy / other(머리말과 같은 잣대
        # `prompt_head`). 수는 **성별로 거르기 전**에 센다 - 화면이 토글마다 '그걸 켜면 몇 명' 을 보여 줄 수 있게.
        gender_counts = {"girl": 0, "boy": 0, "other": 0}
        for _gk, _name, data in chars:
            gender_counts[self.prompt_head(data)] += 1
        wanted = {str(g or "").strip().lower() for g in (genders or [])} & set(gender_counts)
        if wanted:
            chars = [item for item in chars if self.prompt_head(item[2]) in wanted]
        # 작품 칩은 **지금 걸린 것들**에서 뽑는다. 예전에는 검색어를 작품 **이름**에
        # 맞춰 보는 딴 길(`build_groups`)로 뽑아서, 캐릭터 이름을 치면 칩이 거의
        # 안 떴다(실측: `elysia` -> 0개). 작품을 이미 골랐으면 셀 것이 하나뿐이라
        # 세지 않는다 - 그 때 화면은 **푸는 칩** 하나만 보여 준다.
        scope: list[dict[str, Any]] = []
        if group_key == self.GROUP_ALL:
            counts: dict[str, int] = {}
            for gk, _name, _data in chars:
                counts[gk] = counts.get(gk, 0) + 1
            scope = [
                {"key": key, "count": count}
                for key, count in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
            ][:self.SCOPE_CHIP_LIMIT]
        thumbs = self.thumb_index()
        if thumb_first:
            chars.sort(
                key=lambda item: (
                    self._thumb_key(item[0], item[1]) not in thumbs,
                    -int(item[2].get("total_rows", 0) or 0),
                    item[1].lower(),
                )
            )
        else:
            chars.sort(key=lambda item: (-int(item[2].get("total_rows", 0) or 0), item[1].lower()))

        total = len(chars)
        per_page = max(9, min(96, int(per_page or 48)))
        page = max(0, int(page or 0))
        total_pages = max(1, math.ceil(total / per_page))
        if page >= total_pages:
            page = total_pages - 1
        start = page * per_page
        page_items = [
            (index, gk, name, data)
            for index, (gk, name, data) in enumerate(chars[start:start + per_page], start)
        ]
        all_items = [
            self._serialize_list_item(index, gk, name, data, thumbs)
            for index, (gk, name, data) in enumerate(chars)
        ] if include_all else None
        return {
            "group": group_key,
            "query": query,
            "page": page,
            "per_page": per_page,
            "total": total,
            "total_pages": total_pages,
            "thumb_first": bool(thumb_first),
            "recent_only": bool(recent_only),
            "recent_since": self.recent_since(),
            "favorites_only": bool(favorites_only),
            "favorite_count": len(self.favorites()),
            "genders": sorted(wanted),
            "gender_counts": gender_counts,
            "scope": scope,
            "items": [
                self._serialize_list_item(
                    index,
                    gk,
                    name,
                    data,
                    thumbs,
                    include_thumbnail_url=True,
                    thumbnail_size="grid",
                )
                for index, gk, name, data in page_items
            ],
            "all_items": all_items,
        }

    def _get_character(self, group_key: str, name: str) -> dict[str, Any]:
        data = (self.analysis().get(group_key, {}) or {}).get(name)
        if not isinstance(data, dict):
            raise KeyError(f"Character not found: {group_key}::{name}")
        return data

    def _resolve_variant(self, data: dict[str, Any], variant_label: str = "") -> dict[str, Any] | None:
        if not variant_label:
            return None
        for variant in data.get("alternates", []) or []:
            if str(variant.get("label") or "") == variant_label:
                return variant
        raise KeyError(f"Variant not found: {variant_label}")

    def _variant_items(self, data: dict[str, Any], variant: dict[str, Any] | None):
        if variant is None:
            pc_items = list(data.get("personal_color", []) or [])
            ch_items = list(data.get("characteristics", []) or [])
            attire_items: list[dict[str, Any]] = []
            dist = (data.get("breast_size", {}) or {}).get("distribution", []) or []
            if dist:
                ch_items.insert(0, max(dist, key=lambda entry: entry.get("pct", 0)))
        else:
            pc_items = list(variant.get("personal_color", []) or [])
            ch_items = list(variant.get("characteristics", []) or [])
            attire_items = [entry for entry in (variant.get("attire", []) or []) if entry.get("pct", 0) >= 60.0]
        return pc_items, ch_items, attire_items

    @staticmethod
    def _format_entry(entry: dict[str, Any]) -> dict[str, Any]:
        return {
            "tag": str(entry.get("tag") or ""),
            "count": int(entry.get("count", 0) or 0),
            "pct": float(entry.get("pct", 0) or 0),
        }

    def build_detail(
        self,
        group_key: str,
        name: str,
        variant_label: str = "",
        options: dict[str, Any] | None = None,
        api_mode: str = "NAI",
    ) -> dict[str, Any]:
        data = self._get_character(group_key, name)
        variant = self._resolve_variant(data, variant_label)
        pc_items, ch_items, attire_items = self._variant_items(data, variant)
        prompt_payload = self.build_prompt(group_key, name, variant_label, options or {}, api_mode)
        variants = [
            {"label": "", "name": "Default", "rows": int(data.get("total_rows", 0) or 0)}
        ]
        variants.extend(
            {
                "label": str(item.get("label") or ""),
                "name": str(item.get("label") or "").replace("_", " "),
                "rows": int(item.get("rows", 0) or 0),
            }
            for item in data.get("alternates", []) or []
        )
        return {
            "group": group_key,
            "character": name,
            "count": int(data.get("total_rows", 0) or 0),
            "danbooru_posts": data.get("danbooru_posts"),
            "gender": data.get("gender", ""),
            "aliases": data.get("aliases", []) or [],
            "variant": variant_label,
            "variants": variants,
            "favorite": self.is_favorite(group_key, name),
            "thumbnail_url": self._thumb_url(group_key, name, variant_label),
            "default_thumbnail_url": self._thumb_url(group_key, name),
            "sections": {
                "alternate": variants,
                "personal_color": [self._format_entry(entry) for entry in pc_items],
                "characteristics": [self._format_entry(entry) for entry in ch_items],
                "attire": [self._format_entry(entry) for entry in attire_items],
            },
            "prompt": prompt_payload,
        }

    @staticmethod
    def _split_tags(value: str) -> list[str]:
        return [part.strip() for part in str(value or "").split(",") if part.strip()]

    @staticmethod
    def _escape_sd_tag(tag: str) -> str:
        return str(tag or "").replace("(", r"\(").replace(")", r"\)")

    @classmethod
    def copyright_weight(cls, posts: int | None) -> float:
        """게시물 수 -> 작품명 가중치. 1.0 = 그대로. 스냅숏에 없으면(개명 · 4월 이후) 0.5."""
        if posts is None:
            return 0.5
        if posts < 80:          # 40 미만도 그대로(사전에서 빼지는 않는다)
            return 1.0
        if posts < 100:
            return 0.7
        if posts < 150:
            return 0.6
        return 0.5

    def copyright_part(self, group_key: str, name: str, data: dict[str, Any], is_nai: bool = True) -> str:
        """이름 뒤에 붙일 작품명 조각. 빈 문자열 = 붙이지 않는다.

        · 붙이는 작품명 = 엔트리 `copyright`(없으면 그룹). `original` 은 작품명이 아니다 - 붙이지 않는다(작가는
          `display_name` 이 이름에 붙인다).
        · 이름 끝 괄호가 그 작품(`work_in_name`)이면 음수로 - `-0.7::mega man (series) ::` · BA 는 `-1::blue archive ::`.
        · 그 밖에는(의상 · 작가 괄호만 있는 이름 포함 - `gawr gura (2nd costume)`) 게시물 수 구간의 가중치(`copyright_weight`).
        """
        group = str(group_key or "").strip()
        work = str(data.get("copyright") or group).strip()
        if not group or group == self.ORIGINAL_GROUP or not work or work == self.ORIGINAL_GROUP:
            return ""
        if data.get("work_in_name"):
            weight = self.NEGATIVE_COPYRIGHT.get(work.lower(), self.SERIES_TAIL_WEIGHT)
            # 음수 가중치는 NAI 구문에서만 뜻이 있다.
            return f"{weight:g}::{work} ::" if is_nai else ""
        posts = data.get("danbooru_posts")
        weight = self.copyright_weight(int(posts) if isinstance(posts, (int, float)) else None)
        if weight == 1.0:
            return work if is_nai else self._escape_sd_tag(work)
        if is_nai:
            return f"{weight:g}::{work} ::"
        return f"({self._escape_sd_tag(work)}:{weight:g})"

    def display_name(self, group_key: str, name: str, data: dict[str, Any]) -> str:
        """original 캐릭터는 `이름 (작가)` 로 불러야 나온다(usami taiga -> usami taiga (fu-ta))."""
        artist = str(data.get("artist") or "").strip()
        if group_key == self.ORIGINAL_GROUP and artist and "(" not in name:
            return f"{name} ({artist})"
        return name

    def build_prompt(
        self,
        group_key: str,
        name: str,
        variant_label: str = "",
        options: dict[str, Any] | None = None,
        api_mode: str = "NAI",
    ) -> dict[str, Any]:
        data = self._get_character(group_key, name)
        variant = self._resolve_variant(data, variant_label)
        pc_items, ch_items, attire_items = self._variant_items(data, variant)
        current = self.load_options()
        current.update(options or {})

        is_nai = str(api_mode or "NAI").upper() == "NAI"
        cosplay_mode = bool(current.get("cosplay_enabled"))
        cosplay_parts = self._split_tags(current.get("cosplay_name", "")) if cosplay_mode else []
        cosplay_char = cosplay_parts[0] if cosplay_parts else ""
        cosplay_extra = cosplay_parts[1:] if len(cosplay_parts) > 1 else []

        if current.get("hide_charname"):
            char_name = "original"
        elif cosplay_mode and cosplay_char:
            char_name = cosplay_char if is_nai else self._escape_sd_tag(cosplay_char)
        else:
            char_name = self.display_name(group_key, name, data) if current.get("auto_copyright") else name
            if variant_label:
                char_name = f"{char_name} ({variant_label.replace('_', ' ')})"
            if not is_nai:
                char_name = self._escape_sd_tag(char_name)

        tags: list[str] = []
        cosplay_excluded_pc: list[str] = []
        if cosplay_mode:
            dist = (data.get("breast_size", {}) or {}).get("distribution", []) or []
            bs_tag = max(dist, key=lambda item: item.get("pct", 0)).get("tag") if dist else None
            extra = cosplay_extra if is_nai else [self._escape_sd_tag(item) for item in cosplay_extra]
            tags.extend(["alternate costume", "borrowed character"])
            tags.extend(extra)
            original_name = name if is_nai else self._escape_sd_tag(name)
            if original_name:
                cosplay_suffix = "(cosplay)" if is_nai else r"\(cosplay\)"
                tags.append(f"{original_name} {cosplay_suffix}")
            tags.append("borrowed clothes")
            if current.get("auto_characteristics", True):
                for entry in ch_items:
                    tag = entry.get("tag", "")
                    if tag in self.TAG_EXCLUDE or tag == bs_tag:
                        continue
                    tags.append(self.TAG_REPLACE.get(tag, tag))
            for entry in attire_items:
                tag = entry.get("tag", "")
                if tag not in self.TAG_EXCLUDE:
                    tags.append(self.TAG_REPLACE.get(tag, tag))
            for entry in data.get("personal_color", []) or []:
                tag = entry.get("tag", "")
                if tag not in self.TAG_EXCLUDE:
                    cosplay_excluded_pc.append(tag)
        else:
            for entry in pc_items:
                tag = entry.get("tag", "")
                if tag not in self.TAG_EXCLUDE:
                    tags.append(self.TAG_REPLACE.get(tag, tag))
            if current.get("auto_characteristics", True):
                for entry in ch_items:
                    tag = entry.get("tag", "")
                    if tag not in self.TAG_EXCLUDE:
                        tags.append(self.TAG_REPLACE.get(tag, tag))
            for entry in attire_items:
                tag = entry.get("tag", "")
                if tag not in self.TAG_EXCLUDE:
                    tags.append(self.TAG_REPLACE.get(tag, tag))

        # 머리말 = 사전의 성별(사용자 지시 2026-10-21 - 남성에게도 girl 이 붙었다). 비인간은 other
        # (`tools/mark_nonhuman_characters.py` · 코퍼스 no humans 비율 >= 0.3). 가슴 크기 · loli 치환은 여성 기준이라
        # 남성 · 비인간에는 싣지 않는다(pikachu -> large breasts).
        # 코스프레는 예전대로(girl · 태그 그대로) - 착용자 · 의상 캐릭터가 갈리고 사용자가 적은 태그가 섞인다(Codex 3차).
        head = "girl" if cosplay_mode else self.prompt_head(data)
        if head != "girl":
            tags = [tag for tag in tags if tag not in self.FEMALE_ONLY_TAGS]

        prefix_parts: list[str] = []
        if char_name:
            if is_nai:
                prefix_parts.append(head)
            prefix_parts.append(char_name)
            # 이름 숨김 · 코스프레에는 붙이지 않는다(이름 자리가 그 캐릭터가 아니다).
            if (current.get("auto_copyright") and group_key and not current.get("hide_charname")
                    and not (cosplay_mode and cosplay_char)):
                part = self.copyright_part(group_key, name, data, is_nai)
                if part:
                    prefix_parts.append(part)
        character_prompt = (", ".join(prefix_parts) + ", " if prefix_parts else "") + ", ".join(tags)
        return {
            "character_prompt": character_prompt.strip().strip(","),
            "prefix": str(current.get("prefix") or ""),
            "postfix": str(current.get("postfix") or ""),
            "cosplay_excluded_pc": cosplay_excluded_pc,
            "options": current,
        }

    @staticmethod
    def prompt_head(data: dict[str, Any] | None) -> str:
        """캐릭터 프롬프트 머리말 - girl / boy / other(사전 `gender`). 모르면 girl(옛 동작)."""
        gender = str((data or {}).get("gender") or "").strip().lower()
        return gender if gender in ("boy", "other") else "girl"

    def build_generation_overrides(self, payload: dict[str, Any], api_mode: str = "NAI") -> dict[str, Any]:
        group_key = str(payload.get("group") or "")
        name = str(payload.get("character") or "")
        variant_label = str(payload.get("variant") or "")
        if not group_key or not name:
            raise ValueError("group and character are required")
        data = self._get_character(group_key, name)

        char_prompt = str(payload.get("character_prompt") or "").strip()
        prefix_text = str(payload.get("prefix") or "").strip()
        postfix_text = str(payload.get("postfix") or "").strip()
        if not (char_prompt or prefix_text or postfix_text):
            raise ValueError("prompt is empty")

        request_id = str(payload.get("request_id") or "")
        if not request_id:
            raise ValueError("request_id is required")
        is_nai = str(api_mode or "NAI").upper() == "NAI"
        # Prefix 의 인원 태그를 캐릭터 머리말에 맞춘다 - 기본 Prefix 가 `1girl, ...` 라 남성 · 비인간이
        # 메인 `1girl` + 캐릭터 `boy, link` 로 부딪쳤다(Codex 리뷰 2026-10-21). 다른 인원 태그는 그대로 둔다.
        # 인원 태그가 **하나**일 때만 바꾼다 - 사용자가 `1girl, 1boy` 처럼 여럿을 적었으면 그 구성을 지킨다(Codex 재리뷰).
        # `2boys` · `multiple girls` 같은 인원 태그가 하나라도 더 있으면 여럿 구성이다 - 그대로 둔다(Codex 3차).
        # 코스프레도 그대로(머리말이 예전대로 girl 이다).
        count_tag = self.HEAD_COUNT_TAGS[self.prompt_head(data)]
        prefix_parts = self._split_tags(prefix_text)
        count_slots = [i for i, tag in enumerate(prefix_parts) if self._PERSON_COUNT.match(tag.strip().lower())]
        if (len(count_slots) == 1 and prefix_parts[count_slots[0]].lower() in self.HEAD_COUNT_TAGS.values()
                and not payload.get("cosplay_enabled")):
            prefix_parts[count_slots[0]] = count_tag
            prefix_text = ", ".join(prefix_parts)
        width, height = 896, 1152
        snapshot = {
            "group_key": group_key,
            "char_name": name,
            "variant_label": variant_label,
            "save_blocked": bool(
                payload.get("no_save")
                or payload.get("hide_charname")
                or payload.get("cosplay_enabled")
            ),
        }
        label = name + (f" ({variant_label.replace('_', ' ')})" if variant_label else "")
        common = {
            "character_viewer_request": True,
            "character_viewer_request_id": request_id,
            "_remote_queue_source": "Characters",
            "_remote_queue_label": label,
            "_character_viewer_snapshot": snapshot,
            "width": width,
            "height": height,
            "random_resolution": False,
        }
        if is_nai:
            overrides = {
                **common,
                "input": ", ".join(part for part in (prefix_text, postfix_text) if part),
            }
            if char_prompt:
                overrides["characters"] = [char_prompt]
                overrides["uc"] = [str(payload.get("character_uc") or "")]
            return overrides

        char_tags = [tag for tag in self._split_tags(char_prompt) if tag.lower() not in ("girl", "boy", "other")]
        char_name_tags = char_tags[:1]
        char_trait_tags = char_tags[1:]
        prefix_tags = self._split_tags(prefix_text)
        postfix_tags = self._split_tags(postfix_text)
        insert_idx = 0
        for index, tag in enumerate(prefix_tags):
            if tag.lower() in self.HEAD_COUNT_TAGS.values() or "girl" in tag.lower():
                insert_idx = index + 1
                break
        merged = prefix_tags[:insert_idx] + char_name_tags + prefix_tags[insert_idx:] + char_trait_tags + postfix_tags
        for tag in self._split_tags(payload.get("character_uc") or ""):
            merged.append(f"-{tag}")
        return {**common, "input": ", ".join(merged)}

    def _resolve_thumb_file(self, filename: str) -> Path:
        """Resolve an index filename inside ``thumb_dir``, rejecting traversal."""
        path = (self.thumb_dir / filename).resolve()
        root = self.thumb_dir.resolve()
        if root not in path.parents and path != root:
            raise ValueError("invalid thumbnail path")
        return path

    def _write_thumb_index(self, index: dict[str, str]) -> None:
        self.thumb_dir.mkdir(parents=True, exist_ok=True)
        tmp_path = self.thumb_index_path.with_name(self.thumb_index_path.name + ".tmp")
        with open(tmp_path, "w", encoding="utf-8") as handle:
            json.dump(index, handle, ensure_ascii=False, indent=2)
        tmp_path.replace(self.thumb_index_path)
        self._thumb_index = index
        self._invalidate_search("thumbs")

    def thumbnail_path(self, group_key: str, name: str, variant_label: str = "") -> Path:
        filename = self.thumb_index().get(self._thumb_key(group_key, name, variant_label))
        if not filename:
            raise FileNotFoundError("thumbnail not found")
        path = self._resolve_thumb_file(filename)
        if not path.exists():
            raise FileNotFoundError("thumbnail not found")
        return path

    def preview_pack(self):
        """Key-only membership; a value is read only by preview_thumb."""
        if self._preview_pack is None:
            from core.character_preview_index import PreviewKeyIndex
            self._preview_pack = PreviewKeyIndex(self.preview_path, self.preview_index_cache_path)
        return self._preview_pack

    def extension_pack(self) -> dict[str, str]:
        """Read only the manifest once; subsequent membership checks do no I/O."""
        if self._extension_keys is not None:
            return self._extension_keys
        with self._extension_lock:
            if self._extension_keys is None:
                archive = None
                try:
                    archive = zipfile.ZipFile(self.extension_pack_path)
                    manifest = read_manifest(archive)
                    stat = self.extension_pack_path.stat()
                    self._extension_rev = f"{stat.st_mtime_ns}-{stat.st_size}"
                    self._extension_zip = archive
                    self._extension_keys = dict(manifest["keys"])
                except (OSError, ValueError, KeyError, zipfile.BadZipFile, RuntimeError, zlib.error):
                    if archive is not None:
                        archive.close()
                    self._extension_keys = {}
            return self._extension_keys

    def invalidate_extension_pack(self) -> None:
        with self._extension_lock:
            if self._extension_zip is not None:
                self._extension_zip.close()
            self._extension_zip = None
            self._extension_keys = None
            self._extension_rev = "0"
            self._invalidate_search("pack")

    @contextmanager
    def replacing_extension_pack(self):
        # Keep this lock across rename: a concurrent thumbnail must not reopen the old ZIP
        # after close but before os.replace (Windows disallows replacing an open file).
        with self._extension_lock:
            self.invalidate_extension_pack()
            try:
                yield
            finally:
                self.invalidate_extension_pack()

    def _extension_thumb(self, key: str) -> bytes | None:
        with self._extension_lock:
            member = self.extension_pack().get(key)
            if member and self._extension_zip is not None:
                try:
                    return self._extension_zip.read(member)
                except (OSError, ValueError, KeyError, zipfile.BadZipFile, RuntimeError, zlib.error):
                    # Cache the failure until an explicit install invalidation.
                    self._extension_zip.close()
                    self._extension_zip = None
                    self._extension_keys = {}
            return None

    def preview_thumb(self, group_key: str, name: str, variant_label: str = "") -> bytes | None:
        """폴백 미리보기 이미지 바이트. 없으면 None.

        변형(variant)은 담지 않는다 — 팩은 캐릭터 기본형만 뽑은 것이라, 변형을 요청했는데
        기본형 그림을 돌려주면 사용자가 다른 의상을 본다고 오해한다.
        """
        if str(variant_label or ""):
            return None
        # 확장 팩 먼저 - thumbnail_source 와 같은 순서(사용자 > 확장 > 번들).
        ext = self._extension_thumb(f"{group_key}::{name}")
        if ext:
            return ext
        enc = self.preview_pack().get(f"{group_key}::{name}")
        if not enc:
            return None
        try:
            import base64
            return base64.b64decode(enc)
        except Exception:
            return None

    def has_thumbnail(self, group_key: str, name: str, variant_label: str = "") -> bool:
        """사용자 썸네일이 없어도 폴백이 있으면 True — 그리드가 이니셜 대신 그림을 청한다.

        ⚠️ `thumbnail_source()` 의 kind 와 **정의상 같은 판정**이다(인덱스 항목 또는 팩).
        팩의 최초 manifest 로딩 뒤에는 키 집합만 조회한다 — `include_all=True` 목록이 전 캐릭터를
        직렬화하면서 이 판정을 쓰기 때문에 syscall 을 붙이면 통째로 느려진다.
        """
        if self.thumb_index().get(self._thumb_key(group_key, name, variant_label)):
            return True
        return not str(variant_label or "") and (
            f"{group_key}::{name}" in self.preview_pack()
            or f"{group_key}::{name}" in self.extension_pack())

    def delete_thumbnail(self, group_key: str, name: str, variant_label: str = "") -> dict[str, Any]:
        """Delete ONE image's thumbnail: the .webp file AND its index entry.

        확인 없이 즉시 삭제(사용자 지시). 인덱스 항목을 함께 지우는 것이 핵심이다 —
        파일만 사라지면 그리드는 계속 ``has_thumbnail=True``로 보고 404 이미지를
        띄운다(뷰어는 index.json만 신뢰).
        """
        group_key = str(group_key or "")
        name = str(name or "")
        variant_label = str(variant_label or "")
        if not group_key or not name:
            raise ValueError("group and character are required")
        key = self._thumb_key(group_key, name, variant_label)
        index = dict(self.thumb_index())
        filename = str(index.pop(key, "") or "")
        if not filename:
            return {
                "key": key,
                "filename": "",
                "removed": False,
                "removed_file": False,
                "thumbnail_count": len(index),
            }
        # 파일명 살균(``[<>:"/\\|?*]`` -> ``_``)은 서로 다른 키를 같은 파일명으로
        # 접을 수 있다. 남은 키가 아직 이 파일을 가리키면 인덱스 항목만 지운다.
        shared = any(str(value) == filename for value in index.values())
        removed_file = False
        if not shared:
            path = self._resolve_thumb_file(filename)
            if path.exists():
                path.unlink()
                removed_file = True
        self._write_thumb_index(index)
        # 지운 **뒤의 실효 상태**를 함께 준다. 번들 폴백이 있는 캐릭터는 사용자 썸네일을
        # 지워도 여전히 그림이 나오는데(`thumbnail_source` 가 fallback 으로 떨어진다),
        # 프론트가 무조건 `has_thumbnail=false` 로 칠하면 새로고침 전까지 "No Thumb" 라는
        # 거짓을 보여준다.
        return {
            "key": key,
            "filename": filename,
            "removed": True,
            "removed_file": removed_file,
            "thumbnail_count": len(index),
            "has_thumbnail": self.has_thumbnail(group_key, name, variant_label),
            "thumbnail_url": self._thumb_url(group_key, name, variant_label),
            "default_thumbnail_url": self._thumb_url(group_key, name),
        }

    def save_thumbnail(self, pil_image: Any, snapshot: dict[str, Any]) -> dict[str, Any] | None:
        group_key = str(snapshot.get("group_key") or "")
        name = str(snapshot.get("char_name") or "")
        variant_label = str(snapshot.get("variant_label") or "")
        if not group_key or not name:
            return None
        from PIL import Image

        self.thumb_dir.mkdir(parents=True, exist_ok=True)
        key = self._thumb_key(group_key, name, variant_label)
        safe_name = re.sub(r'[<>:"/\\|?*]', "_", key.replace("::", "__")) + ".webp"
        thumb = pil_image.copy()
        thumb.thumbnail(self.THUMB_MAX_SIZE, Image.Resampling.LANCZOS)
        # 최종 경로에 바로 쓰면 덮어쓰는 동안 들어온 GET 이 **잘린 파일**을 받는다.
        # 인덱스와 같은 방식(임시 파일 -> replace)으로 맞춘다. revision(mtime/크기)을
        # 읽는 쪽과도 경합하지 않는다.
        target = self.thumb_dir / safe_name
        tmp_path = target.with_name(target.name + ".tmp")
        thumb.save(tmp_path, "WEBP", quality=82)
        tmp_path.replace(target)

        index = dict(self.thumb_index())
        index[key] = safe_name
        self._write_thumb_index(index)
        # `thumbnail_count` 를 여기서 준다. 저장 시점에 갱신된 인덱스가 이미 손에 있어
        # 프론트가 헤더 숫자를 고치자고 `state()` 를 다시 부를 이유가 없다
        # (`state()` 는 전 캐릭터를 순회한다). 삭제 경로가 쓰는 계약과 같은 모양이다.
        return {
            "key": key,
            "filename": safe_name,
            "url": self._thumb_url(group_key, name, variant_label),
            "thumbnail_count": len(index),
        }
