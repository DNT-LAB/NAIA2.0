export function createConditionalPromptPanel({
  document,
  escHtml,
  onModTextEdit,
}) {
  const moduleBody = document.getElementById('modulePopupBody');

  function normalizeMode(mode) {
    return mode === 'v2' ? 'v2' : 'legacy';
  }

  function normalizeEngineOptions(options = {}) {
    const rawMax = Number(options.max_passes ?? 1);
    const maxPasses = Number.isFinite(rawMax)
      ? Math.min(20, Math.max(1, Math.round(rawMax)))
      : 1;
    return {
      max_passes: maxPasses,
      stop_on_match: Boolean(options.stop_on_match),
    };
  }

  function normalizeState(state = {}) {
    const mode = normalizeMode(state.editor_mode || state.mode);
    const hasLegacy = state.rules_legacy != null;
    const hasV2 = state.rules_v2 != null;
    const fallbackRules = state.rules != null ? String(state.rules) : '';
    const rulesLegacy = hasLegacy ? String(state.rules_legacy) : (mode === 'legacy' ? fallbackRules : '');
    const rulesV2 = hasV2 ? String(state.rules_v2) : (mode === 'v2' ? fallbackRules : '');
    const activeRules = mode === 'v2' ? rulesV2 : rulesLegacy;
    return {
      ...state,
      enabled: Boolean(state.enabled),
      editor_mode: mode,
      rules: activeRules,
      active_rules: activeRules,
      rules_legacy: rulesLegacy,
      rules_v2: rulesV2,
      engine_options: normalizeEngineOptions(state.engine_options || {}),
      active_preset: state.active_preset || '',
    };
  }

  function formatLog(log) {
    if (!log) return '<span style="color:var(--text-dim)">No log yet</span>';
    return escHtml(log).split('\n').map(line => {
      if (!line.trim()) return '';
      if (line.includes('Condition Not Met') || line.includes('Error:')) {
        return `<div style="color:#888">${line}</div>`;
      }
      if (line.includes('Condition Met')) {
        return `<div style="color:#4CAF50">${line}</div>`;
      }
      if (line.startsWith('===')) {
        return `<div style="color:#fff;font-weight:bold">${line}</div>`;
      }
      return `<div>${line}</div>`;
    }).join('');
  }

  function formatRules(text) {
    if (!text) return '<br>';
    return text.split('\n').map(line => {
      if (!line) return '<div class="cond-line"> </div>';
      let result = '';
      let i = 0;
      let inQuote = false;
      let segStart = 0;
      while (i <= line.length) {
        if (i < line.length && line[i] === '"') inQuote = !inQuote;
        if (i === line.length || (line[i] === ',' && !inQuote)) {
          const seg = line.substring(segStart, i);
          const comma = i < line.length ? ',' : '';
          const esc = escHtml(seg);
          if (seg.trimStart().startsWith('#')) {
            result += `<span class="cond-comment">${esc}</span>${escHtml(comma)}`;
          } else {
            result += esc + escHtml(comma);
          }
          segStart = i + 1;
        }
        i++;
      }
      return `<div class="cond-line">${result || ' '}</div>`;
    }).join('') + '<br>';
  }

  function onRulesInput(element) {
    const highlight = document.getElementById('condRulesHighlight');
    if (highlight) highlight.innerHTML = formatRules(element.value);
    const key = element.dataset.condRuleKey || 'rules';
    onModTextEdit('conditional_prompt', key, element.value);
  }

  function syncScroll(element) {
    const highlight = document.getElementById('condRulesHighlight');
    if (highlight) {
      highlight.scrollTop = element.scrollTop;
      highlight.scrollLeft = element.scrollLeft;
    }
  }

  function render(state) {
    let m = normalizeState(state);

    const isV2 = m.editor_mode === 'v2';
    const activeRuleKey = isV2 ? 'rules_v2' : 'rules_legacy';
    const activeRules = isV2 ? m.rules_v2 : m.rules_legacy;
    const modeLabel = isV2 ? 'New Editor DSL' : 'Legacy DSL';
    const presetLabel = m.active_preset ? `<span class="cond-status-chip">Preset ${escHtml(m.active_preset)}</span>` : '';
    const opts = normalizeEngineOptions(m.engine_options);
    const presets = Array.isArray(m.presets) ? m.presets : [];
    const presetOptions = [
      `<option value="">Load preset...</option>`,
      ...presets.map(preset => {
        const name = String(preset.name || '');
        const suffix = preset.is_bundled ? ' bundle' : ' user';
        const count = Number.isFinite(Number(preset.rule_count)) ? ` (${Number(preset.rule_count)})` : '';
        const selected = name && name === m.active_preset ? ' selected' : '';
        return `<option value="${escHtml(name)}"${selected}>${escHtml(name + count + suffix)}</option>`;
      }),
    ].join('');

    moduleBody.innerHTML = `
      <div>
        <label class="mod-checkbox-item">
          <input type="checkbox" ${m.enabled ? 'checked' : ''} oninput="setModuleParam('conditional_prompt','enabled',String(this.checked))">
          <span class="mod-checkbox-label">Enable Conditional Prompt</span>
        </label>
      </div>
      <div>
        <div class="mod-section-label">Execution Path</div>
        <input type="hidden" id="condEditorMode" value="${escHtml(m.editor_mode)}">
        <div class="cond-mode-row">
          <button type="button" class="cond-mode-btn ${!isV2 ? 'active' : ''}" data-cond-mode="legacy" onclick="setModuleParam('conditional_prompt','editor_mode','legacy')">Legacy DSL</button>
          <button type="button" class="cond-mode-btn ${isV2 ? 'active' : ''}" data-cond-mode="v2" onclick="setModuleParam('conditional_prompt','editor_mode','v2')">New Editor</button>
        </div>
      </div>
      <div>
        <div class="mod-section-label">Preset</div>
        <select class="mod-select" id="condPresetSelect" onchange="if(this.value)setModuleParam('conditional_prompt','preset_load',this.value)">
          ${presetOptions}
        </select>
      </div>
      <div>
        <div class="cond-rules-head">
          <div class="mod-section-label">Rules (${modeLabel})</div>
          ${presetLabel}
        </div>
        <div class="cond-rules-wrap">
          <div class="cond-rules-highlight" id="condRulesHighlight">${formatRules(activeRules)}</div>
          <textarea class="mod-textarea cond-rules-input" id="condRulesInput" data-cond-rule-key="${activeRuleKey}" placeholder="(condition):action&#10;# comment lines ignored" oninput="onCondRulesInput(this)" onscroll="syncCondScroll(this)">${escHtml(activeRules)}</textarea>
        </div>
      </div>
      <div>
        <div class="mod-section-label">Engine Options</div>
        <div class="cond-engine-grid">
          <label class="mod-field">
            <span class="mod-field-label">Max Passes</span>
            <input class="mod-input" id="condMaxPasses" type="number" min="1" max="20" step="1" value="${escHtml(String(opts.max_passes))}" onchange="setModuleParam('conditional_prompt','max_passes',this.value)">
          </label>
          <label class="mod-checkbox-item cond-stop-row">
            <input type="checkbox" id="condStopOnMatch" ${opts.stop_on_match ? 'checked' : ''} onchange="setModuleParam('conditional_prompt','stop_on_match',String(this.checked))">
            <span class="mod-checkbox-label">Stop On Match</span>
          </label>
        </div>
      </div>
      <div>
        <div class="mod-section-label mod-collapsible" onclick="this.classList.toggle('open');this.nextElementSibling.classList.toggle('collapsed')">
          Syntax Guide <span class="mod-collapse-arrow">▶</span>
        </div>
        <div class="collapsed" style="font-size:10px;color:var(--text-dim);line-height:1.5;padding:6px 0">
          <b>Condition:</b> tag, ~tag (NOT), *tag (exact), e|q|s|g (rating)<br>
          <b>Logic:</b> &amp; (AND), | (OR), () grouping<br>
          <b>Actions:</b> main+=tag, prefix+=tag, postfix+=tag, old=new<br>
          <b>Character:</b> char_set(N, enabled), char:N+=tag, uc:N=value<br>
          <b>Example:</b> (e):prefix+=nsfw^rating:explicit,
        </div>
      </div>
      <div>
        <button class="mod-action-btn mod-start" onclick="setModuleParam('conditional_prompt','test','1')">Test Rules</button>
      </div>
      <div>
        <div class="mod-section-label">Execution Log</div>
        <div class="mod-log-viewer" id="condLogViewer">${formatLog(m.log)}</div>
      </div>
    `;
  }

  return {
    formatLog,
    formatRules,
    onRulesInput,
    syncScroll,
    render,
  };
}
