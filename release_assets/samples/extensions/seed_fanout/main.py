"""Seed Fan-out — NAIA Custom Extension 샘플 (naia_ext_api=1).

Generate 버튼 1회로 여러 장을 큐에 넣는 확장. 두 가지 모드(NAIA 1.5의
"인스턴트 이벤트"에서 포팅):

- **Seed Fan-out**: 동일 프롬프트로 시드만 바꿔 총 N장(원본 포함) 생성.
  시드 방식 = random(매장 새 시드) / +1 / -1(원본 시드 기준 증감) /
  fixed(전부 원본과 같은 시드 — 입력창 와일드카드 변주 비교용).
  WEBUI/COMFYUI에서 원본 시드가 백엔드 랜덤(-1)이면 +1/-1/fixed는 원본을
  취소하고 확정 seed 묶음으로 대체한다(취소 실패 시 중단·토스트).
- **X/Y Plot**: 파라미터 축 1~2개를 조합한 그리드 생성(전부 동일 시드).
  **원본 요청은 자동 취소되어 정확히 그리드 장수만 생성된다.**
  축 종류를 고르면 그에 맞는 입력칸이 나타난다 — CFG Scale·PG.Rescale(NAI 전용, 값
  범위 "시작,끝,간격") / Sampler("auto"=현재 모드 표준 목록 자동) /
  프롬프트 강조(가중 사다리 — **모드별 문법 자동**: NAI(NAID4/4.5)는
  ``w::키워드::``, WEBUI/COMFYUI는 ``(키워드:w)``) / 프롬프트 스왑(키워드 치환).
  **그리드 합성 저장**(기본 ON): 전 셀 완료 시 축 라벨이 붙은 n×m 합성 PNG를
  저장 폴더의 ``grid/`` 아래 생성(NAIA 1.5 인스턴트 이벤트의 그리드 이미지).
  "Grid 폴더 열기" 버튼(action 필드)으로 바로 연다.

공통: **캐릭터 프롬프트 고정**(NAI) — 켜면 fan-out 시점에 캐릭터 설정을 1회
전개한 스냅샷을 묶음 전체가 공유한다(캐릭터 와일드카드 재롤 방지). Seed
Fan-out에서는 원본까지 취소·대체해 **총 N장 전부 같은 캐릭터**가 되게 한다.
끄면 장마다 재전개.

설치: 이 폴더를 user-data의 ``extensions/`` 아래로 복사 → Settings ▸ Extension
에서 활성화. 동작 설정은 퀵 버튼 팝업에서 편집하며 다음 Generate부터 적용.

확장 API 시연 포인트: register_panel의 2단 칼럼(column)·조건부 표시
(visible_when 계단식 — 축 종류별 입력칸 전환)·placeholder/help,
enqueue_generation overrides(시드/CFG/샘플러/캐릭터 스냅샷), ext_origin 재귀
가드, settings.json 라이브 리로드.
"""

import os
import random
import subprocess
import sys
import threading
import time
from pathlib import Path

SEED_SPACE = 10_000_000_000  # 코어 정규화의 randint(0, 9_999_999_999)와 동일 공간
MAX_TOTAL = 16               # Seed Fan-out 모드 총 장수 상한(원본 포함)
MAX_GRID = 32                # X/Y Plot 그리드 상한(폭주 방지)
MAX_PENDING_GRIDS = 3        # 동시 추적 그리드 배치 상한(실패 셀 잔존 대비 GC)
GRID_BATCH_TIMEOUT = 30 * 60 # 실패/취소 셀이 결과 이벤트를 못 보내도 배치를 정리

FEATURE_FANOUT = "Seed Fan-out"
FEATURE_XY = "X/Y Plot"
AXIS_NONE = "None"
AXIS_CFG = "CFG Scale"
AXIS_RESCALE = "PG.Rescale"
AXIS_SAMPLER = "Sampler"
AXIS_EMPHASIS = "프롬프트 강조"
AXIS_SWAP = "프롬프트 스왑"
# PG.Rescale(cfg_rescale)은 NAI 전용 파라미터 — 다른 모드에선 축 옵션에서 제외.
AXIS_OPTIONS_NAI = [AXIS_NONE, AXIS_CFG, AXIS_RESCALE, AXIS_SAMPLER, AXIS_EMPHASIS, AXIS_SWAP]
AXIS_OPTIONS_LOCAL = [AXIS_NONE, AXIS_CFG, AXIS_SAMPLER, AXIS_EMPHASIS, AXIS_SWAP]

DEFAULT_SETTINGS = {
    "feature": FEATURE_FANOUT,
    "count": 3,
    "mode": "+1",
    "char_fix": False,
    "make_grid": True,
    "x_axis": AXIS_NONE,
    "x_range_start": 5.0,
    "x_range_step": 1.0,
    "x_range_end": 7.0,
    "x_samplers_pick": [],
    "x_emph_target": "",
    "x_emph_start": 0.6,
    "x_emph_step": 0.4,
    "x_emph_end": 1.4,
    "x_swap_base": "",
    "x_swap_steps": [],
    "y_axis": AXIS_NONE,
    "y_range_start": 0.0,
    "y_range_step": 0.2,
    "y_range_end": 0.4,
    "y_samplers_pick": [],
    "y_emph_target": "",
    "y_emph_start": 0.6,
    "y_emph_step": 0.4,
    "y_emph_end": 1.4,
    "y_swap_base": "",
    "y_swap_steps": [],
}

