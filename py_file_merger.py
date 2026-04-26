import os
import shutil
from datetime import datetime

def generate_tree_structure(root_dir, excluded_dirs=None):
    """
    디렉토리 구조를 트리 형태로 생성하는 함수
    """
    if excluded_dirs is None:
        excluded_dirs = {'__pycache__', 'temp', 'venv', 'not_implement', '.git', '.vscode', 'node_modules', 'output'}
    
    tree_lines = []
    
    def add_tree_line(path, level, is_last, file_name, is_dir=False):
        """트리 라인을 추가하는 헬퍼 함수"""
        prefix = ""
        for i in range(level):
            if i == level - 1:
                prefix += "└── " if is_last else "├── "
            else:
                prefix += "    " if i in last_levels else "│   "
        
        # 파일 타입에 따른 아이콘 추가
        if is_dir:
            icon = "📁 "
        elif file_name.endswith('.py'):
            icon = "🐍 "
        elif file_name.endswith('.md'):
            icon = "📖 "
        elif file_name.endswith('.json'):
            icon = "⚙️ "
        elif file_name.endswith(('.parquet', '.txt', '.csv')):
            icon = "📊 "
        else:
            icon = "📄 "
            
        tree_lines.append(f"{prefix}{icon}{file_name}")
    
    last_levels = set()
    
    def walk_directory(current_path, level=0):
        """재귀적으로 디렉토리를 순회하는 함수"""
        try:
            items = []
            
            # 디렉토리와 파일 분리
            dirs = []
            files = []
            
            for item in os.listdir(current_path):
                if item.startswith('.'):
                    continue
                    
                item_path = os.path.join(current_path, item)
                if os.path.isdir(item_path):
                    if item not in excluded_dirs:
                        dirs.append(item)
                else:
                    files.append(item)
            
            # 정렬
            dirs.sort()
            files.sort()
            
            # 모든 아이템 처리
            all_items = [(d, True) for d in dirs] + [(f, False) for f in files]
            
            for i, (item_name, is_dir) in enumerate(all_items):
                is_last = i == len(all_items) - 1
                
                if is_last:
                    last_levels.add(level)
                else:
                    last_levels.discard(level)
                
                add_tree_line(current_path, level, is_last, item_name, is_dir)
                
                # 디렉토리인 경우 재귀 호출
                if is_dir:
                    item_path = os.path.join(current_path, item_name)
                    walk_directory(item_path, level + 1)
                    
        except PermissionError:
            pass
    
    # 루트 디렉토리 추가
    root_name = os.path.basename(os.path.abspath(root_dir)) or "NAIA v2.0"
    tree_lines.append(f"📁 {root_name}/")
    
    # 디렉토리 순회 시작
    walk_directory(root_dir, 0)
    
    return tree_lines

