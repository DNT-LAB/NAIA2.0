"""
NAIA Remote API Server
- FastAPI + uvicorn을 daemon thread에서 실행
- RemoteBridge(QObject)로 FastAPI ↔ Qt 메인 스레드 간 통신
- WebSocket으로 실시간 이미지 푸시
"""
import io
import json
import asyncio
import base64
import random
import re
import time
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import FileResponse, Response, JSONResponse
from fastapi.staticfiles import StaticFiles

from PyQt6.QtCore import QObject, pyqtSignal, Qt, QTimer
from PyQt6.QtWidgets import QFileDialog

from core import api_verification
from core.tag_knowledge import apply_translation_overrides, merge_parquet_tag_records
from core.tag_relation_ranker import TagRelationRanker
from core.tag_search_index import TagSearchIndex


# ---------------------------------------------------------------------------
# WebSocket Manager
# ---------------------------------------------------------------------------
class WebSocketManager:
    """연결된 WebSocket 클라이언트 관리 및 broadcast"""

    def __init__(self):
        self.active_connections: set[WebSocket] = set()
        self._send_lock = asyncio.Lock()
        self.sessions: dict[WebSocket, dict] = {}
        self._bridge_ref = None  # RemoteBridge 역참조 (disconnect 시 pending 정리용)

    async def connect(self, ws: WebSocket) -> str:
        await ws.accept()
        self.active_connections.add(ws)
        session_id = uuid.uuid4().hex[:8]
        self.sessions[ws] = {
            "id": session_id,
            "p_eng_override": None,
            "negative_prompt": None,
            "params_override": None,
            "tag_filter": None,
            "tag_filter_pending": None,
            "active_ratings": None,
            "eligible_ids": None,
        }
        print(f"🌐 Remote client connected (session={session_id}, total: {len(self.active_connections)})")
        return session_id

    async def disconnect(self, ws: WebSocket):
        self.active_connections.discard(ws)
        session = self.sessions.pop(ws, None)
        sid = session["id"] if session else "?"
        # 연결 해제된 WS에 대한 bridge 참조 무효화
        if self._bridge_ref:
            bridge = self._bridge_ref
            bridge._pending_overrides.pop(ws, None)
        print(f"🌐 Remote client disconnected (session={sid}, total: {len(self.active_connections)})")

    async def broadcast_image(self, webp_bytes: bytes, metadata: dict):
        """모든 클라이언트에 메타데이터(JSON) + 이미지(binary) 전송"""
        async with self._send_lock:
            try:
                meta_text = json.dumps({"type": "image_meta", **metadata})
            except Exception as e:
                print(f"🌐 broadcast_image JSON 직렬화 실패: {e}")
                return
            dead = set()
            for ws in list(self.active_connections):
                try:
                    await ws.send_text(meta_text)
                    await ws.send_bytes(webp_bytes)
                except Exception:
                    dead.add(ws)
            self.active_connections -= dead

    async def broadcast_json(self, data: dict):
        """모든 클라이언트에 JSON 메시지 전송"""
        async with self._send_lock:
            try:
                text = json.dumps(data)
            except Exception as e:
                print(f"🌐 broadcast_json JSON 직렬화 실패: {e}")
                return
            dead = set()
            for ws in list(self.active_connections):
                try:
                    await ws.send_text(text)
                except Exception:
                    dead.add(ws)
            self.active_connections -= dead

    async def send_json_to(self, ws: WebSocket, data: dict):
        """특정 클라이언트에만 JSON 전송."""
        try:
            await ws.send_text(json.dumps(data))
        except Exception:
            self.active_connections.discard(ws)


