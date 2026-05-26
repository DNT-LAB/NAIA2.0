"""Conditional Prompt Editor v2.1 — 프리셋 저장/로드 시스템.

RuleBook 을 JSON 으로 직렬화/역직렬화. 사용자 프리셋(`save/conditional_presets/`,
편집 가능)과 번들 프리셋(`data/conditional_presets_bundled/`, read-only) 분리.

스키마 버전(`schema_version`)을 통해 장기 호환성 확보. D4 를 따라 엔진 옵션
(`max_passes`, `stop_on_match`)은 DSL 이 아닌 프리셋 메타 필드로만 저장.

HANDOFF: docs/HANDOFF_CONDITIONAL_PROMPT_V2_2026_04_21.md
SRS:     docs/CONDITIONAL_PROMPT_EDITOR_PHASE1_SRS.md §5.5
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from core.conditional.block_model import (
    Action,
    ConditionNode,
    Rule,
    RuleBook,
)


SCHEMA_VERSION = 1

# ============================================================================
# 기본 경로 — 프로젝트 루트 기준 절대경로
# ============================================================================

_MODULE_DIR = Path(__file__).resolve().parent  # modules/conditional/
_PROJECT_ROOT = _MODULE_DIR.parent.parent

DEFAULT_SAVE_DIR = _PROJECT_ROOT / "save" / "conditional_presets"
DEFAULT_BUNDLED_DIR = _PROJECT_ROOT / "data" / "conditional_presets_bundled"

# Windows 안전 파일명 sanitizer
_NAME_INVALID_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


# ============================================================================
# 메타 정보 (리스트 표시용 경량 구조)
# ============================================================================


@dataclass
class PresetInfo:
    name: str
    path: Path
    description: str
    is_bundled: bool
    rule_count: int


# ============================================================================
# dict ↔ dataclass 직렬화
# ============================================================================


def rulebook_to_dict(
    book: RuleBook, *, name: str = "", description: str = ""
) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "name": name,
        "description": description,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "engine_options": {
            "max_passes": book.max_passes,
            "stop_on_match": book.stop_on_match,
        },
        "rules": [_rule_to_dict(r) for r in book.rules],
    }


def rulebook_from_dict(data: dict) -> RuleBook:
    version = data.get("schema_version", 1)
    if version > SCHEMA_VERSION:
        raise ValueError(
            f"지원되지 않는 스키마 버전: {version} (현재 {SCHEMA_VERSION})"
        )
    opts = data.get("engine_options") or {}
    return RuleBook(
        rules=[_rule_from_dict(r) for r in data.get("rules", [])],
        max_passes=int(opts.get("max_passes", 1)),
        stop_on_match=bool(opts.get("stop_on_match", False)),
    )


def _rule_to_dict(r: Rule) -> dict:
    return {
        "id": r.id,
        "name": r.name,
        "enabled": r.enabled,
        "priority": r.priority,
        "kind": r.kind,
        "condition": (
            _condition_to_dict(r.condition) if r.condition is not None else None
        ),
        "action": _action_to_dict(r.action) if r.action is not None else None,
        "raw_dsl": r.raw_dsl,
    }


def _rule_from_dict(d: dict) -> Rule:
    cond = d.get("condition")
    act = d.get("action")
    rule = Rule(
        name=d.get("name", ""),
        enabled=bool(d.get("enabled", True)),
        priority=int(d.get("priority", 100)),
        kind=d.get("kind", "block"),
        condition=_condition_from_dict(cond) if cond else None,
        action=_action_from_dict(act) if act else None,
        raw_dsl=d.get("raw_dsl"),
    )
    rid = d.get("id")
    if rid:
        rule.id = rid
    return rule


def _condition_to_dict(c: ConditionNode) -> dict:
    return {
        "kind": c.kind,
        "leaf_kind": c.leaf_kind,
        "negated": c.negated,
        "tag_value": c.tag_value,
        "tag_modifier": c.tag_modifier,
        "rating_value": c.rating_value,
        "rating_source": c.rating_source,
        "char_index": c.char_index,
        "char_tag_value": c.char_tag_value,
        "char_tag_modifier": c.char_tag_modifier,
        "logical": c.logical,
        "children": [_condition_to_dict(ch) for ch in c.children],
    }


def _condition_from_dict(d: dict) -> ConditionNode:
    return ConditionNode(
        kind=d.get("kind", "leaf"),
        leaf_kind=d.get("leaf_kind"),
        negated=bool(d.get("negated", False)),
        tag_value=d.get("tag_value", ""),
        tag_modifier=d.get("tag_modifier", "contains"),
        rating_value=d.get("rating_value", ""),
        rating_source=d.get("rating_source", "auto"),
        char_index=d.get("char_index"),
        char_tag_value=d.get("char_tag_value", ""),
        char_tag_modifier=d.get("char_tag_modifier", "contains"),
        logical=d.get("logical"),
        children=[
            _condition_from_dict(c) for c in (d.get("children") or [])
        ],
    )


def _action_to_dict(a: Action) -> dict:
    return {
        "kind": a.kind,
        "target": a.target,
        "preserve_weight": a.preserve_weight,
        "tags": list(a.tags),
        "old_tag": a.old_tag,
        "new_tags": list(a.new_tags),
        "char_state": a.char_state,
        "char_index": a.char_index,
        "char_old_tag": a.char_old_tag,
        "char_new_tag": a.char_new_tag,
    }


def _action_from_dict(d: dict) -> Action:
    return Action(
        kind=d.get("kind", "append_list"),
        target=d.get("target", "main"),
        preserve_weight=bool(d.get("preserve_weight", True)),
        tags=list(d.get("tags") or []),
        old_tag=d.get("old_tag", ""),
        new_tags=list(d.get("new_tags") or []),
        char_state=d.get("char_state"),
        char_index=d.get("char_index"),
        char_old_tag=d.get("char_old_tag", ""),
        char_new_tag=d.get("char_new_tag", ""),
    )


# ============================================================================
# PresetStorage — 파일 I/O (경로 주입 가능, 테스트 용이)
# ============================================================================


class PresetStorage:
    """프리셋 파일 I/O. 경로 주입으로 테스트 환경 분리 가능."""

    def __init__(
        self,
        save_dir: Optional[Path] = None,
        bundled_dir: Optional[Path] = None,
    ):
        self.save_dir = Path(save_dir) if save_dir else DEFAULT_SAVE_DIR
        self.bundled_dir = (
            Path(bundled_dir) if bundled_dir else DEFAULT_BUNDLED_DIR
        )

    # ------------------------------------------------------------------
    # 저장 / 로드 / 삭제
    # ------------------------------------------------------------------

    def save(
        self,
        name: str,
        book: RuleBook,
        *,
        description: str = "",
    ) -> Path:
        """사용자 프리셋 저장. 번들 디렉터리에는 쓰지 않음."""
        safe = _sanitize_name(name)
        if not safe:
            raise ValueError(f"유효하지 않은 프리셋 이름: {name!r}")
        self.save_dir.mkdir(parents=True, exist_ok=True)
        path = self.save_dir / f"{safe}.json"
        data = rulebook_to_dict(book, name=name, description=description)
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return path

    def load(self, name_or_path: str) -> RuleBook:
        """이름 또는 경로로 프리셋 로드.

        - 경로(`.json` 확장자 + 존재)면 그 파일 사용
        - 이름이면 `save_dir` → `bundled_dir` 순서로 탐색 (사용자 우선)
        """
        path = self._resolve(name_or_path)
        if path is None:
            raise FileNotFoundError(f"프리셋을 찾을 수 없음: {name_or_path!r}")
        data = json.loads(path.read_text(encoding="utf-8"))
        return rulebook_from_dict(data)

    def delete(self, name: str) -> bool:
        """사용자 프리셋만 삭제 가능. 번들은 보호."""
        safe = _sanitize_name(name)
        if not safe:
            return False
        path = self.save_dir / f"{safe}.json"
        if path.exists():
            path.unlink()
            return True
        return False

    # ------------------------------------------------------------------
    # 목록 / 조회
    # ------------------------------------------------------------------

    def list_all(self) -> List[PresetInfo]:
        """번들 + 사용자 프리셋을 메타만 읽어 반환. 이름 사전순 정렬."""
        infos: List[PresetInfo] = []
        if self.bundled_dir.exists():
            for p in sorted(self.bundled_dir.glob("*.json")):
                info = _peek(p, is_bundled=True)
                if info is not None:
                    infos.append(info)
        if self.save_dir.exists():
            for p in sorted(self.save_dir.glob("*.json")):
                info = _peek(p, is_bundled=False)
                if info is not None:
                    infos.append(info)
        return infos

    def exists(self, name: str, *, include_bundled: bool = True) -> bool:
        safe = _sanitize_name(name)
        if not safe:
            return False
        if (self.save_dir / f"{safe}.json").exists():
            return True
        if include_bundled and (self.bundled_dir / f"{safe}.json").exists():
            return True
        return False

    # ------------------------------------------------------------------
    # 내부
    # ------------------------------------------------------------------

    def _resolve(self, name_or_path: str) -> Optional[Path]:
        p = Path(name_or_path)
        # 절대/상대 경로 + .json 확장자 + 존재
        if p.suffix.lower() == ".json" and p.exists():
            return p
        safe = _sanitize_name(str(name_or_path))
        if not safe:
            return None
        for base in (self.save_dir, self.bundled_dir):
            candidate = base / f"{safe}.json"
            if candidate.exists():
                return candidate
        return None


# ============================================================================
# 헬퍼
# ============================================================================


def _sanitize_name(name: str) -> str:
    """파일명 부적합 문자 제거. 앞뒤 공백/점 제거."""
    if not isinstance(name, str):
        return ""
    cleaned = _NAME_INVALID_RE.sub("", name).strip().strip(".")
    return cleaned


def _peek(path: Path, *, is_bundled: bool) -> Optional[PresetInfo]:
    """프리셋 파일의 메타만 읽어 `PresetInfo` 생성. 오류는 None."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return PresetInfo(
        name=data.get("name") or path.stem,
        path=path,
        description=data.get("description", ""),
        is_bundled=is_bundled,
        rule_count=len(data.get("rules") or []),
    )


# ============================================================================
# 모듈 레벨 편의 API (기본 경로 singleton)
# ============================================================================


_default_storage: Optional[PresetStorage] = None


def get_default_storage() -> PresetStorage:
    global _default_storage
    if _default_storage is None:
        _default_storage = PresetStorage()
    return _default_storage


def save_preset(name: str, book: RuleBook, *, description: str = "") -> Path:
    return get_default_storage().save(name, book, description=description)


def load_preset(name_or_path: str) -> RuleBook:
    return get_default_storage().load(name_or_path)


def list_presets() -> List[PresetInfo]:
    return get_default_storage().list_all()


def delete_preset(name: str) -> bool:
    return get_default_storage().delete(name)


__all__ = [
    "SCHEMA_VERSION",
    "DEFAULT_SAVE_DIR",
    "DEFAULT_BUNDLED_DIR",
    "PresetInfo",
    "PresetStorage",
    "rulebook_to_dict",
    "rulebook_from_dict",
    "get_default_storage",
    "save_preset",
    "load_preset",
    "list_presets",
    "delete_preset",
]
