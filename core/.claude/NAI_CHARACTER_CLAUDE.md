# Character Prompt / Character Reference — 다른 모듈에서 쓰는 법

NAI V4·V4.5 의 **캐릭터 프롬프트**(`char_captions`)와 **캐릭터 레퍼런스**
(`director_reference_*`)를 이 저장소가 어떻게 감싸고 있는지, 그리고 **왜 우회하는지**.

세 모듈이 이미 이 길을 쓴다 — Character Asset(Assets 탭) · Character Reference 모듈 ·
Interactive 모드. 새 모듈은 페이로드를 직접 조립하지 말고 아래 진입점을 쓴다.

---

## 1. 한 줄 요약 — 두 기능의 결이 다르다

| | Character Prompt | Character Reference |
|---|---|---|
| 페이로드 | `v4_prompt.caption.char_captions[]` | `director_reference_*` 5종 배열 |
| 단위 | **캐릭터별** (최대 5) | **이미지 전체(세트)** |
| 모델 | V4 / V4.5 (`uses_v4_payload`) | **V4.5 전용** (`payload_profile == "v4.5"`) |
| 좌표 | `centers:[{x,y}]` (기본 0.5/0.5) | 없음 |
| 바인딩 | 늦은 바인딩(생성 시점) | 이른/늦은 바인딩 둘 다 |

**여기서 모든 우회가 나온다: 프롬프트는 캐릭터별인데 레퍼런스는 세트 단위다.**
"이 캐릭터는 이 레퍼런스" 라는 연결이 API 에 없다.

---

## 2. Character Prompt

### 페이로드 모양

```python
api_parameters['v4_prompt']['caption']['char_captions'].append({
    'char_caption': prompt,            # 캐릭터 프롬프트
    'centers': [{'x': 0.5, 'y': 0.5}], # 위치. 미지정이면 중앙
})
api_parameters['v4_negative_prompt']['caption']['char_captions'].append({
    'char_caption': uc,                # 같은 인덱스의 네거티브
    'centers': centers,                # centers 는 양쪽이 같아야 한다
})
```

조립 지점은 `core/api_service.py` 의 V4 분기 하나뿐이다. **모듈이 직접 append 하지
않는다** — 네 갈래 입력을 한 모양으로 정규화한 뒤 여기서만 붙인다.

### 정규화 계약

어느 경로로 들어오든 아래 네 리스트로 맞춰진다.

```
characters      list[str]                 # 캐릭터 프롬프트
ucs             list[str]                 # 같은 인덱스의 네거티브 (짧으면 "" 로 채움)
character_positions  list[{'x','y'}]      # 비어 있으면 전원 중앙
character_ids   list[str]                 # 짧으면 index+1 로 채움
```

입력 소스는 우선순위 순으로 넷이다.

| 소스 | 트리거 | 비고 |
|---|---|---|
| Sketchbook | `params['sketchbook_character_prompts']` | 위치 미지원 → 전원 중앙 |
| EarlyBinding | `params['_generation_request'].nai_characters` | 큐 경로 |
| Snapshot | 저장된 롤 스냅샷 | 재현용 |
| HeadlessSettings | 세션 설정에서 롤 | 새 롤이면 스냅샷 저장 |

`character_ids` 는 UUID 슬롯 매핑용이다 — 조건부 프롬프트가 "캐릭터 1" 을 인덱스가
아니라 정체로 찾을 수 있어야 한다(인덱스로 하면 슬롯을 지웠을 때 밀린다).

### 실행본 되돌려쓰기 — 메타데이터 뷰어가 여기 의존한다

캐릭터는 **생성 시점에 늦게 결정**되므로 요청 `params` 에는 없다. 그래서 페이로드를
만든 뒤 언더스코어 키로 되돌려 적는다.

```python
params['_executed_characters']     = [...]
params['_executed_character_ids']  = [...]
params['_executed_characters_uc']  = [...]
```

**분기 판정은 `'characters'` 키만 본다** — 언더스코어 키는 리플레이 의미를 바꾸지
않는다. 새 모듈이 "실제로 무엇이 생성됐나" 를 알아야 하면 이 키를 읽는다.

### 상한 — 경로마다 강도가 다르다. 여기가 함정이다

`NAICharacterData.__post_init__` 은 **raise 한다**:

```python
if len(self.characters) > 5:  raise ValueError("Maximum 5 characters allowed, got ...")
if len(self.uc) != len(self.characters):  raise ValueError(...)   # 길이도 강제
if self.character_positions and len != len(characters):  raise ValueError(...)
```

