import io
from contextlib import redirect_stdout

class SafeExecutor:
    """
    제한된 환경에서 안전하게 파이썬 코드를 실행하는 샌드박스 클래스.
    """
    def __init__(self, allowed_vars: dict):
        # 실행에 사용할 변수들은 복사하여 원본을 보호
        self.allowed_vars = {k: v.copy() for k, v in allowed_vars.items()}
        
        safe_builtins = {
            'print': self.captured_print, 'len': len, 'str': str, 'int': int, 
            'float': float, 'list': list, 'dict': dict, 'set': set, 
            'tuple': tuple, 'range': range, 'abs': abs, 'min': min, 
            'max': max, 'sum': sum, 'sorted': sorted, 'isinstance': isinstance,
            'True': True, 'False': False, 'None': None,
        }

        # 실행 시 사용할 전역 환경 설정
        self.execution_globals = {"__builtins__": safe_builtins}
        self.output_buffer = io.StringIO()

    def captured_print(self, *args, **kwargs):
        print(*args, file=self.output_buffer, **kwargs)

    def execute(self, code: str):
        """사용자 코드를 안전하게 실행하고 결과와 변경된 변수를 반환합니다."""
        
        forbidden_keywords = ['import', 'from', 'eval', 'exec', 'open', 'getattr', 'setattr', 'delattr', '__']
        if any(keyword in code for keyword in forbidden_keywords):
            return "오류: 허용되지 않는 키워드가 포함되어 있습니다.", None, False

        self.output_buffer.seek(0)
        self.output_buffer.truncate(0)

        try:
            # 실행 전 컨텍스트의 모든 태그를 집합(set)으로 만듦
            initial_all_tags = set(self.allowed_vars.get('prefix_tags', [])) | \
                               set(self.allowed_vars.get('main_tags', [])) | \
                               set(self.allowed_vars.get('postfix_tags', []))

            # 실행을 위한 변수들 준비
            execution_globals = {**self.execution_globals, **self.allowed_vars}
            execution_locals = {}
            
            # 코드 실행
            exec(code, execution_globals, execution_locals)

            # 실행 후 변경된 변수들의 최종 상태를 가져옴
            updated_vars = {}
            for key in self.allowed_vars.keys():
                updated_vars[key] = execution_locals.get(key, execution_globals.get(key))

            # 실행 후 컨텍스트의 모든 태그를 집합(set)으로 만듦
            final_all_tags = set(updated_vars.get('prefix_tags', [])) | \
                             set(updated_vars.get('main_tags', [])) | \
                             set(updated_vars.get('postfix_tags', []))

            # '진짜로 제거된' 태그 계산 (초기 상태에는 있었지만, 최종 상태에는 없는 태그)
            truly_removed_tags = initial_all_tags - final_all_tags

            # 최종 removed_tags 목록 업데이트
            # (기존 removed_tags 목록 + 진짜로 제거된 태그 목록)
            final_removed_set = set(updated_vars.get('removed_tags', [])).union(truly_removed_tags)
            updated_vars['removed_tags'] = sorted(list(final_removed_set))

            output = self.output_buffer.getvalue()
            return output, updated_vars, True

        except Exception as e:
            return f"실행 중 오류 발생: {e}", None, False