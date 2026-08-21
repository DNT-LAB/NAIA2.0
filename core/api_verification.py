"""
API 검증 순수 함수 레이어 — Qt/UI 의존성 없음.

- 데스크톱: `core/api_validator.py` 의 QObject 워커가 이 함수들을 호출
- 웹: `core/web_session_app.py` 의 Setup/API route가 이 함수들을 직접 호출

테스트 토큰 `api_test_BCF13af9#d` 는 NAI 한정 검증 우회 (기존 동작 유지).
"""
from dataclasses import dataclass, field
from typing import Optional
import requests


@dataclass
class VerifyResult:
    """API 검증 결과. UI 의존성 없음.

    `extra` 키 스키마 (함수별):
      verify_nai_token:
        - 'tier'            : 'opus' | 'paid' | 'insufficient'
        - 'anlas'           : int (paid/insufficient 티어)
        - 'http_status'     : int  (HTTPError 시)
        - 'test_mode'       : True (테스트 토큰 바이패스)
      verify_webui_url / verify_comfyui_url:
        - 'protocol'        : 'http' | 'https'  (검증 성공한 쪽)
        - 'gpu_name'        : str   (ComfyUI만)
        - 'ram_gb'          : float (ComfyUI만)
      fetch_comfyui_models:
        - 'models'          : list[str]
    """
    success: bool
    message: str
    message_type: str  # 'info' | 'warning' | 'error'
    value: str = ""             # 성공 시 저장할 정규화 값 (token 또는 clean URL)
    extra: dict = field(default_factory=dict)


NAI_TEST_TOKEN = "api_test_BCF13af9#d"
# NAI 서버 이전 공지(2026-07): /user/information, /user/data, /user/subscription 은
# https://image.novelai.net 에서 호출해야 하며 기존 api.novelai.net 경로는 이미 죽었다.
# (생성/업스케일 등 다른 엔드포인트는 이전 대상 아님.)
NAI_SUBSCRIPTION_URL = "https://image.novelai.net/user/subscription"


