"""
Korean to English translator for NAIA 2.0
"""

from typing import Optional
import threading
import time
import warnings

try:
    from googletrans import Translator as GoogleTranslator
    GOOGLETRANS_AVAILABLE = True
except ImportError:
    GOOGLETRANS_AVAILABLE = False

import requests

# googletrans의 비동기 관련 경고 억제
warnings.filterwarnings("ignore", message="coroutine 'Translator.translate' was never awaited")

# ── 레이트 리밋 백오프 (사용자 제보 2026-08-29 "가끔 번역 실패") ────────────────
#
# 무료 엔드포인트(`translate_a/single?client=gtx`)는 **IP 단위로 막는다.** 실측:
# 20/20 HTTP 429, 60초·120초 뒤에도 429. 구글의 차단은 분이 아니라 시간 단위다.
#
# ⚠️ **막힌 동안 계속 두드리면 차단이 길어진다.** 그런데 이 모듈을 쓰는 곳이 팝업
#    하나가 아니다 - 자동완성(`_translate_autocomplete_query`)·Ollama 태그 어시스트가
#    같은 IP 를 함께 태운다(Codex 리뷰 2026-08-29 MED 3). 그래서 백오프는 **여기,
#    모든 소비자가 지나는 자리**에 둔다. 화면 한 곳에 두면 나머지가 그대로 샌다.
#
# ⚠️ 스레드 안전해야 한다 - 백엔드는 `run_in_thread` 로 부르므로 여러 스레드가 동시에
#    들어온다.
_BACKOFF_LOCK = threading.Lock()
_BACKOFF_BASE_SECONDS = 60.0
_BACKOFF_MAX_SECONDS = 900.0
_backoff_until = 0.0
_backoff_step = 0.0

# 실패 사유. ⚠️ **예외로 알리지 않는다.** 이 모듈의 계약은 "실패하면 None, 절대 raise
# 안 함" 이고 자동완성 경로는 예외를 안 잡는다 - 던지게 바꾸면 WS 수신 루프가 통째로
# 끝난다(Codex 리뷰 MED 2). 그래서 마지막 사유를 **따로 돌려주는 함수**를 둔다.
FAILURE_RATE_LIMITED = "rate_limited"
FAILURE_TIMEOUT = "timeout"
FAILURE_NETWORK = "network"
FAILURE_EMPTY = "empty"


def _backoff_remaining() -> float:
    with _BACKOFF_LOCK:
        return max(0.0, _backoff_until - time.monotonic())


def _note_rate_limited() -> None:
    """429 를 봤다. 다음 시도까지 물러선다(성공 전까지 두 배씩)."""
    global _backoff_until, _backoff_step
    with _BACKOFF_LOCK:
        _backoff_step = min(_BACKOFF_MAX_SECONDS,
                            _BACKOFF_BASE_SECONDS if _backoff_step <= 0 else _backoff_step * 2)
        _backoff_until = time.monotonic() + _backoff_step


def _note_success() -> None:
    global _backoff_until, _backoff_step
    with _BACKOFF_LOCK:
        _backoff_until = 0.0
        _backoff_step = 0.0


def translate_with_reason(text: str, direction: str = "ko_en") -> tuple[Optional[str], str]:
    """번역 결과와 **실패 사유**를 함께 돌려준다.

    기존 `korean_to_english` / `english_to_korean` 은 사유 없이 `None` 만 준다. 화면이
    "Translation failed" 밖에 못 말하는 이유가 그것이라, 사유가 필요한 호출자만 이쪽을
    쓴다. 계약은 같다 - **raise 하지 않는다.**
    """
    fn = english_to_korean if direction in {"en_ko", "en-ko", "en2ko"} else korean_to_english
    remaining = _backoff_remaining()
    if remaining > 0:
        return None, FAILURE_RATE_LIMITED
    result = fn(text)
    if result:
        return result, ""
    return None, _last_reason()


_REASON_LOCK = threading.Lock()
_last_failure_reason = ""


def _set_reason(reason: str) -> None:
    global _last_failure_reason
    with _REASON_LOCK:
        _last_failure_reason = reason


def _last_reason() -> str:
    with _REASON_LOCK:
        return _last_failure_reason or FAILURE_EMPTY


def rate_limit_seconds_remaining() -> int:
    """지금 백오프가 걸려 있으면 남은 초. 화면이 "잠시 후" 를 구체적으로 말할 수 있게."""
    return int(_backoff_remaining() + 0.5)


