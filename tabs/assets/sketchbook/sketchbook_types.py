"""
Data types and constants for Sketchbook module
"""

from dataclasses import dataclass
from typing import Tuple, Optional
from PyQt6.QtGui import QPixmap
import uuid

# Canvas size presets
CANVAS_SIZES = {
    # Square
    "1024×1024 (1:1)": (1024, 1024),
    
    # Portrait sizes
    "704×1472 (Portrait)": (704, 1472),
    "768×1344 (Portrait)": (768, 1344),
    "832×1216 (2:3)": (832, 1216),
    "896×1152 (Portrait)": (896, 1152),
    
    # Landscape sizes
    "1088×960 (Landscape)": (1088, 960),
    "1152×896 (Landscape)": (1152, 896),
    "1216×832 (3:2)": (1216, 832),
    "1344×768 (Landscape)": (1344, 768),
}

@dataclass
class LayerData:
    """Data structure for layer information"""
    name: str
    image_path: str
    position: Tuple[float, float]
    scale: float = 1.0
    rotation: float = 0.0
    z_order: int = 0
    visible: bool = True
    opacity: float = 1.0
    id: str = None
    pixmap: Optional[QPixmap] = None
    original_size: Optional[Tuple[int, int]] = None
    character_prompt: Optional[dict] = None  # Character prompt data from JSON
    prompt_activated: bool = True  # Whether prompt is active (default True if has prompt)
    active_properties: Optional[dict] = None  # Track which properties are active

    def __post_init__(self):
        if self.id is None:
            self.id = str(uuid.uuid4())
        # Auto-set prompt_activated based on character_prompt presence
        if self.character_prompt is not None and not hasattr(self, '_prompt_activated_set'):
            self.prompt_activated = True
        # Initialize active_properties if character_prompt exists
        if self.character_prompt and self.active_properties is None:
            # Initialize all properties as inactive by default
            properties = self.character_prompt.get('properties', {})
            self.active_properties = {key: False for key in properties.keys()}
    
    def get_character_prompt(self) -> Tuple[str, str]:
        """Get the combined character prompt and uc based on active properties"""
        if not self.character_prompt or not self.prompt_activated:
            return "", ""
        
        # Get base prompt and uc
        prompt = self.character_prompt.get('prompt', '')
        uc = self.character_prompt.get('uc', '')
        
        # Add active properties to prompt
        if self.active_properties and self.character_prompt.get('properties'):
            properties = self.character_prompt.get('properties', {})
            for prop_key, is_active in self.active_properties.items():
                if is_active and prop_key in properties:
                    prop_data = properties[prop_key]
                    if isinstance(prop_data, dict):
                        prop_prompt = prop_data.get('prompt', '')
                        if prop_prompt:
                            prompt = f"{prompt}, {prop_prompt}"
                        # Also append uc if exists
                        prop_uc = prop_data.get('uc', '')
                        if prop_uc:
                            uc = f"{uc}, {prop_uc}" if uc else prop_uc
        
        return prompt, uc