export function createCharacterPanel({
  document,
  escHtml,
  bindTagAssist,
  flushCharacterEdits,
  setModuleParam,
  showPromptDialog = null,
}) {
  const moduleBody = document.getElementById('modulePopupBody');
  let coldSearch = '';
  let coldPanelOpen = false;
  let lastState = null;
  let coldTooltipEl = null;
  let coldPanelHost = null;
  let resizeBound = false;
  let lastRenderedStructureSignature = '';
  let deferredFocusedRenderState = null;
  let deferredFocusTarget = null;

  function escAttr(value) {
    return String(value ?? '')
      .replace(/&/g, '&amp;')
      .replace(/"/g, '&quot;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
  }

  function slotState(character) {
    const state = String(character?.slot_state || '').toLowerCase();
    if (state === 'cold') return 'cold';
    return character?.active ? 'active' : 'inactive';
  }

  function firstPromptLine(prompt) {
    return String(prompt || '').split(/\r?\n/)[0].trim();
  }

  function coldSummary(character) {
    const customName = String(character?.custom_name || '').trim();
    if (customName) return customName;
    const firstLine = firstPromptLine(character?.prompt);
    const parts = firstLine.split(',').map(part => part.trim()).filter(Boolean);
    if (parts.length && ['girl', 'boy'].includes(parts[0].toLowerCase())) {
      parts.shift();
    }
    return parts.join(', ') || firstLine || '(empty prompt)';
  }

  function coldTooltip(character) {
    const prompt = String(character?.prompt || '').trim() || '(empty)';
    const uc = String(character?.uc || '').trim() || '(empty)';
    const customName = String(character?.custom_name || '').trim();
    return {
      title: customName ? `${customName} - C${character?.id || ''}` : `C${character?.id || ''}`,
      prompt,
      uc,
    };
  }

  function coldSearchText(character, index) {
    return [
      `c${character?.id || index + 1}`,
      character?.custom_name || '',
      coldSummary(character),
      character?.prompt || '',
      character?.uc || '',
    ].join('\n').toLowerCase();
  }

  function applyColdSearchFilter() {
    const query = coldSearch.trim().toLowerCase();
    const root = coldPanelHost || moduleBody;
    const cards = Array.from(root.querySelectorAll('.mod-cold-card'));
    let visibleCount = 0;
    cards.forEach(card => {
      const visible = !query || String(card.dataset.coldSearch || '').includes(query);
      card.hidden = !visible;
      if (visible) visibleCount += 1;
    });
    const count = root.querySelector('[data-cold-count]');
    if (count) count.textContent = `${visibleCount} / ${cards.length} stored`;
    const empty = root.querySelector('.mod-cold-empty');
    if (empty) empty.hidden = visibleCount > 0;
  }

  function ensureColdPanelHost() {
    if (coldPanelHost) return coldPanelHost;
    coldPanelHost = document.createElement('div');
    coldPanelHost.className = 'mod-character-cold-layer';
    document.body.append(coldPanelHost);
    if (!resizeBound) {
      window.addEventListener('resize', positionColdPanel);
      resizeBound = true;
    }
    return coldPanelHost;
  }

  function positionColdPanel() {
    const panel = coldPanelHost?.querySelector('.mod-character-cold-panel.open');
    const popup = document.getElementById('modulePopup');
    if (!panel || !popup) return;
    const popupRect = popup.getBoundingClientRect();
    const viewportWidth = document.documentElement.clientWidth || window.innerWidth;
    if (viewportWidth < 768) {
      panel.style.left = '4vw';
      panel.style.right = '4vw';
      panel.style.top = '72px';
      panel.style.width = 'auto';
      return;
    }
    const minWidth = 240;
    const availableRight = viewportWidth - popupRect.right - 24;
    const width = Math.max(minWidth, Math.min(340, availableRight >= minWidth ? availableRight : viewportWidth - 24));
    const left = availableRight >= minWidth
      ? popupRect.right + 12
      : Math.max(12, viewportWidth - width - 12);
    panel.style.left = `${Math.round(left)}px`;
    panel.style.right = 'auto';
    panel.style.top = `${Math.max(12, Math.round(popupRect.top))}px`;
    panel.style.width = `${Math.round(width)}px`;
  }

  function ensureColdTooltip() {
    if (coldTooltipEl) return coldTooltipEl;
    coldTooltipEl = document.createElement('div');
    coldTooltipEl.className = 'mod-cold-tooltip';
    document.body.append(coldTooltipEl);
    return coldTooltipEl;
  }

  function hideColdTooltip() {
    if (coldTooltipEl) coldTooltipEl.classList.remove('open');
  }

  function showColdTooltip(card) {
    const index = Number(card?.dataset?.coldIndex);
    const character = lastState?.characters?.[index];
    if (!character) return;
    const tooltip = ensureColdTooltip();
    const payload = coldTooltip(character);
    tooltip.innerHTML = `
      <div class="mod-cold-tooltip-title">${escHtml(payload.title)}</div>
      <div class="mod-cold-tooltip-label">Prompt</div>
      <pre>${escHtml(payload.prompt)}</pre>
      <div class="mod-cold-tooltip-label">UC</div>
      <pre>${escHtml(payload.uc)}</pre>
    `;
    tooltip.classList.add('open');
    const rect = card.getBoundingClientRect();
    const tipRect = tooltip.getBoundingClientRect();
    const gap = 10;
    const viewportWidth = document.documentElement.clientWidth || window.innerWidth;
    const viewportHeight = document.documentElement.clientHeight || window.innerHeight;
    let left = rect.left - tipRect.width - gap;
    if (left < gap) left = Math.min(rect.right + gap, viewportWidth - tipRect.width - gap);
    let top = Math.min(rect.top, viewportHeight - tipRect.height - gap);
    top = Math.max(gap, top);
    tooltip.style.left = `${Math.round(left)}px`;
    tooltip.style.top = `${Math.round(top)}px`;
  }

  function bindColdInteractions() {
    (coldPanelHost || moduleBody).querySelectorAll('.mod-cold-card').forEach(card => {
      card.addEventListener('mouseenter', () => showColdTooltip(card));
      card.addEventListener('mouseleave', hideColdTooltip);
      card.addEventListener('focusin', () => showColdTooltip(card));
      card.addEventListener('focusout', hideColdTooltip);
      card.addEventListener('contextmenu', event => {
        event.preventDefault();
        renameSlot(Number(card.dataset.coldIndex));
      });
    });
    moduleBody.querySelectorAll('.mod-char-block').forEach(block => {
      block.addEventListener('contextmenu', event => {
        event.preventDefault();
        renameSlot(Number(block.dataset.charIndex));
      });
    });
  }

  function addSlot() {
    flushCharacterEdits();
    setModuleParam('character', 'add_character', 'true');
  }

  function removeSlot(index) {
    flushCharacterEdits();
    setModuleParam('character', `remove_character_${index}`, 'true');
  }

  function refreshPreview() {
    flushCharacterEdits();
    setModuleParam('character', 'preview_refresh', 'true');
  }

  function setSlotState(index, state) {
    flushCharacterEdits();
    setModuleParam('character', `char_slot_state_${index}`, state);
  }

  function setColdSearch(value) {
    coldSearch = String(value || '');
    applyColdSearchFilter();
  }

  function toggleColdPanel() {
    coldPanelOpen = !coldPanelOpen;
    if (lastState) render(lastState);
  }

  function hideColdPanel() {
    coldPanelOpen = false;
    hideColdTooltip();
    if (coldPanelHost) coldPanelHost.innerHTML = '';
  }

  async function renameSlot(index) {
    const character = lastState?.characters?.[index];
    if (!character) return;
    const originalId = character.id;
    const current = String(character.custom_name || '').trim();
    hideColdTooltip();
    if (!showPromptDialog) return;
    const next = await showPromptDialog('표시 이름을 입력하세요. 비우면 프롬프트 요약을 사용합니다.', {
      title: `Cold Slot C${character.id}`,
      okText: 'Apply',
      cancelText: 'Cancel',
      defaultValue: current,
      placeholder: coldSummary(character),
    });
    if (next === null) return;
    const currentCharacter = lastState?.characters?.[index];
    if (!currentCharacter || currentCharacter.id !== originalId) return;
    setModuleParam('character', `char_slot_name_${index}`, next.trim());
  }

  function captureTextareaHeights() {
    const heights = {};
    moduleBody.querySelectorAll('.mod-char-block[data-char-index]').forEach(block => {
      const index = block.dataset.charIndex;
      const prompt = block.querySelector('.mod-char-prompt');
      const uc = block.querySelector('.mod-char-uc');
      if (prompt?.style?.height) heights[`prompt:${index}`] = prompt.style.height;
      if (uc?.style?.height) heights[`uc:${index}`] = uc.style.height;
    });
    return heights;
  }

  function restoreTextareaHeights(heights) {
    if (!heights) return;
    moduleBody.querySelectorAll('.mod-char-block[data-char-index]').forEach(block => {
      const index = block.dataset.charIndex;
      const prompt = block.querySelector('.mod-char-prompt');
      const uc = block.querySelector('.mod-char-uc');
      const promptHeight = heights[`prompt:${index}`];
      const ucHeight = heights[`uc:${index}`];
      if (prompt && promptHeight) prompt.style.height = promptHeight;
      if (uc && ucHeight) uc.style.height = ucHeight;
    });
  }

  function focusedCharacterTextarea() {
    const active = document.activeElement;
    if (!active || !moduleBody.contains(active)) return null;
    if (!active.classList?.contains('mod-char-prompt') && !active.classList?.contains('mod-char-uc')) return null;
    if (!active.closest?.('.mod-char-block[data-char-index]')) return null;
    return active;
  }

  function characterStructureSignature(state) {
    const chars = Array.isArray(state?.characters) ? state.characters : [];
    return JSON.stringify({
      activated: !!state?.activated,
      reroll_on_generate: !!state?.reroll_on_generate,
      characters: chars.map(character => [
        character?.id,
        slotState(character),
        !!character?.active,
        character?.custom_name || '',
      ]),
    });
  }

  function clearDeferredFocusedRender() {
    if (deferredFocusTarget) {
      deferredFocusTarget.removeEventListener('blur', flushDeferredFocusedRender);
    }
    deferredFocusTarget = null;
    deferredFocusedRenderState = null;
  }

  function queueDeferredFocusedRender(textarea, state) {
    deferredFocusedRenderState = state;
    if (deferredFocusTarget === textarea) return;
    if (deferredFocusTarget) {
      deferredFocusTarget.removeEventListener('blur', flushDeferredFocusedRender);
    }
    deferredFocusTarget = textarea;
    textarea.addEventListener('blur', flushDeferredFocusedRender, {once: true});
  }

  function flushDeferredFocusedRender() {
    const pendingState = deferredFocusedRenderState;
    deferredFocusTarget = null;
    deferredFocusedRenderState = null;
    if (!pendingState) return;
    globalThis.setTimeout(() => {
      if (!focusedCharacterTextarea()) render(pendingState);
    }, 0);
  }

  /** 비활성 슬롯의 이름표. 프롬프트 앞 태그 2개면 보통 `girl, 캐릭터명` 이다.
   *  비활성은 번호를 갖지 않는다 - 번호는 활성 무리 안의 자리이고, 올라올 때 받는다. */
  function inactiveLabel(character) {
    const customName = String(character.custom_name || '').trim();
    if (customName) return escHtml(customName);
    const tags = firstPromptLine(character.prompt)
      .split(',').map(part => part.trim()).filter(Boolean);
    return tags.length ? escHtml(tags.slice(0, 2).join(', ')) : '<span class="mod-char-id-muted">(empty)</span>';
  }

  /**
   * @param ordinal  활성 슬롯이면 활성 무리 안의 1-based 번호(C1, C2...), 아니면 0.
   * @param lastActive  마지막 활성 슬롯인가 - 그러면 ▼ 를 내주지 않는다.
   *   "활성은 최소 하나" 는 여기(UI)에서만 세운다. 백엔드에 강제하면 활성 0을
   *   정상 상태로 쓰는 기존 경로 두 개가 깨진다(Cold 로 비우기 · 조건부 스킵 판정).
   */
  /** Connect 드롭다운. **자기보다 앞선 활성 슬롯만** 후보다(사용자 지정).
   *
   *  그 제약이 곧 안전장치다 - 백엔드 전개 루프가 활성 프레임을 화면 순서대로 한 번
   *  훑으므로, 앞만 가리키면 참조 시점에 값이 이미 확정돼 있고 순환이 생길 수 없다.
   *  값은 표시 번호가 아니라 **slot_uuid** 다 - 번호는 ▲▼·비활성화로 밀린다.
   *  C1 은 앞이 없으므로 아예 그리지 않는다. */
  function connectControl(character, index, ordinal, activeSlots) {
    if (!character.active || ordinal <= 1) return '';
    const current = String(character.connect_to || '');
    const options = activeSlots.slice(0, ordinal - 1).map((item, i) => {
      const uuid = String(item.character.slot_uuid || '');
      const name = String(item.character.custom_name || '').trim();
      const text = name ? `C${i + 1} · ${name}` : `C${i + 1}`;
      return `<option value="${escAttr(uuid)}"${uuid === current ? ' selected' : ''}>${escHtml(text)}</option>`;
    }).join('');
    const on = !!current;
    return `<label class="mod-char-connect${on ? ' is-on' : ''}"`
      + ` data-naia-guide="Connect - 앞선 슬롯의 캐릭터를 그대로 물려받습니다.\\n와일드카드도 같은 값이 옵니다.\\n연결 중에는 아래 두 칸이 '추가할' 칸이 됩니다.">`
      + `<span class="mod-char-connect-tag">${on ? '&#128279;' : 'Connect'}</span>`
      + `<select onchange="setModuleParam('character','char_connect_${index}',this.value)">`
      + `<option value=""${on ? '' : ' selected'}>연결 없음</option>${options}</select></label>`;
  }

  function renderWorkingSlot(character, index, totalCount, ordinal, lastActive, activeSlots) {
    const active = !!character.active;
    const customName = String(character.custom_name || '').trim();
    const label = active
      ? (customName
          ? `${escHtml(customName)} <span class="mod-char-id-muted">C${ordinal}</span>`
          : `C${ordinal}`)
      : inactiveLabel(character);
    const moveBtn = active
      ? (lastActive
          ? ''
          : `<button class="mod-btn-square" aria-label="Deactivate" data-naia-title="비활성으로 내린다" onclick="setCharacterSlotState(${index}, 'inactive')">&#9660;</button>`)
      : `<button class="mod-btn-square mod-char-promote" aria-label="Activate" data-naia-title="활성 맨 아래로 올린다" onclick="setCharacterSlotState(${index}, 'active')">&#9650;</button>`;
    // ✔/✘ - **제자리에서** 끈다(NAI 공식 구현과 같다). 끈 슬롯은 활성 무리에
    // 그대로 남아 번호(C3)도 유지하고, 페이로드에서만 빠진다.
    // ⚠️ ▼(비활성으로 내림)와 **다른 축**이다. 그쪽은 목록에서 치우고 번호를
    //    다시 매긴다. 예전에는 축이 하나라 체크박스가 곧 ▼ 였고, 무리를 나누며
    //    체크박스를 걷어내자 제자리에서 끌 방법이 사라졌다(사용자 제보).
    // 연결 중이면 두 칸의 뜻이 바뀐다 - 대체가 아니라 **덧붙이기**다(사용자 지정).
    const connected = active && !!String(character.connect_to || '');
    const muted = !!character.muted;
    const enableBox = active
      ? `<label class="mod-char-en" data-naia-title="${muted ? '이 슬롯을 켠다' : '이 슬롯을 끈다 (자리는 그대로)'}">`
        + `<input type="checkbox" ${muted ? '' : 'checked'}`
        + ` oninput="setModuleParam('character','char_muted_${index}',String(!this.checked))"></label>`
      : '';
    return `
      <div class="mod-char-block ${active ? 'is-active' : 'is-inactive'}${muted ? ' is-muted' : ''}${connected ? ' is-connected' : ''}" data-char-index="${index}" data-slot-uuid="${escAttr(character.slot_uuid || '')}">
        <div class="mod-char-header">
          ${enableBox}
          <span class="mod-char-title">${label}</span>
          <div class="mod-char-card-actions">
            ${connectControl(character, index, ordinal, activeSlots || [])}
            ${moveBtn}
            <button class="mod-btn-square" aria-label="Move to Cold" data-naia-title="Cold 보관함으로" onclick="setCharacterSlotState(${index}, 'cold')">-</button>
            <button class="mod-btn-sm mod-btn-danger" ${totalCount > 1 ? '' : 'disabled'} onclick="removeCharacterSlot(${index})">Remove</button>
          </div>
        </div>
        <textarea class="mod-textarea mod-char-prompt" placeholder="${connected ? '추가할 캐릭터 프롬프트...' : 'character prompt...'}" oninput="onModTextEdit('character','char_prompt_${index}',this.value)">${escHtml(character.prompt)}</textarea>
        <textarea class="mod-textarea mod-uc mod-char-uc" placeholder="${connected ? '추가할 캐릭터 네거티브...' : 'negative prompt (UC)...'}" oninput="onModTextEdit('character','char_uc_${index}',this.value)">${escHtml(character.uc)}</textarea>
      </div>
    `;
  }

  function renderColdSlot(character, index, totalCount) {
    const summary = coldSummary(character);
    const searchText = coldSearchText(character, index);
    const hasCustomName = Boolean(String(character.custom_name || '').trim());
    return `
      <article class="mod-cold-card" tabindex="0" data-cold-index="${index}" data-slot-uuid="${escAttr(character.slot_uuid || '')}" data-cold-search="${escAttr(searchText)}">
        <span class="mod-cold-id">C${character.id}</span>
        <div class="mod-cold-summary ${hasCustomName ? 'custom' : ''}">${escHtml(summary)}</div>
        <div class="mod-cold-actions">
          <button class="mod-btn-square" aria-label="Restore to Active/Inactive" onclick="setCharacterSlotState(${index}, 'restore')">+</button>
          <button class="mod-btn-square danger" aria-label="Remove" ${totalCount > 1 ? '' : 'disabled'} onclick="removeCharacterSlot(${index})">x</button>
        </div>
      </article>
    `;
  }

  function renderColdPanel(coldSlots, totalCount) {
    const host = ensureColdPanelHost();
    const coldHtml = [
      `<div class="mod-empty mod-cold-empty" ${coldSlots.length ? 'hidden' : ''}>No Cold slots match.</div>`,
      coldSlots.map(({character, index}) => renderColdSlot(character, index, totalCount)).join(''),
    ].join('');
    host.innerHTML = `
      <aside class="mod-character-cold-panel ${coldPanelOpen ? 'open' : ''}">
        <div class="mod-cold-header">
          <div>
            <div class="mod-section-label">Cold</div>
            <div class="mod-char-meta" data-cold-count>${coldSlots.length} / ${coldSlots.length} stored</div>
          </div>
          <button class="module-popup-icon-btn" aria-label="Close Cold panel" onclick="toggleCharacterColdPanel()">x</button>
        </div>
        <input class="mod-cold-search" type="search" value="${escAttr(coldSearch)}" placeholder="Search cold slots..." oninput="setCharacterColdSearch(this.value)">
        <div class="mod-cold-stack">
          ${coldHtml}
        </div>
      </aside>
    `;
    positionColdPanel();
  }

  function render(state) {
    hideColdTooltip();
    const nextState = state || {};
    const structureSignature = characterStructureSignature(nextState);
    const focusedTextarea = focusedCharacterTextarea();
    if (focusedTextarea && lastRenderedStructureSignature === structureSignature) {
      // Server echo for local text edits must not replace the focused textarea;
      // replacing it collapses tag autocomplete before the user can choose.
      lastState = nextState;
      queueDeferredFocusedRender(focusedTextarea, nextState);
      return;
    }
    clearDeferredFocusedRender();
    const textareaHeights = captureTextareaHeights();
    lastState = nextState;
    const chars = nextState.characters || [];
    const workingSlots = chars
      .map((character, index) => ({character, index}))
      .filter(item => slotState(item.character) !== 'cold');
    const coldSlots = chars
      .map((character, index) => ({character, index}))
      .filter(item => slotState(item.character) === 'cold');
    // 화면은 활성/비활성 두 무리다. 배열은 백엔드에서 [active][inactive][cold] 로
    // 정렬돼 오므로(core/character_settings.sort_character_frames) 여기서 다시
    // 순서를 만들지 않는다 - 만들면 index 주소가 저장 순서와 어긋난다.
    const activeSlots = workingSlots.filter(item => item.character.active);
    const inactiveSlots = workingSlots.filter(item => !item.character.active);
    const addBtn = `
      <button class="mod-char-add" onclick="addCharacterSlot()">+ Add Character</button>`;
    const charsHtml = workingSlots.length
      ? [
          activeSlots.map(({character, index}, i) =>
            renderWorkingSlot(character, index, chars.length, i + 1, activeSlots.length <= 1, activeSlots)).join(''),
          addBtn,
          inactiveSlots.length
            ? `<div class="mod-section-label mod-char-group-label">비활성 (${inactiveSlots.length})</div>`
            : '',
          inactiveSlots.map(({character, index}) =>
            renderWorkingSlot(character, index, chars.length, 0, false)).join(''),
        ].join('')
      : `<div class="mod-empty">No active or inactive slots. Restore a Cold slot or add one.</div>${addBtn}`;
    renderColdPanel(coldSlots, chars.length);
    const previewText = nextState.processed_preview_text || '';
    const previewEmpty = !previewText.trim();

    moduleBody.innerHTML = `
      <div class="mod-character-shell">
        <section class="mod-character-workspace">
          <div>
            <label class="mod-checkbox-item">
              <input type="checkbox" ${nextState.activated ? 'checked' : ''} oninput="setModuleParam('character','activated',String(this.checked))">
              <span class="mod-checkbox-label">캐릭터 프롬프트를 활성화 합니다 (NAID4 이상)</span>
            </label>
          </div>
          <div>
            <label class="mod-checkbox-item">
              <input type="checkbox" ${nextState.reroll_on_generate ? 'checked' : ''} oninput="setModuleParam('character','reroll_on_generate',String(this.checked))">
              <span class="mod-checkbox-label">Generate 버튼을 누를 때 캐릭터 와일드카드 재굴림</span>
            </label>
          </div>
          <div class="mod-char-actions">
            <button class="mod-btn-sm mod-btn-encode" onclick="refreshCharacterPreview()">Refresh Preview</button>
            <button class="mod-btn-sm mod-cold-toggle ${coldPanelOpen ? 'active' : ''}" onclick="toggleCharacterColdPanel()">Cold (${coldSlots.length})</button>
            <button class="mod-btn-sm mod-btn-assets" title="캐릭터 에셋 라이브러리 (이미지 기반 영구 보관함)" onclick="openCharacterAssetTab()">Assets</button>
            <span class="mod-char-meta">${nextState.active_count || 0} active / ${workingSlots.length} work / ${coldSlots.length} cold</span>
          </div>
          ${charsHtml}
          <div class="mod-char-preview">
            <div class="mod-section-label">Final Applied Character Prompt</div>
            ${previewEmpty
              ? '<div class="mod-empty">No preview yet. Use Refresh Preview to process wildcards and show the applied character prompts.</div>'
              : `<pre class="mod-char-preview-text">${escHtml(previewText)}</pre>`}
          </div>
        </section>
      </div>
    `;
    moduleBody.querySelectorAll('.mod-textarea:not(.mod-uc)').forEach(element => bindTagAssist(element));
    restoreTextareaHeights(textareaHeights);
    applyColdSearchFilter();
    bindColdInteractions();
    lastRenderedStructureSignature = structureSignature;
  }

  return {
    addSlot,
    removeSlot,
    refreshPreview,
    setSlotState,
    toggleColdPanel,
    hideColdPanel,
    renameSlot,
    setColdSearch,
    render,
  };
}
