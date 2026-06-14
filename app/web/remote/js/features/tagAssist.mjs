export function autocompleteCandidateForRow(row) {
  return row?.candidate && typeof row.candidate === 'object' ? row.candidate : null;
}

export function autocompleteInsertPolicyForRow(row) {
  if (!row || row.disabled || row._wc_type === 'preset_status') return 'none';
  const candidate = autocompleteCandidateForRow(row);
  return String(candidate?.insertPolicy || row.insertPolicy || 'default').toLowerCase();
}

export function canSelectAutocompleteRow(row, {manual = false} = {}) {
  const policy = autocompleteInsertPolicyForRow(row);
  if (policy === 'none') return false;
  if (manual) return policy === 'default' || policy === 'insert' || policy === 'manual';
  return policy === 'default' || policy === 'insert';
}

export function firstDefaultAutocompleteIndexForRows(rows = []) {
  const index = rows.findIndex(row => canSelectAutocompleteRow(row));
  return index >= 0 ? index : -1;
}

export function normalizeWebuiEscapedTagForLookup(text) {
  return String(text || '').replace(/\\([()])/g, '$1');
}

export function createTagAssistController({
  document,
  window,
  navigator,
  tooltip,
  promptEdit,
  negEdit,
  WebSocket,
  getWs,
  getMode,
  getChunkPanelControl,
  openChunkPanel,
  getChunkAnchor,
  onPromptEdit,
  fireModuleOninput,
  escHtml,
  fmtCount,
  catStyle,
  showToast,
  getEventPresetPanel,
}) {
  const tagTooltip = tooltip;
  let lastLookupTag = '';
  let tagLookupTimer = null;
  let tagLookupReadOnly = false;
  let tagChipInfoTooltip = null;
  let promptInfoTooltip = null;
  let promptInfoAnchor = null;
  let lastPromptInfoRawTag = '';
  let acMode = false;
  let acResults = [];
  let acSel = -1;
  let acTimer = null;
  let acTranslationTimer = null;
  let visibleTranslatedAutocompleteQuery = '';
  let presetInlineSearchTimer = null;
  let lastAcQuery = '';
  let lastTranslationRequestQuery = '';
  let lastTranslationRequestId = '';
  let autocompleteTranslationRequestSeq = 0;
  let acTarget = null;
  let presetAutocompleteMeta = null;
  let presetEventContext = {ratingId: 's', personId: '1girl_solo'};
  let presetPersonMenuOpen = false;
  let presetEventSourceResults = [];
  let presetEventSecondarySourceResults = [];
  let presetEventSecondaryResults = [];
  let presetExpressionHoverRow = null;
  let presetEventSearch = '';
  let presetInlineSearchRequestId = 0;
  const hangulRe = /[가-힣ㄱ-ㅎㅏ-ㅣ]/;
  const HANGUL_TRANSLATION_POLL_MS = 600;
  const HANGUL_COMPOSITION_STABLE_RETRY_MS = 600;
  const imeStates = new WeakMap();

  function sendWs(payload) {
    const ws = getWs();
    if (!ws || ws.readyState !== WebSocket.OPEN) return false;
    ws.send(JSON.stringify(payload));
    return true;
  }

  function isPresetEventsQuery(query) {
    return String(query || '').trim().toLowerCase().startsWith('preset:events');
  }

  function presetEventPrefixAndTail(token) {
    const raw = String(token || '').trim();
    const base = 'preset:events';
    if (!raw.toLowerCase().startsWith(base)) return {prefix: '', tail: ''};
    let tailStart = base.length;
    if (raw[tailStart] === '(') {
      const close = raw.indexOf(')', tailStart + 1);
      if (close > tailStart) tailStart = close + 1;
    }
    return {
      prefix: raw.slice(0, tailStart) || base,
      tail: raw.slice(tailStart).replace(/^\/+/, ''),
    };
  }

  function presetEventTokenWithContext(token, context = {}) {
    const {tail} = presetEventPrefixAndTail(token);
    const rating = String(context.ratingId || presetEventContext.ratingId || 's').trim().toLowerCase();
    const safeRating = ['g', 's', 'q', 'e'].includes(rating) ? rating : 's';
    const person = String(context.personId || presetEventContext.personId || '1girl_solo').trim() || '1girl_solo';
    return `preset:events(${safeRating}|${person})${tail ? '/' + tail : ''}`;
  }

  function switchPresetEventContext(nextContext = {}) {
    presetPersonMenuOpen = false;
    presetEventSearch = '';
    presetEventContext = {...presetEventContext, ...nextContext};
    const nextQuery = isPresetEventsQuery(lastAcQuery)
      ? presetEventTokenWithContext(lastAcQuery, presetEventContext)
      : lastAcQuery;
    const target = acTarget || promptEdit;
    const info = getActiveTokenInfo(target);
    if (info && isPresetEventsQuery(info.stripped)) {
      swapToken(target, info, nextQuery);
    }
    renderAutocomplete();
    requestPresetAutocomplete(nextQuery);
  }

  function isPresetClothesQuery(query) {
    return String(query || '').trim().toLowerCase().startsWith('preset:clothes');
  }

  function isPresetExpressionsQuery(query) {
    return String(query || '').trim().toLowerCase().startsWith('preset:expressions');
  }

  function isLocalPresetQuery(query) {
    return isPresetEventsQuery(query) || isPresetClothesQuery(query) || isPresetExpressionsQuery(query);
  }

  function presetQueryAxis(query) {
    if (isPresetClothesQuery(query)) return 'clothes';
    if (isPresetExpressionsQuery(query)) return 'expressions';
    if (isPresetEventsQuery(query)) return 'events';
    return '';
  }

  function presetEventTokenStage(token) {
    const {tail} = presetEventPrefixAndTail(token);
    const count = tail ? tail.split('/').filter(Boolean).length : 0;
    if (count >= 4) return 'combo';
    if (count === 3) return 'item';
    if (count === 2) return 'subcategory';
    if (count === 1) return 'category';
    return 'axis';
  }

  function presetEventStageLabel(stage) {
    const normalized = String(stage || '').toLowerCase();
    if (normalized === 'combo') return 'Observed combo';
    if (normalized === 'item') return 'Main item';
    if (normalized === 'subcategory') return 'Subcategory';
    if (normalized === 'category') return 'Category';
    if (normalized === 'axis') return 'Events';
    if (normalized === 'status') return 'Status';
    if (normalized === 'error') return 'Error';
    return normalized ? normalized.charAt(0).toUpperCase() + normalized.slice(1) : 'Preset';
  }

  function presetEventNextStageLabel(stage) {
    const normalized = String(stage || '').toLowerCase();
    if (normalized === 'combo') return 'observed combos';
    if (normalized === 'item') return 'main items';
    if (normalized === 'subcategory') return 'subcategories';
    if (normalized === 'category') return 'categories';
    return 'items';
  }

  function presetEventTokenTail(token) {
    return presetEventPrefixAndTail(token).tail;
  }

  function presetEventTokenLabel(token, crumbs = []) {
    const lastCrumb = crumbs[crumbs.length - 1]?.label;
    if (lastCrumb) return lastCrumb;
    const tail = presetEventTokenTail(token);
    const last = tail ? tail.split('/').filter(Boolean).pop() : 'events';
    return String(last || 'events').replace(/[_-]+/g, ' ').replace(/^./, ch => ch.toUpperCase());
  }

  function presetRequestPayload(query) {
    const payload = {type: 'autocomplete_preset', query};
    if (isPresetEventsQuery(query) || isPresetExpressionsQuery(query)) {
      payload.presetContext = {...presetEventContext};
    }
    return payload;
  }

  function presetStatusRow(query, message, status = 'preset', axis = 'events') {
    return {
      tag: String(status || 'preset'),
      value: query,
      count: 0,
      desc: message || `${presetAxisDisplayLabel(axis)} Preset data is not ready.`,
      group: `preset/${axis || 'events'}`,
      cat: 'status',
      _wc_type: 'preset_status',
      disabled: true,
      axis: axis || 'events',
      stage: 'status',
    };
  }

  function showPresetEventStatus(query, message, status = 'loading', axis = 'events') {
    presetAutocompleteMeta = {
      axis,
      stage: status,
      context: {...presetEventContext},
      loadState: {main: status, message},
      dataReady: false,
    };
    presetEventSecondarySourceResults = [];
    presetEventSecondaryResults = [];
    acResults = [presetStatusRow(query, message, status, axis)];
    acSel = 0;
    acMode = true;
    renderAutocomplete();
  }

  function syncTooltipSide() {
    if (!tagTooltip || window.innerWidth < 768) return;
    const inModule = acTarget && acTarget.closest('.module-popup, .refine-popup, .tag-filter-popup');
    tagTooltip.classList.toggle('left-side', !!inModule);
  }

  function clearAutocompletePositionStyles() {
    if (!tagTooltip) return;
    tagTooltip.style.removeProperty('top');
    tagTooltip.style.removeProperty('left');
    tagTooltip.style.removeProperty('right');
    tagTooltip.style.removeProperty('max-width');
    tagTooltip.style.removeProperty('max-height');
  }

  function copyCaretMirrorStyle(source, mirror) {
    const style = window.getComputedStyle(source);
    [
      'boxSizing', 'width', 'height', 'fontFamily', 'fontSize', 'fontWeight',
      'fontStyle', 'letterSpacing', 'textTransform', 'lineHeight', 'paddingTop',
      'paddingRight', 'paddingBottom', 'paddingLeft', 'borderTopWidth',
      'borderRightWidth', 'borderBottomWidth', 'borderLeftWidth',
    ].forEach(name => {
      mirror.style[name] = style[name];
    });
    mirror.style.whiteSpace = source.tagName === 'TEXTAREA' ? 'pre-wrap' : 'pre';
    // 줄바꿈 규칙은 원본 textarea에서 그대로 복사한다. 프롬프트/모듈 textarea는
    // word-break:break-all 이라 긴 토큰을 글자 단위로 끊는데, 미러가 'break-word'(=normal)
    // 로 고정돼 있으면 미러는 긴 토큰을 끊지 않아 캐럿 마커가 박스 오른쪽 바깥으로
    // 밀려나고(좌표는 클리핑돼도 살아있음) 자동완성 팝업이 캐럿이 아닌 화면 오른쪽에 뜬다.
    mirror.style.wordBreak = style.wordBreak || 'normal';
    mirror.style.overflowWrap = style.overflowWrap || style.wordWrap || 'normal';
  }

  function getInputCaretPoint(target) {
    if (!target || target.selectionStart == null) return null;
    const rect = target.getBoundingClientRect();
    if (!rect.width || !rect.height) return null;
    const mirror = document.createElement('div');
    const marker = document.createElement('span');
    mirror.setAttribute('aria-hidden', 'true');
    mirror.style.position = 'fixed';
    mirror.style.visibility = 'hidden';
    mirror.style.pointerEvents = 'none';
    mirror.style.left = `${rect.left}px`;
    mirror.style.top = `${rect.top}px`;
    mirror.style.width = `${rect.width}px`;
    mirror.style.height = `${rect.height}px`;
    mirror.style.overflow = 'hidden';
    copyCaretMirrorStyle(target, mirror);
    // 세로 스크롤바가 떠 있으면 textarea의 실제 줄바꿈 폭은 스크롤바만큼 좁다.
    // 미러는 overflow:hidden 이라 스크롤바가 없어 그만큼 더 넓게 줄바꿈하므로,
    // 스크롤바 폭을 오른쪽 패딩으로 예약해 줄바꿈 지점을 맞춘다(없으면 0).
    const cs = window.getComputedStyle(target);
    const scrollbarW = Math.max(0, target.offsetWidth - target.clientWidth
      - (parseFloat(cs.borderLeftWidth) || 0) - (parseFloat(cs.borderRightWidth) || 0));
    if (scrollbarW > 0) {
      mirror.style.paddingRight = `${(parseFloat(cs.paddingRight) || 0) + scrollbarW}px`;
    }
    mirror.textContent = String(target.value || '').slice(0, target.selectionStart);
    marker.textContent = '\u200b';
    mirror.appendChild(marker);
    document.body.appendChild(mirror);
    mirror.scrollTop = target.scrollTop || 0;
    mirror.scrollLeft = target.scrollLeft || 0;
    const markerRect = marker.getBoundingClientRect();
    const point = {
      left: markerRect.left,
      top: markerRect.top,
      bottom: markerRect.bottom,
    };
    mirror.remove();
    return point;
  }

  function positionAutocompleteTooltip() {
    if (!tagTooltip) return;
    const target = acTarget || promptEdit;
    const targetRect = target?.getBoundingClientRect?.();
    const caret = getInputCaretPoint(target);
    const viewport = window.visualViewport || {
      width: window.innerWidth,
      height: window.innerHeight,
      offsetLeft: 0,
      offsetTop: 0,
    };
    const margin = 8;
    const gap = 5;
    const fallbackLeft = targetRect ? targetRect.left : viewport.offsetLeft + margin;
    const fallbackBottom = targetRect ? targetRect.bottom : viewport.offsetTop + 48;
    const anchorLeft = Math.max(viewport.offsetLeft + margin, caret?.left ?? fallbackLeft);
    const anchorBottom = caret?.bottom ?? fallbackBottom;
    const observedPresetPopup = tagTooltip.classList.contains('preset-event-observed-mode');
    const stagedPresetPopup = tagTooltip.classList.contains('preset-event-staged-mode');
    const expressionPresetPopup = tagTooltip.classList.contains('preset-event-expression-mode');
    const widthCeiling = stagedPresetPopup ? 700 : (observedPresetPopup ? 760 : (expressionPresetPopup ? 680 : 560));
    const widthFloor = (observedPresetPopup || stagedPresetPopup || expressionPresetPopup) ? 430 : 280;
    const maxWidth = Math.max(widthFloor, Math.min(widthCeiling, viewport.width - margin * 2));
    const measured = tagTooltip.getBoundingClientRect();
    const width = Math.min(maxWidth, measured.width || maxWidth);
    const maxLeft = viewport.offsetLeft + viewport.width - width - margin;
    const left = Math.max(viewport.offsetLeft + margin, Math.min(anchorLeft, maxLeft));
    const belowTop = anchorBottom + gap;
    const maxHeightBelow = viewport.offsetTop + viewport.height - belowTop - margin;
    const height = measured.height || 220;
    const top = maxHeightBelow >= Math.min(height, 160)
      ? belowTop
      : Math.max(viewport.offsetTop + margin, (caret?.top ?? fallbackBottom) - height - gap);
    const maxHeight = Math.max(120, viewport.offsetTop + viewport.height - top - margin);
    tagTooltip.classList.remove('left-side');
    tagTooltip.style.top = `${Math.round(top)}px`;
    tagTooltip.style.left = `${Math.round(left)}px`;
    tagTooltip.style.right = 'auto';
    tagTooltip.style.maxWidth = `${Math.round(maxWidth)}px`;
    tagTooltip.style.maxHeight = `${Math.round(maxHeight)}px`;
  }

  function positionTagTooltip() {
    if (acMode) {
      positionAutocompleteTooltip();
      return;
    }
    clearAutocompletePositionStyles();
    if (!tagTooltip || window.innerWidth < 768) {
      tagTooltip?.style.removeProperty('--tag-tooltip-top');
      tagTooltip?.style.removeProperty('--tag-tooltip-left');
      tagTooltip?.style.removeProperty('--tag-tooltip-max-width');
      tagTooltip?.style.removeProperty('--tag-tooltip-max-height');
      return;
    }

    const viewerWrapper = document.querySelector('.viewer-wrapper');
    const tabBar = document.querySelector('.right-tab-bar');
    const viewerRect = viewerWrapper?.getBoundingClientRect();
    const tabRect = tabBar?.getBoundingClientRect();
    const viewportHeight = window.visualViewport ? window.visualViewport.height : window.innerHeight;
    const viewportWidth = window.visualViewport ? window.visualViewport.width : window.innerWidth;
    const viewportTop = window.visualViewport ? window.visualViewport.offsetTop : 0;
    const safeGap = 10;
    const sideGap = 22;
    const safeTop = tabRect
      ? tabRect.bottom + safeGap
      : viewportTop + 44;
    const top = Math.max(viewportTop + safeGap, safeTop);
    const maxHeight = Math.max(180, viewportHeight - (top - viewportTop) - safeGap);

    tagTooltip.style.setProperty('--tag-tooltip-top', `${Math.round(top)}px`);
    tagTooltip.style.setProperty('--tag-tooltip-max-height', `${Math.round(maxHeight)}px`);

    if (tagTooltip.classList.contains('left-side')) {
      tagTooltip.style.removeProperty('--tag-tooltip-left');
      tagTooltip.style.removeProperty('--tag-tooltip-max-width');
      return;
    }

    const left = viewerRect
      ? Math.min(viewerRect.left + sideGap, viewportWidth - 320 - safeGap)
      : 494;
    const availableWidth = viewerRect
      ? viewerRect.right - left - sideGap
      : viewportWidth - left - safeGap;
    const maxWidth = Math.max(320, Math.min(680, availableWidth));

    tagTooltip.style.setProperty('--tag-tooltip-left', `${Math.round(Math.max(safeGap, left))}px`);
    tagTooltip.style.setProperty('--tag-tooltip-max-width', `${Math.round(maxWidth)}px`);
  }

  function ensurePromptInfoTooltip() {
    if (!promptInfoTooltip) {
      promptInfoTooltip = document.createElement('div');
      promptInfoTooltip.className = 'result-info-tag-popup';
      document.body.appendChild(promptInfoTooltip);
    }
    return promptInfoTooltip;
  }

  function hidePromptInfoTooltip() {
    if (promptInfoTooltip) promptInfoTooltip.classList.remove('open');
  }

  function copyTextFallback(text) {
    if (typeof document.execCommand !== 'function') return false;
    const textarea = document.createElement('textarea');
    textarea.value = text;
    textarea.setAttribute('readonly', '');
    textarea.style.position = 'fixed';
    textarea.style.left = '-9999px';
    textarea.style.top = '0';
    textarea.style.opacity = '0';
    document.body.appendChild(textarea);
    textarea.focus();
    textarea.select();
    textarea.setSelectionRange(0, textarea.value.length);
    let copied = false;
    try {
      copied = document.execCommand('copy');
    } catch (_) {
      copied = false;
    }
    textarea.remove();
    return copied;
  }

  async function copyTextToClipboard(text) {
    const value = String(text || '');
    if (!value) return false;
    if (copyTextFallback(value)) return true;
    if (navigator.clipboard?.writeText) {
      try {
        await navigator.clipboard.writeText(value);
        return true;
      } catch (_) {
        return false;
      }
    }
    return false;
  }

  function positionPromptInfoTooltip() {
    if (!promptInfoTooltip || !promptInfoTooltip.classList.contains('open')) return;
    const panel = document.getElementById('resultInfoPanel');
    const header = panel?.querySelector('.result-info-header');
    const label = header?.querySelector('span');
    const anchor = label || header || promptInfoAnchor || panel;
    if (!anchor) return;

    const viewport = window.visualViewport || {
      width: window.innerWidth,
      height: window.innerHeight,
      offsetLeft: 0,
      offsetTop: 0,
    };
    const margin = 10;
    const gap = 8;
    const panelRect = panel?.getBoundingClientRect();
    const anchorRect = anchor.getBoundingClientRect();
    const maxWidth = Math.max(260, Math.min(680, (panelRect?.width || viewport.width) - margin * 2));
    const maxHeight = Math.min(420, Math.max(140, anchorRect.top - viewport.offsetTop - margin - gap));
    promptInfoTooltip.style.maxWidth = `${Math.round(maxWidth)}px`;
    promptInfoTooltip.style.maxHeight = `${Math.round(maxHeight)}px`;

    const popupRect = promptInfoTooltip.getBoundingClientRect();
    const minLeft = viewport.offsetLeft + margin;
    const maxLeft = viewport.offsetLeft + viewport.width - popupRect.width - margin;
    let left = panelRect ? panelRect.left + 18 : anchorRect.left;
    left = Math.max(minLeft, Math.min(left, maxLeft));

    const minTop = viewport.offsetTop + margin;
    let top = anchorRect.top - popupRect.height - gap;
    if (top < minTop) top = Math.min(anchorRect.bottom + gap, viewport.offsetTop + viewport.height - popupRect.height - margin);
    top = Math.max(minTop, top);

    promptInfoTooltip.style.left = `${Math.round(left)}px`;
    promptInfoTooltip.style.top = `${Math.round(top)}px`;
  }

  function extraTagInfoFor(infoMap, tag) {
    if (!infoMap || !tag) return null;
    const key = String(tag);
    return infoMap[key] || infoMap[key.toLowerCase()] || null;
  }

  function renderTooltipExtraTag(tag, infoMap, extraClass = '') {
    const tagText = String(tag || '');
    const info = extraTagInfoFor(infoMap, tagText);
    const desc = info?.desc || '';
    const groupText = info ? [info.group, info.subgroup].filter(Boolean).join(' / ') : '';
    const countValue = Number(info?.count || 0);
    const countText = countValue > 0 ? fmtCount(countValue) : '';
    const classes = ['tag-tooltip-extra-tag'];
    if (extraClass) classes.push(extraClass);
    if (desc) classes.push('has-hover-info');
    const attrs = [
      `class="${classes.join(' ')}"`,
      `data-insert="${escHtml(tagText)}"`,
    ];
    if (desc) {
      attrs.push(`data-tooltip-title="${escHtml(info.tag || tagText)}"`);
      attrs.push(`data-tooltip-desc="${escHtml(desc)}"`);
      if (groupText) attrs.push(`data-tooltip-group="${escHtml(groupText)}"`);
      if (countText) attrs.push(`data-tooltip-count="${escHtml(countText)}"`);
      if (info.cat) attrs.push(`data-tooltip-cat="${escHtml(info.cat)}"`);
    }
    return `<span ${attrs.join(' ')}>${escHtml(tagText)}</span>`;
  }

  function autocompleteInfoAttrs(result, title, descOverride = null) {
    const desc = String(descOverride ?? result?.desc ?? result?.prompt ?? '').trim();
    if (!desc) return '';
    const groupText = [result?.group, result?.subgroup].filter(Boolean).join(' / ');
    const countValue = Number(result?.count || 0);
    const countText = countValue > 0 ? fmtCount(countValue) : '';
    const attrs = [
      `data-tooltip-title="${escHtml(title || result?.tag || '')}"`,
      `data-tooltip-desc="${escHtml(desc)}"`,
    ];
    if (groupText) attrs.push(`data-tooltip-group="${escHtml(groupText)}"`);
    if (countText) attrs.push(`data-tooltip-count="${escHtml(countText)}"`);
    if (result?.cat) attrs.push(`data-tooltip-cat="${escHtml(result.cat)}"`);
    return ` ${attrs.join(' ')}`;
  }

  function bindAutocompleteInfoHover(root) {
    if (root?.classList?.contains('preset-event-expression-mode')) return;
    root.querySelectorAll('.tag-ac-item[data-tooltip-desc]').forEach(el => {
      el.addEventListener('mouseenter', e => showTagChipInfoTooltip(el, e));
      el.addEventListener('mousemove', e => positionTagChipInfoTooltip(el, e));
      el.addEventListener('mouseleave', hideTagChipInfoTooltip);
    });
  }

  function normalizePromptInfoLookupTag(raw) {
    let text = String(raw || '').trim();
    if (!text || text.startsWith('#')) return '';
    while (/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)::\s*/.test(text)) {
      text = text.replace(/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)::\s*/, '').trim();
    }
    text = text.replace(/\s*::\s*$/, '').trim();
    text = stripAutocompleteTokenDecorators(text);
    text = text.replace(/^(artist|character|copyright|general|meta):/i, '').trim();
    if (!text || text.startsWith('$') || text.startsWith('__')) return '';
    return text;
  }

  function renderPromptInfoToken(raw) {
    const source = String(raw || '');
    const leading = source.match(/^\s*/)?.[0] || '';
    const trailing = source.match(/\s*$/)?.[0] || '';
    const core = source.trim();
    if (!core) return escHtml(source);
    const lookupTag = normalizePromptInfoLookupTag(core);
    if (!lookupTag) return escHtml(source);
    return escHtml(leading) +
      `<button type="button" class="generation-info-tag" data-tag="${escHtml(lookupTag)}" data-copy-tag="${escHtml(core)}" title="Show tag info">${escHtml(core)}</button>` +
      escHtml(trailing);
  }

  function renderPromptInfoText(text) {
    const parts = String(text || '').split(',');
    return parts.map((part, index) => {
      const rendered = renderPromptInfoToken(part);
      return index < parts.length - 1 ? rendered + '<span class="generation-info-comma">,</span>' : rendered;
    }).join('');
  }

  function renderPromptInfoHtml(label, text) {
    return `<div class="pf-island"><span class="pf-label">${escHtml(label)}</span>` +
      `<span class="generation-info-tags">${renderPromptInfoText(text)}</span></div>`;
  }

  function lookupPromptInfoTag(tag, options = {}) {
    const lookupOptions = options && options.nodeType ? {anchor: options} : options;
    const lookupTag = normalizePromptInfoLookupTag(tag);
    if (!lookupTag) return;
    if (isLocalPresetQuery(lookupTag)) {
      void lookupPresetEventTokenInfo(lookupTag, {
        readOnly: true,
        anchor: lookupOptions?.anchor || null,
        rawTag: lookupOptions?.rawTag || tag || lookupTag,
      });
      return;
    }
    acMode = false;
    acTarget = null;
    lastLookupTag = lookupTag;
    tagLookupReadOnly = true;
    promptInfoAnchor = lookupOptions?.anchor || null;
    lastPromptInfoRawTag = String(lookupOptions?.rawTag || tag || lookupTag).trim();
    hideTagChipInfoTooltip();
    window.clearTimeout(tagLookupTimer);
    tagTooltip.classList.remove('open', 'ac-mode', 'left-side', 'preset-event-mode', 'preset-event-observed-mode', 'preset-event-staged-mode', 'preset-event-expression-mode');
    const promptPopup = ensurePromptInfoTooltip();
    promptPopup.innerHTML = '<div class="tag-tooltip-main"><span class="tag-tooltip-tag">loading...</span></div>';
    promptPopup.classList.add('open');
    positionPromptInfoTooltip();
    sendWs({type: 'tag_lookup', tag: lookupTag});
  }

  function presetEventTooltipRoot(readOnly) {
    return readOnly ? ensurePromptInfoTooltip() : tagTooltip;
  }

  function presetAxisLabel(axis) {
    if (axis === 'expressions') return 'Expression';
    return axis === 'clothes' ? 'Clothes' : 'Event';
  }

  function presetAxisDisplayLabel(axis) {
    if (axis === 'expressions') return 'Expression';
    if (axis === 'clothes') return 'Clothes';
    return 'Event';
  }

  function showPresetEventTooltipLoading(token, {readOnly = false, anchor = null, rawTag = ''} = {}) {
    acMode = false;
    acTarget = readOnly ? null : acTarget;
    lastLookupTag = token;
    tagLookupReadOnly = !!readOnly;
    promptInfoAnchor = anchor || null;
    lastPromptInfoRawTag = String(rawTag || token).trim();
    hideTagChipInfoTooltip();
    window.clearTimeout(tagLookupTimer);
    tagTooltip.classList.remove('open', 'ac-mode', 'left-side', 'preset-event-mode', 'preset-event-observed-mode', 'preset-event-staged-mode', 'preset-event-expression-mode');
    const root = presetEventTooltipRoot(readOnly);
    root.innerHTML = '<div class="tag-tooltip-main"><span class="tag-tooltip-tag">Loading preset...</span></div>';
    root.classList.add('open');
    if (readOnly) positionPromptInfoTooltip();
    else {
      hidePromptInfoTooltip();
      syncTooltipSide();
      positionTagTooltip();
    }
  }

  function bindPresetEventTooltipActions(root, readOnly) {
    bindTagChipInfoHover(root);
    root.querySelectorAll('.tag-tooltip-extra-tag[data-insert]').forEach(el => {
      el.addEventListener('mousedown', e => {
        e.preventDefault();
        hideTagChipInfoTooltip();
        const tag = el.dataset.insert || '';
        if (!tag) return;
        if (readOnly) {
          lookupPromptInfoTag(tag);
          return;
        }
        const target = acTarget || promptEdit;
        const info = getActiveTokenInfo(target);
        if (!info) return;
        const text = target.value;
        const _st = target.scrollTop, _sl = target.scrollLeft; // value 재대입 scrollTop 리셋 → 복원
        target.value = text.substring(0, info.end) + ', ' + tag + text.substring(info.end);
        const newPos = info.end + 2 + tag.length;
        target.selectionStart = target.selectionEnd = newPos;
        target.focus({ preventScroll: true }); // 복원 전 focus(미포커스 시 재스크롤 방지, Codex)
        target.scrollTop = _st; target.scrollLeft = _sl; // 긴 프롬프트 스크롤 점프 방지
        if (target === promptEdit) onPromptEdit();
        else fireModuleOninput(target);
        lastLookupTag = '';
        checkTagHint();
      });
    });
    const tagCopyBtn = root.querySelector('.tag-tooltip-copy-btn');
    if (tagCopyBtn) {
      tagCopyBtn.addEventListener('click', e => {
        e.preventDefault();
        e.stopPropagation();
        copyTextToClipboard(tagCopyBtn.dataset.copyTag || '').then(copied => {
          showToast(copied ? 'Copied to clipboard' : 'Copy failed', copied ? 'success' : 'error');
        });
      });
    }
  }

  function renderPresetEventTokenTooltip(token, payload, {readOnly = false} = {}) {
    if (lastLookupTag.toLowerCase() !== token.toLowerCase()) return;
    const rows = Array.isArray(payload?.results) ? payload.results : [];
    const usableRows = rows.filter(item => item && !item.disabled && item._wc_type !== 'preset_status');
    const row = usableRows[0] || rows[0] || null;
    const preset = payload?.preset || {};
    const crumbs = Array.isArray(preset.crumbs) ? preset.crumbs : [];
    const tokenStage = presetEventTokenStage(token);
    const payloadStage = String(preset.stage || row?.stage || '').toLowerCase();
    const summary = presetEventTooltipSummary(token, tokenStage, payloadStage, usableRows, row, crumbs);
    const groupText = ['preset/events', presetEventStageLabel(tokenStage)].filter(Boolean).join(' / ');
    const pathText = ['Events', ...crumbs.map(crumb => crumb?.label).filter(Boolean)].join(' / ');
    const descParts = [];
    if (pathText) descParts.push(pathText);
    if (summary.desc) descParts.push(summary.desc);
    const root = presetEventTooltipRoot(readOnly);
    let html = '<div class="tag-tooltip-main">' +
      `<span class="tag-tooltip-tag">${escHtml(summary.title)}</span>` +
      (summary.countText ? `<span class="tag-tooltip-count">${escHtml(summary.countText)}</span>` : '') +
      (groupText ? ` <span class="tag-tooltip-group">${escHtml(groupText)}</span>` : '') +
      (descParts.length ? `<span class="tag-tooltip-desc">${escHtml(descParts.join(' · '))}</span>` : '') +
      '</div>';
    if (summary.tags.length) {
      html += `<div class="tag-tooltip-extra"><span class="tag-tooltip-extra-label">${escHtml(summary.extraLabel)}</span>` +
        summary.tags.map(tag => renderTooltipExtraTag(tag, {})).join('') +
        '</div>';
    }
    if (readOnly) {
      html += '<div class="tag-tooltip-copy-row">' +
        `<button type="button" class="tag-tooltip-copy-btn" data-copy-tag="${escHtml(lastPromptInfoRawTag || token)}">Copy Token</button>` +
        '</div>';
    }
    root.innerHTML = html;
    root.classList.remove('ac-mode');
    root.classList.add('open');
    if (readOnly) {
      tagTooltip.classList.remove('open', 'ac-mode', 'left-side', 'preset-event-mode', 'preset-event-observed-mode', 'preset-event-staged-mode', 'preset-event-expression-mode');
      positionPromptInfoTooltip();
    } else {
      hidePromptInfoTooltip();
      tagTooltip.classList.remove('ac-mode', 'preset-event-mode', 'preset-event-observed-mode', 'preset-event-staged-mode', 'preset-event-expression-mode');
      syncTooltipSide();
      positionTagTooltip();
    }
    bindPresetEventTooltipActions(root, readOnly);
  }

  function presetClothesStageLabel(stage) {
    const normalized = String(stage || '').toLowerCase();
    if (normalized === 'combo') return 'Combo';
    if (normalized === 'item') return 'Clothes item';
    if (normalized === 'subcategory') return 'Group';
    if (normalized === 'category') return 'Category';
    if (normalized === 'status') return 'Status';
    if (normalized === 'error') return 'Error';
    return normalized ? normalized.charAt(0).toUpperCase() + normalized.slice(1) : 'Clothes';
  }

  function presetClothesCurrentSegment(parsed) {
    if (!parsed || parsed.mode !== 'staged') return null;
    const index = Number.isInteger(parsed.activeIndex) ? parsed.activeIndex : -1;
    return Array.isArray(parsed.segments)
      ? parsed.segments.find(segment => segment.index === index) || null
      : null;
  }

  function presetClothesTokenLabel(token, preset, rows) {
    const parsed = preset?.parsed || {};
    const crumbs = Array.isArray(preset?.crumbs) ? preset.crumbs : [];
    const active = presetClothesCurrentSegment(parsed);
    if (active?.raw) return String(active.raw).replace(/[_-]+/g, ' ');
    const lastCrumb = crumbs[crumbs.length - 1]?.label;
    if (lastCrumb) return lastCrumb;
    const firstRow = rows?.[0];
    if (parsed.mode === 'staged') return parsed.activeQuery ? parsed.activeQuery : 'Add clothes item';
    if (firstRow?.tag && preset?.stage === 'combo') return firstRow.tag;
    const tail = String(token || '').slice('preset:clothes'.length).replace(/^\/+/, '');
    const last = tail ? tail.split(/[\/&]/).filter(Boolean).pop() : '';
    return last ? last.replace(/[_-]+/g, ' ') : 'Clothes Preset';
  }

  function presetClothesResolveTags(parsed) {
    if (!parsed || parsed.mode !== 'staged') return [];
    return Array.isArray(parsed.resolveTags) && parsed.resolveTags.length
      ? parsed.resolveTags
      : (Array.isArray(parsed.stagedTags) ? parsed.stagedTags : []);
  }

  function presetClothesGenerationText(parsed, {short = false} = {}) {
    const tags = presetClothesResolveTags(parsed);
    if (!tags.length) return '';
    if (parsed?.randomizeOnResolve) {
      return short ? 'Add random match' : 'Generation keeps these tags and adds one matching random Clothes combo';
    }
    return short ? 'Use tags only' : 'Generation applies exactly these staged tags';
  }

  function encodeClothesSegment(value) {
    return String(value || '').trim().replace(/&/g, '%26');
  }

  function clothesTokenFromSegments(segments, {randomize = false} = {}) {
    const cleanSegments = [];
    const seen = new Set();
    for (const segment of segments || []) {
      const clean = String(segment || '').trim();
      if (!clean) continue;
      const key = clean.toLowerCase();
      if (seen.has(key)) continue;
      seen.add(key);
      cleanSegments.push(clean);
    }
    if (!cleanSegments.length) return 'preset:clothes';
    const body = cleanSegments.map(encodeClothesSegment).join('&');
    return `preset:clothes/${body}${randomize ? '&' : ''}`;
  }

  function presetClothesRawSegments(parsed) {
    return Array.isArray(parsed?.segments)
      ? parsed.segments.map(segment => String(segment?.raw || '').trim())
      : [];
  }

  function clothesSegmentBounds(token, segmentIndex) {
    const raw = String(token || '');
    const prefix = 'preset:clothes';
    if (!raw.toLowerCase().startsWith(prefix)) return null;
    let tailStart = prefix.length;
    while (raw[tailStart] === '/') tailStart += 1;
    const tail = raw.slice(tailStart);
    const parts = tail.split('&');
    let start = 0;
    for (let index = 0; index < parts.length; index += 1) {
      const end = start + parts[index].length;
      if (index === segmentIndex) {
        return {start: tailStart + start, end: tailStart + end};
      }
      start = end + 1;
    }
    return null;
  }

  function focusClothesSegment(textarea, tokenInfo, segmentIndex) {
    const token = String(tokenInfo?.stripped || '');
    const bounds = clothesSegmentBounds(token, segmentIndex);
    if (!bounds || !textarea) return false;
    const tokenOffset = Math.max(0, String(tokenInfo.raw || '').indexOf(token));
    const tokenStart = tokenInfo.start + tokenOffset;
    const pos = tokenStart + bounds.end;
    textarea.selectionStart = textarea.selectionEnd = Math.max(tokenInfo.start, pos);
    textarea.focus({preventScroll: true});
    return true;
  }

  function presetClothesTooltipSummary(token, preset, rows, fallbackRow) {
    const parsed = preset?.parsed || {};
    const stage = String(preset?.stage || fallbackRow?.stage || '').toLowerCase();
    const stagedTags = presetClothesResolveTags(parsed);
    const rowCount = rows.length;
    const countText = rowCount ? `${rowCount}${rowCount >= 500 ? '+' : ''}` : '';
    if (fallbackRow?.disabled || fallbackRow?._wc_type === 'preset_status') {
      return {
        title: fallbackRow?.tag || 'Clothes preset',
        countText: '',
        desc: fallbackRow?.desc || 'Clothes Preset data is not ready.',
        extraLabel: 'contains',
        tags: [],
      };
    }
    if (stage === 'combo') {
      return {
        title: fallbackRow?.tag || presetClothesTokenLabel(token, preset, rows),
        countText: fallbackRow?.count ? fmtCount(fallbackRow.count || 0) : countText,
        desc: fallbackRow?.prompt || fallbackRow?.desc || '',
        extraLabel: 'contains',
        tags: rowTags(fallbackRow),
      };
    }
    if (parsed.mode === 'staged') {
      const active = presetClothesCurrentSegment(parsed);
      const activeText = String(active?.raw || parsed.activeQuery || '').trim();
      const parts = [];
      parts.push(`${stagedTags.length} staged ${stagedTags.length === 1 ? 'item' : 'items'}`);
      const generationText = presetClothesGenerationText(parsed);
      if (generationText) parts.push(generationText);
      if (activeText) parts.push(`editing "${activeText}"`);
      if (rowCount) parts.push(`${countText} ${stage === 'item' ? 'candidate items' : 'next options'}`);
      else parts.push('no matching candidates');
      const tags = stagedTags.length ? stagedTags : uniqueLimitedTags(rows, 14);
      return {
        title: activeText || 'Add clothes item',
        countText,
        desc: parts.join(' · '),
        extraLabel: stagedTags.length ? 'staged context' : 'examples',
        tags,
      };
    }
    if (stage === 'category' || stage === 'subcategory') {
      const examples = rows
        .map(row => String(row?.tag || '').trim())
        .filter(Boolean)
        .slice(0, 12);
      return {
        title: presetClothesTokenLabel(token, preset, rows),
        countText,
        desc: rowCount ? `${countText} ${stage === 'category' ? 'slots' : 'groups'}` : 'No child items loaded',
        extraLabel: stage === 'category' ? 'slots' : 'groups',
        tags: examples,
      };
    }
    return {
      title: presetClothesTokenLabel(token, preset, rows),
      countText,
      desc: rowCount ? `${countText} ${stage === 'item' ? 'candidate items' : 'items'}` : 'No matching items loaded',
      extraLabel: 'examples',
      tags: uniqueLimitedTags(rows, 14),
    };
  }

  function renderPresetClothesTokenTooltip(token, payload, {readOnly = false} = {}) {
    if (lastLookupTag.toLowerCase() !== token.toLowerCase()) return;
    const rows = Array.isArray(payload?.results) ? payload.results : [];
    const usableRows = rows.filter(item => item && !item.disabled && item._wc_type !== 'preset_status');
    const row = usableRows[0] || rows[0] || null;
    const preset = payload?.preset || {};
    const crumbs = Array.isArray(preset.crumbs) ? preset.crumbs : [];
    const stage = String(preset.stage || row?.stage || '').toLowerCase();
    const summary = presetClothesTooltipSummary(token, preset, usableRows, row);
    const groupText = ['preset/clothes', presetClothesStageLabel(stage)].filter(Boolean).join(' / ');
    const pathText = ['Clothes', ...crumbs.map(crumb => crumb?.label).filter(Boolean)].join(' / ');
    const descParts = [];
    if (pathText) descParts.push(pathText);
    if (summary.desc) descParts.push(summary.desc);
    const root = presetEventTooltipRoot(readOnly);
    let html = '<div class="tag-tooltip-main">' +
      `<span class="tag-tooltip-tag">${escHtml(summary.title)}</span>` +
      (summary.countText ? `<span class="tag-tooltip-count">${escHtml(summary.countText)}</span>` : '') +
      (groupText ? ` <span class="tag-tooltip-group">${escHtml(groupText)}</span>` : '') +
      (descParts.length ? `<span class="tag-tooltip-desc">${escHtml(descParts.join(' · '))}</span>` : '') +
      '</div>';
    if (summary.tags.length) {
      html += `<div class="tag-tooltip-extra"><span class="tag-tooltip-extra-label">${escHtml(summary.extraLabel)}</span>` +
        summary.tags.map(tag => renderTooltipExtraTag(tag, {})).join('') +
        '</div>';
    }
    if (readOnly) {
      html += '<div class="tag-tooltip-copy-row">' +
        `<button type="button" class="tag-tooltip-copy-btn" data-copy-tag="${escHtml(lastPromptInfoRawTag || token)}">Copy Token</button>` +
        '</div>';
    }
    root.innerHTML = html;
    root.classList.remove('ac-mode');
    root.classList.add('open');
    if (readOnly) {
      tagTooltip.classList.remove('open', 'ac-mode', 'left-side', 'preset-event-mode', 'preset-event-observed-mode', 'preset-event-staged-mode', 'preset-event-expression-mode');
      positionPromptInfoTooltip();
    } else {
      hidePromptInfoTooltip();
      tagTooltip.classList.remove('ac-mode', 'preset-event-mode', 'preset-event-observed-mode', 'preset-event-staged-mode', 'preset-event-expression-mode');
      syncTooltipSide();
      positionTagTooltip();
    }
    bindPresetEventTooltipActions(root, readOnly);
  }

  function rowTags(row) {
    if (Array.isArray(row?.tags) && row.tags.length) {
      return row.tags.map(tag => String(tag || '').trim()).filter(Boolean);
    }
    return String(row?.prompt || '').split(',').map(part => part.trim()).filter(Boolean);
  }

  function uniqueLimitedTags(rows, limit = 12) {
    const seen = new Set();
    const tags = [];
    for (const row of rows || []) {
      for (const tag of rowTags(row)) {
        const key = tag.toLowerCase();
        if (!key || seen.has(key)) continue;
        seen.add(key);
        tags.push(tag);
        if (tags.length >= limit) return tags;
      }
    }
    return tags;
  }

  function presetEventTooltipSummary(token, tokenStage, payloadStage, rows, fallbackRow, crumbs) {
    const title = presetEventTokenLabel(token, crumbs);
    const rowCount = rows.length;
    const countText = rowCount ? `${rowCount}${rowCount >= 500 ? '+' : ''}` : '';
    if (fallbackRow?.disabled || fallbackRow?._wc_type === 'preset_status') {
      return {
        title: fallbackRow?.tag || 'Event preset',
        countText: '',
        desc: fallbackRow?.desc || 'Event Preset data is not ready.',
        extraLabel: 'contains',
        tags: [],
      };
    }
    if (tokenStage === 'combo') {
      const tags = rowTags(fallbackRow);
      return {
        title: fallbackRow?.tag || title,
        countText: fallbackRow?.count ? fmtCount(fallbackRow.count || 0) : '',
        desc: fallbackRow?.prompt || fallbackRow?.desc || '',
        extraLabel: 'contains',
        tags,
      };
    }
    if (tokenStage === 'item') {
      return {
        title,
        countText,
        desc: rowCount ? `${rowCount}${rowCount >= 500 ? '+' : ''} in observed combos` : 'No observed combos loaded',
        extraLabel: 'example tags',
        tags: uniqueLimitedTags(rows, 14),
      };
    }
    if (tokenStage === 'subcategory') {
      return {
        title,
        countText,
        desc: rowCount ? `${rowCount}${rowCount >= 500 ? '+' : ''} ${presetEventNextStageLabel(payloadStage)}` : 'No main items loaded',
        extraLabel: 'example tags',
        tags: uniqueLimitedTags(rows, 14),
      };
    }
    if (tokenStage === 'category' || tokenStage === 'axis') {
      const examples = rows
        .map(row => String(row?.tag || '').trim())
        .filter(Boolean)
        .slice(0, 12);
      return {
        title,
        countText,
        desc: rowCount ? `${rowCount}${rowCount >= 500 ? '+' : ''} ${presetEventNextStageLabel(payloadStage)}` : 'No child items loaded',
        extraLabel: tokenStage === 'axis' ? 'categories' : 'subcategories',
        tags: examples,
      };
    }
    return {
      title: fallbackRow?.tag || title,
      countText,
      desc: fallbackRow?.prompt || fallbackRow?.desc || '',
      extraLabel: 'contains',
      tags: uniqueLimitedTags(rows, 12),
    };
  }

  async function lookupPresetEventTokenInfo(token, {readOnly = false, anchor = null, rawTag = ''} = {}) {
    const lookupTag = String(token || '').trim();
    if (!lookupTag) return;
    const axis = presetQueryAxis(lookupTag) || 'events';
    const renderTooltip = axis === 'clothes' ? renderPresetClothesTokenTooltip : renderPresetEventTokenTooltip;
    const panel = getEventPresetPanel?.();
    showPresetEventTooltipLoading(lookupTag, {readOnly, anchor, rawTag});
    if (!panel || typeof panel.getPresetAutocompletePayload !== 'function') {
      renderTooltip(lookupTag, {
        results: [presetStatusRow(lookupTag, `${presetAxisLabel(axis)} Preset page is not loaded yet.`, 'unavailable', axis)],
        preset: {axis, stage: 'status'},
      }, {readOnly});
      return;
    }
    try {
      const target = readOnly ? null : (acTarget || promptEdit);
      const info = target ? getActiveTokenInfo(target) : null;
      const caretOffset = info ? Math.max(0, (target?.selectionStart || 0) - info.start) : null;
      const payload = await panel.getPresetAutocompletePayload(lookupTag, {
        context: {...presetEventContext},
        limit: 500,
        caretOffset,
      });
      renderTooltip(lookupTag, payload || {}, {readOnly});
    } catch (error) {
      renderTooltip(lookupTag, {
        results: [presetStatusRow(lookupTag, error?.message || `${presetAxisLabel(axis)} Preset lookup failed.`, 'error', axis)],
        preset: {axis, stage: 'error'},
      }, {readOnly});
    }
  }

  function ensureTagChipInfoTooltip() {
    if (!tagChipInfoTooltip) {
      tagChipInfoTooltip = document.createElement('div');
      tagChipInfoTooltip.className = 'tag-chip-info-tooltip';
      document.body.appendChild(tagChipInfoTooltip);
    }
    return tagChipInfoTooltip;
  }

  function hideTagChipInfoTooltip() {
    if (tagChipInfoTooltip) tagChipInfoTooltip.classList.remove('open');
  }

  function isPresetEventInfoAnchor(anchor) {
    return !!anchor.closest?.('.tag-tooltip.preset-event-mode');
  }

  function positionTagChipInfoTooltip(anchor, event = null) {
    if (!tagChipInfoTooltip || !tagChipInfoTooltip.classList.contains('open')) return;
    const rect = anchor.getBoundingClientRect();
    const presetEventInfo = isPresetEventInfoAnchor(anchor);
    const acRoot = presetEventInfo ? null : anchor.closest?.('.tag-tooltip.ac-mode');
    const acRect = acRoot?.getBoundingClientRect?.();
    const viewport = window.visualViewport || {
      width: window.innerWidth,
      height: window.innerHeight,
      offsetLeft: 0,
      offsetTop: 0,
    };
    const margin = 8;
    const gap = 7;
    const maxWidth = Math.max(180, Math.min(280, viewport.width - margin * 2));
    tagChipInfoTooltip.style.maxWidth = `${Math.round(maxWidth)}px`;
    const tipRect = tagChipInfoTooltip.getBoundingClientRect();
    const minLeft = viewport.offsetLeft + margin;
    const maxLeft = viewport.offsetLeft + viewport.width - tipRect.width - margin;
    const sideAnchor = acRect || rect;
    const rightSideLeft = sideAnchor.right + gap;
    const leftSideLeft = sideAnchor.left - tipRect.width - gap;
    let left = Math.max(minLeft, Math.min(rect.left, maxLeft));
    const pointerX = Number(event?.clientX);
    const pointerY = Number(event?.clientY);
    if (presetEventInfo && Number.isFinite(pointerX)) {
      const pointerRight = pointerX + gap;
      const pointerLeft = pointerX - tipRect.width - gap;
      left = pointerRight <= maxLeft ? pointerRight : Math.max(minLeft, pointerLeft);
    } else if (acRect && rightSideLeft <= maxLeft) {
      left = rightSideLeft;
    } else if (acRect && leftSideLeft >= minLeft) {
      left = leftSideLeft;
    }
    const bottomLimit = viewport.offsetTop + viewport.height - margin;
    let top = presetEventInfo && Number.isFinite(pointerY)
      ? pointerY + gap
      : (acRect ? rect.top : rect.bottom + gap);
    if (presetEventInfo || acRect) {
      top = Math.min(top, bottomLimit - tipRect.height);
    } else if (top + tipRect.height > bottomLimit) {
      top = rect.top - tipRect.height - gap;
    }
    top = Math.max(viewport.offsetTop + margin, top);
    tagChipInfoTooltip.style.left = `${Math.round(left)}px`;
    tagChipInfoTooltip.style.top = `${Math.round(top)}px`;
  }

  function showTagChipInfoTooltip(anchor, event = null) {
    const desc = anchor.dataset.tooltipDesc || '';
    if (!desc) {
      hideTagChipInfoTooltip();
      return;
    }
    const title = anchor.dataset.tooltipTitle || anchor.dataset.insert || '';
    const meta = [anchor.dataset.tooltipCount, anchor.dataset.tooltipGroup].filter(Boolean).join(' · ');
    const chipTooltip = ensureTagChipInfoTooltip();
    chipTooltip.innerHTML =
      `<div class="tag-chip-info-title">${escHtml(title)}</div>` +
      (meta ? `<div class="tag-chip-info-meta">${escHtml(meta)}</div>` : '') +
      `<div class="tag-chip-info-desc">${escHtml(desc)}</div>`;
    chipTooltip.classList.add('open');
    chipTooltip.classList.toggle('preset-event-info-tooltip', isPresetEventInfoAnchor(anchor));
    positionTagChipInfoTooltip(anchor, event);
  }

  function bindTagChipInfoHover(root) {
    root.querySelectorAll('.tag-tooltip-extra-tag[data-tooltip-desc]').forEach(el => {
      el.addEventListener('mouseenter', e => showTagChipInfoTooltip(el, e));
      el.addEventListener('mousemove', e => positionTagChipInfoTooltip(el, e));
      el.addEventListener('mouseleave', hideTagChipInfoTooltip);
    });
  }

  function getActiveTokenInfo(textarea, source = null) {
    const text = source?.text != null ? String(source.text) : textarea.value;
    const pos = source?.pos != null
      ? Number(source.pos)
      : (textarea.selectionStart != null ? textarea.selectionStart : -1);
    if (pos < 0 || text.length === 0) return null;
    let start = text.lastIndexOf(',', pos - 1) + 1;
    let end = text.indexOf(',', pos);
    if (end === -1) end = text.length;
    while (start < end && /\s/.test(text[start])) start++;
    let rawEnd = end;
    while (rawEnd > start && /\s/.test(text[rawEnd - 1])) rawEnd--;
    const raw = text.substring(start, rawEnd);
    if (!raw || raw.startsWith('#')) return null;
    let stripped = stripAutocompleteTokenDecorators(raw);
    while (/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)::\s*/.test(stripped)) {
      stripped = stripped.replace(/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)::\s*/, '');
    }
    stripped = stripped.replace(/\s*::$/, '');
    stripped = stripped.trim();
    if (!stripped) return null;
    return { raw, stripped, start, end: rawEnd };
  }

  function getImeState(textarea) {
    return textarea ? imeStates.get(textarea) : null;
  }

  function isImeComposing(textarea) {
    const state = getImeState(textarea);
    return !!(state && state.composing);
  }

  function compositionTextOverride(textarea) {
    const state = getImeState(textarea);
    if (!state?.active || !state.data) return null;
    const baseValue = String(state.baseValue ?? textarea.value ?? '');
    const start = Math.max(0, Math.min(Number(state.start || 0), baseValue.length));
    const end = Math.max(start, Math.min(Number(state.end ?? start), baseValue.length));
    const data = String(state.data || '');
    return {
      text: baseValue.substring(0, start) + data + baseValue.substring(end),
      pos: start + data.length,
    };
  }

  function stripAutocompleteTokenDecorators(raw) {
    let stripped = raw.trim();
    if (stripped.startsWith('-(')) {
      stripped = stripped.substring(1);
    }
    while (stripped.startsWith('(') && stripped.endsWith(')') && hasWrappingParentheses(stripped)) {
      stripped = stripped.substring(1, stripped.length - 1).trim();
    }
    stripped = stripped.replace(/:\d+(?:\.\d+)?$/, '').trim();
    stripped = normalizeWebuiEscapedTagForLookup(stripped).trim();
    return stripped;
  }

  function hasWrappingParentheses(text) {
    let depth = 0;
    for (let i = 0; i < text.length; i++) {
      const char = text[i];
      if (char === '(') depth += 1;
      else if (char === ')') depth -= 1;
      if (depth === 0 && i < text.length - 1) return false;
      if (depth < 0) return false;
    }
    return depth === 0;
  }

  function getTagAtCursor(textarea) {
    const info = getActiveTokenInfo(textarea);
    return info ? info.stripped : '';
  }

  function checkTagHint() {
    if (acMode) return;
    const target = acTarget || promptEdit;
    const tag = getTagAtCursor(target);
    if (tag === lastLookupTag) return;
    lastLookupTag = tag;
    tagLookupReadOnly = false;
    hidePromptInfoTooltip();
    if (!tag) {
      hideTagChipInfoTooltip();
      tagTooltip.classList.remove('open', 'ac-mode', 'preset-event-mode', 'preset-event-observed-mode', 'preset-event-staged-mode', 'preset-event-expression-mode');
      return;
    }
    hideTagChipInfoTooltip();
    tagTooltip.classList.remove('open', 'ac-mode', 'preset-event-mode', 'preset-event-observed-mode', 'preset-event-staged-mode', 'preset-event-expression-mode');
    window.clearTimeout(tagLookupTimer);
    tagLookupTimer = window.setTimeout(() => {
      if (isLocalPresetQuery(tag)) {
        void lookupPresetEventTokenInfo(tag, {readOnly: false});
        return;
      }
      sendWs({type: 'tag_lookup', tag});
    }, 200);
  }

  function openPresetAutocompleteAtCursor(textarea) {
    const target = textarea || acTarget || promptEdit;
    const info = getActiveTokenInfo(target);
    if (!info || !isLocalPresetQuery(info.stripped)) return false;
    acTarget = target;
    lastLookupTag = '';
    tagLookupReadOnly = false;
    window.clearTimeout(tagLookupTimer);
    hidePromptInfoTooltip();
    hideTagChipInfoTooltip();
    presetEventSearch = '';
    requestPresetAutocomplete(info.stripped);
    return true;
  }

  function onTagLookupResult(m) {
    if (acMode) return;
    hideTagChipInfoTooltip();
    if (!m.tag) {
      if (tagLookupReadOnly) {
        hidePromptInfoTooltip();
      } else {
        tagTooltip.classList.remove('open', 'ac-mode', 'preset-event-mode', 'preset-event-observed-mode', 'preset-event-staged-mode', 'preset-event-expression-mode');
      }
      return;
    }
    if (m.tag.toLowerCase() !== lastLookupTag.toLowerCase()) return;
    const groupText = [m.group, m.subgroup].filter(Boolean).join(' / ');
    const extraTagInfo = m.extra_tag_info || {};
    let html = '<div class="tag-tooltip-main">' +
      `<span class="tag-tooltip-tag"${catStyle(m.cat)}>${escHtml(m.tag)}</span>` +
      `<span class="tag-tooltip-count">${fmtCount(m.count || 0)}</span>` +
      (groupText ? ` <span class="tag-tooltip-group">${escHtml(groupText)}</span>` : '') +
      (m.desc ? `<span class="tag-tooltip-desc">${escHtml(m.desc)}</span>` : '') +
      '</div>';
    if (m.implications && m.implications.length) {
      html += '<div class="tag-tooltip-extra"><span class="tag-tooltip-extra-label">implies</span>' +
        m.implications.map(t => renderTooltipExtraTag(t, extraTagInfo)).join('') + '</div>';
    }
    if (m.related && m.related.length) {
      html += '<div class="tag-tooltip-extra"><span class="tag-tooltip-extra-label">related</span>' +
        m.related.map(t => renderTooltipExtraTag(t, extraTagInfo)).join('') + '</div>';
    }
    if (tagLookupReadOnly) {
      const copyText = lastPromptInfoRawTag || m.tag;
      html += '<div class="tag-tooltip-copy-row">' +
        `<button type="button" class="tag-tooltip-copy-btn" data-copy-tag="${escHtml(copyText)}">Copy Tag</button>` +
        '</div>';
    }
    const cd = m.character_details;
    if (cd) {
      const fmtPct = p => p >= 10 ? Math.round(p) + '%' : p.toFixed(1) + '%';
      const DISPLAY_MAX = 6;
      const mkTag = (t, cls) => `<span class="tag-tooltip-extra-tag char-tag ${cls}" data-insert="${escHtml(t.tag)}">${escHtml(t.tag)} <small>${fmtPct(t.pct)}</small></span>`;
      let charTags = '';
      if (cd.copyright) charTags += `<span class="char-copyright">${escHtml(cd.copyright)}</span>`;
      if (cd.personal_color) charTags += cd.personal_color.slice(0, DISPLAY_MAX).map(t => mkTag(t, 'ct-pc')).join('');
      if (cd.personal_color && cd.personal_color.length > DISPLAY_MAX) charTags += `<span class="char-more">+${cd.personal_color.length - DISPLAY_MAX}</span>`;
      if (cd.characteristics) charTags += cd.characteristics.slice(0, DISPLAY_MAX).map(t => mkTag(t, 'ct-ch')).join('');
      if (cd.characteristics && cd.characteristics.length > DISPLAY_MAX) charTags += `<span class="char-more">+${cd.characteristics.length - DISPLAY_MAX}</span>`;
      if (cd.breast_size_top) charTags += `<span class="tag-tooltip-extra-tag char-tag ct-body" data-insert="${escHtml(cd.breast_size_top)}">${escHtml(cd.breast_size_top)}</span>`;
      if (charTags) html += `<div class="tag-tooltip-extra char-details-row">${charTags}</div>`;
      const allTags = [];
      if (cd.personal_color) cd.personal_color.forEach(t => allTags.push(t.tag));
      if (cd.breast_size_top) allTags.push(cd.breast_size_top);
      if (cd.characteristics) cd.characteristics.forEach(t => allTags.push(t.tag));
      html += `<div class="char-copy-row"><button class="char-copy-btn" data-tags="${escHtml(allTags.join(', '))}">\u{1F4CB} Copy All</button>` +
        `<small class="char-sample-count">${cd.total_rows || 0} samples</small></div>`;
    }
    const tooltipRoot = tagLookupReadOnly ? ensurePromptInfoTooltip() : tagTooltip;
    tooltipRoot.innerHTML = html;
    tooltipRoot.classList.remove('ac-mode');
    tooltipRoot.classList.add('open');
    if (tagLookupReadOnly) {
      tagTooltip.classList.remove('open', 'ac-mode', 'left-side', 'preset-event-mode', 'preset-event-observed-mode', 'preset-event-staged-mode', 'preset-event-expression-mode');
      positionPromptInfoTooltip();
    } else {
      hidePromptInfoTooltip();
      syncTooltipSide();
      positionTagTooltip();
    }
    bindTagChipInfoHover(tooltipRoot);
    tooltipRoot.querySelectorAll('.tag-tooltip-extra-tag[data-insert]').forEach(el => {
      el.addEventListener('mousedown', e => {
        e.preventDefault();
        hideTagChipInfoTooltip();
        const tag = el.dataset.insert;
        if (tagLookupReadOnly) {
          lookupPromptInfoTag(tag);
          return;
        }
        const target = acTarget || promptEdit;
        const info = getActiveTokenInfo(target);
        if (!info) return;
        const text = target.value;
        const _st = target.scrollTop, _sl = target.scrollLeft; // value 재대입 scrollTop 리셋 → 복원
        target.value = text.substring(0, info.end) + ', ' + tag + text.substring(info.end);
        const newPos = info.end + 2 + tag.length;
        target.selectionStart = target.selectionEnd = newPos;
        target.focus({ preventScroll: true }); // 복원 전 focus(미포커스 시 재스크롤 방지, Codex)
        target.scrollTop = _st; target.scrollLeft = _sl; // 긴 프롬프트 스크롤 점프 방지
        if (target === promptEdit) onPromptEdit();
        else fireModuleOninput(target);
        lastLookupTag = '';
        checkTagHint();
      });
    });
    const tagCopyBtn = tooltipRoot.querySelector('.tag-tooltip-copy-btn');
    if (tagCopyBtn) {
      tagCopyBtn.addEventListener('click', e => {
        e.preventDefault();
        e.stopPropagation();
        copyTextToClipboard(tagCopyBtn.dataset.copyTag || '').then(copied => {
          showToast(copied ? 'Copied to clipboard' : 'Copy failed', copied ? 'success' : 'error');
        });
      });
    }
    const copyBtn = tooltipRoot.querySelector('.char-copy-btn');
    if (copyBtn) {
      copyBtn.addEventListener('click', e => {
        e.preventDefault();
        e.stopPropagation();
        copyTextToClipboard(copyBtn.dataset.tags).then(copied => {
          showToast(copied ? 'Copied to clipboard' : 'Copy failed', copied ? 'success' : 'error');
        });
      });
    }
  }

  function normalizeAutocompleteQuery(stripped, allowTriggers) {
    const query = String(stripped || '').trim();
    if (!query) return '';
    const lower = query.toLowerCase();
    if (allowTriggers && (
      lower.startsWith('__') ||
      lower.startsWith('$') ||
      lower.startsWith('vibe:') ||
      lower.startsWith('preset:')
    )) return query;
    for (const namespace of ['artist', 'character']) {
      const prefix = namespace + ':';
      if (prefix.startsWith(lower) && lower.length >= 2) return '';
      if (lower.startsWith(prefix)) {
        const suffix = query.slice(prefix.length).trim();
        return suffix ? query : '';
      }
    }
    if (lower === '@') return '';
    if (lower.startsWith('@')) return query.slice(1).trim() ? query : '';
    return query;
  }

  function isAutocompleteControlQuery(query, allowTriggers) {
    if (!allowTriggers) return false;
    const lower = String(query || '').toLowerCase();
    return lower.startsWith('__') ||
      lower.startsWith('$') ||
      lower.startsWith('vibe:') ||
      lower.startsWith('preset:');
  }

  function clearAutocompleteTranslationTimer() {
    if (acTranslationTimer) {
      window.clearTimeout(acTranslationTimer);
      acTranslationTimer = null;
    }
  }

  function clearPendingAutocompleteTranslation(query = '', requestId = '') {
    if (!query && !requestId) {
      lastTranslationRequestQuery = '';
      lastTranslationRequestId = '';
      return;
    }
    if (query && lastTranslationRequestQuery !== query) return;
    if (requestId && lastTranslationRequestId !== requestId) return;
    lastTranslationRequestQuery = '';
    lastTranslationRequestId = '';
  }

  function hasPendingAutocompleteTranslation(query) {
    return !!query
      && hangulRe.test(query)
      && (lastTranslationRequestQuery === query || !!acTranslationTimer);
  }

  function hideAutocompleteWhileTranslationPending() {
    acMode = false;
    acResults = [];
    acSel = -1;
    visibleTranslatedAutocompleteQuery = '';
    presetAutocompleteMeta = null;
    presetPersonMenuOpen = false;
    presetEventSourceResults = [];
    presetEventSecondarySourceResults = [];
    presetEventSecondaryResults = [];
    presetEventSearch = '';
    presetInlineSearchRequestId += 1;
    hideTagChipInfoTooltip();
    tagTooltip.classList.remove('open', 'ac-mode', 'chunk-ac-mode', 'preset-event-mode', 'preset-event-observed-mode', 'preset-event-staged-mode', 'preset-event-expression-mode');
    clearAutocompletePositionStyles();
  }

  function scheduleAutocompleteTranslation(query, allowTriggers) {
    clearAutocompleteTranslationTimer();
    if (!query || !hangulRe.test(query) || isAutocompleteControlQuery(query, allowTriggers)) return;
    if (lastTranslationRequestQuery === query) return;
    acTranslationTimer = window.setTimeout(() => {
      acTranslationTimer = null;
      if (lastAcQuery !== query) return;
      lastTranslationRequestQuery = query;
      const requestId = `ac-tr-${Date.now()}-${++autocompleteTranslationRequestSeq}`;
      lastTranslationRequestId = requestId;
      if (!sendWs({type: 'autocomplete_translate', query, requestId})) {
        clearPendingAutocompleteTranslation(query, requestId);
        return;
      }
      window.setTimeout(() => clearPendingAutocompleteTranslation(query, requestId), 10000);
    }, HANGUL_TRANSLATION_POLL_MS);
  }

  // `__` 와일드카드 토큰을 분류한다.
  //  plain      : __name__            → 일반 (랜덤)
  //  seq        : __*name__           → 순차
  //  dep_master : __$ / __$mas        → 종속 1단계 (master 선택)
  //  dep_slave  : __$master:slave     → 종속 2단계 (slave 선택)
  function wildcardAutocompleteSpec(stripped) {
    const body = String(stripped || '').replace(/^_+/, '').replace(/_+$/, '');
    if (body.startsWith('$')) {
      const rest = body.slice(1);
      const ci = rest.indexOf(':');
      if (ci === -1) return {kind: 'dep_master', master: '', query: rest};
      return {kind: 'dep_slave', master: rest.slice(0, ci), query: rest.slice(ci + 1)};
    }
    if (body.startsWith('*')) return {kind: 'seq', query: body.slice(1)};
    return {kind: 'plain', query: body};
  }

  // 현재 Prefix/Postfix 프롬프트에서 __*name__ (순차) 와일드카드 이름을 수집.
  function collectSequentialMasters() {
    const names = [];
    const seen = new Set();
    ['modPrePrompt', 'modPostPrompt'].forEach(id => {
      const el = document.getElementById(id);
      if (!el) return;
      const re = /__\*(.+?)__/g;
      let mm;
      while ((mm = re.exec(String(el.value || ''))) !== null) {
        const name = mm[1].trim();
        if (name && !seen.has(name)) { seen.add(name); names.push(name); }
      }
    });
    return names;
  }

  // 종속 1단계: __$ 입력 시 프롬프트의 __* master 후보를 클라이언트측으로 나열.
  function showDependentMasterCandidates(query) {
    const ql = String(query || '').toLowerCase();
    const filtered = collectSequentialMasters()
      .filter(name => !ql || name.toLowerCase().includes(ql))
      .sort((a, b) => (a.toLowerCase() !== ql) - (b.toLowerCase() !== ql)
        || (!a.toLowerCase().startsWith(ql) - !b.toLowerCase().startsWith(ql))
        || a.localeCompare(b));
    if (!filtered.length) { hideAutocomplete(); checkTagHint(); return; }
    acResults = filtered.map(name => ({
      tag: name, _wc_type: 'wildcard_master', group: 'master', desc: 'sequential master', cat: '',
    }));
    acSel = firstDefaultAutocompleteIndex(acResults);
    acMode = true;
    renderAutocomplete();
  }

  function scheduleAutocomplete(options = {}) {
    const target = options.target || acTarget || promptEdit;
    const info = options.info || getActiveTokenInfo(target);
    const allowTriggers = target !== negEdit;
    const isChunkTrigger = !!(info && allowTriggers && info.stripped.startsWith('$'));
    const isVibeClusterTrigger = !!(info && allowTriggers && info.stripped.toLowerCase().startsWith('vibe:'));
    const isPresetTrigger = !!(info && allowTriggers && info.stripped.toLowerCase().startsWith('preset:'));
    if (!info || (!isChunkTrigger && !isVibeClusterTrigger && !isPresetTrigger && info.stripped.length < 2)) {
      hideAutocomplete();
      checkTagHint();
      return;
    }
    const query = normalizeAutocompleteQuery(info.stripped, allowTriggers);
    if (!query) {
      hideAutocomplete();
      checkTagHint();
      return;
    }
    if (query === lastAcQuery && !options.force) return;
    if (query !== lastAcQuery) visibleTranslatedAutocompleteQuery = '';
    lastAcQuery = query;
    scheduleAutocompleteTranslation(query, allowTriggers);
    window.clearTimeout(acTimer);
    window.clearTimeout(tagLookupTimer);
    acTimer = window.setTimeout(() => {
      const s = query;
      if (allowTriggers && s.startsWith('__')) {
        const spec = wildcardAutocompleteSpec(s);
        if (spec.kind === 'dep_master') {
          // 종속 1단계: 프롬프트의 __* master 후보를 클라이언트측으로 나열
          showDependentMasterCandidates(spec.query);
        } else {
          // seq/plain/dep_slave 모두 백엔드 와일드카드 검색 (빈 쿼리=전체 나열)
          sendWs({type: 'autocomplete_wildcard', query: spec.query});
        }
      } else if (allowTriggers && s.startsWith('$')) {
        sendWs({type: 'autocomplete_chunk', query: s.slice(1).trim()});
      } else if (allowTriggers && s.toLowerCase().startsWith('vibe:')) {
        sendWs({type: 'autocomplete_vibe_cluster', query: s.slice(5).trim()});
      } else if (allowTriggers && s.toLowerCase().startsWith('preset:')) {
        requestPresetAutocomplete(s);
      } else {
        sendWs({type: 'autocomplete', query: s});
      }
    }, 150);
  }

  function applyAutocompleteResult(m) {
    const q = lastAcQuery;
    const isTranslatedResponse = Object.prototype.hasOwnProperty.call(m || {}, 'translated_query');
    const wcSpec = q && q.startsWith('__') ? wildcardAutocompleteSpec(q) : null;
    // dep_master 는 클라이언트측으로 렌더되므로 백엔드 응답 매칭 대상이 아니다.
    const matchesWc = !!wcSpec && wcSpec.kind !== 'dep_master' && m.query === wcSpec.query;
    const matchesChunk = q && q.startsWith('$') && m.query === q.slice(1).trim();
    const matchesVibeCluster = q && q.toLowerCase().startsWith('vibe:') && m.query === q.slice(5).trim();
    const matchesPreset = q && q.toLowerCase().startsWith('preset:') && m.query === q;
    if (!matchesWc && !matchesChunk && !matchesVibeCluster && !matchesPreset && m.query !== q) return false;
    const target = acTarget || promptEdit;
    let results = (m.results || []).filter(r => !(target && target._excludeE621Autocomplete && r.cat === 'e621'));
    const secondaryResults = (
      Array.isArray(m.secondaryResults) ? m.secondaryResults :
      (Array.isArray(m?.preset?.secondaryResults) ? m.preset.secondaryResults :
      (Array.isArray(m.secondarySuggestions) ? m.secondarySuggestions : []))
    ).filter(r => !(target && target._excludeE621Autocomplete && r.cat === 'e621'));
    // 빈 쿼리(`__` 전체 나열 등)는 기본값('')과 우연히 일치하므로 가드에서 제외.
    if (!isTranslatedResponse && m.query && m.query === visibleTranslatedAutocompleteQuery) {
      return true;
    }
    presetAutocompleteMeta = matchesPreset ? (m.preset || null) : null;
    if (['events', 'clothes', 'expressions'].includes(presetAutocompleteMeta?.axis)) {
      const secondaryAxis = presetAutocompleteMeta?.axis === 'events' || presetAutocompleteMeta?.axis === 'clothes';
      presetExpressionHoverRow = null;
      presetEventSourceResults = results;
      presetEventSecondarySourceResults = secondaryAxis ? secondaryResults : [];
      results = filteredPresetEventResults();
      presetEventSecondaryResults = secondaryAxis
        ? filteredPresetEventSecondaryResults()
        : [];
    } else {
      presetExpressionHoverRow = null;
      presetEventSourceResults = [];
      presetEventSecondarySourceResults = [];
      presetEventSecondaryResults = [];
      presetEventSearch = '';
    }
    const context = presetAutocompleteMeta?.context || {};
    if (context.ratingId || context.personId) {
      presetEventContext = {
        ratingId: context.ratingId || presetEventContext.ratingId,
        personId: context.personId || presetEventContext.personId,
      };
    }
    if (!results.length && !presetEventSecondaryResults.length) {
      if (hasPendingAutocompleteTranslation(m.query || q)) {
        hideAutocompleteWhileTranslationPending();
        return true;
      }
      hideAutocomplete();
      checkTagHint();
      return true;
    }
    acResults = results;
    visibleTranslatedAutocompleteQuery = isTranslatedResponse ? (m.query || '') : '';
    acSel = firstDefaultAutocompleteIndex(results);
    acMode = true;
    renderAutocomplete();
    return true;
  }

  function onAutocompleteResult(m) {
    if (Object.prototype.hasOwnProperty.call(m || {}, 'translated_query')) {
      const requestId = String(m.requestId || '');
      if (requestId && requestId !== lastTranslationRequestId) {
        return true;
      }
      clearPendingAutocompleteTranslation(m.query || '', requestId);
    }
    applyAutocompleteResult(m);
  }

  function requestChunkAutocomplete(query) {
    const normalized = String(query || '').trim();
    if (!normalized) return false;
    lastAcQuery = normalized.startsWith('$') ? normalized : `$${normalized}`;
    window.clearTimeout(acTimer);
    window.clearTimeout(tagLookupTimer);
    return sendWs({type: 'autocomplete_chunk', query: lastAcQuery.slice(1).trim()});
  }

  function requestPresetAutocomplete(query) {
    const normalized = String(query || '').trim();
    if (!normalized) return false;
    const nextQuery = normalized.toLowerCase().startsWith('preset:') ? normalized : `preset:${normalized}`;
    if (nextQuery !== lastAcQuery) {
      presetEventSearch = '';
      presetInlineSearchRequestId += 1;
    }
    lastAcQuery = nextQuery;
    window.clearTimeout(acTimer);
    window.clearTimeout(tagLookupTimer);
    if (isLocalPresetQuery(lastAcQuery)) {
      void requestEventPresetAutocomplete(lastAcQuery);
      return true;
    }
    return sendWs(presetRequestPayload(lastAcQuery));
  }

  async function requestEventPresetAutocomplete(query, {search = '', showLoading = true, restoreSearchFocus = false, inlineSearchRequestId = null} = {}) {
    const requestQuery = String(query || '').trim();
    const requestSearch = String(search || '');
    const axis = presetQueryAxis(requestQuery) || 'events';
    const panel = getEventPresetPanel?.();
    if (!panel || typeof panel.getPresetAutocompletePayload !== 'function') {
      showPresetEventStatus(requestQuery, `${presetAxisDisplayLabel(axis)} Preset page is not loaded yet.`, 'unavailable', axis);
      return false;
    }
    if (showLoading) {
      showPresetEventStatus(requestQuery, `Loading ${presetAxisDisplayLabel(axis)} Preset page...`, 'loading', axis);
    }
    try {
      const target = acTarget || promptEdit;
      const info = getActiveTokenInfo(target);
      const caretOffset = info ? Math.max(0, (target?.selectionStart || 0) - info.start) : null;
      const usesInlineSearch = axis === 'clothes' || axis === 'events' || axis === 'expressions';
      const payload = await panel.getPresetAutocompletePayload(requestQuery, {
        context: {...presetEventContext},
        limit: 500,
        caretOffset,
        search: usesInlineSearch ? requestSearch : '',
      });
      if (lastAcQuery !== requestQuery) return true;
      if (usesInlineSearch) {
        if (inlineSearchRequestId !== null && inlineSearchRequestId !== presetInlineSearchRequestId) return true;
        if ((restoreSearchFocus || inlineSearchRequestId !== null) && requestSearch !== presetEventSearch) return true;
      }
      const applied = applyAutocompleteResult({
        type: 'autocomplete_result',
        query: payload?.query || requestQuery,
        results: payload?.results || [],
        secondaryResults: payload?.secondaryResults || payload?.preset?.secondaryResults || [],
        preset: payload?.preset || {},
      });
      if (restoreSearchFocus && usesInlineSearch) {
        const searchInput = tagTooltip.querySelector('[data-preset-event-search]');
        if (searchInput) {
          searchInput.focus({preventScroll: true});
          searchInput.selectionStart = searchInput.selectionEnd = searchInput.value.length;
        }
      }
      return applied;
    } catch (error) {
      if (lastAcQuery !== requestQuery) return false;
      const usesInlineSearch = axis === 'clothes' || axis === 'events' || axis === 'expressions';
      if (usesInlineSearch) {
        if (inlineSearchRequestId !== null && inlineSearchRequestId !== presetInlineSearchRequestId) return false;
        if ((restoreSearchFocus || inlineSearchRequestId !== null) && requestSearch !== presetEventSearch) return false;
      }
      showPresetEventStatus(requestQuery, error?.message || `${presetAxisDisplayLabel(axis)} Preset page load failed.`, 'error', axis);
      return false;
    }
  }

  function chunkPreviewHtml(result) {
    if (!result) return '';
    const title = result._wc_type === 'vibe_cluster'
      ? `vibe:${result.tag}`
      : (result._wc_type === 'chunk_group' ? `$${result.tag}:` : `$${result.tag}`);
    const meta = result._wc_type === 'chunk_group'
      ? `${result.desc || ''}`
      : (result._wc_type === 'vibe_cluster'
        ? `${result.group || ''}${result.count ? ` - ${result.count} frame(s)` : ''}`
        : `${result.group || ''}`);
    const body = result.preview || result.value || result.desc || '';
    return '<div class="chunk-ac-preview-title">' + escHtml(title) + '</div>' +
      (meta ? '<div class="chunk-ac-preview-meta">' + escHtml(meta) + '</div>' : '') +
      '<pre class="chunk-ac-preview-body">' + escHtml(body) + '</pre>';
  }

  function renderPresetEventToolbar(context) {
    const axis = presetAutocompleteMeta?.axis || 'events';
    const ratingOptions = Array.isArray(context?.ratingOptions) && context.ratingOptions.length
      ? context.ratingOptions
      : [
          {id: 'g', label: 'G', name: 'General'},
          {id: 's', label: 'S', name: 'Sensitive'},
          {id: 'q', label: 'Q', name: 'Questionable'},
          {id: 'e', label: 'E', name: 'Explicit'},
        ];
    const personOptions = Array.isArray(context?.personOptions) && context.personOptions.length
      ? context.personOptions
      : [{id: presetEventContext.personId, label: presetEventContext.personId.replace(/_/g, ' ')}];
    const selectedRating = presetEventContext.ratingId || context?.ratingId || 's';
    const selectedPerson = presetEventContext.personId || context?.personId || '1girl_solo';
    const selectedPersonOption = personOptions.find(option => String(option.id || '') === selectedPerson) || personOptions[0] || {};
    const selectedPersonLabel = selectedPersonOption.label || selectedPerson.replace(/_/g, ' ');
    const ratingHtml = ratingOptions.map(option => {
      const id = String(option.id || '').toLowerCase();
      const label = option.label || id.toUpperCase();
      const active = id === selectedRating ? ' active' : '';
      return `<button type="button" class="preset-event-rating${active}" data-rating="${escHtml(id)}" title="${escHtml(option.name || label)}">${escHtml(label)}</button>`;
    }).join('');
    const personHtml = personOptions.map(option => {
      const id = String(option.id || '');
      const selected = id === selectedPerson ? ' active' : '';
      const label = option.label || id.replace(/_/g, ' ');
      return `<button type="button" class="preset-event-person-option${selected}" data-person="${escHtml(id)}" role="option" aria-selected="${id === selectedPerson ? 'true' : 'false'}">${escHtml(label)}</button>`;
    }).join('');
    const personMenuHtml = axis === 'clothes' ? '' :
      `<div class="preset-event-person-menu${presetPersonMenuOpen ? ' open' : ''}">` +
        `<button type="button" class="preset-event-person-trigger" aria-haspopup="listbox" aria-expanded="${presetPersonMenuOpen ? 'true' : 'false'}">` +
          `<span>${escHtml(selectedPersonLabel)}</span><span class="preset-event-person-caret" aria-hidden="true"></span>` +
        '</button>' +
        `<div class="preset-event-person-options" role="listbox">${personHtml}</div>` +
      '</div>';
    const randomHtml = axis === 'clothes'
      ? '<button type="button" class="preset-event-random" data-preset-clothes-random title="Random Clothes">Random</button>'
      : '';
    return '<div class="preset-event-toolbar">' +
      `<div class="preset-event-ratings">${ratingHtml}</div>` +
      personMenuHtml +
      randomHtml +
      '</div>';
  }

  function eventPresetDisplayTag(row) {
    return row.tag || row.label || row.value || '';
  }

  function presetRowKoLabel(row) {
    return String(row?.displayLabelKo || row?.labelKo || '').trim();
  }

  function renderPresetAutocompleteTag(row, displayTag, axis) {
    const labelKo = axis === 'clothes' ? presetRowKoLabel(row) : '';
    if (!labelKo) return `<span class="tag-ac-tag">${escHtml(displayTag)}</span>`;
    return `<span class="tag-ac-tag preset-event-tag-with-ko">` +
      `<span class="preset-event-tag-main">${escHtml(displayTag)}</span>` +
      `<small class="preset-event-tag-ko">${escHtml(labelKo)}</small>` +
      `</span>`;
  }

  function presetEventParentToken(token) {
    const {prefix, tail: path} = presetEventPrefixAndTail(token);
    if (!prefix) return '';
    const segments = path ? path.split('/').filter(Boolean) : [];
    if (!segments.length) return '';
    const parent = segments.slice(0, -1);
    return `${prefix}${parent.length ? '/' + parent.join('/') : ''}`;
  }

  function presetClothesParentToken(token, parsed) {
    const raw = String(token || '').trim();
    if (!raw.toLowerCase().startsWith('preset:clothes')) return '';
    const prefix = 'preset:clothes';
    const tail = raw.slice(prefix.length).replace(/^\/+/, '');
    if (!tail) return '';
    if (tail.includes('&')) {
      const segments = tail.split('&');
      const activeIndex = Number.isInteger(parsed?.activeIndex)
        ? Math.max(0, Math.min(parsed.activeIndex, segments.length - 1))
        : Math.max(0, segments.length - 1);
      const active = segments[activeIndex] || '';
      const parts = active.split('/').filter(Boolean);
      if (parts.length > 1) {
        segments[activeIndex] = parts.slice(0, -1).join('/');
        return `${prefix}/${segments.join('&')}`;
      }
      if (active) {
        segments[activeIndex] = '';
        return `${prefix}/${segments.join('&')}`;
      }
      return '';
    }
    const parts = tail.split('/').filter(Boolean);
    if (!parts.length) return '';
    const parent = parts.slice(0, -1);
    return `${prefix}${parent.length ? '/' + parent.join('/') : ''}`;
  }

  function simplePresetParentToken(token, axis) {
    const raw = String(token || '').trim();
    const prefix = `preset:${axis}`;
    if (!raw.toLowerCase().startsWith(prefix)) return '';
    const tail = raw.slice(prefix.length).replace(/^\/+/, '');
    const parts = tail.split('/').filter(Boolean);
    if (!parts.length) return '';
    const parent = parts.slice(0, -1);
    return `${prefix}${parent.length ? '/' + parent.join('/') : ''}`;
  }

  function presetParentToken(token) {
    const axis = presetAutocompleteMeta?.axis || presetQueryAxis(token);
    if (axis === 'clothes') return presetClothesParentToken(token, presetAutocompleteMeta?.parsed || null);
    if (axis === 'expressions') return simplePresetParentToken(token, 'expressions');
    return presetEventParentToken(token);
  }

  function presetEventResultMatches(row, query) {
    const needle = String(query || '').trim().toLowerCase();
    if (!needle) return true;
    const tags = Array.isArray(row?.tags) ? row.tags.join(' ') : '';
    const haystack = [
      row?.tag,
      row?.label,
      row?.desc,
      row?.prompt,
      row?.value,
      row?.id,
      tags,
    ].join(' ').toLowerCase();
    return haystack.includes(needle);
  }

  function filteredPresetEventResults() {
    return (presetEventSourceResults || []).filter(row => presetEventResultMatches(row, presetEventSearch));
  }

  function filteredPresetEventSecondaryResults() {
    return (presetEventSecondarySourceResults || []).filter(row => presetEventResultMatches(row, presetEventSearch));
  }

  function refreshClothesInlineSearch() {
    const query = String(lastAcQuery || '').trim();
    if (!isPresetClothesQuery(query)) return;
    const requestId = ++presetInlineSearchRequestId;
    void requestEventPresetAutocomplete(query, {
      search: presetEventSearch,
      showLoading: false,
      restoreSearchFocus: true,
      inlineSearchRequestId: requestId,
    });
  }

  function refreshEventInlineSearch() {
    const query = String(lastAcQuery || '').trim();
    if (!isPresetEventsQuery(query) && !isPresetExpressionsQuery(query)) return;
    const requestId = ++presetInlineSearchRequestId;
    void requestEventPresetAutocomplete(query, {
      search: presetEventSearch,
      showLoading: false,
      restoreSearchFocus: true,
      inlineSearchRequestId: requestId,
    });
  }

  async function randomizeClothesAutocomplete() {
    const panel = getEventPresetPanel?.();
    if (!panel || typeof panel.getClothesRandomAutocompleteSelection !== 'function') return false;
    const target = acTarget || promptEdit;
    const info = getActiveTokenInfo(target);
    if (!info) return false;
    const caretOffset = Math.max(0, (target?.selectionStart || 0) - info.start);
    const result = await panel.getClothesRandomAutocompleteSelection(lastAcQuery || info.stripped, {
      context: {...presetEventContext},
      caretOffset,
      search: presetEventSearch,
      limit: 500,
    });
    if (!result?.ok || !result.token) {
      showToast?.(result?.message || 'No random Clothes candidates.', 'warning');
      return false;
    }
    presetPersonMenuOpen = false;
    presetEventSearch = '';
    swapToken(target, info, result.token);
    target.focus({ preventScroll: true }); // swapToken이 이미 스크롤 복원 — 재스크롤 방지(Codex)
    requestPresetAutocomplete(result.token);
    return true;
  }

  function replaceActivePresetToken(nextToken, {focusEnd = true} = {}) {
    const target = acTarget || promptEdit;
    const info = getActiveTokenInfo(target);
    if (!info) return false;
    swapToken(target, info, nextToken);
    target.focus({preventScroll: true});
    if (focusEnd) {
      const nextInfo = getActiveTokenInfo(target);
      if (nextInfo) {
        target.selectionStart = target.selectionEnd = nextInfo.end;
      }
    }
    presetPersonMenuOpen = false;
    presetEventSearch = '';
    requestPresetAutocomplete(nextToken);
    return true;
  }

  function clothesTokenFromCurrentSegments(transform, {randomize = null} = {}) {
    const parsed = presetAutocompleteMeta?.parsed || {};
    const segments = presetClothesRawSegments(parsed);
    const nextSegments = typeof transform === 'function' ? transform([...segments], parsed) : segments;
    const nextRandomize = randomize === null ? !!parsed.randomizeOnResolve : !!randomize;
    return clothesTokenFromSegments(nextSegments, {randomize: nextRandomize});
  }

  function removeClothesStageSegment(index) {
    const nextToken = clothesTokenFromCurrentSegments(segments => {
      if (index >= 0 && index < segments.length) segments.splice(index, 1);
      return segments;
    });
    return replaceActivePresetToken(nextToken);
  }

  function addClothesStageSegment() {
    const parsed = presetAutocompleteMeta?.parsed || {};
    const nextToken = clothesTokenFromSegments(presetClothesRawSegments(parsed), {randomize: true});
    return replaceActivePresetToken(nextToken);
  }

  function toggleClothesResolveMode() {
    const parsed = presetAutocompleteMeta?.parsed || {};
    const nextToken = clothesTokenFromCurrentSegments(null, {randomize: !parsed.randomizeOnResolve});
    return replaceActivePresetToken(nextToken);
  }

  function focusClothesStageSegment(index) {
    const target = acTarget || promptEdit;
    const info = getActiveTokenInfo(target);
    if (!info) return false;
    if (!focusClothesSegment(target, info, index)) return false;
    presetEventSearch = '';
    requestPresetAutocomplete(info.stripped);
    return true;
  }

  function presetEventStageText(stage) {
    const normalized = String(stage || '').toLowerCase();
    if (normalized === 'category') return 'Category';
    if (normalized === 'subcategory') return 'Subcategory';
    if (normalized === 'item') return 'Main item';
    if (normalized === 'combo') return 'Observed combos';
    if (normalized === 'loading') return 'Loading';
    if (normalized === 'error') return 'Error';
    if (normalized === 'status') return 'Status';
    return normalized ? normalized.charAt(0).toUpperCase() + normalized.slice(1) : 'Preset';
  }

  function presetAutocompleteStageText(axis, stage) {
    if (axis === 'clothes') return presetClothesStageLabel(stage);
    if (axis === 'expressions') return presetEventStageText(stage).replace('Main item', 'Expression');
    return presetEventStageText(stage);
  }

  function presetAutocompletePathParts() {
    const axis = presetAutocompleteMeta?.axis || 'events';
    const crumbs = Array.isArray(presetAutocompleteMeta?.crumbs) ? presetAutocompleteMeta.crumbs : [];
    if (axis === 'clothes') {
      return ['Clothes', ...crumbs.map(crumb => crumb?.label).filter(Boolean)];
    }
    if (axis === 'expressions') {
      return ['Expressions', ...crumbs.map(crumb => crumb?.label).filter(Boolean)];
    }
    return ['Events', ...crumbs.map(crumb => crumb?.label).filter(Boolean)];
  }

  function renderPresetEventStageLine() {
    const axis = presetAutocompleteMeta?.axis || 'events';
    const stage = presetAutocompleteMeta?.stage || '';
    const path = presetAutocompletePathParts();
    const canBack = !!presetParentToken(lastAcQuery);
    const total = presetEventSourceResults.length;
    const visible = acResults.length;
    const countText = presetEventSearch && total !== visible ? ` ${visible}/${total}` : (total ? ` ${total}` : '');
    const optionCountLabel = count => `${count} option${count === 1 ? '' : 's'}`;
    const optionText = presetEventSearch && total !== visible
      ? `${visible}/${total} options`
      : (total ? optionCountLabel(total) : '');
    const generationText = axis === 'clothes'
      ? presetClothesGenerationText(presetAutocompleteMeta?.parsed || {}, {short: true})
      : '';
    const parsed = presetAutocompleteMeta?.parsed || {};
    const stageText = axis === 'clothes' && parsed.mode === 'staged'
      ? [generationText, optionText].filter(Boolean).join(' · ')
      : [
          generationText,
          presetAutocompleteStageText(axis, stage) + countText,
        ].filter(Boolean).join(' · ');
    const pathHtml = path.map((part, index) => {
      const cls = index === path.length - 1 ? ' current' : '';
      return `<span class="preset-event-stage-part${cls}">${escHtml(part)}</span>`;
    }).join('<span class="preset-event-stage-sep">/</span>');
    return '<div class="preset-event-stage-line">' +
      `<button type="button" class="preset-event-back" data-preset-event-back ${canBack ? '' : 'disabled'} title="Back">‹</button>` +
      `<span class="preset-event-stage-path">${pathHtml}</span>` +
      `<span class="preset-event-stage-next">${escHtml(stageText)}</span>` +
      `<input class="preset-event-inline-search" data-preset-event-search value="${escHtml(presetEventSearch)}" placeholder="search" autocomplete="off" spellcheck="false">` +
      '</div>';
  }

  function renderPresetClothesStagedControls({panel = false} = {}) {
    if ((presetAutocompleteMeta?.axis || '') !== 'clothes') return '';
    const parsed = presetAutocompleteMeta?.parsed || {};
    if (parsed.mode !== 'staged') return '';
    const segments = Array.isArray(parsed.segments) ? parsed.segments : [];
    const resolveTags = presetClothesResolveTags(parsed);
    const activeEmpty = segments.some(segment => segment?.active && segment.empty);
    const chips = segments
      .filter(segment => segment?.tag)
      .map(segment => {
        const active = segment.active ? ' active' : '';
        const index = Number(segment.index);
        const label = String(segment.tag || '');
        return '<span class="preset-clothes-chip-wrap">' +
          `<button type="button" class="preset-clothes-chip${active}" data-clothes-chip="${index}" title="Replace ${escHtml(label)}">${escHtml(label)}</button>` +
          `<button type="button" class="preset-clothes-chip-remove" data-clothes-remove="${index}" title="Remove ${escHtml(label)}">×</button>` +
          '</span>';
      })
      .join('');
    if (!chips && !resolveTags.length && !panel) return '';
    const modeLabel = parsed.randomizeOnResolve ? 'Add random match' : 'Use tags only';
    const modeTitle = parsed.randomizeOnResolve
      ? 'Generation keeps staged tags and adds one matching random Clothes combo'
      : 'Generation applies staged tags exactly';
    const modeHint = parsed.randomizeOnResolve
      ? 'Generation keeps selected tags and adds one compatible random clothes match.'
      : 'Generation uses selected clothes tags exactly.';
    const addLabel = activeEmpty ? 'Search empty slot' : 'Add item';
    const addTitle = activeEmpty ? 'Search for a clothes item in the active empty slot' : 'Add another clothes item';
    const addClass = `preset-clothes-chip-add${activeEmpty ? ' active' : ''}`;
    const empty = panel && !chips
      ? '<div class="preset-clothes-panel-empty">No staged clothes selected.</div>'
      : '';
    return `<div class="preset-clothes-staged-controls${panel ? ' panel' : ''}">` +
      `<div class="preset-clothes-chips">${chips}${empty}` +
      `<button type="button" class="${addClass}" data-clothes-add title="${escHtml(addTitle)}">${escHtml(addLabel)}</button>` +
      '</div>' +
      `<button type="button" class="preset-clothes-mode-toggle${parsed.randomizeOnResolve ? ' random' : ' fixed'}" data-clothes-mode-toggle title="${escHtml(modeTitle)}">${escHtml(modeLabel)}</button>` +
      (panel ? `<div class="preset-clothes-staged-hint">${escHtml(modeHint)}</div>` : '') +
      '</div>';
  }

  function renderPresetClothesStagedPanel() {
    if ((presetAutocompleteMeta?.axis || '') !== 'clothes') return '';
    const parsed = presetAutocompleteMeta?.parsed || {};
    if (parsed.mode !== 'staged') return '';
    const resolveTags = presetClothesResolveTags(parsed);
    const title = resolveTags.length === 1 ? '1 tag' : `${resolveTags.length} tags`;
    return '<section class="preset-clothes-primary-staged">' +
      `<div class="preset-clothes-staged-head"><span>Selected Clothes</span><span>${escHtml(title)}</span></div>` +
      renderPresetClothesStagedControls({panel: true}) +
      '</section>';
  }

  function renderPresetExpressionPanel() {
    if ((presetAutocompleteMeta?.axis || '') !== 'expressions') return '';
    const detail = presetExpressionHoverRow
      ? presetExpressionDetailFromRow(presetExpressionHoverRow)
      : (presetAutocompleteMeta?.detail || {});
    const tags = Array.isArray(detail.tags) && detail.tags.length
      ? detail.tags.map(tag => String(tag || '').trim()).filter(Boolean)
      : uniqueLimitedTags(acResults, 12);
    const title = String(detail.title || 'Expression Detail').trim();
    const subtitle = String(detail.subtitle || '').trim();
    const prompt = String(detail.prompt || tags.join(', ')).trim();
    const count = detail.type === 'item' ? Number(detail.count || 0) : 0;
    const tagCount = tags.length;
    const headText = tagCount === 1 ? '1 tag' : `${tagCount} tags`;
    const tagHtml = tags.length
      ? tags.map(tag => `<span class="preset-expression-tag">${escHtml(tag)}</span>`).join('')
      : '<span class="preset-expression-empty">No expression tags.</span>';
    const meta = [
      subtitle,
      count > 0 ? fmtCount(count) : '',
      detail.source ? String(detail.source) : '',
    ].filter(Boolean).join(' · ');
    return '<section class="preset-event-expression-panel">' +
      `<div class="preset-expression-detail-head"><span>Expression Detail</span><span>${escHtml(headText)}</span></div>` +
      '<div class="preset-expression-detail-body">' +
      `<div class="preset-expression-detail-title">${escHtml(title)}</div>` +
      (meta ? `<div class="preset-expression-detail-meta">${escHtml(meta)}</div>` : '') +
      `<div class="preset-expression-tags">${tagHtml}</div>` +
      (prompt ? `<div class="preset-expression-prompt">${escHtml(prompt)}</div>` : '') +
      '</div>' +
      '</section>';
  }

  function presetExpressionDetailFromRow(row) {
    const tags = rowTags(row);
    const detail = row?.detail && typeof row.detail === 'object' ? row.detail : {};
    const title = String(detail.title || eventPresetDisplayTag(row) || row?.tag || 'Expression Detail').trim();
    const subtitle = String(detail.subtitle || row?.desc || '').trim();
    const prompt = String(detail.prompt || row?.prompt || tags.join(', ')).trim();
    return {
      type: detail.type || row?.stage || 'item',
      title,
      subtitle,
      count: Number(detail.count || row?.count || 0) || 0,
      tags: Array.isArray(detail.tags) && detail.tags.length ? detail.tags : tags,
      prompt,
      source: detail.source || row?.group || '',
    };
  }

  function updatePresetExpressionHoverDetail(row) {
    if ((presetAutocompleteMeta?.axis || '') !== 'expressions') return;
    presetExpressionHoverRow = row || null;
    const panel = tagTooltip.querySelector('.preset-event-expression-panel');
    if (!panel) return;
    const html = renderPresetExpressionPanel();
    const template = document.createElement('template');
    template.innerHTML = html;
    const next = template.content.firstElementChild;
    if (next) panel.replaceWith(next);
  }

  function renderPresetEventAutocomplete() {
    const context = presetAutocompleteMeta?.context || {};
    const axis = presetAutocompleteMeta?.axis || 'events';
    const clothesStagedMode = axis === 'clothes' && (presetAutocompleteMeta?.parsed || {}).mode === 'staged';
    const hasObservedPanel = axis === 'events' || clothesStagedMode;
    const hasStagedPanel = clothesStagedMode;
    const hasExpressionPanel = axis === 'expressions';
    let html = `<div class="preset-event-picker${hasObservedPanel ? ' has-observed-panel' : ''}${hasStagedPanel ? ' has-staged-panel' : ''}${hasExpressionPanel ? ' has-expression-panel' : ''}">` +
      renderPresetEventToolbar(context) +
      renderPresetEventStageLine() +
      '<div class="preset-event-popup-body">' +
      '<section class="preset-event-primary-panel">' +
      '<div class="tag-ac-list preset-event-list">';
    acResults.forEach((r, i) => {
      const sel = i === acSel ? ' selected' : '';
      const disabled = r._wc_type === 'preset_status' || r.disabled;
      const itemClass = disabled ? ' disabled' : '';
      const countText = r.count ? fmtCount(r.count || 0) : '';
      const displayTag = eventPresetDisplayTag(r);
      const descText = r.desc || r.prompt || rowTags(r).join(', ');
      const active = r.active ? ' active' : '';
      html += `<div class="tag-ac-item preset-event-item${itemClass}${sel}${active}" data-idx="${i}"${autocompleteInfoAttrs(r, displayTag, descText)}>` +
        renderPresetAutocompleteTag(r, displayTag, axis) +
        `<span class="tag-ac-count">${escHtml(countText)}</span>` +
        '</div>';
    });
    if (!acResults.length) {
      html += '<div class="preset-event-empty">No matches</div>';
    }
    html += '</div>';
    if (hasStagedPanel) {
      html += renderPresetClothesStagedPanel();
    }
    html += '</section>';
    if (hasObservedPanel) {
      const observedCount = presetEventSecondaryResults.length;
      const observedSourceCount = presetEventSecondarySourceResults.length;
      const observedLabel = axis === 'clothes' ? 'Observed Combos' : 'Observed Combos';
      const observedTitle = observedSourceCount
        ? `${observedLabel} ${presetEventSearch && observedCount !== observedSourceCount ? `${observedCount}/${observedSourceCount}` : observedSourceCount}`
        : observedLabel;
      const observedEmpty = axis === 'clothes'
        ? 'No compatible observed combos for selected clothes.'
        : 'Select a main item to inspect observed combos.';
      html += '<section class="preset-event-observed-panel">' +
        `<div class="preset-event-observed-head"><span>${escHtml(observedTitle)}</span><span>Count</span></div>` +
        '<div class="tag-ac-list preset-event-list preset-event-observed-list">';
      presetEventSecondaryResults.forEach((r, i) => {
        const disabled = r._wc_type === 'preset_status' || r.disabled;
        const itemClass = disabled ? ' disabled' : '';
        const countText = r.count ? fmtCount(r.count || 0) : '';
        const displayTag = eventPresetDisplayTag(r);
        const descText = r.desc || r.prompt || rowTags(r).join(', ');
        html += `<div class="tag-ac-item preset-event-item preset-event-observed-item${itemClass}" data-observed-idx="${i}"${autocompleteInfoAttrs(r, displayTag, descText)}>` +
          renderPresetAutocompleteTag(r, displayTag, axis) +
          `<span class="tag-ac-count">${escHtml(countText)}</span>` +
          '</div>';
      });
      if (!presetEventSecondaryResults.length) {
        html += `<div class="preset-event-empty">${escHtml(observedEmpty)}</div>`;
      }
      html += '</div></section>';
    }
    if (hasExpressionPanel) {
      html += renderPresetExpressionPanel();
    }
    html += '</div></div>';
    tagTooltip.innerHTML = html;
    tagTooltip.classList.add('open', 'ac-mode', 'preset-event-mode');
    tagTooltip.classList.toggle('preset-event-observed-mode', hasObservedPanel);
    tagTooltip.classList.toggle('preset-event-staged-mode', hasStagedPanel);
    tagTooltip.classList.toggle('preset-event-expression-mode', hasExpressionPanel);
    tagTooltip.classList.remove('chunk-ac-mode');
    positionTagTooltip();

    const toolbar = tagTooltip.querySelector('.preset-event-toolbar');
    if (toolbar) toolbar.addEventListener('mousedown', e => e.preventDefault());
    tagTooltip.querySelectorAll('[data-clothes-chip]').forEach(button => {
      button.addEventListener('mousedown', e => e.preventDefault());
      button.addEventListener('click', e => {
        e.preventDefault();
        const index = Number(button.dataset.clothesChip);
        if (Number.isInteger(index)) focusClothesStageSegment(index);
      });
    });
    tagTooltip.querySelectorAll('[data-clothes-remove]').forEach(button => {
      button.addEventListener('mousedown', e => e.preventDefault());
      button.addEventListener('click', e => {
        e.preventDefault();
        const index = Number(button.dataset.clothesRemove);
        if (Number.isInteger(index)) removeClothesStageSegment(index);
      });
    });
    const clothesAdd = tagTooltip.querySelector('[data-clothes-add]');
    if (clothesAdd) {
      clothesAdd.addEventListener('mousedown', e => e.preventDefault());
      clothesAdd.addEventListener('click', e => {
        e.preventDefault();
        addClothesStageSegment();
      });
    }
    const clothesModeToggle = tagTooltip.querySelector('[data-clothes-mode-toggle]');
    if (clothesModeToggle) {
      clothesModeToggle.addEventListener('mousedown', e => e.preventDefault());
      clothesModeToggle.addEventListener('click', e => {
        e.preventDefault();
        toggleClothesResolveMode();
      });
    }
    const clothesRandom = tagTooltip.querySelector('[data-preset-clothes-random]');
    if (clothesRandom) {
      clothesRandom.addEventListener('mousedown', e => e.preventDefault());
      clothesRandom.addEventListener('click', e => {
        e.preventDefault();
        void randomizeClothesAutocomplete();
      });
    }
    const backButton = tagTooltip.querySelector('[data-preset-event-back]');
    if (backButton) {
      backButton.addEventListener('mousedown', e => e.preventDefault());
      backButton.addEventListener('click', e => {
        e.preventDefault();
        if (backButton.disabled) return;
        const parentToken = presetParentToken(lastAcQuery);
        if (!parentToken) return;
        const target = acTarget || promptEdit;
        const info = getActiveTokenInfo(target);
        if (info) swapToken(target, info, parentToken);
        presetPersonMenuOpen = false;
        presetEventSearch = '';
        requestPresetAutocomplete(parentToken);
      });
    }
    const searchInput = tagTooltip.querySelector('[data-preset-event-search]');
    if (searchInput) {
      searchInput.addEventListener('mousedown', e => e.stopPropagation());
      searchInput.addEventListener('click', e => e.stopPropagation());
      searchInput.addEventListener('input', () => {
        presetEventSearch = searchInput.value || '';
        window.clearTimeout(presetInlineSearchTimer);
        if (presetAutocompleteMeta?.axis === 'clothes') {
          presetInlineSearchTimer = window.setTimeout(refreshClothesInlineSearch, 180);
        } else if (presetAutocompleteMeta?.axis === 'events' || presetAutocompleteMeta?.axis === 'expressions') {
          presetInlineSearchTimer = window.setTimeout(refreshEventInlineSearch, 180);
        }
      });
      searchInput.addEventListener('keydown', e => {
        e.stopPropagation();
        if ((e.key === 'Enter' || e.key === 'Tab') && acSel >= 0) {
          e.preventDefault();
          selectAutocomplete(acSel);
        } else if (e.key === 'Escape') {
          e.preventDefault();
          presetEventSearch = '';
          window.clearTimeout(presetInlineSearchTimer);
          if (presetAutocompleteMeta?.axis === 'clothes') {
            refreshClothesInlineSearch();
          } else if (presetAutocompleteMeta?.axis === 'events' || presetAutocompleteMeta?.axis === 'expressions') {
            refreshEventInlineSearch();
          } else {
            acResults = filteredPresetEventResults();
            presetEventSecondaryResults = filteredPresetEventSecondaryResults();
            acSel = firstDefaultAutocompleteIndex(acResults);
            renderAutocomplete();
            (acTarget || promptEdit)?.focus?.({preventScroll: true});
          }
        }
      });
    }
    tagTooltip.querySelectorAll('.preset-event-rating').forEach(button => {
      button.addEventListener('mousedown', e => e.preventDefault());
      button.addEventListener('click', e => {
        e.preventDefault();
        const nextRating = button.dataset.rating || presetEventContext.ratingId;
        if (!nextRating || nextRating === presetEventContext.ratingId) return;
        switchPresetEventContext({ratingId: nextRating});
      });
    });
    const personTrigger = tagTooltip.querySelector('.preset-event-person-trigger');
    if (personTrigger) {
      personTrigger.addEventListener('mousedown', e => e.preventDefault());
      personTrigger.addEventListener('click', e => {
        e.preventDefault();
        presetPersonMenuOpen = !presetPersonMenuOpen;
        renderAutocomplete();
      });
    }
    tagTooltip.querySelectorAll('.preset-event-person-option').forEach(button => {
      button.addEventListener('mousedown', e => e.preventDefault());
      button.addEventListener('click', e => {
        e.preventDefault();
        const nextPerson = button.dataset.person || presetEventContext.personId;
        if (!nextPerson || nextPerson === presetEventContext.personId) return;
        switchPresetEventContext({personId: nextPerson});
      });
    });
    tagTooltip.querySelectorAll('.preset-event-item').forEach(el => {
      el.addEventListener('mouseenter', () => {
        if (presetAutocompleteMeta?.axis !== 'expressions' || !el.hasAttribute('data-idx')) return;
        const idx = +el.dataset.idx;
        if (Number.isInteger(idx)) updatePresetExpressionHoverDetail(acResults[idx]);
      });
      el.addEventListener('mousedown', e => {
        if (el.hasAttribute('data-observed-idx')) return;
        e.preventDefault();
        presetPersonMenuOpen = false;
        const idx = +el.dataset.idx;
        if (Number.isInteger(idx)) selectAutocomplete(idx, {manual: true});
      });
    });
    tagTooltip.querySelectorAll('[data-observed-idx]').forEach(el => {
      el.addEventListener('mousedown', e => {
        e.preventDefault();
        presetPersonMenuOpen = false;
        const idx = +el.dataset.observedIdx;
        if (Number.isInteger(idx)) selectPresetObservedCombo(idx);
      });
    });
    bindAutocompleteInfoHover(tagTooltip);
  }

  function renderAutocomplete() {
    hideTagChipInfoTooltip();
    if (presetAutocompleteMeta?.axis === 'events' || presetAutocompleteMeta?.axis === 'clothes' || presetAutocompleteMeta?.axis === 'expressions') {
      renderPresetEventAutocomplete();
      return;
    }
    const chunkMode = acResults.some(r => r._wc_type === 'chunk' || r._wc_type === 'chunk_group' || r._wc_type === 'vibe_cluster');
    let html = chunkMode ? '<div class="chunk-ac-layout"><div class="tag-ac-list chunk-ac-list">' : '<div class="tag-ac-list">';
    acResults.forEach((r, i) => {
      const sel = i === acSel ? ' selected' : '';
      const wcType = r._wc_type;
      const tagColor = wcType ? catStyle(wcType) : catStyle(r.cat);
      const prefix = wcType === 'wildcard' ? '__' : (wcType === 'wildcard_master' ? '$' : (wcType === 'vibe_cluster' ? 'vibe:' : (wcType === 'chunk' || wcType === 'chunk_group' ? '$' : '')));
      const suffix = wcType === 'wildcard' ? '__' : (wcType === 'chunk_group' ? ':' : '');
      const itemClass = chunkMode ? ' chunk-ac-item' : '';
      const displayTag = wcType === 'preset_path'
        ? (r.tag || r.label || r.prompt || r.value || '')
        : (wcType === 'preset_status' ? (r.desc || r.tag || '') : prefix + r.tag + suffix);
      const metaText = wcType === 'chunk'
        ? (r.group || '')
        : (wcType ? (r.desc || '') : fmtCount(r.count));
      const inlinePreview = wcType === 'chunk_group' ? (r.preview || '') : '';
      const hoverTitle = wcType === 'preset_status' ? (r.tag || '') : displayTag;
      html += `<div class="tag-ac-item${itemClass}${sel}" data-idx="${i}"${autocompleteInfoAttrs(r, hoverTitle)}>` +
        `<span class="tag-ac-tag"${tagColor}>${escHtml(displayTag)}</span>` +
        `<span class="tag-ac-group">${escHtml(r.group || '')}</span>` +
        `<span class="tag-ac-count">${escHtml(metaText)}</span>` +
        (chunkMode && inlinePreview ? `<span class="chunk-ac-inline-preview">${escHtml(inlinePreview)}</span>` : '') +
        '</div>';
    });
    html += chunkMode
      ? `</div><div class="chunk-ac-preview">${chunkPreviewHtml(acResults[Math.max(0, acSel)] || acResults[0])}</div></div>`
      : '</div>';
    tagTooltip.innerHTML = html;
    tagTooltip.classList.add('open', 'ac-mode');
    tagTooltip.classList.remove('preset-event-mode', 'preset-event-observed-mode', 'preset-event-staged-mode', 'preset-event-expression-mode');
    tagTooltip.classList.toggle('chunk-ac-mode', chunkMode);
    syncTooltipSide();
    positionTagTooltip();
    tagTooltip.querySelectorAll('.tag-ac-item').forEach(el => {
      if (el.dataset.tooltipDesc) {
        el.addEventListener('mouseenter', () => showTagChipInfoTooltip(el));
        el.addEventListener('mousemove', () => positionTagChipInfoTooltip(el));
        el.addEventListener('mouseleave', hideTagChipInfoTooltip);
      }
      el.addEventListener('mouseenter', () => {
        if (!chunkMode) return;
        const idx = +el.dataset.idx;
        if (Number.isInteger(idx) && idx !== acSel) {
          acSel = idx;
          renderAutocomplete();
        }
      });
      el.addEventListener('mousedown', e => {
        e.preventDefault();
        selectAutocomplete(+el.dataset.idx, {manual: true});
      });
    });
  }

  function canSelectAutocomplete(row, {manual = false} = {}) {
    return canSelectAutocompleteRow(row, {manual});
  }

  function firstDefaultAutocompleteIndex(rows = acResults) {
    return firstDefaultAutocompleteIndexForRows(rows);
  }

  function moveAutocompleteSelection(delta) {
    if (!acResults.length) {
      acSel = -1;
      return;
    }
    const direction = delta >= 0 ? 1 : -1;
    let index = acSel;
    for (let step = 0; step < acResults.length; step++) {
      index += direction;
      if (index < 0 || index >= acResults.length) {
        acSel = -1;
        return;
      }
      if (canSelectAutocomplete(acResults[index])) {
        acSel = index;
        return;
      }
    }
    acSel = -1;
  }

  function selectAutocomplete(idx, options = {}) {
    const r = acResults[idx];
    if (!r) return;
    if (!canSelectAutocomplete(r, options)) return;
    const target = acTarget || promptEdit;
    if (isImeComposing(target)) return;
    const info = getActiveTokenInfo(target);
    if (!info) return;
    let newTag = r.tag;
    if (r._wc_type === 'wildcard_master') {
      // 종속 1단계: master 선택 → __$master: 삽입 후 2단계(slave) 자동완성 트리거
      swapToken(target, info, `__$${r.tag}:`);
      window.setTimeout(() => scheduleAutocomplete({force: true, target}), 0);
      return;
    }
    if (r._wc_type === 'wildcard') {
      const spec = wildcardAutocompleteSpec(info.stripped);
      if (spec.kind === 'dep_slave') newTag = `__$${spec.master}:${r.tag}__`;
      else if (spec.kind === 'seq') newTag = `__*${r.tag}__`;
      else newTag = `__${r.tag}__`;
      swapToken(target, info, newTag);
      hideAutocomplete();
      return;
    }
    if (r._wc_type === 'chunk_group') {
      const groupToken = r.value || `$${r.tag}:`;
      swapToken(target, info, groupToken);
      acMode = true;
      acResults = [];
      acSel = -1;
      tagTooltip.innerHTML = '<div class="chunk-ac-loading">Loading chunk items...</div>';
      tagTooltip.classList.add('open', 'ac-mode', 'chunk-ac-mode');
      syncTooltipSide();
      positionTagTooltip();
      requestChunkAutocomplete(groupToken);
      return;
    }
    if (r._wc_type === 'chunk') {
      swapToken(target, info, r.value || '');
      hideAutocomplete();
      return;
    }
    if (r._wc_type === 'vibe_cluster') {
      swapToken(target, info, r.value || `vibe:${r.tag}`);
      hideAutocomplete();
      return;
    }
    if (r._wc_type === 'preset_status') {
      return;
    }
    if (r._wc_type === 'preset_path') {
      const presetToken = r.axis === 'clothes' && r.clothesTokenValue
        ? r.clothesTokenValue
        : (r.value || `preset:${r.tag}`);
      swapToken(target, info, presetToken);
      if (r.final) {
        hideAutocomplete();
        return;
      }
      acMode = true;
      acResults = [];
      acSel = -1;
      tagTooltip.innerHTML = '<div class="chunk-ac-loading">Loading preset items...</div>';
      tagTooltip.classList.add('open', 'ac-mode');
      tagTooltip.classList.remove('chunk-ac-mode');
      positionTagTooltip();
      requestPresetAutocomplete(presetToken);
      return;
    }
    if (getMode() !== 'NAI') {
      newTag = newTag.replace(/\(/g, '\\(').replace(/\)/g, '\\)');
    }
    const sLower = info.stripped.toLowerCase();
    if (sLower.startsWith('@') && !newTag.startsWith('@')) {
      newTag = '@' + newTag;
    } else {
      for (const pfx of ['artist:', 'character:']) {
        if (sLower.startsWith(pfx) && !newTag.toLowerCase().startsWith(pfx)) {
          newTag = pfx + newTag;
          break;
        }
      }
    }
    swapToken(target, info, newTag);
    hideAutocomplete();
    lastLookupTag = newTag;
    sendWs({type: 'tag_lookup', tag: r.tag});
  }

  function selectPresetObservedCombo(idx) {
    const r = presetEventSecondaryResults[idx];
    if (!r || r.disabled) return;
    const target = acTarget || promptEdit;
    if (isImeComposing(target)) return;
    const info = getActiveTokenInfo(target);
    if (!info) return;
    if (r._wc_type !== 'preset_path') return;
    const presetToken = r.value || `preset:${r.tag}`;
    swapToken(target, info, presetToken);
    if (r.final) {
      hideAutocomplete();
      return;
    }
    acMode = true;
    acResults = [];
    acSel = -1;
    presetEventSecondaryResults = [];
    tagTooltip.innerHTML = '<div class="chunk-ac-loading">Loading preset items...</div>';
    tagTooltip.classList.add('open', 'ac-mode');
    tagTooltip.classList.remove('chunk-ac-mode');
    positionTagTooltip();
    requestPresetAutocomplete(presetToken);
  }

  function swapToken(textarea, tokenInfo, newTag) {
    const text = textarea.value;
    const _st = textarea.scrollTop, _sl = textarea.scrollLeft; // value 재대입 scrollTop=0 리셋 → 복원
    const raw = tokenInfo.raw;
    const stripped = tokenInfo.stripped;
    const rawLower = raw.toLowerCase();
    const strippedLower = stripped.toLowerCase();
    const idx = rawLower.indexOf(strippedLower);
    let prefix = '', suffix = '';
    if (idx >= 0) {
      prefix = raw.substring(0, idx);
      suffix = raw.substring(idx + stripped.length);
    }
    const replacement = prefix + newTag + suffix;
    textarea.value = text.substring(0, tokenInfo.start) + replacement + text.substring(tokenInfo.end);
    const newPos = tokenInfo.start + replacement.length;
    textarea.selectionStart = textarea.selectionEnd = newPos;
    // 스크롤 복원은 focus() 뒤에 — 미포커스 상태(preset/클릭 경로)에서 focus()가 캐럿으로
    // 재스크롤하면 복원이 무효화되고, 이어진 onPromptEdit이 잘못된 스크롤로 오버레이를
    // 동기화한다(Codex 적대리뷰). preventScroll로 focus 자체의 스크롤도 막는다.
    textarea.focus({ preventScroll: true });
    textarea.scrollTop = _st; textarea.scrollLeft = _sl; // 긴 프롬프트 스크롤 점프 방지
    if (textarea === promptEdit) onPromptEdit();
    else fireModuleOninput(textarea);
  }

  function hideAutocomplete() {
    acMode = false;
    acResults = [];
    acSel = -1;
    lastAcQuery = '';
    lastTranslationRequestQuery = '';
    lastTranslationRequestId = '';
    visibleTranslatedAutocompleteQuery = '';
    presetAutocompleteMeta = null;
    presetPersonMenuOpen = false;
    presetEventSourceResults = [];
    presetEventSecondarySourceResults = [];
    presetEventSecondaryResults = [];
    presetEventSearch = '';
    presetInlineSearchRequestId += 1;
    window.clearTimeout(acTimer);
    window.clearTimeout(presetInlineSearchTimer);
    clearAutocompleteTranslationTimer();
    hideTagChipInfoTooltip();
    tagTooltip.classList.remove('open', 'ac-mode', 'chunk-ac-mode', 'preset-event-mode', 'preset-event-observed-mode', 'preset-event-staged-mode', 'preset-event-expression-mode');
    clearAutocompletePositionStyles();
  }

  function bindTagAssist(textarea, options = {}) {
    if (!textarea) return;
    textarea._excludeE621Autocomplete = !!options.excludeE621;
    const imeState = {
      composing: false,
      active: false,
      baseValue: '',
      start: 0,
      end: 0,
      data: '',
      stableTimer: null,
      settleTimer: null,
    };
    imeStates.set(textarea, imeState);
    const allowChunkBridge = !options.disableChunkBridge;
    let lastContextPointer = {type: '', time: 0};
    function clearImeTimers() {
      if (imeState.stableTimer) {
        window.clearTimeout(imeState.stableTimer);
        imeState.stableTimer = null;
      }
      if (imeState.settleTimer) {
        window.clearTimeout(imeState.settleTimer);
        imeState.settleTimer = null;
      }
    }
    function captureCompositionAnchor() {
      imeState.active = true;
      imeState.baseValue = String(textarea.value || '');
      const start = textarea.selectionStart != null ? textarea.selectionStart : imeState.baseValue.length;
      const end = textarea.selectionEnd != null ? textarea.selectionEnd : start;
      imeState.start = Math.max(0, Math.min(start, imeState.baseValue.length));
      imeState.end = Math.max(imeState.start, Math.min(end, imeState.baseValue.length));
    }
    function scheduleCompositionAutocomplete({force = false} = {}) {
      const override = compositionTextOverride(textarea);
      if (!override) return;
      const info = getActiveTokenInfo(textarea, override);
      if (!info) return;
      acTarget = textarea;
      scheduleAutocomplete({target: textarea, info, force});
    }
    function scheduleCompositionStableRetry() {
      if (imeState.stableTimer) window.clearTimeout(imeState.stableTimer);
      const override = compositionTextOverride(textarea);
      if (!override || !hangulRe.test(override.text)) return;
      imeState.stableTimer = window.setTimeout(() => {
        imeState.stableTimer = null;
        if (!imeState.active || !imeState.data) return;
        scheduleCompositionAutocomplete({force: true});
      }, HANGUL_COMPOSITION_STABLE_RETRY_MS);
    }
    function scheduleCompositionSettle() {
      if (imeState.settleTimer) window.clearTimeout(imeState.settleTimer);
      const settle = () => {
        imeState.settleTimer = null;
        imeState.active = false;
        imeState.data = '';
        scheduleAutocomplete({target: textarea, force: true});
      };
      const requestFrame = typeof window.requestAnimationFrame === 'function'
        ? window.requestAnimationFrame.bind(window)
        : null;
      if (requestFrame) {
        requestFrame(() => {
          imeState.settleTimer = window.setTimeout(settle, 50);
        });
      } else {
        imeState.settleTimer = window.setTimeout(settle, 50);
      }
    }
    function rememberContextPointer(event) {
      lastContextPointer = {
        type: String(event.pointerType || ''),
        time: Date.now(),
      };
    }
    function isMobileTextContextSurface() {
      const vv = window.visualViewport;
      const viewportWidth = vv ? vv.width : window.innerWidth;
      if (viewportWidth <= 767) return true;
      const mediaQuery = window.matchMedia?.('(hover: none), (pointer: coarse)');
      if (mediaQuery?.matches) return true;
      return Number(window.navigator?.maxTouchPoints || 0) > 0 && window.innerWidth <= 900;
    }
    function isDesktopSecondaryTextContextMenu(event) {
      const eventPointerType = typeof event.pointerType === 'string' ? event.pointerType : '';
      if (eventPointerType && eventPointerType !== 'mouse') return false;
      if (event.button !== 2 && event.buttons !== 2) return false;
      return !isMobileTextContextSurface();
    }
    function shouldUseNativeTextContextMenu(event) {
      if (!isDesktopSecondaryTextContextMenu(event)) return true;
      const eventPointerType = typeof event.pointerType === 'string' ? event.pointerType : '';
      if (eventPointerType) return eventPointerType !== 'mouse';
      const elapsed = Date.now() - (lastContextPointer.time || 0);
      if (elapsed >= 0 && elapsed < 2500 && lastContextPointer.type) {
        return lastContextPointer.type !== 'mouse';
      }
      return false;
    }
    textarea.addEventListener('compositionstart', () => {
      clearImeTimers();
      imeState.composing = true;
      imeState.data = '';
      captureCompositionAnchor();
    });
    textarea.addEventListener('compositionupdate', e => {
      if (!imeState.active) captureCompositionAnchor();
      imeState.composing = true;
      imeState.data = String(e.data || '');
      scheduleCompositionAutocomplete();
      scheduleCompositionStableRetry();
    });
    textarea.addEventListener('compositionend', e => {
      if (!imeState.active) captureCompositionAnchor();
      imeState.data = String(e.data || imeState.data || '');
      imeState.composing = false;
      if (imeState.stableTimer) {
        window.clearTimeout(imeState.stableTimer);
        imeState.stableTimer = null;
      }
      scheduleCompositionAutocomplete({force: true});
      scheduleCompositionSettle();
    });
    textarea.addEventListener('pointerdown', rememberContextPointer, true);
    textarea.addEventListener('input', e => {
      acTarget = textarea;
      if (imeState.composing || e.isComposing) {
        if (e.data) imeState.data = String(e.data);
        scheduleCompositionAutocomplete();
        scheduleCompositionStableRetry();
        return;
      }
      imeState.active = false;
      imeState.data = '';
      if (imeState.stableTimer) {
        window.clearTimeout(imeState.stableTimer);
        imeState.stableTimer = null;
      }
      scheduleAutocomplete({target: textarea});
    });
    textarea.addEventListener('click', () => {
      acTarget = textarea;
      if (acMode) hideAutocomplete();
      if (openPresetAutocompleteAtCursor(textarea)) return;
      checkTagHint();
    });
    textarea.addEventListener('keyup', e => {
      if (['ArrowLeft','ArrowRight','Home','End'].includes(e.key)) {
        if (acMode) hideAutocomplete();
        if (openPresetAutocompleteAtCursor(textarea)) return;
        checkTagHint();
      }
    });
    textarea.addEventListener('focus', () => {
      acTarget = textarea;
      if (!acMode && !openPresetAutocompleteAtCursor(textarea)) checkTagHint();
    });
    textarea.addEventListener('contextmenu', e => {
      const chunkPanelControl = getChunkPanelControl();
      if (!allowChunkBridge || textarea === negEdit || textarea.classList.contains('mod-uc')) return;
      // 선택 없는 데스크톱 우클릭에도 메뉴를 띄운다(리모트/Paste/Select all 등) —
      // 선택 의존 항목은 chunkPanel이 no-selection 클래스로 숨긴다. 모바일
      // 롱프레스는 아래 shouldUseNativeTextContextMenu가 네이티브로 돌려보낸다.
      if (!chunkPanelControl) return;
      if (shouldUseNativeTextContextMenu(e)) {
        chunkPanelControl.hideSelectionMenu?.();
        return;
      }
      acTarget = textarea;
      hideAutocomplete();
      if (chunkPanelControl.showSelectionMenu(textarea, e)) {
        e.preventDefault();
      }
    });
    textarea.addEventListener('blur', () => {
      window.setTimeout(() => {
        if (document.activeElement !== textarea && !tagTooltip.contains(document.activeElement)) {
          hideAutocomplete();
          hideTagChipInfoTooltip();
          tagTooltip.classList.remove('open', 'ac-mode', 'preset-event-mode', 'preset-event-observed-mode', 'preset-event-staged-mode', 'preset-event-expression-mode');
        }
      }, 200);
    });
    textarea.addEventListener('keydown', e => {
      if (imeState.composing || e.isComposing || e.keyCode === 229) return;
      if (!acMode || !acResults.length) return;
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        moveAutocompleteSelection(1);
        renderAutocomplete();
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        moveAutocompleteSelection(-1);
        renderAutocomplete();
      } else if ((e.key === 'Enter' || e.key === 'Tab') && acSel >= 0) {
        e.preventDefault();
        e.stopPropagation();
        selectAutocomplete(acSel);
      } else if (e.key === 'Escape') {
        e.preventDefault();
        hideAutocomplete();
        if (isPresetEventsQuery(getTagAtCursor(textarea)) || isPresetExpressionsQuery(getTagAtCursor(textarea))) return;
        checkTagHint();
      }
    });
  }

  function bindDefaultTextareas() {
    bindTagAssist(promptEdit);
    bindTagAssist(negEdit);
  }

  document.addEventListener('mousedown', e => {
    if (!promptInfoTooltip || !promptInfoTooltip.classList.contains('open')) return;
    const target = e.target;
    if (promptInfoTooltip.contains(target)) return;
    if (target?.closest?.('.generation-info-tag')) return;
    hidePromptInfoTooltip();
  }, true);
  window.addEventListener('resize', positionPromptInfoTooltip);
  window.addEventListener('scroll', positionPromptInfoTooltip, true);

  return {
    bindDefaultTextareas,
    bindTagAssist,
    lookupPromptInfoTag,
    hidePromptInfoTooltip,
    onTagLookupResult,
    onAutocompleteResult,
    positionTagTooltip,
    renderPromptInfoHtml,
    getTooltip: () => tagTooltip,
    getAcTarget: () => acTarget,
  };
}
