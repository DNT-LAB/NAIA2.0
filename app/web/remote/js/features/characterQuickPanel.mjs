/**
 * 결과 화면 위의 빠른 캐릭터 패널 (`[ ▸ CHARACTER ]`).
 *
 * 왜 있나: Interactive 를 쓰지 않으면 캐릭터를 놓을 자리가 화면에 없었다 —
 * 모듈 팝업을 열어야만 했다(사용자 지적 2026-08-22).
 *
 * 디자인은 Interactive 의 빠른 입력 상자(`.ia-fast-*`)를 그대로 가져왔다:
 * 접힘 = 좁고 반투명, 호버 = 또렷, 펼침 = 폭을 다 쓰고 불투명.
 *
 * ⚠️ Interactive 와 다른 점 둘:
 *   1. 바깥에 겹을 하나 더 둔다. NAI 는 캐릭터가 다섯까지 가므로 그대로 쌓으면
 *      접힌 상태에서도 결과 화면 왼쪽을 세로로 길게 차지한다.
 *   2. 안쪽은 **하나의 그리드**다 - 여러 슬롯을 동시에 펼칠 수 있고 스크롤은
 *      그리드가 통째로 받는다(사용자 지정).
 *
 * ⚠️ Interactive 에서 **반드시 가져와야 하는 두 가지**(주석에 이유가 남아 있다):
 *   · 입력값을 마크업에 넣지 않는다. 렌더 후 `.value` 로 채운다 - 사용자가 적은
 *     `<`·따옴표·줄바꿈이 마크업으로 새지 않게.
 *   · 다시 그릴지 판단하는 서명에 **입력 내용을 넣지 않는다**. 넣으면 한 글자마다
 *     다시 그려 캐럿이 튄다. 구성(누가 있고 무엇이 펼쳐졌나)만 본다.
 */

// 포지티브는 한 줄 더 준다(사용자 지정) - 캐릭터 프롬프트는 보통 네거티브보다 길다.
const MIN_ROWS = {prompt: 4, uc: 2};
// 그리드가 침범하면 안 되는 아래 경계. 결과 정보 패널("GENERATION INFO")이다.
const BOTTOM_ANCHOR = '#resultInfoPanel';
const BOTTOM_GAP = 10;
// 그림을 패널 오른쪽 끝에서 이만큼 띄운다.
const VIEWER_GAP = 8;
// 무대의 최소 크기. 이보다 얕은 뷰어는 POS 편집을 담기엔 너무 작다 - 그때만
// 바닥을 넘고, 넘은 부분은 뷰어가 잘라낸다.
const STAGE_FLOOR = 48;

/** 좁은 화면 판정 - 앱의 기준폭 767px(다른 곳의 미디어쿼리와 한 값). */
function isNarrowViewport() {
  return typeof window !== 'undefined' && !!window.matchMedia
    && window.matchMedia('(max-width: 767px)').matches;
}

// `#주석` 을 연노랑으로 물들이는 층(사용자 지정 2026-10-11) - 워크스페이스와 한 벌을 나눠 쓴다.
import {SESSION_TOKEN, attachSessionKeyGuard} from './sessionKeyGuard.mjs?v=20261019-sk2';
import {paintCommentLayer} from './promptCommentLayer.mjs?v=20261011-cmt5';

