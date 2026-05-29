"""Headless port of e621 Auto-Boost + Danbooru Auto-Weight algorithms.

future01's desktop ``modules/prompt_engineering_module.py`` implemented these two
prompt-preprocessing features as PyQt-bound methods, reachable from the headless
pipeline only via ``MiddleSectionController.get_module_instance(...)``. future02
removed Qt and sets ``middle_section_controller = None``
(``core/headless_context_bootstrap.py``), so the advanced-module bridge in
``core/prompt_engineering_runtime.py`` always resolved to ``None`` and BOTH
features were silent no-ops (dead code) — the checkboxes/settings/UI/debug
scaffolding existed but the algorithms never ran.

This service ports the algorithm bodies **verbatim** from the desktop module
(Dev0714 ≡ future01, byte-identical) into a Qt-free, headless-reachable form.
``_PromptEngineeringAdvancedModuleBridge.module()`` returns an instance of this
service when the desktop controller is absent, so the existing post_processing
and after_wildcard hook wiring drives it unchanged (method names mirror the
desktop contract: ``_apply_danbooru_auto_weight`` / ``_run_e621_boost`` /
``_execute_e621_after_wildcard`` / ``_execute_danbooru_weight_after_wildcard``).

Reused as-is (byte-identical to the desktop branch, do not modify):
  - ``data/danbooru_tag_counts_by_rating.json`` (rating-conditional tag counts)
  - ``data/e621_boost_static.py`` (``recommend_detailed`` lookup table)
Weight syntax is preserved exactly — NAI ``'{w:.2f}::tag ::'`` / e621 group
``'{w}::tag1, ..., tagN ::'``, WEBUI ``'(tag:{w:.2f})'`` / e621 ``'(t1, ..., tN:{w})'``
— this is a downstream prompt-parser contract.

Adaptations from the desktop original (only what Qt removal requires):
  - settings come from ``prompt_engineering_settings`` JSON store (loaded per call)
    instead of ``self._*_settings`` synced from Qt widgets;
  - the Qt ``_update_debug_window`` call is dropped (headless debug renders from
    ``context.metadata['e621_debug_info']`` via the existing renderer);
  - the highlighter side-effect is a guarded no-op (``main_window`` is None
    headless).
"""

from __future__ import annotations

import importlib.util
import json
import math
import random
import re
from pathlib import Path
from typing import Any

from core.prompt_context import PromptContext
from core.prompt_engineering_settings import (
    load_danbooru_weight_settings,
    load_e621_settings,
)

# 가중치 포맷 감지 패턴 (NAI: '1.05::tag ::', WEBUI: '(tag:1.05)') — 데스크톱 모듈과 동일.
_WEIGHT_NAI_DETECT = re.compile(r'^[\d.]+::.*::$')
_WEIGHT_WEBUI_DETECT = re.compile(r'^\(.*:[\d.]+\)$')

# 인원 수 태그 — 가중치/부스트 대상에서 제외 (prompt_engineering_runtime._PERSON_TAGS 와 동일 집합).
_PERSON_TAGS = frozenset({
    "1boy", "2boys", "3boys", "4boys", "5boys", "6+boys",
    "1girl", "2girls", "3girls", "4girls", "5girls", "6+girls",
    "1other", "2others", "3others", "4others", "5others", "6+others",
})

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"