def create_naia_comprehensive_guide(tree_lines, merged_files_info):
    """
    NAIA v2.0 프로젝트의 포괄적인 개발 가이드를 생성하는 함수
    """
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    md_content = f"""# 🚀 NAIA v2.0 통합 개발 가이드 & AI 협업 매뉴얼

> 📅 **최종 업데이트**: {current_time}  
> 🤖 **목적**: 생성형 AI와 오픈소스 개발자들의 효율적인 협업을 위한 종합 가이드  
> 🎯 **대상**: Claude, GPT, 기타 생성형 AI 및 커뮤니티 개발자

---

## 📋 목차

1. [프로젝트 개요 & 목적](#프로젝트-개요--목적)
2. [시스템 아키텍처](#시스템-아키텍처)
3. [프로젝트 구조](#프로젝트-구조)
4. [핵심 컴포넌트 분석](#핵심-컴포넌트-분석)
5. [개발 워크플로우](#개발-워크플로우)
6. [모듈 개발 가이드](#모듈-개발-가이드)
7. [API 통합 가이드](#api-통합-가이드)
8. [AI 협업 프로토콜](#ai-협업-프로토콜)
9. [트러블슈팅](#트러블슈팅)

---

## 🎯 프로젝트 개요 & 목적

### NAIA v2.0이란?

**NAIA (NovelAI Assistant) v2.0**는 AI 이미지 생성을 위한 **고급 프롬프트 관리 및 자동화 시스템**입니다.

#### 핵심 목표
- 🎨 **프롬프트 엔지니어링 자동화**: 복잡한 프롬프트 구성을 직관적으로
- 🔄 **멀티 플랫폼 지원**: NovelAI, Stable Diffusion WebUI, ComfyUI 통합
- 🧩 **모듈화 설계**: 기능별 독립 모듈로 확장성 극대화
- ⚡ **실시간 처리**: 비동기 처리로 끊김 없는 사용자 경험
- 🌐 **오픈소스 생태계**: 커뮤니티 기여 친화적 아키텍처

#### 주요 기능
- **지능형 태그 관리**: 40만+ Danbooru 태그 데이터베이스 기반
- **동적 프롬프트 생성**: 파이프라인 기반 프롬프트 처리
- **실시간 미리보기**: 프롬프트 변경사항 즉시 반영
- **배치 자동화**: 대량 이미지 생성 자동화
- **커스텀 워크플로우**: ComfyUI 워크플로우 통합

---

## 🏗️ 시스템 아키텍처

### 전체 아키텍처 개요

```mermaid
graph TB
    subgraph "🖥️ UI Layer (PyQt6)"
        A[ModernMainWindow] --> B[LeftPanel - Modules]
        A --> C[RightPanel - Tabs]
        B --> D[CollapsibleBox]
        C --> E[TabController]
    end
    
    subgraph "🎛️ Controller Layer"
        F[MiddleSectionController] --> G[Module Lifecycle]
        H[GenerationController] --> I[AI Service Bridge]
        J[PromptGenerationController] --> K[Pipeline Management]
    end
    
    subgraph "🧠 Core Layer"
        L[AppContext] --> M[Event System]
        L --> N[State Management]
        O[PromptProcessor] --> P[Pipeline Hooks]
        Q[APIService] --> R[Multi-Platform Support]
    end
    
    subgraph "🔌 Interface Layer"
        S[BaseMiddleModule] --> T[Module Contract]
        U[BaseTabModule] --> V[Tab Contract]
        W[ModeAwareModule] --> X[Auto Configuration]
    end
    
    subgraph "📊 Data Layer"
        Y[TagDataManager] --> Z[Danbooru Database]
        AA[WildcardManager] --> AB[Dynamic Content]
        AC[FilterDataManager] --> AD[Search & Filter]
    end
    
    A --> F
    F --> L
    H --> Q
    J --> O
    G --> S
    E --> U
    O --> Y
    O --> AA
```

### 설계 원칙

#### 1. **Strict Modularity (엄격한 모듈성)**
- 모든 기능은 독립적인 Module 또는 Tab 클래스로 구현
- 인터페이스 기반 계약으로 일관성 보장
- 런타임 동적 로딩으로 확장성 제공

#### 2. **AppContext 중심 관리**
- 모든 공유 자원, 상태, 이벤트는 AppContext를 통해 관리
- 글로벌 변수 사용 금지로 의존성 명확화
- 중앙집중식 설정 및 생명주기 관리

#### 3. **Event-Driven Architecture (이벤트 기반)**
- Signal/Slot 메커니즘으로 느슨한 결합
- 파이프라인 훅 시스템으로 확장 포인트 제공
- 비동기 이벤트 처리로 반응성 보장

#### 4. **Pipeline Processing (파이프라인 처리)**
- 프롬프트 생성을 단계별 파이프라인으로 분할
- 각 단계마다 훅 포인트로 확장 가능
- 플러그인 방식의 기능 추가 지원

---

## 🌳 프로젝트 구조

### 디렉토리 구조 상세

```
{chr(10).join(tree_lines)}
```

### 핵심 디렉토리 역할

#### 📁 **core/** - 시스템 핵심 로직
- **context.py**: 애플리케이션 중앙 컨텍스트
- **prompt_processor.py**: 프롬프트 파이프라인 엔진
- **api_service.py**: 멀티 플랫폼 API 통합
- **generation_controller.py**: 이미지 생성 제어
- **middle_section_controller.py**: 모듈 생명주기 관리

#### 📁 **interfaces/** - 추상 인터페이스
- **base_module.py**: 미들섹션 모듈 기본 계약
- **base_tab_module.py**: 탭 모듈 기본 계약
- **mode_aware_module.py**: 모드별 설정 자동화

#### 📁 **modules/** - 기능 모듈
- **automation_module.py**: 자동화 및 배치 처리
- **character_module.py**: 캐릭터 입력 관리
- **prompt_engineering_module.py**: 고급 프롬프트 도구

#### 📁 **ui/** - 사용자 인터페이스
- **theme.py**: 다크 테마 및 스타일
- **collapsible.py**: 접이식 UI 컴포넌트
- **right_view.py**: 탭 기반 우측 패널

#### 📁 **data/** - 데이터 저장소
- **tags/**: Danbooru 태그 데이터베이스 (Parquet 형식)
- **KR_tags.parquet**: 한국어 번역 태그
- 각종 목록 파일 (특성, 의상, 색상 등)

---

## 🔧 핵심 컴포넌트 분석

### AppContext - 시스템 중추

**파일**: `core/context.py`

```python
class AppContext:
    '''애플리케이션의 공유 자원 및 상태를 관리하는 컨텍스트'''
    
    # 핵심 역할
    - 모든 컨트롤러와 매니저 인스턴스 보유
    - 이벤트 발행/구독 시스템 제공
    - 모듈 간 의존성 주입 관리
    - 설정 및 상태 중앙 집중화
```

**의존성 관계**:
- **사용하는 곳**: `main.py`, 모든 modules/*, controllers/*
- **관리하는 것**: APIService, WildcardManager, TagDataManager 등

### PromptProcessor - 파이프라인 엔진

**파일**: `core/prompt_processor.py`

```python
class PromptProcessor:
    '''프롬프트 생성 전체 파이프라인 관리'''
    
    # 파이프라인 단계
    1. pre_processing: 전처리
    2. fit_resolution: 해상도 최적화  
    3. expand_wildcards: 와일드카드 확장
    4. post_processing: 후처리
    5. final_format: 최종 포맷팅
    6. after_completion: 완료 후 처리
```

**훅 시스템**: 각 단계마다 모듈이 개입할 수 있는 훅 포인트 제공

### BaseMiddleModule - 모듈 추상화

**파일**: `interfaces/base_module.py`

```python
class BaseMiddleModule(ABC):
    '''모든 미들섹션 모듈의 기본 인터페이스'''
    
    # 필수 구현 메서드
    @abstractmethod
    def get_title(self) -> str
    
    @abstractmethod  
    def create_widget(self, parent) -> QWidget
    
    # 선택적 훅 메서드
    def get_pipeline_hook_info(self) -> Dict
    def execute_pipeline_hook(self, stage, context) -> Any
```

---

## ⚙️ 개발 워크플로우

### 새 모듈 개발 프로세스

#### 1. **모듈 클래스 생성**
```python
# modules/new_feature_module.py
from interfaces.base_module import BaseMiddleModule
from interfaces.mode_aware_module import ModeAwareModule

class NewFeatureModule(BaseMiddleModule, ModeAwareModule):
    def __init__(self, app_context: AppContext):
        super().__init__(app_context)
        self.init_mode_aware_settings()  # 모드별 설정 초기화
    
    def get_title(self) -> str:
        return "새로운 기능"
    
    def create_widget(self, parent) -> QWidget:
        # UI 구성 로직
        pass
```

#### 2. **파이프라인 훅 구현** (선택사항)
```python
def get_pipeline_hook_info(self) -> Dict:
    return {{
        'pre_processing': True,  # 전처리 단계 참여
        'expand_wildcards': True  # 와일드카드 확장 참여
    }}

def execute_pipeline_hook(self, stage: str, context: PromptContext) -> Any:
    if stage == 'pre_processing':
        # 전처리 로직
        return context
    elif stage == 'expand_wildcards':
        # 와일드카드 처리 로직
        return context
```

#### 3. **모듈 등록**
```python
# core/middle_section_controller.py 수정
from modules.new_feature_module import NewFeatureModule

class MiddleSectionController:
    def create_modules(self):
        modules = [
            # 기존 모듈들...
            NewFeatureModule(self.app_context)  # 새 모듈 추가
        ]
```

### 코드 수정 시 체크리스트

#### ✅ **변경 전 확인사항**
- [ ] 해당 컴포넌트의 인터페이스 파일 검토
- [ ] AppContext 의존성 확인  
- [ ] 관련 파이프라인/이벤트 연결 상태 점검
- [ ] 기존 기능에 미치는 영향 분석

#### ✅ **변경 후 검증사항**
- [ ] UI 반응성 테스트 (비동기 처리 확인)
- [ ] 모듈 간 상호작용 정상 동작
- [ ] 파이프라인 훅 정상 실행
- [ ] 메모리 누수 없음

---

## 🔌 API 통합 가이드

### 지원 플랫폼

#### 1. **NovelAI**
```python
# core/api_service.py
class APIService:
    async def generate_image_novelai(self, prompt: str, settings: Dict) -> Dict:
        # NovelAI API 호출 로직
```

#### 2. **Stable Diffusion WebUI**
```python
async def generate_image_webui(self, prompt: str, settings: Dict) -> Dict:
    # WebUI API 호출 로직
```

#### 3. **ComfyUI**
```python
async def generate_image_comfyui(self, workflow: Dict, inputs: Dict) -> Dict:
    # ComfyUI 워크플로우 실행 로직
```

### API 확장 방법

#### 새 플랫폼 추가
```python
# 1. APIService에 새 메서드 추가
async def generate_image_newplatform(self, params: Dict) -> Dict:
    # 새 플랫폼 API 연동 로직
    pass

# 2. API 선택 UI에 옵션 추가
# ui/api_management_window.py 수정

# 3. 설정 저장/로드 로직 업데이트
# 각 플랫폼별 설정 형식 정의
```

---

## 🧩 모듈 개발 가이드

### 모듈 유형별 가이드

#### 1. **Simple Module (단순 모듈)**
```python
class SimpleModule(BaseMiddleModule):
    '''간단한 UI만 제공하는 모듈'''
    
    def create_widget(self, parent):
        widget = QWidget(parent)
        layout = QVBoxLayout(widget)
        
        # UI 구성
        checkbox = QCheckBox("기능 활성화")
        layout.addWidget(checkbox)
        
        return widget
```

#### 2. **Pipeline Module (파이프라인 모듈)**
```python
class PipelineModule(BaseMiddleModule):
    '''프롬프트 파이프라인에 개입하는 모듈'''
    
    def get_pipeline_hook_info(self):
        return {{'post_processing': True}}
    
    def execute_pipeline_hook(self, stage, context):
        if stage == 'post_processing':
            # 프롬프트 후처리 로직
            context.positive_prompt += ", enhanced quality"
        return context
```

#### 3. **Mode-Aware Module (모드별 설정 모듈)**
```python
class ModeAwareModule(BaseMiddleModule, ModeAwareModule):
    '''플랫폼별로 다른 설정을 갖는 모듈'''
    
    def __init__(self, app_context):
        super().__init__(app_context)
        self.init_mode_aware_settings()
    
    def get_mode_aware_config(self):
        return {{
            'NAI': {{'quality_boost': True}},
            'WebUI': {{'quality_boost': False}},
            'ComfyUI': {{'custom_nodes': ['quality_enhancer']}}
        }}
```

### 모듈 설계 베스트 프랙티스

#### 🎯 **단일 책임 원칙**
- 하나의 모듈은 하나의 명확한 기능만 담당
- 복잡한 기능은 여러 모듈로 분할

#### 🔗 **느슨한 결합**
- 다른 모듈에 직접 의존하지 않고 AppContext를 통해 상호작용
- 이벤트 시스템 활용으로 의존성 최소화

#### ⚡ **비동기 처리**
- 파일 I/O, 네트워크 요청 등은 반드시 QThread 사용
- UI 스레드 블로킹 방지

#### 💾 **상태 관리**
- 모듈 설정은 자동 저장/로드 지원
- 모드별 설정 분리 관리

---

## 📚 병합된 코드 파일 정보

"""

    # 병합된 파일 정보 추가
    for file_info in merged_files_info:
        dir_name = file_info['dir_name']
        files = file_info['files']
        file_count = len(files)
        
        md_content += f"""
### 📦 {dir_name} 모듈
- **파일 개수**: {file_count}개
- **포함된 파일들**: {', '.join(files)}
- **출력 파일**: `temp/{dir_name}.py`
- **주요 역할**: {get_module_description(dir_name)}

"""

    md_content += """
---

## 🤖 AI 협업 프로토콜

### 생성형 AI를 위한 개발 가이드라인

#### 1. **아키텍처 존중 (Architecture First)**
```
❌ 잘못된 접근:
- 기존 코드를 무작정 수정
- 아키텍처 패턴 무시
- 직접적인 모듈 간 참조

✅ 올바른 접근:
- AppContext 중심 설계 이해
- 인터페이스 기반 개발
- 파이프라인 훅 시스템 활용
```

#### 2. **모듈성 및 확장성 (Modularity & Extensibility)**
```python
# ✅ 새 기능은 독립 모듈로 구현
class NewFeatureModule(BaseMiddleModule):
    def __init__(self, app_context):
        super().__init__(app_context)
        # 기존 시스템에 영향 없이 구현

# ❌ 기존 클래스를 직접 수정하여 기능 추가
class ExistingModule:
    def existing_method(self):
        # 기존 메서드에 새 기능 추가 (지양)
```

#### 3. **비동기 처리 필수 (Async Processing Mandatory)**
```python
# ✅ 올바른 비동기 처리
class AsyncWorker(QObject):
    finished = pyqtSignal(dict)
    
    def run(self):
        # 무거운 작업 수행
        result = heavy_computation()
        self.finished.emit(result)

# ❌ UI 스레드 블로킹 (절대 금지)
def heavy_computation():
    time.sleep(5)  # UI 멈춤 발생
```

#### 4. **코드 품질 기준 (Code Quality Standards)**
- **명명 규칙**: 클래스는 PascalCase, 메서드는 snake_case
- **타입 힌팅**: 모든 메서드 시그니처에 타입 명시
- **문서화**: 클래스와 주요 메서드에 docstring 필수
- **에러 처리**: try-except 블록으로 안전한 에러 핸들링

#### 5. **사용자 경험 우선 (UX First)**
- 모든 기능은 사용자 워크플로우를 방해하지 않아야 함
- 일관된 UI/UX 패턴 유지
- 접근성과 직관성 고려

### AI 코드 분석 프로세스

#### 📋 **분석 체크리스트**
1. **구조 파악**
   - [ ] 프로젝트 전체 구조 이해
   - [ ] 핵심 컴포넌트 관계 파악
   - [ ] 데이터 흐름 추적

2. **의존성 분석**
   - [ ] import 구조 분석
   - [ ] AppContext 의존성 확인
   - [ ] 모듈 간 결합도 평가

3. **확장 포인트 식별**
   - [ ] 파이프라인 훅 가능성
   - [ ] 새 모듈 추가 지점
   - [ ] UI 확장 영역

4. **영향도 평가**
   - [ ] 변경이 미치는 범위
   - [ ] 테스트 필요 영역
   - [ ] 호환성 이슈

### 커뮤니티 기여 가이드

#### 🤝 **오픈소스 개발자를 위한 가이드**

1. **개발 환경 설정**
```bash
# 의존성 설치
pip install -r requirements.txt

# 개발용 실행
python NAIA_cold_v4.py
```

2. **기여 워크플로우**
   - Fork & Clone
   - Feature Branch 생성
   - 모듈 단위 개발
   - Pull Request 제출

3. **코드 리뷰 기준**
   - 아키텍처 준수 여부
   - 테스트 코드 포함
   - 문서화 완성도
   - 성능 및 메모리 효율성

---

## 🔧 트러블슈팅

### 일반적인 문제와 해결방법

#### 1. **모듈 로딩 실패**
```
🔴 증상: 새 모듈이 UI에 나타나지 않음
🔧 해결: MiddleSectionController의 create_modules()에 추가 확인
```

#### 2. **파이프라인 훅 미작동**
```
🔴 증상: execute_pipeline_hook이 호출되지 않음
🔧 해결: get_pipeline_hook_info() 반환값 확인
```

#### 3. **UI 응답 없음**
```
🔴 증상: 버튼 클릭 후 UI가 멈춤
🔧 해결: 무거운 작업을 QThread로 이동
```

#### 4. **설정 저장 실패**
```
🔴 증상: 모듈 설정이 저장되지 않음
🔧 해결: ModeAwareModule 믹스인 확인
```

### 디버깅 도구

#### 로그 시스템
```python
# 로깅 활용
import logging
logger = logging.getLogger(__name__)
logger.info("모듈 초기화 완료")
```

#### 컨텍스트 상태 확인
```python
# AppContext 상태 디버깅
print(f"활성 모듈: {{self.app_context.get_active_modules()}}")
```

---

## 📈 성능 최적화 가이드

### 메모리 관리
- **지연 로딩**: 필요시에만 데이터 로드
- **캐시 활용**: 반복 사용 데이터 캐싱
- **리소스 해제**: 명시적 cleanup 구현

### UI 반응성
- **가상화**: 대량 데이터 표시시 가상 스크롤링
- **청크 처리**: 대용량 작업을 작은 단위로 분할
- **진행률 표시**: 장시간 작업에 프로그레스바 제공

---

## 🔄 업데이트 및 마이그레이션

### 버전 호환성
- **설정 마이그레이션**: 이전 버전 설정 자동 변환
- **API 변경사항**: 하위 호환성 유지
- **데이터 포맷**: 점진적 업그레이드 지원

### 의존성 관리
- **라이브러리 업데이트**: 정기적인 의존성 점검
- **보안 패치**: 취약점 대응
- **성능 개선**: 최신 기술 도입

---

> 💡 **AI 개발자 팁**: 이 가이드를 참조하여 NAIA v2.0의 아키텍처를 이해하고, 기존 패턴을 따라 안전하게 기능을 확장하세요. 불확실한 부분이 있다면 AppContext와 인터페이스 파일을 먼저 검토하는 것이 핵심입니다.

---

*📅 문서 생성: {current_time}*  
*🔄 이 문서는 코드 변경 시 자동으로 업데이트됩니다.*  
*🤖 AI 협업 최적화를 위해 지속적으로 개선됩니다.*
"""

    return md_content

