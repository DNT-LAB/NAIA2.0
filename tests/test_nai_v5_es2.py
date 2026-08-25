# -*- coding: utf-8 -*-
"""ES2 계약 검증 — V5 i2i/inpaint multipart + 따옴표 대사 -> 메인 text:

네트워크로 나가기 직전의 요청을 가로챈다(네트워크 0, Anlas 0).
"""
import sys, json
sys.path.insert(0, r'C:\VNR\NAIA2.0')

import requests
from core import nai_model_profile as nai_profile

LF = chr(10)


class _Stop(BaseException):   # 광범위 except Exception 에 안 잡히도록
    def __init__(self, url, kwargs):
        self.url, self.kwargs = url, kwargs


def _fake_post(self, url, **kwargs):
    raise _Stop(url, kwargs)


requests.Session.post = _fake_post


class FakeTokens:
    def get_token(self, k):
        return "TESTTOKEN" if k == 'nai_token' else ""


class FakeMSC:
    def get_module_instance(self, name):
        return None


class FakeCtx:
    def __init__(self):
        self.secure_token_manager = FakeTokens()
        self.middle_section_controller = FakeMSC()
        self.temp_window_mode = False
        self.temp_window_character_tab = None
        self.stored = None

    def store_api_payload(self, payload, kind):
        self.stored = payload


from core.api_service import APIService, extract_quoted_speech, merge_quoted_speech

# 진짜 PNG 1x1 (마스크 처리기가 PIL 로 열어야 한다)
import base64, io as _io
from PIL import Image
_buf = _io.BytesIO()
Image.new("L", (8, 8), 255).save(_buf, format="PNG")
PNG = _buf.getvalue()


def capture(model_key, extra=None):
    ctx = FakeCtx()
    svc = APIService(ctx)
    params = {
        'model': model_key,
        'input': '1girl, solo',
        'negative_prompt': 'bad',
        'width': 832, 'height': 1216, 'steps': 28,
        'cfg_scale': 5.0, 'cfg_rescale': 0.4, 'seed': 12345,
        'sampler': 'k_euler_ancestral', 'scheduler': 'native',
    }
    if extra:
        params.update(extra)
    try:
        svc._call_nai_api(params)
    except _Stop as s:
        return s.kwargs, ctx.stored
    raise AssertionError("post 가 호출되지 않았다")


def body_of(kwargs):
    if 'json' in kwargs:
        return kwargs['json'], 'json'
    return json.loads(kwargs['files']['request'][1]), 'multipart'


FAIL = []


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + ("" if cond else "  <- " + str(detail)))
    if not cond:
        FAIL.append(name)


# ═══ 1. V5 i2i — 이미지가 별도 폼 파트로 나간다 ═══════════════════════════
print("=== 1. V5 img2img : image 를 폼 파트로 분리 ===")
kw, stored = capture('NAID5.0F', {'image_bytes': PNG, 'strength': 0.5, 'noise': 0.05})
payload, mode = body_of(kw)
check("multipart 전송", mode == 'multipart')
check("action=img2img", payload['action'] == 'img2img', payload['action'])
check("image 폼 파트가 따로 올라간다", 'image' in kw['files'], list(kw['files']))
check("파트 바이트가 원본 PNG", kw['files']['image'][1] == PNG)
check("파트 MIME image/png", kw['files']['image'][2] == 'image/png')
check("JSON 은 파트 '이름'만 갖는다", payload['parameters']['image'] == 'image',
      str(payload['parameters']['image'])[:40])
check("저장 페이로드는 base64 그대로 (메타뷰어/리플레이 보호)",
      stored['parameters']['image'] == base64.b64encode(PNG).decode(),
      str(stored['parameters']['image'])[:40])

# ═══ 2. V5 인페인트 — image + mask 둘 다 파트 ════════════════════════════
print("=== 2. V5 inpaint : image + mask 둘 다 파트 ===")
kw, _ = capture('NAID5.0F', {'type': 'inpaint', 'image_bytes': PNG, 'mask_bytes': PNG, 'strength': 1.0})
payload, mode = body_of(kw)
check("multipart 전송", mode == 'multipart')
check("action=infill", payload['action'] == 'infill', payload['action'])
check("image 파트 존재", 'image' in kw['files'])
check("mask 파트 존재", 'mask' in kw['files'])
check("JSON image = 이름", payload['parameters']['image'] == 'image')
check("JSON mask = 이름", payload['parameters']['mask'] == 'mask')
check("모델 = nai-diffusion-5-full-inpainting",
      payload['model'] == 'nai-diffusion-5-full-inpainting', payload['model'])