# ---------------------------------------------------------------------------
# Remote Bridge (Qt ↔ FastAPI 스레드 간 브릿지)
# ---------------------------------------------------------------------------
class RemoteBridge(QObject):
    """
    pyqtSignal 기반 스레드 브릿지.
    - FastAPI 스레드에서 emit → Qt 메인 스레드에서 슬롯 실행
    - Qt 메인 스레드에서 emit → asyncio loop로 전달
    """
    # FastAPI → Qt 메인 스레드
    request_generate = pyqtSignal()               # deque에서 pop
    request_random = pyqtSignal()                  # deque에서 pop
    request_set_option = pyqtSignal(str, bool)   # (option_key, checked)
    request_set_prompt = pyqtSignal(str, str)     # (prompt, negative_prompt)
    request_set_mode = pyqtSignal(str)            # API 모드 변경 (NAI/WEBUI/COMFYUI)
    request_set_api_url = pyqtSignal(str, str)    # (mode, url) — WebUI/ComfyUI URL 설정
    request_test_api = pyqtSignal(str)            # mode — API 연결 테스트
    request_set_param = pyqtSignal(str, str)      # (key, value) — 생성 파라미터 변경
    request_get_module = pyqtSignal(object, str)    # (ws, module_id) — 모듈 상태 요청
    request_set_module = pyqtSignal(str, str, str) # (module_id, key, value) — 모듈 파라미터 변경
    request_search = pyqtSignal(str)               # search_params JSON
    request_load_parquet = pyqtSignal(str)          # filename
    request_depth_action = pyqtSignal(str)          # depth search action JSON
    request_restore_snapshot = pyqtSignal()          # 메인 검색 결과 스냅샷 복원
    request_apply_filters = pyqtSignal()            # GSQE + Tag Filter → master에서 재적용
    request_refresh_cache = pyqtSignal()               # WS 연결 시 캐시 갱신 + broadcast
    request_set_desktop_visibility = pyqtSignal(bool)  # 메인 데스크탑 창 표시/숨김
    request_browse_save_directory = pyqtSignal(object)  # (ws) — 로컬 전용 폴더 선택
    request_result_enhance = pyqtSignal(object)         # (ws) — 현재 ImageWindow 결과 Enhance
    request_image_action = pyqtSignal(str, bytes, str)  # (action, image_bytes, label)
    request_set_cloudflared_enabled = pyqtSignal(bool)  # Cloudflared 연결/해제

    # 동기화 대상 옵션 키 매핑: web_key → checkbox_label
    OPTION_KEYS = {
        "prompt_fixed": "프롬프트 고정",
        "auto_generate": "자동 생성",
        "wildcard_standalone": "와일드카드 단독 모드",
    }

    def __init__(self, app_context):
        super().__init__()
        self.app_context = app_context
        self.latest_webp: Optional[bytes] = None
        self.latest_metadata_payload: Optional[dict] = None
        self._ws_manager: Optional[WebSocketManager] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._syncing_option = False
        self._syncing_prompt = False
        self._syncing_param = False
        self._prompt_debounce_timer: Optional[QTimer] = None
        self._params_debounce_timer: Optional[QTimer] = None
        self._pending_overrides: dict = {}  # {ws: {"params": ..., "negative": ..., "source": ..., "auto_generate": bool}}
        # Request queues: WS handler(asyncio)에서 준비 → Qt slot에서 소비. deque는 GIL 하 thread-safe.
        from collections import deque
        self._pending_random_requests: deque = deque()
        self._pending_generate_requests: deque = deque()
        # 캐시: FastAPI 스레드에서 Qt 위젯 직접 접근 방지
        self._cached_prompts: dict = {}
        self._cached_params: dict = {}
        self._cached_options: dict = {}
        # api_status 는 per-ws 평가(setup_allowed 가 IP별로 다름)라 캐시하지 않음.
        # Shared Server Mode: 클라이언트별 독립 P.Eng/Params/Negative
        self.shared_server_mode = False
        # 태그 검색 인덱스 (ui/interactive/interactive 기반)
        self._kr_tags_raw: dict = {}  # tag_lower → full info dict (relations, _kw_lower, _desc_lower 포함)
        self._tag_search_index: Optional[TagSearchIndex] = None
        self._tag_relation_ranker: Optional[TagRelationRanker] = None
        self._kr_tags_lock = threading.Lock()
        self._kr_tags_loaded = False
        # 캐릭터 분석 역인덱스: char_name_lower → (copyright_group, data_dict)
        self._char_analysis: dict = {}
        # Rating 필터: Web Remote GSQE 버튼 상태
        self._active_ratings: set = {'g', 's', 'q', 'e'}
        # Tag filter IDs (Non-shared only — Shared는 session dict 사용)
        self._active_tag_filter_ids: set | None = None
        # 필터 적용 중 _save_search_snapshot에서 reset 방지
        self._skip_filter_reset: bool = False
        # Viewer: 디스크 이미지 스캔 캐시
        self._viewer_cache: list = []
        self._viewer_cache_time: float = 0
        self._viewer_cache_dir: str = ""
        # NAI Anlas: 주기 + 생성 이벤트 기반 refresh. 웹 viewer 좌하단에 pill로 표시.
        self._anlas_cache: Optional[dict] = None     # {"anlas": int, "opus": bool, "tier": str, "fetched_at": str}
        self._anlas_timer: Optional[QTimer] = None
        self._anlas_fetch_in_flight: bool = False
        self._anlas_refresh_interval_ms: int = 5 * 60 * 1000  # 5분
        self._remote_enhance_in_flight: bool = False
        # ComfyUI 전용 sync request matching: request_id → asyncio.Future
        self._pending_comfyui_requests: dict = {}
        self._comfyui_requests_lock = threading.Lock()

    def set_ws_manager(self, ws_manager: WebSocketManager):
        self._ws_manager = ws_manager
        ws_manager._bridge_ref = self

    def set_event_loop(self, loop: asyncio.AbstractEventLoop):
        self._loop = loop

    def _has_clients(self) -> bool:
        return bool(self._ws_manager and self._ws_manager.active_connections)

    def _send_json_to(self, ws, data: dict):
        """특정 WS 클라이언트에만 JSON 전송 (Qt 메인 스레드에서 호출)."""
        if self._loop and self._ws_manager and ws:
            import json as _json
            asyncio.run_coroutine_threadsafe(
                self._ws_manager.send_json_to(ws, data),
                self._loop
            )

    def _recompute_eligible_ids(self, session: dict):
        """세션의 active_ratings + tag_filter 기반으로 eligible ID 벡터 재계산."""
        mw = self.app_context.main_window
        snapshot = getattr(mw, '_search_results_snapshot', None)
        if snapshot is None or snapshot.empty:
            if mw.search_results:
                snapshot = mw.search_results.get_dataframe()
        if snapshot is None or snapshot.empty:
            session["eligible_ids"] = None
            return

        mask = None
        # Rating 필터
        ratings = session.get("active_ratings")
        if ratings and 'rating' in snapshot.columns:
            mask = snapshot["rating"].isin(ratings)
        # Tag filter 교집합
        tag_filter = session.get("tag_filter")
        if tag_filter and tag_filter.get("ids"):
            id_mask = snapshot["id"].isin(tag_filter["ids"])
            mask = (mask & id_mask) if mask is not None else id_mask

        if mask is not None:
            session["eligible_ids"] = set(snapshot.loc[mask, "id"].tolist())
        else:
            session["eligible_ids"] = set(snapshot["id"].tolist())

    def _is_cloudflared_active(self) -> bool:
        """Cloudflared 터널이 활성인지 확인.

        우선순위:
          1) `app_context.cloudflared_active` 명시 플래그 (bool) — 가장 신뢰 가능
          2) 탭 인스턴스에서 `cloudflared_checkbox` 탐색 (fallback, 탭 리팩토링에 취약)
        둘 다 실패하면 False (보수적: 차단 대신 허용).
        """
        flag = getattr(self.app_context, "cloudflared_active", None)
        if isinstance(flag, bool):
            return flag
        try:
            mw = self.app_context.main_window
            if hasattr(mw, 'image_window') and hasattr(mw.image_window, 'tab_controller'):
                for tab in mw.image_window.tab_controller.tab_instances.values():
                    if hasattr(tab, 'cloudflared_checkbox'):
                        return tab.cloudflared_checkbox.isChecked()
        except Exception:
            pass
        return False

    def _get_settings_widget(self):
        """SettingsWidget 인스턴스 반환."""
        try:
            mw = self.app_context.main_window
            right_view = getattr(mw, "image_window", None)
            tab_controller = getattr(right_view, "tab_controller", None)
            if tab_controller and hasattr(tab_controller, "get_tab_instance"):
                settings_module = tab_controller.get_tab_instance("SettingsTabModule")
                if settings_module:
                    return getattr(settings_module, "settings_widget", None)
        except Exception:
            pass
        return None

    def _get_cloudflared_status(self) -> dict:
        """현재 Cloudflared 상태 반환."""
        settings_widget = self._get_settings_widget()
        url = getattr(self.app_context, "cloudflared_tunnel_url", "") or ""
        status_text = getattr(self.app_context, "cloudflared_status_text", "") or ""

        if settings_widget is not None:
            url = getattr(settings_widget, "_cloudflared_tunnel_url", "") or url
            if not status_text:
                label = getattr(settings_widget, "cloudflared_url_label", None)
                if label:
                    raw = label.text() or ""
                    status_text = re.sub(r"<[^>]+>", "", raw.replace("<br>", "\n")).strip()

        if url:
            status_text = url

        return {
            "active": bool(self._is_cloudflared_active()),
            "url": url,
            "status_text": status_text,
        }

    # --- Setup 전용 유틸 (Phase 2 / Phase 3) ---

    _SETUP_TIMESTAMP_FILE = "NAIA_api_timestamps.json"

    def _ws_client_host(self, ws) -> str:
        """WS 클라이언트 IP 안전 추출 (loopback 판정용)."""
        try:
            if ws is not None and getattr(ws, "client", None) is not None:
                return (ws.client.host or "") if hasattr(ws.client, "host") else ""
        except Exception:
            pass
        return ""

    def _setup_gate(self, ws) -> tuple[bool, str]:
        """Setup UI 활성 조건 3중 게이트 — 전부 통과해야 토큰/URL 설정 허용.

        1) 클라이언트가 loopback 에서 접속 (LAN/외부 거부)
        2) Shared Server Mode OFF
        3) Cloudflared 터널 비활성
        """
        host = self._ws_client_host(ws)
        if host not in ("127.0.0.1", "::1"):
            return False, "초기 설정은 로컬(127.0.0.1) 접속에서만 가능합니다."
        if self.shared_server_mode:
            return False, "Shared Server Mode 활성 중 — 초기 설정이 차단됩니다."
        if self._is_cloudflared_active():
            return False, "Cloudflared 터널 활성 중 — 초기 설정이 차단됩니다."
        return True, ""

    def _desktop_window_gate(self, ws) -> tuple[bool, str]:
        """데스크탑 창 제어는 로컬 loopback 클라이언트에만 허용."""
        host = self._ws_client_host(ws)
        if host not in ("127.0.0.1", "::1"):
            return False, "데스크탑 창 제어는 로컬(127.0.0.1) 접속에서만 가능합니다."
        return True, ""

    def _cloudflared_gate(self, ws) -> tuple[bool, str]:
        """Cloudflared 제어는 로컬 loopback 클라이언트에만 허용."""
        host = self._ws_client_host(ws)
        if host not in ("127.0.0.1", "::1"):
            return False, "Cloudflared 제어는 로컬(127.0.0.1) 접속에서만 가능합니다."
        return True, ""

    def _save_directory_gate(self, ws) -> tuple[bool, str]:
        """저장 디렉토리 변경은 로컬 호스트 단독 세션에서만 허용."""
        host = self._ws_client_host(ws)
        if host not in ("127.0.0.1", "::1"):
            return False, "저장 디렉토리 변경은 로컬(127.0.0.1) 접속에서만 가능합니다."
        if self.shared_server_mode:
            return False, "Shared Server Mode 활성 중 — 저장 디렉토리 변경이 차단됩니다."
        if self._is_cloudflared_active():
            return False, "Cloudflared 터널 활성 중 — 저장 디렉토리 변경이 차단됩니다."
        return True, ""

    def _result_enhance_gate(self, ws) -> tuple[bool, str]:
        """Result Enhance는 로컬 호스트 단독 세션에서만 허용."""
        host = self._ws_client_host(ws)
        if host not in ("127.0.0.1", "::1"):
            return False, "Result Enhance는 로컬(127.0.0.1) 접속에서만 가능합니다."
        if self.shared_server_mode:
            return False, "Shared Server Mode 활성 중 — Result Enhance가 차단됩니다."
        if self._is_cloudflared_active():
            return False, "Cloudflared 터널 활성 중 — Result Enhance가 차단됩니다."
        return True, ""

    def _auto_save_settings_gate(self, ws) -> tuple[bool, str]:
        """호스트 전역 auto-save 정책은 Shared Mode에서 원격 변경 차단."""
        if self.shared_server_mode:
            return False, "Shared Server Mode 활성 중 — Auto Save 정책 변경이 차단됩니다."
        return True, ""

    def _is_setup_required(self) -> bool:
        """NAI / WebUI / ComfyUI 셋 다 미설정이면 Setup UI 강제."""
        stm = self.app_context.secure_token_manager
        has_any = bool(
            (stm.get_token("nai_token") or "").strip()
            or (stm.get_token("webui_url") or "").strip()
            or (stm.get_token("comfyui_url") or "").strip()
        )
        return not has_any

    def _save_verify_timestamp(self, key: str):
        """검증 성공 시 `NAIA_api_timestamps.json` 에 타임스탬프 기록 (데스크탑 UI와 공유)."""
        try:
            import os, json as _json
            data = {}
            if os.path.exists(self._SETUP_TIMESTAMP_FILE):
                try:
                    with open(self._SETUP_TIMESTAMP_FILE, "r", encoding="utf-8") as f:
                        data = _json.load(f) or {}
                except Exception:
                    data = {}
            data[f"{key}_last_verified"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with open(self._SETUP_TIMESTAMP_FILE, "w", encoding="utf-8") as f:
                _json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"🌐 Remote: 타임스탬프 저장 실패 — {e}")

    def _load_verify_timestamps(self) -> dict:
        """저장된 마지막 검증 타임스탬프 로드 (마스킹된 상태 표시용)."""
        try:
            import os, json as _json
            if os.path.exists(self._SETUP_TIMESTAMP_FILE):
                with open(self._SETUP_TIMESTAMP_FILE, "r", encoding="utf-8") as f:
                    return _json.load(f) or {}
        except Exception:
            pass
        return {}

    # --- NAI Anlas (viewer 좌하단 pill) ---

    def _anlas_payload(self) -> dict:
        """현재 캐시를 WS 메시지로 직렬화."""
        c = self._anlas_cache or {}
        return {
            "type": "anlas_update",
            "available": bool(c),
            "anlas": c.get("anlas", 0) if c else 0,
            "fetched_at": c.get("fetched_at", "") if c else "",
        }

    def _refresh_anlas_async(self):
        """NAI 토큰으로 Anlas 잔액 조회 — threading.Thread (Qt/asyncio 무관).

        Opus 여부와 상관없이 `fixed + purchased` 숫자를 그대로 노출.
        Opus 등급도 고해상도/특정 파라미터 조합에서 Anlas를 소모하므로 sentinel 처리 안 함.
        """
        if self._anlas_fetch_in_flight:
            return
        token = (self.app_context.secure_token_manager.get_token("nai_token") or "").strip()
        if not token:
            if self._anlas_cache is not None:
                self._anlas_cache = None
                self._broadcast_json(self._anlas_payload())
            return

        self._anlas_fetch_in_flight = True

        def _worker():
            try:
                value = api_verification.fetch_nai_anlas(token)
                if value is not None:
                    self._anlas_cache = {
                        "anlas": int(value),
                        "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    }
                    # Shared Mode 에서는 호스트 잔액이 타 사용자에게 노출되면 안 됨
                    if self._has_clients() and not self.shared_server_mode:
                        self._broadcast_json(self._anlas_payload())
            except Exception as e:
                print(f"🌐 Anlas fetch 실패 — {e}")
            finally:
                self._anlas_fetch_in_flight = False

        threading.Thread(target=_worker, daemon=True, name="NAIA-Anlas-Fetch").start()

    def _start_anlas_timer(self):
        """5분 주기 Anlas refresh 타이머 (Qt 메인 스레드에서 호출)."""
        if self._anlas_timer is None:
            self._anlas_timer = QTimer()
            self._anlas_timer.setInterval(self._anlas_refresh_interval_ms)
            self._anlas_timer.timeout.connect(self._refresh_anlas_async)
        if not self._anlas_timer.isActive():
            self._anlas_timer.start()

    def _stop_anlas_timer(self):
        if self._anlas_timer and self._anlas_timer.isActive():
            self._anlas_timer.stop()

    # --- 캐시 갱신 (Qt 메인 스레드에서 호출) ---

    def _update_cache_all(self):
        """모든 캐시를 갱신 (서버 시작 시 + WS 연결 시).

        api_status 는 per-ws 평가(setup_allowed 가 클라이언트 IP에 따라 다름)이므로
        캐시하지 않고 WS 초기화 시점에 `get_api_status(ws=ws)` 로 직접 생성한다.
        """
        self._cached_prompts = self.get_current_prompts()
        self._cached_params = self.get_generation_params()
        self._cached_options = {"type": "options", **self.get_options()}

    # --- 시그널 슬롯 래퍼 (lambda 대신 disconnect 가능) ---

    def _do_refresh_cache(self):
        """WS 연결 시 메인 스레드에서 캐시 갱신 + broadcast (프롬프트 제외 — 생성/랜덤 시에만 동기화)"""
        self._update_cache_all()
        if self._has_clients():
            if self._cached_options:
                self._broadcast_json(self._cached_options)
            if self._cached_params:
                self._broadcast_json(self._cached_params)

    def _on_option_toggled_slot(self, checked=None):
        """체크박스 toggled → 옵션 브로드캐스트"""
        self.broadcast_options()

    def _on_param_changed_slot(self, *args):
        """파라미터 위젯 변경 → 파라미터 브로드캐스트"""
        self._on_params_changed()

    # --- Qt 메인 스레드에서 실행되는 슬롯 ---

    def _inject_session_overrides(self, ws=None) -> dict | None:
        """Shared Mode: 요청 세션의 P.Eng/Cond 오버라이드를 app_context에 주입. params_override 반환."""
        if not (self.shared_server_mode and ws and self._ws_manager):
            return None
        session = self._ws_manager.sessions.get(ws)
        if not session:
            return None
        # P.Eng: 세션 값 없으면 1회 초기화 (Copy → 데스크톱 복사, 아니면 빈 값)
        if session.get("p_eng_override") is None:
            if getattr(self.app_context, 'shared_copy_peng', False):
                m = self._find_module("prompt_engineering")
                if m:
                    pp = {}
                    for label, cb in m.preprocessing_checkboxes.items():
                        pp[m.option_key_map.get(label, label)] = cb.isChecked()
                    session["p_eng_override"] = {
                        "pre_prompt": m.pre_textedit.toPlainText(),
                        "post_prompt": m.post_textedit.toPlainText(),
                        "auto_hide": m.auto_hide_textedit.toPlainText(),
                        "preprocessing_options": pp,
                    }
                else:
                    session["p_eng_override"] = {}
            else:
                session["p_eng_override"] = {}
        self.app_context.session_p_eng_override = session["p_eng_override"]
        # Cond: 동일 패턴
        if session.get("cond_override") is None:
            if getattr(self.app_context, 'shared_copy_cond', False):
                cm = self._find_module("conditional_prompt")
                if cm:
                    session["cond_override"] = {
                        "enabled": cm.enable_checkbox.isChecked() if hasattr(cm, 'enable_checkbox') else False,
                        "rules": cm.rules_textedit.toPlainText() if hasattr(cm, 'rules_textedit') else "",
                    }
                else:
                    session["cond_override"] = {}
            else:
                session["cond_override"] = {}
        self.app_context.session_cond_override = session["cond_override"]
        return session.get("params_override")

    def _get_session_settings_override(self, ws=None) -> dict | None:
        """Shared Mode: 세션의 옵션 오버라이드를 settings dict로 반환 (UI 미변경)."""
        if not (self.shared_server_mode and ws and self._ws_manager):
            return None
        session = self._ws_manager.sessions.get(ws)
        if not session:
            return None
        opts = session.get("options", {})
        if not opts:
            return None
        override = {}
        if "wildcard_standalone" in opts:
            override["wildcard_standalone"] = opts["wildcard_standalone"]
        return override if override else None

    def _get_session_negative(self, ws=None) -> str | None:
        """Shared Mode: 요청 세션의 negative prompt 반환."""
        if not (self.shared_server_mode and ws and self._ws_manager):
            return None
        session = self._ws_manager.sessions.get(ws)
        return session.get("negative_prompt") if session else None

    def _do_generate(self):
        """Generate 요청 처리. deque에서 준비된 데이터를 pop하여 실행."""
        if not self._pending_generate_requests:
            return
        req = self._pending_generate_requests.popleft()
        try:
            ws = req.get("ws")
            prompt = req.get("prompt", "")
            negative = req.get("negative", "")

            gc = self.app_context.main_window.generation_controller
            if gc.is_generating:
                print("🌐 Remote: 이미 생성 중 — 무시")
                self._send_json_to(ws, {"type": "status", "is_generating": True, "message": "already_generating"})
                return

            # Shared Mode: 세션 오버라이드 주입 (Qt main thread에서 실행 — 위젯 접근 안전)
            session_overrides = self._inject_session_overrides(ws)
            session_neg = self._get_session_negative(ws)
            # Generate 요청의 negative가 비어있으면 세션 값을 fallback으로 사용
            if not negative and session_neg is not None:
                negative = session_neg

            # seed_fixed가 아니면 → 랜덤 시드
            if session_overrides and "seed" in session_overrides:
                if session_overrides.get("seed_fixed") != "true":
                    session_overrides["seed"] = str(random.randint(0, 9999999999))

            # Non-Shared: 웹 프롬프트를 UI에 반영
            if (prompt or negative) and not self.shared_server_mode:
                self._syncing_prompt = True
                mw = self.app_context.main_window
                if prompt:
                    mw.main_prompt_textedit.setPlainText(prompt)
                if negative:
                    mw.negative_prompt_textedit.setPlainText(negative)
                self._syncing_prompt = False

            # Shared Mode: 웹 사용자의 프롬프트를 overrides에 주입 (데스크톱 UI 미변경)
            # session["params_override"] 참조를 직접 변경하면 이후 Random에도 오염되므로 복사
            if self.shared_server_mode and (prompt or negative):
                from core.wildcard_processor import split_tags_smart
                prompt_overrides = {}
                if prompt:
                    prompt_overrides["input"] = ', '.join(split_tags_smart(prompt))
                    prompt_overrides["_raw_input"] = prompt  # Load Prompt용 원본 보존
                if negative:
                    prompt_overrides["negative_prompt"] = ', '.join(split_tags_smart(negative))
                if session_overrides is None:
                    session_overrides = prompt_overrides
                else:
                    session_overrides = {**session_overrides, **prompt_overrides}

            # pending overrides에 source 기록 (on_prompt_generated에서 사용)
            if ws is not None:
                self._pending_overrides[ws] = {"source": "generate"}

            gc.execute_generation_pipeline(overrides=session_overrides, priority=0)
            self._broadcast_json({"type": "status", "is_generating": True})
            print("🌐 Remote: 생성 트리거됨")
        except Exception as e:
            if ws is not None:
                self._pending_overrides.pop(ws, None)
            print(f"🌐 Remote: 생성 트리거 실패 — {e}")

    def _send_result_enhance_error(self, ws, message: str):
        payload = {
            "type": "result_enhance_state",
            "running": False,
            "success": False,
            "message": message,
        }
        toast = {"type": "toast", "message": message, "level": "error"}
        if ws is not None:
            self._send_json_to(ws, payload)
            self._send_json_to(ws, toast)
        else:
            self._broadcast_json(payload)
            self._broadcast_json(toast)

    def _do_result_enhance(self, ws=None):
        """현재 데스크탑 ImageWindow 히스토리 항목에 NAI Enhance를 실행."""
        try:
            allowed, reason = self._result_enhance_gate(ws)
            if not allowed:
                self._send_result_enhance_error(ws, reason)
                return

            if self._remote_enhance_in_flight:
                self._send_result_enhance_error(ws, "Enhance is already running")
                return

            image_window = self._get_image_window_widget()
            if not image_window:
                self._send_result_enhance_error(ws, "ImageWindow is not ready")
                return

            item = getattr(image_window, "current_history_item", None)
            if not item or not getattr(item, "image", None):
                self._send_result_enhance_error(ws, "No image is selected")
                return

            current_mode = ""
            if hasattr(self.app_context, "get_api_mode"):
                current_mode = self.app_context.get_api_mode()
            else:
                current_mode = getattr(self.app_context, "current_api_mode", "")
            if current_mode != "NAI":
                self._send_result_enhance_error(ws, "Enhance is available in NAI mode only")
                return

            if not getattr(item, "generation_params", None):
                self._send_result_enhance_error(ws, "Generation parameters are unavailable")
                return

            if getattr(image_window, "_enhance_upscale", None) == 1.0:
                gen_ctrl = getattr(self.app_context, "generation_controller", None)
                if gen_ctrl and getattr(gen_ctrl, "is_generating", False):
                    self._send_result_enhance_error(ws, "Enhance is unavailable while generation is running")
                    return

            execute_enhance = getattr(image_window, "_execute_enhance", None)
            if not callable(execute_enhance):
                self._send_result_enhance_error(ws, "Enhance action is not available")
                return

            self._remote_enhance_in_flight = True
            self._broadcast_json({"type": "result_enhance_state", "running": True})
            execute_enhance()
            print("🌐 Remote: Enhance 트리거됨")
        except Exception as e:
            self._remote_enhance_in_flight = False
            message = f"Enhance request failed: {e}"
            self._send_result_enhance_error(ws, message)
            print(f"🌐 Remote: Enhance 트리거 실패 — {e}")

    def _do_image_action(self, action: str, image_bytes: bytes, label: str = ""):
        """Remote image action popup에서 전달된 이미지를 데스크탑 동작으로 라우팅."""
        action = (action or "").strip().lower()
        labels = {
            "img2img": "Img2Img",
            "inpaint": "Inpaint",
            "danbooru": "Danbooru tag analysis",
            "vibe": "Vibe Transfer",
        }
        if action not in labels:
            self._broadcast_json({"type": "toast", "message": "Unsupported image action", "level": "error"})
            return
        try:
            from PIL import Image
            with Image.open(io.BytesIO(image_bytes)) as opened:
                pil_image = opened.convert("RGBA").copy()

            main_window = getattr(self.app_context, "main_window", None)
            if not main_window:
                raise RuntimeError("Main window is not ready")

            if action == "img2img":
                handler = getattr(main_window, "activate_img2img_panel", None)
            elif action == "inpaint":
                handler = getattr(main_window, "activate_inpaint_mode", None)
            elif action == "danbooru":
                handler = getattr(main_window, "on_tag_interrogation_requested", None)
            else:
                handler = getattr(main_window, "activate_vibe_transfer", None)

            if not callable(handler):
                raise RuntimeError(f"{labels[action]} action is not available")

            handler(pil_image)
            if action == "vibe":
                state = self._read_vibe_transfer()
                if state:
                    self._broadcast_json(state)
            self._broadcast_json({
                "type": "toast",
                "message": f"{labels[action]} action requested",
                "level": "success",
            })
            print(f"🌐 Remote: image action requested — {action} ({label or 'Input Image'})")
        except Exception as e:
            message = f"{labels.get(action, 'Image')} action failed: {e}"
            self._broadcast_json({"type": "toast", "message": message, "level": "error"})
            print(f"🌐 Remote: image action failed — {action}: {e}")

    def _metadata_json_safe(self, value):
        """메타데이터 응답에 싣기 어려운 객체/바이트를 안전하게 축약."""
        if isinstance(value, bytes):
            return f"<bytes {len(value)}>"
        if isinstance(value, dict):
            cleaned = {}
            for key, item in value.items():
                key_text = str(key)
                key_lower = key_text.lower()
                if any(marker in key_lower for marker in ("token", "secret", "password", "authorization", "api_key")):
                    cleaned[key_text] = "<redacted>"
                    continue
                if key_text in {"image_bytes", "mask_bytes", "raw_bytes"}:
                    cleaned[key_text] = f"<bytes {len(item)}>" if isinstance(item, bytes) else "<binary>"
                    continue
                cleaned[key_text] = self._metadata_json_safe(item)
            return cleaned
        if isinstance(value, (list, tuple, set)):
            return [self._metadata_json_safe(item) for item in value]
        try:
            json.dumps(value)
            return value
        except Exception:
            return str(value)

    def _metadata_summary_from(self, meta: dict, gen_params: dict, image, webp_bytes: bytes) -> dict:
        summary = {
            "width": getattr(image, "width", ""),
            "height": getattr(image, "height", ""),
            "mode": getattr(image, "mode", ""),
            "size_kb": len(webp_bytes) // 1024 if webp_bytes else "",
        }
        if not isinstance(meta, dict):
            meta = {}
        if not isinstance(gen_params, dict):
            gen_params = {}

        prompt = meta.get("prompt") or gen_params.get("input") or gen_params.get("_raw_input") or ""
        negative = (
            meta.get("uc")
            or meta.get("negative")
            or meta.get("negative_prompt")
            or gen_params.get("negative_prompt")
            or ""
        )
        if prompt:
            summary["prompt"] = prompt
        if negative:
            summary["negative"] = negative

        if "characters" in meta:
            summary["characters"] = meta["characters"]
        elif "v4_prompt" in meta:
            try:
                v4_prompt = meta["v4_prompt"]
                if isinstance(v4_prompt, str):
                    v4_prompt = json.loads(v4_prompt)
                captions = v4_prompt.get("caption", {}).get("char_captions", [])
                chars = [caption.get("char_caption", "") for caption in captions if caption.get("char_caption")]
                if chars:
                    summary["characters"] = chars
            except Exception:
                pass

        param_source = meta.get("parameters") if isinstance(meta.get("parameters"), dict) else {}
        for key, aliases in {
            "seed": ("seed",),
            "steps": ("steps",),
            "sampler": ("sampler", "sampler_name"),
            "cfg_scale": ("cfg_scale", "scale", "cfg"),
            "model": ("model",),
        }.items():
            value = ""
            for alias in aliases:
                if alias in gen_params:
                    value = gen_params.get(alias)
                    break
                if alias in meta:
                    value = meta.get(alias)
                    break
                if alias in param_source:
                    value = param_source.get(alias)
                    break
            if value not in ("", None):
                summary[key] = value
        return summary

    def _build_result_metadata_payload(self, image, result: dict, webp_bytes: bytes) -> dict:
        gen_params = result.get("generation_params", {}) or {}
        prompt_context = result.get("prompt_context", {}) or {}
        api_metadata = result.get("api_metadata", {}) or {}
        extracted = {}
        try:
            from utils.image_info import ImageMetadataExtractor
            extracted = ImageMetadataExtractor.extract_metadata(image) or {}
        except Exception as e:
            print(f"🌐 Remote: 최신 이미지 메타데이터 추출 실패 — {e}")

        summary = self._metadata_summary_from(extracted, gen_params, image, webp_bytes)
        raw = {
            "image": {
                "width": getattr(image, "width", None),
                "height": getattr(image, "height", None),
                "mode": getattr(image, "mode", None),
                "format": getattr(image, "format", None),
                "size_kb": len(webp_bytes) // 1024 if webp_bytes else None,
            },
            "extracted_metadata": self._metadata_json_safe(extracted),
            "generation_params": self._metadata_json_safe(gen_params),
            "prompt_context": self._metadata_json_safe(prompt_context),
            "api_metadata": self._metadata_json_safe(api_metadata),
            "creation_timestamp": result.get("creation_timestamp", ""),
            "backend_type": result.get("backend_type", ""),
        }
        return {
            "source": "current",
            "label": "Current Result",
            "summary": self._metadata_json_safe(summary),
            "raw": raw,
            "has_metadata": bool(extracted or gen_params or prompt_context or api_metadata),
        }

    def _build_input_metadata_payload(self, image, image_bytes: bytes, label: str = "Input Image", mime_type: str = "") -> dict:
        extracted = {}
        try:
            from utils.image_info import ImageMetadataExtractor
            extracted = ImageMetadataExtractor.extract_metadata(image) or {}
        except Exception as e:
            print(f"🌐 Remote: 입력 이미지 메타데이터 추출 실패 — {e}")

        summary = self._metadata_summary_from(extracted, {}, image, image_bytes)
        raw = {
            "image": {
                "width": getattr(image, "width", None),
                "height": getattr(image, "height", None),
                "mode": getattr(image, "mode", None),
                "format": getattr(image, "format", None),
                "mime_type": mime_type,
                "size_kb": len(image_bytes) // 1024 if image_bytes else None,
            },
            "extracted_metadata": self._metadata_json_safe(extracted),
        }
        return {
            "source": "input",
            "label": label or "Input Image",
            "summary": self._metadata_json_safe(summary),
            "raw": raw,
            "has_metadata": bool(extracted),
        }

    def _source_row_available(self, source_row) -> bool:
        if source_row is None:
            return False
        try:
            return not bool(source_row.empty)
        except Exception:
            return True

    def _current_api_mode(self) -> str:
        try:
            if hasattr(self.app_context, "get_api_mode"):
                return self.app_context.get_api_mode()
            return str(getattr(self.app_context, "current_api_mode", "") or "")
        except Exception:
            return ""

    def _build_current_result_asset_payload(self) -> dict:
        """Context menu가 사용할 현재 Result의 얇은 액션 계약."""
        image_window = self._get_image_window_widget()
        item = getattr(image_window, "current_history_item", None) if image_window else None
        has_item_image = bool(item and getattr(item, "image", None))
        has_latest_image = self.latest_webp is not None
        metadata_payload = self.latest_metadata_payload if isinstance(self.latest_metadata_payload, dict) else {}
        raw = metadata_payload.get("raw", {}) if isinstance(metadata_payload, dict) else {}
        if not isinstance(raw, dict):
            raw = {}
        summary = metadata_payload.get("summary", {}) if isinstance(metadata_payload, dict) else {}
        if not isinstance(summary, dict):
            summary = {}

        generation_params = getattr(item, "generation_params", None) if item else None
        if not generation_params:
            generation_params = raw.get("generation_params", {})
        prompt_context = getattr(item, "prompt_context", None) if item else None
        if not prompt_context:
            prompt_context = raw.get("prompt_context", {})
        source_row = getattr(item, "source_row", None) if item else None

        filepath = str(getattr(item, "filepath", "") or "") if item else ""
        has_file = bool(filepath and Path(filepath).is_file())
        has_generation_params = bool(generation_params)
        has_source_row = self._source_row_available(source_row)
        has_prompt = bool(
            (isinstance(prompt_context, dict) and (prompt_context.get("main_prompt") or prompt_context.get("final_prompt")))
            or (isinstance(generation_params, dict) and generation_params.get("input"))
            or summary.get("prompt")
        )
        mode = self._current_api_mode()
        has_image = has_item_image or has_latest_image

        return {
            "id": "current",
            "source": "current",
            "path": "",
            "file_path": filepath if has_file else "",
            "label": "Current Result",
            "image_url": "/api/latest-image" if has_latest_image else "",
            "metadata_url": "/api/result/metadata",
            "has_image": has_image,
            "has_metadata": bool(metadata_payload),
            "capabilities": {
                "load_prompt": bool(has_prompt),
                "reroll": bool(has_source_row),
                "queue": bool(has_generation_params),
                "restore_params": bool(has_generation_params),
                "metadata": bool(metadata_payload),
                "paste_image": True,
                "open_file": has_file,
                "save_image": bool(has_item_image and not has_file),
                "copy_png": has_image,
                "copy_webp": has_image,
                "upscale_nai": bool(has_image and mode == "NAI"),
                "inpaint": has_item_image,
                "character_reference": has_item_image,
                "remote_event": has_source_row,
                "delete": False,
            },
        }

    def _build_saved_result_asset_payload(self, rel_path: str) -> dict | None:
        """저장 폴더 이미지의 ResultAsset 계약. HistoryItem 정보가 없으면 보수적으로 제한."""
        target = self._validate_viewer_path(rel_path)
        if not target:
            return None
        try:
            stat = target.stat()
            save_dir = self._get_viewer_save_dir().resolve()
            normalized_path = target.relative_to(save_dir).as_posix()
        except Exception:
            stat = None
            normalized_path = rel_path.replace("\\", "/")

        return {
            "id": f"saved:{normalized_path}",
            "source": "saved",
            "path": normalized_path,
            "file_path": str(target),
            "label": target.name,
            "image_url": "",
            "metadata_url": "",
            "has_image": True,
            "has_metadata": True,
            "size_bytes": stat.st_size if stat else None,
            "mtime": stat.st_mtime if stat else None,
            "capabilities": {
                "load_prompt": False,
                "reroll": False,
                "queue": False,
                "restore_params": False,
                "metadata": True,
                "paste_image": True,
                "open_file": True,
                "save_image": False,
                "copy_png": True,
                "copy_webp": True,
                "upscale_nai": self._current_api_mode() == "NAI",
                "inpaint": False,
                "character_reference": False,
                "remote_event": False,
                "delete": False,
            },
        }

    def _do_random(self):
        """Random 요청 처리. deque에서 준비된 데이터를 pop하여 실행."""
        if not self._pending_random_requests:
            return
        req = self._pending_random_requests.popleft()
        try:
            ws = req.get("ws")
            source_row = req.get("source_row")  # shared mode: 미리 선택됨 / non-shared: None
            active_ratings = req.get("active_ratings", set(self._active_ratings))

            # Shared Mode: 세션 오버라이드 주입 (Qt main thread — 위젯 접근 안전)
            params_override = self._inject_session_overrides(ws)
            session_neg = self._get_session_negative(ws)
            settings_override = self._get_session_settings_override(ws)

            # WS별 pending 저장 (on_prompt_generated에서 auto-generate용)
            mw = self.app_context.main_window
            auto_gen = mw.generation_checkboxes.get("자동 생성")
            auto_gen_checked = bool(auto_gen and auto_gen.isChecked())

            # ComfyUI sync 요청 처리 — ws=None 이지만 request_id로 격리
            comfyui_request_id = req.get("comfyui_request_id")
            force_skip = bool(req.get("force_naia_skip_generate", False))
            respect_autogen = bool(req.get("respect_naia_autogen", True))
            comfyui_peng_override = req.get("peng_override")  # dict or None

            if comfyui_request_id:
                will_naia_generate = (
                    auto_gen_checked and respect_autogen and not force_skip
                )
                override_key = ("comfyui", comfyui_request_id)
                pending_entry = {
                    "params": params_override,
                    "negative": session_neg,
                    "settings_override": settings_override,
                    "source": "comfyui_random",
                    "auto_generate": will_naia_generate,
                    "comfyui_request_id": comfyui_request_id,
                }

                # P.Eng per-request override 주입
                # NAIA 메인 UI 불변; prompt_engineering_module.py:1414 consumer가 이 dict 소비.
                # 이미지 생성 경로는 generation_controller가 알아서 리셋하지만,
                # force_skip=true + 자동생성 OFF 경로는 리셋 안 되므로 on_prompt_generated에서
                # id 비교 후 능동 reset.
                if comfyui_peng_override is not None and isinstance(comfyui_peng_override, dict):
                    self.app_context.session_p_eng_override = comfyui_peng_override
                    pending_entry["_peng_override_ref"] = comfyui_peng_override

                self._pending_overrides[override_key] = pending_entry
            elif ws:
                self._pending_overrides[ws] = {
                    "params": params_override,
                    "negative": session_neg,
                    "settings_override": settings_override,
                    "source": "random",
                    "auto_generate": auto_gen_checked,
                }

            # Non-shared + tag filter: 아직 row를 안 뽑았으면 여기서 처리
            if source_row is None and not self.shared_server_mode and ws and self._ws_manager:
                session = self._ws_manager.sessions.get(ws)
                tag_filter = session.get("tag_filter") if session else None
                if tag_filter and tag_filter.get("ids"):
                    source_row = self._pick_from_tag_filter(tag_filter, active_ratings)
                    if source_row is None:
                        self._send_json_to(ws, {"type": "random_failed",
                                                "message": "Tag filter: no matching rows",
                                                "level": "error"})
                        return

            mw.trigger_random_prompt(settings_override=settings_override,
                                     active_ratings=active_ratings,
                                     source_row_override=source_row)
            print("🌐 Remote: 랜덤 프롬프트 생성됨")
        except Exception as e:
            if ws is not None:
                self._pending_overrides.pop(ws, None)
                self._send_json_to(ws, {"type": "random_failed",
                                        "message": f"Random failed: {e}",
                                        "level": "error"})
            print(f"🌐 Remote: 랜덤 프롬프트 생성 실패 — {e}")

    # --- Tag Filter / Session ID Vector ---

    def _pick_from_session(self, ws) -> object:
        """세션의 eligible_ids에서 랜덤 1개 row 반환. asyncio.to_thread에서 호출."""
        if not self._ws_manager:
            return None
        session = self._ws_manager.sessions.get(ws)
        if not session:
            return None
        eligible_ids = session.get("eligible_ids")
        if eligible_ids is not None:
            return self._pick_from_snapshot(set(), filter_ids=eligible_ids)
        # eligible_ids 미계산 시 ratings 기반 fallback
        ratings = session.get("active_ratings") or self._active_ratings
        tag_filter = session.get("tag_filter")
        filter_ids = tag_filter["ids"] if (tag_filter and tag_filter.get("ids")) else None
        return self._pick_from_snapshot(ratings, filter_ids=filter_ids)

    def _pick_from_snapshot(self, active_ratings: set, filter_ids: set = None):
        """snapshot에서 rating + (선택적) ID 필터 적용하여 랜덤 1개 반환.
        search_results를 pop하지 않으므로 shared mode에서 안전."""
        mw = self.app_context.main_window
        snapshot = getattr(mw, '_search_results_snapshot', None)
        if snapshot is None or snapshot.empty:
            snapshot = mw.search_results.get_dataframe()
        if snapshot.empty:
            return None

        mask = snapshot["rating"].isin(active_ratings) if (active_ratings and 'rating' in snapshot.columns) else None
        if filter_ids is not None:
            id_mask = snapshot["id"].isin(filter_ids)
            mask = (mask & id_mask) if mask is not None else id_mask
        if mask is not None:
            eligible = snapshot[mask]
        else:
            eligible = snapshot
        if eligible.empty:
            return None
        return eligible.sample(n=1).iloc[0].copy()

    def _pick_from_tag_filter(self, tag_filter: dict, active_ratings: set):
        """snapshot에서 tag_filter에 매칭되는 row 중 rating 필터 적용하여 랜덤 1개 반환"""
        return self._pick_from_snapshot(active_ratings, filter_ids=tag_filter["ids"])

    def _do_tag_filter_search(self, tags: list):
        """snapshot에서 태그 AND 검색, 매칭 ID를 반환"""
        import pandas as pd
        mw = self.app_context.main_window
        snapshot = getattr(mw, '_search_results_snapshot', None)
        if snapshot is None or snapshot.empty:
            snapshot = mw.search_results.get_dataframe()
        if snapshot.empty:
            return {"type": "tag_filter_result", "count": 0, "tags": tags, "rating_counts": {r: 0 for r in 'gsqe'}}

        mask = pd.Series(True, index=snapshot.index)
        for tag in tags:
            raw = tag.strip()
            negate = raw.startswith("-")
            tag_clean = raw.lstrip("-").strip().replace("_", " ")
            if not tag_clean:
                continue
            hit = snapshot["general"].str.contains(tag_clean, case=False, na=False, regex=False)
            mask &= ~hit if negate else hit

        matched = snapshot[mask]
        matched_ids = set(matched["id"].tolist())

        rating_counts = {r: 0 for r in 'gsqe'}
        if 'rating' in matched.columns:
            vc = matched['rating'].value_counts()
            for r in 'gsqe':
                rating_counts[r] = int(vc.get(r, 0))

        return {
            "type": "tag_filter_result",
            "count": len(matched_ids),
            "tags": tags,
            "rating_counts": rating_counts,
            "_ids": matched_ids,  # 내부용, WS 응답에서 제거
        }

    # --- 옵션 동기화 (Qt 메인 스레드에서 실행) ---

    def _do_set_option(self, key: str, checked: bool):
        """웹에서 토글한 옵션을 메인 앱 체크박스에 반영"""
        try:
            # auto_save: image_window 체크박스 (OPTION_KEYS 외)
            if key == "auto_save":
                auto_save_checkbox = self._get_auto_save_checkbox()
                if auto_save_checkbox and auto_save_checkbox.isChecked() != checked:
                    self._syncing_option = True
                    auto_save_checkbox.setChecked(checked)
                    self._syncing_option = False
                    print(f"🌐 Remote: 자동 저장 → {checked}")
                return

            label = self.OPTION_KEYS.get(key)
            if not label:
                return
            mw = self.app_context.main_window
            cb = mw.generation_checkboxes.get(label)
            if cb and cb.isChecked() != checked:
                self._syncing_option = True
                cb.setChecked(checked)
                self._syncing_option = False
                print(f"🌐 Remote: {label} → {checked}")
        except Exception as e:
            self._syncing_option = False
            print(f"🌐 Remote: 옵션 설정 실패 — {e}")

    # --- API 모드 변경 (Qt 메인 스레드에서 실행) ---

    def _do_set_mode(self, mode: str):
        """웹에서 선택한 API 모드를 메인 앱에 반영 — 검증 → 스텔스 → toggle_search_mode"""
        valid = ("NAI", "WEBUI", "COMFYUI")
        if mode not in valid:
            self._broadcast_json({"type": "mode_result", "success": False,
                                  "mode": mode, "message": f"Unknown mode: {mode}"})
            return
        try:
            # Shared Mode + Cloudflared: NAI 차단
            if self.shared_server_mode and mode == "NAI" and self._is_cloudflared_active():
                self._broadcast_json({"type": "mode_result", "success": False,
                                      "mode": mode, "message": "NAI mode is not available in Shared Server Mode (Cloudflared)"})
                return

            current = self.app_context.get_api_mode()
            if current == mode:
                self._broadcast_json({"type": "mode_result", "success": True,
                                      "mode": mode, "message": f"{mode} already active"})
                return

            # 1) 사전 검증 — 실패 시 toggle_search_mode 호출하지 않음
            ok, msg = self._validate_api_connection(mode)
            if not ok:
                self._broadcast_json({"type": "mode_result", "success": False,
                                      "mode": mode, "message": msg})
                return

            # 2) 스텔스 모드로 toggle_search_mode 호출 (QMessageBox/탭 열기 억제)
            mw = self.app_context.main_window
            self.app_context.stealth_mode = True
            try:
                mw.toggle_search_mode(mode)
            finally:
                self.app_context.stealth_mode = False

            # 3) 실제 전환 확인
            new_mode = self.app_context.get_api_mode()
            if new_mode == mode:
                self._broadcast_json({"type": "mode_result", "success": True,
                                      "mode": mode, "message": f"{mode} mode active"})
                print(f"🌐 Remote: API 모드 → {mode}")
            else:
                self._broadcast_json({"type": "mode_result", "success": False,
                                      "mode": mode, "message": f"{mode} switch failed"})
        except Exception as e:
            self.app_context.stealth_mode = False
            self._broadcast_json({"type": "mode_result", "success": False,
                                  "mode": mode, "message": str(e)})
            print(f"🌐 Remote: 모드 변경 실패 — {e}")

    def _validate_api_connection(self, mode: str) -> tuple:
        """API 연결 테스트 (팝업 Test 버튼용). (success: bool, message: str)"""
        mw = self.app_context.main_window
        stm = self.app_context.secure_token_manager

        if mode == "NAI":
            token = stm.get_token("nai_token")
            return (True, "Token configured") if token else (False, "Token not configured")

        elif mode == "WEBUI":
            url = stm.get_token("webui_url")
            if not url:
                return False, "URL not configured"
            validated = mw.test_webui(url)
            if validated:
                return True, f"Connected — {validated}"
            return False, "Connection failed"

        elif mode == "COMFYUI":
            url = stm.get_token("comfyui_url")
            if not url:
                return False, "URL not configured"
            validated = mw.test_comfyui(url)
            if validated:
                return True, f"Connected — {validated}"
            return False, "Connection failed"

        return False, "Unknown mode"

    # --- API 설정 (Qt 메인 스레드에서 실행) ---

    _LOCAL_PATTERNS = ("127.0.0.1", "localhost", "192.168.", "10.", "172.16.",
                       "172.17.", "172.18.", "172.19.", "172.20.", "172.21.",
                       "172.22.", "172.23.", "172.24.", "172.25.", "172.26.",
                       "172.27.", "172.28.", "172.29.", "172.30.", "172.31.")

    def _is_local_url(self, url: str) -> bool:
        """로컬/LAN 주소 여부 확인"""
        stripped = url.replace("http://", "").replace("https://", "").split("/")[0].split(":")[0]
        return any(stripped.startswith(p) for p in self._LOCAL_PATTERNS)

    def _do_set_api_url(self, mode: str, url: str):
        """웹에서 입력한 API URL을 저장 (legacy 경로 — 신규 UI 는 verify_webui/verify_comfyui 사용).

        Setup 모달 경로는 `_setup_gate()`(loopback 클라이언트)로 토큰 저장을 보호하므로
        URL 자체의 LAN 체크는 과잉. Cloudflare 터널처럼 외부 주소를 쓰는 케이스를 지원.
        """
        try:
            url = url.strip()
            if not url:
                self._broadcast_json({"type": "api_config_result", "success": False,
                                      "message": "URL is empty"})
                return

            stm = self.app_context.secure_token_manager
            key = "webui_url" if mode == "WEBUI" else "comfyui_url"
            # http:// 프리픽스 보장
            if not url.startswith("http"):
                url = f"http://{url}"
            stm.save_token(key, url)
            self._broadcast_json({"type": "api_config_result", "success": True,
                                  "message": f"URL saved: {url}"})
            # 상태 갱신 전송
            self._broadcast_api_status()
            print(f"🌐 Remote: {mode} URL → {url}")
        except Exception as e:
            self._broadcast_json({"type": "api_config_result", "success": False,
                                  "message": str(e)})

    def _do_test_api(self, mode: str):
        """API 연결 테스트 후 결과 브로드캐스트"""
        ok, msg = self._validate_api_connection(mode)
        self._broadcast_json({"type": "api_test_result", "mode": mode,
                              "success": ok, "message": msg})
        self._broadcast_api_status()

    def get_api_status(self, ws=None) -> dict:
        """각 모드의 설정 상태 + Setup 게이트 상태 반환.

        `ws` 주어지면 해당 클라이언트 기준 `setup_allowed`/`setup_block_reason` 포함.
        없으면 공통 필드만 (브로드캐스트 캐시용).
        """
        stm = self.app_context.secure_token_manager
        timestamps = self._load_verify_timestamps()
        nai_token = (stm.get_token("nai_token") or "").strip()
        # 데스크탑 API 관리 창과 동일 마스킹 규칙: 앞 7자만 노출
        nai_preview = nai_token[:7] if len(nai_token) >= 7 else nai_token
        payload = {
            "type": "api_status",
            "nai_configured": bool(nai_token),
            "nai_token_preview": nai_preview,
            "webui_url": stm.get_token("webui_url") or "",
            "comfyui_url": stm.get_token("comfyui_url") or "",
            "comfyui_default_model": stm.get_token("comfyui_default_model") or "",
            "comfyui_sampling_mode": stm.get_token("comfyui_sampling_mode") or "",
            "active_mode": self.app_context.get_api_mode() if hasattr(self.app_context, "get_api_mode") else "",
            # Shared Server Mode 에서는 웹 사용자에게 Setup 모달을 강제하지 않음 (호스트 책임)
            "setup_required": (not self.shared_server_mode) and self._is_setup_required(),
            "last_verified": {
                "nai": timestamps.get("nai_token_last_verified", ""),
                "webui": timestamps.get("webui_url_last_verified", ""),
                "comfyui": timestamps.get("comfyui_url_last_verified", ""),
            },
        }
        cloudflared = self._get_cloudflared_status()
        payload["cloudflared_active"] = cloudflared["active"]
        payload["cloudflared_url"] = cloudflared["url"]
        payload["cloudflared_status_text"] = cloudflared["status_text"]
        if ws is not None:
            allowed, reason = self._setup_gate(ws)
            payload["setup_allowed"] = allowed
            payload["setup_block_reason"] = reason
            cf_allowed, cf_reason = self._cloudflared_gate(ws)
            payload["cloudflared_control_allowed"] = cf_allowed
            payload["cloudflared_control_block_reason"] = cf_reason
        return payload

    def _broadcast_api_status(self):
        """api_status 를 per-client 송신 (`setup_allowed` 가 IP별로 다름)."""
        if not self._has_clients():
            return
        common = self.get_api_status(ws=None)
        for ws in list(self._ws_manager.active_connections):
            payload = dict(common)
            allowed, reason = self._setup_gate(ws)
            payload["setup_allowed"] = allowed
            payload["setup_block_reason"] = reason
            cf_allowed, cf_reason = self._cloudflared_gate(ws)
            payload["cloudflared_control_allowed"] = cf_allowed
            payload["cloudflared_control_block_reason"] = cf_reason
            self._send_json_to(ws, payload)

    def get_desktop_window_state(self, ws=None) -> dict:
        """메인 데스크탑 창 visibility + 제어 가능 여부."""
        mw = getattr(self.app_context, "main_window", None)
        payload = {
            "type": "desktop_window_state",
            "visible": bool(mw and mw.isVisible() and not mw.isHidden()),
        }
        if ws is not None:
            allowed, reason = self._desktop_window_gate(ws)
            payload["control_allowed"] = allowed
            payload["control_block_reason"] = reason
        return payload

    def _broadcast_desktop_window_state(self):
        if not self._has_clients():
            return
        self._broadcast_json(self.get_desktop_window_state())

    def on_desktop_window_visibility_changed(self, _data: dict):
        self._broadcast_desktop_window_state()

    def on_cloudflared_status_changed(self, _data: dict):
        self._broadcast_api_status()

    def _do_set_desktop_visibility(self, visible: bool):
        mw = getattr(self.app_context, "main_window", None)
        if not mw:
            return
        if hasattr(mw, "set_web_session_window_visible"):
            mw.set_web_session_window_visible(bool(visible))
        elif visible:
            mw.show()
            mw.raise_()
            mw.activateWindow()
        else:
            mw.hide()

    def _do_set_cloudflared_enabled(self, enabled: bool):
        settings_widget = self._get_settings_widget()
        if not settings_widget:
            return

        checkbox = getattr(settings_widget, "cloudflared_checkbox", None)
        if not checkbox:
            return

        if checkbox.isChecked() != bool(enabled):
            checkbox.setChecked(bool(enabled))
        else:
            self._broadcast_api_status()

    def on_api_mode_changed(self, data: dict):
        """api_mode_changed 이벤트 → 웹 클라이언트에 브로드캐스트"""
        new_mode = data.get("new_mode", "")
        # NAI 전환 시 Shared Mode 자동 해제
        if new_mode == "NAI" and self.shared_server_mode:
            self.shared_server_mode = False
            print("🌐 Remote: NAI 모드 전환 — Shared Server Mode 자동 해제")
        # NAI 모드 진입/이탈에 맞춰 Anlas 타이머 제어
        if new_mode == "NAI":
            self._start_anlas_timer()
            self._refresh_anlas_async()
        else:
            self._stop_anlas_timer()
        if not self._has_clients():
            return
        self._broadcast_json({"type": "mode", "mode": new_mode})
        # 모드 변경 시 파라미터도 갱신 (모드별 옵션이 다르므로)
        self._broadcast_params()

    def get_options(self) -> dict:
        """현재 옵션 상태 반환"""
        try:
            mw = self.app_context.main_window
            opts = {
                key: mw.generation_checkboxes[label].isChecked()
                for key, label in self.OPTION_KEYS.items()
                if label in mw.generation_checkboxes
            }
            # auto_save: image_window의 체크박스
            auto_save_checkbox = self._get_auto_save_checkbox()
            if auto_save_checkbox:
                opts["auto_save"] = auto_save_checkbox.isChecked()
            return opts
        except Exception:
            return {}

    def broadcast_options(self):
        """현재 옵션 상태를 모든 WS 클라이언트에 전송 + 캐시 갱신"""
        if self._syncing_option:
            return
        opts = self.get_options()
        if opts:
            self._cached_options = {"type": "options", **opts}
            if self._has_clients():
                self._broadcast_json(self._cached_options)

    # --- 프롬프트 동기화 (Qt 메인 스레드에서 실행) ---

    def _get_character_prompt_for_tokens(self) -> str:
        """데스크탑 토큰 라벨과 같은 기준으로 NAI 캐릭터 프롬프트를 읽는다."""
        try:
            if self.app_context.get_api_mode() != "NAI":
                return ""
            character_module = self._find_module("character")
            if not character_module:
                return ""
            activate_checkbox = getattr(character_module, "activate_checkbox", None)
            if activate_checkbox is not None and not activate_checkbox.isChecked():
                return ""
            processed_data = getattr(character_module, "modifiable_clone", None)
            if not isinstance(processed_data, dict):
                processed_data = getattr(character_module, "last_processed_data", {}) or {}
            characters = processed_data.get("characters", [])
            return " ".join(str(char) for char in characters if char)
        except Exception as e:
            print(f"🌐 Remote: 캐릭터 토큰 프롬프트 읽기 실패 — {e}")
            return ""

    def _build_prompt_token_payload(
        self,
        main_prompt: str,
        negative_prompt: str = "",
        mode: Optional[str] = None,
    ) -> dict:
        """Web Shell에 전달할 기존 NAIA 방식의 프롬프트 토큰 표시값을 만든다."""
        try:
            from utils.token_calculator import get_token_calculator

            calculator = get_token_calculator()
            if not calculator.available:
                return {
                    "prompt_token_label": "Estimated Tokens : N/A (tiktoken not available)",
                    "prompt_token_counts": {"main": 0, "character": 0, "total": 0},
                }
            current_mode = mode or self.app_context.get_api_mode()
            character_prompt = self._get_character_prompt_for_tokens() if current_mode == "NAI" else ""
            token_counts = calculator.count_prompt_tokens(main_prompt or "", character_prompt, current_mode)
            payload = {
                "prompt_token_label": calculator.format_token_label(token_counts, current_mode),
                "prompt_token_counts": token_counts,
            }
            if negative_prompt is not None:
                payload["negative_token_count"] = calculator.count_tokens(
                    negative_prompt or "",
                    current_mode=current_mode,
                )
            return payload
        except Exception as e:
            print(f"🌐 Remote: 프롬프트 토큰 계산 실패 — {e}")
            return {"prompt_token_label": "Estimated Tokens : Error"}

    def _do_set_prompt(self, prompt: str, negative: str):
        """웹에서 편집한 프롬프트를 메인 앱에 반영"""
        try:
            self._syncing_prompt = True
            mw = self.app_context.main_window
            if not self.shared_server_mode:
                mw.main_prompt_textedit.setPlainText(prompt)
                mw.negative_prompt_textedit.setPlainText(negative)
            # Shared Mode: 데스크톱 UI에 쓰지 않음 (세션별 격리)
            self._syncing_prompt = False
            if self._has_clients():
                self._broadcast_json({
                    "type": "prompt_tokens",
                    **self._build_prompt_token_payload(prompt, negative),
                })
        except Exception as e:
            self._syncing_prompt = False
            print(f"🌐 Remote: 프롬프트 설정 실패 — {e}")

    def get_current_prompts(self) -> dict:
        """현재 프롬프트 + 파라미터 상태 반환"""
        try:
            mw = self.app_context.main_window
            prompt = mw.main_prompt_textedit.toPlainText()
            negative = mw.negative_prompt_textedit.toPlainText()
            params = mw.get_main_parameters()
            return {
                "type": "prompt_sync",
                "prompt": prompt,
                "negative_prompt": negative,
                "model": params.get("model", ""),
                "steps": params.get("steps", ""),
                "cfg_scale": params.get("cfg_scale", ""),
                "sampler": params.get("sampler", ""),
                "width": params.get("width", ""),
                "height": params.get("height", ""),
                "seed": params.get("seed", ""),
                **self._build_prompt_token_payload(prompt, negative),
            }
        except Exception:
            return {}

    def _on_prompt_text_changed(self):
        """메인 UI 프롬프트 변경 시 디바운스 후 웹에 전송"""
        if self._syncing_prompt:
            return
        if self._prompt_debounce_timer is None:
            self._prompt_debounce_timer = QTimer()
            self._prompt_debounce_timer.setSingleShot(True)
            self._prompt_debounce_timer.timeout.connect(self._broadcast_prompts)
        self._prompt_debounce_timer.start(500)

    def _broadcast_prompts(self):
        """현재 프롬프트 캐시 갱신 + Non-Shared 모드에서 웹 클라이언트에 동기화"""
        data = self.get_current_prompts()
        if data:
            self._cached_prompts = data
            # Non-Shared: 데스크톱 프롬프트 변경을 웹에 실시간 동기화
            # Shared: 각 클라이언트가 독립 관리하므로 broadcast 안 함
            if not self.shared_server_mode and self._has_clients():
                self._broadcast_json(data)

    # --- Viewer: 디스크 이미지 스캔/썸네일 ---

    def _get_viewer_save_dir(self) -> 'Path':
        """Viewer 기준 저장 루트 반환.

        기본값은 현재 세션 저장 디렉토리다. timestamp 폴더를 사용하는 기본 동작에서는
        이전 세션 이미지가 섞이면 안 되므로 `get_save_directory()`를 우선 사용한다.
        타임스탬프 폴더를 쓰지 않는 구성에서만 base path를 그대로 사용한다.
        """
        from pathlib import Path
        image_crud = self.app_context.image_crud_controller
        current_save_dir = Path(image_crud.get_save_directory())

        if getattr(image_crud, "_use_timestamp_folder", True):
            return current_save_dir

        base_path = getattr(image_crud, "_base_save_path", None)
        if base_path is not None:
            return Path(base_path)

        return current_save_dir

    def _scan_save_folder(self) -> list:
        """저장 폴더 재귀 스캔 → mtime 내림차순 리스트. 2초 캐시."""
        import os, time
        from pathlib import Path
        from datetime import datetime

        save_dir = self._get_viewer_save_dir()
        save_dir_str = str(save_dir)
        now = time.time()

        # 캐시 유효 (같은 디렉터리 + 2초 이내)
        if (self._viewer_cache_dir == save_dir_str
                and now - self._viewer_cache_time < 2.0
                and self._viewer_cache):
            return self._viewer_cache

        if not save_dir.exists():
            self._viewer_cache = []
            self._viewer_cache_time = now
            self._viewer_cache_dir = save_dir_str
            return []

        IMAGE_EXTS = {'.png', '.webp', '.jpg', '.jpeg'}
        entries = []

        def _scan_recursive(folder: Path):
            try:
                for entry in os.scandir(str(folder)):
                    if entry.is_dir(follow_symlinks=False):
                        # .thumbnails 폴더 제외
                        if entry.name == '.thumbnails':
                            continue
                        _scan_recursive(Path(entry.path))
                    elif entry.is_file(follow_symlinks=False):
                        ext = os.path.splitext(entry.name)[1].lower()
                        if ext in IMAGE_EXTS:
                            stat = entry.stat()
                            rel = os.path.relpath(entry.path, save_dir_str).replace('\\', '/')
                            entries.append({
                                "rel_path": rel,
                                "filename": entry.name,
                                "size_bytes": stat.st_size,
                                "mtime": stat.st_mtime,
                                "mtime_iso": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                            })
            except OSError:
                pass

        _scan_recursive(save_dir)
        entries.sort(key=lambda e: e["mtime"], reverse=True)

        self._viewer_cache = entries
        self._viewer_cache_time = now
        self._viewer_cache_dir = save_dir_str
        return entries

    def _invalidate_viewer_cache(self):
        """viewer 캐시 무효화 (새 이미지 저장 시)"""
        self._viewer_cache_time = 0

    def _validate_viewer_path(self, rel_path: str) -> 'Path | None':
        """상대 경로를 저장 폴더 기준으로 검증 (경로 탈출 방지)"""
        from pathlib import Path
        save_dir = self._get_viewer_save_dir().resolve()
        target = (save_dir / rel_path).resolve()
        try:
            target.relative_to(save_dir)
        except ValueError:
            print(f"🌐 Viewer: 경로 탈출 시도 차단 — {rel_path}")
            return None
        if not target.is_file():
            return None
        IMAGE_EXTS = {'.png', '.webp', '.jpg', '.jpeg'}
        if target.suffix.lower() not in IMAGE_EXTS:
            return None
        return target

    def _get_or_create_thumbnail(self, abs_path: 'Path', max_side: int = 0) -> bytes:
        """이미지 썸네일 반환 (디스크 캐시). max_side=0이면 원본의 절반. blocking."""
        from pathlib import Path
        from PIL import Image
        import io

        save_dir = self._get_viewer_save_dir()
        rel = abs_path.relative_to(save_dir.resolve())
        thumb_dir = save_dir / ".thumbnails" / rel.parent
        thumb_path = thumb_dir / (rel.stem + ".thumb.webp")

        # 캐시 유효성 확인 (원본 mtime vs 썸네일 mtime)
        if thumb_path.exists():
            orig_mtime = abs_path.stat().st_mtime
            thumb_mtime = thumb_path.stat().st_mtime
            if thumb_mtime >= orig_mtime:
                return thumb_path.read_bytes()

        # 썸네일 생성
        try:
            img = Image.open(str(abs_path))
            # max_side=0: 원본의 절반 (최소 256px)
            if max_side <= 0:
                max_side = max(img.width, img.height) // 2
                max_side = max(max_side, 256)
            img.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format='WEBP', quality=85, method=4)
            thumb_bytes = buf.getvalue()

            # 디스크 캐시 저장
            thumb_dir.mkdir(parents=True, exist_ok=True)
            thumb_path.write_bytes(thumb_bytes)
            return thumb_bytes
        except Exception as e:
            print(f"🌐 Viewer: 썸네일 생성 실패 — {abs_path}: {e}")
            return b''

    def _on_image_saved(self, data: dict):
        """image_saved 이벤트 핸들러 → viewer_new_image WS broadcast"""
        self._invalidate_viewer_cache()
        if not self._has_clients():
            return
        filepath = data.get("filepath", "")
        if filepath:
            import os
            from datetime import datetime
            viewer_root = str(self._get_viewer_save_dir())
            rel = os.path.relpath(filepath, viewer_root).replace('\\', '/')
            filename = os.path.basename(filepath)
            try:
                mtime = os.path.getmtime(filepath)
                mtime_iso = datetime.fromtimestamp(mtime).isoformat()
            except OSError:
                mtime_iso = ""
            self._broadcast_json({
                "type": "viewer_new_image",
                "rel_path": rel,
                "filename": filename,
                "mtime_iso": mtime_iso,
            })

    # --- 생성 파라미터 동기화 ---

    def _combo_items(self, combo) -> list:
        return [combo.itemText(i) for i in range(combo.count())]

    def get_generation_params(self) -> dict:
        """현재 생성 파라미터 + 선택 가능 옵션 목록 반환"""
        try:
            mw = self.app_context.main_window
            mode = self.app_context.get_api_mode()
            params = {
                "type": "params",
                "api_mode": mode,
                "model": mw.model_combo.currentText(),
                "sampler": mw.sampler_combo.currentText(),
                "scheduler": mw.scheduler_combo.currentText(),
                "resolution": mw.resolution_combo.currentText(),
                "steps": mw.steps_spinbox.value(),
                "cfg_scale": round(mw.cfg_scale_slider.value() / 10.0, 1),
                "cfg_rescale": round(mw.cfg_rescale_slider.value() / 100.0, 2),
                "seed": mw.seed_input.text(),
                "seed_fixed": mw.seed_fix_checkbox.isChecked(),
                "random_resolution": mw.random_resolution_checkbox.isChecked(),
                "auto_fit_resolution": mw.auto_fit_resolution_checkbox.isChecked(),
                # 옵션 목록 (웹 UI select 구성용)
                "options_model": self._combo_items(mw.model_combo),
                "options_sampler": self._combo_items(mw.sampler_combo),
                "options_scheduler": self._combo_items(mw.scheduler_combo),
                "options_resolution": self._combo_items(mw.resolution_combo),
                "steps_range": [mw.steps_spinbox.minimum(), mw.steps_spinbox.maximum()],
            }
            # 모드별 파라미터
            if mode == "NAI":
                nai_flags = {}
                for key in ["SMEA", "DYN", "VAR+", "DECRISP"]:
                    cb = mw.advanced_checkboxes.get(key)
                    if cb:
                        params[key] = cb.isChecked()
                        nai_flags[key] = cb.isEnabled()
                params["nai_flags_enabled"] = nai_flags
            elif mode == "WEBUI":
                if hasattr(mw, 'enable_hr_checkbox'):
                    params["enable_hr"] = mw.enable_hr_checkbox.isChecked()
                    params["hr_scale"] = mw.hr_scale_spinbox.value()
                    params["hr_upscaler"] = mw.hr_upscaler_combo.currentText()
                    params["denoising_strength"] = mw.denoising_strength_spinbox.value()
                    params["hires_steps"] = mw.hires_steps_spinbox.value()
                    params["hr_cfg"] = mw.hr_cfg_spinbox.value()
                    params["options_hr_upscaler"] = self._combo_items(mw.hr_upscaler_combo)
            # ComfyUI sampling_mode / rescale_cfg 는 mode 와 무관하게 항상 송신
            # (데스크탑 우선권 보장 — 모드 전환 타이밍에 누락되지 않도록).
            if hasattr(mw, 'eps_radio'):
                if mw.eps_radio.isChecked():
                    params["sampling_mode"] = "eps"
                elif mw.v_pred_radio.isChecked():
                    params["sampling_mode"] = "v_prediction"
                elif mw.anima_radio.isChecked():
                    params["sampling_mode"] = "anima"
            if hasattr(mw, 'comfyui_rescale_slider'):
                params["rescale_cfg"] = round(mw.comfyui_rescale_slider.value() / 100.0, 2)
            return params
        except Exception as e:
            print(f"🌐 Remote: 파라미터 읽기 실패 — {e}")
            return {}

    def _do_set_param(self, key: str, value: str):
        """웹에서 변경한 생성 파라미터를 메인 앱 위젯에 반영"""
        try:
            self._syncing_param = True
            mw = self.app_context.main_window
            if key == "model":
                idx = mw.model_combo.findText(value)
                if idx >= 0: mw.model_combo.setCurrentIndex(idx)
            elif key == "sampler":
                idx = mw.sampler_combo.findText(value)
                if idx >= 0: mw.sampler_combo.setCurrentIndex(idx)
            elif key == "scheduler":
                idx = mw.scheduler_combo.findText(value)
                if idx >= 0: mw.scheduler_combo.setCurrentIndex(idx)
            elif key == "resolution":
                idx = mw.resolution_combo.findText(value)
                if idx >= 0: mw.resolution_combo.setCurrentIndex(idx)
            elif key == "steps":
                mw.steps_spinbox.setValue(int(value))
            elif key == "cfg_scale":
                mw.cfg_scale_slider.setValue(int(float(value) * 10))
            elif key == "cfg_rescale":
                mw.cfg_rescale_slider.setValue(int(float(value) * 100))
            elif key == "seed":
                mw.seed_input.setText(value)
            elif key == "seed_fixed":
                mw.seed_fix_checkbox.setChecked(value == "true")
            elif key == "random_resolution":
                mw.random_resolution_checkbox.setChecked(value == "true")
            elif key == "auto_fit_resolution":
                mw.auto_fit_resolution_checkbox.setChecked(value == "true")
            elif key in ("SMEA", "DYN", "VAR+", "DECRISP"):
                cb = mw.advanced_checkboxes.get(key)
                if cb: cb.setChecked(value == "true")
            # WEBUI
            elif key == "enable_hr" and hasattr(mw, 'enable_hr_checkbox'):
                mw.enable_hr_checkbox.setChecked(value == "true")
            elif key == "hr_scale" and hasattr(mw, 'hr_scale_spinbox'):
                mw.hr_scale_spinbox.setValue(float(value))
            elif key == "hr_upscaler" and hasattr(mw, 'hr_upscaler_combo'):
                idx = mw.hr_upscaler_combo.findText(value)
                if idx >= 0: mw.hr_upscaler_combo.setCurrentIndex(idx)
            elif key == "denoising_strength" and hasattr(mw, 'denoising_strength_spinbox'):
                mw.denoising_strength_spinbox.setValue(float(value))
            elif key == "hires_steps" and hasattr(mw, 'hires_steps_spinbox'):
                mw.hires_steps_spinbox.setValue(int(value))
            elif key == "hr_cfg" and hasattr(mw, 'hr_cfg_spinbox'):
                mw.hr_cfg_spinbox.setValue(float(value))
            # ComfyUI
            elif key == "sampling_mode" and hasattr(mw, 'eps_radio'):
                if value == "eps": mw.eps_radio.setChecked(True)
                elif value == "v_prediction": mw.v_pred_radio.setChecked(True)
                elif value == "anima": mw.anima_radio.setChecked(True)
            elif key == "rescale_cfg" and hasattr(mw, 'comfyui_rescale_slider'):
                mw.comfyui_rescale_slider.setValue(int(float(value) * 100))
            self._syncing_param = False
        except Exception as e:
            self._syncing_param = False
            print(f"🌐 Remote: 파라미터 설정 실패 — {key}={value}: {e}")

    def _on_params_changed(self):
        """파라미터 위젯 변경 시 디바운스 후 웹에 전송"""
        if self._syncing_param:
            return
        if self._params_debounce_timer is None:
            self._params_debounce_timer = QTimer()
            self._params_debounce_timer.setSingleShot(True)
            self._params_debounce_timer.timeout.connect(self._broadcast_params)
        self._params_debounce_timer.start(300)

    def _broadcast_params(self):
        """현재 파라미터 캐시 갱신 + WS 클라이언트에 전송"""
        data = self.get_generation_params()
        if data:
            self._cached_params = data
            if self._has_clients():
                self._broadcast_json(data)

    # --- 생성 상태 동기화 (메인 UI 포함) ---

    def _on_generation_started_signal(self, data=None):
        """generation_started 이벤트 → 웹에 상태 전송"""
        if self._has_clients():
            self._broadcast_json({"type": "status", "is_generating": True})

    # --- 모듈 상태 (Qt 메인 스레드에서 실행) ---

    def _find_module(self, module_id: str):
        """MiddleSectionController에서 모듈 인스턴스 검색"""
        msc = getattr(self.app_context, 'middle_section_controller', None)
        if not msc:
            return None
        class_map = {
            "prompt_engineering": "PromptEngineeringModule",
            "automation": "AutomationModule",
            "character": "CharacterModule",
            "conditional_prompt": "PromptListModifierModule",
            "character_reference": "CharacterReferenceModule",
            "vibe_transfer": "VibeTransferModule",
            "wildcard": "WildcardStatusModule",
            "instant_wildcard": "InstantWildcardModule",
        }
        target_class = class_map.get(module_id)
        if not target_class:
            return None
        for module in msc.module_instances:
            if module.__class__.__name__ == target_class:
                return module
        return None

    def _get_image_viewer_module(self):
        """RightView 내부의 ImageViewerModule 인스턴스를 반환."""
        try:
            mw = self.app_context.main_window
            right_view = getattr(mw, "image_window", None)
            tab_controller = getattr(right_view, "tab_controller", None)
            if tab_controller and hasattr(tab_controller, "get_tab_instance"):
                return tab_controller.get_tab_instance("ImageViewerModule")
        except Exception:
            pass
        return None

    def _get_image_window_widget(self):
        """실제 ImageWindow 위젯을 반환."""
        image_viewer_module = self._get_image_viewer_module()
        if image_viewer_module:
            widget = getattr(image_viewer_module, "image_window_widget", None)
            if widget:
                return widget

        # 레거시 폴백: main_window.image_window가 직접 ImageWindow인 구조도 허용
        try:
            mw = self.app_context.main_window
            legacy_widget = getattr(mw, "image_window", None)
            if legacy_widget and hasattr(legacy_widget, "auto_save_checkbox"):
                return legacy_widget
        except Exception:
            pass
        return None

    def _get_auto_save_checkbox(self):
        image_window = self._get_image_window_widget()
        if image_window:
            return getattr(image_window, "auto_save_checkbox", None)
        return None

    def _get_save_as_webp_checkbox(self):
        image_window = self._get_image_window_widget()
        if image_window:
            return getattr(image_window, "save_as_webp_checkbox", None)
        return None

    def _get_history_limit_widgets(self):
        image_window = self._get_image_window_widget()
        if not image_window:
            return None, None, None
        enabled = getattr(image_window, "history_limit_enabled", None)
        max_length = getattr(image_window, "max_history_length", None)
        action_group = getattr(image_window, "memory_action_group", None)
        return enabled, max_length, action_group

    def _do_get_module(self, ws, module_id: str):
        """모듈 상태 읽기 → 요청 클라이언트에 unicast"""
        if module_id == "__search__":
            state = self._read_search_state()
        elif module_id == "__depth__":
            state = self._read_depth_state()
        else:
            state = self._read_module_state(module_id, ws=ws)
        if state:
            if ws:
                self._send_json_to(ws, state)
            else:
                self._broadcast_json(state)

    def _read_module_state(self, module_id: str, ws=None) -> dict:
        """모듈 상태 딕셔너리 반환"""
        if module_id == "prompt_engineering":
            return self._read_prompt_engineering(ws=ws)
        elif module_id == "auto_save":
            return self._read_auto_save_settings()
        elif module_id == "automation":
            return self._read_automation()
        elif module_id == "character":
            return self._read_character()
        elif module_id == "conditional_prompt":
            return self._read_conditional_prompt(ws=ws)
        elif module_id == "character_reference":
            return self._read_character_reference()
        elif module_id == "vibe_transfer":
            return self._read_vibe_transfer()
        elif module_id == "save_directory":
            return self._read_save_directory(ws=ws)
        elif module_id == "wildcard":
            return self._read_wildcard()
        elif module_id == "chunk":
            return self._read_chunk()
        return {}

    def _read_save_directory(self, ws=None) -> dict:
        try:
            image_crud = getattr(self.app_context, "image_crud_controller", None)
            if not image_crud:
                return {}

            base_path = getattr(image_crud, "_base_save_path", Path("output"))
            use_timestamp = bool(image_crud.get_use_timestamp_folder())
            current_save_dir = image_crud.get_save_directory()
            payload = {
                "type": "module_state",
                "module_id": "save_directory",
                "base_path": str(base_path),
                "current_save_directory": str(current_save_dir),
                "session_timestamp": getattr(self.app_context, "session_timestamp", ""),
                "use_timestamp_folder": use_timestamp,
                "save_counter": int(getattr(image_crud, "_save_counter", 1)),
                "filename_format": image_crud.get_filename_format(),
                "filename_format_options": [
                    {"value": "number_only", "label": "번호만 (00001.png)"},
                    {"value": "time_number", "label": "시간_번호 (143052_00001.png)"},
                    {"value": "datetime", "label": "날짜_시간 (20250108_143052.png)"},
                    {"value": "prompt", "label": "프롬프트 (prompt.png)"},
                    {"value": "wildcard", "label": "와일드카드 (wildcard.png)"},
                ],
                "classification_method": image_crud.get_classification_method(),
                "classification_method_options": [
                    {"value": "none", "label": "분류 없음"},
                    {"value": "prompt_recognition", "label": "프롬프트 인식"},
                ],
                "classification_rules": image_crud.get_classification_rules(),
            }
            if ws is not None:
                control_allowed, control_reason = self._save_directory_gate(ws)
                payload["control_allowed"] = control_allowed
                payload["control_block_reason"] = control_reason
                payload["browse_allowed"] = control_allowed
                payload["browse_block_reason"] = control_reason
            return payload
        except Exception as e:
            print(f"🌐 Remote: save_directory 상태 읽기 실패 — {e}")
            return {}

    def _broadcast_save_directory_state(self):
        if not self._has_clients():
            return
        for ws in list(self._ws_manager.active_connections):
            self._send_json_to(ws, self._read_save_directory(ws=ws))

    def on_save_directory_changed(self, _data: dict):
        self._broadcast_save_directory_state()

    def _persist_base_save_directory_setting(self, new_path: str):
        """데스크탑 Settings와 동일한 설정 파일에도 base_path를 반영."""
        try:
            mw = getattr(self.app_context, "main_window", None)
            right_view = getattr(mw, "image_window", None)
            tab_controller = getattr(right_view, "tab_controller", None)
            settings_tab = tab_controller.get_tab_instance("SettingsTabModule") if tab_controller else None
            settings_widget = getattr(settings_tab, "settings_widget", None) if settings_tab else None

            if settings_tab is not None:
                settings_tab.set_setting('save_directory.base_path', new_path)
            else:
                settings_path = Path("app_settings.json")
                settings_data = {}
                if settings_path.exists():
                    try:
                        with open(settings_path, "r", encoding="utf-8") as f:
                            settings_data = json.load(f) or {}
                    except Exception:
                        settings_data = {}
                settings_data.setdefault("save_directory", {})["base_path"] = new_path
                with open(settings_path, "w", encoding="utf-8") as f:
                    json.dump(settings_data, f, indent=2, ensure_ascii=False)

            if settings_widget is not None and hasattr(settings_widget, "save_path_edit"):
                settings_widget.save_path_edit.blockSignals(True)
                settings_widget.save_path_edit.setText(new_path)
                settings_widget.save_path_edit.blockSignals(False)
        except Exception as e:
            print(f"🌐 Remote: save_directory 설정 영속화 실패 — {e}")

    def _read_auto_save_settings(self) -> dict:
        try:
            auto_save_checkbox = self._get_auto_save_checkbox()
            save_as_webp_checkbox = self._get_save_as_webp_checkbox()
            history_limit_enabled, max_history_length, memory_action_group = self._get_history_limit_widgets()

            memory_action = 1
            if memory_action_group is not None and memory_action_group.checkedId() > 0:
                memory_action = int(memory_action_group.checkedId())

            return {
                "type": "module_state",
                "module_id": "auto_save",
                "auto_save": bool(auto_save_checkbox and auto_save_checkbox.isChecked()),
                "save_as_webp": bool(save_as_webp_checkbox and save_as_webp_checkbox.isChecked()),
                "history_limit_enabled": bool(history_limit_enabled and history_limit_enabled.isChecked()),
                "max_history_length": int(max_history_length.value()) if max_history_length else 2000,
                "memory_action": memory_action,
                "memory_action_options": [
                    {"value": 1, "label": "[1] 1장씩 자동저장+정리"},
                    {"value": 2, "label": "[2] 1장씩 저장없이 삭제"},
                    {"value": 3, "label": "[3] 자동생성 중단"},
                ],
            }
        except Exception as e:
            print(f"🌐 Remote: auto_save 상태 읽기 실패 — {e}")
            return {}

    def _broadcast_auto_save_settings(self):
        state = self._read_auto_save_settings()
        if state and self._has_clients():
            self._broadcast_json(state)

    def _on_auto_save_settings_changed(self, *_args):
        self._broadcast_auto_save_settings()

    def _read_prompt_engineering(self, ws=None) -> dict:
        try:
            m = self._find_module("prompt_engineering")
            if not m:
                return {}

            # Shared Mode: 세션에서 읽기 (없으면 1회 초기화)
            session = self._ws_manager.sessions.get(ws) if (self.shared_server_mode and ws and self._ws_manager) else None
            if session is not None:
                # 1회 초기화 (Copy 플래그에 따라 데스크톱 복사 or 빈 값)
                if session.get("p_eng_override") is None:
                    if getattr(self.app_context, 'shared_copy_peng', False):
                        pp = {}
                        for label, cb in m.preprocessing_checkboxes.items():
                            pp[m.option_key_map.get(label, label)] = cb.isChecked()
                        session["p_eng_override"] = {
                            "pre_prompt": m.pre_textedit.toPlainText(),
                            "post_prompt": m.post_textedit.toPlainText(),
                            "auto_hide": m.auto_hide_textedit.toPlainText(),
                            "preprocessing_options": pp,
                        }
                    else:
                        session["p_eng_override"] = {}
                override = session["p_eng_override"]
                pp = {}
                for label, cb in m.preprocessing_checkboxes.items():
                    pp[m.option_key_map.get(label, label)] = False
                if override.get("preprocessing_options"):
                    pp.update(override["preprocessing_options"])
                return {
                    "type": "module_state",
                    "module_id": "prompt_engineering",
                    "preset": "*remote",
                    "preset_options": ["*remote"],
                    "pre_prompt": override.get("pre_prompt", ""),
                    "post_prompt": override.get("post_prompt", ""),
                    "auto_hide": override.get("auto_hide", ""),
                    "preprocessing": pp,
                    "e621_settings": {},
                    "danbooru_settings": {},
                    "debug_snapshot": {},
                    "preset_can_save_current": False,
                    "preset_can_delete": False,
                }

            preprocessing = {}
            for label, cb in m.preprocessing_checkboxes.items():
                key = m.option_key_map.get(label, label)
                preprocessing[key] = cb.isChecked()
            presets = [m.preset_combo.itemText(i) for i in range(m.preset_combo.count())]
            current_preset = m.preset_combo.currentText()
            return {
                "type": "module_state",
                "module_id": "prompt_engineering",
                "preset": current_preset,
                "preset_options": presets,
                "pre_prompt": m.pre_textedit.toPlainText(),
                "post_prompt": m.post_textedit.toPlainText(),
                "auto_hide": m.auto_hide_textedit.toPlainText(),
                "preprocessing": preprocessing,
                "e621_settings": dict(getattr(m, "_e621_settings", {}) or {}),
                "danbooru_settings": dict(getattr(m, "_danbooru_weight_settings", {}) or {}),
                "debug_snapshot": m.get_debug_snapshot() if hasattr(m, "get_debug_snapshot") else {},
                "preset_can_save_current": current_preset not in ("", "(프리셋 없음)", "*randomized"),
                "preset_can_delete": current_preset not in ("", "(프리셋 없음)", "*randomized", "default"),
            }
        except Exception as e:
            print(f"🌐 Remote: 모듈 상태 읽기 실패 — {e}")
            return {}

    def _broadcast_prompt_engineering_state(self):
        state = self._read_prompt_engineering()
        if state:
            self._broadcast_json(state)

    @staticmethod
    def _coerce_bool(value) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)

    def _sanitize_remote_e621_settings(self, raw_settings: dict, current_settings: dict) -> dict:
        settings = dict(current_settings or {})

        try:
            weight = float(raw_settings.get("weight", settings.get("weight", 0.0)))
        except (TypeError, ValueError):
            weight = settings.get("weight", 0.0)
        settings["weight"] = max(-5.0, min(5.0, weight))

        mode = str(raw_settings.get("mode", settings.get("mode", "stable")) or "stable")
        settings["mode"] = mode if mode in {"stable", "confused"} else "stable"

        hidden_tags = raw_settings.get("hidden_tags", settings.get("hidden_tags", []))
        if isinstance(hidden_tags, str):
            hidden_tags = hidden_tags.replace("\n", ",").split(",")
        if not isinstance(hidden_tags, list):
            hidden_tags = []

        normalized_hidden = []
        for tag in hidden_tags:
            clean = str(tag).strip().replace(" ", "_")
            if clean and clean not in normalized_hidden:
                normalized_hidden.append(clean)
        settings["hidden_tags"] = normalized_hidden
        return settings

    def _sanitize_remote_danbooru_settings(self, raw_settings: dict, current_settings: dict) -> dict:
        settings = dict(current_settings or {})

        def _float_value(key: str, default: float, lo: float, hi: float) -> float:
            try:
                value = float(raw_settings.get(key, settings.get(key, default)))
            except (TypeError, ValueError):
                value = settings.get(key, default)
            return max(lo, min(hi, value))

        try:
            magnitude = int(raw_settings.get("magnitude", settings.get("magnitude", 3)))
        except (TypeError, ValueError):
            magnitude = settings.get("magnitude", 3)
        settings["magnitude"] = max(1, min(10, magnitude))
        settings["rating_blend"] = round(_float_value("rating_blend", 0.3, 0.0, 1.0), 2)
        settings["override_on"] = self._coerce_bool(raw_settings.get("override_on", settings.get("override_on", False)))
        settings["override_scale"] = _float_value("override_scale", 0.35, 0.0, 5.0)
        settings["override_min"] = _float_value("override_min", 0.80, 0.0, 5.0)
        settings["override_max"] = _float_value("override_max", 1.35, 0.0, 10.0)
        settings["rating_override_on"] = self._coerce_bool(
            raw_settings.get("rating_override_on", settings.get("rating_override_on", False))
        )
        rating_override = str(raw_settings.get("rating_override", settings.get("rating_override", "s")) or "s")
        settings["rating_override"] = rating_override if rating_override in {"g", "s", "q", "e"} else "s"
        settings["invert_weight"] = self._coerce_bool(
            raw_settings.get("invert_weight", settings.get("invert_weight", False))
        )
        return settings

    def _read_automation(self) -> dict:
        try:
            m = self._find_module("automation")
            if not m:
                return {}
            # automation type: 0=unlimited, 1=timer, 2=count
            auto_type = 0
            if m.timer_radio and m.timer_radio.isChecked():
                auto_type = 1
            elif m.count_radio and m.count_radio.isChecked():
                auto_type = 2
            return {
                "type": "module_state",
                "module_id": "automation",
                "delay": m.delay_input.text() if m.delay_input else "0",
                "random_delay": m.random_delay_checkbox.isChecked() if m.random_delay_checkbox else False,
                "repeat": m.repeat_input.text() if m.repeat_input else "1",
                "auto_type": auto_type,
                "timer_minutes": m.timer_input.text() if m.timer_input else "30",
                "count_limit": m.count_input.text() if m.count_input else "100",
                "notify": m.notify_checkbox.isChecked() if m.notify_checkbox else False,
                "is_running": m.automation_controller.is_running if m.automation_controller else False,
                "status": m.automation_count_label.text() if m.automation_count_label else "",
                "repeat_info": m.repeat_info_label.text() if hasattr(m, 'repeat_info_label') and m.repeat_info_label else "",
                "delay_info": m.delay_info_label.text() if hasattr(m, 'delay_info_label') and m.delay_info_label else "",
            }
        except Exception as e:
            print(f"🌐 Remote: automation 상태 읽기 실패 — {e}")
            return {}

    def _read_character(self) -> dict:
        try:
            m = self._find_module("character")
            if not m:
                return {}
            characters = []
            for w in m.character_widgets:
                characters.append({
                    "id": w.char_id,
                    "active": w.active_checkbox.isChecked(),
                    "prompt": w.prompt_textbox.toPlainText(),
                    "uc": w.uc_textbox.toPlainText(),
                })
            processed_data = getattr(m, "modifiable_clone", None)
            if not isinstance(processed_data, dict):
                processed_data = getattr(m, "last_processed_data", {}) or {}
            processed_characters = [str(v) for v in processed_data.get("characters", []) if v is not None]
            processed_ucs = [str(v) for v in processed_data.get("uc", []) if v is not None]
            character_token_count = 0
            try:
                if m.activate_checkbox and m.activate_checkbox.isChecked() and processed_characters:
                    from utils.token_calculator import get_token_calculator

                    calculator = get_token_calculator()
                    if calculator.available:
                        character_token_count = calculator.count_tokens(
                            " ".join(processed_characters),
                            current_mode="NAI",
                        )
            except Exception:
                character_token_count = 0
            return {
                "type": "module_state",
                "module_id": "character",
                "activated": m.activate_checkbox.isChecked() if m.activate_checkbox else False,
                "reroll_on_generate": m.reroll_on_generate_checkbox.isChecked() if m.reroll_on_generate_checkbox else False,
                "characters": characters,
                "character_count": len(characters),
                "active_count": sum(1 for w in m.character_widgets if w.active_checkbox.isChecked()),
                "processed_characters": processed_characters,
                "processed_ucs": processed_ucs,
                "character_token_count": character_token_count,
                "processed_preview_text": (
                    m.processed_prompt_display.toPlainText()
                    if hasattr(m, "processed_prompt_display") and m.processed_prompt_display
                    else ""
                ),
            }
        except Exception as e:
            print(f"🌐 Remote: character 상태 읽기 실패 — {e}")
            return {}

    def _read_conditional_prompt(self, ws=None) -> dict:
        try:
            m = self._find_module("conditional_prompt")
            if not m:
                return {}
            # Shared Mode: 세션 오버라이드
            session = self._ws_manager.sessions.get(ws) if (self.shared_server_mode and ws and self._ws_manager) else None
            if session is not None:
                # 1회 초기화
                if session.get("cond_override") is None:
                    if getattr(self.app_context, 'shared_copy_cond', False):
                        session["cond_override"] = {
                            "enabled": m.enable_checkbox.isChecked() if hasattr(m, 'enable_checkbox') else False,
                            "rules": m.rules_textedit.toPlainText() if hasattr(m, 'rules_textedit') else "",
                        }
                    else:
                        session["cond_override"] = {}
                override = session["cond_override"]
                return {
                    "type": "module_state",
                    "module_id": "conditional_prompt",
                    "enabled": override.get("enabled", False),
                    "rules": override.get("rules", ""),
                    "log": "",
                }
            return {
                "type": "module_state",
                "module_id": "conditional_prompt",
                "enabled": m.enable_checkbox.isChecked() if hasattr(m, 'enable_checkbox') else False,
                "rules": m.rules_textedit.toPlainText() if hasattr(m, 'rules_textedit') else "",
                "log": m.log_textedit.toPlainText() if hasattr(m, 'log_textedit') else "",
            }
        except Exception as e:
            print(f"🌐 Remote: conditional_prompt 상태 읽기 실패 — {e}")
            return {}

    def _do_set_module(self, module_id: str, key: str, value: str):
        """웹에서 변경한 모듈 파라미터를 메인 앱에 반영"""
        if module_id == "prompt_engineering":
            self._set_prompt_engineering(key, value)
        elif module_id == "auto_save":
            self._set_auto_save_settings(key, value)
        elif module_id == "automation":
            self._set_automation(key, value)
        elif module_id == "character":
            self._set_character(key, value)
        elif module_id == "conditional_prompt":
            self._set_conditional_prompt(key, value)
        elif module_id == "character_reference":
            self._set_character_reference(key, value)
        elif module_id == "vibe_transfer":
            self._set_vibe_transfer(key, value)
        elif module_id == "save_directory":
            self._set_save_directory(key, value)
        elif module_id == "wildcard":
            self._set_wildcard(key, value)

    def _set_auto_save_settings(self, key: str, value: str):
        try:
            image_window = self._get_image_window_widget()
            if not image_window:
                return

            if key == "save_as_webp":
                checkbox = self._get_save_as_webp_checkbox()
                if checkbox and checkbox.isChecked() != (value == "true"):
                    checkbox.setChecked(value == "true")
            elif key == "history_limit_enabled":
                checkbox, _, _ = self._get_history_limit_widgets()
                if checkbox and checkbox.isChecked() != (value == "true"):
                    checkbox.setChecked(value == "true")
            elif key == "max_history_length":
                _, spinbox, _ = self._get_history_limit_widgets()
                if spinbox:
                    new_value = max(spinbox.minimum(), min(spinbox.maximum(), int(value)))
                    if spinbox.value() != new_value:
                        spinbox.setValue(new_value)
                    else:
                        image_window.save_memory_settings()
            elif key == "memory_action":
                _, _, action_group = self._get_history_limit_widgets()
                if action_group:
                    action_id = int(value)
                    button = action_group.button(action_id)
                    if button and not button.isChecked():
                        button.setChecked(True)
                    if hasattr(image_window, "save_memory_settings"):
                        image_window.save_memory_settings()
            else:
                return

            self._broadcast_auto_save_settings()
        except Exception as e:
            print(f"🌐 Remote: auto_save 설정 실패 — {key}={value}: {e}")
            self._broadcast_json({"type": "toast", "message": f"Auto Save 설정 실패: {e}", "level": "error"})

    def _set_save_directory(self, key: str, value: str):
        try:
            image_crud = getattr(self.app_context, "image_crud_controller", None)
            if not image_crud:
                return

            if key == "base_path":
                self._broadcast_json({
                    "type": "toast",
                    "message": "기본 저장 경로는 Browse로만 변경할 수 있습니다.",
                    "level": "error",
                })
                return
            elif key == "use_timestamp_folder":
                image_crud.set_use_timestamp_folder(value == "true")
            elif key == "filename_format":
                image_crud.set_filename_format(value)
            elif key == "classification_method":
                image_crud.set_classification_method(value)
            elif key == "classification_rules":
                image_crud.set_classification_rules(value)
            else:
                return

            self._broadcast_save_directory_state()
        except Exception as e:
            print(f"🌐 Remote: save_directory 설정 실패 — {key}={value}: {e}")
            self._broadcast_json({"type": "toast", "message": f"저장 디렉토리 설정 실패: {e}", "level": "error"})

    def _do_browse_save_directory(self, ws):
        try:
            image_crud = getattr(self.app_context, "image_crud_controller", None)
            if not image_crud:
                return

            current_path = str(getattr(image_crud, "_base_save_path", Path("output")))
            new_path = QFileDialog.getExistingDirectory(None, "저장 디렉토리 선택", current_path)
            if not new_path:
                return

            self._persist_base_save_directory_setting(new_path)
            self.app_context.set_base_save_directory(new_path)
            self._broadcast_save_directory_state()
            if ws is not None:
                self._send_json_to(ws, {
                    "type": "toast",
                    "message": f"저장 경로 변경: {new_path}",
                    "level": "success",
                })
        except Exception as e:
            print(f"🌐 Remote: save_directory 찾아보기 실패 — {e}")
            if ws is not None:
                self._send_json_to(ws, {
                    "type": "toast",
                    "message": f"저장 디렉토리 선택 실패: {e}",
                    "level": "error",
                })

    def _set_prompt_engineering(self, key: str, value: str):
        try:
            m = self._find_module("prompt_engineering")
            if not m:
                return
            if key == "pre_prompt":
                m.pre_textedit.setPlainText(value)
            elif key == "post_prompt":
                m.post_textedit.setPlainText(value)
            elif key == "auto_hide":
                m.auto_hide_textedit.setPlainText(value)
            elif key == "preset":
                idx = m.preset_combo.findText(value)
                if idx >= 0:
                    m.preset_combo.setCurrentIndex(idx)
                    self._broadcast_prompt_engineering_state()
            elif key == "preset_save_current":
                current_preset = m.preset_combo.currentText() if m.preset_combo else getattr(m, "current_preset", "")
                if current_preset in ("", "(프리셋 없음)", "*randomized"):
                    self._broadcast_json({"type": "toast", "message": "저장할 현재 프리셋이 없습니다.", "level": "error"})
                    return
                m.save_current_preset(current_preset)
                m.current_preset = current_preset
                m.last_preset = current_preset
                m.save_last_used_preset_info()
                self._broadcast_json({"type": "toast", "message": f"프리셋 저장: {current_preset}", "level": "success"})
                self._broadcast_prompt_engineering_state()
            elif key == "preset_create":
                ok, result = m.save_preset_noninteractive(value)
                if ok:
                    self._broadcast_json({"type": "toast", "message": f"프리셋 저장: {result}", "level": "success"})
                    self._broadcast_prompt_engineering_state()
                else:
                    self._broadcast_json({"type": "toast", "message": result, "level": "error"})
            elif key == "preset_apply_recommended":
                if hasattr(self.app_context, "get_api_mode") and self.app_context.get_api_mode() != "NAI":
                    self._broadcast_json({
                        "type": "toast",
                        "message": "추천 설정 적용은 NAI 모드에서만 사용할 수 있습니다.",
                        "level": "error",
                    })
                    return
                ok, result = m.create_and_apply_recommended_preset()
                if ok:
                    self._broadcast_json({"type": "toast", "message": f"추천 프리셋 적용: {result}", "level": "success"})
                    self._broadcast_prompt_engineering_state()
                else:
                    self._broadcast_json({"type": "toast", "message": result, "level": "error"})
            elif key == "preset_delete":
                target_name = value or (m.preset_combo.currentText() if m.preset_combo else getattr(m, "current_preset", ""))
                ok, result = m.delete_preset_noninteractive(target_name)
                if ok:
                    self._broadcast_json({"type": "toast", "message": f"프리셋 삭제: {result}", "level": "success"})
                    self._broadcast_prompt_engineering_state()
                else:
                    self._broadcast_json({"type": "toast", "message": result, "level": "error"})
            elif key == "e621_settings":
                settings = self._sanitize_remote_e621_settings(
                    json.loads(value or "{}"),
                    getattr(m, "_e621_settings", {}),
                )
                m._on_e621_settings_changed(settings)
                try:
                    if getattr(m, "_e621_settings_window", None) is not None and m._e621_settings_window.isVisible():
                        m._e621_settings_window.load_settings(settings)
                except RuntimeError:
                    m._e621_settings_window = None
                self._broadcast_json({"type": "toast", "message": "e621 설정 저장됨", "level": "success"})
                self._broadcast_prompt_engineering_state()
            elif key == "danbooru_settings":
                settings = self._sanitize_remote_danbooru_settings(
                    json.loads(value or "{}"),
                    getattr(m, "_danbooru_weight_settings", {}),
                )
                m._on_danbooru_weight_settings_changed(settings)
                try:
                    if getattr(m, "_danbooru_weight_settings_window", None) is not None and m._danbooru_weight_settings_window.isVisible():
                        m._danbooru_weight_settings_window.load_settings(settings)
                except RuntimeError:
                    m._danbooru_weight_settings_window = None
                self._broadcast_json({"type": "toast", "message": "Danbooru 설정 저장됨", "level": "success"})
                self._broadcast_prompt_engineering_state()
            elif key == "debug_refresh":
                self._broadcast_prompt_engineering_state()
            elif key.startswith("pp_"):
                # preprocessing option: pp_remove_author → remove_author
                pp_key = key[3:]
                # option_key_map 역참조: value→label
                for label, opt_key in m.option_key_map.items():
                    if opt_key == pp_key:
                        cb = m.preprocessing_checkboxes.get(label)
                        if cb:
                            cb.setChecked(value == "true")
                            self._broadcast_prompt_engineering_state()
                        break
        except Exception as e:
            print(f"🌐 Remote: 모듈 설정 실패 — {key}={value}: {e}")

    def _set_automation(self, key: str, value: str):
        try:
            m = self._find_module("automation")
            if not m:
                return
            should_broadcast = False
            if key == "delay":
                m.delay_input.setText(value)
                should_broadcast = True
            elif key == "random_delay":
                m.random_delay_checkbox.setChecked(value == "true")
                should_broadcast = True
            elif key == "repeat":
                m.repeat_input.setText(value)
                should_broadcast = True
            elif key == "auto_type":
                v = int(value)
                if v == 0 and m.unlimited_radio:
                    m.unlimited_radio.setChecked(True)
                    should_broadcast = True
                elif v == 1 and m.timer_radio:
                    m.timer_radio.setChecked(True)
                    should_broadcast = True
                elif v == 2 and m.count_radio:
                    m.count_radio.setChecked(True)
                    should_broadcast = True
            elif key == "timer_minutes":
                if m.timer_input:
                    m.timer_input.setText(value)
                    should_broadcast = True
            elif key == "count_limit":
                if m.count_input:
                    m.count_input.setText(value)
                    should_broadcast = True
            elif key == "notify":
                if m.notify_checkbox:
                    m.notify_checkbox.setChecked(value == "true")
                    should_broadcast = True
            elif key == "start":
                m.start_automation()
                should_broadcast = True
            elif key == "stop":
                m.stop_automation()
                should_broadcast = True
            if should_broadcast:
                self._broadcast_automation_state()
        except Exception as e:
            print(f"🌐 Remote: automation 설정 실패 — {key}={value}: {e}")

    def _broadcast_automation_state(self):
        state = self._read_automation()
        if state:
            self._broadcast_json(state)

    def _broadcast_character_state(self):
        state = self._read_character()
        if state:
            self._broadcast_json(state)

    def _set_character(self, key: str, value: str):
        try:
            m = self._find_module("character")
            if not m:
                return
            if key == "activated":
                m.activate_checkbox.setChecked(value == "true")
                if m.activate_checkbox and not m.activate_checkbox.isChecked():
                    m.process_and_update_view()
                self._broadcast_character_state()
            elif key == "reroll_on_generate":
                if m.reroll_on_generate_checkbox:
                    m.reroll_on_generate_checkbox.setChecked(value == "true")
                self._broadcast_character_state()
            elif key == "bulk_characters":
                payload = json.loads(value or "{}")
                characters = payload.get("characters", [])
                characters_uc = payload.get("characters_uc", [])
                if not isinstance(characters, list):
                    characters = []
                if not isinstance(characters_uc, list):
                    characters_uc = []
                target_count = max(1, len(characters))
                while len(m.character_widgets) < target_count:
                    m.add_character_widget()
                for idx, widget in enumerate(m.character_widgets):
                    has_character = idx < len(characters) and bool(str(characters[idx]).strip())
                    widget.active_checkbox.setChecked(has_character)
                    if idx < len(characters):
                        widget.prompt_textbox.setPlainText(str(characters[idx] or ""))
                        uc_text = str(characters_uc[idx] or "") if idx < len(characters_uc) else ""
                        widget.uc_textbox.setPlainText(uc_text)
                if m.activate_checkbox:
                    m.activate_checkbox.setChecked(any(
                        bool(str(character).strip()) for character in characters
                    ))
                if hasattr(m, "process_and_update_view"):
                    m.process_and_update_view()
                self._broadcast_character_state()
            elif key == "add_character":
                m.add_character_widget()
                self._broadcast_character_state()
            elif key == "preview_refresh":
                m.process_and_update_view()
                self._broadcast_character_state()
            elif key.startswith("remove_character_"):
                idx = int(key.split("_")[-1])
                if len(m.character_widgets) <= 1:
                    self._broadcast_json({
                        "type": "toast",
                        "message": "마지막 캐릭터 슬롯은 삭제할 수 없습니다.",
                        "level": "error",
                    })
                    return
                if 0 <= idx < len(m.character_widgets):
                    m.remove_character_widget(m.character_widgets[idx])
                    self._broadcast_character_state()
            elif key.startswith("char_prompt_"):
                # char_prompt_0, char_prompt_1, ...
                idx = int(key.split("_")[-1])
                if idx < len(m.character_widgets):
                    m.character_widgets[idx].prompt_textbox.setPlainText(value)
            elif key.startswith("char_uc_"):
                idx = int(key.split("_")[-1])
                if idx < len(m.character_widgets):
                    m.character_widgets[idx].uc_textbox.setPlainText(value)
            elif key.startswith("char_active_"):
                idx = int(key.split("_")[-1])
                if idx < len(m.character_widgets):
                    m.character_widgets[idx].active_checkbox.setChecked(value == "true")
            # Broadcast badge update on activation/active toggle
            if key.startswith("char_active_"):
                self._broadcast_character_state()
        except Exception as e:
            print(f"🌐 Remote: character 설정 실패 — {key}={value}: {e}")

    def _set_conditional_prompt(self, key: str, value: str):
        try:
            m = self._find_module("conditional_prompt")
            if not m:
                return
            if key == "enabled":
                m.enable_checkbox.setChecked(value == "true")
                state = self._read_conditional_prompt()
                if state:
                    self._broadcast_json(state)
            elif key == "rules":
                m.rules_textedit.setPlainText(value)
            elif key == "test":
                # test_rules()를 직접 호출 (test_button은 로컬 변수)
                if hasattr(m, 'test_rules'):
                    m.test_rules()
                # 테스트 완료 후 로그 갱신 브로드캐스트
                state = self._read_conditional_prompt()
                if state:
                    self._broadcast_json(state)
        except Exception as e:
            print(f"🌐 Remote: conditional_prompt 설정 실패 — {key}={value}: {e}")

    # --- Character Reference / Vibe Transfer (이미지 업로드 모듈) ---

    def _generate_thumbnail_b64(self, pil_image, max_side=128) -> str:
        """PIL 이미지를 작은 JPEG 썸네일 base64로 변환"""
        from PIL import Image
        thumb = pil_image.copy()
        thumb.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
        if thumb.mode == 'RGBA':
            thumb = thumb.convert('RGB')
        buf = io.BytesIO()
        thumb.save(buf, format="JPEG", quality=70)
        return base64.b64encode(buf.getvalue()).decode()

    def _read_character_reference(self) -> dict:
        try:
            m = self._find_module("character_reference")
            if not m:
                return {}
            frames = []
            for i, f in enumerate(m.character_frames):
                thumb = ""
                try:
                    if hasattr(f, 'image') and f.image:
                        thumb = self._generate_thumbnail_b64(f.image)
                except Exception:
                    pass
                frames.append({
                    "index": i,
                    "file_hash": f.file_hash,
                    "file_name": f.file_name,
                    "is_enabled": f.is_enabled,
                    "reference_type": f.reference_type,
                    "strength": f.strength,
                    "fidelity": f.fidelity,
                    "thumbnail": thumb,
                })
            # NAID4.5 호환 여부 확인
            is_naid45 = False
            try:
                if hasattr(m, '_is_naid45_model'):
                    is_naid45 = m._is_naid45_model()
            except Exception:
                pass
            return {
                "type": "module_state",
                "module_id": "character_reference",
                "is_naid45": is_naid45,
                "frames": frames,
            }
        except Exception as e:
            print(f"🌐 Remote: character_reference 상태 읽기 실패 — {e}")
            return {}

    def _read_vibe_transfer(self) -> dict:
        try:
            m = self._find_module("vibe_transfer")
            if not m:
                return {}
            frames = []
            for i, f in enumerate(m.vibe_frames):
                thumb = ""
                try:
                    if hasattr(f, 'image') and f.image and not f.is_no_image:
                        thumb = self._generate_thumbnail_b64(f.image)
                except Exception:
                    pass
                encoding_keys = list(f.vibe_encodings.keys()) if hasattr(f, 'vibe_encodings') else []
                has_encoding = f.information_extracted in f.vibe_encodings if hasattr(f, 'vibe_encodings') else False
                frames.append({
                    "index": i,
                    "file_hash": f.file_hash,
                    "file_name": f.file_name,
                    "is_enabled": f.is_enabled,
                    "is_no_image": f.is_no_image,
                    "reference_strength": f.reference_strength,
                    "information_extracted": f.information_extracted,
                    "has_encoding": has_encoding,
                    "encoding_keys": [float(k) for k in encoding_keys],
                    "thumbnail": thumb,
                })
            return {
                "type": "module_state",
                "module_id": "vibe_transfer",
                "normalize": m.normalize_checkbox.isChecked() if hasattr(m, 'normalize_checkbox') else False,
                "frame_count": len(m.vibe_frames),
                "max_frames": 8,
                "frames": frames,
            }
        except Exception as e:
            print(f"🌐 Remote: vibe_transfer 상태 읽기 실패 — {e}")
            return {}

    def _set_character_reference(self, key: str, value: str):
        prev_stealth = getattr(self.app_context, 'stealth_mode', False)
        self.app_context.stealth_mode = True
        try:
            m = self._find_module("character_reference")
            if not m:
                return
            if key == "upload_image":
                img_bytes = base64.b64decode(value)
                temp_dir = Path("temp/remote_upload")
                temp_dir.mkdir(parents=True, exist_ok=True)
                temp_path = temp_dir / f"char_ref_{int(time.time() * 1000)}.png"
                temp_path.write_bytes(img_bytes)
                m._add_character_frame(str(temp_path))
            elif key.startswith("remove_frame_"):
                idx = int(key.split("_")[-1])
                if 0 <= idx < len(m.character_frames):
                    m._remove_frame(m.character_frames[idx])
            elif key.startswith("enable_"):
                idx = int(key.split("_")[-1])
                if 0 <= idx < len(m.character_frames):
                    enabling = (value == "true")
                    m.character_frames[idx].enable_check.setChecked(enabling)
                    # 상호 배타: Char Ref 활성 → Vibe 전부 비활성
                    if enabling:
                        self._disable_all_vibe_frames()
            elif key.startswith("strength_"):
                idx = int(key.split("_")[-1])
                if 0 <= idx < len(m.character_frames):
                    m.character_frames[idx].strength_slider.setValue(int(float(value) * 20))
            elif key.startswith("fidelity_"):
                idx = int(key.split("_")[-1])
                if 0 <= idx < len(m.character_frames):
                    m.character_frames[idx].fidelity_slider.setValue(int(float(value) * 20))
            elif key.startswith("ref_type_"):
                idx = int(key.split("_")[-1])
                if 0 <= idx < len(m.character_frames):
                    display_map = {"character&style": "Character & Style", "character": "Character", "style": "Style"}
                    m.character_frames[idx].ref_type_combo.setCurrentText(display_map.get(value, value))
            elif key == "get_storage":
                storage = self._scan_char_ref_storage()
                self._broadcast_json(storage)
                return
            elif key == "apply_storage":
                file_hash = value
                images_folder = Path("save/character_reference/images")
                image_path = images_folder / f"{file_hash}.png"
                if image_path.exists():
                    m._on_apply_character_from_storage(file_hash, image_path.name, str(image_path))
                    # Storage 적용은 자동 enable → Vibe 비활성
                    self._disable_all_vibe_frames()
            # 변경 후 상태 브로드캐스트
            state = self._read_character_reference()
            if state:
                self._broadcast_json(state)
        except Exception as e:
            print(f"🌐 Remote: character_reference 설정 실패 — {key}{'(image)' if key == 'upload_image' else ''}: {e}")
        finally:
            self.app_context.stealth_mode = prev_stealth

    def _set_vibe_transfer(self, key: str, value: str):
        prev_stealth = getattr(self.app_context, 'stealth_mode', False)
        self.app_context.stealth_mode = True
        try:
            m = self._find_module("vibe_transfer")
            if not m:
                return
            if key == "upload_image":
                img_bytes = base64.b64decode(value)
                temp_dir = Path("temp/remote_upload")
                temp_dir.mkdir(parents=True, exist_ok=True)
                temp_path = temp_dir / f"vibe_{int(time.time() * 1000)}.png"
                temp_path.write_bytes(img_bytes)
                m._add_vibe_frame(str(temp_path))
            elif key.startswith("remove_frame_"):
                idx = int(key.split("_")[-1])
                if 0 <= idx < len(m.vibe_frames):
                    m._remove_frame(m.vibe_frames[idx])
            elif key.startswith("enable_"):
                idx = int(key.split("_")[-1])
                if 0 <= idx < len(m.vibe_frames):
                    enabling = (value == "true")
                    m.vibe_frames[idx].enable_check.setChecked(enabling)
                    # 상호 배타: Vibe 활성 → Char Ref 전부 비활성
                    if enabling:
                        self._disable_all_char_ref_frames()
            elif key.startswith("ref_strength_"):
                idx = int(key.split("_")[-1])
                if 0 <= idx < len(m.vibe_frames):
                    m.vibe_frames[idx].ref_strength_slider.setValue(int(float(value) * 100))
            elif key.startswith("info_extracted_"):
                idx = int(key.split("_")[-1])
                if 0 <= idx < len(m.vibe_frames):
                    m.vibe_frames[idx].info_extracted_slider.setValue(int(float(value) * 100))
            elif key == "normalize":
                if hasattr(m, 'normalize_checkbox'):
                    m.normalize_checkbox.setChecked(value == "true")
            elif key.startswith("encode_"):
                idx = int(key.split("_")[-1])
                if 0 <= idx < len(m.vibe_frames):
                    frame = m.vibe_frames[idx]
                    if not frame.is_no_image:
                        m._on_encoding_requested(frame, frame.information_extracted)
            elif key == "get_storage":
                storage = self._scan_vibe_storage()
                self._broadcast_json(storage)
                return
            elif key == "apply_storage":
                # value = "model|file_hash|ie_value"
                parts = value.split("|")
                if len(parts) >= 3:
                    model, file_hash, ie_str = parts[0], parts[1], parts[2]
                    m._on_apply_vibe_from_storage(model, file_hash, "", float(ie_str))
            # 변경 후 상태 브로드캐스트
            state = self._read_vibe_transfer()
            if state:
                self._broadcast_json(state)
        except Exception as e:
            print(f"🌐 Remote: vibe_transfer 설정 실패 — {key}{'(image)' if key == 'upload_image' else ''}: {e}")
        finally:
            self.app_context.stealth_mode = prev_stealth

    # ── Wildcard Module ──

    def _read_wildcard(self) -> dict:
        """와일드카드 모듈 상태 읽기"""
        try:
            m = self._find_module("wildcard")
            if not m:
                return {}
            # 히스토리 엔트리
            history = []
            ctx = self.app_context.current_prompt_context
            if ctx and ctx.wildcard_history:
                for name, values in ctx.wildcard_history.items():
                    history.append({"name": name, "value": values[-1]})
            # 순차/종속 상태
            state_lines = []
            if ctx and ctx.wildcard_state:
                for name, state in ctx.wildcard_state.items():
                    state_lines.append({"name": name, "current": state['current'], "total": state['total']})
            # 인스턴트 와일드카드 그룹 정보
            instant_groups = []
            iw_module = self._find_module("instant_wildcard")
            if iw_module:
                try:
                    flat_dict, tree = iw_module.get_wildcards()
                    for fname, items in tree.items():
                        group_name = fname.replace('.json', '') if fname.endswith('.json') else fname
                        keys = list(items.keys())
                        instant_groups.append({"name": group_name, "count": len(keys), "keys": keys[:20]})
                except Exception:
                    pass
            return {
                "type": "module_state",
                "module_id": "wildcard",
                "history": history,
                "state": state_lines,
                "prompt_squeeze": getattr(self.app_context, 'prompt_squeeze_enabled', True),
                "wildcard_count": len(self.app_context.wildcard_manager.wildcard_dict_tree),
                "instant_groups": instant_groups,
            }
        except Exception as e:
            print(f"🌐 Remote: wildcard 상태 읽기 실패: {e}")
            return {}

    def _set_wildcard(self, key: str, value: str):
        """와일드카드 모듈 파라미터 설정"""
        try:
            m = self._find_module("wildcard")
            if not m:
                return
            if key == "prompt_squeeze":
                if hasattr(m, 'prompt_squeeze_checkbox') and m.prompt_squeeze_checkbox:
                    m.prompt_squeeze_checkbox.setChecked(value == "true")
            elif key == "reload":
                m.reload_wildcards()
                state = self._read_wildcard()
                if state:
                    self._broadcast_json(state)
                return
            elif key == "reset_sequential":
                m.reset_sequential_wildcards()
                state = self._read_wildcard()
                if state:
                    self._broadcast_json(state)
                return
            elif key == "open_manager":
                m.open_wildcard_manager()
                return
            elif key == "get_file_tree":
                tree = self._scan_wildcard_tree()
                self._broadcast_json({"type": "wildcard_manager", "action": "file_tree", "tree": tree})
                return
            elif key == "read_file":
                content = self._read_wildcard_file(value)
                if content is not None:
                    self._broadcast_json({"type": "wildcard_manager", "action": "file_content", "path": value, "content": content})
                return
            elif key == "save_file":
                import json as _json
                try:
                    data = _json.loads(value)
                except (ValueError, TypeError):
                    print("🌐 Remote: wildcard save_file — 잘못된 JSON")
                    return
                self._save_wildcard_file(data.get("path", ""), data.get("content", ""))
                return
            elif key == "delete_file":
                self._delete_wildcard_file(value)
                return
            elif key == "create_file":
                self._create_wildcard_file(value)
                return
            elif key == "preview_wildcard":
                result = self._preview_wildcard(value)
                self._broadcast_json({"type": "wildcard_manager", "action": "preview_result", "name": value, "result": result})
                return
            # 일반 파라미터 변경 시 상태 브로드캐스트
            state = self._read_wildcard()
            if state:
                self._broadcast_json(state)
        except Exception as e:
            print(f"🌐 Remote: wildcard 설정 실패 — {key}: {e}")

    def _scan_wildcard_tree(self) -> list:
        """와일드카드 디렉토리 트리 스캔"""
        from pathlib import Path
        wm = self.app_context.wildcard_manager
        base = Path(wm.wildcards_dir)
        if not base.exists():
            return []
        tree = []
        try:
            for item in sorted(base.iterdir()):
                if item.name.startswith('.'):
                    continue
                if item.is_dir():
                    folder = {"name": item.name, "type": "folder", "files": []}
                    for f in sorted(item.rglob("*.txt")):
                        try:
                            lines = len(f.read_text(encoding='utf-8').splitlines())
                        except Exception:
                            lines = 0
                        rel = str(f.relative_to(base)).replace('\\', '/')
                        folder["files"].append({"name": f.name, "path": rel, "lines": lines})
                    if folder["files"]:
                        tree.append(folder)
                elif item.suffix == '.txt':
                    try:
                        lines = len(item.read_text(encoding='utf-8').splitlines())
                    except Exception:
                        lines = 0
                    tree.append({"name": item.name, "type": "file", "path": item.name, "lines": lines})
        except Exception as e:
            print(f"🌐 Remote: wildcard tree 스캔 실패: {e}")
        return tree

    def _validate_wildcard_path(self, rel_path: str) -> 'Path | None':
        """상대 경로를 검증하고 절대 경로 반환 (경로 탈출 방지)"""
        from pathlib import Path
        wm = self.app_context.wildcard_manager
        base = Path(wm.wildcards_dir).resolve()
        target = (base / rel_path).resolve()
        try:
            target.relative_to(base)
        except ValueError:
            print(f"🌐 Remote: 경로 탈출 시도 차단 — {rel_path}")
            return None
        return target

    def _read_wildcard_file(self, rel_path: str) -> str | None:
        """와일드카드 파일 읽기"""
        target = self._validate_wildcard_path(rel_path)
        if not target or not target.is_file() or target.suffix != '.txt':
            return None
        try:
            return target.read_text(encoding='utf-8')
        except Exception as e:
            print(f"🌐 Remote: wildcard 파일 읽기 실패 — {rel_path}: {e}")
            return None

    def _save_wildcard_file(self, rel_path: str, content: str):
        """와일드카드 파일 저장 + 리로드"""
        if not rel_path.endswith('.txt'):
            return
        target = self._validate_wildcard_path(rel_path)
        if not target:
            return
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding='utf-8')
            self.app_context.wildcard_manager.reload_wildcards()
            # 트리 + 내용 갱신
            tree = self._scan_wildcard_tree()
            self._broadcast_json({"type": "wildcard_manager", "action": "file_tree", "tree": tree})
            self._broadcast_json({"type": "wildcard_manager", "action": "file_content", "path": rel_path, "content": content})
            self._broadcast_json({"type": "wildcard_manager", "action": "save_ok", "path": rel_path})
        except Exception as e:
            print(f"🌐 Remote: wildcard 파일 저장 실패 — {rel_path}: {e}")

    def _delete_wildcard_file(self, rel_path: str):
        """와일드카드 파일 삭제 + 리로드"""
        target = self._validate_wildcard_path(rel_path)
        if not target or not target.is_file() or target.suffix != '.txt':
            return
        try:
            target.unlink()
            self.app_context.wildcard_manager.reload_wildcards()
            tree = self._scan_wildcard_tree()
            self._broadcast_json({"type": "wildcard_manager", "action": "file_tree", "tree": tree})
            self._broadcast_json({"type": "wildcard_manager", "action": "file_deleted", "path": rel_path})
        except Exception as e:
            print(f"🌐 Remote: wildcard 파일 삭제 실패 — {rel_path}: {e}")

    def _create_wildcard_file(self, rel_path: str):
        """빈 와일드카드 파일 생성"""
        if not rel_path.endswith('.txt'):
            rel_path += '.txt'
        target = self._validate_wildcard_path(rel_path)
        if not target:
            return
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                target.write_text('', encoding='utf-8')
            self.app_context.wildcard_manager.reload_wildcards()
            tree = self._scan_wildcard_tree()
            self._broadcast_json({"type": "wildcard_manager", "action": "file_tree", "tree": tree})
            self._broadcast_json({"type": "wildcard_manager", "action": "file_content", "path": rel_path.replace('\\', '/'), "content": ""})
        except Exception as e:
            print(f"🌐 Remote: wildcard 파일 생성 실패 — {rel_path}: {e}")

    def _preview_wildcard(self, name: str) -> str:
        """와일드카드 확장 미리보기 (5회)"""
        import random
        wm = self.app_context.wildcard_manager
        entries = list(wm.wildcard_dict_tree.get(name, []))  # 스냅샷
        if not entries:
            return f"Wildcard '{name}' not found"
        weights = [w for w, _ in entries]
        texts = [t for _, t in entries]
        results = [random.choices(texts, weights=weights, k=1)[0] for _ in range(5)]
        return '\n'.join(f"#{i+1}: {r}" for i, r in enumerate(results))

    def _disable_all_vibe_frames(self):
        """Vibe Transfer 전체 프레임 비활성 + 상태 브로드캐스트"""
        try:
            vm = self._find_module("vibe_transfer")
            if not vm:
                return
            changed = False
            for f in vm.vibe_frames:
                if f.is_enabled:
                    f.enable_check.setChecked(False)
                    changed = True
            if changed:
                state = self._read_vibe_transfer()
                if state:
                    self._broadcast_json(state)
        except Exception:
            pass

    def _disable_all_char_ref_frames(self):
        """Character Reference 전체 프레임 비활성 + 상태 브로드캐스트"""
        try:
            cm = self._find_module("character_reference")
            if not cm:
                return
            changed = False
            for f in cm.character_frames:
                if f.is_enabled:
                    f.enable_check.setChecked(False)
                    changed = True
            if changed:
                state = self._read_character_reference()
                if state:
                    self._broadcast_json(state)
        except Exception:
            pass

    def _scan_char_ref_storage(self) -> dict:
        """Character Reference Storage 스캔 → 썸네일 목록 반환"""
        try:
            from PIL import Image
            items = []
            images_folder = Path("save/character_reference/images")
            metadata_folder = Path("save/character_reference/metadata")
            if not images_folder.exists():
                return {"type": "storage_list", "module_id": "character_reference", "items": []}
            image_files = sorted(images_folder.glob("*.png"), key=lambda x: x.stat().st_mtime, reverse=True)
            for img_file in image_files[:50]:  # 최대 50개
                file_hash = img_file.stem
                # 메타데이터 로드
                char_name = ""
                meta_path = metadata_folder / f"{file_hash}.json"
                if meta_path.exists():
                    try:
                        with open(meta_path, 'r', encoding='utf-8') as f:
                            meta = json.load(f)
                        char_name = meta.get("character_name", "")
                    except Exception:
                        pass
                # 썸네일
                thumb = ""
                try:
                    pil = Image.open(img_file)
                    thumb = self._generate_thumbnail_b64(pil)
                except Exception:
                    pass
                items.append({
                    "file_hash": file_hash,
                    "file_name": img_file.name,
                    "character_name": char_name,
                    "thumbnail": thumb,
                })
            return {"type": "storage_list", "module_id": "character_reference", "items": items}
        except Exception as e:
            print(f"🌐 Remote: char_ref storage 스캔 실패 — {e}")
            return {"type": "storage_list", "module_id": "character_reference", "items": []}

    def _scan_vibe_storage(self) -> dict:
        """Vibe Transfer Storage 스캔 → 모델별 썸네일 목록 반환"""
        try:
            from PIL import Image
            models = {}
            vibe_folder = Path("save/vibe_transfer")
            if not vibe_folder.exists():
                return {"type": "storage_list", "module_id": "vibe_transfer", "models": {}}
            # 현재 모델 확인
            current_model = ""
            try:
                m = self._find_module("vibe_transfer")
                if m and hasattr(m, '_get_current_model'):
                    current_model = m._get_current_model()
            except Exception:
                pass
            for model_dir in sorted(vibe_folder.iterdir()):
                if not model_dir.is_dir():
                    continue
                model_name = model_dir.name
                items = []
                images_folder = model_dir / "images"
                for json_file in sorted(model_dir.glob("*.json"))[:50]:
                    try:
                        with open(json_file, 'r', encoding='utf-8') as f:
                            data = json.load(f)
                        if data.get("volatile", False):
                            continue
                        file_hash = data.get("file_hash", json_file.stem)
                        file_name = data.get("file_name", "Unknown")
                        encodings = data.get("encodings", {})
                        encoding_keys = [float(k) for k in encodings.keys()]
                        # 썸네일
                        thumb = ""
                        image_path = images_folder / f"{file_hash}.png"
                        if image_path.exists():
                            try:
                                pil = Image.open(image_path)
                                thumb = self._generate_thumbnail_b64(pil)
                            except Exception:
                                pass
                        items.append({
                            "file_hash": file_hash,
                            "file_name": file_name,
                            "encoding_keys": encoding_keys,
                            "thumbnail": thumb,
                        })
                    except Exception:
                        continue
                if items:
                    models[model_name] = items
            return {
                "type": "storage_list",
                "module_id": "vibe_transfer",
                "models": models,
                "current_model": current_model,
            }
        except Exception as e:
            print(f"🌐 Remote: vibe storage 스캔 실패 — {e}")
            return {"type": "storage_list", "module_id": "vibe_transfer", "models": {}}

    # --- 한글 태그 (KR_tags) ---

    def _load_kr_tags(self):
        """ui/interactive/interactive (JSON) 로드 + 고속 인덱스 빌드 (최초 1회, 스레드 안전)"""
        if self._kr_tags_loaded:
            return
        with self._kr_tags_lock:
            if self._kr_tags_loaded:
                return
            import os
            path = 'ui/interactive/interactive'
            try:
                if not os.path.exists(path):
                    print(f"🌐 Remote: tag data not found at {path}")
                    self._kr_tags_loaded = True
                    return
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                # NAI 이스케이프 정규화 헬퍼
                def _norm(s):
                    return s.replace('\\(', '(').replace('\\)', ')') if s else s
                # --- Source 0: interactive (가장 풍부한 데이터) ---
                raw = {}
                for tag, info in data.items():
                    kw_str = info.get('keywords_kr', '')
                    tag_n = _norm(tag)
                    raw[tag_n.lower()] = {
                        **info,
                        '_tag': tag_n,
                        '_src': 0,
                        '_kw_lower': kw_str.replace('<', '').replace('>', '').lower() if kw_str else '',
                        '_desc_lower': info.get('description', '').lower(),
                    }
                src0 = len(raw)
                # --- Source 1-2: KR_tags / e621 parquet fallback ---
                pq_sources = [
                    ('data/KR_tags.parquet', 1),
                    ('data/e621_KR_tags.parquet', 2),
                ]
                pq_stats = merge_parquet_tag_records(raw, pq_sources)
                override_stats = apply_translation_overrides(raw, 'data/tag_index/tag_translation_overrides.json')
                for err in pq_stats.errors + override_stats.errors:
                    print(f"🌐 Remote: tag metadata merge warning — {err}")
                # --- Source 3-10: prompt engineering filter lists (그룹 소속만) ---
                filter_sources = [
                    ('data/characteristic_list.txt', 3, '특징'),
                    ('data/clothes_list.txt', 4, '의상'),
                    ('data/taglist/expression_tags.json', 5, '표정'),
                    ('data/taglist/pose_action_tags.json', 6, '자세/행동'),
                    ('data/taglist/location_tags.json', 7, '장소'),
                    ('data/taglist/meta_tags.json', 8, '메타'),
                    ('data/taglist/object_tags.json', 9, '물체'),
                    ('data/color.txt', 10, '색상'),
                ]
                filter_count = 0
                for fpath, src_key, group_name in filter_sources:
                    if not os.path.exists(fpath):
                        continue
                    try:
                        tags = []
                        if fpath.endswith('.json'):
                            with open(fpath, 'r', encoding='utf-8') as f:
                                jdata = json.load(f)
                            # JSON taglist 구조 파싱: tags/modifiers/groups/categories/uncategorized
                            if isinstance(jdata, dict):
                                collected = []
                                for key in ('tags', 'modifiers', 'uncategorized'):
                                    v = jdata.get(key, [])
                                    if isinstance(v, list):
                                        collected.extend(v)
                                for key in ('groups', 'categories'):
                                    v = jdata.get(key, {})
                                    if isinstance(v, dict):
                                        for sub_tags in v.values():
                                            if isinstance(sub_tags, list):
                                                collected.extend(sub_tags)
                                tags = collected
                            else:
                                tags = jdata
                        else:
                            with open(fpath, 'r', encoding='utf-8') as f:
                                tags = [line.strip() for line in f if line.strip()]
                        for tag_raw in tags:
                            tag_n = _norm(tag_raw.replace('_', ' '))
                            tag_lower = tag_n.lower()
                            if tag_lower in raw:
                                continue
                            raw[tag_lower] = {
                                '_tag': tag_n, '_src': src_key,
                                'freq': 0, 'description': '', 'group': group_name,
                                'subgroup': '', 'keywords_kr': '',
                                '_kw_lower': '', '_desc_lower': '',
                            }
                            filter_count += 1
                    except Exception as e:
                        print(f"🌐 Remote: filter {fpath} 로드 실패 — {e}")
                # --- Source 11-13: artist / character / copyright dicts ---
                dict_sources = [
                    ('artist_dictionary', 'artist_dict', 11, 'artist'),
                    ('danbooru_character', 'character_dict_count', 12, 'character'),
                    ('result_dict_copyright', 'copyright_dict', 13, 'copyright'),
                ]
                dict_count = 0
                for mod_name, var_name, src_key, cat in dict_sources:
                    try:
                        import importlib
                        mod = importlib.import_module(mod_name)
                        d = getattr(mod, var_name, {})
                        for tag_raw, freq in d.items():
                            # NAI 이스케이프 정규화: \( → (, \) → )
                            tag_norm = tag_raw.replace('\\(', '(').replace('\\)', ')')
                            tag_lower = tag_norm.lower()
                            if tag_lower in raw:
                                # 기존 엔트리에 cat만 보강
                                if '_cat' not in raw[tag_lower]:
                                    raw[tag_lower]['_cat'] = cat
                                continue
                            raw[tag_lower] = {
                                '_tag': tag_norm, '_src': src_key, '_cat': cat,
                                'freq': int(freq) if isinstance(freq, (int, float)) else 0,
                                'description': '', 'group': cat,
                                'subgroup': '', 'keywords_kr': '',
                                '_kw_lower': '', '_desc_lower': '',
                            }
                            dict_count += 1
                    except Exception as e:
                        print(f"🌐 Remote: dict {mod_name} 로드 실패 — {e}")
                self._kr_tags_raw = raw
                try:
                    self._tag_search_index = TagSearchIndex.from_raw_tag_records(raw)
                    self._tag_relation_ranker = TagRelationRanker(raw)
                except Exception as e:
                    self._tag_search_index = None
                    self._tag_relation_ranker = None
                    print(f"🌐 Remote: shared tag index build failed — {e}")
                print(
                    "🌐 Remote: tag index — "
                    f"{src0} interactive + {pq_stats.added} parquet "
                    f"+ {pq_stats.records_updated} KR merges "
                    f"(desc fill {pq_stats.description_filled}, desc replace {pq_stats.description_replaced}, "
                    f"kw fill {pq_stats.keywords_filled}, kw replace {pq_stats.keywords_replaced}) "
                    f"+ {override_stats.applied} overrides + {filter_count} filter + {dict_count} dict = {len(raw)} total"
                )
                self._kr_tags_loaded = True
            except Exception as e:
                self._kr_tags_loaded = True
                print(f"🌐 Remote: tag index 로드 실패 — {e}")

    def _load_char_analysis(self):
        """character_analysis.json → 역인덱스 구축 + _kr_tags_raw 누락 캐릭터 보강"""
        if self._char_analysis:
            return
        try:
            analysis_path = Path(__file__).resolve().parent.parent / "data" / "character_analysis.json"
            if not analysis_path.exists():
                print("🌐 Remote: character_analysis.json 없음 — 캐릭터 상세 비활성")
                return
            with open(analysis_path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            idx = {}
            backfill_count = 0
            alias_count = 0
            for group_key, chars in raw.items():
                for char_name, data in chars.items():
                    cl = char_name.lower()
                    total = data.get("total_rows", 0)
                    # 동명 캐릭터 → total_rows 높은 쪽 우선
                    if cl in idx and idx[cl][1].get("total_rows", 0) >= total:
                        continue
                    idx[cl] = (group_key, data)
                    # _kr_tags_raw에 없는 캐릭터 → character로 역등록
                    if self._kr_tags_raw and cl not in self._kr_tags_raw:
                        self._kr_tags_raw[cl] = {
                            '_tag': char_name, '_src': 14, '_cat': 'character',
                            'freq': total, 'description': '',
                            'group': 'character', 'subgroup': group_key,
                            'keywords_kr': '', '_kw_lower': '', '_desc_lower': '',
                        }
                        backfill_count += 1
                    # 괄호 포함 이름 → base name(괄호 제거)도 역인덱스에 등록
                    if '(' in char_name:
                        base = char_name.split('(')[0].strip().lower()
                        if base and base != cl:
                            if base not in idx or idx[base][1].get("total_rows", 0) < total:
                                idx[base] = (group_key, data)
                                alias_count += 1
                                # base name도 _kr_tags_raw에 등록
                                if self._kr_tags_raw and base not in self._kr_tags_raw:
                                    self._kr_tags_raw[base] = {
                                        '_tag': char_name.split('(')[0].strip(),
                                        '_src': 14, '_cat': 'character',
                                        'freq': total, 'description': '',
                                        'group': 'character', 'subgroup': group_key,
                                        'keywords_kr': '', '_kw_lower': '', '_desc_lower': '',
                                    }
            self._char_analysis = idx
            print(f"🌐 Remote: character_analysis — {len(idx)} indexed, {backfill_count} backfilled to tags, {alias_count} base-name aliases")
        except Exception as e:
            print(f"🌐 Remote: character_analysis 로드 실패 — {e}")

    def _search_kr_tags(self, query: str, limit: int = 20) -> list:
        """5단계 우선순위 태그 검색: exact → starts_with → kr_keyword → contains → desc
        prefix 라우팅: 'artist:x' → artist만, 'character:x' → character만"""
        self._load_kr_tags()
        if not self._kr_tags_raw:
            return []
        query = query.strip()
        if not query:
            return []
        # prefix 라우팅 (@artist → artist: 변환 포함)
        cat_filter = None
        ql = query.lower()
        if ql.startswith('@'):
            cat_filter = 'artist'
            ql = ql[1:]
        else:
            for pfx in ('artist:', 'character:'):
                if ql.startswith(pfx):
                    cat_filter = pfx[:-1]  # 'artist' or 'character'
                    ql = ql[len(pfx):]
                    break
        if not ql:
            return []
        if self._tag_search_index is not None:
            cats = {cat_filter} if cat_filter else None
            matches = self._tag_search_index.search(ql, limit=limit, cats=cats)
            return [
                {
                    "tag": result.tag,
                    "count": result.entry.freq,
                    "desc": result.entry.desc,
                    "group": result.entry.category,
                    "cat": result.entry.cat,
                }
                for result in matches
            ]

        exact, starts, kr_kw, contains, desc_m = [], [], [], [], []
        for tag_lower, info in self._kr_tags_raw.items():
            cat = info.get('_cat', '')
            if cat_filter and cat != cat_filter:
                continue
            tag = info['_tag']
            freq = info.get('freq', 0)
            d = info.get('description', '')
            g = info.get('group', '')
            entry = {"tag": tag, "count": freq, "desc": d, "group": g, "cat": cat}
            # prefix 검색 시 tag_lower에서 prefix 제거하여 매칭
            match_key = tag_lower
            if cat_filter and match_key.startswith(cat_filter + ':'):
                match_key = match_key[len(cat_filter) + 1:]
            if match_key == ql:
                exact.append(entry)
                continue
            if match_key.startswith(ql):
                starts.append(entry)
                continue
            kw_lower = info.get('_kw_lower', '')
            if kw_lower and ql in kw_lower:
                kr_kw.append(entry)
                continue
            if ql in match_key:
                contains.append(entry)
                continue
            if d and len(ql) >= 3 and ql in info.get('_desc_lower', ''):
                desc_m.append(entry)
        for grp in [exact, starts, kr_kw, contains, desc_m]:
            grp.sort(key=lambda x: x['count'], reverse=True)
        return (exact + starts + kr_kw + contains + desc_m)[:limit]

    def _search_wildcards(self, query: str, limit: int = 12) -> list:
        """와일드카드 이름 검색 (__name__ 용)"""
        try:
            wm = self.app_context.wildcard_manager
            q = query.lower().strip()
            if not q:
                return []
            results = []
            # 스냅샷으로 스레드 안전 순회
            tree_snapshot = dict(wm.wildcard_dict_tree)
            for key, entries in tree_snapshot.items():
                kl = key.lower()
                if q in kl:
                    results.append({
                        "tag": key,
                        "count": len(entries),
                        "desc": f"{len(entries)} entries",
                        "group": "wildcard",
                        "cat": "",
                        "_wc_type": "wildcard",
                    })
            # exact/startswith 우선
            exact = [r for r in results if r['tag'].lower() == q]
            starts = [r for r in results if r['tag'].lower().startswith(q) and r not in exact]
            rest = [r for r in results if r not in exact and r not in starts]
            return (exact + starts + rest)[:limit]
        except Exception as e:
            print(f"🌐 Remote: wildcard 검색 실패: {e}")
            return []

    def _read_chunk(self) -> dict:
        """Chunk 모듈: 인스턴트 와일드카드 트리 전체 반환"""
        try:
            iw_module = self._find_module("instant_wildcard")
            if not iw_module:
                return {"type": "module_state", "module_id": "chunk", "groups": []}
            flat_dict, tree = iw_module.get_wildcards()
            groups = []
            for fname, items in tree.items():
                group_name = fname.replace('.json', '') if fname.endswith('.json') else fname
                group_items = []
                for key, value in items.items():
                    group_items.append({"key": key, "value": value})
                groups.append({"name": group_name, "items": group_items})
            return {"type": "module_state", "module_id": "chunk", "groups": groups}
        except Exception as e:
            print(f"🌐 Remote: chunk 읽기 실패: {e}")
            return {"type": "module_state", "module_id": "chunk", "groups": []}

    def _lookup_tag_info(self, tag: str) -> dict:
        """정확한 태그명으로 상세 정보 + relations 조회"""
        self._load_kr_tags()
        if not self._kr_tags_raw:
            return {}
        tag_lower = tag.strip().lower()
        info = self._kr_tags_raw.get(tag_lower)
        if not info:
            return {}
        result = {
            "tag": info['_tag'], "count": info.get('freq', 0),
            "desc": info.get('description', ''),
            "group": info.get('group', ''),
            "subgroup": info.get('subgroup', ''),
            "cat": info.get('_cat', ''),
        }
        rels = info.get('relations', {})
        parents = rels.get('parent', [])
        if isinstance(parents, str):
            parents = [parents]
        if self._tag_relation_ranker is not None:
            parents = self._tag_relation_ranker.valid_implications(tag_lower, info, limit=8)
        if parents:
            result['implications'] = parents[:8]
        if self._tag_relation_ranker is not None:
            related = self._tag_relation_ranker.rank_related(tag_lower, info, limit=8)
        else:
            siblings = rels.get('siblings', [])
            if isinstance(siblings, str):
                siblings = [siblings]
            word_match = rels.get('word_match', [])
            if isinstance(word_match, str):
                word_match = [word_match]
            related = []
            seen = set(parents)
            for t in siblings + word_match:
                if t not in seen:
                    seen.add(t)
                    related.append(t)
        if related:
            result['related'] = related[:8]
        extra_tags = list(result.get('implications', [])) + list(result.get('related', []))
        if extra_tags:
            extra_tag_info = {}
            for extra_tag in extra_tags:
                extra_key = str(extra_tag).strip().lower()
                extra_info = self._kr_tags_raw.get(extra_key)
                if not extra_info:
                    continue
                extra_tag_info[str(extra_tag)] = {
                    "tag": extra_info.get('_tag', str(extra_tag)),
                    "count": extra_info.get('freq', 0),
                    "desc": extra_info.get('description', ''),
                    "group": extra_info.get('group', ''),
                    "subgroup": extra_info.get('subgroup', ''),
                    "cat": extra_info.get('_cat', ''),
                }
            if extra_tag_info:
                result['extra_tag_info'] = extra_tag_info
        # 캐릭터 태그 → character_analysis 상세 정보 추가
        if result.get('cat') == 'character' and self._char_analysis:
            match = self._char_analysis.get(tag_lower)
            if match:
                gk, cdata = match
                # breast_size: distribution 최빈값
                bs_top = ""
                bs_dist = cdata.get("breast_size", {}).get("distribution", [])
                if bs_dist:
                    top_entry = max(bs_dist, key=lambda x: x.get("pct", 0))
                    bs_top = top_entry.get("tag", "")
                result['character_details'] = {
                    'copyright': gk,
                    'personal_color': cdata.get('personal_color', []),
                    'characteristics': cdata.get('characteristics', []),
                    'breast_size_top': bs_top,
                    'total_rows': cdata.get('total_rows', 0),
                }
        return result

    # --- 검색 시스템 ---

    def _read_search_state(self) -> dict:
        """검색 상태 + 커스텀 parquet 목록 반환"""
        try:
            mw = self.app_context.main_window
            if not mw:
                return {}
            count = mw.search_results.get_count() if mw.search_results else 0
            # 현재 검색 파라미터
            query = mw.search_input.text() if hasattr(mw, 'search_input') else ""
            exclude = mw.exclude_input.text() if hasattr(mw, 'exclude_input') else ""
            ratings = {}
            if hasattr(mw, 'rating_checkboxes'):
                for k in ('e', 'q', 's', 'g'):
                    cb = mw.rating_checkboxes.get(k)
                    ratings[k] = cb.isChecked() if cb else True
            # 커스텀 parquet 파일 목록
            custom_dir = Path("save/custom_tags")
            parquets = []
            if custom_dir.exists():
                parquets = sorted([f.name for f in custom_dir.glob("*.parquet")])
            # Rating별 카운트 breakdown (master에서 — 필터 전 전체 기준)
            rating_counts = {}
            filtered_count = count
            master = getattr(mw, '_master_filter_snapshot', None)
            if master is not None and not master.empty and 'rating' in master.columns:
                rating_counts = {r: int((master['rating'] == r).sum()) for r in 'gsqe'}
                filtered_count = count  # 이미 하드 필터된 search_results의 count
            elif mw.search_results and hasattr(mw.search_results, 'get_count_by_rating'):
                rating_counts = mw.search_results.get_count_by_rating()
                filtered_count = mw.search_results.get_filtered_count(self._active_ratings)
            return {
                "type": "search_state",
                "count": filtered_count,
                "total_count": count,
                "rating_counts": rating_counts,
                "active_ratings": list(self._active_ratings),
                "query": query,
                "exclude": exclude,
                "ratings": ratings,
                "parquets": parquets,
            }
        except Exception as e:
            print(f"🌐 Remote: search 상태 읽기 실패 — {e}")
            return {}

    def _do_search(self, params_json: str):
        """검색 실행"""
        try:
            params = json.loads(params_json)
            mw = self.app_context.main_window
            if not mw:
                return
            # 검색 파라미터 UI에 반영
            if hasattr(mw, 'search_input'):
                mw.search_input.setText(params.get("query", ""))
            if hasattr(mw, 'exclude_input'):
                mw.exclude_input.setText(params.get("exclude", ""))
            if hasattr(mw, 'rating_checkboxes'):
                for k in ('e', 'q', 's', 'g'):
                    cb = mw.rating_checkboxes.get(k)
                    if cb:
                        # Remote: 항상 전체 rating 포함 검색 (소비 시점에 GSQE로 필터)
                        cb.setChecked(True)
            # active_ratings 갱신: 클라이언트가 보낸 rating 상태 반영
            self._active_ratings = set(
                k for k in 'gsqe' if params.get(f"rating_{k}", True)
            )
            # 검색 실행
            mw.trigger_search()
        except Exception as e:
            print(f"🌐 Remote: search 실행 실패 — {e}")

    def _do_load_parquet(self, filename: str):
        """커스텀 parquet 로드"""
        try:
            import pandas as pd
            mw = self.app_context.main_window
            if not mw:
                return
            file_path = Path("save/custom_tags") / filename
            if not file_path.exists():
                return
            df = pd.read_parquet(file_path)
            mw.search_results.set_dataframe(df)
            if hasattr(mw, '_save_search_snapshot'):
                mw._save_search_snapshot()
            count = mw.search_results.get_count()
            # UI 레이블 업데이트
            if hasattr(mw, 'result_label1'):
                mw.result_label1.setText(f"검색: {count}")
            if hasattr(mw, 'result_label2'):
                mw.result_label2.setText(f"남음: {count}")
            # 웹 클라이언트에 전체 상태 전송
            state = self._read_search_state()
            if state:
                state["loaded"] = filename
                self._broadcast_json(state)
        except Exception as e:
            print(f"🌐 Remote: parquet 로드 실패 — {e}")

    def _on_search_progress(self, completed: int, total: int):
        """검색 진행률 브로드캐스트"""
        self._broadcast_json({
            "type": "search_progress",
            "completed": completed,
            "total": total,
        })

    def _on_search_complete(self, total_count: int):
        """검색 완료 시 전체 상태 브로드캐스트"""
        state = self._read_search_state()
        if state:
            self._broadcast_json(state)

    # --- 심층검색 ---

    def _find_depth_tab(self):
        """열려있는 DepthSearchWindow 인스턴스 반환"""
        mw = getattr(self.app_context, 'main_window', None)
        if not mw:
            return None
        iw = getattr(mw, 'image_window', None)
        if not iw:
            return None
        tc = getattr(iw, 'tab_controller', None)
        if not tc:
            return None
        for tab in tc.module_instances.values():
            if tab.__class__.__name__ == 'DepthSearchTabModule':
                return tab.widget  # DepthSearchWindow 인스턴스
        return None

    def _read_depth_state(self) -> dict:
        try:
            dw = self._find_depth_tab()
            if not dw:
                return {"type": "depth_state", "open": False}
            count = dw.current_model.get_count() if dw.current_model else 0
            original = dw.original_model.get_count() if dw.original_model else 0
            # 레이팅 상태
            ratings = {}
            if hasattr(dw, 'd_rating_checkboxes'):
                for k in ('e', 'q', 's', 'g'):
                    cb = dw.d_rating_checkboxes.get(k)
                    ratings[k] = cb.isChecked() if cb else True
            # 숫자 필터 상태
            filters = {}
            for name in ('token_min', 'token_max', 'id_min', 'id_max', 'score_min'):
                check = getattr(dw, f'{name}_check', None)
                inp = getattr(dw, f'{name}_input', None)
                if check and inp:
                    filters[name] = {"enabled": check.isChecked(), "value": inp.text()}
            # 캐릭터 필터
            filters['rem_char'] = getattr(dw, 'rem_char_check', None) and dw.rem_char_check.isChecked()
            filters['only_empty_char'] = getattr(dw, 'only_empty_char_check', None) and dw.only_empty_char_check.isChecked()
            # 스테이징 상태
            staging_count = len(dw.staged_items) if hasattr(dw, 'staged_items') else 0
            return {
                "type": "depth_state",
                "open": True,
                "count": count,
                "original": original,
                "query": dw.d_search_input.text() if hasattr(dw, 'd_search_input') else "",
                "exclude": dw.d_exclude_input.text() if hasattr(dw, 'd_exclude_input') else "",
                "ratings": ratings,
                "filters": filters,
                "staging_count": staging_count,
            }
        except Exception as e:
            print(f"🌐 Remote: depth 상태 읽기 실패 — {e}")
            return {"type": "depth_state", "open": False}

    def _do_depth_action(self, params_json: str):
        try:
            params = json.loads(params_json)
            action = params.get("action", "")
            mw = self.app_context.main_window
            # 원격 호출 중 QMessageBox 억제
            prev_stealth = getattr(self.app_context, 'stealth_mode', False)
            self.app_context.stealth_mode = True

            if action == "open":
                # 심층검색 탭 열기 (이미 열려있으면 switch만 됨)
                if mw and hasattr(mw, 'open_depth_search_tab'):
                    # 검색 결과 없으면 열 수 없음 → 즉시 피드백
                    if hasattr(mw, 'search_results') and mw.search_results.is_empty():
                        self._broadcast_json({
                            "type": "depth_state", "open": False,
                            "error": "no_search_results"
                        })
                        return
                    mw.open_depth_search_tab()
                    # 이미 열려있으면 tab_added 미발생 → 직접 브로드캐스트
                    # 새로 열리면 tab_added 시그널로 _on_tab_added에서 브로드캐스트
                    dw = self._find_depth_tab()
                    if dw:
                        self._broadcast_depth_state()
                return

            dw = self._find_depth_tab()
            if not dw:
                self._broadcast_json({"type": "depth_state", "open": False})
                return

            if action == "filter":
                if hasattr(dw, 'd_search_input'):
                    dw.d_search_input.setText(params.get("query", ""))
                if hasattr(dw, 'd_exclude_input'):
                    dw.d_exclude_input.setText(params.get("exclude", ""))
                # 레이팅 필터
                ratings = params.get("ratings", {})
                if hasattr(dw, 'd_rating_checkboxes'):
                    for k in ('e', 'q', 's', 'g'):
                        cb = dw.d_rating_checkboxes.get(k)
                        if cb:
                            cb.setChecked(ratings.get(k, True))
                # 숫자 필터 (token, id, score)
                filters = params.get("filters", {})
                for name in ('token_min', 'token_max', 'id_min', 'id_max', 'score_min'):
                    f = filters.get(name)
                    if f is None:
                        continue
                    check = getattr(dw, f'{name}_check', None)
                    inp = getattr(dw, f'{name}_input', None)
                    if check:
                        check.setChecked(f.get("enabled", False))
                    if inp:
                        inp.setText(str(f.get("value", "")))
                # 캐릭터 필터
                if 'rem_char' in filters:
                    cb = getattr(dw, 'rem_char_check', None)
                    if cb:
                        cb.setChecked(bool(filters['rem_char']))
                if 'only_empty_char' in filters:
                    cb = getattr(dw, 'only_empty_char_check', None)
                    if cb:
                        cb.setChecked(bool(filters['only_empty_char']))
                dw.apply_filters()
                self._broadcast_depth_state()

            elif action == "assign":
                dw.assign_results_to_main()
                # 메인 카운트도 갱신
                state = self._read_search_state()
                if state:
                    self._broadcast_json(state)
                self._broadcast_depth_state()

            elif action == "promote":
                dw.promote_current_to_original()
                self._broadcast_depth_state()

            elif action == "restore":
                dw.restore_to_original()
                self._broadcast_depth_state()

            elif action == "stage":
                # 현재 필터 결과를 스테이징에 추가
                dw.add_to_staging()
                self._broadcast_depth_state()

            elif action == "merge_staging":
                # 스테이징 아이템 병합
                dw.merge_staging()
                self._broadcast_depth_state()

            elif action == "clear_staging":
                dw.clear_staging()
                self._broadcast_depth_state()

            elif action == "export":
                # 현재 뷰를 save/custom_tags/에 자동 저장
                if not dw.current_model.is_empty():
                    from datetime import datetime as _dt
                    export_dir = Path("save/custom_tags")
                    export_dir.mkdir(parents=True, exist_ok=True)
                    fname = f"refine_{_dt.now().strftime('%Y%m%d_%H%M%S')}.parquet"
                    path = export_dir / fname
                    dw.current_model.get_dataframe().to_parquet(str(path))
                    print(f"🌐 Remote: depth export → {path}")
                # 내보내기 후 검색 상태도 갱신 (parquet 목록 갱신)
                search_state = self._read_search_state()
                if search_state:
                    self._broadcast_json(search_state)
                self._broadcast_depth_state()

        except Exception as e:
            print(f"🌐 Remote: depth action 실패 — {e}")
        finally:
            self.app_context.stealth_mode = prev_stealth

    def _do_restore_snapshot(self):
        """메인 검색 결과를 복원 — master가 있으면 원본에서 복원 (필터 해제)"""
        try:
            mw = self.app_context.main_window
            if not mw:
                return
            # Master snapshot 존재 → 필터 전 원본에서 복원 + 필터 초기화
            master = getattr(mw, '_master_filter_snapshot', None)
            if master is not None and not master.empty:
                from core.search_result_model import SearchResultModel
                mw.search_results = SearchResultModel(master)
                mw._save_search_snapshot()  # → _reset_remote_filters → 필터 초기화 + master 재설정
            elif hasattr(mw, '_restore_from_snapshot'):
                mw._restore_from_snapshot()
            count = mw.search_results.get_count() if mw.search_results else 0
            if hasattr(mw, 'result_label1'):
                mw.result_label1.setText(f"검색: {count}")
            if hasattr(mw, 'result_label2'):
                mw.result_label2.setText(f"남음: {count}")
            state = self._read_search_state()
            if state:
                self._broadcast_json(state)
        except Exception as e:
            print(f"🌐 Remote: 복원 실패 — {e}")

    def _compute_master_count(self, active_ratings: set) -> dict:
        """master snapshot 기준으로 현재 필터 조합의 카운트 반환 (asyncio.to_thread용)"""
        mw = self.app_context.main_window
        master = getattr(mw, '_master_filter_snapshot', None)
        if master is None or master.empty:
            # Lazy init: 서버 시작 전에 검색이 완료된 경우
            snapshot = getattr(mw, '_search_results_snapshot', None)
            if snapshot is not None and not snapshot.empty:
                master = snapshot.copy()
                mw._master_filter_snapshot = master
            elif mw and mw.search_results and not mw.search_results.is_empty():
                master = mw.search_results.get_dataframe().copy()
                mw._master_filter_snapshot = master
            else:
                return {"count": 0, "rating_counts": {}}
        rc = {r: int((master['rating'] == r).sum()) for r in 'gsqe'} if 'rating' in master.columns else {}
        source = master
        tag_ids = self._active_tag_filter_ids
        if tag_ids and 'id' in source.columns:
            source = source[source['id'].isin(tag_ids)]
        count = int(source['rating'].isin(active_ratings).sum()) if (active_ratings and 'rating' in source.columns) else len(source)
        return {"count": count, "rating_counts": rc}

    def _do_apply_filters(self):
        """GSQE + Tag Filter를 master snapshot에서 재적용 (Non-shared only).
        set_active_ratings / tag_filter_assign / tag_filter_clear 시 호출."""
        if self.shared_server_mode:
            return
        try:
            mw = self.app_context.main_window
            if not mw:
                return
            master = getattr(mw, '_master_filter_snapshot', None)
            if master is None or master.empty:
                # Lazy init: 서버 시작 전에 검색이 완료된 경우
                snapshot = getattr(mw, '_search_results_snapshot', None)
                if snapshot is not None and not snapshot.empty:
                    master = snapshot.copy()
                elif mw.search_results and not mw.search_results.is_empty():
                    master = mw.search_results.get_dataframe().copy()
                if master is None or master.empty:
                    return
                mw._master_filter_snapshot = master

            filtered = master
            # GSQE 필터
            ratings = self._active_ratings
            if ratings and ratings != {'g', 's', 'q', 'e'} and 'rating' in filtered.columns:
                filtered = filtered[filtered['rating'].isin(ratings)]
            # Tag Filter
            tag_ids = self._active_tag_filter_ids
            if tag_ids and 'id' in filtered.columns:
                filtered = filtered[filtered['id'].isin(tag_ids)]

            from core.search_result_model import SearchResultModel
            mw.search_results = SearchResultModel(filtered) if not filtered.empty else SearchResultModel()
            try:
                self._skip_filter_reset = True
                mw._save_search_snapshot()
            finally:
                self._skip_filter_reset = False

            count = mw.search_results.get_count()
            if hasattr(mw, 'result_label1'):
                mw.result_label1.setText(f"검색: {count}")
            if hasattr(mw, 'result_label2'):
                mw.result_label2.setText(f"남음: {count}")
            state = self._read_search_state()
            if state:
                self._broadcast_json(state)
        except Exception as e:
            print(f"🌐 Remote: 필터 적용 실패 — {e}")

    def _reset_remote_filters(self):
        """검색 데이터 교체 시 Remote Session 필터 전체 초기화 (Non-shared only).
        _save_search_snapshot()에서 호출됨 (필터 적용 중에는 _skip_filter_reset으로 우회)."""
        if self.shared_server_mode:
            return
        # GSQE 전체 활성화
        self._active_ratings = {'g', 's', 'q', 'e'}
        self.app_context.remote_active_ratings = None
        # Tag filter 초기화
        self._active_tag_filter_ids = None
        if self._ws_manager:
            for session in self._ws_manager.sessions.values():
                session["tag_filter"] = None
                session["tag_filter_pending"] = None
        # Master snapshot 설정 (현재 search_results = 새로 유입된 비필터 데이터)
        mw = self.app_context.main_window
        if mw and mw.search_results and not mw.search_results.is_empty():
            mw._master_filter_snapshot = mw.search_results.get_dataframe().copy()
        # Web 클라이언트에 filter_reset broadcast
        if not self._has_clients():
            return
        count = mw.search_results.get_count() if mw and mw.search_results else 0
        rc = {}
        if mw and mw.search_results and hasattr(mw.search_results, 'get_count_by_rating'):
            rc = mw.search_results.get_count_by_rating()
        self._broadcast_json({
            "type": "filter_reset",
            "count": count,
            "rating_counts": rc,
        })

    def _on_tab_added(self, tab_id: str, instance):
        """TabController에서 탭 추가 시 호출 — depth tab이면 상태 브로드캐스트"""
        if instance.__class__.__name__ == 'DepthSearchTabModule':
            self._broadcast_depth_state()

    def _broadcast_depth_state(self):
        state = self._read_depth_state()
        if state:
            self._broadcast_json(state)

    # --- AppContext 이벤트 콜백 (Qt 메인 스레드에서 호출됨) ---

    def on_prompt_generated(self, prompt_context):
        """프롬프트 생성 완료 시 WebSocket 전송 + 자동생성 트리거"""
        try:
            # === ComfyUI sync 요청 응답 처리 (ws 기반 auto_ws 스캔보다 먼저) ===
            comfyui_prompt = prompt_context.final_prompt or ""
            comfyui_negative = ""
            try:
                comfyui_negative = self.app_context.main_window.negative_prompt_textedit.toPlainText()
            except Exception:
                pass
            _mw_for_cf = self.app_context.main_window
            comfyui_remaining = (
                _mw_for_cf.search_results.get_count()
                if _mw_for_cf and _mw_for_cf.search_results else 0
            )

            comfyui_keys = [
                k for k in list(self._pending_overrides.keys())
                if isinstance(k, tuple) and len(k) == 2 and k[0] == "comfyui"
            ]
            for ck in comfyui_keys:
                cf_pending = self._pending_overrides.pop(ck, {})
                cf_id = cf_pending.get("comfyui_request_id")
                cf_will_generate = cf_pending.get("auto_generate", False)

                # P.Eng override 능동 reset (id 비교, 다른 세션 값 훼손 방지)
                # 이미지 생성 경로는 generation_controller가 리셋하지만,
                # 프롬프트만 생성되는 경로(force_skip=true + 자동생성 OFF) 안전망.
                _peng_ref = cf_pending.get("_peng_override_ref")
                if _peng_ref is not None and self.app_context.session_p_eng_override is _peng_ref:
                    self.app_context.session_p_eng_override = None

                # NAIA 자체 generate 트리거 (auto_generate=True 인 경우)
                if cf_will_generate:
                    try:
                        gc_cf = _mw_for_cf.generation_controller
                        if not gc_cf.is_generating:
                            gc_cf.execute_generation_pipeline(
                                overrides=cf_pending.get("params"), priority=0,
                            )
                            self._broadcast_json({"type": "status", "is_generating": True})
                    except Exception as e:
                        print(f"🌐 ComfyUI: NAIA generate 실패 — {e}")

                # 추천 해상도 결정 — NAIA 표준 fallback chain 미러:
                # 1) source_row 의 image_width/height (auto_fit_resolution 정책)
                # 2) resolution_combo 에서 random pick (random_resolution 정책,
                #    generation_controller.py:393-399 패턴; 단 setCurrentIndex 미호출 → UI 불변)
                # combo 는 _load_resolutions 가 default 7개 항목을 항상 보장하므로
                # 추가 hardcoded fallback 없음. ComfyUI 경로는 항상 random/auto 켠 효과.
                # NAIA combo 텍스트 포맷: "1024 x 1024" (공백 포함)
                cf_width, cf_height, cf_res_source = None, None, "unknown"
                try:
                    src_row = getattr(prompt_context, "source_row", None)
                    if src_row is not None and "image_width" in src_row and "image_height" in src_row:
                        try:
                            w = int(src_row["image_width"])
                            h = int(src_row["image_height"])
                            if w > 0 and h > 0:
                                cf_width, cf_height, cf_res_source = w, h, "detected"
                        except (ValueError, TypeError):
                            pass
                    if cf_width is None:
                        rc = getattr(_mw_for_cf, "resolution_combo", None)
                        if rc is not None and rc.count() > 0:
                            idx = random.randint(0, rc.count() - 1)
                            text = rc.itemText(idx)
                            try:
                                # NAIA 표준 " x " 우선, 안전망으로 "x" 도 허용
                                sep = " x " if " x " in text else "x"
                                w_str, h_str = text.split(sep)
                                w, h = int(w_str.strip()), int(h_str.strip())
                                cf_width, cf_height, cf_res_source = w, h, "random"
                            except Exception:
                                pass
                except Exception as e:
                    print(f"🌐 ComfyUI: 해상도 결정 실패 — {e}")

                # Future 완료 (HTTP 응답 전송)
                if cf_id:
                    with self._comfyui_requests_lock:
                        cf_future = self._pending_comfyui_requests.pop(cf_id, None)
                    if cf_future is not None and self._loop is not None:
                        cf_payload = {
                            "request_id": cf_id,
                            "prompt": comfyui_prompt,
                            "negative_prompt": comfyui_negative,
                            "naia_started_generation": cf_will_generate,
                            "remaining": comfyui_remaining,
                            "source": "comfyui_random",
                            "width": cf_width,
                            "height": cf_height,
                            "resolution_source": cf_res_source,
                        }
                        # asyncio Future는 event loop 스레드에서 set 해야 안전
                        self._loop.call_soon_threadsafe(
                            lambda f=cf_future, p=cf_payload: (
                                f.set_result(p) if not f.done() else None
                            )
                        )

            # === 기존 ws 기반 auto_generate 처리 ===
            # _pending_overrides에서 auto_generate=True인 항목 찾아 소비
            auto_ws = None
            for ws_key, pending in list(self._pending_overrides.items()):
                if pending.get("auto_generate"):
                    auto_ws = ws_key
                    break

            source = "random"  # 기본값 (메인 UI에서 직접 트리거 시)
            if auto_ws:
                pending = self._pending_overrides.pop(auto_ws, {})
                source = pending.get("source", "random")
                pending_neg = pending.get("negative")
                pending_params = pending.get("params")
                # seed_fixed가 아닌 경우 → 랜덤 시드로 교체
                if pending_params and "seed" in pending_params:
                    if pending_params.get("seed_fixed") != "true":
                        pending_params["seed"] = str(random.randint(0, 9999999999))
                # pending negative 반영
                if pending_neg is not None:
                    if not self.shared_server_mode:
                        self._syncing_prompt = True
                        self.app_context.main_window.negative_prompt_textedit.setPlainText(pending_neg)
                        self._syncing_prompt = False
                    if pending_params is None:
                        pending_params = {}
                    pending_params["negative_prompt"] = pending_neg
                gc = self.app_context.main_window.generation_controller
                if not gc.is_generating:
                    gc.execute_generation_pipeline(overrides=pending_params, priority=0)
                    self._broadcast_json({"type": "status", "is_generating": True})
                    print("🌐 Remote: 자동생성 트리거됨")
            else:
                # auto_generate 아닌 pending (generate 등) → source만 추출
                for ws_key, pending in list(self._pending_overrides.items()):
                    if pending.get("source"):
                        source = pending.pop("source")
                        if not pending:  # 빈 dict면 제거
                            self._pending_overrides.pop(ws_key, None)
                        break

            if not self._has_clients():
                return
            prompt = prompt_context.final_prompt or ""
            mw = self.app_context.main_window
            remaining = mw.search_results.get_count() if mw and mw.search_results else 0
            rating_counts = {}
            if mw and mw.search_results and hasattr(mw.search_results, 'get_count_by_rating'):
                rating_counts = mw.search_results.get_count_by_rating()
            if self._loop and self._ws_manager:
                data = {"type": "prompt_generated", "prompt": prompt, "remaining": remaining,
                        "source": source, "rating_counts": rating_counts}
                data.update(self._build_prompt_token_payload(prompt, None))
                asyncio.run_coroutine_threadsafe(
                    self._ws_manager.broadcast_json(data),
                    self._loop
                )
                ctx = self.app_context.current_prompt_context
                if ctx and (ctx.wildcard_history or ctx.wildcard_state):
                    wc_state = self._read_wildcard()
                    if wc_state:
                        asyncio.run_coroutine_threadsafe(
                            self._ws_manager.broadcast_json(wc_state),
                            self._loop
                        )
                if not self.shared_server_mode:
                    pe_state = self._read_prompt_engineering()
                    if pe_state:
                        asyncio.run_coroutine_threadsafe(
                            self._ws_manager.broadcast_json(pe_state),
                            self._loop
                        )
                char_state = self._read_character()
                if char_state:
                    asyncio.run_coroutine_threadsafe(
                        self._ws_manager.broadcast_json(char_state),
                        self._loop
                    )
        except Exception as e:
            print(f"🌐 Remote: 프롬프트 전송 실패 — {e}")

    def on_generation_result(self, result: dict):
        """생성 완료 시 PIL→WebP 변환 후 WebSocket broadcast"""
        # NAI 모드에서 생성 끝나면 Anlas 잔액 갱신 (실제 사용량 반영)
        try:
            if hasattr(self.app_context, "get_api_mode") and self.app_context.get_api_mode() == "NAI":
                self._refresh_anlas_async()
        except Exception:
            pass
        try:
            image = result.get("image")
            if image is None:
                return

            buf = io.BytesIO()
            image.save(buf, format='WEBP', quality=85, method=4)
            webp_bytes = buf.getvalue()

            gen_params = result.get("generation_params", {})
            metadata = {
                "width": image.width,
                "height": image.height,
                "size_kb": len(webp_bytes) // 1024,
                "timestamp": datetime.now().isoformat(),
                "can_enhance": bool(gen_params),
                "prompt": gen_params.get("input", ""),
                "negative_prompt": gen_params.get("negative_prompt", ""),
                "seed": gen_params.get("seed", ""),
                "steps": gen_params.get("steps", ""),
                "cfg_scale": gen_params.get("cfg_scale", ""),
                "sampler": gen_params.get("sampler", ""),
                "model": gen_params.get("model", ""),
            }

            # /api/latest-image 호환을 위해 최신 이미지만 보존한다.
            self.latest_webp = webp_bytes
            self.latest_metadata_payload = self._build_result_metadata_payload(image, result, webp_bytes)

            if not self._has_clients():
                return

            self._broadcast_json({"type": "status", "is_generating": False})

            if self._loop and self._ws_manager:
                asyncio.run_coroutine_threadsafe(
                    self._ws_manager.broadcast_image(webp_bytes, metadata),
                    self._loop
                )
        except Exception as e:
            print(f"🌐 Remote: 이미지 변환/broadcast 실패 — {e}")

    def on_result_enhance_completed(self, success: bool = False, message: str = ""):
        """ImageWindow Enhance 완료 상태를 Web Result 버튼에 반영."""
        self._remote_enhance_in_flight = False
        payload = {
            "type": "result_enhance_state",
            "running": False,
            "success": bool(success),
        }
        if message:
            payload["message"] = str(message)
        self._broadcast_json(payload)
        if not success and message:
            self._broadcast_json({"type": "toast", "message": str(message), "level": "error"})

    def _broadcast_json(self, data: dict):
        if self._loop and self._ws_manager:
            asyncio.run_coroutine_threadsafe(
                self._ws_manager.broadcast_json(data),
                self._loop
            )


# ---------------------------------------------------------------------------
# FastAPI App 생성
# ---------------------------------------------------------------------------
def create_app(bridge: RemoteBridge, ws_manager: WebSocketManager) -> FastAPI:
    app = FastAPI(title="NAIA Remote")

    web_dir = Path(__file__).parent.parent / "ui" / "remote_web"
    js_dir = web_dir / "js"
    if js_dir.exists():
        app.mount("/js", StaticFiles(directory=str(js_dir)), name="remote_js")

    @app.get("/")
    async def index():
        html_path = web_dir / "index.html"
        if html_path.exists():
            return FileResponse(str(html_path), media_type="text/html")
        return JSONResponse({"error": "index.html not found"}, status_code=404)

    @app.get("/style.css")
    async def serve_css():
        p = web_dir / "style.css"
        return FileResponse(str(p), media_type="text/css") if p.exists() else JSONResponse({"error": "not found"}, 404)

    @app.get("/app.js")
    async def serve_js():
        p = web_dir / "app.js"
        return FileResponse(str(p), media_type="application/javascript") if p.exists() else JSONResponse({"error": "not found"}, 404)

    @app.post("/api/generate")
    async def api_generate():
        bridge._pending_generate_requests.append({"ws": None, "prompt": "", "negative": ""})
        bridge.request_generate.emit()
        return {"status": "generation_requested"}

    @app.post("/api/random")
    async def api_random():
        bridge._pending_random_requests.append({"ws": None, "source_row": None, "active_ratings": set(bridge._active_ratings)})
        bridge.request_random.emit()
        return {"status": "random_generation_requested"}

    @app.post("/api/comfyui/random")
    async def api_comfyui_random(req: Request):
        """ComfyUI 전용 sync 랜덤 프롬프트 요청.

        Body (JSON, 선택):
          - timeout: float (default 30) — 응답 대기 최대 시간(초)
          - respect_naia_autogen: bool (default true) — NAIA "자동 생성" 체크 존중
          - force_naia_skip_generate: bool (default false) — 강제로 NAIA generate 차단
          - peng_override: dict (default null) — per-request P.Eng 오버라이드. NAIA 메인 UI 불변.
              생략 시: 데스크톱 UI 사용
              빈 dict {}: 전부 빈 값 (prefix/postfix/auto_hide 비우고 preprocessing 전부 OFF)
              부분 dict: 명시 필드만 적용. 구조:
                {
                  "pre_prompt": str,
                  "post_prompt": str,
                  "auto_hide": str,
                  "preprocessing_options": {key: bool, ...}  # remove_author, remove_clothes, ...
                }

        Response 200:
          { request_id, prompt, negative_prompt, naia_started_generation, remaining, source }
        Response 504: { "error": "timeout" }
        """
        try:
            body = await req.json()
        except Exception:
            body = {}
        timeout = float(body.get("timeout", 30))
        respect_autogen = bool(body.get("respect_naia_autogen", True))
        force_skip = bool(body.get("force_naia_skip_generate", False))
        peng_override = body.get("peng_override")
        if peng_override is not None and not isinstance(peng_override, dict):
            return JSONResponse({"error": "peng_override must be a dict"}, status_code=400)

        request_id = str(uuid.uuid4())
        loop = asyncio.get_running_loop()
        future = loop.create_future()

        with bridge._comfyui_requests_lock:
            bridge._pending_comfyui_requests[request_id] = future

        bridge._pending_random_requests.append({
            "ws": None,
            "source_row": None,
            "active_ratings": set(bridge._active_ratings),
            "comfyui_request_id": request_id,
            "respect_naia_autogen": respect_autogen,
            "force_naia_skip_generate": force_skip,
            "peng_override": peng_override,
        })
        bridge.request_random.emit()

        try:
            result = await asyncio.wait_for(future, timeout=timeout)
            return result
        except asyncio.TimeoutError:
            with bridge._comfyui_requests_lock:
                bridge._pending_comfyui_requests.pop(request_id, None)
            return JSONResponse({"error": "timeout"}, status_code=504)

    @app.get("/api/comfyui/health")
    async def api_comfyui_health():
        try:
            gc = bridge.app_context.main_window.generation_controller
            return {
                "ok": True,
                "api_mode": bridge.app_context.get_api_mode(),
                "is_generating": gc.is_generating,
            }
        except Exception as e:
            return JSONResponse(
                {"ok": False, "error": str(e)},
                status_code=503,
            )

    @app.get("/api/status")
    async def api_status():
        try:
            gc = bridge.app_context.main_window.generation_controller
            return {
                "is_generating": gc.is_generating,
                "api_mode": bridge.app_context.get_api_mode(),
            }
        except Exception:
            return {"is_generating": False, "api_mode": "unknown"}

    @app.get("/api/latest-image")
    async def api_latest_image():
        if bridge.latest_webp is None:
            return JSONResponse({"error": "No image generated yet"}, status_code=404)
        return Response(
            content=bridge.latest_webp,
            media_type="image/webp",
            headers={"Content-Disposition": "attachment; filename=naia_latest.webp"}
        )

    @app.get("/api/result/metadata")
    async def api_result_metadata():
        if bridge.latest_metadata_payload is None:
            return JSONResponse({"error": "No image generated yet"}, status_code=404)
        return bridge.latest_metadata_payload

    @app.post("/api/image-action/{action}")
    async def api_image_action(action: str, req: Request):
        action = (action or "").strip().lower()
        if action not in {"img2img", "inpaint", "danbooru", "vibe"}:
            return JSONResponse({"error": "Unsupported action"}, status_code=400)
        image_bytes = await req.body()
        if not image_bytes:
            return JSONResponse({"error": "No image data"}, status_code=400)
        max_bytes = 64 * 1024 * 1024
        if len(image_bytes) > max_bytes:
            return JSONResponse({"error": "Image is too large"}, status_code=413)
        label = (req.query_params.get("label") or "Input Image")[:120]
        bridge.request_image_action.emit(action, image_bytes, label)
        return {"ok": True, "action": action}

    @app.get("/api/result/asset/current")
    async def api_current_result_asset():
        asset = await asyncio.to_thread(bridge._build_current_result_asset_payload)
        if not asset.get("has_image"):
            return JSONResponse({"error": "No image generated yet"}, status_code=404)
        return asset

    @app.get("/api/result/asset/saved")
    async def api_saved_result_asset(path: str):
        asset = await asyncio.to_thread(bridge._build_saved_result_asset_payload, path)
        if not asset:
            return JSONResponse({"error": "not found"}, status_code=404)
        return asset

    @app.post("/api/metadata/extract")
    async def api_metadata_extract(req: Request):
        image_bytes = await req.body()
        if not image_bytes:
            return JSONResponse({"error": "No image data"}, status_code=400)
        max_bytes = 64 * 1024 * 1024
        if len(image_bytes) > max_bytes:
            return JSONResponse({"error": "Image is too large"}, status_code=413)

        label = (req.query_params.get("label") or "Input Image")[:120]
        mime_type = req.headers.get("content-type", "")

        def _extract():
            from PIL import Image
            with Image.open(io.BytesIO(image_bytes)) as img:
                img.load()
                return bridge._build_input_metadata_payload(img, image_bytes, label, mime_type)

        try:
            return await asyncio.to_thread(_extract)
        except Exception as e:
            return JSONResponse({"error": f"Invalid image: {e}"}, status_code=400)

    # --- Viewer REST API ---

    @app.get("/api/viewer/list")
    async def viewer_list(page: int = 0, per_page: int = 30):
        entries = await asyncio.to_thread(bridge._scan_save_folder)
        start = page * per_page
        end = start + per_page
        return {
            "total": len(entries),
            "page": page,
            "per_page": per_page,
            "images": entries[start:end],
        }

    @app.post("/api/viewer/open-folder")
    async def viewer_open_folder():
        def _open_folder():
            import os
            import subprocess
            import sys

            folder = Path(bridge.app_context.session_save_path)
            folder.mkdir(parents=True, exist_ok=True)

            if sys.platform.startswith("darwin"):
                subprocess.Popen(["open", str(folder)])
            elif os.name == "nt":
                os.startfile(str(folder))  # type: ignore[attr-defined]
            else:
                subprocess.Popen(["xdg-open", str(folder)])
            return str(folder)

        try:
            opened = await asyncio.to_thread(_open_folder)
            return {"ok": True, "path": opened}
        except Exception as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

    @app.get("/api/viewer/thumb/{path:path}")
    async def viewer_thumb(path: str, size: int = 0):
        target = bridge._validate_viewer_path(path)
        if not target:
            return JSONResponse({"error": "not found"}, 404)
        # size=0: 원본의 절반 (서버에서 자동 결정)
        if size > 0:
            size = min(max(size, 50), 1024)
        thumb_bytes = await asyncio.to_thread(bridge._get_or_create_thumbnail, target, size)
        if not thumb_bytes:
            return JSONResponse({"error": "thumbnail failed"}, 500)
        return Response(content=thumb_bytes, media_type="image/webp")

    @app.get("/api/viewer/image/{path:path}")
    async def viewer_image(path: str):
        target = bridge._validate_viewer_path(path)
        if not target:
            return JSONResponse({"error": "not found"}, 404)
        ext = target.suffix.lower()
        media = {".webp": "image/webp", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}.get(ext, "image/png")
        return FileResponse(str(target), media_type=media)

    @app.get("/api/viewer/meta")
    async def viewer_meta_query(path: str, full: bool = False):
        return await viewer_meta(path, full)

    @app.get("/api/viewer/meta/{path:path}")
    async def viewer_meta(path: str, full: bool = False):
        target = bridge._validate_viewer_path(path)
        if not target:
            return JSONResponse({"error": "not found"}, 404)

        def _extract(img_path, include_full=False):
            import json as _json
            from PIL import Image as _Image

            meta = None
            # 1차: ImageMetadataExtractor (UnicodeEncodeError 대비 — cp949 콘솔)
            try:
                from utils.image_info import ImageMetadataExtractor
                meta = ImageMetadataExtractor.extract_metadata(str(img_path))
            except Exception:
                pass

            # 2차 fallback: Comment 필드 직접 파싱
            if not meta or 'prompt' not in meta:
                try:
                    img = _Image.open(str(img_path))
                    comment = img.info.get('Comment', '')
                    if comment and comment.strip().startswith('{'):
                        meta = _json.loads(comment)
                except Exception:
                    pass

            if not meta:
                return {"summary": {}, "raw": {}} if include_full else {}

            result = {}
            if 'prompt' in meta:
                result['prompt'] = meta['prompt']
            if 'uc' in meta:
                result['negative'] = meta['uc']
            elif 'negative' in meta:
                result['negative'] = meta['negative']
            # NAI v4 character captions
            if 'characters' in meta:
                result['characters'] = meta['characters']
            elif 'v4_prompt' in meta:
                # v4_prompt에서 직접 추출
                try:
                    v4 = meta['v4_prompt']
                    if isinstance(v4, str):
                        v4 = _json.loads(v4)
                    captions = v4.get('caption', {}).get('char_captions', [])
                    chars = [c.get('char_caption', '') for c in captions if c.get('char_caption')]
                    if chars:
                        result['characters'] = chars
                except Exception:
                    pass
            # parameters (flat NAI JSON: steps/scale/seed at top level)
            for k in ('steps', 'scale', 'seed', 'sampler', 'width', 'height'):
                if k in meta:
                    result[k] = meta[k]
            # nested parameters dict (from _parse_nai_format path)
            if 'parameters' in meta and isinstance(meta['parameters'], dict):
                for k in ('steps', 'scale', 'seed', 'sampler', 'width', 'height'):
                    if k in meta['parameters'] and k not in result:
                        result[k] = meta['parameters'][k]
            if include_full:
                try:
                    raw_meta = _json.loads(_json.dumps(meta, default=str, ensure_ascii=False))
                except Exception:
                    raw_meta = str(meta)
                return {"summary": result, "raw": raw_meta}
            return result

        data = await asyncio.to_thread(_extract, target, full)
        return data

    @app.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket):
        session_id = await ws_manager.connect(ws)
        try:
            # 세션 정보 전송
            await ws.send_text(json.dumps({
                "type": "session",
                "session_id": session_id,
                "shared_server_mode": bridge.shared_server_mode,
            }))
            await ws.send_text(json.dumps(bridge.get_desktop_window_state(ws)))
            # 클라이언트 초기 메시지를 잠시 보관한 뒤 초기화 패킷 전송 후 재처리한다.
            _pending_init_cmds = []
            try:
                init_data = await asyncio.wait_for(ws.receive_text(), timeout=3.0)
                if init_data.startswith("{"):
                    _pending_init_cmds.append(json.loads(init_data))
                else:
                    _pending_init_cmds.append(init_data)
            except (asyncio.TimeoutError, Exception):
                pass

            current_mode = bridge.app_context.get_api_mode()
            await ws.send_text(json.dumps({"type": "mode", "mode": current_mode}))
            if bridge._cached_options:
                await ws.send_text(json.dumps(bridge._cached_options))
            if bridge._cached_prompts:
                await ws.send_text(json.dumps(bridge._cached_prompts))
            if bridge._cached_params:
                await ws.send_text(json.dumps(bridge._cached_params))
            # api_status 는 per-ws 평가 (setup_allowed 가 클라이언트 IP에 따라 다름)
            await ws.send_text(json.dumps(bridge.get_api_status(ws=ws)))
            # 캐시된 Anlas 있으면 바로 송신 (viewer pill 초기화)
            # Shared Mode 에서는 호스트 잔액 노출 금지
            if bridge._anlas_cache and not bridge.shared_server_mode:
                await ws.send_text(json.dumps(bridge._anlas_payload()))
            # init_complete: 클라이언트에 초기화 완료 신호 (복원 가드 해제용)
            await ws.send_text(json.dumps({"type": "init_complete"}))
            # 메인 스레드에서 캐시 갱신 + broadcast (초기화 타이밍 이슈 방지)
            bridge.request_refresh_cache.emit()
            # Send module badge states (automation countdown, character count)
            bridge.request_get_module.emit(None, "automation")
            bridge.request_get_module.emit(None, "character")
            bridge.request_get_module.emit(None, "character_reference")
            bridge.request_get_module.emit(None, "vibe_transfer")

            # 보류된 초기 메시지를 메인 루프에 재주입
            # (get_search_state, restore_session 등 초기화 단계에서 소비된 메시지)
            _replay_queue = list(_pending_init_cmds)

            while True:
                # 보류된 초기 메시지가 있으면 먼저 처리
                if _replay_queue:
                    cmd = _replay_queue.pop(0)
                    data = json.dumps(cmd) if isinstance(cmd, dict) else str(cmd)  # 아래 분기 재사용
                else:
                    data = await ws.receive_text()
                if data == "generate":
                    bridge._pending_generate_requests.append({"ws": ws, "prompt": "", "negative": ""})
                    bridge.request_generate.emit()
                elif data == "random":
                    # Shared: eligible_ids에서 row 선택 (asyncio thread)
                    if bridge.shared_server_mode:
                        row = await asyncio.to_thread(bridge._pick_from_session, ws)
                        if row is None:
                            await ws.send_text(json.dumps({"type": "random_failed", "message": "No matching rows for current filter", "level": "error"}))
                            continue
                        bridge._pending_random_requests.append({"ws": ws, "source_row": row, "active_ratings": None})
                    else:
                        bridge._pending_random_requests.append({"ws": ws, "source_row": None, "active_ratings": set(bridge._active_ratings)})
                    bridge.request_random.emit()
                elif data == "sync":
                    if not bridge.shared_server_mode and bridge._cached_prompts:
                        await ws.send_text(json.dumps(bridge._cached_prompts))
                    if bridge._cached_params:
                        await ws.send_text(json.dumps(bridge._cached_params))
                elif data.startswith("{"):
                    try:
                        cmd = json.loads(data)
                        cmd_type = cmd.get("type")
                        if cmd_type == "random":
                            if bridge.shared_server_mode:
                                row = await asyncio.to_thread(bridge._pick_from_session, ws)
                                if row is None:
                                    await ws.send_text(json.dumps({"type": "random_failed", "message": "No matching rows for current filter", "level": "error"}))
                                    continue
                                bridge._pending_random_requests.append({"ws": ws, "source_row": row, "active_ratings": None})
                            else:
                                ratings = cmd.get("ratings", [])
                                valid = set(r for r in ratings if r in 'gsqe')
                                active = valid if valid else set(bridge._active_ratings)
                                bridge._pending_random_requests.append({"ws": ws, "source_row": None, "active_ratings": active})
                            bridge.request_random.emit()
                        elif cmd_type == "set_option":
                            opt_key = cmd.get("key", "")
                            if bridge.shared_server_mode:
                                if opt_key in ("auto_generate", "auto_save"):
                                    pass  # 차단 (호스트 전역 설정)
                                elif opt_key in ("prompt_fixed", "wildcard_standalone"):
                                    # 세션별 저장
                                    session = ws_manager.sessions.get(ws)
                                    if session:
                                        opts = session.setdefault("options", {})
                                        opts[opt_key] = bool(cmd.get("value"))
                                else:
                                    bridge.request_set_option.emit(opt_key, cmd["value"])
                            else:
                                bridge.request_set_option.emit(opt_key, cmd["value"])
                        elif cmd_type == "set_prompt":
                            if bridge.shared_server_mode:
                                # Shared: negative만 세션에 저장 (positive는 Generate 시 전송)
                                session = ws_manager.sessions.get(ws)
                                if session:
                                    session["negative_prompt"] = cmd.get("negative_prompt", "")
                            else:
                                bridge.request_set_prompt.emit(
                                    cmd.get("prompt", ""),
                                    cmd.get("negative_prompt", "")
                                )
                        elif cmd_type == "set_mode":
                            bridge.request_set_mode.emit(cmd.get("mode", ""))
                        elif cmd_type == "set_desktop_window_visibility":
                            allowed, reason = bridge._desktop_window_gate(ws)
                            if not allowed:
                                await ws.send_text(json.dumps({
                                    "type": "toast",
                                    "message": reason,
                                    "level": "error",
                                }))
                                continue
                            bridge.request_set_desktop_visibility.emit(bool(cmd.get("visible", False)))
                        elif cmd_type == "set_param":
                            v = cmd.get("value", "")
                            if bridge.shared_server_mode:
                                # Shared: 세션 dict에 저장
                                session = ws_manager.sessions.get(ws)
                                if session:
                                    po = session.setdefault("params_override", {})
                                    key = cmd.get("key", "")
                                    po[key] = str(v).lower() if isinstance(v, bool) else str(v)
                            else:
                                bridge.request_set_param.emit(
                                    cmd.get("key", ""), str(v).lower() if isinstance(v, bool) else str(v))
                        elif cmd_type == "set_api_url":
                            bridge.request_set_api_url.emit(
                                cmd.get("mode", ""), cmd.get("url", ""))
                        elif cmd_type == "test_api":
                            bridge.request_test_api.emit(cmd.get("mode", ""))
                        elif cmd_type == "get_module_state":
                            bridge.request_get_module.emit(ws, cmd.get("module_id", ""))
                        elif cmd_type == "set_module_param":
                            mid = cmd.get("module_id", "")
                            mkey = cmd.get("key", "")
                            mval = str(cmd.get("value", ""))
                            if mid == "auto_save":
                                allowed, reason = bridge._auto_save_settings_gate(ws)
                                if not allowed:
                                    await ws.send_text(json.dumps({
                                        "type": "toast",
                                        "message": reason,
                                        "level": "error",
                                    }))
                                    continue
                                bridge.request_set_module.emit(mid, mkey, mval)
                                continue
                            if mid == "save_directory":
                                allowed, reason = bridge._save_directory_gate(ws)
                                if not allowed:
                                    await ws.send_text(json.dumps({
                                        "type": "toast",
                                        "message": reason,
                                        "level": "error",
                                    }))
                                    continue
                                bridge.request_set_module.emit(mid, mkey, mval)
                                continue
                            # Shared Mode: P.Eng / Cond → 세션 dict에 저장
                            if bridge.shared_server_mode and mid == "conditional_prompt":
                                session = ws_manager.sessions.get(ws)
                                if session:
                                    co = session.setdefault("cond_override", {})
                                    if mkey == "enabled":
                                        co["enabled"] = (mval == "true")
                                    elif mkey == "rules":
                                        co["rules"] = mval
                                    # test는 세션 오버라이드로 실행 불가 — 무시
                            elif bridge.shared_server_mode and mid == "prompt_engineering":
                                session = ws_manager.sessions.get(ws)
                                if session:
                                    po = session.setdefault("p_eng_override", {})
                                    if mkey in ("pre_prompt", "post_prompt", "auto_hide"):
                                        po[mkey] = mval  # 텍스트 그대로 저장, hook에서 split
                                    elif mkey.startswith("pp_"):
                                        pp = po.setdefault("preprocessing_options", {})
                                        pp[mkey[3:]] = (mval == "true")  # strip pp_ prefix
                                    elif mkey == "preset":
                                        po["preset"] = mval
                            else:
                                bridge.request_set_module.emit(mid, mkey, mval)
                        elif cmd_type == "browse_save_directory":
                            allowed, reason = bridge._save_directory_gate(ws)
                            if not allowed:
                                await ws.send_text(json.dumps({
                                    "type": "toast",
                                    "message": reason,
                                    "level": "error",
                                }))
                                continue
                            bridge.request_browse_save_directory.emit(ws)
                        elif cmd_type in ("get_search_state", "search", "load_parquet",
                                           "depth_action", "get_depth_state", "restore_snapshot"):
                            if bridge.shared_server_mode:
                                pass  # Shared Mode: 검색/Depth/Restore 차단
                            elif cmd_type == "get_search_state":
                                bridge.request_get_module.emit(None, "__search__")
                            elif cmd_type == "search":
                                bridge.request_search.emit(json.dumps(cmd))
                            elif cmd_type == "load_parquet":
                                bridge.request_load_parquet.emit(cmd.get("filename", ""))
                            elif cmd_type == "depth_action":
                                bridge.request_depth_action.emit(json.dumps(cmd))
                            elif cmd_type == "get_depth_state":
                                bridge.request_get_module.emit(None, "__depth__")
                            elif cmd_type == "restore_snapshot":
                                bridge.request_restore_snapshot.emit()
                        elif cmd_type == "set_active_ratings":
                            ratings = cmd.get("ratings", [])
                            new_ratings = set(r for r in ratings if r in 'gsqe')
                            if not new_ratings:
                                new_ratings = {'q', 'e'}  # 최소 1개 보장
                            if bridge.shared_server_mode:
                                session = ws_manager.sessions.get(ws)
                                if session:
                                    session["active_ratings"] = new_ratings
                                    await asyncio.to_thread(bridge._recompute_eligible_ids, session)
                            else:
                                bridge._active_ratings = new_ratings
                                bridge.app_context.remote_active_ratings = new_ratings
                                bridge.request_apply_filters.emit()
                            # 즉시 카운트 계산하여 응답
                            if bridge.shared_server_mode:
                                state = await asyncio.to_thread(bridge._read_search_state)
                                rc = state.get("rating_counts", {})
                                count = sum(rc.get(r, 0) for r in new_ratings)
                            else:
                                info = await asyncio.to_thread(bridge._compute_master_count, new_ratings)
                                rc = info["rating_counts"]
                                count = info["count"]
                            await ws.send_text(json.dumps({
                                "type": "rating_update",
                                "active_ratings": list(new_ratings),
                                "count": count,
                                "rating_counts": rc,
                            }))
                        elif cmd_type == "tag_filter_search":
                            tags = cmd.get("tags", [])
                            if tags:
                                result = await asyncio.to_thread(bridge._do_tag_filter_search, tags)
                                # pending에 저장 (Assign 전까지 Random에 미반영)
                                session = ws_manager.sessions.get(ws)
                                if session:
                                    ids = result.pop("_ids", set())
                                    session["tag_filter_pending"] = {
                                        "tags": tags,
                                        "ids": ids,
                                        "count": result["count"],
                                    }
                                else:
                                    result.pop("_ids", None)
                                await ws.send_text(json.dumps(result))
                            else:
                                await ws.send_text(json.dumps({
                                    "type": "tag_filter_result", "count": 0,
                                    "tags": [], "rating_counts": {r: 0 for r in 'gsqe'},
                                }))
                        elif cmd_type == "tag_filter_assign":
                            # pending → 확정: Random에서 사용
                            session = ws_manager.sessions.get(ws)
                            if session and session.get("tag_filter_pending"):
                                session["tag_filter"] = session.pop("tag_filter_pending")
                                await asyncio.to_thread(bridge._recompute_eligible_ids, session)
                                tf = session["tag_filter"]
                                # Non-shared: master에서 GSQE + Tag Filter 재적용
                                if not bridge.shared_server_mode:
                                    bridge._active_tag_filter_ids = tf.get("ids")
                                    bridge.request_apply_filters.emit()
                                await ws.send_text(json.dumps({
                                    "type": "tag_filter_assigned",
                                    "count": tf["count"],
                                    "tags": tf["tags"],
                                }))
                            else:
                                await ws.send_text(json.dumps({
                                    "type": "toast",
                                    "message": "No pending search to assign",
                                    "level": "error",
                                }))
                        elif cmd_type == "tag_filter_clear":
                            session = ws_manager.sessions.get(ws)
                            if session:
                                session["tag_filter"] = None
                                session["tag_filter_pending"] = None
                                await asyncio.to_thread(bridge._recompute_eligible_ids, session)
                            # Non-shared: tag filter 해제 + 재적용
                            if not bridge.shared_server_mode:
                                bridge._active_tag_filter_ids = None
                                bridge.request_apply_filters.emit()
                            await ws.send_text(json.dumps({
                                "type": "tag_filter_result", "count": 0,
                                "tags": [], "rating_counts": {r: 0 for r in 'gsqe'},
                            }))
                        elif cmd_type == "tag_search":
                            # 한글/영문 태그 검색 — 스레드 풀에서 실행 (초기 로드 블로킹 방지)
                            query = cmd.get("query", "")
                            results = await asyncio.to_thread(bridge._search_kr_tags, query, 20)
                            await ws.send_text(json.dumps({
                                "type": "tag_search_result",
                                "query": query,
                                "results": results,
                            }))
                        elif cmd_type == "tag_filter_ac":
                            query = cmd.get("query", "")
                            results = await asyncio.to_thread(bridge._search_kr_tags, query, 12)
                            await ws.send_text(json.dumps({
                                "type": "tag_filter_ac_result",
                                "query": query,
                                "results": results,
                            }))
                        elif cmd_type == "autocomplete":
                            # 프롬프트 자동완성 — 5단계 검색
                            query = cmd.get("query", "")
                            results = await asyncio.to_thread(bridge._search_kr_tags, query, 12)
                            await ws.send_text(json.dumps({
                                "type": "autocomplete_result",
                                "query": query,
                                "results": results,
                            }))
                        elif cmd_type == "autocomplete_wildcard":
                            query = cmd.get("query", "")
                            results = await asyncio.to_thread(bridge._search_wildcards, query, 12)
                            await ws.send_text(json.dumps({
                                "type": "autocomplete_result",
                                "query": query,
                                "results": results,
                            }))
                        elif cmd_type == "tag_lookup":
                            # 태그 상세 정보 조회
                            tag = cmd.get("tag", "")
                            info = await asyncio.to_thread(bridge._lookup_tag_info, tag)
                            await ws.send_text(json.dumps({
                                "type": "tag_lookup_result", **info,
                            }))
                        elif cmd_type == "restore_session":
                            # 클라이언트 LocalStorage → 서버 세션 복원 (재연결 시)
                            if bridge.shared_server_mode:
                                session = ws_manager.sessions.get(ws)
                                if session:
                                    # params
                                    params = cmd.get("params")
                                    if params and isinstance(params, dict):
                                        session["params_override"] = {k: str(v) for k, v in params.items()}
                                    # negative prompt
                                    neg = cmd.get("negative_prompt")
                                    if neg is not None:
                                        session["negative_prompt"] = str(neg)
                                    # options (prompt_fixed, wildcard_standalone)
                                    opts = cmd.get("options")
                                    if opts and isinstance(opts, dict):
                                        session["options"] = {k: bool(v) for k, v in opts.items()}
                                    # P.Eng override
                                    p_eng = cmd.get("p_eng")
                                    if p_eng and isinstance(p_eng, dict):
                                        restored = {}
                                        for k in ("pre_prompt", "post_prompt", "auto_hide", "preset"):
                                            if k in p_eng:
                                                restored[k] = str(p_eng[k])
                                        pp = p_eng.get("preprocessing_options")
                                        if pp and isinstance(pp, dict):
                                            restored["preprocessing_options"] = {k: bool(v) for k, v in pp.items()}
                                        session["p_eng_override"] = restored
                                    # Cond override
                                    cond = cmd.get("cond")
                                    if cond and isinstance(cond, dict):
                                        session["cond_override"] = {
                                            "enabled": bool(cond.get("enabled", False)),
                                            "rules": str(cond.get("rules", "")),
                                        }
                                    print(f"🌐 Session restored from client LocalStorage (session={session['id']})")
                        elif cmd_type == "generate":
                            bridge._pending_generate_requests.append({
                                "ws": ws,
                                "prompt": cmd.get("prompt", ""),
                                "negative": cmd.get("negative_prompt", ""),
                            })
                            bridge.request_generate.emit()
                        elif cmd_type == "result_enhance":
                            bridge.request_result_enhance.emit(ws)
                        elif cmd_type == "probe_api":
                            # 저장된 토큰/URL 로 실시간 연결 가능 여부 확인.
                            # keyring 값 사용 — 웹으로 토큰이 노출되지 않음. 저장/타임스탬프 갱신 없음.
                            # 3개 backend 병렬 ping (최악 NAI 10s).
                            # Setup 게이트(loopback + !shared + !cloudflared) 적용 — LAN/터널 기기가
                            # 호스트 자격증명으로 NAI /user/subscription 을 스팸 호출하지 못하도록.
                            allowed, reason = bridge._setup_gate(ws)
                            if not allowed:
                                await ws.send_text(json.dumps({
                                    "type": "setup_blocked",
                                    "command": "probe_api",
                                    "reason": reason,
                                }))
                                continue
                            stm_p = bridge.app_context.secure_token_manager

                            async def _probe(mode_key, token_key, fn):
                                val = (stm_p.get_token(token_key) or "").strip()
                                if not val:
                                    return (mode_key, None)
                                try:
                                    r = await asyncio.to_thread(fn, val)
                                    return (mode_key, bool(r.success))
                                except Exception:
                                    return (mode_key, False)

                            pairs = await asyncio.gather(
                                _probe("NAI",     "nai_token",    api_verification.verify_nai_token),
                                _probe("WEBUI",   "webui_url",    api_verification.verify_webui_url),
                                _probe("COMFYUI", "comfyui_url",  api_verification.verify_comfyui_url),
                            )
                            results = {k: v for k, v in pairs}
                            await ws.send_text(json.dumps({
                                "type": "probe_result", "results": results,
                            }))

                        elif cmd_type in ("verify_nai", "verify_webui", "verify_comfyui",
                                          "clear_api", "set_cloudflared_enabled"):
                            # --- Setup 전용 명령 (Phase 2+3) ---
                            if cmd_type == "set_cloudflared_enabled":
                                allowed, reason = bridge._cloudflared_gate(ws)
                            else:
                                allowed, reason = bridge._setup_gate(ws)
                            if not allowed:
                                payload_type = "setup_blocked" if cmd_type != "set_cloudflared_enabled" else "toast"
                                payload = {
                                    "type": payload_type,
                                    "command": cmd_type,
                                    "reason": reason,
                                }
                                if payload_type == "toast":
                                    payload["message"] = reason
                                    payload["level"] = "error"
                                await ws.send_text(json.dumps(payload))
                                continue

                            stm = bridge.app_context.secure_token_manager

                            if cmd_type == "verify_nai":
                                token = (cmd.get("token") or "").strip()
                                r = await asyncio.to_thread(api_verification.verify_nai_token, token)
                                await ws.send_text(json.dumps({
                                    "type": "verify_result", "mode": "NAI",
                                    "success": r.success, "message": r.message,
                                    "message_type": r.message_type, "extra": r.extra,
                                }))
                                if r.success:
                                    stm.save_token("nai_token", r.value or token)
                                    bridge._save_verify_timestamp("nai_token")
                                    bridge._broadcast_api_status()
                                    # 토큰이 바뀌었을 수 있으니 Anlas 즉시 갱신
                                    bridge._refresh_anlas_async()

                            elif cmd_type == "verify_webui":
                                url = (cmd.get("url") or "").strip()
                                r = await asyncio.to_thread(api_verification.verify_webui_url, url)
                                await ws.send_text(json.dumps({
                                    "type": "verify_result", "mode": "WEBUI",
                                    "success": r.success, "message": r.message,
                                    "message_type": r.message_type, "extra": r.extra,
                                }))
                                if r.success:
                                    protocol = (r.extra or {}).get("protocol", "http")
                                    stm.save_token("webui_url", f"{protocol}://{r.value}")
                                    bridge._save_verify_timestamp("webui_url")
                                    bridge._broadcast_api_status()

                            elif cmd_type == "verify_comfyui":
                                url = (cmd.get("url") or "").strip()
                                r = await asyncio.to_thread(api_verification.verify_comfyui_url, url)
                                await ws.send_text(json.dumps({
                                    "type": "verify_result", "mode": "COMFYUI",
                                    "success": r.success, "message": r.message,
                                    "message_type": r.message_type, "extra": r.extra,
                                }))
                                if r.success:
                                    protocol = (r.extra or {}).get("protocol", "http")
                                    stm.save_token("comfyui_url", f"{protocol}://{r.value}")
                                    bridge._save_verify_timestamp("comfyui_url")
                                    bridge._broadcast_api_status()

                            elif cmd_type == "clear_api":
                                mode = (cmd.get("mode") or "").upper()
                                if mode == "NAI":
                                    stm.save_token("nai_token", "")
                                    bridge._anlas_cache = None
                                    if not bridge.shared_server_mode:
                                        bridge._broadcast_json(bridge._anlas_payload())
                                elif mode == "WEBUI":
                                    stm.save_token("webui_url", "")
                                elif mode == "COMFYUI":
                                    stm.save_token("comfyui_url", "")
                                    stm.save_token("comfyui_default_model", "")
                                    stm.save_token("comfyui_sampling_mode", "")
                                bridge._broadcast_api_status()

                            elif cmd_type == "set_cloudflared_enabled":
                                bridge.request_set_cloudflared_enabled.emit(bool(cmd.get("enabled", False)))
                    except Exception:
                        pass
        except WebSocketDisconnect:
            await ws_manager.disconnect(ws)
        except Exception as e:
            print(f"🌐 WebSocket error: {e}")
            await ws_manager.disconnect(ws)

    return app


