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
// POS 편집에서 캐릭터 칩 줄이 쓰는 높이(두 줄까지 여유).
const CHIPS_BAND = 62;

export function createCharacterQuickPanel({
  document, escHtml, setModuleParam, onModTextEdit,
  openCharacterModule = () => {},
  getResolution = () => null,      // {w, h} — 지금 설정된 생성 해상도
  bindTagAssist = () => {},        // 태그 자동완성. 모듈 팝업의 캐릭터 칸과 같은 사양
}) {
  let mount = null;
  let open = false;
  const openSlots = new Set();       // 동시에 여러 개 펼칠 수 있다 - Set 이다
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
  let stageRes = null;           // 진입 시점 해상도(편집 중 변경에 흔들리지 않게)

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

  /** `object-fit: contain` 이 실제로 그리는 사각형. 요소 상자와 다르다. */
  function drawnImageRect() {
    const img = document.getElementById('preview');
    if (!img || !img.naturalWidth || !img.classList.contains('show')) return null;
    const box = img.getBoundingClientRect();
    if (!box.width || !box.height) return null;
    const scale = Math.min(box.width / img.naturalWidth, box.height / img.naturalHeight);
    const w = img.naturalWidth * scale;
    const h = img.naturalHeight * scale;
    const posX = getComputedStyle(img).objectPosition.split(' ')[0];
    const slack = box.width - w;
    const offX = posX.endsWith('px') ? parseFloat(posX) : slack * (parseFloat(posX) / 100);
    return { left: box.left + offX, top: box.top + (box.height - h) / 2, width: w, height: h,
             natural: { w: img.naturalWidth, h: img.naturalHeight } };
  }

  /** 무대가 설 자리와 그 종류를 정한다.
   *
   *  ⚠️ **그릴 때마다 다시 잰다.** 진입 때 한 번 재서 들고 있었더니, 그 뒤 이미지가
   *  움직이면(패널 펼침에 따른 오른쪽 밀기, 새 그림 도착) 무대만 옛 자리에 남아
   *  그림과 어긋났다 - 무대가 그림 위에 정확히 얹히지 않으면 좌표가 거짓말이 된다.
   *
   *  "진입 시에만" 이라는 사양은 **해상도**에 대한 것이다(편집 중에 해상도를 바꿔도
   *  원이 튀지 않아야 한다). 그래서 해상도만 진입 시점 값(`stageRes`)으로 고정하고,
   *  자리는 매번 실측한다.
   */
  function measureStage() {
    const res = stageRes || getResolution();
    const drawn = drawnImageRect();
    const matches = !!(drawn && res
      && drawn.natural.w === res.w && drawn.natural.h === res.h);
    if (matches) return { ...drawn, overlay: true };
    // 그림이 없거나 비율이 다르면 뷰어 안에 **지금 해상도 비율**의 상자를 세운다.
    //
    // ⚠️ 패널과 칩 줄이 쓰는 자리를 먼저 빼고 남는 데에 세운다. 뷰어 전체에
    //    세웠더니 무대가 패널을 덮어 `Finish Editing POS` 에 닿을 수 없었다(실측).
    //    그래서 그림이 "약간 줄어든다"(사용자 사양) - 줄어드는 것이 아니라 남는
    //    자리에 맞춰 서는 것이다.
    const viewer = document.getElementById('resultViewer');
    if (!viewer) return null;
    const v = viewer.getBoundingClientRect();
    const panel = mount && visible ? mount.getBoundingClientRect() : null;
    const left0 = panel ? Math.max(v.left, panel.right + 10) : v.left + 12;
    const top0 = v.top + CHIPS_BAND;
    const ratio = res ? res.w / res.h : 1;
    const maxW = Math.max(120, v.right - 12 - left0);
    const maxH = Math.max(120, v.bottom - 12 - top0);
    let w = maxH * ratio;
    let h = maxH;
    if (w > maxW) { w = maxW; h = maxW / ratio; }
    return { left: left0 + (maxW - w) / 2, top: top0 + (maxH - h) / 2,
             width: w, height: h, overlay: false };
  }

  function renderStage() {
    if (posDragging) return;      // 끌고 있는 원을 교체하지 않는다
    if (!posEditing) {
      if (stage) { stage.classList.remove('open'); stage.innerHTML = ''; }
      return;
    }
    const box = stageRect = measureStage();
    if (!box) return;
    ensureStage();
    const wrap = host().getBoundingClientRect();
    Object.assign(stage.style, {
      left: Math.round(box.left - wrap.left) + 'px',
      top: Math.round(box.top - wrap.top) + 'px',
      width: Math.round(box.width) + 'px',
      height: Math.round(box.height) + 'px',
    });
    stage.classList.toggle('is-overlay', !!box.overlay);
    const slots = activeSlots(lastState);
    stage.innerHTML = slots.map(({character, index}, i) => {
      const p = character.position || { x: 0.5, y: 0.5 };
      const on = posSelected === index;
      return `<button type="button" class="cq-dot${on ? ' is-on' : ''}"`
        + ` data-cq-dot="${index}" style="left:${p.x * 100}%;top:${p.y * 100}%"`
        + ` aria-label="${escHtml(slotLabel(character, i + 1))}">${i + 1}</button>`;
    }).join('');
    stage.classList.add('open');
    renderChips(slots);
  }

  /** 무대 위쪽 캐릭터 칩. 4명을 넘으면 줄을 바꾼다(사용자 지정). */
  function renderChips(slots) {
    if (!chips || !document.body.contains(chips)) {
      chips = document.createElement('div');
      chips.className = 'cq-chips';
      chips.addEventListener('click', event => {
        const chip = event.target.closest('[data-cq-chip]');
        if (!chip) return;
        posSelected = Number(chip.dataset.cqChip);
        renderStage();
      });
      host().appendChild(chips);
    }
    const wrap = host().getBoundingClientRect();
    const box = stageRect;
    chips.style.left = Math.round(box.left - wrap.left) + 'px';
    chips.style.width = Math.round(box.width) + 'px';
    // 무대 **위**에 놓되, 그만한 자리가 없으면(해상도가 맞아 그림에 겹쳐 세운 경우
    // 그림이 뷰어 꼭대기까지 닿는다) 무대 안쪽 위에 얹는다. 잘려서 안 보이는 것보다
    // 그림을 조금 가리는 편이 낫다.
    const above = box.top - wrap.top - CHIPS_BAND;
    chips.style.top = Math.round(above >= 4 ? above : box.top - wrap.top + 6) + 'px';
    chips.innerHTML = slots.map(({character, index}, i) =>
      `<button type="button" class="cq-chip${posSelected === index ? ' is-on' : ''}"`
      + ` data-cq-chip="${index}"><span class="cq-chip-n">${i + 1}</span>`
      + `<span class="cq-chip-t">${escHtml(slotLabel(character, i + 1).replace(/^C\d+\s*·\s*/, '') || '(비어 있음)')}</span></button>`
    ).join('');
    chips.classList.add('open');
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

  function setPosEditing(on) {
    posEditing = !!on;
    if (posEditing) {
      posSelected = null;
      // 해상도만 진입 시점으로 고정한다 - 편집 중에 바꿔도 원이 튀지 않는다
      // (사용자 지정). 무대 **자리**는 renderStage 가 매번 실측한다.
      stageRes = getResolution();
      stageRect = null;
    } else {
      stageRect = null;
      stageRes = null;
      if (chips) { chips.classList.remove('open'); chips.innerHTML = ''; }
    }
    const viewer = document.getElementById('resultViewer');
    if (viewer) viewer.classList.toggle('is-cq-posedit', posEditing);
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

  /** 한 줄 라벨. 이름이 있으면 이름, 없으면 프롬프트 앞 태그. */
  function slotLabel(character, ordinal) {
    const tag = 'C' + ordinal;
    const custom = String(character.custom_name || '').trim();
    if (custom) return `${tag} · ${custom}`;
    const first = String(character.prompt || '').split(/\r?\n/)[0]
      .split(',').map(part => part.trim()).filter(Boolean);
    // 앞 태그는 보통 `girl` 이라 그것만으로는 구분이 안 된다 - 둘째까지 본다.
    const hint = first.slice(0, 2).join(', ');
    return hint ? `${tag} · ${hint}` : tag;
  }

  function slotHtml(character, index, ordinal, activeCount) {
    const isOpen = openSlots.has(index);
    // 라벨(PROMPT/NEGATIVE)을 두지 않는다 - 자리를 먹는 만큼 입력 공간을 뺏는다.
    // 네거티브는 **테두리 색**으로 구분하고, 뜻은 placeholder 가 말한다.
    const body = isOpen
      ? `<textarea class="cq-input" data-cq-field="char_prompt_${index}" data-cq-min="prompt"`
        + ` rows="${MIN_ROWS.prompt}" placeholder="캐릭터 프롬프트"></textarea>`
        + `<textarea class="cq-input is-neg" data-cq-field="char_uc_${index}" data-cq-min="uc"`
        + ` rows="${MIN_ROWS.uc}" placeholder="캐릭터 네거티브"></textarea>`
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
    return `<div class="cq-slot${isOpen ? ' is-open' : ''}">`
      + `<div class="cq-slot-headrow">`
      + `<button type="button" class="cq-slot-head" data-cq-toggle="${index}"`
      + ` aria-expanded="${isOpen ? 'true' : 'false'}">`
      + '<span class="cq-caret" aria-hidden="true">▸</span>'
      + `<span class="cq-slot-title" data-cq-label="${index}">`
      + `${escHtml(slotLabel(character, ordinal))}</span></button>`
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
  function signature(state) {
    const slots = activeSlots(state)
      .map(({index}) => [index, openSlots.has(index) ? 1 : 0].join('~'))
      .join('|');
    // `activated` 도 넣는다 - 모듈 팝업에서 끄면 이쪽 체크도 따라와야 한다.
    return `${open ? 1 : 0}${state && state.activated ? 1 : 0}`
      + `${state && state.use_custom_positions ? 1 : 0}${posEditing ? 1 : 0}#${slots}`;
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
      if (document.activeElement === element) { autoGrow(element); return; }
      const next = String((match[1] === 'prompt' ? character.prompt : character.uc) || '');
      if (element.value !== next) element.value = next;
      autoGrow(element);
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
    const centered = slack / 2;
    const offset = Math.min(Math.max(want, centered), slack);
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
    const toggle = event.target.closest('[data-cq-toggle]');
    if (toggle) {
      const index = Number(toggle.dataset.cqToggle);
      if (openSlots.has(index)) openSlots.delete(index); else openSlots.add(index);
      render(lastState, true);
      return;
    }
    if (event.target.closest('[data-cq-posmode]')) {
      const next = !(lastState && lastState.use_custom_positions);
      // AUTO 로 되돌리면 편집 중일 이유가 없다.
      if (!next && posEditing) setPosEditing(false);
      setModuleParam('character', 'use_custom_positions', String(next));
      return;
    }
    if (event.target.closest('[data-cq-posedit]')) { setPosEditing(true); return; }
    if (event.target.closest('[data-cq-posdone]')) { setPosEditing(false); return; }
    if (event.target.closest('[data-cq-manage]')) { openCharacterModule(); return; }
    if (event.target.closest('[data-cq-add]')) setModuleParam('character', 'add_character', 'true');
  }

  /** Interactive 가 켜져 있거나 NAI 모드가 아니면 자리를 비운다. */
  function setVisible(next) {
    visible = !!next;
    // 보이기로 했는데 아직 그린 적이 없으면 지금 그린다. 상태는 module_state 가
    // 오기 전이라 없을 수 있는데, 그때는 render 가 알아서 물러난다.
    if (visible && !mount && lastState) render(lastState, true);
    if (mount) mount.classList.toggle('open', visible);
    // 패널이 사라지면 편집도 끝난다 - 무대만 남으면 나갈 문이 없다.
    if (!visible && posEditing) setPosEditing(false);
    syncViewerShift();
  }

  function render(state, force) {
    if (state) lastState = state;
    if (!visible) return;
    const current = lastState;
    if (!current) return;
    ensureMount();
    const nextSignature = signature(current);
    if (!force && nextSignature === lastSignature) {
      syncValues(current); bindAssist(); fitGridHeight(); return;
    }
    const slots = activeSlots(current);
    // POS 편집 중에는 슬롯 목록을 접고 그 자리에 종료 버튼만 둔다(사용자 지정) -
    // 편집은 이미지 위 무대에서 하고, 여기는 나가는 문 하나면 된다.
    const body = open && posEditing
      ? `<div class="cq-grid cq-grid-pos">`
        + `<button type="button" class="cq-posdone" data-cq-posdone="1">`
        + `Finish Editing POS</button></div>`
      : open
      ? `<div class="cq-grid">`
        + slots.map(({character, index}, i) =>
            slotHtml(character, index, i + 1, slots.length)).join('')
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
    const custom = !!current.use_custom_positions;
    mount.innerHTML = `<div class="cq-box${open ? ' is-open' : ''}">`
      + `<div class="cq-head-row">`
      + `<button type="button" class="cq-head" data-cq-head="1"`
      + ` aria-expanded="${open ? 'true' : 'false'}">`
      + '<span class="cq-caret" aria-hidden="true">▸</span>'
      + `<span class="cq-title">CHARACTER</span></button>`
      + `<label class="cq-enable"><input type="checkbox" data-cq-enable="1"`
      + `${enabled ? ' checked' : ''}><span>활성화</span></label>`
      // POS: AUTO 는 좌표를 아예 안 보낸다 -> NAI 가 배치(AI's Choice).
      // CUSTOM 이어야 슬롯 좌표가 나가고, 그때만 편집 버튼이 생긴다.
      + `<button type="button" class="cq-pos${custom ? ' is-custom' : ''}"`
      + ` data-cq-posmode="1">POS : ${custom ? 'CUSTOM' : 'AUTO'}</button>`
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
  window.addEventListener('resize', () => fitGridHeight());
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
    const observer = new ResizeObserver(() => fitGridHeight());
    watchAnchor();
    // 결과 패널은 늦게 생길 수 있다 - 그릴 때마다 한 번 더 확인한다.
    anchorWatcher = watchAnchor;
  }

  return {render, setVisible, isOpen: () => open};
}
