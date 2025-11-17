# test_sequence_integration.py

"""
시퀀스 생성 통합 테스트

이 파일은 GenerationController의 시퀀스 생성 기능을 테스트합니다.

실행 방법:
    python test_sequence_integration.py
"""

import sys
import os

# 프로젝트 루트를 Python 경로에 추가
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.sequence_parser import SequenceParser


class TestSequenceIntegration:
    """시퀀스 생성 통합 테스트"""

    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.test_results = []

    def assert_equal(self, actual, expected, test_name):
        """값 비교 어설션"""
        if actual == expected:
            self.passed += 1
            self.test_results.append(f"[OK] PASS: {test_name}")
            return True
        else:
            self.failed += 1
            self.test_results.append(f"[FAIL] FAIL: {test_name}")
            self.test_results.append(f"   Expected: {expected}")
            self.test_results.append(f"   Actual: {actual}")
            return False

    def assert_true(self, condition, test_name):
        """조건 어설션"""
        return self.assert_equal(condition, True, test_name)

    def assert_in(self, item, container, test_name):
        """포함 어설션"""
        if item in container:
            self.passed += 1
            self.test_results.append(f"[OK] PASS: {test_name}")
            return True
        else:
            self.failed += 1
            self.test_results.append(f"[FAIL] FAIL: {test_name}")
            self.test_results.append(f"   '{item}' not in container")
            return False

    # ==================== 통합 테스트 ====================

    def test_srs_example_1(self):
        """SRS 예제 1 - 기본 사용법"""
        prompt = """1girl, solo, looking at viewer,
:begin
:seq1 :o, ?,
:seq2 open mouth, hands up, happy,
:seq3 closed mouth, smile,
:end
detailed background, year 2024, aesthetic"""

        # 1. 시퀀스 감지
        is_seq = SequenceParser.is_sequence_prompt(prompt)
        self.assert_true(is_seq, "SRS 예제 1: 시퀀스 감지")

        # 2. 파싱
        parsed = SequenceParser.parse_prompt(prompt)
        self.assert_equal(len(parsed["sequences"]), 3, "SRS 예제 1: 3개 시퀀스")

        # 3. 검증
        is_valid, msg = SequenceParser.validate_structure(parsed)
        self.assert_true(is_valid, "SRS 예제 1: 검증 통과")

        # 4. 프롬프트 세트 생성
        sets = SequenceParser.generate_prompt_sets(parsed)
        self.assert_equal(len(sets), 3, "SRS 예제 1: 3개 프롬프트 세트")

        # 5. 첫 번째 세트 검증
        expected_elements = ["1girl", "solo", "looking at viewer", ":o", "detailed background", "year 2024", "aesthetic"]
        for elem in expected_elements:
            self.assert_in(elem, sets[0], f"SRS 예제 1: 첫 번째 세트에 '{elem}'")

        # 6. 두 번째 세트 검증
        self.assert_in("open mouth", sets[1], "SRS 예제 1: 두 번째 세트에 'open mouth'")
        self.assert_in("hands up", sets[1], "SRS 예제 1: 두 번째 세트에 'hands up'")

        # 7. 세 번째 세트 검증
        self.assert_in("closed mouth", sets[2], "SRS 예제 1: 세 번째 세트에 'closed mouth'")
        self.assert_in("smile", sets[2], "SRS 예제 1: 세 번째 세트에 'smile'")

    def test_srs_example_2(self):
        """SRS 예제 2 - 해상도 및 Seed 지정"""
        prompt = """1girl, resolution:832x1216,
:begin
:seq1 seed:12345, standing,
:seq2 seed:67890, sitting,
:end
park, sunny day"""

        # 1. 파싱 및 프롬프트 세트 생성
        parsed = SequenceParser.parse_prompt(prompt)
        sets = SequenceParser.generate_prompt_sets(parsed)

        self.assert_equal(len(sets), 2, "SRS 예제 2: 2개 프롬프트 세트")

        # 2. resolution: 태그가 첫 번째 프롬프트에 포함되어야 함
        self.assert_in("resolution:832x1216", sets[0], "SRS 예제 2: resolution 태그 포함")

        # 3. seed: 태그가 각 프롬프트에 포함되어야 함
        self.assert_in("seed:12345", sets[0], "SRS 예제 2: 첫 번째 seed 태그")
        self.assert_in("seed:67890", sets[1], "SRS 예제 2: 두 번째 seed 태그")

        # 4. 공통 요소 확인
        for s in sets:
            self.assert_in("1girl", s, "SRS 예제 2: 모든 세트에 '1girl'")
            self.assert_in("park", s, "SRS 예제 2: 모든 세트에 'park'")
            self.assert_in("sunny day", s, "SRS 예제 2: 모든 세트에 'sunny day'")

    def test_srs_example_3(self):
        """SRS 예제 3 - 빈 begin 영역"""
        prompt = """masterpiece, best quality,
:begin,
:seq1 red hair, blue eyes,
:seq2 blonde hair, green eyes,
:end,
portrait, detailed face"""

        parsed = SequenceParser.parse_prompt(prompt)
        sets = SequenceParser.generate_prompt_sets(parsed)

        self.assert_equal(len(sets), 2, "SRS 예제 3: 2개 프롬프트 세트")

        # 첫 번째 세트
        self.assert_in("masterpiece", sets[0], "SRS 예제 3: 첫 번째 세트에 'masterpiece'")
        self.assert_in("red hair", sets[0], "SRS 예제 3: 첫 번째 세트에 'red hair'")
        self.assert_in("blue eyes", sets[0], "SRS 예제 3: 첫 번째 세트에 'blue eyes'")
        self.assert_in("portrait", sets[0], "SRS 예제 3: 첫 번째 세트에 'portrait'")

        # 두 번째 세트
        self.assert_in("blonde hair", sets[1], "SRS 예제 3: 두 번째 세트에 'blonde hair'")
        self.assert_in("green eyes", sets[1], "SRS 예제 3: 두 번째 세트에 'green eyes'")

    def test_complex_prompt(self):
        """복잡한 프롬프트 테스트"""
        prompt = """masterpiece, best quality, 1girl, solo, looking at viewer,
:begin standing, outdoors,
:seq1 happy, smiling, peace sign,
:seq2 surprised, :o, ?,
:seq3 angry, >:(, clenched fist,
:seq4 sad, crying, tears,
:end detailed background, year 2024, aesthetic, beautiful lighting"""

        parsed = SequenceParser.parse_prompt(prompt)
        sets = SequenceParser.generate_prompt_sets(parsed)

        self.assert_equal(len(sets), 4, "복잡한 프롬프트: 4개 세트")

        # 각 세트가 고유한 표정을 포함하는지 확인
        self.assert_in("happy", sets[0], "복잡한 프롬프트: 세트 1에 'happy'")
        self.assert_in("surprised", sets[1], "복잡한 프롬프트: 세트 2에 'surprised'")
        self.assert_in("angry", sets[2], "복잡한 프롬프트: 세트 3에 'angry'")
        self.assert_in("sad", sets[3], "복잡한 프롬프트: 세트 4에 'sad'")

        # 모든 세트가 공통 요소를 포함하는지 확인
        for i, s in enumerate(sets):
            self.assert_in("masterpiece", s, f"복잡한 프롬프트: 세트 {i+1}에 'masterpiece'")
            self.assert_in("standing", s, f"복잡한 프롬프트: 세트 {i+1}에 'standing'")
            self.assert_in("detailed background", s, f"복잡한 프롬프트: 세트 {i+1}에 'detailed background'")

    def test_edge_case_many_sequences(self):
        """에지 케이스: 많은 시퀀스"""
        sequences = [f":seq{i} pose{i}," for i in range(1, 11)]  # 10개 시퀀스
        sequences_text = "\n".join(sequences)

        prompt = f"""1girl,
:begin
{sequences_text}
:end
background"""

        parsed = SequenceParser.parse_prompt(prompt)
        sets = SequenceParser.generate_prompt_sets(parsed)

        self.assert_equal(len(sets), 10, "많은 시퀀스: 10개 세트")

        # 각 세트가 고유한 pose를 포함하는지 확인
        for i in range(10):
            self.assert_in(f"pose{i+1}", sets[i], f"많은 시퀀스: 세트 {i+1}에 'pose{i+1}'")

    def test_edge_case_minimal(self):
        """에지 케이스: 최소 구성"""
        prompt = ":begin :seq1 test :end"

        parsed = SequenceParser.parse_prompt(prompt)
        sets = SequenceParser.generate_prompt_sets(parsed)

        self.assert_equal(len(sets), 1, "최소 구성: 1개 세트")
        self.assert_in("test", sets[0], "최소 구성: 'test' 포함")

    # ==================== 실행 메서드 ====================

    def run_all_tests(self):
        """모든 테스트 실행"""
        print("=" * 70)
        print("Sequence Generation Integration Test")
        print("=" * 70)
        print()

        print("[1/6] SRS Example 1 - Basic usage...")
        self.test_srs_example_1()

        print("[2/6] SRS Example 2 - Resolution and Seed...")
        self.test_srs_example_2()

        print("[3/6] SRS Example 3 - Empty begin area...")
        self.test_srs_example_3()

        print("[4/6] Complex prompt test...")
        self.test_complex_prompt()

        print("[5/6] Edge case - Many sequences...")
        self.test_edge_case_many_sequences()

        print("[6/6] Edge case - Minimal configuration...")
        self.test_edge_case_minimal()

        # 결과 출력
        print()
        print("=" * 70)
        print("Test Results")
        print("=" * 70)
        for result in self.test_results:
            print(result)

        print()
        print("=" * 70)
        print(f"Total: {self.passed + self.failed} tests")
        print(f"[OK] Passed: {self.passed}")
        print(f"[FAIL] Failed: {self.failed}")
        print(f"Success Rate: {self.passed / (self.passed + self.failed) * 100:.1f}%")
        print("=" * 70)

        return self.failed == 0


if __name__ == "__main__":
    # UTF-8 인코딩 설정 (Windows 호환성)
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

    tester = TestSequenceIntegration()
    success = tester.run_all_tests()

    if success:
        print("\n[SUCCESS] All integration tests passed!")
        sys.exit(0)
    else:
        print(f"\n[WARNING] {tester.failed} test(s) failed.")
        sys.exit(1)
