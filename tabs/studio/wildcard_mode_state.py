"""
WildcardModeState - State management for wildcard navigation with swappable axes
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple


@dataclass
class WildcardAxisInfo:
    """Information about a single wildcard axis"""
    name: str                          # Wildcard name (e.g., "pose" or "custom")
    items: List[str]                   # All items in this wildcard
    item_count: int                    # Total items


@dataclass
class WildcardModeState:
    """State for wildcard navigation mode with swappable axes

    Concept:
    - WC1 and WC2 are the two wildcards
    - Page Axis: One item per page (user navigates through pages)
    - Frame Axis: All items on each page (fills frames)
    - axes_swapped: False = WC1 is Page, WC2 is Frame
                    True = WC2 is Page, WC1 is Frame
    """
    # Mode flag
    is_wildcard_mode: bool = False

    # Original prompt pattern (for regeneration)
    original_prompt_pattern: str = ""

    # The two wildcards
    wc1: Optional[WildcardAxisInfo] = None
    wc2: Optional[WildcardAxisInfo] = None

    # Axis assignment (False = WC1 is Page, True = WC2 is Page)
    axes_swapped: bool = False

    # Current page (for page axis)
    current_page: int = 0  # 0-indexed

    # Virtual 2D grid of all combinations
    # Key: (wc1_index, wc2_index) -> expanded prompt
    combination_grid: Dict[Tuple[int, int], str] = field(default_factory=dict)

    def get_page_axis(self) -> Optional[WildcardAxisInfo]:
        """Get the wildcard currently assigned to page axis"""
        if self.axes_swapped:
            return self.wc2
        else:
            return self.wc1

    def get_frame_axis(self) -> Optional[WildcardAxisInfo]:
        """Get the wildcard currently assigned to frame axis"""
        if self.axes_swapped:
            return self.wc1
        else:
            return self.wc2

    def get_page_axis_name(self) -> str:
        """Get page axis wildcard name"""
        page_axis = self.get_page_axis()
        return page_axis.name if page_axis else ""

    def get_frame_axis_name(self) -> str:
        """Get frame axis wildcard name"""
        frame_axis = self.get_frame_axis()
        return frame_axis.name if frame_axis else ""

    def get_total_pages(self) -> int:
        """Get total number of pages"""
        page_axis = self.get_page_axis()
        return page_axis.item_count if page_axis else 1

    def get_current_page_item(self) -> str:
        """Get the current page's item value"""
        page_axis = self.get_page_axis()
        if not page_axis or self.current_page >= page_axis.item_count:
            return ""
        return page_axis.items[self.current_page]

    def get_frame_items(self) -> List[str]:
        """Get all frame items for current page"""
        frame_axis = self.get_frame_axis()
        return frame_axis.items if frame_axis else []

    def get_visible_combinations(self) -> List[Tuple[int, int, str]]:
        """Get combinations for current page as (wc1_idx, wc2_idx, prompt)

        Returns:
            List of (wc1_index, wc2_index, prompt) for current page
        """
        result = []

        if not self.wc1 or not self.wc2:
            return result

        frame_axis = self.get_frame_axis()
        if not frame_axis:
            return result

        if self.axes_swapped:
            # WC2 is Page, WC1 is Frame
            # Current page selects one WC2 item, iterate through all WC1 items
            wc2_idx = self.current_page
            if wc2_idx < self.wc2.item_count:
                for wc1_idx in range(self.wc1.item_count):
                    prompt = self.combination_grid.get((wc1_idx, wc2_idx), "")
                    result.append((wc1_idx, wc2_idx, prompt))
        else:
            # WC1 is Page, WC2 is Frame
            # Current page selects one WC1 item, iterate through all WC2 items
            wc1_idx = self.current_page
            if wc1_idx < self.wc1.item_count:
                for wc2_idx in range(self.wc2.item_count):
                    prompt = self.combination_grid.get((wc1_idx, wc2_idx), "")
                    result.append((wc1_idx, wc2_idx, prompt))

        return result

    def navigate_page(self, delta: int):
        """Navigate pages by delta

        Args:
            delta: Relative page movement (-1=previous, +1=next)
        """
        new_page = self.current_page + delta
        max_page = self.get_total_pages() - 1
        self.current_page = max(0, min(new_page, max_page))

    def swap_axes(self):
        """Swap page and frame axes"""
        self.axes_swapped = not self.axes_swapped
        # Reset to first page when swapping
        self.current_page = 0
        print(f"Axes swapped: Page={self.get_page_axis_name()}, Frame={self.get_frame_axis_name()}")

    def reset(self):
        """Reset to non-wildcard mode"""
        self.is_wildcard_mode = False
        self.original_prompt_pattern = ""
        self.wc1 = None
        self.wc2 = None
        self.axes_swapped = False
        self.current_page = 0
        self.combination_grid.clear()
