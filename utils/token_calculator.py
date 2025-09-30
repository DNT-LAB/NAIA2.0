"""
Token calculation utility using tiktoken with CLIP tokenizer approximation.
Provides functions to count tokens in text for Stable Diffusion prompt estimation.
"""

import tiktoken
from typing import Optional, Dict, Any
import re


class TokenCalculator:
    """
    Handles token counting for prompts using tiktoken GPT-2 encoding 
    with correction factors to approximate CLIP tokenizer behavior.
    """
    
    # CLIP 토크나이저 근사를 위한 모드별 보정 계수
    # GPT-2는 대체로 CLIP보다 약간 적게 토큰화하는 경향이 있음
    CLIP_CORRECTION_FACTORS = {
        "NAI": 1.12,      # NovelAI 모드 (가중치 제거 후)
        "WEBUI": 0.99,    # WebUI 모드 (괄호 가중치 포함)
        "COMFYUI": 0.99,  # ComfyUI 모드 (괄호 가중치 포함)
    }
    
    # 특수 패턴별 추가 보정 계수
    PATTERN_CORRECTIONS = {
        'parentheses': 0.02,   # 괄호가 많을 때 추가 2%
        'underscores': 0.01,   # 언더스코어가 많을 때 추가 1%
        'numbers': 0.02,        # 숫자가 많을 때 추가 2%
        'punctuation': 0.01,   # 구두점이 많을 때 추가 1%
        'lora_tags': 0.03,      # <lora:...> 태그 추가 3%
    }
    
    def __init__(self):
        """Initialize the token calculator with GPT-2 encoding."""
        try:
            self.encoding = tiktoken.get_encoding("gpt2")
            self.available = True
        except Exception as e:
            print(f"Warning: tiktoken initialization failed: {e}")
            self.encoding = None
            self.available = False
    
    def _preprocess_common(self, text: str) -> str:
        """
        Common preprocessing for all modes: clean tags and remove comments.
        
        Steps:
        1. Split by comma and strip each element
        2. Remove empty elements and comments (starting with #)
        3. Rejoin with ", "
        
        Args:
            text: The original prompt text
            
        Returns:
            Cleaned text with empty/comment tags removed
        """
        if not text:
            return text
        
        # Step 1: Split by comma and process each tag
        tags = text.split(',')
        
        # Step 2: Strip and filter tags
        cleaned_tags = []
        for tag in tags:
            stripped_tag = tag.strip()
            # Skip empty tags and comments
            if stripped_tag and not stripped_tag.startswith('#'):
                cleaned_tags.append(stripped_tag)
        
        # Step 3: Rejoin with consistent spacing
        return ', '.join(cleaned_tags)
    
    def _preprocess_nai_weights(self, text: str) -> str:
        """
        Remove Novel AI weight syntax before token counting.
        
        Removes patterns like:
        - "1.55::artist:chihiro (khorosho), artist:collagen ::"
        - "0.6::artist:moromoro 0p0, artist:usashiro mani ::"
        - "-0.85::flat color, chromatic aberration ::"
        
        Args:
            text: The original prompt text
            
        Returns:
            Text with NAI weight syntax removed
        """
        if not text or '::' not in text:
            return text
        
        # Step 1: Remove weight prefix patterns like "1.55::" or "-0.85::"
        # Matches: optional minus, digits, optional decimal point and more digits, followed by ::
        weight_prefix_pattern = r'-?\d+(?:\.\d+)?::'
        text = re.sub(weight_prefix_pattern, '', text)
        
        # Step 2: Remove remaining "::" markers
        text = text.replace('::', '')
        
        # Step 3: Clean up extra spaces and commas
        # Remove multiple consecutive spaces
        text = re.sub(r'\s+', ' ', text)
        # Remove spaces before commas
        text = re.sub(r'\s+,', ',', text)
        # Remove multiple consecutive commas
        text = re.sub(r',+', ',', text)
        # Remove leading/trailing spaces and commas
        text = text.strip(' ,')
        
        return text
    
    def _preprocess_webui_weights(self, text: str) -> str:
        """
        Process WebUI/ComfyUI weight syntax for token counting.
        
        New rules:
        - Only escaped parentheses \( \) count as tokens (1 token for pair)
        - Weight syntax (text:weight) or (text) removes weights but no tokens for parentheses
        - Regular parentheses contribute 0 tokens
        
        Args:
            text: The original prompt text
            
        Returns:
            Text with weight syntax processed and escaped parentheses marked
        """
        if not text:
            return text
        
        # Step 1: Mark escaped parentheses as tokens (each pair = 1 token)
        # Replace \( and \) with token markers
        text = text.replace('\\(', '__ESCAPED_PAREN_TOKEN__')
        text = text.replace('\\)', '__ESCAPED_PAREN_TOKEN__')
        
        # Step 2: Process weight syntax - remove weights but keep content
        if '(' in text:
            # Pattern for weight syntax: (content:weight) or (content)
            weight_pattern = r'\(([^()]+?)(?::[+-]?\d*\.?\d+)?\)'
            
            def replace_weight(match):
                content = match.group(1).strip()  # Extract content without weight
                return content  # No token markers - parentheses count as 0 tokens
            
            # Remove weight syntax parentheses and weights
            text = re.sub(weight_pattern, replace_weight, text)
        
        # Step 3: Clean up extra spaces
        text = re.sub(r'\s+', ' ', text)
        text = re.sub(r'\s+,', ',', text)
        text = re.sub(r',+', ',', text)
        text = text.strip(' ,')
        
        return text
    
    def _count_webui_tokens(self, processed_text: str) -> int:
        """
        Count additional tokens for escaped parentheses only.
        
        Args:
            processed_text: Text with __ESCAPED_PAREN_TOKEN__ markers
            
        Returns:
            Number of additional tokens (each escaped pair = 1 token)
        """
        escaped_tokens = processed_text.count('__ESCAPED_PAREN_TOKEN__')
        # Each pair of escaped parentheses = 1 token
        # Since we replaced both \( and \) with same marker, divide by 2
        return escaped_tokens // 2
    
    def _calculate_pattern_correction(self, text: str) -> float:
        """
        Calculate additional correction factor based on text patterns.
        
        Args:
            text: The text to analyze
            
        Returns:
            Additional correction factor (0.0 to ~0.1)
        """
        if not text:
            return 0.0
        
        correction = 0.0
        text_len = len(text)
        
        # 괄호 비율 체크
        parentheses_count = text.count('(') + text.count(')') + text.count('[') + text.count(']')
        if parentheses_count / text_len > 0.02:  # 2% 이상
            correction += self.PATTERN_CORRECTIONS['parentheses']
        
        # 언더스코어 비율 체크
        underscore_count = text.count('_')
        if underscore_count / text_len > 0.01:  # 1% 이상
            correction += self.PATTERN_CORRECTIONS['underscores']
        
        # 숫자 비율 체크
        number_count = sum(1 for c in text if c.isdigit())
        if number_count / text_len > 0.05:  # 5% 이상
            correction += self.PATTERN_CORRECTIONS['numbers']
        
        # 구두점 비율 체크
        punctuation_count = text.count(',') + text.count('.') + text.count(':') + text.count(';')
        if punctuation_count / text_len > 0.03:  # 3% 이상
            correction += self.PATTERN_CORRECTIONS['punctuation']
        
        # LoRA 태그 체크
        lora_matches = re.findall(r'<lora:[^>]+>', text)
        if lora_matches:
            correction += self.PATTERN_CORRECTIONS['lora_tags']
        
        return correction
    
    def count_tokens(self, text: str, use_clip_approximation: bool = True, current_mode: str = "NAI") -> int:
        """
        Count the number of tokens in the given text with CLIP approximation.
        
        Args:
            text: The text to tokenize
            use_clip_approximation: Whether to apply CLIP tokenizer approximation
            current_mode: Current API mode ('NAI', 'WEBUI', 'COMFYUI') - NAI weight removal only in NAI mode
            
        Returns:
            Number of tokens in the text, or 0 if encoding is not available
        """
        if not self.available or not text:
            return 0
        
        try:
            # Step 1: Common preprocessing - clean tags and remove comments
            preprocessed_text = self._preprocess_common(text)
            additional_tokens = 0
            
            # Step 2: Mode-specific weight processing
            if current_mode == "NAI":
                preprocessed_text = self._preprocess_nai_weights(preprocessed_text)
            elif current_mode in ["WEBUI", "COMFYUI"]:
                preprocessed_text = self._preprocess_webui_weights(preprocessed_text)
                # Count additional tokens for escaped parentheses only
                additional_tokens = self._count_webui_tokens(preprocessed_text)
                # Remove token placeholders for GPT-2 encoding
                preprocessed_text = preprocessed_text.replace('__ESCAPED_PAREN_TOKEN__', '')
                preprocessed_text = re.sub(r'\s+', ' ', preprocessed_text).strip()
            
            # Step 2.5: Count artist: tokens (applies to all modes)
            artist_count = preprocessed_text.count('artist:')
            additional_tokens += artist_count * 2  # Each "artist:" adds 2 tokens
            
            # Step 3: GPT-2 기반 토큰 카운트
            tokens = self.encoding.encode(preprocessed_text)
            base_count = len(tokens) + additional_tokens  # Add escaped parentheses + artist tokens
            
            if not use_clip_approximation:
                return base_count
            
            # CLIP 토크나이저 근사를 위한 모드별 보정 (전처리된 텍스트 기준)
            base_correction = self.CLIP_CORRECTION_FACTORS.get(current_mode, 1.08)  # 기본값은 WEBUI/COMFYUI와 동일
            pattern_correction = self._calculate_pattern_correction(preprocessed_text)
            total_correction = base_correction + pattern_correction
            
            # 보정된 토큰 수 계산 (반올림)
            corrected_count = round(base_count * total_correction)
            
            # 디버그 정보 (가중치 제거/처리 확인용)
            # if text != preprocessed_text or additional_tokens > 0:
            #     mode_name = current_mode
            #     artist_tokens = artist_count * 2
            #     other_additional = additional_tokens - artist_tokens
                
            #     print(f"{mode_name} Weight Processing:")
            #     print(f"  Original: {text[:100]}{'...' if len(text) > 100 else ''}")
            #     print(f"  Processed: {preprocessed_text[:100]}{'...' if len(preprocessed_text) > 100 else ''}")
            #     print(f"  Base Tokens: {len(tokens)}, Artist: {artist_tokens} ({artist_count} instances), Other: {other_additional}, Total: {base_count}, Corrected: {corrected_count}")
            
            return corrected_count
            
        except Exception as e:
            print(f"Error counting tokens: {e}")
            return 0
    
    def count_prompt_tokens(self, main_prompt: str, character_prompt: Optional[str] = None, current_mode: str = "NAI") -> Dict[str, int]:
        """
        Count tokens for main prompt and optionally character prompt.
        
        Args:
            main_prompt: The main prompt text
            character_prompt: Optional character prompt text
            current_mode: Current API mode ('NAI', 'WEBUI', 'COMFYUI')
            
        Returns:
            Dictionary with token counts:
            - 'main': Main prompt token count
            - 'character': Character prompt token count (0 if not provided)
            - 'total': Total token count
        """
        main_tokens = self.count_tokens(main_prompt, current_mode=current_mode)
        character_tokens = self.count_tokens(character_prompt, current_mode=current_mode) if character_prompt else 0
        
        return {
            'main': main_tokens,
            'character': character_tokens,
            'total': main_tokens + character_tokens
        }
    
    def format_token_label(self, token_counts: Dict[str, int], mode: str = "NAI") -> str:
        """
        Format token counts for display in the UI label.
        
        Args:
            token_counts: Dictionary with 'main', 'character', and 'total' counts
            mode: Current API mode ('NAI', 'WEBUI', 'COMFYUI')
            
        Returns:
            Formatted string for the token label
        """
        if mode == "NAI":
            return f"Estimated Tokens : {token_counts['total']} (Main {token_counts['main']} + Character {token_counts['character']})"
        else:
            return f"Estimated Tokens : {token_counts['main']}"


