/** 레퍼런스 인셋 창 - 그림을 넣고, 켜고 끄고, 배치를 정한다(사용자 지정 2026-10-09 · 10-10 개편 · 목업 승인).
 *
 *  여는 곳: **Fn > 레퍼런스 인셋**(꽂아 둔 것이 없어도 열린다) · Result 왼쪽 위의 인셋 띠.
 *
 *      ┌─ 레퍼런스 인셋 ──────────── [켬 ●] [×] ┐
 *      │ ┌───────────┃──────────────────────┐ │
 *      │ │           ┃                      │ │   ┃ = 경계선. 좌우로 끌어 **칸의 너비**를 정한다.
 *      │ │ (칸 안의  ▮      그릴 곳           │ │   칸은 늘 왼쪽에 붙어 있다.
 *      │ │   그림) ◻ ┃                      │ │   칸 안의 그림: 끌면 옮겨지고, 휠 · ◻ 로 크기가 바뀐다.
 *      │ └───────────┃──────────────────────┘ │
 *      │ 칸의 그림  [붙여넣기] [저장] [Storage] [업스케일]            (상태 한 줄) │
 *      │ 캔버스    [1:1][9:7][3:2][16:9] [기본값]              칸 616px · 그릴 곳 60% │
 *      │ 해상도    [1216x832][1536x1024 · Anlas 소모][1728x1216 · Anlas 소모]        │
 *      │ 결과      ☐ 인셋 칸을 빼고 남기기                              Anlas 소모 │
 *      └──────────────────────────────────────┘
 *
 *  상태는 셋이다(서버의 `configured` · `active`):
 *    - 꽂아 둔 것이 없다 → '레퍼런스로 쓸 그림을 넣어 주세요' + [붙여넣기] [Storage] [Assets]
 *    - 꽂아 뒀고 켜져 있다 → 다음 생성이 인셋으로 나간다
 *    - 꽂아 뒀는데 꺼져 있다 → 일반 생성. **그림 · 배치 · 해상도는 그대로** 남아 있고 스위치로 다시 켠다
 *      (예전에는 끄면 전부 사라져 처음부터 다시 꽂아야 했다).
 *
 *  [붙여넣기] = 클립보드의 그림을 칸의 그림으로. ⚠️ **단추로만** 받는다 - 창이 떠 있는 동안 Ctrl+V 를 가로채던
 *    것은 회수했다(사용자 결정 2026-10-10: 다른 데 붙여넣으려던 그림이 이리로 왔다). 되살리지 말 것.
 *  [저장] = 지금 칸의 그림을 **Storage** 에 넣는다. 눌렀을 때만 들어간다 - 붙여넣은 그림은 저장하지 않으면 앱을
 *    끌 때 사라진다. 기억하는 것은 그림뿐이다(배치는 꺼낼 때마다 기본). 업스케일해 뒀으면 올려 둔 판이 들어간다.
 *  [Storage] = 저장해 둔 그림 목록. 누르면 그 그림을 칸에 놓고 인셋을 켠다. x = 보관본 지우기(두 번 눌러야 지운다).
 *  [업스케일] = 레퍼런스 **원본**을 NAI 업스케일에 한 번 보내 두고, 그 뒤로는 거기서 줄여 칸에 놓는다
 *    (Anlas 가 든다 · 그림 하나에 한 번). ⚠️ 구운 캔버스를 올렸다가 되줄이는 방식은 실측에서 아무것도 못 바꿨다
 *    - [수정] 단추와 잠금이 있던 그 판으로 되돌리지 말 것.
 *  캔버스 = **비율(종류)을 고르고 그 안에서 크기를 고른다**(사용자 지정 2026-10-10): 비율마다 1MP · Large · Wallpaper
 *    세 급. 비율을 바꾸면 같은 급의 크기로 간다. 1MP 를 넘는 크기는 **Anlas 를 소모한다** - 칩에 'Anlas 소모' 라고만
 *    적는다(소모량을 숫자로 적지 않는다 - 사용자 지정 2026-10-10: 실제 소모량이 불명확하다). 드는가 아닌가는 서버의
 *    `canvas_costs`(0 이면 무료)로 가린다. 목록 · 묶음은 전부 서버가 실어 보낸다.
 *  에셋의 그림은 Assets 탭의 [C1+레퍼런스 인셋] 으로 꽂는다 - 이 창 안에서 에셋을 고르지는 않는다(사용자 결정).
 *  [Assets] = 그 Assets 탭을 연다(사용자 지시 2026-10-11). 꽂는 일은 여전히 거기서 한다 - 캐릭터 프롬프트(C1)와
 *  그림이 함께 실려야 하기 때문이다.
 *
 *  경위(10-09 하루에 세 번 바뀌었다 - 되돌리기 전에 읽을 것): 자유롭게 옮기는 박스 → "좌측은 무조건 왼쪽에 고정 ·
 *  사이즈만 · 이동 불가"(그림을 키우면 머리 쪽만 보였다) → "기존 사양처럼 경계선이 필요하고 내부 드래그 가능해야".
 *  그래서 **칸은 왼쪽 고정이고, 옮기는 것은 칸 안의 그림**이다. 칸 자체를 떼어 옮기는 길은 없다.
 *
 *  ⚠️ 한계 값(격자 · 최소/최대 높이 · 칸 안에 남길 폭 · 경계선의 범위)은 서버가 상태의 `limits` 로 실어 보낸다
 *     (SSOT = utils/reference_inpaint_preprocess). 여기에 숫자를 복사하지 않는다.
 *  ⚠️ 끄는 동안 · 휠을 굴리는 동안은 **화면이 직접 그린다**(그림 한 장을 CSS 로 놓을 뿐이라 서버를 안 부른다).
 *     놓거나 휠이 멎으면 한 번만 보내고, 그 답(서버가 한계에 맞춘 값)으로 화면을 다시 맞춘다.
 *  ⚠️ 창은 캔버스를 **미리 보여 주는 것**이지 나가는 그림 자체가 아니다 - 칸 선은 화면에서 얇게만 긋는다.
 *
 *  상하 모드(사용자 지시 2026-10-18 - 머리줄의 [좌우 | 상하]): 칸이 **위**에 붙고 경계선은 가로줄이다. 서버는 원본을
 *    전치해 가로로 굽고 돌려 세운다 - 그래서 `box` · `divider` · `limits` · `source_*` 는 **눕힌 모델 공간** 값이고,
 *    `width` · `height` · `sizes` 만 실제(세로) 캔버스다. 위의 계산 함수들은 모델 공간에서 그대로 돌고(`geo()`),
 *    그리기와 포인터만 축을 바꾼다(모델 x = 화면 y). 방향은 세션 설정이다(앱을 다시 켜면 좌우).
 *
 *  그림 두 장(사용자 결정 2026-10-18 - "같은 인물을 두 장" · 두 장 상한 · 크롭 대신 칸 안 피벗): [+ 한 장 더] 로 둘째
 *    그림을 넣으면 칸이 모델 y 에서 두 칸으로 나뉜다(좌우 모드 = 위아래 칸 · 상하 모드 = 좌우 칸 · 기본 반반 · 사이 선을
 *    끌어 조절). 그림마다 제 칸 안에서만 보이고, 끌기 · 휠 · 손잡이는 **누른 칸의 그림**을 움직인다(휠은 커서 밑의 점이
 *    피벗). [그림 1] [그림 2] 칩이 [붙여넣기] · [Storage] · [저장] 이 어느 그림에 가는지 정한다. 업스케일은 첫 그림만.
 *  그릴 곳 = 마지막 결과(사용자 결정 2026-10-18 "결과물이 우측 윈도우에도"): 인셋으로 만든 결과가 오면 미리보기의 그릴
 *    곳에 얹는다([결과 보기] 로 끄고 켠다). 칸을 빼고 남긴 결과는 그 자리(오른쪽 · 아래)에 맞춰 놓는다.
 */
import {createDraggablePanel} from './draggablePanel.mjs?v=20260926-childalign';

/** 원본 비율에서 나오는 너비. 서버(`normalize_reference_inset_box`)와 같은 식이다. */
export function insetWidthFor(height, sourceWidth, sourceHeight) {
  return Math.max(1, Math.round(sourceWidth * (height / Math.max(1, sourceHeight))));
}

/** 경계선(칸의 너비)을 격자와 한계에 맞춘다. 기본 경계와 같은 값은 그대로 둔다(서버와 같은 규칙). */
export function clampInsetDivider(divider, state) {
  if (divider === state.default_divider) return divider;
  const limits = state.limits || {};
  const grid = Number(limits.grid) || 8;
  return Math.max(Number(limits.min_divider) || grid,
    Math.min(Number(limits.max_divider) || Number(state.width), Math.round(divider / grid) * grid));
}

/** 칸 안의 그림 자리 · 높이를 한계에 맞춘다(너비는 비율에서). 서버가 같은 일을 한 번 더 한다 - 여기는 끄는 동안의 화면용. */
export function clampInsetBox(box, divider, state) {
  const limits = state.limits || {};
  const grid = Number(limits.grid) || 8;
  const canvasH = Number(state.height) || 0;
  const height = Math.max(Number(limits.min_height) || grid,
    Math.min(Number(limits.max_height) || canvasH * 2, Math.round(box.height / grid) * grid));
  const width = insetWidthFor(height, state.source_width, state.source_height);
  const keep = Number(limits.min_visible) || 0;
  const x = Math.max(keep - width, Math.min(divider - keep, Math.round(box.x)));
  const y = Math.max(keep - height, Math.min(canvasH - keep, Math.round(box.y)));
  return {x, y, width, height};
}

/** 칸 안에서 실제로 보이는 그림 부분(캔버스 px). 없으면 null. */
export function visibleInsetRect(box, divider, canvasH) {
  const left = Math.max(0, box.x);
  const top = Math.max(0, box.y);
  const right = Math.min(divider, box.x + box.width);
  const bottom = Math.min(canvasH, box.y + box.height);
  if (right <= left || bottom <= top) return null;
  return {left, top, right, bottom};
}

/** 캔버스에서 칸이 안 덮은 넓이의 비율(0 ~ 1) - 모델이 그릴 수 있는 곳. 칸은 높이 전체라 너비만 본다. */
export function insetOpenRatio(divider, canvasW) {
  return 1 - Math.max(0, Math.min(canvasW, divider)) / Math.max(1, canvasW);
}

/** 그림의 손잡이를 끈다: 그림의 왼쪽 위는 제자리, 비율은 그대로. dx/dy = 캔버스 px. */
export function resizeInsetBox(box, dx, dy, divider, state) {
  const ratio = Math.max(1, state.source_height) / Math.max(1, state.source_width);
  // 가로로 끌든 세로로 끌든 따라오게 - 높이로 환산해 더 크게 움직인 쪽을 쓴다.
  const byX = dx * ratio;
  return clampInsetBox({x: box.x, y: box.y, height: box.height + (Math.abs(dy) >= Math.abs(byX) ? dy : byX)}, divider, state);
}

/** 휠의 닻: 캔버스의 한 점과, 그 점이 그림의 어디(0 ~ 1)에 있는지. 굴리는 동안 그 점 밑의 그림이 제자리에 남는다. */
export function insetZoomAnchor(box, point) {
  return {
    x: point.x, y: point.y,
    fx: (point.x - box.x) / Math.max(1, box.width), fy: (point.y - box.y) / Math.max(1, box.height),
  };
}

/** 휠: 닻을 붙잡고 한 칸 키우거나 줄인다. `direction` = +1(키우기) | -1(줄이기).
 *  이어 굴릴 때는 **처음에 잡은 닻**을 계속 넘긴다 - 칸마다 다시 재면 반올림이 한쪽으로 쌓인다. */
export function zoomInsetBox(box, direction, anchor, divider, state) {
  const grid = Number(state.limits?.grid) || 8;
  const step = Math.max(grid, Math.round(box.height * 0.06 / grid) * grid);
  const sized = clampInsetBox({x: box.x, y: box.y, height: box.height + direction * step}, divider, state);
  return clampInsetBox({
    x: anchor.x - anchor.fx * sized.width, y: anchor.y - anchor.fy * sized.height, height: sized.height,
  }, divider, state);
}

