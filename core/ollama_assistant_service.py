"""Ollama 로컬 어시스턴트 프록시 서비스 (Dev0714 ollama_module 패턴의 헤드리스 이식).

Remote Web 페이지가 직접 localhost:11434를 찌르면 폰/LAN/Cloudflared 세션에서는
그 기기 자신의 localhost를 가리켜 오동작한다 — 그래서 NAIA 백엔드가 도는 머신의
Ollama를 서버측에서 프록시한다.

상태 모델 (Dev0714 3상태 + 모델 설치 여부):
  installed(=``ollama --version`` 성공) → running(=GET /api/tags 200) → model_installed.
설치 자체는 자동화하지 않는다 — 프론트가 https://ollama.com/download 안내를 연다
(Dev0714 ``_open_ollama_download_page`` 동일 결정). 서버 시작(``ollama serve``)과
모델 다운로드(``/api/pull`` 스트리밍)는 백엔드가 대행한다.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from threading import Lock, Thread
from typing import Any, Callable

DEFAULT_OLLAMA_BASE = "http://127.0.0.1:11434"
# 프론트(ollamaAssistantPopup.mjs)의 DEFAULT_MODEL과 미러 — 요청에 model이 없을 때 폴백.
# E2B-IQ3_M로 전환: round-trip eval에서 E4B Q4_K_M 대비 recall↑(0.615→0.665)·noise↓
# (0.215→0.182)·VRAM 절반(3.1GB)·2.3배 빠름. 파이프라인이 추론을 코드로 외부화해
# 작은 모델이 더 순종적(노이즈↓). E2B는 IQ3_M만 로드 가능(_P 양자화는 llama.cpp 미지원).
DEFAULT_MODEL = "hf.co/HauhauCS/Gemma-4-E2B-Uncensored-HauhauCS-Aggressive:IQ3_M"

_IDLE_PULL_STATE: dict[str, Any] = {
    "active": False,
    "model": "",
    "status": "",
    "percent": 0,
    "completed_mb": 0.0,
    "total_mb": 0.0,
    "error": "",
    "done": False,
}


def _no_window_flags() -> int:
    return subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


class OllamaAssistantService:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        version_probe: Callable[[], str | None] | None = None,
        http_get: Callable[..., Any] | None = None,
        http_stream: Callable[..., Any] | None = None,
        server_spawner: Callable[[], Any] | None = None,
    ):
        self.base_url = str(
            base_url or os.environ.get("NAIA_OLLAMA_URL") or DEFAULT_OLLAMA_BASE
        ).rstrip("/")
        # 테스트 주입 지점들 — 실환경에서는 전부 기본 구현 사용.
        self._version_probe = version_probe or self._probe_cli_version
        self._http_get = http_get or self._default_http_get
        self._http_stream = http_stream or self._default_http_stream
        self._server_spawner = server_spawner or self._default_server_spawner
        self._lock = Lock()
        self._pull_state: dict[str, Any] = dict(_IDLE_PULL_STATE)
        self._pull_thread: Thread | None = None
        self._pull_cancel = False
        # 취소가 블록된 스트림 read를 즉시 끊을 수 있게 활성 응답을 보관 (Codex F2).
        self._pull_response: Any = None
        # ``ollama serve`` 프로세스 소유 — 살아있는 동안 중복 스폰 방지 (Codex F3).
        self._server_process: Any = None
        # CLI 버전 프로브 캐시(짧은 TTL) — 공개 status가 요청마다 subprocess를
        # 스폰하지 않도록 빈도를 묶는다 (Codex F1). 락은 singleflight 보장:
        # 캐시 만료 직후 동시 요청 버스트가 병렬 subprocess를 스폰하지 못하게.
        self._version_cache: tuple[float, str | None] = (0.0, None)
        self._version_cache_ttl = 5.0
        self._version_probe_lock = Lock()

    # ------------------------------------------------------------------
    # 기본 IO 구현
    # ------------------------------------------------------------------

    @staticmethod
    def _probe_cli_version() -> str | None:
        """``ollama --version`` — 설치 여부 판정 (Dev0714 is_installed 동일)."""
        try:
            result = subprocess.run(
                ["ollama", "--version"],
                capture_output=True, text=True, timeout=2,
                creationflags=_no_window_flags(),
            )
            if result.returncode != 0:
                return None
            return (result.stdout or "").strip() or "installed"
        except Exception:
            return None

    def _default_http_get(self, path: str, *, timeout: float = 1.5) -> Any:
        import requests

        return requests.get(f"{self.base_url}{path}", timeout=timeout)

    def _default_http_stream(self, path: str, payload: dict[str, Any]) -> Any:
        import requests

        return requests.post(
            f"{self.base_url}{path}", json=payload, stream=True, timeout=(5, 600),
        )

    def _default_server_spawner(self) -> Any:
        """``ollama serve``를 창 없이 분리 실행 (Dev0714 start_server 동일)."""
        return subprocess.Popen(
            ["ollama", "serve"],
            creationflags=_no_window_flags(),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    # ------------------------------------------------------------------
    # 상태
    # ------------------------------------------------------------------

    def _cached_version_probe(self, *, fresh: bool = False) -> str | None:
        # singleflight: 동시 호출은 첫 번째가 프로브하는 동안 대기했다가
        # 갱신된 캐시를 그대로 받는다 (병렬 subprocess 스폰 방지).
        with self._version_probe_lock:
            now = time.monotonic()
            cached_at, cached = self._version_cache
            if not fresh and now - cached_at < self._version_cache_ttl:
                return cached
            value = self._version_probe()
            self._version_cache = (time.monotonic(), value)
            return value

    @staticmethod
    def _models_path_warning() -> str:
        """Ollama 모델 디렉터리 경로에 비-ASCII(한글 등) 문자가 있으면 경고 문구를 반환한다.

        llama.cpp(Ollama 내부 llama-server)는 Windows에서 비-ASCII 경로의 모델/CLIP
        파일을 못 열어 "Failed to load CLIP model ... exit status 1"로 죽는다(upstream
        한계 — NAIA가 고칠 수 없음). 사용자가 암호 같은 에러 대신 원인·해결책을 바로
        알도록, 모델 경로(OLLAMA_MODELS 또는 기본 ~/.ollama/models)가 비-ASCII면 안내한다.
        Windows 전용(비-Windows는 UTF-8 경로가 정상이라 경고 불필요)."""
        try:
            import os
            import sys

            if sys.platform != "win32":
                return ""
            from pathlib import Path

            raw = os.environ.get("OLLAMA_MODELS") or str(Path.home() / ".ollama" / "models")
            if raw and not raw.isascii():
                return (
                    "Ollama 모델 경로에 한글 등 비영문 문자가 포함돼 있어 모델 로딩이 "
                    "실패할 수 있습니다 (llama.cpp의 Windows 경로 제약). 환경변수 "
                    "OLLAMA_MODELS를 영문 경로(예: C:\\ollama\\models)로 지정하거나 모델을 "
                    "영문 경로로 옮긴 뒤 Ollama를 재시작하세요."
                )
        except Exception:
            pass
        return ""

    def status(
        self,
        model: str | None = None,
        *,
        include_details: bool = True,
        fresh: bool = False,
    ) -> dict[str, Any]:
        """Ollama 상태. ``include_details=False``(비-루프백 클라이언트)는 버전·
        설치 모델 목록·엔드포인트 등 호스트 인벤토리를 제외한 요약만 준다.
        ``fresh=True``(다시 확인 버튼)는 CLI 프로브 캐시를 우회해, 사용자가
        방금 설치한 Ollama가 TTL 안에서도 즉시 잡히게 한다."""
        target = str(model or DEFAULT_MODEL).strip()
        version = self._cached_version_probe(fresh=fresh)
        installed = version is not None
        running = False
        models: list[str] = []
        try:
            response = self._http_get("/api/tags", timeout=1.5)
            if getattr(response, "status_code", 0) == 200:
                running = True
                payload = response.json() or {}
                models = [
                    str(item.get("name") or "")
                    for item in payload.get("models", [])
                    if isinstance(item, dict)
                ]
        except Exception:
            running = False
        # 서버가 떠 있으면 CLI 프로브 실패와 무관하게 "설치됨"으로 본다
        # (PATH에 없지만 서비스로 도는 경우).
        if running:
            installed = True
        model_installed = any(
            name == target or name.split(":")[0] == target for name in models if name
        )
        if not include_details:
            # 원격 클라이언트: 진행 상태 렌더에 필요한 최소만 (호스트 인벤토리 비노출).
            return {
                "ok": True,
                "installed": installed,
                "running": running,
                "model_installed": model_installed,
                "control_allowed": False,
            }
        return {
            "ok": True,
            "installed": installed,
            "running": running,
            "version": version or "",
            "models": models,
            "model": target,
            "model_installed": model_installed,
            "endpoint": f"{self.base_url}/v1",
            "download_page": "https://ollama.com/download",
            "control_allowed": True,
            # 비-ASCII(한글) 모델 경로 경고 — 빈 문자열이면 문제 없음(프론트가 게이트).
            "path_warning": self._models_path_warning(),
        }

    # ------------------------------------------------------------------
    # 서버 시작
    # ------------------------------------------------------------------

    def _owned_server_alive(self) -> bool:
        process = self._server_process
        if process is None:
            return False
        poll = getattr(process, "poll", None)
        try:
            return poll is not None and poll() is None
        except Exception:
            return False

    def start_server(self, *, wait_seconds: float = 10.0) -> dict[str, Any]:
        if self.status().get("running"):
            return {"ok": True, "running": True, "message": "Ollama 서버가 이미 실행 중입니다."}
        # 우리가 띄운 프로세스가 아직 살아있으면(기동 중) 중복 스폰하지 않고
        # 응답 대기만 다시 한다 (Codex F3: stale spawn 반복 방지).
        if not self._owned_server_alive():
            try:
                self._server_process = self._server_spawner()
            except Exception as exc:
                return {"ok": False, "running": False, "error": f"서버 시작 실패: {exc}"}
        deadline = time.monotonic() + max(1.0, wait_seconds)
        while time.monotonic() < deadline:
            time.sleep(0.5)
            # 프로세스가 즉시 죽었으면(포트 충돌 등) 기다리지 않고 보고.
            if self._server_process is not None and not self._owned_server_alive():
                self._server_process = None
                return {"ok": False, "running": False, "error": "ollama serve 프로세스가 곧바로 종료되었습니다."}
            try:
                response = self._http_get("/api/tags", timeout=1.0)
                if getattr(response, "status_code", 0) == 200:
                    return {"ok": True, "running": True, "message": "Ollama 서버를 시작했습니다."}
            except Exception:
                continue
        return {"ok": False, "running": False, "error": "서버가 제한 시간 안에 응답하지 않았습니다."}

    # ------------------------------------------------------------------
    # 모델 다운로드 (Ollama REST /api/pull 스트리밍)
    # ------------------------------------------------------------------

    def pull_state(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._pull_state)

    def cancel_pull(self) -> dict[str, Any]:
        with self._lock:
            if self._pull_state.get("active"):
                self._pull_cancel = True
                self._pull_state["status"] = "취소 중..."
                # 블록된 read를 즉시 끊는다 — 플래그만으로는 다음 청크가 올 때까지
                # (혹은 read 타임아웃까지) 다운로드가 계속된다 (Codex F2).
                response = self._pull_response
            else:
                response = None
        if response is not None:
            try:
                response.close()
            except Exception:
                pass
        return self.pull_state()

    def start_pull(self, model: str | None = None) -> dict[str, Any]:
        target = str(model or DEFAULT_MODEL).strip()
        with self._lock:
            if self._pull_state.get("active"):
                return dict(self._pull_state)
            self._pull_cancel = False
            self._pull_state = {
                **_IDLE_PULL_STATE,
                "active": True,
                "model": target,
                "status": "다운로드 준비 중...",
            }
            worker = Thread(
                target=self._run_pull, args=(target,), daemon=True, name="ollama-model-pull",
            )
            self._pull_thread = worker
            worker.start()
            return dict(self._pull_state)

    def _set_pull(self, **updates: Any) -> None:
        with self._lock:
            self._pull_state.update(updates)

    def _run_pull(self, model: str) -> None:
        response = None
        try:
            response = self._http_stream("/api/pull", {"model": model, "stream": True})
            with self._lock:
                self._pull_response = response
                cancelled_before_stream = self._pull_cancel
            if cancelled_before_stream:
                self._set_pull(active=False, status="취소됨", error="", done=False)
                return
            status_code = getattr(response, "status_code", 0)
            if status_code != 200:
                detail = ""
                try:
                    detail = str((response.json() or {}).get("error") or "")
                except Exception:
                    pass
                raise RuntimeError(detail or f"Ollama HTTP {status_code}")
            for raw_line in response.iter_lines():
                if self._pull_cancel:
                    self._set_pull(active=False, status="취소됨", error="", done=False)
                    return
                if not raw_line:
                    continue
                try:
                    line = json.loads(raw_line)
                except Exception:
                    continue
                if line.get("error"):
                    raise RuntimeError(str(line["error"]))
                status = str(line.get("status") or "")
                total = float(line.get("total") or 0)
                completed = float(line.get("completed") or 0)
                updates: dict[str, Any] = {"status": status or "다운로드 중..."}
                if total > 0:
                    updates["percent"] = int(max(0, min(100, completed / total * 100)))
                    updates["completed_mb"] = round(completed / (1024 * 1024), 1)
                    updates["total_mb"] = round(total / (1024 * 1024), 1)
                if status == "success":
                    updates.update({"percent": 100, "done": True})
                self._set_pull(**updates)
            with self._lock:
                done = bool(self._pull_state.get("done"))
            if done:
                self._set_pull(active=False, status="모델 다운로드 완료", error="")
            else:
                self._set_pull(active=False, error="다운로드가 완료 신호 없이 종료되었습니다.")
        except Exception as exc:
            if self._pull_cancel:
                # cancel_pull()이 스트림을 닫아 read가 예외로 끊긴 경우 — 정상 취소.
                self._set_pull(active=False, status="취소됨", error="", done=False)
            else:
                self._set_pull(active=False, done=False, error=str(exc) or "모델 다운로드 실패")
        finally:
            with self._lock:
                self._pull_response = None
            if response is not None:
                try:
                    response.close()
                except Exception:
                    pass
