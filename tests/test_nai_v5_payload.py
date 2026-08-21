# -*- coding: utf-8 -*-
"""V5 배선 오프라인 검증 - 네트워크로 나가기 직전의 요청을 가로채 계약을 본다."""
import sys, json
sys.path.insert(0, r'C:\VNR\NAIA2.0')

import requests
from core import nai_model_profile as nai_profile


class _Stop(BaseException):   # 광범위 except Exception 에 안 잡히도록
    def __init__(self, url, kwargs):
        self.url, self.kwargs = url, kwargs


def _fake_post(self, url, **kwargs):
    raise _Stop(url, kwargs)


requests.Session.post = _fake_post


class FakeVibeModule:
    def get_vibe_transfer_multiple_data(self):
        return {
            'normalize_reference_strength_multiple': True,
            'reference_image_multiple': ['ENCODED_VIBE_A'],
            'reference_strength_multiple': [0.6],
        }


class FakeMSC:
    def __init__(self, vibe=True):
        self._vibe = FakeVibeModule() if vibe else None

    def get_module_instance(self, name):
        if name == "VibeTransferModule":
            return self._vibe
        return None


class FakeTokens:
    def get_token(self, k):
        return "TESTTOKEN" if k == 'nai_token' else ""


class FakeCtx:
    def __init__(self, vibe=True):
        self.secure_token_manager = FakeTokens()
        self.middle_section_controller = FakeMSC(vibe)
        self.temp_window_mode = False
        self.temp_window_character_tab = None
        self.multi_account_enabled = False
        self.image_crud_controller = None
        self.stored = None

    def store_api_payload(self, payload, kind):
        self.stored = payload


from core.api_service import APIService

PNG = bytes([0x89, 0x50, 0x4E, 0x47])


def capture(model_key, extra=None, vibe=True):
    ctx = FakeCtx(vibe)
    svc = APIService(ctx)
    params = {
        'model': model_key,
        'input': '1girl, solo',
        'negative_prompt': 'bad',
        'width': 832, 'height': 1216, 'steps': 28,
        'cfg_scale': 5.0, 'cfg_rescale': 0.4, 'seed': 12345,
        'sampler': 'k_euler_ancestral', 'scheduler': 'native',
        'characters': ['char one'], 'uc': ['char uc'],
    }
    if extra:
        params.update(extra)
    try:
        svc._call_nai_api(params)
    except _Stop as s:
        return s.url, s.kwargs, ctx.stored
    raise AssertionError("post 가 호출되지 않았다")


def body_of(kwargs):
    if 'json' in kwargs:
        return kwargs['json'], 'json'
    part = kwargs['files']['request']
    return json.loads(part[1]), 'multipart'


FAIL = []


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + ("" if cond else "  <- " + str(detail)))
    if not cond:
        FAIL.append(name)


print("=== 1. NAID5.0F : transport / payload contract ===")
url, kw, stored = capture('NAID5.0F')
payload, mode = body_of(kw)
check("multipart transport", mode == 'multipart', list(kw.keys()))
check("request part filename = blob", kw['files']['request'][0] == 'blob')
check("request part MIME = application/json", kw['files']['request'][2] == 'application/json')
check("model = nai-diffusion-5-full", payload['model'] == 'nai-diffusion-5-full', payload['model'])
check("uses v4_prompt", 'v4_prompt' in payload['parameters'])
check("no v5_prompt", 'v5_prompt' not in payload['parameters'])
check("char_captions carried",
      len(payload['parameters']['v4_prompt']['caption']['char_captions']) == 1,
      payload['parameters']['v4_prompt']['caption']['char_captions'])
check("vibe dropped (reference_image_multiple absent)",
      'reference_image_multiple' not in payload['parameters'])
check("vibe dropped (reference_strength_multiple absent)",
      'reference_strength_multiple' not in payload['parameters'])
check("character reference dropped",
      not any(k.startswith('director_reference') for k in payload['parameters']))

print("=== 2. NAID5.0C ===")
url, kw, _ = capture('NAID5.0C')
payload, mode = body_of(kw)
check("multipart", mode == 'multipart')
check("model = nai-diffusion-5-curated", payload['model'] == 'nai-diffusion-5-curated', payload['model'])

print("=== 3. V5 + VAR+ : skip_cfg_above_sigma key must be absent ===")
url, kw, _ = capture('NAID5.0F', {'VAR+': True})
payload, _ = body_of(kw)
check("VAR+ on -> no skip_cfg_above_sigma",
      'skip_cfg_above_sigma' not in payload['parameters'],
      payload['parameters'].get('skip_cfg_above_sigma'))

