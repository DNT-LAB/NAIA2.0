"""ANIMA 셋업 진단 정보 - 실패 화면의 [자세히] · [에러 로그 복사](사용자 지정 2026-09-29).

제보에 그대로 붙여 넣을 텍스트 하나로 모은다. 특히 NVIDIA 가 아닌 그래픽 카드(AMD Radeon · Intel)에서 왜 막혔는지가
한눈에 보이게 - nvidia-smi 원문과 Windows 가 본 그래픽 카드 목록을 함께 싣고 판정을 한 줄로 적는다.
- NAIA · OS · 프로필
- GPU: nvidia-smi(설치 검사와 같은 명령의 원문) · Windows 그래픽 카드(Win32_VideoController) · 판정
- 설치: 상태 · 단계 · 코드 · 메시지 · 상세 · 끝난 단계 · Traceback(어디서 났는지 - 엔진 폴더 state/job.json)
- 마지막 요청 오류(검사 · 설치 · 엔진 켜기 … - 서비스가 기억한 것) · 마지막 PC 검사 결과
- 엔진: 상태 · 마지막 시작 오류(Traceback) · engine.log 의 이번 기동 부분
- 설정: 엔진 · 모델 · LoRA 폴더 · 자동 끄기 · VRAM 예약
사용자 폴더(C:\\Users\\이름)는 %USERPROFILE% 로 가린다(공개 제보에 붙여 넣는다). 토큰 · 키는 싣지 않는다.
"""
from __future__ import annotations

import json
import os
import platform
import re
import subprocess
import threading
from datetime import datetime
from pathlib import Path

from . import manifest
from .install import app_version, gpu_probe, validate_gpu
from .runtime import LOG_START_MARK, ManagedEngineError

LOG_LINES = 120          # engine.log 이번 기동 부분에서 싣는 끝줄 수
LOG_WINDOW = 65536       # engine.log 끝에서 읽는 바이트
# PCI 제조사 번호(PNPDeviceID 의 VEN_xxxx) - 드라이버가 없는 카드도 이 번호는 진짜 제조사다
VENDORS = {"10DE": "NVIDIA", "1002": "AMD", "1022": "AMD", "8086": "Intel", "1414": "Microsoft", "5143": "Qualcomm"}
_ADAPTERS_PS = ("[Console]::OutputEncoding=[Text.Encoding]::UTF8; "
                "Get-CimInstance Win32_VideoController | "
                "Select-Object Name,DriverVersion,PNPDeviceID,Status | ConvertTo-Json -Compress")


def _flags():
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _recording(log, run):
    """gpu_probe 에 넘길 run - 명령마다 종료 코드와 출력 원문을 적어 둔다(실패 · 없음도)."""
    def recorded(args, **kwargs):
        try:
            result = run(args, **kwargs)
        except (OSError, subprocess.TimeoutExpired) as exc:
            log.append({"args": list(args), "error": f"{type(exc).__name__}: {exc}"})
            raise
        log.append({"args": list(args), "code": result.returncode, "out": result.stdout or "", "err": result.stderr or ""})
        return result
    return recorded


def windows_adapters(run=None):
    """Windows 가 본 그래픽 카드 [{name, driver, vendor, status}]. 드라이버가 없는 카드는 이름이 'Microsoft 기본 디스플레이
    어댑터' 지만 제조사 번호(VEN_)는 진짜다. Windows 가 아니거나 못 물으면 []."""
    if os.name != "nt":
        return []
    run = run or subprocess.run
    try:
        result = run(["powershell", "-NoProfile", "-NonInteractive", "-Command", _ADAPTERS_PS], capture_output=True,
                     text=True, encoding="utf-8", errors="replace", timeout=20, creationflags=_flags())
        data = json.loads((result.stdout or "").strip() or "[]")
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return []
    adapters = []
    for row in data if isinstance(data, list) else [data]:
        if not isinstance(row, dict):
            continue
        match = re.search(r"VEN_([0-9A-Fa-f]{4})", str(row.get("PNPDeviceID") or ""))
        vendor = VENDORS.get(match.group(1).upper(), "VEN_" + match.group(1).upper()) if match else ""
        adapters.append({"name": str(row.get("Name") or "?"), "driver": str(row.get("DriverVersion") or ""),
                         "vendor": vendor, "status": str(row.get("Status") or "")})
    return adapters


def _no_driver(adapter):
    return "basic display" in adapter["name"].lower() or "기본 디스플레이" in adapter["name"]


