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
import copy
import hashlib
import math
import mimetypes
import random
import re
import socket
import tempfile
import time
import threading
import uuid
import urllib.error
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import quote, urljoin, urlparse

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import FileResponse, Response, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from PyQt6.QtCore import QObject, pyqtSignal, Qt, QTimer, QThread, QCoreApplication
from PyQt6.QtWidgets import QFileDialog

from core import api_verification
from core.danbooru_client import DANBOORU_BASE_URL, fetch_danbooru_post
from core.character_viewer_service import CharacterViewerService
from core.clothes_preset_service import ClothesPresetService
from core.event_preset_service import EventPresetService
from core.expression_preset_service import ExpressionPresetService
from core.kr_tag_loader import format_kr_tag_load_summary, load_kr_tag_records
from core.preset_input_bridge import PresetInputBridge, update_app_preset_context
from core.preset_composer_service import PresetComposerService
from core.tag_relation_ranker import TagRelationRanker
from core.vibe_cluster_resolver import is_valid_vibe_cluster_name, search_vibe_clusters
from core.kr_phrase_canonicalizer import match_kr_phrase_canonical_tags
from core.kr_sentence_reconstructor import reconstruct_kr_tag_queries
from core.nai_vibe_limits import MAX_NAI_VIBE_REFERENCES, NAI_VIBE_INCLUDED_REFERENCES
from core.tag_search_index import TagSearchIndex, normalize_search_query
from core.resolution_utils import (
    MAX_1MP_PIXELS,
    STANDARD_1MP_RESOLUTIONS,
    STANDARD_1MP_RESOLUTION_LABELS,
    normalize_anima_resolution_preset_id,
    nearest_standard_1mp_resolution,
    parse_resolution_pair,
)
from utils.translator import korean_to_english
from utils.clipboard_image import clipboard_png_bytes, set_png_clipboard_bytes
from utils.webui_generation_info import extract_webui_seed
from ui.event_preset.download_worker import DOWNLOAD_URL as EVENT_PRESET_DOWNLOAD_URL
from ui.event_preset.download_worker import SSL_CONTEXT as EVENT_PRESET_SSL_CONTEXT
from ui.event_preset.download_worker import THUMBNAIL_DOWNLOAD_URL as EVENT_PRESET_THUMBNAIL_DOWNLOAD_URL


_AUTOCOMPLETE_TRANSLATION_RULES_PATH = (
    Path(__file__).resolve().parent.parent
    / "data"
    / "tag_index"
    / "autocomplete_translation_rules.json"
)
_AUTOCOMPLETE_RESULT_CACHE_MAX = 128


def _normalize_autocomplete_rule_token(value) -> str:
    return str(value or "").strip().lower()


def _load_autocomplete_translation_rules() -> dict:
    try:
        with _AUTOCOMPLETE_TRANSLATION_RULES_PATH.open("r", encoding="utf-8") as f:
            loaded = json.load(f)
        return loaded if isinstance(loaded, dict) else {}
    except Exception as exc:
        print(f"Remote: autocomplete translation rules load failed - {exc}")
        return {}


def _autocomplete_rule_list(rules: dict, key: str) -> set[str]:
    value = rules.get(key, [])
    if not isinstance(value, list):
        return set()
    return {
        token
        for token in (_normalize_autocomplete_rule_token(item) for item in value)
        if token
    }


def _autocomplete_rule_aliases(rules: dict, key: str) -> dict[str, tuple[str, ...]]:
    value = rules.get(key, {})
    if not isinstance(value, dict):
        return {}
    aliases: dict[str, tuple[str, ...]] = {}
    for raw_key, raw_values in value.items():
        alias_key = _normalize_autocomplete_rule_token(raw_key)
        if not alias_key or not isinstance(raw_values, list):
            continue
        alias_values = tuple(
            token
            for token in (
                _normalize_autocomplete_rule_token(item) for item in raw_values
            )
            if token
        )
        if alias_values:
            aliases[alias_key] = alias_values
    return aliases


def _autocomplete_action_verbs(rules: dict) -> dict[str, str]:
    value = rules.get("action_verbs", {})
    if not isinstance(value, dict):
        return {}
    actions: dict[str, str] = {}
    for raw_key, raw_value in value.items():
        key = _normalize_autocomplete_rule_token(raw_key)
        action = _normalize_autocomplete_rule_token(raw_value)
        if key and action:
            actions[key] = action
    return actions


def _autocomplete_domain_alias_rules(rules: dict) -> list[dict]:
    value = rules.get("domain_phrase_alias_rules", [])
    return [rule for rule in value if isinstance(rule, dict)] if isinstance(value, list) else []


def _autocomplete_protected_kr_phrases(rules: dict) -> tuple[dict[str, object], ...]:
    value = rules.get("protected_kr_phrases", [])
    if not isinstance(value, list):
        return ()
    protected = []
    for raw_rule in value:
        if not isinstance(raw_rule, dict):
            continue
        source = _normalize_autocomplete_rule_token(raw_rule.get("source"))
        target = _normalize_autocomplete_rule_token(raw_rule.get("target"))
        if not source or not target:
            continue
        bad_phrases = raw_rule.get("bad_phrases", [])
        if isinstance(bad_phrases, str):
            bad_phrases = [bad_phrases]
        source_exclusion_terms = raw_rule.get("source_exclusion_terms", [])
        if isinstance(source_exclusion_terms, str):
            source_exclusion_terms = [source_exclusion_terms]
        protected.append(
            {
                "source": source,
                "target": target,
                "bad_phrases": tuple(
                    token
                    for token in (
                        _normalize_autocomplete_rule_token(item)
                        for item in bad_phrases
                    )
                    if token
                ),
                "source_exclusion_terms": tuple(
                    token
                    for token in (
                        _normalize_autocomplete_rule_token(item)
                        for item in source_exclusion_terms
                    )
                    if token
                ),
            }
        )
    return tuple(protected)


_AUTOCOMPLETE_TRANSLATION_RULES = _load_autocomplete_translation_rules()
_AUTOCOMPLETE_TRANSLATION_STOPWORDS = _autocomplete_rule_list(
    _AUTOCOMPLETE_TRANSLATION_RULES,
    "stopwords",
)
_AUTOCOMPLETE_TRANSLATION_PRONOUNS = _autocomplete_rule_list(
    _AUTOCOMPLETE_TRANSLATION_RULES,
    "pronouns",
)
_AUTOCOMPLETE_TRANSLATION_POSSESSIVES = _autocomplete_rule_list(
    _AUTOCOMPLETE_TRANSLATION_RULES,
    "possessives",
)
_AUTOCOMPLETE_TRANSLATION_ACTOR_WORDS = _autocomplete_rule_list(
    _AUTOCOMPLETE_TRANSLATION_RULES,
    "actor_words",
)
_AUTOCOMPLETE_TRANSLATION_PARTICLES = _autocomplete_rule_list(
    _AUTOCOMPLETE_TRANSLATION_RULES,
    "particles",
)
_AUTOCOMPLETE_WEAK_POSE_VERBS = _autocomplete_rule_list(
    _AUTOCOMPLETE_TRANSLATION_RULES,
    "weak_pose_verbs",
)
_AUTOCOMPLETE_RELATION_PREPOSITIONS = _autocomplete_rule_list(
    _AUTOCOMPLETE_TRANSLATION_RULES,
    "relation_prepositions",
)
_AUTOCOMPLETE_RELATION_OBJECT_ALIASES = _autocomplete_rule_aliases(
    _AUTOCOMPLETE_TRANSLATION_RULES,
    "relation_object_aliases",
)
_AUTOCOMPLETE_LOW_VALUE_SINGLE_TOKENS = _autocomplete_rule_list(
    _AUTOCOMPLETE_TRANSLATION_RULES,
    "low_value_single_tokens",
)
_AUTOCOMPLETE_BODY_RELATION_SUBJECTS = _autocomplete_rule_list(
    _AUTOCOMPLETE_TRANSLATION_RULES,
    "body_relation_subjects",
)
_AUTOCOMPLETE_ACTION_VERBS = _autocomplete_action_verbs(
    _AUTOCOMPLETE_TRANSLATION_RULES
)
_AUTOCOMPLETE_ACTION_FORMS = {
    **_AUTOCOMPLETE_ACTION_VERBS,
    **{value: value for value in _AUTOCOMPLETE_ACTION_VERBS.values()},
}
_AUTOCOMPLETE_TRANSITIVE_ACTION_FORMS = {
    _AUTOCOMPLETE_ACTION_VERBS[action]
    for action in _autocomplete_rule_list(
        _AUTOCOMPLETE_TRANSLATION_RULES,
        "transitive_action_verbs",
    )
    if action in _AUTOCOMPLETE_ACTION_VERBS
}
_AUTOCOMPLETE_DOMAIN_PHRASE_ALIAS_RULES = _autocomplete_domain_alias_rules(
    _AUTOCOMPLETE_TRANSLATION_RULES
)
_AUTOCOMPLETE_PROTECTED_KR_PHRASES = _autocomplete_protected_kr_phrases(
    _AUTOCOMPLETE_TRANSLATION_RULES
)
_AUTOCOMPLETE_EXPLICIT_QUERY_MARKERS = (
    "sex",
    "sexual",
    "penis",
    "pussy",
    "vulva",
    "genital",
    "genitals",
    "anus",
    "anal",
    "cum",
    "semen",
    "ejaculation",
    "fellatio",
    "cunnilingus",
    "masturbation",
    "handjob",
    "penetration",
    "orgasm",
    "dildo",
    "vibrator",
    "섹스",
    "성행위",
    "성관계",
    "성교",
    "삽입",
    "펠라",
    "펠라치오",
    "커닐링구스",
    "자위",
    "사정",
    "정액",
    "남성기",
    "여성기",
    "성기",
    "음부",
    "보지",
    "자지",
    "항문",
    "애널",
    "딜도",
    "바이브레이터",
    "스팽킹",
)
_AUTOCOMPLETE_SENSITIVE_QUERY_MARKERS = (
    "breast",
    "breasts",
    "nipple",
    "nipples",
    "panty",
    "panties",
    "bra",
    "nude",
    "naked",
    "cleavage",
    "crotch",
    "thigh",
    "ass",
    "butt",
    "armpit",
    "navel",
    "censor",
    "censored",
    "mosaic",
    "see-through",
    "가슴",
    "유두",
    "젖꼭지",
    "팬티",
    "브라",
    "브래지어",
    "나체",
    "알몸",
    "누드",
    "노출",
    "가랑이",
    "엉덩이",
    "허벅지",
    "겨드랑이",
    "배꼽",
    "복부",
    "검열",
    "모자이크",
    "검은 막대",
    "막대 검열",
    "시스루",
    "블루머",
    "부르마",
    "포켓몬",
)
_AUTOCOMPLETE_EXPLICIT_CANDIDATE_MARKERS = (
    *_AUTOCOMPLETE_EXPLICIT_QUERY_MARKERS,
    "bdsm",
    "bondage",
    "fetish",
    "threesome",
    "foursome",
    "fivesome",
    "harem",
    "gangbang",
    "rape",
    "molestation",
    "chikan",
    "spanking",
    "pokephilia",
    "upskirt",
    "crotch",
    "nipple",
    "nipples",
    "areola",
    "clitoris",
    "labia",
    "glans",
    "testicles",
    "scrotum",
    "erection",
    "urination",
    "feces",
    "scat",
    "guro",
    "vore",
    "성인",
    "성적",
    "페티시",
    "강간",
    "치한",
    "스팽킹",
)
_AUTOCOMPLETE_SENSITIVE_CANDIDATE_MARKERS = (
    *_AUTOCOMPLETE_SENSITIVE_QUERY_MARKERS,
    "underwear",
    "lingerie",
    "bloomers",
    "buruma",
    "swimsuit",
    "bikini",
    "topless",
    "bottomless",
    "sideboob",
    "underboob",
    "cameltoe",
    "see-through",
    "wardrobe malfunction",
    "속옷",
    "수영복",
    "비키니",
)
_AUTOCOMPLETE_EXPLICIT_GROUP_MARKERS = (
    "nsfw",
    "danger",
    "h >",
    "h>",
    "explicit",
    "sexual",
    "adult",
    "성인",
    "성적",
    "성행위",
    "페티시",
)


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
            "tag_filter": None,
            "tag_filter_pending": None,
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
    request_resolution_action = pyqtSignal(str)   # request_id — 해상도 목록 조회/저장
    request_get_module = pyqtSignal(object, str)    # (ws, module_id) — 모듈 상태 요청
    request_set_module = pyqtSignal(str, str, str) # (module_id, key, value) — 모듈 파라미터 변경
    request_artist_thumb_random_peng = pyqtSignal(str, str)  # (request_id, artist_prompt)
    request_search = pyqtSignal(str)               # search_params JSON
    request_load_parquet = pyqtSignal(str)          # filename
    request_merge_parquet = pyqtSignal(str)         # filename
    request_uploaded_parquet = pyqtSignal(str)      # upload payload JSON
    request_search_parquet_action = pyqtSignal(str) # action JSON
    request_depth_action = pyqtSignal(str)          # depth search action JSON
    request_restore_snapshot = pyqtSignal()          # 메인 검색 결과 스냅샷 복원
    request_apply_filters = pyqtSignal()            # GSQE + Tag Filter → master에서 재적용
    request_refresh_cache = pyqtSignal()               # WS 연결 시 캐시 갱신 + broadcast
    request_set_desktop_visibility = pyqtSignal(bool)  # 메인 데스크탑 창 표시/숨김
    request_send_desktop_sync = pyqtSignal(str)        # request_id — ordered desktop snapshot
    request_result_enhance = pyqtSignal(object, str)    # (ws, json) — 현재/저장 ImageWindow 결과 Enhance
    request_set_result_enhance_config = pyqtSignal(object, str)  # (ws, json) — Enhance 설정 변경
    request_result_reroll = pyqtSignal(str)             # result context JSON — desktop reroll 재사용
    request_result_queue = pyqtSignal(str)              # result context JSON — 결과 이미지를 생성 큐에 추가
    request_result_history_action = pyqtSignal(str)     # request_id — 결과 히스토리 저장/삭제
    request_result_upscale = pyqtSignal(object, str)    # (ws, json) — 현재/저장 결과 NAI 2x upscale
    request_result_image_action = pyqtSignal(str)       # result context JSON — 숨김 img2img 세션 등
    request_image_action = pyqtSignal(str, bytes, str)  # (action, image_bytes, label)
    request_copy_png_to_clipboard = pyqtSignal(bytes, str)  # (png_bytes, filename)
    request_read_clipboard_png = pyqtSignal(str)        # request_id — Qt clipboard PNG read
    request_danbooru_prompt_preview = pyqtSignal(object)  # request dict with event/tags/prompt
    request_open_danbooru_browser = pyqtSignal(str)     # URL — 기존 PyQt6 Danbooru WebView 탭 열기
    request_artist_thumb_generate = pyqtSignal(object)  # Artist Thumbnail generate payload
    request_character_viewer_generate = pyqtSignal(object)  # Character Viewer generate payload
    request_queue_action = pyqtSignal(str)              # queue action JSON — pause/resume/clear/remove
    request_set_cloudflared_enabled = pyqtSignal(bool)  # Cloudflared 연결/해제
    request_comfyui_workflow_action = pyqtSignal(str)   # request_id — ComfyUI workflow load/clear
    request_prompt_preset_thumbnail_generate = pyqtSignal(object)  # sync request dict — Qt thread generation enqueue

    # 동기화 대상 옵션 키 매핑: web_key → checkbox_label
    OPTION_KEYS = {
        "prompt_fixed": "프롬프트 고정",
        "auto_generate": "자동 생성",
        "wildcard_standalone": "와일드카드 단독 모드",
    }
    MEMORY_HISTORY_PATH_PREFIX = "__history__/"
    HISTORY_ITEM_PATH_PREFIX = "__history_item__/"
    STYLE_THUMBNAILS_PATH = Path("data/taglist/style_thumbnails.json")
    STYLE_META_TAGS_PATH = Path("data/taglist/style_meta_tags.json")
    ARTIST_THUMB_MODES = {
        "NAID4.5F-31000": {
            "label": "NAID4.5F-31000",
            "path": Path("data/artist_thumbnail_nai.json"),
            "url": "https://huggingface.co/baqu2213/PoemForSmallFThings/resolve/main/NAIA/NAID4.5_artist_thumbnail_31000/artist_thumbnail_nai",
        },
        "NoobNAI-XL-33000": {
            "label": "NoobNAI-XL-33000",
            "path": Path("data/artist_thumbnail.json"),
            "url": "https://huggingface.co/baqu2213/PoemForSmallFThings/resolve/main/NAIA/Noob_artist_thumbnail_33000/artist_thumbnail",
        },
        "ANIMA-14000": {
            "label": "ANIMA-14000",
            "path": Path("data/artist_thumbnail_anima.json"),
            "url": "https://huggingface.co/baqu2213/PoemForSmallFThings/resolve/main/NAIA/Anima_artist_thumbnail/artist_thumbnail_anima.json",
            "expected_size": 1699850378,
            "sha256": "ACD01B81AB1E3078E2F2F1607D53382D0312B0661C0E7F620F28D7FFBD818A8C",
        },
    }
    ARTIST_THUMB_OPTION_MODES = ("NAI", "WEBUI", "COMFYUI")
    DEFAULT_RESOLUTIONS = list(STANDARD_1MP_RESOLUTION_LABELS)
    PROMPT_ENGINEERING_PRESET_MODES = ("NAI", "WEBUI", "COMFYUI")

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
        self._cached_result_enhance_config: dict = {}
        self._remote_web_ui_state: dict = self._load_remote_web_ui_state()
        self._webui_hiresfix_assist: dict = dict(self._remote_web_ui_state["webui_hiresfix_assist"])
        self._remote_auto_generate_enabled = False
        # api_status 는 per-ws 평가(setup_allowed 가 IP별로 다름)라 캐시하지 않음.
        # 태그 검색 인덱스 (ui/interactive/interactive 기반)
        self._kr_tags_raw: dict = {}  # tag_lower → full info dict (relations, _kw_lower, _desc_lower 포함)
        self._tag_search_index: Optional[TagSearchIndex] = None
        self._tag_relation_ranker: Optional[TagRelationRanker] = None
        self._autocomplete_translation_cache: dict[str, str] = {}
        self._autocomplete_result_cache: dict[tuple[str, int], tuple[list[dict], str]] = {}
        self._prompt_highlight_index_cache: Optional[dict] = None
        self._kr_tags_lock = threading.Lock()
        self._kr_tags_loaded = False
        # 캐릭터 분석 역인덱스: char_name_lower → (copyright_group, data_dict)
        self._char_analysis: dict = {}
        # 서버 측 lazy 인덱스(KR_tags + character_analysis) 워밍업 완료 플래그.
        # 부팅 후 daemon thread 가 warmup → True 로 세팅 + WS broadcast.
        # WS 클라이언트는 init_complete 이후 이 broadcast 를 받아야 사용 가능 시점으로 인지.
        self._lazy_indices_ready = False
        self._search_filter_state = self._load_search_filter_state()
        # Rating 필터: Web Remote GSQE 버튼 상태
        self._active_ratings: set = set(self._search_filter_state.get("ratings") or ['g', 's', 'q', 'e'])
        # Tag filter IDs for remote quick filter.
        self._active_tag_filter_ids: set | None = None
        # 필터 적용 중 _save_search_snapshot에서 reset 방지
        self._skip_filter_reset: bool = False
        # Viewer: 디스크 이미지 스캔 캐시
        self._viewer_cache: list = []
        self._viewer_cache_time: float = 0
        self._viewer_cache_dir: str = ""
        self._cached_e621_event_key: tuple | None = None
        self._cached_e621_event_state: dict | None = None
        self._thumbnail_b64_cache: dict[tuple, str] = {}
        self._character_viewer_grid_thumb_cache: dict[tuple, tuple[bytes, str]] = {}
        # NAI Anlas: 주기 + 생성 이벤트 기반 refresh. 웹 viewer 좌하단에 pill로 표시.
        self._anlas_cache: Optional[dict] = None     # {"anlas": int, "opus": bool, "tier": str, "fetched_at": str}
        self._anlas_timer: Optional[QTimer] = None
        self._anlas_fetch_in_flight: bool = False
        self._anlas_refresh_interval_ms: int = 5 * 60 * 1000  # 5분
        self._remote_enhance_in_flight: bool = False
        self._remote_enhance_api_mode: str = ""
        self._remote_enhance_request_id: str = ""
        self._remote_enhance_thread = None
        self._remote_enhance_worker = None
        self._remote_upscale_in_flight: bool = False
        self._remote_upscale_thread = None
        self._remote_upscale_worker = None
        self._remote_img2img_window_id: Optional[int] = None
        self._remote_img2img_source_label: str = ""
        self._danbooru_browser_window = None
        self._danbooru_browser_widget = None
        self._danbooru_prompt_preview_bridge_connected = False
        self._style_thumb_meta_cache: Optional[dict] = None
        self._style_thumb_data_cache: Optional[dict] = None
        self._artist_thumb_data_cache: dict[str, dict] = {}
        self._artist_thumb_image_cache: dict[tuple[str, str], tuple[bytes, str]] = {}
        self._artist_thumb_random_history: dict[tuple[str, str, str, int], list[str]] = {}
        self._artist_thumb_lock = threading.RLock()
        self._artist_thumb_download_thread: Optional[threading.Thread] = None
        self._artist_thumb_download_cancel = threading.Event()
        self._artist_thumb_download_state = {
            "active": False,
            "mode": "",
            "percent": 0,
            "downloaded_mb": 0.0,
            "total_mb": 0.0,
            "message": "",
            "error": "",
            "done": False,
            "updated_at": "",
        }
        self._ensure_artist_thumb_state()
        self._repo_root = Path(__file__).resolve().parent.parent
        self._character_viewer_service = CharacterViewerService(self._repo_root)
        self._event_preset_service = EventPresetService(self._repo_root)
        self._clothes_preset_service = ClothesPresetService(self._repo_root)
        self._expression_preset_service = ExpressionPresetService(self._repo_root)
        self._preset_composer_service = PresetComposerService(
            self._event_preset_service,
            axis_providers={"clothes": self._clothes_preset_service},
        )
        self._publish_preset_services()
        self._event_preset_download_lock = threading.RLock()
        self._event_preset_download_thread: Optional[threading.Thread] = None
        self._event_preset_download_cancel = threading.Event()
        self._event_preset_download_state = {
            "active": False,
            "phase": "",
            "percent": 0,
            "downloaded_mb": 0.0,
            "total_mb": 0.0,
            "message": "",
            "error": "",
            "done": False,
            "updated_at": "",
        }
        # ComfyUI 전용 sync request matching: request_id → asyncio.Future
        self._pending_comfyui_requests: dict = {}
        self._comfyui_requests_lock = threading.Lock()
        # ComfyUI workflow actions: FastAPI request_id → {loop, future, action, metadata}
        self._pending_comfyui_workflow_actions: dict = {}
        self._comfyui_workflow_actions_lock = threading.Lock()
        # Desktop snapshot requests: FastAPI request_id → {loop, future, reason}
        self._pending_desktop_snapshot_requests: dict = {}
        self._desktop_snapshot_requests_lock = threading.Lock()
        # Resolution manager actions: FastAPI request_id → {loop, future, payload}
        self._pending_resolution_actions: dict = {}
        self._resolution_actions_lock = threading.Lock()
        self._pending_clipboard_png_requests: dict = {}
        self._clipboard_png_requests_lock = threading.Lock()
        self._pending_result_history_actions: dict = {}
        self._result_history_actions_lock = threading.Lock()
        self._pending_artist_thumb_random_peng_requests: dict = {}
        self._artist_thumb_random_peng_requests_lock = threading.Lock()

    def _publish_preset_services(self) -> None:
        """Expose already-loaded preset services to prompt-time shortcut expansion."""
        try:
            self.app_context.event_preset_service = self._event_preset_service
            self.app_context.clothes_preset_service = self._clothes_preset_service
            self.app_context.expression_preset_service = self._expression_preset_service
            self.app_context.preset_services_revision = int(getattr(self.app_context, "preset_services_revision", 0) or 0) + 1
            self._preset_autocomplete_bridge = None
            if not hasattr(self.app_context, "preset_input_context"):
                self.app_context.preset_input_context = {"ratingId": "s", "personId": "1girl_solo"}
                self.app_context.preset_input_context_source = "default"
                self.app_context.preset_input_context_fields = set()
        except Exception:
            pass

    def _set_preset_input_context(self, context: dict | None, source: str) -> dict[str, str]:
        return update_app_preset_context(self.app_context, context if isinstance(context, dict) else {}, source=source)

    def _search_filter_state_path(self) -> Path:
        return Path("save") / "remote_web_filter_state.json"

    def _root_app_settings_path(self) -> Path:
        return Path("app_settings.json")

    def _default_remote_web_ui_state(self) -> dict:
        return {
            "version": 1,
            "webui_hiresfix_assist": {"enabled": True, "target": 512},
            "resolution_preset": {
                "WEBUI": {"enabled": False, "preset": "standard"},
                "COMFYUI": {"enabled": False, "preset": "standard"},
            },
            "hires_preset_swap": "",
            "random_prompt_weight": "1",
        }

    def _normalize_webui_hiresfix_assist_state(self, raw) -> dict:
        state = raw if isinstance(raw, dict) else {}
        try:
            target = 768 if int(float(state.get("target") or 512)) == 768 else 512
        except (TypeError, ValueError):
            target = 512
        return {
            "enabled": self._coerce_bool(state.get("enabled", True)),
            "target": target,
        }

    def _normalize_resolution_preset_state(self, raw) -> dict:
        state = raw if isinstance(raw, dict) else {}
        return {
            "enabled": self._coerce_bool(state.get("enabled", False)),
            "preset": normalize_anima_resolution_preset_id(state.get("preset")),
        }

    def _normalize_resolution_preset_map(self, raw) -> dict:
        data = raw if isinstance(raw, dict) else {}
        defaults = self._default_remote_web_ui_state()["resolution_preset"]
        return {
            mode: self._normalize_resolution_preset_state(data.get(mode, defaults[mode]))
            for mode in ("WEBUI", "COMFYUI")
        }

    def _enforce_webui_resolution_tool_exclusion(self, state: dict) -> dict:
        """WEBUI Res Preset and Hiresfix Assist are mutually exclusive."""
        try:
            preset_state = state["resolution_preset"]["WEBUI"]
            hires_state = state["webui_hiresfix_assist"]
            if preset_state.get("enabled") and hires_state.get("enabled"):
                hires_state["enabled"] = False
        except Exception:
            pass
        return state

    @staticmethod
    def _normalize_hires_preset_swap_name(raw) -> str:
        name = str(raw or "").strip()
        if not name:
            return ""
        name = Path(name).name
        if name.endswith(".json"):
            name = name[:-5]
        for char in '<>:"/\\|?*':
            name = name.replace(char, "")
        if name in {"", "*randomized", "(프리셋 없음)"}:
            return ""
        return name.strip()

    def _normalize_remote_web_ui_state(self, raw) -> dict:
        state = self._default_remote_web_ui_state()
        if isinstance(raw, dict):
            try:
                state["version"] = int(raw.get("version") or state["version"])
            except (TypeError, ValueError):
                pass
            state["webui_hiresfix_assist"] = self._normalize_webui_hiresfix_assist_state(
                raw.get("webui_hiresfix_assist")
            )
            state["resolution_preset"] = self._normalize_resolution_preset_map(
                raw.get("resolution_preset")
            )
            state["hires_preset_swap"] = self._normalize_hires_preset_swap_name(
                raw.get("hires_preset_swap", state["hires_preset_swap"])
            )
            state["random_prompt_weight"] = self._format_anima_weight(
                raw.get("random_prompt_weight", state["random_prompt_weight"])
            )
        return self._enforce_webui_resolution_tool_exclusion(state)

    def _get_settings_module(self):
        """SettingsTabModule 인스턴스 반환."""
        try:
            mw = self.app_context.main_window
            right_view = getattr(mw, "image_window", None)
            tab_controller = getattr(right_view, "tab_controller", None)
            if tab_controller and hasattr(tab_controller, "get_tab_instance"):
                return tab_controller.get_tab_instance("SettingsTabModule")
        except Exception:
            pass
        return None

    def _read_root_app_settings(self) -> dict:
        settings_module = self._get_settings_module()
        module_data = getattr(settings_module, "settings_data", None) if settings_module else None
        if isinstance(module_data, dict) and module_data:
            return copy.deepcopy(module_data)

        path = self._root_app_settings_path()
        try:
            if path.exists():
                with path.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                    return data if isinstance(data, dict) else {}
        except Exception as e:
            print(f"🌐 Remote: app_settings 로드 실패 — {e}")
        return {}

    def _write_root_app_settings(self, settings: dict):
        settings_data = settings if isinstance(settings, dict) else {}
        settings_module = self._get_settings_module()
        if settings_module is not None and hasattr(settings_module, "settings_data"):
            try:
                settings_module.settings_data = copy.deepcopy(settings_data)
                if hasattr(settings_module, "save_settings"):
                    settings_module.save_settings()
                    return
            except Exception as e:
                print(f"🌐 Remote: SettingsTab 저장 실패 — {e}")

        try:
            path = self._root_app_settings_path()
            tmp_path = path.with_suffix(path.suffix + ".tmp")
            with tmp_path.open("w", encoding="utf-8") as f:
                json.dump(settings_data, f, ensure_ascii=False, indent=2)
                f.write("\n")
            tmp_path.replace(path)
        except Exception as e:
            print(f"🌐 Remote: app_settings 저장 실패 — {e}")

    def _load_remote_web_ui_state(self) -> dict:
        settings = self._read_root_app_settings()
        return self._normalize_remote_web_ui_state(settings.get("remote_web"))

    def _write_remote_web_ui_state(self):
        settings = self._read_root_app_settings()
        settings["remote_web"] = self._normalize_remote_web_ui_state(
            getattr(self, "_remote_web_ui_state", None)
        )
        self._write_root_app_settings(settings)

    def _save_remote_web_ui_state(self, **updates):
        state = self._normalize_remote_web_ui_state(getattr(self, "_remote_web_ui_state", None))
        if "webui_hiresfix_assist" in updates:
            state["webui_hiresfix_assist"] = self._normalize_webui_hiresfix_assist_state(
                updates.get("webui_hiresfix_assist")
            )
        if "resolution_preset" in updates:
            state["resolution_preset"] = self._normalize_resolution_preset_map(
                updates.get("resolution_preset")
            )
        if "hires_preset_swap" in updates:
            state["hires_preset_swap"] = self._normalize_hires_preset_swap_name(
                updates.get("hires_preset_swap")
            )
        if "random_prompt_weight" in updates:
            state["random_prompt_weight"] = self._format_anima_weight(updates.get("random_prompt_weight"))
        state = self._enforce_webui_resolution_tool_exclusion(state)
        self._remote_web_ui_state = state
        self._webui_hiresfix_assist = dict(state["webui_hiresfix_assist"])
        self._write_remote_web_ui_state()

    def _resolution_preset_defaults_for_mode(self, mode: str | None = None) -> dict:
        normalized_mode = self._normalize_resolution_mode(mode)
        if normalized_mode not in {"WEBUI", "COMFYUI"}:
            return {}
        state = self._normalize_remote_web_ui_state(getattr(self, "_remote_web_ui_state", None))
        preset_state = state["resolution_preset"].get(normalized_mode, {})
        normalized = self._normalize_resolution_preset_state(preset_state)
        return {
            "resolution_preset_enabled": bool(normalized["enabled"]),
            "resolution_preset": normalized["preset"],
        }

    def get_resolution_preset_params(self, mode: str | None = None) -> dict:
        return self._resolution_preset_defaults_for_mode(mode or self._current_api_mode())

    def _save_resolution_preset_param(self, key: str, value: str):
        mode = self._normalize_resolution_mode()
        if mode not in {"WEBUI", "COMFYUI"}:
            return
        state = self._normalize_remote_web_ui_state(getattr(self, "_remote_web_ui_state", None))
        preset_map = state["resolution_preset"]
        current = self._normalize_resolution_preset_state(preset_map.get(mode))
        if key == "resolution_preset_enabled":
            current["enabled"] = self._coerce_bool(value)
        elif key == "resolution_preset":
            current["preset"] = normalize_anima_resolution_preset_id(value)
        preset_map[mode] = current
        updates = {"resolution_preset": preset_map}
        should_broadcast_hiresfix = False
        if mode == "WEBUI" and current.get("enabled"):
            hires_state = self._normalize_webui_hiresfix_assist_state(
                getattr(self, "_webui_hiresfix_assist", None)
            )
            if hires_state.get("enabled"):
                hires_state["enabled"] = False
                updates["webui_hiresfix_assist"] = hires_state
                should_broadcast_hiresfix = True
        self._save_remote_web_ui_state(**updates)
        if should_broadcast_hiresfix:
            self._broadcast_webui_hiresfix_assist_state()

    def _remote_web_generation_param_defaults(self, mode: str | None = None) -> dict:
        state = self._normalize_remote_web_ui_state(getattr(self, "_remote_web_ui_state", None))
        normalized_mode = self._normalize_resolution_mode(mode)
        defaults = self._resolution_preset_defaults_for_mode(normalized_mode)
        if normalized_mode == "WEBUI":
            weight = state["random_prompt_weight"]
            defaults.update({
                "anima_weight": weight,
                "anima_weight_raw": weight,
                "random_prompt_weight": weight,
                "hires_preset_swap": state["hires_preset_swap"],
            })
        return defaults

    def get_webui_hiresfix_assist_params(self) -> dict:
        state = self._normalize_webui_hiresfix_assist_state(
            getattr(self, "_webui_hiresfix_assist", None)
        )
        return {
            "webui_hiresfix_assist": bool(state["enabled"]),
            "webui_hiresfix_assist_target": state["target"],
        }

    def get_webui_hires_preset_swap_params(self) -> dict:
        state = self._normalize_remote_web_ui_state(
            getattr(self, "_remote_web_ui_state", None)
        )
        swap_name = state.get("hires_preset_swap") or ""
        return {"hires_preset_swap": swap_name} if swap_name else {}

    def is_remote_auto_generate_enabled(self) -> bool:
        return bool(getattr(self, "_remote_auto_generate_enabled", False))

    def _normalize_rating_list(self, ratings=None) -> list[str]:
        source = ratings if ratings is not None else ['g', 's', 'q', 'e']
        if isinstance(source, str):
            source = list(source)
        try:
            picked = {str(item).strip().lower() for item in source}
        except TypeError:
            picked = set()
        normalized = [key for key in ('g', 's', 'q', 'e') if key in picked]
        return normalized or ['g', 's', 'q', 'e']

    def _normalize_filter_tags(self, value) -> list[str]:
        if not isinstance(value, (list, tuple, set)):
            return []
        out = []
        seen = set()
        for item in value:
            tag = str(item or "").strip().replace(" ", "_")
            if not tag:
                continue
            negative = tag.startswith("-")
            tag_body = tag[1:] if negative else tag
            tag_body = tag_body.lstrip("-")
            if not tag_body:
                continue
            clean = ("-" if negative else "") + tag_body
            if clean in seen:
                continue
            seen.add(clean)
            out.append(clean)
        return out

    def _default_search_filter_state(self) -> dict:
        return {
            "version": 1,
            "query": "",
            "exclude": "",
            "ratings": ['g', 's', 'q', 'e'],
            "tag_filter": [],
            "tag_filter_exclude": [],
            "tag_filter_active": False,
            "updated_at": None,
        }

    def _normalize_search_filter_state(self, raw) -> dict:
        state = self._default_search_filter_state()
        if isinstance(raw, dict):
            state["query"] = str(raw.get("query", state["query"]) or "")
            state["exclude"] = str(raw.get("exclude", state["exclude"]) or "")
            state["ratings"] = self._normalize_rating_list(raw.get("ratings", state["ratings"]))
            state["tag_filter"] = self._normalize_filter_tags(
                raw.get("tag_filter") or raw.get("include") or raw.get("include_tags")
            )
            exclude_tags = raw.get("tag_filter_exclude") or raw.get("exclude_tags")
            state["tag_filter_exclude"] = [
                tag.lstrip("-") for tag in self._normalize_filter_tags(exclude_tags)
            ]
            state["tag_filter_active"] = bool(raw.get("tag_filter_active")) and (
                bool(state["tag_filter"]) or bool(state["tag_filter_exclude"])
            )
            state["updated_at"] = raw.get("updated_at")
        return state

    def _load_search_filter_state(self) -> dict:
        path = self._search_filter_state_path()
        try:
            if path.exists():
                with path.open("r", encoding="utf-8") as f:
                    return self._normalize_search_filter_state(json.load(f))
        except Exception as e:
            print(f"🌐 Remote: filter state 로드 실패 — {e}")
        return self._default_search_filter_state()

    def _write_search_filter_state(self):
        try:
            state = self._normalize_search_filter_state(self._search_filter_state)
            state["updated_at"] = datetime.now().isoformat(timespec="seconds")
            self._search_filter_state = state
            path = self._search_filter_state_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = path.with_suffix(path.suffix + ".tmp")
            with tmp_path.open("w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False, indent=2)
                f.write("\n")
            tmp_path.replace(path)
        except Exception as e:
            print(f"🌐 Remote: filter state 저장 실패 — {e}")

    def _save_search_filter_state(self, **updates):
        state = dict(self._search_filter_state or self._default_search_filter_state())
        if "query" in updates and updates["query"] is not None:
            state["query"] = str(updates["query"] or "")
        if "exclude" in updates and updates["exclude"] is not None:
            state["exclude"] = str(updates["exclude"] or "")
        if "ratings" in updates and updates["ratings"] is not None:
            state["ratings"] = self._normalize_rating_list(updates["ratings"])
        if "tag_filter" in updates and updates["tag_filter"] is not None:
            state["tag_filter"] = [
                tag.lstrip("-") for tag in self._normalize_filter_tags(updates["tag_filter"])
            ]
        if "tag_filter_exclude" in updates and updates["tag_filter_exclude"] is not None:
            state["tag_filter_exclude"] = [
                tag.lstrip("-") for tag in self._normalize_filter_tags(updates["tag_filter_exclude"])
            ]
        if "tag_filter_active" in updates and updates["tag_filter_active"] is not None:
            state["tag_filter_active"] = bool(updates["tag_filter_active"])
        state = self._normalize_search_filter_state(state)
        self._search_filter_state = state
        self._active_ratings = set(state["ratings"])
        self.app_context.remote_active_ratings = set(self._active_ratings)
        self._write_search_filter_state()

    def _save_search_filter_state_from_payload(self, payload: dict):
        if not isinstance(payload, dict):
            return
        self._save_search_filter_state(
            query=payload.get("query") if "query" in payload else None,
            exclude=payload.get("exclude") if "exclude" in payload else None,
            ratings=payload.get("ratings") if "ratings" in payload else None,
            tag_filter=payload.get("tag_filter") if "tag_filter" in payload else None,
            tag_filter_exclude=payload.get("tag_filter_exclude") if "tag_filter_exclude" in payload else None,
            tag_filter_active=payload.get("tag_filter_active") if "tag_filter_active" in payload else None,
        )

    def _apply_saved_search_filter_state(self):
        state = self._normalize_search_filter_state(self._search_filter_state)
        self._search_filter_state = state
        self._active_ratings = set(state["ratings"])
        self.app_context.remote_active_ratings = set(self._active_ratings)
        mw = getattr(self.app_context, "main_window", None)
        if not mw:
            return
        try:
            if hasattr(mw, "search_input"):
                mw.search_input.setText(state["query"])
            if hasattr(mw, "exclude_input"):
                mw.exclude_input.setText(state["exclude"])
        except Exception as e:
            print(f"🌐 Remote: saved filter UI 적용 실패 — {e}")

    def _restore_saved_tag_filter_ids(self) -> bool:
        state = self._normalize_search_filter_state(self._search_filter_state)
        tags = [*state["tag_filter"], *["-" + tag for tag in state["tag_filter_exclude"]]]
        if not state["tag_filter_active"] or not tags:
            self._active_tag_filter_ids = None
            return False
        result = self._do_tag_filter_search(tags)
        ids = result.pop("_ids", set()) if isinstance(result, dict) else set()
        self._active_tag_filter_ids = ids or None
        return bool(self._active_tag_filter_ids)

    def _restore_saved_search_filter_state(self):
        self._apply_saved_search_filter_state()
        try:
            mw = self.app_context.main_window
            if not mw or not mw.search_results or mw.search_results.is_empty():
                return
            master = getattr(mw, "_master_filter_snapshot", None)
            if master is None or master.empty:
                mw._master_filter_snapshot = mw.search_results.get_dataframe().copy()
            self._restore_saved_tag_filter_ids()
            self._do_apply_filters()
        except Exception as e:
            print(f"🌐 Remote: saved filter 복원 실패 — {e}")

    def set_ws_manager(self, ws_manager: WebSocketManager):
        self._ws_manager = ws_manager
        ws_manager._bridge_ref = self

    def set_event_loop(self, loop: asyncio.AbstractEventLoop):
        self._loop = loop

    def _has_clients(self) -> bool:
        return bool(self._ws_manager and self._ws_manager.active_connections)

    @staticmethod
    def _queue_preview(value, limit: int = 140) -> str:
        text = re.sub(r"\s+", " ", str(value or "")).strip()
        return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"

    def _queue_param_summary(self, params: dict | None = None, request=None) -> dict:
        params = params if isinstance(params, dict) else {}
        prompt = params.get("_raw_input") or params.get("input") or params.get("prompt") or ""
        negative = params.get("negative_prompt") or params.get("uc") or ""
        width = params.get("width")
        height = params.get("height")
        resolution = f"{width}x{height}" if width and height else ""

        character_count = 0
        characters = params.get("characters")
        if isinstance(characters, (list, tuple)):
            character_count = len(characters)
        nai_characters = getattr(request, "nai_characters", None) if request else None
        if not character_count and nai_characters:
            character_count = len(getattr(nai_characters, "characters", []) or [])

        vibe_count = 0
        vibes = params.get("reference_image_multiple")
        if isinstance(vibes, (list, tuple)):
            vibe_count = len(vibes)
        nai_vibes = getattr(request, "nai_vibe_transfer", None) if request else None
        if not vibe_count and nai_vibes:
            vibe_count = len(getattr(nai_vibes, "reference_image_multiple", []) or [])

        char_ref_count = 0
        director_images = params.get("director_reference_images")
        if isinstance(director_images, (list, tuple)):
            char_ref_count = len(director_images)
        nai_ref = getattr(request, "nai_character_reference", None) if request else None
        if not char_ref_count and nai_ref:
            char_ref_count = len(getattr(nai_ref, "director_reference_images", []) or [])

        return {
            "prompt_preview": self._queue_preview(prompt),
            "negative_preview": self._queue_preview(negative, 100),
            "mode": str(params.get("api_mode") or self._current_api_mode() or ""),
            "resolution": resolution,
            "seed": str(params.get("seed") or ""),
            "source": str(params.get("_remote_queue_source") or "queue"),
            "label": str(params.get("_remote_queue_label") or ""),
            "character_count": character_count,
            "vibe_count": vibe_count,
            "char_ref_count": char_ref_count,
        }

    def _serialize_queue_request(self, request, position: int | None = None, active: bool = False) -> dict:
        params = getattr(request, "params", {}) if request else {}
        summary = self._queue_param_summary(params, request=request)
        source_row = getattr(request, "source_row", None) if request else None
        source_name = str(getattr(source_row, "name", "") or "")
        label = summary["label"] or source_name or summary["source"]
        return {
            **summary,
            "id": str(getattr(request, "request_id", "") or ""),
            "position": position,
            "priority": int(getattr(request, "priority", 0) or 0),
            "status": "processing" if active else str(getattr(request, "status", "pending") or "pending"),
            "created_at": getattr(getattr(request, "created_at", None), "isoformat", lambda: None)(),
            "started_at": getattr(getattr(request, "started_at", None), "isoformat", lambda: None)(),
            "completed_at": getattr(getattr(request, "completed_at", None), "isoformat", lambda: None)(),
            "wait_time": request.get_wait_time() if request and hasattr(request, "get_wait_time") else None,
            "elapsed_time": request.get_elapsed_time() if request and hasattr(request, "get_elapsed_time") else None,
            "label": self._queue_preview(label, 80),
        }

    def _serialize_active_generation(self) -> dict | None:
        try:
            gc = self.app_context.main_window.generation_controller
            params = getattr(gc, "current_generation_params", None)
            if not isinstance(params, dict):
                return None
            request = params.get("_generation_request")
            if request:
                return self._serialize_queue_request(request, position=0, active=True)
            summary = self._queue_param_summary(params)
            return {
                **summary,
                "id": "active",
                "position": 0,
                "priority": 0,
                "status": "processing",
                "created_at": None,
                "started_at": None,
                "completed_at": None,
                "wait_time": None,
                "elapsed_time": None,
                "label": summary["label"] or summary["source"] or "Current generation",
            }
        except Exception:
            return None

    def _build_queue_state(self) -> dict:
        try:
            queue_manager = self.app_context.generation_queue_manager
            gc = self.app_context.main_window.generation_controller
            queued = [
                self._serialize_queue_request(request, position=index + 1)
                for index, request in enumerate(queue_manager.get_all_requests())
            ]
            active = self._serialize_active_generation() if getattr(gc, "is_generating", False) else None
            if active and active.get("id") == "active" and not queued:
                active = None
            stats = queue_manager.get_queue_stats()
            return {
                "type": "queue_state",
                "is_generating": bool(getattr(gc, "is_generating", False)),
                "paused": bool(stats.get("is_paused", False)),
                "total": int(stats.get("total", len(queued)) or 0),
                "has_urgent": bool(stats.get("has_urgent", False)),
                "priority_counts": stats.get("priority_counts", {}),
                "active": active,
                "items": queued,
            }
        except Exception as e:
            return {
                "type": "queue_state",
                "error": str(e),
                "is_generating": False,
                "paused": False,
                "total": 0,
                "active": None,
                "items": [],
            }

    def _broadcast_queue_state(self, _data=None):
        if self._has_clients():
            self._broadcast_json(self._build_queue_state())

    def _is_queued_webui_result_enhance(self, queue_manager, request_id: str = "") -> bool:
        try:
            for request in queue_manager.get_all_requests():
                if request_id and getattr(request, "request_id", "") != request_id:
                    continue
                params = getattr(request, "params", {}) or {}
                if params.get("result_enhance_request") and params.get("result_enhance_backend") == "WEBUI":
                    return True
        except Exception:
            return False
        return False

    def _clear_queued_result_enhance_state(self, message: str = "Enhance canceled"):
        self._remote_enhance_in_flight = False
        self._remote_enhance_api_mode = ""
        self._remote_enhance_request_id = ""
        self._broadcast_json({
            "type": "result_enhance_state",
            "running": False,
            "success": False,
            "message": message,
        })

    def _do_queue_action(self, payload_json: str = "{}"):
        try:
            payload = json.loads(payload_json) if payload_json else {}
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        action = str(payload.get("action") or "").strip().lower()
        request_id = str(payload.get("request_id") or payload.get("id") or "").strip()
        queue_manager = self.app_context.generation_queue_manager
        try:
            queued_enhance_canceled = False
            if action == "pause":
                queue_manager.pause_queue()
            elif action == "resume":
                queue_manager.resume_queue()
            elif action == "clear":
                queued_enhance_canceled = self._is_queued_webui_result_enhance(queue_manager)
                queue_manager.clear_queue()
            elif action == "remove":
                if not request_id:
                    raise ValueError("request_id is required")
                if not queue_manager.remove_request(request_id):
                    raise ValueError("queue item not found")
                queued_enhance_canceled = request_id == self._remote_enhance_request_id
            else:
                raise ValueError("unsupported queue action")
            if queued_enhance_canceled:
                self._clear_queued_result_enhance_state()
            self._broadcast_queue_state()
        except Exception as e:
            self._broadcast_json({"type": "toast", "message": f"Queue action failed: {e}", "level": "error"})
            self._broadcast_queue_state()

    def _send_json_to(self, ws, data: dict):
        """특정 WS 클라이언트에만 JSON 전송 (Qt 메인 스레드에서 호출)."""
        if self._loop and self._ws_manager and ws:
            import json as _json
            asyncio.run_coroutine_threadsafe(
                self._ws_manager.send_json_to(ws, data),
                self._loop
            )

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
            settings_module = self._get_settings_module()
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

    def _request_client_host(self, req) -> str:
        """HTTP 클라이언트 IP 안전 추출 (loopback 판정용)."""
        try:
            if req is not None and getattr(req, "client", None) is not None:
                return (req.client.host or "") if hasattr(req.client, "host") else ""
        except Exception:
            pass
        return ""

    def _is_loopback_host(self, host: str) -> bool:
        host = str(host or "").strip()
        if host in ("127.0.0.1", "::1", "localhost"):
            return True
        try:
            import ipaddress
            return ipaddress.ip_address(host).is_loopback
        except Exception:
            return False

    def _desktop_img2img_gate(self, host: str) -> tuple[bool, str]:
        """호스트 데스크탑에 PyQt img2img/Inpaint 창을 띄우는 요청 게이트."""
        if not self._is_loopback_host(host):
            return False, "Img2Img/Inpaint 데스크탑 창은 로컬(127.0.0.1) 접속에서만 열 수 있습니다."
        if self._is_cloudflared_active():
            return False, "Cloudflared 터널 활성 중 — Img2Img/Inpaint 데스크탑 창 열기가 차단됩니다."
        return True, ""

    def _nai_img2img_mode_gate(self) -> tuple[bool, str]:
        if str(self._current_api_mode() or "").upper() != "NAI":
            return False, "Img2Img/Inpaint is available in NAI mode only"
        return True, ""

    def _desktop_browser_gate(self, host: str) -> tuple[bool, str]:
        """호스트 데스크탑에 PyQt WebEngine 창/탭을 띄우는 요청 게이트."""
        if not self._is_loopback_host(host):
            return False, "Danbooru PyQt6 브라우저는 로컬(127.0.0.1) 접속에서만 열 수 있습니다."
        if self._is_cloudflared_active():
            return False, "Cloudflared 터널 활성 중 — Danbooru PyQt6 브라우저 열기가 차단됩니다."
        return True, ""

    def _setup_gate(self, ws) -> tuple[bool, str]:
        """Setup UI 활성 조건 2중 게이트 — 전부 통과해야 토큰/URL 설정 허용.

        1) 클라이언트가 loopback 에서 접속 (LAN/외부 거부)
        2) Cloudflared 터널 비활성
        """
        host = self._ws_client_host(ws)
        if host not in ("127.0.0.1", "::1"):
            return False, "초기 설정은 로컬(127.0.0.1) 접속에서만 가능합니다."
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
        if self._is_cloudflared_active():
            return False, "Cloudflared 터널 활성 중 — 저장 디렉토리 변경이 차단됩니다."
        return True, ""

    def _result_enhance_gate(self, ws) -> tuple[bool, str]:
        """Result Enhance는 로컬 호스트 단독 세션에서만 허용."""
        host = self._ws_client_host(ws)
        if host not in ("127.0.0.1", "::1"):
            return False, "Result Enhance는 로컬(127.0.0.1) 접속에서만 가능합니다."
        if self._is_cloudflared_active():
            return False, "Cloudflared 터널 활성 중 — Result Enhance가 차단됩니다."
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
                    if self._has_clients():
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
        """WS 초기화용 캐시를 갱신한다.

        Shared Mode의 지속적인 desktop -> web 설정값 전파는 중단한다. Web Session은
        자체 입력값을 유지하고, 캐시는 모드/API 상태와 파라미터 선택지 schema만
        제공한다. 초기 접속/모드 변경/프리셋 로드처럼 명시적인 reset 지점은
        별도의 desktop snapshot 이벤트가 처리한다. api_status 는 per-ws 평가(setup_allowed 가 클라이언트 IP에
        따라 다름)이므로 캐시하지 않고 WS 초기화 시점에 `get_api_status(ws=ws)`
        로 직접 생성한다.
        """
        self._cached_prompts = {}
        self._cached_options = {}
        self._cached_params = self.get_generation_param_schema()
        self._cached_result_enhance_config = {}

    # --- 시그널 슬롯 래퍼 (lambda 대신 disconnect 가능) ---

    def _do_refresh_cache(self):
        """WS 연결 시 schema cache만 갱신 + broadcast."""
        self._update_cache_all()
        if self._has_clients():
            if self._cached_params:
                self._broadcast_json(self._cached_params)

    def _on_option_toggled_slot(self, checked=None):
        """Desktop checkbox changes update the shared Web Shell option state."""
        if self._syncing_option:
            return
        self.broadcast_options()

    def _on_param_changed_slot(self, *args):
        """Desktop parameter changes no longer push control state to Web Sessions."""
        return

    # --- Qt 메인 스레드에서 실행되는 슬롯 ---

    def _do_generate(self):
        """Generate 요청 처리. deque에서 준비된 데이터를 pop하여 실행."""
        if not self._pending_generate_requests:
            return
        req = self._pending_generate_requests.popleft()
        try:
            ws = req.get("ws")
            prompt = req.get("prompt", "")
            negative = req.get("negative", "")
            raw_overrides = req.get("overrides")
            request_overrides = raw_overrides if isinstance(raw_overrides, dict) else None

            gc = self.app_context.main_window.generation_controller

            if request_overrides is not None:
                # Studio and tool requests are per-generation overrides. They must not
                # mutate the visible main prompt/negative fields.
                session_overrides = dict(request_overrides)
            else:
                # 일반 웹 Generate는 기존처럼 웹 편집 내용을 데스크톱 UI에 반영한다.
                if prompt or negative:
                    self._syncing_prompt = True
                    try:
                        mw = self.app_context.main_window
                        if prompt:
                            mw.main_prompt_textedit.setPlainText(prompt)
                        if negative:
                            mw.negative_prompt_textedit.setPlainText(negative)
                    finally:
                        self._syncing_prompt = False
                session_overrides = {}
            session_overrides.setdefault("_remote_queue_source", "Web")
            if (
                str(session_overrides.get("_comfyui_workflow_mode") or "").lower() == "custom"
                and self.app_context.get_api_mode() == "COMFYUI"
            ):
                manager = self._get_comfyui_workflow_manager()
                if not manager or not getattr(manager, "user_workflow", None):
                    self._send_json_to(ws, {
                        "type": "toast",
                        "message": "ComfyUI custom workflow is no longer loaded on the server.",
                        "level": "error",
                    })
                    return

            # pending overrides에 source 기록 (on_prompt_generated에서 사용)
            if ws is not None:
                self._pending_overrides[ws] = {"source": "generate"}

            queue_manager = self.app_context.generation_queue_manager
            if gc.is_generating or not queue_manager.is_empty():
                gc._enqueue_current_request(session_overrides, priority=0)
                if not gc.is_generating and not queue_manager.is_paused():
                    QTimer.singleShot(0, gc._process_next_queue_request)
                self._send_json_to(ws, {"type": "status", "is_generating": bool(gc.is_generating), "message": "queued"})
                self._broadcast_queue_state()
                print("🌐 Remote: 생성 요청을 큐에 추가")
                return

            gc.execute_generation_pipeline(overrides=session_overrides, priority=0)
            self._broadcast_json({"type": "status", "is_generating": True})
            self._broadcast_queue_state()
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

    @staticmethod
    def _clamp_result_enhance_number(value, minimum: float, maximum: float, fallback: float) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return fallback
        return min(maximum, max(minimum, number))

    def _normalize_result_enhance_config(self, payload: dict | None = None) -> dict:
        """Desktop ImageWindow와 Web Remote가 공유하는 Enhance 설정 payload."""
        payload = payload or {}
        image_window = self._get_image_window_widget()
        fallback_upscale = getattr(image_window, "_enhance_upscale", 1.5) if image_window else 1.5
        fallback_strength = getattr(image_window, "_enhance_strength", 0.2) if image_window else 0.2
        fallback_noise = getattr(image_window, "_enhance_noise", 0.0) if image_window else 0.0

        upscale_value = payload.get("upscale", fallback_upscale)
        try:
            upscale = 1.0 if abs(float(upscale_value) - 1.0) < 0.01 else 1.5
        except (TypeError, ValueError):
            upscale = 1.5
        strength = round(
            self._clamp_result_enhance_number(payload.get("strength", fallback_strength), 0.1, 0.9, 0.2),
            1,
        )
        noise = round(
            self._clamp_result_enhance_number(payload.get("noise", fallback_noise), 0.0, 0.1, 0.0),
            1,
        )
        return {
            "type": "result_enhance_config",
            "upscale": upscale,
            "strength": strength,
            "noise": noise,
        }

    @staticmethod
    def _coerce_result_enhance_bool(value, fallback: bool = False) -> bool:
        if isinstance(value, bool):
            return value
        if value is None:
            return fallback
        text = str(value).strip().lower()
        if text in {"1", "true", "yes", "on"}:
            return True
        if text in {"0", "false", "no", "off"}:
            return False
        return fallback

    def _normalize_webui_result_enhance_hires_settings(self, payload: dict | None = None) -> dict:
        """WEBUI Result Enhance reuses the current Params Hires.fix fields."""
        payload = payload or {}
        current_params = {}
        try:
            if str(self._current_api_mode() or "").upper() == "WEBUI":
                current_params = self.get_generation_params() or {}
        except Exception:
            current_params = {}
        payload_settings = payload.get("hires_settings") if isinstance(payload.get("hires_settings"), dict) else {}
        merged = {**current_params, **payload_settings}
        return {
            "enable_hr": True,
            "hr_scale": round(
                self._clamp_result_enhance_number(merged.get("hr_scale"), 1.0, 4.0, 2.0),
                1,
            ),
            "hr_upscaler": str(merged.get("hr_upscaler") or "Latent (nearest-exact)").strip()
                or "Latent (nearest-exact)",
            "denoising_strength": round(
                self._clamp_result_enhance_number(merged.get("denoising_strength"), 0.0, 1.0, 0.5),
                2,
            ),
            "hires_steps": int(
                self._clamp_result_enhance_number(merged.get("hires_steps"), 0, 150, 10)
            ),
            "hr_cfg": round(
                self._clamp_result_enhance_number(merged.get("hr_cfg"), 0.0, 30.0, 7.0),
                1,
            ),
            "webui_hiresfix_assist": self._coerce_result_enhance_bool(
                merged.get("webui_hiresfix_assist"),
                False,
            ),
            "webui_hiresfix_assist_target": 768
                if str(merged.get("webui_hiresfix_assist_target") or "").strip() == "768"
                else 512,
        }

    def _result_enhance_config_payload(self) -> dict:
        return self._normalize_result_enhance_config()

    def _broadcast_result_enhance_config(self):
        """Deprecated desktop -> web Enhance settings sync path."""
        self._cached_result_enhance_config = {}

    def _do_set_result_enhance_config(self, ws=None, payload_json: str = "{}"):
        """Persist Web Remote Enhance config only in the requesting session."""
        try:
            allowed, reason = self._result_enhance_gate(ws)
            if not allowed:
                self._send_result_enhance_error(ws, reason)
                return

            image_window = self._get_image_window_widget()
            if not image_window:
                self._send_result_enhance_error(ws, "ImageWindow is not ready")
                return

            try:
                payload = json.loads(payload_json) if isinstance(payload_json, str) else dict(payload_json or {})
            except Exception:
                payload = {}

            config = self._normalize_result_enhance_config(payload)

            self._cached_result_enhance_config = {}
            if ws is not None:
                self._send_json_to(ws, {**config, "_session_echo": True})
            self._send_json_to(ws, {"type": "toast", "message": "Enhance settings updated", "level": "success"})
            print(
                "🌐 Remote: Enhance 설정 갱신 "
                f"(x{config['upscale']:g}, strength={config['strength']:.1f}, noise={config['noise']:.1f})"
            )
        except Exception as e:
            self._send_result_enhance_error(ws, f"Enhance settings update failed: {e}")
            print(f"🌐 Remote: Enhance 설정 갱신 실패 — {e}")

    @staticmethod
    def _round_enhance_size(value: float) -> int:
        import math

        return math.ceil(value / 64) * 64

    def _resolve_result_enhance_source(self, payload: dict) -> dict:
        import copy

        image_window = self._get_image_window_widget()
        if not image_window:
            raise RuntimeError("ImageWindow is not ready")

        payload = payload if isinstance(payload, dict) else {}
        source = str(payload.get("source") or "").strip().lower()
        rel_path = str(payload.get("path") or "").strip()
        file_path = str(payload.get("file_path") or payload.get("filePath") or "").strip()

        if rel_path and source != "current":
            item = self._find_history_item_by_path(rel_path=rel_path, file_path=file_path)
            if not item:
                raise RuntimeError("Selected history item is unavailable")
        else:
            item = getattr(image_window, "current_history_item", None)

        if not item or not getattr(item, "image", None):
            raise RuntimeError("No image is selected")
        if not getattr(item, "generation_params", None):
            raise RuntimeError("Generation parameters are unavailable")

        return {
            "image_window": image_window,
            "item": item,
            "generation_params": copy.deepcopy(getattr(item, "generation_params", {}) or {}),
        }

    def _prepare_nai_result_enhance_context(self, payload: dict) -> dict:
        import copy

        context = self._resolve_result_enhance_source(payload)
        image_window = context["image_window"]
        item = context["item"]
        image = item.image

        config = self._normalize_result_enhance_config(payload)
        upscale = config["upscale"]
        strength = config["strength"]
        noise = config["noise"]

        orig_w, orig_h = image.size
        if upscale == 1.0:
            new_w, new_h = orig_w, orig_h
        else:
            round_size = getattr(image_window, "_round_to_64", None)
            if callable(round_size):
                new_w = round_size(orig_w * 1.5)
                new_h = round_size(orig_h * 1.5)
            else:
                new_w = self._round_enhance_size(orig_w * 1.5)
                new_h = self._round_enhance_size(orig_h * 1.5)

        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        image_bytes = buffer.getvalue()

        params = copy.deepcopy(context["generation_params"])
        params["image_bytes"] = image_bytes
        params["strength"] = strength
        params["noise"] = noise
        params["width"] = new_w
        params["height"] = new_h
        params["api_mode"] = "NAI"
        params.pop("type", None)
        params.pop("mask_bytes", None)

        context.update({
            "params": params,
            "orig_w": orig_w,
            "orig_h": orig_h,
            "new_w": new_w,
            "new_h": new_h,
            "upscale": upscale,
            "strength": strength,
            "noise": noise,
            "api_mode": "NAI",
        })
        return context

    @staticmethod
    def _webui_result_enhance_dimension(value, fallback: int) -> int:
        try:
            number = int(float(value))
        except (TypeError, ValueError):
            return int(fallback)
        return max(1, number)

    def _apply_webui_result_enhance_size_policy(self, params: dict, base_w: int, base_h: int) -> tuple[int, int, float]:
        payload = {"width": base_w, "height": base_h}
        scale = self._clamp_result_enhance_number(params.get("hr_scale"), 1.0, 4.0, 2.0)
        api_service = getattr(self.app_context, "api_service", None)
        if api_service is not None:
            apply_resolution = getattr(api_service, "_apply_webui_hiresfix_assist_resolution", None)
            if callable(apply_resolution):
                try:
                    apply_resolution(payload, params)
                except Exception:
                    payload = {"width": base_w, "height": base_h}
            fit_scale = getattr(api_service, "_fit_webui_hiresfix_assist_scale", None)
            if callable(fit_scale):
                try:
                    scale = fit_scale(payload, scale)
                except Exception:
                    pass
        payload_w = self._webui_result_enhance_dimension(payload.get("width"), base_w)
        payload_h = self._webui_result_enhance_dimension(payload.get("height"), base_h)
        scale = round(self._clamp_result_enhance_number(scale, 1.0, 4.0, 2.0), 1)
        params["width"] = payload_w
        params["height"] = payload_h
        params["hr_scale"] = scale
        scaled_dimension = getattr(api_service, "_webui_scaled_dimension", None) if api_service is not None else None
        if callable(scaled_dimension):
            new_w = scaled_dimension(payload_w, scale)
            new_h = scaled_dimension(payload_h, scale)
        else:
            new_w = max(1, int(round(float(payload_w) * scale)))
            new_h = max(1, int(round(float(payload_h) * scale)))
        return new_w, new_h, scale

    @staticmethod
    def _resolve_webui_result_enhance_seed(item, params: dict) -> int | None:
        candidates = [
            params,
            getattr(item, "generation_params", None),
            getattr(item, "api_metadata", None),
            getattr(item, "metadata", None),
            getattr(item, "prompt_context", None),
            getattr(item, "info_text", None),
        ]

        image = getattr(item, "image", None)
        image_info = getattr(image, "info", None)
        if image_info:
            candidates.append(dict(image_info))

        raw_bytes = getattr(item, "raw_bytes", None)
        if raw_bytes:
            try:
                from PIL import Image

                with Image.open(io.BytesIO(raw_bytes)) as raw_image:
                    candidates.append(dict(getattr(raw_image, "info", {}) or {}))
            except Exception:
                pass

        for candidate in candidates:
            seed = extract_webui_seed(candidate)
            if seed is not None:
                return seed
        return None

    def _lock_webui_result_enhance_replay_params(self, item, params: dict, base_w: int, base_h: int) -> None:
        seed = self._resolve_webui_result_enhance_seed(item, params)
        if seed is None:
            raise RuntimeError("WEBUI result seed is unavailable; cannot reproduce source image for Enhance")
        params["seed"] = seed
        params["seed_fixed"] = True
        params["random_resolution"] = False
        params["resolution_preset_enabled"] = False
        params["resolution"] = f"{base_w} x {base_h}"

    def _prepare_webui_result_enhance_context(self, payload: dict) -> dict:
        import copy

        context = self._resolve_result_enhance_source(payload)
        item = context["item"]
        image = item.image
        orig_w, orig_h = image.size

        credential = ""
        token_manager = getattr(self.app_context, "secure_token_manager", None)
        if token_manager is not None:
            credential = str(token_manager.get_token("webui_url") or "").strip()
        if not credential:
            raise RuntimeError("WEBUI URL is not configured")

        hires_settings = self._normalize_webui_result_enhance_hires_settings(payload)
        params = copy.deepcopy(context["generation_params"])
        params.pop("type", None)
        params.pop("image_bytes", None)
        params.pop("mask_bytes", None)
        params.pop("strength", None)
        params.pop("noise", None)

        base_w = self._webui_result_enhance_dimension(params.get("width"), orig_w)
        base_h = self._webui_result_enhance_dimension(params.get("height"), orig_h)
        params["width"] = base_w
        params["height"] = base_h
        self._lock_webui_result_enhance_replay_params(item, params, base_w, base_h)
        params.update(hires_settings)
        params["api_mode"] = "WEBUI"
        params["credential"] = credential

        new_w, new_h, upscale = self._apply_webui_result_enhance_size_policy(params, base_w, base_h)
        strength = hires_settings["denoising_strength"]

        context.update({
            "params": params,
            "orig_w": orig_w,
            "orig_h": orig_h,
            "base_w": base_w,
            "base_h": base_h,
            "new_w": new_w,
            "new_h": new_h,
            "upscale": upscale,
            "strength": strength,
            "noise": 0.0,
            "api_mode": "WEBUI",
            "hr_upscaler": hires_settings["hr_upscaler"],
            "hires_steps": hires_settings["hires_steps"],
            "hr_cfg": hires_settings["hr_cfg"],
        })
        return context

    def _prepare_result_enhance_context(self, payload: dict, mode: str | None = None) -> dict:
        enhance_mode = str(mode or (payload or {}).get("mode") or self._current_api_mode() or "").upper()
        if enhance_mode == "WEBUI":
            return self._prepare_webui_result_enhance_context(payload)
        return self._prepare_nai_result_enhance_context(payload)

    @staticmethod
    def _result_enhance_source_row(context: dict):
        item = context.get("item")
        source_row = getattr(item, "source_row", None) if item is not None else None
        if source_row is not None:
            return source_row
        import pandas as pd

        return pd.Series(
            {"general": None, "character": None, "copyright": None, "artist": None, "meta": None},
            name="webui_result_enhance",
        )

    def _queue_webui_result_enhance(self, context: dict, ws=None):
        from core.generation_request import GenerationRequest

        gc = getattr(getattr(self.app_context, "main_window", None), "generation_controller", None)
        queue_manager = getattr(self.app_context, "generation_queue_manager", None)
        if gc is None or queue_manager is None:
            raise RuntimeError("generation queue is not available")

        params = copy.deepcopy(context.get("params") or {})
        params.update({
            "result_enhance_request": True,
            "result_enhance_backend": "WEBUI",
            "result_enhance_upscale": context.get("upscale", params.get("hr_scale", 2.0)),
            "result_enhance_strength": context.get("strength", params.get("denoising_strength", 0.5)),
            "result_enhance_hr_upscaler": context.get("hr_upscaler", params.get("hr_upscaler", "")),
            "result_enhance_hires_steps": context.get("hires_steps", params.get("hires_steps", 10)),
            "result_enhance_hr_cfg": context.get("hr_cfg", params.get("hr_cfg", 7.0)),
            "result_enhance_source_size": [context.get("orig_w"), context.get("orig_h")],
            "result_enhance_preview_size": [context.get("new_w"), context.get("new_h")],
            "_remote_queue_source": "WEBUI Enhance",
            "_raw_input": params.get("input", ""),
        })

        request = GenerationRequest(
            params=params,
            source_row=self._result_enhance_source_row(context),
            priority=0,
            max_retries=0,
        )
        params["result_enhance_request_id"] = request.request_id
        queue_id = queue_manager.enqueue_request(request)
        self._remote_enhance_in_flight = True
        self._remote_enhance_api_mode = "WEBUI"
        self._remote_enhance_request_id = queue_id
        self._broadcast_json({
            "type": "result_enhance_state",
            "running": True,
            "message": "Enhance queued",
        })
        self._send_json_to(ws, {"type": "toast", "message": "Enhance queued", "level": "success"})
        self._broadcast_queue_state()

        if not getattr(gc, "is_generating", False) and not queue_manager.is_paused():
            QTimer.singleShot(0, gc._process_next_queue_request)
        print(f"🌐 Remote: WEBUI Enhance 큐 추가됨 ({queue_id[:8]}...)")

    def _do_result_enhance(self, ws=None, payload_json: str = "{}"):
        """현재/저장 ImageWindow 히스토리 항목에 Result Enhance를 실행."""
        try:
            allowed, reason = self._result_enhance_gate(ws)
            if not allowed:
                self._send_result_enhance_error(ws, reason)
                return

            if self._remote_enhance_in_flight:
                self._send_result_enhance_error(ws, "Enhance is already running")
                return

            try:
                payload = json.loads(payload_json) if isinstance(payload_json, str) else dict(payload_json or {})
            except Exception:
                payload = {}

            current_mode = str(self._current_api_mode() or "").upper()
            if current_mode not in {"NAI", "WEBUI"}:
                self._send_result_enhance_error(ws, "Enhance is available in NAI or WEBUI mode only")
                return
            requested_mode = str(payload.get("mode") or "").upper()
            if requested_mode in {"NAI", "WEBUI"} and requested_mode != current_mode:
                self._send_result_enhance_error(ws, "Enhance mode changed; refresh the result selection")
                return

            context = self._prepare_result_enhance_context(payload, mode=current_mode)
            image_window = context["image_window"]

            if context.get("api_mode") == "WEBUI":
                self._queue_webui_result_enhance(context, ws=ws)
                return

            if context.get("api_mode") == "NAI" and context["upscale"] == 1.0:
                gen_ctrl = getattr(self.app_context, "generation_controller", None)
                if gen_ctrl and getattr(gen_ctrl, "is_generating", False):
                    self._send_result_enhance_error(ws, "Enhance is unavailable while generation is running")
                    return

            from PyQt6.QtCore import QObject as _QObject, QThread, pyqtSignal as _pyqtSignal

            class EnhanceWorker(_QObject):
                finished = _pyqtSignal(dict)

                def __init__(self, api_service, params):
                    super().__init__()
                    self.api_service = api_service
                    self.params = params

                def run(self):
                    try:
                        result = self.api_service.call_generation_api(self.params)
                    except Exception as exc:
                        result = {"status": "error", "message": str(exc)}
                    self.finished.emit(result)

            self._remote_enhance_in_flight = True
            self._remote_enhance_api_mode = "NAI"
            self._remote_enhance_request_id = ""
            self._broadcast_json({"type": "result_enhance_state", "running": True})
            if hasattr(image_window, "enhance_button"):
                image_window.enhance_button.setEnabled(False)
            thread = QThread()
            worker = EnhanceWorker(self.app_context.api_service, context["params"])
            self._remote_enhance_thread = thread
            self._remote_enhance_worker = worker
            worker.moveToThread(thread)
            thread.started.connect(worker.run)
            worker.finished.connect(lambda result: self._handle_remote_result_enhance(result, context, ws))
            worker.finished.connect(thread.quit)
            worker.finished.connect(worker.deleteLater)
            thread.finished.connect(thread.deleteLater)
            thread.finished.connect(lambda: setattr(self, "_remote_enhance_thread", None))
            thread.finished.connect(lambda: setattr(self, "_remote_enhance_worker", None))
            thread.start()
            print("🌐 Remote: Enhance 트리거됨")
        except Exception as e:
            self._remote_enhance_in_flight = False
            self._remote_enhance_api_mode = ""
            self._remote_enhance_request_id = ""
            message = f"Enhance request failed: {e}"
            self._send_result_enhance_error(ws, message)
            print(f"🌐 Remote: Enhance 트리거 실패 — {e}")

    def _handle_remote_result_enhance(self, result: dict, context: dict, ws=None):
        from PIL import Image
        import copy

        self._remote_enhance_in_flight = False
        success = False
        completion_message = ""
        try:
            image_window = context.get("image_window")
            source_item = context.get("item")
            if not image_window or not source_item:
                completion_message = "Enhance result target is unavailable"
                return

            update_state = getattr(image_window, "_update_enhance_button_state", None)
            if callable(update_state):
                update_state()

            if not isinstance(result, dict) or result.get("status") != "success":
                completion_message = result.get("message", "Enhance failed") if isinstance(result, dict) else "Enhance failed"
                return

            pil_image = result.get("image")
            raw_bytes = result.get("raw_bytes")
            if pil_image is None and raw_bytes:
                pil_image = Image.open(io.BytesIO(raw_bytes))
            if pil_image is None:
                completion_message = "Enhance result image is unavailable"
                return
            if raw_bytes is None:
                buffer = io.BytesIO()
                pil_image.save(buffer, format="PNG")
                raw_bytes = buffer.getvalue()

            api_mode = str(context.get("api_mode") or context.get("params", {}).get("api_mode") or "NAI").upper()
            result_w, result_h = getattr(pil_image, "size", (context.get("new_w"), context.get("new_h")))
            info_text = getattr(source_item, "info_text", "") or ""
            if api_mode == "WEBUI":
                info_text += (
                    f"\nEnhanced: x{context.get('upscale', 2.0):g}, "
                    f"denoise={context.get('strength', 0.5):g}, "
                    f"upscaler={context.get('hr_upscaler') or 'Latent (nearest-exact)'} "
                    f"({result_w}x{result_h})"
                )
            else:
                info_text += (
                    f"\nEnhanced: x{context.get('upscale', 1.5):g}, "
                    f"strength={context.get('strength', 0.2):.1f}, "
                    f"noise={context.get('noise', 0.0):.1f} "
                    f"({result_w}x{result_h})"
                )

            enhanced_params = copy.deepcopy(context.get("params") or {})
            enhanced_params.pop("image_bytes", None)
            enhanced_params.pop("credential", None)
            enhanced_params["width"] = result_w
            enhanced_params["height"] = result_h
            enhanced_params["api_mode"] = api_mode
            if api_mode == "WEBUI":
                enhanced_params["enable_hr"] = True
                enhanced_params["hr_scale"] = context.get("upscale", enhanced_params.get("hr_scale", 2.0))
                enhanced_params["hr_upscaler"] = context.get("hr_upscaler", enhanced_params.get("hr_upscaler", "Latent (nearest-exact)"))
                enhanced_params["denoising_strength"] = context.get(
                    "strength",
                    enhanced_params.get("denoising_strength", 0.5),
                )
                enhanced_params["hires_steps"] = context.get("hires_steps", enhanced_params.get("hires_steps", 10))
                enhanced_params["hr_cfg"] = context.get("hr_cfg", enhanced_params.get("hr_cfg", 7.0))
            else:
                enhanced_params["strength"] = context.get("strength", 0.2)
                enhanced_params["noise"] = context.get("noise", 0.0)

            api_metadata = copy.deepcopy(getattr(source_item, "api_metadata", {}) or {})
            api_metadata.update({
                "enhanced": True,
                "enhance_backend": api_mode,
                "enhance_upscale": context.get("upscale", 1.5),
                "enhance_strength": context.get("strength", 0.2),
                "source_size": (context.get("orig_w"), context.get("orig_h")),
                "result_size": (result_w, result_h),
            })
            if api_mode == "WEBUI":
                api_metadata.update({
                    "enhance_hr_upscaler": context.get("hr_upscaler", ""),
                    "enhance_hires_steps": context.get("hires_steps", 10),
                    "enhance_hr_cfg": context.get("hr_cfg", 7.0),
                })
            else:
                api_metadata["enhance_noise"] = context.get("noise", 0.0)

            generation_result = {
                "image": pil_image,
                "raw_bytes": raw_bytes,
                "info": info_text,
                "source_row": getattr(source_item, "source_row", None),
                "generation_params": enhanced_params,
                "prompt_context": copy.deepcopy(getattr(source_item, "prompt_context", {}) or {}),
                "api_metadata": api_metadata,
                "creation_timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "backend_type": api_mode,
            }
            image_window.add_to_history(
                pil_image,
                raw_bytes,
                info_text,
                getattr(source_item, "source_row", None),
                generation_result=generation_result,
            )
            self.app_context.publish("generation_result_available", generation_result)
            success = True
            completion_message = "Enhance complete"
            print(
                f"✅ Remote Enhance 성공: "
                f"{context.get('orig_w')}x{context.get('orig_h')} → {result_w}x{result_h}"
            )
        finally:
            self.on_result_enhance_completed(success, completion_message)

    def _send_result_upscale_state(self, ws, running: bool = False, success: bool = False, message: str = ""):
        payload = {
            "type": "result_upscale_state",
            "running": running,
            "success": success,
            "message": message,
        }
        if ws is not None:
            self._send_json_to(ws, payload)
            if message:
                self._send_json_to(ws, {
                    "type": "toast",
                    "message": message,
                    "level": "success" if success else "error",
                })
        else:
            self._broadcast_json(payload)
            if message:
                self._broadcast_json({
                    "type": "toast",
                    "message": message,
                    "level": "success" if success else "error",
                })

    def _resolve_result_upscale_source(self, payload: dict) -> dict:
        from PIL import Image
        from PyQt6.QtGui import QPixmap

        image_window = self._get_image_window_widget()
        if not image_window:
            raise RuntimeError("ImageWindow is not ready")

        source = str(payload.get("source") or "").strip().lower()
        rel_path = str(payload.get("path") or "").strip()
        use_saved_path = bool(rel_path and source != "current")

        if use_saved_path:
            target = self._validate_viewer_path(rel_path)
            if not target:
                raise RuntimeError("Image file is unavailable")
            image_bytes = Path(target).read_bytes()
            with Image.open(io.BytesIO(image_bytes)) as opened:
                pil_image = opened.convert("RGBA").copy()
            raw_bytes = image_bytes
            info_text = f"Upscaled from {Path(target).name}"
            source_row = None
            generation_params = {}
            prompt_context = {}
            api_metadata = {"upscale_source_path": rel_path}
        else:
            item = getattr(image_window, "current_history_item", None)
            if not item or not getattr(item, "image", None):
                raise RuntimeError("No image is selected")
            pil_image = item.image
            raw_bytes = getattr(item, "raw_bytes", None) or b""
            info_text = getattr(item, "info_text", "") or ""
            source_row = getattr(item, "source_row", None)
            generation_params = dict(getattr(item, "generation_params", {}) or {})
            prompt_context = dict(getattr(item, "prompt_context", {}) or {})
            api_metadata = dict(getattr(item, "api_metadata", {}) or {})

        png_buffer = io.BytesIO()
        pil_image.save(png_buffer, format="PNG")
        png_bytes = png_buffer.getvalue()
        pixmap = QPixmap()
        if not pixmap.loadFromData(png_bytes):
            raise RuntimeError("Image conversion failed")

        return {
            "image_window": image_window,
            "pixmap": pixmap,
            "raw_bytes": raw_bytes or png_bytes,
            "info_text": info_text,
            "source_row": source_row,
            "generation_params": generation_params,
            "prompt_context": prompt_context,
            "api_metadata": api_metadata,
        }

    def _do_result_upscale(self, ws=None, payload_json: str = "{}"):
        """Remote Web 컨텍스트 메뉴에서 NAI 2x 업스케일을 실행."""
        try:
            allowed, reason = self._result_enhance_gate(ws)
            if not allowed:
                self._send_result_upscale_state(ws, False, False, reason)
                return

            if self._remote_upscale_in_flight:
                self._send_result_upscale_state(ws, False, False, "NAI upscale is already running")
                return

            current_mode = self.app_context.get_api_mode() if hasattr(self.app_context, "get_api_mode") else getattr(self.app_context, "current_api_mode", "")
            if current_mode != "NAI":
                self._send_result_upscale_state(ws, False, False, "NAI upscale is available in NAI mode only")
                return

            try:
                payload = json.loads(payload_json) if isinstance(payload_json, str) else dict(payload_json or {})
            except Exception:
                payload = {}
            context = self._resolve_result_upscale_source(payload)

            from PyQt6.QtCore import QObject as _QObject, QThread, pyqtSignal as _pyqtSignal

            class UpscaleWorker(_QObject):
                finished = _pyqtSignal(dict)

                def __init__(self, api_service, pixmap, raw_bytes):
                    super().__init__()
                    self.api_service = api_service
                    self.pixmap = pixmap
                    self.raw_bytes = raw_bytes

                def run(self):
                    result = self.api_service.upscale_NAI(self.pixmap, raw_bytes=self.raw_bytes)
                    self.finished.emit(result)

            self._remote_upscale_in_flight = True
            self._send_result_upscale_state(ws, True, False, "")
            thread = QThread()
            worker = UpscaleWorker(self.app_context.api_service, context["pixmap"], context["raw_bytes"])
            self._remote_upscale_thread = thread
            self._remote_upscale_worker = worker
            worker.moveToThread(thread)
            thread.started.connect(worker.run)
            worker.finished.connect(lambda result: self._handle_result_upscale(result, context, ws))
            worker.finished.connect(thread.quit)
            worker.finished.connect(worker.deleteLater)
            thread.finished.connect(thread.deleteLater)
            thread.finished.connect(lambda: setattr(self, "_remote_upscale_thread", None))
            thread.finished.connect(lambda: setattr(self, "_remote_upscale_worker", None))
            thread.start()
            print("🌐 Remote: NAI 2x upscale 트리거됨")
        except Exception as e:
            self._remote_upscale_in_flight = False
            message = f"NAI upscale request failed: {e}"
            self._send_result_upscale_state(ws, False, False, message)
            print(f"🌐 Remote: NAI 2x upscale 트리거 실패 — {e}")

    def _handle_result_upscale(self, result: dict, context: dict, ws=None):
        from PIL import Image
        from PyQt6.QtCore import QBuffer, QIODevice

        self._remote_upscale_in_flight = False
        try:
            if not isinstance(result, dict) or result.get("status") != "success":
                message = result.get("message", "NAI upscale failed") if isinstance(result, dict) else "NAI upscale failed"
                self._send_result_upscale_state(ws, False, False, message)
                return

            upscaled_pixmap = result.get("image")
            raw_bytes = result.get("raw_bytes")
            if raw_bytes:
                image_data = raw_bytes
            else:
                qbuffer = QBuffer()
                qbuffer.open(QIODevice.OpenModeFlag.WriteOnly)
                upscaled_pixmap.save(qbuffer, "PNG")
                image_data = qbuffer.data().data()
                qbuffer.close()

            with Image.open(io.BytesIO(image_data)) as opened:
                upscaled_image = opened.copy()

            info_text = (context.get("info_text") or "").strip()
            if info_text:
                info_text = f"{info_text}\nUpscaled: 2x ({upscaled_image.width}x{upscaled_image.height})"
            else:
                info_text = f"Upscaled: 2x ({upscaled_image.width}x{upscaled_image.height})"

            generation_params = dict(context.get("generation_params") or {})
            generation_params.pop("image_bytes", None)
            generation_params["width"] = upscaled_image.width
            generation_params["height"] = upscaled_image.height
            generation_params["api_mode"] = "NAI"
            generation_params["upscale_factor"] = 2

            api_metadata = dict(context.get("api_metadata") or {})
            api_metadata.update({
                "upscaled": True,
                "upscale_factor": 2,
                "upscale_method": "NAI",
            })
            generation_result = {
                "image": upscaled_image,
                "generation_params": generation_params,
                "prompt_context": dict(context.get("prompt_context") or {}),
                "api_metadata": api_metadata,
                "creation_timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "backend_type": "NAI",
            }

            image_window = context.get("image_window")
            if image_window and hasattr(image_window, "add_to_history"):
                image_window.add_to_history(
                    upscaled_image,
                    image_data,
                    info_text,
                    context.get("source_row"),
                    generation_result=generation_result,
                )
            self.app_context.publish("generation_result_available", generation_result)
            self._send_result_upscale_state(ws, False, True, "NAI 2x upscale complete")
        except Exception as e:
            self._send_result_upscale_state(ws, False, False, f"NAI upscale result failed: {e}")
            print(f"🌐 Remote: NAI 2x upscale 결과 처리 실패 — {e}")

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

            if action in {"img2img", "inpaint"}:
                self._open_desktop_img2img_surface(
                    pil_image=pil_image,
                    history_item=None,
                    mode=action,
                    source_label=label or "Input Image",
                )
                print(f"🌐 Remote: desktop {action} surface opened — {label or 'Input Image'}")
                return
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

    def _load_characteristic_tags(self) -> set[str]:
        path = Path("data") / "characteristic_list.txt"
        try:
            return {
                line.strip().replace("_", " ")
                for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            }
        except Exception:
            return set()

    def _build_danbooru_prompt_preview(self, tags: dict) -> str:
        if not isinstance(tags, dict):
            return ""

        main_window = getattr(self.app_context, "main_window", None)
        controller = getattr(main_window, "prompt_gen_controller", None) if main_window else None
        if controller and hasattr(controller, "generate_instant_source_silent"):
            try:
                prompt = controller.generate_instant_source_silent(tags, self._collect_prompt_reopen_settings())
                if prompt:
                    return str(prompt)
            except Exception as e:
                print(f"🌐 Remote: Danbooru prompt preview failed — {e}")

        general_tags = tags.get("general") if isinstance(tags.get("general"), list) else []
        return ", ".join(map(str, general_tags))

    def _fallback_danbooru_prompt(self, tags: dict) -> str:
        general_tags = tags.get("general") if isinstance(tags, dict) and isinstance(tags.get("general"), list) else []
        return ", ".join(map(str, general_tags))

    def _request_danbooru_prompt_preview(self, tags: dict) -> str:
        main_window = getattr(self.app_context, "main_window", None)
        controller = getattr(main_window, "prompt_gen_controller", None) if main_window else None
        if not controller or not self._danbooru_prompt_preview_bridge_connected:
            return self._fallback_danbooru_prompt(tags)

        event = threading.Event()
        request = {
            "tags": tags,
            "prompt": "",
            "event": event,
        }
        self.request_danbooru_prompt_preview.emit(request)
        if not event.wait(5.0):
            print("🌐 Remote: Danbooru prompt preview timed out")
            return self._fallback_danbooru_prompt(tags)
        return str(request.get("prompt") or "") or self._fallback_danbooru_prompt(tags)

    def _do_danbooru_prompt_preview(self, request: dict):
        try:
            request["prompt"] = self._build_danbooru_prompt_preview(request.get("tags", {}))
        except Exception as e:
            print(f"🌐 Remote: Danbooru prompt preview bridge failed — {e}")
            request["prompt"] = self._fallback_danbooru_prompt(request.get("tags", {}))
        finally:
            event = request.get("event")
            if event:
                event.set()

    def _build_danbooru_post_payload(self, query: str) -> dict:
        post = fetch_danbooru_post(
            query,
            characteristic_tags=self._load_characteristic_tags(),
        )
        post["prompt"] = self._request_danbooru_prompt_preview(post.get("tags", {}))
        return post

    def _normalize_danbooru_browser_url(self, value: str = "") -> str:
        text = str(value or "").strip()
        if not text:
            return f"{DANBOORU_BASE_URL}/posts?tags=rating%3Ageneral&z=5"

        if text.isdigit():
            return f"{DANBOORU_BASE_URL}/posts/{text}"

        if text.startswith("//"):
            text = "https:" + text
        elif text.startswith("/"):
            text = urljoin(DANBOORU_BASE_URL, text)
        elif re.match(r"^(?:www\.)?danbooru\.donmai\.us(?:/|$)", text, re.IGNORECASE):
            text = "https://" + text
        elif not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", text):
            text = f"{DANBOORU_BASE_URL}/posts?tags={quote(text, safe=':-_~')}"

        parsed = urlparse(text)
        hostname = (parsed.hostname or "").lower()
        if parsed.scheme not in {"http", "https"} or hostname not in {"danbooru.donmai.us", "www.danbooru.donmai.us"}:
            raise ValueError("Danbooru URL, post ID, or tag query is required")
        return text

    def _clear_danbooru_browser_window(self, *_args):
        self._danbooru_browser_window = None
        self._danbooru_browser_widget = None

    def _create_danbooru_browser_window(self):
        from PyQt6.QtCore import Qt
        from PyQt6.QtWidgets import QApplication, QMainWindow
        from tabs.web_view import BrowserTab

        main_window = getattr(self.app_context, "main_window", None)
        window = QMainWindow(parent=None)
        window.setObjectName("NaiaDanbooruWindow")
        window.setWindowTitle("NAIA - 단부루 웹 (Qt)")
        window.setStyleSheet("QMainWindow#NaiaDanbooruWindow { background: #0a0a0f; }")
        window.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.WindowMinimizeButtonHint
            | Qt.WindowType.WindowMaximizeButtonHint
            | Qt.WindowType.WindowCloseButtonHint
            | Qt.WindowType.WindowTitleHint
        )
        window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        window.resize(1240, 860)
        window.setMinimumSize(760, 520)

        app = QApplication.instance()
        if app and not app.windowIcon().isNull():
            window.setWindowIcon(app.windowIcon())

        browser = BrowserTab(window)
        if main_window and hasattr(main_window, "on_instant_generation_requested"):
            browser.generate_prompt_requested.connect(main_window.on_instant_generation_requested)
        if main_window and hasattr(main_window, "on_generate_with_image_requested"):
            browser.generate_with_image_requested.connect(main_window.on_generate_with_image_requested)

        window.setCentralWidget(browser)
        window.destroyed.connect(self._clear_danbooru_browser_window)
        self._danbooru_browser_window = window
        self._danbooru_browser_widget = browser
        return window, browser

    def _do_open_danbooru_browser(self, url: str):
        try:
            target_url = self._normalize_danbooru_browser_url(url)
            window = self._danbooru_browser_window
            browser = self._danbooru_browser_widget
            if window is None or browser is None:
                window, browser = self._create_danbooru_browser_window()

            window.show()
            if window.isMinimized():
                window.showNormal()
            window.raise_()
            window.activateWindow()
            QTimer.singleShot(120, lambda widget=browser, target=target_url: widget.load_url(target))
            print(f"🌐 Remote: opened detached PyQt6 Danbooru browser — {target_url}")
        except Exception as e:
            self._broadcast_json({
                "type": "toast",
                "message": f"Danbooru Qt window failed: {e}",
                "level": "error",
            })
            print(f"🌐 Remote: failed to open PyQt6 Danbooru browser — {e}")

    def _load_style_thumb_meta(self) -> dict:
        if self._style_thumb_meta_cache is not None:
            return self._style_thumb_meta_cache

        path = Path(self.STYLE_META_TAGS_PATH)
        if not path.exists():
            raise FileNotFoundError(f"Style thumbnail metadata not found: {path}")
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("Style thumbnail metadata is invalid")
        categories = data.get("categories")
        if not isinstance(categories, dict):
            data["categories"] = {}
        self._style_thumb_meta_cache = data
        return data

    def _load_style_thumb_data(self) -> dict:
        if self._style_thumb_data_cache is not None:
            return self._style_thumb_data_cache

        path = Path(self.STYLE_THUMBNAILS_PATH)
        if not path.exists():
            raise FileNotFoundError(f"Style thumbnail data not found: {path}")
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("Style thumbnail data is invalid")
        self._style_thumb_data_cache = {
            str(key): str(value)
            for key, value in data.items()
            if isinstance(value, str) and value.strip()
        }
        return self._style_thumb_data_cache

    def _style_thumb_categories(self) -> dict:
        meta = self._load_style_thumb_meta()
        categories = meta.get("categories", {})
        return categories if isinstance(categories, dict) else {}

    def _build_thumb_tab_state(self) -> dict:
        categories = self._style_thumb_categories()
        thumbnail_data = self._load_style_thumb_data()
        thumbnail_keys = set(thumbnail_data.keys())
        category_payload = []

        for key, info in categories.items():
            if not isinstance(info, dict):
                continue
            tags = [str(tag) for tag in info.get("tags", []) if str(tag or "").strip()]
            available = [tag for tag in tags if tag in thumbnail_keys]
            category_payload.append({
                "key": str(key),
                "name": str(info.get("name") or key),
                "description": str(info.get("description") or ""),
                "total": len(tags),
                "available": len(available),
            })

        selected = ""
        for category in category_payload:
            if category["available"]:
                selected = category["key"]
                break
        if not selected and category_payload:
            selected = category_payload[0]["key"]

        return {
            "categories": category_payload,
            "selected": selected,
            "total_available": sum(category["available"] for category in category_payload),
        }

    def _build_thumb_category_payload(self, category_key: str) -> dict:
        key = str(category_key or "").strip()
        categories = self._style_thumb_categories()
        if key not in categories:
            raise KeyError("Unknown style thumbnail category")

        info = categories[key]
        if not isinstance(info, dict):
            raise KeyError("Unknown style thumbnail category")
        thumbnail_data = self._load_style_thumb_data()
        tags = [
            str(tag)
            for tag in info.get("tags", [])
            if str(tag or "").strip() and str(tag) in thumbnail_data
        ]
        return {
            "key": key,
            "name": str(info.get("name") or key),
            "description": str(info.get("description") or ""),
            "tags": [
                {
                    "tag": tag,
                    "image_url": f"/api/thumb/image?tag={quote(tag, safe='')}",
                }
                for tag in tags
            ],
        }

    def _style_thumb_media_type(self, image_bytes: bytes) -> str:
        if image_bytes.startswith(b"\xff\xd8"):
            return "image/jpeg"
        if image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
            return "image/png"
        if image_bytes.startswith(b"RIFF") and image_bytes[8:12] == b"WEBP":
            return "image/webp"
        return "application/octet-stream"

    def _build_thumb_image_payload(self, tag: str) -> tuple[bytes, str]:
        tag_name = str(tag or "").strip()
        if not tag_name:
            raise ValueError("tag is required")
        encoded = self._load_style_thumb_data().get(tag_name)
        if not encoded:
            raise FileNotFoundError(f"Style thumbnail not found: {tag_name}")
        if encoded.startswith("data:") and "," in encoded:
            encoded = encoded.split(",", 1)[1]
        image_bytes = base64.b64decode(encoded)
        return image_bytes, self._style_thumb_media_type(image_bytes)

    def _artist_thumb_mode_info(self, mode: str) -> dict:
        key = str(mode or "").strip()
        info = self.ARTIST_THUMB_MODES.get(key)
        if not info:
            raise KeyError("Unknown artist thumbnail mode")
        return info

    def _artist_thumb_mode_path(self, mode: str) -> Path:
        return Path(self._artist_thumb_mode_info(mode)["path"])

    def _artist_thumb_file_state(self, info: dict) -> dict:
        path = Path(info["path"])
        exists = path.exists()
        size = path.stat().st_size if exists else 0
        expected_size = int(info.get("expected_size") or 0)
        needs_update = bool(exists and expected_size and size != expected_size)
        return {
            "exists": exists,
            "available": bool(exists and not needs_update),
            "needs_update": needs_update,
            "size": size,
            "expected_size": expected_size,
            "size_mb": round(size / (1024 * 1024), 1) if exists else 0,
            "expected_size_mb": round(expected_size / (1024 * 1024), 1) if expected_size else 0,
            "sha256": str(info.get("sha256") or ""),
        }

    def _artist_thumb_file_sha256(self, path: Path) -> str:
        digest = hashlib.sha256()
        with Path(path).open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest().upper()

    def _validate_artist_thumb_download_file(self, mode: str, path: Path) -> int:
        file_size = Path(path).stat().st_size
        if file_size < (1024 * 1024):
            raise ValueError(f"다운로드된 파일이 너무 작습니다 ({file_size / 1024:.1f} KB)")
        mode_info = self._artist_thumb_mode_info(mode)
        expected_size = int(mode_info.get("expected_size") or 0)
        if expected_size and file_size != expected_size:
            raise ValueError(
                f"다운로드된 파일 크기가 예상과 다릅니다 ({file_size} / {expected_size} bytes)"
            )
        expected_sha256 = str(mode_info.get("sha256") or "").upper()
        if expected_sha256:
            self._set_artist_thumb_download_state(message="다운로드 파일을 검증하는 중...")
            actual_sha256 = self._artist_thumb_file_sha256(Path(path))
            if actual_sha256 != expected_sha256:
                raise ValueError(f"다운로드된 파일 해시가 예상과 다릅니다 ({actual_sha256})")
        return file_size

    def _artist_thumb_download_snapshot(self) -> dict:
        with self._artist_thumb_lock:
            return dict(self._artist_thumb_download_state)

    def _set_artist_thumb_download_state(self, **updates) -> dict:
        with self._artist_thumb_lock:
            self._artist_thumb_download_state.update(updates)
            self._artist_thumb_download_state["updated_at"] = datetime.now().isoformat(timespec="seconds")
            return dict(self._artist_thumb_download_state)

    def _start_artist_thumb_download(self, mode: str) -> dict:
        key = str(mode or "").strip()
        info = self._artist_thumb_mode_info(key)
        path = Path(info["path"])
        url = str(info.get("url") or "")
        if not url:
            raise ValueError(f"download url is not configured: {key}")
        file_state = self._artist_thumb_file_state(info)
        if file_state["available"]:
            return self._set_artist_thumb_download_state(
                active=False,
                mode=key,
                percent=100,
                downloaded_mb=file_state["size_mb"],
                total_mb=file_state["size_mb"],
                message="이미 다운로드되어 있습니다.",
                error="",
                done=True,
            )
        with self._artist_thumb_lock:
            if self._artist_thumb_download_state.get("active"):
                return dict(self._artist_thumb_download_state)
            self._artist_thumb_download_cancel.clear()
            self._artist_thumb_download_state.update({
                "active": True,
                "mode": key,
                "percent": 0,
                "downloaded_mb": 0.0,
                "total_mb": 0.0,
                "message": "다운로드 준비 중...",
                "error": "",
                "done": False,
                "updated_at": datetime.now().isoformat(timespec="seconds"),
            })
            worker = threading.Thread(
                target=self._run_artist_thumb_download,
                args=(key, path, url),
                daemon=True,
                name=f"artist-thumb-download-{key}",
            )
            self._artist_thumb_download_thread = worker
            worker.start()
            return dict(self._artist_thumb_download_state)

    def _cancel_artist_thumb_download(self) -> dict:
        state = self._artist_thumb_download_snapshot()
        if state.get("active"):
            self._artist_thumb_download_cancel.set()
            return self._set_artist_thumb_download_state(message="다운로드 취소 중...")
        return state

    def _run_artist_thumb_download(self, mode: str, target_path: Path, url: str):
        temp_path = target_path.with_suffix(target_path.suffix + ".tmp")
        try:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            request = urllib.request.Request(url, headers={"User-Agent": "NAIA/2.0.0 ArtistThumb Module"})
            self._set_artist_thumb_download_state(message="다운로드 연결 중...")
            with urllib.request.urlopen(request, timeout=30) as response:
                total_size = int(response.headers.get("content-length", 0) or 0)
                total_mb = round(total_size / (1024 * 1024), 1) if total_size else 0.0
                downloaded = 0
                last_update = 0.0
                with temp_path.open("wb") as out_file:
                    while True:
                        if self._artist_thumb_download_cancel.is_set():
                            raise InterruptedError("다운로드가 취소되었습니다.")
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        out_file.write(chunk)
                        downloaded += len(chunk)
                        now = time.time()
                        if now - last_update >= 0.25:
                            percent = min(100, int((downloaded * 100) / total_size)) if total_size else 0
                            downloaded_mb = round(downloaded / (1024 * 1024), 1)
                            message = (
                                f"다운로드 중... {percent}% ({downloaded_mb}/{total_mb} MB)"
                                if total_size else f"다운로드 중... {downloaded_mb} MB"
                            )
                            self._set_artist_thumb_download_state(
                                percent=percent,
                                downloaded_mb=downloaded_mb,
                                total_mb=total_mb,
                                message=message,
                            )
                            last_update = now

            file_size = self._validate_artist_thumb_download_file(mode, temp_path)
            temp_path.replace(target_path)
            with self._artist_thumb_lock:
                self._artist_thumb_data_cache.clear()
                self._artist_thumb_image_cache.clear()
            size_mb = round(file_size / (1024 * 1024), 1)
            self._set_artist_thumb_download_state(
                active=False,
                mode=mode,
                percent=100,
                downloaded_mb=size_mb,
                total_mb=size_mb,
                message=f"다운로드 완료 ({size_mb} MB)",
                error="",
                done=True,
            )
        except InterruptedError as e:
            try:
                if temp_path.exists():
                    temp_path.unlink()
            except Exception:
                pass
            self._set_artist_thumb_download_state(
                active=False,
                mode=mode,
                message=str(e),
                error=str(e),
                done=False,
            )
        except urllib.error.HTTPError as e:
            try:
                if temp_path.exists():
                    temp_path.unlink()
            except Exception:
                pass
            message = f"HTTP 오류 {e.code}: {e.reason}"
            self._set_artist_thumb_download_state(active=False, mode=mode, message=message, error=message, done=False)
        except urllib.error.URLError as e:
            try:
                if temp_path.exists():
                    temp_path.unlink()
            except Exception:
                pass
            message = f"네트워크 오류: {e.reason}"
            self._set_artist_thumb_download_state(active=False, mode=mode, message=message, error=message, done=False)
        except Exception as e:
            try:
                if temp_path.exists():
                    temp_path.unlink()
            except Exception:
                pass
            message = f"다운로드 실패: {e}"
            self._set_artist_thumb_download_state(active=False, mode=mode, message=message, error=message, done=False)

    def _event_preset_download_snapshot(self) -> dict:
        with self._event_preset_download_lock:
            state = dict(self._event_preset_download_state)
        try:
            state["availability"] = self._event_preset_service.status().get("dataAvailability", {})
        except Exception:
            state["availability"] = {}
        return state

    def _set_event_preset_download_state(self, **updates) -> dict:
        with self._event_preset_download_lock:
            self._event_preset_download_state.update(updates)
            self._event_preset_download_state["updated_at"] = datetime.now().isoformat(timespec="seconds")
            return dict(self._event_preset_download_state)

    def _start_event_preset_download(self) -> dict:
        status = self._event_preset_service.status()
        availability = status.get("dataAvailability", {}) if isinstance(status, dict) else {}
        if availability.get("main") == "ready" and availability.get("thumbnails") == "ready":
            return self._set_event_preset_download_state(
                active=False,
                phase="complete",
                percent=100,
                downloaded_mb=0.0,
                total_mb=0.0,
                message="Event Preset 데이터가 이미 설치되어 있습니다.",
                error="",
                done=True,
            )
        with self._event_preset_download_lock:
            if self._event_preset_download_state.get("active"):
                return dict(self._event_preset_download_state)
            self._event_preset_download_cancel.clear()
            self._event_preset_download_state.update({
                "active": True,
                "phase": "main",
                "percent": 0,
                "downloaded_mb": 0.0,
                "total_mb": 0.0,
                "message": "다운로드 준비 중...",
                "error": "",
                "done": False,
                "updated_at": datetime.now().isoformat(timespec="seconds"),
            })
            worker = threading.Thread(
                target=self._run_event_preset_download,
                daemon=True,
                name="event-preset-download",
            )
            self._event_preset_download_thread = worker
            worker.start()
            return dict(self._event_preset_download_state)

    def _cancel_event_preset_download(self) -> dict:
        state = self._event_preset_download_snapshot()
        if state.get("active"):
            self._event_preset_download_cancel.set()
            return self._set_event_preset_download_state(message="다운로드 취소 중...")
        return state

    def _run_event_preset_download(self):
        main_path = self._repo_root / "ui" / "event_preset" / "naia_prompt_preset"
        thumb_path = self._repo_root / "data" / "event_preset_thumbnail"
        try:
            if not main_path.exists() or not self._validate_event_preset_zip(main_path):
                self._download_event_preset_file(
                    phase="main",
                    target_path=main_path,
                    url=EVENT_PRESET_DOWNLOAD_URL,
                    user_agent="NAIA/2.0.0 EventPreset Module",
                    validator=self._validate_event_preset_zip,
                    invalid_message="다운로드된 Event Preset 데이터가 손상되었습니다.",
                )
            else:
                self._set_event_preset_download_state(
                    phase="main",
                    percent=100,
                    message="Event Preset 데이터가 이미 존재합니다.",
                )

            if not thumb_path.exists() or thumb_path.stat().st_size < 1_000_000:
                self._download_event_preset_file(
                    phase="thumbnail",
                    target_path=thumb_path,
                    url=EVENT_PRESET_THUMBNAIL_DOWNLOAD_URL,
                    user_agent="NAIA/2.0.0 EventPreset Thumbnail",
                    validator=lambda path: path.exists() and path.stat().st_size >= 1_000_000,
                    invalid_message="다운로드된 썸네일 데이터가 손상되었습니다.",
                )
            else:
                self._set_event_preset_download_state(
                    phase="thumbnail",
                    percent=100,
                    message="썸네일 데이터가 이미 존재합니다.",
                )

            self._event_preset_service = EventPresetService(self._repo_root)
            self._preset_composer_service = PresetComposerService(
                self._event_preset_service,
                axis_providers={"clothes": self._clothes_preset_service},
            )
            self._publish_preset_services()
            self._set_event_preset_download_state(
                active=False,
                phase="complete",
                percent=100,
                message="Event Preset 데이터 다운로드 완료",
                error="",
                done=True,
            )
        except InterruptedError as e:
            self._set_event_preset_download_state(
                active=False,
                message=str(e),
                error=str(e),
                done=False,
            )
        except urllib.error.HTTPError as e:
            message = f"HTTP 오류 {e.code}: {e.reason}"
            self._set_event_preset_download_state(active=False, message=message, error=message, done=False)
        except urllib.error.URLError as e:
            message = f"네트워크 오류: {e.reason}"
            self._set_event_preset_download_state(active=False, message=message, error=message, done=False)
        except Exception as e:
            message = f"다운로드 실패: {e}"
            self._set_event_preset_download_state(active=False, message=message, error=message, done=False)

    def _download_event_preset_file(
        self,
        *,
        phase: str,
        target_path: Path,
        url: str,
        user_agent: str,
        validator,
        invalid_message: str,
    ) -> None:
        temp_path = target_path.with_name(target_path.name + ".download_tmp")
        target_path.parent.mkdir(parents=True, exist_ok=True)
        if temp_path.exists():
            temp_path.unlink()
        if target_path.exists() and not validator(target_path):
            target_path.unlink()

        self._set_event_preset_download_state(
            phase=phase,
            percent=5,
            downloaded_mb=0.0,
            total_mb=0.0,
            message="다운로드 연결 중...",
        )
        request = urllib.request.Request(url, headers={"User-Agent": user_agent})
        try:
            with urllib.request.urlopen(request, timeout=30, context=EVENT_PRESET_SSL_CONTEXT) as response:
                total_size = int(response.headers.get("content-length", 0) or 0)
                total_mb = round(total_size / (1024 * 1024), 1) if total_size else 0.0
                downloaded = 0
                last_update = 0.0
                with temp_path.open("wb") as out_file:
                    while True:
                        if self._event_preset_download_cancel.is_set():
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
                            self._set_event_preset_download_state(
                                percent=percent,
                                downloaded_mb=downloaded_mb,
                                total_mb=total_mb,
                                message=message,
                            )
                            last_update = now

            self._set_event_preset_download_state(percent=92, message="검증 중...")
            if not validator(temp_path):
                raise ValueError(invalid_message)
            temp_path.replace(target_path)
            size_mb = round(target_path.stat().st_size / (1024 * 1024), 1)
            self._set_event_preset_download_state(
                percent=100,
                downloaded_mb=size_mb,
                total_mb=size_mb,
                message="설치 완료",
            )
        except Exception:
            try:
                if temp_path.exists():
                    temp_path.unlink()
            except Exception:
                pass
            raise

    @staticmethod
    def _validate_event_preset_zip(path: Path) -> bool:
        try:
            with zipfile.ZipFile(path, "r") as zf:
                names = set(zf.namelist())
                return (
                    "base/event_taxonomy_v2_1.parquet" in names
                    and "base/tag_catalog.parquet" in names
                )
        except (zipfile.BadZipFile, OSError, Exception):
            return False

    def _artist_thumb_artist_weights(self) -> dict:
        try:
            from artist_dictionary import artist_dict
            return artist_dict if isinstance(artist_dict, dict) else {}
        except Exception as e:
            print(f"🌐 Remote: artist dictionary 로드 실패 — {e}")
            return {}

    def _read_artist_thumb_lines(self, path: Path) -> list[str]:
        try:
            if not path.exists():
                return []
            with path.open("r", encoding="utf-8") as f:
                return [line.strip() for line in f if line.strip()]
        except Exception as e:
            print(f"🌐 Remote: artist list 파일 읽기 실패 ({path}) — {e}")
            return []

    def _write_artist_thumb_lines(self, path: Path, values: list[str]):
        path.parent.mkdir(parents=True, exist_ok=True)
        seen = set()
        cleaned = []
        for value in values:
            text = str(value or "").strip()
            if not text or text in seen:
                continue
            seen.add(text)
            cleaned.append(text)
        if path.exists() and self._read_artist_thumb_lines(path) == cleaned:
            return
        with path.open("w", encoding="utf-8") as f:
            for value in cleaned:
                f.write(f"{value}\n")

    def _artist_thumb_state_path(self) -> Path:
        return Path("artist_thumb") / "artist_state.json"

    def _artist_thumb_favorite_path(self) -> Path:
        return Path("wildcards") / "favorite_artist.txt"

    def _artist_thumb_banned_path(self) -> Path:
        return Path("artist_thumb") / "banned_artist.txt"

    def _artist_thumb_options_path(self) -> Path:
        return Path("artist_thumb") / "generate_options.json"

    def _artist_thumb_options_mode(self, mode: str = "") -> str:
        mode_key = str(mode or "").strip().upper()
        if mode_key in self.ARTIST_THUMB_OPTION_MODES:
            return mode_key
        current_mode = str(self._current_api_mode() or "").strip().upper()
        if current_mode in self.ARTIST_THUMB_OPTION_MODES:
            return current_mode
        return "NAI"

    def _normalize_artist_thumb_options(self, data, mode: str = "") -> dict:
        source = data if isinstance(data, dict) else {}
        legacy = {
            "prefix": str(source.get("prefix") or ""),
            "postfix": str(source.get("postfix") or ""),
        }
        raw_modes = source.get("modes") if isinstance(source.get("modes"), dict) else {}
        modes = {}
        for mode_key in self.ARTIST_THUMB_OPTION_MODES:
            values = raw_modes.get(mode_key) if isinstance(raw_modes.get(mode_key), dict) else {}
            prefix = values.get("prefix") if "prefix" in values else legacy["prefix"]
            postfix = values.get("postfix") if "postfix" in values else legacy["postfix"]
            modes[mode_key] = {
                "prefix": str(prefix or ""),
                "postfix": str(postfix or ""),
            }
        mode_key = self._artist_thumb_options_mode(mode)
        selected = modes.get(mode_key, modes["NAI"])
        return {
            "version": 2,
            "mode": mode_key,
            "prefix": selected["prefix"],
            "postfix": selected["postfix"],
            "modes": modes,
        }

    def _artist_thumb_favorite_thumbnail_cache_path(self) -> Path:
        return Path("artist_thumb") / "favorite_thumbnail_cache.json"

    def _parse_resolution_pair(self, value) -> tuple[int, int] | None:
        return parse_resolution_pair(value)

    def _artist_thumb_resolution_allowed(self, width: int, height: int) -> bool:
        if width <= 0 or height <= 0:
            return False
        if width % 64 != 0 or height % 64 != 0:
            return False
        return width * height <= MAX_1MP_PIXELS

    def _artist_thumb_resolution_options(self) -> list[tuple[int, int]]:
        defaults = list(STANDARD_1MP_RESOLUTIONS)
        mw = getattr(self.app_context, "main_window", None)
        combo = getattr(mw, "resolution_combo", None)
        options = []
        seen = set()
        try:
            count = combo.count() if combo is not None else 0
        except Exception:
            count = 0
        for index in range(count):
            try:
                pair = self._parse_resolution_pair(combo.itemText(index))
            except Exception:
                pair = None
            if pair:
                pair = nearest_standard_1mp_resolution(*pair)
            if pair and self._artist_thumb_resolution_allowed(*pair) and pair not in seen:
                options.append(pair)
                seen.add(pair)
        if not options:
            options = [pair for pair in defaults if self._artist_thumb_resolution_allowed(*pair)]
        return options or [(832, 1216)]

    def _artist_thumb_random_resolution(self) -> tuple[int, int, str]:
        width, height = random.SystemRandom().choice(self._artist_thumb_resolution_options())
        return width, height, "random"

    def _coerce_artist_thumb_resolution(self, width, height) -> tuple[int, int]:
        pair = nearest_standard_1mp_resolution(width, height)
        if self._artist_thumb_resolution_allowed(*pair):
            return pair
        return (832, 1216)

    def _normalize_artist_thumb_values(self, values) -> list[str]:
        seen = set()
        normalized = []
        if not isinstance(values, (list, tuple, set)):
            return []
        for value in values:
            text = str(value or "").strip()
            if not text or text in seen:
                continue
            seen.add(text)
            normalized.append(text)
        return normalized

    def _merge_artist_thumb_values(self, primary, additions) -> list[str]:
        return self._normalize_artist_thumb_values([
            *self._normalize_artist_thumb_values(primary),
            *self._normalize_artist_thumb_values(additions),
        ])

    def _normalize_artist_thumb_state(self, data, fallback: dict | None = None) -> dict:
        source = data if isinstance(data, dict) else {}
        fallback = fallback if isinstance(fallback, dict) else {}
        favorites_source = source.get("favorites", fallback.get("favorites", []))
        banned_source = source.get("banned", fallback.get("banned", []))
        return {
            "version": 1,
            "favorites": self._normalize_artist_thumb_values(favorites_source),
            "banned": self._normalize_artist_thumb_values(banned_source),
        }

    def _legacy_artist_thumb_state(self) -> dict:
        return self._normalize_artist_thumb_state({
            "favorites": self._read_artist_thumb_lines(self._artist_thumb_favorite_path()),
            "banned": self._read_artist_thumb_lines(self._artist_thumb_banned_path()),
        })

    def _read_artist_thumb_state_file(self, *, merge_legacy_additions: bool = True) -> dict:
        path = self._artist_thumb_state_path()
        if not path.exists():
            raise FileNotFoundError(path)
        try:
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            raise RuntimeError(f"artist thumb state JSON is invalid: {path}: {e}") from e
        state = self._normalize_artist_thumb_state(data)
        if merge_legacy_additions:
            legacy = self._legacy_artist_thumb_state()
            state["favorites"] = self._merge_artist_thumb_values(state["favorites"], legacy["favorites"])
            state["banned"] = self._merge_artist_thumb_values(state["banned"], legacy["banned"])
        return state

    def _sync_artist_thumb_state_mirrors(self, state: dict):
        normalized = self._normalize_artist_thumb_state(state)
        # favorite_artist.txt는 와일드카드 호출용 공개 미러이므로 JSON 원본에서 항상 복원한다.
        self._write_artist_thumb_lines(self._artist_thumb_favorite_path(), normalized["favorites"])
        # 기존 제외 목록 파일도 수동 확인/호환을 위해 유지한다.
        self._write_artist_thumb_lines(self._artist_thumb_banned_path(), normalized["banned"])

    def _write_artist_thumb_state(self, state: dict) -> dict:
        normalized = self._normalize_artist_thumb_state(state)
        path = self._artist_thumb_state_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_name(f"{path.name}.tmp")
        with temp_path.open("w", encoding="utf-8") as f:
            json.dump(normalized, f, ensure_ascii=False, indent=2)
            f.write("\n")
        temp_path.replace(path)
        self._sync_artist_thumb_state_mirrors(normalized)
        return normalized

    def _ensure_artist_thumb_state(self) -> dict:
        with self._artist_thumb_lock:
            path = self._artist_thumb_state_path()
            if not path.exists():
                return self._write_artist_thumb_state(self._legacy_artist_thumb_state())
            return self._read_artist_thumb_state_file()

    def _artist_thumb_state(self) -> dict:
        with self._artist_thumb_lock:
            return self._read_artist_thumb_state_file()

    def _artist_thumb_favorites(self) -> list[str]:
        return list(self._artist_thumb_state().get("favorites", []))

    def _artist_thumb_banned(self) -> list[str]:
        return list(self._artist_thumb_state().get("banned", []))

    def _artist_thumb_custom_filters(self, weights: dict | None = None, banned_set: set[str] | None = None) -> list[dict]:
        base = Path("artist_thumb")
        filters = []
        if not base.exists():
            return filters
        weights = weights or self._artist_thumb_artist_weights()
        banned_set = banned_set if banned_set is not None else set(self._artist_thumb_banned())
        for path in sorted(base.glob("*.txt")):
            if path.name == "banned_artist.txt":
                continue
            items = self._read_artist_thumb_lines(path)
            filters.append({
                "key": f"custom:{path.stem}",
                "name": path.stem,
                "count": len([a for a in items if a in weights and a not in banned_set]),
            })
        return filters

    def _load_artist_thumb_options(self, mode: str = "") -> dict:
        path = self._artist_thumb_options_path()
        if not path.exists():
            return self._normalize_artist_thumb_options({}, mode)
        try:
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            return self._normalize_artist_thumb_options(data, mode)
        except Exception as e:
            print(f"🌐 Remote: artist thumb 옵션 로드 실패 — {e}")
            return self._normalize_artist_thumb_options({}, mode)

    def _save_artist_thumb_options(self, options: dict) -> dict:
        requested_mode = options.get("mode") if isinstance(options, dict) else ""
        mode = self._artist_thumb_options_mode(requested_mode)
        current = self._load_artist_thumb_options(mode)
        if isinstance(options, dict):
            mode_values = current["modes"].setdefault(mode, {"prefix": "", "postfix": ""})
            if "prefix" in options:
                mode_values["prefix"] = str(options.get("prefix") or "")
            if "postfix" in options:
                mode_values["postfix"] = str(options.get("postfix") or "")
        selected = current["modes"].get(mode, {"prefix": "", "postfix": ""})
        current["version"] = 2
        current["mode"] = mode
        current["prefix"] = selected.get("prefix", "")
        current["postfix"] = selected.get("postfix", "")
        path = self._artist_thumb_options_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            json.dump(current, f, ensure_ascii=False, indent=2)
            f.write("\n")
        return current

    def _normalize_artist_thumb_thumbnail_cache(self, data) -> dict:
        source = data if isinstance(data, dict) else {}
        raw_items = source.get("items", source.get("thumbnails", {}))
        if not isinstance(raw_items, dict):
            raw_items = {}
        items = {}
        for artist, value in raw_items.items():
            artist_name = str(artist or "").strip()
            if not artist_name:
                continue
            if isinstance(value, dict):
                thumbnail = str(value.get("thumbnail") or value.get("image") or "").strip()
                mode = str(value.get("mode") or "").strip()
                updated_at = str(value.get("updated_at") or "").strip()
            elif isinstance(value, (list, tuple)):
                thumbnail = str(value[0] if value else "").strip()
                mode = ""
                updated_at = ""
            else:
                thumbnail = str(value or "").strip()
                mode = ""
                updated_at = ""
            if not thumbnail:
                continue
            items[artist_name] = {
                "mode": mode,
                "thumbnail": thumbnail,
                "updated_at": updated_at,
            }
        return {
            "version": 1,
            "items": items,
        }

    def _load_artist_thumb_thumbnail_cache(self) -> dict:
        path = self._artist_thumb_favorite_thumbnail_cache_path()
        if not path.exists():
            return {"version": 1, "items": {}}
        try:
            with path.open("r", encoding="utf-8") as f:
                return self._normalize_artist_thumb_thumbnail_cache(json.load(f))
        except Exception as e:
            raise RuntimeError(f"artist thumb thumbnail cache JSON is invalid: {path}: {e}") from e

    def _write_artist_thumb_thumbnail_cache(self, cache: dict) -> dict:
        normalized = self._normalize_artist_thumb_thumbnail_cache(cache)
        path = self._artist_thumb_favorite_thumbnail_cache_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_name(f"{path.name}.tmp")
        with temp_path.open("w", encoding="utf-8") as f:
            json.dump(normalized, f, ensure_ascii=False, indent=2)
            f.write("\n")
        temp_path.replace(path)
        return normalized

    def _artist_thumb_cache_entry_from_data(self, artist: str, mode: str, thumb_data: dict) -> dict | None:
        artist_name = str(artist or "").strip()
        if not artist_name or not isinstance(thumb_data, dict):
            return None
        encoded_list = thumb_data.get(artist_name)
        if not isinstance(encoded_list, (list, tuple)) or not encoded_list:
            return None
        thumbnail = str(encoded_list[0] or "").strip()
        if not thumbnail:
            return None
        return {
            "mode": str(mode or "").strip(),
            "thumbnail": thumbnail,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }

    def _sync_artist_thumb_favorite_thumbnail_cache(self, mode: str = "", thumb_data: dict | None = None) -> dict:
        mode_key = str(mode or "").strip()
        with self._artist_thumb_lock:
            favorites = self._artist_thumb_favorites()
            favorite_set = set(favorites)
            cache = self._load_artist_thumb_thumbnail_cache()
            items = dict(cache.get("items") or {})
            changed = False
            removed = 0
            added = 0

            for artist in list(items.keys()):
                if artist not in favorite_set:
                    items.pop(artist, None)
                    removed += 1
                    changed = True

            missing_artists = [artist for artist in favorites if not items.get(artist, {}).get("thumbnail")]
            if not changed and not missing_artists:
                return {
                    "count": len(items),
                    "added": 0,
                    "removed": 0,
                    "missing": 0,
                    "changed": False,
                    "path": str(self._artist_thumb_favorite_thumbnail_cache_path()),
                    "cache": {"version": 1, "items": items},
                }

            if mode_key and thumb_data is None:
                thumb_data = self._artist_thumb_data_cache.get(mode_key)

            if mode_key and isinstance(thumb_data, dict):
                for artist in missing_artists:
                    entry = self._artist_thumb_cache_entry_from_data(artist, mode_key, thumb_data)
                    if not entry:
                        continue
                    items[artist] = entry
                    added += 1
                    changed = True

            if changed:
                cache = self._write_artist_thumb_thumbnail_cache({"version": 1, "items": items})
            else:
                cache = {"version": 1, "items": items}

            missing = len([artist for artist in favorites if not items.get(artist, {}).get("thumbnail")])
            return {
                "count": len(items),
                "added": added,
                "removed": removed,
                "missing": missing,
                "changed": changed,
                "path": str(self._artist_thumb_favorite_thumbnail_cache_path()),
                "cache": cache,
            }

    def _cache_artist_thumb_favorite_from_loaded_mode(self, artist: str, mode: str) -> bool:
        artist_name = str(artist or "").strip()
        mode_key = str(mode or "").strip()
        if not artist_name or not mode_key:
            return False
        with self._artist_thumb_lock:
            thumb_data = self._artist_thumb_data_cache.get(mode_key)
            entry = self._artist_thumb_cache_entry_from_data(artist_name, mode_key, thumb_data or {})
            if not entry:
                return False
            try:
                cache = self._load_artist_thumb_thumbnail_cache()
            except Exception as e:
                print(f"🌐 Remote: artist thumb favorite thumbnail cache reset failed cache — {e}")
                cache = {"version": 1, "items": {}}
            items = dict(cache.get("items") or {})
            current = items.get(artist_name) or {}
            if current.get("thumbnail") == entry.get("thumbnail") and current.get("mode") == entry.get("mode"):
                return False
            items[artist_name] = entry
            self._write_artist_thumb_thumbnail_cache({"version": 1, "items": items})
            return True

    def _remove_artist_thumb_favorite_thumbnail_cache(self, artist: str) -> bool:
        artist_name = str(artist or "").strip()
        if not artist_name:
            return False
        with self._artist_thumb_lock:
            try:
                cache = self._load_artist_thumb_thumbnail_cache()
            except Exception as e:
                print(f"🌐 Remote: artist thumb favorite thumbnail cache remove skipped — {e}")
                return False
            items = dict(cache.get("items") or {})
            if artist_name not in items:
                return False
            items.pop(artist_name, None)
            self._write_artist_thumb_thumbnail_cache({"version": 1, "items": items})
            return True

    def _load_artist_thumb_data(self, mode: str) -> dict:
        key = str(mode or "").strip()
        if not key:
            return {}
        with self._artist_thumb_lock:
            info = self._artist_thumb_mode_info(key)
            file_state = self._artist_thumb_file_state(info)
            cached = self._artist_thumb_data_cache.get(key)
            if cached is not None and not file_state["needs_update"]:
                if key == "NAID4.5F-31000":
                    try:
                        self._sync_artist_thumb_favorite_thumbnail_cache(key, cached)
                    except Exception as e:
                        print(f"🌐 Remote: artist thumb favorite thumbnail cache sync failed — {e}")
                return cached
            if not file_state["available"]:
                self._artist_thumb_data_cache.pop(key, None)
                path = Path(info["path"])
                if file_state["needs_update"]:
                    raise RuntimeError(f"Artist thumbnail data needs update: {path}")
                raise FileNotFoundError(f"Artist thumbnail data not found: {path}")
            path = self._artist_thumb_mode_path(key)
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("Artist thumbnail data is invalid")
            self._artist_thumb_data_cache.clear()
            self._artist_thumb_image_cache.clear()
            self._artist_thumb_data_cache[key] = data
            if key == "NAID4.5F-31000":
                try:
                    self._sync_artist_thumb_favorite_thumbnail_cache(key, data)
                except Exception as e:
                    print(f"🌐 Remote: artist thumb favorite thumbnail cache sync failed — {e}")
            return data

    def _artist_thumb_format_count(self, value) -> int:
        try:
            return int(value)
        except Exception:
            return 0

    def _artist_thumb_base_list(
        self,
        filter_key: str,
        weights: dict,
        *,
        exclude_banned: bool = True,
        allow_banned_filter: bool = True,
    ) -> tuple[list[str], str]:
        key = str(filter_key or "all").strip() or "all"
        favorites = self._artist_thumb_favorites()
        banned = self._artist_thumb_banned()
        banned_set = set(banned)

        if key == "favorites":
            items = [a for a in favorites if a in weights]
            if exclude_banned:
                items = [a for a in items if a not in banned_set]
            return items, "관심 작가"
        if key == "banned":
            if not allow_banned_filter:
                return [], "제외 작가"
            return [a for a in banned if a in weights], "제외 작가"
        if key.startswith("custom:"):
            name = key.split(":", 1)[1].strip()
            safe_name = Path(name).name
            items = self._read_artist_thumb_lines(Path("artist_thumb") / f"{safe_name}.txt")
            items = [a for a in items if a in weights]
            if exclude_banned:
                items = [a for a in items if a not in banned_set]
            return items, safe_name

        return [a for a in weights.keys() if a not in banned_set], "전체 목록"

    def _artist_thumb_random_sample(
        self,
        artists: list[str],
        sample_size: int,
        history_key: tuple[str, str, str, int],
    ) -> list[str]:
        if sample_size <= 0 or not artists:
            return []

        with self._artist_thumb_lock:
            recent = set(self._artist_thumb_random_history.get(history_key, []))

        candidates = [artist for artist in artists if artist not in recent]
        if len(candidates) < sample_size:
            candidates = list(artists)

        picked = random.SystemRandom().sample(candidates, min(sample_size, len(candidates)))

        with self._artist_thumb_lock:
            history = [artist for artist in self._artist_thumb_random_history.get(history_key, []) if artist in artists]
            history.extend(picked)
            max_history = max(sample_size * 8, sample_size)
            if len(history) > max_history:
                history = history[-max_history:]
            self._artist_thumb_random_history[history_key] = history
            if len(self._artist_thumb_random_history) > 64:
                self._artist_thumb_random_history.pop(next(iter(self._artist_thumb_random_history)), None)

        return picked

    def _build_artist_thumb_state(self) -> dict:
        weights = self._artist_thumb_artist_weights()
        favorites = self._artist_thumb_favorites()
        banned = self._artist_thumb_banned()
        banned_set = set(banned)
        try:
            favorite_thumbnail_cache = self._sync_artist_thumb_favorite_thumbnail_cache()
            favorite_thumbnail_cache.pop("cache", None)
        except Exception as e:
            print(f"🌐 Remote: artist thumb favorite thumbnail cache sync failed — {e}")
            favorite_thumbnail_cache = {
                "count": 0,
                "added": 0,
                "removed": 0,
                "missing": len(favorites),
                "changed": False,
                "error": str(e),
            }
        modes = []
        for key, info in self.ARTIST_THUMB_MODES.items():
            file_state = self._artist_thumb_file_state(info)
            modes.append({
                "key": key,
                "label": str(info.get("label") or key),
                "available": file_state["available"],
                "needs_update": file_state["needs_update"],
                "loaded": key in self._artist_thumb_data_cache and file_state["available"],
                "size": file_state["size"],
                "expected_size": file_state["expected_size"],
                "size_mb": file_state["size_mb"],
                "expected_size_mb": file_state["expected_size_mb"],
                "sha256": file_state["sha256"],
            })
        return {
            "modes": modes,
            "filters": [
                {"key": "all", "name": "전체 목록", "count": len(self._artist_thumb_base_list("all", weights)[0])},
                {
                    "key": "favorites",
                    "name": "관심 작가",
                    "count": len(self._artist_thumb_base_list("favorites", weights)[0]),
                },
                {"key": "banned", "name": "제외 작가", "count": len([a for a in banned if a in weights])},
                *self._artist_thumb_custom_filters(weights, banned_set),
            ],
            "artist_count": len(weights),
            "favorites": favorites,
            "banned": banned,
            "options": self._load_artist_thumb_options(),
            "download": self._artist_thumb_download_snapshot(),
            "favorite_thumbnail_cache": favorite_thumbnail_cache,
        }

    def _build_artist_thumb_list(
        self,
        mode: str = "",
        filter_key: str = "all",
        query: str = "",
        page: int = 0,
        per_page: int = 48,
        random_sample: bool = False,
    ) -> dict:
        mode_key = str(mode or "").strip()
        weights = self._artist_thumb_artist_weights()
        thumb_data = self._load_artist_thumb_data(mode_key) if mode_key else {}
        base_list, filter_name = self._artist_thumb_base_list(
            filter_key,
            weights,
            exclude_banned=True,
            allow_banned_filter=not random_sample,
        )
        if thumb_data:
            thumb_keys = set(thumb_data.keys())
            base_list = [artist for artist in base_list if artist in thumb_keys]

        query_text = str(query or "").strip().lower().replace("_", " ")
        if query_text:
            base_list = [
                artist for artist in base_list
                if query_text in artist.lower().replace("_", " ")
            ]

        base_list = sorted(
            base_list,
            key=lambda artist: weights.get(artist, 0),
            reverse=True,
        )
        total = len(base_list)
        per_page = max(12, min(96, int(per_page or 48)))
        page = max(0, int(page or 0))
        total_pages = max(1, (total + per_page - 1) // per_page)
        if page >= total_pages:
            page = max(0, total_pages - 1)
        if random_sample:
            sample_size = min(per_page, total)
            artists = self._artist_thumb_random_sample(
                base_list,
                sample_size,
                (mode_key, str(filter_key or "all"), query_text, per_page),
            )
        else:
            start = page * per_page
            artists = base_list[start:start + per_page]
        favorite_set = set(self._artist_thumb_favorites())
        banned_set = set(self._artist_thumb_banned())
        try:
            favorite_thumb_items = self._load_artist_thumb_thumbnail_cache().get("items", {})
        except Exception as e:
            print(f"🌐 Remote: artist thumb favorite thumbnail cache load failed — {e}")
            favorite_thumb_items = {}

        def item_image_url(artist: str) -> str:
            if mode_key and artist in thumb_data:
                return f"/api/artist-thumb/image?mode={quote(mode_key, safe='')}&artist={quote(artist, safe='')}"
            if artist in favorite_thumb_items:
                return f"/api/artist-thumb/favorite-image?artist={quote(artist, safe='')}"
            return ""

        return {
            "mode": mode_key,
            "filter": str(filter_key or "all"),
            "filter_name": filter_name,
            "query": query,
            "page": page,
            "per_page": per_page,
            "total": total,
            "total_pages": total_pages,
            "random": bool(random_sample),
            "excluded_count": len(banned_set),
            "items": [
                {
                    "artist": artist,
                    "weight": self._artist_thumb_format_count(weights.get(artist, 0)),
                    "favorite": artist in favorite_set,
                    "banned": artist in banned_set,
                    "has_image": bool(item_image_url(artist)),
                    "image_url": item_image_url(artist),
                }
                for artist in artists
            ],
        }

    def _artist_thumb_media_type(self, image_bytes: bytes) -> str:
        if image_bytes.startswith(b"\xff\xd8"):
            return "image/jpeg"
        if image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
            return "image/png"
        if image_bytes.startswith(b"RIFF") and image_bytes[8:12] == b"WEBP":
            return "image/webp"
        return "application/octet-stream"

    def _build_artist_thumb_image_payload_from_encoded(self, encoded) -> tuple[bytes, str]:
        encoded_text = str(encoded or "")
        if encoded_text.startswith("data:") and "," in encoded_text:
            encoded_text = encoded_text.split(",", 1)[1]
        raw = base64.b64decode(encoded_text)

        try:
            from PIL import Image
            image = Image.open(io.BytesIO(raw))
            image.load()
            if image.width > 170:
                image = image.crop((85, 0, image.width - 85, image.height))
            if image.mode not in ("RGB", "L"):
                image = image.convert("RGB")
            out = io.BytesIO()
            image.save(out, format="JPEG", quality=86, optimize=True)
            return out.getvalue(), "image/jpeg"
        except Exception:
            return raw, self._artist_thumb_media_type(raw)

    def _build_artist_thumb_image_payload(self, mode: str, artist: str) -> tuple[bytes, str]:
        mode_key = str(mode or "").strip()
        artist_name = str(artist or "").strip()
        if not mode_key:
            raise ValueError("mode is required")
        if not artist_name:
            raise ValueError("artist is required")
        cache_key = (mode_key, artist_name)
        with self._artist_thumb_lock:
            cached = self._artist_thumb_image_cache.get(cache_key)
            if cached:
                return cached

        data = self._load_artist_thumb_data(mode_key)
        encoded_list = data.get(artist_name)
        if not encoded_list or not encoded_list[0]:
            raise FileNotFoundError(f"Artist thumbnail not found: {artist_name}")
        image_bytes, media_type = self._build_artist_thumb_image_payload_from_encoded(encoded_list[0])

        with self._artist_thumb_lock:
            if len(self._artist_thumb_image_cache) > 512:
                self._artist_thumb_image_cache.pop(next(iter(self._artist_thumb_image_cache)), None)
            self._artist_thumb_image_cache[cache_key] = (image_bytes, media_type)
        return image_bytes, media_type

    def _build_artist_thumb_favorite_image_payload(self, artist: str) -> tuple[bytes, str]:
        artist_name = str(artist or "").strip()
        if not artist_name:
            raise ValueError("artist is required")
        cache_key = ("__favorite_cache__", artist_name)
        with self._artist_thumb_lock:
            cached = self._artist_thumb_image_cache.get(cache_key)
            if cached:
                return cached
            thumb_cache = self._load_artist_thumb_thumbnail_cache()
            entry = (thumb_cache.get("items") or {}).get(artist_name) or {}
            encoded = entry.get("thumbnail")
        if not encoded:
            raise FileNotFoundError(f"Favorite artist thumbnail not found: {artist_name}")
        image_bytes, media_type = self._build_artist_thumb_image_payload_from_encoded(encoded)
        with self._artist_thumb_lock:
            if len(self._artist_thumb_image_cache) > 512:
                self._artist_thumb_image_cache.pop(next(iter(self._artist_thumb_image_cache)), None)
            self._artist_thumb_image_cache[cache_key] = (image_bytes, media_type)
        return image_bytes, media_type

    def _set_artist_thumb_favorite(self, artist: str, favorite: bool, mode: str = "") -> dict:
        artist_name = str(artist or "").strip()
        if not artist_name:
            raise ValueError("artist is required")
        with self._artist_thumb_lock:
            state = self._artist_thumb_state()
            favorites = list(state.get("favorites", []))
            if favorite and artist_name not in favorites:
                favorites.append(artist_name)
            elif not favorite and artist_name in favorites:
                favorites = [a for a in favorites if a != artist_name]
            state["favorites"] = favorites
            self._write_artist_thumb_state(state)
            if favorite:
                self._cache_artist_thumb_favorite_from_loaded_mode(artist_name, mode)
            else:
                self._remove_artist_thumb_favorite_thumbnail_cache(artist_name)
        return self._build_artist_thumb_state()

    def _set_artist_thumb_banned(self, artist: str, banned: bool) -> dict:
        artist_name = str(artist or "").strip()
        if not artist_name:
            raise ValueError("artist is required")
        with self._artist_thumb_lock:
            state = self._artist_thumb_state()
            banned_list = list(state.get("banned", []))
            if banned and artist_name not in banned_list:
                banned_list.append(artist_name)
            elif not banned and artist_name in banned_list:
                banned_list = [a for a in banned_list if a != artist_name]
            state["banned"] = banned_list
            if banned:
                state["favorites"] = [a for a in state.get("favorites", []) if a != artist_name]
            self._write_artist_thumb_state(state)
        return self._build_artist_thumb_state()

    def _artist_thumb_final_prompt(self, payload: dict) -> str:
        prompt_parts = []
        for key in ("prefix", "positive", "postfix"):
            value = str(payload.get(key) or "").strip()
            if value:
                prompt_parts.append(value)
        return ", ".join(prompt_parts).strip()

    def _build_artist_thumb_random_peng_override(self, artist_prompt: str) -> dict:
        artist_value = str(artist_prompt or "").strip().rstrip(",")
        if not artist_value:
            raise ValueError("artist_prompt is required")

        module = self._find_module("prompt_engineering")
        if not module:
            return {
                "pre_prompt": artist_value,
                "post_prompt": "",
                "auto_hide": "",
                "preprocessing_options": {},
            }

        pre_prompt = module.pre_textedit.toPlainText() if module.pre_textedit else ""
        post_prompt = module.post_textedit.toPlainText() if module.post_textedit else ""
        auto_hide = module.auto_hide_textedit.toPlainText() if module.auto_hide_textedit else ""
        preprocessing = {}
        for label, checkbox in module.preprocessing_checkboxes.items():
            key = module.option_key_map.get(label, label)
            preprocessing[key] = checkbox.isChecked()

        pre_prompt = str(pre_prompt or "").strip()
        return {
            "pre_prompt": f"{artist_value}, {pre_prompt}" if pre_prompt else artist_value,
            "post_prompt": post_prompt,
            "auto_hide": auto_hide,
            "preprocessing_options": preprocessing,
        }

    async def _request_artist_thumb_random_peng_override(self, artist_prompt: str, timeout: float = 5.0) -> dict:
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        request_id = uuid.uuid4().hex
        with self._artist_thumb_random_peng_requests_lock:
            self._pending_artist_thumb_random_peng_requests[request_id] = {
                "loop": loop,
                "future": future,
            }
        self.request_artist_thumb_random_peng.emit(request_id, artist_prompt)
        try:
            result = await asyncio.wait_for(future, timeout=timeout)
            return result if isinstance(result, dict) else {}
        except asyncio.TimeoutError:
            with self._artist_thumb_random_peng_requests_lock:
                self._pending_artist_thumb_random_peng_requests.pop(request_id, None)
            raise
        except asyncio.CancelledError:
            with self._artist_thumb_random_peng_requests_lock:
                self._pending_artist_thumb_random_peng_requests.pop(request_id, None)
            raise

    def _complete_artist_thumb_random_peng_request(self, request: dict, result: dict = None, error: Exception = None):
        loop = request.get("loop")
        future = request.get("future")
        if loop is None or future is None:
            return

        def finish():
            if future.done():
                return
            if error is not None:
                future.set_exception(error)
            else:
                future.set_result(result or {})

        loop.call_soon_threadsafe(finish)

    def _do_build_artist_thumb_random_peng_override(self, request_id: str, artist_prompt: str):
        with self._artist_thumb_random_peng_requests_lock:
            request = self._pending_artist_thumb_random_peng_requests.pop(request_id, None)
        if not request:
            return
        try:
            result = self._build_artist_thumb_random_peng_override(artist_prompt)
            self._complete_artist_thumb_random_peng_request(request, result=result)
        except Exception as e:
            self._complete_artist_thumb_random_peng_request(request, error=e)

    def _do_artist_thumb_generate(self, payload: dict):
        try:
            payload = payload if isinstance(payload, dict) else {}
            final_positive = self._artist_thumb_final_prompt(payload)
            if not final_positive:
                self._broadcast_json({
                    "type": "toast",
                    "message": "Artist Thumbnail 프롬프트가 비어 있습니다.",
                    "level": "error",
                })
                return

            negative = payload.get("negative_prompt")
            if negative is None:
                try:
                    negative = self.app_context.main_window.negative_prompt_textedit.toPlainText().strip()
                except Exception:
                    negative = ""

            try:
                width = int(payload.get("width") or 832)
                height = int(payload.get("height") or 1216)
            except Exception:
                width, height = 832, 1216
            use_active_resolution = self._coerce_bool(payload.get("artist_thumb_use_active_resolution"))
            if not use_active_resolution:
                width, height = self._coerce_artist_thumb_resolution(width, height)

            overrides = {
                "input": final_positive,
                "_raw_input": final_positive,
                "negative_prompt": str(negative or ""),
                "width": width,
                "height": height,
                "artist_thumb_request": True,
                "artist_thumb_request_id": str(payload.get("request_id") or uuid.uuid4().hex),
                "_remote_queue_source": "Artist Thumb",
                "_remote_queue_label": str(payload.get("artist") or "").strip(),
            }
            if use_active_resolution:
                for key in (
                    "api_mode",
                    "resolution",
                    "random_resolution",
                    "auto_fit_resolution",
                    "resolution_preset_enabled",
                    "resolution_preset",
                    "enable_hr",
                    "hr_scale",
                    "hr_upscaler",
                    "denoising_strength",
                    "hires_steps",
                    "hr_cfg",
                    "hires_preset_swap",
                    "webui_hiresfix_assist",
                    "webui_hiresfix_assist_target",
                ):
                    if key in payload:
                        overrides[key] = payload.get(key)
                overrides["width"] = width
                overrides["height"] = height
                overrides.setdefault("resolution", f"{width} x {height}")
                overrides["artist_thumb_use_active_resolution"] = True
            else:
                overrides["random_resolution"] = False

            mw = getattr(self.app_context, "main_window", None)
            if not mw:
                raise RuntimeError("main window is not available")
            auto_generate_checkbox = getattr(mw, "generation_checkboxes", {}).get("자동 생성") if mw else None
            auto_generate_was_checked = None

            gc = getattr(mw, "generation_controller", None)
            queue_manager = getattr(self.app_context, "generation_queue_manager", None)
            if not gc or not queue_manager:
                raise RuntimeError("generation controller is not available")
            try:
                if auto_generate_checkbox:
                    auto_generate_was_checked = bool(auto_generate_checkbox.isChecked())
                    if auto_generate_was_checked:
                        auto_generate_checkbox.setChecked(False)

                if gc.is_generating or not queue_manager.is_empty():
                    gc._enqueue_current_request(overrides, priority=0)
                    if not gc.is_generating and not queue_manager.is_paused():
                        QTimer.singleShot(0, gc._process_next_queue_request)
                    self._broadcast_json({"type": "status", "is_generating": bool(gc.is_generating), "message": "queued"})
                    self._broadcast_queue_state()
                    return

                gc.execute_generation_pipeline(overrides=overrides, priority=0)
                self._broadcast_json({"type": "status", "is_generating": True})
                self._broadcast_queue_state()
            finally:
                if (
                    auto_generate_checkbox
                    and auto_generate_was_checked is not None
                    and bool(auto_generate_checkbox.isChecked()) != auto_generate_was_checked
                ):
                    auto_generate_checkbox.setChecked(auto_generate_was_checked)
        except Exception as e:
            print(f"🌐 Remote: Artist Thumb 생성 실패 — {e}")
            self._broadcast_json({
                "type": "toast",
                "message": f"Artist Thumb 생성 실패: {e}",
                "level": "error",
            })

    # --- Character Viewer service / generation ---

    def _character_viewer_state(self) -> dict:
        state = self._character_viewer_service.state()
        state["generation_delay_ms"] = self._character_viewer_generation_delay_ms()
        return state

    def _character_viewer_generation_delay_ms(self) -> int:
        try:
            mw = getattr(self.app_context, "main_window", None)
            module = getattr(mw, "automation_module", None) if mw is not None else None
            delay = module.get_generation_delay() if module is not None else 0
            if delay > 0:
                return int(float(delay) * 1000)
        except Exception:
            pass
        return 500

    def _character_viewer_groups(self, query: str = "") -> dict:
        return self._character_viewer_service.build_groups(query)

    def _character_viewer_list(
        self,
        group: str = "",
        query: str = "",
        page: int = 0,
        per_page: int = 48,
        thumb_first: bool = True,
        include_all: bool = False,
    ) -> dict:
        group_key = str(group or CharacterViewerService.GROUP_ALL)
        return self._character_viewer_service.build_list(
            group_key,
            query,
            page,
            per_page,
            thumb_first,
            include_all,
        )

    def _character_viewer_detail(
        self,
        group: str,
        character: str,
        variant: str = "",
        options: dict | None = None,
    ) -> dict:
        api_mode = self.app_context.get_api_mode() if hasattr(self.app_context, "get_api_mode") else "NAI"
        return self._character_viewer_service.build_detail(
            str(group or ""),
            str(character or ""),
            str(variant or ""),
            options or {},
            api_mode,
        )

    def _character_viewer_prompt(self, payload: dict) -> dict:
        api_mode = self.app_context.get_api_mode() if hasattr(self.app_context, "get_api_mode") else "NAI"
        payload = payload if isinstance(payload, dict) else {}
        return self._character_viewer_service.build_prompt(
            str(payload.get("group") or ""),
            str(payload.get("character") or ""),
            str(payload.get("variant") or ""),
            payload.get("options") if isinstance(payload.get("options"), dict) else payload,
            api_mode,
        )

    def _character_viewer_save_options(self, payload: dict) -> dict:
        return self._character_viewer_service.save_options(payload if isinstance(payload, dict) else {})

    def _character_viewer_thumbnail_payload(
        self,
        group: str,
        character: str,
        variant: str = "",
        size: str = "",
    ) -> tuple[bytes, str]:
        path = self._character_viewer_service.thumbnail_path(
            str(group or ""),
            str(character or ""),
            str(variant or ""),
        )
        size_key = str(size or "").strip().lower()
        if size_key == "grid":
            stat = path.stat()
            cache_key = (str(path), stat.st_mtime_ns, stat.st_size, size_key)
            cached = self._character_viewer_grid_thumb_cache.get(cache_key)
            if cached is not None:
                return cached
            from PIL import Image

            with Image.open(path) as image:
                image.thumbnail((384, 384), Image.Resampling.BILINEAR)
                if image.mode not in ("RGB", "RGBA"):
                    image = image.convert("RGB")
                buf = io.BytesIO()
                image.save(buf, "WEBP", quality=72, method=0)
            payload = (buf.getvalue(), "image/webp")
            if len(self._character_viewer_grid_thumb_cache) > 256:
                self._character_viewer_grid_thumb_cache.clear()
            self._character_viewer_grid_thumb_cache[cache_key] = payload
            return payload
        with open(path, "rb") as handle:
            raw = handle.read()
        if raw.startswith(b"\xff\xd8"):
            media_type = "image/jpeg"
        elif raw.startswith(b"\x89PNG\r\n\x1a\n"):
            media_type = "image/png"
        elif raw.startswith(b"RIFF") and raw[8:12] == b"WEBP":
            media_type = "image/webp"
        else:
            media_type = "application/octet-stream"
        return raw, media_type

    # --- Event Preset service ---

    def _event_preset_status(self) -> dict:
        status = self._event_preset_service.status()
        status["download"] = self._event_preset_download_snapshot()
        return status

    def _event_preset_bootstrap(
        self,
        rating_id: str = "s",
        person_id: str = "1girl_solo",
        search: str = "",
        category_id: str = "",
        subcategory_id: str = "",
        event_id: str = "",
        limit: int | None = None,
    ) -> dict:
        self._set_preset_input_context(
            {"ratingId": rating_id, "personId": person_id},
            "event_bootstrap",
        )
        payload = self._event_preset_service.bootstrap(
            rating_id,
            person_id,
            search,
            category_id,
            subcategory_id,
            event_id,
            limit,
        )
        payload["download"] = self._event_preset_download_snapshot()
        return payload

    def _event_preset_select(self, payload: dict) -> dict:
        payload = payload if isinstance(payload, dict) else {}
        self._set_preset_input_context(payload, "event_select")
        return self._event_preset_service.select(payload)

    def _event_preset_prompt_preview(self, payload: dict) -> dict:
        payload = payload if isinstance(payload, dict) else {}
        self._set_preset_input_context(payload, "event_preview")
        return self._event_preset_service.prompt_preview(payload)

    def _event_preset_generate(self, payload: dict) -> dict:
        payload = payload if isinstance(payload, dict) else {}
        self._set_preset_input_context(payload, "event_generate")
        mw = self.app_context.main_window
        gc = getattr(mw, "generation_controller", None) if mw else None
        if gc is not None and getattr(gc, "is_generating", False):
            raise RuntimeError("이미 생성 중입니다.")
        result = self._event_preset_service.generation_source(payload)
        source_row_data = result.get("sourceRow") or {}
        if not isinstance(source_row_data, dict) or not source_row_data.get("general"):
            raise ValueError("Event Preset prompt source is empty.")
        import pandas as pd
        request_id = str(result.get("requestId") or uuid.uuid4().hex)
        source_row = pd.Series(source_row_data, name=f"event_preset:{request_id}")
        rating = str(source_row_data.get("rating") or "").strip()
        active_ratings = {rating} if rating in {"g", "s", "q", "e"} else set(self._active_ratings)
        request_overrides = payload.get("overrides") if isinstance(payload.get("overrides"), dict) else {}
        overrides = dict(request_overrides)
        overrides.update({
            "event_preset_request": True,
            "event_preset_request_id": request_id,
        })
        self._pending_random_requests.append({
            "ws": None,
            "source_row": source_row,
            "active_ratings": active_ratings,
            "event_preset_request_id": request_id,
            "overrides": overrides,
        })
        self.request_random.emit()
        return {
            "ok": True,
            "status": "generation_requested",
            "requestId": request_id,
            "selected": result.get("selected") or {},
            "promptPreview": result.get("promptPreview") or "",
            "event": result.get("event") or {},
        }

    def _preset_prompt_preview(self, payload: dict) -> dict:
        payload = payload if isinstance(payload, dict) else {}
        context = payload.get("context") if isinstance(payload.get("context"), dict) else payload
        self._set_preset_input_context(context, "preset_preview")
        return self._preset_composer_service.prompt_preview(payload)

    def _preset_generate(self, payload: dict) -> dict:
        payload = payload if isinstance(payload, dict) else {}
        context = payload.get("context") if isinstance(payload.get("context"), dict) else payload
        self._set_preset_input_context(context, "preset_generate")
        mw = self.app_context.main_window
        gc = getattr(mw, "generation_controller", None) if mw else None
        if gc is not None and getattr(gc, "is_generating", False):
            raise RuntimeError("이미 생성 중입니다.")
        result = self._preset_composer_service.generation_source(payload)
        source_row_data = result.get("sourceRow") or {}
        if not isinstance(source_row_data, dict) or not source_row_data.get("general"):
            raise ValueError("Preset prompt source is empty.")
        import pandas as pd
        request_id = str(result.get("requestId") or uuid.uuid4().hex)
        source_name = str(result.get("sourceName") or f"preset:{request_id}")
        source_row = pd.Series(source_row_data, name=source_name)
        rating = str(source_row_data.get("rating") or "").strip()
        active_ratings = {rating} if rating in {"g", "s", "q", "e"} else set(self._active_ratings)
        request_overrides = payload.get("overrides") if isinstance(payload.get("overrides"), dict) else {}
        result_overrides = result.get("overrides") if isinstance(result.get("overrides"), dict) else {}
        overrides = dict(request_overrides)
        overrides.update(result_overrides)
        self._pending_random_requests.append({
            "ws": None,
            "source_row": source_row,
            "active_ratings": active_ratings,
            "remote_preset_request_id": request_id,
            "overrides": overrides,
        })
        self.request_random.emit()
        return {
            "ok": True,
            "status": "generation_requested",
            "requestId": request_id,
            "promptPlan": result.get("promptPlan") or {},
        }

    def _clothes_preset_status(self) -> dict:
        return self._clothes_preset_service.status()

    def _clothes_preset_bootstrap(self, payload: dict) -> dict:
        payload = payload if isinstance(payload, dict) else {}
        self._set_preset_input_context(payload, "clothes_bootstrap")
        return self._clothes_preset_service.bootstrap(payload)

    def _clothes_preset_select(self, payload: dict) -> dict:
        payload = payload if isinstance(payload, dict) else {}
        self._set_preset_input_context(payload, "clothes_select")
        return self._clothes_preset_service.select(payload)

    def _clothes_preset_lucky(self, payload: dict) -> dict:
        payload = payload if isinstance(payload, dict) else {}
        self._set_preset_input_context(payload, "clothes_lucky")
        return self._clothes_preset_service.lucky(payload)

    def _clothes_preset_prompt_fragment(self, payload: dict) -> dict:
        payload = payload if isinstance(payload, dict) else {}
        self._set_preset_input_context(payload, "clothes_fragment")
        return self._clothes_preset_service.prompt_fragment(payload)

    def _expression_preset_status(self) -> dict:
        return self._expression_preset_service.status()

    def _expression_preset_bootstrap(self, payload: dict) -> dict:
        payload = payload if isinstance(payload, dict) else {}
        self._set_preset_input_context(payload, "expression_bootstrap")
        return self._expression_preset_service.bootstrap(payload)

    def _event_preset_thumbnail_payload(
        self,
        event_id: str = "",
        tag: str = "",
        size: str = "",
    ) -> tuple[bytes, str]:
        return self._event_preset_service.thumbnail_payload(
            str(event_id or ""),
            str(tag or ""),
            str(size or ""),
        )

    def _broadcast_character_viewer_error(self, request_id: str, message: str) -> None:
        self._broadcast_json({
            "type": "character_viewer_error",
            "request_id": str(request_id or ""),
            "message": str(message or "Character Viewer generation failed"),
            "level": "error",
        })

    def _do_character_viewer_generate(self, payload: dict):
        try:
            payload = payload if isinstance(payload, dict) else {}
            request_id = str(payload.get("request_id") or "")
            api_mode = self.app_context.get_api_mode() if hasattr(self.app_context, "get_api_mode") else "NAI"
            overrides = self._character_viewer_service.build_generation_overrides(payload, api_mode)
            if "negative_prompt" not in overrides:
                negative = payload.get("negative_prompt")
                if negative is None:
                    try:
                        negative = self.app_context.main_window.negative_prompt_textedit.toPlainText().strip()
                    except Exception:
                        negative = ""
                overrides["negative_prompt"] = str(negative or "")

            mw = getattr(self.app_context, "main_window", None)
            if not mw:
                raise RuntimeError("main window is not available")
            gc = getattr(mw, "generation_controller", None)
            queue_manager = getattr(self.app_context, "generation_queue_manager", None)
            if not gc or not queue_manager:
                raise RuntimeError("generation controller is not available")

            token_key = "nai_token" if api_mode == "NAI" else ("comfyui_url" if api_mode == "COMFYUI" else "webui_url")
            token_manager = getattr(self.app_context, "secure_token_manager", None)
            if token_manager is not None and not token_manager.get_token(token_key):
                self._broadcast_character_viewer_error(request_id, f"{api_mode} 인증 정보가 없습니다.")
                return

            auto_generate_checkbox = getattr(mw, "generation_checkboxes", {}).get("자동 생성") if mw else None
            auto_generate_was_checked = None
            try:
                if auto_generate_checkbox:
                    auto_generate_was_checked = bool(auto_generate_checkbox.isChecked())
                    if auto_generate_was_checked:
                        auto_generate_checkbox.setChecked(False)

                if gc.is_generating or not queue_manager.is_empty():
                    gc._enqueue_current_request(overrides, priority=0)
                    if not gc.is_generating and not queue_manager.is_paused():
                        QTimer.singleShot(0, gc._process_next_queue_request)
                    self._broadcast_json({"type": "status", "is_generating": bool(gc.is_generating), "message": "queued"})
                    self._broadcast_queue_state()
                    return

                gc.execute_generation_pipeline(overrides=overrides, priority=0)
                self._broadcast_json({"type": "status", "is_generating": True})
                self._broadcast_queue_state()
            finally:
                if (
                    auto_generate_checkbox
                    and auto_generate_was_checked is not None
                    and bool(auto_generate_checkbox.isChecked()) != auto_generate_was_checked
                ):
                    auto_generate_checkbox.setChecked(auto_generate_was_checked)
        except Exception as e:
            print(f"🌐 Remote: Character Viewer 생성 실패 — {e}")
            self._broadcast_character_viewer_error(
                str(payload.get("request_id") or "") if isinstance(payload, dict) else "",
                f"Character Viewer 생성 실패: {e}",
            )
            self._broadcast_json({
                "type": "toast",
                "message": f"Character Viewer 생성 실패: {e}",
                "level": "error",
            })

    def _clear_comfyui_random_request(self, request_id: str):
        cf_id = str(request_id or "")
        if not cf_id:
            return None
        override_key = ("comfyui", cf_id)
        cf_pending = self._pending_overrides.pop(override_key, None)
        if isinstance(cf_pending, dict):
            peng_ref = cf_pending.get("_peng_override_ref")
            if peng_ref is not None and self.app_context.session_p_eng_override is peng_ref:
                self.app_context.session_p_eng_override = None
        with self._comfyui_requests_lock:
            return self._pending_comfyui_requests.pop(cf_id, None)

    def _fail_comfyui_random_request(self, request_id: str, message: str):
        future = self._clear_comfyui_random_request(request_id)
        if future is None or self._loop is None:
            return
        self._loop.call_soon_threadsafe(
            lambda f=future, m=message: (
                f.set_exception(RuntimeError(m)) if not f.done() else None
            )
        )

    def _img2img_manager(self):
        main_window = getattr(self.app_context, "main_window", None)
        if not main_window:
            return None
        return getattr(main_window, "img2img_window_manager", None)

    def _get_remote_img2img_window(self):
        manager = self._img2img_manager()
        window_id = self._remote_img2img_window_id
        if not manager or not window_id:
            return None
        return getattr(manager, "windows", {}).get(window_id)

    def _close_remote_img2img_session(self):
        manager = self._img2img_manager()
        window_id = self._remote_img2img_window_id
        self._remote_img2img_window_id = None
        self._remote_img2img_source_label = ""
        if manager and window_id:
            close_window = getattr(manager, "close_window", None)
            if callable(close_window):
                close_window(window_id)

    def _pil_preview_payload(self, pil_image, max_side: int = 640) -> tuple[str, int, int]:
        if pil_image is None:
            return "", 0, 0
        try:
            from PIL import Image

            thumb = pil_image.copy()
            thumb.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
            if thumb.mode not in ("RGB", "RGBA"):
                thumb = thumb.convert("RGBA")
            buffer = io.BytesIO()
            thumb.save(buffer, format="PNG", optimize=True)
            encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
            return f"data:image/png;base64,{encoded}", int(thumb.width), int(thumb.height)
        except Exception as exc:
            print(f"🌐 Remote: img2img preview encode failed — {exc}")
            return "", 0, 0

    def _pil_preview_data_url(self, pil_image, max_side: int = 640) -> str:
        return self._pil_preview_payload(pil_image, max_side=max_side)[0]

    def _mask_preview_data_url(self, mask_image, size: tuple[int, int]) -> str:
        if mask_image is None or not size[0] or not size[1]:
            return ""
        try:
            from PIL import Image

            mask = mask_image.convert("L").resize(size, Image.Resampling.NEAREST)
            buffer = io.BytesIO()
            mask.save(buffer, format="PNG", optimize=True)
            encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
            return f"data:image/png;base64,{encoded}"
        except Exception as exc:
            print(f"🌐 Remote: inpaint mask preview encode failed — {exc}")
            return ""

    def _remote_img2img_strength_float(self, raw_value: int) -> float:
        return 1.0 if int(raw_value) == 99 else int(raw_value) / 100.0

    def _read_img2img(self) -> dict:
        window = self._get_remote_img2img_window()
        if not window:
            return {
                "type": "module_state",
                "module_id": "img2img",
                "active": False,
            }

        pil_image = getattr(window, "pil_image", None)
        strength_raw = int(window.strength_slider.value())
        noise_raw = int(window.noise_slider.value())
        preview, preview_width, preview_height = self._pil_preview_payload(pil_image)
        image_width = int(getattr(pil_image, "width", 0) or 0)
        image_height = int(getattr(pil_image, "height", 0) or 0)
        mode = str(getattr(window, "mode", "img2img") or "img2img")
        has_mask = bool(getattr(window, "full_mask_pil", None) or getattr(window, "small_mask_pil", None))
        characters = []
        for index, row in enumerate(getattr(window, "character_rows", []) or []):
            characters.append({
                "id": index + 1,
                "active": bool(row["active_checkbox"].isChecked()),
                "prompt": row["prompt_edit"].toPlainText(),
                "uc": row["uc_edit"].toPlainText(),
            })

        return {
            "type": "module_state",
            "module_id": "img2img",
            "active": True,
            "window_id": int(getattr(window, "window_id", 0) or 0),
            "mode": mode,
            "source_label": self._remote_img2img_source_label,
            "width": image_width,
            "height": image_height,
            "preview": preview,
            "preview_width": preview_width,
            "preview_height": preview_height,
            "has_mask": has_mask,
            "mask_preview": self._mask_preview_data_url(
                getattr(window, "full_mask_pil", None) or getattr(window, "small_mask_pil", None),
                (image_width, image_height),
            ),
            "strength": strength_raw,
            "strength_value": self._remote_img2img_strength_float(strength_raw),
            "noise": noise_raw,
            "noise_value": noise_raw / 100.0,
            "repeat": int(window.repeat_spin.value()),
            "main_prompt": window.main_prompt_edit.toPlainText(),
            "negative_prompt": window.negative_prompt_edit.toPlainText(),
            "characters": characters,
            "requires_mask": mode == "inpaint" and not has_mask,
            "can_generate": bool(pil_image) and (mode != "inpaint" or has_mask),
        }

    def _broadcast_img2img_state(self):
        self._broadcast_json(self._read_img2img())

    def _reuse_remote_img2img_window(self, window, pil_image, manager, history_item=None,
                                     mode: str = "img2img", mask_data=None):
        """Reconfigure the hidden remote Img2Img window without rebuilding its Qt widget tree."""
        main_window = getattr(self.app_context, "main_window", None)

        previous_mode = str(getattr(window, "mode", "img2img") or "img2img")
        try:
            manager._last_strength_by_mode[previous_mode] = window.strength_slider.value()
            manager._last_noise_by_mode[previous_mode] = window.noise_slider.value()
        except Exception:
            pass

        window.set_image(pil_image, mode, mask_data, None)
        if hasattr(window, "_create_character_rows"):
            window._create_character_rows([])
        if hasattr(window, "main_prompt_edit"):
            window.main_prompt_edit.clear()
        if hasattr(window, "negative_prompt_edit"):
            window.negative_prompt_edit.clear()

        if (history_item and (
                getattr(history_item, 'prompt_context', None) or
                getattr(history_item, 'generation_params', None))):
            window.initialize_from_history_item(history_item)
        elif main_window and hasattr(window, "initialize_from_main_ui"):
            window.initialize_from_main_ui(main_window)

        active_mode = str(getattr(window, "mode", "img2img") or "img2img")
        try:
            window.strength_slider.setValue(manager._last_strength_by_mode.get(active_mode, 70))
            window.noise_slider.setValue(manager._last_noise_by_mode.get(active_mode, 0))
            window.repeat_spin.setValue(1)
        except Exception:
            pass
        restore_button = getattr(window, "_restore_button", None)
        if callable(restore_button):
            restore_button()
        return window

    def _open_remote_img2img_session(self, pil_image, history_item=None, source_label: str = "",
                                     mode: str = "img2img", mask_data=None):
        manager = self._img2img_manager()
        if not manager:
            raise RuntimeError("Img2Img manager is not ready")
        if pil_image is None:
            raise RuntimeError("Img2Img source image is unavailable")
        mode = "inpaint" if str(mode or "").strip().lower() == "inpaint" else "img2img"

        window = self._get_remote_img2img_window()
        if window:
            window = self._reuse_remote_img2img_window(
                window=window,
                pil_image=pil_image,
                manager=manager,
                history_item=history_item,
                mode=mode,
                mask_data=mask_data,
            )
        else:
            self._close_remote_img2img_session()
            window = manager.create_window(
                pil_image=pil_image,
                mode=mode,
                mask_data=mask_data,
                history_item=history_item,
                visible=False,
            )
        self._remote_img2img_window_id = int(getattr(window, "window_id", 0) or 0)
        self._remote_img2img_source_label = str(source_label or "Result Image")
        self._broadcast_img2img_state()
        label = "Inpaint" if mode == "inpaint" else "Img2Img"
        self._broadcast_json({
            "type": "toast",
            "message": f"{label} session ready",
            "level": "success",
        })

    def _open_desktop_img2img_surface(self, pil_image, history_item=None, source_label: str = "",
                                      mode: str = "img2img"):
        """Open the native PyQt img2img/inpaint surface; Web Shell only requests it."""
        allowed, reason = self._nai_img2img_mode_gate()
        if not allowed:
            raise RuntimeError(reason)
        manager = self._img2img_manager()
        if not manager:
            raise RuntimeError("Img2Img manager is not ready")
        if pil_image is None:
            raise RuntimeError("Img2Img source image is unavailable")

        self._close_remote_img2img_session()
        mode = "inpaint" if str(mode or "").strip().lower() == "inpaint" else "img2img"

        if mode == "inpaint":
            window = manager.create_inpaint_from_editor(
                pil_image,
                history_item=history_item,
                parent=getattr(self.app_context, "main_window", None),
            )
            label = "Inpaint"
        else:
            window = manager.create_window(
                pil_image=pil_image,
                mode="img2img",
                history_item=history_item,
                visible=True,
            )
            label = "Img2Img"

        if not window:
            self._broadcast_json({
                "type": "toast",
                "message": f"{label} request cancelled",
                "level": "info",
            })
            return

        self._broadcast_json({
            "type": "toast",
            "message": f"{label} opened on desktop",
            "level": "success",
        })

    def _resolve_result_image_action_source(self, payload: dict, action_label: str = "Img2Img") -> tuple[object, object, str]:
        from PIL import Image

        item = self._get_result_context_history_item(payload)
        item_image = getattr(item, "image", None) if item else None
        label = str(payload.get("label") or payload.get("path") or "Result Image")
        if item_image is not None:
            return item_image.copy(), item, label

        rel_path = str(payload.get("path") or "").strip()
        if rel_path:
            raise RuntimeError(f"Saved {action_label} requires an in-memory history item")

        source = str(payload.get("source") or "").strip().lower()
        if source == "current" and self.latest_webp:
            with Image.open(io.BytesIO(self.latest_webp)) as opened:
                return opened.convert("RGBA").copy(), None, "Current Result"

        raise RuntimeError("Img2Img source is unavailable")

    def _do_result_image_action(self, payload_json: str = "{}"):
        try:
            payload = json.loads(payload_json or "{}")
            if not isinstance(payload, dict):
                payload = {}
            action = str(payload.get("action") or "").strip().lower()
            if action not in {"img2img", "inpaint"}:
                self._broadcast_json({"type": "toast", "message": "Unsupported result image action", "level": "error"})
                return
            allowed, reason = self._nai_img2img_mode_gate()
            if not allowed:
                self._broadcast_json({"type": "toast", "message": reason, "level": "error"})
                return
            action_label = "Inpaint" if action == "inpaint" else "Img2Img"
            pil_image, history_item, label = self._resolve_result_image_action_source(payload, action_label)
            self._open_desktop_img2img_surface(
                pil_image=pil_image,
                history_item=history_item,
                mode=action,
                source_label=label,
            )
            print(f"🌐 Remote: result {action} desktop surface opened — {label}")
        except Exception as e:
            message = f"Image action failed: {e}"
            self._broadcast_json({"type": "toast", "message": message, "level": "error"})
            print(f"🌐 Remote: result image action failed — {e}")

    def _decode_remote_inpaint_mask(self, value: str, target_size: tuple[int, int]):
        from PIL import Image

        text = str(value or "").strip()
        if "," in text and text.lower().startswith("data:"):
            text = text.split(",", 1)[1]
        if not text:
            return None, None, 0, 0

        mask_bytes = base64.b64decode(text)
        with Image.open(io.BytesIO(mask_bytes)) as opened:
            full_mask = opened.convert("L")

        if full_mask.size != target_size:
            full_mask = full_mask.resize(target_size, Image.Resampling.NEAREST)

        threshold_table = [0 if i <= 127 else 255 for i in range(256)]
        full_mask = full_mask.point(threshold_table, "L")
        white_pixels = int(full_mask.histogram()[255])
        if white_pixels <= 0:
            return None, None, 0, 0

        small_size = (max(1, target_size[0] // 8), max(1, target_size[1] // 8))
        small_mask = full_mask.resize(small_size, Image.Resampling.NEAREST).point(threshold_table, "L")
        painted_blocks = int(small_mask.histogram()[255])
        if painted_blocks < 8:
            return None, None, white_pixels, painted_blocks
        return full_mask, small_mask, white_pixels, painted_blocks

    def _set_img2img(self, key: str, value: str):
        key = str(key or "")
        try:
            if key == "close":
                self._close_remote_img2img_session()
                self._broadcast_img2img_state()
                return

            window = self._get_remote_img2img_window()
            if not window:
                self._broadcast_json({"type": "toast", "message": "No active Img2Img session", "level": "error"})
                return

            should_broadcast = False
            if key == "main_prompt":
                window.main_prompt_edit.setPlainText(value)
            elif key == "negative_prompt":
                window.negative_prompt_edit.setPlainText(value)
            elif key == "strength":
                window.strength_slider.setValue(max(1, min(99, int(float(value)))))
            elif key == "noise":
                window.noise_slider.setValue(max(0, min(99, int(float(value)))))
            elif key == "repeat":
                window.repeat_spin.setValue(max(1, min(99, int(float(value)))))
            elif key == "mask_png":
                target = getattr(window, "pil_image", None)
                if not target:
                    raise RuntimeError("Inpaint source image is unavailable")
                full_mask, small_mask, white_pixels, painted_blocks = self._decode_remote_inpaint_mask(
                    value,
                    (int(target.width), int(target.height)),
                )
                if not full_mask or not small_mask:
                    if white_pixels > 0:
                        raise RuntimeError("Inpaint mask is too small")
                    raise RuntimeError("Inpaint mask is empty")
                window.mode = "inpaint"
                window.full_mask_pil = full_mask
                window.small_mask_pil = small_mask
                window._outpaint_data = None
                if hasattr(window, "_update_preview"):
                    window._update_preview()
                if hasattr(window, "_update_title"):
                    window._update_title()
                print(f"🌐 Remote: inpaint mask applied ({white_pixels} px, {painted_blocks} blocks)")
                should_broadcast = True
            elif key == "clear_mask":
                if str(getattr(window, "mode", "")).lower() == "inpaint":
                    window.full_mask_pil = None
                    window.small_mask_pil = None
                    window._outpaint_data = None
                    if hasattr(window, "_update_preview"):
                        window._update_preview()
                    should_broadcast = True
            elif key == "add_character":
                window._add_character_row()
                should_broadcast = True
            elif key.startswith("remove_character_"):
                index = int(key.rsplit("_", 1)[-1])
                rows = getattr(window, "character_rows", []) or []
                if 0 <= index < len(rows):
                    window._remove_character_row(rows[index])
                    should_broadcast = True
            elif key.startswith("char_active_"):
                index = int(key.rsplit("_", 1)[-1])
                rows = getattr(window, "character_rows", []) or []
                if 0 <= index < len(rows):
                    rows[index]["active_checkbox"].setChecked(self._coerce_bool(value))
            elif key.startswith("char_prompt_"):
                index = int(key.rsplit("_", 1)[-1])
                rows = getattr(window, "character_rows", []) or []
                if 0 <= index < len(rows):
                    rows[index]["prompt_edit"].setPlainText(value)
            elif key.startswith("char_uc_"):
                index = int(key.rsplit("_", 1)[-1])
                rows = getattr(window, "character_rows", []) or []
                if 0 <= index < len(rows):
                    rows[index]["uc_edit"].setPlainText(value)
            elif key == "generate":
                params = window._collect_generation_params()
                repeat_count = int(window.repeat_spin.value())
                if repeat_count > 1:
                    params["img2img_batch_request"] = True
                    params["img2img_batch_total"] = repeat_count
                params["img2img_batch_window_id"] = int(getattr(window, "window_id", 0) or 0)
                main_window = getattr(self.app_context, "main_window", None)
                if not main_window or not hasattr(main_window, "on_img2img_window_generate"):
                    raise RuntimeError("Generation controller is not ready")
                main_window.on_img2img_window_generate(params["img2img_batch_window_id"], params)
                label = "Inpaint" if str(getattr(window, "mode", "")).lower() == "inpaint" else "Img2Img"
                self._broadcast_json({"type": "toast", "message": f"{label} generation requested", "level": "success"})
                should_broadcast = True
            else:
                return

            if should_broadcast:
                self._broadcast_img2img_state()
        except Exception as e:
            print(f"🌐 Remote: img2img 설정 실패 — {key}={value}: {e}")
            self._broadcast_json({"type": "toast", "message": f"Img2Img update failed: {e}", "level": "error"})

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
        if isinstance(source_row, dict):
            prompt_source_keys = {
                "general",
                "character",
                "copyright",
                "artist",
                "meta",
                "rating",
                "image_width",
                "image_height",
            }
            return bool(source_row) and any(key in source_row for key in prompt_source_keys)
        try:
            return not bool(source_row.empty)
        except Exception:
            return True

    def _mark_result_reroll_prompt_pending(self):
        request_id = uuid.uuid4().hex
        self._pending_overrides[("result_reroll", request_id)] = {
            "source": "result_reroll",
        }
        return request_id

    def _get_current_result_source_row(self):
        image_window = self._get_image_window_widget()
        item = getattr(image_window, "current_history_item", None) if image_window else None
        source_row = getattr(item, "source_row", None) if item else None
        if not self._source_row_available(source_row):
            return None
        try:
            return source_row.copy()
        except Exception:
            return source_row

    def _get_result_context_source_row(self, payload: dict | None = None):
        payload = payload if isinstance(payload, dict) else {}
        source = str(payload.get("source") or "").strip().lower()
        rel_path = str(payload.get("path") or "").strip()
        file_path = str(payload.get("file_path") or payload.get("filePath") or "").strip()

        if rel_path and source != "current":
            item = self._find_history_item_by_path(rel_path=rel_path, file_path=file_path)
            source_row = getattr(item, "source_row", None) if item else None
            if not self._source_row_available(source_row):
                return None
            try:
                return source_row.copy()
            except Exception:
                return source_row

        return self._get_current_result_source_row()

    def _get_result_context_history_item(self, payload: dict | None = None):
        payload = payload if isinstance(payload, dict) else {}
        source = str(payload.get("source") or "").strip().lower()
        rel_path = str(payload.get("path") or "").strip()
        file_path = str(payload.get("file_path") or payload.get("filePath") or "").strip()
        if rel_path and source != "current":
            return self._find_history_item_by_path(rel_path=rel_path, file_path=file_path)
        image_window = self._get_image_window_widget()
        return getattr(image_window, "current_history_item", None) if image_window else None

    def _get_result_history_action_item(self, payload: dict | None = None):
        payload = payload if isinstance(payload, dict) else {}
        rel_path = str(payload.get("path") or "").strip()
        file_path = str(payload.get("file_path") or payload.get("filePath") or "").strip()
        if rel_path or file_path:
            return self._find_history_item_by_path(rel_path=rel_path, file_path=file_path)
        image_window = self._get_image_window_widget()
        return getattr(image_window, "current_history_item", None) if image_window else None

    def _result_context_generation_params(self, payload: dict | None = None) -> dict:
        item = self._get_result_context_history_item(payload)
        params = getattr(item, "generation_params", None) if item else None
        if isinstance(params, dict) and params:
            return params.copy()

        payload = payload if isinstance(payload, dict) else {}
        source = str(payload.get("source") or "").strip().lower()
        if source == "current" and isinstance(self.latest_metadata_payload, dict):
            raw = self.latest_metadata_payload.get("raw", {})
            if isinstance(raw, dict) and isinstance(raw.get("generation_params"), dict):
                return raw["generation_params"].copy()
        return {}

    def _result_queue_mode(self, payload: dict | None = None) -> str:
        payload = payload if isinstance(payload, dict) else {}
        mode = str(payload.get("queue_mode") or payload.get("queueMode") or "").strip().lower()
        if not mode and (payload.get("use_current_ui") or payload.get("useCurrentUi")):
            mode = "reopen"
        if mode not in {"original", "reopen", "current_character"}:
            mode = "original"
        return mode

    def _collect_prompt_reopen_settings(self) -> dict:
        mw = self.app_context.main_window
        comfyui_sampling_mode = "eps"
        if hasattr(mw, "anima_radio") and mw.anima_radio.isChecked():
            comfyui_sampling_mode = "anima"
        elif hasattr(mw, "v_pred_radio") and mw.v_pred_radio.isChecked():
            comfyui_sampling_mode = "v_prediction"
        elif hasattr(mw, "eps_radio") and mw.eps_radio.isChecked():
            comfyui_sampling_mode = "eps"

        return {
            "prompt_fixed": False,
            "auto_generate": False,
            "turbo_mode": bool(mw.generation_checkboxes.get("터보 옵션") and mw.generation_checkboxes["터보 옵션"].isChecked()),
            "wildcard_standalone": False,
            "auto_fit_resolution": bool(getattr(mw, "auto_fit_resolution_checkbox", None) and mw.auto_fit_resolution_checkbox.isChecked()),
            "api_mode": self.app_context.get_api_mode(),
            "comfyui_sampling_mode": comfyui_sampling_mode,
        }

    def _apply_current_character_params(self, params: dict) -> dict:
        char_module = self.app_context.middle_section_controller.get_module_instance("CharacterModule")
        if char_module and hasattr(char_module, "activate_checkbox") and char_module.activate_checkbox.isChecked():
            char_params = char_module.get_parameters()
            if char_params and char_params.get("characters"):
                params["characters"] = char_params["characters"]
                params["uc"] = char_params["uc"]
                params["character_positions"] = char_params.get("character_positions", [])
                return params

        params.pop("characters", None)
        params.pop("uc", None)
        params.pop("character_positions", None)
        return params

    def _do_result_reroll(self, payload_json: str = "{}"):
        """데스크탑 ImageWindow의 '프롬프트 다시개봉' 구현체를 Remote Web에서 재사용."""
        try:
            payload = json.loads(payload_json) if payload_json else {}
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}

        image_window = self._get_image_window_widget()
        if not image_window:
            self._broadcast_json({"type": "toast", "message": "ImageWindow is not ready", "level": "error"})
            return

        source = str(payload.get("source") or "").strip().lower()
        rel_path = str(payload.get("path") or "").strip()
        if rel_path and source != "current":
            source_row = self._get_result_context_source_row(payload)
            if not self._source_row_available(source_row):
                self._broadcast_json({"type": "toast", "message": "Reroll source is unavailable", "level": "error"})
                return
            self._mark_result_reroll_prompt_pending()
            image_window.instant_generation_requested.emit(source_row)
            print("🌐 Remote: saved result 프롬프트 다시개봉 실행")
            return

        reroll_current_prompt = getattr(image_window, "_reroll_current_prompt", None)
        if callable(reroll_current_prompt):
            item = getattr(image_window, "current_history_item", None)
            source_row = getattr(item, "source_row", None) if item else None
            if not self._source_row_available(source_row):
                self._broadcast_json({"type": "toast", "message": "Reroll source is unavailable", "level": "error"})
                return
            self._mark_result_reroll_prompt_pending()
            reroll_current_prompt()
            print("🌐 Remote: desktop 프롬프트 다시개봉 실행")
            return

        item = getattr(image_window, "current_history_item", None)
        source_row = getattr(item, "source_row", None) if item else None
        if not self._source_row_available(source_row):
            self._broadcast_json({"type": "toast", "message": "Reroll source is unavailable", "level": "error"})
            return
        self._mark_result_reroll_prompt_pending()
        image_window.instant_generation_requested.emit(source_row)
        print("🌐 Remote: desktop 프롬프트 다시개봉 fallback 실행")

    def _do_result_queue(self, payload_json: str = "{}"):
        """Result 컨텍스트 메뉴에서 현재/저장 결과를 생성 큐에 추가."""
        try:
            payload = json.loads(payload_json) if payload_json else {}
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}

        try:
            from core.generation_request import GenerationRequest
            import pandas as pd

            params = self._result_context_generation_params(payload)
            if not params:
                self._broadcast_json({"type": "toast", "message": "Queue source params are unavailable", "level": "error"})
                self._broadcast_queue_state()
                return

            priority = 100 if str(payload.get("position") or "back").lower() == "front" else 0
            queue_mode = self._result_queue_mode(payload)
            source = str(payload.get("source") or "").strip() or "result"
            label = str(payload.get("label") or payload.get("path") or source or "result").strip()
            item = self._get_result_context_history_item(payload)
            source_row = getattr(item, "source_row", None) if item else None

            if queue_mode == "reopen":
                if not self._source_row_available(source_row):
                    self._broadcast_json({"type": "toast", "message": "P.Eng / WC source row is unavailable", "level": "error"})
                    self._broadcast_queue_state()
                    return
                settings = self._collect_prompt_reopen_settings()
                prompt = self.app_context.main_window.prompt_gen_controller.generate_instant_source_silent(source_row, settings)
                if not prompt:
                    self._broadcast_json({"type": "toast", "message": "P.Eng / WC reopen failed", "level": "error"})
                    self._broadcast_queue_state()
                    return
                params["input"] = prompt
                params["_raw_input"] = prompt
            elif queue_mode == "current_character":
                if self._current_api_mode() != "NAI":
                    self._broadcast_json({"type": "toast", "message": "Current character queue is only available in NAI mode", "level": "error"})
                    self._broadcast_queue_state()
                    return
                params = self._apply_current_character_params(params)

            main_window = self.app_context.main_window
            if hasattr(main_window, "random_resolution_checkbox") and main_window.random_resolution_checkbox:
                if main_window.random_resolution_checkbox.isChecked():
                    random_index = random.randint(0, main_window.resolution_combo.count() - 1)
                    selected_value = main_window.resolution_combo.itemText(random_index)
                    width, height = map(int, selected_value.split(" x "))
                    params["width"] = width
                    params["height"] = height

            if hasattr(main_window, "seed_fix_checkbox") and main_window.seed_fix_checkbox:
                if not main_window.seed_fix_checkbox.isChecked():
                    random_seed = random.randint(0, 9999999999)
                    params["seed"] = random_seed
                    params["extra_noise_seed"] = random_seed

            params.pop("_generation_request", None)
            source_labels = {
                "original": source,
                "reopen": "P.Eng / WC",
                "current_character": "Current Character",
            }
            params["_remote_queue_source"] = source_labels.get(queue_mode, source)
            params["_remote_queue_label"] = label

            if source_row is None:
                source_row = pd.Series()

            request = GenerationRequest(params=params, source_row=source_row, priority=priority, max_retries=0)
            queue_manager = self.app_context.generation_queue_manager
            if priority > 0:
                queue_manager.enqueue_with_priority(request)
            else:
                queue_manager.enqueue_request(request)

            gc = self.app_context.main_window.generation_controller
            if not gc.is_generating and not queue_manager.is_paused():
                QTimer.singleShot(0, gc._process_next_queue_request)

            position_label = "front" if priority > 0 else "back"
            self._broadcast_json({"type": "toast", "message": f"Queued result to {position_label}", "level": "success"})
            self._broadcast_queue_state()
        except Exception as e:
            print(f"🌐 Remote: result queue failed — {e}")
            self._broadcast_json({"type": "toast", "message": f"Queue result failed: {e}", "level": "error"})
            self._broadcast_queue_state()

    async def _request_result_history_action(self, action: str, payload: dict | None = None, timeout: float = 8.0) -> dict:
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        request_id = uuid.uuid4().hex
        with self._result_history_actions_lock:
            self._pending_result_history_actions[request_id] = {
                "loop": loop,
                "future": future,
                "action": action,
                "payload": payload if isinstance(payload, dict) else {},
            }
        self.request_result_history_action.emit(request_id)
        try:
            result = await asyncio.wait_for(future, timeout=timeout)
            return result if isinstance(result, dict) else {"ok": False, "error": "Invalid result action response"}
        finally:
            with self._result_history_actions_lock:
                self._pending_result_history_actions.pop(request_id, None)

    def _complete_result_history_action(self, request: dict, result: dict):
        loop = request.get("loop")
        future = request.get("future")
        if loop is None or future is None:
            return
        loop.call_soon_threadsafe(
            lambda f=future, r=result: (f.set_result(r) if not f.done() else None)
        )

    def _unsaved_history_items(self) -> list:
        return [
            item
            for item in (self._iter_memory_history_items() or ())
            if item is not None
            and getattr(item, "image", None) is not None
            and not self._history_item_file_path(item)
        ]

    def _unsaved_history_count(self) -> int:
        return len(self._unsaved_history_items())

    def _save_history_item_to_file(self, item, image_window=None) -> dict:
        if not item or not getattr(item, "image", None):
            return {"ok": False, "error": "History image is unavailable"}

        existing_path = self._history_item_file_path(item)
        if existing_path:
            return {
                "ok": True,
                "already_saved": True,
                "path": self._history_item_path_key(item),
                "file_path": str(existing_path),
                "asset": self._build_saved_result_asset_payload(self._history_item_path_key(item)),
            }

        image_window = image_window or self._get_image_window_widget()
        if image_window is None:
            return {"ok": False, "error": "Image window is unavailable"}

        raw_bytes = getattr(item, "raw_bytes", None)
        if not raw_bytes:
            try:
                raw_bytes, _media_type = self._history_item_image_payload(item)
            except Exception as e:
                return {"ok": False, "error": f"Image bytes are unavailable: {e}"}

        image_crud = getattr(image_window, "image_crud", None) or getattr(self.app_context, "image_crud_controller", None)
        if image_crud is None or not hasattr(image_crud, "save_image"):
            return {"ok": False, "error": "Image save controller is unavailable"}

        try:
            save_as_webp_checkbox = self._get_save_as_webp_checkbox()
            is_webp = bool(save_as_webp_checkbox and save_as_webp_checkbox.isChecked())
            create_info = getattr(image_window, "_create_classification_info", None)
            classification_source = getattr(self.app_context, "image_crud_controller", None) or image_crud
            classification_info = create_info(item) if callable(create_info) else {
                "method": getattr(classification_source, "get_classification_method", lambda: "none")(),
                "prompt": str(getattr(item, "info_text", "") or ""),
                "image_size": getattr(getattr(item, "image", None), "size", (0, 0)),
                "tags": [],
                "backend_type": str(getattr(item, "backend_type", "NAI") or "NAI"),
            }
            success, filepath, error = image_crud.save_image(
                image_bytes=bytes(raw_bytes),
                as_webp=is_webp,
                classification_info=classification_info,
            )
        except Exception as e:
            return {"ok": False, "error": f"Image save failed: {e}"}

        if not success:
            return {"ok": False, "error": error or "Image save failed"}

        try:
            item.filepath = filepath
        except Exception:
            pass

        return {
            "ok": True,
            "saved": True,
            "path": self._history_item_path_key(item),
            "file_path": str(filepath or ""),
            "asset": self._build_saved_result_asset_payload(self._history_item_path_key(item)),
        }

    def _save_result_history_item(self, payload: dict) -> dict:
        image_window = self._get_image_window_widget()
        if image_window is None:
            return {"ok": False, "error": "Image window is unavailable"}
        item = self._get_result_history_action_item(payload)
        result = self._save_history_item_to_file(item, image_window=image_window)
        if not result.get("ok"):
            return result
        if result.get("already_saved"):
            return result

        if hasattr(self.app_context, "main_window") and hasattr(self.app_context.main_window, "status_bar"):
            try:
                self.app_context.main_window.status_bar.showMessage(f"✅ 이미지 저장 완료: {Path(result.get('file_path') or '').name}", 3000)
            except Exception:
                pass

        payload = self._history_item_summary(item)
        payload.update({"type": "viewer_new_image", "total": self._history_count()})
        self._broadcast_json(payload)
        self._broadcast_auto_save_settings()
        return result

    def _save_all_unsaved_history_items(self) -> dict:
        image_window = self._get_image_window_widget()
        if image_window is None:
            return {"ok": False, "error": "Image window is unavailable"}
        items = self._unsaved_history_items()
        saved = 0
        failures = []
        for item in list(items):
            result = self._save_history_item_to_file(item, image_window=image_window)
            if result.get("ok") and not result.get("already_saved"):
                saved += 1
                payload = self._history_item_summary(item)
                payload.update({"type": "viewer_new_image", "total": self._history_count()})
                self._broadcast_json(payload)
            elif not result.get("ok"):
                failures.append({
                    "path": self._history_item_path_key(item),
                    "error": result.get("error") or "Image save failed",
                })
        remaining = self._unsaved_history_count()
        if hasattr(self.app_context, "main_window") and hasattr(self.app_context.main_window, "status_bar"):
            try:
                self.app_context.main_window.status_bar.showMessage(f"✅ 미저장 히스토리 {saved}장 일괄 저장 완료", 3000)
            except Exception:
                pass
        self._broadcast_auto_save_settings()
        return {
            "ok": not failures,
            "saved": saved,
            "requested": len(items),
            "remaining": remaining,
            "failures": failures,
        }

    def _collect_unsaved_history_download_entries(self) -> dict:
        entries = []
        for item in self._unsaved_history_items():
            try:
                image_bytes, media_type = self._history_item_image_payload(item)
            except Exception as e:
                return {"ok": False, "error": f"Image bytes are unavailable: {e}"}
            entries.append({
                "filename": self._history_item_filename(item),
                "bytes": bytes(image_bytes),
                "media_type": media_type,
            })
        return {
            "ok": True,
            "count": len(entries),
            "entries": entries,
        }

    def _delete_result_history_item(self, payload: dict) -> dict:
        image_window = self._get_image_window_widget()
        if image_window is None:
            return {"ok": False, "error": "Image window is unavailable"}
        history_window = getattr(image_window, "image_history_window", None)
        if history_window is None:
            return {"ok": False, "error": "History window is unavailable"}
        item = self._get_result_history_action_item(payload)
        if not item:
            return {"ok": False, "error": "History item is unavailable"}
        if self._history_item_file_path(item):
            return {"ok": False, "error": "Only unsaved history images can be deleted from this action"}

        rel_path = self._history_item_path_key(item)
        for widget in list(getattr(history_window, "history_widgets", []) or []):
            if getattr(widget, "history_item", None) is item:
                history_window.on_item_delete_requested(widget)
                return {
                    "ok": True,
                    "deleted": True,
                    "path": rel_path,
                    "history_id": self._ensure_history_id(item),
                    "total": self._history_count(),
                }
        return {"ok": False, "error": "History item is not in the visible history queue"}

    def _do_result_history_action(self, request_id: str):
        with self._result_history_actions_lock:
            request = self._pending_result_history_actions.pop(request_id, None)
        if not request:
            return

        action = str(request.get("action") or "").strip().lower()
        payload = request.get("payload") if isinstance(request.get("payload"), dict) else {}
        try:
            if action == "save":
                result = self._save_result_history_item(payload)
            elif action == "delete":
                result = self._delete_result_history_item(payload)
            elif action == "save_all_unsaved":
                result = self._save_all_unsaved_history_items()
            elif action == "collect_unsaved_download":
                result = self._collect_unsaved_history_download_entries()
            else:
                result = {"ok": False, "error": "Unsupported result history action"}
        except Exception as e:
            result = {"ok": False, "error": f"Result history action failed: {e}"}
        self._complete_result_history_action(request, result)

    def _open_path_location(self, target: Path):
        import subprocess
        import sys

        path = Path(target)
        if sys.platform.startswith("win"):
            subprocess.Popen(["explorer", f"/select,{str(path)}"])
        elif sys.platform.startswith("darwin"):
            subprocess.Popen(["open", "-R", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path.parent)])

    def _result_png_filename(self, source_name: str = "") -> str:
        raw_name = Path(str(source_name or "")).name
        raw_name = re.sub(r'[<>:"/\\|?*\x00-\x1F]', "_", raw_name).strip()
        stem = Path(raw_name).stem if raw_name else ""
        return f"{stem or 'naia-result'}.png"

    def _download_content_disposition(self, filename: str) -> str:
        ascii_name = re.sub(r"[^A-Za-z0-9._ -]+", "_", filename).strip(" ._")
        ascii_name = ascii_name or "naia-result.png"
        return f'attachment; filename="{ascii_name}"; filename*=UTF-8\'\'{quote(filename)}'

    def _image_media_type_for_path(self, image_path: 'Path') -> str:
        ext = Path(image_path).suffix.lower()
        return {
            ".webp": "image/webp",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
            ".bmp": "image/bmp",
        }.get(ext, "image/png")

    def _image_media_type_for_bytes(self, image_bytes: bytes) -> str:
        if image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
            return "image/png"
        if image_bytes.startswith(b"\xff\xd8\xff"):
            return "image/jpeg"
        if image_bytes.startswith(b"RIFF") and len(image_bytes) >= 12 and image_bytes[8:12] == b"WEBP":
            return "image/webp"
        if image_bytes.startswith(b"GIF87a") or image_bytes.startswith(b"GIF89a"):
            return "image/gif"
        return "application/octet-stream"

    def _resolve_result_original_file(self, source: str = "", rel_path: str = "") -> 'Path | None':
        source = str(source or "").strip().lower()
        rel_path = str(rel_path or "").strip()

        if rel_path:
            target = self._validate_viewer_path(rel_path)
            if target and Path(target).is_file():
                return Path(target)

        if source and source != "current":
            return None

        image_window = self._get_image_window_widget()
        item = getattr(image_window, "current_history_item", None) if image_window else None
        filepath = str(getattr(item, "filepath", "") or "") if item else ""
        if filepath and Path(filepath).is_file():
            return Path(filepath).resolve()

        return None

    def _is_png_bytes(self, image_bytes: bytes) -> bool:
        if not image_bytes or not image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
            return False
        try:
            from PIL import Image

            with Image.open(io.BytesIO(image_bytes)) as opened:
                return (opened.format or "").upper() == "PNG"
        except Exception:
            return False

    def _pil_image_to_png_bytes(self, image) -> bytes:
        from utils.comfyui_png_metadata import build_pnginfo, image_to_png_bytes

        pnginfo = build_pnginfo(dict(getattr(image, "info", {}) or {}))
        return image_to_png_bytes(image, pnginfo=pnginfo)

    def _build_result_png_payload(self, source: str = "", rel_path: str = "") -> tuple[bytes, str]:
        from PIL import Image

        source = str(source or "").strip().lower()
        rel_path = str(rel_path or "").strip()

        if rel_path:
            history_item = self._find_history_item_by_rel_path(rel_path)
            if history_item and getattr(history_item, "image", None):
                label = str(getattr(history_item, "filepath", "") or self._history_item_filename(history_item))
                raw_bytes = getattr(history_item, "raw_bytes", None)
                if raw_bytes:
                    raw_bytes = bytes(raw_bytes)
                    if self._is_png_bytes(raw_bytes):
                        return raw_bytes, self._result_png_filename(label)
                filepath = str(getattr(history_item, "filepath", "") or "")
                if filepath and Path(filepath).is_file() and Path(filepath).suffix.lower() == ".png":
                    return Path(filepath).read_bytes(), self._result_png_filename(filepath)
                return self._pil_image_to_png_bytes(history_item.image), self._result_png_filename(label)

            target = self._validate_viewer_path(rel_path)
            if not target and source != "current":
                raise FileNotFoundError("Image file is unavailable")
            if target and target.suffix.lower() == ".png":
                return target.read_bytes(), self._result_png_filename(target.name)
            if target:
                with Image.open(str(target)) as opened:
                    opened.load()
                    image = opened.convert("RGBA").copy()
                return self._pil_image_to_png_bytes(image), self._result_png_filename(target.name)

        image_window = self._get_image_window_widget()
        item = getattr(image_window, "current_history_item", None) if image_window else None
        if item and getattr(item, "image", None):
            filepath = str(getattr(item, "filepath", "") or "")
            label = filepath or "naia-result.png"
            raw_bytes = getattr(item, "raw_bytes", None)
            if raw_bytes:
                raw_bytes = bytes(raw_bytes)
                if self._is_png_bytes(raw_bytes):
                    return raw_bytes, self._result_png_filename(label)
            if filepath and Path(filepath).is_file() and Path(filepath).suffix.lower() == ".png":
                return Path(filepath).read_bytes(), self._result_png_filename(filepath)
            return self._pil_image_to_png_bytes(item.image), self._result_png_filename(label)

        if self.latest_webp:
            with Image.open(io.BytesIO(self.latest_webp)) as opened:
                opened.load()
                image = opened.convert("RGBA").copy()
            return self._pil_image_to_png_bytes(image), "naia-result.png"

        raise FileNotFoundError("No image is selected")

    def _set_png_clipboard_bytes(self, png_bytes: bytes, filename: str = ""):
        set_png_clipboard_bytes(png_bytes, filename)

    def _do_copy_png_to_clipboard(self, png_bytes: bytes, filename: str = ""):
        try:
            self._set_png_clipboard_bytes(png_bytes, filename)
        except Exception as e:
            print(f"🌐 Remote: PNG clipboard copy failed — {e}")
            self._broadcast_json({
                "type": "toast",
                "message": f"PNG clipboard copy failed: {e}",
                "level": "error",
            })

    async def _request_clipboard_png(self, timeout: float = 2.0) -> bytes:
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        request_id = uuid.uuid4().hex
        with self._clipboard_png_requests_lock:
            self._pending_clipboard_png_requests[request_id] = {
                "loop": loop,
                "future": future,
            }
        self.request_read_clipboard_png.emit(request_id)
        try:
            result = await asyncio.wait_for(future, timeout=timeout)
        finally:
            with self._clipboard_png_requests_lock:
                self._pending_clipboard_png_requests.pop(request_id, None)

        if not isinstance(result, dict):
            raise RuntimeError("Invalid clipboard read result")
        error = str(result.get("error") or "").strip()
        if error:
            raise RuntimeError(error)
        png_bytes = result.get("png_bytes")
        if not png_bytes:
            raise FileNotFoundError("No image in clipboard")
        return bytes(png_bytes)

    def _complete_clipboard_png_request(self, request: dict, result: dict):
        loop = request.get("loop")
        future = request.get("future")
        if loop is None or future is None:
            return
        loop.call_soon_threadsafe(
            lambda f=future, r=result: (f.set_result(r) if not f.done() else None)
        )

    def _do_read_clipboard_png(self, request_id: str):
        with self._clipboard_png_requests_lock:
            request = self._pending_clipboard_png_requests.pop(request_id, None)
        if not request:
            return
        try:
            png_bytes = clipboard_png_bytes()
            result = {
                "ok": bool(png_bytes),
                "png_bytes": bytes(png_bytes) if png_bytes else b"",
            }
        except Exception as e:
            result = {"ok": False, "error": str(e), "png_bytes": b""}
        self._complete_clipboard_png_request(request, result)

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
        rel_path = ""
        if item:
            rel_path = self._history_item_path_key(item)
        history_urls = self._history_item_public_urls(item) if item else {}
        label = Path(filepath).name if filepath else (self._history_item_filename(item) if item else "Current Result")
        has_generation_params = bool(generation_params)
        has_source_row = self._source_row_available(source_row)
        has_prompt = bool(
            (isinstance(prompt_context, dict) and (prompt_context.get("main_prompt") or prompt_context.get("final_prompt")))
            or (isinstance(generation_params, dict) and generation_params.get("input"))
            or summary.get("prompt")
        )
        mode = str(self._current_api_mode() or "").upper()
        nai_mode = mode == "NAI"
        webui_mode = mode == "WEBUI"
        has_image = has_item_image or has_latest_image
        has_metadata = bool(metadata_payload or rel_path)
        can_use_nai_img2img = bool(has_image and nai_mode)
        can_enhance = bool(has_item_image and has_generation_params and (nai_mode or webui_mode))

        return {
            "id": "current",
            "source": "current",
            "path": rel_path,
            "file_path": filepath if has_file else "",
            "label": label,
            "image_url": history_urls.get("image_url") or ("/api/latest-image" if has_latest_image else ""),
            "metadata_url": history_urls.get("metadata_url") or "/api/result/metadata",
            "has_image": has_image,
            "has_metadata": has_metadata,
            "can_enhance": can_enhance,
            "capabilities": {
                "load_prompt": bool(has_prompt),
                "reroll": bool(has_source_row),
                "queue": bool(has_generation_params),
                "restore_params": bool(has_generation_params),
                "metadata": has_metadata,
                "paste_image": True,
                "open_file": has_file,
                "save_image": has_image,
                "copy_png": has_image,
                "image_action": can_use_nai_img2img,
                "upscale_nai": bool(has_image and nai_mode),
                "enhance": can_enhance,
                "inpaint": can_use_nai_img2img,
                "character_reference": has_item_image,
                "remote_event": has_source_row,
                "delete": False,
            },
        }

    def _build_saved_result_asset_payload(self, rel_path: str) -> dict | None:
        """저장 폴더 이미지의 ResultAsset 계약. HistoryItem 정보가 없으면 보수적으로 제한."""
        matched_item = self._find_history_item_by_path(rel_path=rel_path)
        target = self._validate_viewer_path(rel_path)
        if not target and not matched_item:
            return None
        stat = None
        if target:
            try:
                stat = target.stat()
            except Exception:
                stat = None
        if self._is_history_item_path(rel_path) or self._is_memory_history_path(rel_path):
            normalized_path = rel_path.replace("\\", "/")
        else:
            try:
                normalized_path = target.relative_to(self._get_viewer_save_dir().resolve()).as_posix()
            except Exception:
                normalized_path = rel_path.replace("\\", "/")
        matched_source_row = getattr(matched_item, "source_row", None) if matched_item else None
        has_source_row = self._source_row_available(matched_source_row)
        has_generation_params = bool(getattr(matched_item, "generation_params", None)) if matched_item else False
        has_history_image = bool(matched_item and getattr(matched_item, "image", None))
        mode = str(self._current_api_mode() or "").upper()
        nai_mode = mode == "NAI"
        webui_mode = mode == "WEBUI"
        can_use_nai_img2img = bool(has_history_image and nai_mode)
        can_enhance = bool(matched_item and getattr(matched_item, "image", None) and has_generation_params and (nai_mode or webui_mode))
        history_urls = self._history_item_public_urls(matched_item) if matched_item else {}
        label = target.name if target else self._history_item_filename(matched_item)
        file_path = str(target) if target else ""

        return {
            "id": f"saved:{normalized_path}",
            "source": "saved",
            "path": normalized_path,
            "file_path": file_path,
            "label": label,
            "image_url": history_urls.get("image_url", ""),
            "metadata_url": history_urls.get("metadata_url", ""),
            "has_image": True,
            "has_metadata": True,
            "can_enhance": can_enhance,
            "size_bytes": stat.st_size if stat else None,
            "mtime": stat.st_mtime if stat else None,
            "capabilities": {
                "load_prompt": True,
                "reroll": has_source_row,
                "queue": has_generation_params,
                "restore_params": True,
                "metadata": True,
                "paste_image": True,
                "open_file": bool(target),
                "save_image": True,
                "copy_png": True,
                "image_action": can_use_nai_img2img,
                "upscale_nai": nai_mode,
                "enhance": can_enhance,
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
        ws = None
        comfyui_request_id = None
        remote_preset_request_id = None
        try:
            ws = req.get("ws")
            source_row = req.get("source_row")
            active_ratings = req.get("active_ratings", set(self._active_ratings))

            # WS별 pending 저장 (on_prompt_generated에서 auto-generate용)
            mw = self.app_context.main_window
            auto_gen = mw.generation_checkboxes.get("자동 생성")
            auto_gen_checked = bool(auto_gen and auto_gen.isChecked())

            # ComfyUI sync 요청 처리 — ws=None 이지만 request_id로 격리
            comfyui_request_id = req.get("comfyui_request_id")
            event_preset_request_id = req.get("event_preset_request_id")
            remote_preset_request_id = req.get("remote_preset_request_id")
            remote_random_request_id = str(req.get("remote_random_request_id") or "")
            force_skip = bool(req.get("force_naia_skip_generate", False))
            respect_autogen = bool(req.get("respect_naia_autogen", True))
            comfyui_peng_override = req.get("peng_override")  # dict or None
            request_overrides = req.get("overrides") if isinstance(req.get("overrides"), dict) else None

            if comfyui_request_id:
                will_naia_generate = (
                    auto_gen_checked and respect_autogen and not force_skip
                )
                override_key = ("comfyui", comfyui_request_id)
                pending_entry = {
                    "params": None,
                    "negative": None,
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
            elif event_preset_request_id:
                self._pending_overrides[("event_preset", event_preset_request_id)] = {
                    "params": req.get("overrides") if isinstance(req.get("overrides"), dict) else {"event_preset_request": True},
                    "negative": req.get("negative"),
                    "source": "event_preset",
                    "auto_generate": True,
                    "event_preset_request_id": event_preset_request_id,
                }
                self.app_context.skip_prompt_engineering_auto_hide = True
            elif remote_preset_request_id:
                self._pending_overrides[("preset", remote_preset_request_id)] = {
                    "params": req.get("overrides") if isinstance(req.get("overrides"), dict) else {"remote_preset_request": True},
                    "negative": req.get("negative"),
                    "source": "preset",
                    "auto_generate": True,
                    "remote_preset_request_id": remote_preset_request_id,
                }
                self.app_context.skip_prompt_engineering_auto_hide = True
            elif ws:
                self._pending_overrides[ws] = {
                    "params": request_overrides,
                    "negative": None,
                    "source": "random",
                    "auto_generate": auto_gen_checked,
                    "remote_random_request_id": remote_random_request_id,
                }

            if source_row is None and ws and self._ws_manager:
                session = self._ws_manager.sessions.get(ws)
                tag_filter = session.get("tag_filter") if session else None
                if tag_filter and tag_filter.get("ids"):
                    source_row = self._pick_from_tag_filter(tag_filter, active_ratings)
                    if source_row is None:
                        self._send_json_to(ws, {"type": "random_failed",
                                                "message": "Tag filter: no matching rows",
                                                "level": "error"})
                        return

            if comfyui_request_id and source_row is None:
                if self._pick_from_snapshot(active_ratings) is None:
                    self._fail_comfyui_random_request(
                        comfyui_request_id,
                        "Random prompt source is empty",
                    )
                    print("🌐 Remote: 랜덤 프롬프트 생성 실패 — 후보 없음")
                    return

            mw.trigger_random_prompt(settings_override=request_overrides,
                                     active_ratings=active_ratings,
                                     source_row_override=source_row)
            print("🌐 Remote: 랜덤 프롬프트 생성됨")
        except Exception as e:
            if comfyui_request_id:
                self._fail_comfyui_random_request(comfyui_request_id, f"Random failed: {e}")
            elif remote_preset_request_id:
                self._pending_overrides.pop(("preset", remote_preset_request_id), None)
                self._broadcast_json({
                    "type": "preset_generation_error",
                    "source": "preset",
                    "requestId": str(remote_preset_request_id or ""),
                    "message": f"Random failed: {e}",
                })
            elif ws is not None:
                self._pending_overrides.pop(ws, None)
                self._send_json_to(ws, {"type": "random_failed",
                                        "message": f"Random failed: {e}",
                                        "level": "error"})
            print(f"🌐 Remote: 랜덤 프롬프트 생성 실패 — {e}")

    # --- Tag Filter ---

    def _master_search_dataframe(self):
        """Return the unfiltered search source used by Remote GSQE/Tag Filter."""
        mw = self.app_context.main_window
        master = getattr(mw, '_master_filter_snapshot', None)
        if master is not None and not master.empty:
            return master
        snapshot = getattr(mw, '_search_results_snapshot', None)
        if snapshot is not None and not snapshot.empty:
            mw._master_filter_snapshot = snapshot.copy()
            return snapshot
        if mw.search_results and not mw.search_results.is_empty():
            master = mw.search_results.get_dataframe()
            mw._master_filter_snapshot = master.copy()
            return master
        return None

    def _pick_from_snapshot(self, active_ratings: set, filter_ids: set = None):
        """master snapshot에서 rating + (선택적) ID 필터 적용하여 랜덤 1개 반환.
        search_results를 pop하지 않으므로 원격 quick filter에서 안전하다."""
        snapshot = self._master_search_dataframe()
        if snapshot is None or snapshot.empty:
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
        """master snapshot에서 태그 AND 검색, 매칭 ID를 반환"""
        import pandas as pd
        snapshot = self._master_search_dataframe()
        if snapshot is None or snapshot.empty:
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
            checked = self._coerce_bool(checked)
            # auto_save: image_window 체크박스 (OPTION_KEYS 외)
            if key == "auto_save":
                auto_save_checkbox = self._get_auto_save_checkbox()
                if auto_save_checkbox and auto_save_checkbox.isChecked() != checked:
                    self._syncing_option = True
                    try:
                        auto_save_checkbox.setChecked(checked)
                    finally:
                        self._syncing_option = False
                print(f"🌐 Remote: 자동 저장 → {checked}")
                self.broadcast_options()
                self._broadcast_auto_save_settings()
                return

            label = self.OPTION_KEYS.get(key)
            if not label:
                return
            if key == "auto_generate":
                self._remote_auto_generate_enabled = checked
            mw = self.app_context.main_window
            cb = mw.generation_checkboxes.get(label)
            if cb:
                if cb.isChecked() != checked:
                    self._syncing_option = True
                    try:
                        cb.setChecked(checked)
                    finally:
                        self._syncing_option = False
                    print(f"🌐 Remote: {label} → {checked}")
                self._sync_detached_option_widget(key, checked)
                self._refresh_generation_option_ui(key, cb)
            if cb:
                # setChecked() emits toggled synchronously while _syncing_option is True;
                # broadcast the shared server state after the Qt widget has settled.
                self.broadcast_options()
        except Exception as e:
            self._syncing_option = False
            print(f"🌐 Remote: 옵션 설정 실패 — {e}")

    def _sync_detached_option_widget(self, key: str, checked: bool):
        """분리된 프롬프트 창의 복제 체크박스를 직접 갱신."""
        attr_map = {
            "prompt_fixed": "detached_prompt_fixed",
            "auto_generate": "detached_auto_generate",
        }
        attr = attr_map.get(key)
        if not attr:
            return
        try:
            mw = self.app_context.main_window
            detached_cb = getattr(mw, attr, None)
            if detached_cb is None:
                return
            was_blocked = detached_cb.blockSignals(True)
            try:
                detached_cb.setChecked(checked)
            finally:
                detached_cb.blockSignals(was_blocked)
            self._repaint_checkbox(detached_cb)
        except Exception as e:
            print(f"🌐 Remote: 분리 체크박스 동기화 실패 — {key}: {e}")

    def _refresh_generation_option_ui(self, key: str, cb):
        """옵션 변경 후 체크박스와 관련 버튼의 시각 상태를 즉시 갱신."""
        try:
            self._repaint_checkbox(cb)
            if key == "prompt_fixed":
                updater = getattr(self.app_context.main_window, "update_random_prompt_button_state", None)
                if callable(updater):
                    updater()
        except Exception as e:
            print(f"🌐 Remote: 옵션 UI 갱신 실패 — {key}: {e}")

    @staticmethod
    def _repaint_checkbox(cb):
        try:
            style = cb.style()
            style.unpolish(cb)
            style.polish(cb)
            cb.update()
            cb.repaint()
        except Exception:
            pass

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
        setup_needed = self._is_setup_required()
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
            "setup_required": setup_needed,
            "last_verified": {
                "nai": timestamps.get("nai_token_last_verified", ""),
                "webui": timestamps.get("webui_url_last_verified", ""),
                "comfyui": timestamps.get("comfyui_url_last_verified", ""),
            },
            "autocomplete": self._autocomplete_status_payload(),
        }
        cloudflared = self._get_cloudflared_status()
        payload["cloudflared_active"] = cloudflared["active"]
        payload["cloudflared_url"] = cloudflared["url"]
        payload["cloudflared_status_text"] = cloudflared["status_text"]
        if ws is not None:
            allowed, reason = self._setup_gate(ws)
            payload["setup_allowed"] = allowed
            payload["setup_block_reason"] = reason
            payload["setup_required"] = setup_needed and allowed
            cf_allowed, cf_reason = self._cloudflared_gate(ws)
            payload["cloudflared_control_allowed"] = cf_allowed
            payload["cloudflared_control_block_reason"] = cf_reason
        return payload

    def _autocomplete_status_payload(self) -> dict:
        def safe_attr(name: str, default=None):
            try:
                return object.__getattribute__(self, name)
            except (AttributeError, RuntimeError):
                return default

        index = safe_attr("_tag_search_index")
        try:
            metadata_ready = bool(index and index.metadata_fallback_index_ready())
        except Exception:
            metadata_ready = False
        translation_cache = safe_attr("_autocomplete_translation_cache", {})
        result_cache = safe_attr("_autocomplete_result_cache", {})
        return {
            "kr_tags_loaded": bool(safe_attr("_kr_tags_loaded", False)),
            "metadata_fallback": {
                "ready": metadata_ready,
                "live_path_allows_build": False,
            },
            "translation_cache_size": len(translation_cache) if isinstance(translation_cache, dict) else 0,
            "result_cache_size": len(result_cache) if isinstance(result_cache, dict) else 0,
        }

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
            payload["setup_required"] = bool(common.get("setup_required")) and allowed
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
        """api_mode_changed event -> broadcast schema, then an authoritative desktop snapshot."""
        new_mode = data.get("new_mode", "")
        # NAI 모드 진입/이탈에 맞춰 Anlas 타이머 제어
        if new_mode == "NAI":
            self._start_anlas_timer()
            self._refresh_anlas_async()
        else:
            self._stop_anlas_timer()
        if not self._has_clients():
            return
        self._broadcast_json({"type": "mode", "mode": new_mode})
        # 먼저 선택지 schema를 갱신하고, preset/mode 적용이 끝난 뒤 full snapshot을 보낸다.
        self._broadcast_params()
        self._queue_desktop_control_snapshot_broadcast("mode_changed")

    def on_prompt_preset_loaded(self, data: dict):
        """Prompt preset load is an explicit desktop-authoritative reset point."""
        reason = "preset_loaded"
        if isinstance(data, dict) and data.get("reason"):
            reason = str(data.get("reason") or reason)
        self._queue_desktop_control_snapshot_broadcast(reason)

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
            opts["auto_save"] = bool(auto_save_checkbox and auto_save_checkbox.isChecked())
            return opts
        except Exception:
            return {}

    def broadcast_options(self):
        """Broadcast the shared generation-option state to all Web Shell sessions."""
        options = self.get_options()
        if not bool(options.get("auto_generate")):
            self._remote_auto_generate_enabled = False
        payload = {"type": "options", **options}
        self._cached_options = payload
        if self._has_clients():
            self._broadcast_json(payload)

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
            mw.main_prompt_textedit.setPlainText(prompt)
            mw.negative_prompt_textedit.setPlainText(negative)
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
            resolution = mw.resolution_combo.currentText() if hasattr(mw, "resolution_combo") else ""
            width = ""
            height = ""
            match = re.search(r"(\d+)\s*x\s*(\d+)", str(resolution), re.IGNORECASE)
            if match:
                width, height = match.group(1), match.group(2)
            return {
                "type": "prompt_sync",
                "prompt": prompt,
                "negative_prompt": negative,
                "model": mw.model_combo.currentText() if hasattr(mw, "model_combo") else "",
                "steps": mw.steps_spinbox.value() if hasattr(mw, "steps_spinbox") else "",
                "cfg_scale": round(mw.cfg_scale_slider.value() / 10.0, 1) if hasattr(mw, "cfg_scale_slider") else "",
                "sampler": mw.sampler_combo.currentText() if hasattr(mw, "sampler_combo") else "",
                "width": width,
                "height": height,
                "seed": mw.seed_input.text() if hasattr(mw, "seed_input") else "",
                **self._build_prompt_token_payload(prompt, negative),
            }
        except Exception:
            return {}

    def _desktop_control_snapshot_payloads(self, reason: str = "desktop_sync") -> list[dict]:
        """Build an explicit desktop-authoritative snapshot for bootstrap/reset events."""
        payloads = []
        try:
            params = self.get_generation_params()
            if params:
                params_payload = dict(params)
                params_payload["desktop_sync"] = True
                params_payload["sync_reason"] = reason
                payloads.append(params_payload)
        except Exception as e:
            print(f"🌐 Remote: desktop params snapshot failed — {e}")

        try:
            prompts = self.get_current_prompts()
            if prompts:
                prompt_payload = dict(prompts)
                prompt_payload["desktop_sync"] = True
                prompt_payload["sync_reason"] = reason
                prompt_payload["force"] = True
                payloads.append(prompt_payload)
        except Exception as e:
            print(f"🌐 Remote: desktop prompt snapshot failed — {e}")

        return payloads

    def _broadcast_desktop_control_snapshot(self, reason: str = "desktop_sync"):
        if not self._has_clients():
            return
        for payload in self._desktop_control_snapshot_payloads(reason):
            self._broadcast_json(payload)

    async def _request_desktop_control_snapshot(self, reason: str, timeout: Optional[float] = None) -> list[dict]:
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        request_id = uuid.uuid4().hex
        with self._desktop_snapshot_requests_lock:
            self._pending_desktop_snapshot_requests[request_id] = {
                "loop": loop,
                "future": future,
                "reason": reason,
            }
        self.request_send_desktop_sync.emit(request_id)
        try:
            result = await asyncio.wait_for(future, timeout=timeout) if timeout is not None else await future
            return result if isinstance(result, list) else []
        except asyncio.TimeoutError:
            with self._desktop_snapshot_requests_lock:
                self._pending_desktop_snapshot_requests.pop(request_id, None)
            print(f"🌐 Remote: desktop snapshot timed out — {reason}")
            return []
        except asyncio.CancelledError:
            with self._desktop_snapshot_requests_lock:
                self._pending_desktop_snapshot_requests.pop(request_id, None)
            raise

    async def send_desktop_control_snapshot_to_ws(self, ws, reason: str, timeout: Optional[float] = None) -> list[dict]:
        payloads = await self._request_desktop_control_snapshot(reason, timeout=timeout)
        for payload in payloads:
            await ws.send_text(json.dumps(payload))
        return payloads

    def _complete_desktop_snapshot_request(self, request: dict, payloads: list[dict]):
        loop = request.get("loop")
        future = request.get("future")
        if loop is None or future is None:
            return
        loop.call_soon_threadsafe(
            lambda f=future, p=payloads: (f.set_result(p) if not f.done() else None)
        )

    def _do_send_desktop_control_snapshot(self, request_id: str):
        with self._desktop_snapshot_requests_lock:
            request = self._pending_desktop_snapshot_requests.pop(request_id, None)
        if not request:
            return
        reason = str(request.get("reason") or "desktop_sync")
        try:
            payloads = self._desktop_control_snapshot_payloads(reason)
        except Exception as e:
            print(f"🌐 Remote: desktop snapshot request failed — {e}")
            payloads = []
        self._complete_desktop_snapshot_request(request, payloads)

    def _queue_desktop_control_snapshot_broadcast(self, reason: str):
        QTimer.singleShot(0, lambda r=reason: self._broadcast_desktop_control_snapshot(r))

    def _on_prompt_text_changed(self):
        """Desktop prompt edits no longer push control state to Web Sessions."""
        return

    def _broadcast_prompts(self):
        """Deprecated desktop -> web prompt sync path."""
        self._cached_prompts = {}

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

    def _ensure_history_id(self, item) -> str:
        history_id = str(getattr(item, "history_id", "") or "").strip()
        if not history_id:
            history_id = uuid.uuid4().hex
            try:
                setattr(item, "history_id", history_id)
            except Exception:
                pass
        return re.sub(r"[^A-Za-z0-9_.-]+", "_", history_id)[:96] or uuid.uuid4().hex

    def _history_item_filename(self, item) -> str:
        stable_filename = str(getattr(item, "history_filename", "") or "").strip()
        if stable_filename:
            return stable_filename

        filepath = str(getattr(item, "filepath", "") or "")
        if filepath:
            filename = Path(filepath).name
            if filename:
                try:
                    setattr(item, "history_filename", filename)
                except Exception:
                    pass
                return filename
        raw_bytes = getattr(item, "raw_bytes", None)
        extension = "webp" if isinstance(raw_bytes, (bytes, bytearray)) and bytes(raw_bytes).startswith(b"RIFF") and bytes(raw_bytes)[8:12] == b"WEBP" else "png"
        filename = f"history-{self._ensure_history_id(item)[:12]}.{extension}"
        try:
            setattr(item, "history_filename", filename)
        except Exception:
            pass
        return filename

    def _history_item_path_key(self, item) -> str:
        return f"{self.HISTORY_ITEM_PATH_PREFIX}{self._ensure_history_id(item)}/{self._history_item_filename(item)}"

    def _history_item_public_urls(self, item) -> dict:
        history_id = quote(self._ensure_history_id(item), safe="")
        return {
            "thumb_url": f"/api/history/thumb/{history_id}",
            "image_url": f"/api/history/image/{history_id}",
            "metadata_url": f"/api/history/meta/{history_id}",
        }

    def _is_history_item_path(self, rel_path: str) -> bool:
        return str(rel_path or "").replace("\\", "/").startswith(self.HISTORY_ITEM_PATH_PREFIX)

    def _history_id_from_path(self, rel_path: str) -> str:
        rel_path = str(rel_path or "").replace("\\", "/")
        if not self._is_history_item_path(rel_path):
            return ""
        rest = rel_path[len(self.HISTORY_ITEM_PATH_PREFIX):]
        return rest.split("/", 1)[0].strip()

    def _find_history_item_by_id(self, history_id: str):
        history_id = str(history_id or "").strip()
        if not history_id:
            return None
        for item in self._iter_memory_history_items() or ():
            if self._ensure_history_id(item) == history_id:
                return item
        return None

    def _find_history_item_by_rel_path(self, rel_path: str):
        history_id = self._history_id_from_path(rel_path)
        return self._find_history_item_by_id(history_id) if history_id else None

    def _history_item_file_path(self, item) -> 'Path | None':
        filepath = str(getattr(item, "filepath", "") or "")
        if not filepath:
            return None
        try:
            path = Path(filepath).resolve()
        except Exception:
            return None
        return path if self._is_viewer_image_file(path) else None

    def _history_item_summary(self, item, index: int = 0) -> dict:
        from datetime import datetime

        path = self._history_item_file_path(item)
        raw_bytes = getattr(item, "raw_bytes", None)
        size_bytes = len(raw_bytes) if isinstance(raw_bytes, (bytes, bytearray)) else 0
        mtime = time.time()
        if path:
            try:
                stat = path.stat()
                size_bytes = stat.st_size
                mtime = stat.st_mtime
            except OSError:
                pass
        summary = {
            "rel_path": self._history_item_path_key(item),
            "history_id": self._ensure_history_id(item),
            "filename": self._history_item_filename(item),
            "file_path": str(path) if path else "",
            "source": "memory",
            "size_bytes": size_bytes,
            "mtime": mtime,
            "mtime_iso": datetime.fromtimestamp(mtime).isoformat(),
            "index": index,
        }
        summary.update(self._history_item_public_urls(item))
        return summary

    def _history_count(self) -> int:
        return sum(1 for _ in (self._iter_memory_history_items() or ()))

    def _scan_memory_history(self) -> list:
        """현재 ImageWindow 히스토리에 남아있는 이미지 목록만 반환.

        Web Shell의 History는 데스크탑 ImageHistoryWindow와 동일하게 현재 저장
        폴더 설정이 아니라 메모리 HistoryItem을 기준으로 동작해야 한다. 따라서
        URL path는 현재 저장 루트 상대경로가 아니라 HistoryItem.history_id에서 만든
        안정 키를 사용한다. Auto Save가 꺼져 filepath가 없어도 Web History가
        Desktop History의 기능적 복제체로 남도록 한다.
        """
        entries = []
        for index, item in enumerate(self._iter_memory_history_items() or ()):
            if item is not None:
                entries.append(self._history_item_summary(item, index=index))
        return entries

    def _invalidate_viewer_cache(self):
        """viewer 캐시 무효화 (새 이미지 저장 시)"""
        self._viewer_cache_time = 0

    def _iter_memory_history_items(self):
        """Yield in-memory HistoryItem objects without reading image bytes."""
        image_window = self._get_image_window_widget()
        if not image_window:
            return

        seen_ids = set()
        history_window = getattr(image_window, "image_history_window", None)
        history_widgets = getattr(history_window, "history_widgets", []) if history_window else []
        for widget in history_widgets:
            item = getattr(widget, "history_item", None)
            if item is None or id(item) in seen_ids:
                continue
            seen_ids.add(id(item))
            yield item

        if history_window is not None:
            return

        current_item = getattr(image_window, "current_history_item", None)
        if current_item is not None and id(current_item) not in seen_ids:
            yield current_item

    def _history_path_digest(self, abs_path: 'Path') -> str:
        import os

        try:
            normalized = os.path.normcase(str(Path(abs_path).resolve()))
        except Exception:
            normalized = os.path.normcase(str(abs_path))
        return hashlib.sha256(normalized.encode("utf-8", errors="replace")).hexdigest()[:24]

    def _memory_history_path_key(self, abs_path: 'Path') -> str:
        path = Path(abs_path)
        digest = self._history_path_digest(path)
        return f"{self.MEMORY_HISTORY_PATH_PREFIX}{digest}/{path.name}"

    def _is_memory_history_path(self, rel_path: str) -> bool:
        return str(rel_path or "").replace("\\", "/").startswith(self.MEMORY_HISTORY_PATH_PREFIX)

    def _resolve_memory_history_path(self, rel_path: str) -> 'Path | None':
        rel_path = str(rel_path or "").replace("\\", "/").strip()
        if not self._is_memory_history_path(rel_path):
            return None

        rest = rel_path[len(self.MEMORY_HISTORY_PATH_PREFIX):]
        digest = rest.split("/", 1)[0].strip()
        if not digest:
            return None

        for item in self._iter_memory_history_items() or ():
            filepath = str(getattr(item, "filepath", "") or "")
            if not filepath:
                continue
            try:
                path = Path(filepath).resolve()
            except Exception:
                continue
            if self._history_path_digest(path) == digest and self._is_viewer_image_file(path):
                return path
        return None

    def _resolve_memory_history_path_by_suffix(self, rel_path: str) -> 'Path | None':
        """Resolve stale relative paths that were minted before the save root changed."""
        rel_path = str(rel_path or "").replace("\\", "/").strip().lstrip("/")
        if not rel_path or rel_path.startswith("../") or "/../" in rel_path:
            return None
        rel_parts = [part for part in Path(rel_path).parts if part not in ("", ".")]
        if not rel_parts:
            return None

        matches = []
        for item in self._iter_memory_history_items() or ():
            filepath = str(getattr(item, "filepath", "") or "")
            if not filepath:
                continue
            try:
                path = Path(filepath).resolve()
            except Exception:
                continue
            path_parts = list(path.parts)
            if len(path_parts) >= len(rel_parts) and path_parts[-len(rel_parts):] == rel_parts and self._is_viewer_image_file(path):
                matches.append(path)

        if len(matches) == 1:
            return matches[0]
        return None

    def _is_viewer_image_file(self, path: 'Path') -> bool:
        try:
            target = Path(path)
            return target.is_file() and target.suffix.lower() in {'.png', '.webp', '.jpg', '.jpeg'}
        except Exception:
            return False

    def _validate_viewer_path(self, rel_path: str) -> 'Path | None':
        """상대/히스토리 경로를 검증하고 실제 이미지 파일로 해석한다."""
        from pathlib import Path

        history_item = self._find_history_item_by_rel_path(rel_path)
        if history_item:
            return self._history_item_file_path(history_item)

        history_target = self._resolve_memory_history_path(rel_path)
        if history_target:
            return history_target

        save_dir = self._get_viewer_save_dir().resolve()
        target = (save_dir / rel_path).resolve()
        try:
            target.relative_to(save_dir)
        except ValueError:
            fallback = self._resolve_memory_history_path_by_suffix(rel_path)
            if fallback:
                return fallback
            print(f"🌐 Viewer: 경로 탈출 시도 차단 — {rel_path}")
            return None
        if self._is_viewer_image_file(target):
            return target

        fallback = self._resolve_memory_history_path_by_suffix(rel_path)
        if fallback:
            return fallback
        return None

    def _get_or_create_thumbnail(self, abs_path: 'Path', max_side: int = 0) -> bytes:
        """이미지 썸네일 반환 (디스크 캐시). max_side=0이면 원본의 절반. blocking."""
        from pathlib import Path
        from PIL import Image
        import io

        abs_path = Path(abs_path).resolve()
        thumb_path = self._thumbnail_cache_path(abs_path, max_side)
        thumb_dir = thumb_path.parent

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

    def _thumbnail_cache_path(self, abs_path: 'Path', max_side: int = 0) -> 'Path':
        import tempfile

        abs_path = Path(abs_path).resolve()
        digest = self._history_path_digest(abs_path)
        size_token = "auto" if max_side <= 0 else str(max(1, int(max_side)))
        cache_root = Path(tempfile.gettempdir()) / "NAIA2" / "remote_web_thumbnails"
        return cache_root / digest[:2] / f"{digest}.{size_token}.thumb.webp"

    def _history_item_image_payload(self, item) -> tuple[bytes, str]:
        raw_bytes = getattr(item, "raw_bytes", None)
        if isinstance(raw_bytes, bytearray):
            raw_bytes = bytes(raw_bytes)
        if isinstance(raw_bytes, bytes) and raw_bytes:
            return raw_bytes, self._image_media_type_for_bytes(raw_bytes)

        image = getattr(item, "image", None)
        if image is None:
            raise FileNotFoundError("History image is unavailable")
        buf = io.BytesIO()
        image.save(buf, format="PNG")
        return buf.getvalue(), "image/png"

    def _history_item_thumbnail(self, item, max_side: int = 0) -> bytes:
        path = self._history_item_file_path(item)
        if path:
            return self._get_or_create_thumbnail(path, max_side)

        image = getattr(item, "image", None)
        if image is None:
            return b""
        try:
            from PIL import Image

            thumb = image.copy()
            if max_side <= 0:
                max_side = 256
            max_side = min(max(max_side, 50), 1024)
            thumb.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
            buf = io.BytesIO()
            thumb.save(buf, format="WEBP", quality=85, method=4)
            return buf.getvalue()
        except Exception as e:
            print(f"🌐 Viewer: 메모리 히스토리 썸네일 생성 실패 — {e}")
            return b""

    def _history_item_meta_payload(self, item, include_full: bool = False) -> dict:
        gen_params = getattr(item, "generation_params", {}) or {}
        prompt_context = getattr(item, "prompt_context", {}) or {}
        raw = {
            "generation_params": gen_params,
            "prompt_context": prompt_context,
            "api_metadata": getattr(item, "api_metadata", {}) or {},
        }
        prompt = ""
        negative = ""
        if isinstance(prompt_context, dict):
            prompt = str(prompt_context.get("main_prompt") or prompt_context.get("final_prompt") or "")
        if isinstance(gen_params, dict):
            prompt = prompt or str(gen_params.get("input") or gen_params.get("prompt") or "")
            negative = str(gen_params.get("negative_prompt") or gen_params.get("uc") or "")

        result = {}
        if prompt:
            result["prompt"] = prompt
        if negative:
            result["negative"] = negative
        characters = prompt_context.get("characters") if isinstance(prompt_context, dict) else None
        if characters:
            result["characters"] = characters
        if include_full:
            result["summary"] = dict(result)
            result["raw"] = self._metadata_json_safe(raw)
        return result

    def _on_image_saved(self, data: dict):
        """image_saved는 저장 폴더 캐시만 무효화한다.

        Web History의 원본은 Desktop HistoryItem이므로 저장 완료 이벤트가
        히스토리 항목을 직접 추가하면 Auto Save off/큐 제한 상태와 갈라진다.
        """
        self._invalidate_viewer_cache()

    def on_history_item_added(self, history_item):
        self._invalidate_viewer_cache()
        if not history_item or not self._has_clients():
            return
        payload = self._history_item_summary(history_item)
        payload.update({
            "type": "viewer_new_image",
            "total": self._history_count(),
        })
        self._broadcast_json(payload)
        self._broadcast_auto_save_settings()

    def on_history_item_removed(self, history_item):
        self._invalidate_viewer_cache()
        if not history_item or not self._has_clients():
            return
        self._broadcast_json({
            "type": "viewer_history_removed",
            "rel_path": self._history_item_path_key(history_item),
            "history_id": self._ensure_history_id(history_item),
            "total": self._history_count(),
        })
        self._broadcast_auto_save_settings()

    def on_history_cleared(self):
        self._invalidate_viewer_cache()
        if self._has_clients():
            self._broadcast_json({"type": "viewer_history_cleared", "total": 0})
            self._broadcast_auto_save_settings()

    # --- 생성 파라미터 동기화 ---

    def _combo_items(self, combo) -> list:
        return [combo.itemText(i) for i in range(combo.count())]

    def _get_comfyui_workflow_manager(self):
        manager = getattr(self.app_context, "comfyui_workflow_manager", None)
        if manager is not None:
            return manager
        mw = getattr(self.app_context, "main_window", None)
        return getattr(mw, "workflow_manager", None)

    def _format_anima_weight(self, raw) -> str:
        text = str(raw or "").strip()
        if not text:
            value = 1.0
        else:
            try:
                value = float(text)
            except (TypeError, ValueError):
                value = 1.0
            if not math.isfinite(value):
                value = 1.0
        return f"{value:.3f}".rstrip("0").rstrip(".")

    def _comfyui_workflow_state_payload(self, event_data: Optional[dict] = None) -> dict:
        manager = self._get_comfyui_workflow_manager()
        event_data = event_data if isinstance(event_data, dict) else {}
        node_map = getattr(manager, "user_workflow_node_map", None) or {}
        has_custom = bool(getattr(manager, "user_workflow", None) is not None)
        if "has_custom" in event_data:
            has_custom = bool(event_data.get("has_custom"))
        return {
            "type": "comfyui_workflow_state",
            "has_custom": has_custom,
            "workflow_label": "Custom Workflow" if has_custom else "Basic Workflow",
            "model_compat": event_data.get("model_compat", node_map.get("model_compat") if has_custom else None),
            "locked_loader_class": event_data.get("locked_loader_class", node_map.get("locked_loader_class")),
            "locked_model_display": event_data.get("locked_model_display", node_map.get("locked_model_display")),
        }

    def _set_comfyui_workflow_buttons(self, has_custom: bool):
        mw = getattr(self.app_context, "main_window", None)
        if not mw:
            return
        default_btn = getattr(mw, "workflow_default_btn", None)
        custom_btn = getattr(mw, "workflow_custom_btn", None)
        try:
            if has_custom:
                if custom_btn:
                    custom_btn.setEnabled(True)
                    custom_btn.setChecked(True)
            else:
                if default_btn:
                    default_btn.setChecked(True)
                if custom_btn:
                    custom_btn.setEnabled(False)
        except Exception as e:
            print(f"🌐 Remote: ComfyUI 워크플로우 버튼 상태 갱신 실패 — {e}")

    def _show_comfyui_workflow_status(self, message: str):
        mw = getattr(self.app_context, "main_window", None)
        status_bar = getattr(mw, "status_bar", None)
        if status_bar and hasattr(status_bar, "showMessage"):
            try:
                status_bar.showMessage(message, 3000)
            except Exception:
                pass

    def _broadcast_comfyui_workflow_state(self, event_data: Optional[dict] = None):
        state = self._comfyui_workflow_state_payload(event_data)
        if self._has_clients():
            self._broadcast_json(state)
        return state

    def on_comfyui_workflow_changed(self, data: dict):
        """Desktop workflow edits should not push selected state into Web Sessions."""
        params = self.get_generation_param_schema()
        if params:
            self._cached_params = params

    def _extract_comfyui_workflow_metadata_from_png_bytes(self, image_bytes: bytes) -> dict:
        if not image_bytes:
            raise ValueError("No image data")

        try:
            from PIL import Image
            with Image.open(io.BytesIO(image_bytes)) as img:
                metadata = dict(img.info or {})
        except Exception as e:
            raise ValueError(f"PNG 분석 실패: {e}") from e

        if "prompt" not in metadata or not (metadata.get("workflow") or metadata.get("workflow_api")):
            raise ValueError("선택한 이미지에서 ComfyUI 워크플로우 정보를 찾을 수 없습니다.")
        return metadata

    async def _request_comfyui_workflow_action(
        self,
        action: str,
        metadata: Optional[dict] = None,
        timeout: float = 30.0,
    ) -> dict:
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        request_id = uuid.uuid4().hex
        with self._comfyui_workflow_actions_lock:
            self._pending_comfyui_workflow_actions[request_id] = {
                "loop": loop,
                "future": future,
                "action": action,
                "metadata": metadata,
            }
        self.request_comfyui_workflow_action.emit(request_id)
        try:
            return await asyncio.wait_for(future, timeout=timeout)
        finally:
            with self._comfyui_workflow_actions_lock:
                self._pending_comfyui_workflow_actions.pop(request_id, None)

    def _complete_comfyui_workflow_action(self, request: dict, result: dict):
        loop = request.get("loop")
        future = request.get("future")
        if loop is None or future is None:
            return
        loop.call_soon_threadsafe(
            lambda f=future, r=result: (f.set_result(r) if not f.done() else None)
        )

    def _do_comfyui_workflow_action(self, request_id: str):
        with self._comfyui_workflow_actions_lock:
            request = self._pending_comfyui_workflow_actions.pop(request_id, None)
        if not request:
            return

        try:
            action = str(request.get("action") or "").strip().lower()
            if action == "load":
                result = self._load_comfyui_workflow_from_metadata(request.get("metadata") or {})
            elif action == "clear":
                result = self._clear_comfyui_workflow()
            else:
                result = {"ok": False, "error": "Unsupported ComfyUI workflow action"}
        except Exception as e:
            result = {"ok": False, "error": f"ComfyUI workflow action failed: {e}"}
        self._complete_comfyui_workflow_action(request, result)

    def _load_comfyui_workflow_from_metadata(self, metadata: dict) -> dict:
        manager = self._get_comfyui_workflow_manager()
        if manager is None:
            return {"ok": False, "error": "ComfyUI workflow manager is unavailable"}

        if not isinstance(metadata, dict):
            return {"ok": False, "error": "Invalid workflow metadata"}

        analysis_result = manager.analyze_workflow_for_ui(metadata)
        if not analysis_result.get("success"):
            return {
                "ok": False,
                "error": analysis_result.get("error_message") or "워크플로우 검증에 실패했습니다.",
                "analysis": analysis_result,
                "workflow": self._comfyui_workflow_state_payload(),
            }

        if not manager.load_workflow_from_metadata(metadata):
            return {
                "ok": False,
                "error": "워크플로우를 로드하지 못했습니다.",
                "analysis": analysis_result,
                "workflow": self._comfyui_workflow_state_payload(),
            }

        self._set_comfyui_workflow_buttons(True)
        self._show_comfyui_workflow_status("✅ 커스텀 워크플로우가 활성화되었습니다.")
        state = self._comfyui_workflow_state_payload()
        params = self.get_generation_param_schema()
        if params:
            self._cached_params = params
        if self._has_clients():
            self._broadcast_json(state)
            if params:
                self._broadcast_json(params)
        return {
            "ok": True,
            "analysis": analysis_result,
            "workflow": state,
            "params": params,
        }

    def _clear_comfyui_workflow(self) -> dict:
        manager = self._get_comfyui_workflow_manager()
        if manager is None:
            return {"ok": False, "error": "ComfyUI workflow manager is unavailable"}

        manager.clear_user_workflow()
        self._set_comfyui_workflow_buttons(False)
        self._show_comfyui_workflow_status("🔄 기본 워크플로우로 전환되었습니다.")
        state = self._comfyui_workflow_state_payload()
        params = self.get_generation_param_schema()
        if params:
            self._cached_params = params
        if self._has_clients():
            self._broadcast_json(state)
            if params:
                self._broadcast_json(params)
        return {
            "ok": True,
            "workflow": state,
            "params": params,
        }

    @staticmethod
    def _strip_generation_param_values(params: dict) -> dict:
        schema = dict(params or {})
        for key in (
            "model", "sampler", "scheduler", "resolution", "steps", "cfg_scale",
            "cfg_rescale", "seed", "seed_fixed", "random_resolution",
            "auto_fit_resolution", "SMEA", "DYN", "VAR+", "DECRISP",
            "enable_hr", "hr_scale", "hr_upscaler", "denoising_strength",
            "hires_steps", "hr_cfg", "sampling_mode", "rescale_cfg",
            "anima_weight", "anima_weight_raw", "comfyui_workflow",
            "comfyui_workflow_has_custom", "comfyui_workflow_label",
        ):
            schema.pop(key, None)
        schema["schema_only"] = True
        return schema

    def get_generation_param_schema(self) -> dict:
        """Return selectable parameter metadata without desktop-selected values."""
        schema = self._strip_generation_param_values(self.get_generation_params())
        schema.update(self._remote_web_generation_param_defaults(self._current_api_mode()))
        return schema

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
            params.update(self._resolution_preset_defaults_for_mode(mode))
            if mode == "WEBUI":
                params.update(self._remote_web_generation_param_defaults(mode))
            elif hasattr(mw, 'anima_weight_edit'):
                raw_anima_weight = mw.anima_weight_edit.text().strip()
                params["anima_weight_raw"] = raw_anima_weight
                params["anima_weight"] = self._format_anima_weight(raw_anima_weight)
            workflow_state = self._comfyui_workflow_state_payload()
            params["comfyui_workflow"] = {k: v for k, v in workflow_state.items() if k != "type"}
            params["comfyui_workflow_has_custom"] = workflow_state["has_custom"]
            params["comfyui_workflow_label"] = workflow_state["workflow_label"]
            return params
        except Exception as e:
            print(f"🌐 Remote: 파라미터 읽기 실패 — {e}")
            return {}

    def _do_set_param(self, key: str, value: str):
        """웹에서 변경한 생성 파라미터를 메인 앱 위젯에 반영"""
        try:
            self._syncing_param = True
            if key == "hires_preset_swap":
                self._save_remote_web_ui_state(hires_preset_swap=value)
                self._syncing_param = False
                return
            if key in {"resolution_preset_enabled", "resolution_preset"}:
                self._save_resolution_preset_param(key, value)
                self._syncing_param = False
                return
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
                if hasattr(mw, "clear_detected_resolution_override"):
                    mw.clear_detected_resolution_override()
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
                if value != "true" and hasattr(mw, "clear_detected_resolution_override"):
                    mw.clear_detected_resolution_override()
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
                button = None
                if value == "eps":
                    button = mw.eps_radio
                elif value == "v_prediction":
                    button = mw.v_pred_radio
                elif value == "anima":
                    button = mw.anima_radio
                if button is not None:
                    button.setChecked(True)
                    if hasattr(mw, '_on_sampling_mode_changed'):
                        mw._on_sampling_mode_changed(button)
            elif key == "rescale_cfg" and hasattr(mw, 'comfyui_rescale_slider'):
                mw.comfyui_rescale_slider.setValue(int(float(value) * 100))
            elif key == "anima_weight":
                normalized_weight = self._format_anima_weight(value)
                if hasattr(mw, 'anima_weight_edit'):
                    mw.anima_weight_edit.setText(normalized_weight)
                self._save_remote_web_ui_state(random_prompt_weight=normalized_weight)
            self._syncing_param = False
        except Exception as e:
            self._syncing_param = False
            print(f"🌐 Remote: 파라미터 설정 실패 — {key}={value}: {e}")

    def _on_params_changed(self):
        """Desktop parameter edits no longer push control state to Web Sessions."""
        return

    def _broadcast_params(self):
        """파라미터 선택지 schema만 캐시 갱신 + WS 클라이언트에 전송."""
        data = self.get_generation_param_schema()
        if data:
            self._cached_params = data
            if self._has_clients():
                self._broadcast_json(data)

    async def _request_resolution_action(self, payload: dict, timeout: float = 5.0) -> dict:
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        request_id = uuid.uuid4().hex
        with self._resolution_actions_lock:
            self._pending_resolution_actions[request_id] = {
                "loop": loop,
                "future": future,
                "payload": dict(payload or {}),
            }
        self.request_resolution_action.emit(request_id)
        try:
            return await asyncio.wait_for(future, timeout=timeout)
        finally:
            with self._resolution_actions_lock:
                self._pending_resolution_actions.pop(request_id, None)

    def _complete_resolution_action(self, request: dict, result: dict):
        loop = request.get("loop")
        future = request.get("future")
        if loop is None or future is None:
            return
        loop.call_soon_threadsafe(
            lambda f=future, r=result: (f.set_result(r) if not f.done() else None)
        )

    def _normalize_resolution_mode(self, mode: str | None = None) -> str:
        normalized = str(mode or self._current_api_mode() or "NAI").strip().upper()
        return normalized if normalized in {"NAI", "WEBUI", "COMFYUI"} else "NAI"

    def _resolution_multiple_for_mode(self, mode: str | None = None) -> int:
        return 64 if self._normalize_resolution_mode(mode) == "NAI" else 8

    def _current_resolution_items(self, mode: str | None = None) -> list[str]:
        mode = self._normalize_resolution_mode(mode)
        mw = getattr(self.app_context, "main_window", None)
        combo = getattr(mw, "resolution_combo", None)
        if mode == self._normalize_resolution_mode() and combo is not None:
            items = self._combo_items(combo)
            if items:
                return items
        if hasattr(mw, "_load_resolutions"):
            try:
                items = mw._load_resolutions(mode)
                if items:
                    return [str(item) for item in items if str(item).strip()]
            except Exception as exc:
                print(f"🌐 Remote: {mode} 해상도 목록 로드 실패 — {exc}")
        stored = getattr(mw, "resolutions", None)
        if mode == self._normalize_resolution_mode() and isinstance(stored, list) and stored:
            return [str(item) for item in stored if str(item).strip()]
        return list(self.DEFAULT_RESOLUTIONS)

    def _resolution_manager_state(self, mode: str | None = None) -> dict:
        mode = self._normalize_resolution_mode(mode)
        mw = getattr(self.app_context, "main_window", None)
        combo = getattr(mw, "resolution_combo", None)
        current = ""
        try:
            if mode == self._normalize_resolution_mode() and combo is not None:
                current = combo.currentText()
        except Exception:
            current = ""
        resolutions = self._current_resolution_items(mode)
        if current not in resolutions:
            current = resolutions[0] if resolutions else ""
        return {
            "ok": True,
            "api_mode": mode,
            "multiple": self._resolution_multiple_for_mode(mode),
            "max_value": 8192,
            "warning_pixel_area": 1024 * 1024,
            "defaults": list(self.DEFAULT_RESOLUTIONS),
            "resolutions": resolutions,
            "current_resolution": current,
        }

    def _normalize_resolution_items_for_save(self, raw_items, mode: str | None = None) -> list[str]:
        if not isinstance(raw_items, list):
            raise ValueError("resolutions must be a list")
        mode = self._normalize_resolution_mode(mode)
        multiple = self._resolution_multiple_for_mode(mode)
        normalized = []
        seen = set()
        for item in raw_items:
            pair = self._parse_resolution_pair(item)
            if not pair:
                raise ValueError(f"invalid resolution: {item}")
            width, height = pair
            if width > 8192 or height > 8192:
                raise ValueError("width and height must be 8192 or less")
            if width % multiple != 0 or height % multiple != 0:
                raise ValueError(f"width and height must be multiples of {multiple}")
            label = f"{width} x {height}"
            if label in seen:
                continue
            seen.add(label)
            normalized.append(label)
        if not normalized:
            raise ValueError("resolution list cannot be empty")
        return normalized

    def _apply_resolution_items(self, resolutions: list[str], mode: str | None = None) -> dict:
        mode = self._normalize_resolution_mode(mode)
        mw = getattr(self.app_context, "main_window", None)
        if mw is None:
            raise RuntimeError("main window is unavailable")
        combo = getattr(mw, "resolution_combo", None)
        current = combo.currentText() if combo is not None else ""
        if hasattr(mw, "_save_resolutions"):
            mw._save_resolutions(resolutions, mode)

        if mode != self._normalize_resolution_mode():
            return self._resolution_manager_state(mode)

        if hasattr(mw, "_apply_resolutions_for_mode"):
            try:
                mw._apply_resolutions_for_mode(mode, current)
                if hasattr(mw, "status_bar") and mw.status_bar:
                    mw.status_bar.showMessage("✅ 해상도 목록이 저장되었습니다.", 3000)
                self._broadcast_params()
                return self._resolution_manager_state(mode)
            except Exception as exc:
                print(f"🌐 Remote: 모드별 해상도 적용 실패 — {exc}")

        mw.resolutions = list(resolutions)

        for target_combo in (combo, getattr(mw, "detached_resolution_combo", None)):
            if target_combo is None:
                continue
            try:
                was_blocked = target_combo.blockSignals(True)
                try:
                    target_combo.clear()
                    target_combo.addItems(mw.resolutions)
                    if current in mw.resolutions:
                        target_combo.setCurrentText(current)
                    else:
                        target_combo.setCurrentIndex(0)
                finally:
                    target_combo.blockSignals(was_blocked)
            except Exception as exc:
                print(f"🌐 Remote: 해상도 콤보 갱신 실패 — {exc}")

        if hasattr(mw, "status_bar") and mw.status_bar:
            mw.status_bar.showMessage("✅ 해상도 목록이 저장되었습니다.", 3000)
        self._broadcast_params()
        return self._resolution_manager_state()

    def _do_resolution_action(self, request_id: str):
        with self._resolution_actions_lock:
            request = self._pending_resolution_actions.pop(request_id, None)
        if not request:
            return
        payload = request.get("payload") or {}
        action = str(payload.get("action") or "get").strip().lower()
        mode = self._normalize_resolution_mode(payload.get("api_mode") or payload.get("mode"))
        try:
            if action == "get":
                result = self._resolution_manager_state(mode)
            elif action == "save":
                resolutions = self._normalize_resolution_items_for_save(payload.get("resolutions"), mode)
                result = self._apply_resolution_items(resolutions, mode)
            else:
                result = {"ok": False, "error": "unsupported resolution action"}
        except Exception as exc:
            result = {"ok": False, "error": str(exc)}
        self._complete_resolution_action(request, result)

    # --- 생성 상태 동기화 (메인 UI 포함) ---

    def _on_generation_started_signal(self, data=None):
        """generation_started 이벤트 → 웹에 상태 전송"""
        if self._has_clients():
            self._broadcast_json({"type": "status", "is_generating": True})
            self._broadcast_queue_state()

    def on_generation_error(self, data=None):
        """Generation error event -> clear Remote Web generation state."""
        payload = data if isinstance(data, dict) else {}
        scoped_error = False
        if payload.get("event_preset_request"):
            scoped_error = True
            self._broadcast_json({
                "type": "event_preset_generation_error",
                "requestId": str(payload.get("event_preset_request_id") or ""),
                "message": str(payload.get("message") or "Event Preset generation failed"),
            })
        if payload.get("remote_preset_request"):
            scoped_error = True
            self._broadcast_json({
                "type": "preset_generation_error",
                "source": "preset",
                "requestId": str(payload.get("remote_preset_request_id") or ""),
                "message": str(payload.get("message") or "Preset generation failed"),
            })
        if payload.get("result_enhance_request"):
            scoped_error = True
            self.on_result_enhance_completed(False, str(payload.get("message") or "Enhance failed"))
        if not scoped_error:
            self._broadcast_json({
                "type": "toast",
                "message": str(payload.get("message") or "Generation failed"),
                "level": "error",
            })
        self._broadcast_json({"type": "status", "is_generating": False})

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
            "e621_event": "E621EventModuleV2",
            "ollama": "OllamaModule",
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

    def _find_history_item_by_path(self, rel_path: str = "", file_path: str = ""):
        image_window = self._get_image_window_widget()
        if not image_window:
            return None

        target = None
        rel_path = str(rel_path or "").strip()
        file_path = str(file_path or "").strip()
        if rel_path:
            history_item = self._find_history_item_by_rel_path(rel_path)
            if history_item:
                return history_item
        if rel_path:
            target = self._validate_viewer_path(rel_path)
        elif file_path:
            try:
                target = Path(file_path).resolve()
            except Exception:
                target = None
        if not target:
            return None

        try:
            target = Path(target).resolve()
        except Exception:
            return None

        history_window = getattr(image_window, "image_history_window", None)
        history_widgets = getattr(history_window, "history_widgets", []) if history_window else []
        for widget in history_widgets:
            item = getattr(widget, "history_item", None)
            item_path = getattr(item, "filepath", "") if item else ""
            if not item_path:
                continue
            try:
                if Path(item_path).resolve() == target:
                    return item
            except Exception:
                continue

        current_item = getattr(image_window, "current_history_item", None)
        current_path = getattr(current_item, "filepath", "") if current_item else ""
        if current_path:
            try:
                if Path(current_path).resolve() == target:
                    return current_item
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
        elif module_id == "event_stream":
            return self._read_event_stream()
        elif module_id == "webui_hiresfix_assist":
            return self._read_webui_hiresfix_assist()
        elif module_id == "character_reference":
            return self._read_character_reference()
        elif module_id == "vibe_transfer":
            return self._read_vibe_transfer()
        elif module_id == "img2img":
            return self._read_img2img()
        elif module_id == "save_directory":
            return self._read_save_directory(ws=ws)
        elif module_id == "wildcard":
            return self._read_wildcard()
        elif module_id == "instant_wildcard":
            return self._read_instant_wildcard()
        elif module_id == "chunk":
            return self._read_chunk()
        elif module_id == "e621_event":
            return self._read_e621_event()
        elif module_id == "ollama":
            return self._read_ollama()
        return {}

    def _read_event_stream(self) -> dict:
        try:
            runtime = getattr(self.app_context, "event_stream_runtime", None)
            state = runtime.get_state() if runtime and hasattr(runtime, "get_state") else {}
            return {
                "type": "module_state",
                "module_id": "event_stream",
                **state,
            }
        except Exception as e:
            print(f"🌐 Remote: event_stream 상태 읽기 실패 — {e}")
            return {
                "type": "module_state",
                "module_id": "event_stream",
                "active": False,
                "error": str(e),
            }

    def _broadcast_event_stream_state(self, _payload=None):
        if not self._has_clients():
            return
        self._broadcast_json(self._read_event_stream())

    def _read_webui_hiresfix_assist(self) -> dict:
        state = self._normalize_webui_hiresfix_assist_state(
            getattr(self, "_webui_hiresfix_assist", None)
        )
        return {
            "type": "module_state",
            "module_id": "webui_hiresfix_assist",
            **state,
        }

    def _broadcast_webui_hiresfix_assist_state(self):
        if not self._has_clients():
            return
        self._broadcast_json(self._read_webui_hiresfix_assist())

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
        self._invalidate_viewer_cache()

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
            if auto_save_checkbox is None:
                return {}
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
                "unsaved_history_count": self._unsaved_history_count(),
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
        if self._syncing_option:
            return
        self._broadcast_auto_save_settings()

    def _read_prompt_engineering(self, ws=None) -> dict:
        try:
            m = self._find_module("prompt_engineering")
            if not m:
                return {}

            # 콤보가 현재 API 모드의 프리셋 폴더와 동기화돼 있음을 보장한다.
            # api_mode_changed 이벤트가 일부 경로(예: 웹 트리거 모드 전환)에서 늦거나 누락되면
            # preset_combo 가 이전 모드의 항목을 들고 있어 Hires Preset Swap 등 후행 소비자가
            # 잘못된 목록을 받게 된다. load_preset_list 는 blockSignals + 선택값 보존이 되어 있어
            # 데스크탑 UI 에 부작용 없이 idempotent 하게 갱신된다.
            try:
                if hasattr(m, "load_preset_list"):
                    m.load_preset_list()
            except Exception as e:
                print(f"⚠️ Remote: preset_combo 동기화 실패 — {e}")

            preprocessing = {}
            for label, cb in m.preprocessing_checkboxes.items():
                key = m.option_key_map.get(label, label)
                preprocessing[key] = cb.isChecked()
            presets = [m.preset_combo.itemText(i) for i in range(m.preset_combo.count())]
            current_preset = m.preset_combo.currentText()
            randomized_pool = list(getattr(m, "randomized_preset_list", []) or [])
            if hasattr(m, "get_randomized_available_presets"):
                randomized_available = list(m.get_randomized_available_presets())
            else:
                randomized_available = [
                    preset_name for preset_name in getattr(m, "preset_list", [])
                    if preset_name not in ("", "*randomized", "default", *randomized_pool)
                ]
            preset_summaries = [
                self._prompt_engineering_preset_summary(m, preset_name)
                for preset_name in presets
            ]
            webui_presets = self._prompt_engineering_preset_names_for_mode("WEBUI")
            webui_preset_summaries = [
                self._prompt_engineering_preset_summary(m, preset_name, mode="WEBUI")
                for preset_name in webui_presets
            ]
            return {
                "type": "module_state",
                "module_id": "prompt_engineering",
                "preset": current_preset,
                "preset_options": presets,
                "preset_summaries": preset_summaries,
                "webui_preset_options": webui_presets,
                "webui_preset_summaries": webui_preset_summaries,
                "randomized_active": current_preset == "*randomized",
                "randomized_preset_list": randomized_pool,
                "randomized_available_presets": randomized_available,
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

    def _prompt_engineering_preset_names_for_mode(self, mode: str) -> list[str]:
        """Return real prompt-engineering preset files for one API mode."""
        try:
            mode_key = self._normalize_prompt_engineering_preset_mode(mode)
        except ValueError:
            return []
        preset_dir = Path("save") / "presets" / mode_key
        if not preset_dir.is_dir():
            return []
        names = []
        for path in sorted(preset_dir.glob("*.json")):
            if not path.is_file():
                continue
            if path.name.endswith(".hires.json"):
                continue
            name = path.stem
            if not name or name == "*randomized" or name.endswith(".hires"):
                continue
            names.append(name)
        if "default" in names:
            names.remove("default")
            names.insert(0, "default")
        return names

    def _prompt_engineering_preview_candidates(self, preset_name: str, mode: str = "") -> list[Path]:
        safe_name = Path(str(preset_name or "").strip()).name
        if not safe_name or safe_name == "*randomized":
            return []
        mode_key = self._normalize_prompt_engineering_preset_mode(mode, allow_empty=True)

        candidates = []
        preview_dir = Path("save") / "presets" / "previews"
        for ext in (".png", ".webp", ".jpg", ".jpeg"):
            candidates.append(preview_dir / f"{safe_name}{ext}")

        # Legacy favorite-preset thumbnails are mode-tagged in favorites.json.
        try:
            favorites_path = Path("save") / "presets" / "favorites.json"
            favorite_items = json.loads(favorites_path.read_text(encoding="utf-8")) if favorites_path.exists() else []
            if any(
                isinstance(item, dict)
                and item.get("name") == safe_name
                and (not mode_key or item.get("mode") == mode_key)
                for item in favorite_items
            ):
                favorite_dir = Path("save") / "presets" / "favorites"
                for ext in (".png", ".webp", ".jpg", ".jpeg"):
                    candidates.append(favorite_dir / f"{safe_name}{ext}")
        except Exception:
            pass
        return candidates

    def _prompt_engineering_preview_path(self, preset_name: str, mode: str = "") -> Path | None:
        for candidate in self._prompt_engineering_preview_candidates(preset_name, mode):
            try:
                target = candidate.resolve()
            except Exception:
                continue
            if target.is_file():
                return target
        return None

    def _prompt_engineering_thumbnail_target(self, preset_name: str) -> Path:
        safe_name = Path(str(preset_name or "").strip()).name
        if not safe_name or safe_name == "*randomized":
            raise ValueError("Preset name is required")
        target_dir = Path("save") / "presets" / "previews"
        target_dir.mkdir(parents=True, exist_ok=True)
        return target_dir / f"{safe_name}.png"

    def _prompt_engineering_thumbnail_update_payload(self, preset_name: str, mode: str = "") -> dict:
        safe_name = Path(str(preset_name or "").strip()).name
        mode_key = self._normalize_prompt_engineering_preset_mode(mode, allow_empty=True)
        target = self._prompt_engineering_preview_path(safe_name, mode_key)
        if not target:
            target = self._prompt_engineering_thumbnail_target(safe_name)
        try:
            version = int(target.stat().st_mtime) if target.exists() else int(time.time())
        except Exception:
            version = int(time.time())
        return {
            "ok": True,
            "name": safe_name,
            "mode": mode_key,
            "has_thumbnail": target.exists(),
            "thumbnail_url": (
                f"/api/prompt-engineering/preset-thumbnail"
                f"?name={quote(safe_name, safe='')}&mode={quote(mode_key, safe='')}&v={version}"
            ),
        }

    def _save_prompt_engineering_thumbnail_image(self, image, preset_name: str, mode: str = "") -> dict:
        mode_key = self._normalize_prompt_engineering_preset_mode(mode, allow_empty=True)
        target = self._prompt_engineering_thumbnail_target(preset_name)
        source = image.convert("RGBA") if hasattr(image, "convert") else image
        source.save(target, format="PNG")
        return self._prompt_engineering_thumbnail_update_payload(preset_name, mode_key)

    def _save_prompt_engineering_thumbnail_bytes(self, preset_name: str, mode: str, image_bytes: bytes) -> dict:
        if not image_bytes:
            raise ValueError("Image payload is empty")
        if len(image_bytes) > 24 * 1024 * 1024:
            raise ValueError("Image is too large")
        mode_key = self._normalize_prompt_engineering_preset_mode(mode, allow_empty=True)
        from PIL import Image
        with Image.open(io.BytesIO(image_bytes)) as opened:
            opened.load()
            payload = self._save_prompt_engineering_thumbnail_image(opened, preset_name, mode_key)
        self._broadcast_json({
            "type": "prompt_engineering_preset_thumbnail_updated",
            **payload,
        })
        return payload

    def _normalize_prompt_engineering_preset_mode(self, mode: str = "", *, allow_empty: bool = False) -> str:
        value = str(mode or "").strip().upper()
        if not value:
            if allow_empty:
                return ""
            current_mode = str(self._current_api_mode() or "").strip().upper()
            return current_mode if current_mode in self.PROMPT_ENGINEERING_PRESET_MODES else "NAI"
        if value not in self.PROMPT_ENGINEERING_PRESET_MODES:
            raise ValueError("Invalid preset mode")
        return value

    def _active_vibe_transfer_count_for_generation(self) -> int:
        try:
            module = self._find_module("vibe_transfer")
            if not module:
                return 0
            frames = getattr(module, "vibe_frames", []) or []
            if frames:
                return sum(
                    1 for frame in frames
                    if bool(getattr(frame, "is_enabled", False))
                    and bool(getattr(frame, "vibe_encodings", None))
                )
            if hasattr(module, "get_vibe_transfer_multiple_data"):
                data = module.get_vibe_transfer_multiple_data() or {}
                vibes = data.get("reference_image_multiple") or []
                if isinstance(vibes, (list, tuple)):
                    return len(vibes)
        except Exception:
            return 0
        return 0

    def _prompt_engineering_preset_file(self, preset_name: str, mode: str = "") -> Path | None:
        safe_name = Path(str(preset_name or "").strip()).name
        if not safe_name:
            return None
        mode_candidates = []
        if mode:
            mode_candidates.append(self._normalize_prompt_engineering_preset_mode(mode))
        try:
            current_mode = self._normalize_prompt_engineering_preset_mode(
                self._current_api_mode(),
                allow_empty=True,
            )
            if current_mode and current_mode not in mode_candidates:
                mode_candidates.append(current_mode)
        except Exception:
            pass
        for fallback_mode in self.PROMPT_ENGINEERING_PRESET_MODES:
            if fallback_mode not in mode_candidates:
                mode_candidates.append(fallback_mode)
        for mode_name in mode_candidates:
            candidate = Path("save") / "presets" / mode_name / f"{safe_name}.json"
            if candidate.exists():
                return candidate
        return None

    def _prompt_engineering_thumbnail_generation_prompt(self, preset_name: str, mode: str = "") -> str:
        pieces = []
        preset_file = self._prompt_engineering_preset_file(preset_name, mode)
        if preset_file:
            try:
                data = json.loads(preset_file.read_text(encoding="utf-8"))
                settings = data.get("module_settings", {}) if isinstance(data, dict) else {}
                pre_prompt = str(settings.get("pre_prompt", "") or "").strip()
                if pre_prompt:
                    pieces.append(pre_prompt)
            except Exception as e:
                print(f"🌐 Remote: 프리셋 썸네일 생성용 프롬프트 읽기 실패 — {preset_name}: {e}")
        pieces.append("1girl, original, solo, upper body")
        return ", ".join(piece for piece in pieces if piece)

    def _request_prompt_engineering_thumbnail_generation(self, payload: dict) -> dict:
        payload = payload if isinstance(payload, dict) else {}
        name = Path(str(payload.get("name") or "").strip()).name
        mode = self._normalize_prompt_engineering_preset_mode(payload.get("mode") or "")
        if not name or name == "*randomized":
            raise ValueError("Preset name is required")
        if not self._prompt_engineering_preset_file(name, mode):
            raise FileNotFoundError(f"Preset not found: {name}")

        prompt = self._prompt_engineering_thumbnail_generation_prompt(name, mode)
        try:
            negative = self.app_context.main_window.negative_prompt_textedit.toPlainText().strip()
        except Exception:
            negative = ""
        request_id = str(payload.get("request_id") or uuid.uuid4().hex)
        overrides = {
            "input": prompt,
            "_raw_input": prompt,
            "negative_prompt": negative,
            "width": 1088,
            "height": 960,
            "random_resolution": False,
            "prompt_preset_thumbnail_request": True,
            "prompt_preset_thumbnail_request_id": request_id,
            "prompt_preset_thumbnail_name": name,
            "prompt_preset_thumbnail_mode": mode,
            "_skip_vibe_transfer_late_binding": True,
            "_remote_queue_source": "Preset Thumb",
            "_remote_queue_label": name,
        }
        vibe_count = self._active_vibe_transfer_count_for_generation()
        message = f"{name} 임시 썸네일 생성을 요청했습니다."
        if vibe_count:
            message += (
                " 현재 활성 Vibe Transfer는 썸네일 생성에 적용하지 않습니다. "
                "프리셋 썸네일에 Vibe를 반영하려면 Vibe Cluster로 저장한 뒤 "
                "프리셋 프롬프트에 vibe:클러스터명을 넣어주세요."
            )
        self._pending_generate_requests.append({"ws": None, "overrides": overrides})
        self.request_generate.emit()
        return {
            "ok": True,
            "status": "generation_requested",
            "request_id": request_id,
            "name": name,
            "mode": mode,
            "vibe_active": bool(vibe_count),
            "vibe_count": vibe_count,
            "message": message,
        }

    def _request_prompt_engineering_thumbnail_generation_threadsafe(self, payload: dict) -> dict:
        app = QCoreApplication.instance()
        if app and self.thread() == QThread.currentThread():
            return self._request_prompt_engineering_thumbnail_generation(payload)

        done = threading.Event()
        request = {
            "payload": payload if isinstance(payload, dict) else {},
            "done": done,
            "result": None,
            "error": None,
        }
        self.request_prompt_preset_thumbnail_generate.emit(request)
        if not done.wait(10):
            raise TimeoutError("Preset thumbnail generation request timed out")
        if request["error"]:
            raise request["error"]
        return request["result"] or {}

    def _do_request_prompt_engineering_thumbnail_generation(self, request: dict):
        if not isinstance(request, dict):
            return
        try:
            payload = request.get("payload")
            request["result"] = self._request_prompt_engineering_thumbnail_generation(payload)
        except Exception as e:
            request["error"] = e
        finally:
            done = request.get("done")
            if done:
                done.set()

    def _prompt_engineering_preset_summary(self, module, preset_name: str, mode: str = "") -> dict:
        name = str(preset_name or "")
        try:
            current_mode = self._normalize_prompt_engineering_preset_mode(
                mode or self._current_api_mode(),
                allow_empty=True,
            ) or "NAI"
        except ValueError:
            current_mode = "NAI"
        summary = {
            "name": name,
            "api_mode": current_mode,
            "description": "",
            "pre_prompt_preview": "",
            "post_prompt_preview": "",
            "auto_hide_preview": "",
            "has_thumbnail": False,
            "thumbnail_url": "",
        }
        if not name or name == "*randomized":
            summary["description"] = "Randomly selects from the randomized preset list."
            return summary

        try:
            if mode:
                try:
                    preset_dir = module.get_preset_dir(current_mode)
                except TypeError:
                    preset_dir = Path("save") / "presets" / current_mode
            else:
                preset_dir = module.get_preset_dir()
            preset_file = preset_dir / f"{name}.json"
            if preset_file.exists():
                with open(preset_file, "r", encoding="utf-8") as f:
                    preset_data = json.load(f)
                module_settings = preset_data.get("module_settings", {}) or {}
                try:
                    summary["api_mode"] = self._normalize_prompt_engineering_preset_mode(
                        preset_data.get("api_mode", current_mode) or current_mode,
                    )
                except ValueError:
                    summary["api_mode"] = current_mode
                summary["description"] = str(preset_data.get("description", "") or "")
                summary["pre_prompt_preview"] = str(module_settings.get("pre_prompt", "") or "")
                summary["post_prompt_preview"] = str(module_settings.get("post_prompt", "") or "")
                summary["auto_hide_preview"] = str(module_settings.get("auto_hide_prompt", "") or "")
        except Exception as e:
            print(f"🌐 Remote: 프리셋 요약 읽기 실패 — {name}: {e}")

        preview_path = self._prompt_engineering_preview_path(name, summary["api_mode"])
        if preview_path:
            summary["has_thumbnail"] = True
            try:
                version = int(preview_path.stat().st_mtime)
            except Exception:
                version = int(time.time())
            summary["thumbnail_url"] = (
                f"/api/prompt-engineering/preset-thumbnail"
                f"?name={quote(name, safe='')}&mode={quote(summary['api_mode'], safe='')}&v={version}"
            )
        return summary

    def _broadcast_prompt_engineering_state(self):
        state = self._read_prompt_engineering()
        if state:
            self._broadcast_json(state)

    # ------------------------------------------------------------
    # Hires Preset Overlay (sidecar: <name>.hires.json) — Edit 기능 백엔드
    # ------------------------------------------------------------
    HIRES_OVERLAY_DISALLOWED_NAMES = {"", "*randomized", "(프리셋 없음)"}

    def _hires_overlay_path(self, preset_name: str) -> Optional[Path]:
        """sidecar 경로 반환. 경로 탈출 / 예약 이름 / 비-WEBUI 모드면 None."""
        name = (preset_name or "").strip()
        if name in self.HIRES_OVERLAY_DISALLOWED_NAMES:
            return None
        safe_name = Path(name).name
        if safe_name != name:
            return None  # 경로 탈출 방지
        try:
            mode = self.app_context.get_api_mode() or "WEBUI"
        except Exception:
            mode = "WEBUI"
        if mode != "WEBUI":
            return None
        return Path("save") / "presets" / mode / f"{safe_name}.hires.json"

    def _hires_overlay_response(self, preset_name: str) -> dict:
        """Edit 모달용 — 원본 + overlay 동시 반환."""
        name = (preset_name or "").strip()
        response = {
            "type": "hires_preset_overlay",
            "preset_name": name,
            "original": {"prefix_prompt": "", "postfix_prompt": "", "negative_prompt": ""},
            "overlay": None,
            "editable": False,
        }
        path = self._hires_overlay_path(name)
        if path is None:
            return response
        response["editable"] = True

        # 원본 프리셋 로드 (sidecar 경로 옆 동일 이름의 .json)
        try:
            preset_path = path.parent / f"{name}.json"
            if preset_path.exists():
                preset_data = json.loads(preset_path.read_text(encoding="utf-8"))
                module_settings = preset_data.get("module_settings", {}) or {}
                main_settings = preset_data.get("main_settings", {}) or {}
                response["original"] = {
                    "prefix_prompt": str(module_settings.get("pre_prompt", "") or ""),
                    "postfix_prompt": str(module_settings.get("post_prompt", "") or ""),
                    "negative_prompt": str(
                        main_settings.get("negative") or main_settings.get("negative_prompt") or ""
                    ),
                }
        except Exception as e:
            print(f"🌐 Remote: hires overlay 원본 로드 실패 — {name}: {e}")

        # Overlay 로드 (있을 때만)
        if path.exists():
            try:
                overlay = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(overlay, dict):
                    response["overlay"] = {
                        "prefix_prompt": str(overlay.get("prefix_prompt", "") or ""),
                        "postfix_prompt": str(overlay.get("postfix_prompt", "") or ""),
                        "negative_prompt": str(overlay.get("negative_prompt", "") or ""),
                    }
            except Exception as e:
                print(f"🌐 Remote: hires overlay 파싱 실패 — {name}: {e}")

        return response

    def _write_hires_overlay(self, preset_name: str, body: dict) -> tuple[bool, str]:
        path = self._hires_overlay_path(preset_name)
        if path is None:
            return False, "WEBUI 모드의 일반 프리셋만 편집할 수 있습니다."
        payload = {
            "schema_version": 1,
            "prefix_prompt": str((body or {}).get("prefix_prompt", "") or ""),
            "postfix_prompt": str((body or {}).get("postfix_prompt", "") or ""),
            "negative_prompt": str((body or {}).get("negative_prompt", "") or ""),
        }
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            return True, f"Overlay saved: {path.name}"
        except Exception as e:
            return False, f"저장 실패: {e}"

    def _reset_hires_overlay(self, preset_name: str) -> tuple[bool, str]:
        path = self._hires_overlay_path(preset_name)
        if path is None:
            return False, "WEBUI 모드의 일반 프리셋만 편집할 수 있습니다."
        try:
            if path.exists():
                path.unlink()
                return True, f"Overlay removed: {path.name}"
            return True, "Overlay already absent."
        except Exception as e:
            return False, f"삭제 실패: {e}"

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
                if hasattr(m, "_slot_state_for_widget"):
                    slot_state = m._slot_state_for_widget(w)
                else:
                    slot_state = "active" if w.active_checkbox.isChecked() else getattr(w, "slot_state", "inactive")
                characters.append({
                    "id": w.char_id,
                    "active": w.active_checkbox.isChecked(),
                    "slot_state": slot_state,
                    "return_slot_state": str(getattr(w, "return_slot_state", "") or ""),
                    "custom_name": str(getattr(w, "custom_name", "") or ""),
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
                "cold_count": sum(1 for item in characters if item.get("slot_state") == "cold"),
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

    def _cond_engine_options(self, module=None, source=None) -> dict:
        raw = source
        if raw is None and module is not None:
            try:
                if hasattr(module, "get_engine_options"):
                    raw = module.get_engine_options()
                else:
                    raw = getattr(module, "_engine_options", None)
            except Exception:
                raw = None
        if not isinstance(raw, dict):
            raw = {}
        try:
            max_passes = int(raw.get("max_passes", 1))
        except Exception:
            max_passes = 1
        return {
            "max_passes": min(20, max(1, max_passes)),
            "stop_on_match": bool(raw.get("stop_on_match", False)),
        }

    def _cond_preset_infos(self) -> list:
        try:
            from modules.conditional.preset_io import get_default_storage

            infos = []
            for info in get_default_storage().list_all():
                infos.append({
                    "name": info.name,
                    "description": info.description,
                    "is_bundled": bool(info.is_bundled),
                    "rule_count": int(info.rule_count),
                })
            return infos
        except Exception as e:
            print(f"🌐 Remote: conditional preset 목록 읽기 실패 — {e}")
            return []

    def _cond_rulebook_dict_from_dsl(self, dsl_text: str, module=None) -> dict:
        """조건부 v2 DSL을 웹 편집기가 쓰는 RuleBook JSON으로 변환."""
        try:
            from dataclasses import asdict
            from modules.conditional.dsl_parser import parse_rulebook
            from modules.conditional.preset_io import SCHEMA_VERSION

            book = parse_rulebook(dsl_text or "")
            opts = self._cond_engine_options(module) if module is not None else {}
            book.max_passes = int(opts.get("max_passes", book.max_passes))
            book.stop_on_match = bool(opts.get("stop_on_match", book.stop_on_match))
            return {
                "schema_version": SCHEMA_VERSION,
                "name": "",
                "description": "",
                "engine_options": {
                    "max_passes": book.max_passes,
                    "stop_on_match": book.stop_on_match,
                },
                "rules": [asdict(rule) for rule in book.rules],
            }
        except Exception as e:
            print(f"🌐 Remote: conditional RuleBook 변환 실패 — {e}")
            return {
                "schema_version": 1,
                "name": "",
                "description": "",
                "engine_options": self._cond_engine_options(module) if module is not None else {},
                "rules": [],
            }

    def _cond_book_from_json_value(self, value: str):
        from modules.conditional.preset_io import rulebook_from_dict

        data = json.loads(value or "{}")
        if isinstance(data, dict) and isinstance(data.get("book"), dict):
            data = data["book"]
        if not isinstance(data, dict):
            data = {}
        return rulebook_from_dict(data), data

    def _cond_state_values_from_module(self, module) -> dict:
        legacy_rules = ""
        rules_textedit = getattr(module, "rules_textedit", None)
        if rules_textedit is not None:
            try:
                legacy_rules = rules_textedit.toPlainText()
            except Exception:
                legacy_rules = ""

        try:
            editor_mode = module.get_editor_mode() if hasattr(module, "get_editor_mode") else getattr(module, "_editor_mode", "legacy")
        except Exception:
            editor_mode = "legacy"
        editor_mode = editor_mode if editor_mode in ("legacy", "v2") else "legacy"

        try:
            rules_v2 = module.get_v2_dsl() if hasattr(module, "get_v2_dsl") else getattr(module, "_rules_v2_dsl", "")
        except Exception:
            rules_v2 = ""
        rules_v2 = rules_v2 if isinstance(rules_v2, str) else ""

        active_rules = rules_v2 if editor_mode == "v2" else legacy_rules
        active_preset = None
        try:
            if hasattr(module, "get_active_preset_name"):
                active_preset = module.get_active_preset_name()
            else:
                active_preset = getattr(module, "_active_preset_name", None)
        except Exception:
            active_preset = None

        enable_checkbox = getattr(module, "enable_checkbox", None)
        enabled = False
        if enable_checkbox is not None:
            try:
                enabled = bool(enable_checkbox.isChecked())
            except Exception:
                enabled = False

        return {
            "enabled": enabled,
            "editor_mode": editor_mode,
            "rules": active_rules,
            "active_rules": active_rules,
            "rules_legacy": legacy_rules,
            "rules_v2": rules_v2,
            "rules_v2_book": self._cond_rulebook_dict_from_dsl(rules_v2, module),
            "engine_options": self._cond_engine_options(module),
            "active_preset": active_preset or "",
            "presets": self._cond_preset_infos(),
        }

    def _read_conditional_prompt(self, ws=None) -> dict:
        try:
            m = self._find_module("conditional_prompt")
            if not m:
                return {}
            values = self._cond_state_values_from_module(m)
            log = ""
            log_textedit = getattr(m, "log_textedit", None)
            if log_textedit is not None:
                try:
                    log = log_textedit.toPlainText()
                except Exception:
                    log = ""
            return {
                "type": "module_state",
                "module_id": "conditional_prompt",
                **values,
                "log": log,
            }
        except Exception as e:
            print(f"🌐 Remote: conditional_prompt 상태 읽기 실패 — {e}")
            return {}

    # --- E621 Event Module V2 ---

    def _ensure_e621_loaded(self, module) -> bool:
        """E621 module data/settings lazy-load for remote access."""
        if not module:
            return False
        try:
            if not getattr(module, "_remote_settings_loaded", False) and hasattr(module, "load_settings"):
                module.load_settings()
                module._remote_settings_loaded = True
            if not getattr(module, "is_loaded", False) and hasattr(module, "load_data"):
                module.load_data()
            return bool(getattr(module, "data", None))
        except Exception as e:
            print(f"🌐 Remote: E621 데이터 로드 실패 — {e}")
            return False

    def _e621_view_mode(self, module) -> str:
        radio = getattr(module, "radio_starred", None)
        if radio is not None:
            try:
                return "starred" if radio.isChecked() else "default"
            except Exception:
                pass
        return getattr(module, "_remote_view_mode", "default")

    def _e621_category_data(self, module, category: str):
        data = getattr(module, "data", None) or {}
        for section in ("General", "Species"):
            section_data = data.get(section, {})
            if isinstance(section_data, dict) and category in section_data:
                return section, section_data.get(category)
        return None, None

    def _e621_collect_tags(self, module, data) -> list:
        tags = []
        try:
            module._collect_all_tags(data, tags)
        except Exception:
            tags = []
        return tags

    def _e621_format_count(self, module, count) -> str:
        try:
            return module._format_count(int(count or 0))
        except Exception:
            try:
                return str(int(count or 0))
            except Exception:
                return "0"

    def _e621_clean_wiki_text(self, module, text: str) -> str:
        try:
            return module._clean_wiki_text(text or "")
        except Exception:
            return text or ""

    def _e621_tag_payload(self, module, tag_data: dict) -> dict:
        tag_name = tag_data.get("tag", "") if isinstance(tag_data, dict) else ""
        count = tag_data.get("count", 0) if isinstance(tag_data, dict) else 0
        return {
            "tag": tag_name,
            "display": tag_name.replace("_", " "),
            "kor": tag_data.get("kor", "") if isinstance(tag_data, dict) else "",
            "count": count,
            "count_label": self._e621_format_count(module, count),
            "starred": tag_name in getattr(module, "starred_keys", set()),
            "hidden": tag_name in getattr(module, "deleted_keys", set()),
            "matched_in_wiki": bool(tag_data.get("matched_in_wiki", False)) if isinstance(tag_data, dict) else False,
        }

    def _e621_filter_tags(self, module, tags: list, include_hidden: bool = False) -> list:
        deleted = getattr(module, "deleted_keys", set())
        if not include_hidden:
            tags = [tag for tag in tags if tag.get("tag", "") not in deleted]
        if self._e621_view_mode(module) == "starred":
            starred = getattr(module, "starred_keys", set())
            tags = [tag for tag in tags if tag.get("tag", "") in starred]
        return tags

    def _e621_update_search_index(self, module, search_text: str):
        search_text = (search_text or "").strip().lower()
        module._remote_search_text = search_text
        module.searched_tree = {}
        if not search_text:
            module.is_searching = False
            return
        if not getattr(module, "data", None):
            module.is_searching = False
            return

        searched_tree = {}
        data = module.data or {}
        all_categories = {}
        for section in ("General", "Species"):
            section_data = data.get(section, {})
            if isinstance(section_data, dict):
                all_categories.update(section_data)

        for category_name, category_data in all_categories.items():
            if not isinstance(category_data, dict):
                continue
            category_folders = {}
            for folder_name, folder_data in category_data.items():
                folder_tags = self._e621_collect_tags(module, folder_data)
                matched = []
                for tag_data in folder_tags:
                    tag_name = tag_data.get("tag", "")
                    matched_in_tag = search_text in tag_name.lower()
                    matched_in_wiki = False
                    if not getattr(module, "disable_wiki_search", False) and not matched_in_tag:
                        wiki_body = tag_data.get("wiki_body", "").lower()
                        wiki_preview = tag_data.get("wiki_preview", "").lower()
                        matched_in_wiki = search_text in wiki_body or search_text in wiki_preview
                    if matched_in_tag or matched_in_wiki:
                        tagged = dict(tag_data)
                        tagged["matched_in_wiki"] = matched_in_wiki
                        matched.append(tagged)
                if matched:
                    category_folders[folder_name] = matched
            if category_folders:
                searched_tree[category_name] = category_folders

        module.searched_tree = searched_tree
        module.is_searching = bool(searched_tree)

    def _e621_categories(self, module) -> list:
        data = getattr(module, "data", None) or {}
        starred = getattr(module, "starred_keys", set())
        categories = []
        for section in ("General", "Species"):
            section_data = data.get(section, {})
            if not isinstance(section_data, dict):
                continue
            for name in sorted(section_data.keys()):
                category_data = section_data.get(name, {})
                tags = self._e621_collect_tags(module, category_data)
                hidden = getattr(module, "deleted_keys", set())
                visible_tags = [tag for tag in tags if tag.get("tag", "") not in hidden]
                starred_count = sum(1 for tag in visible_tags if tag.get("tag", "") in starred)
                categories.append({
                    "name": name,
                    "section": section,
                    "folder_count": len(category_data) if isinstance(category_data, dict) else 0,
                    "tag_count": len(visible_tags),
                    "starred_count": starred_count,
                    "matched": bool(getattr(module, "is_searching", False) and name in getattr(module, "searched_tree", {})),
                    "selected": name == getattr(module, "current_category", None),
                })
        return categories

    def _e621_folders(self, module) -> list:
        category = getattr(module, "current_category", None)
        if not category:
            return []
        folders_source = None
        if getattr(module, "is_searching", False):
            folders_source = getattr(module, "searched_tree", {}).get(category, {})
        else:
            _, folders_source = self._e621_category_data(module, category)
        if not isinstance(folders_source, dict):
            return []

        folders = []
        for folder_name in sorted(folders_source.keys()):
            tags = self._e621_collect_tags(module, folders_source.get(folder_name))
            tags = self._e621_filter_tags(module, tags)
            if not tags:
                continue
            folders.append({
                "name": folder_name,
                "display": folder_name.replace("_", " "),
                "tag_count": len(tags),
                "selected": folder_name == getattr(module, "current_level2", None),
            })
        return folders

    def _e621_visible_tags(self, module) -> list:
        selected_category = getattr(module, "current_category", None)
        selected_folder = getattr(module, "current_level2", None)
        tags = []
        if getattr(module, "is_searching", False):
            searched_tree = getattr(module, "searched_tree", {})
            category_items = (
                [(selected_category, searched_tree.get(selected_category, {}))]
                if selected_category else list(searched_tree.items())
            )
            seen = set()
            for _, folders in category_items:
                if not isinstance(folders, dict):
                    continue
                folder_items = (
                    [(selected_folder, folders.get(selected_folder, []))]
                    if selected_folder else list(folders.items())
                )
                for _, folder_tags in folder_items:
                    for tag_data in folder_tags or []:
                        tag_name = tag_data.get("tag", "")
                        if tag_name in seen:
                            continue
                        seen.add(tag_name)
                        tags.append(tag_data)
        elif selected_category:
            _, category_data = self._e621_category_data(module, selected_category)
            if isinstance(category_data, dict):
                if selected_folder:
                    tags = self._e621_collect_tags(module, category_data.get(selected_folder, {}))
                else:
                    tags = self._e621_collect_tags(module, category_data)
        tags = self._e621_filter_tags(module, tags)
        tags.sort(key=lambda item: int(item.get("count") or 0), reverse=True)
        return tags

    def _e621_find_tag(self, module, tag_name: str) -> dict | None:
        if not tag_name:
            return None
        for tag_data in self._e621_visible_tags(module):
            if tag_data.get("tag", "") == tag_name:
                return tag_data
        data = getattr(module, "data", None) or {}
        for section in ("General", "Species"):
            section_data = data.get(section, {})
            if not isinstance(section_data, dict):
                continue
            for category_data in section_data.values():
                for tag_data in self._e621_collect_tags(module, category_data):
                    if tag_data.get("tag", "") == tag_name:
                        return tag_data
        return None

    def _e621_wiki_payload(self, module, tag_data: dict | None) -> dict:
        if not tag_data:
            return {"tag": "", "text": "", "translated": False}
        tag_name = tag_data.get("tag", "")
        count = tag_data.get("count", 0)
        body = tag_data.get("wiki_body") or tag_data.get("wiki_preview") or ""
        clean_body = self._e621_clean_wiki_text(module, body) if body else "위키 정보 없음"
        translated_body, translated = self._e621_translate_wiki_body(module, tag_name, count, clean_body)
        display = tag_name.replace("_", " ")
        text = f"Tag: {display}\nCount: {self._e621_format_count(module, count)}\n\n{'=' * 50}\n\n{translated_body}"
        return {"tag": tag_name, "text": text, "translated": translated}

    def _e621_translation_cache(self, module) -> dict:
        cache = getattr(module, "_remote_wiki_translation_cache", None)
        if not isinstance(cache, dict):
            cache = {}
            setattr(module, "_remote_wiki_translation_cache", cache)
        return cache

    def _e621_translate_wiki_body(self, module, tag_name: str, count, body_text: str) -> tuple[str, bool]:
        if getattr(module, "disable_translation", False):
            return body_text, False
        if not body_text or body_text == "위키 정보 없음":
            return body_text, False
        try:
            translatable_text = module._extract_translatable_text(body_text)
        except Exception:
            translatable_text = body_text.strip()
        if not translatable_text or translatable_text == "위키 정보 없음":
            return body_text, False

        cache = self._e621_translation_cache(module)
        cache_key = (str(tag_name), str(count), translatable_text)
        translated_text = cache.get(cache_key)
        if translated_text is None:
            try:
                from utils.translator import english_to_korean
                translated_text = english_to_korean(translatable_text) or ""
            except Exception as e:
                print(f"🌐 Remote: e621 wiki 번역 실패 — {e}")
                translated_text = ""
            if translated_text:
                cache[cache_key] = translated_text
        if not translated_text:
            return body_text, False

        remaining_text = body_text[len(translatable_text):].strip() if len(translatable_text) < len(body_text) else ""
        if remaining_text:
            return f"{translated_text}\n\n{remaining_text}", True
        return translated_text, True

    def _e621_testbench_text(self, module) -> str:
        edit = getattr(module, "related_tags_edit", None)
        if edit is not None:
            try:
                return edit.toPlainText()
            except Exception:
                pass
        return getattr(
            module,
            "_remote_testbench_text",
            "1girl, 1boy, 2:: e621태그는_강조하여_입력하세요 ::, duo, male/female, nsfw, rating:explicit",
        )

    def _e621_widget_not_hidden(self, widget, default: bool = True) -> bool:
        if widget is None:
            return default
        try:
            return not bool(widget.isHidden())
        except Exception:
            return default

    def _e621_prompt_testbench_visible(self, module) -> bool:
        edit_visible = self._e621_widget_not_hidden(getattr(module, "related_tags_edit", None), True)
        button_visible = self._e621_widget_not_hidden(getattr(module, "generate_button", None), True)
        return bool(edit_visible and button_visible)

    def _e621_translation_control_visible(self, module) -> bool:
        return self._e621_widget_not_hidden(getattr(module, "disable_translation_checkbox", None), True)

    def _e621_wiki_search_control_visible(self, module) -> bool:
        return self._e621_widget_not_hidden(getattr(module, "disable_wiki_search_checkbox", None), True)

    def _e621_effective_search_text(self, module) -> str:
        remote_text = getattr(module, "_remote_search_text", "")
        if remote_text:
            return remote_text
        search_input = getattr(module, "search_input", None)
        if search_input is not None:
            try:
                return search_input.text()
            except Exception:
                pass
        return ""

    def _e621_event_state_cache_key(self, module, loaded: bool) -> tuple:
        selected_name = getattr(module, "_remote_selected_tag", None) or getattr(module, "current_level3", None)
        return (
            id(getattr(module, "data", None)),
            bool(loaded),
            self._e621_effective_search_text(module),
            bool(getattr(module, "is_searching", False)),
            self._e621_view_mode(module),
            bool(getattr(module, "disable_translation", False)),
            bool(getattr(module, "disable_wiki_search", False)),
            self._e621_prompt_testbench_visible(module),
            self._e621_translation_control_visible(module),
            self._e621_wiki_search_control_visible(module),
            getattr(module, "current_category", None),
            getattr(module, "current_level2", None),
            selected_name,
            tuple(sorted(getattr(module, "starred_keys", set()))),
            tuple(sorted(getattr(module, "deleted_keys", set()))),
            self._e621_testbench_text(module),
        )

    def _read_e621_event(self) -> dict:
        try:
            module = self._find_module("e621_event")
            if not module:
                return {}
            loaded = self._ensure_e621_loaded(module)
            cache_key = self._e621_event_state_cache_key(module, loaded)
            if self._cached_e621_event_key == cache_key and self._cached_e621_event_state is not None:
                return self._cached_e621_event_state
            selected_name = getattr(module, "_remote_selected_tag", None) or getattr(module, "current_level3", None)
            selected_tag = self._e621_find_tag(module, selected_name) if loaded else None
            visible_tags = self._e621_visible_tags(module) if loaded else []
            tag_limit = 300
            state = {
                "type": "module_state",
                "module_id": "e621_event",
                "data_loaded": loaded,
                "data_path": str(getattr(module, "data_path", "")),
                "search_text": self._e621_effective_search_text(module),
                "view_mode": self._e621_view_mode(module),
                "disable_translation": bool(getattr(module, "disable_translation", False)),
                "disable_wiki_search": bool(getattr(module, "disable_wiki_search", False)),
                "prompt_testbench_visible": self._e621_prompt_testbench_visible(module),
                "translation_control_visible": self._e621_translation_control_visible(module),
                "wiki_search_control_visible": self._e621_wiki_search_control_visible(module),
                "current_category": getattr(module, "current_category", None),
                "current_level2": getattr(module, "current_level2", None),
                "categories": self._e621_categories(module) if loaded else [],
                "folders": self._e621_folders(module) if loaded else [],
                "tags": [self._e621_tag_payload(module, item) for item in visible_tags[:tag_limit]],
                "tag_total": len(visible_tags),
                "tag_limit": tag_limit,
                "starred_total": len(getattr(module, "starred_keys", set())),
                "hidden_total": len(getattr(module, "deleted_keys", set())),
                "hidden_items": sorted(getattr(module, "deleted_keys", set()))[:120],
                "selected": self._e621_tag_payload(module, selected_tag) if selected_tag else None,
                "wiki": self._e621_wiki_payload(module, selected_tag),
                "testbench": self._e621_testbench_text(module),
            }
            self._cached_e621_event_key = cache_key
            self._cached_e621_event_state = state
            return state
        except Exception as e:
            print(f"🌐 Remote: e621_event 상태 읽기 실패 — {e}")
            return {}

    def _broadcast_e621_event_state(self):
        state = self._read_e621_event()
        if state:
            self._broadcast_json(state)

    # --- Ollama Module ---

    def _ollama_supported_models(self) -> list:
        try:
            from modules.ollama_module import SUPPORTED_MODELS
            return list(SUPPORTED_MODELS)
        except Exception:
            return [
                "huihui_ai/qwen3-vl-abliterated:8b-instruct",
                "huihui_ai/qwen3-vl-abliterated:4b-instruct",
            ]

    def _ollama_creativity_options(self) -> list:
        try:
            from modules.ollama_module import CREATIVITY_PROFILES
            return [
                {"value": value, "label": profile.get("label", str(value))}
                for value, profile in sorted(CREATIVITY_PROFILES.items())
            ]
        except Exception:
            return [
                {"value": 0.1, "label": "Conservative"},
                {"value": 0.3, "label": "Restrained"},
                {"value": 0.5, "label": "Default"},
                {"value": 0.7, "label": "Creative"},
                {"value": 0.9, "label": "Bold"},
            ]

    def _probe_ollama_status(self, module, include_install_probe: bool = False):
        try:
            import requests
            response = requests.get("http://localhost:11434/api/tags", timeout=1)
            if response.status_code == 200:
                models_data = response.json().get("models", [])
                module.ollama_installed = True
                module.ollama_server_running = True
                module.available_models = [item.get("name", "") for item in models_data if item.get("name")]
                return
        except Exception:
            pass

        module.ollama_server_running = False
        module.available_models = []
        if include_install_probe:
            try:
                import subprocess
                import sys
                proc = subprocess.run(
                    ["ollama", "--version"],
                    capture_output=True,
                    text=True,
                    timeout=2,
                    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                )
                module.ollama_installed = proc.returncode == 0
            except Exception:
                module.ollama_installed = bool(getattr(module, "ollama_installed", False))

    def _ollama_input_text(self, module) -> str:
        edit = getattr(module, "input_text", None)
        if edit is not None:
            try:
                return edit.toPlainText()
            except Exception:
                pass
        return getattr(module, "_remote_input_text", "")

    def _ollama_output_text(self, module) -> str:
        edit = getattr(module, "output_text", None)
        if edit is not None:
            try:
                return edit.toPlainText()
            except Exception:
                pass
        return getattr(module, "_remote_output_text", "")

    def _ollama_creativity_value(self, module) -> float:
        combo = getattr(module, "creativity_combo", None)
        if combo is not None:
            try:
                return float(combo.currentData())
            except Exception:
                pass
        return float(getattr(module, "_remote_creativity", 0.5))

    def _read_ollama(self) -> dict:
        try:
            module = self._find_module("ollama")
            if not module:
                return {}
            if not getattr(module, "_remote_ollama_state_initialized", False):
                self._probe_ollama_status(module, include_install_probe=True)
                module._remote_ollama_state_initialized = True
            worker = getattr(module, "worker", None)
            is_running = bool(worker and worker.isRunning())
            return {
                "type": "module_state",
                "module_id": "ollama",
                "installed": bool(getattr(module, "ollama_installed", False)),
                "server_running": bool(getattr(module, "ollama_server_running", False)),
                "available_models": list(getattr(module, "available_models", [])),
                "supported_models": self._ollama_supported_models(),
                "selected_model": getattr(module, "selected_model", ""),
                "load_model": bool(module.load_checkbox.isChecked()) if getattr(module, "load_checkbox", None) else bool(getattr(module, "_remote_load_model", False)),
                "auto_offload": bool(module.offload_checkbox.isChecked()) if getattr(module, "offload_checkbox", None) else bool(getattr(module, "_remote_auto_offload", True)),
                "e621_nsfw_boost": bool(module.e621_nsfw_boost_checkbox.isChecked()) if getattr(module, "e621_nsfw_boost_checkbox", None) else bool(getattr(module, "_remote_e621_nsfw_boost", False)),
                "creativity": self._ollama_creativity_value(module),
                "creativity_options": self._ollama_creativity_options(),
                "tag_db_loaded": bool(getattr(module.tag_db, "is_loaded", False)),
                "tag_count": module.tag_db.tag_count() if getattr(module.tag_db, "is_loaded", False) else 0,
                "input": self._ollama_input_text(module),
                "output": self._ollama_output_text(module),
                "status": getattr(module, "_remote_status_text", "") or (
                    module.status_label.text() if getattr(module, "status_label", None) else ""
                ),
                "progress": int(getattr(module, "_remote_progress", 0)),
                "is_running": is_running,
                "stages": list(getattr(module, "_remote_stage_outputs", []))[-20:],
            }
        except Exception as e:
            print(f"🌐 Remote: ollama 상태 읽기 실패 — {e}")
            return {}

    def _broadcast_ollama_state(self):
        state = self._read_ollama()
        if state:
            self._broadcast_json(state)

    def _on_remote_ollama_status(self, module, status: str):
        module._remote_status_text = status
        self._broadcast_ollama_state()

    def _on_remote_ollama_progress(self, module, percent: int):
        module._remote_progress = int(percent)
        self._broadcast_ollama_state()

    def _on_remote_ollama_stage(self, module, stage_name: str, content: str, color: str):
        stages = list(getattr(module, "_remote_stage_outputs", []))
        stages.append({"stage": stage_name, "content": content, "color": color})
        module._remote_stage_outputs = stages[-20:]
        self._broadcast_ollama_state()

    def _on_remote_ollama_complete(self, module, result: dict):
        combined = result.get("combined_prompt", "")
        module._remote_output_text = combined
        module._remote_status_text = "Conversion complete"
        module._remote_progress = 100
        if getattr(module, "output_text", None) is not None:
            module.output_text.setPlainText(combined)
        if getattr(module, "copy_btn", None) is not None:
            module.copy_btn.setEnabled(bool(combined))
        self._broadcast_ollama_state()

    def _on_remote_ollama_failed(self, module, error: str):
        module._remote_status_text = f"Conversion failed: {error}"
        self._broadcast_json({"type": "toast", "message": module._remote_status_text, "level": "error"})
        self._broadcast_ollama_state()

    def _on_remote_ollama_finished(self, module):
        worker = getattr(module, "worker", None)
        if worker:
            worker.deleteLater()
            module.worker = None
        self._probe_ollama_status(module, include_install_probe=False)
        self._broadcast_ollama_state()

    def _on_remote_ollama_server_action_complete(self, module, success: bool):
        module._server_action_worker = None
        self._probe_ollama_status(module, include_install_probe=True)
        module._remote_status_text = "Ollama server action complete" if success else "Ollama server action failed"
        self._broadcast_ollama_state()

    def _set_ollama(self, key: str, value: str):
        try:
            module = self._find_module("ollama")
            if not module:
                return
            should_broadcast = True

            if key == "refresh":
                self._probe_ollama_status(module, include_install_probe=True)
                if not getattr(module.tag_db, "is_loaded", False):
                    try:
                        module.tag_db.load()
                    except Exception as e:
                        print(f"🌐 Remote: Ollama tag DB load 실패 — {e}")
            elif key == "model":
                module.selected_model = value
                if getattr(module, "model_combo", None) is not None:
                    idx = module.model_combo.findText(value)
                    if idx >= 0:
                        module.model_combo.setCurrentIndex(idx)
            elif key == "auto_offload":
                checked = value == "true"
                module._remote_auto_offload = checked
                if getattr(module, "offload_checkbox", None) is not None:
                    module.offload_checkbox.setChecked(checked)
            elif key == "e621_nsfw_boost":
                checked = value == "true"
                module._remote_e621_nsfw_boost = checked
                if getattr(module, "e621_nsfw_boost_checkbox", None) is not None:
                    module.e621_nsfw_boost_checkbox.setChecked(checked)
            elif key == "creativity":
                creativity = float(value)
                module._remote_creativity = creativity
                if getattr(module, "creativity_combo", None) is not None:
                    for idx in range(module.creativity_combo.count()):
                        if float(module.creativity_combo.itemData(idx)) == creativity:
                            module.creativity_combo.setCurrentIndex(idx)
                            break
            elif key == "input":
                module._remote_input_text = value
                if getattr(module, "input_text", None) is not None:
                    module.input_text.setPlainText(value)
                should_broadcast = False
            elif key == "server_action":
                if value not in ("start", "stop"):
                    return
                active = getattr(module, "_server_action_worker", None)
                if active and active.isRunning():
                    self._broadcast_json({"type": "toast", "message": "Ollama server action is already running", "level": "error"})
                    return
                from modules.ollama_module import OllamaServerActionWorker
                module._remote_status_text = "Starting Ollama server..." if value == "start" else "Stopping Ollama server..."
                self._broadcast_ollama_state()
                worker = OllamaServerActionWorker(action=value)
                module._server_action_worker = worker
                worker.action_completed.connect(lambda success, m=module: self._on_remote_ollama_server_action_complete(m, success))
                worker.finished.connect(worker.deleteLater)
                worker.start()
            elif key == "load_model":
                checked = value == "true"
                module._remote_load_model = checked
                if getattr(module, "load_checkbox", None) is not None:
                    module.load_checkbox.setChecked(checked)
                elif checked:
                    import requests
                    requests.post(
                        "http://localhost:11434/api/chat",
                        json={
                            "model": module.selected_model,
                            "messages": [{"role": "user", "content": "test"}],
                            "stream": False,
                            "keep_alive": -1,
                        },
                        timeout=120,
                    )
                else:
                    import requests
                    requests.post(
                        "http://localhost:11434/api/chat",
                        json={
                            "model": module.selected_model,
                            "messages": [{"role": "user", "content": ""}],
                            "stream": False,
                            "keep_alive": 0,
                        },
                        timeout=10,
                    )
            elif key == "convert":
                prompt = value.strip() or self._ollama_input_text(module).strip()
                if not prompt:
                    self._broadcast_json({"type": "toast", "message": "Ollama prompt is empty", "level": "error"})
                    return
                worker = getattr(module, "worker", None)
                if worker and worker.isRunning():
                    self._broadcast_json({"type": "toast", "message": "Ollama conversion is already running", "level": "error"})
                    return
                if not getattr(module.tag_db, "is_loaded", False):
                    module.tag_db.load()
                module._remote_input_text = prompt
                module._remote_output_text = ""
                module._remote_progress = 0
                module._remote_stage_outputs = []
                if getattr(module, "input_text", None) is not None:
                    module.input_text.setPlainText(prompt)
                from modules.ollama_module import OllamaConversionWorker
                worker = OllamaConversionWorker(
                    prompt=prompt,
                    model=getattr(module, "selected_model", self._ollama_supported_models()[0]),
                    tag_db=module.tag_db,
                    auto_offload=bool(module.offload_checkbox.isChecked()) if getattr(module, "offload_checkbox", None) else bool(getattr(module, "_remote_auto_offload", True)),
                    e621_nsfw_boost=bool(module.e621_nsfw_boost_checkbox.isChecked()) if getattr(module, "e621_nsfw_boost_checkbox", None) else bool(getattr(module, "_remote_e621_nsfw_boost", False)),
                    creativity=self._ollama_creativity_value(module),
                )
                module.worker = worker
                worker.conversion_completed.connect(lambda result, m=module: self._on_remote_ollama_complete(m, result))
                worker.conversion_failed.connect(lambda error, m=module: self._on_remote_ollama_failed(m, error))
                worker.status_changed.connect(lambda status, m=module: self._on_remote_ollama_status(m, status))
                worker.progress_updated.connect(lambda percent, m=module: self._on_remote_ollama_progress(m, percent))
                worker.stage_output.connect(lambda stage, content, color, m=module: self._on_remote_ollama_stage(m, stage, content, color))
                worker.finished.connect(lambda m=module: self._on_remote_ollama_finished(m))
                worker.start()
            elif key == "cancel":
                worker = getattr(module, "worker", None)
                if worker and worker.isRunning():
                    worker.cancel()
                    worker.quit()
            elif key == "copy_output":
                output = self._ollama_output_text(module).strip()
                if output:
                    from PyQt6.QtWidgets import QApplication
                    QApplication.clipboard().setText(output)
                    self._broadcast_json({"type": "toast", "message": "Ollama output copied", "level": "success"})
            else:
                should_broadcast = False

            if should_broadcast:
                self._broadcast_ollama_state()
        except Exception as e:
            print(f"🌐 Remote: ollama 설정 실패 — {key}={value}: {e}")
            self._broadcast_json({"type": "toast", "message": f"Ollama action failed: {e}", "level": "error"})

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
        elif module_id == "event_stream":
            self._set_event_stream(key, value)
        elif module_id == "webui_hiresfix_assist":
            self._set_webui_hiresfix_assist(key, value)
        elif module_id == "character_reference":
            self._set_character_reference(key, value)
        elif module_id == "vibe_transfer":
            self._set_vibe_transfer(key, value)
        elif module_id == "img2img":
            self._set_img2img(key, value)
        elif module_id == "save_directory":
            self._set_save_directory(key, value)
        elif module_id == "wildcard":
            self._set_wildcard(key, value)
        elif module_id == "instant_wildcard":
            self._set_instant_wildcard(key, value)
        elif module_id == "e621_event":
            self._set_e621_event(key, value)
        elif module_id == "ollama":
            self._set_ollama(key, value)

    def _set_event_stream(self, key: str, value: str):
        try:
            runtime = getattr(self.app_context, "event_stream_runtime", None)
            if not runtime:
                self._broadcast_json({
                    "type": "toast",
                    "message": "Event Stream runtime is not available.",
                    "level": "error",
                })
                return

            if key == "active":
                enabled = self._coerce_bool(value)
                if enabled and not runtime.is_active:
                    runtime.start_linear()
                    self._broadcast_json({
                        "type": "toast",
                        "message": "이벤트 스트림 활성화",
                        "level": "success",
                    })
                elif not enabled and runtime.is_active:
                    runtime.stop()
                    self._broadcast_json({
                        "type": "toast",
                        "message": "이벤트 스트림 비활성화",
                        "level": "success",
                    })
            elif key == "restart":
                runtime.start_linear()
                self._broadcast_json({
                    "type": "toast",
                    "message": "이벤트 스트림을 기본 노드 시퀀스로 재시작했습니다.",
                    "level": "success",
                })
            else:
                return

            self._broadcast_event_stream_state()
        except Exception as e:
            print(f"🌐 Remote: event_stream 설정 실패 — {key}={value}: {e}")
            self._broadcast_json({"type": "toast", "message": f"이벤트 스트림 설정 실패: {e}", "level": "error"})

    def _set_webui_hiresfix_assist(self, key: str, value: str):
        try:
            state = self._normalize_webui_hiresfix_assist_state(
                getattr(self, "_webui_hiresfix_assist", None)
            )
            if key == "enabled":
                state["enabled"] = self._coerce_bool(value)
            elif key == "target":
                try:
                    state["target"] = 768 if int(float(value)) == 768 else 512
                except (TypeError, ValueError):
                    state["target"] = 512
            else:
                return
            updates = {"webui_hiresfix_assist": state}
            should_broadcast_params = False
            if key == "enabled" and state.get("enabled"):
                ui_state = self._normalize_remote_web_ui_state(
                    getattr(self, "_remote_web_ui_state", None)
                )
                preset_map = ui_state["resolution_preset"]
                webui_preset = self._normalize_resolution_preset_state(
                    preset_map.get("WEBUI")
                )
                if webui_preset.get("enabled"):
                    webui_preset["enabled"] = False
                    preset_map["WEBUI"] = webui_preset
                    updates["resolution_preset"] = preset_map
                    should_broadcast_params = True
            self._webui_hiresfix_assist = state
            self._save_remote_web_ui_state(**updates)
            self._broadcast_webui_hiresfix_assist_state()
            if should_broadcast_params:
                self._broadcast_params()
        except Exception as e:
            print(f"🌐 Remote: webui_hiresfix_assist 설정 실패 — {key}={value}: {e}")

    def _set_auto_save_settings(self, key: str, value: str):
        try:
            image_window = self._get_image_window_widget()
            if not image_window:
                return

            if key == "save_as_webp":
                checkbox = self._get_save_as_webp_checkbox()
                if checkbox and checkbox.isChecked() != (value == "true"):
                    self._syncing_option = True
                    try:
                        checkbox.setChecked(value == "true")
                    finally:
                        self._syncing_option = False
            elif key == "auto_save":
                checkbox = self._get_auto_save_checkbox()
                enabled = self._coerce_bool(value)
                if checkbox and checkbox.isChecked() != enabled:
                    self._syncing_option = True
                    try:
                        checkbox.setChecked(enabled)
                    finally:
                        self._syncing_option = False
            elif key == "history_limit_enabled":
                checkbox, _, _ = self._get_history_limit_widgets()
                if checkbox and checkbox.isChecked() != (value == "true"):
                    self._syncing_option = True
                    try:
                        checkbox.setChecked(value == "true")
                    finally:
                        self._syncing_option = False
            elif key == "max_history_length":
                _, spinbox, _ = self._get_history_limit_widgets()
                if spinbox:
                    new_value = max(spinbox.minimum(), min(spinbox.maximum(), int(value)))
                    if spinbox.value() != new_value:
                        self._syncing_option = True
                        try:
                            spinbox.setValue(new_value)
                        finally:
                            self._syncing_option = False
                    else:
                        image_window.save_memory_settings()
            elif key == "memory_action":
                _, _, action_group = self._get_history_limit_widgets()
                if action_group:
                    action_id = int(value)
                    button = action_group.button(action_id)
                    if button and not button.isChecked():
                        self._syncing_option = True
                        try:
                            button.setChecked(True)
                        finally:
                            self._syncing_option = False
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
                raw_path = value.strip()
                if not raw_path:
                    self._broadcast_json({
                        "type": "toast",
                        "message": "저장 경로를 입력해주세요.",
                        "level": "error",
                    })
                    return
                new_path = str(Path(raw_path).expanduser())
                image_crud.set_base_save_directory(new_path)
                self._persist_base_save_directory_setting(new_path)
                self._broadcast_json({
                    "type": "toast",
                    "message": f"저장 경로 변경: {new_path}",
                    "level": "success",
                })
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
                ok, result = m.create_and_apply_recommended_preset()
                if ok:
                    self._broadcast_json({"type": "toast", "message": f"추천 프리셋 적용: {result}", "level": "success"})
                    self._broadcast_prompt_engineering_state()
                    self._broadcast_params()
                    self._broadcast_prompts()
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
            elif key == "randomized_add":
                if not hasattr(m, "add_randomized_preset"):
                    self._broadcast_json({"type": "toast", "message": "랜덤 프리셋 관리를 사용할 수 없습니다.", "level": "error"})
                    return
                ok, result = m.add_randomized_preset(value)
                if ok:
                    self._broadcast_prompt_engineering_state()
                else:
                    self._broadcast_json({"type": "toast", "message": result, "level": "error"})
            elif key == "randomized_remove":
                if not hasattr(m, "remove_randomized_preset"):
                    self._broadcast_json({"type": "toast", "message": "랜덤 프리셋 관리를 사용할 수 없습니다.", "level": "error"})
                    return
                ok, result = m.remove_randomized_preset(value)
                if ok:
                    self._broadcast_prompt_engineering_state()
                else:
                    self._broadcast_json({"type": "toast", "message": result, "level": "error"})
            elif key == "randomized_clear":
                if not hasattr(m, "clear_randomized_presets"):
                    self._broadcast_json({"type": "toast", "message": "랜덤 프리셋 관리를 사용할 수 없습니다.", "level": "error"})
                    return
                ok, result = m.clear_randomized_presets()
                if ok:
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
                    if hasattr(m, "set_character_slot_state"):
                        m.set_character_slot_state(idx, "active" if has_character else "inactive")
                    else:
                        widget.slot_state = "active" if has_character else "inactive"
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
                    state = "active" if value == "true" else "inactive"
                    if hasattr(m, "set_character_slot_state"):
                        m.set_character_slot_state(idx, state)
                    else:
                        m.character_widgets[idx].slot_state = state
                        m.character_widgets[idx].active_checkbox.setChecked(value == "true")
                    if hasattr(m, "process_and_update_view"):
                        m.process_and_update_view()
            elif key.startswith("char_slot_name_"):
                idx = int(key.split("_")[-1])
                if idx < len(m.character_widgets):
                    if hasattr(m, "set_character_custom_name"):
                        m.set_character_custom_name(idx, value)
                    else:
                        m.character_widgets[idx].custom_name = str(value or "").strip()
                    self._broadcast_character_state()
            elif key.startswith("char_slot_state_"):
                idx = int(key.split("_")[-1])
                if idx < len(m.character_widgets):
                    if hasattr(m, "set_character_slot_state"):
                        m.set_character_slot_state(idx, value)
                    else:
                        widget = m.character_widgets[idx]
                        requested = str(value or "").strip().lower()
                        if requested == "restore":
                            requested = str(getattr(widget, "return_slot_state", "") or "inactive").strip().lower()
                        normalized = requested if requested in {"active", "inactive", "cold"} else "inactive"
                        if normalized == "cold":
                            widget.return_slot_state = "active" if widget.active_checkbox.isChecked() else "inactive"
                        else:
                            widget.return_slot_state = normalized
                        widget.slot_state = normalized
                        widget.active_checkbox.setChecked(normalized == "active")
                    if hasattr(m, "process_and_update_view"):
                        m.process_and_update_view()
                    self._broadcast_character_state()
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
            should_broadcast = False
            if key == "enabled":
                m.enable_checkbox.setChecked(value == "true")
                should_broadcast = True
            elif key in ("editor_mode", "mode"):
                if value in ("legacy", "v2"):
                    if hasattr(m, "set_editor_mode"):
                        m.set_editor_mode(value)
                    else:
                        m._editor_mode = value
                    should_broadcast = True
            elif key == "rules_legacy":
                if getattr(m, "rules_textedit", None) is not None:
                    m.rules_textedit.setPlainText(value)
            elif key == "rules_v2":
                if hasattr(m, "set_v2_dsl"):
                    m.set_v2_dsl(value)
                elif getattr(m, "rules_textedit", None) is not None:
                    m.rules_textedit.setPlainText(value)
            elif key == "rules_v2_book":
                from modules.conditional.dsl_serializer import serialize_rulebook

                book, data = self._cond_book_from_json_value(value)
                opts = self._cond_engine_options(source=data.get("engine_options") or {})
                book.max_passes = opts["max_passes"]
                book.stop_on_match = opts["stop_on_match"]
                dsl = serialize_rulebook(book)
                if hasattr(m, "set_v2_dsl"):
                    m.set_v2_dsl(dsl)
                elif getattr(m, "rules_textedit", None) is not None:
                    m.rules_textedit.setPlainText(dsl)
                if hasattr(m, "set_engine_options"):
                    m.set_engine_options(
                        max_passes=opts["max_passes"],
                        stop_on_match=opts["stop_on_match"],
                    )
                else:
                    m._engine_options = opts
                if hasattr(m, "set_editor_mode"):
                    m.set_editor_mode("v2")
                else:
                    m._editor_mode = "v2"
            elif key == "rules":
                mode = m.get_editor_mode() if hasattr(m, "get_editor_mode") else getattr(m, "_editor_mode", "legacy")
                if mode == "v2" and hasattr(m, "set_v2_dsl"):
                    m.set_v2_dsl(value)
                elif getattr(m, "rules_textedit", None) is not None:
                    m.rules_textedit.setPlainText(value)
            elif key in ("engine_options", "max_passes", "stop_on_match"):
                opts = self._cond_engine_options(m)
                if key == "engine_options":
                    try:
                        opts = self._cond_engine_options(source=json.loads(value or "{}"))
                    except Exception:
                        opts = self._cond_engine_options(source={})
                elif key == "max_passes":
                    opts["max_passes"] = value
                    opts = self._cond_engine_options(source=opts)
                elif key == "stop_on_match":
                    opts["stop_on_match"] = value == "true"
                    opts = self._cond_engine_options(source=opts)
                if hasattr(m, "set_engine_options"):
                    m.set_engine_options(
                        max_passes=opts["max_passes"],
                        stop_on_match=opts["stop_on_match"],
                    )
                else:
                    m._engine_options = opts
                should_broadcast = True
            elif key == "preset_load":
                loaded = False
                if hasattr(m, "load_preset_by_name"):
                    loaded = bool(m.load_preset_by_name(value))
                if loaded:
                    should_broadcast = True
                    self._broadcast_json({
                        "type": "toast",
                        "message": f"조건부 프리셋 로드: {value}",
                        "level": "success",
                    })
                else:
                    self._broadcast_json({
                        "type": "toast",
                        "message": f"조건부 프리셋을 찾을 수 없습니다: {value}",
                        "level": "error",
                    })
            elif key == "preset_save":
                from modules.conditional.preset_io import (
                    get_default_storage,
                    rulebook_from_dict,
                )

                payload = json.loads(value or "{}")
                if isinstance(payload, str):
                    payload = {"name": payload}
                if not isinstance(payload, dict):
                    payload = {}
                name = str(payload.get("name") or "").strip()
                source_preset = str(payload.get("source_preset") or "").strip()
                activate_raw = payload.get("activate", False)
                activate = activate_raw is True or (
                    isinstance(activate_raw, str)
                    and activate_raw.strip().lower() == "true"
                )
                book_data = payload.get("book") if isinstance(payload.get("book"), dict) else None
                if not name:
                    self._broadcast_json({
                        "type": "toast",
                        "message": "조건부 프리셋 이름이 비어 있습니다.",
                        "level": "error",
                    })
                else:
                    storage = get_default_storage()
                    bundled_name = any(
                        info.name == name and info.is_bundled
                        for info in storage.list_all()
                    )
                    if bundled_name:
                        self._broadcast_json({
                            "type": "toast",
                            "message": "번들 프리셋과 같은 이름으로 저장할 수 없습니다.",
                            "level": "error",
                        })
                    else:
                        book = None
                        try:
                            if book_data is not None:
                                book = rulebook_from_dict(book_data)
                            elif source_preset:
                                book = storage.load(source_preset)
                            else:
                                from modules.conditional.dsl_parser import parse_rulebook

                                current_dsl = m.get_v2_dsl() if hasattr(m, "get_v2_dsl") else getattr(m, "_rules_v2_dsl", "")
                                book = parse_rulebook(current_dsl or "")
                                opts = self._cond_engine_options(m)
                                book.max_passes = opts["max_passes"]
                                book.stop_on_match = opts["stop_on_match"]
                        except FileNotFoundError:
                            self._broadcast_json({
                                "type": "toast",
                                "message": f"복제할 조건부 프리셋을 찾을 수 없습니다: {source_preset}",
                                "level": "error",
                            })
                        if book is not None:
                            storage.save(name, book)
                            m._active_preset_name = name
                            if activate:
                                from modules.conditional.dsl_serializer import serialize_rulebook

                                dsl = serialize_rulebook(book)
                                if hasattr(m, "set_engine_options"):
                                    m.set_engine_options(
                                        max_passes=book.max_passes,
                                        stop_on_match=book.stop_on_match,
                                    )
                                else:
                                    m._engine_options = {
                                        "max_passes": book.max_passes,
                                        "stop_on_match": book.stop_on_match,
                                    }
                                if hasattr(m, "set_v2_dsl"):
                                    m.set_v2_dsl(dsl)
                                else:
                                    m._rules_v2_dsl = dsl
                                if hasattr(m, "set_editor_mode"):
                                    m.set_editor_mode("v2")
                                else:
                                    m._editor_mode = "v2"
                            should_broadcast = True
                            self._broadcast_json({
                                "type": "toast",
                                "message": f"조건부 프리셋 저장: {name}",
                                "level": "success",
                            })
            elif key == "preset_delete":
                from modules.conditional.preset_io import get_default_storage

                name = str(value or "").strip()
                if name and get_default_storage().delete(name):
                    if getattr(m, "_active_preset_name", None) == name:
                        m._active_preset_name = None
                    should_broadcast = True
                    self._broadcast_json({
                        "type": "toast",
                        "message": f"조건부 프리셋 삭제: {name}",
                        "level": "success",
                    })
                else:
                    self._broadcast_json({
                        "type": "toast",
                        "message": f"삭제할 사용자 프리셋을 찾을 수 없습니다: {name}",
                        "level": "error",
                    })
            elif key == "simulate_v2":
                from dataclasses import asdict
                from modules.conditional.dsl_serializer import serialize_rulebook

                book, data = self._cond_book_from_json_value(value)
                opts = self._cond_engine_options(source=data.get("engine_options") or {})
                book.max_passes = opts["max_passes"]
                book.stop_on_match = opts["stop_on_match"]
                dsl = serialize_rulebook(book)
                if hasattr(m, "simulate_for_preview"):
                    result = m.simulate_for_preview(rules_text=dsl)
                else:
                    result = {
                        "ok": False,
                        "error": "현재 조건부 프롬프트 모듈이 시뮬레이션을 지원하지 않습니다.",
                    }
                state = self._read_conditional_prompt()
                if state:
                    try:
                        schema_version = int(data.get("schema_version", 1))
                    except Exception:
                        schema_version = 1
                    state_book = {
                        "schema_version": schema_version,
                        "name": str(data.get("name") or ""),
                        "description": str(data.get("description") or ""),
                        "engine_options": opts,
                        "rules": [asdict(rule) for rule in book.rules],
                    }
                    state.update({
                        "editor_mode": "v2",
                        "rules": dsl,
                        "active_rules": dsl,
                        "rules_v2": dsl,
                        "rules_v2_book": state_book,
                        "engine_options": opts,
                        "local_dirty": True,
                    })
                    state["simulation"] = result
                    self._broadcast_json(state)
            elif key == "test":
                # test_rules()를 직접 호출 (test_button은 로컬 변수)
                if hasattr(m, 'test_rules'):
                    m.test_rules()
                # 테스트 완료 후 로그 갱신 브로드캐스트
                should_broadcast = True
            if should_broadcast:
                state = self._read_conditional_prompt()
                if state:
                    self._broadcast_json(state)
        except Exception as e:
            print(f"🌐 Remote: conditional_prompt 설정 실패 — {key}={value}: {e}")

    def _set_e621_event(self, key: str, value: str):
        try:
            m = self._find_module("e621_event")
            if not m:
                return
            self._ensure_e621_loaded(m)
            should_broadcast = True

            if key == "search":
                search_text = value.strip()
                if getattr(m, "search_input", None) is not None:
                    m.search_input.setText(search_text)
                self._e621_update_search_index(m, search_text)
                m.current_category = None
                m.current_level2 = None
                m.current_level3 = None
                m._remote_selected_tag = None
            elif key == "reset":
                if getattr(m, "widget", None) is not None and hasattr(m, "on_reset"):
                    try:
                        m.on_reset()
                    except Exception:
                        pass
                m.current_category = None
                m.current_level2 = None
                m.current_level3 = None
                m._remote_selected_tag = None
                m._remote_search_text = ""
                m.is_searching = False
                m.searched_tree = {}
            elif key == "view_mode":
                mode = "starred" if value == "starred" else "default"
                m._remote_view_mode = mode
                if getattr(m, "radio_starred", None) is not None and getattr(m, "radio_default", None) is not None:
                    if mode == "starred":
                        m.radio_starred.setChecked(True)
                    else:
                        m.radio_default.setChecked(True)
            elif key == "category":
                category = value or None
                m.current_category = category
                m.current_level2 = None
                m.current_level3 = None
                m._remote_selected_tag = None
                if category and getattr(m, "category_buttons", None):
                    button = m.category_buttons.get(category)
                    if button is not None:
                        try:
                            button.setChecked(True)
                        except Exception:
                            pass
            elif key == "level2":
                m.current_level2 = value or None
                m.current_level3 = None
                m._remote_selected_tag = None
            elif key == "selected_tag":
                tag_name = value or None
                m.current_level3 = tag_name
                m._remote_selected_tag = tag_name
                if tag_name and getattr(m, "level3_list", None) is not None:
                    try:
                        for row in range(m.level3_list.count()):
                            item = m.level3_list.item(row)
                            tag_data = item.data(Qt.ItemDataRole.UserRole)
                            if tag_data and tag_data.get("tag", "") == tag_name:
                                m.level3_list.setCurrentItem(item)
                                m.on_level3_clicked(item)
                                break
                    except Exception:
                        pass
            elif key == "toggle_star":
                tag_name = value.strip()
                if tag_name:
                    if tag_name in m.starred_keys:
                        m.starred_keys.discard(tag_name)
                    else:
                        m.starred_keys.add(tag_name)
                    m.save_starred_keys()
                    m.current_level3 = tag_name
                    m._remote_selected_tag = tag_name
                    if hasattr(m, "update_category_starred_labels"):
                        try:
                            m.update_category_starred_labels()
                        except Exception:
                            pass
            elif key == "hide":
                tag_name = value.strip()
                if tag_name:
                    m.deleted_keys.add(tag_name)
                    m.save_deleted_keys()
                    m.current_level3 = None
                    m._remote_selected_tag = None
            elif key == "restore":
                tag_name = value.strip()
                if tag_name:
                    m.deleted_keys.discard(tag_name)
                    m.save_deleted_keys()
            elif key == "disable_translation":
                m.disable_translation = (value == "true")
                if getattr(m, "disable_translation_checkbox", None) is not None:
                    m.disable_translation_checkbox.setChecked(m.disable_translation)
                m.save_settings()
            elif key == "disable_wiki_search":
                m.disable_wiki_search = (value == "true")
                if getattr(m, "disable_wiki_search_checkbox", None) is not None:
                    m.disable_wiki_search_checkbox.setChecked(m.disable_wiki_search)
                m.save_settings()
                if getattr(m, "_remote_search_text", ""):
                    self._e621_update_search_index(m, m._remote_search_text)
            elif key == "testbench":
                m._remote_testbench_text = value
                if getattr(m, "related_tags_edit", None) is not None:
                    m.related_tags_edit.setPlainText(value)
            elif key == "generate":
                prompt = value.strip() or self._e621_testbench_text(m)
                tags = [tag.strip() for tag in prompt.split(",") if tag.strip()]
                if not tags:
                    self._broadcast_json({
                        "type": "toast",
                        "message": "E621 testbench is empty",
                        "level": "error",
                    })
                    return
                m._remote_testbench_text = prompt
                if getattr(m, "related_tags_edit", None) is not None:
                    m.related_tags_edit.setPlainText(prompt)
                tags_data = {
                    "id": 10000000,
                    "artist": [],
                    "copyright": [],
                    "character": [],
                    "general": tags,
                    "meta": [],
                }
                if hasattr(m, "signals") and hasattr(m.signals, "generation_requested"):
                    m.signals.generation_requested.emit(tags_data)
                self._broadcast_json({
                    "type": "toast",
                    "message": f"E621 generation requested ({len(tags)} tags)",
                    "level": "success",
                })
            else:
                should_broadcast = False

            if should_broadcast:
                self._broadcast_e621_event_state()
        except Exception as e:
            print(f"🌐 Remote: e621_event 설정 실패 — {key}={value}: {e}")

    # --- Character Reference / Vibe Transfer (이미지 업로드 모듈) ---

    def _thumbnail_cache_key(self, frame, pil_image, max_side: int) -> tuple:
        size = getattr(pil_image, "size", None)
        return (
            max_side,
            getattr(frame, "file_hash", "") or "",
            getattr(frame, "file_name", "") or "",
            id(pil_image),
            size,
            getattr(pil_image, "mode", ""),
        )

    def _generate_thumbnail_b64(self, pil_image, max_side=128, cache_key=None) -> str:
        """PIL 이미지를 작은 JPEG 썸네일 base64로 변환"""
        if cache_key is not None and cache_key in self._thumbnail_b64_cache:
            return self._thumbnail_b64_cache[cache_key]
        from PIL import Image
        thumb = pil_image.copy()
        thumb.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
        if thumb.mode == 'RGBA':
            thumb = thumb.convert('RGB')
        buf = io.BytesIO()
        thumb.save(buf, format="JPEG", quality=70)
        encoded = base64.b64encode(buf.getvalue()).decode()
        if cache_key is not None:
            if len(self._thumbnail_b64_cache) > 512:
                self._thumbnail_b64_cache.clear()
            self._thumbnail_b64_cache[cache_key] = encoded
        return encoded

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
                        thumb = self._generate_thumbnail_b64(
                            f.image,
                            cache_key=self._thumbnail_cache_key(f, f.image, 128),
                        )
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
            encoding_worker = getattr(m, "encoding_worker", None)
            encoding_target = getattr(m, "_encoding_target_frame", None)
            enabled_count = 0
            enabled_strength_total = 0.0
            for i, f in enumerate(m.vibe_frames):
                thumb = ""
                try:
                    if hasattr(f, 'image') and f.image and not f.is_no_image:
                        thumb = self._generate_thumbnail_b64(
                            f.image,
                            cache_key=self._thumbnail_cache_key(f, f.image, 128),
                        )
                except Exception:
                    pass
                encoding_keys = sorted(float(k) for k in getattr(f, 'vibe_encodings', {}).keys())
                information_extracted = float(getattr(f, 'information_extracted', 1.0))
                active_encoding = None
                has_encoding = False
                if encoding_keys:
                    active_encoding = min(encoding_keys, key=lambda key: abs(key - information_extracted))
                    has_encoding = abs(active_encoding - information_extracted) < 1e-9
                is_encoding = bool(encoding_worker and encoding_worker.isRunning() and encoding_target is f)
                if f.is_enabled and getattr(f, 'vibe_encodings', None):
                    enabled_count += 1
                    try:
                        enabled_strength_total += float(f.reference_strength)
                    except Exception:
                        pass
                frames.append({
                    "index": i,
                    "file_hash": f.file_hash,
                    "file_name": f.file_name,
                    "is_enabled": f.is_enabled,
                    "is_no_image": f.is_no_image,
                    "is_naid3": bool(getattr(f, 'is_naid3', False)),
                    "reference_strength": f.reference_strength,
                    "information_extracted": information_extracted,
                    "has_encoding": has_encoding,
                    "active_encoding": active_encoding,
                    "encoding_in_progress": is_encoding,
                    "encoding_keys": encoding_keys,
                    "thumbnail": thumb,
                })
            return {
                "type": "module_state",
                "module_id": "vibe_transfer",
                "normalize": m.normalize_checkbox.isChecked() if hasattr(m, 'normalize_checkbox') else False,
                "enabled_count": enabled_count,
                "frame_count": len(m.vibe_frames),
                "max_frames": MAX_NAI_VIBE_REFERENCES,
                "included_frames": NAI_VIBE_INCLUDED_REFERENCES,
                "extra_cost_count": max(0, enabled_count - NAI_VIBE_INCLUDED_REFERENCES),
                "strength_total": round(enabled_strength_total, 3),
                "strength_warning": (
                    enabled_count > 1
                    and enabled_strength_total > 1.0
                    and not (m.normalize_checkbox.isChecked() if hasattr(m, 'normalize_checkbox') else False)
                ),
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

            def _set_frame_information_extracted(frame, raw_value):
                information_extracted = max(0.01, min(1.0, round(float(raw_value), 2)))
                frame.information_extracted = information_extracted
                slider = getattr(frame, 'info_extracted_slider', None)
                if slider is not None:
                    slider.setValue(int(round(information_extracted * 100)))
                label = getattr(frame, 'info_extracted_label', None)
                if label is not None:
                    label.setText(f"Information Extracted {information_extracted:.2f}")
                if hasattr(frame, '_update_encoding_status'):
                    frame._update_encoding_status()
                if hasattr(frame, '_update_encode_button_visibility'):
                    frame._update_encode_button_visibility()
                return information_extracted

            def _vibe_capacity_full():
                return len(getattr(m, "vibe_frames", []) or []) >= MAX_NAI_VIBE_REFERENCES

            def _broadcast_vibe_capacity_error():
                self._broadcast_json({
                    "type": "toast",
                    "message": f"Maximum {MAX_NAI_VIBE_REFERENCES} Vibe Transfer frames allowed",
                    "level": "error",
                })

            if key == "upload_image":
                if _vibe_capacity_full():
                    _broadcast_vibe_capacity_error()
                else:
                    img_bytes = base64.b64decode(value)
                    temp_dir = Path("temp/remote_upload")
                    temp_dir.mkdir(parents=True, exist_ok=True)
                    temp_path = temp_dir / f"vibe_{int(time.time() * 1000)}.png"
                    temp_path.write_bytes(img_bytes)
                    m._add_vibe_frame(str(temp_path))
                    self._disable_all_char_ref_frames()
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
                    _set_frame_information_extracted(m.vibe_frames[idx], value)
            elif key == "normalize":
                if hasattr(m, 'normalize_checkbox'):
                    m.normalize_checkbox.setChecked(value == "true")
            elif key.startswith("encode_"):
                idx = int(key.split("_")[-1])
                if 0 <= idx < len(m.vibe_frames):
                    frame = m.vibe_frames[idx]
                    if not frame.is_no_image:
                        if value not in (None, ""):
                            _set_frame_information_extracted(frame, value)
                        m._on_encoding_requested(frame, frame.information_extracted)
            elif key == "get_storage":
                storage = self._scan_vibe_storage()
                self._broadcast_json(storage)
                return
            elif key == "apply_storage":
                # value = "model|file_hash|ie_value"
                parts = value.split("|")
                if _vibe_capacity_full():
                    _broadcast_vibe_capacity_error()
                elif len(parts) >= 3:
                    model, file_hash, ie_str = parts[0], parts[1], parts[2]
                    m._on_apply_vibe_from_storage(model, file_hash, "", float(ie_str))
                    self._disable_all_char_ref_frames()
            elif key == "cluster_list":
                self._broadcast_json(self._scan_vibe_clusters())
                return
            elif key == "cluster_save":
                if self._save_current_vibe_cluster(m, value):
                    listing = self._scan_vibe_clusters()
                    listing["source"] = "cluster_save"
                    self._broadcast_json(listing)
                return
            elif key == "cluster_load":
                self._load_vibe_cluster(m, value)
            elif key == "cluster_delete":
                self._delete_vibe_cluster(value)
                self._broadcast_json(self._scan_vibe_clusters())
                return
            elif key == "cluster_rename":
                self._rename_vibe_cluster(value)
                self._broadcast_json(self._scan_vibe_clusters())
                return
            elif key == "cluster_thumbnail":
                self._update_vibe_cluster_thumbnail(value)
                self._broadcast_json(self._scan_vibe_clusters())
                return
            elif key == "restore_metadata":
                if _vibe_capacity_full():
                    _broadcast_vibe_capacity_error()
                else:
                    self._restore_vibe_transfer_from_metadata(m, value)
            # 변경 후 상태 브로드캐스트
            state = self._read_vibe_transfer()
            if state:
                self._broadcast_json(state)
        except Exception as e:
            print(f"🌐 Remote: vibe_transfer 설정 실패 — {key}{'(image)' if key == 'upload_image' else ''}: {e}")
        finally:
            self.app_context.stealth_mode = prev_stealth

    def _vibe_model_from_source(self, source: str) -> Optional[str]:
        model_map = {
            "NovelAI Diffusion V4.5 4BDE2A90": "NAID4.5F",
            "NovelAI Diffusion V4.5 C02D4F98": "NAID4.5C",
            "NovelAI Diffusion V4 7ABFFA2A": "NAID4.0C",
            "NovelAI Diffusion V4 37442FCA": "NAID4.0F",
        }
        source_text = str(source or "")
        for needle, model_name in model_map.items():
            if needle in source_text:
                return model_name
        return None

    def _current_vibe_model(self, module) -> str:
        getter = getattr(module, "_get_current_model", None)
        if callable(getter):
            return str(getter() or "")
        return ""

    def _vibe_cluster_root(self) -> Path:
        return Path("save/vibe_transfer_clusters")

    def _vibe_cluster_thumb_root(self) -> Path:
        return self._vibe_cluster_root() / "thumbnails"

    def _safe_vibe_cluster_id(self, raw_id: str) -> str:
        text = Path(str(raw_id or "")).name
        safe = re.sub(r"[^A-Za-z0-9_.-]", "", text)
        if safe in {"", ".", ".."}:
            return ""
        return safe

    def _is_valid_vibe_cluster_name(self, name: str) -> bool:
        return is_valid_vibe_cluster_name(name)

    def _broadcast_invalid_vibe_cluster_name(self):
        self._broadcast_json({
            "type": "toast",
            "message": "Vibe cluster name must use letters, numbers, and Korean only",
            "level": "error",
        })

    def _vibe_cluster_json_path(self, raw_id: str) -> Optional[Path]:
        cluster_id = self._safe_vibe_cluster_id(raw_id)
        if not cluster_id:
            return None
        return self._vibe_cluster_root() / f"{cluster_id}.json"

    def _read_vibe_cluster_json(self, raw_id: str) -> Optional[dict]:
        path = self._vibe_cluster_json_path(raw_id)
        if not path or not path.exists():
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else None
        except Exception as e:
            print(f"🌐 Remote: vibe cluster 읽기 실패 — {path}: {e}")
            return None

    def _save_vibe_cluster_thumbnail(self, cluster_id: str, thumbnail_data: str) -> bool:
        if not thumbnail_data:
            return False
        try:
            from PIL import Image

            data_text = str(thumbnail_data)
            if "," in data_text and "base64" in data_text.split(",", 1)[0]:
                data_text = data_text.split(",", 1)[1]
            image_bytes = base64.b64decode(data_text)
            with Image.open(io.BytesIO(image_bytes)) as img:
                img = img.convert("RGB")
                canvas = Image.new("RGB", (512, 512), "black")
                ratio = min(512 / img.width, 512 / img.height)
                new_size = (max(1, int(img.width * ratio)), max(1, int(img.height * ratio)))
                resized = img.resize(new_size, Image.Resampling.LANCZOS)
                pos = ((512 - new_size[0]) // 2, (512 - new_size[1]) // 2)
                canvas.paste(resized, pos)
                thumb_root = self._vibe_cluster_thumb_root()
                thumb_root.mkdir(parents=True, exist_ok=True)
                canvas.save(thumb_root / f"{cluster_id}.png", "PNG")
            return True
        except Exception as e:
            print(f"🌐 Remote: vibe cluster 썸네일 저장 실패 — {cluster_id}: {e}")
            return False

    def _vibe_cluster_thumbnail_b64(self, cluster_id: str) -> str:
        try:
            from PIL import Image

            thumb_path = self._vibe_cluster_thumb_root() / f"{cluster_id}.png"
            if not thumb_path.exists():
                return ""
            with Image.open(thumb_path) as img:
                return self._generate_thumbnail_b64(img, max_side=160)
        except Exception:
            return ""

    def _scan_vibe_clusters(self) -> dict:
        root = self._vibe_cluster_root()
        items = []
        try:
            root.mkdir(parents=True, exist_ok=True)
            for json_file in sorted(root.glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True):
                try:
                    with open(json_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    cluster_id = self._safe_vibe_cluster_id(data.get("id") or json_file.stem)
                    if not cluster_id:
                        continue
                    frames = data.get("frames") if isinstance(data.get("frames"), list) else []
                    enabled_count = sum(1 for frame in frames if frame.get("is_enabled", True))
                    items.append({
                        "id": cluster_id,
                        "name": str(data.get("name") or cluster_id),
                        "description": str(data.get("description") or ""),
                        "created_at": data.get("created_at") or "",
                        "updated_at": data.get("updated_at") or "",
                        "model": data.get("model") or "",
                        "frame_count": len(frames),
                        "enabled_count": enabled_count,
                        "normalize": bool(data.get("normalize_strength", False)),
                        "thumbnail": self._vibe_cluster_thumbnail_b64(cluster_id),
                    })
                except Exception as e:
                    print(f"🌐 Remote: vibe cluster 스캔 항목 실패 — {json_file}: {e}")
        except Exception as e:
            print(f"🌐 Remote: vibe cluster 스캔 실패 — {e}")

        current_count = 0
        try:
            module = self._find_module("vibe_transfer")
            current_count = len(getattr(module, "vibe_frames", []) or [])
        except Exception:
            pass
        return {
            "type": "storage_list",
            "module_id": "vibe_cluster",
            "items": items,
            "current_frame_count": current_count,
            "max_frames": MAX_NAI_VIBE_REFERENCES,
        }

    def _save_current_vibe_cluster(self, module, value: str) -> bool:
        try:
            payload = json.loads(value) if isinstance(value, str) else (value or {})
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}

        name = str(payload.get("name") or "").strip()
        if not self._is_valid_vibe_cluster_name(name):
            self._broadcast_invalid_vibe_cluster_name()
            return False

        root = self._vibe_cluster_root()
        root.mkdir(parents=True, exist_ok=True)
        now = datetime.now().isoformat(timespec="seconds")
        cluster_id = f"{int(time.time() * 1000)}-{uuid.uuid4().hex[:8]}"
        description = str(payload.get("description") or "").strip()
        current_model = self._current_vibe_model(module)
        frames = []

        for frame in getattr(module, "vibe_frames", []) or []:
            encodings = {
                str(float(key)): value
                for key, value in getattr(frame, "vibe_encodings", {}).items()
                if value
            }
            if not encodings:
                continue
            target_model = getattr(frame, "target_model", None) or current_model
            frames.append({
                "encodings": encodings,
                "reference_strength": float(getattr(frame, "reference_strength", 0.6)),
                "information_extracted": float(getattr(frame, "information_extracted", 1.0)),
                "is_enabled": bool(getattr(frame, "is_enabled", True)),
                "is_no_image": bool(getattr(frame, "is_no_image", False)),
                "target_model": target_model,
            })

        if not frames:
            self._broadcast_json({"type": "toast", "message": "No encoded Vibe Transfer frames to save", "level": "error"})
            return False

        data = {
            "id": cluster_id,
            "name": name,
            "description": description,
            "created_at": now,
            "updated_at": now,
            "model": current_model,
            "normalize_strength": bool(
                getattr(getattr(module, "normalize_checkbox", None), "isChecked", lambda: False)()
            ),
            "frames": frames,
        }
        with open(root / f"{cluster_id}.json", "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        self._save_vibe_cluster_thumbnail(cluster_id, payload.get("thumbnail_data") or "")
        self._broadcast_json({"type": "toast", "message": f"Saved Vibe cluster: {name}", "level": "success"})
        return True

    def _delete_vibe_cluster(self, cluster_id: str) -> bool:
        safe_id = self._safe_vibe_cluster_id(cluster_id)
        path = self._vibe_cluster_json_path(safe_id)
        if not safe_id or not path:
            return False
        deleted = False
        if path.exists():
            path.unlink()
            deleted = True
        thumb_path = self._vibe_cluster_thumb_root() / f"{safe_id}.png"
        if thumb_path.exists():
            thumb_path.unlink()
        if deleted:
            self._broadcast_json({"type": "toast", "message": "Deleted Vibe cluster", "level": "success"})
        return deleted

    def _rename_vibe_cluster(self, value: str) -> bool:
        try:
            payload = json.loads(value) if isinstance(value, str) else value
        except Exception:
            return False
        if not isinstance(payload, dict):
            return False
        cluster_id = self._safe_vibe_cluster_id(payload.get("id"))
        data = self._read_vibe_cluster_json(cluster_id)
        if not data:
            return False
        name = str(payload.get("name") or "").strip()
        description = str(payload.get("description") or "").strip()
        if name:
            if not self._is_valid_vibe_cluster_name(name):
                self._broadcast_invalid_vibe_cluster_name()
                return False
            data["name"] = name
        data["description"] = description
        data["updated_at"] = datetime.now().isoformat(timespec="seconds")
        path = self._vibe_cluster_json_path(cluster_id)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        self._broadcast_json({"type": "toast", "message": "Updated Vibe cluster", "level": "success"})
        return True

    def _update_vibe_cluster_thumbnail(self, value: str) -> bool:
        try:
            payload = json.loads(value) if isinstance(value, str) else value
        except Exception:
            return False
        if not isinstance(payload, dict):
            return False
        cluster_id = self._safe_vibe_cluster_id(payload.get("id"))
        data = self._read_vibe_cluster_json(cluster_id)
        if not data:
            return False
        changed = self._save_vibe_cluster_thumbnail(cluster_id, payload.get("thumbnail_data") or "")
        if changed:
            data["updated_at"] = datetime.now().isoformat(timespec="seconds")
            path = self._vibe_cluster_json_path(cluster_id)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            self._broadcast_json({"type": "toast", "message": "Updated Vibe cluster thumbnail", "level": "success"})
        return changed

    def _load_vibe_cluster(self, module, value: str) -> int:
        try:
            payload = json.loads(value) if isinstance(value, str) else value
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        cluster_id = self._safe_vibe_cluster_id(payload.get("id"))
        mode = str(payload.get("mode") or "append").lower()
        data = self._read_vibe_cluster_json(cluster_id)
        if not data:
            self._broadcast_json({"type": "toast", "message": "Vibe cluster not found", "level": "error"})
            return 0

        if mode == "clean":
            for frame in list(getattr(module, "vibe_frames", []) or []):
                module._remove_frame(frame)

        frames = data.get("frames") if isinstance(data.get("frames"), list) else []
        added = 0
        skipped = 0
        for frame_data in frames:
            if len(getattr(module, "vibe_frames", []) or []) >= MAX_NAI_VIBE_REFERENCES:
                skipped += 1
                continue
            encodings = frame_data.get("encodings") if isinstance(frame_data.get("encodings"), dict) else {}
            if not encodings:
                skipped += 1
                continue
            pairs = []
            for key, encoding in encodings.items():
                try:
                    pairs.append((float(key), encoding))
                except Exception:
                    continue
            if not pairs:
                skipped += 1
                continue
            pairs.sort(key=lambda item: item[0])
            target_model = frame_data.get("target_model") or data.get("model") or self._current_vibe_model(module)
            vibe_data = {
                "reference_image_multiple": [encoding for _, encoding in pairs],
                "reference_strength_multiple": [float(frame_data.get("reference_strength", 0.6))],
                "reference_information_extracted_multiple": [key for key, _ in pairs],
                "source_model": target_model,
            }
            frame = module._add_vibe_frame_from_metadata(f"cluster_{cluster_id}_{added}", vibe_data)
            if not frame:
                skipped += 1
                continue
            selected_ie = frame_data.get("information_extracted", pairs[0][0])
            setter = getattr(module, "_set_frame_information_extracted", None)
            if callable(setter):
                setter(frame, selected_ie)
            else:
                frame.information_extracted = float(selected_ie)
            strength_setter = getattr(module, "_set_frame_reference_strength", None)
            if callable(strength_setter):
                strength_setter(frame, frame_data.get("reference_strength", 0.6))
            is_enabled = bool(frame_data.get("is_enabled", True))
            frame.is_enabled = is_enabled
            enable_check = getattr(frame, "enable_check", None)
            if enable_check is not None:
                enable_check.setChecked(is_enabled)
            added += 1

        if added:
            self._disable_all_char_ref_frames()
            message = f"Loaded {added} Vibe cluster frame(s)"
            if skipped:
                message += f" ({skipped} skipped)"
            self._broadcast_json({"type": "toast", "message": message, "level": "success"})
        else:
            self._broadcast_json({"type": "toast", "message": "No Vibe cluster frames loaded", "level": "error"})
        return added

    def _restore_vibe_transfer_from_metadata(self, module, value: str):
        try:
            payload = json.loads(value) if isinstance(value, str) else value
        except Exception as e:
            self._broadcast_json({"type": "toast", "message": f"Invalid Vibe metadata: {e}", "level": "error"})
            return
        if not isinstance(payload, dict):
            self._broadcast_json({"type": "toast", "message": "Invalid Vibe metadata", "level": "error"})
            return

        ref_images = payload.get("reference_image_multiple") or []
        if not isinstance(ref_images, list):
            ref_images = [ref_images]
        ref_images = [str(item) for item in ref_images if item]
        if not ref_images:
            self._broadcast_json({"type": "toast", "message": "No Vibe Transfer data in metadata", "level": "error"})
            return

        source_model = payload.get("source_model") or self._vibe_model_from_source(payload.get("source", ""))
        if not source_model:
            self._broadcast_json({"type": "toast", "message": "Unsupported Vibe metadata source model", "level": "error"})
            return

        current_model = self._current_vibe_model(module)
        if current_model and source_model not in current_model:
            self._broadcast_json({
                "type": "toast",
                "message": f"Vibe metadata requires {source_model}; current model is {current_model}",
                "level": "error",
            })
            return

        def _number_list(raw):
            if not isinstance(raw, list):
                raw = [raw] if raw not in (None, "") else []
            result = []
            for item in raw:
                try:
                    result.append(float(item))
                except Exception:
                    pass
            return result

        strengths = _number_list(payload.get("reference_strength_multiple"))
        information_extracted = _number_list(payload.get("reference_information_extracted_multiple"))

        if hasattr(module, "normalize_checkbox"):
            normalize = bool(payload.get("normalize_reference_strength_multiple", False))
            module.normalize_checkbox.setChecked(normalize)

        import hashlib
        added_count = 0
        for index, encoding in enumerate(ref_images):
            per_hash = hashlib.sha256(encoding.encode()).hexdigest()[:16]
            per_vibe_data = {
                "reference_image_multiple": [encoding],
                "reference_strength_multiple": [strengths[index] if index < len(strengths) else 0.6],
                "reference_information_extracted_multiple": [information_extracted[index]]
                if index < len(information_extracted) else [],
                "source_model": source_model,
            }
            frame = module._add_vibe_frame_from_metadata(f"no_image_metadata_{per_hash}", per_vibe_data)
            if frame:
                added_count += 1

        if added_count:
            self._disable_all_char_ref_frames()
            self._broadcast_json({
                "type": "toast",
                "message": f"Restored {added_count} Vibe Transfer frame(s)",
                "level": "success",
            })
        else:
            self._broadcast_json({"type": "toast", "message": "No Vibe Transfer frames restored", "level": "error"})

    # ── Wildcard Module ──

    # --- Instant Wildcard Module ---

    def _instant_wildcard_filename(self, name: str) -> str:
        filename = Path(str(name or "").strip()).name
        if not filename:
            return ""
        if not filename.endswith(".json"):
            filename += ".json"
        return filename

    def _instant_wildcard_file_signature(self, module) -> tuple:
        try:
            module.save_path.mkdir(parents=True, exist_ok=True)
            entries = []
            for item in sorted(module.save_path.glob("*.json"), key=lambda path: path.name):
                if item.name == "wc_metadata.json":
                    continue
                stat = item.stat()
                entries.append((item.name, stat.st_mtime_ns, stat.st_size))
            return tuple(entries)
        except Exception:
            return ()

    def _ensure_instant_wildcard_selection(self, module):
        if module.json_data:
            if module.current_file not in module.json_data:
                module.current_file = next(iter(module.json_data.keys()))
            current_items = module.json_data.get(module.current_file, {})
            if current_items and module.current_key not in current_items:
                module.current_key = next(iter(sorted(current_items.keys())))
            elif not current_items:
                module.current_key = None
        else:
            module.current_file = None
            module.current_key = None

    def _reload_instant_wildcards(self, module, *, force: bool = False) -> bool:
        if not module:
            return False
        try:
            module.save_path.mkdir(parents=True, exist_ok=True)
            default_file = module.save_path / "default.json"
            if not default_file.exists() and hasattr(module, "create_initial_files"):
                module.create_initial_files()

            signature = self._instant_wildcard_file_signature(module)
            if (
                not force
                and getattr(module, "_remote_iw_file_signature", None) == signature
                and getattr(module, "json_data", None)
            ):
                self._ensure_instant_wildcard_selection(module)
                return True

            if getattr(module, "file_combo", None) is not None and getattr(module, "key_combo", None) is not None:
                module.load_all_wildcards()
            else:
                module.json_data.clear()
                module.instant_wildcard_dict.clear()
                module.instant_wildcard_tree.clear()
                json_files = sorted([
                    item.name for item in module.save_path.glob("*.json")
                    if item.name != "wc_metadata.json"
                ])
                if "default.json" in json_files:
                    json_files.remove("default.json")
                    json_files.insert(0, "default.json")

                for filename in json_files:
                    filepath = module.save_path / filename
                    try:
                        with open(filepath, "r", encoding="utf-8") as handle:
                            data = json.load(handle)
                        if not isinstance(data, dict):
                            data = {}
                        module.json_data[filename] = data
                        basename = filename[:-5] if filename.endswith(".json") else filename
                        module.instant_wildcard_tree[basename] = data.copy()
                        for key, value in data.items():
                            flat_key = key
                            if flat_key in module.instant_wildcard_dict and basename != "default":
                                flat_key = f"{flat_key} ({basename})"
                            module.instant_wildcard_dict[flat_key] = value
                    except Exception as e:
                        print(f"🌐 Remote: instant wildcard 파일 로드 실패 — {filename}: {e}")

                if hasattr(module, "signals") and hasattr(module.signals, "wildcards_updated"):
                    module.signals.wildcards_updated.emit(module.instant_wildcard_dict)
                wildcard_manager = getattr(getattr(module, "app_context", None), "wildcard_manager", None)
                if wildcard_manager:
                    wildcard_manager.update_instant_wildcards(
                        module.instant_wildcard_dict,
                        module.instant_wildcard_tree,
                    )

            module._remote_iw_file_signature = signature
            self._ensure_instant_wildcard_selection(module)
            return True
        except Exception as e:
            print(f"🌐 Remote: instant_wildcard reload 실패 — {e}")
            return False

    def _write_instant_wildcard_file(self, module, filename: str) -> bool:
        filename = self._instant_wildcard_filename(filename)
        if not filename:
            return False
        try:
            module.save_path.mkdir(parents=True, exist_ok=True)
            filepath = module.save_path / filename
            data = module.json_data.get(filename, {})
            with open(filepath, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2)
            self._reload_instant_wildcards(module, force=True)
            return True
        except Exception as e:
            print(f"🌐 Remote: instant_wildcard 저장 실패 — {filename}: {e}")
            return False

    def _read_instant_wildcard(self) -> dict:
        try:
            module = self._find_module("instant_wildcard")
            if not module:
                return {}
            self._reload_instant_wildcards(module)
            files = []
            for filename in sorted(module.json_data.keys(), key=lambda name: (name != "default.json", name)):
                data = module.json_data.get(filename, {})
                group = filename[:-5] if filename.endswith(".json") else filename
                files.append({
                    "name": filename,
                    "group": group,
                    "count": len(data) if isinstance(data, dict) else 0,
                    "selected": filename == module.current_file,
                })

            current_file = module.current_file
            current_data = module.json_data.get(current_file, {}) if current_file else {}
            items = []
            if isinstance(current_data, dict):
                for key in sorted(current_data.keys()):
                    items.append({
                        "key": key,
                        "value": current_data.get(key, ""),
                        "selected": key == module.current_key,
                    })
            current_value = ""
            if current_file and module.current_key:
                current_value = module.json_data.get(current_file, {}).get(module.current_key, "")

            return {
                "type": "module_state",
                "module_id": "instant_wildcard",
                "files": files,
                "items": items,
                "current_file": current_file,
                "current_group": current_file[:-5] if current_file and current_file.endswith(".json") else current_file,
                "current_key": module.current_key,
                "current_value": current_value,
                "flat_count": len(getattr(module, "instant_wildcard_dict", {})),
                "save_path": str(getattr(module, "save_path", "")),
            }
        except Exception as e:
            print(f"🌐 Remote: instant_wildcard 상태 읽기 실패 — {e}")
            return {}

    def _broadcast_instant_wildcard_state(self):
        state = self._read_instant_wildcard()
        if state:
            self._broadcast_json(state)
        wildcard_state = self._read_wildcard()
        if wildcard_state:
            self._broadcast_json(wildcard_state)
        chunk_state = self._read_chunk()
        if chunk_state:
            self._broadcast_json(chunk_state)

    def _set_instant_wildcard(self, key: str, value: str):
        try:
            module = self._find_module("instant_wildcard")
            if not module:
                return
            self._reload_instant_wildcards(module)
            should_broadcast = True

            if key == "reload":
                self._reload_instant_wildcards(module, force=True)
            elif key == "select_file":
                filename = self._instant_wildcard_filename(value)
                if filename in module.json_data:
                    module.current_file = filename
                    data = module.json_data.get(filename, {})
                    module.current_key = next(iter(sorted(data.keys()))) if data else None
                    if getattr(module, "file_combo", None) is not None:
                        module.file_combo.setCurrentText(filename)
            elif key == "select_key":
                item_key = value.strip()
                if module.current_file and item_key in module.json_data.get(module.current_file, {}):
                    module.current_key = item_key
                    if getattr(module, "key_combo", None) is not None:
                        module.key_combo.setCurrentText(item_key)
                    if getattr(module, "value_edit", None) is not None:
                        module.value_edit.setPlainText(module.json_data[module.current_file][item_key])
            elif key == "value":
                if module.current_file and module.current_key:
                    module.json_data.setdefault(module.current_file, {})[module.current_key] = value
                    self._write_instant_wildcard_file(module, module.current_file)
            elif key == "upsert":
                payload = json.loads(value)
                filename = self._instant_wildcard_filename(payload.get("file") or module.current_file)
                item_key = str(payload.get("key", "")).strip()
                item_value = str(payload.get("value", ""))
                if not filename or not item_key:
                    self._broadcast_json({
                        "type": "toast",
                        "message": "Instant wildcard file/key is required",
                        "level": "error",
                    })
                    return
                module.json_data.setdefault(filename, {})[item_key] = item_value
                module.current_file = filename
                module.current_key = item_key
                saved = self._write_instant_wildcard_file(module, filename)
                self._broadcast_json({
                    "type": "toast",
                    "message": f"Chunk saved: {item_key}" if saved else "Chunk save failed",
                    "level": "success" if saved else "error",
                })
                if not saved:
                    should_broadcast = False
            elif key == "delete":
                payload = json.loads(value)
                filename = self._instant_wildcard_filename(payload.get("file") or module.current_file)
                item_key = str(payload.get("key", "")).strip()
                if filename in module.json_data and item_key in module.json_data[filename]:
                    del module.json_data[filename][item_key]
                    image_path = Path("save") / "instant_wildcard" / "images" / filename[:-5] / f"{item_key}.png"
                    if image_path.exists():
                        try:
                            image_path.unlink()
                        except Exception as e:
                            print(f"🌐 Remote: instant wildcard 이미지 삭제 실패 — {e}")
                    if module.current_file == filename and module.current_key == item_key:
                        remaining = module.json_data.get(filename, {})
                        module.current_key = next(iter(sorted(remaining.keys()))) if remaining else None
                    self._write_instant_wildcard_file(module, filename)
            elif key == "rename":
                payload = json.loads(value)
                filename = self._instant_wildcard_filename(payload.get("file") or module.current_file)
                old_key = str(payload.get("old_key", "")).strip()
                new_key = str(payload.get("new_key", "")).strip()
                if filename in module.json_data and old_key in module.json_data[filename] and new_key:
                    if new_key != old_key:
                        module.json_data[filename][new_key] = module.json_data[filename].pop(old_key)
                        old_image = Path("save") / "instant_wildcard" / "images" / filename[:-5] / f"{old_key}.png"
                        new_image = Path("save") / "instant_wildcard" / "images" / filename[:-5] / f"{new_key}.png"
                        if old_image.exists():
                            try:
                                new_image.parent.mkdir(parents=True, exist_ok=True)
                                old_image.rename(new_image)
                            except Exception as e:
                                print(f"🌐 Remote: instant wildcard 이미지 이름 변경 실패 — {e}")
                    module.current_file = filename
                    module.current_key = new_key
                    self._write_instant_wildcard_file(module, filename)
            elif key == "add_group":
                filename = self._instant_wildcard_filename(value)
                if filename:
                    if filename not in module.json_data:
                        module.json_data[filename] = {}
                        self._write_instant_wildcard_file(module, filename)
                    module.current_file = filename
                    module.current_key = None
            else:
                should_broadcast = False

            if should_broadcast:
                self._broadcast_instant_wildcard_state()
        except Exception as e:
            print(f"🌐 Remote: instant_wildcard 설정 실패 — {key}={value}: {e}")

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
            return {
                "type": "module_state",
                "module_id": "wildcard",
                "history": history,
                "state": state_lines,
                "prompt_squeeze": getattr(self.app_context, 'prompt_squeeze_enabled', True),
                "wildcard_count": len(self.app_context.wildcard_manager.wildcard_dict_tree),
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
                        if data.get("is_no_image") or data.get("storage_type") == "metadata_vibe" or not image_path.exists():
                            continue
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
            try:
                try:
                    repo_root = object.__getattribute__(self, "_repo_root")
                except (AttributeError, RuntimeError):
                    repo_root = Path(__file__).resolve().parent.parent
                result = load_kr_tag_records(repo_root)
                for warning in result.warnings:
                    print(f"🌐 Remote: {warning}")
                raw = result.raw
                if not raw:
                    self._kr_tags_loaded = True
                    return
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
                    f"{format_kr_tag_load_summary(result)}"
                )
                self._kr_tags_loaded = True
            except Exception as e:
                self._kr_tags_loaded = True
                print(f"🌐 Remote: tag index 로드 실패 — {e}")

    def _read_prompt_highlight_index(self) -> dict:
        """Prompt highlighter용 compact tag class index.

        Web typing path must not call TagSearchIndex on every keypress. Instead,
        the client receives these Sets once and classifies tokens locally with
        O(1) membership checks. The source of truth is the same merged
        `_kr_tags_raw` corpus used to build TagSearchIndex, plus P.Engineering
        filter lists for high/mid value buckets.
        """
        if self._prompt_highlight_index_cache is not None:
            return self._prompt_highlight_index_cache

        self._load_kr_tags()
        self._load_char_analysis()

        def _norm_tag(value) -> str:
            return (
                str(value or "")
                .replace("\\(", "(")
                .replace("\\)", ")")
                .replace("_", " ")
                .strip()
                .lower()
            )

        def _add_tags(target: set[str], values):
            if not values:
                return
            for value in values:
                tag = _norm_tag(value)
                if tag:
                    target.add(tag)

        def _read_json_tags(path: Path) -> set[str]:
            tags: set[str] = set()
            if not path.exists():
                return tags
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)

                def _collect_tag_lists(node, depth: int = 0):
                    if depth > 4:
                        return
                    if isinstance(node, list):
                        _add_tags(tags, node)
                        return
                    if not isinstance(node, dict):
                        return
                    for key in ("tags", "modifiers", "uncategorized"):
                        if isinstance(node.get(key), list):
                            _add_tags(tags, node.get(key))
                    for key in ("groups", "categories", "regions"):
                        value = node.get(key)
                        if isinstance(value, dict):
                            for child in value.values():
                                _collect_tag_lists(child, depth + 1)
                        elif isinstance(value, list):
                            _add_tags(tags, value)

                if isinstance(data, dict):
                    _collect_tag_lists(data)
                elif isinstance(data, list):
                    _add_tags(tags, data)
            except Exception as e:
                print(f"🌐 Remote: prompt highlight taglist load failed ({path}): {e}")
            return tags

        root_dir = Path(__file__).resolve().parent.parent
        taglist_dir = root_dir / "data" / "taglist"

        high_value = set()
        high_value.update(_read_json_tags(taglist_dir / "expression_tags.json"))
        high_value.update(_read_json_tags(taglist_dir / "pose_action_tags.json"))

        mid_value = set()
        mid_value.update(_read_json_tags(taglist_dir / "object_tags.json"))
        mid_value.update(_read_json_tags(taglist_dir / "clothing_regions.json"))
        clothes_path = root_dir / "data" / "clothes_list.txt"
        if clothes_path.exists():
            try:
                with open(clothes_path, "r", encoding="utf-8") as f:
                    _add_tags(mid_value, [line.strip() for line in f if line.strip()])
            except Exception as e:
                print(f"🌐 Remote: prompt highlight clothes list load failed: {e}")

        artist_tags = set()
        character_tags = set()
        copyright_tags = set()
        known_tags = set()
        for tag_lower, info in self._kr_tags_raw.items():
            tag = _norm_tag(info.get("_tag", tag_lower))
            if not tag:
                continue
            cat = str(info.get("_cat", "") or "")
            if cat == "artist":
                artist_tags.add(tag)
            elif cat == "character":
                character_tags.add(tag)
            elif cat == "copyright":
                copyright_tags.add(tag)
            else:
                known_tags.add(tag)

        known_tags.update(high_value)
        known_tags.update(mid_value)
        known_tags.update(_read_json_tags(taglist_dir / "style_meta_tags.json"))
        known_tags.difference_update(artist_tags)
        known_tags.difference_update(character_tags)
        known_tags.difference_update(copyright_tags)

        payload = {
            "highValueTags": sorted(high_value),
            "midValueTags": sorted(mid_value),
            "knownTags": sorted(known_tags),
            "artistTags": sorted(artist_tags),
            "characterTags": sorted(character_tags),
            "copyrightTags": sorted(copyright_tags),
            "stats": {
                "high": len(high_value),
                "mid": len(mid_value),
                "known": len(known_tags),
                "artists": len(artist_tags),
                "characters": len(character_tags),
                "copyrights": len(copyright_tags),
            },
        }
        self._prompt_highlight_index_cache = payload
        return payload

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

    @staticmethod
    def _autocomplete_candidate_fields(
        candidate_type: str,
        source: str,
        *,
        confidence: float = 1.0,
        insert_policy: str = "default",
        rank_score: float | None = None,
        score: float | None = None,
    ) -> dict:
        candidate = {
            "type": candidate_type,
            "source": source,
            "confidence": float(confidence),
            "insertPolicy": insert_policy,
        }
        fields = {
            "candidate": candidate,
            "candidateType": candidate_type,
            "source": source,
            "confidence": candidate["confidence"],
            "insertPolicy": insert_policy,
        }
        if rank_score is not None:
            candidate["rankScore"] = float(rank_score)
            fields["rankScore"] = candidate["rankScore"]
        if score is not None:
            candidate["score"] = float(score)
            fields["autocompleteScore"] = candidate["score"]
        return fields

    @staticmethod
    def _apply_autocomplete_candidate_schema(
        row: dict,
        candidate_type: str | None = None,
        source: str | None = None,
        *,
        confidence: float | None = None,
        insert_policy: str | None = None,
        rank_score: float | None = None,
        score: float | None = None,
    ) -> None:
        candidate = row.get("candidate")
        if not isinstance(candidate, dict):
            candidate = {}
        resolved_type = candidate_type or row.get("candidateType") or candidate.get("type") or "tag_exact"
        resolved_source = source or row.get("source") or candidate.get("source") or "tag_index"
        resolved_confidence = (
            confidence
            if confidence is not None
            else row.get("confidence", candidate.get("confidence", 1.0))
        )
        resolved_policy = (
            insert_policy
            or row.get("insertPolicy")
            or candidate.get("insertPolicy")
            or "default"
        )
        resolved_rank_score = (
            rank_score
            if rank_score is not None
            else row.get("rankScore", candidate.get("rankScore"))
        )
        resolved_score = (
            score
            if score is not None
            else row.get("autocompleteScore", candidate.get("score"))
        )
        row.update(
            RemoteBridge._autocomplete_candidate_fields(
                str(resolved_type),
                str(resolved_source),
                confidence=float(resolved_confidence or 0.0),
                insert_policy=str(resolved_policy),
                rank_score=(
                    float(resolved_rank_score)
                    if resolved_rank_score is not None
                    else None
                ),
                score=(
                    float(resolved_score)
                    if resolved_score is not None
                    else None
                ),
            )
        )

    @staticmethod
    def _autocomplete_candidate_value(row: dict, key: str, fallback=None):
        candidate = row.get("candidate")
        if isinstance(candidate, dict) and candidate.get(key) is not None:
            return candidate.get(key)
        if key == "type":
            return row.get("candidateType", fallback)
        if key == "source":
            return row.get("source", fallback)
        if key == "insertPolicy":
            return row.get("insertPolicy", fallback)
        if key == "score":
            return row.get("autocompleteScore", fallback)
        return row.get(key, fallback)

    @staticmethod
    def _autocomplete_float(value, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _autocomplete_nai_standard_score(row: dict) -> float:
        candidate_type = str(
            RemoteBridge._autocomplete_candidate_value(row, "type", "tag_exact")
            or "tag_exact"
        )
        insert_policy = str(
            RemoteBridge._autocomplete_candidate_value(row, "insertPolicy", "default")
            or "default"
        ).lower()
        type_weight = {
            "tag_canonical": 900.0,
            "tag_exact": 820.0,
            "tag_metadata": 760.0,
            "tag_translated": 680.0,
            "prompt_phrase": 640.0,
            "translation_hint": 120.0,
            "debug": 0.0,
        }.get(candidate_type, 500.0)
        rank_score = RemoteBridge._autocomplete_float(
            RemoteBridge._autocomplete_candidate_value(
                row,
                "rankScore",
                row.get("_rank_score", row.get("_metadata_score", 0.0)),
            )
        )
        confidence = RemoteBridge._autocomplete_float(
            RemoteBridge._autocomplete_candidate_value(row, "confidence", 1.0),
            1.0,
        )
        try:
            count = max(0, int(row.get("count") or 0))
        except (TypeError, ValueError):
            count = 0
        count_score = min(math.log10(count + 1) * 12.0, 72.0) if count else 0.0
        tag_tokens = normalize_search_query(row.get("tag", "")).split()
        length_penalty = max(0, len(tag_tokens) - 3) * 24.0
        if candidate_type == "translation_hint":
            length_penalty += max(0, len(tag_tokens) - 2) * 16.0
        manual_penalty = 520.0 if insert_policy == "manual" else 0.0
        return (
            type_weight
            + min(max(rank_score, 0.0), 900.0)
            + (max(0.0, min(confidence, 1.0)) * 60.0)
            + count_score
            - length_penalty
            - manual_penalty
        )

    @staticmethod
    def _canonical_base_tags_for_rows(rows: list[dict]) -> set[str]:
        return {
            normalize_search_query(row.get("tag", ""))
            for row in rows
            if (
                str(RemoteBridge._autocomplete_candidate_value(row, "type", ""))
                == "tag_canonical"
                and normalize_search_query(row.get("tag", ""))
            )
        }

    @staticmethod
    def _canonical_variant_of(tag: str, canonical_tags: set[str]) -> str:
        normalized = normalize_search_query(tag)
        if not normalized or normalized in canonical_tags:
            return ""
        tag_tokens = set(normalized.split())
        for canonical in sorted(canonical_tags, key=lambda item: (-len(item.split()), item)):
            canonical_tokens = set(canonical.split())
            if not canonical_tokens:
                continue
            if len(canonical_tokens) == 1:
                token = next(iter(canonical_tokens))
                if token in tag_tokens:
                    return canonical
                continue
            if canonical_tokens.issubset(tag_tokens):
                return canonical
        return ""

    @staticmethod
    def _canonical_base_boost_bucket(row: dict, canonical_tags: set[str]) -> tuple[int, str]:
        candidate_type = str(RemoteBridge._autocomplete_candidate_value(row, "type", ""))
        tag = normalize_search_query(row.get("tag", ""))
        if candidate_type == "tag_canonical" and tag in canonical_tags:
            return (0, "")
        variant_of = RemoteBridge._canonical_variant_of(tag, canonical_tags)
        if variant_of:
            row["_canonical_variant_of"] = variant_of
            return (2, variant_of)
        return (1, "")

    @staticmethod
    def _autocomplete_contains_domain_marker(text: str, markers: tuple[str, ...]) -> bool:
        normalized = normalize_search_query(text)
        if not normalized:
            return False
        compact = normalized.replace(" ", "")
        for marker in markers:
            marker_norm = normalize_search_query(marker)
            if not marker_norm:
                continue
            if any("\uac00" <= char <= "\ud7a3" for char in marker_norm):
                if marker_norm.replace(" ", "") in compact:
                    return True
                continue
            if " " in marker_norm:
                if marker_norm in normalized:
                    return True
                continue
            if re.search(
                rf"(?<![a-z0-9]){re.escape(marker_norm)}(?![a-z0-9])",
                normalized,
            ):
                return True
        return False

    @classmethod
    def _autocomplete_query_intent(cls, query: str | None) -> str:
        if cls._autocomplete_contains_domain_marker(
            query or "",
            _AUTOCOMPLETE_EXPLICIT_QUERY_MARKERS,
        ):
            return "explicit"
        if cls._autocomplete_contains_domain_marker(
            query or "",
            _AUTOCOMPLETE_SENSITIVE_QUERY_MARKERS,
        ):
            return "sensitive"
        return "general"

    @classmethod
    def _autocomplete_candidate_domain(cls, row: dict) -> str:
        tag_text = str(row.get("tag") or "")
        group_text = str(row.get("group") or "")
        cat_text = str(row.get("cat") or "")
        tag_is_explicit = cls._autocomplete_contains_domain_marker(
            tag_text,
            _AUTOCOMPLETE_EXPLICIT_CANDIDATE_MARKERS,
        )
        if tag_is_explicit:
            return "explicit"
        tag_is_sensitive = cls._autocomplete_contains_domain_marker(
            tag_text,
            _AUTOCOMPLETE_SENSITIVE_CANDIDATE_MARKERS,
        )
        group_blob = " ".join((group_text, cat_text))
        if cls._autocomplete_contains_domain_marker(
            group_blob,
            _AUTOCOMPLETE_EXPLICIT_GROUP_MARKERS,
        ):
            return "sensitive" if tag_is_sensitive else "explicit"
        if tag_is_sensitive or cls._autocomplete_contains_domain_marker(
            group_blob,
            _AUTOCOMPLETE_SENSITIVE_CANDIDATE_MARKERS,
        ):
            return "sensitive"
        return "general"

    @classmethod
    def _autocomplete_domain_demote_bucket(
        cls,
        row: dict,
        query_intent: str,
    ) -> int:
        candidate_domain = cls._autocomplete_candidate_domain(row)
        row["_query_intent"] = query_intent
        row["_candidate_domain"] = candidate_domain
        if query_intent != "general":
            return 0
        if candidate_domain == "explicit":
            row["_domain_demoted"] = True
            return 2
        if candidate_domain == "sensitive":
            return 1
        return 0

    def _score_autocomplete_candidates(
        self,
        rows: list[dict],
        *,
        sort: bool = False,
        query: str | None = None,
        score_sort: bool = False,
    ) -> list[dict]:
        scored: list[dict] = []
        query_intent = self._autocomplete_query_intent(query) if query else "unknown"
        for row in rows:
            item = dict(row)
            score = self._autocomplete_nai_standard_score(item)
            rank_score = self._autocomplete_candidate_value(
                item,
                "rankScore",
                item.get("_rank_score", item.get("_metadata_score")),
            )
            self._apply_autocomplete_candidate_schema(
                item,
                score=score,
                rank_score=rank_score,
            )
            scored.append(item)
        canonical_tags = self._canonical_base_tags_for_rows(scored)
        should_domain_sort = query_intent == "general" and bool(query)
        if not sort and (canonical_tags or should_domain_sort):
            return [
                row for _, row in sorted(
                    enumerate(scored),
                    key=lambda indexed_row: (
                        0
                        if self._canonical_base_boost_bucket(indexed_row[1], canonical_tags)[0] == 0
                        else 1,
                        self._autocomplete_domain_demote_bucket(indexed_row[1], query_intent),
                        self._canonical_base_boost_bucket(indexed_row[1], canonical_tags)[0],
                        indexed_row[0],
                    ),
                )
            ]
        if not sort:
            return scored

        def sort_key(indexed_row):
            index, row = indexed_row
            candidate_type = str(self._autocomplete_candidate_value(row, "type", ""))
            insert_policy = str(
                self._autocomplete_candidate_value(row, "insertPolicy", "default")
                or "default"
            ).lower()
            manual_bucket = 1 if candidate_type in {"translation_hint", "debug"} or insert_policy == "manual" else 0
            canonical_bucket, _ = self._canonical_base_boost_bucket(row, canonical_tags)
            domain_bucket = self._autocomplete_domain_demote_bucket(row, query_intent)
            autocomplete_score = self._autocomplete_float(row.get("autocompleteScore"))
            return (
                manual_bucket,
                0 if canonical_bucket == 0 else 1,
                domain_bucket,
                canonical_bucket,
                -autocomplete_score if score_sort else 0.0,
                index,
            )

        return [row for _, row in sorted(enumerate(scored), key=sort_key)]

    def _search_kr_tags(self, query: str, limit: int = 20) -> list:
        """5단계 우선순위 태그 검색: exact → starts_with → kr_keyword → contains → desc
        prefix 라우팅: 'artist:x' → artist만, 'character:x' → character만"""
        query = normalize_search_query(query)
        if not query:
            return []
        # prefix 라우팅 (@artist → artist: 변환 포함)
        cat_filter = None
        ql = query.lower()
        if ql.startswith('@'):
            cat_filter = 'artist'
            ql = normalize_search_query(ql[1:])
        else:
            for pfx in ('artist:', 'character:'):
                if ql.startswith(pfx):
                    cat_filter = pfx[:-1]  # 'artist' or 'character'
                    ql = normalize_search_query(ql[len(pfx):])
                    break
        if not ql:
            return []
        self._load_kr_tags()
        if not self._kr_tags_raw:
            return []
        if self._tag_search_index is not None:
            cats = {cat_filter} if cat_filter else None
            matches = self._tag_search_index.search_autocomplete(ql, limit=limit, cats=cats)
            rows = [
                {
                    "tag": result.tag,
                    "count": result.entry.freq,
                    "desc": result.entry.desc,
                    "group": result.entry.category,
                    "cat": result.entry.cat,
                    **self._autocomplete_candidate_fields(
                        "tag_exact",
                        "tag_index",
                    ),
                }
                for result in matches
            ]
            return self._score_autocomplete_candidates(rows, query=query)

        exact, starts, kr_kw, contains, desc_m = [], [], [], [], []
        for tag_lower, info in self._kr_tags_raw.items():
            cat = info.get('_cat', '')
            if cat_filter and cat != cat_filter:
                continue
            tag = info['_tag']
            freq = info.get('freq', 0)
            d = info.get('description', '')
            g = info.get('group', '')
            entry = {
                "tag": tag,
                "count": freq,
                "desc": d,
                "group": g,
                "cat": cat,
                **self._autocomplete_candidate_fields(
                    "tag_exact",
                    "tag_index",
                ),
            }
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
        return self._score_autocomplete_candidates(
            (exact + starts + kr_kw + contains + desc_m)[:limit],
            query=query,
        )

    def _search_kr_metadata_fallback(
        self,
        query: str,
        limit: int = 20,
        *,
        allow_build: bool = True,
    ) -> list:
        query = normalize_search_query(query)
        if not query or not self._has_hangul_text(query):
            return []
        try:
            object.__getattribute__(self, "_kr_tags_lock")
        except (AttributeError, RuntimeError):
            return []
        self._load_kr_tags()
        if getattr(self, "_tag_search_index", None) is None:
            return []
        if (
            not allow_build
            and not self._tag_search_index.metadata_fallback_index_ready()
            and not self._tag_search_index.warm_metadata_fallback_index(allow_build=False)
        ):
            return []
        matches = self._tag_search_index.search_metadata_fallback(
            query,
            limit=limit,
            exclude_noisy_categories=True,
        )
        rows = [
            {
                "tag": result.tag,
                "count": result.entry.freq,
                "desc": result.entry.desc,
                "group": result.entry.category,
                "cat": result.entry.cat,
                "_metadata": True,
                "_metadata_score": result.score,
                **self._autocomplete_candidate_fields(
                    "tag_metadata",
                    "kr_metadata",
                    confidence=0.85,
                    rank_score=result.score,
                ),
            }
            for result in matches
        ]
        return self._score_autocomplete_candidates(
            rows,
            sort=True,
            query=query,
            score_sort=True,
        )

    @staticmethod
    def _has_hangul_text(text: str) -> bool:
        return bool(re.search(r"[가-힣ㄱ-ㅎㅏ-ㅣ]", str(text or "")))

    def _translate_autocomplete_query(self, query: str) -> str:
        query = normalize_search_query(query)
        if not query or not self._has_hangul_text(query):
            return ""
        cached = self._autocomplete_translation_cache.get(query)
        if cached is not None:
            return cached
        translated = normalize_search_query(korean_to_english(query) or "")
        if not translated or self._has_hangul_text(translated) or translated == query:
            translated = ""
        if translated:
            translated = self._protect_autocomplete_translation_terms(query, translated)
        if len(self._autocomplete_translation_cache) > 256:
            self._autocomplete_translation_cache.clear()
        self._autocomplete_translation_cache[query] = translated
        return translated

    @staticmethod
    def _translation_phrase_pattern(phrase: str) -> str:
        escaped = re.escape(phrase).replace(r"\ ", r"\s+")
        return rf"(?<![a-z0-9]){escaped}(?![a-z0-9])"

    @staticmethod
    def _protect_autocomplete_translation_terms(query: str, translated: str) -> str:
        protected = _AUTOCOMPLETE_PROTECTED_KR_PHRASES
        if not protected:
            return translated
        normalized_query = normalize_search_query(query)
        normalized_translated = normalize_search_query(translated)
        if not normalized_query or not normalized_translated:
            return normalized_translated
        compact_query = normalized_query.replace(" ", "")
        for rule in protected:
            source = str(rule.get("source") or "")
            target = str(rule.get("target") or "")
            if not source or not target:
                continue
            compact_source = source.replace(" ", "")
            if source not in normalized_query and compact_source not in compact_query:
                continue
            exclusions = tuple(str(item) for item in rule.get("source_exclusion_terms", ()))
            if any(term and term in normalized_query for term in exclusions):
                continue
            for bad_phrase in sorted(
                (str(item) for item in rule.get("bad_phrases", ())),
                key=len,
                reverse=True,
            ):
                if not bad_phrase:
                    continue
                normalized_translated = re.sub(
                    RemoteBridge._translation_phrase_pattern(bad_phrase),
                    target,
                    normalized_translated,
                )
        return normalize_search_query(normalized_translated)

    def _autocomplete_result_cache_get(self, query: str, limit: int) -> tuple[list[dict], str] | None:
        try:
            cache = object.__getattribute__(self, "_autocomplete_result_cache")
        except (AttributeError, RuntimeError):
            return None
        if not isinstance(cache, dict):
            return None
        key = (normalize_search_query(query), int(limit or 0))
        cached = cache.get(key)
        if cached is None:
            return None
        rows, translated = cached
        return copy.deepcopy(rows), translated

    def _autocomplete_result_cache_set(
        self,
        query: str,
        limit: int,
        rows: list[dict],
        translated: str,
    ) -> tuple[list[dict], str]:
        try:
            cache = object.__getattribute__(self, "_autocomplete_result_cache")
        except (AttributeError, RuntimeError):
            cache = None
        if not isinstance(cache, dict):
            cache = {}
            self._autocomplete_result_cache = cache
        if len(cache) >= _AUTOCOMPLETE_RESULT_CACHE_MAX:
            cache.clear()
        key = (normalize_search_query(query), int(limit or 0))
        cache[key] = (copy.deepcopy(rows), translated)
        return rows, translated

    @staticmethod
    def _is_noisy_autocomplete_category(row: dict) -> bool:
        cat = normalize_search_query(row.get("cat", ""))
        if cat in {"artist", "character", "copyright"}:
            return True
        tag = normalize_search_query(row.get("tag", "")).replace("\\", "")
        parenthetical_parts = re.findall(r"\(([^)]*)\)", tag)
        if parenthetical_parts and any(
            normalize_search_query(part) not in {"medium", "meme"}
            for part in parenthetical_parts
        ):
            return True
        if (
            " uniform" in tag
            and len(tag.split()) > 2
            and tag not in {"school uniform", "kindergarten uniform", "military uniform", "uniform"}
        ):
            return True
        group = normalize_search_query(row.get("group", ""))
        if any(
            marker in group
            for marker in (
                "artist",
                "character",
                "copyright",
                "작가",
                "아티스트",
                "창작자",
                "저작권",
                "캐릭터",
                "등장인물",
                "버튜버",
                "버추얼 유튜버",
                "virtual youtuber",
                "hololive",
                "nijisanji",
                "작품",
                "시리즈",
                "미디어",
            )
        ):
            return True
        desc = normalize_search_query(row.get("desc", ""))
        is_apparel_variant = bool(set(tag.split()).intersection({"uniform", "dress", "costume", "outfit"}))
        apparel_source_markers = ("작품", "시리즈", "프랜차이즈", "특정", "캐릭터들이 입는", "등이 입는")
        if is_apparel_variant and any(marker in desc for marker in apparel_source_markers):
            return True
        source_markers = ("프랜차이즈", "극장판")
        if any(marker in desc for marker in source_markers):
            return True
        return False

    def _filter_noisy_autocomplete_rows(self, rows: list[dict], query: str) -> list[dict]:
        if not self._has_hangul_text(query):
            return rows
        return [
            row
            for row in rows
            if not self._is_noisy_autocomplete_category(row)
        ]

    def _canonical_autocomplete_rows(self, query: str, limit: int = 20) -> list[dict]:
        reconstructed_queries = reconstruct_kr_tag_queries(query, limit=8)
        if not reconstructed_queries:
            return []
        match_items = []
        seen_match_tags: set[str] = set()
        for reconstructed in reconstructed_queries:
            matches = match_kr_phrase_canonical_tags(reconstructed.query, limit=limit)
            for match in matches:
                key = normalize_search_query(match.tag)
                if not key or key in seen_match_tags:
                    continue
                seen_match_tags.add(key)
                match_items.append((match, reconstructed))
                if len(match_items) >= limit:
                    break
            if len(match_items) >= limit:
                break
        if not match_items:
            return []
        try:
            bridge_state = object.__getattribute__(self, "__dict__")
        except Exception:
            bridge_state = {}
        if "_kr_tags_raw" not in bridge_state:
            self._kr_tags_raw = {}
            bridge_state = object.__getattribute__(self, "__dict__")
        if "_kr_tags_loaded" in bridge_state:
            self._load_kr_tags()
            bridge_state = object.__getattribute__(self, "__dict__")
        raw_tags = bridge_state.get("_kr_tags_raw", {})
        rows: list[dict] = []
        seen: set[str] = set()
        for match, reconstructed in match_items:
            key = normalize_search_query(match.tag)
            if not key or key in seen:
                continue
            seen.add(key)
            info = raw_tags.get(key) or raw_tags.get(match.tag.lower())
            if info is None:
                exact_rows = [
                    row for row in self._search_kr_tags(match.tag, limit=5)
                    if normalize_search_query(row.get("tag", "")) == key
                ]
                if exact_rows:
                    row = dict(exact_rows[0])
                else:
                    row = {
                        "tag": match.tag,
                        "count": 0,
                        "desc": "",
                        "group": "",
                        "cat": "",
                    }
            else:
                row = {
                    "tag": info.get("_tag", match.tag),
                    "count": info.get("freq", info.get("count", 0)),
                    "desc": info.get("description", info.get("desc", "")),
                    "group": info.get("group", ""),
                    "cat": info.get("_cat", ""),
                }
            row["_canonical"] = True
            row["_canonical_rule"] = match.rule_id
            row["_canonical_axis"] = match.axis
            row["_canonical_query"] = reconstructed.query
            row["_canonical_query_form"] = reconstructed.form
            confidence = min(max(match.confidence * reconstructed.confidence, 0.0), 1.0)
            row["_rank_score"] = 920.0 * confidence
            row.update(
                self._autocomplete_candidate_fields(
                    "tag_canonical",
                    "kr_phrase_canonical",
                    confidence=confidence,
                    rank_score=row["_rank_score"],
                )
            )
            rows.append(row)
        return rows

    def _translation_search_query_levels(self, translated: str) -> list[list[str]]:
        normalized = normalize_search_query(translated)
        if not normalized:
            return []
        normalized = normalized.replace("’", "'").replace("`", "'")
        tokens = re.findall(r"[a-z0-9]+(?:'[a-z0-9]+)?", normalized)
        normalized = " ".join(tokens)
        if not normalized:
            return []
        query_levels: list[list[str]] = []

        def add_query(value: str, level: int = 0):
            term = normalize_search_query(value)
            if not term:
                return
            if any(term in queries for queries in query_levels):
                return
            while len(query_levels) <= level:
                query_levels.append([])
            query_levels[level].append(term)

        def possessive_base(token: str) -> str:
            if token.endswith("'s"):
                return token[:-2]
            return token

        def is_pronoun_or_possessive(token: str) -> bool:
            base = possessive_base(token)
            return (
                token in _AUTOCOMPLETE_TRANSLATION_PRONOUNS
                or token in _AUTOCOMPLETE_TRANSLATION_POSSESSIVES
                or base in _AUTOCOMPLETE_TRANSLATION_PRONOUNS
                or base in _AUTOCOMPLETE_TRANSLATION_POSSESSIVES
                or (token.endswith("'s") and base in _AUTOCOMPLETE_TRANSLATION_ACTOR_WORDS)
            )

        def is_structural_noise(token: str) -> bool:
            if is_pronoun_or_possessive(token):
                return True
            if token in _AUTOCOMPLETE_TRANSLATION_PARTICLES:
                return True
            if token in _AUTOCOMPLETE_WEAK_POSE_VERBS:
                return True
            return (
                token in _AUTOCOMPLETE_TRANSLATION_STOPWORDS
                and token not in _AUTOCOMPLETE_RELATION_PREPOSITIONS
            )

        def has_phrase(phrase_tokens: list[str], phrase: tuple[str, ...]) -> bool:
            if not phrase:
                return False
            phrase_length = len(phrase)
            return any(
                tuple(phrase_tokens[index:index + phrase_length]) == phrase
                for index in range(0, len(phrase_tokens) - phrase_length + 1)
            )

        def add_domain_phrase_aliases():
            plain_tokens = [possessive_base(token) for token in tokens]
            token_set = set(plain_tokens)

            def normalized_items(value) -> list[str]:
                if not isinstance(value, list):
                    return []
                return [
                    token
                    for token in (
                        _normalize_autocomplete_rule_token(item) for item in value
                    )
                    if token
                ]

            def rule_group_matches(group: dict) -> bool:
                if not isinstance(group, dict):
                    return False
                if any(token in token_set for token in normalized_items(group.get("tokens_any"))):
                    return True
                phrases = group.get("phrases_any", [])
                if not isinstance(phrases, list):
                    return False
                for phrase in phrases:
                    phrase_tokens = normalized_items(phrase)
                    if phrase_tokens and has_phrase(plain_tokens, tuple(phrase_tokens)):
                        return True
                return False

            def rule_matches(rule: dict) -> bool:
                groups = rule.get("when_all", [])
                if not groups:
                    return True
                if not isinstance(groups, list):
                    return False
                return all(rule_group_matches(group) for group in groups)

            for rule in _AUTOCOMPLETE_DOMAIN_PHRASE_ALIAS_RULES:
                if not rule_matches(rule):
                    continue
                outputs = rule.get("outputs", [])
                if not isinstance(outputs, list):
                    continue
                for output in outputs:
                    if not isinstance(output, dict) or not rule_matches(output):
                        continue
                    for query in normalized_items(output.get("queries")):
                        add_query(query, 2)

        def add_cleaned_sentence():
            removed_actor_token = False
            has_weak_pose_verb = False
            cleaned = [
                token for token in tokens
                if not (
                    is_pronoun_or_possessive(token)
                    or (
                        token in _AUTOCOMPLETE_TRANSLATION_STOPWORDS
                        and token not in _AUTOCOMPLETE_RELATION_PREPOSITIONS
                    )
                )
            ]
            for token in tokens:
                if is_pronoun_or_possessive(token):
                    removed_actor_token = True
                if token in _AUTOCOMPLETE_WEAK_POSE_VERBS:
                    has_weak_pose_verb = True
            while cleaned and cleaned[-1] in _AUTOCOMPLETE_RELATION_PREPOSITIONS:
                cleaned.pop()
            if len(cleaned) >= 2 and (removed_actor_token or has_weak_pose_verb):
                add_query(" ".join(cleaned), 1)

        def content_phrase_after(index: int, max_terms: int = 2) -> list[str]:
            phrase: list[str] = []
            cursor = index + 1
            while cursor < len(tokens) and is_structural_noise(tokens[cursor]):
                cursor += 1
            while cursor < len(tokens) and len(phrase) < max_terms:
                token = tokens[cursor]
                if token in _AUTOCOMPLETE_TRANSLATION_STOPWORDS:
                    break
                if _AUTOCOMPLETE_ACTION_FORMS.get(token):
                    break
                if len(token) >= 3:
                    phrase.append(token)
                cursor += 1
            return phrase

        def action_object_phrase_after_preposition(
            index: int,
            immediate_object: list[str],
            max_terms: int = 2,
        ) -> list[str]:
            if not immediate_object:
                return []
            cursor = index + 1
            found_immediate = False
            while cursor < len(tokens):
                token = tokens[cursor]
                if _AUTOCOMPLETE_ACTION_FORMS.get(token):
                    return []
                if token == "of":
                    if not found_immediate:
                        return []
                    cursor += 1
                    break
                if is_structural_noise(token):
                    cursor += 1
                    continue
                if token in _AUTOCOMPLETE_RELATION_PREPOSITIONS:
                    return []
                found_immediate = True
                cursor += 1
            else:
                return []

            phrase: list[str] = []
            while cursor < len(tokens) and len(phrase) < max_terms:
                token = tokens[cursor]
                if is_structural_noise(token):
                    cursor += 1
                    continue
                if token in _AUTOCOMPLETE_RELATION_PREPOSITIONS:
                    break
                if _AUTOCOMPLETE_ACTION_FORMS.get(token):
                    break
                if len(token) >= 3:
                    phrase.append(token)
                cursor += 1
            return phrase

        def action_relation_phrase_after(index: int, max_terms: int = 2) -> list[str]:
            action_relation_prepositions = {
                *_AUTOCOMPLETE_RELATION_PREPOSITIONS,
                "at",
                "in",
            }
            cursor = index + 1
            while (
                cursor < len(tokens)
                and tokens[cursor] not in action_relation_prepositions
                and is_structural_noise(tokens[cursor])
            ):
                cursor += 1
            if cursor >= len(tokens):
                return []
            preposition = tokens[cursor]
            if preposition not in action_relation_prepositions:
                return []
            cursor += 1
            object_tokens: list[str] = []
            while cursor < len(tokens) and len(object_tokens) < max_terms:
                token = tokens[cursor]
                if is_structural_noise(token):
                    cursor += 1
                    continue
                if token in _AUTOCOMPLETE_RELATION_PREPOSITIONS:
                    break
                if _AUTOCOMPLETE_ACTION_FORMS.get(token):
                    break
                if len(token) >= 3:
                    object_tokens.append(token)
                cursor += 1
            return [preposition, *object_tokens] if object_tokens else []

        def add_content_run_phrases():
            run: list[str] = []

            def flush_run():
                if len(run) < 2:
                    return
                for size in (3, 2):
                    if len(run) < size:
                        continue
                    for index in range(0, len(run) - size + 1):
                        phrase_tokens = run[index:index + size]
                        if any(_AUTOCOMPLETE_ACTION_FORMS.get(token) for token in phrase_tokens):
                            continue
                        add_query(" ".join(phrase_tokens), 2)

            for token in tokens:
                if (
                    token in _AUTOCOMPLETE_TRANSLATION_STOPWORDS
                    or is_structural_noise(token)
                ):
                    flush_run()
                    run = []
                    continue
                if len(token) >= 3:
                    run.append(token)
            flush_run()

        def relation_subject_before(index: int) -> str:
            def has_prior_content(cursor: int) -> bool:
                probe = cursor - 1
                while probe >= 0:
                    previous = tokens[probe]
                    if is_structural_noise(previous):
                        probe -= 1
                        continue
                    return (
                        previous not in _AUTOCOMPLETE_RELATION_PREPOSITIONS
                        and not _AUTOCOMPLETE_ACTION_FORMS.get(previous)
                    )
                return False

            cursor = index - 1
            while cursor >= 0:
                token = tokens[cursor]
                if is_structural_noise(token):
                    cursor -= 1
                    continue
                if token in _AUTOCOMPLETE_RELATION_PREPOSITIONS:
                    break
                if _AUTOCOMPLETE_ACTION_FORMS.get(token):
                    if has_prior_content(cursor):
                        cursor -= 1
                        continue
                    break
                if token.endswith("ing") and has_prior_content(cursor):
                    cursor -= 1
                    continue
                return token if len(token) >= 3 else ""
            return ""

        def relation_object_after(index: int, max_terms: int = 2) -> tuple[list[str], bool]:
            object_tokens: list[str] = []
            own_context = False
            cursor = index + 1
            while cursor < len(tokens):
                token = tokens[cursor]
                if token in _AUTOCOMPLETE_TRANSLATION_POSSESSIVES:
                    own_context = True
                if is_structural_noise(token):
                    cursor += 1
                    continue
                break
            while cursor < len(tokens) and len(object_tokens) < max_terms:
                token = tokens[cursor]
                if token in _AUTOCOMPLETE_TRANSLATION_POSSESSIVES:
                    own_context = True
                    cursor += 1
                    continue
                if is_structural_noise(token):
                    cursor += 1
                    continue
                if token in _AUTOCOMPLETE_RELATION_PREPOSITIONS:
                    break
                if _AUTOCOMPLETE_ACTION_FORMS.get(token):
                    break
                if len(token) >= 3:
                    object_tokens.append(token)
                cursor += 1
            return object_tokens, own_context

        def aliased_relation_objects(subject: str, object_tokens: list[str]) -> list[list[str]]:
            if not object_tokens:
                return []
            aliases = _AUTOCOMPLETE_RELATION_OBJECT_ALIASES.get(object_tokens[-1], ())
            if not aliases:
                return []
            preferred_plural = subject.endswith("s")
            ordered = sorted(
                aliases,
                key=lambda alias: 0 if alias.endswith("s") == preferred_plural else 1,
            )
            return [object_tokens[:-1] + [alias] for alias in ordered]

        def add_relation_phrases():
            for index, token in enumerate(tokens):
                if token not in _AUTOCOMPLETE_RELATION_PREPOSITIONS:
                    continue
                subject = relation_subject_before(index)
                object_tokens, own_context = relation_object_after(index)
                if not subject or not object_tokens:
                    continue
                aliased_objects = aliased_relation_objects(subject, object_tokens)
                prefer_own_relation = (
                    own_context and subject in _AUTOCOMPLETE_BODY_RELATION_SUBJECTS
                )
                if prefer_own_relation:
                    for candidate_objects in aliased_objects:
                        add_query(" ".join([subject, token, "own", *candidate_objects]), 2)
                    for candidate_objects in aliased_objects:
                        add_query(" ".join([subject, token, *candidate_objects]), 2)
                    add_query(" ".join([subject, token, "own", *object_tokens]), 2)
                else:
                    for candidate_objects in aliased_objects:
                        add_query(" ".join([subject, token, *candidate_objects]), 2)
                add_query(" ".join([subject, token, *object_tokens]), 2)
                add_query(" ".join([subject, token]), 3)
                add_query(" ".join([token, *object_tokens]), 3)

        content_tokens = [
            token for token in tokens
            if len(token) >= 3
            and token not in _AUTOCOMPLETE_TRANSLATION_STOPWORDS
            and not is_pronoun_or_possessive(token)
            and token not in _AUTOCOMPLETE_WEAK_POSE_VERBS
            and token not in _AUTOCOMPLETE_LOW_VALUE_SINGLE_TOKENS
            and not _AUTOCOMPLETE_ACTION_FORMS.get(token)
        ]

        add_query(normalized, 0)
        add_cleaned_sentence()
        add_domain_phrase_aliases()
        for index, token in enumerate(tokens):
            action_variant = _AUTOCOMPLETE_ACTION_FORMS.get(token)
            if not action_variant:
                continue
            relation_phrase = action_relation_phrase_after(index)
            if relation_phrase:
                add_query(" ".join([action_variant, *relation_phrase]), 2)
            object_phrase = content_phrase_after(index)
            if action_variant in _AUTOCOMPLETE_TRANSITIVE_ACTION_FORMS and object_phrase:
                add_query(" ".join([action_variant] + object_phrase), 2)
                prepositional_object = action_object_phrase_after_preposition(index, object_phrase)
                if prepositional_object:
                    add_query(" ".join([action_variant] + prepositional_object), 2)
                if len(object_phrase) > 1:
                    add_query(" ".join(object_phrase), 3)
                add_query(action_variant, 3)
            elif relation_phrase:
                add_query(action_variant, 3)
            else:
                add_query(action_variant, 2)

        add_relation_phrases()
        add_content_run_phrases()
        for token in content_tokens:
            add_query(token, 3)
        return [queries for queries in query_levels if queries]

    def _translation_search_queries(self, translated: str) -> list[str]:
        queries: list[str] = []
        for level in RemoteBridge._translation_search_query_levels(self, translated):
            for query in level:
                if query not in queries:
                    queries.append(query)
                if len(queries) >= 18:
                    return queries
        return queries

    @staticmethod
    def _fallback_translation_tokens(translated: str) -> list[str]:
        normalized = normalize_search_query(translated)
        normalized = normalized.replace("’", "'").replace("`", "'")
        return re.findall(r"[a-z0-9]+(?:'[a-z0-9]+)?", normalized)

    @staticmethod
    def _fallback_possessive_base(token: str) -> str:
        return token[:-2] if token.endswith("'s") else token

    @staticmethod
    def _fallback_token_is_pronoun_or_possessive(token: str) -> bool:
        base = RemoteBridge._fallback_possessive_base(token)
        return (
            token in _AUTOCOMPLETE_TRANSLATION_PRONOUNS
            or token in _AUTOCOMPLETE_TRANSLATION_POSSESSIVES
            or base in _AUTOCOMPLETE_TRANSLATION_PRONOUNS
            or base in _AUTOCOMPLETE_TRANSLATION_POSSESSIVES
        )

    @staticmethod
    def _simple_fallback_recommended_query(translated: str) -> str:
        tokens = RemoteBridge._fallback_translation_tokens(translated)
        has_pronoun_or_possessive = any(
            RemoteBridge._fallback_token_is_pronoun_or_possessive(token)
            for token in tokens
        )
        if not has_pronoun_or_possessive:
            return normalize_search_query(" ".join(tokens))
        cleaned: list[str] = []
        for token in tokens:
            base = RemoteBridge._fallback_possessive_base(token)
            if RemoteBridge._fallback_token_is_pronoun_or_possessive(token):
                if token.endswith("'s") and base in _AUTOCOMPLETE_TRANSLATION_ACTOR_WORDS:
                    cleaned.append(base)
                continue
            if token in {"a", "an", "the", "be", "been", "being", "is", "are", "was", "were"}:
                continue
            cleaned.append(token)
        return normalize_search_query(" ".join(cleaned))

    @staticmethod
    def _fallback_query_has_pronoun_or_possessive(query: str) -> bool:
        return any(
            RemoteBridge._fallback_token_is_pronoun_or_possessive(token)
            for token in RemoteBridge._fallback_translation_tokens(query)
        )

    @staticmethod
    def _prompt_phrase_row(
        phrase: str,
        *,
        confidence: float = 0.72,
        reason: str = "phrase normalizer",
    ) -> dict:
        return {
            "tag": normalize_search_query(phrase),
            "count": 0,
            "desc": reason,
            "group": "[prompt phrase]",
            "cat": "",
            "_wc_type": "prompt_phrase",
            "_prompt_phrase": True,
            **RemoteBridge._autocomplete_candidate_fields(
                "prompt_phrase",
                "phrase_normalizer",
                confidence=confidence,
                insert_policy="default",
            ),
        }

    @staticmethod
    def _prompt_phrase_quality_ok(phrase: str, *, force: bool = False) -> bool:
        normalized = normalize_search_query(phrase)
        tokens = RemoteBridge._fallback_translation_tokens(normalized)
        if not tokens:
            return False
        if not force and not (2 <= len(tokens) <= 5):
            return False
        if force and len(tokens) > 5:
            return False
        if any(RemoteBridge._fallback_token_is_pronoun_or_possessive(token) for token in tokens):
            return False
        if any(token in {"a", "an", "the", "be", "been", "being", "is", "are", "was", "were"} for token in tokens):
            return False
        if not force:
            canonical_actions = set(_AUTOCOMPLETE_ACTION_FORMS.values())
            has_action = any(token in canonical_actions for token in tokens)
            if not has_action:
                return False
        return True

    def _normalized_prompt_phrase_rows(self, translated: str, limit: int = 20) -> list[dict]:
        tokens = self._fallback_translation_tokens(translated)
        token_set = {self._fallback_possessive_base(token) for token in tokens}
        candidates: list[tuple[str, float, str, bool]] = []

        def add(phrase: str, confidence: float = 0.72, reason: str = "phrase normalizer", *, force: bool = False):
            normalized = normalize_search_query(phrase)
            if not normalized:
                return
            candidates.append((normalized, confidence, reason, force))

        if token_set & {"raise", "raises", "raised", "raising", "lift", "lifts", "lifted", "lifting"} and token_set & {"arm", "arms"}:
            add("arms raised", 0.86, "raise/lift arms", force=True)
            add("raising arms", 0.82, "raise/lift arms", force=True)

        if token_set & {"separate", "separated", "detached"} and token_set & {"sleeve", "sleeves"}:
            add("detached sleeves", 0.86, "detached sleeve rule", force=True)
            if token_set & {"wrist", "wrists"}:
                add("wrist cuffs", 0.78, "detached sleeve rule", force=True)

        if token_set & {"pin", "pins"} and token_set & {"clothes", "clothing", "lapel", "decorative", "attached"}:
            add("lapel pin", 0.78, "clothing pin rule", force=True)
            add("brooch", 0.74, "clothing pin rule", force=True)
            add("decorative pin on clothes", 0.70, "clothing pin rule", force=True)

        for query in self._translation_search_queries(translated):
            add(query, 0.68, "translation query phrase")

        rows: list[dict] = []
        seen: set[str] = set()
        for phrase, confidence, reason, force in candidates:
            key = normalize_search_query(phrase)
            if not key or key in seen:
                continue
            if not self._prompt_phrase_quality_ok(key, force=force):
                continue
            seen.add(key)
            rows.append(self._prompt_phrase_row(key, confidence=confidence, reason=reason))
            if len(rows) >= min(limit, 5):
                break
        return rows

    def _append_prompt_phrase_rows(
        self,
        rows: list[dict],
        translated: str,
        limit: int,
    ) -> list[dict]:
        normalized_rows: dict[str, int] = {}
        for index, row in enumerate(rows):
            key = normalize_search_query(row.get("tag", ""))
            if key and key not in normalized_rows:
                normalized_rows[key] = index
        next_rows = list(rows)
        prompt_rows: list[dict] = []
        for row in self._normalized_prompt_phrase_rows(translated, limit):
            key = normalize_search_query(row.get("tag", ""))
            if not key:
                continue
            existing_index = normalized_rows.get(key)
            if existing_index is not None:
                if next_rows[existing_index].get("candidateType") == "translation_hint":
                    next_rows[existing_index] = row
                continue
            normalized_rows[key] = len(next_rows) + len(prompt_rows)
            prompt_rows.append(row)
        if not prompt_rows:
            return next_rows
        return next_rows + prompt_rows

    @staticmethod
    def _fallback_recommended_row(query: str) -> dict:
        return {
            "tag": query,
            "count": 0,
            "desc": "translation hint",
            "group": "[translation hint]",
            "cat": "",
            "_wc_type": "fallback_recommended",
            "_fallback_recommended": True,
            **RemoteBridge._autocomplete_candidate_fields(
                "translation_hint",
                "translation_fallback",
                confidence=0.2,
                insert_policy="manual",
            ),
        }

    @staticmethod
    def _translated_query_row_allowed(row: dict, translated_query: str) -> bool:
        query = normalize_search_query(translated_query)
        query_tokens = query.split()
        if len(query_tokens) != 1:
            return True
        tag = normalize_search_query(row.get("tag", ""))
        return query_tokens[0] in tag.split()

    @staticmethod
    def _translated_fallback_row_score(row: dict, translated_query: str, level_index: int) -> float:
        query = normalize_search_query(translated_query)
        tag = normalize_search_query(row.get("tag", ""))
        if not query or not tag:
            return 0.0
        query_size = len(query.split())
        score = 660.0 - (level_index * 170.0)
        if tag == query:
            score += 130.0
        elif tag.startswith(query):
            score += 70.0
        elif query in tag:
            score += 45.0
        elif query_size == 1 and query in tag.split():
            score += 20.0
        if query_size <= 1:
            score -= 110.0
        try:
            count = int(row.get("count") or 0)
        except (TypeError, ValueError):
            count = 0
        if count > 0:
            score += min(math.log10(count + 1) * 3.0, 18.0)
        return score

    def _fallback_recommended_rows(
        self,
        translated: str,
        limit: int,
        *,
        multiword_only: bool = False,
    ) -> list[dict]:
        rows: list[dict] = []
        queries = self._translation_search_queries(translated)
        simple_query = self._simple_fallback_recommended_query(translated)
        if simple_query:
            queries = [simple_query] + [
                query for query in queries
                if query != simple_query and not self._fallback_query_has_pronoun_or_possessive(query)
            ]
        preferred = [query for query in queries if len(query.split()) >= 2]
        fallback = [] if multiword_only else [query for query in queries if len(query.split()) < 2]
        for query in preferred + fallback:
            if not query:
                continue
            rows.append(self._fallback_recommended_row(query))
            if len(rows) >= min(limit, 5):
                break
        return rows

    @staticmethod
    def _translated_query_has_actor_context(translated: str) -> bool:
        tokens = re.findall(
            r"[a-z0-9]+(?:'[a-z0-9]+)?",
            normalize_search_query(translated).replace("’", "'").replace("`", "'"),
        )
        for token in tokens:
            base = token[:-2] if token.endswith("'s") else token
            if base in _AUTOCOMPLETE_TRANSLATION_ACTOR_WORDS:
                return True
        return False

    def _has_strong_translated_match(self, rows: list[dict], translated: str) -> bool:
        levels = self._translation_search_query_levels(translated)
        strong_queries = {
            query
            for level in levels
            for query in level
            if len(query.split()) >= 2
        }
        if not strong_queries:
            return False
        for row in rows:
            tag = normalize_search_query(row.get("tag", ""))
            if not tag:
                continue
            if tag in strong_queries:
                return True
        return False

    def _should_prepend_fallback_recommended(self, translated: str, rows: list[dict]) -> bool:
        if not translated or not self._translated_query_has_actor_context(translated):
            return False
        return not self._has_strong_translated_match(rows, translated)

    def _should_prepend_simple_fallback_recommended(
        self,
        query: str,
        translated: str,
        rows: list[dict],
    ) -> bool:
        simple_query = self._simple_fallback_recommended_query(translated)
        simple_tokens = simple_query.split()
        if not simple_query or not (1 <= len(simple_tokens) <= 4):
            return False
        normalized_query = normalize_search_query(query)
        if not normalized_query or not self._has_hangul_text(normalized_query):
            return False
        hangul_terms = re.findall(r"[가-힣ㄱ-ㅎㅏ-ㅣ]+", normalized_query)
        if len(hangul_terms) < 2:
            return False
        if len(hangul_terms) > 3 or sum(len(term) for term in hangul_terms) > 12:
            return False
        action_suffixes = (
            "고있다",
            "고있는",
            "고있음",
            "하다",
            "한다",
            "했다",
            "하는",
            "하기",
            "하게",
            "하다",
            "함",
            "음",
            "다",
            "기",
        )
        if any(term.endswith(action_suffixes) for term in hangul_terms):
            return False
        if any(_AUTOCOMPLETE_ACTION_FORMS.get(token) for token in simple_tokens):
            return False
        row_tags = {
            normalize_search_query(row.get("tag", ""))
            for row in rows
        }
        if simple_query in row_tags:
            return False
        return not self._has_strong_translated_match(rows, simple_query)

    def _search_kr_tags_with_translation(self, query: str, limit: int = 20) -> tuple[list, str]:
        cached_result = self._autocomplete_result_cache_get(query, limit)
        if cached_result is not None:
            return cached_result
        canonical_results = self._filter_noisy_autocomplete_rows(
            self._canonical_autocomplete_rows(query, min(limit, 8)),
            query,
        )
        canonical_tags = {
            normalize_search_query(row.get("tag", ""))
            for row in canonical_results
            if normalize_search_query(row.get("tag", ""))
        }
        base_results = self._filter_noisy_autocomplete_rows(
            [
                row for row in self._search_kr_tags(query, limit)
                if normalize_search_query(row.get("tag", "")) not in canonical_tags
            ],
            query,
        )
        translated = self._translate_autocomplete_query(query)
        if not translated:
            metadata_rows = self._search_kr_metadata_fallback(
                query,
                min(limit, 8),
                allow_build=False,
            )
            if metadata_rows:
                combined_rows = self._filter_noisy_autocomplete_rows(
                    canonical_results + metadata_rows + base_results,
                    query,
                )
                rows = self._score_autocomplete_candidates(
                    combined_rows,
                    sort=True,
                    query=query,
                    score_sort=True,
                )[:limit]
                return self._autocomplete_result_cache_set(query, limit, rows, "")
            rows = self._score_autocomplete_candidates(
                canonical_results + base_results,
                query=query,
            )
            return self._autocomplete_result_cache_set(query, limit, rows, "")

        merged: dict[str, dict] = {}
        order: list[str] = []

        def copy_best_score(target: dict, source: dict, key: str) -> None:
            score = source.get(key)
            if score is None:
                return
            try:
                next_score = float(score)
            except (TypeError, ValueError):
                return
            try:
                previous_score = float(target.get(key) or 0.0)
            except (TypeError, ValueError):
                previous_score = 0.0
            if key not in target or next_score > previous_score:
                target[key] = next_score

        def add_result(row: dict, translated_match: bool = False, metadata_match: bool = False):
            tag = str(row.get("tag") or "")
            if not tag:
                return
            existing = merged.get(tag)
            if existing is None:
                item = dict(row)
                if translated_match:
                    item["_translated"] = True
                    if item.get("candidateType") in {None, "", "tag_exact"}:
                        item["candidateType"] = "tag_translated"
                    if item.get("source") in {None, "", "tag_index"}:
                        item["source"] = "translation_search"
                    if item.get("candidateType") == "tag_translated":
                        item["confidence"] = 0.75
                    item.setdefault("insertPolicy", "default")
                if metadata_match:
                    item["_metadata"] = True
                    item["candidateType"] = "tag_metadata"
                    item["source"] = "kr_metadata"
                    item["confidence"] = 0.85
                    item.setdefault("insertPolicy", "default")
                item.setdefault("candidateType", "tag_exact")
                item.setdefault("source", "tag_index")
                item.setdefault("confidence", 1.0)
                item.setdefault("insertPolicy", "default")
                self._apply_autocomplete_candidate_schema(
                    item,
                    rank_score=(
                        item.get("_rank_score")
                        if item.get("_rank_score") is not None
                        else item.get("_metadata_score")
                    ),
                )
                merged[tag] = item
                order.append(tag)
                return
            if translated_match:
                existing["_translated"] = True
                copy_best_score(existing, row, "_rank_score")
                existing["desc"] = existing.get("desc") or row.get("desc", "")
                existing["group"] = existing.get("group") or row.get("group", "")
                if existing.get("candidateType") not in {"tag_canonical", "tag_exact", "tag_metadata"}:
                    existing["candidateType"] = "tag_translated"
                    existing["source"] = "translation_search"
                    existing["confidence"] = 0.75
                self._apply_autocomplete_candidate_schema(
                    existing,
                    rank_score=(
                        existing.get("_rank_score")
                        if existing.get("_rank_score") is not None
                        else existing.get("_metadata_score")
                    ),
                )
            if metadata_match:
                existing["_metadata"] = True
                copy_best_score(existing, row, "_metadata_score")
                copy_best_score(existing, row, "_rank_score")
                existing["desc"] = existing.get("desc") or row.get("desc", "")
                existing["group"] = existing.get("group") or row.get("group", "")
                if existing.get("candidateType") != "tag_canonical":
                    existing["candidateType"] = "tag_metadata"
                    existing["source"] = "kr_metadata"
                    existing["confidence"] = 0.85
                self._apply_autocomplete_candidate_schema(
                    existing,
                    rank_score=(
                        existing.get("_metadata_score")
                        if existing.get("_metadata_score") is not None
                        else existing.get("_rank_score")
                    ),
                )

        natural_hangul_query = self._has_hangul_text(query) and len(normalize_search_query(query).split()) >= 2
        base_head_count = max(3, limit // 2)
        for row in canonical_results:
            add_result(row)
        if not natural_hangul_query:
            for row in base_results[:base_head_count]:
                add_result(row)

        evidence_rows: list[dict] = []
        for level_index, query_level in enumerate(self._translation_search_query_levels(translated)):
            level_rows: list[dict] = []
            for translated_query in query_level:
                translated_query_size = len(translated_query.split())
                if translated_query_size <= 1:
                    translated_query_limit = min(2, limit)
                elif translated_query_size == 2:
                    translated_query_limit = min(4, limit)
                else:
                    translated_query_limit = min(6, limit)
                rows = [
                    row for row in self._search_kr_tags(translated_query, translated_query_limit)
                    if self._translated_query_row_allowed(row, translated_query)
                ]
                rows.sort(
                    key=lambda row: 0
                    if normalize_search_query(row.get("tag", "")) == translated_query
                    else 1
                )
                for row in rows:
                    item = dict(row)
                    item["_translated"] = True
                    item["_translated_query"] = translated_query
                    item["_rank_score"] = self._translated_fallback_row_score(
                        row,
                        translated_query,
                        level_index,
                    )
                    level_rows.append(item)
            if not level_rows:
                continue
            evidence_rows.extend(level_rows)
            break

        metadata_evidence_rows: list[dict] = []
        for row in self._search_kr_metadata_fallback(
            query,
            min(limit, 8),
            allow_build=False,
        ):
            item = dict(row)
            item["_metadata"] = True
            item["_rank_score"] = float(item.get("_metadata_score") or 0.0)
            metadata_evidence_rows.append(item)
            evidence_rows.append(item)

        if evidence_rows:
            if not metadata_evidence_rows:
                for row in evidence_rows:
                    add_result(row, translated_match=bool(row.get("_translated")))
                evidence_rows = []

        if evidence_rows:
            best_by_tag: dict[str, dict] = {}
            for row in evidence_rows:
                tag = str(row.get("tag") or "")
                if not tag:
                    continue
                previous = best_by_tag.get(tag)
                if previous is None or float(row.get("_rank_score") or 0.0) > float(previous.get("_rank_score") or 0.0):
                    best_by_tag[tag] = row
                else:
                    if row.get("_translated"):
                        previous["_translated"] = True
                    if row.get("_metadata"):
                        previous["_metadata"] = True
            ranked_rows = sorted(
                best_by_tag.values(),
                key=lambda row: (
                    -float(row.get("_rank_score") or 0.0),
                    -int(row.get("count") or 0),
                    str(row.get("tag") or ""),
                ),
            )
            for row in ranked_rows:
                add_result(
                    row,
                    translated_match=bool(row.get("_translated")),
                    metadata_match=bool(row.get("_metadata")),
                )

        base_tail = base_results if natural_hangul_query else base_results[base_head_count:]
        for row in base_tail:
            add_result(row)

        if not merged:
            for row in self._fallback_recommended_rows(translated, limit):
                add_result(row)

        results = [merged[tag] for tag in order]
        results = self._append_prompt_phrase_rows(results, translated, limit)
        results = self._filter_noisy_autocomplete_rows(results, query)
        if self._should_prepend_simple_fallback_recommended(query, translated, results):
            simple_query = self._simple_fallback_recommended_query(translated)
            if simple_query:
                results = [self._fallback_recommended_row(simple_query)] + results
        if self._should_prepend_fallback_recommended(translated, results):
            existing_tags = {
                normalize_search_query(row.get("tag", ""))
                for row in results
            }
            recommended = [
                row
                for row in self._fallback_recommended_rows(translated, limit, multiword_only=True)
                if normalize_search_query(row.get("tag", "")) not in existing_tags
            ]
            results = recommended + results
        elif not any(row.get("_fallback_recommended") for row in results):
            existing_tags = {
                normalize_search_query(row.get("tag", ""))
                for row in results
            }
            recommended = [
                row
                for row in self._fallback_recommended_rows(translated, max(limit, 5))
                if normalize_search_query(row.get("tag", "")) not in existing_tags
            ][:1]
            if recommended:
                results = results[:max(0, limit - len(recommended))] + recommended

        rows = self._score_autocomplete_candidates(results, sort=True, query=query)[:limit]
        return self._autocomplete_result_cache_set(query, limit, rows, translated)

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

    def _search_chunks(self, query: str, limit: int = 12) -> list:
        """인스턴트 와일드카드 Chunk 검색 ($key / $group: 용)."""
        try:
            module = self._find_module("instant_wildcard")
            if not module:
                return []
            self._reload_instant_wildcards(module)
            flat_dict, tree = module.get_wildcards()
            raw = str(query or "").strip()
            if raw.startswith("$"):
                raw = raw[1:].strip()
            q = raw.lower()

            def preview_text(value: str, max_len: int = 96) -> str:
                text = str(value or "").replace("\n", " ").strip()
                return text[:max_len] + "..." if len(text) > max_len else text

            def match_rank(text: str, needle: str) -> int | None:
                haystack = str(text or "").lower()
                if not needle:
                    return 4
                if haystack == needle:
                    return 0
                if haystack.startswith(needle):
                    return 1
                for word in re.split(r"[\s_\-]+", haystack):
                    if word.startswith(needle):
                        return 2
                if needle in haystack:
                    return 3
                return None

            def group_result(group_name: str, items: dict) -> dict:
                samples = []
                for key, value in list(items.items())[:5]:
                    samples.append(f"{key}: {preview_text(value, 42)}")
                if len(items) > 5:
                    samples.append(f"... +{len(items) - 5}")
                return {
                    "tag": group_name,
                    "value": f"${group_name}:",
                    "count": len(items),
                    "desc": f"{len(items)} entries",
                    "group": "chunk group",
                    "cat": "",
                    "preview": "\n".join(samples),
                    "_wc_type": "chunk_group",
                }

            def item_result(key: str, value: str, group_name: str) -> dict:
                return {
                    "tag": key,
                    "value": str(value or ""),
                    "count": 0,
                    "desc": preview_text(value),
                    "group": group_name,
                    "cat": "",
                    "preview": str(value or ""),
                    "_wc_type": "chunk",
                }

            def item_matches(items: dict, group_name: str, needle: str) -> list:
                ranked = []
                for index, (key, value) in enumerate(items.items()):
                    key_rank = match_rank(key, needle)
                    value_rank = match_rank(value, needle)
                    rank_values = [r for r in (key_rank, None if value_rank is None else value_rank + 2) if r is not None]
                    if not rank_values:
                        continue
                    ranked.append((min(rank_values), index, item_result(key, value, group_name)))
                ranked.sort(key=lambda item: (item[0], item[1]))
                return [item[2] for item in ranked]

            if ":" in raw:
                group_name, item_query = raw.split(":", 1)
                group_name = group_name.strip()
                item_query = item_query.strip()
                group_items = tree.get(group_name)
                if group_items is None:
                    group_items = next(
                        (items for existing_name, items in tree.items()
                         if str(existing_name).lower() == group_name.lower()),
                        None,
                    )
                if not group_items:
                    return []
                return item_matches(group_items, group_name, item_query.lower())[:limit]

            results = []
            exact_group_items = []
            group_ranked = []
            for index, (group_name, items) in enumerate(tree.items()):
                rank = match_rank(group_name, q)
                if rank is None:
                    continue
                group_ranked.append((rank, index, group_result(group_name, items)))
                if q and str(group_name).lower() == q:
                    exact_group_items = item_matches(items, group_name, "")

            group_ranked.sort(key=lambda item: (item[0], item[1]))
            results.extend(item[2] for item in group_ranked)
            results.extend(exact_group_items)

            item_ranked = []
            for group_name, items in tree.items():
                for item in item_matches(items, group_name, q):
                    item_ranked.append(item)
            seen = {(item["_wc_type"], item["group"], item["tag"]) for item in results}
            for item in item_ranked:
                key = (item["_wc_type"], item["group"], item["tag"])
                if key in seen:
                    continue
                seen.add(key)
                results.append(item)

            if not results and q:
                for key, value in flat_dict.items():
                    rank_values = [r for r in (match_rank(key, q), match_rank(value, q)) if r is not None]
                    if rank_values:
                        results.append(item_result(key, value, "chunk"))

            return results[:limit]
        except Exception as e:
            print(f"🌐 Remote: chunk 검색 실패: {e}")
            return []

    def _search_vibe_clusters(self, query: str, limit: int = 12) -> list:
        try:
            return search_vibe_clusters(query, limit=limit)
        except Exception as e:
            print(f"🌐 Remote: vibe cluster 검색 실패: {e}")
            return []

    def _preset_autocomplete_payload(
        self,
        query: str,
        limit: int = 12,
        context: dict | None = None,
    ) -> dict:
        """preset: path autocomplete payload for Remote Web prompt inputs."""
        try:
            token = str(query or "").strip()
            if not token.lower().startswith("preset:"):
                token = "preset:" + token
            context = context if isinstance(context, dict) else {}
            preset_context = self._set_preset_input_context({
                "ratingId": str(context.get("ratingId") or "s"),
                "personId": str(context.get("personId") or "1girl_solo"),
            }, "autocomplete")
            bridge = getattr(self, "_preset_autocomplete_bridge", None)
            if bridge is None:
                try:
                    bridge = PresetInputBridge(
                        self._repo_root,
                        event_service=self._event_preset_service,
                        clothes_service=self._clothes_preset_service,
                        expression_service=self._expression_preset_service,
                        context=preset_context,
                    )
                except TypeError:
                    bridge = PresetInputBridge(self._repo_root, context=preset_context)
                self._preset_autocomplete_bridge = bridge
            elif hasattr(bridge, "set_context"):
                bridge.set_context(preset_context)
            caret_offset = context.get("caretOffset")
            try:
                caret_offset = int(caret_offset) if caret_offset is not None else None
            except (TypeError, ValueError):
                caret_offset = None
            try:
                payload = bridge.suggest(token, limit=limit, caret_offset=caret_offset)
            except TypeError:
                payload = bridge.suggest(token, limit=limit)
            rows = payload.get("suggestions") or []
            secondary_rows = (
                payload.get("secondaryResults")
                or payload.get("secondarySuggestions")
                or []
            )
            if payload.get("stage") in {"loading", "unavailable"}:
                state = payload.get("loadState") or {}
                message = str(state.get("message") or "Preset data is not ready.")
                rows = [{
                    "tag": str(state.get("main") or payload.get("stage") or "preset"),
                    "value": token,
                    "count": 0,
                    "desc": message,
                    "group": "preset",
                    "cat": "preset",
                    "_wc_type": "preset_status",
                    "disabled": True,
                }]
                secondary_rows = []
            return {
                "query": token,
                "results": rows,
                "secondaryResults": secondary_rows,
                "preset": {
                    "axis": payload.get("axis") or "",
                    "stage": payload.get("stage") or "",
                    "context": payload.get("presetContext") or {},
                    "loadState": payload.get("loadState") or {},
                    "dataReady": bool(payload.get("dataReady")),
                    "secondaryResults": secondary_rows,
                },
            }
        except Exception as e:
            print(f"🌐 Remote: preset path 검색 실패: {e}")
            return {"query": str(query or ""), "results": [], "preset": {}}

    def _search_preset_paths(
        self,
        query: str,
        limit: int = 12,
        context: dict | None = None,
    ) -> list:
        return self._preset_autocomplete_payload(query, limit=limit, context=context).get("results", [])

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
        tag_lower = re.sub(r'\\([()])', r'\1', tag.strip()).lower()
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
        # 캐릭터 태그 → character_analysis 상세 정보 추가 (첫 호출 시 lazy 빌드)
        if result.get('cat') == 'character':
            if not self._char_analysis:
                self._load_char_analysis()
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
                "active_ratings": self._normalize_rating_list(self._active_ratings),
                "query": query,
                "exclude": exclude,
                "ratings": ratings,
                "filter_preferences": self._normalize_search_filter_state(self._search_filter_state),
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
            self._save_search_filter_state(
                query=params.get("query", ""),
                exclude=params.get("exclude", ""),
                ratings=self._normalize_rating_list(self._active_ratings),
            )
            # 검색 실행
            mw.trigger_search()
        except Exception as e:
            print(f"🌐 Remote: search 실행 실패 — {e}")

    def _custom_parquet_dir(self) -> Path:
        return Path("save/custom_tags")

    def _normalize_custom_parquet_filename(self, filename: str, *, fallback_prefix: str = "search_export") -> str:
        clean = Path(str(filename or "").strip()).name
        if not clean:
            clean = f"{fallback_prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.parquet"
        if not clean.lower().endswith(".parquet"):
            clean += ".parquet"
        return clean

    def _next_custom_parquet_path(self, filename: str, *, fallback_prefix: str = "search_export") -> Path:
        explicit_filename = bool(str(filename or "").strip())
        clean = self._normalize_custom_parquet_filename(filename, fallback_prefix=fallback_prefix)
        path = self._custom_parquet_dir() / clean
        if explicit_filename or not path.exists():
            return path
        stem = path.stem
        suffix = path.suffix
        for index in range(2, 1000):
            candidate = path.with_name(f"{stem}_{index}{suffix}")
            if not candidate.exists():
                return candidate
        return path.with_name(f"{stem}_{uuid.uuid4().hex[:8]}{suffix}")

    def _resolve_custom_parquet_path(self, filename: str) -> Path | None:
        raw = str(filename or "").strip()
        clean = self._normalize_custom_parquet_filename(raw)
        if raw and clean != raw:
            return None
        return self._custom_parquet_dir() / clean

    def _set_search_dataframe(self, df, *, snapshot: bool = True):
        mw = self.app_context.main_window
        mw.search_results.set_dataframe(df)
        if snapshot and hasattr(mw, '_save_search_snapshot'):
            mw._save_search_snapshot()
        count = mw.search_results.get_count()
        if hasattr(mw, 'result_label1'):
            mw.result_label1.setText(f"검색: {count}")
        if hasattr(mw, 'result_label2'):
            mw.result_label2.setText(f"남음: {count}")
        return count

    def _do_load_parquet(self, filename: str):
        """커스텀 parquet 로드"""
        self._load_or_merge_custom_parquet(filename, merge=False)

    def _do_merge_parquet(self, filename: str):
        """커스텀 parquet 를 현재 검색 결과에 병합"""
        self._load_or_merge_custom_parquet(filename, merge=True)

    def _load_or_merge_custom_parquet(self, filename: str, *, merge: bool = False):
        file_path = self._resolve_custom_parquet_path(filename)
        if not file_path:
            self._broadcast_json({"type": "toast", "message": "Invalid parquet filename", "level": "error"})
            return
        if not file_path.exists():
            self._broadcast_json({"type": "toast", "message": f"Parquet not found: {filename}", "level": "error"})
            return
        self._load_or_merge_parquet_path(file_path, display_name=file_path.name, merge=merge)

    def _load_or_merge_parquet_path(self, file_path: Path, *, display_name: str = "", merge: bool = False):
        try:
            import pandas as pd
            mw = self.app_context.main_window
            if not mw:
                return
            df = pd.read_parquet(file_path)
            if merge:
                current_df = mw.search_results.get_dataframe() if mw.search_results else pd.DataFrame()
                if current_df is not None and not current_df.empty:
                    df = pd.concat([current_df, df], ignore_index=True)
            count = self._set_search_dataframe(df)
            # 웹 클라이언트에 전체 상태 전송
            state = self._read_search_state()
            if state:
                state["merged" if merge else "loaded"] = display_name or file_path.name
                self._broadcast_json(state)
            verb = "merged" if merge else "loaded"
            self._broadcast_json({
                "type": "toast",
                "message": f"{display_name or file_path.name} {verb} ({count:,})",
                "level": "success",
            })
        except Exception as e:
            print(f"🌐 Remote: parquet 로드 실패 — {e}")
            self._broadcast_json({"type": "toast", "message": f"Parquet action failed: {e}", "level": "error"})

    def _do_uploaded_parquet(self, payload_json: str):
        """브라우저에서 업로드된 parquet 파일을 로드/병합."""
        params = json.loads(payload_json or "{}")
        temp_path = Path(str(params.get("temp_path") or ""))
        filename = self._normalize_custom_parquet_filename(params.get("filename") or temp_path.name)
        merge = str(params.get("action") or "").strip() == "merge"
        try:
            if not temp_path.exists():
                self._broadcast_json({"type": "toast", "message": "Uploaded parquet is unavailable", "level": "error"})
                return
            self._load_or_merge_parquet_path(temp_path, display_name=filename, merge=merge)
        finally:
            try:
                temp_path.unlink(missing_ok=True)
            except Exception:
                pass

    def _do_search_parquet_action(self, payload_json: str):
        """SEARCH Parquet 메뉴 액션: export / runner 저장."""
        try:
            params = json.loads(payload_json or "{}")
            action = str(params.get("action") or "").strip()
            mw = self.app_context.main_window
            if not mw or not mw.search_results:
                return
            current_df = mw.search_results.get_dataframe()
            if current_df is None or current_df.empty:
                self._broadcast_json({"type": "toast", "message": "No search results to save", "level": "error"})
                return

            if action == "export_results":
                export_dir = self._custom_parquet_dir()
                export_dir.mkdir(parents=True, exist_ok=True)
                path = self._next_custom_parquet_path(
                    params.get("filename") or "",
                    fallback_prefix="search_export",
                )
                current_df.to_parquet(path, index=False)
                message = f"Exported {path.name} ({len(current_df):,})"
            elif action == "save_runner":
                path = Path("naia_temp_rows.parquet")
                current_df.to_parquet(path, index=False)
                message = f"Saved runner parquet ({len(current_df):,})"
            else:
                self._broadcast_json({"type": "toast", "message": "Unsupported parquet action", "level": "error"})
                return

            state = self._read_search_state()
            if state:
                self._broadcast_json(state)
            self._broadcast_json({"type": "toast", "message": message, "level": "success"})
        except Exception as e:
            print(f"🌐 Remote: search parquet action 실패 — {e}")
            self._broadcast_json({"type": "toast", "message": f"Parquet action failed: {e}", "level": "error"})

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
        """GSQE + Tag Filter를 master snapshot에서 재적용.
        set_active_ratings / tag_filter_assign / tag_filter_clear 시 호출."""
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
        """검색 데이터 교체 시 Remote Session 필터 전체 초기화.
        _save_search_snapshot()에서 호출됨 (필터 적용 중에는 _skip_filter_reset으로 우회)."""
        self._apply_saved_search_filter_state()
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
        has_tag_filter = self._restore_saved_tag_filter_ids()
        has_rating_filter = set(self._active_ratings) != {'g', 's', 'q', 'e'}
        if has_rating_filter or has_tag_filter:
            self._do_apply_filters()
            return
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
            "active_ratings": self._normalize_rating_list(self._active_ratings),
            "filter_preferences": self._normalize_search_filter_state(self._search_filter_state),
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
                    if (
                        src_row is not None
                        and "image_width" in src_row
                        and "image_height" in src_row
                    ):
                        try:
                            w = int(src_row["image_width"])
                            h = int(src_row["image_height"])
                            if w > 0 and h > 0:
                                fitted_w, fitted_h = self._coerce_artist_thumb_resolution(w, h)
                                if self._artist_thumb_resolution_allowed(fitted_w, fitted_h):
                                    cf_width, cf_height = fitted_w, fitted_h
                                    cf_res_source = "detected" if (fitted_w, fitted_h) == (w, h) else "detected_fit"
                        except (ValueError, TypeError):
                            pass
                    if cf_width is None:
                        cf_width, cf_height, cf_res_source = self._artist_thumb_random_resolution()
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
            prompt_source_row = getattr(prompt_context, "source_row", None)
            prompt_source_name = str(getattr(prompt_source_row, "name", "") or "")
            prompt_event_preset_request_id = ""
            if prompt_source_name.startswith("event_preset:"):
                prompt_event_preset_request_id = prompt_source_name.split(":", 1)[1]
            prompt_remote_preset_request_id = ""
            if prompt_source_name.startswith("preset:"):
                prompt_remote_preset_request_id = prompt_source_name.split(":", 1)[1]

            auto_ws = None
            if prompt_event_preset_request_id:
                event_key = ("event_preset", prompt_event_preset_request_id)
                if event_key in self._pending_overrides:
                    auto_ws = event_key
            if auto_ws is None and prompt_remote_preset_request_id:
                preset_key = ("preset", prompt_remote_preset_request_id)
                if preset_key in self._pending_overrides:
                    auto_ws = preset_key
            if auto_ws is None and not prompt_event_preset_request_id and not prompt_remote_preset_request_id:
                for ws_key, pending in list(self._pending_overrides.items()):
                    if (
                        isinstance(ws_key, tuple)
                        and len(ws_key) == 2
                        and ws_key[0] in {"event_preset", "preset"}
                    ):
                        continue
                    if pending.get("auto_generate"):
                        auto_ws = ws_key
                        break

            prompt_settings = getattr(prompt_context, "settings", {}) or {}
            is_auto_generated_prompt = bool(prompt_settings.get("auto_generate"))
            source = (
                "event_preset"
                if prompt_event_preset_request_id
                else (
                    "preset"
                    if prompt_remote_preset_request_id
                    else ("auto_generate" if is_auto_generated_prompt else "random")
                )
            )
            event_preset_request_id = prompt_event_preset_request_id
            remote_preset_request_id = prompt_remote_preset_request_id
            remote_random_request_id = ""
            if auto_ws:
                pending = self._pending_overrides.pop(auto_ws, {})
                source = pending.get("source", "random")
                remote_random_request_id = str(pending.get("remote_random_request_id") or "")
                event_preset_request_id = str(
                    pending.get("event_preset_request_id")
                    or event_preset_request_id
                    or ""
                )
                remote_preset_request_id = str(
                    pending.get("remote_preset_request_id")
                    or remote_preset_request_id
                    or ""
                )
                pending_neg = pending.get("negative")
                pending_params = pending.get("params")
                if pending_params and isinstance(pending_params, dict):
                    detected_resolution = None
                    try:
                        detected_resolution = (getattr(prompt_context, "metadata", {}) or {}).get("detected_resolution")
                    except Exception:
                        detected_resolution = None
                    if detected_resolution and len(detected_resolution) == 2:
                        try:
                            width, height = int(detected_resolution[0]), int(detected_resolution[1])
                            if width > 0 and height > 0:
                                pending_params["width"] = width
                                pending_params["height"] = height
                                pending_params["resolution"] = f"{width} x {height}"
                        except (TypeError, ValueError):
                            pass
                # seed_fixed가 아닌 경우 → 랜덤 시드로 교체
                if pending_params and "seed" in pending_params:
                    if not self._coerce_bool(pending_params.get("seed_fixed")):
                        pending_params["seed"] = str(random.randint(0, 9999999999))
                # pending negative 반영
                if pending_neg is not None:
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
                elif source == "event_preset" and event_preset_request_id:
                    self._broadcast_json({
                        "type": "event_preset_generation_error",
                        "requestId": event_preset_request_id,
                        "message": "Event Preset generation skipped because generation is already running.",
                    })
                elif source == "preset" and remote_preset_request_id:
                    self._broadcast_json({
                        "type": "preset_generation_error",
                        "source": "preset",
                        "requestId": remote_preset_request_id,
                        "message": "Preset generation skipped because generation is already running.",
                    })
            else:
                # auto_generate 아닌 pending (generate 등) → source만 추출
                for ws_key, pending in list(self._pending_overrides.items()):
                    if (
                        isinstance(ws_key, tuple)
                        and len(ws_key) == 2
                        and ws_key[0] in {"event_preset", "preset"}
                    ):
                        continue
                    pending_source = pending.get("source")
                    if pending_source:
                        source = pending_source
                        remote_random_request_id = str(
                            pending.get("remote_random_request_id")
                            or remote_random_request_id
                            or ""
                        )
                        if pending_source == "random" and not pending.get("auto_generate"):
                            self._pending_overrides.pop(ws_key, None)
                        else:
                            pending.pop("source", None)
                        if ws_key in self._pending_overrides and not pending:  # 빈 dict면 제거
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
                if source == "random" and remote_random_request_id:
                    data["random_request_id"] = remote_random_request_id
                    data["requestId"] = remote_random_request_id
                detected_resolution = (getattr(prompt_context, "metadata", {}) or {}).get("detected_resolution")
                if detected_resolution and len(detected_resolution) == 2:
                    try:
                        width, height = int(detected_resolution[0]), int(detected_resolution[1])
                        if width > 0 and height > 0:
                            data["detected_resolution"] = {"width": width, "height": height}
                            data["resolution"] = f"{width} x {height}"
                    except (TypeError, ValueError):
                        pass
                if event_preset_request_id:
                    data["event_preset_request_id"] = event_preset_request_id
                if remote_preset_request_id:
                    data["requestId"] = remote_preset_request_id
                    data["remote_preset_request_id"] = remote_preset_request_id
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
        """생성 완료 시그널 슬롯 (Qt 메인 스레드).
        무거운 작업(WebP 인코딩 + 메타데이터 추출 + broadcast)은 워커 스레드로 위임 — 메인 스레드 블록 금지.
        """
        # NAI 모드에서 생성 끝나면 Anlas 잔액 갱신 (가벼움 — 비동기 HTTP)
        try:
            if hasattr(self.app_context, "get_api_mode") and self.app_context.get_api_mode() == "NAI":
                self._refresh_anlas_async()
        except Exception:
            pass
        image = result.get("image")
        if image is None:
            return
        try:
            gen_params = result.get("generation_params", {}) or {}
            if gen_params.get("result_enhance_request"):
                self.on_result_enhance_completed(True, "Enhance complete")
        except Exception:
            pass
        # 메인 스레드는 worker 시작만 — image.save(WEBP method=4) 가 ~수백 ms 잡으면 GUI 정지
        threading.Thread(
            target=self._encode_and_broadcast_result,
            args=(image, result),
            daemon=True,
            name="ResultBroadcast",
        ).start()

    def _encode_and_broadcast_result(self, image, result: dict):
        """워커 스레드: WebP 인코딩 → 즉시 broadcast → 무거운 metadata 후처리.
        broadcast 를 먼저 큐잉해서 클라이언트 페인트 latency 최소화. metadata payload 빌드는
        /api/result/metadata 호출 시까지만 준비되면 되므로 broadcast 뒤로 미룬다.
        """
        try:
            # 1. WebP 인코딩 — method=0 (가장 빠름, GIL 점유 시간 최소화)
            #    method=4 대비 ~3-5x 빠름. 파일 크기는 약간 커지나 미리보기 용도라 무관.
            buf = io.BytesIO()
            image.save(buf, format='WEBP', quality=85, method=0)
            webp_bytes = buf.getvalue()

            gen_params = result.get("generation_params", {})
            character_viewer_thumbnail = None
            prompt_preset_thumbnail = None
            character_viewer_snapshot = gen_params.get("_character_viewer_snapshot") or {}
            remote_preset_axes = gen_params.get("remote_preset_axes") or []
            if isinstance(remote_preset_axes, str):
                remote_preset_axes = [item.strip() for item in remote_preset_axes.split(",") if item.strip()]
            if gen_params.get("prompt_preset_thumbnail_request"):
                try:
                    preset_name = str(gen_params.get("prompt_preset_thumbnail_name") or "")
                    preset_mode = str(gen_params.get("prompt_preset_thumbnail_mode") or "")
                    prompt_preset_thumbnail = self._save_prompt_engineering_thumbnail_image(image, preset_name, preset_mode)
                    self._broadcast_json({
                        "type": "prompt_engineering_preset_thumbnail_updated",
                        "request_id": str(gen_params.get("prompt_preset_thumbnail_request_id") or ""),
                        "message": f"{preset_name} 임시 썸네일을 업데이트했습니다.",
                        **prompt_preset_thumbnail,
                    })
                except Exception as e:
                    print(f"🌐 Remote: 프리셋 썸네일 저장 실패 — {e}")
                    self._broadcast_json({
                        "type": "toast",
                        "message": f"프리셋 썸네일 저장 실패: {e}",
                        "level": "error",
                    })
            if gen_params.get("character_viewer_request"):
                try:
                    if isinstance(character_viewer_snapshot, dict) and not character_viewer_snapshot.get("save_blocked"):
                        character_viewer_thumbnail = self._character_viewer_service.save_thumbnail(image, character_viewer_snapshot)
                except Exception as e:
                    print(f"🌐 Remote: Character Viewer 썸네일 저장 실패 — {e}")
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
                "artist_thumb_request": bool(gen_params.get("artist_thumb_request")),
                "artist_thumb_request_id": str(gen_params.get("artist_thumb_request_id") or ""),
                "artist_thumb_artist": str(gen_params.get("_remote_queue_label") or ""),
                "character_viewer_request": bool(gen_params.get("character_viewer_request")),
                "character_viewer_request_id": str(gen_params.get("character_viewer_request_id") or ""),
                "character_viewer_character": str(gen_params.get("_remote_queue_label") or ""),
                "character_viewer_group": (
                    str(character_viewer_snapshot.get("group_key") or "")
                    if isinstance(character_viewer_snapshot, dict) else ""
                ),
                "character_viewer_character_name": (
                    str(character_viewer_snapshot.get("char_name") or "")
                    if isinstance(character_viewer_snapshot, dict) else ""
                ),
                "character_viewer_variant": (
                    str(character_viewer_snapshot.get("variant_label") or "")
                    if isinstance(character_viewer_snapshot, dict) else ""
                ),
                "character_viewer_thumbnail_saved": bool(character_viewer_thumbnail),
                "character_viewer_thumbnail_url": (
                    str(character_viewer_thumbnail.get("url") or "")
                    if isinstance(character_viewer_thumbnail, dict) else ""
                ),
                "prompt_preset_thumbnail_request": bool(gen_params.get("prompt_preset_thumbnail_request")),
                "prompt_preset_thumbnail_request_id": str(gen_params.get("prompt_preset_thumbnail_request_id") or ""),
                "prompt_preset_thumbnail_name": str(gen_params.get("prompt_preset_thumbnail_name") or ""),
                "prompt_preset_thumbnail_saved": bool(prompt_preset_thumbnail),
                "prompt_preset_thumbnail_url": (
                    str(prompt_preset_thumbnail.get("thumbnail_url") or "")
                    if isinstance(prompt_preset_thumbnail, dict) else ""
                ),
                "event_preset_request": bool(gen_params.get("event_preset_request")),
                "event_preset_request_id": str(gen_params.get("event_preset_request_id") or ""),
                "remote_preset_request": bool(gen_params.get("remote_preset_request")),
                "remote_preset_request_id": str(gen_params.get("remote_preset_request_id") or ""),
                "remote_preset_axes": list(remote_preset_axes),
                "remote_queue_source": str(gen_params.get("_remote_queue_source") or ""),
            }

            # 2. /api/latest-image 호환을 위한 최신 이미지 보존 (GIL 하 atomic 대입)
            self.latest_webp = webp_bytes

            # 3. broadcast 우선 — 메인 스레드/클라이언트가 이미지를 빨리 받도록
            if self._has_clients():
                self._broadcast_json({"type": "status", "is_generating": False})
                if self._loop and self._ws_manager:
                    asyncio.run_coroutine_threadsafe(
                        self._ws_manager.broadcast_image(webp_bytes, metadata),
                        self._loop,
                    )

            # 4. 무거운 metadata payload 는 broadcast 큐잉 후에 빌드
            #    (ImageMetadataExtractor.extract_metadata 가 PIL 동기 작업 — GIL 부담)
            try:
                self.latest_metadata_payload = self._build_result_metadata_payload(image, result, webp_bytes)
            except Exception as e:
                print(f"🌐 Remote: latest_metadata_payload 빌드 실패 — {e}")
        except Exception as e:
            print(f"🌐 Remote: 이미지 변환/broadcast 실패 — {e}")

    def on_result_enhance_completed(self, success: bool = False, message: str = ""):
        """ImageWindow Enhance 완료 상태를 Web Result 버튼에 반영."""
        self._remote_enhance_in_flight = False
        self._remote_enhance_api_mode = ""
        self._remote_enhance_request_id = ""
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

    def on_result_enhance_config_changed(self, *_args, **_kwargs):
        """Desktop Enhance setting edits no longer push config to Web."""
        self._broadcast_result_enhance_config()

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
    # Windows registry MIME mappings can report .mjs as text/plain, which
    # Chromium rejects for module scripts.
    mimetypes.add_type("text/javascript", ".mjs")
    no_cache_headers = {"Cache-Control": "no-store, max-age=0"}
    image_export_base_headers = {
        "Cache-Control": "no-store",
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Expose-Headers": "Content-Disposition, Content-Type",
        "Cross-Origin-Resource-Policy": "cross-origin",
    }

    def image_export_headers(filename: str = "") -> dict:
        headers = dict(image_export_base_headers)
        if filename:
            headers["Content-Disposition"] = bridge._download_content_disposition(filename)
        return headers

    def image_export_options_headers() -> dict:
        headers = dict(image_export_base_headers)
        headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
        headers["Access-Control-Allow-Headers"] = "*"
        return headers

    def web_file(path: Path, media_type: str):
        return FileResponse(str(path), media_type=media_type, headers=no_cache_headers)

    js_dir = web_dir / "js"
    if js_dir.exists():
        app.mount("/js", StaticFiles(directory=str(js_dir)), name="remote_js")
    guides_dir = web_dir / "guides"
    if guides_dir.exists():
        app.mount("/guides", StaticFiles(directory=str(guides_dir), html=True), name="remote_guides")

    @app.get("/")
    async def index():
        html_path = web_dir / "index.html"
        if html_path.exists():
            return web_file(html_path, "text/html")
        return JSONResponse({"error": "index.html not found"}, status_code=404)

    @app.get("/style.css")
    async def serve_css():
        p = web_dir / "style.css"
        return web_file(p, "text/css") if p.exists() else JSONResponse({"error": "not found"}, 404)

    @app.get("/app.js")
    async def serve_js():
        p = web_dir / "app.js"
        return web_file(p, "application/javascript") if p.exists() else JSONResponse({"error": "not found"}, 404)

    @app.get("/api/prompt-highlight-index")
    async def api_prompt_highlight_index():
        data = await asyncio.to_thread(bridge._read_prompt_highlight_index)
        content = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        return Response(content=content, media_type="application/json", headers=no_cache_headers)

    @app.post("/api/generate")
    async def api_generate():
        bridge._pending_generate_requests.append({"ws": None, "prompt": "", "negative": ""})
        bridge.request_generate.emit()
        return {"status": "generation_requested"}

    @app.get("/api/queue/state")
    async def api_queue_state():
        return await asyncio.to_thread(bridge._build_queue_state)

    @app.get("/api/resolutions")
    async def api_resolutions(req: Request):
        result = await bridge._request_resolution_action({
            "action": "get",
            "api_mode": req.query_params.get("mode") or req.query_params.get("api_mode"),
        })
        if not result.get("ok"):
            return JSONResponse({"error": result.get("error") or "Resolution state unavailable"}, status_code=500)
        return result

    @app.post("/api/resolutions")
    async def api_save_resolutions(req: Request):
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        result = await bridge._request_resolution_action({
            "action": "save",
            "api_mode": payload.get("api_mode") or payload.get("mode"),
            "resolutions": payload.get("resolutions"),
        })
        if not result.get("ok"):
            return JSONResponse({"error": result.get("error") or "Resolution save failed"}, status_code=400)
        return result

    @app.post("/api/queue/action")
    async def api_queue_action(req: Request):
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        action = str(payload.get("action") or "").strip().lower()
        if action not in {"pause", "resume", "clear", "remove"}:
            return JSONResponse({"error": "Unsupported queue action"}, status_code=400)
        if action == "remove" and not str(payload.get("request_id") or payload.get("id") or "").strip():
            return JSONResponse({"error": "request_id is required"}, status_code=400)
        bridge.request_queue_action.emit(json.dumps(payload))
        return {"ok": True, "action": action}

    @app.post("/api/search/parquet/upload")
    async def api_search_parquet_upload(req: Request):
        action = str(req.query_params.get("action") or "").strip().lower()
        if action not in {"load", "merge"}:
            return JSONResponse({"error": "action must be load or merge"}, status_code=400)
        filename = Path(str(req.query_params.get("filename") or "uploaded.parquet")).name
        if not filename.lower().endswith(".parquet"):
            return JSONResponse({"error": "Only .parquet files are supported"}, status_code=400)
        content = await req.body()
        if not content:
            return JSONResponse({"error": "Uploaded parquet is empty"}, status_code=400)

        upload_dir = Path("save/tmp_remote_uploads")
        upload_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(delete=False, suffix=".parquet", dir=str(upload_dir)) as tmp:
            tmp.write(content)
            temp_path = Path(tmp.name)
        bridge.request_uploaded_parquet.emit(json.dumps({
            "action": action,
            "filename": filename,
            "temp_path": str(temp_path),
        }))
        return {"ok": True, "action": action, "filename": filename}

    @app.post("/api/random")
    async def api_random():
        bridge._pending_random_requests.append({"ws": None, "source_row": None, "active_ratings": set(bridge._active_ratings)})
        bridge.request_random.emit()
        return {"status": "random_generation_requested"}

    @app.post("/api/result/action/reroll")
    async def api_result_action_reroll(req: Request):
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        source_row = await asyncio.to_thread(bridge._get_result_context_source_row, payload)
        if not bridge._source_row_available(source_row):
            return JSONResponse({"error": "Reroll source is unavailable"}, status_code=400)
        bridge.request_result_reroll.emit(json.dumps(payload))
        return {"ok": True, "action": "reroll"}

    @app.post("/api/result/action/queue")
    async def api_result_action_queue(req: Request):
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        position = str(payload.get("position") or "back").strip().lower()
        if position not in {"front", "back"}:
            return JSONResponse({"error": "position must be front or back"}, status_code=400)
        queue_mode = bridge._result_queue_mode(payload)
        if queue_mode == "reopen":
            source_row = await asyncio.to_thread(bridge._get_result_context_source_row, payload)
            if not bridge._source_row_available(source_row):
                return JSONResponse({"error": "P.Eng / WC source row is unavailable"}, status_code=400)
        if queue_mode == "current_character" and bridge._current_api_mode() != "NAI":
            return JSONResponse({"error": "Current character queue is only available in NAI mode"}, status_code=400)
        params = await asyncio.to_thread(bridge._result_context_generation_params, payload)
        if not params:
            return JSONResponse({"error": "Queue source params are unavailable"}, status_code=400)
        bridge.request_result_queue.emit(json.dumps(payload))
        return {"ok": True, "action": "queue", "position": position, "queue_mode": queue_mode}

    @app.post("/api/result/action/save")
    async def api_result_action_save(req: Request):
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        result = await bridge._request_result_history_action("save", payload)
        if not result.get("ok"):
            return JSONResponse({"error": result.get("error") or "Image save failed"}, status_code=400)
        return result

    @app.post("/api/result/action/delete")
    async def api_result_action_delete(req: Request):
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        result = await bridge._request_result_history_action("delete", payload)
        if not result.get("ok"):
            return JSONResponse({"error": result.get("error") or "History delete failed"}, status_code=400)
        return result

    @app.post("/api/history/unsaved/save-all")
    async def api_history_unsaved_save_all():
        result = await bridge._request_result_history_action("save_all_unsaved", {}, timeout=300.0)
        if not result.get("ok"):
            return JSONResponse({
                "error": result.get("error") or "Some images could not be saved",
                **{key: result[key] for key in ("saved", "requested", "remaining", "failures") if key in result},
            }, status_code=400)
        return result

    @app.get("/api/history/unsaved/download")
    async def api_history_unsaved_download():
        result = await bridge._request_result_history_action("collect_unsaved_download", {}, timeout=120.0)
        if not result.get("ok"):
            return JSONResponse({"error": result.get("error") or "History download failed"}, status_code=400)
        entries = result.get("entries") if isinstance(result.get("entries"), list) else []
        if not entries:
            return JSONResponse({"error": "No unsaved history images"}, status_code=404)

        zip_buffer = io.BytesIO()
        used_names = set()
        with zipfile.ZipFile(zip_buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for index, entry in enumerate(entries, start=1):
                raw_name = Path(str(entry.get("filename") or f"history-{index:04d}.png")).name
                if not raw_name:
                    raw_name = f"history-{index:04d}.png"
                stem = Path(raw_name).stem or f"history-{index:04d}"
                suffix = Path(raw_name).suffix or ".png"
                filename = raw_name
                counter = 2
                while filename in used_names:
                    filename = f"{stem}-{counter}{suffix}"
                    counter += 1
                used_names.add(filename)
                zf.writestr(filename, bytes(entry.get("bytes") or b""))
        zip_buffer.seek(0)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return Response(
            content=zip_buffer.getvalue(),
            media_type="application/zip",
            headers=image_export_headers(f"naia-unsaved-history-{timestamp}.zip"),
        )

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
            bridge._clear_comfyui_random_request(request_id)
            return JSONResponse({"error": "timeout"}, status_code=504)
        except Exception as e:
            bridge._clear_comfyui_random_request(request_id)
            return JSONResponse({"error": str(e)}, status_code=500)

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

    @app.get("/api/comfyui/workflow/state")
    async def api_comfyui_workflow_state():
        return await asyncio.to_thread(bridge._comfyui_workflow_state_payload)

    @app.get("/api/comfyui/web")
    async def api_comfyui_web():
        stm = bridge.app_context.secure_token_manager
        url = str(stm.get_token("comfyui_url") or "").strip()
        if not url:
            return JSONResponse({"ok": False, "error": "ComfyUI URL is not configured"}, status_code=404)
        if not url.startswith(("http://", "https://")):
            url = f"http://{url}"
        return RedirectResponse(url)

    @app.post("/api/comfyui/workflow/upload")
    async def api_comfyui_workflow_upload(req: Request):
        image_bytes = await req.body()
        max_bytes = 64 * 1024 * 1024
        if len(image_bytes) > max_bytes:
            return JSONResponse({"ok": False, "error": "Image is too large"}, status_code=413)
        try:
            metadata = await asyncio.to_thread(bridge._extract_comfyui_workflow_metadata_from_png_bytes, image_bytes)
        except ValueError as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=400)
        try:
            result = await bridge._request_comfyui_workflow_action("load", metadata=metadata)
        except asyncio.TimeoutError:
            return JSONResponse({"ok": False, "error": "ComfyUI workflow upload timed out"}, status_code=504)
        if not result.get("ok"):
            return JSONResponse(result, status_code=400)
        return result

    @app.post("/api/comfyui/workflow/default")
    async def api_comfyui_workflow_default():
        try:
            result = await bridge._request_comfyui_workflow_action("clear")
        except asyncio.TimeoutError:
            return JSONResponse({"ok": False, "error": "ComfyUI workflow switch timed out"}, status_code=504)
        if not result.get("ok"):
            return JSONResponse(result, status_code=400)
        return result

    @app.get("/api/status")
    async def api_status():
        try:
            gc = bridge.app_context.main_window.generation_controller
            return {
                "is_generating": gc.is_generating,
                "api_mode": bridge.app_context.get_api_mode(),
                "autocomplete": bridge._autocomplete_status_payload(),
            }
        except Exception:
            return {
                "is_generating": False,
                "api_mode": "unknown",
                "autocomplete": bridge._autocomplete_status_payload(),
            }

    @app.get("/api/latest-image")
    async def api_latest_image():
        if bridge.latest_webp is None:
            return JSONResponse({"error": "No image generated yet"}, status_code=404, headers=image_export_headers())
        return Response(
            content=bridge.latest_webp,
            media_type="image/webp",
            headers=image_export_headers("naia_latest.webp"),
        )

    @app.options("/api/result/image/png")
    async def api_result_image_png_options():
        return Response(status_code=204, headers=image_export_options_headers())

    @app.get("/api/result/image/png")
    async def api_result_image_png(source: str = "", path: str = ""):
        try:
            png_bytes, filename = await asyncio.to_thread(bridge._build_result_png_payload, source, path)
        except FileNotFoundError as e:
            return JSONResponse({"error": str(e)}, status_code=404, headers=image_export_headers())
        except Exception as e:
            return JSONResponse({"error": f"PNG export failed: {e}"}, status_code=500, headers=image_export_headers())

        return Response(
            content=png_bytes,
            media_type="image/png",
            headers=image_export_headers(filename),
        )

    @app.options("/api/result/image/original")
    async def api_result_image_original_options():
        return Response(status_code=204, headers=image_export_options_headers())

    @app.get("/api/result/image/original")
    async def api_result_image_original(source: str = "", path: str = ""):
        target = await asyncio.to_thread(bridge._resolve_result_original_file, source, path)
        if target:
            return FileResponse(
                str(target),
                media_type=bridge._image_media_type_for_path(target),
                filename=target.name,
                headers=image_export_headers(),
            )
        normalized_source = str(source or "").strip().lower()
        requested_path = str(path or "").strip()
        can_use_latest_fallback = not requested_path and normalized_source in {"", "current"}
        if can_use_latest_fallback and bridge.latest_webp is not None:
            return Response(
                content=bridge.latest_webp,
                media_type="image/webp",
                headers=image_export_headers("naia_latest.webp"),
            )
        return JSONResponse({"error": "No original image is available"}, status_code=404, headers=image_export_headers())

    @app.post("/api/result/clipboard/png")
    async def api_result_clipboard_png(req: Request):
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        source = str(payload.get("source") or "")
        path = str(payload.get("path") or "")
        try:
            png_bytes, filename = await asyncio.to_thread(bridge._build_result_png_payload, source, path)
        except FileNotFoundError as e:
            return JSONResponse({"error": str(e)}, status_code=404)
        except Exception as e:
            return JSONResponse({"error": f"PNG clipboard payload failed: {e}"}, status_code=500)

        bridge.request_copy_png_to_clipboard.emit(png_bytes, filename)
        try:
            copied_bytes = await bridge._request_clipboard_png(timeout=2.0)
        except asyncio.TimeoutError:
            return JSONResponse({"error": "PNG clipboard copy timed out"}, status_code=504)
        except Exception as e:
            return JSONResponse({"error": f"PNG clipboard copy verification failed: {e}"}, status_code=500)
        if copied_bytes != png_bytes:
            return JSONResponse({"error": "PNG clipboard copy verification failed: clipboard payload mismatch"}, status_code=500)
        return {
            "ok": True,
            "filename": filename,
            "bytes": len(png_bytes),
        }

    @app.get("/api/clipboard/png")
    async def api_clipboard_png():
        try:
            png_bytes = await bridge._request_clipboard_png()
        except FileNotFoundError as e:
            return JSONResponse({"error": str(e)}, status_code=404)
        except asyncio.TimeoutError:
            return JSONResponse({"error": "Clipboard read timed out"}, status_code=504)
        except Exception as e:
            return JSONResponse({"error": f"Clipboard read failed: {e}"}, status_code=500)
        return Response(
            content=png_bytes,
            media_type="image/png",
            headers={"Cache-Control": "no-store"},
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
        if action in {"img2img", "inpaint"}:
            allowed, reason = bridge._desktop_img2img_gate(bridge._request_client_host(req))
            if not allowed:
                return JSONResponse({"error": reason}, status_code=403)
            allowed, reason = bridge._nai_img2img_mode_gate()
            if not allowed:
                return JSONResponse({"error": reason}, status_code=403)
        image_bytes = await req.body()
        if not image_bytes:
            return JSONResponse({"error": "No image data"}, status_code=400)
        max_bytes = 64 * 1024 * 1024
        if len(image_bytes) > max_bytes:
            return JSONResponse({"error": "Image is too large"}, status_code=413)
        label = (req.query_params.get("label") or "Input Image")[:120]
        bridge.request_image_action.emit(action, image_bytes, label)
        return {"ok": True, "action": action}

    @app.post("/api/danbooru/post")
    async def api_danbooru_post(req: Request):
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        query = str(payload.get("query") or req.query_params.get("query") or "").strip()
        try:
            return await asyncio.to_thread(bridge._build_danbooru_post_payload, query)
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=400)
        except Exception as e:
            return JSONResponse({"error": f"Danbooru lookup failed: {e}"}, status_code=502)

    @app.post("/api/danbooru/browser/open")
    async def api_danbooru_browser_open(req: Request):
        allowed, reason = bridge._desktop_browser_gate(bridge._request_client_host(req))
        if not allowed:
            return JSONResponse({"error": reason}, status_code=403)
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        query = str(payload.get("url") or payload.get("query") or req.query_params.get("url") or "").strip()
        try:
            target_url = bridge._normalize_danbooru_browser_url(query)
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=400)
        bridge.request_open_danbooru_browser.emit(target_url)
        return {"ok": True, "url": target_url}

    @app.get("/api/thumb/state")
    async def api_thumb_state():
        try:
            return await asyncio.to_thread(bridge._build_thumb_tab_state)
        except FileNotFoundError as e:
            return JSONResponse({"error": str(e)}, status_code=404)
        except Exception as e:
            return JSONResponse({"error": f"Thumb state failed: {e}"}, status_code=500)

    @app.get("/api/thumb/category/{category_key}")
    async def api_thumb_category(category_key: str):
        try:
            return await asyncio.to_thread(bridge._build_thumb_category_payload, category_key)
        except KeyError as e:
            return JSONResponse({"error": str(e)}, status_code=404)
        except FileNotFoundError as e:
            return JSONResponse({"error": str(e)}, status_code=404)
        except Exception as e:
            return JSONResponse({"error": f"Thumb category failed: {e}"}, status_code=500)

    @app.get("/api/thumb/image")
    async def api_thumb_image(tag: str = ""):
        try:
            image_bytes, media_type = await asyncio.to_thread(bridge._build_thumb_image_payload, tag)
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=400)
        except FileNotFoundError as e:
            return JSONResponse({"error": str(e)}, status_code=404)
        except Exception as e:
            return JSONResponse({"error": f"Thumb image failed: {e}"}, status_code=500)
        return Response(
            content=image_bytes,
            media_type=media_type,
            headers={"Cache-Control": "public, max-age=3600"},
        )

    @app.get("/api/artist-thumb/state")
    async def api_artist_thumb_state():
        try:
            return await asyncio.to_thread(bridge._build_artist_thumb_state)
        except Exception as e:
            return JSONResponse({"error": f"Artist Thumb state failed: {e}"}, status_code=500)

    @app.get("/api/artist-thumb/list")
    async def api_artist_thumb_list(
        mode: str = "",
        filter: str = "all",
        query: str = "",
        page: int = 0,
        per_page: int = 48,
        random_sample: bool = False,
    ):
        try:
            return await asyncio.to_thread(
                bridge._build_artist_thumb_list,
                mode,
                filter,
                query,
                page,
                per_page,
                random_sample,
            )
        except FileNotFoundError as e:
            return JSONResponse({"error": str(e)}, status_code=404)
        except KeyError as e:
            return JSONResponse({"error": str(e)}, status_code=404)
        except Exception as e:
            return JSONResponse({"error": f"Artist Thumb list failed: {e}"}, status_code=500)

    @app.get("/api/artist-thumb/image")
    async def api_artist_thumb_image(mode: str = "", artist: str = ""):
        try:
            image_bytes, media_type = await asyncio.to_thread(
                bridge._build_artist_thumb_image_payload,
                mode,
                artist,
            )
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=400)
        except (FileNotFoundError, KeyError) as e:
            return JSONResponse({"error": str(e)}, status_code=404)
        except Exception as e:
            return JSONResponse({"error": f"Artist Thumb image failed: {e}"}, status_code=500)
        return Response(
            content=image_bytes,
            media_type=media_type,
            headers={"Cache-Control": "public, max-age=3600"},
        )

    @app.get("/api/artist-thumb/favorite-image")
    async def api_artist_thumb_favorite_image(artist: str = ""):
        try:
            image_bytes, media_type = await asyncio.to_thread(
                bridge._build_artist_thumb_favorite_image_payload,
                artist,
            )
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=400)
        except (FileNotFoundError, KeyError) as e:
            return JSONResponse({"error": str(e)}, status_code=404)
        except Exception as e:
            return JSONResponse({"error": f"Artist Thumb favorite image failed: {e}"}, status_code=500)
        return Response(
            content=image_bytes,
            media_type=media_type,
            headers={"Cache-Control": "public, max-age=3600"},
        )

    @app.post("/api/artist-thumb/favorite")
    async def api_artist_thumb_favorite(req: Request):
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        try:
            return await asyncio.to_thread(
                bridge._set_artist_thumb_favorite,
                payload.get("artist", ""),
                bool(payload.get("favorite", True)),
                payload.get("mode", ""),
            )
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=400)
        except Exception as e:
            return JSONResponse({"error": f"Artist Thumb favorite failed: {e}"}, status_code=500)

    @app.post("/api/artist-thumb/ban")
    async def api_artist_thumb_ban(req: Request):
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        try:
            return await asyncio.to_thread(
                bridge._set_artist_thumb_banned,
                payload.get("artist", ""),
                bool(payload.get("banned", True)),
            )
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=400)
        except Exception as e:
            return JSONResponse({"error": f"Artist Thumb ban failed: {e}"}, status_code=500)

    @app.post("/api/artist-thumb/options")
    async def api_artist_thumb_options(req: Request):
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        try:
            return await asyncio.to_thread(bridge._save_artist_thumb_options, payload)
        except Exception as e:
            return JSONResponse({"error": f"Artist Thumb options failed: {e}"}, status_code=500)

    @app.get("/api/artist-thumb/download")
    async def api_artist_thumb_download_state():
        try:
            return await asyncio.to_thread(bridge._artist_thumb_download_snapshot)
        except Exception as e:
            return JSONResponse({"error": f"Artist Thumb download state failed: {e}"}, status_code=500)

    @app.post("/api/artist-thumb/download")
    async def api_artist_thumb_download(req: Request):
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        try:
            return await asyncio.to_thread(bridge._start_artist_thumb_download, payload.get("mode", ""))
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=400)
        except KeyError as e:
            return JSONResponse({"error": str(e)}, status_code=404)
        except Exception as e:
            return JSONResponse({"error": f"Artist Thumb download failed: {e}"}, status_code=500)

    @app.post("/api/artist-thumb/download/cancel")
    async def api_artist_thumb_download_cancel():
        try:
            return await asyncio.to_thread(bridge._cancel_artist_thumb_download)
        except Exception as e:
            return JSONResponse({"error": f"Artist Thumb download cancel failed: {e}"}, status_code=500)

    @app.post("/api/artist-thumb/random-prompt")
    async def api_artist_thumb_random_prompt(req: Request):
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        artist_prompt = str(payload.get("artist_prompt") or "").strip()
        if not artist_prompt:
            return JSONResponse({"error": "artist_prompt is required"}, status_code=400)
        try:
            timeout = max(5.0, min(60.0, float(payload.get("timeout", 30))))
        except (TypeError, ValueError):
            timeout = 30.0

        try:
            peng_override = await bridge._request_artist_thumb_random_peng_override(
                artist_prompt,
                timeout=min(5.0, timeout),
            )
        except asyncio.TimeoutError:
            return JSONResponse({"error": "prompt_engineering snapshot timeout"}, status_code=504)
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=400)

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
            "artist_thumb_random_prompt": True,
            "respect_naia_autogen": False,
            "force_naia_skip_generate": True,
            "peng_override": peng_override,
        })
        bridge.request_random.emit()

        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            bridge._clear_comfyui_random_request(request_id)
            return JSONResponse({"error": "timeout"}, status_code=504)
        except Exception as e:
            bridge._clear_comfyui_random_request(request_id)
            return JSONResponse({"error": str(e)}, status_code=500)

    @app.post("/api/artist-thumb/generate")
    async def api_artist_thumb_generate(req: Request):
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        if not bridge._artist_thumb_final_prompt(payload):
            return JSONResponse({"error": "prompt is empty"}, status_code=400)
        bridge.request_artist_thumb_generate.emit(payload)
        return {"ok": True}

    @app.get("/api/character-viewer/state")
    async def api_character_viewer_state():
        try:
            return await asyncio.to_thread(bridge._character_viewer_state)
        except Exception as e:
            return JSONResponse({"error": f"Character Viewer state failed: {e}"}, status_code=500)

    @app.get("/api/character-viewer/groups")
    async def api_character_viewer_groups(query: str = ""):
        try:
            return await asyncio.to_thread(bridge._character_viewer_groups, query)
        except Exception as e:
            return JSONResponse({"error": f"Character Viewer groups failed: {e}"}, status_code=500)

    @app.get("/api/character-viewer/list")
    async def api_character_viewer_list(
        group: str = "",
        query: str = "",
        page: int = 0,
        per_page: int = 48,
        thumb_first: bool = True,
        include_all: bool = False,
    ):
        try:
            return await asyncio.to_thread(
                bridge._character_viewer_list,
                group,
                query,
                page,
                per_page,
                thumb_first,
                include_all,
            )
        except Exception as e:
            return JSONResponse({"error": f"Character Viewer list failed: {e}"}, status_code=500)

    @app.post("/api/character-viewer/detail")
    async def api_character_viewer_detail(req: Request):
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        try:
            return await asyncio.to_thread(
                bridge._character_viewer_detail,
                payload.get("group", ""),
                payload.get("character", ""),
                payload.get("variant", ""),
                payload.get("options") if isinstance(payload.get("options"), dict) else {},
            )
        except KeyError as e:
            return JSONResponse({"error": str(e)}, status_code=404)
        except Exception as e:
            return JSONResponse({"error": f"Character Viewer detail failed: {e}"}, status_code=500)

    @app.post("/api/character-viewer/prompt")
    async def api_character_viewer_prompt(req: Request):
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        try:
            return await asyncio.to_thread(bridge._character_viewer_prompt, payload)
        except KeyError as e:
            return JSONResponse({"error": str(e)}, status_code=404)
        except Exception as e:
            return JSONResponse({"error": f"Character Viewer prompt failed: {e}"}, status_code=500)

    @app.post("/api/character-viewer/options")
    async def api_character_viewer_options(req: Request):
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        try:
            return await asyncio.to_thread(bridge._character_viewer_save_options, payload)
        except Exception as e:
            return JSONResponse({"error": f"Character Viewer options failed: {e}"}, status_code=500)

    @app.get("/api/character-viewer/thumbnail")
    async def api_character_viewer_thumbnail(group: str = "", character: str = "", variant: str = "", size: str = ""):
        try:
            image_bytes, media_type = await asyncio.to_thread(
                bridge._character_viewer_thumbnail_payload,
                group,
                character,
                variant,
                size,
            )
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=400)
        except (FileNotFoundError, KeyError) as e:
            return JSONResponse({"error": str(e)}, status_code=404)
        except Exception as e:
            return JSONResponse({"error": f"Character Viewer thumbnail failed: {e}"}, status_code=500)
        return Response(
            content=image_bytes,
            media_type=media_type,
            headers={"Cache-Control": "public, max-age=3600"},
        )

    @app.get("/api/event-preset/status")
    async def api_event_preset_status():
        try:
            return await asyncio.to_thread(bridge._event_preset_status)
        except Exception as e:
            return JSONResponse({"error": f"Event Preset status failed: {e}"}, status_code=500)

    @app.get("/api/event-preset/download")
    async def api_event_preset_download_state():
        try:
            return await asyncio.to_thread(bridge._event_preset_download_snapshot)
        except Exception as e:
            return JSONResponse({"error": f"Event Preset download state failed: {e}"}, status_code=500)

    @app.post("/api/event-preset/download")
    async def api_event_preset_download():
        try:
            return await asyncio.to_thread(bridge._start_event_preset_download)
        except Exception as e:
            return JSONResponse({"error": f"Event Preset download failed: {e}"}, status_code=500)

    @app.post("/api/event-preset/download/cancel")
    async def api_event_preset_download_cancel():
        try:
            return await asyncio.to_thread(bridge._cancel_event_preset_download)
        except Exception as e:
            return JSONResponse({"error": f"Event Preset download cancel failed: {e}"}, status_code=500)

    @app.get("/api/tag/lookup")
    async def api_tag_lookup(tag: str = ""):
        try:
            return await asyncio.to_thread(bridge._lookup_tag_info, tag)
        except Exception as e:
            return JSONResponse({"error": f"Tag lookup failed: {e}"}, status_code=500)

    @app.get("/api/event-preset/bootstrap")
    async def api_event_preset_bootstrap(
        ratingId: str = "s",
        personId: str = "1girl_solo",
        search: str = "",
        categoryId: str = "",
        subcategoryId: str = "",
        eventId: str = "",
        limit: int = 0,
    ):
        try:
            return await asyncio.to_thread(
                bridge._event_preset_bootstrap,
                ratingId,
                personId,
                search,
                categoryId,
                subcategoryId,
                eventId,
                limit or None,
            )
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=400)
        except Exception as e:
            return JSONResponse({"error": f"Event Preset bootstrap failed: {e}"}, status_code=500)

    @app.post("/api/event-preset/select")
    async def api_event_preset_select(req: Request):
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        try:
            return await asyncio.to_thread(bridge._event_preset_select, payload)
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=400)
        except KeyError as e:
            return JSONResponse({"error": str(e)}, status_code=404)
        except Exception as e:
            return JSONResponse({"error": f"Event Preset select failed: {e}"}, status_code=500)

    @app.post("/api/event-preset/prompt-preview")
    async def api_event_preset_prompt_preview(req: Request):
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        try:
            return await asyncio.to_thread(bridge._event_preset_prompt_preview, payload)
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=400)
        except Exception as e:
            return JSONResponse({"error": f"Event Preset prompt preview failed: {e}"}, status_code=500)

    @app.post("/api/preset/prompt-preview")
    async def api_preset_prompt_preview(req: Request):
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        try:
            return await asyncio.to_thread(bridge._preset_prompt_preview, payload)
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=400)
        except Exception as e:
            return JSONResponse({"error": f"Preset prompt preview failed: {e}"}, status_code=500)

    @app.post("/api/preset/generate")
    async def api_preset_generate(req: Request):
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        try:
            return await asyncio.to_thread(bridge._preset_generate, payload)
        except RuntimeError as e:
            return JSONResponse({"error": str(e)}, status_code=409)
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=400)
        except KeyError as e:
            return JSONResponse({"error": str(e)}, status_code=404)
        except Exception as e:
            return JSONResponse({"error": f"Preset generate failed: {e}"}, status_code=500)

    @app.get("/api/clothes-preset/status")
    async def api_clothes_preset_status():
        try:
            return await asyncio.to_thread(bridge._clothes_preset_status)
        except Exception as e:
            return JSONResponse({"error": f"Clothes Preset status failed: {e}"}, status_code=500)

    @app.post("/api/clothes-preset/bootstrap")
    async def api_clothes_preset_bootstrap(req: Request):
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        try:
            return await asyncio.to_thread(bridge._clothes_preset_bootstrap, payload)
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=400)
        except Exception as e:
            return JSONResponse({"error": f"Clothes Preset bootstrap failed: {e}"}, status_code=500)

    @app.post("/api/clothes-preset/select")
    async def api_clothes_preset_select(req: Request):
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        try:
            return await asyncio.to_thread(bridge._clothes_preset_select, payload)
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=400)
        except Exception as e:
            return JSONResponse({"error": f"Clothes Preset select failed: {e}"}, status_code=500)

    @app.post("/api/clothes-preset/lucky")
    async def api_clothes_preset_lucky(req: Request):
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        try:
            return await asyncio.to_thread(bridge._clothes_preset_lucky, payload)
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=400)
        except Exception as e:
            return JSONResponse({"error": f"Clothes Preset lucky failed: {e}"}, status_code=500)

    @app.post("/api/clothes-preset/prompt-fragment")
    async def api_clothes_preset_prompt_fragment(req: Request):
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        try:
            return await asyncio.to_thread(bridge._clothes_preset_prompt_fragment, payload)
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=400)
        except Exception as e:
            return JSONResponse({"error": f"Clothes Preset prompt fragment failed: {e}"}, status_code=500)

    @app.get("/api/expression-preset/status")
    async def api_expression_preset_status():
        try:
            return await asyncio.to_thread(bridge._expression_preset_status)
        except Exception as e:
            return JSONResponse({"error": f"Expression Preset status failed: {e}"}, status_code=500)

    @app.post("/api/expression-preset/bootstrap")
    async def api_expression_preset_bootstrap(req: Request):
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        try:
            return await asyncio.to_thread(bridge._expression_preset_bootstrap, payload)
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=400)
        except Exception as e:
            return JSONResponse({"error": f"Expression Preset bootstrap failed: {e}"}, status_code=500)

    @app.post("/api/event-preset/generate")
    async def api_event_preset_generate(req: Request):
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        try:
            return await asyncio.to_thread(bridge._event_preset_generate, payload)
        except RuntimeError as e:
            return JSONResponse({"error": str(e)}, status_code=409)
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=400)
        except KeyError as e:
            return JSONResponse({"error": str(e)}, status_code=404)
        except Exception as e:
            return JSONResponse({"error": f"Event Preset generate failed: {e}"}, status_code=500)

    @app.get("/api/event-preset/thumbnail")
    async def api_event_preset_thumbnail(eventId: str = "", tag: str = "", size: str = ""):
        try:
            image_bytes, media_type = await asyncio.to_thread(
                bridge._event_preset_thumbnail_payload,
                eventId,
                tag,
                size,
            )
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=400)
        except (FileNotFoundError, KeyError) as e:
            return JSONResponse({"error": str(e)}, status_code=404)
        except Exception as e:
            return JSONResponse({"error": f"Event Preset thumbnail failed: {e}"}, status_code=500)
        return Response(
            content=image_bytes,
            media_type=media_type,
            headers={"Cache-Control": "public, max-age=3600"},
        )

    @app.get("/api/prompt-engineering/preset-thumbnail")
    async def api_prompt_engineering_preset_thumbnail(name: str = "", mode: str = ""):
        try:
            target = await asyncio.to_thread(
                bridge._prompt_engineering_preview_path,
                name,
                mode,
            )
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=400)
        if not target:
            return JSONResponse({"error": "Preset thumbnail not found"}, status_code=404)
        return FileResponse(
            str(target),
            media_type=bridge._image_media_type_for_path(target),
            headers=no_cache_headers,
        )

    @app.post("/api/prompt-engineering/preset-thumbnail/upload")
    async def api_prompt_engineering_preset_thumbnail_upload(req: Request, name: str = "", mode: str = ""):
        try:
            image_bytes = await req.body()
            return await asyncio.to_thread(
                bridge._save_prompt_engineering_thumbnail_bytes,
                name,
                mode,
                image_bytes,
            )
        except ValueError as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=400)
        except Exception as e:
            return JSONResponse({"ok": False, "error": f"Preset thumbnail upload failed: {e}"}, status_code=500)

    @app.post("/api/prompt-engineering/preset-thumbnail/generate")
    async def api_prompt_engineering_preset_thumbnail_generate(req: Request):
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        try:
            return await asyncio.to_thread(
                bridge._request_prompt_engineering_thumbnail_generation_threadsafe,
                payload,
            )
        except FileNotFoundError as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=404)
        except ValueError as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=400)
        except Exception as e:
            return JSONResponse({"ok": False, "error": f"Preset thumbnail generation failed: {e}"}, status_code=500)

    @app.post("/api/character-viewer/generate")
    async def api_character_viewer_generate(req: Request):
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        if not payload.get("request_id"):
            return JSONResponse({"error": "request_id is required"}, status_code=400)
        if not (payload.get("character_prompt") or payload.get("prefix") or payload.get("postfix")):
            return JSONResponse({"error": "prompt is empty"}, status_code=400)
        bridge.request_character_viewer_generate.emit(payload)
        return {"ok": True}

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

    @app.post("/api/image/fetch")
    async def api_image_fetch(req: Request):
        try:
            payload = await req.json()
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        url = str(payload.get("url") or req.query_params.get("url") or "").strip()
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return JSONResponse({"error": "Only http/https image URLs are supported"}, status_code=400)

        max_bytes = 64 * 1024 * 1024

        def _validate_public_url(candidate_url: str):
            import ipaddress
            import socket

            candidate = urlparse(candidate_url)
            if candidate.scheme not in {"http", "https"} or not candidate.hostname:
                raise ValueError("Only http/https image URLs are supported")
            try:
                addresses = socket.getaddrinfo(
                    candidate.hostname,
                    candidate.port or (443 if candidate.scheme == "https" else 80),
                    type=socket.SOCK_STREAM,
                )
            except OSError as e:
                raise ValueError(f"Could not resolve image host: {e}") from e
            for address in addresses:
                ip = ipaddress.ip_address(address[4][0])
                if (
                    ip.is_private
                    or ip.is_loopback
                    or ip.is_link_local
                    or ip.is_multicast
                    or ip.is_reserved
                    or ip.is_unspecified
                ):
                    raise ValueError("Private network image URLs are not supported")
            return candidate

        def _fetch_remote_image():
            import requests
            from PIL import Image

            current_url = url
            response = None
            for _ in range(5):
                current = _validate_public_url(current_url)
                headers = {
                    "User-Agent": "Mozilla/5.0 (compatible; NAIA-Remote/1.0)",
                    "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
                    "Referer": f"{current.scheme}://{current.netloc}/",
                }
                response = requests.get(
                    current_url,
                    headers=headers,
                    timeout=(5, 20),
                    stream=True,
                    allow_redirects=False,
                )
                if response.is_redirect or response.is_permanent_redirect:
                    location = response.headers.get("location")
                    response.close()
                    if not location:
                        raise ValueError("Image URL redirected without a location")
                    current_url = urljoin(current_url, location)
                    continue
                break
            else:
                raise ValueError("Too many redirects")

            if response is None:
                raise ValueError("Could not fetch image")

            with response:
                if response.status_code >= 400:
                    raise ValueError(f"HTTP {response.status_code}")
                content_length = response.headers.get("content-length")
                if content_length and int(content_length) > max_bytes:
                    raise ValueError("Image is too large")
                media_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                chunks = []
                total = 0
                for chunk in response.iter_content(chunk_size=65536):
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > max_bytes:
                        raise ValueError("Image is too large")
                    chunks.append(chunk)
                image_bytes = b"".join(chunks)

            if not media_type.startswith("image/"):
                try:
                    with Image.open(io.BytesIO(image_bytes)) as img:
                        fmt = (img.format or "").lower()
                    media_type = {
                        "jpeg": "image/jpeg",
                        "jpg": "image/jpeg",
                        "png": "image/png",
                        "webp": "image/webp",
                        "gif": "image/gif",
                        "bmp": "image/bmp",
                        "tiff": "image/tiff",
                    }.get(fmt, "")
                except Exception:
                    media_type = ""
            if not media_type.startswith("image/"):
                raise ValueError("URL did not return an image")
            return image_bytes, media_type

        try:
            image_bytes, media_type = await asyncio.to_thread(_fetch_remote_image)
            return Response(
                content=image_bytes,
                media_type=media_type,
                headers={"Cache-Control": "no-store"},
            )
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=400)

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
    async def viewer_list(page: int = 0, per_page: int = 30, scope: str = "memory"):
        if str(scope or "").lower() in {"disk", "saved", "all"}:
            entries = await asyncio.to_thread(bridge._scan_save_folder)
            resolved_scope = "disk"
        else:
            entries = await asyncio.to_thread(bridge._scan_memory_history)
            resolved_scope = "memory"
        start = page * per_page
        end = start + per_page
        return {
            "total": len(entries),
            "page": page,
            "per_page": per_page,
            "scope": resolved_scope,
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

    # --- History REST API ---

    @app.get("/api/history/list")
    async def history_list(page: int = 0, per_page: int = 30):
        page = max(0, int(page or 0))
        per_page = min(max(1, int(per_page or 30)), 100)
        entries = await asyncio.to_thread(bridge._scan_memory_history)
        start = page * per_page
        end = start + per_page
        return {
            "total": len(entries),
            "page": page,
            "per_page": per_page,
            "scope": "memory",
            "images": entries[start:end],
        }

    @app.get("/api/history/thumb/{history_id}")
    async def history_thumb(history_id: str, size: int = 0):
        item = await asyncio.to_thread(bridge._find_history_item_by_id, history_id)
        if not item:
            return JSONResponse({"error": "not found"}, 404)
        if size > 0:
            size = min(max(size, 50), 1024)
        thumb_bytes = await asyncio.to_thread(bridge._history_item_thumbnail, item, size)
        if not thumb_bytes:
            return JSONResponse({"error": "thumbnail failed"}, 500)
        return Response(content=thumb_bytes, media_type="image/webp")

    @app.get("/api/history/image/{history_id}")
    async def history_image(history_id: str):
        item = await asyncio.to_thread(bridge._find_history_item_by_id, history_id)
        if not item:
            return JSONResponse({"error": "not found"}, 404)
        try:
            image_bytes, media_type = await asyncio.to_thread(bridge._history_item_image_payload, item)
        except FileNotFoundError:
            return JSONResponse({"error": "not found"}, 404)
        return Response(content=image_bytes, media_type=media_type)

    @app.get("/api/history/meta/{history_id}")
    async def history_meta(history_id: str, full: bool = False):
        item = await asyncio.to_thread(bridge._find_history_item_by_id, history_id)
        if not item:
            return JSONResponse({"error": "not found"}, 404)
        return await asyncio.to_thread(bridge._history_item_meta_payload, item, full)

    @app.post("/api/history/open-folder")
    async def history_open_folder():
        return await viewer_open_folder()

    @app.post("/api/result/open-location")
    async def api_result_open_location(req: Request):
        try:
            body = await req.json()
        except Exception:
            body = {}

        target = None
        rel_path = str(body.get("path") or "").strip()
        if rel_path:
            target = bridge._validate_viewer_path(rel_path)
        else:
            asset = await asyncio.to_thread(bridge._build_current_result_asset_payload)
            file_path = asset.get("file_path") if isinstance(asset, dict) else ""
            if file_path:
                target = Path(file_path)

        if not target or not Path(target).is_file():
            return JSONResponse({"error": "Image file is unavailable"}, status_code=404)

        history_item = await asyncio.to_thread(bridge._find_history_item_by_path, rel_path=rel_path) if rel_path else None
        if not history_item:
            try:
                save_dir = bridge._get_viewer_save_dir().resolve()
                Path(target).resolve().relative_to(save_dir)
            except Exception:
                return JSONResponse({"error": "Image file is outside the result folder"}, status_code=400)

        await asyncio.to_thread(bridge._open_path_location, Path(target))
        return {"ok": True}

    @app.get("/api/viewer/thumb/{path:path}")
    async def viewer_thumb(path: str, size: int = 0):
        history_item = await asyncio.to_thread(bridge._find_history_item_by_rel_path, path)
        target = await asyncio.to_thread(bridge._validate_viewer_path, path)
        if not target and not history_item:
            return JSONResponse({"error": "not found"}, 404)
        # size=0: 원본의 절반 (서버에서 자동 결정)
        if size > 0:
            size = min(max(size, 50), 1024)
        if history_item:
            thumb_bytes = await asyncio.to_thread(bridge._history_item_thumbnail, history_item, size)
        else:
            thumb_bytes = await asyncio.to_thread(bridge._get_or_create_thumbnail, target, size)
        if not thumb_bytes:
            return JSONResponse({"error": "thumbnail failed"}, 500)
        return Response(content=thumb_bytes, media_type="image/webp")

    @app.get("/api/viewer/image/{path:path}")
    async def viewer_image(path: str):
        history_item = await asyncio.to_thread(bridge._find_history_item_by_rel_path, path)
        target = await asyncio.to_thread(bridge._validate_viewer_path, path)
        if history_item and not target:
            try:
                image_bytes, media_type = await asyncio.to_thread(bridge._history_item_image_payload, history_item)
            except FileNotFoundError:
                return JSONResponse({"error": "not found"}, 404)
            return Response(content=image_bytes, media_type=media_type)
        if not target:
            return JSONResponse({"error": "not found"}, 404)
        return FileResponse(str(target), media_type=bridge._image_media_type_for_path(target))

    @app.get("/api/viewer/meta")
    async def viewer_meta_query(path: str, full: bool = False):
        return await viewer_meta(path, full)

    @app.get("/api/viewer/meta/{path:path}")
    async def viewer_meta(path: str, full: bool = False):
        history_item = await asyncio.to_thread(bridge._find_history_item_by_rel_path, path)
        target = await asyncio.to_thread(bridge._validate_viewer_path, path)
        if history_item and not target:
            return await asyncio.to_thread(bridge._history_item_meta_payload, history_item, full)
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
            await ws.send_text(json.dumps({"type": "options", **bridge.get_options()}))
            if bridge._cached_params:
                await ws.send_text(json.dumps(bridge._cached_params))
            await ws.send_text(json.dumps(bridge._build_queue_state()))
            # api_status 는 per-ws 평가 (setup_allowed 가 클라이언트 IP에 따라 다름)
            await ws.send_text(json.dumps(bridge.get_api_status(ws=ws)))
            await bridge.send_desktop_control_snapshot_to_ws(ws, "initial")
            # 캐시된 Anlas 있으면 바로 송신 (viewer pill 초기화)
            if bridge._anlas_cache:
                await ws.send_text(json.dumps(bridge._anlas_payload()))
            # init_complete: 클라이언트에 캐시 도착 완료 신호 (복원 가드 해제용)
            # 단 사용자 사용 가능 시점은 lazy_indices_ready 도 도착해야 함.
            await ws.send_text(json.dumps({"type": "init_complete"}))
            # 이미 lazy 인덱스 워밍업이 끝난 상태(재연결/늦은 접속) 면 즉시 알린다.
            if bridge._lazy_indices_ready:
                await ws.send_text(json.dumps({"type": "lazy_indices_ready"}))
            # 메인 스레드에서 캐시 갱신 + broadcast (초기화 타이밍 이슈 방지)
            bridge.request_refresh_cache.emit()
            # Send module badge states (automation countdown, character count)
            bridge.request_get_module.emit(None, "automation")
            bridge.request_get_module.emit(None, "character")
            bridge.request_get_module.emit(None, "character_reference")
            bridge.request_get_module.emit(None, "vibe_transfer")

            # 보류된 초기 메시지를 메인 루프에 재주입
            # (get_search_state 등 초기화 단계에서 소비된 메시지)
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
                    bridge._pending_random_requests.append({"ws": ws, "source_row": None, "active_ratings": set(bridge._active_ratings)})
                    bridge.request_random.emit()
                elif data == "sync":
                    await ws.send_text(json.dumps({
                        "type": "mode",
                        "mode": bridge.app_context.get_api_mode(),
                    }))
                    await ws.send_text(json.dumps({"type": "options", **bridge.get_options()}))
                    if bridge._cached_params:
                        await ws.send_text(json.dumps(bridge._cached_params))
                    await ws.send_text(json.dumps(bridge._build_queue_state()))
                    await ws.send_text(json.dumps(bridge.get_api_status(ws=ws)))
                    await bridge.send_desktop_control_snapshot_to_ws(ws, "manual_sync")
                    if bridge._anlas_cache:
                        await ws.send_text(json.dumps(bridge._anlas_payload()))
                elif data.startswith("{"):
                    try:
                        cmd = json.loads(data)
                        cmd_type = cmd.get("type")
                        if cmd_type == "random":
                            ratings = cmd.get("ratings", [])
                            valid = set(r for r in ratings if r in 'gsqe')
                            active = valid if valid else set(bridge._active_ratings)
                            overrides = cmd.get("overrides") if isinstance(cmd.get("overrides"), dict) else None
                            random_request_id = str(cmd.get("random_request_id") or cmd.get("requestId") or "")
                            bridge._pending_random_requests.append({
                                "ws": ws,
                                "source_row": None,
                                "active_ratings": active,
                                "overrides": overrides,
                                "remote_random_request_id": random_request_id,
                            })
                            bridge.request_random.emit()
                        elif cmd_type == "set_option":
                            opt_key = cmd.get("key", "")
                            option_value = bridge._coerce_bool(cmd.get("value"))
                            bridge.request_set_option.emit(opt_key, option_value)
                        elif cmd_type == "set_prompt":
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
                            bridge.request_set_module.emit(mid, mkey, mval)
                        elif cmd_type == "read_hires_preset_overlay":
                            preset_name = str(cmd.get("preset_name", "") or "")
                            response = await asyncio.to_thread(bridge._hires_overlay_response, preset_name)
                            await ws.send_text(json.dumps(response))
                        elif cmd_type == "write_hires_preset_overlay":
                            preset_name = str(cmd.get("preset_name", "") or "")
                            action = str(cmd.get("action", "save") or "save")
                            if action == "reset":
                                ok, msg = await asyncio.to_thread(bridge._reset_hires_overlay, preset_name)
                            else:
                                ok, msg = await asyncio.to_thread(
                                    bridge._write_hires_overlay,
                                    preset_name,
                                    cmd.get("body") if isinstance(cmd.get("body"), dict) else {},
                                )
                            await ws.send_text(json.dumps({
                                "type": "toast",
                                "message": msg,
                                "level": "success" if ok else "error",
                            }))
                            if ok:
                                response = await asyncio.to_thread(bridge._hires_overlay_response, preset_name)
                                await ws.send_text(json.dumps(response))
                        elif cmd_type in ("get_search_state", "search", "load_parquet", "merge_parquet",
                                           "search_parquet_action", "depth_action", "get_depth_state", "restore_snapshot"):
                            if cmd_type == "get_search_state":
                                bridge.request_get_module.emit(None, "__search__")
                            elif cmd_type == "search":
                                bridge.request_search.emit(json.dumps(cmd))
                            elif cmd_type == "load_parquet":
                                bridge.request_load_parquet.emit(cmd.get("filename", ""))
                            elif cmd_type == "merge_parquet":
                                bridge.request_merge_parquet.emit(cmd.get("filename", ""))
                            elif cmd_type == "search_parquet_action":
                                bridge.request_search_parquet_action.emit(json.dumps(cmd))
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
                            bridge._active_ratings = new_ratings
                            bridge.app_context.remote_active_ratings = new_ratings
                            bridge._save_search_filter_state(ratings=bridge._normalize_rating_list(new_ratings))
                            bridge.request_apply_filters.emit()
                            # 즉시 카운트 계산하여 응답
                            info = await asyncio.to_thread(bridge._compute_master_count, new_ratings)
                            rc = info["rating_counts"]
                            count = info["count"]
                            await ws.send_text(json.dumps({
                                "type": "rating_update",
                                "active_ratings": bridge._normalize_rating_list(new_ratings),
                                "count": count,
                                "rating_counts": rc,
                            }))
                        elif cmd_type == "save_search_filter_state":
                            await asyncio.to_thread(bridge._save_search_filter_state_from_payload, cmd)
                        elif cmd_type == "tag_filter_search":
                            tags = cmd.get("tags", [])
                            request_id = str(cmd.get("request_id") or "")
                            if tags:
                                result = await asyncio.to_thread(bridge._do_tag_filter_search, tags)
                                if request_id:
                                    result["request_id"] = request_id
                                # pending에 저장 (Assign 전까지 Random에 미반영)
                                session = ws_manager.sessions.get(ws)
                                if session:
                                    ids = result.pop("_ids", set())
                                    session["tag_filter_pending"] = {
                                        "tags": tags,
                                        "ids": ids,
                                        "count": result["count"],
                                        "request_id": request_id,
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
                            pending = session.get("tag_filter_pending") if session else None
                            request_id = str(cmd.get("request_id") or "")
                            if pending and request_id and str(pending.get("request_id") or "") != request_id:
                                await ws.send_text(json.dumps({
                                    "type": "toast",
                                    "message": "Tag filter search is stale. Search again.",
                                    "level": "error",
                                }))
                            elif session and pending:
                                session["tag_filter"] = session.pop("tag_filter_pending")
                                tf = session["tag_filter"]
                                bridge._active_tag_filter_ids = tf.get("ids")
                                bridge._save_search_filter_state(
                                    tag_filter=[
                                        str(tag).lstrip("-")
                                        for tag in tf.get("tags", [])
                                        if not str(tag).startswith("-")
                                    ],
                                    tag_filter_exclude=[
                                        str(tag).lstrip("-")
                                        for tag in tf.get("tags", [])
                                        if str(tag).startswith("-")
                                    ],
                                    tag_filter_active=True,
                                )
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
                            bridge._active_tag_filter_ids = None
                            bridge._save_search_filter_state(
                                tag_filter=[],
                                tag_filter_exclude=[],
                                tag_filter_active=False,
                            )
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
                        elif cmd_type == "autocomplete_translate":
                            query = cmd.get("query", "")
                            request_id = str(cmd.get("requestId") or cmd.get("request_id") or "")
                            results, translated = await asyncio.to_thread(
                                bridge._search_kr_tags_with_translation,
                                query,
                                12,
                            )
                            payload = {
                                "type": "autocomplete_result",
                                "query": query,
                                "results": results,
                                "translated_query": translated,
                            }
                            if request_id:
                                payload["requestId"] = request_id
                            await ws.send_text(json.dumps(payload))
                        elif cmd_type == "autocomplete_wildcard":
                            query = cmd.get("query", "")
                            results = await asyncio.to_thread(bridge._search_wildcards, query, 12)
                            await ws.send_text(json.dumps({
                                "type": "autocomplete_result",
                                "query": query,
                                "results": results,
                            }))
                        elif cmd_type == "autocomplete_chunk":
                            query = cmd.get("query", "")
                            results = await asyncio.to_thread(bridge._search_chunks, query, 12)
                            await ws.send_text(json.dumps({
                                "type": "autocomplete_result",
                                "query": query,
                                "results": results,
                            }))
                        elif cmd_type == "autocomplete_vibe_cluster":
                            query = cmd.get("query", "")
                            results = await asyncio.to_thread(bridge._search_vibe_clusters, query, 12)
                            await ws.send_text(json.dumps({
                                "type": "autocomplete_result",
                                "query": query,
                                "results": results,
                            }))
                        elif cmd_type == "autocomplete_preset":
                            query = cmd.get("query", "")
                            payload = await asyncio.to_thread(
                                bridge._preset_autocomplete_payload,
                                query,
                                12,
                                cmd.get("presetContext") if isinstance(cmd, dict) else None,
                            )
                            await ws.send_text(json.dumps({
                                "type": "autocomplete_result",
                                "query": payload.get("query", query),
                                "results": payload.get("results", []),
                                "secondaryResults": payload.get("secondaryResults", []),
                                "preset": payload.get("preset") or {},
                            }))
                        elif cmd_type == "tag_lookup":
                            # 태그 상세 정보 조회
                            tag = cmd.get("tag", "")
                            info = await asyncio.to_thread(bridge._lookup_tag_info, tag)
                            await ws.send_text(json.dumps({
                                "type": "tag_lookup_result", **info,
                            }))
                        elif cmd_type == "generate":
                            raw_overrides = cmd.get("overrides")
                            bridge._pending_generate_requests.append({
                                "ws": ws,
                                "prompt": cmd.get("prompt", ""),
                                "negative": cmd.get("negative_prompt", ""),
                                "overrides": raw_overrides if isinstance(raw_overrides, dict) else None,
                            })
                            bridge.request_generate.emit()
                        elif cmd_type == "result_enhance":
                            bridge.request_result_enhance.emit(ws, json.dumps(cmd))
                        elif cmd_type == "set_result_enhance_config":
                            bridge.request_set_result_enhance_config.emit(ws, json.dumps(cmd))
                        elif cmd_type == "result_upscale":
                            bridge.request_result_upscale.emit(ws, json.dumps(cmd))
                        elif cmd_type == "result_image_action":
                            allowed, reason = bridge._desktop_img2img_gate(bridge._ws_client_host(ws))
                            if not allowed:
                                await ws.send_text(json.dumps({
                                    "type": "toast",
                                    "message": reason,
                                    "level": "error",
                                }))
                                continue
                            allowed, reason = bridge._nai_img2img_mode_gate()
                            if not allowed:
                                await ws.send_text(json.dumps({
                                    "type": "toast",
                                    "message": reason,
                                    "level": "error",
                                }))
                                continue
                            bridge.request_result_image_action.emit(json.dumps(cmd))
                        elif cmd_type == "probe_api":
                            # 저장된 토큰/URL 로 실시간 연결 가능 여부 확인.
                            # keyring 값 사용 — 웹으로 토큰이 노출되지 않음. 저장/타임스탬프 갱신 없음.
                            # 3개 backend 병렬 ping (최악 NAI 10s).
                            # Setup 게이트(loopback + !cloudflared) 적용 — LAN/터널 기기가
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
                                failed_keys = []
                                if mode == "NAI":
                                    if not stm.delete_token("nai_token"):
                                        failed_keys.append("nai_token")
                                    else:
                                        bridge._anlas_cache = None
                                        bridge._broadcast_json(bridge._anlas_payload())
                                elif mode == "WEBUI":
                                    if not stm.delete_token("webui_url"):
                                        failed_keys.append("webui_url")
                                elif mode == "COMFYUI":
                                    for key in ("comfyui_url", "comfyui_default_model", "comfyui_sampling_mode"):
                                        if not stm.delete_token(key):
                                            failed_keys.append(key)
                                else:
                                    await ws.send_text(json.dumps({
                                        "type": "clear_api_result",
                                        "mode": mode,
                                        "success": False,
                                        "message": "알 수 없는 API 모드입니다.",
                                        "message_type": "error",
                                    }))
                                    continue

                                if failed_keys:
                                    message = (
                                        "연결 해제 실패: 저장된 설정을 삭제하지 못했습니다 "
                                        f"({', '.join(failed_keys)})."
                                    )
                                    await ws.send_text(json.dumps({
                                        "type": "clear_api_result",
                                        "mode": mode,
                                        "success": False,
                                        "message": message,
                                        "message_type": "error",
                                    }))
                                    await ws.send_text(json.dumps({
                                        "type": "toast",
                                        "message": message,
                                        "level": "error",
                                    }))
                                    bridge._broadcast_api_status()
                                    continue

                                await ws.send_text(json.dumps({
                                    "type": "clear_api_result",
                                    "mode": mode,
                                    "success": True,
                                    "message": "연결 해제됨",
                                    "message_type": "info",
                                }))
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


def _remote_bind_probe_hosts(host: str) -> list[str]:
    clean_host = (host or "0.0.0.0").strip()
    if clean_host in {"0.0.0.0", "::", "*"}:
        return [clean_host, "127.0.0.1"]
    return [clean_host]


def _can_bind_remote_port(host: str, port: int) -> bool:
    for probe_host in _remote_bind_probe_hosts(host):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                sock.bind((probe_host, port))
                sock.listen(1)
        except OSError:
            return False
    return True


def _select_remote_server_port(host: str, preferred_port: int, *, max_attempts: int = 25) -> int:
    try:
        start_port = int(preferred_port)
    except (TypeError, ValueError):
        start_port = 7243
    start_port = min(65535, max(1024, start_port))

    for offset in range(max_attempts):
        candidate = start_port + offset
        if candidate > 65535:
            break
        if _can_bind_remote_port(host, candidate):
            return candidate

    raise OSError(f"No available Remote API port near {start_port}")


def start_remote_server(app_context, host: str = "0.0.0.0", port: int = 7243):
    """Remote API 서버를 daemon thread로 시작."""
    global _server_instance, _bridge_instance, _checkbox_connections, _param_signal_sources, _bridge_signal_connections

    if _server_instance is not None:
        print("🌐 Remote: 서버가 이미 실행 중")
        return _server_instance

    requested_port = port
    port = _select_remote_server_port(host, port)
    try:
        requested_port_int = int(requested_port)
    except (TypeError, ValueError):
        requested_port_int = None
    if port != requested_port_int:
        print(f"🌐 Remote: port {requested_port} unavailable on {host}; using {port}")

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
    bridge.request_resolution_action.connect(bridge._do_resolution_action, Qt.ConnectionType.QueuedConnection)
    bridge.request_get_module.connect(bridge._do_get_module, Qt.ConnectionType.QueuedConnection)
    bridge.request_set_module.connect(bridge._do_set_module, Qt.ConnectionType.QueuedConnection)
    bridge.request_artist_thumb_random_peng.connect(
        bridge._do_build_artist_thumb_random_peng_override,
        Qt.ConnectionType.QueuedConnection,
    )
    bridge.request_search.connect(bridge._do_search, Qt.ConnectionType.QueuedConnection)
    bridge.request_load_parquet.connect(bridge._do_load_parquet, Qt.ConnectionType.QueuedConnection)
    bridge.request_merge_parquet.connect(bridge._do_merge_parquet, Qt.ConnectionType.QueuedConnection)
    bridge.request_uploaded_parquet.connect(bridge._do_uploaded_parquet, Qt.ConnectionType.QueuedConnection)
    bridge.request_search_parquet_action.connect(bridge._do_search_parquet_action, Qt.ConnectionType.QueuedConnection)
    bridge.request_depth_action.connect(bridge._do_depth_action, Qt.ConnectionType.QueuedConnection)
    bridge.request_restore_snapshot.connect(bridge._do_restore_snapshot, Qt.ConnectionType.QueuedConnection)
    bridge.request_apply_filters.connect(bridge._do_apply_filters, Qt.ConnectionType.QueuedConnection)
    bridge.request_refresh_cache.connect(bridge._do_refresh_cache, Qt.ConnectionType.QueuedConnection)
    bridge.request_set_desktop_visibility.connect(bridge._do_set_desktop_visibility, Qt.ConnectionType.QueuedConnection)
    bridge.request_send_desktop_sync.connect(bridge._do_send_desktop_control_snapshot, Qt.ConnectionType.QueuedConnection)
    bridge.request_result_enhance.connect(bridge._do_result_enhance, Qt.ConnectionType.QueuedConnection)
    bridge.request_set_result_enhance_config.connect(bridge._do_set_result_enhance_config, Qt.ConnectionType.QueuedConnection)
    bridge.request_result_reroll.connect(bridge._do_result_reroll, Qt.ConnectionType.QueuedConnection)
    bridge.request_result_queue.connect(bridge._do_result_queue, Qt.ConnectionType.QueuedConnection)
    bridge.request_result_history_action.connect(bridge._do_result_history_action, Qt.ConnectionType.QueuedConnection)
    bridge.request_result_upscale.connect(bridge._do_result_upscale, Qt.ConnectionType.QueuedConnection)
    bridge.request_result_image_action.connect(bridge._do_result_image_action, Qt.ConnectionType.QueuedConnection)
    bridge.request_image_action.connect(bridge._do_image_action, Qt.ConnectionType.QueuedConnection)
    bridge.request_copy_png_to_clipboard.connect(bridge._do_copy_png_to_clipboard, Qt.ConnectionType.QueuedConnection)
    bridge.request_read_clipboard_png.connect(bridge._do_read_clipboard_png, Qt.ConnectionType.QueuedConnection)
    bridge.request_danbooru_prompt_preview.connect(bridge._do_danbooru_prompt_preview, Qt.ConnectionType.QueuedConnection)
    bridge.request_open_danbooru_browser.connect(bridge._do_open_danbooru_browser, Qt.ConnectionType.QueuedConnection)
    bridge._danbooru_prompt_preview_bridge_connected = True
    bridge.request_artist_thumb_generate.connect(bridge._do_artist_thumb_generate, Qt.ConnectionType.QueuedConnection)
    bridge.request_character_viewer_generate.connect(bridge._do_character_viewer_generate, Qt.ConnectionType.QueuedConnection)
    bridge.request_queue_action.connect(bridge._do_queue_action, Qt.ConnectionType.QueuedConnection)
    bridge.request_set_cloudflared_enabled.connect(bridge._do_set_cloudflared_enabled, Qt.ConnectionType.QueuedConnection)
    bridge.request_comfyui_workflow_action.connect(bridge._do_comfyui_workflow_action, Qt.ConnectionType.QueuedConnection)
    bridge.request_prompt_preset_thumbnail_generate.connect(
        bridge._do_request_prompt_engineering_thumbnail_generation,
        Qt.ConnectionType.QueuedConnection,
    )
    QTimer.singleShot(0, bridge._restore_saved_search_filter_state)

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
    app_context.subscribe("generation_error", bridge.on_generation_error)
    app_context.subscribe("result_enhance_completed", bridge.on_result_enhance_completed)
    app_context.subscribe("result_enhance_config_changed", bridge.on_result_enhance_config_changed)
    app_context.subscribe("prompt_generated", bridge.on_prompt_generated)
    app_context.subscribe("api_mode_changed", bridge.on_api_mode_changed)
    app_context.subscribe("prompt_preset_loaded", bridge.on_prompt_preset_loaded)
    app_context.subscribe("image_saved", bridge._on_image_saved)
    app_context.subscribe("history_item_added", bridge.on_history_item_added)
    app_context.subscribe("history_item_removed", bridge.on_history_item_removed)
    app_context.subscribe("history_cleared", bridge.on_history_cleared)
    app_context.subscribe("desktop_window_visibility_changed", bridge.on_desktop_window_visibility_changed)
    app_context.subscribe("cloudflared_status_changed", bridge.on_cloudflared_status_changed)
    app_context.subscribe("save_directory_changed", bridge.on_save_directory_changed)
    app_context.subscribe("comfyui_workflow_changed", bridge.on_comfyui_workflow_changed)
    app_context.subscribe("event_stream_started", bridge._broadcast_event_stream_state)
    app_context.subscribe("event_stream_stopped", bridge._broadcast_event_stream_state)

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
    app_context.subscribe("generation_result_available", bridge._broadcast_queue_state)
    for queue_event in [
        "queue_request_enqueued", "queue_request_dequeued",
        "queue_queue_paused", "queue_queue_resumed",
        "queue_queue_cleared", "queue_request_removed",
        "queue_request_started", "queue_request_completed",
        "queue_request_failed", "queue_state_changed",
    ]:
        app_context.subscribe(queue_event, bridge._broadcast_queue_state)

    # Generation option checkboxes participate in the shared Remote Web state.
    _checkbox_connections = []
    _bridge_signal_connections = []
    for key, label in RemoteBridge.OPTION_KEYS.items():
        cb = mw.generation_checkboxes.get(label)
        if cb:
            cb.toggled.connect(bridge._on_option_toggled_slot)
            _checkbox_connections.append((cb, "toggled"))

    # Auto-save is part of the same shared option snapshot and has extra settings.
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

    # Parameter hooks keep the schema refresh path without pushing selected values.
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
    if hasattr(mw, 'anima_weight_edit'):
        _param_signal_sources.append((mw.anima_weight_edit, "textChanged"))

    for widget, signal_name in _param_signal_sources:
        try:
            getattr(widget, signal_name).connect(bridge._on_param_changed_slot)
        except Exception:
            pass

    # 캐시 초기화 (FastAPI 스레드에서 Qt 위젯 직접 접근 방지)
    bridge._update_cache_all()

    # KR_tags 인덱스 + character_analysis 는 부팅 main thread 가 끝난 직후
    # daemon thread 에서 워밍업한다. metadata fallback 은 prebuilt artifact 만 읽고,
    # artifact 가 없으면 라이브 프로세스에서 무거운 빌드를 시도하지 않는다.
    # 완료 시 모든 WS 클라이언트에 broadcast 하여 boot indicator 와 동기화.
    def _bg_warmup_lazy_indices():
        try:
            bridge._load_kr_tags()
            if bridge._tag_search_index is not None:
                bridge._tag_search_index.warm_metadata_fallback_index(allow_build=False)
        except Exception as e:
            print(f"🌐 Remote: KR_tags warmup 실패 — {e}")
        try:
            bridge._load_char_analysis()
        except Exception as e:
            print(f"🌐 Remote: character_analysis warmup 실패 — {e}")
        bridge._lazy_indices_ready = True
        # event loop 가 준비될 때까지 잠깐 대기 (NAIA-RemoteAPI thread 가 set_event_loop 호출)
        import time as _time
        for _ in range(50):
            if bridge._loop is not None:
                break
            _time.sleep(0.1)
        if bridge._loop is not None and bridge._ws_manager is not None:
            try:
                asyncio.run_coroutine_threadsafe(
                    bridge._ws_manager.broadcast_json({"type": "lazy_indices_ready"}),
                    bridge._loop,
                )
            except Exception as e:
                print(f"🌐 Remote: lazy_indices_ready broadcast 실패 — {e}")
    threading.Thread(target=_bg_warmup_lazy_indices, daemon=True, name="LazyIndices-Warmup").start()

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
            for event_name in ["generation_result_available", "generation_error", "result_enhance_completed", "result_enhance_config_changed", "prompt_generated", "api_mode_changed", "prompt_preset_loaded", "generation_started", "image_saved", "desktop_window_visibility_changed", "cloudflared_status_changed", "save_directory_changed", "comfyui_workflow_changed"]:
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
