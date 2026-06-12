"""Seed Fan-out — NAIA Custom Extension 샘플 (naia_ext_api=1).

Generate 버튼 1회로 여러 장을 큐에 넣는 확장. 두 가지 모드(NAIA 1.5의
"인스턴트 이벤트"에서 포팅):

- **Seed Fan-out**: 동일 프롬프트로 시드만 바꿔 총 N장(원본 포함) 생성.
  시드 방식 = random(매장 새 시드) / +1 / -1(원본 시드 기준 증감) /
  fixed(전부 원본과 같은 시드 — 입력창 와일드카드 변주 비교용).
- **X/Y Plot**: 파라미터 축 1~2개를 조합한 그리드 생성(전부 동일 시드).
  **원본 요청은 자동 취소되어 정확히 그리드 장수만 생성된다.**
  축 종류를 고르면 그에 맞는 입력칸이 나타난다 — CFG Scale·PG.Rescale(값
  범위 "시작,끝,간격") / Sampler("auto"=현재 모드 표준 목록 자동) /
  프롬프트 강조(가중 사다리 — **모드별 문법 자동**: NAI(NAID4/4.5)는
  ``w::키워드::``, WEBUI/COMFYUI는 ``(키워드:w)``) / 프롬프트 스왑(키워드 치환).

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

import random

SEED_SPACE = 10_000_000_000  # 코어 정규화의 randint(0, 9_999_999_999)와 동일 공간
MAX_TOTAL = 16               # Seed Fan-out 모드 총 장수 상한(원본 포함)
MAX_GRID = 32                # X/Y Plot 그리드 상한(폭주 방지)

FEATURE_FANOUT = "Seed Fan-out"
FEATURE_XY = "X/Y Plot"
AXIS_NONE = "None"
AXIS_CFG = "CFG Scale"
AXIS_RESCALE = "PG.Rescale"
AXIS_SAMPLER = "Sampler"
AXIS_EMPHASIS = "프롬프트 강조"
AXIS_SWAP = "프롬프트 스왑"
AXIS_OPTIONS = [AXIS_NONE, AXIS_CFG, AXIS_RESCALE, AXIS_SAMPLER, AXIS_EMPHASIS, AXIS_SWAP]

DEFAULT_SETTINGS = {
    "feature": FEATURE_FANOUT,
    "count": 3,
    "mode": "+1",
    "char_fix": False,
    "x_axis": AXIS_NONE,
    "x_range": "5,7,1",
    "x_samplers": "auto",
    "x_emphasis": "smile,0.6,1.4,0.4",
    "x_swap": "",
    "y_axis": AXIS_NONE,
    "y_range": "0,0.4,0.2",
    "y_samplers": "auto",
    "y_emphasis": "smile,0.6,1.4,0.4",
    "y_swap": "",
}

# 축 종류 → 전용 입력칸 키 접미사(입력칸은 visible_when으로 축 선택에 따라 전환).
AXIS_ARG_SUFFIX = {
    AXIS_CFG: "range",
    AXIS_RESCALE: "range",
    AXIS_SAMPLER: "samplers",
    AXIS_EMPHASIS: "emphasis",
    AXIS_SWAP: "swap",
}

# 모드별 표준 샘플러(UI sampler_options_for_mode 미러) — "auto"가 이 목록을 쓴다.
MODE_SAMPLERS = {
    "NAI": ["k_euler_ancestral", "k_euler", "k_dpmpp_2m", "ddim"],
    "WEBUI": ["Euler a", "Euler", "DPM++ 2M", "DPM++ 2M Karras"],
    "COMFYUI": ["euler", "euler_ancestral", "dpmpp_2m", "dpmpp_sde"],
}


def _float_range(args_text):
    """"시작,끝,간격" → [시작, 시작+간격, ... ≤끝] (소수 2자리 반올림)."""
    parts = [part.strip() for part in str(args_text or "").split(",") if part.strip()]
    start, end, step = float(parts[0]), float(parts[1]), float(parts[2])
    if step <= 0:
        raise ValueError("간격은 양수여야 합니다")
    values = []
    current = start
    while current <= end + 1e-9 and len(values) <= MAX_GRID:
        values.append(round(current, 2))
        current += step
    return values


def _emphasis_values(args_text, api_mode):
    """"키워드,시작,끝,간격"(실수 가중) → [(키워드, 치환문자열)...].

    가중 문법은 모드별 자동: NAI(NAID4/4.5)=``w::키워드::`` 수치 강조,
    WEBUI/COMFYUI=로컬 ``(키워드:w)``."""
    parts = [part.strip() for part in str(args_text or "").split(",")]
    keyword = parts[0]
    if not keyword or len(parts) < 4:
        raise ValueError("키워드,시작,끝,간격 형식이어야 합니다")
    weights = _float_range(",".join(parts[1:4]))
    values = []
    for weight in weights:
        if api_mode == "NAI":
            wrapped = f"{weight:g}::{keyword}::"
        else:
            wrapped = f"({keyword}:{weight:g})"
        values.append((keyword, wrapped))
    return values


def _swap_values(args_text):
    """"키워드,대체1,대체2…" → [(키워드, 대체)...]; 대체 안의 '^'는 ', '로 치환."""
    parts = [part.strip() for part in str(args_text or "").split(",")]
    keyword = parts[0]
    if not keyword or len(parts) < 2:
        raise ValueError("키워드,대체1[,대체2…] 형식이어야 합니다")
    return [(keyword, alt.replace("^", ", ")) for alt in parts[1:] if alt]


class SeedFanout:
    def __init__(self, ctx):
        self.ctx = ctx

    # ── 진입점: 모든 큐 삽입 구독 ────────────────────────────────
    def on_generation_dispatched(self, info):
        if not isinstance(info, dict):
            return
        if info.get("ext_origin"):
            return  # 재귀 가드: 확장 파생 요청에는 절대 다시 반응하지 않는다.
        if str(info.get("source") or "") != "generate":
            return  # 메인 Generate 버튼 경로에만 반응(그 외 경로는 적용 불가).
        settings = self.ctx.load_settings(DEFAULT_SETTINGS)
        params = info.get("params") if isinstance(info.get("params"), dict) else {}

        # 캐릭터 프롬프트 고정(NAI): 지금 1회 전개한 스냅샷을 파생 전 장에 동봉.
        char_overrides = {}
        if settings.get("char_fix") and str(info.get("api_mode") or "") == "NAI":
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
        base = self._base_seed(params.get("seed"))

        # 캐릭터 고정 시 원본을 취소하고 총 N장 전부를 스냅샷 공유 묶음으로 대체
        # — 원본만 캐릭터를 따로 추첨해 묶음과 어긋나는 문제 방지. 취소가 실패하면
        # (이미 실행 시작 등) 기존처럼 원본 유지 + 변형 N-1장으로 폴백.
        replace_original = False
        if char_overrides:
            replace_original = self.ctx.cancel_generation(info.get("request_id")).get("ok", False)
        seeds = self._variant_seeds(base, variants, mode)
        if replace_original:
            seeds = [base] + seeds
        queued = 0
        for seed in seeds:
            result = self._enqueue_clone(info, params, {"seed": seed, **char_overrides})
            queued += 1 if result.get("ok") else 0
        origin_note = "원본 대체(캐릭터 고정)" if replace_original else "원본 1 + 변형"
        self.ctx.log(f"Seed Fan-out: 총 {total}장({origin_note} {queued}/{len(seeds)}, "
                     f"mode={mode}, base={base})")

    @staticmethod
    def _base_seed(raw_seed):
        try:
            base = int(raw_seed)
        except (TypeError, ValueError):
            base = -1
        if base < 0:
            # WEBUI/COMFYUI는 시드가 -1(백엔드 랜덤)으로 남을 수 있다 — base를 추첨.
            base = random.randint(0, SEED_SPACE - 1)
        return base

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
        api_mode = str(info.get("api_mode") or "")
        x_values = self._axis_values("X", settings.get("x_axis"), settings, "x", api_mode)
        y_values = self._axis_values("Y", settings.get("y_axis"), settings, "y", api_mode)
        if x_values is None or y_values is None:
            return  # 축 파싱 실패는 _axis_values가 로그로 안내
        combos = [(x, y) for y in y_values for x in x_values]
        if len(combos) <= 1 and combos and combos[0] == (None, None):
            self.ctx.log("X/Y Plot: 사용할 축이 없습니다 (X/Y 모두 None)")
            return
        if len(combos) > MAX_GRID:
            self.ctx.log(f"X/Y Plot: 조합 {len(combos)}개 → 상한 {MAX_GRID}개로 절단")
            combos = combos[:MAX_GRID]

        # 그리드 비교의 본질: 전 항목 동일 시드(원본 시드 고정).
        base_seed = self._base_seed(params.get("seed"))

        # 셀을 전부 먼저 빌드(키워드 검증 포함)하고, 1장 이상 유효할 때만 원본을
        # 취소한다 — X/Y Plot은 "그리드만" 생성한다(원본까지 N+1장 생성 방지).
        # 전 셀이 무효(키워드 부재 등)면 원본을 건드리지 않는다.
        base_prompt = str(params.get("input") or "")
        cells = []
        for x_value, y_value in combos:
            overrides = {"seed": base_seed, **char_overrides}
            prompt = base_prompt
            ok = True
            for value in (x_value, y_value):
                if value is None:
                    continue
                kind, payload = value
                if kind == "param":
                    overrides[payload[0]] = payload[1]
                elif kind == "prompt":
                    keyword, replacement = payload
                    if keyword not in prompt:
                        self.ctx.log(f"X/Y Plot: 프롬프트에 '{keyword}'가 없어 건너뜀")
                        ok = False
                        break
                    prompt = prompt.replace(keyword, replacement, 1)
            if ok:
                cells.append((overrides, prompt))
        if not cells:
            self.ctx.log("X/Y Plot: 유효한 조합이 없어 원본만 생성합니다")
            return
        cancelled = self.ctx.cancel_generation(info.get("request_id")).get("ok", False)
        queued = 0
        for overrides, prompt in cells:
            result = self._enqueue_clone(info, params, overrides, prompt=prompt)
            queued += 1 if result.get("ok") else 0
        origin_note = "원본 취소, 그리드만" if cancelled else "원본 유지(취소 실패)"
        self.ctx.log(f"X/Y Plot: {queued}/{len(cells)}장 큐 추가 ({origin_note}, seed={base_seed} 고정)")

    def _axis_values(self, axis_name, axis, settings, prefix, api_mode):
        """축 정의 → 조합 항목 리스트. 항목 = None | ("param", (key, value)) |
        ("prompt", (keyword, replacement)). 파싱 실패 시 None(전체 중단).
        인자는 축 종류별 전용 키(x_range/x_samplers/...)에서 읽고, 샘플러/강조는
        api_mode를 따른다(샘플러 "auto"=모드 표준 목록, 강조=모드별 가중 문법)."""
        axis = str(axis or AXIS_NONE)
        if axis == AXIS_NONE:
            return [None]
        args_text = settings.get(f"{prefix}_{AXIS_ARG_SUFFIX.get(axis, 'range')}")
        try:
            if axis == AXIS_CFG:
                return [("param", ("cfg_scale", value)) for value in _float_range(args_text)]
            if axis == AXIS_RESCALE:
                return [("param", ("cfg_rescale", value)) for value in _float_range(args_text)]
            if axis == AXIS_SAMPLER:
                text = str(args_text or "").strip()
                if not text or text.lower() == "auto":
                    samplers = MODE_SAMPLERS.get(api_mode)
                    if not samplers:
                        raise ValueError(f"'{api_mode}' 모드의 표준 샘플러 목록이 없습니다 — 직접 입력하세요")
                else:
                    samplers = [part.strip() for part in text.split(",") if part.strip()]
                if not samplers:
                    raise ValueError("샘플러 콤마 목록이 비었습니다")
                return [("param", ("sampler", sampler)) for sampler in samplers]
            if axis == AXIS_EMPHASIS:
                return [("prompt", pair) for pair in _emphasis_values(args_text, api_mode)]
            if axis == AXIS_SWAP:
                return [("prompt", pair) for pair in _swap_values(args_text)]
        except Exception as exc:
            self.ctx.log(f"X/Y Plot: {axis_name}축({axis}) 인자 해석 실패 — {exc}")
            return None
        return [None]

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


def _axis_fields(prefix, section, base_order, when_xy):
    """축 1개분 패널 필드 — 종류 select + 종류별 전용 입력칸. 입력칸의
    visible_when은 종류 select를 가리키고, 종류 자신은 모드(feature)에 묶여
    있어 모드≠X/Y면 계단식으로 함께 숨는다."""
    axis_key = f"{prefix}_axis"
    common = {"type": "text", "column": "right", "section": section, "apply": "next-generation"}
    return [
        {"key": axis_key, "type": "select", "options": AXIS_OPTIONS, "default": AXIS_NONE,
         "label": "종류", "order": base_order, "visible_when": when_xy,
         "column": "right", "section": section, "apply": "next-generation"},
        {"key": f"{prefix}_range", "default": DEFAULT_SETTINGS[f"{prefix}_range"],
         "label": "값 범위", "placeholder": "시작,끝,간격 — 예: 5,7,1",
         "help": "시작,끝,간격. 예: 5,7,1 → 5·6·7 세 값 = 3장",
         "order": base_order + 1,
         "visible_when": {"field": axis_key, "in": [AXIS_CFG, AXIS_RESCALE]}, **common},
        {"key": f"{prefix}_samplers", "default": DEFAULT_SETTINGS[f"{prefix}_samplers"],
         "label": "샘플러 목록", "placeholder": "auto = 현재 모드 표준 목록",
         "help": "auto면 현재 모드(NAI/WEBUI/COMFYUI)의 표준 샘플러를 자동 나열 — 1개당 1장. "
                 "직접 쉼표 목록 입력도 가능",
         "order": base_order + 2,
         "visible_when": {"field": axis_key, "in": [AXIS_SAMPLER]}, **common},
        {"key": f"{prefix}_emphasis", "default": DEFAULT_SETTINGS[f"{prefix}_emphasis"],
         "label": "강조 사다리", "placeholder": "키워드,시작,끝,간격 — 예: smile,0.6,1.4,0.4",
         "help": "키워드 가중을 시작~끝까지 간격씩 스윕(1장씩). 문법은 모드 자동 — "
                 "NAI(NAID4/4.5)는 w::키워드::, WEBUI/COMFYUI는 (키워드:w). "
                 "예: smile,0.6,1.4,0.4 → 0.6 / 1 / 1.4 3장",
         "order": base_order + 3,
         "visible_when": {"field": axis_key, "in": [AXIS_EMPHASIS]}, **common},
        {"key": f"{prefix}_swap", "default": DEFAULT_SETTINGS[f"{prefix}_swap"],
         "label": "키워드 스왑", "placeholder": "키워드,대체1,대체2 — ^는 콤마",
         "help": "프롬프트 속 키워드를 각 대체값으로 바꿔 1장씩. 대체값 안의 '^'는 콤마로 치환. "
                 "예: blue hair,red hair,blonde hair",
         "order": base_order + 4,
         "visible_when": {"field": axis_key, "in": [AXIS_SWAP]}, **common},
    ]


def register(ctx):
    ext = SeedFanout(ctx)
    ctx.subscribe("generation_request_dispatched", ext.on_generation_dispatched)
    if hasattr(ctx, "register_panel"):
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
                *_axis_fields("x", "X 축", 10, when_xy),
                *_axis_fields("y", "Y 축", 20, when_xy),
            ],
            title="Seed Fan-out",
        )
    ctx.log("ready — Seed Fan-out / X/Y Plot (퀵 버튼 팝업에서 조정, 관리는 Settings ▸ Extension)")
