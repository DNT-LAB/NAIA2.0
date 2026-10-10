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
 *    - 꽂아 둔 것이 없다 → '레퍼런스로 쓸 그림을 넣어 주세요' + [붙여넣기] [Storage]
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
 *  에셋의 그림은 Assets 탭의 [C1+레퍼런스 인셋] 으로 꽂는다 - 이 창에는 에셋을 고르는 단추가 없다(사용자 결정).
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
} = {}) {
  let panel = null;
  // 서버의 인셋 상태. 꽂아 둔 것이 없으면 `{configured: false}` - 그때도 창은 열려 있다.
  let state = null;
  let view = 'main';        // 'main'(배치) | 'storage'(저장해 둔 그림 목록)
  let stored = null;        // Storage 목록 {items, current} - 열 때마다 다시 받는다
  let storedSeq = 0;
  let armedDelete = '';     // x 를 한 번 누른 보관본의 id - 한 번 더 눌러야 지운다
  let armedTimer = 0;
  let draft = null;         // 끄는 중 · 보내는 중인 배치 {box, divider} - 있으면 이것을 그린다
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
  let pressedPasteEpoch;
  // 지금 칸에 놓인 그림 · 캔버스의 표식. 배치는 이것이 같을 때만 뜻이 있다(다른 그림 · 다른 캔버스의 좌표다).
  const identity = () => (configured()
    ? [state.width, state.height, state.source_revision, state.character_id, state.variation].join('|') : '');
  // 답을 못 받은 요청은 서버가 나중에 끝낼 수 있다 - 그때의 상태를 받아 오려고 몇 번 더 묻는다(ms 뒤).
  const FOLLOW_UP_MS = [2000, 5000, 15000, 30000, 60000];
  let followTimers = [];
  const layout = () => draft || {box: state.box, divider: state.divider};
  // 업스케일을 기다리는 동안만 배치가 잠긴다. 업스케일해 둔 뒤에는 마음대로 바꾼다(원본을 올려 둔 것이라 유지된다).
  const locked = () => busy;

  function ensurePanel() {
    if (panel) return panel;
    panel = createDraggablePanel({
      document: doc, window: win, title: '레퍼런스 인셋', variant: 'riw', storageKey: 'reference-inset',
      width: 520, minWidth: 520, maxWidth: 520, collapsible: false, escHtml,
      // 닫을 때 끌어 놓고 아직 안 보낸 배치가 있으면 보낸다 - 휠을 굴리자마자 닫아도 화면에서 본 대로 나간다.
      onClose: () => { drag = null; win?.clearTimeout(wheelTimer); wheelAnchor = null; commit(); },
    });
    // 머리줄의 켜고 끄기. `data-nodrag` 가 없으면 스위치를 누르려다 창을 끈다.
    panel.slot.innerHTML = `
      <label class="riw-switch" data-nodrag data-riw-switch>
        <input type="checkbox" data-riw-enabled>
        <span class="riw-switch-text" data-riw-enabled-text>끔</span>
      </label>`;
    panel.body.innerHTML = `
      <div class="riw-main" data-riw-main>
        <div class="riw-stage" data-riw-stage>
          <div class="riw-panel" data-riw-panel data-naia-title="끌어서 칸 안의 그림을 옮깁니다 · 휠로 크기를 바꿉니다">
            <img class="riw-pic" alt="레퍼런스 인셋 그림" draggable="false">
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
          </div>
          <div class="riw-empty-hint">에셋의 그림은 Assets 탭의 [C1+레퍼런스 인셋] 으로 꽂습니다</div>
        </div>
        <div class="riw-row" data-riw-row>
          <span class="riw-label">칸의 그림</span>
          <button type="button" class="riw-chip" data-riw-paste
                  data-naia-title="클립보드의 그림(캡쳐 · 복사한 것)으로 인셋 칸의 그림을 바꿉니다">붙여넣기</button>
          <button type="button" class="riw-chip" data-riw-save
                  data-naia-title="지금 칸의 그림을 Storage 에 넣어 둡니다 - 앱을 다시 켜도 꺼내 쓸 수 있습니다 (그림만 기억합니다 · 업스케일해 뒀으면 올려 둔 판을 넣습니다)">저장</button>
          <button type="button" class="riw-chip" data-riw-storage
                  data-naia-title="저장해 둔 그림에서 고릅니다">Storage</button>
          <button type="button" class="riw-chip" data-riw-upscale
                  data-naia-title="레퍼런스 원본을 NAI 업스케일에 한 번 보내 두고, 그 뒤로는 거기서 줄여 칸에 놓습니다 - 그림을 키워도 흐려지지 않습니다 (Anlas 가 듭니다 · 그림 하나에 한 번)">업스케일</button>
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
          <span class="riw-cost" data-riw-cost
                data-naia-title="이 캔버스(1MP 를 넘는 해상도)로 생성하면 Anlas 를 소모합니다"></span>
        </div>
      </div>
      <div class="riw-store" data-riw-store hidden>
        <div class="riw-row">
          <button type="button" class="riw-chip" data-riw-back>&#8592; 돌아가기</button>
          <span class="riw-label" data-riw-store-count></span>
          <span class="riw-read">누르면 칸에 놓습니다 · 배치는 기본으로 놓입니다</span>
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
      frame: find('[data-riw-frame]'),
      divider: find('[data-riw-divider]'),
      kinds: find('[data-riw-kinds]'),
      sizes: find('[data-riw-sizes]'),
      cost: find('[data-riw-cost]'),
      reset: find('[data-riw-reset]'),
      read: find('[data-riw-read]'),
      upscale: find('[data-riw-upscale]'),
      pastes: [...panel.body.querySelectorAll('[data-riw-paste]')],
      storages: [...panel.body.querySelectorAll('[data-riw-storage]')],
      save: find('[data-riw-save]'),
      crop: find('[data-riw-crop]'),
      note: find('[data-riw-note]'),
      enabled: panel.slot.querySelector('[data-riw-enabled]'),
      enabledText: panel.slot.querySelector('[data-riw-enabled-text]'),
      switchBox: panel.slot.querySelector('[data-riw-switch]'),
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
    el.kinds.addEventListener('click', onPickKind);
    el.reset.addEventListener('click', () => { if (!locked()) send({reset: true}, null); });
    el.upscale.addEventListener('click', runUpscale);
    el.pastes.forEach(button => button.addEventListener('click', () => {
      if (locked()) return;
      pressedPasteEpoch = toggleEpoch();
      if (typeof requestPaste === 'function') requestPaste();
      else showToast('이 화면에서는 붙여넣기를 쓸 수 없습니다', 'error');
    }));
    el.storages.forEach(button => button.addEventListener('click', () => { if (!locked()) showStorage(); }));
    el.back.addEventListener('click', () => showMain());
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
    el.crop.addEventListener('change', () => {
      send({enabled: el.crop.checked}, KEEP_DRAFT, '/api/character-asset/inset/crop');
    });
    return panel;
  }

  // ── 그리기 ────────────────────────────────────────────────────────────
  function render() {
    if (!panel || !state) return;
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
    if (view === 'storage') { renderStorage(); return; }
    el.stage.hidden = !ready;
    el.empty.hidden = ready;
    el.rows.forEach(row => { row.hidden = !ready; });
    if (!ready) { el.pic.removeAttribute('src'); return; }
    el.stage.classList.toggle('is-off', !on);
    const canvasW = Number(state.width) || 1;
    const canvasH = Number(state.height) || 1;
    const {box, divider} = layout();
    el.stage.style.aspectRatio = `${canvasW} / ${canvasH}`;
    // 칸에 놓인 그림 = 붙여넣은 그림이면 그것, 아니면 에셋의 그림. 주소의 `v` 가 그림이 바뀔 때마다 달라진다
    // (캐릭터 · 바리에이션 · 붙여넣은 그림의 지문) - 캐시가 옛 그림을 주지 않게.
    const src = '/api/character-asset/inset/source?v=' + encodeURIComponent(
      `${state.character_id || ''}-${state.variation || ''}-${state.source_revision || ''}`);
    if (el.pic.getAttribute('src') !== src) el.pic.setAttribute('src', src);
    const pct = (value, whole) => `${(value / whole) * 100}%`;
    // 칸 = 왼쪽 가장자리 ~ 경계선. 그림은 칸이 자른다(칸 기준 % 로 놓는다).
    el.panel.style.width = pct(divider, canvasW);
    el.pic.style.left = pct(box.x, divider);
    el.pic.style.top = pct(box.y, canvasH);
    el.pic.style.width = pct(box.width, divider);
    el.pic.style.height = pct(box.height, canvasH);
    el.divider.style.left = pct(divider, canvasW);
    // 테두리 · 손잡이는 그림의 **칸 안에 보이는 부분**에 붙는다 - 잘려 나간 모서리는 잡을 수 없다.
    const seen = visibleInsetRect(box, divider, canvasH);
    el.frame.hidden = !seen;
    if (seen) {
      el.frame.style.left = pct(seen.left, canvasW);
      el.frame.style.top = pct(seen.top, canvasH);
      el.frame.style.width = pct(seen.right - seen.left, canvasW);
      el.frame.style.height = pct(seen.bottom - seen.top, canvasH);
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
    el.upscale.textContent = busy ? '업스케일 중…' : state.upscaled ? '업스케일됨' : '업스케일';
    el.pastes.forEach(button => { button.disabled = lock; });
    el.storages.forEach(button => { button.disabled = lock; });
    el.save.disabled = lock || !!state.saved;                // 이미 Storage 에 있는 그림이다
    el.save.textContent = state.saved ? '저장됨' : '저장';
    // 그림이 어디서 왔고, 앱을 끄면 남는가.
    const origin = state.saved ? 'Storage 의 그림' : state.standalone ? '붙여넣은 그림 · 저장 안 됨'
      : state.overridden ? '붙여넣은 그림 · 저장 안 됨' : '에셋의 그림';
    el.note.textContent = busy ? 'NAI 업스케일을 기다리는 중…'
      : [on ? '' : '꺼져 있음', origin, state.upscaled ? '업스케일해 둠' : ''].filter(Boolean).join(' · ');
    el.read.textContent = `칸 ${divider}px · 그릴 곳 ${Math.round(insetOpenRatio(divider, canvasW) * 100)}%`;
  }

  // ── 끌기 ──────────────────────────────────────────────────────────────
  function canvasScale() {
    const rect = el.stage.getBoundingClientRect();
    return rect.width > 0 ? (Number(state.width) || 1) / rect.width : 1;
  }

  function canvasPoint(event) {
    const rect = el.stage.getBoundingClientRect();
    const scale = canvasScale();
    return {x: (event.clientX - rect.left) * scale, y: (event.clientY - rect.top) * scale};
  }

  function onPointerDown(event) {
    if (!configured() || locked() || event.button !== 0) return;
    // 경계선 → 칸의 너비 · 손잡이 → 그림 크기 · 칸 안 → 그림 옮기기. 경계선 오른쪽(그릴 곳)은 아무것도 아니다.
    const kind = event.target.closest?.('[data-riw-divider]') ? 'divider'
      : event.target.closest?.('[data-riw-handle]') ? 'size'
      : event.target.closest?.('[data-riw-panel]') ? 'pan' : '';
    if (!kind) return;
    event.preventDefault();
    win?.clearTimeout(wheelTimer);
    wheelAnchor = null;
    // 끄는 내내 **누른 순간의 배치**에서 잰다 - 답이 늦게 와 상태가 바뀌어도 손 밑의 그림이 튀지 않는다.
    const from = layout();
    // `made` = 누른 순간의 그림 · 캔버스. 끄는 동안 그것이 바뀌면(붙여넣기의 답이 왔다) 놓을 때 이 배치를 버린다 -
    // 옛 그림의 좌표를 새 그림에 보내지 않는다(Codex 리뷰 5차).
    drag = {kind, startX: event.clientX, startY: event.clientY, box: {...from.box}, divider: from.divider,
      moved: false, made: identity()};
    try { el.stage.setPointerCapture(event.pointerId); } catch (_error) { /* 못 잡아도 끌린다 */ }
    el.stage.classList.add('is-dragging');
  }

  function onPointerMove(event) {
    if (!drag || !configured()) return;
    if (!drag.moved && Math.hypot(event.clientX - drag.startX, event.clientY - drag.startY) < 3) return;
    drag.moved = true;
    const scale = canvasScale();
    const dx = (event.clientX - drag.startX) * scale;
    const dy = (event.clientY - drag.startY) * scale;
    if (drag.kind === 'divider') {
      const divider = clampInsetDivider(drag.divider + dx, state);
      // 경계선이 그림을 지나쳐 좁아지면 그림을 칸 안으로 데려온다(그림을 잃어버리지 않게).
      draft = {divider, box: clampInsetBox(drag.box, divider, state)};
    } else if (drag.kind === 'size') {
      draft = {divider: drag.divider, box: resizeInsetBox(drag.box, dx, dy, drag.divider, state)};
    } else {
      draft = {divider: drag.divider,
        box: clampInsetBox({x: drag.box.x + dx, y: drag.box.y + dy, height: drag.box.height}, drag.divider, state)};
    }
    render();
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
    if (!wheelAnchor) {
      // 포인터가 칸 안의 그림 위면 그 점을, 아니면 보이는 그림의 가운데를 붙잡는다.
      const point = canvasPoint(event);
      const seen = visibleInsetRect(from.box, from.divider, Number(state.height) || 0);
      const inside = seen && point.x >= seen.left && point.x <= seen.right && point.y >= seen.top && point.y <= seen.bottom;
      const held = inside || !seen ? point : {x: (seen.left + seen.right) / 2, y: (seen.top + seen.bottom) / 2};
      wheelAnchor = insetZoomAnchor(from.box, held);
    }
    draft = {divider: from.divider, box: zoomInsetBox(from.box, event.deltaY < 0 ? 1 : -1, wheelAnchor, from.divider, state)};
    render();
    // 휠은 여러 번 온다 - 멎은 뒤에 한 번만 보낸다.
    win?.clearTimeout(wheelTimer);
    wheelTimer = win?.setTimeout(() => { wheelAnchor = null; commit(); }, 220) || 0;
  }

  function commit() {
    if (!draft || !configured()) { draft = null; return lastSend; }
    const sent = draft;
    lastSend = send({x: sent.box.x, y: sent.box.y, height: sent.box.height, divider: sent.divider}, sent);
    return lastSend;
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
    const limit = path.endsWith('/inset/upscale') ? UPSCALE_TIMEOUT_MS : SEND_TIMEOUT_MS;
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
  function acceptPastedImage(blob) {
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
    const epoch = pressedPasteEpoch !== undefined ? pressedPasteEpoch : toggleEpoch();
    pressedPasteEpoch = undefined;
    send(blob, null, '/api/character-asset/inset/source' + (epoch === null ? '' : `?toggle=${epoch}`)).then(data => {
      if (!data) return;
      view = 'main';
      render();
      // 켜졌는지는 서버의 답이 말한다 - 그 사이에 사용자가 껐으면 그림만 바뀌고 꺼진 채다.
      showToast(!data.active ? '인셋 칸의 그림을 바꿨습니다 - 인셋은 꺼져 있습니다'
        : fresh ? '붙여넣은 그림으로 레퍼런스 인셋을 켰습니다' : '인셋 칸의 그림을 붙여넣은 그림으로 바꿨습니다', 'success');
    });
    return true;
  }

  // ── Storage ───────────────────────────────────────────────────────────
  async function saveToStorage() {
    if (!configured() || locked() || state.saved) return;
    const data = await send({}, KEEP_DRAFT, '/api/character-asset/inset/storage');
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
    const current = state?.saved ? String(stored.current || '') : '';
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
    const data = await send({id: pick.dataset.riwPick, toggle: toggleEpoch()}, null,
      '/api/character-asset/inset/storage/apply');
    if (!data) { loadStorage(); return; }      // 그 사이에 지워졌을 수 있다 - 목록을 다시 받는다
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
  function sync(next) {
    const before = state;
    state = next && typeof next === 'object' ? next : null;
    if (!panel) return;
    if (!configured()) draft = null;       // 놓을 그림이 없다 - 닫으면서 보낼 배치도 없다
    // 캔버스나 그림이 바뀌었으면(띠의 해상도 메뉴 · 다른 창) 끌어 놓은 배치는 **옛 캔버스의 값**이다 - 버린다.
    // 안 버리면 새 캔버스 위에 옛 배치가 그려진다(Codex 리뷰 3차). 끄는 중인 손은 놓을 때 새 한계에 맞춰진다.
    if (draft && !drag && before && state && (before.width !== state.width || before.height !== state.height
        || before.source_revision !== state.source_revision || before.character_id !== state.character_id
        || before.variation !== state.variation)) {
      win?.clearTimeout(wheelTimer);
      wheelAnchor = null;
      draft = null;
    }
    if (panel.isOpen()) render();
  }

  function open(next) {
    state = next && typeof next === 'object' ? next : {active: false, configured: false};
    ensurePanel();
    draft = null;
    view = 'main';
    disarmDelete();
    panel.open();
    panel.raise?.();
    render();
  }

  return {open, sync, isOpen: () => !!panel?.isOpen(), acceptPastedImage};
}
