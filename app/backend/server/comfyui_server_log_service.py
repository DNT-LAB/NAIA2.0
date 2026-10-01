"""외부 ComfyUI(API 모드) 서버 출력 - Generate 콘솔이 읽는다(사용자 지정 2026-10-01: "API 모드에서도 Generate 를 통한
ComfyUI 백엔드 터미널 보여주는 기능". 인계 docs/COMFYUI_API_TERMINAL_HANDOFF_2026_10_01.md).

ComfyUI 는 자기 stdout/stderr 를 최근 300조각 링에 들고 있다(app/logger.py LogInterceptor - 줄이 아니라 write 조각) -
GET /internal/logs/raw 가 {"entries": [{"t", "m"}...], "size": {...}} 로 준다(설치본 v0.22.0 소스로 확인). 이 경로는 ComfyUI
프런트 전용이라 버전 · 프록시에 따라 없을 수 있다고 보고 다룬다: 404 · 405 · 501 · 401/403 · 모양이 다른 응답은 '미지원' 으로
답하고(잠시 기억해 다시 두드리지 않는다), 연결 실패는 '닿지 않음' 으로 답한다. 어느 쪽도 생성 경로에는 닿지 않는다.

링에는 커서가 없고 회전하며, 진행 막대('\\r' 로 시작하는 조각)는 줄이 끝나지 않은 마지막 조각을 갈아 끼운다. 그래서 받은
스냅숏을 앞 스냅숏과 **겹치는 위치**로 이어 붙여 새 조각에만 우리 순번(seq)을 단다 - 같은 문장이 되풀이돼도 지우지 않는다.
겹치는 데가 없으면(서버 재시작 · 두 번 읽는 사이 300조각 넘게 찍힘) 이어지지 않았다고(gap) 알린다.

- 첫 조회(since 없음)는 '지금부터' 다 - 그 전의 서버 출력(앞 요청의 것)은 보이지 않는다.
- 서버 전체 출력이다. entries 에 prompt_id 가 없으니 이 요청만의 로그라고 단정하지 않는다(화면 머리에 'ComfyUI 서버 출력').
- 저장된 외부 URL(comfyui_url)만 연다 - 화면이 URL 이나 경로를 넘기지 않는다. 관리형 엔진은 자기 engine.log 콘솔이 있다.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any, Callable

import requests

LOG_PATH = "/internal/logs/raw"
TIMEOUT = (1.5, 3.0)            # (연결, 읽기) - 콘솔 조회가 오래 붙잡지 않게
MIN_INTERVAL = 0.4              # 여러 탭 · 콘솔이 함께 물어도 외부 서버에는 이 간격으로만 묻는다
FRESH_WAIT = 5.0                # '지금' 이 필요한 조회(기준선 · 마지막)가 앞 조회를 기다리는 한도
UNSUPPORTED_TTL = 60.0          # '미지원' 을 기억하는 시간 - 서버를 바꿔 끼웠을 수 있어 영원히는 아니다
MAX_ENTRIES = 2000              # 우리 쪽에 쌓아 두는 조각 수
MAX_TEXT = 64 * 1024            # 한 번에 돌려주는 글자 수 - 넘치면 뒤쪽을 주고 gap 으로 알린다


class LogUnsupported(Exception):
    """이 서버는 로그 API 를 주지 않는다(없음 · 권한 · 모양이 다름)."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def base_url(raw: Any) -> str:
    # core/comfyui_service.ComfyUIService 와 같은 규칙(끝 / 제거 · 스킴이 없으면 http://)
    url = str(raw or "").strip().rstrip("/")
    if url and not url.startswith("http"):
        url = f"http://{url}"
    return url


