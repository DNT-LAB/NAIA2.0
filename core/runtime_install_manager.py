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

# 태그 코퍼스 증분 (버킷 150~174, 2025/09~2026/06, 1,584,644행). 275MB.
#
# ⚠️ **`TAG_ARCHIVE_EXPECTED_COUNT` 를 175 로 올리면 안 된다.** 그 숫자는 베이스
# 아카이브의 "다 받았는가" 판정에 쓰인다. 올리는 순간 150개를 이미 가진 기존
# 사용자 전원이 베이스를 **미완성으로 판정받아 1.4GB 를 다시 받는다.**
# 증분은 별도 아카이브로 내보내고, 준비 판정은 개수가 아니라 **마지막 파일 이름**
# 으로 한다 - 두 아카이브가 같은 `tags/` 를 공유해서 개수로는 구분이 안 된다.
#
# ⚠️ zip 을 다시 만들 때는 **파일 이름을 바꿔야 한다.** 다운로더가 바이트 오프셋으로
# 이어받으므로(Range 요청), 같은 URL 에 다른 내용을 올리면 중간까지 받아 둔
# 사용자의 임시 파일이 조용히 깨진다.
TAG_INCREMENT_ARCHIVE_URL = (
    "https://huggingface.co/baqu2213/PoemForSmallFThings/resolve/main/naia_tags_inc_150_174.zip"
)
TAG_INCREMENT_MARKER = "tags_174.parquet"

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


# ⚠️ 이 목록과 taglist/*.json 은 **앱 소유 사전**이다. 앱 어디에서도 쓰지 않는
#    읽기 전용이고 편집 UI 도 없다(사용자 커스터마이즈는 PE 카테고리 오버라이드가
#    따로 저장한다). 그래서 배포본과 다르면 **덮어써서 갱신한다**.
#
#    예전엔 `target.exists()` 면 무조건 건너뛰었다. user-data 가 primary 이고
#    resource 는 fallback 이라(`headless_random_prompt_service._install_filter_manager`)
#    한 번 설치된 사전은 업데이트를 해도 **영영 옛것이 남았다** — 사전을 고쳐
#    배포해도 기존 사용자에게 닿지 않는다(2026-08-26 실측: 포터블 user-data 에
#    3,399개짜리 옛 characteristic_list.txt 가 그대로 있었다).
BOOTSTRAP_DATA_FILES = (
    "clothes_list.txt",
    "color.txt",
    "characteristic_list.txt",
)
BOOTSTRAP_TAGLIST_GLOB = "*.json"

# 크기가 같을 때 내용까지 비교할 상한. `taglist/style_thumbnails.json` 이 54MB 라
# 전량 비교는 매 기동 20ms(콜드 디스크에선 그 몇 배)를 먹는다 — 사전류는 전부
# 1MB 미만이라 이 문턱으로 실질 정확도를 잃지 않는다. 크기가 다르면 문턱과
# 무관하게 갱신하므로, 실제 개정은 크기 검사에서 걸린다.
BOOTSTRAP_CONTENT_COMPARE_MAX_BYTES = 4 * 1024 * 1024


def refresh_bootstrap_data_files(runtime_paths: Any) -> dict[str, Any]:
    """앱 소유 사전을 user-data 로 복사/갱신한다. 기동 경로와 설치 경로가 함께 쓴다.

    반환 `{copied, refreshed, present, missing}`. 어떤 실패도 기동을 막지 않는다.
    """
    source_data = runtime_paths.resource_path("data")
    target_data = runtime_paths.data_dir
    copied = 0
    refreshed = 0
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
        try:
            if target.exists():
                src_stat = source.stat()
                dst_stat = target.stat()
                same = src_stat.st_size == dst_stat.st_size
                # ⚠️ 크기가 같아도 **배포본이 더 새로우면** 갱신한다. 안 그랬면
                #    4MB 넘는 파일(taglist/style_thumbnails.json = 54MB)는 크기만 보므로
                #    크기가 같은 개정이 **영영 안 닿는다**(Codex #6). stat 두 번이라
                #    공짜나 다름없고, 갱신 뒤엔 target 이 더 새로워 재발동하지 않는다.
                if same and src_stat.st_mtime > dst_stat.st_mtime + 1:
                    same = False
                if same and src_stat.st_size <= BOOTSTRAP_CONTENT_COMPARE_MAX_BYTES:
                    same = source.read_bytes() == target.read_bytes()
                if same:
                    present += 1
                    continue
                target.write_bytes(source.read_bytes())
                refreshed += 1
                # cp949 콘솔이라 ASCII 만 쓴다.
                print(f"[data] refreshed dictionary: {relative}", flush=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read_bytes())
            copied += 1
        except OSError as exc:  # noqa: PERF203 - 파일 하나가 기동을 막으면 안 된다
            print(f"[data] bootstrap skip {relative}: {exc}", flush=True)
            missing.append(relative)

    return {"copied": copied, "refreshed": refreshed, "present": present, "missing": missing}