# ═══ 3. NAID5.0C 인페인트 — Full 인페인팅을 빌려 쓴다 ════════════════════
print("=== 3. NAID5.0C inpaint : 서버에 없는 이름을 안 보낸다 ===")
kw, _ = capture('NAID5.0C', {'type': 'inpaint', 'image_bytes': PNG, 'mask_bytes': PNG})
payload, _ = body_of(kw)
check("nai-diffusion-5-curated-inpainting 을 보내지 않는다",
      payload['model'] != 'nai-diffusion-5-curated-inpainting', payload['model'])
check("Full 인페인팅을 빌려 쓴다",
      payload['model'] == 'nai-diffusion-5-full-inpainting', payload['model'])
print("=== 3b. NAID5.0C i2i 는 Curated 그대로 (Full 로 끌려가지 않는다) ===")
kw, _ = capture('NAID5.0C', {'image_bytes': PNG, 'strength': 0.5})
payload, _ = body_of(kw)
check("i2i 는 nai-diffusion-5-curated", payload['model'] == 'nai-diffusion-5-curated', payload['model'])

# ═══ 4. 회귀 — V4.5 는 인라인 base64 그대로 ═════════════════════════════
print("=== 4. 회귀: V4.5 i2i/inpaint 는 예전 그대로 ===")
kw, _ = capture('NAID4.5F', {'image_bytes': PNG, 'strength': 0.5})
payload, mode = body_of(kw)
check("json 전송 (multipart 아님)", mode == 'json')
check("image 는 payload 안 base64", payload['parameters']['image'] == base64.b64encode(PNG).decode())
check("폼 파트 없음", 'files' not in kw)
kw, _ = capture('NAID4.5F', {'type': 'inpaint', 'image_bytes': PNG, 'mask_bytes': PNG})
payload, _ = body_of(kw)
check("4.5 인페인트 모델명 불변",
      payload['model'] == 'nai-diffusion-4-5-full-inpainting', payload['model'])

# ═══ 5. 따옴표 대사 -> 메인 text: (V5 전용) ══════════════════════════════
print("=== 5. 따옴표 대사 병합 (V5 전용) ===")
kw, _ = capture('NAID5.0F', {'input': '1girl, blackboard, "Tags are concise."'})
payload, _ = body_of(kw)
base = payload['parameters']['v4_prompt']['caption']['base_caption']
check("메인 뒤에 text: 로 얹힌다", base.endswith(', text: Tags are concise.'), base)
check("payload input 도 같은 값", payload['input'] == base)

kw, _ = capture('NAID5.0F', {'input': '1girl, "안녕, 반가워"', 'characters': ['2girl, "고마워"'], 'uc': ['']})
payload, _ = body_of(kw)
base = payload['parameters']['v4_prompt']['caption']['base_caption']
check("따옴표 안 쉼표가 안 끊긴다", '안녕, 반가워' in base, base)
check("메인 -> 캐릭터 차례로 LF 두 개로 잇는다",
      base.endswith('text: 안녕, 반가워' + LF + LF + '고마워'), repr(base[-40:]))
check("캐릭터 칸은 원본 그대로 (지우지 않는다)",
      payload['parameters']['v4_prompt']['caption']['char_captions'][0]['char_caption'] == '2girl, "고마워"')

kw, _ = capture('NAID5.0F', {'input': '1girl, text: 안녕, blue sky, "고마워"'})
payload, _ = body_of(kw)
base = payload['parameters']['v4_prompt']['caption']['base_caption']
check("메인에 이미 text: 가 있으면 그 조각에 잇는다 (앞머리 재사용)",
      base.count('text:') == 1, base)
# ⚠️ 원본의 따옴표는 **그대로 남는다**(공식 웹도 "같은 문장 그대로" 두고 뒤에 얹는다).
# 지우면 그림 자체가 달라지므로, 기댓값에도 꼬리의 `, "고마워"` 가 남아 있어야 한다.
check("잇는 자리는 그 조각 끝 (뒤 문장 순서 보존)",
      base == '1girl, text: 안녕' + LF + LF + '고마워, blue sky, \"고마워\"', repr(base))

kw, _ = capture('NAID5.0F', {'input': '1girl, text: 코드, "코드"'})
payload, _ = body_of(kw)
check("이미 같은 대사가 붙어 있으면 아무것도 안 한다 (재생성 중복 방지)",
      payload['parameters']['v4_prompt']['caption']['base_caption'] == '1girl, text: 코드, \"코드\"',
      payload['parameters']['v4_prompt']['caption']['base_caption'])

kw, _ = capture('NAID5.0F', {'input': '1girl, korean text, context: foo, solo'})
payload, _ = body_of(kw)
check("따옴표가 없으면 무변경", payload['parameters']['v4_prompt']['caption']['base_caption']
      == '1girl, korean text, context: foo, solo')

