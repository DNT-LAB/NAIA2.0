# CLAUDE.md — tabs/storyteller/

스토리텔러 관련 복합 UI가 위치합니다(testbench, story widgets 등). 퍼포먼스와 반응성 유지가 중요합니다.

가이드라인
- 렌더링/이미지/파일 IO는 워커 스레드에서 처리. UI 스레드 블로킹 금지.
- theme/scaling 키 재사용으로 글꼴/패딩 일관 유지.
- 상호작용은 RightView/TabController 경유. 메인 윈도우 직접 접근 지양.
- 탭 수명: `on_tab_activated/deactivated`로 상태 전환, `cleanup()`에서 타이머/스레드 해제.
- 대용량 데이터는 지연 로딩/페이지네이션 고려.
