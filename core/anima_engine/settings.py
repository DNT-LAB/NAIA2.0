"""Atomic settings, consent, and read-only model/LoRA discovery."""
from __future__ import annotations

import copy
import base64
import hashlib
import io
import json
import os
import struct
import tempfile
import time
import warnings
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from threading import RLock

from PIL import Image

from . import manifest
from .profile import ProfileError, number, validate_chain

LOCK = RLock()
DEFAULTS = {"version": 1, "engine_root": None, "model_dirs": [], "lora_dirs": [], "unet_dirs": [],
            "lora_chain": [], "idle_minutes": 30, "reserve_vram_gb": "auto"}
THUMB_MAX_BYTES = 10 * 1024 * 1024
_TRIGGER_CACHE = {}
_CATALOG_CACHE = {}
_THUMB_CACHE = {}
_UNET_CACHE = {}
_COMMON_TAGS = {"1girl", "1boy", "solo", "2girls", "2boys", "multiple girls", "multiple boys",
                "male focus", "female focus", "looking at viewer", "rating safe", "rating questionable",
                "rating explicit", "masterpiece", "best quality", "high quality"}


def read_json(path):
    try:
        with LOCK:
            value = json.loads(Path(path).read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _replace_file(source, target):
    # Windows readers/virus scanners may briefly deny replacing an open target.
    # Preserve the old file and fail normally if the denial persists.
    for attempt in range(6):
        try:
            os.replace(source, target)
            return
        except PermissionError as exc:
            if getattr(exc, "winerror", None) not in (5, 32, 33) or attempt == 5:
                raise
            time.sleep(0.02 * (attempt + 1))


def atomic_json(path, value):
    with LOCK:
        _atomic_json(path, value)


def _atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        _replace_file(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


@dataclass
class AnimaSettings:
    data: dict = field(default_factory=lambda: copy.deepcopy(DEFAULTS))

    def __getattr__(self, name):
        try:
            return self.data[name]
        except KeyError:
            raise AttributeError(name) from None


def load_settings(save_root):
    return AnimaSettings({**copy.deepcopy(DEFAULTS), **read_json(Path(save_root) / "anima_engine_user.json")})


def save_settings(save_root, updates):
    with LOCK:
        data = {**load_settings(save_root).data, **updates}
        number(data["idle_minutes"], "idle_minutes", 0, 720, integer=True)
        if data["reserve_vram_gb"] != "auto":
            number(data["reserve_vram_gb"], "reserve_vram_gb", 0, 64)
        for key in ("model_dirs", "lora_dirs", "unet_dirs"):
            if not isinstance(data[key], list) or not all(isinstance(x, str) and Path(x).is_absolute() for x in data[key]):
                raise ProfileError("PATH_INVALID", field=key)
        if data["engine_root"] is not None and not isinstance(data["engine_root"], str):
            raise ProfileError("PATH_INVALID", field="engine_root")
        for key in ("model_dirs", "lora_dirs", "unet_dirs"):
            data[key] = list(dict.fromkeys(data[key]))
        atomic_json(Path(save_root) / "anima_engine_user.json", data)
        return AnimaSettings(data)


def license_bundle():
    items = manifest.LICENSES
    pairs = sorted([[item["id"], item["sha256"]] for item in items])
    return hashlib.sha256(json.dumps(pairs, separators=(",", ":")).encode()).hexdigest()


def license_text(license_id):
    item = next((x for x in manifest.LICENSES if x["id"] == license_id), None)
    if item is None:
        raise KeyError(license_id)
    path = Path(__file__).parent / "licenses" / item["file"]
    if not path.is_file() and item.get("packaged_file"):
        path = path.with_name(item["packaged_file"])
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != item["sha256"]:
        raise ProfileError("HASH_MISMATCH", field=license_id)
    return data.decode("utf-8")


def consent_agreed(save_root):
    return read_json(Path(save_root) / "anima_engine_consent.json").get("bundle_sha256") == license_bundle()


def record_consent(save_root, consent, naia_version):
    if not isinstance(consent, dict) or consent.get("agreed") is not True or consent.get("bundle_sha256") != license_bundle():
        raise ProfileError("CONSENT_REQUIRED")
    for item in manifest.LICENSES:
        license_text(item["id"])
    atomic_json(Path(save_root) / "anima_engine_consent.json", {
        "version": 1, "bundle_sha256": license_bundle(),
        "items": [{"id": x["id"], "sha256": x["sha256"]} for x in manifest.LICENSES],
        "agreed_at": datetime.now().astimezone().isoformat(), "naia_version": naia_version, "client": "loopback"})


def verified_hash(path, engine_root, *, force=False, cancel=None):
    from core.llama_model_download import sha256_of
    path = Path(path).resolve()
    stat = path.stat()
    cache_path = Path(engine_root) / "state/verified.json"
    with LOCK:
        cache = read_json(cache_path)
        item = cache.get(str(path), {})
        if not force and item.get("size") == stat.st_size and item.get("mtime_ns") == stat.st_mtime_ns:
            return item.get("sha256")
    digest = sha256_of(path, cancel=cancel)
    after = path.stat()
    if (stat.st_size, stat.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ProfileError("HASH_MISMATCH", field=str(path))
    with LOCK:
        cache = read_json(cache_path)
        cache[str(path)] = {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns, "sha256": digest}
        atomic_json(cache_path, cache)
    return digest


def walk_files(root, *, depth=None):
    """Do not follow junctions/symlinks into unregistered directories."""
    root = Path(root)
    if not root.is_dir():
        return
    stack = [(root, 0)]
    while stack:
        folder, level = stack.pop()
        try:
            with os.scandir(folder) as entries:
                for entry in entries:
                    if entry.is_symlink() or getattr(entry, "is_junction", lambda: False)():
                        continue
                    if entry.is_file(follow_symlinks=False):
                        yield Path(entry.path)
                    elif entry.is_dir(follow_symlinks=False) and (depth is None or level < depth):
                        stack.append((Path(entry.path), level + 1))
        except OSError:
            continue


def lora_catalog(settings):
    # Scanning is shared by the N thumbnail requests for one library page.
    roots = ([Path(settings.engine_root) / "models/loras"] if settings.engine_root else []) + [Path(p) for p in settings.lora_dirs]
    key = tuple((str(root), _file_stamp(root)) for root in roots)
    with LOCK:
        cached = _CATALOG_CACHE.get(key)
        if cached and time.monotonic() - cached[0] < 2:
            return copy.deepcopy(cached[1])
        result = _scan_lora_catalog(settings)
        if len(_CATALOG_CACHE) >= 64:
            _CATALOG_CACHE.clear()
        _CATALOG_CACHE[key] = (time.monotonic(), result)
        return copy.deepcopy(result)


def _scan_lora_catalog(settings):
    roots = []
    if settings.engine_root:
        roots.append((Path(settings.engine_root) / "models/loras", "managed"))
    roots.extend((Path(p), Path(p).name) for p in settings.lora_dirs)
    found = {}
    seen = set()
    for root, source in roots:
        for path in walk_files(root):
            if path.suffix.lower() != ".safetensors":
                continue
            identity = str(path.resolve()).casefold()
            if identity in seen:
                continue
            seen.add(identity)
            name = path.relative_to(root).as_posix()
            key = name.casefold()
            if key in found:
                found[key]["conflict"] = True
            else:
                found[key] = {"name": name, "size": path.stat().st_size, "source": source,
                              "conflict": False, "path": str(path)}
    return list(found.values())



# ---- ANIMA 모델(UNet) — 관리형 엔진이 고를 수 있는 모델 ----
# ComfyUI 는 모델 이름을 목록 문자열과 **정확히** 대조한다(execution.py value_not_in_list). 그 목록은
# folder_paths.recursive_search 의 os.path.relpath 라 Windows 에서는 하위 폴더가 역슬래시다 — 같은 표기로 만든다.
# ANIMA 인지는 가리지 않는다(사용자 지정 09-28) — 개인 병합 모델일 수 있고, 안 맞는 파일이면 생성 단계에서 엔진이
# 오류로 끝낸다. 같은 이름이 앞 폴더에 있는 파일만 뺀다(ComfyUI 는 앞 폴더의 것을 연다).


def _receipt_unet(settings):
    if not settings.engine_root:
        return None
    unet = ((read_json(Path(settings.engine_root) / "receipt.json").get("models") or {}).get("unet") or {}).get("path")
    return Path(unet) if unet else None


def _folder_identity(folder):
    try:
        return str(Path(folder).resolve()).casefold()
    except OSError:
        return str(folder).casefold()


def unet_roots(settings, receipt_unet=None):
    """ComfyUI 가 diffusion_models 를 찾는 순서(write_model_config 와 같다) — 앞 폴더의 같은 이름이 이긴다."""
    roots = []
    if settings.engine_root:
        roots.append((Path(settings.engine_root) / "models" / "diffusion_models", "managed"))
    if receipt_unet is not None:
        roots.append((receipt_unet.parent, "reuse"))
    roots.extend((Path(p), Path(p).name) for p in settings.unet_dirs)
    unique, seen = [], set()
    for folder, source in roots:
        identity = _folder_identity(folder)
        if identity not in seen:
            seen.add(identity)
            unique.append((folder, source))
    return unique


def unet_catalog(settings):
    """{'available': [{name, size, source, path}], 'skipped': [{name, source, reason}]} — 기본 모델이 맨 앞.

    reason: shadowed(앞 폴더에 같은 이름 — ComfyUI 는 앞 폴더의 파일을 연다).
    """
    receipt_unet = _receipt_unet(settings)
    roots = unet_roots(settings, receipt_unet)
    key = tuple((str(root), _file_stamp(root)) for root, _ in roots) + (str(receipt_unet),)
    with LOCK:
        cached = _UNET_CACHE.get(key)
        if cached and time.monotonic() - cached[0] < 2:
            return copy.deepcopy(cached[1])
    result = _scan_unet_catalog(roots)
    with LOCK:
        if len(_UNET_CACHE) >= 64:
            _UNET_CACHE.clear()
        _UNET_CACHE[key] = (time.monotonic(), result)
    return copy.deepcopy(result)


def _scan_unet_catalog(roots):
    available, skipped, names, files = [], [], set(), set()
    for root, source in roots:
        for path in sorted(walk_files(root), key=lambda p: str(p).casefold()):
            if path.suffix.lower() != ".safetensors":
                continue
            identity = _folder_identity(path)
            if identity in files:
                continue
            files.add(identity)
            name = str(path.relative_to(root))
            if name.casefold() in names:            # ComfyUI 는 앞 폴더의 같은 이름 파일을 연다
                skipped.append({"name": name, "source": source, "reason": "shadowed"})
                continue
            names.add(name.casefold())
            try:
                size = path.stat().st_size
            except OSError:
                continue
            available.append({"name": name, "size": size, "source": source, "path": str(path)})
    default = manifest.MODELS[0]["filename"].casefold()
    available.sort(key=lambda x: (x["name"].casefold() != default, x["name"].casefold()))
    return {"available": available, "skipped": skipped}


def check_lora_header(path):
    try:
        with Path(path).open("rb") as handle:
            size = struct.unpack("<Q", handle.read(8))[0]
            if not 2 <= size <= min(16 * 1024 * 1024, Path(path).stat().st_size - 8):
                raise ValueError("header size")
            header = json.loads(handle.read(size))
        tensors = {k: v for k, v in header.items() if k != "__metadata__"}
        if not tensors:
            raise ValueError("empty tensors")
        data_size = Path(path).stat().st_size - 8 - size
        for value in tensors.values():
            start, end = value["data_offsets"]
            if not 0 <= start <= end <= data_size or not isinstance(value["shape"], list) or not value["dtype"]:
                raise ValueError("tensor offsets")
        return any(any(word in key.lower() for word in ("diffusion", "transformer", "dit", "lora_unet")) for key in tensors)
    except (OSError, ValueError, KeyError, TypeError, AttributeError, struct.error):
        raise ProfileError("LORA_INVALID", field=Path(path).name) from None


def _file_stamp(path):
    try:
        stat = path.stat()
        return (stat.st_size, stat.st_mtime_ns)
    except OSError:
        return None


def _plain_file(path):
    return path.is_file() and not path.is_symlink() and not getattr(path, "is_junction", lambda: False)()


def _header_metadata(path):
    # Only read the bounded safetensors header, never tensor data.
    with path.open("rb") as handle:
        size = struct.unpack("<Q", handle.read(8))[0]
        if not 2 <= size <= min(16 * 1024 * 1024, path.stat().st_size - 8):
            return {}
        metadata = json.loads(handle.read(size)).get("__metadata__", {})
        return metadata if isinstance(metadata, dict) else {}


def _trigger_words(words, source):
    result = []
    for word in words:
        if isinstance(word, str) and (word := word.strip()) and word not in [x["word"] for x in result]:
            result.append({"word": word, "source": source})
            if len(result) == 3:
                break
    return result


def _caption_triggers(metadata):
    from core.tag_rating_dist import load_rating_dist
    counts = load_rating_dist()
    # Missing optional tag data must not turn common captions into suggested triggers.
    if not counts:
        return []
    folders = metadata.get("ss_dataset_dirs", "{}")
    frequencies = metadata.get("ss_tag_frequency", "{}")
    folders = json.loads(folders) if isinstance(folders, str) else folders
    frequencies = json.loads(frequencies) if isinstance(frequencies, str) else frequencies
    if not isinstance(folders, dict) or not isinstance(frequencies, dict):
        return []
    candidates = []
    for folder, info in folders.items():
        total = info.get("img_count", 0) if isinstance(info, dict) else 0
        tags = frequencies.get(folder, {})
        if not isinstance(total, (int, float)) or total <= 0 or not isinstance(tags, dict):
            continue
        for tag, frequency in tags.items():
            if not isinstance(frequency, (int, float)) or not isinstance(tag, str):
                continue
            normalized = tag.strip().lower().replace("_", " ")
            values = counts.get(normalized, counts.get(normalized.replace(" ", "_"), []))
            if (frequency >= total * 0.95 and normalized not in _COMMON_TAGS
                    and isinstance(values, list) and sum(values) < 5000):
                candidates.append(tag)
    return _trigger_words(candidates, "caption")


def lora_triggers(path):
    path = Path(path)
    sidecar = path.with_suffix(".civitai.info")
    stamp = (_file_stamp(path), _file_stamp(sidecar))
    key = str(path.resolve())
    with LOCK:
        cached = _TRIGGER_CACHE.get(key)
        if cached and cached[0] == stamp:
            return copy.deepcopy(cached[1])
    metadata, result = {}, []
    try:
        metadata = _header_metadata(path)
        phrase = metadata.get("modelspec.trigger_phrase", "")
        if isinstance(phrase, str):
            result = _trigger_words(phrase.split(","), "modelspec")
    except (OSError, ValueError, TypeError, AttributeError, struct.error):
        pass
    if not result and _plain_file(sidecar) and sidecar.stat().st_size <= 2 * 1024 * 1024:
        words = read_json(sidecar).get("trainedWords", [])
        if isinstance(words, list):
            result = _trigger_words(words, "civitai")
    if not result:
        try:
            result = _caption_triggers(metadata) if metadata else []
        except (ValueError, TypeError, AttributeError):
            pass
    with LOCK:
        if len(_TRIGGER_CACHE) >= 2048:
            _TRIGGER_CACHE.clear()
        _TRIGGER_CACHE[key] = (stamp, result)
    return copy.deepcopy(result)


def resolve_lora(settings, name):
    if (not isinstance(name, str) or not name or "\\" in name or ":" in name
            or name.startswith("/") or any(part in ("", ".", "..") for part in name.split("/"))):
        raise ProfileError("LORA_NOT_FOUND")
    entry = next((x for x in lora_catalog(settings) if x["name"] == name), None)
    if entry is None:
        raise ProfileError("LORA_NOT_FOUND", field=name)
    if entry["conflict"]:
        raise ProfileError("LORA_NAME_CONFLICT", field=name)
    return entry


def _thumb_path(settings, name):
    if not settings.engine_root:
        raise ProfileError("ENGINE_NOT_READY")
    root = Path(settings.engine_root).resolve()
    key = base64.urlsafe_b64encode(name.encode("utf-8")).decode("ascii").rstrip("=")
    path = root / "state/lora_thumbs" / (key + ".png")
    if path.resolve().parent != root / "state/lora_thumbs":
        raise ProfileError("PATH_INVALID", field="lora_thumbs")
    return path


def lora_thumb(settings, entry):
    if entry["conflict"]:
        return None, None
    choices = []
    if settings.engine_root:
        choices.append(("naia", _thumb_path(settings, entry["name"])))
    source = Path(entry["path"])
    choices.extend(("sidecar", p) for p in (source.with_suffix(".png"), source.with_suffix(".preview.png")))
    for kind, path in choices:
        if _plain_file(path):
            return path, {"kind": kind, "version": path.stat().st_mtime_ns}
    return None, None


def png_thumbnail(data):
    try:
        if len(data) > THUMB_MAX_BYTES or not data.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError("PNG signature or size")
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as source:
                if source.format != "PNG":
                    raise ValueError("PNG required")
                source.load()
                image = source.convert("RGBA" if "A" in source.getbands() or "transparency" in source.info else "RGB")
                image.thumbnail((768, 768), Image.Resampling.LANCZOS)
                output = io.BytesIO()
                image.save(output, format="PNG")
                return output.getvalue()
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombWarning, Image.DecompressionBombError):
        raise ProfileError("LORA_THUMB_INVALID") from None


def read_lora_thumb(settings, name):
    path, info = lora_thumb(settings, resolve_lora(settings, name))
    if path is None or path.stat().st_size > THUMB_MAX_BYTES:
        raise ProfileError("LORA_NOT_FOUND", field=name)
    if info["kind"] == "naia":
        return path.read_bytes()
    key = (str(path), *_file_stamp(path))
    with LOCK:
        if key not in _THUMB_CACHE:
            data = png_thumbnail(path.read_bytes())
            # Bound decoded/re-encoded sidecar bytes, not just the entry count.
            if len(_THUMB_CACHE) >= 128 or sum(map(len, _THUMB_CACHE.values())) + len(data) > 32 * 1024 * 1024:
                _THUMB_CACHE.clear()
            _THUMB_CACHE[key] = data
        return _THUMB_CACHE[key]


def put_lora_thumb(settings, name, data):
    entry = resolve_lora(settings, name)
    data = png_thumbnail(data)
    path = _thumb_path(settings, entry["name"])
    with LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix="thumb-", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            _replace_file(tmp, path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
    return {"kind": "naia", "version": path.stat().st_mtime_ns}


def delete_lora_thumb(settings, name):
    entry = resolve_lora(settings, name)
    # This is solely our generated PNG, never a user-owned sidecar or LoRA file.
    with LOCK:
        _thumb_path(settings, entry["name"]).unlink(missing_ok=True)


def lora_folder(settings, name=None):
    if name is not None:
        return Path(resolve_lora(settings, name)["path"]).parent.resolve()
    if not settings.engine_root:
        raise ProfileError("ENGINE_NOT_READY")
    root = Path(settings.engine_root).resolve()
    folder = root / "models/loras"
    if folder.resolve() != folder:
        raise ProfileError("PATH_INVALID", field="loras")
    folder.mkdir(parents=True, exist_ok=True)
    # A folder opened before the first prepare is already an owned engine root.
    (root / "state").mkdir(exist_ok=True)
    return folder


def save_lora_chain(save_root, chain):
    settings = load_settings(save_root)
    catalog = {x["name"]: x for x in lora_catalog(settings)}
    validate_chain(chain, catalog)
    clean, warnings = [], []
    for item in chain:
        entry = catalog.get(item["name"])
        if entry is None:
            raise ProfileError("LORA_NOT_FOUND", field=item["name"])
        if entry["conflict"]:
            raise ProfileError("LORA_NAME_CONFLICT", field=item["name"])
        if not settings.engine_root:
            raise ProfileError("ENGINE_NOT_READY")
        if not check_lora_header(entry["path"]):
            warnings.append("ANIMA DiT LoRA 호환성을 확인해 주세요: " + item["name"])
        clean.append({"name": item["name"], "strength": item.get("strength", 1.0),
                      "enabled": item.get("enabled", True),
                      "sha256": verified_hash(entry["path"], settings.engine_root)})
    save_settings(save_root, {"lora_chain": clean})
    return clean, warnings


def quick_receipt(settings):
    if not settings.engine_root:
        return None
    root = Path(settings.engine_root)
    receipt = read_json(root / "receipt.json")
    # An interrupted repair must not advertise a previous receipt against a half-replaced runtime.
    journal = read_json(root / "state/job.json")
    if journal.get("error", {}).get("code") == "INTERRUPTED":
        return None
    if (receipt.get("profile_id"), receipt.get("profile_revision"), receipt.get("runtime_id")) != (
            manifest.PROFILE_ID, manifest.PROFILE_REVISION, manifest.RUNTIME_ID):
        return None
    python = root / "runtime" / manifest.RUNTIME_ID / "ComfyUI_windows_portable/python_embeded/python.exe"
    if not python.is_file():
        return None
    try:
        for model in manifest.MODELS:
            entry = receipt["models"][model["id"]]
            if entry["sha256"] != model["sha256"] or Path(entry["path"]).stat().st_size != model["size"]:
                return None
    except (KeyError, OSError, TypeError):
        return None
    return receipt


def write_model_config(settings, model_paths, path):
    # JSON scalars are YAML-safe, including Windows paths, colons and Unicode.
    root = Path(settings.engine_root)
    lines = ["naia_managed:", "  base_path: " + json.dumps(str(root / "models")),
             "  diffusion_models: diffusion_models", "  text_encoders: text_encoders", "  vae: vae", "  loras: loras"]
    for i, model in enumerate(manifest.MODELS):
        folder = Path(model_paths[model["id"]]).parent
        lines.extend([f"naia_reuse_{i}:", "  base_path: " + json.dumps(str(folder)), f"  {model['category']}: ."])
    for i, folder in enumerate(settings.lora_dirs):
        lines.extend([f"naia_loras_{i}:", "  base_path: " + json.dumps(folder), "  loras: ."])
    # ANIMA 모델 폴더 — 관리형 · 기본 모델 자리 뒤(ComfyUI 는 앞 폴더의 같은 이름을 연다, unet_roots 와 같은 순서)
    for i, folder in enumerate(settings.unet_dirs):
        lines.extend([f"naia_unets_{i}:", "  base_path: " + json.dumps(folder), "  diffusion_models: ."])
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write("\n".join(lines) + "\n")
        _replace_file(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)
    return path


def model_config_path(save_root):
    """ComfyUI 에 넘기는 모델 경로 파일 - user-data 마다 하나.

    엔진 폴더에 하나(state/extra_model_paths.yaml)를 두었더니, 같은 엔진을 쓰는 다른 NAIA(격리 시험 · 새 포터블 -
    설치를 가져다 쓴다)가 LoRA · 모델 폴더를 바꾸거나 설치를 돌릴 때 제 폴더로 통째 덮었다(09-29). 옛 파일은 그대로 둔다
    (옛 판 NAIA 가 아직 쓴다).
    """
    return Path(save_root) / "anima_engine_model_paths.yaml"


def write_instance_model_config(save_root, model_paths=None):
    """이 user-data 의 설정(LoRA · 모델 폴더)으로 모델 경로 파일을 쓰고 그 경로를 돌려준다 - 엔진을 켤 때마다 부른다.

    model_paths = 기본 모델 셋의 자리 {id: path}. 설치 중에는 계획의 것(영수증이 아직 없다 · 다른 폴더에서 재사용한 모델),
    그 뒤로는 영수증의 것.
    """
    settings = load_settings(save_root)
    if model_paths is None:
        model_paths = {k: v["path"] for k, v in ((quick_receipt(settings) or {}).get("models") or {}).items()}
    return write_model_config(settings, model_paths, model_config_path(save_root))
