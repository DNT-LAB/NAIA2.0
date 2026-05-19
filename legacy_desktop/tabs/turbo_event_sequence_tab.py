"""
Turbo Event Sequence Tab - Root Level Entry Point

이 파일은 TabController가 탭을 발견할 수 있도록 루트 레벨에 위치합니다.
실제 구현은 turbo_event_sequence/ 서브디렉토리에 있습니다.
"""

import sys
import os

# 현재 파일의 디렉토리(tabs/)를 기준으로 프로젝트 루트 경로 추가
_current_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(_current_dir)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

# 이제 절대 임포트 사용 가능
from legacy_desktop.tabs.turbo_event_sequence import TurboEventSequenceTabModule

# TabController가 클래스를 발견할 수 있도록 노출
__all__ = ['TurboEventSequenceTabModule']
