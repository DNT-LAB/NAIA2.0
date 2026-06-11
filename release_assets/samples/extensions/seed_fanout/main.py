"""Seed Fan-out — NAIA Custom Extension 샘플 (naia_ext_api=1).

Generate 버튼 1회로 여러 장을 큐에 넣는 확장. 두 가지 모드(NAIA 1.5의
"인스턴트 이벤트"에서 포팅):

- **Seed Fan-out**: 동일 프롬프트로 시드만 바꿔 총 N장(원본 포함) 생성.
  시드 방식 = random(매장 새 시드) / +1 / -1(원본 시드 기준 증감) /
  fixed(전부 원본과 같은 시드 — 입력창 와일드카드 변주 비교용).
- **X/Y Plot**: 파라미터 축 1~2개를 조합한 그리드 생성(전부 동일 시드).
  축: CFG Scale · PG.Rescale("시작,끝,간격") / Sampler("콤마 목록") /
  프롬프트 강조("키워드,시작,끝,간격" — {{kw}}/[kw] 가중 스윕) /
  프롬프트 스왑("키워드,대체1,대체2…" — '^'는 콤마로 치환).

공통: **캐릭터 프롬프트 고정**(NAI) — 켜면 fan-out 시점에 캐릭터 설정을 1회
전개한 스냅샷을 모든 파생 장에 동봉한다(캐릭터 프롬프트에 와일드카드가 있어도
파생 장들끼리 동일; 원본 1장은 자체 실행 시 별도 전개). 끄면 장마다 재전개.

설치: 이 폴더를 user-data의 ``extensions/`` 아래로 복사 → Settings ▸ Extension
에서 활성화. 설정은 패널(또는 퀵 팝업)에서 편집하며 다음 Generate부터 적용.

확장 API 시연 포인트: register_panel의 2단 칼럼(column)·조건부 표시
(visible_when), enqueue_generation overrides(시드/CFG/샘플러/캐릭터 스냅샷),
ext_origin 재귀 가드, settings.json 라이브 리로드.
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
    "x_args": "",
    "y_axis": AXIS_NONE,
    "y_args": "",
}


def _float_range(args_text):
    """"시작,끝,간격" → [시작, 시작+간격, ... ≤끝] (소수 1자리 반올림)."""
    parts = [part.strip() for part in str(args_text or "").split(",") if part.strip()]
    start, end, step = float(parts[0]), float(parts[1]), float(parts[2])
    if step <= 0:
        raise ValueError("간격은 양수여야 합니다")
    values = []
    current = start
    while current <= end + 1e-9 and len(values) <= MAX_GRID:
        values.append(round(current, 1))
        current += step
    return values


def _emphasis_values(args_text):
    """"키워드,시작,끝,간격"(정수) → [(라벨, 치환문자열)...] — i<0 [kw], i>0 {kw}."""
    parts = [part.strip() for part in str(args_text or "").split(",")]
    keyword = parts[0]
    start, end, step = int(parts[1]), int(parts[2]), int(parts[3])
    if not keyword or step <= 0:
        raise ValueError("키워드,시작,끝,간격 형식이어야 합니다")
    values = []
    for i in range(start, end + 1, step):
        if i < 0:
            wrapped = "[" * abs(i) + keyword + "]" * abs(i)
        elif i == 0:
            wrapped = keyword
        else:
            wrapped = "{" * i + keyword + "}" * i
        values.append((keyword, wrapped))
        if len(values) > MAX_GRID:
            break
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
        seeds = self._variant_seeds(params.get("seed"), variants, mode)
        queued = 0
        for seed in seeds:
            result = self._enqueue_clone(info, params, {"seed": seed, **char_overrides})
            queued += 1 if result.get("ok") else 0
        self.ctx.log(f"Seed Fan-out: 총 {total}장(원본 1 + 변형 {queued}/{variants}, "
                     f"mode={mode}, base={params.get('seed')})")

    @staticmethod
    def _variant_seeds(base_seed, count, mode):
        if mode == "random":
            return [random.randint(0, SEED_SPACE - 1) for _ in range(count)]
        try:
            base = int(base_seed)
        except (TypeError, ValueError):
            base = -1
        if base < 0:
            # WEBUI/COMFYUI는 시드가 -1(백엔드 랜덤)으로 남을 수 있다 — base를 추첨.
            base = random.randint(0, SEED_SPACE - 1)
        if mode == "fixed":
            return [base] * count  # 동일 시드 — 입력창 와일드카드 변주 비교용
        step = -1 if mode == "-1" else 1
        return [(base + step * i) % SEED_SPACE for i in range(1, count + 1)]

    # ── 모드 2: X/Y Plot (인스턴트 이벤트 포팅) ──────────────────
    def _run_xy_plot(self, info, params, settings, char_overrides):
        x_values = self._axis_values("X", settings.get("x_axis"), settings.get("x_args"))
        y_values = self._axis_values("Y", settings.get("y_axis"), settings.get("y_args"))
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
        try:
            base_seed = int(params.get("seed"))
        except (TypeError, ValueError):
            base_seed = -1
        if base_seed < 0:
            base_seed = random.randint(0, SEED_SPACE - 1)

        base_prompt = str(params.get("input") or "")
        queued = 0
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
            if not ok:
                continue
            result = self._enqueue_clone(info, params, overrides, prompt=prompt)
            queued += 1 if result.get("ok") else 0
        self.ctx.log(f"X/Y Plot: {queued}/{len(combos)}장 큐 추가 (seed={base_seed} 고정)")

    def _axis_values(self, axis_name, axis, args_text):
        """축 정의 → 조합 항목 리스트. 항목 = None | ("param", (key, value)) |
        ("prompt", (keyword, replacement)). 파싱 실패 시 None(전체 중단)."""
        axis = str(axis or AXIS_NONE)
        if axis == AXIS_NONE:
            return [None]
        try:
            if axis == AXIS_CFG:
                return [("param", ("cfg_scale", value)) for value in _float_range(args_text)]
            if axis == AXIS_RESCALE:
                return [("param", ("cfg_rescale", value)) for value in _float_range(args_text)]
            if axis == AXIS_SAMPLER:
                samplers = [part.strip() for part in str(args_text or "").split(",") if part.strip()]
                if not samplers:
                    raise ValueError("샘플러 콤마 목록이 비었습니다")
                return [("param", ("sampler", sampler)) for sampler in samplers]
            if axis == AXIS_EMPHASIS:
                return [("prompt", pair) for pair in _emphasis_values(args_text)]
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
                 "help": "NAI 전용. 켜면 파생 장들이 지금 1회 전개한 캐릭터 스냅샷을 공유"
                         "(캐릭터 와일드카드 재롤 방지). 끄면 장마다 재전개",
                 "apply": "next-generation", "order": 3},
                # ── X/Y Plot (복잡 모드 → 우측 칼럼) ──
                {"key": "x_axis", "type": "select", "options": AXIS_OPTIONS, "default": AXIS_NONE,
                 "label": "X 축", "column": "right", "section": "X/Y Plot", "order": 10,
                 "apply": "next-generation", "visible_when": when_xy},
                {"key": "x_args", "type": "text", "default": "", "label": "X 인자",
                 "help": "CFG/Rescale: 시작,끝,간격 · Sampler: 콤마 목록 · "
                         "강조: 키워드,시작,끝,간격 · 스왑: 키워드,대체1,대체2(^=콤마)",
                 "column": "right", "section": "X/Y Plot", "order": 11,
                 "apply": "next-generation", "visible_when": when_xy},
                {"key": "y_axis", "type": "select", "options": AXIS_OPTIONS, "default": AXIS_NONE,
                 "label": "Y 축", "column": "right", "section": "X/Y Plot", "order": 12,
                 "apply": "next-generation", "visible_when": when_xy},
                {"key": "y_args", "type": "text", "default": "", "label": "Y 인자",
                 "column": "right", "section": "X/Y Plot", "order": 13,
                 "apply": "next-generation", "visible_when": when_xy},
            ],
            title="Seed Fan-out",
        )
    ctx.log("ready — Seed Fan-out / X/Y Plot (Settings ▸ Extension 또는 퀵 버튼에서 조정)")