try:
    import certifi

    SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
except Exception:  # pragma: no cover - platform fallback
    SSL_CONTEXT = ssl.create_default_context()


# 태그 아카이브는 1.2GB 다. 느린 회선에서 한 번 멎으면 처음부터 다시 받아야 했고,
# 실제로 "태그 데이터 설치 실패: The read operation timed out" 으로 설치가 깨졌다
# (v2.0.34 빌드 중 실측). 소켓 타임아웃을 늘리고, 끊기면 **이어받는다**.
_DOWNLOAD_TIMEOUT_SECONDS = 60
_DOWNLOAD_ATTEMPTS = 5
_DOWNLOAD_BACKOFF_CAP = 8      # 재시도 대기 상한(초). 테스트는 0 으로 낮춘다.


def _content_range_starts_at(header: Any, expected_start: int) -> bool:
    """206 응답이 **우리가 기대한 지점부터** 보내 주는가.

    `Content-Range: bytes 1234-5678/9999` 의 첫 숫자가 지금 갖고 있는 바이트 수와
    같아야 이어붙일 수 있다. 다르면 구멍이나 중복이 생기고, 그 손상은 한참 뒤
    압축 해제에서 CRC 오류로 튀어나와 원인 모를 "설치 실패" 가 된다.

    헤더가 없거나 못 읽으면 **False**(= 처음부터 다시 받는다). 다시 받는 비용은
    시간뿐이지만, 잘못 이어붙이는 비용은 사용자가 원인을 못 찾는 실패다.
    """
    raw = str(header or "").strip()
    if not raw.lower().startswith("bytes"):
        return False
    try:
        span = raw.split(None, 1)[1].split("/", 1)[0]
        return int(span.split("-", 1)[0]) == int(expected_start)
    except (IndexError, ValueError):
        return False