def gpu_verdict(gpu, adapters):
    """(코드, 한 줄 설명) - 설치 검사(validate_gpu)와 같은 판정에 Windows 가 본 카드로 까닭을 붙인다."""
    try:
        validate_gpu(gpu)
        return "OK", "NVIDIA GPU 와 드라이버가 ANIMA 엔진 요건(RTX 20 이상 · CUDA 13.0 드라이버)을 만족합니다."
    except ManagedEngineError as exc:
        code, message = exc.code, exc.message
    attempt = " NVIDIA 카드가 확인되어 설치 및 실행을 시도할 수 있습니다. 실제 동작은 실행 시 확인합니다."
    if code == "NO_NVIDIA_GPU":
        nvidia = [a for a in adapters if a["vendor"] == "NVIDIA"]
        if nvidia:
            state = "드라이버가 설치되지 않았습니다" if any(_no_driver(a) for a in nvidia) else "NVIDIA 드라이버(nvidia-smi)를 쓸 수 없습니다"
            return "GPU_PROBE_FAILED", f"NVIDIA 그래픽 카드는 있지만 {state}." + attempt
        others = [a["name"] + (f" (드라이버 없음 · {a['vendor']})" if _no_driver(a) else "")
                  for a in adapters if not (a["vendor"] == "Microsoft" and not _no_driver(a))]
        return code, (f"NVIDIA 그래픽 카드가 없습니다(이 PC: {', '.join(others) or '알 수 없음'}). ANIMA 엔진(ComfyUI CUDA 판)은 "
                      "NVIDIA 전용이라 AMD Radeon · Intel 그래픽에서는 동작하지 않습니다.")
    return code, message + (attempt if gpu is not None else "")


def engine_log_tail(engine_root, lines=LOG_LINES):
    """engine.log 의 이번 기동 부분(마지막 머리줄부터) 끝줄들 - 엔진 폴더가 없거나 못 읽으면 ''."""
    if not engine_root:
        return ""
    path = Path(engine_root) / "state/engine.log"
    try:
        with path.open("rb") as handle:
            handle.seek(max(0, path.stat().st_size - LOG_WINDOW))
            text = handle.read().decode("utf-8", "replace")
    except OSError:
        return ""
    mark = text.rfind(LOG_START_MARK)
    return "\n".join((text[mark:] if mark >= 0 else text).splitlines()[-lines:])


def mask_home(text, home=None):
    """사용자 폴더(C:\\Users\\이름)를 %USERPROFILE% 로 - 대소문자 · 슬래시 · JSON 이스케이프 모양 모두."""
    home = str(home or Path.home()).rstrip("\\/")
    if len(home) < 4:                 # 'C:' 같은 짧은 값은 가리지 않는다(글자 전체를 먹는다)
        return text
    for variant in (home.replace("\\", "\\\\"), home, home.replace("\\", "/")):
        text = re.sub(re.escape(variant), "%USERPROFILE%", text, flags=re.IGNORECASE)
    return text


def _indent(text, prefix="    "):
    return "\n".join(prefix + line for line in str(text).rstrip().splitlines())


