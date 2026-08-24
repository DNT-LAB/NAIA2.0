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

export function createCharacterQuickPanel({
  document, escHtml, setModuleParam, onModTextEdit,
  openCharacterModule = () => {},
  getResolution = () => null,      // {w, h} — 지금 설정된 생성 해상도
  bindTagAssist = () => {},        // 태그 자동완성. 모듈 팝업의 캐릭터 칸과 같은 사양
  showToast = () => {},            // 잠긴 조작을 눌렀을 때 이유를 말한다
}) {
  let mount = null;
  let open = false;
  const openSlots = new Set();       // 동시에 여러 개 펼칠 수 있다 - Set 이다
  let pendingAddOpen = null;         // + Add 직전의 활성 슬롯 수(에코를 기다린다)
  let lastState = null;
  let lastSignature = '';
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
    const res = getResolution();
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
    const viewerBox = document.getElementById('resultViewer')?.getBoundingClientRect();
    const bandBottom = peek ? ((viewerBox ? viewerBox.top : 0) + 4) : renderBand(slots);
    const box = stageRect = measureStage(bandBottom, peek);
    if (!box) return;
    ensureStage();
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
    stage.innerHTML = (peek ? gridSvg(true) : gridSvg()) + slots.map(({character, index}, i) => {
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
    const res = getResolution();
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
    const res = getResolution();
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
    const next = !!on && !posEditing;
    if (posPeek === next) return;
    posPeek = next;
    renderStage();
  }

  function setPosEditing(on) {
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
      + `<textarea class="cq-input${cls}" data-cq-field="char_${kind}_${index}" data-cq-min="${kind === 'prompt' ? 'prompt' : 'uc'}"`
      + ` rows="${MIN_ROWS[kind === 'prompt' ? 'prompt' : 'uc']}" placeholder="${ph}"></textarea></div>`;
    const body = isOpen
      ? field('prompt', '', linked ? '추가할 캐릭터 프롬프트' : '캐릭터 프롬프트')
        + field('uc', ' is-neg', linked ? '추가할 캐릭터 네거티브' : '캐릭터 네거티브')
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
    return `<div class="cq-slot${isOpen ? ' is-open' : ''}${muted ? ' is-muted' : ''}`
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

  function signature(state) {
    // ⚠️ muted 도 서명에 넣는다. 빼면 ✔/✘ 를 눌러도 다시 그리지 않아 표시가
    //    옛 상태에 굳는다(POS 라벨이 CUSTOM 에 굳었던 것과 같은 계열).
    // ⚠️ Connect 도 같은 이유로 넣는다. 이미 CUSTOM 인 상태에서 링크를 걸면
    //    `posModeOf` 는 그대로라 서명이 안 바뀌고, POS 버튼의 자물쇠가 안 나타난다.
    // ⚠️ **참/거짓이 아니라 대상 uuid 를 넣는다.** 불리언으로 넣으면 C3 의 연결을
    //    C1 에서 C2 로 바꿔도 서명이 그대로라 다시 그리지 않는다 - 칩은 계속 `C1` 이라
    //    말하고 원본 배지도 옛 슬롯에 붙어 있다(Codex 리뷰 2026-08-24 #6).
    const slots = activeSlots(state)
      .map(({index, character}) =>
        [index, openSlots.has(index) ? 1 : 0, character && character.muted ? 1 : 0,
         String((character && character.connect_to) || '')].join('~'))
      .join('|');
    // `activated` 도 넣는다 - 모듈 팝업에서 끄면 이쪽 체크도 따라와야 한다.
    // ⚠️ POS 는 **모드 이름**을 넣는다. 불리언으로 넣으면 CUSTOM->RAND 전환이
    //    서명에 안 잡혀 라벨이 CUSTOM 에 굳는다(둘 다 "참"이 아니게 되는 순간).
    return `${open ? 1 : 0}${state && state.activated ? 1 : 0}`
      + `${posModeOf(state)}${posEditing ? 1 : 0}#${slots}`;
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
    grid.style.maxHeight = Math.max(120, Math.round(limit - top - BOTTOM_GAP)) + 'px';
  }

  /** 최소 줄수는 지키되, 넘치면 한 줄씩 늘어난다(사용자 지정). */
  function autoGrow(element) {
    const rows = MIN_ROWS[element.dataset.cqMin] || 2;
    const line = 1.4 * 11;                       // .cq-input 의 line-height * font-size
    const min = Math.round(rows * line) + 12;    // + 세로 패딩
    element.style.height = 'auto';
    element.style.height = Math.max(min, element.scrollHeight) + 'px';
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
    autoGrow(element);
    // 강조는 **글자를 칠 때마다** 다시 칠한다. 서명 기반 재렌더는 입력 내용을 일부러
    // 무시하므로(캐럿 튐) 여기서 하지 않으면 구간이 옛 모양에 굳는다.
    paintConnectHighlight(element);
    onModTextEdit('character', element.dataset.cqField, element.value);
  }

  function onClick(event) {
    // 활성화 토글은 label/input 이라 클릭이 여기로도 올라온다 - 바깥 토글보다 먼저 본다.
    if (event.target.closest('[data-cq-enable]') || event.target.closest('.cq-enable')) return;
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
      // AUTO -> CUSTOM -> RAND -> AUTO (사용자 지정).
      const now = posModeOf(lastState);
      const next = POS_CYCLE[(POS_CYCLE.indexOf(now) + 1) % POS_CYCLE.length];
      // CUSTOM 을 떠나면 편집 중일 이유가 없다 - 원을 옮길 대상이 사라진다.
      if (next !== 'custom' && posEditing) setPosEditing(false);
      setModuleParam('character', 'position_mode', next);
      return;
    }
    if (event.target.closest('[data-cq-posedit]')) { setPosPeek(false); setPosEditing(true); return; }
    if (event.target.closest('[data-cq-posdone]')) { setPosEditing(false); return; }
    if (event.target.closest('[data-cq-manage]')) { openCharacterModule(); return; }
    if (event.target.closest('[data-cq-add]')) {
      // 지금 활성 슬롯 수를 적어 둔다 - 에코가 이보다 늘면 그게 새 슬롯이다.
      pendingAddOpen = activeSlots(lastState).length;
      setModuleParam('character', 'add_character', 'true');
    }
  }

  /** Interactive 가 켜져 있거나 NAI 모드가 아니면 자리를 비운다. */
  function setVisible(next) {
    visible = !!next;
    // 보이기로 했는데 아직 그린 적이 없으면 지금 그린다. 상태는 module_state 가
    // 오기 전이라 없을 수 있는데, 그때는 render 가 알아서 물러난다.
    if (visible && !mount && lastState) render(lastState, true);
    // POS 편집 중에는 패널을 감춘다(A안) - 띠의 종료 버튼이 나가는 문이다.
    if (mount) mount.classList.toggle('open', visible && !posEditing);
    // 패널이 사라지면 편집도 끝난다 - 무대만 남으면 나갈 문이 없다.
    if (!visible && posEditing) setPosEditing(false);
    syncViewerShift();
  }

  function render(state, force) {
    if (state) lastState = state;
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
      syncValues(current); bindAssist(); fitGridHeight();
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
        + `<button type="button" class="cq-manage" data-cq-manage="1">Manage</button>`
        + `</div></div>`
      : '';
    // 머리는 **버튼 하나가 아니라 줄**이다. 활성화 토글과 POS 를 나란히 두어야
    // 하는데, <button> 안에 <input> 이나 <button> 을 넣으면 마크업이 깨지고
    // 안쪽을 눌러도 바깥 토글이 먼저 먹는다.
    const enabled = !!current.activated;
    const posMode = posModeOf(current);
    const custom = posMode === 'custom';
    const posLocked = hasConnectedSlot(current);
    mount.innerHTML = `<div class="cq-box${open ? ' is-open' : ''}">`
      + `<div class="cq-head-row">`
      + `<button type="button" class="cq-head" data-cq-head="1"`
      + ` aria-expanded="${open ? 'true' : 'false'}">`
      + '<span class="cq-caret" aria-hidden="true">▸</span>'
      + `<span class="cq-title">CHARACTER</span></button>`
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
      + `</div><div class="cq-body">${body}</div></div>`;
    lastSignature = nextSignature;
    syncValues(current);
    bindAssist();          // 렌더가 칸을 새로 만들었다 - 반드시 다시 건다
    fitGridHeight();
    syncViewerShift();
    if (posEditing) renderStage();      // 좌표가 서버에서 돌아오면 원도 맞춘다
  }

  // 창 크기가 바뀌면 아래 경계도 움직인다. 한 번만 건다.
  // ⚠️ 무대도 함께 다시 그린다. 띠의 폭은 px 로 넣으므로 창이 좁아져도 스스로
  //    줄지 않는다 - 다시 그려야 칩이 접히고 그만큼 무대가 내려간다(실측).
  // 미는 양은 뷰어 상자에서 나온다 - 창이 바뀌면 그것도 같이 다시 재야 한다.
  window.addEventListener('resize', () => { fitGridHeight(); syncViewerShift(); renderStage(); });
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

  return {render, setVisible, isOpen: () => open};
}
