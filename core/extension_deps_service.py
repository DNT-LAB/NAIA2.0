"""확장 Python 의존성(requirements) 격리 설치 (②단계).

SSOT 원칙(설계 논의):
- 패키지: 본체(현재 venv)가 이미 만족하는 의존성은 **재사용**한다(단일 출처).
  본체에 없는 것만 확장 폴더 안 ``.deps/`` 에 격리 설치하고, 본체에 있는데
  버전이 안 맞으면 **거부**한다(본체 버전을 절대 바꾸지 않음 — SSOT 보호).
- 능력: 무거운 ML(torch/tensorflow/onnxruntime-gpu 등)은 **차단**한다. NAIA의
  ML 추론 단일 출처는 외부 백엔드(ComfyUI 등)다 — 확장은 오케스트레이터.

격리는 ``pip install --only-binary=:all: --target <ext>/.deps`` 로 하고
(wheel-only — 소스 빌드/임의 코드 실행 금지), 로드 시에만 그 경로를
``sys.path`` 에 얹는다.

⚠️ 격리의 한계(정직한 계약):
- ``sys.modules`` 는 프로세스 전역이라 이것은 **파일 격리**이지 완전한 모듈
  격리가 아니다. 같은 패키지를 다른 버전으로 쓰는 두 확장은 먼저 import된
  쪽이 이긴다(true isolation은 subprocess/subinterpreter 필요 — v2 과제).
  대신 host-conflict를 **설치 단계에서 전이 의존성까지 fail-closed로 차단**해
  본체 패키지 shadowing을 막는다.
- requirement 문자열은 PEP 508 직접 참조(``name @ url``·``git+``·로컬 경로·
  ``.whl``)와 옵션 토큰(``-r``·``--index-url``)을 **거부**한다(설치 전 검증).
- 전이 의존성은 ``pip --dry-run --report`` 로 미리 해석해 **해석된 모든 배포**를
  denylist·host 버전 정책에 통과시켜야만 실제 설치한다(transitive heavy ML 차단).

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
from collections.abc import Iterator
from contextlib import contextmanager
from importlib import metadata as importlib_metadata
from pathlib import Path
from typing import Any

DEPS_DIRNAME = ".deps"
# .deps 와 분리해 ext 루트에 두는 설치 매니페스트(서명) — deps_ready 판정용.
DEPS_MANIFEST_NAME = ".naia_deps.json"
# 의존성 설치 총량 상한(.deps 압축 해제 크기). manifest로 낮출 수 있고, hard cap은 못 넘는다.
DEFAULT_MAX_INSTALL_MB = 300
HARD_MAX_INSTALL_MB = 800
# 전이 의존성 해석/설치 subprocess 타임아웃(초).
_PIP_TIMEOUT = 600

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

# packaging 부재 시 fallback 화이트리스트: name[extras] + 선택적 버전 스펙(들).
_STRICT_REQ_RE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._-]*"                       # 이름
    r"(?:\[[A-Za-z0-9,._-]+\])?"                          # 선택: extras
    r"(?:\s*(?:===|==|~=|!=|<=|>=|<|>)\s*[A-Za-z0-9][A-Za-z0-9.*+!_-]*"
    r"(?:\s*,\s*(?:===|==|~=|!=|<=|>=|<|>)\s*[A-Za-z0-9][A-Za-z0-9.*+!_-]*)*)?$"
)
_BARE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class ExtensionDepsError(Exception):
    """사용자에게 그대로 보여줄 의존성 처리 실패."""


# ── packaging 로더 (본체 → pip 내장 vendored 폴백) ──────────────────


def _requirement_cls() -> Any:
    """packaging.requirements.Requirement — 본체 우선, 없으면 pip 내장."""
    try:
        from packaging.requirements import Requirement

        return Requirement
    except Exception:
        pass
    try:
        from pip._vendor.packaging.requirements import Requirement

        return Requirement
    except Exception:
        return None


def _version_cls() -> Any:
    try:
        from packaging.version import Version

        return Version
    except Exception:
        pass
    try:
        from pip._vendor.packaging.version import Version

        return Version
    except Exception:
        return None


def _norm_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", str(name or "").strip().lower())


def _parse_requirement(line: str) -> tuple[str, str] | None:
    """requirement 한 줄 → (정규화 이름, 원본 spec). 주석/빈 줄은 None.

    fail-closed: URL/경로/VCS 직접 참조(PEP 508 ``name @ url``·``file:``·``git+``·
    로컬 경로·``.whl``)와 옵션 토큰(``-r``·``--index-url``)·해석 불가한 줄은
    **거부**(예외)한다. wheel-only·소스 빌드 금지 계약을 설치 전에 강제한다."""
    raw = str(line or "").strip()
    if not raw or raw.startswith("#"):
        return None
    if raw.startswith("-"):
        raise ExtensionDepsError(f"옵션 토큰은 requirement로 쓸 수 없습니다: {raw}")
    low = raw.lower()
    # 노골적 URL/VCS/경로(이름 없이 시작하는 형태).
    if "://" in raw or low.startswith("git+") or raw.startswith((".", "/")):
        raise ExtensionDepsError(f"URL/경로/VCS requirement는 지원하지 않습니다: {raw}")

    requirement_cls = _requirement_cls()
    if requirement_cls is not None:
        try:
            req = requirement_cls(raw)
        except Exception:
            raise ExtensionDepsError(f"요구사항 형식을 해석할 수 없습니다: {raw}")
        # PEP 508 직접 참조(name @ url)는 req.url 로 잡힌다 — 거부.
        if getattr(req, "url", None):
            raise ExtensionDepsError(f"URL/경로/VCS requirement는 지원하지 않습니다: {raw}")
        if not req.name:
            raise ExtensionDepsError(f"요구사항 형식을 해석할 수 없습니다: {raw}")
        return _norm_name(req.name), raw

    # packaging/pip 둘 다 없을 때: 엄격 화이트리스트(이외 전부 거부).
    if "@" in raw:
        raise ExtensionDepsError(f"URL/경로/VCS requirement는 지원하지 않습니다: {raw}")
    if not _STRICT_REQ_RE.match(raw):
        raise ExtensionDepsError(f"요구사항 형식을 해석할 수 없습니다: {raw}")
    match = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)", raw)
    return _norm_name(match.group(1)), raw


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


def _manifest_path(ext_dir: Path) -> Path:
    return Path(ext_dir) / DEPS_MANIFEST_NAME


def has_installed_deps(ext_dir: Path) -> bool:
    """.deps 디렉터리에 실제 패키지가 들어있나(payload 존재)."""
    target = deps_dir(ext_dir)
    return target.is_dir() and any(target.iterdir())


def _read_manifest(ext_dir: Path) -> dict[str, Any] | None:
    try:
        return json.loads(_manifest_path(ext_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def deps_satisfy(ext_dir: Path, requirements: Any) -> bool:
    """선언 requirements가 이미 설치 완료된 상태인가(서명 비교).

    매니페스트(.naia_deps.json)의 requirements 서명이 현재 선언과 일치하고,
    설치 payload가 필요하면 .deps도 실재해야 True. 매니페스트가 없는 옛 설치는
    .deps 존재로만 하위호환 판정. **전부 host-satisfied(설치 0)** 인 경우 .deps
    없이도 매니페스트 서명만 맞으면 True(noop 정상 로드)."""
    reqs = normalize_requirements(requirements)
    if not reqs:
        return True
    manifest = _read_manifest(ext_dir)
    if manifest is None:
        # 매니페스트 없는 옛 .deps: 존재하면 ready로 본다(하위호환).
        return has_installed_deps(ext_dir)
    want = sorted(_norm_name(r) for r in reqs)
    have = sorted(_norm_name(r) for r in (manifest.get("requirements") or []))
    if want != have:
        return False
    # 설치된 패키지가 있다고 기록됐으면 .deps payload가 실재해야 한다(크래시 방어).
    if manifest.get("installed"):
        return has_installed_deps(ext_dir)
    return True


def recover_orphaned_deps(ext_dir: Path) -> bool:
    """크래시로 .deps가 사라지고 .deps.bak-*만 남았으면 최신 백업 복원(Low2)."""
    target = deps_dir(ext_dir)
    if target.exists():
        return False
    backups = sorted(Path(ext_dir).glob(f"{DEPS_DIRNAME}.bak-*"))
    if not backups:
        return False
    try:
        backups[-1].replace(target)
    except OSError:
        return False
    for stale in backups[:-1]:
        shutil.rmtree(stale, ignore_errors=True)
    return True


def inject_syspath(ext_dir: Path) -> None:
    """확장 .deps 를 현재 프로세스 sys.path 앞에 1회 얹는다(로드 직전).

    ⚠️ sys.modules는 프로세스 전역이라 완전 격리가 아니다(모듈 셰도잉 가능).
    이미 import된 본체 모듈은 그대로이고, 전이 host-conflict는 설치 단계에서
    차단한다. 확장-확장 간 같은 패키지 다른 버전은 먼저 로드된 쪽이 이긴다
    (true isolation은 subprocess/subinterpreter 필요 — 문서화된 v1 한계)."""
    target = deps_dir(ext_dir)
    if not target.is_dir():
        return
    path_str = str(target.resolve())
    if path_str not in sys.path:
        sys.path.insert(0, path_str)


@contextmanager
def extension_syspath(ext_dir: Path) -> Iterator[None]:
    """확장 .deps 를 현재 실행 경계 안에서만 sys.path 앞에 둔다."""
    target = deps_dir(ext_dir)
    if not target.is_dir():
        yield
        return
    path_str = str(target.resolve())
    inserted = False
    if path_str not in sys.path:
        sys.path.insert(0, path_str)
        inserted = True
    try:
        yield
    finally:
        if inserted:
            try:
                sys.path.remove(path_str)
            except ValueError:
                pass


def _host_version(norm_name: str) -> str | None:
    """본체(현재 venv)에 설치된 패키지 버전 — 없으면 None."""
    try:
        return importlib_metadata.version(norm_name)
    except importlib_metadata.PackageNotFoundError:
        return None
    except Exception:
        return None


def _spec_satisfied(spec: str, name: str, host_ver: str) -> bool:
    """본체 버전이 requirement spec을 만족하나. **fail-closed**: 파서 부재/파싱
    실패 시 bare 이름(버전 제약 없음)일 때만 재사용 허용, 그 외엔 거부(SSOT)."""
    requirement_cls = _requirement_cls()
    version_cls = _version_cls()
    if requirement_cls is not None and version_cls is not None:
        try:
            requirement = requirement_cls(spec)
            if not requirement.specifier:
                return True
            return version_cls(host_ver) in requirement.specifier
        except Exception:
            return bool(_BARE_NAME_RE.match(str(spec or "").strip()))
    # 파서 자체가 없으면 bare 이름만 재사용 허용(버전 비교 불가 → 보수적 거부).
    return bool(_BARE_NAME_RE.match(str(spec or "").strip()))


def analyze_requirements(reqs: list[str]) -> dict[str, Any]:
    """requirements를 host 재사용/설치 대상/거부로 분류(설치 전 미리보기 — 최상위만).

    반환: {host_satisfied: [...], to_install: [...], blocked: [{req, reason}]}.
    - blocked: 무거운 ML denylist / URL·옵션·형식 오류 / 본체 버전 불만족.
    ⚠️ 전이 의존성 검증은 설치 단계(_resolve_install_set)에서 별도로 한다."""
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


def _validate_resolved_dists(resolved: list[dict[str, str]]) -> list[str]:
    """pip이 .deps에 실제로 넣을(전이 포함) 배포 집합을 정책 검증 → 위반 사유 목록.

    빈 목록이면 통과. 무거운 ML(전이 포함)·본체와 다른 버전(shadow 위험)을 잡는다.
    순수 함수(네트워크 무관) — 단위 테스트 가능."""
    violations: list[str] = []
    for dist in resolved:
        norm = _norm_name(dist.get("name", ""))
        if not norm:
            continue
        version = str(dist.get("version") or "")
        if norm in HEAVY_ML_DENYLIST or norm.startswith(_DENY_PREFIXES):
            violations.append(f"{dist.get('name')}=={version} (무거운 ML — 백엔드 위임)")
            continue
        host_ver = _host_version(norm)
        if host_ver is not None and version and host_ver != version:
            violations.append(
                f"{dist.get('name')}=={version} (본체 {host_ver}와 충돌 — SSOT 보호)"
            )
    return violations


class ExtensionDepsInstaller:
    """확장 의존성 격리 설치 — 전이 검증(dry-run) + pip --target(wheel-only) +
    크기 cap + atomic + 설치 매니페스트."""

    def __init__(self, ext_dir: Path | str):
        self.ext_dir = Path(ext_dir)

    def install(self, reqs: list[str], *, max_install_mb: int | None = None) -> dict[str, Any]:
        """선언 requirements를 격리 설치. blocked(최상위)면 즉시 실패, 전이 의존성은
        dry-run으로 해석해 정책 검증 후에만 실제 설치한다. 전부 host-satisfied면
        설치 없이 매니페스트만 기록(noop)."""
        recover_orphaned_deps(self.ext_dir)
        analysis = analyze_requirements(reqs)
        if analysis["blocked"]:
            reasons = "; ".join(f"{b['req']}: {b['reason']}" for b in analysis["blocked"])
            raise ExtensionDepsError(reasons)

        to_install = analysis["to_install"]
        resolved: list[dict[str, str]] = []
        size_mb = 0.0
        if to_install:
            cap = self._resolve_cap(max_install_mb)
            staging = self.ext_dir / f".deps-staging-{int(time.time() * 1000)}"
            try:
                resolved = self._resolve_install_set(to_install, staging)
                self._pip_target_install(to_install, staging)
                size_mb = _dir_size_mb(staging)
                if size_mb > cap:
                    raise ExtensionDepsError(
                        f"의존성 크기({size_mb:.0f}MB)가 상한({cap}MB)을 초과합니다."
                    )
                self._atomic_replace(staging)
            finally:
                shutil.rmtree(staging, ignore_errors=True)

        # 매니페스트 기록(noop 포함) → deps_ready가 서명으로 일관 판정.
        self._write_manifest(reqs, resolved, size_mb)
        return {
            "installed": [d["name"] for d in resolved],
            "host_satisfied": analysis["host_satisfied"],
            "deps_dir": str(deps_dir(self.ext_dir)) if resolved else "",
            "size_mb": round(size_mb, 1),
        }

    def _resolve_install_set(self, reqs: list[str], staging: Path) -> list[dict[str, str]]:
        """pip --dry-run --report 로 전이 의존성까지 해석 → .deps에 들어갈 배포 집합.

        해석된 배포 중 무거운 ML/host 버전 충돌이 하나라도 있으면 설치 거부(High2).
        실제 설치 전에 doit — 다운로드/빌드 작업이 일어나기 전에 차단한다."""
        staging.mkdir(parents=True, exist_ok=True)
        report_path = self.ext_dir / f".deps-report-{int(time.time() * 1000)}.json"
        cmd = [
            sys.executable, "-m", "pip", "install",
            "--only-binary=:all:",
            "--no-input",
            "--disable-pip-version-check",
            "--dry-run",
            "--report", str(report_path),
            "--target", str(staging),
            *reqs,
        ]
        try:
            proc = self._run_pip(cmd)
            if proc.returncode != 0:
                self._write_pip_log(proc.stdout, proc.stderr)
                raise ExtensionDepsError(self._classify_pip_error(proc.stderr or proc.stdout))
            resolved = self._parse_report(report_path)
        finally:
            try:
                report_path.unlink()
            except OSError:
                pass
        violations = _validate_resolved_dists(resolved)
        if violations:
            raise ExtensionDepsError(
                "전이 의존성이 정책을 위반합니다(설치 거부): " + "; ".join(violations)
            )
        return resolved

    @staticmethod
    def _parse_report(report_path: Path) -> list[dict[str, str]]:
        """pip --report JSON → [{name, version}, ...] (install 목록)."""
        try:
            data = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ExtensionDepsError("의존성 해석 보고서를 읽지 못했습니다.") from exc
        out: list[dict[str, str]] = []
        for item in (data.get("install") or []):
            meta = item.get("metadata") or {}
            name = meta.get("name")
            if name:
                out.append({"name": str(name), "version": str(meta.get("version") or "")})
        return out

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
        proc = self._run_pip(cmd)
        if proc.returncode != 0:
            self._write_pip_log(proc.stdout, proc.stderr)
            raise ExtensionDepsError(self._classify_pip_error(proc.stderr or proc.stdout))

    def _run_pip(self, cmd: list[str]) -> subprocess.CompletedProcess:
        env = dict(os.environ)
        env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
        try:
            return subprocess.run(
                cmd, capture_output=True, text=True, timeout=_PIP_TIMEOUT,
                env=env, cwd=str(self.ext_dir),
            )
        except FileNotFoundError:
            raise ExtensionDepsError("pip을 찾을 수 없습니다(런타임 환경 문제).")
        except subprocess.TimeoutExpired:
            raise ExtensionDepsError("의존성 설치 시간이 초과되었습니다.")

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

    def _write_manifest(self, declared: list[str], resolved: list[dict[str, str]],
                        size_mb: float) -> None:
        """설치 서명을 ext 루트(.naia_deps.json)에 기록 — deps_ready 판정용(Low1).

        ``requirements`` 는 **선언된** 전체 목록(host-satisfied 포함)이라 deps_ready가
        선언과 1:1로 비교한다."""
        try:
            _manifest_path(self.ext_dir).write_text(
                json.dumps(
                    {
                        "requirements": list(normalize_requirements(declared)),
                        "installed": [f"{d['name']}=={d['version']}" for d in resolved],
                        "size_mb": round(size_mb, 1),
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
        except Exception:
            pass

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
    "deps_satisfy",
    "extension_syspath",
    "has_installed_deps",
    "inject_syspath",
    "recover_orphaned_deps",
    "HEAVY_ML_DENYLIST",
]