class HeadlessPromptBoostService:
    """Qt-free port of the desktop PromptEngineeringModule's e621/danbooru logic.

    A single instance is cached on the app context so the (lazy, one-time) data
    loads — the danbooru counts table and the e621 ``recommend_detailed`` module —
    persist across generations.
    """

    # ── 클래스 상수 (데스크톱 PromptEngineeringModule 과 동일 값) ──
    _RATING_INDEX = {"g": 0, "s": 1, "q": 2, "e": 3}
    _danbooru_norm_low_default = 1.0
    _danbooru_norm_high_default = 10.0
    _RATING_BLEND = 0.3  # Rating 보정 블렌드 비율 (0=전역만, 1=rating만)
    _DANBOORU_MAGNITUDE_TABLE = {
        1:  {"min_weight": 0.88, "max_weight": 1.15, "scale": 0.15, "label": "약한"},
        2:  {"min_weight": 0.84, "max_weight": 1.25, "scale": 0.25, "label": "중간"},
        3:  {"min_weight": 0.80, "max_weight": 1.35, "scale": 0.35, "label": "추천"},
        4:  {"min_weight": 0.75, "max_weight": 1.42, "scale": 0.42, "label": "강한"},
        5:  {"min_weight": 0.70, "max_weight": 1.50, "scale": 0.50, "label": "최대"},
        6:  {"min_weight": 0.62, "max_weight": 1.60, "scale": 0.60, "label": "최대+"},
        7:  {"min_weight": 0.55, "max_weight": 1.70, "scale": 0.70, "label": "최대++"},
        8:  {"min_weight": 0.50, "max_weight": 1.80, "scale": 0.80, "label": "극한"},
        9:  {"min_weight": 0.45, "max_weight": 1.90, "scale": 0.90, "label": "극한+"},
        10: {"min_weight": 0.40, "max_weight": 2.00, "scale": 1.00, "label": "극한++"},
    }

    def __init__(self, app_context: Any):
        self.app_context = app_context
        # danbooru 데이터 lazy-load 캐시 (인스턴스 1회 로드 후 재사용)
        self._danbooru_tag_counts = None
        self._danbooru_rating_totals = [1, 1, 1, 1]
        self._danbooru_global_idfs = {}
        self._danbooru_norm_low = self._danbooru_norm_low_default
        self._danbooru_norm_high = self._danbooru_norm_high_default
        # 설정 (각 호출 진입 시 JSON 스토어에서 새로 로드)
        self._e621_settings = {"weight": 0.0, "hidden_tags": [], "mode": "stable"}
        self._danbooru_weight_settings = {"magnitude": 3}
        # NOTE: self._e621_recommend 은 의도적으로 미초기화 — _run_e621_boost 의
        # `if not hasattr(self, '_e621_recommend')` lazy-load 가드가 동작해야 한다.

    # ── 설정 로딩 (데스크톱의 apply_settings(collect_settings()) 대체) ──
    def _settings_save_root(self):
        runtime_paths = getattr(self.app_context, "runtime_paths", None)
        return getattr(runtime_paths, "save_dir", None)

    def _refresh_e621_settings(self) -> None:
        self._e621_settings = load_e621_settings(save_root=self._settings_save_root())

    def _refresh_danbooru_settings(self) -> None:
        self._danbooru_weight_settings = load_danbooru_weight_settings(
            save_root=self._settings_save_root()
        )

    # ── Danbooru 데이터 로더 (verbatim) ──
    def _get_danbooru_tag_counts(self) -> dict:
        """Rating 조건부 태그 빈도 데이터 로드 + 전역 IDF 범위 사전 계산 (lazy, 1회만)"""
        if self._danbooru_tag_counts is not None:
            return self._danbooru_tag_counts
        path = _DATA_DIR / "danbooru_tag_counts_by_rating.json"
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        meta = data.pop("_meta")
        self._danbooru_rating_totals = meta["total_posts"]  # [g, s, q, e]
        self._danbooru_tag_counts = data  # {tag: [g, s, q, e]}

        # 전역 IDF 범위 사전 계산 (정규화 기준)
        global_total = sum(self._danbooru_rating_totals)
        global_idfs = {}
        for tag, counts in data.items():
            gc = sum(counts)
            if gc > 0:
                global_idfs[tag] = -math.log2(gc / global_total)
        self._danbooru_global_idfs = global_idfs
        # 정규화 범위: 실용 태그 대역 (IDF 1~10) 으로 클리핑
        self._danbooru_norm_low = self._danbooru_norm_low_default
        self._danbooru_norm_high = self._danbooru_norm_high_default
        self._danbooru_global_total = global_total
        print(f"[Danbooru Auto-Weight] loaded {len(data):,} tags, "
              f"norm range: {self._danbooru_norm_low}~{self._danbooru_norm_high}")
        return self._danbooru_tag_counts

    @staticmethod
    def _strip_weight_syntax(tag: str) -> str:
        """태그에서 가중치 래핑 구문을 제거하여 순수 태그명만 반환.
        NAI: '1.20::tag ::' → 'tag'
        A1111/ComfyUI: '(tag:1.20)' → 'tag'
        """
        s = tag.strip()
        if '::' in s:
            if s.endswith('::'):
                s = s[:-2].strip()
            if '::' in s:
                parts = s.split('::', 1)
                try:
                    float(parts[0].strip())
                    s = parts[1].strip()
                except ValueError:
                    pass
        if s.startswith('(') and s.endswith(')'):
            inner = s[1:-1]
            colon_idx = inner.rfind(':')
            if colon_idx > 0:
                try:
                    float(inner[colon_idx + 1:])
                    s = inner[:colon_idx].strip()
                except ValueError:
                    pass
        return s

    def _infer_rating_from_tags(self, tags: list) -> str:
        """태그 분포 기반 rating 추론 (와일드카드 단독 모드 전용). Naive Bayes."""
        if not tags:
            return 's'

        tag_counts = self._get_danbooru_tag_counts()
        totals = self._danbooru_rating_totals  # [g, s, q, e]
        vocab_size = len(tag_counts)

        log_scores = [0.0, 0.0, 0.0, 0.0]  # g, s, q, e

        matched = 0
        for tag in tags:
            clean = self._strip_weight_syntax(tag)
            if clean in _PERSON_TAGS or clean not in tag_counts:
                continue
            counts = tag_counts[clean]
            matched += 1
            for ri in range(4):
                prob = (counts[ri] + 1) / (totals[ri] + vocab_size)
                log_scores[ri] += math.log(prob)

        if matched < 3:
            return 's'  # 데이터 부족 — 보수적 기본값

        max_score = max(log_scores)
        rating_labels = ['g', 's', 'q', 'e']
        best_ri = log_scores.index(max_score)
        best_rating = rating_labels[best_ri]

        print(f"[Danbooru Auto-Weight] inferred rating='{best_rating}' "
              f"from {matched} tags (scores: "
              f"g={log_scores[0]-max_score:.1f}, s={log_scores[1]-max_score:.1f}, "
              f"q={log_scores[2]-max_score:.1f}, e={log_scores[3]-max_score:.1f})")
        return best_rating

    # ── Danbooru Auto-Weight 코어 (verbatim, in-place) ──
    def _apply_danbooru_auto_weight(self, main_tags: list, context: PromptContext, *, min_valid_count: int = 3):
        """전역 IDF + Rating 조건부 보정 블렌딩, 전역 범위 정규화 (main_tags in-place 수정)

        blended_idf = global_idf + α * (rating_idf - global_idf)
        norm = (blended_idf - n_low) / (n_high - n_low)
        weight = 1.0 + scale * (2*norm - 1)
        """
        self._refresh_danbooru_settings()
        try:
            tag_counts = self._get_danbooru_tag_counts()
        except Exception as e:
            print(f"⚠️ Danbooru Auto-Weight: 태그 데이터 로드 실패 — {e}")
            return

        settings = self._danbooru_weight_settings
        mag = settings.get("magnitude", 3)
        mag_params = self._DANBOORU_MAGNITUDE_TABLE.get(mag, self._DANBOORU_MAGNITUDE_TABLE[3])
        scale = mag_params["scale"]
        min_w = mag_params["min_weight"]
        max_w = mag_params["max_weight"]
        # 커스텀 오버라이드 적용
        if settings.get("override_on"):
            scale = settings.get("override_scale", scale)
            min_w = settings.get("override_min", min_w)
            max_w = settings.get("override_max", max_w)
        invert = settings.get("invert_weight", False)
        is_nai = context.settings.get('api_mode') == 'NAI'
        alpha = settings.get("rating_blend", self._RATING_BLEND)

        # Rating 조건부: 오버라이드 > source_row > 추론 > fallback
        if settings.get("rating_override_on") and settings.get("rating_override") in self._RATING_INDEX:
            rating = settings["rating_override"]
        else:
            _raw_rating = context.source_row.get('rating', None)
            # NaN/None/NaT 등 pandas missing 타입 모두 처리
            rating = str(_raw_rating).strip().lower() if _raw_rating is not None and _raw_rating == _raw_rating else None
            if rating not in self._RATING_INDEX:
                # 와일드카드 단독 모드: 태그에서 추론
                if context.settings.get('wildcard_standalone', False):
                    rating = self._infer_rating_from_tags(main_tags)
                else:
                    rating = 's'  # fallback
        ri = self._RATING_INDEX[rating]
        rating_total = max(self._danbooru_rating_totals[ri], 1)

        # 실용 대역 클리핑 정규화 범위 (IDF 1~10)
        n_low = self._danbooru_norm_low
        n_high = self._danbooru_norm_high
        n_range = n_high - n_low

        global_idfs = self._danbooru_global_idfs

        # 1단계: 각 태그의 블렌딩 IDF 계산
        blended_values = []
        valid_count = 0
        for tag in main_tags:
            clean = tag.strip()
            if clean in _PERSON_TAGS or clean not in tag_counts:
                blended_values.append(None)
                continue
            # 전역 IDF
            g_idf = global_idfs.get(clean)
            if g_idf is None:
                blended_values.append(None)
                continue
            # Rating 조건부 IDF
            r_count = tag_counts[clean][ri]
            if r_count > 0:
                r_idf = -math.log2(r_count / rating_total)
                blended = g_idf + alpha * (r_idf - g_idf)
            else:
                # 해당 rating에서 미출현 → 전역 IDF만 사용
                blended = g_idf
            blended_values.append(blended)
            valid_count += 1

        if valid_count < min_valid_count:
            print(f"[Danbooru Auto-Weight] skipped (valid tags={valid_count} < {min_valid_count})")
            return

        # 2단계: 전역 범위 정규화 → 가중치 계산 → 미세 섭동 → 래핑
        weighted_count = 0
        for idx, tag in enumerate(main_tags):
            bv = blended_values[idx]
            if bv is None:
                continue

            norm = max(0.0, min(1.0, (bv - n_low) / n_range))
            if invert:
                norm = 1.0 - norm
            weight = 1.0 + scale * (2 * norm - 1)
            weight = max(min_w, min(max_w, weight))

            if abs(weight - 1.0) < 0.01:
                continue

            # 미세 섭동: 85% 0~2%, 10% 2~5%, 4% 5~8%, 1% 8~10%
            # 각 구간 내에서도 하한 쪽에 편향 (beta 분포 α=1, β=3)
            r = random.random()
            if r < 0.85:
                jitter_mag = random.betavariate(1, 3) * 0.02
            elif r < 0.95:
                jitter_mag = 0.02 + random.betavariate(1, 3) * 0.03
            elif r < 0.99:
                jitter_mag = 0.05 + random.betavariate(1, 3) * 0.03
            else:
                jitter_mag = 0.08 + random.betavariate(1, 3) * 0.02
            jitter = jitter_mag * random.choice((-1, 1))
            weight = weight * (1.0 + jitter)
            weight = max(min_w, min(max_w, weight))

            clean = tag.strip()
            if is_nai:
                main_tags[idx] = f"{weight:.2f}::{clean} ::"
            else:
                main_tags[idx] = f"({clean}:{weight:.2f})"
            weighted_count += 1

        print(f"[Danbooru Auto-Weight] {weighted_count}/{valid_count} tags weighted "
              f"(rating={rating}, mag={mag} [{mag_params['label']}], {min_w}~{max_w})")

    # ── e621 Auto-Boost 코어 (verbatim; Qt highlighter 는 headless 에서 no-op) ──
    def _run_e621_boost(self, context, input_tags: list, target_tags: list):
        """e621 추천을 실행하여 target_tags에 결과를 추가한다."""
        self._refresh_e621_settings()
        try:
            if not hasattr(self, '_e621_recommend'):
                _e621_file = _DATA_DIR / "e621_boost_static.py"
                _spec = importlib.util.spec_from_file_location("e621_boost_static", _e621_file)
                _mod = importlib.util.module_from_spec(_spec)
                _spec.loader.exec_module(_mod)
                self._e621_recommend = _mod.recommend_detailed
            recommend_detailed = self._e621_recommend
            boost_prompt = ", ".join(input_tags)
            print(f"[e621 DEBUG] input tags ({len(input_tags)}): {boost_prompt[:200]}{'...' if len(boost_prompt) > 200 else ''}")
            _mode = self._e621_settings.get("mode", "stable")
            boost_results = recommend_detailed(boost_prompt, top_n=15, diversity_cap=3, mode=_mode)
            print(f"[e621 DEBUG] results ({len(boost_results)}): {[(t, f'{s:.4f}', c) for t, s, c, src in boost_results]}")
            if boost_results:
                # 숨김 태그 필터링
                _hidden = set(self._e621_settings.get("hidden_tags", []))
                boost_tags = [tag.replace("_", " ") for tag, score, cat, src in boost_results
                              if tag not in _PERSON_TAGS and tag not in _hidden]
                # 가중치 래핑
                weight = self._e621_settings.get("weight", 0.0)
                if boost_tags and weight != 0:
                    is_nai = context.settings.get('api_mode') == 'NAI'
                    if is_nai:
                        boost_tags[0] = f"{weight}::" + boost_tags[0]
                        boost_tags[-1] = boost_tags[-1] + " ::"
                    else:
                        boost_tags[0] = "(" + boost_tags[0]
                        boost_tags[-1] = boost_tags[-1] + f":{weight})"
                target_tags.extend(boost_tags)
                context.metadata['e621_boost_tags'] = [
                    {"tag": tag, "score": score, "cat": cat, "src": src}
                    for tag, score, cat, src in boost_results
                ]
                context.metadata['e621_debug_info'] = {
                    'input_tags': input_tags,
                    'results': [
                        {"tag": tag, "score": score, "cat": cat, "src": src}
                        for tag, score, cat, src in boost_results
                    ],
                }
                # headless: main_window/highlighter 없음 → 가드 no-op (데스크톱 패리티 유지)
                main_window = getattr(self.app_context, 'main_window', None) if getattr(self, 'app_context', None) else None
                if main_window and hasattr(main_window, 'main_prompt_highlighter'):
                    main_window.main_prompt_highlighter.set_e621_tags(set(boost_tags))
                print(f"🔥 e621 Auto-Boost: {len(boost_results)} tags added")
        except ImportError:
            print("⚠️ e621_boost_static not found — Auto-Boost skipped")
        except Exception as e:
            print(f"⚠️ e621 Auto-Boost error: {e}")

    # ── after_wildcard 실행 진입점 (verbatim; _update_debug_window 호출만 제거) ──
    def _execute_e621_after_wildcard(self, context) -> 'PromptContext':
        """after_wildcard hook: 와일드카드 단독 + e621 동시 사용 시에만 작동."""
        if '_e621_source_tags' not in context.metadata:
            return context
        _e621_source = context.metadata.pop('_e621_source_tags')
        _e621_input = list(context.prefix_tags) + _e621_source
        self._run_e621_boost(context, _e621_input, context.main_tags)
        # headless: Qt debug window 없음 — debug 는 context.metadata['e621_debug_info'] 로 렌더됨
        return context

    def _execute_danbooru_weight_after_wildcard(self, context) -> 'PromptContext':
        """after_wildcard hook (priority 15): 와일드카드 단독 + Danbooru Auto-Weight 동시 사용 시
        전개된 prefix_tags에 가중치를 in-place 적용. e621(priority 10) 이후에 실행.
        또한, 조건부 프롬프트 등이 main_tags에 추가한 미처리 태그에도 가중치 적용."""
        if '_danbooru_weight_deferred' not in context.metadata:
            # deferred가 아니어도 main_tags 미처리 태그 처리는 수행
            applied = context.metadata.get('_danbooru_weight_applied_tags')
            if applied is not None and context.main_tags:
                self._apply_weight_to_new_main_tags(context, applied)
            return context
        context.metadata.pop('_danbooru_weight_deferred')
        if context.prefix_tags:
            # __wildcard__ 전개 결과가 'tag1, tag2, tag3' 형태의 단일 문자열일 수 있음
            # 개별 태그로 분리하여 in-place 교체
            flat_tags = []
            for tag in context.prefix_tags:
                if ',' in tag:
                    flat_tags.extend(t.strip() for t in tag.split(',') if t.strip())
                else:
                    flat_tags.append(tag)
            context.prefix_tags[:] = flat_tags
            print(f"[Danbooru Auto-Weight] after_wildcard: applying to {len(context.prefix_tags)} prefix_tags")
            self._apply_danbooru_auto_weight(context.prefix_tags, context)
        # main_tags 미처리 태그에도 가중치 적용
        applied = context.metadata.get('_danbooru_weight_applied_tags')
        if applied is not None and context.main_tags:
            self._apply_weight_to_new_main_tags(context, applied)
        return context

    def _apply_weight_to_new_main_tags(self, context, applied_tags: set):
        """main_tags에서 Auto-Weight 미적용 raw 태그를 찾아 가중치 적용.
        이미 가중치 포맷, e621 그룹 래핑 태그는 스킵."""
        # e621 부스트 태그 수집 — 그룹 래핑 간섭 방지
        e621_tags = set()
        for item in context.metadata.get('e621_boost_tags', []):
            e621_tags.add(item['tag'].replace('_', ' '))

        new_tags = []
        in_e621_group = False
        for i, tag in enumerate(context.main_tags):
            clean = tag.strip()
            # 이미 가중치 포맷이면 스킵
            if _WEIGHT_NAI_DETECT.match(clean) or _WEIGHT_WEBUI_DETECT.match(clean):
                continue
            # e621 그룹 래핑 감지: '1.05::tag' (opening) ~ 'tag ::' (closing)
            if clean.endswith('::'):
                in_e621_group = False  # 그룹 종료
                continue
            if re.match(r'^[\d.]+::', clean):
                in_e621_group = True   # 그룹 시작
                continue
            if in_e621_group:
                continue               # 그룹 중간 태그
            # e621 부스트 태그면 스킵 (가중치 0인 경우 래핑 없이 추가됨)
            if clean in e621_tags:
                continue
            # 이미 post_processing에서 처리된 태그면 스킵
            if clean in applied_tags:
                continue
            new_tags.append(i)
        if not new_tags:
            return
        # 미처리 태그만 추출하여 가중치 적용
        temp_tags = [context.main_tags[i] for i in new_tags]
        print(f"[Danbooru Auto-Weight] after_wildcard: applying to {len(temp_tags)} new main_tags")
        self._apply_danbooru_auto_weight(temp_tags, context, min_valid_count=1)
        # 결과를 원래 위치에 반영
        for j, idx in enumerate(new_tags):
            context.main_tags[idx] = temp_tags[j]


def get_headless_prompt_boost_service(app_context: Any) -> "HeadlessPromptBoostService":
    """Return the app-context-cached boost service (created once)."""
    service = getattr(app_context, "headless_prompt_boost_service", None)
    if not isinstance(service, HeadlessPromptBoostService):
        service = HeadlessPromptBoostService(app_context)
        setattr(app_context, "headless_prompt_boost_service", service)
    return service