export function createReferenceInsetWindow({
  document: doc = (typeof document !== 'undefined' ? document : null),
  window: win = (typeof window !== 'undefined' ? window : null),
  fetch: fetchImpl = (typeof fetch !== 'undefined' ? fetch.bind(globalThis) : null),
  escHtml = value => String(value ?? '')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'),
  showToast = () => {},
  // 서버가 돌려준 새 인셋 상태를 받는다(배지가 같은 상태를 본다).
  onState = () => {},
  // [붙여넣기] 단추: 클립보드의 그림을 읽어 `acceptPastedImage(blob)` 로 넘겨 준다(읽는 일은 앱이 한다).
  requestPaste = null,
  // [Assets] 단추: Assets 탭을 연다(탭을 바꾸는 일은 앱이 한다).
  openAssets = null,
} = {}) {
  let panel = null;
  // 서버의 인셋 상태. 꽂아 둔 것이 없으면 `{configured: false}` - 그때도 창은 열려 있다.
  let state = null;
  let view = 'main';        // 'main'(배치) | 'storage'(저장해 둔 그림 목록)
  let stored = null;        // Storage 목록 {items, current} - 열 때마다 다시 받는다
  let storedSeq = 0;
  let armedDelete = '';     // x 를 한 번 누른 보관본의 id - 한 번 더 눌러야 지운다
  let armedTimer = 0;
  let draft = null;         // 끄는 중 · 보내는 중인 배치 {box, divider, box2, split} - 있으면 이것을 그린다
  let slot = 1;             // 고른 그림(1 | 2) - [붙여넣기] · [Storage] · [저장] 이 가는 곳
  let wantSecond = false;   // [+ 한 장 더] 를 눌렀고 둘째 그림이 아직 없다
  let lastResult = null;    // 인셋으로 만든 마지막 결과 {url, width, height} - 그릴 곳에 얹는다
  let resultSeq = 0;        // 결과를 풀어 볼 때마다 올라가는 번호 - 늦게 풀린 옛 결과가 새것을 덮지 않게
  // [특징 추출] 의 결과 {keep, unknown, dropped, on: Set(켜진 태그), url} - 가상 캐릭터에 넣기 전에 사람이 고른다.
  let extracted = null;
  let extracting = false;
  // 사용자가 닫은 '프롬프트 인식됨'(칸 · 그림 열쇠들) - 같은 그림이 다시 그려져도 되살리지 않는다(Codex 리뷰).
  let recognizedDismissed = new Set();
  // [배경 제거] - Anlas 가 든다. 한 번 누르면 '한 번 더' 로 바뀌고(3초), 그때 누르면 보낸다(Storage 지우기와 같은 방식).
  // [초기화] - 한 번 누르면 채워지고(3초) 한 번 더 누르면 비운다. 글자는 안 바꾼다(머리줄이 흔들리지 않게).
  let resetArmed = false;
  let resetTimer = 0;
  let removeBgArmed = false;
  let removeBgTimer = 0;
  let removingBg = false;
  let drag = null;
  let wheelTimer = 0;
  let wheelAnchor = null;   // 휠을 굴리기 시작한 순간의 닻 - 멎을 때까지 쥔다
  // 서버로 가는 요청은 **한 줄로 선다**(앞의 답이 온 뒤에 다음이 나간다). 그래서 답은 보낸 순서대로 오고, 마지막
  // 답이 곧 서버의 지금 상태다. ⚠️ 순번 하나로 '늦게 온 답은 버린다' 를 하지 말 것 - 길이 여럿이라(배치 · 붙여넣기 ·
  // 켜고 끄기 · 결과 자르기 · Storage) 붙여넣기가 가 있는 동안 체크 하나를 누르면, 서버를 바꾼 붙여넣기의 답이
  // 버려져 화면이 옛 그림 · 꺼짐에 남았다(Codex 리뷰 2026-10-10).
  // ⚠️ 줄을 세우면 답이 안 오는 요청 하나가 뒤의 것을 전부 막는다 - 그래서 (1) 기다리는 한계를 두고(`sendNow`),
  //    (2) **켜고 끄기는 줄을 서지 않는다**(끄려는 손이 긴 일 뒤에 묶이면 안 된다 - Codex 리뷰 2차). 줄 밖의 답과
  //    순서가 뒤바뀌어도 되는 까닭: 상태마다 서버가 차례 번호를 싣고, 앱이 옛 번호의 답을 버린다(app.js).
  let sendChain = Promise.resolve();
  const SEND_TIMEOUT_MS = 30000;        // 보통 요청(배치 · 그림 · 저장)
  const UPSCALE_TIMEOUT_MS = 200000;    // NAI 업스케일은 오래 걸린다
  let lastSend = Promise.resolve();   // 가는 중인 배치 전송 - 업스케일은 이것이 끝난 뒤에 건다
  let busy = false;                   // 업스케일을 기다리는 중 - 그동안만 배치를 못 바꾼다
  let el = null;

  const configured = () => !!state?.configured;
  // `send` 의 둘째 인자: 배치와 무관한 요청(켜고 끄기 · 결과 자르기 · 저장) - 답이 와도 끌어 놓은 배치를 안 지운다.
  const KEEP_DRAFT = Symbol('keep-draft');
  // 인셋을 켜는 요청(붙여넣기 · Storage 꺼내기)에 싣는, **누른 순간에** 화면이 알던 켜고 끄기 차례. 요청이 줄에서
  // 기다리거나 그림이 올라가는 동안 사용자가 끄면 서버가 이 값으로 알아보고 켜지 않는다(Codex 리뷰 3차).
  const toggleEpoch = () => (Number.isFinite(state?.toggle_epoch) ? state.toggle_epoch : null);
  // [붙여넣기] 를 **누른 순간**의 차례. 클립보드를 읽는 데도 시간이 걸린다(권한 창이 뜨기도 한다) - 그림을 받은
  // 뒤에 읽으면 그 사이에 끈 것을 놓친다(Codex 리뷰 4차). undefined = 누른 것이 없다.
  // 지금 칸에 놓인 그림 · 캔버스의 표식. 배치는 이것이 같을 때만 뜻이 있다(다른 그림 · 다른 캔버스의 좌표다).
  // 방향도 넣는다 - 정사각 캔버스는 방향을 바꿔도 치수가 같다(옛 방향의 좌표가 새 방향으로 나간다 - Codex 리뷰).
  const identity = () => (configured()
    ? [state.width, state.height, state.source_revision, state.character_id, state.variation, state.orientation,
      state.second?.source_revision || ''].join('|') : '');
  // 답을 못 받은 요청은 서버가 나중에 끝낼 수 있다 - 그때의 상태를 받아 오려고 몇 번 더 묻는다(ms 뒤).
  const FOLLOW_UP_MS = [2000, 5000, 15000, 30000, 60000];
  let followTimers = [];
  const layout = () => draft
    || {box: state.box, divider: state.divider, box2: state.second?.box || null, split: state.second ? state.split : null};
  // 상하 모드인가 · 계산 함수에 넘길 **모델 공간** 상태(세로면 캔버스의 너비 · 높이를 맞바꾼 것 - 머리 주석).
  const vertical = () => state?.orientation === 'vertical';
  const geo = () => (vertical() ? {...state, width: state.height, height: state.width} : state);
  // 그림 n 의 모델 공간 상태(둘째 그림이면 그 그림의 비율) · 그 그림의 칸(모델 y 범위).
  const geoOf = n => (n === 2 && state.second
    ? {...geo(), source_width: state.second.source_width, source_height: state.second.source_height} : geo());
  const cellOf = (n, lay) => {
    const whole = Number(geo().height) || 1;
    if (!lay.box2) return {top: 0, bottom: whole};
    return n === 2 ? {top: lay.split, bottom: whole} : {top: 0, bottom: lay.split};
  };
  /** 그림 n 의 자리를 한계와 **제 칸**에 맞춘다(그림의 min_visible 만큼은 칸 안에 남긴다 - 서버와 같은 규칙). */
  const clampCell = (box, divider, n, lay) => {
    const placed = clampInsetBox(box, divider, geoOf(n));
    const {top, bottom} = cellOf(n, lay);
    const keep = Number(state.limits?.min_visible) || 0;
    return {...placed, y: Math.max(top + keep - placed.height, Math.min(bottom - keep, placed.y))};
  };
  /** 그림 n 의 칸 안에서 보이는 부분(모델 px). */
  const cellSeen = (box, divider, n, lay) => {
    const {top, bottom} = cellOf(n, lay);
    const left = Math.max(0, box.x);
    const right = Math.min(divider, box.x + box.width);
    const upper = Math.max(top, box.y);
    const lower = Math.min(bottom, box.y + box.height);
    return right > left && lower > upper ? {left, top: upper, right, bottom: lower} : null;
  };
  // 업스케일을 기다리는 동안만 배치가 잠긴다. 업스케일해 둔 뒤에는 마음대로 바꾼다(원본을 올려 둔 것이라 유지된다).
  const locked = () => busy;

  function ensurePanel() {
    if (panel) return panel;
    panel = createDraggablePanel({
      document: doc, window: win, title: '레퍼런스 인셋', variant: 'riw', storageKey: 'reference-inset',
      // 접을 수 있다(2026-10-11) - 머리줄(이름 · 켜고 끄기)만 남겨 결과를 가리지 않게 둘 수 있다.
      width: 520, minWidth: 520, maxWidth: 520, collapsible: true, escHtml,
      // 닫을 때 끌어 놓고 아직 안 보낸 배치가 있으면 보낸다 - 휠을 굴리자마자 닫아도 화면에서 본 대로 나간다.
      onClose: () => { drag = null; win?.clearTimeout(wheelTimer); wheelAnchor = null; commit(); },
    });
    // 머리줄의 켜고 끄기. `data-nodrag` 가 없으면 스위치를 누르려다 창을 끈다.
    panel.slot.innerHTML = `
      <button type="button" class="riw-reset-btn" data-nodrag data-riw-reset-all
              data-naia-title="그림 · 배치 · 가상 캐릭터를 비우고 인셋을 끕니다 - 처음 화면으로 (두 번 눌러야 합니다 · 저장하지 않은 붙여넣은 그림은 사라집니다)">초기화</button>
      <span class="riw-orient" data-nodrag role="group" aria-label="칸의 방향">
        <button type="button" class="riw-orient-btn" data-riw-orient="horizontal"
                data-naia-title="칸이 왼쪽 · 그릴 곳이 오른쪽">좌우</button>
        <button type="button" class="riw-orient-btn" data-riw-orient="vertical"
                data-naia-title="칸이 위 · 그릴 곳이 아래 (캔버스를 세웁니다 - 배치는 기본으로 돌아갑니다)">상하</button>
      </span>
      <label class="riw-switch" data-nodrag data-riw-switch>
        <input type="checkbox" data-riw-enabled>
        <span class="riw-switch-text" data-riw-enabled-text>끔</span>
      </label>`;
    panel.body.innerHTML = `
      <div class="riw-main" data-riw-main>
        <div class="riw-stage" data-riw-stage>
          <img class="riw-result" data-riw-result alt="" draggable="false" hidden>
          <div class="riw-panel" data-riw-panel data-naia-title="끌어서 칸 안의 그림을 옮깁니다 · 휠로 크기를 바꿉니다">
            <div class="riw-cell" data-riw-cell="1"><img class="riw-pic" alt="레퍼런스 인셋 그림" draggable="false"></div>
            <div class="riw-cell" data-riw-cell="2" hidden><img class="riw-pic" data-riw-pic2 alt="둘째 그림"
                 draggable="false"></div>
            <div class="riw-split" data-riw-split hidden data-naia-title="끌어서 두 칸의 크기를 나눕니다"></div>
          </div>
          <div class="riw-frame" data-riw-frame>
            <span class="riw-handle" data-riw-handle data-naia-title="끌어서 그림의 크기를 바꿉니다"></span>
          </div>
          <div class="riw-divider" data-riw-divider data-naia-title="좌우로 끌어 인셋 칸의 너비를 정합니다"></div>
        </div>
        <div class="riw-empty" data-riw-empty hidden>
          <div class="riw-empty-text">레퍼런스로 쓸 그림을 넣어 주세요</div>
          <div class="riw-row riw-row-center">
            <button type="button" class="riw-chip" data-riw-paste
                    data-naia-title="클립보드의 그림(캡쳐 · 복사한 것)을 레퍼런스로 씁니다">붙여넣기</button>
            <button type="button" class="riw-chip" data-riw-storage
                    data-naia-title="저장해 둔 그림에서 고릅니다">Storage</button>
            <button type="button" class="riw-chip" data-riw-assets
                    data-naia-title="Assets 탭을 엽니다 - 캐릭터를 고르고 [C1 + 레퍼런스 인셋 적용] 을 누릅니다">Assets</button>
          </div>
          <div class="riw-empty-hint">에셋의 그림은 Assets 탭의 [C1+레퍼런스 인셋] 으로 꽂습니다</div>
        </div>
        <div class="riw-row" data-riw-row>
          <span class="riw-sizes" data-riw-slots></span>
          <button type="button" class="riw-chip" data-riw-paste
                  data-naia-title="클립보드의 그림(캡쳐 · 복사한 것)으로 인셋 칸의 그림을 바꿉니다">붙여넣기</button>
          <button type="button" class="riw-chip" data-riw-save
                  data-naia-title="지금 칸의 그림을 Storage 에 넣어 둡니다 - 앱을 다시 켜도 꺼내 쓸 수 있습니다 (그림만 기억합니다 · 업스케일해 뒀으면 올려 둔 판을 넣습니다)">저장</button>
          <button type="button" class="riw-chip" data-riw-storage
                  data-naia-title="저장해 둔 그림에서 고릅니다">Storage</button>
          <button type="button" class="riw-chip" data-riw-extract-run
                  data-naia-title="고른 그림을 WD 태거(huggingface - 그림이 외부로 나갑니다)에 보내 캐릭터 특징만 뽑습니다 - 확인한 뒤 가상 캐릭터에 넣습니다">특징 추출</button>
          <button type="button" class="riw-chip riw-chip-paid" data-riw-remove-bg
                  data-naia-title="고른 그림의 배경을 NovelAI Remove BG 로 지웁니다 - 배치는 그대로 · Anlas 를 소모합니다 (두 번 눌러야 보냅니다 · 지운 그림은 Storage 에 저장됩니다)">배경 제거 (유료)</button>
          <button type="button" class="riw-chip" data-riw-upscale
                  data-naia-title="레퍼런스 원본을 NAI 업스케일에 한 번 보내 두고, 그 뒤로는 거기서 줄여 칸에 놓습니다 - 그림을 키워도 흐려지지 않습니다 (Anlas 가 듭니다 · 그림 하나에 한 번)">업스케일</button>
          <button type="button" class="riw-chip" data-riw-bg
                  data-naia-title="칸의 바탕색을 흰색 · 회색 · 검정 순서로 바꿉니다 - 투명한 그림의 뒤와 그림이 덮지 않은 자리가 이 색으로 나갑니다"></button>
          <span class="riw-note" data-riw-note></span>
        </div>
        <div class="riw-row" data-riw-row>
          <span class="riw-label">캔버스</span>
          <span class="riw-sizes" data-riw-kinds></span>
          <button type="button" class="riw-chip" data-riw-reset
                  data-naia-title="예전 배치로 돌아갑니다 (그림을 높이에 꽉 채우고, 그림의 끝이 경계)">기본값</button>
          <span class="riw-read" data-riw-read></span>
        </div>
        <div class="riw-row" data-riw-row>
          <span class="riw-label">해상도</span>
          <span class="riw-sizes" data-riw-sizes></span>
        </div>
        <div class="riw-row" data-riw-row>
          <span class="riw-label">결과</span>
          <label class="riw-check" data-naia-title="생성된 그림에서 인셋 칸을 잘라 내고 그린 부분만 남깁니다 (NAI 메타데이터는 남습니다)">
            <input type="checkbox" data-riw-crop> 인셋 칸을 빼고 남기기</label>
          <label class="riw-check riw-check-paid" data-riw-auto-upscale-box hidden
                 data-naia-title="칸을 빼고 남긴 결과를 NovelAI 업스케일에 보낸 뒤 1MP 로 줄여 히스토리에 넣습니다 - 생성마다 Anlas 를 소모합니다 (메타데이터는 남습니다)">
            <input type="checkbox" data-riw-auto-upscale> 생성 후 자동 업스케일 (유료)</label>
          <span class="riw-cost" data-riw-cost
                data-naia-title="이 캔버스(1MP 를 넘는 해상도)로 생성하면 Anlas 를 소모합니다"></span>
        </div>
        <div class="riw-extract" data-riw-extract hidden>
          <div class="riw-row">
            <span class="riw-label" data-riw-extract-label>추출된 특징</span>
            <span class="riw-extract-src" data-riw-extract-src></span>
            <span class="riw-extract-modes" data-riw-extract-modes>
              <button type="button" class="riw-chip" data-riw-extract-mode="features">특징만</button>
              <button type="button" class="riw-chip" data-riw-extract-mode="both">특징+의상</button>
              <button type="button" class="riw-chip" data-riw-extract-mode="clothes">의상만</button>
            </span>
          </div>
          <div class="riw-extract-edit">
            <div class="riw-extract-hl" data-riw-extract-hl aria-hidden="true"></div>
            <textarea class="riw-extract-text" data-riw-extract-text spellcheck="false" rows="3"
                      aria-label="가상 캐릭터에 넣을 프롬프트"></textarea>
          </div>
          <div class="riw-read riw-extract-legend">흰색 = 특징 · 연노랑 = 의상 · 회색 = 직접 쓴 것</div>
          <div class="riw-row">
            <button type="button" class="riw-chip is-on" data-riw-extract-c1
                    data-naia-title="이 프롬프트를 가상 C1 에 넣습니다 (C1 을 덮습니다)">가상 C1 에 넣기</button>
            <button type="button" class="riw-chip" data-riw-extract-add
                    data-naia-title="이 프롬프트를 새 가상 캐릭터로 넣습니다">가상 캐릭터로 추가</button>
            <button type="button" class="riw-chip" data-riw-extract-close>닫기</button>
          </div>
        </div>
        <div class="riw-row" data-riw-row>
          <span class="riw-label">그릴 곳</span>
          <label class="riw-check" data-naia-title="인셋으로 만든 마지막 결과를 미리보기의 그릴 곳에 얹어 보여 줍니다">
            <input type="checkbox" data-riw-show-result checked> 결과 보기</label>
          <span class="riw-read" data-riw-result-note></span>
        </div>
      </div>
      <div class="riw-store" data-riw-store hidden>
        <div class="riw-row">
          <button type="button" class="riw-chip" data-riw-back>&#8592; 돌아가기</button>
          <span class="riw-label" data-riw-store-count></span>
          <span class="riw-read">누르면 칸에 놓습니다 · 배치는 기본으로 놓입니다</span>
          <button type="button" class="riw-link" data-riw-store-folder
                  data-naia-title="Storage 의 그림이 저장된 폴더를 엽니다">폴더 열기</button>
        </div>
        <div class="riw-store-grid" data-riw-store-grid></div>
      </div>`;
    const find = selector => panel.body.querySelector(selector);
    el = {
      main: find('[data-riw-main]'),
      stage: find('[data-riw-stage]'),
      empty: find('[data-riw-empty]'),
      rows: [...panel.body.querySelectorAll('[data-riw-row]')],
      panel: find('[data-riw-panel]'),
      pic: find('.riw-pic'),
      pic2: find('[data-riw-pic2]'),
      cell1: find('[data-riw-cell="1"]'),
      cell2: find('[data-riw-cell="2"]'),
      split: find('[data-riw-split]'),
      slots: find('[data-riw-slots]'),
      result: find('[data-riw-result]'),
      showResult: find('[data-riw-show-result]'),
      extractRun: find('[data-riw-extract-run]'),
      removeBg: find('[data-riw-remove-bg]'),
      extract: find('[data-riw-extract]'),
      extractText: find('[data-riw-extract-text]'),
      extractHl: find('[data-riw-extract-hl]'),
      extractModes: find('[data-riw-extract-modes]'),
      extractSrc: find('[data-riw-extract-src]'),
      extractLabel: find('[data-riw-extract-label]'),
      autoUpscale: find('[data-riw-auto-upscale]'),
      autoUpscaleBox: find('[data-riw-auto-upscale-box]'),
      resultNote: find('[data-riw-result-note]'),
      frame: find('[data-riw-frame]'),
      divider: find('[data-riw-divider]'),
      kinds: find('[data-riw-kinds]'),
      sizes: find('[data-riw-sizes]'),
      cost: find('[data-riw-cost]'),
      reset: find('[data-riw-reset]'),
      read: find('[data-riw-read]'),
      upscale: find('[data-riw-upscale]'),
      bg: find('[data-riw-bg]'),
      pastes: [...panel.body.querySelectorAll('[data-riw-paste]')],
      storages: [...panel.body.querySelectorAll('[data-riw-storage]')],
      assets: [...panel.body.querySelectorAll('[data-riw-assets]')],
      save: find('[data-riw-save]'),
      crop: find('[data-riw-crop]'),
      note: find('[data-riw-note]'),
      enabled: panel.slot.querySelector('[data-riw-enabled]'),
      enabledText: panel.slot.querySelector('[data-riw-enabled-text]'),
      switchBox: panel.slot.querySelector('[data-riw-switch]'),
      orients: [...panel.slot.querySelectorAll('[data-riw-orient]')],
      resetAll: panel.slot.querySelector('[data-riw-reset-all]'),
      store: find('[data-riw-store]'),
      storeGrid: find('[data-riw-store-grid]'),
      storeCount: find('[data-riw-store-count]'),
      back: find('[data-riw-back]'),
    };
    el.stage.addEventListener('pointerdown', onPointerDown);
    el.stage.addEventListener('pointermove', onPointerMove);
    el.stage.addEventListener('pointerup', onPointerUp);
    el.stage.addEventListener('pointercancel', onPointerUp);
    el.stage.addEventListener('wheel', onWheel, {passive: false});
    el.sizes.addEventListener('click', onPickSize);
    el.slots.addEventListener('click', onPickSlot);
    el.showResult.addEventListener('change', () => { render(); });
    el.extractRun.addEventListener('click', runExtract);
    el.resetAll.addEventListener('click', runResetAll);
    el.removeBg.addEventListener('click', runRemoveBg);
    el.extractModes.addEventListener('click', event => {
      const pick = event.target.closest('[data-riw-extract-mode]');
      if (!pick || !extracted) return;
      setExtractMode(pick.dataset.riwExtractMode);
    });
    el.extractText.addEventListener('input', () => {
      if (!extracted) return;
      extracted.text = el.extractText.value;
      extracted.edited = true;             // 손으로 고쳤다 - 앞선 [넣기] 의 늦은 답이 이 칸을 닫지 않는다(Codex 리뷰)
      paintExtract();
    });
    el.extractText.addEventListener('scroll', () => { el.extractHl.scrollTop = el.extractText.scrollTop; });
    el.autoUpscale.addEventListener('change', () => {
      send({enabled: el.autoUpscale.checked}, KEEP_DRAFT, '/api/character-asset/inset/auto-upscale').then(data => {
        if (data) showToast(data.auto_upscale ? '생성 후 자동 업스케일을 켰습니다 - 생성마다 Anlas 를 소모합니다'
          : '생성 후 자동 업스케일을 껐습니다', data.auto_upscale ? 'info' : 'success');
      });
    });
    find('[data-riw-extract-c1]').addEventListener('click', () => useExtracted('virtual_c1'));
    find('[data-riw-extract-add]').addEventListener('click', () => useExtracted('add_character'));
    find('[data-riw-extract-close]').addEventListener('click', () => {
      if (extracted?.key) recognizedDismissed.add(extracted.key);
      extracted = null;
      renderExtract();
    });
    el.kinds.addEventListener('click', onPickKind);
    el.reset.addEventListener('click', () => { if (!locked()) send({reset: true}, null); });
    el.upscale.addEventListener('click', runUpscale);
    el.pastes.forEach(button => button.addEventListener('click', () => {
      if (locked()) return;
      // 누른 순간의 차례 · 고른 그림을 **이 요청에만** 묶어 넘긴다 - 클립보드를 읽는 사이에 칩을 바꾸거나 한 번 더 눌러도
      // 각 붙여넣기는 제가 눌린 그림으로 간다(Codex 리뷰 - 공용 변수 하나로 쥐면 두 번째 누름이 첫 번째를 덮었다).
      const pressed = {epoch: toggleEpoch(), slot};
      if (typeof requestPaste === 'function') requestPaste(pressed);
      else showToast('이 화면에서는 붙여넣기를 쓸 수 없습니다', 'error');
    }));
    el.storages.forEach(button => button.addEventListener('click', () => { if (!locked()) showStorage(); }));
    el.assets.forEach(button => button.addEventListener('click', () => {
      if (typeof openAssets === 'function') openAssets();
      else showToast('이 화면에서는 Assets 탭을 열 수 없습니다', 'error');
    }));
    el.back.addEventListener('click', () => showMain());
    // 칸의 방향. 꽂아 둔 것이 없어도 정해 둔다(다음에 꽂는 그림이 그 방향으로 선다).
    el.orients.forEach(button => button.addEventListener('click', () => {
      const wanted = button.dataset.riwOrient;
      if (locked() || wanted === (state?.orientation || 'horizontal')) return;
      win?.clearTimeout(wheelTimer);
      wheelAnchor = null;
      draft = null;
      send({orientation: wanted}, null, '/api/character-asset/inset/orientation');
    }));
    // [폴더 열기](사용자 지시 2026-10-12) - Storage 의 그림이 저장된 폴더를 탐색기로 연다.
    find('[data-riw-store-folder]').addEventListener('click', async () => {
      try {
        const response = await fetchImpl('/api/character-asset/open-folder', {
          method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({target: 'storage'}),
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
      } catch (error) {
        showToast(`폴더를 열지 못했습니다: ${error.message}`, 'error');
      }
    });
    el.storeGrid.addEventListener('click', onStoreClick);
    el.save.addEventListener('click', saveToStorage);
    el.enabled.addEventListener('change', () => {
      const wanted = el.enabled.checked;
      // 줄을 서지 않고 바로 보낸다(위 `sendChain` 의 주석) - 업스케일 · 붙여넣기가 가 있는 동안에도 끌 수 있다.
      sendNow({enabled: wanted}, KEEP_DRAFT, '/api/character-asset/inset/enabled').then(data => {
        if (!data) return;
        if (data.references_disabled) showToast('레퍼런스 인셋을 켰습니다 - Character Reference 는 껐습니다', 'success');
        else showToast(wanted ? '레퍼런스 인셋을 켰습니다' : '레퍼런스 인셋을 껐습니다 - 그림과 배치는 남아 있습니다', 'success');
      });
    });
    // 칸의 바탕색: 흰색 <-> 검정(사용자 결정 2026-10-11). 이 세션의 설정이라 그림을 바꿔 꽂아도 남는다.
    el.bg.addEventListener('click', () => {
      if (locked()) return;
      // 흰색 -> 회색 -> 검정 -> 흰색(회색 - 사용자 지시 2026-10-18).
      const next = {white: 'gray', gray: 'black', black: 'white'}[state?.background] || 'gray';
      send({color: next}, KEEP_DRAFT, '/api/character-asset/inset/background');
    });
    el.crop.addEventListener('change', () => {
      send({enabled: el.crop.checked}, KEEP_DRAFT, '/api/character-asset/inset/crop');
    });
    return panel;
  }

  // ── 그리기 ────────────────────────────────────────────────────────────
  function render() {
    if (!panel || !state) return;
    showRecognized();          // 고른 그림이 바뀌는 길이 여럿이다 - 그릴 때마다 그 그림의 인식 칸으로(Codex 리뷰)
    const ready = configured();
    const on = ready && !!state.active;
    el.main.hidden = view !== 'main';
    el.store.hidden = view !== 'storage';
    // 켜고 끄기: 꽂아 둔 것이 있어야 켤 수 있다.
    el.enabled.checked = on;
    el.enabled.disabled = !ready;                            // 업스케일을 기다리는 중에도 끌 수 있다
    el.enabledText.textContent = on ? '켬' : '끔';
    el.switchBox.classList.toggle('is-on', on);
    el.switchBox.dataset.naiaTitle = !ready ? '그림을 넣으면 켤 수 있습니다'
      : on ? '켜져 있습니다 - 다음 생성이 인셋으로 나갑니다 (끄면 일반 생성 · 그림과 배치는 남습니다)'
        : '꺼져 있습니다 - 일반 생성으로 나갑니다 (켜면 이 그림 · 배치 그대로 이어집니다)';
    el.crop.checked = !!state.crop_result;
    // 자동 업스케일은 칸을 빼고 남길 때만 뜻이 있다(자른 결과에 건다) - 그때만 보인다.
    el.autoUpscaleBox.hidden = !state.crop_result;
    el.autoUpscale.checked = !!state.auto_upscale;
    // 머리줄의 방향 - 아래의 일찍 돌아가는 길(Storage · 빈 상태)보다 먼저 맞춘다.
    const vert = vertical();
    el.orients.forEach(button => {
      const on = button.dataset.riwOrient === (vert ? 'vertical' : 'horizontal');
      button.classList.toggle('is-on', on);
      button.setAttribute('aria-pressed', on ? 'true' : 'false');
      button.disabled = locked();
    });
    if (!state.second && !wantSecond) slot = 1;
    el.resetAll.disabled = locked() || (!configured() && !(state.characters || []).length);
    el.resetAll.classList.toggle('is-armed', resetArmed);
    if (view === 'storage') { renderStorage(); renderExtract(); return; }
    el.stage.hidden = !ready;
    el.empty.hidden = ready;
    el.rows.forEach(row => { row.hidden = !ready; });
    // 처음 화면 · Storage 에서도 추출 칸을 다시 따진다 - 안 하면 [초기화] 뒤에도 앞 그림의 특징이 남아 보인다.
    if (!ready) { el.pic.removeAttribute('src'); renderExtract(); return; }
    el.stage.classList.toggle('is-off', !on);
    const canvasW = Number(state.width) || 1;
    const canvasH = Number(state.height) || 1;
    const lay = layout();
    const {box, divider} = lay;
    const modelW = vert ? canvasH : canvasW;       // 모델 공간(칸이 왼쪽인 눕힌 캔버스)
    const modelH = vert ? canvasW : canvasH;
    el.stage.style.aspectRatio = `${canvasW} / ${canvasH}`;
    el.stage.classList.toggle('is-vertical', vert);
    // 칸에 놓인 그림 = 붙여넣은 그림이면 그것, 아니면 에셋의 그림. 주소의 `v` 가 그림이 바뀔 때마다 달라진다
    // (캐릭터 · 바리에이션 · 붙여넣은 그림의 지문) - 캐시가 옛 그림을 주지 않게.
    const src = '/api/character-asset/inset/source?v=' + encodeURIComponent(
      `${state.character_id || ''}-${state.variation || ''}-${state.source_revision || ''}`);
    if (el.pic.getAttribute('src') !== src) el.pic.setAttribute('src', src);
    const pct = (value, whole) => `${(value / whole) * 100}%`;
    // 칸 = 왼쪽 가장자리 ~ 경계선. 그림은 칸이 자른다(칸 기준 % 로 놓는다).
    // 상하 모드는 같은 모델 값을 **축을 바꿔** 놓는다(모델 x · 너비 -> 화면 y · 높이).
    el.panel.style.width = vert ? '100%' : pct(divider, canvasW);
    el.panel.style.height = vert ? pct(divider, modelW) : '';
    // 칸 하나에 그림 하나. 둘째 그림이 없으면 첫 칸이 칸 전체다(예전과 같은 자리).
    const placeCell = (cellEl, picEl, picBox, n) => {
      const {top, bottom} = cellOf(n, lay);
      const span = Math.max(1, bottom - top);
      cellEl.style.left = vert ? pct(top, modelH) : '0';
      cellEl.style.top = vert ? '0' : pct(top, modelH);
      cellEl.style.width = vert ? pct(span, modelH) : '100%';
      cellEl.style.height = vert ? '100%' : pct(span, modelH);
      picEl.style.left = vert ? pct(picBox.y - top, span) : pct(picBox.x, divider);
      picEl.style.top = vert ? pct(picBox.x, divider) : pct(picBox.y - top, span);
      picEl.style.width = vert ? pct(picBox.height, span) : pct(picBox.width, divider);
      picEl.style.height = vert ? pct(picBox.width, divider) : pct(picBox.height, span);
    };
    placeCell(el.cell1, el.pic, box, 1);
    const two = !!lay.box2 && !!state.second;
    el.cell2.hidden = !two;
    el.split.hidden = !two;
    if (two) {
      const src2 = '/api/character-asset/inset/source?slot=2&v=' + encodeURIComponent(state.second.source_revision || '');
      if (el.pic2.getAttribute('src') !== src2) el.pic2.setAttribute('src', src2);
      placeCell(el.cell2, el.pic2, lay.box2, 2);
      el.split.style.left = vert ? pct(lay.split, modelH) : '';
      el.split.style.top = vert ? '' : pct(lay.split, modelH);
      el.split.dataset.naiaTitle = vert ? '좌우로 끌어 두 칸의 너비를 나눕니다' : '위아래로 끌어 두 칸의 높이를 나눕니다';
    } else {
      el.pic2.removeAttribute('src');
    }
    el.divider.style.left = vert ? '' : pct(divider, canvasW);
    el.divider.style.top = vert ? pct(divider, modelW) : '';
    el.divider.dataset.naiaTitle = vert ? '위아래로 끌어 인셋 칸의 높이를 정합니다' : '좌우로 끌어 인셋 칸의 너비를 정합니다';
    // 테두리 · 손잡이는 그림의 **칸 안에 보이는 부분**에 붙는다 - 잘려 나간 모서리는 잡을 수 없다.
    // 고른 그림의 테두리 · 손잡이만 보인다(두 장이면 [그림 1] · [그림 2] 칩 · 누른 칸이 정한다).
    const picked = two && slot === 2 ? 2 : 1;
    const seen = cellSeen(picked === 2 ? lay.box2 : box, divider, picked, lay);
    el.frame.hidden = !seen;
    if (seen) {
      el.frame.style.left = vert ? pct(seen.top, modelH) : pct(seen.left, canvasW);
      el.frame.style.top = vert ? pct(seen.left, modelW) : pct(seen.top, canvasH);
      el.frame.style.width = vert ? pct(seen.bottom - seen.top, modelH) : pct(seen.right - seen.left, canvasW);
      el.frame.style.height = vert ? pct(seen.right - seen.left, modelW) : pct(seen.bottom - seen.top, canvasH);
    }
    // 업스케일을 기다리는 동안: 끌 것(경계선 · 테두리)을 감춘다.
    const lock = locked();
    el.stage.classList.toggle('is-locked', lock);
    // 캔버스: 비율(종류)을 고르고 → 그 비율의 크기를 고른다. 묶음 · 금액은 서버가 실어 보낸다.
    const current = `${canvasW}x${canvasH}`;
    const groups = sizeGroups();
    const at = kindIndex(groups, current);
    const costs = state.canvas_costs || {};
    const kinds = groups.length > 1 ? groups.map((group, index) => `<button type="button"
        class="riw-chip${index === at ? ' is-on' : ''}" data-riw-kind="${index}"
        aria-pressed="${index === at ? 'true' : 'false'}"${lock ? ' disabled' : ''}>${escHtml(group.label)}</button>`).join('') : '';
    if (el.kinds.innerHTML !== kinds) el.kinds.innerHTML = kinds;
    const chips = (groups[at]?.sizes || []).map(pair => {
      const label = sizeLabel(pair);
      const price = Number(costs[label]) || 0;
      return `<button type="button" class="riw-chip${label === current ? ' is-on' : ''}" data-riw-size="${label}"
              aria-pressed="${label === current ? 'true' : 'false'}"${lock ? ' disabled' : ''}${price > 0
                ? ' data-naia-title="1MP 를 넘는 해상도입니다 - 생성할 때 Anlas 를 소모합니다"' : ''}>${label}${
                price > 0 ? '<span class="riw-chip-cost"> · Anlas 소모</span>' : ''}</button>`;
    }).join('');
    if (el.sizes.innerHTML !== chips) el.sizes.innerHTML = chips;
    const price = Number(costs[current]) || 0;
    // 꺼져 있으면 이 캔버스로 나가지 않는다 - '켜면' 을 붙여 지금 나가는 금액처럼 읽히지 않게 한다.
    // ⚠️ **소모량을 숫자로 적지 않는다**(사용자 지정 2026-10-10: "Anlas 소모량은 불명확하니 모두 'Anlas 소모' 로 대체").
    //    서버의 추정치(`canvas_costs`)는 '드는가 아닌가' 로만 쓴다 - 인셋 인페인트의 실제 청구는 그 식과 다를 수 있다.
    el.cost.textContent = price > 0 ? (on ? 'Anlas 소모' : '켜면 Anlas 소모') : '';
    el.reset.disabled = lock || (!draft && !state.custom);
    el.upscale.disabled = lock || !!state.upscaled;          // 그림 하나에 한 번이면 된다
    // 미리보기의 칸도 **나가는 캔버스와 같은 바탕**을 깐다. 예전에는 미리보기는 희고 나가는 것은 검었다.
    const tone = {black: ['바탕 검정', '#000000'], gray: ['바탕 회색', '#d0d0d0']}[state.background] || ['바탕 흰색', '#ffffff'];
    el.bg.textContent = tone[0];
    el.bg.disabled = lock;
    el.panel.style.background = tone[1];
    el.upscale.textContent = busy ? '업스케일 중…' : state.upscaled ? '업스케일됨' : '업스케일';
    el.pastes.forEach(button => { button.disabled = lock; });
    el.storages.forEach(button => { button.disabled = lock; });
    const onSecond = slot === 2;
    const savedNow = onSecond ? !!state.second?.saved : !!state.saved;
    el.save.disabled = lock || savedNow || (onSecond && !state.second);   // 이미 Storage 에 있는 그림이다
    el.save.textContent = savedNow ? '저장됨' : '저장';
    el.upscale.disabled = el.upscale.disabled || onSecond;   // 업스케일은 첫 그림만
    // 그림이 어디서 왔고, 앱을 끄면 남는가.
    const origin = onSecond ? (!state.second ? '둘째 그림을 넣어 주세요 (붙여넣기 · Storage)'
      : state.second.saved ? '둘째 그림 · Storage 의 그림' : '둘째 그림 · 저장 안 됨')
      : state.saved ? 'Storage 의 그림' : state.standalone ? '붙여넣은 그림 · 저장 안 됨'
        : state.overridden ? '붙여넣은 그림 · 저장 안 됨' : '에셋의 그림';
    el.note.textContent = busy ? 'NAI 업스케일을 기다리는 중…'
      : [on ? '' : '꺼져 있음', origin, state.upscaled ? '업스케일해 둠' : ''].filter(Boolean).join(' · ');
    el.read.textContent = `칸 ${divider}px · 그릴 곳 ${Math.round(insetOpenRatio(divider, modelW) * 100)}%`;
    renderSlots(two, lock);
    renderResult(canvasW, canvasH);
    el.extractRun.disabled = lock || extracting || (slot === 2 && !state.second);
    // 이미 지운 판이면 그림이 바뀔 때까지 다시 내지 않는다(사용자 지시 2026-10-18).
    // ⚠️ 누르기 확인(armed)은 **글을 바꾸지 않는다** - 글이 길어지면 줄이 넘쳐 아래 칸이 밀렸다(사용자 제보). 색과 토스트로만.
    const removedNow = slot === 2 ? !!state.second?.bg_removed : !!state.bg_removed;
    el.removeBg.disabled = lock || removingBg || removedNow || (slot === 2 && !state.second);
    el.removeBg.classList.toggle('is-armed', removeBgArmed && !removedNow);
    el.removeBg.textContent = removingBg ? '배경 제거 중…' : removedNow ? '배경 제거됨' : '배경 제거 (유료)';
    el.extractRun.textContent = extracting ? '특징 추출 중…' : '특징 추출';
    renderExtract();
  }

  // ── 끌기 ──────────────────────────────────────────────────────────────
  function canvasScale() {
    const rect = el.stage.getBoundingClientRect();
    return rect.width > 0 ? (Number(state.width) || 1) / rect.width : 1;
  }

  /** 포인터 자리(모델 공간 캔버스 px). 상하 모드면 화면의 y 가 모델의 x 다. */
  function canvasPoint(event) {
    const rect = el.stage.getBoundingClientRect();
    const scale = canvasScale();
    const x = (event.clientX - rect.left) * scale;
    const y = (event.clientY - rect.top) * scale;
    return vertical() ? {x: y, y: x} : {x, y};
  }

  function onPointerDown(event) {
    if (!configured() || locked() || event.button !== 0) return;
    // 경계선 → 칸의 너비 · 손잡이 → 그림 크기 · 칸 안 → 그림 옮기기. 경계선 오른쪽(그릴 곳)은 아무것도 아니다.
    const kind = event.target.closest?.('[data-riw-divider]') ? 'divider'
      : event.target.closest?.('[data-riw-handle]') ? 'size'
      : event.target.closest?.('[data-riw-split]') ? 'split'
      : event.target.closest?.('[data-riw-panel]') ? 'pan' : '';
    if (!kind) return;
    // 두 장이면 누른 칸의 그림을 고른다(손잡이는 지금 고른 그림의 것이다).
    if (kind === 'pan') slot = slotAt(canvasPoint(event));
    event.preventDefault();
    win?.clearTimeout(wheelTimer);
    wheelAnchor = null;
    // 끄는 내내 **누른 순간의 배치**에서 잰다 - 답이 늦게 와 상태가 바뀌어도 손 밑의 그림이 튀지 않는다.
    const from = layout();
    // `made` = 누른 순간의 그림 · 캔버스. 끄는 동안 그것이 바뀌면(붙여넣기의 답이 왔다) 놓을 때 이 배치를 버린다 -
    // 옛 그림의 좌표를 새 그림에 보내지 않는다(Codex 리뷰 5차).
    drag = {kind, startX: event.clientX, startY: event.clientY, box: {...from.box}, divider: from.divider,
      box2: from.box2 ? {...from.box2} : null, split: from.split, slot: from.box2 ? slot : 1,
      moved: false, made: identity()};
    render();
    try { el.stage.setPointerCapture(event.pointerId); } catch (_error) { /* 못 잡아도 끌린다 */ }
    el.stage.classList.add('is-dragging');
  }

  function onPointerMove(event) {
    if (!drag || !configured()) return;
    if (!drag.moved && Math.hypot(event.clientX - drag.startX, event.clientY - drag.startY) < 3) return;
    drag.moved = true;
    const scale = canvasScale();
    const screenX = (event.clientX - drag.startX) * scale;
    const screenY = (event.clientY - drag.startY) * scale;
    // 모델 공간의 움직임 - 상하 모드면 축이 바뀐다(위아래로 끌면 경계선이 움직인다).
    const [dx, dy] = vertical() ? [screenY, screenX] : [screenX, screenY];
    const model = geo();
    if (drag.box2) {
      onTwoPictureMove(dx, dy);
    } else if (drag.kind === 'divider') {
      const divider = clampInsetDivider(drag.divider + dx, model);
      // 경계선이 그림을 지나쳐 좁아지면 그림을 칸 안으로 데려온다(그림을 잃어버리지 않게).
      draft = {divider, box: clampInsetBox(drag.box, divider, model)};
    } else if (drag.kind === 'size') {
      draft = {divider: drag.divider, box: resizeInsetBox(drag.box, dx, dy, drag.divider, model)};
    } else {
      draft = {divider: drag.divider,
        box: clampInsetBox({x: drag.box.x + dx, y: drag.box.y + dy, height: drag.box.height}, drag.divider, model)};
    }
    render();
  }

  /** 두 장일 때의 끌기: 경계선(두 그림 모두 맞춘다) · 사이 선 · 고른 그림의 손잡이 · 누른 칸의 그림. */
  function onTwoPictureMove(dx, dy) {
    const base = {box: drag.box, box2: drag.box2, divider: drag.divider, split: drag.split};
    if (drag.kind === 'divider') {
      const divider = clampInsetDivider(drag.divider + dx, geo());
      const lay = {...base, divider};
      draft = {...lay, box: clampCell(drag.box, divider, 1, lay), box2: clampCell(drag.box2, divider, 2, lay)};
      return;
    }
    if (drag.kind === 'split') {
      const limits = state.split_limits || {};
      const grid = Number(state.limits?.grid) || 8;
      const split = Math.max(Number(limits.min_split) || grid, Math.min(Number(limits.max_split) || drag.split,
        Math.round((drag.split + dy) / grid) * grid));
      const lay = {...base, split};
      draft = {...lay, box: clampCell(drag.box, drag.divider, 1, lay), box2: clampCell(drag.box2, drag.divider, 2, lay)};
      return;
    }
    const n = drag.slot;
    const from = n === 2 ? drag.box2 : drag.box;
    const moved = drag.kind === 'size'
      ? clampCell(resizeInsetBox(from, dx, dy, drag.divider, geoOf(n)), drag.divider, n, base)
      : clampCell({x: from.x + dx, y: from.y + dy, height: from.height}, drag.divider, n, base);
    draft = {...base, [n === 2 ? 'box2' : 'box']: moved};
  }

  function onPointerUp() {
    if (!drag) return;
    const moved = drag.moved;
    const made = drag.made;
    drag = null;
    el.stage.classList.remove('is-dragging');
    if (made !== identity()) {
      draft = null;                        // 끄는 동안 그림 · 캔버스가 바뀌었다 - 이 배치는 옛것의 좌표다
      render();
      return;
    }
    if (moved && draft) commit();
  }

  function onWheel(event) {
    if (!configured() || drag) return;
    event.preventDefault();
    if (locked()) return;
    const from = layout();
    if (from.box2) { onTwoPictureWheel(event, from); return; }
    if (!wheelAnchor) {
      // 포인터가 칸 안의 그림 위면 그 점을, 아니면 보이는 그림의 가운데를 붙잡는다.
      const point = canvasPoint(event);
      const seen = visibleInsetRect(from.box, from.divider, Number(geo().height) || 0);
      const inside = seen && point.x >= seen.left && point.x <= seen.right && point.y >= seen.top && point.y <= seen.bottom;
      const held = inside || !seen ? point : {x: (seen.left + seen.right) / 2, y: (seen.top + seen.bottom) / 2};
      wheelAnchor = insetZoomAnchor(from.box, held);
    }
    draft = {divider: from.divider, box: zoomInsetBox(from.box, event.deltaY < 0 ? 1 : -1, wheelAnchor, from.divider, geo())};
    render();
    // 휠은 여러 번 온다 - 멎은 뒤에 한 번만 보낸다.
    win?.clearTimeout(wheelTimer);
    wheelTimer = win?.setTimeout(() => { wheelAnchor = null; commit(); }, 220) || 0;
  }

  /** 두 장일 때의 휠: 커서 밑 칸의 그림을, 커서 밑의 점(피벗)을 붙잡고 키우거나 줄인다. */
  function onTwoPictureWheel(event, from) {
    const point = canvasPoint(event);
    if (!wheelAnchor) {
      // 칸 안이면 커서 밑 칸의 그림, 칸 밖이면 고른 그림. 피벗 = 그 그림 위의 커서, 아니면 보이는 부분의 가운데.
      const inside = point.x >= 0 && point.x <= from.divider;
      const n = inside ? slotAt(point) : slot;
      slot = n;
      const picBox = n === 2 ? from.box2 : from.box;
      const seen = cellSeen(picBox, from.divider, n, from);
      const over = seen && point.x >= seen.left && point.x <= seen.right && point.y >= seen.top && point.y <= seen.bottom;
      const held = over || !seen ? point : {x: (seen.left + seen.right) / 2, y: (seen.top + seen.bottom) / 2};
      wheelAnchor = {...insetZoomAnchor(picBox, held), slot: n};
    }
    const n = wheelAnchor.slot;
    const picBox = n === 2 ? from.box2 : from.box;
    const zoomed = clampCell(zoomInsetBox(picBox, event.deltaY < 0 ? 1 : -1, wheelAnchor, from.divider, geoOf(n)),
      from.divider, n, from);
    draft = {...from, [n === 2 ? 'box2' : 'box']: zoomed};
    render();
    win?.clearTimeout(wheelTimer);
    wheelTimer = win?.setTimeout(() => { wheelAnchor = null; commit(); }, 220) || 0;
  }

  /** 모델 공간의 점이 든 칸(두 장일 때). 한 장이면 늘 1. */
  function slotAt(point) {
    const lay = layout();
    return lay.box2 && point.y >= lay.split ? 2 : 1;
  }

  function commit() {
    if (!draft || !configured()) { draft = null; return lastSend; }
    const sent = draft;
    lastSend = sent.box2
      ? send({x: sent.box.x, y: sent.box.y, height: sent.box.height, divider: sent.divider, split: sent.split,
        second: {x: sent.box2.x, y: sent.box2.y, height: sent.box2.height}}, sent)
      : send({x: sent.box.x, y: sent.box.y, height: sent.box.height, divider: sent.divider}, sent);
    return lastSend;
  }

  // ── 그림 칩 · 결과 ─────────────────────────────────────────────────────
  function renderSlots(two, lock) {
    const chip = (key, label, on, title = '') => `<button type="button" class="riw-chip${on ? ' is-on' : ''}"
      data-riw-slot="${key}" aria-pressed="${on ? 'true' : 'false'}"${lock ? ' disabled' : ''}${
      title ? ` data-naia-title="${escHtml(title)}"` : ''}>${label}</button>`;
    const html = two || wantSecond
      ? chip('1', '그림 1', slot === 1) + chip('2', two ? '그림 2' : '그림 2 · 비어 있음', slot === 2)
        + (two ? chip('remove', '&times; 빼기', false, '둘째 그림을 뺍니다 - 칸이 다시 하나가 됩니다') : '')
      : chip('add', '+ 한 장 더', false, '같은 인물의 둘째 그림을 칸에 함께 넣습니다 (두 장까지) - 붙여넣기 · Storage 로 넣습니다');
    if (el.slots.innerHTML !== html) el.slots.innerHTML = html;
  }

  function onPickSlot(event) {
    const pick = event.target.closest('[data-riw-slot]');
    if (!pick || !configured() || locked()) return;
    const key = pick.dataset.riwSlot;
    if (key === 'add') { wantSecond = true; slot = 2; render(); return; }
    if (key === 'remove') {
      win?.clearTimeout(wheelTimer);
      wheelAnchor = null;
      draft = null;
      wantSecond = false;
      slot = 1;
      send({reset: true}, null, '/api/character-asset/inset/source?slot=2').then(data => {
        if (data) showToast('둘째 그림을 뺐습니다', 'success');
      });
      return;
    }
    slot = key === '2' ? 2 : 1;
    if (slot === 1 && !state.second) wantSecond = false;
    showRecognized();          // 고른 그림의 인식 칸으로(Codex 리뷰 - 다른 그림의 것이 남아 있었다)
    render();
  }

  /** 마지막 결과를 그릴 곳에 얹는다. 크기가 이 캔버스(또는 칸을 뺀 그릴 곳)와 맞을 때만 - 다른 캔버스의 결과는 감춘다. */
  function renderResult(canvasW, canvasH) {
    const want = !!el.showResult.checked && !!lastResult;
    let place = null;
    if (want) {
      const {width: rw, height: rh} = lastResult;
      if (rw === canvasW && rh === canvasH) place = {left: 0, top: 0, width: canvasW, height: canvasH};
      else if (!vertical() && rh === canvasH && rw < canvasW) place = {left: canvasW - rw, top: 0, width: rw, height: rh};
      else if (vertical() && rw === canvasW && rh < canvasH) place = {left: 0, top: canvasH - rh, width: rw, height: rh};
    }
    el.result.hidden = !place;
    if (place) {
      if (el.result.getAttribute('src') !== lastResult.url) el.result.setAttribute('src', lastResult.url);
      el.result.style.left = `${(place.left / canvasW) * 100}%`;
      el.result.style.top = `${(place.top / canvasH) * 100}%`;
      el.result.style.width = `${(place.width / canvasW) * 100}%`;
      el.result.style.height = `${(place.height / canvasH) * 100}%`;
    }
    el.resultNote.textContent = !el.showResult.checked ? ''
      : !lastResult ? '인셋으로 생성하면 여기에 보입니다'
        : place ? `마지막 결과 ${lastResult.width}x${lastResult.height}` : '다른 캔버스의 결과라 감췄습니다';
  }

  // ── 특징 추출 (사용자 결정 2026-10-18) ──────────────────────────────────
  /** 고른 그림을 WD 태거에 보내 캐릭터 특징만 받는다. ⚠️ 그림이 외부(huggingface)로 나간다 - 단추를 누를 때만. */
  async function runExtract() {
    if (!configured() || locked() || extracting) return;
    const forKey = pictureKey();           // 보낸 순간의 그림 - 이 결과가 어느 그림의 것인지(Codex 리뷰)
    const before = extracted;              // 보낸 순간의 칸 - 그 사이에 칸이 바뀌었으면(다른 그림을 거쳐 왔어도) 덮지 않는다
    extracting = true;
    render();
    showToast('특징 추출 중… 외부 태거의 답을 기다립니다(보통 4초)', 'info');
    try {
      const response = await fetchImpl('/api/character-asset/inset/extract-features', {
        method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({slot}),
      });
      const data = await response.json().catch(() => null);
      if (!response.ok || !data || data.error) {
        showToast(`특징을 뽑지 못했습니다: ${data?.error || response.status}`, 'error');
        return;
      }
      // 기다리는 사이에 그림이 바뀌었으면 버린다 - 지금 그림의 칸(고친 글 포함)을 덮지 않는다(Codex 리뷰).
      if (pictureKey() !== forKey || extracted !== before) {
        showToast('그림이 바뀌어 특징 추출 결과를 버렸습니다', 'info');
        return;
      }
      // 사전에 없는 태그(unknown)는 넣지 않는다(사용자 결정 2026-10-18) - 필요하면 손으로 쓴다(회색으로 보인다).
      extracted = {
        features: data.keep || [],
        clothes: (data.dropped || []).filter(row => row.group === '의상').map(row => row.tag),
        mode: 'features', text: '', url: String(data.space_url || ''), notice: String(data.notice || ''),
        key: forKey,
      };
      extracted.text = extracted.features.join(', ');
    } catch (error) {
      showToast(`특징을 뽑지 못했습니다: ${error.message}`, 'error');
    } finally {
      extracting = false;
      render();
    }
  }

  async function runResetAll() {
    if (locked()) return;
    if (!resetArmed) {
      resetArmed = true;
      win?.clearTimeout(resetTimer);
      resetTimer = win?.setTimeout(() => { resetArmed = false; render(); }, 3000) || 0;
      showToast('한 번 더 누르면 인셋을 초기화합니다 (그림 · 배치 · 가상 캐릭터)', 'info');
      render();
      return;
    }
    resetArmed = false;
    recognizedDismissed = new Set();
    win?.clearTimeout(resetTimer);
    win?.clearTimeout(wheelTimer);
    wheelAnchor = null;
    draft = null;
    extracted = null;
    wantSecond = false;
    slot = 1;
    view = 'main';
    clearResult();
    const data = await send({}, null, '/api/character-asset/inset/reset');
    if (data) showToast('레퍼런스 인셋을 초기화했습니다', 'success');
  }

  async function runRemoveBg() {
    if (!configured() || locked() || removingBg || (slot === 2 && !state.second)) return;
    if (slot === 2 ? state.second?.bg_removed : state.bg_removed) return;
    if (!removeBgArmed) {
      removeBgArmed = true;
      win?.clearTimeout(removeBgTimer);
      removeBgTimer = win?.setTimeout(() => { removeBgArmed = false; render(); }, 3000) || 0;
      showToast('한 번 더 누르면 배경을 지웁니다 (Anlas 소모)', 'info');
      render();
      return;
    }
    removeBgArmed = false;
    win?.clearTimeout(removeBgTimer);
    win?.clearTimeout(wheelTimer);
    wheelAnchor = null;
    removingBg = true;
    render();
    const target = slot;
    try {
      const data = await send({slot: target}, null, '/api/character-asset/inset/remove-bg');
      if (data && data.store_error) {
        // 지운 그림은 칸에 있지만 저장되지 않았다 - 앱을 끄면 사라진다. [저장] 으로 다시 넣게 한다(Codex 리뷰).
        showToast(`배경은 지웠지만 Storage 에 저장하지 못했습니다 - [저장] 을 눌러 주세요 (${data.store_error})`, 'warning');
      } else if (data) {
        showToast(`${target === 2 ? '둘째 그림의' : '칸의 그림의'} 배경을 지웠습니다${
          data.stored ? ' - Storage 에 저장했습니다' : ''}`, 'success');
      }
    } finally {
      removingBg = false;
      render();
    }
  }

  /** [특징만] · [특징+의상] · [의상만] - 프롬프트를 그 묶음으로 다시 채운다(손으로 고친 것은 덮인다). */
  function setExtractMode(mode) {
    if (!extracted) return;
    extracted.mode = mode;
    const tags = mode === 'clothes' ? extracted.clothes
      : mode === 'both' ? [...extracted.features, ...extracted.clothes] : extracted.features;
    extracted.text = tags.join(', ');
    renderExtract();
  }

  /** 프롬프트 칸 뒤에 같은 글을 깔고 태그마다 칠한다: 특징 = 흰색 · 의상 = 연노랑 · 그 밖(직접 쓴 것) = 회색. */
  /** 맨 바깥 쉼표로만 자른다(쉼표도 한 조각으로 남긴다) - 괄호 안 · 가중치 묶음(`n::` ~ `::`) 안의 쉼표는 자르지 않는다.
   *  `core/inset_feature_extract._prompt_units` 와 같은 규칙(Codex 리뷰 - 묶음이 쪼개져 색이 틀렸다). */
  function splitTopLevel(text) {
    const out = [];
    let buf = '';
    let depth = 0;
    let weighted = false;
    for (let i = 0; i < text.length; i += 1) {
      if (text.startsWith('::', i)) {
        if (weighted) weighted = false;
        else if (/-?\d+(?:\.\d+)?\s*$/.test(buf)) weighted = true;
        buf += '::';
        i += 1;
        continue;
      }
      const ch = text[i];
      if ('{[('.includes(ch)) depth += 1;
      else if ('}])'.includes(ch)) depth = Math.max(0, depth - 1);
      if (ch === ',' && depth === 0 && !weighted) { out.push(buf, ','); buf = ''; } else buf += ch;
    }
    out.push(buf);
    return out;
  }

  function paintExtract() {
    const features = new Set(extracted.features.map(tag => tag.toLowerCase()));
    const clothes = new Set(extracted.clothes.map(tag => tag.toLowerCase()));
    const html = splitTopLevel(String(extracted.text || '')).map(part => {
      if (part === ',') return '<span class="riw-hl-sep">,</span>';
      const key = part.trim().toLowerCase();
      const kind = features.has(key) ? 'f' : clothes.has(key) ? 'c' : 'o';
      return `<span class="riw-hl-${kind}">${escHtml(part)}</span>`;
    }).join('') + '\n';
    el.extractHl.innerHTML = html;
    el.extractHl.scrollTop = el.extractText.scrollTop;
  }

  function renderExtract() {
    el.extract.hidden = !extracted || view !== 'main' || !configured();
    if (el.extract.hidden) return;
    el.extractLabel.textContent = extracted.label || '추출된 특징';
    if (el.extractText.value !== extracted.text) el.extractText.value = extracted.text;
    el.extractModes.querySelectorAll('[data-riw-extract-mode]').forEach(button => {
      const on = button.dataset.riwExtractMode === extracted.mode;
      button.classList.toggle('is-on', on);
      button.setAttribute('aria-pressed', on ? 'true' : 'false');
    });
    paintExtract();
    const src = extracted.url
      ? `[ ${escHtml(extracted.notice || '웹에서 사용')} : <a href="${escHtml(extracted.url)}" target="_blank"
         rel="noopener noreferrer">WD 태거</a> ]` : escHtml(extracted.source || '');
    if (el.extractSrc.innerHTML !== src) el.extractSrc.innerHTML = src;
  }

  /** 프롬프트 칸의 글을 가상 캐릭터에 넣는다. */
  async function useExtracted(key) {
    if (!extracted) return;
    const applied = extracted;             // 누른 순간의 칸 - 답을 기다리는 사이에 그림을 바꿔도 이것을 닫는다(Codex 리뷰)
    // 칸에 적힌 그대로 넣는다(손으로 고친 것 포함) - 빈 조각만 걷는다.
    const prompt = String(extracted.text || '').split(',').map(part => part.trim()).filter(Boolean).join(', ');
    if (!prompt) { showToast('넣을 프롬프트가 비어 있습니다', 'error'); return; }
    const data = await send({key, value: key === 'virtual_c1' ? {prompt} : prompt}, KEEP_DRAFT,
      '/api/character-asset/inset/character');
    if (!data) return;
    // 넣은 칸은 닫은 것과 같다 - 그 그림의 인식 칸을 다시 띄우지 않는다(Codex 리뷰).
    if (applied.key) recognizedDismissed.add(applied.key);
    // 다른 그림을 거쳐 돌아와 같은 그림의 칸이 새로 떠 있어도 닫는다 - 단 그 새 칸을 손으로 고쳤으면(아직 안 넣은 글) 둔다(Codex 리뷰).
    if (extracted === applied || (applied.key && extracted?.key === applied.key && !extracted.edited)) extracted = null;
    render();
    showToast(key === 'virtual_c1' ? '가상 C1 에 넣었습니다' : '가상 캐릭터로 추가했습니다', 'success');
  }

  /** 앱이 새 결과를 받을 때마다 부른다. 인셋이 켜져 있을 때 온 결과만 쥔다(그 결과가 이 캔버스로 나간 것이다). */
  function showResult(blob) {
    if (!configured() || !state.active || !blob || typeof URL === 'undefined') return;
    const seq = ++resultSeq;
    const url = URL.createObjectURL(blob);
    const probe = new Image();
    probe.onload = () => {
      // 그 사이에 더 새 결과가 왔거나 인셋을 껐다 - 이 결과는 버린다(Codex 리뷰).
      if (seq !== resultSeq || !configured() || !state.active) { URL.revokeObjectURL(url); return; }
      if (lastResult?.url) URL.revokeObjectURL(lastResult.url);
      lastResult = {url, width: probe.naturalWidth, height: probe.naturalHeight};
      if (panel?.isOpen()) render();
    };
    probe.onerror = () => { URL.revokeObjectURL(url); };
    probe.src = url;
  }

  /** 쥔 결과를 놓는다(인셋을 껐거나 꽂아 둔 것이 없어졌다) - 풀리는 중인 것도 버린다. */
  function clearResult() {
    resultSeq += 1;
    if (lastResult?.url && typeof URL !== 'undefined') URL.revokeObjectURL(lastResult.url);
    lastResult = null;
    el?.result?.removeAttribute('src');
  }

  async function runUpscale() {
    if (!configured() || locked() || state.upscaled) return;
    win?.clearTimeout(wheelTimer);
    wheelAnchor = null;
    busy = true;
    render();
    try {
      // 끌어 놓고 아직 안 보낸 배치가 있으면 그것부터 - 업스케일 뒤에 화면에 보이는 배치로 구워져야 한다.
      await commit();
      const data = await send({}, null, '/api/character-asset/inset/upscale');
      if (data) showToast(data.message || '인셋을 업스케일했습니다', 'success');
    } finally {
      busy = false;
      render();
    }
  }

  // ── 서버 ──────────────────────────────────────────────────────────────
  /** 서버에 보낸다. `sent` = 이 요청이 실어 간 배치(`draft` 였던 것) | null(배치를 통째로 바꾸는 요청 - 기본값 ·
   *  해상도 · 그림 바꾸기 · 업스케일) | KEEP_DRAFT(배치와 무관한 요청). 답은 새 상태이거나, 실패하면 null. */
  function send(body, sent, route = '') {
    // 배치를 실어 가는 요청은 **만들 때의** 그림 · 캔버스를 적어 둔다 - 줄에서 기다리는 사이에 그것이 바뀌면
    // 보내지 않는다. 보내면 새 그림의 기본 배치를 옛 그림의 좌표가 덮는다(Codex 리뷰 4차).
    const made = sent && sent !== KEEP_DRAFT ? identity() : '';
    const run = sendChain.then(() => {
      if (made && made !== identity()) {
        if (draft === sent) draft = null;
        render();
        return null;
      }
      return sendNow(body, sent, route);
    });
    sendChain = run.catch(() => null);      // 한 요청이 터져도 줄은 이어진다
    return run;
  }

  async function sendNow(body, sent, route) {
    const path = route || (body.width ? '/api/character-asset/inset/canvas' : '/api/character-asset/inset/box');
    // 붙여넣은 그림은 본문 바이트 그대로 보낸다(그 밖에는 JSON).
    const raw = typeof Blob !== 'undefined' && body instanceof Blob;
    let data = null;
    let failed = '';
    let lost = false;       // 답을 못 받았다 - 서버가 바꿨는지 알 수 없다
    // 기다리는 한계. 넘으면 이 요청을 실패로 치고 줄을 풀어 준다 - 안 그러면 뒤의 요청이 영영 안 나간다.
    const controller = typeof AbortController === 'function' ? new AbortController() : null;
    const limit = path.endsWith('/inset/upscale') || path.endsWith('/inset/remove-bg') ? UPSCALE_TIMEOUT_MS : SEND_TIMEOUT_MS;
    const timer = controller && win ? win.setTimeout(() => controller.abort(), limit) : 0;
    try {
      const response = await fetchImpl(path, {
        method: 'POST',
        headers: {'Content-Type': raw ? (body.type || 'image/png') : 'application/json'},
        body: raw ? body : JSON.stringify(body),
        ...(controller ? {signal: controller.signal} : {}),
      });
      let bodyLost = false;
      data = await response.json().catch(() => { bodyLost = true; return null; });
      if (response.ok && bodyLost) {
        // 서버는 '됐다' 고 했는데 본문을 못 읽었다(읽는 중에 끊김 · 한계 시간) - 바뀌었을 수 있다. 결과를 모른다.
        lost = true;
        failed = '응답이 끊겼습니다';
      } else if (!response.ok || !data || data.error) {
        failed = data?.error || `HTTP ${response.status}`;
      }
    } catch (error) {
      lost = true;
      failed = error?.name === 'AbortError' ? '응답이 너무 늦습니다' : '서버에 닿지 못했습니다';
    } finally {
      if (timer) win.clearTimeout(timer);
    }
    // 보낸 뒤에 또 끌었거나 굴렸으면(draft 가 달라졌다) 그 손을 덮지 않는다. 배치와 무관한 답은 draft 를 안 건드린다 -
    // 휠을 굴리고 보내기를 기다리는 사이(220ms)에 체크 하나를 누르면 굴린 배치가 사라졌다(Codex 리뷰 2026-10-10).
    if (sent !== KEEP_DRAFT && !drag && (sent === null || draft === sent)) draft = null;
    if (failed) {
      if (lost) {
        // 답을 못 받았을 뿐이다 - 서버는 받았을 수 있고, **나중에 끝낼 수도 있다**. '못 바꿨다' 고 단정하지 않고,
        // 지금 상태를 받은 뒤 몇 번 더 물어 맞춘다. 한 번만 묻고 말면, 그 뒤에 서버가 인셋을 켰을 때 띠 없이
        // 인셋으로 생성이 나간다(Codex 리뷰 3차).
        showToast(`인셋의 답을 받지 못했습니다(${failed}) - 서버가 끝내면 화면을 맞춥니다`, 'warning');
        followUp();
      } else {
        showToast(`인셋을 바꾸지 못했습니다: ${failed}`, 'error');
      }
      render();
      return null;
    }
    onState(data);                               // 띠와 이 창이 같은 상태를 본다(`sync` 로 돌아온다)
    // 앱이 이 답을 옛것이라고 버렸으면 `sync` 가 안 돌아온다 - 위에서 끌던 배치를 지웠으니 여기서 다시 그린다.
    render();
    return data;
  }

  function followUp() {
    followTimers.forEach(timer => win?.clearTimeout(timer));
    followTimers = [];
    refresh();
    if (!win) return;
    followTimers = FOLLOW_UP_MS.map(delay => win.setTimeout(refresh, delay));
  }

  /** 서버의 지금 상태를 다시 받는다(답을 못 받았을 때 · 보관본을 지운 뒤). */
  async function refresh() {
    try {
      const response = await fetchImpl('/api/character-asset/inset/state');
      const fresh = response.ok ? await response.json().catch(() => null) : null;
      if (fresh) onState(fresh);
    } catch (_error) { /* 다음 조작의 답이 맞춘다 */ }
  }

  const sizeLabel = pair => `${Number(pair?.[0]) || 0}x${Number(pair?.[1]) || 0}`;

  /** 캔버스 크기를 비율(종류)별로 묶은 것. 옛 백엔드는 묶음을 안 보낸다 - 그때는 한 묶음으로(비율 줄이 안 뜬다). */
  function sizeGroups() {
    const groups = Array.isArray(state?.size_groups)
      ? state.size_groups.filter(group => Array.isArray(group?.sizes) && group.sizes.length) : [];
    return groups.length ? groups : [{label: '', sizes: Array.isArray(state?.sizes) ? state.sizes : []}];
  }

  /** 지금 캔버스가 든 묶음의 자리(없으면 0). */
  function kindIndex(groups, current) {
    const at = groups.findIndex(group => group.sizes.some(pair => sizeLabel(pair) === current));
    return at < 0 ? 0 : at;
  }

  function pickCanvas(width, height) {
    if (!(width > 0 && height > 0)) return;
    if (width === Number(state.width) && height === Number(state.height)) return;
    win?.clearTimeout(wheelTimer);
    wheelAnchor = null;
    draft = null;
    send({width, height}, null);
  }

  function onPickSize(event) {
    const pick = event.target.closest('[data-riw-size]');
    if (!pick || !configured() || locked()) return;
    const [width, height] = pick.dataset.riwSize.split('x').map(Number);
    pickCanvas(width, height);
  }

  /** 비율을 바꾼다 - **같은 급**(묶음 안의 같은 자리: 1MP · Large · Wallpaper)의 크기로 간다. 무료 대역에 있었으면
   *  비율을 바꿔도 무료 대역이다(비율만 바꾸려다 Anlas 가 드는 크기로 건너가지 않는다). */
  function onPickKind(event) {
    const pick = event.target.closest('[data-riw-kind]');
    if (!pick || !configured() || locked()) return;
    const groups = sizeGroups();
    const current = `${Number(state.width) || 0}x${Number(state.height) || 0}`;
    const from = groups[kindIndex(groups, current)];
    const tier = Math.max(0, from.sizes.findIndex(pair => sizeLabel(pair) === current));
    const to = groups[Number(pick.dataset.riwKind)];
    const pair = to?.sizes[Math.min(tier, (to?.sizes.length || 1) - 1)];
    if (pair) pickCanvas(Number(pair[0]), Number(pair[1]));
  }

  /** [붙여넣기] 로 읽어 온 그림을 받는다. 꽂아 둔 것이 없으면 이 그림만으로 인셋이 선다(서버가 켠다).
   *  ⚠️ 앱의 Ctrl+V 훅에 이것을 물리지 말 것 - 단추로만 받는다(머리 주석). */
  function acceptPastedImage(blob, pressed = null) {
    if (!panel || !panel.isOpen()) return false;
    if (!blob || !String(blob.type || '').startsWith('image/')) {
      showToast('클립보드에 그림이 없습니다', 'error');
      return false;
    }
    if (locked()) return true;                 // 업스케일을 기다리는 중 - 아무것도 안 한다
    win?.clearTimeout(wheelTimer);
    wheelAnchor = null;
    draft = null;                              // 그림이 바뀌면 배치는 기본으로 돌아간다 - 끌던 것을 버린다
    const fresh = !configured();
    // 단추를 누른 순간의 차례(클립보드를 읽기 전에 잡아 둔 것). 단추 없이 불렸으면 지금 값 - 어느 쪽이든 줄을 서기 전이다.
    const epoch = pressed ? pressed.epoch : toggleEpoch();
    const target = pressed ? pressed.slot : slot;
    // 둘째 그림 자리를 골랐으면(첫 그림이 있을 때만) 그리로 간다.
    const toSecond = target === 2 && !fresh;
    const query = [epoch === null ? '' : `toggle=${epoch}`, toSecond ? 'slot=2' : ''].filter(Boolean).join('&');
    send(blob, null, '/api/character-asset/inset/source' + (query ? `?${query}` : '')).then(data => {
      if (!data) return;
      view = 'main';
      if (toSecond) { wantSecond = false; render(); showToast('둘째 그림을 넣었습니다', 'success'); return; }
      render();
      // 켜졌는지는 서버의 답이 말한다 - 그 사이에 사용자가 껐으면 그림만 바뀌고 꺼진 채다.
      showToast(!data.active ? '인셋 칸의 그림을 바꿨습니다 - 인셋은 꺼져 있습니다'
        : fresh ? '붙여넣은 그림으로 레퍼런스 인셋을 켰습니다' : '인셋 칸의 그림을 붙여넣은 그림으로 바꿨습니다', 'success');
    });
    return true;
  }

  // ── Storage ───────────────────────────────────────────────────────────
  async function saveToStorage() {
    const onSecond = slot === 2;
    if (!configured() || locked() || (onSecond ? !state.second || state.second.saved : state.saved)) return;
    const data = await send(onSecond ? {slot: 2} : {}, KEEP_DRAFT, '/api/character-asset/inset/storage');
    if (data) showToast('Storage 에 저장했습니다', 'success');
  }

  function showMain() {
    view = 'main';
    disarmDelete();
    render();
  }

  async function showStorage() {
    view = 'storage';
    disarmDelete();
    render();
    await loadStorage();
  }

  async function loadStorage() {
    const seq = ++storedSeq;
    let data = null;
    try {
      const response = await fetchImpl('/api/character-asset/inset/storage');
      data = response.ok ? await response.json().catch(() => null) : null;
    } catch (_error) { data = null; }
    if (seq !== storedSeq) return;
    if (!data || !Array.isArray(data.items)) {
      stored = {items: [], current: '', failed: true};
      showToast('Storage 를 읽지 못했습니다', 'error');
    } else {
      stored = data;
    }
    if (view === 'storage') render();
  }

  function disarmDelete() {
    armedDelete = '';
    win?.clearTimeout(armedTimer);
  }

  function renderStorage() {
    const items = stored?.items || [];
    el.storeCount.textContent = stored ? `Storage · ${items.length}장` : 'Storage';
    if (!stored) {
      el.storeGrid.innerHTML = '<div class="riw-store-empty">불러오는 중…</div>';
      return;
    }
    if (!items.length) {
      el.storeGrid.innerHTML = `<div class="riw-store-empty">${stored.failed ? 'Storage 를 읽지 못했습니다'
        : '저장해 둔 그림이 없습니다 - 칸에 그림을 넣고 [저장] 을 누르면 여기에 남습니다'}</div>`;
      return;
    }
    // 지금 칸에 놓인 그림 = 인셋 상태의 `saved` 가 가리키는 한 장(목록의 `current`).
    const current = slot === 2 ? (state?.second?.saved ? String(stored.current2 || '') : '')
      : state?.saved ? String(stored.current || '') : '';
    el.storeGrid.innerHTML = items.map(item => {
      const id = escHtml(item.id);
      const armed = armedDelete === item.id;
      return `<div class="riw-store-item${item.id === current ? ' is-current' : ''}" data-riw-item="${id}">
        <button type="button" class="riw-store-pick" data-riw-pick="${id}"
                data-naia-title="이 그림을 인셋 칸에 놓고 인셋을 켭니다">
          <img src="/api/character-asset/inset/storage/${id}/image?thumb=1" alt="저장해 둔 레퍼런스" loading="lazy" draggable="false">
          <span class="riw-store-size">${Number(item.width) || 0}x${Number(item.height) || 0}</span>
        </button>
        <button type="button" class="riw-store-x${armed ? ' is-armed' : ''}" data-riw-del="${id}"
                data-naia-title="Storage 에서 지웁니다 (한 번 더 눌러야 지워집니다)">${armed ? '지우기' : '&times;'}</button>
      </div>`;
    }).join('');
  }

  async function onStoreClick(event) {
    const del = event.target.closest('[data-riw-del]');
    if (del) {
      const id = del.dataset.riwDel;
      if (armedDelete !== id) {
        // 한 번 누르면 '지우기' 로 바뀌고, 그 상태에서 한 번 더 눌러야 지운다(되돌릴 수 없다).
        disarmDelete();
        armedDelete = id;
        armedTimer = win?.setTimeout(() => { armedDelete = ''; if (view === 'storage') render(); }, 3000) || 0;
        render();
        return;
      }
      disarmDelete();
      await deleteStored(id);
      return;
    }
    const pick = event.target.closest('[data-riw-pick]');
    if (!pick || locked()) return;
    win?.clearTimeout(wheelTimer);
    wheelAnchor = null;
    draft = null;
    const toSecond = slot === 2 && configured();
    const data = await send({id: pick.dataset.riwPick, toggle: toggleEpoch(), ...(toSecond ? {slot: 2} : {})}, null,
      '/api/character-asset/inset/storage/apply');
    if (!data) { loadStorage(); return; }      // 그 사이에 지워졌을 수 있다 - 목록을 다시 받는다
    if (toSecond) wantSecond = false;
    view = 'main';
    render();
    showToast(data.active ? 'Storage 의 그림을 인셋 칸에 놓았습니다'
      : 'Storage 의 그림을 인셋 칸에 놓았습니다 - 인셋은 꺼져 있습니다', 'success');
  }

  async function deleteStored(id) {
    const seq = ++storedSeq;
    let data = null;
    try {
      const response = await fetchImpl(`/api/character-asset/inset/storage/${encodeURIComponent(id)}`, {method: 'DELETE'});
      data = response.ok ? await response.json().catch(() => null) : null;
    } catch (_error) { data = null; }
    if (!data || !Array.isArray(data.items)) {
      showToast('Storage 에서 지우지 못했습니다', 'error');
      if (seq === storedSeq) loadStorage();
      return;
    }
    if (seq === storedSeq) stored = {items: data.items, current: data.current || ''};
    // 지운 것이 지금 칸의 그림이었으면 '저장됨' 이 풀린다 - 인셋 상태를 다시 받는다(칸의 그림은 그대로다).
    await refresh();
    if (view === 'storage') render();
  }

  // ── 바깥에서 부르는 것 ────────────────────────────────────────────────
  /** 서버 상태가 바뀔 때마다 부른다. 꺼졌거나 꽂아 둔 것이 없어져도 **창은 닫지 않는다** - 이 창이 켜는 자리다. */
  /** 붙여넣은 NAI 그림의 캐릭터 프롬프트를 '프롬프트 인식됨' 으로 띄운다(사용자 지시 2026-10-18). 고른 칸의 그림이
   *  처음 보일 때 한 번 - [특징만] · [특징+의상] · [의상만] 과 칠하기는 [특징 추출] 과 같다. */
  /** 고른 그림의 열쇠(칸 · 그림 판). 추출 칸이 어느 그림의 것인지 가른다. */
  function pictureKey() {
    const n = slot === 2 ? 2 : 1;
    return `${n}|${n === 2 ? state?.second?.source_revision || '' : state?.source_revision || ''}`;
  }

  function showRecognized() {
    if (!configured()) return;
    const n = slot === 2 ? 2 : 1;
    const rec = n === 2 ? state.second?.recognized : state.recognized;
    const key = pictureKey();
    // 이미 이 그림의 것(인식이든 [특징 추출] 이든) - 고친 글을 덮지 않는다(Codex 리뷰).
    if (extracted?.key === key) return;
    // 다른 그림의 칸([특징 추출] 결과도)은 걷는다(Codex 리뷰 - 메타데이터 없는 그림 아래에 앞 그림의 글이 남아 C1 으로 들어갔다).
    if (extracted && extracted.key !== key) extracted = null;
    if (!rec || recognizedDismissed.has(key)) return;
    extracted = {
      features: rec.features || [], clothes: rec.clothes || [], mode: 'features', text: (rec.features || []).join(', '),
      url: '', notice: '', label: '프롬프트 인식됨', source: `NAI 메타데이터 · C1${n === 2 ? ' (둘째 그림)' : ''}`,
      key, recKey: key,
    };
  }

  function sync(next) {
    const before = state;
    state = next && typeof next === 'object' ? next : null;
    if (!configured() || !state.active) clearResult();     // 꺼지면 마지막 결과도 놓는다(Codex 리뷰)
    showRecognized();          // 창이 닫혀 있을 때 붙여넣었어도 열면 보이게 - 창 확인보다 먼저
    if (!panel) return;
    if (!configured()) draft = null;       // 놓을 그림이 없다 - 닫으면서 보낼 배치도 없다
    // 캔버스나 그림이 바뀌었으면(띠의 해상도 메뉴 · 다른 창) 끌어 놓은 배치는 **옛 캔버스의 값**이다 - 버린다.
    // 안 버리면 새 캔버스 위에 옛 배치가 그려진다(Codex 리뷰 3차). 끄는 중인 손은 놓을 때 새 한계에 맞춰진다.
    if (draft && !drag && before && state && (before.width !== state.width || before.height !== state.height
        || before.source_revision !== state.source_revision || before.character_id !== state.character_id
        || before.variation !== state.variation || before.orientation !== state.orientation
        || before.second?.source_revision !== state.second?.source_revision)) {
      win?.clearTimeout(wheelTimer);
      wheelAnchor = null;
      draft = null;
    }
    if (panel.isOpen()) render();
  }

  function open(next) {
    state = next && typeof next === 'object' ? next : {active: false, configured: false};
    showRecognized();
    ensurePanel();
    draft = null;
    view = 'main';
    disarmDelete();
    panel.open();
    panel.expand?.();          // 연다는 것은 보겠다는 것이다 - 접혀 있었으면 편다
    panel.raise?.();
    render();
  }

  /** 창을 닫는다(떠 있을 때만). 에셋에서 [C1 + 레퍼런스 인셋 적용] 을 누르면 창은 닫힌 채로 Result 로 넘어간다. */
  function close() {
    if (panel?.isOpen()) panel.close();
  }

  return {open, close, sync, isOpen: () => !!panel?.isOpen(), acceptPastedImage, showResult};
}