# ---------------------------------------------------------------------------
# 서버 시작/종료
# ---------------------------------------------------------------------------
_server_instance: Optional[uvicorn.Server] = None
_bridge_instance: Optional[RemoteBridge] = None
_checkbox_connections: list = []  # 체크박스 toggled 연결 추적
_param_signal_sources: list = []  # 파라미터 위젯 시그널 연결 추적
_bridge_signal_connections: list = []  # (obj, signal_name, callback) 추가 연결 추적


def start_remote_server(app_context, host: str = "0.0.0.0", port: int = 7243):
    """Remote API 서버를 daemon thread로 시작."""
    global _server_instance, _bridge_instance, _checkbox_connections, _param_signal_sources, _bridge_signal_connections

    if _server_instance is not None:
        print("🌐 Remote: 서버가 이미 실행 중")
        return _server_instance

    ws_manager = WebSocketManager()
    bridge = RemoteBridge(app_context)
    bridge.set_ws_manager(ws_manager)
    _bridge_instance = bridge
    app_context.remote_bridge = bridge

    # 시그널 → Qt 메인 스레드 슬롯 연결
    bridge.request_generate.connect(bridge._do_generate, Qt.ConnectionType.QueuedConnection)
    bridge.request_random.connect(bridge._do_random, Qt.ConnectionType.QueuedConnection)
    bridge.request_set_option.connect(bridge._do_set_option, Qt.ConnectionType.QueuedConnection)
    bridge.request_set_prompt.connect(bridge._do_set_prompt, Qt.ConnectionType.QueuedConnection)
    bridge.request_set_mode.connect(bridge._do_set_mode, Qt.ConnectionType.QueuedConnection)
    bridge.request_set_api_url.connect(bridge._do_set_api_url, Qt.ConnectionType.QueuedConnection)
    bridge.request_test_api.connect(bridge._do_test_api, Qt.ConnectionType.QueuedConnection)
    bridge.request_set_param.connect(bridge._do_set_param, Qt.ConnectionType.QueuedConnection)
    bridge.request_get_module.connect(bridge._do_get_module, Qt.ConnectionType.QueuedConnection)
    bridge.request_set_module.connect(bridge._do_set_module, Qt.ConnectionType.QueuedConnection)
    bridge.request_search.connect(bridge._do_search, Qt.ConnectionType.QueuedConnection)
    bridge.request_load_parquet.connect(bridge._do_load_parquet, Qt.ConnectionType.QueuedConnection)
    bridge.request_depth_action.connect(bridge._do_depth_action, Qt.ConnectionType.QueuedConnection)
    bridge.request_restore_snapshot.connect(bridge._do_restore_snapshot, Qt.ConnectionType.QueuedConnection)
    bridge.request_apply_filters.connect(bridge._do_apply_filters, Qt.ConnectionType.QueuedConnection)
    bridge.request_refresh_cache.connect(bridge._do_refresh_cache, Qt.ConnectionType.QueuedConnection)
    bridge.request_set_desktop_visibility.connect(bridge._do_set_desktop_visibility, Qt.ConnectionType.QueuedConnection)
    bridge.request_browse_save_directory.connect(bridge._do_browse_save_directory, Qt.ConnectionType.QueuedConnection)
    bridge.request_result_enhance.connect(bridge._do_result_enhance, Qt.ConnectionType.QueuedConnection)
    bridge.request_image_action.connect(bridge._do_image_action, Qt.ConnectionType.QueuedConnection)
    bridge.request_set_cloudflared_enabled.connect(bridge._do_set_cloudflared_enabled, Qt.ConnectionType.QueuedConnection)

    # 검색 컨트롤러 시그널 연결
    mw = app_context.main_window
    if mw and hasattr(mw, 'search_controller'):
        mw.search_controller.search_progress.connect(bridge._on_search_progress)
        mw.search_controller.search_complete.connect(bridge._on_search_complete)

    # 자동화 모듈 시그널 연결 (메인 UI에서 start/stop 시 웹 동기화)
    auto_module = bridge._find_module("automation")
    if auto_module and hasattr(auto_module, 'automation_controller'):
        ac = auto_module.automation_controller
        ac.automation_finished.connect(bridge._broadcast_automation_state)
        ac.progress_updated.connect(bridge._broadcast_automation_state)

    # TabController tab_added 시그널 연결 (심층검색 탭 생성 감지)
    if mw and hasattr(mw, 'image_window') and mw.image_window:
        tc = getattr(mw.image_window, 'tab_controller', None)
        if tc:
            tc.tab_added.connect(bridge._on_tab_added)

    # AppContext 이벤트 구독
    app_context.subscribe("generation_result_available", bridge.on_generation_result)
    app_context.subscribe("result_enhance_completed", bridge.on_result_enhance_completed)
    app_context.subscribe("prompt_generated", bridge.on_prompt_generated)
    app_context.subscribe("api_mode_changed", bridge.on_api_mode_changed)
    app_context.subscribe("image_saved", bridge._on_image_saved)
    app_context.subscribe("desktop_window_visibility_changed", bridge.on_desktop_window_visibility_changed)
    app_context.subscribe("cloudflared_status_changed", bridge.on_cloudflared_status_changed)
    app_context.subscribe("save_directory_changed", bridge.on_save_directory_changed)

    # NAI 모드에서 시작된 경우 Anlas 타이머 부트 + 초기 fetch
    try:
        if hasattr(app_context, "get_api_mode") and app_context.get_api_mode() == "NAI":
            bridge._start_anlas_timer()
            bridge._refresh_anlas_async()
    except Exception:
        pass

    # 메인 UI 위젯 연결
    mw = app_context.main_window
    mw.main_prompt_textedit.textChanged.connect(bridge._on_prompt_text_changed)
    mw.negative_prompt_textedit.textChanged.connect(bridge._on_prompt_text_changed)

    # 생성 상태 이벤트 (메인 UI/자동생성 포함 전체 감지)
    app_context.subscribe("generation_started", bridge._on_generation_started_signal)

    # 체크박스 변경 → 웹 동기화 (메서드 참조로 disconnect 가능)
    _checkbox_connections = []
    _bridge_signal_connections = []
    for key, label in RemoteBridge.OPTION_KEYS.items():
        cb = mw.generation_checkboxes.get(label)
        if cb:
            cb.toggled.connect(bridge._on_option_toggled_slot)
            _checkbox_connections.append((cb, "toggled"))

    # auto_save 체크박스 → 웹 동기화
    auto_save_checkbox = bridge._get_auto_save_checkbox()
    if auto_save_checkbox:
        auto_save_checkbox.toggled.connect(bridge._on_option_toggled_slot)
        auto_save_checkbox.toggled.connect(bridge._on_auto_save_settings_changed)
        _checkbox_connections.append((auto_save_checkbox, "toggled"))
        _bridge_signal_connections.append((auto_save_checkbox, "toggled", bridge._on_auto_save_settings_changed))

    save_as_webp_checkbox = bridge._get_save_as_webp_checkbox()
    if save_as_webp_checkbox:
        save_as_webp_checkbox.toggled.connect(bridge._on_auto_save_settings_changed)
        _bridge_signal_connections.append((save_as_webp_checkbox, "toggled", bridge._on_auto_save_settings_changed))

    history_limit_enabled, max_history_length, memory_action_group = bridge._get_history_limit_widgets()
    if history_limit_enabled:
        history_limit_enabled.toggled.connect(bridge._on_auto_save_settings_changed)
        _bridge_signal_connections.append((history_limit_enabled, "toggled", bridge._on_auto_save_settings_changed))
    if max_history_length:
        max_history_length.valueChanged.connect(bridge._on_auto_save_settings_changed)
        _bridge_signal_connections.append((max_history_length, "valueChanged", bridge._on_auto_save_settings_changed))
    if memory_action_group:
        memory_action_group.buttonClicked.connect(bridge._on_auto_save_settings_changed)
        _bridge_signal_connections.append((memory_action_group, "buttonClicked", bridge._on_auto_save_settings_changed))

    # 생성 파라미터 위젯 변경 → 웹 동기화 (메서드 참조로 disconnect 가능)
    _param_signal_sources.clear()
    _param_signal_sources.extend([
        (mw.model_combo, "currentTextChanged"),
        (mw.sampler_combo, "currentTextChanged"),
        (mw.scheduler_combo, "currentTextChanged"),
        (mw.resolution_combo, "currentTextChanged"),
        (mw.steps_spinbox, "valueChanged"),
        (mw.cfg_scale_slider, "valueChanged"),
        (mw.cfg_rescale_slider, "valueChanged"),
        (mw.seed_input, "textChanged"),
        (mw.seed_fix_checkbox, "toggled"),
        (mw.random_resolution_checkbox, "toggled"),
        (mw.auto_fit_resolution_checkbox, "toggled"),
    ])
    # NAI 고급 옵션 체크박스
    for key in ["SMEA", "DYN", "VAR+", "DECRISP"]:
        cb = mw.advanced_checkboxes.get(key)
        if cb:
            _param_signal_sources.append((cb, "toggled"))
    # WEBUI HR 위젯
    for attr, sig in [("enable_hr_checkbox", "toggled"), ("hr_scale_spinbox", "valueChanged"),
                      ("hr_upscaler_combo", "currentTextChanged"), ("denoising_strength_spinbox", "valueChanged"),
                      ("hires_steps_spinbox", "valueChanged"), ("hr_cfg_spinbox", "valueChanged")]:
        w = getattr(mw, attr, None)
        if w: _param_signal_sources.append((w, sig))
    # ComfyUI 위젯
    for attr in ["eps_radio", "v_pred_radio", "anima_radio"]:
        w = getattr(mw, attr, None)
        if w: _param_signal_sources.append((w, "toggled"))
    if hasattr(mw, 'comfyui_rescale_slider'):
        _param_signal_sources.append((mw.comfyui_rescale_slider, "valueChanged"))

    for widget, signal_name in _param_signal_sources:
        try:
            getattr(widget, signal_name).connect(bridge._on_param_changed_slot)
        except Exception:
            pass

    # 캐시 초기화 (FastAPI 스레드에서 Qt 위젯 직접 접근 방지)
    bridge._update_cache_all()

    # Shared Server Mode: app_context에서 읽기 (Settings에서 bridge 생성 전에 설정될 수 있음)
    bridge.shared_server_mode = getattr(app_context, 'shared_server_mode', False)
    if bridge.shared_server_mode:
        print(f"🌐 Remote: Shared Server Mode 활성 상태로 시작")

    # KR_tags 인덱스 + character_analysis 백그라운드 로드 (첫 검색 지연 방지)
    def _bg_load():
        bridge._load_kr_tags()
        bridge._load_char_analysis()
    threading.Thread(target=_bg_load, daemon=True, name="KR-Tags-Loader").start()

    # FastAPI 앱 생성 + uvicorn 시작
    app = create_app(bridge, ws_manager)
    config = uvicorn.Config(app, host=host, port=port, log_level="warning")
    server = uvicorn.Server(config)
    _server_instance = server

    def _run_server():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        bridge.set_event_loop(loop)
        loop.run_until_complete(server.serve())

    threading.Thread(target=_run_server, daemon=True, name="NAIA-RemoteAPI").start()
    print(f"🌐 Remote API server starting on http://localhost:{port}")
    return server


