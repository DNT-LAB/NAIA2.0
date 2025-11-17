# test_sequence_parser.py

"""
SequenceParser 유닛 테스트

이 파일은 core/sequence_parser.py의 모든 기능을 테스트합니다.

실행 방법:
    python test_sequence_parser.py
"""

import sys
import os

# 프로젝트 루트를 Python 경로에 추가
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.sequence_parser import SequenceParser


class TestSequenceParser:
    """SequenceParser 테스트 클래스"""

    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.test_results = []

    def assert_equal(self, actual, expected, test_name):
        """값 비교 어설션"""
        if actual == expected:
            self.passed += 1
            self.test_results.append(f"✅ PASS: {test_name}")
            return True
        else:
            self.failed += 1
            self.test_results.append(f"❌ FAIL: {test_name}")
            self.test_results.append(f"   Expected: {expected}")
            self.test_results.append(f"   Actual: {actual}")
            return False

    def assert_true(self, condition, test_name):
        """조건 어설션"""
        return self.assert_equal(condition, True, test_name)

    def assert_false(self, condition, test_name):
        """거짓 조건 어설션"""
        return self.assert_equal(condition, False, test_name)

    def assert_in(self, item, container, test_name):
        """포함 어설션"""
        if item in container:
            self.passed += 1
            self.test_results.append(f"✅ PASS: {test_name}")
            return True
        else:
            self.failed += 1
            self.test_results.append(f"❌ FAIL: {test_name}")
            self.test_results.append(f"   '{item}' not in '{container}'")
            return False

    # ==================== is_sequence_prompt 테스트 ====================

    def test_is_sequence_prompt_valid(self):
        """시퀀스 구문 감지 - 정상 케이스"""
        prompt = "1girl, :begin :seq1 happy :end bg"
        result = SequenceParser.is_sequence_prompt(prompt)
        self.assert_true(result, "is_sequence_prompt: 정상 시퀀스 감지")

    def test_is_sequence_prompt_invalid(self):
        """시퀀스 구문 감지 - 일반 프롬프트"""
        prompt = "1girl, happy, detailed background"
        result = SequenceParser.is_sequence_prompt(prompt)
        self.assert_false(result, "is_sequence_prompt: 일반 프롬프트는 False")

    def test_is_sequence_prompt_only_begin(self):
        """시퀀스 구문 감지 - :begin만 있는 경우"""
        prompt = "1girl, :begin happy"
        result = SequenceParser.is_sequence_prompt(prompt)
        self.assert_false(result, "is_sequence_prompt: :begin만 있으면 False")

    def test_is_sequence_prompt_only_end(self):
        """시퀀스 구문 감지 - :end만 있는 경우"""
        prompt = "1girl, happy :end bg"
        result = SequenceParser.is_sequence_prompt(prompt)
        self.assert_false(result, "is_sequence_prompt: :end만 있으면 False")

    def test_is_sequence_prompt_case_insensitive(self):
        """시퀀스 구문 감지 - 대소문자 무시"""
        prompt = "1girl, :BEGIN :seq1 happy :END bg"
        result = SequenceParser.is_sequence_prompt(prompt)
        self.assert_true(result, "is_sequence_prompt: 대소문자 무시")

    def test_is_sequence_prompt_empty(self):
        """시퀀스 구문 감지 - 빈 문자열"""
        prompt = ""
        result = SequenceParser.is_sequence_prompt(prompt)
        self.assert_false(result, "is_sequence_prompt: 빈 문자열은 False")

    # ==================== parse_prompt 테스트 ====================

    def test_parse_prompt_basic(self):
        """기본 파싱 테스트"""
        prompt = "1girl, solo, :begin :seq1 happy :seq2 sad :end detailed bg"
        parsed = SequenceParser.parse_prompt(prompt)

        self.assert_equal(parsed["prefix"], "1girl, solo", "parse_prompt: prefix 추출")
        self.assert_equal(len(parsed["sequences"]), 2, "parse_prompt: 2개 시퀀스")
        self.assert_in("happy", parsed["sequences"][0], "parse_prompt: 첫 번째 시퀀스에 'happy'")
        self.assert_in("sad", parsed["sequences"][1], "parse_prompt: 두 번째 시퀀스에 'sad'")
        self.assert_equal(parsed["end"], "detailed bg", "parse_prompt: end 추출")

    def test_parse_prompt_with_comma_separator(self):
        """쉼표 구분자 테스트"""
        prompt = "1girl, :begin, :seq1, happy, :seq2, sad, :end, bg"
        parsed = SequenceParser.parse_prompt(prompt)

        self.assert_equal(len(parsed["sequences"]), 2, "parse_prompt: 쉼표 구분자로 2개 시퀀스")

    def test_parse_prompt_with_newline(self):
        """개행문자 구분자 테스트"""
        prompt = """1girl, solo,
:begin
:seq1 happy
:seq2 sad
:end
detailed bg"""
        parsed = SequenceParser.parse_prompt(prompt)

        self.assert_equal(len(parsed["sequences"]), 2, "parse_prompt: 개행문자 구분자로 2개 시퀀스")

    def test_parse_prompt_no_prefix(self):
        """prefix 없는 경우"""
        prompt = ":begin :seq1 happy :end bg"
        parsed = SequenceParser.parse_prompt(prompt)

        self.assert_equal(parsed["prefix"], "", "parse_prompt: prefix 없음")
        self.assert_equal(len(parsed["sequences"]), 1, "parse_prompt: 1개 시퀀스")

    def test_parse_prompt_no_end_content(self):
        """end 영역 없는 경우"""
        prompt = "1girl, :begin :seq1 happy :end"
        parsed = SequenceParser.parse_prompt(prompt)

        self.assert_equal(parsed["end"], "", "parse_prompt: end 영역 없음")

    def test_parse_prompt_with_begin_content(self):
        """begin 영역에 내용이 있는 경우"""
        prompt = "1girl, :begin looking at viewer, :seq1 happy :end bg"
        parsed = SequenceParser.parse_prompt(prompt)

        self.assert_in("looking at viewer", parsed["begin"], "parse_prompt: begin 영역에 내용")

    def test_parse_prompt_seq_variations(self):
        """:seq 토큰 변형 테스트"""
        prompt = "1girl, :begin :seq1 a :seqx b :seqqq c :end d"
        parsed = SequenceParser.parse_prompt(prompt)

        self.assert_equal(len(parsed["sequences"]), 3, "parse_prompt: :seq 변형 3개")

    def test_parse_prompt_special_characters(self):
        """특수문자 포함 테스트"""
        prompt = "1girl, :begin :seq1 :o, ?, <3 :seq2 ^_^ :end bg"
        parsed = SequenceParser.parse_prompt(prompt)

        self.assert_in(":o", parsed["sequences"][0], "parse_prompt: 특수문자 포함")
        self.assert_in("^_^", parsed["sequences"][1], "parse_prompt: 특수문자 포함")

    def test_parse_prompt_missing_begin(self):
        """:begin 누락 케이스"""
        prompt = "1girl, :seq1 happy :end bg"
        try:
            parsed = SequenceParser.parse_prompt(prompt)
            self.assert_true(False, "parse_prompt: :begin 누락 시 ValueError 발생해야 함")
        except ValueError as e:
            self.assert_in(":begin", str(e), "parse_prompt: :begin 누락 에러 메시지")

    def test_parse_prompt_missing_end(self):
        """:end 누락 케이스"""
        prompt = "1girl, :begin :seq1 happy"
        try:
            parsed = SequenceParser.parse_prompt(prompt)
            self.assert_true(False, "parse_prompt: :end 누락 시 ValueError 발생해야 함")
        except ValueError as e:
            self.assert_in(":end", str(e), "parse_prompt: :end 누락 에러 메시지")

    def test_parse_prompt_wrong_order(self):
        """:begin과 :end 순서 오류"""
        prompt = "1girl, :end :begin :seq1 happy"
        try:
            parsed = SequenceParser.parse_prompt(prompt)
            self.assert_true(False, "parse_prompt: 순서 오류 시 ValueError 발생해야 함")
        except ValueError as e:
            self.assert_true(True, "parse_prompt: 순서 오류 감지")

    def test_parse_prompt_duplicate_begin(self):
        """🆕 중복 :begin 토큰 감지 (MEDIUM-3 수정 검증)"""
        prompt = "1girl, :begin :seq1 happy :begin :seq2 sad :end bg"
        try:
            parsed = SequenceParser.parse_prompt(prompt)
            self.assert_true(False, "parse_prompt: 중복 :begin 시 ValueError 발생해야 함")
        except ValueError as e:
            self.assert_in(":begin", str(e).lower(), "parse_prompt: 중복 :begin 에러 메시지")
            self.assert_in("2", str(e), "parse_prompt: 개수 2 표시")

    def test_parse_prompt_duplicate_end(self):
        """🆕 중복 :end 토큰 감지 (MEDIUM-3 수정 검증)"""
        prompt = "1girl, :begin :seq1 happy :end :seq2 sad :end bg"
        try:
            parsed = SequenceParser.parse_prompt(prompt)
            self.assert_true(False, "parse_prompt: 중복 :end 시 ValueError 발생해야 함")
        except ValueError as e:
            self.assert_in(":end", str(e).lower(), "parse_prompt: 중복 :end 에러 메시지")
            self.assert_in("2", str(e), "parse_prompt: 개수 2 표시")

    def test_parse_prompt_multiple_duplicates(self):
        """🆕 다중 중복 토큰 감지 (MEDIUM-3 수정 검증)"""
        prompt = ":begin :begin :begin :seq1 a :end bg"
        try:
            parsed = SequenceParser.parse_prompt(prompt)
            self.assert_true(False, "parse_prompt: 3개 :begin 시 ValueError 발생해야 함")
        except ValueError as e:
            self.assert_in("3", str(e), "parse_prompt: 개수 3 표시")

    # ==================== validate_structure 테스트 ====================

    def test_validate_structure_valid(self):
        """검증 - 정상 구조"""
        parsed = {
            "prefix": "1girl",
            "begin": "",
            "sequences": ["happy", "sad"],
            "end": "bg"
        }
        is_valid, msg = SequenceParser.validate_structure(parsed)
        self.assert_true(is_valid, "validate_structure: 정상 구조 검증 통과")

    def test_validate_structure_empty_sequences(self):
        """검증 - 빈 시퀀스"""
        parsed = {
            "prefix": "1girl",
            "begin": "",
            "sequences": [],
            "end": "bg"
        }
        is_valid, msg = SequenceParser.validate_structure(parsed)
        self.assert_false(is_valid, "validate_structure: 빈 시퀀스는 실패")
        self.assert_in("비어있습니다", msg, "validate_structure: 빈 시퀀스 에러 메시지")

    def test_validate_structure_missing_key(self):
        """검증 - 필수 키 누락"""
        parsed = {
            "prefix": "1girl",
            "sequences": ["happy"]
            # "begin"과 "end" 누락
        }
        is_valid, msg = SequenceParser.validate_structure(parsed)
        self.assert_false(is_valid, "validate_structure: 필수 키 누락은 실패")

    def test_validate_structure_invalid_sequences_type(self):
        """검증 - sequences가 리스트가 아닌 경우"""
        parsed = {
            "prefix": "1girl",
            "begin": "",
            "sequences": "not a list",
            "end": "bg"
        }
        is_valid, msg = SequenceParser.validate_structure(parsed)
        self.assert_false(is_valid, "validate_structure: sequences 타입 오류")

    # ==================== generate_prompt_sets 테스트 ====================

    def test_generate_prompt_sets_basic(self):
        """프롬프트 세트 생성 - 기본"""
        parsed = {
            "prefix": "1girl",
            "begin": "",
            "sequences": ["happy", "sad"],
            "end": "bg"
        }
        sets = SequenceParser.generate_prompt_sets(parsed)

        self.assert_equal(len(sets), 2, "generate_prompt_sets: 2개 세트 생성")
        self.assert_in("1girl", sets[0], "generate_prompt_sets: 첫 번째 세트에 prefix")
        self.assert_in("happy", sets[0], "generate_prompt_sets: 첫 번째 세트에 seq")
        self.assert_in("bg", sets[0], "generate_prompt_sets: 첫 번째 세트에 end")
        self.assert_in("sad", sets[1], "generate_prompt_sets: 두 번째 세트에 seq")

    def test_generate_prompt_sets_with_begin(self):
        """프롬프트 세트 생성 - begin 포함"""
        parsed = {
            "prefix": "1girl",
            "begin": "looking at viewer",
            "sequences": ["happy"],
            "end": "bg"
        }
        sets = SequenceParser.generate_prompt_sets(parsed)

        self.assert_in("looking at viewer", sets[0], "generate_prompt_sets: begin 포함")

    def test_generate_prompt_sets_no_prefix(self):
        """프롬프트 세트 생성 - prefix 없음"""
        parsed = {
            "prefix": "",
            "begin": "",
            "sequences": ["happy", "sad"],
            "end": "bg"
        }
        sets = SequenceParser.generate_prompt_sets(parsed)

        self.assert_equal(len(sets), 2, "generate_prompt_sets: prefix 없어도 생성")
        # 첫 번째 요소가 "happy"로 시작해야 함 (prefix가 없으므로)
        self.assert_in("happy", sets[0], "generate_prompt_sets: prefix 없으면 seq부터 시작")

    def test_generate_prompt_sets_complex(self):
        """프롬프트 세트 생성 - 복잡한 케이스"""
        parsed = {
            "prefix": "1girl, solo, looking at viewer",
            "begin": "standing",
            "sequences": [
                ":o, ?, surprised",
                "open mouth, hands up, happy",
                "closed mouth, teeth, smile, happy, hands up"
            ],
            "end": "detailed background, year 2024, aesthetic"
        }
        sets = SequenceParser.generate_prompt_sets(parsed)

        self.assert_equal(len(sets), 3, "generate_prompt_sets: 3개 세트 생성")

        # 첫 번째 세트 검증
        self.assert_in("1girl", sets[0], "generate_prompt_sets: 복잡한 케이스 - prefix")
        self.assert_in("standing", sets[0], "generate_prompt_sets: 복잡한 케이스 - begin")
        self.assert_in(":o", sets[0], "generate_prompt_sets: 복잡한 케이스 - seq1")
        self.assert_in("detailed background", sets[0], "generate_prompt_sets: 복잡한 케이스 - end")

        # 두 번째 세트 검증
        self.assert_in("open mouth", sets[1], "generate_prompt_sets: 복잡한 케이스 - seq2")

        # 세 번째 세트 검증
        self.assert_in("closed mouth", sets[2], "generate_prompt_sets: 복잡한 케이스 - seq3")

    # ==================== _normalize_text 테스트 ====================

    def test_normalize_text_spaces(self):
        """텍스트 정규화 - 공백 정리"""
        text = "1girl,   solo,    looking   at   viewer"
        normalized = SequenceParser._normalize_text(text)

        # 연속 공백이 하나로
        self.assert_false("  " in normalized, "_normalize_text: 연속 공백 제거")

    def test_normalize_text_commas(self):
        """텍스트 정규화 - 쉼표 정리"""
        text = "1girl,,, solo,, looking at viewer"
        normalized = SequenceParser._normalize_text(text)

        # 연속 쉼표가 하나로
        self.assert_false(",," in normalized, "_normalize_text: 연속 쉼표 제거")

    def test_normalize_text_trim(self):
        """텍스트 정규화 - 앞뒤 공백/쉼표 제거"""
        text = "  , 1girl, solo ,  "
        normalized = SequenceParser._normalize_text(text)

        # 앞뒤 공백과 쉼표 제거
        self.assert_equal(normalized[0], '1', "_normalize_text: 앞 공백/쉼표 제거")
        self.assert_false(normalized.endswith(' '), "_normalize_text: 뒤 공백 제거")
        self.assert_false(normalized.endswith(','), "_normalize_text: 뒤 쉼표 제거")

    # ==================== 통합 테스트 ====================

    def test_integration_full_pipeline(self):
        """통합 테스트 - 전체 파이프라인"""
        prompt = """1girl, solo, looking at viewer,
:begin
:seq1 :o, ?,
:seq2 open mouth, hands up, happy,
:seq3 closed mouth, teeth, smile, happy, hands up,
:end detailed background, year 2024, aesthetic"""

        # 1. 시퀀스 감지
        is_seq = SequenceParser.is_sequence_prompt(prompt)
        self.assert_true(is_seq, "통합 테스트: 시퀀스 감지")

        # 2. 파싱
        parsed = SequenceParser.parse_prompt(prompt)
        self.assert_equal(len(parsed["sequences"]), 3, "통합 테스트: 3개 시퀀스 파싱")

        # 3. 검증
        is_valid, msg = SequenceParser.validate_structure(parsed)
        self.assert_true(is_valid, "통합 테스트: 구조 검증 통과")

        # 4. 프롬프트 세트 생성
        sets = SequenceParser.generate_prompt_sets(parsed)
        self.assert_equal(len(sets), 3, "통합 테스트: 3개 프롬프트 세트 생성")

        # 5. 각 세트 검증
        self.assert_in("1girl", sets[0], "통합 테스트: 첫 번째 세트에 prefix")
        self.assert_in(":o", sets[0], "통합 테스트: 첫 번째 세트에 seq1")
        self.assert_in("detailed background", sets[0], "통합 테스트: 첫 번째 세트에 end")

        self.assert_in("open mouth", sets[1], "통합 테스트: 두 번째 세트에 seq2")
        self.assert_in("closed mouth", sets[2], "통합 테스트: 세 번째 세트에 seq3")

    def test_integration_example_from_srs(self):
        """통합 테스트 - SRS 예제"""
        prompt = """1girl, solo, looking at viewer,
:begin
:seq1 :o, ?,
:seq2 open mouth, hands up, happy,
:seq3 closed mouth, teeth, smile, happy, hands up,
:end detailed background, year 2024, aesthetic, ..."""

        parsed = SequenceParser.parse_prompt(prompt)
        sets = SequenceParser.generate_prompt_sets(parsed)

        # 예상 결과
        expected_count = 3
        self.assert_equal(len(sets), expected_count, "SRS 예제: 3개 프롬프트 생성")

        # 첫 번째 프롬프트에 필수 요소들이 포함되어야 함
        required_elements = ["1girl", "solo", "looking at viewer", ":o", "detailed background"]
        for elem in required_elements:
            self.assert_in(elem, sets[0], f"SRS 예제: 첫 번째 프롬프트에 '{elem}' 포함")

    # ==================== 실행 메서드 ====================

    def run_all_tests(self):
        """모든 테스트 실행"""
        print("=" * 70)
        print("SequenceParser Unit Test")
        print("=" * 70)
        print()

        # is_sequence_prompt 테스트
        print("[1/7] is_sequence_prompt tests...")
        self.test_is_sequence_prompt_valid()
        self.test_is_sequence_prompt_invalid()
        self.test_is_sequence_prompt_only_begin()
        self.test_is_sequence_prompt_only_end()
        self.test_is_sequence_prompt_case_insensitive()
        self.test_is_sequence_prompt_empty()

        # parse_prompt 테스트
        print("[2/7] parse_prompt tests...")
        self.test_parse_prompt_basic()
        self.test_parse_prompt_with_comma_separator()
        self.test_parse_prompt_with_newline()
        self.test_parse_prompt_no_prefix()
        self.test_parse_prompt_no_end_content()
        self.test_parse_prompt_with_begin_content()
        self.test_parse_prompt_seq_variations()
        self.test_parse_prompt_special_characters()
        self.test_parse_prompt_missing_begin()
        self.test_parse_prompt_missing_end()
        self.test_parse_prompt_wrong_order()
        # 🆕 MEDIUM-3 수정 검증 테스트
        self.test_parse_prompt_duplicate_begin()
        self.test_parse_prompt_duplicate_end()
        self.test_parse_prompt_multiple_duplicates()

        # validate_structure 테스트
        print("[3/7] validate_structure tests...")
        self.test_validate_structure_valid()
        self.test_validate_structure_empty_sequences()
        self.test_validate_structure_missing_key()
        self.test_validate_structure_invalid_sequences_type()

        # generate_prompt_sets 테스트
        print("[4/7] generate_prompt_sets tests...")
        self.test_generate_prompt_sets_basic()
        self.test_generate_prompt_sets_with_begin()
        self.test_generate_prompt_sets_no_prefix()
        self.test_generate_prompt_sets_complex()

        # _normalize_text 테스트
        print("[5/7] _normalize_text tests...")
        self.test_normalize_text_spaces()
        self.test_normalize_text_commas()
        self.test_normalize_text_trim()

        # 통합 테스트
        print("[6/7] Integration tests...")
        self.test_integration_full_pipeline()
        self.test_integration_example_from_srs()

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

    tester = TestSequenceParser()
    success = tester.run_all_tests()

    if success:
        print("\n[SUCCESS] All tests passed!")
        sys.exit(0)
    else:
        print(f"\n[WARNING] {tester.failed} test(s) failed.")
        sys.exit(1)
