from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from threading import Event, RLock, Thread
from typing import Any, Callable
import ssl
import time
import urllib.error
import urllib.request
import zipfile

from app.backend.runtime import RuntimePaths


TAG_ARCHIVE_URL = "https://huggingface.co/baqu2213/PoemForSmallFThings/resolve/main/naia_tags.zip"
TAG_ARCHIVE_EXPECTED_COUNT = 150

# Event Corpus (Interactive 모드의 태그 공기 추천). Dev0714 QuickSearchBlock 이 쓰던 것과
# 동일한 아카이브다. Dev0714 는 zip_ref.extractall() 을 그대로 써서 traversal 에 무방비였는데,
# 여기서는 아래 _extract_archive 의 basename 평탄화 + 확장자 화이트리스트를 그대로 태운다.
CORPUS_ARCHIVE_URL = (
    "https://huggingface.co/baqu2213/PoemForSmallFThings/resolve/main/NAIA/naia-tag-events.zip"
)


@dataclass(frozen=True)
class ArchiveSpec:
    """다운로드+압축해제 대상 아카이브 1종.

    태그 아카이브(2GB)와 이벤트 코퍼스가 같은 코드를 공유한다. 아카이브별로 다른 것은
    URL / 대상 디렉터리 / 허용 확장자 / 준비 완료 판정뿐이다.
    """

    key: str                                   # snapshot 키
    url: str
    subdir: str                                # runtime data_dir 하위
    suffixes: tuple[str, ...]                  # 허용 멤버 확장자 (화이트리스트)
    label: str                                 # 사용자 노출 한글 명칭
    temp_name: str
    count_glob: str = "*"
    expected_count: int = 0
    required_names: tuple[str, ...] = ()       # 반드시 존재해야 하는 파일명
    min_count: int = 1


BOOTSTRAP_DATA_FILES = (
    "clothes_list.txt",
    "color.txt",
    "characteristic_list.txt",
)
BOOTSTRAP_TAGLIST_GLOB = "*.json"

try:
    import certifi

    SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
except Exception:  # pragma: no cover - platform fallback
    SSL_CONTEXT = ssl.create_default_context()