def get_module_description(dir_name):
    """모듈별 설명을 반환하는 함수"""
    descriptions = {
        "main": "🚀 애플리케이션 진입점 및 메인 윈도우 (NAIA_cold_v4.py)",
        "core": "⚙️ 시스템 핵심 로직 - 컨텍스트, 프롬프트 파이프라인, API 서비스, 컨트롤러",
        "interfaces": "🔌 추상 인터페이스 - 모듈 계약 정의 및 모드별 설정 자동화",
        "modules": "🧩 기능 모듈 - 자동화, 캐릭터 입력, 프롬프트 엔지니어링 등",
        "ui": "🎨 사용자 인터페이스 - 테마, 컴포넌트, 다이얼로그, 탭 뷰",
        "utils": "🛠️ 유틸리티 - 설정 로드 및 헬퍼 함수",
        "data": "📊 데이터 저장소 - Danbooru 태그, 번역 데이터, 설정 파일",
        "tabs": "📑 탭 모듈 - 이미지 뷰어, 설정, Studio 등 우측 패널 기능",
        "wildcards": "🎲 와일드카드 데이터 - 동적 프롬프트 생성용 텍스트 파일"
    }
    return descriptions.get(dir_name, f"📁 {dir_name} - 프로젝트별 커스텀 모듈")

