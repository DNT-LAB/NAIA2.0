"""사용자가 추가한 UI 폰트 파일을 보관/열람/삭제하는 서비스.

Settings > Global > 폰트에서 업로드한 폰트 파일을 다룬다. 저장 위치는
``runtime_paths.ui_assets_dir / "fonts"`` 이며 리포지토리 소스는 건드리지 않는다
(runtime_write_policy: repository data/** 및 root 쓰기 금지).

CSS 쪽에서는 파일마다 합성 패밀리명(``naia-font-<id>``)을 부여해 @font-face 로 싣는다.
따라서 폰트 내부 name 테이블을 신뢰할 필요가 없고, woff2 처럼 압축된 포맷도 동일하게
다룰 수 있다. 내부 이름 파싱은 표시용 라벨을 예쁘게 만들기 위한 best-effort 로만 쓴다.
"""

from __future__ import annotations

import hashlib
import re
import struct
import threading
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote


# 확장자 allowlist. 브라우저가 실제로 렌더할 수 있는 포맷만 받는다.
ALLOWED_SUFFIXES: dict[str, str] = {
    ".otf": "font/otf",
    ".ttf": "font/ttf",
    ".ttc": "font/collection",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
}

# sfnt/woff 매직 바이트. 확장자만 믿지 않고 선두 4바이트를 함께 검사한다.
_MAGIC_SFNT = {
    b"OTTO",            # CFF outlines OpenType
    b"\x00\x01\x00\x00",  # TrueType outlines
    b"true",            # legacy macOS TrueType
    b"typ1",            # legacy Type 1 in sfnt
    b"ttcf",            # TrueType Collection
}
_MAGIC_WOFF = b"wOFF"
_MAGIC_WOFF2 = b"wOF2"

# CJK 폰트는 20MB 를 넘기도 한다. 그래도 상한은 둔다.
MAX_FONT_BYTES = 40 * 1024 * 1024
# 서버가 0.0.0.0 에 바인딩되므로(LAN/터널 접속 기능) 파일 하나의 크기만 막으면
# 이름만 바꿔 무한히 쌓을 수 있다. 저장소 전체에도 상한을 둔다.
MAX_TOTAL_FONT_BYTES = 300 * 1024 * 1024
MAX_FONT_COUNT = 40

_SAFE_STEM = re.compile(r"[^A-Za-z0-9가-힣._ -]+")


class FontValidationError(ValueError):
    """업로드된 파일이 폰트로 받아들여지지 않을 때."""


@dataclass(frozen=True)
class FontAsset:
    font_id: str
    filename: str
    label: str
    size: int
    media_type: str
    version: str

    def to_payload(self) -> dict:
        return {
            "id": self.font_id,
            "filename": self.filename,
            "label": self.label,
            "size": self.size,
            "media_type": self.media_type,
            # 프런트가 @font-face 에 그대로 쓰는 합성 패밀리명
            "family": f"naia-font-{self.font_id}",
            # 폰트 본문은 캐시(max-age=86400)되는데, 삭제 후 같은 이름으로 다시 올리면
            # URL 이 재사용돼 브라우저가 옛 바이트를 계속 쓴다. 내용이 바뀌면 값이 바뀌는
            # 버전 쿼리를 붙여 그 창을 막는다.
            "url": f"/fonts/{quote(self.filename)}?v={self.version}",
        }


def _sanitize_stem(value: str) -> str:
    stem = unicodedata.normalize("NFC", str(value or "").strip())
    stem = _SAFE_STEM.sub("_", stem).strip(" ._-")
    return stem[:64]


def _font_id_for(filename: str) -> str:
    """CSS 식별자로 안전한 소문자 슬러그 + **확장자를 포함한 파일명** 해시.

    해시가 필수인 이유: 슬러그만 쓰면 ASCII 가 아닌 이름이 전부 같은 값으로 붕괴한다
    ("나눔고딕"/"맑은 고딕"/"본고딕" → 전부 빈 문자열). 그러면
    (a) delete 가 첫 번째 일치 항목을 지워 **다른 폰트를 삭제**하고,
    (b) 합성 패밀리명(naia-font-<id>)이 겹쳐 엉뚱한 폰트가 렌더된다.

    해시 입력이 stem 이 아니라 **파일명 전체**인 이유: 저장 시 중복 판정은 확장자까지
    포함하므로 `Same.otf` 와 `Same.ttf` 가 공존할 수 있다. stem 만 해싱하면 이 둘이
    같은 id 가 되어 위와 똑같은 오삭제 경로가 다시 열린다.
    """
    normalized = unicodedata.normalize("NFC", Path(str(filename or "")).name)
    slug = unicodedata.normalize("NFKD", Path(normalized).stem)
    slug = re.sub(r"[^A-Za-z0-9]+", "-", slug).strip("-").lower()
    digest = hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:10]
    return f"{slug}-{digest}" if slug else f"font-{digest}"


