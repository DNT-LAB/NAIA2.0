"""NAIA Custom Extension 런타임 — 로더 + 공식 표면(ExtensionContext) v1.

사용자 확장은 user-data의 ``extensions/<ext-id>/`` 아래에 두며 NAIA 소스 트리를
건드리지 않는다(업데이트 생존). 확장이 의지할 수 있는 **공식 표면은
ExtensionContext의 공개 메서드뿐**이다 — 그 외 내부 모듈 import는 동작하더라도
릴리즈마다 깨질 수 있다(naia_ext_api=1, experimental).

레이아웃::

    user-data/extensions/<ext-id>/
        extension.json   {"id", "name", "version", "naia_ext_api": 1, "entry": "main.py"}
        main.py          def register(ctx: ExtensionContext) -> None  를 export
        settings.json    (선택) ctx.load_settings()/save_settings() 저장소

안전 계약:
- 확장 로드/콜백 실패는 어떤 경우에도 부팅·생성 루프를 깨지 않는다(per-ext 격리).
  이벤트 버스 publish는 콜백 예외를 잡지 않으므로, 확장 콜백은 반드시 안전
  래퍼를 거쳐 구독된다(연속 실패 시 자동 음소거).
- 파이프라인 훅 priority 0~99는 코어 예약 대역 — 확장 훅은 100 미만을 100으로
  클램프한다(코어 훅(PE=10, 조건부 DSL=2 등)보다 항상 뒤에 실행).
- 신뢰 모델: 확장은 in-process 임의 Python이며 샌드박스가 없다. 설치 = 제작자
  신뢰. 자세한 고지는 README의 Extensions 섹션 참조.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

NAIA_EXT_API_VERSION = 1
EXT_DISABLE_ENV = "NAIA_DISABLE_EXTENSIONS"
EXT_DIR_ENV = "NAIA_EXT_DIR"
# 0~99는 코어 훅 예약 대역(PE/조건부 DSL 등). 확장은 100 이상만 허용.
EXT_HOOK_PRIORITY_MIN = 100
# 같은 이벤트 콜백이 연속으로 이 횟수만큼 예외를 던지면 음소거한다.
EXT_CALLBACK_MUTE_THRESHOLD = 5
# 확장 파생 요청의 최대 체인 깊이. allow_chain=True여도 이 깊이를 넘는
# enqueue는 무조건 거부된다(버그성 무한 연쇄의 호스트 측 절대 상한).
EXT_CHAIN_DEPTH_MAX = 4
# show_toast 남용 방어(Codex R1-#3): 확장당 최소 발행 간격(초) + 재진입 차단.
EXT_TOAST_MIN_INTERVAL = 0.25
SETTINGS_FILENAME = "settings.json"
# 확장 퀵 버튼의 메인 UI 노출 위치: 도구바(독립 바) / 자동화·고급 기능 카테고리 /
# 없음. (프롬프트 도구는 항목이 많아 스크롤 폴드에 묻히고, Fn 메뉴는 팝업 앵커
# UX가 나빠 제외 — 저장돼 있던 구 값은 로드 시 기본값 tools로 폴백된다.)
PLACEMENT_VALUES = ("tools", "assistant_tools", "none")
PLACEMENT_DEFAULT = "tools"
# 시작 동작(전역 정책): 작동 스위치(armed)를 부팅 시 어떻게 초기화할지.
#  remember = 종료 시점 상태 복원(disarmed config) / auto_off = 항상 꺼짐 /
#  auto_on = 항상 켜짐. 부팅(로드) 시에만 적용 — 런타임 토글은 그대로.
STARTUP_VALUES = ("remember", "auto_off", "auto_on")
STARTUP_DEFAULT = "remember"


def _ext_print(ext_id: str, message: str) -> None:
    print(f"[ext:{ext_id}] {message}", flush=True)


def _json_sanitize(value: Any) -> Any:
    """save_settings 폴백용 재귀 정화 — 비유한 float(NaN/inf)를 repr 문자열로
    강등해, 폴백 경로에서도 비표준 JSON 리터럴이 파일에 남지 않게 한다
    (Codex R4-#5; 키는 str 강제, 직렬화 불가 타입은 dumps의 default=repr 몫)."""
    try:
        if isinstance(value, dict):
            return {str(key): _json_sanitize(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [_json_sanitize(item) for item in value]
        if isinstance(value, float) and (value != value or value in (float("inf"), float("-inf"))):
            return repr(value)
        return value
    except (SystemExit, Exception):
        return repr(value)


def _safe_error_text(exc: BaseException) -> str:
    """예외 객체의 **무예외** 문자열화 — __str__/__repr__이 던지는 적대적 예외
    (SystemExit 포함)가 로깅 경로에서 다시 터져 격리 래퍼 밖으로 새는 것을 막는다."""
    try:
        return str(exc)
    except (SystemExit, Exception):
        try:
            return repr(exc)
        except (SystemExit, Exception):
            return "<unrepresentable exception>"


# 현재 스레드가 처리 중인 이벤트의 확장 체인 깊이(요청 lineage 기반).
# 사용자 요청 이벤트 = 0, 확장 파생 요청 이벤트 = 그 요청의 _ext_chain_depth.
# 깊이 1 이상에서의 enqueue_generation은 기본 차단(allow_chain으로 해제 가능),
# EXT_CHAIN_DEPTH_MAX 초과는 allow_chain과 무관하게 무조건 차단 — A확장 변형에
# B확장이 또 생성을 붙이는 무한 연쇄(큐 폭주)를 호스트 차원에서 끊는다.
_CHAIN_GUARD = threading.local()
# show_toast 재진입 가드 — extension_toast 구독 콜백 안에서의 재호출(무한 재귀) 차단.
_TOAST_GUARD = threading.local()


def _current_event_chain_depth() -> int:
    return int(getattr(_CHAIN_GUARD, "event_depth", 0) or 0)


def _coerce_chain_depth(raw: Any) -> int:
    """체인 깊이의 **무예외** 강제 변환.

    None → 0(미기록), 변환 실패(비숫자 문자열·float('inf')/nan의 OverflowError/
    ValueError·예외를 던지는 커스텀 __int__ 등 **모든** 예외) → 상한
    EXT_CHAIN_DEPTH_MAX = 그 이벤트에서 추가 체인 불가(fail-closed). 음수는 0으로
    클램프."""
    if raw is None:
        return 0
    try:
        depth = int(raw)
    except (SystemExit, Exception):
        return EXT_CHAIN_DEPTH_MAX
    return max(0, depth)


def ext_lineage_fields(params: Any) -> dict[str, Any]:
    """요청 params의 확장 lineage(``_ext_origin``/``_ext_chain_depth``)를 이벤트
    payload 필드(``ext_origin``/``ext_chain_depth``)로 **무조건 무예외** 변환한다.

    enqueue/저장이 끝난 뒤의 publish가 비정상 값으로 터져 split-brain이 되지
    않도록 함수 전체가 가드된다 — get()/truthiness가 던지는 적대적 dict 서브클래스/
    값을 포함해 어떤 입력에도 예외를 내지 않는다. 형식이 깨진 깊이·전면 실패는
    0(사용자 레벨)이 아니라 상한(EXT_CHAIN_DEPTH_MAX)으로 간주해 그 이벤트에서의
    추가 체인을 차단한다(fail-closed)."""
    try:
        origin = ""
        depth = 0
        if isinstance(params, dict):
            raw_origin = params.get("_ext_origin")
            if raw_origin:
                try:
                    origin = str(raw_origin)
                except (SystemExit, Exception):
                    origin = "<invalid>"
            depth = _coerce_chain_depth(params.get("_ext_chain_depth"))
        return {"ext_origin": origin, "ext_chain_depth": depth}
    except (SystemExit, Exception):
        return {"ext_origin": "", "ext_chain_depth": EXT_CHAIN_DEPTH_MAX}


def _callback_identity(callback: Callable[..., Any]) -> tuple:
    """bound method는 접근할 때마다 새 객체라 id()가 변한다 — (self, func) 정체성으로
    정규화해 subscribe/unsubscribe가 같은 키를 보게 한다."""
    bound_self = getattr(callback, "__self__", None)
    func = getattr(callback, "__func__", None)
    if bound_self is not None and func is not None:
        return (id(bound_self), id(func))
    return (id(callback),)


PANEL_FIELD_TYPES = {"bool", "int", "float", "select", "multiselect", "text", "tags", "list", "action"}
PANEL_APPLY_MODES = {"immediate", "next-generation", "restart-required"}


def _normalize_panel_fields(fields: Any) -> list[dict[str, Any]]:
    """register_panel 스키마 정규화 — 잘못된 필드는 건너뛰고(관용), 유효 필드는
    (section, order, 선언 순서)로 정렬해 돌려준다. ``action``은 버튼으로 렌더되어
    클릭 시 register_panel(on_action=...) 핸들러가 호출된다(설정 저장 없음)."""
    normalized: list[dict[str, Any]] = []
    if not isinstance(fields, (list, tuple)):
        return normalized
    for index, raw in enumerate(fields):
        try:
            entry = _normalize_panel_field(raw, index)
        except (SystemExit, Exception) as exc:
            # no-throw(Codex R6-#4): 적대적 메타(__str__/__int__ raising 등)는
            # 그 필드만 관용 스킵 — 정규화가 코어로 예외를 전파하지 않는다.
            # 침묵 누락 방지(R7): 어떤 필드가 왜 빠졌는지 로그를 남긴다.
            # except 핸들러 안이므로 로그 자체도 중첩 가드(R8) — stdout IO 실패
            # 같은 드문 경우에도 no-throw 계약을 지킨다.
            try:
                key_hint = str(raw.get("key")) if isinstance(raw, dict) else ""
                print(
                    "Remote Web: extension panel field skipped "
                    f"(index={index}, key={key_hint or '?'}) — {_safe_error_text(exc)}",
                    flush=True,
                )
            except (SystemExit, Exception):
                pass
            entry = None
        if entry is not None:
            normalized.append(entry)
    normalized.sort(key=lambda item: (item["section"], item["order"], item["_index"]))
    for entry in normalized:
        entry.pop("_index", None)
    return normalized


def _normalize_panel_field(raw: Any, index: int) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    key = str(raw.get("key") or "").strip()
    ftype = str(raw.get("type") or "").strip().lower()
    if not key or ftype not in PANEL_FIELD_TYPES:
        return None
    try:
        order = int(raw.get("order")) if isinstance(raw.get("order"), (int, float)) else index
    except (ValueError, OverflowError, TypeError):  # NaN/inf/적대 서브클래스 — 선언 순서 폴백
        order = index
    entry: dict[str, Any] = {
        "key": key,
        "type": ftype,
        "label": str(raw.get("label") or key),
        "help": str(raw.get("help") or ""),
        "section": str(raw.get("section") or ""),
        "order": order,
        "apply": (
            str(raw.get("apply")) if str(raw.get("apply") or "") in PANEL_APPLY_MODES else "immediate"
        ),
        # 다단 패널: left(기본) | right | extra — right/extra 필드가 보이면
        # 렌더러가 해당 칼럼을 펼친다(extra=스왑 빌더처럼 깊은 모드용 3번째 칸).
        "column": (
            str(raw.get("column"))
            if str(raw.get("column") or "") in {"right", "extra"}
            else "left"
        ),
        # 노출 계약: module(기본)=퀵 버튼 팝업(실제 동작 설정 전담) /
        # global=Settings ▸ Extension(전역 설정 — 저장 경로 등). 두 화면은
        # 서로의 scope 필드를 렌더하지 않는다.
        "scope": "global" if str(raw.get("scope") or "") == "global" else "module",
        "_index": index,
    }
    # 입력 예시/형식 안내(text/tags/number) — 렌더러가 placeholder 속성으로 표시.
    if str(raw.get("placeholder") or "").strip():
        entry["placeholder"] = str(raw.get("placeholder")).strip()
    # 긴 프롬프트 구문용: text/list 입력을 textarea(여러 줄)로 렌더.
    # `is True` 리터럴 체크 — 적대적 __bool__ 객체의 truthiness 평가를 피한다.
    if raw.get("multiline") is True and ftype in {"text", "list"}:
        entry["multiline"] = True
    # 조건부 표시: {"field": <다른 필드 key>, "in": [허용값...]} — 렌더러가 현재
    # 설정값으로 평가한다(예: 모드 select 값에 따라 우측 패널 등장). 컨트롤러
    # 필드 자신이 숨으면 종속 필드도 계단식으로 숨는다(렌더러 구현).
    visible_when = raw.get("visible_when")
    if isinstance(visible_when, dict) and str(visible_when.get("field") or "").strip():
        allowed = visible_when.get("in")
        entry["visible_when"] = {
            "field": str(visible_when.get("field")).strip(),
            "in": [str(item) for item in allowed] if isinstance(allowed, (list, tuple)) else [],
        }
    if "default" in raw:
        entry["default"] = raw.get("default")
    if ftype in {"int", "float"}:
        for bound in ("min", "max", "step"):
            if isinstance(raw.get(bound), (int, float)):
                entry[bound] = raw.get(bound)
    if ftype in {"select", "multiselect"}:
        options = [str(opt) for opt in (raw.get("options") or []) if str(opt).strip()]
        if not options:
            return None
        entry["options"] = options
    return entry


def _coerce_panel_value(field_def: dict[str, Any], value: Any) -> tuple[bool, Any, str]:
    """패널 입력값을 필드 타입으로 강제 변환한다 → (ok, coerced, error_message).

    실패 시 ok=False + 사용자에게 보여줄 메시지(인스펙션 #6 — 조용한 거부 금지)."""
    ftype = str(field_def.get("type") or "")
    try:
        if ftype == "bool":
            if isinstance(value, str):
                return True, value.strip().lower() in {"1", "true", "on", "yes"}, ""
            return True, bool(value), ""
        if ftype in {"int", "float"}:
            number = int(value) if ftype == "int" else float(value)
            minimum = field_def.get("min")
            maximum = field_def.get("max")
            if isinstance(minimum, (int, float)) and number < minimum:
                number = type(number)(minimum)
            if isinstance(maximum, (int, float)) and number > maximum:
                number = type(number)(maximum)
            return True, number, ""
        if ftype == "select":
            text = str(value)
            options = field_def.get("options") or []
            if text not in options:
                return False, None, f"허용값: {', '.join(options)}"
            return True, text, ""
        if ftype == "multiselect":
            options = [str(opt) for opt in (field_def.get("options") or [])]
            if isinstance(value, str):
                try:
                    value = json.loads(value)
                except Exception:
                    value = [part.strip() for part in value.split(",")]
            if not isinstance(value, (list, tuple)):
                return False, None, "목록이어야 합니다"
            chosen = [str(item) for item in value if str(item) in options]
            return True, chosen, ""  # 허용 외 값은 조용히 걸러냄(모드 전환 잔존 대비)
        if ftype == "list":
            if isinstance(value, str):
                try:
                    value = json.loads(value)
                except Exception:
                    value = [value]
            if not isinstance(value, (list, tuple)):
                return False, None, "목록이어야 합니다"
            items = [str(item).strip() for item in value]
            return True, [item for item in items if item], ""
        if ftype == "text":
            return True, str(value), ""
        if ftype == "tags":
            if isinstance(value, (list, tuple)):
                items = [str(item).strip() for item in value]
            else:
                items = [part.strip() for part in str(value).split(",")]
            return True, [item for item in items if item], ""
        return False, None, f"지원하지 않는 필드 타입: {ftype}"
    except (SystemExit, Exception) as exc:
        return False, None, f"값 변환 실패: {_safe_error_text(exc)}"


def _generation_service(app_context: Any):
    """app/backend의 generation_service() 헬퍼와 같은 캐시 슬롯을 공유한다."""
    service = getattr(app_context, "headless_generation_service", None)
    if service is None:
        from core.headless_generation_service import HeadlessGenerationService

        service = HeadlessGenerationService(app_context)
        app_context.headless_generation_service = service
    return service


@dataclass
class ExtensionRecord:
    ext_id: str
    directory: Path | None = None
    name: str = ""
    version: str = ""
    description: str = ""
    homepage: str = ""
    # lifecycle status: discovered(매니페스트만 읽음, 코드 미실행) | loading |
    # loaded | error | manifest_error. 차단/승인/소프트 on-off는 status가 아니라
    # 아래 사실(fact) 불리언으로 표현하고 UI 칩은 클라이언트가 조합해 파생한다
    # (설계 인스펙션 #3: 단일 status 문자열로 뭉개지 않는다).
    status: str = "discovered"
    error: str = ""
    approved: bool = False   # 사용자 동의(=import 허용). 동의 전에는 코드 미실행.
    blocked: bool = False    # 하드 OFF — 부팅 시 import 제외(승인보다 우선).
    enabled: bool = True     # Settings ON/OFF — OFF면 작동 정지 + 퀵 버튼 숨김.
    armed: bool = True       # 모듈 작동 스위치(팝업 Activate) — OFF여도 노출은 유지.
    placement: str = PLACEMENT_DEFAULT  # 퀵 버튼 위치: tools | fn | none (호스트 UI 설정).
    # 전역 정책(부팅 시 적용): 시작 동작·입력 필드 기억.
    startup: str = STARTUP_DEFAULT       # remember | auto_off | auto_on.
    remember_inputs: bool = True         # OFF면 부팅 시 settings.json을 비워 기본값으로 시작.
    hooks: int = 0
    subscriptions: int = 0
    # Phase B: ctx.register_panel() 선언 스키마({"title","fields":[...]}) 또는 None.
    panel: dict[str, Any] | None = None
    # 매니페스트 파싱 시 확정되는 진입점(검증 완료 경로). 로드 시에만 사용.
    entry_path: Path | None = None
    # 설정 검증 실패 피드백(인스펙션 #6) — {field_key: message}, 성공 시 비움.
    field_errors: dict[str, str] = field(default_factory=dict)
    # action 타입 필드 버튼 클릭 핸들러(register_panel on_action) — 직렬화 제외.
    action_handler: Any = None

    @property
    def is_active(self) -> bool:
        """확장 코드가 실제로 동작해야 하는가 — 모든 래퍼 게이트가 이것만 본다.

        우선순위(인스펙션 #1): blocked > enabled > armed. 로드 안 된 상태면
        어차피 코드가 없으므로 자연히 비활성. enabled(Settings)는 노출까지
        끄는 마스터, armed(팝업 Activate)는 작동만 멈추는 모듈 스위치 — 두
        플래그의 분리는 사용자 계약(작동 OFF ≠ 숨김)."""
        return self.status == "loaded" and self.enabled and self.armed and not self.blocked

    def status_payload(self) -> dict[str, Any]:
        return {
            "id": self.ext_id,
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "homepage": self.homepage,
            "status": self.status,
            "error": self.error,
            "approved": self.approved,
            "blocked": self.blocked,
            "enabled": self.enabled,
            "armed": self.armed,
            "placement": self.placement,
            "startup": self.startup,
            "remember_inputs": self.remember_inputs,
            "active": self.is_active,
            "hooks": self.hooks,
            "subscriptions": self.subscriptions,
            "panel": self.panel,
            "field_errors": dict(self.field_errors),
            "directory": str(self.directory or ""),
        }


class _ExtensionHookAdapter:
    """확장 훅을 코어 파이프라인 레지스트리 계약에 맞춰 감싼다.

    - priority를 확장 대역(>=100)으로 클램프해 코어 훅 순서를 보호한다.
    - get_title()에 ``ext:<id>:`` 접두사를 붙여 SEAM observer/로그가 회귀
      발생원을 확장 단위로 호명할 수 있게 한다.
    - 실행 예외는 PromptProcessor._run_hooks가 per-hook으로 격리한다.
    - soft OFF(record.is_active=False)면 context를 그대로 통과시킨다(즉시 발효).
    """

    def __init__(self, record: ExtensionRecord, hook: Any):
        self._record = record
        self._ext_id = record.ext_id
        self._hook = hook
        raw = dict(hook.get_pipeline_hook_info() or {})
        declared = int(raw.get("priority", EXT_HOOK_PRIORITY_MIN) or EXT_HOOK_PRIORITY_MIN)
        priority = max(EXT_HOOK_PRIORITY_MIN, declared)
        if priority != declared:
            _ext_print(record.ext_id, f"hook priority {declared} -> {priority} (0~{EXT_HOOK_PRIORITY_MIN - 1}는 코어 예약 대역)")
        self._info = {
            "target_pipeline": str(raw.get("target_pipeline") or "PromptProcessor"),
            "hook_point": str(raw.get("hook_point") or "final_hookpoint"),
            "priority": priority,
        }

    def get_pipeline_hook_info(self) -> dict[str, Any]:
        return dict(self._info)

    def get_title(self) -> str:
        inner = ""
        getter = getattr(self._hook, "get_title", None)
        if callable(getter):
            try:
                inner = str(getter() or "")
            except (SystemExit, Exception):
                inner = ""
        return f"ext:{self._ext_id}:{inner or self._hook.__class__.__name__}"

    def execute_pipeline_hook(self, context: Any) -> Any:
        if not self._record.is_active:
            return context
        try:
            return self._hook.execute_pipeline_hook(context)
        except SystemExit as exc:
            # sys.exit()는 Exception이 아니라 코어 per-hook 격리(except Exception)를
            # 뚫고 생성 스레드를 죽인다 — 어댑터 경계에서 차단하고 no-op 처리.
            _ext_print(self._ext_id, f"hook blocked sys.exit(): {_safe_error_text(exc)}")
            return context


class ExtensionContext:
    """확장에게 주어지는 유일한 공식 표면(naia_ext_api=1).

    여기 있는 공개 메서드 외의 내부 모듈 접근은 지원되지 않는다(언제든 깨짐).
    """

    api_version = NAIA_EXT_API_VERSION

    def __init__(self, record: ExtensionRecord, app_context: Any):
        self._record = record
        self._app_context = app_context
        # 원본 콜백 정체성 -> (이벤트명, 안전 래퍼) 매핑(unsubscribe/teardown 용).
        self._wrapped: dict[tuple, tuple[str, Callable[..., Any]]] = {}
        # 등록한 훅 어댑터(teardown 시 레지스트리에서 제거).
        self._hook_adapters: list[Any] = []
        # show_toast 레이트 리밋 기준 시각(확장 인스턴스 단위).
        self._last_toast_at = 0.0

    # ── 식별/로그 ────────────────────────────────────────────────
    @property
    def ext_id(self) -> str:
        return self._record.ext_id

    @property
    def name(self) -> str:
        return self._record.name

    @property
    def version(self) -> str:
        return self._record.version

    @property
    def ext_dir(self) -> Path:
        return Path(self._record.directory or ".")

    def log(self, message: str) -> None:
        _ext_print(self.ext_id, str(message))

    # ── L1: 이벤트 구독 ──────────────────────────────────────────
    def subscribe(
        self,
        event_name: str,
        callback: Callable[..., Any],
        *,
        run_when_disarmed: bool = False,
    ) -> None:
        """이벤트 버스 구독. 콜백 예외는 격리되며 연속 실패 시 자동 음소거된다.

        v1 공식 이벤트: ``generation_request_dispatched``(payload에 읽기 전용
        params 스냅샷 포함), ``generation_result_available``, ``prompt_generated``.
        그 외 이벤트도 수신되지만 이름/페이로드 안정성은 보장하지 않는다.

        ``run_when_disarmed=True``는 **UI 메타 갱신 전용** 옵트인: 팝업
        Activate(armed)가 꺼져 있어도 콜백이 돈다 — 모드 전환 시 패널 선택지
        재구성(``api_mode_changed``/``api_options_refreshed`` → register_panel)
        처럼 생성에 개입하지 않는 갱신용. armed가 꺼져도 패널은 계속 노출되므로
        이 갱신이 막히면 선택지가 stale로 남는다. Settings OFF(enabled=False)와
        차단(blocked)·미로드는 여전히 항상 차단된다. 이 콜백 안에서의
        enqueue/cancel 같은 생성 개입은 금지(어차피 해당 API의 is_active
        게이트가 거부한다)."""
        key = (str(event_name), *_callback_identity(callback))
        if key in self._wrapped:
            return
        wrapped = self._safe_callback(
            str(event_name), callback, run_when_disarmed=bool(run_when_disarmed)
        )
        self._wrapped[key] = (str(event_name), wrapped)
        self._app_context.subscribe(str(event_name), wrapped)
        self._record.subscriptions += 1

    def unsubscribe(self, event_name: str, callback: Callable[..., Any]) -> None:
        entry = self._wrapped.pop((str(event_name), *_callback_identity(callback)), None)
        if entry is not None:
            self._app_context.unsubscribe(entry[0], entry[1])
            self._record.subscriptions = max(0, self._record.subscriptions - 1)

    def _safe_callback(
        self,
        event_name: str,
        callback: Callable[..., Any],
        *,
        run_when_disarmed: bool = False,
    ) -> Callable[..., Any]:
        state = {"errors": 0, "muted": False}

        def _runner(*args: Any, **kwargs: Any) -> None:
            if state["muted"]:
                return
            record = self._record
            if run_when_disarmed:
                # UI 메타 갱신 옵트인: armed(작동 스위치)만 우회 — 로드/승인/차단/
                # Settings OFF 게이트는 그대로 적용된다.
                if record.status != "loaded" or not record.enabled or record.blocked:
                    return
            elif not record.is_active:
                return
            payload = args[0] if args else None
            # 체인 깊이 전파: 확장 파생 요청 이벤트(ext_origin/ext_chain_depth 포함)는
            # 그 요청의 lineage 깊이를 쓰고, 체인 정보가 없는 이벤트(큐 이벤트 등
            # 중첩 발행)는 현재 문맥을 상속한다 — 비체인 이벤트 경유로 깊이가 0으로
            # 리셋되는 우회를 막는다.
            prev_depth = _current_event_chain_depth()
            try:
                if isinstance(payload, dict) and (
                    payload.get("ext_origin") or payload.get("ext_chain_depth")
                ):
                    # 무예외 강제 변환 — 깨진 깊이가 isolation try 바깥에서 터져
                    # publish의 이후 구독자 전달을 중단시키지 않게 한다. 체인
                    # 이벤트인데 깊이가 0/누락이면 최소 1로 간주.
                    event_depth = _coerce_chain_depth(payload.get("ext_chain_depth")) or 1
                else:
                    event_depth = prev_depth
            except (SystemExit, Exception):
                # get()/truthiness가 던지는 적대적 payload도 전달을 못 끊는다 —
                # 깊이는 상한으로 간주(fail-closed: 그 이벤트에서 체인 불가).
                event_depth = EXT_CHAIN_DEPTH_MAX
            _CHAIN_GUARD.event_depth = event_depth
            try:
                callback(*args, **kwargs)
                state["errors"] = 0
            # SystemExit(sys.exit())는 Exception이 아니라 격리를 뚫는다 — 명시적으로
            # 잡아 같은 음소거 경로로 보낸다. KeyboardInterrupt는 의도적으로 통과.
            except (SystemExit, Exception) as exc:
                # 로깅 경로까지 무예외 — __str__이 던지는 예외 객체가 여기서 다시
                # 터지면 publish의 이후 구독자 전달이 끊긴다(_safe_error_text +
                # 전체 가드).
                try:
                    state["errors"] += 1
                    self.log(
                        f"event '{event_name}' callback error "
                        f"({state['errors']}/{EXT_CALLBACK_MUTE_THRESHOLD}): "
                        f"{_safe_error_text(exc)}"
                    )
                    if state["errors"] >= EXT_CALLBACK_MUTE_THRESHOLD:
                        state["muted"] = True
                        self.log(f"event '{event_name}' callback muted (연속 실패 한도 초과)")
                except Exception:
                    pass
            finally:
                _CHAIN_GUARD.event_depth = prev_depth

        return _runner

    # ── L2: 프롬프트 파이프라인 훅 ───────────────────────────────
    def register_hook(self, hook: Any) -> None:
        """프롬프트 파이프라인 훅 등록.

        hook은 ``get_pipeline_hook_info() -> dict``와
        ``execute_pipeline_hook(context) -> context``를 구현해야 한다
        (interfaces.headless_module_protocol.HeadlessPipelineHook 계약).
        hook_point: pre_processing | post_processing | after_wildcard | final_hookpoint.
        """
        if not callable(getattr(hook, "get_pipeline_hook_info", None)) or not callable(
            getattr(hook, "execute_pipeline_hook", None)
        ):
            raise TypeError(
                "hook must implement get_pipeline_hook_info() and execute_pipeline_hook(context)"
            )
        adapter = _ExtensionHookAdapter(self._record, hook)
        self._app_context.register_pipeline_hook(adapter.get_pipeline_hook_info(), adapter)
        self._hook_adapters.append(adapter)
        self._record.hooks += 1

    # ── 설정 패널 선언(Phase B) ──────────────────────────────────
    def register_panel(
        self,
        fields: list[dict[str, Any]],
        *,
        title: str | None = None,
        on_action: Any = None,
    ) -> None:
        """Extensions 패널에 노출할 선언적 설정 폼을 등록한다(확장은 JS 0줄).

        field: {key(필수), type: bool|int|float|select|text|tags|action,
        label(=key), default, min/max/step(int/float), options(select),
        help(툴팁), placeholder, section(그룹), order(정렬), scope, column,
        visible_when, apply: immediate|next-generation|restart-required(기본
        immediate)}. 값은 ``settings.json``으로 라운드트립되며
        ``ctx.load_settings()``로 읽는 값과 같은 파일이다.

        ``action`` 타입은 버튼으로 렌더되고, 클릭 시 ``on_action(key)``가
        호출된다(설정 저장 없음). on_action 예외는 격리되어 로그만 남는다.
        """
        normalized = _normalize_panel_fields(fields)
        self._record.panel = {
            "title": str(title or self._record.name or self.ext_id),
            "fields": normalized,
        }
        self._record.action_handler = on_action if callable(on_action) else None

    # ── 생성 큐 ──────────────────────────────────────────────────
    def enqueue_generation(
        self,
        *,
        overrides: dict[str, Any] | None = None,
        prompt: str | None = None,
        negative_prompt: str | None = None,
        api_mode: str | None = None,
        prompt_run_id: str | None = None,
        priority: int = 0,
        allow_chain: bool = False,
    ) -> dict[str, Any]:
        """생성 요청을 큐에 추가한다(일반 Generate와 동일한 정규화 경로).

        파생 요청에는 ``_ext_origin``이 찍히고, 그 dispatched 이벤트의
        ``ext_origin`` 필드로 다시 확인할 수 있다 — 이벤트 콜백에서 이 메서드를
        호출하는 확장은 ext_origin이 빈 이벤트만 처리하는 것이 기본 패턴이다.
        나아가 호스트도 **확장 파생 이벤트를 처리 중인 동안의 호출을 기본
        차단**한다(확장끼리 서로의 파생 요청에 생성을 덧붙이는 무한 연쇄 방지).
        의도적 체인이면 ``allow_chain=True``로 해제할 수 있지만, 모든 파생 요청에
        체인 깊이가 기록되며 깊이 ``EXT_CHAIN_DEPTH_MAX``(4)를 넘는 enqueue는
        allow_chain과 무관하게 무조건 거부된다 — 버그성 무한 연쇄의 절대 상한.
        큐 삽입만 하며 소비 루프를 직접 깨우지는 않는다(생성 흐름 안에서 호출되면
        진행 중인 루프가 이어서 소비).
        """
        if not self._record.is_active:
            return {"ok": False, "request_id": "", "message": "extension disabled"}
        current_depth = _current_event_chain_depth()
        child_depth = current_depth + 1
        if child_depth > EXT_CHAIN_DEPTH_MAX:
            message = (
                f"chain depth cap: 확장 파생 체인 깊이 상한({EXT_CHAIN_DEPTH_MAX}) 초과 — "
                "enqueue_generation이 거부되었습니다(allow_chain으로도 해제 불가)"
            )
            self.log(message)
            return {"ok": False, "request_id": "", "message": message}
        if current_depth > 0 and not allow_chain:
            message = (
                "chained enqueue blocked: 확장 파생 요청 이벤트 처리 중에는 "
                "enqueue_generation이 차단됩니다(연쇄 폭주 방지, allow_chain=True로 해제)"
            )
            self.log(message)
            return {"ok": False, "request_id": "", "message": message}
        merged = dict(overrides or {})
        merged["_ext_origin"] = self.ext_id
        merged["_ext_chain_depth"] = child_depth
        merged.setdefault("_remote_queue_source", f"ext:{self.ext_id}")
        command: dict[str, Any] = {
            "type": f"ext:{self.ext_id}",
            "overrides": merged,
            "priority": int(priority or 0),
        }
        if prompt is not None:
            command["prompt"] = str(prompt)
        if negative_prompt is not None:
            command["negative_prompt"] = str(negative_prompt)
        if api_mode:
            command["api_mode"] = str(api_mode)
        if prompt_run_id:
            command["prompt_run_id"] = str(prompt_run_id)
        dispatch = _generation_service(self._app_context).enqueue_remote_request(command)
        return {
            "ok": bool(getattr(dispatch, "ok", False)),
            "request_id": str(getattr(dispatch, "request_id", "") or ""),
            "message": str(getattr(dispatch, "blocked_reason", "") or ""),
        }

    # ── 대기 요청 취소 ───────────────────────────────────────────
    def cancel_generation(self, request_id: Any) -> dict[str, Any]:
        """대기(pending) 중인 생성 요청을 큐에서 제거한다 → {ok, message}.

        이미 실행을 시작했거나 큐에 없는 요청은 제거되지 않는다(ok=False).
        용례: 그리드형 확장이 자신이 반응한 원본 요청을 파생 묶음으로 대체
        (예: X/Y Plot — 원본 1장을 취소하고 그리드만 남김).

        경합 보강(Codex R1-#2/R2): enqueue→dispatched 발행 사이에 소비 루프가
        먼저 dequeue해 간 요청은 remove가 놓친다 — 이 경우 톰스톤을 남겨
        러너가 실행 직전에 건너뛴다(mark/consume_cancellation). 반환 dict의
        ``skip_scheduled``가 True면 그 예약이 걸린 상태다: 호출자는 ok=True와
        거의 동일하게(원본이 안 나온다고) 취급하되, 이미 execute가 시작된
        마이크로초 윈도에서는 원본이 그대로 생성될 수 있음을 감안해야 한다
        (ok=True만이 확정 제거)."""
        if not self._record.is_active:
            return {"ok": False, "skip_scheduled": False, "message": "extension disabled"}
        try:
            rid = str(request_id or "").strip()
            if not rid:
                return {"ok": False, "skip_scheduled": False, "message": "request_id가 비었습니다"}
            queue = getattr(self._app_context, "generation_queue_manager", None)
            remover = getattr(queue, "remove_request", None)
            if not callable(remover):
                return {"ok": False, "skip_scheduled": False, "message": "큐 제거를 지원하지 않는 런타임입니다"}
            if bool(remover(rid)):
                return {"ok": True, "skip_scheduled": False, "message": ""}
            marker = getattr(queue, "mark_cancelled", None)
            if callable(marker) and marker(rid):
                # 큐엔 없지만 실행 전이면 러너가 톰스톤을 소비해 건너뛴다.
                return {
                    "ok": False,
                    "skip_scheduled": True,
                    "message": "큐에 없음 — 실행 전이면 건너뛰도록 예약됨",
                }
            return {"ok": False, "skip_scheduled": False, "message": "이미 실행 중이거나 큐에 없는 요청"}
        except (SystemExit, Exception) as exc:
            return {"ok": False, "skip_scheduled": False, "message": _safe_error_text(exc)}

    # ── 모드/토스트 ──────────────────────────────────────────────
    def get_api_mode(self) -> str:
        """현재 API 모드("NAI"/"WEBUI"/"COMFYUI") — 실패 시 "".

        의도적으로 is_active 게이트가 없다: register(ctx) 시점(status=loading,
        is_active=False)에 모드별 패널 옵션(샘플러 목록 등)을 구성하는 정당한
        용례가 있고, 부작용 없는 순수 읽기다(Codex R1-#1 검토 결과 — 상태를
        만지거나 와일드카드를 소모하는 resolve_nai_characters와 달리 무해)."""
        try:
            return str(self._app_context.get_api_mode() or "")
        except (SystemExit, Exception):
            return ""

    def get_sampler_options(self) -> list[str]:
        """현재 API 모드에서 **실제 사용 가능한** 샘플러 목록.

        WEBUI/COMFYUI는 연결(옵션 새로고침) 시 캐시된 라이브 목록
        (remote_option_cache["options_sampler"] — /sdapi/v1/samplers,
        /object_info 유래, 20개 이상일 수 있음)을 우선 사용하고, 캐시가 없으면
        (미연결) UI 표준 폴백 목록을 돌려준다. NAI는 표준 목록. 라이브 목록이
        갱신되면 "api_options_refreshed" 이벤트가 발행되므로, 선택지를 쓰는
        확장은 그 이벤트에서 register_panel을 다시 호출하면 된다.
        get_api_mode와 같은 사유로 is_active 게이트 없음(register 시점 사용,
        순수 읽기)."""
        try:
            mode = self.get_api_mode() or "NAI"
            if mode in ("WEBUI", "COMFYUI"):
                cache = getattr(self._app_context, "remote_option_cache", None)
                if isinstance(cache, dict):
                    cached = (cache.get(mode) or {}).get("options_sampler") or []
                    cleaned = [str(item).strip() for item in cached if str(item or "").strip()]
                    if cleaned:
                        return cleaned
            from core.headless_session_state_service import HeadlessSessionStateService

            return list(HeadlessSessionStateService.sampler_options_for_mode(mode))
        except (SystemExit, Exception):
            return []

    def show_toast(self, message: Any, level: str = "info") -> None:
        """사용자에게 토스트 표시(연결된 웹 클라이언트 전원).

        level: info | success | warning | error. 백엔드의 "extension_toast"
        이벤트 → WS 브릿지로 중계되며, 브릿지/클라이언트가 없으면 콘솔 로그만
        남는다(무해). 검증 실패 안내("시작 프롬프트가 프롬프트에 없습니다" 등)
        같은 사용자 피드백 용도.

        남용 방어(Codex R1-#3): ① 같은 스레드 재진입 차단 — extension_toast를
        구독한 확장이 콜백에서 다시 show_toast를 불러도 무한 재귀가 되지 않는다.
        ② 확장당 최소 발행 간격(EXT_TOAST_MIN_INTERVAL) — 루프성 호출은 로그만
        남기고 드롭해 WS 브로드캐스트 폭주를 막는다."""
        if not self._record.is_active:
            return
        if getattr(_TOAST_GUARD, "active", False):
            self.log("show_toast 재진입 차단(extension_toast 콜백 안에서 호출)")
            return
        try:
            text = str(message or "").strip()
            if not text:
                return
            now = time.monotonic()
            if now - self._last_toast_at < EXT_TOAST_MIN_INTERVAL:
                self.log(f"toast 드롭(rate-limit {EXT_TOAST_MIN_INTERVAL}s): {text[:80]}")
                return
            self._last_toast_at = now
            lvl = str(level or "info").lower()
            if lvl not in {"info", "success", "warning", "error"}:
                lvl = "info"
            self.log(f"toast({lvl}): {text}")
            _TOAST_GUARD.active = True
            try:
                self._app_context.publish(
                    "extension_toast",
                    {"message": text[:300], "level": lvl, "ext_id": self.ext_id},
                )
            finally:
                _TOAST_GUARD.active = False
        except (SystemExit, Exception) as exc:
            self.log(f"show_toast failed: {_safe_error_text(exc)}")

    # ── 결과 조회 / 저장 경로 ────────────────────────────────────
    def get_result_image(self, request_id: Any) -> dict[str, Any]:
        """완료된 생성 요청의 이미지를 돌려준다 → {ok, image, file_path, message}.

        image는 히스토리 원본의 **PIL 사본**(확장이 변형해도 히스토리 불변).
        file_path는 자동 저장이 이미 끝났으면 그 경로, 아니면 ""(저장은 결과
        이벤트 뒤 비동기일 수 있다). generation_result_available 콜백에서
        이벤트의 request_id로 호출하는 것이 기본 패턴."""
        if not self._record.is_active:
            return {"ok": False, "image": None, "file_path": "", "message": "extension disabled"}
        try:
            rid = str(request_id or "").strip()
            store = getattr(self._app_context, "result_store", None)
            finder = getattr(store, "find_by_generation_request_id", None)
            if not rid or not callable(finder):
                return {"ok": False, "image": None, "file_path": "", "message": "결과 저장소 없음"}
            item = finder(rid)
            image = getattr(item, "image", None) if item is not None else None
            if image is None:
                return {"ok": False, "image": None, "file_path": "", "message": "해당 요청의 결과 없음"}
            return {
                "ok": True,
                "image": image.copy(),
                "file_path": str(getattr(item, "filepath", "") or ""),
                "message": "",
            }
        except (SystemExit, Exception) as exc:
            return {"ok": False, "image": None, "file_path": "", "message": _safe_error_text(exc)}

    def get_save_directory(self) -> str:
        """현재 세션의 이미지 자동 저장 디렉터리 경로(str). 실패 시 ""."""
        if not self._record.is_active:
            return ""
        try:
            current = getattr(self._app_context, "_current_save_directory", None)
            if callable(current):
                return str(current())
        except (SystemExit, Exception) as exc:
            self.log(f"get_save_directory failed: {_safe_error_text(exc)}")
        return ""

    # ── NAI 캐릭터 스냅샷 ────────────────────────────────────────
    def resolve_nai_characters(self) -> dict[str, Any] | None:
        """현재 캐릭터 설정을 **지금 1회 전개**(와일드카드 포함)한 스냅샷을 돌려준다.

        반환: {"characters": [...], "uc": [...], "character_positions": [...]} 또는
        None(캐릭터 비활성/NAI 아님/비활성 확장/실패). 이 스냅샷을
        enqueue_generation의 overrides에 그대로 실으면 해당 요청은 실행 시 늦은
        바인딩(매번 재전개) 대신 스냅샷을 사용한다 — 변형 묶음의 캐릭터 고정용.
        전개는 와일드카드 롤을 소모하는 부작용이 있으므로 비활성 확장은 차단
        (Codex R1-#1).
        """
        if not self._record.is_active:
            return None
        try:
            mode = str(self._app_context.get_api_mode() or "NAI")
            if mode != "NAI":
                return None
            from core.character_settings import character_params_from_settings

            snap = character_params_from_settings(self._app_context, mode=mode)
            if snap and snap.get("characters"):
                return {
                    "characters": [str(c) for c in snap["characters"]],
                    "uc": [str(u) for u in (snap.get("uc") or [])],
                    "character_positions": list(snap.get("character_positions") or []),
                }
        except (SystemExit, Exception) as exc:
            self.log(f"resolve_nai_characters failed: {_safe_error_text(exc)}")
        return None

    # ── 설정 영속 ────────────────────────────────────────────────
    def load_settings(self, defaults: dict[str, Any] | None = None) -> dict[str, Any]:
        """``<ext_dir>/settings.json``을 읽어 defaults 위에 병합해 돌려준다.

        파일이 없거나 깨져 있으면 defaults 사본을 반환한다(읽기 전용 — 파일을
        만들지는 않는다).
        """
        try:
            merged = dict(defaults or {})
        except (SystemExit, Exception):
            merged = {}
        try:
            path = self.ext_dir / SETTINGS_FILENAME
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                merged.update(raw)
        except FileNotFoundError:
            pass
        except (SystemExit, Exception) as exc:
            self.log(f"settings.json read failed ({_safe_error_text(exc)}) — defaults 사용")
        return merged

    def save_settings(self, data: dict[str, Any]) -> bool:
        """``settings.json`` 저장 → **무손실 성공 여부**. no-throw(Codex R1-#5/R2).

        True = JSON 라운드트립이 보장되는 저장 — 직렬화 결과를 다시 파싱해
        원본과 ==로 대조해 판정한다(json.dumps의 **암묵 변환**까지 탐지:
        비문자열 dict 키의 str 강제, tuple→list 등 — Codex R3-#5). 직렬화 불가
        값은 repr 문자열로 강등해 기록하고 False(데이터는 남되 라운드트립
        비보장 — load_settings는 변환된 형태를 돌려준다). IO 실패도 False+로그."""
        try:
            payload = dict(data or {})
            try:
                # allow_nan=False(Codex R4): NaN/inf는 표준 JSON이 아니다 — 여기서
                # ValueError로 떨어뜨려 아래 정화 폴백으로 강등한다(엄격한 외부
                # 파서가 못 읽는 비표준 리터럴을 파일에 남기지 않음).
                text = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False)
                lossless = json.loads(text) == payload
                if not lossless:
                    self.log("save_settings: JSON 암묵 변환 감지(비문자열 키/tuple 등) — 라운드트립 비보장")
            except (TypeError, ValueError):
                sanitized = _json_sanitize(payload)
                text = json.dumps(sanitized, ensure_ascii=False, indent=2, default=repr, allow_nan=False)
                lossless = False
                self.log("save_settings: 직렬화 불가/비표준 값을 repr 문자열로 기록(라운드트립 비보장)")
            path = self.ext_dir / SETTINGS_FILENAME
            path.write_text(text, encoding="utf-8")
            return lossless
        except (SystemExit, Exception) as exc:
            self.log(f"save_settings failed: {_safe_error_text(exc)}")
            return False

    # ── 내부: 부분 등록 롤백 ─────────────────────────────────────
    def _teardown(self) -> None:
        """register(ctx)가 도중에 실패했을 때 이미 걸린 구독/훅을 전부 회수한다.

        롤백이 없으면 status=error인 확장의 고아 콜백이 매 생성마다 계속 돈다.
        """
        for event_name, wrapped in list(self._wrapped.values()):
            try:
                self._app_context.unsubscribe(event_name, wrapped)
            except Exception:
                pass
        self._wrapped.clear()
        hooks_root = getattr(self._app_context, "pipeline_hooks", None)
        if isinstance(hooks_root, dict) and self._hook_adapters:
            adapter_ids = {id(adapter) for adapter in self._hook_adapters}
            for points in hooks_root.values():
                if not isinstance(points, dict):
                    continue
                for entries in points.values():
                    if isinstance(entries, list):
                        entries[:] = [
                            (priority, instance)
                            for priority, instance in entries
                            if id(instance) not in adapter_ids
                        ]
        self._hook_adapters.clear()
        self._record.hooks = 0
        self._record.subscriptions = 0
        self._record.action_handler = None


@dataclass
class ExtensionManager:
    app_context: Any
    records: list[ExtensionRecord] = field(default_factory=list)
    # 최초 도입 부팅에서 자동 승인(grandfather)된 id — 패널이 1회 안내 후 비운다.
    grandfathered: list[str] = field(default_factory=list)
    _loaded: bool = field(default=False, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def extensions_root(self) -> Path | None:
        env_dir = os.environ.get(EXT_DIR_ENV)
        if env_dir:
            return Path(env_dir)
        runtime_paths = getattr(self.app_context, "runtime_paths", None)
        if runtime_paths is None:
            return None
        try:
            return runtime_paths.extensions_dir
        except Exception:
            return None

    def load_all(self) -> list[ExtensionRecord]:
        if self._loaded:
            return self.records
        self._loaded = True
        if os.environ.get(EXT_DISABLE_ENV) == "1":
            print("Remote Web: extensions disabled by NAIA_DISABLE_EXTENSIONS=1", flush=True)
            return self.records
        with self._lock:
            self._discover_locked()
            self._apply_config_locked()
            for record in self.records:
                if record.status == "discovered" and record.approved and not record.blocked:
                    self._load_record_locked(record)
        if self.records:
            loaded = sum(1 for record in self.records if record.status == "loaded")
            print(
                f"Remote Web: extensions loaded {loaded}/{len(self.records)} from {self.extensions_root()}",
                flush=True,
            )
        return self.records

    def status_payload(self) -> list[dict[str, Any]]:
        return [record.status_payload() for record in self.records]

    def _find(self, ext_id: str) -> ExtensionRecord | None:
        clean = str(ext_id or "").strip()
        for record in self.records:
            if record.ext_id == clean:
                return record
        return None

    # ── 발견(코드 미실행) ────────────────────────────────────────
    def _discover_locked(self) -> None:
        """매니페스트만 스캔해 레코드를 만든다 — 동의(approve) 전에는 어떤 확장
        코드도 import/실행되지 않는다(슬라이스1 자동 로드의 보안 교정)."""
        root = self.extensions_root()
        if root is None or not root.is_dir():
            return
        known = {str(record.directory): record for record in self.records if record.directory}
        seen: set[str] = set()
        for manifest_path in sorted(root.glob("*/extension.json")):
            directory = manifest_path.parent
            seen.add(str(directory))
            existing = known.get(str(directory))
            if existing is not None:
                if existing.status in {"discovered", "manifest_error"}:
                    self._parse_manifest_into(manifest_path, existing)
                continue
            record = ExtensionRecord(ext_id=directory.name, directory=directory)
            self.records.append(record)
            self._parse_manifest_into(manifest_path, record)
        # 디렉터리가 사라진 미로드 레코드는 목록에서 제거(로드된 것은 세션 동안 유지).
        self.records[:] = [
            record
            for record in self.records
            if record.status not in {"discovered", "manifest_error"} or str(record.directory) in seen
        ]

    def _parse_manifest_into(self, manifest_path: Path, record: ExtensionRecord) -> None:
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if not isinstance(manifest, dict):
                raise ValueError("extension.json must be a JSON object")
            directory = manifest_path.parent
            ext_id = str(manifest.get("id") or directory.name).strip() or directory.name
            if any(other is not record and other.ext_id == ext_id for other in self.records):
                raise ValueError(f"duplicate extension id '{ext_id}'")
            declared_api = int(manifest.get("naia_ext_api", 0) or 0)
            if declared_api != NAIA_EXT_API_VERSION:
                record.ext_id = ext_id
                raise ValueError(
                    f"unsupported naia_ext_api={declared_api} (host={NAIA_EXT_API_VERSION})"
                )
            entry = str(manifest.get("entry") or "main.py")
            entry_path = (directory / entry).resolve()
            if not entry_path.is_relative_to(directory.resolve()):
                raise ValueError(f"entry escapes extension directory: {entry}")
            record.ext_id = ext_id
            record.name = str(manifest.get("name") or ext_id)
            record.version = str(manifest.get("version") or "")
            record.description = str(manifest.get("description") or "")
            # source_url은 향후 업데이트 체크용 예약 — v1은 homepage 폴백으로만 사용.
            record.homepage = str(manifest.get("homepage") or manifest.get("source_url") or "")
            record.entry_path = entry_path
            record.status = "discovered"
            record.error = ""
        except (SystemExit, Exception) as exc:
            record.status = "manifest_error"
            record.error = _safe_error_text(exc)
            print(
                f"Remote Web: extension manifest invalid '{record.ext_id}' - {record.error}",
                flush=True,
            )

    # ── 사실(approved/inactive/blocked) 영속 ─────────────────────
    def _config_path(self) -> Path | None:
        runtime_paths = getattr(self.app_context, "runtime_paths", None)
        if runtime_paths is None:
            return None
        try:
            return runtime_paths.config_dir / "extensions.json"
        except Exception:
            return None

    def _apply_config_locked(self) -> None:
        """config/extensions.json의 사실을 레코드에 적용한다.

        우선순위(설계 인스펙션 #1): blocked가 approved/enabled에 우선하며,
        inactive(soft OFF)는 approved에만 의미가 있다(쓰기 시 정규화).
        레거시 {"disabled": [...]} 키는 blocked로 이관. ``approved`` 키 자체가
        없으면(기능 도입 이전 설치 또는 NAIA_EXT_DIR 오버라이드/테스트 모드)
        현재 발견된 확장을 일괄 자동 승인(grandfather)하고 1회 안내 플래그를
        남긴다 — 이후 새로 발견되는 확장은 예외 없이 미승인에서 시작한다.
        """
        raw: dict[str, Any] = {}
        path = self._config_path()
        if path is not None:
            try:
                parsed = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(parsed, dict):
                    raw = parsed
            except FileNotFoundError:
                raw = {}
            except Exception as exc:
                print(f"Remote Web: extensions.json read failed - {_safe_error_text(exc)}", flush=True)

        def _ids(key: str) -> set[str]:
            return {str(item).strip() for item in (raw.get(key) or []) if str(item).strip()}

        blocked = _ids("blocked") | _ids("disabled")
        inactive = _ids("inactive")
        if isinstance(raw.get("approved"), list):
            approved = _ids("approved")
        else:
            approved = {record.ext_id for record in self.records if record.status == "discovered"}
            newly = sorted(approved - blocked)
            if newly:
                self.grandfathered = newly
                print(
                    f"Remote Web: extensions grandfathered (최초 도입 일괄 승인): {', '.join(newly)}",
                    flush=True,
                )
        disarmed = _ids("disarmed")
        forget_inputs = _ids("forget_inputs")
        placement_map = raw.get("placement") if isinstance(raw.get("placement"), dict) else {}
        startup_map = raw.get("startup") if isinstance(raw.get("startup"), dict) else {}
        for record in self.records:
            record.approved = record.ext_id in approved
            record.blocked = record.ext_id in blocked
            record.enabled = record.ext_id not in inactive
            saved_startup = str(startup_map.get(record.ext_id) or "")
            record.startup = saved_startup if saved_startup in STARTUP_VALUES else STARTUP_DEFAULT
            # 시작 동작 정책으로 부팅 시 armed 초기화(런타임 토글은 이후 별도).
            if record.startup == "auto_off":
                record.armed = False
            elif record.startup == "auto_on":
                record.armed = True
            else:  # remember — 종료 시점 상태(disarmed) 복원
                record.armed = record.ext_id not in disarmed
            record.remember_inputs = record.ext_id not in forget_inputs
            # 입력 필드 기억 OFF: 부팅 시 settings.json을 비워 기본값으로 시작.
            if not record.remember_inputs:
                self._clear_settings_file(record)
            saved_placement = str(placement_map.get(record.ext_id) or "")
            record.placement = saved_placement if saved_placement in PLACEMENT_VALUES else PLACEMENT_DEFAULT
        self._write_config_locked()

    @staticmethod
    def _clear_settings_file(record: "ExtensionRecord") -> None:
        """확장의 settings.json을 제거한다(입력 필드 기억 OFF). 없으면 무시,
        실패도 무해(다음 load_settings가 defaults를 돌려줄 뿐)."""
        directory = getattr(record, "directory", None)
        if directory is None:
            return
        try:
            (directory / SETTINGS_FILENAME).unlink(missing_ok=True)
        except (SystemExit, Exception):
            pass

    def _write_config_locked(self) -> None:
        path = self._config_path()
        if path is None:
            return
        payload = {
            "approved": sorted({r.ext_id for r in self.records if r.approved}),
            # 정규화: inactive ⊆ approved (미승인 확장의 soft 상태는 무의미).
            "inactive": sorted({r.ext_id for r in self.records if r.approved and not r.enabled}),
            # 모듈 작동 스위치(팝업 Activate This Script) OFF — 노출은 유지된다.
            "disarmed": sorted({r.ext_id for r in self.records if r.approved and not r.armed}),
            "blocked": sorted({r.ext_id for r in self.records if r.blocked}),
            # 입력 필드 기억 OFF(기본 ON이라 OFF인 것만 기록).
            "forget_inputs": sorted({r.ext_id for r in self.records if r.approved and not r.remember_inputs}),
            # 기본값(tools)이 아닌 위치만 기록 — 맵에 없으면 tools.
            "placement": {
                r.ext_id: r.placement
                for r in sorted(self.records, key=lambda item: item.ext_id)
                if r.placement != PLACEMENT_DEFAULT
            },
            # 기본값(remember)이 아닌 시작 동작만 기록.
            "startup": {
                r.ext_id: r.startup
                for r in sorted(self.records, key=lambda item: item.ext_id)
                if r.startup != STARTUP_DEFAULT
            },
        }
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:
            print(f"Remote Web: extensions.json write failed - {_safe_error_text(exc)}", flush=True)

    # ── 로드(동의 후에만) ────────────────────────────────────────
    def _load_record_locked(self, record: ExtensionRecord) -> None:
        ctx: ExtensionContext | None = None
        record.status = "loading"
        try:
            entry_path = record.entry_path
            if entry_path is None or not entry_path.is_file():
                raise FileNotFoundError(f"entry not found: {entry_path}")
            module_name = f"naia_ext_{re.sub(r'[^0-9A-Za-z_]', '_', record.ext_id)}"
            spec = importlib.util.spec_from_file_location(module_name, entry_path)
            if spec is None or spec.loader is None:
                raise ImportError(f"cannot import entry: {entry_path}")
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)

            register = getattr(module, "register", None)
            if not callable(register):
                raise AttributeError("entry must export register(ctx)")
            ctx = ExtensionContext(record, self.app_context)
            register(ctx)
            record.status = "loaded"
            record.error = ""
            print(
                f"Remote Web: extension loaded id={record.ext_id} v{record.version or '?'} "
                f"hooks={record.hooks} subs={record.subscriptions}",
                flush=True,
            )
        # SystemExit(sys.exit())도 잡는다 — 버그성 확장이 import/register에서 sys.exit를
        # 불러도 부팅과 다음 확장 로드가 계속되어야 한다. KeyboardInterrupt는 통과.
        except (SystemExit, Exception) as exc:
            record.status = "error"
            record.error = _safe_error_text(exc)
            if ctx is not None:
                # register() 도중 실패: 이미 걸린 구독/훅을 회수해 고아 콜백을 막는다.
                try:
                    ctx._teardown()
                except Exception:
                    pass
            print(
                f"Remote Web: extension '{record.ext_id}' failed to load - {record.error}",
                flush=True,
            )

    # ── Extensions 패널 API (module_id="extensions") ─────────────
    def panel_state(self) -> dict[str, Any]:
        """패널 표시용 상태. 열 때마다 재발견하므로 새로 설치한 확장이 재시작
        없이 목록에 나타난다(승인은 절대 자동 부여되지 않는다)."""
        with self._lock:
            self._discover_locked()
            entries = []
            for record in self.records:
                entry = record.status_payload()
                entry["settings"] = self._panel_settings_locked(record)
                entries.append(entry)
            entries.sort(key=lambda item: (item["status"] != "loaded", str(item["name"]).lower()))
            notice = list(self.grandfathered)
            self.grandfathered = []
            root = self.extensions_root()
            return {
                "extensions": entries,
                "install_dir": str(root) if root is not None else "",
                "grandfathered": notice,
            }

    def _panel_settings_locked(self, record: ExtensionRecord) -> dict[str, Any] | None:
        if not record.panel or record.directory is None:
            return None
        values: dict[str, Any] = {}
        for field_def in record.panel.get("fields", []):
            if "default" in field_def:
                values[field_def["key"]] = field_def["default"]
        try:
            raw = json.loads((record.directory / SETTINGS_FILENAME).read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                values.update(raw)
        except FileNotFoundError:
            pass
        except Exception as exc:
            _ext_print(record.ext_id, f"settings.json read failed ({_safe_error_text(exc)})")
        return values

    def apply_panel_param(self, key: str, value: Any) -> None:
        """즉시 발효 키(enabled/blocked/setting). approve/retry는 import가 수반되므로
        호출자가 워커 스레드에서 load_by_key()로 처리한다(인스펙션 #2)."""
        action, _, rest = str(key or "").strip().partition(":")
        pending_action: Any = None
        with self._lock:
            if action == "enabled":
                record = self._find(rest)
                if record is not None:
                    record.enabled = _coerce_panel_value({"type": "bool"}, value)[1]
                    self._write_config_locked()
            elif action == "armed":
                record = self._find(rest)
                if record is not None:
                    record.armed = _coerce_panel_value({"type": "bool"}, value)[1]
                    self._write_config_locked()
            elif action == "blocked":
                record = self._find(rest)
                if record is not None:
                    record.blocked = _coerce_panel_value({"type": "bool"}, value)[1]
                    self._write_config_locked()
            elif action == "placement":
                record = self._find(rest)
                if record is not None and str(value) in PLACEMENT_VALUES:
                    record.placement = str(value)
                    self._write_config_locked()
            elif action == "startup":
                record = self._find(rest)
                if record is not None and str(value) in STARTUP_VALUES:
                    # 다음 부팅부터 적용(현재 armed는 건드리지 않음 — 의도된 계약).
                    record.startup = str(value)
                    self._write_config_locked()
            elif action == "remember_inputs":
                record = self._find(rest)
                if record is not None:
                    record.remember_inputs = _coerce_panel_value({"type": "bool"}, value)[1]
                    self._write_config_locked()
            elif action == "setting":
                ext_id, _, field_key = rest.partition(":")
                pending_action = self._apply_setting_locked(ext_id, field_key, value)
        # action 핸들러는 락 밖에서 — 느린 핸들러(폴더 열기 등)가 패널 잠금을
        # 붙들거나, 핸들러→매니저 재진입 데드락이 생기지 않게 한다.
        if pending_action is not None:
            ext_id, field_key, handler = pending_action
            try:
                handler(field_key)
            except (SystemExit, Exception) as exc:
                _ext_print(ext_id, f"on_action({field_key}) 실패: {_safe_error_text(exc)}")

    def _apply_setting_locked(self, ext_id: str, field_key: str, value: Any) -> Any:
        """일반 필드는 검증·영속까지 끝낸다(반환 None). action 필드는 호출자가
        락 해제 후 실행할 (ext_id, key, handler)를 돌려준다."""
        record = self._find(ext_id)
        if record is None or not record.panel or record.directory is None:
            return None
        field_def = next(
            (item for item in record.panel.get("fields", []) if item.get("key") == field_key),
            None,
        )
        if field_def is None:
            return None
        if field_def.get("type") == "action":
            handler = record.action_handler
            if record.is_active and callable(handler):
                return (record.ext_id, field_key, handler)
            return None
        ok, coerced, message = _coerce_panel_value(field_def, value)
        if not ok:
            record.field_errors[field_key] = message
            return
        record.field_errors.pop(field_key, None)
        path = record.directory / SETTINGS_FILENAME
        current: dict[str, Any] = {}
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                current = raw  # 선언 안 된 키 보존(B3)
        except FileNotFoundError:
            pass
        except Exception:
            pass
        current[field_key] = coerced
        try:
            path.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:
            record.field_errors[field_key] = f"저장 실패: {_safe_error_text(exc)}"

    def mark_loading(self, key: str) -> None:
        """approve/retry 백그라운드 처리 전, 패널에 '로딩 중'을 먼저 보여주기 위한 표시."""
        with self._lock:
            for record in self._load_targets(key):
                if record.status in {"discovered", "error"}:
                    record.status = "loading"

    def load_by_key(self, key: str) -> None:
        """approve:<id> / retry:<id> / retry_errors — import가 수반되는 무거운 경로.
        워커 스레드에서 호출된다(이벤트 루프 비차단, 매니저 락으로 직렬화)."""
        action, _, _ = str(key or "").strip().partition(":")
        with self._lock:
            for record in self._load_targets(key):
                if action == "approve":
                    if record.blocked or record.status == "manifest_error":
                        continue
                    record.approved = True
                    self._write_config_locked()
                if record.approved and not record.blocked and record.status in {"discovered", "loading", "error"}:
                    self._load_record_locked(record)

    def _load_targets(self, key: str) -> list[ExtensionRecord]:
        action, _, rest = str(key or "").strip().partition(":")
        if action in {"approve", "retry"}:
            record = self._find(rest)
            return [record] if record is not None else []
        if action == "retry_errors":
            return [record for record in self.records if record.status == "error"]
        return []


def load_extensions(app_context: Any) -> ExtensionManager:
    """컨텍스트당 한 번만 확장을 발견/로드한다(재호출은 no-op)."""
    manager = getattr(app_context, "extension_manager", None)
    if manager is None:
        manager = ExtensionManager(app_context)
        app_context.extension_manager = manager
    manager.load_all()
    return manager


__all__ = [
    "EXT_CALLBACK_MUTE_THRESHOLD",
    "EXT_CHAIN_DEPTH_MAX",
    "EXT_DIR_ENV",
    "EXT_DISABLE_ENV",
    "EXT_HOOK_PRIORITY_MIN",
    "ExtensionContext",
    "ExtensionManager",
    "ExtensionRecord",
    "NAIA_EXT_API_VERSION",
    "ext_lineage_fields",
    "load_extensions",
]