# Global instance for easy access
_token_calculator = None

def get_token_calculator() -> TokenCalculator:
    """
    Get or create the global TokenCalculator instance.
    
    Returns:
        The global TokenCalculator instance
    """
    global _token_calculator
    if _token_calculator is None:
        _token_calculator = TokenCalculator()
    return _token_calculator


def count_tokens(text: str, current_mode: str = "NAI") -> int:
    """
    Convenience function to count tokens in text.
    
    Args:
        text: The text to tokenize
        current_mode: Current API mode ('NAI', 'WEBUI', 'COMFYUI')
        
    Returns:
        Number of tokens in the text
    """
    calculator = get_token_calculator()
    return calculator.count_tokens(text, current_mode=current_mode)


def count_prompt_tokens(main_prompt: str, character_prompt: Optional[str] = None, current_mode: str = "NAI") -> Dict[str, int]:
    """
    Convenience function to count tokens for prompts.
    
    Args:
        main_prompt: The main prompt text
        character_prompt: Optional character prompt text
        current_mode: Current API mode ('NAI', 'WEBUI', 'COMFYUI')
        
    Returns:
        Dictionary with token counts
    """
    calculator = get_token_calculator()
    return calculator.count_prompt_tokens(main_prompt, character_prompt, current_mode)


def format_token_label(token_counts: Dict[str, int], mode: str = "NAI") -> str:
    """
    Convenience function to format token counts for display.
    
    Args:
        token_counts: Dictionary with 'main', 'character', and 'total' counts
        mode: Current API mode
        
    Returns:
        Formatted string for the token label
    """
    calculator = get_token_calculator()
    return calculator.format_token_label(token_counts, mode)