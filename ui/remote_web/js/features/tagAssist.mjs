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
  let lastAcQuery = '';
  let acTarget = null;

  function sendWs(payload) {
    const ws = getWs();
    if (!ws || ws.readyState !== WebSocket.OPEN) return false;
    ws.send(JSON.stringify(payload));
    return true;
  }

  function syncTooltipSide() {
    if (!tagTooltip || window.innerWidth < 768) return;
    const inModule = acTarget && acTarget.closest('.module-popup, .refine-popup, .tag-filter-popup');
    tagTooltip.classList.toggle('left-side', !!inModule);
  }

  function positionTagTooltip() {
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

  function getActiveTokenInfo(textarea) {
    const text = textarea.value;
    const pos = textarea.selectionStart != null ? textarea.selectionStart : -1;
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
      sendWs({type: 'tag_lookup', tag});
    }, 200);
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
    if (allowTriggers && (lower.startsWith('__') || lower.startsWith('$'))) return query;
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

  function scheduleAutocomplete() {
    const target = acTarget || promptEdit;
    const info = getActiveTokenInfo(target);
    const allowTriggers = target !== negEdit;
    const isChunkTrigger = !!(info && allowTriggers && info.stripped.startsWith('$'));
    if (!info || (!isChunkTrigger && info.stripped.length < 2)) {
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
    if (query === lastAcQuery) return;
    lastAcQuery = query;
    window.clearTimeout(acTimer);
    window.clearTimeout(tagLookupTimer);
    acTimer = window.setTimeout(() => {
      const s = query;
      if (allowTriggers && s.startsWith('__')) {
        const q = s.replace(/^_+/, '').replace(/_+$/, '');
        if (q.length >= 1) sendWs({type: 'autocomplete_wildcard', query: q});
      } else if (allowTriggers && s.startsWith('$')) {
        sendWs({type: 'autocomplete_chunk', query: s.slice(1).trim()});
      } else {
        sendWs({type: 'autocomplete', query: s});
      }
    }, 150);
  }

  function onAutocompleteResult(m) {
    const q = lastAcQuery;
    const matchesWc = q && q.startsWith('__') && m.query === q.replace(/^_+/, '').replace(/_+$/, '');
    const matchesChunk = q && q.startsWith('$') && m.query === q.slice(1).trim();
    if (!matchesWc && !matchesChunk && m.query !== q) return;
    const target = acTarget || promptEdit;
    const results = (m.results || []).filter(r => !(target && target._excludeE621Autocomplete && r.cat === 'e621'));
    if (!results.length) {
      hideAutocomplete();
      checkTagHint();
      return;
    }
    acResults = results;
    acSel = results.some(r => r._wc_type === 'chunk' || r._wc_type === 'chunk_group') ? 0 : -1;
    acMode = true;
    renderAutocomplete();
  }

  function chunkPreviewHtml(result) {
    if (!result) return '';
    const title = result._wc_type === 'chunk_group' ? `$${result.tag}` : `$${result.tag}`;
    const meta = result._wc_type === 'chunk_group'
      ? `${result.desc || ''}`
      : `${result.group || ''}`;
    const body = result.preview || result.value || result.desc || '';
    return '<div class="chunk-ac-preview-title">' + escHtml(title) + '</div>' +
      (meta ? '<div class="chunk-ac-preview-meta">' + escHtml(meta) + '</div>' : '') +
      '<pre class="chunk-ac-preview-body">' + escHtml(body) + '</pre>';
  }

  function renderAutocomplete() {
    hideTagChipInfoTooltip();
    const chunkMode = acResults.some(r => r._wc_type === 'chunk' || r._wc_type === 'chunk_group');
    let html = chunkMode ? '<div class="chunk-ac-layout"><div class="tag-ac-list chunk-ac-list">' : '<div class="tag-ac-list">';
    acResults.forEach((r, i) => {
      const sel = i === acSel ? ' selected' : '';
      const wcType = r._wc_type;
      const tagColor = wcType ? catStyle(wcType) : catStyle(r.cat);
      const prefix = wcType === 'wildcard' ? '__' : (wcType === 'chunk' || wcType === 'chunk_group' ? '$' : '');
      const suffix = wcType === 'wildcard' ? '__' : (wcType === 'chunk_group' ? ':' : '');
      const itemClass = chunkMode ? ' chunk-ac-item' : '';
      html += `<div class="tag-ac-item${itemClass}${sel}" data-idx="${i}">` +
        `<span class="tag-ac-tag"${tagColor}>${escHtml(prefix + r.tag + suffix)}</span>` +
        `<span class="tag-ac-group">${escHtml(r.group || '')}</span>` +
        `<span class="tag-ac-count">${wcType ? escHtml(r.desc || '') : fmtCount(r.count)}</span>` +
        (chunkMode ? `<span class="chunk-ac-inline-preview">${escHtml(r.preview || r.value || '')}</span>` : '') +
        '</div>';
    });
    html += chunkMode
      ? `</div><div class="chunk-ac-preview">${chunkPreviewHtml(acResults[Math.max(0, acSel)] || acResults[0])}</div></div>`
      : '</div>';
    tagTooltip.innerHTML = html;
    tagTooltip.classList.add('open', 'ac-mode');
    tagTooltip.classList.toggle('chunk-ac-mode', chunkMode);
    syncTooltipSide();
    positionTagTooltip();
    tagTooltip.querySelectorAll('.tag-ac-item').forEach(el => {
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
    const target = acTarget || promptEdit;
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
      swapToken(target, info, r.value || `$${r.tag}:`);
      hideAutocomplete();
      return;
    }
    if (r._wc_type === 'chunk') {
      swapToken(target, info, r.value || '');
      hideAutocomplete();
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
    window.clearTimeout(acTimer);
    hideTagChipInfoTooltip();
    tagTooltip.classList.remove('open', 'ac-mode', 'chunk-ac-mode');
  }

  function bindTagAssist(textarea, options = {}) {
    if (!textarea) return;
    textarea._excludeE621Autocomplete = !!options.excludeE621;
    let composing = false;
    const allowChunkBridge = !options.disableChunkBridge;
    function hasTextSelection() {
      return textarea.selectionStart != null
        && textarea.selectionEnd != null
        && textarea.selectionStart !== textarea.selectionEnd
        && textarea.value.substring(textarea.selectionStart, textarea.selectionEnd).trim().length > 0;
    }
    textarea.addEventListener('compositionstart', () => { composing = true; });
    textarea.addEventListener('compositionend', () => {
      composing = false;
      scheduleAutocomplete();
    });
    textarea.addEventListener('input', () => {
      acTarget = textarea;
      if (!composing) scheduleAutocomplete();
    });
    textarea.addEventListener('click', () => {
      acTarget = textarea;
      if (acMode) hideAutocomplete();
      checkTagHint();
    });
    textarea.addEventListener('keyup', e => {
      if (['ArrowLeft','ArrowRight','Home','End'].includes(e.key)) {
        if (acMode) hideAutocomplete();
        checkTagHint();
      }
    });
    textarea.addEventListener('focus', () => {
      acTarget = textarea;
      if (!acMode) checkTagHint();
    });
    textarea.addEventListener('contextmenu', e => {
      const chunkPanelControl = getChunkPanelControl();
      if (!allowChunkBridge || textarea === negEdit || textarea.classList.contains('mod-uc')) return;
      if (!hasTextSelection() || !chunkPanelControl) return;
      acTarget = textarea;
      hideAutocomplete();
      if (chunkPanelControl.showSelectionMenu(textarea, e)) {
        e.preventDefault();
      }
    });
    textarea.addEventListener('blur', () => {
      window.setTimeout(() => {
        if (document.activeElement !== textarea) {
          hideAutocomplete();
          hideTagChipInfoTooltip();
          tagTooltip.classList.remove('open', 'ac-mode');
        }
      }, 200);
    });
    textarea.addEventListener('keydown', e => {
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
