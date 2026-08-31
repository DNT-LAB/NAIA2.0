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
from typing import Any
from threading import Event, RLock, Thread
from typing import Any
from zipfile import ZipFile

NAIA_EXT_API_VERSION = 1
# 확장 zip 다운로드 상한(코드만 — 의존성은 ②단계 별도). 큰 레포 방어.
MAX_DOWNLOAD_BYTES = 60 * 1024 * 1024      # 60MB
MAX_UNCOMPRESSED_BYTES = 200 * 1024 * 1024  # 200MB(추출 총량)
MAX_MEMBERS = 5000
EXT_ID_RE = re.compile(r"[0-9A-Za-z][0-9A-Za-z_.-]{0,63}")

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


def _validate_ext_id(ext_id: str) -> str:
    """설치 id는 디렉터리명과 1:1이어야 한다.

    자동 정규화로 다른 manifest id가 같은 디렉터리에 충돌하면 승인/차단 상태가
    엉킬 수 있으므로, GitHub 설치 경로에서는 안전한 id만 받는다.
    """
    text = str(ext_id or "").strip()
    if not EXT_ID_RE.fullmatch(text) or _safe_dir_name(text) != text:
        raise ExtensionInstallError(
            "extension.json의 id는 영문/숫자로 시작하고 영문/숫자/._-만 사용할 수 있습니다."
        )
    return text


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
        if parsed.scheme != "https":
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


def _codeload_urls(owner: str, repo: str, ref: str, *, explicit: bool) -> list[tuple[str, str]]:
    if not explicit:
        return [(f"heads/{ref}", _codeload_url(owner, repo, ref))]
    return [
        (f"heads/{ref}", _codeload_url(owner, repo, ref)),
        (f"tags/{ref}", f"https://codeload.github.com/{owner}/{repo}/zip/refs/tags/{ref}"),
        (ref, f"https://codeload.github.com/{owner}/{repo}/zip/{ref}"),
    ]


# 매니페스트는 작다 - 이보다 크면 확장 매니페스트가 아니다.
MAX_MANIFEST_BYTES = 64 * 1024


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


def compare_versions(left: str, right: str) -> int:
    """`left` 가 크면 1, 작으면 -1, 같으면 0.

    ⚠️ 문자열 비교로는 안 된다 - `0.10.0` 이 `0.9.0` 보다 **작다**고 나온다.
       숫자 조각으로 끊어 수로 견준다. 숫자가 아닌 꼬리(`-beta`)는 무시한다 -
       그걸 순서로 세우려면 규약이 필요한데 확장마다 다르다.
    """
    def parts(value: str) -> list[int]:
        return [int(chunk) for chunk in re.findall(r"\d+", str(value or ""))] or [0]

    a, b = parts(left), parts(right)
    for i in range(max(len(a), len(b))):
        x = a[i] if i < len(a) else 0
        y = b[i] if i < len(b) else 0
        if x != y:
            return 1 if x > y else -1
    return 0


def fetch_remote_manifest(url: str, *, timeout: float = 15.0) -> dict[str, Any]:
    """레포 루트의 `extension.json` 만 읽어 온다 — **zip 을 받지 않는다**.

    업데이트가 있는지만 보는 데 수 MB 를 받을 이유가 없다(실측: 매니페스트만
    0.37초). 매니페스트가 하위 폴더에 있는 레포는 여기서 못 찾는다 - 그때는
    `found=False` 로 정직하게 답하고 화면이 "확인 불가" 라고 말한다. 추측으로
    폴더 이름을 넣어 보면 엉뚱한 확장의 버전을 읽을 수 있다.
    """
    owner, repo, ref = parse_github_url(url)
    branch = ref or _detect_default_branch(owner, repo)
    raw = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/extension.json"
    request = urllib.request.Request(raw, headers={"User-Agent": "NAIA/2.0 Extension Updater"})
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=SSL_CONTEXT) as response:
            data = json.loads(response.read(MAX_MANIFEST_BYTES).decode("utf-8"))
    except Exception as exc:
        return {"found": False, "branch": branch, "error": _safe_error(exc)}
    if not isinstance(data, dict):
        return {"found": False, "branch": branch, "error": "매니페스트 모양이 아닙니다."}
    return {
        "found": True,
        "branch": branch,
        "id": str(data.get("id") or ""),
        "name": str(data.get("name") or ""),
        "version": str(data.get("version") or ""),
    }


