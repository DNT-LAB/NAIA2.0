"""Sequence 데이터(events_v1.parquet) 다운로드 — Event Preset 다운로더 미러.

시퀀스 데이터는 빌드에 싣지 않고 HuggingFace 에서 온디맨드로 받는다(Event Preset 동일 정책).
단일 parquet 파일이라 EventPresetDownloadService 보다 단순(썸네일 없음). 스레드+진행률+
검증(parquet 메타로 컬럼/행 확인) 후 runtime data_dir 에 설치하고, 완료 시 서비스 reload.
"""
from __future__ import annotations

import os
import ssl
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from threading import Event, RLock, Thread
from typing import Any, Callable

# HF 호스팅 URL (Event Preset 과 동일 레포). 필요 시 env 로 오버라이드.
DOWNLOAD_URL = os.environ.get(
    "NAIA_SEQ_DOWNLOAD_URL",
    "https://huggingface.co/baqu2213/PoemForSmallFThings/resolve/main/NAIA/naia_sequence_events_v1.parquet",
)
TARGET_RELPATH = Path("sequence_preset") / "events_v1.parquet"

try:
    import certifi

    SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
except Exception:  # pragma: no cover
    SSL_CONTEXT = ssl.create_default_context()


class SequenceDownloadService:
    """PyQt-free Sequence 데이터 다운로더 (헤드리스 Web Session)."""

    def __init__(
        self,
        repo_root: Path | str,
        *,
        status_provider: Callable[[], dict[str, Any]],
        on_complete: Callable[[], None] | None = None,
        data_root: Path | str | None = None,
    ):
        self.repo_root = Path(repo_root)
        self.data_root = Path(data_root) if data_root is not None else self.repo_root / "data"
        self._status_provider = status_provider
        self._on_complete = on_complete
        self._lock = RLock()
        self._cancel = Event()
        self._thread: Thread | None = None
        self._state: dict[str, Any] = {
            "active": False, "phase": "idle", "percent": 0,
            "downloaded_mb": 0.0, "total_mb": 0.0,
            "message": "", "error": "", "done": False, "updated_at": "",
        }

    def _target(self) -> Path:
        return self.data_root / TARGET_RELPATH

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            state = dict(self._state)
        try:
            status = self._status_provider()
            state["availability"] = status.get("dataAvailability", {}) if isinstance(status, dict) else {}
        except Exception:
            state["availability"] = {}
        state["url"] = DOWNLOAD_URL
        return state

    def start(self) -> dict[str, Any]:
        status = self._status_provider()
        availability = status.get("dataAvailability", {}) if isinstance(status, dict) else {}
        if availability.get("data") == "ready":
            return self._set_state(
                active=False, phase="complete", percent=100,
                downloaded_mb=0.0, total_mb=0.0,
                message="Sequence 데이터가 이미 설치되어 있습니다.", error="", done=True,
            )
        with self._lock:
            if self._state.get("active"):
                return dict(self._state)
            self._cancel.clear()
            self._state.update({
                "active": True, "phase": "data", "percent": 0,
                "downloaded_mb": 0.0, "total_mb": 0.0,
                "message": "다운로드 준비 중...", "error": "", "done": False,
                "updated_at": datetime.now().isoformat(timespec="seconds"),
            })
            worker = Thread(target=self._run, daemon=True, name="sequence-data-download")
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
        target = self._target()
        try:
            if target.exists() and self._validate(target):
                self._set_state(phase="data", percent=100, message="Sequence 데이터가 이미 존재합니다.")
            else:
                self._download_file(
                    target_path=target, url=DOWNLOAD_URL,
                    user_agent="NAIA/2.0 Sequence Module",
                    validator=self._validate,
                    invalid_message="다운로드된 Sequence 데이터가 손상되었습니다.",
                )
            if self._on_complete is not None:
                self._on_complete()
            self._set_state(
                active=False, phase="complete", percent=100,
                message="Sequence 데이터 다운로드 완료", error="", done=True,
            )
        except InterruptedError as exc:
            self._set_state(active=False, message=str(exc), error=str(exc), done=False)
        except urllib.error.HTTPError as exc:
            msg = f"HTTP 오류 {exc.code}: {exc.reason}"
            self._set_state(active=False, message=msg, error=msg, done=False)
        except urllib.error.URLError as exc:
            msg = f"네트워크 오류: {exc.reason}"
            self._set_state(active=False, message=msg, error=msg, done=False)
        except Exception as exc:
            msg = f"다운로드 실패: {exc}"
            self._set_state(active=False, message=msg, error=msg, done=False)

    def _download_file(
        self, *, target_path: Path, url: str, user_agent: str,
        validator: Callable[[Path], bool], invalid_message: str,
    ) -> None:
        temp_path = target_path.with_name(target_path.name + ".download_tmp")
        target_path.parent.mkdir(parents=True, exist_ok=True)
        if temp_path.exists():
            temp_path.unlink()
        if target_path.exists() and not validator(target_path):
            target_path.unlink()

        self._set_state(phase="data", percent=5, downloaded_mb=0.0, total_mb=0.0,
                        message="다운로드 연결 중...")
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
                            self._set_state(percent=percent, downloaded_mb=downloaded_mb,
                                            total_mb=total_mb, message=message)
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
    def _validate(path: Path) -> bool:
        try:
            import pyarrow.parquet as pq
            md = pq.read_metadata(str(path))
            cols = {md.schema.column(i).name for i in range(md.num_columns)}
            need = {"group_id", "peak_rating", "frame_count", "search_tags", "frames"}
            return need <= cols and md.num_rows > 0
        except Exception:
            return False


__all__ = ["SequenceDownloadService"]