def merge_py_files():
    """
    현재 디렉토리와 하위 디렉토리를 순회하며 .py 파일들을 찾아서
    디렉토리별로 합친 후 temp 폴더에 저장하는 함수
    """
    
    # temp 폴더 생성 (이미 존재하면 삭제 후 재생성)
    temp_dir = "temp"
    if os.path.exists(temp_dir):
        shutil.rmtree(temp_dir)
    os.makedirs(temp_dir)
    
    # 현재 디렉토리부터 시작
    root_dir = "."
    
    # 트리 구조 생성
    print("🌳 NAIA v2.0 프로젝트 구조 분석 중...")
    tree_lines = generate_tree_structure(root_dir)
    
    # 병합된 파일 정보 저장
    merged_files_info = []
    
    # 각 디렉토리를 순회
    for root, dirs, files in os.walk(root_dir):
        # 제외할 디렉토리 필터링
        dirs[:] = [d for d in dirs if d not in ['__pycache__', 'temp', 'venv', 'not_implement', '.git', '.vscode', 'node_modules', 'output']]
        
        # 현재 디렉토리에서 .py 파일 찾기
        if root == ".":
            # 시작 디렉토리에서는 NAIA_cold_v4.py만 읽기 (없으면 모든 .py 파일)
            py_files = [f for f in files if f == 'NAIA_cold_v4.py']
            if not py_files:  # NAIA_cold_v4.py가 없으면 모든 .py 파일
                py_files = [f for f in files if f.endswith('.py') and not f.startswith('test_')]
        else:
            # 하위 디렉토리에서는 모든 .py 파일 읽기 (테스트 파일 제외)
            py_files = [f for f in files if f.endswith('.py') and not f.startswith('test_')]
        
        if py_files:
            # 디렉토리 이름 결정
            if root == ".":
                dir_name = "main"
            else:
                # 경로에서 디렉토리 이름 추출 (상대 경로)
                dir_name = os.path.basename(root)
            
            # 합친 내용을 저장할 문자열
            merged_content = f"""# 🐍 {dir_name} 모듈 - NAIA v2.0
# 📅 생성 일시: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
# 📦 포함된 파일: {', '.join(py_files)}
# 🎯 모듈 역할: {get_module_description(dir_name)}

# ═══════════════════════════════════════════════════════════════
# 🤖 AI 분석 가이드:
# - 이 모듈의 클래스와 함수들은 NAIA v2.0의 {dir_name} 계층을 구성합니다
# - 각 파일 간의 의존성과 상호작용을 주의깊게 분석하세요
# - 수정 시에는 반드시 AppContext와 인터페이스 계약을 확인하세요
# ═══════════════════════════════════════════════════════════════

"""
            
            # 각 .py 파일의 내용 읽기
            for py_file in sorted(py_files):
                file_path = os.path.join(root, py_file)
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                    
                    merged_content += f"""
# ╔══════════════════════════════════════════════════════════════════╗
# ║ 📄 파일명: {py_file.ljust(50)} ║
# ║ 📂 경로: {file_path.ljust(52)} ║  
# ╚══════════════════════════════════════════════════════════════════╝

{content}

# ╔══════════════════════════════════════════════════════════════════╗
# ║ ✅ {py_file} 끝 {' ' * (59 - len(py_file))} ║
# ╚══════════════════════════════════════════════════════════════════╝

"""
                    
                except UnicodeDecodeError:
                    # UTF-8로 읽기 실패 시 다른 인코딩으로 시도
                    try:
                        with open(file_path, 'r', encoding='cp949') as f:
                            content = f.read()
                        merged_content += f"""
# ╔══════════════════════════════════════════════════════════════════╗
# ║ 📄 파일명: {py_file.ljust(50)} ║
# ║ ⚠️  인코딩: CP949로 읽음 {' ' * 37} ║
# ╚══════════════════════════════════════════════════════════════════╝

{content}

# ╔══════════════════════════════════════════════════════════════════╗
# ║ ✅ {py_file} 끝 {' ' * (59 - len(py_file))} ║
# ╚══════════════════════════════════════════════════════════════════╝

"""
                    except Exception as e:
                        merged_content += f"""
# ╔══════════════════════════════════════════════════════════════════╗
# ║ ❌ 파일명: {py_file.ljust(48)} ║
# ║ 🚨 오류: {str(e)[:50].ljust(50)} ║
# ╚══════════════════════════════════════════════════════════════════╝

# 파일 읽기 실패: {str(e)}

"""
                
                except Exception as e:
                    merged_content += f"""
# ╔══════════════════════════════════════════════════════════════════╗
# ║ ❌ 파일명: {py_file.ljust(48)} ║
# ║ 🚨 오류: {str(e)[:50].ljust(50)} ║
# ╚══════════════════════════════════════════════════════════════════╝

# 파일 읽기 실패: {str(e)}

"""
            
            # temp 폴더에 저장
            output_file = os.path.join(temp_dir, f"{dir_name}.py")
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(merged_content)
            
            # 병합 정보 저장
            merged_files_info.append({
                'dir_name': dir_name,
                'files': py_files,
                'file_count': len(py_files),
                'output_path': output_file
            })
            
            print(f"✅ 생성됨: {output_file}")
            print(f"   📊 {len(py_files)}개 파일 병합 완료 ({root})")
    
    # NAIA v2.0 통합 개발 가이드 생성
    print("\n📖 NAIA v2.0 통합 개발 가이드 생성 중...")
    comprehensive_guide = create_naia_comprehensive_guide(tree_lines, merged_files_info)
    
    # 통합 가이드를 .md 파일로 저장
    guide_file_path = os.path.join(temp_dir, "naia_v2_comprehensive_dev_guide.md")
    with open(guide_file_path, 'w', encoding='utf-8') as f:
        f.write(comprehensive_guide)
    
    print(f"📚 생성됨: {guide_file_path}")
    print(f"   🎯 NAIA v2.0 종합 개발 가이드 및 AI 협업 매뉴얼")