print("=== 4. V5 inpaint : model suffix ===")
url, kw, _ = capture('NAID5.0F', {'type': 'inpaint', 'image_bytes': PNG, 'mask_bytes': PNG})
payload, mode = body_of(kw)
check("model = nai-diffusion-5-full-inpainting",
      payload['model'] == 'nai-diffusion-5-full-inpainting', payload['model'])
check("inpaint also multipart", mode == 'multipart')

print("=== 5. regression: NAID4.5F unchanged ===")
url, kw, _ = capture('NAID4.5F', {'VAR+': True})
payload, mode = body_of(kw)
check("plain json (not multipart)", mode == 'json', list(kw.keys()))
check("model = nai-diffusion-4-5-full", payload['model'] == 'nai-diffusion-4-5-full')
check("skip_cfg_above_sigma == 58", payload['parameters'].get('skip_cfg_above_sigma') == 58)
check("vibe sent", payload['parameters'].get('reference_image_multiple') == ['ENCODED_VIBE_A'])
check("v4_prompt present", 'v4_prompt' in payload['parameters'])
check("char_captions present",
      len(payload['parameters']['v4_prompt']['caption']['char_captions']) == 1)

print("=== 6. regression: NAID3 ===")
url, kw, _ = capture('NAID3', {'VAR+': True})
payload, mode = body_of(kw)
check("plain json", mode == 'json')
check("model = nai-diffusion-3", payload['model'] == 'nai-diffusion-3')
check("skip_cfg_above_sigma == 19", payload['parameters'].get('skip_cfg_above_sigma') == 19)
check("no v4_prompt", 'v4_prompt' not in payload['parameters'])
check("vibe sent", payload['parameters'].get('reference_image_multiple') == ['ENCODED_VIBE_A'])

print("=== 7. regression: NAID4.0F ===")
url, kw, _ = capture('NAID4.0F', {'VAR+': True})
payload, mode = body_of(kw)
check("plain json", mode == 'json')
check("model = nai-diffusion-4-full", payload['model'] == 'nai-diffusion-4-full')
check("skip_cfg_above_sigma == 19", payload['parameters'].get('skip_cfg_above_sigma') == 19)
check("v4_prompt present", 'v4_prompt' in payload['parameters'])

print("=== 8. Content-Type header ===")
url, kw, _ = capture('NAID5.0F')
check("V5: no explicit Content-Type (requests builds boundary)",
      'Content-Type' not in kw.get('headers', {}), kw.get('headers'))
url, kw, _ = capture('NAID4.5F')
check("V4.5: Content-Type application/json kept",
      kw.get('headers', {}).get('Content-Type') == 'application/json', kw.get('headers'))

print("=== 9. profile unit contract ===")
check("NAID5.0F -> v4 payload", nai_profile.uses_v4_prompt_payload('NAID5.0F'))
check("NAID5.0F vibe disabled", not nai_profile.supports_vibe_transfer('NAID5.0F'))
check("NAID5.0C CR disabled", not nai_profile.supports_character_reference('NAID5.0C'))
check("NAID4.5F vibe enabled", nai_profile.supports_vibe_transfer('NAID4.5F'))
check("NAID4.5F CR enabled", nai_profile.supports_character_reference('NAID4.5F'))
check("NAID3 vibe enabled", nai_profile.supports_vibe_transfer('NAID3'))
check("NAID3 CR disabled", not nai_profile.supports_character_reference('NAID3'))
check("NAID3 not v4 payload", not nai_profile.uses_v4_prompt_payload('NAID3'))
check("normalize known key", nai_profile.normalize_model_key('NAID5.0F') == 'NAID5.0F')
check("normalize unknown -> empty", nai_profile.normalize_model_key('sd_xl_base.safetensors') == '')
check("multipart only for V5", nai_profile.uses_multipart_request('NAID5.0F')
      and not nai_profile.uses_multipart_request('NAID4.5F'))
check("combo list has both V5 keys",
      nai_profile.NAI_MODEL_KEYS[:2] == ('NAID5.0F', 'NAID5.0C'), nai_profile.NAI_MODEL_KEYS)
check("default stays NAID4.5F", nai_profile.DEFAULT_NAI_MODEL_KEY == 'NAID4.5F')

print()
if FAIL:
    print("FAILED %d: %s" % (len(FAIL), FAIL))
    sys.exit(1)
print("ALL PASSED")