def _detect_format(data: bytes, suffix: str) -> None:
    """매직 바이트와 확장자가 서로 맞는지 확인한다."""
    if len(data) < 4:
        raise FontValidationError("폰트 파일이 너무 작습니다.")
    head = data[:4]
    if suffix == ".woff2":
        if head != _MAGIC_WOFF2:
            raise FontValidationError("woff2 파일이 아닙니다.")
        return
    if suffix == ".woff":
        if head != _MAGIC_WOFF:
            raise FontValidationError("woff 파일이 아닙니다.")
        return
    if head in _MAGIC_SFNT:
        return
    if head in (_MAGIC_WOFF, _MAGIC_WOFF2):
        raise FontValidationError("확장자와 실제 폰트 형식이 다릅니다(woff 계열).")
    raise FontValidationError("지원하지 않는 폰트 형식입니다. (otf / ttf / woff / woff2)")


def _read_sfnt_display_name(data: bytes) -> str:
    """sfnt(name 테이블)에서 표시용 이름을 best-effort 로 뽑는다.

    실패하면 빈 문자열을 돌려주고 호출부가 파일명으로 대체한다. woff/woff2 는
    압축돼 있어 여기서 다루지 않는다.
    """
    try:
        if data[:4] not in _MAGIC_SFNT or data[:4] == b"ttcf":
            return ""
        num_tables = struct.unpack(">H", data[4:6])[0]
        name_offset = name_length = 0
        for index in range(num_tables):
            base = 12 + index * 16
            tag = data[base:base + 4]
            if tag == b"name":
                name_offset, name_length = struct.unpack(">II", data[base + 8:base + 16])
                break
        if not name_length or name_offset + name_length > len(data):
            return ""
        table = data[name_offset:name_offset + name_length]
        count, string_offset = struct.unpack(">HH", table[2:6])
        best = ""
        for index in range(count):
            rec = 6 + index * 12
            if rec + 12 > len(table):
                break
            platform_id, encoding_id, _lang, name_id, length, offset = struct.unpack(
                ">HHHHHH", table[rec:rec + 12]
            )
            # name_id 4 = Full name, 1 = Family name
            if name_id not in (1, 4):
                continue
            start = string_offset + offset
            raw = table[start:start + length]
            if not raw:
                continue
            if platform_id == 3 or (platform_id == 0):
                text = raw.decode("utf-16-be", errors="ignore")
            else:
                text = raw.decode("latin-1", errors="ignore")
            text = text.strip()
            if not text:
                continue
            if name_id == 4:
                return text
            best = best or text
        return best
    except Exception:
        return ""


