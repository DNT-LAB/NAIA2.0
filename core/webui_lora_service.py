"""On-demand Forge LoRA catalog and NAIA's per-file thumbnail/metadata overrides."""

import hashlib
import json
import os
import subprocess
import sys
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path, PurePath, PurePosixPath, PureWindowsPath
from tempfile import NamedTemporaryFile
from urllib.parse import urlencode, urlsplit

import requests

from core.anima_engine.integration import save_root_of
from core.anima_engine.settings import atomic_json, png_from_image
from core.api_service import APIService
from core.headless_generation_service import credential_for_mode
from core.headless_payload_utils import is_loopback_host


OFFLINE = "WebUI 에 연결하지 못했습니다"
LOCAL_ONLY = "폴더 열기는 NAIA 와 WebUI 를 켠 PC 에서만 할 수 있습니다."
THUMB = "/sd_extra_networks/thumb"
IMAGE_TYPES = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
               "webp": "image/webp", "gif": "image/gif"}


def _triggers(metadata):
    if not isinstance(metadata, dict):
        return []
    phrase = metadata.get("modelspec.trigger_phrase")
    if isinstance(phrase, str):
        words = list(dict.fromkeys(word.strip() for word in phrase.split(",") if word.strip()))
        if words:
            return words
    frequencies = metadata.get("ss_tag_frequency")
    if isinstance(frequencies, str):
        try:
            frequencies = json.loads(frequencies)
        except ValueError:
            return []
    counts = Counter()
    if isinstance(frequencies, dict):
        for tags in frequencies.values():
            if isinstance(tags, dict):
                counts.update({tag: n for tag, n in tags.items()
                               if isinstance(n, (int, float)) and n > 0})
    return [tag for tag, _ in counts.most_common(3)]


def _forge_path(value):
    if not isinstance(value, str) or not value:
        return None
    path = PureWindowsPath(value) if PureWindowsPath(value).drive or "\\" in value else PurePosixPath(value)
    return path if path.is_absolute() and ".." not in path.parts else None


def _common_folder(parents):
    if not parents:
        return None
    first = parents[0]
    for folder in (first, *first.parents):
        if all(path.is_relative_to(folder) for path in parents):
            # A single occupied subtree can be deeper than Forge's actual LoRA root.
            for ancestor in (folder, *folder.parents):
                if ancestor.name.casefold() == "lora":
                    return ancestor
            return folder if folder.name and len(set(parents)) > 1 else None
    return None


def _preview(base, path):
    if path:
        stem = str(path.with_suffix(""))
        for suffix in ("", ".preview"):
            for ext, mime in IMAGE_TYPES.items():
                candidate = f"{stem}{suffix}.{ext}"
                # Forge serves GET. Stream only headers while discovering candidates.
                try:
                    with requests.get(base + THUMB, params={"filename": candidate}, stream=True,
                                      timeout=3, allow_redirects=False) as response:
                        if response.status_code == 200 and _image_type(response, mime):
                            return candidate
                except requests.RequestException:
                    return None
    return None


def _image_type(response, fallback):
    mime = response.headers.get("Content-Type", "").partition(";")[0].lower()
    if mime in IMAGE_TYPES.values():
        return mime
    return fallback if mime == "application/octet-stream" else None


@dataclass
class Entry:
    name: str
    alias: str
    path: PurePath | None
    triggers: list[str]
    preview: str | None = None


