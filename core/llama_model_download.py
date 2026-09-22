"""Boost v2 모델(Gemma 4 E2B QAT Q4_0 GGUF, 3.1 GiB)을 첫 사용 시 내려받는다.

- revision 을 고정한다(재현성). 받은 뒤 SHA-256 이 맞을 때만 최종 이름으로 옮긴다 —
  부분 파일·잘못된 파일을 정상 모델로 승격하지 않는다.
- ``.part`` 가 남아 있으면 Range 로 이어받는다(서버가 206 으로 답할 때만; 아니면 처음부터).
- 스레드 하나, 상태는 snapshot() 으로 폴링한다(EventPresetDownloadService 와 같은 모양).
"""

from __future__ import annotations

import hashlib
import ssl
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from threading import Event, RLock, Thread
from typing import Any, Callable

MODEL_REPO = "google/gemma-4-E2B-it-qat-q4_0-gguf"
MODEL_REVISION = "675cff42a74c774d6cb76f76d8eacb49b48c9b93"
MODEL_REMOTE_FILE = "gemma-4-E2B_q4_0-it.gguf"
MODEL_URL = f"https://huggingface.co/{MODEL_REPO}/resolve/{MODEL_REVISION}/{MODEL_REMOTE_FILE}"
MODEL_SHA256 = "fa401b55b07ee70a54c6dae3903c783a6e65064312529ea57175cb5f8dec6634"
MODEL_SIZE = 3_349_516_256
MODEL_LICENSE = "Apache-2.0"

try:
    import certifi

    SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
except Exception:  # pragma: no cover - platform fallback
    SSL_CONTEXT = ssl.create_default_context()

_CHUNK = 4 * 1024 * 1024


def sha256_of(path: Path, *, cancel: Event | None = None) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            if cancel is not None and cancel.is_set():
                raise InterruptedError("다운로드가 취소되었습니다.")
            block = handle.read(_CHUNK)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


class LlamaModelDownloadService:
    def __init__(
        self,
        target_path: Path | str,
        *,
        url: str = MODEL_URL,
        sha256: str = MODEL_SHA256,
        expected_size: int = MODEL_SIZE,
        opener: Callable[..., Any] | None = None,
    ) -> None:
        self.target_path = Path(target_path)
        self.url = url
        self.sha256 = sha256.lower()
        self.expected_size = int(expected_size)
        self._open = opener or (lambda req, timeout: urllib.request.urlopen(req, timeout=timeout, context=SSL_CONTEXT))
        self._lock = RLock()
        self._cancel = Event()
        self._thread: Thread | None = None
        self._state: dict[str, Any] = {
            "active": False, "phase": "idle", "percent": 0, "downloaded_mb": 0.0,
            "total_mb": round(self.expected_size / 1048576, 1), "message": "", "error": "", "done": False,
            "updated_at": "",
        }

    @property
    def part_path(self) -> Path:
        return self.target_path.with_name(self.target_path.name + ".part")

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            state = dict(self._state)
        state["installed"] = self.target_path.is_file()
        state["partial_mb"] = round(self.part_path.stat().st_size / 1048576, 1) if self.part_path.is_file() else 0.0
        return state

    def start(self) -> dict[str, Any]:
        with self._lock:
            if self._state.get("active"):
                return dict(self._state)
            if self.target_path.is_file():
                return self._set_state(phase="complete", percent=100, done=True, error="",
                                       message="모델이 이미 설치되어 있습니다.")
            self._cancel.clear()
            self._state.update({"active": True, "phase": "download", "percent": 0, "message": "연결 중...",
                                "error": "", "done": False})
            self._thread = Thread(target=self._run, daemon=True, name="boost-model-download")
            self._thread.start()
            return dict(self._state)

    def cancel(self) -> dict[str, Any]:
        if self.snapshot().get("active"):
            self._cancel.set()
            return self._set_state(message="취소 중...")
        return self.snapshot()

    def wait(self, timeout: float | None = None) -> None:
        thread = self._thread
        if thread is not None:
            thread.join(timeout)

    # ── 내부 ──────────────────────────────────────────────────────────────

    def _run(self) -> None:
        try:
            self.target_path.parent.mkdir(parents=True, exist_ok=True)
            self._download()
            self._set_state(phase="verify", message="검증 중(SHA-256)...")
            actual = sha256_of(self.part_path, cancel=self._cancel)
            if actual != self.sha256:
                self.part_path.unlink(missing_ok=True)  # 틀린 파일은 이어받기 대상도 아니다
                raise ValueError(f"SHA-256 불일치 — 받은 파일을 지웠습니다 ({actual[:12]}…)")
            self.part_path.replace(self.target_path)
            self._set_state(active=False, phase="complete", percent=100, done=True, error="",
                            downloaded_mb=round(self.expected_size / 1048576, 1), message="설치 완료")
        except InterruptedError as exc:
            self._set_state(active=False, phase="cancelled", message=str(exc), error="", done=False)
        except urllib.error.HTTPError as exc:
            self._fail(f"HTTP 오류 {exc.code}: {exc.reason}")
        except urllib.error.URLError as exc:
            self._fail(f"네트워크 오류: {exc.reason}")
        except Exception as exc:
            self._fail(f"다운로드 실패: {exc}")

    def _fail(self, message: str) -> None:
        self._set_state(active=False, phase="error", message=message, error=message, done=False)

    def _download(self) -> None:
        have = self.part_path.stat().st_size if self.part_path.is_file() else 0
        if have > self.expected_size:
            self.part_path.unlink()
            have = 0
        if have == self.expected_size:
            return  # 다 받아 둔 .part — 검증만 한다
        headers = {"User-Agent": "NAIA/2.0 BoostModel"}
        if have:
            headers["Range"] = f"bytes={have}-"
        response = self._open(urllib.request.Request(self.url, headers=headers), 30)
        with response:
            status = getattr(response, "status", None) or response.getcode()
            if have and status != 206:
                have = 0  # 서버가 이어받기를 안 받아 줬다 — 처음부터
            mode = "ab" if have else "wb"
            downloaded, last = have, 0.0
            with self.part_path.open(mode) as out:
                while True:
                    if self._cancel.is_set():
                        raise InterruptedError("다운로드가 취소되었습니다(받은 부분은 남겨 두고 이어받습니다).")
                    chunk = response.read(_CHUNK)
                    if not chunk:
                        break
                    out.write(chunk)
                    downloaded += len(chunk)
                    now = time.monotonic()
                    if now - last >= 0.25:
                        last = now
                        percent = min(99, int(downloaded * 100 / self.expected_size))
                        mb = round(downloaded / 1048576, 1)
                        self._set_state(percent=percent, downloaded_mb=mb,
                                        message=f"다운로드 중... {percent}% ({mb}/{self._state['total_mb']} MB)")
        size = self.part_path.stat().st_size
        if size != self.expected_size:
            raise ValueError(f"받은 크기가 다릅니다({size} / {self.expected_size} bytes) — 다시 시도하면 이어받습니다")

    def _set_state(self, **updates: Any) -> dict[str, Any]:
        with self._lock:
            self._state.update(updates)
            self._state["updated_at"] = datetime.now().isoformat(timespec="seconds")
            return dict(self._state)


__all__ = ["LlamaModelDownloadService", "MODEL_URL", "MODEL_SHA256", "MODEL_SIZE", "sha256_of"]
