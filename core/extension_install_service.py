"""GitHub URL → Custom Extension 자동 설치 (git 불요, zip 다운로드).

git이 설치돼 있지 않은 일반 사용자를 위해 GitHub 레포의 zip 아카이브
(codeload.github.com)를 HTTP로 받아 user-data/extensions/<id>/ 에 푼다.
의존성(requirements) 설치는 별도 슬라이스(②단계) — 이 서비스는 **파일 배치
까지만** 하며, 발견·미승인 등록·승인 절차는 기존 ExtensionManager가 처리한다
(동의 모델 유지: 설치는 코드를 실행하지 않고, 패널이 panel_state로 재발견해
``discovered`` 상태로 띄운다 → 사용자가 명시 승인해야 import).

보안:
- 호스트 화이트리스트(github.com / codeload.github.com) + HTTPS 강제. 임의 URL
  다운로드 금지(SSRF 차단).
- 다운로드/추출 크기 상한(zip 폭탄·디스크 보호).
- zip-slip 방어(추출 멤버 경로가 staging 밖으로 못 나감).
- staging → 원자적 교체. 실패 시 staging 정리(부분 설치 잔재 없음).
- 라우트가 loopback-gated(원격 클라이언트가 host에 코드를 깔지 못함).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from threading import Event, RLock, Thread
from typing import Any
from zipfile import ZipFile

NAIA_EXT_API_VERSION = 1
# 확장 zip 다운로드 상한(코드만 — 의존성은 ②단계 별도). 큰 레포 방어.
MAX_DOWNLOAD_BYTES = 60 * 1024 * 1024      # 60MB
MAX_UNCOMPRESSED_BYTES = 200 * 1024 * 1024  # 200MB(추출 총량)
MAX_MEMBERS = 5000

try:
    import certifi

    SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
except Exception:  # pragma: no cover
    SSL_CONTEXT = ssl.create_default_context()


class ExtensionInstallError(Exception):
    """사용자에게 그대로 보여줄 설치 실패 메시지."""


def _safe_dir_name(ext_id: str) -> str:
    """확장 id를 안전한 디렉터리 이름으로 정규화(경로 탈출·특수문자 차단)."""
    cleaned = re.sub(r"[^0-9A-Za-z_.-]", "_", str(ext_id or "").strip())
    cleaned = cleaned.strip("._-") or "extension"
    return cleaned[:64]


def parse_github_url(url: str) -> tuple[str, str, str | None]:
    """GitHub URL/짧은 형식 → (owner, repo, ref|None). github.com만 허용.

    지원: https://github.com/owner/repo[.git][/tree/<ref>][/...] · owner/repo[@ref]
    ref(브랜치/태그) 미지정이면 None(호출자가 default branch 탐지)."""
    raw = str(url or "").strip()
    if not raw:
        raise ExtensionInstallError("GitHub 주소를 입력하세요.")
    ref: str | None = None
    if "://" in raw or raw.lower().startswith("github.com"):
        parsed = urllib.parse.urlparse(raw if "://" in raw else f"https://{raw}")
        if parsed.scheme not in ("", "https", "http"):
            raise ExtensionInstallError("HTTPS GitHub 주소만 지원합니다.")
        host = (parsed.hostname or "").lower()
        if host not in ("github.com", "www.github.com"):
            raise ExtensionInstallError("github.com 주소만 설치할 수 있습니다.")
        parts = [p for p in parsed.path.split("/") if p]
        if len(parts) < 2:
            raise ExtensionInstallError("owner/repo 형식의 GitHub 주소가 아닙니다.")
        owner, repo = parts[0], parts[1]
        # .../tree/<ref> 또는 .../commit/<ref> 형태면 ref 추출.
        if len(parts) >= 4 and parts[2] in ("tree", "commit"):
            ref = parts[3]
    else:
        # owner/repo 또는 owner/repo@ref 짧은 형식.
        token, _, after = raw.partition("@")
        if after.strip():
            ref = after.strip()
        parts = [p for p in token.split("/") if p]
        if len(parts) != 2:
            raise ExtensionInstallError("owner/repo 형식의 GitHub 주소를 입력하세요.")
        owner, repo = parts
    repo = repo[:-4] if repo.lower().endswith(".git") else repo
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", owner) or not re.fullmatch(r"[A-Za-z0-9_.-]+", repo):
        raise ExtensionInstallError("GitHub owner/repo 이름이 올바르지 않습니다.")
    return owner, repo, ref


def _codeload_url(owner: str, repo: str, ref: str) -> str:
    return f"https://codeload.github.com/{owner}/{repo}/zip/refs/heads/{ref}"


def _detect_default_branch(owner: str, repo: str) -> str:
    """GitHub API로 default branch 조회 — 실패 시 main→master 폴백."""
    api = f"https://api.github.com/repos/{owner}/{repo}"
    request = urllib.request.Request(api, headers={"User-Agent": "NAIA/2.0 Extension Installer",
                                                   "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(request, timeout=15, context=SSL_CONTEXT) as response:
            data = json.loads(response.read().decode("utf-8"))
            branch = str(data.get("default_branch") or "").strip()
            if branch:
                return branch
    except Exception:
        pass
    return "main"  # codeload 다운로드가 main 실패 시 master 재시도(아래)


class ExtensionInstallService:
    """GitHub zip 확장 설치 — 스레드 + 진행률 + 취소(설치 매니저 패턴)."""

    def __init__(self, extensions_root: Path | str):
        self.extensions_root = Path(extensions_root)
        self._lock = RLock()
        self._cancel = Event()
        self._thread: Thread | None = None
        self._state: dict[str, Any] = self._idle_state()

    @staticmethod
    def _idle_state() -> dict[str, Any]:
        return {
            "active": False, "phase": "idle", "percent": 0,
            "message": "", "error": "", "done": False,
            "installed_id": "", "installed_name": "", "url": "", "updated_at": "",
        }

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._state)

    def start(self, url: str) -> dict[str, Any]:
        with self._lock:
            if self._state.get("active"):
                return dict(self._state)
            self._cancel.clear()
            self._state = self._idle_state()
            self._state.update({
                "active": True, "phase": "resolve", "percent": 0,
                "message": "GitHub 주소 확인 중...", "url": str(url or "").strip(),
                "updated_at": datetime.now().isoformat(timespec="seconds"),
            })
            worker = Thread(target=self._run, args=(str(url or "").strip(),),
                            daemon=True, name="extension-github-install")
            self._thread = worker
            worker.start()
            return dict(self._state)

    def cancel(self) -> dict[str, Any]:
        with self._lock:
            if self._state.get("active"):
                self._cancel.set()
                self._state["message"] = "설치 취소 중..."
        return self.snapshot()

    def _run(self, url: str) -> None:
        staging = self.extensions_root / f".install-staging-{int(time.time() * 1000)}"
        try:
            owner, repo, ref = parse_github_url(url)
            refs = [ref] if ref else ["main", "master"]
            self._set(phase="download", percent=5, message=f"{owner}/{repo} 내려받는 중...")
            zip_bytes = self._download_first_available(owner, repo, refs)
            self._guard_cancel()
            self._set(phase="extract", percent=70, message="압축 해제 중...")
            ext_dir, ext_id, ext_name = self._extract_extension(zip_bytes, staging, repo)
            self._guard_cancel()
            self._set(phase="install", percent=90, message="설치 중...")
            self._place(ext_dir, ext_id)
            self._set(active=False, phase="complete", percent=100, done=True,
                      installed_id=ext_id, installed_name=ext_name,
                      message=f"'{ext_name}' 설치 완료 — Settings에서 승인하면 사용됩니다.",
                      error="")
        except InterruptedError as exc:
            self._set(active=False, phase="idle", message=str(exc), error="", done=False)
        except ExtensionInstallError as exc:
            self._set(active=False, phase="error", message=str(exc), error=str(exc), done=False)
        except Exception as exc:  # 예기치 못한 실패도 사용자 메시지로
            msg = f"설치 실패: {exc}"
            self._set(active=False, phase="error", message=msg, error=msg, done=False)
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    # ── 다운로드 ─────────────────────────────────────────────────
    def _download_first_available(self, owner: str, repo: str, refs: list[str]) -> bytes:
        last_error: Exception | None = None
        tried: list[str] = []
        # ref 미지정이면 default branch 조회를 우선 시도하도록 보강.
        if refs == ["main", "master"]:
            detected = _detect_default_branch(owner, repo)
            if detected not in refs:
                refs = [detected, *refs]
        for ref in refs:
            self._guard_cancel()
            try:
                return self._download(_codeload_url(owner, repo, ref))
            except urllib.error.HTTPError as exc:
                last_error = exc
                tried.append(ref)
                if exc.code in (404, 403):
                    continue  # 브랜치 없음 → 다음 후보
                raise ExtensionInstallError(f"다운로드 실패(HTTP {exc.code}): {exc.reason}")
            except urllib.error.URLError as exc:
                raise ExtensionInstallError(f"네트워크 오류: {exc.reason}")
        raise ExtensionInstallError(
            f"브랜치를 찾을 수 없습니다(시도: {', '.join(tried) or '?'}). "
            "주소에 /tree/<브랜치>를 포함해 보세요."
        )

    def _download(self, url: str) -> bytes:
        request = urllib.request.Request(url, headers={"User-Agent": "NAIA/2.0 Extension Installer"})
        with urllib.request.urlopen(request, timeout=30, context=SSL_CONTEXT) as response:
            total = int(response.headers.get("content-length", 0) or 0)
            if total and total > MAX_DOWNLOAD_BYTES:
                raise ExtensionInstallError(
                    f"확장 크기가 상한({MAX_DOWNLOAD_BYTES // (1024 * 1024)}MB)을 초과합니다."
                )
            chunks: list[bytes] = []
            downloaded = 0
            last = 0.0
            while True:
                self._guard_cancel()
                chunk = response.read(256 * 1024)
                if not chunk:
                    break
                downloaded += len(chunk)
                if downloaded > MAX_DOWNLOAD_BYTES:
                    raise ExtensionInstallError(
                        f"확장 크기가 상한({MAX_DOWNLOAD_BYTES // (1024 * 1024)}MB)을 초과합니다."
                    )
                chunks.append(chunk)
                now = time.time()
                if now - last >= 0.25:
                    pct = 5 + int((downloaded * 60) / total) if total else 30
                    self._set(percent=min(65, pct),
                              message=f"내려받는 중... {downloaded // 1024}KB")
                    last = now
            return b"".join(chunks)

    # ── 추출 + extension.json 위치 탐색 ──────────────────────────
    def _extract_extension(self, zip_bytes: bytes, staging: Path, repo: str) -> tuple[Path, str, str]:
        import io

        staging.mkdir(parents=True, exist_ok=True)
        staging_resolved = staging.resolve()
        total_uncompressed = 0
        with ZipFile(io.BytesIO(zip_bytes)) as archive:
            members = archive.infolist()
            if len(members) > MAX_MEMBERS:
                raise ExtensionInstallError("확장 아카이브 항목이 너무 많습니다.")
            for info in members:
                self._guard_cancel()
                name = info.filename
                if not name or name.endswith("/"):
                    continue
                # zip-slip 방어: 추출 경로가 staging 밖으로 못 나가게.
                target = (staging / name).resolve()
                if not target.is_relative_to(staging_resolved):
                    raise ExtensionInstallError(f"안전하지 않은 아카이브 경로: {name}")
                total_uncompressed += info.file_size
                if total_uncompressed > MAX_UNCOMPRESSED_BYTES:
                    raise ExtensionInstallError("압축 해제 크기가 상한을 초과합니다(zip 폭탄 의심).")
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as src, target.open("wb") as dst:
                    shutil.copyfileobj(src, dst, length=256 * 1024)
        # codeload zip은 {repo}-{ref}/ 단일 래퍼가 staging 아래 1단계를 차지한다.
        # 래퍼 루트(staging 기준 depth 2) 또는 래퍼 안 1단계 하위(depth 3)에서
        # extension.json을 찾는다(모노레포 1확장 지원). 더 깊은 건 무시.
        manifests = list(staging.rglob("extension.json"))
        manifests = [m for m in manifests if self._depth_under(m, staging) <= 3]
        if not manifests:
            raise ExtensionInstallError("이 레포에서 extension.json을 찾지 못했습니다.")
        if len(manifests) > 1:
            raise ExtensionInstallError(
                f"extension.json이 여러 개입니다({len(manifests)}) — 단일 확장 레포만 지원합니다."
            )
        manifest_path = manifests[0]
        ext_id, ext_name = self._validate_manifest(manifest_path)
        return manifest_path.parent, ext_id, ext_name

    @staticmethod
    def _depth_under(path: Path, root: Path) -> int:
        try:
            return len(path.relative_to(root).parts)
        except Exception:
            return 99

    @staticmethod
    def _validate_manifest(manifest_path: Path) -> tuple[str, str]:
        """설치 시점 최소 검증(파싱·id·api 버전·entry 존재). 풀 검증/등록은
        ExtensionManager.discover가 한다(중복·경로탈출 등)."""
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise ExtensionInstallError(f"extension.json을 읽을 수 없습니다: {exc}")
        if not isinstance(manifest, dict):
            raise ExtensionInstallError("extension.json 형식이 올바르지 않습니다.")
        ext_id = str(manifest.get("id") or manifest_path.parent.name).strip()
        if not ext_id:
            raise ExtensionInstallError("extension.json에 id가 없습니다.")
        try:
            api = int(manifest.get("naia_ext_api", 0) or 0)
        except (TypeError, ValueError):
            api = 0
        if api != NAIA_EXT_API_VERSION:
            raise ExtensionInstallError(
                f"지원하지 않는 naia_ext_api={api} (호스트={NAIA_EXT_API_VERSION})."
            )
        entry = str(manifest.get("entry") or "main.py")
        if not (manifest_path.parent / entry).is_file():
            raise ExtensionInstallError(f"진입 파일 '{entry}'이 레포에 없습니다.")
        return ext_id, str(manifest.get("name") or ext_id)

    # ── 배치(staging → extensions/<id>) ─────────────────────────
    def _place(self, source_dir: Path, ext_id: str) -> None:
        safe = _safe_dir_name(ext_id)
        target = (self.extensions_root / safe).resolve()
        if not target.is_relative_to(self.extensions_root.resolve()):
            raise ExtensionInstallError("설치 경로가 올바르지 않습니다.")
        self.extensions_root.mkdir(parents=True, exist_ok=True)
        backup: Path | None = None
        if target.exists():
            # 업데이트: 기존을 백업해 두고 실패 시 복원(원자적 교체에 근접).
            backup = target.with_name(f"{safe}.bak-{int(time.time() * 1000)}")
            target.replace(backup)
        try:
            shutil.copytree(source_dir, target)
        except Exception:
            if backup is not None and not target.exists():
                backup.replace(target)  # 복원
                backup = None
            raise
        finally:
            if backup is not None:
                shutil.rmtree(backup, ignore_errors=True)

    # ── 내부 ─────────────────────────────────────────────────────
    def _guard_cancel(self) -> None:
        if self._cancel.is_set():
            raise InterruptedError("설치가 취소되었습니다.")

    def _set(self, **updates: Any) -> dict[str, Any]:
        with self._lock:
            self._state.update(updates)
            self._state["updated_at"] = datetime.now().isoformat(timespec="seconds")
            return dict(self._state)


__all__ = [
    "ExtensionInstallService",
    "ExtensionInstallError",
    "parse_github_url",
]
