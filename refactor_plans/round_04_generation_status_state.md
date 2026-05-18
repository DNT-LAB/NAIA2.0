# Round 04 - Generation Status 상태 중앙화

## 라운드 3 이후 남은 문제

Remote Web 생성 상태 payload가 여러 생성 경로에서 직접 만들어지고 있었다. 이 구조는 image generation 단계에서 `is_generating` 플래그가 각 호출 경로마다 따로 관리되는 문제를 키운다.

## 이번 라운드 범위

1. 생성 큐/이미지 생성 파이프라인 자체는 바꾸지 않는다.
2. `RemoteBridge`가 WebSocket `status` payload를 만드는 단일 helper를 갖게 한다.
3. helper가 `_remote_is_generating`을 갱신해 서버가 현재 Remote Web 생성 상태를 보유한다.
4. 기존 status payload의 wire format은 유지한다.

## 변경 계획

- `RemoteBridge._remote_is_generating`을 추가한다.
- `_generation_status_payload()`와 `_send_generation_status()`를 추가한다.
- 기존 `{type: "status", is_generating: ...}` 직접 송신 경로를 helper 호출로 교체한다.
- 기존 generation error/status 회귀 테스트를 유지하고 helper 테스트를 추가한다.

## 검증 게이트

- `python -m py_compile core/remote_api_server.py`
- `python -m pytest tests/test_remote_api_status.py`
- `rg '"type": "status"' core/remote_api_server.py`로 status payload 생성 위치가 helper로 수렴했는지 확인
- WebSession 재시작 후 `/api/status` 확인
- Chrome CDP로 Remote Web 루트 로드 확인

## 수행 결과

- 직접 status dict를 만들던 generate, Artist Thumb, Character Viewer, prompt auto-generate, result broadcast 경로가 `_send_generation_status()`를 사용하게 됐다.
- helper 내부가 `_remote_is_generating`을 갱신한다.
- `status` payload wire format은 `{type: "status", is_generating: bool, message?: str}`로 유지된다.
- `--web-shell --web-shell-port 7244` 재시작에서 `/api/status`가 정상 응답했고, CDP에서 Remote Web 루트가 `NAIA Remote`로 로드됐다.
- 첫 legacy `--web-session` 재시작은 리스닝 후 HTTP 응답이 지연됐지만, 프로세스 정리 후 동일 경로 재시도에서 `/api/status`가 정상 응답했다.

## Static Review

- 큐 상태 payload와 이미지 binary broadcast 순서는 바꾸지 않았다.
- status helper는 `_broadcast_json()` 호출 위치만 모으고, generation controller의 실행 조건이나 큐 정책은 변경하지 않는다.
