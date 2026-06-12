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
    "make_grid": True,
    "x_axis": AXIS_NONE,
    "x_range": "5,7,1",
    "x_samplers_pick": [],
    "x_emph_target": "",
    "x_emph_start": 0.6,
    "x_emph_step": 0.4,
    "x_emph_end": 1.4,
    "x_swap_base": "",
    "x_swap_steps": [],
    "y_axis": AXIS_NONE,
    "y_range": "0,0.4,0.2",
    "y_samplers_pick": [],
    "y_emph_target": "",
    "y_emph_start": 0.6,
    "y_emph_step": 0.4,
    "y_emph_end": 1.4,
    "y_swap_base": "",
    "y_swap_steps": [],
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


def _wrap_emphasis(keyword, weight, api_mode):
    """가중 문법은 모드별 자동: NAI(NAID4/4.5)=``w::키워드::``,
    WEBUI/COMFYUI=로컬 ``(키워드:w)``."""
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
        # — 원본만 캐릭터를 따로 추첨해 묶음과 어긋나는 문제 방지. 확정 제거(ok)
        # 또는 건너뛰기 예약(skip_scheduled — 러너가 실행 전에 톰스톤 소비)이면
        # 대체로 간주한다(Codex R2-#2: 예약인데 원본까지 나오는 건 이미 execute가
        # 시작된 마이크로초 윈도뿐). 둘 다 아니면 원본 유지 + 변형 N-1장 폴백.
        replace_original = False
        if char_overrides:
            cancel = self.ctx.cancel_generation(info.get("request_id"))
            replace_original = bool(cancel.get("ok") or cancel.get("skip_scheduled"))
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
        x_meta = self._axis_values("X", settings.get("x_axis"), settings, "x", api_mode)
        y_meta = self._axis_values("Y", settings.get("y_axis"), settings, "y", api_mode)
        if x_meta is None or y_meta is None:
            return  # 축 파싱 실패는 _axis_values가 로그로 안내
        x_values, x_title = x_meta
        y_values, y_title = y_meta
        combos = [(x, y) for y in y_values for x in x_values]
        if len(combos) <= 1 and combos and combos[0] == (None, None):
            self.ctx.log("X/Y Plot: 사용할 축이 없습니다 (X/Y 모두 None)")
            return
        if len(combos) > MAX_GRID:
            self.ctx.log(f"X/Y Plot: 조합 {len(combos)}개 → 상한 {MAX_GRID}개로 절단")
            combos = combos[:MAX_GRID]

        # 프롬프트 치환 축의 시작/원본 프롬프트가 실제 프롬프트에 **태그 경계로**
        # 존재하는지 선검증 — 없으면 토스트로 안내하고 전체 중단(원본만 생성).
        # substring이 아니라 태그 시퀀스 매칭이다: "smile"은 "bitter smile" 안이
        # 아니라 독립 태그 smile에만 매칭된다.
        base_prompt = str(params.get("input") or "")
        for axis_values in (x_values, y_values):
            for item in axis_values:
                if item is None or item[0] != "prompt":
                    continue
                keyword = item[1][0]
                if keyword and _find_tag_span(base_prompt, keyword) is None:
                    self._toast(f'"{keyword}" — 시작 프롬프트가 프롬프트에 없습니다(태그 단위 일치 기준)')
                    return
                break  # 축의 키워드는 동일 — 첫 항목만 보면 충분

        # 그리드 비교의 본질: 전 항목 동일 시드(원본 시드 고정).
        base_seed = self._base_seed(params.get("seed"))

        # 셀을 전부 먼저 빌드(키워드 검증 포함)하고, 1장 이상 유효할 때만 원본을
        # 취소한다 — X/Y Plot은 "그리드만" 생성한다(원본까지 N+1장 생성 방지).
        # 전 셀이 무효(키워드 부재 등)면 원본을 건드리지 않는다.
        cols = len(x_values)
        cells = []
        for index, (x_value, y_value) in enumerate(combos):
            overrides = {"seed": base_seed, **char_overrides}
            prompt = base_prompt
            ok = True
            for value in (x_value, y_value):
                if value is None:
                    continue
                kind, payload = value[0], value[1]
                if kind == "param":
                    overrides[payload[0]] = payload[1]
                elif kind == "prompt":
                    keyword, replacement = payload
                    span = _find_tag_span(prompt, keyword)
                    if span is None:
                        self.ctx.log(f"X/Y Plot: 프롬프트에 태그 '{keyword}'가 없어 건너뜀")
                        ok = False
                        break
                    prompt = prompt[:span[0]] + replacement + prompt[span[1]:]
            if ok:
                cells.append((overrides, prompt, index % cols, index // cols))
        if not cells:
            self.ctx.log("X/Y Plot: 유효한 조합이 없어 원본만 생성합니다")
            return
        cancel = self.ctx.cancel_generation(info.get("request_id"))
        queued = 0
        id_map = {}
        for overrides, prompt, col, row in cells:
            result = self._enqueue_clone(info, params, overrides, prompt=prompt)
            if result.get("ok"):
                queued += 1
                if result.get("request_id"):
                    id_map[result["request_id"]] = (col, row)
        if cancel.get("ok"):
            origin_note = "원본 취소, 그리드만"
        elif cancel.get("skip_scheduled"):
            origin_note = "원본 건너뛰기 예약, 그리드만"
        else:
            origin_note = "원본 유지(취소 실패)"
        self.ctx.log(f"X/Y Plot: {queued}/{len(cells)}장 큐 추가 ({origin_note}, seed={base_seed} 고정)")

        # n×m 합성 이미지: 전 셀 완료 시 grid/ 폴더에 저장(설정으로 끌 수 있음).
        if settings.get("make_grid") and id_map:
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
                "expected": set(id_map.keys()),
            }
            with self._grid_lock:
                self._grid_batches.append(batch)
                while len(self._grid_batches) > MAX_PENDING_GRIDS:
                    dropped = self._grid_batches.pop(0)
                    self.ctx.log(f"그리드 추적 GC: 미완료 배치 폐기({len(dropped['expected'])}셀 미수신)")

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
            batch["expected"].discard(rid)
            if fetched.get("ok"):
                batch["images"][batch["ids"][rid]] = fetched["image"]
            else:
                self.ctx.log(f"그리드 셀 회수 실패({rid[:8]}): {fetched.get('message')}")
            done = not batch["expected"]
            if done:
                self._grid_batches.remove(batch)
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
        filename = f"grid_{time.strftime('%Y%m%d_%H%M%S')}_{cols}x{rows}.png"
        path = grid_dir / filename
        canvas.save(path, format="PNG")
        return str(path)

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
            if axis == AXIS_CFG:
                return ([("param", ("cfg_scale", value), f"{value:g}")
                         for value in _float_range(settings.get(f"{prefix}_range"))], "CFG Scale")
            if axis == AXIS_RESCALE:
                return ([("param", ("cfg_rescale", value), f"{value:g}")
                         for value in _float_range(settings.get(f"{prefix}_range"))], "PG.Rescale")
            if axis == AXIS_SAMPLER:
                # 현재 모드 샘플러 목록에서 체크 선택 — 선택 수 = 생성 수.
                picked = settings.get(f"{prefix}_samplers_pick")
                picked = [str(item) for item in picked] if isinstance(picked, (list, tuple)) else []
                mode_list = MODE_SAMPLERS.get(api_mode)
                if mode_list:
                    picked = [item for item in picked if item in mode_list]
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
                start = float(settings.get(f"{prefix}_emph_start"))
                step = float(settings.get(f"{prefix}_emph_step"))
                end = float(settings.get(f"{prefix}_emph_end"))
                if step <= 0:
                    self._toast(f"{axis_name}축 강조 사다리: 가중치 스텝은 양수여야 합니다")
                    return None
                if end < start:
                    self._toast(f"{axis_name}축 강조 사다리: 종료 가중치가 시작보다 작습니다")
                    return None
                items = []
                weight = start
                while weight <= end + 1e-9 and len(items) <= MAX_GRID:
                    rounded = round(weight, 2)
                    items.append(("prompt", (target, _wrap_emphasis(target, rounded, api_mode)),
                                  f"{rounded:g}"))
                    weight += step
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
                return ([("prompt", (base, step), step) for step in steps],
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


def _axis_fields(prefix, section, base_order, when_xy, samplers):
    """축 1개분 패널 필드 — 종류 select + 종류별 전용 입력칸. 입력칸의
    visible_when은 종류 select를 가리키고, 종류 자신은 모드(feature)에 묶여
    있어 모드≠X/Y면 계단식으로 함께 숨는다. 스왑은 3번째 칼럼(extra)에
    [시작 프롬프트]+[Step n 대치 프롬프트]+[추가+] 빌더로 펼쳐진다."""
    axis_key = f"{prefix}_axis"
    common = {"column": "right", "section": section, "apply": "next-generation"}
    when_emph = {"field": axis_key, "in": [AXIS_EMPHASIS]}
    when_swap = {"field": axis_key, "in": [AXIS_SWAP]}
    return [
        {"key": axis_key, "type": "select", "options": AXIS_OPTIONS, "default": AXIS_NONE,
         "label": "종류", "order": base_order, "visible_when": when_xy, **common},
        {"key": f"{prefix}_range", "type": "text", "default": DEFAULT_SETTINGS[f"{prefix}_range"],
         "label": "값 범위", "placeholder": "시작,끝,간격 — 예: 5,7,1",
         "help": "시작,끝,간격. 예: 5,7,1 → 5·6·7 세 값 = 3장",
         "order": base_order + 1,
         "visible_when": {"field": axis_key, "in": [AXIS_CFG, AXIS_RESCALE]}, **common},
        {"key": f"{prefix}_samplers_pick", "type": "multiselect", "options": samplers,
         "default": list(samplers), "label": "샘플러 선택",
         "help": "현재 모드의 샘플러 목록 — 체크한 샘플러 1개당 1장(선택 수 = 생성 수)",
         "order": base_order + 2,
         "visible_when": {"field": axis_key, "in": [AXIS_SAMPLER]}, **common},
        # ── 강조 사다리: 원본 프롬프트(쉼표 허용) + 시작/스텝/종료 — 전부 필수 ──
        {"key": f"{prefix}_emph_target", "type": "text", "multiline": True, "default": "",
         "label": "원본 프롬프트", "placeholder": "태그 단위 정확 매칭 — 쉼표 포함 긴 구문 가능",
         "help": "프롬프트 창에 존재하는 태그(시퀀스)를 그대로 입력 — 매칭은 태그 경계 기준"
                 "(smile은 bitter smile 안이 아니라 독립 태그 smile에만 일치). "
                 "이 구간에 가중을 입혀 1장씩 생성 — 문법은 모드 자동(NAI w::…::, 로컬 (…:w))",
         "order": base_order + 3, "visible_when": when_emph, **common},
        {"key": f"{prefix}_emph_start", "type": "float", "default": 0.6, "step": 0.1,
         "label": "시작 가중치", "order": base_order + 4, "visible_when": when_emph, **common},
        {"key": f"{prefix}_emph_step", "type": "float", "default": 0.4, "min": 0.05, "step": 0.05,
         "label": "가중치 스텝", "order": base_order + 5, "visible_when": when_emph, **common},
        {"key": f"{prefix}_emph_end", "type": "float", "default": 1.4, "step": 0.1,
         "label": "종료 가중치", "order": base_order + 6, "visible_when": when_emph, **common},
        # ── 프롬프트 스왑: 3번째 칼럼(extra) 빌더 ──
        {"key": f"{prefix}_swap_base", "type": "text", "multiline": True, "default": "",
         "label": "시작 프롬프트", "placeholder": "프롬프트 창에 존재하는 태그(시퀀스) — 쉼표 포함 긴 구문 가능",
         "help": "프롬프트 창의 이 구간을 아래 Step들로 바꿔 1장씩 생성. 매칭은 태그 경계 기준"
                 "(smile은 bitter smile 안이 아니라 독립 태그 smile에만 일치). "
                 "프롬프트에 없으면 토스트로 안내하고 중단",
         "column": "extra", "section": f"{section} · 프롬프트 스왑", "apply": "next-generation",
         "order": base_order + 7, "visible_when": when_swap},
        {"key": f"{prefix}_swap_steps", "type": "list", "multiline": True, "default": [],
         "label": "대치할 프롬프트", "placeholder": "이 내용으로 교체 — 쉼표 포함 긴 구문 가능",
         "help": "Step 1개당 1장 — [추가 +]로 늘리고 ×로 제거. "
                 "\"spread legs, pen, the pen glides across warm skin\" 같은 구문 전체 가능",
         "column": "extra", "section": f"{section} · 프롬프트 스왑", "apply": "next-generation",
         "order": base_order + 8, "visible_when": when_swap},
    ]


def _register_panel(ctx, ext):
    """패널 (재)등록 — 샘플러 선택지는 현재 API 모드 목록을 따른다.
    api_mode_changed 구독으로 모드 전환 시 다시 호출된다."""
    if not hasattr(ctx, "register_panel"):
        return
    mode = ""
    if hasattr(ctx, "get_api_mode"):
        mode = str(ctx.get_api_mode() or "")
    samplers = MODE_SAMPLERS.get(mode, MODE_SAMPLERS["NAI"])
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
            *_axis_fields("x", "X 축", 10, when_xy, samplers),
            *_axis_fields("y", "Y 축", 30, when_xy, samplers),
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
        title="Seed Fan-out",
        on_action=ext.on_action,
    )


def register(ctx):
    ext = SeedFanout(ctx)
    ctx.subscribe("generation_request_dispatched", ext.on_generation_dispatched)
    ctx.subscribe("generation_result_available", ext.on_generation_result)
    # 모드 전환 시 샘플러 선택지를 그 모드 목록으로 재등록.
    ctx.subscribe("api_mode_changed", lambda _payload: _register_panel(ctx, ext))
    _register_panel(ctx, ext)
    ctx.log("ready — Seed Fan-out / X/Y Plot (퀵 버튼 팝업에서 조정, 관리는 Settings ▸ Extension)")
