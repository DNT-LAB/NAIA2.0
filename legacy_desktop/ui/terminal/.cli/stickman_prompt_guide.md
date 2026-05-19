# Stickman → NovelAI Prompt Tag Guide

## Overview
손으로 그린 스틱맨/스케치를 분석하여 NovelAI 프롬프트 태그를 생성하기 위한 가이드.

---

## 필수 제약 조건

1. **퀄리티 태그 금지** — masterpiece, best quality, highly detailed 등 퀄리티 관련 태그는 작성하지 않음
2. **언더바 사용 금지** — NovelAI 프롬프트이므로 `arms up` (O), `arms_up` (X). 띄어쓰기로 구분
3. **자연어 보완 허용** — Danbooru 태그로 표현이 불충분한 경우, 태그 뒷부분에 자연어 문장을 추가하여 상세 기술 가능

---

## 분석 프레임워크 (3 Layer)

### Layer 1: POSE (포즈)
- 전신 자세: standing, sitting, lying, kneeling, crouching, leaning
- 팔 위치: arms up, arms behind back, hand on hip, reaching out, crossed arms, hand on own chest
- 다리 위치: legs crossed, spread legs, one knee up, feet on desk
- 머리/시선: looking at viewer, looking away, looking up, looking down, head tilt, profile
- 몸통 방향: facing viewer, from side, from behind, twisted torso, contrapposto

### Layer 2: SCENE + OBJECTS (씬 및 오브젝트)
- **환경**: indoors, outdoors, classroom, office, bedroom, rooftop, park, cafe
- **가구/소품**: desk, chair, bed, sofa, table, window, door, bookshelf
- **상호작용**: sitting on chair, leaning on desk, holding phone, reading book, typing
- **오브젝트 위치**: 캐릭터와의 물리적 관계를 구체적으로 기술
  - 예: "feet resting ON TOP of desk surface" → `feet on desk, desk`
  - 예: "hand gripping sword handle" → `holding sword, sword`

### Layer 3: MOOD + CAMERA (분위기 및 카메라)
- **분위기**: happy, melancholy, dramatic, peaceful, energetic, mysterious
- **조명**: dramatic lighting, soft lighting, backlighting, rim lighting, natural lighting
- **카메라 앵글**: from above, from below, dutch angle, wide shot, close-up, cowboy shot, full body
- **구도**: dynamic angle, dynamic pose, cinematic composition

---

## 출력 형식

**반드시 아래 순서대로 출력할 것** — 태그를 먼저 제시하고, 해설은 맨 마지막에 배치하여 사용자가 태그를 쉽게 복사할 수 있도록 한다.

### 1단계: 스틱맨 분석
그림에서 읽어낸 포즈, 씬, 오브젝트, 분위기를 간략히 서술.

### 2단계: 제안 태그 (복사용)
쉼표 구분 태그를 **코드 블록 하나** 안에 작성. **번호, 불릿, 카테고리 라벨 없이** 쉼표로만 연결하여 사용자가 바로 복사·붙여넣기할 수 있는 형태로 제공할 것.

카테고리 배치 순서 (라벨은 출력하지 않음):
포즈 → 씬/배경 → 상호작용 → 분위기/스타일 → 자연어 보완

예시 형태:
```
sitting, leaning back, feet on desk, bare feet, hands behind head, looking away, indoors, window, desk, coffee cup, potted plant, peaceful, natural lighting, from side
```

※ 퀄리티 태그는 작성하지 않음

### 3단계: 태그 해설 (맨 마지막)
각 태그의 선택 이유와 역할을 표 또는 목록으로 설명. **반드시 태그 뒤에 배치.**

---

## 분석 시 주의사항

1. **사지-오브젝트 상호작용을 구체적으로** — 다리가 테이블 위에 있으면 반드시 명시
2. **단순화하거나 생략하지 말 것** — 스틱맨의 모든 디테일을 태그로 변환
3. **구도에서 분위기를 추론** — 전체 구성에서 감정과 분위기를 읽어낼 것
4. **Danbooru 스타일 태그 우선** — 공백 구분, 소문자. 적절한 태그가 없으면 자연어로 보완
5. **NovelAI 형식 준수** — 언더바 대신 공백 사용

---

## 예시

### 예시 1: 의자에 앉아 타이핑하는 포즈
```
solo,
sitting, typing, looking at viewer, slight smile,
office, desk, computer, monitor, office chair,
indoors, soft lighting, from front
```

### 예시 2: 책상에 발 올린 포즈
```
solo,
sitting, feet on desk, leaning back, crossed legs, smug, hand behind head,
desk, office chair, monitor,
indoors, dramatic lighting, from side
```

### 예시 3: 링거를 끌며 걷는 환자
```
solo,
walking, hospital gown, bare feet, looking ahead,
iv drip, iv stand, iv bag, bandage on hand,
hospital, hospital hallway, indoors, white walls,
melancholy, soft lighting, full body, from side,
girl in a hospital gown walking while dragging an IV stand with one hand
```
