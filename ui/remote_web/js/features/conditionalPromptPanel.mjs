export function createConditionalPromptPanel({
  document,
  escHtml,
  onModTextEdit,
  setModuleParam,
}) {
  const moduleBody = document.getElementById('modulePopupBody');
  const sendModuleParam = setModuleParam || ((moduleId, key, value) => {
    if (typeof globalThis.setModuleParam === 'function') {
      globalThis.setModuleParam(moduleId, key, value);
    }
  });

  const TAG_MODIFIERS = new Set(['contains', 'exact', 'not_contains', 'not_exact']);
  const LEAF_KINDS = new Set(['tag', 'rating', 'char_in', 'char_on']);
  const ACTION_KINDS = new Set(['append_list', 'append', 'replace', 'char_set', 'char_replace', 'char_append']);
  const FIXED_TARGETS = new Set(['prefix', 'main', 'postfix', 'global_uc', 'neg']);
  const RATING_VALUES = new Set(['e', 'q', 's', 'g']);
  const RATING_SOURCES = new Set(['auto', 'row', 'override', 'bayes']);

  let currentState = null;
  let selectedRuleId = null;
  let presetPopoverOpen = false;
  let dirty = false;
  let bound = false;

  function safeText(value) {
    return value == null ? '' : String(value);
  }

  function boolValue(value, fallback = false) {
    if (typeof value === 'boolean') return value;
    if (typeof value === 'string') return value.toLowerCase() === 'true';
    if (value == null) return fallback;
    return Boolean(value);
  }

  function clampInt(value, min, max, fallback) {
    const parsed = Number(value);
    if (!Number.isFinite(parsed)) return fallback;
    return Math.min(max, Math.max(min, Math.round(parsed)));
  }

  function newId() {
    if (globalThis.crypto && typeof globalThis.crypto.randomUUID === 'function') {
      return globalThis.crypto.randomUUID();
    }
    return `web-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
  }

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
      stop_on_match: boolValue(options.stop_on_match),
    };
  }

  function emptyCondition(kind = 'tag') {
    if (kind === 'group') {
      return {
        kind: 'group',
        leaf_kind: null,
        negated: false,
        tag_value: '',
        tag_modifier: 'contains',
        rating_value: '',
        rating_source: 'auto',
        char_index: null,
        char_tag_value: '',
        char_tag_modifier: 'contains',
        logical: 'AND',
        children: [],
      };
    }
    return {
      kind: 'leaf',
      leaf_kind: LEAF_KINDS.has(kind) ? kind : 'tag',
      negated: false,
      tag_value: '',
      tag_modifier: 'contains',
      rating_value: kind === 'rating' ? 'e' : '',
      rating_source: 'auto',
      char_index: kind === 'char_in' || kind === 'char_on' ? 1 : null,
      char_tag_value: '',
      char_tag_modifier: 'contains',
      logical: null,
      children: [],
    };
  }

  function emptyAction(kind = 'append_list') {
    const validKind = ACTION_KINDS.has(kind) ? kind : 'append_list';
    return {
      kind: validKind,
      target: 'main',
      preserve_weight: true,
      tags: [],
      old_tag: '',
      new_tags: [],
      char_state: validKind === 'char_set' ? 'enabled' : null,
      char_index: ['char_set', 'char_replace', 'char_append'].includes(validKind) ? 1 : null,
      char_old_tag: '',
      char_new_tag: '',
    };
  }

  function emptyRule(index = 0) {
    return {
      id: newId(),
      name: '',
      enabled: true,
      priority: (index + 1) * 10,
      kind: 'block',
      condition: emptyCondition('tag'),
      action: emptyAction('append_list'),
      raw_dsl: null,
    };
  }

  function normalizeCondition(condition) {
    const raw = condition && typeof condition === 'object' ? condition : emptyCondition('tag');
    if (raw.kind === 'group') {
      return {
        ...emptyCondition('group'),
        logical: raw.logical === 'OR' ? 'OR' : 'AND',
        children: Array.isArray(raw.children) ? raw.children.map(normalizeCondition) : [],
      };
    }
    const leafKind = LEAF_KINDS.has(raw.leaf_kind) ? raw.leaf_kind : 'tag';
    return {
      ...emptyCondition(leafKind),
      leaf_kind: leafKind,
      negated: boolValue(raw.negated),
      tag_value: safeText(raw.tag_value),
      tag_modifier: TAG_MODIFIERS.has(raw.tag_modifier) ? raw.tag_modifier : 'contains',
      rating_value: RATING_VALUES.has(raw.rating_value) ? raw.rating_value : 'e',
      rating_source: RATING_SOURCES.has(raw.rating_source) ? raw.rating_source : 'auto',
      char_index: raw.char_index == null ? 1 : clampInt(raw.char_index, 1, 99, 1),
      char_tag_value: safeText(raw.char_tag_value),
      char_tag_modifier: TAG_MODIFIERS.has(raw.char_tag_modifier) ? raw.char_tag_modifier : 'contains',
    };
  }

  function normalizeTags(tags) {
    if (!Array.isArray(tags)) return [];
    return tags.map(tag => safeText(tag).trim()).filter(Boolean);
  }

  function normalizeAction(action) {
    const raw = action && typeof action === 'object' ? action : emptyAction('append_list');
    const kind = ACTION_KINDS.has(raw.kind) ? raw.kind : 'append_list';
    return {
      ...emptyAction(kind),
      kind,
      target: safeText(raw.target) || 'main',
      preserve_weight: boolValue(raw.preserve_weight, true),
      tags: normalizeTags(raw.tags),
      old_tag: safeText(raw.old_tag),
      new_tags: normalizeTags(raw.new_tags),
      char_state: raw.char_state === 'disabled' ? 'disabled' : 'enabled',
      char_index: raw.char_index == null ? 1 : clampInt(raw.char_index, 1, 99, 1),
      char_old_tag: safeText(raw.char_old_tag),
      char_new_tag: safeText(raw.char_new_tag),
    };
  }

  function normalizeRule(rule, index) {
    const raw = rule && typeof rule === 'object' ? rule : emptyRule(index);
    const kind = raw.kind === 'raw' ? 'raw' : 'block';
    return {
      id: safeText(raw.id) || newId(),
      name: safeText(raw.name),
      enabled: raw.enabled !== false,
      priority: Number.isFinite(Number(raw.priority)) ? Math.round(Number(raw.priority)) : (index + 1) * 10,
      kind,
      condition: normalizeCondition(raw.condition),
      action: normalizeAction(raw.action),
      raw_dsl: raw.raw_dsl == null ? null : safeText(raw.raw_dsl),
    };
  }

  function fallbackBookFromDsl(text, engineOptions = {}) {
    const rules = safeText(text)
      .split(/\n|,(?=\s*(?:#?\())/)
      .map(part => part.trim())
      .filter(Boolean)
      .map((line, index) => ({
        ...emptyRule(index),
        kind: 'raw',
        raw_dsl: line,
        enabled: !line.startsWith('#'),
      }));
    return {
      schema_version: 1,
      name: '',
      description: '',
      engine_options: normalizeEngineOptions(engineOptions),
      rules,
    };
  }

  function normalizeBook(book, fallbackDsl = '', engineOptions = {}) {
    const raw = book && typeof book === 'object'
      ? book
      : fallbackBookFromDsl(fallbackDsl, engineOptions);
    return {
      schema_version: clampInt(raw.schema_version, 1, 99, 1),
      name: safeText(raw.name),
      description: safeText(raw.description),
      engine_options: normalizeEngineOptions(raw.engine_options || engineOptions),
      rules: Array.isArray(raw.rules) ? raw.rules.map(normalizeRule) : [],
    };
  }

  function normalizeState(state = {}) {
    const mode = normalizeMode(state.editor_mode || state.mode);
    const hasLegacy = state.rules_legacy != null;
    const hasV2 = state.rules_v2 != null;
    const fallbackRules = state.rules != null ? String(state.rules) : '';
    const rulesLegacy = hasLegacy ? String(state.rules_legacy) : (mode === 'legacy' ? fallbackRules : '');
    const rulesV2 = hasV2 ? String(state.rules_v2) : (mode === 'v2' ? fallbackRules : '');
    const engineOptions = normalizeEngineOptions(state.engine_options || {});
    const book = normalizeBook(state.rules_v2_book, rulesV2, engineOptions);
    const activeRules = mode === 'v2' ? serializeRulebook(book) : rulesLegacy;
    return {
      ...state,
      enabled: Boolean(state.enabled),
      editor_mode: mode,
      rules: activeRules,
      active_rules: activeRules,
      rules_legacy: rulesLegacy,
      rules_v2: serializeRulebook(book),
      rules_v2_book: book,
      engine_options: normalizeEngineOptions(book.engine_options || engineOptions),
      active_preset: state.active_preset || '',
      presets: Array.isArray(state.presets) ? state.presets : [],
    };
  }

  function rulebook() {
    if (!currentState) return normalizeBook(null);
    return currentState.rules_v2_book;
  }

  function selectedRule() {
    const book = rulebook();
    if (!book.rules.length) return null;
    let rule = book.rules.find(item => item.id === selectedRuleId);
    if (!rule) {
      rule = book.rules[0];
      selectedRuleId = rule.id;
    }
    return rule;
  }

  function selectedRuleIndex() {
    const rule = selectedRule();
    if (!rule) return -1;
    return rulebook().rules.findIndex(item => item.id === rule.id);
  }

  function renumberPriorities() {
    rulebook().rules.forEach((rule, index) => {
      rule.priority = (index + 1) * 10;
    });
  }

  function escapeAttr(value) {
    return escHtml(safeText(value));
  }

  function option(value, label, selectedValue) {
    return `<option value="${escapeAttr(value)}"${value === selectedValue ? ' selected' : ''}>${escHtml(label)}</option>`;
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

  function tagPrefix(modifier) {
    if (modifier === 'exact') return '*';
    if (modifier === 'not_contains') return '~';
    if (modifier === 'not_exact') return '~!';
    return '';
  }

  function serializeCondition(condition, isRoot = true) {
    const cond = normalizeCondition(condition);
    if (cond.kind === 'leaf') return serializeLeaf(cond);
    if (!cond.children.length) return '';
    if (cond.children.length === 1) return serializeCondition(cond.children[0], isRoot);
    const sep = cond.logical === 'OR' ? '|' : '&';
    const inner = cond.children.map(child => serializeCondition(child, false)).join(sep);
    return isRoot ? inner : `(${inner})`;
  }

  function serializeLeaf(leaf) {
    if (leaf.leaf_kind === 'rating') {
      const neg = leaf.negated ? '~' : '';
      const value = RATING_VALUES.has(leaf.rating_value) ? leaf.rating_value : 'e';
      if (leaf.rating_source === 'auto') return `${neg}${value}`;
      return `${neg}rating(${value}, source=${leaf.rating_source || 'auto'})`;
    }
    if (leaf.leaf_kind === 'char_in') {
      const inner = `${tagPrefix(leaf.char_tag_modifier)}${leaf.char_tag_value || ''}`;
      return `${leaf.negated ? '~' : ''}char_in(${leaf.char_index || 1}, ${inner})`;
    }
    if (leaf.leaf_kind === 'char_on') {
      return `${leaf.negated ? '~' : ''}char_on(${leaf.char_index || 1})`;
    }
    const body = `${tagPrefix(leaf.tag_modifier)}${leaf.tag_value || ''}`;
    if (leaf.negated && !body.startsWith('~')) return `~${body}`;
    return body;
  }

  function joinTags(tags) {
    return normalizeTags(tags).join('^');
  }

  function serializeAction(action) {
    const act = normalizeAction(action);
    if (act.kind === 'append_list') return `${act.target}+=${joinTags(act.tags)}`;
    if (act.kind === 'append') return `${act.target}+:${joinTags(act.tags)}`;
    if (act.kind === 'replace') return `${act.old_tag}=${joinTags(act.new_tags)}`;
    if (act.kind === 'char_set') return `char_set(${act.char_index || 1}, ${act.char_state || 'enabled'})`;
    if (act.kind === 'char_replace') return `char_replace(${act.char_index || 1}, ${act.char_old_tag}, ${act.char_new_tag})`;
    if (act.kind === 'char_append') return `char:${act.char_index || 1}+=${joinTags(act.tags)}`;
    return 'main+=';
  }

  function serializeRule(rule) {
    if (!rule) return '';
    if (rule.kind === 'raw') {
      const line = safeText(rule.raw_dsl).trim();
      if (!line) return '';
      if (!rule.enabled && !line.startsWith('#')) return `#${line}`;
      return line;
    }
    const line = `(${serializeCondition(rule.condition, true)}):${serializeAction(rule.action)}`;
    return rule.enabled ? line : `#${line}`;
  }

  function serializeRulebook(book) {
    const withIndex = [...(book?.rules || [])].map((rule, index) => ({rule, index}));
    withIndex.sort((a, b) => {
      const diff = Number(a.rule.priority || 0) - Number(b.rule.priority || 0);
      return diff || a.index - b.index;
    });
    return withIndex.map(item => serializeRule(item.rule)).filter(line => line.trim()).join(',\n');
  }

  function describeTarget(target) {
    if (target === 'prefix') return '선행고정 뒤';
    if (target === 'main') return '메인 프롬프트';
    if (target === 'postfix') return '후행고정 뒤';
    if (target === 'global_uc') return '공용 UC';
    if (target === 'neg') return '네거티브';
    if (target === 'char:*') return '모든 활성 캐릭터 프롬프트';
    if (target === 'uc:*') return '모든 활성 캐릭터 UC';
    if (target?.startsWith('char:')) return `캐릭터 ${target.split(':')[1]} 프롬프트`;
    if (target?.startsWith('uc:')) return `캐릭터 ${target.split(':')[1]} UC`;
    return target || '메인 프롬프트';
  }

  function describeCondition(node) {
    const cond = normalizeCondition(node);
    if (cond.kind === 'group') {
      const joiner = cond.logical === 'OR' ? ' 또는 ' : ' 그리고 ';
      const parts = cond.children.map(describeCondition).filter(Boolean);
      return parts.length ? `(${parts.join(joiner)})` : '비어 있는 조건 묶음';
    }
    let text;
    if (cond.leaf_kind === 'rating') {
      text = `등급이 ${String(cond.rating_value || 'e').toUpperCase()}`;
    } else if (cond.leaf_kind === 'char_in') {
      text = `캐릭터 ${cond.char_index || 1} 안에 '${cond.char_tag_value || ''}' ${tagModifierLabel(cond.char_tag_modifier)}`;
    } else if (cond.leaf_kind === 'char_on') {
      text = `캐릭터 ${cond.char_index || 1} 슬롯이 켜져 있음`;
    } else {
      text = `'${cond.tag_value || ''}' ${tagModifierLabel(cond.tag_modifier)}`;
    }
    return cond.negated ? `${text} 아님` : text;
  }

  function describeAction(action) {
    const act = normalizeAction(action);
    if (act.kind === 'append_list' || act.kind === 'append') {
      return `${describeTarget(act.target)}에 ${joinTags(act.tags) || '(태그 없음)'} 추가`;
    }
    if (act.kind === 'replace') return `'${act.old_tag || ''}'를 ${joinTags(act.new_tags) || '(태그 없음)'}로 교체`;
    if (act.kind === 'char_set') return `캐릭터 ${act.char_index || 1}을 ${act.char_state === 'disabled' ? '사용 안 함' : '사용'}`;
    if (act.kind === 'char_replace') return `캐릭터 ${act.char_index || 1}의 '${act.char_old_tag || ''}'를 '${act.char_new_tag || ''}'로 교체`;
    if (act.kind === 'char_append') return `캐릭터 ${act.char_index || 1}에 ${joinTags(act.tags) || '(태그 없음)'} 추가`;
    return '변경 없음';
  }

  function tagModifierLabel(modifier) {
    if (modifier === 'exact') return '정확히 일치';
    if (modifier === 'not_contains') return '포함하지 않음';
    if (modifier === 'not_exact') return '정확히 일치하지 않음';
    return '포함';
  }

  function actionBadge(action) {
    const kind = action?.kind || 'append_list';
    const labels = {
      append_list: '추가',
      append: '끝추가',
      replace: '교체',
      char_set: '캐릭터',
      char_append: '캐추가',
      char_replace: '캐교체',
    };
    return labels[kind] || '추가';
  }

  function conditionBadge(rule) {
    if (rule.kind === 'raw') return '고급';
    return rule.condition?.kind === 'group' ? '묶음' : '단일';
  }

  function markDirty() {
    dirty = true;
    if (currentState) currentState.simulation = null;
    updateDynamicText();
  }

  function currentBookPayload() {
    const book = rulebook();
    book.engine_options = normalizeEngineOptions(book.engine_options);
    return {
      schema_version: book.schema_version || 1,
      name: book.name || '',
      description: book.description || '',
      engine_options: book.engine_options,
      rules: book.rules.map(rule => ({
        ...rule,
        condition: normalizeCondition(rule.condition),
        action: normalizeAction(rule.action),
      })),
    };
  }

  function applyBook({showToast = true} = {}) {
    if (!currentState) return;
    const book = currentBookPayload();
    const dsl = serializeRulebook(book);
    currentState.rules_v2_book = normalizeBook(book, dsl, book.engine_options);
    currentState.rules_v2 = dsl;
    currentState.rules = dsl;
    currentState.active_rules = dsl;
    currentState.editor_mode = 'v2';
    dirty = false;
    sendModuleParam('conditional_prompt', 'rules_v2_book', JSON.stringify({book}));
    updateDynamicText();
    if (showToast && typeof globalThis.showToast === 'function') {
      globalThis.showToast('조건부 프롬프트 규칙을 모듈에 적용했습니다', 'success');
    }
  }

  function savePreset() {
    const input = document.getElementById('condPresetNameInput');
    const select = document.getElementById('condPresetSelect');
    const name = safeText(input?.value || select?.value).trim();
    if (!name) {
      if (typeof globalThis.showToast === 'function') globalThis.showToast('프리셋 이름을 입력하세요', 'error');
      return;
    }
    sendModuleParam('conditional_prompt', 'preset_save', JSON.stringify({
      name,
      book: currentBookPayload(),
    }));
    dirty = false;
    updateDynamicText();
  }

  function updateDynamicText() {
    if (!currentState) return;
    const book = rulebook();
    const dsl = serializeRulebook(book);
    currentState.rules_v2 = dsl;
    currentState.rules = currentState.editor_mode === 'v2' ? dsl : currentState.rules_legacy;
    currentState.active_rules = currentState.rules;

    const selected = selectedRule();
    const selectedDsl = document.getElementById('condSelectedDsl');
    if (selectedDsl) {
      selectedDsl.value = currentState.simulation
        ? formatSimulationText(currentState.simulation)
        : (selected ? serializeRule(selected) : '');
    }
    const summary = document.getElementById('condSelectedSummary');
    if (summary) summary.textContent = selected ? `${describeCondition(selected.condition)} → ${describeAction(selected.action)}` : '선택한 규칙 요약이 여기에 표시됩니다.';
    const dirtyChip = document.getElementById('condDirtyChip');
    if (dirtyChip) {
      dirtyChip.textContent = dirty ? '미적용 변경' : '적용됨';
      dirtyChip.classList.toggle('dirty', dirty);
    }
    const applyBtn = document.querySelector('[data-cond-action="apply-book"]');
    if (applyBtn) applyBtn.disabled = !dirty;
  }

  function renderModeBar(m) {
    const presetName = safeText(m.active_preset || '').trim();
    const presetLabel = presetName ? `<span class="cond-status-chip cond-preset-status">Preset ${escHtml(presetName)}</span>` : '';
    const presetButtonLabel = presetName ? `프리셋: ${presetName}` : '프리셋';
    return `
      <div class="cond-topbar">
        <label class="mod-checkbox-item cond-enable-row">
          <input type="checkbox" ${m.enabled ? 'checked' : ''} data-cond-global="enabled">
          <span class="mod-checkbox-label">조건부 프롬프트 활성화</span>
        </label>
        <div class="cond-mode-row">
          <button type="button" class="cond-mode-btn ${m.editor_mode !== 'v2' ? 'active' : ''}" data-cond-mode="legacy">Legacy DSL</button>
          <button type="button" class="cond-mode-btn ${m.editor_mode === 'v2' ? 'active' : ''}" data-cond-mode="v2">New Editor</button>
        </div>
        <div class="cond-status-row">
          <button type="button" class="cond-preset-toggle" data-cond-action="toggle-preset-popover">${escHtml(presetButtonLabel)}</button>
          ${presetLabel}
          <span class="cond-status-chip" id="condDirtyChip">${dirty ? '미적용 변경' : '적용됨'}</span>
        </div>
      </div>`;
  }

  function renderLegacy(m) {
    const activeRuleKey = 'rules_legacy';
    const activeRules = m.rules_legacy;
    moduleBody.innerHTML = `
      <div class="cond-root">
        ${renderModeBar(m)}
        <input type="hidden" id="condEditorMode" value="${escapeAttr(m.editor_mode)}">
        <div>
          <div class="cond-rules-head">
            <div class="mod-section-label">Rules (Legacy DSL)</div>
            ${m.active_preset ? `<span class="cond-status-chip">Preset ${escHtml(m.active_preset)}</span>` : ''}
          </div>
          <div class="cond-rules-wrap">
            <div class="cond-rules-highlight" id="condRulesHighlight">${formatRules(activeRules)}</div>
            <textarea class="mod-textarea cond-rules-input" id="condRulesInput" data-cond-rule-key="${activeRuleKey}" placeholder="(condition):action&#10;# comment lines ignored" oninput="onCondRulesInput(this)" onscroll="syncCondScroll(this)">${escHtml(activeRules)}</textarea>
          </div>
        </div>
        ${renderSyntaxGuide()}
        <div>
          <button class="mod-action-btn mod-start" data-cond-action="test-rules">Test Rules</button>
        </div>
        <div>
          <div class="mod-section-label">Execution Log</div>
          <div class="mod-log-viewer" id="condLogViewer">${formatLog(m.log)}</div>
        </div>
      </div>`;
  }

  function renderSyntaxGuide() {
    return `
      <div>
        <div class="mod-section-label mod-collapsible" data-cond-action="toggle-syntax">
          Syntax Guide <span class="mod-collapse-arrow">▶</span>
        </div>
        <div class="collapsed" style="font-size:10px;color:var(--text-dim);line-height:1.5;padding:6px 0">
          <b>Condition:</b> tag, ~tag (NOT), *tag (exact), e|q|s|g (rating)<br>
          <b>Logic:</b> &amp; (AND), | (OR), () grouping<br>
          <b>Actions:</b> main+=tag, prefix+=tag, postfix+=tag, old=new<br>
          <b>Character:</b> char_set(N, enabled), char:N+=tag, uc:N=value
        </div>
      </div>`;
  }

  function renderV2(m) {
    const book = rulebook();
    if (selectedRuleId && !book.rules.some(rule => rule.id === selectedRuleId)) selectedRuleId = null;
    if (!selectedRuleId && book.rules.length) selectedRuleId = book.rules[0].id;
    const selected = selectedRule();
    const simulationActive = Boolean(m.simulation);
    moduleBody.innerHTML = `
      <div class="cond-root cond-v2-editor${presetPopoverOpen ? ' cond-preset-popover-open' : ''}">
        ${renderModeBar(m)}
        <input type="hidden" id="condEditorMode" value="${escapeAttr(m.editor_mode)}">
        <div class="cond-summary-box" id="condSelectedSummary">${escHtml(selected ? `${describeCondition(selected.condition)} → ${describeAction(selected.action)}` : '선택한 규칙 요약이 여기에 표시됩니다.')}</div>
        <div class="cond-v2-grid">
          ${renderPresetPane(m)}
          ${renderRuleListPane(book)}
          ${renderConditionPane(selected)}
          ${renderActionPane(selected)}
        </div>
        <div class="cond-bottom-actions">
          <button type="button" class="mod-action-btn" data-cond-action="reload-state">현재 DSL 다시 불러오기</button>
          <button type="button" class="mod-action-btn" data-cond-action="${simulationActive ? 'clear-simulation' : 'test-rules'}">${simulationActive ? '시뮬레이션 종료' : '시뮬레이션'}</button>
          <button type="button" class="mod-action-btn mod-start" data-cond-action="apply-book" ${dirty ? '' : 'disabled'}>✔ 모듈에 적용</button>
        </div>
        <div>
          <div class="mod-section-label">Execution Log</div>
          <div class="mod-log-viewer" id="condLogViewer">${formatLog(m.log)}</div>
        </div>
      </div>`;
    updateDynamicText();
  }

  function renderPresetPane(m) {
    const presets = Array.isArray(m.presets) ? m.presets : [];
    const options = [
      `<option value="">프리셋 선택...</option>`,
      ...presets.map(preset => {
        const name = safeText(preset.name);
        const suffix = preset.is_bundled ? ' bundle' : ' user';
        const count = Number.isFinite(Number(preset.rule_count)) ? ` (${Number(preset.rule_count)})` : '';
        return `<option value="${escapeAttr(name)}"${name === m.active_preset ? ' selected' : ''}>${escHtml(name + count + suffix)}</option>`;
      }),
    ].join('');
    const presetItems = presets.map(preset => {
      const name = safeText(preset.name);
      const active = name === m.active_preset;
      return `
        <button type="button" class="cond-preset-item${active ? ' active' : ''}" data-cond-action="load-preset" data-preset-name="${escapeAttr(name)}">
          <span>${escHtml(name)}</span>
          <small>${preset.rule_count ?? 0}개${preset.is_bundled ? ' · 번들' : ''}</small>
        </button>`;
    }).join('');
    return `
      <section class="cond-pane cond-preset-pane">
        <div class="cond-pane-title-row">
          <div class="cond-pane-title">프리셋</div>
          <button type="button" class="cond-preset-close" data-cond-action="toggle-preset-popover" aria-label="프리셋 닫기">×</button>
        </div>
        <select class="mod-select" id="condPresetSelect">${options}</select>
        <div class="cond-preset-list">${presetItems || '<div class="cond-empty">저장된 프리셋 없음</div>'}</div>
        <input class="mod-input" id="condPresetNameInput" placeholder="프리셋 이름" value="${escapeAttr(m.active_preset)}">
        <div class="cond-button-row">
          <button type="button" data-cond-action="load-selected-preset">불러오기</button>
          <button type="button" data-cond-action="save-preset">저장</button>
          <button type="button" data-cond-action="delete-preset">삭제</button>
        </div>
      </section>`;
  }

  function renderRuleListPane(book) {
    const selectedId = selectedRule()?.id || '';
    const rows = book.rules.map((rule, index) => `
      <button type="button" class="cond-rule-item${rule.id === selectedId ? ' selected' : ''}${rule.enabled ? '' : ' disabled'}" data-cond-action="select-rule" data-rule-id="${escapeAttr(rule.id)}">
        <span class="cond-rule-dot"></span>
        <span class="cond-badge kind-${rule.kind === 'raw' ? 'raw' : rule.condition.kind}">${escHtml(conditionBadge(rule))}</span>
        <span class="cond-badge action-${escapeAttr(rule.action.kind || 'raw')}">${escHtml(rule.kind === 'raw' ? 'DSL' : actionBadge(rule.action))}</span>
        <strong>${escHtml(rule.kind === 'raw' ? (rule.raw_dsl || '직접 DSL 편집') : describeAction(rule.action))}</strong>
        <small>#${index + 1}</small>
      </button>`).join('');
    return `
      <section class="cond-pane cond-rule-pane">
        <div class="cond-pane-title">규칙 목록</div>
        <div class="cond-rule-list">${rows || '<div class="cond-empty">규칙 없음</div>'}</div>
        <div class="cond-rule-tools">
          <button type="button" data-cond-action="toggle-rule" ${selectedId ? '' : 'disabled'}>켜기/끄기</button>
          <button type="button" data-cond-action="add-rule">+ 새 규칙</button>
          <button type="button" data-cond-action="delete-rule" ${selectedId ? '' : 'disabled'}>- 선택 제거</button>
          <button type="button" data-cond-action="move-rule-up" ${selectedRuleIndex() > 0 ? '' : 'disabled'}>↑ 위로</button>
          <button type="button" data-cond-action="move-rule-down" ${selectedRuleIndex() >= 0 && selectedRuleIndex() < book.rules.length - 1 ? '' : 'disabled'}>↓ 아래로</button>
        </div>
      </section>`;
  }

  function renderConditionPane(rule) {
    if (!rule) {
      return `
        <section class="cond-pane cond-condition-pane">
          <div class="cond-pane-title">이 조건이 맞으면</div>
          <div class="cond-empty">규칙을 선택하세요.</div>
        </section>`;
    }
    if (rule.kind === 'raw') {
      return `
        <section class="cond-pane cond-condition-pane">
          <div class="cond-pane-title">고급 DSL 직접 편집</div>
          <textarea class="mod-textarea cond-raw-editor" data-cond-rule-field="raw_dsl">${escHtml(rule.raw_dsl || '')}</textarea>
        </section>`;
    }
    return `
      <section class="cond-pane cond-condition-pane">
        <div class="cond-pane-title">이 조건이 맞으면</div>
        <div class="cond-condition-scroll">
          ${renderConditionNode(rule.condition, '')}
        </div>
      </section>`;
  }

  function renderConditionNode(node, path) {
    const cond = normalizeCondition(node);
    const pathAttr = escapeAttr(path);
    const removable = path !== '';
    const depth = path ? path.split('.').length : 0;
    if (cond.kind === 'group') {
      const children = cond.children.map((child, index) => renderConditionNode(child, path ? `${path}.${index}` : String(index))).join('');
      return `
        <div class="cond-condition-card group depth-${depth % 5}" data-cond-node-path="${pathAttr}">
          <div class="cond-node-row cond-kind-row">
            <label>조건 형태:</label>
            <select class="mod-select" data-cond-node-field="kind" data-cond-node-path="${pathAttr}">
              ${option('leaf', '단일 조건', 'group')}
              ${option('group', '조건 묶음', 'group')}
            </select>
            ${removable ? `<button type="button" class="cond-delete-node-btn" data-cond-action="delete-condition" data-cond-node-path="${pathAttr}" aria-label="이 조건 제거">×</button>` : ''}
          </div>
          <div class="cond-node-row">
            <label>묶음 방식:</label>
            <select class="mod-select" data-cond-node-field="logical" data-cond-node-path="${pathAttr}">
              ${option('AND', '모두 만족', cond.logical)}
              ${option('OR', '하나라도 만족', cond.logical)}
            </select>
          </div>
          <div class="cond-children">${children || '<div class="cond-empty compact">비어 있는 조건 묶음</div>'}</div>
          <div class="cond-button-row">
            <button type="button" data-cond-action="add-condition-leaf" data-cond-node-path="${pathAttr}">+ 조건</button>
            <button type="button" data-cond-action="add-condition-group" data-cond-node-path="${pathAttr}">+ 묶음</button>
          </div>
        </div>`;
    }
    const leafKind = cond.leaf_kind || 'tag';
    return `
      <div class="cond-condition-card depth-${depth % 5}" data-cond-node-path="${pathAttr}">
        <div class="cond-node-row cond-kind-row">
          <label>조건 형태:</label>
          <select class="mod-select" data-cond-node-field="kind" data-cond-node-path="${pathAttr}">
            ${option('leaf', '단일 조건', 'leaf')}
            ${option('group', '조건 묶음', 'leaf')}
          </select>
          ${removable ? `<button type="button" class="cond-delete-node-btn" data-cond-action="delete-condition" data-cond-node-path="${pathAttr}" aria-label="이 조건 제거">×</button>` : ''}
        </div>
        <div class="cond-node-row">
          <label>판단 기준:</label>
          <select class="mod-select" data-cond-node-field="leaf_kind" data-cond-node-path="${pathAttr}">
            ${option('tag', '태그 확인', leafKind)}
            ${option('rating', '등급 확인', leafKind)}
            ${option('char_in', '캐릭터 안 태그', leafKind)}
            ${option('char_on', '캐릭터 활성 여부', leafKind)}
          </select>
        </div>
        ${renderLeafFields(cond, pathAttr)}
      </div>`;
  }

  function renderLeafFields(cond, pathAttr) {
    const negated = cond.negated ? ' checked' : '';
    if (cond.leaf_kind === 'rating') {
      return `
        <div class="cond-node-row">
          <label>등급:</label>
          <select class="mod-select" data-cond-node-field="rating_value" data-cond-node-path="${pathAttr}">
            ${option('e', 'E', cond.rating_value)}
            ${option('q', 'Q', cond.rating_value)}
            ${option('s', 'S', cond.rating_value)}
            ${option('g', 'G', cond.rating_value)}
          </select>
          <select class="mod-select" data-cond-node-field="rating_source" data-cond-node-path="${pathAttr}">
            ${option('auto', '자동 판단', cond.rating_source)}
            ${option('row', '원본 행 값', cond.rating_source)}
            ${option('override', '강제 지정', cond.rating_source)}
            ${option('bayes', 'Bayes 결과', cond.rating_source)}
          </select>
        </div>
        <label class="mod-checkbox-item cond-inline-check">
          <input type="checkbox" data-cond-node-field="negated" data-cond-node-path="${pathAttr}"${negated}>
          <span class="mod-checkbox-label">NOT</span>
        </label>`;
    }
    if (cond.leaf_kind === 'char_in') {
      return `
        <div class="cond-node-row">
          <label>캐릭터:</label>
          <input class="mod-input" type="number" min="1" max="99" value="${escapeAttr(cond.char_index || 1)}" data-cond-node-field="char_index" data-cond-node-path="${pathAttr}">
        </div>
        <div class="cond-node-row">
          <label>찾을 태그:</label>
          <input class="mod-input" placeholder="예: blue_hair" value="${escapeAttr(cond.char_tag_value)}" data-cond-node-field="char_tag_value" data-cond-node-path="${pathAttr}">
          <select class="mod-select" data-cond-node-field="char_tag_modifier" data-cond-node-path="${pathAttr}">
            ${option('contains', '포함', cond.char_tag_modifier)}
            ${option('exact', '정확히 일치', cond.char_tag_modifier)}
            ${option('not_contains', '포함하지 않음', cond.char_tag_modifier)}
            ${option('not_exact', '정확히 일치하지 않음', cond.char_tag_modifier)}
          </select>
        </div>
        <label class="mod-checkbox-item cond-inline-check">
          <input type="checkbox" data-cond-node-field="negated" data-cond-node-path="${pathAttr}"${negated}>
          <span class="mod-checkbox-label">NOT</span>
        </label>`;
    }
    if (cond.leaf_kind === 'char_on') {
      return `
        <div class="cond-node-row">
          <label>캐릭터:</label>
          <input class="mod-input" type="number" min="1" max="99" value="${escapeAttr(cond.char_index || 1)}" data-cond-node-field="char_index" data-cond-node-path="${pathAttr}">
        </div>
        <label class="mod-checkbox-item cond-inline-check">
          <input type="checkbox" data-cond-node-field="negated" data-cond-node-path="${pathAttr}"${negated}>
          <span class="mod-checkbox-label">NOT</span>
        </label>`;
    }
    return `
      <div class="cond-node-row">
        <label>찾을 태그:</label>
        <input class="mod-input" placeholder="예: blue_hair" value="${escapeAttr(cond.tag_value)}" data-cond-node-field="tag_value" data-cond-node-path="${pathAttr}">
        <select class="mod-select" data-cond-node-field="tag_modifier" data-cond-node-path="${pathAttr}">
          ${option('contains', '포함', cond.tag_modifier)}
          ${option('exact', '정확히 일치', cond.tag_modifier)}
          ${option('not_contains', '포함하지 않음', cond.tag_modifier)}
          ${option('not_exact', '정확히 일치하지 않음', cond.tag_modifier)}
        </select>
      </div>`;
  }

  function renderActionPane(rule) {
    const dsl = rule ? serializeRule(rule) : '';
    const simulation = currentState?.simulation;
    const previewText = simulation ? formatSimulationText(simulation) : dsl;
    const previewTitle = simulation ? '시뮬레이션 결과' : 'DSL 미리보기 (선택한 규칙)';
    return `
      <section class="cond-pane cond-action-pane">
        <div class="cond-pane-title">이렇게 바꾸기</div>
        ${rule ? (rule.kind === 'raw' ? renderRawActionHelp() : renderActionEditor(rule.action)) : '<div class="cond-empty">규칙을 선택하세요.</div>'}
        <div class="cond-dsl-viewer">
          <div class="cond-pane-title small">${escHtml(previewTitle)}</div>
          <textarea id="condSelectedDsl" readonly spellcheck="false">${escHtml(previewText)}</textarea>
        </div>
      </section>`;
  }

  function formatSimulationText(result) {
    if (!result || typeof result !== 'object') return '';
    if (!result.ok) return `[시뮬레이션 실패]\n${safeText(result.error || '알 수 없는 오류')}`;
    const sample = result.sample || {};
    const lines = [
      `[시뮬레이션 성공] 매칭 ${Number(result.matched_count || 0)}개`,
    ];
    if (sample.rating || sample.character || sample.artist) {
      lines.push(`샘플: rating=${sample.rating || '-'} / character=${sample.character || '-'} / artist=${sample.artist || '-'}`);
    }
    if (sample.general_preview) lines.push(`general: ${sample.general_preview}`);
    const matched = Array.isArray(result.matched_rule_texts) ? result.matched_rule_texts : [];
    if (matched.length) {
      lines.push('', '[발동 규칙]');
      matched.forEach(rule => lines.push(String(rule)));
    }
    if (result.final_prompt) {
      lines.push('', '[최종 프롬프트]');
      lines.push(String(result.final_prompt));
    }
    return lines.join('\n');
  }

  function renderRawActionHelp() {
    return '<div class="cond-empty">고급 DSL 규칙은 왼쪽 직접 편집 영역에서 수정합니다.</div>';
  }

  function renderActionEditor(action) {
    const act = normalizeAction(action);
    return `
      <div class="cond-action-card">
        <div class="cond-node-row">
          <label>변경 방식:</label>
          <select class="mod-select" data-cond-action-field="kind">
            ${option('append_list', '태그 추가', act.kind)}
            ${option('append', '문장 끝에 붙이기', act.kind)}
            ${option('replace', '태그 교체', act.kind)}
            ${option('char_set', '캐릭터 사용 여부', act.kind)}
            ${option('char_append', '캐릭터 태그 추가', act.kind)}
            ${option('char_replace', '캐릭터 태그 교체', act.kind)}
          </select>
        </div>
        ${renderActionFields(act)}
      </div>`;
  }

  function parseTarget(target) {
    const value = safeText(target) || 'main';
    if (FIXED_TARGETS.has(value)) return {kind: value, index: 1, wildcard: false};
    const [kind, index] = value.split(':');
    if ((kind === 'char' || kind === 'uc') && index === '*') return {kind, index: 1, wildcard: true};
    if (kind === 'char' || kind === 'uc') return {kind, index: clampInt(index, 1, 99, 1), wildcard: false};
    return {kind: 'main', index: 1, wildcard: false};
  }

  function renderTargetFields(act) {
    const target = parseTarget(act.target);
    const showSlot = target.kind === 'char' || target.kind === 'uc';
    return `
      <div class="cond-node-row">
        <label>적용 위치:</label>
        <select class="mod-select" data-cond-action-field="target_kind">
          ${option('prefix', '선행고정 뒤', target.kind)}
          ${option('main', '메인 프롬프트', target.kind)}
          ${option('postfix', '후행고정 뒤', target.kind)}
          ${option('neg', '네거티브', target.kind)}
          ${option('char', '캐릭터 프롬프트', target.kind)}
          ${option('uc', '캐릭터 UC', target.kind)}
        </select>
      </div>
      ${showSlot ? `
        <div class="cond-node-row">
          <label>대상 슬롯:</label>
          <input class="mod-input" type="number" min="1" max="99" value="${escapeAttr(target.index)}" data-cond-action-field="target_index">
          <label class="mod-checkbox-item cond-inline-check">
            <input type="checkbox" data-cond-action-field="target_wildcard"${target.wildcard ? ' checked' : ''}>
            <span class="mod-checkbox-label">모든 활성 슬롯</span>
          </label>
        </div>` : ''}`;
  }

  function renderActionFields(act) {
    if (act.kind === 'append_list' || act.kind === 'append') {
      return `
        ${renderTargetFields(act)}
        ${renderTagEditor('tags', act.tags, '추가할 태그:', '태그 추가 (Enter)')}`;
    }
    if (act.kind === 'replace') {
      return `
        <div class="cond-node-row">
          <label>찾을 태그:</label>
          <input class="mod-input" value="${escapeAttr(act.old_tag)}" placeholder="예: __bad_tag__" data-cond-action-field="old_tag">
        </div>
        ${renderTagEditor('new_tags', act.new_tags, '바꿀 태그:', '교체 후 태그 추가')}`;
    }
    if (act.kind === 'char_set') {
      return `
        <div class="cond-node-row">
          <label>대상 캐릭터:</label>
          <input class="mod-input" type="number" min="1" max="99" value="${escapeAttr(act.char_index || 1)}" data-cond-action-field="char_index">
          <label>상태:</label>
          <select class="mod-select" data-cond-action-field="char_state">
            ${option('enabled', '사용', act.char_state)}
            ${option('disabled', '사용 안 함', act.char_state)}
          </select>
        </div>`;
    }
    if (act.kind === 'char_replace') {
      return `
        <div class="cond-node-row">
          <label>대상 캐릭터:</label>
          <input class="mod-input" type="number" min="1" max="99" value="${escapeAttr(act.char_index || 1)}" data-cond-action-field="char_index">
        </div>
        <div class="cond-node-row">
          <label>기존 태그:</label>
          <input class="mod-input" value="${escapeAttr(act.char_old_tag)}" data-cond-action-field="char_old_tag">
          <label>새 태그:</label>
          <input class="mod-input" value="${escapeAttr(act.char_new_tag)}" data-cond-action-field="char_new_tag">
        </div>`;
    }
    return `
      <div class="cond-node-row">
        <label>대상 캐릭터:</label>
        <input class="mod-input" type="number" min="1" max="99" value="${escapeAttr(act.char_index || 1)}" data-cond-action-field="char_index">
      </div>
      ${renderTagEditor('tags', act.tags, '추가할 태그:', '태그 추가 (Enter)')}`;
  }

  function renderTagEditor(field, tags, label, placeholder) {
    const chips = normalizeTags(tags).map((tag, index) => `
      <button type="button" class="cond-chip" data-cond-action="remove-tag" data-tag-field="${escapeAttr(field)}" data-tag-index="${index}">
        <span>${escHtml(tag)}</span><b>×</b>
      </button>`).join('');
    return `
      <div class="cond-tag-editor" data-tag-field="${escapeAttr(field)}">
        <label>${escHtml(label)}</label>
        <div class="cond-chip-list">
          ${chips}
          <input class="cond-chip-input" placeholder="${escapeAttr(placeholder)}" data-tag-input="${escapeAttr(field)}">
        </div>
      </div>`;
  }

  function getConditionNode(path) {
    const rule = selectedRule();
    if (!rule) return null;
    if (!path) return rule.condition;
    let node = rule.condition;
    for (const rawPart of path.split('.')) {
      const index = Number(rawPart);
      if (!node || node.kind !== 'group' || !node.children[index]) return null;
      node = node.children[index];
    }
    return node;
  }

  function setConditionNode(path, nextNode) {
    const rule = selectedRule();
    if (!rule) return;
    if (!path) {
      rule.condition = nextNode;
      return;
    }
    const parts = path.split('.');
    const last = Number(parts.pop());
    const parent = getConditionNode(parts.join('.'));
    if (parent?.kind === 'group' && parent.children[last]) {
      parent.children[last] = nextNode;
    }
  }

  function deleteConditionNode(path) {
    if (!path) return;
    const parts = path.split('.');
    const last = Number(parts.pop());
    const parent = getConditionNode(parts.join('.'));
    if (parent?.kind === 'group') parent.children.splice(last, 1);
  }

  function updateConditionField(target) {
    const path = target.dataset.condNodePath || '';
    const field = target.dataset.condNodeField;
    if (!field) return;
    const node = getConditionNode(path);
    if (!node) return;
    let value = target.type === 'checkbox' ? target.checked : target.value;
    if (field === 'kind') {
      setConditionNode(path, value === 'group' ? emptyCondition('group') : emptyCondition('tag'));
      markDirty();
      render(currentState);
      return;
    }
    if (field === 'leaf_kind') {
      setConditionNode(path, emptyCondition(value));
      markDirty();
      render(currentState);
      return;
    }
    if (field === 'char_index') value = clampInt(value, 1, 99, 1);
    node[field] = value;
    markDirty();
    if (target.tagName === 'SELECT' || target.type === 'checkbox' || target.type === 'number') render(currentState);
  }

  function composeTargetFromAction(action) {
    const kind = action._target_kind || parseTarget(action.target).kind;
    if (FIXED_TARGETS.has(kind)) return kind;
    if (kind === 'char' || kind === 'uc') {
      if (action._target_wildcard) return `${kind}:*`;
      return `${kind}:${clampInt(action._target_index, 1, 99, 1)}`;
    }
    return 'main';
  }

  function updateActionField(target) {
    const rule = selectedRule();
    if (!rule || rule.kind === 'raw') return;
    const field = target.dataset.condActionField;
    if (!field) return;
    let action = rule.action = normalizeAction(rule.action);
    let value = target.type === 'checkbox' ? target.checked : target.value;
    if (field === 'kind') {
      rule.action = emptyAction(value);
      markDirty();
      render(currentState);
      return;
    }
    if (field === 'target_kind') {
      const parsed = parseTarget(action.target);
      action._target_kind = value;
      action._target_index = parsed.index;
      action._target_wildcard = parsed.wildcard;
      action.target = composeTargetFromAction(action);
      markDirty();
      render(currentState);
      return;
    }
    if (field === 'target_index' || field === 'target_wildcard') {
      const parsed = parseTarget(action.target);
      action._target_kind = parsed.kind;
      action._target_index = field === 'target_index' ? clampInt(value, 1, 99, 1) : parsed.index;
      action._target_wildcard = field === 'target_wildcard' ? value : parsed.wildcard;
      action.target = composeTargetFromAction(action);
      delete action._target_kind;
      delete action._target_index;
      delete action._target_wildcard;
      markDirty();
      if (field === 'target_wildcard') render(currentState);
      return;
    }
    if (field === 'char_index') value = clampInt(value, 1, 99, 1);
    action[field] = value;
    markDirty();
    if (target.tagName === 'SELECT' || target.type === 'checkbox' || target.type === 'number') render(currentState);
  }

  function addTag(field, value) {
    const rule = selectedRule();
    if (!rule || rule.kind === 'raw') return;
    const clean = safeText(value).trim();
    if (!clean) return;
    const action = rule.action = normalizeAction(rule.action);
    const tags = normalizeTags(action[field]);
    if (!tags.includes(clean)) tags.push(clean);
    action[field] = tags;
    markDirty();
    render(currentState);
  }

  function removeTag(field, index) {
    const rule = selectedRule();
    if (!rule || rule.kind === 'raw') return;
    const action = rule.action = normalizeAction(rule.action);
    const tags = normalizeTags(action[field]);
    tags.splice(Number(index), 1);
    action[field] = tags;
    markDirty();
    render(currentState);
  }

  function handleClick(event) {
    const root = event.target.closest('.cond-root');
    if (!root || !moduleBody.contains(root)) return;
    const modeButton = event.target.closest('[data-cond-mode]');
    if (modeButton) {
      const mode = normalizeMode(modeButton.dataset.condMode);
      if (!currentState) return;
      currentState.editor_mode = mode;
      presetPopoverOpen = false;
      sendModuleParam('conditional_prompt', 'editor_mode', mode);
      render(currentState);
      return;
    }
    const actionEl = event.target.closest('[data-cond-action]');
    if (!actionEl) return;
    const action = actionEl.dataset.condAction;
    if (action === 'toggle-syntax') {
      actionEl.classList.toggle('open');
      actionEl.nextElementSibling?.classList.toggle('collapsed');
    } else if (action === 'toggle-preset-popover') {
      presetPopoverOpen = !presetPopoverOpen;
      renderWithScrollRestore(['.cond-rule-list', '.cond-condition-scroll']);
    } else if (action === 'select-rule') {
      selectedRuleId = actionEl.dataset.ruleId || '';
      renderWithScrollRestore(['.cond-rule-list']);
    } else if (action === 'add-rule') {
      const book = rulebook();
      const rule = emptyRule(book.rules.length);
      book.rules.push(rule);
      renumberPriorities();
      selectedRuleId = rule.id;
      markDirty();
      render(currentState);
    } else if (action === 'delete-rule') {
      const index = selectedRuleIndex();
      if (index >= 0) {
        rulebook().rules.splice(index, 1);
        renumberPriorities();
        selectedRuleId = rulebook().rules[Math.min(index, rulebook().rules.length - 1)]?.id || null;
        markDirty();
        render(currentState);
      }
    } else if (action === 'toggle-rule') {
      const rule = selectedRule();
      if (rule) {
        rule.enabled = !rule.enabled;
        markDirty();
        renderWithScrollRestore(['.cond-rule-list']);
      }
    } else if (action === 'move-rule-up' || action === 'move-rule-down') {
      const book = rulebook();
      const index = selectedRuleIndex();
      const next = action === 'move-rule-up' ? index - 1 : index + 1;
      if (index >= 0 && next >= 0 && next < book.rules.length) {
        const [rule] = book.rules.splice(index, 1);
        book.rules.splice(next, 0, rule);
        renumberPriorities();
        markDirty();
        render(currentState);
      }
    } else if (action === 'delete-condition') {
      deleteConditionNode(actionEl.dataset.condNodePath || '');
      markDirty();
      render(currentState);
    } else if (action === 'add-condition-leaf' || action === 'add-condition-group') {
      const path = actionEl.dataset.condNodePath || '';
      const node = getConditionNode(path);
      if (node?.kind === 'group') {
        node.children.push(action === 'add-condition-group' ? emptyCondition('group') : emptyCondition('tag'));
        markDirty();
        render(currentState);
      }
    } else if (action === 'remove-tag') {
      removeTag(actionEl.dataset.tagField, actionEl.dataset.tagIndex);
    } else if (action === 'apply-book') {
      applyBook();
    } else if (action === 'reload-state') {
      if (typeof globalThis.requestModuleState === 'function') {
        globalThis.requestModuleState('conditional_prompt');
      }
    } else if (action === 'clear-simulation') {
      if (currentState) {
        currentState.simulation = null;
        renderWithScrollRestore(['.cond-rule-list', '.cond-condition-scroll']);
      }
    } else if (action === 'test-rules') {
      if (currentState?.editor_mode === 'v2') {
        sendModuleParam('conditional_prompt', 'simulate_v2', JSON.stringify({book: currentBookPayload()}));
      } else {
        sendModuleParam('conditional_prompt', 'test', '1');
      }
    } else if (action === 'save-preset') {
      savePreset();
    } else if (action === 'delete-preset') {
      const select = document.getElementById('condPresetSelect');
      const name = safeText(select?.value).trim();
      if (name) sendModuleParam('conditional_prompt', 'preset_delete', name);
    } else if (action === 'load-selected-preset') {
      const select = document.getElementById('condPresetSelect');
      const name = safeText(select?.value).trim();
      if (name) {
        presetPopoverOpen = false;
        sendModuleParam('conditional_prompt', 'preset_load', name);
      }
    } else if (action === 'load-preset') {
      const name = safeText(actionEl.dataset.presetName).trim();
      if (name) {
        presetPopoverOpen = false;
        sendModuleParam('conditional_prompt', 'preset_load', name);
      }
    }
  }

  function renderWithScrollRestore(selectors) {
    const positions = selectors.map(selector => {
      const element = moduleBody.querySelector(selector);
      return {selector, top: element ? element.scrollTop : 0};
    });
    render(currentState);
    positions.forEach(({selector, top}) => {
      const element = moduleBody.querySelector(selector);
      if (element) element.scrollTop = top;
    });
  }

  function handleInput(event) {
    const target = event.target;
    if (!target.closest?.('.cond-root')) return;
    if (target.dataset.condRuleField === 'raw_dsl') {
      const rule = selectedRule();
      if (rule) {
        rule.raw_dsl = target.value;
        markDirty();
      }
      return;
    }
    if (target.dataset.condNodeField) {
      updateConditionField(target);
      return;
    }
    if (target.dataset.condActionField) {
      updateActionField(target);
      return;
    }
    if (target.dataset.condEngine) {
      const book = rulebook();
      const key = target.dataset.condEngine;
      if (key === 'max_passes') book.engine_options.max_passes = clampInt(target.value, 1, 20, 1);
      markDirty();
    }
  }

  function handleChange(event) {
    const target = event.target;
    if (!target.closest?.('.cond-root')) return;
    if (target.dataset.condGlobal === 'enabled') {
      sendModuleParam('conditional_prompt', 'enabled', String(target.checked));
      if (currentState) currentState.enabled = target.checked;
      return;
    }
    if (target.dataset.condEngine === 'stop_on_match') {
      rulebook().engine_options.stop_on_match = !!target.checked;
      markDirty();
      return;
    }
    if (target.dataset.condEngine === 'max_passes') {
      rulebook().engine_options.max_passes = clampInt(target.value, 1, 20, 1);
      markDirty();
      return;
    }
    if (target.dataset.condNodeField) {
      updateConditionField(target);
      return;
    }
    if (target.dataset.condActionField) {
      updateActionField(target);
    }
  }

  function handleKeydown(event) {
    const target = event.target;
    if (!target?.dataset?.tagInput) return;
    if (event.key !== 'Enter' && event.key !== ',') return;
    event.preventDefault();
    addTag(target.dataset.tagInput, target.value);
  }

  function bindEvents() {
    if (bound || !moduleBody) return;
    bound = true;
    moduleBody.addEventListener('click', handleClick);
    moduleBody.addEventListener('input', handleInput);
    moduleBody.addEventListener('change', handleChange);
    moduleBody.addEventListener('keydown', handleKeydown);
  }

  function render(state) {
    bindEvents();
    const preserveDirty = state === currentState;
    currentState = normalizeState(state);
    if (!preserveDirty) dirty = Boolean(currentState.local_dirty);
    if (currentState.editor_mode === 'v2') renderV2(currentState);
    else renderLegacy(currentState);
  }

  function collectState(baseState = {}) {
    if (!currentState) return baseState;
    const state = {...baseState, ...currentState};
    if (currentState.editor_mode === 'v2') {
      const book = currentBookPayload();
      state.rules_v2_book = book;
      state.rules_v2 = serializeRulebook(book);
      state.rules = state.rules_v2;
      state.active_rules = state.rules_v2;
      state.engine_options = normalizeEngineOptions(book.engine_options);
    } else {
      const mode = document.getElementById('condEditorMode');
      const rules = document.getElementById('condRulesInput');
      if (mode) state.editor_mode = mode.value === 'v2' ? 'v2' : 'legacy';
      if (rules) {
        const key = rules.dataset.condRuleKey || 'rules_legacy';
        state[key] = rules.value;
        state.rules_legacy = rules.value;
        state.rules = rules.value;
        state.active_rules = rules.value;
      }
      const maxPasses = document.getElementById('condMaxPasses');
      const stopOnMatch = document.getElementById('condStopOnMatch');
      state.engine_options = normalizeEngineOptions({
        max_passes: maxPasses ? maxPasses.value : state.engine_options?.max_passes,
        stop_on_match: stopOnMatch ? stopOnMatch.checked : state.engine_options?.stop_on_match,
      });
    }
    return state;
  }

  return {
    formatLog,
    formatRules,
    onRulesInput,
    syncScroll,
    render,
    collectState,
  };
}
