import {createEventPresetFixtureState} from './eventPresetFixtures.mjs?v=20260507-event-preset-generate1';

async function readJsonResponse(response) {
  let data = null;
  try {
    data = await response.json();
  } catch (_) {
    data = null;
  }
  if (!response.ok) {
    const message = data?.error || data?.message || `HTTP ${response.status}`;
    throw new Error(message);
  }
  return data || {};
}

function createServerEventPresetProvider() {
  function bootstrap(params = {}) {
    const query = new URLSearchParams();
    for (const [key, value] of Object.entries({
      ratingId: params.ratingId,
      personId: params.personId,
      search: params.search,
      categoryId: params.categoryId,
      subcategoryId: params.subcategoryId,
      eventId: params.eventId,
      limit: params.limit,
    })) {
      if (value != null && value !== '') query.set(key, String(value));
    }
    return fetch(`/api/event-preset/bootstrap?${query.toString()}`, {cache: 'no-store'})
      .then(readJsonResponse);
  }

  function postJson(url, payload) {
    return fetch(url, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload || {}),
      cache: 'no-store',
    }).then(readJsonResponse);
  }

  return {
    mode: 'server',
    status: () => fetch('/api/event-preset/status', {cache: 'no-store'}).then(readJsonResponse),
    bootstrap,
    select: payload => postJson('/api/event-preset/select', payload),
    promptPreview: payload => postJson('/api/event-preset/prompt-preview', payload),
    generate: payload => postJson('/api/event-preset/generate', payload),
    downloadState: () => fetch('/api/event-preset/download', {cache: 'no-store'}).then(readJsonResponse),
    startDownload: () => postJson('/api/event-preset/download', {}),
    cancelDownload: () => postJson('/api/event-preset/download/cancel', {}),
  };
}

function findContextInData(data, eventId) {
  for (const category of data?.categories || []) {
    for (const subcategory of category?.subcategories || []) {
      for (const event of subcategory?.events || []) {
        if (event.id === eventId) return {category, subcategory, event};
      }
    }
  }
  return null;
}

function createFixtureEventPresetProvider(fixture) {
  return {
    mode: 'fixture',
    status: () => Promise.resolve({
      ok: true,
      dataMode: fixture.dataMode,
      dataAvailability: fixture.dataAvailability,
    }),
    bootstrap: () => Promise.resolve(fixture),
    select: payload => {
      const context = findContextInData(fixture, payload?.eventId);
      const event = context?.event || null;
      return Promise.resolve({
        ok: true,
        dataMode: fixture.dataMode,
        dataAvailability: fixture.dataAvailability,
        selected: payload || fixture.selected,
        event,
        promptPreview: '',
      });
    },
    promptPreview: () => Promise.resolve({ok: true, prompt: '', atoms: []}),
    generate: payload => Promise.resolve({ok: true, selected: payload || fixture.selected}),
  };
}

