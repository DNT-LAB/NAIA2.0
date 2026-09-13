# -*- coding: utf-8 -*-
"""Interactive 특징 썸네일 벤치 — headless CLI 생성기.

용도
    wildcards/thumb/_todo/<batch>.txt 의 태그를 순차로 소비하며 NAI V4.5 로 한 장씩
    생성해 <out>/<batch>/ 에 저장한다. 축별 고정 베이스는 _bench.json 이 SSOT다.

왜 GUI 를 안 쓰나
    수백 장을 사람이 눌러 돌리기엔 소모가 크다. core/api_service.py 는 AppContext /
    이벤트 버스 / 파이프라인 훅에 묶여 있어 CLI 에서 통째로 끌어오기 부적합하다.
    그래서 '검증된 페이로드 계약만' 여기로 옮겨 복제했다 — 파라미터/모델/네거티브는
    사용자가 실제로 승인한 이미지의 메타데이터에서 그대로 뽑았다(--verify 로 대조).

주의
    - 토큰은 SecureTokenManager(keyring + Fernet)에서 읽는다. 파일/인자로 받지 않는다.
    - 요청 상한(--max-requests)과 steps/해상도 상한을 코드에서 강제한다. 사용자가
      승인한 한도(3000회 / steps 28 / 1024x1024)를 넘기지 못한다.
    - 딜레이는 기본 2초 ±50%(Automation 과 같은 조건). 서버 부하를 고려한 값이다.

사용
    python tools/thumb_bench.py --list
    python tools/thumb_bench.py horns --dry-run
    python tools/thumb_bench.py horns --limit 5
    python tools/thumb_bench.py horns state ears        # 여러 배치 연속
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import random
import re
import sys
import time
import zipfile
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

WILDCARD_DIR = ROOT / "wildcards" / "thumb"
TODO_DIR = WILDCARD_DIR / "_todo"
BENCH_FILE = WILDCARD_DIR / "_bench.json"
DEFAULT_OUT = ROOT / "NAIA-Portable" / "user-data" / "output" / "_thumb_bench"

NAI_URL = "https://image.novelai.net/ai/generate-image"
NAI_SUBSCRIPTION_URL = "https://image.novelai.net/user/subscription"

# 사용자 승인 한도 — 코드에서 강제한다.
HARD_MAX_REQUESTS = 3500
HARD_MAX_STEPS = 28
HARD_SIZE = 1024


def load_bench() -> dict:
    if not BENCH_FILE.exists():
        raise SystemExit(f"벤치 정의가 없습니다: {BENCH_FILE}  (tools/thumb_bench_init.py 로 생성)")
    return json.loads(BENCH_FILE.read_text(encoding="utf-8"))


def batch_tags(name: str, required: bool = True) -> list[str]:
    """배치 목록. 파일이 없으면 빈 목록(required=False) 또는 종료.

    계획은 생성 전에 한 번에 만든다. 없는 배치 하나가 SystemExit 을 내면 뒤에 있는
    멀쩡한 배치까지 통째로 죽는다(실측: 5개 중 4번째가 없어 0장 생성). 배치는 다 끝나면
    thumb_todo 가 파일을 지우므로 '없음'은 정상 상황이다 -> 경고만 하고 건너뛴다.
    """
    path = TODO_DIR / f"{name}.txt"
    if not path.exists():
        if required:
            print(f"  !! 배치 파일이 없어 건너뜁니다(이미 완료된 축일 수 있음): {path.name}")
        return []
    return [l.strip() for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def get_token(token_file: str | None = None) -> str:
    """토큰 하나. 지정 파일이 SecureTokenManager 보다 **먼저 이긴다**.

    작가 썸네일 도구(`C:\\VNR\\artist_thumb_tool`)가 계정을 `token.txt`~`token7.txt` 로
    나눠 두고 `--token-file` 로 고르는 것과 같은 규약이다. 그쪽 계정을 여기서 쓰려면
    앱 저장소(`secure_tokens.json`)를 건드리지 않고 파일을 가리키는 편이 안전하다 —
    앱 토큰을 덮어쓰면 사용자의 원격 웹 세션이 같이 바뀐다.
    """
    if token_file:
        path = Path(token_file)
        if not path.exists():
            raise SystemExit(f"토큰 파일이 없습니다: {path}")
        token = path.read_text(encoding="utf-8").strip()
        if not token:
            raise SystemExit(f"토큰 파일이 비어 있습니다: {path}")
        return token
    from core.secure_token_manager import SecureTokenManager
    token = SecureTokenManager().get_token("nai_token")
    if not token:
        raise SystemExit("NAI 토큰을 찾을 수 없습니다. 앱에서 한 번 로그인해 저장하세요.")
    return token


def fetch_usage(token: str, timeout: int = 8) -> dict | None:
    """무료 생성 풀 상태. 실패하면 None(측정 보조값이라 생성을 막지 않는다).

    ⚠️ `percent` 는 **내림한 정수**라 경계 판정에 쓸 수 없다. 무료/유료를 가르는 것은
    `isNegative` 다(작가 도구에서 실측으로 확정된 것과 같은 계약).
    """
    try:
        with requests.Session() as session:
            res = session.get(NAI_SUBSCRIPTION_URL, timeout=timeout,
                              headers={"Authorization": f"Bearer {token}", "Accept": "*/*"})
            if res.status_code != 200:
                return None
            usage = (res.json() or {}).get("usage") or {}
        return {"percent": int(usage.get("percent", 0) or 0),
                "is_negative": bool(usage.get("isNegative", False)),
                "next_percent_sec": int(usage.get("timeUntilNextPercent", 0) or 0)}
    except Exception:
        return None


def build_prompt(bench: dict, batch: str, tag: str) -> tuple[str, str]:
    """(positive, negative). <<VARY>> 자리에 가중치 블록을 넣는다."""
    spec = bench["batches"].get(batch)
    if not spec:
        raise SystemExit(f"_bench.json 에 '{batch}' 정의가 없습니다.")
    weight = spec.get("weight", bench["defaults"]["weight"])
    vary = f"{weight}::{tag} ::"
    positive = spec["template"].replace("<<VARY>>", vary)
    negative = spec.get("negative") or bench["defaults"]["negative"]
    _guard_adult(batch, positive)
    # 배치가 **자기 태그를 억제**하고 있으면 돌려도 그 태그가 안 나온다. 실측:
    # `species_male` 의 네거티브에 `furry male` 이 들어 있어 `furry male` 을 돌렸더니
    # 수인 요소가 전혀 없는 맨 남성이 나왔다. 조용히 실패하고 팩에 들어가므로 여기서 막는다.
    # (양쪽 `-1:: ... ::` 블록과 일반 네거티브 모두 대상이다.)
    _neg_words = {w.strip().lower() for w in re.split(r"[,:]", negative) if w.strip()}
    if tag.lower() in _neg_words:
        raise SystemExit(
            f"배치 '{batch}' 의 네거티브가 태그 '{tag}' 를 억제한다. "
            f"이 배치로는 그 태그를 만들 수 없다 — 억제 없는 배치로 갈라라"
            f"(tools/thumb_todo.py 의 FRAMING_SPLIT)."
        )
    return positive, negative


# 성인 축은 **어린 외형으로 생성될 수 없어야 한다.** 정의 파일을 손으로 고치거나
# 다른 배치 이름을 붙여도 여기서 막힌다 — 사용자 요구는 "어린 외형의 nsfw 이미지가
# 배포되는 것"을 막는 것이고, 그 마지막 방어선은 요청 직전이다.
# `diaper` 도 넣는다 — 성인 기저귀 취향이 따로 있긴 하나, 성적 맥락에서는
# 유아화로 읽히고 이 프로젝트의 우려(한국 법)와 정면으로 닿는다.
# **목록이 아니라 정규식이다.** 부분 문자열 7개만 보던 탓에 `child` · `baby` ·
# `teenage` · `muscular child` · 맨 `young` 이 통과했다(Codex 리뷰 2026-07-30 실측).
# 같은 목록이 세 곳에 복사돼 있었고 셋 다 같은 구멍이었다 — 공용 모듈로 합쳤다.
from tools.thumb_age_guard import danger_age_hits, DANGER_AGE_EXAMPLES  # noqa: E402


def _guard_adult(batch: str, positive: str) -> None:
    if "nsfw" not in batch:
        return
    bad = danger_age_hits(positive)
    if bad:
        raise SystemExit(
            f"거부: 성인 배치 '{batch}' 의 프롬프트에 어린 외형 태그가 있습니다 {bad}.\n"
            f"       _bench.json 을 고쳤다면 되돌리고, tools/thumb_bench_init.py 를 다시 도세요."
        )
    # 남성 커플(sensitive)은 `mature male` 로 연령을 만든다 — 요구는 연령이지 성별이 아니다.
    if "mature female" not in positive and "mature male" not in positive:
        raise SystemExit(
            f"거부: 성인 배치 '{batch}' 에 `mature female` 이 없습니다.\n"
            f"       연령을 만드는 것은 이 태그 하나뿐입니다(실측). 근거는\n"
            f"       wildcards/nsfw/_DEFERRED_body_nsfw.md 참조."
        )
    # `rating:sensitive` 는 세 번째 등급이다 — 성적 묘사 없이 관계·종족만 보이는 것.
    # `yuri` · `bara` · `tentacles` 처럼 정의 자체는 성인 도감에 있으나 그림으로는
    # 옷 입은 두 사람이면 성립하는 태그를 위해 연다(사용자 요청 2026-07-29).
    #
    # 연령 요구는 **그대로 산다**. 등급이 낮아도 어린 외형으로 관계를 그리는 것은
    # 이 프로젝트가 막으려는 바로 그것이다. 은닉만 뺀다 — 노출이 없으면 가릴 것이
    # 없고, 오히려 얼굴이 보여야 관계가 읽힌다.
    if "rating:sensitive" in positive:
        for bad_tag in ("nude", "naked", "rating:explicit", "rating:questionable"):
            if bad_tag in positive:
                raise SystemExit(
                    f"거부: sensitive 배치 '{batch}' 에 `{bad_tag}` 가 있습니다.\n"
                    f"       sensitive 는 노출 없는 등급입니다. 섞으면 등급이 무의미해집니다."
                )
        return
    if not ("rating:explicit" in positive or "rating:questionable" in positive):
        raise SystemExit(f"거부: 성인 배치 '{batch}' 에 등급 태그가 없습니다.")
    missing = [c for c in ("faceless female", "head out of frame", "close-up")
               if c not in positive]
    if missing:
        raise SystemExit(
            f"거부: 성인 배치 '{batch}' 에 은닉 태그가 빠졌습니다 {missing}.\n"
            f"       썸네일은 '무슨 행위인지'만 보이면 되고 외형은 안 보여야 합니다."
        )


def payload_for(bench: dict, positive: str, negative: str, seed: int) -> dict:
    p = dict(bench["defaults"]["parameters"])
    # 승인 한도 강제 — 정의 파일이 바뀌어도 여기서 막는다.
    p["steps"] = min(int(p.get("steps", 28)), HARD_MAX_STEPS)
    p["width"] = p["height"] = HARD_SIZE
    p["seed"] = seed
    p["extra_noise_seed"] = seed
    p["negative_prompt"] = negative
    p["v4_prompt"] = {"caption": {"base_caption": positive, "char_captions": []},
                      "use_coords": False, "use_order": True}
    p["v4_negative_prompt"] = {"caption": {"base_caption": negative, "char_captions": []},
                              "legacy_uc": False}
    return {"input": positive, "model": bench["defaults"]["model"],
            "action": "generate", "parameters": p}


def generate_one(token: str, payload: dict, timeout: int = 180) -> tuple[bytes, dict]:
    """NAI 응답(zip)에서 첫 이미지 바이트를 뽑는다. (이미지, 계측) 을 돌려준다.

    ## 무엇을 재는가

    `elapsed` 는 **요청을 보낸 순간부터 응답 본문을 다 받을 때까지**다. NAI 는 그림이
    다 그려진 뒤에야 zip 을 흘리기 시작하므로 이 값이 곧 생성 대기시간이다. 압축 해제와
    파일 쓰기는 뺐다 — 서버 상태를 재는 것이지 내 디스크를 재는 것이 아니다.

    ⚠️ 세션을 매 요청 새로 연다(원래 그랬다). TLS 핸드셰이크가 장마다 붙지만 그 값은
    **일정한 바닥**이라 추세를 보는 데는 방해가 안 된다. 여기서 세션을 재사용하도록
    바꾸면 측정 대상 자체가 달라지므로 QoS 관측 중에는 건드리지 않는다.
    """
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    started = time.perf_counter()
    with requests.Session() as session:
        res = session.post(NAI_URL, headers=headers, json=payload, timeout=timeout)
        status = res.status_code
        if status != 200:
            elapsed = time.perf_counter() - started
            body = (res.text or "")[:200].replace("\n", " ")
            # 429 는 '느려짐'이 아니라 '거절'이다. 그때 서버가 붙여 보내는 헤더가
            # 정책을 말해 준다(얼마나 기다리라는지 · 창이 언제 열리는지). 이것을 안 남기면
            # "429 를 봤다" 까지만 알고 "어떤 한도에 걸렸다" 는 모른 채 끝난다.
            keep = ("retry-after", "x-ratelimit-limit", "x-ratelimit-remaining",
                    "x-ratelimit-reset", "ratelimit-reset", "cf-ray", "server")
            headers = {k: v for k, v in res.headers.items() if k.lower() in keep}
            raise NaiRequestError(f"HTTP {status}: {body}", status=status,
                                  elapsed=elapsed, headers=headers)
        content = res.content
    elapsed = time.perf_counter() - started
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        return z.read(z.infolist()[0]), {"elapsed": elapsed, "status": status,
                                         "bytes": len(content)}


class NaiRequestError(RuntimeError):
    """HTTP 단계에서 실패한 요청. 실패도 응답시간을 남겨야 한다 -- 느려지다 끊기는지,
    곧장 거절당하는지가 QoS 판정에서 서로 다른 이야기다."""

    def __init__(self, message: str, *, status: int | None = None, elapsed: float = 0.0,
                 headers: dict | None = None):
        super().__init__(message)
        self.status = status
        self.elapsed = elapsed
        self.headers = headers or {}


def slug(tag: str) -> str:
    """파일명용 슬러그. 태그마다 반드시 달라야 한다.

    기호 표정 축에서 실측 사고가 났다: 구두점을 전부 '_' 로 바꾸면 ^_^ / >_< / ... /
    @_@ / =_= / |_| / ._. 가 모두 '___' 이 된다(67개 태그 -> 38개 슬러그). 그러면
    --skip-existing 이 남의 파일을 보고 29개를 건너뛴다. 짧은 해시를 붙여 단사로 만든다.
    (팩 빌더는 파일명이 아니라 PNG 메타데이터의 2::태그 :: 로 축을 판정하므로,
     해시가 붙어도 분류에는 영향이 없다.)
    """
    keep = "".join(c if (c.isalnum() or c in " -_") else "_" for c in tag)
    base = "_".join(keep.split()) or "tag"
    digest = hashlib.sha1(tag.encode("utf-8")).hexdigest()[:6]
    return f"{base}-{digest}"


def main() -> int:
    ap = argparse.ArgumentParser(description="Interactive 썸네일 벤치 headless 생성기")
    ap.add_argument("batches", nargs="*", help="_todo/<name>.txt 의 name (여러 개 가능)")
    ap.add_argument("--list", action="store_true", help="배치 목록과 장수만 출력")
    ap.add_argument("--dry-run", action="store_true", help="요청하지 않고 프롬프트만 출력")
    ap.add_argument("--limit", type=int, default=0, help="배치당 최대 장수 (0=전체)")
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="저장 폴더")
    ap.add_argument("--delay", type=float, default=2.0, help="요청 간 기본 딜레이 초 (기본 2)")
    ap.add_argument("--jitter", type=float, default=0.5, help="딜레이 흔들기 비율 (기본 0.5 = ±50%%)")
    ap.add_argument("--seed", type=int, default=5485583918,
                    help="고정 시드. 축이 달라도 같은 얼굴/구도가 나와 비교가 쉽다")
    ap.add_argument("--max-requests", type=int, default=HARD_MAX_REQUESTS,
                    help=f"이번 실행의 요청 상한 (하드 상한 {HARD_MAX_REQUESTS})")
    ap.add_argument("--retries", type=int, default=3, help="장당 재시도 횟수")
    ap.add_argument("--skip-existing", action="store_true", default=True,
                    help="이미 파일이 있으면 건너뛴다(기본 켜짐)")
    ap.add_argument("--redo", action="store_true", help="기존 파일을 무시하고 다시 생성")
    ap.add_argument("--token-file", default=None,
                    help="토큰을 이 파일에서 읽는다(예: C:/VNR/artist_thumb_tool/token7.txt). "
                         "지정하면 앱 저장소보다 먼저 이긴다")
    ap.add_argument("--latency-log", default=None,
                    help="장당 응답시간 JSONL 경로 (기본: <out>/_latency.jsonl). "
                         "이어붙이므로 중단하고 다시 돌려도 한 줄기로 남는다")
    ap.add_argument("--stop-on-stall", type=float, default=0.0,
                    help="응답이 이 초를 넘으면 즉시 중단한다(0=끄기). 계정의 '깨끗한 잔량'을 "
                         "재는 탐침용 - 재는 행위가 재려는 것을 소모하므로 첫 스톨에서 끊는다")
    ap.add_argument("--usage-every", type=int, default=25,
                    help="N 장마다 무료 풀(usage) 상태를 같이 기록한다 (0=안 함, 기본 25)")
    args = ap.parse_args()

    bench = load_bench()

    if args.list or not args.batches:
        print(f"{'배치':<26}{'장수':>5}  프레이밍 / 가중치")
        for path in sorted(TODO_DIR.glob("*.txt")):
            name = path.stem
            spec = bench["batches"].get(name)
            n = len(batch_tags(name))
            info = (f"{spec.get('framing','?'):<9} {spec.get('weight','?')}::"
                    if spec else "!! _bench.json 에 정의 없음")
            print(f"{name:<26}{n:>5}  {info}")
        total = sum(len(batch_tags(p.stem)) for p in TODO_DIR.glob("*.txt"))
        print(f"\n총 {total}장.  하드 상한 {HARD_MAX_REQUESTS}회 / steps {HARD_MAX_STEPS} / {HARD_SIZE}px")
        return 0

    cap = min(args.max_requests, HARD_MAX_REQUESTS)
    out_root = Path(args.out)
    token = None if args.dry_run else get_token(args.token_file)

    plan: list[tuple[str, str]] = []
    for name in args.batches:
        tags = batch_tags(name)
        if args.limit:
            tags = tags[:args.limit]
        plan.extend((name, t) for t in tags)
    if len(plan) > cap:
        print(f"!! 계획 {len(plan)}장이 상한 {cap}회를 넘습니다. 앞 {cap}장만 진행합니다.")
        plan = plan[:cap]

    if not plan:
        print("생성할 것이 없습니다(모든 배치가 비었거나 파일이 없습니다).")
        return 0
    # 벤치 정의를 미리 전부 확인한다. 없는 정의는 build_prompt 에서 SystemExit 을 내는데,
    # 그게 첫 장 생성 시점이라 계획을 다 세운 뒤에 죽는다(실측: 49장 계획 후 0장 생성).
    # 요청을 하나도 보내기 전에 걸러야 한다.
    undefined = sorted({name for name, _ in plan if name not in bench["batches"]})
    if undefined:
        print(f"!! _bench.json 에 정의가 없는 배치: {undefined}")
        print("   tools/thumb_bench_init.py 를 다시 실행해 정의를 만드세요.")
        return 2
    # 프롬프트 가드도 **요청 전에** 전부 돌린다. build_prompt 의 가드(자기 태그 억제 ·
    # 연령 · 은닉 · 등급)는 SystemExit 을 내는데, 그것이 장 생성 도중에 터지면 남은 계획이
    # 통째로 죽는다 -- 실측: 3,300장 런이 197장째 `extra digits` 하나에 멈췄다.
    # 못 만드는 태그는 **계획에서 빼고 이유를 드러낸다**(조용히 삼키지 않는다).
    blocked: list[tuple[str, str, str]] = []
    usable: list[tuple[str, str]] = []
    for name, tag in plan:
        try:
            build_prompt(bench, name, tag)
        except SystemExit as exc:
            blocked.append((name, tag, str(exc).splitlines()[0][:120]))
            continue
        usable.append((name, tag))
    if blocked:
        print(f"!! 프롬프트 가드에 걸려 계획에서 뺀 {len(blocked)}장:")
        for name, tag, why in blocked[:20]:
            print(f"   {name}/{tag}  — {why}")
        if len(blocked) > 20:
            print(f"   ... 외 {len(blocked) - 20}장")
    plan = usable
    if not plan:
        print("가드를 통과한 태그가 없습니다.")
        return 2

    print(f"배치 {len(args.batches)}개 / 총 {len(plan)}장 / 딜레이 {args.delay}s "
          f"±{int(args.jitter * 100)}% / 시드 {args.seed}")
    if args.dry_run:
        for name, tag in plan[:6]:
            pos, _ = build_prompt(bench, name, tag)
            print(f"\n[{name}] {tag}\n  {pos[:240]}")
        print(f"\n--dry-run: 요청하지 않았습니다. ({len(plan)}장 계획)")
        return 0

    done = failed = skipped = 0
    t0 = time.time()
    out_root.mkdir(parents=True, exist_ok=True)
    log_path = Path(args.latency_log) if args.latency_log else out_root / "_latency.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    # 이어붙인다. 중단하고 다시 돌리는 것이 이 도구의 정상 운용이라(--skip-existing 기본 켜짐)
    # 덮어쓰면 앞 구간이 사라져 "몇 장째부터 느려지는가" 를 볼 수 없다.
    log = log_path.open("a", encoding="utf-8")
    run_id = f"{int(t0)}"
    samples: list[float] = []   # 성공한 장의 응답시간(초), 순서대로
    stopped_on_stall = False
    usage_now = fetch_usage(token) if args.usage_every else None
    print(f"응답시간 기록: {log_path}   (run {run_id})"
          + (f" / 시작 usage {usage_now['percent']}%" if usage_now else ""))

    # 어느 계정으로 뽑았는지 라벨. **토큰 값은 절대 안 남긴다** - 파일 이름만 남긴다.
    # 계정을 갈아 끼워 IP 단인지 계정 단인지 가르려면 이 라벨이 로그에 있어야 한다.
    token_label = Path(args.token_file).name if args.token_file else "app-store"

    def record(**row) -> None:
        row["run"] = run_id
        row["token"] = token_label
        row["at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        row["since_start"] = round(time.time() - t0, 2)
        log.write(json.dumps(row, ensure_ascii=False) + "\n")
        log.flush()   # 중간에 죽어도 앞 구간은 남아야 한다

    try:
        for i, (name, tag) in enumerate(plan, 1):
            out_dir = out_root / name
            out_dir.mkdir(parents=True, exist_ok=True)
            dst = out_dir / f"{i:04d}_{slug(tag)}.png"
            existing = next(out_dir.glob(f"*_{slug(tag)}.png"), None)
            if existing and not args.redo:
                skipped += 1
                continue
            pos, neg = build_prompt(bench, name, tag)
            payload = payload_for(bench, pos, neg, args.seed)
            for attempt in range(1, args.retries + 1):
                try:
                    image, meta = generate_one(token, payload)
                    dst.write_bytes(image)
                    done += 1
                    samples.append(meta["elapsed"])
                    if args.usage_every and done % args.usage_every == 0:
                        usage_now = fetch_usage(token)
                    record(n=done, i=i, batch=name, tag=tag, attempt=attempt, ok=True,
                           elapsed=round(meta["elapsed"], 3), status=meta["status"],
                           bytes=meta["bytes"], usage=usage_now)
                    if args.stop_on_stall and meta["elapsed"] > args.stop_on_stall:
                        print(f"[{i}/{len(plan)}] {name}/{tag}  STALL {meta['elapsed']:.1f}s "
                              f"— 중단(--stop-on-stall {args.stop_on_stall:.0f}s)")
                        print(f"\n>>> 스톨 전까지 정상 연속 {done - 1}장 "
                              f"(이 장 포함 {done}장째에서 걸림)")
                        stopped_on_stall = True
                        break
                    eta = (time.time() - t0) / max(done, 1) * (len(plan) - i)
                    recent = samples[-20:]
                    print(f"[{i}/{len(plan)}] {name}/{tag}  OK  {meta['elapsed']:.1f}s "
                          f"(최근20 평균 {sum(recent) / len(recent):.1f}s, "
                          f"남은 예상 {eta / 60:.1f}분)")
                    break
                except Exception as exc:
                    status = getattr(exc, "status", None)
                    headers = getattr(exc, "headers", None) or None
                    record(n=done, i=i, batch=name, tag=tag, attempt=attempt, ok=False,
                           elapsed=round(getattr(exc, "elapsed", 0.0), 3), status=status,
                           error=str(exc)[:200], headers=headers, usage=usage_now)
                    if attempt == args.retries:
                        failed += 1
                        print(f"[{i}/{len(plan)}] {name}/{tag}  FAIL  {exc}")
                    else:
                        wait = 5 * attempt
                        # 429 는 서버가 '얼마나 기다리라'를 말해 준다. 그걸 무시하고 5초 뒤에
                        # 다시 두드리면 재시도를 다 태우고 실패로 적힌다 - 한도가 무엇인지
                        # 재려는 관측에서 정작 그 한도를 못 본 채 끝난다.
                        retry_after = (headers or {}).get("Retry-After") or \
                                      (headers or {}).get("retry-after")
                        if status == 429:
                            try:
                                wait = max(wait, min(float(retry_after), 300.0))
                            except (TypeError, ValueError):
                                wait = max(wait, 60.0)   # 헤더가 없으면 보수적으로
                        print(f"[{i}/{len(plan)}] {name}/{tag}  재시도 {attempt}/{args.retries} "
                              f"({exc}) — {wait:.0f}s 대기"
                              + (f"  헤더 {headers}" if headers else ""))
                        time.sleep(wait)
            if stopped_on_stall:
                break
            # Automation 과 같은 조건: 2초 ±50%
            if i < len(plan):
                time.sleep(max(0.2, args.delay * (1 + random.uniform(-args.jitter, args.jitter))))
    finally:
        log.close()

    print(f"\n완료 {done} / 건너뜀 {skipped} / 실패 {failed}   경과 {(time.time() - t0) / 60:.1f}분")
    print_latency_blocks(samples)
    print(f"저장 위치: {out_root}")
    print(f"응답시간 기록: {log_path}")
    print("다음: python tools/build_interactive_thumbnails.py \"<위 폴더>\"")
    return 0 if failed == 0 else 1


def print_latency_blocks(samples: list[float], block: int = 50) -> None:
    """응답시간을 50장 구간으로 끊어 중앙값·평균을 낸다.

    "400~500장쯤부터 느려진다" 는 보고를 확인하려면 **누적 장수를 가로축**에 놓아야 한다.
    전체 평균 하나로는 뒤쪽 둔화가 앞쪽 빠름에 묻힌다(실제로 그렇게 묻힌다).

    ⚠️ 이 표만으로 QoS 를 단정하지 마라 — 장수와 경과시간은 같이 늘어난다. 둘을 가르는
    것은 JSONL 의 `since_start` 와, 딜레이를 다르게 준 두 번째 판이다.
    """
    if not samples:
        return
    print(f"\n{'구간':<14}{'장수':>5}{'중앙값':>9}{'평균':>9}{'최대':>9}")
    for start in range(0, len(samples), block):
        chunk = sorted(samples[start:start + block])
        mid = chunk[len(chunk) // 2]
        print(f"{start + 1:>5}-{start + len(chunk):<8}{len(chunk):>5}"
              f"{mid:>8.1f}s{sum(chunk) / len(chunk):>8.1f}s{chunk[-1]:>8.1f}s")


if __name__ == "__main__":
    raise SystemExit(main())
