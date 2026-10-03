"""Bundled tone reference and signed positions. Bands describe a sample, not quality."""
from __future__ import annotations

import math

AXIS_SPECS = (
    # 밝기는 화면의 축에서 뺐다(사용자 결정 2026-10-03): 움직일 손잡이가 없고, 높은 쪽은 배경이 흰 그림일 뿐이다
    # (기준 표본에서 밝기와 테두리 밝기의 상관 0.95). 값은 남긴다 - 시험 생성의 전후 비교가 쓴다.
    ("lightness", "lightness.mean", "밝기", 1, ["장면을 탄다 — 사실상 배경의 밝기다"], False),
    ("chroma", "chroma.mean", "채도", 1, ["흰 배경이면 낮게 나온다"], True),
    ("yellow", "tint.highlights.b", "누런 기", 1, ["장면의 조명도 올린다"], True),
    ("line_contrast", "lines.depth", "선 대비", 1, ["맨 아래쪽은 선이 없는 그림이다"], True),
    ("line_width", "lines.width", "선 굵기", 2,
     ["선이 사라진 그림에서도 정상으로 읽힌다 — 선 대비와 같이 본다", "10px 이상은 못 잡는다"], True),
    ("sharpness", "texture.sharpness", "또렷함", 0, ["해상도에 민감하다"], True),
    ("grain", "texture.grain", "거칠기", 2, ["세밀한 묘사에도 오른다"], True),
    ("dark_floor", "lightness.p01", "가장 어두운 1%", 1, [], False),
    ("center_chroma", "regions.center.chroma_mean", "가운데 채도", 1, [], False),
    ("neutral_share", "chroma.neutral_share", "무채색 비율", 2, [], False),
    ("red", "tint.highlights.a", "붉은 기", 1, [], False),
    ("line_floor", "lines.floor", "선 명도", 1, [], False),
    # RGB 치우침(채널 평균 - 세 채널의 평균). 화면의 'RGB 로 어디에 얼마나' 가 이 여섯을 0점과 견준다.
    ("rgb_r", "rgb.overall.bias.r", "R", 1, [], False),
    ("rgb_g", "rgb.overall.bias.g", "G", 1, [], False),
    ("rgb_b", "rgb.overall.bias.b", "B", 1, [], False),
    ("rgb_hi_r", "rgb.highlights.bias.r", "밝은 영역 R", 1, [], False),
    ("rgb_hi_g", "rgb.highlights.bias.g", "밝은 영역 G", 1, [], False),
    ("rgb_hi_b", "rgb.highlights.bias.b", "밝은 영역 B", 1, [], False),
)

