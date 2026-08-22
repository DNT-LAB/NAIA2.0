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

const MIN_ROWS = {prompt: 3, uc: 2};

export function createCharacterQuickPanel({document, escHtml, setModuleParam, onModTextEdit}) {
  let mount = null;
  let open = false;
  const openSlots = new Set();       // 동시에 여러 개 펼칠 수 있다 - Set 이다
  let lastState = null;
  let lastSignature = '';
  let visible = false;

  function host() {
    return document.querySelector('.viewer-wrapper') || document.body;
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

  function slotHtml(character, index, ordinal) {
    const isOpen = openSlots.has(index);
    const body = isOpen
      ? `<div class="cq-sub">PROMPT</div>`
        + `<textarea class="cq-input" data-cq-field="char_prompt_${index}" data-cq-min="prompt"`
        + ` rows="${MIN_ROWS.prompt}" placeholder="캐릭터 프롬프트"></textarea>`
        + `<div class="cq-sub">NEGATIVE</div>`
        + `<textarea class="cq-input" data-cq-field="char_uc_${index}" data-cq-min="uc"`
        + ` rows="${MIN_ROWS.uc}" placeholder="캐릭터 네거티브"></textarea>`
      : '';
    // ⚠️ title 을 두지 않는다. 앱이 그걸 걷어 자체 툴팁으로 바꾸는데, 이 상자는
    //    좁아서 툴팁이 라벨을 그대로 덮는다(사용자 지적). 화살표가 이미 접힘/펼침을
    //    말하고 있어 설명이 필요 없다.
    return `<div class="cq-slot${isOpen ? ' is-open' : ''}">`
      + `<button type="button" class="cq-slot-head" data-cq-toggle="${index}"`
      + ` aria-expanded="${isOpen ? 'true' : 'false'}">`
      + '<span class="cq-caret" aria-hidden="true">▸</span>'
      + `<span class="cq-slot-title">${escHtml(slotLabel(character, ordinal))}</span></button>`
      + `<div class="cq-slot-body">${body}</div></div>`;
  }

  /** 구성만 담는다 - 입력 내용은 절대 넣지 않는다(캐럿 튐). */
  function signature(state) {
    const slots = activeSlots(state)
      .map(({character, index}, i) =>
        [index, openSlots.has(index) ? 1 : 0, slotLabel(character, i + 1)].join('~'))
      .join('|');
    // `activated` 도 넣는다 - 모듈 팝업에서 끄면 이쪽 체크도 따라와야 한다.
    return `${open ? 1 : 0}${state && state.activated ? 1 : 0}#${slots}`;
  }

  /** 렌더가 값을 지웠으므로 여기서 되돌린다(마크업에 값을 넣지 않는 대가). */
  function syncValues(state) {
    const chars = (state && state.characters) || [];
    mount.querySelectorAll('[data-cq-field]').forEach(element => {
      const key = element.dataset.cqField || '';
      const match = key.match(/^char_(prompt|uc)_(\d+)$/);
      if (!match) return;
      const character = chars[Number(match[2])];
      if (!character) return;
      const next = String((match[1] === 'prompt' ? character.prompt : character.uc) || '');
      if (element.value !== next) element.value = next;
      autoGrow(element);
    });
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
    const toggle = event.target.closest('[data-cq-toggle]');
    if (toggle) {
      const index = Number(toggle.dataset.cqToggle);
      if (openSlots.has(index)) openSlots.delete(index); else openSlots.add(index);
      render(lastState, true);
      return;
    }
    if (event.target.closest('[data-cq-add]')) setModuleParam('character', 'add_character', 'true');
  }

  /** Interactive 가 켜져 있거나 NAI 모드가 아니면 자리를 비운다. */
  function setVisible(next) {
    visible = !!next;
    // 보이기로 했는데 아직 그린 적이 없으면 지금 그린다. 상태는 module_state 가
    // 오기 전이라 없을 수 있는데, 그때는 render 가 알아서 물러난다.
    if (visible && !mount && lastState) render(lastState, true);
    if (mount) mount.classList.toggle('open', visible);
  }

  function render(state, force) {
    if (state) lastState = state;
    if (!visible) return;
    const current = lastState;
    if (!current) return;
    ensureMount();
    const nextSignature = signature(current);
    if (!force && nextSignature === lastSignature) { syncValues(current); return; }
    const slots = activeSlots(current);
    const body = open
      ? `<div class="cq-grid">`
        + slots.map(({character, index}, i) => slotHtml(character, index, i + 1)).join('')
        + `<button type="button" class="cq-add" data-cq-add="1">+ Add Character</button>`
        + `</div>`
      : '';
    // 머리는 **버튼 하나가 아니라 줄**이다. 활성화 토글과 POS 를 나란히 두어야
    // 하는데, <button> 안에 <input> 이나 <button> 을 넣으면 마크업이 깨지고
    // 안쪽을 눌러도 바깥 토글이 먼저 먹는다.
    const enabled = !!current.activated;
    mount.innerHTML = `<div class="cq-box${open ? ' is-open' : ''}">`
      + `<div class="cq-head-row">`
      + `<button type="button" class="cq-head" data-cq-head="1"`
      + ` aria-expanded="${open ? 'true' : 'false'}">`
      + '<span class="cq-caret" aria-hidden="true">▸</span>'
      + `<span class="cq-title">CHARACTER</span></button>`
      + `<label class="cq-enable"><input type="checkbox" data-cq-enable="1"`
      + `${enabled ? ' checked' : ''}><span>활성화</span></label>`
      + `<button type="button" class="cq-pos" data-cq-pos="1">POS</button>`
      + `<span class="cq-count">${slots.length}</span>`
      + `</div><div class="cq-body">${body}</div></div>`;
    lastSignature = nextSignature;
    syncValues(current);
  }

  return {render, setVisible, isOpen: () => open};
}
