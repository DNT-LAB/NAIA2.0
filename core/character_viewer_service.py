"""Server-side Character Viewer data and prompt helpers."""

from __future__ import annotations

import json
import math
import re
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
        self.thumb_index_path = self.thumb_dir / "index.json"
        self.tags_path = self.save_dir / "character_viewer_tags.json"
        self._groups: dict[str, Any] | None = None
        self._analysis: dict[str, Any] | None = None
        self._tag_index: dict[str, tuple[str, dict[str, Any]]] | None = None
        self._thumb_index: dict[str, str] | None = None
        self._preview_rev: str | None = None
        self._presets: dict[str, Any] | None = None
        self._preview_pack: dict[str, str] | None = None
        self._debut: dict[str, str] | None = None
        self._recent_since: str = ""

    def data_available(self) -> bool:
        return self.groups_path.exists() and self.analysis_path.exists()

    def _load_json(self, path: Path, fallback: Any) -> Any:
        if not path.exists():
            return fallback
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)

    def groups(self) -> dict[str, Any]:
        if self._groups is None:
            self._groups = self._load_json(self.groups_path, {})
        return self._groups

    def analysis(self) -> dict[str, Any]:
        if self._analysis is None:
            self._analysis = self._load_json(self.analysis_path, {})
        return self._analysis

    def debut_index(self) -> dict[str, str]:
        """캐릭터 이름 -> 처음 나타난 달("YYYY-MM"). 파일이 없으면 빈 사전이다.

        ⚠️ 왼쪽 끝은 잘려 있다 - 코퍼스가 2015-12 에서 시작하므로 그 이전에 데뷔한
           캐릭터는 전부 그 달로 뭉친다. [최신] 은 **반대쪽 끝**만 보므로 무관하다.
        """
        if self._debut is None:
            raw = self._load_json(self.debut_path, {})
            table = raw.get("debut") if isinstance(raw, dict) else None
            self._debut = table if isinstance(table, dict) else {}
            since = raw.get("recent_since") if isinstance(raw, dict) else ""
            self._recent_since = str(since or self.RECENT_SINCE)
        return self._debut

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

    def load_options(self) -> dict[str, Any]:
        data = self._load_json(self.tags_path, {})
        return {
            "prefix": data.get("prefix", self.DEFAULT_PREFIX),
            "postfix": data.get("postfix", self.DEFAULT_POSTFIX),
            "cosplay_enabled": bool(data.get("cosplay_enabled", False)),
            "cosplay_name": str(data.get("cosplay_name", "")),
            "auto_copyright": bool(data.get("auto_copyright", False)),
            "auto_characteristics": bool(data.get("auto_characteristics", True)),
            "hide_charname": bool(data.get("hide_charname", False)),
            "no_save": bool(data.get("no_save", False)),
            "thumb_first": bool(data.get("thumb_first", data.get("empty_thumb_only", True))),
            "empty_thumb_only": bool(data.get("empty_thumb_only", True)),
        }

    def save_options(self, payload: dict[str, Any]) -> dict[str, Any]:
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
        ):
            if key in payload:
                current[key] = payload[key]
        self.save_dir.mkdir(parents=True, exist_ok=True)
        with open(self.tags_path, "w", encoding="utf-8") as handle:
            json.dump(current, handle, ensure_ascii=False, indent=2)
        return current

    def _group_counts(self) -> list[tuple[str, int]]:
        out: list[tuple[str, int]] = []
        for group_key, data in self.groups().items():
            if str(group_key).startswith("_") or not isinstance(data, dict):
                continue
            total = len(data.get("girl", []) or []) + len(data.get("boy", []) or [])
            out.append((group_key, total))
        out.sort(key=lambda item: (-item[1], item[0].lower()))
        return out

    def state(self) -> dict[str, Any]:
        group_counts = self._group_counts()
        character_count = sum(1 for _ in self._iter_all_chars())
        thumbs = self.thumb_index()
        return {
            "available": self.data_available(),
            "group_count": len(group_counts),
            "character_count": character_count,
            "thumbnail_count": len(thumbs),
            "options": self.load_options(),
        }

    def build_groups(self, query: str = "", limit: int = 2000) -> dict[str, Any]:
        query_text = str(query or "").strip().lower()
        groups = [{"key": self.GROUP_ALL, "name": "All", "count": sum(c for _, c in self._group_counts())}]
        for key, count in self._group_counts():
            if query_text and query_text not in key.lower():
                continue
            groups.append({"key": key, "name": key, "count": count})
            if len(groups) >= limit:
                break
        return {"items": groups, "total": len(groups)}

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
                              or f"{group_key}::{name}" in self.preview_pack()),
        }
        # 화면이 '요즘 캐릭터' 를 가릴 수 있게 함께 보낸다(모르면 빈 문자열).
        item["debut"] = self.debut_index().get(name, "")
        if include_tags:
            item["tags"] = self._tag_search_str(data)
        if include_thumbnail_url:
            item["thumbnail_url"] = self._thumb_url(group_key, name, size=thumbnail_size)
        return item

    def build_list(
        self,
        group_key: str = GROUP_ALL,
        query: str = "",
        page: int = 0,
        per_page: int = 48,
        thumb_first: bool = True,
        include_all: bool = False,
        recent_only: bool = False,
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
        if recent_only:
            chars = [item for item in chars if self.is_recent(item[1])]
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
            "gender": data.get("gender", ""),
            "aliases": data.get("aliases", []) or [],
            "variant": variant_label,
            "variants": variants,
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
            char_name = name
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

        prefix_parts: list[str] = []
        if char_name:
            if is_nai:
                prefix_parts.append("girl")
            prefix_parts.append(char_name)
            if current.get("auto_copyright") and group_key:
                prefix_parts.append(group_key if is_nai else self._escape_sd_tag(group_key))
        character_prompt = (", ".join(prefix_parts) + ", " if prefix_parts else "") + ", ".join(tags)
        return {
            "character_prompt": character_prompt.strip().strip(","),
            "prefix": str(current.get("prefix") or ""),
            "postfix": str(current.get("postfix") or ""),
            "cosplay_excluded_pc": cosplay_excluded_pc,
            "options": current,
        }

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

        char_tags = [tag for tag in self._split_tags(char_prompt) if tag.lower() != "girl"]
        char_name_tags = char_tags[:1]
        char_trait_tags = char_tags[1:]
        prefix_tags = self._split_tags(prefix_text)
        postfix_tags = self._split_tags(postfix_text)
        insert_idx = 0
        for index, tag in enumerate(prefix_tags):
            if "girl" in tag.lower():
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

    def thumbnail_path(self, group_key: str, name: str, variant_label: str = "") -> Path:
        filename = self.thumb_index().get(self._thumb_key(group_key, name, variant_label))
        if not filename:
            raise FileNotFoundError("thumbnail not found")
        path = self._resolve_thumb_file(filename)
        if not path.exists():
            raise FileNotFoundError("thumbnail not found")
        return path

    def preview_pack(self) -> dict[str, str]:
        """번들 미리보기 팩(`data/character_preview_thumbs.json`). 처음 쓸 때만 읽는다.

        **사용자 썸네일의 폴백이다 — 덮지 않는다.** 우선순위는 사용자 지정이다:

            1순위  user-data/data/character_thumbnails/  (사용자가 만든 것)
            2순위  이 팩                                  (번들, 256px webp q72)

        9,738명 전부를 넣으면 92MB 라 릴리즈에 다 담지 않는다. 빈도 상위 N명만 담고
        (`tools/build_character_preview_pack.py --limit`), 나머지는 지금처럼 이니셜 타일이다.
        """
        if self._preview_pack is None:
            data = self._load_json(self.preview_path, {})
            thumbs = data.get("thumbs") if isinstance(data, dict) else None
            self._preview_pack = thumbs if isinstance(thumbs, dict) else {}
        return self._preview_pack

    def preview_thumb(self, group_key: str, name: str, variant_label: str = "") -> bytes | None:
        """폴백 미리보기 이미지 바이트. 없으면 None.

        변형(variant)은 담지 않는다 — 팩은 캐릭터 기본형만 뽑은 것이라, 변형을 요청했는데
        기본형 그림을 돌려주면 사용자가 다른 의상을 본다고 오해한다.
        """
        if str(variant_label or ""):
            return None
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
        여기는 stat 을 하지 않는다 — `include_all=True` 목록이 전 캐릭터(11,890명)를
        직렬화하면서 이 판정을 쓰기 때문에 syscall 을 붙이면 통째로 느려진다.
        """
        if self.thumb_index().get(self._thumb_key(group_key, name, variant_label)):
            return True
        return not str(variant_label or "") and f"{group_key}::{name}" in self.preview_pack()

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