class RuntimeInstallManager:
    """Initialize and install runtime-owned data for headless/Electron runs."""

    def __init__(
        self,
        runtime_paths: RuntimePaths,
        *,
        tag_archive_url: str = TAG_ARCHIVE_URL,
        expected_tag_files: int = TAG_ARCHIVE_EXPECTED_COUNT,
        on_tag_archive_complete: Callable[[], None] | None = None,
        corpus_archive_url: str = CORPUS_ARCHIVE_URL,
        on_corpus_archive_complete: Callable[[], None] | None = None,
    ):
        self.runtime_paths = runtime_paths
        self.tag_archive_url = tag_archive_url
        self.expected_tag_files = int(expected_tag_files or 0)
        self._on_tag_archive_complete = on_tag_archive_complete
        self.corpus_archive_url = corpus_archive_url
        self._on_corpus_archive_complete = on_corpus_archive_complete
        self._specs: dict[str, ArchiveSpec] = {
            "tag_archive": ArchiveSpec(
                key="tag_archive",
                url=tag_archive_url,
                subdir="tags",
                suffixes=(".parquet",),
                label="태그 데이터",
                temp_name="naia_tags.zip.download_tmp",
                count_glob="tags_*.parquet",
                expected_count=self.expected_tag_files,
            ),
            "corpus_archive": ArchiveSpec(
                key="corpus_archive",
                url=corpus_archive_url,
                subdir="quick_search",
                suffixes=(".tgp", ".tgpm"),
                label="이벤트 코퍼스",
                temp_name="naia_tag_events.zip.download_tmp",
                count_glob="*.tgp",
                required_names=("metadata.tgpm",),
                min_count=1,
            ),
        }
        self._completion_hooks: dict[str, Callable[[], None] | None] = {
            "tag_archive": on_tag_archive_complete,
            "corpus_archive": on_corpus_archive_complete,
        }
        self._lock = RLock()
        self._cancel = Event()
        self._thread: Thread | None = None
        self._download_state: dict[str, Any] = {
            "active": False,
            "phase": "idle",
            "percent": 0,
            "downloaded_mb": 0.0,
            "total_mb": 0.0,
            "message": "",
            "error": "",
            "done": False,
            "updated_at": "",
        }
        self._bootstrap_state: dict[str, Any] = {
            "copied": 0,
            "present": 0,
            "missing": [],
        }

    @property
    def tag_dir(self) -> Path:
        return self.runtime_paths.data_dir / "tags"

    # ------------------------------------------------------------------
    # 아카이브 공통
    # ------------------------------------------------------------------

    def _spec(self, key: str) -> ArchiveSpec:
        spec = self._specs.get(key)
        if spec is None:
            raise ValueError(f"unknown archive: {key!r}")
        return spec

    def _archive_dir(self, spec: ArchiveSpec) -> Path:
        return self.runtime_paths.data_dir / spec.subdir

    def _archive_file_count(self, spec: ArchiveSpec) -> int:
        target = self._archive_dir(spec)
        if not target.exists():
            return 0
        return len([path for path in target.glob(spec.count_glob) if path.is_file()])

    def _archive_ready(self, spec: ArchiveSpec, count: int | None = None) -> bool:
        found = self._archive_file_count(spec) if count is None else count
        target = self._archive_dir(spec)
        for name in spec.required_names:
            if not (target / name).is_file():
                return False
        if spec.expected_count:
            return found >= spec.expected_count
        return found >= spec.min_count

    def _archive_snapshot(self, spec: ArchiveSpec, download: dict[str, Any]) -> dict[str, Any]:
        count = self._archive_file_count(spec)
        return {
            "ready": self._archive_ready(spec, count),
            "file_count": count,
            "expected_count": spec.expected_count,
            "missing_count": max(0, spec.expected_count - count) if spec.expected_count else 0,
            "target": str(self._archive_dir(spec)),
            "downloadable": bool(spec.url),
            "url": spec.url,
            "label": spec.label,
            "download": download,
        }

    def initialize(self) -> dict[str, Any]:
        self.runtime_paths.ensure_writable_dirs()
        self._copy_bootstrap_data_files()
        self.tag_dir.mkdir(parents=True, exist_ok=True)
        return self.snapshot()

    def snapshot(self) -> dict[str, Any]:
        self.runtime_paths.ensure_writable_dirs()
        count = self._tag_file_count()
        ready = self._tag_archive_ready(count)
        with self._lock:
            download = dict(self._download_state)
        return {
            "ok": True,
            "runtime": {
                "user_root": str(self.runtime_paths.user_root),
                "data_dir": str(self.runtime_paths.data_dir),
                "downloads_dir": str(self.runtime_paths.downloads_dir),
                "resource_root": str(self.runtime_paths.resource_root),
                "portable": bool(self.runtime_paths.portable),
                "data_initialized": self.runtime_paths.data_dir.exists(),
            },
            # 기존 키/필드는 그대로 유지한다 — 프론트 설치 패널이 읽고 있다.
            "tag_archive": {
                "ready": ready,
                "file_count": count,
                "expected_count": self.expected_tag_files,
                "missing_count": max(0, self.expected_tag_files - count) if self.expected_tag_files else 0,
                "target": str(self.tag_dir),
                "downloadable": bool(self.tag_archive_url),
                "url": self.tag_archive_url,
                "download": download,
            },
            "corpus_archive": self._archive_snapshot(self._spec("corpus_archive"), download),
            "samples": {
                "app_data_template": str(self.runtime_paths.resource_path("app_data_template")),
                "release_samples": str(self.runtime_paths.resource_path("release_assets/samples")),
            },
            "bootstrap_data": dict(self._bootstrap_state),
        }

    def start_tag_archive_download(self, *, blocking: bool = False) -> dict[str, Any]:
        return self.start_archive_download("tag_archive", blocking=blocking)

    def cancel_tag_archive_download(self) -> dict[str, Any]:
        return self.cancel_archive_download()

    def start_corpus_archive_download(self, *, blocking: bool = False) -> dict[str, Any]:
        return self.start_archive_download("corpus_archive", blocking=blocking)

    def start_archive_download(self, key: str, *, blocking: bool = False) -> dict[str, Any]:
        spec = self._spec(key)
        self.initialize()
        if self._archive_ready(spec):
            return self._set_state(
                active=False,
                phase="complete",
                percent=100,
                downloaded_mb=0.0,
                total_mb=0.0,
                message=f"{spec.label}가 이미 설치되어 있습니다.",
                error="",
                done=True,
            )

        with self._lock:
            # 다운로더는 단일 비행이다. 2GB 태그 아카이브와 코퍼스를 동시에 받으면
            # 진행률 상태(_download_state)가 하나뿐이라 서로 덮어쓴다.
            if self._download_state.get("active"):
                return dict(self._download_state)
            self._cancel.clear()
            self._download_state.update({
                "active": True,
                "phase": spec.key,
                "percent": 0,
                "downloaded_mb": 0.0,
                "total_mb": 0.0,
                "message": f"{spec.label} 다운로드 준비 중...",
                "error": "",
                "done": False,
                "updated_at": datetime.now().isoformat(timespec="seconds"),
            })
            if not blocking:
                worker = Thread(
                    target=self._run_archive_download,
                    args=(spec,),
                    daemon=True,
                    name=f"runtime-{spec.key}-download",
                )
                self._thread = worker
                worker.start()
                return dict(self._download_state)

        self._run_archive_download(spec)
        with self._lock:
            return dict(self._download_state)

    def cancel_archive_download(self) -> dict[str, Any]:
        with self._lock:
            state = dict(self._download_state)
        if state.get("active"):
            self._cancel.set()
            phase = str(state.get("phase") or "")
            label = self._specs[phase].label if phase in self._specs else "데이터"
            return self._set_state(message=f"{label} 다운로드 취소 중...")
        return state

    def _run_archive_download(self, spec: ArchiveSpec) -> None:
        temp_zip = self.runtime_paths.downloads_dir / spec.temp_name
        target = self._archive_dir(spec)
        try:
            self.runtime_paths.ensure_writable_dirs()
            target.mkdir(parents=True, exist_ok=True)
            self._download_archive(spec, temp_zip)
            extracted = self._extract_archive(spec, temp_zip)
            if spec.expected_count and extracted < spec.expected_count:
                raise ValueError(
                    f"{spec.label} 파일이 부족합니다 ({extracted}/{spec.expected_count})"
                )
            # 압축 해제 직후 실제 준비 상태를 다시 검증한다. 멤버 수만 세면 필수 파일
            # (코퍼스의 metadata.tgpm)이 빠진 아카이브도 성공으로 보고된다.
            if not self._archive_ready(spec):
                missing = [
                    name for name in spec.required_names
                    if not (target / name).is_file()
                ]
                detail = f" (누락: {', '.join(missing)})" if missing else ""
                raise ValueError(f"{spec.label} 설치 후 검증 실패{detail}")
            hook = self._completion_hooks.get(spec.key)
            if hook is not None:
                hook()
            self._set_state(
                active=False,
                phase="complete",
                percent=100,
                message=f"{spec.label} 설치 완료 ({extracted}개 파일)",
                error="",
                done=True,
            )
        except InterruptedError as exc:
            self._set_state(active=False, message=str(exc), error=str(exc), done=False)
        except urllib.error.HTTPError as exc:
            message = f"HTTP 오류 {exc.code}: {exc.reason}"
            self._set_state(active=False, message=message, error=message, done=False)
        except urllib.error.URLError as exc:
            message = f"네트워크 오류: {exc.reason}"
            self._set_state(active=False, message=message, error=message, done=False)
        except Exception as exc:
            message = f"{spec.label} 설치 실패: {exc}"
            self._set_state(active=False, message=message, error=message, done=False)
        finally:
            try:
                temp_zip.unlink(missing_ok=True)
            except Exception:
                pass

    def _download_archive(self, spec: ArchiveSpec, temp_zip: Path) -> None:
        temp_zip.parent.mkdir(parents=True, exist_ok=True)
        request = urllib.request.Request(
            spec.url,
            headers={"User-Agent": "NAIA/2.0.33 RuntimeInstallManager"},
        )
        self._set_state(percent=5, message=f"{spec.label} 다운로드 연결 중...")
        open_kwargs = {"timeout": 30}
        if spec.url.startswith("https://"):
            open_kwargs["context"] = SSL_CONTEXT
        with urllib.request.urlopen(request, **open_kwargs) as response:
            total_size = int(response.headers.get("content-length", 0) or 0)
            total_mb = round(total_size / (1024 * 1024), 1) if total_size else 0.0
            downloaded = 0
            last_update = 0.0
            with temp_zip.open("wb") as output:
                while True:
                    if self._cancel.is_set():
                        raise InterruptedError("태그 데이터 다운로드가 취소되었습니다.")
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    output.write(chunk)
                    downloaded += len(chunk)
                    now = time.time()
                    if now - last_update >= 0.25:
                        percent = min(85, 10 + int((downloaded * 75) / total_size)) if total_size else 10
                        downloaded_mb = round(downloaded / (1024 * 1024), 1)
                        self._set_state(
                            percent=percent,
                            downloaded_mb=downloaded_mb,
                            total_mb=total_mb,
                            message=(
                                f"{spec.label} 다운로드 중... {percent}% ({downloaded_mb}/{total_mb} MB)"
                                if total_size else f"{spec.label} 다운로드 중... {downloaded_mb} MB"
                            ),
                        )
                        last_update = now
        if temp_zip.stat().st_size < 1024:
            raise ValueError(f"다운로드된 {spec.label} ZIP 파일이 너무 작습니다.")

    def _extract_archive(self, spec: ArchiveSpec, temp_zip: Path) -> int:
        self._set_state(percent=90, message=f"{spec.label} 압축 해제 중...")
        extracted = 0
        seen_names: set[str] = set()
        with zipfile.ZipFile(temp_zip, "r") as archive:
            members = [
                info for info in archive.infolist()
                if info.filename.endswith(spec.suffixes)
            ]
            if not members:
                raise ValueError(
                    f"ZIP 파일에 {'/'.join(spec.suffixes)} 파일이 없습니다."
                )
            for index, info in enumerate(members, 1):
                if self._cancel.is_set():
                    raise InterruptedError("태그 데이터 설치가 취소되었습니다.")
                filename = Path(info.filename).name
                # basename 평탄화 + 확장자 화이트리스트 = path traversal 차단.
                if not filename or filename in seen_names or not filename.endswith(spec.suffixes):
                    raise ValueError(f"안전하지 않은 {spec.label} ZIP 항목입니다: {info.filename}")
                seen_names.add(filename)
                target = self._archive_dir(spec) / filename
                temp_target = target.with_name(target.name + ".install_tmp")
                with archive.open(info) as source, temp_target.open("wb") as output:
                    while True:
                        chunk = source.read(1024 * 1024)
                        if not chunk:
                            break
                        output.write(chunk)
                temp_target.replace(target)
                extracted += 1
                percent = min(99, 90 + int((index * 9) / len(members)))
                self._set_state(percent=percent, message=f"{spec.label} 설치 중... {index}/{len(members)}")
        return extracted

    def _tag_file_count(self) -> int:
        if not self.tag_dir.exists():
            return 0
        return len([path for path in self.tag_dir.glob("tags_*.parquet") if path.is_file()])

    def _copy_bootstrap_data_files(self) -> None:
        source_data = self.runtime_paths.resource_path("data")
        target_data = self.runtime_paths.data_dir
        copied = 0
        present = 0
        missing: list[str] = []

        candidates: list[Path] = [source_data / relative for relative in BOOTSTRAP_DATA_FILES]
        taglist_dir = source_data / "taglist"
        if taglist_dir.is_dir():
            candidates.extend(sorted(taglist_dir.glob(BOOTSTRAP_TAGLIST_GLOB)))
        else:
            missing.append("taglist/*.json")

        seen: set[str] = set()
        for source in candidates:
            relative = source.relative_to(source_data).as_posix()
            if relative in seen:
                continue
            seen.add(relative)
            target = target_data / relative
            if not source.is_file():
                missing.append(relative)
                continue
            if target.exists():
                present += 1
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read_bytes())
            copied += 1

        self._bootstrap_state = {
            "copied": copied,
            "present": present,
            "missing": missing,
        }

    def _tag_archive_ready(self, count: int | None = None) -> bool:
        current = self._tag_file_count() if count is None else int(count)
        return current >= self.expected_tag_files if self.expected_tag_files else current > 0

    def _set_state(self, **updates: Any) -> dict[str, Any]:
        with self._lock:
            self._download_state.update(updates)
            self._download_state["updated_at"] = datetime.now().isoformat(timespec="seconds")
            return dict(self._download_state)


__all__ = [
    "BOOTSTRAP_DATA_FILES",
    "BOOTSTRAP_TAGLIST_GLOB",
    "RuntimeInstallManager",
    "TAG_ARCHIVE_EXPECTED_COUNT",
    "TAG_ARCHIVE_URL",
]