class WebuiLoraService:
    def __init__(self, context):
        self.context = context
        self.save = save_root_of(context)
        self.catalogs = {}
        self.catalog_lock = threading.Lock()
        self.meta_lock = threading.RLock()

    def base(self):
        return APIService._normalize_webui_url(credential_for_mode(self.context, "WEBUI"))

    def catalog(self, base, refresh=False):
        with self.catalog_lock:
            if refresh:
                self.catalogs.pop(base, None)
                requests.post(base + "/sdapi/v1/refresh-loras", timeout=10).raise_for_status()
            if base not in self.catalogs:
                response = requests.get(base + "/sdapi/v1/loras", timeout=3, allow_redirects=False)
                response.raise_for_status()
                try:
                    data = response.json()
                except ValueError as exc:
                    raise requests.RequestException(OFFLINE) from exc
                if not isinstance(data, list):
                    raise requests.RequestException(OFFLINE)
                entries = {}
                for row in data:
                    if not isinstance(row, dict) or not isinstance(row.get("name"), str) or not row["name"]:
                        continue
                    name = row["name"]
                    entries[name] = Entry(name, row.get("alias") or "", _forge_path(row.get("path")),
                                          _triggers(row.get("metadata")))
                with ThreadPoolExecutor(max_workers=8) as pool:
                    previews = pool.map(lambda entry: _preview(base, entry.path), entries.values())
                    for entry, preview in zip(entries.values(), previews):
                        entry.preview = preview
                parents = [entry.path.parent for entry in entries.values() if entry.path]
                self.catalogs[base] = entries, _common_folder(parents)
            return self.catalogs[base]

    def _meta(self):
        try:
            return json.loads((self.save / "webui_lora_meta.json").read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}

    def _png(self, name):
        key = hashlib.sha256(name.encode("utf-8")).hexdigest()
        return self.save / "webui_lora_thumbs" / (key + ".png")

    def listing(self, refresh=False):
        try:
            entries, root = self.catalog(self.base(), refresh)
        except (requests.RequestException, ValueError):
            return {"available": [], "warnings": [OFFLINE]}
        meta = self._meta()
        rows = []
        for name, entry in entries.items():
            parent = entry.path.parent if entry.path else None
            folder = parent.name if parent else ""
            if parent and root:
                folder = "" if parent == root else parent.relative_to(root).as_posix()
            try:
                version = self._png(name).stat().st_mtime_ns
            except FileNotFoundError:
                version = None
            params = {"name": name}
            if version is not None:
                params["v"] = version
            prefs = meta.get(name, {})
            rows.append({"name": name, "alias": entry.alias, "folder": folder, "triggers": entry.triggers,
                         "has_forge_preview": bool(entry.preview), "has_saved_thumb": version is not None,
                         "thumb_url": "/api/webui/loras/thumb?" + urlencode(params) if version is not None or entry.preview else "",
                         "favorite": prefs.get("favorite", False), "default_strength": prefs.get("default_strength", 0.8)})
        return {"available": rows, "warnings": []}

    def _entry(self, base, name):
        entries, _ = self.catalog(base)
        if name not in entries:
            raise FileNotFoundError("LoRA를 찾지 못했습니다.")
        return entries[name]

    def update_meta(self, name, changes):
        self._entry(self.base(), name)
        with self.meta_lock:
            meta = self._meta()
            prefs = meta.setdefault(name, {})
            prefs.update(changes)
            atomic_json(self.save / "webui_lora_meta.json", meta)
            return {"name": name, **prefs}

    def thumbnail(self, name):
        base = self.base()
        entry = self._entry(base, name)
        try:
            return self._png(name).read_bytes(), "image/png"
        except FileNotFoundError:
            pass
        if entry.preview:
            with requests.get(base + THUMB, params={"filename": entry.preview}, timeout=5,
                              allow_redirects=False) as response:
                mime = _image_type(response, IMAGE_TYPES[entry.preview.rsplit(".", 1)[1]])
                if response.status_code == 200 and mime:
                    return response.content, mime
        raise FileNotFoundError("미리보기가 없습니다.")

    def history(self, name):
        self._entry(self.base(), name)
        store = getattr(self.context, "result_store", None)
        return {"candidates": store.webui_lora_candidates(name) if store is not None else []}

    def save_history_thumb(self, name, history_id):
        self._entry(self.base(), name)
        store = getattr(self.context, "result_store", None)
        item = store.get_item(history_id) if store is not None else None
        if item is None or item.image is None:
            raise FileNotFoundError("히스토리에서 그 그림이 사라졌습니다. 다시 고르세요.")
        data = png_from_image(item.image)
        path = self._png(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = NamedTemporaryFile(dir=path.parent, delete=False)
        try:
            with tmp:
                tmp.write(data)
            os.replace(tmp.name, path)
        finally:
            Path(tmp.name).unlink(missing_ok=True)
        return {"ok": True}

    def delete_thumb(self, name):
        self._entry(self.base(), name)
        self._png(name).unlink(missing_ok=True)
        return {"ok": True}

    def open_folder(self, name, local):
        base = self.base()
        if not local or not is_loopback_host(urlsplit(base).hostname):
            return {"ok": False, "message": LOCAL_ONLY}
        entries, folder = self.catalog(base)
        if name:
            entry = entries.get(name)
            folder = entry.path.parent if entry and entry.path else None
        elif folder is None:
            parents = {entry.path.parent for entry in entries.values() if entry.path}
            if len(parents) == 1:
                folder = parents.pop()
        if folder is None or not Path(folder).is_dir():
            raise FileNotFoundError("LoRA 폴더를 찾지 못했습니다.")
        if os.name == "nt":
            os.startfile(str(folder))
        else:
            subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(folder)])
        return {"ok": True}
