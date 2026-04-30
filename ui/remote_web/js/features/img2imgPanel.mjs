export function createImg2ImgPanel({
  document,
  moduleBody,
  escHtml,
  setModuleParam,
  onModTextEdit,
  flushPendingModuleEdit,
  showToast,
}) {
  function formatRatio(value, fallback = '0.00') {
    const number = Number(value);
    if (!Number.isFinite(number)) return fallback;
    return number.toFixed(2);
  }

  function renderCharacter(character, index) {
    return `
      <div class="mod-char-block mod-img2img-char" data-img2img-char-index="${index}">
        <div class="mod-char-header">
          <label class="mod-checkbox-item" style="margin:0">
            <input type="checkbox" ${character.active ? 'checked' : ''} oninput="img2imgSetCharacterActive(${index}, this.checked)">
            <span class="mod-checkbox-label">C${character.id || index + 1}</span>
          </label>
          <button type="button" class="mod-btn-sm mod-btn-danger" onclick="img2imgRemoveCharacter(${index})">Remove</button>
        </div>
        <textarea class="mod-textarea mod-char-prompt" placeholder="character prompt..." oninput="img2imgText('char_prompt_${index}', this.value)">${escHtml(character.prompt || '')}</textarea>
        <textarea class="mod-textarea mod-uc mod-char-uc" placeholder="negative prompt (UC)..." oninput="img2imgText('char_uc_${index}', this.value)">${escHtml(character.uc || '')}</textarea>
      </div>`;
  }

  function render(state) {
    if (!state || !state.active) {
      moduleBody.innerHTML = `
        <div class="mod-empty">
          No active Img2Img session. Use Result image context menu or image paste to send an image.
        </div>`;
      return;
    }

    const strength = Number.isFinite(Number(state.strength)) ? Number(state.strength) : 70;
    const noise = Number.isFinite(Number(state.noise)) ? Number(state.noise) : 0;
    const repeat = Number.isFinite(Number(state.repeat)) ? Number(state.repeat) : 1;
    const characters = Array.isArray(state.characters) ? state.characters : [];
    const preview = state.preview
      ? `<img class="mod-img2img-preview-img" src="${state.preview}" alt="">`
      : '<div class="mod-empty">No preview</div>';

    moduleBody.innerHTML = `
      <div class="mod-img2img">
        <div class="mod-img2img-head">
          <div class="mod-img2img-preview">${preview}</div>
          <div class="mod-img2img-summary">
            <div class="mod-section-label">Source</div>
            <div class="mod-info-chip">${escHtml(state.source_label || 'Result Image')}</div>
            <div class="mod-img2img-meta">${escHtml(state.mode || 'img2img')} · ${Number(state.width) || 0}×${Number(state.height) || 0}</div>
          </div>
        </div>

        <div class="mod-img2img-controls">
          <div class="mod-img2img-range">
            <label>Strength <strong id="img2imgStrengthValue">${formatRatio(state.strength_value)}</strong></label>
            <input type="range" min="1" max="99" value="${strength}" oninput="img2imgSlider('strength', this.value)">
          </div>
          <div class="mod-img2img-range">
            <label>Noise <strong id="img2imgNoiseValue">${formatRatio(state.noise_value)}</strong></label>
            <input type="range" min="0" max="99" value="${noise}" oninput="img2imgSlider('noise', this.value)">
          </div>
          <div class="mod-field mod-img2img-repeat">
            <label class="mod-field-label">Repeat</label>
            <input class="mod-input" type="number" min="1" max="99" value="${repeat}" oninput="img2imgRepeat(this.value)">
          </div>
        </div>

        <div>
          <div class="mod-section-label">Main Prompt</div>
          <textarea class="mod-textarea mod-textarea-lg" id="img2imgMainPrompt" oninput="img2imgText('main_prompt', this.value)">${escHtml(state.main_prompt || '')}</textarea>
        </div>
        <div>
          <div class="mod-section-label">Undesired Content</div>
          <textarea class="mod-textarea" id="img2imgNegativePrompt" oninput="img2imgText('negative_prompt', this.value)">${escHtml(state.negative_prompt || '')}</textarea>
        </div>

        <div class="mod-char-actions">
          <button type="button" class="mod-btn-sm" onclick="img2imgAddCharacter()">+ Add Character</button>
          <span class="mod-char-meta">${characters.length} character slots</span>
        </div>
        ${characters.map(renderCharacter).join('')}

        <div class="mod-img2img-actions">
          <button type="button" class="mod-action-btn mod-start" ${state.can_generate ? '' : 'disabled'} onclick="img2imgGenerate()">Generate</button>
          <button type="button" class="mod-btn-secondary" onclick="img2imgClose()">Close Session</button>
        </div>
      </div>`;
  }

  function slider(key, rawValue) {
    const raw = Math.max(key === 'strength' ? 1 : 0, Math.min(99, Math.round(Number(rawValue) || 0)));
    const label = document.getElementById(key === 'strength' ? 'img2imgStrengthValue' : 'img2imgNoiseValue');
    if (label) label.textContent = formatRatio(key === 'strength' && raw === 99 ? 1 : raw / 100);
    setModuleParam('img2img', key, String(raw));
  }

  function repeat(value) {
    const count = Math.max(1, Math.min(99, Math.round(Number(value) || 1)));
    setModuleParam('img2img', 'repeat', String(count));
  }

  function text(key, value) {
    onModTextEdit('img2img', key, value);
  }

  function addCharacter() {
    flushPendingModuleEdit('img2img');
    setModuleParam('img2img', 'add_character', 'true');
  }

  function removeCharacter(index) {
    flushPendingModuleEdit('img2img');
    setModuleParam('img2img', `remove_character_${index}`, 'true');
  }

  function setCharacterActive(index, checked) {
    setModuleParam('img2img', `char_active_${index}`, String(checked));
  }

  function generate() {
    flushPendingModuleEdit('img2img');
    setModuleParam('img2img', 'generate', 'true');
  }

  function close() {
    flushPendingModuleEdit('img2img');
    setModuleParam('img2img', 'close', 'true');
    showToast('Img2Img session closed', 'success');
  }

  return {
    render,
    slider,
    repeat,
    text,
    addCharacter,
    removeCharacter,
    setCharacterActive,
    generate,
    close,
  };
}
