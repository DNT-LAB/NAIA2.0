"""
Korean to English translator for NAIA 2.0
"""

from typing import Optional
import warnings

try:
    from googletrans import Translator as GoogleTranslator
    GOOGLETRANS_AVAILABLE = True
except ImportError:
    GOOGLETRANS_AVAILABLE = False

import requests

# googletrans의 비동기 관련 경고 억제
warnings.filterwarnings("ignore", message="coroutine 'Translator.translate' was never awaited")


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
                    _record_translation(text, translated, "ko->en")
                    return translated
    except Exception:
        pass

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
                    _record_translation(text, translated_text, "en->ko")
                    return translated_text
    except Exception:
        pass

    return None