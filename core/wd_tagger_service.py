# -*- coding: utf-8 -*-
"""WD14 이미지 태거 — HuggingFace Space(`SmilingWolf/wd-tagger`)를 HTTP 로 부른다.

## 왜 로컬 추론이 아닌가

Dev0714 의 태거는 `onnxruntime` 으로 직접 추론했다. 그러려면 (a) 번들 파이썬에
onnxruntime 휠, (b) 모델 380MB 온디맨드 다운로드, (c) 그 다운로드/설치 UI 가 전부
필요하다. 원격 호출은 그 셋을 통째로 없앤다.

## ⚠️ 이미지가 외부로 나간다

이 서비스는 **사용자의 이미지를 제3자 서버(huggingface.co)로 업로드한다.**
NAIA 출력에는 강한 NSFW 가 있을 수 있다. 화면에 반드시 명시할 것 — 사용자가
알고 누르는 것과 모르고 눌리는 것은 다르다(사용자 결정 2026-08-31).

## 왜 `gradio_client` 를 안 쓰는가

문서가 권하는 `gradio_client` 는 `huggingface_hub` · `fsspec` 등을 끌고 온다.
포터블 런타임(`user-data/runtime-env`)에는 그것들이 **없고** `requests` 는 **있다**
(실측 2026-08-31). Gradio 의 REST 는 3단계뿐이라 직접 부르면 의존성이 0이다.

    POST /gradio_api/upload            -> ["/tmp/gradio/<hash>/name.png"]
    POST /gradio_api/call/predict      -> {"event_id": "..."}
    GET  /gradio_api/call/predict/<id> -> SSE, 마지막 `data:` 줄이 결과

## 실측 (2026-08-31)

- 콜드 스타트 ~13s · 웜 3.5~4.2s. 인증 불필요.
- 832x1216 PNG 를 그대로 올리면 업로드만 2.3~2.5s(3MB) — 합 6.0~6.7s.
- **정사각 패딩 후 448 로 줄여 보내도 태그가 완전히 같다**(6/6 일치). 모델이
  어차피 448 로 줄이므로 그 전처리를 여기서 해 업로드를 줄인다 -> 합 ~4.4s.

## 미측정

레이트 리밋 · 이용약관 · 지속 사용 시 토큰 필요 여부. Space 가 잠들거나 큐가
밀리거나 API 스키마가 바뀌면 이 기능은 죽는다 — 죽어도 **앱의 다른 부분은
멀쩡해야 한다**(호출부는 예외를 삼키고 기능만 비활성).
"""
from __future__ import annotations

import io
import json
import time
from dataclasses import dataclass, field
from typing import Any

SPACE_BASE = "https://smilingwolf-wd-tagger.hf.space"
API_NAME = "predict"

# Space 의 Model Dropdown 이 받는 값들. 앞의 것이 기본(문서 기본값과 같다).
MODEL_REPOS = (
    "SmilingWolf/wd-swinv2-tagger-v3",
    "SmilingWolf/wd-convnext-tagger-v3",
    "SmilingWolf/wd-vit-tagger-v3",
    "SmilingWolf/wd-vit-large-tagger-v3",
    "SmilingWolf/wd-eva02-large-tagger-v3",
    "SmilingWolf/wd-v1-4-moat-tagger-v2",
    "SmilingWolf/wd-v1-4-swinv2-tagger-v2",
    "SmilingWolf/wd-v1-4-convnext-tagger-v2",
    "SmilingWolf/wd-v1-4-convnextv2-tagger-v2",
    "SmilingWolf/wd-v1-4-vit-tagger-v2",
    "deepghs/idolsankaku-swinv2-tagger-v1",
    "deepghs/idolsankaku-eva02-large-tagger-v1",
)
DEFAULT_MODEL = MODEL_REPOS[0]

