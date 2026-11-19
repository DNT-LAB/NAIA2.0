"""Build targets, generate preset thumbnails from a shared list, or report progress."""

import argparse
import json
import os
import random
import sys
import time
from collections import Counter, deque
from pathlib import Path

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.build_preset_thumb_targets import (
    DEFAULT_OUT_DIR, KIND_ORDER, build_targets, completed_keys, load_templates,
)
from tools.character_pack_generate import (
    ACCOUNTS, CLAIM_STALE_SECONDS, SLOW_SECONDS, TOOL,
    _anlas, _claim, _load_client, _log, _v5_extra, _v5_usage,
)

# 구독이 살아 있는 두 계정만 쓴다(사용자 11-18: "0UY, MYT 만 남기고" - GN5 · BKN 은 구독 만료로 trial 400).
PRESET_ACCOUNTS = ("MYT", "0UY")
# Anlas 를 써서라도 계속 그리는 계정(사용자 11-18: "0UY 는 Anlas 를 소비하도록" - 사용량 상태가 애매하다).
# 이 계정은 Anlas 가 줄어도 멈추지 않는다. 바닥나면 서비스가 402 로 거절해 AccountRefused 로 멈춘다.
ANLAS_SPEND_ACCOUNTS = ("0UY",)


class AccountRefused(Exception):
    """The service refused this account (no subscription, bad token) - retrying cannot help."""


def _say(message: str) -> None:
    print(message.encode("ascii", "backslashreplace").decode("ascii"), flush=True)


