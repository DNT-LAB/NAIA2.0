"""PyQt-free style thumbnail data service for the Remote Web Thumb tab."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from threading import RLock
from typing import Any
from urllib.parse import quote

from core.style_variants import STYLE_VARIANTS_APPROX_MB, is_webp, open_variants


class StyleThumbnailService:
    META_PATH = Path("data/taglist/style_meta_tags.json")
    THUMBNAILS_PATH = Path("data/taglist/style_thumbnails.json")

    def __init__(self, root: Path | str, variants_path: Path | None = None):
        self.root = Path(root)
        self.meta_path = self.root / self.META_PATH
        self.thumbnails_path = self.root / self.THUMBNAILS_PATH
        self._meta_cache: dict[str, Any] | None = None
        self._thumbnail_cache: dict[str, str] | None = None
        self._thumbnail_version = '0'
        self.variants_path = Path(variants_path) if variants_path is not None else None
        self.variants_lock = RLock()
        self._variants_signature = None
        self._variants_cache = None

    def _variants(self):
        """Called under variants_lock; keep only metadata and byte offsets resident."""
        path = self.variants_path
        if path is None or not path.is_file() or path.with_suffix(".corrupt").exists():
            self._variants_signature = self._variants_cache = None
            return None
        stat = path.stat()
        signature = (stat.st_size, stat.st_mtime_ns)
        if signature != self._variants_signature:
            self._variants_signature = self._variants_cache = None
            try:
                loaded = open_variants(path)
            except OSError:
                return None   # 잠금 · 일시 I/O - 손상이 아니다. 다음 요청에서 다시 연다(재리뷰 N1)
            except (ValueError, KeyError, TypeError):
                path.with_suffix(".corrupt").write_text(
                    "verification failed\n", encoding="utf-8", newline="\n")
                return None
            self._variants_cache = loaded
            self._variants_signature = signature
        return self._variants_cache

    @staticmethod
    def _variant_label(variant: dict) -> str:
        place, weight = variant["place"], variant["weight"]
        if place == "front":
            return "단일"
        return f"UC {weight:g}" if place == "uc" else f"POS {weight:+g}"

    def variants_payload(self, tag: str) -> dict:
        with self.variants_lock:
            loaded = self._variants()
            payload = {"ready": False, "tag": tag, "base": "", "gt_url": "",
                       "variants": [], "download": {"approx_mb": STYLE_VARIANTS_APPROX_MB}}
            if loaded is None:
                return payload
            metadata, _ = loaded
            if tag not in metadata["index"]:
                raise KeyError("Unknown style variants tag")
            info = metadata["index"][tag]
            # 묶음 판 표시 - 파일 크기 · 수정 시각(받을 때마다 바뀐다).
            ver = "".join(f"{n:x}" for n in (self._variants_signature or (0, 0)))
            payload.update(
                ready=True, base=info["base"],
                gt_url=f"/api/thumb/variant-image?gt={quote(info['base'], safe='')}&v={ver}",
                variants=[{
                    "col": v["col"], "place": v["place"], "weight": v["weight"],
                    "label": self._variant_label(v),
                    "url": f"/api/thumb/variant-image?tag={quote(tag, safe='')}&col={quote(v['col'], safe='')}&v={ver}",
                } for v in info["variants"]],
            )
            return payload

    def variant_image(self, tag: str, col: str) -> tuple[bytes, str]:
        with self.variants_lock:
            loaded = self._variants()
            if loaded is not None:
                metadata, index = loaded
                info = metadata["index"].get(tag, {})
                for variant in info.get("variants", []):
                    if variant["col"] == col:
                        return self._variant_bytes(index, variant["key"])
            raise FileNotFoundError("Style variant image not found")

    def variant_gt(self, base: str) -> tuple[bytes, str]:
        with self.variants_lock:
            loaded = self._variants()
            if loaded is not None:
                metadata, index = loaded
                if base in metadata["bases"]:
                    return self._variant_bytes(index, metadata["bases"][base]["gt"])
            raise FileNotFoundError("Style variant GT not found")

    def _variant_bytes(self, index, key: str) -> tuple[bytes, str]:
        try:
            encoded = index[key]
        except (KeyError, OSError):
            # 색인은 파일 잠금 · 묶음 교체 · 본문 손상(base64 · JSON)을 모두 KeyError 로 올린다. 잠금 · 교체는 손상이 아니고
            # (재리뷰 N1: 손상 표시를 남겨 멀쩡한 묶음을 영영 못 쓰게 했다), 본문 손상은 표시해야 다시 받을 수 있다
            # (3차 재리뷰 G1: 전부 일시 오류로 보내 깨진 묶음이 '준비됨' 으로 남았다) - 새로 열어 한 번 더 읽어 가른다.
            self._variants_signature = self._variants_cache = None
            if self._unreadable_while_file_opens(key):
                self._mark_variants_corrupt(f"unreadable entry: {key}")
            raise FileNotFoundError("Style variant image not readable") from None
        try:
            image = base64.b64decode(encoded, validate=True)
        except ValueError:
            image = None
        if image is None or not is_webp(image):
            # 바이트는 읽었는데 그림이 아니다 = 깨진 묶음 - 손상 표시를 남겨 '준비 안 됨' 으로 돌린다
            # (Codex 리뷰 #2: 404 만 내고 ready 로 남아 다시 받을 길이 없었다).
            self._variants_signature = self._variants_cache = None
            self._mark_variants_corrupt(f"unreadable image: {key}")
            raise FileNotFoundError("Style variant image not found")
        return image, "image/webp"

    def _unreadable_while_file_opens(self, key: str) -> bool:
        """그 그림 구간을 **직접** 읽어 본다(색인은 읽기 실패도 해석 실패도 KeyError 로 바꿔 올려서 못 가른다).
        읽기가 실패하면(파일 · 구간 잠금 · 일시 I/O) 손상인지 알 수 없으니 표시하지 않는다 - 4차 재리뷰: 파일이 열린다는
        것만 보고 손상으로 찍어, 구간 잠금이 풀린 뒤에도 멀쩡한 묶음을 못 썼다. 읽은 바이트가 JSON 문자열 · base64 ·
        WebP 머리로 풀리지 않을 때만 손상이다. 새 색인으로 읽으므로 묶음이 바뀐 경우는 새 묶음에서 그대로 읽힌다."""
        path = self.variants_path
        if path is None:
            return False
        try:
            _, fresh = open_variants(path)
        except OSError:
            return False
        except (KeyError, ValueError, TypeError):
            return True                      # 머리(메타)부터 깨졌다 - _variants 와 같은 판정
        span = fresh.offsets.get(key)
        if span is None:
            return True
        begin, finish = span
        try:
            with path.open("rb") as handle:
                handle.seek(begin)
                body = handle.read(finish - begin)
        except OSError:
            return False
        if len(body) != finish - begin:
            return False                     # 그 사이 줄어든 파일 - 교체 중일 수 있다
        try:
            value = json.loads(body)
            image = base64.b64decode(value, validate=True) if isinstance(value, str) else None
        except ValueError:
            image = None
        return image is None or not is_webp(image)

    def _mark_variants_corrupt(self, reason: str) -> None:
        if self.variants_path is None:
            return
        try:
            self.variants_path.with_suffix(".corrupt").write_text(f"{reason}\n", encoding="utf-8", newline="\n")
        except OSError:
            pass

    def _load_json(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            raise FileNotFoundError(str(path))
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict):
            raise ValueError(f"Invalid JSON object: {path}")
        return data

    def metadata(self) -> dict[str, Any]:
        if self._meta_cache is None:
            data = self._load_json(self.meta_path)
            if not isinstance(data.get("categories"), dict):
                data["categories"] = {}
            self._meta_cache = data
        return self._meta_cache

    def _image_url(self, key: str) -> str:
        """번들 썸네일 주소. 이미지 응답은 1시간 캐시라 파일이 바뀌면(업데이트 · 다시 굽기) 주소도 바뀌어야 한다 -
        같은 주소면 브라우저가 옛 그림을 계속 보여 준다(2026-10-26 실측: 잘라 구운 새 판과 옛 판이 섞였다)."""
        return f"/api/thumb/image?tag={quote(key, safe='')}&v={self._thumbnail_version}"

    def thumbnails(self) -> dict[str, str]:
        if self._thumbnail_cache is None:
            try:
                stat = self.thumbnails_path.stat()
                self._thumbnail_version = f"{stat.st_size:x}{int(stat.st_mtime):x}"
            except OSError:
                self._thumbnail_version = "0"
            data = self._load_json(self.thumbnails_path)
            self._thumbnail_cache = {
                str(key): str(value)
                for key, value in data.items()
                if isinstance(value, str) and value.strip()
            }
        return self._thumbnail_cache

    def categories(self) -> dict[str, Any]:
        categories = self.metadata().get("categories", {})
        return categories if isinstance(categories, dict) else {}

    def state(self) -> dict[str, Any]:
        categories = self.categories()
        thumbnail_keys = set(self.thumbnails().keys())
        category_payload = []
        for key, info in categories.items():
            if not isinstance(info, dict):
                continue
            tags = [str(tag) for tag in info.get("tags", []) if str(tag or "").strip()]
            available = [tag for tag in tags if tag in thumbnail_keys]
            category_payload.append({
                "key": str(key),
                "name": str(info.get("name") or key),
                "description": str(info.get("description") or ""),
                "total": len(tags),
                "available": len(available),
            })

        selected = ""
        for category in category_payload:
            if category["available"]:
                selected = category["key"]
                break
        if not selected and category_payload:
            selected = category_payload[0]["key"]

        return {
            "categories": category_payload,
            "selected": selected,
            "total_available": sum(category["available"] for category in category_payload),
            "bases": self._bases_payload(thumbnail_keys),
        }

    def _bases_payload(self, thumbnail_keys: set[str]) -> dict[str, Any]:
        """생성 기준(version 3) - 이름 · 설정 메모 · GT 이미지 주소. GT 는 썸네일 파일에 `__gt__:<기준>` 키로 들어 있다."""
        bases = self.metadata().get("bases", {})
        payload = {}
        for key, info in (bases.items() if isinstance(bases, dict) else []):
            if not isinstance(info, dict):
                continue
            gt_key = str(info.get("gt") or "")
            payload[str(key)] = {
                "name": str(info.get("name") or key),
                "note": str(info.get("note") or ""),
                "gt_url": self._image_url(gt_key) if gt_key in thumbnail_keys else "",
            }
        return payload

    def category_payload(self, category_key: str) -> dict[str, Any]:
        key = str(category_key or "").strip()
        categories = self.categories()
        if key not in categories:
            raise KeyError("Unknown style thumbnail category")
        info = categories[key]
        if not isinstance(info, dict):
            raise KeyError("Unknown style thumbnail category")
        thumbnail_data = self.thumbnails()
        tags = [
            str(tag)
            for tag in info.get("tags", [])
            if str(tag or "").strip() and str(tag) in thumbnail_data
        ]
        # 소제목(version 3 · Novel AI 공식): 썸네일이 있는 태그만 남긴다. single = 가중치 없이 한 장만 뽑은 묶음.
        sections = []
        for section in info.get("sections", []) if isinstance(info.get("sections"), list) else []:
            if not isinstance(section, dict):
                continue
            section_tags = [str(tag) for tag in section.get("tags", []) if str(tag) in thumbnail_data]
            if section_tags:
                sections.append({"name": str(section.get("name") or ""), "tags": section_tags,
                                 "single": bool(section.get("single"))})
        return {
            "key": key,
            "name": str(info.get("name") or key),
            "description": str(info.get("description") or ""),
            "base": str(info.get("base") or ""),
            "sections": sections,
            "tags": [self._tag_item(tag, thumbnail_data) for tag in tags],
        }

    def _tag_item(self, tag: str, thumbnail_data: dict[str, str]) -> dict[str, Any]:
        """카드 한 장. 빼기 그림(`__minus__:<태그>` · UC 2.5 없으면 UC 1)이 번들에 있으면 그 주소와 라벨도 싣는다 -
        큰 그림 세 장이 변형 묶음 없이도 뜬다(2026-10-26)."""
        item = {"tag": tag, "image_url": self._image_url(tag)}
        descriptions = self.metadata().get("descriptions", {})
        desc = descriptions.get(tag) if isinstance(descriptions, dict) else None
        if isinstance(desc, str) and desc.strip():
            item["desc"] = desc.strip()      # 큰 그림 미리보기 머리줄(자동완성과 같은 설명 · 2026-10-26)
        minus_key = f"__minus__:{tag}"
        if minus_key in thumbnail_data:
            labels = self.metadata().get("minus_labels", {})
            item["minus_url"] = self._image_url(minus_key)
            item["minus_label"] = str(labels.get(tag) or "") if isinstance(labels, dict) else ""
        return item

    @staticmethod
    def media_type(image_bytes: bytes) -> str:
        if image_bytes.startswith(b"\xff\xd8"):
            return "image/jpeg"
        if image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
            return "image/png"
        if image_bytes.startswith(b"RIFF") and image_bytes[8:12] == b"WEBP":
            return "image/webp"
        return "application/octet-stream"

    def image_payload(self, tag: str) -> tuple[bytes, str]:
        tag_name = str(tag or "").strip()
        if not tag_name:
            raise ValueError("tag is required")
        encoded = self.thumbnails().get(tag_name)
        if not encoded:
            raise FileNotFoundError(f"Style thumbnail not found: {tag_name}")
        if encoded.startswith("data:") and "," in encoded:
            encoded = encoded.split(",", 1)[1]
        image_bytes = base64.b64decode(encoded)
        return image_bytes, self.media_type(image_bytes)
