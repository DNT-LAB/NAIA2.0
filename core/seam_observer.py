"""
SEAM observer — 관측 전용(observation-only) 파이프라인 seam 계측기.

두 backbone 중 **PromptContext(파이프라인 버스)** 를 계측한다. PromptProcessor._run_hooks
에서 각 훅 실행 전후로 감시 필드의 얕은 스냅샷을 떠서
  (1) 어떤 필드가 바뀌었나          → writes  (= 그 훅이 버스 위에서 소유/변형하는 sub-asset)
  (2) 태그 필드 구조 불변식이 깨졌나 → violation (괄호 균형 등)
를 관측한다.

설계 원칙 (이 모듈은 절대 시스템을 깨지 않는다):
  - 절대 raise 안 함 / context 를 절대 mutate 안 함 / 제어 흐름 안 바꿈.
  - NAIA_SEAM_OBSERVE 가 켜졌을 때만 동작. 기본 OFF → 호출부 enabled 가드로 오버헤드 0.

**누적 방지(핵심)**: 매 훅·매 생성마다 기록하지 않는다 — 그러면 Auto-Gen 에서 수만 줄로 쌓인다.
'정보가 새로울 때만' 기록한다:
  - seam_manifest.json : 모듈→writes→hook_point 전체 지도. **append 아님, 덮어쓰기**.
                         훅 종류 수만큼만이라 항상 작고 수렴. (에이전트 판독용 manifest)
  - seam.log          : 처음 보는 (module,hook_point,writes-shape) 1회 + 불변식 위반(같은
                         위반은 1/10/100…회째에만 = throttle). novelty-gated → 워밍업 후 사실상 안 늘어남.

활성화:
  set NAIA_SEAM_OBSERVE=1
  (선택) set NAIA_SEAM_DIR=C:\\some\\dir            # 기본 = %TEMP%\\naia_seam
출력:
  <dir>/seam_manifest.json   <dir>/seam.log
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Optional

_TRUE = {"1", "true", "on", "yes"}
_LOG_MAX_BYTES = 512 * 1024  # novelty-gated라 도달할 일 없지만 방어적 상한

# 감시할 PromptContext 필드 (태그 버스 + 최종 출력)
_TAG_FIELDS = ("prefix_tags", "main_tags", "postfix_tags", "removed_tags", "global_append_tags")
_WATCH_FIELDS = _TAG_FIELDS + ("final_prompt",)


def _tags_struct_ok(value: Any) -> tuple[bool, str]:
    """보수적 구조 불변식: 괄호/대괄호/중괄호 균형. 깨지면 (False, 이유).

    이스케이프된 괄호(`\\(` `\\)`)는 제외하고 균형만 본다(오탐 회피). Closed Eyes Sync /
    조건부 DSL 의 괄호 파손 같은 버그를 '그 훅의 경계에서' 잡아내는 최소 불변식.
    """
    try:
        if value is None:
            return True, ""
        if isinstance(value, (list, tuple)):
            text = ", ".join(str(t) for t in value)
        else:
            text = str(value)
        stripped = (
            text.replace("\\(", "").replace("\\)", "")
            .replace("\\[", "").replace("\\]", "")
            .replace("\\{", "").replace("\\}", "")
        )
        for op, cl, name in (("(", ")", "paren"), ("[", "]", "bracket"), ("{", "}", "brace")):
            if stripped.count(op) != stripped.count(cl):
                return False, f"unbalanced {name}: {stripped.count(op)}x'{op}' vs {stripped.count(cl)}x'{cl}'"
        return True, ""
    except Exception:
        return True, ""  # 관측기는 절대 방해하지 않는다


def _is_log_milestone(count: int) -> bool:
    """1, 10, 100, 1000, ... 일 때만 True (반복 위반 throttle)."""
    if count < 1:
        return False
    while count % 10 == 0:
        count //= 10
    return count == 1


def _callback_label(callback: Any) -> str:
    """구독 콜백 → 'ClassName.method' 또는 'module.func' 라벨."""
    try:
        owner = getattr(callback, "__self__", None)
        name = getattr(callback, "__name__", None) or repr(callback)
        if owner is not None:
            return f"{owner.__class__.__name__}.{name}"
        mod = (getattr(callback, "__module__", "") or "").split(".")[-1]
        return f"{mod}.{name}" if mod else str(name)
    except Exception:
        return "?"


# 이벤트 발행자(caller) 탐색 시 건너뛸 인프라 모듈 (래퍼 프레임)
_CALLER_SKIP = (
    "core.seam_observer",
    "core.web_session_context",
    "core.headless_event_bus",
    "core.context",
)


def _caller_label() -> str:
    """publish() 호출 스택을 거슬러 인프라 래퍼를 건너뛰고 실제 발행 모듈을 찾는다."""
    try:
        frame = sys._getframe(1)
        for _ in range(15):
            frame = frame.f_back
            if frame is None:
                break
            mod = frame.f_globals.get("__name__", "") or ""
            if mod and not mod.startswith(_CALLER_SKIP):
                return f"{mod.split('.')[-1]}.{frame.f_code.co_name}"
    except Exception:
        pass
    return "?"


class _SeamObserver:
    def __init__(self) -> None:
        self.enabled = os.environ.get("NAIA_SEAM_OBSERVE", "").strip().lower() in _TRUE
        self._dir: Optional[Path] = None
        self._seen_writes: set[str] = set()              # 이미 로그한 write-shape 키
        self._manifest: dict[str, dict] = {}             # "module|hook_point" -> entry
        self._violations: dict[str, dict] = {}           # "module|field|why" -> {count, first_ts, last_ts, ...}
        self._dirty = False
        # 이벤트 버스(AppContext-event) 그래프 = 모듈↔모듈 상하관계
        self._event_subs: dict[str, set] = {}            # event -> {subscriber_label}
        self._event_pubs: dict[str, dict] = {}           # event -> {publisher_label: count}
        self._seen_event_edges: set[str] = set()         # 이미 로그한 pub/sub 엣지 (novelty)
        # WS-command 버스 = Search/Quick Filter/Depth 등 프런트→백엔드 명령
        self._command_counts: dict[str, int] = {}        # command_type -> count
        # 카운트 신선도: 구조 변화는 즉시 flush, 그 외엔 최소 2초 간격으로 카운트 갱신
        self._last_flush: dict[str, float] = {"manifest": 0.0, "events": 0.0, "commands": 0.0}

    # ---- 경로 ----
    def _seam_dir(self) -> Path:
        if self._dir is None:
            base = (os.environ.get("NAIA_SEAM_DIR") or os.environ.get("NAIA_SEAM_JOURNAL_DIR") or "").strip()
            self._dir = Path(base) if base else Path(tempfile.gettempdir()) / "naia_seam"
            try:
                self._dir.mkdir(parents=True, exist_ok=True)
            except Exception:
                pass
        return self._dir

    def _flush_due(self, key: str) -> bool:
        """구조 변화가 없어도 최소 2초마다 카운트를 디스크에 반영(언더카운트 방지)."""
        try:
            return (time.time() - self._last_flush.get(key, 0.0)) >= 2.0
        except Exception:
            return False

    # ---- 스냅샷 (훅 실행 직전, read-only) ----
    def snapshot(self, context: Any) -> Optional[dict]:
        if not self.enabled:
            return None
        try:
            snap: dict = {}
            for field in _WATCH_FIELDS:
                value = getattr(context, field, None)
                snap[field] = list(value) if isinstance(value, list) else value
            return snap
        except Exception:
            return None

    # ---- 관측 (훅 실행 직후) ----
    def observe(
        self,
        pipeline: str,
        hook_point: str,
        module: str,
        before: Optional[dict],
        after: Any,
    ) -> None:
        if not self.enabled or before is None:
            return
        try:
            writes: list[str] = []
            violations: list[tuple[str, str]] = []
            for field in _WATCH_FIELDS:
                cur = getattr(after, field, None)
                cur_cmp = list(cur) if isinstance(cur, list) else cur
                if cur_cmp != before.get(field):
                    writes.append(field)
                    if field in _TAG_FIELDS:
                        ok, why = _tags_struct_ok(cur)
                        if not ok:
                            violations.append((field, why))
            if not writes and not violations:
                return

            self._update_manifest(pipeline, hook_point, module, writes)

            # novelty-gated: 처음 보는 write-shape 만 1줄
            wkey = f"{pipeline}|{hook_point}|{module}|{','.join(writes)}"
            if wkey not in self._seen_writes:
                self._seen_writes.add(wkey)
                self._append_log(f'WRITE {pipeline}/{hook_point} "{module}" -> {", ".join(writes) or "-"}')

            for field, why in violations:
                self._record_violation(hook_point, module, field, why)

            if self._dirty or self._flush_due("manifest"):
                self._flush_manifest()
        except Exception:
            pass  # 관측기는 절대 방해하지 않는다

    # ---- 내부 ----
    def _update_manifest(self, pipeline: str, hook_point: str, module: str, writes: list[str]) -> None:
        key = f"{module}|{hook_point}"
        entry = self._manifest.get(key)
        if entry is None:
            entry = {"pipeline": pipeline, "hook_point": hook_point, "module": module,
                     "writes": set(), "observations": 0}
            self._manifest[key] = entry
            self._dirty = True
        prev = len(entry["writes"])
        entry["writes"].update(writes)
        entry["observations"] += 1
        if len(entry["writes"]) != prev:
            self._dirty = True

    def _record_violation(self, hook_point: str, module: str, field: str, why: str) -> None:
        sig = f"{module}|{field}|{why}"
        now = round(time.time(), 3)
        v = self._violations.get(sig)
        if v is None:
            v = {"module": module, "hook_point": hook_point, "field": field, "why": why,
                 "count": 0, "first_ts": now, "last_ts": now}
            self._violations[sig] = v
        v["count"] += 1
        v["last_ts"] = now
        self._dirty = True
        if _is_log_milestone(v["count"]):
            self._append_log(f'VIOLATION "{module}" {field}: {why} (x{v["count"]})')

    def _flush_manifest(self) -> None:
        try:
            hooks = [
                {"module": e["module"], "hook_point": e["hook_point"], "pipeline": e["pipeline"],
                 "writes": sorted(e["writes"]), "observations": e["observations"]}
                for e in self._manifest.values()
            ]
            hooks.sort(key=lambda h: (h["hook_point"], h["module"]))
            violations = sorted(self._violations.values(), key=lambda v: -v["count"])
            doc = {"bus": "prompt_pipeline", "updated": round(time.time(), 3),
                   "hooks": hooks, "violations": violations}
            path = self._seam_dir() / "seam_manifest.json"
            tmp = path.with_suffix(".json.tmp")
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump(doc, handle, ensure_ascii=False, indent=2)
            os.replace(tmp, path)  # 원자적 덮어쓰기 (append 아님 → 수렴·소형)
            self._last_flush["manifest"] = time.time()
            self._dirty = False
        except Exception:
            pass

    def _append_log(self, message: str) -> None:
        try:
            path = self._seam_dir() / "seam.log"
            try:
                if path.exists() and path.stat().st_size > _LOG_MAX_BYTES:
                    return  # 방어적 상한 (novelty-gated라 정상적으론 도달 안 함)
            except Exception:
                pass
            stamp = time.strftime("%Y-%m-%dT%H:%M:%S")
            with open(path, "a", encoding="utf-8") as handle:
                handle.write(f"{stamp} {message}\n")
        except Exception:
            pass


    # ---- 이벤트 버스 그래프 (모듈↔모듈 상하관계 추적) ----
    def observe_subscribe(self, event_name: str, callback: Any) -> None:
        """WebSessionContext.subscribe 에서 호출. event→구독자 엣지 기록."""
        if not self.enabled:
            return
        try:
            label = _callback_label(callback)
            subs = self._event_subs.setdefault(str(event_name), set())
            if label not in subs:
                subs.add(label)
                edge = f"sub|{event_name}|{label}"
                if edge not in self._seen_event_edges:
                    self._seen_event_edges.add(edge)
                    self._append_log(f"SUBSCRIBE {event_name} <- {label}")
                self._flush_events()
        except Exception:
            pass

    def observe_publish(self, event_name: str) -> None:
        """WebSessionContext.publish 에서 호출. 발행자→event 엣지 + 횟수 기록."""
        if not self.enabled:
            return
        try:
            publisher = _caller_label()
            pubs = self._event_pubs.setdefault(str(event_name), {})
            new_edge = publisher not in pubs
            pubs[publisher] = pubs.get(publisher, 0) + 1
            if new_edge:
                edge = f"pub|{event_name}|{publisher}"
                if edge not in self._seen_event_edges:
                    self._seen_event_edges.add(edge)
                    self._append_log(f"PUBLISH {publisher} -> {event_name}")
            if new_edge or self._flush_due("events"):
                self._flush_events()
        except Exception:
            pass

    # ---- WS-command 버스 (Search / Quick Filter / Depth 등) ----
    def observe_command(self, command_type: str) -> None:
        """websocket_session 디스패치에서 호출. command_type→횟수 기록."""
        if not self.enabled:
            return
        try:
            ct = str(command_type or "").strip()
            if not ct:
                return
            new = ct not in self._command_counts
            self._command_counts[ct] = self._command_counts.get(ct, 0) + 1
            if new:
                self._append_log(f"WS-COMMAND {ct}")
            if new or self._flush_due("commands"):
                self._flush_commands()
        except Exception:
            pass

    def _flush_commands(self) -> None:
        try:
            items = sorted(self._command_counts.items(), key=lambda x: -x[1])
            doc = {"bus": "ws_command", "updated": round(time.time(), 3),
                   "commands": [{"type": k, "count": v} for k, v in items]}
            path = self._seam_dir() / "seam_commands.json"
            tmp = path.with_suffix(".json.tmp")
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump(doc, handle, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
            self._last_flush["commands"] = time.time()
        except Exception:
            pass

    def _flush_events(self) -> None:
        try:
            names = sorted(set(self._event_subs) | set(self._event_pubs))
            events = {}
            for name in names:
                events[name] = {
                    "publishers": [
                        {"label": k, "count": v}
                        for k, v in sorted(self._event_pubs.get(name, {}).items(), key=lambda x: -x[1])
                    ],
                    "subscribers": sorted(self._event_subs.get(name, set())),
                }
            doc = {"bus": "appcontext_event", "updated": round(time.time(), 3), "events": events}
            path = self._seam_dir() / "seam_events.json"
            tmp = path.with_suffix(".json.tmp")
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump(doc, handle, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
            self._last_flush["events"] = time.time()
        except Exception:
            pass


# 모듈 전역 싱글턴 — 호출부는 `from core.seam_observer import seam_observer`
seam_observer = _SeamObserver()
