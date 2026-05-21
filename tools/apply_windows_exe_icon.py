"""Apply a Windows ICO resource to an existing executable.

The Electron portable build keeps ``signAndEditExecutable`` disabled to avoid
implicit code-signing/toolchain side effects for bundled Python executables.
This helper updates only the final NAIA.exe icon resource after packaging.
"""

from __future__ import annotations

import argparse
import ctypes
from dataclasses import dataclass
import json
import os
from pathlib import Path
import struct
import sys
from typing import Any


RT_ICON = 3
RT_GROUP_ICON = 14
LANG_NEUTRAL = 0


@dataclass(frozen=True)
class IconImage:
    width: int
    height: int
    color_count: int
    reserved: int
    planes: int
    bit_count: int
    data: bytes


def _load_ico(path: Path) -> list[IconImage]:
    data = path.read_bytes()
    if len(data) < 6:
        raise ValueError(f"ICO file is too small: {path}")
    reserved, icon_type, count = struct.unpack_from("<HHH", data, 0)
    if reserved != 0 or icon_type != 1 or count <= 0:
        raise ValueError(f"Invalid ICO header: {path}")
    images: list[IconImage] = []
    offset = 6
    for _ in range(count):
        if offset + 16 > len(data):
            raise ValueError(f"ICO directory is truncated: {path}")
        width, height, color_count, entry_reserved, planes, bit_count, size, image_offset = struct.unpack_from(
            "<BBBBHHII",
            data,
            offset,
        )
        offset += 16
        if image_offset + size > len(data):
            raise ValueError(f"ICO image data is truncated: {path}")
        images.append(
            IconImage(
                width=width,
                height=height,
                color_count=color_count,
                reserved=entry_reserved,
                planes=planes,
                bit_count=bit_count,
                data=data[image_offset : image_offset + size],
            )
        )
    return images


def _group_icon_resource(images: list[IconImage], *, base_icon_id: int) -> bytes:
    payload = bytearray(struct.pack("<HHH", 0, 1, len(images)))
    for index, image in enumerate(images):
        payload.extend(
            struct.pack(
                "<BBBBHHIH",
                image.width,
                image.height,
                image.color_count,
                image.reserved,
                image.planes,
                image.bit_count,
                len(image.data),
                base_icon_id + index,
            )
        )
    return bytes(payload)


def _resource_id(value: int) -> ctypes.c_void_p:
    return ctypes.c_void_p(value)


def _raise_last_error(action: str) -> None:
    error = ctypes.get_last_error()
    raise ctypes.WinError(error, action)


def apply_windows_exe_icon(
    exe_path: str | Path,
    icon_path: str | Path,
    *,
    group_icon_id: int = 1,
    base_icon_id: int = 1,
    language_id: int = LANG_NEUTRAL,
) -> dict[str, Any]:
    exe = Path(exe_path)
    icon = Path(icon_path)
    violations: list[dict[str, str]] = []
    if os.name != "nt":
        violations.append({"path": str(exe), "reason": "Windows icon resources can only be updated on Windows"})
    if not exe.is_file():
        violations.append({"path": str(exe), "reason": "target executable is missing"})
    if not icon.is_file():
        violations.append({"path": str(icon), "reason": "icon file is missing"})
    if violations:
        return {"ok": False, "exe": str(exe), "icon": str(icon), "violations": violations}

    try:
        images = _load_ico(icon)
        group_payload = _group_icon_resource(images, base_icon_id=base_icon_id)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        begin_update = kernel32.BeginUpdateResourceW
        begin_update.argtypes = [ctypes.c_wchar_p, ctypes.c_bool]
        begin_update.restype = ctypes.c_void_p
        update_resource = kernel32.UpdateResourceW
        update_resource.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_uint16,
            ctypes.c_void_p,
            ctypes.c_uint32,
        ]
        update_resource.restype = ctypes.c_bool
        end_update = kernel32.EndUpdateResourceW
        end_update.argtypes = [ctypes.c_void_p, ctypes.c_bool]
        end_update.restype = ctypes.c_bool

        handle = begin_update(str(exe), False)
        if not handle:
            _raise_last_error("BeginUpdateResourceW")
        try:
            for index, image in enumerate(images):
                resource_id = base_icon_id + index
                buffer = ctypes.create_string_buffer(image.data)
                ok = update_resource(
                    handle,
                    _resource_id(RT_ICON),
                    _resource_id(resource_id),
                    language_id,
                    buffer,
                    len(image.data),
                )
                if not ok:
                    _raise_last_error(f"UpdateResourceW RT_ICON {resource_id}")
            group_buffer = ctypes.create_string_buffer(group_payload)
            ok = update_resource(
                handle,
                _resource_id(RT_GROUP_ICON),
                _resource_id(group_icon_id),
                language_id,
                group_buffer,
                len(group_payload),
            )
            if not ok:
                _raise_last_error(f"UpdateResourceW RT_GROUP_ICON {group_icon_id}")
            if not end_update(handle, False):
                handle = None
                _raise_last_error("EndUpdateResourceW")
            handle = None
        finally:
            if handle:
                end_update(handle, True)
    except Exception as exc:
        return {
            "ok": False,
            "exe": str(exe),
            "icon": str(icon),
            "violations": [{"path": str(exe), "reason": f"icon resource update failed: {exc}"}],
        }

    return {
        "ok": True,
        "exe": str(exe),
        "icon": str(icon),
        "group_icon_id": group_icon_id,
        "base_icon_id": base_icon_id,
        "image_count": len(images),
        "violations": [],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Apply a Windows ICO resource to an executable.")
    parser.add_argument("exe", help="Target executable path.")
    parser.add_argument("icon", help="ICO file path.")
    args = parser.parse_args(argv)

    payload = apply_windows_exe_icon(args.exe, args.icon)
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
