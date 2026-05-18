# Round 09 - Result Image Payload helper 분리

## 라운드 8 이후 남은 문제

Plain Remote random은 core service 직접 실행 경로가 생겼지만, 결과 이미지 반환 경로는 여전히 `RemoteBridge(QObject)` 메서드 안에 PNG 판별, PIL 변환, 히스토리 메모리 이미지 payload, 메타 payload 요약 로직이 집중되어 있었다.

이 로직은 WebSession endpoint가 직접 쓰는 기능이며, PyQt widget 자체보다 먼저 분리할 수 있는 pure image/bytes 처리 영역이다.

## 이번 라운드 범위

1. `/api/result/image/png`, `/api/history/image/*`, `/api/history/thumb/*`, `/api/history/meta/*`가 쓰는 pure payload helper를 `core`로 이동한다.
2. 파일 경로 검증, 히스토리 item 탐색, 디스크 thumbnail cache 위치 결정은 아직 `RemoteBridge`에 남긴다.
3. `ImageWindow` 및 history widget 접근 자체는 보존한다. 이번 라운드는 bytes/PIL/metadata helper 분리만 수행한다.
4. endpoint 반환 형식과 기존 WebSession 기능은 유지한다.

## 변경 계획

- `core/result_image_payload_service.py`를 추가한다.
- PNG filename, download disposition, media type 판별, PNG byte 검증, PIL 이미지 PNG 변환을 helper로 이동한다.
- history item image payload, memory thumbnail WEBP payload, metadata summary payload를 helper로 이동한다.
- `RemoteBridge`의 기존 private method는 wrapper로 유지해 외부 테스트/endpoint 호출 계약을 깨지 않는다.
- helper 단위 테스트와 기존 Remote API result/history 테스트를 추가/유지한다.

## 검증 게이트

- `python -m py_compile core/result_image_payload_service.py core/remote_api_server.py`
- `python -m pytest tests/test_result_image_payload_service.py -q`
- result/history 관련 `tests/test_remote_api_status.py` 좁은 테스트
- `python -m pytest tests/test_remote_api_status.py -q`
- `git diff --check`
- WebSession 재시작 후 `/api/status` 확인
- Chrome CDP로 Remote Web 루트 로드 확인

## Static Review

- 새 helper는 `PyQt`/`QObject` dependency가 없다.
- FastAPI endpoint는 여전히 `RemoteBridge` wrapper를 호출하므로 route contract는 유지된다.
- 저장 경로 검증과 history item 탐색은 기존 bridge 메서드를 그대로 사용한다.
- thumbnail 디스크 cache는 기존 `_get_or_create_thumbnail()` 경로를 유지하고, 메모리 history thumbnail만 helper로 이동한다.

## 수행 결과

- `core/result_image_payload_service.py` 추가.
- `RemoteBridge`의 PNG filename/media type/PNG bytes/PIL conversion/history image/meta helper를 pure helper 위임으로 변경.
- 저장된 PNG 파일 bytes 우선, raw PNG bytes 우선, latest WEBP fallback PNG 변환 순서는 유지.
- helper 단위 테스트 7개 추가.

## 검증 결과

- `python -m py_compile core/result_image_payload_service.py core/remote_api_server.py` 통과.
- `python -m pytest tests/test_result_image_payload_service.py -q` 통과: 7 passed.
- result/history 관련 `tests/test_remote_api_status.py` 좁은 테스트 통과: 15 passed, 116 deselected.
- `python -m pytest tests/test_remote_api_status.py -q` 통과: 131 passed.
- `python -m pytest tests/test_result_image_payload_service.py tests/test_prompt_generation_service.py -q` 통과: 10 passed.
- `git diff --check` 통과.
- `--web-shell --web-shell-port 7249` 재시작 후 `/api/status` 정상 응답: `api_mode` NAI, `is_generating` false.
- Chrome CDP `9339`에서 `http://127.0.0.1:7249/` 로드 확인: title `NAIA Remote`, readyState `complete`, Generate/생성 관련 UI 텍스트 확인.
