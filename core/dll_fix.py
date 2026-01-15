import os
import sys
import ctypes

def load_torch_dlls():
    """
    Windows에서 torch 관련 DLL 로드 문제를 해결하기 위한 함수.
    [WinError 1114] DLL 초기화 루틴을 실행할 수 없습니다 오류 대응.
    """
    if sys.platform != "win32":
        return

    try:
        # venv 내부의 torch/lib 경로 찾기
        import site
        
        # site-packages 경로들 확인
        site_packages = site.getsitepackages()
        torch_lib_path = None
        
        for sp in site_packages:
            possible_path = os.path.join(sp, 'torch', 'lib')
            if os.path.exists(possible_path):
                torch_lib_path = possible_path
                break
        
        if not torch_lib_path:
            # 현재 실행 파일 기준 상대 경로로 시도
            current_dir = os.path.dirname(os.path.abspath(__file__))
            # core/../venv/Lib/site-packages/torch/lib
            possible_path = os.path.abspath(os.path.join(current_dir, '..', 'venv', 'Lib', 'site-packages', 'torch', 'lib'))
            if os.path.exists(possible_path):
                torch_lib_path = possible_path

        if torch_lib_path:
            # DLL 검색 경로에 추가 (Python 3.8+)
            os.add_dll_directory(torch_lib_path)
            
            # 주요 DLL 수동 로드 시도
            dlls_to_load = ['c10.dll', 'torch_cpu.dll']
            for dll in dlls_to_load:
                dll_path = os.path.join(torch_lib_path, dll)
                if os.path.exists(dll_path):
                    try:
                        ctypes.CDLL(dll_path)
                        print(f"✅ Loaded DLL: {dll}")
                    except Exception as e:
                        print(f"⚠️ Failed to load DLL {dll}: {e}")
        else:
            print("⚠️ Torch lib directory not found.")
            
    except Exception as e:
        print(f"⚠️ DLL fix failed: {e}")

# 모듈 로드 시 자동 실행
load_torch_dlls()