def verify_nai_token(token: str) -> VerifyResult:
    """NAI 영구 토큰 검증.

    구독 등급별 판정:
    - Opus 등급 → success/info
    - Opus 아님 + Anlas > 20 → success/warning (유료 소진 예정 안내)
    - Opus 아님 + Anlas <= 20 → 실패/warning
    - 401 → 실패/error
    """
    token = (token or "").strip()
    if not token:
        return VerifyResult(False, "토큰을 입력해주세요.", "error")

    # 테스트 토큰: 실제 HTTP 호출 없이 통과 (기존 동작)
    if token == NAI_TEST_TOKEN:
        return VerifyResult(True, "테스트 토큰 (검증 생략)", "info", value=token,
                            extra={"test_mode": True})

    try:
        response = requests.get(
            NAI_SUBSCRIPTION_URL,
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()
        perks = data.get("perks") or {}

        if perks.get("unlimitedMaxPriority", False):
            return VerifyResult(True, "Opus 등급 구독 확인", "info", value=token,
                                extra={"tier": "opus"})

        training = data.get("trainingStepsLeft") or {}
        fixed = training.get("fixedTrainingStepsLeft", 0)
        purchased = training.get("purchasedTrainingSteps", 0)
        total = fixed + purchased

        if total > 20:
            return VerifyResult(
                True,
                f"Opus 구독 아님 — 유료 Anlas 소진 모드 (보유: {total})",
                "warning",
                value=token,
                extra={"tier": "paid", "anlas": total},
            )
        return VerifyResult(
            False,
            f"유효 토큰이지만 Opus 구독 아님 + Anlas 부족 ({total})",
            "warning",
            extra={"tier": "insufficient", "anlas": total},
        )
    except requests.exceptions.HTTPError as e:
        code = e.response.status_code if e.response is not None else 0
        if code == 401:
            return VerifyResult(False, "인증 실패 (HTTP 401): 유효하지 않은 토큰",
                                "error", extra={"http_status": 401})
        return VerifyResult(False, f"HTTP 오류: {code}", "error",
                            extra={"http_status": code})
    except requests.exceptions.RequestException as e:
        return VerifyResult(False, f"네트워크 오류: {e}", "error")
    except Exception as e:  # pragma: no cover
        return VerifyResult(False, f"알 수 없는 오류: {e}", "error")


def _split_protocol(url: str) -> tuple[str, list[str]]:
    """URL 에서 protocol 제거 + 시도할 protocol 조합 반환."""
    clean = (url or "").replace("http://", "").replace("https://", "").rstrip("/")
    return clean, [f"https://{clean}", f"http://{clean}"]


def verify_webui_url(url: str) -> VerifyResult:
    """AUTOMATIC1111 WebUI 연결 검증.

    `/sdapi/v1/progress?skip_current_image=true` 로 프로토콜 2개 순차 시도.
    """
    if not (url or "").strip():
        return VerifyResult(False, "WebUI 주소를 입력해주세요.", "error")

    clean, protocols = _split_protocol(url)
    for base in protocols:
        try:
            res = requests.get(f"{base}/sdapi/v1/progress?skip_current_image=true", timeout=3)
            if res.status_code == 200 and "progress" in res.json():
                return VerifyResult(
                    True, "WebUI 연결 성공", "info", value=clean,
                    extra={"protocol": base.split("://", 1)[0]},
                )
        except requests.exceptions.RequestException:
            continue

    return VerifyResult(False, f"WebUI 연결 실패: '{url}' 주소를 확인해주세요.", "error")


def verify_comfyui_url(url: str) -> VerifyResult:
    """ComfyUI 연결 검증.

    `/system_stats` 로 프로토콜 2개 순차 시도. 성공 시 GPU/RAM 정보 반환.
    """
    if not (url or "").strip():
        return VerifyResult(False, "ComfyUI 주소를 입력해주세요.", "error")

    clean, protocols = _split_protocol(url)
    for base in protocols:
        try:
            res = requests.get(f"{base}/system_stats", timeout=5)
            if res.status_code == 200:
                stats = res.json() or {}
                device = stats.get("system") or {}
                gpu_name = device.get("gpu_name", "Unknown GPU")
                ram_total = device.get("ram_total", 0) or 0
                ram_gb = ram_total / (1024 ** 3) if ram_total > 0 else 0.0
                return VerifyResult(
                    True,
                    f"ComfyUI 연결 성공 — {gpu_name} / {ram_gb:.1f}GB",
                    "info",
                    value=clean,
                    extra={
                        "protocol": base.split("://", 1)[0],
                        "gpu_name": gpu_name,
                        "ram_gb": round(ram_gb, 1),
                    },
                )
        except requests.exceptions.RequestException:
            continue

    return VerifyResult(
        False, f"ComfyUI 연결 실패: '{url}' 주소를 확인하고 서버가 실행 중인지 확인해주세요.",
        "error",
    )


def fetch_comfyui_models(url: str) -> VerifyResult:
    """ComfyUI `/object_info` 에서 CheckpointLoaderSimple + UNETLoader 모델 목록 수집.

    성공 시 extra['models'] 에 정렬된 리스트.
    """
    if not (url or "").strip():
        return VerifyResult(False, "URL이 비어 있습니다.", "error", extra={"models": []})

    clean, _ = _split_protocol(url)
    normalized = f"http://{clean}"  # ComfyUI 는 http 기본

    try:
        res = requests.get(f"{normalized}/object_info", timeout=10)
        if res.status_code != 200:
            return VerifyResult(False, f"API 응답 오류 (HTTP {res.status_code})",
                                "error", extra={"models": []})

        info = res.json() or {}
        all_models: set[str] = set()

        for node_name, key in (("CheckpointLoaderSimple", "ckpt_name"), ("UNETLoader", "unet_name")):
            node = info.get(node_name) or {}
            required = (node.get("input") or {}).get("required") or {}
            spec = required.get(key) or []
            if isinstance(spec, list) and spec:
                candidates = spec[0]
                if isinstance(candidates, list):
                    all_models.update(candidates)

        if not all_models:
            return VerifyResult(False, "사용 가능한 모델이 없습니다.", "warning",
                                extra={"models": []})

        models = sorted(all_models)
        return VerifyResult(True, f"모델 {len(models)}개 발견", "info",
                            value=clean, extra={"models": models})

    except requests.exceptions.Timeout:
        return VerifyResult(False, "모델 목록 로드 시간 초과", "error", extra={"models": []})
    except requests.exceptions.ConnectionError:
        return VerifyResult(False, "ComfyUI 서버 연결 실패", "error", extra={"models": []})
    except Exception as e:  # pragma: no cover
        return VerifyResult(False, f"모델 목록 로드 실패: {e}", "error", extra={"models": []})


def fetch_nai_anlas(token: str) -> Optional[int]:
    """NAI 구독의 Anlas 잔액 조회. Opus 여부와 무관 — 실제 잔액은 어느 등급이든 소모됨.

    `api_service.get_anlas()` 와 동일 규칙: `fixedTrainingStepsLeft + purchasedTrainingSteps`.
    실패 시 None.
    """
    token = (token or "").strip()
    if not token:
        return None
    try:
        res = requests.get(
            NAI_SUBSCRIPTION_URL,
            headers={"Authorization": f"Bearer {token}"},
            timeout=5,
        )
        if res.status_code != 200:
            return None
        data = res.json() or {}
        training = data.get("trainingStepsLeft") or {}
        fixed = int(training.get("fixedTrainingStepsLeft", 0) or 0)
        purchased = int(training.get("purchasedTrainingSteps", 0) or 0)
        return fixed + purchased
    except requests.exceptions.RequestException:
        return None
    except Exception:  # pragma: no cover
        return None


def fetch_nai_usage_limit(token: str) -> Optional[dict]:
    """NAI Diffusion V5 의 **Opus 사용량 한도** 조회.

    V5 는 Anlas 가 아니라 별도 사용량 풀을 쓴다(무료 범위: 캐릭터 레퍼런스 없이
    1MP 이하 · steps 28 이하). 잔량은 **생성 응답에 실리지 않고** 구독 응답의
    `usage` 로만 온다(2026-08-19 실측):

        usage = {"percent": 100, "isNegative": false, "timeUntilNextPercent": 7888}

    `percent` 는 정수라 한 장 생성으로는 눈금이 안 움직인다 - 회복까지 남은 시간은
    `timeUntilNextPercent`(초), 소진 판정은 `isNegative` 로 본다.
    실패하거나 서버가 `usage` 를 안 주면 None(= 표시하지 않음).
    """
    token = (token or "").strip()
    if not token:
        return None
    try:
        res = requests.get(
            NAI_SUBSCRIPTION_URL,
            headers={"Authorization": f"Bearer {token}"},
            timeout=5,
        )
        if res.status_code != 200:
            return None
        usage = (res.json() or {}).get("usage")
        if not isinstance(usage, dict):
            return None
        return {
            "percent": int(usage.get("percent", 0) or 0),
            "is_negative": bool(usage.get("isNegative", False)),
            "seconds_until_next_percent": int(usage.get("timeUntilNextPercent", 0) or 0),
        }
    except requests.exceptions.RequestException:
        return None
    except Exception:  # pragma: no cover
        return None


def test_comfyui_connection(url: str) -> bool:
    """빠른 boolean 판정 (내부 유틸)."""
    if not (url or "").strip():
        return False
    clean, _ = _split_protocol(url)
    try:
        res = requests.get(f"http://{clean}/system_stats", timeout=5)
        return res.status_code == 200
    except requests.exceptions.RequestException:
        return False
