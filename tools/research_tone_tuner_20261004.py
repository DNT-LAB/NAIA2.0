"""Offline Tone Tuner research. Never opens images, imports core, or calls a service.

Outputs are create-only. Reproduce in a fresh docs/tone_tuner_2026_10_04/<name>
directory rather than overwriting another session's files.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
from collections import Counter
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq
from scipy import stats

ROOT = Path(__file__).resolve().parents[1]
PROMPTS = "docs/tone_eval_2026_10_03/round3/reference_prompts.jsonl"
MEASUREMENTS = "docs/tone_eval_2026_10_03/round3/reference_measurements.jsonl"
COUNTS = "data/danbooru_tag_counts_by_rating.json"
SNAP = "data/danbooru_tag_snapshot/tags.parquet"
ALIASES = "data/danbooru_tag_snapshot/tag_aliases.parquet"
THUMB = "data/taglist/style_meta_tags.json"
AXES = "data/interactive_axis_tags.json"
SURVEY = "docs/STYLE_MOOD_CONTROL_SURVEY_2026_10_03.md"
MEMO = "core/headless_memo_service.py"
BENCH = "docs/mood_bench/raw_levers/manifest.json"
ZERO_PROMPT = ("-1::artist collaboration ::, 0.75::, countershade ::, year 2024, "
               "masterpiece, very aesthetic, high-quality digital art, high complexity, "
               "-0.25::low complexity, detailed background ::, 0.15::ultra complexity ::, no text, depthness")
METRICS = {
    "lightness": "lightness.mean", "chroma": "chroma.mean",
    "yellow": "tint.highlights.b", "line_contrast": "lines.depth",
    "line_width": "lines.width", "sharpness": "texture.sharpness",
    "grain": "texture.grain", "center_chroma": "regions.center.chroma_mean",
    "center_lightness": "regions.center.lightness_mean",
    "border_lightness": "regions.border.lightness_mean",
    "border_chroma": "regions.border.chroma_mean", "neutral_share": "chroma.neutral_share",
    "lightness_std": "lightness.std", "dark_share": "lightness.dark_share",
    "hue_entropy": "hue.entropy_bits", "red": "tint.highlights.a",
    "rgb_r": "rgb.overall.bias.r", "rgb_b": "rgb.overall.bias.b",
}
GROUPS = {
    "quality": "품질·미감·연도", "detail": "복잡도·디테일·깊이",
    "color": "색·팔레트", "lightness": "밝기·대비", "lighting": "조명",
    "line": "선", "surface": "면·채색·질감", "skin": "피부·신체 질감",
    "face": "얼굴·눈·머리카락 세부", "space": "배경·공간·광학",
    "weather": "시간·날씨(장면형)", "negative": "열화·오류 억제",
}
# tag | Korean label | intended positive-prompt change | risk | metric:direction
# Every unmeasured effect is a hypothesis, not a claim of V5 efficacy.
SEEDS = {
"quality": """
masterpiece|대표작 조건|완성도·장식 증가를 기대하지만 품질 보장은 아님|high|none
very aesthetic|높은 미감 조건|미감 조건으로 소품·채색 분포 변화|high|chroma:up
aesthetic|미감 조건|미감 조건의 분포 변화; 점수 다이얼 아님|high|none
top aesthetic|최상 미감 표현|Thumb에만 있는 미감 표현; V5 지원 미확인|high|none
very displeasing|낮은 미감 조건|비선호 미감 분포; 네거티브 연구 재료|high|none
displeasing|비선호 미감|분포 전환; 채도 감소로 단정 못함|high|none
best quality|최고 품질 조건|선·음영 변화 가능; 기본보다 항상 좋다는 뜻 아님|medium|none
amazing quality|우수 품질 조건|기본 분포와 비슷할 가능성|medium|none
great quality|좋은 품질 조건|기본 분포와 비슷할 가능성|medium|none
normal quality|보통 품질 조건|품질 범주 전환; 구조 변화 가능|high|none
bad quality|낮은 품질 조건|저품질 분포 연구 재료; 권장 포지티브 아님|high|none
worst quality|최저 품질 조건|저품질 분포 연구 재료; 권장 포지티브 아님|high|none
high-quality digital art|디지털 품질 문구|한 시드에서는 거의 무효; 일반 효능 미확인|medium|none
best illustration|최고 일러스트 문구|자연어 완성도 요구; 모델 전용이라고 확정 못함|high|none
highres|고해상도 메타|고해상도 그림 분포 연상; 출력 픽셀 수는 바꾸지 않음|medium|none
absurdres|초고해상도 메타|원본 해상도 메타; 업스케일 기능 아님|medium|none
no text|글자 배제 조건|문자 없는 출력을 기대; 문자 검사는 별도|medium|none
""",
"detail": """
low complexity|낮은 복잡도|표현을 단순하고 평평하게|medium|sharpness:down
medium complexity|중간 복잡도|기본에 가까운 복잡도 조건|medium|none
high complexity|높은 복잡도|선 대비·고주파·장식 증가|high|line_contrast:up
ultra complexity|초고복잡도|고주파·여러 크기의 대비 증가|high|sharpness:up
depthness|음영 깊이|어두운 면·깊은 음영 증가 가설; DOF와 같지 않음|high|dark_share:up
detailed background|배경 상세 문구|배경 묘사 밀도 증가를 요구; 영점에서는 음수|high|none
simple illustration|단순 일러스트 문구|묘사 단순화 가설; 음수 효과 별도 미검증|high|sharpness:down
absurdly detailed composition|고밀도 구도|조밀한 구성·묘사; 내용까지 늘 수 있음|high|sharpness:up
""",
"color": """
grey theme|회색 테마|채도 감소; 가중치에 따라 스위치 전환|high|chroma:down
colorful|다채로운 색|여러 색·배경 교체; 채도 증가 보장 없음|high|hue_entropy:up
muted color|차분한 색|색의 강도 감소 가설; 밝기와 함께 변할 수 있음|medium|chroma:down
pale color|옅은 색|옅은 팔레트; 채도와 밝기는 별개|medium|chroma:down
pastel colors|파스텔|파스텔 계열 팔레트·부드러운 색면|high|chroma:down
limited palette|제한 팔레트|사용 색 종류 제한; 저채도와 같지 않음|high|hue_entropy:down
spot color|포인트 색|흑백 바탕에 제한적 색|high|neutral_share:up
partially colored|부분 채색|일부 영역만 채색|high|neutral_share:up
monochrome|단색계|단색 계열; 반드시 흑백은 아님|high|hue_entropy:down
greyscale|회색조|회색 명암 표현|high|chroma:down
sepia|세피아|갈색·누런 계열 색조|high|yellow:up
warm colored|따뜻한 색|따뜻한 팔레트; b*만으로 전체 온도 못 봄|medium|yellow:up
cool colored|차가운 색|차가운 팔레트 가설|medium|yellow:down
saturated|높은 채도|강한 채도 가설; 효과 별도 검증|medium|chroma:up
neon palette|네온 팔레트|네온 색 분포; 광원 추가 가능|high|chroma:up
analogous colors|유사색|이웃 색상 조합|high|hue_entropy:down
inverted colors|색 반전|반전 색 표현; 개선 기본값 아님|high|none
blue theme|파랑 테마|파랑 우세; 배경·의상 변경 가능|high|rgb_b:up
pink theme|분홍 테마|분홍 우세; 다른 원색으로 치환 가능|high|rgb_r:up
red theme|빨강 테마|빨강 우세|high|rgb_r:up
purple theme|보라 테마|보라 우세|high|none
green theme|초록 테마|초록 우세|high|none
yellow theme|노랑 테마|노랑 우세|high|yellow:up
orange theme|주황 테마|주황 우세|high|yellow:up
brown theme|갈색 테마|갈색 우세|high|none
aqua theme|청록 테마|청록 우세|high|none
pale colors|옅은 색 별칭|pale color와 중복 선택하지 않음|medium|chroma:down
""",
"lightness": """
black theme|검정 테마|검정 우세; 검은 의상·배경까지 변경|high|lightness:down
white theme|흰색 테마|흰색 우세; 의상까지 흰색으로 변경|high|lightness:up
dark|어두운 표현|어두운 장면·정서 가설|high|lightness:down
dim lighting|희미한 조명|어두운 조명 가설; 광원 재구성|high|lightness:down
high contrast|강한 명암 대비|전체 명암 대비 증가 가설; 채도 손잡이 아님|high|lightness_std:up
chiaroscuro|명암법|강한 명암·어두운 배경으로 장면 전환|high|lightness_std:up
overexposure|과노출|밝은 영역·클리핑 증가 가설|high|lightness:up
""",
"lighting": """
backlighting|역광|뒤쪽 광원·인물 윤곽의 밝기 변화|high|none
sidelighting|측광|옆쪽 광원·명암 방향 변화|high|none
underlighting|아래 조명|아래쪽 광원·얼굴 음영 변화|high|none
sunlight|햇빛|태양광 조명; 야외 장면 추가 가능|high|lightness:up
dappled sunlight|얼룩 햇빛|수목 사이 빛·점박이 음영|high|none
light rays|빛줄기|빛의 경로·광선 추가|high|none
sunbeam|햇살 줄기|태양광의 빛줄기|high|none
moonlight|달빛|달 광원·야간 색조|high|none
bloom|빛 번짐|밝은 경계 주변 광학 번짐|medium|sharpness:down
lens flare|렌즈 플레어|광원 주변 플레어 패턴 추가|high|none
spotlight|집중 조명|좁은 조명·무대 연상|high|lightness_std:up
colored shadow|유색 그림자|그림자에 색을 부여|medium|none
shadow|그림자|그림자 면·광원 변경|high|dark_share:up
shaded face|얼굴 그림자|얼굴을 가리는 음영; 표정도 달라질 수 있음|high|none
soft lighting|부드러운 조명 문구|부드러운 명암 경계를 자연어로 요구|high|lightness_std:down
cinematic lighting|영화적 조명 문구|장면형 조명 요구; 한 축 다이얼 아님|high|none
volumetric lighting|체적 조명 문구|안개 속 광선·공기감 요구|high|none
""",
"line": """
jaggy lines|거친 선|선 대비 증가를 노린 사용자 조합 재료|medium|line_contrast:up
black outline|검정 외곽선|검고 굵은 경계 유도|medium|line_contrast:up
thick outlines|굵은 외곽선|굵은 선; 음수 프롬프트로 가늘게 연구|medium|line_width:up
thick lineart|굵은 선화|두꺼운 선화 가설; 외곽선과 완전 동치 아님|medium|line_width:up
no lineart|무선화|선 없는 면 표현; 굵기 지표를 속일 수 있음|high|line_contrast:down
lineart|선화|채색 없는 선화로 전환할 위험|high|none
outline|외곽선|외곽 경계 추가; 스티커형 윤곽 위험|medium|none
colored lineart|유색 선화|검정이 아닌 색 선|medium|none
white outline|흰 외곽선|스티커 같은 흰 경계|high|none
sketch|스케치|미완성·초벌 선 스타일|high|none
thin lineart|얇은 선화 문구|얇은 선을 요구; 실제 태그·효과 미확인|medium|line_width:down
""",
"surface": """
anime coloring|애니 채색|애니식 채색; cel shading (2d)의 정식 대상|high|none
cel shading (2d)|애니 채색 별칭|anime coloring과 중복 선택하지 않음|high|none
cel shading|폐기 셀 셰이딩|deprecated; 활성 별칭 없는 경우 자동 치환하지 않음|high|none
flat color|평면 채색|그림자·하이라이트·그라데이션 없는 색면|high|lightness_std:down
blending|색 혼합|색·음영 경계 혼합|medium|sharpness:down
hatching (texture)|해칭|평행선으로 면을 묘사|high|grain:up
crosshatching|교차 해칭|겹친 선 음영|high|grain:up
brush stroke|붓 자국|붓결 표면 묘사|high|grain:up
painterly|회화적 면|붓질·회화적 면; 구조 재해석 가능|high|none
impasto|두꺼운 물감|돌출된 물감 질감|high|grain:up
paper texture|종이 질감|종이 표면 패턴 추가|medium|grain:up
canvas texture|캔버스 질감|직물 결 표면 추가|medium|grain:up
halftone|망점|망점 패턴 추가; UC 충돌|medium|grain:up
dithering|디더링|제한색 근사 점패턴; UC 충돌|medium|grain:up
screentones|스크린톤|만화 톤 패턴; 공식 메모 단수와 구별|high|grain:up
watercolor (medium)|수채 매체|수채 번짐·투명층 표현|high|none
graphite (medium)|흑연 매체|연필 선·흑백 재질 표현|high|none
oil painting (medium)|유화 매체|유화식 면·붓질 분포|high|none
realistic|실사적 스타일|형태·채색을 실사 쪽으로 재해석|high|none
3d|3D 스타일|입체 렌더링 분포; 그림체 전환|high|none
""",
"skin": """
shiny skin|피부 광택|피부의 반사 하이라이트; 피부 ROI 필요|low|none
silky skin|매끈한 피부 문구|부드러운 피부 표면 요구; 효능 미검증|low|none
detailed skin texture|상세 피부 문구|피부 표면 세부 요구; 모공 추가 보장 없음|medium|none
natural skin tone|자연 피부색 문구|피부색 자연스러움 요구; 정답색 없음|medium|none
oiled|오일 코팅|기름칠된 표면·광택; 신체 외 영역도 가능|medium|none
oil|폐기 오일 태그|deprecated; oiled로 무조건 동치 취급 금지|high|none
sweat|땀|피부 땀방울·젖음; 운동·긴장 맥락 추가 가능|medium|none
sweatdrop|땀방울 기호|표면 물방울이 아니라 표정 연출일 수 있음|high|none
wet|젖음|피부·머리·옷의 젖음; 장면 변경 위험|high|none
water drops|물방울|표면 방울; 땀과 구별 안 될 수 있음|medium|none
skindentation|피부 눌림|옷·끈 접촉의 국소 눌림; 체형 변경 가능|high|none
veins|혈관|혈관 선 표현; 근육·긴장과 공변|high|none
muscular|근육 체형|근육량·형태 변경; 단순 피부 질감 아님|high|none
muscle|근육 별칭|muscular로 정규화; 질감 다이얼 아님|high|none
wrinkled skin|주름진 피부|피부 주름; 나이·형태 변경 위험|high|none
tan|태닝|피부색을 어둡게; 품질 개선과 별개|high|none
tanlines|태닝 경계|노출·의상 경계에 따른 피부색 차이|high|none
pale skin|창백한 피부|옅은 피부색; 노출 보정과 별개|high|none
dark skin|어두운 피부|피부색 변경; 품질 척도 아님|high|none
freckles|주근깨|피부 점무늬 추가; 세밀함 점수와 별개|medium|none
mole|점|국소 점 추가; 결함으로 자동 제거 금지|medium|none
goosebumps|소름|돌기 표면 요구; 미검증|medium|none
stretch marks|튼살|피부 선무늬·체형 맥락; 오류로 간주 금지|high|none
cellulite|셀룰라이트|피부 요철; 품질 개선의 반대라고 간주 금지|high|none
translucent skin|반투명 피부|투과 피부·내부 표현; 판타지 변형 위험|high|none
glowing skin|발광 피부|자체 발광; 자연 반사광과 다름|high|none
cracked skin|갈라진 피부|갈라짐 표현; 마른 피부·판타지 재질 모두 가능|high|none
cum on body|성인 피부 위 체액|성인 몸 표면의 체액·반사; 내용 추가 항목|high|none
cum on breasts|성인 가슴 위 체액|성인 가슴 표면의 체액; 광택 손잡이와 분리|high|none
erect nipples|성인 유두 형태|성인 신체의 국소 돌출 형태; 질감·품질 아님|high|none
puffy nipples|성인 유두 입체감|성인 유두의 볼륨 형태; 해부 내용 변경|high|none
areolae|성인 유륜 표현|성인 유륜 형태·색; 전신 지표 없음|high|none
""",
"face": """
detailed eyes|눈 상세 문구|홍채·눈 묘사 세부 요구; 0건 이름만으로 학습 태그 아님|medium|none
eyelashes|속눈썹|속눈썹 추가·강조; 내용 세부|medium|none
glossy lips|입술 광택 문구|국소 입술 하이라이트 요구|low|none
lip gloss|립글로스|화장·반사광 추가; 입술 형태까지 변화 가능|medium|none
shiny hair|폐기 머리 광택|deprecated 이름; 모델 효능과 태그 상태는 별개|medium|none
hair shine|머리카락 광택|머리 반사 밴드·하이라이트|low|none
hair highlights|머리 하이라이트|반사광 또는 염색선의 중의성; 재질로 단정 금지|high|none
eye reflection|눈 반사|눈 표면 반사·내용 반영|medium|none
glowing eyes|발광 눈|자체 발광; 눈 세밀함 증가와 다름|high|none
""",
"space": """
depth of field|피사계 심도|초점 영역·거리별 흐림|high|none
blurry background|배경 흐림|배경 고주파를 낮춤; 전신 선명도와 반대 아님|medium|sharpness:down
bokeh|보케|초점 밖 빛 원반 추가|high|none
scenery|풍경 중심|배경의 비중·장면 전환|high|none
simple background|단순 배경|배경 밀도를 줄임; 인물 품질과 별개|high|none
white background|흰 배경|배경을 흰색으로; 명도 평균에 큰 영향|high|lightness:up
gradient background|그라데이션 배경|배경 색·밝기 경사|high|none
atmospheric perspective|대기 원근|거리별 대비·색 변화; 구도 영향|high|none
film grain|필름 그레인|전역 미세 잡음; 공식 UC 메모와 충돌|medium|grain:up
chromatic aberration|색수차|경계의 채널 어긋남; 공식 UC 메모와 충돌|medium|none
soft focus|소프트 포커스|흐릿한 초점·낮은 국소 대비|medium|sharpness:down
motion blur|움직임 흐림|방향성 흐림·동작 변경|high|sharpness:down
vignetting|비네팅|가장자리 어둡게; 인물 노출 보정 아님|medium|border_lightness:down
""",
"weather": """
day|낮|낮 시간의 장면·조명|high|lightness:up
night|밤|야간 장면·조명|high|lightness:down
sunset|일몰|일몰 색·시간·배경|high|yellow:up
blue sky|푸른 하늘|하늘 내용 추가; 전역 색온도 다이얼 아님|high|rgb_b:up
cloudy sky|흐린 하늘|하늘·구름 분포|high|none
fog|안개|장면의 저주파 흐림·대비 완화|high|lightness_std:down
rain|비|비·젖음·날씨 맥락|high|none
snow|눈|하얀 눈 풍경·입자|high|lightness:up
outdoors|야외|야외 장소 조건; 관찰 교란용도|high|none
indoors|실내|실내 장소 조건; 관찰 교란용도|high|none
""",
"negative": """
lowres|저해상도 표현 억제|낮은 해상도 느낌 분포; 출력 크기와 별개|medium|none
bad anatomy|해부 오류 억제|잘못된 신체 구조 표현; 픽셀 지표로 정오 판정 불가|high|none
artistic error|그림 오류 억제|그림 오류 범주; 포괄적 무결성 보장 아님|high|none
jpeg artifacts|JPEG 흔적 억제|압축 블록·링잉 표현|medium|none
bad hands|손 오류 억제|손 구조 오류 범주; 손가락 수 보장 아님|high|none
extra digits|추가 손발가락 억제|추가 손발가락 형태 억제 요구|high|none
missing fingers|손가락 누락 억제|손가락 누락 표현 억제 요구|high|none
scan artifacts|스캔 흔적 억제|스캔 얼룩·노이즈 표현|medium|grain:up
aliasing|계단 현상 억제|경계 계단 표현|medium|none
color banding|색 띠 억제|계조 띠·색 단계|medium|none
watermark|워터마크 억제|저작표시 내용 억제; 제거 기능 아님|high|none
text|문자 억제|문자 내용 억제; OCR 없이 성공 판단 어려움|high|none
screentone|공식 메모 단수 톤|screentones와 활성 별칭 관계 없음; 모델 반응 미확인|medium|grain:up
white haze|공식 메모 흰 안개|자연어 안개 표현; 공식 메모 인용에 한정|medium|none
""",
}
NAI_ONLY = set("masterpiece|very aesthetic|aesthetic|very displeasing|displeasing|best quality|amazing quality|great quality|normal quality|bad quality|worst quality|high-quality digital art|no text|low complexity|medium complexity|high complexity|ultra complexity|depthness".split("|"))
NATURAL = set("top aesthetic|best illustration|detailed background|simple illustration|soft lighting|cinematic lighting|volumetric lighting|thin lineart|silky skin|detailed skin texture|natural skin tone|detailed eyes|glossy lips|screentone|white haze".split("|"))
CONTROL_TAGS = "white background|simple background|gradient background|blurry background|outdoors|indoors|day|night|sunset|blue sky|cloudy sky|upper body|cowboy shot|full body|close-up|portrait|1girl|1boy|2girls|solo|multiple girls|dark skin|pale skin|tan|sweat|wet|black hair|white hair|black dress|white dress|black shirt|white shirt".split("|")
ADULT = {"cum on body", "cum on breasts", "erect nipples", "puffy nipples", "areolae"}


def norm(tag):
    return " ".join(tag.replace("_", " ").casefold().split())


MARKER = re.compile(r"(?P<weight>[+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*::|(?P<close>::)|(?P<comma>,)")


def parse_prompt(text):
    """Subset used by this corpus: comma tags + nested numeric :: groups.

    Return all occurrences, including zero and negative weights (not absence).
    Reject brace syntax rather than silently misclassifying unsupported syntax.
    """
    if any(x in text for x in "{}[]"):
        raise ValueError("brace/bracket weighting requires a separate parser")
    stack, tokens, cursor = [], [], 0

    def emit(end):
        tag = norm(text[cursor:end])
        if tag:
            tokens.append((tag, math.prod(stack)))

    for m in MARKER.finditer(text):
        # A numeric suffix before a closing :: (artist:foo95 ::,
        # artist:labo 9696 ::) is part of the tag, NOT a new weight.
        numeric_tail_close = bool(m.group("weight") and text[cursor:m.start()].strip())
        if numeric_tail_close:
            emit(m.end("weight"))
        else:
            emit(m.start())
        if m.group("weight") and not numeric_tail_close:
            stack.append(float(m.group("weight")))
        elif m.group("close") or numeric_tail_close:
            if not stack:
                raise ValueError("unmatched weight close")
            stack.pop()
        cursor = m.end()
    emit(len(text))
    if stack:
        raise ValueError("unclosed weight group")
    return tokens


def json_read(rel):
    with (ROOT / rel).open(encoding="utf-8") as f:
        return json.load(f)


def jsonl_read(rel):
    with (ROOT / rel).open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def write_json(path, obj):
    with path.open("x", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2, allow_nan=False)
        f.write("\n")


def write_csv(path, rows):
    with path.open("x", encoding="utf-8", newline="\n") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def safe_num(x):
    return round(float(x), 8) if np.isfinite(x) else None


def get_metric(obj, key):
    for part in key.split("."):
        obj = obj.get(part) if isinstance(obj, dict) else None
    return float(obj) if isinstance(obj, (int, float)) and not isinstance(obj, bool) else np.nan


def load_pairs():
    p, m = jsonl_read(PROMPTS), jsonl_read(MEASUREMENTS)
    if len(p) != len(m) or len(p) != 4054:
        raise ValueError(f"expected 4054 aligned lines, got {len(p)} / {len(m)}")
    paths = set()
    for i, (a, b) in enumerate(zip(p, m), 1):
        if a["path"] != b["path"] or a["file"] != b["file"]:
            raise ValueError(f"line {i}: path/file mismatch")
        if a["path"] in paths:
            raise ValueError("duplicate image path")
        paths.add(a["path"])
        if "result" not in b or "error" in b:
            raise ValueError("failed measurement")
        image = b["result"]["image"]
        if (a["width"], a["height"]) != (image["width"], image["height"]):
            raise ValueError("dimension mismatch")
    return p, m


def lexicon():
    counts = json_read(COUNTS)
    snap = {}
    for row in pq.read_table(ROOT / SNAP, columns=["name", "category", "post_count", "is_deprecated"]).to_pylist():
        snap[norm(row["name"])] = row
    aliases = {norm(r["antecedent_name"]): norm(r["consequent_name"])
               for r in pq.read_table(ROOT / ALIASES, columns=["antecedent_name", "consequent_name", "status"]).to_pylist()
               if r["status"] == "active"}
    return counts, snap, aliases


def canonical(tag, aliases):
    seen = set()
    while tag in aliases:
        if tag in seen:
            raise ValueError("alias cycle")
        seen.add(tag)
        tag = aliases[tag]
    return tag


def corpus_count(tag, counts):
    # Missing from autocomplete's sparse index is unknown, NOT zero.
    value = counts.get(tag.replace(" ", "_"))
    if value is None:
        value = counts.get(tag)
    return sum(value) if isinstance(value, list) else None


def base_catalog(counts, snap, aliases):
    thumb = json_read(THUMB)["categories"]
    axis = json_read(AXES)["axes"]
    thumb_tags = {norm(t) for c in thumb.values() for t in c["tags"]}
    zero = dict(parse_prompt(ZERO_PROMPT))
    bench_negative = json_read(BENCH)[0]["negative"]
    baseline_uc = {t for t, w in parse_prompt(bench_negative) if w > 0}
    items = []
    seeds = dict(SEEDS)
    seeds["quality"] += "\n" + "\n".join(
        f"year {y}|연도 {y}|게시 연도 조건; 이웃 연도 차이는 미검증|high|none" for y in range(2020, 2027))
    for group, block in seeds.items():
        for line in block.strip().splitlines():
            if not line.strip():
                continue
            tag, label, effect, risk, hint = line.strip().split("|")
            tag = norm(tag)
            target = canonical(tag, aliases)
            record = snap.get(tag, {})
            count = corpus_count(tag, counts)
            if tag in aliases:
                kind = "alias"
            elif tag in NAI_ONLY or tag.startswith("year "):
                kind = "nai_only"
            elif tag in NATURAL or (count is None and not record.get("post_count", 0)):
                kind = "natural_language"
            else:
                kind = "danbooru_meta" if record.get("category") == 5 else "danbooru_general"
            level, note, source = "guess", "[추정] 효과·범위는 V5 생성으로 미검증. 의미와 효과를 분리한다.", "본 조사 후보 가설"
            if kind in {"danbooru_general", "danbooru_meta", "alias"}:
                level, note, source = "knowledge", "[지식] 표현의 일반적 의미. V5의 효과·역방향·안전 가중치를 보증하지 않는다.", "일반 표현 지식; 로컬 태그 이름 대조"
            if tag in NAI_ONLY or tag.startswith("year "):
                level, note, source = "recorded", "[기록] 저장소 V5 메모·사다리. 지원·효과의 최신 웹 검증 없음.", f"{MEMO}:61-99; {SURVEY} §12-15"
            ph = [] if hint == "none" else [{"axis": hint.split(":")[0], "direction": hint.split(":")[1], "confidence": "guess", "slot": "prompt"}]
            gap = "지표 없음: 국소 ROI 또는 내용·형태에 대한 사람의 판독이 필요하다" if not ph else "전체 지표의 변화는 국소 개선·내용 보존을 증명하지 않는다"
            if group in {"skin", "face"}:
                gap = "지표 없음: 사용자가 지정한 피부/얼굴/눈/머리 ROI에서 반사·질감·경계 측정이 필요하다"
            negative_effect = "표현 억제를 기대하나 반대 외양·품질 개선을 보장하지 않음; V5 미검증"
            slots = {
                "prompt": {"effect": effect, "weight_range": [0.3, 1.0], "evidence_level": level,
                           "validation": "unvalidated", "range_status": "proposed_test_grid_not_safe_range"},
                "negative": {"effect": negative_effect, "weight_range": [0.5, 1.0], "evidence_level": "guess",
                             "validation": "unvalidated", "range_status": "proposed_test_grid_not_safe_range"},
            }
            default_slot = "negative" if group == "negative" or tag in {"bad quality", "worst quality", "displeasing", "very displeasing", "screentone"} else "prompt"
            deprecated = bool(record.get("is_deprecated"))
            item = {
                "id": re.sub(r"[^a-z0-9]+", "_", tag).strip("_"), "group": group,
                "label_ko": label, "tags": [tag], "kind": kind, "corpus_count": count,
                "corpus_count_status": "indexed_175_shards" if count is not None else "not_in_sparse_index_unknown",
                "alias_of": target if tag in aliases else None,
                "canonical_corpus_count": corpus_count(target, counts),
                "snapshot": {"category": record.get("category"), "site_post_count": record.get("post_count"), "deprecated": deprecated},
                "slots": slots, "axis_hint": ph,
                "measurable": "partial" if ph else "none", "metric_gap": gap,
                "reroll_risk": risk, "reroll_risk_status": "hypothesis_not_measured" , "conflicts": [],
                "in_zero_preset": tag in zero, "zero_preset_weights": [zero[tag]] if tag in zero else [],
                "in_baseline_negative": tag in baseline_uc,
                "official_uc": [], "evidence": {"level": level, "note": note, "source": source},
                "priority": 2 if group in {"skin", "face", "lighting", "line", "surface"} else 3,
                "thumb_member": tag in thumb_tags,
                "interactive_axes": [a for a, ts in axis.items() if tag in {norm(t) for t in ts}],
                "default_slot": default_slot, "adult_only": tag in ADULT,
                "control_type": "slot_selector_and_weight",
                "status": "alias_hidden" if kind == "alias" else "research_hold" if deprecated or tag == "top aesthetic" else "candidate",
                "test_recipe": f"{default_slot}에 {tag} 0.5/1을 각각 한 조건으로; {hint if hint != 'none' else '국소 ROI·사람 판독'}를 관찰, 반대칸의 동일 개념 제거 후 원본과 비교",
            }
            if tag.startswith("year "):
                item["control_type"] = "exclusive_choice"
                item["conflicts"] = [f"year {y}" for y in range(2020, 2027) if f"year {y}" != tag]
            if tag.endswith("complexity") or tag in {"grey theme", "thick outlines"}:
                item["control_type"] = "nonlinear_slot_weight"
            items.append(item)
    by_tag = {x["tags"][0]: x for x in items}
    for family in ["best quality|amazing quality|great quality|normal quality|bad quality|worst quality", "aesthetic|very aesthetic|displeasing|very displeasing", "low complexity|medium complexity|high complexity|ultra complexity"]:
        tags = family.split("|")
        for tag in tags:
            by_tag[tag]["conflicts"] += [x for x in tags if x != tag]
    conflicts = {"flat color": ["depthness", "blending", "shiny skin"], "no lineart": ["jaggy lines", "black outline", "lineart", "thick outlines"],
                 "grey theme": ["negative:grey theme", "colorful", "saturated"], "high contrast": ["negative:high contrast", "soft focus"],
                 "ultra complexity": ["negative:high contrast"], "shiny skin": ["flat color"], "wet": ["sweat", "oiled"],
                 "hair highlights": ["hair shine"], "screentones": ["UC:screentone"], "screentone": ["screentones:NOT_active_alias"],
                 "black theme": ["white theme"], "white theme": ["black theme"]}
    for tag, cs in conflicts.items():
        by_tag[tag]["conflicts"] += cs
    uc = {
        "Heavy": "lowres|artistic error|film grain|scan artifacts|worst quality|bad quality|jpeg artifacts|very displeasing|chromatic aberration|dithering|halftone|screentone|multiple views|logo|too many watermarks|negative space|blank page",
        "Light": "lowres|bad hands|bad anatomy|artistic error|sepia|white haze|worst quality|very displeasing|jpeg artifacts",
        "Human focus": "lowres|artistic error|film grain|scan artifacts|worst quality|bad quality|jpeg artifacts|very displeasing|chromatic aberration|dithering|halftone|screentone|multiple views|logo|too many watermarks|negative space|blank page|@ @|mismatched pupils|glowing eyes|bad anatomy",
    }
    for item in items:
        tag = item["tags"][0]
        item["official_uc"] = [name for name, tags in uc.items() if tag in tags.split("|")]
        if item["official_uc"]:
            item["conflicts"].append("official_UC:" + tag)
            item["official_uc_evidence"] = {"level": "recorded", "source": MEMO + ":76-81", "note": "[기록] 공식 UC라고 저장된 메모; 이번 작업은 웹 확인 안 함"}
    # Existing generation results are quoted as RECORDS, never relabelled as a rerun.
    records = {
        "grey theme": ("§20.4, §20.6", "프롬프트 1: 채도 6/6 하락, 중앙 -64%, 유지 0.70. 네거티브 1: 채도 6/6 상승, +76%, 유지 0.90. 스위치·작가 의존.", "chroma"),
        "high contrast": ("§20", "네거티브: 또렷함 10/10 하락, 중앙 -17%, 유지 0.93. 프롬프트는 채도 손잡이 아님.", "sharpness"),
        "ultra complexity": ("§18", "0.15→0.5: 또렷함 10/10 상승, 중앙 +34, 유지 0.81. 선 대비 9/10, 거칠기 10/10 증가. 한 작가·두 구도.", "sharpness"),
        "high complexity": ("§12, §15", "맨바탕 단일 시드: 선 대비 23.1→33.9; 0.5 이후 선 가파르기 포화. 장식·밝기 함께 변함.", "line_contrast"),
        "low complexity": ("§15", "단일 시드: 양수에서 평평; -0.5에서 붕괴. -0.25 거의 무효. 0≠삭제.", "sharpness"),
        "depthness": ("§12", "단일 시드: 어두운 픽셀 8%→29%. depth of field 상위 버전이라는 메모는 추정.", "dark_share"),
        "jaggy lines": ("§19", "프롬프트 2 + 네거티브 no lineart: evaiyu 선 대비 약20→34~44; 시드 다른 장들이라 태그 단독·인과 미확인.", "line_contrast"),
        "thick outlines": ("§17, §19", "프롬프트 음수 + 네거티브 양수 조합. 같은 시드 tsunderemaids 2.80→1.96; 두 자리 개별 효과 미분리, 선 소실 위험.", "line_width"),
        "sepia": ("§9.3", "네거티브 sepia, warm colored 단일 시드 조합 기록; 누런 기 감소, 다른 축 부작용.", "yellow"),
        "warm colored": ("§9.3", "네거티브 sepia, warm colored 단일 시드 조합 기록; 개별 효과·일반화 미확인.", "yellow"),
    }
    for tag, (section, note, record_axis) in records.items():
        it = by_tag[tag]
        it["priority"] = 1
        it["evidence"] = {"level": "recorded", "note": "[기록] " + note, "source": SURVEY + " " + section}
        it["axis_hint"] = [{"axis": record_axis, "direction": "slot_dependent", "confidence": "recorded", "slot": "see_slots"}]
    by_tag["grey theme"]["slots"]["prompt"].update(effect="[기록] 채도 감소; 0.5↔1 사이 전환점 작가 의존", validation="recorded_6_pairs", evidence_level="recorded", weight_range=[0.25, 1.5])
    by_tag["grey theme"]["slots"]["negative"].update(effect="[기록] 채도 증가; 밝기 감소 가능", validation="recorded_6_pairs", evidence_level="recorded", weight_range=[0.5, 1.5])
    by_tag["high contrast"]["slots"]["negative"].update(effect="[기록] 또렷함·명암 대비 감소; 채도 저하 용도 아님", validation="recorded_10_pairs", evidence_level="recorded")
    by_tag["ultra complexity"]["slots"]["prompt"].update(effect="[기록] 또렷함·거칠기 증가; 재구성 위험", validation="recorded_10_pairs", evidence_level="recorded", weight_range=[0.15, 0.5])
    for tag in ["high complexity", "low complexity", "depthness"]:
        by_tag[tag]["slots"]["prompt"].update(validation="recorded_single_seed", evidence_level="recorded")
    for tag in ["sepia", "warm colored"]:
        by_tag[tag]["slots"]["negative"].update(effect="[기록] 묶음에서 누런 기 감소;単独 미검증".replace("単独", "단독"), validation="recorded_single_seed_bundle", evidence_level="recorded")
    for tag, span in [("high complexity", [-0.5, -0.25]), ("ultra complexity", [-0.5, -0.15]), ("low complexity", [-0.25, -0.25]), ("thick outlines", [-2.5, -1.0]), ("simple illustration", [-0.5, -0.25])]:
        by_tag[tag]["slots"]["prompt_negative_weight"] = {
            "effect": {
                "high complexity": "[기록] 단일 시드: -0.5/-0.25에서 선 대비16.8/21.9로 맨바탕23.1보다 감소; 모든 그림에 대한 역방향 보장 아님",
                "ultra complexity": "[기록] 단일 시드 음수에서 또렷함·선 대비 감소; 그림 재구성 위험, UC high contrast와 동치 아님",
                "low complexity": "[기록] -0.25는 거의 무효; -0.5에서 그림 붕괴. 복잡도 증가 손잡이로 승인하지 않음",
                "thick outlines": "[기록] 양수 UC와 함께 쓴 조합에서 선 굵기 감소; 음수 prompt 단독 효과는 미분리, 선 소실 위험",
                "simple illustration": "[추정] 단순화 억제 가설; V5 미검증",
            }[tag],
            "weight_range": span, "evidence_level": "recorded" if tag != "simple illustration" else "guess",
            "validation": "recorded_single_seed_or_bundle" if tag != "simple illustration" else "unvalidated",
            "range_status": "proposed_test_grid_not_safe_range",
        }
    by_tag["low complexity"]["warnings"] = ["음수 -0.5 이하 금지 제안: 단일 시드 붕괴 기록; -0.25도 개선 보장 없음"]
    by_tag["thick outlines"]["warnings"] = ["음수 프롬프트·양수 UC 조합 증거만 있음", "폭 감소와 선 소실을 분리", "no lineart 포지티브 동시 사용 피함"]
    # Bundles are one item with an explicit recipe, not three proven individual levers.
    bundle = dict(by_tag["black theme"])
    bundle.update(id="brightness_negative_bundle", label_ko="어두운 그림 밝히기 묶음", tags=["black theme", "dark", "muted color"],
                  corpus_count=None, corpus_count_status="bundle_union_not_counted", canonical_corpus_count=None,
                  per_tag_corpus_count={t: corpus_count(t, counts) for t in ["black theme", "dark", "muted color"]},
                  alias_of=None, slots={"negative": {"effect": "[기록] 어두운 그림의 밝기 상승; 배경·의상 교체 가능", "weight_range": [0.5, 1.5], "evidence_level": "recorded", "validation": "recorded_6_pairs", "range_status": "proposed_test_grid_not_safe_range"}},
                  axis_hint=[{"axis": "lightness", "direction": "up", "confidence": "recorded", "slot": "negative"}],
                  priority=1, default_slot="negative", control_type="bundle_recipe", reroll_risk="high", reroll_risk_status="recorded_bundle",
                  evidence={"level": "recorded", "note": "[기록] 밝기 6/6 증가, 중앙 +13.3, 유지 중앙0.76/최저0.20; 개별 몫 미분리", "source": SURVEY + " §20.4"},
                  test_recipe="UC에 black theme, dark, muted color 가중치1 묶음 대 각각 단독; 밝기 상승·의상 유지·채도 부작용을 비교")
    items.append(bundle)
    for tag in ["shiny skin", "oiled", "sweat", "flat color", "blending", "bloom", "hair shine", "detailed skin texture", "detailed eyes"]:
        by_tag[tag]["priority"] = 1
    return items, thumb, axis


def presence_maps(prompts, aliases):
    slots = {"prompt": [], "negative": []}
    weights = {"prompt": [], "negative": []}
    for p in prompts:
        for slot, field in [("prompt", "prompt"), ("negative", "uc")]:
            d = {}
            for tag, w in parse_prompt(p[field]):
                tag = canonical(tag, aliases)
                d.setdefault(tag, []).append(w)
            weights[slot].append(d)
            slots[slot].append({t for t, ws in d.items() if any(w > 0 for w in ws)})
    return slots, weights


def demean(a, codes, ng):
    if a.ndim == 1:
        return a - (np.bincount(codes, weights=a, minlength=ng) / np.bincount(codes, minlength=ng))[codes]
    return np.column_stack([demean(a[:, j], codes, ng) for j in range(a.shape[1])])


def cluster_fit(rx, ry, codes, ng, rank):
    ss = float(rx @ rx)
    if ss < 1e-9:
        return (None,) * 5
    beta = float(rx @ ry / ss)
    e = ry - beta * rx
    score = np.bincount(codes, weights=rx * e, minlength=ng)
    g = int(np.count_nonzero(np.bincount(codes, minlength=ng) > 1))
    if g < 2 or len(rx) <= ng + rank + 1:
        return beta, None, None, None, None
    variance = (score @ score / ss ** 2) * (g / (g - 1)) * ((len(rx) - 1) / (len(rx) - ng - rank - 1))
    se = math.sqrt(max(0.0, float(variance)))
    if se == 0:
        return beta, None, None, None, None
    critical = stats.t.ppf(.975, g - 1)
    return beta, se, beta - critical * se, beta + critical * se, 2 * stats.t.sf(abs(beta / se), g - 1)


def adjust_q(rows, pkey, qkey):
    subset = [(i, r[pkey]) for i, r in enumerate(rows) if r[pkey] is not None]
    subset.sort(key=lambda p: p[1])
    q, n = 1.0, len(subset)
    for rank in range(n, 0, -1):
        i, p = subset[rank - 1]
        q = min(q, p * n / rank)
        rows[i][qkey] = safe_num(q)


def observe(items, prompts, measurements, aliases):
    slots, weights = presence_maps(prompts, aliases)
    artists = [p["artist"] for p in prompts]
    _, artist_codes = np.unique(artists, return_inverse=True)
    y_all = np.array([[get_metric(m["result"], k) for k in METRICS.values()] for m in measurements])
    reliable = np.array([m["result"]["lines"].get("width_reliable", False) for m in measurements])
    tags = sorted({canonical(t, aliases) for it in items for t in it["tags"]})
    universe = Counter(t for s in slots["prompt"] for t in s if not t.startswith("artist:"))
    cotags, rows = {}, []
    controls = np.array([[float(t in s) for t in CONTROL_TAGS] for s in slots["prompt"]])
    for slot in ["prompt", "negative"]:
        other = "negative" if slot == "prompt" else "prompt"
        for tag in tags:
            x_all = np.array([float(tag in s) for s in slots[slot]])
            # Never interpret zero/negative weighted mentions as untreated, nor
            # simultaneous opposite-slot mentions as a clean single-slot contrast.
            ambiguous = np.array([any(w <= 0 for w in d.get(tag, [])) for d in weights[slot]])
            opposite = np.array([tag in s for s in slots[other]])
            eligible = ~ambiguous & ~opposite
            exposed = x_all.astype(bool) & eligible
            unexposed = ~x_all.astype(bool) & eligible
            ne, nu = int(exposed.sum()), int(unexposed.sum())
            cw = Counter(w for d in weights[slot] for w in d.get(tag, []))
            key = f"{slot}:{tag}"
            if slot == "prompt" and ne and nu:
                co = []
                for co_tag, total in universe.items():
                    if co_tag == tag or total < 20:
                        continue
                    both = sum(co_tag in s for s, yes in zip(slots["prompt"], exposed) if yes)
                    absent_both = sum(co_tag in s for s, yes in zip(slots["prompt"], unexposed) if yes)
                    delta = both / ne - absent_both / nu
                    if both >= 5 and delta > 0:
                        co.append({"tag": co_tag, "both": both, "p_if_present": safe_num(both / ne),
                                   "p_if_absent": safe_num(absent_both / nu), "prevalence_difference": safe_num(delta)})
                cotags[key] = sorted(co, key=lambda r: (-r["prevalence_difference"], r["tag"]))[:8]
            for j, axis in enumerate(METRICS):
                keep = eligible & np.isfinite(y_all[:, j])
                if axis == "line_width":
                    keep &= reliable
                x, y = x_all[keep], y_all[keep, j]
                _, codes = np.unique(artist_codes[keep], return_inverse=True)
                ng = len(np.unique(codes))
                a, b = y[x > 0], y[x == 0]
                row = {"tag": tag, "slot": slot, "axis": axis, "n_present": len(a), "n_absent": len(b),
                       "excluded_nonpositive": int(ambiguous.sum()), "excluded_opposite_slot": int(opposite.sum()),
                       "excluded_missing_or_unreliable": int((eligible & ~keep).sum()),
                       "weights": json.dumps(sorted(cw.items())), "status": "estimable" if len(a) >= 2 and len(b) >= 2 else "no_contrast_or_too_few",
                       "mean_present": safe_num(a.mean()) if len(a) else None,
                       "mean_absent": safe_num(b.mean()) if len(b) else None,
                       "delta_mean": None, "delta_median": None, "global_sd_effect": None,
                       "welch_low": None, "welch_high": None, "welch_p": None, "welch_q_bh": None,
                       "informative_artists": 0, "within_beta": None, "within_low": None, "within_high": None,
                       "adjusted_beta": None, "adjusted_low": None, "adjusted_high": None, "adjusted_p": None, "adjusted_q_bh": None,
                       "controls_rank": None, "support_flag": "insufficient", "interpretation": "association_not_causal"}
                if row["status"] == "estimable":
                    delta = float(a.mean() - b.mean())
                    v1, v0 = a.var(ddof=1) / len(a), b.var(ddof=1) / len(b)
                    se = math.sqrt(v1 + v0)
                    df = (v1 + v0) ** 2 / (v1 ** 2 / (len(a) - 1) + v0 ** 2 / (len(b) - 1))
                    critical = stats.t.ppf(.975, df)
                    row.update(delta_mean=safe_num(delta), delta_median=safe_num(np.median(a) - np.median(b)),
                               global_sd_effect=safe_num(delta / y.std(ddof=1)), welch_low=safe_num(delta - critical * se),
                               welch_high=safe_num(delta + critical * se), welch_p=safe_num(2 * stats.t.sf(abs(delta / se), df)))
                    wx, wy = demean(x, codes, ng), demean(y, codes, ng)
                    informative = int(np.count_nonzero(np.bincount(codes, weights=wx ** 2, minlength=ng) > 1e-9))
                    row["informative_artists"] = informative
                    wb = cluster_fit(wx, wy, codes, ng, 0)
                    row.update(within_beta=safe_num(wb[0]) if wb[0] is not None else None,
                               within_low=safe_num(wb[2]) if wb[2] is not None else None, within_high=safe_num(wb[3]) if wb[3] is not None else None)
                    # Controls are a sensitivity analysis, not a causal adjustment:
                    # background/shot tags may also be mediators.
                    z = demean(controls[keep][:, [i for i, t in enumerate(CONTROL_TAGS) if t != tag]], codes, ng)
                    u, singular, _ = np.linalg.svd(z, full_matrices=False)
                    rank = int(np.count_nonzero(singular > 1e-8))
                    basis = u[:, :rank]
                    rx, ry = wx - basis @ (basis.T @ wx), wy - basis @ (basis.T @ wy)
                    ab = cluster_fit(rx, ry, codes, ng, rank)
                    row.update(adjusted_beta=safe_num(ab[0]) if ab[0] is not None else None,
                               adjusted_low=safe_num(ab[2]) if ab[2] is not None else None,
                               adjusted_high=safe_num(ab[3]) if ab[3] is not None else None,
                               adjusted_p=safe_num(ab[4]) if ab[4] is not None else None, controls_rank=rank,
                               support_flag="adequate_descriptive" if len(a) >= 20 and len(b) >= 20 and informative >= 10 else "sparse_descriptive")
                rows.append(row)
    adjust_q(rows, "welch_p", "welch_q_bh")
    adjust_q(rows, "adjusted_p", "adjusted_q_bh")
    summary = {
        "schema": "tone-tuner-observation.v1", "n_pairs": len(prompts), "alignment": "all_lines_path_file_dimensions_equal_unique_paths",
        "artists": len(set(artists)), "artist_image_counts": dict(sorted(Counter(Counter(artists).values()).items())),
        "same_seed_counts": dict(sorted(Counter(Counter(p["seed"] for p in prompts).values()).items())),
        "settings": {k: sorted({str(p[k]) for p in prompts}) for k in ["width", "height", "steps", "scale", "sampler"]},
        "line_width_unreliable": int((~reliable).sum()), "tag_count": len(tags), "metric_count": len(METRICS),
        "metric_missing": {axis: int((~np.isfinite(y_all[:, j])).sum()) for j, axis in enumerate(METRICS)},
        "effect_rows": len(rows), "estimable_rows": sum(r["status"] == "estimable" for r in rows),
        "adjusted_estimable_rows": sum(r["adjusted_p"] is not None for r in rows),
        "adequate_rows": sum(r["support_flag"] == "adequate_descriptive" for r in rows),
        "controls": CONTROL_TAGS, "method": "presence_positive_weight; Welch descriptive CI; artist fixed effects; co-tag sensitivity FWL; artist-cluster CR1 t CI; BH across all estimable tag-slot-axis tests",
        "warning": "No causal claim. No same-seed intervention. Artists repeat and can confound. Sparse/constant UC and preset tokens have no contrast. CI is exploratory.",
        "lightness_border_pearson": safe_num(np.corrcoef(y_all[:, 0], y_all[:, list(METRICS).index('border_lightness')])[0, 1]),
        "global_means": {axis: safe_num(np.nanmean(y_all[:, j])) for j, axis in enumerate(METRICS)},
        "observed_candidate_counts": {t: {s: sum(t in ts for ts in slots[s]) for s in slots} for t in tags},
    }
    for item in items:
        target = canonical(item["tags"][0], aliases)
        if len(item["tags"]) != 1:
            continue
        matches = [r for r in rows if r["tag"] == target and r["status"] == "estimable"]
        item["observation"] = {
            "evidence_level": "measured", "scope": "association_only_not_generated_effect",
            "n_prompt_positive": summary["observed_candidate_counts"][target]["prompt"],
            "n_negative_positive": summary["observed_candidate_counts"][target]["negative"],
            "estimable_axes_slots": len(matches), "source": "observational_effects.csv",
        }
    return rows, cotags, summary


def audit(items, thumb, axis, counts, snap, aliases):
    candidates = {t for it in items for t in it["tags"]}
    rows = []
    for group, category in thumb.items():
        for raw in category["tags"]:
            tag = norm(raw)
            rec = snap.get(tag, {})
            if tag in candidates:
                decision, reason = "catalog", "후보/보류 상태는 catalog 참조"
            elif group == "named_style":
                decision, reason = "exclude_from_tuner", "작가·프랜차이즈·양식 선택: 국소 보정과 분리"
            elif group == "era_style":
                decision, reason = "exclude_from_tuner", "시대 화풍 전환; 연도 조건은 2020년 이후만 별도"
            elif group == "digital_3d" or tag.endswith("(medium)"):
                decision, reason = "advanced_defer", "도구/매체 전체 전환; 중복 저위험 보정이 아님"
            elif rec.get("is_deprecated") or tag in aliases:
                decision, reason = "alias_or_deprecated_review", "활성 별칭/폐기 상태 대조 후 결정; 자동 동치 금지"
            elif group in {"art_style", "genre_and_type"}:
                decision, reason = "advanced_defer", "그림체·출처 유형의 전면 변경; 개선 정답 아님"
            else:
                decision, reason = "advanced_defer", "세부 표현/내용/관리 흔적; 우선 손잡이의 좁은 검증 뒤 검토"
            rows.append({"thumb_category": group, "tag": tag, "corpus_count": corpus_count(tag, counts),
                         "active_alias_of": aliases.get(tag), "deprecated": bool(rec.get("is_deprecated")), "decision": decision, "reason": reason})
    skin = []
    for raw in axis["skin"]:
        tag = norm(raw)
        selected = tag in candidates
        skin.append({"tag": tag, "corpus_count": corpus_count(tag, counts), "decision": "catalog" if selected else "content_palette_or_morphology_defer",
                     "reason": "질감/피부색 후보; catalog에서 내용 변경 표시" if selected else "피부색·노출 경계·털/비늘/금속 등 내용 변경; 성인 여부 때문에 제외한 것이 아님"})
    return rows, skin


def validate_catalog(catalog):
    items = catalog["items"]
    assert len({it["id"] for it in items}) == len(items)
    for it in items:
        assert it["kind"] in {"danbooru_general", "danbooru_meta", "alias", "nai_only", "natural_language"}
        assert it["priority"] in {1, 2, 3}
        assert it["evidence"]["level"] in {"measured", "recorded", "knowledge", "guess", "community"}
        assert it["measurable"] in {"yes", "partial", "none"}
        for slot, data in it["slots"].items():
            lo, hi = data["weight_range"]
            assert lo <= hi
            if slot == "negative":
                assert lo > 0
            if slot == "prompt_negative_weight":
                assert hi < 0
        for t in it["tags"]:
            if t.startswith("year "):
                assert int(t.split()[1]) >= 2020
    return len(items)


def run(out):
    out = out.resolve()
    allowed = (ROOT / "docs/tone_tuner_2026_10_04").resolve()
    if out != allowed and allowed not in out.parents:
        raise ValueError("output must stay under docs/tone_tuner_2026_10_04")
    names = ["catalog_draft.json", "observational_effects.csv", "co_tags.json", "observational_summary.json", "thumb_audit.csv", "skin_axis_audit.csv", "group_tables.md"]
    if any((out / n).exists() for n in names):
        raise FileExistsError("create-only: choose a fresh --out directory")
    prompts, measurements = load_pairs()
    counts, snap, aliases = lexicon()
    items, thumb, axis = base_catalog(counts, snap, aliases)
    rows, cotags, summary = observe(items, prompts, measurements, aliases)
    thumb_rows, skin_rows = audit(items, thumb, axis, counts, snap, aliases)
    sources = [PROMPTS, MEASUREMENTS, COUNTS, SNAP, ALIASES, THUMB, AXES, SURVEY, MEMO, BENCH, "core/image_tone_advisor.py", "core/image_tone_reference.py", "core/image_tone_inspector.py"]
    hashes = {rel: hashlib.sha256((ROOT / rel).read_bytes()).hexdigest() for rel in sources}
    catalog = {
        "schema": "naia.tone-tuner.catalog-draft.v1", "date": "2026-10-04", "model_scope": "NAI V5; offline research draft; no generation",
        "groups": GROUPS, "count_scope": counts["_meta"], "source_sha256": hashes,
        "policies": {"zero": "remove_all_owned_occurrences_not_weight_zero", "negative_weight_in_uc": "never",
                     "ranges": "test_proposals_not_calibrated_safe_ranges", "slot_semantics": "negative_not_guaranteed_inverse; per_slot_evidence",
                     "aliases": "active_only; preserve_original_text; hidden_alias_entries_not_independent_controls",
                     "missing_count": "null_is_not_zero; snapshot_site_post_count_is_separate_population",
                     "unlisted_slots": "unvalidated_not_proposed; no_claim_of_no_effect_or_equivalence_to_negative",
                     "age_scope": "adult surface vocabulary retained; no sexual content involving minors"},
        "items": items,
    }
    validate_catalog(catalog)
    summary.update(catalog_items=len(items), kind_counts=dict(Counter(it["kind"] for it in items)),
                   group_counts=dict(Counter(it["group"] for it in items)), priority_counts=dict(Counter(it["priority"] for it in items)),
                   thumb_total=len(thumb_rows), thumb_decisions=dict(Counter(r["decision"] for r in thumb_rows)),
                   skin_axis_total=len(skin_rows), skin_axis_decisions=dict(Counter(r["decision"] for r in skin_rows)), source_sha256=hashes)
    out.mkdir(parents=True, exist_ok=True)
    write_json(out / names[0], catalog)
    write_csv(out / names[1], rows)
    write_json(out / names[2], cotags)
    write_json(out / names[3], summary)
    write_csv(out / names[4], thumb_rows)
    write_csv(out / names[5], skin_rows)
    table = ["# 묶음별 전체 후보 표", "", "카탈로그의 축소 보기. 빈도는 175샤드 sparse index; —는 미색인(0 아님).",
             "효과·가중치·역방향은 catalog의 자리별 근거를 우선한다. [실측] 어휘/빈도, [지식]/[추정] 의미, [기록] 이전 생성 기록.", ""]
    for group, label in GROUPS.items():
        table += [f"## {label}", "", "|항목 / 태그|실체|코퍼스|자리·근거|기대 효과(해당 자리)|재구성 위험 / 측정|영점|", "|---|---|---:|---|---|---|---|"]
        for it in items:
            if it["group"] != group:
                continue
            slot = it["default_slot"]
            count = it["corpus_count"]
            effect = it["slots"][slot]["effect"]
            table.append(f"|{it['label_ko']} / `{', '.join(it['tags'])}`|{it['kind']} / {it['status']}|{count if count is not None else '—'}|{slot} / {it['slots'][slot]['evidence_level']}|{effect}|{it['reroll_risk']} / {it['measurable']}|{it['zero_preset_weights'] or '없음'}|")
        table.append("")
    with (out / names[6]).open("x", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(table) + "\n")
    print(json.dumps({k: summary[k] for k in ["n_pairs", "artists", "artist_image_counts", "line_width_unreliable", "catalog_items", "kind_counts", "group_counts", "thumb_decisions", "skin_axis_decisions", "tag_count", "effect_rows", "estimable_rows", "adjusted_estimable_rows", "adequate_rows", "lightness_border_pearson"]}, ensure_ascii=False, indent=2))
    print("CREATED", *[str(p.relative_to(ROOT)) for p in [out / n for n in names]], sep="\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "docs/tone_tuner_2026_10_04")
    parser.add_argument("--diagnose-advisor", action="store_true", help="read-only numeric-artist parsing reproducer; no output files")
    args = parser.parse_args()
    if args.diagnose_advisor:
        import importlib.util
        import sys
        sys.dont_write_bytecode = True
        spec = importlib.util.spec_from_file_location("advisor_readonly", ROOT / "core/image_tone_advisor.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        prompt = "1.15::artist:anam95 ::, 0.75::solo ::, high complexity"
        actual = module._Prompt({"pre_prompt": "", "prompt": prompt, "post_prompt": "", "negative_prompt": ""})
        print(json.dumps({"input": prompt, "research_parser_expected": parse_prompt(prompt),
                          "advisor_actual": [(t["tag"], t["weight"]) for t in actual.tokens],
                          "advisor_unclosed_groups": len(actual.open_groups)}, ensure_ascii=False, indent=2))
        return
    run(args.out)


if __name__ == "__main__":
    main()