def _read_targets(out_dir: Path) -> dict:
    try:
        return json.loads((out_dir / "_targets.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SystemExit("Missing _targets.json. Run targets first.") from None


def _claim_key(out_dir: Path, key: str) -> Path | None:
    claim = out_dir / f"{key}.claim"
    for _ in range(2):
        try:
            with claim.open("x", encoding="ascii") as fp:
                fp.write(str(os.getpid()))
            return claim
        except FileExistsError:
            pass
        try:
            cutoff = time.time() - CLAIM_STALE_SECONDS
            if claim.stat().st_mtime > cutoff:
                return None
            # Serialize stale-file removal so a second reaper cannot unlink a new
            # owner's claim. Rank zero is outside the 16-character key namespace.
            recovery_lock = _claim(out_dir, 0)
            if recovery_lock is None:
                return None
            try:
                if claim.stat().st_mtime <= cutoff:
                    claim.unlink()
            finally:
                recovery_lock.unlink(missing_ok=True)
        except FileNotFoundError:
            continue
    return None


def _payload_v5(client, settings: dict, target: dict, seed: int) -> dict:
    payload = client.build_payload(
        prompt=target["prompt"], negative_prompt=settings["negative_prompt"], model=settings["model"],
        width=target["width"], height=target["height"], steps=settings["steps"],
        cfg_scale=settings["cfg_scale"], cfg_rescale=settings["cfg_rescale"],
        sampler=settings["sampler"], noise_schedule=settings["noise_schedule"], seed=seed,
    )
    payload["model"] = settings["api_model"]
    payload["parameters"].pop("skip_cfg_above_sigma", None)
    return payload


def _generate_png(client, payload: dict, token: str, label: str, key: str, stop: Path, logf) -> bytes | None:
    for attempt in range(1, 6):
        if stop.is_file():
            return None
        began = time.monotonic()
        try:
            png = client.generate(payload, token, timeout=120, model="NAID5F")
            if not png:
                raise ValueError("empty image response")
            return png
        except Exception as exc:
            message = str(exc)[:200]
            _log(logf, ev="retry", account=label, key=key, attempt=attempt, err=message,
                 took=round(time.monotonic() - began, 1))
            # 계정 자체가 못 그리는 응답(구독 없음 = 'trial generation' 400 · 인증 401/403)은 다시 보내도 같다 - 이 계정을 바로 멈춘다.
            if any(f"NAI HTTP {code}" in message for code in (400, 401, 402, 403)):
                raise AccountRefused(message) from exc
            _say(f"[{label}] {key} retry {attempt}: {message[:90]}")
            time.sleep(20 if "429" in message else 5 * attempt)
    return None


def _stop(logf, label: str, reason: str, done: int, **details) -> str:
    _log(logf, ev=reason, account=label, done=done, **details)
    _say(f"[{label}] {reason} done={done}")
    return reason


def run_account(label: str, out_dir: Path, limit: int | None = None) -> str:
    document = _read_targets(out_dir)
    template = load_templates()
    version = document["template_version"]
    if version != template["template_version"]:
        raise SystemExit("Template version changed. Rebuild targets first.")
    settings = template["generation"]
    client = _load_client()
    sizes = {tuple(size) for size in template["resolutions"].values()}
    sizes.update((target["width"], target["height"]) for target in document["targets"])
    unsafe = [(w, h) for w, h in sorted(sizes) if not client.is_free_generation(settings["steps"], w, h)]
    if unsafe:
        raise SystemExit(f"Outside free generation band: {unsafe}")

    existing = completed_keys(out_dir)
    items = [t for t in document["targets"] if t["key"] not in existing]
    stop = out_dir / "STOP"
    done = give_ups = 0
    recent = deque(maxlen=10)
    with (
        (out_dir / f"run_{label}.jsonl").open("a", encoding="utf-8", newline="\n") as logf,
        (out_dir / f"manifest_{label}.jsonl").open("a", encoding="utf-8", newline="\n") as manifest,
    ):
        if stop.is_file():
            return _stop(logf, label, "stop_file", done)
        if not items or limit == 0:
            _log(logf, ev="account_done", account=label, done=0)
            _say(f"[{label}] finished new=0")
            return "done"
        token = (TOOL / ACCOUNTS[label]).read_text(encoding="utf-8").strip()
        start_anlas = _anlas(client, token)
        _log(logf, ev="account_start", account=label, todo=len(items), anlas=start_anlas)
        _log(logf, ev="v5_usage", account=label, percent=_v5_usage(client, token))
        spend_ok = label in ANLAS_SPEND_ACCOUNTS
        _say(f"[{label}] start todo={len(items)} anlas={start_anlas} spend_anlas={spend_ok}")

        for target in items:
            if stop.is_file():
                return _stop(logf, label, "stop_file", done)
            key = target["key"]
            path = out_dir / f"{key}.png"
            if path.is_file():
                continue
            claim = _claim_key(out_dir, key)
            if claim is None:
                continue
            try:
                # A peer may have published its PNG between the first check and our claim.
                if path.is_file():
                    continue
                began = time.monotonic()
                seed = random.randint(1, 9_999_999_999)
                payload = _payload_v5(client, settings, target, seed)
                try:
                    png = _generate_png(client, payload, token, label, key, stop, logf)
                except AccountRefused as exc:
                    return _stop(logf, label, "account_refused", done, err=str(exc)[:200])
                if png is None:
                    if stop.is_file():
                        return _stop(logf, label, "stop_file", done)
                    _log(logf, ev="give_up", account=label, key=key)
                    give_ups += 1
                    if give_ups >= 5:
                        return _stop(logf, label, "give_up_streak", done)
                    continue
                part = path.with_suffix(".part")
                part.write_bytes(png)
                part.replace(path)
                _log(manifest, key=key, file=path.name, seed=seed, prompt=target["prompt"],
                     width=target["width"], height=target["height"], template_version=version, account=label)
            finally:
                claim.unlink(missing_ok=True)

            done += 1
            give_ups = 0
            recent.append(time.monotonic() - began)
            if done % 25 == 0:
                now = _anlas(client, token)
                usage, extra = _v5_usage(client, token), _v5_extra(client, token)
                _log(logf, ev="progress", account=label, done=done, anlas=now, start_anlas=start_anlas)
                _log(logf, ev="v5_usage", account=label, done=done, percent=usage, purchased_percent=extra)
                _say(f"[{label}] done={done} anlas={now} v5={usage}% extra={extra}%")
                if not spend_ok and start_anlas is not None and now is not None and now < start_anlas:
                    return _stop(logf, label, "anlas_dropped", done, start=start_anlas, now=now)
            if len(recent) == recent.maxlen:
                average = sum(recent) / len(recent)
                if average > SLOW_SECONDS:
                    return _stop(logf, label, "bucket_empty", done, avg=round(average, 1))
            if limit is not None and done >= limit:
                break
            time.sleep(1.0)
        _log(logf, ev="account_done", account=label, done=done, anlas=_anlas(client, token))
        _say(f"[{label}] finished new={done}")
    return "done"


def status(out_dir: Path) -> None:
    targets = _read_targets(out_dir)["targets"]
    existing = completed_keys(out_dir)
    total = Counter(t["kind"] for t in targets)
    done = Counter(t["kind"] for t in targets if t["key"] in existing)
    for kind in KIND_ORDER:
        _say(f"{kind} {done[kind]}/{total[kind]}")
    _say(f"remaining={len(targets) - sum(done.values())}")

    today = time.strftime("%Y-%m-%d")
    for label in PRESET_ACCOUNTS:
        path = out_dir / f"manifest_{label}.jsonl"
        count = today_count = 0
        if path.is_file():
            with path.open(encoding="utf-8") as manifest:
                for line in manifest:
                    if not line.strip():
                        continue
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        if not line.endswith("\n"):  # A writer is still appending the last record.
                            break
                        raise
                    count += 1
                    if row["t"][:10] == today:
                        today_count += 1
        _say(f"{label} manifest={count} today={today_count}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    targets = sub.add_parser("targets", help="build the shared target list")
    run = sub.add_parser("run", help="generate unclaimed thumbnails for one account")
    report = sub.add_parser("status", help="count saved PNGs and manifest records")
    for command in (targets, run, report):
        command.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    run.add_argument("--account", choices=PRESET_ACCOUNTS, required=True)
    run.add_argument("--any", action="store_true", required=True, help="take work from the shared list")
    run.add_argument("--limit", type=int, help="maximum number of new PNGs")
    args = parser.parse_args()
    if args.command == "targets":
        build_targets(args.out_dir)
    elif args.command == "status":
        status(args.out_dir)
    else:
        if args.limit is not None and args.limit < 0:
            parser.error("--limit must be nonnegative")
        run_account(args.account, args.out_dir, args.limit)


if __name__ == "__main__":
    main()