export function createCharacterQuickPanel({
  document, escHtml, setModuleParam, onModTextEdit,
  openCharacterModule = () => {},
  getResolution = () => null,      // {w, h} — 지금 설정된 생성 해상도
  // Rnd Res 가 켜져 있는가. 켜져 있으면 해상도가 **매 생성마다 바뀌므로** 좌표를
  // 앉혀 둘 캔버스가 없다 - POS 는 AUTO 로 고정하고 미리보기·편집을 막는다
  // (사용자 지정 2026-08-29: 그리드 비율이 생성마다 널뛰어 원이 거짓말을 했다).
  isRandomResolution = () => false,
  // V5 인페인트 가상 캔버스가 결과 뷰어를 차지하고 있을 때 그 무대의 자리와 크기.
  // {left, top, width, height, w, h} 또는 null.
  //
  // ⚠️ 캔버스가 떠 있는 동안 화면의 그림은 `#preview` 가 **아니다**(그건 숨겨져 있다).
  //    생성 해상도도 파라미터가 아니라 캔버스 크기다. 이걸 모르면 무대가 파라미터
  //    비율로 서서 그림과 어긋난 자리에 원을 놓게 된다
  //    (사용자 제보 2026-08-26: "현재 이미지와 POS 해상도 불일치").
  getCanvasStage = () => null,
  // 가상 캔버스 세션이 **결과 보기**면 편집 모드로 되돌린다. POS 좌표는 "지금 생성할
  // 캔버스" 의 좌표계라, 이미 나온 결과를 보는 화면에서는 얹을 판이 없다.
  //
  // ⚠️ 결과 보기에서는 `renderPlane` 이 평면을 감추므로 `getCanvasStage()` 가 null 을
  //    돌려준다 -> 무대가 옛 폴백(파라미터 해상도 == 화면 그림 크기일 때만 배경을 깜)으로
  //    떨어지는데, 세션 중에는 그 둘이 다르다. 게다가 `is-cq-posedit` 가 결과 이미지를
  //    `opacity:0` 으로 감춰서 **화면이 통째로 검게** 된다(사용자 제보 2026-08-30).
  //    실측(원본 832x1216 · 캔버스 1152x896): overlay=false · background=none ·
  //    무대 비율 1.286 vs 그림 0.684. 편집 모드에서는 overlay=true 로 정상이었다.
  ensureCanvasEditMode = () => {},
  // POS 를 나갈 때 들어오기 전 모드(결과 보기)로 돌려준다.
  restoreCanvasViewMode = () => {},
  bindTagAssist = () => {},        // 태그 자동완성. 모듈 팝업의 캐릭터 칸과 같은 사양
  showToast = () => {},            // 잠긴 조작을 눌렀을 때 이유를 말한다
}) {
  let mount = null;
  let keyGuard = null;               // 랜덤 슬롯 키 지킴이(`sessionKeyGuard.mjs`)
  let open = false;
  const openSlots = new Set();       // 동시에 여러 개 펼칠 수 있다 - Set 이다
  let pendingAddOpen = null;         // + Add 직전의 활성 슬롯 수(에코를 기다린다)
  let lastState = null;
  let lastSignature = '';
  // [Refresh] 를 누르고 결과를 기다리는 슬롯 - {uuid, index, before, at}. 응답(module_state)이
  // 오면 그 슬롯에 뽑힌 값을 툴팁으로 잠깐 보인다(사용자 지정 2026-09-24).
  let pendingRefresh = null;
  let refreshTip = null;
  let refreshTipTimer = null;
  let visible = false;
  let anchorWatcher = null;      // 결과 패널이 늦게 생기면 다시 붙는다
  let stage = null;              // POS 편집 무대(원이 놓이는 판)
  let chips = null;              // 무대 위 캐릭터 칩 줄
  let posEditing = false;
  // POS 버튼에 손을 올린 동안만 배치를 겹쳐 보여 준다(사용자 지정) - 편집에 들어가지
  // 않고 "지금 누가 어디 서 있나" 만 확인하는 자리다.
  let posPeek = false;
  let posSelected = null;        // 칩과 원이 **같은** 선택을 본다
  let stageRect = null;          // 진입 시 한 번 잰 무대 기하
  let posDragging = false;       // 끄는 중에는 다시 그리지 않는다
  // 해상도는 **얼리지 않는다.** 편집 중에 바꾸면 무대가 곧바로 그 비율이 되어야 한다
  // (사용자 제보). 좌표는 0~1 정규화라 비율이 바뀌어도 원은 제자리를 지킨다 - 예전에
  // "편집 중 흔들리지 않게" 라며 진입 시점 값으로 고정했는데, 흔들릴 것이 없었다.
  let stageResWatch = 0;         // 편집 중에만 도는 해상도 감시
  let lastStageResKey = '';

  function host() {
    return document.querySelector('.viewer-wrapper') || document.body;
  }

  // ── POS 편집 무대 ─────────────────────────────────────────────────────
  //
  // 무대는 **좌표계를 보여주는 판**이다. 화면의 그림과 지금 설정한 해상도가 같으면
  // 그림 위에 반투명 검은 판을 덮고, 다르면(옛 그림·비어 있음) 흰 테두리의 검은
  // 상자를 따로 띄운다 - 다른 비율의 그림 위에 원을 놓으면 좌표가 거짓말이 된다.
  //
  // ⚠️ 무대 기하는 **진입 시점에 한 번만** 잰다(사용자 지정). 편집 중에 해상도가
  //    바뀌어도 원이 튀지 않는다.
  function ensureStage() {
    if (stage && document.body.contains(stage)) return stage;
    stage = document.createElement('div');
    stage.className = 'cq-stage';
    stage.addEventListener('pointerdown', onStagePointerDown);
    stage.addEventListener('click', onStageClick);
    host().appendChild(stage);
    return stage;
  }

  /** 무대가 설 자리와 그 종류를 정한다.
   *
   *  ⚠️ 무대를 **그림 위에 얹지 않는다.** 예전에는 해상도가 맞으면 그려진 그림의
   *  사각형을 그대로 무대로 삼았는데, 그러면 무대가 그림의 레이아웃에 묶여
   *  칩 줄이 늘어나도 비켜설 수가 없고, 그림이 조금만 움직여도(밀기·트랜지션·
   *  새 그림) 좌표가 어긋났다. 대신 **남는 자리에 무대를 세우고 그림을 무대의
   *  배경으로 깐다** - 무대 비율이 곧 해상도 비율이라 1:1 로 맞고, 칩이 몇 줄이
   *  되든 자리만 다시 잡으면 된다.
   *
   *  해상도는 **매번 지금 값을 읽는다.** 편집 중에 바꾸면 무대 비율이 곧바로 따라야
   *  한다(사용자 제보: 즉석 변경이 반영되지 않았다). 좌표는 0~1 정규화라 비율이
   *  바뀌어도 원은 제자리를 지킨다.
   *
   *  @param bandBottom 칩 줄이 끝나는 y(뷰포트 기준). 줄이 늘면 무대가 내려간다.
   */
  /** `#preview` 가 **실제로 그리는** 사각형.
   *
   *  ⚠️ 요소 상자가 아니다. `#preview` 는 `width/height: 100%` + `object-fit: contain`
   *     이라 요소는 늘 뷰어를 꽉 채우고 그림만 그 안에서 레터박싱된다 -
   *     `getBoundingClientRect()` 를 그대로 쓰면 무대가 그림보다 훨씬 크게 잡힌다.
   *  ⚠️ 가로 자리는 `object-position` 이 정한다. syncViewerShift 가 넣은
   *     `--cq-img-shift` 로 그림이 오른쪽에 밀려 있을 수 있으니 **가운데라고 가정하지
   *     말고 계산된 값을 읽는다.**
   */
  /** 지금 화면이 실제로 쓰는 생성 해상도. 캔버스가 떠 있으면 그쪽이 이긴다. */
  function resolutionNow() {
    const canvas = getCanvasStage();
    if (canvas && canvas.w > 0 && canvas.h > 0) return {w: canvas.w, h: canvas.h};
    return getResolution();
  }

  function drawnImageRect(img) {
    const box = img.getBoundingClientRect();
    const nw = img.naturalWidth, nh = img.naturalHeight;
    if (!box.width || !box.height || !nw || !nh) return null;
    const scale = Math.min(box.width / nw, box.height / nh);
    const width = nw * scale, height = nh * scale;
    // `50%` 는 "남는 여백의 절반", `124px` 는 "왼쪽에서 124px". 둘 다 온다.
    const at = (raw, slack) => {
      const text = String(raw || '50%');
      const value = parseFloat(text);
      if (!Number.isFinite(value)) return slack / 2;
      return text.endsWith('%') ? slack * (value / 100) : value;
    };
    const parts = String(getComputedStyle(img).objectPosition || '50% 50%').trim().split(/\s+/);
    return {
      left: box.left + at(parts[0], box.width - width),
      top: box.top + at(parts[1], box.height - height),
      width, height,
    };
  }

  function measureStage(bandBottom, snapToImage) {
    // 가상 캔버스가 떠 있으면 **그 무대에 그대로 겹친다.** 따로 상자를 세우면 비율도
    // 자리도 어긋나 원이 그림의 다른 지점을 가리킨다(실측: 무대 1.284 vs 캔버스 0.778).
    const canvas = getCanvasStage();
    if (canvas && canvas.width > 0 && canvas.height > 0) {
      return {left: canvas.left, top: canvas.top, width: canvas.width, height: canvas.height,
              overlay: true, src: ''};
    }
    const res = resolutionNow();
    const img = document.getElementById('preview');
    const shown = !!(img && img.naturalWidth && img.classList.contains('show'));
    // 엿보기는 띠가 없어 **피할 것이 없다** - 그림에 딱 맞춰 얹는다. 따로 계산한
    // 사각형은 비율만 같고 자리가 조금씩 어긋나 "약간 안 맞는" 느낌을 준다(사용자 지적).
    // ⚠️ 비율이 다르면 맞추지 않는다 - 어긋난 그림에 원을 얹으면 좌표가 거짓말이 된다.
    if (snapToImage && shown && res) {
      const drawn = drawnImageRect(img);
      if (drawn && Math.abs(img.naturalWidth / img.naturalHeight - res.w / res.h) < 0.01) {
        // `src` 는 비운다 - 진짜 그림이 이미 뒤에 있으니 다시 깔 이유가 없다
        // (엿보기에는 `is-cq-posedit` 를 안 붙여 원본이 그대로 보인다).
        // `overlay` 는 켠다 - 원이 그림에 묻히지 않게 덮는 층이 필요하다.
        return {...drawn, overlay: true, src: ''};
      }
    }
    // 화면의 그림과 지금 해상도가 같을 때만 그림을 깐다. 비율이 다른 그림 위에
    // 원을 놓으면 좌표가 거짓말이 된다.
    const matches = !!(shown && res
      && img.naturalWidth === res.w && img.naturalHeight === res.h);
    const viewer = document.getElementById('resultViewer');
    if (!viewer) return null;
    const v = viewer.getBoundingClientRect();
    const ratio = res ? res.w / res.h : (shown ? img.naturalWidth / img.naturalHeight : 1);
    const left0 = v.left + 12;
    // ⚠️ 무대는 **늘 띠 아래, 뷰어 안**이다. 자리가 모자라면 작아질 뿐 비켜서지
    //    않는다. 예전에는 120px 을 억지로 확보해 무대가 뷰어 바닥 밖으로
    //    삐져나갔고(Codex 지적), 그렇다고 띠를 덮게 했더니 띠(z 7)가 무대(z 5)보다
    //    위라 **띠에 가린 원을 끌 수가 없었다**(Codex 2차 지적). 작은 무대가 못
    //    끄는 무대보다 낫다.
    const top0 = bandBottom + 8;
    const maxW = Math.max(STAGE_FLOOR, v.right - 12 - left0);
    const maxH = Math.max(STAGE_FLOOR, v.bottom - 12 - top0);
    let w = maxH * ratio;
    let h = maxH;
    if (w > maxW) { w = maxW; h = maxW / ratio; }
    return { left: left0 + (maxW - w) / 2, top: top0 + (maxH - h) / 2,
             width: w, height: h, overlay: matches,
             src: matches ? img.currentSrc || img.src : '' };
  }

  function renderStage() {
    if (posDragging) return;      // 끌고 있는 원을 교체하지 않는다
    if (!posEditing && !posPeek) {
      if (stage) { stage.classList.remove('open', 'is-peek'); stage.innerHTML = ''; }
      if (chips) { chips.classList.remove('open'); chips.innerHTML = ''; }
      return;
    }
    // **엿보기**: POS 버튼에 손을 올린 동안만 배치를 겹쳐 보여 준다(사용자 지정).
    // 편집에 들어가지 않고 "지금 누가 어디 서 있나" 만 확인하는 자리라, 띠도 안 그리고
    // 아무것도 못 누르게 둔다 - 손을 떼면 사라진다.
    const peek = !posEditing;
    const slots = activeSlots(lastState);
    // 줄이 몇 줄이 될지는 그려 봐야 안다 - 띠를 **먼저** 그려 실제 높이를 재고,
    // 무대는 그 아래 남는 자리에 세운다(사용자 지정: 줄이 넘으면 자동 조절).
    // 엿보기에는 띠가 없으므로 뷰어 위쪽에서 바로 시작한다.
    // ⚠️ `is-peek` 를 **재기 전에** 붙인다. 이 클래스가 그림의 `object-position`
    //    트랜지션을 끄는데, 나중에 붙이면 재는 동안엔 아직 트랜지션이 돌고 있어
    //    **움직이는 중인 자리**를 잡는다 - 그 다음 클래스가 붙는 순간 그림만 최종
    //    위치로 튀어 무대가 어긋난 채 남는다(Codex CONCERN 2026-08-25).
    ensureStage();
    stage.classList.toggle('is-peek', peek);
    const viewerBox = document.getElementById('resultViewer')?.getBoundingClientRect();
    const bandBottom = peek ? ((viewerBox ? viewerBox.top : 0) + 4) : renderBand(slots);
    const box = stageRect = measureStage(bandBottom, peek);
    // 잴 자리가 없으면 표식도 거둔다 - 안 그러면 뜨지도 않은 무대 때문에 그림의
    // 트랜지션만 꺼진 채 남는다.
    if (!box) { stage.classList.remove('is-peek'); return; }
    const wrap = host().getBoundingClientRect();
    Object.assign(stage.style, {
      left: Math.round(box.left - wrap.left) + 'px',
      top: Math.round(box.top - wrap.top) + 'px',
      width: Math.round(box.width) + 'px',
      height: Math.round(box.height) + 'px',
      // 무대 비율 = 해상도 비율이므로 100% 100% 가 곧 1:1 대응이다.
      backgroundImage: box.src ? `url("${box.src}")` : '',
    });
    stage.classList.toggle('is-overlay', !!box.overlay);
    stage.classList.toggle('is-peek', peek);
    // 엿보기에서는 격자를 늘 깐다 - 어디쯤인지 가늠할 눈금이 없으면 원만 떠 있어
    // "저게 그림의 어느 지점인가" 를 알 수 없다(사용자가 보여 준 그림도 격자가 있다).
    // ⚠️ 캐릭터가 **1명이면 NAI 가 좌표를 조용히 무시한다**(실측 - `api_service.py`
    //    의 `coords_given` 주석 참조). 화면은 멀쩡히 움직이는데 결과가 안 바뀌니
    //    모르면 "왜 안 먹지" 가 된다(사용자 지정). 엿보기와 편집 **둘 다**에 적는다 -
    //    손을 올렸을 때만 알려 주고 정작 끌 때 입을 다물면 반만 해결한 셈이다.
    //    0명일 때는 안 적는다. 그 문구가 가리키는 상황이 아니고, 빈 무대는 스스로
    //    설명이 된다.
    const lonely = slots.length === 1;
    stage.innerHTML = (peek ? gridSvg(true) : gridSvg())
      + (lonely
        ? '<div class="cq-lonely">캐릭터가 1명일 때는 위치 지정이 적용되지 않습니다.</div>'
        : '')
      + slots.map(({character, index}, i) => {
      const p = character.position || { x: 0.5, y: 0.5 };
      const on = !peek && posSelected === index;
      // 무대의 동그라미도 같이 흐려진다 - 띠만 흐리면 무대에서는 여전히 구분이 안 된다.
      const muted = !!(character && character.muted);
      return `<button type="button" class="cq-dot${on ? ' is-on' : ''}${muted ? ' is-muted' : ''}"`
        + ` data-cq-dot="${index}" style="left:${p.x * 100}%;top:${p.y * 100}%"`
        + ` aria-label="${escHtml(slotLabel(character, i + 1))}">${i + 1}</button>`;
    }).join('');
    stage.classList.add('open');
  }

  // ── POS 격자 ─────────────────────────────────────────────────────────────
  // 64×64 **생성 픽셀** 단위. 중앙을 가로지르는 두 선만 굵고 연한 하늘색이고 나머지는
  // 흰 dash 다(사용자 지정).
  const POS_GRID_STEP = 64;
  const POS_GRID_KEY = 'naia.pos.showgrid.v1';
  let posGrid = (() => {
    try { return localStorage.getItem(POS_GRID_KEY) === '1'; } catch (_) { return false; }
  })();

  /** 무대에 깔 격자.
   *
   *  ⚠️ SVG 로 그린다. dash 격자를 `repeating-linear-gradient` 로 만들려면 축마다
   *     겹겹이 쌓아야 하고 중앙선만 다르게 하기가 사실상 불가능하다.
   *  ⚠️ `viewBox` 를 **해상도 그대로** 잡아 64 단위가 곧 생성 픽셀 64 가 되게 한다.
   *     대신 선은 그만큼 얇아지므로 `vector-effect: non-scaling-stroke` 로 굵기와
   *     dash 간격을 화면 픽셀에 고정한다 - 안 하면 무대가 작을수록 선이 사라진다.
   */
  /** `force` 면 Show Grid 설정과 무관하게 그린다 - 엿보기에는 눈금이 있어야
   *  원이 그림의 어느 지점인지 읽힌다(사용자 지정). */
  function gridSvg(force) {
    if (!posGrid && !force) return '';
    const res = resolutionNow();
    const w = Number(res?.w) > 0 ? Math.trunc(res.w) : 0;
    const h = Number(res?.h) > 0 ? Math.trunc(res.h) : 0;
    if (!w || !h) return '';        // 해상도를 모르면 격자의 뜻이 없다
    const cx = w / 2, cy = h / 2;
    return `<svg class="cq-posgrid" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" aria-hidden="true">`
      + `<defs><pattern id="cqGridCell" width="${POS_GRID_STEP}" height="${POS_GRID_STEP}"`
      + ` patternUnits="userSpaceOnUse">`
      + `<path d="M ${POS_GRID_STEP} 0 L 0 0 0 ${POS_GRID_STEP}" class="cq-posgrid-line"/>`
      + `</pattern></defs>`
      + `<rect width="${w}" height="${h}" fill="url(#cqGridCell)"/>`
      + `<line x1="${cx}" y1="0" x2="${cx}" y2="${h}" class="cq-posgrid-mid"/>`
      + `<line x1="0" y1="${cy}" x2="${w}" y2="${cy}" class="cq-posgrid-mid"/>`
      + `</svg>`;
  }

  function setPosGrid(on) {
    posGrid = !!on;
    try { localStorage.setItem(POS_GRID_KEY, posGrid ? '1' : '0'); } catch (_) {}
    renderStage();
  }

  /** 무대 위 띠: 종료 버튼 + 캐릭터 칩. 칩은 자리가 모자라면 줄을 바꾼다.
   *
   *  종료 버튼은 **두 줄 높이**로 세워 띠의 세로를 놀리지 않는다(사용자 지정).
   *  띠는 뷰어 폭을 다 쓰므로 캐릭터가 늘어도 옆으로 퍼지다 아래로 접힌다.
   *
   *  @return 띠가 끝나는 y(뷰포트 기준) - 무대가 그 아래에 선다.
   */
  function renderBand(slots) {
    if (!chips || !document.body.contains(chips)) {
      chips = document.createElement('div');
      chips.className = 'cq-chips';
      chips.addEventListener('click', event => {
        if (event.target.closest('[data-cq-posdone]')) { setPosEditing(false); return; }
        if (event.target.closest('[data-cq-grid]')) { setPosGrid(!posGrid); return; }
        const chip = event.target.closest('[data-cq-chip]');
        if (!chip) return;
        posSelected = Number(chip.dataset.cqChip);
        renderStage();
      });
      host().appendChild(chips);
    }
    const viewer = document.getElementById('resultViewer');
    const v = viewer ? viewer.getBoundingClientRect() : host().getBoundingClientRect();
    const wrap = host().getBoundingClientRect();
    chips.style.left = Math.round(v.left + 12 - wrap.left) + 'px';
    chips.style.top = Math.round(v.top + 8 - wrap.top) + 'px';
    chips.style.width = Math.round(v.width - 24) + 'px';
    chips.innerHTML =
      `<button type="button" class="cq-posdone" data-cq-posdone="1">`
      + `<span>Finish</span><span>Editing POS</span></button>`
      + `<div class="cq-chiprow">`
      // 격자 토글은 **칩 줄의 맨 앞**에 둔다. 종료 버튼은 두 줄 높이라 그 옆에 붙이면
      // 세로 가운데가 안 맞고, 칩과 같은 줄에 두면 자리가 모자랄 때 함께 접힌다.
      + `<button type="button" class="cq-gridtoggle${posGrid ? ' is-on' : ''}" data-cq-grid="1"`
      + ` aria-pressed="${posGrid ? 'true' : 'false'}">`
      + `<span class="cq-gridtoggle-box">${posGrid ? '&#10003;' : ''}</span>`
      + `<span>Show Grid</span></button>`
      // 끈 슬롯(`is-muted`)도 띠에 남는다 - 자리는 그대로 두고 좌표만 못 옮기게 하는
      // 것이 아니라, 이번 생성에 안 나갈 뿐이라 어디 서 있었는지는 보여야 한다.
      // 다만 **켠 것과 구분이 안 되면** 안 나갈 인물을 옮기며 시간을 쓴다(사용자 제보).
      + slots.map(({character, index}, i) =>
          `<button type="button" class="cq-chip${posSelected === index ? ' is-on' : ''}`
          + `${character && character.muted ? ' is-muted' : ''}"`
          + ` data-cq-chip="${index}"><span class="cq-chip-n">${i + 1}</span>`
          + `<span class="cq-chip-t">${escHtml(slotLabel(character, i + 1).replace(/^C\d+\s*·\s*/, '') || '(비어 있음)')}</span></button>`
        ).join('')
      + `</div>`;
    chips.classList.add('open');
    return chips.getBoundingClientRect().bottom;
  }

  function onStageClick(event) {
    const dot = event.target.closest('[data-cq-dot]');
    if (dot) { posSelected = Number(dot.dataset.cqDot); renderStage(); }
  }

  function onStagePointerDown(event) {
    const dot = event.target.closest('[data-cq-dot]');
    if (!dot) return;
    event.preventDefault();
    const index = Number(dot.dataset.cqDot);
    posSelected = index;
    // ⚠️ 진입 때 잰 `stageRect` 로 계산하면 안 된다. 그건 무대를 **놓을 자리**를
    //    정한 값(뷰포트 기준)이고, 그 뒤 스크롤이나 레이아웃 변화가 생기면 실제
    //    무대와 어긋난다 - 놓는 순간 원이 엉뚱한 자리로 갔다(사용자 제보).
    //    포인터 계산은 **살아 있는 무대**를 그때그때 재서 한다.
    //    원의 %는 테두리 안쪽(패딩 상자) 기준이므로 그 상자로 재야 1:1로 맞는다.
    const rectNow = () => {
      const r = stage.getBoundingClientRect();
      const bw = parseFloat(getComputedStyle(stage).borderLeftWidth) || 0;
      return { left: r.left + bw, top: r.top + bw,
               width: Math.max(1, r.width - bw * 2), height: Math.max(1, r.height - bw * 2) };
    };
    const move = (e) => {
      const box = rectNow();
      const x = Math.min(1, Math.max(0, (e.clientX - box.left) / box.width));
      const y = Math.min(1, Math.max(0, (e.clientY - box.top) / box.height));
      dot.style.left = (x * 100) + '%';
      dot.style.top = (y * 100) + '%';
      dot.dataset.cqX = x.toFixed(3);
      dot.dataset.cqY = y.toFixed(3);
    };
    const up = () => {
      posDragging = false;
      document.removeEventListener('pointermove', move);
      document.removeEventListener('pointerup', up);
      document.removeEventListener('pointercancel', up);
      // 즉시 저장(사용자 확인 - 공식 홈페이지도 그렇다). 놓는 순간 한 번만 보낸다 -
      // 끌 때마다 보내면 한 번의 드래그가 수십 번의 왕복이 된다.
      if (dot.dataset.cqX !== undefined) {
        const x = Number(dot.dataset.cqX);
        const y = Number(dot.dataset.cqY);
        // ⚠️ 화면을 **먼저** 새 값으로 맞춘다. 서버 echo 가 오기까지 한 박자가 있는데,
        //    그 사이에 무엇이든 다시 그리면 원이 옛 자리로 튀었다가 돌아온다
        //    (실측: 연달아 끌면 매번 직전 좌표가 보였다).
        const character = (lastState && lastState.characters || [])[index];
        if (character) character.position = { x, y };
        setModuleParam('character', `char_pos_${index}`, `${x},${y}`);
      }
      dot.classList.remove('is-drag');
    };
    // ⚠️ 여기서 다시 그리면 **끌고 있던 원이 교체돼** 참조가 끊긴다(실측: 드래그가
    //    통째로 무시됐다). 선택 표시는 클래스만 손으로 바꾸고, 드래그가 끝날 때까지
    //    renderStage 를 막는다(서버 echo 가 와도 마찬가지다).
    posDragging = true;
    stage.querySelectorAll('.cq-dot.is-on').forEach(e => e.classList.remove('is-on'));
    dot.classList.add('is-on', 'is-drag');
    if (chips) {
      chips.querySelectorAll('.cq-chip.is-on').forEach(e => e.classList.remove('is-on'));
      const chip = chips.querySelector(`[data-cq-chip="${index}"]`);
      if (chip) chip.classList.add('is-on');
    }
    document.addEventListener('pointermove', move);
    document.addEventListener('pointerup', up);
    document.addEventListener('pointercancel', up);
  }

  function resKey() {
    const res = resolutionNow();
    return res ? `${res.w}x${res.h}` : '';
  }

  /** 편집 중에만 해상도를 지켜본다.
   *
   *  ⚠️ **이벤트로는 못 잡는다.** 해상도가 바뀌는 길이 여럿이다 - 커스텀 셀렉트,
   *  `Rnd Res`, `Auto Res`, 프리셋, 서버 에코. 그중 하나만 놓쳐도 무대가 옛 비율에
   *  굳는다(사용자 제보: 즉석 변경이 반영 안 됨). 값 하나를 비교하는 쪽이 확실하다.
   *  편집을 끝내면 멈추므로 상시 비용은 없다.
   */
  function startStageResWatch() {
    stopStageResWatch();
    lastStageResKey = resKey();
    stageResWatch = setInterval(() => {
      const now = resKey();
      if (now === lastStageResKey) return;
      lastStageResKey = now;
      renderStage();
    }, 350);
  }

  function stopStageResWatch() {
    if (stageResWatch) { clearInterval(stageResWatch); stageResWatch = 0; }
    lastStageResKey = '';
  }

  /** POS 버튼 hover 엿보기를 켜고 끈다.
   *
   * ⚠️ 편집 중에는 아무것도 하지 않는다 - 이미 무대가 떠 있고, 엿보기가 끼어들면
   *    골라 둔 원의 선택이 풀린다.
   */
  function setPosPeek(on) {
    // Rnd Res 중에는 엿보기도 막는다 - 지금 해상도로 그린 무대는 다음 생성과 무관하다.
    const next = !!on && !posEditing && !posBlockedByRandom();
    if (posPeek === next) return;
    posPeek = next;
    renderStage();
  }

  function setPosEditing(on) {
    // 켜는 방향만 막는다. **끄는 방향은 늘 통과시켜야** 한다 - 편집 중에 Rnd Res 를
    // 켜면 여기로 나가야 하는데 막으면 무대에 갇힌다.
    if (on && posBlockedByRandom()) {
      showToast('Rnd Res 중에는 POS 편집이 잠깁니다 (해상도가 매 생성마다 바뀝니다)', 'info');
      return;
    }
    // ⚠️ **무대를 재기 전**에 편집 모드로 돌려놓는다. 순서가 뒤집히면 평면이 아직
    //    감춰진 채로 재서 폴백 경로로 떨어진다(그게 곧 검은 화면이다).
    if (on) { try { ensureCanvasEditMode(); } catch (_) { /* 화면 전환 실패가 POS 를 막으면 안 된다 */ } }
    else { try { restoreCanvasViewMode(); } catch (_) { /* 위와 같다 */ } }
    posEditing = !!on;
    if (posEditing) posPeek = false;
    if (posEditing) {
      posSelected = null;
      stageRect = null;
      startStageResWatch();
    } else {
      stageRect = null;
      stopStageResWatch();
      if (chips) { chips.classList.remove('open'); chips.innerHTML = ''; }
    }
    const viewer = document.getElementById('resultViewer');
    if (viewer) viewer.classList.toggle('is-cq-posedit', posEditing);
    if (mount) mount.classList.toggle('open', visible && !posEditing);
    render(lastState, true);
    renderStage();
    // 진입 직후 한 번 더 잰다. 이 렌더가 패널 높이·이미지 밀기를 바꾸므로 그
    // 결과가 레이아웃에 반영된 **다음 프레임**의 자리가 진짜다.
    if (posEditing) requestAnimationFrame(() => renderStage());
  }

  function ensureMount() {
    if (mount && document.body.contains(mount)) return mount;
    mount = document.createElement('div');
    mount.className = 'cq-float';
    // ⚠️ 포커스를 뺏지 않는다. 상자 안을 누르면 편집 중인 칸이 blur 되어
    //    입력이 커밋되고 다시 그려진다 - 캐럿이 튄다.
    //
    // ⚠️ 다만 **폼 컨트롤은 빼야 한다.** `preventDefault()` 는 네이티브 select 의
    //    드롭다운이 열리는 것까지 막는다 - 호버 툴팁은 뜨는데 눌러도 아무 일이
    //    없어서 "버튼이 고장났다" 로 보인다(사용자 제보: Connect 가 안 눌림).
    //    예외는 **select 까지만** 넓힌다. 체크박스(활성화)는 preventDefault 로도
    //    정상 동작하므로 넣을 이유가 없고, 넣으면 포커스를 뺏어 위 규칙을 깬다.
    mount.addEventListener('mousedown', event => {
      if (!event.target.closest('textarea, select')) event.preventDefault();
    });
    mount.addEventListener('click', onClick);
    // 랜덤 슬롯 칸의 `__키__` 를 지킨다(공용 - Manage 창도 같은 것을 쓴다). 되돌리면 서버에도 되돌린 글을 보낸다.
    keyGuard = attachSessionKeyGuard(mount, {
      tokenOf: element => element.dataset.cqLock || '',
      serverText: element => ((lastState && lastState.characters) || [])
        .find(character => character && character.slot_uuid === element.dataset.cqUuid)?.prompt || '',
      onRevert: element => onModTextEdit('character', element.dataset.cqField, element.value, element.dataset.cqUuid || ''),
      toast: message => showToast(message, 'info'),
    });
    mount.addEventListener('input', onInput);
    // POS 버튼 hover 엿보기(사용자 지정). ⚠️ `mouseover`/`mouseout` 을 쓴다 -
    // `mouseenter` 는 버블링이 없어 위임이 안 되는데, 이 버튼은 다시 그릴 때마다 새
    // 요소가 되므로 위임이 아니면 매 렌더마다 다시 걸어야 한다.
    mount.addEventListener('mouseover', event => {
      if (event.target.closest?.('[data-cq-posedit]')) setPosPeek(true);
    });
    mount.addEventListener('mouseout', event => {
      if (!event.target.closest?.('[data-cq-posedit]')) return;
      // 버튼 **안에서** 자식으로 옮겨 다니는 것은 나간 것이 아니다.
      if (event.relatedTarget?.closest?.('[data-cq-posedit]')) return;
      setPosPeek(false);
    });
    // 강조 미러는 textarea 와 같이 스크롤해야 한다. `scroll` 은 버블링하지 않으므로
    // **캡처 단계**로 받는다 - 안 그러면 긴 프롬프트에서 띠가 글자와 어긋난다.
    mount.addEventListener('scroll', event => {
      const element = event.target;
      if (element && element.dataset && element.dataset.cqField) paintConnectHighlight(element);
    }, true);
    host().appendChild(mount);
    // ⚠️ 지금까지의 가시성을 **새 요소에 다시 입힌다.** `setVisible` 은 mount 가
    //    없으면 아무것도 못 하고 플래그만 남긴다 - 초기화 순서에 따라
    //    `setVisible(true)` 가 먼저 오면 이 요소는 `.open` 없이 태어나 영영
    //    display:none 이었다(사용자 인스턴스에서 실측: DOM 에는 있는데 0x0).
    mount.classList.toggle('open', visible);
    return mount;
  }

  /** 활성 슬롯만. 인덱스는 **전체 배열 기준**이다 - set_param 이 그걸로 주소 지정한다. */
  function activeSlots(state) {
    const chars = (state && state.characters) || [];
    return chars
      .map((character, index) => ({character, index}))
      .filter(item => item.character && item.character.active);
  }

  // ── Connect 공유 구간 마커 ───────────────────────────────────────────────
  // 백엔드 `core/character_settings._split_connect_region` 과 **같은 정규식**이어야
  // 한다. 화면이 칠해 주는 구간과 실제로 물려주는 구간이 다르면, 이 강조는 가르치는
  // 것이 아니라 속이는 것이 된다.
  const CONNECT_OPEN_RE = /&connect\s*:?/i;
  const CONNECT_CLOSE_RE = /&end/i;

  // 이 모듈은 `escHtml` 만 주입받는다. 속성값에는 따옴표까지 막아야 하므로 따로 둔다
  // (slot_uuid 는 hex 라 지금은 안전하지만, 값의 출처를 믿고 짜면 언젠가 틀린다).
  function escAttr(value) {
    return String(value ?? '').replace(/[&<>"']/g, char => (
      {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[char]
    ));
  }

  /** `{head, openTok, shared, closeTok, tail}` 또는 마커가 없으면 null. */
  function connectParts(text) {
    const source = String(text || '');
    const opened = source.match(CONNECT_OPEN_RE);
    if (!opened) return null;
    const head = source.slice(0, opened.index);
    const openTok = opened[0];
    const rest = source.slice(opened.index + openTok.length);
    const closed = rest.match(CONNECT_CLOSE_RE);
    if (!closed) return {head, openTok, shared: rest, closeTok: '', tail: ''};
    return {
      head, openTok,
      shared: rest.slice(0, closed.index),
      closeTok: closed[0],
      tail: rest.slice(closed.index + closed[0].length),
    };
  }

  /** 태그 경계 구간 `[start, end)` 목록.
   *
   *  ⚠️ 백엔드 `split_tags_smart` 와 **같은 규칙**이어야 한다 — `<...>` 안의 쉼표는
   *     경계가 아니고, 닫히지 않은 `<` 는 뒤를 삼킨다. 여기서 규칙이 갈리면 화면이
   *     빼기로 칠한 것이 실제로는 안 빠진다(가르치는 게 아니라 속이는 것이 된다).
   *  글자를 자르지 않고 **구간만** 낸다 — 미러는 원문과 한 글자도 달라선 안 된다. */
  function tagRanges(text) {
    const out = [];
    let depth = 0, start = 0;
    for (let i = 0; i < text.length; i++) {
      const ch = text[i];
      if (ch === '<') depth++;
      else if (ch === '>') depth = Math.max(0, depth - 1);
      else if (ch === ',' && depth === 0) { out.push([start, i]); start = i + 1; }
    }
    out.push([start, text.length]);
    return out;
  }

  /** 한 토막 안의 `-태그` 를 감싼다. 나머지는 원문 그대로.
   *  백엔드 `_apply_minus_tags` 와 같은 판정: 맨 앞이 `-` 이고 `::` 가 없을 것. */
  function minusHtml(text) {
    let out = '', cursor = 0, hit = false;
    for (const [start, end] of tagRanges(text)) {
      out += escHtml(text.slice(cursor, start));
      const piece = text.slice(start, end);
      const lead = piece.match(/^\s*/)[0];
      const core = piece.slice(lead.length).replace(/\s+$/, '');
      const trail = piece.slice(lead.length + core.length);
      if (core.length > 1 && core.startsWith('-') && !core.includes('::')) {
        out += escHtml(lead) + `<span class="cq-hl-minus">${escHtml(core)}</span>` + escHtml(trail);
        hit = true;
      } else {
        out += escHtml(piece);
      }
      cursor = end;
    }
    out += escHtml(text.slice(cursor));
    return {html: out, hit};
  }

  /** 미러에 칠할 HTML. 칠할 것이 없으면 빈 문자열(강조를 아예 걸지 않는다).
   *  @param minus 이 슬롯에서 `-태그` 가 빼기로 동작하는가(= 연결된 슬롯인가). */
  function connectHighlightHtml(text, minus) {
    const paint = segment => (minus ? minusHtml(segment) : {html: escHtml(segment), hit: false});
    const parts = connectParts(text);
    if (!parts) {
      // 구간 마커가 없어도 `-태그` 는 칠한다. 둘 다 없으면 아무것도 하지 않는다.
      const whole = paint(text);
      return whole.hit ? whole.html : '';
    }
    const head = paint(parts.head), shared = paint(parts.shared), tail = paint(parts.tail);
    return head.html
      + `<span class="cq-hl-mark">${escHtml(parts.openTok)}</span>`
      + `<span class="cq-hl-share">${shared.html}</span>`
      + (parts.closeTok ? `<span class="cq-hl-mark">${escHtml(parts.closeTok)}</span>` : '')
      + tail.html;
  }

  /** 이 칸이 속한 슬롯이 연결돼 있나 — `-태그` 가 빼기로 동작하는 조건이다. */
  function fieldIsLinked(element) {
    const match = String(element?.dataset?.cqField || '').match(/^char_(?:prompt|uc)_(\d+)$/);
    if (!match) return false;
    const character = ((lastState && lastState.characters) || [])[Number(match[1])];
    return !!(character && String(character.connect_to || ''));
  }

  /** 칸 하나의 강조를 다시 칠한다.
   *
   *  ⚠️ 미러는 글자를 **투명**으로 그리고 배경만 남긴다. 글자까지 그리면 아래
   *     textarea 의 글자와 겹쳐 이중으로 보이고, 그러려면 textarea 글자를 투명하게
   *     해야 하는데 그러면 이 코드가 한 번이라도 실패했을 때 칸이 통째로 비어 보인다.
   *     배경만 칠하면 최악의 경우가 "강조가 안 보인다" 로 끝난다.
   *  ⚠️ 칠할 것이 없으면 미러를 비운다 - 이 기능을 안 쓰는 사용자에게는 아무 일도
   *     일어나지 않는다. */
  function paintConnectHighlight(element) {
    const wrap = element && element.parentElement;
    if (!wrap || !wrap.classList.contains('cq-input-wrap')) return;
    // `#주석` 층도 같은 때에 다시 칠한다 - 글자를 칠 때 · 서버 값이 올 때 · 스크롤할 때가 전부 이 함수로 온다.
    paintCommentLayer(element, escHtml);
    const mirror = wrap.querySelector('.cq-hl');
    if (!mirror) return;
    const html = connectHighlightHtml(element.value, fieldIsLinked(element));
    if (mirror.innerHTML !== html) mirror.innerHTML = html;
    wrap.classList.toggle('has-hl', !!html);
    mirror.scrollTop = element.scrollTop;
  }

  function paintAllConnectHighlights() {
    mount?.querySelectorAll('.cq-input-wrap > [data-cq-field]')
      .forEach(element => paintConnectHighlight(element));
  }

  /** Connect 드롭다운. **자기보다 앞선 활성 슬롯만** 후보다(사용자 지정).
   *  그 제약이 곧 안전장치다 - 백엔드 전개 루프가 활성 프레임을 화면 순서대로 한 번
   *  훑으므로, 앞만 가리키면 참조 시점에 값이 이미 확정돼 있고 순환이 생길 수 없다.
   *  값은 표시 번호가 아니라 **slot_uuid** 다 - 번호는 ▼·비활성화로 밀린다. */
  function connectControl(character, index, ordinal, slots) {
    if (ordinal <= 1) return '';
    // ⚠️ **원본 역할인 슬롯에는 Connect 를 주지 않는다.** 주면 C3→C2 를 걸어 둔 뒤
    //    C2→C1 을 걸 수 있고, 그 순간 사슬 금지 규칙에 걸려 C3 의 링크가 조용히
    //    사라진다(백엔드 `_prune_character_links`). 애초에 고를 수 없게 해서 그
    //    상황을 만들지 않는다 — 슬롯은 원본이거나 대상이거나 둘 다 아니거나 셋 중
    //    하나다. 이 자리에는 `⇩N` 원본 배지가 이미 서서 역할을 말한다.
    const uuid = String(character.slot_uuid || '');
    if (uuid && slots.some(item => String(item.character.connect_to || '') === uuid)) return '';
    const current = String(character.connect_to || '');
    const on = !!current;
    const sourceOrdinal = slots.findIndex(item => String(item.character.slot_uuid || '') === current) + 1;
    // ⚠️ 원본이 꺼져 있으면 백엔드 전개 대상에서 빠져 **아무것도 물려받지 못한다**.
    //    보통은 원본을 끄면 자식도 함께 꺼지므로(사용자 지정, `_connected_children`)
    //    이 상태가 잘 안 생기지만, 남아 있는 옛 저장본이나 다른 경로로 어긋날 수 있다.
    //    **자식이 켜져 있을 때만** 경고한다 - 둘 다 꺼져 있으면 아무 일도 안 일어나는데
    //    경고를 띄우면 그게 더 헷갈린다(Codex 리뷰 2026-08-24 #2).
    const sourceItem = sourceOrdinal ? slots[sourceOrdinal - 1] : null;
    const broken = on && !character.muted && (!sourceItem || !!sourceItem.character.muted);
    const label = on
      ? `${broken ? '&#9888;' : '&#128279;'} C${sourceOrdinal || '?'}`
      : '&#8681; Connect';
    // ⚠️ 네이티브 `<select>` 를 쓰지 않는다. 드롭다운 팝업은 OS 가 그려서 스타일이
    //    전혀 안 먹고(사용자 지적: "못생김"), 앱의 커스텀 select 위젯은 17px 칩에
    //    들어갈 폭이 아니다. Tag Filter 팝업과 같은 결의 작은 메뉴를 직접 띄운다.
    const guide = !on
      ? '앞선 슬롯의 캐릭터를 그대로 물려받습니다.\\n와일드카드도 같은 값이 옵니다.\\n\\n연결하면 원본에 &connect: … &end 가 자동으로 붙습니다. &end 를 앞으로 당기면 그만큼만 물려줍니다.'
      : broken
        ? `원본 C${sourceOrdinal || '?'} 이(가) 꺼져 있어 **아무것도 물려받지 못합니다**.\\n원본의 ✔ 를 다시 켜거나 연결을 바꾸세요.`
        : `C${sourceOrdinal || '?'} 의 캐릭터를 물려받는 중입니다.\\n아래 두 칸은 '추가할' 칸입니다.\\n\\n물려받는 범위는 C${sourceOrdinal || '?'} 의 &connect: … &end 구간이 정합니다.\\n\\n-태그 를 적으면 그 태그를 빼고 물려받습니다.`;
    return `<button type="button" class="cq-connect${on ? ' is-on' : ''}${broken ? ' is-broken' : ''}"`
      + ` data-cq-connect="${index}" aria-haspopup="listbox" aria-expanded="false"`
      + ` data-naia-guide="${guide}">`
      + `<span class="cq-connect-tag">${label}</span></button>`;
  }

  // ── Connect 메뉴 ─────────────────────────────────────────────────────────
  // Tag Filter 팝업과 같은 결(`--bg-surface` + `--border-glow` + 큰 그림자).
  //
  // ⚠️ **body 에 붙이고 fixed 로 놓는다.** 칩은 `.cq-slot-headrow` 안에 있고 그 조상
  //    (`.cq-box`)이 스크롤 상자라, 안에 그리면 메뉴가 잘리거나 같이 스크롤된다.
  let connectMenuEl = null;
  let connectMenuDismiss = null;
  // 열려 있는 칩을 다시 누르면 **닫히고 끝나야 한다.** 바깥 클릭 해제(capture mousedown)가
  // 먼저 닫고 그 뒤 click 이 다시 열어 "안 닫힌다" 로 보인다 - 방금 이 칩 때문에 닫혔다는
  // 사실을 한 클릭 동안만 기억해 재열기를 막는다.
  let connectMenuClosedFrom = null;

  function closeConnectMenu() {
    if (connectMenuDismiss) {
      document.removeEventListener('mousedown', connectMenuDismiss, true);
      document.removeEventListener('keydown', connectMenuDismiss, true);
      window.removeEventListener('resize', connectMenuDismiss, true);
      window.removeEventListener('scroll', connectMenuDismiss, true);
      connectMenuDismiss = null;
    }
    connectMenuEl?.remove();
    connectMenuEl = null;
    mount?.querySelectorAll('[data-cq-connect]').forEach(el => {
      el.classList.remove('is-menu-open');
      el.setAttribute('aria-expanded', 'false');
      // 열 때 떼어 둔 안내문을 돌려준다(아래 `openConnectMenu` 참조).
      if (el.dataset.cqGuideStash !== undefined) {
        el.dataset.naiaGuide = el.dataset.cqGuideStash;
        delete el.dataset.cqGuideStash;
      }
    });
  }

  function openConnectMenu(button, index) {
    closeConnectMenu();
    const slots = activeSlots(lastState);
    const ordinal = slots.findIndex(item => item.index === index) + 1;
    if (ordinal <= 1) return;
    const current = String(slots[ordinal - 1]?.character.connect_to || '');
    const row = (value, main, sub, on) =>
      `<button type="button" class="cq-connect-item${on ? ' is-on' : ''}" role="option"`
      + ` aria-selected="${on ? 'true' : 'false'}" data-cq-pick="${escAttr(value)}">`
      + `<b>${escHtml(main)}</b>${sub ? `<span>${escHtml(sub)}</span>` : ''}</button>`;

    connectMenuEl = document.createElement('div');
    connectMenuEl.className = 'cq-connect-menu';
    connectMenuEl.setAttribute('role', 'listbox');
    connectMenuEl.innerHTML =
      `<div class="cq-connect-menu-head">물려받을 슬롯</div>`
      + row('', '연결 없음', '이 슬롯만의 캐릭터', !current)
      + slots.slice(0, ordinal - 1).map((item, i) => {
          const uuid = String(item.character.slot_uuid || '');
          // ⚠️ **이미 남을 물고 있는 슬롯은 후보가 아니다**(사용자 지정: 사슬 금지).
          //    C3→C2→C1 이 되면 C3 가 무엇을 물려받는지가 C2 의 구간 설정에까지
          //    달려 있어 화면만 보고 결과를 예측할 수 없다. 백엔드도 같은 규칙으로
          //    막지만(`_prune_character_links`), 고를 수 없어야 헛클릭이 없다.
          if (String(item.character.connect_to || '')) return '';
          // 꺼진 슬롯(✘)도 후보가 아니다 - 물려받아도 아무것도 안 온다(위 `broken` 참조).
          if (item.character.muted) return '';
          const name = String(item.character.custom_name || '').trim();
          const hint = name || String(item.character.prompt || '')
            .replace(CONNECT_OPEN_RE, '').replace(CONNECT_CLOSE_RE, '')
            .split(',').map(part => part.trim()).filter(Boolean).slice(0, 2).join(', ');
          return row(uuid, `C${i + 1}`, hint || '(비어 있음)', uuid === current);
        }).join('');
    document.body.appendChild(connectMenuEl);
    button.classList.add('is-menu-open');
    button.setAttribute('aria-expanded', 'true');
    // ⚠️ 가이드 툴팁을 내린다. 사용자는 칩에 손을 올려 설명을 읽고 그대로 누르는데,
    //    그러면 열린 툴팁이 **메뉴를 통째로 덮는다**(실측). 앱의 툴팁은 `pointerout`
    //    에 닫히므로 그 계약으로 내리고, 메뉴가 떠 있는 동안은 안내문을 아예 떼어
    //    다시 뜨지 못하게 한다(메뉴 자체가 이미 설명을 담고 있다).
    //    ⚠️ **순서가 중요하다.** 앱의 핸들러는 `closest('[data-naia-guide]')` 로 대상을
    //       찾으므로, 속성을 먼저 지우면 아무것도 못 찾고 툴팁이 그대로 남는다(실측).
    //       내리고 나서 뗀다.
    button.dispatchEvent(new PointerEvent('pointerout', {bubbles: true, relatedTarget: null}));
    if (button.dataset.naiaGuide !== undefined) {
      button.dataset.cqGuideStash = button.dataset.naiaGuide;
      delete button.dataset.naiaGuide;
    }

    const rect = button.getBoundingClientRect();
    const mw = connectMenuEl.offsetWidth, mh = connectMenuEl.offsetHeight;
    const margin = 6;
    // 칩의 **오른쪽 끝**에 맞춘다 - 칩이 줄 오른쪽에 있어 왼쪽 정렬하면 화면 밖으로 샌다.
    let left = Math.max(margin, Math.min(rect.right - mw, window.innerWidth - mw - margin));
    let top = rect.bottom + 4;
    if (top + mh > window.innerHeight - margin) top = Math.max(margin, rect.top - mh - 4);
    connectMenuEl.style.left = `${Math.round(left)}px`;
    connectMenuEl.style.top = `${Math.round(top)}px`;

    connectMenuEl.addEventListener('click', event => {
      const pick = event.target.closest('[data-cq-pick]');
      if (!pick) return;
      closeConnectMenu();
      setModuleParam('character', `char_connect_${index}`, pick.dataset.cqPick);
    });

    connectMenuDismiss = event => {
      if (event.type === 'keydown' && event.key !== 'Escape') return;
      if (event.type === 'mousedown' && connectMenuEl?.contains(event.target)) return;
      if (event.type === 'mousedown') {
        connectMenuClosedFrom = event.target?.closest?.('[data-cq-connect]') || null;
      }
      closeConnectMenu();
    };
    document.addEventListener('mousedown', connectMenuDismiss, true);
    document.addEventListener('keydown', connectMenuDismiss, true);
    window.addEventListener('resize', connectMenuDismiss, true);
    window.addEventListener('scroll', connectMenuDismiss, true);
  }

  /** 이 슬롯을 물려받는 슬롯 수. 원본에는 Connect 드롭다운이 없어(앞을 가리킬 대상이
   *  없다) 자기가 원본이라는 사실을 알 길이 없었다. 구간 마커를 쓰는 자리도 원본이다. */
  function connectSourceBadge(character, slots) {
    const uuid = String(character.slot_uuid || '');
    if (!uuid) return '';
    const takers = slots.filter(item => String(item.character.connect_to || '') === uuid).length;
    if (!takers) return '';
    const hasRegion = CONNECT_OPEN_RE.test(String(character.prompt || '') + String(character.uc || ''));
    return `<span class="cq-source${hasRegion ? ' has-region' : ''}">&#8681;${takers}</span>`;
  }

  /** 한 줄 라벨. 이름이 있으면 이름, 없으면 프롬프트 앞 태그. */
  /** 한 줄 라벨. 이름이 있으면 이름, 없으면 프롬프트 앞 태그.
   *
   *  연결된 슬롯은 `C2 · C1 + smile` 로 쓴다(사용자 지정). 자기가 적은 것만 보여 주면
   *  접힌 상태에서 **몸통이 어디서 오는지가 화면에서 사라진다** — 그 슬롯의 결과는
   *  대부분 물려받은 쪽이다.
   *
   *  @param sourceOrdinal 물려받는 원본의 1-based 번호(없으면 0).
   */
  function slotLabel(character, ordinal, sourceOrdinal = 0) {
    const tag = 'C' + ordinal;
    const lead = sourceOrdinal ? `${tag} · C${sourceOrdinal}` : tag;
    const custom = String(character.custom_name || '').trim();
    if (custom) return sourceOrdinal ? `${lead} + ${custom}` : `${tag} · ${custom}`;
    // 마커는 이름이 아니다. 안 걷어내면 접힌 슬롯이 `C1 · &connect: girl` 이 되어
    // 정작 구분에 필요한 태그 한 칸을 문법이 잡아먹는다(실측).
    const first = String(character.prompt || '')
      .replace(CONNECT_OPEN_RE, '').replace(CONNECT_CLOSE_RE, '')
      .split(/\r?\n/)[0]
      .split(',').map(part => part.trim()).filter(Boolean);
    // 앞 태그는 보통 `girl` 이라 그것만으로는 구분이 안 된다 - 둘째까지 본다.
    const hint = first.slice(0, 2).join(', ');
    if (sourceOrdinal) return hint ? `${lead} + ${hint}` : lead;
    return hint ? `${tag} · ${hint}` : tag;
  }

  /** 이 슬롯이 물려받는 원본의 1-based 번호. 연결이 없거나 못 찾으면 0. */
  function sourceOrdinalOf(character, slots) {
    const link = String(character.connect_to || '');
    if (!link) return 0;
    return slots.findIndex(item => String(item.character.slot_uuid || '') === link) + 1;
  }

  function slotHtml(character, index, ordinal, activeCount, slots) {
    const isOpen = openSlots.has(index);
    // 연결 중이면 두 칸의 뜻이 바뀐다 - 대체가 아니라 **덧붙이기**다(사용자 지정).
    const linked = !!String(character.connect_to || '');
    // 라벨(PROMPT/NEGATIVE)을 두지 않는다 - 자리를 먹는 만큼 입력 공간을 뺏는다.
    // 네거티브는 **테두리 색**으로 구분하고, 뜻은 placeholder 가 말한다.
    //
    // 강조 미러는 textarea 와 **같은 부모** 안에 형제로 둔다. 렌더가 innerHTML 이라
    // 나중에 DOM 을 감싸는 방식은 매 렌더마다 다시 해야 하고 한 번 빠지면 조용히 안 뜬다.
    const field = (kind, cls, ph) =>
      `<div class="cq-input-wrap">`
      + `<div class="cq-hl" aria-hidden="true"></div>`
      + `<textarea class="cq-input${cls}" data-cq-field="char_${kind}_${index}" data-cq-uuid="${escAttr(character.slot_uuid || '')}" data-cq-min="${kind === 'prompt' ? 'prompt' : 'uc'}"`
      // 랜덤 슬롯의 앞머리 `__키__` 는 못 고친다(사용자 지시 2026-10-19) - 서버 `keep_session_prefix` 와 같은 규칙으로 바로 되돌린다.
      + (kind === 'prompt' && character.session_wildcard && SESSION_TOKEN.test(character.prompt || '')
        ? ` data-cq-lock="${escAttr(String(character.prompt).match(SESSION_TOKEN)[0])}"` : '')
      + ` rows="${MIN_ROWS[kind === 'prompt' ? 'prompt' : 'uc']}" placeholder="${ph}"></textarea>`
      // `#주석` 층은 칸 **뒤**의 형제다 - style.css 가 칸의 상태(`.is-neg` · 초점)를 `~` 로 읽어 색을 고른다.
      + `<div class="pc-cmt" aria-hidden="true"></div></div>`;
    const body = isOpen
      ? field('prompt', '', linked ? '추가할 캐릭터 프롬프트' : '캐릭터 프롬프트')
        + field('uc', ' is-neg', linked ? '추가할 캐릭터 네거티브' : '캐릭터 네거티브')
        // 랜덤 슬롯 출력 옵션 2줄(사용자 지시 2026-10-19) - 내용은 `paintSessionOptions` 가 채운다.
        + (character.session_wildcard ? '<div class="cq-sopt" data-cq-sopt="1"></div>' : '')
      : '';
    // ⚠️ title 을 두지 않는다. 앱이 그걸 걷어 자체 툴팁으로 바꾸는데, 이 상자는
    //    좁아서 툴팁이 라벨을 그대로 덮는다(사용자 지적). 화살표가 이미 접힘/펼침을
    //    말하고 있어 설명이 필요 없다.
    //
    // 머리는 **줄**이다 - <button> 안에 <button> 을 넣으면 마크업이 깨지고
    // 안쪽을 눌러도 바깥 토글이 먼저 먹는다(바깥 CHARACTER 머리와 같은 이유).
    //
    // C1 은 지울 수 없다(사용자 지정). 마지막 활성 하나는 남아야 하고, 그 자리가
    // C1 이다. ▼ 도 활성이 하나뿐이면 내주지 않는다 - 내리면 활성이 0이 된다.
    const canRemove = ordinal > 1;
    const canDeactivate = activeCount > 1;
    // ✔/✘ 가 캐럿 자리를 받는다(사용자 지정). 캐럿은 뜻이 없었다 - 머리줄 전체가
    // 이미 접고 펴는 버튼이라 화살표는 상태 표시일 뿐이었고, 그 자리가 NAI 공식
    // 구현에서 켬/끔이 있는 자리다.
    //
    // ⚠️ 머리 <button> **바깥**에 둔다. 안에 넣으면 마크업이 깨지고 안쪽을 눌러도
    //    바깥 토글이 먼저 먹는다(이 파일이 이미 두 번 밟은 함정).
    const muted = !!character.muted;
    // 켜진 슬롯(✔)은 배경으로 드러낸다(사용자 지정 2026-10-15) - 꺼진 것과 글자 흐림만으로 가르면, 여럿 중
    // 무엇이 이번 생성에 나가는지 한눈에 안 잡힌다.
    return `<div class="cq-slot${isOpen ? ' is-open' : ''}${muted ? ' is-muted' : ' is-live'}`
      + `${linked ? ' is-linked' : ''}">`
      + `<div class="cq-slot-headrow">`
      + `<button type="button" class="cq-slot-en${muted ? '' : ' is-on'}"`
      + ` data-cq-mute="${index}" aria-pressed="${muted ? 'false' : 'true'}"`
      + ` aria-label="${muted ? '이 슬롯을 켠다' : '이 슬롯을 끈다'}">`
      + `${muted ? '✘' : '✔'}</button>`
      + `<button type="button" class="cq-slot-head" data-cq-toggle="${index}"`
      + ` aria-expanded="${isOpen ? 'true' : 'false'}">`
      + `<span class="cq-slot-title" data-cq-label="${index}">`
      + `${escHtml(slotLabel(character, ordinal, sourceOrdinalOf(character, slots || [])))}</span></button>`
      + connectSourceBadge(character, slots || [])
      + connectControl(character, index, ordinal, slots || [])
      // [Refresh] = 이 슬롯의 와일드카드를 **지금** 다시 굴린다(사용자 지정 2026-09-24).
      // 가상(인페인트 세션) 캐릭터에는 굴림 스냅샷이 없어 내지 않는다.
      + (lastState && lastState.virtual
          ? ''
          : `<button type="button" class="cq-slot-btn cq-refresh" data-cq-refresh="${index}"`
            + ` aria-label="이 슬롯의 와일드카드를 다시 굴린다">Refresh</button>`)
      + (canDeactivate
          ? `<button type="button" class="cq-slot-btn" data-cq-down="${index}"`
            + ` aria-label="비활성으로 내림">&#9660;</button>`
          : '')
      + `<button type="button" class="cq-slot-btn is-danger" data-cq-del="${index}"`
      + `${canRemove ? '' : ' disabled'} aria-label="슬롯 제거">-</button>`
      + `</div>`
      + `<div class="cq-slot-body">${body}</div></div>`;
  }

  /** 구성만 담는다 - 입력 내용은 절대 넣지 않는다(캐럿 튐).
   *
   *  ⚠️ 예전에 `slotLabel()` 을 여기 넣었다가 정확히 그 함정을 밟았다: 라벨은
   *  프롬프트 앞 태그에서 만들어지므로 **입력 내용이다.** 한 글자 칠 때마다 서명이
   *  바뀌어 통째로 다시 그렸고, 그 순간 편집 중인 textarea 가 교체돼 포커스가
   *  빠졌다(사용자 제보). 라벨은 서명이 아니라 syncValues 가 제자리에서 고친다. */
  /** POS 세 상태. 서버가 `position_mode` 를 주지만 옛 필드도 받아 둔다. */
  const POS_CYCLE = ['auto', 'custom', 'random'];
  const POS_LABEL = {auto: 'AUTO', custom: 'CUSTOM', random: 'RAND'};
  function posModeOf(state) {
    const raw = state && state.position_mode;
    if (POS_CYCLE.includes(raw)) return raw;
    return state && state.use_custom_positions ? 'custom' : 'auto';
  }

  /** Connect 를 쓰는 슬롯이 하나라도 있나. 있으면 POS 가 CUSTOM 에 못 박힌다
   *  (백엔드 `_normalize_character_settings_with_migration` 이 강제한다). */
  function hasConnectedSlot(state) {
    return ((state && state.characters) || [])
      .some(character => character && character.active && String(character.connect_to || ''));
  }

  /** Rnd Res 중에는 POS 를 잠근다. 해상도가 매번 바뀌면 원을 앉힐 캔버스가 없다. */
  function posBlockedByRandom() {
    // ⚠️ **가상(인페인트 세션)에서는 안 막는다**(사용자 지정 2026-08-29).
    //    Rnd Res 로 막는 이유는 "다음 생성의 캔버스 비율을 모른다" 였는데, 세션은
    //    캔버스 해상도가 **고정**이라 그 전제가 성립하지 않는다. 좌표가 뜻을 가진다.
    if (lastState && lastState.virtual) return false;
    try { return !!isRandomResolution(); } catch (_) { return false; }
  }
  let randomPosForced = false;   // AUTO 강제를 **한 번만** 보낸다(에코마다 쏘면 안 된다)

  function signature(state) {
    // ⚠️ muted 도 서명에 넣는다. 빼면 ✔/✘ 를 눌러도 다시 그리지 않아 표시가
    //    옛 상태에 굳는다(POS 라벨이 CUSTOM 에 굳었던 것과 같은 계열).
    // ⚠️ Connect 도 같은 이유로 넣는다. 이미 CUSTOM 인 상태에서 링크를 걸면
    //    `posModeOf` 는 그대로라 서명이 안 바뀌고, POS 버튼의 자물쇠가 안 나타난다.
    // ⚠️ **참/거짓이 아니라 대상 uuid 를 넣는다.** 불리언으로 넣으면 C3 의 연결을
    //    C1 에서 C2 로 바꿔도 서명이 그대로라 다시 그리지 않는다 - 칩은 계속 `C1` 이라
    //    말하고 원본 배지도 옛 슬롯에 붙어 있다(Codex 리뷰 2026-08-24 #6).
    // ⚠️ **누가 그 자리에 있는가**(uuid)도 넣는다. 빠른 길은 칸을 다시 안 그리고 값만 바꾸는데, 칸에는 그릴
    //    때의 uuid(`data-cq-uuid`)가 적혀 있고 글 편집은 그것을 함께 보낸다. 같은 자리에 다른 캐릭터가 왔는데
    //    (일괄 적용 · 씬) 안 그리면 칸은 옛 uuid 를 쥔 채 새 글을 보여 주고, 거기에 친 것을 서버가 **옛
    //    캐릭터(보관함)** 에 가져다 쓴다(Codex 리뷰 2026-10-05). uuid 는 입력 내용이 아니라 신원이다 -
    //    글자를 친다고 바뀌지 않으니 아래 '라벨을 넣지 마라' 와 어긋나지 않는다.
    const slots = activeSlots(state)
      .map(({index, character}) =>
        [index, String((character && character.slot_uuid) || ''),
         openSlots.has(index) ? 1 : 0, character && character.muted ? 1 : 0,
         String((character && character.connect_to) || '')].join('~'))
      .join('|');
    // `activated` 도 넣는다 - 모듈 팝업에서 끄면 이쪽 체크도 따라와야 한다.
    // ⚠️ POS 는 **모드 이름**을 넣는다. 불리언으로 넣으면 CUSTOM->RAND 전환이
    //    서명에 안 잡혀 라벨이 CUSTOM 에 굳는다(둘 다 "참"이 아니게 되는 순간).
    // ⚠️ `virtual` 도 넣는다. 메인과 세션의 슬롯 구조가 우연히 같으면(같은 인원수·
    //    같은 POS 모드·아무것도 안 펼친 상태) 서명이 똑같아 빠른 경로로 빠지고,
    //    머리줄을 다시 안 그려 **(가상) 배지가 안 뜬다**(Codex 리뷰 2026-08-26).
    //    세션을 닫을 때는 반대로 배지가 남는다.
    // ⚠️ Rnd Res 잠금과 **해상도**도 넣는다. 안 넣으면 (a) 랜덤을 켜도 POS 버튼에
    //    자물쇠가 안 붙고, (b) 해상도가 바뀌어도 무대 비율이 옛 값에 굳어 그리드가
    //    그림과 어긋난 채 남는다(사용자 지정: "POS 그리드 및 패널 동기화").
    const res = resolutionNow();
    // ⚠️ `reroll_on_generate` 도 넣는다 - 모듈 창에서 바꾸면 이쪽 체크도 따라와야 한다.
    return `${open ? 1 : 0}${state && state.activated ? 1 : 0}${state && state.virtual ? 1 : 0}`
      + `${state && state.virtual_label ? state.virtual_label : ''}`
      + `${state && state.reroll_on_generate ? 1 : 0}`
      + `${posModeOf(state)}${posEditing ? 1 : 0}${posBlockedByRandom() ? 'R' : '-'}`
      + `${res ? `${res.w}x${res.h}` : '-'}#${slots}`;
  }

  /** 자동완성을 새로 그린 칸에 다시 건다.
   *
   *  ⚠️ 매 렌더마다 요소가 교체되므로 **렌더 뒤에 반드시** 불러야 한다. 한 번만
   *  걸면 첫 렌더의 칸에만 붙고, 슬롯을 접었다 펴는 순간 조용히 사라진다.
   *
   *  옵션은 모듈 팝업의 캐릭터 칸과 같다(카테고리 제외 없음) - 캐릭터 슬롯에서는
   *  아티스트도 캐릭터도 다 쓴다. Interactive 의 전역 태그 칸만 그 둘을 뺀다.
   */
  function bindAssist() {
    if (!mount) return;
    mount.querySelectorAll('[data-cq-field]').forEach(element => {
      if (element._cqAssistBound) return;   // 같은 요소에 두 번 걸지 않는다
      element._cqAssistBound = true;
      bindTagAssist(element);
    });
  }

  /** 렌더가 값을 지웠으므로 여기서 되돌린다(마크업에 값을 넣지 않는 대가). */
  function syncValues(state) {
    const chars = (state && state.characters) || [];
    // 라벨은 프롬프트에서 파생되므로 **여기서** 고친다. 다시 그리면 편집 중인
    // 칸이 교체돼 포커스가 빠진다(위 signature 주석 참조).
    const labelSlots = activeSlots(state);
    const ordinalOf = new Map();
    labelSlots.forEach(({index}, i) => ordinalOf.set(index, i + 1));
    mount.querySelectorAll('[data-cq-label]').forEach(element => {
      const index = Number(element.dataset.cqLabel);
      const character = chars[index];
      if (!character) return;
      const next = slotLabel(character, ordinalOf.get(index) || 1, sourceOrdinalOf(character, labelSlots));
      if (element.textContent !== next) element.textContent = next;
    });
    mount.querySelectorAll('[data-cq-field]').forEach(element => {
      const key = element.dataset.cqField || '';
      const match = key.match(/^char_(prompt|uc)_(\d+)$/);
      if (!match) return;
      const character = chars[Number(match[2])];
      if (!character) return;
      // ⚠️ **지금 쓰고 있는 칸은 건드리지 않는다.** 서버 echo 가 조금 늦게 오는데
      //    그때 `.value` 를 덮으면 (가) 한글 조합이 끊기고 (나) 자동완성이 막 끼워
      //    넣은 글자가 되감긴다. 편집 중인 칸은 화면 쪽이 진실이다.
      if (document.activeElement === element) { autoGrow(element); paintConnectHighlight(element); return; }
      const next = String((match[1] === 'prompt' ? character.prompt : character.uc) || '');
      if (element.value !== next) element.value = next;
      autoGrow(element);
      // 값이 서버에서 온 경로(다른 창에서 편집·프리셋 적용 등)도 강조가 따라와야 한다.
      paintConnectHighlight(element);
    });
  }

  /** 패널이 펼쳐져 있으면 결과 이미지를 오른쪽으로 민다(사용자 지정).
   *
   *  ⚠️ 미는 대상은 **요소가 아니라 그림**이다. `#preview` 는 `width/height: 100%`
   *  + `object-fit: contain` 이라 요소는 늘 뷰어를 꽉 채우고 그림만 그 안에서
   *  레터박싱된다. 그래서 `justify-content` 도 `padding` 도 안 먹는다(실측: flex-end
   *  로 바꿔도 imgLeft 가 1px 도 안 움직였다). CSS 가 `object-position` 을 옮긴다 -
   *  남는 여백만큼만 이동하고, 그림이 꽉 차 있으면 그대로다. 크기는 안 건드린다.
   *
   *  Interactive 의 `--ia-shift`(padding 으로 자리를 비우는 방식)를 쓰지 않는 이유:
   *  그쪽은 팝업이 자리를 **요구**해 그림이 작아져도 되는 경우다. 여기 패널은
   *  반투명으로 얹히는 것이라 그림을 줄일 이유가 없다. */
  function syncViewerShift() {
    const viewer = document.getElementById('resultViewer');
    if (!viewer) return;
    const on = visible && open;
    viewer.classList.toggle('is-cq-shift', on);
    if (!on) { viewer.style.removeProperty('--cq-img-shift'); return; }
    const img = document.getElementById('preview');
    const box = img && img.getBoundingClientRect();
    if (!img || !box || !box.width || !img.naturalWidth) {
      viewer.style.removeProperty('--cq-img-shift');
      return;
    }
    // `object-fit: contain` 이 실제로 그리는 크기. 요소 상자와 다르다.
    const scale = Math.min(box.width / img.naturalWidth, box.height / img.naturalHeight);
    const drawnWidth = img.naturalWidth * scale;
    const slack = Math.max(0, box.width - drawnWidth);
    // 캐릭터 박스 **오른쪽 끝**까지만 민다(사용자 정정). 끝까지 밀지 않는다.
    //
    // ⚠️ **밀기만 한다.** 넓은 화면에서는 가운데 놓인 그림이 이미 패널을 벗어나
    //    있는데, 원하는 위치를 그대로 넣으면 오히려 왼쪽으로 **당겨**진다
    //    (실측: 가운데 908 -> 760 으로 끌려왔다). 기본 자리(가운데)보다 왼쪽으로는
    //    가지 않게 바닥을 받친다.
    const panel = mount && mount.getBoundingClientRect();
    const want = panel ? panel.right + VIEWER_GAP - box.left : 0;
    // ⚠️ **다 못 비키면 아예 안 비킨다**(사용자 정정). 여백이 모자란데 끝까지 밀면
    //    그림만 한쪽으로 쏠린 채 여전히 패널에 가린다 - 어중간하게 옮기느니
    //    가운데 그대로 두고 겹치는 편이 낫다.
    if (want > slack) { viewer.style.removeProperty('--cq-img-shift'); return; }
    // 기본 자리(가운데)보다 왼쪽으로는 가지 않는다 - 밀기만 한다.
    const offset = Math.min(Math.max(want, slack / 2), slack);
    viewer.style.setProperty('--cq-img-shift', Math.round(offset) + 'px');
  }

  /** 그리드가 GENERATION INFO 바로 위까지만 자라게 한다(사용자 지정).
   *
   *  CSS 의 vh 로는 못 한다 - 결과 정보 패널의 높이가 접힘/펼침에 따라 변하고,
   *  패널 자체도 뷰포트 맨 위에서 시작하지 않는다. 그릴 때마다 실제로 잰다. */
  function fitGridHeight() {
    if (anchorWatcher) anchorWatcher();
    const grid = mount && mount.querySelector('.cq-grid');
    if (!grid) return;
    const anchor = document.querySelector(BOTTOM_ANCHOR);
    const limit = anchor ? anchor.getBoundingClientRect().top : window.innerHeight;
    const top = grid.getBoundingClientRect().top;
    // 아래에 랜덤 캐릭터 줄이 붙어 있으면 그만큼 덜 자란다.
    const roll = mount.querySelector('.cq-roll');
    const below = roll ? roll.offsetHeight + 6 : 0;
    grid.style.maxHeight = Math.max(120, Math.round(limit - top - BOTTOM_GAP - below)) + 'px';
  }

  /** 최소 줄수는 지키되, 넘치면 한 줄씩 늘어난다(사용자 지정). */
  function autoGrow(element) {
    const rows = MIN_ROWS[element.dataset.cqMin] || 2;
    const line = 1.4 * 11;                       // .cq-input 의 line-height * font-size
    const min = Math.round(rows * line) + 12;    // + 세로 패딩
    // 측정 중 height:auto 로 줄어들면 그리드의 스크롤 범위도 잠시 줄어든다.
    // 브라우저의 scroll anchoring 이 적용되지 않는 경우 입력/서버 echo 마다
    // scrollTop 이 위로 잘리므로, 최종 높이를 적용한 뒤 편집 위치를 복원한다.
    const grid = element.closest('.cq-grid');
    const keepScroll = grid?.scrollTop;
    element.style.height = 'auto';
    element.style.height = Math.max(min, element.scrollHeight) + 'px';
    if (grid) grid.scrollTop = keepScroll;
  }

  function onInput(event) {
    const toggle = event.target.closest('[data-cq-enable]');
    if (toggle) {
      // 모듈 팝업의 "캐릭터 프롬프트를 활성화 합니다" 와 같은 값이다 - 한쪽을
      // 바꾸면 module_state 로 다른 쪽도 따라온다.
      setModuleParam('character', 'activated', String(toggle.checked));
      return;
    }
    const element = event.target.closest('[data-cq-field]');
    if (!element) return;
    if (element.dataset.cqLock && !event.isComposing && keyGuard && keyGuard.check(element)) return;
    autoGrow(element);
    // 강조는 **글자를 칠 때마다** 다시 칠한다. 서명 기반 재렌더는 입력 내용을 일부러
    // 무시하므로(캐럿 튐) 여기서 하지 않으면 구간이 옛 모양에 굳는다.
    paintConnectHighlight(element);
    // 이 편집은 0.5초 묵혔다 간다. 그 칸을 그릴 때 적어 둔 uuid 를 함께 보내, 그 사이 배열이 바뀌어도
    // 서버가 번호가 아니라 **그 칸**을 찾아가게 한다(가상 캐릭터는 uuid 가 없다 - 세션 쪽 길로 간다).
    onModTextEdit('character', element.dataset.cqField, element.value, element.dataset.cqUuid || '');
  }

  function onClick(event) {
    // 활성화 토글은 label/input 이라 클릭이 여기로도 올라온다 - 바깥 토글보다 먼저 본다.
    if (event.target.closest('[data-cq-enable]') || event.target.closest('.cq-enable')) return;
    if (event.target.closest('[data-cq-roll-fold]')) {
      rollFold = !rollFold;
      try { localStorage.setItem(ROLL_FOLD_KEY, rollFold ? '1' : '0'); } catch (error) { /* 기억 못 해도 지금은 접힌다 */ }
      renderRoll();
      fitGridHeight();
      return;
    }
    if (event.target.closest('[data-cq-roll-detail]')) { rollDetail = !rollDetail; renderRoll(); fitGridHeight(); return; }
    if (event.target.closest('[data-cq-roll-pin]')) { void pinRoll(); return; }
    if (event.target.closest('[data-cq-wcsave]')) { void openWcSave(); return; }
    const soptKey = event.target.closest('[data-cq-sopt-k]');
    if (soptKey) { void setSessionOptions(soptKey.dataset.cqSoptK); return; }
    if (event.target.closest('[data-cq-sopt-paren]')) { void setSessionOptions('paren'); return; }
    if (event.target.closest('.cq-sopt-chk')) return;          // label 클릭은 input 으로 한 번 더 온다 - input 것만
    if (event.target.closest('[data-cq-roll-fav]')) { void rollToggle('fav'); return; }
    if (event.target.closest('[data-cq-roll-hide]')) { void rollToggle('hide'); return; }
    // '생성 때 갱신' - label 을 누르면 click 이 label 과 input 에 두 번 온다. input 것만 본다.
    if (event.target.closest('.cq-reroll')) {
      const box = event.target.closest('[data-cq-reroll]');
      if (box) setModuleParam('character', 'reroll_on_generate', String(box.checked));
      return;
    }
    const refresh = event.target.closest('[data-cq-refresh]');
    if (refresh) { requestRefresh(Number(refresh.dataset.cqRefresh)); return; }
    // TODO(POS): 캐릭터 좌표 편집. 규약은 확정됨(좌상단 원점 · 0~1 · 소수 3자리)
    //   이고 백엔드도 준비됐다(use_coords). 앵커 UI 만 남았다.
    if (event.target.closest('[data-cq-pos]')) return;
    const head = event.target.closest('[data-cq-head]');
    if (head) { open = !open; render(lastState, true); return; }
    // ▼ 와 - 는 슬롯 배열을 바꾼다. 번호는 활성 무리 안의 자리라 서버가 새 상태를
    // 밀어 주면 저절로 재정렬된다 - 여기서 따로 손대지 않는다.
    const down = event.target.closest('[data-cq-down]');
    if (down) {
      openSlots.delete(Number(down.dataset.cqDown));
      setModuleParam('character', `char_slot_state_${down.dataset.cqDown}`, 'inactive');
      return;
    }
    const del = event.target.closest('[data-cq-del]');
    if (del) {
      if (del.disabled) return;
      openSlots.delete(Number(del.dataset.cqDel));
      setModuleParam('character', `remove_character_${del.dataset.cqDel}`, 'true');
      return;
    }
    const mute = event.target.closest('[data-cq-mute]');
    if (mute) {
      const index = Number(mute.dataset.cqMute);
      const slot = activeSlots(lastState).find(item => item.index === index);
      const nextMuted = !(slot && slot.character.muted);
      // 끄면 접고, 켜면 편다(사용자 지정). 끈 슬롯의 입력칸은 쓸 일이 없으니
      // 자리를 돌려주고, 다시 켜는 것은 대개 거기에 뭘 쓰려는 것이다.
      if (nextMuted) openSlots.delete(index); else openSlots.add(index);
      setModuleParam('character', `char_muted_${index}`, String(nextMuted));
      // 서버 에코를 기다리지 않고 접힘/펼침을 먼저 반영한다 - 에코는 muted 만
      // 바꾸고 openSlots 는 이쪽 상태라 다시 그려 줘야 화면이 따라온다.
      render(lastState, true);
      return;
    }
    const connect = event.target.closest('[data-cq-connect]');
    if (connect) {
      // 방금 이 칩 때문에 닫혔으면 다시 열지 않는다(위 `connectMenuClosedFrom` 참조).
      if (connectMenuClosedFrom === connect) { connectMenuClosedFrom = null; return; }
      connectMenuClosedFrom = null;
      openConnectMenu(connect, Number(connect.dataset.cqConnect));
      return;
    }
    const toggle = event.target.closest('[data-cq-toggle]');
    if (toggle) {
      const index = Number(toggle.dataset.cqToggle);
      if (openSlots.has(index)) openSlots.delete(index); else openSlots.add(index);
      render(lastState, true);
      return;
    }
    if (event.target.closest('[data-cq-posmode]')) {
      // Connect 가 걸려 있으면 POS 는 CUSTOM 에 못 박힌다(백엔드 정규화가 강제한다).
      // 여기서 막지 않으면 눌러도 값이 되돌아와 "버튼이 고장났다" 로 보인다.
      if (hasConnectedSlot(lastState)) {
        showToast('Connect 를 쓰는 동안에는 POS 가 CUSTOM 으로 고정됩니다 (칸마다 직접 앉히는 기능입니다)', 'info');
        return;
      }
      if (posBlockedByRandom()) {
        showToast('Rnd Res 중에는 POS 가 AUTO 로 고정됩니다 (해상도가 매 생성마다 바뀌어 좌표를 앉힐 캔버스가 없습니다)', 'info');
        return;
      }
      // AUTO -> CUSTOM -> RAND -> AUTO (사용자 지정).
      // ⚠️ **가상 캐릭터는 RAND 를 건너뛴다**(사용자 지정 2026-08-29). 인페인트 세션의
      //    캐릭터에는 뜻이 없다 - 백엔드도 auto/custom 만 받는다.
      const cycle = lastState && lastState.virtual
        ? POS_CYCLE.filter(mode => mode !== 'random')
        : POS_CYCLE;
      const now = posModeOf(lastState);
      const at = cycle.indexOf(now);
      const next = cycle[(at < 0 ? 0 : at + 1) % cycle.length];
      // CUSTOM 을 떠나면 편집 중일 이유가 없다 - 원을 옮길 대상이 사라진다.
      if (next !== 'custom' && posEditing) setPosEditing(false);
      setModuleParam('character', 'position_mode', next);
      return;
    }
    if (event.target.closest('[data-cq-posedit]')) { setPosPeek(false); setPosEditing(true); return; }
    if (event.target.closest('[data-cq-posdone]')) { setPosEditing(false); return; }
    // ⚠️ 여기서 좁은 화면을 따로 막지 않는다. 모바일에서는 버튼을 아예 안 그리고,
    //    혹 넓혔다 좁히는 사이에 남은 버튼이 눌려도 `openModule` 이 **목에서** 막고
    //    이유까지 말해 준다. 여기서 조용히 삼키면 아무 일도 안 일어나 보인다.
    if (event.target.closest('[data-cq-manage]')) { closeFind(); openCharacterModule(); return; }
    if (event.target.closest('[data-cq-find]')) { if (findEl) closeFind(); else openFind(); return; }
    if (event.target.closest('[data-cq-feat]')) { toggleFeat(); return; }
    if (event.target.closest('[data-cq-add]')) {
      // 지금 활성 슬롯 수를 적어 둔다 - 에코가 이보다 늘면 그게 새 슬롯이다.
      pendingAddOpen = activeSlots(lastState).length;
      setModuleParam('character', 'add_character', 'true');
    }
  }

  /** Interactive 가 켜져 있거나 NAI 모드가 아니면 자리를 비운다. */
  /** [Refresh] - 이 슬롯만 다시 굴려 달라고 한다. 밀린 입력은 `setModuleParam` 이 먼저
   *  내보낸다(방금 친 글로 굴린다). 결과는 module_state 로 와서 `render` 가 툴팁을 띄운다. */
  function requestRefresh(index) {
    const character = ((lastState && lastState.characters) || [])[index];
    const uuid = String((character && character.slot_uuid) || '');
    if (!uuid) return;
    const slots = (lastState && lastState.processed_slots) || {};
    const at = Date.now();
    pendingRefresh = {uuid, index, before: JSON.stringify(slots[uuid] || null), at};
    setModuleParam('character', 'preview_refresh_slot', uuid);
    // 같은 값이 다시 뽑히면 '바뀐' 응답이 없다 - 잠시 뒤 최신 상태로 한 번 띄운다.
    setTimeout(() => { if (pendingRefresh && pendingRefresh.at === at) settleRefresh(lastState, true); }, 900);
  }

  /** 뽑힌 값 툴팁 - 반투명, 약 2초(사용자 지정 2026-09-24). 패널 **오른쪽 바깥**(그림 위)에
   *  그 슬롯 머리줄 높이로 띄운다. 오른쪽에 자리가 없으면 머리줄 아래로. 누름을 막지 않는다. */
  function showRefreshTip(index, entry) {
    const head = mount && mount.querySelector(`[data-cq-refresh="${index}"]`)?.closest('.cq-slot-headrow');
    const box = mount && mount.querySelector('.cq-box');
    if (!head || !box) return;
    if (!refreshTip) {
      refreshTip = document.createElement('div');
      refreshTip.className = 'cq-refresh-tip';
      refreshTip.setAttribute('role', 'status');
      document.body.appendChild(refreshTip);
    }
    const rolls = (entry && Array.isArray(entry.rolls)) ? entry.rolls : [];
    const frozen = rolls.some(roll => roll.key === '(frozen)');
    const picked = rolls.filter(roll => roll.key && roll.key !== '(frozen)');
    const label = escHtml(String(head.querySelector('.cq-slot-title')?.textContent || '').trim());
    const clip = text => (text.length > 70 ? `${text.slice(0, 69)}…` : text);
    const lines = frozen
      ? ['<i>📌 고정된 슬롯이라 바뀌지 않았습니다 - 결과 창에서 풀 수 있습니다</i>']
      : picked.length
        ? picked.map(roll => `<span class="cq-tip-key">${escHtml(roll.key)}</span>`
          + ` → ${escHtml(clip(String(roll.value || '')))}`)
        : ['<i>와일드카드가 없어 그대로입니다</i>'];
    refreshTip.innerHTML = `<b>${label} · 새로 굴렸습니다</b>${lines.map(line => `<div>${line}</div>`).join('')}`;
    const h = head.getBoundingClientRect();
    const b = box.getBoundingClientRect();
    const room = (window.innerWidth || 0) - b.right - 16;
    refreshTip.style.maxWidth = `${Math.max(180, Math.min(360, room > 180 ? room : b.width))}px`;
    if (room > 180) {
      refreshTip.style.left = `${Math.round(b.right + 8)}px`;
      refreshTip.style.top = `${Math.round(h.top)}px`;
    } else {
      refreshTip.style.left = `${Math.round(b.left)}px`;
      refreshTip.style.top = `${Math.round(h.bottom + 4)}px`;
    }
    refreshTip.classList.remove('is-on');
    void refreshTip.offsetWidth;            // 연달아 눌러도 다시 떠오르게
    refreshTip.classList.add('is-on');
    clearTimeout(refreshTipTimer);
    refreshTipTimer = setTimeout(() => refreshTip && refreshTip.classList.remove('is-on'), 2000);
  }

  /** 응답이 왔나. 값이 바뀌었거나(굴린 결과) 조금 지났으면(같은 값이 다시 뽑혔을 수 있다) 띄운다.
   *  ⚠️ 밀린 입력을 내보낸 **에코가 먼저** 올 수 있다 - 그건 결과가 아니라 곧바로 띄우지 않는다. */
  function settleRefresh(state, force = false) {
    if (!pendingRefresh) return;
    const age = Date.now() - pendingRefresh.at;
    if (age > 5000) { pendingRefresh = null; return; }
    const entry = ((state && state.processed_slots) || {})[pendingRefresh.uuid] || null;
    if (!entry) return;
    if (!force && JSON.stringify(entry) === pendingRefresh.before && age < 600) return;
    const {index} = pendingRefresh;
    pendingRefresh = null;
    requestAnimationFrame(() => showRefreshTip(index, entry));
    // [Refresh] 도 굴림이다 - 랜덤 슬롯이면 디버그 줄을 마지막으로 뽑힌 캐릭터로(A).
    if (state && (state.characters || [])[index]?.session_wildcard) noteRandom();
  }

  // ── Find(패널 바깥의 빠른 불러오기) ───────────────────────────────────────
  // Manage 를 열지 않고 캐릭터를 슬롯에 담는다(사용자 지정 2026-10-15). 두 갈래:
  //   [캐릭터 · 작품]       Manage 의 검색 탭과 같은 캐릭터 사전(`/api/character-viewer/*`) - 누르면 기본 변형을 담는다
  //   [히스토리 · 즐겨찾기] 보관함(히스토리 · ★ · 그룹) - 누르면 Manage 의 ↩ 와 같은 길(`char_slot_state_N=active`)
  // 같은 캐릭터가 이미 슬롯에 있으면 서버가 새로 넣지 않고 그 슬롯을 켠다(`_active_duplicate`) - 화면은 그 사실을
  // 줄의 `C3` 표로 미리 보여 줄 뿐 판단은 서버가 한다.
  //
  // ⚠️ 창은 **body 에 fixed 로** 붙인다(Connect 메뉴와 같은 까닭 - 패널 상자는 overflow 로 자른다).
  // ⚠️ 목록만 갈아 끼운다. 창 전체를 다시 그리면 검색칸이 새로 생겨 한 글자마다 캐럿을 잃는다.
  const FIND_PER_PAGE = 30;
  let findEl = null;
  // [특징] 검색 · 제외 판(사용자 지시 2026-10-19) - Find 단추 위에 따로 뜬다. 낱말은 **캐릭터 데이터에 있는 것만**
  // 고른다(`/api/character-viewer/feature-suggest` - Artist Thumbnail 검색칸과 같은 규칙). 고른 낱말은 판을 닫아도
  // 남아 [캐릭터 · 작품] 목록에 걸린다(단추에 수가 붙는다). 검색 줄 = 전부(AND · 작품은 그중 하나), 제외 줄 = 하나라도.
  let featEl = null;
  const featTerms = {inc: [], exc: []};          // [{tag, kind, label}]
  const featSugg = {inc: null, exc: null};       // {rows, active, seq, timer}
  let findDexTotal = null;
  // 처음 여는 갈래 = 히스토리 · 즐겨찾기(사용자 지시 2026-10-17). 탭 차례(사전이 앞)는 그대로 - 기본값만 바꿨다.
  let findTab = 'lib';
  const findQuery = {dex: '', lib: '', hid: ''};
  let findDexRows = [];
  let findDexSeq = 0;
  let findDexTimer = 0;
  let findDexLoading = false;
  let findDexError = '';
  let findPicking = '';            // 사전 상세를 받는 중인 줄(두 번 눌러 두 번 담지 않게)
  let findDismiss = null;
  // 창 안을 누르고 있는 동안에는 목록을 갈아 끼우지 않는다 - 눌린 줄이 떼기 전에 사라지면 크롬은 click 을 안 보낸다
  // (CHARACTER_WORKSPACE_CLAUDE.md 법 0). 그사이 온 갱신은 뗀 뒤(click 이 먼저 지나간 다음) 한 번 그린다(Codex 2차 리뷰).
  let findHeld = false;
  let findHeldRender = false;
  let findHeldTimer = 0;
  let hidRows = null;              // Find [제외] - 숨긴 캐릭터(null = 아직 안 읽음)
  let hidSeq = 0;
  let hidLoading = false;

  function settleFindHeld() {
    clearTimeout(findHeldTimer);
    findHeldTimer = 0;
    if (!findHeld) return;
    findHeld = false;
    if (findHeldRender) { findHeldRender = false; renderFindList(); }
  }

  /** 뗐다 - click 이 먼저 지나가게 0ms 뒤에 푼다. 창 밖에서 뗀 경우(mouseup 이 안 오는 경우)는 1초 뒤에 푼다. */
  function onFindPointerUp() {
    if (findHeld) setTimeout(settleFindHeld, 0);
  }

  /** [Find] [필터] 줄은 패널 머리줄 옆(위)이 기본이다(사용자 지시 2026-10-19). 좁은 창에서는 Result 오른쪽 위의 알약(Usage 등 -
   *  같은 층에서 패널보다 위)이 그 자리를 덮는다 - 덮였으면 예전 자리(패널 오른쪽 아래)로 내린다. 패널 층을 올리면 Result 의 다른
   *  덮개(대기열 · 디버그 오버레이 등)까지 덮게 되어 층은 건드리지 않는다. */
  function placeFindBar() {
    const bar = mount?.querySelector('.cq-find-bar');
    if (!bar) return;
    bar.classList.remove('is-low');
    const rect = bar.getBoundingClientRect();
    if (!rect.width) return;
    // 덮는 것은 Result 오른쪽 위의 알약들뿐이다(사용량 · 모바일 통계 - 같은 층에서 패널보다 위). 그 상자와 겹치는지만 본다.
    // ⚠️ 예전엔 그 자리의 맨 위 요소를 집었다(`elementFromPoint`) - 그리는 순간 잠깐 떠 있던 토스트 · 창이 집히면 단추 줄이
    //    아래로 내려간 채 다음 렌더까지 남았다(사용자 제보 2026-10-19: Find · 필터가 다시 아래로).
    const covered = ['naiUsagePill', 'statsIsland'].some(id => {
      const el = document.getElementById(id);
      if (!el || el.classList.contains('hidden') || !el.getClientRects().length) return false;
      const box = el.getBoundingClientRect();
      return box.width > 0 && box.height > 0 && box.left < rect.right && box.right > rect.left
        && box.top < rect.bottom && box.bottom > rect.top;
    });
    if (covered) bar.classList.add('is-low');
  }

  /** 서버 `_set_mark` 와 같은 잣대 - 프롬프트 + 네거티브, 쉼표 앞뒤 공백 무시. 둘 다 비면 ''. */
  function setMark(prompt, uc) {
    const norm = text => String(text || '').split(',').map(part => part.trim()).filter(Boolean).join(', ');
    const p = norm(prompt), u = norm(uc);
    return (p || u) ? `${p}\u0000${u}` : '';
  }

  /** 이 글을 가진 활성 슬롯의 표시 번호(C{n}). 없으면 0. */
  function duplicateOrdinal(prompt, uc) {
    const mark = setMark(prompt, uc);
    if (!mark) return 0;
    const slots = activeSlots(lastState);
    const at = slots.findIndex(({character}) => setMark(character.prompt, character.uc) === mark);
    return at + 1;
  }

  function slotsAreFull() {
    const max = Number(lastState && lastState.max_slots) || 0;
    return !!max && activeSlots(lastState).length >= max;
  }

  function findAvailable(state) {
    return !!(visible && open && !posEditing && state && !state.virtual && !isNarrowViewport());
  }

  function featCount() {
    return featTerms.inc.length + featTerms.exc.length;
  }

  /** 서버에 보낼 꼴 - 작품은 `work:<이름>`. */
  function featParams() {
    const enc = term => encodeURIComponent(term.kind === 'work' ? `work:${term.tag}` : term.tag);
    return [...featTerms.inc.map(term => `inc=${enc(term)}`), ...featTerms.exc.map(term => `exc=${enc(term)}`)];
  }

  function toggleFeat() {
    if (featEl) { closeFeat(); return; }
    // 결과는 Find 의 [캐릭터 · 작품] 목록이 보여 준다 - 판과 함께 연다.
    if (!findEl) openFind();
    if (findTab !== 'dex') setFindTab('dex');
    openFeat();
  }

  function closeFeat() {
    for (const line of ['inc', 'exc']) clearTimeout(featSugg[line]?.timer);
    featSugg.inc = featSugg.exc = null;
    featEl?.remove();
    featEl = null;
    mount?.querySelector('[data-cq-feat]')?.classList.remove('is-on');
    positionFind();
  }

  function openFeat() {
    featEl?.remove();
    featEl = document.createElement('div');
    featEl.className = 'cq-feat-pop';
    featEl.setAttribute('role', 'dialog');
    featEl.setAttribute('aria-label', '필터 - 검색 · 제외');
    // 후보 목록은 칸 **아래에 떠서** 밑의 줄 · Find 창을 덮는다 - 판 안의 줄로 두면 판이 길어져 창을 끌어내린다
    // (사용자 제보 2026-10-19). `.cq-feat-field` 가 기준 상자다.
    const line = (key, label, hint) =>
      `<div class="cq-feat-field"><div class="cq-feat-line"><span class="cq-feat-lab">${label}</span>`
      + `<div class="cq-feat-box" data-cqx-box="${key}"><span class="cq-feat-chips" data-cqx-chips="${key}"></span>`
      + `<input type="text" autocomplete="off" spellcheck="false" data-cqx-in="${key}" placeholder="${hint}"></div></div>`
      + `<div class="cq-feat-sugg" data-cqx-sugg="${key}" hidden></div></div>`;
    featEl.innerHTML = line('inc', '검색', '색 · 특징 · 가슴 · 작품')
      + line('exc', '제외', '뺄 것')
      + `<div class="cq-feat-foot"><span data-cqx-count></span>`
      + `<button type="button" data-cqx-clear>비우기</button></div>`;
    document.body.appendChild(featEl);
    featEl.addEventListener('input', onFeatInput);
    featEl.addEventListener('keydown', onFeatKey);
    featEl.addEventListener('click', onFeatClick);
    // 후보 줄을 누르는 동안 칸이 초점을 잃어 목록이 닫히지 않게 - 누르기는 click 에서 처리한다.
    featEl.addEventListener('mousedown', event => { if (event.target.closest('[data-cqx-pick]')) event.preventDefault(); });
    mount?.querySelector('[data-cq-feat]')?.classList.add('is-on');
    renderFeat();
    featEl.querySelector('[data-cqx-in="inc"]')?.focus();
  }

  function renderFeat() {
    if (!featEl) return;
    for (const key of ['inc', 'exc']) {
      const chips = featEl.querySelector(`[data-cqx-chips="${key}"]`);
      if (chips) {
        chips.innerHTML = featTerms[key].map((term, i) =>
          `<button type="button" class="cq-feat-chip is-${key}" data-cqx-del="${key}:${i}"`
          + ` aria-label="${escAttr(`${term.tag} 빼기`)}">${term.kind === 'work' ? '<em>작품</em>' : ''}`
          + `${escHtml(term.tag)}<i aria-hidden="true">×</i></button>`).join('');
      }
      paintFeatSugg(key);
    }
    const count = featEl.querySelector('[data-cqx-count]');
    if (count) {
      count.textContent = !featCount() ? '고른 낱말이 없습니다'
        : findDexLoading ? '찾는 중…'
          : findDexTotal === null ? '' : `${Number(findDexTotal).toLocaleString()}명`;
    }
    syncFeatButton();
    positionFeat();
    positionFind();
  }

  /** 단추의 수 · 켜짐만 고친다(패널 전체를 다시 그리지 않는다). */
  function syncFeatButton() {
    const button = mount?.querySelector('[data-cq-feat]');
    if (!button) return;
    const n = featCount();
    button.classList.toggle('has-terms', !!n);
    button.classList.toggle('is-on', !!featEl);
    const label = n ? `필터 · ${n}` : '필터';
    const text = [...button.childNodes].find(node => node.nodeType === 3);
    if (text && text.textContent !== label) text.textContent = label;
  }

  function onFeatInput(event) {
    const input = event.target.closest('[data-cqx-in]');
    if (!input) return;
    scheduleFeatSuggest(input.dataset.cqxIn, input.value);
  }

  function scheduleFeatSuggest(key, value) {
    const state = featSugg[key] || (featSugg[key] = {rows: [], active: -1, seq: 0, timer: 0});
    clearTimeout(state.timer);
    // 차례는 **칠 때** 올린다(Codex 리뷰) - 타이머가 돌 때 올리면 칸을 비우거나 바꾼 뒤 날아오던 앞 응답이 채택됐다.
    const mine = ++state.seq;
    const text = String(value || '').trim();
    // 한글은 한 글자로도 뜻이 있다(귀 · 뿔) - 영문은 두 글자부터(Artist Thumbnail 과 같다).
    const hangul = /[가-힣ㄱ-ㅎㅏ-ㅣ]/.test(text);
    if (!text || (!hangul && text.length < 2)) {
      state.rows = []; state.active = -1; state.pending = false; state.stale = false; paintFeatSugg(key); return;
    }
    // 보이던 후보는 앞 글자의 것이다 - 새 답이 올 때까지 흐리게 두고 고르지 못하게 한다(Codex 리뷰: pink 후보가 뜬 채
    // blue 로 바꾸고 Enter 를 치면 pink hair 가 들어갔다). 지우면 매 글자마다 목록이 깜박인다.
    if (state.rows.length && !state.stale) { state.stale = true; paintFeatSugg(key); }
    state.timer = setTimeout(async () => {
      state.timer = 0;
      let rows = [];
      let pending = false;
      try {
        const res = await fetch(`/api/character-viewer/feature-suggest?q=${encodeURIComponent(text)}`);
        const data = await res.json().catch(() => ({}));
        rows = Array.isArray(data.rows) ? data.rows : [];
        pending = !!data.pending;
      } catch (_) { return; }
      if (mine !== state.seq || featSugg[key] !== state || !featEl) return;
      if (pending) {
        // 태그 사전을 만드는 중(한글) - 알리고 잠시 뒤 같은 글자로 다시 묻는다(그사이 치면 차례가 바뀌어 멈춘다).
        state.rows = [];
        state.pending = true;
        paintFeatSugg(key);
        state.timer = setTimeout(() => {
          if (mine === state.seq && featSugg[key] === state && featEl) scheduleFeatSuggest(key, value);
        }, 1500);
        return;
      }
      state.pending = false;
      state.stale = false;
      const chosen = new Set([...featTerms.inc, ...featTerms.exc].map(term => `${term.kind}\u0000${term.tag}`));
      state.rows = rows.filter(row => !chosen.has(`${row.kind}\u0000${row.tag}`));
      // 정확히 친 것이 있으면 그것만 미리 고른다(Artist Thumbnail 과 같은 규칙).
      const typed = text.toLowerCase();
      state.active = state.rows.findIndex(row => String(row.tag).toLowerCase() === typed);
      paintFeatSugg(key);
    }, 160);
  }

  function paintFeatSugg(key) {
    const box = featEl?.querySelector(`[data-cqx-sugg="${key}"]`);
    if (!box) return;
    const state = featSugg[key];
    if (state?.pending && !state.rows.length) {
      box.innerHTML = '<div class="cq-feat-wait">태그 사전 준비 중…</div>';
      box.hidden = false;
      positionFind();
      return;
    }
    // 판의 높이가 바뀐다 - Find 창도 다시 앉힌다(positionFind 가 판을 먼저 앉힌다 · Codex 리뷰).
    if (!state || !state.rows.length) { box.hidden = true; box.innerHTML = ''; positionFind(); return; }
    box.classList.toggle('is-stale', !!state.stale);
    box.innerHTML = state.rows.map((row, i) =>
      `<button type="button" class="cq-feat-row${i === state.active ? ' is-on' : ''}" data-cqx-pick="${key}:${i}">`
      + `<span>${escHtml(row.tag)}</span><em>${escHtml(row.label || '')}</em>`
      + `<b>${Number(row.count || 0).toLocaleString()}</b></button>`).join('');
    box.hidden = false;
    positionFind();
    if (state.active >= 0) box.querySelectorAll('[data-cqx-pick]')[state.active]?.scrollIntoView({block: 'nearest'});
  }

  function pickFeat(key, row) {
    if (!row || featSugg[key]?.stale) return;          // 낡은 후보는 고르지 않는다
    const same = term => term.kind === row.kind && term.tag === row.tag;
    // 다른 줄에 있으면 옮긴다(같은 낱말을 찾으면서 빼는 일은 없다).
    featTerms.inc = featTerms.inc.filter(term => !same(term));
    featTerms.exc = featTerms.exc.filter(term => !same(term));
    featTerms[key].push({tag: row.tag, kind: row.kind, label: row.label});
    const input = featEl?.querySelector(`[data-cqx-in="${key}"]`);
    if (input) input.value = '';
    featSugg[key] = null;
    applyFeat();
    input?.focus();
  }

  /** 낱말이 바뀌었다 - 목록을 다시 받는다(사전 탭으로). */
  function applyFeat() {
    findDexTotal = null;
    if (findEl && findTab !== 'dex') setFindTab('dex');
    else if (findEl) void loadFindDex();
    renderFeat();
  }

  function onFeatKey(event) {
    const input = event.target.closest('[data-cqx-in]');
    // 한글 조합을 확정하는 Enter 는 isComposing 이 이미 false 일 수 있다 - keyCode 229 도 IME 의 것이다(Codex 리뷰).
    if (!input || event.isComposing || event.keyCode === 229) return;
    const key = input.dataset.cqxIn;
    const state = featSugg[key];
    const n = state ? state.rows.length : 0;
    if ((event.key === 'ArrowDown' || event.key === 'ArrowUp') && n) {
      event.preventDefault();
      // 끝에서 한 번 더 누르면 '아무것도 안 고름' 을 거친다(Artist Thumbnail 과 같다).
      const next = state.active + (event.key === 'ArrowDown' ? 1 : -1);
      state.active = next < -1 ? n - 1 : next >= n ? -1 : next;
      paintFeatSugg(key);
      return;
    }
    if (event.key === 'Enter') {
      event.preventDefault();
      // 고른 줄(없으면 맨 위) - 이 데이터에 없는 낱말은 넣지 않는다.
      if (n) pickFeat(key, state.rows[state.active >= 0 ? state.active : 0]);
      return;
    }
    if (event.key === 'Backspace' && !input.value && featTerms[key].length) {
      featTerms[key].pop();
      applyFeat();
    }
  }

  function onFeatClick(event) {
    const pick = event.target.closest('[data-cqx-pick]');
    if (pick) {
      const [key, index] = pick.dataset.cqxPick.split(':');
      pickFeat(key, featSugg[key]?.rows[Number(index)]);
      return;
    }
    const del = event.target.closest('[data-cqx-del]');
    if (del) {
      const [key, index] = del.dataset.cqxDel.split(':');
      featTerms[key].splice(Number(index), 1);
      applyFeat();
      return;
    }
    if (event.target.closest('[data-cqx-clear]')) {
      if (!featCount()) return;
      featTerms.inc = [];
      featTerms.exc = [];
      applyFeat();
      return;
    }
    // 빈 곳을 누르면 그 줄의 칸에 초점.
    const box = event.target.closest('[data-cqx-box]');
    if (box) box.querySelector('[data-cqx-in]')?.focus();
  }

  /** [필터] 판은 단추 줄 **바로 아래**에 뜬다 - 단추 줄이 패널 머리줄 옆(위)으로 올라갔다(사용자 지시 2026-10-19).
   *  아래에 자리가 없으면 위로. */
  function positionFeat() {
    const bar = mount?.querySelector('.cq-find-bar');
    if (!featEl || !bar) return;
    const rect = bar.getBoundingClientRect();
    const margin = 8;
    const width = featEl.offsetWidth, height = featEl.offsetHeight;
    const left = Math.max(margin, Math.min(rect.left, window.innerWidth - width - margin));
    const below = rect.bottom + 6;
    const above = rect.top - height - 6;
    // 줄이 예전 자리(아래 · `is-low`)로 내려가 있으면 예전처럼 위를 먼저 본다.
    const preferAbove = bar.classList.contains('is-low') && above >= margin;
    const top = !preferAbove && (below + height <= window.innerHeight - margin || above < margin)
      ? Math.max(margin, Math.min(below, window.innerHeight - height - margin))
      : above;
    featEl.style.left = `${Math.round(left)}px`;
    featEl.style.top = `${Math.round(top)}px`;
  }

  function closeFind() {
    closeFeat();
    if (findDismiss) {
      document.removeEventListener('mousedown', findDismiss, true);
      document.removeEventListener('keydown', findDismiss, true);
      document.removeEventListener('mouseup', onFindPointerUp, true);
      window.removeEventListener('blur', onFindPointerUp);
      findDismiss = null;
    }
    clearTimeout(findHeldTimer);
    findHeldTimer = 0;
    findHeld = false;
    findHeldRender = false;
    findEl?.remove();
    findEl = null;
    hideFindZoom();
    mount?.querySelector('[data-cq-find]')?.classList.remove('is-on');
  }

  // ── Find 썸네일 미리보기(사용자 지시 2026-10-19) ─────────────────────────────
  //  캐릭터 줄에 마우스를 올리면 Find 판 왼쪽에 크게(아티스트 리모컨 확대와 같은 결). 썸네일이 없으면 No Image.
  //  [히스토리 · 즐겨찾기] 줄은 사전 캐릭터가 아니라 슬롯 보관함이라 띄우지 않는다.
  let findZoomEl = null;

  function hideFindZoom() {
    if (findZoomEl) findZoomEl.hidden = true;
  }

  function showFindZoom(rowEl) {
    if (!findEl) return;
    if (!findZoomEl) {
      findZoomEl = document.createElement('div');
      findZoomEl.className = 'cq-find-zoom';
      findZoomEl.setAttribute('aria-hidden', 'true');
      document.body.appendChild(findZoomEl);
    }
    const el = findZoomEl;
    const img = rowEl.querySelector('img.cq-find-img');
    const name = rowEl.querySelector('.cq-find-text b')?.textContent || '';
    const sub = rowEl.querySelector('.cq-find-text span')?.textContent || '';
    const html = (img ? `<img alt="" decoding="async" src="${escAttr(img.getAttribute('src') || '')}">`
      : `<div class="cq-find-zoom-none">No Image</div>`)
      + `<div class="cq-find-zoom-cap"><b>${escHtml(name)}</b><span>${escHtml(sub)}</span></div>`;
    if (el._cqHtml !== html) { el._cqHtml = html; el.innerHTML = html; }
    el.hidden = false;
    // 자리 = Find 판 왼쪽 · 줄 높이 가운데 · 화면 안. 왼쪽에 자리가 없으면 오른쪽.
    const margin = 8;
    const panel = findEl.getBoundingClientRect();
    const row = rowEl.getBoundingClientRect();
    const width = el.offsetWidth;
    const height = el.offsetHeight;
    let left = panel.left - width - margin;
    if (left < margin) left = Math.min(window.innerWidth - width - margin, panel.right + margin);
    const top = Math.min(Math.max(margin, row.top + row.height / 2 - height / 2), window.innerHeight - height - margin);
    el.style.left = `${Math.round(left)}px`;
    el.style.top = `${Math.round(top)}px`;
  }

  function onFindHover(event) {
    const row = event.target.closest('[data-cqf-char], [data-cqf-hid-char]');
    if (row && findEl && findEl.contains(row)) showFindZoom(row); else hideFindZoom();
  }

  function openFind() {
    closeConnectMenu();
    closeFind();
    findEl = document.createElement('div');
    findEl.className = 'cq-find-pop';
    findEl.setAttribute('role', 'dialog');
    findEl.setAttribute('aria-label', '캐릭터 찾기');
    findEl.innerHTML =
      `<div class="cq-find-seg">`
      + `<button type="button" data-cqf-tab="dex">캐릭터 · 작품</button>`
      + `<button type="button" data-cqf-tab="lib">히스토리 · 즐겨찾기</button>`
      // [제외] - 숨긴 캐릭터(랜덤 디버그 줄의 [숨김] · 사용자 지시 2026-10-19). 누르면 숨김을 푼다.
      + `<button type="button" data-cqf-tab="hid">제외</button></div>`
      + `<input class="cq-find-q" type="search" autocomplete="off" spellcheck="false" data-cqf-q="1">`
      + `<div class="cq-find-list" data-cqf-list="1"></div>`
      // [현재 결과 -> 랜덤 와일드카드](사용자 지시 2026-10-19) - [캐릭터 · 작품] 에서만 보인다.
      + `<button type="button" class="cq-find-rw" data-cqf-rw="1" hidden></button>`;
    document.body.appendChild(findEl);
    findEl.addEventListener('click', onFindClick);
    findEl.addEventListener('mouseover', onFindHover);
    findEl.addEventListener('mouseleave', hideFindZoom);
    // 목록을 굴리면 줄이 마우스 밑에서 바뀐다 - 미리보기는 다음 mouseover 가 다시 띄운다.
    findEl.addEventListener('wheel', hideFindZoom, {passive: true});
    findEl.addEventListener('mousedown', () => {
      findHeld = true;
      clearTimeout(findHeldTimer);
      findHeldTimer = setTimeout(settleFindHeld, 1000);
    });
    findEl.addEventListener('input', event => {
      const input = event.target.closest('[data-cqf-q]');
      if (!input) return;
      findQuery[findTab] = input.value;
      if (findTab === 'dex') scheduleFindDex(); else renderFindList();
    });
    mount?.querySelector('[data-cq-find]')?.classList.add('is-on');
    setFindTab(findTab);
    positionFind();
    findEl.querySelector('[data-cqf-q]')?.focus();
    findDismiss = event => {
      if (event.type === 'keydown') {
        if (event.key !== 'Escape') return;
        // 한글 조합을 취소하는 Escape 는 IME 의 것이다 - Find 를 닫지 않는다(Codex 리뷰).
        if (event.isComposing || event.keyCode === 229) return;
        // 지금 칸의 후보 목록이 열려 있으면 그것만 닫는다(다른 줄 것을 먼저 닫지 않는다).
        const line = featEl?.contains(event.target) ? event.target.closest?.('[data-cqx-in]')?.dataset.cqxIn : '';
        const sugg = line ? featSugg[line] : null;
        if (sugg && (sugg.rows.length || sugg.pending)) {
          event.stopPropagation();
          clearTimeout(sugg.timer);
          sugg.seq += 1;
          sugg.rows = [];
          sugg.pending = false;
          paintFeatSugg(line);
          return;
        }
        closeFind();
        return;
      }
      if (featEl?.contains(event.target)) return;
      // 창 안 · 패널(Find 단추 포함 - 단추는 스스로 열고 닫는다)은 바깥이 아니다. 패널의 ✔ 를 누르며 여러 명을
      // 담는 동안 창이 닫히면 매번 다시 열어야 한다.
      if (findEl?.contains(event.target) || mount?.contains(event.target)) return;
      closeFind();
    };
    document.addEventListener('mousedown', findDismiss, true);
    document.addEventListener('keydown', findDismiss, true);
    document.addEventListener('mouseup', onFindPointerUp, true);
    window.addEventListener('blur', onFindPointerUp);
  }

  /** Find 단추 바로 위로 띄운다(단추는 패널 오른쪽 아래 바깥) - 위에 자리가 없으면 화면 안으로 당긴다. */
  function positionFind() {
    positionFeat();          // 패널이 다시 그려지면 단추 줄이 움직인다 - 판도 따라간다(Find 창 자리는 판을 본다)
    const button = mount?.querySelector('[data-cq-find]');
    if (!findEl || !button) return;
    const rect = button.getBoundingClientRect();
    const margin = 8;
    const width = findEl.offsetWidth, height = findEl.offsetHeight;
    const left = Math.max(margin, Math.min(rect.left, window.innerWidth - width - margin));
    // 단추 줄이 위(머리줄 옆)에 있다 - **아래로** 연다(사용자 지시 2026-10-19). 아래에 자리가 없을 때만 위로.
    const above = rect.top - height - 6;
    const low = !!mount?.querySelector('.cq-find-bar.is-low');
    let top = !(low && above >= margin) && (rect.bottom + 6 + height <= window.innerHeight - margin || above < margin)
      ? Math.max(margin, Math.min(rect.bottom + 6, window.innerHeight - height - margin))
      : above;
    if (featEl) {
      // [특징] 판이 단추 위(또는 아래)를 쓴다 - Find 창은 판과 단추를 피해 아래로, 자리가 없으면 위로 쌓는다.
      const feat = featEl.getBoundingClientRect();
      const featBelow = feat.top >= rect.bottom;
      const below = (featBelow ? feat.bottom : rect.bottom) + 6;
      const aboveAll = Math.min(feat.top, rect.top) - height - 6;
      if (below + height <= window.innerHeight - margin) top = below;
      else if (aboveAll >= margin) top = aboveAll;
      else top = Math.max(margin, window.innerHeight - height - margin);
    }
    findEl.style.left = `${Math.round(left)}px`;
    findEl.style.top = `${Math.round(top)}px`;
  }

  function setFindTab(tab) {
    findTab = tab === 'lib' ? 'lib' : tab === 'hid' ? 'hid' : 'dex';
    if (findTab !== 'dex' && featEl) closeFeat();      // 낱말은 [캐릭터 · 작품] 에만 걸린다
    if (!findEl) return;
    findEl.querySelectorAll('[data-cqf-tab]').forEach(el =>
      el.classList.toggle('is-on', el.dataset.cqfTab === findTab));
    const input = findEl.querySelector('[data-cqf-q]');
    if (input) {
      input.value = findQuery[findTab];
      input.placeholder = findTab === 'dex' ? '캐릭터 · 작품 이름' : findTab === 'hid' ? '숨긴 캐릭터 · 작품' : '이름 · 프롬프트 · 그룹';
    }
    if (findTab === 'dex' && !findDexRows.length && !findDexLoading) void loadFindDex();
    if (findTab === 'hid') void loadHidden();          // 열 때마다 새로 - 다른 창이 숨겼을 수 있다
    renderFindList();
  }

  function scheduleFindDex() {
    clearTimeout(findDexTimer);
    // 180ms - Manage 검색 탭과 같은 값(사람이 한 글자 치는 사이).
    findDexTimer = setTimeout(() => { findDexTimer = 0; void loadFindDex(); }, 180);
  }

  async function loadFindDex() {
    const seq = ++findDexSeq;
    findDexLoading = true;
    renderFindList();
    try {
      const parts = [
        'group=__ALL__', `query=${encodeURIComponent(findQuery.dex.trim())}`,
        'page=0', `per_page=${FIND_PER_PAGE}`, 'thumb_first=true',
        'recent_only=false', 'favorites_only=false',
        ...featParams(),
      ];
      const res = await fetch(`/api/character-viewer/list?${parts.join('&')}`);
      const data = await res.json().catch(() => ({}));
      // 낡은 응답은 버린다 - 한 글자마다 요청이 나가면 순서가 뒤집힌다.
      if (seq !== findDexSeq) return;
      if (!res.ok) throw new Error(data.error || '캐릭터를 불러오지 못했습니다.');
      findDexRows = Array.isArray(data.items) ? data.items : [];
      findDexTotal = Number.isFinite(Number(data.total)) ? Number(data.total) : null;
      findDexError = '';
    } catch (error) {
      if (seq !== findDexSeq) return;
      findDexRows = [];
      findDexError = error.message || String(error);
    }
    findDexLoading = false;
    renderFindList();
    renderFeat();
  }

  /** 보관함(활성이 아닌 것) - ★ 먼저, 그다음 그룹, 그다음 히스토리(최근 순). 검색은 이름 · 프롬프트 · 그룹. */
  function findLibRows() {
    const query = findQuery.lib.trim().toLowerCase();
    const rank = character => (character.favorite ? 0 : (String(character.group || '').trim() ? 1 : 2));
    return ((lastState && lastState.characters) || [])
      .map((character, index) => ({character, index}))
      .filter(({character}) => character && String(character.slot_state || '') !== 'active'
        && (String(character.prompt || '').trim() || String(character.uc || '').trim()
            || String(character.custom_name || '').trim()))
      .filter(({character}) => !query || [character.custom_name, character.prompt, character.group]
        .some(text => String(text || '').toLowerCase().includes(query)))
      .sort((a, b) => rank(a.character) - rank(b.character)
        || (Number(b.character.used_at) || 0) - (Number(a.character.used_at) || 0))
      .slice(0, 80);
  }

  function findTagHtml(ordinal) {
    return ordinal
      ? `<span class="cq-find-tag is-dup" title="이미 슬롯에 있습니다 - 누르면 C${ordinal} 을 켭니다">C${ordinal}</span>`
      : '<span class="cq-find-tag">+ 슬롯</span>';
  }

  function renderFindList() {
    const list = findEl && findEl.querySelector('[data-cqf-list]');
    if (!list) return;
    if (findHeld) { findHeldRender = true; return; }     // 누르는 중 - 뗀 뒤에 그린다(위 `findHeld`)
    const keepScroll = list.scrollTop;
    let html = '';
    const empty = text => `<div class="cq-find-empty">${escHtml(text)}</div>`;
    if (findTab === 'hid') {
      const query = findQuery.hid.trim().toLowerCase();
      const rows = (hidRows || []).filter(row => !query
        || `${row.character} ${row.group}`.toLowerCase().includes(query));
      html = rows.length ? rows.map(row => `<button type="button" class="cq-find-row"`
          + ` data-cqf-hid-group="${escAttr(row.group)}" data-cqf-hid-char="${escAttr(row.character)}">`
          + (row.thumbnail_url
            ? `<img class="cq-find-img" loading="lazy" decoding="async" alt="" src="${escAttr(row.thumbnail_url)}">`
            : `<span class="cq-find-img is-initial">${escHtml(String(row.character || '?').trim().charAt(0).toUpperCase() || '?')}</span>`)
          + `<span class="cq-find-text"><b>${escHtml(row.character)}</b>`
          + `<span>${escHtml(row.group)}${row.danbooru_posts != null ? ` · ${Number(row.danbooru_posts).toLocaleString()}` : ''}</span></span>`
          + `<span class="cq-find-tag">되돌리기</span></button>`).join('')
        : empty(hidLoading || hidRows === null ? '불러오는 중…'
          : query ? '맞는 캐릭터가 없습니다.' : '숨긴 캐릭터가 없습니다. 랜덤 캐릭터 줄의 [숨김] 으로 넣습니다.');
    } else if (findTab === 'lib') {
      const rows = findLibRows();
      html = rows.length ? rows.map(({character, index}) => {
        const name = String(character.custom_name || '').trim();
        const title = name || String(character.prompt || '').split(',').map(part => part.trim())
          .filter(Boolean).slice(0, 3).join(', ') || '(네거티브만)';
        const group = String(character.group || '').trim();
        const sub = character.favorite ? `★ 즐겨찾기${group ? ` · ${group}` : ''}`
          : group ? `그룹 · ${group}` : '히스토리';
        return `<button type="button" class="cq-find-row" data-cqf-lib="${index}"`
          + ` data-cqf-uuid="${escAttr(character.slot_uuid || '')}"`
          + ` title="${escAttr(String(character.prompt || ''))}">`
          + `<span class="cq-find-text"><b>${escHtml(title)}</b><span>${escHtml(sub)}</span></span>`
          + `${findTagHtml(duplicateOrdinal(character.prompt, character.uc))}</button>`;
      }).join('') : empty(findQuery.lib.trim() ? '맞는 캐릭터가 없습니다.' : '보관함이 비어 있습니다.');
    } else if (findDexError && !findDexRows.length) {
      html = empty(findDexError);
    } else if (!findDexRows.length) {
      html = empty(findDexLoading ? '찾는 중…' : '맞는 캐릭터가 없습니다.');
    } else {
      // 사전의 줄은 아직 프롬프트를 모른다(상세를 받아야 안다) - 중복 표는 이름으로 짐작하지 않는다. 서버가 판단한다.
      html = findDexRows.map(row => {
        const key = `${row.group}\u0000${row.character}`;
        const busy = findPicking === key;
        return `<button type="button" class="cq-find-row${busy ? ' is-busy' : ''}"`
          // title 을 두지 않는다 - 앱이 자체 툴팁으로 바꿔 띄우는데, 줄에 이미 보이는 이름 · 작품을 그대로 되풀이하며
          // 아래 줄을 덮는다(실측).
          + ` data-cqf-group="${escAttr(row.group)}" data-cqf-char="${escAttr(row.character)}">`
          + (row.thumbnail_url
            ? `<img class="cq-find-img" loading="lazy" decoding="async" alt="" src="${escAttr(row.thumbnail_url)}">`
            : `<span class="cq-find-img is-initial">${escHtml(String(row.character || '?').trim().charAt(0).toUpperCase() || '?')}</span>`)
          + `<span class="cq-find-text"><b>${escHtml(row.character)}</b>`
          + `<span>${escHtml(row.group)} · ${Number(row.count) || 0}</span></span>`
          + `<span class="cq-find-tag">${busy ? '담는 중…' : '+ 슬롯'}</span></button>`;
      }).join('');
    }
    // 같은 내용이면 갈아 끼우지 않는다 - 보관함 목록은 서버 에코마다 다시 그려 보는데(빠른 길 포함), 누르는 도중에
    // 줄이 새 요소로 바뀌면 크롬은 click 을 보내지 않는다(CHARACTER_WORKSPACE_CLAUDE.md 법 0).
    if (list._cqfHtml !== html) {
      list._cqfHtml = html;
      list.innerHTML = html;
      list.scrollTop = keepScroll;
    }
    renderFindFoot();
    positionFind();
  }

  /** 지금 [캐릭터 · 작품] 결과 전부를 세션 와일드카드 슬롯으로(사용자 지시 2026-10-19). 서버가 같은 조건으로 다시 센다. */
  let findRwBusy = false;
  async function makeRandomWildcard() {
    if (findRwBusy || !findDexTotal) return;
    findRwBusy = true;
    renderFindFoot();
    try {
      const res = await fetch('/api/character-viewer/session-wildcard', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          query: findQuery.dex.trim(),
          inc: featTerms.inc.map(term => (term.kind === 'work' ? `work:${term.tag}` : term.tag)),
          exc: featTerms.exc.map(term => (term.kind === 'work' ? `work:${term.tag}` : term.tag)),
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || '랜덤 와일드카드를 만들지 못했습니다.');
      showToast(`랜덤 와일드카드 슬롯 · ${Number(data.count).toLocaleString()}명 - 이 세션에만 있고 기록에 남지 않습니다`
        + (data.reroll_on_generate ? '' : ' (생성 때 재굴림이 꺼져 있으면 Random 마다 바뀝니다)'), 'success');
    } catch (error) {
      showToast(error.message || String(error), 'error');
    } finally {
      findRwBusy = false;
      renderFindFoot();
    }
  }

  function renderFindFoot() {
    const button = findEl?.querySelector('[data-cqf-rw]');
    if (!button) return;
    const show = findTab === 'dex' && !!findDexTotal;
    button.hidden = !show;
    if (!show) return;
    const label = findRwBusy ? '만드는 중…'
      : `현재 결과 → 랜덤 와일드카드 (${Number(findDexTotal).toLocaleString()}명)`;
    if (button.textContent !== label) button.textContent = label;
    button.disabled = findRwBusy;
  }

  function onFindClick(event) {
    if (event.target.closest('[data-cqf-rw]')) { void makeRandomWildcard(); return; }
    const tab = event.target.closest('[data-cqf-tab]');
    if (tab) { setFindTab(tab.dataset.cqfTab); findEl?.querySelector('[data-cqf-q]')?.focus(); return; }
    const hid = event.target.closest('[data-cqf-hid-char]');
    if (hid) { void unhideFind(hid.dataset.cqfHidGroup || '', hid.dataset.cqfHidChar || ''); return; }
    const lib = event.target.closest('[data-cqf-lib]');
    if (lib) { pickFindLib(Number(lib.dataset.cqfLib), lib.dataset.cqfUuid || ''); return; }
    const dex = event.target.closest('[data-cqf-char]');
    if (dex) void pickFindDex(dex.dataset.cqfGroup || '', dex.dataset.cqfChar || '');
  }

  /** 보관함 -> 슬롯. Manage 의 ↩ 와 같은 명령이다(★ · 그룹은 사본, 히스토리는 옮김 - 서버 규칙). */
  function pickFindLib(shownIndex, uuid) {
    // ⚠️ 줄에 적힌 번호는 그릴 때의 것이다 - 그 사이 다른 창이 보관함을 고쳤으면 그 번호에는 다른 캐릭터가 있다.
    //    **uuid 로 지금 자리를 찾는다**(Codex 리뷰 2026-10-15). 사라졌으면 목록을 새로 그리고 멈춘다.
    const chars = (lastState && lastState.characters) || [];
    const index = uuid ? chars.findIndex(item => String(item && item.slot_uuid || '') === uuid) : shownIndex;
    const character = chars[index];
    if (!character || String(character.slot_state || '') === 'active') {
      showToast('그 캐릭터는 보관함에 더 없습니다.', 'info');
      renderFindList();
      return;
    }
    const dup = duplicateOrdinal(character.prompt, character.uc);
    if (!dup && slotsAreFull()) { showToast(`활성 캐릭터 슬롯은 최대 ${lastState.max_slots}개입니다.`, 'info'); return; }
    // 번호는 이 목록을 그릴 때의 것이다 - uuid 를 함께 보내 서버가 그 캐릭터가 **지금 있는 자리**를 찾게 한다.
    setModuleParam('character', `char_slot_state_${index}`, 'active', {slotUuid: uuid});
    // 중복이면 서버가 'C{n} 을 켰습니다' 를 말한다 - 여기서 또 말하지 않는다.
    if (!dup) showToast('슬롯 맨 아래에 담았습니다.', 'info');
  }

  /** 사전 -> 슬롯. Manage 검색 탭의 [+ 슬롯] 과 같다(기본 변형 · 이름 = 캐릭터 이름). */
  async function pickFindDex(group, character) {
    const key = `${group}\u0000${character}`;
    if (!character || findPicking) return;
    findPicking = key;
    renderFindList();
    try {
      const res = await fetch('/api/character-viewer/detail', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        // 옵션을 못 박는다 - 안 넘기면 Characters 탭에 저장된 값(이름 숨김 등)을 읽는다(Manage 와 같은 까닭).
        body: JSON.stringify({group, character, variant: '',
                              options: {hide_charname: false, cosplay_enabled: false, auto_copyright: true}}),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || '상세를 불러오지 못했습니다.');
      const prompt = String(data.prompt?.character_prompt || '').trim();
      if (!prompt) { showToast('담을 프롬프트가 없습니다.', 'info'); return; }
      const dup = duplicateOrdinal(prompt, '');
      if (!dup && slotsAreFull()) { showToast(`활성 캐릭터 슬롯은 최대 ${lastState.max_slots}개입니다.`, 'info'); return; }
      // 한 번에 끝낸다(빈 슬롯을 만들고 번호를 찾아 채우면 그 사이 남의 에코가 끼어 남의 슬롯을 덮는다).
      setModuleParam('character', 'add_character', JSON.stringify({prompt, uc: '', custom_name: character}));
      if (!dup) showToast(`${character} 을(를) 슬롯 맨 아래에 담았습니다.`, 'info');
    } catch (error) {
      showToast(error.message || String(error), 'error');
    } finally {
      findPicking = '';
      renderFindList();
    }
  }

  // ── 랜덤 캐릭터 디버그 줄(사용자 지시 2026-10-19) ─────────────────────────────────────
  // 세션 와일드카드 슬롯(Find [현재 결과 -> 랜덤 와일드카드])이 켜져 있는 동안 패널 아래에 붙는다. PE 디버그와 같은 꼴 · 2줄.
  //   보이는 캐릭터 - Random · 생성이 굴리면 **마지막으로 뽑힌 것**(A), 히스토리 등으로 그림이 바뀌면 **그 그림의 것**(C).
  //   [★ favorite] = 캐릭터 탭과 같은 도감 즐겨찾기 · [숨김] = 앞으로 검색에 안 나온다(Find [제외] 에서 되돌린다).
  //   접으면 이름만(접힘은 이 브라우저에 기억한다).
  const ROLL_FOLD_KEY = 'naia.cq.rollFold';
  let rollFold = false;
  // [자세히] - 이번 캐릭터의 태그 줄을 줄 아래 임시 칸(읽기 전용 · 복사 가능)에 펼친다(사용자 지시 2026-10-19). 이 창에서만.
  let rollDetail = false;
  try { rollFold = localStorage.getItem(ROLL_FOLD_KEY) === '1'; } catch (error) { /* 못 읽으면 펼친 채로 */ }
  // 서버가 마지막으로 확인해 준 옵션 {key, options} - 다음 조작의 바탕. 재조회 답이 늦거나 실패해도 옛 옵션으로 덮지 않는다(Codex 리뷰 21차).
  let soptLast = null;
  let rollInfo = null;           // 서버 답 {active, count, source, item}
  let rollSeq = 0;
  let rollBusy = false;
  // 그림이 바뀌었거나 Random 이 굴렸는데 아직 답이 없다 - 지금 보이는 캐릭터는 옛 것이라 [★] [숨김] 을 막는다(Codex 리뷰).
  let rollStale = false;
  let rollLastAsk = 'last';      // 마지막으로 무엇을 물었나 - 옵션 바꾸는 사이 버린 답을 다시 물을 때 쓴다('last' | 'image')
  // 지금 줄이 보는 랜덤 슬롯(uuid + `__키__`) - 풀을 새로 만들면 바뀐다. 바뀌면 옛 캐릭터 · 수를 버리고 다시 묻는다(Codex 리뷰).
  let rollSlotKey = '';
  let rollImageTimer = 0;

  // 꺼 둔(✗) 랜덤 슬롯은 없는 것으로 친다 - [📌 고정] 으로 꺼졌을 때도 줄을 내린다(사용자 지시 2026-10-19).
  const liveSession = character => character && character.session_wildcard && !character.muted;

  function sessionSlot(state) {
    if (!state || state.virtual || !state.activated) return null;
    return activeSlots(state).find(({character}) => liveSession(character)) || null;
  }

  function sessionSlotOrdinal(state) {
    // 캐릭터 모듈이 꺼져 있으면 랜덤 슬롯도 안 굴린다 - 줄을 내리지 않는다.
    if (!state || state.virtual || !state.activated) return 0;
    const at = activeSlots(state).findIndex(({character}) => liveSession(character));
    return at + 1;
  }

  /** 서버에 묻는다 - prompts 를 주면 그 그림의 캐릭터에서(C), 안 주면 마지막으로 뽑힌 것(A). ids = 그 그림의 슬롯 id. */
  async function fetchRoll(prompts, ids = null) {
    if (!sessionSlotOrdinal(lastState)) { rollInfo = null; renderRoll(); return; }
    const seq = ++rollSeq;
    try {
      const res = await fetch('/api/character-viewer/session-roll', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(Array.isArray(prompts) ? {prompts, ids: Array.isArray(ids) ? ids : []} : {}),
      });
      const data = await res.json().catch(() => ({}));
      if (seq !== rollSeq || !res.ok) return;          // 낡은 답은 버린다
      rollInfo = data && data.active ? data : null;
      rollStale = false;
      // 서버가 지금 말해 준 옵션이 가장 새것이다 - 다른 창에서 바꿨어도 이것을 다음 조작의 바탕으로(Codex 리뷰 22차).
      if (rollInfo) soptLast = {key: rollInfo.key, options: rollInfo.options || {}};
    } catch (error) {
      return;
    }
    renderRoll();
    fitGridHeight();
  }

  /** 지금 보이는 그림의 메타 주소(PE 디버그와 같은 규칙). 생성 중 중간 그림 · 빈 화면은 null. */
  function previewMetaUrl() {
    const preview = document.getElementById('preview');
    if (!preview || !preview.classList.contains('show') || !preview.getAttribute('src')) return '';
    const source = preview.dataset.source || '';
    if (source === 'preview') return '';
    let path = source === 'saved' ? String(preview.dataset.path || '') : '';
    if (!path) {
      try {
        const url = new URL(preview.getAttribute('src'), location.href);
        const prefix = '/api/viewer/image/';
        if (url.pathname.startsWith(prefix)) path = decodeURIComponent(url.pathname.slice(prefix.length));
      } catch (error) { /* 주소가 아니면 아래로 */ }
    }
    if (path) return `/api/viewer/meta?${new URLSearchParams({path, full: '1'}).toString()}`;
    return source === 'current' ? '/api/result/metadata' : '';
  }

  /** 그림이 바뀌었다(히스토리를 눌렀거나 결과가 왔다) - 그 그림의 캐릭터 프롬프트로 묻는다. */
  async function rollFromImage() {
    rollImageTimer = 0;
    if (!sessionSlotOrdinal(lastState)) return;
    const url = previewMetaUrl();
    if (!url) return;
    const seq = ++rollSeq;
    let data = null;
    try {
      const res = await fetch(url, {cache: 'no-store'});
      data = res.ok ? await res.json() : null;
    } catch (error) {
      data = null;
    }
    if (seq !== rollSeq || !data) return;
    // 랜덤 슬롯이 그 그림의 몇 번째 캐릭터인가는 **서버가** 가린다 - 그림이 든 슬롯 id 로(없으면 생성과 같은 잣대로 센다).
    await fetchRoll(characterPromptsOf(data), characterIdsOf(data));
  }

  /** 메타에서 그 그림의 캐릭터 슬롯 id(`_executed_character_ids` - 슬롯 uuid). 없으면(디스크 PNG) null. */
  function characterIdsOf(data) {
    let found = null;
    const walk = (node, depth) => {
      if (found || depth > 6 || !node || typeof node !== 'object') return;
      if (Array.isArray(node._executed_character_ids)) { found = node._executed_character_ids.map(String); return; }
      for (const value of Object.values(node)) walk(value, depth + 1);
    };
    walk(data, 0);
    return found;
  }

  /** 메타에서 캐릭터 프롬프트들 - 앱 결과 · 히스토리(`_executed_characters`)와 디스크 PNG(NAI 의 `char_captions`)를 다 본다. */
  function characterPromptsOf(data) {
    const found = [];
    const walk = (node, depth) => {
      if (found.length || depth > 6 || !node) return;
      if (typeof node === 'string') {
        if (node.includes('char_captions') && node.trim().startsWith('{')) {
          try { walk(JSON.parse(node), depth + 1); } catch (error) { /* JSON 이 아니다 */ }
        }
        return;
      }
      if (typeof node !== 'object') return;
      for (const key of ['_executed_characters', 'characters']) {
        if (Array.isArray(node[key]) && node[key].some(item => typeof item === 'string')) {
          found.push(...node[key].filter(item => typeof item === 'string'));
          return;
        }
      }
      if (Array.isArray(node.char_captions)) {
        found.push(...node.char_captions.map(item => (typeof item === 'string' ? item : item?.char_caption || '')));
        return;
      }
      for (const value of Object.values(node)) walk(value, depth + 1);
    };
    walk(data, 0);
    return found.map(text => String(text || '')).filter(Boolean);
  }

  function watchPreviewForRoll() {
    const preview = document.getElementById('preview');
    if (!preview || preview._cqRollWatch || typeof MutationObserver === 'undefined') return;
    preview._cqRollWatch = new MutationObserver(records => {
      if (!records.some(record => record.attributeName === 'src' || record.attributeName === 'data-source')) return;
      if (preview.dataset.source === 'preview' || !sessionSlotOrdinal(lastState)) return;
      rollSeq += 1;          // 그림이 바뀌었다 - 지금 날아오는 답(옛 그림 · 옛 Random)은 버린다(Codex 리뷰)
      rollStale = true;
      rollLastAsk = 'image';
      renderRoll();
      clearTimeout(rollImageTimer);
      rollImageTimer = setTimeout(() => { void rollFromImage(); }, 150);
    });
    preview._cqRollWatch.observe(preview, {attributes: true, attributeFilter: ['src', 'data-source']});
  }

  function renderRoll() {
    if (!mount) return;
    let el = mount.querySelector('.cq-roll');
    const slot = sessionSlot(lastState);
    if (!slot) {
      // 랜덤 슬롯이 정말 없어졌다(지움 · 모듈 끔 · 가상) - 줄도 기억도 버린다.
      el?.remove();
      if (rollSlotKey) { rollSlotKey = ''; rollInfo = null; }
      return;
    }
    const ordinal = sessionSlotOrdinal(lastState);
    if (!visible || posEditing) {
      // 다른 탭 · POS 편집 동안은 줄만 내린다 - 돌아왔을 때 보던 그림의 캐릭터를 마지막 Random 으로 덮지 않는다(Codex 리뷰).
      el?.remove();
      return;
    }
    // 풀 = 슬롯 uuid + `__키__`. 글 전체로 보면 뒤에 `, smile` 만 덧붙여도 새 풀로 여겨 보던 그림의 캐릭터를 덮었다(Codex 리뷰).
    const slotKey = `${slot?.character?.slot_uuid || ''}\u0000${(String(slot?.character?.prompt || '').match(SESSION_TOKEN) || [''])[0]}`;
    if (slotKey !== rollSlotKey) {
      // 세션 슬롯이 막 생겼거나(패널이 다시 보이거나) **새 풀로 바뀌었다** - 옛 줄을 버리고 마지막으로 뽑힌 것을 묻는다.
      rollSlotKey = slotKey;
      rollInfo = null;
      watchPreviewForRoll();
      void fetchRoll(null);
    }
    if (!el) {
      el = document.createElement('div');
      el.className = 'cq-roll';
      const box = mount.querySelector('.cq-box');
      if (box) box.after(el); else mount.appendChild(el);
    }
    const item = rollInfo && rollInfo.item;
    const posts = item && Number.isFinite(Number(item.danbooru_posts)) && item.danbooru_posts !== null
      ? `<span class="cq-roll-n">${Number(item.danbooru_posts).toLocaleString()}</span>` : '';
    const empty = !rollInfo ? '…'
      : rollInfo.source === 'image' ? '이 그림에는 랜덤 캐릭터가 없습니다'
        : rollInfo.unresolved ? '어느 캐릭터인지 알 수 없습니다(출력 옵션)' : '아직 뽑히지 않았습니다';
    // 첫 줄(이름 줄)을 누르면 접고 편다 - 따로 접기 단추를 두지 않는다 · 슬롯 번호(C{n})는 숨긴다(사용자 지시 2026-10-19).
    const line1 = `<div class="cq-roll-l cq-roll-head" data-cq-roll-fold="1" role="button" tabindex="0"`
      + ` aria-expanded="${rollFold ? 'false' : 'true'}" title="${rollFold ? '펼치기' : '접기'}">`
      + (item ? `<b class="cq-roll-name">${escHtml(item.character)}</b>${rollFold ? '' : posts}`
        + (rollFold ? '' : `<span class="cq-roll-g">${escHtml(item.group)}</span>`)
        : `<span class="cq-roll-dim">${escHtml(empty)}</span>`)
      + `</div>`;
    const line2 = rollFold ? ''
      : `<div class="cq-roll-l"><span class="cq-roll-k">랜덤</span>`
        + `<span class="cq-roll-dim">${Number(rollInfo && rollInfo.count || 0).toLocaleString()}명</span>`
        + (item
          ? `<button type="button" class="cq-roll-btn${rollDetail ? ' is-on' : ''}" data-cq-roll-detail="1"`
            + ` aria-pressed="${rollDetail ? 'true' : 'false'}" title="이번 캐릭터에 쓴 태그를 아래에 펼칩니다">자세히</button>`
            + `<button type="button" class="cq-roll-btn" data-cq-roll-pin="1"${rollBusy || rollStale || soptBusy || !item.line ? ' disabled' : ''}`
            + ` title="랜덤 슬롯을 끄고 이 캐릭터를 맨 아래 슬롯에 켭니다">📌 고정</button>`
            + `<button type="button" class="cq-roll-btn${item.favorite ? ' is-fav' : ''}" data-cq-roll-fav="1"${rollBusy || rollStale ? ' disabled' : ''}>`
            + `${item.favorite ? '★ favorite 됨' : '★ favorite'}</button>`
            + `<button type="button" class="cq-roll-btn${item.hidden ? ' is-hid' : ''}" data-cq-roll-hide="1"${rollBusy || rollStale ? ' disabled' : ''}>`
            + `${item.hidden ? '숨김 취소' : '숨김'}</button>`
          : '')
        + `</div>`;
    // [자세히] 를 켜면 셋째 칸 = 태그 줄(읽기 전용 textarea - 사용자가 직접 골라 복사한다).
    // [복사] 단추는 두지 않는다 - 그대로 쓰려면 [📌 고정] 이 있다(사용자 지시 2026-10-19).
    const detail = !rollFold && rollDetail && item && item.line
      ? `<div class="cq-roll-detail"><textarea class="cq-roll-tags" readonly rows="3" spellcheck="false"`
        + ` aria-label="이번 캐릭터 태그">${escHtml(item.line)}</textarea></div>`
      : '';
    const html = line1 + line2 + detail;
    if (el._cqHtml !== html) { el._cqHtml = html; el.innerHTML = html; }
    // 접히면 흐리게 · CHARACTER 도 접혀 있으면 그 접힌 폭과 맞춘다(style.css `.cq-roll.is-fold`).
    el.classList.toggle('is-fold', rollFold);
    paintSessionOptions();
  }

  // ── 랜덤 슬롯 출력 옵션(사용자 지시 2026-10-19 · 결정 = 목업 기본안) ──
  //   [괄호 제거] 체크 · [작품명 제거] [캐릭터명 제거] 는 함께 켤 수 있다 · [이름+작품만] [이름만] 은 묶음(누르면 나머지를 끈다).
  //   수명 = 그 슬롯(풀). 서버가 풀을 원래 줄에서 다시 만든다(`/api/character-viewer/session-options`).
  let soptBusy = false;
  // 사용자가 고른 옵션 {key, options} - 누르는 즉시 화면에 보이고, 서버로는 가장 마지막 것만 차례로 보낸다(사용자 제보 2026-10-19:
  // 보내고 다시 읽는 동안 단추를 잠갔더니 그사이 누른 것이 버려지고(괄호 제거가 세 번 안 먹음) 잠금/풀림이 깜박였다).
  let soptWanted = null;

  function soptShown() {
    const key = rollInfo && rollInfo.key;
    if (soptWanted && soptWanted.key === key) return soptWanted.options;
    if (soptLast && soptLast.key === key) return soptLast.options;
    return (rollInfo && rollInfo.options) || {};
  }

  function paintSessionOptions() {
    const box = mount && mount.querySelector('[data-cq-sopt]');
    if (!box) return;
    const o = soptShown();
    const preset = o.drop_features ? (o.drop_copyright ? 'no' : 'nc') : '';
    // 첫 조회 전(풀 키를 모른다)에만 막는다 - 보내는 중에는 막지 않는다(누른 것은 모아 두었다가 이어서 보낸다).
    const locked = !rollInfo || !rollInfo.key;
    const btn = (key, label, on) => `<button type="button" class="cq-sopt-btn${on ? ' is-on' : ''}" data-cq-sopt-k="${key}"`
      + `${locked ? ' disabled' : ''}>${label}</button>`;
    const html = `<div class="cq-sopt-row">`
      + `<label class="cq-sopt-chk"><input type="checkbox" data-cq-sopt-paren="1"${o.parens ? ' checked' : ''}`
      + `${locked ? ' disabled' : ''}><span>괄호 제거</span></label>`
      + btn('cp', '작품명 제거', !!o.drop_copyright && !o.drop_features)
      + btn('nm', '캐릭터명 제거', !!o.drop_name)
      // 둘째 줄 = 묶음 둘. 나갈 줄 미리보기는 두지 않는다 - 디버그 줄이 결과를 보인다(사용자 지시 2026-10-19).
      + `</div><div class="cq-sopt-row">`
      + btn('nc', '이름+작품만', preset === 'nc')
      + btn('no', '이름만', preset === 'no')
      // 지금 풀(숨김 뺀 인원 · 지금 옵션의 줄)을 와일드카드 파일로(사용자 지시 2026-10-19).
      + `<button type="button" class="cq-sopt-btn cq-sopt-save" data-cq-wcsave="1"${locked ? ' disabled' : ''}`
      + ` title="지금 랜덤 풀(숨긴 캐릭터 빼고)을 와일드카드 파일로 저장합니다">와일드카드로 저장</button>`
      + `</div>`;
    if (box._cqHtml !== html) { box._cqHtml = html; box.innerHTML = html; }
    // 브라우저가 먼저 바꿔 둔 체크 상태를 보이는 값에 맞춘다(같은 HTML 이면 갈아 끼우지 않으므로).
    const check = box.querySelector('[data-cq-sopt-paren]');
    if (check && check.checked !== !!o.parens) check.checked = !!o.parens;
  }

  function setSessionOptions(key) {
    // 첫 조회가 오기 전(풀 키를 모른다)에는 못 바꾼다 - 빈 옵션 · 빈 키로 서버 설정을 덮었다(Codex 리뷰 23차).
    if (!rollInfo || !rollInfo.key) return;
    const o = {...soptShown()};
    if (key === 'paren') o.parens = !o.parens;
    if (key === 'cp') { o.drop_copyright = !(o.drop_copyright && !o.drop_features); o.drop_features = false; }
    if (key === 'nm') { o.drop_name = !o.drop_name; o.drop_features = false; }
    if (key === 'nc') { const on = !(o.drop_features && !o.drop_copyright); o.drop_features = on; o.drop_copyright = false; o.drop_name = false; }
    if (key === 'no') { const on = !(o.drop_features && o.drop_copyright); o.drop_features = on; o.drop_copyright = on; o.drop_name = false; }
    soptWanted = {key: rollInfo.key, options: o};
    paintSessionOptions();
    if (!soptBusy) void flushSessionOptions();
  }

  const sameOptions = (a, b) => ['parens', 'drop_copyright', 'drop_name', 'drop_features']
    .every(name => !!(a && a[name]) === !!(b && b[name]));

  /** 고른 옵션을 서버로 - 보내는 사이 또 누르면 끝난 뒤 마지막 것을 이어서 보낸다. 다 보내면 결과를 서버에서 다시 읽는다. */
  async function flushSessionOptions() {
    soptBusy = true;
    // 지금 날아오는 조회 답은 옛 옵션의 줄을 든다 - 버린다. 끝날 때까지 [📌 고정] 은 막는다(Codex 리뷰 15차).
    rollSeq += 1;
    renderRoll();
    try {
      while (soptWanted && rollInfo && soptWanted.key === rollInfo.key
             && !(soptLast && soptLast.key === soptWanted.key && sameOptions(soptLast.options, soptWanted.options))) {
        const wanted = soptWanted;
        const item = rollInfo.item;
        const res = await fetch('/api/character-viewer/session-options', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({...wanted.options, key: wanted.key, group: item?.group || '', character: item?.character || ''}),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.error || '옵션을 바꾸지 못했습니다.');
        soptLast = {key: data.key, options: data.options || wanted.options};
        if (rollInfo && rollInfo.key === data.key) {
          rollInfo.options = soptLast.options;
          if (Number.isFinite(Number(data.count))) rollInfo.count = Number(data.count);
          if (rollInfo.item && rollInfo.item === item && data.line) rollInfo.item.line = data.line;
        }
      }
      soptWanted = null;
    } catch (error) {
      soptWanted = null;            // 서버 값으로 되돌려 보인다
      showToast(error.message || String(error), 'error');
    }
    // 줄 · 옵션 · 수를 **서버에서 다시 읽는다**(서버가 진실 - 그사이 시작한 조회가 옛 옵션을 들고 와도 덮인다 · Codex 리뷰 16차).
    rollStale = true;
    renderRoll();
    try {
      await (rollLastAsk === 'image' && previewMetaUrl() ? rollFromImage() : fetchRoll(null));
    } finally {
      soptBusy = false;
      renderRoll();
      // 다시 읽는 사이 또 눌렀으면 이어서 보낸다.
      if (soptWanted) void flushSessionOptions();
    }
  }

  // ── [와일드카드로 저장](사용자 지시 2026-10-19) ─────────────────────────────
  //  지금 세션 풀에서 숨기지 않은 인원을 지금 출력 옵션의 줄 그대로 와일드카드 파일로 쓴다. 위치 = 와일드카드 관리 모듈의
  //  Browse Files 와 같은 폴더 목록(안 고르면 최상층) · 같은 폴더에 같은 이름은 저장하지 않는다. 랜덤 슬롯은 그대로 둔다.
  let wcSave = null;          // {back, key, folder, tree, busy}

  function closeWcSave() {
    if (!wcSave) return;
    wcSave.back.remove();
    document.removeEventListener('keydown', onWcSaveKey, true);
    wcSave = null;
  }

  function onWcSaveKey(event) {
    if (event.key !== 'Escape') return;
    event.stopPropagation();
    closeWcSave();
  }

  /** 그 폴더(빈 글 = 최상층)에 바로 든 파일 이름들(.txt 뺀 · 소문자) - 같은 이름 검사용. */
  function wcSaveNames(folder) {
    const names = new Set();
    for (const item of (wcSave && wcSave.tree) || []) {
      if (!folder && item.type === 'file') names.add(String(item.name || '').replace(/\.txt$/i, '').toLowerCase());
      if (folder && item.type === 'folder' && item.name === folder) {
        for (const file of item.files || []) {
          const rest = String(file.path || '').slice(folder.length + 1);
          if (rest && !rest.includes('/')) names.add(rest.replace(/\.txt$/i, '').toLowerCase());
        }
      }
    }
    return names;
  }

  function wcSaveCheck() {
    if (!wcSave) return '';
    const input = wcSave.back.querySelector('[data-wcs-name]');
    const errEl = wcSave.back.querySelector('[data-wcs-err]');
    const name = String(input?.value || '').trim().replace(/\.txt$/i, '');
    let error = '';
    if (!name) error = '이름을 적으세요.';
    else if (/[\\/:*?"<>|]/.test(name) || name.startsWith('.')) error = '이름에 / \\ : * ? " < > | 는 쓸 수 없습니다.';
    else if (wcSaveNames(wcSave.folder).has(name.toLowerCase())) error = '이 폴더에 같은 이름이 있습니다.';
    if (errEl) { errEl.textContent = error; errEl.classList.remove('is-ok'); }
    const ok = wcSave.back.querySelector('[data-wcs-ok]');
    if (ok) ok.disabled = Boolean(error) || wcSave.busy;
    return error;
  }

  function paintWcSaveTree() {
    if (!wcSave) return;
    const treeEl = wcSave.back.querySelector('[data-wcs-tree]');
    const whereEl = wcSave.back.querySelector('[data-wcs-where]');
    const folder = wcSave.folder;
    let html = `<button type="button" class="cq-wcs-row is-root${folder ? '' : ' is-sel'}" data-wcs-folder="">(최상층)</button>`;
    for (const item of wcSave.tree) {
      if (item.type === 'folder') {
        const open = item.name === folder;
        html += `<button type="button" class="cq-wcs-row is-folder${open ? ' is-sel' : ''}" data-wcs-folder="${escHtml(item.name)}">`
          + `${open ? '▾' : '▸'} ${escHtml(item.name)} <span class="cq-wcs-n">(${(item.files || []).length})</span></button>`;
        if (open) {
          html += (item.files || []).map(file => `<div class="cq-wcs-row is-file is-in">${escHtml(String(file.path || '').slice(item.name.length + 1))}</div>`).join('');
        }
      } else {
        html += `<div class="cq-wcs-row is-file">${escHtml(item.name)}</div>`;
      }
    }
    treeEl.innerHTML = html;
    if (whereEl) whereEl.textContent = folder ? `${folder}/` : '(최상층)';
    wcSaveCheck();
  }

  async function openWcSave() {
    closeWcSave();
    let info = null;
    try {
      const res = await fetch('/api/character-viewer/session-save', {cache: 'no-store'});
      info = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(info.error || '랜덤 슬롯이 없습니다.');
    } catch (error) {
      showToast(error.message || String(error), 'error');
      return;
    }
    const back = document.createElement('div');
    back.className = 'cq-wcs-back';
    back.innerHTML = `<div class="cq-wcs" role="dialog" aria-label="와일드카드로 저장">`
      + `<div class="cq-wcs-head"><b>와일드카드로 저장</b><span class="cq-wcs-dim">숨김 뺀 ${Number(info.count || 0).toLocaleString()}명</span>`
      + `<button type="button" class="cq-wcs-x" data-wcs-close="1" aria-label="닫기">×</button></div>`
      + `<div class="cq-wcs-tree" data-wcs-tree></div>`
      + `<div class="cq-wcs-form">`
      + `<div class="cq-wcs-line"><span class="cq-wcs-dim">위치</span><span data-wcs-where></span></div>`
      + `<div class="cq-wcs-line"><span class="cq-wcs-dim">이름</span><input type="text" class="cq-wcs-name" data-wcs-name`
      + ` spellcheck="false" autocomplete="off" placeholder="idolmaster_girls"><span class="cq-wcs-dim">.txt</span></div>`
      + `<div class="cq-wcs-err" data-wcs-err></div></div>`
      + `<div class="cq-wcs-foot"><button type="button" class="cq-wcs-btn" data-wcs-close="1">취소</button>`
      + `<button type="button" class="cq-wcs-btn is-ok" data-wcs-ok="1">저장</button></div></div>`;
    document.body.appendChild(back);
    wcSave = {back, key: info.key, folder: '', tree: Array.isArray(info.tree) ? info.tree : [], busy: false};
    back.addEventListener('mousedown', event => { if (event.target === back) closeWcSave(); });
    back.addEventListener('click', event => {
      if (event.target.closest('[data-wcs-close]')) { closeWcSave(); return; }
      const row = event.target.closest('[data-wcs-folder]');
      if (row && wcSave) { wcSave.folder = row.dataset.wcsFolder || ''; paintWcSaveTree(); return; }
      if (event.target.closest('[data-wcs-ok]')) void saveWcSave();
    });
    back.addEventListener('input', event => { if (event.target.closest('[data-wcs-name]')) wcSaveCheck(); });
    back.addEventListener('keydown', event => {
      if (event.key === 'Enter' && event.target.closest('[data-wcs-name]')) { event.preventDefault(); void saveWcSave(); }
    });
    document.addEventListener('keydown', onWcSaveKey, true);
    paintWcSaveTree();
    back.querySelector('[data-wcs-name]')?.focus();
  }

  async function saveWcSave() {
    if (!wcSave || wcSave.busy || wcSaveCheck()) return;
    const state = wcSave;
    const name = String(state.back.querySelector('[data-wcs-name]')?.value || '').trim();
    state.busy = true;
    wcSaveCheck();
    try {
      const res = await fetch('/api/character-viewer/session-save', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({key: state.key, folder: state.folder, name}),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || '저장하지 못했습니다.');
      if (wcSave === state) closeWcSave();
      showToast(`${data.wildcard} 로 저장했습니다 (${Number(data.count || 0).toLocaleString()}줄).`, 'success');
    } catch (error) {
      state.busy = false;
      if (wcSave !== state) return;
      wcSaveCheck();
      const errEl = state.back.querySelector('[data-wcs-err]');
      if (errEl) errEl.textContent = error.message || String(error);
    }
  }

  /** [📌 고정](사용자 결정 2026-10-19) - 랜덤 슬롯을 끄고, 보이는 캐릭터를 지금 옵션의 줄로 맨 아래 슬롯에 켠다. 기존 길만 쓴다
   *  (add_character - 같은 글이 이미 있으면 서버가 그 슬롯을 켠다 · char_muted). */
  async function pinRoll() {
    const item = rollInfo && rollInfo.item;
    if (!item || !item.line || rollBusy || rollStale || soptBusy) return;
    const dup = duplicateOrdinal(item.line, '');
    if (!dup && slotsAreFull()) { showToast(`활성 캐릭터 슬롯은 최대 ${lastState.max_slots}개입니다.`, 'info'); return; }
    // 넣기와 끄기는 서버가 한 잠금 안에서 한다 - 넣기가 막히면 끄지 않는다(Codex 리뷰 23차).
    rollBusy = true;
    renderRoll();
    try {
      const res = await fetch('/api/character-viewer/session-pin', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({key: rollInfo.key, group: item.group, character: item.character}),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || '고정하지 못했습니다.');
      const slot = sessionSlot(lastState);
      if (slot) openSlots.delete(slot.index);
      showToast(`${item.character} 을(를) 맨 아래 슬롯에 켜고 랜덤 슬롯을 껐습니다.`, 'info');
    } catch (error) {
      showToast(error.message || String(error), 'error');
    } finally {
      rollBusy = false;
      renderRoll();
    }
  }

  async function rollToggle(kind) {
    const item = rollInfo && rollInfo.item;
    if (!item || rollBusy || rollStale) return;
    const sentInfo = rollInfo;            // 응답이 올 때 줄이 다른 풀 · 다른 캐릭터면 수를 덮지 않는다(Codex 리뷰)
    rollBusy = true;
    renderRoll();
    try {
      const fav = kind === 'fav';
      const res = await fetch(fav ? '/api/character-viewer/favorite' : '/api/character-viewer/hidden', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(fav
          ? {group: item.group, character: item.character, favorite: !item.favorite}
          : {group: item.group, character: item.character, hidden: !item.hidden}),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || '바꾸지 못했습니다.');
      if (fav) {
        item.favorite = !!data.favorite;
        // 캐릭터 탭이 들고 있는 목록(즐겨찾기 보기 포함)도 낡았다 - 다음에 열 때 다시 읽게 한다(Codex 리뷰).
        try { window.dispatchEvent(new CustomEvent('naia:character-hidden-changed')); } catch (error) { /* 없으면 그만 */ }
        showToast(item.favorite ? `${item.character} - 즐겨찾기에 넣었습니다` : `${item.character} - 즐겨찾기에서 뺐습니다`, 'info');
      } else {
        afterHiddenChanged();
        item.hidden = !!data.hidden;
        if (rollInfo === sentInfo && Number.isFinite(Number(data.session_count))) rollInfo.count = Number(data.session_count);
        showToast(item.hidden ? `${item.character} - 숨겼습니다. 검색 · 랜덤에서 빠지고 Find [제외] 에서 되돌립니다`
          : `${item.character} - 숨김을 풀었습니다`, 'info');
        hidRows = null;
        if (findEl && findTab === 'hid') void loadHidden();
      }
    } catch (error) {
      showToast(error.message || String(error), 'error');
    } finally {
      rollBusy = false;
      renderRoll();
    }
  }

  /** 숨김이 바뀌었다 - 들고 있던 검색 목록은 낡았다. Find 사전 목록은 비워(지금 보고 있으면 다시 읽고), 캐릭터 탭에는
   *  다음에 열 때 다시 읽으라고 알린다(Codex 리뷰). */
  function afterHiddenChanged() {
    findDexSeq += 1;
    findDexLoading = false;
    findDexRows = [];
    if (findEl && findTab === 'dex') void loadFindDex();
    try { window.dispatchEvent(new CustomEvent('naia:character-hidden-changed')); } catch (error) { /* 없으면 그만 */ }
  }

  /** Random 이 굴렸다 - 기다리던 그림 읽기는 접고(그보다 Random 이 나중이다) 마지막으로 뽑힌 것을 보인다(A). */
  function noteRandom() {
    clearTimeout(rollImageTimer);
    rollImageTimer = 0;
    rollStale = true;
    rollLastAsk = 'last';
    renderRoll();
    void fetchRoll(null);
  }

  // ── Find [제외] - 숨긴 캐릭터 목록. 줄을 누르면 숨김을 푼다. ──
  async function loadHidden() {
    const seq = ++hidSeq;
    hidLoading = true;
    renderFindList();
    try {
      const res = await fetch('/api/character-viewer/hidden', {cache: 'no-store'});
      const data = await res.json().catch(() => ({}));
      if (seq !== hidSeq) return;
      if (!res.ok) throw new Error(data.error || '제외 목록을 불러오지 못했습니다.');
      hidRows = Array.isArray(data.items) ? data.items : [];
    } catch (error) {
      if (seq !== hidSeq) return;
      hidRows = [];
      showToast(error.message || String(error), 'error');
    }
    hidLoading = false;
    renderFindList();
  }

  async function unhideFind(group, character) {
    try {
      const res = await fetch('/api/character-viewer/hidden', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({group, character, hidden: false}),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || '되돌리지 못했습니다.');
      showToast(`${character} - 다시 검색에 나옵니다`, 'info');
      afterHiddenChanged();
      const item = rollInfo && rollInfo.item;
      if (item && item.group === group && item.character === character) { item.hidden = false; renderRoll(); }
    } catch (error) {
      showToast(error.message || String(error), 'error');
    }
    void loadHidden();
  }

  function setVisible(next) {
    visible = !!next;
    // 보이기로 했으면 **다시 그린다.**
    //
    // ⚠️ 예전에는 `!mount` 일 때만 그렸다. 그런데 `render()` 는 안 보이는 동안 온 상태를
    //    `lastState` 에 넣어 두기만 하고 DOM 은 안 건드린다 - 이미 mount 가 있으면 그
    //    사이에 온 상태가 **영영 화면에 못 올라온다.** 사용자가 한 번 누를 때까지
    //    옛 화면이 남는다(사용자 제보 2026-08-26: 인페인트에 들어가도 (가상) 이
    //    바로 안 뜨고 누른 뒤에야 바뀐다).
    if (visible && lastState) render(lastState, true);
    // POS 편집 중에는 패널을 감춘다(A안) - 띠의 종료 버튼이 나가는 문이다.
    if (mount) mount.classList.toggle('open', visible && !posEditing);
    // 패널이 사라지면 편집도 끝난다 - 무대만 남으면 나갈 문이 없다.
    if (!visible && posEditing) setPosEditing(false);
    if (!visible) closeFind();
    renderRoll();
    syncViewerShift();
  }

  function render(state, force) {
    if (state) lastState = state;
    if (state) settleRefresh(state);
    if (!visible) return;
    const current = lastState;
    if (!current) return;
    // 방금 추가한 슬롯은 **펼친 채로** 나온다(사용자 지정) - 추가한 이유가 거기에
    // 뭔가 적으려는 것이라, 접힌 채 나오면 한 번 더 눌러야 한다.
    //
    // ⚠️ 새 슬롯의 인덱스는 **서버 에코가 와야** 안다(`add_character` 는 백엔드가
    //    프레임을 붙이고 정렬까지 한다). 그래서 누를 때 세어 둔 수보다 늘어난
    //    순간에 마지막 활성 슬롯을 편다.
    if (pendingAddOpen !== null) {
      const now = activeSlots(current);
      if (now.length > pendingAddOpen) {
        openSlots.add(now[now.length - 1].index);
        pendingAddOpen = null;
        force = true;
      }
    }
    ensureMount();
    const nextSignature = signature(current);
    if (!force && nextSignature === lastSignature) {
      syncValues(current); bindAssist(); renderRoll(); fitGridHeight();
      // 보관함은 서명에 없다(활성 슬롯 구조만 본다) - 다른 창이 보관함을 고친 상태도 이 길로 온다. Find 의 보관함
      // 목록은 여기서도 고친다(Codex 리뷰 2026-10-15). 내용이 같으면 `renderFindList` 가 갈아 끼우지 않는다.
      if (findEl && findTab === 'lib') renderFindList();
      // ⚠️ 여기서도 무대를 다시 그린다. 프롬프트를 고쳐도 서명은 그대로라(내용은
      //    서명에 없다) 이 경로로 빠지는데, 칩 이름은 프롬프트에서 나온다 -
      //    빼먹으면 편집 중 칩이 옛 이름에 굳는다(실측).
      if (posEditing) renderStage();
      return;
    }
    // 여기부터는 머리줄을 통째로 다시 그린다 - 열려 있던 Connect 메뉴는 사라진 칩을
    // 가리키게 되고, 담고 있던 인덱스도 옛 것이다. 닫고 간다.
    closeConnectMenu();
    const slots = activeSlots(current);
    // POS 편집 중에는 패널을 통째로 감춘다(사용자 결정 A안) - 그림 위를 가장 적게
    // 가리는 길이고, 나가는 문은 띠의 종료 버튼이 맡는다.
    const body = open
      ? `<div class="cq-grid">`
        + slots.map(({character, index}, i) =>
            slotHtml(character, index, i + 1, slots.length, slots)).join('')
        // Manage 는 모듈 팝업을 연다 - 실수로 ▼ 로 내린 슬롯을 되살릴 곳이 거기다
        // (여기에는 비활성 무리가 보이지 않는다).
        + `<div class="cq-foot">`
        + `<button type="button" class="cq-add" data-cq-add="1">+ Add Character</button>`
        // 캐릭터 모듈 창의 "Generate 때 와일드카드 재굴림" 과 **같은 값**(`reroll_on_generate`)이다 - 끄면 Random 이
        // 굴린 값을 Generate 가 그대로 쓰고, 바꾸고 싶을 때 [Refresh] 를 누른다. 예전엔 아래 줄에 긴 글로 따로 있어
        // 패널 밑으로 밀려 보였다(사용자 지정 2026-09-30: 디자인 개선) - [Add] 줄의 켜고 끄는 단추로 올린다.
        + (current.virtual
          ? ''
          : `<label class="cq-reroll" title="켜면 Generate 때마다 캐릭터 와일드카드를 새로 굴립니다.`
            + ` 끄면 Random · Refresh 가 굴린 값을 그대로 씁니다."><input type="checkbox" data-cq-reroll="1"`
            + `${current.reroll_on_generate ? ' checked' : ''}><span>생성 때 재굴림</span></label>`)
        // ⚠️ 모바일에서는 **Manage 를 내보내지 않는다**(사용자 지정 2026-09-03).
        //    이 버튼이 여는 캐릭터 모듈 팝업은 좁은 화면에 맞춰져 있지 않아, 열면
        //    화면을 덮고 빠져나오기 어렵다. 여기서 안 그리는 것이 가장 확실하다.
        + (isNarrowViewport()
          ? ''
          : `<button type="button" class="cq-manage" data-cq-manage="1">Manage</button>`)
        + `</div>`
      : '';
    // 머리는 **버튼 하나가 아니라 줄**이다. 활성화 토글과 POS 를 나란히 두어야
    // 하는데, <button> 안에 <input> 이나 <button> 을 넣으면 마크업이 깨지고
    // 안쪽을 눌러도 바깥 토글이 먼저 먹는다.
    const enabled = !!current.activated;
    // Rnd Res 가 켜지면 CUSTOM 을 **AUTO 로 되돌린다.** 좌표가 살아 있으면 다음
    // 생성에서 다른 비율의 캔버스에 그대로 실려 나가 구도가 어긋난다.
    // ⚠️ 한 번만 보낸다 - 에코마다 쏘면 서버와 핑퐁이 된다.
    if (posBlockedByRandom()) {
      if (posEditing) setPosEditing(false);
      else if (posPeek) setPosPeek(false);
      if (posModeOf(current) === 'custom' && !randomPosForced) {
        randomPosForced = true;
        setModuleParam('character', 'position_mode', 'auto');
      }
    } else {
      randomPosForced = false;
    }
    const posMode = posBlockedByRandom() ? 'auto' : posModeOf(current);
    const custom = posMode === 'custom';
    const posLocked = hasConnectedSlot(current) || posBlockedByRandom();
    // ⚠️ 이 아래 `innerHTML` 이 `.cq-grid` 를 **새 요소로 갈아치운다** - 스크롤이 0 으로
    //    돌아간다. 서명이 바뀌는 일은 편집 중에도 일어나므로(해상도 변경 · Rnd Res 로
    //    생성 · 슬롯 접기 · Connect · POS 전환 · 활성화 토글), 길게 적던 사용자는 보던
    //    자리를 잃는다(사용자 제보: "프롬 적는데 자꾸 스크롤이 맨 위로 갱신된다").
    //    실측: 해상도 하나만 바꿔도 284 -> 0. 자리는 여기서 쥐고 아래에서 되돌린다.
    const keepScroll = mount.querySelector('.cq-grid')?.scrollTop || 0;
    mount.innerHTML = `<div class="cq-box${open ? ' is-open' : ''}">`
      + `<div class="cq-head-row">`
      + `<button type="button" class="cq-head" data-cq-head="1"`
      + ` aria-expanded="${open ? 'true' : 'false'}">`
      + '<span class="cq-caret" aria-hidden="true">▸</span>'
      + `<span class="cq-title">CHARACTER</span>`
      + `</button>`
      // 가상 캐릭터 프롬프트는 **메인과 갈라져 있다** - 여기서 고친 것이 메인에 안 남고,
      // 인페인트 요청에만 실린다. 그 사실을 머리말이 말해 준다(사용자 지정).
      //
      // ⚠️ 머리 **버튼 안이 아니라 줄의 형제**로 둔다. 버튼은 `flex:1` 로 눌리는데
      //    안에는 `min-width:78px` 인 제목이 있어, 배지를 넣으면 버튼 밖으로 삐져나와
      //    옆의 `활성화` 를 덮는다(실측: 버튼 오른쪽 끝 145 vs 배지 161).
      // `virtual_label` = 어느 쪽의 가상인가(인셋 - 2026-10-18). 없으면 인페인트 세션이다.
      + (lastState && lastState.virtual
        ? `<span class="cq-virtual">가상${lastState.virtual_label ? ` · ${escHtml(lastState.virtual_label)}` : ''}</span>`
        : '')
      + `<label class="cq-enable"><input type="checkbox" data-cq-enable="1"`
      + `${enabled ? ' checked' : ''}><span>활성화</span></label>`
      // POS 세 상태. AUTO 는 고정 자리, CUSTOM 은 슬롯이 기억한 자리, RAND 는
      // 생성 요청마다 새로 굽는 무작위 배치다. 옮길 원이 있는 CUSTOM 에서만
      // 편집 버튼이 생긴다 - RAND 의 자리는 누를 시점에 아직 존재하지 않는다.
      // Connect 중에는 CUSTOM 에 못 박힌다 - 자물쇠를 붙여 "왜 안 바뀌는가" 를
      // 누르기 전에 알려 준다(누르면 토스트가 이유를 말한다).
      + `<button type="button" class="cq-pos is-${posMode}${posLocked ? ' is-locked' : ''}"`
      + (posLocked
          ? ' data-naia-guide="Connect 를 쓰는 동안에는 POS 가 CUSTOM 으로 고정됩니다.\\n같은 캐릭터를 칸마다 직접 앉히는 기능이라 AUTO/RAND 가 자리를 정하면 안 됩니다."'
          : '')
      + ` data-cq-posmode="1">POS : ${POS_LABEL[posMode]}${posLocked ? ' &#128274;' : ''}</button>`
      + (custom
          ? `<button type="button" class="cq-pos cq-pos-edit" data-cq-posedit="1">POS</button>`
          : '')
      + `<span class="cq-count">${slots.length}</span>`
      + `</div><div class="cq-body">${body}</div></div>`
      // [Find] - 패널 **바깥**, Manage 옆(오른쪽 아래 모서리)에 뜬다(사용자 지정 2026-10-15). 상자는 overflow 로
      // 자르므로 상자의 형제로 둔다. 가상(인페인트 세션) · 좁은 화면 · 접힘에는 내지 않는다.
      + (findAvailable(current)
          ? `<div class="cq-find-bar">`
            + `<button type="button" class="cq-find${findEl ? ' is-on' : ''}" data-cq-find="1"`
            + ` aria-label="캐릭터 찾기 - 캐릭터 · 작품 · 히스토리 · 즐겨찾기">`
            + `<svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="7" cy="7" r="4.6"/><path d="M10.5 10.5 14 14"/></svg>`
            + `Find</button>`
            // [필터] - 검색 · 제외 판을 연다(사용자 지시 2026-10-19 · 이름 = 필터). 고른 낱말이 있으면 수를 단다.
            + `<button type="button" class="cq-find cq-feat-btn${featEl ? ' is-on' : ''}${featCount() ? ' has-terms' : ''}"`
            + ` data-cq-feat="1" aria-label="필터 - 색 · 특징 · 가슴 · 작품으로 찾고 뺍니다">`
            + `<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M2.5 3.5h11l-4.2 5v4l-2.6 1.2V8.5z"/></svg>`
            + `필터${featCount() ? ` · ${featCount()}` : ''}</button></div>`
          : '');
    lastSignature = nextSignature;
    // Find 창은 body 에 떠 있다 - 단추가 사라졌으면 닫고, 남았으면 새 상태로 목록(중복 표)을 고치고 다시 붙인다.
    if (findEl) {
      if (findAvailable(current)) renderFindList(); else closeFind();
    }
    syncValues(current);
    bindAssist();          // 렌더가 칸을 새로 만들었다 - 반드시 다시 건다
    renderRoll();          // 패널을 통째로 갈아 끼웠다 - 디버그 줄을 다시 붙인다(높이 재기 전에)
    fitGridHeight();
    placeFindBar();
    // 쥐고 있던 스크롤을 되돌린다. **`syncValues`(칸 높이) 와 `fitGridHeight`(높이 상한)
    // 뒤라야 한다** - 그 둘이 scrollHeight 와 clientHeight 를 정하므로, 먼저 넣으면
    // 브라우저가 아직 짧은 내용에 맞춰 다시 잘라낸다.
    if (keepScroll) {
      const grid = mount.querySelector('.cq-grid');
      if (grid) grid.scrollTop = keepScroll;
    }
    syncViewerShift();
    if (posEditing) renderStage();      // 좌표가 서버에서 돌아오면 원도 맞춘다
  }

  // 창 크기가 바뀌면 아래 경계도 움직인다. 한 번만 건다.
  // ⚠️ 무대도 함께 다시 그린다. 띠의 폭은 px 로 넣으므로 창이 좁아져도 스스로
  //    줄지 않는다 - 다시 그려야 칩이 접히고 그만큼 무대가 내려간다(실측).
  // 미는 양은 뷰어 상자에서 나온다 - 창이 바뀌면 그것도 같이 다시 재야 한다.
  window.addEventListener('resize', () => { fitGridHeight(); syncViewerShift(); renderStage(); placeFindBar(); positionFind(); });
  // ⚠️ resize 만으로는 모자란다. GENERATION INFO 패널은 **창과 무관하게** 높이가
  //    변한다(히스토리 항목을 고르면 내용이 늘어난다) - 그때 경계가 올라오는데
  //    창은 그대로라 resize 가 오지 않는다. 그 요소를 직접 지켜본다.
  if (typeof ResizeObserver === 'function') {
    let observed = null;
    const watchAnchor = () => {
      const anchor = document.querySelector(BOTTOM_ANCHOR);
      if (!anchor || anchor === observed) return;
      observer.disconnect();
      observer.observe(anchor);
      observed = anchor;
    };
    // ⚠️ 무대도 다시 그린다. 이 패널이 높이를 바꾸면 뷰어의 아래 경계가 함께
    //    움직이는데, 창은 그대로라 resize 가 안 온다 - 무대만 옛 사각형에 남아
    //    결과 패널을 덮는다(Codex 지적).
    const observer = new ResizeObserver(() => { fitGridHeight(); renderStage(); });
    watchAnchor();
    // 결과 패널은 늦게 생길 수 있다 - 그릴 때마다 한 번 더 확인한다.
    anchorWatcher = watchAnchor;
  }

  // ⚠️ 편집 중에 보고 있는 그림이 바뀔 수 있다(패널은 숨어 있어도 Ctrl+Enter 는
  //    먹고, 히스토리 항목을 지우면 그림이 사라진다). 무대 배경은 그때의 `src` 를
  //    복사해 둔 것이라, 다시 그리지 않으면 옛 그림이 남거나 폐기된 blob URL 을
  //    가리켜 빈칸이 된다(Codex 지적).
  //
  //    `load` 만으로는 모자란다 - **지우기·비우기는 load 를 안 쏜다**(Codex 2차).
  //    그래서 `src` 속성 자체를 지켜본다. 배경에는 URL 만 쓰므로 디코드를 기다릴
  //    이유도 없다. `load` 는 남겨 둔다 - 해상도 일치 판정이 naturalWidth 를 본다.
  const preview = document.getElementById('preview');
  if (preview) {
    // ⚠️ **미는 양도 다시 잰다.** 그것은 지금 그림의 여백(slack)에서 나오는데,
    //    Rnd Res/Auto Res 로 비율이 달라진 그림이 들어와도 아무도 다시 재지 않아
    //    옛 그림 기준의 이동량이 그대로 남았다 - 그림이 가운데로 못 왔다.
    //    패널을 접었다 펴면 `setVisible` 이 다시 재서 돌아온다(사용자 제보).
    // ⚠️ 순서가 있다. 미는 양을 **먼저** 고쳐야 무대가 그림의 새 자리를 읽는다 -
    //    엿보기 무대는 `object-position` 을 읽어 그림에 겹치므로, 거꾸로 하면
    //    한 박자 뒤진 자리에 선다. 엿보는 중에도 다시 그린다(Auto Gen 중 hover).
    const refresh = () => { syncViewerShift(); if (posEditing || posPeek) renderStage(); };
    preview.addEventListener('load', refresh);
    if (typeof MutationObserver === 'function') {
      new MutationObserver(refresh).observe(preview, {
        attributes: true, attributeFilter: ['src', 'class'],
      });
    }
  }

  // 폭이 기준선을 넘나들면 Manage 버튼의 유무가 뒤집힌다. 다시 그려 주지 않으면
  // 창을 넓힌 뒤에도 버튼이 안 돌아오고, 좁힌 뒤에도 남아 있다.
  if (typeof window !== 'undefined' && window.matchMedia) {
    window.matchMedia('(max-width: 767px)')
      .addEventListener?.('change', () => render(null, true));
  }

  // noteRandom - Random 이 굴렸다(그림이 없어도) - 마지막으로 뽑힌 캐릭터를 보인다(A).
  return {render, setVisible, isOpen: () => open, noteRandom};
}
