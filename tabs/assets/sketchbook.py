"""
Sketchbook module - Bridge file for backward compatibility
This file maintains compatibility with existing imports while using the new modular structure.
"""

# Import the main widget from the new modular structure
from tabs.assets.sketchbook.sketchbook_widget import SketchbookWidget

# Export for backward compatibility
__all__ = ['SketchbookWidget']