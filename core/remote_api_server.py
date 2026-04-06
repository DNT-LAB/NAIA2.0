"""
NAIA Remote API Server
- FastAPI + uvicorn을 daemon thread에서 실행
- RemoteBridge(QObject)로 FastAPI ↔ Qt 메인 스레드 간 통신
- WebSocket으로 실시간 이미지 푸시
"""
import io
import json
import asyncio
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response, JSONResponse

from PyQt6.QtCore import QObject, pyqtSignal, Qt, QTimer


# ---------------------------------------------------------------------------
# WebSocket Manager
# ---------------------------------------------------------------------------
class WebSocketManager:
    """연결된 WebSocket 클라이언트 관리 및 broadcast"""

    def __init__(self):
        self.active_connections: set[WebSocket] = set()

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active_connections.add(ws)
        print(f"🌐 Remote client connected (total: {len(self.active_connections)})")

    async def disconnect(self, ws: WebSocket):
        self.active_connections.discard(ws)
        print(f"🌐 Remote client disconnected (total: {len(self.active_connections)})")

    async def broadcast_image(self, webp_bytes: bytes, metadata: dict):
        """모든 클라이언트에 메타데이터(JSON) + 이미지(binary) 전송"""
        meta_text = json.dumps({"type": "image_meta", **metadata})
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
        text = json.dumps(data)
        dead = set()
        for ws in list(self.active_connections):
            try:
                await ws.send_text(text)
            except Exception:
                dead.add(ws)
        self.active_connections -= dead


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
    request_generate = pyqtSignal(str, str)      # (prompt, negative) — 빈 문자열이면 현재 UI 사용
    request_random = pyqtSignal()
    request_set_option = pyqtSignal(str, bool)   # (option_key, checked)
    request_set_prompt = pyqtSignal(str, str)     # (prompt, negative_prompt)
    request_set_mode = pyqtSignal(str)            # API 모드 변경 (NAI/WEBUI/COMFYUI)
    request_set_api_url = pyqtSignal(str, str)    # (mode, url) — WebUI/ComfyUI URL 설정
    request_test_api = pyqtSignal(str)            # mode — API 연결 테스트
    request_set_param = pyqtSignal(str, str)      # (key, value) — 생성 파라미터 변경
    request_get_module = pyqtSignal(str)           # module_id — 모듈 상태 요청
    request_set_module = pyqtSignal(str, str, str) # (module_id, key, value) — 모듈 파라미터 변경
    request_search = pyqtSignal(str)               # search_params JSON
    request_load_parquet = pyqtSignal(str)          # filename
    request_depth_action = pyqtSignal(str)          # depth search action JSON
    request_restore_snapshot = pyqtSignal()          # 메인 검색 결과 스냅샷 복원

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
        self.latest_metadata: Optional[dict] = None
        self._image_history: list = []  # [(webp_bytes, metadata), ...] 최대 200장
        self._ws_manager: Optional[WebSocketManager] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._syncing_option = False
        self._syncing_prompt = False
        self._syncing_param = False
        self._prompt_debounce_timer: Optional[QTimer] = None
        self._params_debounce_timer: Optional[QTimer] = None
        self._auto_generate_pending = False  # prompt_generated 이벤트 기반 자동생성
        # 캐시: FastAPI 스레드에서 Qt 위젯 직접 접근 방지
        self._cached_prompts: dict = {}
        self._cached_params: dict = {}
        self._cached_options: dict = {}
        self._cached_api_status: dict = {}

    def set_ws_manager(self, ws_manager: WebSocketManager):
        self._ws_manager = ws_manager

    def set_event_loop(self, loop: asyncio.AbstractEventLoop):
        self._loop = loop

    def _has_clients(self) -> bool:
        return bool(self._ws_manager and self._ws_manager.active_connections)

    # --- 캐시 갱신 (Qt 메인 스레드에서 호출) ---

    def _update_cache_all(self):
        """모든 캐시를 갱신 (서버 시작 시 + WS 연결 시)"""
        self._cached_prompts = self.get_current_prompts()
        self._cached_params = self.get_generation_params()
        self._cached_options = {"type": "options", **self.get_options()}
        self._cached_api_status = self.get_api_status()

    # --- 시그널 슬롯 래퍼 (lambda 대신 disconnect 가능) ---

    def _on_option_toggled_slot(self, checked=None):
        """체크박스 toggled → 옵션 브로드캐스트"""
        self.broadcast_options()

    def _on_param_changed_slot(self, *args):
        """파라미터 위젯 변경 → 파라미터 브로드캐스트"""
        self._on_params_changed()

    # --- Qt 메인 스레드에서 실행되는 슬롯 ---

    def _do_generate(self, prompt: str, negative: str):
        """현재 UI 파라미터로 생성 트리거. prompt가 있으면 먼저 반영"""
        try:
            gc = self.app_context.main_window.generation_controller
            if gc.is_generating:
                print("🌐 Remote: 이미 생성 중 — 무시")
                self._broadcast_json({"type": "status", "is_generating": True, "message": "already_generating"})
                return
            # 웹에서 보낸 프롬프트가 있으면 즉시 반영 (디바운스 대기 없이)
            if prompt or negative:
                self._syncing_prompt = True
                mw = self.app_context.main_window
                if prompt:
                    mw.main_prompt_textedit.setPlainText(prompt)
                if negative:
                    mw.negative_prompt_textedit.setPlainText(negative)
                self._syncing_prompt = False
            gc.execute_generation_pipeline(priority=0)
            self._broadcast_json({"type": "status", "is_generating": True})
            print("🌐 Remote: 생성 트리거됨")
        except Exception as e:
            print(f"🌐 Remote: 생성 트리거 실패 — {e}")

    def _do_random(self):
        """랜덤 프롬프트 생성. auto_generate ON이면 prompt_generated 이벤트에서 자동 트리거"""
        try:
            mw = self.app_context.main_window
            auto_gen = mw.generation_checkboxes.get("자동 생성")
            if auto_gen and auto_gen.isChecked():
                self._auto_generate_pending = True

            mw.trigger_random_prompt()
            print("🌐 Remote: 랜덤 프롬프트 생성됨")
        except Exception as e:
            print(f"🌐 Remote: 랜덤 프롬프트 생성 실패 — {e}")

    # --- 옵션 동기화 (Qt 메인 스레드에서 실행) ---

    def _do_set_option(self, key: str, checked: bool):
        """웹에서 토글한 옵션을 메인 앱 체크박스에 반영"""
        try:
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
        """웹에서 입력한 API URL을 저장"""
        try:
            url = url.strip()
            if not url:
                self._broadcast_json({"type": "api_config_result", "success": False,
                                      "message": "URL is empty"})
                return
            if not self._is_local_url(url):
                self._broadcast_json({"type": "api_config_result", "success": False,
                                      "message": "Only local/LAN addresses allowed here"})
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

    def get_api_status(self) -> dict:
        """각 모드의 설정 상태 반환"""
        stm = self.app_context.secure_token_manager
        return {
            "type": "api_status",
            "nai_configured": bool(stm.get_token("nai_token")),
            "webui_url": stm.get_token("webui_url") or "",
            "comfyui_url": stm.get_token("comfyui_url") or "",
        }

    def _broadcast_api_status(self):
        self._cached_api_status = self.get_api_status()
        if self._has_clients():
            self._broadcast_json(self._cached_api_status)

    def on_api_mode_changed(self, data: dict):
        """api_mode_changed 이벤트 → 웹 클라이언트에 브로드캐스트"""
        if not self._has_clients():
            return
        new_mode = data.get("new_mode", "")
        self._broadcast_json({"type": "mode", "mode": new_mode})
        # 모드 변경 시 파라미터도 갱신 (모드별 옵션이 다르므로)
        self._broadcast_params()

    def get_options(self) -> dict:
        """현재 옵션 상태 반환"""
        try:
            mw = self.app_context.main_window
            return {
                key: mw.generation_checkboxes[label].isChecked()
                for key, label in self.OPTION_KEYS.items()
                if label in mw.generation_checkboxes
            }
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

    def _do_set_prompt(self, prompt: str, negative: str):
        """웹에서 편집한 프롬프트를 메인 앱에 반영"""
        try:
            self._syncing_prompt = True
            mw = self.app_context.main_window
            mw.main_prompt_textedit.setPlainText(prompt)
            mw.negative_prompt_textedit.setPlainText(negative)
            self._syncing_prompt = False
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
        """현재 프롬프트 캐시 갱신 + WS 클라이언트에 전송"""
        data = self.get_current_prompts()
        if data:
            self._cached_prompts = data
            if self._has_clients():
                self._broadcast_json(data)

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
            elif mode == "COMFYUI":
                if hasattr(mw, 'eps_radio'):
                    if mw.eps_radio.isChecked():
                        params["sampling_mode"] = "eps"
                    elif mw.v_pred_radio.isChecked():
                        params["sampling_mode"] = "v_prediction"
                    elif mw.anima_radio.isChecked():
                        params["sampling_mode"] = "anima"
                    else:
                        params["sampling_mode"] = "eps"
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
        }
        target_class = class_map.get(module_id)
        if not target_class:
            return None
        for module in msc.module_instances:
            if module.__class__.__name__ == target_class:
                return module
        return None

    def _do_get_module(self, module_id: str):
        """모듈 상태 읽기 → 브로드캐스트"""
        if module_id == "__search__":
            state = self._read_search_state()
        elif module_id == "__depth__":
            state = self._read_depth_state()
        else:
            state = self._read_module_state(module_id)
        if state:
            self._broadcast_json(state)

    def _read_module_state(self, module_id: str) -> dict:
        """모듈 상태 딕셔너리 반환"""
        if module_id == "prompt_engineering":
            return self._read_prompt_engineering()
        elif module_id == "automation":
            return self._read_automation()
        elif module_id == "character":
            return self._read_character()
        return {}

    def _read_prompt_engineering(self) -> dict:
        try:
            m = self._find_module("prompt_engineering")
            if not m:
                return {}
            preprocessing = {}
            for label, cb in m.preprocessing_checkboxes.items():
                key = m.option_key_map.get(label, label)
                preprocessing[key] = cb.isChecked()
            presets = [m.preset_combo.itemText(i) for i in range(m.preset_combo.count())]
            return {
                "type": "module_state",
                "module_id": "prompt_engineering",
                "preset": m.preset_combo.currentText(),
                "preset_options": presets,
                "pre_prompt": m.pre_textedit.toPlainText(),
                "post_prompt": m.post_textedit.toPlainText(),
                "auto_hide": m.auto_hide_textedit.toPlainText(),
                "preprocessing": preprocessing,
            }
        except Exception as e:
            print(f"🌐 Remote: 모듈 상태 읽기 실패 — {e}")
            return {}

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
            return {
                "type": "module_state",
                "module_id": "character",
                "activated": m.activate_checkbox.isChecked() if m.activate_checkbox else False,
                "reroll_on_generate": m.reroll_on_generate_checkbox.isChecked() if m.reroll_on_generate_checkbox else False,
                "characters": characters,
            }
        except Exception as e:
            print(f"🌐 Remote: character 상태 읽기 실패 — {e}")
            return {}

    def _do_set_module(self, module_id: str, key: str, value: str):
        """웹에서 변경한 모듈 파라미터를 메인 앱에 반영"""
        if module_id == "prompt_engineering":
            self._set_prompt_engineering(key, value)
        elif module_id == "automation":
            self._set_automation(key, value)
        elif module_id == "character":
            self._set_character(key, value)

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
            elif key.startswith("pp_"):
                # preprocessing option: pp_remove_author → remove_author
                pp_key = key[3:]
                # option_key_map 역참조: value→label
                for label, opt_key in m.option_key_map.items():
                    if opt_key == pp_key:
                        cb = m.preprocessing_checkboxes.get(label)
                        if cb:
                            cb.setChecked(value == "true")
                        break
        except Exception as e:
            print(f"🌐 Remote: 모듈 설정 실패 — {key}={value}: {e}")

    def _set_automation(self, key: str, value: str):
        try:
            m = self._find_module("automation")
            if not m:
                return
            if key == "delay":
                m.delay_input.setText(value)
            elif key == "random_delay":
                m.random_delay_checkbox.setChecked(value == "true")
            elif key == "repeat":
                m.repeat_input.setText(value)
            elif key == "auto_type":
                v = int(value)
                if v == 0 and m.unlimited_radio:
                    m.unlimited_radio.setChecked(True)
                elif v == 1 and m.timer_radio:
                    m.timer_radio.setChecked(True)
                elif v == 2 and m.count_radio:
                    m.count_radio.setChecked(True)
            elif key == "timer_minutes":
                if m.timer_input:
                    m.timer_input.setText(value)
            elif key == "count_limit":
                if m.count_input:
                    m.count_input.setText(value)
            elif key == "notify":
                if m.notify_checkbox:
                    m.notify_checkbox.setChecked(value == "true")
            elif key == "start":
                m.start_automation()
            elif key == "stop":
                m.stop_automation()
        except Exception as e:
            print(f"🌐 Remote: automation 설정 실패 — {key}={value}: {e}")

    def _set_character(self, key: str, value: str):
        try:
            m = self._find_module("character")
            if not m:
                return
            if key == "activated":
                m.activate_checkbox.setChecked(value == "true")
            elif key == "reroll_on_generate":
                if m.reroll_on_generate_checkbox:
                    m.reroll_on_generate_checkbox.setChecked(value == "true")
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
        except Exception as e:
            print(f"🌐 Remote: character 설정 실패 — {key}={value}: {e}")

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
            return {
                "type": "search_state",
                "count": count,
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
                        cb.setChecked(params.get(f"rating_{k}", True))
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
        tc = getattr(self.app_context, 'tab_controller', None)
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
            return {
                "type": "depth_state",
                "open": True,
                "count": count,
                "original": original,
                "query": dw.d_search_input.text() if hasattr(dw, 'd_search_input') else "",
                "exclude": dw.d_exclude_input.text() if hasattr(dw, 'd_exclude_input') else "",
            }
        except Exception as e:
            print(f"🌐 Remote: depth 상태 읽기 실패 — {e}")
            return {"type": "depth_state", "open": False}

    def _do_depth_action(self, params_json: str):
        try:
            params = json.loads(params_json)
            action = params.get("action", "")
            mw = self.app_context.main_window

            if action == "open":
                # 심층검색 탭 열기
                if mw and hasattr(mw, 'open_depth_search_tab'):
                    mw.open_depth_search_tab()
                    # 탭이 준비되면 상태 전송 (약간의 지연 필요)
                    QTimer.singleShot(2000, lambda: self._broadcast_depth_state())
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
                if hasattr(dw, 'rating_checkboxes'):
                    for k in ('e', 'q', 's', 'g'):
                        cb = dw.rating_checkboxes.get(k)
                        if cb:
                            cb.setChecked(ratings.get(k, True))
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

        except Exception as e:
            print(f"🌐 Remote: depth action 실패 — {e}")

    def _do_restore_snapshot(self):
        """메인 검색 결과를 스냅샷에서 복원"""
        try:
            mw = self.app_context.main_window
            if not mw:
                return
            if hasattr(mw, '_restore_from_snapshot'):
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

    def _broadcast_depth_state(self):
        state = self._read_depth_state()
        if state:
            self._broadcast_json(state)

    # --- AppContext 이벤트 콜백 (Qt 메인 스레드에서 호출됨) ---

    def on_prompt_generated(self, prompt_context):
        """프롬프트 생성 완료 시 WebSocket 전송 + 자동생성 트리거"""
        try:
            # 자동생성 대기 중이면 이미지 생성 트리거
            if self._auto_generate_pending:
                self._auto_generate_pending = False
                gc = self.app_context.main_window.generation_controller
                if not gc.is_generating:
                    gc.execute_generation_pipeline(priority=0)
                    self._broadcast_json({"type": "status", "is_generating": True})
                    print("🌐 Remote: 자동생성 트리거됨")

            if not self._has_clients():
                return
            prompt = prompt_context.final_prompt or ""
            mw = self.app_context.main_window
            remaining = mw.search_results.get_count() if mw and mw.search_results else 0
            if self._loop and self._ws_manager:
                data = {"type": "prompt_generated", "prompt": prompt, "remaining": remaining}
                asyncio.run_coroutine_threadsafe(
                    self._ws_manager.broadcast_json(data),
                    self._loop
                )
        except Exception as e:
            self._auto_generate_pending = False
            print(f"🌐 Remote: 프롬프트 전송 실패 — {e}")

    def on_generation_result(self, result: dict):
        """생성 완료 시 PIL→WebP 변환 후 캐시 저장 + WebSocket broadcast"""
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
                "prompt": gen_params.get("input", ""),
                "negative_prompt": gen_params.get("negative_prompt", ""),
                "seed": gen_params.get("seed", ""),
                "steps": gen_params.get("steps", ""),
                "cfg_scale": gen_params.get("cfg_scale", ""),
                "sampler": gen_params.get("sampler", ""),
                "model": gen_params.get("model", ""),
            }

            # 항상 캐시 (클라이언트 없어도 다음 접속 시 전송 가능)
            self.latest_webp = webp_bytes
            self.latest_metadata = metadata
            self._image_history.append((webp_bytes, metadata))
            if len(self._image_history) > 200:
                self._image_history.pop(0)

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
        bridge.request_generate.emit("", "")
        return {"status": "generation_requested"}

    @app.post("/api/random")
    async def api_random():
        bridge.request_random.emit()
        return {"status": "random_generation_requested"}

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

    @app.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket):
        await ws_manager.connect(ws)
        try:
            # 연결 시 히스토리 전체 전송 (새로고침 복원)
            for hist_webp, hist_meta in bridge._image_history:
                await ws.send_text(json.dumps({"type": "image_meta", **hist_meta}))
                await ws.send_bytes(hist_webp)
            current_mode = bridge.app_context.get_api_mode()
            await ws.send_text(json.dumps({"type": "mode", "mode": current_mode}))
            if bridge._cached_options:
                await ws.send_text(json.dumps(bridge._cached_options))
            if bridge._cached_prompts:
                await ws.send_text(json.dumps(bridge._cached_prompts))
            if bridge._cached_params:
                await ws.send_text(json.dumps(bridge._cached_params))
            if bridge._cached_api_status:
                await ws.send_text(json.dumps(bridge._cached_api_status))

            while True:
                data = await ws.receive_text()
                if data == "generate":
                    bridge.request_generate.emit("", "")
                elif data == "random":
                    bridge.request_random.emit()
                elif data == "sync":
                    if bridge._cached_prompts:
                        await ws.send_text(json.dumps(bridge._cached_prompts))
                    if bridge._cached_params:
                        await ws.send_text(json.dumps(bridge._cached_params))
                elif data.startswith("{"):
                    try:
                        cmd = json.loads(data)
                        cmd_type = cmd.get("type")
                        if cmd_type == "set_option":
                            bridge.request_set_option.emit(cmd["key"], cmd["value"])
                        elif cmd_type == "set_prompt":
                            bridge.request_set_prompt.emit(
                                cmd.get("prompt", ""),
                                cmd.get("negative_prompt", "")
                            )
                        elif cmd_type == "set_mode":
                            bridge.request_set_mode.emit(cmd.get("mode", ""))
                        elif cmd_type == "set_param":
                            v = cmd.get("value", "")
                            bridge.request_set_param.emit(
                                cmd.get("key", ""), str(v).lower() if isinstance(v, bool) else str(v))
                        elif cmd_type == "set_api_url":
                            bridge.request_set_api_url.emit(
                                cmd.get("mode", ""), cmd.get("url", ""))
                        elif cmd_type == "test_api":
                            bridge.request_test_api.emit(cmd.get("mode", ""))
                        elif cmd_type == "get_module_state":
                            bridge.request_get_module.emit(cmd.get("module_id", ""))
                        elif cmd_type == "set_module_param":
                            bridge.request_set_module.emit(
                                cmd.get("module_id", ""),
                                cmd.get("key", ""),
                                str(cmd.get("value", "")))
                        elif cmd_type == "get_search_state":
                            bridge.request_get_module.emit("__search__")
                        elif cmd_type == "search":
                            bridge.request_search.emit(json.dumps(cmd))
                        elif cmd_type == "load_parquet":
                            bridge.request_load_parquet.emit(cmd.get("filename", ""))
                        elif cmd_type == "depth_action":
                            bridge.request_depth_action.emit(json.dumps(cmd))
                        elif cmd_type == "get_depth_state":
                            bridge.request_get_module.emit("__depth__")
                        elif cmd_type == "restore_snapshot":
                            bridge.request_restore_snapshot.emit()
                        elif cmd_type == "generate":
                            # 프롬프트 포함 생성 요청
                            bridge.request_generate.emit(
                                cmd.get("prompt", ""),
                                cmd.get("negative_prompt", "")
                            )
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


