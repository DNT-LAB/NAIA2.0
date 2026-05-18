# Round 03 - RemoteBridge 서버 소유 상태 축소

## 라운드 2 이후 남은 문제

`TabController`의 startup-visible prototype import는 줄였지만, Remote Web의 options/params는 여전히 많은 지점에서 Qt 위젯 상태를 직접 읽는다. 특히 WebSocket 초기화와 sync는 FastAPI thread에서 `get_options()`를 호출하므로 PyQt6 checkbox 접근이 남아 있다.

## 이번 라운드 범위

1. `get_generation_params()`는 desktop snapshot reader로 유지한다. mode 변경과 preset load의 명시적 desktop reset 계약을 깨지 않기 위해서다.
2. Remote Web에서 변경되는 options/params는 `RemoteBridge` 내부 server-owned state에 먼저 저장한다.
3. Desktop checkbox toggle은 `_on_option_toggled_slot()`에서만 server state로 adopt한다.
4. `set_param`으로 들어온 bool 값은 `"false"` 문자열이 아니라 실제 `False`로 params broadcast에 반영한다.

## 변경 계획

- `RemoteBridge`에 `_remote_option_state`, `_remote_param_values` state를 추가한다.
- 기존 `get_options()`의 Qt widget reader 본문은 `_read_desktop_options()`로 분리한다.
- `_update_cache_all()`은 최초 cache 구성 시점에 server state가 비어 있으면 desktop snapshot으로 seed한다.
- `_do_set_option()`은 server state를 먼저 갱신하고 desktop widget은 mirror side effect로 둔다.
- `_do_set_param()`은 key별 타입 정규화 후 server param state를 갱신하고 full params payload를 broadcast한다.
- `_desktop_control_snapshot_payloads()`는 명시적 reset 지점에서 desktop params를 server state로 adopt한다.

## 검증 게이트

- `python -m py_compile core/remote_api_server.py`
- `python -m pytest tests/test_remote_api_status.py`
- 별도 WebSession 재시작 후 `/api/status` 확인
- Chrome CDP로 Remote Web 루트 로드 확인

## 수행 결과

- `RemoteBridge`에 server-owned option/param state를 추가했다.
- Web-origin option 변경은 server state를 먼저 갱신하고, desktop checkbox는 mirror로만 반영한다.
- Desktop checkbox 변경은 `_on_option_toggled_slot()`에서만 server state에 adopt한다.
- Web-origin param 변경은 `_remote_param_values`에 타입 정규화된 값으로 저장하고, full params payload를 별도 broadcast한다.
- `schema_only` cache인 `_cached_params`는 full selected values로 오염시키지 않았다.
- WebSession 재시작 후 `/api/status`가 `api_mode: NAI`, `is_generating: false`로 응답했다.
- Chrome CDP에서 `NAIA Remote` 문서가 `complete` 상태로 로드되고 WebSocket readyState가 `1`임을 확인했다.
- 재시작 로그에서 `Traceback`, `Error`, `Exception` 매칭은 없었다.

## Static Review

- `_cached_params`는 계속 schema-only cache로 유지한다. full selected params는 `_remote_param_values`와 explicit desktop snapshot에만 존재한다.
- `mode_changed`/`preset_loaded`는 기존처럼 desktop snapshot을 강제로 보낸다.
- WebSocket init에서 쓰는 `get_options()`는 server state를 반환하므로 Qt widget 직접 접근을 줄인다.
- 상태 helper는 기존 `get_generation_params()`가 가진 선택지/schema reader 책임을 침범하지 않는다.
