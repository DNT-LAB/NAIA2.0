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
import re
import subprocess
import sys
import time
from threading import Lock, Thread
from typing import Any, Callable

DEFAULT_OLLAMA_BASE = "http://127.0.0.1:11434"
# 프론트(ollamaAssistantPopup.mjs)의 DEFAULT_MODEL과 미러 — 요청에 model이 없을 때 폴백.
# E4B는 현재 기본 권장 모델이다. 더 가벼운/강한 모델은 CURATED_MODELS에서
# 다운로드·활성화할 수 있고, DEFAULT_MODEL은 첫 실행/연결 실패 시의 단일 폴백만 담당한다.
DEFAULT_MODEL = "hf.co/HauhauCS/Gemma-4-E4B-Uncensored-HauhauCS-Aggressive:Q4_K_M"
CURATED_MODELS: tuple[dict[str, str], ...] = (
    {
        "model": "hf.co/HauhauCS/Gemma-4-E2B-Uncensored-HauhauCS-Aggressive:IQ3_M",
        "label": "E2B · 가벼움",
        "size": "~4.1GB",
    },
    {
        "model": "hf.co/HauhauCS/Gemma-4-E4B-Uncensored-HauhauCS-Aggressive:Q4_K_M",
        "label": "E4B · 권장",
        "size": "~6.3GB",
    },
    {
        "model": "hf.co/HauhauCS/Gemma4-26B-A4B-Uncensored-HauhauCS-Balanced:IQ4_XS",
        "label": "E26B · 강력",
        "size": "~15GB",
    },
)

_SCENE_SEGMENT_AXES = frozenset({
    "clothing",
    "action",
    "gaze",
    "expression",
    "body",
    "background",
    "object",
    "character",
    "general",
})
_SCENE_SCAFFOLD_CONCEPTS = frozenset({
    "girl",
    "boy",
    "character",
    "scene",
    "composition",
    "구도",
    "소녀",
    "dog",
    "hands",
    "pose",
})
_SCENE_ACTION_MARKERS = (
    "묶", "구속", "속박", "bound", "tied", "all fours", "kneeling",
    "crossed arms", "네발",
)
_SCENE_GAZE_MARKERS = ("viewer", "looking", "올려다", "카메라")
_SCENE_SOURCE_CONCEPT_RULES: tuple[tuple[tuple[str, ...], str, str, str], ...] = (
    (("교복", "school uniform"), "교복", "clothing", "school uniform"),
    (("수영복", "swimsuit"), "수영복", "clothing", "swimsuit"),
    (("기모노", "kimono"), "기모노", "clothing", "kimono"),
    (("후드티", "hoodie"), "후드티", "clothing", "hoodie"),
    (("양손", "팔을 묶", "arms bound", "arms tied"), "양손을 묶인", "action", "arms behind back"),
    (("묶", "구속", "속박", "bound", "tied"), "묶인", "action", "bound"),
    (("개 같은", "네발", "all fours"), "네발기기 자세", "action", "all fours"),
    (("viewer", "카메라", "올려다", "looking at viewer"), "viewer를 보는", "gaze", "looking at viewer"),
    (("째려", "노려", "glaring"), "째려보는", "expression", "glaring"),
    (("혀", "tongue"), "혀를 내미는", "expression", "tongue out"),
    (("무릎", "kneel"), "무릎 꿇은", "action", "kneeling"),
    (("울먹", "눈물", "tear"), "울먹이는", "expression", "tears"),
    (("팔짱", "crossed arms"), "팔짱", "action", "crossed arms"),
)

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


def _endpoint_is_local(url: str) -> bool:
    """엔드포인트가 NAIA 실행 머신 자신을 가리키는지(=로컬 Ollama 제어 가능).

    원격(cloudflared/LAN 등)이면 False — 그때는 ``ollama serve`` 스폰과 로컬 CLI
    설치 판정이 무의미하므로 status/start_server가 원격 모드로 적응한다."""
    try:
        from urllib.parse import urlparse

        raw = str(url) if "://" in str(url) else "http://" + str(url)
        host = (urlparse(raw).hostname or "").lower()
        return host in {"127.0.0.1", "localhost", "0.0.0.0", "::1", ""}
    except Exception:
        return False


def _model_name_matches(installed: str, target: str) -> bool:
    left = str(installed or "").strip()
    right = str(target or "").strip()
    if not left or not right:
        return False
    return left == right or left.split(":", 1)[0] == right.split(":", 1)[0]