def _record_translation(source: str, translated: Optional[str], direction: str) -> None:
    """번역 1건을 기록한다(best-effort). 기록 실패가 번역을 깨뜨리지 않도록 완전히 격리.

    임포트 자체도 try 안에서 지연 로드해 translator 모듈을 leaf 의존으로 유지한다
    (순환 임포트/필수 의존 회피). 호출 지점 라벨은 ``context`` 인자를 비워 두어
    ``translation_context(...)``로 설정된 현재 컨텍스트를 사용하게 하고, 아무 것도
    설정되지 않았을 때만 범용 ``"translator"``로 폴백한다(이중 기록 없이 라벨링).
    """
    try:
        if not translated:
            return
        from core.translation_history import current_context, log_translation

        # 호출자가 translation_context(...)로 라벨을 설정했으면 그것을, 아니면
        # 범용 "translator"를 컨텍스트로 사용한다.
        label = current_context("translator")
        log_translation(source, translated, direction=direction, context=label)
    except Exception:
        pass


def korean_to_english(text: str) -> Optional[str]:
    """
    한글을 영어로 번역

    Args:
        text: 한글 텍스트

    Returns:
        영어로 번역된 텍스트 또는 None
    """
    if not text or not text.strip():
        return text

    # 1. googletrans 시도
    if GOOGLETRANS_AVAILABLE:
        try:
            translator = GoogleTranslator()
            result = translator.translate(text, src='ko', dest='en')
            if result and hasattr(result, 'text'):
                translated = result.text.lower()
                _record_translation(text, translated, "ko->en")
                return translated
        except (RuntimeWarning, Exception):
            # googletrans 내부의 비동기 관련 경고 무시
            pass

    # 2. requests로 Google Translate API 호출
    #    ⚠️ **막혀 있으면 아예 안 나간다.** 429 중에 계속 두드리면 차단이 길어진다.
    if _backoff_remaining() > 0:
        _set_reason(FAILURE_RATE_LIMITED)
        return None
    try:
        base_url = "https://translate.googleapis.com/translate_a/single"

        params = {
            'client': 'gtx',
            'sl': 'ko',
            'tl': 'en',
            'dt': 't',
            'q': text
        }

        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }

        response = requests.get(base_url, params=params, headers=headers, timeout=5)

        if response.status_code == 429:
            _note_rate_limited()
            _set_reason(FAILURE_RATE_LIMITED)
            return None
        if response.status_code == 200:
            # 명시적으로 동기 방식으로 JSON 파싱
            try:
                result = response.json()
            except Exception:
                result = None

            if result and len(result) > 0 and len(result[0]) > 0:
                translated_parts = []
                for part in result[0]:
                    if part[0]:
                        translated_parts.append(part[0])

                translated_text = ''.join(translated_parts)
                if translated_text:
                    translated = translated_text.lower()
                    _note_success()
                    _set_reason("")
                    _record_translation(text, translated, "ko->en")
                    return translated
    except requests.Timeout:
        _set_reason(FAILURE_TIMEOUT)
        return None
    except Exception:
        _set_reason(FAILURE_NETWORK)
        return None

    _set_reason(FAILURE_EMPTY)
    return None


def english_to_korean(text: str) -> Optional[str]:
    """
    영어를 한글로 번역

    Args:
        text: 영어 텍스트

    Returns:
        한글로 번역된 텍스트 또는 None
    """
    if not text or not text.strip():
        return text

    # 1. googletrans 시도
    if GOOGLETRANS_AVAILABLE:
        try:
            translator = GoogleTranslator()
            result = translator.translate(text, src='en', dest='ko')
            if result and hasattr(result, 'text'):
                _record_translation(text, result.text, "en->ko")
                return result.text
        except (RuntimeWarning, Exception):
            # googletrans 내부의 비동기 관련 경고 무시
            pass

    # 2. requests로 Google Translate API 호출
    #    ⚠️ **막혀 있으면 아예 안 나간다.** 429 중에 계속 두드리면 차단이 길어진다.
    if _backoff_remaining() > 0:
        _set_reason(FAILURE_RATE_LIMITED)
        return None
    try:
        base_url = "https://translate.googleapis.com/translate_a/single"

        params = {
            'client': 'gtx',
            'sl': 'en',
            'tl': 'ko',
            'dt': 't',
            'q': text
        }

        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }

        response = requests.get(base_url, params=params, headers=headers, timeout=5)

        if response.status_code == 429:
            _note_rate_limited()
            _set_reason(FAILURE_RATE_LIMITED)
            return None
        if response.status_code == 200:
            # 명시적으로 동기 방식으로 JSON 파싱
            try:
                result = response.json()
            except Exception:
                result = None

            if result and len(result) > 0 and len(result[0]) > 0:
                translated_parts = []
                for part in result[0]:
                    if part[0]:
                        translated_parts.append(part[0])

                translated_text = ''.join(translated_parts)
                if translated_text:
                    _note_success()
                    _set_reason("")
                    _record_translation(text, translated_text, "en->ko")
                    return translated_text
    except requests.Timeout:
        _set_reason(FAILURE_TIMEOUT)
        return None
    except Exception:
        _set_reason(FAILURE_NETWORK)
        return None

    _set_reason(FAILURE_EMPTY)
    return None