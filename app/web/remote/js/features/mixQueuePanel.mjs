/** 믹스 큐 — 아티스트 여러 명을 순서·가중치와 함께 쌓는 판 (리모컨 전용).
 *
 *  리모컨의 확대 보기가 뜨던 자리에 붙는다. 큐는 위에서 아래로 **삽입 순서**이고,
 *  켜져 있는 블럭만 조립에 들어간다. 조립 결과는 곧바로 ARTIST PROMPT 칸으로 간다
 *  (사용자 지정) - 그 칸이 Generate 와 Generate with Random Prompt 가 쓰는 자리다.
 *
 *      ┌ 믹스 모드 ─────────────┐
 *      │ [−] 0.9 [+]  kouji     │ ← 끌어서 순서를 바꾼다
 *      │ [−] 1.0 [+]  dairi *   │ ← `*` = 임시(격자에서 방금 고른 것)
 *      │ [−]-1.0 [+]  collab ▨  │ ← 못 지우는 블럭. 기본 꺼짐
 *      ├────────────────────────┤
 *      │ [삽입] [삭제] [비활성] │
 *      └────────────────────────┘
 *
 *  ⚠️ **서식은 여기서 만들지 않는다.** `formatToken` 을 받아 쓴다 - NAI/Anima/SD 표기가
 *     이미 `artistThumbTab` 에 있고, 두 곳에서 만들면 반드시 어긋난다(오늘 한 번 겪었다).
 *  ⚠️ 우클릭 하나에 **세 가지**를 몰아 둔다(`artist:` 토글 · 비활성 · 제거) - 블럭이
 *     좁아 단추를 더 못 놓는다(사용자 지정).
 */

const COLLAB_ID = '__collab__';
const HOLD_FIRST_MS = 320;     // 누르고 있을 때 반복이 시작되기까지
// 그 뒤 0.5초마다 (사용자 지정). ⚠️ 0.1초마다로 두었더니 1초만 쥐어도 0.6 이
// 움직여 조절이 안 됐다 - 쥐는 것은 '성큼' 이지 '순식간' 이 아니다.
const HOLD_STEP_MS = 500;
const STEP = 0.01;             // 한 번 누르면 (사용자 지정)
// 길게 누를 때는 **0.1**씩(사용자 지정). 0.1 은 0.01 의 배수라 눈금이 어긋나지 않는다.
const HOLD_STEP = 0.1;

let seq = 0;
const nextId = () => `mq${++seq}`;

/** 0.01 씩 더하면 부동소수 찌꺼기가 붙는다(0.7000000000000001). 두 자리로 고정한다. */
function roundStep(value) {
  const n = Number.parseFloat(value);
  if (!Number.isFinite(n)) return 1;
  return Math.round(n * 100) / 100;
}

/** 꼬리 0 은 뗀다 - 44px 칸에 `0.90` 보다 `0.9` 가 낫다. */
function weightText(value) {
  return String(roundStep(value));
}

