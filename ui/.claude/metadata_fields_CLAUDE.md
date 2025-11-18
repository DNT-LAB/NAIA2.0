# NovelAI 메타데이터 필드 레퍼런스

> **레퍼런스 문서**: 상세 필드 정보를 위한 레퍼런스 파일입니다. 메인 문서에서 링크로 참조됩니다.

---

## NovelAI 메타데이터 필드 (NAID4.5F 기준)

⚠️ **주의**: 아래 필드는 NAID4.5F 이미지에서 관찰된 것으로, **모델 버전, 생성 옵션에 따라 다를 수 있습니다**.

### 최상위 필드 (Stealth PNG)

```python
'Software': 'NovelAI',
'Source': 'NovelAI Diffusion V4.5 4BDE2A90',
'Title': '...',
'Description': '...',
'Generation time': '...',
```

### Comment 내부 필드 (중첩 JSON)

#### 프롬프트

```python
'prompt': str,
'uc': str,  # Negative prompt
'v4_prompt': dict,  # NAI v4 형식 프롬프트
'v4_negative_prompt': dict,
```

#### 생성 파라미터

```python
'steps': int,
'width': int,
'height': int,
'scale': float,  # CFG Scale
'uncond_scale': float,  # UC Strength
'cfg_rescale': float,
'seed': int,
'n_samples': int,
'noise_schedule': str,  # Scheduler
'sampler': str,
'sm': bool,  # SMEA
'sm_dyn': bool,  # SMEA+DYN
'skip_cfg_above_sigma': float,  # VAR+
'skip_cfg_below_sigma': float,
```

#### Vibe Transfer (있을 경우)

```python
'reference_image_multiple': [str],  # base64 인코딩된 이미지
'reference_information_extracted_multiple': [float],
'reference_strength_multiple': [float],
```

#### Director Tools (있을 경우)

```python
'director_references': [...],
'director_reference_strengths': [...],
'director_reference_images': [...],
'director_reference_descriptions': [...],
```

#### 고급 옵션

```python
'lora_unet_weights': str,
'lora_clip_weights': str,
'dynamic_thresholding': bool,
'dynamic_thresholding_percentile': float,
'dynamic_thresholding_mimic_scale': float,
'controlnet_strength': float,
'controlnet_model': str,
```

#### 기타 필드

```python
'legacy_v3_extend': bool,
'deliberate_euler_ancestral_bug': bool,
'prefer_brownian': bool,
'cfg_sched_eligibility': str,
'explike_fine_detail': bool,
'minimize_sigma_inf': bool,
'uncond_per_vibe': bool,
'wonky_vibe_correlation': bool,
'stream': bool,
'version': int,
'request_type': str,
'signed_hash': str,
```

---

## 지원 모델 매핑

```python
model_map = {
    'NovelAI Diffusion V4.5 4BDE2A90': 'NAID4.5F',  # Full
    'NovelAI Diffusion V4.5 C02D4F98': 'NAID4.5C',  # Curated
    'NovelAI Diffusion V4 7ABFFA2A': 'NAID4.0C',    # v4 Curated
    'NovelAI Diffusion V4 37442FCA': 'NAID4.0F',    # v4 Full
    'Stable Diffusion XL 7BCCAA2C': None            # NAID3 (미지원)
}
```

---

*레퍼런스 문서 버전: 1.0*
*최종 업데이트: 2025-01-17*
