# Remote Web Tab Restoration — 2026-05-02

## Scope

이 라운드는 임시 배포를 위해 숨겨졌던 Web Shell 우측 탭을 다시 노출하고, 각 탭이 실제로 동작하려면 필요한 데스크탑 기능/브릿지를 식별한 기록이다.

제외 대상: `Storyteller`, `Assets`, `Hooker` 계열은 제거/재설계 예정이므로 복원하지 않는다.

## Restored Tabs

| Tab | 현재 상태 | 필요한 데스크탑 기능/브릿지 |
| --- | --- | --- |
| Result | 기존 동작 유지 | `ImageWindow` history, result asset, context image actions, queue/enhance/upscale endpoints |
| Danbooru | 이번 라운드에서 URL/Post ID 기반 미러링 구현 | `/api/danbooru/post`, Danbooru public post JSON, `data/characteristic_list.txt`, `PromptGenerationController.generate_instant_source_silent()` preview |
| Metadata | 기존 동작 유지 | `/api/result/metadata`, `/api/metadata/extract`, metadata apply/restore bridge |
| Thumb | 탭 노출만 복원 | `ThumbnailsTabModule`의 스타일 썸네일 소스, 선택 상태, 적용 액션을 Web Shell contract로 분리 필요 |
| Artists | 탭 노출만 복원 | `ArtistThumbModule` gallery/rule/randomizer state, `generation_completed_for_artist_thumb` 이벤트 bridge 필요 |
| Studio | 탭 노출만 복원 | `StudioTab`의 frame/grid/sequence 상태와 generation override bridge 필요. 현재 개선 예정 기능과 충돌하지 않게 별도 라운드 권장 |
| Settings | 탭 노출만 복원 | 기존 module popup의 API/Save/Web Session bridge를 top-level tab으로 재배치하는 UI 작업 필요 |

## Danbooru Mirroring

Desktop 원본 탭(`tabs/web_view.py`)은 `QWebEngineView`로 Danbooru 페이지를 열고 HTML에서 `artist/copyright/character/general/meta` 태그를 추출한다. Web Shell에서는 외부 사이트 embed와 로그인 쿠키를 안정적으로 공유하기 어렵기 때문에 public post JSON을 서버가 조회하는 방식으로 대체한다.

이번 구현:

- `core/danbooru_client.py` 추가
- `/api/danbooru/post` 추가
- prompt preview는 FastAPI worker에서 직접 `AppContext`를 건드리지 않고 Qt queued signal을 통해 desktop prompt pipeline에서 계산
- Web Shell `Danbooru` 탭에서 post ID/URL 입력 → JSON 조회 → 태그/이미지/프롬프트 preview 표시
- `data/characteristic_list.txt`에 있는 general tag는 desktop 탭과 동일하게 character 쪽으로 이동
- `Apply Prompt`는 현재 prompt editor에 preview를 적용
- `Generate`는 preview 적용 후 기존 Web Shell generate flow를 호출

남은 차이:

- Desktop QWebEngine의 로그인 세션/브라우징 경험은 Web Shell에서 복제하지 않았다.
- private/restricted post 접근은 public JSON으로 실패할 수 있다.
- Thumb/Artists/Studio/Settings는 이번 라운드에서 숨김 복원과 필요 기능 식별까지만 수행했다.

## Desktop-only Core Features

Remote Web로 옮길 때 별도 bridge가 필요한 데스크탑 전용 기능:

- Native PyQt modal/dialog: `QMessageBox`, `QFileDialog`, destructive confirm, progress dialog
- QWebEngine 기반 브라우저 세션: Danbooru cookies/profile, arbitrary web navigation
- Image action surfaces: standalone Img2Img/Inpaint window, mask editor, Vibe Transfer storage window
- Tag interrogation: onnxruntime presence check, model download progress, `TaggerWorker`, `TagResultWindow`
- Filesystem actions: open folder/file location, native clipboard MIME, user save directory selection
- Long-running generation workflows: `GenerationController`, queue manager, QThread worker cleanup
- Tab detach/dock lifecycle and PyQt widget ownership

## Review Notes

- Web Shell 탭을 보이게 하는 것과 기능 이식은 별개다. 탭을 열었을 때 blocking desktop UI가 필요한 기능은 REST/WS bridge와 non-blocking toast/confirm contract를 먼저 둬야 한다.
- `Storyteller`, `Assets`, `Hooker`는 이번 복원 범위 밖이다. `TabController.REMOVED_TAB_MODULES` 차단은 유지한다.