# BEGIN GENERATED REFERENCE
REFERENCE = {'schema': 'naia.tone-reference.v1',
 'sample': 'NAIA random prompts; review_raw50, review_raw51, review_raw52, review_raw53, review_raw54, '
           'review_raw55, review_raw56, review_raw57, review_raw58; <artist>/*.png excluding 0_first.png',
 'images': 4054,
 'rule': 'cut = round(n * 500 / 4002); zero = trimmed mean; band = trimmed min/max',
 'built_at': '2026-10-03T14:33:51.368892+00:00',
 'axes': [{'id': 'lightness',
           'key': 'lightness.mean',
           'label': '밝기',
           'zero': 69.36017422748192,
           'low': 57.42,
           'high': 79.23,
           'digits': 1,
           'cautions': ['장면을 탄다 — 사실상 배경의 밝기다'],
           'primary': False},
          {'id': 'chroma',
           'key': 'chroma.mean',
           'label': '채도',
           'zero': 14.648274161735701,
           'low': 8.77,
           'high': 22.02,
           'digits': 1,
           'cautions': ['흰 배경이면 낮게 나온다'],
           'primary': True},
          {'id': 'yellow',
           'key': 'tint.highlights.b',
           'label': '누런 기',
           'zero': 2.018911900065746,
           'low': 0.0,
           'high': 7.49,
           'digits': 1,
           'cautions': ['장면의 조명도 올린다'],
           'primary': True},
          {'id': 'line_contrast',
           'key': 'lines.depth',
           'label': '선 대비',
           'zero': 36.237343852728465,
           'low': 26.9,
           'high': 48.5,
           'digits': 1,
           'cautions': ['맨 아래쪽은 선이 없는 그림이다'],
           'primary': True},
          {'id': 'line_width',
           'key': 'lines.width',
           'label': '선 굵기',
           'zero': 1.7751150558842865,
           'low': 1.49,
           'high': 2.28,
           'digits': 2,
           'cautions': ['선이 사라진 그림에서도 정상으로 읽힌다 — 선 대비와 같이 본다', '10px 이상은 못 잡는다'],
           'primary': True},
          {'id': 'sharpness',
           'key': 'texture.sharpness',
           'label': '또렷함',
           'zero': 243.76104536489152,
           'low': 135.3,
           'high': 387.2,
           'digits': 0,
           'cautions': ['해상도에 민감하다'],
           'primary': True},
          {'id': 'grain',
           'key': 'texture.grain',
           'label': '거칠기',
           'zero': 0.54215483234714,
           'low': 0.207,
           'high': 1.075,
           'digits': 2,
           'cautions': ['세밀한 묘사에도 오른다'],
           'primary': True},
          {'id': 'dark_floor',
           'key': 'lightness.p01',
           'label': '가장 어두운 1%',
           'zero': 10.046387245233399,
           'low': 2.57,
           'high': 19.8,
           'digits': 1,
           'cautions': [],
           'primary': False},
          {'id': 'center_chroma',
           'key': 'regions.center.chroma_mean',
           'label': '가운데 채도',
           'zero': 16.510884286653518,
           'low': 11.55,
           'high': 22.22,
           'digits': 1,
           'cautions': [],
           'primary': False},
          {'id': 'neutral_share',
           'key': 'chroma.neutral_share',
           'label': '무채색 비율',
           'zero': 0.2871487508218277,
           'low': 0.0872,
           'high': 0.5186,
           'digits': 2,
           'cautions': [],
           'primary': False},
          {'id': 'red',
           'key': 'tint.highlights.a',
           'label': '붉은 기',
           'zero': 0.2775739644970414,
           'low': -1.54,
           'high': 2.97,
           'digits': 1,
           'cautions': [],
           'primary': False},
          {'id': 'line_floor',
           'key': 'lines.floor',
           'label': '선 명도',
           'zero': 22.749802761341222,
           'low': 9.4,
           'high': 36.0,
           'digits': 1,
           'cautions': [],
           'primary': False},
          {'id': 'rgb_r',
           'key': 'rgb.overall.bias.r',
           'label': 'R',
           'zero': 8.374030243261013,
           'low': -4.4,
           'high': 19.6,
           'digits': 1,
           'cautions': [],
           'primary': False},
          {'id': 'rgb_g',
           'key': 'rgb.overall.bias.g',
           'label': 'G',
           'zero': -4.002366863905325,
           'low': -8.6,
           'high': 0.9,
           'digits': 1,
           'cautions': [],
           'primary': False},
          {'id': 'rgb_b',
           'key': 'rgb.overall.bias.b',
           'label': 'B',
           'zero': -4.243786982248521,
           'low': -14.1,
           'high': 6.3,
           'digits': 1,
           'cautions': [],
           'primary': False},
          {'id': 'rgb_hi_r',
           'key': 'rgb.highlights.bias.r',
           'label': '밝은 영역 R',
           'zero': 2.8534188034188035,
           'low': -0.9,
           'high': 12.1,
           'digits': 1,
           'cautions': [],
           'primary': False},
          {'id': 'rgb_hi_g',
           'key': 'rgb.highlights.bias.g',
           'label': '밝은 영역 G',
           'zero': 0.3472715318869165,
           'low': -1.5,
           'high': 3.1,
           'digits': 1,
           'cautions': [],
           'primary': False},
          {'id': 'rgb_hi_b',
           'key': 'rgb.highlights.bias.b',
           'label': '밝은 영역 B',
           'zero': -3.1673570019723867,
           'low': -12.2,
           'high': 0.2,
           'digits': 1,
           'cautions': [],
           'primary': False}]}
# END GENERATED REFERENCE


def metric_value(inspection, key):
    value = inspection
    for part in key.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return float(value)


def axis_positions(inspection, reference=REFERENCE):
    """Return every axis; missing/nonfinite readings remain JSON-safe nulls.

    width_reliable comes from the valid cross-section fraction (B2). Older
    inspections without that key use the SRS contrast-distance fallback.
    Degenerate reference spans cannot define a distance (null, outside band).
    """
    positions = []
    for axis in reference["axes"]:
        value = metric_value(inspection, axis["key"])
        zero, low, high = (axis[k] for k in ("zero", "low", "high"))
        distance = None
        if value is not None:
            span = abs((high if value >= zero else low) - zero)
            distance = (value-zero)/span if span else (0.0 if value == zero else None)
        positions.append({k: axis[k] for k in ("id", "key", "label", "zero", "low", "high")} | {
            "value": value, "distance": distance,
            "side": "center" if distance is None or abs(distance) < .25 else "low" if distance < 0 else "high",
            "in_band": value is not None and low <= value <= high,
            "reliable": True, "cautions": list(axis.get("cautions", [])),
            "primary": axis.get("primary", True), "digits": axis.get("digits", 2),
        })
    contrast = next((p["distance"] for p in positions if p["id"] == "line_contrast"), None)
    for position in positions:
        if position["id"] == "line_width":
            lines = inspection.get("lines", {}) if isinstance(inspection, dict) else {}
            marker = lines.get("width_reliable") if isinstance(lines, dict) else None
            available = position["value"] is not None
            if isinstance(marker, bool):
                position["reliable"] = marker and available
                if not position["reliable"]:
                    position["cautions"].append("유효 단면 비율 88% 미만 또는 측정 없음: 선 굵기 해석을 보류한다 (10장 확인 기준)")
            else:
                position["reliable"] = contrast is not None and contrast >= -1.5 and available
                if not position["reliable"]:
                    position["cautions"].append("선 대비 거리 -1.5 미만 또는 측정 없음: 선 굵기 해석을 보류한다 (구 측정의 임시 규칙)")
    return positions