# 모델 입력 해상도. 이 값으로 줄여 보내도 태그가 같다(실측) — 업로드를 줄이는 것이
# 유일한 목적이므로, 모델이 바뀌어 입력 크기가 달라져도 서버가 다시 줄일 뿐이다.
MODEL_INPUT_SIZE = 448
# 원본이 이보다 작으면 **확대하지 않는다.** 확대는 태그를 바꾼다(실측: 61x68 짜리를
# 448 로 키웠더니 9종 중 4종이 달라졌다) — 서버가 알아서 하게 둔다.
UPLOAD_MAX_BYTES = 32 * 1024 * 1024

# 콜드 스타트가 13초쯤 걸린다(실측). 넉넉히 주되 무한은 아니다.
TIMEOUT_UPLOAD = 90.0
TIMEOUT_CALL = 30.0
TIMEOUT_RESULT = 180.0


class TaggerError(RuntimeError):
    """사용자에게 그대로 보여도 되는 실패."""


@dataclass
class TagResult:
    tag_string: str = ""
    general: list[dict[str, Any]] = field(default_factory=list)
    character: list[dict[str, Any]] = field(default_factory=list)
    rating: list[dict[str, Any]] = field(default_factory=list)
    elapsed_ms: int = 0
    sent_size: tuple[int, int] | None = None

    def payload(self) -> dict[str, Any]:
        return {
            "ok": True,
            "tag_string": self.tag_string,
            "general": self.general,
            "character": self.character,
            "rating": self.rating,
            "elapsed_ms": self.elapsed_ms,
            "sent_size": list(self.sent_size) if self.sent_size else None,
        }


def _requests():
    try:
        import requests  # noqa: PLC0415 — 선택적 의존성처럼 다룬다
    except Exception as exc:  # pragma: no cover - 런타임에 항상 있다
        raise TaggerError(f"requests 를 불러오지 못했습니다: {exc}") from exc
    return requests


