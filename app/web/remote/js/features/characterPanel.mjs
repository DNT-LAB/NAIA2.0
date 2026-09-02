/**
 * 캐릭터 워크스페이스 — [ 캐릭터 슬롯 | 작업 영역(탭) ]
 *
 * 사용자 지정 2026-09-01:
 *   "1. 기본 디자인 기조 : 메모와 유사합니다.
 *    2. 슬롯 디자인 기조 : 캐릭터 퀵 프롬프트 슬롯과 동일합니다.
 *    3. 구조는 [ 캐릭터 슬롯 | 작업 영역 (탭) ] 입니다."
 *   "캐릭터 프롬프트 모듈에서는 슬롯을 전부 펼칩니다."
 *   "[a] 왼쪽은 활성만 · Add Character 는 목록 바로 밑"
 *
 * ## 무엇이 문제였나 (실측 2026-09-01, 슬롯 8개)
 *
 *     창          420 x 696  = 뷰포트 720 의 **97%**
 *     슬롯 하나   163px      (Quick 은 같은 내용을 22~99px 로 그린다)
 *     한 화면에   **4개**
 *     스크롤      **1,086px** - 그리고 슬롯을 만들수록 끝없이 길어졌다
 *
 * 스크롤 길이가 "여태 만든 슬롯 전부" 에 비례했다. 이제 왼쪽에는 **활성만** 두므로
 * 지금 생성에 나가는 것에만 비례한다. 나머지는 **히스토리** 탭이 유일한 보관처다 - 썼던 슬롯을 최대 500개 누적한다
 * (사용자 지정 2026-09-01: 기존 비활성의 역할을 대신한다).
 *
 * ⚠️ Cold 는 **동작이 없는 세 번째 상태**였다(`is_enabled` 는 `active and not muted`
 *    뿐이라 inactive 와 하는 일이 같았다). 서랍을 파서 줄을 숨겼을 뿐이라 진짜 문제인
 *    줄 높이는 그대로였다. 이제 **그룹**으로 접는다 - 옛 `cold` 슬롯은 그룹 "Cold" 로
 *    읽힌다(저장은 안 바꾼다).
 */
