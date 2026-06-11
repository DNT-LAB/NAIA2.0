"""Seed Fan-out — NAIA Custom Extension 샘플 (naia_ext_api=1).

Generate 버튼을 누르면 **동일 프롬프트**로 시드만 바꾼 변형 n장을 큐에 추가한다.
원본 요청은 그대로 진행되므로 총 1 + n 장이 생성된다.

설치: 이 폴더(seed_fanout)를 user-data의 ``extensions/`` 아래로 복사 후 백엔드 재시작.
(Windows 설치형 기본 위치: ``%APPDATA%\\NAIA\\extensions\\seed_fanout``)

설정: ``settings.json`` (없으면 아래 DEFAULT_SETTINGS 사용, 매 생성 시 다시 읽으므로
파일만 고치면 재시작 없이 반영된다)::

    {"count": 3, "mode": "+1", "sources": ["generate"]}

- count   : 추가로 큐에 넣을 변형 수 (1~16)
- mode    : "random" = 변형마다 새 랜덤 시드 / "+1" = base+1, base+2, ... /
            "-1" = base-1, base-2, ... (base = 원본 요청의 시드. 원본이 랜덤(-1)으로
            남는 WEBUI/COMFYUI 경로면 base를 한 번 추첨해서 사용)
- sources : 반응할 생성 경로(dispatched 이벤트의 source = 명령 type).
            기본 ["generate"] = 메인 Generate 버튼만. 프리셋/Refine/자동화 경로까지
            늘리면 해당 경로도 n배가 되니 주의.

동작 원리(확장 API 시연):
- ctx.subscribe("generation_request_dispatched", ...) 로 모든 큐 삽입을 구독
- 이벤트의 ``ext_origin`` 이 비어있지 않으면 **확장이 만든 파생 요청이므로 무시**
  (이 가드가 없으면 무한 재귀로 큐가 폭주한다 — 직접 만들 때 반드시 복사할 것)
- ctx.enqueue_generation(...) 으로 원본 prompt/negative/해상도를 복제하고 시드만 교체

주의: 입력창 와일드카드(``__wc__`` 등)는 NAIA가 **생성 직전에** 전개하므로,
프롬프트에 와일드카드가 있으면 변형마다 다른 전개가 나올 수 있다(본가 동작과 동일).
"""

import random

SEED_SPACE = 10_000_000_000  # 코어 정규화의 randint(0, 9_999_999_999)와 동일 공간
MAX_COUNT = 16

DEFAULT_SETTINGS = {
    "count": 3,
    "mode": "+1",
    "sources": ["generate"],
}


class SeedFanout:
    def __init__(self, ctx):
        self.ctx = ctx

    def on_generation_dispatched(self, info):
        if not isinstance(info, dict):
            return
        # 재귀 가드: 확장이 만든 파생 요청(ext_origin 有)에는 절대 다시 반응하지 않는다.
        if info.get("ext_origin"):
            return
        settings = self.ctx.load_settings(DEFAULT_SETTINGS)
        sources = settings.get("sources") or DEFAULT_SETTINGS["sources"]
        if str(info.get("source") or "") not in {str(s) for s in sources}:
            return
        try:
            count = int(settings.get("count") or 0)
        except (TypeError, ValueError):
            count = 0
        if count <= 0:
            return
        if count > MAX_COUNT:
            self.ctx.log(f"count {count} -> {MAX_COUNT} (상한 클램프)")
            count = MAX_COUNT

        params = info.get("params") if isinstance(info.get("params"), dict) else {}
        mode = str(settings.get("mode") or "+1")
        seeds = self._variant_seeds(params.get("seed"), count, mode)

        queued = 0
        for seed in seeds:
            result = self.ctx.enqueue_generation(
                prompt=params.get("input"),
                negative_prompt=params.get("negative_prompt"),
                api_mode=info.get("api_mode"),
                prompt_run_id=info.get("prompt_run_id"),
                overrides={
                    "seed": seed,
                    "width": params.get("width"),
                    "height": params.get("height"),
                },
            )
            if result.get("ok"):
                queued += 1
            else:
                self.ctx.log(f"variant blocked: {result.get('message')}")
        self.ctx.log(
            f"queued {queued}/{count} seed variants (mode={mode}, base={params.get('seed')}, "
            f"seeds={seeds})"
        )

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
        step = -1 if mode == "-1" else 1
        return [(base + step * i) % SEED_SPACE for i in range(1, count + 1)]


def register(ctx):
    ext = SeedFanout(ctx)
    ctx.subscribe("generation_request_dispatched", ext.on_generation_dispatched)
    # Extensions 패널에 설정 폼 노출(선언적 — JS 불필요). 값은 settings.json으로
    # 라운드트립되고 이 확장은 매 생성 시 다시 읽으므로 저장 즉시 반영된다.
    if hasattr(ctx, "register_panel"):
        ctx.register_panel(
            fields=[
                {"key": "count", "type": "int", "min": 1, "max": MAX_COUNT,
                 "default": DEFAULT_SETTINGS["count"], "label": "변형 수",
                 "help": "Generate 1회당 추가로 큐에 넣을 장수", "apply": "next-generation", "order": 1},
                {"key": "mode", "type": "select", "options": ["random", "+1", "-1"],
                 "default": DEFAULT_SETTINGS["mode"], "label": "시드 방식",
                 "apply": "next-generation", "order": 2},
                {"key": "sources", "type": "tags", "default": list(DEFAULT_SETTINGS["sources"]),
                 "label": "반응 경로", "help": "반응할 생성 명령 type 목록 (기본: 메인 Generate 버튼)",
                 "apply": "next-generation", "order": 3},
            ],
            title="Seed Fan-out",
        )
    ctx.log("ready — Generate 시 시드 변형을 큐에 추가합니다 (Extensions 패널에서 조정)")
