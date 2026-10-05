// V5 인페인트 가상 캔버스.
//
// V5 는 인페인트를 별도 팝업으로 빼지 않는다(사용자 지정 2026-08-26).
//
// ⚠️ **캔버스는 결과 이미지와 같은 자리(plane)에 산다.** 아래에 작은 복제본을 하나 더
//    띄우면 어느 쪽이 진짜인지 알 수 없다(사용자 지적). 가상 캔버스는 "원본과 실물을
//    분리해 두는 종이" 지, 별도의 미리보기가 아니다.
//
//    · 화면(스테이지) -> `#inpaintCanvasPlane` (결과 뷰어 위에 겹친다)
//    · 조작(도크)     -> `#inpaintCanvasPanel` (결과 뷰어 **안**에 떠 있고, 접힌다)
//
// 도크는 세션이 사는 동안 떠 있고, 거기서 셋 중 하나를 고른다:
//    편집(캔버스를 본다) / 결과 보기(생성 결과를 본다) / 세션 닫기(끝낸다).
//
// ⚠️ `가상 캔버스` 토글은 **없앴다**(사용자 지적: "역할이 모호합니다"). 실제로 켜나
//    끄나 결과가 같았다 - 캔버스=원본 크기 · 오프셋 0 · 배율 1 · 회전 0 이면
//    `build_payload` 가 원본을 그대로 돌려주고 빈 곳 마스크도 안 생긴다. 그 상태로
//    가는 길은 `초기화` 다.
//
// ⚠️ 계열 판정은 백엔드가 한다(`canvas_supported`). 여기서 모델 표를 한 벌 더 들면
//    커스텀 모델이 등록될 때마다 두 곳이 어긋난다.
//
// 스테이지·격자·드래그는 `posStage.mjs` 를 쓴다. 캐릭터 POS 화면과 같은 몸짓이어야
// 한다는 사용자 지정이고, 그 규칙들은 실측으로 얻은 것이라 두 번 짜면 한쪽이 틀린다.
//
// ⚠️ 좌표는 전부 **캔버스 픽셀**로 주고받는다. 화면이 줄어 있어도 그대로다 - 화면
//    비율로 보내면 캔버스 크기를 바꾼 순간 전부 어긋난다.
//
// ⚠️ 아래 import 의 캐시 키는 posStage 를 고칠 때도 **함께** 바꾼다. 이 파일 키만
//    올리면 브라우저가 옛 posStage 를 계속 쓴다 - import 는 URL 로 캐시된다.
import {contentToPercent, createPosStage, gridSvg} from './posStage.mjs?v=20260826-cancel1';

// 밴드를 못 받았을 때만 쓰는 폴백(옛 목록). 평소에는 백엔드가 내려 준 NAI 밴드를
// 쓴다 - 여기에 목록을 박아 두면 Params 탭과 갈라져, 실제로 **유료권이 통째로
// 빠져 있었다**(Large/Wallpaper 가 없어 인페인트 도중 유료 해상도로 갈 길이 없었다).
const CANVAS_SIZES = ['832 x 1216', '1216 x 832', '1024 x 1024', '1152 x 896', '896 x 1152'];
const GRID_KEY = 'naia.inpaintcanvas.grid.v1';
// 레이어 목록을 펼쳐 둘지(사용자마다 기억한다).
const LAYERS_OPEN_KEY = 'naia.inpaintcanvas.layers.v1';

// 레이어 목록 · 단축키 단추에 쓰는 작은 아이콘(글자보다 덜 자리 먹고, 곁눈으로 갈린다).
const svg = (body, size = 14) => `<svg viewBox="0 0 24 24" width="${size}" height="${size}" fill="none"`
  + ` stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${body}</svg>`;
const ICON = {
  layers: svg('<path d="M12 3 2.5 8 12 13l9.5-5z"/><path d="m2.5 12.5 9.5 5 9.5-5"/><path d="m2.5 16.5 9.5 5 9.5-5"/>', 13),
  eye: svg('<path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>', 13),
  eyeOff: svg('<path d="M3 3l18 18"/><path d="M10.6 5.1A10.4 10.4 0 0 1 12 5c6.4 0 10 7 10 7a17 17 0 0 1-3.2 4.2M6.6 6.6C3.8 8.4 2 12 2 12s3.6 7 10 7c1.7 0 3.2-.5 4.5-1.2"/><path d="M9.9 9.9a3 3 0 0 0 4.2 4.2"/>', 13),
  trash: svg('<path d="M4 7h16"/><path d="M10 11v6M14 11v6"/><path d="M6 7l1 13h10l1-13"/><path d="M9 7V4h6v3"/>', 13),
  up: svg('<path d="m6 15 6-6 6 6"/>', 13),
  down: svg('<path d="m6 9 6 6 6-6"/>', 13),
  fold: svg('<path d="m9 6 6 6-6 6"/>', 13),
  plus: svg('<path d="M12 5v14M5 12h14"/>', 12),
  upload: svg('<path d="M12 15V4"/><path d="m7 9 5-5 5 5"/><path d="M4 15v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3"/>', 22),
  keys: svg('<rect x="2.5" y="6" width="19" height="12" rx="2"/><path d="M6 10h.01M10 10h.01M14 10h.01M18 10h.01M7 14h10"/>', 14),
  // 우클릭 메뉴
  flipX: svg('<path d="M12 3v18"/><path d="M8 7.5 3.5 12 8 16.5z"/><path d="m16 7.5 4.5 4.5-4.5 4.5z"/>'),
  flipY: svg('<path d="M3 12h18"/><path d="M7.5 8 12 3.5 16.5 8z"/><path d="m7.5 16 4.5 4.5 4.5-4.5z"/>'),
  rotCw: svg('<path d="M20 12a8 8 0 1 1-2.7-6"/><path d="M20 4v5h-5"/>'),
  rotCcw: svg('<path d="M4 12a8 8 0 1 0 2.7-6"/><path d="M4 4v5h5"/>'),
  reset: svg('<path d="M4 12a8 8 0 1 0 2.7-6"/><path d="M4 4v5h5"/><circle cx="12" cy="12" r="1.6"/>'),
  paste: svg('<rect x="6" y="5" width="12" height="16" rx="2"/><path d="M9 5V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v1"/><path d="M9 12h6M9 16h4"/>'),
};

// 도크 머리의 단축키 툴팁. 예전에는 머리 줄에 글자로 늘어놓아 좁은 화면에서 잘렸다
// ("…숫자 위치는 P…" - 사용자 제보 2026-10-03). 무엇을 누르면 되는지는 필요할 때만 본다.
const CANVAS_KEYS = [
  [['끌기'], '레이어 이동 · 누른 자리의 레이어가 골라집니다'],
  [['휠'], '확대 / 축소 (커서 자리 기준)'],
  [['Ctrl', '휠'], '회전'],
  [['가운데 끌기'], '확대 · Ctrl 을 쥐면 회전'],
  [['방향키'], '1px 이동 · Shift 16px'],
  [['Ctrl', 'Z'], '이동 · 회전 되돌리기'],
  [['Ctrl', 'V'], '이미지를 새 레이어로 붙여넣기'],
  [['0'], '고른 레이어 초기화'],
  [['우클릭'], '반전 · 90° 회전 메뉴'],
  [['Del'], '고른 레이어 지우기 (묻고 지웁니다)'],
];

// 백엔드 `clamp_scale` 과 같은 한계. 어긋나면 화면이 보내 놓고 다른 값을 되받는다.
const SCALE_MIN_PCT = 10;
const SCALE_MAX_PCT = 400;
// 변형은 서버가 이미지를 다시 합성한다. 슬라이더가 움직이는 동안 매번 보내면 그만큼
// 합성이 쌓이므로 마지막 값만 보낸다.
// ⚠️ 이 값이 **체감 지연의 대부분**이다. 백엔드를 13~66ms 로 줄이고 나니(전송본 PNG를
//    생성 때로 미루고, 미리보기를 JPEG 로 바꾸고, 베이스를 캐시) 200ms 가 남은 가장 큰
//    항목이 됐다. 120ms 면 200% 기준 합성이 절반쯤 쉬어 느린 기기에서도 밀리지 않는다.
const TRANSFORM_DEBOUNCE_MS = 120;

// 중앙 버튼 드래그 감도. 세로 3px 당 1% - 한 화면(약 700px)에 대략 배율 전 구간이 든다.
const MIDDLE_SCALE_PX_PER_PCT = 3;
// 회전은 각도를 그대로 따라가되, 중앙 가까이에서는 각도가 튀므로 그 안은 무시한다.
const ROTATE_DEAD_ZONE_PX = 40;
// 베이스 미세 이동. Shift 는 자동 마스킹 반경과 같은 값으로 맞춘다.
const NUDGE_PX = 1;
const NUDGE_PX_COARSE = 16;
// 휠 한 칸. Shift 를 누르면 다섯 배로 간다(방향키와 같은 손버릇).
const WHEEL_SCALE_PCT = 2;
const WHEEL_ROTATE_DEG = 1;
const WHEEL_COARSE = 5;

const ratio = (value) => (Number(value) || 0).toFixed(2);
const clampPct = (v) => Math.max(SCALE_MIN_PCT, Math.min(SCALE_MAX_PCT, Math.round(Number(v) || 100)));
const wrapDeg = (v) => ((Math.round(Number(v) || 0) % 360) + 360) % 360;

