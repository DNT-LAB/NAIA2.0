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
  openMaskEditor = () => {},
  // 마스크를 지우는 **하나뿐인 목**. 서버만 지우면 브라우저에 남은 초안이 살아 있어,
  // 다시 [마스크 그리기] 를 열면 지운 것이 그대로 되살아난다(사용자 제보 2026-08-30).
  // 실측: 지우기 전 31,232px -> 지운 뒤 도크는 "빈 곳 자동" 인데 에디터는 여전히 31,232px.
  onClearMask = () => {},
  onSlider = () => {},
  onRepeat = () => {},
  onGenerate = () => {},
  // 지금 생성이 도는 중인가(사용자 지정 2026-08-29: 생성 중에는 또 못 누른다).
  isGenerating = () => false,
  onClose = () => {},
  onVisibility = () => {},
  getResolutionBands = () => [],
  getFreePixels = () => 1048576,
}) {
  let state = null;
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
  const transformTimers = {};

  const read = (key, fallback) => {
    try { return localStorage.getItem(key) ?? fallback; } catch (_) { return fallback; }
  };
  const write = (key, value) => {
    try { localStorage.setItem(key, value); } catch (_) {}
  };

  let showGrid = read(GRID_KEY, '1') !== '0';

  const canvasSize = () => ({
    w: Number(state?.canvas_width) || 0,
    h: Number(state?.canvas_height) || 0,
  });

  function send(key, value) {
    try { setModuleParam('img2img', key, value); }
    catch (error) { showToast?.(`캔버스 설정 실패: ${error.message}`, 'error'); }
  }

  /** 변형은 마지막 값만 보낸다. 슬라이더 한 번에 수십 번 합성시키지 않는다. */
  function sendTransform(key, value) {
    if (transformTimers[key]) clearTimeout(transformTimers[key].id);
    transformTimers[key] = {
      value,
      id: setTimeout(() => {
        delete transformTimers[key];
        send(key, value);
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
      send(key, pending.value);
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
    if (next && String(next.window_id || '') !== String(state?.window_id || '')) undoStack = [];
    if (next) state = next;
    if (!panel) return;
    // ⚠️ 조작 중에는 절대 다시 그리지 않는다(posStage 규칙 1). 서버 echo 가 와도
    //    마찬가지다 - 끌고 있던 노드가 교체되면 그 조작이 통째로 무시된다.
    if (posStage?.isDragging() || rangeDragging || typingInPanel()) return;
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
    panel.innerHTML = dockHtml();
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
  function dockHtml() {
    const {w, h} = canvasSize();
    const editing = viewMode === 'edit';
    const off = editing ? '' : 'disabled';
    const scalePct = clampPct((Number(state.base_scale) || 1) * 100);
    const rotation = wrapDeg(state.base_rotation);
    return `
      <div class="ic-bar ic-bar-head ic-nowrap">
        <span class="ic-title">인페인트</span>
        <div class="ic-modes${flashModes ? ' is-fresh' : ''}" role="group" aria-label="보기 모드">
          <button type="button" class="ic-btn${editing ? ' is-on' : ''}" data-ic="mode-edit">편집</button>
          <button type="button" class="ic-btn${editing ? '' : ' is-on'}" data-ic="mode-result">결과 보기</button>
        </div>
        <span class="ic-spacer"></span>
        <span class="ic-hint">${editing
          ? '끌기=이동 · 휠=크기 · Ctrl+휠=회전 · 방향키=1px(Shift 16) · 0=초기화 · 숫자 위치는 POS 에서'
          : '생성 결과를 보는 중입니다.'}</span>
      </div>
      <div class="ic-cols">
        <section class="ic-col" aria-label="캔버스">
          <div class="ic-row">
            <span class="ic-label">캔버스</span>
            <select class="ic-select" data-ic="size" ${off} aria-label="캔버스 해상도">${sizeOptions(w, h)}</select>
            <button type="button" class="ic-btn" data-ic="undo" ${(editing && undoStack.length) ? '' : 'disabled'}
              title="이동/회전을 한 단계 되돌립니다 (Ctrl+Z)">&#8630;</button>
            <button type="button" class="ic-btn" data-ic="reset" ${off}
              title="원본 그대로로 되돌립니다 — 크기·위치·확대·회전">초기화</button>
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
            <button type="button" class="ic-btn ic-nudge" data-ic="rot-down" ${off} title="1° 반시계">−</button>
            <input type="range" class="ic-slider-wide" min="0" max="359" step="1" value="${rotation}"
                   data-ic-tr="rotation" ${off} aria-label="회전 각도">
            <strong class="ic-val" data-ic-val="rotation">${rotation}°</strong>
            <button type="button" class="ic-btn ic-nudge" data-ic="rot-up" ${off} title="1° 시계">+</button>
            <button type="button" class="ic-btn" data-ic="rot-quarter" ${off} title="90° 돌리기">⟳</button>
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
    fitStage();
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
  function nudge(key, delta) {
    if (!state) return;
    if (key === 'scale') applyTransform('scale', clampPct((Number(state.base_scale) || 1) * 100 + delta));
    else applyTransform('rotation', wrapDeg((Number(state.base_rotation) || 0) + delta));
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

  /** 지금의 이동·회전. 되돌리기가 기억하는 것은 이 셋뿐이다. */
  function transformSnapshot() {
    return {
      x: Math.round(Number(state?.base_offset_x) || 0),
      y: Math.round(Number(state?.base_offset_y) || 0),
      rotation: Number(state?.base_rotation) || 0,
    };
  }

  /** 바꾸기 **직전**에 부른다. 같은 값이면 안 쌓는다(방향키를 오래 눌러도 한 칸씩만). */
  function pushUndo() {
    if (!state?.active || undoApplying || undoGestureOpen) return;
    const snap = transformSnapshot();
    const top = undoStack[undoStack.length - 1];
    if (top && top.x === snap.x && top.y === snap.y && top.rotation === snap.rotation) return;
    undoStack.push(snap);
    if (undoStack.length > UNDO_LIMIT) undoStack.shift();
  }

  /** 드래그 한 번을 한 단계로 묶는다. 시작에서 한 번 쌓고, 끝날 때까지 잠근다. */
  function beginUndoGesture() {
    if (undoGestureOpen) return;
    pushUndo();
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
      state.base_rotation = snap.rotation;
      const input = panel?.querySelector('[data-ic-tr="rotation"]');
      const label = panel?.querySelector('[data-ic-val="rotation"]');
      if (input) input.value = String(snap.rotation);
      if (label) label.textContent = `${snap.rotation}°`;
      send('base_rotation', {value: snap.rotation});
      state.base_offset_x = snap.x;
      state.base_offset_y = snap.y;
      send('base_offset', {x: snap.x, y: snap.y});
    } finally {
      undoApplying = false;
    }
  }

  function applyTransform(key, value, at) {
    if (!state) return;
    // 회전만 되돌리기에 남긴다(확대는 대상이 아니다 - 위 UNDO 주석).
    if (key !== 'scale') pushUndo();
    // 규칙 3 — 서버 echo 전에 화면 값을 먼저 맞춰 둔다.
    if (key === 'scale') state.base_scale = value / 100;
    else state.base_rotation = value;
    const input = panel.querySelector(`[data-ic-tr="${key}"]`);
    const label = panel.querySelector(`[data-ic-val="${key}"]`);
    if (input && input.value !== String(value)) input.value = String(value);
    if (label) label.textContent = key === 'scale' ? `${value}%` : `${value}°`;
    // 기준점을 안 주면 백엔드가 캔버스 한가운데를 잡는다(슬라이더·± 가 그 경우다).
    const payload = key === 'scale' ? {value: value / 100} : {value};
    if (at) payload.at = at;
    sendTransform(key === 'scale' ? 'base_scale' : 'base_rotation', payload);
  }

  function onClick(event) {
    const action = event.target.closest?.('[data-ic]')?.dataset.ic;
    if (!action) return;
    if (action === 'mode-edit') return setViewMode('edit');
    if (action === 'mode-result') return setViewMode('result');
    if (action === 'grid') {
      showGrid = !showGrid;
      write(GRID_KEY, showGrid ? '1' : '0');
      return render();
    }
    if (action === 'undo') return undoTransform();
    if (action === 'reset') {
      flushTransforms();
      // ⚠️ 초기화는 **확대와 캔버스 크기까지** 되돌린다. 기록을 남겨 두면 그 뒤의
      //    되돌리기가 이동·회전만 살려 내 **반쪽 상태**가 된다 - 커밋 메시지에
      //    "절대 안 만든다" 고 적어 놓고 정작 안 비우고 있었다(BLOCK 3).
      undoStack = [];
      return send('base_reset', null);
    }
    if (action === 'zoom-in') return nudge('scale', 1);
    if (action === 'zoom-out') return nudge('scale', -1);
    if (action === 'rot-up') return nudge('rotation', 1);
    if (action === 'rot-down') return nudge('rotation', -1);
    // 90° 는 자주 쓰는 자리라 한 번에 간다 - 슬라이더로 정확히 90 을 맞추기는 번거롭다.
    if (action === 'rot-quarter') return nudge('rotation', 90);
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
      applyTransform(transform, transform === 'scale'
        ? clampPct(event.target.value)
        : wrapDeg(event.target.value));
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
    // 마커는 표시 전용이라 붙잡지 않는다 - 그 위에서 눌러도 베이스가 움직인다.
    if (event.button === 1) { event.preventDefault(); beginMiddleDrag(event); return; }
    if (event.button === 0) beginBaseDrag(event);
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
    const startOffset = {
      x: Number(state.base_offset_x) || 0,
      y: Number(state.base_offset_y) || 0,
    };
    const placedW = Number(state.placed_width) || Number(state.base_width) || 0;
    const placedH = Number(state.placed_height) || Number(state.base_height) || 0;
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
      pushUndo();
      if (state) { state.base_offset_x = ox; state.base_offset_y = oy; }
      send('base_offset', {x: ox, y: oy});
    });
  }

  function commit({x, y, key}) {
    if (key === 'base') {
      if (pendingOffset) {
        const {x: ox, y: oy} = pendingOffset;
        pendingOffset = null;
        pushUndo();
        // 규칙 3 — 서버 echo 전에 화면 값을 먼저 맞춰 둔다.
        if (state) { state.base_offset_x = ox; state.base_offset_y = oy; }
        send('base_offset', {x: ox, y: oy});
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
      const next = clampPct((Number(state.base_scale) || 1) * 100 + dir * WHEEL_SCALE_PCT * boost);
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
        const ox = Math.round((Number(state.base_offset_x) || 0) + move[0]);
        const oy = Math.round((Number(state.base_offset_y) || 0) + move[1]);
        state.base_offset_x = ox;
        state.base_offset_y = oy;
        send('base_offset', {x: ox, y: oy});
        return;
      }
      if (event.key === '0') {
        event.preventDefault();
        send('base_reset', null);
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
    const startScale = clampPct((Number(state.base_scale) || 1) * 100);
    const startRotation = wrapDeg(state.base_rotation);
    const ghost = host.querySelector('[data-ic-ghost]');
    // ⚠️ **`placed_*` 를 돌리면 안 된다.** 그건 이미 PIL 이 회전시킨 뒤의 축정렬
    //    바운딩 박스라(`utils/v5_inpaint_canvas.transform_base` 의 `expand=True`),
    //    그 사각형을 CSS 로 또 돌리면 두 번 부풀어 보인다(Codex 자문 2026-08-27).
    //    유령은 **회전 전 사각형**(베이스 x 배율)을 지금 놓인 자리의 한가운데에
    //    놓고 돌린다.
    // ⚠️ 이 유령은 **각도와 대략의 자리**를 보여 주는 조작 피드백이다 - 서버 결과와
    //    픽셀이 같다고 약속하지 않는다. 회전은 캔버스 한가운데를 붙잡으므로 그림이
    //    많이 치우쳐 있으면 놓을 때 조금 어긋난다.
    const scaleNow = Number(state.base_scale) || 1;
    const preW = (Number(state.base_width) || 0) * scaleNow;
    const preH = (Number(state.base_height) || 0) * scaleNow;
    const cx = (Number(state.base_offset_x) || 0)
      + (Number(state.placed_width) || preW) / 2;
    const cy = (Number(state.base_offset_y) || 0)
      + (Number(state.placed_height) || preH) / 2;
    const startY = event.clientY;
    const at = canvasPointOf(event);   // 누른 지점 = 크기의 기준점
    if (rotating) plane?.classList.add('is-rotate');
    const pivot = {x: rect.left + rect.width / 2, y: rect.top + rect.height / 2};
    const angleOf = (ev) => Math.atan2(ev.clientY - pivot.y, ev.clientX - pivot.x) * 180 / Math.PI;
    const startAngle = angleOf(event);
    const startDist = Math.hypot(event.clientX - pivot.x, event.clientY - pivot.y);
    let sent = null;

    posStage.beginFreeDrag(event, host, (ev) => {
      if (rotating) {
        if (startDist < ROTATE_DEAD_ZONE_PX) return;
        const next = wrapDeg(startRotation + (angleOf(ev) - startAngle));
        sent = {key: 'rotation', value: next};
        // 끄는 **한 번**이 한 단계다. 여기서 열어 두면 아래 `applyTransform` 이
        // 프레임마다 불려도 기록은 하나뿐이다(Codex BLOCK 2).
        beginUndoGesture();
        applyTransform('rotation', next);
        // 그림 자체는 서버가 다시 합성해야 돈다(놓을 때 한 번). 끄는 동안에는
        // 유령이 각도를 보여 준다 - 예전에는 슬라이더 숫자만 바뀌고 화면에는
        // 아무 반응이 없었다(사용자 지적 2026-08-27).
        if (ghost && preW > 0 && preH > 0) {
          ghost.hidden = false;
          ghost.style.left = `${(cx / w) * 100}%`;
          ghost.style.top = `${(cy / h) * 100}%`;
          ghost.style.width = `${(preW / w) * 100}%`;
          ghost.style.height = `${(preH / h) * 100}%`;
          ghost.style.transform = `translate(-50%, -50%) rotate(${next}deg)`;
        }
      } else {
        const next = clampPct(startScale + (startY - ev.clientY) / MIDDLE_SCALE_PX_PER_PCT);
        sent = {key: 'scale', value: next};
        applyTransform('scale', next, at);
      }
    }, () => {
      // 제스처가 끝났다 - 다음 조작은 새 단계로 쌓인다.
      endUndoGesture();
      // 놓는 순간 마지막 값을 곧바로 보낸다 - 디바운스가 남아 있으면 거기서 또 간다.
      if (!sent) return;
      if (sent.key === 'scale') sendTransform('base_scale', {value: sent.value / 100, at});
      else sendTransform('base_rotation', {value: sent.value});
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
    plane?.addEventListener('pointerdown', onPlanePointerDown);
    // 슬라이더는 패널 밖에서 손을 떼도 끝난다 - document 에서 받아야 놓치지 않는다.
    document.addEventListener('pointerup', () => { rangeDragging = false; });
    document.addEventListener('pointercancel', () => { rangeDragging = false; });
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
    /** 큰 Generate 버튼이 지나는 문. 도크 버튼과 **같은 함수**다 - 가드도 flush 도
     *  한 자리에 있어야 한 쪽만 빠뜨리는 일이 없다. */
    generate: () => requestGenerate(),
  };
}
