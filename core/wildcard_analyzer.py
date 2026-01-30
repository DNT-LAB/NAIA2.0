# core/wildcard_analyzer.py

import re
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass


@dataclass
class WildcardInfo:
    """와일드카드 정보 클래스"""
    name: str  # 와일드카드 이름 (경로 포함)
    item_count: int  # 항목 개수
    is_sequential: bool = False  # 순차 와일드카드인가?
    master_name: Optional[str] = None  # 종속 와일드카드의 Master 이름
    advance_rate: int = 1  # 몇 번마다 전진하는가?
    level: int = 0  # 의존성 깊이 (0=독립, 1=1차 종속, 2=2차 종속...)


class WildcardAnalyzer:
    """
    와일드카드 의존성 분석 및 통계 계산 유틸리티
    프롬프트에서 순차/종속 와일드카드를 분석하고 조합 수를 계산합니다.
    """

    def __init__(self, wildcard_manager):
        """
        Args:
            wildcard_manager: WildcardManager 인스턴스
        """
        self.wildcard_manager = wildcard_manager

    def _find_wildcard_key(self, name: str) -> Optional[str]:
        """
        와일드카드 이름을 Fuzzy Matching으로 찾습니다.

        1. 정확한 이름으로 먼저 찾기
        2. 실패 시, 해당 이름으로 끝나는 키 찾기 (subfolder/name 지원)

        Args:
            name: 찾을 와일드카드 이름

        Returns:
            실제 와일드카드 키 (없으면 None)
        """
        wildcard_dict = self.wildcard_manager.wildcard_dict_tree

        # 1. 정확한 이름으로 찾기
        if name in wildcard_dict:
            return name

        # 2. 끝나는 이름으로 찾기 (subfolder/name 지원)
        for key in wildcard_dict.keys():
            if key.endswith('/' + name) or key.endswith('\\' + name):
                return key

        return None

    def parse_prompt(self, prompt: str) -> List[WildcardInfo]:
        """
        프롬프트에서 순차/종속 와일드카드를 추출합니다.

        Args:
            prompt: 분석할 프롬프트 문자열

        Returns:
            와일드카드 정보 리스트
        """
        wildcards = []

        # 복합 와일드카드 패턴: __*name__ 또는 __$master:slave__
        # .+? 는 non-greedy이므로 가능한 한 짧게 매칭하되, __ 까지는 진행
        compound_pattern = r'__(\*?)(\$?)(.+?)__'

        matches = re.findall(compound_pattern, prompt)

        for asterisk, dollar, content in matches:
            is_sequential = bool(asterisk)
            is_dependent = bool(dollar)

            if is_dependent:
                # 종속 와일드카드: $master:slave
                if ':' in content:
                    parts = content.split(':', 1)
                    master_name = parts[0].strip()
                    slave_name = parts[1].strip()

                    # Slave 와일드카드 정보
                    slave_count = self._get_wildcard_count(slave_name)
                    if slave_count > 0:
                        wildcards.append(WildcardInfo(
                            name=slave_name,
                            item_count=slave_count,
                            is_sequential=True,  # 종속은 항상 순차적
                            master_name=master_name
                        ))
                else:
                    # 잘못된 종속 구문
                    continue
            elif is_sequential:
                # 순차 와일드카드: *name
                count = self._get_wildcard_count(content)
                if count > 0:
                    wildcards.append(WildcardInfo(
                        name=content,
                        item_count=count,
                        is_sequential=True
                    ))

        return wildcards

    def _get_wildcard_count(self, wildcard_name: str) -> int:
        """
        와일드카드의 항목 개수를 반환합니다.
        Fuzzy Matching을 사용하여 찾습니다.

        Args:
            wildcard_name: 와일드카드 이름

        Returns:
            항목 개수 (존재하지 않으면 0)
        """
        # Fuzzy Matching으로 실제 키 찾기
        actual_key = self._find_wildcard_key(wildcard_name)
        if not actual_key:
            return 0

        lines = self.wildcard_manager.wildcard_dict_tree.get(actual_key)
        return len(lines) if lines else 0

    def build_dependency_chain(self, wildcards: List[WildcardInfo]) -> List[WildcardInfo]:
        """
        와일드카드 의존성 체인을 구성하고 레벨을 계산합니다.

        Args:
            wildcards: 파싱된 와일드카드 리스트

        Returns:
            의존성 정보가 추가된 와일드카드 리스트
        """
        # 이름으로 인덱싱
        wildcard_map = {wc.name: wc for wc in wildcards}

        # 의존성 레벨 계산
        def calculate_level(wc: WildcardInfo, visited=None) -> int:
            if visited is None:
                visited = set()

            # 순환 참조 방지
            if wc.name in visited:
                return 0
            visited.add(wc.name)

            # Master가 없으면 레벨 0 (독립)
            if not wc.master_name:
                return 0

            # Master가 리스트에 없으면 레벨 1
            master_wc = wildcard_map.get(wc.master_name)
            if not master_wc:
                return 1

            # Master의 레벨 + 1
            return calculate_level(master_wc, visited) + 1

        # 각 와일드카드의 레벨 설정
        for wc in wildcards:
            wc.level = calculate_level(wc)

        # 레벨 순으로 정렬
        wildcards.sort(key=lambda x: x.level)

        return wildcards

    def calculate_advance_rates(self, wildcards: List[WildcardInfo]) -> Dict[str, int]:
        """
        각 와일드카드의 전진 속도를 계산합니다.

        Args:
            wildcards: 의존성 체인이 구성된 와일드카드 리스트

        Returns:
            {와일드카드명: 전진 속도} 딕셔너리
        """
        rates = {}

        for wc in wildcards:
            if not wc.master_name:
                # 독립 와일드카드: 매번 전진
                rates[wc.name] = 1
                wc.advance_rate = 1
            else:
                # 종속 와일드카드: Master의 사이클 * Master의 전진 속도
                # Fuzzy Matching으로 Master 찾기
                actual_master_key = self._find_wildcard_key(wc.master_name)

                if actual_master_key:
                    master_count = self._get_wildcard_count(wc.master_name)
                    # rates에서 Master의 advance_rate를 찾을 때도 실제 키 사용
                    master_rate = rates.get(actual_master_key, 1)
                    advance_rate = master_count * master_rate
                else:
                    # Master를 찾을 수 없으면 기본값
                    advance_rate = 1

                rates[wc.name] = advance_rate
                wc.advance_rate = advance_rate

        return rates

    def calculate_total_combinations(self, wildcards: List[WildcardInfo]) -> int:
        """
        전체 조합 경우의 수를 계산합니다.

        Args:
            wildcards: 와일드카드 리스트

        Returns:
            전체 조합 수
        """
        if not wildcards:
            return 0

        total = 1
        for wc in wildcards:
            total *= wc.item_count

        return total

    def analyze(self, prompt: str) -> Tuple[List[WildcardInfo], int, Dict[str, int]]:
        """
        프롬프트를 종합 분석합니다.

        Args:
            prompt: 분석할 프롬프트

        Returns:
            (와일드카드 리스트, 전체 조합 수, 전진 속도 딕셔너리)
        """
        # 1. 프롬프트 파싱
        wildcards = self.parse_prompt(prompt)

        if not wildcards:
            return [], 0, {}

        # 2. 의존성 체인 구성
        wildcards = self.build_dependency_chain(wildcards)

        # 3. 전진 속도 계산
        advance_rates = self.calculate_advance_rates(wildcards)

        # 4. 전체 조합 수 계산
        total_combinations = self.calculate_total_combinations(wildcards)

        return wildcards, total_combinations, advance_rates

    def get_warning_level(self, total_combinations: int) -> Tuple[str, str]:
        """
        조합 수에 따른 경고 레벨을 반환합니다.

        Args:
            total_combinations: 전체 조합 수

        Returns:
            (색상 코드, 경고 메시지)
        """
        if total_combinations == 0:
            return "#666666", "와일드카드 없음"
        elif total_combinations <= 100:
            return "#4CAF50", "🟢 적정 - 안전한 조합 수입니다"
        elif total_combinations <= 1000:
            return "#FF9800", "🟡 주의 - 조합이 다소 많습니다"
        elif total_combinations <= 10000:
            return "#FF5722", "🟠 경고 - 조합이 많습니다. 신중하게 사용하세요"
        else:
            return "#F44336", "🔴 위험 - 조합 수가 과도합니다! 와일드카드 구조를 단순화하세요!"

    def format_number(self, number: int) -> str:
        """
        숫자를 읽기 쉬운 형식으로 포맷합니다.

        Args:
            number: 포맷할 숫자

        Returns:
            포맷된 문자열 (예: "1,234")
        """
        return f"{number:,}"