def build_report(*, settings, install, journal=None, job_trace="", job_phases=(), request_error=None, checks=None,
                 engine=None, engine_error=None, comfyui_engine="", run=None, now=None, home=None):
    """진단 텍스트 - 모자라거나 실패한 조회는 그 자리에 적고 넘어간다(진단은 멈추지 않는다)."""
    run = run or subprocess.run
    journal = journal or {}
    error = journal.get("error") or {}
    out = []
    add = out.append
    stamp = (now or datetime.now().astimezone()).isoformat(timespec="seconds")
    add(f"NAIA ANIMA 진단 정보 · {stamp}")
    add(f"NAIA {app_version()} · {platform.system()} {platform.release()} ({platform.version()}) {platform.machine()}"
        f" · Python {platform.python_version()}")
    add(f"프로필 {manifest.PROFILE_ID} r{manifest.PROFILE_REVISION} · 런타임 {manifest.RUNTIME_ID}"
        f" · 생성 엔진 선택 {comfyui_engine or '-'}")

    add("")
    add("[GPU]")
    # Windows 조회(PowerShell 이 뜨는 데 몇 초)는 nvidia-smi 와 함께 돌린다
    found = {}
    asker = threading.Thread(target=lambda: found.update(adapters=windows_adapters(run)), daemon=True)
    asker.start()
    log = []
    try:
        gpu = gpu_probe(run=_recording(log, run))
    except Exception as exc:          # noqa: BLE001 - 진단은 멈추지 않는다
        gpu = None
        log.append({"args": ["nvidia-smi"], "error": f"{type(exc).__name__}: {exc}"})
    for entry in log:
        name = " ".join(entry["args"][:2]) if len(entry["args"]) > 1 and entry["args"][1].startswith("--query") else "nvidia-smi"
        if "error" in entry:
            add(f"{name}: 실행 못 함 - {entry['error']}")
            continue
        body = entry["out"] if name != "nvidia-smi" else "\n".join(
            line for line in entry["out"].splitlines() if "Driver Version" in line or "CUDA Version" in line)
        add(f"{name}: 종료 코드 {entry['code']}")
        if body.strip():
            add(_indent(body))
        if entry["err"].strip():
            add(_indent("stderr: " + entry["err"].strip().splitlines()[0]))
    asker.join(timeout=30)
    adapters = found.get("adapters") or []
    add("Windows 가 본 그래픽 카드:" if adapters else "Windows 가 본 그래픽 카드: (조회 못 함)")
    for a in adapters:
        bits = [a["name"], a["vendor"], f"드라이버 {a['driver']}" if a["driver"] else "드라이버 없음", a["status"]]
        add("  - " + " · ".join(bit for bit in bits if bit))
    if gpu is not None:
        add(f"선택 GPU: {gpu.name} · 드라이버 {gpu.driver or '?'} · Compute Capability {gpu.compute_cap or '?'}"
            f" · CUDA {gpu.cuda_version or '?'} · 조회 {gpu.source}")
    code, reason = gpu_verdict(gpu, adapters)
    add(f"판정: {code} - {reason}")

    add("")
    add("[설치]")
    add(f"상태 {install.get('state') or '-'} · 단계 {install.get('phase') or journal.get('phase') or '-'}"
        f" · 코드 {install.get('code') or error.get('code') or '-'}")
    message = install.get("message") or error.get("message")
    if message:
        add(f"메시지: {message}")
    detail = install.get("detail") or error.get("detail")
    if detail:
        add("상세:")
        add(_indent(detail))
    phases = list(job_phases) or journal.get("completed_phases") or []
    if journal.get("job_id") or phases:
        add(f"작업 {journal.get('job_id') or install.get('job_id') or '-'} · 시작 {journal.get('started_at') or '-'}"
            f" · 갱신 {journal.get('updated_at') or '-'} · 끝난 단계 {', '.join(phases) or '-'}")
    trace = job_trace or error.get("trace") or ""
    if trace:
        add("Traceback(어디서 났는지):")
        add(_indent(trace))

    if request_error:
        add("")
        add(f"[마지막 요청 오류] {request_error.get('action') or '-'} · {request_error.get('at') or '-'}")
        add(f"코드 {request_error.get('code') or '-'} · {request_error.get('message') or ''}")
        if request_error.get("detail"):
            add("상세:")
            add(_indent(request_error["detail"]))
        if request_error.get("trace"):
            add("Traceback(어디서 났는지):")
            add(_indent(request_error["trace"]))

    if checks:
        add("")
        add("[PC 검사] 마지막 결과")
        for check in checks:
            mark = "⚠" if check.get("warning") else "✓" if check.get("ok") else "✕"
            add(f"  {mark} {check.get('id')}" + (f" {check['code']}" if check.get("code") else "")
                + (f" - {check['message']}" if check.get("message") else ""))

    engine = engine or {}
    add("")
    add("[엔진]")
    add(f"상태 {engine.get('state') or 'stopped'} · 포트 {engine.get('port') or '-'} · 코드 {engine.get('code') or '-'}"
        + (f" · {engine['message']}" if engine.get("message") else ""))
    if engine_error:
        add(f"마지막 시작 오류 {engine_error.get('at') or '-'} · {engine_error.get('code') or '-'} · {engine_error.get('message') or ''}")
        if engine_error.get("trace"):
            add("Traceback(어디서 났는지):")
            add(_indent(engine_error["trace"]))
    tail = engine_log_tail(settings.engine_root)
    if tail:
        add(f"engine.log 이번 기동(끝 {LOG_LINES}줄까지):")
        add(_indent(tail))
    else:
        add("engine.log: 없음(엔진을 켠 적이 없거나 설치 위치가 없다)")

    add("")
    add("[설정]")
    add(f"설치 위치 {settings.engine_root or '(정하지 않음)'}")
    add(f"모델 폴더 {', '.join(settings.unet_dirs) or '기본'} · LoRA 폴더 {', '.join(settings.lora_dirs) or '없음'}"
        f" · 자동 끄기 {settings.idle_minutes}분 · VRAM 예약 {settings.reserve_vram_gb}")
    return mask_home("\n".join(out), home)
