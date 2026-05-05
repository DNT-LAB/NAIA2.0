import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from core.wildcard_processor import split_tags_smart


VIBE_CLUSTER_ROOT = Path("save/vibe_transfer_clusters")
VIBE_CLUSTER_NAME_RE = re.compile(r"^[A-Za-z0-9가-힣ㄱ-ㅎㅏ-ㅣ]+$")


class VibeClusterPromptError(ValueError):
    pass


@dataclass(frozen=True)
class VibeClusterPromptResult:
    applied: bool
    cluster_id: str = ""
    cluster_name: str = ""
    frame_count: int = 0


def is_valid_vibe_cluster_name(name: str) -> bool:
    return bool(VIBE_CLUSTER_NAME_RE.fullmatch(str(name or "")))


def _safe_cluster_id(raw_id: Any) -> str:
    text = Path(str(raw_id or "")).name
    safe = re.sub(r"[^A-Za-z0-9_.-]", "", text)
    return "" if safe in {"", ".", ".."} else safe


def _read_cluster_file(path: Path) -> Optional[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None
        cluster_id = _safe_cluster_id(data.get("id") or path.stem)
        name = str(data.get("name") or cluster_id).strip()
        if not cluster_id or not is_valid_vibe_cluster_name(name):
            return None
        data["_cluster_id"] = cluster_id
        data["_cluster_name"] = name
        data["_mtime"] = path.stat().st_mtime
        return data
    except Exception:
        return None


def list_vibe_clusters(root: Path = VIBE_CLUSTER_ROOT) -> list[dict]:
    if not root.exists():
        return []
    records = []
    for path in root.glob("*.json"):
        data = _read_cluster_file(path)
        if data:
            records.append(data)
    records.sort(key=lambda item: item.get("_mtime", 0), reverse=True)
    return records


def search_vibe_clusters(query: str, limit: int = 12, root: Path = VIBE_CLUSTER_ROOT) -> list[dict]:
    needle = str(query or "").strip().lower()
    ranked = []
    for index, data in enumerate(list_vibe_clusters(root)):
        name = str(data.get("_cluster_name") or "")
        lower = name.lower()
        if not needle:
            rank = 3
        elif lower == needle:
            rank = 0
        elif lower.startswith(needle):
            rank = 1
        elif needle in lower:
            rank = 2
        else:
            continue
        frames = data.get("frames") if isinstance(data.get("frames"), list) else []
        enabled = sum(1 for frame in frames if isinstance(frame, dict) and frame.get("is_enabled", True))
        description = str(data.get("description") or "")
        model = str(data.get("model") or "")
        ranked.append((rank, index, {
            "tag": name,
            "value": f"vibe:{name}",
            "count": enabled,
            "desc": description or f"{enabled}/{len(frames)} frames",
            "group": model,
            "cat": "",
            "preview": description or f"{model} - {enabled}/{len(frames)} enabled",
            "_wc_type": "vibe_cluster",
        }))
    ranked.sort(key=lambda item: (item[0], item[1]))
    return [item[2] for item in ranked[:limit]]


def resolve_vibe_cluster(name: str, root: Path = VIBE_CLUSTER_ROOT) -> dict:
    query = str(name or "").strip()
    if not query:
        raise VibeClusterPromptError("vibe: cluster name is empty")
    if not is_valid_vibe_cluster_name(query):
        raise VibeClusterPromptError("Vibe cluster name must use letters, numbers, and Korean only")

    matches = [
        data for data in list_vibe_clusters(root)
        if str(data.get("_cluster_name") or "").lower() == query.lower()
    ]
    if not matches:
        raise VibeClusterPromptError(f"Vibe cluster not found: {query}")
    if len(matches) > 1:
        raise VibeClusterPromptError(f"Vibe cluster name is duplicated: {query}")
    return matches[0]


def _closest_encoding(encodings: dict, information_extracted: Any) -> tuple[float, str] | None:
    pairs = []
    for key, encoding in encodings.items():
        if not encoding:
            continue
        try:
            pairs.append((float(key), str(encoding)))
        except Exception:
            continue
    if not pairs:
        return None
    pairs.sort(key=lambda item: item[0])
    try:
        target = float(information_extracted)
    except Exception:
        target = pairs[0][0]
    return min(pairs, key=lambda item: abs(item[0] - target))


def _cluster_to_vibe_params(data: dict, current_model: str) -> dict:
    frames = data.get("frames") if isinstance(data.get("frames"), list) else []
    reference_images = []
    reference_strengths = []
    reference_info = []

    for frame in frames:
        if not isinstance(frame, dict) or not frame.get("is_enabled", True):
            continue
        encodings = frame.get("encodings") if isinstance(frame.get("encodings"), dict) else {}
        selected = _closest_encoding(encodings, frame.get("information_extracted"))
        if not selected:
            continue
        ie_value, encoding = selected
        reference_images.append(encoding)
        try:
            strength = float(frame.get("reference_strength", 0.6))
        except Exception:
            strength = 0.6
        reference_strengths.append(strength)
        reference_info.append(ie_value)

    if not reference_images:
        name = data.get("_cluster_name") or data.get("name") or ""
        raise VibeClusterPromptError(f"Vibe cluster has no enabled encoded frames: {name}")

    normalize = bool(data.get("normalize_strength", False))
    if normalize:
        total = sum(reference_strengths)
        if total > 1.0:
            reference_strengths = [round(strength / total, 15) for strength in reference_strengths]

    params = {
        "normalize_reference_strength_multiple": normalize,
        "reference_image_multiple": reference_images,
        "reference_strength_multiple": reference_strengths,
    }
    if "NAID3" in str(current_model or ""):
        params["reference_information_extracted_multiple"] = reference_info
    return params


def extract_vibe_cluster_tags(prompt: str) -> tuple[str, list[str]]:
    tokens = split_tags_smart(str(prompt or ""))
    clean_tokens = []
    names = []
    for token in tokens:
        stripped = token.strip()
        if stripped.lower().startswith("vibe:"):
            names.append(stripped[5:].strip())
        else:
            clean_tokens.append(token)
    return ", ".join(clean_tokens), names


def apply_vibe_cluster_prompt_override(params: dict, root: Path = VIBE_CLUSTER_ROOT) -> VibeClusterPromptResult:
    prompt = params.get("input")
    if not isinstance(prompt, str) or "vibe:" not in prompt.lower():
        return VibeClusterPromptResult(applied=False)

    cleaned_prompt, names = extract_vibe_cluster_tags(prompt)
    if not names:
        return VibeClusterPromptResult(applied=False)
    if len(names) > 1:
        raise VibeClusterPromptError("Only one vibe: cluster tag is allowed per prompt")
    if str(params.get("api_mode", "NAI")).upper() != "NAI":
        raise VibeClusterPromptError("vibe: cluster override is available only in NAI mode")

    data = resolve_vibe_cluster(names[0], root)
    vibe_params = _cluster_to_vibe_params(data, str(params.get("model") or ""))
    params["input"] = cleaned_prompt
    params.update(vibe_params)
    if "reference_information_extracted_multiple" not in vibe_params:
        params.pop("reference_information_extracted_multiple", None)
    cluster_name = str(data.get("_cluster_name") or data.get("name") or names[0])
    cluster_id = str(data.get("_cluster_id") or data.get("id") or "")
    params["_vibe_cluster_override"] = {
        "id": cluster_id,
        "name": cluster_name,
        "frame_count": len(vibe_params["reference_image_multiple"]),
    }
    return VibeClusterPromptResult(
        applied=True,
        cluster_id=cluster_id,
        cluster_name=cluster_name,
        frame_count=len(vibe_params["reference_image_multiple"]),
    )
