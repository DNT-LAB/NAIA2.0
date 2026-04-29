const PP_OPTIONS = [
  ['remove_author', 'Remove Artist'],
  ['remove_work_title', 'Remove Work Title'],
  ['remove_character_name', 'Remove Character Name'],
  ['remove_character_features', 'Remove Char Features'],
  ['remove_clothes', 'Remove Clothing'],
  ['remove_color', 'Remove Color Tags'],
  ['remove_location_and_background_color', 'Remove Location/BG'],
  ['remove_expression', 'Remove Expression'],
  ['remove_pose_action', 'Remove Pose/Action'],
  ['remove_meta_tags', 'Remove Meta Tags'],
  ['remove_object_tags', 'Remove Object Tags'],
  ['remove_noise_tags', 'Remove Low-freq Tags'],
  ['e621_auto_boost', 'e621 Auto-Boost'],
  ['danbooru_auto_weight', 'Danbooru Auto-Weight'],
  ['tag_implication_compression', 'Tag Implication'],
];

const PP_OPTION_TONES = {
  remove_author: 'pe-tone-yellow',
  remove_work_title: 'pe-tone-yellow',
  remove_character_name: 'pe-tone-yellow',
  e621_auto_boost: 'pe-tone-pink',
  danbooru_auto_weight: 'pe-tone-teal',
  tag_implication_compression: 'pe-tone-teal',
};

const PE_EDITABLE_IDS = ['modPrePrompt', 'modPostPrompt', 'modAutoHide'];

export function createPromptEngineeringPanel({
  document,
  moduleBody,
  escHtml,
  bindTagAssist,
}) {
  function captureFocus() {
    const active = document.activeElement;
    if (!active || !PE_EDITABLE_IDS.includes(active.id)) return null;
    return {
      id: active.id,
      value: active.value,
      selectionStart: active.selectionStart,
      selectionEnd: active.selectionEnd,
      scrollTop: active.scrollTop,
    };
  }

  function restoreFocus(snap) {
    if (!snap) return;
    const el = document.getElementById(snap.id);
    if (!el) return;
    el.value = snap.value;
    el.scrollTop = snap.scrollTop;
    try { el.focus({ preventScroll: true }); } catch (e) { el.focus(); }
    try { el.setSelectionRange(snap.selectionStart, snap.selectionEnd); } catch (e) {}
  }

  function render(m) {
    const focusSnap = captureFocus();

    const presetOpts = (m.preset_options || [])
      .map(preset => `<option value="${preset}"${preset === m.preset ? ' selected' : ''}>${preset}</option>`)
      .join('');

    const preprocessing = m.preprocessing || {};
    const preprocessingHtml = PP_OPTIONS.map(([key, label]) =>
      `<label class="mod-checkbox-item ${PP_OPTION_TONES[key] || ''}">
      <input type="checkbox" ${preprocessing[key] ? 'checked' : ''} oninput="setPromptEngineeringOption('${key}', this.checked)">
      <span class="mod-checkbox-label">${label}</span>
    </label>`
    ).join('');

    const presetControlHtml = `
    <div>
      <div class="mod-section-label">Quick Preset</div>
      <div class="mod-preset-toolbar">
        <select class="mod-select mod-preset-select" id="modPreset" onchange="onPromptPresetChange(this.value)">${presetOpts}</select>
        <button class="mod-btn-secondary mod-btn-compact" onclick="openPePresetAddPanel()">Add</button>
        <button class="mod-btn-secondary mod-btn-compact" onclick="openPePresetManagePanel()">Manage</button>
      </div>
    </div>
  `;

    const advancedHtml = `
    <div>
      <div class="mod-section-label">Tools</div>
      <div class="mod-inline-row">
        <button class="mod-btn-secondary" onclick="openPeE621Panel()">e621 Auto-Boost Settings</button>
        <button class="mod-btn-secondary" onclick="openPeDanbooruPanel()">Danbooru Auto-Weight Settings</button>
      </div>
      <div class="mod-inline-row">
        <button class="mod-btn-secondary" onclick="openPeDebugPanel()">Debug Snapshot</button>
      </div>
    </div>
  `;

    moduleBody.innerHTML = `
    ${presetControlHtml}
    <div>
      <div class="mod-section-label">Prefix Prompt</div>
      <textarea class="mod-textarea mod-textarea-lg" id="modPrePrompt" placeholder="prefix tags..." oninput="onModTextEdit('prompt_engineering','pre_prompt',this.value)">${escHtml(m.pre_prompt)}</textarea>
    </div>
    <div>
      <div class="mod-section-label">Postfix Prompt</div>
      <textarea class="mod-textarea mod-textarea-lg" id="modPostPrompt" placeholder="postfix tags..." oninput="onModTextEdit('prompt_engineering','post_prompt',this.value)">${escHtml(m.post_prompt)}</textarea>
    </div>
    <div>
      <div class="mod-section-label mod-collapsible" onclick="this.classList.toggle('open');this.nextElementSibling.classList.toggle('collapsed')">Auto-Hide (Filter) <span class="mod-collapse-arrow">▶</span></div>
      <textarea class="mod-textarea collapsed" id="modAutoHide" placeholder="tags to filter out..." oninput="onModTextEdit('prompt_engineering','auto_hide',this.value)">${escHtml(m.auto_hide)}</textarea>
    </div>
    <div>
      <div class="mod-section-label">Preprocessing Options</div>
      <div class="mod-checkbox-grid">${preprocessingHtml}</div>
    </div>
    ${advancedHtml}
  `;

    ['modPrePrompt', 'modPostPrompt'].forEach(id => {
      const el = document.getElementById(id);
      if (el) bindTagAssist(el);
    });
    restoreFocus(focusSnap);
  }

  return {
    render,
  };
}
