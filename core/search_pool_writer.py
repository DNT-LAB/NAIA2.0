"""검색 풀 영속 파일(last-search · runner)을 응답 뒤 백그라운드로 쓴다.

Custom parquet 불러오기/합치기는 풀 전체를 parquet 으로 **두 번** 동기 기록한 뒤에야 응답했다
(1.3M 행 = 3.2초, 로드 전체 5.6초의 57%). 그동안 프론트는 Tag Filter 재적용을 보내지 못한다.

- 한 번만 쓴다: 설치 직후엔 runner 대상(남은 풀)과 last-search 대상(snapshot)이 같은 내용이라
  runner 는 last-search 파일을 **복사**한다.
- latest-wins: 대기 중인 작업은 새 작업이 덮는다. 쓰는 중인 작업은 끝까지 쓴다.
- 동기 기록(`write_now`)과 같은 파일 락을 쓴다 - 같은 tmp 경로를 두 스레드가 동시에 쓰지 않는다.
  동기 기록은 대기 중인 같은 종류의 작업을 취소한다(안 그러면 더 오래된 프레임이 나중에 덮는다).
- 프레임은 **호출자가 풀 락 안에서 캡처한 불변 참조**여야 한다. 여기서 `get_dataframe()` 을
  부르면 안 된다(Random pop 과 경쟁 + 캐시 무효화 부작용).
"""

from __future__ import annotations

import os
import shutil
import threading
from pathlib import Path
from typing import Any

_CREATE_GUARD = threading.Lock()


def _atomic_to_parquet(frame: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    frame.to_parquet(tmp, index=False)
    os.replace(tmp, path)


def _atomic_copy(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(dst.suffix + ".tmp")
    shutil.copyfile(src, tmp)
    os.replace(tmp, dst)


class SearchPoolWriter:
    def __init__(self) -> None:
        self._cond = threading.Condition()
        self._file_lock = threading.Lock()
        self._job: dict[str, Any] | None = None
        self._busy = False
        self._thread: threading.Thread | None = None
        self.last_error: str | None = None

    # ---- 백그라운드 -------------------------------------------------------
    def submit(self, last_path: Path, frame: Any, runner_path: Path | None = None) -> None:
        """last-search 를 쓰고, runner_path 가 있으면 같은 파일을 복사한다."""
        with self._cond:
            self._job = {"last": (Path(last_path), frame), "runner_copy": Path(runner_path) if runner_path else None}
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._run, name="naia-search-pool-writer", daemon=True)
                self._thread.start()
            self._cond.notify_all()

    def _run(self) -> None:
        while True:
            with self._cond:
                while self._job is None:
                    self._cond.wait()
                job, self._job = self._job, None
                self._busy = True
            try:
                with self._file_lock:
                    last = job.get("last")
                    if last is not None:
                        _atomic_to_parquet(last[1], last[0])
                        runner = job.get("runner_copy")
                        if runner is not None:
                            _atomic_copy(last[0], runner)
                self.last_error = None
            except Exception as exc:  # best-effort, 기존 persist 와 같은 정책
                self.last_error = str(exc)
                print(f"Headless Remote: search pool write failed - {exc}", flush=True)
            finally:
                with self._cond:
                    self._busy = False
                    self._cond.notify_all()

    def flush(self, timeout: float | None = None) -> bool:
        """대기·진행 중인 작업이 끝날 때까지 기다린다(종료·시험용). 끝났으면 True."""
        with self._cond:
            return self._cond.wait_for(lambda: self._job is None and not self._busy, timeout)

    # ---- 동기 --------------------------------------------------------------
    def write_now(self, path: Path, frame: Any, *, kind: str) -> None:
        """동기 기록. kind='last' 면 대기 중인 작업 전체를, 'runner' 면 runner 복사만 취소한다.

        last 를 새로 쓰면 대기 중인 runner 복사도 버린다 - 복사 원본(last 파일)이 이미 다른
        내용이 되어 runner 에 엉뚱한 풀이 들어간다."""
        with self._cond:
            if self._job is not None:
                if kind == "last":
                    self._job = None
                elif kind == "runner":
                    self._job["runner_copy"] = None
        with self._file_lock:
            _atomic_to_parquet(frame, Path(path))


def search_pool_writer(context: Any) -> SearchPoolWriter:
    """context 당 하나. 시험 더블(context 에 속성을 못 붙이는 객체)도 모듈 하나로 동작한다."""
    writer = getattr(context, "_search_pool_writer", None)
    if writer is not None:
        return writer
    with _CREATE_GUARD:
        writer = getattr(context, "_search_pool_writer", None)
        if writer is None:
            writer = SearchPoolWriter()
            try:
                setattr(context, "_search_pool_writer", writer)
            except Exception:
                pass
        return writer