export function createInpaintCanvasPanel({
  panel, plane, viewer, escHtml, setModuleParam, showToast,
  // 프롬프트 복원이 이미지를 고른 뒤 무엇을 되살릴지 묻는다(사용자 지정 2026-09-10).
  showConfirmDialog = null,
  openMaskEditor = () => {},
  // 마스크를 지우는 **하나뿐인 목**. 서버만 지우면 브라우저에 남은 초안이 살아 있어,
  // 다시 [마스크 그리기] 를 열면 지운 것이 그대로 되살아난다(사용자 제보 2026-08-30).
  // 실측: 지우기 전 31,232px -> 지운 뒤 도크는 "빈 곳 자동" 인데 에디터는 여전히 31,232px.
  onClearMask = () => {},
  onSlider = () => {},
  onRepeat = () => {},
  onGenerate = () => {},
  // 캐릭터 에셋 액자 모드에서만 쓰인다(사용자 지정 2026-08-31).
  //   'frame'     -> 지금 놓인 그대로 저장(생성 없음 = 0 Anlas)
  //   'generated' -> 인페인트로 빈 곳을 메운 뒤 그 결과를 저장
  onSaveCharacterAssetFrame = () => {},
  // 지금 생성이 도는 중인가(사용자 지정 2026-08-29: 생성 중에는 또 못 누른다).
  isGenerating = () => false,
  onClose = () => {},
  onVisibility = () => {},
  getResolutionBands = () => [],
  getFreePixels = () => 1048576,
  // 우클릭 메뉴의 [이미지 붙여넣기]. 클립보드를 읽는 길은 앱이 쥐고 있다(`resultImageInput`) -
  // 읽어 온 그림은 붙여넣기 훅을 거쳐 `acceptPastedImage` 로 돌아온다. 없으면 그 줄을 안 띄운다.
  onRequestPaste = null,
}) {
  let state = null;
  let restorePop = null;   // 프롬프트 복원 - 출처 고르는 팝업
  let stageEl = null;
  let posStage = null;
  // 편집(캔버스) / 결과 보기. 화면에서만 쓰는 값이라 서버에 안 보낸다 - 다른 기기에서
  // 보던 화면을 여기서 바꿔 버리면 안 된다.
  let viewMode = 'edit';
  // 드래그 중 계산한 베이스 오프셋. DOM 에 붙여 두면 재렌더에 함께 날아간다.
  let pendingOffset = null;
  // ── 되돌리기 (사용자 지정 2026-08-30: "실수로 드래그하면 되돌릴 방법이 없다") ──
  //
  // **되돌릴 대상은 이동과 회전뿐이다**(사용자 지정). 확대는 뺀다 - 커서를 붙잡고
  // 굴리는 조작이라 한 눈금이 곧 한 단계가 아니고, 되돌리면 붙잡았던 지점이
  // 어긋나 오히려 더 헷갈린다.
  //
  // ⚠️ 초기화(`base_reset`)는 **되돌리기 대상이 아니다.** 그것은 확대까지 함께
  //    되돌리는데, 여기서 이동·회전만 복구하면 "되돌렸다" 면서 반만 돌아온다 -
  //    반쪽 복구는 거짓말이라 아예 안 건다.
  // ⚠️ 쌓는 것은 **바뀌기 전 값**이다. 바뀐 뒤에 쌓으면 한 번 눌러도 제자리다.
  const UNDO_LIMIT = 20;
  let undoStack = [];
  // 되돌리는 도중에 다시 쌓지 않는다 - 안 막으면 되돌리기가 자기 자신을 기록해
  // 두 번째 누름이 원래대로 돌아온다(무한 왕복).
  let undoApplying = false;
  // 드래그 **한 번**을 한 단계로 묶는다. 회전 드래그는 `pointermove` 마다
  // `applyTransform` 을 부르므로, 안 묶으면 한 번 끄는 동안 20칸이 통째로 밀린다
  // (Codex 리뷰 2026-08-30 BLOCK 2). 시작할 때 한 번만 쌓고 그 뒤로는 잠근다.
  let undoGestureOpen = false;
  // POS 에 들어오기 **전에** 보던 모드. 나갈 때 돌려주려고 적어 둔다(빈 문자열이면
  // POS 가 모드를 바꾼 적이 없다는 뜻이다).
  let posEntryViewMode = '';
  // [자동 마스킹] 을 누른 뒤 결과를 기다리는 중인가(사용자 지정 2026-08-27:
  // "시각적 피드백이 필요하다"). 칠하는 데 성공하면 상태가 오고, 그때 한 번
  // 번쩍이며 말해 준다.
  //
  // ⚠️ **빈 곳이 없으면 상태가 아예 안 온다.** 백엔드가 module_state 대신 토스트
  //    하나만 돌려주기 때문이다(`_auto_mask` 의 "빈 곳이 없습니다"). 그래서 이
  //    깃발은 시간으로도 내려간다 - 안 그러면 켜진 채 남아 **다음 상태**에서
  //    엉뚱하게 "칠했습니다" 라고 말한다.
  let autoMaskPending = false;
  let autoMaskTimer = 0;
  // 방금 칠한 것을 한 번 번쩍여 눈에 알린다. 그리고 나면 꺼진다(계속 깜빡이면 방해다).
  let flashMask = false;
  // 생성이 끝나 **자동으로** 결과 보기로 넘어간 순간에만 선다. 사용자가 직접 누른
  // 전환에는 안 선다 - 자기가 누른 것은 이미 안다.
  let flashModes = false;
  // 슬라이더를 끄는 동안에는 다시 그리지 않는다 - 끌던 input 이 교체되면 드래그가 끊긴다.
  let rangeDragging = false;
  // 슬라이더를 끌거나 반복 칸에 쓰는 동안 **건너뛴 도크 갱신이 있다**는 표시. 조작이 끝나면
  // 그때 그린다(`settleDock`). 그 사이의 조작은 `dockLayerId()` 가 지킨다 - 도크의 단추와
  // 슬라이더는 **도크가 보여 주는 레이어**를 고친다.
  let dockStale = false;
  const transformTimers = {};
  // 레이어 목록(뷰어 오른쪽에 떠 있다). 도크와 따로 그린다 - 도크는 아래 가운데에 있고
  // 목록은 길어질 수 있어서 한 상자에 넣으면 캔버스를 그만큼 가린다.
  let layersEl = null;
  let layerPop = null;        // [+ 이미지] 를 눌러 연 고르기 팝업
  let layerUploading = false;
  // 고른 레이어. **이 화면만의 값**이다(보기 모드 `viewMode` 와 같은 이유) - 서버에 두면
  // 다른 탭이 고르는 순간 이 탭의 슬라이더 · 끌기 대상이 말없이 바뀐다(Codex 재리뷰
  // 2026-10-03: 화면은 L1 인데 `layer_scale {id:'L2'}` 가 나갔다). 늦게 온 echo 가
  // 선택을 되돌리는 경합도 같은 뿌리였다 - 서버 값을 안 읽으면 둘 다 없다.
  let activeId = 'base';

  const read = (key, fallback) => {
    try { return localStorage.getItem(key) ?? fallback; } catch (_) { return fallback; }
  };
  const write = (key, value) => {
    try { localStorage.setItem(key, value); } catch (_) {}
  };

  let showGrid = read(GRID_KEY, '1') !== '0';
  let showLayers = read(LAYERS_OPEN_KEY, '1') !== '0';

  const canvasSize = () => ({
    w: Number(state?.canvas_width) || 0,
    h: Number(state?.canvas_height) || 0,
  });

  // ── 레이어(사용자 지정 2026-10-03) ─────────────────────────────────────
  // 베이스는 서버의 `base_*` 키 그대로고(예전 계약), 덧붙인 이미지는 `layers` 에 함께
  // 실려 온다(아래 -> 위, 베이스 포함). 이동·확대·회전·되돌리기는 **고른 레이어**
  // (`active_layer`)에 먹는다 - 손으로 고르거나, 그림 위를 누르면 그 자리 레이어가 골라진다.

  /** 아래 -> 위. 레이어를 모르는 옛 서버면 베이스 한 줄을 지어 내 예전처럼 돈다. */
  function layerRows() {
    const rows = Array.isArray(state?.layers) ? state.layers : [];
    if (rows.length || !state) return rows;
    return [{
      id: 'base', kind: 'base', name: '원본', visible: true,
      offset_x: state.base_offset_x, offset_y: state.base_offset_y,
      width: state.base_width, height: state.base_height,
      placed_width: state.placed_width, placed_height: state.placed_height,
      scale: state.base_scale, rotation: state.base_rotation, thumb: '',
    }];
  }
  const extraLayerCount = () => layerRows().filter(row => row.id !== 'base').length;
  /** 고른 레이어. 지워졌으면 원본으로 돌아간다. */
  function activeLayerId() {
    return layerRows().some(row => row.id === activeId) ? activeId : 'base';
  }
  const layerRow = (id) => layerRows().find(row => row.id === id) || null;

  /** 레이어의 지금 기하(캔버스 픽셀). `placedW/H` 는 회전까지 먹인 뒤의 축정렬 상자다. */
  function tx(id = activeLayerId()) {
    const row = layerRow(id) || {};
    const scale = Number(row.scale) || 1;
    const w = Number(row.width) || 0;
    const h = Number(row.height) || 0;
    return {
      id,
      x: Math.round(Number(row.offset_x) || 0),
      y: Math.round(Number(row.offset_y) || 0),
      scale,
      rotation: Number(row.rotation) || 0,
      w,
      h,
      placedW: Number(row.placed_width) || Math.round(w * scale),
      placedH: Number(row.placed_height) || Math.round(h * scale),
    };
  }

  /** 서버 echo 전에 화면 값을 먼저 맞춘다(규칙 3). 베이스는 예전 `base_*` 키에도 적는다 -
   *  두 곳이 갈리면 다음 조작이 어느 쪽에서 시작할지 알 수 없다. */
  function patchLayer(id, patch) {
    if (!state) return;
    const row = (Array.isArray(state.layers) ? state.layers : []).find(item => item.id === id);
    if (row) Object.assign(row, patch);
    if (id !== 'base') return;
    if ('offset_x' in patch) state.base_offset_x = patch.offset_x;
    if ('offset_y' in patch) state.base_offset_y = patch.offset_y;
    if ('scale' in patch) state.base_scale = patch.scale;
    if ('rotation' in patch) state.base_rotation = patch.rotation;
  }
  const setLayerOffset = (id, x, y) => patchLayer(id, {offset_x: x, offset_y: y});

  /** 레이어 이동 한 번. ⚠️ 베이스는 **예전 키**(`base_offset`)로 보낸다 - 그쪽 규칙
   *  (캔버스 자동 켜기 · 앵커)은 실측으로 맞춰 둔 것이라 새 길로 우회하지 않는다. */
  function sendOffset(id, x, y) {
    if (id === 'base') send('base_offset', {x, y});
    else send('layer_offset', {id, x, y});
  }

  /** 확대/회전은 마지막 값만, 레이어마다 따로 묶는다(다른 레이어의 값이 덮이지 않게). */
  function sendLayerTransform(id, key, payload) {
    if (id === 'base') sendTransform(key === 'scale' ? 'base_scale' : 'base_rotation', payload);
    else sendTransform(`layer_${key}:${id}`, {...payload, id}, `layer_${key}`);
  }

  /** 그림 위의 한 점(캔버스 픽셀)에서 **맨 위에 보이는** 레이어. 없으면 ''.
   *
   *  축정렬 상자가 아니라 **돌린 사각형**으로 잰다 - 돌린 그림의 모서리 바깥 쐐기를
   *  눌렀는데 그 레이어가 잡히면 아래 레이어를 영영 못 고른다.
   *  ⚠️ PIL 은 양의 각도를 **반시계**로 돌린다(y 가 아래로 자라는 화면 좌표). 점을
   *     거꾸로(시계 방향) 돌려 레이어 자신의 좌표로 되돌린 뒤 반폭과 비교한다.
   */
  function layerAt(point) {
    if (!point) return '';
    const rows = layerRows();
    for (let i = rows.length - 1; i >= 0; i -= 1) {
      const row = rows[i];
      if (row.visible === false) continue;
      const t = tx(row.id);
      const halfW = (t.w * t.scale) / 2;
      const halfH = (t.h * t.scale) / 2;
      if (!(halfW > 0) || !(halfH > 0)) continue;
      const dx = point.x - (t.x + t.placedW / 2);
      const dy = point.y - (t.y + t.placedH / 2);
      const rad = (t.rotation * Math.PI) / 180;
      const lx = dx * Math.cos(rad) - dy * Math.sin(rad);
      const ly = dx * Math.sin(rad) + dy * Math.cos(rad);
      if (Math.abs(lx) <= halfW && Math.abs(ly) <= halfH) return row.id;
    }
    return '';
  }

  /** 레이어를 고른다 - 이 화면에서만(도크 슬라이더 · 목록 · 테두리). 서버로는 안 보낸다(`activeId`). */
  function selectLayer(id) {
    if (!state || !layerRow(id) || id === activeLayerId()) return;
    // 미뤄 둔 변형은 원래 레이어 몫이다 - 먼저 흘려보낸다.
    flushTransforms();
    activeId = id;
    refreshChrome();
  }

  function send(key, value) {
    try { setModuleParam('img2img', key, value); }
    catch (error) { showToast?.(`캔버스 설정 실패: ${error.message}`, 'error'); }
  }

  /** 변형은 마지막 값만 보낸다. 슬라이더 한 번에 수십 번 합성시키지 않는다.
   *  `key` 는 묶음 이름(타이머), `param` 은 실제로 보낼 파라미터다(레이어는 둘이 다르다). */
  function sendTransform(key, value, param = key) {
    if (transformTimers[key]) clearTimeout(transformTimers[key].id);
    transformTimers[key] = {
      value,
      param,
      id: setTimeout(() => {
        delete transformTimers[key];
        send(param, value);
      }, TRANSFORM_DEBOUNCE_MS),
    };
  }

  /** 미뤄 둔 변형을 **지금 당장** 보낸다.
   *
   *  ⚠️ 이걸 안 하면 **돈이 잘못 나간다.** 휠을 굴린 뒤 120ms 안에 `인페인트 생성` 을
   *     누르면, 백엔드는 아직 옛 배율로 굽고 요청하고, 새 배율은 큐에 들어간 뒤에야
   *     도착한다(Codex 리뷰 2026-08-26 BLOCK 1). 초기화·세션 닫기도 마찬가지로,
   *     미뤄 둔 값이 뒤늦게 되살아나 방금 되돌린 것을 다시 적용한다.
   *  ⚠️ `img2imgPanel.generate()` 의 `flushSliders()` 는 **강도/노이즈용**이다.
   *     여기 타이머는 그것과 별개라 저쪽이 대신 비워 주지 않는다.
   */
  function flushTransforms() {
    Object.keys(transformTimers).forEach(key => {
      const pending = transformTimers[key];
      if (!pending) return;
      clearTimeout(pending.id);
      delete transformTimers[key];
      send(pending.param || key, pending.value);
    });
  }

  // ── 렌더 ────────────────────────────────────────────────────────────────
  function render(next) {
    // [자동 마스킹] 의 답이 도착했다. 빈 곳이 없으면 화면이 거의 안 바뀌므로
    // **무슨 일이 있었는지 말해 준다** - 눌렀는데 조용하면 고장으로 읽힌다.
    // `lifecycle_only` = 생성 생명주기만 실린 갱신(img2img_generation_state).
    // 자동 마스킹의 답이 아니므로 대기표를 삼키면 안 된다 - 삼키면 진짜 결과가
    // 왔을 때 알릴 대상이 없어 눌러도 조용한 채로 끝난다.
    if (autoMaskPending && next && next.module_id === 'img2img' && !next.lifecycle_only) {
      autoMaskPending = false;
      clearTimeout(autoMaskTimer);
      // 실패(빈 곳 없음)는 백엔드가 이미 말한다 - 여기서 또 말하면 두 번 뜬다.
      if (next.has_mask) {
        showToast?.('빈 곳과 그 경계를 칠했습니다', 'success');
        flashMask = true;                 // 아래 renderPlane 이 한 번 번쩍인다
      }
    }
    // ⚠️ **그림이 바뀌면 되돌리기 기록도 버린다.** 세션은 살아 있는데 다른 그림을
    //    열면(`window_id` 가 바뀐다) 남의 그림에서 잰 자리가 이 그림에 적용된다.
    if (next && String(next.window_id || '') !== String(state?.window_id || '')) {
      undoStack = [];
      activeId = 'base';          // 다른 그림이다 - 옛 그림의 레이어를 고른 채 남기지 않는다
      closeLayerMenu();           // 옛 그림에서 연 메뉴가 새 그림을 고치지 않게
    }
    if (next) state = next;
    // 메뉴가 가리키던 레이어가 사라졌으면(다른 탭이 지웠다) 닫는다.
    if (layerMenu && !layerRow(layerMenu.dataset.icMenuLayer)) closeLayerMenu();
    if (!panel) return;
    // ⚠️ 조작 중에는 절대 다시 그리지 않는다(posStage 규칙 1). 서버 echo 가 와도
    //    마찬가지다 - 끌고 있던 노드가 교체되면 그 조작이 통째로 무시된다.
    if (posStage?.isDragging()) return;
    if (rangeDragging || typingInPanel()) {
      // 슬라이더를 끌거나 반복 칸에 쓰는 중이면 **도크만** 건너뛴다(끌던 input 이 교체되면
      // 드래그가 끊긴다). 캔버스는 그린다 - 그 사이 다른 탭이 레이어를 숨기거나 옮기면
      // 화면은 옛 그림인데 [인페인트 생성] 은 서버의 새 합성으로 나간다(Codex 재리뷰
      // 2026-10-03). plane 은 도크와 다른 노드라 그려도 입력이 안 끊긴다.
      if (state?.active && state.canvas_supported && !panel.hidden) renderPlane();
      dockStale = true;
      return;
    }
    // 캔버스는 V5 인페인트 전용이다. 다른 계열에서 띄우면 팝업과 조작 수단이 둘로
    // 갈려 어느 쪽이 진짜인지 알 수 없게 된다.
    const show = !!(state?.active && state.canvas_supported);
    if (show !== !panel.hidden) onVisibility(show);
    if (!show) {
      disarmSessionInput();     // 세션이 끝나면 입력을 **즉시** 돌려준다(사용자 지정)
      panel.innerHTML = '';
      panel.hidden = true;
      viewMode = 'edit';        // 다음 세션은 편집부터 시작한다
      // 되돌리기 기록은 **세션의 것**이다. 다음 세션으로 넘기면 남의 그림의 자리를
      // 이 그림에 적용하게 된다.
      undoStack = [];
      // ⚠️ 번쩍임 표도 여기서 내린다. 세션이 없을 때 `showResult()` 가 불리면
      //    (일반 생성 결과도 이 자리를 지난다) 표만 서고 그릴 도크가 없어, 다음에
      //    세션을 열자마자 이유 없이 번쩍인다 - 표식이 값싸진다.
      flashModes = false;
      renderPlane();
      return;
    }
    armSessionInput();
    panel.hidden = false;
    // 접기는 없앴다(사용자 지정 2026-08-29: "실용성이 없다"). 도크는 늘 펼쳐져 있고,
    // 닫는 길은 `세션 닫기` 와 헤더의 Inpaint 버튼 두 곳이다.
    panel.className = 'inpaint-canvas-panel';
    // 도크를 다시 그리면 팝업이 통째로 지워진다 - 손잡이만 남으면
    // 다음 클릭이 이미 사라진 노드를 지우려 든다.
    restorePop = null;
    drawDock();
    flashModes = false;          // 한 번만 번쩍인다(그린 순간 표를 내린다)
    renderPlane();
  }

  /** 캔버스 해상도 목록.
   *
   *  ⚠️ 지금 크기가 프리셋에 없으면 `<select>` 는 **첫 항목**을 보여 준다 - 화면이
   *     실제와 다른 해상도를 말하게 된다. 원본 크기는 프리셋과 무관하고(사용자가
   *     아무 이미지나 보낼 수 있다) `초기화` 는 그 원본 크기로 돌아가므로, 늘 있을
   *     수 있는 일이다. 없으면 맨 앞에 끼워 넣는다.
   */
  const bare = (t) => String(t).replace(/\s+/g, '');

  /** 밴드별로 묶은 해상도 목록. 없으면 옛 폴백 하나로 묶는다.
   *
   *  ⚠️ 유료권(1MP 초과)은 **묶음 이름에** 표시한다. 항목마다 글자를 붙이면 30줄이
   *     전부 길어져 무엇이 무엇인지 안 보인다 - 어차피 금액은 Generate 버튼의 칩이
   *     정확히 말한다.
   */
  function sizeGroups() {
    const bands = getResolutionBands() || [];
    if (!bands.length) return [{label: '', items: CANVAS_SIZES.slice()}];
    const free = Number(getFreePixels()) || 1048576;
    return bands.map(band => {
      const items = (band.resolutions || []).map(String);
      const paid = items.some(text => {
        const [bw, bh] = text.split('x').map(v => parseInt(v.trim(), 10));
        return bw > 0 && bh > 0 && bw * bh > free;
      });
      return {label: `${band.label || band.id}${paid ? ' · Anlas' : ''}`, items};
    }).filter(g => g.items.length);
  }

  function sizeOptions(w, h) {
    const current = (w > 0 && h > 0) ? `${w} x ${h}` : '';
    const groups = sizeGroups();
    const known = groups.some(g => g.items.some(label => bare(label) === bare(current)));
    const opt = (label) => {
      const [sw, sh] = label.split('x').map(v => parseInt(v.trim(), 10));
      const sel = (sw === w && sh === h) ? ' selected' : '';
      return `<option value="${escHtml(label)}"${sel}>${escHtml(label)}</option>`;
    };
    // ⚠️ 지금 크기가 목록에 없을 수 있다(사용자가 아무 이미지나 보낼 수 있고,
    //    `초기화` 는 원본 크기로 돌아간다). 없으면 `<select>` 가 **첫 항목**을
    //    보여 줘서 화면이 실제와 다른 해상도를 말한다 - 맨 앞에 끼워 넣는다.
    const head = (current && !known) ? `<option value="${escHtml(current)}" selected>${escHtml(current)}</option>` : '';
    return head + groups.map(g => (
      g.label
        ? `<optgroup label="${escHtml(g.label)}">${g.items.map(opt).join('')}</optgroup>`
        : g.items.map(opt).join('')
    )).join('');
  }

  // 좌우 2단(사용자 지정 2026-08-26). 왼쪽은 **캔버스의 기하**, 오른쪽은 **인페인트의
  // 실행**이다. 한 단으로 늘어놓으면 세 줄이 넉 줄이 되고, 그만큼 캔버스가 눌린다.
  /** 프롬프트 복원 단추. 머리줄의 [편집 | 결과 보기] 옆이 자리다(사용자 지정 2026-09-10).
   *
   *  제보: 포토샵으로 고쳐 EXIF 가 사라진 그림을 들여와 인페인트하면 캐릭터·메인
   *  프롬프트를 잃는다. 세션은 **그 그림의 캐릭터만** 쓰므로(라이브 UI 폴백 없음) 빈 것
   *  자체는 의도된 동작이고, 없던 것은 사용자가 출처를 지목하는 길이다.
   *
   *  ⚠️ 처음엔 캐릭터 패널에 줄을 하나 더 얹었다가 물렀다 - 줄 하나를 통째로 먹으면서
   *     버튼만 놓아 **빈 공간만 늘었다**(사용자 지적). 여기는 이미 있는 줄이라 폭만 쓴다.
   *  캐릭터가 비어 있으면 색을 준다 - 자리를 더 쓰지 않고 눈에만 띄게 한다.
   */
  function restoreButtonHtml() {
    const empty = !((state && state.characters) || []).some(c => c && String(c.prompt || '').trim());
    return `<button type="button" class="ic-btn ic-restore${empty ? ' is-empty' : ''}"`
      + ` data-ic="restore-prompts"`
      + ` title="${empty
          ? '이 이미지에는 캐릭터 프롬프트가 없습니다. 다른 이미지에서 가져옵니다'
          : '다른 이미지에서 프롬프트를 가져옵니다'}">프롬프트 복원</button>`;
  }

  /** 단축키 툴팁. 단추에 올리거나 초점을 주면 위로 카드가 뜬다(CSS `:hover` · `:focus-within`).
   *
   *  ⚠️ `title` 을 달지 않는다 - 앱의 전역 툴팁(`data-naia-title`)이 그것을 빨아들여
   *     카드 위에 한 줄짜리 툴팁이 하나 더 뜬다.
   */
  function keysHtml() {
    const rows = CANVAS_KEYS.map(([combo, label]) => `<div class="ic-keys-row">`
      + `<span class="ic-keys-combo">${combo.map(key => `<kbd>${escHtml(key)}</kbd>`).join('')}</span>`
      + `<span class="ic-keys-label">${escHtml(label)}</span></div>`).join('');
    return `<span class="ic-keys">`
      + `<button type="button" class="ic-btn ic-icon-btn ic-keys-btn" aria-label="캔버스 단축키">${ICON.keys}</button>`
      + `<span class="ic-keys-card" role="tooltip">`
      + `<span class="ic-keys-title">캔버스 조작</span>${rows}`
      + `<span class="ic-keys-foot">캐릭터 숫자 위치는 POS 에서 고칩니다</span>`
      + `</span></span>`;
  }

  /** 지금 이동·확대·회전이 먹는 레이어. 레이어가 둘 이상일 때만 띄운다 - 하나뿐이면
   *  당연한 것을 굳이 적어 머리 줄만 붐빈다. 누르면 레이어 목록을 편다. */
  function targetChipHtml() {
    if (!extraLayerCount()) return '';
    const row = layerRow(activeLayerId());
    return `<button type="button" class="ic-target" data-ic="show-layers"`
      + ` title="이동 · 확대 · 회전이 이 레이어에 먹습니다 - 눌러서 레이어 목록">`
      + `${ICON.layers}<span>${escHtml(row?.name || '원본')}</span></button>`;
  }

  function dockHtml() {
    const {w, h} = canvasSize();
    const editing = viewMode === 'edit';
    const off = editing ? '' : 'disabled';
    const active = tx();
    const scalePct = clampPct(active.scale * 100);
    const rotation = wrapDeg(active.rotation);
    const onBase = active.id === 'base';
    return `
      <div class="ic-bar ic-bar-head ic-nowrap">
        <span class="ic-title">인페인트</span>
        <div class="ic-modes${flashModes ? ' is-fresh' : ''}" role="group" aria-label="보기 모드">
          <button type="button" class="ic-btn${editing ? ' is-on' : ''}" data-ic="mode-edit">편집</button>
          <button type="button" class="ic-btn${editing ? '' : ' is-on'}" data-ic="mode-result">결과 보기</button>
        </div>
        ${restoreButtonHtml()}
        <span class="ic-spacer"></span>
        ${editing ? targetChipHtml() : ''}
        ${editing ? keysHtml() : ''}
      </div>
      ${state.canvas_purpose === 'character_asset' ? `
      <div class="ic-bar ic-bar-asset ic-nowrap">
        <span class="ic-asset-label">캐릭터 에셋 액자</span>
        <span class="ic-asset-hint">액자 안에 스탠딩을 맞춘 뒤 저장하세요.</span>
        <span class="ic-spacer"></span>
        <button type="button" class="ic-btn ic-btn-asset" data-ic="asset-save-frame"
          title="지금 액자에 놓인 그대로 저장합니다 (생성하지 않음)">이 프레임으로 저장</button>
        <button type="button" class="ic-btn" data-ic="asset-save-generated"
          title="빈 곳을 인페인트로 메운 뒤 그 결과를 저장합니다 (Anlas 소모)">생성 후 저장</button>
      </div>` : ''}
      <div class="ic-cols">
        <section class="ic-col" aria-label="캔버스">
          <div class="ic-row">
            <span class="ic-label">캔버스</span>
            <select class="ic-select" data-ic="size" ${off} aria-label="캔버스 해상도">${sizeOptions(w, h)}</select>
            <button type="button" class="ic-btn ic-icon-btn" data-ic="undo" ${(editing && undoStack.length) ? '' : 'disabled'}
              title="이동/회전을 한 단계 되돌립니다 (Ctrl+Z)">&#8630;</button>
            <button type="button" class="ic-btn" data-ic="reset" ${off}
              title="${onBase
                ? '원본 그대로로 되돌립니다 — 크기·위치·확대·회전'
                : '고른 레이어를 처음 자리로 되돌립니다 — 위치·확대·회전'}">초기화</button>
            <button type="button" class="ic-btn${showGrid ? ' is-on' : ''}" data-ic="grid" ${off} title="격자">격자</button>
          </div>
          <div class="ic-row">
            <span class="ic-label">확대</span>
            <button type="button" class="ic-btn ic-nudge" data-ic="zoom-out" ${off} title="1% 축소">−</button>
            <input type="range" class="ic-slider-wide" min="${SCALE_MIN_PCT}" max="${SCALE_MAX_PCT}" step="1"
                   value="${scalePct}" data-ic-tr="scale" ${off} aria-label="확대 비율">
            <strong class="ic-val" data-ic-val="scale">${scalePct}%</strong>
            <button type="button" class="ic-btn ic-nudge" data-ic="zoom-in" ${off} title="1% 확대">+</button>
          </div>
          <div class="ic-row">
            <span class="ic-label">회전</span>
            <button type="button" class="ic-btn ic-nudge" data-ic="rot-down" ${off} title="1° 시계 방향">−</button>
            <input type="range" class="ic-slider-wide" min="0" max="359" step="1" value="${rotation}"
                   data-ic-tr="rotation" ${off} aria-label="회전 각도">
            <strong class="ic-val" data-ic-val="rotation">${rotation}°</strong>
            <button type="button" class="ic-btn ic-nudge" data-ic="rot-up" ${off} title="1° 반시계 방향">+</button>
            <button type="button" class="ic-btn" data-ic="rot-quarter" ${off} title="90° 반시계로 돌리기">⟲</button>
          </div>
        </section>
        ${runColHtml(editing)}
      </div>
    `;
  }

  // 팝업이 안 열리므로 인페인트 조작은 전부 여기 있어야 한다.
  function runColHtml(editing) {
    const strength = Number.isFinite(Number(state.strength)) ? Number(state.strength) : 99;
    const noise = Number.isFinite(Number(state.noise)) ? Number(state.noise) : 0;
    const repeat = Number.isFinite(Number(state.repeat)) ? Number(state.repeat) : 1;
    // ⚠️ 셋을 가른다. `has_mask` 는 **칠한 것 + 빈 곳**이라 회전만 해도 참이 된다 -
    //    그걸 그대로 "마스크 있음" 이라 적으면 칠한 적 없는 사용자에게 거짓말이다
    //    (사용자 제보 2026-08-27).
    const painted = !!state.has_user_mask;      // 사람이 칠한 것
    const masked = !!state.has_mask;            // 칠한 것 + 빈 곳(= 생성 가능 여부)
    // 생성이 도는 동안에는 버튼 자체를 잠근다 - 눌러 봐야 토스트만 나오는 것보다
    // 눌리지 않는 편이 낫다(사용자 지정 2026-08-29).
    let busyNow = false;
    try { busyNow = !!isGenerating(); } catch (_) { busyNow = false; }
    const gapOnly = masked && !painted;
    const genTitle = state.requires_mask
      ? ' title="생성 전에 마스크를 칠하거나 베이스를 옮겨 빈 자리를 여세요"' : '';
    return `
      <section class="ic-col" aria-label="인페인트 실행">
        <div class="ic-row">
          <button type="button" class="ic-btn ic-btn-mask" data-ic="mask" ${editing ? '' : 'disabled'}>마스크 그리기</button>
          <button type="button" class="ic-btn" data-ic="auto-mask" ${editing ? '' : 'disabled'}
            title="빈 곳과 그 경계(16px)를 한 번에 칠합니다">자동 마스킹</button>
          <span class="ic-mask-state${painted ? ' is-on' : ''}${gapOnly ? ' is-auto' : ''}"
            title="${gapOnly
              ? '베이스가 못 덮은 빈 곳이 자동으로 열립니다 - 직접 칠한 것은 없습니다'
              : (painted ? '직접 칠한 마스크가 있습니다' : '아직 칠한 곳이 없습니다')}"
            >${painted ? '마스크 있음' : (gapOnly ? '빈 곳 자동' : '마스크 없음')}</span>
          <button type="button" class="ic-btn" data-ic="clear-mask"
            ${(painted && editing) ? '' : 'disabled'}
            title="직접 칠한 것만 지웁니다 (빈 곳은 베이스를 되돌려야 사라집니다)">지우기</button>
        </div>
        <div class="ic-row">
          <span class="ic-label">강도</span>
          <input type="range" min="1" max="99" value="${strength}" data-ic-range="strength" aria-label="강도">
          <strong class="ic-val" data-ic-val="strength">${ratio(state.strength_value)}</strong>
          <span class="ic-label">노이즈</span>
          <input type="range" min="0" max="99" value="${noise}" data-ic-range="noise" aria-label="노이즈">
          <strong class="ic-val" data-ic-val="noise">${ratio(state.noise_value)}</strong>
        </div>
        <div class="ic-row">
          <span class="ic-label">반복</span>
          <input class="ic-num" type="number" min="1" max="99" value="${repeat}" data-ic-num="repeat" aria-label="반복">
          <span class="ic-spacer"></span>
          <button type="button" class="ic-btn ic-btn-go${masked ? '' : ' is-blocked'}${busyNow ? ' is-busy' : ''}" data-ic="generate"${busyNow ? ' disabled' : ''}${genTitle}>${busyNow ? '생성 중…' : '인페인트 생성'}</button>
          <button type="button" class="ic-btn ic-btn-end" data-ic="close">세션 닫기</button>
        </div>
      </section>
    `;
  }

  // 결과 이미지와 같은 자리. 편집 모드일 때만 겹친다.
  function renderPlane() {
    if (!plane) return;
    const editing = !!(state?.active && state.canvas_supported && viewMode === 'edit');
    // 뷰어에 표식을 남겨 결과 이미지를 숨긴다 - 캔버스가 반투명하게 겹치면 옮긴
    // 자리가 원본과 겹쳐 보여 무엇이 진짜인지 알 수 없다.
    viewer?.classList.toggle('ic-editing', editing);
    // 목록을 **먼저** 그린다 - 펼친 목록은 plane 에 오른쪽 여백을 만들고(CSS `:has`),
    // 아래 `fitStage` 가 그 여백을 재서 스테이지를 앉힌다.
    renderLayers(editing);
    if (!editing) { plane.innerHTML = ''; plane.hidden = true; stageEl = null; return; }
    plane.hidden = false;

    const {w, h} = canvasSize();
    const preview = state.preview || '';
    const chars = (state.characters || [])
      .map((c, i) => ({...c, index: i}))
      .filter(c => c.prompt && c.position);
    plane.innerHTML = `
      <div class="ic-stage" data-ic-stage="1">
        ${preview ? `<img class="ic-canvas" src="${escHtml(preview)}" alt="canvas" draggable="false">` : ''}
        ${showGrid ? gridSvg(w, h, {className: 'ic-grid pos-grid'}) : ''}
        ${state.mask_preview
          ? `<div class="ic-mask${flashMask ? ' is-flash' : ''}"
              style="--ic-mask-url:url('${escHtml(state.mask_preview)}')"></div>`
          : ''}
        <div class="ic-sel" data-ic-sel="1" hidden></div>
        <div class="ic-ghost" data-ic-ghost="1" hidden></div>
        ${chars.map(c => {
          const p = contentToPercent(c.position.x, c.position.y, w, h);
          // ⚠️ **표시 전용이다.** 예전에는 여기서도 끌 수 있었는데, 그러면 위치를 고치는
          //    길이 둘이 된다(여기 + 캐릭터 POS 편집) - 인원을 더하거나 POS 모드를
          //    오갈 때 어느 쪽이 진짜인지 알 수 없어진다(사용자 지적 2026-08-26).
          //    좌표를 고치는 곳은 **POS 편집 하나**로 둔다.
          return `<span class="ic-marker" data-ic-marker="${c.index}"
            style="left:${p.left};top:${p.top}" title="${escHtml(c.prompt)}">${c.index + 1}</span>`;
        }).join('')}
      </div>
    `;
    stageEl = plane.querySelector('[data-ic-stage]');
    // 번쩍임은 **한 번뿐**이다. 안 끄면 다음 렌더마다 다시 번쩍여 방해가 된다.
    flashMask = false;
    placeSelection();
    fitStage();
  }

  /** 고른 레이어를 점선으로 두른다. 레이어가 둘 이상일 때만 - 하나뿐이면 고를 것이 없다.
   *
   *  ⚠️ 축정렬 상자(`placed_*`)가 아니라 **돌리기 전 사각형**을 놓고 돌린다(유령과 같은
   *     이유 - `beginMiddleDrag` 주석). PIL 은 반시계로 돌리므로 CSS 는 음수 각도다.
   */
  function placeSelection() {
    const sel = stageEl?.querySelector('[data-ic-sel]');
    if (!sel) return;
    const {w, h} = canvasSize();
    const t = tx();
    const preW = t.w * t.scale;
    const preH = t.h * t.scale;
    if (!extraLayerCount() || !(w > 0) || !(h > 0) || !(preW > 0) || !(preH > 0)) {
      sel.hidden = true;
      return;
    }
    sel.hidden = false;
    sel.classList.toggle('is-hidden-layer', layerRow(t.id)?.visible === false);
    sel.style.left = `${((t.x + t.placedW / 2) / w) * 100}%`;
    sel.style.top = `${((t.y + t.placedH / 2) / h) * 100}%`;
    sel.style.width = `${(preW / w) * 100}%`;
    sel.style.height = `${(preH / h) * 100}%`;
    sel.style.transform = `translate(-50%, -50%) rotate(${-t.rotation}deg)`;
  }

  /** 도크를 그린다. **도크가 보여 주는 레이어**(`icDockLayer`)를 함께 적는다. */
  function drawDock() {
    panel.innerHTML = dockHtml();
    panel.dataset.icDockLayer = activeLayerId();
    // 어느 세션의 도크인가. 반복 칸에 쓰는 사이 다른 탭이 세션을 바꾸면 도크는 옛 그림의 것인데
    // `base` 라는 같은 id 가 새 그림에도 있다(Codex 확인 리뷰 2026-10-05: 옛 150% 표시에서 새
    // 세션에 `base_scale 1.51` 이 나갔다). 메뉴(`icMenuWindow`)와 같은 이유다.
    panel.dataset.icDockWindow = String(state?.window_id ?? '');
    dockStale = false;
  }

  /** 도크의 단추 · 슬라이더가 고칠 레이어 = **도크가 지금 보여 주는 레이어**.
   *
   *  ⚠️ `activeLayerId()` 가 아니다. 도크는 슬라이더를 끌거나 반복 칸에 쓰는 동안 다시 그려지지
   *     않는데, 그 사이에 고른 레이어가 바뀔 수 있다(업로드가 끝나 새 레이어가 골라진다 · 다른
   *     탭이 그 레이어를 지운다). 그때 `activeLayerId()` 를 읽으면 도크는 L1 · 150% 를 보이는데
   *     [+] 는 L2 를 고친다(Codex 리뷰 2026-10-05, 세 번에 걸쳐 같은 뿌리). 조작이 끝난 뒤 다시
   *     그리는 것(`settleDock`)만으로는 **그 첫 조작**을 못 막는다 - 보이는 것을 고치게 한다.
   *  그 레이어가 그 사이 지워졌으면 null - 아무것도 고치지 않고 도크를 다시 그린다.
   */
  function dockLayerId() {
    const id = panel?.dataset?.icDockLayer || '';
    const sameSession = (panel?.dataset?.icDockWindow ?? '') === String(state?.window_id ?? '');
    if (id && sameSession && layerRow(id)) return id;
    dockStale = true;
    if (!rangeDragging && !typingInPanel() && !restorePop) refreshChrome();
    return null;
  }

  /** 레이어를 바꿔 골랐을 때 **스테이지는 그대로 두고** 둘레만 다시 그린다.
   *
   *  ⚠️ 스테이지를 다시 만들면 안 된다 - 그림 위를 눌러 고르는 순간 곧바로 끌기가
   *     시작되는데, 그 노드를 갈아 끼우면 끌기가 죽은 노드를 붙잡는다.
   */
  function refreshChrome() {
    if (!state?.active || !panel || panel.hidden) return;
    if (!rangeDragging && !typingInPanel()) {
      closeRestorePicker();
      drawDock();
    } else {
      dockStale = true;          // 조작이 끝나면 `settleDock` 이 그린다
    }
    renderLayers(viewMode === 'edit');
    placeSelection();
  }

  /** 밀린 도크를 지금 그린다(조작이 끝난 뒤에만). 슬라이더를 놓을 때와 다음 클릭에 부른다.
   *
   *  ⚠️ 반복 칸에서 초점이 나가는 순간(`focusout`)에는 **그리지 않는다.** 칸에 쓰고 곧바로
   *     [인페인트 생성] 을 누르면 초점 이동 -> 떼기 -> click 순서인데, 그 사이에 도크를 갈아
   *     끼우면 누른 단추가 사라져 click 이 안 난다. 그래서 문서의 click(패널의 처리기가 먼저
   *     돈 뒤)에 그린다.
   */
  function settleDock() {
    if (!dockStale || rangeDragging || typingInPanel()) return;
    // 방금 연 [프롬프트 복원] 팝업은 도크 안에 산다 - 도크를 갈아 끼우면 같은 클릭에 닫힌다
    // (Codex 재리뷰 2026-10-05: 반복 칸을 고친 직후 복원을 누르면 열리자마자 닫혔다). 닫힌 뒤에 그린다.
    if (restorePop) return;
    if (!state?.active || !state.canvas_supported || !panel || panel.hidden) { dockStale = false; return; }
    refreshChrome();
  }

  // ── 레이어 목록 ─────────────────────────────────────────────────────────
  function layerCardHtml(row, {active, top, bottom}) {
    const base = row.id === 'base';
    const hidden = row.visible === false;
    const pct = Math.round((Number(row.scale) || 1) * 100);
    const rot = Math.round(Number(row.rotation) || 0);
    const meta = hidden ? '숨김'
      : `${pct}%${rot ? ` · ${rot}°` : ''}${row.flip_x ? ' · ↔' : ''}${row.flip_y ? ' · ↕' : ''}`;
    const tool = (act, icon, title, disabled = false) => `<button type="button" class="ic-lbtn"`
      + ` data-ic-layer-act="${act}"${disabled ? ' disabled' : ''} title="${escHtml(title)}">${icon}</button>`;
    return `<li class="ic-layer${active ? ' is-active' : ''}${hidden ? ' is-hidden' : ''}"`
      + ` data-ic-layer="${escHtml(row.id)}"${active ? ' aria-current="true"' : ''}>`
      + `<span class="ic-layer-thumb">${row.thumb
        ? `<img src="${escHtml(row.thumb)}" alt="" draggable="false">` : ''}</span>`
      + `<span class="ic-layer-text">`
      + `<span class="ic-layer-name">${escHtml(row.name || (base ? '원본' : '이미지'))}</span>`
      + `<span class="ic-layer-meta">${escHtml(meta)}</span></span>`
      + `<span class="ic-layer-tools">`
      + tool('visible', hidden ? ICON.eyeOff : ICON.eye,
        hidden ? '보이기' : '숨기기 — 숨긴 자리는 다시 그려집니다')
      + tool('remove', ICON.trash, base ? '원본은 지울 수 없습니다 — 숨기기를 쓰세요' : '레이어 지우기', base)
      + tool('up', ICON.up, '한 칸 위로', top)
      + tool('down', ICON.down, '한 칸 아래로', bottom)
      + `</span></li>`;
  }

  function layersHtml() {
    const rows = layerRows().slice().reverse();           // 화면은 위가 먼저다
    const count = rows.length;
    if (!showLayers) {
      return `<button type="button" class="ic-layers-pill" data-ic-layers="open" aria-expanded="false"`
        + ` title="레이어 목록 펴기">${ICON.layers}<span>레이어</span><b>${count}</b></button>`;
    }
    const limit = Number(state?.layer_limit) || 8;
    const full = extraLayerCount() >= limit;
    const active = activeLayerId();
    return `<div class="ic-layers-head">`
      + `<span class="ic-layers-title">${ICON.layers}<span>레이어</span><b>${count}</b></span>`
      + `<button type="button" class="ic-lbtn ic-layers-add" data-ic-layers="add"`
      + `${(full || layerUploading) ? ' disabled' : ''} title="${full
        ? `레이어는 ${limit}장까지 올릴 수 있습니다`
        : '이미지를 레이어로 올립니다 — 캔버스에 끌어다 놓기 · Ctrl+V 도 됩니다'}">`
      + `${ICON.plus}<span>${layerUploading ? '올리는 중…' : '이미지'}</span></button>`
      + `<button type="button" class="ic-lbtn" data-ic-layers="close" aria-expanded="true"`
      + ` title="레이어 목록 접기">${ICON.fold}</button></div>`
      + `<ol class="ic-layer-list">${rows.map((row, i) => layerCardHtml(row, {
        active: row.id === active, top: i === 0, bottom: i === count - 1,
      })).join('')}</ol>`
      + `<div class="ic-layers-drop">여기에 놓으면 레이어로 올라갑니다</div>`;
  }

  /** 목록은 **편집 중에만** 뜬다. 결과 보기에는 얹을 캔버스가 없다. */
  function renderLayers(editing) {
    if (!layersEl) return;
    if (!editing) {
      closeLayerPicker();
      closeLayerMenu();
      layersEl.hidden = true;
      layersEl.innerHTML = '';
      return;
    }
    // 고르기 팝업이 열려 있으면 다시 그리지 않는다 - 썸네일을 고르던 중에 사라진다.
    if (layerPop) return;
    layersEl.hidden = false;
    layersEl.classList.toggle('is-folded', !showLayers);
    layersEl.innerHTML = layersHtml();
  }

  function setLayersOpen(open) {
    showLayers = !!open;
    write(LAYERS_OPEN_KEY, showLayers ? '1' : '0');
    closeLayerPicker();
    renderLayers(viewMode === 'edit');
    // 펼친 목록만큼 plane 오른쪽이 비켜선다 - plane 상자 크기는 그대로라
    // ResizeObserver 가 안 불린다. 직접 다시 앉힌다.
    fitStage();
  }

  /** 레이어로 올린다. 그림 바이트 · 히스토리 경로(JSON) 두 갈래. 상태는 서버가 방송한다. */
  async function uploadLayer(body, {json = false, label = ''} = {}) {
    if (layerUploading) {
      showToast?.('앞선 이미지를 올리는 중입니다 - 끝나면 다시 해 주세요', 'info');
      return;
    }
    layerUploading = true;
    renderLayers(viewMode === 'edit');
    try {
      // 올리는 동안 세션이 바뀌면 서버가 거절한다 - 어느 세션에 올리는지 함께 보낸다.
      const params = new URLSearchParams({window: String(state?.window_id ?? '')});
      if (label) params.set('label', String(label).slice(0, 120));
      const response = await fetch(`/api/img2img/layer?${params}`, {
        method: 'POST',
        headers: {'Content-Type': json ? 'application/json' : (body?.type || 'application/octet-stream')},
        body: json ? JSON.stringify(body) : body,
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
      // 방금 올린 레이어를 고른다 - **올린 이 탭만**. 서버가 넣은 id 를 돌려준다(다른 탭은 방송을
      // 받아도 제 선택을 그대로 둔다). 방송이 먼저 와 있지 않아도 `activeId` 가 기다린다.
      const added = data?.state?.active_layer;
      if (added) { activeId = String(added); refreshChrome(); }
    } catch (error) {
      showToast?.(`레이어를 올리지 못했습니다: ${error.message}`, 'error');
    } finally {
      layerUploading = false;
      renderLayers(viewMode === 'edit');
    }
  }

  function pickLayerFile() {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = 'image/*';
    input.addEventListener('change', () => {
      const file = input.files && input.files[0];
      if (file) uploadLayer(file, {label: file.name || ''});
    });
    input.click();
  }

  /** [+ 이미지] - 파일 열기 + 최근 히스토리. 프롬프트 복원 팝업과 같은 모양이다. */
  async function openLayerPicker(anchor) {
    closeLayerPicker();
    if (!layersEl) return;
    const pop = document.createElement('div');
    pop.className = 'ic-restore-pop ic-layer-pop';
    const box = layersEl.getBoundingClientRect();
    const at = anchor ? anchor.getBoundingClientRect() : box;
    pop.style.top = `${Math.round(at.bottom - box.top + 6)}px`;
    pop.innerHTML = `<div class="ic-restore-head">`
      + `<span>레이어로 올릴 이미지</span>`
      + `<button type="button" class="ic-restore-x" data-ic-layers="pop-close">&#10005;</button></div>`
      // 넓은 놓기 자리(사용자 지정 2026-10-03). 누르면 파일 열기, 끌어다 놓으면 바로 올린다 -
      // 놓기는 목록(`layersEl`)의 처리기가 받는다(팝업이 그 안에 있다).
      + `<button type="button" class="ic-layer-dropzone" data-ic-layers="pop-file">`
      + `${ICON.upload}<span class="ic-layer-dropzone-main">이미지를 여기로 끌어다 놓기</span>`
      + `<span class="ic-layer-dropzone-sub">눌러서 파일 열기 · <kbd>Ctrl</kbd><kbd>V</kbd> 붙여넣기</span>`
      + `</button>`
      + `<div class="ic-restore-hint">PNG 의 투명한 부분으로는 아래 레이어가 비칩니다</div>`
      + `<div class="ic-restore-list" data-ic-list="1">불러오는 중…</div>`;
    layersEl.appendChild(pop);
    layerPop = pop;
    try {
      const response = await fetch('/api/history/list?page=0&per_page=24');
      const data = await response.json();
      const images = Array.isArray(data && data.images) ? data.images : [];
      const list = pop.querySelector('[data-ic-list]');
      if (!list) return;
      list.innerHTML = images.length
        ? images.map(item => `<button type="button" class="ic-restore-item"`
            + ` data-ic-lpath="${escHtml(String(item.rel_path || ''))}"`
            + ` title="${escHtml(String(item.filename || ''))}">`
            + `<img src="${escHtml(String(item.thumb_url || ''))}" alt="" loading="lazy"></button>`).join('')
        : `<div class="ic-restore-hint">히스토리가 비어 있습니다</div>`;
    } catch (_error) {
      const list = pop.querySelector('[data-ic-list]');
      if (list) list.innerHTML = `<div class="ic-restore-hint">히스토리를 못 읽었습니다</div>`;
    }
  }

  function closeLayerPicker() {
    const had = !!layerPop;
    if (layerPop && layerPop.parentElement) layerPop.parentElement.removeChild(layerPop);
    layerPop = null;
    return had;
  }

  function onLayersClick(event) {
    const target = event.target;
    const path = target.closest?.('[data-ic-lpath]')?.dataset.icLpath;
    if (path !== undefined) {
      closeLayerPicker();
      uploadLayer({path, source: 'saved'}, {json: true});
      return;
    }
    const button = target.closest?.('[data-ic-layers]');
    const command = button?.dataset.icLayers;
    if (command === 'open') return setLayersOpen(true);
    if (command === 'close') return setLayersOpen(false);
    if (command === 'pop-close') { closeLayerPicker(); renderLayers(viewMode === 'edit'); return; }
    if (command === 'pop-file') { closeLayerPicker(); renderLayers(viewMode === 'edit'); pickLayerFile(); return; }
    if (command === 'add') {
      if (closeLayerPicker()) { renderLayers(viewMode === 'edit'); return; }
      openLayerPicker(button);
      return;
    }
    const card = target.closest?.('[data-ic-layer]');
    if (!card) return;
    const id = card.dataset.icLayer;
    const act = target.closest?.('[data-ic-layer-act]')?.dataset.icLayerAct;
    if (act === 'visible') return toggleLayerVisible(id);
    if (act === 'remove') return removeLayer(id);
    if (act === 'up' || act === 'down') {
      send('layer_move', {id, dir: act});
      return;
    }
    selectLayer(id);
  }

  // ── 레이어 동작: 도크 · 목록 · 단축키 · 우클릭 메뉴가 **같은 함수**를 부른다 ──────────
  // 입구마다 따로 짜면 한쪽이 빠뜨린다(초기화의 되돌리기 비우기가 실제로 0 키에서만 빠져 있었다).

  /** 레이어를 처음 자리로. 베이스는 예전 그대로 캔버스 크기까지 원본으로 간다. */
  function resetLayer(id) {
    flushTransforms();
    // ⚠️ 초기화는 **확대(베이스는 캔버스 크기까지)** 되돌린다. 기록을 남겨 두면 그 뒤의
    //    되돌리기가 이동·회전만 살려 내 **반쪽 상태**가 된다(BLOCK 3).
    undoStack = [];
    return id === 'base' ? send('base_reset', null) : send('layer_reset', {id});
  }

  function toggleLayerVisible(id) {
    send('layer_visible', {id, visible: layerRow(id)?.visible === false});
  }

  /** 레이어를 지운다 - **늘 묻고 나서**(사용자 지정 2026-10-05: "인페인트 모드에서는 무조건 팝업으로
   *  물어봅니다"). 목록의 휴지통 · 우클릭 메뉴 · Del 키가 모두 여기를 지난다.
   *
   *  ⚠️ '묻지 않기' 는 두지 않는다. 올린 그림은 지우면 되돌릴 길이 없다(되돌리기는 이동 · 회전뿐이다).
   *  ⚠️ 묻는 사이 세션이 바뀌거나 그 레이어가 사라질 수 있다 - 답을 받은 뒤 다시 본다.
   */
  let removeAsking = false;
  async function removeLayer(id) {
    if (id === 'base' || removeAsking) return;
    const row = layerRow(id);
    if (!row || !state?.active) return;
    const askedIn = String(state.window_id ?? '');
    let confirmed = true;
    if (typeof showConfirmDialog === 'function') {
      removeAsking = true;
      try {
        confirmed = await showConfirmDialog(
          `'${row.name || '이미지'}' 레이어를 지울까요?\n지운 레이어는 되돌릴 수 없습니다.`,
          {title: '레이어 지우기', okText: '지우기', cancelText: '취소'});
      } catch (_) {
        confirmed = false;
      } finally {
        removeAsking = false;
      }
    }
    if (!confirmed) return;
    if (!state?.active || String(state.window_id ?? '') !== askedIn || !layerRow(id)) return;
    // 지운 레이어를 가리키는 되돌리기는 갈 곳이 없다.
    undoStack = undoStack.filter(snap => snap.id !== id);
    send('layer_remove', {id});
  }

  /** 좌우(`x`) · 상하(`y`) 반전. 화면에 보이는 그대로 뒤집힌다(회전 부호는 서버가 함께 바꾼다).
   *
   *  ⚠️ 미뤄 둔 확대/회전을 **먼저** 보낸다. 서버는 반전하면서 회전의 부호를 뒤집는데,
   *     그 뒤에 늦게 도착한 옛 회전값이 방금 뒤집은 값을 덮으면 그림이 엉뚱한 쪽으로 기운다.
   */
  function flipLayer(id, axis) {
    flushTransforms();
    send('layer_flip', {id, axis});
  }

  // ── 우클릭 메뉴(사용자 지정 2026-10-05) ─────────────────────────────────
  // ⚠️ 결과 이미지의 우클릭 메뉴는 **문서 전체**에 걸려 있고(`resultContextMenu` - 누른 곳이
  //    `.viewer` 안이면 뜬다), 캔버스 · 레이어 목록 · 도크가 전부 그 뷰어 안에 산다. 여기서
  //    전파를 끊지 않으면 편집 중인 캔버스 위에 "이미지 저장 · 큐에 추가 · 이미지 삭제" 가
  //    뜬다(사용자 제보 2026-10-05). 그 자리에는 레이어 메뉴를 띄운다.
  let layerMenu = null;

  function closeLayerMenu() {
    if (!layerMenu) return false;
    layerMenu.remove();
    layerMenu = null;
    return true;
  }

  function layerMenuHtml(id) {
    const row = layerRow(id);
    if (!row) return '';
    const base = id === 'base';
    const hidden = row.visible === false;
    const item = (act, icon, label, {hint = '', danger = false, disabled = false, on = false} = {}) =>
      `<button type="button" role="menuitem" class="ic-menu-item${danger ? ' is-danger' : ''}${on ? ' is-on' : ''}"`
      + ` data-ic-menu="${act}"${disabled ? ' disabled' : ''}>`
      + `<span class="ic-menu-icon">${icon}</span><span class="ic-menu-label">${escHtml(label)}</span>`
      + `${hint ? `<span class="ic-menu-hint">${escHtml(hint)}</span>` : ''}</button>`;
    const sep = '<div class="ic-menu-sep" role="separator"></div>';
    return `<div class="ic-menu-head">${ICON.layers}<span>${escHtml(row.name || (base ? '원본' : '이미지'))}</span></div>`
      // 뒤집혀 있으면 켜진 표시를 한다 - 다시 누르면 풀린다는 것이 보인다.
      + item('flip-x', ICON.flipX, '좌우 반전', {on: !!row.flip_x})
      + item('flip-y', ICON.flipY, '상하 반전', {on: !!row.flip_y})
      + sep
      + item('rot-cw', ICON.rotCw, '시계 방향 90°')
      + item('rot-ccw', ICON.rotCcw, '반시계 방향 90°')
      + sep
      + item('visible', hidden ? ICON.eye : ICON.eyeOff, hidden ? '보이기' : '숨기기')
      + item('reset', ICON.reset, '초기화', {hint: '0'})
      + (typeof onRequestPaste === 'function'
        ? sep + item('paste', ICON.paste, '이미지 붙여넣기', {hint: 'Ctrl+V'}) : '')
      + sep
      + item('remove', ICON.trash, base ? '원본은 지울 수 없습니다' : '레이어 지우기', {danger: true, disabled: base});
  }

  function openLayerMenu(id, x, y) {
    closeLayerMenu();
    const html = layerMenuHtml(id);
    if (!html) return;
    const menu = document.createElement('div');
    menu.className = 'ic-menu';
    menu.setAttribute('role', 'menu');
    menu.dataset.icMenuLayer = id;
    // 어느 세션에서 열었는가. 떠 있는 사이 다른 탭이 세션을 닫고 새 그림을 열면 `base` 라는
    // 같은 id 가 **다른 그림**을 가리킨다(Codex 리뷰 2026-10-05).
    menu.dataset.icMenuWindow = String(state?.window_id ?? '');
    menu.innerHTML = html;
    document.body.appendChild(menu);
    // 화면 밖으로 나가지 않게 앉힌다(뷰어 아래쪽에서 누르면 메뉴가 잘린다).
    const rect = menu.getBoundingClientRect();
    const maxX = (document.documentElement.clientWidth || window.innerWidth) - rect.width - 6;
    const maxY = (document.documentElement.clientHeight || window.innerHeight) - rect.height - 6;
    menu.style.left = `${Math.round(Math.max(6, Math.min(x, maxX)))}px`;
    menu.style.top = `${Math.round(Math.max(6, Math.min(y, maxY)))}px`;
    menu.addEventListener('click', onLayerMenuClick);
    // 메뉴 위에서 또 우클릭해도 결과 이미지 메뉴가 뜨지 않게.
    menu.addEventListener('contextmenu', (event) => { event.preventDefault(); event.stopPropagation(); });
    layerMenu = menu;
  }

  function onLayerMenuClick(event) {
    const act = event.target.closest?.('[data-ic-menu]')?.dataset.icMenu;
    if (!act) return;
    const id = layerMenu?.dataset.icMenuLayer || 'base';
    const openedIn = layerMenu?.dataset.icMenuWindow ?? '';
    closeLayerMenu();
    if (openedIn !== String(state?.window_id ?? '')) return;      // 다른 세션이 됐다
    // 메뉴가 떠 있는 사이에 세션이 닫혔거나 그 레이어가 지워졌으면 아무것도 안 한다.
    if (!state?.active || viewMode !== 'edit' || !layerRow(id)) return;
    if (act === 'flip-x') return flipLayer(id, 'x');
    if (act === 'flip-y') return flipLayer(id, 'y');
    // 서버(PIL)는 반시계가 양수다 - 시계 방향은 빼기.
    if (act === 'rot-cw') return applyTransform('rotation', wrapDeg(tx(id).rotation - 90), null, id);
    if (act === 'rot-ccw') return applyTransform('rotation', wrapDeg(tx(id).rotation + 90), null, id);
    if (act === 'visible') return toggleLayerVisible(id);
    if (act === 'reset') return resetLayer(id);
    if (act === 'paste') return onRequestPaste?.();
    if (act === 'remove') return removeLayer(id);
  }

  /** 캔버스 위 우클릭 - 누른 자리의 레이어를 고르고 그 레이어의 메뉴를 띄운다. */
  function onStageContextMenu(event) {
    event.preventDefault();
    event.stopPropagation();           // 결과 이미지 메뉴로 올라가지 않게
    if (viewMode !== 'edit' || !state?.active || posStage?.isDragging()) return;
    const hit = layerAt(canvasPointOf(event));
    if (hit && hit !== activeLayerId()) selectLayer(hit);
    openLayerMenu(activeLayerId(), event.clientX, event.clientY);
  }

  /** 레이어 목록 위 우클릭 - 카드면 그 레이어의 메뉴, 아니면 막기만 한다. */
  function onLayersContextMenu(event) {
    event.preventDefault();
    event.stopPropagation();
    const id = event.target.closest?.('[data-ic-layer]')?.dataset.icLayer;
    if (!id || !state?.active || !layerRow(id)) return;
    selectLayer(id);
    openLayerMenu(id, event.clientX, event.clientY);
  }

  /** 도크 위 우클릭 - 결과 이미지 메뉴만 막는다(글자 칸의 기본 메뉴는 둔다). */
  function onDockContextMenu(event) {
    event.stopPropagation();
    if (!event.target?.matches?.('input, textarea')) event.preventDefault();
  }

  // ── 끌어다 놓기: 캔버스(스테이지)나 목록에 놓으면 레이어로 ─────────────────
  // ⚠️ 뷰어에도 놓기 처리가 있다(`resultImageInput` - 이미지 동작 팝업). 스테이지 **위**에
  //    놓았을 때만 가로채고 전파를 끊는다. 스테이지 밖(뷰어 빈 곳)은 예전 팝업 그대로다.
  function dropHasImage(dataTransfer) {
    const types = Array.from(dataTransfer?.types || []);
    return types.includes('Files') || types.includes('application/x-naia-source');
  }
  function dropTargetOk(event) {
    if (viewMode !== 'edit' || !state?.active || !state?.canvas_supported) return false;
    if (!dropHasImage(event.dataTransfer)) return false;
    if (event.currentTarget === plane) return !!event.target?.closest?.('[data-ic-stage]');
    return true;
  }
  function markDrop(on) {
    stageEl?.classList.toggle('is-drop', !!on);
    layersEl?.classList.toggle('is-drop', !!on);
  }
  function onLayerDragOver(event) {
    if (!dropTargetOk(event)) return;
    event.preventDefault();
    event.stopPropagation();
    if (event.dataTransfer) event.dataTransfer.dropEffect = 'copy';
    markDrop(true);
  }
  function onLayerDragLeave(event) {
    if (event.currentTarget.contains(event.relatedTarget)) return;
    markDrop(false);
  }
  function onLayerDrop(event) {
    if (!dropTargetOk(event)) return;
    event.preventDefault();
    event.stopPropagation();
    markDrop(false);
    viewer?.classList.remove('drag-over');      // 뷰어의 놓기 표시가 남지 않게
    closeLayerPicker();                         // 고르기 팝업의 놓기 자리에 놓았을 수도 있다
    let internal = null;
    try { internal = JSON.parse(event.dataTransfer.getData('application/x-naia-source') || 'null'); }
    catch (_) { internal = null; }
    if (internal && typeof internal === 'object') {
      uploadLayer({path: internal.path || '', source: internal.source || ''}, {json: true});
      return;
    }
    const files = Array.from(event.dataTransfer?.files || []);
    const file = files.find(item => item && String(item.type || '').startsWith('image/'));
    if (!file) { showToast?.('이미지 파일만 레이어로 올릴 수 있습니다', 'error'); return; }
    uploadLayer(file, {label: file.name || ''});
  }

  /** 스테이지를 남는 자리에 **비율 그대로** 앉힌다.
   *
   *  ⚠️ CSS `aspect-ratio` 로는 안 된다. 한 축만 확실할 때는 맞지만, 폭·높이 양쪽에
   *     한계가 걸리면 먼저 걸린 쪽만 잘리고 다른 쪽이 안 따라와 그림이 눌린다
   *     (실측: 도크가 자라 높이가 줄자 1.462 -> 1.399). 좌표 환산은 스테이지 상자의
   *     비율에만 기대므로, 눌린 상자는 곧 거짓말하는 좌표다.
   */
  function fitStage() {
    if (!stageEl || !plane) return;
    const {w, h} = canvasSize();
    if (!(w > 0) || !(h > 0)) return;
    const style = getComputedStyle(plane);
    const availW = plane.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight);
    const availH = plane.clientHeight - parseFloat(style.paddingTop) - parseFloat(style.paddingBottom);
    if (!(availW > 0) || !(availH > 0)) return;
    const scale = Math.min(availW / w, availH / h);
    stageEl.style.width = `${Math.round(w * scale)}px`;
    stageEl.style.height = `${Math.round(h * scale)}px`;
  }

  // ── 조작 ────────────────────────────────────────────────────────────────
  function typingInPanel() {
    const active = document.activeElement;
    return !!(active && panel?.contains(active) && active.matches?.('input[type="number"]'));
  }

  function setViewMode(mode) {
    const next = mode === 'result' ? 'result' : 'edit';
    if (next === viewMode) return;
    viewMode = next;
    render();
  }

  /** 확대/회전을 정확히 얼마만큼 민다. 화면은 즉시, 서버는 묶어서. */
  function nudge(key, delta, id = activeLayerId()) {
    if (!state || !id) return;
    const t = tx(id);
    if (key === 'scale') applyTransform('scale', clampPct(t.scale * 100 + delta), null, id);
    else applyTransform('rotation', wrapDeg(t.rotation + delta), null, id);
  }

  /** 지금 인페인트 생성을 보낼 수 있는가. 안 되면 **이유를 말하고** false.
   *
   *  ⚠️ 예전에는 버튼을 `disabled` 로 뒀다. 눌리지 않는 버튼은 왜 안 되는지 알려
   *     주지 않는다 - 사용자는 "버튼이 죽었다" 로만 본다(사용자 지정 2026-08-27).
   *  ⚠️ 마스크가 없으면 백엔드도 `Inpaint mask is required` 로 거절한다. 여기서
   *     먼저 막는 것은 그 거절을 **한국어로, 무엇을 하면 되는지와 함께** 돌려주기
   *     위해서다.
   */
  function canGenerateNow() {
    if (!state) return false;
    if (!state.has_mask) {
      showToast?.('칠한 곳이 없습니다 - [마스크 그리기] 로 고칠 곳을 칠하거나, '
        + '베이스를 옮겨 빈 자리를 연 뒤 [자동 마스킹] 을 누르세요', 'error');
      return false;
    }
    if (state.can_generate === false) {
      showToast?.('지금은 생성할 수 없습니다 (앞선 요청이 끝나기를 기다리는 중)', 'error');
      return false;
    }
    // ⚠️ **생성 중에는 또 못 누른다**(사용자 지정 2026-08-29). 연타하면 그만큼
    //    유료 요청이 쌓인다 - `state.can_generate` 는 서버 에코라 한 박자 늦어,
    //    누른 직후의 연타를 못 막는다. 화면이 아는 `generating` 으로 즉시 막는다.
    let busy = false;
    try { busy = !!isGenerating(); } catch (_) { busy = false; }
    if (busy) {
      showToast?.('이미 생성 중입니다 - 끝나면 다시 누르세요', 'error');
      return false;
    }
    return true;
  }

  /** 인페인트 생성으로 가는 **유일한 문**.
   *
   *  ⚠️ 도크 버튼과 큰 `Generate (Inpaint)` 가 각자 이 일을 하면 한쪽이 빠뜨린다 -
   *     실제로 큰 버튼이 `flushTransforms()` 를 빠뜨려, 옮기고 120ms 안에 누르면
   *     **옛 배치로 유료 요청**이 나갔다(Codex 리뷰 2026-08-27). 예전 라운드가
   *     잡았던 바로 그 버그를 새 진입점으로 되살린 셈이다.
   */
  function requestGenerate() {
    if (!canGenerateNow()) return false;
    flushTransforms();
    onGenerate();
    return true;
  }

  /** 고른 레이어의 지금 이동·회전. 되돌리기가 기억하는 것은 이것뿐이다(확대는 뺀다).
   *  **어느 레이어의 것인지**(`id`)도 함께 적는다 - 레이어를 바꿔 고른 뒤 되돌리면
   *  지금 고른 레이어가 아니라 그 값을 쟀던 레이어가 돌아와야 한다. */
  function transformSnapshot(id = activeLayerId()) {
    const t = tx(id);
    return {id: t.id, x: t.x, y: t.y, rotation: t.rotation};
  }

  /** 바꾸기 **직전**에 부른다. 같은 값이면 안 쌓는다(방향키를 오래 눌러도 한 칸씩만).
   *  끌기는 **누른 순간** 잰 스냅숏을 넘긴다 - 놓는 순간에 재면 그 사이 도착한 echo 가
   *  고른 레이어를 바꿔 다른 레이어를 기록한다(Codex 리뷰 2026-10-03). */
  function pushUndo(snap = transformSnapshot()) {
    if (!state?.active || undoApplying || undoGestureOpen || !snap) return;
    const top = undoStack[undoStack.length - 1];
    if (top && top.id === snap.id && top.x === snap.x && top.y === snap.y
        && top.rotation === snap.rotation) return;
    undoStack.push(snap);
    if (undoStack.length > UNDO_LIMIT) undoStack.shift();
  }

  /** 드래그 한 번을 한 단계로 묶는다. 시작에서 한 번 쌓고, 끝날 때까지 잠근다. */
  function beginUndoGesture(snap = transformSnapshot()) {
    if (undoGestureOpen) return;
    pushUndo(snap);
    undoGestureOpen = true;
  }
  function endUndoGesture() { undoGestureOpen = false; }

  /** 한 단계 되돌린다. 되돌릴 것이 없으면 말해 준다 - 조용하면 고장으로 읽힌다. */
  function undoTransform() {
    if (!state?.active) return;
    if (!undoStack.length) { showToast?.('되돌릴 이동/회전이 없습니다', 'info'); return; }
    // ⚠️ **미뤄 둔 회전을 먼저 흘려보낸다.** 디바운스에 걸려 있던 값이 되돌린 뒤에
    //    도착하면 방금 되돌린 것을 다시 덮는다.
    flushTransforms();
    const snap = undoStack.pop();
    const id = snap.id || 'base';
    // 그 사이에 지운 레이어다 - 갈 곳이 없으니 버리고 다음 칸으로(조용하면 고장으로 읽힌다).
    if (!layerRow(id)) { showToast?.('되돌릴 레이어가 이미 없습니다', 'info'); return; }
    undoApplying = true;
    try {
      // ⚠️ **회전을 먼저, 이동을 나중에.** 서버는 회전을 받으면 캔버스 한가운데를
      //    앵커로 잡고 오프셋을 **다시 계산**한다(`_recompose_canvas(anchor)`).
      //    이동을 먼저 보내면 뒤따라온 회전이 방금 되돌린 좌표를 덮는다
      //    (Codex 리뷰 2026-08-30 BLOCK 1).
      // ⚠️ **둘 다 무조건 보낸다.** 예전에는 "지금 값과 다를 때만" 보냈는데, 화면의
      //    `state` 는 서버 echo 로 통째로 갈아 끼워진다 - 늦게 온 echo 를 보고
      //    "이미 같다" 고 판단해 **아무것도 안 보내는** 창이 있었다(BLOCK 4).
      //    같은 값을 다시 보내는 비용은 합성 한 번이고, 안 보내는 대가는 유료 생성이
      //    되돌리지 않은 자리로 나가는 것이다.
      patchLayer(id, {rotation: snap.rotation});
      if (id === (panel?.dataset?.icDockLayer || '')) {      // 도크가 보여 주는 레이어일 때만
        const input = panel?.querySelector('[data-ic-tr="rotation"]');
        const label = panel?.querySelector('[data-ic-val="rotation"]');
        if (input) input.value = String(snap.rotation);
        if (label) label.textContent = `${snap.rotation}°`;
      }
      setLayerOffset(id, snap.x, snap.y);
      if (id === 'base') {
        send('base_rotation', {value: snap.rotation});
        send('base_offset', {x: snap.x, y: snap.y});
      } else {
        send('layer_rotation', {id, value: snap.rotation});
        send('layer_offset', {id, x: snap.x, y: snap.y});
      }
    } finally {
      undoApplying = false;
    }
  }

  /** 고른 레이어에 확대/회전을 먹인다. 화면은 즉시, 서버는 묶어서. */
  function applyTransform(key, value, at, id = activeLayerId()) {
    if (!state) return;
    // 회전만 되돌리기에 남긴다(확대는 대상이 아니다 - 위 UNDO 주석).
    if (key !== 'scale') pushUndo(transformSnapshot(id));
    // 규칙 3 — 서버 echo 전에 화면 값을 먼저 맞춰 둔다.
    patchLayer(id, key === 'scale' ? {scale: value / 100} : {rotation: value});
    // 도크의 숫자는 **도크가 보여 주는 레이어**의 것일 때만 고친다 - 캔버스에서 다른 레이어를
    // 굴리는 동안(도크가 밀려 있을 때) 남의 값을 도크에 적으면 표시가 거짓말을 한다.
    if (id === (panel.dataset.icDockLayer || '')) {
      const input = panel.querySelector(`[data-ic-tr="${key}"]`);
      const label = panel.querySelector(`[data-ic-val="${key}"]`);
      if (input && input.value !== String(value)) input.value = String(value);
      if (label) label.textContent = key === 'scale' ? `${value}%` : `${value}°`;
    }
    // 기준점을 안 주면 백엔드가 캔버스 한가운데를 잡는다(슬라이더·± 가 그 경우다).
    const payload = key === 'scale' ? {value: value / 100} : {value};
    if (at) payload.at = at;
    sendLayerTransform(id, key, payload);
  }

  /** 복원 1단계 - 출처 이미지를 고른다.
   *
   *  사용자 지정 2026-09-10: **이미지를 먼저 고르고**, 무엇을 되살릴지는 그 뒤에 묻는다.
   *  그래서 여기서는 scope 를 정하지 않고 `probe` 로 내용만 확인한다.
   */
  async function openRestorePicker(anchor) {
    closeRestorePicker();
    if (!panel) return;
    const pop = document.createElement('div');
    pop.className = 'ic-restore-pop';
    // 머리줄은 폭이 좁으므로 왼쪽 끝을 도크 기준으로 맞춘다. 위/아래는 `placeRestorePop` 이 잰다.
    const box = panel.getBoundingClientRect();
    const at = anchor ? anchor.getBoundingClientRect() : box;
    pop.style.left = `${Math.max(6, Math.min(at.left - box.left, box.width - 306))}px`;
    pop.innerHTML = `<div class="ic-restore-head">`
      + `<span>어느 이미지에서 가져올까요?</span>`
      + `<button type="button" class="ic-restore-x" data-ic="restore-close">&#10005;</button></div>`
      + `<button type="button" class="ic-restore-file" data-ic="restore-file">파일에서 열기…</button>`
      + `<div class="ic-restore-hint">EXIF 가 살아 있는 원본을 고르세요</div>`
      + `<div class="ic-restore-list" data-ic-list="1">불러오는 중…</div>`;
    panel.appendChild(pop);
    restorePop = pop;
    placeRestorePop(pop, at, box);

    // 히스토리는 곁들이다 - 없거나 실패해도 파일 열기는 그대로 쓸 수 있어야 한다.
    try {
      const response = await fetch('/api/history/list?page=0&per_page=24');
      const data = await response.json();
      const images = Array.isArray(data && data.images) ? data.images : [];
      const list = pop.querySelector('[data-ic-list]');
      if (!list) return;
      list.innerHTML = images.length
        ? images.map(item => `<button type="button" class="ic-restore-item"`
            + ` data-ic-path="${escHtml(String(item.rel_path || ''))}"`
            + ` title="${escHtml(String(item.filename || ''))}">`
            + `<img src="${escHtml(String(item.thumb_url || ''))}" alt="" loading="lazy"></button>`).join('')
        : `<div class="ic-restore-hint">히스토리가 비어 있습니다</div>`;
      // 썸네일이 들어오면 키가 자란다 - 다시 잰다(첫 배치는 '불러오는 중…' 한 줄로 쟀다).
      if (restorePop === pop) placeRestorePop(pop, at, box);
    } catch (_error) {
      const list = pop.querySelector('[data-ic-list]');
      if (list) list.innerHTML = `<div class="ic-restore-hint">히스토리를 못 읽었습니다</div>`;
    }
  }

  /** 팝업의 위/아래를 정한다. 도크는 뷰어 **아래쪽**에 붙어 있어(`bottom: 6px`) 아래로 펴면
   *  GENERATION INFO 바 밑으로 들어가 히스토리 줄이 잘렸다(사용자 제보 2026-09-13). 그래서
   *  **위로 펴는 것이 기본**이고, 위가 모자랄 때만 아래로 편다. 썸네일이 늦게 들어와 키가 자라므로
   *  붙인 직후와 목록이 찬 뒤 두 번 부른다. */
  function placeRestorePop(pop, at, box) {
    const height = pop.getBoundingClientRect().height;
    const roomAbove = at.top - 8;
    const roomBelow = window.innerHeight - at.bottom - 8;
    if (roomAbove >= height || roomAbove >= roomBelow) {
      pop.style.top = 'auto';
      pop.style.bottom = `${Math.max(4, box.bottom - at.top + 4)}px`;
    } else {
      pop.style.bottom = 'auto';
      pop.style.top = `${at.bottom - box.top + 4}px`;
    }
  }

  function closeRestorePicker() {
    if (restorePop && restorePop.parentElement) restorePop.parentElement.removeChild(restorePop);
    restorePop = null;
  }

  /** 복원 2단계 - 고른 것에 무엇이 들었는지 보고, 무엇을 되살릴지 묻는다. */
  async function runRestore(init) {
    try {
      const probe = await fetch('/api/img2img/restore-prompts?probe=1', init);
      const data = await probe.json().catch(() => ({}));
      if (!probe.ok) throw new Error(data.error || `HTTP ${probe.status}`);
      const found = data.found || {};
      const hasMain = !!found.has_main;
      const count = Number(found.character_count || 0);
      if (!hasMain && !count) {
        showToast('그 이미지에는 복원할 프롬프트가 없습니다', 'error');
        return;
      }
      // 없는 선택지는 아예 내밀지 않는다 - 고른 뒤에 실패를 보면 안 된다.
      const choices = [];
      if (hasMain && count) choices.push({key: 'both', label: `둘 다 (메인 + 캐릭터 ${count}명)`});
      if (count) choices.push({key: 'characters', label: `캐릭터 프롬프트만 (${count}명)`});
      if (hasMain) choices.push({key: 'main', label: '메인 프롬프트만'});
      let scope = choices.length === 1 ? choices[0].key : 'both';
      if (typeof showConfirmDialog === 'function' && choices.length > 1) {
        const lines = [];
        if (hasMain) lines.push(`메인: ${String(found.main_preview || '').slice(0, 60)}`);
        (found.character_previews || []).forEach((text, i) => lines.push(`C${i + 1}: ${text}`));
        scope = await showConfirmDialog('무엇을 복원할까요?', {
          title: found.label ? `${found.label} 에서 복원` : '프롬프트 복원',
          messageHtml: lines.map(line => escHtml(line)).join('<br>'),
          choices,
        });
        if (!scope) return;                       // 취소 - 아무것도 안 한다
      }
      const applied = await fetch(
        `/api/img2img/restore-prompts?pending=1&scope=${encodeURIComponent(scope)}`,
        {method: 'POST'});
      const result = await applied.json().catch(() => ({}));
      if (!applied.ok) throw new Error(result.error || `HTTP ${applied.status}`);
    } catch (error) {
      showToast(error.message || '프롬프트 복원에 실패했습니다', 'error');
    }
  }

  function onClick(event) {
    // ── 프롬프트 복원 ─────────────────────────────────────────────────
    if (event.target.closest?.('[data-ic-path]')) {
      const path = event.target.closest('[data-ic-path]').dataset.icPath;
      closeRestorePicker();
      runRestore({
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({path}),
      });
      return;
    }
    const action = event.target.closest?.('[data-ic]')?.dataset.ic;
    if (!action) return;
    if (action === 'restore-close') return closeRestorePicker();
    if (action === 'restore-prompts') {
      const button = event.target.closest('[data-ic]');
      if (restorePop) closeRestorePicker();
      else openRestorePicker(button);
      return;
    }
    if (action === 'restore-file') {
      const input = document.createElement('input');
      input.type = 'file';
      input.accept = 'image/*';
      input.addEventListener('change', async () => {
        const file = input.files && input.files[0];
        if (!file) return;
        closeRestorePicker();
        await runRestore({
          method: 'POST',
          headers: {'Content-Type': file.type || 'application/octet-stream'},
          body: file,
        });
      });
      input.click();
      return;
    }
    if (action === 'mode-edit') return setViewMode('edit');
    if (action === 'mode-result') return setViewMode('result');
    if (action === 'grid') {
      showGrid = !showGrid;
      write(GRID_KEY, showGrid ? '1' : '0');
      return render();
    }
    if (action === 'asset-save-frame') {
      // 조작이 아직 서버에 안 갔으면 먼저 흘려보낸다 - 안 그러면 방금 맞춘
      // 위치가 빠진 합성본이 저장된다(슬라이더는 마지막 값만 보낸다).
      flushTransforms();
      return onSaveCharacterAssetFrame('frame');
    }
    if (action === 'asset-save-generated') {
      flushTransforms();
      return onSaveCharacterAssetFrame('generated');
    }
    if (action === 'undo') return undoTransform();
    if (action === 'reset') {
      const id = dockLayerId();
      return id ? resetLayer(id) : undefined;
    }
    if (action === 'show-layers') return setLayersOpen(true);
    // 도크의 ± 는 **도크가 보여 주는 레이어**를 민다(`dockLayerId` 주석).
    if (action === 'zoom-in') return nudge('scale', 1, dockLayerId());
    if (action === 'zoom-out') return nudge('scale', -1, dockLayerId());
    if (action === 'rot-up') return nudge('rotation', 1, dockLayerId());
    if (action === 'rot-down') return nudge('rotation', -1, dockLayerId());
    // 90° 는 자주 쓰는 자리라 한 번에 간다 - 슬라이더로 정확히 90 을 맞추기는 번거롭다.
    if (action === 'rot-quarter') return nudge('rotation', 90, dockLayerId());
    if (action === 'mask') return openMaskEditor();
    if (action === 'auto-mask') {
      // ⚠️ **여기도 flush 가 먼저다.** 빈 곳은 지금 배치에서 계산되는데, 미뤄 둔
      //    변형이 남아 있으면 서버는 **옛 배치**로 칠하고 그 결과가 사용자 마스크로
      //    굳는다 - 나중에 변형이 도착해도 엉뚱한 자리가 생성 대상으로 남는다
      //    (Codex 리뷰 2026-08-27).
      flushTransforms();
      // 자동 마스킹은 화면이 거의 안 바뀔 수 있다(빈 곳이 없으면 아무것도 안 칠한다).
      // 눌렀는데 아무 말이 없으면 고장으로 읽힌다 - 결과는 상태가 도착할 때 말한다.
      autoMaskPending = true;
      clearTimeout(autoMaskTimer);
      autoMaskTimer = setTimeout(() => { autoMaskPending = false; }, 4000);
      return send('auto_mask', 'true');
    }
    // ⚠️ **`send('clear_mask')` 를 직접 부르지 않는다.** 그러면 서버만 지워지고
    //    브라우저의 마스크 초안이 남아, 에디터를 다시 열면 지운 마스크가 되살아난다.
    //    지우는 입구가 둘(도크의 [지우기] · 에디터의 [초기화])인데 초안까지 지우는
    //    쪽은 하나뿐이었다 - 같은 함수로 합친다.
    if (action === 'clear-mask') return onClearMask();
    // ⚠️ 생성/닫기 전에 미뤄 둔 변형을 먼저 보낸다 - 순서가 뒤집히면 옛 그림으로 굽는다.
    if (action === 'generate') return requestGenerate();
    if (action === 'close') { flushTransforms(); return onClose(); }
  }

  function onChange(event) {
    if (event.target.closest?.('[data-ic="size"]')) {
      // 캔버스가 바뀌면 예전 **픽셀** 좌표는 뜻이 달라진다(세로->가로면 아예 밖이다).
      undoStack = [];
      send('canvas_size', event.target.value);
    }
  }

  function onInput(event) {
    const transform = event.target?.dataset?.icTr;
    if (transform) {
      // 슬라이더도 도크가 보여 주는 레이어를 고친다. 끄는 동안 도크는 다시 안 그려지므로
      // 이 id 가 곧 **누른 순간의 레이어**다(끄는 사이 다른 레이어가 골라져도 안 바뀐다).
      const id = dockLayerId();
      if (!id) return;
      applyTransform(transform, transform === 'scale'
        ? clampPct(event.target.value)
        : wrapDeg(event.target.value), null, id);
      return;
    }
    const key = event.target?.dataset?.icRange;
    if (key) {
      // 값 표시는 여기서 직접 맞춘다 - 팝업이 안 열려 있어 저쪽 라벨은 존재하지 않는다.
      const raw = Math.max(key === 'strength' ? 1 : 0, Math.min(99, Math.round(Number(event.target.value) || 0)));
      const label = panel.querySelector(`[data-ic-val="${key}"]`);
      if (label) label.textContent = ratio(key === 'strength' && raw === 99 ? 1 : raw / 100);
      onSlider(key, raw);
      return;
    }
    if (event.target?.dataset?.icNum === 'repeat') onRepeat(event.target.value);
  }

  function onPanelPointerDown(event) {
    if (event.target?.matches?.('input[type="range"]')) rangeDragging = true;
  }

  function onPlanePointerDown(event) {
    if (!stageEl) return;
    // 레이어 목록의 고르기 팝업은 캔버스를 누르면 닫는다.
    if (closeLayerPicker()) renderLayers(viewMode === 'edit');
    // 마커는 표시 전용이라 붙잡지 않는다 - 그 위에서 눌러도 베이스가 움직인다.
    if (event.button === 1) { event.preventDefault(); beginMiddleDrag(event); return; }
    if (event.button !== 0) return;
    // 누른 자리에 보이는 맨 위 레이어를 고르고 **곧바로** 끈다(파워포인트처럼).
    // 아무 레이어도 없는 빈 곳이면 고른 레이어를 그대로 끈다 - 예전의 "어디서나 끈다".
    const hit = layerAt(canvasPointOf(event));
    if (hit && hit !== activeLayerId()) selectLayer(hit);
    beginBaseDrag(event);
  }

  /** 그림 위 **어디서나** 끌어서 옮긴다(사용자 지정 2026-08-26, 파워포인트처럼).
   *
   *  ⚠️ 좌표를 `pointToContent` 로 받으면 안 된다. 그건 스테이지 밖을 **잘라낸다**
   *     (마커는 캔버스 안에 있어야 하니 그쪽에는 맞는 동작이다). 베이스를 밖으로 밀
   *     때는 커서가 스테이지를 벗어나는데, 그러면 델타가 가장자리에서 멈춰 **덜 간다**
   *     - 사용자 제보 "정확한 위치로 놓여지지 않습니다". 화면 픽셀 델타를 직접 재서
   *     캔버스 배율로만 나눈다.
   */
  function beginBaseDrag(event) {
    const host = stageEl;
    const {w, h} = canvasSize();
    const rect = host.getBoundingClientRect();
    if (!(rect.width > 0) || !(w > 0) || !(h > 0)) return;
    const perX = w / rect.width;
    const perY = h / rect.height;
    const startX = event.clientX;
    const startY = event.clientY;
    // 끄는 것은 **누른 순간 고른 레이어**다. 끄는 사이에 echo 가 와도 대상이 바뀌지 않는다.
    const layer = tx();
    const startSnap = transformSnapshot(layer.id);
    const startOffset = {x: layer.x, y: layer.y};
    const placedW = layer.placedW;
    const placedH = layer.placedH;
    const ghost = host.querySelector('[data-ic-ghost]');

    posStage.beginFreeDrag(event, host, (ev) => {
      const ox = Math.round(startOffset.x + (ev.clientX - startX) * perX);
      const oy = Math.round(startOffset.y + (ev.clientY - startY) * perY);
      pendingOffset = {x: ox, y: oy};
      // 그림 자체는 서버가 다시 합성해야 움직인다(놓을 때 한 번). 끄는 동안에는
      // **어디에 놓이는지**와 **얼마나 새 자리가 열리는지**를 유령으로 보여 준다.
      if (ghost) {
        ghost.hidden = false;
        // 회전이 남긴 변환을 지운다 - 이동 유령은 좌상단 기준이다(같은 요소를 쓴다).
        ghost.style.transform = '';
        ghost.style.left = `${(ox / w) * 100}%`;
        ghost.style.top = `${(oy / h) * 100}%`;
        ghost.style.width = `${(placedW / w) * 100}%`;
        ghost.style.height = `${(placedH / h) * 100}%`;
      }
    }, () => {
      if (!pendingOffset) return;
      const {x: ox, y: oy} = pendingOffset;
      pendingOffset = null;
      // 끄는 동안에는 `state` 가 안 바뀌므로, 여기서 쌓으면 **끌기 전 자리**가 담긴다.
      // 드래그 한 번 = 한 단계다(사용자가 되돌리고 싶은 단위가 그것이다).
      pushUndo(startSnap);
      setLayerOffset(layer.id, ox, oy);
      sendOffset(layer.id, ox, oy);
    });
  }

  function commit({x, y, key}) {
    if (key === 'base') {
      if (pendingOffset) {
        const {x: ox, y: oy} = pendingOffset;
        pendingOffset = null;
        const id = activeLayerId();
        pushUndo();
        // 규칙 3 — 서버 echo 전에 화면 값을 먼저 맞춰 둔다.
        setLayerOffset(id, ox, oy);
        sendOffset(id, ox, oy);
      }
      return;
    }
    const index = Number(String(key).replace('char_', ''));
    if (!Number.isFinite(index)) return;
    const character = (state?.characters || [])[index];
    if (character) character.position = {x, y};
    send(`char_position_${index}`, {x, y});
  }

  /** 이 조작들은 **인페인트 세션 안에서만** 산다(사용자 지정 2026-08-26).
   *
   *  ⚠️ 방향키와 중앙 버튼은 document 를 가로챈다. 세션이 끝나도 붙어 있으면 앱 전체의
   *     입력을 조용히 갉아먹는다 - 세션이 열릴 때 걸고, 닫히는 즉시 돌려준다.
   */
  let sessionInputTeardown = null;

  function armSessionInput() {
    if (sessionInputTeardown) return;

    // ⚠️ Chromium 은 중앙 버튼을 누르면 **자동 스크롤**(사방향 커서)을 띄운다.
    //    `pointerdown` 만 막아도 되는 것이 원칙이지만, 빌드에 따라 호환 `mousedown`
    //    으로 새는 경우가 있어 셋 다 막는다.
    const swallowMiddle = (event) => {
      if (event.button === 1 && plane?.contains(event.target)) event.preventDefault();
    };
    const swallowAux = (event) => {
      if (event.button === 1 && plane?.contains(event.target)) event.preventDefault();
    };
    document.addEventListener('mousedown', swallowMiddle, true);
    document.addEventListener('auxclick', swallowAux, true);

    // 휠 = 크기(커서 붙잡음), Ctrl+휠 = 회전.
    //
    // ⚠️ Ctrl+휠은 원래 **Electron 셸의 UI 배율**이다(`preload.cjs` 가 window 에
    //    capture 로 물고 stopPropagation 한다). 페이지에서는 가로챌 수 없어서, 그쪽
    //    예외 목록에 `.ic-plane` 을 적어 두고서야 여기까지 온다. 예외를 안 적으면
    //    이 리스너는 **영영 안 불린다**(사용자 제보 2026-08-26).
    const onWheel = (event) => {
      if (viewMode !== 'edit' || !state?.active) return;
      if (!plane?.contains(event.target)) return;
      event.preventDefault();
      event.stopPropagation();
      const dir = event.deltaY < 0 ? 1 : -1;
      const boost = event.shiftKey ? WHEEL_COARSE : 1;
      if (event.ctrlKey) {
        nudge('rotation', dir * WHEEL_ROTATE_DEG * boost);
        return;
      }
      // 커서 아래를 붙잡고 키운다 - 안 붙잡으면 굴릴수록 그림이 도망간다.
      const next = clampPct(tx().scale * 100 + dir * WHEEL_SCALE_PCT * boost);
      applyTransform('scale', next, canvasPointOf(event));
    };
    plane?.addEventListener('wheel', onWheel, {passive: false});

    // Ctrl 을 쥐면 **회전할 수 있다는 것을 커서로 알린다**(사용자 지적: 회전 커서가
    // 안 보인다). 표식은 매 렌더마다 새로 나는 스테이지가 아니라 **plane** 에 붙인다.
    const syncRotateCursor = (event) => {
      plane?.classList.toggle('is-rotate',
        !!(event?.ctrlKey) && viewMode === 'edit' && !!state?.active);
    };
    const dropRotateCursor = () => plane?.classList.remove('is-rotate');
    document.addEventListener('keydown', syncRotateCursor);
    document.addEventListener('keyup', syncRotateCursor);
    window.addEventListener('blur', dropRotateCursor);

    const onKeyDown = (event) => {
      if (viewMode !== 'edit' || !state?.active) return;
      const active = document.activeElement;
      // 글자를 치고 있으면 손대지 않는다.
      if (active && active.matches?.('input, textarea, select, [contenteditable="true"]')) return;
      // Ctrl+Z = 이동/회전 한 단계 되돌리기(사용자 지정 2026-08-30).
      // ⚠️ 위 가드가 입력칸을 이미 걸러 낸다 - 글자를 치는 중에는 브라우저 기본
      //    되돌리기가 먹어야 한다.
      if ((event.ctrlKey || event.metaKey) && !event.shiftKey && (event.key === 'z' || event.key === 'Z')) {
        event.preventDefault();
        undoTransform();
        return;
      }
      const step = event.shiftKey ? NUDGE_PX_COARSE : NUDGE_PX;
      const move = {ArrowLeft: [-step, 0], ArrowRight: [step, 0],
                    ArrowUp: [0, -step], ArrowDown: [0, step]}[event.key];
      if (move) {
        event.preventDefault();
        pushUndo();
        const t = tx();
        const ox = Math.round(t.x + move[0]);
        const oy = Math.round(t.y + move[1]);
        setLayerOffset(t.id, ox, oy);
        sendOffset(t.id, ox, oy);
        return;
      }
      if (event.key === '0') {
        event.preventDefault();
        resetLayer(activeLayerId());      // [초기화] 단추 · 우클릭 메뉴와 같은 함수
      }
    };
    document.addEventListener('keydown', onKeyDown);

    sessionInputTeardown = () => {
      plane?.removeEventListener('wheel', onWheel);
      document.removeEventListener('keydown', syncRotateCursor);
      document.removeEventListener('keyup', syncRotateCursor);
      window.removeEventListener('blur', dropRotateCursor);
      dropRotateCursor();
      document.removeEventListener('mousedown', swallowMiddle, true);
      document.removeEventListener('auxclick', swallowAux, true);
      document.removeEventListener('keydown', onKeyDown);
      sessionInputTeardown = null;
    };
  }

  function disarmSessionInput() {
    // 끌고 있던 것이 있으면 먼저 끊는다 - 세션이 닫힌 뒤 놓아도 stale 좌표가 안 나간다.
    posStage?.cancelDrag?.();
    flushTransforms();
    if (sessionInputTeardown) sessionInputTeardown();
  }

  /** 화면 좌표를 캔버스 픽셀로. 확대의 기준점을 잡는 데 쓴다. */
  function canvasPointOf(event) {
    if (!stageEl) return null;
    const rect = stageEl.getBoundingClientRect();
    const {w, h} = canvasSize();
    if (!(rect.width > 0) || !(w > 0) || !(h > 0)) return null;
    return {
      x: Math.round((event.clientX - rect.left) / rect.width * w),
      y: Math.round((event.clientY - rect.top) / rect.height * h),
    };
  }

  /** 중앙 버튼 드래그: 크기(세로) / Ctrl 이면 회전(각도).
   *
   *  ⚠️ 크기는 **누른 지점**을, 회전은 **캔버스 한가운데**를 붙잡는다. 안 붙잡으면
   *     놓인 상자의 좌상단이 고정돼 키울수록 그림이 우하단으로 도망간다(실측:
   *     200% 에서 그림 한가운데가 캔버스 모서리, 400% 에서는 화면 밖).
   *  ⚠️ 중앙 버튼이 없는 입력기(터치·트랙패드·펜)가 있다 - 슬라이더와 ± 는 그대로
   *     남는다. 이건 빠른 길이지 유일한 길이 아니다.
   */
  function beginMiddleDrag(event) {
    const host = stageEl;
    const {w, h} = canvasSize();
    const rect = host.getBoundingClientRect();
    if (!(rect.width > 0) || !(w > 0) || !(h > 0)) return;
    const rotating = event.ctrlKey;
    // 고른 레이어를 키우거나 돌린다(가운데 버튼은 레이어를 새로 고르지 않는다 - 휠과 같다).
    const layer = tx();
    const startScale = clampPct(layer.scale * 100);
    const startSnap = transformSnapshot(layer.id);
    const startRotation = wrapDeg(layer.rotation);
    const ghost = host.querySelector('[data-ic-ghost]');
    // ⚠️ **`placed_*` 를 돌리면 안 된다.** 그건 이미 PIL 이 회전시킨 뒤의 축정렬
    //    바운딩 박스라(`utils/v5_inpaint_canvas.transform_base` 의 `expand=True`),
    //    그 사각형을 CSS 로 또 돌리면 두 번 부풀어 보인다(Codex 자문 2026-08-27).
    //    유령은 **회전 전 사각형**(베이스 x 배율)을 지금 놓인 자리의 한가운데에
    //    놓고 돌린다.
    // ⚠️ 이 유령은 **각도와 대략의 자리**를 보여 주는 조작 피드백이다 - 서버 결과와
    //    픽셀이 같다고 약속하지 않는다. 회전은 캔버스 한가운데를 붙잡으므로 그림이
    //    많이 치우쳐 있으면 놓을 때 조금 어긋난다.
    const preW = layer.w * layer.scale;
    const preH = layer.h * layer.scale;
    const cx = layer.x + (layer.placedW || preW) / 2;
    const cy = layer.y + (layer.placedH || preH) / 2;
    const startY = event.clientY;
    const at = canvasPointOf(event);   // 누른 지점 = 크기의 기준점
    if (rotating) plane?.classList.add('is-rotate');
    const pivot = {x: rect.left + rect.width / 2, y: rect.top + rect.height / 2};
    // ⚠️ 화면 각도(atan2, y 아래)는 **시계**가 양수인데 서버(PIL)는 **반시계**가 양수다. 그래서 회전은
    //    시작각에서 **뺀다** - 더하면 손을 반시계로 돌릴 때 그림은 시계로 돌았다(실측 2026-10-03:
    //    손 -30° -> 회전 330°, 유령은 손을 따라가고 결과는 반대로 기울었다).
    const angleOf = (ev) => Math.atan2(ev.clientY - pivot.y, ev.clientX - pivot.x) * 180 / Math.PI;
    const startAngle = angleOf(event);
    const startDist = Math.hypot(event.clientX - pivot.x, event.clientY - pivot.y);
    let sent = null;

    posStage.beginFreeDrag(event, host, (ev) => {
      if (rotating) {
        if (startDist < ROTATE_DEAD_ZONE_PX) return;
        const next = wrapDeg(startRotation - (angleOf(ev) - startAngle));   // 빼기 - 위 angleOf 주석
        sent = {key: 'rotation', value: next};
        // 끄는 **한 번**이 한 단계다. 여기서 열어 두면 아래 `applyTransform` 이
        // 프레임마다 불려도 기록은 하나뿐이다(Codex BLOCK 2).
        beginUndoGesture(startSnap);
        applyTransform('rotation', next, null, layer.id);
        // 그림 자체는 서버가 다시 합성해야 돈다(놓을 때 한 번). 끄는 동안에는
        // 유령이 각도를 보여 준다 - 예전에는 슬라이더 숫자만 바뀌고 화면에는
        // 아무 반응이 없었다(사용자 지적 2026-08-27).
        if (ghost && preW > 0 && preH > 0) {
          ghost.hidden = false;
          ghost.style.left = `${(cx / w) * 100}%`;
          ghost.style.top = `${(cy / h) * 100}%`;
          ghost.style.width = `${(preW / w) * 100}%`;
          ghost.style.height = `${(preH / h) * 100}%`;
          // ⚠️ 음수 각도다 - 서버(PIL)는 반시계로 돌리고 CSS 는 시계로 돈다. 예전에는 부호가
          //    같아 유령이 실제 그림과 **반대로** 돌았다(2026-10-03 레이어 테두리를 맞추다 발견).
          ghost.style.transform = `translate(-50%, -50%) rotate(${-next}deg)`;
        }
      } else {
        const next = clampPct(startScale + (startY - ev.clientY) / MIDDLE_SCALE_PX_PER_PCT);
        sent = {key: 'scale', value: next};
        applyTransform('scale', next, at, layer.id);
      }
    }, () => {
      // 제스처가 끝났다 - 다음 조작은 새 단계로 쌓인다.
      endUndoGesture();
      // 놓는 순간 마지막 값을 곧바로 보낸다 - 디바운스가 남아 있으면 거기서 또 간다.
      if (!sent) return;
      if (sent.key === 'scale') sendLayerTransform(layer.id, 'scale', {value: sent.value / 100, at});
      else sendLayerTransform(layer.id, 'rotation', {value: sent.value});
      sent = null;
      if (rotating) plane?.classList.remove('is-rotate');
    });
  }

  if (panel) {
    // 도크가 실제로 차지한 높이를 뷰어에 적어 둔다. 캔버스가 그만큼 비켜선다 -
    // 고정값으로 박으면 좁은 창에서 줄이 접혀 도크가 그림을 덮는다(실측 286px).
    // 도크 높이 -> plane 여백 -> 스테이지 크기. 셋이 사슬로 물려 있다.
    //
    // ⚠️ **콜백 안에서 레이아웃을 바꾸면 안 된다.** 바로 쓰면 같은 프레임 안에서
    //    관찰 대상이 또 바뀌어 브라우저가 "ResizeObserver loop completed with
    //    undelivered notifications" 를 던진다(실측). 다음 프레임으로 미루고,
    //    값이 그대로면 아예 쓰지 않는다 - 둘 다 있어야 사슬이 멎는다.
    const deferred = (fn) => {
      let queued = 0;
      return () => {
        if (queued) return;
        queued = requestAnimationFrame(() => { queued = 0; fn(); });
      };
    };

    if (viewer && typeof ResizeObserver === 'function') {
      let lastDockH = -1;
      const syncDockHeight = deferred(() => {
        const h = Math.round(panel.getBoundingClientRect().height);
        if (h === lastDockH) return;
        lastDockH = h;
        viewer.style.setProperty('--ic-dock-h', `${h}px`);
      });
      new ResizeObserver(syncDockHeight).observe(panel);
    }
    // 남는 자리가 바뀌면(도크가 접히거나 줄이 늘거나 창이 바뀌면) 다시 앉힌다.
    if (plane && typeof ResizeObserver === 'function') {
      let lastBox = '';
      const refit = deferred(() => {
        const box = `${plane.clientWidth}x${plane.clientHeight}`;
        if (box === lastBox) return;
        lastBox = box;
        fitStage();
      });
      new ResizeObserver(refit).observe(plane);
    }
    panel.addEventListener('click', onClick);
    panel.addEventListener('change', onChange);
    panel.addEventListener('input', onInput);
    panel.addEventListener('pointerdown', onPanelPointerDown);
    panel.addEventListener('contextmenu', onDockContextMenu);
    plane?.addEventListener('pointerdown', onPlanePointerDown);
    plane?.addEventListener('contextmenu', onStageContextMenu);
    // 레이어 목록은 뷰어 오른쪽에 따로 떠 있다(도크와 한 상자에 넣으면 캔버스를 더 가린다).
    if (viewer) {
      layersEl = document.createElement('div');
      layersEl.className = 'ic-layers';
      layersEl.hidden = true;
      layersEl.setAttribute('aria-label', '레이어');
      viewer.appendChild(layersEl);
      layersEl.addEventListener('click', onLayersClick);
      layersEl.addEventListener('contextmenu', onLayersContextMenu);
      for (const target of [layersEl, plane].filter(Boolean)) {
        target.addEventListener('dragenter', onLayerDragOver);
        target.addEventListener('dragover', onLayerDragOver);
        target.addEventListener('dragleave', onLayerDragLeave);
        target.addEventListener('drop', onLayerDrop);
      }
      // 고르기 팝업 · 우클릭 메뉴는 바깥을 누르면 닫는다.
      document.addEventListener('pointerdown', (event) => {
        if (layerMenu && !layerMenu.contains(event.target)) closeLayerMenu();
        if (layerPop && !layersEl.contains(event.target)) {
          closeLayerPicker();
          renderLayers(viewMode === 'edit');
        }
      }, true);
      // Esc · 창 크기 · 스크롤 · 초점 잃음에도 메뉴를 닫는다(떠 있는 자리가 뜻을 잃는다).
      document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape' && closeLayerMenu()) event.stopPropagation();
      }, true);
      window.addEventListener('resize', closeLayerMenu);
      window.addEventListener('blur', closeLayerMenu);
      window.addEventListener('wheel', closeLayerMenu, {passive: true, capture: true});
    }
    // 슬라이더는 패널 밖에서 손을 떼도 끝난다 - document 에서 받아야 놓치지 않는다.
    const endRangeDrag = () => {
      const wasDragging = rangeDragging;
      rangeDragging = false;
      // 끄는 동안 밀린 도크(다른 레이어가 골라졌을 수 있다)를 손을 뗀 지금 그린다.
      if (wasDragging) settleDock();
    };
    document.addEventListener('pointerup', endRangeDrag);
    document.addEventListener('pointercancel', endRangeDrag);
    // 반복 칸에서 나온 뒤의 첫 클릭에도 그린다(패널의 click 처리기가 먼저 돈 뒤다).
    document.addEventListener('click', settleDock);
    posStage = createPosStage({
      // 스테이지는 매 렌더마다 새로 만들어진다 - 함수로 넘겨 늘 살아 있는 것을 잰다.
      stage: () => stageEl,
      getContentSize: canvasSize,
      onCommit: commit,
      onDragEnd: () => {
        // 재렌더가 유령을 지우지만, 커밋이 없어 다시 그리지 않는 경우도 있다.
        const spirit = stageEl?.querySelector('[data-ic-ghost]');
        if (spirit) { spirit.setAttribute('hidden', ''); spirit.style.transform = ''; }
        render();
      },
    });
  }

  return {
    render,
    /** 헤더의 Inpaint 버튼을 **다시 눌러** 닫는 길(사용자 지정 2026-08-29).
     *
     *  ⚠️ `세션 닫기` 버튼과 **같은 일**을 해야 한다. 미뤄 둔 변형을 먼저 흘려보내지
     *     않으면 백엔드가 옛 배율로 굽는다 - 여는 입구와 닫는 입구가 갈리면 그 차이가
     *     그대로 돈이 된다(Codex 리뷰 2026-08-26 BLOCK 1 과 같은 계열).
     */
    requestClose() {
      flushTransforms();
      return onClose();
    },
    /** 생성이 끝나면 결과를 봐야 한다 - 캔버스가 결과를 가리고 있으면 안 된다. */
    showResult() {
      // ⚠️ 이건 **자동** 전환이다(새 결과가 도착해 캔버스를 치웠다). 사용자는 아무것도
      //    안 눌렀으니, 바뀌었다는 사실을 눈으로 알려야 한다 - 안 그러면 편집으로
      //    돌아가는 길을 못 찾는다(사용자 제보 2026-08-28 "포커스 노출이 느슨하다").
      //    이미 결과 보기면 바뀐 게 없으므로 번쩍이지 않는다.
      if (viewMode !== 'result') flashModes = true;
      setViewMode('result');
    },
    /** Inpaint 를 눌러 세션이 열렸다. 도크가 **반드시** 눈에 보이게 한다.
     *
     *  ⚠️ 이게 없으면 버튼이 조용히 아무 일도 안 한 것처럼 보이는 길이 셋이나 된다:
     *    · 접어 둔 상태가 저장돼 있으면 24px 알약만 떠서 못 알아본다
     *    · 직전 세션에서 `결과 보기` 로 끝났으면 캔버스가 안 그려진다
     *    · 반복 칸에 커서가 남아 있으면 `typingInPanel` 가드가 렌더를 통째로 막는다
     *  세 가지 모두 여기서 풀고 그린다.
     */
    revealForSession() {
      viewMode = 'edit';
      if (document.activeElement && panel?.contains(document.activeElement)) {
        try { document.activeElement.blur(); } catch (_) {}
      }
      rangeDragging = false;
      render();
    },
    /** 지금 무대가 놓인 자리와 캔버스 해상도. 캐릭터 POS 무대가 여기 겹쳐 선다.
     *
     *  ⚠️ 캔버스가 떠 있는 동안 화면의 그림은 `#preview` 가 아니고, 생성 해상도도
     *     파라미터가 아니라 캔버스 크기다. 이걸 안 알려 주면 POS 무대가 파라미터
     *     비율로 서서 그림과 어긋난다(사용자 제보: "현재 이미지와 POS 해상도 불일치").
     */
    stageRect() {
      if (!stageEl || plane?.hidden) return null;
      const r = stageEl.getBoundingClientRect();
      const {w, h} = canvasSize();
      if (!(r.width > 0) || !(r.height > 0) || !(w > 0) || !(h > 0)) return null;
      return {left: r.left, top: r.top, width: r.width, height: r.height, w, h};
    },
    /** POS 무대가 얹힐 수 있게 **편집 모드**로 되돌린다.
     *
     *  POS 좌표는 "지금 생성할 캔버스" 의 좌표계다 - 결과 보기는 이미 나온 그림을
     *  보는 화면이라 얹을 판이 없다(평면이 감춰져 `stageRect()` 가 null 이다).
     *  세션이 없거나 캔버스를 안 쓰면 아무것도 안 한다.
     */
    ensureEditMode() {
      if (!state?.active || !state?.canvas_supported) return false;
      if (viewMode === 'edit') return false;
      // 사용자가 결과를 보다 들어왔다 - 나갈 때 돌려주려고 적어 둔다
      // (Codex 리뷰 2026-08-30 CONCERN 5: 나가도 편집 모드에 남아 있었다).
      posEntryViewMode = viewMode;
      setViewMode('edit');
      return true;
    },
    /** POS 를 나갈 때 들어오기 전 모드로 되돌린다. 바꾼 적이 없으면 아무것도 안 한다. */
    restoreViewModeAfterPos() {
      if (!posEntryViewMode) return false;
      const back = posEntryViewMode;
      posEntryViewMode = '';
      // 그 사이에 세션이 닫혔거나 사용자가 직접 모드를 골랐으면 건드리지 않는다.
      if (!state?.active || !state?.canvas_supported) return false;
      if (viewMode !== 'edit') return false;
      setViewMode(back);
      return true;
    },
    handleModuleState(payload) {
      if (payload && payload.module_id === 'img2img') render(payload);
    },
    /** 붙여넣은 이미지를 **새 레이어**로 받는다(사용자 지정 2026-10-03, 포토샵처럼).
     *
     *  세션이 없거나 캔버스를 안 쓰면 false - 부른 쪽이 예전 길(이미지 동작 팝업)로 간다.
     *  ⚠️ 결과 보기 중이었으면 **편집으로 돌아온다.** 올린 레이어가 안 보이면 붙여넣기가
     *     조용히 사라진 것으로 읽힌다.
     */
    acceptPastedImage(blob, label = '') {
      if (!state?.active || !state?.canvas_supported || !blob) return false;
      if (viewMode !== 'edit') setViewMode('edit');
      if (closeLayerPicker()) renderLayers(true);
      // 클립보드 그림에는 이름이 없다(앱이 붙인 'Clipboard Image') - 목록에서 알아보게 적는다.
      const generic = !label || label === 'Clipboard Image';
      uploadLayer(blob, {label: generic ? '붙여넣기' : label});
      return true;
    },
    /** 인페인트 세션이 열려 있는가(캔버스를 쓰는 세션). 히스토리 삭제가 이 동안에는 반드시 묻는다. */
    isSessionActive() {
      return !!(state?.active && state?.canvas_supported);
    },
    /** Del(· Backspace · Ctrl+D) 키. **편집 화면에서는 이 키가 레이어의 것**이다 - true 를 돌려주면
     *  히스토리는 아무것도 지우지 않는다(사용자 제보 2026-10-05).
     *
     *  고른 레이어를 (묻고 나서) 지운다. 원본을 골랐으면 지우지 않고 말해 준다 - 조용하면
     *  키가 죽은 것으로 읽히고, 그렇다고 히스토리로 넘기면 엉뚱한 것이 지워진다.
     *  결과 보기 중에는 false - 그때 보이는 것은 결과 그림이라 예전처럼 히스토리의 키다.
     */
    handleDeleteKey() {
      if (!state?.active || !state?.canvas_supported || viewMode !== 'edit') return false;
      closeLayerMenu();
      const id = activeLayerId();
      if (id === 'base') {
        showToast?.('원본은 지울 수 없습니다 - 지울 레이어를 먼저 고르세요', 'info');
        return true;
      }
      removeLayer(id);
      return true;
    },
    /** 큰 Generate 버튼이 지나는 문. 도크 버튼과 **같은 함수**다 - 가드도 flush 도
     *  한 자리에 있어야 한 쪽만 빠뜨리는 일이 없다. */
    generate: () => requestGenerate(),
  };
}
