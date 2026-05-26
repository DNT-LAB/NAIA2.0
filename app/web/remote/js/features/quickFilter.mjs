const STORAGE_KEY = 'naia_quick_filter_options';
const RATING_KEYS = ['g', 's', 'q', 'e'];
const DEFAULT_RATING_KEYS = ['g', 's', 'q'];

export function normalizeRatings(value) {
  if (!Array.isArray(value)) return [...DEFAULT_RATING_KEYS];
  const picked = RATING_KEYS.filter(key => value.includes(key));
  return picked.length ? picked : [...DEFAULT_RATING_KEYS];
}

export function normalizeTags(value) {
  if (!Array.isArray(value)) return [];
  const seen = new Set();
  const out = [];
  value.forEach(item => {
    const tag = String(item || '').trim().replace(/^-+/, '').replace(/ /g, '_');
    if (!tag || seen.has(tag)) return;
    seen.add(tag);
    out.push(tag);
  });
  return out;
}

export function normalizePreferences(raw) {
  if (!raw || typeof raw !== 'object') return null;
  const include = normalizeTags(raw.tag_filter || raw.include || raw.include_tags);
  const exclude = normalizeTags(raw.tag_filter_exclude || raw.exclude || raw.exclude_tags);
  return {
    ratings: normalizeRatings(raw.ratings),
    tag_filter: include,
    tag_filter_exclude: exclude,
    tag_filter_active: !!raw.tag_filter_active && (include.length > 0 || exclude.length > 0),
  };
}

export function hasCustomPreferences(pref) {
  if (!pref) return false;
  const ratings = normalizeRatings(pref.ratings);
  const defaultRatings = ratings.length === DEFAULT_RATING_KEYS.length
    && DEFAULT_RATING_KEYS.every(key => ratings.includes(key));
  return !defaultRatings
    || (pref.tag_filter && pref.tag_filter.length > 0)
    || (pref.tag_filter_exclude && pref.tag_filter_exclude.length > 0)
    || !!pref.tag_filter_active;
}

export function loadPreferences(storage = localStorage) {
  try {
    const raw = storage.getItem(STORAGE_KEY);
    return raw ? normalizePreferences(JSON.parse(raw)) : null;
  } catch (_) {
    return null;
  }
}

export function savePreferences(pref, storage = localStorage) {
  try {
    if (hasCustomPreferences(pref)) {
      storage.setItem(STORAGE_KEY, JSON.stringify(pref));
    } else {
      storage.removeItem(STORAGE_KEY);
    }
  } catch (_) {}
}