그런데 이 검사는 **EarlyBinding(큐) 경로에만** 걸린다. Sketchbook / Snapshot /
HeadlessSettings 는 `NAICharacterData` 를 거치지 않고 정규화 리스트로 바로 들어가고,
`api_service.py` 에는 5 상한 검사가 없다 — **6개를 보내면 NAI 가 조용히 자른다.**

`uc` 길이도 마찬가지다. `NAICharacterData` 는 불일치를 거부하지만, 다른 경로는
`api_service` 가 `""` 로 패딩한다(`ucs[i] if i < len(ucs) else ""`).

> 새 모듈은 **자기 경로에서 5를 막아야 한다.** 큐를 타면 예외로 알게 되지만, 직접
> 생성 경로는 아무 말 없이 잘린다. 프론트도 `MAX_NAI_CHARACTERS = 5` 로 맞춰 뒀다.

---

## 3. Character Reference

### 진입점 — 직접 조립하지 말 것

```python
params = context._character_reference_service().active_params()
# {} 이면 비활성(모델 미지원 / 프레임 없음 / 전부 disabled)
api_parameters.update(params)
```

`core/headless_character_reference_service.py::active_params()` 가 정본이다.
Character Asset 은 요청 단위로만 붙이려고 같은 모양을 따로 만든다
(`headless_character_asset_service.py::_bench_reference_params` / 다중 레퍼런스판).

### 5종 배열은 인덱스가 맞아야 한다

```python
{
  "director_reference_descriptions": [           # 참조 종류를 caption 에 싣는다
      {"caption": {"base_caption": "character&style", "char_captions": []},
       "legacy_uc": False}],
  "director_reference_images": [b64],            # image_data() 를 통과한 문자열
  "director_reference_information_extracted": [1],
  "director_reference_strength_values": [0.8],
  "director_reference_secondary_strength_values": [0.2],   # = fidelity 반전
}
```

- `base_caption` 은 프롬프트가 아니라 **참조 종류**다: `character&style` | `character`
  (`BENCH_REFERENCE_TYPES`). 다른 값을 넣으면 거부한다.
- `secondary_strength` 는 **fidelity 의 반전 + 0.05 양자화**다:
  `round((1.0 - fidelity) * 20) / 20.0`. UI 의 fidelity 를 그대로 보내면 반대로 걸린다.
- `strength` 도 같은 양자화를 거친다(`round(x*20)/20`).
- 이미지는 반드시 `service.image_data(PIL.Image)` 를 통과시킨다 — 임의 해상도를
  **가장 가까운 NAI 캔버스**(2:3 1024×1536 / 3:2 1536×1024 / 1:1 1472×1472)로 맞춘다.

### 같이 따라오는 부작용 — 빼먹으면 조용히 품질이 깨진다

```python
del api_parameters['skip_cfg_above_sigma']          # 반드시 제거
api_parameters['controlnet_strength'] = 1
api_parameters['inpaintImg2ImgStrength'] = 1
api_parameters['normalize_reference_strength_multiple'] = True
```

`skip_cfg_above_sigma` 는 V4.5 기본이 58인데(`nai_model_contract.py`), Character
Reference 와 같이 있으면 **제거해야** 한다. `active_params()` 는 이 제거를 하지
않는다 — 호출부(`api_service.py`)가 한다. 새 경로를 만들면 같이 옮겨야 한다.

인페인트(`action_type == "infill"`)면 `_mirror_nai_inpaint_img2img_strength` 로
중첩 `img2img.strength` 까지 미러링한다. V4/4.5 는 중첩 키를 따로 본다.

### 모델 게이트 — 조용히 버리지 않는다

```python
if not model_spec.supports_character_reference:      # payload_profile == "v4.5"
    raise ValueError("Character Reference requires a model with the v4.5 ...")
```

비지원 모델에서 **조용히 drop 하지 않고 명시적으로 거부**한다(Codex 지적 반영).
새 모듈도 같은 규칙을 지킨다 — 사용자가 레퍼런스를 켰는데 무시된 그림이 나오면
원인을 찾을 수 없다.

### 캐시

`(경로, mtime_ns)` 키로 b64 를 캐시하고 8개를 넘으면 통째로 비운다. 같은 레퍼런스로
연속 생성할 때 매번 인코딩하지 않기 위한 것이다.

---

## 4. 왜 우회하는가 — 세 가지 우회

### 우회 1. 캐릭터별 레퍼런스가 없다 → 세트 단위로 늦게 바인딩

