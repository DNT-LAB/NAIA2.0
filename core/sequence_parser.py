# core/sequence_parser.py

"""
시퀀스 프롬프트 파싱 및 검증 모듈

이 모듈은 사용자가 입력한 시퀀스 프롬프트(:begin, :seq, :end 구문)를
파싱하고 검증하여 여러 개의 프롬프트 세트로 변환하는 기능을 제공합니다.

Example:
    >>> prompt = "1girl, :begin :seq1 happy :seq2 sad :end bg"
    >>> parser = SequenceParser()
    >>> if parser.is_sequence_prompt(prompt):
    ...     parsed = parser.parse_prompt(prompt)
    ...     is_valid, msg = parser.validate_structure(parsed)
    ...     if is_valid:
    ...         sets = parser.generate_prompt_sets(parsed)
"""

import re
from typing import Dict, List, Tuple


class SequenceParser:
    """
    시퀀스 프롬프트 파싱 및 검증을 담당하는 클래스

    시퀀스 프롬프트는 다음 구조를 가집니다:
    [prefix], :begin [begin_content], :seq[id] [seq_content], ..., :end [end_content]

    Attributes:
        TOKEN_BEGIN: 시퀀스 시작 토큰 (:begin)
        TOKEN_SEQ_PREFIX: 시퀀스 토큰 접두사 (:seq)
        TOKEN_END: 시퀀스 종료 토큰 (:end)
    """

    # 토큰 정의
    TOKEN_BEGIN = ":begin"
    TOKEN_SEQ_PREFIX = ":seq"
    TOKEN_END = ":end"

    # 정규식 패턴
    PATTERN_BEGIN = r':begin'
    PATTERN_SEQ = r':seq[^\s,\n]*'  # :seq 뒤에 임의의 문자 (공백, 쉼표, 개행 아님)
    PATTERN_END = r':end'

    @staticmethod
    def is_sequence_prompt(text: str) -> bool:
        """
        프롬프트가 시퀀스 구문을 포함하는지 확인

        Args:
            text: 검사할 프롬프트 텍스트

        Returns:
            bool: :begin과 :end가 모두 포함되어 있으면 True
        """
        if not text or not isinstance(text, str):
            return False

        text_lower = text.lower()
        return SequenceParser.TOKEN_BEGIN in text_lower and SequenceParser.TOKEN_END in text_lower

    @staticmethod
    def parse_prompt(text: str) -> Dict[str, any]:
        """
        프롬프트를 파싱하여 구조화된 딕셔너리 반환

        Args:
            text: 원본 프롬프트 텍스트

        Returns:
            dict: {
                "prefix": str,       # :begin 이전의 텍스트
                "begin": str,        # :begin 다음 ~ 첫 :seq 이전
                "sequences": List[str],  # 각 :seq의 내용
                "end": str           # :end 이후의 텍스트
            }

        Raises:
            ValueError: 파싱 실패 시 (예: :begin이나 :end가 없는 경우)
        """
        if not text:
            raise ValueError("프롬프트가 비어있습니다.")

        # 대소문자 구분 없이 처리하기 위해 원본과 소문자 버전 모두 사용
        text_lower = text.lower()

        # :begin과 :end 위치 찾기
        begin_pos = text_lower.find(SequenceParser.TOKEN_BEGIN)
        end_pos = text_lower.find(SequenceParser.TOKEN_END)

        if begin_pos == -1:
            raise ValueError(":begin 토큰을 찾을 수 없습니다.")
        if end_pos == -1:
            raise ValueError(":end 토큰을 찾을 수 없습니다.")
        if begin_pos >= end_pos:
            raise ValueError(":begin이 :end보다 뒤에 있습니다.")

        # 🔧 FIX MEDIUM-3: 중복 토큰 검증
        begin_count = text_lower.count(SequenceParser.TOKEN_BEGIN)
        end_count = text_lower.count(SequenceParser.TOKEN_END)
        if begin_count > 1:
            raise ValueError(f":begin 토큰이 {begin_count}개 발견되었습니다. 1개만 허용됩니다.")
        if end_count > 1:
            raise ValueError(f":end 토큰이 {end_count}개 발견되었습니다. 1개만 허용됩니다.")

        # 1. prefix 추출 (:begin 이전)
        prefix = text[:begin_pos].strip()
        prefix = SequenceParser._remove_trailing_separator(prefix)

        # 2. :begin 이후부터 :end 이전까지의 영역
        begin_start = begin_pos + len(SequenceParser.TOKEN_BEGIN)
        sequence_area = text[begin_start:end_pos]

        # 3. :seq 토큰들을 찾기
        seq_pattern = re.compile(SequenceParser.PATTERN_SEQ, re.IGNORECASE)
        seq_matches = list(seq_pattern.finditer(sequence_area))

        # 4. begin 영역 추출 (첫 번째 :seq 이전)
        if seq_matches:
            first_seq_pos = seq_matches[0].start()
            begin_content = sequence_area[:first_seq_pos].strip()
            begin_content = SequenceParser._remove_leading_separator(begin_content)
            begin_content = SequenceParser._remove_trailing_separator(begin_content)
        else:
            # :seq가 없는 경우 전체가 begin 영역
            begin_content = sequence_area.strip()
            begin_content = SequenceParser._remove_leading_separator(begin_content)
            begin_content = SequenceParser._remove_trailing_separator(begin_content)

        # 5. sequences 추출
        sequences = []
        for i, match in enumerate(seq_matches):
            # :seq 토큰 다음부터 다음 :seq 또는 끝까지
            seq_start = match.end()
            seq_end = seq_matches[i + 1].start() if i + 1 < len(seq_matches) else len(sequence_area)

            seq_content = sequence_area[seq_start:seq_end].strip()
            seq_content = SequenceParser._remove_leading_separator(seq_content)
            seq_content = SequenceParser._remove_trailing_separator(seq_content)

            sequences.append(seq_content)

        # 6. end 영역 추출 (:end 이후)
        end_start = end_pos + len(SequenceParser.TOKEN_END)
        end_content = text[end_start:].strip()
        end_content = SequenceParser._remove_leading_separator(end_content)

        return {
            "prefix": prefix,
            "begin": begin_content,
            "sequences": sequences,
            "end": end_content
        }

    @staticmethod
    def validate_structure(parsed: Dict[str, any]) -> Tuple[bool, str]:
        """
        파싱된 구조 검증

        Args:
            parsed: parse_prompt()의 반환값

        Returns:
            tuple: (검증 성공 여부, 에러 메시지)
                - (True, ""): 검증 성공
                - (False, "error message"): 검증 실패
        """
        # 필수 키 확인
        required_keys = ["prefix", "begin", "sequences", "end"]
        for key in required_keys:
            if key not in parsed:
                return (False, f"파싱 결과에 '{key}' 키가 없습니다.")

        # sequences가 리스트인지 확인
        if not isinstance(parsed["sequences"], list):
            return (False, "sequences가 리스트 타입이 아닙니다.")

        # sequences가 비어있는지 확인
        if len(parsed["sequences"]) == 0:
            return (False, "시퀀스가 비어있습니다. 최소 1개의 :seq 토큰이 필요합니다.")

        # 모든 검증 통과
        return (True, "")

    @staticmethod
    def generate_prompt_sets(parsed: Dict[str, any]) -> List[str]:
        """
        파싱된 딕셔너리로부터 프롬프트 세트 생성

        Args:
            parsed: parse_prompt()의 반환값

        Returns:
            List[str]: 생성된 프롬프트 리스트

        Example:
            >>> parsed = {
            ...     "prefix": "1girl, solo",
            ...     "begin": "looking at viewer",
            ...     "sequences": ["happy", "sad"],
            ...     "end": "detailed bg"
            ... }
            >>> sets = SequenceParser.generate_prompt_sets(parsed)
            >>> print(sets[0])
            "1girl, solo, looking at viewer, happy, detailed bg"
        """
        prefix = parsed.get("prefix", "")
        begin = parsed.get("begin", "")
        sequences = parsed.get("sequences", [])
        end = parsed.get("end", "")

        prompt_sets = []

        for seq in sequences:
            # 각 부분을 리스트에 모음
            parts = []

            if prefix:
                parts.append(prefix)
            if begin:
                parts.append(begin)
            if seq:
                parts.append(seq)
            if end:
                parts.append(end)

            # ", "로 연결
            prompt = ", ".join(parts)

            # 정규화
            prompt = SequenceParser._normalize_text(prompt)

            prompt_sets.append(prompt)

        return prompt_sets

    @staticmethod
    def _normalize_text(text: str) -> str:
        """
        텍스트 정규화 (공백 정리, 연속 쉼표 제거)

        Args:
            text: 원본 텍스트

        Returns:
            str: 정규화된 텍스트
        """
        if not text:
            return ""

        # 1. 연속된 공백을 하나로
        text = re.sub(r'\s+', ' ', text)

        # 2. 연속된 쉼표를 하나로 (사이 공백 포함)
        text = re.sub(r',\s*,+', ',', text)

        # 3. 쉼표 앞뒤 공백 정리 (쉼표 뒤에만 공백 하나)
        text = re.sub(r'\s*,\s*', ', ', text)

        # 4. 시작과 끝 쉼표/공백 제거
        text = text.strip().strip(',').strip()

        return text

    @staticmethod
    def _remove_leading_separator(text: str) -> str:
        """
        텍스트 앞의 구분자 제거 (쉼표, 공백)

        Args:
            text: 원본 텍스트

        Returns:
            str: 구분자가 제거된 텍스트
        """
        if not text:
            return ""

        # 앞쪽 공백과 쉼표 제거 (반복)
        while text and text[0] in [' ', ',', '\n', '\t']:
            text = text[1:]

        return text

    @staticmethod
    def _remove_trailing_separator(text: str) -> str:
        """
        텍스트 뒤의 구분자 제거 (쉼표, 공백)

        Args:
            text: 원본 텍스트

        Returns:
            str: 구분자가 제거된 텍스트
        """
        if not text:
            return ""

        # 뒤쪽 공백과 쉼표 제거 (반복)
        while text and text[-1] in [' ', ',', '\n', '\t']:
            text = text[:-1]

        return text


# 편의를 위한 함수형 인터페이스
def is_sequence_prompt(text: str) -> bool:
    """SequenceParser.is_sequence_prompt()의 함수형 래퍼"""
    return SequenceParser.is_sequence_prompt(text)


def parse_sequence_prompt(text: str) -> Dict[str, any]:
    """SequenceParser.parse_prompt()의 함수형 래퍼"""
    return SequenceParser.parse_prompt(text)


def validate_sequence_structure(parsed: Dict[str, any]) -> Tuple[bool, str]:
    """SequenceParser.validate_structure()의 함수형 래퍼"""
    return SequenceParser.validate_structure(parsed)


def generate_sequence_prompt_sets(parsed: Dict[str, any]) -> List[str]:
    """SequenceParser.generate_prompt_sets()의 함수형 래퍼"""
    return SequenceParser.generate_prompt_sets(parsed)
