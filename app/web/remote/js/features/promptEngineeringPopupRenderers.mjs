export function createPromptEngineeringPopupRenderers({
  document,
  requestAnimationFrame,
  escHtml,
  createPromptPreset,
  addRandomizedPreset,
  removeRandomizedPreset,
  switchRandomizedPreset,
  clearRandomizedPresets,
  setRandomizedWildcard,
  bindTagAssist,
  bindDanbooruFeedback,
  panels,
}) {
  const OLLAMA_BOOST_GUIDE =
    '자연어 가중치 — 보강된 자연어 프롬프트에 부여할 가중치입니다. '
    + 'NAI는 {v}::..:: , 로컬(WEBUI/COMFYUI)은 (..:v) 구문으로 적용됩니다.\\n\\n'
    + 'Effort — 보강 자연어의 길이·창의성. 간결(concise) / 표준(standard) / 풍부(rich).\\n\\n'
    + 'Input 구성 — Ollama에 보낼 입력에 PE Prefix / PE Postfix / e621 Auto-Boost 태그를 '
    + '포함할지 선택합니다.\\n\\n'
    + '⚠️ Prefix / Postfix는 **와일드카드 출력만** 반영됩니다. 고정 아티스트·퀄리티 태그'
    + '(예: 1.2::artist:.. ::, masterpiece, best quality)는 모델이 다루기 어렵고 의도와 '
    + '무관하므로 제외하고, __이름__ 와일드카드가 펼쳐진 결과만 입력에 넣습니다. '
    + '(포함 태그의 가중치 구문은 자동 제거.)';
  const OLLAMA_BOOST_EFFORTS = [
    ['concise', '간결'],
    ['standard', '표준'],
    ['rich', '풍부'],
  ];
  const RANDOMIZED_WC_GUIDE =
    '랜덤 프리셋(*randomized) 사용 시, 매 생성마다 뽑힌 프리셋의 선행 프롬프트(Prefix)에 '
    + '여기 입력을 함께 주입합니다.\\n\\n'
    + '고정 태그(예: artist:ciloranko, 1girl)는 그대로 항상 들어가고, 와일드카드(__character__)는 '
    + '매 생성 새로 추출됩니다. 둘을 섞어 써도 됩니다.\\n\\n'
    + '앞 = Prefix 앞(artist 류 권장), 뒤 = Prefix 뒤(character 류 권장). '
    + '(와일드카드는 구식 <...>가 아닌 __이름__ 형식)\\n\\n'
    + '체크를 끄면 주입하지 않으며, *randomized 프리셋에서만 동작합니다.';
  let randomizedPreview = null;
  let randomizedPreviewHideTimer = null;

  function compactPreviewText(text, limit = 420) {
    const normalized = String(text || '').replace(/\s+/g, ' ').trim();
    if (!normalized) return '';
    return normalized.length > limit ? `${normalized.slice(0, Math.max(0, limit - 3))}...` : normalized;
  }

  function presetSummaryMap(m) {
    const summaryMap = new Map();
    (m.preset_summaries || []).forEach(summary => {
      if (summary && summary.name) summaryMap.set(String(summary.name), summary);
    });
    return summaryMap;
  }

  function presetPreviewAttrs(preset, summaryMap) {
    const summary = summaryMap.get(String(preset));
    if (!summary) return '';
    return [
      `data-preview-name="${escHtml(summary.name || preset)}"`,
      `data-preview-mode="${escHtml(summary.api_mode || '')}"`,
      `data-preview-prefix="${escHtml(compactPreviewText(summary.pre_prompt_preview, 1200))}"`,
      `data-preview-description="${escHtml(compactPreviewText(summary.description, 300))}"`,
      `data-preview-thumbnail="${escHtml(summary.thumbnail_url || '')}"`,
    ].join(' ');
  }

  function cancelRandomizedPreviewHide() {
    if (randomizedPreviewHideTimer) {
      clearTimeout(randomizedPreviewHideTimer);
      randomizedPreviewHideTimer = null;
    }
  }

  function ensureRandomizedPreview() {
    if (randomizedPreview) return randomizedPreview;
    const preview = document.createElement('div');
    preview.className = 'custom-select-preview custom-select-preview-prompt-preset pe-randomized-preview';
    preview.hidden = true;
    preview.addEventListener('pointerenter', cancelRandomizedPreviewHide);
    preview.addEventListener('pointerleave', () => scheduleRandomizedPreviewHide());
    document.body.append(preview);
    randomizedPreview = preview;
    return preview;
  }

  function hideRandomizedPreview() {
    cancelRandomizedPreviewHide();
    if (!randomizedPreview) return;
    randomizedPreview.hidden = true;
    randomizedPreview.textContent = '';
  }

  function scheduleRandomizedPreviewHide() {
    cancelRandomizedPreviewHide();
    randomizedPreviewHideTimer = setTimeout(hideRandomizedPreview, 80);
  }

  function positionRandomizedPreview(anchor, preview) {
    const margin = 8;
    const rect = anchor.getBoundingClientRect();
    const viewportWidth = window.innerWidth || document.documentElement.clientWidth || 0;
    const viewportHeight = window.innerHeight || document.documentElement.clientHeight || 0;
    const width = Math.min(380, Math.max(260, viewportWidth - margin * 2));
    preview.style.width = `${width}px`;
    const previewHeight = Math.min(preview.offsetHeight || 0, viewportHeight - margin * 2);
    let left = rect.right + margin;
    if (left + width > viewportWidth - margin) left = rect.left - width - margin;
    if (left < margin) left = Math.max(margin, viewportWidth - width - margin);
    let top = rect.top;
    if (top + previewHeight > viewportHeight - margin) top = viewportHeight - previewHeight - margin;
    if (top < margin) top = margin;
    preview.style.left = `${Math.round(left)}px`;
    preview.style.top = `${Math.round(top)}px`;
  }

  function renderRandomizedPreview(anchor, preset, summaryMap) {
    const summary = summaryMap.get(String(preset)) || { name: preset };
    const preview = ensureRandomizedPreview();
    cancelRandomizedPreviewHide();
    preview.textContent = '';

    const thumb = document.createElement('div');
    thumb.className = 'custom-select-preview-thumb';
    const thumbnailUrl = summary.thumbnail_url || '';
    if (thumbnailUrl) {
      thumb.classList.add('has-image');
      const image = document.createElement('img');
      image.src = thumbnailUrl;
      image.alt = '';
      image.loading = 'lazy';
      image.decoding = 'async';
      const markImageRatio = () => {
        const isPortrait = image.naturalWidth > 0 && image.naturalHeight / image.naturalWidth >= 1.18;
        thumb.classList.toggle('is-portrait', isPortrait);
      };
      if (image.complete) markImageRatio();
      else image.addEventListener('load', markImageRatio, { once: true });
      thumb.append(image);
    } else {
      const empty = document.createElement('span');
      empty.textContent = 'No image';
      thumb.append(empty);
    }

    const copy = document.createElement('div');
    copy.className = 'custom-select-preview-copy';
    const head = document.createElement('div');
    head.className = 'custom-select-preview-head';
    const title = document.createElement('strong');
    title.textContent = summary.name || preset;
    head.append(title);
    if (summary.api_mode) {
      const mode = document.createElement('span');
      mode.textContent = summary.api_mode;
      head.append(mode);
    }
    copy.append(head);

    const description = compactPreviewText(summary.description, 300);
    if (description) {
      const desc = document.createElement('p');
      desc.className = 'custom-select-preview-desc';
      desc.textContent = description;
      copy.append(desc);
    }

    const prefix = document.createElement('pre');
    prefix.className = 'custom-select-preview-prefix';
    prefix.textContent = compactPreviewText(summary.pre_prompt_preview, 1200) || 'No prefix prompt';
    copy.append(prefix);

    preview.append(thumb, copy);
    preview.hidden = false;
    requestAnimationFrame(() => positionRandomizedPreview(anchor, preview));
  }

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
    const title = panels.presetManage?.querySelector('.module-popup-title');
    if (title) title.textContent = m.preset === '*randomized' ? 'Manage Randomized' : 'Manage Preset';

    if (m.preset === '*randomized') {
      renderRandomizedManage(body, m);
      return;
    }

    const canSaveCurrent = !!m.preset_can_save_current;
    const canDeleteCurrent = !!m.preset_can_delete;
    body.innerHTML = `
    <div class="mod-section-label">Current Preset</div>
    <div class="mod-info-chip">${escHtml(m.preset || '(none)')}</div>
    <div class="mod-inline-row">
      <button class="mod-btn-secondary" ${canSaveCurrent ? '' : 'disabled'} onclick="saveCurrentPromptPreset()">Save Current</button>
      <button class="mod-btn-danger" ${canDeleteCurrent ? '' : 'disabled'} onclick="deleteCurrentPromptPreset()">Delete Current</button>
    </div>
  `;
  }

  function renderRandomizedManage(body, m) {
    const pool = Array.isArray(m.randomized_preset_list) ? m.randomized_preset_list : [];
    const available = Array.isArray(m.randomized_available_presets) ? m.randomized_available_presets : [];
    const summaryMap = presetSummaryMap(m);
    const wcFront = typeof m.randomized_wildcard_front === 'string' ? m.randomized_wildcard_front : '';
    const wcBack = typeof m.randomized_wildcard_back === 'string' ? m.randomized_wildcard_back : '';
    const wcEnabled = !!m.randomized_wildcard_enabled;
    // Preserve in-progress typing if an unrelated state push re-renders mid-edit.
    const activeEl = document.activeElement;
    const focusedWcId = activeEl && (activeEl.id === 'modRandomizedWildcardFront' || activeEl.id === 'modRandomizedWildcardBack')
      ? activeEl.id : null;
    const wcLiveValue = focusedWcId ? activeEl.value : null;
    const wcCaret = focusedWcId ? activeEl.selectionStart : null;
    hideRandomizedPreview();
    const poolHtml = pool.length
      ? pool.map(preset => `
        <div class="pe-randomized-row">
          <span class="pe-randomized-name">${escHtml(preset)}</span>
          <div class="pe-randomized-actions">
            <button class="mod-btn-secondary mod-btn-compact" data-randomized-switch="${escHtml(preset)}">Switch</button>
            <button class="mod-btn-secondary mod-btn-compact" data-randomized-show="${escHtml(preset)}">Show</button>
            <button class="mod-btn-danger mod-btn-compact" data-randomized-remove="${escHtml(preset)}">Remove</button>
          </div>
        </div>
      `).join('')
      : '<div class="pe-randomized-empty">No presets selected</div>';
    const optionsHtml = available
      .map(preset => `<option value="${escHtml(preset)}" ${presetPreviewAttrs(preset, summaryMap)}>${escHtml(preset)}</option>`)
      .join('');
    body.innerHTML = `
    <div class="mod-section-label">Current Preset</div>
    <div class="mod-info-chip">${escHtml(m.preset || '(none)')}</div>
    <div class="mod-section-label">Randomized Pool</div>
    <div class="pe-randomized-list">${poolHtml}</div>
    <div class="pe-randomized-wc">
      <div class="mod-section-label pe-randomized-wc-head">
        <span>Randomized Inject (고정/와일드카드)</span>
        <button type="button" class="header-guide-btn" data-naia-guide="${escHtml(RANDOMIZED_WC_GUIDE)}">ⓘ 가이드</button>
      </div>
      <label class="mod-checkbox-item">
        <input type="checkbox" id="modRandomizedWildcardEnabled" ${wcEnabled ? 'checked' : ''}>
        <span class="mod-checkbox-label">매 생성마다 아래 내용을 주입 (고정 태그 또는 와일드카드)</span>
      </label>
      <label class="mod-field pe-randomized-wc-field">
        <span class="mod-field-label">앞 (artist 등 · Prefix 앞)</span>
        <textarea class="mod-textarea pe-randomized-wc-input" id="modRandomizedWildcardFront" rows="2"
                  placeholder="예: artist:ciloranko  또는  __artist__">${escHtml(wcFront)}</textarea>
      </label>
      <label class="mod-field pe-randomized-wc-field">
        <span class="mod-field-label">뒤 (character 등 · Prefix 뒤)</span>
        <textarea class="mod-textarea pe-randomized-wc-input" id="modRandomizedWildcardBack" rows="2"
                  placeholder="예: 1girl, smile  또는  __character__">${escHtml(wcBack)}</textarea>
      </label>
    </div>
    <div>
      <div class="mod-section-label">Add Preset</div>
      <div class="mod-inline-row pe-randomized-add-row">
        <select class="mod-select" id="modRandomizedPresetAddSelect" data-preview-kind="prompt-preset" data-preview-actions="none" ${available.length ? '' : 'disabled'}>${optionsHtml}</select>
        <button class="mod-btn-secondary mod-btn-compact" id="modRandomizedPresetAddBtn" ${available.length ? '' : 'disabled'}>Add</button>
      </div>
    </div>
    <div class="mod-inline-row">
      <button class="mod-btn-danger" id="modRandomizedPresetClearBtn" ${pool.length ? '' : 'disabled'}>Clear Pool</button>
    </div>
  `;

    const addButton = document.getElementById('modRandomizedPresetAddBtn');
    const addSelect = document.getElementById('modRandomizedPresetAddSelect');
    if (addButton) addButton.addEventListener('click', () => addRandomizedPreset());
    if (addSelect) {
      addSelect.addEventListener('keydown', event => {
        if (event.key === 'Enter') {
          event.preventDefault();
          addRandomizedPreset();
        }
      });
    }
    body.querySelectorAll('[data-randomized-remove]').forEach(button => {
      button.addEventListener('click', () => removeRandomizedPreset(button.dataset.randomizedRemove || ''));
    });
    body.querySelectorAll('[data-randomized-switch]').forEach(button => {
      button.addEventListener('click', () => {
        hideRandomizedPreview();
        switchRandomizedPreset(button.dataset.randomizedSwitch || '');
      });
    });
    body.querySelectorAll('[data-randomized-show]').forEach(button => {
      const preset = button.dataset.randomizedShow || '';
      button.addEventListener('mouseenter', () => renderRandomizedPreview(button, preset, summaryMap));
      button.addEventListener('focus', () => renderRandomizedPreview(button, preset, summaryMap));
      button.addEventListener('mouseleave', event => {
        if (randomizedPreview && randomizedPreview.contains(event.relatedTarget)) return;
        scheduleRandomizedPreviewHide();
      });
      button.addEventListener('blur', scheduleRandomizedPreviewHide);
    });
    const clearButton = document.getElementById('modRandomizedPresetClearBtn');
    if (clearButton) clearButton.addEventListener('click', () => clearRandomizedPresets());

    const wcFrontInput = document.getElementById('modRandomizedWildcardFront');
    const wcBackInput = document.getElementById('modRandomizedWildcardBack');
    const wcEnabledBox = document.getElementById('modRandomizedWildcardEnabled');
    const sendWildcard = () => {
      if (typeof setRandomizedWildcard === 'function') {
        setRandomizedWildcard(
          wcFrontInput ? wcFrontInput.value : '',
          wcBackInput ? wcBackInput.value : '',
          !!(wcEnabledBox && wcEnabledBox.checked),
        );
      }
    };
    if (wcEnabledBox) wcEnabledBox.addEventListener('change', sendWildcard);
    [wcFrontInput, wcBackInput].forEach(el => {
      if (!el) return;
      // 'change' fires on blur/Enter — avoids a backend round-trip (and re-render) per keystroke.
      el.addEventListener('change', sendWildcard);
      if (typeof bindTagAssist === 'function') bindTagAssist(el);
    });
    if (focusedWcId) {
      const restoreEl = document.getElementById(focusedWcId);
      if (restoreEl) {
        restoreEl.value = wcLiveValue;
        restoreEl.focus();
        try { restoreEl.setSelectionRange(wcCaret, wcCaret); } catch (_error) {}
      }
    }
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
    const weight = Number(e621.weight ?? 0);
    const e621Hidden = Array.isArray(e621.hidden_tags) ? e621.hidden_tags.join(', ') : '';
    body.innerHTML = `
    <div class="mod-boost-block">
      <div class="mod-boost-head">
        <span class="mod-boost-name">부스트 강도</span>
        <span class="mod-boost-val" id="modE621WeightValue">${weight.toFixed(2)}</span>
      </div>
      <input type="range" class="mod-boost-slider" id="modE621Weight" min="-5" max="5" step="0.05" value="${escHtml(String(weight))}"
        oninput="var v=document.getElementById('modE621WeightValue'); if(v) v.textContent=(+this.value).toFixed(2);">
      <div class="mod-boost-scale"><span>약화 −5</span><span>0 (래핑 없음)</span><span>강조 +5</span></div>
      <div class="mod-boost-caption">0이면 추천 태그를 가중치 없이 그대로 추가합니다.</div>
    </div>
    <div class="mod-boost-block">
      <div class="mod-boost-head"><span class="mod-boost-name">추천 모드</span></div>
      <select class="mod-select" id="modE621Mode" style="width:100%">
        <option value="stable"${e621.mode === 'stable' || !e621.mode ? ' selected' : ''}>stable — 결정적 (항상 같은 추천)</option>
        <option value="confused"${e621.mode === 'confused' ? ' selected' : ''}>confused — 확률적 (다양성↑)</option>
      </select>
    </div>
    <div>
      <div class="mod-section-label">숨길 태그 (Hidden Tags)</div>
      <textarea class="mod-textarea" id="modE621HiddenTags" placeholder="쉼표 또는 줄바꿈으로 구분">${escHtml(e621Hidden)}</textarea>
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
    const mag = Number(danbooru.magnitude ?? 3);
    const blend = Number(danbooru.rating_blend ?? 0.3);
    const advOpen = danbooru.override_on || danbooru.rating_override_on || danbooru.invert_weight;
    body.innerHTML = `
    <div class="mod-boost-block">
      <div class="mod-boost-head">
        <span class="mod-boost-name">강조 강도 <span class="mod-boost-chip" id="modDanMagLabel">추천</span></span>
        <span class="mod-boost-val" id="modDanMagValue">${mag} / 10</span>
      </div>
      <input type="range" class="mod-boost-slider" id="modDanMagnitude" min="1" max="10" step="1" value="${escHtml(String(mag))}">
      <div class="mod-boost-scale"><span>약한</span><span>추천</span><span>극한++</span></div>
      <div class="mod-boost-caption">적용 범위 <span id="modDanRange">0.80 ~ 1.35</span></div>
    </div>
    <div class="mod-boost-block">
      <div class="mod-boost-head">
        <span class="mod-boost-name">Rating 반영</span>
        <span class="mod-boost-val" id="modDanBlendValue">${blend.toFixed(1)}</span>
      </div>
      <input type="range" class="mod-boost-slider" id="modDanBlend" min="0" max="1" step="0.1" value="${escHtml(String(blend))}">
      <div class="mod-boost-scale"><span>전역 IDF</span><span>Rating IDF</span></div>
    </div>
    <div id="modDanFeedback"></div>
    <details class="mod-boost-adv"${advOpen ? ' open' : ''}>
      <summary>고급 — 오버라이드 · Rating 강제 · 반전</summary>
      <label class="mod-checkbox-item">
        <input type="checkbox" id="modDanOverrideOn" ${danbooru.override_on ? 'checked' : ''}>
        <span class="mod-checkbox-label">커스텀 오버라이드 (프리셋 곡선 대체)</span>
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
        <span class="mod-checkbox-label">Rating 강제 (모든 태그에 고정 등급 적용)</span>
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
        <span class="mod-checkbox-label">가중치 반전 (흔한 태그를 강조)</span>
      </label>
    </details>
    <div class="mod-inline-row">
      <button class="mod-btn-secondary" onclick="savePromptEngineeringDanbooruSettings()">Save Danbooru Settings</button>
    </div>
  `;
    bindDanbooruFeedback(danbooru);
  }

  function renderOllamaBoost(m) {
    const body = getBody(panels.ollamaBoost);
    if (!body) return;
    const boost = m.ollama_boost_settings || {};
    const nlWeight = Number.isFinite(Number(boost.nl_weight)) ? Number(boost.nl_weight) : 1.0;
    const effort = ['concise', 'standard', 'rich'].includes(boost.effort) ? boost.effort : 'rich';
    const includePrefix = !!boost.include_prefix;
    const includePostfix = !!boost.include_postfix;
    const includeE621 = !!boost.include_e621;
    const effortHtml = OLLAMA_BOOST_EFFORTS.map(([value, label]) => `
      <label class="mod-checkbox-item">
        <input type="radio" name="modOllamaBoostEffort" value="${escHtml(value)}"${effort === value ? ' checked' : ''}>
        <span class="mod-checkbox-label">${escHtml(label)}</span>
      </label>`).join('');
    body.innerHTML = `
    <div class="mod-boost-block">
      <div class="mod-boost-head">
        <span class="mod-boost-name">자연어 가중치</span>
        <span class="mod-boost-val" id="modOllamaBoostWeightValue">${nlWeight.toFixed(2)}</span>
      </div>
      <input type="range" class="mod-boost-slider" id="modOllamaBoostWeight" min="0.75" max="3" step="0.05" value="${escHtml(String(nlWeight))}"
        oninput="var v=document.getElementById('modOllamaBoostWeightValue'); if(v) v.textContent=(+this.value).toFixed(2);">
      <div class="mod-boost-scale" style="position:relative;display:block;height:12px;">
        <span style="position:absolute;left:0;">0.75</span>
        <span style="position:absolute;left:11.1%;transform:translateX(-50%);">1.0</span>
        <span style="position:absolute;right:0;">3.0</span>
      </div>
      <div class="mod-boost-caption">보강된 자연어 프롬프트 전체에 적용할 가중치 (1.0=무가중, NAI {v}::..:: / 로컬 (..:v)).</div>
    </div>
    <div class="mod-boost-block">
      <div class="mod-boost-head"><span class="mod-boost-name">Effort</span></div>
      <div class="mod-checkbox-grid" id="modOllamaBoostEffort">${effortHtml}</div>
      <div class="mod-boost-caption">보강 자연어의 길이·창의성(scene_boost level).</div>
    </div>
    <div>
      <div class="mod-section-label">Input 구성</div>
      <div class="mod-checkbox-grid">
        <label class="mod-checkbox-item">
          <input type="checkbox" id="modOllamaBoostIncludePrefix"${includePrefix ? ' checked' : ''}>
          <span class="mod-checkbox-label">PE Prefix 포함</span>
        </label>
        <label class="mod-checkbox-item">
          <input type="checkbox" id="modOllamaBoostIncludePostfix"${includePostfix ? ' checked' : ''}>
          <span class="mod-checkbox-label">PE Postfix 포함</span>
        </label>
        <label class="mod-checkbox-item">
          <input type="checkbox" id="modOllamaBoostIncludeE621"${includeE621 ? ' checked' : ''}>
          <span class="mod-checkbox-label">e621 Auto-Boost 포함</span>
        </label>
      </div>
      <div class="mod-boost-caption">Prefix / Postfix는 <b>와일드카드 출력만</b> 반영 (고정 아티스트·퀄리티 태그 제외). 가중치 구문 자동 제거.</div>
    </div>
    <div class="mod-inline-row">
      <button class="mod-btn-secondary" onclick="savePromptEngineeringOllamaBoostSettings()">Save Ollama Boost Settings</button>
    </div>
  `;
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
    renderOllamaBoost,
    renderDebugPanel,
  };
}
