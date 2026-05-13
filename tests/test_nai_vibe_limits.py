import pytest

from core.generation_request import NAIVibeTransferData
from core.nai_vibe_limits import MAX_NAI_VIBE_REFERENCES


def _vibe_data(count: int, *, ie_values=None) -> NAIVibeTransferData:
    return NAIVibeTransferData(
        reference_image_multiple=[f"encoded-{index}" for index in range(count)],
        reference_strength_multiple=[1.0 / count] * count,
        normalize=True,
        reference_information_extracted_multiple=ie_values or [],
    )


def test_nai_vibe_transfer_data_accepts_official_maximum():
    data = _vibe_data(
        MAX_NAI_VIBE_REFERENCES,
        ie_values=[
            round((index + 1) / MAX_NAI_VIBE_REFERENCES, 3)
            for index in range(MAX_NAI_VIBE_REFERENCES)
        ],
    )

    assert len(data.reference_image_multiple) == MAX_NAI_VIBE_REFERENCES
    assert data.reference_information_extracted_multiple[-1] == 1.0


def test_nai_vibe_transfer_data_rejects_above_official_maximum():
    with pytest.raises(ValueError, match=f"Maximum {MAX_NAI_VIBE_REFERENCES} reference images"):
        _vibe_data(MAX_NAI_VIBE_REFERENCES + 1)