def fetch_entries(url: str) -> list[tuple[str, str]]:
    try:
        response = requests.get(url + LOG_PATH, timeout=TIMEOUT)
    except requests.RequestException as exc:
        raise ConnectionError(type(exc).__name__) from None
    if response.status_code in (401, 403, 404, 405, 501):
        raise LogUnsupported(f"HTTP {response.status_code}")
    if response.status_code != 200:
        raise ConnectionError(f"HTTP {response.status_code}")
    try:
        data = response.json()
    except ValueError:
        raise LogUnsupported("format") from None
    entries = data.get("entries") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        raise LogUnsupported("format")
    out = []
    for item in entries:
        if not isinstance(item, dict) or not isinstance(item.get("m"), str):
            raise LogUnsupported("format")
        out.append((str(item.get("t") or ""), item["m"]))
    return out


def _overlap(prev: list, cur: list) -> int | None:
    """prev 의 끝 L 조각 == cur 의 앞 L 조각인 L. 같은 링의 뒤 스냅숏이면 cur = prev[k:] + 새 조각들이다."""
    if not prev:
        return None
    last = prev[-1]
    for j in range(len(cur) - 1, -1, -1):
        if cur[j] == last and j + 1 <= len(prev) and prev[len(prev) - j - 1:] == cur[:j + 1]:
            return j + 1
    return None


def merge(prev: list, cur: list) -> tuple[list, bool]:
    """(새 조각들, 이어졌나). 이어지지 않으면 cur 전부가 새것이다(재시작한 서버의 출력 · 넘쳐서 놓친 뒤의 출력)."""
    length = _overlap(prev, cur)
    if length is None and prev and not prev[-1][1].endswith("\n"):
        # 줄이 끝나지 않은 마지막 조각(진행 막대)은 '\r' 조각이 갈아 끼운다(LogInterceptor.write) - 그 조각을 빼고 다시 맞춘다
        length = _overlap(prev[:-1], cur)
    if length is None:
        return list(cur), False
    return cur[length:], True


