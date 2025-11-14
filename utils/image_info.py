# utils/image_info.py
"""이미지 메타데이터 추출 및 처리 유틸리티"""

import json
import gzip
import re
import io
from typing import Dict, Any, Optional, Union
from PIL import Image
from pathlib import Path
try:
    import piexif
    import piexif.helper
    PIEXIF_AVAILABLE = True
except ImportError:
    PIEXIF_AVAILABLE = False
    print("Warning: piexif not available, EXIF metadata extraction limited")


class ImageMetadataExtractor:
    """이미지에서 AI 생성 메타데이터를 추출하는 클래스"""
    
    @staticmethod
    def has_metadata(image_path: Union[str, Path, Image.Image]) -> bool:
        """이미지에 메타데이터가 있는지 확인"""
        try:
            if isinstance(image_path, (str, Path)):
                img = Image.open(image_path)
            else:
                img = image_path

            # 여러 메타데이터 소스 확인
            if 'Comment' in img.info:
                print("✅ has_metadata: Comment 필드 발견")
                return True
            if 'parameters' in img.info:
                print("✅ has_metadata: parameters 필드 발견")
                return True
            if hasattr(img, 'getexif') and img.getexif():
                print("✅ has_metadata: EXIF 데이터 발견")
                return True

            # Stealth PNG 확인 (RGBA만)
            if img.mode == 'RGBA':
                print(f"🔍 has_metadata: RGBA 이미지 감지, stealth PNG 확인 시작...")
                stealth_data = ImageMetadataExtractor._read_stealth_pnginfo(img)
                if stealth_data:
                    print(f"✅ has_metadata: Stealth PNG 데이터 발견 (길이: {len(stealth_data)})")
                    return True
                else:
                    print("❌ has_metadata: Stealth PNG 데이터 없음")
            else:
                print(f"ℹ️ has_metadata: 이미지 모드 {img.mode}, stealth PNG 확인 스킵")

            print("❌ has_metadata: 메타데이터 없음")
            return False

        except Exception as e:
            print(f"❌ 메타데이터 확인 중 오류: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    @staticmethod
    def extract_metadata(image_path: Union[str, Path, Image.Image]) -> Optional[Dict[str, Any]]:
        """이미지에서 메타데이터 추출"""
        try:
            if isinstance(image_path, (str, Path)):
                img = Image.open(image_path)
            else:
                img = image_path

            # NovelAI 메타데이터도 포함
            result = {}

            # img.info의 모든 필드를 먼저 수집
            if hasattr(img, 'info') and img.info:
                result.update(img.info)
            
            # 1. parameters 필드 확인 (Stable Diffusion WebUI) - 우선순위 높음
            if 'parameters' in img.info:
                parsed = ImageMetadataExtractor._parse_parameters(img.info['parameters'])
                if parsed:
                    result.update(parsed)
            
            # 2. EXIF 데이터 확인 (WebUI JPEG/PNG)
            if 'exif' in img.info or hasattr(img, 'getexif'):
                exif_data = ImageMetadataExtractor._extract_from_exif(img)
                if exif_data:
                    result.update(exif_data)
            
            # 3. Comment 필드 확인 (NovelAI 등)
            if 'Comment' in img.info:
                parsed = ImageMetadataExtractor._parse_comment(img.info['Comment'])
                if parsed:
                    result.update(parsed)
            
            # 4. GIF comment field
            if 'comment' in img.info:
                comment = img.info['comment']
                if isinstance(comment, bytes):
                    comment = comment.decode('utf8', errors="ignore")
                if comment:
                    parsed = ImageMetadataExtractor._parse_parameters(comment)
                    if parsed:
                        result.update(parsed)
            
            # 5. Stealth PNG 확인
            if img.mode == 'RGBA':
                stealth_data = ImageMetadataExtractor._read_stealth_pnginfo(img)
                if stealth_data:
                    parsed = ImageMetadataExtractor._parse_stealth_data(stealth_data)
                    if parsed:
                        result.update(parsed)

            return result if result else None
            
        except Exception as e:
            print(f"메타데이터 추출 중 오류: {e}")
            return None
    
    @staticmethod
    def _parse_comment(comment: str) -> Optional[Dict[str, Any]]:
        """Comment 필드 파싱"""
        try:
            # JSON 형식 시도
            if comment.strip().startswith('{'):
                return json.loads(comment)

            # NAI 형식 파싱
            return ImageMetadataExtractor._parse_nai_format(comment)

        except Exception:
            # 일반 텍스트로 반환
            return {'type': 'text', 'content': comment}
    
    @staticmethod
    def _parse_parameters(params: str) -> Dict[str, Any]:
        """Stable Diffusion WebUI parameters 파싱"""
        result = {
            'type': 'webui',
            'prompt': '',
            'negative': '',
            'parameters': {}
        }
        
        # Negative prompt 분리
        if 'Negative prompt:' in params:
            parts = params.split('Negative prompt:')
            result['prompt'] = parts[0].strip()
            
            # 나머지 파라미터 파싱
            if '\n' in parts[1]:
                neg_parts = parts[1].split('\n', 1)
                result['negative'] = neg_parts[0].strip()
                if len(neg_parts) > 1:
                    result['parameters'] = ImageMetadataExtractor._parse_webui_params(neg_parts[1])
            else:
                result['negative'] = parts[1].strip()
        else:
            # Negative prompt가 없는 경우
            if '\n' in params:
                parts = params.split('\n', 1)
                result['prompt'] = parts[0].strip()
                if len(parts) > 1:
                    result['parameters'] = ImageMetadataExtractor._parse_webui_params(parts[1])
            else:
                result['prompt'] = params.strip()
        
        return result
    
    @staticmethod
    def _parse_webui_params(param_str: str) -> Dict[str, Any]:
        """WebUI 파라미터 문자열 파싱"""
        params = {}
        
        # Steps: 20, Sampler: Euler a, CFG scale: 7.0 형식 파싱
        param_pattern = r'(\w+(?:\s+\w+)*?):\s*([^,]+)'
        matches = re.findall(param_pattern, param_str)
        
        for key, value in matches:
            key = key.strip().lower().replace(' ', '_')
            value = value.strip()
            
            # 숫자 변환 시도
            try:
                if '.' in value:
                    params[key] = float(value)
                else:
                    params[key] = int(value)
            except ValueError:
                params[key] = value
        
        return params
    
    @staticmethod
    def _parse_nai_format(text: str) -> Dict[str, Any]:
        """NovelAI 형식 메타데이터 파싱"""
        result = {
            'type': 'nai',
            'prompt': '',
            'uc': '',
            'parameters': {}
        }
        
        # prompt 추출
        prompt_match = re.search(r'"prompt"\s*:\s*"([^"]*)"', text)
        if prompt_match:
            result['prompt'] = prompt_match.group(1)
        
        # negative prompt (uc) 추출
        uc_match = re.search(r'"uc"\s*:\s*"([^"]*)"', text)
        if uc_match:
            result['uc'] = uc_match.group(1)
        
        # 기타 파라미터 추출
        param_keys = ['steps', 'scale', 'uncond_scale', 'cfg_rescale', 'seed', 
                     'sampler', 'sm', 'sm_dyn', 'noise_schedule']
        
        for key in param_keys:
            pattern = r'"{}":\s*([^,\}}]+)'.format(key)
            match = re.search(pattern, text)
            if match:
                value = match.group(1).strip()
                try:
                    if value.lower() == 'true':
                        result['parameters'][key] = True
                    elif value.lower() == 'false':
                        result['parameters'][key] = False
                    elif '.' in value:
                        result['parameters'][key] = float(value)
                    else:
                        result['parameters'][key] = int(value)
                except ValueError:
                    result['parameters'][key] = value.strip('"')
        
        # 캐릭터 프롬프트 추출
        result['characters'] = ImageMetadataExtractor._extract_char_captions(text)
        result['characters_uc'] = ImageMetadataExtractor._extract_char_captions(text, negative=True)
        
        return result
    
    @staticmethod
    def _extract_char_captions(text: str, negative: bool = False) -> list:
        """캐릭터 캡션 추출"""
        captions = []
        
        if negative:
            # negative prompt 섹션 찾기
            neg_marker = '"v4_negative_prompt"'
            neg_start = text.find(neg_marker)
            if neg_start != -1:
                text = text[neg_start:]
        
        # char_caption 추출
        pattern = r'"char_caption"\s*:\s*"([^"]*)"'
        matches = re.findall(pattern, text)
        captions.extend(matches)
        
        return captions
    
    @staticmethod
    def _extract_from_exif(img: Image.Image) -> Optional[Dict[str, Any]]:
        """EXIF 데이터에서 메타데이터 추출 - WebUI 호환"""
        try:
            # WebUI style EXIF extraction
            if PIEXIF_AVAILABLE and hasattr(img, 'info') and 'exif' in img.info:
                exif_data = img.info['exif']
                try:
                    exif = piexif.load(exif_data)
                    user_comment = (exif or {}).get("Exif", {}).get(piexif.ExifIFD.UserComment, b'')
                    
                    if user_comment:
                        geninfo = None
                        try:
                            # Try piexif.helper first (AUTOMATIC1111 standard)
                            geninfo = piexif.helper.UserComment.load(user_comment)
                        except ValueError:
                            # Fallback: UTF-8 decoding
                            try:
                                geninfo = user_comment.decode('utf8', errors="ignore")
                            except:
                                # Last resort: UTF-16 decoding
                                if user_comment.startswith(b'UNICODE\x00\x00'):
                                    utf16_data = user_comment[9:]
                                    geninfo = utf16_data.decode('utf-16le', errors='ignore')
                        
                        if geninfo:
                            # Parse WebUI format parameters
                            return ImageMetadataExtractor._parse_parameters(geninfo)
                            
                except Exception as e:
                    print(f"EXIF piexif parsing error: {e}")
            
            # Fallback to standard getexif
            exif = img.getexif()
            if exif:
                # Check for UserComment tag (37510)
                if 37510 in exif:
                    user_comment = exif[37510]
                    if isinstance(user_comment, (bytes, str)):
                        try:
                            if isinstance(user_comment, bytes):
                                if PIEXIF_AVAILABLE:
                                    comment_text = piexif.helper.UserComment.load(user_comment)
                                else:
                                    comment_text = user_comment.decode('utf-8', errors='ignore')
                            else:
                                comment_text = user_comment
                            
                            if comment_text and comment_text.strip():
                                return ImageMetadataExtractor._parse_parameters(comment_text)
                        except Exception as e:
                            print(f"EXIF UserComment extraction failed: {e}")
                
                # Check other EXIF tags
                for tag_id, value in exif.items():
                    if isinstance(value, bytes):
                        try:
                            decoded = value.decode('utf-8', errors='ignore')
                            if 'prompt' in decoded.lower() or 'negative' in decoded.lower():
                                return ImageMetadataExtractor._parse_parameters(decoded)
                        except:
                            continue
            
            return None
            
        except Exception as e:
            print(f"EXIF extraction error: {e}")
            return None
    
    @staticmethod
    def _read_stealth_pnginfo(image: Image.Image) -> Optional[str]:
        """Stealth PNG 정보 읽기"""
        if image.mode != 'RGBA':
            print(f"⚠️ _read_stealth_pnginfo: 이미지 모드 {image.mode}, RGBA 아님")
            return None

        width, height = image.size
        print(f"🔍 _read_stealth_pnginfo: 이미지 크기 {width}x{height}")
        pixels = image.load()

        binary_data = ''
        buffer_a = ''
        index_a = 0
        confirming_signature = True
        reading_param_len = False
        reading_param = False
        read_end = False

        for x in range(width):
            for y in range(height):
                r, g, b, a = pixels[x, y]
                buffer_a += str(a & 1)
                index_a += 1

                if confirming_signature and x == 0:
                    if y == 119:  # index_a == len('stealth_pngcomp') * 8 == 120
                        decoded_sig = bytearray(
                            int(buffer_a[i:i + 8], 2)
                            for i in range(0, len(buffer_a), 8)
                        ).decode('utf-8', errors='ignore')

                        print(f"🔍 _read_stealth_pnginfo: 시그니처 확인 - '{decoded_sig}'")
                        if decoded_sig == 'stealth_pngcomp':
                            print("✅ _read_stealth_pnginfo: Stealth PNG 시그니처 확인됨")
                            confirming_signature = False
                            reading_param_len = True
                            buffer_a = ''
                            index_a = 0
                        else:
                            print(f"❌ _read_stealth_pnginfo: 시그니처 불일치 (기대: 'stealth_pngcomp')")
                            return None

                elif reading_param_len:
                    if index_a == 32:  # 32 bits for length
                        param_len = int(buffer_a, 2)
                        print(f"✅ _read_stealth_pnginfo: 데이터 길이 읽음 - {param_len} bits")
                        reading_param_len = False
                        reading_param = True
                        buffer_a = ''
                        index_a = 0

                elif reading_param:
                    if index_a == param_len:
                        binary_data = buffer_a
                        print(f"✅ _read_stealth_pnginfo: 바이너리 데이터 읽기 완료 ({param_len} bits)")
                        read_end = True
                        break
                else:
                    read_end = True
                    break

            if read_end:
                break

        if binary_data:
            try:
                byte_data = bytearray(
                    int(binary_data[i:i + 8], 2)
                    for i in range(0, len(binary_data), 8)
                )
                print(f"🔍 _read_stealth_pnginfo: gzip 압축 해제 시도 ({len(byte_data)} bytes)")
                decoded_data = gzip.decompress(bytes(byte_data)).decode('utf-8')
                print(f"✅ _read_stealth_pnginfo: 데이터 추출 성공 (길이: {len(decoded_data)})")
                return decoded_data
            except Exception as e:
                print(f"❌ _read_stealth_pnginfo: gzip 압축 해제 실패 - {e}")
                pass

        print("❌ _read_stealth_pnginfo: 바이너리 데이터 없음")
        return None
    
    @staticmethod
    def _parse_stealth_data(data: str) -> Optional[Dict[str, Any]]:
        """Stealth PNG 데이터 파싱"""
        try:
            # JSON 직접 파싱 시도
            if data.strip().startswith('{'):
                try:
                    # 먼저 그대로 파싱 시도
                    parsed = json.loads(data)
                    # Comment 필드가 있으면 이것도 JSON 파싱 시도
                    if 'Comment' in parsed and isinstance(parsed['Comment'], str):
                        try:
                            parsed['Comment'] = json.loads(parsed['Comment'])
                        except:
                            pass  # Comment가 JSON이 아니면 그대로 유지
                    return parsed
                except json.JSONDecodeError:
                    # 실패하면 백슬래시 제거 후 재시도 (구형 호환성)
                    try:
                        return json.loads(data.replace("\\", ""))
                    except:
                        pass
        except Exception as e:
            print(f"Stealth data parsing error: {e}")

        # NAI 형식으로 파싱 시도
        return ImageMetadataExtractor._parse_nai_format(data)
    
    @staticmethod
    def detect_software(metadata: Dict[str, Any]) -> str:
        """메타데이터에서 소프트웨어 타입 감지"""
        if not metadata:
            return 'unknown'
        
        meta_type = metadata.get('type', '')
        if meta_type:
            return meta_type
        
        # NovelAI 특징 확인
        if 'sm' in metadata.get('parameters', {}):
            return 'nai'
        
        # WebUI 특징 확인
        if 'sampler' in metadata.get('parameters', {}):
            return 'webui'
        
        return 'unknown'