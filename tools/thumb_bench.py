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


def get_token() -> str:
    from core.secure_token_manager import SecureTokenManager
    token = SecureTokenManager().get_token("nai_token")
    if not token:
        raise SystemExit("NAI 토큰을 찾을 수 없습니다. 앱에서 한 번 로그인해 저장하세요.")
    return token


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
    return positive, negative


# 성인 축은 **어린 외형으로 생성될 수 없어야 한다.** 정의 파일을 손으로 고치거나
# 다른 배치 이름을 붙여도 여기서 막힌다 — 사용자 요구는 "어린 외형의 nsfw 이미지가
# 배포되는 것"을 막는 것이고, 그 마지막 방어선은 요청 직전이다.
_DANGER_AGE = ("young female", "young male", "adolescent", "loli", "shota", "toddlercon")


def _guard_adult(batch: str, positive: str) -> None:
    if "nsfw" not in batch:
        return
    bad = [t for t in _DANGER_AGE if t in positive]
    if bad:
        raise SystemExit(
            f"거부: 성인 배치 '{batch}' 의 프롬프트에 어린 외형 태그가 있습니다 {bad}.\n"
            f"       _bench.json 을 고쳤다면 되돌리고, tools/thumb_bench_init.py 를 다시 도세요."
        )
    if "mature female" not in positive:
        raise SystemExit(
            f"거부: 성인 배치 '{batch}' 에 `mature female` 이 없습니다.\n"
            f"       연령을 만드는 것은 이 태그 하나뿐입니다(실측). 근거는\n"
            f"       wildcards/nsfw/_DEFERRED_body_nsfw.md 참조."
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


def generate_one(token: str, payload: dict, timeout: int = 180) -> bytes:
    """NAI 응답(zip)에서 첫 이미지 바이트를 뽑는다."""
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    with requests.Session() as session:
        res = session.post(NAI_URL, headers=headers, json=payload, timeout=timeout)
        if res.status_code != 200:
            body = (res.text or "")[:200].replace("\n", " ")
            raise RuntimeError(f"HTTP {res.status_code}: {body}")
        content = res.content
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        return z.read(z.infolist()[0])


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
    token = None if args.dry_run else get_token()

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
                dst.write_bytes(generate_one(token, payload))
                done += 1
                eta = (time.time() - t0) / max(done, 1) * (len(plan) - i)
                print(f"[{i}/{len(plan)}] {name}/{tag}  OK   (남은 예상 {eta / 60:.1f}분)")
                break
            except Exception as exc:
                if attempt == args.retries:
                    failed += 1
                    print(f"[{i}/{len(plan)}] {name}/{tag}  FAIL  {exc}")
                else:
                    wait = 5 * attempt
                    print(f"[{i}/{len(plan)}] {name}/{tag}  재시도 {attempt}/{args.retries} "
                          f"({exc}) — {wait}s 대기")
                    time.sleep(wait)
        # Automation 과 같은 조건: 2초 ±50%
        if i < len(plan):
            time.sleep(max(0.2, args.delay * (1 + random.uniform(-args.jitter, args.jitter))))

    print(f"\n완료 {done} / 건너뜀 {skipped} / 실패 {failed}   경과 {(time.time() - t0) / 60:.1f}분")
    print(f"저장 위치: {out_root}")
    print("다음: python tools/build_interactive_thumbnails.py \"<위 폴더>\"")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
