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
 *    줄 높이는 그대로였다. 이제 **그룹**으로 접는다 - 옛 `cold` 슬롯은 그룹 "Cold Storage" 로
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

  // ⚠️ 즐겨찾기는 **그룹이 아니라 플래그**다. 그룹 탭에 한 줄로 섞어 뒀더니 사용자가
  //    그룹으로 오해했다(제보 2026-09-02: 거기서 빼면 그룹에서 빠지는 줄 알았다).
  //    히스토리 옆 **자기 탭**으로 뗀다 - 같은 목록의 다른 보기라는 뜻이 또렷해진다.
  const TABS = [
    {key: 'history', label: '히스토리'},
    {key: 'favourites', label: '즐겨찾기'},
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
  // ⚠️ **uuid 로 잡는다.** index 는 슬롯이 무리를 옮길 때마다 밀려서, 펼쳐 둔
  //    항목이 조용히 다른 캐릭터로 바뀐다.
  const openHistory = new Set();
  // '즉시 생성' 은 복원이 서버에 반영된 **뒤에** 생성해야 한다 - 바로 부르면
  // 아직 활성이 아닌 상태로 나간다. 되돌아온 상태에서 활성이 된 것을 보고 쏜다.
  let pendingGenerateUuid = '';
  // '그룹에 전달' 을 누른 히스토리 항목(uuid). 그 항목 아래에 그룹 고르기 줄이 열린다.
  let groupPickerUuid = '';
  // 그룹 탭의 검색어. **그룹 안의 항목**을 찾는다(사용자 지정 2026-09-02) - 그룹
  // 이름을 찾는 것이 아니다. 이름은 눈에 다 보이지만 안에 무엇이 들었는지는 안 보인다.
  let groupQuery = '';
  // 그룹 탭에서 펼쳐 둔 그룹. 키는 `g:이름` · 즐겨찾기 `fav` · 그룹 없음 `none`.
  const openGroups = new Set();
  // ⚠️ 그룹 행의 키를 **그룹 이름 그대로 쓰면 안 된다.** 사용자가 `★` 이라는 그룹을
  //    만들 수 있고(백엔드가 막지 않는다), 그러면 즐겨찾기 행과 키가 겹쳐 그 그룹의
  //    멤버가 영영 안 보이고 드롭도 즐겨찾기로 샌다(실측 재현).
  //    이름은 `g:` 뒤에만 둔다 - 그러면 어떤 이름도 `fav`/`none` 과 겹치지 않는다.
  const GRP_FAV = 'fav';
  const GRP_NONE = 'none';
  const grpKey = name => 'g:' + name;
  const grpName = key => (String(key || '').slice(0, 2) === 'g:' ? String(key).slice(2) : '');
  // 드래그 규약은 interactiveScenePanel 과 같다: 우리 자료형 하나로 **우리 것만** 받고,
  // 끌기 도중 다시 그려져 원본이 사라지면 `dragend` 가 오지 않으므로 표를 직접 버린다.
  const DND_MIME = 'application/x-naia-charslot';
  let dragUuid = '';

  /** 그룹 목록은 **서버가 SSOT** 다(빈 그룹도 있어야 하므로 프레임에서 뽑지 않는다). */
  function groupsOf(state) {
    const list = Array.isArray(state?.groups) ? state.groups.map(g => String(g || '').trim()).filter(Boolean) : [];
    return [...new Set(list)];
  }


  /** 우리 자료형을 든 끌기가 그룹 행 위에 있을 때만 그 행. 파일·남의 글은 무시한다. */
  function dropTarget(event) {
    const el = event.target && event.target.closest ? event.target.closest('[data-cw-drop]') : null;
    if (!el) return null;
    const types = (event.dataTransfer && event.dataTransfer.types) || [];
    const mine = types.includes ? types.includes(DND_MIME)
      : Array.prototype.indexOf.call(types, DND_MIME) >= 0;
    return mine ? el : null;
  }
  function clearDrag() {
    dragUuid = '';
    moduleBody.querySelectorAll('.is-dragging, .is-drop, .is-dropzone')
      .forEach(el => el.classList.remove('is-dragging', 'is-drop', 'is-dropzone'));
  }

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

  /** 그룹 배경 색조. 서버가 **만들 때 무작위로** 배정해 둔 값이다. */
  function hueOf(name) {
    const map = lastState?.group_colors;
    const raw = map && Object.prototype.hasOwnProperty.call(map, name) ? map[name] : null;
    return Number.isFinite(Number(raw)) ? Number(raw) : null;
  }

  /** 색을 인라인으로 문다 - 그룹 수가 정해져 있지 않아 CSS 클래스로는 못 쓴다. */
  function hueStyle(name) {
    const hue = name ? hueOf(name) : null;
    return hue === null ? '' : ` style="--cw-grp-hue:${hue}"`;
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
      tab, query, groupQuery,
      JSON.stringify(state?.group_colors || {}),
      [...openHistory].sort().join(','),
      groupsOf(state).join(','), groupPickerUuid,
      [...openGroups].sort().join(','),
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
    const next = await showPromptDialog('이 캐릭터를 목록에서 무엇으로 부를까요? (비우면 프롬프트 앞머리)', {
      title: '슬롯 이름', defaultValue: String(character.custom_name || ''),
    });
    if (next === null) return;
    setModuleParam('character', `char_slot_name_${index}`, String(next).trim());
  }

  /** 새 그룹. **내장 팝업**이 이름을 받는다(사용자 지정 2026-09-02). */
  async function createGroup() {
    if (!showPromptDialog) return;
    // ⚠️ 시그니처는 `showPromptDialog(message, options)` 다 - 객체 하나로 부르면
    //    `escHtml(object)` 에서 터진다(실측: TypeError s.replace is not a function).
    const next = await showPromptDialog('만들 그룹의 이름을 적어 주세요.', {
      title: '새 그룹', okText: '만들기', defaultValue: '',
    });
    const name = String(next ?? '').trim();
    if (!name) return;
    setModuleParam('character', 'add_group', name);
  }

  async function editGroup(index) {
    const character = (lastState?.characters || [])[index];
    if (!character || !showPromptDialog) return;
    const next = await showPromptDialog('새 그룹 이름을 적으면 만들어서 넣습니다.', {
      title: '그룹', okText: '넣기', defaultValue: groupOf(character),
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

  /**
   * 히스토리·즐겨찾기 검색. **프롬프트 쪽만 본다.**
   *
   * ⚠️ 그룹 이름은 빼 뒀다(사용자 지정 2026-09-02: "히스토리에서는 그룹까지 검색하는
   *    것이 비현실적입니다"). 그룹 하나에 수십 개가 들어 있으면 그 이름을 친 순간
   *    목록이 통째로 나와, 찾으려던 캐릭터가 오히려 묻힌다. 그룹으로 좁히는 일은
   *    **그룹 탭**이 펼쳐서 한다.
   */
  function matchesQuery(character) {
    const needle = query.trim().toLowerCase();
    if (!needle) return true;
    return [character.prompt, character.uc, character.custom_name]
      .join(' ').toLowerCase().includes(needle);
  }

  /** 히스토리 한 항목. 히스토리 탭과 그룹 탭(펼친 그룹 안)이 **같은 것**을 그린다. */
  /**
   * 히스토리 한 항목. 히스토리 탭과 그룹 탭(펼친 그룹 안)이 **같은 것**을 그린다.
   *
   * @param inGroup 그룹 탭에서 그린다면 그 행의 키(`fav` · `none` · `g:이름`).
   *   ⚠️ 오른쪽 끝 버튼의 **뜻이 달라진다**(사용자 제보 2026-09-02):
   *     히스토리 -> ✕ 영구 삭제 (전체 목록이니 그것이 옳다)
   *     그룹 안  -> − 이 그룹에서 빼기 (거기 있는 것은 **한 그룹의 사본이 아니라
   *                같은 캐릭터**다 - 지우면 즐겨찾기·히스토리에서 함께 사라진다.
   *                실제로 사용자가 그렇게 잃었다.)
   */
  function renderHistoryItem(character, index, groups, inGroup) {
    const uuid = String(character.slot_uuid || '');
    const open = openHistory.has(uuid);
    return `
    <div class="cw-li${open ? ' is-open' : ''}${groupOf(character) ? ' has-hue' : ''}"
      data-cw-li="${index}"${hueStyle(groupOf(character))}>
      <!-- ⚠️ 툴팁은 **프롬프트 전문**이다(사용자 지정 2026-09-02). 조작 설명을 띄우면
           정작 궁금한 것(잘린 뒷부분)을 볼 길이 없다. -->
      <div class="cw-li-row" data-cw-toggle="${escAttr(uuid)}" draggable="true"
        data-cw-drag="${index}" data-cw-drag-uuid="${escAttr(uuid)}"
        title="${escAttr(character.prompt || '(비어 있음)')}">
        <!-- 왼쪽 끝 = 복원(사용자 지정 2026-09-02). 슬롯 맨 아래로 간다. -->
        <button type="button" class="cw-li-btn" data-cw-load="${index}"
          title="슬롯으로 복원">↩</button>
        <!-- ⚠️ 즐겨찾기는 이제 **표시**다(조작은 펼친 뒤에 있다) - 안 보이면
             위의 ★ 필터가 무엇을 거르는지 알 수 없다. -->
      <span class="cw-li-text">${character.favorite ? '<span class="cw-li-fav">★</span> ' : ''}${escHtml(slotLabel(character, {full: true}))}</span>
        <!-- ⚠️ 그룹 안에서는 칩을 안 그린다 - **머리줄이 이미 그 이름**이다.
             히스토리·즐겨찾기에는 머리줄이 없으니 거기서는 남긴다. -->
        ${!inGroup && groupOf(character)
          ? `<span class="cw-li-group">${escHtml(groupOf(character))}</span>`
          : ''}
        <!-- 오른쪽 끝 = 삭제(사용자 지정). 여기가 **영영 지우는 유일한 길**이다 -
             슬롯의 ✕ 는 히스토리로 보낼 뿐이다. -->
        ${inGroup
          ? `<button type="button" class="cw-li-btn" data-cw-ungroup="${index}"
              data-cw-ungroup-key="${escAttr(inGroup)}"
              title="${inGroup === GRP_FAV ? '즐겨찾기에서 뺀다' : '이 그룹에서 뺀다 (캐릭터는 남는다)'}">−</button>`
          : `<button type="button" class="cw-li-btn is-danger" data-cw-remove="${index}"
              title="영구 삭제">✕</button>`}
      </div>
      ${open ? `
      <div class="cw-li-body">
        <div class="cw-li-field">${escHtml(character.prompt || '(비어 있음)')}</div>
        <div class="cw-li-field is-uc">${escHtml(character.uc || '(네거티브 없음)')}</div>
        ${groupPickerUuid === uuid ? `
        <div class="cw-li-picker">
          ${groups.map(name => `<button type="button" class="cw-chip${groupOf(character) === name ? ' is-on' : ''}"
            data-cw-pick-group="${index}" data-cw-group-name="${escAttr(name)}">${escHtml(name)}</button>`).join('')}
          <button type="button" class="cw-chip" data-cw-pick-group="${index}" data-cw-group-name="">그룹 해제</button>
          <button type="button" class="cw-chip is-go" data-cw-new-group-for="${index}">+ 새 그룹</button>
        </div>` : ''}
        <div class="cw-li-actions">
          <button type="button" class="cw-li-act${groupPickerUuid === uuid ? ' is-on' : ''}" data-cw-editgroup="${index}"
            data-cw-uuid="${escAttr(uuid)}">그룹에 전달</button>
          <button type="button" class="cw-li-act${character.favorite ? ' is-on' : ''}"
            data-cw-fav="${index}">${character.favorite ? '즐겨찾기 해제' : '즐겨찾기 등록'}</button>
          <button type="button" class="cw-li-act is-go" data-cw-gen="${index}">즉시 생성</button>
        </div>
      </div>` : ''}
    </div>`;
  }

  /**
   * 히스토리 · 즐겨찾기 목록. 둘은 **같은 목록의 다른 보기**라 한 함수로 그린다.
   *
   * @param onlyFav 즐겨찾기 탭이면 true - 별을 단 것만 보이고, 오른쪽 끝 버튼이
   *   `−`(즐겨찾기 해제)가 된다. 히스토리에서만 `✕`(영구 삭제)다.
   */
  function renderHistory(storedSlots, groups, onlyFav) {
    // ⚠️ 최근에 쓴 것이 위다. 백엔드 배열 순서는 저장 순서라 그대로 두면 오래된 것이
    //    위에 남는다(index 주소는 건드리지 않는다 - 보이는 순서만 바꾼다).
    const rows = [...storedSlots]
      .sort((a, b) => (b.character.used_at || 0) - (a.character.used_at || 0))
      .filter(({character}) => !onlyFav || character.favorite)
      .filter(({character}) => matchesQuery(character));
    const empty = onlyFav
      ? (storedSlots.length ? '조건에 맞는 즐겨찾기가 없습니다.' : '즐겨찾기가 없습니다. 항목을 펼쳐 [즐겨찾기 등록] 을 누르세요.')
      : (storedSlots.length ? '조건에 맞는 캐릭터가 없습니다.' : '아직 히스토리가 없습니다. 슬롯의 ✕ 로 지우면 여기에 쌓입니다 (최대 500개).');
    const list = rows.length
      ? rows.map(({character, index}) =>
          renderHistoryItem(character, index, groups, onlyFav ? GRP_FAV : '')).join('')
      : `<div class="cw-empty">${empty}</div>`;
    return `
      <div class="cw-filters">
        <input class="cw-search" type="search" value="${escAttr(query)}"
          placeholder="프롬프트 · 태그 검색…" data-cw-search="1">
        <!-- ⚠️ 그룹 칩과 ★ 칩은 걷었다(사용자 지정 2026-09-02). 그룹은 **그룹 탭**이
             펼쳐서 보여 주고 즐겨찾기는 **자기 탭**이 있다 - 여기 두면 같은 길이
             둘이고, 늘수록 검색칸을 밀어낸다. -->
      </div>
      <div class="cw-list">${list}</div>`;
  }

  /**
   * 그룹 탭 - 만들고, 지우고, 들여다본다(사용자 지정 2026-09-02).
   *
   * ⚠️ 즐겨찾기는 **그룹처럼** 보이되 항상 맨 위다(사용자 지정). 실제로는 플래그라
   *    지울 수 없다 - 그래서 ✕ 가 없다.
   * ⚠️ Cold 는 폐기된 상태다. 옛 cold 슬롯이 있으면 "Cold Storage" 그룹이 **한 번**
   *    생기고, 그 뒤로는 다른 그룹과 똑같다 - 지우면 사라진다(사용자 지적 2026-09-02).
   */
  function renderGroups(storedSlots, groups) {
    // 최근에 쓴 것이 위 - 히스토리 탭과 같은 순서.
    const ordered = [...storedSlots]
      .sort((a, b) => (b.character.used_at || 0) - (a.character.used_at || 0));
    const needle = groupQuery.trim().toLowerCase();
    const hit = character => !needle ||
      [character.prompt, character.uc, character.custom_name]
        .join(' ').toLowerCase().includes(needle);
    const members = key => ordered.filter(({character}) =>
      groupOf(character) === grpName(key) && hit(character));
    // ⚠️ 누르면 **그 자리에서 펼친다**(사용자 지정 2026-09-02: 탭을 옮기는 것은
    //    싫다). 펼친 안쪽은 히스토리 탭과 같은 항목이라 복원·삭제·펼침이 그대로 된다.
    const row = (key, label, {pinned = false, deletable = true} = {}) => {
      const items = members(key);
      // ⚠️ 검색 중에는 **맞는 것이 든 그룹만** 보이고 자동으로 펼친다 - 접힌 채
      //    개수만 바뀌면 어디에 있는지 알 수 없어 한 번 더 눌러야 한다.
      if (needle && !items.length) return '';
      const open = needle ? true : openGroups.has(key);
      return `
      <div class="cw-grp${pinned ? ' is-pinned' : ''}${open ? ' is-open' : ''}${
        grpName(key) ? ' has-hue' : ''}"${hueStyle(grpName(key))}>
        <div class="cw-grp-row" data-cw-drop="${escAttr(key)}">
          <button type="button" class="cw-grp-open" data-cw-toggle-group="${escAttr(key)}"
            title="${open ? '접는다' : '펼친다'}">
            <span class="cw-grp-caret">${open ? '▾' : '▸'}</span>
            ${escHtml(label)}
            <span class="cw-grp-count">${items.length}</span>
          </button>
          ${deletable ? `<button type="button" class="cw-li-btn is-danger" data-cw-remove-group="${escAttr(key)}"
            title="그룹 삭제 (안의 캐릭터는 그룹 없음으로 남는다)">✕</button>` : ''}
        </div>
        ${open ? `<div class="cw-grp-items">${items.length
          ? items.map(({character, index}) => renderHistoryItem(character, index, groups, key)).join('')
          : '<div class="cw-empty">비어 있습니다.</div>'}</div>` : ''}
      </div>`;
    };
    const rows = [
      // ⚠️ 즐겨찾기는 여기 없다 - **플래그이지 그룹이 아니다**(사용자 지정 2026-09-02).
      //    자기 탭에 있다.
      ...groups.map(name => row(grpKey(name), name)),
      // 그룹 없음도 한 줄이다 - 안 그러면 34개가 어디 있는지 찾을 길이 없다.
      row(GRP_NONE, '그룹 없음', {deletable: false}),
    ].join('');
    return `
      <div class="cw-filters">
        <!-- ⚠️ 여기는 **검색**이다(사용자 지정 2026-09-02). 예전엔 새 그룹 이름을 받는
             칸이었는데, 그룹이 늘면 정작 찾을 길이 없었다. 만들기는 팝업이 받는다. -->
        <input class="cw-search" type="search" value="${escAttr(groupQuery)}"
          placeholder="그룹 안에서 검색…" data-cw-group-search="1">
        <button type="button" class="cw-chip is-go" data-cw-add-group="1">+ 만들기</button>
      </div>
      <div class="cw-list cw-list-groups">${rows}</div>`;
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
    if (tab === 'history') body = renderHistory(storedSlots, groups, false);
    else if (tab === 'favourites') body = renderHistory(storedSlots, groups, true);
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
    const groups = groupsOf(nextState);

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
    if (dragUuid && !moduleBody.querySelector(`[data-cw-drag-uuid="${dragUuid.replace(/"/g, '')}"]`)) clearDrag();
    // '즉시 생성' 의 두 번째 박자 - 복원이 반영됐으면 그때 쏜다.
    if (pendingGenerateUuid) {
      const landed = chars.find(item => String(item.slot_uuid || '') === pendingGenerateUuid);
      if (landed && slotState(landed) === 'active') {
        pendingGenerateUuid = '';
        window.generateAction?.();
      }
    }
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
      const groupSearch = event.target.closest('[data-cw-group-search]');
      // ⚠️ 히스토리와 **같은 규약**이다(사용자 제보 2026-09-02: 한 글자마다 포커스가
      //    빠졌다). `rerender()` 는 입력칸까지 새로 만들어 커서를 잃는다.
      if (groupSearch) { groupQuery = groupSearch.value; scheduleRerender(); return; }
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
      const pick = hit('[data-cw-pick-group]');
      if (pick) {
        setModuleParam('character', `char_group_${Number(pick.dataset.cwPickGroup)}`, pick.dataset.cwGroupName || '');
        groupPickerUuid = '';
        return;
      }
      const newFor = hit('[data-cw-new-group-for]');
      if (newFor) { void editGroup(Number(newFor.dataset.cwNewGroupFor)); groupPickerUuid = ''; return; }
      const group = hit('[data-cw-editgroup]');
      if (group) {
        // 그룹 목록에서 고른다 - 이름을 매번 치게 하지 않는다(사용자 지정: "편히").
        const uuid = group.dataset.cwUuid || '';
        groupPickerUuid = groupPickerUuid === uuid ? '' : uuid;
        rerender();
        return;
      }
      if (hit('[data-cw-add-group]')) { void createGroup(); return; }
      const removeGroup = hit('[data-cw-remove-group]');
      if (removeGroup) {
        // 백엔드는 **이름**을 받는다 - 화면 키(`g:이름`)를 그대로 보내면 안 지워진다.
        setModuleParam('character', 'remove_group', grpName(removeGroup.dataset.cwRemoveGroup));
        return;
      }
      const toggleGroup = hit('[data-cw-toggle-group]');
      if (toggleGroup) {
        const key = toggleGroup.dataset.cwToggleGroup;
        if (openGroups.has(key)) openGroups.delete(key);
        else openGroups.add(key);
        rerender();
        return;
      }
      const load = hit('[data-cw-load]');
      if (load) { setSlotState(Number(load.dataset.cwLoad), 'active'); return; }
      const gen = hit('[data-cw-gen]');
      if (gen) {
        const index = Number(gen.dataset.cwGen);
        // ⚠️ 복원이 서버에 닿기 **전에** 생성하면 이 캐릭터 없이 나간다.
        //    표를 남기고, 되돌아온 상태에서 활성이 된 것을 보고 쏜다.
        pendingGenerateUuid = String((lastState?.characters || [])[index]?.slot_uuid || '');
        setSlotState(index, 'active');
        return;
      }
      const ungroup = hit('[data-cw-ungroup]');
      if (ungroup) {
        const index = Number(ungroup.dataset.cwUngroup);
        // ⚠️ **빼기지 삭제가 아니다.** 캐릭터는 히스토리에 그대로 남는다.
        if (ungroup.dataset.cwUngroupKey === GRP_FAV) {
          setModuleParam('character', `char_favorite_${index}`, 'false');
        } else {
          setModuleParam('character', `char_group_${index}`, '');
        }
        return;
      }
      const remove = hit('[data-cw-remove]');
      if (remove) { removeSlot(Number(remove.dataset.cwRemove)); return; }
      const mute = hit('[data-cw-mute]');
      if (mute) {
        const index = Number(mute.dataset.cwMute);
        const character = (lastState?.characters || [])[index];
        setModuleParam('character', `char_muted_${index}`, String(!character?.muted));
        return;
      }
      // ⚠️ **펼침 토글은 맨 마지막**이다. 이 표는 행 전체에 붙어 있어서, 위의
      //    버튼들보다 먼저 보면 행 안의 버튼(↩ ✕)을 눌러도 펼쳐지기만 한다
      //    (라이브에서 삭제가 안 먹었다: 히스토리 1개 -> 눌러도 1개).
      const toggle = hit('[data-cw-toggle]');
      if (toggle) {
        const uuid = toggle.dataset.cwToggle;
        if (openHistory.has(uuid)) openHistory.delete(uuid);
        else openHistory.add(uuid);
        rerender();
        return;
      }



      if (hit('[data-cw-refresh]')) { refreshPreview(); return; }
      if (hit('[data-cw-assets]')) { window.openCharacterAssetTab?.(); return; }
      if (hit('[data-cw-search-tab]')) window.openCharacterViewerTab?.();
    });

    root.addEventListener('dragstart', event => {
      const row = event.target && event.target.closest ? event.target.closest('[data-cw-drag]') : null;
      if (!row) return;
      dragUuid = row.dataset.cwDragUuid || '';
      try {
        // ⚠️ **uuid 를 싣는다.** index 를 실으면 끌기 도중 다른 에코가 목록을 다시
        //    정렬했을 때 그 번호가 이미 남의 것이라 **엉뚱한 캐릭터가 옮겨진다**.
        //    index 는 놓는 순간 현재 상태에서 다시 찾는다.
        event.dataTransfer.setData(DND_MIME, dragUuid);
        // 일부 브라우저는 표준 자료형이 하나도 없으면 끌기를 취소한다.
        event.dataTransfer.setData('text/plain', dragUuid);
        event.dataTransfer.effectAllowed = 'move';
      } catch (_) { /* 무시 */ }
      row.closest('.cw-li')?.classList.add('is-dragging');
      moduleBody.querySelectorAll('[data-cw-drop]').forEach(el => el.classList.add('is-dropzone'));
    });
    root.addEventListener('dragend', () => clearDrag());
    root.addEventListener('dragover', event => {
      const target = dropTarget(event);
      if (!target) return;
      event.preventDefault();
      event.dataTransfer.dropEffect = 'move';
      if (!target.classList.contains('is-drop')) {
        moduleBody.querySelectorAll('.is-drop').forEach(el => el.classList.remove('is-drop'));
        target.classList.add('is-drop');
      }
    });
    root.addEventListener('dragleave', event => {
      const target = event.target && event.target.closest ? event.target.closest('[data-cw-drop]') : null;
      if (target && !target.contains(event.relatedTarget)) target.classList.remove('is-drop');
    });
    root.addEventListener('drop', event => {
      const target = dropTarget(event);
      if (!target) return;
      event.preventDefault();
      let uuid = '';
      try { uuid = event.dataTransfer.getData(DND_MIME); } catch (_) { uuid = ''; }
      const key = target.dataset.cwDrop;
      clearDrag();
      // 놓는 **지금**의 상태에서 번호를 찾는다(끌던 사이에 목록이 밀렸을 수 있다).
      const index = (lastState?.characters || []).findIndex(
        item => String(item.slot_uuid || '') === uuid);
      if (!uuid || index < 0) return;
      // 그룹 행만 드롭 대상이다(`none` -> '' = 그룹 해제). 즐겨찾기는 그룹이 아니라
      // 플래그라 여기 없다 - 항목을 펼쳐 [즐겨찾기 등록] 으로 켠다.
      setModuleParam('character', `char_group_${index}`, grpName(key));
    });


    root.addEventListener('contextmenu', event => {
      // ⚠️ 슬롯 행에서는 아무것도 가로채지 않는다 - 이름 조작이 히스토리로 갔고,
      //    프롬프트 칸에서 우클릭하면 붙여넣기 같은 기본 메뉴가 떠야 한다.
      // 히스토리 행은 그룹의 지름길로 남긴다(버튼도 함께 보인다).
      const item = event.target.closest('[data-cw-li]');
      if (!item) return;
      event.preventDefault();
      const character = (lastState?.characters || [])[Number(item.dataset.cwLi)];
      const uuid = String(character?.slot_uuid || '');
      if (uuid) { openHistory.add(uuid); groupPickerUuid = uuid; rerender(); }
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
    // ⚠️ 그룹 탭도 여기로 온다. 펼친 그룹 안의 항목은 `.cw-grp-items` 안에 있고 그것은
    //    다시 `.cw-list` 안이라, 목록만 갈아 끼워도 전부 갱신된다. 전체를 다시 그리면
    //    검색 입력칸이 새로 만들어져 **한 글자마다 커서를 잃는다**(사용자 제보).
    if (!list || (tab !== 'history' && tab !== 'favourites' && tab !== 'groups')) {
      rerender();
      return;
    }
    const chars = lastState?.characters || [];
    const indexed = chars.map((character, index) => ({character, index}));
    const storedSlots = indexed.filter(item => slotState(item.character) !== 'active');
    const groups = groupsOf(lastState);
    const html = tab === 'groups'
      ? renderGroups(storedSlots, groups)
      : renderHistory(storedSlots, groups, tab === 'favourites');
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