export function createMixQueuePanel({
  document: doc,
  escHtml = value => String(value ?? '')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'),
  showToast = () => {},
  // (artist, weight, {withPrefix}) => string   ⚠️ 서식의 단일 소유자
  formatToken = (artist, weight) => `${weight}::${artist}`,
  onChange = () => {},        // (조립된 문자열) => void
  onHoverBlock = () => {},    // (element, {artist}) => void   확대 보기 요청
  onLeaveBlock = () => {},
  // 임시 블럭의 가중치가 큐 안에서 바뀌었다 - 메인 슬라이더도 따라와야 한다(사용자 지정).
  // ⚠️ 이 콜백은 **큐가 원인일 때만** 부른다. 메인에서 들어온 값(`setTempWeight`)에
  //    다시 부르면 둘이 서로를 밀어 무한히 돈다.
  onTempWeight = () => {},
} = {}) {
  const el = doc.createElement('div');
  el.className = 'mixq';
  el.hidden = true;
  el.innerHTML = `
    <div class="mixq-head">
      <span class="mixq-title">믹스 모드</span>
      <span class="mixq-hint">끌어서 순서 · 우클릭으로 더 보기</span>
    </div>
    <div class="mixq-list" role="list"></div>
    <div class="mixq-foot">
      <button type="button" class="mixq-btn" data-mixq-act="commit">현재 태그 삽입</button>
      <button type="button" class="mixq-btn" data-mixq-act="remove">선택 태그 삭제</button>
      <button type="button" class="mixq-btn" data-mixq-act="disable">선택 태그 비활성</button>
    </div>
    <div class="mixq-menu" hidden role="menu"></div>
  `;
  const listEl = el.querySelector('.mixq-list');
  const menuEl = el.querySelector('.mixq-menu');

  /** 큐. 마지막의 collab 블럭은 못 지우지만 **움직일 수는 있다**(사용자 지정). */
  let blocks = [collabBlock()];
  let dragId = '';
  let menuFor = '';

  function collabBlock() {
    return {
      id: COLLAB_ID,
      artist: 'artist collaboration',
      weight: -1,
      withPrefix: false,     // `artist:` 를 붙이지 않는다
      enabled: false,        // 기본 꺼짐
      temp: false,
      locked: true,          // 제거 불가
      selected: false,
      image: '',
    };
  }

  const find = id => blocks.find(b => b.id === id) || null;
  const tempBlock = () => blocks.find(b => b.temp) || null;

  // ── 조립 ──────────────────────────────────────────────────────────────
  function compose() {
    return blocks
      .filter(b => b.enabled && String(b.artist || '').trim())
      .map(b => formatToken(b.artist, b.weight, {withPrefix: b.withPrefix}))
      .filter(Boolean)
      .join(', ');
  }

  function emit() {
    onChange(compose());
  }

  // ── 그리기 ────────────────────────────────────────────────────────────
  function render() {
    listEl.innerHTML = blocks.map(b => {
      const classes = ['mixq-block'];
      if (!b.enabled) classes.push('is-off');
      if (b.selected) classes.push('is-selected');
      if (b.temp) classes.push('is-temp');
      if (b.locked) classes.push('is-locked');
      const name = b.withPrefix ? `artist:${b.artist}` : b.artist;
      return `<div class="${classes.join(' ')}" role="listitem" draggable="true"
                   data-mixq-id="${escHtml(b.id)}" title="${escHtml(name)}">
        <button type="button" class="mixq-step" data-mixq-step="-1" aria-label="가중치 내리기">−</button>
        <input class="mixq-weight" type="text" inputmode="decimal"
               value="${escHtml(weightText(b.weight))}" aria-label="가중치">
        <button type="button" class="mixq-step" data-mixq-step="1" aria-label="가중치 올리기">+</button>
        <span class="mixq-name">${escHtml(name)}</span>
        ${b.temp ? '<span class="mixq-badge">임시</span>' : ''}
      </div>`;
    }).join('');
    paintFoot();
  }

  /** 아래 단추는 **대상이 있을 때만** 살아난다 - 단추가 켜지는 것이 곧 '고른 것이
   *  무엇에 쓰이는지' 의 설명이다(상태가 뜻을 못 전달한다는 제보). */
  function paintFoot() {
    const commit = el.querySelector('[data-mixq-act="commit"]');
    if (commit) commit.disabled = !tempBlock();
    const picked = blocks.filter(b => b.selected).length;
    el.querySelectorAll('[data-mixq-act="remove"], [data-mixq-act="disable"]')
      .forEach(btn => { btn.disabled = picked === 0; });
  }

  function refresh() {
    render();
    emit();
  }

  // ── 가중치 ────────────────────────────────────────────────────────────
  /** 가중치를 바꾸는 **모든 길**이 여기로 모인다 - 임시 블럭이면 메인 가중치도
   *  같이 움직여야 한다(사용자 지정). 길이 셋(+/- · 타이핑 · 커밋)이라 한 곳에
   *  모으지 않으면 넷째 길이 생길 때 또 빠뜨린다. */
  function applyWeight(block, value) {
    block.weight = value;
    if (block.temp) onTempWeight(block.weight);
    emit();          // ⚠️ 여기서 render() 를 부르면 누르고 있는 단추가 사라진다
  }

  function bump(id, direction, step = STEP) {
    const block = find(id);
    if (!block) return;
    const next = roundStep(block.weight + direction * step);
    const input = listEl.querySelector(`[data-mixq-id="${CSS.escape(id)}"] .mixq-weight`);
    if (input) input.value = weightText(next);
    applyWeight(block, next);
  }

  let holdTimer = null;
  let holdRepeat = null;

  function stopHold() {
    if (holdTimer) { clearTimeout(holdTimer); holdTimer = null; }
    if (holdRepeat) { clearInterval(holdRepeat); holdRepeat = null; }
  }

  function startHold(id, direction) {
    stopHold();
    bump(id, direction);
    // 누르고 있으면 0.1초당 0.1씩(사용자 지정). 첫 반복 전에는 조금 기다린다 -
    // 한 번 누르려던 것이 두세 번 먹으면 미세 조정이 안 된다.
    holdTimer = setTimeout(() => {
      holdTimer = null;
      holdRepeat = setInterval(() => bump(id, direction, HOLD_STEP), HOLD_STEP_MS);
    }, HOLD_FIRST_MS);
  }

  // ── 우클릭 메뉴 (artist: 토글 · 비활성 · 제거) ─────────────────────────
  function openMenu(block, x, y) {
    menuFor = block.id;
    menuEl.innerHTML = `
      <button type="button" data-mixq-menu="prefix"${block.locked ? ' disabled' : ''}>${block.withPrefix ? '`artist:` 떼기' : '`artist:` 붙이기'}</button>
      <button type="button" data-mixq-menu="enabled">${block.enabled ? '비활성으로' : '다시 켜기'}</button>
      <button type="button" data-mixq-menu="remove"${block.locked ? ' disabled' : ''}>제거</button>
    `;
    menuEl.hidden = false;
    const box = el.getBoundingClientRect();
    const menu = menuEl.getBoundingClientRect();
    const left = Math.min(Math.max(4, x - box.left), box.width - menu.width - 4);
    const top = Math.min(Math.max(4, y - box.top), box.height - menu.height - 4);
    menuEl.style.left = `${Math.round(left)}px`;
    menuEl.style.top = `${Math.round(top)}px`;
  }

  function closeMenu() {
    menuFor = '';
    menuEl.hidden = true;
  }

  // ── 배선 ──────────────────────────────────────────────────────────────
  listEl.addEventListener('pointerdown', event => {
    const step = event.target.closest('[data-mixq-step]');
    if (!step) return;
    event.preventDefault();
    const id = step.closest('[data-mixq-id]')?.dataset.mixqId || '';
    startHold(id, Number(step.dataset.mixqStep) || 1);
  });
  doc.addEventListener('pointerup', stopHold);
  doc.addEventListener('pointercancel', stopHold);

  listEl.addEventListener('input', event => {
    const input = event.target.closest('.mixq-weight');
    if (!input) return;
    const block = find(input.closest('[data-mixq-id]')?.dataset.mixqId || '');
    if (!block) return;
    // 타이핑 도중에는 값을 다시 쓰지 않는다 - 캐럿이 끝으로 튄다.
    const parsed = Number.parseFloat(input.value);
    if (Number.isFinite(parsed)) applyWeight(block, parsed);
  });
  listEl.addEventListener('change', event => {
    const input = event.target.closest('.mixq-weight');
    if (!input) return;
    const block = find(input.closest('[data-mixq-id]')?.dataset.mixqId || '');
    if (!block) return;
    const next = roundStep(input.value);
    input.value = weightText(next);
    applyWeight(block, next);
  });

  // 블럭을 누르면 고름(아래 단추들의 대상). 단추·입력칸은 제외한다.
  listEl.addEventListener('click', event => {
    if (event.target.closest('[data-mixq-step], .mixq-weight')) return;
    const host = event.target.closest('[data-mixq-id]');
    if (!host) return;
    const block = find(host.dataset.mixqId);
    if (!block) return;
    block.selected = !block.selected;
    host.classList.toggle('is-selected', block.selected);
    paintFoot();   // ⚠️ 여기서 render() 를 부르면 스크롤이 튄다 - 단추만 다시 그린다.
  });

  listEl.addEventListener('contextmenu', event => {
    const host = event.target.closest('[data-mixq-id]');
    if (!host) return;
    event.preventDefault();
    const block = find(host.dataset.mixqId);
    if (block) openMenu(block, event.clientX, event.clientY);
  });

  menuEl.addEventListener('click', event => {
    const action = event.target.closest('[data-mixq-menu]')?.dataset.mixqMenu;
    const block = find(menuFor);
    closeMenu();
    if (!action || !block) return;
    if (action === 'prefix') { if (block.locked) return; block.withPrefix = !block.withPrefix; }
    else if (action === 'enabled') block.enabled = !block.enabled;
    else if (action === 'remove') {
      if (block.locked) { showToast('이 블럭은 지울 수 없습니다.', 'error'); return; }
      blocks = blocks.filter(b => b.id !== block.id);
    }
    refresh();
  });
  el.addEventListener('pointerdown', event => {
    if (!event.target.closest('.mixq-menu')) closeMenu();
  }, true);

  // 끌어서 순서 바꾸기. 임시 블럭과 collab 블럭도 움직인다(사용자 지정).
  listEl.addEventListener('dragstart', event => {
    const host = event.target.closest('[data-mixq-id]');
    if (!host) return;
    dragId = host.dataset.mixqId;
    host.classList.add('is-dragging');
    try { event.dataTransfer.setData('text/plain', dragId); } catch { /* 일부 브라우저 */ }
    if (event.dataTransfer) event.dataTransfer.effectAllowed = 'move';
  });
  listEl.addEventListener('dragend', () => {
    dragId = '';
    listEl.querySelectorAll('.is-dragging, .is-drop-before, .is-drop-after')
      .forEach(node => node.classList.remove('is-dragging', 'is-drop-before', 'is-drop-after'));
  });
  listEl.addEventListener('dragover', event => {
    if (!dragId) return;
    event.preventDefault();
    if (event.dataTransfer) event.dataTransfer.dropEffect = 'move';
    const host = event.target.closest('[data-mixq-id]');
    listEl.querySelectorAll('.is-drop-before, .is-drop-after')
      .forEach(node => node.classList.remove('is-drop-before', 'is-drop-after'));
    if (!host || host.dataset.mixqId === dragId) return;
    const rect = host.getBoundingClientRect();
    host.classList.add(event.clientY < rect.top + rect.height / 2 ? 'is-drop-before' : 'is-drop-after');
  });
  listEl.addEventListener('drop', event => {
    if (!dragId) return;
    event.preventDefault();
    const host = event.target.closest('[data-mixq-id]');
    const from = blocks.findIndex(b => b.id === dragId);
    if (from < 0) return;
    const moved = blocks[from];
    blocks.splice(from, 1);
    let to = blocks.length;
    if (host && host.dataset.mixqId !== dragId) {
      const rect = host.getBoundingClientRect();
      const at = blocks.findIndex(b => b.id === host.dataset.mixqId);
      to = at < 0 ? blocks.length : at + (event.clientY < rect.top + rect.height / 2 ? 0 : 1);
    }
    blocks.splice(to, 0, moved);
    dragId = '';
    refresh();
  });

  // 블럭에 마우스를 올리면 확대 보기(3-f). 격자 쪽과 달리 **믹스 판 옆**에 뜬다.
  listEl.addEventListener('pointerover', event => {
    if (event.pointerType === 'touch') return;
    const host = event.target.closest('[data-mixq-id]');
    if (!host) { onLeaveBlock(); return; }
    const block = find(host.dataset.mixqId);
    if (block) onHoverBlock(host, block);
  });
  listEl.addEventListener('pointerout', event => {
    if (!event.relatedTarget || !listEl.contains(event.relatedTarget)) onLeaveBlock();
    else if (!event.relatedTarget.closest?.('[data-mixq-id]')) onLeaveBlock();
  });

  el.querySelector('.mixq-foot').addEventListener('click', event => {
    const action = event.target.closest('[data-mixq-act]')?.dataset.mixqAct;
    if (!action) return;
    if (action === 'commit') {
      const temp = tempBlock();
      if (!temp) { showToast('격자에서 아티스트를 먼저 고르세요.', 'error'); return; }
      temp.temp = false;
      refresh();
      return;
    }
    const picked = blocks.filter(b => b.selected);
    if (!picked.length) { showToast('블럭을 먼저 고르세요.', 'error'); return; }
    if (action === 'remove') {
      const locked = picked.filter(b => b.locked);
      blocks = blocks.filter(b => !(b.selected && !b.locked));
      if (locked.length) showToast('못 지우는 블럭은 남겼습니다.', 'info');
    } else if (action === 'disable') {
      // 하나라도 켜져 있으면 전부 끈다 - 눌렀는데 절반만 바뀌면 뭘 한 건지 모른다.
      const anyOn = picked.some(b => b.enabled);
      picked.forEach(b => { b.enabled = !anyOn; });
    }
    refresh();
  });

  // ── 바깥에서 부르는 것 ────────────────────────────────────────────────
  return {
    el,
    isOpen: () => !el.hidden,
    setOpen(open) {
      el.hidden = !open;
      closeMenu();
      if (open) refresh();
      return !el.hidden;
    },
    /** 격자에서 고른 작가 - 임시 블럭 한 자리를 차지하고 다음 선택에 갈린다. */
    setTempArtist(artist, image = '') {
      const name = String(artist || '').trim();
      const temp = tempBlock();
      if (!name) {
        if (temp) blocks = blocks.filter(b => !b.temp);
        refresh();
        return;
      }
      if (temp) {
        temp.artist = name;
        temp.image = image;
      } else {
        // collab 블럭은 늘 마지막이 **기본**이지만 사용자가 옮겼다면 그 자리를 지킨다.
        const at = blocks.findIndex(b => b.id === COLLAB_ID);
        const block = {
          id: nextId(), artist: name, weight: 1, withPrefix: true,
          enabled: true, temp: true, locked: false, selected: false, image,
        };
        if (at < 0) blocks.push(block);
        else blocks.splice(at, 0, block);
      }
      refresh();
    },
    /** 임시 블럭의 가중치 - 리모컨의 슬라이더가 이걸 민다. */
    setTempWeight(value) {
      const temp = tempBlock();
      if (!temp) return false;
      // ⚠️ 메인에서 들어온 값이다 - `onTempWeight` 로 되돌려 부르지 않는다(서로 민다).
      temp.weight = roundStep(value);
      const input = listEl.querySelector(`[data-mixq-id="${CSS.escape(temp.id)}"] .mixq-weight`);
      if (input) input.value = weightText(temp.weight);
      emit();
      return true;
    },
    compose,
    blockFor: id => find(id),
    snapshot: () => blocks.map(b => ({...b})),
  };
}
