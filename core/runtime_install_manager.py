from __future__ import annotations

from datetime import datetime
from pathlib import Path
from threading import Event, RLock, Thread
from typing import Any, Callable
import ssl
import time
import urllib.error
import urllib.request
import zipfile

from app.backend.runtime import RuntimePaths


TAG_ARCHIVE_URL = "https://huggingface.co/baqu2213/PoemForSmallFThings/resolve/main/naia_tags.zip"
TAG_ARCHIVE_EXPECTED_COUNT = 150
BOOTSTRAP_DATA_FILES = (
    "clothes_list.txt",
    "color.txt",
    "characteristic_list.txt",
)
BOOTSTRAP_TAGLIST_GLOB = "*.json"

try:
    import certifi

    SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
except Exception:  # pragma: no cover - platform fallback
    SSL_CONTEXT = ssl.create_default_context()


class RuntimeInstallManager:
    """Initialize and install runtime-owned data for headless/Electron runs."""

    def __init__(
        self,
        runtime_paths: RuntimePaths,
        *,
        tag_archive_url: str = TAG_ARCHIVE_URL,
        expected_tag_files: int = TAG_ARCHIVE_EXPECTED_COUNT,
        on_tag_archive_complete: Callable[[], None] | None = None,
    ):
        self.runtime_paths = runtime_paths
        self.tag_archive_url = tag_archive_url
        self.expected_tag_files = int(expected_tag_files or 0)
        self._on_tag_archive_complete = on_tag_archive_complete
        self._lock = RLock()
        self._cancel = Event()
        self._thread: Thread | None = None
        self._download_state: dict[str, Any] = {
            "active": False,
            "phase": "idle",
            "percent": 0,
            "downloaded_mb": 0.0,
            "total_mb": 0.0,
            "message": "",
            "error": "",
            "done": False,
            "updated_at": "",
        }
        self._bootstrap_state: dict[str, Any] = {
            "copied": 0,
            "present": 0,
            "missing": [],
        }

    @property
    def tag_dir(self) -> Path:
        return self.runtime_paths.data_dir / "tags"

    def initialize(self) -> dict[str, Any]:
        self.runtime_paths.ensure_writable_dirs()
        self._copy_bootstrap_data_files()
        self.tag_dir.mkdir(parents=True, exist_ok=True)
        return self.snapshot()

    def snapshot(self) -> dict[str, Any]:
        self.runtime_paths.ensure_writable_dirs()
        count = self._tag_file_count()
        ready = self._tag_archive_ready(count)
        with self._lock:
            download = dict(self._download_state)
        return {
            "ok": True,
            "runtime": {
                "user_root": str(self.runtime_paths.user_root),
                "data_dir": str(self.runtime_paths.data_dir),
                "downloads_dir": str(self.runtime_paths.downloads_dir),
                "resource_root": str(self.runtime_paths.resource_root),
                "portable": bool(self.runtime_paths.portable),
                "data_initialized": self.runtime_paths.data_dir.exists(),
            },
            "tag_archive": {
                "ready": ready,
                "file_count": count,
                "expected_count": self.expected_tag_files,
                "missing_count": max(0, self.expected_tag_files - count) if self.expected_tag_files else 0,
                "target": str(self.tag_dir),
                "downloadable": bool(self.tag_archive_url),
                "url": self.tag_archive_url,
                "download": download,
            },
            "samples": {
                "app_data_template": str(self.runtime_paths.resource_path("app_data_template")),
                "release_samples": str(self.runtime_paths.resource_path("release_assets/samples")),
            },
            "bootstrap_data": dict(self._bootstrap_state),
        }

    def start_tag_archive_download(self, *, blocking: bool = False) -> dict[str, Any]:
        self.initialize()
        count = self._tag_file_count()
        if self._tag_archive_ready(count):
            return self._set_state(
                active=False,
                phase="complete",
                percent=100,
                downloaded_mb=0.0,
                total_mb=0.0,
                message="태그 데이터가 이미 설치되어 있습니다.",
                error="",
                done=True,
            )

        with self._lock:
            if self._download_state.get("active"):
                return dict(self._download_state)
            self._cancel.clear()
            self._download_state.update({
                "active": True,
                "phase": "tag_archive",
                "percent": 0,
                "downloaded_mb": 0.0,
                "total_mb": 0.0,
                "message": "태그 데이터 다운로드 준비 중...",
                "error": "",
                "done": False,
                "updated_at": datetime.now().isoformat(timespec="seconds"),
            })
            if blocking:
                pass
            else:
                worker = Thread(
                    target=self._run_tag_archive_download,
                    daemon=True,
                    name="runtime-tag-archive-download",
                )
                self._thread = worker
                worker.start()
                return dict(self._download_state)

        self._run_tag_archive_download()
        with self._lock:
            return dict(self._download_state)

    def cancel_tag_archive_download(self) -> dict[str, Any]:
        state = self.snapshot()["tag_archive"]["download"]
        if state.get("active"):
            self._cancel.set()
            return self._set_state(message="태그 데이터 다운로드 취소 중...")
        return state

    def _run_tag_archive_download(self) -> None:
        temp_zip = self.runtime_paths.downloads_dir / "naia_tags.zip.download_tmp"
        try:
            self.runtime_paths.ensure_writable_dirs()
            self.tag_dir.mkdir(parents=True, exist_ok=True)
            self._download_archive(temp_zip)
            extracted = self._extract_archive(temp_zip)
            if self.expected_tag_files and extracted < self.expected_tag_files:
                raise ValueError(f"태그 parquet 파일이 부족합니다 ({extracted}/{self.expected_tag_files})")
            if self._on_tag_archive_complete is not None:
                self._on_tag_archive_complete()
            self._set_state(
                active=False,
                phase="complete",
                percent=100,
                message=f"태그 데이터 설치 완료 ({extracted}개 파일)",
                error="",
                done=True,
            )
        except InterruptedError as exc:
            self._set_state(active=False, message=str(exc), error=str(exc), done=False)
        except urllib.error.HTTPError as exc:
            message = f"HTTP 오류 {exc.code}: {exc.reason}"
            self._set_state(active=False, message=message, error=message, done=False)
        except urllib.error.URLError as exc:
            message = f"네트워크 오류: {exc.reason}"
            self._set_state(active=False, message=message, error=message, done=False)
        except Exception as exc:
            message = f"태그 데이터 설치 실패: {exc}"
            self._set_state(active=False, message=message, error=message, done=False)
        finally:
            try:
                temp_zip.unlink(missing_ok=True)
            except Exception:
                pass

    def _download_archive(self, temp_zip: Path) -> None:
        temp_zip.parent.mkdir(parents=True, exist_ok=True)
        request = urllib.request.Request(
            self.tag_archive_url,
            headers={"User-Agent": "NAIA/2.0.1 RuntimeInstallManager"},
        )
        self._set_state(percent=5, message="태그 데이터 다운로드 연결 중...")
        open_kwargs = {"timeout": 30}
        if self.tag_archive_url.startswith("https://"):
            open_kwargs["context"] = SSL_CONTEXT
        with urllib.request.urlopen(request, **open_kwargs) as response:
            total_size = int(response.headers.get("content-length", 0) or 0)
            total_mb = round(total_size / (1024 * 1024), 1) if total_size else 0.0
            downloaded = 0
            last_update = 0.0
            with temp_zip.open("wb") as output:
                while True:
                    if self._cancel.is_set():
                        raise InterruptedError("태그 데이터 다운로드가 취소되었습니다.")
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    output.write(chunk)
                    downloaded += len(chunk)
                    now = time.time()
                    if now - last_update >= 0.25:
                        percent = min(85, 10 + int((downloaded * 75) / total_size)) if total_size else 10
                        downloaded_mb = round(downloaded / (1024 * 1024), 1)
                        self._set_state(
                            percent=percent,
                            downloaded_mb=downloaded_mb,
                            total_mb=total_mb,
                            message=(
                                f"태그 데이터 다운로드 중... {percent}% ({downloaded_mb}/{total_mb} MB)"
                                if total_size else f"태그 데이터 다운로드 중... {downloaded_mb} MB"
                            ),
                        )
                        last_update = now
        if temp_zip.stat().st_size < 1024:
            raise ValueError("다운로드된 태그 ZIP 파일이 너무 작습니다.")

    def _extract_archive(self, temp_zip: Path) -> int:
        self._set_state(percent=90, message="태그 데이터 압축 해제 중...")
        extracted = 0
        seen_names: set[str] = set()
        with zipfile.ZipFile(temp_zip, "r") as archive:
            members = [info for info in archive.infolist() if info.filename.endswith(".parquet")]
            if not members:
                raise ValueError("ZIP 파일에 parquet 파일이 없습니다.")
            for index, info in enumerate(members, 1):
                if self._cancel.is_set():
                    raise InterruptedError("태그 데이터 설치가 취소되었습니다.")
                filename = Path(info.filename).name
                if not filename or filename in seen_names or not filename.endswith(".parquet"):
                    raise ValueError(f"안전하지 않은 태그 ZIP 항목입니다: {info.filename}")
                seen_names.add(filename)
                target = self.tag_dir / filename
                temp_target = target.with_name(target.name + ".install_tmp")
                with archive.open(info) as source, temp_target.open("wb") as output:
                    while True:
                        chunk = source.read(1024 * 1024)
                        if not chunk:
                            break
                        output.write(chunk)
                temp_target.replace(target)
                extracted += 1
                percent = min(99, 90 + int((index * 9) / len(members)))
                self._set_state(percent=percent, message=f"태그 데이터 설치 중... {index}/{len(members)}")
        return extracted

    def _tag_file_count(self) -> int:
        if not self.tag_dir.exists():
            return 0
        return len([path for path in self.tag_dir.glob("tags_*.parquet") if path.is_file()])

    def _copy_bootstrap_data_files(self) -> None:
        source_data = self.runtime_paths.resource_path("data")
        target_data = self.runtime_paths.data_dir
        copied = 0
        present = 0
        missing: list[str] = []

        candidates: list[Path] = [source_data / relative for relative in BOOTSTRAP_DATA_FILES]
        taglist_dir = source_data / "taglist"
        if taglist_dir.is_dir():
            candidates.extend(sorted(taglist_dir.glob(BOOTSTRAP_TAGLIST_GLOB)))
        else:
            missing.append("taglist/*.json")

        seen: set[str] = set()
        for source in candidates:
            relative = source.relative_to(source_data).as_posix()
            if relative in seen:
                continue
            seen.add(relative)
            target = target_data / relative
            if not source.is_file():
                missing.append(relative)
                continue
            if target.exists():
                present += 1
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read_bytes())
            copied += 1

        self._bootstrap_state = {
            "copied": copied,
            "present": present,
            "missing": missing,
        }

    def _tag_archive_ready(self, count: int | None = None) -> bool:
        current = self._tag_file_count() if count is None else int(count)
        return current >= self.expected_tag_files if self.expected_tag_files else current > 0

    def _set_state(self, **updates: Any) -> dict[str, Any]:
        with self._lock:
            self._download_state.update(updates)
            self._download_state["updated_at"] = datetime.now().isoformat(timespec="seconds")
            return dict(self._download_state)


__all__ = [
    "BOOTSTRAP_DATA_FILES",
    "BOOTSTRAP_TAGLIST_GLOB",
    "RuntimeInstallManager",
    "TAG_ARCHIVE_EXPECTED_COUNT",
    "TAG_ARCHIVE_URL",
]
