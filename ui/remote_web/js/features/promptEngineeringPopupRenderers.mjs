export function createPromptEngineeringPopupRenderers({
  document,
  requestAnimationFrame,
  escHtml,
  getSharedMode,
  createPromptPreset,
  bindDanbooruFeedback,
  panels,
}) {
  function getBody(panel) {
    return panel ? panel.querySelector('.pe-popup-body') : null;
  }

  function renderPresetAdd(m) {
    const body = getBody(panels.presetAdd);
    if (!body) return;
    body.innerHTML = `
    <div class="mod-section-label">Current Preset</div>
    <div class="mod-info-chip">${escHtml(m.preset || '(none)')}</div>
    <label class="mod-field">
      <span class="mod-field-label">New Preset Name</span>
      <input class="mod-input" id="modPresetNewName" placeholder="new preset name" autocomplete="off" spellcheck="false">
    </label>
    <div class="mod-inline-row">
      <button class="mod-btn-secondary" onclick="createPromptPreset()">Save As</button>
      <button class="mod-btn-secondary" onclick="closePePresetAddPanel()">Close</button>
    </div>
  `;
    const input = document.getElementById('modPresetNewName');
    if (input) {
      input.addEventListener('keydown', (event) => {
        if (event.key === 'Enter') {
          event.preventDefault();
          createPromptPreset();
        }
      });
      requestAnimationFrame(() => input.focus());
    }
  }

  function renderPresetManage(m) {
    const body = getBody(panels.presetManage);
    if (!body) return;
    const sharedMode = getSharedMode();
    const canSaveCurrent = !!m.preset_can_save_current && !sharedMode;
    const canDeleteCurrent = !!m.preset_can_delete && !sharedMode;
    body.innerHTML = `
    <div class="mod-section-label">Current Preset</div>
    <div class="mod-info-chip">${escHtml(m.preset || '(none)')}</div>
    <div class="mod-inline-row">
      <button class="mod-btn-secondary" ${canSaveCurrent ? '' : 'disabled'} onclick="saveCurrentPromptPreset()">Save Current</button>
      <button class="mod-btn-danger" ${canDeleteCurrent ? '' : 'disabled'} onclick="deleteCurrentPromptPreset()">Delete Current</button>
    </div>
  `;
  }

  function renderDebugSnapshot(snapshot) {
    const sourceInfo = snapshot.source_info || {};
    const filterLog = Array.isArray(snapshot.filter_log) ? snapshot.filter_log : [];
    const implicationInfo = Array.isArray(snapshot.implication_info) ? snapshot.implication_info : [];
    const e621Info = snapshot.e621_info || {};
    const originalCount = Number(snapshot.original_count || 0);
    const remainingCount = Number(snapshot.remaining_count || 0);
    const hasDebugData = filterLog.length || implicationInfo.length || (e621Info.results || []).length || Object.values(sourceInfo).some(Boolean);

    if (!hasDebugData) {
      return '<div class="mod-debug-empty">No debug data yet. Generate a prompt once.</div>';
    }

    const sourceRows = Object.entries(sourceInfo)
      .filter(([, value]) => value != null && String(value).trim() !== '')
      .map(([key, value]) => `<div class="mod-debug-meta"><span>${escHtml(key)}</span><strong>${escHtml(String(value))}</strong></div>`)
      .join('');

    const filterRounds = filterLog.map(entry => {
      const removed = Array.isArray(entry.removed) ? entry.removed : [];
      const status = !entry.enabled ? 'OFF' : (removed.length ? `ON · ${removed.length} removed` : 'ON');
      return `
      <div class="mod-debug-round">
        <div class="mod-debug-round-title">${escHtml(entry.name || 'Round')} <span>${status}</span></div>
        ${removed.length ? `<pre class="mod-debug-block">${escHtml(removed.join(', '))}</pre>` : ''}
      </div>
    `;
    }).join('');

    const implicationHtml = implicationInfo.length
      ? `
      <div class="mod-debug-round">
        <div class="mod-debug-round-title">Tag Implication <span>${implicationInfo.length} removed</span></div>
        <pre class="mod-debug-block">${escHtml(implicationInfo.map(item => `${item.removed} <- ${item.by}`).join('\n'))}</pre>
      </div>
    `
      : '';

    const e621Results = Array.isArray(e621Info.results) ? e621Info.results : [];
    const e621Html = e621Results.length
      ? `
      <div class="mod-debug-round">
        <div class="mod-debug-round-title">e621 Auto-Boost <span>${e621Results.length} suggested</span></div>
        <pre class="mod-debug-block">${escHtml(`input: ${(e621Info.input_tags || []).join(', ')}`)}</pre>
        <pre class="mod-debug-block">${escHtml(e621Results.map(item => `${item.tag} (${Number(item.score || 0).toFixed(4)}) [${item.cat || ''}] <- ${item.src || ''}`).join('\n'))}</pre>
      </div>
    `
      : '';

    return `
    ${sourceRows ? `<div class="mod-debug-meta-grid">${sourceRows}</div>` : ''}
    <div class="mod-debug-summary">Original ${originalCount} → Remaining ${remainingCount} · Removed ${Math.max(0, originalCount - remainingCount)}</div>
    ${filterRounds}
    ${implicationHtml}
    ${e621Html}
  `;
  }

  function renderE621(m) {
    const body = getBody(panels.e621);
    if (!body) return;
    const e621 = m.e621_settings || {};
    const e621Hidden = Array.isArray(e621.hidden_tags) ? e621.hidden_tags.join(', ') : '';
    body.innerHTML = `
    <div class="mod-section-label">Weight / Mode</div>
    <div class="mod-inline-row">
      <input class="mod-input" id="modE621Weight" type="number" min="-5" max="5" step="0.05" value="${escHtml(String(e621.weight ?? 0))}" placeholder="weight">
      <select class="mod-select" id="modE621Mode">
        <option value="stable"${e621.mode === 'stable' || !e621.mode ? ' selected' : ''}>stable</option>
        <option value="confused"${e621.mode === 'confused' ? ' selected' : ''}>confused</option>
      </select>
    </div>
    <div>
      <div class="mod-section-label">Hidden Tags</div>
      <textarea class="mod-textarea" id="modE621HiddenTags" placeholder="comma or newline separated tags">${escHtml(e621Hidden)}</textarea>
    </div>
    <div class="mod-inline-row">
      <button class="mod-btn-secondary" onclick="savePromptEngineeringE621Settings()">Save e621 Settings</button>
    </div>
  `;
  }

  function renderDanbooru(m) {
    const body = getBody(panels.danbooru);
    if (!body) return;
    const danbooru = m.danbooru_settings || {};
    body.innerHTML = `
    <div id="modDanFeedback"></div>
    <div class="mod-grid-2">
      <label class="mod-field">
        <span class="mod-field-label">Magnitude</span>
        <input class="mod-input" id="modDanMagnitude" type="number" min="1" max="10" step="1" value="${escHtml(String(danbooru.magnitude ?? 3))}">
      </label>
      <label class="mod-field">
        <span class="mod-field-label">Rating Blend</span>
        <input class="mod-input" id="modDanBlend" type="number" min="0" max="1" step="0.1" value="${escHtml(String(danbooru.rating_blend ?? 0.3))}">
      </label>
    </div>
    <label class="mod-checkbox-item">
      <input type="checkbox" id="modDanOverrideOn" ${danbooru.override_on ? 'checked' : ''}>
      <span class="mod-checkbox-label">Custom Override</span>
    </label>
    <div class="mod-grid-3">
      <label class="mod-field">
        <span class="mod-field-label">Scale</span>
        <input class="mod-input" id="modDanOverrideScale" type="number" min="0" max="5" step="0.05" value="${escHtml(String(danbooru.override_scale ?? 0.35))}">
      </label>
      <label class="mod-field">
        <span class="mod-field-label">Min</span>
        <input class="mod-input" id="modDanOverrideMin" type="number" min="0" max="5" step="0.05" value="${escHtml(String(danbooru.override_min ?? 0.8))}">
      </label>
      <label class="mod-field">
        <span class="mod-field-label">Max</span>
        <input class="mod-input" id="modDanOverrideMax" type="number" min="0" max="10" step="0.05" value="${escHtml(String(danbooru.override_max ?? 1.35))}">
      </label>
    </div>
    <label class="mod-checkbox-item">
      <input type="checkbox" id="modDanRatingOverrideOn" ${danbooru.rating_override_on ? 'checked' : ''}>
      <span class="mod-checkbox-label">Rating Override</span>
    </label>
    <div class="mod-inline-row">
      <select class="mod-select" id="modDanRatingOverride">
        <option value="g"${danbooru.rating_override === 'g' ? ' selected' : ''}>General</option>
        <option value="s"${danbooru.rating_override === 's' || !danbooru.rating_override ? ' selected' : ''}>Sensitive</option>
        <option value="q"${danbooru.rating_override === 'q' ? ' selected' : ''}>Questionable</option>
        <option value="e"${danbooru.rating_override === 'e' ? ' selected' : ''}>Explicit</option>
      </select>
    </div>
    <label class="mod-checkbox-item">
      <input type="checkbox" id="modDanInvertWeight" ${danbooru.invert_weight ? 'checked' : ''}>
      <span class="mod-checkbox-label">Invert Weight</span>
    </label>
    <div class="mod-inline-row">
      <button class="mod-btn-secondary" onclick="savePromptEngineeringDanbooruSettings()">Save Danbooru Settings</button>
    </div>
  `;
    bindDanbooruFeedback(danbooru);
  }

  function renderDebugPanel(m) {
    const body = getBody(panels.debug);
    if (!body) return;
    body.innerHTML = `
    <div class="mod-inline-row">
      <button class="mod-btn-secondary" onclick="refreshPromptEngineeringDebug()">Refresh Debug</button>
    </div>
    ${renderDebugSnapshot(m.debug_snapshot || {})}
  `;
  }

  return {
    renderPresetAdd,
    renderPresetManage,
    renderDebugSnapshot,
    renderE621,
    renderDanbooru,
    renderDebugPanel,
  };
}
