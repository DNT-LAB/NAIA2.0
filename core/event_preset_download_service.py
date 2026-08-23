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


DOWNLOAD_URL = "https://huggingface.co/baqu2213/PoemForSmallFThings/resolve/main/NAIA/naia_prompt_preset"
THUMBNAIL_DOWNLOAD_URL = "https://huggingface.co/baqu2213/PoemForSmallFThings/resolve/main/NAIA/event_preset_thumbnail"

try:
    import certifi

    SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
except Exception:  # pragma: no cover - platform fallback
    SSL_CONTEXT = ssl.create_default_context()


class EventPresetDownloadService:
    """PyQt-free Event Preset downloader used by the headless Web Session."""

    def __init__(
        self,
        repo_root: Path | str,
        *,
        status_provider: Callable[[], dict[str, Any]],
        on_complete: Callable[[], None] | None = None,
        data_root: Path | str | None = None,
        thumbnail_root: Path | str | None = None,
    ):
        self.repo_root = Path(repo_root)
        self.data_root = Path(data_root) if data_root is not None else self.repo_root / "data"
        self.thumbnail_root = Path(thumbnail_root) if thumbnail_root is not None else self.repo_root / "data"
        self._status_provider = status_provider
        self._on_complete = on_complete
        self._lock = RLock()
        self._cancel = Event()
        self._thread: Thread | None = None
        self._main_only = False  # main(조합)만 받기 — 어시스트 B 참조용
        self._force_main = False
        self._state: dict[str, Any] = {
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

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            state = dict(self._state)
        try:
            status = self._status_provider()
            state["availability"] = status.get("dataAvailability", {}) if isinstance(status, dict) else {}
        except Exception:
            state["availability"] = {}
        return state

    def start(self, *, main_only: bool = False, force: bool = False) -> dict[str, Any]:
        # main_only=True → 조합 데이터(main, ~385MB)만. 썸네일(갤러리용 ~434MB)은
        # 건너뛴다. Ollama 어시스트의 B 실조합 참조는 main만 필요.
        status = self._status_provider()
        availability = status.get("dataAvailability", {}) if isinstance(status, dict) else {}
        main_ready = availability.get("main") == "ready"
        thumb_ready = availability.get("thumbnails") == "ready"
        if not force and main_ready and (main_only or thumb_ready):
            return self._set_state(
                active=False,
                phase="complete",
                percent=100,
                downloaded_mb=0.0,
                total_mb=0.0,
                message="Event Preset 데이터가 이미 설치되어 있습니다.",
                error="",
                done=True,
            )

        with self._lock:
            if self._state.get("active"):
                return dict(self._state)
            self._cancel.clear()
            self._main_only = bool(main_only)
            self._force_main = bool(force)
            self._state.update({
                "active": True,
                "phase": "main",
                "percent": 0,
                "downloaded_mb": 0.0,
                "total_mb": 0.0,
                "message": "다운로드 준비 중...",
                "error": "",
                "done": False,
                "updated_at": datetime.now().isoformat(timespec="seconds"),
            })
            worker = Thread(target=self._run, daemon=True, name="event-preset-download")
            self._thread = worker
            worker.start()
            return dict(self._state)

    def cancel(self) -> dict[str, Any]:
        state = self.snapshot()
        if state.get("active"):
            self._cancel.set()
            return self._set_state(message="다운로드 취소 중...")
        return state

    def _run(self) -> None:
        main_path = self.data_root / "event_preset" / "naia_prompt_preset"
        thumb_path = self.thumbnail_root / "event_preset_thumbnail"
        try:
            force_main = bool(self._force_main)
            if force_main or not main_path.exists() or not self._validate_event_preset_zip(main_path):
                self._download_file(
                    phase="main",
                    target_path=main_path,
                    url=DOWNLOAD_URL,
                    user_agent="NAIA/2.0.36 EventPreset Module",
                    validator=self._validate_event_preset_zip,
                    invalid_message="다운로드된 Event Preset 데이터가 손상되었습니다.",
                )
            else:
                self._set_state(phase="main", percent=100, message="Event Preset 데이터가 이미 존재합니다.")

            if self._main_only:
                # 어시스트 B 참조: 조합(main)만으로 충분 — 썸네일 다운로드 생략.
                self._set_state(phase="thumbnail", percent=100, message="썸네일은 건너뜁니다(조합 데이터만 사용).")
            elif not thumb_path.exists() or thumb_path.stat().st_size < 1_000_000:
                self._download_file(
                    phase="thumbnail",
                    target_path=thumb_path,
                    url=THUMBNAIL_DOWNLOAD_URL,
                    user_agent="NAIA/2.0.36 EventPreset Thumbnail",
                    validator=lambda path: path.exists() and path.stat().st_size >= 1_000_000,
                    invalid_message="다운로드된 썸네일 데이터가 손상되었습니다.",
                )
            else:
                self._set_state(phase="thumbnail", percent=100, message="썸네일 데이터가 이미 존재합니다.")

            if self._on_complete is not None:
                self._on_complete()
            self._set_state(
                active=False,
                phase="complete",
                percent=100,
                message="Event Preset 데이터 다운로드 완료",
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
            message = f"다운로드 실패: {exc}"
            self._set_state(active=False, message=message, error=message, done=False)

    def _download_file(
        self,
        *,
        phase: str,
        target_path: Path,
        url: str,
        user_agent: str,
        validator: Callable[[Path], bool],
        invalid_message: str,
    ) -> None:
        temp_path = target_path.with_name(target_path.name + ".download_tmp")
        target_path.parent.mkdir(parents=True, exist_ok=True)
        if temp_path.exists():
            temp_path.unlink()
        if target_path.exists() and not validator(target_path):
            target_path.unlink()

        self._set_state(
            phase=phase,
            percent=5,
            downloaded_mb=0.0,
            total_mb=0.0,
            message="다운로드 연결 중...",
        )
        request = urllib.request.Request(url, headers={"User-Agent": user_agent})
        try:
            with urllib.request.urlopen(request, timeout=30, context=SSL_CONTEXT) as response:
                total_size = int(response.headers.get("content-length", 0) or 0)
                total_mb = round(total_size / (1024 * 1024), 1) if total_size else 0.0
                downloaded = 0
                last_update = 0.0
                with temp_path.open("wb") as out_file:
                    while True:
                        if self._cancel.is_set():
                            raise InterruptedError("다운로드가 취소되었습니다.")
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        out_file.write(chunk)
                        downloaded += len(chunk)
                        now = time.time()
                        if now - last_update >= 0.25:
                            percent = min(90, 10 + int((downloaded * 80) / total_size)) if total_size else 10
                            downloaded_mb = round(downloaded / (1024 * 1024), 1)
                            message = (
                                f"다운로드 중... {percent}% ({downloaded_mb}/{total_mb} MB)"
                                if total_size else f"다운로드 중... {downloaded_mb} MB"
                            )
                            self._set_state(
                                percent=percent,
                                downloaded_mb=downloaded_mb,
                                total_mb=total_mb,
                                message=message,
                            )
                            last_update = now

            self._set_state(percent=92, message="검증 중...")
            if not validator(temp_path):
                raise ValueError(invalid_message)
            temp_path.replace(target_path)
            size_mb = round(target_path.stat().st_size / (1024 * 1024), 1)
            self._set_state(percent=100, downloaded_mb=size_mb, total_mb=size_mb, message="설치 완료")
        except Exception:
            try:
                if temp_path.exists():
                    temp_path.unlink()
            except Exception:
                pass
            raise

    def _set_state(self, **updates: Any) -> dict[str, Any]:
        with self._lock:
            self._state.update(updates)
            self._state["updated_at"] = datetime.now().isoformat(timespec="seconds")
            return dict(self._state)

    @staticmethod
    def _validate_event_preset_zip(path: Path) -> bool:
        try:
            with zipfile.ZipFile(path, "r") as archive:
                names = set(archive.namelist())
                return (
                    "base/event_taxonomy_v2_1.parquet" in names
                    and "base/tag_catalog.parquet" in names
                )
        except Exception:
            return False


__all__ = ["EventPresetDownloadService"]