# 모드별 표준 샘플러(UI sampler_options_for_mode 미러) — ctx.get_sampler_options를
# 못 쓰는 구런타임 폴백. WEBUI/COMFYUI는 연결 시 실제 백엔드 목록(20+개 가능)이
# ctx.get_sampler_options로 들어오므로 이 표는 미연결/NAI 기본값일 뿐이다.
MODE_SAMPLERS = {
    "NAI": ["k_euler_ancestral", "k_euler", "k_dpmpp_2m", "ddim"],
    "WEBUI": ["Euler a", "Euler", "DPM++ 2M", "DPM++ 2M Karras"],
    "COMFYUI": ["euler", "euler_ancestral", "dpmpp_2m", "dpmpp_sde"],
}


def _sampler_options(ctx, api_mode):
    """현재 모드의 실사용 샘플러 목록 — 호스트 라이브 캐시 우선, 폴백은 표준표."""
    api_mode = str(api_mode or "NAI").upper()
    getter = getattr(ctx, "get_sampler_options", None)
    if callable(getter):
        live = [str(item) for item in (getter() or []) if str(item or "").strip()]
        if live:
            return live
    return MODE_SAMPLERS.get(api_mode, MODE_SAMPLERS["NAI"])


def _float_ladder(start, step, end):
    """시작→종료를 스텝 간격으로 오르는 값 사다리(소수 2자리 반올림).
    검증 실패는 ValueError — 호출자가 토스트로 사용자에게 안내한다."""
    start, step, end = float(start), float(step), float(end)
    if step <= 0:
        raise ValueError("스텝은 양수여야 합니다")
    if end < start:
        raise ValueError("종료 값이 시작 값보다 작습니다")
    values = []
    current = start
    while current <= end + 1e-9 and len(values) < MAX_GRID:
        values.append(round(current, 2))
        current += step
    return values


def _sanitize_settings_for_mode(ctx, settings, api_mode, notify=None, persist=False):
    """NAI-only settings that survived a mode switch are converted to safe no-ops."""
    mode = str(api_mode or "").upper()
    clean = dict(settings or {})
    if mode in ("", "NAI"):
        return clean
    changed = []
    for prefix, label in (("x", "X"), ("y", "Y")):
        key = f"{prefix}_axis"
        if clean.get(key) == AXIS_RESCALE:
            clean[key] = AXIS_NONE
            changed.append(label)
    if changed:
        message = f"{'/'.join(changed)}축 PG.Rescale은 NAI 전용이라 {mode}에서는 None으로 전환했습니다"
        if persist:
            saver = getattr(ctx, "save_settings", None)
            if callable(saver):
                saver(clean)
        if callable(notify):
            notify(message, "warning")
        else:
            logger = getattr(ctx, "log", None)
            if callable(logger):
                logger(message)
    return clean


