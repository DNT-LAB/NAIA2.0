# -*- coding: utf-8 -*-
"""조합 모델 번들 배경 다운로드.

Interactive 를 열면 시작하고, 받는 동안 추천 영역이 안내 문구를 띄운다. 179MB 라
첫 진입을 막으면 안 된다 - 조합 카드가 없어도 나머지 기능은 전부 돈다.

## 규약

- **한 번에 하나.** 여러 탭/재진입에서 동시에 눌러도 스레드는 하나다.
- **부분 파일을 최종 이름으로 두지 않는다.** `.part` 에 받고 검증 후 rename 한다.
  중간에 끊긴 파일이 정식 이름을 달고 있으면 다음 실행이 그걸 정상이라고 믿는다.
- **받은 뒤 전 그룹을 검증한다**(`ComboBundle.verify_all`, 실측 13그룹 2초).
  `read()` 는 읽는 그룹만 보므로, 안 쓰는 그룹이 깨진 채 남아 있다가 사용자가
  인원 수를 바꾸는 순간 터진다.
- **실패를 조용히 삼키지 않는다.** 상태에 남기고 1회 로그한다(ASCII, cp949 콘솔).
"""

from __future__ import annotations

import hashlib
import shutil
import threading
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path

# 다른 런타임 자산과 같은 호스팅을 쓴다(`core/runtime_install_manager.py` 참조).
# URL 이 비어 있으면 다운로드 기능 자체가 꺼진 것으로 본다.
BUNDLE_URL = ("https://huggingface.co/baqu2213/PoemForSmallFThings/"
              "resolve/main/NAIA/naia_tag_combo_v1.ncsb")
BUNDLE_NAME = "naia_tag_combo_v1.ncsb"
BUNDLE_SHA256 = "2ae34aa9c5abae0187b517b5ce78a232a405e1818cb9393eff4c22253f2f8bc0"
BUNDLE_BYTES = 187_801_727

_CHUNK = 1 << 20
_UA = "NAIA TagCombo Downloader"


@dataclass
class DownloadState:
    state: str = "idle"          # idle · downloading · verifying · ready · error
    received: int = 0
    total: int = BUNDLE_BYTES
    error: str = ""
    started: float = 0.0
    finished: float = 0.0

    def as_dict(self) -> dict:
        d = asdict(self)
        d["percent"] = (round(self.received * 100.0 / self.total, 1)
                        if self.total else 0.0)
        if self.state == "downloading" and self.started and self.received:
            el = max(1e-6, time.time() - self.started)
            rate = self.received / el
            d["bytesPerSec"] = int(rate)
            d["etaSec"] = int(max(0, (self.total - self.received) / max(rate, 1)))
        return d


class BundleDownloader:
    def __init__(self, target_dir: Path, *, url: str = BUNDLE_URL,
                 name: str = BUNDLE_NAME, sha256: str = BUNDLE_SHA256):
        self.dir = Path(target_dir)
        self.url = url
        self.name = name
        self.sha256 = sha256
        self.state = DownloadState()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._warned = False

    # ---- 상태 --------------------------------------------------------
    @property
    def path(self) -> Path:
        return self.dir / self.name

    def configured(self) -> bool:
        return bool(self.url)

    def present(self) -> bool:
        return self.path.exists()

    def status(self) -> dict:
        d = self.state.as_dict()
        if self.present() and d["state"] in ("idle", "ready"):
            d["state"] = "ready"
        d.update(configured=self.configured(), name=self.name,
                 path=str(self.path))
        return d

    # ---- 실행 --------------------------------------------------------
    def start(self) -> dict:
        """이미 있거나 받는 중이면 아무것도 하지 않는다(호출부가 안전하게 반복 호출)."""
        with self._lock:
            if self.present():
                self.state.state = "ready"
                return self.status()
            if not self.configured():
                self.state.state = "error"
                self.state.error = "download url is not configured"
                return self.status()
            if self._thread is not None and self._thread.is_alive():
                return self.status()
            self.state = DownloadState(state="downloading", started=time.time())
            self._thread = threading.Thread(target=self._run, daemon=True,
                                            name="tag-combo-download")
            self._thread.start()
            return self.status()

    def _log_once(self, msg: str) -> None:
        if self._warned:
            return
        self._warned = True
        safe = msg.encode("ascii", "backslashreplace").decode("ascii")
        print(f"[tag-combo] {safe}")

    def _run(self) -> None:
        part = self.path.with_suffix(self.path.suffix + ".part")
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            req = urllib.request.Request(self.url, headers={"User-Agent": _UA})
            digest = hashlib.sha256()
            with urllib.request.urlopen(req, timeout=60) as resp, \
                    part.open("wb") as fh:
                total = int(resp.headers.get("Content-Length") or 0)
                if total:
                    self.state.total = total
                while True:
                    chunk = resp.read(_CHUNK)
                    if not chunk:
                        break
                    fh.write(chunk)
                    digest.update(chunk)
                    self.state.received += len(chunk)
            got = digest.hexdigest()
            if self.sha256 and got != self.sha256:
                raise ValueError(f"sha256 mismatch: got {got[:16]}...")

            # 내용 검증까지 하고서야 정식 이름을 준다.
            self.state.state = "verifying"
            from .bundle import ComboBundle
            bad = ComboBundle(part).verify_all()
            if bad:
                raise ValueError(f"corrupt groups: {bad[:3]}")

            shutil.move(str(part), str(self.path))
            self.state.state = "ready"
            self.state.finished = time.time()
        except (OSError, ValueError, urllib.error.URLError) as exc:
            self.state.state = "error"
            self.state.error = f"{type(exc).__name__}: {exc}"
            self._log_once(f"bundle download failed: {self.state.error}")
            try:
                part.unlink(missing_ok=True)
            except OSError:
                pass