export function createCharacterPanel({
  document,
  escHtml,
  bindTagAssist,
  flushCharacterEdits,
  setModuleParam,
  showPromptDialog = null,
}) {
  const moduleBody = document.getElementById('modulePopupBody');

  const TABS = [
    {key: 'history', label: '히스토리'},
    {key: 'assets', label: '에셋'},
    {key: 'search', label: '검색'},
    {key: 'groups', label: '그룹'},
    {key: 'tools', label: '도구'},
  ];

  let lastState = null;
  let lastRenderedStructureSignature = '';
  let deferredFocusedRenderState = null;
  let deferredFocusTarget = null;
  let tab = 'history';
  let query = '';
  let favouritesOnly = false;
  let groupFilter = '';

  /** 이 패널은 showToast 를 주입받지 않는다 - 전역이 있으면 쓴다. */
  function showToastSafe(message) {
    if (typeof window !== 'undefined' && typeof window.showToast === 'function') {
      window.showToast(message, 'info');
    }
  }

  function escAttr(value) {
    return escHtml(String(value ?? '')).replace(/"/g, '&quot;');
  }

  function slotState(character) {
    const raw = String(character?.slot_state || '').toLowerCase();
    if (raw === 'active' || raw === 'inactive' || raw === 'cold') return raw;
    return character?.active ? 'active' : 'inactive';
  }

  /**
   * 목록 한 줄에 보일 이름. 사용자가 지은 이름이 있으면 그것이 이긴다.
   *
   * ⚠️ 히스토리에서는 **프롬프트 전문**을 쓴다(넘치면 CSS 가 자른다). 첫 태그만
   *    잘라 쓰면 `1girl` 이 여럿이라 서로 구분이 안 된다(실측: 보관 4줄 중 3줄이
   *    `1girl`/`1boy` 였다). 슬롯 쪽은 아래에 프롬프트 칸이 붙어 있으니 짧아도 된다.
   */
  function slotLabel(character, {full = false} = {}) {
    const custom = String(character?.custom_name || '').trim();
    if (custom) return custom;
    const prompt = String(character?.prompt || '').trim();
    if (!prompt) return '(비어 있음)';
    return full ? prompt : prompt.split(',')[0].trim();
  }

  function groupOf(character) {
    return String(character?.group || '').trim();
  }

  // ── 편집 중 재렌더 방지 ────────────────────────────────────────────────
  //
  // ⚠️ 서버 에코가 **포커스된 textarea 를 갈아치우면** 태그 자동완성이 고르기 전에
  //    닫힌다. 구조가 그대로면 다시 그리지 않고 미뤄 둔다.

  function characterStructureSignature(state) {
    const chars = state?.characters || [];
    return [
      state?.activated ? 1 : 0,
      state?.reroll_on_generate ? 1 : 0,
      tab, query, favouritesOnly ? 1 : 0, groupFilter,
      chars.length,
      chars.map(item => [
        item.slot_uuid, slotState(item), item.muted ? 1 : 0,
        item.favorite ? 1 : 0, groupOf(item), item.custom_name || '',
      ].join(':')).join('|'),
    ].join('#');
  }

  function focusedCharacterTextarea() {
    const active = document.activeElement;
    if (!active || active.tagName !== 'TEXTAREA') return null;
    return active.closest('.cw-slot') ? active : null;
  }

  function clearDeferredFocusedRender() {
    if (deferredFocusTarget) {
      deferredFocusTarget.removeEventListener('blur', flushDeferredFocusedRender);
      deferredFocusTarget = null;
    }
    deferredFocusedRenderState = null;
  }

  function queueDeferredFocusedRender(textarea, state) {
    deferredFocusedRenderState = state;
    if (deferredFocusTarget === textarea) return;
    if (deferredFocusTarget) deferredFocusTarget.removeEventListener('blur', flushDeferredFocusedRender);
    deferredFocusTarget = textarea;
    textarea.addEventListener('blur', flushDeferredFocusedRender);
  }

  function flushDeferredFocusedRender() {
    const pending = deferredFocusedRenderState;
    clearDeferredFocusedRender();
    if (pending) render(pending);
  }

  /** Quick 과 같은 규약: 최소 줄수는 지키되 넘치면 한 줄씩 늘어난다. */
  function autoGrow(element) {
    const rows = element.dataset.cwMin === 'uc' ? 1 : 2;
    const line = 1.4 * 11;                       // .cw-input 의 line-height * font-size
    const min = Math.round(rows * line) + 12;    // + 세로 패딩
    element.style.height = 'auto';
    element.style.height = Math.max(min, element.scrollHeight) + 'px';
  }

  // ── 조작 ────────────────────────────────────────────────────────────────

  function addSlot() {
    if (flushCharacterEdits) flushCharacterEdits();
    setModuleParam('character', 'add_character', 'true');
  }

  function removeSlot(index) {
    setModuleParam('character', `remove_character_${index}`, 'true');
  }

  function refreshPreview() {
    if (flushCharacterEdits) flushCharacterEdits();
    setModuleParam('character', 'preview_refresh', 'true');
  }

  function setSlotState(index, state) {
    setModuleParam('character', `char_slot_state_${index}`, state);
  }

  /**
   * 슬롯 별칭. **화면에는 버튼이 없다**(사용자 지정 2026-09-02):
   *   "이름 바꾸기는 필요없는것이, 애초에 검색을 통해 내부 컨텐츠를 읽을 수
   *    있으면 문제없기 때문입니다."
   * 히스토리 검색이 프롬프트 전문을 훑으므로 별칭 없이도 찾을 수 있다.
   * ⚠️ 함수는 남긴다 - `app.js` 의 전역 `renameCharacterSlot` 이 이것을 부르고,
   *    이미 붙어 있는 별칭은 목록에서 계속 이름으로 쓰인다(`slotLabel`).
   */
  async function renameSlot(index) {
    const character = (lastState?.characters || [])[index];
    if (!character || !showPromptDialog) return;
    const next = await showPromptDialog({
      title: '슬롯 이름',
      message: '이 캐릭터를 목록에서 무엇으로 부를까요? (비우면 프롬프트 앞머리)',
      value: String(character.custom_name || ''),
    });
    if (next === null) return;
    setModuleParam('character', `char_slot_name_${index}`, String(next).trim());
  }

  async function editGroup(index) {
    const character = (lastState?.characters || [])[index];
    if (!character || !showPromptDialog) return;
    const next = await showPromptDialog({
      title: '그룹',
      message: '이 캐릭터를 어느 그룹에 둘까요? (비우면 그룹 없음)',
      value: groupOf(character),
    });
    if (next === null) return;
    setModuleParam('character', `char_group_${index}`, String(next).trim());
  }

  // ── 왼쪽: 활성 슬롯 (전부 펼침) ─────────────────────────────────────────

  function renderSlot(character, index, ordinal) {
    const muted = !!character.muted;
    return `
      <div class="cw-slot${muted ? ' is-muted' : ''}" data-cw-slot="${index}">
        <div class="cw-slot-row">
          <button type="button" class="cw-slot-en${muted ? '' : ' is-on'}"
            data-cw-mute="${index}" title="${muted ? '이 슬롯을 켠다' : '이 슬롯을 끈다 (자리는 그대로)'}">✔</button>
          <span class="cw-slot-name">C${ordinal} · ${escHtml(slotLabel(character))}</span>
          <button type="button" class="cw-slot-btn${character.favorite ? ' is-star' : ''}"
            data-cw-fav="${index}" title="즐겨찾기">${character.favorite ? '★' : '☆'}</button>
          <!-- ⚠️ **지우면 히스토리로 간다**(사용자 지정 2026-09-02). 그래서 위험
               색을 쓰지 않는다 - 잃는 것이 없다. 예전의 ▼(내리기)와 ✕(삭제)가
               같은 일이 되어 컨트롤이 하나로 줄었다. -->
          <button type="button" class="cw-slot-btn" data-cw-down="${index}"
            title="히스토리로 보낸다 (거기서 다시 담을 수 있다)">✕</button>
        </div>
        <div class="cw-slot-body">
          <textarea class="cw-input" data-cw-field="char_prompt_${index}" data-cw-min="prompt"
            rows="2" placeholder="캐릭터 프롬프트">${escHtml(character.prompt || '')}</textarea>
          <textarea class="cw-input is-uc" data-cw-field="char_uc_${index}" data-cw-min="uc"
            rows="1" placeholder="캐릭터 네거티브 (UC)">${escHtml(character.uc || '')}</textarea>
        </div>
      </div>`;
  }

  function renderSlots(activeSlots, total, maxSlots) {
    // ⚠️ 상한은 **서버가 준 값**을 쓴다. 프런트가 자기 숫자를 들고 있으면 둘이
    //    어긋나 "눌리는데 안 늘어나는" 버튼이 된다(백엔드는 조용히 거절한다).
    //
    // ⚠️ **활성만 센다.** 처음엔 전체 프레임 수로 셌는데, 그러면 히스토리가 슬롯
    //    자리를 먹는다 - `1 active · 39 stored` 인데 `+ Add Character (40/25)` 로
    //    잠겨 캐릭터를 못 늘렸다(사용자 제보). 상한은 **나가는 개수**의 상한이고,
    //    히스토리는 나가지 않는다.
    const used = activeSlots.length;
    const full = maxSlots > 0 && used >= maxSlots;
    const body = activeSlots.length
      ? activeSlots.map(({character, index}, i) => renderSlot(character, index, i + 1)).join('')
      : '<div class="cw-slots-empty">활성 슬롯이 없습니다.<br>히스토리에서 담거나 새로 추가하세요.</div>';
    return `
      <div class="cw-slots">
        <div class="cw-slots-head">
          <span>슬롯</span><span class="cw-sp"></span>
          <span>${used}${maxSlots ? ` / ${maxSlots}` : ''}</span>
        </div>
        <div class="cw-slots-scroll">
          ${body}
          <button type="button" class="cw-add" data-cw-add="1"${full ? ' disabled' : ''}
            title="${full ? `활성 슬롯은 최대 ${maxSlots}개입니다` : ''}">${
            full ? `+ Add Character (${used}/${maxSlots})` : '+ Add Character'}</button>
        </div>
      </div>`;
  }

  // ── 오른쪽: 작업 영역 ───────────────────────────────────────────────────

  function matchesQuery(character) {
    const needle = query.trim().toLowerCase();
    if (!needle) return true;
    return [character.prompt, character.uc, character.custom_name, groupOf(character)]
      .join(' ').toLowerCase().includes(needle);
  }

  function renderHistory(storedSlots, groups) {
    // ⚠️ 히스토리는 **최근에 쓴 것이 위**다. 백엔드 배열 순서는 저장 순서라
    //    그대로 두면 오래된 것이 위에 남는다(index 주소는 건드리지 않는다 -
    //    보이는 순서만 바꾸고 각 행은 자기 index 를 그대로 들고 다닌다).
    const rows = [...storedSlots]
      .sort((a, b) => (b.character.used_at || 0) - (a.character.used_at || 0))
      .filter(({character}) => !favouritesOnly || character.favorite)
      .filter(({character}) => !groupFilter || groupOf(character) === groupFilter)
      .filter(({character}) => matchesQuery(character));
    const groupChips = groups.map(name =>
      `<button type="button" class="cw-chip${groupFilter === name ? ' is-on' : ''}"
        data-cw-group-filter="${escAttr(name)}">${escHtml(name)}</button>`).join('');
    const list = rows.length
      ? rows.map(({character, index}) => `
          <div class="cw-li" data-cw-li="${index}" data-cw-load="${index}"
            title="누르면 슬롯 맨 아래에 담긴다">
            <button type="button" class="cw-li-star${character.favorite ? ' is-on' : ''}"
              data-cw-fav="${index}" title="즐겨찾기">${character.favorite ? '★' : '☆'}</button>
            <span class="cw-li-text">${escHtml(slotLabel(character, {full: true}))}</span>

            ${groupOf(character)
              ? `<button type="button" class="cw-li-group" data-cw-editgroup="${index}"
                  title="그룹 바꾸기">${escHtml(groupOf(character))}</button>`
              : `<button type="button" class="cw-li-group cw-reveal" data-cw-editgroup="${index}"
                  title="그룹에 넣기">+ 그룹</button>`}
          </div>`).join('')
      : `<div class="cw-empty">${storedSlots.length ? '조건에 맞는 캐릭터가 없습니다.' : '아직 히스토리가 없습니다. 슬롯의 ▼ 로 내리면 여기에 쌓입니다 (최대 500개).'}</div>`;
    return `
      <div class="cw-filters">
        <input class="cw-search" type="search" value="${escAttr(query)}"
          placeholder="캐릭터 · 태그 · 그룹 검색…" data-cw-search="1">
        <button type="button" class="cw-chip${favouritesOnly ? ' is-on' : ''}" data-cw-fav-only="1"
          title="즐겨찾기만">★</button>
        <button type="button" class="cw-chip${groupFilter ? '' : ' is-on'}" data-cw-group-filter="">전체</button>
        ${groupChips}
      </div>
      <div class="cw-list">${list}</div>`;
  }

  function renderGroups(storedSlots, groups) {
    const counts = new Map();
    storedSlots.forEach(({character}) => {
      const name = groupOf(character) || '(그룹 없음)';
      counts.set(name, (counts.get(name) || 0) + 1);
    });
    const rows = [...counts.entries()].map(([name, count]) => `
      <div class="cw-li">
        <span class="cw-li-text">${escHtml(name)}</span>
        <span class="cw-li-group">${count}</span>
      </div>`).join('');
    return `<div class="cw-list">${rows || '<div class="cw-empty">그룹이 없습니다.</div>'}</div>`;
  }

  function renderTools(state) {
    const preview = String(state.processed_preview_text || '');
    return `
      <div class="cw-tools">
        <label class="cw-tool-row">
          <input type="checkbox" ${state.reroll_on_generate ? 'checked' : ''} data-cw-reroll="1">
          <span>Generate 버튼을 누를 때 캐릭터 와일드카드 재굴림</span>
        </label>
        <div class="cw-tool-row">
          <button type="button" class="cw-chip" data-cw-refresh="1">Refresh Preview</button>
          <button type="button" class="cw-chip" data-cw-assets="1">Assets ↗</button>
        </div>
        <div class="cw-tool-note">
          미리보기는 저장된 롤을 그대로 보여 줍니다 — 열어도 다시 굴리지 않습니다.
        </div>
        ${preview.trim()
          ? `<pre class="mod-char-preview-text">${escHtml(preview)}</pre>`
          : '<div class="cw-empty">아직 미리보기가 없습니다. [Refresh Preview] 를 누르세요.</div>'}
      </div>`;
  }

  function renderWork(state, storedSlots, groups) {
    const tabs = TABS.map(item =>
      `<button type="button" class="cw-tab${tab === item.key ? ' is-active' : ''}"
        data-cw-tab="${item.key}">${item.label}</button>`).join('');
    let body;
    if (tab === 'history') body = renderHistory(storedSlots, groups);
    else if (tab === 'groups') body = renderGroups(storedSlots, groups);
    else if (tab === 'tools') body = renderTools(state);
    else if (tab === 'assets') {
      // ⚠️ 기존 에셋 기능을 **옮기지 않는다**(사용자 지정: "기존 기능 제거는 아님").
      //    여기서는 그 화면으로 보내기만 한다 - 29개 라우트짜리 별개 계보다.
      body = `<div class="cw-empty">캐릭터 에셋은 이미지 기반의 별도 보관함입니다.<br><br>
        <button type="button" class="cw-chip" data-cw-assets="1">에셋 탭 열기 ↗</button></div>`;
    } else {
      body = `<div class="cw-empty">캐릭터 검색(Danbooru)은 Characters 탭에 있습니다.<br><br>
        <button type="button" class="cw-chip" data-cw-search-tab="1">Characters 탭 열기 ↗</button></div>`;
    }
    return `<div class="cw-work"><div class="cw-tabs">${tabs}<span class="cw-tab-fill"></span></div>${body}</div>`;
  }

  // ── 렌더 ────────────────────────────────────────────────────────────────

  function render(state) {
    const nextState = state || {};
    const structureSignature = characterStructureSignature(nextState);
    const focusedTextarea = focusedCharacterTextarea();
    if (focusedTextarea && lastRenderedStructureSignature === structureSignature) {
      lastState = nextState;
      queueDeferredFocusedRender(focusedTextarea, nextState);
      return;
    }
    clearDeferredFocusedRender();
    lastState = nextState;

    const chars = nextState.characters || [];
    const indexed = chars.map((character, index) => ({character, index}));
    // ⚠️ 배열은 백엔드가 [active][inactive][cold] 로 정렬해 보낸다. 여기서 순서를
    //    다시 만들지 않는다 - 만들면 index 주소가 저장 순서와 어긋난다.
    const activeSlots = indexed.filter(item => slotState(item.character) === 'active');
    const storedSlots = indexed.filter(item => slotState(item.character) !== 'active');
    const groups = [...new Set(storedSlots.map(item => groupOf(item.character)).filter(Boolean))].sort();

    moduleBody.innerHTML = `
      <div class="mod-character-shell">
        <div class="cw-slots-head" style="border-bottom:1px solid var(--border-dim)">
          <label class="cw-tool-row" style="gap:6px">
            <input type="checkbox" ${nextState.activated ? 'checked' : ''} data-cw-activated="1">
            <span>캐릭터 프롬프트 활성화</span>
          </label>
          <span class="cw-sp"></span>
          <span>${nextState.active_count || 0} active · ${storedSlots.length} stored</span>
        </div>
        <div class="cw-body">
          ${renderSlots(activeSlots, chars.length, Number(nextState.max_slots) || 0)}
          ${renderWork(nextState, storedSlots, groups)}
        </div>
      </div>`;

    moduleBody.querySelectorAll('.cw-input').forEach(element => {
      autoGrow(element);
      if (!element.classList.contains('is-uc')) bindTagAssist(element);
    });
    bindEvents();
    lastRenderedStructureSignature = structureSignature;
  }

  // ── 이벤트 (렌더마다 새 뿌리에 건다 - innerHTML 이 옛 리스너를 함께 지운다) ──

  function bindEvents() {
    const root = moduleBody.querySelector('.mod-character-shell');
    if (!root) return;

    root.addEventListener('input', event => {
      const field = event.target.closest('[data-cw-field]');
      if (field) {
        autoGrow(field);
        setModuleParam('character', field.dataset.cwField, field.value);
        return;
      }
      const search = event.target.closest('[data-cw-search]');
      if (search) { query = search.value; scheduleRerender(); return; }
      const activated = event.target.closest('[data-cw-activated]');
      if (activated) { setModuleParam('character', 'activated', String(activated.checked)); return; }
      const reroll = event.target.closest('[data-cw-reroll]');
      if (reroll) setModuleParam('character', 'reroll_on_generate', String(reroll.checked));
    });

    root.addEventListener('click', event => {
      const hit = selector => event.target.closest(selector);
      const tabBtn = hit('[data-cw-tab]');
      if (tabBtn) { tab = tabBtn.dataset.cwTab; rerender(); return; }
      const add = hit('[data-cw-add]');
      if (add) {
        if (add.disabled) {
          const max = Number(lastState?.max_slots) || 0;
          showToastSafe(`활성 캐릭터 슬롯은 최대 ${max}개입니다.`);
          return;
        }
        addSlot();
        return;
      }

      const fav = hit('[data-cw-fav]');
      if (fav) {
        const index = Number(fav.dataset.cwFav);
        const character = (lastState?.characters || [])[index];
        setModuleParam('character', `char_favorite_${index}`, String(!character?.favorite));
        return;
      }
      const down = hit('[data-cw-down]');
      if (down) { setSlotState(Number(down.dataset.cwDown), 'inactive'); return; }
      const group = hit('[data-cw-editgroup]');
      if (group) { void editGroup(Number(group.dataset.cwEditgroup)); return; }
      const load = hit('[data-cw-load]');
      if (load) { setSlotState(Number(load.dataset.cwLoad), 'active'); return; }
      const remove = hit('[data-cw-remove]');
      if (remove) { removeSlot(Number(remove.dataset.cwRemove)); return; }
      const mute = hit('[data-cw-mute]');
      if (mute) {
        const index = Number(mute.dataset.cwMute);
        const character = (lastState?.characters || [])[index];
        setModuleParam('character', `char_muted_${index}`, String(!character?.muted));
        return;
      }


      if (hit('[data-cw-fav-only]')) { favouritesOnly = !favouritesOnly; rerender(); return; }
      const groupFilterBtn = hit('[data-cw-group-filter]');
      if (groupFilterBtn) { groupFilter = groupFilterBtn.dataset.cwGroupFilter; rerender(); return; }
      if (hit('[data-cw-refresh]')) { refreshPreview(); return; }
      if (hit('[data-cw-assets]')) { window.openCharacterAssetTab?.(); return; }
      if (hit('[data-cw-search-tab]')) window.openCharacterViewerTab?.();
    });

    root.addEventListener('contextmenu', event => {
      // ⚠️ 슬롯 행에서는 아무것도 가로채지 않는다 - 이름 조작이 히스토리로 갔고,
      //    프롬프트 칸에서 우클릭하면 붙여넣기 같은 기본 메뉴가 떠야 한다.
      // 히스토리 행은 그룹의 지름길로 남긴다(버튼도 함께 보인다).
      const item = event.target.closest('[data-cw-li]');
      if (!item) return;
      event.preventDefault();
      void editGroup(Number(item.dataset.cwLi));
    });
  }

  /** 검색어처럼 서버를 안 거치는 값은 그 자리에서 다시 그린다. */
  function rerender() {
    lastRenderedStructureSignature = '';
    render(lastState || {});
  }

  // ⚠️ 검색은 글자마다 다시 그리면 입력 칸이 갈리며 커서가 튄다. 목록만 갈아 끼운다.
  function scheduleRerender() {
    const list = moduleBody.querySelector('.cw-list');
    if (!list) { rerender(); return; }
    const chars = lastState?.characters || [];
    const indexed = chars.map((character, index) => ({character, index}));
    const storedSlots = indexed.filter(item => slotState(item.character) !== 'active');
    const groups = [...new Set(storedSlots.map(item => groupOf(item.character)).filter(Boolean))].sort();
    const html = renderHistory(storedSlots, groups);
    const parsed = document.createElement('div');
    parsed.innerHTML = html;
    const nextList = parsed.querySelector('.cw-list');
    if (nextList) list.innerHTML = nextList.innerHTML;
  }

  // 다른 창(예: Image Tagger 결과)이 '어느 캐릭터에 넣을까' 를 물으려면
  // 슬롯 목록이 필요하다. 렌더 상태를 그대로 빌려준다(사본).
  const getCharacters = () => (Array.isArray(lastState?.characters) ? [...lastState.characters] : []);

  // ⚠️ Cold 서랍은 사라졌다(그룹으로 접었다). app.js 의 옛 호출부가 남아 있으므로
  //    빈 껍데기를 남겨 둔다 - 없애면 `characterPanel.hideColdPanel is not a function`.
  const noop = () => {};

  return {
    getCharacters,
    addSlot,
    removeSlot,
    refreshPreview,
    setSlotState,
    renameSlot,
    render,
    toggleColdPanel: noop,
    hideColdPanel: noop,
    setColdSearch: noop,
  };
}
