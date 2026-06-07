import random
import re
from typing import List
from .prompt_context import PromptContext
from .wildcard_manager import WildcardManager


def split_tags_smart(text: str) -> list[str]:
    """
    콤마로 태그를 분리하되, <...> 블록 내부의 콤마는 보존합니다.

    예시:
        "a, <angry,shy|b|c>, d" -> ["a", "<angry,shy|b|c>", "d"]
        "a, <lora:model:0.8>, b" -> ["a", "<lora:model:0.8>", "b"]
        "a, b, c" -> ["a", "b", "c"]
    """
    if not text:
        return []
    result, current, depth = [], [], 0
    for char in text:
        if char == '<':
            depth += 1
            current.append(char)
        elif char == '>':
            depth = max(0, depth - 1)
            current.append(char)
        elif char == ',' and depth == 0:
            tag = ''.join(current).strip()
            if tag:
                result.append(tag)
            current = []
        else:
            current.append(char)
    tag = ''.join(current).strip()
    if tag:
        result.append(tag)
    return result


class WildcardProcessor:
    def __init__(self, wildcard_manager: WildcardManager):
        self.wildcard_manager = wildcard_manager

    def _find_wildcard_key(self, name: str) -> str | None:
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

    def expand_tags(self, tag_list: List[str], context: PromptContext,
                    wildcard_sink: "list | None" = None) -> List[str]:
        """
        태그 리스트를 받아 리스트 내의 모든 와일드카드를 확장합니다.
        이것이 다른 모듈에서 호출할 기본 진입점(entry-point)이 됩니다.

        ``wildcard_sink``가 주어지면 *와일드카드(__name__/<name>/$instant)에서 나온* 출력
        태그만 따로 수집한다(고정 태그는 제외). Ollama Boost가 prefix/postfix의 **와일드카드
        출력만** 캡처하는 용도(설정 [기능3]) — 고정 아티스트/퀄리티 태그 오염 방지.
        """
        expanded_list = []
        for tag in tag_list:
            is_wildcard = ('__' in tag) or ('<' in tag) or tag.strip().startswith('$')
            produced: List[str] = []
            # $ 로 시작하는 인스턴트 와일드카드 처리
            if tag.startswith('$'):
                instant_key = tag[1:].strip()  # $ 제거
                # ":" 포함 여부 확인하여 필터링 적용
                if ":" in instant_key:
                    parts = instant_key.split(":", 1)
                    group_name = parts[0]
                    filter_text = parts[1].lower() if len(parts) > 1 else ""
                    if group_name in self.wildcard_manager.instant_wildcard_tree:
                        group_dict = self.wildcard_manager.instant_wildcard_tree[group_name]
                        if not group_dict:
                            produced = [tag]  # 그룹 비어있으면 원본 유지
                        else:
                            src = group_dict
                            if filter_text:
                                filtered_dict = {k: v for k, v in group_dict.items() if filter_text in k.lower()}
                                if filtered_dict:
                                    src = filtered_dict
                            random_key = random.choice(list(src.keys()))
                            random_value = src[random_key]
                            produced = [t.strip() for t in random_value.split(',') if t.strip()]
                    else:
                        produced = [tag]  # 그룹 못 찾으면 원본 유지
                # ":" 없이 단순 그룹명인 경우
                elif instant_key in self.wildcard_manager.instant_wildcard_tree:
                    group_dict = self.wildcard_manager.instant_wildcard_tree[instant_key]
                    if group_dict:
                        random_key = random.choice(list(group_dict.keys()))
                        random_value = group_dict[random_key]
                        produced = [t.strip() for t in random_value.split(',') if t.strip()]
                    else:
                        produced = [tag]
                # tree에 없으면 기존 instant_wildcard_dict에서 검색
                elif instant_key in self.wildcard_manager.instant_wildcard_dict:
                    instant_value = self.wildcard_manager.instant_wildcard_dict[instant_key]
                    produced = [t.strip() for t in instant_value.split(',') if t.strip()]
                else:
                    produced = [tag]  # 인스턴트 와일드카드 못 찾으면 원본 유지
            else:
                # 일반 와일드카드 처리(고정 태그는 그대로 통과)
                produced = self._expand_recursive(tag, context)
            expanded_list.extend(produced)
            # 실제로 전개된 경우만 sink에 수집한다(Codex). LoRA(<lora:..>)·미해결 토큰
            # (<missing>/__missing__/$missing)은 _expand_recursive/인스턴트 분기가 원본을 그대로
            # 반환(produced == [tag])하므로 "와일드카드 출력"이 아니다 → 제외.
            # 주의: <wc>(구식 각괄호)의 2번째+ 태그는 global_append_tags로 빠져 in-place sink엔
            # 안 잡힌다. 사용자 권장 문법은 __name__(in-place 콤마결합)이라 실사용엔 무영향.
            if wildcard_sink is not None and is_wildcard and produced != [tag]:
                wildcard_sink.extend(produced)
        return expanded_list

    def _expand_recursive(self, tag: str, context: PromptContext, depth=0) -> List[str]:
        """하나의 태그를 재귀적으로 확장합니다."""
        if depth > 10: return [tag]
        
        # $ 로 시작하는 인스턴트 와일드카드 처리 (재귀 호출에서도)
        if tag.startswith('$'):
            instant_key = tag[1:].strip()
            
            # ":" 포함 여부 확인하여 필터링 적용
            if ":" in instant_key:
                parts = instant_key.split(":", 1)
                group_name = parts[0]
                filter_text = parts[1].lower() if len(parts) > 1 else ""
                
                # tree에서 그룹 찾기
                if group_name in self.wildcard_manager.instant_wildcard_tree:
                    group_dict = self.wildcard_manager.instant_wildcard_tree[group_name]
                    
                    # filter_text를 포함하는 key들만 추출
                    if filter_text and group_dict:
                        filtered_dict = {k: v for k, v in group_dict.items() if filter_text in k.lower()}
                        
                        if filtered_dict:
                            # 필터링된 결과에서 무작위 선택
                            random_key = random.choice(list(filtered_dict.keys()))
                            random_value = filtered_dict[random_key]
                        else:
                            # 필터링 결과가 없으면 전체에서 무작위 선택
                            random_key = random.choice(list(group_dict.keys()))
                            random_value = group_dict[random_key]
                    elif group_dict:
                        # 필터 텍스트가 없으면 전체에서 무작위 선택
                        random_key = random.choice(list(group_dict.keys()))
                        random_value = group_dict[random_key]
                    else:
                        # 그룹이 비어있으면 원본 유지
                        return [tag]
                        
                    # 값을 콤마로 분리하여 개별 태그로 추가
                    instant_tags = [t.strip() for t in random_value.split(',') if t.strip()]
                    return instant_tags
                return [tag]
            
            # ":" 없이 단순 그룹명인 경우
            elif instant_key in self.wildcard_manager.instant_wildcard_tree:
                # tree에서 해당 그룹의 딕셔너리 가져오기
                group_dict = self.wildcard_manager.instant_wildcard_tree[instant_key]
                if group_dict:
                    # 무작위로 key-value 쌍 선택
                    random_key = random.choice(list(group_dict.keys()))
                    random_value = group_dict[random_key]
                    # 값을 콤마로 분리하여 개별 태그로 추가
                    instant_tags = [t.strip() for t in random_value.split(',') if t.strip()]
                    return instant_tags
                return [tag]
            # tree에 없으면 기존 instant_wildcard_dict에서 검색
            elif instant_key in self.wildcard_manager.instant_wildcard_dict:
                instant_value = self.wildcard_manager.instant_wildcard_dict[instant_key]
                instant_tags = [t.strip() for t in instant_value.split(',') if t.strip()]
                return instant_tags
            return [tag]

        if tag.startswith('<') and tag.endswith('>'):
            wildcard_name = tag[1:-1]

            # Lora/모델 참조 태그 보호 (WEBUI/ComfyUI 모드)
            _SKIP_PREFIXES = ('lora:', 'hypernet:', 'lyco:', 'embedding:')
            if any(wildcard_name.lower().startswith(p) for p in _SKIP_PREFIXES):
                return [tag]

            # 인라인 와일드카드 처리
            if '|' in wildcard_name:
                options = wildcard_name.split('|')
                chosen_option = random.choice(options).strip()
                # 선택된 옵션을 콤마로 분리하여 각 서브 태그를 개별 확장 (__name__ 등 지원)
                sub_tags = [t.strip() for t in chosen_option.split(',') if t.strip()]
                result = []
                for sub_tag in sub_tags:
                    result.extend(self._expand_recursive(sub_tag, context, depth + 1))
                return result

            # 파일 기반 와일드카드 처리 - <태그명> 형태는 기존 로직 유지
            line = self._get_wildcard_line(wildcard_name, context)
            if line is None: return [tag]
            
            resolved_tags = self._expand_recursive(line, context, depth + 1)
            
            final_tags_in_place = []
            for resolved_tag in resolved_tags:
                sub_tags = [t.strip() for t in resolved_tag.split(',')]
                tags_to_keep = [t[1:] for t in sub_tags if t.startswith('*')]
                tags_to_append = [t for t in sub_tags if not t.startswith('*')]

                if tags_to_keep:
                    final_tags_in_place.extend(tags_to_keep)
                    context.global_append_tags.extend(tags_to_append)
                elif tags_to_append:
                    final_tags_in_place.append(tags_to_append[0])
                    context.global_append_tags.extend(tags_to_append[1:])
            
            return final_tags_in_place if final_tags_in_place else []
        
        # 복합 와일드카드 처리 (__...__)
        if '__' in tag:
            parts = re.split(r'(__.*?__)', tag)
            result_parts = []
            
            for part in parts:
                if not part:
                    continue
                    
                if part.startswith('__') and part.endswith('__'):
                    # __태그명__ 형태: global_append_tags 없이 현재 위치에 일괄 나열
                    wildcard_name = part[2:-2]
                    line = self._get_wildcard_line(wildcard_name, context)
                    if line is not None:
                        expanded_parts = self._expand_recursive(line, context, depth + 1)
                        # 모든 결과를 현재 위치에 콤마로 연결
                        all_tags = []
                        for expanded_part in expanded_parts:
                            sub_tags = [t.strip() for t in expanded_part.split(',')]
                            all_tags.extend(sub_tags)
                        result_parts.append(', '.join(all_tags))
                    else:
                        result_parts.append(part)  # 확장 실패시 원본 유지
                else:
                    result_parts.append(part)
            
            return [''.join(result_parts)]

        return [tag]

    def _get_wildcard_line(self, wildcard_name: str, context: PromptContext) -> str | None:
        """WildcardManager에서 와일드카드 내용을 가져옵니다. 순차/종속 모드를 처리합니다."""
        is_sequential = wildcard_name.startswith('*')
        is_observer = wildcard_name.startswith('$')

        if is_sequential:
            wildcard_name = wildcard_name[1:]
        elif is_observer:
            try:
                master_name, slave_name = wildcard_name[1:].split(':', 1)
                wildcard_name = slave_name
            except ValueError:
                print(f"경고: 잘못된 종속 와일드카드 구문입니다: {wildcard_name}")
                return None

        # Fuzzy Matching으로 실제 키 찾기
        actual_wildcard_key = self._find_wildcard_key(wildcard_name)
        if not actual_wildcard_key:
            print(f"경고: 와일드카드 '{wildcard_name}'을 찾을 수 없습니다.")
            return None

        # entries: [(weight, text), ...] 형식
        entries = self.wildcard_manager.wildcard_dict_tree.get(actual_wildcard_key)
        if not entries:
            print(f"경고: 와일드카드 '{actual_wildcard_key}'의 내용이 비어있습니다.")
            return None

        chosen_line = ""
        total_entries = len(entries)

        # 🔒 오버라이드 확인 (모든 모드 공통, 카운터 동결)
        # list 형태는 큐처럼 앞에서 한 개씩 소비하고, 소진 시 일반 분기로 폴백한다.
        # str 형태는 기존 동작과 같이 단일 고정값을 반환한다.
        ctx_ref = getattr(self.wildcard_manager, '_app_context_ref', None)
        ctx = ctx_ref() if ctx_ref else None
        override_val = ctx.wildcard_override.get(actual_wildcard_key) if ctx else None
        if isinstance(override_val, list):
            override_val = override_val.pop(0) if override_val else None

        if override_val is not None:
            chosen_line = override_val

        elif is_sequential:
            # sequential_counters는 실제 키로 저장
            counter = context.sequential_counters.get(actual_wildcard_key, 0)
            chosen_line = entries[counter % total_entries][1]  # text 부분
            context.sequential_counters[actual_wildcard_key] = counter + 1
            # [상태 관찰] 순차 와일드카드 상태 기록 (실제 키 사용)
            context.wildcard_state[actual_wildcard_key] = {'current': counter % total_entries + 1, 'total': total_entries}

        elif is_observer:
            # 🔧 [수정] Master/Slave 의존성 로직 개선 + Fuzzy Matching
            # Master도 Fuzzy Matching으로 찾기
            actual_master_key = self._find_wildcard_key(master_name)

            if not actual_master_key:
                print(f"경고: Master 와일드카드 '{master_name}'을 찾을 수 없습니다.")
                # 기본값으로 첫 번째 항목 반환
                chosen_line = entries[0][1]
                slave_index = 0
                completed_master_cycles = 0
            else:
                master_counter = context.sequential_counters.get(actual_master_key, 0)

                # Master 와일드카드의 길이를 가져와서 사이클 계산
                master_entries = self.wildcard_manager.wildcard_dict_tree.get(actual_master_key, [])
                master_total = len(master_entries) if master_entries else 1

                # Master가 완전한 사이클을 몇 번 완료했는지 계산
                # master_counter는 같은 프롬프트에서 이미 +1 된 post-increment 값이므로 -1 보정
                completed_master_cycles = (master_counter - 1) // master_total if master_counter > 0 else 0

                # Slave는 master의 완전한 사이클 완료 횟수에 따라 진행
                slave_index = completed_master_cycles % total_entries
                chosen_line = entries[slave_index][1]

            # [상태 관찰] 종속 와일드카드 상태 기록 (실제 키 사용)
            context.wildcard_state[actual_wildcard_key] = {
                'current': slave_index + 1,
                'total': total_entries,
                'master_cycles': completed_master_cycles,
                'master_name': actual_master_key if actual_master_key else 'unknown'  # 실제 Master 키 기록
            }

            # 🔧 [중요] 종속 와일드카드의 counter는 "전진 횟수"를 저장
            # 전진 횟수 = Master가 완료한 사이클 수
            # 다음 종속 와일드카드가 이 와일드카드를 Master로 참조할 때,
            # completed_slave_cycles = counter // total_lines로 계산
            context.sequential_counters[actual_wildcard_key] = completed_master_cycles

        else: # 일반 무작위 모드 — 가중치 기반 선택
            weights = [w for w, _ in entries]
            chosen_line = random.choices([t for _, t in entries], weights=weights, k=1)[0]

        context.wildcard_history.setdefault(actual_wildcard_key, []).append(chosen_line)
        return chosen_line