"""
Inpaint generation worker for API calls
"""

from PyQt6.QtCore import QThread, pyqtSignal
from PIL import Image, ImageFilter
import numpy as np
import io
import base64

class InpaintGenerationWorker(QThread):
    """Worker thread for inpaint image generation"""
    generation_finished = pyqtSignal(Image.Image, Image.Image, tuple)  # combined_image, server_original, bounding_box
    generation_error = pyqtSignal(str)
    progress_update = pyqtSignal(str)
    
    def __init__(self, app_context, composite_img: Image.Image, mask_img: Image.Image, 
                 main_prompt: str, negative_prompt: str, strength: float = 0.7,
                 small_mask: Image.Image = None, character_prompts: list = None):
        super().__init__()
        self.app_context = app_context
        self.composite_img = composite_img
        self.mask_img = mask_img
        self.small_mask = small_mask  # Pre-generated small mask for NAI
        self.main_prompt = main_prompt
        self.negative_prompt = negative_prompt
        self.strength = strength
        self.character_prompts = character_prompts or []  # List of (prompt, uc) tuples
    
    def run(self):
        """Run the generation process"""
        try:
            self.progress_update.emit("이미지 준비 중...")
            
            # Get bounding box of mask
            bbox = self._get_mask_bbox(self.mask_img)
            if not bbox:
                self.generation_error.emit("마스크 영역이 없습니다.")
                return
            
            # Convert images to bytes for API
            composite_bytes = io.BytesIO()
            self.composite_img.save(composite_bytes, format='PNG')
            composite_bytes.seek(0)
            
            # Prepare mask based on API mode
            mask_bytes = io.BytesIO()
            api_mode = "NAI"  # Default
            
            if hasattr(self.app_context, 'main_window'):
                api_mode = self.app_context.main_window.get_current_api_mode() if hasattr(
                    self.app_context.main_window, 'get_current_api_mode'
                ) else "NAI"
            
            if api_mode == "NAI":
                # NAI requires 1/8 size mask
                if self.small_mask:
                    # Use pre-generated small mask
                    self.small_mask.save(mask_bytes, format='PNG')
                else:
                    # Create small mask if not provided
                    small_mask = self._create_small_mask(self.mask_img)
                    small_mask.save(mask_bytes, format='PNG')
            else:
                # WebUI/ComfyUI use full size mask
                self.mask_img.save(mask_bytes, format='PNG')
            
            mask_bytes.seek(0)
            
            self.progress_update.emit("파라미터 수집 중...")
            
            # Collect parameters
            params = self._collect_parameters(api_mode)
            
            # Add inpaint-specific parameters
            params['type'] = 'inpaint'
            params['strength'] = self.strength
            params['noise'] = 0.0
            params['image_bytes'] = composite_bytes.getvalue()  # Use image_bytes for NAI
            params['mask_bytes'] = mask_bytes.getvalue()       # Use mask_bytes for NAI
            params['width'] = self.composite_img.width
            params['height'] = self.composite_img.height
            
            # Override prompts
            params['input'] = self.main_prompt if self.main_prompt else params.get('prompt', '')
            params['prompt'] = params['input']  # Alias for compatibility
            params['negative_prompt'] = self.negative_prompt if self.negative_prompt else params.get('negative_prompt', '')
            
            self.progress_update.emit("API 호출 중...")
            
            # Call API
            if hasattr(self.app_context, 'api_service'):
                result = self.app_context.api_service.call_generation_api(params)
                
                if result.get('status') == 'success':
                    generated_image = result.get('image')
                    if generated_image:
                        # Combine with original image using mask
                        final_img = self._combine_with_original(
                            generated_image, self.composite_img, self.mask_img, bbox
                        )
                        # Emit both combined result and server original
                        self.generation_finished.emit(final_img, generated_image, bbox)
                    else:
                        self.generation_error.emit("생성된 이미지를 찾을 수 없습니다.")
                else:
                    error_msg = result.get('message', '알 수 없는 오류')
                    self.generation_error.emit(f"생성 실패: {error_msg}")
            else:
                self.generation_error.emit("API 서비스를 찾을 수 없습니다.")
                
        except Exception as e:
            self.generation_error.emit(f"오류 발생: {str(e)}")
    
    def _get_mask_bbox(self, mask_img: Image.Image) -> tuple:
        """Get bounding box of the mask"""
        # Convert to grayscale if needed
        if mask_img.mode != 'L':
            mask_img = mask_img.convert('L')
        
        # Use numpy for more accurate bbox calculation
        mask_array = np.array(mask_img)
        
        # Find non-zero pixels
        non_zero = np.where(mask_array > 128)
        
        if len(non_zero[0]) == 0:
            # No mask, return full image bounds
            return (0, 0, mask_img.width, mask_img.height)
        
        # Calculate bounding box
        y_min = int(non_zero[0].min())
        y_max = int(non_zero[0].max())
        x_min = int(non_zero[1].min())
        x_max = int(non_zero[1].max())
        
        return (x_min, y_min, x_max + 1, y_max + 1)
    
    def _create_small_mask(self, mask_img: Image.Image) -> Image.Image:
        """Create 1/8 size mask for NAI API"""
        w, h = mask_img.size
        small_w, small_h = w // 8, h // 8
        
        # Resize mask to 1/8 size
        small_mask = mask_img.resize((small_w, small_h), Image.Resampling.NEAREST)
        
        # Ensure binary mask (0 or 255)
        import numpy as np
        mask_array = np.array(small_mask)
        mask_array = np.where(mask_array > 127, 255, 0).astype(np.uint8)
        
        return Image.fromarray(mask_array, mode='L')
    
    def _collect_parameters(self, api_mode: str) -> dict:
        """Collect generation parameters from main window"""
        params = {}
        
        if not hasattr(self.app_context, 'main_window'):
            return params
        
        main_window = self.app_context.main_window
        
        # Get credentials
        credential = None
        if hasattr(self.app_context, 'secure_token_manager'):
            if api_mode == "NAI":
                credential = self.app_context.secure_token_manager.get_token('nai_token')
            elif api_mode == "COMFYUI":
                credential = self.app_context.secure_token_manager.get_token('comfyui_url')
            else:
                credential = self.app_context.secure_token_manager.get_token('webui_url')
        
        # Get main parameters
        if hasattr(main_window, 'get_main_parameters'):
            params = main_window.get_main_parameters()
            params['api_mode'] = api_mode
            params['credential'] = credential
            
            # Collect module parameters
            if hasattr(self.app_context, 'middle_section_controller'):
                controller = self.app_context.middle_section_controller
                if hasattr(controller, 'module_instances'):
                    for module in controller.module_instances:
                        if hasattr(module, 'get_parameters'):
                            module_params = module.get_parameters()
                            if module_params:
                                params.update(module_params)
        
        # Add sketchbook character prompts if available
        if self.character_prompts:
            params['sketchbook_character_prompts'] = self.character_prompts
            print(f"📝 Added {len(self.character_prompts)} character prompts to params")
        
        return params
    
    def _apply_mask_with_feathering(self, generated_img: Image.Image, mask_img: Image.Image, 
                                   feather_pixels: int = 6) -> Image.Image:
        """Apply mask with feathering effect"""
        # Convert mask to L mode if needed
        if mask_img.mode != 'L':
            mask_img = mask_img.convert('L')
        
        # Apply Gaussian blur for feathering
        feathered_mask = mask_img.filter(ImageFilter.GaussianBlur(radius=feather_pixels))
        
        # Ensure images are in RGBA mode
        if generated_img.mode != 'RGBA':
            generated_img = generated_img.convert('RGBA')
        
        # Apply mask
        result = Image.new('RGBA', generated_img.size, (0, 0, 0, 0))
        result.paste(generated_img, (0, 0))
        result.putalpha(feathered_mask)
        
        return result
    
    def _apply_mask_with_feathering_and_crop(self, generated_img: Image.Image, mask_img: Image.Image, 
                                            bbox: tuple, feather_pixels: int = 6) -> Image.Image:
        """Apply mask with feathering and crop to bounding box"""
        # First apply mask to full image
        full_result = self._apply_mask_with_feathering(generated_img, mask_img, feather_pixels)
        
        # Crop to bounding box
        cropped = full_result.crop(bbox)
        
        return cropped
    
    def _combine_with_original(self, generated_img: Image.Image, original_img: Image.Image, 
                               mask_img: Image.Image, bbox: tuple, feather_pixels: int = 6) -> Image.Image:
        """Combine generated image with original using mask"""
        from PIL import ImageFilter
        
        # Ensure all images are RGBA
        if generated_img.mode != 'RGBA':
            generated_img = generated_img.convert('RGBA')
        if original_img.mode != 'RGBA':
            original_img = original_img.convert('RGBA')
        
        # Convert mask to L mode if needed
        if mask_img.mode != 'L':
            mask_img = mask_img.convert('L')
        
        # Apply Gaussian blur for feathering
        feathered_mask = mask_img.filter(ImageFilter.GaussianBlur(radius=feather_pixels))
        
        # Create result image starting with original
        result = original_img.copy()
        
        # Paste generated image using feathered mask
        result.paste(generated_img, (0, 0), feathered_mask)
        
        # Crop to bounding box
        cropped = result.crop(bbox)
        
        return cropped