print("=== 5b. V4.5 는 병합하지 않는다 (사용자 지정: V5 전용) ===")
kw, _ = capture('NAID4.5F', {'input': '1girl, "안녕"'})
payload, _ = body_of(kw)
check("4.5 base_caption 무변경",
      payload['parameters']['v4_prompt']['caption']['base_caption'] == '1girl, "안녕"',
      payload['parameters']['v4_prompt']['caption']['base_caption'])
check("4.5 input 무변경", payload['input'] == '1girl, "안녕"')

# ═══ 6. 헬퍼 단위 ═══════════════════════════════════════════════════════
print("=== 6. 헬퍼 단위 ===")
check("text: 는 옮기지 않는다", extract_quoted_speech(['text: 무시해']) == '')
check("둥근 따옴표도 받는다", extract_quoted_speech(['\u201c둥근\u201d']) == '둥근')
check("빈 따옴표는 건너뛴다", extract_quoted_speech(['""', '"진짜"']) == '진짜')
check("한 칸에 둘이면 둘 다", extract_quoted_speech(['"하나" 그리고 "둘"']) == '하나' + LF + LF + '둘')
check("리터럴 백슬래시n 은 풀지 않는다",
      extract_quoted_speech([r'"가\n나"']) == r'가\n나', repr(extract_quoted_speech([r'"가\n나"'])))
check("teXt 대소문자 구분 안 함 (공식 웹 표기)",
      merge_quoted_speech('a, teXt: 안녕', '안녕') == 'a, teXt: 안녕')
check("빈 자리면 그대로 채운다", merge_quoted_speech('a, text: , b', '값') == 'a, text: 값, b',
      merge_quoted_speech('a, text: , b', '값'))
check("base 가 비면 앞머리만", merge_quoted_speech('', '값') == 'text: 값')

# ═══ 7. 프로필 단위 ═════════════════════════════════════════════════════
print("=== 7. 프로필 단위 ===")
check("5.0C 인페인팅 = Full 빌림",
      nai_profile.inpainting_api_model('NAID5.0C') == 'nai-diffusion-5-full-inpainting')
check("5.0F 인페인팅 = 규칙대로",
      nai_profile.inpainting_api_model('NAID5.0F') == 'nai-diffusion-5-full-inpainting')
check("4.5F 인페인팅 불변",
      nai_profile.inpainting_api_model('NAID4.5F') == 'nai-diffusion-4-5-full-inpainting')
check("인페인팅 이름을 또 붙이지 않는다",
      nai_profile.inpainting_api_model('nai-diffusion-5-full-inpainting') == 'nai-diffusion-5-full-inpainting')
# 인페인팅 wire 전수표 — future02 계약과 한 자도 다르면 안 된다.
# ⚠️ NAID4.0C 는 베이스에만 `-preview` 가 붙는다. 규칙대로 이으면 없는 모델이 된다.
_INPAINT_TABLE = {
    'NAID5.0F': 'nai-diffusion-5-full-inpainting',
    'NAID5.0C': 'nai-diffusion-5-full-inpainting',      # Full 을 빌려 쓴다
    'NAID4.5F': 'nai-diffusion-4-5-full-inpainting',
    'NAID4.5C': 'nai-diffusion-4-5-curated-inpainting',
    'NAID4.0F': 'nai-diffusion-4-full-inpainting',
    'NAID4.0C': 'nai-diffusion-4-curated-inpainting',   # `-preview` 가 빠진다
    'NAID3':    'nai-diffusion-3-inpainting',
}
for _k, _want in _INPAINT_TABLE.items():
    check(f"인페인팅 wire {_k}", nai_profile.inpainting_api_model(_k) == _want,
          nai_profile.inpainting_api_model(_k))
check("NAID4.0C 는 -preview-inpainting 을 만들지 않는다",
      'preview-inpainting' not in nai_profile.inpainting_api_model('NAID4.0C'))

check("wire 이름도 그 모델로 (Enhance 4.5 누수 방지)",
      nai_profile.resolve_api_model('nai-diffusion-5-full') == 'nai-diffusion-5-full')
check("인페인팅 wire 도 되찾는다",
      nai_profile.resolve_api_model('nai-diffusion-5-full-inpainting') == 'nai-diffusion-5-full')
check("모르는 값은 기본 모델",
      nai_profile.resolve_api_model('sd_xl.safetensors') == 'nai-diffusion-4-5-full')

print()
if FAIL:
    print("FAILED %d: %s" % (len(FAIL), FAIL))
    sys.exit(1)
print("ALL PASSED")
