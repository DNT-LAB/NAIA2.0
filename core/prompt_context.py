# core/prompt_context.py

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
import pandas as pd

@dataclass
class PromptContext:
    """
    프롬프트 생성 파이프라인에서 사용될 데이터 구조체.
    생성 과정의 모든 단계에 걸쳐 데이터를 전달하고 상태를 관리합니다.
    """
    # --- 입력 데이터 ---
    source_row: pd.Series
    settings: Dict[str, Any]
    
    # --- 태그 리스트 ---
    prefix_tags: List[str] = field(default_factory=list)
    main_tags: List[str] = field(default_factory=list)
    postfix_tags: List[str] = field(default_factory=list)
    
    # --- [추가됨] 와일드카드 처리 과정에서 사용될 속성들 ---
    
    # '<wildcard>' 구문에서 뒤로 보내질 태그들을 임시 저장
    global_append_tags: List[str] = field(default_factory=list)
    
    # '<*wildcard>'의 순서를 기억하기 위한 카운터
    sequential_counters: Dict[str, int] = field(default_factory=dict)
    
    # 이번 생성에 사용된 모든 와일드카드와 그 결과를 기록 (히스토리)
    wildcard_history: Dict[str, List[str]] = field(default_factory=dict)
    
    # 순차/종속 와일드카드의 현재 상태(n/m)를 기록
    wildcard_state: Dict[str, Dict[str, int]] = field(default_factory=dict)

    # --- 처리 결과 ---
    removed_tags: List[str] = field(default_factory=list)
    final_prompt: Optional[str] = None
    
    # 처리 과정에서 발생하는 추가 정보를 담는 메타데이터
    metadata: Dict[str, Any] = field(default_factory=dict)

    def get_all_tags(self) -> List[str]:
        """현재 Prefix, Main, Postfix 태그를 모두 합친 리스트를 반환"""
        self.prefix_tags.append("\n\n")
        self.main_tags.append("\n\n")
        return self.prefix_tags + self.main_tags + self.postfix_tags