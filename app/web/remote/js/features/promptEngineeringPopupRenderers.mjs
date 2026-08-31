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
  saveCategoryFilter,
  bindTagHoverInfo,
  panels,
}) {
  const CATEGORY_EDITOR_INPUT_CLASS = 'mod-debug-cat-input';
  const CATEGORY_SEARCH_CLASS = 'mod-debug-cat-search';
  const CATEGORY_TAGS_ENDPOINT = '/api/prompt-engineering/category-tags';
  const CATEGORY_PAGE_LIMIT = 200;
  // 사전 클릭-제외가 실제 태그 단위로 의미가 없는(부분일치 색상 단어) 카테고리.
  // (비어 있음) 색상 카테고리도 이제 클릭-제외 가능 — 백엔드가 색상 '단어' exclude 를
  // 패턴 보호로 처리한다(exclude 'blue' = blue* 부분일치 제거 전체 보호).
  const DICT_CLICK_DISABLED_CATEGORIES = new Set();

  // 열려 있는 카테고리 편집기의 전체 작업 상태 — module_state push 로 인한 재렌더
  // 후에도 이 상태로 편집기를 복원해 미저장 선택이 절대 소실되지 않게 한다(한 번에
  // 하나만 열림). workingExclude 는 정규화(lower) 집합, excludeDisplay 는 정규화→원형.
  let editorState = null;
  let searchDebounceTimer = null;
  let savedFlashUntil = 0;   // "저장됨" 피드백이 재렌더에도 잠깐 유지되도록 하는 만료 타임스탬프

  function parseTagInput(value) {
    return String(value || '')
      .split(',')
      .map(tag => tag.trim())
      .filter(Boolean);
  }

  function normTag(value) {
    return String(value == null ? '' : value).trim().toLowerCase();
  }

  function cssEscape(value) {
    if (typeof CSS !== 'undefined' && CSS && typeof CSS.escape === 'function') return CSS.escape(value);
    return String(value).replace(/["\\\]]/g, '\\$&');
  }

  // Auto-Hide 묶음 문법 미러(백엔드 compile_hide_pattern 과 동일한 관대한 일반화 규칙).
  // 감싸면(개수 무관) 포함 / 앞에만 " x" 경계 / 뒤에만 포함 / 중간 밑줄=공백 / 심 비면 null.
  // 반환 null = plain(정확일치), 아니면 (keyword)->bool 포함-매치 predicate.
  function compileHidePattern(item) {
    if (typeof item !== 'string') return null;
    const strippedLead = item.replace(/^_+/, '');
    const lead = item.length - strippedLead.length;
    const core = strippedLead.replace(/_+$/, '');
    const trail = strippedLead.length - core.length;
    if (lead === 0 && trail === 0) return null;
    if (!core.trim()) return null;               // 밑줄만("____") -> 전체 매치 폭주 차단
    let needle = core.replace(/_/g, ' ');
    if (lead > 0 && trail === 0) needle = ' ' + needle;
    // lower만(trim 금지) — 앞 경계 공백을 needle 안에 유지.
    const n = needle.toLowerCase();
    if (!n.trim()) return null;
    return (keyword) => String(keyword == null ? '' : keyword).toLowerCase().includes(n);
  }

  function isPatternTerm(item) {
    return compileHidePattern(item) !== null;
  }

  // 항목 리스트를 {exact:Set(정규화), preds:[predicate]} 매처로 컴파일(1회).
  function buildExcludeMatcher(entries) {
    const exact = new Set();
    const preds = [];
    (entries || []).forEach(entry => {
      const text = String(entry || '');
      if (!text.trim()) return;
      const pred = compileHidePattern(text);
      if (pred) preds.push(pred);
      else exact.add(normTag(text));
    });
    return { exact, preds };
  }

  function matcherHas(matcher, tag) {
    if (!matcher) return false;
    if (matcher.exact.has(normTag(tag))) return true;
    return matcher.preds.some(pred => pred(tag));
  }

  function newEditorState(key, categoryFilters) {
    const entry = (categoryFilters && typeof categoryFilters === 'object' ? categoryFilters[key] : null) || {};
    const workingExclude = new Set();
    const excludeDisplay = new Map();
    (Array.isArray(entry.exclude) ? entry.exclude : []).forEach(tag => {
      const n = normTag(tag);
      if (!n) return;
      workingExclude.add(n);
      if (!excludeDisplay.has(n)) excludeDisplay.set(n, String(tag));
    });
    const include = Array.isArray(entry.include) ? entry.include.join(', ') : '';
    const hide = Array.isArray(entry.hide) ? entry.hide.join(', ') : '';
    return {
      key,
      q: '',
      tags: [],
      infoMap: {},       // 태그 → {desc, count, group} (autocomplete 설명 툴팁용, 페이지 누적)
      total: 0,
      fullTotal: null,
      loaded: 0,
      workingExclude,
      excludeDisplay,
      workingInclude: include,
      workingHide: hide,
      dirty: false,
      loading: false,
      error: null,
      supported: null,   // null=아직 미조회, true/false=조회 결과
      reason: '',
      _excludeMatcher: null,   // workingExclude 변경 시 재빌드하는 매처 캐시(패턴 포함)
    };
  }

  // workingExclude(정확일치+패턴 문자열)로부터 매처 재빌드/조회. 매 chip 재컴파일 방지.
  function rebuildExcludeMatcher() {
    if (!editorState) return;
    const entries = [...editorState.workingExclude].map(n => editorState.excludeDisplay.get(n) || n);
    editorState._excludeMatcher = buildExcludeMatcher(entries);
  }

  function ensureExcludeMatcher() {
    if (editorState && !editorState._excludeMatcher) rebuildExcludeMatcher();
    return (editorState && editorState._excludeMatcher) || { exact: new Set(), preds: [] };
  }

  function isWorkingExcluded(tag) {
    return matcherHas(ensureExcludeMatcher(), tag);
  }

  // 카테고리별 exclude 매처: 편집 중이면 workingExclude(미저장 포함), 아니면 저장된 값.
  function excludeMatcherFor(key, categoryFilters) {
    if (editorState && editorState.key === key) return ensureExcludeMatcher();
    const arr = (categoryFilters && categoryFilters[key] && Array.isArray(categoryFilters[key].exclude))
      ? categoryFilters[key].exclude : [];
    return buildExcludeMatcher(arr);
  }
  const OLLAMA_BOOST_GUIDE =
    '자연어 가중치 — 보강된 자연어 프롬프트에 부여할 가중치입니다. '
    + 'NAI는 {v}::..:: , 로컬(WEBUI/COMFYUI)은 (..:v) 구문으로 적용됩니다.\\n\\n'
    + 'Effort — 보강 자연어의 길이·창의성. 간결(concise) / 표준(standard) / 풍부(rich).\\n\\n'
    + 'Style 확장 — 향·재질·광원 같은 감각적 보강을 태그에 직접 없어도 허용할지 선택합니다. '
    + '미입력 대상 색상과 눈색은 항상 차단됩니다.\\n\\n'
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

  // 카테고리 라운드에서 제거된 태그를 클릭 가능한 chip 으로 — "방금 지워진 이 태그를
  // 앞으로 지우지 마"의 최단 경로(클릭=편집기 열림 + 제외 토글).
  function renderRemovedChips(key, removed, categoryFilters) {
    const matcher = excludeMatcherFor(key, categoryFilters);
    const chips = removed.map(tag => {
      const excluded = matcherHas(matcher, tag);
      return `<button type="button" class="mod-debug-removed-chip${excluded ? ' is-excluded' : ''}"`
        + ` data-removed-cat="${escHtml(key)}" data-removed-tag="${escHtml(tag)}"`
        + ` title="클릭: 이 카테고리 필터에서 제외(보호)">${escHtml(tag)}</button>`;
    }).join('');
    return `<div class="mod-debug-removed-chips" data-removed-catbox="${escHtml(key)}">${chips}</div>`;
  }

  // 편집기 컨테이너는 빈 placeholder — 내용은 editorState 로부터 renderEditorInto() 가
  // 채운다(단일 소스: 재렌더에도 미저장 상태 보존).
  function renderCategoryEditorShell(key) {
    return `<div class="mod-debug-cat-editor" data-cat-editor="${escHtml(key)}" hidden></div>`;
  }

  // 스냅샷 없이도 설정 행을 그릴 수 있는 카테고리 정의(백엔드 filter_log 이름과 동일).
  const CATEGORY_ROUNDS = [
    ['remove_character_features', '캐릭터 특징'],
    ['remove_clothes', '의류'],
    ['remove_clothing_event', '의상 이벤트'],
    ['remove_color', '색상'],
    ['remove_location_and_background_color', '위치/배경'],
    ['remove_expression', '표정'],
    ['remove_pose_action', '포즈/동작'],
    ['remove_meta_tags', '메타'],
    ['remove_object_tags', '사물'],
    ['remove_noise_tags', '노이즈 태그'],
  ];

  function renderDebugSnapshot(snapshot, categoryFilters = {}, preprocessing = {}) {
    const sourceInfo = snapshot.source_info || {};
    let filterLog = Array.isArray(snapshot.filter_log) ? snapshot.filter_log : [];
    const implicationInfo = Array.isArray(snapshot.implication_info) ? snapshot.implication_info : [];
    const e621Info = snapshot.e621_info || {};
    const originalCount = Number(snapshot.original_count || 0);
    const remainingCount = Number(snapshot.remaining_count || 0);
    const hasDebugData = filterLog.length || implicationInfo.length || (e621Info.results || []).length || Object.values(sourceInfo).some(Boolean);

    // 첫 생성 전에도 설정은 가능해야 한다(Codex 리뷰 반영) — 미리보기 데이터만 비운 채
    // 고정 카테고리 행(⚙ 포함)을 합성 렌더. enabled 는 현재 preprocessing 체크 상태.
    if (!filterLog.length) {
      filterLog = CATEGORY_ROUNDS.map(([key, name]) => ({
        key, name, enabled: !!(preprocessing || {})[key], removed: [],
      }));
    }
    const emptyNote = hasDebugData
      ? ''
      : '<div class="mod-debug-empty">미리보기 데이터 없음 — 프롬프트를 한 번 생성하면 제거 내역이 표시됩니다. 필터 설정(⚙)은 지금도 가능합니다.</div>';

    const sourceRows = Object.entries(sourceInfo)
      .filter(([, value]) => value != null && String(value).trim() !== '')
      .map(([key, value]) => `<div class="mod-debug-meta"><span>${escHtml(key)}</span><strong>${escHtml(String(value))}</strong></div>`)
      .join('');

    const filterRounds = filterLog.map(entry => {
      const removed = Array.isArray(entry.removed) ? entry.removed : [];
      const status = !entry.enabled ? 'OFF' : (removed.length ? `ON · ${removed.length} removed` : 'ON');
      const catKey = String(entry.key || '');
      // Auto Hide(자체 문법)는 카테고리 오버라이드 대상이 아니므로 ⚙ 미노출.
      // Auto Hide(자체 문법)와 개별 숨김(여러 카테고리가 섞인 합계)은 한 카테고리의
    // 편집기로 열 수 없다 - ⚙ 를 달면 어느 서랍을 여는지 말할 수 없다.
    const editable = catKey && catKey !== 'auto_hide' && catKey !== 'category_hide';
      const isOpen = editable && editorState && editorState.key === catKey;
      const gear = editable
        ? `<button type="button" class="mod-debug-gear${isOpen ? ' is-open' : ''}" data-cat-gear="${escHtml(catKey)}"`
          + ` data-naia-guide="${escHtml(categoryGuide(catKey))}" aria-label="필터 예외/추가 태그 설정">⚙</button>`
        : '';
      // 카테고리 라운드는 제거된 태그를 클릭 chip 으로(빠른 제외), 나머지는 pre 유지.
      const removedBlock = removed.length
        ? (editable
            ? renderRemovedChips(catKey, removed, categoryFilters)
            : `<pre class="mod-debug-block">${escHtml(removed.join(', '))}</pre>`)
        : '';
      const editor = editable ? renderCategoryEditorShell(catKey) : '';
      return `
      <div class="mod-debug-round${isOpen ? ' is-open' : ''}"${editable ? ` data-cat-round="${escHtml(catKey)}"` : ''}>
        <div class="mod-debug-round-title">
          <span class="mod-debug-round-name">${escHtml(entry.name || 'Round')}</span>
          <span class="mod-debug-round-meta"><span>${status}</span>${gear}</span>
        </div>
        ${removedBlock}
        ${editor}
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
    ${emptyNote}
    ${hasDebugData ? `<div class="mod-debug-summary">Original ${originalCount} → Remaining ${remainingCount} · Removed ${Math.max(0, originalCount - remainingCount)}</div>` : ''}
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
    const allowScentStyle = boost.allow_scent_style !== false;
    const allowMaterialStyle = boost.allow_material_style !== false;
    const allowLightStyle = boost.allow_light_style !== false;
    const emphasizeFraming = !!boost.emphasize_framing;
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
      <div class="mod-section-label">Style 확장</div>
      <div class="mod-checkbox-grid">
        <label class="mod-checkbox-item">
          <input type="checkbox" id="modOllamaBoostAllowScent"${allowScentStyle ? ' checked' : ''}>
          <span class="mod-checkbox-label">향·공기감 허용</span>
        </label>
        <label class="mod-checkbox-item">
          <input type="checkbox" id="modOllamaBoostAllowMaterial"${allowMaterialStyle ? ' checked' : ''}>
          <span class="mod-checkbox-label">재질·텍스처 허용</span>
        </label>
        <label class="mod-checkbox-item">
          <input type="checkbox" id="modOllamaBoostAllowLight"${allowLightStyle ? ' checked' : ''}>
          <span class="mod-checkbox-label">광원·색조 허용</span>
        </label>
        <label class="mod-checkbox-item">
          <input type="checkbox" id="modOllamaBoostEmphasizeFraming"${emphasizeFraming ? ' checked' : ''}>
          <span class="mod-checkbox-label">구도(close-up) 강조</span>
        </label>
      </div>
      <div class="mod-boost-caption">미입력 대상 색상과 눈색은 항상 차단합니다. 광원 색조·향·재질은 태그에 직접 없어도 스타일 보강으로 허용할지 선택합니다. <b>구도(close-up) 강조</b>: 자연어 본문이 카메라 샷·앵글(close-up·low angle)을 직접 묘사하도록 허용해 기존 사양에 가까운 프레이밍을 냅니다(기본 OFF=다양성 우선).</div>
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

  // ===== 카테고리 편집기 엔진 (editorState 단일 소스) ===== //
  // 설명문은 UI 에서 빼고 ⚙ 버튼의 data-naia-guide 툴팁으로 옮긴다(텍스트 다이어트).
  const CATEGORY_GUIDES = {
    default: '제외 태그: 이 카테고리가 ON이어도 제거되지 않습니다(보호).\n추가 제거: 이 카테고리가 ON일 때 함께 제거됩니다.\n개별 숨김: 이 카테고리가 OFF여도 항상 제거됩니다 (프롬프트 우클릭 > 자동 숨김).\n사전 태그를 클릭하거나, 미리보기의 제거된 태그를 클릭해 제외하세요.',
    remove_color: '색상은 단어 부분일치로 제거됩니다.\n사전의 색상 단어를 제외하면 그 색상 전체가 보호됩니다 (예: blue → blue hair, blue dress 유지).\n미리보기의 제거된 태그를 클릭하면 그 태그 하나만 보호됩니다.\n추가 제거: 이 카테고리가 ON일 때 함께 제거됩니다.',
    remove_noise_tags: '빈도 기반이라 사전 목록이 없습니다.\n미리보기의 제거된 태그를 클릭해 제외하거나, 추가 제거 태그를 직접 입력하세요.',
  };

  // Auto-Hide 묶음 문법을 exclude/추가 제거/검색에 그대로 쓸 수 있다(텍스트 다이어트: 상세는 여기 툴팁).
  const PATTERN_GUIDE_LINE = '\n\n묶음 문법(밑줄 개수 무관): __x__·_x_ = x 포함 / _x·__x = " x" 앞 단어 경계 / x_ = x 포함 / plain = 정확일치. 중간 밑줄은 공백 취급(blue_eyes = "blue eyes"). (~ 는 미지원=정확일치 취급)';

  function categoryGuide(key) {
    return (CATEGORY_GUIDES[key] || CATEGORY_GUIDES.default) + PATTERN_GUIDE_LINE;
  }

  function fmtCount(value) {
    const n = Number(value || 0);
    return Number.isFinite(n) ? n.toLocaleString() : '0';
  }

  function editorContainer() {
    const body = getBody(panels.debug);
    if (!body || !editorState) return null;
    return body.querySelector(`[data-cat-editor="${cssEscape(editorState.key)}"]`);
  }

  function refreshRemovedChipHighlights(key) {
    const body = getBody(panels.debug);
    if (!body || !editorState || editorState.key !== key) return;
    const box = body.querySelector(`[data-removed-catbox="${cssEscape(key)}"]`);
    if (!box) return;
    const matcher = ensureExcludeMatcher();
    box.querySelectorAll('[data-removed-tag]').forEach(btn => {
      btn.classList.toggle('is-excluded', matcherHas(matcher, btn.dataset.removedTag || ''));
    });
  }

  function isSavedFlashing() {
    return Date.now() < savedFlashUntil;
  }

  function saveButtonLabel(dirty) {
    if (dirty) return '저장 *';
    return isSavedFlashing() ? '저장됨' : '저장';
  }

  function updateSaveDirty() {
    const container = editorContainer();
    if (!container || !editorState) return;
    const btn = container.querySelector('[data-cat-save]');
    if (!btn) return;
    const dirty = !!editorState.dirty;
    btn.classList.toggle('is-dirty', dirty);
    btn.classList.toggle('is-saved', !dirty && isSavedFlashing());
    btn.textContent = saveButtonLabel(dirty);
  }

  function flashSaved() {
    savedFlashUntil = Date.now() + 1400;
    updateSaveDirty();
    setTimeout(updateSaveDirty, 1450);
  }

  function updateSelected() {
    const container = editorContainer();
    if (!container || !editorState) return;
    const items = [...editorState.workingExclude];
    const badge = container.querySelector('.mod-debug-cat-selcount');
    if (badge) badge.textContent = String(items.length);
    const sel = container.querySelector('.mod-debug-cat-selected');
    if (!sel) return;
    if (!items.length) {
      sel.innerHTML = '<span class="mod-debug-cat-selected-empty">없음</span>';
      return;
    }
    sel.innerHTML = items.map(n => {
      const disp = editorState.excludeDisplay.get(n) || n;
      const pat = isPatternTerm(disp);
      return `<span class="mod-debug-cat-selchip${pat ? ' is-pattern' : ''}"${pat ? ' title="패턴: 포함 일치"' : ''}>${escHtml(disp)}`
        + `<button type="button" class="mod-debug-cat-selx" data-sel-remove="${escHtml(n)}" title="제외 해제">×</button></span>`;
    }).join('');
    sel.querySelectorAll('[data-sel-remove]').forEach(btn => {
      btn.addEventListener('click', () => removeExclude(btn.dataset.selRemove || ''));
    });
  }

  // 검색어가 패턴이면 dict 위에 액션 행 — "제외에 추가 / 추가 제거에 추가"(N개 일치).
  function updatePatternRow() {
    const container = editorContainer();
    if (!container || !editorState) return;
    const row = container.querySelector('.mod-debug-cat-patternrow');
    if (!row) return;
    const q = editorState.q;
    if (!q || !isPatternTerm(q)) {
      row.hidden = true;
      row.innerHTML = '';
      return;
    }
    row.hidden = false;
    const already = editorState.workingExclude.has(normTag(q));
    row.innerHTML = `
      <span class="mod-debug-cat-patterninfo"><span class="mod-debug-cat-patterntag">${escHtml(q)}</span> · ${fmtCount(editorState.total)}개 일치</span>
      <span class="mod-debug-cat-patternactions">
        <button type="button" class="mod-debug-cat-patternbtn" data-pattern-exclude${already ? ' disabled' : ''}>${already ? '제외됨' : '제외에 추가'}</button>
        <button type="button" class="mod-debug-cat-patternbtn" data-pattern-include>추가 제거에 추가</button>
      </span>`;
    const exBtn = row.querySelector('[data-pattern-exclude]');
    if (exBtn && !already) exBtn.addEventListener('click', () => addPatternToExclude(q));
    const inBtn = row.querySelector('[data-pattern-include]');
    if (inBtn) inBtn.addEventListener('click', () => addPatternToInclude(q));
  }

  function updateDict() {
    const container = editorContainer();
    if (!container || !editorState) return;
    const count = container.querySelector('.mod-debug-cat-count');
    if (count) {
      count.textContent = (editorState.fullTotal != null && editorState.q)
        ? `${fmtCount(editorState.total)} / ${fmtCount(editorState.fullTotal)}`
        : fmtCount(editorState.total);
    }
    updatePatternRow();
    const dict = container.querySelector('.mod-debug-cat-dict');
    if (!dict) return;
    if (editorState.error) {
      dict.innerHTML = `<div class="mod-debug-cat-error">사전 로드 실패: ${escHtml(editorState.error)} `
        + '<button type="button" class="mod-btn-secondary mod-btn-compact" data-cat-retry>재시도</button></div>';
      const retry = dict.querySelector('[data-cat-retry]');
      if (retry) retry.addEventListener('click', () => fetchCategoryTags(true));
      return;
    }
    if (editorState.loading && editorState.tags.length === 0) {
      dict.innerHTML = '<div class="mod-debug-cat-loading">불러오는 중...</div>';
      return;
    }
    const disabled = DICT_CLICK_DISABLED_CATEGORIES.has(editorState.key);
    const infoMap = editorState.infoMap || {};
    const matcher = ensureExcludeMatcher();
    const chipsHtml = editorState.tags.map(tag => {
      const excluded = matcherHas(matcher, tag);
      // autocomplete 와 동일한 호버 설명 툴팁 — desc 없이 count/group 만 있어도 부여
      // (설명 미등재 태그도 최소 빈도는 보여준다).
      const info = infoMap[tag];
      let tooltipAttrs = '';
      if (info && (info.desc || Number(info.count || 0) > 0 || info.group)) {
        tooltipAttrs = ` data-tooltip-title="${escHtml(tag)}"`;
        if (info.desc) tooltipAttrs += ` data-tooltip-desc="${escHtml(info.desc)}"`;
        const cnt = Number(info.count || 0);
        if (cnt > 0) tooltipAttrs += ` data-tooltip-count="${escHtml(cnt.toLocaleString())}"`;
        if (info.group) tooltipAttrs += ` data-tooltip-group="${escHtml(info.group)}"`;
      }
      return `<button type="button" class="mod-debug-tag-chip${excluded ? ' is-excluded' : ''}${disabled ? ' is-disabled' : ''}"`
        + `${disabled ? ' disabled' : ''} data-dict-tag="${escHtml(tag)}"${tooltipAttrs}>${escHtml(tag)}</button>`;
    }).join('');
    const remaining = editorState.total - editorState.loaded;
    const more = remaining > 0
      ? `<button type="button" class="mod-debug-cat-more" data-cat-more>더 보기 +${Math.min(CATEGORY_PAGE_LIMIT, remaining)}</button>`
      : '';
    dict.innerHTML = (chipsHtml + more) || '<div class="mod-debug-cat-empty">일치하는 사전 태그가 없습니다.</div>';
    if (!disabled) {
      dict.querySelectorAll('[data-dict-tag]').forEach(btn => {
        btn.addEventListener('click', () => toggleExclude(btn.dataset.dictTag || ''));
      });
    }
    const moreBtn = dict.querySelector('[data-cat-more]');
    if (moreBtn) {
      moreBtn.addEventListener('click', () => {
        if (editorState && editorState.loading) return;   // 연타 방지(같은 offset 중복 요청)
        fetchCategoryTags(false);
      });
    }
    if (typeof bindTagHoverInfo === 'function') {
      bindTagHoverInfo(dict, '.mod-debug-tag-chip[data-tooltip-title]');
    }
  }

  function toggleExclude(tag) {
    if (!editorState) return;
    const n = normTag(tag);
    if (!n) return;
    if (editorState.workingExclude.has(n)) {
      editorState.workingExclude.delete(n);
    } else {
      editorState.workingExclude.add(n);
      if (!editorState.excludeDisplay.has(n)) editorState.excludeDisplay.set(n, String(tag));
    }
    editorState.dirty = true;
    rebuildExcludeMatcher();
    updateDict();
    updateSelected();
    updateSaveDirty();
    refreshRemovedChipHighlights(editorState.key);
  }

  // 검색 패턴 문자열 자체를 exclude/include 에 추가(원형 보존).
  function addPatternToExclude(patternStr) {
    if (!editorState) return;
    const n = normTag(patternStr);
    if (!n) return;
    if (!editorState.workingExclude.has(n)) {
      editorState.workingExclude.add(n);
      editorState.excludeDisplay.set(n, String(patternStr));
    }
    editorState.dirty = true;
    rebuildExcludeMatcher();
    updateDict();
    updateSelected();
    updateSaveDirty();
    refreshRemovedChipHighlights(editorState.key);
  }

  function addPatternToInclude(patternStr) {
    if (!editorState) return;
    const term = String(patternStr || '').trim();
    if (!term) return;
    const current = parseTagInput(editorState.workingInclude);
    if (!current.map(normTag).includes(normTag(term))) current.push(term);
    editorState.workingInclude = current.join(', ');
    editorState.dirty = true;
    const container = editorContainer();
    const ta = container ? container.querySelector('[data-cat-include]') : null;
    if (ta) ta.value = editorState.workingInclude;
    updateSaveDirty();
  }

  function removeExclude(n) {
    if (!editorState) return;
    editorState.workingExclude.delete(n);
    rebuildExcludeMatcher();
    editorState.dirty = true;
    updateDict();
    updateSelected();
    updateSaveDirty();
    refreshRemovedChipHighlights(editorState.key);
  }

  function saveEditor() {
    if (!editorState || typeof saveCategoryFilter !== 'function') return;
    const exclude = [...editorState.workingExclude].map(n => editorState.excludeDisplay.get(n) || n);
    const include = parseTagInput(editorState.workingInclude);
    const hide = parseTagInput(editorState.workingHide);
    // 전송 실패(재연결 중 등) 시 dirty 유지 — 미저장 상태가 조용히 사라지지 않게 한다.
    const sent = saveCategoryFilter(editorState.key, exclude, include, hide);
    if (sent === false) {
      updateSaveDirty();
      return;
    }
    editorState.dirty = false;
    flashSaved();
  }

  async function fetchCategoryTags(reset) {
    if (!editorState) return;
    const key = editorState.key;
    const offset = reset ? 0 : editorState.loaded;
    // 요청 세대 가드 — 이전 쿼리/페이지의 늦은 응답이 최신 상태를 덮어쓰지 않게 한다
    // (같은 카테고리 안에서도 검색어 변경·더 보기 연타 레이스 차단, Codex 리뷰 반영).
    const seq = (editorState._fetchSeq = (editorState._fetchSeq || 0) + 1);
    editorState.loading = true;
    editorState.error = null;
    updateDict();
    let data;
    try {
      const url = `${CATEGORY_TAGS_ENDPOINT}?category=${encodeURIComponent(key)}`
        + `&q=${encodeURIComponent(editorState.q)}&offset=${offset}&limit=${CATEGORY_PAGE_LIMIT}`;
      const res = await fetch(url, { headers: { Accept: 'application/json' } });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      data = await res.json();
    } catch (err) {
      if (!editorState || editorState.key !== key || editorState._fetchSeq !== seq) return;
      editorState.loading = false;
      editorState.error = String(err && err.message ? err.message : err);
      updateDict();
      return;
    }
    // 편집기 전환/닫힘/새 요청 발행 사이에 도착한 낡은 응답은 폐기.
    if (!editorState || editorState.key !== key || editorState._fetchSeq !== seq) return;
    editorState.loading = false;
    if (data && data.supported === false) {
      editorState.supported = false;
      editorState.reason = String(data.reason || '');
      editorState.tags = [];
      editorState.total = 0;
      editorState.loaded = 0;
      const container = editorContainer();
      if (container) renderEditorInto(container);   // dict 영역 제거 → 스켈레톤 재구성
      return;
    }
    editorState.supported = true;
    const incoming = Array.isArray(data && data.tags) ? data.tags : [];
    const incomingInfo = (data && typeof data.info === 'object' && data.info) || {};
    editorState.infoMap = reset ? {...incomingInfo} : {...editorState.infoMap, ...incomingInfo};
    if (reset) {
      editorState.tags = incoming;
    } else {
      // 더 보기 연타/재시도로 같은 페이지가 두 번 도착해도 중복 chip 을 만들지 않는다.
      const seen = new Set(editorState.tags.map(normTag));
      editorState.tags = editorState.tags.concat(incoming.filter(t => !seen.has(normTag(t))));
    }
    editorState.loaded = editorState.tags.length;
    editorState.total = Number(data && data.total || 0);
    if (editorState.q === '' && editorState.fullTotal == null) editorState.fullTotal = editorState.total;
    updateDict();
  }

  function renderEditorInto(container) {
    if (!container || !editorState) return;
    const key = editorState.key;
    const showDict = editorState.supported !== false;
    const noteHtml = editorState.supported === false
      ? `<div class="mod-debug-cat-sec">
          <div class="mod-debug-cat-note">${
            editorState.reason === 'frequency-based'
              ? '빈도 기반 · 사전 목록 없음 — 미리보기의 제거된 태그를 클릭해 제외'
              : '사전 미로드 — 미리보기의 제거된 태그를 클릭해 제외'
          }</div>
        </div>`
      : '';
    const colorHint = key === 'remove_color'
      ? '<div class="mod-debug-cat-hint">색상 단어 제외 = 그 색상 전체 보호 · 제거된 태그 클릭 = 그 태그만 보호</div>'
      : '';
    const dictHtml = showDict
      ? `<div class="mod-debug-cat-sec mod-debug-cat-dictsec">
          <div class="mod-debug-cat-searchrow">
            <span class="mod-debug-cat-searchbox">
              <span class="mod-debug-cat-searchicon" aria-hidden="true">🔍</span>
              <input type="text" class="${CATEGORY_SEARCH_CLASS}" placeholder="사전 검색 · __패턴__ 지원"
                     autocomplete="off" spellcheck="false" value="${escHtml(editorState.q)}">
            </span>
            <span class="mod-debug-cat-count"></span>
          </div>
          <div class="mod-debug-cat-patternrow" hidden></div>
          <div class="mod-debug-cat-dictwrap"><div class="mod-debug-cat-dict"></div></div>
          ${colorHint}
        </div>`
      : '';
    container.innerHTML = `
      <div class="mod-debug-cat-inner">
        ${dictHtml}
        ${noteHtml}
        <div class="mod-debug-cat-sec mod-debug-cat-selsec">
          <div class="mod-debug-cat-sechead">
            <span class="mod-debug-cat-sectitle">제외 중</span>
            <span class="mod-debug-cat-badge mod-debug-cat-selcount">0</span>
          </div>
          <div class="mod-debug-cat-selected"></div>
        </div>
        <div class="mod-debug-cat-sec">
          <div class="mod-debug-cat-sechead"><span class="mod-debug-cat-sectitle">추가 제거</span></div>
          <textarea class="mod-textarea ${CATEGORY_EDITOR_INPUT_CLASS}" data-cat-include rows="2"
                    placeholder="함께 제거할 태그 (쉼표)">${escHtml(editorState.workingInclude)}</textarea>
        </div>
        <div class="mod-debug-cat-sec">
          <div class="mod-debug-cat-sechead"><span class="mod-debug-cat-sectitle">개별 숨김</span>
            <span class="mod-debug-cat-note">이 카테고리가 OFF여도 항상 제거</span></div>
          <textarea class="mod-textarea ${CATEGORY_EDITOR_INPUT_CLASS}" data-cat-hide rows="2"
                    placeholder="항상 숨길 태그 (쉼표)">${escHtml(editorState.workingHide)}</textarea>
        </div>
        <div class="mod-debug-cat-actions">
          <button type="button" class="mod-debug-cat-save${editorState.dirty ? ' is-dirty' : (isSavedFlashing() ? ' is-saved' : '')}" data-cat-save>${saveButtonLabel(!!editorState.dirty)}</button>
        </div>
      </div>`;

    const searchInput = container.querySelector(`.${CATEGORY_SEARCH_CLASS}`);
    if (searchInput) {
      searchInput.addEventListener('input', () => {
        if (!editorState) return;
        editorState.q = searchInput.value.trim();
        if (searchDebounceTimer) clearTimeout(searchDebounceTimer);
        searchDebounceTimer = setTimeout(() => fetchCategoryTags(true), 250);
      });
    }
    // 두 칸이 같은 모양이라 하나로 묶는다 - 따로 쓰면 한쪽만 고치게 된다.
    [['[data-cat-include]', 'workingInclude'], ['[data-cat-hide]', 'workingHide']]
      .forEach(([selector, field]) => {
        const input = container.querySelector(selector);
        if (!input) return;
        input.addEventListener('input', () => {
          if (!editorState) return;
          editorState[field] = input.value;
          editorState.dirty = true;
          updateSaveDirty();
        });
        if (typeof bindTagAssist === 'function') bindTagAssist(input);
      });
    const saveBtn = container.querySelector('[data-cat-save]');
    if (saveBtn) saveBtn.addEventListener('click', saveEditor);

    updateSelected();
    if (showDict) updateDict();
  }

  // 단일 슬롯 아코디언 — 열린 카테고리만 펼치고, 라운드/⚙ 에 is-open 표시.
  function applyOpenSlotState(body) {
    const scope = body || getBody(panels.debug);
    if (!scope) return;
    const key = editorState ? editorState.key : null;
    scope.querySelectorAll('[data-cat-editor]').forEach(el => {
      if (el.dataset.catEditor !== key) el.hidden = true;
    });
    scope.querySelectorAll('[data-cat-round]').forEach(el => {
      el.classList.toggle('is-open', !!key && el.dataset.catRound === key);
    });
    scope.querySelectorAll('[data-cat-gear]').forEach(el => {
      el.classList.toggle('is-open', !!key && el.dataset.catGear === key);
    });
  }

  function openEditor(key, categoryFilters) {
    if (!editorState || editorState.key !== key) {
      editorState = newEditorState(key, categoryFilters);
      if (key === 'remove_noise_tags') { editorState.supported = false; editorState.reason = 'frequency-based'; }
    }
    const container = editorContainer();
    if (container) {
      container.hidden = false;
      renderEditorInto(container);
      if (typeof requestAnimationFrame === 'function') {
        requestAnimationFrame(() => {
          try { container.scrollIntoView({ block: 'nearest' }); } catch (_error) {}
        });
      }
    }
    applyOpenSlotState();
    if (editorState.supported !== false && editorState.tags.length === 0 && !editorState.loading) {
      fetchCategoryTags(true);
    }
  }

  function closeEditor() {
    const container = editorContainer();
    if (container) container.hidden = true;
    editorState = null;
    applyOpenSlotState();
  }

  function quickExclude(key, tag, categoryFilters) {
    if (!editorState || editorState.key !== key) {
      openEditor(key, categoryFilters);
    }
    toggleExclude(tag);
  }

  function bindDebugPanelEvents(body, categoryFilters) {
    body.querySelectorAll('[data-cat-gear]').forEach(button => {
      button.addEventListener('click', () => {
        const key = button.dataset.catGear || '';
        if (editorState && editorState.key === key) closeEditor();
        else openEditor(key, categoryFilters);
      });
    });
    body.querySelectorAll('[data-removed-tag]').forEach(button => {
      button.addEventListener('click', () => {
        quickExclude(button.dataset.removedCat || '', button.dataset.removedTag || '', categoryFilters);
      });
    });
    // 재렌더 후 열려 있던 편집기 복원(editorState 로부터).
    if (editorState) {
      const container = body.querySelector(`[data-cat-editor="${cssEscape(editorState.key)}"]`);
      if (container) {
        container.hidden = false;
        renderEditorInto(container);
        if (editorState.supported !== false && editorState.tags.length === 0
            && !editorState.loading && !editorState.error) {
          fetchCategoryTags(true);
        }
      } else {
        editorState = null;
      }
    }
    applyOpenSlotState(body);
  }

  function renderDebugPanel(m) {
    const body = getBody(panels.debug);
    if (!body) return;
    // 재렌더 가드 — 검색 input / include textarea 편집 중이면(module_state push 로 인한)
    // 파괴적 재렌더를 건너뛴다. editorState 가 미저장 선택을 들고 있으므로 안전.
    const active = document.activeElement;
    if (active && panels.debug && panels.debug.contains(active) && active.classList
        && (active.classList.contains(CATEGORY_EDITOR_INPUT_CLASS)
            || active.classList.contains(CATEGORY_SEARCH_CLASS))) {
      return;
    }
    const categoryFilters = (m && typeof m.category_filters === 'object' && m.category_filters) || {};
    body.innerHTML = `
    <div class="mod-inline-row">
      <button class="mod-btn-secondary" onclick="refreshPromptEngineeringDebug()">Refresh Debug</button>
    </div>
    ${renderDebugSnapshot(m.debug_snapshot || {}, categoryFilters, m.preprocessing || {})}
  `;
    bindDebugPanelEvents(body, categoryFilters);
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