def create_simple_project_structure(tree_lines, merged_files_info):
    """기존 project_structure.md와 호환되는 간단한 문서 생성"""
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    md_content = f"""# 프로젝트 구조 분석 문서 (NAIA v2.0)

> 📋 **생성 일시**: {current_time}
> 🤖 **AI 분석용**: 이 문서는 생성형 AI가 프로젝트 구조를 효율적으로 이해할 수 있도록 작성되었습니다.
> 📚 **상세 가이드**: 더 자세한 정보는 `naia_v2_comprehensive_dev_guide.md`를 참조하세요.

---

## 📖 문서 개요

NAIA v2.0는 AI 이미지 생성을 위한 고급 프롬프트 관리 및 자동화 시스템입니다.
이 문서는 프로젝트의 전체 구조와 각 파일의 역할을 설명합니다.

---

## 🌳 프로젝트 구조

```
{chr(10).join(tree_lines)}
```

---

## 📁 디렉토리 및 파일 설명

### 🎯 주요 디렉토리 구조 분석

#### 🚀 **main**: 애플리케이션 진입점 및 메인 윈도우
#### ⚙️ **core**: 시스템 핵심 로직 - 컨텍스트, API, 컨트롤러
#### 🔌 **interfaces**: 추상 인터페이스 및 모듈 계약
#### 🧩 **modules**: 기능별 독립 모듈
#### 🎨 **ui**: 사용자 인터페이스 컴포넌트
#### 📊 **data**: Danbooru 태그 데이터베이스 및 설정

---

## 🐍 Python 파일 병합 정보

"""

    # 병합된 파일 정보 추가
    for file_info in merged_files_info:
        dir_name = file_info['dir_name']
        files = file_info['files']
        file_count = len(files)
        
        md_content += f"""
### 📦 {dir_name} 모듈
- **파일 개수**: {file_count}개
- **포함된 파일들**: {', '.join(files)}
- **출력 파일**: `temp/{dir_name}.py`

"""

    md_content += """
---

## 🤖 AI 분석 가이드

### 코드 이해를 위한 핵심 포인트

1. **진입점 파악**: `NAIA_cold_v4.py`에서 시작
2. **아키텍처**: AppContext 중심의 모듈형 설계
3. **파이프라인**: PromptProcessor를 통한 단계별 처리
4. **의존성**: 인터페이스 기반 모듈 계약

### 분석 시 주의사항

- **모듈 시스템**: BaseMiddleModule 상속 구조 확인
- **컨텍스트 관리**: AppContext를 통한 의존성 주입
- **파이프라인 훅**: 확장 포인트 활용 방법
- **비동기 처리**: QThread 기반 UI 반응성 유지

### 코드 수정 시 고려사항

1. **아키텍처 존중**: 기존 패턴 및 인터페이스 준수
2. **모듈 독립성**: 느슨한 결합 유지
3. **사용자 경험**: UI 반응성 및 일관성 보장
4. **확장성**: 파이프라인 훅 및 이벤트 시스템 활용

---

> 💡 **상세 정보**: NAIA v2.0의 전체 아키텍처, 개발 가이드, AI 협업 프로토콜은 `naia_v2_comprehensive_dev_guide.md`에서 확인할 수 있습니다.

---

*📅 생성 일시: {current_time}*
*🔄 이 문서는 코드 변경 시 자동으로 업데이트됩니다.*
"""

    return md_content

def main():
    """메인 함수"""
    print("🚀 NAIA v2.0 통합 문서 생성 도구")
    print("=" * 80)
    print("🎯 생성형 AI와 오픈소스 개발자를 위한 종합 가이드 생성")
    print("=" * 80)
    
    merge_py_files()
    
    print("=" * 80)
    print("✅ 완료! temp 폴더를 확인하세요.")
    print()
    print("📚 생성된 문서:")
    print("   🎯 naia_v2_comprehensive_dev_guide.md - 통합 개발 가이드")
    print("   📋 project_structure.md - 기본 구조 문서")
    print("   🐍 *.py - 모듈별 병합 코드 파일")
    print()
    print("🤖 AI 협업 준비 완료!")
    print("=" * 80)

if __name__ == "__main__":
    main()
