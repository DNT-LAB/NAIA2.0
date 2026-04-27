export function createCharacterPanel({
  document,
  escHtml,
  bindTagAssist,
  flushCharacterEdits,
  setModuleParam,
}) {
  const moduleBody = document.getElementById('modulePopupBody');

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

  function render(state) {
    const chars = state.characters || [];
    const charsHtml = chars.map((character, index) => `
      <div class="mod-char-block" data-char-index="${index}">
        <div class="mod-char-header">
          <label class="mod-checkbox-item" style="margin:0">
            <input type="checkbox" ${character.active ? 'checked' : ''} oninput="setModuleParam('character','char_active_${index}',String(this.checked))">
            <span class="mod-checkbox-label">C${character.id}</span>
          </label>
          <button class="mod-btn-sm mod-btn-danger" ${chars.length > 1 ? '' : 'disabled'} onclick="removeCharacterSlot(${index})">Remove</button>
        </div>
        <textarea class="mod-textarea mod-char-prompt" placeholder="character prompt..." oninput="onModTextEdit('character','char_prompt_${index}',this.value)">${escHtml(character.prompt)}</textarea>
        <textarea class="mod-textarea mod-uc mod-char-uc" placeholder="negative prompt (UC)..." oninput="onModTextEdit('character','char_uc_${index}',this.value)">${escHtml(character.uc)}</textarea>
      </div>
    `).join('');
    const previewText = state.processed_preview_text || '';
    const previewEmpty = !previewText.trim();

    moduleBody.innerHTML = `
      <div>
        <label class="mod-checkbox-item">
          <input type="checkbox" ${state.activated ? 'checked' : ''} oninput="setModuleParam('character','activated',String(this.checked))">
          <span class="mod-checkbox-label">Enable Character Prompts (NAID4+)</span>
        </label>
      </div>
      <div>
        <label class="mod-checkbox-item">
          <input type="checkbox" ${state.reroll_on_generate ? 'checked' : ''} oninput="setModuleParam('character','reroll_on_generate',String(this.checked))">
          <span class="mod-checkbox-label">Process wildcards on Generate</span>
        </label>
      </div>
      <div class="mod-char-actions">
        <button class="mod-btn-sm" onclick="addCharacterSlot()">+ Add Character</button>
        <button class="mod-btn-sm mod-btn-encode" onclick="refreshCharacterPreview()">Refresh Preview</button>
        <span class="mod-char-meta">${state.active_count || 0} active / ${state.character_count || chars.length} slots</span>
      </div>
      ${charsHtml}
      <div class="mod-char-preview">
        <div class="mod-section-label">Final Applied Character Prompt</div>
        ${previewEmpty
          ? '<div class="mod-empty">No preview yet. Use Refresh Preview to process wildcards and show the applied character prompts.</div>'
          : `<pre class="mod-char-preview-text">${escHtml(previewText)}</pre>`}
      </div>
    `;
    moduleBody.querySelectorAll('.mod-textarea:not(.mod-uc)').forEach(element => bindTagAssist(element));
  }

  return {
    addSlot,
    removeSlot,
    refreshPreview,
    render,
  };
}
