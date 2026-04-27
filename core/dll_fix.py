"""Windows torch DLL 로드 보조.

부팅 시에는 `os.add_dll_directory(torch/lib)` 만 즉시 실행하여 DLL 검색 path를
세팅한다 (수 ms, 안전망 유지). 실제 `c10.dll`/`torch_cpu.dll` 의 ctypes 선로딩은
`load_torch_dlls()` 명시 호출 시에만 수행한다.

코드베이스에 직접 `import torch` 가 없으므로 보통은 명시 호출이 불필요하다.
WD14 tagger 등 transitive 경로에서 `[WinError 1114]` 가 발생하면 그 워커
시작 직전에 `load_torch_dlls()` 를 호출하면 된다.
"""

import os
import sys
import ctypes


_TORCH_LIB_PATH = None


def _resolve_torch_lib_path() -> str | None:
    if sys.platform != "win32":
        return None
    try:
        import site
        for sp in site.getsitepackages():
            p = os.path.join(sp, 'torch', 'lib')
            if os.path.exists(p):
                return p
        # venv 폴백
        current_dir = os.path.dirname(os.path.abspath(__file__))
        p = os.path.abspath(
            os.path.join(current_dir, '..', 'venv', 'Lib', 'site-packages', 'torch', 'lib')
        )
        if os.path.exists(p):
            return p
    except Exception as e:
        print(f"⚠️ torch lib path 탐색 실패: {e}")
    return None


def _register_dll_directory():
    """torch/lib 을 Windows DLL 검색 path에 등록만 한다 (가벼움)."""
    global _TORCH_LIB_PATH
    if sys.platform != "win32":
        return
    _TORCH_LIB_PATH = _resolve_torch_lib_path()
    if _TORCH_LIB_PATH:
        try:
            os.add_dll_directory(_TORCH_LIB_PATH)
        except Exception as e:
            print(f"⚠️ add_dll_directory 실패: {e}")
    else:
        # torch 미설치 환경 — 정상 (image tagging 안 쓰면 무관)
        pass


def load_torch_dlls():
    """c10.dll / torch_cpu.dll 명시적 선로딩. WD14 tagger 등 transitive
    torch import 경로에서 [WinError 1114] 가 나면 워커 시작 전 호출."""
    if sys.platform != "win32":
        return
    if _TORCH_LIB_PATH is None:
        return
    for dll in ('c10.dll', 'torch_cpu.dll'):
        dll_path = os.path.join(_TORCH_LIB_PATH, dll)
        if os.path.exists(dll_path):
            try:
                ctypes.CDLL(dll_path)
                print(f"✅ Loaded DLL: {dll}")
            except Exception as e:
                print(f"⚠️ Failed to load DLL {dll}: {e}")


# 모듈 로드 시 가벼운 path 등록만 자동 실행
_register_dll_directory()