def prepare_upload_bytes(image_bytes: bytes) -> tuple[bytes, tuple[int, int]]:
    """업로드용으로 줄인다 — **정사각 패딩 후 448**(모델 전처리와 같은 순서).

    ⚠️ 원본이 448 보다 작으면 그대로 보낸다. 확대는 태그를 바꾼다(실측).
    """
    from PIL import Image

    with Image.open(io.BytesIO(image_bytes)) as raw:
        raw.load()
        image = raw.convert("RGB")

    width, height = image.size
    side = max(width, height)
    if side <= MODEL_INPUT_SIZE:
        # 이미 작다 — 손대면 오히려 결과가 달라진다.
        buf = io.BytesIO()
        image.save(buf, "PNG")
        return buf.getvalue(), (width, height)

    square = Image.new("RGB", (side, side), (255, 255, 255))
    square.paste(image, ((side - width) // 2, (side - height) // 2))
    small = square.resize((MODEL_INPUT_SIZE, MODEL_INPUT_SIZE), Image.BICUBIC)
    buf = io.BytesIO()
    small.save(buf, "PNG")
    return buf.getvalue(), (MODEL_INPUT_SIZE, MODEL_INPUT_SIZE)


def _confidences(block: Any) -> list[dict[str, Any]]:
    """Gradio Label 컴포넌트의 `{label, confidences:[{label, confidence}]}` 를 편다."""
    if not isinstance(block, dict):
        return []
    rows = block.get("confidences")
    if not isinstance(rows, list):
        return []
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = str(row.get("label") or "").strip()
        if not name:
            continue
        try:
            score = float(row.get("confidence") or 0.0)
        except (TypeError, ValueError):
            score = 0.0
        # Danbooru 원문은 밑줄이다 — 프롬프트에 그대로 쓸 수 있게 공백으로 편다
        # (Dev0714 태거도 같은 처리를 했다).
        out.append({"tag": name.replace("_", " "), "score": round(score, 4)})
    return out


def _last_sse_data(response: Any) -> str:
    """SSE 스트림에서 **마지막** `data:` 줄을 돌려준다.

    Gradio 는 진행 이벤트(`data: null` 등)를 여러 번 보내고 마지막에 결과를 준다.
    첫 줄을 집으면 진행 상태를 결과로 착각한다.
    """
    last = ""
    for raw in response.iter_lines(decode_unicode=True):
        if raw and raw.startswith("data: "):
            last = raw[6:]
    return last


def tag_image(
    image_bytes: bytes,
    *,
    general_thresh: float = 0.35,
    character_thresh: float = 0.85,
    model_repo: str = DEFAULT_MODEL,
    general_mcut: bool = False,
    character_mcut: bool = False,
    base_url: str = SPACE_BASE,
) -> TagResult:
    """이미지를 원격 태거에 보내 태그를 받는다.

    ⚠️ 이 호출은 **이미지를 외부 서버로 보낸다.** 호출부는 사용자에게 그 사실을
    이미 알렸어야 한다.
    """
    if not image_bytes:
        raise TaggerError("이미지가 비어 있습니다.")
    if len(image_bytes) > UPLOAD_MAX_BYTES:
        raise TaggerError("이미지가 너무 큽니다.")
    repo = str(model_repo or DEFAULT_MODEL)
    if repo not in MODEL_REPOS:
        raise TaggerError(f"알 수 없는 모델입니다: {repo}")

    requests = _requests()
    started = time.time()
    payload_bytes, sent_size = prepare_upload_bytes(image_bytes)

    try:
        upload = requests.post(
            f"{base_url}/gradio_api/upload",
            files={"files": ("image.png", io.BytesIO(payload_bytes), "image/png")},
            timeout=TIMEOUT_UPLOAD,
        )
    except Exception as exc:
        raise TaggerError(f"태거 서버에 연결하지 못했습니다: {exc}") from exc
    if upload.status_code != 200:
        raise TaggerError(f"이미지 업로드 실패(HTTP {upload.status_code}).")
    try:
        remote_path = upload.json()[0]
    except Exception as exc:
        raise TaggerError(f"업로드 응답을 이해하지 못했습니다: {exc}") from exc

    body = {
        "data": [
            {"path": remote_path, "meta": {"_type": "gradio.FileData"}},
            repo,
            float(general_thresh),
            bool(general_mcut),
            float(character_thresh),
            bool(character_mcut),
        ]
    }
    try:
        call = requests.post(
            f"{base_url}/gradio_api/call/{API_NAME}", json=body, timeout=TIMEOUT_CALL
        )
    except Exception as exc:
        raise TaggerError(f"태거 호출에 실패했습니다: {exc}") from exc
    if call.status_code != 200:
        raise TaggerError(f"태거 호출 실패(HTTP {call.status_code}).")
    try:
        event_id = call.json()["event_id"]
    except Exception as exc:
        raise TaggerError(f"태거 응답을 이해하지 못했습니다: {exc}") from exc

    try:
        stream = requests.get(
            f"{base_url}/gradio_api/call/{API_NAME}/{event_id}",
            stream=True,
            timeout=TIMEOUT_RESULT,
        )
        raw_result = _last_sse_data(stream)
    except Exception as exc:
        raise TaggerError(f"태거 결과를 받지 못했습니다: {exc}") from exc
    if not raw_result:
        raise TaggerError("태거가 결과를 돌려주지 않았습니다(대기열이 밀렸을 수 있습니다).")
    try:
        data = json.loads(raw_result)
    except Exception as exc:
        raise TaggerError(f"태거 결과를 해석하지 못했습니다: {exc}") from exc
    if not isinstance(data, list) or len(data) < 4:
        # 오류일 때 Gradio 는 다른 모양을 준다 — 그것을 태그로 오해하지 않는다.
        raise TaggerError("태거가 예상과 다른 결과를 돌려줬습니다.")

    tag_string = ", ".join(
        part.strip().replace("_", " ") for part in str(data[0] or "").split(",") if part.strip()
    )
    return TagResult(
        tag_string=tag_string,
        rating=_confidences(data[1]),
        character=_confidences(data[2]),
        general=_confidences(data[3]),
        elapsed_ms=int((time.time() - started) * 1000),
        sent_size=sent_size,
    )
