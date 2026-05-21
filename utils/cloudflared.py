"""
Cloudflared 터널 관리 — pycloudflared 대체 경량 구현.
바이너리 다운로드 + Quick Tunnel 시작/종료.
"""
from __future__ import annotations

import atexit
import platform
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import NamedTuple
from urllib.request import urlopen

_DOWNLOAD_URLS = {
    # Windows
    ("windows", "amd64"): "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe",
    ("windows", "x86"): "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-386.exe",
    # Linux
    ("linux", "x86_64"): "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64",
    ("linux", "i386"): "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-386",
    ("linux", "arm"): "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm",
    ("linux", "arm64"): "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64",
    ("linux", "aarch64"): "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64",
    # macOS (tgz archive)
    ("darwin", "x86_64"): "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-darwin-amd64.tgz",
    ("darwin", "arm64"): "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-darwin-arm64.tgz",
}

_BIN_DIR = Path(__file__).parent / ".cloudflared_bin"
_URL_PAT = re.compile(r"(https?://\S+\.trycloudflare\.com)")
_METRICS_PAT = re.compile(r"(127\.0\.0\.1:\d+/metrics)")


class TunnelInfo(NamedTuple):
    tunnel_url: str
    metrics_url: str
    process: subprocess.Popen


_running: dict[int, TunnelInfo] = {}
_atexit_handlers: dict[int, object] = {}  # port → atexit에 등록된 함수 참조


def _get_platform_key() -> tuple[str, str]:
    system = platform.system().lower()
    machine = platform.machine().lower()
    key = (system, machine)
    if key not in _DOWNLOAD_URLS:
        raise RuntimeError(f"지원하지 않는 플랫폼: {system}/{machine}")
    return key


def _binary_dir(bin_dir: str | Path | None = None) -> Path:
    return Path(bin_dir) if bin_dir is not None else _BIN_DIR


def _get_executable_path(bin_dir: str | Path | None = None) -> Path:
    base_dir = _binary_dir(bin_dir)
    system, machine = _get_platform_key()
    if system == "darwin":
        return base_dir / "cloudflared"
    filename = _DOWNLOAD_URLS[(system, machine)].split("/")[-1]
    return base_dir / filename


def _download(on_progress=None, *, bin_dir: str | Path | None = None) -> Path:
    """cloudflared 바이너리 다운로드. on_progress(desc) 콜백으로 상태 전달."""
    base_dir = _binary_dir(bin_dir)
    exe = _get_executable_path(base_dir)
    if exe.exists():
        return exe

    base_dir.mkdir(parents=True, exist_ok=True)
    system, machine = _get_platform_key()
    url = _DOWNLOAD_URLS[(system, machine)]

    if on_progress:
        on_progress("Cloudflared 바이너리 다운로드 중...")

    dest = base_dir / url.split("/")[-1]
    with urlopen(url) as resp, dest.open("wb") as dst:
        shutil.copyfileobj(resp, dst)

    if system == "darwin":
        # macOS: tgz 아카이브 — 내부에 "cloudflared" 바이너리 직접 포함
        import tarfile
        with tarfile.open(dest, "r:gz") as tar:
            for member in tar.getmembers():
                if member.name.endswith("cloudflared") and member.isfile():
                    member.name = "cloudflared"
                    tar.extract(member, base_dir)
                    break
        dest.unlink()

    exe.chmod(0o755)
    return exe


def _readline_timeout(stream, timeout: float) -> str | None:
    """타임아웃 있는 readline. daemon 스레드 사용으로 leak 방지."""
    result = []
    done = threading.Event()

    def _read():
        try:
            line = stream.readline()
            result.append(line)
        except (OSError, ValueError):
            pass
        finally:
            done.set()

    t = threading.Thread(target=_read, daemon=True)
    t.start()
    if done.wait(timeout=timeout):
        return result[0] if result else None
    return None


def start_tunnel(
    port: int,
    on_progress=None,
    timeout: float = 30.0,
    *,
    bin_dir: str | Path | None = None,
) -> TunnelInfo:
    """
    Cloudflared Quick Tunnel 시작.

    Args:
        port: 로컬 서버 포트
        on_progress: 상태 메시지 콜백 (UI 업데이트용)
        timeout: 전체 타임아웃 (초)
    Returns:
        TunnelInfo
    """
    if port in _running:
        return _running[port]

    exe = _download(on_progress=on_progress, bin_dir=bin_dir)

    if on_progress:
        on_progress("Cloudflared 터널 연결 중...")

    proc = subprocess.Popen(
        [str(exe), "tunnel", "--url", f"http://127.0.0.1:{port}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        encoding="utf-8",
    )

    tunnel_url = metrics_url = ""
    deadline = time.monotonic() + timeout

    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            proc.terminate()
            raise RuntimeError("Cloudflared 연결 시간 초과")
        line = _readline_timeout(proc.stderr, timeout=min(5.0, remaining))
        if line is None:
            if proc.poll() is not None:
                raise RuntimeError("Cloudflared 프로세스가 예기치 않게 종료됨")
            continue
        m = _URL_PAT.search(line)
        if m:
            tunnel_url = m.group(1)
        m = _METRICS_PAT.search(line)
        if m:
            metrics_url = "http://" + m.group(1)
        if tunnel_url and metrics_url:
            break

    def _cleanup(p=proc):
        _terminate_process(p)

    atexit.register(_cleanup)
    _atexit_handlers[port] = _cleanup

    info = TunnelInfo(tunnel_url, metrics_url, proc)
    _running[port] = info
    return info


def _terminate_process(proc: subprocess.Popen) -> None:
    """프로세스 종료 헬퍼 — atexit 등록/해제에 동일 객체 사용."""
    try:
        proc.terminate()
    except OSError:
        pass


def stop_tunnel(port: int) -> None:
    """터널 종료."""
    if port in _running:
        info = _running.pop(port)
        _terminate_process(info.process)
        handler = _atexit_handlers.pop(port, None)
        if handler:
            atexit.unregister(handler)


def stop_all() -> None:
    """모든 터널 종료."""
    for port in list(_running):
        stop_tunnel(port)


def remove_binary(*, bin_dir: str | Path | None = None) -> None:
    """다운로드된 바이너리 삭제."""
    exe = _get_executable_path(bin_dir)
    if exe.exists():
        exe.unlink()
