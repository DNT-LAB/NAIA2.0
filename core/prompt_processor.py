import pandas as pd
from typing import Dict, Any
from core.prompt_context import PromptContext
from core.wildcard_processor import WildcardProcessor # 이전 단계에서 생성
from core.context import AppContext

class PromptProcessor:
    PIPELINE_NAME = "PromptProcessor"

    def __init__(self, app_context: AppContext):
        self.app_context = app_context
        self.wildcard_processor = WildcardProcessor(app_context.main_window.wildcard_manager)

    def process(self) -> PromptContext:
        """
        [수정] AppContext에 저장된 current_prompt_context를 가져와 파이프라인을 실행합니다.
        이제 이 메소드는 인자를 받지 않습니다.
        """
        context = self.app_context.current_prompt_context
        if not context:
            raise ValueError("PromptProcessor.process: AppContext에 current_prompt_context가 설정되지 않았습니다.")

        # [수정] _step_1_initialize를 여기에서 호출하지 않고, 컨트롤러가 context 생성 시 초기화하도록 변경

        context = self._run_hooks('pre_processing', context)
        context = self._step_2_fit_resolution(context)
        context = self._run_hooks('post_processing', context)
        context = self._step_3_expand_wildcards(context)
        context = self._run_hooks('after_wildcard', context)
        context = self._run_hooks('final_hookpoint', context)
        context.final_prompt = self._step_final_format(context)
        
        return context
    
    def _run_hooks(self, hook_point: str, context: PromptContext) -> PromptContext:
        """등록된 훅들을 순서대로 실행합니다."""
        hooks_to_run = self.app_context.get_pipeline_hooks(self.PIPELINE_NAME, hook_point)
        
        for module_hook in hooks_to_run:
            try:
                # 각 훅은 context를 받아 수정 후 다시 반환
                context = module_hook.execute_pipeline_hook(context)
            except Exception as e:
                print(f"파이프라인 훅 실행 중 오류 ({module_hook.get_title()}): {e}")
                
        return context

    def _step_2_fit_resolution(self, context: PromptContext) -> PromptContext:
        """[신규] 해상도 자동 맞춤 로직을 파이프라인의 한 단계로 추가합니다."""
        settings = context.settings
        source_row = context.source_row
        
        if not settings.get('auto_fit_resolution', False) or settings.get('wildcard_standalone', False):
            return context

        if 'image_width' not in source_row or 'image_height' not in source_row:
            return context

        try:
            width = int(source_row['image_width'])
            height = int(source_row['image_height'])
            if width > 0 and height > 0:
                # 처리 결과를 context의 metadata에 저장합니다.
                context.metadata['detected_resolution'] = (width, height)
        except (ValueError, TypeError):
            pass
            
        return context

    def _step_3_expand_wildcards(self, context: PromptContext) -> PromptContext:
        """와일드카드를 실제 태그로 치환하는 단계"""
        context.prefix_tags = self.wildcard_processor.expand_tags(context.prefix_tags, context)
        context.postfix_tags = self.wildcard_processor.expand_tags(context.postfix_tags, context)
        return context

    def _step_final_format(self, context: PromptContext) -> str:
        """모든 태그를 조합하여 최종 문자열로 포맷팅하는 단계"""
        
        # [추가] Step 3에서 처리된 global_append_tags를 main_tags의 끝에 추가합니다.
        # 이 작업은 다른 모든 처리보다 먼저 수행되어야 합니다.
        if context.global_append_tags:
            context.main_tags.extend(context.global_append_tags)

        # 인물 태그 세트 정의
        person_sets = {
            "boys": {"1boy", "2boys", "3boys", "4boys", "5boys", "6+boys"},
            "girls": {"1girl", "2girls", "3girls", "4girls", "5girls", "6+girls"},
            "others": {"1other", "2others", "3others", "4others", "5others", "6+others"}
        }
        all_person_tags = person_sets["boys"] | person_sets["girls"] | person_sets["others"]
        
        person_tags_found = []
        new_main_tags = []

        # 1. main_tags에서 인물 관련 태그와 나머지 태그 분리
        for tag in context.main_tags:
            if tag in all_person_tags:
                person_tags_found.append(tag)
            else:
                new_main_tags.append(tag)

        # 2. 찾은 인물 태그들을 boys -> girls -> others 순서로 정렬
        sorted_person_tags = sorted(person_tags_found, key=lambda tag: 
                                    0 if tag in person_sets["boys"] else 
                                    1 if tag in person_sets["girls"] else 2)

        # 3. 태그 자동 변환 적용
        tag_conversion_map = {
            'v': 'peace sign', 'double v': 'double peace', '|_|': 'bar eyes',
            '\\||/': 'open \\m/', ':|': 'neutral face', ';|': 'neutral face',
            'eyepatch bikini': 'square bikini', 'tachi-e': 'character image'
        }

        converted_main_tags = [tag_conversion_map.get(tag, tag) for tag in new_main_tags]
        if converted_main_tags:
            converted_main_tags.insert(0, '#랜덤프롬프트')  # Ensure 'main tags' is always the first tag

        # 4. context 최종 업데이트
        context.main_tags = converted_main_tags

        # 4-1. 인원수 태그 배치 (ANIMA 모드 고려)
        # settings에 workflow_type 정보가 없으므로 main_window에서 직접 확인
        is_anima_mode = False
        if self.app_context.current_api_mode == 'COMFYUI':
            # AppContext를 통해 main_window의 라디오 버튼 상태 확인
            if hasattr(self.app_context, 'main_window'):
                main_window = self.app_context.main_window
                if hasattr(main_window, 'anima_radio') and main_window.anima_radio.isChecked():
                    is_anima_mode = True

        is_comfyui = self.app_context.current_api_mode == 'COMFYUI'

        if is_comfyui and is_anima_mode:
            # ANIMA 모드: @ 태그 앞에 삽입
            at_index = None
            for i, tag in enumerate(context.prefix_tags):
                if '@' in tag:
                    at_index = i
                    break

            if at_index is not None:
                # ANIMA 모드: 순서대로 삽입 (인원수 → 캐릭터 → copyright → @artist)
                anima_tags = []

                # 1. 인원수 태그
                anima_tags.extend(sorted_person_tags)

                # 2. 캐릭터 태그 (metadata에서, 괄호 이스케이프 + 가중치 적용)
                if 'anima_character' in context.metadata:
                    character_str = context.metadata['anima_character']
                    # 쉼표로 분리하여 리스트로 만들기
                    char_list = [c.strip() for c in character_str.split(',')]

                    if char_list:
                        # 괄호 이스케이프 처리
                        char_list = [c.replace("(", r"\(").replace(")", r"\)") for c in char_list]

                        # 첫 원소에 "(" 붙이기
                        char_list[0] = f"({char_list[0]}"

                        # 마지막 원소에 ":0.8)" 붙이기
                        char_list[-1] = f"{char_list[-1]}:0.7)"

                        # 다시 쉼표로 조인
                        character = ', '.join(char_list)
                        anima_tags.append(character)

                # 3. copyright 태그 (metadata에서, 괄호 이스케이프)
                if 'anima_copyright' in context.metadata:
                    copyright_tag = context.metadata['anima_copyright'].replace("(", r"\(").replace(")", r"\)")
                    anima_tags.append(copyright_tag)

                # 4. @artist 태그 (metadata에서, @ 붙이고 괄호 이스케이프)
                if 'anima_artist' in context.metadata:
                    artist = context.metadata['anima_artist'].replace("(", r"\(").replace(")", r"\)")
                    anima_tags.append(f"@{artist}")

                # @ 태그 앞에 삽입
                context.prefix_tags = (
                    context.prefix_tags[:at_index] +
                    anima_tags +
                    context.prefix_tags[at_index:]
                )
                print(f"🎨 ANIMA 모드: 태그 삽입 완료 (인덱스 {at_index}): {', '.join(anima_tags)}")
            else:
                # @ 태그가 없으면 맨 뒤에 삽입
                anima_tags = []

                # 1. 인원수 태그
                anima_tags.extend(sorted_person_tags)

                # 2. 캐릭터 태그 (괄호 이스케이프 + 가중치 적용)
                if 'anima_character' in context.metadata:
                    character_str = context.metadata['anima_character']
                    # 쉼표로 분리하여 리스트로 만들기
                    char_list = [c.strip() for c in character_str.split(',')]

                    if char_list:
                        # 괄호 이스케이프 처리
                        char_list = [c.replace("(", r"\(").replace(")", r"\)") for c in char_list]

                        # 첫 원소에 "(" 붙이기
                        char_list[0] = f"({char_list[0]}"

                        # 마지막 원소에 ":0.8)" 붙이기
                        char_list[-1] = f"{char_list[-1]}:0.75)"

                        # 다시 쉼표로 조인
                        character = ', '.join(char_list)
                        anima_tags.append(character)

                # 3. copyright 태그 (괄호 이스케이프)
                if 'anima_copyright' in context.metadata:
                    copyright_tag = context.metadata['anima_copyright'].replace("(", r"\(").replace(")", r"\)")
                    anima_tags.append(copyright_tag)

                # 4. @artist 태그 (@ 붙이고 괄호 이스케이프)
                if 'anima_artist' in context.metadata:
                    artist = context.metadata['anima_artist'].replace("(", r"\(").replace(")", r"\)")
                    anima_tags.append(f"@{artist}")

                context.prefix_tags = context.prefix_tags + anima_tags
                print(f"🎨 ANIMA 모드: @ 태그 없음, 태그를 맨 뒤에 삽입: {', '.join(anima_tags)}")

            # 🆕 ANIMA 모드: main_tags에 가중치 적용 (0.75)
            if context.main_tags:
                # "#"로 시작하지 않는 첫 번째 인덱스 찾기
                first_non_hash_idx = None
                for i, tag in enumerate(context.main_tags):
                    if not tag.startswith('#'):
                        first_non_hash_idx = i
                        break

                # 첫 번째 non-# 태그와 마지막 태그에 가중치 적용
                if first_non_hash_idx is not None:
                    # 첫 번째 non-# 태그에 "(" 붙이기
                    context.main_tags[first_non_hash_idx] = f"({context.main_tags[first_non_hash_idx]}"

                    # 마지막 태그에 ":0.75)" 붙이기
                    context.main_tags[-1] = f"{context.main_tags[-1]}:0.8)"

                    print(f"🎨 ANIMA 모드: main_tags에 가중치 0.75 적용 (첫 인덱스: {first_non_hash_idx}, 마지막: {len(context.main_tags)-1})")

        else:
            # 기존 방식: 맨 앞에 삽입
            context.prefix_tags = sorted_person_tags + context.prefix_tags

        # --- 이하 기존 로직 ---
        all_tags = context.get_all_tags()
        seen = set()
        final_tags = []

        for tag in all_tags:
            if '\n\n' in tag or tag not in seen:
                final_tags.append(tag)
                if '\n\n' not in tag:
                    seen.add(tag)
        
        formatted_prompt = []
        for tag in final_tags:
            if tag.startswith('#'):
                formatted_prompt.append(f"\n{tag.strip()}\n")
            elif tag == "\n\n":
                formatted_prompt.append("\n\n")
            else:
                formatted_tag = tag
                formatted_prompt.append(formatted_tag)

        final_string = ', '.join(formatted_prompt)

        return final_string