def _safe_error(exc: Exception) -> str:
    text = str(exc).strip() or exc.__class__.__name__
    return text[:160]


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

    def install_sample(self, sample_name: str, samples_root: Path | str) -> dict[str, Any]:
        """번들 샘플 확장(``release_assets/samples/extensions/<name>``)을
        ``user-data/extensions``로 복사한다. GitHub 설치와 달리 로컬 파일 복사라
        동기·즉시(스레드/진행률 불요) — 일반 사용자가 폴더를 손으로 옮기지 않아도
        '바로 사용하기'로 설치된다. **파일 배치까지만** 하며, 발견·승인은 기존 흐름이
        처리한다(동의 모델 유지: 복사 후에도 ``discovered``로 떠서 사용자가 명시 승인해야
        import 된다)."""
        with self._lock:
            if self._state.get("active"):
                return dict(self._state)  # GitHub 설치 진행 중이면 양보(상태 공유)
            # active를 *선점*한다(단순 확인이 아니라) — 확인~_place 사이에 GitHub start()가
            # active=false로 끼어들어 동시 _place/_state 접근하는 TOCTOU 방지(Codex).
            self._state = self._idle_state()
            self._state.update({
                "active": True, "phase": "sample", "percent": 0,
                "message": "샘플 설치 중...",
                "updated_at": datetime.now().isoformat(timespec="seconds"),
            })
        try:
            samples_resolved = Path(samples_root).resolve()
            source = (samples_resolved / _safe_dir_name(sample_name)).resolve()
            # path 탈출 방어: 정규화된 source가 samples 루트 안에 있어야 한다.
            if not source.is_relative_to(samples_resolved):
                raise ExtensionInstallError("샘플 경로가 올바르지 않습니다.")
            manifest = source / "extension.json"
            if not source.is_dir() or not manifest.is_file():
                raise ExtensionInstallError(f"샘플 확장을 찾을 수 없습니다: {sample_name}")
            try:
                meta = json.loads(manifest.read_text(encoding="utf-8"))
            except Exception:
                raise ExtensionInstallError("샘플 extension.json을 읽을 수 없습니다.")
            ext_id = str((meta or {}).get("id") or _safe_dir_name(sample_name)).strip()
            ext_name = str((meta or {}).get("name") or ext_id).strip()
            self._place(source, ext_id)  # 재사용: id 검증·중복 거부·copytree
            return self._set(
                active=False, phase="complete", percent=100, done=True,
                installed_id=ext_id, installed_name=ext_name, url="", error="",
                message=f"'{ext_name}' 설치됨 — Settings에서 승인하면 사용됩니다.",
            )
        except ExtensionInstallError as exc:
            return self._set(active=False, phase="error", percent=0, done=False,
                             message=str(exc), error=str(exc))
        except Exception as exc:  # 예기치 못한 실패도 사용자 메시지로
            msg = f"샘플 설치 실패: {exc}"
            return self._set(active=False, phase="error", percent=0, done=False,
                             message=msg, error=msg)

    def _run(self, url: str) -> None:
        staging = self.extensions_root / f".install-staging-{int(time.time() * 1000)}"
        try:
            owner, repo, ref = parse_github_url(url)
            refs = [ref] if ref else ["main", "master"]
            self._set(phase="download", percent=5, message=f"{owner}/{repo} 내려받는 중...")
            zip_bytes = self._download_first_available(owner, repo, refs, explicit_ref=bool(ref))
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
    def _download_first_available(
        self,
        owner: str,
        repo: str,
        refs: list[str],
        *,
        explicit_ref: bool = False,
    ) -> bytes:
        last_error: Exception | None = None
        tried: list[str] = []
        # ref 미지정이면 default branch 조회를 우선 시도하도록 보강.
        if refs == ["main", "master"]:
            detected = _detect_default_branch(owner, repo)
            if detected not in refs:
                refs = [detected, *refs]
        for ref in refs:
            self._guard_cancel()
            for label, url in _codeload_urls(owner, repo, ref, explicit=explicit_ref):
                try:
                    return self._download(url)
                except urllib.error.HTTPError as exc:
                    last_error = exc
                    tried.append(label)
                    if exc.code in (404, 403):
                        continue  # 브랜치/태그 없음 → 다음 후보
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
        ext_id = _validate_ext_id(str(manifest.get("id") or manifest_path.parent.name).strip())
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
        safe = _validate_ext_id(ext_id)
        target = (self.extensions_root / safe).resolve()
        if not target.is_relative_to(self.extensions_root.resolve()):
            raise ExtensionInstallError("설치 경로가 올바르지 않습니다.")
        self.extensions_root.mkdir(parents=True, exist_ok=True)
        if target.exists():
            raise ExtensionInstallError(
                f"확장 '{safe}'이 이미 설치되어 있습니다. 업데이트는 재승인 흐름이 추가된 뒤 지원됩니다."
            )
        try:
            # __pycache__/*.pyc는 빌드 산출물 — 배치 시 제외(스테일 바이트코드 복사 방지).
            shutil.copytree(source_dir, target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        except Exception:
            shutil.rmtree(target, ignore_errors=True)
            raise

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