def _friendly_ollama_error(raw: Any) -> str:
    """Ollama 모델 로드/아키텍처 미지원 에러를 사용자 안내 메시지로 매핑(그 외는 원문 유지).

    예: E26B(Gemma4-26B)는 `gemma4` 아키텍처를 선언하는데 구버전 Ollama(llama.cpp)가
    이를 모르면 `unable to load model`/`unknown model architecture`만 반환한다 → raw 메시지는
    원인을 알기 어렵다. Ollama 업데이트(또는 자원 확인)로 유도한다."""
    text = str(raw or "")
    low = text.lower()
    if (
        "unable to load model" in low
        or "error loading model" in low
        or "unknown model architecture" in low
        or "failed to load model" in low
        or "failed to create server" in low
    ):
        return (
            "모델 로드에 실패했습니다 — 이 모델은 최신 Ollama 런타임이 필요할 수 있습니다. "
            "Ollama를 최신 버전으로 업데이트하거나, GPU/메모리 자원이 충분한지 확인하세요. "
            "(가벼운 모델 E4B/E2B는 현재 런타임에서 동작합니다.)"
        )
    return text


def _resolve_connection_defaults() -> tuple[str, str]:
    """(base_url, model) 우선순위: 영속 설정 → env ``NAIA_OLLAMA_URL`` → 코드 기본.

    고급 연결 설정(셀프호스팅 엔드포인트)을 UI에서 바꾸면 ``ollama_connection_user.json``에
    영속되고, 다음 서비스 생성 시 이 함수가 그 값을 최우선으로 집어 온다. env는 기존
    파워유저/개발 경로를 위해 폴백으로 유지한다."""
    endpoint = ""
    model = ""
    try:
        from core.prompt_engineering_settings import load_ollama_connection_settings

        saved = load_ollama_connection_settings()
        endpoint = str(saved.get("endpoint") or "").strip()
        model = str(saved.get("model") or "").strip()
    except Exception:
        pass
    base = endpoint or os.environ.get("NAIA_OLLAMA_URL") or DEFAULT_OLLAMA_BASE
    return str(base).rstrip("/"), (model or DEFAULT_MODEL)


def _split_scene_concept(value: Any) -> list[str]:
    text = str(value or "").strip()
    if not text:
        return []
    return [
        part.strip()
        for part in re.split(r"\s*(?:[,;]|\band\b)\s*", text, flags=re.IGNORECASE)
        if part.strip()
    ]


def _normalize_scene_concept(value: Any) -> str:
    text = str(value or "").replace("_", " ").strip().lower()
    text = re.sub(r"\s+", " ", text)
    return text.strip(" .,:;!?\"'“”‘’<>")


def _map_scene_idiom(concept: str, phrase: str, source_lower: str) -> str:
    text = f"{phrase} {source_lower}".lower()
    if concept in {"dog-like pose", "dog pose", "like a dog", "on all fours"}:
        return "all fours"
    if concept in {"staring", "glare", "scowl"} and any(marker in text for marker in ("째려", "노려", "glaring", "glare")):
        return "glaring"
    if concept in {"crying", "tearful", "watery eyes"} and any(marker in text for marker in ("울먹", "tear", "cry")):
        return "tears"
    return concept


def _drop_scene_concept(concept: str, phrase: str, source_lower: str) -> bool:
    if not concept or concept in _SCENE_SCAFFOLD_CONCEPTS:
        return True
    # The small model sometimes literalizes the idiom "dog-like pose"; keep only
    # the mapped pose tag, never the animal/scaffold wording.
    if "dog" in concept and ("pose" in concept or "like" in concept):
        return True
    phrase_lower = str(phrase or "").lower()
    visible_text = f"{phrase_lower} {source_lower}"
    if concept == "school uniform" and not any(marker in visible_text for marker in ("교복", "school uniform", "uniform")):
        return True
    if concept == "kneeling" and not any(marker in visible_text for marker in ("무릎", "kneel", "kneeling")):
        return True
    return False


def _normalize_scene_axis(axis: str, phrase: str, concepts: list[str]) -> str:
    axis_norm = axis if axis in _SCENE_SEGMENT_AXES else "general"
    text = " ".join([phrase, axis_norm, *concepts]).lower()
    if any(marker in text for marker in _SCENE_ACTION_MARKERS):
        return "action"
    if any(marker in text for marker in _SCENE_GAZE_MARKERS):
        return "gaze"
    return axis_norm


