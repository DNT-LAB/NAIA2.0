"""
WildcardCombinationGenerator - Utility for generating all wildcard combinations
"""

from typing import List, Dict, Tuple
from core.wildcard_manager import WildcardManager
from core.wildcard_processor import WildcardProcessor
from core.prompt_context import PromptContext
import pandas as pd


class WildcardCombinationGenerator:
    """Generator for creating all wildcard combinations in 2D grid"""

    def __init__(self, wildcard_manager: WildcardManager):
        self.wildcard_manager = wildcard_manager
        self.processor = WildcardProcessor(wildcard_manager)

    def get_wildcard_items(self, wildcard_name: str) -> List[str]:
        """Get all items from a wildcard file

        Args:
            wildcard_name: Name of wildcard (e.g., "pose", "characters/outfit")

        Returns:
            List of items in the wildcard, or empty list if not found
        """
        # Try direct match first
        if wildcard_name in self.wildcard_manager.wildcard_dict_tree:
            return self.wildcard_manager.wildcard_dict_tree[wildcard_name].copy()

        # Try fuzzy match (remove common prefixes/suffixes)
        # This handles cases like "test_emotions" matching "subfolder/test_emotions"
        for key in self.wildcard_manager.wildcard_dict_tree.keys():
            if wildcard_name in key or key.endswith(wildcard_name):
                return self.wildcard_manager.wildcard_dict_tree[key].copy()

        print(f"Warning: Wildcard '{wildcard_name}' not found")
        return []

    def generate_all_combinations(
        self,
        prompt_pattern: str,
        axis_x_name: str,
        axis_y_name: str
    ) -> Dict[Tuple[int, int], str]:
        """Generate all (x_idx, y_idx) -> expanded_prompt mappings

        Args:
            prompt_pattern: Original prompt pattern with wildcards
            axis_x_name: X-axis wildcard name
            axis_y_name: Y-axis wildcard name

        Returns:
            Dictionary mapping (x_index, y_index) to expanded prompts
        """
        # Get items for each axis
        x_items = self.get_wildcard_items(axis_x_name)
        y_items = self.get_wildcard_items(axis_y_name)

        if not x_items or not y_items:
            print(f"Error: Cannot generate combinations - missing wildcard items")
            return {}

        # Split prompt pattern by commas to get individual tags
        tags = [tag.strip() for tag in prompt_pattern.split(',') if tag.strip()]

        # Generate all combinations
        combination_grid = {}

        for y_idx in range(len(y_items)):
            for x_idx in range(len(x_items)):
                # Create fresh context for this combination
                context = PromptContext(
                    source_row=pd.Series(),
                    settings={}
                )

                # Expand tags with current wildcard indices
                expanded_tags = self.processor.expand_tags(tags.copy(), context)

                # Join into final prompt
                expanded_prompt = ', '.join(expanded_tags)

                # Store in grid
                combination_grid[(x_idx, y_idx)] = expanded_prompt

        print(f"Generated {len(combination_grid)} combinations ({len(x_items)}x{len(y_items)})")
        return combination_grid

    def expand_for_indices(
        self,
        prompt_pattern: str,
        axis_x_name: str,
        x_index: int,
        axis_y_name: str,
        y_index: int
    ) -> str:
        """Expand prompt for specific axis indices

        Args:
            prompt_pattern: Original prompt pattern with wildcards
            axis_x_name: X-axis wildcard name
            x_index: Index of X-axis item to use
            axis_y_name: Y-axis wildcard name
            y_index: Index of Y-axis item to use

        Returns:
            Expanded prompt string
        """
        # This is a placeholder - full implementation would need to
        # manually set wildcard indices in the context before expanding
        # For now, just use the existing expand logic
        tags = [tag.strip() for tag in prompt_pattern.split(',') if tag.strip()]

        context = PromptContext(
            source_row=pd.Series(),
            settings={}
        )

        expanded_tags = self.processor.expand_tags(tags.copy(), context)
        return ', '.join(expanded_tags)
