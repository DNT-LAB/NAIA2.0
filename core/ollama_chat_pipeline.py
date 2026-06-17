# -*- coding: utf-8 -*-
"""Step-by-step Ollama Chat pipeline.

Chat input is conversational and ambiguous, so this module owns the Chat-specific
flow instead of cloning Ollama Assist's high-level pipeline. Assist remains the
source for low-level grounded helpers: translation, tag validation/recovery,
variant collapse, and rating gates.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
import time
import uuid
from typing import Any, Callable, Iterable

from core.intent_action_pipeline import GenerationInfoContext
from core.semantic_tag_discovery import ground_scene_segments, normalize_scene_concept


SearchFn = Callable[[str, int, GenerationInfoContext], list[dict[str, Any]]]
EventProvider = Callable[[str, str, str, int], list[dict[str, Any]]]
ClothesProvider = Callable[[str, int], list[dict[str, Any]]]

_HANGUL_RE = re.compile(r"[가-힣ㄱ-ㅎㅏ-ㅣ]")
_CONTEXT_REF_RE = re.compile(
    r"(이런|이거|이 프롬프트|이 이미지|이 그림|현재|지금|그거|this|that|current)",
    re.IGNORECASE,
)
_VAGUE_REFERENTIAL_RE = re.compile(
    r"(이런\s*(?:느낌|분위기|감성)|이거\s*같은|그거\s*같은|this\s*(?:feeling|vibe|mood))",
    re.IGNORECASE,
)
_CLOTHES_COMBO_RE = re.compile(
    r"(코디|조합|어울리는\s*(?:옷|의상|복장)|outfit combination|clothing combination|goes with)",
    re.IGNORECASE,
)
_RELATED_RE = re.compile(r"(관련|추천|recommend|suggest)", re.IGNORECASE)
_MAKE_SCENE_RE = re.compile(
    r"(만들|만들어|장면|구도|scene|compose|create|build|입고|잡는|붙잡|따르는|누워|해변|칼날|여전사)",
    re.IGNORECASE,
)
_VISUAL_DECLARATIVE_RE = re.compile(
    r"(입은|입고|신고|들고|낀|쓴|멘|맨|매고|앉아|서\s*있|누운|누워|짓는|하는|머리를\s*한|"
    r"wearing|standing|sitting|holding|lying)",
    re.IGNORECASE,
)
_VISUAL_CONTENT_RE = re.compile(
    r"(소녀|소년|여자|남자|캐릭터|머리|금발|붉은\s*머리|흰머리|백발|코트|조끼|셔츠|넥타이|"
    r"재킷|자켓|부츠|스커트|드레스|후드티|비키니|수영복|피아노|촛불|칼날|검|해변|배경|"
    r"girl|boy|woman|man|character|hair|blonde|red hair|white hair|coat|vest|shirt|necktie|"
    r"jacket|boots|skirt|dress|hoodie|bikini|swimsuit|piano|candle|sword|blade|beach)",
    re.IGNORECASE,
)
_QUESTION_RE = re.compile(
    r"(\?|？|있나요|있을까|뭐|무엇|어떻게|어때|없나|추천|관련|how|what|why|when|where)",
    re.IGNORECASE,
)
_SOURCE_OBJECT_RE = re.compile(r"(소스|코드|파일|repo|repository|저장소|source|code|file)", re.IGNORECASE)
_MUTATION_ACTION_RE = re.compile(r"(수정|고쳐|패치|삭제|commit|push|write|delete|patch)", re.IGNORECASE)
_EVENT_SEED_AXES = {"action", "pose", "object", "gaze", "expression", "background", "general"}
_EVENT_EXCLUDED_AXES = {"clothing", "character"}

_EVENT_STOP_TAGS = {
    "girl", "boy", "character", "scene", "composition", "pose", "hands", "dog",
    "looking at viewer", "standing", "sitting", "holding", "lying",
    "arms up", "arm up", "hand up", "head tilt", "leaning forward", "sweat",
    "looking ahead", "looking back",
}
_NEAR_EMPTY_GENERIC_TAGS = _EVENT_STOP_TAGS | {
    "1girl", "1boy", "solo", "person", "female", "male", "woman", "man",
    "background", "simple background", "scenery", "mood", "mood lighting",
    "lighting", "soft lighting", "atmosphere", "vibe", "feeling", "aesthetic",
    "looking", "viewing", "camera",
}
_EVENT_STOP_PARTS = (
    "pussy", "futanari", "genital", "pantyshot", "wardrobe malfunction",
    "popped button", "flying button", "clothes lift", "bikini top lift",
    "bikini pull", "bikini in mouth", "clothes in mouth", "tearing clothes",
    "torn clothes", "instrument on back", "mouth hold", "undone bikini",
    "onto self", "zettai ryouiki", "uniform", "blood from eyes", "strap lift",
    "strap slip", "skirt lift", "hand in bikini", "convenient censoring",
)
_CATCHING_INCOMPATIBLE_PARTS = (
    "drawing", "unsheath", "sheathed", "sheath", "pointing", "licking",
    "left-handed", "suicide", "to throat", "sword writing",
)
_CLOTHES_STOP_TAGS = {
    "1girl", "1boy", "solo", "girl", "boy", "woman", "man", "person",
    "male", "female", "standing", "sitting", "lying", "looking at viewer",
    "looking back", "looking ahead", "holding", "pose", "hands",
    "panties", "underwear", "thong", "lingerie", "bra",
    "thighhighs", "headset", "detached sleeves", "wa maid", "male maid",
    "bag charm", "pocket", "bloomers", "hair stick", "mob cap",
}
_CLOTHES_STOP_PARTS = (
    "looking ", "standing", "sitting", "lying", "holding ", "pose",
    "background", "from ", "pov", "open mouth", "smile", "tears",
    "sweat", "blush", "sex", "pussy", "penis", "breasts",
    "panties", "underwear", "thong", "lingerie", "bra", "nipple",
    "areola", "cameltoe", "genital", "thighhighs",
)
_CLOTHES_BLOCKED_CATEGORY_PARTS = ("패턴", "가방", "노출")
_CLOTHES_ALLOWED_CATEGORY_PARTS = (
    "패션", "의류", "복식", "clothing", "fashion", "accessor", "shoe", "footwear",
)
_CLOTHES_LIFT_GLOBAL_FLOOR = 1000
_CLOTHES_MIN_COOCCUR = 80
_CLOTHES_WEAK_SEED_TAGS = {
    "shirt", "collared shirt", "necktie", "tie", "ribbon", "bow",
    "skirt", "dress", "hat", "gloves", "boots", "shoes", "socks",
    "long sleeves", "short sleeves",
}


@dataclass
class ChatPipelineProgress:
    active: bool = False
    runId: str = ""
    step: int = 0
    total: int = 5
    label: str = ""
    started_at: float = 0.0
    done: bool = True

    def snapshot(self) -> dict[str, Any]:
        elapsed = round(max(0.0, time.time() - self.started_at), 1) if self.started_at else 0.0
        return {
            "active": self.active,
            "runId": self.runId,
            "step": self.step,
            "total": self.total,
            "label": self.label,
            "elapsed": elapsed,
            "done": self.done,
        }


@dataclass
class ClampedIntent:
    goal: str = "chat"
    subjects: list[dict[str, Any]] = field(default_factory=list)
    params: dict[str, Any] = field(default_factory=dict)
    ambiguity: dict[str, Any] = field(default_factory=dict)
    proceed: bool = True
    interpretation_note: str = ""
    clarification: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    def summary(self) -> dict[str, Any]:
        return {
            "goal": self.goal,
            "subjects": self.subjects,
            "params": self.params,
            "ambiguity": self.ambiguity,
            "proceed": self.proceed,
            "interpretation_note": self.interpretation_note,
            "clarification": self.clarification,
        }


class OllamaChatPipeline:
    def __init__(
        self,
        *,
        assistant: Any,
        assist_helpers: Any,
        searcher: SearchFn,
        event_provider: EventProvider,
        clothes_provider: ClothesProvider | None = None,
        translator: Callable[[str], str | None] | None = None,
    ) -> None:
        self.assistant = assistant
        self.assist = assist_helpers
        self.searcher = searcher
        self.event_provider = event_provider
        self.clothes_provider = clothes_provider
        self.translator = translator
        self._progress = ChatPipelineProgress()

    def progress(self) -> dict[str, Any]:
        return self._progress.snapshot()

    def _begin(self, run_id: str, label: str) -> None:
        self._progress = ChatPipelineProgress(
            active=True, runId=run_id, step=1, total=5,
            label=label, started_at=time.time(), done=False,
        )

    def _stage(self, step: int, label: str) -> None:
        self._progress.step = int(step)
        self._progress.label = str(label)

    def _end(self) -> None:
        self._progress.active = False
        self._progress.done = True

    def run(
        self,
        user_input: str,
        *,
        gen_context: GenerationInfoContext,
        history: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        run_id = uuid.uuid4().hex
        self._begin(run_id, "intent")
        try:
            raw_intent = self._analyze(user_input, gen_context, history or [])
            intent = self._clamp_intent(raw_intent, user_input, gen_context)
            if not intent.proceed:
                return self._clarification(user_input, intent)
            if intent.goal not in {"scene_compose", "event_lookup", "tag_discovery"}:
                return {"handled": False, "intent": intent.summary()}
            if intent.goal == "tag_discovery" and not self._looks_scene_like(user_input):
                return {"handled": False, "intent": intent.summary()}

            self._stage(2, "번역")
            translation = self._translate(user_input)
            clean = str(translation.get("cleanEnglish") or user_input).strip()

            self._stage(3, "도구")
            decompose = self.assistant.decompose_scene(clean)
            if not isinstance(decompose, dict) or not decompose.get("ok"):
                return {"handled": False, "intent": intent.summary(), "translation": translation}
            segments = ground_scene_segments(
                decompose.get("segments") or [],
                searcher=self._clean_searcher,
                context=gen_context,
                per_concept_limit=6,
            )
            if not segments:
                return {"handled": False, "intent": intent.summary(), "translation": translation}

            self._stage(4, "가지치기")
            flat_tags = self._flat_scene_tags(segments)
            event_tags = self._event_tags(segments, flat_tags, clean)
            clothes_tags = self._clothes_tags(segments, flat_tags)

            self._stage(5, "최종")
            final_tags = self._final_tags(flat_tags, event_tags)
            if self._is_near_empty(final_tags, event_tags, user_input):
                return self._clarification(user_input, intent)
            return {
                "handled": True,
                "ok": True,
                "type": "scene_pipeline",
                "intent": intent.summary(),
                "translation": {
                    "source": translation.get("source") or user_input,
                    "mt": translation.get("mt") or "",
                    "cleanEnglish": clean,
                },
                "segments": segments,
                "eventTags": event_tags,
                "clothesTags": clothes_tags,
                "finalTags": final_tags,
                "message": "이렇게 이해하고 실제 태그 후보로 정리했습니다.",
            }
        except Exception as exc:
            return {"handled": False, "error": str(exc) or "chat pipeline failed"}
        finally:
            self._end()

    def _clarification(self, user_input: str, intent: ClampedIntent) -> dict[str, Any]:
        question = (
            intent.clarification
            or "무엇을 만들고 싶은지 조금 더 구체적으로 알려주세요. 아래처럼 입력하면 가장 잘 동작해요:"
        )
        if "아래처럼" not in question:
            question = "무엇을 만들고 싶은지 조금 더 구체적으로 알려주세요. 아래처럼 입력하면 가장 잘 동작해요:"
        return {
            "handled": True,
            "ok": True,
            "type": "clarification",
            "question": question,
            "examples": [
                "교복 입은 소녀가 침대에 누워 카메라를 보는 장면",
                "메이드복에 어울리는 의상 조합",
                "가슴골을 강조하는 태그",
                "수영복 입은 소녀가 해변에 누운 장면",
            ],
            "intent": intent.summary(),
        }

    def _is_near_empty(
        self,
        final_tags: list[str],
        event_tags: list[dict[str, Any]],
        user_input: str = "",
    ) -> bool:
        event_set = {_norm(item.get("tag")) for item in event_tags or []}
        scene_meaningful = [
            tag for tag in final_tags or []
            if _norm(tag) not in event_set and self._is_meaningful_tag(tag)
        ]
        if _VAGUE_REFERENTIAL_RE.search(str(user_input or "")) and len(scene_meaningful) <= 2:
            return True
        if event_tags:
            return False
        meaningful: list[str] = []
        for tag in final_tags or []:
            if self._is_meaningful_tag(tag):
                meaningful.append(_norm(tag))
        return len(meaningful) <= 1

    def _is_meaningful_tag(self, tag: Any) -> bool:
        norm = _norm(tag)
        if not norm:
            return False
        if norm in _NEAR_EMPTY_GENERIC_TAGS:
            return False
        if any(part in norm for part in ("mood", "lighting", "background", "atmosphere", "vibe")):
            return False
        return True

    def _analyze(
        self,
        user_input: str,
        gen_context: GenerationInfoContext,
        history: list[dict[str, Any]],
    ) -> dict[str, Any]:
        analyzer = getattr(self.assistant, "analyze_chat_intent", None)
        if not callable(analyzer):
            return {}
        result = analyzer(
            user_input=user_input,
            context=gen_context.summary(),
            history=history,
        )
        if isinstance(result, dict) and result.get("ok") and isinstance(result.get("data"), dict):
            return dict(result["data"])
        return {}

    def _clamp_intent(
        self,
        raw: dict[str, Any],
        user_input: str,
        gen_context: GenerationInfoContext,
    ) -> ClampedIntent:
        text = str(user_input or "")
        has_context = bool(gen_context.prompt or gen_context.tags or gen_context.metadata)
        context_ref = bool(_CONTEXT_REF_RE.search(text))
        visual_scene = self._looks_visual_declarative(text)
        goal = str(raw.get("goal") or "chat").strip()
        if goal not in {
            "scene_compose", "clothes_combo", "event_lookup",
            "tag_discovery", "prompt_critique", "chat", "blocked",
        }:
            goal = "chat"
        if _SOURCE_OBJECT_RE.search(text) and _MUTATION_ACTION_RE.search(text):
            goal = "blocked"
        elif _CLOTHES_COMBO_RE.search(text):
            goal = "clothes_combo"
        elif (_MAKE_SCENE_RE.search(text) or visual_scene) and not _RELATED_RE.search(text):
            goal = "scene_compose"
        elif _RELATED_RE.search(text):
            goal = "tag_discovery"

        subjects = self._normalize_subjects(raw.get("subjects"), text)
        if goal == "scene_compose" and not subjects:
            subject = self._fallback_subject(text)
            if subject:
                subjects = [{"text": subject, "kind": "scene", "axis": "general", "confidence": 0.5}]
        if goal == "tag_discovery" and not subjects:
            subject = self._fallback_subject(text)
            if subject:
                subjects = [{"text": subject, "kind": "subject", "axis": "general", "confidence": 0.5}]

        ambiguity = raw.get("ambiguity") if isinstance(raw.get("ambiguity"), dict) else {}
        level = str(ambiguity.get("level") or "low").lower()
        if level not in {"none", "low", "medium", "high"}:
            level = "low"
        ambiguity = {
            "level": level,
            "alternatives": [
                str(item)[:120]
                for item in (ambiguity.get("alternatives") if isinstance(ambiguity.get("alternatives"), list) else [])
                if str(item or "").strip()
            ][:4],
            "reason": str(ambiguity.get("reason") or "")[:500],
        }
        params = raw.get("params") if isinstance(raw.get("params"), dict) else {}
        params = {
            "context_ref": context_ref,
            "needs_tools": goal not in {"chat", "blocked"},
            "desired_output": str(params.get("desired_output") or ""),
            "tone": str(params.get("tone") or ""),
        }
        proceed = bool(raw.get("proceed", True))
        clarification = str(raw.get("clarification") or "").strip()
        if context_ref and not has_context:
            goal = "chat"
            proceed = False
            ambiguity["level"] = "high"
            clarification = self._clarification_for(text)
        if ambiguity["level"] == "high" or (goal not in {"chat", "blocked"} and not subjects):
            proceed = False
            clarification = clarification or self._clarification_for(text)
        note = str(raw.get("interpretation_note") or "").strip()
        if ambiguity["level"] == "medium" and not note:
            note = "요청이 넓어서 가장 가능성 높은 의미로 먼저 해석했습니다."
        return ClampedIntent(
            goal=goal,
            subjects=subjects,
            params=params,
            ambiguity=ambiguity,
            proceed=proceed,
            interpretation_note=note,
            clarification=clarification,
            raw=raw,
        )

    def _normalize_subjects(self, value: Any, user_input: str) -> list[dict[str, Any]]:
        raw_items = value if isinstance(value, list) else []
        out: list[dict[str, Any]] = []
        for item in raw_items[:6]:
            if not isinstance(item, dict):
                continue
            text = self._english_subject(str(item.get("text") or ""), user_input)
            if not text:
                continue
            out.append({
                "text": text,
                "kind": str(item.get("kind") or "subject")[:60],
                "axis": str(item.get("axis") or "general")[:60],
                "confidence": _clamp_float(item.get("confidence"), 0.0, 1.0, 0.5),
            })
        if not out:
            subject = self._fallback_subject(user_input)
            if subject:
                out.append({"text": subject, "kind": "subject", "axis": "general", "confidence": 0.5})
        return out

    def _english_subject(self, text: str, user_input: str) -> str:
        value = str(text or "").strip()
        paren = re.search(r"\(([A-Za-z][^)]+)\)", value)
        if paren:
            value = paren.group(1)
        value = value.lower().replace("_", " ")
        if _HANGUL_RE.search(value):
            return self._fallback_subject(user_input)
        value = re.sub(r"\b(thing|object|scene|prompt|tags?|recommendation|related)\b", " ", value)
        value = " ".join(value.split())
        if len(value) > 40 or len(value.split()) > 7:
            return ""
        return value[:80]

    def _fallback_subject(self, text: str) -> str:
        if "메이드" in text:
            return "maid"
        if "해변" in text:
            return "beach scene"
        if "여전사" in text and ("칼날" in text or "검" in text):
            return "female warrior catching blade"
        if "칼날" in text:
            return "catching blade"
        if "비키니" in text:
            return "bikini"
        if "섹시" in text:
            return "sexy"
        if self._looks_visual_declarative(text):
            return ""
        cleaned = re.sub(r"(관련|추천|프롬프트|태그|만들어줘|만들|장면|구도)", " ", text)
        cleaned = " ".join(cleaned.split())
        if len(cleaned) > 40:
            return ""
        return cleaned[:80]

    def _clarification_for(self, text: str) -> str:
        if "이런" in text or "느낌" in text:
            return "어떤 느낌을 말하는지 참고 이미지나 키워드를 하나만 알려주세요."
        return "어떤 방향으로 만들고 싶은지 한 가지 키워드만 더 알려주세요."

    def _looks_scene_like(self, text: str) -> bool:
        text = str(text or "")
        return bool(_MAKE_SCENE_RE.search(text) or self._looks_visual_declarative(text))

    def _looks_visual_declarative(self, text: str) -> bool:
        text = str(text or "").strip()
        if not text:
            return False
        if _QUESTION_RE.search(text) or _RELATED_RE.search(text) or _CLOTHES_COMBO_RE.search(text):
            return False
        if _SOURCE_OBJECT_RE.search(text) and _MUTATION_ACTION_RE.search(text):
            return False
        content_hits = _VISUAL_CONTENT_RE.findall(text)
        if _VISUAL_DECLARATIVE_RE.search(text) and len(content_hits) >= 2:
            return True
        return len(text) >= 28 and len(content_hits) >= 3

    def _translate(self, user_input: str) -> dict[str, Any]:
        mt = ""
        try:
            translated, original = self.assist.translate_to_english(user_input)
            if translated and translated != original and not _HANGUL_RE.search(str(translated)):
                mt = str(translated)
        except Exception:
            mt = ""
        reconciler = getattr(self.assistant, "reconcile_scene_english", None)
        if callable(reconciler):
            result = reconciler(source=user_input, mt=mt)
            if isinstance(result, dict) and result.get("ok"):
                return result
        clean = mt or user_input
        return {"ok": True, "source": user_input, "mt": mt, "cleanEnglish": clean}

    def _clean_searcher(
        self,
        query: str,
        limit: int,
        gen_context: GenerationInfoContext,
    ) -> list[dict[str, Any]]:
        query = normalize_scene_concept(query)
        if not query or _HANGUL_RE.search(query):
            return []
        return self.searcher(query, limit, gen_context)

    def _flat_scene_tags(self, segments: list[dict[str, Any]]) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        for segment in segments or []:
            for row in segment.get("tags") or []:
                tag = _norm(row.get("tag"))
                if tag and tag not in seen:
                    seen.add(tag)
                    out.append(tag)
        return out

    def _event_tags(
        self,
        segments: list[dict[str, Any]],
        flat_tags: list[str],
        clean_english: str,
    ) -> list[dict[str, Any]]:
        queries = self._event_queries(segments, flat_tags, clean_english)
        if not queries:
            return []
        scene_set = {_norm(tag) for tag in flat_tags}
        protected = set(scene_set)
        for query in queries:
            protected.add(_norm(query))
        weights: dict[str, dict[str, Any]] = {}
        for query in queries[:8]:
            for rating in ("s", "g"):
                try:
                    rows = list(self.event_provider(rating, "1girl_solo", query, 4) or [])
                except Exception:
                    rows = []
                for row in rows:
                    if isinstance(row, tuple):
                        tag, count = row[0], row[1] if len(row) > 1 else 1
                        support = 1
                    else:
                        tag = row.get("tag")
                        count = row.get("count", 1)
                        support = row.get("support", 1)
                    norm = _norm(tag)
                    if not norm or norm in scene_set or self._event_stop(norm):
                        continue
                    item = weights.setdefault(norm, {
                        "tag": norm, "count": 0, "support": 0, "queries": set(),
                    })
                    item["count"] += int(count or 0)
                    item["support"] += int(support or 1)
                    item["queries"].add(query)
        candidates = list(weights.values())
        if not candidates:
            return []
        candidates.sort(key=lambda item: int(item.get("count") or 0), reverse=True)
        top_count = int(candidates[0].get("count") or 0)
        floor = max(30, min(100, int(top_count * 0.01)))
        catch_context = any("catch" in item or "grab" in item for item in protected)
        validated: list[dict[str, Any]] = []
        seen: set[str] = set(scene_set)
        for item in candidates:
            tag = str(item["tag"])
            count = int(item.get("count") or 0)
            support = int(item.get("support") or 0)
            if support < 2 or count < floor:
                continue
            if catch_context and any(part in tag for part in _CATCHING_INCOMPATIBLE_PARTS):
                continue
            if catch_context and not any(part in tag for part in ("sword", "weapon", "blade", "catch", "holding")):
                continue
            if tag == "holding weapon" and any(c["tag"] == "holding sword" for c in validated):
                continue
            if tag == "holding sword" and any(c["tag"] == "holding weapon" for c in validated):
                validated = [c for c in validated if c["tag"] != "holding weapon"]
            if not self.assist.tag_allowed(tag, "e"):
                continue
            validated_row = self.assist.validate_tag(tag)
            if not validated_row:
                validated_row = self.assist.recover_tag(tag, seen, max_rating="e")
            if not validated_row:
                continue
            real_tag = _norm(validated_row.get("tag"))
            if not real_tag or real_tag in seen or self._event_stop(real_tag):
                continue
            seen.add(real_tag)
            validated.append({
                "tag": real_tag,
                "count": count,
                "support": support,
            })
        collapsed = self.assist.collapse_variants(validated, protected)
        collapsed.sort(key=lambda item: int(item.get("count") or 0), reverse=True)
        return collapsed[:6]

    def _clothes_tags(
        self,
        segments: list[dict[str, Any]],
        flat_tags: list[str],
    ) -> list[dict[str, Any]]:
        provider = self.clothes_provider
        if not callable(provider):
            return []
        scene_set = {_norm(tag) for tag in flat_tags or []}
        seeds: list[str] = []
        seed_seen: set[str] = set()
        for segment in segments or []:
            if _norm(segment.get("axis")) != "clothing":
                continue
            phrase = _norm(segment.get("phrase"))
            for row in segment.get("tags") or []:
                tag = _norm(row.get("tag"))
                if not self._clothes_seed_matches_phrase(tag, phrase):
                    continue
                if tag and tag not in seed_seen:
                    seed_seen.add(tag)
                    seeds.append(tag)
        if not seeds:
            return []

        query_seeds = [seed for seed in seeds if seed not in _CLOTHES_WEAK_SEED_TAGS]
        if not query_seeds:
            query_seeds = seeds

        weighted: dict[str, int] = {}
        for seed in query_seeds[:6]:
            try:
                combos = list(provider(seed, 8) or [])
            except Exception:
                combos = []
            for combo in combos:
                if not isinstance(combo, dict):
                    continue
                try:
                    count = int(combo.get("count") or combo.get("post_count") or 0)
                except Exception:
                    count = 0
                if count <= 0:
                    count = 1
                tags = combo.get("tags") if isinstance(combo.get("tags"), list) else []
                for tag in tags:
                    norm = _norm(tag)
                    if not norm or norm == seed or norm in scene_set or self._clothes_stop(norm):
                        continue
                    weighted[norm] = weighted.get(norm, 0) + count
        if not weighted:
            return []

        candidates: list[dict[str, Any]] = []
        seen: set[str] = set(scene_set)
        global_counts: dict[str, int] = {}
        for tag, count in weighted.items():
            count = int(count)
            if count < _CLOTHES_MIN_COOCCUR:
                continue
            if tag in seen:
                continue
            if not self.assist.tag_allowed(tag, "e"):
                continue
            validated = self.assist.validate_tag(tag)
            if not validated:
                continue
            if not self._clothes_category_allowed(validated.get("category")):
                continue
            real_tag = _norm(validated.get("tag"))
            if not real_tag or real_tag in seen or self._clothes_stop(real_tag):
                continue
            global_count = self._clothes_global_count(real_tag, validated, global_counts)
            score = float(count)
            lift = 0.0
            if global_count > 0:
                lift = count / max(global_count, _CLOTHES_LIFT_GLOBAL_FLOOR)
                score = lift
            seen.add(real_tag)
            candidates.append({
                "tag": real_tag,
                "count": count,
                "_score": score,
                "_lift": lift,
                "_global": global_count,
            })
        candidates.sort(
            key=lambda item: (float(item.get("_score") or 0.0), int(item.get("count") or 0)),
            reverse=True,
        )
        protected = set(scene_set)
        seed_tokens = [
            {word for word in seed.split() if len(word) > 1}
            for seed in seeds
        ]
        for item in candidates:
            tag = _norm(item.get("tag"))
            tag_tokens = {word for word in tag.split() if len(word) > 1}
            if any(tokens and tokens <= tag_tokens for tokens in seed_tokens):
                protected.add(tag)
        collapsed = self.assist.collapse_variants(candidates, protected)
        collapsed.sort(
            key=lambda item: (float(item.get("_score") or 0.0), int(item.get("count") or 0)),
            reverse=True,
        )
        out: list[dict[str, Any]] = []
        seen = set(scene_set)
        for item in collapsed:
            tag = _norm(item.get("tag"))
            if not tag or tag in seen:
                continue
            seen.add(tag)
            out.append({"tag": tag, "count": int(item.get("count") or 0)})
            if len(out) >= 8:
                break
        return out

    def _event_queries(
        self,
        segments: list[dict[str, Any]],
        flat_tags: list[str],
        clean_english: str,
    ) -> list[str]:
        out: list[str] = []

        def add(value: str) -> None:
            text = normalize_scene_concept(value)
            if not text or _HANGUL_RE.search(text) or text in out:
                return
            if text in _EVENT_STOP_TAGS:
                return
            out.append(text)

        for segment in segments or []:
            axis = _norm(segment.get("axis"))
            if axis in _EVENT_EXCLUDED_AXES or axis not in _EVENT_SEED_AXES:
                continue
            for row in segment.get("tags") or []:
                add(str(row.get("concept") or ""))
                add(str(row.get("tag") or ""))
        joined = " ".join(out).lower()
        if any(word in joined for word in ("tea", "teapot", "pour")):
            for item in ("teapot", "holding teapot", "serving", "pouring"):
                add(item)
        if any(word in joined for word in ("blade", "sword", "warrior", "catch")):
            for item in ("catching", "holding sword", "sword", "blade"):
                add(item)
        if "beach" in joined:
            add("beach")
        if "lying" in joined or "reclin" in joined:
            add("lying down")
        return out[:10]

    def _event_stop(self, tag: str) -> bool:
        if tag in _EVENT_STOP_TAGS:
            return True
        return any(part in tag for part in _EVENT_STOP_PARTS)

    def _clothes_stop(self, tag: str) -> bool:
        if tag in _CLOTHES_STOP_TAGS or tag in _EVENT_STOP_TAGS or tag in _NEAR_EMPTY_GENERIC_TAGS:
            return True
        return any(part in tag for part in _CLOTHES_STOP_PARTS)

    def _clothes_category_allowed(self, category: Any) -> bool:
        text = str(category or "").strip()
        if not text:
            return False
        if any(part in text for part in _CLOTHES_BLOCKED_CATEGORY_PARTS):
            return False
        lowered = text.lower()
        return any(part in lowered or part in text for part in _CLOTHES_ALLOWED_CATEGORY_PARTS)

    def _clothes_global_count(
        self,
        tag: str,
        validated: dict[str, Any],
        cache: dict[str, int],
    ) -> int:
        tag = _norm(tag)
        if tag in cache:
            return cache[tag]
        try:
            count = int(validated.get("count") or 0)
        except Exception:
            count = 0
        if count <= 0:
            try:
                rows = list(self.searcher(tag, 1, GenerationInfoContext()) or [])
            except Exception:
                rows = []
            for row in rows:
                row_tag = _norm(row.get("tag"))
                if row_tag != tag:
                    continue
                try:
                    count = int(row.get("count") or 0)
                except Exception:
                    count = 0
                break
        cache[tag] = max(0, count)
        return cache[tag]

    def _clothes_seed_matches_phrase(self, tag: str, phrase: str) -> bool:
        if not tag or not phrase:
            return bool(tag)
        words = [word for word in tag.split() if len(word) > 1]
        if not words:
            return False
        return all(word in phrase for word in words)

    def _final_tags(self, flat_tags: list[str], event_tags: list[dict[str, Any]]) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        for tag in list(flat_tags or []) + [str(item.get("tag") or "") for item in event_tags or []]:
            norm = _norm(tag)
            if norm and norm not in seen:
                seen.add(norm)
                out.append(norm)
        return out


def _norm(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().replace("_", " ").split())


def _clamp_float(value: Any, low: float, high: float, default: float) -> float:
    try:
        num = float(value)
    except Exception:
        return default
    return max(low, min(high, num))