def start_remote_server(app_context, host: str = "0.0.0.0", port: int = 7243):
    """Remote API 서버를 daemon thread로 시작."""
    global _server_instance, _bridge_instance, _checkbox_connections, _param_signal_sources

    if _server_instance is not None:
        print("🌐 Remote: 서버가 이미 실행 중")
        return _server_instance

    ws_manager = WebSocketManager()
    bridge = RemoteBridge(app_context)
    bridge.set_ws_manager(ws_manager)
    _bridge_instance = bridge

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

    # 검색 컨트롤러 시그널 연결
    mw = app_context.main_window
    if mw and hasattr(mw, 'search_controller'):
        mw.search_controller.search_progress.connect(bridge._on_search_progress)
        mw.search_controller.search_complete.connect(bridge._on_search_complete)

    # AppContext 이벤트 구독
    app_context.subscribe("generation_result_available", bridge.on_generation_result)
    app_context.subscribe("prompt_generated", bridge.on_prompt_generated)
    app_context.subscribe("api_mode_changed", bridge.on_api_mode_changed)

    # 메인 UI 위젯 연결
    mw = app_context.main_window
    mw.main_prompt_textedit.textChanged.connect(bridge._on_prompt_text_changed)
    mw.negative_prompt_textedit.textChanged.connect(bridge._on_prompt_text_changed)

    # 생성 상태 이벤트 (메인 UI/자동생성 포함 전체 감지)
    app_context.subscribe("generation_started", bridge._on_generation_started_signal)

    # 체크박스 변경 → 웹 동기화 (메서드 참조로 disconnect 가능)
    _checkbox_connections = []
    for key, label in RemoteBridge.OPTION_KEYS.items():
        cb = mw.generation_checkboxes.get(label)
        if cb:
            cb.toggled.connect(bridge._on_option_toggled_slot)
            _checkbox_connections.append((cb, "toggled"))

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
    global _server_instance, _bridge_instance, _checkbox_connections, _param_signal_sources

    if _server_instance:
        _server_instance.should_exit = True
        print("🌐 Remote API server stopping...")
        _server_instance = None

    if _bridge_instance:
        try:
            ctx = _bridge_instance.app_context
            mw = ctx.main_window

            # AppContext 이벤트 구독 해제
            for event_name in ["generation_result_available", "prompt_generated", "api_mode_changed", "generation_started"]:
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

            # 파라미터 위젯 시그널 연결 해제
            for widget, signal_name in _param_signal_sources:
                try:
                    getattr(widget, signal_name).disconnect(_bridge_instance._on_param_changed_slot)
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
