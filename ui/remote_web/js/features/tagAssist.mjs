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
  let presetInlineSearchTimer = null;
  let lastAcQuery = '';
  let lastTranslationRequestQuery = '';
  let acTarget = null;
  let presetAutocompleteMeta = null;
  let presetEventContext = {ratingId: 's', personId: '1girl_solo'};
  let presetPersonMenuOpen = false;
  let presetEventSourceResults = [];
  let presetEventSearch = '';
  let presetInlineSearchRequestId = 0;
  const hangulRe = /[가-힣ㄱ-ㅎㅏ-ㅣ]/;
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

  function isPresetClothesQuery(query) {
    return String(query || '').trim().toLowerCase().startsWith('preset:clothes');
  }

  function isLocalPresetQuery(query) {
    return isPresetEventsQuery(query) || isPresetClothesQuery(query);
  }

  function isClothesEmptyStagedSegmentAtCursor(info, textarea) {
    const token = String(info?.stripped || '');
    if (!textarea || !isPresetClothesQuery(token)) return false;
    const prefix = 'preset:clothes';
    let tailStart = prefix.length;
    while (token[tailStart] === '/') tailStart += 1;
    const tail = token.slice(tailStart);
    if (!tail.includes('&')) return false;

    const cursor = textarea.selectionStart != null ? Number(textarea.selectionStart) : info.end;
    const tokenOffset = Math.max(0, String(info.raw || '').indexOf(token));
    const tokenCursor = Math.max(0, Math.min(cursor - info.start - tokenOffset, token.length));
    const tailCursor = Math.max(0, Math.min(tokenCursor - tailStart, tail.length));
    const segments = tail.split('&');
    let start = 0;
    for (const segment of segments) {
      const end = start + segment.length;
      if (tailCursor >= start && tailCursor <= end) {
        return segment.length === 0;
      }
      start = end + 1;
    }
    return false;
  }

  function presetQueryAxis(query) {
    if (isPresetClothesQuery(query)) return 'clothes';
    if (isPresetEventsQuery(query)) return 'events';
    return '';
  }

  function presetEventTokenStage(token) {
    const raw = String(token || '').trim();
    if (!isPresetEventsQuery(raw)) return '';
    const tail = raw.slice('preset:events'.length).replace(/^\/+/, '');
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
    const raw = String(token || '').trim();
    if (!isPresetEventsQuery(raw)) return '';
    return raw.slice('preset:events'.length).replace(/^\/+/, '');
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
    if (isPresetEventsQuery(query)) {
      payload.presetContext = {...presetEventContext};
    }
    return payload;
  }

  function presetStatusRow(query, message, status = 'preset', axis = 'events') {
    return {
      tag: String(status || 'preset'),
      value: query,
      count: 0,
      desc: message || `${axis === 'clothes' ? 'Clothes' : 'Event'} Preset data is not ready.`,
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
    mirror.style.wordBreak = 'break-word';
    mirror.style.overflowWrap = 'break-word';
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
    const maxWidth = Math.max(280, Math.min(560, viewport.width - margin * 2));
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
    root.querySelectorAll('.tag-ac-item[data-tooltip-desc]').forEach(el => {
      el.addEventListener('mouseenter', () => showTagChipInfoTooltip(el));
      el.addEventListener('mousemove', () => positionTagChipInfoTooltip(el));
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
    tagTooltip.classList.remove('open', 'ac-mode', 'left-side');
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
    return axis === 'clothes' ? 'Clothes' : 'Event';
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
    tagTooltip.classList.remove('open', 'ac-mode', 'left-side', 'preset-event-mode');
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
        target.value = text.substring(0, info.end) + ', ' + tag + text.substring(info.end);
        const newPos = info.end + 2 + tag.length;
        target.selectionStart = target.selectionEnd = newPos;
        target.focus();
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
      tagTooltip.classList.remove('open', 'ac-mode', 'left-side', 'preset-event-mode');
      positionPromptInfoTooltip();
    } else {
      hidePromptInfoTooltip();
      tagTooltip.classList.remove('ac-mode', 'preset-event-mode');
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
    if (normalized === 'category') return 'Slot';
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
      return short ? 'Random seed' : 'Generation uses these staged tags as a random Clothes seed';
    }
    return short ? 'Fixed tags' : 'Generation applies exactly these staged tags';
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
      tagTooltip.classList.remove('open', 'ac-mode', 'left-side', 'preset-event-mode');
      positionPromptInfoTooltip();
    } else {
      hidePromptInfoTooltip();
      tagTooltip.classList.remove('ac-mode', 'preset-event-mode');
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

  function positionTagChipInfoTooltip(anchor) {
    if (!tagChipInfoTooltip || !tagChipInfoTooltip.classList.contains('open')) return;
    const rect = anchor.getBoundingClientRect();
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
    let left = Math.max(minLeft, Math.min(rect.left, maxLeft));
    let top = rect.bottom + gap;
    const bottomLimit = viewport.offsetTop + viewport.height - margin;
    if (top + tipRect.height > bottomLimit) top = rect.top - tipRect.height - gap;
    top = Math.max(viewport.offsetTop + margin, top);
    tagChipInfoTooltip.style.left = `${Math.round(left)}px`;
    tagChipInfoTooltip.style.top = `${Math.round(top)}px`;
  }

  function showTagChipInfoTooltip(anchor) {
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
    positionTagChipInfoTooltip(anchor);
  }

  function bindTagChipInfoHover(root) {
    root.querySelectorAll('.tag-tooltip-extra-tag[data-tooltip-desc]').forEach(el => {
      el.addEventListener('mouseenter', () => showTagChipInfoTooltip(el));
      el.addEventListener('mousemove', () => positionTagChipInfoTooltip(el));
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
      tagTooltip.classList.remove('open', 'ac-mode');
      return;
    }
    hideTagChipInfoTooltip();
    tagTooltip.classList.remove('open', 'ac-mode');
    window.clearTimeout(tagLookupTimer);
    tagLookupTimer = window.setTimeout(() => {
      if (isLocalPresetQuery(tag)) {
        void lookupPresetEventTokenInfo(tag, {readOnly: false});
        return;
      }
      sendWs({type: 'tag_lookup', tag});
    }, 200);
  }

  function openClothesStagedAutocompleteAtCursor(textarea) {
    const target = textarea || acTarget || promptEdit;
    const info = getActiveTokenInfo(target);
    if (!isClothesEmptyStagedSegmentAtCursor(info, target)) return false;
    acTarget = target;
    lastLookupTag = '';
    window.clearTimeout(tagLookupTimer);
    hidePromptInfoTooltip();
    hideTagChipInfoTooltip();
    scheduleAutocomplete({target, info, force: true});
    return true;
  }

  function onTagLookupResult(m) {
    if (acMode) return;
    hideTagChipInfoTooltip();
    if (!m.tag) {
      if (tagLookupReadOnly) {
        hidePromptInfoTooltip();
      } else {
        tagTooltip.classList.remove('open', 'ac-mode');
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
      tagTooltip.classList.remove('open', 'ac-mode', 'left-side');
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
        target.value = text.substring(0, info.end) + ', ' + tag + text.substring(info.end);
        const newPos = info.end + 2 + tag.length;
        target.selectionStart = target.selectionEnd = newPos;
        target.focus();
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

  function scheduleAutocompleteTranslation(query, allowTriggers) {
    clearAutocompleteTranslationTimer();
    if (!query || !hangulRe.test(query) || isAutocompleteControlQuery(query, allowTriggers)) return;
    if (lastTranslationRequestQuery === query) return;
    acTranslationTimer = window.setTimeout(() => {
      acTranslationTimer = null;
      if (lastAcQuery !== query) return;
      lastTranslationRequestQuery = query;
      sendWs({type: 'autocomplete_translate', query});
    }, 2000);
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
    lastAcQuery = query;
    scheduleAutocompleteTranslation(query, allowTriggers);
    window.clearTimeout(acTimer);
    window.clearTimeout(tagLookupTimer);
    acTimer = window.setTimeout(() => {
      const s = query;
      if (allowTriggers && s.startsWith('__')) {
        const q = s.replace(/^_+/, '').replace(/_+$/, '');
        if (q.length >= 1) sendWs({type: 'autocomplete_wildcard', query: q});
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
    const matchesWc = q && q.startsWith('__') && m.query === q.replace(/^_+/, '').replace(/_+$/, '');
    const matchesChunk = q && q.startsWith('$') && m.query === q.slice(1).trim();
    const matchesVibeCluster = q && q.toLowerCase().startsWith('vibe:') && m.query === q.slice(5).trim();
    const matchesPreset = q && q.toLowerCase().startsWith('preset:') && m.query === q;
    if (!matchesWc && !matchesChunk && !matchesVibeCluster && !matchesPreset && m.query !== q) return false;
    const target = acTarget || promptEdit;
    let results = (m.results || []).filter(r => !(target && target._excludeE621Autocomplete && r.cat === 'e621'));
    presetAutocompleteMeta = matchesPreset ? (m.preset || null) : null;
    if (presetAutocompleteMeta?.axis === 'events' || presetAutocompleteMeta?.axis === 'clothes') {
      presetEventSourceResults = results;
      results = filteredPresetEventResults();
    } else {
      presetEventSourceResults = [];
      presetEventSearch = '';
    }
    const context = presetAutocompleteMeta?.context || {};
    if (context.ratingId || context.personId) {
      presetEventContext = {
        ratingId: context.ratingId || presetEventContext.ratingId,
        personId: context.personId || presetEventContext.personId,
      };
    }
    if (!results.length) {
      hideAutocomplete();
      checkTagHint();
      return true;
    }
    acResults = results;
    acSel = results.some(r => (
      r._wc_type === 'chunk' ||
      r._wc_type === 'chunk_group' ||
      r._wc_type === 'vibe_cluster' ||
      r._wc_type === 'preset_path' ||
      r._wc_type === 'preset_status'
    )) ? 0 : -1;
    acMode = true;
    renderAutocomplete();
    return true;
  }

  function onAutocompleteResult(m) {
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
      showPresetEventStatus(requestQuery, `${axis === 'clothes' ? 'Clothes' : 'Event'} Preset page is not loaded yet.`, 'unavailable', axis);
      return false;
    }
    if (showLoading) {
      showPresetEventStatus(requestQuery, `Loading ${axis === 'clothes' ? 'Clothes' : 'Event'} Preset page...`, 'loading', axis);
    }
    try {
      const target = acTarget || promptEdit;
      const info = getActiveTokenInfo(target);
      const caretOffset = info ? Math.max(0, (target?.selectionStart || 0) - info.start) : null;
      const payload = await panel.getPresetAutocompletePayload(requestQuery, {
        context: {...presetEventContext},
        limit: 500,
        caretOffset,
        search: axis === 'clothes' ? requestSearch : '',
      });
      if (lastAcQuery !== requestQuery) return true;
      if (axis === 'clothes') {
        if (inlineSearchRequestId !== null && inlineSearchRequestId !== presetInlineSearchRequestId) return true;
        if ((restoreSearchFocus || inlineSearchRequestId !== null) && requestSearch !== presetEventSearch) return true;
      }
      const applied = applyAutocompleteResult({
        type: 'autocomplete_result',
        query: payload?.query || requestQuery,
        results: payload?.results || [],
        preset: payload?.preset || {},
      });
      if (restoreSearchFocus && axis === 'clothes') {
        const searchInput = tagTooltip.querySelector('[data-preset-event-search]');
        if (searchInput) {
          searchInput.focus({preventScroll: true});
          searchInput.selectionStart = searchInput.selectionEnd = searchInput.value.length;
        }
      }
      return applied;
    } catch (error) {
      if (lastAcQuery !== requestQuery) return false;
      if (axis === 'clothes') {
        if (inlineSearchRequestId !== null && inlineSearchRequestId !== presetInlineSearchRequestId) return false;
        if ((restoreSearchFocus || inlineSearchRequestId !== null) && requestSearch !== presetEventSearch) return false;
      }
      showPresetEventStatus(requestQuery, error?.message || `${axis === 'clothes' ? 'Clothes' : 'Event'} Preset page load failed.`, 'error', axis);
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

  function presetEventParentToken(token) {
    const raw = String(token || '').trim();
    if (!raw.toLowerCase().startsWith('preset:events')) return '';
    const path = raw.slice('preset:events'.length).replace(/^\/+/, '');
    const segments = path ? path.split('/').filter(Boolean) : [];
    if (!segments.length) return '';
    const parent = segments.slice(0, -1);
    return `preset:events${parent.length ? '/' + parent.join('/') : ''}`;
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

  function presetParentToken(token) {
    const axis = presetAutocompleteMeta?.axis || presetQueryAxis(token);
    if (axis === 'clothes') return presetClothesParentToken(token, presetAutocompleteMeta?.parsed || null);
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
    target.focus();
    requestPresetAutocomplete(result.token);
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
    return axis === 'clothes' ? presetClothesStageLabel(stage) : presetEventStageText(stage);
  }

  function presetAutocompletePathParts() {
    const axis = presetAutocompleteMeta?.axis || 'events';
    const crumbs = Array.isArray(presetAutocompleteMeta?.crumbs) ? presetAutocompleteMeta.crumbs : [];
    if (axis === 'clothes') {
      const parsed = presetAutocompleteMeta?.parsed || {};
      const stagedTags = presetClothesResolveTags(parsed);
      const stagedLabel = stagedTags.length
        ? stagedTags.slice(0, 3).join(' + ') + (stagedTags.length > 3 ? ' + ...' : '')
        : '';
      return ['Clothes', stagedLabel, ...crumbs.map(crumb => crumb?.label).filter(Boolean)].filter(Boolean);
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
    const generationText = axis === 'clothes'
      ? presetClothesGenerationText(presetAutocompleteMeta?.parsed || {}, {short: true})
      : '';
    const stageText = [
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

  function renderPresetEventAutocomplete() {
    const context = presetAutocompleteMeta?.context || {};
    let html = '<div class="preset-event-picker">' +
      renderPresetEventToolbar(context) +
      renderPresetEventStageLine() +
      '<div class="tag-ac-list preset-event-list">';
    acResults.forEach((r, i) => {
      const sel = i === acSel ? ' selected' : '';
      const disabled = r._wc_type === 'preset_status' || r.disabled;
      const itemClass = disabled ? ' disabled' : '';
      const countText = r.count ? fmtCount(r.count || 0) : '';
      const displayTag = eventPresetDisplayTag(r);
      const descText = r.desc || r.prompt || rowTags(r).join(', ');
      html += `<div class="tag-ac-item preset-event-item${itemClass}${sel}" data-idx="${i}"${autocompleteInfoAttrs(r, displayTag, descText)}>` +
        `<span class="tag-ac-tag">${escHtml(displayTag)}</span>` +
        `<span class="tag-ac-count">${escHtml(countText)}</span>` +
        '</div>';
    });
    if (!acResults.length) {
      html += '<div class="preset-event-empty">No matches</div>';
    }
    html += '</div></div>';
    tagTooltip.innerHTML = html;
    tagTooltip.classList.add('open', 'ac-mode', 'preset-event-mode');
    tagTooltip.classList.remove('chunk-ac-mode');
    positionTagTooltip();

    const toolbar = tagTooltip.querySelector('.preset-event-toolbar');
    if (toolbar) toolbar.addEventListener('mousedown', e => e.preventDefault());
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
        } else {
          acResults = filteredPresetEventResults();
          acSel = acResults.length ? 0 : -1;
          renderAutocomplete();
          const nextInput = tagTooltip.querySelector('[data-preset-event-search]');
          if (nextInput) {
            nextInput.focus({preventScroll: true});
            nextInput.selectionStart = nextInput.selectionEnd = nextInput.value.length;
          }
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
          } else {
            acResults = filteredPresetEventResults();
            acSel = acResults.length ? 0 : -1;
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
        presetPersonMenuOpen = false;
        presetEventSearch = '';
        presetEventContext = {...presetEventContext, ratingId: nextRating};
        renderAutocomplete();
        requestPresetAutocomplete(lastAcQuery);
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
        presetPersonMenuOpen = false;
        presetEventSearch = '';
        presetEventContext = {...presetEventContext, personId: nextPerson};
        renderAutocomplete();
        requestPresetAutocomplete(lastAcQuery);
      });
    });
    tagTooltip.querySelectorAll('.preset-event-item').forEach(el => {
      el.addEventListener('mousedown', e => {
        e.preventDefault();
        presetPersonMenuOpen = false;
        const idx = +el.dataset.idx;
        if (Number.isInteger(idx)) selectAutocomplete(idx);
      });
    });
    bindAutocompleteInfoHover(tagTooltip);
  }

  function renderAutocomplete() {
    hideTagChipInfoTooltip();
    if (presetAutocompleteMeta?.axis === 'events' || presetAutocompleteMeta?.axis === 'clothes') {
      renderPresetEventAutocomplete();
      return;
    }
    const chunkMode = acResults.some(r => r._wc_type === 'chunk' || r._wc_type === 'chunk_group' || r._wc_type === 'vibe_cluster');
    let html = chunkMode ? '<div class="chunk-ac-layout"><div class="tag-ac-list chunk-ac-list">' : '<div class="tag-ac-list">';
    acResults.forEach((r, i) => {
      const sel = i === acSel ? ' selected' : '';
      const wcType = r._wc_type;
      const tagColor = wcType ? catStyle(wcType) : catStyle(r.cat);
      const prefix = wcType === 'wildcard' ? '__' : (wcType === 'vibe_cluster' ? 'vibe:' : (wcType === 'chunk' || wcType === 'chunk_group' ? '$' : ''));
      const suffix = wcType === 'wildcard' ? '__' : (wcType === 'chunk_group' ? ':' : '');
      const itemClass = chunkMode ? ' chunk-ac-item' : '';
      const displayTag = wcType === 'preset_path'
        ? (r.value || r.tag || '')
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
    tagTooltip.classList.remove('preset-event-mode');
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
        selectAutocomplete(+el.dataset.idx);
      });
    });
  }

  function selectAutocomplete(idx) {
    const r = acResults[idx];
    if (!r) return;
    if (r.disabled) return;
    const target = acTarget || promptEdit;
    if (isImeComposing(target)) return;
    const info = getActiveTokenInfo(target);
    if (!info) return;
    let newTag = r.tag;
    if (r._wc_type === 'wildcard') {
      newTag = '__' + r.tag + '__';
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

  function swapToken(textarea, tokenInfo, newTag) {
    const text = textarea.value;
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
    textarea.focus();
    if (textarea === promptEdit) onPromptEdit();
    else fireModuleOninput(textarea);
  }

  function hideAutocomplete() {
    acMode = false;
    acResults = [];
    acSel = -1;
    lastAcQuery = '';
    lastTranslationRequestQuery = '';
    presetAutocompleteMeta = null;
    presetPersonMenuOpen = false;
    presetEventSourceResults = [];
    presetEventSearch = '';
    presetInlineSearchRequestId += 1;
    window.clearTimeout(acTimer);
    window.clearTimeout(presetInlineSearchTimer);
    clearAutocompleteTranslationTimer();
    hideTagChipInfoTooltip();
    tagTooltip.classList.remove('open', 'ac-mode', 'chunk-ac-mode', 'preset-event-mode');
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
      }, 2000);
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
    function hasTextSelection() {
      return textarea.selectionStart != null
        && textarea.selectionEnd != null
        && textarea.selectionStart !== textarea.selectionEnd
        && textarea.value.substring(textarea.selectionStart, textarea.selectionEnd).trim().length > 0;
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
      if (openClothesStagedAutocompleteAtCursor(textarea)) return;
      checkTagHint();
    });
    textarea.addEventListener('keyup', e => {
      if (['ArrowLeft','ArrowRight','Home','End'].includes(e.key)) {
        if (acMode) hideAutocomplete();
        if (openClothesStagedAutocompleteAtCursor(textarea)) return;
        checkTagHint();
      }
    });
    textarea.addEventListener('focus', () => {
      acTarget = textarea;
      if (!acMode && !openClothesStagedAutocompleteAtCursor(textarea)) checkTagHint();
    });
    textarea.addEventListener('contextmenu', e => {
      const chunkPanelControl = getChunkPanelControl();
      if (!allowChunkBridge || textarea === negEdit || textarea.classList.contains('mod-uc')) return;
      if (!hasTextSelection() || !chunkPanelControl) return;
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
          tagTooltip.classList.remove('open', 'ac-mode');
        }
      }, 200);
    });
    textarea.addEventListener('keydown', e => {
      if (imeState.composing || e.isComposing || e.keyCode === 229) return;
      if (!acMode || !acResults.length) return;
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        acSel = Math.min(acSel + 1, acResults.length - 1);
        renderAutocomplete();
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        acSel = Math.max(acSel - 1, -1);
        renderAutocomplete();
      } else if ((e.key === 'Enter' || e.key === 'Tab') && acSel >= 0) {
        e.preventDefault();
        e.stopPropagation();
        selectAutocomplete(acSel);
      } else if (e.key === 'Escape') {
        e.preventDefault();
        hideAutocomplete();
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
    onTagLookupResult,
    onAutocompleteResult,
    positionTagTooltip,
    renderPromptInfoHtml,
    getTooltip: () => tagTooltip,
    getAcTarget: () => acTarget,
  };
}
