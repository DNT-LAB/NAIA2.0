"""
Sequence Generator - Utility for converting frame events to :sequence text format
"""

from typing import List, Dict


def generate_sequence_text(frames_data: List[Dict]) -> str:
    """
    Convert frame events data to :sequence text format.

    Args:
        frames_data: List of frame data dictionaries, each containing:
            - prompt: Main prompt text
            - negative_prompt: Additional negative prompt (optional)
            - resolution: Resolution string like "1024 x 1024" (optional)

    Returns:
        str: Generated sequence text in format:
            :begin, :seq1 [prompt] [-neg_tag1, -neg_tag2] resolution:WxH, :seq2 ..., :end,

    Example:
        >>> frames = [
        ...     {"prompt": "happy", "negative_prompt": "sad, angry", "resolution": "1024 x 1024"},
        ...     {"prompt": "excited", "negative_prompt": "", "resolution": "832 x 1216"}
        ... ]
        >>> text = generate_sequence_text(frames)
        >>> print(text)
        :begin, :seq1 happy, -sad, -angry, resolution:1024x1024, :seq2 excited, resolution:832x1216, :end,
    """
    if not frames_data:
        return ":begin, :end,"

    parts = [":begin"]

    for i, frame in enumerate(frames_data, start=1):
        content_parts = []

        # Add main prompt
        prompt = frame.get('prompt', '').strip()
        if prompt:
            content_parts.append(prompt)

        # Add negative prompt tags with '-' prefix
        negative = frame.get('negative_prompt', '').strip()
        if negative:
            # Split by comma and add '-' prefix to each tag
            neg_tags = [tag.strip() for tag in negative.split(',') if tag.strip()]
            neg_with_prefix = [f"-{tag}" for tag in neg_tags]
            if neg_with_prefix:
                content_parts.append(', '.join(neg_with_prefix))

        # Add resolution tag
        resolution = frame.get('resolution', '').strip()
        if resolution and ' x ' in resolution:
            # Convert "1024 x 1024" to "resolution:1024x1024"
            res_clean = resolution.replace(' x ', 'x').replace(' ', '')
            content_parts.append(f"resolution:{res_clean}")

        # Join sequence marker with content (no comma between :seqN and content)
        seq_content = ', '.join(content_parts)
        if seq_content:
            parts.append(f":seq{i} {seq_content}")
        else:
            parts.append(f":seq{i}")

    parts.append(":end,")

    # Join all parts with ", "
    return ', '.join(parts)


def generate_sequence_text_from_preset(preset_data: Dict) -> str:
    """
    Convert preset data to :sequence text format.

    Args:
        preset_data: Preset dictionary containing 'frames' list

    Returns:
        str: Generated sequence text
    """
    frames = preset_data.get('frames', [])

    # Extract prompt_data from each frame
    frames_data = []
    for frame in frames:
        prompt_data = frame.get('prompt_data', {})
        frames_data.append({
            'prompt': prompt_data.get('prompt', ''),
            'negative_prompt': prompt_data.get('negative_prompt', ''),
            'resolution': prompt_data.get('resolution', '')
        })

    return generate_sequence_text(frames_data)