export function createEventPresetPanel({
  document,
  promptEdit,
  applyPromptText,
  onPromptEdit,
  getGenerating,
  showToast,
  escHtml,
  onGenerateStateChange,
} = {}) {
  const root = document?.getElementById('eventPresetPanel');
  const overlay = document?.getElementById('eventPresetOverlay');
  const viewer = document?.getElementById('resultViewer') || document?.querySelector('.viewer');
  const rightResultPane = document?.getElementById('rightTabResult');
  if (!root || !overlay) return null;

  let viewData = createEventPresetFixtureState();
  const query = new URLSearchParams(document?.defaultView?.location?.search || '');
  const useFixtureProvider = query.has('codex_event_preset_fixture') || query.has('codex_event_preset_skel');
  const provider = useFixtureProvider
    ? createFixtureEventPresetProvider(viewData)
    : createServerEventPresetProvider();
  const initialSelected = useFixtureProvider
    ? viewData.selected
    : {
      ratingId: 's',
      personId: '1girl_solo',
      search: '',
      categoryId: '',
      subcategoryId: '',
      eventId: '',
      comboId: '',
      recommendedTagIds: [],
    };
  const state = {
    activeTab: false,
    search: initialSelected.search || '',
    ratingId: initialSelected.ratingId,
    personId: initialSelected.personId,
    categoryId: initialSelected.categoryId,
    subcategoryId: initialSelected.subcategoryId || '',
    eventId: initialSelected.eventId,
    comboId: initialSelected.comboId,
    assistTab: 'combos',
    recommendedTagIds: new Set((initialSelected.recommendedTagIds || []).map(String)),
    dataStatus: useFixtureProvider ? 'ready' : 'idle',
    dataMessage: '',
    loaded: useFixtureProvider,
    selectionLoading: false,
    generatePending: false,
    generating: false,
    download: viewData.download || {},
  };
  let bootstrapRequestSeq = 0;
  let selectRequestSeq = 0;
  let searchTimer = null;
  let downloadPollTimer = null;

  const escapeHtml = typeof escHtml === 'function'
    ? escHtml
    : value => String(value ?? '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');

  function formatCount(value) {
    const number = Number(value || 0);
    if (number >= 1000) return `${(number / 1000).toFixed(number >= 10000 ? 0 : 1)}k`;
    return String(number);
  }

  function displayCount(item) {
    return item?.displayCount || formatCount(item?.count || 0);
  }

  function dataAvailability() {
    return viewData?.dataAvailability || {};
  }

  function dataReady() {
    const main = dataAvailability().main;
    return state.dataStatus === 'ready' && (main === 'ready' || main === 'fixture');
  }

  function downloadActive() {
    return !!state.download?.active;
  }

  function downloadAvailable() {
    return provider.mode === 'server';
  }

  function setRecommendedTagIds(ids) {
    state.recommendedTagIds = new Set((ids || []).map(item => String(item)));
  }

  function selectedPayload() {
    return {
      requestId: `event-preset-${Date.now()}-${Math.random().toString(16).slice(2)}`,
      ratingId: state.ratingId,
      personId: state.personId,
      categoryId: state.categoryId,
      subcategoryId: state.subcategoryId,
      eventId: state.eventId,
      comboId: state.comboId,
      search: state.search,
      recommendedTagIds: Array.from(state.recommendedTagIds),
    };
  }

  const PERSON_TAGS = {
    '1girl_solo': ['1girl', 'solo'],
    '1boy_solo': ['1boy', 'solo'],
    '1girl_1boy': ['1girl', '1boy'],
    '2girls': ['2girls'],
    '2boys': ['2boys'],
    '1girl_multiple_boys': ['1girl', 'multiple boys'],
    '1boy_multiple_girls': ['1boy', 'multiple girls'],
    'multiple_girls': ['multiple girls'],
    'multiple_boys': ['multiple boys'],
    'multiple_girls_multiple_boys': ['multiple girls', 'multiple boys'],
    '1girl': ['1girl'],
    '1boy': ['1boy'],
    other: [],
  };

  const RATING_TAGS = {
    g: 'rating:general',
    s: 'rating:sensitive',
    q: 'rating:questionable',
    e: 'rating:explicit',
  };

  const SCROLL_SELECTORS = [
    '[data-ep-category-rail]',
    '.event-preset-events-body',
    '.event-preset-assist-list',
    '.event-preset-recommend-body',
  ];

  function captureScrollState() {
    return SCROLL_SELECTORS.map(selector => {
      const element = root.querySelector(selector) || overlay.querySelector(selector);
      return element ? [selector, element.scrollTop, element.scrollLeft] : null;
    }).filter(Boolean);
  }

  function restoreScrollState(snapshot) {
    for (const [selector, top, left] of snapshot || []) {
      const element = root.querySelector(selector) || overlay.querySelector(selector);
      if (!element) continue;
      element.scrollTop = top;
      element.scrollLeft = left;
    }
  }

  function resetAssistListScroll() {
    const element = overlay.querySelector('.event-preset-assist-list');
    if (!element) return;
    element.scrollTop = 0;
    element.scrollLeft = 0;
  }

  function applySelectedPayload(selected = {}) {
    if (selected.ratingId) state.ratingId = selected.ratingId;
    if (selected.personId) state.personId = selected.personId;
    state.categoryId = selected.categoryId || state.categoryId || '';
    state.subcategoryId = selected.subcategoryId || state.subcategoryId || '';
    state.eventId = selected.eventId || state.eventId || '';
    state.comboId = selected.comboId || state.comboId || '';
    if (Array.isArray(selected.recommendedTagIds)) setRecommendedTagIds(selected.recommendedTagIds);
    if (selected.search != null) state.search = selected.search;
  }

  function mergeEventDetail(eventDetail) {
    if (!eventDetail?.id) return;
    const context = findContextInData(viewData, eventDetail.id);
    if (context?.event) Object.assign(context.event, eventDetail);
  }

  function splitPromptTags(text) {
    return String(text || '')
      .split(',')
      .map(cleanPromptAtom)
      .filter(Boolean);
  }

  function cleanPromptAtom(value) {
    let text = String(value || '').trim();
    while (text.length >= 2 && text.startsWith('[') && text.endsWith(']')) {
      text = text.slice(1, -1).trim();
    }
    return text;
  }

  async function loadBootstrap({showLoading = true} = {}) {
    const requestSeq = ++bootstrapRequestSeq;
    if (showLoading) {
      state.dataStatus = 'loading';
      state.dataMessage = 'Event Preset 데이터를 불러오는 중입니다.';
      renderAll();
    }
    try {
      const payload = await provider.bootstrap(selectedPayload());
      if (requestSeq !== bootstrapRequestSeq) return;
      viewData = {
        ...viewData,
        ...payload,
        categories: payload.categories || [],
        ratings: payload.ratings || viewData.ratings || [],
        persons: payload.persons || viewData.persons || [],
        dataAvailability: payload.dataAvailability || viewData.dataAvailability || {},
        download: payload.download || viewData.download || {},
      };
      state.download = viewData.download || {};
      applySelectedPayload(payload.selected || {});
      const mainState = dataAvailability().main;
      state.dataStatus = (mainState === 'ready' || mainState === 'fixture')
        ? 'ready'
        : (mainState || 'missing');
      state.dataMessage = dataAvailability().message || '';
      state.loaded = true;
      renderAll();
      syncDownloadPolling();
      if (dataReady() && state.eventId) loadSelection({showLoading: false});
    } catch (error) {
      if (requestSeq !== bootstrapRequestSeq) return;
      state.dataStatus = 'error';
      state.dataMessage = error?.message || 'Event Preset 데이터를 불러오지 못했습니다.';
      state.loaded = true;
      renderAll();
      showToast?.(state.dataMessage, 'error');
      syncDownloadPolling();
    }
  }

  async function loadSelection({showLoading = true, resetAssistScroll = false} = {}) {
    if (!dataReady() || !state.eventId) return;
    const requestSeq = ++selectRequestSeq;
    if (showLoading) {
      state.selectionLoading = true;
      renderAll();
    }
    try {
      const payload = await provider.select(selectedPayload());
      if (requestSeq !== selectRequestSeq) return;
      applySelectedPayload(payload.selected || {});
      mergeEventDetail(payload.event);
      state.selectionLoading = false;
      renderAll();
      if (resetAssistScroll) resetAssistListScroll();
    } catch (error) {
      if (requestSeq !== selectRequestSeq) return;
      state.selectionLoading = false;
      renderAll();
      showToast?.(error?.message || 'Event Preset 선택 데이터를 불러오지 못했습니다.', 'error');
    }
  }

  function scheduleBootstrap() {
    if (provider.mode === 'fixture') {
      renderAll();
      return;
    }
    if (searchTimer) clearTimeout(searchTimer);
    searchTimer = setTimeout(() => loadBootstrap({showLoading: false}), 260);
  }

  async function refreshDownloadState({bootstrapOnDone = false} = {}) {
    if (!downloadAvailable() || typeof provider.downloadState !== 'function') return;
    try {
      const payload = await provider.downloadState();
      state.download = payload || {};
      if (payload?.availability) {
        viewData = {
          ...viewData,
          dataAvailability: payload.availability,
          download: payload,
        };
        const mainState = dataAvailability().main;
        state.dataStatus = (mainState === 'ready' || mainState === 'fixture')
          ? 'ready'
          : (mainState || state.dataStatus || 'missing');
        state.dataMessage = dataAvailability().message || state.dataMessage || '';
      }
      renderAll({preserveScroll: true});
      syncDownloadPolling();
      if (bootstrapOnDone && payload?.done && !payload?.error) {
        loadBootstrap({showLoading: true});
      }
    } catch (error) {
      showToast?.(error?.message || 'Event Preset 다운로드 상태를 확인하지 못했습니다.', 'error');
    }
  }

  function syncDownloadPolling() {
    if (!downloadAvailable()) return;
    if (downloadActive()) {
      if (!downloadPollTimer) {
        downloadPollTimer = setInterval(() => {
          void refreshDownloadState({bootstrapOnDone: true});
        }, 800);
      }
      return;
    }
    if (downloadPollTimer) {
      clearInterval(downloadPollTimer);
      downloadPollTimer = null;
    }
  }

  async function startDownload() {
    if (!downloadAvailable() || typeof provider.startDownload !== 'function') return;
    try {
      state.download = {
        ...(state.download || {}),
        active: true,
        phase: 'main',
        percent: 0,
        message: '다운로드 준비 중...',
        error: '',
      };
      renderAll({preserveScroll: true});
      const payload = await provider.startDownload();
      state.download = payload || state.download;
      renderAll({preserveScroll: true});
      syncDownloadPolling();
    } catch (error) {
      state.download = {
        ...(state.download || {}),
        active: false,
        error: error?.message || 'Event Preset 다운로드를 시작하지 못했습니다.',
        message: error?.message || 'Event Preset 다운로드를 시작하지 못했습니다.',
      };
      renderAll({preserveScroll: true});
      showToast?.(state.download.error, 'error');
    }
  }

  async function cancelDownload() {
    if (!downloadAvailable() || typeof provider.cancelDownload !== 'function') return;
    try {
      state.download = await provider.cancelDownload();
      renderAll({preserveScroll: true});
      syncDownloadPolling();
    } catch (error) {
      showToast?.(error?.message || 'Event Preset 다운로드 취소에 실패했습니다.', 'error');
    }
  }

  function categories() {
    return viewData.categories || [];
  }

  function findCategory(id = state.categoryId) {
    return categories().find(category => category.id === id) || categories()[0] || null;
  }

  function eventContextsForCategory(category) {
    const contexts = [];
    for (const subcategory of category?.subcategories || []) {
      for (const event of subcategory.events || []) {
        contexts.push({category, subcategory, event});
      }
    }
    return contexts;
  }

  function findEvent(id = state.eventId) {
    if (!id) return {category: findCategory(), subcategory: null, event: null};
    for (const category of categories()) {
      for (const context of eventContextsForCategory(category)) {
        if (context.event.id === id) return context;
      }
    }
    return {category: findCategory(), subcategory: null, event: null};
  }

  function eventPassesPartition(event) {
    if (viewData.dataMode === 'real') return true;
    const ratingOk = !event?.ratings?.length || event.ratings.includes(state.ratingId);
    const personOk = state.personId === 'all' || !event?.persons?.length || event.persons.includes(state.personId);
    return ratingOk && personOk;
  }

  function eventMatchesSearch(context) {
    if (viewData.dataMode === 'real') return true;
    const query = state.search.trim().toLowerCase();
    if (!query) return true;
    const {category, subcategory, event} = context;
    const haystack = [
      category?.label,
      subcategory?.label,
      event?.label,
      event?.tag,
      ...(event?.promptAtoms || []),
    ].join(' ').toLowerCase();
    return haystack.includes(query);
  }

  function visibleEventContexts(category = findCategory()) {
    const partitioned = eventContextsForCategory(category).filter(context => eventPassesPartition(context.event));
    const searched = partitioned.filter(eventMatchesSearch);
    return searched.length ? searched : partitioned;
  }

  function selectedContext() {
    const context = findEvent(state.eventId);
    if (context.event) return context;
    const category = findCategory();
    return {category, subcategory: null, event: null};
  }

  function selectContext(context) {
    if (!context?.event) {
      state.eventId = '';
      state.comboId = '';
      state.recommendedTagIds = new Set();
      return;
    }
    state.categoryId = context.category.id;
    state.subcategoryId = context.subcategory?.id || '';
    state.eventId = context.event.id;
    state.comboId = context.event.observedCombos?.[0]?.id || '';
    setRecommendedTagIds(context.event.recommendedTags?.slice(0, 2).map(tag => tag.id) || []);
  }

  function ensureVisibleSelection() {
    const category = findCategory();
    const visible = visibleEventContexts(category);
    if (!visible.length) {
      selectContext(null);
      return;
    }
    if (!visible.some(context => context.event.id === state.eventId)) {
      selectContext(visible[0]);
    }
  }

  function currentCombo(event = selectedContext().event) {
    return event?.observedCombos?.find(combo => combo.id === state.comboId)
      || event?.observedCombos?.[0]
      || null;
  }

  function comboPromptText(combo) {
    return combo?.prompt || (combo?.tags || []).join(', ') || combo?.label || '';
  }

  function allCandidateRecommendedTags(event = selectedContext().event) {
    const items = [];
    const seen = new Set();
    const push = item => {
      const key = String(item?.id || item?.tag || '').toLowerCase();
      if (!key || seen.has(key)) return;
      seen.add(key);
      items.push(item);
    };
    (event?.recommendedTags || []).forEach(push);
    for (const slotItems of Object.values(event?.slots || {})) {
      (slotItems || []).forEach(push);
    }
    return items;
  }

  function selectedRecommendedTags(event = selectedContext().event) {
    return allCandidateRecommendedTags(event).filter(tag => state.recommendedTagIds.has(String(tag.id)));
  }

  function directRecommendedTags(event = selectedContext().event) {
    if (Array.isArray(event?.directRecommendedTags) && event.directRecommendedTags.length) {
      return event.directRecommendedTags;
    }
    const ordered = [
      ...(event?.slots?.expression || []),
      ...(event?.slots?.clothing || []),
      ...(event?.slots?.characteristic || []),
    ];
    const seen = new Set();
    return ordered.filter(item => {
      const key = String(item?.id || item?.tag || '').trim().toLowerCase();
      if (!key || seen.has(key)) return false;
      seen.add(key);
      return true;
    });
  }

  function recommendationGroup(event, item) {
    if (item?.group) return item.group;
    const slots = event?.slots || {};
    if ((slots.expression || []).some(tag => tag.id === item.id || tag.tag === item.tag)) return 'Expression';
    if ((slots.clothing || []).some(tag => tag.id === item.id || tag.tag === item.tag)) return 'Clothing';
    if ((slots.characteristic || []).some(tag => tag.id === item.id || tag.tag === item.tag)) return 'Characteristic';
    return 'Auto';
  }

  function recommendationGroupForTab(tabId = state.assistTab) {
    if (tabId === 'expression') return 'Expression';
    if (tabId === 'clothing') return 'Clothing';
    if (tabId === 'characteristic') return 'Characteristic';
    return 'Auto';
  }

  function activeRecommendedTags(event = selectedContext().event) {
    if (state.assistTab === 'combos') return directRecommendedTags(event);
    const group = recommendationGroupForTab();
    return allCandidateRecommendedTags(event).filter(item => recommendationGroup(event, item) === group);
  }

  function uniqueTags(tags) {
    const seen = new Set();
    const result = [];
    for (const tag of tags) {
      const clean = cleanPromptAtom(tag);
      const key = clean.toLowerCase();
      if (!key || seen.has(key)) continue;
      seen.add(key);
      result.push(clean);
    }
    return result;
  }

  function promptPreview() {
    const {event} = selectedContext();
    if (!event) return '';
    const combo = currentCombo(event);
    return uniqueTags([
      ...(PERSON_TAGS[state.personId] || []),
      ...(combo?.prompt ? splitPromptTags(combo.prompt) : (combo?.tags || [])),
      ...selectedRecommendedTags(event).map(tag => tag.tag),
      RATING_TAGS[state.ratingId] || '',
    ]).join(', ');
  }

  function recommendationGroupClass(group) {
    const normalized = String(group || 'Auto').toLowerCase();
    if (normalized === 'expression') return 'event-preset-recommend-chip--expression';
    if (normalized === 'clothing') return 'event-preset-recommend-chip--clothing';
    if (normalized === 'characteristic' || normalized === 'characters') {
      return 'event-preset-recommend-chip--characteristic';
    }
    return 'event-preset-recommend-chip--auto';
  }

  function chipButton({label, active, action, id}) {
    return `
      <button type="button"
              class="event-preset-chip ${active ? 'active' : ''}"
              data-ep-action="${escapeHtml(action)}"
              data-ep-id="${escapeHtml(id)}"
              aria-pressed="${active ? 'true' : 'false'}">${escapeHtml(label)}</button>`;
  }

  function renderToolbar() {
    const ratings = root.querySelector('[data-ep-ratings]');
    const person = root.querySelector('[data-ep-person]');
    if (ratings) {
      ratings.innerHTML = (viewData.ratings || []).map(rating => chipButton({
        label: rating.label,
        active: rating.id === state.ratingId,
        action: 'rating',
        id: rating.id,
      })).join('');
    }
    if (person) {
      person.innerHTML = (viewData.persons || []).map(option => `
        <option value="${escapeHtml(option.id)}" ${option.id === state.personId ? 'selected' : ''}>${escapeHtml(option.label)}</option>
      `).join('');
      person.disabled = !dataReady() && provider.mode !== 'fixture';
    }
  }

  function renderCategories() {
    const rail = root.querySelector('[data-ep-category-rail]');
    if (!rail) return;
    if (state.dataStatus === 'loading') {
      rail.innerHTML = '<div class="event-preset-empty">데이터를 불러오는 중입니다.</div>';
      return;
    }
    if (!dataReady()) {
      rail.innerHTML = `<div class="event-preset-empty">${escapeHtml(state.dataMessage || 'Event Preset data is not ready.')}</div>`;
      return;
    }
    if (!categories().length) {
      rail.innerHTML = '<div class="event-preset-empty">표시할 이벤트가 없습니다.</div>';
      return;
    }
    let lastGroup = '';
    rail.innerHTML = categories().map(category => {
      const group = category.group || 'GENERAL';
      const heading = group !== lastGroup
        ? `<div class="event-preset-category-group">${escapeHtml(group)}</div>`
        : '';
      lastGroup = group;
      return `
        ${heading}
        <button type="button"
                class="event-preset-category ${category.id === state.categoryId ? 'active' : ''}"
                data-ep-action="category"
                data-ep-id="${escapeHtml(category.id)}">
          <span class="event-preset-category-name">${escapeHtml(category.label)}</span>
          <span class="event-preset-category-count">(${escapeHtml(displayCount(category))})</span>
        </button>`;
    }).join('');
  }

  function renderEvents() {
    const target = root.querySelector('[data-ep-event-table]');
    if (!target) return;
    const category = findCategory();
    const rows = visibleEventContexts(category);
    const emptyText = !dataReady()
      ? (state.dataMessage || 'Event Preset data is not ready.')
      : '이 카테고리에 표시할 이벤트가 없습니다.';
    const body = rows.length
      ? rows.map((context, index) => `
        <button type="button"
                class="event-preset-event-row ${context.event.id === state.eventId ? 'active' : ''}"
                data-ep-action="event"
                data-ep-id="${escapeHtml(context.event.id)}">
          <span class="event-preset-event-index">${index + 1}</span>
          <span class="event-preset-event-name">${escapeHtml(context.event.label || context.event.tag)}</span>
          <span class="event-preset-event-count">${escapeHtml(formatCount(context.event.count))}</span>
        </button>`).join('')
      : `<div class="event-preset-empty">${escapeHtml(emptyText)}</div>`;
    target.innerHTML = `
      <div class="event-preset-events-head">
        <span>Events (${escapeHtml(category?.label || '-')})</span>
        <span>Count</span>
      </div>
      <div class="event-preset-events-body">${body}</div>`;
  }

  function renderSelection() {
    const selected = root.querySelector('[data-ep-selected-chips]');
    const preview = root.querySelector('[data-ep-prompt-preview]');
    const {category, event} = selectedContext();
    const combo = currentCombo(event);
    if (selected) {
      const parts = [
        (viewData.ratings || []).find(rating => rating.id === state.ratingId)?.label,
        (viewData.persons || []).find(person => person.id === state.personId)?.label,
        category?.label,
        event?.tag,
        combo?.label,
      ].filter(Boolean);
      selected.innerHTML = parts.map(part => `<span class="event-preset-selected-chip">${escapeHtml(part)}</span>`).join('');
    }
    if (preview) {
      const fallback = state.selectionLoading
        ? '선택 데이터를 불러오는 중입니다.'
        : (!dataReady() ? (state.dataMessage || 'Event Preset data is not ready.') : 'Select an event preset.');
      preview.textContent = promptPreview() || fallback;
    }
    if (typeof onGenerateStateChange === 'function') onGenerateStateChange(canGenerateCurrentPreset());
  }

  function renderDownloadOverlay() {
    const panel = root.querySelector('[data-ep-download-overlay]');
    if (!panel) return;
    const availability = dataAvailability();
    const mainState = availability.main || state.dataStatus;
    const thumbState = availability.thumbnails || '';
    const datasetsReady = mainState === 'ready' && thumbState === 'ready';
    const hasBlockingDownloadError = !!state.download?.error && !datasetsReady;
    const shouldShow = provider.mode === 'server' && (
      downloadActive()
      || mainState === 'missing'
      || mainState === 'error'
      || (mainState === 'ready' && thumbState === 'missing')
      || hasBlockingDownloadError
    );
    panel.hidden = !shouldShow;
    panel.setAttribute('aria-hidden', shouldShow ? 'false' : 'true');
    if (!shouldShow) {
      panel.innerHTML = '';
      return;
    }

    const download = state.download || {};
    const phase = String(download.phase || (mainState === 'ready' ? 'thumbnail' : 'main'));
    const percent = Math.max(0, Math.min(100, Number(download.percent || 0)));
    const message = download.message || availability.message || 'Event Preset data is not installed.';
    const error = download.error || '';
    const active = !!download.active;
    const phaseLabel = phase === 'thumbnail' ? 'THUMBNAILS' : (phase === 'complete' ? 'COMPLETE' : 'DATASET');
    const title = error ? 'DOWNLOAD FAILED' : (active ? 'DOWNLOADING' : 'MISSING DATA');
    const mainBadge = mainState === 'ready' ? 'READY' : 'MISSING';
    const thumbBadge = thumbState === 'ready' ? 'READY' : 'MISSING';
    const progressText = active
      ? `${phaseLabel} ${percent}%`
      : (error ? 'ERROR' : `${mainBadge} / ${thumbBadge}`);
    panel.innerHTML = `
      <div class="event-preset-download-card" role="dialog" aria-modal="true" aria-label="Event Preset data download">
        <div class="event-preset-download-head">
          <span>Event Preset</span>
          <strong>${escapeHtml(title)}</strong>
        </div>
        <div class="event-preset-download-body">
          <div class="event-preset-download-status">
            <span>Main <b class="${mainState === 'ready' ? 'ready' : 'missing'}">${escapeHtml(mainBadge)}</b></span>
            <span>Thumb <b class="${thumbState === 'ready' ? 'ready' : 'missing'}">${escapeHtml(thumbBadge)}</b></span>
          </div>
          <p>${escapeHtml(error || message)}</p>
          <div class="event-preset-download-progress" aria-label="${escapeHtml(progressText)}">
            <span style="width:${percent}%"></span>
          </div>
          <div class="event-preset-download-meta">
            <span>${escapeHtml(progressText)}</span>
            <span>${download.downloaded_mb ? `${escapeHtml(String(download.downloaded_mb))} MB` : ''}</span>
          </div>
        </div>
        <div class="event-preset-download-actions">
          ${active
            ? '<button type="button" data-ep-action="cancel-download">Cancel</button>'
            : '<button type="button" class="primary" data-ep-action="start-download">Download</button>'}
        </div>
      </div>
    `;
  }

  const ASSIST_TABS = [
    {id: 'combos', label: 'Observed', title: 'Observed Event Combos'},
    {id: 'expression', label: 'Expression', title: 'Expression'},
    {id: 'clothing', label: 'Clothing', title: 'Clothing'},
    {id: 'characteristic', label: 'Char', title: 'Characteristic'},
  ];

  function activeAssistMeta() {
    return ASSIST_TABS.find(tab => tab.id === state.assistTab) || ASSIST_TABS[0];
  }

  function activeAssistItems(event = selectedContext().event) {
    const slots = event?.slots || {};
    if (state.assistTab === 'expression') return slots.expression || [];
    if (state.assistTab === 'clothing') return slots.clothing || [];
    if (state.assistTab === 'characteristic') return slots.characteristic || [];
    return event?.observedCombos || [];
  }

  function activeAssistTitle() {
    return activeAssistMeta().title;
  }

  function overlayList(items, options = {}) {
    if (!items?.length) return '<div class="event-preset-assist-empty">No values</div>';
    return items.map(item => {
      const active = options.activeIds?.has(item.id) || item.id === options.activeId;
      const action = options.action
        ? ` data-ep-action="${escapeHtml(options.action)}" data-ep-id="${escapeHtml(item.id)}"`
        : '';
      const confidence = item.confidence != null ? Number(item.confidence).toFixed(3) : '-';
      const label = options.promptBundle ? comboPromptText(item) : (item.tag || item.label);
      const rowClass = [
        'event-preset-assist-row',
        options.promptBundle ? 'event-preset-assist-row--prompt' : '',
        active ? 'active' : '',
      ].filter(Boolean).join(' ');
      return `
        <button type="button"
                class="${rowClass}"
                ${action}
                ${options.action ? '' : 'disabled'}>
          <span class="event-preset-assist-row-name">${escapeHtml(label)}</span>
          <span>${escapeHtml(formatCount(item.count))}</span>
          ${options.showConfidence ? `<span>${escapeHtml(confidence)}</span>` : ''}
        </button>`;
    }).join('');
  }

  function activeRecommendedTitle() {
    if (state.assistTab === 'combos') return 'DIRECT RECOMMEND TAGS';
    return `Recommended ${activeAssistMeta().title} Tags`;
  }

  function recommendedSection(event) {
    const items = activeRecommendedTags(event);
    if (!items.length) {
      return '<div class="event-preset-recommend-body"><div class="event-preset-assist-empty">No recommendations for this tab</div></div>';
    }
    return `
      <div class="event-preset-recommend-body">
        <div class="event-preset-recommend-chips">
          ${items.map(item => {
            const active = state.recommendedTagIds.has(String(item.id));
            const group = recommendationGroup(event, item);
            return `
              <button type="button"
                      class="event-preset-recommend-chip ${recommendationGroupClass(group)} ${active ? 'active' : ''}"
                      data-ep-group="${escapeHtml(group)}"
                      data-ep-action="recommended"
                      data-ep-id="${escapeHtml(item.id)}"
                      aria-pressed="${active ? 'true' : 'false'}">
                <span>${escapeHtml(item.tag)}</span>
                <span>${escapeHtml(formatCount(item.count))}</span>
              </button>`;
          }).join('')}
        </div>
      </div>`;
  }

  function renderOverlay() {
    if (!dataReady()) {
      overlay.innerHTML = `
        <div class="event-preset-assist-card">
          <header class="event-preset-assist-head">
            <span>Preset Assist</span>
            <strong>${escapeHtml(state.dataStatus || 'idle')}</strong>
          </header>
          <div class="event-preset-assist-empty">${escapeHtml(state.dataMessage || 'Event Preset data is not ready.')}</div>
        </div>`;
      return;
    }
    const {event} = selectedContext();
    const combo = currentCombo(event);
    const thumb = event?.thumbnail || {};
    const thumbStyle = thumb.accent ? ` style="--event-preset-thumb-accent: ${escapeHtml(thumb.accent)}"` : '';
    const thumbUrl = thumb.url || (thumb.status === 'ready' && event?.id
      ? `/api/event-preset/thumbnail?eventId=${encodeURIComponent(event.id)}`
      : '');
    const activeItems = activeAssistItems(event);
    const activeAction = state.assistTab === 'combos' ? 'combo' : '';
    const activeIds = state.assistTab === 'combos' ? undefined : new Set();
    const promptBundleMode = state.assistTab === 'combos';
    const comboSummary = comboPromptText(combo) || event?.tag || '';
    overlay.innerHTML = `
        <div class="event-preset-assist-card">
        <div class="event-preset-assist-thumb"${thumbStyle}>
          ${thumbUrl ? `<img src="${escapeHtml(thumbUrl)}" alt="${escapeHtml(event?.tag || 'Event thumbnail')}" loading="lazy">` : ''}
          <div class="event-preset-thumb-info">
            <span>Preset Assist</span>
            <strong>${escapeHtml(event?.tag || 'No event')}</strong>
            <em>${escapeHtml(comboSummary)}</em>
          </div>
        </div>
        <div class="event-preset-assist-tabs" role="tablist" aria-label="Event Preset assist sections">
          ${ASSIST_TABS.map(tab => `
            <button type="button"
                    class="event-preset-assist-tab ${tab.id === state.assistTab ? 'active' : ''}"
                    data-ep-action="assist-tab"
                    data-ep-id="${escapeHtml(tab.id)}"
                    role="tab"
                    aria-selected="${tab.id === state.assistTab ? 'true' : 'false'}">${escapeHtml(tab.label)}</button>
          `).join('')}
        </div>
        <section class="event-preset-assist-list-panel ${promptBundleMode ? 'prompt-bundles' : 'with-confidence'}">
          <div class="event-preset-assist-list-head">
            <span>${escapeHtml(activeAssistTitle())}</span>
            <span>Count</span>
            ${promptBundleMode ? '' : '<span>Conf</span>'}
          </div>
          <div class="event-preset-assist-list">
            ${overlayList(activeItems, {
              action: activeAction,
              activeId: promptBundleMode ? combo?.id : '',
              activeIds,
              promptBundle: promptBundleMode,
              showConfidence: !promptBundleMode,
            })}
          </div>
        </section>
        <div class="event-preset-recommend-panel">
          <div class="event-preset-recommend-head">
            <span>${escapeHtml(activeRecommendedTitle())}</span>
            <button type="button" data-ep-action="clear-recommended">Clear</button>
          </div>
          ${recommendedSection(event)}
        </div>
      </div>`;
  }

  function renderAll({preserveScroll = true} = {}) {
    const scrollSnapshot = preserveScroll ? captureScrollState() : null;
    if (dataReady()) ensureVisibleSelection();
    renderToolbar();
    renderCategories();
    renderEvents();
    renderSelection();
    renderOverlay();
    renderDownloadOverlay();
    if (scrollSnapshot) restoreScrollState(scrollSnapshot);
  }

  function showOverlay() {
    if (!state.activeTab || !rightResultPane?.classList.contains('active')) return;
    overlay.hidden = false;
    overlay.setAttribute('aria-hidden', 'false');
    viewer?.classList.add('event-preset-overlay-active');
  }

  function hideOverlay() {
    overlay.hidden = true;
    overlay.setAttribute('aria-hidden', 'true');
    viewer?.classList.remove('event-preset-overlay-active');
  }

  function focusResultImage() {
    hideOverlay();
    viewer?.focus?.({preventScroll: true});
  }

  async function generateCurrentPreset() {
    const preview = promptPreview();
    if (!preview || state.generatePending) return false;
    if (state.generating || !!getGenerating?.()) {
      showToast?.('이미 생성 중입니다.', 'error');
      return false;
    }
    state.generatePending = true;
    renderAll({preserveScroll: true});
    try {
      const requestPayload = selectedPayload();
      const payload = await provider.generate(requestPayload);
      applySelectedPayload(payload.selected || {});
      if (provider.mode === 'fixture') {
        if (typeof applyPromptText === 'function') {
          applyPromptText(preview);
        } else if (promptEdit) {
          promptEdit.value = preview;
          if (typeof onPromptEdit === 'function') onPromptEdit();
        }
      }
      state.generatePending = false;
      renderAll({preserveScroll: true});
      showToast?.('Event Preset 생성 요청을 전달했습니다.', 'success');
      return provider.mode === 'server'
        ? {requestId: String(payload.requestId || requestPayload.requestId || '')}
        : false;
    } catch (error) {
      state.generatePending = false;
      renderAll({preserveScroll: true});
      showToast?.(error?.message || 'Event Preset 생성 요청에 실패했습니다.', 'error');
      return false;
    }
  }

  function canGenerateCurrentPreset() {
    return !!promptPreview()
      && !state.generatePending
      && !state.generating
      && !getGenerating?.()
      && dataReady()
      && !!selectedContext().event;
  }

  function handleActionClick(event) {
    const button = event.target.closest('[data-ep-action]');
    if (!button) return;
    const action = button.dataset.epAction;
    const id = button.dataset.epId;
    let shouldBootstrap = false;
    let shouldSelect = false;
    let shouldResetAssistScroll = false;
    if (state.activeTab) showOverlay();
    if (action === 'rating') {
      state.ratingId = id;
      shouldBootstrap = true;
    } else if (action === 'category') {
      state.categoryId = id;
      selectContext(visibleEventContexts(findCategory(id))[0] || null);
      shouldSelect = true;
    } else if (action === 'event') {
      const context = eventContextsForCategory(findCategory()).find(candidate => candidate.event.id === id);
      selectContext(context);
      shouldSelect = true;
      shouldResetAssistScroll = true;
    } else if (action === 'combo') {
      state.comboId = id;
      shouldSelect = provider.mode === 'server';
    } else if (action === 'assist-tab') {
      state.assistTab = id || 'combos';
    } else if (action === 'recommended') {
      if (state.recommendedTagIds.has(String(id))) state.recommendedTagIds.delete(String(id));
      else state.recommendedTagIds.add(id);
      shouldSelect = provider.mode === 'server';
    } else if (action === 'clear-recommended') {
      state.recommendedTagIds = new Set();
      shouldSelect = provider.mode === 'server';
    } else if (action === 'clear-search') {
      state.search = '';
      const input = root.querySelector('[data-ep-search]');
      if (input) input.value = '';
      shouldBootstrap = true;
    } else if (action === 'start-download') {
      void startDownload();
    } else if (action === 'cancel-download') {
      void cancelDownload();
    }
    renderAll({preserveScroll: !(shouldBootstrap || action === 'category')});
    if (shouldBootstrap) loadBootstrap({showLoading: provider.mode === 'server'});
    else if (shouldSelect) loadSelection({showLoading: false, resetAssistScroll: shouldResetAssistScroll});
  }

  function handleSearchInput(event) {
    const input = event.target.closest('[data-ep-search]');
    if (!input) return;
    state.search = input.value || '';
    renderAll();
    scheduleBootstrap();
  }

  function handleChange(event) {
    const person = event.target.closest('[data-ep-person]');
    if (!person) return;
    state.personId = person.value || '1girl_solo';
    renderAll();
    loadBootstrap({showLoading: provider.mode === 'server'});
  }

  function renderShell() {
    root.innerHTML = `
      <div class="event-preset-filter-row">
        <div class="event-preset-rating-control">
          <span class="event-preset-control-label">Rating</span>
          <div class="event-preset-chip-row" data-ep-ratings></div>
        </div>
        <label class="event-preset-person-control">
          <span class="event-preset-control-label">Person</span>
          <select class="event-preset-person-select" data-ep-person></select>
        </label>
      </div>
      <label class="event-preset-search">
        <span class="event-preset-search-icon" aria-hidden="true">&#128269;</span>
        <input type="search" data-ep-search value="${escapeHtml(state.search)}" placeholder="search events..." autocomplete="off" spellcheck="false">
        <button type="button" class="event-preset-search-clear" data-ep-action="clear-search" aria-label="Clear search">&times;</button>
      </label>
      <div class="event-preset-browser">
        <section class="event-preset-category-pane">
          <div class="event-preset-pane-title">Categories</div>
          <nav class="event-preset-category-rail" data-ep-category-rail aria-label="Event Preset categories"></nav>
        </section>
        <section class="event-preset-event-pane" data-ep-event-table></section>
      </div>
      <section class="event-preset-footer">
        <div class="event-preset-selected-chips" data-ep-selected-chips></div>
        <div class="event-preset-preview-text" data-ep-prompt-preview></div>
      </section>
      <section class="event-preset-download-overlay" data-ep-download-overlay aria-hidden="true" hidden></section>
    `;
  }

  renderShell();
  renderAll();
  hideOverlay();

  root.addEventListener('click', handleActionClick);
  root.addEventListener('click', () => { if (state.activeTab) showOverlay(); });
  root.addEventListener('focusin', () => { if (state.activeTab) showOverlay(); });
  root.addEventListener('input', handleSearchInput);
  root.addEventListener('change', handleChange);
  overlay.addEventListener('pointerdown', event => event.stopPropagation());
  overlay.addEventListener('click', event => {
    event.stopPropagation();
    handleActionClick(event);
  });
  viewer?.addEventListener('click', event => {
    if (overlay.contains(event.target)) return;
    hideOverlay();
  });
  viewer?.addEventListener('focusin', event => {
    if (overlay.contains(event.target)) return;
    hideOverlay();
  });
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape') hideOverlay();
  });
  document.addEventListener('click', event => {
    const rightTabButton = event.target.closest?.('[data-right-tab]');
    if (rightTabButton && rightTabButton.dataset.rightTab !== 'result') hideOverlay();
  });
  if (rightResultPane && document.defaultView?.MutationObserver) {
    const observer = new document.defaultView.MutationObserver(() => {
      if (!rightResultPane.classList.contains('active')) hideOverlay();
    });
    observer.observe(rightResultPane, {attributes: true, attributeFilter: ['class', 'hidden', 'aria-hidden']});
  }

  function setActiveTab(active) {
    state.activeTab = !!active;
    root.classList.toggle('active', state.activeTab);
    if (state.activeTab) {
      if (!state.loaded) loadBootstrap({showLoading: true});
      renderAll();
      showOverlay();
    } else {
      hideOverlay();
    }
  }

  setActiveTab(document.getElementById('tabPreset')?.classList.contains('active'));

  return {
    setActiveTab,
    showOverlay,
    hideOverlay,
    focusResultImage,
    generateCurrentPreset,
    canGenerate: canGenerateCurrentPreset,
    setGeneratingStatus(generating) {
      state.generating = !!generating;
      renderSelection();
    },
    getFixtureState: () => viewData,
  };
}
