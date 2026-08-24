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
  function measureStage(bandBottom) {
    const res = getResolution();
    const img = document.getElementById('preview');
    const shown = !!(img && img.naturalWidth && img.classList.contains('show'));
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
    if (!posEditing) {
      if (stage) { stage.classList.remove('open'); stage.innerHTML = ''; }
      if (chips) { chips.classList.remove('open'); chips.innerHTML = ''; }
      return;
    }
    const slots = activeSlots(lastState);
    // 줄이 몇 줄이 될지는 그려 봐야 안다 - 띠를 **먼저** 그려 실제 높이를 재고,
    // 무대는 그 아래 남는 자리에 세운다(사용자 지정: 줄이 넘으면 자동 조절).
    const bandBottom = renderBand(slots);
    const box = stageRect = measureStage(bandBottom);
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
    stage.innerHTML = slots.map(({character, index}, i) => {
      const p = character.position || { x: 0.5, y: 0.5 };
      const on = posSelected === index;
      return `<button type="button" class="cq-dot${on ? ' is-on' : ''}"`
        + ` data-cq-dot="${index}" style="left:${p.x * 100}%;top:${p.y * 100}%"`
        + ` aria-label="${escHtml(slotLabel(character, i + 1))}">${i + 1}</button>`;
    }).join('');
    stage.classList.add('open');
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
      + slots.map(({character, index}, i) =>
          `<button type="button" class="cq-chip${posSelected === index ? ' is-on' : ''}"`
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

  function setPosEditing(on) {
    posEditing = !!on;
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
    mount.addEventListener('mousedown', event => {
      if (!event.target.closest('textarea')) event.preventDefault();
    });
    mount.addEventListener('click', onClick);
    mount.addEventListener('input', onInput);
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

  /** 미러에 칠할 HTML. 마커가 없으면 빈 문자열(강조를 아예 걸지 않는다). */
  function connectHighlightHtml(text) {
    const parts = connectParts(text);
    if (!parts) return '';
    return escHtml(parts.head)
      + `<span class="cq-hl-mark">${escHtml(parts.openTok)}</span>`
      + `<span class="cq-hl-share">${escHtml(parts.shared)}</span>`
      + (parts.closeTok ? `<span class="cq-hl-mark">${escHtml(parts.closeTok)}</span>` : '')
      + escHtml(parts.tail);
  }

  /** 칸 하나의 강조를 다시 칠한다.
   *
   *  ⚠️ 미러는 글자를 **투명**으로 그리고 배경만 남긴다. 글자까지 그리면 아래
   *     textarea 의 글자와 겹쳐 이중으로 보이고, 그러려면 textarea 글자를 투명하게
   *     해야 하는데 그러면 이 코드가 한 번이라도 실패했을 때 칸이 통째로 비어 보인다.
   *     배경만 칠하면 최악의 경우가 "강조가 안 보인다" 로 끝난다.
   *  ⚠️ 마커가 없으면 미러를 비운다 - 이 기능을 안 쓰는 사용자에게는 아무 일도
   *     일어나지 않는다. */
  function paintConnectHighlight(element) {
    const wrap = element && element.parentElement;
    if (!wrap || !wrap.classList.contains('cq-input-wrap')) return;
    const mirror = wrap.querySelector('.cq-hl');
    if (!mirror) return;
    const html = connectHighlightHtml(element.value);
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
    const current = String(character.connect_to || '');
    const options = slots.slice(0, ordinal - 1).map((item, i) => {
      const uuid = String(item.character.slot_uuid || '');
      const name = String(item.character.custom_name || '').trim();
      const text = name ? `C${i + 1} · ${name}` : `C${i + 1}`;
      return `<option value="${escAttr(uuid)}"${uuid === current ? ' selected' : ''}>${escHtml(text)}</option>`;
    }).join('');
    const on = !!current;
    return `<span class="cq-connect${on ? ' is-on' : ''}">`
      + `<span class="cq-connect-tag">${on ? '&#128279;' : 'Connect'}</span>`
      + `<select data-cq-connect="${index}" aria-label="앞선 슬롯에서 물려받기">`
      + `<option value=""${on ? '' : ' selected'}>연결 없음</option>${options}</select></span>`;
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
  function slotLabel(character, ordinal) {
    const tag = 'C' + ordinal;
    const custom = String(character.custom_name || '').trim();
    if (custom) return `${tag} · ${custom}`;
    // 마커는 이름이 아니다. 안 걷어내면 접힌 슬롯이 `C1 · &connect: girl` 이 되어
    // 정작 구분에 필요한 태그 한 칸을 문법이 잡아먹는다(실측).
    const first = String(character.prompt || '')
      .replace(CONNECT_OPEN_RE, '').replace(CONNECT_CLOSE_RE, '')
      .split(/\r?\n/)[0]
      .split(',').map(part => part.trim()).filter(Boolean);
    // 앞 태그는 보통 `girl` 이라 그것만으로는 구분이 안 된다 - 둘째까지 본다.
    const hint = first.slice(0, 2).join(', ');
    return hint ? `${tag} · ${hint}` : tag;
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
      + `${escHtml(slotLabel(character, ordinal))}</span></button>`
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
    const slots = activeSlots(state)
      .map(({index, character}) =>
        [index, openSlots.has(index) ? 1 : 0, character && character.muted ? 1 : 0,
         character && String(character.connect_to || '') ? 1 : 0].join('~'))
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
    const ordinalOf = new Map();
    activeSlots(state).forEach(({index}, i) => ordinalOf.set(index, i + 1));
    mount.querySelectorAll('[data-cq-label]').forEach(element => {
      const index = Number(element.dataset.cqLabel);
      const character = chars[index];
      if (!character) return;
      const next = slotLabel(character, ordinalOf.get(index) || 1);
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
    // Connect 드롭다운. `change` 가 아니라 `input` 으로도 오는 브라우저가 있어
    // 여기서 함께 받는다(select 는 둘 다 발화한다).
    const connect = event.target.closest('[data-cq-connect]');
    if (connect) {
      setModuleParam('character', `char_connect_${connect.dataset.cqConnect}`, connect.value);
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
    if (event.target.closest('[data-cq-posedit]')) { setPosEditing(true); return; }
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
  window.addEventListener('resize', () => { fitGridHeight(); renderStage(); });
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
    const refresh = () => { if (posEditing) renderStage(); };
    preview.addEventListener('load', refresh);
    if (typeof MutationObserver === 'function') {
      new MutationObserver(refresh).observe(preview, {
        attributes: true, attributeFilter: ['src', 'class'],
      });
    }
  }

  return {render, setVisible, isOpen: () => open};
}
