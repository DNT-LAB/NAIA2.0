"""Headless Storyteller cycle controller.

Runs a single *cycle* of N freeze-locked generations on top of the shared Auto
Generate loop, then stops. It is a run-policy controller (mirrors
``HeadlessAutomationService``): Start arms Auto Generate and the Event Stream
freeze/allocator runtime; the generation runner counts each completed image and
this controller finishes the run — disarming Auto Gen and clearing the freeze
snapshot — when the page count is reached.

The freeze itself (same character / artist / style across every page, varying
composition) lives in ``core/event_tree/runtime.py`` (EventStreamRuntime); this
controller only owns the *cycle* (how many pages, when to stop, cleanup).
"""

from __future__ import annotations

import json
import random
import uuid
from pathlib import Path
from typing import Any


STORYTELLER_SOURCE = "Storyteller"
_MAX_STORYTELLER_PAGES = 100
_STORYTELLER_SETTINGS_FILE = "StorytellerModule.json"

# 1.5 EV.A parity: per-step rating choices. "all" follows the active rating toggles
# (LegacyStoryNodeSpec.ratings=None falls back to active_ratings at allocation).
_STEP_RATING_SETS: dict[str, set[str] | None] = {
    "all": None,
    "g": {"g"},
    "s": {"s"},
    "q": {"q"},
    "e": {"e"},
    "eq": {"e", "q"},
    "sg": {"s", "g"},
}


def _parse_resolution_text(value: Any) -> tuple[int | None, int | None]:
    try:
        parts = str(value or "").lower().replace("×", "x").split("x")
        if len(parts) == 2:
            width = int(parts[0].strip())
            height = int(parts[1].strip())
            if width > 0 and height > 0:
                return width, height
    except (TypeError, ValueError):
        pass
    return None, None