NAI 는 `director_reference_images[]` 를 이미지 전체에 건다. `char_captions[i]` 와
묶는 필드가 없다. 그래서 Interactive 모드의 캐릭터별 [Reference] 버튼은 **비활성**이고
툴팁에 이유가 적혀 있다:

```js
// interactivePanel.mjs
title="레퍼런스 이미지 (준비 중) — NAI 는 캐릭터별이 아니라 세트 단위로 받는다"
```

Character Asset 은 **한 캐릭터만 다루는 화면**이라 이 제약을 피해 간다 —
그 캐릭터의 primary 이미지를 **그 요청에 한해** 세트 레퍼런스로 늦게 바인딩한다
(`_bench_reference_params`). 세션 상태를 건드리지 않으므로 다른 생성에 새지 않는다.

> 새 모듈이 여러 캐릭터에 각각 레퍼런스를 걸고 싶다면 **API 로는 불가능하다.**
> 선택지는 (a) 한 번에 한 캐릭터만 다루기, (b) 아래 인셋 트릭, (c) 인페인트로
> 캐릭터를 순차 교체하기 셋뿐이다.

### 우회 2. 레퍼런스 인셋 — 프롬프트로 만드는 유사 레퍼런스

`core/reference_inset_service.py` 는 프롬프트에 `borderless panels` 태그를 끼워
**그림 안에 참조 패널을 그리게** 한다. API 레퍼런스가 아니라 프롬프트 트릭이다.

```python
REFERENCE_INSET_TAGS = ("borderless panels",)
REFERENCE_INSET_HOOK_INFO = {
    "target_pipeline": "PromptProcessor",
    "hook_point": "final_hookpoint",
    "priority": 90,
}
```

- 트리거: `settings['reference_inset_tag_required']` 또는 `settings['cropped_image_request']`,
  또는 `context.metadata['reference_inset']`
- 파이프라인 훅(`modules/reference_inset_module.py`)이 정상 경로지만, **[랜덤/다음
  프롬프트] 를 거치지 않는 직접 생성**에서는 훅이 안 돈다 → `api_service.py` 가
  생성 시점에 한 번 더 삽입한다. 이중 삽입은 "이미 있으면 누락분만 보충" 으로 막는다.
- 인원 태그(`REFERENCE_INSET_PERSON_TAGS`)를 같이 본다 — 사람이 없으면 패널이 무의미.

### 우회 3. 캐릭터 프롬프트가 늦게 결정된다 → 실행본을 되돌려 적는다

§2 의 `_executed_characters*`. 조건부/와일드카드가 생성 시점에 굴러가므로 요청에는
"무엇이 나갈지" 가 없다. 메타뷰어·프리셋 되살리기·Freeze 가 전부 이 되돌려쓰기에
의존한다. 새 모듈이 캐릭터를 늦게 정하면 **같은 키에 같은 방식으로 기록해야** 한다.

---

## 5. 새 모듈 체크리스트

```
[ ] 캐릭터 프롬프트를 직접 char_captions 에 넣지 않는다.
    -> characters / ucs / positions / character_ids 네 리스트로 정규화해서 넘긴다.
[ ] 5개 상한을 UI 에서 막는다. 넘기면 조용히 드롭된다.
[ ] 캐릭터를 늦게 정하면 _executed_characters* 를 되돌려 적는다.
[ ] Character Reference 는 active_params() 를 쓴다. 5종 배열을 손으로 맞추지 않는다.
[ ] 손으로 만들어야 한다면: fidelity 반전(1-x)·0.05 양자화·image_data() 통과·
    skip_cfg_above_sigma 제거·controlnet/inpaint/normalize 3종 동반.
[ ] 비지원 모델은 조용히 넘기지 말고 raise 한다.
[ ] 캐릭터별 레퍼런스는 API 에 없다. 한 캐릭터씩 다루거나 인셋 트릭을 쓴다.
```

---

## 6. 파일 지도

| 파일 | 역할 |
|---|---|
| `core/api_service.py` | **유일한 페이로드 조립 지점**. char_captions·director_* 둘 다 |
| `core/generation_request.py` | `NAICharacterData`(최대 5) · `NAICharacterReferenceData` |
| `core/headless_character_reference_service.py` | CR 정본 — `active_params()` / `image_data()` |
| `core/headless_character_asset_service.py` | 요청 단위 CR 늦은 바인딩 · 벤치 모드 |
| `core/reference_inset_service.py` | 프롬프트 인셋 트릭 |
| `core/nai_model_contract.py` | `supports_character_reference` · `skip_cfg_above_sigma` |
| `app/web/remote/js/features/interactivePanel.mjs` | 캐릭터별 Reference 가 비활성인 이유 |
