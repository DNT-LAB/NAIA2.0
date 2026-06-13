"""확장 Python 의존성(requirements) 격리 설치 (②단계).

SSOT 원칙(설계 논의):
- 패키지: 본체(현재 venv)가 이미 만족하는 의존성은 **재사용**한다(단일 출처).
  본체에 없는 것만 확장 폴더 안 ``.deps/`` 에 격리 설치하고, 본체에 있는데
  버전이 안 맞으면 **거부**한다(본체 버전을 절대 바꾸지 않음 — SSOT 보호).
- 능력: 무거운 ML(torch/tensorflow/onnxruntime-gpu 등)은 **차단**한다. NAIA의
  ML 추론 단일 출처는 외부 백엔드(ComfyUI 등)다 — 확장은 오케스트레이터.

격리는 ``pip install --only-binary=:all: --target <ext>/.deps`` 로 하고
(wheel-only — 소스 빌드/임의 코드 실행 금지), 로드 시에만 그 경로를
``sys.path`` 에 얹는다. 단 ``sys.modules`` 는 프로세스 전역이라 파일 격리이지
완전한 모듈 격리는 아니다(host conflict를 설치 단계에서 fail-closed로 차단).

pip 실행/host 판정/sys.path는 모두 **현재 백엔드 프로세스**(=본체 venv,
``sys.executable``) 기준 — 포터블에선 user-data/runtime-env venv.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import sysconfig
import time
from importlib import metadata as importlib_metadata
from pathlib import Path
from typing import Any

DEPS_DIRNAME = ".deps"
# 의존성 설치 총량 상한(.deps 압축 해제 크기). manifest로 낮출 수 있고, hard cap은 못 넘는다.
DEFAULT_MAX_INSTALL_MB = 300
HARD_MAX_INSTALL_MB = 800

# 능력 SSOT: 무거운 ML 런타임은 백엔드 위임 — 확장에 in-process 설치 금지.
# 정규화된 패키지명(소문자, '-'/'_' 통일) 기준. onnxruntime(CPU)는 허용한다.
HEAVY_ML_DENYLIST = {
    "torch", "torchvision", "torchaudio",
    "tensorflow", "tensorflow-cpu", "tensorflow-gpu", "tensorflow-intel",
    "jax", "jaxlib", "flax",
    "onnxruntime-gpu", "onnxruntime-directml", "onnxruntime-training",
    "xformers", "triton", "bitsandbytes", "deepspeed",
    "cupy", "cupy-cuda12x", "cupy-cuda11x",
    "diffusers", "transformers", "accelerate", "timm",
    "tensorrt", "paddlepaddle", "paddlepaddle-gpu",
}
# nvidia-* CUDA 런타임 wheel(torch가 끌어오는 대형 묶음)도 차단.
_DENY_PREFIXES = ("nvidia-", "nvidia_")


def _norm_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", str(name or "").strip().lower())


def _parse_requirement(line: str) -> tuple[str, str] | None:
    """requirement 한 줄 → (정규화 이름, 원본 spec). 주석/빈 줄/옵션은 None.

    PEP 508 풀 파싱 대신 이름+spec만 뽑는다. URL/path/VCS requirement는
    거부(이름이 패키지명 형식이 아니면 None)."""
    raw = str(line or "").split("#", 1)[0].strip()
    if not raw or raw.startswith("-"):
        return None
    if "://" in raw or raw.startswith((".", "/")) or raw.startswith("git+"):
        raise ExtensionDepsError(f"URL/경로 requirement는 지원하지 않습니다: {raw}")
    match = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)", raw)
    if not match:
        return None
    return _norm_name(match.group(1)), raw


class ExtensionDepsError(Exception):
    """사용자에게 그대로 보여줄 의존성 처리 실패."""


def normalize_requirements(raw: Any) -> list[str]:
    """manifest python.requirements(list[str]) 정규화 — 문자열만, 중복 제거."""
    if not isinstance(raw, (list, tuple)):
        return []
    seen: set[str] = set()
    result: list[str] = []
    for item in raw:
        text = str(item or "").strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def deps_dir(ext_dir: Path) -> Path:
    return Path(ext_dir) / DEPS_DIRNAME


def has_installed_deps(ext_dir: Path) -> bool:
    target = deps_dir(ext_dir)
    return target.is_dir() and any(target.iterdir())


def inject_syspath(ext_dir: Path) -> None:
    """확장 .deps 를 현재 프로세스 sys.path 앞에 1회 얹는다(로드 직전).

    이미 있으면 무시. 본체 패키지보다 뒤(append 아님, but host reuse가 우선
    이미 import된 모듈은 그대로) — 단 sys.modules 전역 한계는 설치 단계
    host-conflict 차단으로 보완."""
    target = deps_dir(ext_dir)
    if not target.is_dir():
        return
    path_str = str(target.resolve())
    if path_str not in sys.path:
        sys.path.insert(0, path_str)


def _host_version(norm_name: str) -> str | None:
    """본체(현재 venv)에 설치된 패키지 버전 — 없으면 None."""
    try:
        return importlib_metadata.version(norm_name)
    except importlib_metadata.PackageNotFoundError:
        return None
    except Exception:
        return None


def analyze_requirements(reqs: list[str]) -> dict[str, Any]:
    """requirements를 host 재사용/설치 대상/거부로 분류(설치 전 미리보기).

    반환: {host_satisfied: [...], to_install: [...], blocked: [{req, reason}]}.
    - blocked: 무거운 ML denylist / URL requirement / 본체 버전 불만족.
    """
    host_satisfied: list[str] = []
    to_install: list[str] = []
    blocked: list[dict[str, str]] = []
    for req in normalize_requirements(reqs):
        try:
            parsed = _parse_requirement(req)
        except ExtensionDepsError as exc:
            blocked.append({"req": req, "reason": str(exc)})
            continue
        if parsed is None:
            continue
        name, spec = parsed
        if name in HEAVY_ML_DENYLIST or name.startswith(_DENY_PREFIXES):
            blocked.append({
                "req": req,
                "reason": "무거운 ML 패키지는 설치할 수 없습니다 — 추론은 백엔드(ComfyUI 등)에 위임하세요.",
            })
            continue
        host_ver = _host_version(name)
        if host_ver is not None:
            if _spec_satisfied(spec, name, host_ver):
                host_satisfied.append(f"{req}  (본체 {name}=={host_ver} 재사용)")
            else:
                blocked.append({
                    "req": req,
                    "reason": f"본체가 {name}=={host_ver}를 쓰고 있어 다른 버전을 설치할 수 없습니다(SSOT 보호).",
                })
            continue
        to_install.append(req)
    return {"host_satisfied": host_satisfied, "to_install": to_install, "blocked": blocked}


def _spec_satisfied(spec: str, name: str, host_ver: str) -> bool:
    """본체 버전이 requirement spec을 만족하나. packaging 있으면 정확히,
    없으면 보수적으로 '버전 명시 없으면 OK, 있으면 불확실→재사용 허용'."""
    try:
        from packaging.requirements import Requirement
        from packaging.version import Version

        requirement = Requirement(spec)
        if not requirement.specifier:
            return True
        return Version(host_ver) in requirement.specifier
    except Exception:
        # packaging 부재/파싱 실패: 이름만 같으면 재사용 허용(보수적 — 본체를
        # 안 바꾸는 것이 우선이고, 정밀 비교 실패로 거부하면 UX가 나빠진다).
        return True


class ExtensionDepsInstaller:
    """확장 의존성 격리 설치 — pip --target(wheel-only) + 크기 cap + atomic."""

    def __init__(self, ext_dir: Path | str):
        self.ext_dir = Path(ext_dir)

    def install(self, reqs: list[str], *, max_install_mb: int | None = None) -> dict[str, Any]:
        """to_install 항목을 .deps에 격리 설치. host 재사용/거부는 analyze가
        분류 — 여기선 blocked가 있으면 즉시 실패(설치 안 함)."""
        analysis = analyze_requirements(reqs)
        if analysis["blocked"]:
            reasons = "; ".join(f"{b['req']}: {b['reason']}" for b in analysis["blocked"])
            raise ExtensionDepsError(reasons)
        to_install = analysis["to_install"]
        if not to_install:
            return {"installed": [], "host_satisfied": analysis["host_satisfied"], "deps_dir": ""}

        cap = self._resolve_cap(max_install_mb)
        staging = self.ext_dir / f".deps-staging-{int(time.time() * 1000)}"
        try:
            self._pip_target_install(to_install, staging)
            size_mb = _dir_size_mb(staging)
            if size_mb > cap:
                raise ExtensionDepsError(
                    f"의존성 크기({size_mb:.0f}MB)가 상한({cap}MB)을 초과합니다."
                )
            self._atomic_replace(staging)
            return {
                "installed": to_install,
                "host_satisfied": analysis["host_satisfied"],
                "deps_dir": str(deps_dir(self.ext_dir)),
                "size_mb": round(size_mb, 1),
            }
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    def _pip_target_install(self, reqs: list[str], staging: Path) -> None:
        staging.mkdir(parents=True, exist_ok=True)
        cmd = [
            sys.executable, "-m", "pip", "install",
            "--only-binary=:all:",          # wheel-only: 소스 빌드/임의 코드 금지
            "--no-input",
            "--disable-pip-version-check",
            "--no-warn-script-location",
            "--target", str(staging),
            *reqs,
        ]
        env = dict(os.environ)
        env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=600,
                env=env, cwd=str(self.ext_dir),
            )
        except FileNotFoundError:
            raise ExtensionDepsError("pip을 찾을 수 없습니다(런타임 환경 문제).")
        except subprocess.TimeoutExpired:
            raise ExtensionDepsError("의존성 설치 시간이 초과되었습니다.")
        if proc.returncode != 0:
            self._write_pip_log(proc.stdout, proc.stderr)
            raise ExtensionDepsError(self._classify_pip_error(proc.stderr or proc.stdout))

    def _atomic_replace(self, staging: Path) -> None:
        target = deps_dir(self.ext_dir)
        backup: Path | None = None
        if target.exists():
            backup = target.with_name(f"{DEPS_DIRNAME}.bak-{int(time.time() * 1000)}")
            target.replace(backup)
        try:
            staging.replace(target)
        except Exception:
            if backup is not None and not target.exists():
                backup.replace(target)
                backup = None
            raise
        finally:
            if backup is not None:
                shutil.rmtree(backup, ignore_errors=True)

    def _resolve_cap(self, requested: int | None) -> int:
        cap = DEFAULT_MAX_INSTALL_MB
        if isinstance(requested, (int, float)) and requested > 0:
            cap = int(requested)
        return min(cap, HARD_MAX_INSTALL_MB)

    def _write_pip_log(self, stdout: str, stderr: str) -> None:
        try:
            log_dir = self.ext_dir / ".install"
            log_dir.mkdir(parents=True, exist_ok=True)
            (log_dir / "pip.log").write_text(
                f"$ pip install --only-binary=:all: --target .deps ...\n\n[stdout]\n{stdout}\n\n[stderr]\n{stderr}",
                encoding="utf-8",
            )
        except Exception:
            pass

    @staticmethod
    def _classify_pip_error(text: str) -> str:
        low = str(text or "").lower()
        if "could not find a version" in low or "no matching distribution" in low:
            tag = sysconfig.get_platform()
            return (f"설치 가능한 wheel을 찾지 못했습니다(Python {sys.version_info.major}."
                    f"{sys.version_info.minor} / {tag}). 소스 빌드가 필요한 패키지는 지원하지 않습니다.")
        if "only-binary" in low or "no binary" in low:
            return "이 패키지는 wheel(미리 빌드된 바이너리)이 없어 설치할 수 없습니다(소스 빌드 금지)."
        if "network" in low or "timed out" in low or "connection" in low:
            return "네트워크 오류로 의존성을 받지 못했습니다."
        if "resolutionimpossible" in low or "conflict" in low:
            return "의존성 버전 충돌로 설치할 수 없습니다."
        # 마지막 비어있지 않은 줄을 사용자 메시지로(원시 로그는 .install/pip.log).
        lines = [ln.strip() for ln in str(text or "").splitlines() if ln.strip()]
        return f"의존성 설치 실패: {lines[-1] if lines else '알 수 없는 오류'}"


def _dir_size_mb(path: Path) -> float:
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += (Path(root) / name).stat().st_size
            except OSError:
                pass
    return total / (1024 * 1024)


__all__ = [
    "ExtensionDepsError",
    "ExtensionDepsInstaller",
    "analyze_requirements",
    "normalize_requirements",
    "deps_dir",
    "has_installed_deps",
    "inject_syspath",
    "HEAVY_ML_DENYLIST",
]