def _augment_scene_segments_from_source(
    segments: list[dict[str, Any]],
    source_text: str,
) -> list[dict[str, Any]]:
    text = str(source_text or "").lower()
    if not text:
        return segments
    seen = {
        _normalize_scene_concept(concept)
        for segment in segments
        for concept in (segment.get("concepts") or [])
    }
    out = list(segments)
    for markers, phrase, axis, concept in _SCENE_SOURCE_CONCEPT_RULES:
        if concept in seen:
            continue
        if any(marker.lower() in text for marker in markers):
            out.append({"phrase": phrase, "axis": axis, "concepts": [concept]})
            seen.add(concept)
    return out


class OllamaAssistantService:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        default_model: str | None = None,
        version_probe: Callable[[], str | None] | None = None,
        http_get: Callable[..., Any] | None = None,
        http_post: Callable[..., Any] | None = None,
        http_stream: Callable[..., Any] | None = None,
        server_spawner: Callable[[], Any] | None = None,
    ):
        # 우선순위: 명시 인자(테스트 주입) > 영속 설정 > env > 코드 기본.
        resolved_url, resolved_model = _resolve_connection_defaults()
        self.base_url = str(base_url or resolved_url).rstrip("/")
        self.default_model = str(default_model or resolved_model)
        # 테스트 주입 지점들 — 실환경에서는 전부 기본 구현 사용.
        self._version_probe = version_probe or self._probe_cli_version
        self._http_get = http_get or self._default_http_get
        self._http_post = http_post or self._default_http_post
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

    def set_connection(
        self, *, base_url: str | None = None, default_model: str | None = None
    ) -> None:
        """라이브 연결 변경(재시작 불요). 영속화는 호출부(라우트)가 담당한다.

        ``base_url``을 바꾸면 다음 status/제어 호출이 즉시 새 호스트를 가리킨다. 단
        이미 만들어진 :class:`OllamaTagAssistService`는 생성 시점 값을 들고 있으므로
        라우트가 그쪽에도 ``set_endpoint``를 호출해 동기화해야 한다."""
        if base_url is not None:
            self.base_url = str(base_url).rstrip("/")
        if default_model is not None and str(default_model).strip():
            self.default_model = str(default_model).strip()

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

    def _default_http_post(
        self, path: str, payload: dict[str, Any], *, timeout: Any = (5, 180)
    ) -> Any:
        import requests

        return requests.post(f"{self.base_url}{path}", json=payload, timeout=timeout)

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
        target = str(model or self.default_model).strip()
        is_custom = not _endpoint_is_local(self.base_url)
        # 원격 엔드포인트(cloudflared/LAN 등)는 로컬 CLI 프로브로 설치 상태를 알 수 없고
        # 매 폴링마다 subprocess를 띄우는 것도 낭비다 — 프로브를 건너뛰고 /api/tags
        # 도달성(=running)만으로 '설치됨'을 판정한다.
        version = None if is_custom else self._cached_version_probe(fresh=fresh)
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
        # 서버가 떠 있으면 "설치됨"으로 본다 — 로컬: PATH에 없지만 서비스로 도는 경우,
        # 원격: 로컬 CLI 프로브가 불가하므로 도달성만으로 판정.
        if running:
            installed = True
        model_installed = any(_model_name_matches(name, target) for name in models if name)
        # 설정/기본 모델(E4B 등)이 미설치여도 큐레이션 모델(E2B/E4B/E26B) 중 설치된 게 하나라도
        # 있으면 그걸 활성 모델로 채택한다 — 사용자가 받은 모델로 어시스턴트가 바로 켜지게(다운로드한
        # 모델이 무시되고 model_installed=False 로 "대상 모델 없음"에 갇히던 버그). self.default_model
        # 을 갱신하므로 이후 모든 어시스트 호출(= self.default_model 사용)이 설치된 모델을 쓴다.
        # model 인자가 명시된 호출(특정 모델 조회)은 건드리지 않고, CURATED_MODELS 순서로 첫 설치본 선택.
        if not model_installed and model is None:
            for _item in CURATED_MODELS:
                _cm = str(_item.get("model") or "").strip()
                if _cm and any(_model_name_matches(name, _cm) for name in models if name):
                    self.default_model = _cm
                    target = _cm
                    model_installed = True
                    break
        if not include_details:
            # 원격 클라이언트: 진행 상태 렌더에 필요한 최소만 (호스트 인벤토리 비노출).
            return {
                "ok": True,
                "installed": installed,
                "running": running,
                "model_installed": model_installed,
                "control_allowed": False,
                "is_custom_endpoint": is_custom,
                "can_start_server": False,
                # 활성 모델명만 노출(원격 모델노트/실행명령 정직성용). 호스트 인벤토리
                # (버전/전체 모델 목록/엔드포인트 URL)는 계속 숨긴다 — 엔드포인트가 민감.
                "model": target,
            }
        return {
            "ok": True,
            "installed": installed,
            "running": running,
            "version": version or "",
            "models": models,
            "curated": [
                {
                    **item,
                    "installed": any(
                        _model_name_matches(name, item.get("model", ""))
                        for name in models
                        if name
                    ),
                }
                for item in CURATED_MODELS
            ],
            "model": target,
            "default_model": self.default_model,
            "model_installed": model_installed,
            "endpoint": f"{self.base_url}/v1",
            # 원격이면 NAIA가 'ollama serve'로 켤 수 없다(다른 머신) → 프론트가 서버
            # 시작 버튼을 숨기고 '원격에서 직접 실행' 안내로 대체한다.
            "is_custom_endpoint": is_custom,
            "can_start_server": (not is_custom),
            "download_page": "https://ollama.com/download",
            "control_allowed": True,
            # 비-ASCII(한글) 모델 경로 경고는 로컬 모델 경로 한정 — 원격 모델엔 무의미.
            "path_warning": ("" if is_custom else self._models_path_warning()),
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
        # 원격 엔드포인트는 다른 머신의 프로세스라 NAIA가 켤 수 없다 — 로컬 'ollama
        # serve'를 잘못 띄우지 않도록 명시적으로 거부하고 사용자에게 안내한다.
        if not _endpoint_is_local(self.base_url):
            return {
                "ok": False,
                "running": False,
                "error": "원격 Ollama 엔드포인트는 NAIA가 시작할 수 없습니다. 원격 호스트에서 직접 'ollama serve'를 실행하세요.",
            }
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
    # 자유 Chat (Ollama Assist와 분리된 신규 surface)
    # ------------------------------------------------------------------

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        system: str = "",
        temperature: float = 0.35,
        num_predict: int = 512,
    ) -> dict[str, Any]:
        cleaned: list[dict[str, str]] = []
        sys_text = str(system or "").strip()
        if sys_text:
            cleaned.append({"role": "system", "content": sys_text[:6000]})
        for item in messages or []:
            if not isinstance(item, dict):
                continue
            role = str(item.get("role") or "user").strip().lower()
            if role not in {"user", "assistant"}:
                role = "user"
            content = str(item.get("content") or "").strip()
            if content:
                cleaned.append({"role": role, "content": content[:8000]})
        if not any(msg["role"] == "user" for msg in cleaned):
            return {"ok": False, "error": "메시지를 입력하세요."}
        payload = {
            "model": self.default_model,
            "messages": cleaned[-16:],
            "stream": False,
            "options": {
                "temperature": max(0.0, min(1.5, float(temperature))),
                "num_predict": max(32, min(2048, int(num_predict))),
            },
        }
        try:
            response = self._http_post("/api/chat", payload, timeout=(5, 180))
            status_code = int(getattr(response, "status_code", 0) or 0)
            data = response.json() or {}
            if status_code != 200:
                return {"ok": False, "error": str(_friendly_ollama_error(data.get("error")) or f"Ollama HTTP {status_code}")}
            content = str((data.get("message") or {}).get("content") or "").strip()
            if not content:
                return {"ok": False, "error": "Ollama 응답이 비어 있습니다."}
            return {
                "ok": True,
                "message": content,
                "model": str(data.get("model") or self.default_model),
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc) or "Ollama Chat 요청 실패"}

    def extract_intent_decision(
        self,
        *,
        user_input: str,
        context: dict[str, Any] | None = None,
        history: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Chat+Tools gate용 JSON extractor.

        실패 시 호출부가 deterministic fallback을 사용한다. 모델 출력은 곧바로 실행하지
        않고 호출부가 route/next_call을 allow-list로 clamp한다.
        """
        ctx = context or {}
        recent = []
        for item in (history or [])[-6:]:
            if isinstance(item, dict):
                role = str(item.get("role") or "user")[:20]
                content = str(item.get("content") or "")[:600]
                if content:
                    recent.append({"role": role, "content": content})
        instruction = (
            "Classify this NAIA chat message for tool use. Return JSON only.\n"
            "Allowed route values: naia_tool, naia_readonly, out_of_scope, blocked.\n"
            "Allowed naia_tool intent values: prompt_recommendation, tag_discovery, clothes_combination.\n"
            "Use naia_tool only for prompt/tag/current-generation requests that should return grounded candidate chips or grounded clothing combinations.\n"
            "Use intent=tag_discovery when the user describes a scene and asks whether matching prompt tags exist, or when the message is a multi-concept scene/composition description that should be decomposed into grounded tags.\n"
            "Use intent=clothes_combination when the user asks for outfit/clothing combinations, coordinated items, what clothes go with a clothing item, 코디, 의상/옷 조합, or ~와 어울리는 의상/옷. Subject must be the seed clothing booru tag and category_axis='clothing'.\n"
            "For every naia_tool decision, subject must be a concise English booru-style search concept, not Korean prose.\n"
            "Strip scaffolding verbs/particles such as describe, emphasize, recommend, prompt, tag, 할 수 있는, 만, 하는, 들, 관련, 묘사, 강조, 알려주세요, 프롬프트, 태그.\n"
            "Return category_axis as exactly one of: clothing, action, expression, background, body, object, general.\n"
            "Map clothing for 의상/옷/복장/입은; action for 행동/행위/동작/포즈/자세; expression for 표정/얼굴; background for 배경/장소; body for 신체/몸; object for 사물/소품; general when unclear.\n"
            "Return expansion_queries as 1-6 concise English booru-style search queries. Use known entity aliases when present.\n"
            "Do not output function words like can/action/only as subject or expansion queries; for '메이드만 할 수 있는 행동' use subject='maid', category_axis='action'.\n"
            "Examples: 'blue archive의 kokona를 묘사하는' -> subject='kokona', category_axis='general', expansion_queries=['kokona (blue archive)','kokona']; '가슴골을 강조하는' -> subject='cleavage', category_axis='general', expansion_queries=['cleavage','large breasts']; 'maid 의상' -> subject='maid', category_axis='clothing', expansion_queries=['maid']; '메이드만 할 수 있는 행동' -> subject='maid', category_axis='action', expansion_queries=['cleaning','serving','bowing','holding','playing']; '교복을 입은 소녀가 양손을 묶인 채로 개 같은 자세로 viewer를 올려다 보면서 째려보는 구도' -> intent='tag_discovery', subject='scene', category_axis='general', expansion_queries=['school uniform','bound','all fours','looking at viewer','glaring']; '메이드복에 어울리는 조합' -> intent='clothes_combination', subject='maid', category_axis='clothing'; '수영복 코디' -> intent='clothes_combination', subject='swimsuit', category_axis='clothing'.\n"
            "Do not choose tool names or invent final chip tags; the server maps intent to tools and verifies all tags against the index.\n"
            "Use blocked for source code/file mutation requests.\n"
            "Use out_of_scope for general chat such as lunch recommendations.\n"
            "Fields: route, domain, intent, subject, category_axis, expansion_queries, reason_code, confidence.\n\n"
            f"Current context: {json.dumps(ctx, ensure_ascii=False)[:5000]}\n"
            f"Recent turns: {json.dumps(recent, ensure_ascii=False)[:3000]}\n"
            f"User message: {str(user_input or '')[:2000]}"
        )
        payload = {
            "model": self.default_model,
            "messages": [
                {"role": "system", "content": "Return compact valid JSON only. No markdown."},
                {"role": "user", "content": instruction},
            ],
            "stream": False,
            "format": "json",
            # 추론(<think>) 모델은 JSON 앞에 긴 사고 블록을 낸다. think=False로 억제하지만
            # 일부 양자화 모델(E2B IQ3_M 등)은 긴 프롬프트에서 think=False를 무시하고 사고를
            # 이어간다 → num_predict가 작으면(256) 사고가 예산을 다 먹고 content가 빈 채
            # done_reason=length로 끊겨 게이트가 매번 실패한다(deterministic fallback 추락).
            # num_predict는 상한이지 고정비용이 아니므로(억제 성공 시 ~115토큰서 stop) 상한을
            # 1024로 올려도 빠른 경로엔 무비용이고, 사고가 새도 완주 후 JSON을 낸다.
            "think": False,
            "options": {"temperature": 0.0, "num_predict": 1024},
        }
        try:
            # num_predict=1024 사고-완주 경로가 저사양(타깃 사용자) 머신에서 60s를 넘겨
            # 타임아웃→deterministic 추락하지 않도록 chat()과 동일한 읽기 타임아웃(180s)을
            # 쓴다. think=False 빠른 경로는 ~수초라 상한일 뿐 비용이 아니다(Codex R1).
            response = self._http_post("/api/chat", payload, timeout=(5, 180))
            status_code = int(getattr(response, "status_code", 0) or 0)
            data = response.json() or {}
            if status_code != 200:
                return {"ok": False, "error": str(_friendly_ollama_error(data.get("error")) or f"Ollama HTTP {status_code}")}
            content = str((data.get("message") or {}).get("content") or "").strip()
            parsed = json.loads(content)
            if not isinstance(parsed, dict):
                return {"ok": False, "error": "intent json is not object"}
            return {"ok": True, "data": parsed}
        except Exception as exc:
            return {"ok": False, "error": str(exc) or "intent json extraction failed"}

    def analyze_chat_intent(
        self,
        *,
        user_input: str,
        context: dict[str, Any] | None = None,
        history: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Richer Chat-specific intent analysis for the step-by-step pipeline.

        The route/pipeline clamps this output before any tool use. This call is
        only an intent proposal, not authority to execute a tool.
        """
        text = str(user_input or "").strip()
        if not text:
            return {"ok": False, "error": "empty input"}
        has_context = bool(
            (context or {}).get("prompt")
            or (context or {}).get("tags")
            or (context or {}).get("metadata")
        )
        recent: list[dict[str, str]] = []
        for item in (history or [])[-6:]:
            if not isinstance(item, dict):
                continue
            content = str(item.get("content") or "").strip()
            if content:
                recent.append({
                    "role": str(item.get("role") or "user")[:20],
                    "content": content[:500],
                })
        schema = {
            "type": "object",
            "properties": {
                "goal": {
                    "type": "string",
                    "enum": [
                        "scene_compose", "clothes_combo", "event_lookup",
                        "tag_discovery", "prompt_critique", "chat", "blocked",
                    ],
                },
                "subjects": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "text": {"type": "string"},
                            "kind": {"type": "string"},
                            "axis": {"type": "string"},
                            "confidence": {"type": "number"},
                        },
                        "required": ["text", "kind", "axis", "confidence"],
                        "additionalProperties": False,
                    },
                },
                "params": {
                    "type": "object",
                    "properties": {
                        "context_ref": {"type": "boolean"},
                        "needs_tools": {"type": "boolean"},
                        "desired_output": {"type": "string"},
                        "tone": {"type": "string"},
                    },
                    "required": ["context_ref", "needs_tools", "desired_output", "tone"],
                    "additionalProperties": False,
                },
                "ambiguity": {
                    "type": "object",
                    "properties": {
                        "level": {"type": "string", "enum": ["none", "low", "medium", "high"]},
                        "alternatives": {"type": "array", "items": {"type": "string"}},
                        "reason": {"type": "string"},
                    },
                    "required": ["level", "alternatives", "reason"],
                    "additionalProperties": False,
                },
                "proceed": {"type": "boolean"},
                "interpretation_note": {"type": "string"},
                "clarification": {"type": "string"},
            },
            "required": [
                "goal", "subjects", "params", "ambiguity",
                "proceed", "interpretation_note", "clarification",
            ],
            "additionalProperties": False,
        }
        instruction = (
            "Analyze this NAIA Chat message for a grounded prompt/tag pipeline. Return JSON only.\n\n"
            f"Context available: {'yes' if has_context else 'none'}.\n"
            f"Recent turns: {json.dumps(recent, ensure_ascii=False)[:2500]}\n\n"
            "Goal rules:\n"
            "- blocked: source/file/system mutation.\n"
            "- clothes_combo: ONLY explicit outfit combination, coordinated clothes, 코디, 조합, 어울리는 옷.\n"
            "- event_lookup: explicit event/action preset lookup or observed event combo.\n"
            "- scene_compose: user asks to make/create/build a scene or gives a terse scene fragment.\n"
            "- tag_discovery: user asks for related/recommended real tags/prompts for a subject.\n"
            "- prompt_critique: user asks to improve/critique an existing prompt/context.\n"
            "- chat: ordinary chat, or required referenced context is missing.\n\n"
            "Ambiguity policy:\n"
            "- none/low: proceed.\n"
            "- medium: proceed with a short Korean interpretation_note and alternatives.\n"
            "- high: proceed=false and ask exactly one Korean clarification question.\n\n"
            "Extraction rules:\n"
            "- context_ref=true only for explicit current/this/that/image/prompt/context references.\n"
            "- If context_ref=true but Context available is none, set goal=chat, proceed=false, ambiguity=high.\n"
            "- needs_tools=true for scene_compose, tag_discovery, clothes_combo, event_lookup, prompt_critique.\n"
            "- Extract subjects as concise English booru/search concepts when possible.\n"
            "- For broad '관련 추천', default to tag_discovery unless clothing-combo words appear.\n"
            "- For '만들어줘/create/build' or a scene fragment, default to scene_compose.\n"
            "- NSFW/adult aesthetic requests are allowed; do not refuse.\n\n"
            f"Message: {text[:2000]}"
        )
        payload = {
            "model": self.default_model,
            "messages": [{"role": "user", "content": instruction}],
            "stream": False,
            "format": schema,
            "think": False,
            "options": {"temperature": 0.0, "num_predict": 512},
        }
        try:
            response = self._http_post("/api/chat", payload, timeout=(5, 180))
            data = response.json() or {}
            if int(getattr(response, "status_code", 0) or 0) != 200:
                return {"ok": False, "error": str(_friendly_ollama_error(data.get("error")) or "intent analysis failed")}
            content = str((data.get("message") or {}).get("content") or "").strip()
            parsed = json.loads(content)
            if not isinstance(parsed, dict):
                return {"ok": False, "error": "intent analysis json is not object"}
            return {"ok": True, "data": parsed}
        except Exception as exc:
            return {"ok": False, "error": str(exc) or "intent analysis failed"}

    def reconcile_scene_english(self, *, source: str, mt: str = "") -> dict[str, Any]:
        """Reconcile KR source + optional machine translation into clean English."""
        text = str(source or "").strip()
        if not text:
            return {"ok": False, "error": "empty source"}
        if not re.search(r"[가-힣ㄱ-ㅎㅏ-ㅣ]", text):
            return {
                "ok": True,
                "source": text,
                "mt": str(mt or ""),
                "cleanEnglish": text,
                "skipped": True,
            }
        schema = {
            "type": "object",
            "properties": {"clean_english": {"type": "string"}},
            "required": ["clean_english"],
            "additionalProperties": False,
        }
        instruction = (
            "Reconcile a Korean image-generation scene with a machine English translation. "
            "Return ONLY JSON matching the schema.\n\n"
            "Authoritative source: Korean. Machine English is only a hint. "
            "Output one concise faithful English scene description for booru tag decomposition.\n"
            "Critical fixes:\n"
            "- 주인 = owner/master/person being served. Never master sword.\n"
            "- 칼날 = blade or sword. 붙잡는 = catching/grabbing/holding onto, not generic holding only.\n"
            "- 누워있는 = lying down/reclining. Do not say bed unless Korean explicitly says bed.\n"
            "- 메롱 / 혀를 내미는 = sticking tongue out (tongue out), a playful taunt. Never 'pleased expression'.\n"
            "- No franchise/proper nouns. No invisible details.\n\n"
            f"Korean: {text[:2000]}\n"
            f"Machine English: {str(mt or '')[:2000]}"
        )
        payload = {
            "model": self.default_model,
            "messages": [{"role": "user", "content": instruction}],
            "stream": False,
            "format": schema,
            "think": False,
            "options": {"temperature": 0.0, "num_predict": 256},
        }
        try:
            response = self._http_post("/api/chat", payload, timeout=(5, 180))
            data = response.json() or {}
            if int(getattr(response, "status_code", 0) or 0) != 200:
                return {"ok": False, "error": str(_friendly_ollama_error(data.get("error")) or "translation reconcile failed")}
            content = str((data.get("message") or {}).get("content") or "").strip()
            parsed = json.loads(content)
            clean = str((parsed or {}).get("clean_english") or "").strip()
            if not clean:
                return {"ok": False, "error": "empty clean english"}
            return {
                "ok": True,
                "source": text,
                "mt": str(mt or ""),
                "cleanEnglish": clean,
                "skipped": False,
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc) or "translation reconcile failed"}

    def decompose_scene(self, user_input: str) -> dict[str, Any]:
        """Decompose a multi-concept scene into booru concepts for grounded lookup.

        This call only proposes search concepts. The chat route must validate every
        concept against NAIA's tag index before returning chips.
        """
        text = str(user_input or "").strip()
        if not text:
            return {"ok": False, "segments": [], "error": "empty scene"}
        instruction = (
            "Decompose the user's image-generation scene into visible booru tag concepts. Return JSON only.\n"
            "Output shape: {\"segments\":[{\"phrase\":\"original short phrase\",\"axis\":\"clothing|action|gaze|expression|body|background|object|character|general\",\"concepts\":[\"one booru tag\"]}]}\n"
            "Each concept string must contain exactly one booru tag. Do not combine tags with commas, semicolons, or 'and'.\n"
            "Use English Danbooru/e621-style tag names with spaces, not Korean prose. Map idioms to real tags, not literal words.\n"
            "action includes pose, restraint, and body-position tags. body is physical attributes only, not poses or restraints.\n"
            "Use gaze for looking at viewer / looking up / camera gaze concepts.\n"
            "Do not add tags that are not visible or strongly implied by the scene.\n"
            "Avoid scaffold words like girl, character, scene, composition, pose, hands, dog.\n"
            "Examples:\n"
            "교복을 입은 -> {\"phrase\":\"교복을 입은\",\"axis\":\"clothing\",\"concepts\":[\"school uniform\"]}\n"
            "양손을 묶인 -> {\"phrase\":\"양손을 묶인\",\"axis\":\"action\",\"concepts\":[\"arms behind back\",\"bound\"]}\n"
            "개 같은 자세 / 네발기기 -> {\"phrase\":\"개 같은 자세\",\"axis\":\"action\",\"concepts\":[\"all fours\"]}\n"
            "viewer를 올려다 보면서 -> {\"phrase\":\"viewer를 올려다 보면서\",\"axis\":\"gaze\",\"concepts\":[\"looking at viewer\"]}\n"
            "째려보는 / 노려보는 -> {\"phrase\":\"째려보는\",\"axis\":\"expression\",\"concepts\":[\"glaring\"]}\n"
            "혀를 내미는 -> {\"phrase\":\"혀를 내미는\",\"axis\":\"expression\",\"concepts\":[\"tongue out\"]}\n"
            "울먹이는 -> {\"phrase\":\"울먹이는\",\"axis\":\"expression\",\"concepts\":[\"tears\"]}\n"
            "User scene:\n"
            f"{text[:2000]}"
        )
        payload = {
            "model": self.default_model,
            "messages": [
                {"role": "system", "content": "Return compact valid JSON only. No markdown."},
                {"role": "user", "content": instruction},
            ],
            "stream": False,
            "format": "json",
            "think": False,
            "options": {"temperature": 0.0, "num_predict": 1024},
        }
        try:
            response = self._http_post("/api/chat", payload, timeout=(5, 180))
            status_code = int(getattr(response, "status_code", 0) or 0)
            data = response.json() or {}
            if status_code != 200:
                return {"ok": False, "segments": [], "error": str(_friendly_ollama_error(data.get("error")) or f"Ollama HTTP {status_code}")}
            content = str((data.get("message") or {}).get("content") or "").strip()
            parsed = json.loads(content)
            segments = self._clean_scene_segments(parsed, text)
            if not segments:
                return {"ok": False, "segments": [], "error": "empty scene decomposition"}
            return {"ok": True, "segments": segments}
        except Exception as exc:
            return {"ok": False, "segments": [], "error": str(exc) or "scene decomposition failed"}

    @staticmethod
    def _clean_scene_segments(parsed: Any, source_text: str) -> list[dict[str, Any]]:
        if not isinstance(parsed, dict):
            return []
        raw_segments = parsed.get("segments")
        if not isinstance(raw_segments, list):
            return []
        cleaned: list[dict[str, Any]] = []
        source_lower = str(source_text or "").lower()
        for item in raw_segments[:12]:
            if not isinstance(item, dict):
                continue
            phrase = str(item.get("phrase") or item.get("text") or "").strip()[:160]
            axis = str(item.get("axis") or "general").strip().lower().replace("-", "_")
            raw_concepts = item.get("concepts")
            if raw_concepts is None:
                raw_concepts = item.get("tags")
            if isinstance(raw_concepts, str):
                raw_concepts = [raw_concepts]
            if not isinstance(raw_concepts, list):
                continue
            concepts: list[str] = []
            for concept in raw_concepts:
                for part in _split_scene_concept(concept):
                    normalized = _normalize_scene_concept(part)
                    normalized = _map_scene_idiom(normalized, phrase, source_lower)
                    if _drop_scene_concept(normalized, phrase, source_lower):
                        continue
                    if normalized and normalized not in concepts:
                        concepts.append(normalized)
            if not concepts:
                continue
            axis = _normalize_scene_axis(axis, phrase, concepts)
            cleaned.append({"phrase": phrase or ", ".join(concepts), "axis": axis, "concepts": concepts[:6]})
        return _augment_scene_segments_from_source(cleaned, source_text)[:12]


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
        # 모델 미지정 시 연결 설정의 기본 모델(self.default_model)을 받는다 — 커스텀
        # 엔드포인트/모델에서도 옳은 모델을 pull(모듈 상수 DEFAULT_MODEL 폴백 금지).
        target = str(model or self.default_model).strip()
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