class ExternalComfyLog:
    def __init__(self, fetch: Callable[[str], list] = fetch_entries, clock: Callable[[], float] = time.monotonic):
        self._fetch = fetch
        self._clock = clock
        self._state_lock = threading.Lock()
        self._fetch_lock = threading.Lock()
        self._url = ""
        self._snapshot: list | None = None      # None = 이 서버는 아직 한 번도 못 읽었다(첫 스냅숏은 기준선)
        self._entries: deque = deque(maxlen=MAX_ENTRIES)   # (seq, text)
        self._gaps: deque = deque(maxlen=64)               # 이 순번부터는 앞과 이어지지 않는다
        self._seq = 0
        self._fetched_at = float("-inf")
        self._state, self._reason = "ok", ""
        self._unsupported_until = float("-inf")

    def read(self, url: Any, since: int | None = None, fresh: bool = False) -> dict[str, Any]:
        url = base_url(url)
        with self._state_lock:
            if url != self._url:
                self._switch(url)
        if not url:
            return {"ok": True, "state": "unconfigured", "reason": "", "text": "", "since": self._seq, "gap": False}
        # 기준선(since 없음)과 마지막 조회(fresh)는 '지금' 의 서버를 읽어야 한다 - 간격 · 앞 조회와 관계없이 새로 묻는다
        self._refresh(url, wait=fresh or since is None)
        with self._state_lock:
            payload = self._payload(since)
            if fresh and self._state == "ok":
                # A fast failure can already be inside the first baseline. Only the final read
                # carries this bounded, explicitly labelled fallback; normal polls remain deltas.
                tail, remaining = [], MAX_TEXT
                for _, text in reversed(self._snapshot or []):
                    tail.append(text[-remaining:])
                    remaining -= len(tail[-1])
                    if not remaining:
                        break
                payload["tail"] = "".join(reversed(tail))
            return payload

    def _switch(self, url: str) -> None:
        # 다른 서버 - 앞 서버의 조각은 버리고 순번은 이어 간다. 번호 하나를 비워 둔다: 앞 서버의 커서(이전 순번)를 든 화면은
        # gap 을 받고, 바꾼 뒤에 기준선을 잡은 화면(비운 번호)은 받지 않는다 - 안 비우면 둘의 커서가 같아 가를 수 없다.
        self._url = url
        self._snapshot = None
        self._entries.clear()
        self._seq += 1
        self._gaps.append(self._seq)
        self._fetched_at = float("-inf")
        self._state, self._reason = "ok", ""
        self._unsupported_until = float("-inf")

    def _refresh(self, url: str, *, wait: bool) -> None:
        with self._state_lock:
            if self._state == "unsupported" and self._clock() < self._unsupported_until:
                return
            if not wait and self._clock() - self._fetched_at < MIN_INTERVAL:
                return
        acquired = self._fetch_lock.acquire(timeout=FRESH_WAIT) if wait else self._fetch_lock.acquire(blocking=False)
        if not acquired:
            return                          # 다른 조회가 서버에 묻는 중 - 쌓인 것으로 답한다
        try:
            if not wait and self._clock() - self._fetched_at < MIN_INTERVAL:
                return                      # 기다리는 사이 누가 받아 왔다
            entries, state, reason = None, "ok", ""
            try:
                entries = self._fetch(url)
            except LogUnsupported as exc:
                state, reason = "unsupported", exc.reason
            except Exception as exc:        # 연결 실패 · 시간 초과 · 5xx - 다음 조회에서 다시 묻는다
                state, reason = "unreachable", str(exc) or type(exc).__name__
            with self._state_lock:
                if url != self._url:
                    return                  # 그 사이 URL 이 바뀌었다 - 옛 서버의 답은 버린다
                self._fetched_at = self._clock()
                self._state, self._reason = state, reason
                if state == "unsupported":
                    self._unsupported_until = self._fetched_at + UNSUPPORTED_TTL
                if entries is not None:
                    self._absorb(entries)
        finally:
            self._fetch_lock.release()

    def _absorb(self, entries: list) -> None:
        prev, self._snapshot = self._snapshot, entries
        if prev is None:
            return                          # 첫 스냅숏 = 기준선(그 전 출력은 앞 요청 · 다른 손님의 것이다)
        new, joined = merge(prev, entries)
        if not joined:
            self._gaps.append(self._seq + 1)
        for _, text in new:
            self._seq += 1
            self._entries.append((self._seq, text))

    def _payload(self, since: int | None) -> dict[str, Any]:
        base = {"ok": True, "state": self._state, "reason": self._reason}
        latest = self._seq
        if since is None:
            return {**base, "text": "", "since": latest, "gap": False}
        if since > latest:                  # NAIA 가 다시 켜져 순번이 처음부터다 - 지금부터 다시
            return {**base, "text": "", "since": latest, "gap": True}
        oldest = self._entries[0][0] if self._entries else latest + 1
        text = "".join(chunk for seq, chunk in self._entries if seq > since)
        gap = since < oldest - 1 or any(mark > since for mark in self._gaps)
        if len(text) > MAX_TEXT:
            text, gap = text[-MAX_TEXT:], True
        return {**base, "text": text, "since": latest, "gap": gap}


def service_for(context: Any) -> ExternalComfyLog:
    service = getattr(context, "_comfyui_server_log", None)
    if service is None:
        service = ExternalComfyLog()
        setattr(context, "_comfyui_server_log", service)
    return service


def server_log_payload(context: Any, since: int | None = None, fresh: bool = False) -> dict[str, Any]:
    from core.anima_engine import integration
    if integration.managed_selected(context):
        # 관리형 ANIMA 는 자기 기동 콘솔(engine.log)이 있다 - 외부 로그를 읽지 않는다
        return {"ok": True, "state": "managed", "reason": "", "text": "", "since": since or 0, "gap": False}
    url = context.secure_token_manager.get_token("comfyui_url")
    return service_for(context).read(url, since, fresh)