def stop_remote_server():
    """서버 graceful shutdown + 이벤트/시그널 해제"""
    global _server_instance, _bridge_instance, _checkbox_connections, _param_signal_sources, _bridge_signal_connections

    if _server_instance:
        _server_instance.should_exit = True
        print("🌐 Remote API server stopping...")
        _server_instance = None

    if _bridge_instance:
        try:
            ctx = _bridge_instance.app_context
            ctx.remote_bridge = None
            ctx.remote_active_ratings = None
            # Master snapshot + 필터 상태 정리
            mw_ref = ctx.main_window
            if mw_ref:
                if hasattr(mw_ref, '_master_filter_snapshot'):
                    mw_ref._master_filter_snapshot = None
            mw = ctx.main_window

            # AppContext 이벤트 구독 해제
            for event_name in ["generation_result_available", "result_enhance_completed", "prompt_generated", "api_mode_changed", "generation_started", "image_saved", "desktop_window_visibility_changed", "cloudflared_status_changed", "save_directory_changed"]:
                if event_name in ctx.subscribers:
                    ctx.subscribers[event_name] = [
                        cb for cb in ctx.subscribers[event_name]
                        if not hasattr(cb, '__self__') or cb.__self__ is not _bridge_instance
                    ]

            # textChanged 연결 해제
            try:
                mw.main_prompt_textedit.textChanged.disconnect(_bridge_instance._on_prompt_text_changed)
                mw.negative_prompt_textedit.textChanged.disconnect(_bridge_instance._on_prompt_text_changed)
            except TypeError:
                pass


            # 체크박스 toggled 연결 해제 (메서드 참조이므로 disconnect 가능)
            for cb, signal_name in _checkbox_connections:
                try:
                    getattr(cb, signal_name).disconnect(_bridge_instance._on_option_toggled_slot)
                except TypeError:
                    pass

            for obj, signal_name, callback in _bridge_signal_connections:
                try:
                    getattr(obj, signal_name).disconnect(callback)
                except TypeError:
                    pass

            # 파라미터 위젯 시그널 연결 해제
            for widget, signal_name in _param_signal_sources:
                try:
                    getattr(widget, signal_name).disconnect(_bridge_instance._on_param_changed_slot)
                except TypeError:
                    pass

            # TabController tab_added 연결 해제
            if mw and hasattr(mw, 'image_window') and mw.image_window:
                tc = getattr(mw.image_window, 'tab_controller', None)
                if tc:
                    try:
                        tc.tab_added.disconnect(_bridge_instance._on_tab_added)
                    except TypeError:
                        pass

            # 디바운스 타이머 정리
            if _bridge_instance._prompt_debounce_timer:
                _bridge_instance._prompt_debounce_timer.stop()
            if _bridge_instance._params_debounce_timer:
                _bridge_instance._params_debounce_timer.stop()
        except Exception:
            pass

        _bridge_instance = None

    _checkbox_connections = []
    _param_signal_sources = []
    _bridge_signal_connections = []
