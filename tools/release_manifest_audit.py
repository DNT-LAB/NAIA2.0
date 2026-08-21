"""Audit a NAIA release directory against the draft include/exclude policy."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import fnmatch
import json
from pathlib import Path
from typing import Iterable


DEFAULT_MANIFEST = Path("release_assets/manifests/release_include_exclude_draft.json")
FORBIDDEN_PATH_PARTS = {
    ".claude",
    ".cloudflared_bin",
    ".experimental",
    ".pytest_cache",
    "_build",
    "__pycache__",
    "NAIA-Portable",
    "NAIA-Web",
    "docs",
    "legacy_desktop",
    "logs",
    "node_modules",
    "output",
    "refactor_docs",
    "refactor_plans",
    "release_package",
    "save",
    "smoke-user-data",
    "temp",
    "tests",
    "tmp",
    "venv",
    "wildcards",
}
FORBIDDEN_FILE_GLOBS = (
    "AGENTS.md",
    "CLAUDE.md",
    "*.md",
    "NAIA_cold_v4.py",
    "requirements-desktop-legacy*.txt",
    "result_dupl.py",
    "artist_thumbnail*.json",
    "*.xlsx",
    "*.naiv4vibe",
    "*.naiv4vibebundle",
    "00001.png",
    "20250827_*.png",
    "manual_*.png",
    "test*.png",
    "temp_image.png",
    "character_reference_*_result.png",
    "vibe_transfer_*_result.png",
    "stickman_canvas_tmp.webp",
    "~$*",
    "naia_temp_rows.parquet",
)
FORBIDDEN_PATH_GLOBS = (
    "core/context.py",
    "core/image_crud_controller.py",
    "core/mode_ware_manager.py",
    "core/tag_data_manager.py",
    "core/dll_fix.py",
    "tabs/comic_generator/*",
    "ui/variational/*",
    "experimental/ontology_visualizer/*",
    "temp/ezmode/*",
    "data/character_thumbnails/*",
    "data/event_preset/*",
    "data/event_preset_thumbnail",
    "data/tags/*",
    "data/tagger/*",
    "ui/event_preset/*",
    "ui/*/downloaded/*",
    "*/data/character_thumbnails/*",
    "*/data/event_preset/*",
    "*/data/event_preset_thumbnail",
    "*/data/tags/*",
    "*/data/tagger/*",
    "*/ui/event_preset/*",
    "*/ui/*/downloaded/*",
    "tmp_codex_*/*",
    "*/tmp_codex_*/*",
    "*/core/context.py",
    "*/core/image_crud_controller.py",
    "*/core/mode_ware_manager.py",
    "*/core/tag_data_manager.py",
    "*/core/dll_fix.py",
    "*/tabs/comic_generator/*",
    "*/ui/variational/*",
    "*/experimental/ontology_visualizer/*",
    "*/temp/ezmode/*",
    "app/electron/dist/*",
    "app/electron/node_modules/*",
    "*/app/electron/dist/*",
    "*/app/electron/node_modules/*",
)
ALLOWED_BOOTSTRAP_DATA_GLOBS = (
    "data/clothes_list.txt",
    "data/color.txt",
    "data/characteristic_list.txt",
    "data/taglist/*.json",
    "*/data/clothes_list.txt",
    "*/data/color.txt",
    "*/data/characteristic_list.txt",
    "*/data/taglist/*.json",
    # Reviewed clean-machine bundles (2.0.2): tag-search KR corpus + metadata
    # index + Character Viewer catalogs. Small/medium, not hosted on the public
    # mirror, so they ship with the payload instead of via a runtime download.
    "data/KR_tags.parquet",
    "data/e621_KR_tags.parquet",
    "data/tag_index/*",
    "data/copyright_groups.json",
    "data/character_analysis.json",
    "data/e621_data",
    # Search date-cutoff slider bucket→date map (data/tag_bucket_dates.json). Small
    # static index loaded by core/tag_bucket_dates.load_bucket_dates; without it the
    # slider has no buckets and stays at the placeholder.
    "data/tag_bucket_dates.json",
    # Prompt-boost static lookup tables (e621 Auto-Boost / Danbooru Auto-Weight)
    # loaded at generation time from the resource root; see prompt_boost_static_data
    # in runtime_asset_classification.json.
    "data/e621_boost_static.py",
    "data/danbooru_tag_counts_by_rating.json",
    # Interactive 모드가 런타임에 읽는 것들. 없으면 그리드가 통째로 비거나
    # 추천 줄이 사라진다 — include 에는 있었는데 이 예외 목록에서 빠져 있었다.
    #   interactive_tags        태그 그룹/서브그룹/관계 사전 (TagRelationRanker)
    #   interactive_thumbnails  썸네일 팩 (10,458키)
    #   tag_cooccurrence        사전 칩 '함께 쓰이는 것' (없으면 그 줄이 빈다)
    #   character_presets       캐릭터 프리셋 슬롯 배정표
    #   character_preview_thumbs 캐릭터 뷰어 폴백 썸네일 (사용자 것이 없을 때)
    "data/interactive_tags.json",
    "data/interactive_thumbnails.json",
    "data/tag_cooccurrence.json",
    "data/character_presets.json",
    "data/character_preview_thumbs.json",
    # v2.0.34 검토: Interactive 확장이 런타임에 읽는 정적 표 5개(합 3.8MB).
    # include 패턴에는 이미 있었는데 이 예외 목록에서 빠져 게이트가 막았다.
    # 공개 미러에 올린 것이 아니라 페이로드로 실어야 한다 — 안 실으면 배포판에서
    # 해당 기능이 **조용히** 죽는다(clothing_harmony 가 실제로 그랬다).
    #   interactive_axis_tags        축/서브그룹 어휘 (없으면 그리드가 빈다)
    #   interactive_adult_tags       성인 축 분류
    #   interactive_clothing_harmony 의상 '함께 쓰는 것'/'같이 안 쓰는 것'
    #   interactive_tag_harmony      의상 밖 어휘까지 넓힌 추천 표
    #   interactive_preset_facts     프리셋 근거 표
    "data/interactive_axis_tags.json",
    "data/interactive_adult_tags.json",
    "data/interactive_clothing_harmony.json",
    "data/interactive_tag_harmony.json",
    "data/interactive_preset_facts.json",
    # NOTE: Sequence dataset (data/sequence_preset/events_v1.parquet) is NOT shipped —
    # it is downloaded on demand from HuggingFace (core/sequence_download_service.py),
    # mirroring Event Preset. So it is intentionally absent from this allowlist.
    "*/data/KR_tags.parquet",
    "*/data/e621_KR_tags.parquet",
    "*/data/tag_index/*",
    "*/data/copyright_groups.json",
    "*/data/character_analysis.json",
    "*/data/e621_data",
    "*/data/tag_bucket_dates.json",
    "*/data/e621_boost_static.py",
    "*/data/danbooru_tag_counts_by_rating.json",
    "*/data/interactive_tags.json",
    "*/data/interactive_thumbnails.json",
    "*/data/tag_cooccurrence.json",
    "*/data/character_presets.json",
    "*/data/character_preview_thumbs.json",
    # v2.0.34 Interactive 확장분(위 bare 패턴과 짝) — 스테이징 경로는
    # `resources/naia-backend/data/...` 라 `*/data/...` 형태가 따로 필요하다.
    "*/data/interactive_axis_tags.json",
    "*/data/interactive_adult_tags.json",
    "*/data/interactive_clothing_harmony.json",
    "*/data/interactive_tag_harmony.json",
    "*/data/interactive_preset_facts.json",
    # 캐릭터 생성 벤치 랜덤 슬롯 풀(2.0.33) - 없으면 클린 설치에서 랜덤생성이
    # 404로 죽는다. SOURCE_BOOTSTRAP_PATHS/release_include_exclude_draft/
    # runtime_asset_classification과 함께 4곳 등록 세트.
    "data/random_character.txt",
    "data/random_outfits.txt",
    "*/data/random_character.txt",
    "*/data/random_outfits.txt",
)
FORBIDDEN_PACKAGE_NAMES = (
    "PyQt6",
    "PyQt6-Qt6",
    "PyQt6-WebEngine",
    "PyQt6-WebEngine-Qt6",
    "PyQt6_sip",
    "PyQt6-QScintilla",
)


@dataclass(frozen=True)
class ReleaseViolation:
    path: str
    reason: str


def load_manifest(path: str | Path = DEFAULT_MANIFEST) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _relative_files(root: Path) -> Iterable[Path]:
    for path in root.rglob("*"):
        if path.is_file():
            yield path.relative_to(root)
        elif path.is_dir() and not any(path.iterdir()):
            yield path.relative_to(root)


def _has_forbidden_part(relative: Path) -> str | None:
    if relative.parts and relative.parts[0] == "user-data" and len(relative.parts) > 1:
        return "portable user-data must not contain bundled runtime state"
    is_python_runtime = len(relative.parts) >= 2 and relative.parts[0] == "resources" and relative.parts[1] == "python"
    for part in relative.parts:
        if is_python_runtime and part == "venv":
            continue
        if part in FORBIDDEN_PATH_PARTS:
            return f"forbidden runtime/development path part: {part}"
        if part in FORBIDDEN_PACKAGE_NAMES:
            return f"forbidden desktop dependency package: {part}"
    return None


def _has_forbidden_filename(relative: Path) -> str | None:
    name = relative.name
    for pattern in FORBIDDEN_FILE_GLOBS:
        if fnmatch.fnmatchcase(name, pattern):
            return f"forbidden file pattern: {pattern}"
    return None


def _has_forbidden_path_pattern(relative: Path) -> str | None:
    posix = relative.as_posix()
    if len(relative.parts) >= 2 and relative.parts[0] == "resources" and relative.parts[1] == "python":
        return None
    if any(fnmatch.fnmatchcase(posix, pattern) for pattern in ALLOWED_BOOTSTRAP_DATA_GLOBS):
        return None
    for index, part in enumerate(relative.parts):
        if part == "data":
            next_part = relative.parts[index + 1] if len(relative.parts) > index + 1 else ""
            if next_part != "source":
                return "forbidden runtime data path: data/**"
    for pattern in FORBIDDEN_PATH_GLOBS:
        if fnmatch.fnmatchcase(posix, pattern):
            return f"forbidden path pattern: {pattern}"
    return None


def audit_release_directory(
    release_root: str | Path,
    *,
    manifest_path: str | Path = DEFAULT_MANIFEST,
) -> list[ReleaseViolation]:
    root = Path(release_root)
    if not root.exists():
        return [ReleaseViolation(str(root), "release root does not exist")]
    if not root.is_dir():
        return [ReleaseViolation(str(root), "release root is not a directory")]

    return audit_release_paths(_relative_files(root), manifest_path=manifest_path)


def audit_release_paths(
    relative_paths: Iterable[str | Path],
    *,
    manifest_path: str | Path = DEFAULT_MANIFEST,
) -> list[ReleaseViolation]:
    manifest = load_manifest(manifest_path)
    manifest_rules = "\n".join(manifest.get("hard_rules", []))
    violations: list[ReleaseViolation] = []

    if "PyQt6" not in manifest_rules or "legacy_desktop" not in manifest_rules:
        violations.append(
            ReleaseViolation(str(manifest_path), "manifest hard rules do not mention PyQt6 and legacy_desktop")
        )

    for item in relative_paths:
        relative = Path(item)
        # Bundled Grok (progrok) runtime ships like resources/python — a trusted vendored
        # runtime materialized at release time (npm ci from a pinned tarball). Its node_modules
        # tree contains README.md / dist / etc. that the generic include/exclude policy would
        # flag, so exempt the whole resources/progrok-runtime subtree the way resources/python
        # is exempted from the path-pattern checks.
        parts = relative.parts
        if len(parts) >= 2 and parts[0] == "resources" and parts[1] == "progrok-runtime":
            continue
        reason = (
            _has_forbidden_path_pattern(relative)
            or _has_forbidden_part(relative)
            or _has_forbidden_filename(relative)
        )
        if reason:
            violations.append(ReleaseViolation(relative.as_posix(), reason))

    return violations


def audit_payload(release_root: str | Path, *, manifest_path: str | Path = DEFAULT_MANIFEST) -> dict:
    violations = audit_release_directory(release_root, manifest_path=manifest_path)
    return {
        "ok": not violations,
        "release_root": str(Path(release_root)),
        "manifest": str(Path(manifest_path)),
        "violations": [violation.__dict__ for violation in violations],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit a NAIA release directory.")
    parser.add_argument("release_root", help="Directory containing a staged or packaged NAIA release.")
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST), help="Release include/exclude manifest path.")
    args = parser.parse_args(argv)

    payload = audit_payload(args.release_root, manifest_path=args.manifest)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
