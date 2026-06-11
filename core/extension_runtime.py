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
SETTINGS_FILENAME = "settings.json"


def _ext_print(ext_id: str, message: str) -> None:
    print(f"[ext:{ext_id}] {message}", flush=True)


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
    status: str = "pending"  # pending | loaded | disabled | error
    error: str = ""
    hooks: int = 0
    subscriptions: int = 0

    def status_payload(self) -> dict[str, Any]:
        return {
            "id": self.ext_id,
            "name": self.name,
            "version": self.version,
            "status": self.status,
            "error": self.error,
            "hooks": self.hooks,
            "subscriptions": self.subscriptions,
            "directory": str(self.directory or ""),
        }


class _ExtensionHookAdapter:
    """확장 훅을 코어 파이프라인 레지스트리 계약에 맞춰 감싼다.

    - priority를 확장 대역(>=100)으로 클램프해 코어 훅 순서를 보호한다.
    - get_title()에 ``ext:<id>:`` 접두사를 붙여 SEAM observer/로그가 회귀
      발생원을 확장 단위로 호명할 수 있게 한다.
    - 실행 예외는 PromptProcessor._run_hooks가 per-hook으로 격리한다.
    """

    def __init__(self, ext_id: str, hook: Any):
        self._ext_id = ext_id
        self._hook = hook
        raw = dict(hook.get_pipeline_hook_info() or {})
        declared = int(raw.get("priority", EXT_HOOK_PRIORITY_MIN) or EXT_HOOK_PRIORITY_MIN)
        priority = max(EXT_HOOK_PRIORITY_MIN, declared)
        if priority != declared:
            _ext_print(ext_id, f"hook priority {declared} -> {priority} (0~{EXT_HOOK_PRIORITY_MIN - 1}는 코어 예약 대역)")
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
    def subscribe(self, event_name: str, callback: Callable[..., Any]) -> None:
        """이벤트 버스 구독. 콜백 예외는 격리되며 연속 실패 시 자동 음소거된다.

        v1 공식 이벤트: ``generation_request_dispatched``(payload에 읽기 전용
        params 스냅샷 포함), ``generation_result_available``, ``prompt_generated``.
        그 외 이벤트도 수신되지만 이름/페이로드 안정성은 보장하지 않는다.
        """
        key = (str(event_name), *_callback_identity(callback))
        if key in self._wrapped:
            return
        wrapped = self._safe_callback(str(event_name), callback)
        self._wrapped[key] = (str(event_name), wrapped)
        self._app_context.subscribe(str(event_name), wrapped)
        self._record.subscriptions += 1

    def unsubscribe(self, event_name: str, callback: Callable[..., Any]) -> None:
        entry = self._wrapped.pop((str(event_name), *_callback_identity(callback)), None)
        if entry is not None:
            self._app_context.unsubscribe(entry[0], entry[1])
            self._record.subscriptions = max(0, self._record.subscriptions - 1)

    def _safe_callback(self, event_name: str, callback: Callable[..., Any]) -> Callable[..., Any]:
        state = {"errors": 0, "muted": False}

        def _runner(*args: Any, **kwargs: Any) -> None:
            if state["muted"]:
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
        adapter = _ExtensionHookAdapter(self.ext_id, hook)
        self._app_context.register_pipeline_hook(adapter.get_pipeline_hook_info(), adapter)
        self._hook_adapters.append(adapter)
        self._record.hooks += 1

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

    # ── 설정 영속 ────────────────────────────────────────────────
    def load_settings(self, defaults: dict[str, Any] | None = None) -> dict[str, Any]:
        """``<ext_dir>/settings.json``을 읽어 defaults 위에 병합해 돌려준다.

        파일이 없거나 깨져 있으면 defaults 사본을 반환한다(읽기 전용 — 파일을
        만들지는 않는다).
        """
        merged = dict(defaults or {})
        path = self.ext_dir / SETTINGS_FILENAME
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                merged.update(raw)
        except FileNotFoundError:
            pass
        except Exception as exc:
            self.log(f"settings.json read failed ({exc}) — defaults 사용")
        return merged

    def save_settings(self, data: dict[str, Any]) -> None:
        path = self.ext_dir / SETTINGS_FILENAME
        path.write_text(
            json.dumps(dict(data or {}), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

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


@dataclass
class ExtensionManager:
    app_context: Any
    records: list[ExtensionRecord] = field(default_factory=list)
    _loaded: bool = field(default=False, repr=False)

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
        root = self.extensions_root()
        if root is None or not root.is_dir():
            return self.records
        disabled = self._disabled_ids()
        for manifest_path in sorted(root.glob("*/extension.json")):
            self._load_one(manifest_path, disabled)
        if self.records:
            loaded = sum(1 for record in self.records if record.status == "loaded")
            print(
                f"Remote Web: extensions loaded {loaded}/{len(self.records)} from {root}",
                flush=True,
            )
        return self.records

    def status_payload(self) -> list[dict[str, Any]]:
        return [record.status_payload() for record in self.records]

    def _disabled_ids(self) -> set[str]:
        runtime_paths = getattr(self.app_context, "runtime_paths", None)
        if runtime_paths is None:
            return set()
        try:
            raw = json.loads(
                (runtime_paths.config_dir / "extensions.json").read_text(encoding="utf-8")
            )
            return {str(item).strip() for item in (raw.get("disabled") or []) if str(item).strip()}
        except FileNotFoundError:
            return set()
        except Exception as exc:
            print(f"Remote Web: extensions.json read failed - {exc}", flush=True)
            return set()

    def _load_one(self, manifest_path: Path, disabled: set[str]) -> None:
        directory = manifest_path.parent
        record = ExtensionRecord(ext_id=directory.name, directory=directory)
        self.records.append(record)
        ctx: ExtensionContext | None = None
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if not isinstance(manifest, dict):
                raise ValueError("extension.json must be a JSON object")
            record.ext_id = str(manifest.get("id") or directory.name).strip() or directory.name
            record.name = str(manifest.get("name") or record.ext_id)
            record.version = str(manifest.get("version") or "")

            declared_api = int(manifest.get("naia_ext_api", 0) or 0)
            if declared_api != NAIA_EXT_API_VERSION:
                record.status = "error"
                record.error = (
                    f"unsupported naia_ext_api={declared_api} (host={NAIA_EXT_API_VERSION})"
                )
                print(f"Remote Web: extension '{record.ext_id}' skipped - {record.error}", flush=True)
                return
            if record.ext_id in disabled:
                record.status = "disabled"
                print(f"Remote Web: extension '{record.ext_id}' disabled (config/extensions.json)", flush=True)
                return
            if any(
                other is not record and other.ext_id == record.ext_id and other.status == "loaded"
                for other in self.records
            ):
                raise ValueError(f"duplicate extension id '{record.ext_id}'")

            entry = str(manifest.get("entry") or "main.py")
            entry_path = (directory / entry).resolve()
            if not entry_path.is_relative_to(directory.resolve()):
                raise ValueError(f"entry escapes extension directory: {entry}")
            if not entry_path.is_file():
                raise FileNotFoundError(f"entry not found: {entry}")

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
