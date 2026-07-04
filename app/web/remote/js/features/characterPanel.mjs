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

  function renderWorkingSlot(character, index, totalCount) {
    const customName = String(character.custom_name || '').trim();
    const label = customName ? `${escHtml(customName)} <span class="mod-char-id-muted">C${character.id}</span>` : `C${character.id}`;
    return `
      <div class="mod-char-block" data-char-index="${index}" data-slot-uuid="${escAttr(character.slot_uuid || '')}">
        <div class="mod-char-header">
          <label class="mod-checkbox-item" style="margin:0">
            <input type="checkbox" ${character.active ? 'checked' : ''} oninput="setModuleParam('character','char_active_${index}',String(this.checked))">
            <span class="mod-checkbox-label">${label}</span>
          </label>
          <div class="mod-char-card-actions">
            <button class="mod-btn-square" aria-label="Move to Cold" onclick="setCharacterSlotState(${index}, 'cold')">-</button>
            <button class="mod-btn-sm mod-btn-danger" ${totalCount > 1 ? '' : 'disabled'} onclick="removeCharacterSlot(${index})">Remove</button>
          </div>
        </div>
        <textarea class="mod-textarea mod-char-prompt" placeholder="character prompt..." oninput="onModTextEdit('character','char_prompt_${index}',this.value)">${escHtml(character.prompt)}</textarea>
        <textarea class="mod-textarea mod-uc mod-char-uc" placeholder="negative prompt (UC)..." oninput="onModTextEdit('character','char_uc_${index}',this.value)">${escHtml(character.uc)}</textarea>
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
    const charsHtml = workingSlots.length
      ? workingSlots.map(({character, index}) => renderWorkingSlot(character, index, chars.length)).join('')
      : '<div class="mod-empty">No active or inactive slots. Use + Add Character or restore a Cold slot.</div>';
    renderColdPanel(coldSlots, chars.length);
    const previewText = nextState.processed_preview_text || '';
    const previewEmpty = !previewText.trim();

    moduleBody.innerHTML = `
      <div class="mod-character-shell">
        <section class="mod-character-workspace">
          <div>
            <label class="mod-checkbox-item">
              <input type="checkbox" ${nextState.activated ? 'checked' : ''} oninput="setModuleParam('character','activated',String(this.checked))">
              <span class="mod-checkbox-label">Enable Character Prompts (NAID4+)</span>
            </label>
          </div>
          <div>
            <label class="mod-checkbox-item">
              <input type="checkbox" ${nextState.reroll_on_generate ? 'checked' : ''} oninput="setModuleParam('character','reroll_on_generate',String(this.checked))">
              <span class="mod-checkbox-label">Process wildcards on Generate</span>
            </label>
          </div>
          <div class="mod-char-actions">
            <button class="mod-btn-sm" onclick="addCharacterSlot()">+ Add Character</button>
            <button class="mod-btn-sm mod-btn-encode" onclick="refreshCharacterPreview()">Refresh Preview</button>
            <button class="mod-btn-sm mod-cold-toggle ${coldPanelOpen ? 'active' : ''}" onclick="toggleCharacterColdPanel()">Cold (${coldSlots.length})</button>
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