class FontAssetService:
    """업로드된 UI 폰트의 저장소."""

    def __init__(self, fonts_dir: Path, bundled_dir: Path | None = None) -> None:
        self._fonts_dir = Path(fonts_dir)
        self._bundled_dir = Path(bundled_dir) if bundled_dir is not None else None
        # 업로드는 워커 스레드에서 실행되므로 동시 요청이 가능하다. 용량 검사 →
        # 파일명 결정 → .part 교체가 원자적이지 않으면 (a) 둘 다 이전 사용량을 보고
        # 상한을 넘기고 (b) 같은 이름을 고른 두 요청이 같은 .part 를 덮어써 서로의
        # 바이트를 응답한다. 저장 경로 전체를 하나의 락으로 감싼다.
        # RLock 인 이유: save_font 가 락을 쥔 채 _asset_for → _file_meta 를 호출하고
        # _file_meta 도 캐시 기록에 같은 락이 필요하다. 일반 Lock 이면 자기 자신에
        # 걸려 교착한다.
        self._write_lock = threading.RLock()
        # (파일명, mtime_ns, size) -> (표시용 라벨, 내용 해시 버전).
        # 둘 다 파일 본문이 필요하므로 한 번 읽어 함께 캐시한다.
        self._meta_cache: dict[tuple[str, int, int], tuple[str, str]] = {}

    @property
    def fonts_dir(self) -> Path:
        return self._fonts_dir

    def _ensure_dir(self) -> Path:
        self._fonts_dir.mkdir(parents=True, exist_ok=True)
        return self._fonts_dir

    def _invalidate(self, filename: str) -> None:
        """해당 파일명의 캐시 항목을 모두 버린다.

        캐시 키가 (이름, mtime, size)라서, 삭제 후 같은 이름·같은 크기로 다시 올렸는데
        파일시스템 타임스탬프 해상도가 낮아 mtime 까지 같으면 캐시가 그대로 적중해
        **옛 내용 해시**를 돌려준다. 그러면 내용 해시 버전을 도입한 의미가 사라지므로,
        파일을 쓰거나 지울 때 명시적으로 무효화한다."""
        for key in [key for key in self._meta_cache if key[0] == filename]:
            self._meta_cache.pop(key, None)

    def _file_meta(self, path: Path, stat_result) -> tuple[str, str]:
        """(표시용 라벨, 캐시 버전)을 한 번의 파일 읽기로 구한다.

        버전은 **내용 해시**다. mtime 을 쓰면 타임스탬프 해상도가 낮은 파일시스템
        (FAT/exFAT 는 2초)에서 삭제 후 곧바로 재업로드할 때 값이 같아져 URL 이
        재사용되고, 24시간 캐시 때문에 브라우저가 옛 폰트를 계속 쓴다.
        캐시 키에 mtime/size 를 쓰는 것은 파일이 안 바뀌었을 때 재읽기를 피하기 위함이다.
        """
        key = (path.name, stat_result.st_mtime_ns, stat_result.st_size)
        cached = self._meta_cache.get(key)
        if cached is not None:
            return cached
        label = ""
        version = ""
        try:
            data = path.read_bytes()
            version = hashlib.sha1(data).hexdigest()[:16]
            if path.suffix.lower() in (".otf", ".ttf"):
                label = _read_sfnt_display_name(data)
        except OSError:
            version = f"{stat_result.st_mtime_ns:x}"
        meta = (label or path.stem, version)
        # 읽는 동안 파일이 교체됐을 수 있다(업로드/삭제는 다른 워커 스레드).
        # 그대로 캐시하면 **옛 내용의 해시가 새 파일 키로 다시 들어가** 무효화가
        # 무의미해진다. 읽기 전후 stat 이 같을 때만 캐시에 남긴다.
        try:
            after = path.stat()
        except OSError:
            return meta
        if (after.st_mtime_ns, after.st_size) != (stat_result.st_mtime_ns, stat_result.st_size):
            return meta
        with self._write_lock:
            self._meta_cache[key] = meta
        return meta

    def _asset_for(self, path: Path) -> FontAsset:
        stat_result = path.stat()
        label, version = self._file_meta(path, stat_result)
        return FontAsset(
            font_id=_font_id_for(path.name),
            filename=path.name,
            label=label,
            size=stat_result.st_size,
            media_type=ALLOWED_SUFFIXES.get(path.suffix.lower(), "application/octet-stream"),
            version=version,
        )

    def list_fonts(self) -> dict:
        if not self._fonts_dir.is_dir():
            return {"fonts": []}
        assets: list[dict] = []
        for path in sorted(self._fonts_dir.iterdir(), key=lambda item: item.name.lower()):
            if not path.is_file() or path.suffix.lower() not in ALLOWED_SUFFIXES:
                continue
            try:
                assets.append(self._asset_for(path).to_payload())
            except OSError:
                continue
        return {"fonts": assets}

    def _assert_storage_budget(self, incoming: int) -> None:
        """저장소 전체 용량/개수 상한. 파일 하나만 막으면 이름을 바꿔 계속 쌓을 수 있다."""
        if not self._fonts_dir.is_dir():
            return
        count = 0
        used = 0
        for path in self._fonts_dir.iterdir():
            if not path.is_file() or path.suffix.lower() not in ALLOWED_SUFFIXES:
                continue
            count += 1
            try:
                used += path.stat().st_size
            except OSError:
                continue
        if count + 1 > MAX_FONT_COUNT:
            raise FontValidationError(f"추가할 수 있는 폰트는 최대 {MAX_FONT_COUNT}개입니다.")
        if used + incoming > MAX_TOTAL_FONT_BYTES:
            limit_mb = MAX_TOTAL_FONT_BYTES // (1024 * 1024)
            raise FontValidationError(f"폰트 저장 용량({limit_mb}MB)을 초과했습니다.")

    def assert_can_accept(self, declared_length: str | int | None = None) -> None:
        """본문을 받기 전에 저장소가 받아들일 수 있는지 미리 본다.

        가득 찬 상태에서도 40MB 를 다 받고 나서 거절하면 그만큼을 헛되이 메모리에
        올리게 된다. 여기서 통과해도 최종 판정은 save_font 안의 락에서 다시 한다."""
        try:
            incoming = int(declared_length) if declared_length is not None else 0
        except (TypeError, ValueError):
            incoming = 0
        self._assert_storage_budget(max(0, incoming))

    def save_font(self, filename: str, data: bytes) -> dict:
        raw_name = Path(str(filename or "")).name
        suffix = Path(raw_name).suffix.lower()
        if suffix not in ALLOWED_SUFFIXES:
            raise FontValidationError("지원하지 않는 확장자입니다. (otf / ttf / woff / woff2)")
        if not data:
            raise FontValidationError("빈 파일입니다.")
        if len(data) > MAX_FONT_BYTES:
            limit_mb = MAX_FONT_BYTES // (1024 * 1024)
            raise FontValidationError(f"폰트 파일이 너무 큽니다. (최대 {limit_mb}MB)")
        _detect_format(data, suffix)

        stem = _sanitize_stem(Path(raw_name).stem) or _read_sfnt_display_name(data) or "font"
        stem = _sanitize_stem(stem) or "font"

        # 용량 검사 → 이름 예약 → 교체를 한 덩어리로 묶는다(위 _write_lock 주석 참조).
        with self._write_lock:
            self._assert_storage_budget(len(data))
            target_dir = self._ensure_dir()
            target = target_dir / f"{stem}{suffix}"
            # 같은 이름이 있으면 덮어쓰지 않고 번호를 붙인다.
            counter = 2
            while target.exists():
                target = target_dir / f"{stem}-{counter}{suffix}"
                counter += 1
                if counter > 999:
                    raise FontValidationError("같은 이름의 폰트가 너무 많습니다.")

            temp = target.with_suffix(target.suffix + ".part")
            temp.write_bytes(data)
            temp.replace(target)
            self._invalidate(target.name)
            return {"ok": True, "font": self._asset_for(target).to_payload()}

    def delete_font(self, font_id: str) -> dict:
        # 넘어온 값은 이미 id 다. 여기서 다시 _font_id_for 를 태우면 id 를 stem 으로
        # 오해해 이중 슬러그화되므로, 정규화만 하고 그대로 비교한다.
        wanted = str(font_id or "").strip().lower()
        if not wanted or not re.fullmatch(r"[a-z0-9-]{1,128}", wanted):
            raise FileNotFoundError("폰트를 찾을 수 없습니다.")
        if not self._fonts_dir.is_dir():
            raise FileNotFoundError("폰트를 찾을 수 없습니다.")
        for path in sorted(self._fonts_dir.iterdir(), key=lambda item: item.name):
            if not path.is_file() or path.suffix.lower() not in ALLOWED_SUFFIXES:
                continue
            if _font_id_for(path.name) == wanted:
                path.unlink()
                self._invalidate(path.name)
                return {"ok": True, "id": wanted}
        raise FileNotFoundError("폰트를 찾을 수 없습니다.")

    def resolve_file(self, filename: str) -> tuple[Path, str]:
        """서빙용 경로 해석. 업로드분 우선, 없으면 번들 폰트로 폴백."""
        name = Path(str(filename or "")).name
        suffix = Path(name).suffix.lower()
        if not name or suffix not in ALLOWED_SUFFIXES:
            raise FileNotFoundError("폰트를 찾을 수 없습니다.")
        for root in (self._fonts_dir, self._bundled_dir):
            if root is None:
                continue
            try:
                candidate = (root / name).resolve()
                if not candidate.is_relative_to(root.resolve()):
                    continue
            except (OSError, ValueError):
                continue
            if candidate.is_file():
                return candidate, ALLOWED_SUFFIXES[suffix]
        raise FileNotFoundError("폰트를 찾을 수 없습니다.")
