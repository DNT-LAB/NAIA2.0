"""프리셋 저장/로드 시스템 테스트 (Sub-phase 1.5).

검증 범위:
1. dict ↔ RuleBook 직렬화 왕복 (단순/중첩/raw/engine_options)
2. `PresetStorage` 파일 I/O — save/load/delete, 번들 보호
3. 이름 sanitization (Windows 안전)
4. 스키마 버전 체크
5. 결측 필드 기본값 fallback (장기 호환성)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from modules.conditional.block_model import (  # noqa: E402
    Action,
    ConditionNode,
    Rule,
    RuleBook,
    make_and_group,
    make_char_in_leaf,
    make_or_group,
    make_rating_leaf,
    make_tag_leaf,
)
from modules.conditional.preset_io import (  # noqa: E402
    SCHEMA_VERSION,
    PresetStorage,
    rulebook_from_dict,
    rulebook_to_dict,
)


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def simple_book() -> RuleBook:
    return RuleBook(
        rules=[
            Rule(
                kind="block",
                enabled=True,
                priority=100,
                condition=make_tag_leaf("blush"),
                action=Action(
                    kind="append_list", target="main", tags=["smile"]
                ),
            ),
        ],
        max_passes=2,
        stop_on_match=True,
    )


@pytest.fixture
def complex_book() -> RuleBook:
    return RuleBook(
        rules=[
            Rule(
                kind="block",
                enabled=True,
                priority=50,
                name="첫 규칙",
                condition=make_and_group(
                    make_tag_leaf("blush", modifier="exact"),
                    make_or_group(
                        make_rating_leaf("q", source="override"),
                        make_char_in_leaf(1, "smile"),
                    ),
                ),
                action=Action(
                    kind="append_list",
                    target="main",
                    tags=["happy", "glowing"],
                ),
            ),
            Rule(
                kind="block",
                enabled=False,
                priority=200,
                condition=make_tag_leaf("nsfw"),
                action=Action(
                    kind="replace",
                    old_tag="__bad__",
                    new_tags=["clean"],
                ),
            ),
            Rule(
                kind="raw",
                enabled=True,
                raw_dsl="(a):existing_tag+=new",
            ),
            Rule(
                kind="block",
                enabled=True,
                priority=10,
                condition=ConditionNode(
                    kind="leaf",
                    leaf_kind="char_on",
                    char_index=2,
                ),
                action=Action(
                    kind="char_set",
                    char_index=3,
                    char_state="disabled",
                ),
            ),
        ],
        max_passes=5,
        stop_on_match=False,
    )


@pytest.fixture
def tmp_storage(tmp_path) -> PresetStorage:
    """격리된 임시 디렉터리로 구성된 저장소."""
    save_dir = tmp_path / "save" / "conditional_presets"
    bundled_dir = tmp_path / "data" / "conditional_presets_bundled"
    return PresetStorage(save_dir=save_dir, bundled_dir=bundled_dir)


# ============================================================================
# dict ↔ RuleBook 직렬화
# ============================================================================


class TestDictSerialization:
    def test_schema_version_in_output(self, simple_book):
        d = rulebook_to_dict(simple_book)
        assert d["schema_version"] == SCHEMA_VERSION

    def test_engine_options_preserved(self, simple_book):
        d = rulebook_to_dict(simple_book)
        assert d["engine_options"]["max_passes"] == 2
        assert d["engine_options"]["stop_on_match"] is True

    def test_simple_roundtrip(self, simple_book):
        d = rulebook_to_dict(simple_book)
        restored = rulebook_from_dict(d)
        assert len(restored.rules) == 1
        r = restored.rules[0]
        assert r.enabled and r.kind == "block"
        assert r.condition.tag_value == "blush"
        assert r.action.target == "main"
        assert r.action.tags == ["smile"]
        assert restored.max_passes == 2
        assert restored.stop_on_match is True

    def test_complex_roundtrip(self, complex_book):
        d = rulebook_to_dict(complex_book)
        restored = rulebook_from_dict(d)
        assert len(restored.rules) == 4

        # 규칙 1 — 중첩 AND/OR
        r0 = restored.rules[0]
        assert r0.name == "첫 규칙"
        assert r0.priority == 50
        assert r0.condition.logical == "AND"
        assert r0.condition.children[1].logical == "OR"
        inner_or = r0.condition.children[1]
        assert inner_or.children[0].leaf_kind == "rating"
        assert inner_or.children[0].rating_source == "override"
        assert inner_or.children[1].leaf_kind == "char_in"
        assert inner_or.children[1].char_index == 1

        # 규칙 2 — disabled + replace
        r1 = restored.rules[1]
        assert not r1.enabled
        assert r1.action.kind == "replace"
        assert r1.action.old_tag == "__bad__"

        # 규칙 3 — raw fallback
        r2 = restored.rules[2]
        assert r2.kind == "raw"
        assert r2.raw_dsl == "(a):existing_tag+=new"
        assert r2.condition is None
        assert r2.action is None

        # 규칙 4 — char_set
        r3 = restored.rules[3]
        assert r3.action.kind == "char_set"
        assert r3.action.char_state == "disabled"

    def test_id_preserved_across_roundtrip(self, simple_book):
        original_id = simple_book.rules[0].id
        d = rulebook_to_dict(simple_book)
        restored = rulebook_from_dict(d)
        assert restored.rules[0].id == original_id

    def test_empty_book(self):
        book = RuleBook()
        d = rulebook_to_dict(book)
        restored = rulebook_from_dict(d)
        assert len(restored.rules) == 0
        assert restored.max_passes == 1
        assert restored.stop_on_match is False


class TestSchemaCompatibility:
    def test_reject_newer_schema(self):
        with pytest.raises(ValueError, match="스키마 버전"):
            rulebook_from_dict({"schema_version": 999, "rules": []})

    def test_missing_schema_version_defaults_to_1(self):
        # 스키마 필드 없어도 legacy 로 해석
        book = rulebook_from_dict({"rules": []})
        assert isinstance(book, RuleBook)

    def test_missing_engine_options(self):
        book = rulebook_from_dict({"schema_version": 1, "rules": []})
        assert book.max_passes == 1
        assert book.stop_on_match is False

    def test_missing_rule_fields_use_defaults(self):
        book = rulebook_from_dict(
            {
                "schema_version": 1,
                "rules": [
                    {"kind": "block", "condition": None, "action": None},
                ],
            }
        )
        r = book.rules[0]
        assert r.enabled is True
        assert r.priority == 100
        assert r.condition is None


# ============================================================================
# PresetStorage 파일 I/O
# ============================================================================


class TestPresetStorageSave:
    def test_save_creates_file(self, tmp_storage, simple_book):
        path = tmp_storage.save("my_preset", simple_book)
        assert path.exists()
        assert path.suffix == ".json"
        assert path.parent == tmp_storage.save_dir

    def test_save_includes_description(self, tmp_storage, simple_book):
        path = tmp_storage.save(
            "tagged", simple_book, description="테스트 설명"
        )
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["description"] == "테스트 설명"

    def test_save_utf8(self, tmp_storage, simple_book):
        path = tmp_storage.save("한글_프리셋", simple_book)
        assert path.exists()
        content = path.read_text(encoding="utf-8")
        # 한글이 그대로 들어가야 함 (ensure_ascii=False)
        assert "한글_프리셋" in content

    def test_save_rejects_empty_name(self, tmp_storage, simple_book):
        with pytest.raises(ValueError):
            tmp_storage.save("", simple_book)
        with pytest.raises(ValueError):
            tmp_storage.save("   ", simple_book)

    def test_save_sanitizes_invalid_chars(self, tmp_storage, simple_book):
        # Windows 금지 문자 제거 후에도 남는 이름이면 허용
        path = tmp_storage.save("my<preset>", simple_book)
        assert "mypreset" in path.stem

    def test_save_overwrites_existing(self, tmp_storage, simple_book):
        p1 = tmp_storage.save("same", simple_book)
        simple_book.rules[0].action.tags = ["changed"]
        p2 = tmp_storage.save("same", simple_book)
        assert p1 == p2
        data = json.loads(p2.read_text(encoding="utf-8"))
        assert data["rules"][0]["action"]["tags"] == ["changed"]


class TestPresetStorageLoad:
    def test_load_by_name(self, tmp_storage, simple_book):
        tmp_storage.save("loadme", simple_book)
        restored = tmp_storage.load("loadme")
        assert len(restored.rules) == 1
        assert restored.rules[0].condition.tag_value == "blush"

    def test_load_by_path(self, tmp_storage, simple_book):
        path = tmp_storage.save("via_path", simple_book)
        restored = tmp_storage.load(str(path))
        assert restored.rules[0].action.target == "main"

    def test_load_missing_raises(self, tmp_storage):
        with pytest.raises(FileNotFoundError):
            tmp_storage.load("does_not_exist")

    def test_load_user_overrides_bundled(
        self, tmp_storage, simple_book, complex_book
    ):
        # 번들에 먼저 저장
        tmp_storage.bundled_dir.mkdir(parents=True, exist_ok=True)
        bundled_data = rulebook_to_dict(complex_book, name="shared")
        (tmp_storage.bundled_dir / "shared.json").write_text(
            json.dumps(bundled_data, ensure_ascii=False),
            encoding="utf-8",
        )
        # 사용자가 같은 이름으로 저장 → 사용자 우선
        tmp_storage.save("shared", simple_book)
        restored = tmp_storage.load("shared")
        assert len(restored.rules) == 1  # simple_book 의 것
        assert restored.rules[0].condition.tag_value == "blush"

    def test_load_bundled_when_user_absent(self, tmp_storage, complex_book):
        tmp_storage.bundled_dir.mkdir(parents=True, exist_ok=True)
        bundled_data = rulebook_to_dict(complex_book, name="bundle_only")
        (tmp_storage.bundled_dir / "bundle_only.json").write_text(
            json.dumps(bundled_data, ensure_ascii=False),
            encoding="utf-8",
        )
        restored = tmp_storage.load("bundle_only")
        assert len(restored.rules) == 4


class TestPresetStorageDelete:
    def test_delete_user_preset(self, tmp_storage, simple_book):
        path = tmp_storage.save("deletable", simple_book)
        assert path.exists()
        assert tmp_storage.delete("deletable") is True
        assert not path.exists()

    def test_delete_missing_returns_false(self, tmp_storage):
        assert tmp_storage.delete("never_existed") is False

    def test_delete_does_not_touch_bundled(self, tmp_storage, complex_book):
        tmp_storage.bundled_dir.mkdir(parents=True, exist_ok=True)
        bundled_path = tmp_storage.bundled_dir / "protected.json"
        bundled_path.write_text(
            json.dumps(rulebook_to_dict(complex_book)),
            encoding="utf-8",
        )
        # 사용자 프리셋 없는 상태에서 삭제 시도
        assert tmp_storage.delete("protected") is False
        assert bundled_path.exists()  # 번들 보호


class TestPresetStorageList:
    def test_list_empty(self, tmp_storage):
        assert tmp_storage.list_all() == []

    def test_list_user_only(self, tmp_storage, simple_book):
        tmp_storage.save("a", simple_book)
        tmp_storage.save("b", simple_book)
        infos = tmp_storage.list_all()
        assert len(infos) == 2
        assert all(not i.is_bundled for i in infos)
        names = sorted(i.name for i in infos)
        assert names == ["a", "b"]

    def test_list_combines_bundled_and_user(
        self, tmp_storage, simple_book, complex_book
    ):
        tmp_storage.bundled_dir.mkdir(parents=True, exist_ok=True)
        (tmp_storage.bundled_dir / "bundle1.json").write_text(
            json.dumps(rulebook_to_dict(complex_book, name="bundle1")),
            encoding="utf-8",
        )
        tmp_storage.save("user1", simple_book)
        infos = tmp_storage.list_all()
        assert len(infos) == 2
        bundled = [i for i in infos if i.is_bundled]
        user = [i for i in infos if not i.is_bundled]
        assert len(bundled) == 1 and bundled[0].name == "bundle1"
        assert len(user) == 1 and user[0].name == "user1"
        assert bundled[0].rule_count == 4
        assert user[0].rule_count == 1

    def test_list_skips_corrupted(self, tmp_storage):
        tmp_storage.save_dir.mkdir(parents=True, exist_ok=True)
        (tmp_storage.save_dir / "broken.json").write_text(
            "{{not valid json", encoding="utf-8"
        )
        # 깨진 파일은 조용히 skip
        assert tmp_storage.list_all() == []

    def test_exists(self, tmp_storage, simple_book):
        tmp_storage.save("present", simple_book)
        assert tmp_storage.exists("present")
        assert not tmp_storage.exists("absent")


# ============================================================================
# 이름 sanitization
# ============================================================================


class TestSanitization:
    @pytest.mark.parametrize(
        "raw,expected_substring",
        [
            ("normal", "normal"),
            ("한글", "한글"),
            ("with space", "with space"),
            ("bad<name>", "badname"),
            ("pipe|broken", "pipebroken"),
            ("a/b\\c", "abc"),
            ("  padded  ", "padded"),
            ("dots.txt.", "dots.txt"),  # 후행 점 제거
        ],
    )
    def test_various(self, tmp_storage, simple_book, raw, expected_substring):
        path = tmp_storage.save(raw, simple_book)
        assert expected_substring in path.stem

    def test_all_invalid_rejected(self, tmp_storage, simple_book):
        with pytest.raises(ValueError):
            tmp_storage.save("<>|?", simple_book)


# ============================================================================
# 통합 — 엔드투엔드 왕복
# ============================================================================


class TestEndToEnd:
    def test_save_load_roundtrip_preserves_structure(
        self, tmp_storage, complex_book
    ):
        tmp_storage.save("e2e", complex_book, description="E2E 테스트")
        restored = tmp_storage.load("e2e")

        assert len(restored.rules) == len(complex_book.rules)
        assert restored.max_passes == complex_book.max_passes
        assert restored.stop_on_match == complex_book.stop_on_match

        for original, r in zip(complex_book.rules, restored.rules):
            assert original.kind == r.kind
            assert original.enabled == r.enabled
            assert original.priority == r.priority
            assert original.id == r.id

    def test_priority_sort_after_load(self, tmp_storage, complex_book):
        tmp_storage.save("sorted", complex_book)
        restored = tmp_storage.load("sorted")
        sorted_rules = restored.sorted_rules()
        priorities = [r.priority for r in sorted_rules]
        assert priorities == sorted(priorities)


# ============================================================================
# 수동 실행
# ============================================================================


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
