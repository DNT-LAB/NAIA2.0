#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Simple test script for temp generation params (no emojis)
"""

import sys

print("=" * 60)
print("Temporary Generation Window Parameter Test")
print("=" * 60)

# Test 1: Import TempGenerationParamsWidget
print("\n[Test 1] Import TempGenerationParamsWidget...")
try:
    from ui.temp_generation_params import TempGenerationParamsWidget
    print("SUCCESS: TempGenerationParamsWidget imported")
except Exception as e:
    print(f"FAIL: TempGenerationParamsWidget import failed: {e}")
    sys.exit(1)

# Test 2: Import TempGenerationWindow
print("\n[Test 2] Import TempGenerationWindow...")
try:
    from ui.temp_generation_window import TempGenerationWindow
    print("SUCCESS: TempGenerationWindow imported")
except Exception as e:
    print(f"FAIL: TempGenerationWindow import failed: {e}")
    sys.exit(1)

# Test 3: Check TempGenerationParamsWidget methods
print("\n[Test 3] Check TempGenerationParamsWidget methods...")
try:
    methods = [
        'set_initial_values',
        'collect_parameters',
        'update_ui_for_mode'
    ]
    for method in methods:
        if hasattr(TempGenerationParamsWidget, method):
            print(f"  OK: {method} exists")
        else:
            print(f"  FAIL: {method} missing")
            sys.exit(1)
except Exception as e:
    print(f"FAIL: Method check failed: {e}")
    sys.exit(1)

# Test 4: Check TempGenerationWindow methods
print("\n[Test 4] Check TempGenerationWindow methods...")
try:
    methods = [
        'set_prompts',
        'set_initial_params',
        'update_params_ui_for_mode'
    ]
    for method in methods:
        if hasattr(TempGenerationWindow, method):
            print(f"  OK: {method} exists")
        else:
            print(f"  FAIL: {method} missing")
            sys.exit(1)
except Exception as e:
    print(f"FAIL: Method check failed: {e}")
    sys.exit(1)

# Test 5: Check method signatures
print("\n[Test 5] Check method signatures...")
try:
    import inspect

    # Check collect_parameters
    sig = inspect.signature(TempGenerationParamsWidget.collect_parameters)
    print(f"  collect_parameters signature: {sig}")

    # Check set_initial_values
    sig2 = inspect.signature(TempGenerationParamsWidget.set_initial_values)
    print(f"  set_initial_values signature: {sig2}")

    # Check update_ui_for_mode
    sig3 = inspect.signature(TempGenerationParamsWidget.update_ui_for_mode)
    print(f"  update_ui_for_mode signature: {sig3}")

except Exception as e:
    print(f"FAIL: Signature check failed: {e}")
    sys.exit(1)

print("\n" + "=" * 60)
print("ALL TESTS PASSED!")
print("=" * 60)
print("\nNext steps for manual testing:")
print("  1. Run NAIA application")
print("  2. Click [Temp] button to create temporary window")
print("  3. Verify parameters are copied correctly")
print("  4. Test API mode change confirmation dialog")
print("  5. Test NAI model change confirmation (NAID3 <-> NAID4.x)")
print("=" * 60)
