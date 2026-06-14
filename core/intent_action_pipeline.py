# -*- coding: utf-8 -*-
"""Generation Info Instant Commandline 기판.

CoT 미지원 소형 모델을 전제로 한다. 모델에게 긴 자기반성/기억추적을 맡기지 않고,
코드가 단방향 finite pipeline을 소유한다.

v1 계약:
  * 홈은 Generation Info이지만 전역 커맨드 진입점을 전제로 한다.
  * 현재 생성물 프롬프트/태그/메타를 grounding context로 받는다.
  * Journal은 감사 로그일 뿐, 같은 run 안에서 다시 읽어 결정을 재귀 보정하지 않는다.
  * Tool 선택과 실행은 코드가 한다. LLM은 IntentFrame 제안기에 머문다.
  * 같은 action/query/context 조합은 한 run 안에서 한 번만 허용한다.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Callable, Iterable
import hashlib
import json
import re
import tempfile
import uuid

from core.semantic_tag_discovery import (
    clean_tag_discovery_subject,
    discover_prompt_tags,
    discover_semantic_tags,
)


@dataclass(frozen=True)
class GenerationInfoContext:
    """현재 Generation Info 표면에서 얻은 grounding context."""

    prompt: str = ""
    tags: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_value(cls, value: Any = None) -> "GenerationInfoContext":
        if isinstance(value, cls):
            return value
        if not isinstance(value, dict):
            return cls()
        prompt = _coerce_text(value.get("prompt") or value.get("current_prompt") or value.get("final_prompt"))
        tags_raw = value.get("tags") or value.get("current_tags") or ()
        tags: tuple[str, ...] = ()
        if isinstance(tags_raw, (list, tuple)):
            tags = tuple(
                tag
                for tag in (_coerce_text(item, limit=200).strip() for item in tags_raw)
                if tag
            )
        metadata = value.get("metadata") if isinstance(value.get("metadata"), dict) else {}
        return cls(prompt=prompt, tags=tags, metadata=dict(metadata))

    def summary(self) -> dict[str, Any]:
        return {
            "prompt": self.prompt,
            "tags": list(self.tags),
            "metadata": self.metadata,
        }

    def key(self) -> str:
        return json.dumps(self.summary(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


SearchFn = Callable[[str, int, GenerationInfoContext], list[dict[str, Any]]]
TranslatorFn = Callable[[str], str | None]

INTENT_PROMPT_RECOMMENDATION = "prompt_recommendation"
INTENT_TAG_DISCOVERY = "tag_discovery"

ACTION_PROMPT_SEARCH = "prompt_search"
ACTION_SEARCH_TAGS = ACTION_PROMPT_SEARCH  # backward-compatible alias for earlier Phase 0 tests.
ACTION_SEMANTIC_TAG_SEARCH = "semantic_tag_search"
ACTION_NONE = "none"

ROUTE_NAIA_TOOL = "naia_tool"
ROUTE_NAIA_READONLY = "naia_readonly"
ROUTE_OUT_OF_SCOPE = "out_of_scope"
ROUTE_BLOCKED = "blocked"

DOMAIN_NAIA = "naia"
DOMAIN_GENERAL = "general"
DOMAIN_SOURCE_CODE = "source_code"

READONLY_POLICY = "naia_tools_readonly"

_MAX_ACTIONS_PER_RUN = 1
_MAX_JOURNAL_RECORDS = 1000
_JOURNAL_ROTATE_SLACK = 100
_JOURNAL_LOCK = RLock()
_HANGUL_RE = re.compile(r"[가-힣ㄱ-ㅎㅏ-ㅣ]")
_SUBJECT_PATTERNS = (
    re.compile(r"(.+?)(?:와|과)\s*관련(?:된|한)?\s*프롬프트"),
    re.compile(r"(.+?)\s*관련(?:된|한)?\s*프롬프트"),
    re.compile(r"(.+?)\s*프롬프트"),
)
_TAG_DISCOVERY_PATTERNS = (
    re.compile(r"(.+?)(?:을|를)?\s*묘사(?:하는|할|한)?\s*태그"),
    re.compile(r"(.+?)(?:와|과|에)?\s*관련(?:된|한)?\s*태그"),
    re.compile(r"(.+?)\s*태그(?:가|를|는)?\s*(?:있|찾|추천|알려)"),
)
_NAIA_FEATURE_KEYWORDS = (
    "naia", "프롬프트", "prompt", "태그", "tag", "시퀀스", "sequence",
    "이벤트", "event", "의상", "clothes", "복장", "generation", "생성",
    "메타", "metadata", "이미지", "결과", "result", "director", "enhance",
)
_PROMPT_SEARCH_KEYWORDS = (
    "프롬프트", "prompt", "태그", "tag", "추천", "찾아", "검색", "더",
    "변형", "관련", "뜻", "소개",
)
_SOURCE_OBJECT_KEYWORDS = (
    "소스", "source", "코드", "code", "파일", "file", "repo", "repository", "저장소",
)
_MUTATION_KEYWORDS = (
    "수정", "고쳐", "변경", "패치", "patch", "삭제", "delete", "쓰기",
    "write", "저장", "commit", "커밋", "push", "푸시",
)


@dataclass(frozen=True)
class IntentFrame:
    intent: str
    subject: str
    relation: str = "related"
    object: str = "prompt"
    action: str = "introduce"
    language: str = "ko"
    confidence: float = 0.0
    expansion_queries: tuple[str, ...] = ()


@dataclass(frozen=True)
class IntentDecision:
    route: str
    domain: str
    tool_allowed: bool
    read_only: bool = True
    reason_code: str = ""
    next_call: str = "none"
    confidence: float = 0.0

    def summary(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ActionRequest:
    id: str
    action: str
    query: str
    limit: int = 12
    reason: str = ""
    expansion_queries: tuple[str, ...] = ()

    def key(self, context: GenerationInfoContext | None = None) -> str:
        context_key = context.key() if context else ""
        expansion_key = "\n".join(q.strip().lower() for q in self.expansion_queries)
        return f"{self.action}\n{self.query.strip().lower()}\n{self.limit}\n{expansion_key}\n{context_key}"


@dataclass(frozen=True)
class ToolResult:
    action_id: str
    action: str
    query: str
    rows: list[dict[str, Any]]
    ok: bool = True
    error: str = ""


@dataclass
class PipelineRun:
    run_id: str
    user_input: str
    context: GenerationInfoContext
    intent: IntentFrame
    decision: IntentDecision
    actions: list[ActionRequest] = field(default_factory=list)
    tool_results: list[ToolResult] = field(default_factory=list)
    final_output: str = ""
    halted: bool = False
    halt_reason: str = ""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _coerce_text(value: Any, limit: int = 8000) -> str:
    try:
        text = "" if value is None else str(value)
    except Exception:
        return ""
    return text[:limit]


def _default_journal_path() -> Path:
    try:
        from app.backend.runtime.paths import resolve_runtime_paths

        return Path(resolve_runtime_paths().logs_dir) / "instant_command_journal.jsonl"
    except Exception:
        return Path(tempfile.gettempdir()) / "naia_logs" / "instant_command_journal.jsonl"


def _append_jsonl(path: Path, record: dict[str, Any], *, max_records: int = _MAX_JOURNAL_RECORDS) -> None:
    try:
        with _JOURNAL_LOCK:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
            _rotate_jsonl(path, max_records=max_records)
    except Exception:
        # Journal은 보조 감사 로그다. 기록 실패가 사용자 응답을 깨면 안 된다.
        pass


def _rotate_jsonl(path: Path, *, max_records: int) -> None:
    if max_records <= 0:
        return
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        if len(lines) <= max_records + _JOURNAL_ROTATE_SLACK:
            return
        path.write_text("\n".join(lines[-max_records:]) + "\n", encoding="utf-8")
    except Exception:
        pass


def extract_intent_frame(
    user_input: str,
    context: GenerationInfoContext | dict[str, Any] | None = None,
) -> IntentFrame:
    """작은 deterministic fallback extractor.

    출시용 커맨드라인 두뇌가 아니다. Phase 3의 Ollama JSON extractor가 기본 경로가
    되면 이 함수는 JSON 실패/모델 부재 시의 fallback으로 남는다.
    """
    ctx = GenerationInfoContext.from_value(context)
    text = _coerce_text(user_input).strip()
    grounded = f"{text}\n{ctx.prompt}\n{' '.join(ctx.tags)}".strip()
    lowered = grounded.lower()
    subject = ""
    for pattern in _SUBJECT_PATTERNS:
        m = pattern.search(text)
        if m:
            subject = m.group(1)
            break
    tag_subject = ""
    for pattern in _TAG_DISCOVERY_PATTERNS:
        m = pattern.search(text)
        if m:
            tag_subject = m.group(1)
            break
    subject = _clean_subject(subject or text or ctx.prompt)
    has_context = bool(ctx.prompt or ctx.tags or ctx.metadata)
    context_ref = any(k in text for k in ("여기", "현재", "이 프롬프트", "이 태그", "이거", "변형", "관련", "더", "뜻"))
    wants_prompt = "프롬프트" in grounded or "prompt" in lowered or (has_context and context_ref)
    wants_intro = any(k in text for k in ("소개", "추천", "알려", "찾아", "검색", "더", "변형", "뜻"))
    if subject and wants_prompt and wants_intro:
        return IntentFrame(
            intent=INTENT_PROMPT_RECOMMENDATION,
            subject=subject,
            confidence=0.72,
        )
    wants_tag = "태그" in text or "tag" in lowered
    wants_tag_discovery = wants_tag and any(k in text for k in ("있", "찾", "추천", "알려", "묘사", "상황", "어울", "관련"))
    if wants_tag_discovery:
        tag_subject = clean_tag_discovery_subject(tag_subject or text)
        if tag_subject:
            return IntentFrame(
                intent=INTENT_TAG_DISCOVERY,
                subject=tag_subject,
                relation="semantic",
                object="tag",
                action="discover",
                language="ko" if _HANGUL_RE.search(grounded) else "en",
                confidence=0.7,
            )
    return IntentFrame(
        intent="unknown",
        subject=subject,
        relation="",
        object="",
        action="",
        language="ko" if _HANGUL_RE.search(grounded) else "en",
        confidence=0.2 if subject else 0.0,
    )


def decide_intent_route(
    intent: IntentFrame,
    user_input: str,
    context: GenerationInfoContext | dict[str, Any] | None = None,
) -> IntentDecision:
    """NAIA 도구 사용 가능성을 구조화한다.

    이 결정은 tool 실행 전의 deterministic gate다. NAIA Chat이 일반 잡담을 하더라도
    이 파이프라인은 NAIA 도구 호출 여부만 결정한다. 소스/파일 수정 요청은 NAIA 내부
    기능 접근과 별개로 항상 read-only boundary에서 차단한다.
    """
    ctx = GenerationInfoContext.from_value(context)
    text = _coerce_text(user_input)
    lowered = text.lower()
    has_context = bool(ctx.prompt or ctx.tags or ctx.metadata)
    context_ref = has_context and any(
        k in text for k in ("여기", "현재", "이 프롬프트", "이 태그", "이거", "결과", "생성물", "이 이미지")
    )

    if _asks_source_mutation(lowered):
        return IntentDecision(
            route=ROUTE_BLOCKED,
            domain=DOMAIN_SOURCE_CODE,
            tool_allowed=False,
            read_only=True,
            reason_code="source_mutation_blocked",
            next_call="none",
            confidence=0.9,
        )

    if intent.intent == INTENT_PROMPT_RECOMMENDATION and intent.subject:
        return IntentDecision(
            route=ROUTE_NAIA_TOOL,
            domain=DOMAIN_NAIA,
            tool_allowed=True,
            read_only=True,
            reason_code="prompt_search_allowed",
            next_call=ACTION_PROMPT_SEARCH,
            confidence=max(0.0, min(1.0, intent.confidence)),
        )
    if intent.intent == INTENT_TAG_DISCOVERY and intent.subject:
        return IntentDecision(
            route=ROUTE_NAIA_TOOL,
            domain=DOMAIN_NAIA,
            tool_allowed=True,
            read_only=True,
            reason_code="semantic_tag_search_allowed",
            next_call=ACTION_SEMANTIC_TAG_SEARCH,
            confidence=max(0.0, min(1.0, intent.confidence)),
        )

    if _contains_any(lowered, _NAIA_FEATURE_KEYWORDS) or context_ref:
        return IntentDecision(
            route=ROUTE_NAIA_READONLY,
            domain=DOMAIN_NAIA,
            tool_allowed=False,
            read_only=True,
            reason_code="naia_readonly_question",
            next_call="readonly_answer",
            confidence=max(0.35, min(0.75, intent.confidence or 0.5)),
        )

    return IntentDecision(
        route=ROUTE_OUT_OF_SCOPE,
        domain=DOMAIN_GENERAL,
        tool_allowed=False,
        read_only=True,
        reason_code="non_naia_request",
        next_call="none",
        confidence=max(0.4, min(0.8, 1.0 - (intent.confidence or 0.0))),
    )


def _contains_any(text: str, needles: Iterable[str]) -> bool:
    return any(str(needle).lower() in text for needle in needles)


def _asks_source_mutation(lowered: str) -> bool:
    return _contains_any(lowered, _SOURCE_OBJECT_KEYWORDS) and _contains_any(lowered, _MUTATION_KEYWORDS)


def _clean_subject(value: str) -> str:
    text = _coerce_text(value, limit=200).strip()
    text = re.sub(r"^(사용자가|유저가|나는|제가)\s*", "", text)
    text = re.sub(r"(?:들을|를|을|에 대해|에 대한|와|과)$", "", text).strip()
    text = text.strip(" .,:;!?\"'“”‘’<>")
    return text


def build_action_requests(
    intent: IntentFrame,
    decision: IntentDecision | None = None,
) -> list[ActionRequest]:
    """코드 소유 라우팅. 모델은 tool/action 이름을 직접 고르지 않는다."""
    if decision is not None and not decision.tool_allowed:
        return []
    if not intent.subject:
        return []
    if intent.intent == INTENT_TAG_DISCOVERY:
        return [
            ActionRequest(
                id="act-semantic-tag-search-1",
                action=ACTION_SEMANTIC_TAG_SEARCH,
                query=intent.subject,
                limit=12,
                expansion_queries=intent.expansion_queries,
                reason=(
                    "사용자가 자연어 장면 설명에 맞는 실제 태그 후보를 요청했고, "
                    "semantic_tag_search 후보 검색이 필요함."
                ),
            )
        ]
    if intent.intent != INTENT_PROMPT_RECOMMENDATION:
        return []
    return [
        ActionRequest(
            id="act-prompt-search-1",
            action=ACTION_PROMPT_SEARCH,
            query=intent.subject,
            limit=12,
            expansion_queries=intent.expansion_queries,
            reason=(
                "사용자가 현재 생성물 맥락에서 관련 프롬프트 후보를 요청했고, "
                "prompt_search 후보 검색이 필요함."
            ),
        )
    ]


class PipelineLoopGuard:
    """한 run 안에서 자기기억 재탐색/반복 action을 막는 단순 게이트."""

    def __init__(self, max_actions: int = _MAX_ACTIONS_PER_RUN):
        self.max_actions = max(0, int(max_actions))
        self._seen: set[str] = set()
        self._count = 0

    def check(self, action: ActionRequest, context: GenerationInfoContext | None = None) -> tuple[bool, str]:
        if action.action in {"journal_recall", "memory_recall", "self_reflect"}:
            return False, "recursive_memory_action_blocked"
        if self._count >= self.max_actions:
            return False, "max_actions_exceeded"
        key = action.key(context)
        digest = hashlib.sha1(key.encode("utf-8", "replace")).hexdigest()
        if digest in self._seen:
            return False, "duplicate_action_blocked"
        self._seen.add(digest)
        self._count += 1
        return True, ""


class IntentActionPipeline:
    """주입 가능한 prompt_search 기반의 단방향 Instant 실행 기판."""

    def __init__(
        self,
        *,
        searcher: SearchFn | None = None,
        journal_path: str | Path | None = None,
        max_actions: int = _MAX_ACTIONS_PER_RUN,
        max_journal_records: int = _MAX_JOURNAL_RECORDS,
        translator: TranslatorFn | None = None,
    ):
        self.searcher = searcher
        self.journal_path = Path(journal_path) if journal_path else _default_journal_path()
        self.max_actions = max_actions
        self.max_journal_records = max_journal_records
        self.translator = translator

    def run(
        self,
        user_input: str,
        context: GenerationInfoContext | dict[str, Any] | None = None,
        intent: IntentFrame | None = None,
        decision: IntentDecision | None = None,
    ) -> PipelineRun:
        ctx = GenerationInfoContext.from_value(context)
        intent = intent or extract_intent_frame(user_input, ctx)
        decision = decision or decide_intent_route(intent, user_input, ctx)
        run = PipelineRun(
            run_id=str(uuid.uuid4()),
            user_input=_coerce_text(user_input),
            context=ctx,
            intent=intent,
            decision=decision,
        )
        guard = PipelineLoopGuard(max_actions=self.max_actions)
        for action in build_action_requests(run.intent, run.decision):
            ok, reason = guard.check(action, run.context)
            if not ok:
                run.halted = True
                run.halt_reason = reason
                break
            run.actions.append(action)
            result = self._execute_action(action, run.context)
            run.tool_results.append(result)
        run.final_output = compose_final_output(run)
        self._journal_run(run)
        return run

    def _execute_action(self, action: ActionRequest, context: GenerationInfoContext) -> ToolResult:
        if action.action not in {ACTION_PROMPT_SEARCH, ACTION_SEMANTIC_TAG_SEARCH}:
            return ToolResult(
                action_id=action.id,
                action=action.action,
                query=action.query,
                rows=[],
                ok=False,
                error="unsupported_action",
            )
        if self.searcher is None:
            return ToolResult(
                action_id=action.id,
                action=action.action,
                query=action.query,
                rows=[],
                ok=False,
                error="searcher_unavailable",
            )
        try:
            if action.action == ACTION_SEMANTIC_TAG_SEARCH:
                rows = discover_semantic_tags(
                    action.query,
                    searcher=self.searcher,
                    context=context,
                    limit=action.limit,
                    expansion_queries=action.expansion_queries,
                    translator=self.translator,
                )
            else:
                rows = discover_prompt_tags(
                    action.query,
                    searcher=self.searcher,
                    context=context,
                    limit=action.limit,
                    expansion_queries=action.expansion_queries,
                    translator=self.translator,
                )
            return ToolResult(
                action_id=action.id,
                action=action.action,
                query=action.query,
                rows=_normalize_rows(rows),
            )
        except Exception as exc:
            return ToolResult(
                action_id=action.id,
                action=action.action,
                query=action.query,
                rows=[],
                ok=False,
                error=_coerce_text(exc, limit=500),
            )

    def _journal_run(self, run: PipelineRun) -> None:
        result_count = sum(len(result.rows) for result in run.tool_results if result.ok)
        record: dict[str, Any] = {
            "v": 1,
            "ts": _utc_now(),
            "event": "instant_command_run",
            "run_id": run.run_id,
            "input": run.user_input,
            "context": run.context.summary(),
            "intent": asdict(run.intent),
            "decision": run.decision.summary(),
            "actions": [asdict(action) for action in run.actions],
            "result_count": result_count,
            "tool_errors": [result.error for result in run.tool_results if not result.ok and result.error],
            "halted": run.halted,
            "halt_reason": run.halt_reason,
            "structured_output": structured_output(run),
        }
        _append_jsonl(self.journal_path, record, max_records=self.max_journal_records)


def _normalize_rows(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows or []:
        tag = _coerce_text(row.get("tag"), limit=200).strip()
        if not tag:
            continue
        out.append({
            "tag": tag,
            "count": _safe_int(row.get("count")),
            "desc": _coerce_text(row.get("desc") or row.get("description"), limit=500),
            "group": _coerce_text(row.get("group"), limit=200),
            "cat": _coerce_text(row.get("cat") or row.get("_cat"), limit=80),
            **_normalize_optional_row_fields(row),
        })
    return out


def _normalize_optional_row_fields(row: dict[str, Any]) -> dict[str, Any]:
    extra: dict[str, Any] = {}
    if "score" in row:
        try:
            extra["score"] = float(row.get("score") or 0.0)
        except Exception:
            pass
    if row.get("reason"):
        extra["reason"] = _coerce_text(row.get("reason"), limit=300)
    if row.get("role"):
        extra["role"] = _coerce_text(row.get("role"), limit=80)
    return extra


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except Exception:
        return 0


def structured_output(run: PipelineRun) -> dict[str, Any]:
    """Journal/다음 파이프라인 호출용 결정론적 출력."""
    return {
        "v": 1,
        "run_id": run.run_id,
        "route": run.decision.route,
        "domain": run.decision.domain,
        "read_only": run.decision.read_only,
        "policy": READONLY_POLICY,
        "tool_allowed": run.decision.tool_allowed,
        "next_call": run.decision.next_call,
        "reason_code": run.decision.reason_code,
        "intent": asdict(run.intent),
        "actions": [asdict(action) for action in run.actions],
        "tool_results": [
            {
                "action_id": result.action_id,
                "action": result.action,
                "query": result.query,
                "ok": result.ok,
                "error": result.error,
                "row_count": len(result.rows),
                "rows": result.rows,
            }
            for result in run.tool_results
        ],
        "halted": run.halted,
        "halt_reason": run.halt_reason,
        "final_output": run.final_output,
    }


def compose_final_output(run: PipelineRun) -> str:
    """후보 rows만 근거로 하는 단순 composer."""
    if run.halted:
        return "요청 처리 중 반복/재귀 위험이 감지되어 중단했습니다."
    if run.decision.route == ROUTE_BLOCKED:
        return "NAIA 도구 파이프라인은 읽기전용입니다. 소스코드/파일 수정 요청에는 NAIA 도구를 사용하지 않습니다."
    if run.decision.route == ROUTE_OUT_OF_SCOPE:
        return "NAIA 기능 또는 현재 생성물 맥락과 무관한 요청으로 분류되어 NAIA 도구를 사용하지 않았습니다."
    if run.decision.route == ROUTE_NAIA_READONLY:
        return "NAIA 관련 읽기전용 질문으로 분류했습니다. 현재 v1에서는 후보 검색 도구가 필요한 요청만 실행합니다."
    if run.intent.intent not in {INTENT_PROMPT_RECOMMENDATION, INTENT_TAG_DISCOVERY}:
        return "요청 의도를 Instant 프롬프트 검색 작업으로 확정하지 못했습니다."
    rows: list[dict[str, Any]] = []
    for result in run.tool_results:
        if result.ok:
            rows.extend(result.rows)
    if not rows:
        if run.intent.intent == INTENT_TAG_DISCOVERY:
            return f"{run.intent.subject} 상황을 묘사하는 태그 후보를 찾지 못했습니다."
        return f"{run.intent.subject} 관련 프롬프트 후보를 찾지 못했습니다."
    all_tags = _dedupe([str(row["tag"]) for row in rows if row.get("tag")])
    tags = all_tags[:8]
    prefix = f"상위 {len(tags)}개" if len(all_tags) > len(tags) else f"{len(tags)}개"
    total = f"(총 {len(all_tags)}개 후보 중) " if len(all_tags) > len(tags) else ""
    if run.intent.intent == INTENT_TAG_DISCOVERY:
        return (
            f"{run.intent.subject} 상황을 묘사하는 태그 후보 {prefix}는 {total}"
            + ", ".join(tags)
            + " 입니다."
        )
    return (
        f"{run.intent.subject} 관련 주요 프롬프트 후보 {prefix}는 {total}"
        + ", ".join(tags)
        + " 입니다."
    )


def _dedupe(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        key = value.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(value.strip())
    return out


__all__ = [
    "ACTION_NONE",
    "ACTION_PROMPT_SEARCH",
    "ACTION_SEMANTIC_TAG_SEARCH",
    "ACTION_SEARCH_TAGS",
    "ActionRequest",
    "DOMAIN_GENERAL",
    "DOMAIN_NAIA",
    "DOMAIN_SOURCE_CODE",
    "GenerationInfoContext",
    "IntentActionPipeline",
    "IntentDecision",
    "IntentFrame",
    "INTENT_PROMPT_RECOMMENDATION",
    "INTENT_TAG_DISCOVERY",
    "PipelineLoopGuard",
    "PipelineRun",
    "READONLY_POLICY",
    "ROUTE_BLOCKED",
    "ROUTE_NAIA_READONLY",
    "ROUTE_NAIA_TOOL",
    "ROUTE_OUT_OF_SCOPE",
    "ToolResult",
    "build_action_requests",
    "compose_final_output",
    "decide_intent_route",
    "extract_intent_frame",
    "structured_output",
]
