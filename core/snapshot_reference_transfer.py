"""스냅샷 전용 이미지 경계와 해시 병합으로 일반 업로드의 부수 효과를 피한다."""

from __future__ import annotations

import copy
import math
import re
from pathlib import Path
from typing import Any


def reference_image_parts(kind: str, frame: dict[str, Any]) -> tuple[str, ...]:
    file_hash = frame.get("file_hash")
    if not isinstance(file_hash, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", file_hash):
        raise ValueError("Malformed snapshot reference hash")
    if kind == "vibe_transfer":
        model = frame.get("target_model")
        if not isinstance(model, str) or not re.fullmatch(r"[A-Za-z0-9_-][A-Za-z0-9_.-]*", model):
            raise ValueError("Malformed snapshot vibe model")
        return kind, model, "images", f"{file_hash}.png"
    return kind, "images", f"{file_hash}.png"


def validate_reference_section(section: Any, kind: str) -> list[dict[str, Any]]:
    if not isinstance(section, dict) or not isinstance(section.get("frames"), list):
        raise ValueError("Malformed snapshot reference section")
    if kind == "vibe_transfer" and not isinstance(section.get("normalize_strength"), bool):
        raise ValueError("Malformed snapshot vibe normalization")
    for frame in section["frames"]:
        if not isinstance(frame, dict) or not isinstance(frame.get("is_enabled"), bool):
            raise ValueError("Malformed snapshot reference frame")
        reference_image_parts(kind, frame)
        numeric = ("reference_strength", "information_extracted") if kind == "vibe_transfer" else ("strength", "fidelity")
        for key in numeric:
            if key in frame and (isinstance(frame[key], bool) or not isinstance(frame[key], (int, float))
                                 or not math.isfinite(frame[key])):
                raise ValueError("Malformed snapshot reference value")
        if kind == "vibe_transfer" and not isinstance(frame.get("vibe_encodings", {}), dict):
            raise ValueError("Malformed snapshot vibe encodings")
    return section["frames"]


def capture_reference_images(context: Any, kind: str, section: dict[str, Any]) -> dict[str, bytes]:
    images = {}
    subfolder = "vibe" if kind == "vibe_transfer" else kind
    for frame in validate_reference_section(section, kind):
        source = context._existing_save_path(*reference_image_parts(kind, frame))
        key = f"refs/{subfolder}/{frame['file_hash']}.png"
        if key not in images and source.is_file():
            # 읽기 실패도 해당 구역의 실패로 격리한다. 저장 직전 원본이 바뀌는 경쟁도 피한다.
            images[key] = source.read_bytes()
    return images


def restore_reference_images(context: Any, kind: str, frames: list[dict[str, Any]], directory: Path) -> None:
    # file_path은 다른 PC의 절대 경로일 수 있으므로 스냅샷 내부 사본만 읽는다.
    for frame in frames:
        parts = reference_image_parts(kind, frame)
        if context._existing_save_path(*parts).exists():
            continue
        source = directory / parts[-1]
        if source.is_symlink() or source.resolve().parent != directory.resolve():
            raise ValueError("Snapshot reference image escapes its directory")
        if not source.is_file():
            continue
        image = source.read_bytes()
        target = context._save_path(*parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            # 조회 이후 파일이 생겨도 덮지 않는다. Storage의 정렬 시각도 보존한다.
            with target.open("xb") as output:
                output.write(image)
        except FileExistsError:
            pass


def merge_reference_frames(existing: list[dict[str, Any]], restored: list[dict[str, Any]]) -> list[dict[str, Any]]:
    hashes = {frame["file_hash"] for frame in restored}
    # 같은 해시가 여러 칸에 있으면 스냅샷의 칸별 값을 모두 보존한다.
    absent = [copy.deepcopy(frame) for frame in existing if frame.get("file_hash") not in hashes]
    for frame in absent:
        frame["is_enabled"] = False
    return restored + absent