class RuntimeInstallManager:
    """Initialize and install runtime-owned data for headless/Electron runs."""

    def __init__(
        self,
        runtime_paths: RuntimePaths,
        *,
        tag_archive_url: str = TAG_ARCHIVE_URL,
        expected_tag_files: int = TAG_ARCHIVE_EXPECTED_COUNT,
        on_tag_archive_complete: Callable[[], None] | None = None,
        tag_increment_archive_url: str = TAG_INCREMENT_ARCHIVE_URL,
        corpus_archive_url: str = CORPUS_ARCHIVE_URL,
        on_corpus_archive_complete: Callable[[], None] | None = None,
    ):
        self.runtime_paths = runtime_paths
        self.tag_archive_url = tag_archive_url
        self.expected_tag_files = int(expected_tag_files or 0)
        self._on_tag_archive_complete = on_tag_archive_complete
        self.tag_increment_archive_url = tag_increment_archive_url
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
            # 베이스와 **같은 디렉터리**에 풀린다. 그래서 준비 판정을 개수로 하면
            # 베이스와 구분이 안 된다 - 마지막 파일이 있는지로 본다.
            "tag_archive_increment": ArchiveSpec(
                key="tag_archive_increment",
                url=tag_increment_archive_url,
                subdir="tags",
                suffixes=(".parquet",),
                label="최신 태그 데이터",
                temp_name="naia_tags_increment.zip.download_tmp",
                count_glob="tags_*.parquet",
                required_names=(TAG_INCREMENT_MARKER,),
                min_count=1,
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
            # 증분도 베이스와 같은 후처리를 탄다 - 새 parquet 이 생겼다는 사실은
            # 같고, 검색·자동완성이 목록을 다시 잡아야 한다.
            "tag_archive_increment": on_tag_archive_complete,
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
            # 증분은 **베이스가 준비된 뒤에만** 의미가 있다. 베이스가 없는 사용자에게
            # 권하면 1.4GB 를 건너뛰고 275MB 를 받아 반쪽 코퍼스가 된다.
            "tag_archive_increment": {
                **self._archive_snapshot(self._spec("tag_archive_increment"), download),
                "base_ready": ready,
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

    def start_tag_increment_download(self, *, blocking: bool = False) -> dict[str, Any]:
        return self.start_archive_download("tag_archive_increment", blocking=blocking)

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
        """아카이브를 받는다. **끊기면 이어받는다.**

        ⚠️ 예전에는 시도 한 번에 이어받기가 없었다. 태그 아카이브는 1.2GB 라
        느린 회선에서는 중간에 한 번만 멎어도(소켓 read 타임아웃) **처음부터** 다시
        받아야 했고, 실제로 "태그 데이터 설치 실패: The read operation timed out"
        으로 설치가 깨졌다(v2.0.34 빌드 중 실측).

        받아 둔 바이트는 파일에 그대로 두고 `Range: bytes=N-` 로 이어 붙인다.
        Range 를 무시하고 200 을 주는 서버면 그때만 처음부터 다시 받는다.
        """
        temp_zip.parent.mkdir(parents=True, exist_ok=True)
        open_kwargs: dict[str, Any] = {"timeout": _DOWNLOAD_TIMEOUT_SECONDS}
        if spec.url.startswith("https://"):
            open_kwargs["context"] = SSL_CONTEXT

        downloaded = temp_zip.stat().st_size if temp_zip.exists() else 0
        total_size = 0
        last_error: Exception | None = None

        for attempt in range(1, _DOWNLOAD_ATTEMPTS + 1):
            if self._cancel.is_set():
                raise InterruptedError("태그 데이터 다운로드가 취소되었습니다.")
            headers = {"User-Agent": "NAIA/2.0.41 RuntimeInstallManager"}
            if downloaded > 0:
                headers["Range"] = f"bytes={downloaded}-"
            # ⚠️ `_set_state` 는 dict.update 라 None 을 넣으면 그 값이 None 이 된다.
            # 진행률은 첫 연결일 때만 건드린다(이어받는 중에 5% 로 되돌리면 안 된다).
            progress: dict[str, Any] = {"percent": 5} if downloaded == 0 else {}
            self._set_state(
                message=(
                    f"{spec.label} 다운로드 연결 중..." if attempt == 1 and downloaded == 0
                    else f"{spec.label} 이어받는 중... (시도 {attempt}/{_DOWNLOAD_ATTEMPTS})"
                ),
                **progress,
            )
            try:
                request = urllib.request.Request(spec.url, headers=headers)
                with urllib.request.urlopen(request, **open_kwargs) as response:
                    # Range 를 보냈는데 200 이 오면 서버가 무시한 것 - 이어붙이면
                    # 파일이 깨지므로 그때만 처음부터 다시 받는다.
                    #
                    # ⚠️ 206 만 보고 이어붙이면 안 된다. **어디서부터** 보냈는지는
                    # `Content-Range` 에만 있고, 그게 우리가 가진 바이트 수와 다르면
                    # 이어붙인 파일에 구멍이나 중복이 생긴다(Codex 리뷰 2026-08-21).
                    # 그 손상은 여기서 안 잡히고 한참 뒤 압축 해제에서 CRC 오류로
                    # 튀어나와, 사용자에겐 원인 모를 "설치 실패" 로 보인다.
                    resuming = (
                        downloaded > 0
                        and response.status == 206
                        and _content_range_starts_at(response.headers.get("content-range"),
                                                     downloaded)
                    )
                    if downloaded > 0 and not resuming:
                        downloaded = 0
                    body_size = int(response.headers.get("content-length", 0) or 0)
                    total_size = (downloaded + body_size) if body_size else total_size
                    mode = "ab" if resuming else "wb"
                    downloaded = self._stream_to_file(
                        spec, response, temp_zip, mode, downloaded, total_size)
                last_error = None
                break
            except InterruptedError:
                raise
            except urllib.error.HTTPError as exc:
                # 416 = 이미 다 받아 둔 상태에서 그 뒤를 또 달라고 한 것.
                if exc.code == 416 and downloaded > 0:
                    last_error = None
                    break
                raise
            except Exception as exc:  # noqa: BLE001 - 끊김/타임아웃은 재시도 대상이다
                last_error = exc
                # ⚠️ **디스크에서 다시 잰다.** `_stream_to_file` 이 도중에 예외를
                # 던지면 반환값을 못 받아 `downloaded` 가 0 인 채로 남는다 - 그러면
                # Range 를 안 보내 이어받기가 통째로 무력화된다(테스트가 잡았다).
                # 실제로 몇 바이트가 들어갔는지는 파일만이 안다.
                downloaded = temp_zip.stat().st_size if temp_zip.exists() else 0
                if attempt >= _DOWNLOAD_ATTEMPTS:
                    break
                # 취소에 즉시 반응해야 하므로 sleep 대신 이벤트 대기를 쓴다.
                if self._cancel.wait(min(_DOWNLOAD_BACKOFF_CAP, 2 ** (attempt - 1))):
                    raise InterruptedError("태그 데이터 다운로드가 취소되었습니다.")

        if last_error is not None:
            raise last_error
        if not temp_zip.exists() or temp_zip.stat().st_size < 1024:
            raise ValueError(f"다운로드된 {spec.label} ZIP 파일이 너무 작습니다.")

    def _stream_to_file(self, spec: ArchiveSpec, response: Any, temp_zip: Path,
                        mode: str, downloaded: int, total_size: int) -> int:
        """응답 본문을 파일에 흘려 넣고 지금까지 받은 총 바이트를 돌려준다."""
        total_mb = round(total_size / (1024 * 1024), 1) if total_size else 0.0
        last_update = 0.0
        with temp_zip.open(mode) as output:
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
        return downloaded

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
        self._bootstrap_state = refresh_bootstrap_data_files(self.runtime_paths)

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