class HeadlessStorytellerService:
    def __init__(self, context: Any):
        self.context = context
        self._steps_cache: list[dict[str, str]] | None = None
        # carry(의상/배경 유지) vs PE 제거 옵션 충돌 경고는 종류별 1회만(사용자 요청).
        self._carry_conflict_warned: set[str] = set()

    # ------------------------------------------------------------------ state
    def state(self) -> dict[str, Any]:
        runtime = self._runtime()
        running = bool(runtime and runtime.get("is_running"))
        event_stream = getattr(self.context, "event_stream_runtime", None)
        target = int(runtime.get("target_count") or 0) if runtime else 0
        completed = int(runtime.get("completed_count") or 0) if runtime else 0
        return self.context._module_state_payload("storyteller", {
            "available": True,
            "runtime": "web",
            "is_running": running,
            "run_id": str(runtime.get("run_id") or "") if runtime else "",
            "target_count": target,
            "completed_count": completed,
            "remaining_count": max(0, target - completed) if running else 0,
            "event_stream_active": bool(event_stream and getattr(event_stream, "is_active", False)),
            "status": self._status_text(runtime),
            "steps": self.load_steps(),
        })

    def set_param(self, key: str, value: Any) -> dict[str, Any] | None:
        if key == "run_cycle":
            return self.start_cycle(value)
        if key == "manual_arm":
            return self.arm_manual(value)
        if key == "manual_disarm":
            return self.disarm_manual()
        if key == "steps":
            steps = self._parse_steps_value(value)
            self.save_steps(steps)
            state = self.state()
            conflicts = self._carry_conflict_messages(steps) + self._use_vibe_mode_messages(steps)
            if conflicts:
                state["_headless_extra_messages"] = conflicts
            return state
        if key == "validate":
            return self.validate_steps(value)
        if key == "stop":
            return self.stop()
        return None

    def _build_step_nodes(self, steps: list[dict[str, Any]], count: int):
        from core.event_tree import LegacyStoryNodeSpec

        if steps:
            return [
                LegacyStoryNodeSpec(
                    node_id=f"story.page.{index + 1}",
                    name=f"Step {index + 1}",
                    ratings=_STEP_RATING_SETS.get(str(step.get("rating") or "all")),
                    include_tags=tuple(sorted(self._split_step_tags(step.get("include")))),
                    exclude_tags=tuple(sorted(self._split_step_tags(step.get("exclude")))),
                    # carry(의상/배경 유지)·Use Vibe는 EventStreamRuntime이 노드 policy로
                    # 직접 적용한다 — 수동 진행/자동 사이클 공통. 마지막 스텝의 use_vibe는
                    # 적용할 다음 스텝이 없으므로 강제 OFF(무의미한 캡처 차단, FE disable과
                    # 이중 방어 — 사용자 요청).
                    axis_carry_policy={
                        "keep_clothes": bool(step.get("keep_clothes")),
                        "keep_background": bool(step.get("keep_background")),
                        "use_vibe": bool(step.get("use_vibe")) and index < len(steps) - 1,
                    },
                )
                for index, step in enumerate(steps)
            ]
        return [
            LegacyStoryNodeSpec(node_id=f"story.page.{index + 1}", name=f"Page {index + 1}")
            for index in range(count)
        ]

    def _carry_conflict_messages(self, steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """의상/배경 유지가 PE의 해당 '제거' 옵션과 함께 켜져 있으면 노란 토스트로 1회
        경고(사용자 요청). 충돌 의미: 라운드 첫 페이지는 carry 없이 생성되는데 제거
        옵션이 그 페이지의 의상/배경 태그를 지워 다음 스텝에 유지할 재료가 없어진다."""
        if not steps:
            return []
        try:
            from core.prompt_engineering_settings import get_prompt_engineering_store

            settings = get_prompt_engineering_store(self.context).collect_settings()
            preprocessing = dict(settings.get("preprocessing_options") or {})
        except Exception:
            return []
        messages: list[dict[str, Any]] = []
        pairs = (
            ("keep_clothes", "remove_clothes", "의상"),
            ("keep_background", "remove_location_and_background_color", "배경"),
        )
        for keep_key, remove_key, label in pairs:
            if keep_key in self._carry_conflict_warned:
                continue
            if not preprocessing.get(remove_key):
                continue
            if not any(step.get(keep_key) for step in steps):
                continue
            self._carry_conflict_warned.add(keep_key)
            messages.append(self.context._toast(
                f"{label} 유지 ↔ PE '{label} 제거' 충돌: 라운드 첫 페이지의 {label} 태그가 "
                f"제거돼 다음 스텝에 유지할 내용이 없습니다. PE의 {label} 제거를 꺼주세요.",
                level="warning",
            ))
        return messages

    def _use_vibe_mode_messages(self, steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Use Vibe 스텝이 있는데 인코딩 불가 런타임(비NAI 모드/NAID3)이면 1회 경고 —
        라이브에선 조용히 아무 일도 안 일어나므로 명시한다(토큰 유무는 실행 시점 검증).
        마지막 스텝의 use_vibe는 어차피 강제 OFF라 경고 대상에서 제외한다."""
        if not steps or not any(step.get("use_vibe") for step in steps[:-1]):
            return []
        if "use_vibe_mode" in self._carry_conflict_warned:
            return []
        try:
            mode = str(self.context.get_api_mode() or "").upper()
            naid3 = bool(self.context._is_naid3_model())
        except Exception:
            return []
        if mode == "NAI" and not naid3:
            return []
        reason = (
            "NAID3 모델은 Vibe 인코딩을 지원하지 않습니다"
            if mode == "NAI"
            else "NAI 모드에서만 동작합니다"
        )
        self._carry_conflict_warned.add("use_vibe_mode")
        return [self.context._toast(
            f"스텝의 'Vibe 사용(2 Anlas)'은 {reason} — 이번 실행에서는 무시됩니다.",
            level="warning",
        )]

    # -------------------------------------------------- 1.5식 수동 진행 모드
    def arm_manual(self, value: Any) -> dict[str, Any]:
        """작성한 스텝 시퀀스를 allocator에 무장만 한다(자동 생성 없음). 이후의 모든
        랜덤(수동 포함)이 스텝을 순서대로(순환) 전진시킨다 — 1.5 EV.A처럼 사용자가
        마음에 드는 이미지가 나올 때까지 직접 라운드를 반복한다."""
        if self.is_running():
            return self._error_state("자동 사이클 실행 중에는 수동 진행을 시작할 수 없습니다.")
        if self._foreign_event_stream_active():
            return self._error_state(
                "다른 Event Stream(예: Sequence)이 무장돼 있습니다. 먼저 정지한 뒤 시작하세요."
            )
        steps = self._parse_steps_value(value)
        if steps:
            self.save_steps(steps)
        else:
            steps = self.load_steps()
        nodes = self._build_step_nodes(steps, max(1, len(steps)))
        event_stream = self.context._create_event_stream_runtime()
        event_stream.start_linear(nodes, run_id=f"storyteller-manual-{uuid.uuid4().hex[:8]}")
        state = self.state()
        state["_headless_extra_messages"] = [
            self.context._toast(
                f"수동 진행 시작: {len(nodes)}스텝 — Random 버튼으로 한 스텝씩 진행합니다.",
                level="info",
            ),
            self.context._event_stream_module_state(),
            *self._carry_conflict_messages(steps),
            *self._use_vibe_mode_messages(steps),
        ]
        return state

    def disarm_manual(self) -> dict[str, Any]:
        if self.is_running():
            return self._error_state("자동 사이클이 실행 중입니다. 정지 버튼을 사용하세요.")
        event_stream = getattr(self.context, "event_stream_runtime", None)
        if event_stream is not None:
            try:
                event_stream.stop()
            except Exception:
                pass
        state = self.state()
        state["_headless_extra_messages"] = [
            self.context._toast("수동 진행을 종료했습니다.", level="info"),
            self.context._event_stream_module_state(),
        ]
        return state

    # ------------------------------------------------------------------ start
    def start_cycle(self, value: Any) -> dict[str, Any]:
        count, overrides, ratings, steps = self._parse_cycle_request(value)
        if steps:
            # The authored step sequence IS the cycle: one page per step.
            self.save_steps(steps)
            count = len(steps)
        count = max(1, min(_MAX_STORYTELLER_PAGES, count))

        # Mutual exclusion with Automation — both drive the single Auto Generate
        # loop, so only one controller may own it at a time.
        if self.context._automation_service().is_running():
            return self._error_state(
                "Automation is running. Stop it before starting a Storyteller cycle."
            )
        if self.is_running():
            return self._error_state("A Storyteller cycle is already running.")
        if self._foreign_event_stream_active():
            return self._error_state(
                "다른 Event Stream(예: Sequence)이 무장돼 있습니다. 먼저 정지한 뒤 시작하세요."
            )
        # Don't start on top of an in-flight queue/generation.
        if getattr(self.context, "is_generating", False):
            return self._error_state("A generation is in progress. Wait for it to finish.")
        queue = getattr(self.context, "generation_queue_manager", None)
        if queue is not None and (queue.is_paused() or not queue.is_empty()):
            return self._error_state(
                "The generation queue is busy. Wait for it to drain, then start the cycle."
            )
        credential_error = self._credential_error()
        if credential_error:
            return self._error_state(credential_error)

        run_id = f"storyteller-{uuid.uuid4().hex}"

        # One node per authored step (1.5 EV.A parity: each step = a scene condition with
        # its own include/exclude/rating). Without steps, fall back to N identical Current
        # Search pages. Either way, the freeze snapshot is captured on the first generation
        # and replayed for the rest, so character/artist/style stay identical while the
        # per-step source row provides the scene.
        nodes = self._build_step_nodes(steps, count)
        event_stream = self.context._create_event_stream_runtime()
        event_stream.start_linear(nodes, run_id=run_id)

        self.context.storyteller_runtime_state = {
            "run_id": run_id,
            "is_running": True,
            "target_count": count,
            "completed_count": 0,
            "finish_reason": "",
            # 런 시작 시점의 스텝 스냅샷(carry/해상도 계획용) — 실행 중 편집과 격리.
            "steps": steps,
            # 'default' 스텝의 해상도 베이스: 이전 스텝이 박은 해상도가 다음 페이지로
            # 새지 않도록 시작 시점의 UI 값으로 복원하는 데 쓴다.
            "base_resolution": {
                "width": overrides.get("width"),
                "height": overrides.get("height"),
                "resolution": overrides.get("resolution"),
            },
        }
        options_message = self._engage_auto_generate(True)

        # Generate page 1 here so arming + the first page are ATOMIC: there is no window
        # where the freeze/Auto Gen is on but nothing is generating. The random path runs
        # the Event Stream allocation + captures the freeze snapshot; on any failure we
        # roll the whole cycle back (no stuck armed state).
        from core.headless_random_prompt_service import HeadlessRandomPromptService

        page_overrides = dict(overrides)
        page_overrides["auto_generate"] = True
        # 내부 페이지 생성 마커(수동 랜덤 차단 가드 통과용).
        page_overrides["_storyteller_page"] = True
        # A story MUST re-roll a fresh prompt (new composition) every page — the freeze
        # keeps character/style identical, not the whole prompt. So force prompt_fixed OFF
        # even if the user's live params have it on (else pages 2..N reuse page 1 and skip
        # the Event Stream allocation entirely).
        page_overrides["prompt_fixed"] = False
        try:
            result = HeadlessRandomPromptService(self.context).generate(
                active_ratings=ratings,
                overrides=page_overrides,
                random_request_id=f"{run_id}:p1",
            )
        except Exception as exc:  # pragma: no cover - defensive
            self.finish(run_id, reason="error", error=str(exc))
            return self._error_state(f"Storyteller failed to start: {exc}")
        if not result.success:
            self.finish(run_id, reason="error", error=result.error or "")
            return self._error_state(
                result.error or "Storyteller could not generate the first page."
            )

        # Page-1 generate command, stamped with the run id so the runner counts it (and
        # only it / its stamped continuations) as a page. Carries the user's live params.
        gen_overrides = dict(page_overrides)
        gen_overrides["event_stream_run_id"] = run_id
        gen_overrides["_remote_queue_source"] = STORYTELLER_SOURCE
        gen_overrides["_remote_queue_label"] = STORYTELLER_SOURCE
        gen_overrides["input"] = result.prompt
        gen_overrides["_raw_input"] = result.prompt
        if result.detected_resolution:
            width, height = result.detected_resolution
            gen_overrides["width"] = width
            gen_overrides["height"] = height
            gen_overrides["resolution"] = f"{width} x {height}"
        # 스텝별 해상도(페이지 1): 지정 시 Auto Res/UI 값보다 우선한다.
        page1_plan = self.page_plan(run_id)
        if page1_plan and page1_plan.get("width") and page1_plan.get("height"):
            gen_overrides["width"] = page1_plan["width"]
            gen_overrides["height"] = page1_plan["height"]
            gen_overrides["resolution"] = f"{page1_plan['width']} x {page1_plan['height']}"
        # 페이지 1 해상도 기록('previous' 해상도용). carry 추출은 런타임 담당.
        self.record_page_outcome(
            run_id,
            width=gen_overrides.get("width"),
            height=gen_overrides.get("height"),
        )
        command = {
            "type": "generate",
            "prompt": result.prompt,
            "negative_prompt": str(self.context.negative_prompt_text or ""),
            "overrides": gen_overrides,
        }

        messages: list[dict[str, Any]] = []
        if options_message:
            messages.append(options_message)
        prompt_payload = result.websocket_payload()
        prompt_payload["source"] = "storyteller"
        messages.append(prompt_payload)
        messages.extend(result.extra_messages or [])
        messages.append(self.context._toast(
            f"Storyteller cycle: {count} page(s).",
            level="info",
        ))
        messages.extend(self._carry_conflict_messages(steps))
        messages.extend(self._use_vibe_mode_messages(steps))
        state = self.state()
        state["_headless_extra_messages"] = messages
        state["_headless_generation_commands"] = [command]
        return state

    def _parse_cycle_request(
        self, value: Any
    ) -> tuple[int, dict[str, Any], set[str] | None, list[dict[str, str]]]:
        """Accept either a bare page count, or a JSON object/string
        ``{count, steps, overrides, ratings}`` carrying the authored step sequence plus
        the live UI params for page 1."""
        data: Any = value
        if isinstance(value, str):
            text = value.strip()
            if text.startswith("{"):
                try:
                    data = json.loads(text)
                except (ValueError, TypeError):
                    data = {}
            else:
                try:
                    return (max(1, int(text)), {}, None, [])
                except (TypeError, ValueError):
                    return (1, {}, None, [])
        if isinstance(data, dict):
            try:
                count = max(1, int(data.get("count", 1)))
            except (TypeError, ValueError):
                count = 1
            overrides = data.get("overrides")
            overrides = dict(overrides) if isinstance(overrides, dict) else {}
            ratings = self._normalize_ratings(data.get("ratings"))
            steps = self._normalize_steps(data.get("steps"))
            return (count, overrides, ratings, steps)
        try:
            return (max(1, int(value)), {}, None, [])
        except (TypeError, ValueError):
            return (1, {}, None, [])

    # ------------------------------------------------------------- step cards
    def _normalize_steps(self, raw: Any) -> list[dict[str, Any]]:
        steps: list[dict[str, Any]] = []
        if isinstance(raw, list):
            for item in raw:
                if not isinstance(item, dict):
                    continue
                rating = str(item.get("rating") or "all").strip().lower()
                if rating not in _STEP_RATING_SETS:
                    rating = "all"
                steps.append({
                    "include": str(item.get("include") or "").strip(),
                    "exclude": str(item.get("exclude") or "").strip(),
                    "rating": rating,
                    # 1.5 carry parity: 이 스텝의 의상/배경을 '다음' 스텝에 유지할지.
                    "keep_clothes": bool(item.get("keep_clothes", False)),
                    "keep_background": bool(item.get("keep_background", False)),
                    # Use Vibe(2 Anlas): 이 스텝의 생성 결과를 IE 0.6으로 인코딩해 이후
                    # 스텝에 단일 vibe(RS 0.9)로 적용. 스트림 동안만 유지, Storage 미저장.
                    "use_vibe": bool(item.get("use_vibe", False)),
                    # 스텝별 해상도: default | random | previous | "W x H"
                    "resolution": self._normalize_step_resolution(item.get("resolution")),
                })
        return steps[:_MAX_STORYTELLER_PAGES]

    @staticmethod
    def _normalize_step_resolution(value: Any) -> str:
        text = str(value or "default").strip().lower()
        if text in {"default", "random", "previous"}:
            return text
        width, height = _parse_resolution_text(text)
        if width and height:
            return f"{width} x {height}"
        return "default"

    def _parse_steps_value(self, value: Any) -> list[dict[str, str]]:
        data: Any = value
        if isinstance(value, str):
            try:
                data = json.loads(value)
            except (ValueError, TypeError):
                data = []
        if isinstance(data, dict):
            data = data.get("steps")
        return self._normalize_steps(data)

    def load_steps(self) -> list[dict[str, str]]:
        if self._steps_cache is not None:
            return [dict(step) for step in self._steps_cache]
        steps: list[dict[str, str]] = []
        try:
            path = self.context._existing_save_path(_STORYTELLER_SETTINGS_FILE)
            if path and Path(path).exists():
                data = json.loads(Path(path).read_text(encoding="utf-8"))
                steps = self._normalize_steps(data.get("steps") if isinstance(data, dict) else None)
        except Exception:
            steps = []
        self._steps_cache = steps
        return [dict(step) for step in steps]

    def save_steps(self, steps: list[dict[str, str]]) -> list[dict[str, str]]:
        normalized = self._normalize_steps(steps)
        try:
            path = Path(self.context._save_path(_STORYTELLER_SETTINGS_FILE))
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps({"steps": normalized}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass
        self._steps_cache = normalized
        return [dict(step) for step in normalized]

    def validate_steps(self, value: Any) -> dict[str, Any]:
        """1.5 EV.A의 스텝 검증: 각 스텝 조건이 현재 검색에서 몇 건과 매칭되는지 센다
        (비파괴). 0건이면 그 스텝은 실행 시 실패하므로 UI가 Invalid로 표시한다.
        ``{step, index}``면 해당 스텝 하나만 검증하고 ``validation_index``를 에코한다
        (1.5처럼 카드별 '프롬프트 검증' 버튼)."""
        data: Any = value
        if isinstance(value, str):
            try:
                data = json.loads(value)
            except (ValueError, TypeError):
                data = {}
        single_index: int | None = None
        if isinstance(data, dict) and isinstance(data.get("step"), dict):
            steps = self._normalize_steps([data.get("step")])
            try:
                single_index = int(data.get("index"))
            except (TypeError, ValueError):
                single_index = None
        else:
            steps = self._parse_steps_value(data)
        if not steps:
            steps = self.load_steps()
        search_results = getattr(self.context, "search_results", None)
        active_ratings = None
        getter = getattr(self.context, "get_active_ratings", None)
        if callable(getter):
            try:
                active_ratings = getter()
            except Exception:
                active_ratings = None
        results: list[dict[str, Any]] = []
        for step in steps:
            count = 0
            if search_results is not None:
                rating_set = _STEP_RATING_SETS.get(str(step.get("rating") or "all")) or active_ratings
                try:
                    counter = getattr(search_results, "count_rows_matching_tags", None)
                    if callable(counter):
                        # 벡터화 카운트 — 수십만 행에서도 초 단위(행별 apply는 분 단위 + GIL).
                        count = int(counter(
                            rating_set,
                            include_tags=sorted(self._split_step_tags(step.get("include"))),
                            exclude_tags=sorted(self._split_step_tags(step.get("exclude"))),
                        ))
                    elif hasattr(search_results, "count_rows_matching"):
                        count = int(search_results.count_rows_matching(
                            rating_set, self._step_predicate(step)
                        ))
                except Exception:
                    count = 0
            results.append({"count": count, "ok": count > 0})
        state = self.state()
        state["validation"] = results
        if single_index is not None:
            state["validation_index"] = single_index
        return state

    def _step_predicate(self, step: dict[str, str]):
        from core.event_tree.runtime import EventStreamRuntime, _clean_tags

        include = self._split_step_tags(step.get("include"))
        exclude = self._split_step_tags(step.get("exclude"))
        if include or exclude:
            return lambda row: EventStreamRuntime._matches_node_tags(row, include, exclude)
        return lambda row: (
            bool(_clean_tags(row.get("general", ""))) if "general" in row.index else True
        )

    @staticmethod
    def _split_step_tags(text: Any) -> set[str]:
        from core.wildcard_processor import split_tags_smart

        return {tag.strip() for tag in split_tags_smart(str(text or "")) if tag and tag.strip()}

    # ----------------------------------------------------- carry / resolution
    def page_plan(self, run_id: str) -> dict[str, Any] | None:
        """다음 페이지(= steps[completed_count])의 carry/해상도 계획.

        1.5 계약: 스텝 N의 '의상/배경 유지' 체크는 N의 의상/배경을 N+1로 가져간다 —
        그래서 carry는 '이전' 스텝의 플래그가 결정하고, 주입 재료는 직전 페이지의 최종
        프롬프트에서 추출해 둔 태그(record_page_outcome)다."""
        runtime = self._runtime_for_run(run_id)
        if runtime is None:
            return None
        steps = runtime.get("steps") or []
        index = int(runtime.get("completed_count") or 0)
        if not steps or index >= len(steps):
            return None
        plan: dict[str, Any] = {"step_index": index}
        plan["base_resolution"] = dict(runtime.get("base_resolution") or {})
        width, height = self._resolve_step_resolution(steps[index].get("resolution"), runtime)
        if width and height:
            plan["width"] = width
            plan["height"] = height
        # NOTE: carry(의상/배경 유지)는 더 이상 여기서 계획하지 않는다 —
        # EventStreamRuntime이 노드 axis_carry_policy로 모든 스트림 생성(수동 포함)에
        # 직접 적용한다. 이 plan은 자동 사이클의 스텝별 해상도 전용.
        return plan

    def record_page_outcome(
        self,
        run_id: str,
        *,
        prompt: Any = None,
        width: Any = None,
        height: Any = None,
    ) -> None:
        """페이지 생성 직후 호출: 'previous' 해상도용으로 이번 페이지 해상도를 기록한다.
        (carry 태그 추출은 EventStreamRuntime.record_generated_context가 단일 담당.)"""
        runtime = self._runtime_for_run(run_id)
        if runtime is None:
            return
        try:
            parsed_width = int(width)
            parsed_height = int(height)
            if parsed_width > 0 and parsed_height > 0:
                runtime["last_width"] = parsed_width
                runtime["last_height"] = parsed_height
        except (TypeError, ValueError):
            pass

    def _resolve_step_resolution(self, value: Any, runtime: dict[str, Any]) -> tuple[int | None, int | None]:
        resolution = str(value or "default")
        if resolution == "default":
            return (None, None)
        if resolution == "random":
            # 해상도 매니저가 저장한 현재 모드의 사용자 목록에서 추첨 — 메인
            # 파라미터의 Rnd Res와 동일한 모집단(폴백=표준 1MP).
            try:
                labels = list(self.context.resolution_options_for_mode())
            except Exception:
                labels = []
            if not labels:
                from core.resolution_utils import STANDARD_1MP_RESOLUTION_LABELS

                labels = list(STANDARD_1MP_RESOLUTION_LABELS)
            if not labels:
                return (None, None)
            return _parse_resolution_text(random.choice(labels))
        if resolution == "previous":
            try:
                width = int(runtime.get("last_width"))
                height = int(runtime.get("last_height"))
            except (TypeError, ValueError):
                return (None, None)
            return (width, height) if width > 0 and height > 0 else (None, None)
        return _parse_resolution_text(resolution)

    # carry 태그 추출/정규화는 EventStreamRuntime(_extract_carry_tags/_normalize_carry_tag)
    # 으로 이전됐다 — 수동 진행/자동 사이클 공통 적용을 위해.

    @staticmethod
    def _normalize_ratings(value: Any) -> set[str] | None:
        if isinstance(value, str):
            picked = {item for item in ("g", "s", "q", "e") if item in set(value)}
            return picked or None
        if isinstance(value, (list, tuple, set)):
            picked = {str(item).strip().lower() for item in value}
            picked = {item for item in ("g", "s", "q", "e") if item in picked}
            return picked or None
        return None

    # ------------------------------------------------------- runner callbacks
    def record_generation_completed(self, run_id: str) -> dict[str, Any]:
        runtime = self._runtime_for_run(run_id)
        if runtime is None:
            return {"continue": False, "messages": []}
        runtime["completed_count"] = int(runtime.get("completed_count") or 0) + 1
        if runtime["completed_count"] >= int(runtime.get("target_count") or 0):
            return self.finish(run_id, reason="complete")
        return {"continue": True, "messages": []}

    def finish(self, run_id: str, *, reason: str = "complete", error: str = "") -> dict[str, Any]:
        runtime = self._runtime()
        if runtime and str(runtime.get("run_id") or "") == str(run_id or ""):
            runtime["is_running"] = False
            runtime["finish_reason"] = reason
        # Deterministic cleanup: stop the freeze/allocator runtime (clears the snapshot
        # and deactivates Event Stream) and disarm Auto Generate.
        event_stream = getattr(self.context, "event_stream_runtime", None)
        if event_stream is not None:
            try:
                event_stream.stop()
            except Exception:
                pass
        messages: list[dict[str, Any]] = []
        options_message = self._engage_auto_generate(False)
        if options_message:
            messages.append(options_message)
        if error:
            messages.append(self.context._toast(f"Storyteller stopped: {error}", level="error"))
        elif reason == "complete":
            messages.append(self.context._toast("Storyteller cycle complete.", level="success"))
        return {"continue": False, "messages": messages}

    def fail(self, run_id: str, message: str) -> dict[str, Any]:
        return self.finish(run_id, reason="error", error=message)

    def stop(self) -> dict[str, Any]:
        runtime = self._runtime()
        if not runtime or not runtime.get("is_running"):
            return self.state()
        policy = self.finish(str(runtime.get("run_id") or ""), reason="stopped")
        state = self.state()
        state["_headless_extra_messages"] = policy.get("messages", [])
        return state

    # ------------------------------------------------------------- inspectors
    def is_running(self, run_id: str | None = None) -> bool:
        runtime = self._runtime()
        if not runtime or not runtime.get("is_running"):
            return False
        return not run_id or str(runtime.get("run_id") or "") == str(run_id)

    def active_run_id(self) -> str:
        runtime = self._runtime()
        if not runtime or not runtime.get("is_running"):
            return ""
        return str(runtime.get("run_id") or "")

    def _foreign_event_stream_active(self) -> bool:
        """공유 EventStreamRuntime 이 Storyteller 가 아닌 런(예: Sequence freeze)으로 무장돼
        있는지. start_linear 은 무조건 clobber 하므로, 외부 런을 짓밟지 않도록 가드한다.
        자기(Storyteller auto/manual) 런은 run_id 가 'storyteller' 로 시작해 재무장이 허용된다
        — 기존 Storyteller↔수동진행 동작 보존."""
        es = getattr(self.context, "event_stream_runtime", None)
        if es is None or not getattr(es, "is_active", False):
            return False
        return not str(getattr(es, "run_id", "") or "").startswith("storyteller")

    # ----------------------------------------------------------------- helpers
    def _runtime(self) -> dict[str, Any] | None:
        runtime = getattr(self.context, "storyteller_runtime_state", None)
        return runtime if isinstance(runtime, dict) else None

    def _runtime_for_run(self, run_id: str) -> dict[str, Any] | None:
        runtime = self._runtime()
        if not runtime or not runtime.get("is_running"):
            return None
        if str(runtime.get("run_id") or "") != str(run_id or ""):
            return None
        return runtime

    def _engage_auto_generate(self, enabled: bool) -> dict[str, Any] | None:
        try:
            current = bool(self.context.get_options().get("auto_generate", False))
            if current == bool(enabled):
                return None
            self.context.set_option("auto_generate", bool(enabled))
            return {"type": "options", **self.context.get_options()}
        except Exception:
            return None

    def _credential_error(self) -> str:
        from core.headless_generation_service import TOKEN_KEYS

        api_mode = str(self.context.get_api_mode() or "NAI").upper()
        token_key = TOKEN_KEYS.get(api_mode, "nai_token")
        credential = str(self.context.secure_token_manager.get_token(token_key) or "")
        if credential:
            return ""
        return f"{api_mode} credential is not configured."

    def _error_state(self, message: str) -> dict[str, Any]:
        state = self.state()
        state["_headless_extra_messages"] = [self.context._toast(message, level="error")]
        return state

    def _status_text(self, runtime: dict[str, Any] | None) -> str:
        if runtime and runtime.get("is_running"):
            return (
                f"Running ({int(runtime.get('completed_count') or 0)}"
                f"/{int(runtime.get('target_count') or 0)})"
            )
        reason = str(runtime.get("finish_reason") or "") if runtime else ""
        if reason == "complete":
            return "Complete"
        if reason == "stopped":
            return "Stopped"
        if reason == "error":
            return "Stopped after error"
        return ""