export function createQuickFilterController(deps) {
  const doc = deps.document;
  const storage = deps.localStorage;
  const SocketClass = deps.WebSocket;

  let includeTags = [];
  let excludeTags = [];
  let active = false;
  let acResults = [];
  let acSelection = -1;
  let acTimer = null;
  let pendingAssignOnRestore = false;
  let ratingCounts = null;
  let acTarget = 'include';
  let searchSeq = 0;
  let latestSearchRequestId = '';

  const getEl = id => doc.getElementById(id);
  const isSocketOpen = () => {
    const socket = deps.getWs();
    return socket && socket.readyState === SocketClass.OPEN;
  };
  const send = payload => {
    if (!isSocketOpen()) return;
    deps.getWs().send(JSON.stringify(payload));
  };
  const getActiveRatings = () => {
    const ratingState = deps.getRatingState();
    return RATING_KEYS.filter(key => ratingState[key]);
  };
  const setActiveRatings = ratings => {
    const normalized = normalizeRatings(ratings);
    const ratingState = deps.getRatingState();
    RATING_KEYS.forEach(key => {
      ratingState[key] = normalized.includes(key);
    });
  };
  const payload = () => [...includeTags, ...excludeTags.map(tag => '-' + tag)];
  const nextSearchRequestId = () => {
    searchSeq += 1;
    latestSearchRequestId = `tf-${Date.now()}-${searchSeq}`;
    return latestSearchRequestId;
  };
  const invalidateSearchRequest = () => {
    searchSeq += 1;
    latestSearchRequestId = '';
  };
  const collectPreferences = () => ({
    ratings: getActiveRatings(),
    tag_filter: [...includeTags],
    tag_filter_exclude: [...excludeTags],
    tag_filter_active: active,
  });

  function updateHighlight() {
    const toggleBtn = getEl('tagFilterToggle');
    if (!toggleBtn) return;
    const control = toggleBtn.closest('.prompt-quick-control');
    const highlighted = hasCustomPreferences(collectPreferences());
    if (control) control.classList.toggle('quick-filter-memory', highlighted);
    toggleBtn.title = highlighted
      ? 'Quick filter settings are saved'
      : 'Open quick filter';
  }

  function save() {
    const preferences = collectPreferences();
    savePreferences(preferences, storage);
    updateHighlight();
    send({type: 'save_search_filter_state', ...preferences});
  }

  function load() {
    return loadPreferences(storage);
  }

  function renderIncludeChips() {
    const el = getEl('tagFilterChips');
    if (!el) return;
    if (!includeTags.length) {
      el.innerHTML = '';
      return;
    }
    el.innerHTML = includeTags.map((tag, index) =>
      `<span class="tag-filter-chip">${deps.escHtml(tag)}<span class="chip-x" onclick="removeTagFilterTag(${index})">&times;</span></span>`
    ).join('');
  }

  function renderExcludeChips() {
    const el = getEl('tagFilterExcludeChips');
    if (!el) return;
    if (!excludeTags.length) {
      el.innerHTML = '';
      return;
    }
    el.innerHTML = excludeTags.map((tag, index) =>
      `<span class="tag-filter-chip exclude">${deps.escHtml(tag)}<span class="chip-x" onclick="removeTagFilterExcludeTag(${index})">&times;</span></span>`
    ).join('');
  }

  function clearAutocomplete() {
    acResults = [];
    acSelection = -1;
    const el = getEl('tagFilterAc');
    if (el) el.innerHTML = '';
  }

  function renderAutocomplete() {
    const el = getEl('tagFilterAc');
    if (!el) return;
    if (!acResults.length) {
      el.innerHTML = '';
      return;
    }
    let html = '<div class="tag-ac-list">';
    acResults.forEach((result, index) => {
      const selected = index === acSelection ? ' selected' : '';
      const tagColor = deps.catStyle(result.cat);
      html += `<div class="tag-ac-item${selected}" data-idx="${index}">`
        + `<span class="tag-ac-tag"${tagColor}>${deps.escHtml(result.tag)}</span>`
        + `<span class="tag-ac-group">${deps.escHtml(result.group || '')}</span>`
        + `<span class="tag-ac-count">${deps.fmtCount(result.count)}</span>`
        + '</div>';
    });
    html += '</div>';
    el.innerHTML = html;
    el.querySelectorAll('.tag-ac-item').forEach(item => {
      item.addEventListener('mousedown', event => {
        event.preventDefault();
        selectAutocomplete(acResults[+item.dataset.idx].tag);
      });
    });
  }

  function selectAutocomplete(tag) {
    const clean = String(tag || '').replace(/ /g, '_');
    if (!clean) return;
    if (acTarget === 'exclude') {
      if (!excludeTags.includes(clean)) {
        excludeTags.push(clean);
        renderExcludeChips();
        save();
      }
      const input = getEl('tagFilterExcludeInput');
      if (input) input.value = '';
    } else {
      if (!includeTags.includes(clean)) {
        includeTags.push(clean);
        renderIncludeChips();
        save();
      }
      const input = getEl('tagFilterInput');
      if (input) input.value = '';
    }
    clearAutocomplete();
  }

  function bindAutocompleteInput(inputId, target) {
    const input = getEl(inputId);
    if (!input) return;

    input.addEventListener('focus', () => {
      acTarget = target;
    });

    input.addEventListener('input', function() {
      acTarget = target;
      const query = this.value.trim();
      if (query.length < 2) {
        clearAutocomplete();
        return;
      }
      clearTimeout(acTimer);
      acTimer = setTimeout(() => {
        send({type: 'tag_filter_ac', query});
      }, 150);
    });

    input.addEventListener('keydown', function(event) {
      if (event.key === 'ArrowDown') {
        event.preventDefault();
        acSelection = Math.min(acSelection + 1, acResults.length - 1);
        renderAutocomplete();
      } else if (event.key === 'ArrowUp') {
        event.preventDefault();
        acSelection = Math.max(acSelection - 1, -1);
        renderAutocomplete();
      } else if (event.key === 'Enter') {
        event.preventDefault();
        if (acSelection >= 0 && acResults[acSelection]) {
          selectAutocomplete(acResults[acSelection].tag);
        } else if (this.value.trim()) {
          selectAutocomplete(this.value.trim());
        }
      } else if (event.key === 'Escape') {
        clearAutocomplete();
      }
    });
  }

  function bindInputs() {
    bindAutocompleteInput('tagFilterInput', 'include');
    bindAutocompleteInput('tagFilterExcludeInput', 'exclude');
  }

  function open() {
    const popup = getEl('tagFilterPopup');
    if (!popup) return;
    deps.closeAuxiliaryPopups(popup);
    popup.classList.add('open');
    const toggleBtn = getEl('tagFilterToggle');
    if (toggleBtn) toggleBtn.classList.add('active');
    renderIncludeChips();
    const input = getEl('tagFilterInput');
    if (input) input.focus();
  }

  function close() {
    const popup = getEl('tagFilterPopup');
    if (popup) popup.classList.remove('open');
    if (!active) {
      const toggleBtn = getEl('tagFilterToggle');
      if (toggleBtn) toggleBtn.classList.remove('active');
    }
    clearAutocomplete();
  }

  function toggle() {
    const popup = getEl('tagFilterPopup');
    if (!popup) return;
    if (popup.classList.contains('open')) close();
    else open();
  }

  function clearFilter(options = {}) {
    const sendClear = options.sendClear !== false;
    const persist = options.persist !== false;

    includeTags = [];
    excludeTags = [];
    active = false;
    ratingCounts = null;
    pendingAssignOnRestore = false;
    invalidateSearchRequest();
    renderIncludeChips();
    renderExcludeChips();

    const countEl = getEl('tagFilterCount');
    if (countEl) {
      countEl.textContent = '';
      countEl.classList.remove('has-result');
    }
    const toggleBtn = getEl('tagFilterToggle');
    if (toggleBtn) {
      toggleBtn.classList.remove('active');
      toggleBtn.classList.remove('assigned');
    }
    const assignBtn = getEl('tagFilterAssignBtn');
    if (assignBtn) assignBtn.disabled = true;

    const restored = deps.computeLocalFilteredCount();
    if (restored !== null && restored !== undefined) deps.updateSearchCount(restored);
    if (sendClear) send({type: 'tag_filter_clear'});
    if (persist) save();
    else updateHighlight();
  }

  function reset(options = {}) {
    clearFilter({
      sendClear: options.sendClear === true,
      persist: options.persist === true,
    });
    close();
    if (options.restoreSaved) restorePreferences();
  }

  function invalidateAssignedState() {
    active = false;
    ratingCounts = null;
    invalidateSearchRequest();
    const assignBtn = getEl('tagFilterAssignBtn');
    if (assignBtn) assignBtn.disabled = true;
    const countEl = getEl('tagFilterCount');
    if (countEl) {
      countEl.textContent = '';
      countEl.classList.remove('has-result');
    }
    const toggleBtn = getEl('tagFilterToggle');
    if (toggleBtn) toggleBtn.classList.remove('assigned');
  }

  function removeExcludeTag(index) {
    excludeTags.splice(index, 1);
    renderExcludeChips();
    invalidateAssignedState();
    if (!includeTags.length && !excludeTags.length) clearFilter();
    else send({type: 'tag_filter_clear'});
    save();
  }

  function removeIncludeTag(index) {
    includeTags.splice(index, 1);
    renderIncludeChips();
    invalidateAssignedState();
    if (!includeTags.length && !excludeTags.length) clearFilter();
    else send({type: 'tag_filter_clear'});
    save();
  }

  function apply() {
    if (!includeTags.length && !excludeTags.length) return;
    if (!isSocketOpen()) return;
    save();
    send({type: 'tag_filter_search', tags: payload(), request_id: nextSearchRequestId()});
  }

  function assign() {
    send({type: 'tag_filter_assign', request_id: latestSearchRequestId});
  }

  function onResult(message) {
    if (message.request_id && message.request_id !== latestSearchRequestId) {
      return;
    }
    const assignBtn = getEl('tagFilterAssignBtn');
    ratingCounts = message.rating_counts || null;
    const countEl = getEl('tagFilterCount');
    if (!countEl || !assignBtn) return;
    if (message.count > 0) {
      countEl.textContent = `${message.count.toLocaleString()} matched`;
      countEl.classList.add('has-result');
      assignBtn.disabled = false;
      if (pendingAssignOnRestore) {
        pendingAssignOnRestore = false;
        assign();
      }
    } else {
      pendingAssignOnRestore = false;
      countEl.textContent = message.count === 0 && message.tags && message.tags.length ? 'No matches' : '';
      countEl.classList.remove('has-result');
      assignBtn.disabled = true;
    }
  }

  function onAssigned(message) {
    active = true;
    if (message.rating_counts) ratingCounts = message.rating_counts;
    const toggleBtn = getEl('tagFilterToggle');
    if (toggleBtn) {
      toggleBtn.classList.remove('active');
      toggleBtn.classList.add('assigned');
    }
    const countEl = getEl('tagFilterCount');
    if (countEl) {
      countEl.textContent = `${(message.count || 0).toLocaleString()} assigned`;
      countEl.classList.add('has-result');
    }
    const assignBtn = getEl('tagFilterAssignBtn');
    if (assignBtn) assignBtn.disabled = true;
    save();
    if (ratingCounts) {
      let filtered = 0;
      const ratingState = deps.getRatingState();
      RATING_KEYS.forEach(key => {
        if (ratingState[key]) filtered += (ratingCounts[key] || 0);
      });
      deps.updateSearchCount(filtered);
    }
    deps.showToast(`Tag filter assigned: ${(message.count || 0).toLocaleString()} rows`, 'success');
  }

  function onUpdate(message) {
    if (message.rating_counts) ratingCounts = message.rating_counts;
    const countEl = getEl('tagFilterCount');
    if (countEl) {
      countEl.textContent = `${(message.count || 0).toLocaleString()} assigned`;
      countEl.classList.add('has-result');
    }
    const toggleBtn = getEl('tagFilterToggle');
    if (toggleBtn && active) toggleBtn.classList.add('assigned');
    if (ratingCounts) {
      let filtered = 0;
      const ratingState = deps.getRatingState();
      RATING_KEYS.forEach(key => {
        if (ratingState[key]) filtered += (ratingCounts[key] || 0);
      });
      deps.updateSearchCount(filtered);
    }
  }

  function onAutocompleteResult(message) {
    const popup = getEl('tagFilterPopup');
    if (!popup || !popup.classList.contains('open')) return;
    const inputId = acTarget === 'exclude' ? 'tagFilterExcludeInput' : 'tagFilterInput';
    const input = getEl(inputId);
    if (!input || input.value.trim().length < 2) return;
    acResults = message.results || [];
    acSelection = -1;
    renderAutocomplete();
  }

  function applyPreferences(saved, options = {}) {
    const pref = normalizePreferences(saved);
    if (!pref) {
      updateHighlight();
      return false;
    }

    setActiveRatings(pref.ratings);
    includeTags = [...pref.tag_filter];
    excludeTags = [...pref.tag_filter_exclude];
    active = pref.tag_filter_active;
    ratingCounts = null;
    renderIncludeChips();
    renderExcludeChips();
    deps.syncRatingButtons();

    if (options.updateCount !== false) {
      const localCount = deps.computeLocalFilteredCount();
      if (localCount !== null && localCount !== undefined) deps.updateSearchCount(localCount);
    }

    const countEl = getEl('tagFilterCount');
    if (countEl) {
      countEl.textContent = '';
      countEl.classList.remove('has-result');
    }
    const assignBtn = getEl('tagFilterAssignBtn');
    if (assignBtn) assignBtn.disabled = true;
    const toggleBtn = getEl('tagFilterToggle');
    if (toggleBtn) {
      toggleBtn.classList.remove('active');
      toggleBtn.classList.toggle('assigned', active);
    }
    updateHighlight();

    if (options.send !== false && isSocketOpen()) {
      send({type: 'set_active_ratings', ratings: pref.ratings});
      const tags = payload();
      if (tags.length) {
        pendingAssignOnRestore = active;
        send({type: 'tag_filter_search', tags, request_id: nextSearchRequestId()});
      }
    }
    return true;
  }

  function restorePreferences(options = {}) {
    const saved = load();
    if (!saved) {
      updateHighlight();
      return false;
    }
    return applyPreferences(saved, options);
  }

  return {
    bindInputs,
    toggle,
    open,
    close,
    clear: clearFilter,
    removeExcludeTag,
    removeIncludeTag,
    apply,
    assign,
    onResult,
    onAssigned,
    onUpdate,
    onAutocompleteResult,
    applyPreferences,
    restorePreferences,
    updateHighlight,
    savePreferences: save,
    loadPreferences: load,
    reset,
    normalizeTags,
    payload,
    isActive: () => active,
    getRatingCounts: () => ratingCounts,
  };
}
