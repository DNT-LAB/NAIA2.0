const PP_OPTIONS = [
  ['remove_author', 'Remove Artist'],
  ['remove_work_title', 'Remove Work Title'],
  ['remove_character_name', 'Remove Character Name'],
  ['remove_character_features', 'Remove Char Features'],
  ['remove_clothes', 'Remove Clothing'],
  ['remove_clothing_event', 'Remove Clothing Events'],
  ['remove_color', 'Remove Color Tags'],
  ['remove_location_and_background_color', 'Remove Location/BG'],
  ['remove_expression', 'Remove Expression'],
  ['remove_pose_action', 'Remove Pose/Action'],
  ['remove_meta_tags', 'Remove Meta Tags'],
  ['remove_object_tags', 'Remove Object Tags'],
  ['remove_noise_tags', 'Remove Low-freq Tags'],
  ['closed_eyes_sync', 'Closed Eyes Sync'],
  ['e621_auto_boost', 'e621 Auto-Boost'],
  ['danbooru_auto_weight', 'Danbooru Auto-Weight'],
  ['tag_implication_compression', 'Tag Implication'],
];

const PP_OPTION_TONES = {
  remove_author: 'pe-tone-yellow',
  remove_work_title: 'pe-tone-yellow',
  remove_character_name: 'pe-tone-yellow',
  closed_eyes_sync: 'pe-tone-pink',
  e621_auto_boost: 'pe-tone-pink',
  danbooru_auto_weight: 'pe-tone-teal',
  tag_implication_compression: 'pe-tone-teal',
};

const PE_EDITABLE_IDS = ['modPrePrompt', 'modPostPrompt', 'modAutoHide'];

function compactPreviewText(text, limit = 420) {
  const normalized = String(text || '').replace(/\s+/g, ' ').trim();
  if (!normalized) return '';
  return normalized.length > limit ? `${normalized.slice(0, Math.max(0, limit - 3))}...` : normalized;
}

function labelForPreprocessingKey(key) {
  return String(key || '')
    .replace(/^remove_/, 'Remove ')
    .replace(/_/g, ' ')
    .replace(/\b\w/g, char => char.toUpperCase());
}

function buildPreprocessingOptions(preprocessing) {
  const knownKeys = new Set(PP_OPTIONS.map(([key]) => key));
  const dynamicOptions = Object.keys(preprocessing || {})
    .filter(key => !knownKeys.has(key))
    .sort()
    .map(key => [key, labelForPreprocessingKey(key)]);
  return [...PP_OPTIONS, ...dynamicOptions];
}

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

  function captureTextareaHeights() {
    const heights = {};
    PE_EDITABLE_IDS.forEach(id => {
      const el = document.getElementById(id);
      if (el && el.style.height) heights[id] = el.style.height;
    });
    return heights;
  }

  function restoreTextareaHeights(heights) {
    if (!heights) return;
    Object.entries(heights).forEach(([id, height]) => {
      const el = document.getElementById(id);
      if (el && height) el.style.height = height;
    });
  }

  function render(m) {
    const focusSnap = captureFocus();
    // While the user is actively editing one of the prompt textareas, this
    // render is almost always the echo of their own keystrokes coming back as a
    // module_state broadcast (after the input debounce). Rebuilding innerHTML
    // here replaces the focused textarea node, which dismisses the open
    // autocomplete popup and drops focus mid-word — even though we restore both
    // afterward, the popup is already gone. The local DOM already holds the
    // edited value, so skip the destructive rebuild while a prompt textarea is
    // focused; the next render after blur reflects any real state change.
    if (focusSnap) return;
    const textareaHeights = captureTextareaHeights();
    const summaryMap = new Map();
    (m.preset_summaries || []).forEach(summary => {
      if (summary && summary.name) summaryMap.set(String(summary.name), summary);
    });

    const presetOpts = (m.preset_options || [])
      .map(preset => {
        const summary = summaryMap.get(String(preset));
        const title = summary ? compactPreviewText(summary.pre_prompt_preview, 180) : '';
        const previewAttrs = summary ? [
          `data-preview-name="${escHtml(summary.name || preset)}"`,
          `data-preview-mode="${escHtml(summary.api_mode || '')}"`,
          `data-preview-prefix="${escHtml(compactPreviewText(summary.pre_prompt_preview, 1200))}"`,
          `data-preview-description="${escHtml(compactPreviewText(summary.description, 300))}"`,
          `data-preview-thumbnail="${escHtml(summary.thumbnail_url || '')}"`,
        ].join(' ') : '';
        return `<option value="${escHtml(preset)}"${preset === m.preset ? ' selected' : ''}${title ? ` title="${escHtml(title)}"` : ''} ${previewAttrs}>${escHtml(preset)}</option>`;
      })
      .join('');

    const preprocessing = m.preprocessing || {};
    const preprocessingHtml = buildPreprocessingOptions(preprocessing).map(([key, label]) =>
      `<label class="mod-checkbox-item ${PP_OPTION_TONES[key] || ''}">
      <input type="checkbox" ${preprocessing[key] ? 'checked' : ''} oninput="setPromptEngineeringOption('${key}', this.checked)">
      <span class="mod-checkbox-label">${label}</span>
    </label>`
    ).join('');

    const presetControlHtml = `
    <div>
      <div class="mod-section-label">Quick Preset</div>
      <div class="mod-preset-toolbar">
        <select class="mod-select mod-preset-select" id="modPreset" data-preview-kind="prompt-preset" onchange="onPromptPresetChange(this.value)">${presetOpts}</select>
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
    <div class="pe-prompt-stack">
      <div class="pe-prompt-field">
        <div class="mod-section-label">Prefix Prompt</div>
        <textarea class="mod-textarea pe-textarea" id="modPrePrompt" placeholder="prefix tags..." oninput="onModTextEdit('prompt_engineering','pre_prompt',this.value)">${escHtml(m.pre_prompt)}</textarea>
      </div>
      <div class="pe-prompt-field">
        <div class="mod-section-label">Postfix Prompt</div>
        <textarea class="mod-textarea pe-textarea" id="modPostPrompt" placeholder="postfix tags..." oninput="onModTextEdit('prompt_engineering','post_prompt',this.value)">${escHtml(m.post_prompt)}</textarea>
      </div>
      <div class="pe-prompt-field">
        <div class="mod-section-label">Auto-Hide (Filter)</div>
        <textarea class="mod-textarea pe-textarea" id="modAutoHide" placeholder="tags to filter out..." oninput="onModTextEdit('prompt_engineering','auto_hide',this.value)">${escHtml(m.auto_hide)}</textarea>
      </div>
    </div>
    <div>
      <div class="mod-section-label">Preprocessing Options</div>
      <div class="mod-checkbox-grid">${preprocessingHtml}</div>
    </div>
    ${advancedHtml}
  `;

    PE_EDITABLE_IDS.forEach(id => {
      const el = document.getElementById(id);
      if (el) bindTagAssist(el);
    });
    restoreTextareaHeights(textareaHeights);
    restoreFocus(focusSnap);
  }

  return {
    render,
  };
}
