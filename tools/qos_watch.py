# -*- coding: utf-8 -*-
"""QoS 관측 워치독 — 응답시간 로그를 100장마다 한 줄로 요약해 표준출력에 흘린다.

`thumb_bench.py --latency-log` 이 쓰는 JSONL 을 따라 읽는다. **100장 경계를 넘을 때만**
한 줄을 내보내고, 실패·중단은 즉시 내보낸다(조용한 실패가 '아직 도는 중'과 구별되지
않으면 워치독이 아니다).

    python tools/qos_watch.py <latency.jsonl> [--every 100] [--run-log <run.log>]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


def median(xs: list[float]) -> float:
    s = sorted(xs)
    return s[len(s) // 2] if s else 0.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("log")
    ap.add_argument("--every", type=int, default=100)
    ap.add_argument("--run-log", default=None)
    ap.add_argument("--poll", type=float, default=20.0)
    args = ap.parse_args()

    log = Path(args.log)
    run_log = Path(args.run_log) if args.run_log else None
    seen = 0            # 읽은 JSONL 줄 수
    ok: list[float] = []
    fails = 0
    last_mark = 0
    first_block: float | None = None
    idle = 0

    while True:
        if not log.exists():
            time.sleep(args.poll)
            continue
        rows = log.read_text(encoding="utf-8", errors="replace").splitlines()
        if len(rows) == seen:
            idle += 1
            # 5분 넘게 한 줄도 안 늘면 멈춘 것이다 — 침묵으로 넘기지 않는다.
            if idle * args.poll >= 300:
                print(f"!! 정체: {int(idle * args.poll)}초 동안 새 기록 없음 "
                      f"(성공 {len(ok)} / 실패 {fails})", flush=True)
                idle = 0
            time.sleep(args.poll)
            continue
        idle = 0
        for line in rows[seen:]:
            try:
                row = json.loads(line)
            except Exception:       # noqa: BLE001
                continue
            if row.get("ok"):
                ok.append(float(row.get("elapsed") or 0.0))
            else:
                fails += 1
                print(f"!! 실패 n={row.get('n')} {row.get('batch')}/{row.get('tag')} "
                      f"status={row.get('status')} {str(row.get('error'))[:110]}", flush=True)
        seen = len(rows)

        while len(ok) >= last_mark + args.every:
            last_mark += args.every
            block = ok[last_mark - args.every:last_mark]
            med = median(block)
            if first_block is None:
                first_block = med
            drift = med / first_block if first_block else 1.0
            recent = ok[-20:]
            usage = ""
            try:
                tail = json.loads(rows[-1])
                u = tail.get("usage") or {}
                if u:
                    usage = f" usage {u.get('percent')}%"
            except Exception:       # noqa: BLE001
                pass
            print(f"[{last_mark}장] 중앙값 {med:.1f}s  평균 {sum(block)/len(block):.1f}s  "
                  f"최대 {max(block):.1f}s  1구간대비 {drift:.2f}x  "
                  f"최근20 {sum(recent)/len(recent):.1f}s  실패 {fails}{usage}", flush=True)

        if run_log and run_log.exists():
            text = run_log.read_text(encoding="utf-8", errors="replace")
            if "Traceback" in text or "완료 " in text:
                for line in text.splitlines()[-3:]:
                    print(f"[run] {line}", flush=True)
                return 0
        time.sleep(args.poll)


if __name__ == "__main__":
    sys.exit(main())
