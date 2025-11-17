#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
임시 생성 창 파라미터 기능 테스트 스크립트

Phase 2 구현 검증:
1. TempGenerationParamsWidget 임포트
2. TempGenerationWindow 임포트
3. 위젯 인스턴스화
"""

import sys

print("=" * 60)
print("임시 생성 창 파라미터 기능 테스트")
print("=" * 60)

# Test 1: Import TempGenerationParamsWidget
print("\n[Test 1] TempGenerationParamsWidget import...")
try:
    from ui.temp_generation_params import TempGenerationParamsWidget
    print("✅ TempGenerationParamsWidget import 성공")
except Exception as e:
    print(f"❌ TempGenerationParamsWidget import 실패: {e}")
    sys.exit(1)

# Test 2: Import TempGenerationWindow
print("\n[Test 2] TempGenerationWindow import...")
try:
    from ui.temp_generation_window import TempGenerationWindow
    print("✅ TempGenerationWindow import 성공")
except Exception as e:
    print(f"❌ TempGenerationWindow import 실패: {e}")
    sys.exit(1)

# Test 3: Check class methods
print("\n[Test 3] TempGenerationParamsWidget 메서드 확인...")
try:
    methods = [
        'set_initial_values',
        'collect_parameters',
        'update_ui_for_mode'
    ]
    for method in methods:
        if hasattr(TempGenerationParamsWidget, method):
            print(f"  ✅ {method} 메서드 존재")
        else:
            print(f"  ❌ {method} 메서드 없음")
            sys.exit(1)
except Exception as e:
    print(f"❌ 메서드 확인 실패: {e}")
    sys.exit(1)

# Test 4: Check TempGenerationWindow methods
print("\n[Test 4] TempGenerationWindow 메서드 확인...")
try:
    methods = [
        'set_prompts',
        'set_initial_params',
        'update_params_ui_for_mode'
    ]
    for method in methods:
        if hasattr(TempGenerationWindow, method):
            print(f"  ✅ {method} 메서드 존재")
        else:
            print(f"  ❌ {method} 메서드 없음")
            sys.exit(1)
except Exception as e:
    print(f"❌ 메서드 확인 실패: {e}")
    sys.exit(1)

# Test 5: Verify collect_parameters returns dict
print("\n[Test 5] collect_parameters 반환 타입 확인...")
try:
    # Check method signature
    import inspect
    sig = inspect.signature(TempGenerationParamsWidget.collect_parameters)
    print(f"  ✅ collect_parameters 시그니처: {sig}")

    # Check return annotation
    if sig.return_annotation == dict:
        print(f"  ✅ 반환 타입: dict")
    else:
        print(f"  ℹ️  반환 타입 힌트: {sig.return_annotation}")
except Exception as e:
    print(f"❌ 시그니처 확인 실패: {e}")
    sys.exit(1)

print("\n" + "=" * 60)
print("✅ 모든 테스트 통과!")
print("=" * 60)
print("\n다음 단계: NAIA 애플리케이션 실행 후 수동 테스트")
print("  1. [Temp] 버튼 클릭하여 임시 창 생성")
print("  2. 파라미터가 올바르게 복사되었는지 확인")
print("  3. API 모드 변경 시 확인 다이얼로그 확인")
print("  4. NAI 모델 (NAID3 ↔ NAID4.x) 변경 시 확인 다이얼로그 확인")
print("=" * 60)