def _cap_grid_axes(x_values, y_values):
    """Return rectangular axis prefixes whose cell count does not exceed MAX_GRID."""
    x_values = list(x_values or [None])
    y_values = list(y_values or [None])
    original = len(x_values) * len(y_values)
    if original <= MAX_GRID:
        return x_values, y_values, original
    best_cells, best_cols, best_rows = 0, 1, 1
    for rows in range(1, len(y_values) + 1):
        cols = min(len(x_values), MAX_GRID // rows)
        if cols <= 0:
            break
        cells = cols * rows
        if cells > best_cells or (cells == best_cells and cols > best_cols):
            best_cells, best_cols, best_rows = cells, cols, rows
    return x_values[:best_cols], y_values[:best_rows], original


def _wrap_emphasis(keyword, weight, api_mode):
    """가중 문법은 모드별 자동: NAI(NAID4/4.5)=``w::키워드::``,
    WEBUI/COMFYUI=로컬 ``(키워드:w)``."""
    api_mode = str(api_mode or "").upper()
    if api_mode == "NAI":
        return f"{weight:g}::{keyword}::"
    return f"({keyword}:{weight:g})"


def _find_tag_span(prompt, phrase):
    """태그 경계 정렬 매칭 — phrase(쉼표 태그 시퀀스)가 prompt의 태그 경계에서
    연속으로 정확히 일치하는 **첫 위치**의 문자 구간 (start, end)을 돌려준다.
    없으면 None.

    단순 substring 치환의 함정을 막는다: prompt가 "bitter smile, closed mouth,
    smile"일 때 phrase "smile"은 "bitter smile" 안의 부분 문자열이 아니라
    **독립 태그 smile**(세 번째)에 매칭된다. 치환은 prompt[start:end]만 바꾸므로
    주변 공백/서식은 원형 그대로 보존된다."""
    targets = [part.strip() for part in str(phrase or "").split(",") if part.strip()]
    if not targets:
        return None
    text = str(prompt or "")
    segments = []  # (stripped_tag, content_start, content_end)
    pos = 0
    for part in text.split(","):
        stripped = part.strip()
        start = pos + (len(part) - len(part.lstrip()))
        segments.append((stripped, start, start + len(stripped)))
        pos += len(part) + 1  # ',' 포함
    for index in range(len(segments) - len(targets) + 1):
        if all(segments[index + offset][0] == targets[offset] for offset in range(len(targets))):
            return segments[index][1], segments[index + len(targets) - 1][2]
    return None


class SeedFanout:
    def __init__(self, ctx):
        self.ctx = ctx
        # X/Y 그리드 합성 추적: [{ids: {request_id: (col,row)}, cols, rows,
        #  x_labels, y_labels, images: {(col,row): PIL}, expected: set}]
        self._grid_batches = []
        self._grid_lock = threading.Lock()

    def _toast(self, message, level="error"):
        """사용자 안내 — 토스트 브릿지가 있으면 토스트, 없으면 로그."""
        notifier = getattr(self.ctx, "show_toast", None)
        if callable(notifier):
            notifier(message, level)
        else:
            self.ctx.log(message)

    # ── 진입점: 모든 큐 삽입 구독 ────────────────────────────────
    def on_generation_dispatched(self, info):
        if not isinstance(info, dict):
            return
        if info.get("ext_origin"):
            return  # 재귀 가드: 확장 파생 요청에는 절대 다시 반응하지 않는다.
        if str(info.get("source") or "") != "generate":
            return  # 메인 Generate 버튼 경로에만 반응(그 외 경로는 적용 불가).
        api_mode = str(info.get("api_mode") or "").upper()
        settings = self.ctx.load_settings(DEFAULT_SETTINGS)
        settings = _sanitize_settings_for_mode(
            self.ctx,
            settings,
            api_mode,
            notify=self._toast,
            persist=True,
        )
        params = info.get("params") if isinstance(info.get("params"), dict) else {}

        # 캐릭터 프롬프트 고정(NAI): 지금 1회 전개한 스냅샷을 파생 전 장에 동봉.
        char_overrides = {}
        if settings.get("char_fix") and api_mode == "NAI":
            snapshot = self.ctx.resolve_nai_characters()
            if snapshot:
                char_overrides = snapshot
                self.ctx.log(f"캐릭터 프롬프트 고정: {len(snapshot['characters'])}명 스냅샷")

        feature = str(settings.get("feature") or FEATURE_FANOUT)
        if feature == FEATURE_XY:
            self._run_xy_plot(info, params, settings, char_overrides)
        else:
            self._run_fanout(info, params, settings, char_overrides)

    # ── 모드 1: Seed Fan-out ─────────────────────────────────────
    def _run_fanout(self, info, params, settings, char_overrides):
        try:
            total = int(settings.get("count") or 0)
        except (TypeError, ValueError):
            total = 0
        total = max(1, min(total, MAX_TOTAL))
        variants = total - 1  # count = 원본 포함 총 장수
        if variants <= 0:
            return
        mode = str(settings.get("mode") or "+1")
        api_mode = str(info.get("api_mode") or "").upper()
        seed_known = self._known_seed(params.get("seed")) is not None
        base = self._base_seed(params.get("seed"))
        needs_seeded_original = (
            api_mode in {"WEBUI", "COMFYUI"}
            and mode in {"+1", "-1", "fixed"}
            and not seed_known
        )

        # 캐릭터 고정 또는 WEBUI/COMFYUI의 backend-random(-1) 상대 시드 모드에서는
        # 원본을 취소하고 총 N장 전부를 확정된 파생 요청으로 대체한다. 원본이 -1로
        # 그대로 실행되면 +1/-1/fixed가 "원본 시드 기준"이라는 계약을 지킬 수 없다.
        replace_original = False
        if char_overrides or needs_seeded_original:
            cancel = self.ctx.cancel_generation(info.get("request_id"))
            replace_original = bool(cancel.get("ok") or cancel.get("skip_scheduled"))
            if needs_seeded_original and not replace_original:
                self._toast(
                    f"{api_mode} {mode} 시드 방식은 원본 -1 시드를 알 수 없어 "
                    "원본 대체가 필요합니다. 원본 취소 실패로 fan-out을 중단합니다.",
                    "error",
                )
                return
        seeds = self._variant_seeds(base, variants, mode)
        if replace_original:
            seeds = [base] + seeds
        queued = 0
        for seed in seeds:
            result = self._enqueue_clone(info, params, {"seed": seed, **char_overrides})
            queued += 1 if result.get("ok") else 0
        if replace_original and char_overrides:
            origin_note = "원본 대체(캐릭터 고정)"
        elif replace_original:
            origin_note = "원본 대체(시드 확정)"
        else:
            origin_note = "원본 1 + 변형"
        self.ctx.log(f"Seed Fan-out: 총 {total}장({origin_note} {queued}/{len(seeds)}, "
                     f"mode={mode}, base={base})")

    @staticmethod
    def _known_seed(raw_seed):
        try:
            seed = int(raw_seed)
        except (TypeError, ValueError):
            return None
        return seed if seed >= 0 else None

    @classmethod
    def _base_seed(cls, raw_seed):
        seed = cls._known_seed(raw_seed)
        if seed is not None:
            return seed
        # WEBUI/COMFYUI는 시드가 -1(백엔드 랜덤)으로 남을 수 있다 — 대체 원본용
        # 확정 base를 추첨하고, 필요한 모드에서는 원본을 취소한 뒤 이 seed로 재큐잉.
        return random.randint(0, SEED_SPACE - 1)

    @staticmethod
    def _variant_seeds(base, count, mode):
        if mode == "random":
            return [random.randint(0, SEED_SPACE - 1) for _ in range(count)]
        if mode == "fixed":
            return [base] * count  # 동일 시드 — 입력창 와일드카드 변주 비교용
        step = -1 if mode == "-1" else 1
        return [(base + step * i) % SEED_SPACE for i in range(1, count + 1)]

    # ── 모드 2: X/Y Plot (인스턴트 이벤트 포팅) ──────────────────
    def _run_xy_plot(self, info, params, settings, char_overrides):
        api_mode = str(info.get("api_mode") or "").upper()
        x_meta = self._axis_values("X", settings.get("x_axis"), settings, "x", api_mode)
        y_meta = self._axis_values("Y", settings.get("y_axis"), settings, "y", api_mode)
        if x_meta is None or y_meta is None:
            return  # 축 파싱 실패는 _axis_values가 로그로 안내
        x_values, x_title = x_meta
        y_values, y_title = y_meta
        x_values, y_values, original_combo_count = _cap_grid_axes(x_values, y_values)
        combos = [(x, y) for y in y_values for x in x_values]
        if len(combos) <= 1 and combos and combos[0] == (None, None):
            self.ctx.log("X/Y Plot: 사용할 축이 없습니다 (X/Y 모두 None)")
            return
        if original_combo_count > len(combos):
            self.ctx.log(
                f"X/Y Plot: 조합 {original_combo_count}개 → "
                f"{len(combos)}개({len(x_values)}x{len(y_values)}) 직사각형으로 절단"
            )

        # 프롬프트 치환 축의 시작/원본 프롬프트가 실제 프롬프트에 **태그 경계로**
        # 존재하는지 선검증 — 없으면 토스트로 안내하고 전체 중단(원본만 생성).
        # substring이 아니라 태그 시퀀스 매칭이다: "smile"은 "bitter smile" 안이
        # 아니라 독립 태그 smile에만 매칭된다. 두 축 모두 프롬프트 축이면 span을
        # base 기준으로 잡고 겹침을 거부한다(Codex R6-#1: X 치환 결과를 Y가
        # 다시 잡는 오염 방지 — 셀 빌드도 같은 base span을 쓴다).
        base_prompt = str(params.get("input") or "")
        axis_spans = []  # 프롬프트 축의 (키워드, base 기준 span) — 축 순서 X, Y
        for axis_values in (x_values, y_values):
            for item in axis_values:
                if item is None or item[0] != "prompt":
                    continue
                keyword = item[1][0]
                span = _find_tag_span(base_prompt, keyword) if keyword else None
                if span is None:
                    self._toast(f'"{keyword}" — 시작 프롬프트가 프롬프트에 없습니다(태그 단위 일치 기준)')
                    return
                axis_spans.append(span)
                break  # 축의 키워드는 동일 — 첫 항목만 보면 충분
        if len(axis_spans) == 2:
            (s1, e1), (s2, e2) = axis_spans
            if not (e1 <= s2 or e2 <= s1):
                self._toast("X·Y 축의 시작/원본 프롬프트 구간이 겹칩니다 — 서로 다른 구간을 지정하세요")
                return

        # 그리드 비교의 본질: 전 항목 동일 시드(원본 시드 고정).
        base_seed = self._base_seed(params.get("seed"))

        # 셀을 전부 먼저 빌드(키워드 검증 포함)하고, 1장 이상 유효할 때만 원본을
        # 취소한다 — X/Y Plot은 "그리드만" 생성한다(원본까지 N+1장 생성 방지).
        # 전 셀이 무효(키워드 부재 등)면 원본을 건드리지 않는다.
        cols = len(x_values)
        cells = []
        for index, (x_value, y_value) in enumerate(combos):
            overrides = {"seed": base_seed, **char_overrides}
            ok = True
            # 프롬프트 치환은 전부 base_prompt 기준 span으로 모은 뒤 뒤 구간부터
            # 적용한다 — X의 교체 결과 안에서 Y가 다시 매칭되는 오염 방지(R6-#1).
            prompt_ops = []
            for value in (x_value, y_value):
                if value is None:
                    continue
                kind, payload = value[0], value[1]
                if kind == "param":
                    overrides[payload[0]] = payload[1]
                elif kind == "prompt":
                    keyword, replacement = payload
                    span = _find_tag_span(base_prompt, keyword)
                    if span is None:
                        self.ctx.log(f"X/Y Plot: 프롬프트에 태그 '{keyword}'가 없어 건너뜀")
                        ok = False
                        break
                    prompt_ops.append((span, replacement))
            if not ok:
                continue
            prompt = base_prompt
            for (start, end), replacement in sorted(prompt_ops, key=lambda op: op[0][0], reverse=True):
                prompt = prompt[:start] + replacement + prompt[end:]
            cells.append((overrides, prompt, index % cols, index // cols))
        if not cells:
            self.ctx.log("X/Y Plot: 유효한 조합이 없어 원본만 생성합니다")
            return
        cancel = self.ctx.cancel_generation(info.get("request_id"))
        if not (cancel.get("ok") or cancel.get("skip_scheduled")):
            self._toast(
                "X/Y Plot은 그리드 전용 생성이라 원본 취소가 필요합니다. "
                "원본 취소 실패로 그리드 큐 추가를 중단합니다.",
                "error",
            )
            return
        queued = 0
        id_map = {}
        for overrides, prompt, col, row in cells:
            result = self._enqueue_clone(info, params, overrides, prompt=prompt)
            if result.get("ok"):
                queued += 1
                if result.get("request_id"):
                    id_map[result["request_id"]] = (col, row)
        failed_tracking = len(cells) - len(id_map)
        if cancel.get("ok"):
            origin_note = "원본 취소, 그리드만"
        elif cancel.get("skip_scheduled"):
            origin_note = "원본 건너뛰기 예약, 그리드만"
        self.ctx.log(f"X/Y Plot: {queued}/{len(cells)}장 큐 추가 ({origin_note}, seed={base_seed} 고정)")

        # n×m 합성 이미지: 전 셀 완료 시 grid/ 폴더에 저장(설정으로 끌 수 있음).
        if settings.get("make_grid"):
            if failed_tracking:
                self.ctx.log(f"그리드 합성 생략: 추적 불가/큐 추가 실패 셀 {failed_tracking}개")
            elif id_map:
                batch = {
                    "ids": id_map,
                    "cols": cols,
                    "rows": len(y_values),
                    # 라벨=축 값(가중치/샘플러명 등), 타이틀=축 종류(+키워드) —
                    # WEBUI/NAIA 1.5 그리드처럼 축 타이틀 밴드를 따로 확보한다.
                    "x_labels": [value[2] if value else "" for value in x_values],
                    "y_labels": [value[2] if value else "" for value in y_values],
                    "x_title": x_title,
                    "y_title": y_title,
                    "images": {},
                    "failed": 0,
                    "expected": set(id_map.keys()),
                }
                self._track_grid_batch(batch)

    def _track_grid_batch(self, batch):
        timer = threading.Timer(GRID_BATCH_TIMEOUT, self._expire_grid_batch, args=(batch,))
        timer.daemon = True
        batch["timer"] = timer
        dropped_batches = []
        with self._grid_lock:
            self._grid_batches.append(batch)
            while len(self._grid_batches) > MAX_PENDING_GRIDS:
                dropped_batches.append(self._grid_batches.pop(0))
        for dropped in dropped_batches:
            self._cancel_grid_timer(dropped)
            self.ctx.log(f"그리드 추적 GC: 미완료 배치 폐기({len(dropped['expected'])}셀 미수신)")
        timer.start()

    @staticmethod
    def _cancel_grid_timer(batch):
        timer = batch.get("timer") if isinstance(batch, dict) else None
        if timer is not None:
            try:
                timer.cancel()
            except Exception:
                pass

    def _expire_grid_batch(self, batch):
        with self._grid_lock:
            if batch not in self._grid_batches:
                return
            self._grid_batches.remove(batch)
            missing = len(batch.get("expected") or [])
            received = len(batch.get("images") or {})
        self.ctx.log(
            f"그리드 배치 만료: {missing}셀 미완료, {received}셀 수신 — 합성 취소"
        )

    # ── 그리드 합성: 결과 이벤트 수집 → 전 셀 완료 시 PNG 저장 ──
    def on_generation_result(self, info):
        if not isinstance(info, dict):
            return
        rid = str(info.get("request_id") or "")
        if not rid:
            return
        with self._grid_lock:
            batch = next((item for item in self._grid_batches if rid in item["expected"]), None)
        if batch is None:
            return  # 우리 그리드 셀이 아님
        fetched = self.ctx.get_result_image(rid)
        with self._grid_lock:
            if batch not in self._grid_batches:
                return
            batch["expected"].discard(rid)
            if fetched.get("ok"):
                batch["images"][batch["ids"][rid]] = fetched["image"]
            else:
                batch["failed"] = int(batch.get("failed") or 0) + 1
                self.ctx.log(f"그리드 셀 회수 실패({rid[:8]}): {fetched.get('message')}")
            done = not batch["expected"]
            if done:
                self._grid_batches.remove(batch)
                self._cancel_grid_timer(batch)
        if done and batch.get("failed"):
            self.ctx.log(f"그리드 합성 생략: 결과 이미지 수신 실패 {batch['failed']}셀")
            return
        if done and batch["images"]:
            try:
                path = self._compose_and_save(batch)
                if path:
                    self.ctx.log(f"그리드 저장: {path}")
            except Exception as exc:
                self.ctx.log(f"그리드 합성 실패: {exc}")

    def _compose_and_save(self, batch):
        from PIL import Image, ImageDraw, ImageFont

        images = batch["images"]
        cell_w = max(image.width for image in images.values())
        cell_h = max(image.height for image in images.values())
        cols, rows = batch["cols"], batch["rows"]
        gutter = 6
        bg = (16, 16, 22)
        title_color = (157, 139, 255)   # NAIA accent-light — 축 타이틀
        label_color = (220, 220, 235)
        # 밴드 구성(WEBUI/NAIA 1.5식): 축 타이틀 공간을 값 라벨과 별도로 확보.
        # 상단 = X 타이틀(28) + X 값 라벨(34), 좌측 = Y 타이틀(28, 세로 회전) +
        # Y 값 라벨(150). 해당 축이 없으면 0.
        title_band = 28
        x_title = str(batch.get("x_title") or "")
        y_title = str(batch.get("y_title") or "")
        top_title = title_band if x_title else 0
        top_labels = 34 if any(batch["x_labels"]) else 0
        left_title = title_band if y_title else 0
        left_labels = 150 if any(batch["y_labels"]) else 0
        top_band = top_title + top_labels
        left_band = left_title + left_labels
        grid_w = cols * (cell_w + gutter) + gutter
        grid_h = rows * (cell_h + gutter) + gutter
        width = left_band + grid_w
        height = top_band + grid_h
        canvas = Image.new("RGB", (width, height), bg)
        draw = ImageDraw.Draw(canvas)
        try:
            font = ImageFont.truetype("malgun.ttf", 20)  # Windows 한글 폰트, 실패 시 기본
        except Exception:
            font = ImageFont.load_default()
        for (col, row), image in images.items():
            canvas.paste(image, (left_band + gutter + col * (cell_w + gutter),
                                 top_band + gutter + row * (cell_h + gutter)))
        if x_title:
            draw.text((left_band + grid_w // 2, top_title // 2), x_title[:80],
                      fill=title_color, font=font, anchor="mm")
        for col, label in enumerate(batch["x_labels"]):
            if label:
                x_center = left_band + gutter + col * (cell_w + gutter) + cell_w // 2
                draw.text((x_center, top_title + top_labels // 2), label[:60],
                          fill=label_color, font=font, anchor="mm")
        if y_title:
            # 세로 축 타이틀: 가로로 그린 띠를 90° 회전해 좌측 끝에 부착.
            strip = Image.new("RGB", (grid_h, title_band), bg)
            strip_draw = ImageDraw.Draw(strip)
            strip_draw.text((grid_h // 2, title_band // 2), y_title[:80],
                            fill=title_color, font=font, anchor="mm")
            canvas.paste(strip.rotate(90, expand=True), (0, top_band))
        for row, label in enumerate(batch["y_labels"]):
            if label:
                y_center = top_band + gutter + row * (cell_h + gutter) + cell_h // 2
                draw.text((left_title + 8, y_center), label[:24],
                          fill=label_color, font=font, anchor="lm")
        grid_dir = self._grid_dir()
        if grid_dir is None:
            self.ctx.log("그리드 저장 실패: 저장 디렉터리를 알 수 없습니다")
            return None
        path = self._unique_grid_path(grid_dir, cols, rows)
        canvas.save(path, format="PNG")
        return str(path)

    @staticmethod
    def _unique_grid_path(grid_dir, cols, rows):
        stem = f"grid_{time.strftime('%Y%m%d_%H%M%S')}_{time.time_ns() % 1_000_000_000:09d}_{cols}x{rows}"
        path = grid_dir / f"{stem}.png"
        index = 1
        while path.exists():
            path = grid_dir / f"{stem}_{index}.png"
            index += 1
        return path

    def _grid_dir(self):
        base = self.ctx.get_save_directory()
        if not base:
            return None
        grid_dir = Path(base) / "grid"
        grid_dir.mkdir(parents=True, exist_ok=True)
        return grid_dir

    # ── 패널 action 버튼 ─────────────────────────────────────────
    def on_action(self, key):
        if key != "open_grid_folder":
            return
        grid_dir = self._grid_dir()
        if grid_dir is None:
            self.ctx.log("Grid 폴더를 열 수 없습니다: 저장 디렉터리를 알 수 없습니다")
            return
        try:
            if sys.platform == "win32":
                os.startfile(str(grid_dir))  # noqa: S606 — 로컬 폴더 열기(사용자 액션)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(grid_dir)])
            else:
                subprocess.Popen(["xdg-open", str(grid_dir)])
            self.ctx.log(f"Grid 폴더 열기: {grid_dir}")
        except Exception as exc:
            self.ctx.log(f"Grid 폴더 열기 실패: {exc}")

    def _axis_values(self, axis_name, axis, settings, prefix, api_mode):
        """축 정의 → (조합 항목 리스트, 축 타이틀). 항목 = None |
        ("param", (key, value), 라벨) | ("prompt", (keyword, replacement), 라벨).
        검증 실패 시 None(전체 중단) — 사용자에겐 토스트로 사유 안내.
        타이틀은 축 종류(+대상) — 그리드 Axis Title 밴드(WEBUI/1.5식)가 쓴다."""
        axis = str(axis or AXIS_NONE)
        if axis == AXIS_NONE:
            return ([None], "")
        try:
            if axis in (AXIS_CFG, AXIS_RESCALE):
                if axis == AXIS_RESCALE and api_mode != "NAI":
                    self._toast(f"{axis_name}축 PG.Rescale은 NAI 전용입니다 — 다른 축을 선택하세요")
                    return None
                values = _float_ladder(
                    settings.get(f"{prefix}_range_start"),
                    settings.get(f"{prefix}_range_step"),
                    settings.get(f"{prefix}_range_end"),
                )
                param_key = "cfg_scale" if axis == AXIS_CFG else "cfg_rescale"
                return ([("param", (param_key, value), f"{value:g}") for value in values],
                        "CFG Scale" if axis == AXIS_CFG else "PG.Rescale")
            if axis == AXIS_SAMPLER:
                # 실사용 샘플러 목록(라이브 캐시 우선)에서 고른 것만 — 선택 수 = 생성 수.
                picked = settings.get(f"{prefix}_samplers_pick")
                picked = [str(item) for item in picked] if isinstance(picked, (list, tuple)) else []
                available = _sampler_options(self.ctx, api_mode)
                if available:
                    picked = [item for item in picked if item in available]
                if not picked:
                    self._toast(f"{axis_name}축 Sampler: 샘플러를 1개 이상 선택하세요")
                    return None
                return ([("param", ("sampler", sampler), sampler) for sampler in picked], "Sampler")
            if axis == AXIS_EMPHASIS:
                # 원본 프롬프트(정확 매칭·쉼표 허용) + 시작/스텝/종료 가중치 — 전부 필수.
                target = str(settings.get(f"{prefix}_emph_target") or "").strip()
                if not target:
                    self._toast(f"{axis_name}축 강조 사다리: 원본 프롬프트를 입력하세요(모든 칸 필수)")
                    return None
                weights = _float_ladder(
                    settings.get(f"{prefix}_emph_start"),
                    settings.get(f"{prefix}_emph_step"),
                    settings.get(f"{prefix}_emph_end"),
                )
                items = [("prompt", (target, _wrap_emphasis(target, weight, api_mode)), f"{weight:g}")
                         for weight in weights]
                return (items, f"프롬프트 강조 · {target[:16]}")
            if axis == AXIS_SWAP:
                # 시작 프롬프트 + Step 대치 프롬프트들(빌더) — 전부 필수.
                base = str(settings.get(f"{prefix}_swap_base") or "").strip()
                steps_raw = settings.get(f"{prefix}_swap_steps")
                steps = [str(item).strip() for item in steps_raw] if isinstance(steps_raw, (list, tuple)) else []
                steps = [item for item in steps if item]
                if not base or not steps:
                    self._toast(f"{axis_name}축 프롬프트 스왑: 시작 프롬프트와 Step을 모두 채워주세요")
                    return None
                # 시작 프롬프트(원본·미치환)를 첫 셀로 포함 → 시작→step1→step2처럼
                # 기준선 1장이 함께 나온다(다른 축의 시작값과 동일한 감각). (base→base)는
                # 항등 치환이라 프롬프트가 그대로 유지된다.
                return ([("prompt", (base, base), "원본")]
                        + [("prompt", (base, step), step) for step in steps],
                        f"프롬프트 스왑 · {base[:16]}")
        except Exception as exc:
            self._toast(f"X/Y Plot {axis_name}축({axis}) 설정 해석 실패 — {exc}")
            return None
        return ([None], "")

    # ── 공통: 원본 복제 enqueue ──────────────────────────────────
    def _enqueue_clone(self, info, params, overrides, prompt=None):
        merged = {
            "width": params.get("width"),
            "height": params.get("height"),
            **overrides,
        }
        result = self.ctx.enqueue_generation(
            prompt=prompt if prompt is not None else params.get("input"),
            negative_prompt=params.get("negative_prompt"),
            api_mode=info.get("api_mode"),
            prompt_run_id=info.get("prompt_run_id"),
            overrides=merged,
        )
        if not result.get("ok"):
            self.ctx.log(f"enqueue 거부: {result.get('message')}")
        return result


def _axis_fields(prefix, section, base_order, when_xy, samplers, axis_options):
    """축 1개분 패널 필드 — 종류 select + 종류별 전용 입력칸. 입력칸의
    visible_when은 종류 select를 가리키고, 종류 자신은 모드(feature)에 묶여
    있어 모드≠X/Y면 계단식으로 함께 숨는다. 스왑은 3번째 칼럼(extra)에
    [시작 프롬프트]+[Step n 대치 프롬프트]+[추가+] 빌더로 펼쳐진다.
    axis_options는 모드별(PG.Rescale은 NAI 전용)."""
    axis_key = f"{prefix}_axis"
    common = {"column": "right", "section": section, "apply": "next-generation"}
    when_range = {"field": axis_key, "in": [AXIS_CFG, AXIS_RESCALE]}
    when_emph = {"field": axis_key, "in": [AXIS_EMPHASIS]}
    when_swap = {"field": axis_key, "in": [AXIS_SWAP]}
    return [
        {"key": axis_key, "type": "select", "options": axis_options, "default": AXIS_NONE,
         "label": "종류", "order": base_order, "visible_when": when_xy, **common},
        # ── CFG Scale · PG.Rescale: 시작/스텝/종료 3칸(강조 사다리와 동일 UI) ──
        {"key": f"{prefix}_range_start", "type": "float",
         "default": DEFAULT_SETTINGS[f"{prefix}_range_start"], "step": 0.5,
         "label": "시작 값", "order": base_order + 1, "visible_when": when_range, **common},
        {"key": f"{prefix}_range_step", "type": "float",
         "default": DEFAULT_SETTINGS[f"{prefix}_range_step"], "min": 0.05, "step": 0.05,
         "label": "값 스텝", "order": base_order + 2, "visible_when": when_range, **common},
        {"key": f"{prefix}_range_end", "type": "float",
         "default": DEFAULT_SETTINGS[f"{prefix}_range_end"], "step": 0.5,
         "label": "종료 값", "help": "시작→종료를 스텝 간격으로 1장씩(상한 32)",
         "order": base_order + 3, "visible_when": when_range, **common},
        {"key": f"{prefix}_samplers_pick", "type": "multiselect", "options": samplers,
         "default": [], "label": "샘플러 선택",
         "help": "콤보박스로 추가, 칩의 ×로 제거 — 1개당 1장(선택 수 = 생성 수). "
                 "WEBUI/COMFYUI는 연결 시 실제 백엔드 샘플러 목록으로 갱신",
         "order": base_order + 4,
         "visible_when": {"field": axis_key, "in": [AXIS_SAMPLER]}, **common},
        # ── 강조 사다리: 원본 프롬프트(쉼표 허용) + 시작/스텝/종료 — 전부 필수 ──
        {"key": f"{prefix}_emph_target", "type": "text", "multiline": True, "default": "",
         "label": "원본 프롬프트", "placeholder": "태그 단위 정확 매칭 — 쉼표 포함 긴 구문 가능",
         "help": "프롬프트 창에 존재하는 태그(시퀀스)를 그대로 입력 — 매칭은 태그 경계 기준"
                 "(smile은 bitter smile 안이 아니라 독립 태그 smile에만 일치). "
                 "이 구간에 가중을 입혀 1장씩 생성 — 문법은 모드 자동(NAI w::…::, 로컬 (…:w))",
         "order": base_order + 5, "visible_when": when_emph, **common},
        {"key": f"{prefix}_emph_start", "type": "float", "default": 0.6, "step": 0.1,
         "label": "시작 가중치", "order": base_order + 6, "visible_when": when_emph, **common},
        {"key": f"{prefix}_emph_step", "type": "float", "default": 0.4, "min": 0.05, "step": 0.05,
         "label": "가중치 스텝", "order": base_order + 7, "visible_when": when_emph, **common},
        {"key": f"{prefix}_emph_end", "type": "float", "default": 1.4, "step": 0.1,
         "label": "종료 가중치", "order": base_order + 8, "visible_when": when_emph, **common},
        # ── 프롬프트 스왑: 3번째 칼럼(extra) 빌더 ──
        {"key": f"{prefix}_swap_base", "type": "text", "multiline": True, "default": "",
         "label": "시작 프롬프트", "placeholder": "프롬프트 창에 존재하는 태그(시퀀스) — 쉼표 포함 긴 구문 가능",
         "help": "프롬프트 창의 이 구간을 아래 Step들로 바꿔 1장씩 생성. 매칭은 태그 경계 기준"
                 "(smile은 bitter smile 안이 아니라 독립 태그 smile에만 일치). "
                 "프롬프트에 없으면 토스트로 안내하고 중단",
         "column": "extra", "section": f"{section} · 프롬프트 스왑", "apply": "next-generation",
         "order": base_order + 9, "visible_when": when_swap},
        {"key": f"{prefix}_swap_steps", "type": "list", "multiline": True, "default": [],
         "label": "대치할 프롬프트", "placeholder": "이 내용으로 교체 — 쉼표 포함 긴 구문 가능",
         "help": "Step 1개당 1장 — [추가 +]로 늘리고 ×로 제거. "
                 "\"spread legs, pen, the pen glides across warm skin\" 같은 구문 전체 가능",
         "column": "extra", "section": f"{section} · 프롬프트 스왑", "apply": "next-generation",
         "order": base_order + 10, "visible_when": when_swap},
    ]


def _register_panel(ctx, ext):
    """패널 (재)등록 — 샘플러 선택지는 현재 API 모드 목록을 따른다.
    api_mode_changed 구독으로 모드 전환 시 다시 호출된다."""
    if not hasattr(ctx, "register_panel"):
        return
    mode = ""
    if hasattr(ctx, "get_api_mode"):
        mode = str(ctx.get_api_mode() or "").upper()
    _sanitize_settings_for_mode(
        ctx,
        ctx.load_settings(DEFAULT_SETTINGS) if hasattr(ctx, "load_settings") else DEFAULT_SETTINGS,
        mode or "NAI",
        persist=True,
    )
    # 실사용 샘플러(라이브 캐시 우선 — WEBUI/COMFYUI 연결 시 실제 백엔드 목록).
    samplers = _sampler_options(ctx, mode or "NAI")
    # PG.Rescale은 NAI 전용 — 다른 모드에선 축 선택지에서 제외(모드 미상=NAI 간주).
    axis_options = AXIS_OPTIONS_NAI if mode in ("", "NAI") else AXIS_OPTIONS_LOCAL
    when_fanout = {"field": "feature", "in": [FEATURE_FANOUT]}
    when_xy = {"field": "feature", "in": [FEATURE_XY]}
    ctx.register_panel(
        fields=[
            {"key": "feature", "type": "select", "options": [FEATURE_FANOUT, FEATURE_XY],
             "default": FEATURE_FANOUT, "label": "모드", "order": 0,
             "apply": "next-generation",
             "help": "Seed Fan-out=시드 변형 n장 · X/Y Plot=파라미터 그리드(인스턴트 이벤트)"},
            {"key": "count", "type": "int", "min": 1, "max": MAX_TOTAL,
             "default": DEFAULT_SETTINGS["count"], "label": "생성 수",
             "help": "Generate 1회당 총 장수(원본 포함). 1이면 추가 생성 없음",
             "apply": "next-generation", "order": 1, "visible_when": when_fanout},
            {"key": "mode", "type": "select", "options": ["random", "+1", "-1", "fixed"],
             "default": DEFAULT_SETTINGS["mode"], "label": "시드 방식",
             "help": "fixed=전부 원본과 같은 시드(와일드카드 변주 비교용)",
             "apply": "next-generation", "order": 2, "visible_when": when_fanout},
            {"key": "char_fix", "type": "bool", "default": False,
             "label": "캐릭터 프롬프트 고정",
             "help": "NAI 전용. 켜면 묶음 전체(원본 포함)가 지금 1회 전개한 캐릭터 "
                     "스냅샷을 공유(캐릭터 와일드카드 재롤 방지). 끄면 장마다 재전개",
             "apply": "next-generation", "order": 3},
            # ── X/Y Plot (복잡 모드 → 우측 칼럼, 축 종류별 입력칸 전환) ──
            *_axis_fields("x", "X 축", 10, when_xy, samplers, axis_options),
            *_axis_fields("y", "Y 축", 30, when_xy, samplers, axis_options),
            {"key": "make_grid", "type": "bool", "default": True,
             "label": "그리드 합성 저장",
             "help": "전 셀 완료 시 n×m 합성 PNG를 저장 폴더의 grid/ 아래 생성"
                     "(축 타이틀·값 라벨 포함)",
             "column": "right", "section": "그리드 이미지", "order": 50,
             "apply": "next-generation", "visible_when": when_xy},
            {"key": "open_grid_folder", "type": "action", "label": "Grid 폴더 열기",
             "help": "저장 폴더/grid 를 파일 탐색기로 연다(서버 기기 기준)",
             "column": "right", "section": "그리드 이미지", "order": 51,
             "visible_when": when_xy},
        ],
        title="여러장 생성-X/Y Plot",
        on_action=ext.on_action,
    )


def register(ctx):
    ext = SeedFanout(ctx)
    ctx.subscribe("generation_request_dispatched", ext.on_generation_dispatched)
    ctx.subscribe("generation_result_available", ext.on_generation_result)
    # 모드 전환·라이브 옵션 갱신(WEBUI/COMFYUI 연결) 시 샘플러 선택지 재등록.
    # run_when_disarmed: 작동 OFF여도 패널은 노출되므로 선택지 갱신은 돌아야
    # 한다(UI 메타 전용 — 생성 개입 없음).
    refresh = lambda _payload: _register_panel(ctx, ext)  # noqa: E731
    try:
        ctx.subscribe("api_mode_changed", refresh, run_when_disarmed=True)
        ctx.subscribe("api_options_refreshed", refresh, run_when_disarmed=True)
    except TypeError:  # 구런타임(옵션 미지원) 폴백
        ctx.subscribe("api_mode_changed", refresh)
        ctx.subscribe("api_options_refreshed", refresh)
    _register_panel(ctx, ext)
    ctx.log("ready — 여러장 생성-X/Y Plot (퀵 버튼 팝업에서 조정, 관리는 Settings ▸ Extension)")
