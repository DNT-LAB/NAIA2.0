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
# ⚠️ **번들을 다시 구우면 반드시 파일 이름을 바꿔라.**
#
# `present()` 는 이름만 보고 sha 를 확인하지 않는다. 같은 이름으로 덮어쓰면 이미
# 받은 설치는 `start()` 에서 곧장 ready 로 빠져 **옛 번들을 영영 쓴다**(Codex
# 지적, 코드 확인). 상수만 고치면 신규 설치는 179MB 를 받아 sha 불일치로 버리고,
# 기존 설치는 옛 것을 쓰는 최악의 조합이 된다.
#
# v2 = 레시피 뱅크 + 의미 그래프 + 앵커 주변분포를 부속 자산으로 품은 NCSB2.
# v3 = 같은 NCSB2 이되 뱅크가 NRB3(앵커 -> {rows, tags})다. 뱅크 형식이 바뀌면
#      옛 뱅크는 `RecipeBank` 가 명시적으로 거부하고 서비스는 조용히 온라인
#      경로로 떨어진다 - 추천이 다시 니치해지는데 아무도 모른다. 그래서 위
#      규약대로 **이름을 바꿔** 옛 설치가 새 파일을 받게 한다.
BUNDLE_URL = ("https://huggingface.co/baqu2213/PoemForSmallFThings/"
              "resolve/main/NAIA/naia_tag_combo_v3.ncsb")
BUNDLE_NAME = "naia_tag_combo_v3.ncsb"
# 지난 이름들. 새 번들이 자리를 잡으면 지운다 - 200MB 짜리가 나란히 쌓인다.
STALE_NAMES = ("naia_tag_combo.ncsb", "naia_tag_combo_v2.ncsb")
# 아래 둘은 `tools/build_tag_combo_bundle.py` 가 빌드 끝에 출력한다. 업로드할
# **그 파일**의 값이어야 한다 - 검증한 뒤 다시 구우면 sha 가 달라진다.
BUNDLE_SHA256 = "7dd410b61cfba2e52d4f92cf0cd72d2d8fea33e3d0b1c3c53a3a262b81f6dec2"
BUNDLE_BYTES = 203_110_395

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

    def sweep_stale(self) -> list[str]:
        """지난 이름의 번들을 치운다. **현재 번들이 있을 때만** 부른다.

        이름을 바꿔 새로 받게 만들면 옛 파일이 그대로 남는다(각 200MB). 지우는
        건 내려받은 캐시뿐이고 사용자 데이터가 아니다 - 그래도 지금 쓰는 이름과
        같으면 절대 건드리지 않는다.
        """
        gone = []
        for nm in STALE_NAMES:
            if nm == self.name:
                continue
            p = self.dir / nm
            try:
                if p.is_file():
                    p.unlink()
                    gone.append(nm)
            except OSError:
                pass
        if gone:
            print(f"[tag-combo] removed stale bundle(s): {', '.join(gone)}")
        return gone

    def retry(self) -> dict:
        """error 에서 빠져나오는 유일한 길. 프론트의 [다시 시도] 가 부른다."""
        with self._lock:
            if self.state.state == "error":
                self.state = DownloadState()
                self._warned = False
        return self.start()

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
                self.sweep_stale()
                return self.status()
            if not self.configured():
                self.state.state = "error"
                self.state.error = "download url is not configured"
                return self.status()
            if self._thread is not None and self._thread.is_alive():
                return self.status()
            if self.state.state == "error":
                # **실패에서 저절로 다시 받지 않는다.** 스레드가 죽어 있으므로
                # 위 검사를 통과해 버리는데, 그러면 상태 폴링이나 재진입 POST 가
                # 들어올 때마다 179MB 를 새로 긁는다. 빠져나오는 길은 retry() 뿐,
                # 즉 사용자가 명시적으로 다시 시도할 때뿐이다.
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
            # 받은 **그 자리에서** 옛 이름을 치운다. `start()` 의 sweep 은 이미
            # 있을 때만 도니까, 이게 없으면 새로 받은 회차에는 200MB 짜리 둘이
            # 나란히 남고 다음 실행까지 그대로다(실측 확인).
            self.sweep_stale()
            self.state.state = "ready"
            self.state.finished = time.time()
        except BaseException as exc:      # noqa: BLE001 - 아래 주석 참조
            # ⚠️ **여기서 예외를 좁히면 안 된다.**
            #
            # 원래 `(OSError, ValueError, URLError)` 만 받았다. 그런데 다운로드
            # 중 연결이 끊기면 `http.client.IncompleteRead` 가 나는데 이건
            # OSError 가 아니다. 잘린 번들을 파싱하면 `struct.error` 가 난다.
            # 둘 다 안 잡혀서 스레드는 죽고 **상태는 `downloading` 에 영원히
            # 남았다** - 프론트는 "받는 중"을 무한 폴링하고, `.part` 가 쌓이고,
            # 재시도할 방법이 없다. (Codex 게이트 실증: state=downloading,
            # part_exists=true, final_exists=false)
            #
            # 무엇이 터지든 상태는 반드시 error 로 착지해야 한다. 부분 파일도
            # 반드시 치운다 - 정식 이름은 검증을 통과해야만 받는다.
            self.state.state = "error"
            self.state.error = f"{type(exc).__name__}: {exc}"[:300]
            self._log_once(f"bundle download failed: {self.state.error}")
            try:
                part.unlink(missing_ok=True)
            except OSError:
                pass
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
