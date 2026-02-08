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
                return result.text.lower()
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
                    return translated_text.lower()
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
                    return translated_text
    except Exception:
        pass

    return None