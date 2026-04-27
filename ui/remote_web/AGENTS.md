# Remote Web UI 작업 규칙

적용 범위: `ui/remote_web` 이하 전체.

## 목표
- `app.js`와 `style.css`가 다시 거대 단일 파일이 되지 않도록 기능 단위로 작성한다.
- 빌드 단계 없이 브라우저 네이티브 ES module과 정적 파일 제공만으로 동작해야 한다.
- 기존 HTML inline handler 호환성은 유지하되, 실제 구현은 작은 컨트롤러 모듈로 이동한다.

## JavaScript 작성 규칙
- 새 기능 구현은 기본적으로 `js/features/*.mjs` 또는 공통 성격이면 `js/core/*.mjs`에 둔다.
- `app.js`는 부트스트랩, WebSocket 연결, 전역 inline handler 래퍼, 모듈 간 결선만 담당한다.
- `app.js`에 50줄 이상 기능 구현을 새로 추가하지 않는다. 기존 기능을 수정할 때도 가능하면 먼저 모듈로 추출한다.
- feature 모듈은 `createXxxController({ ...deps })` 팩토리 형태를 우선 사용하고, DOM/`ws`/`localStorage`/헬퍼 함수는 명시적으로 주입한다.
- 모듈 내부에서 다른 feature 모듈의 상태를 직접 참조하지 않는다. 필요한 값은 getter/callback으로 받는다.
- HTML에서 호출되는 함수명은 `app.js`에 얇은 래퍼로 남긴다. 래퍼는 보통 1-3줄이어야 한다.
- 새 동적 import promise는 마지막 초기화 `Promise.all([...])`에 추가하고, 실패 로그 메시지를 명확히 남긴다.
- feature 모듈이 500줄을 넘기 시작하면 하위 컨트롤러나 순수 렌더 함수로 재분리한다.

## CSS 작성 규칙
- 새 스타일은 관련 UI 섹션 주석 아래에 모으고, 범용 클래스명 대신 기능 prefix를 사용한다.
- 한 기능의 스타일이 150줄을 넘으면 CSS 분리 계획을 먼저 세우고, 관련 markup/JS와 함께 작은 단위로 분할한다.
- 새 색상/spacing은 기존 Remote Web 팔레트와 컴포넌트 패턴을 재사용한다.

## 검증 규칙
- JS 변경마다 최소 검증:
  - `node --check ui/remote_web/app.js`
  - `node --check` for changed `ui/remote_web/js/**/*.mjs`
  - `git diff --check`
- 새 `.mjs` 파일은 FastAPI `/js/...` 정적 제공 smoke를 확인한다.
- DOM/상태 로직을 분리한 경우 Node 기반 behavior smoke를 추가로 실행한다.
- 기능 단위마다 static review와 테스트 후 checkpoint commit을 만든다.

## 금지
- `app.js`에 새 대형 렌더러, 팝업 컨트롤러, 검색 로직, 히스토리 로직을 직접 추가하지 않는다.
- build tool 도입, 패키지 설치, 외부 CDN 의존성 추가는 별도 요구가 없으면 하지 않는다.
- 리팩터링 중 기존 inline handler, WebSocket message type, DOM id/class 계약을 임의로 바꾸지 않는다.
