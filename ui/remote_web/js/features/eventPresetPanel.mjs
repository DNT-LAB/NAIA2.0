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
    generateComposite: payload => postJson('/api/preset/generate', payload),
    clothesStatus: () => fetch('/api/clothes-preset/status', {cache: 'no-store'}).then(readJsonResponse),
    clothesBootstrap: payload => postJson('/api/clothes-preset/bootstrap', payload),
    clothesSelect: payload => postJson('/api/clothes-preset/select', payload),
    clothesLucky: payload => postJson('/api/clothes-preset/lucky', payload),
    expressionStatus: () => fetch('/api/expression-preset/status', {cache: 'no-store'}).then(readJsonResponse),
    expressionBootstrap: payload => postJson('/api/expression-preset/bootstrap', payload),
    downloadState: () => fetch('/api/event-preset/download', {cache: 'no-store'}).then(readJsonResponse),
    startDownload: () => postJson('/api/event-preset/download', {}),
    cancelDownload: () => postJson('/api/event-preset/download/cancel', {}),
    tagLookup: tag => fetch(`/api/tag/lookup?tag=${encodeURIComponent(tag)}`, {cache: 'no-store'}).then(readJsonResponse),
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
    generateComposite: payload => Promise.resolve({ok: true, requestId: payload?.requestId || '', promptPlan: payload?.promptPlan || {}}),
    clothesStatus: () => Promise.resolve({ok: true, dataAvailability: {main: 'missing', message: 'Fixture Clothes backend is not available.'}}),
    clothesBootstrap: () => Promise.resolve({ok: true, dataAvailability: {main: 'missing'}, selected: {}, comboRows: {rows: []}, browser: {categories: [], subcategories: [], items: []}, staged: {items: [], groups: [], tags: []}, promptFragment: {tags: []}}),
    clothesSelect: payload => Promise.resolve({ok: true, selected: payload || {}, comboRows: {rows: []}, browser: {categories: [], subcategories: [], items: []}, staged: {items: [], groups: [], tags: []}, promptFragment: {tags: []}}),
    clothesLucky: () => Promise.resolve({ok: true, lucky: {comboId: 'fixture-lucky', comboText: 'shirt, skirt, long sleeves, hair ornament', tags: ['shirt', 'skirt', 'long sleeves', 'hair ornament']}}),
    expressionStatus: () => Promise.resolve({ok: true, dataAvailability: {main: 'fixture'}, counts: {expressionCombos: 0, expressionTags: 0, staticTags: 0}}),
    expressionBootstrap: () => Promise.resolve({ok: true, dataAvailability: {main: 'fixture'}, categories: []}),
    tagLookup: tag => Promise.resolve({tag}),
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
  const MIN_SEARCH_LENGTH = 2;
  const CLOTHES_PAIR_MODE = 'Balanced';

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
    activeAxis: 'events',
    search: initialSelected.search || '',
    expressionSearch: '',
    clothesSearch: '',
    ratingId: initialSelected.ratingId,
    personId: initialSelected.personId,
    categoryId: initialSelected.categoryId,
    subcategoryId: initialSelected.subcategoryId || '',
    eventId: initialSelected.eventId,
    comboId: initialSelected.comboId,
    expressionCategoryId: '',
    expressionSubcategoryId: '',
    selectedExpressionIds: new Set(),
    expandedExpressionSubcategoryIds: new Set(),
    expressionStatus: 'idle',
    expressionMessage: '',
    expressionLoading: false,
    expressionData: {
      dataAvailability: {},
      counts: {},
      categories: [],
    },
    clothesStatus: 'idle',
    clothesMessage: '',
    clothesLoading: false,
    clothesPairMode: CLOTHES_PAIR_MODE,
    clothesCategoryId: '',
    clothesSubcategoryId: '',
    clothesComboId: '',
    clothesComboText: '',
    clothesComboFocusTags: [],
    clothesStagedItems: [],
    clothesData: {
      dataAvailability: {},
      capabilities: {},
      pairModes: [],
      comboRows: {rows: [], summary: ''},
      browser: {categories: [], subcategories: [], items: []},
      staged: {items: [], groups: [], tags: []},
      promptFragment: {tags: []},
      rules: {},
    },
    searchShowAll: false,
    assistTab: 'combos',
    recommendedTagIds: new Set((initialSelected.recommendedTagIds || []).map(String)),
    dataStatus: useFixtureProvider ? 'ready' : 'idle',
    dataMessage: '',
    loaded: useFixtureProvider,
    selectionLoading: false,
    generatePending: false,
    generating: false,
    download: viewData.download || {},
    promptText: '',
    promptDirty: false,
  };
  let bootstrapRequestSeq = 0;
  let selectRequestSeq = 0;
  let searchTimer = null;
  let downloadPollTimer = null;
  let tagInfoTooltip = null;
  let tagInfoHoverTimer = null;
  let tagInfoRequestSeq = 0;
  let tagInfoAnchor = null;
  const tagInfoCache = new Map();

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

  function selectedPayload({includeRecommendedTags = true} = {}) {
    const payload = {
      requestId: `event-preset-${Date.now()}-${Math.random().toString(16).slice(2)}`,
      ratingId: state.ratingId,
      personId: state.personId,
      categoryId: state.categoryId,
      subcategoryId: state.subcategoryId,
      eventId: state.eventId,
      comboId: state.comboId,
      search: state.search,
      recommendedTagIds: includeRecommendedTags ? Array.from(state.recommendedTagIds) : [],
    };
    if (state.promptDirty || state.selectedExpressionIds.size) {
      payload.promptOverride = promptPreview();
      payload.promptPlan = promptPlan();
    }
    return payload;
  }

  function randomIndex(length) {
    if (!length) return -1;
    return Math.floor(Math.random() * length);
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
    '[data-ep-subcategory-rail]',
    '.event-preset-events-body',
    '[data-ep-expression-category-rail]',
    '[data-ep-expression-subcategory-rail]',
    '[data-ep-expression-items-body]',
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

  function tagInfoAttrs(tag) {
    const clean = cleanPromptAtom(tag);
    return clean ? ` data-ep-tag-info="${escapeHtml(clean)}"` : '';
  }

  function tagKey(tag) {
    return cleanPromptAtom(tag).toLowerCase();
  }

  function renderTagToken(tag, className = 'event-preset-inline-tag', extraAttrs = '') {
    const clean = cleanPromptAtom(tag);
    if (!clean) return '';
    return `<span class="${className}"${tagInfoAttrs(clean)}${extraAttrs}>${escapeHtml(clean)}</span>`;
  }

  function stageableTagAttrs(tag) {
    const clean = cleanPromptAtom(tag);
    return clean
      ? ` data-ep-action="clothes-stage-token" data-ep-tag="${escapeHtml(clean)}"`
      : '';
  }

  function renderPromptTagTokens(text, {stagedTags = null, stageable = false} = {}) {
    const tags = splitPromptTags(text);
    if (!tags.length) return escapeHtml(text || '');
    return tags.map(tag => {
      const staged = stagedTags?.has(tagKey(tag));
      const classNames = ['event-preset-inline-tag'];
      if (staged) classNames.push('event-preset-inline-tag--staged');
      if (stageable) classNames.push('event-preset-inline-tag--stageable');
      return renderTagToken(tag, classNames.join(' '), stageable ? stageableTagAttrs(tag) : '');
    }).join('<span class="event-preset-inline-separator">, </span>');
  }

  function ensureTagInfoTooltip() {
    if (!tagInfoTooltip) {
      tagInfoTooltip = document.createElement('div');
      tagInfoTooltip.className = 'event-preset-tag-tooltip';
      document.body.appendChild(tagInfoTooltip);
    }
    return tagInfoTooltip;
  }

  function positionTagInfoTooltip(event) {
    if (!tagInfoTooltip?.classList.contains('open')) return;
    const viewport = window.visualViewport || {
      width: window.innerWidth,
      height: window.innerHeight,
      offsetLeft: 0,
      offsetTop: 0,
    };
    const margin = 8;
    const gap = 12;
    const anchorRect = tagInfoAnchor?.getBoundingClientRect?.();
    const x = Number.isFinite(event?.clientX) ? event.clientX : (anchorRect?.left || viewport.offsetLeft);
    const y = Number.isFinite(event?.clientY) ? event.clientY : (anchorRect?.bottom || viewport.offsetTop);
    const rect = tagInfoTooltip.getBoundingClientRect();
    const minLeft = viewport.offsetLeft + margin;
    const maxLeft = viewport.offsetLeft + viewport.width - rect.width - margin;
    const minTop = viewport.offsetTop + margin;
    const maxTop = viewport.offsetTop + viewport.height - rect.height - margin;
    let left = x + gap;
    let top = y + gap;
    if (left > maxLeft) left = x - rect.width - gap;
    if (top > maxTop) top = y - rect.height - gap;
    tagInfoTooltip.style.left = `${Math.round(Math.max(minLeft, Math.min(left, maxLeft)))}px`;
    tagInfoTooltip.style.top = `${Math.round(Math.max(minTop, Math.min(top, maxTop)))}px`;
  }

  function hideTagInfoTooltip() {
    if (tagInfoHoverTimer) {
      window.clearTimeout(tagInfoHoverTimer);
      tagInfoHoverTimer = null;
    }
    tagInfoAnchor = null;
    tagInfoRequestSeq += 1;
    tagInfoTooltip?.classList.remove('open');
  }

  function renderTagInfoTooltip(info, tag) {
    const tooltip = ensureTagInfoTooltip();
    const groupText = [info?.group, info?.subgroup].filter(Boolean).join(' / ');
    const desc = info?.desc || '';
    tooltip.innerHTML = `
      <div class="tag-tooltip-main">
        <span class="tag-tooltip-tag">${escapeHtml(info?.tag || tag)}</span>
        ${info?.count ? `<span class="tag-tooltip-count">${escapeHtml(formatCount(info.count))}</span>` : ''}
        ${groupText ? `<span class="tag-tooltip-group">${escapeHtml(groupText)}</span>` : ''}
        ${desc ? `<span class="tag-tooltip-desc">${escapeHtml(desc)}</span>` : '<span class="tag-tooltip-desc">한글 설명 없음</span>'}
      </div>`;
    tooltip.classList.add('open');
  }

  async function showTagInfoTooltip(anchor, event) {
    const tag = cleanPromptAtom(anchor?.dataset?.epTagInfo || '');
    if (!tag || typeof provider.tagLookup !== 'function') return;
    tagInfoAnchor = anchor;
    const tooltip = ensureTagInfoTooltip();
    tooltip.innerHTML = '<div class="tag-tooltip-main"><span class="tag-tooltip-tag">loading...</span></div>';
    tooltip.classList.add('open');
    positionTagInfoTooltip(event);
    const requestSeq = ++tagInfoRequestSeq;
    try {
      let info = tagInfoCache.get(tag.toLowerCase());
      if (!info) {
        info = await provider.tagLookup(tag);
        tagInfoCache.set(tag.toLowerCase(), info || {});
      }
      if (requestSeq !== tagInfoRequestSeq || tagInfoAnchor !== anchor) return;
      if (!info?.tag && !info?.desc && !info?.group) {
        hideTagInfoTooltip();
        return;
      }
      renderTagInfoTooltip(info, tag);
      positionTagInfoTooltip(event);
    } catch (_) {
      if (requestSeq === tagInfoRequestSeq) hideTagInfoTooltip();
    }
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

  function clothesReady() {
    return state.clothesStatus === 'ready'
      && state.clothesData?.dataAvailability?.main === 'ready';
  }

  function clothesRequest(extra = {}) {
    return {
      ratingId: state.ratingId,
      comboId: state.clothesComboId,
      comboSearch: state.clothesSearch,
      itemSearch: state.clothesSearch,
      categoryId: state.clothesCategoryId,
      subcategoryId: state.clothesSubcategoryId,
      stagedItems: state.clothesStagedItems,
      comboLimit: 80,
      itemLimit: 160,
      ...extra,
      pairMode: CLOTHES_PAIR_MODE,
    };
  }

  function applyClothesPayload(payload = {}) {
    const selected = payload.selected || {};
    const browser = payload.browser || {};
    const staged = payload.staged || {};
    state.clothesData = {
      ...state.clothesData,
      ...payload,
      dataAvailability: payload.dataAvailability || state.clothesData.dataAvailability || {},
      capabilities: payload.capabilities || state.clothesData.capabilities || {},
      pairModes: payload.pairModes || state.clothesData.pairModes || [],
      comboRows: payload.comboRows || state.clothesData.comboRows || {rows: []},
      browser: {
        categories: browser.categories || [],
        subcategories: browser.subcategories || [],
        items: browser.items || [],
        selected: browser.selected || {},
      },
      staged: {
        items: staged.items || [],
        groups: staged.groups || [],
        tags: staged.tags || [],
      },
      promptFragment: payload.promptFragment || state.clothesData.promptFragment || {tags: []},
      rules: payload.rules || state.clothesData.rules || {},
    };
    state.clothesPairMode = CLOTHES_PAIR_MODE;
    state.clothesCategoryId = browser.selected?.categoryId || selected.categoryId || state.clothesCategoryId || '';
    state.clothesSubcategoryId = browser.selected?.subcategoryId || selected.subcategoryId || state.clothesSubcategoryId || '';
    if (Object.prototype.hasOwnProperty.call(selected, 'comboId')) {
      state.clothesComboId = selected.comboId || '';
      if (!state.clothesComboId) state.clothesComboFocusTags = [];
    }
    if (Object.prototype.hasOwnProperty.call(selected, 'comboText')) {
      state.clothesComboText = selected.comboText || '';
    }
    state.clothesStagedItems = state.clothesData.staged.items || [];
    const mainState = state.clothesData.dataAvailability?.main || payload.dataMode || '';
    state.clothesStatus = mainState === 'ready' ? 'ready' : (mainState || state.clothesStatus || 'idle');
    state.clothesMessage = state.clothesData.dataAvailability?.message || '';
  }

  async function loadClothes({showLoading = true, extra = {}} = {}) {
    if (!provider.clothesBootstrap) return;
    if (showLoading) {
      state.clothesLoading = true;
      state.clothesStatus = state.clothesStatus === 'idle' ? 'loading' : state.clothesStatus;
      renderAll({preserveScroll: true});
    }
    try {
      const payload = await provider.clothesBootstrap(clothesRequest(extra));
      applyClothesPayload(payload);
      state.clothesLoading = false;
      renderAll({preserveScroll: true});
    } catch (error) {
      state.clothesLoading = false;
      state.clothesStatus = 'error';
      state.clothesMessage = error?.message || 'Clothes Preset 데이터를 불러오지 못했습니다.';
      renderAll({preserveScroll: true});
      showToast?.(state.clothesMessage, 'error');
    }
  }

  async function selectClothes(extra = {}) {
    if (!provider.clothesSelect) return;
    state.clothesLoading = true;
    renderAll({preserveScroll: true});
    try {
      const payload = await provider.clothesSelect(clothesRequest(extra));
      applyClothesPayload(payload);
      state.clothesLoading = false;
      state.promptDirty = false;
      syncPromptText({force: true});
      renderAll({preserveScroll: true});
    } catch (error) {
      state.clothesLoading = false;
      renderAll({preserveScroll: true});
      showToast?.(error?.message || 'Clothes Preset 선택 데이터를 불러오지 못했습니다.', 'error');
    }
  }

  function expressionsReady() {
    return provider.mode === 'fixture'
      || (state.expressionStatus === 'ready' && state.expressionData?.dataAvailability?.main === 'ready');
  }

  function expressionRequest(extra = {}) {
    return {
      ratingId: state.ratingId,
      personId: state.personId,
      limit: 20000,
      ...extra,
    };
  }

  function applyExpressionPayload(payload = {}) {
    state.expressionData = {
      ...state.expressionData,
      ...payload,
      dataAvailability: payload.dataAvailability || state.expressionData.dataAvailability || {},
      counts: payload.counts || state.expressionData.counts || {},
      categories: payload.categories || [],
    };
    const mainState = state.expressionData.dataAvailability?.main || payload.dataMode || '';
    state.expressionStatus = mainState === 'ready' || mainState === 'fixture'
      ? 'ready'
      : (mainState || state.expressionStatus || 'idle');
    state.expressionMessage = state.expressionData.dataAvailability?.message || '';
  }

  async function loadExpressions({showLoading = true} = {}) {
    if (provider.mode === 'fixture' || !provider.expressionBootstrap) {
      renderAll({preserveScroll: true});
      return;
    }
    if (showLoading) {
      state.expressionLoading = true;
      state.expressionStatus = state.expressionStatus === 'idle' ? 'loading' : state.expressionStatus;
      renderAll({preserveScroll: true});
    }
    try {
      const payload = await provider.expressionBootstrap(expressionRequest());
      applyExpressionPayload(payload);
      selectFirstMatchingExpressionSearchResult();
      state.expressionLoading = false;
      renderAll({preserveScroll: true});
    } catch (error) {
      state.expressionLoading = false;
      state.expressionStatus = 'error';
      state.expressionMessage = error?.message || 'Expression Preset 데이터를 불러오지 못했습니다.';
      renderAll({preserveScroll: true});
      showToast?.(state.expressionMessage, 'error');
    }
  }

  function scheduleBootstrap() {
    if (provider.mode === 'fixture') {
      renderAll();
      return;
    }
    if (searchTimer) {
      clearTimeout(searchTimer);
      searchTimer = null;
    }
    const query = state.search.trim();
    if (query && query.length < MIN_SEARCH_LENGTH) return;
    searchTimer = setTimeout(() => {
      searchTimer = null;
      loadBootstrap({showLoading: false});
    }, 260);
  }

  function scheduleClothesLoad() {
    if (provider.mode === 'fixture') {
      renderAll();
      return;
    }
    if (searchTimer) {
      clearTimeout(searchTimer);
      searchTimer = null;
    }
    const query = state.clothesSearch.trim();
    if (query && query.length < MIN_SEARCH_LENGTH) return;
    searchTimer = setTimeout(() => {
      searchTimer = null;
      void loadClothes({showLoading: false});
    }, 260);
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

  function searchActive() {
    return state.search.trim().length >= MIN_SEARCH_LENGTH;
  }

  function findCategory(id = state.categoryId) {
    return categories().find(category => category.id === id)
      || categories().find(category => eventContextsForCategory(category).some(context => eventPassesPartition(context.event)))
      || categories()[0]
      || null;
  }

  function eventContextsForSubcategory(category, subcategory) {
    return (subcategory?.events || []).map(event => ({category, subcategory, event}));
  }

  function eventContextsForCategory(category) {
    const contexts = [];
    for (const subcategory of category?.subcategories || []) {
      contexts.push(...eventContextsForSubcategory(category, subcategory));
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
    if (!query || query.length < MIN_SEARCH_LENGTH) return true;
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

  function filterEventContexts(contexts) {
    const partitioned = (contexts || []).filter(context => eventPassesPartition(context.event));
    return searchActive() ? partitioned.filter(eventMatchesSearch) : partitioned;
  }

  function visibleEventContexts(category = findCategory()) {
    return filterEventContexts(eventContextsForCategory(category));
  }

  function allVisibleEventContexts() {
    return filterEventContexts(categories().flatMap(category => eventContextsForCategory(category)));
  }

  function visibleSubcategoryContexts(category = findCategory()) {
    return (category?.subcategories || []).map(subcategory => {
      const events = filterEventContexts(eventContextsForSubcategory(category, subcategory));
      return {category, subcategory, events};
    }).filter(context => context.events.length);
  }

  function allVisibleSubcategoryContexts() {
    return categories().flatMap(category => visibleSubcategoryContexts(category));
  }

  function currentSubcategoryContexts() {
    return state.searchShowAll && searchActive()
      ? allVisibleSubcategoryContexts()
      : visibleSubcategoryContexts(findCategory());
  }

  function findSubcategoryContext(id = state.subcategoryId) {
    const current = currentSubcategoryContexts();
    return current.find(context => context.subcategory.id === id)
      || current[0]
      || null;
  }

  function currentEventContexts() {
    const selectedSubcategory = findSubcategoryContext();
    if (selectedSubcategory?.events?.length) return selectedSubcategory.events;
    return state.searchShowAll && searchActive()
      ? allVisibleEventContexts()
      : visibleEventContexts(findCategory());
  }

  function eventRowButton(eventId = state.eventId) {
    return Array.from(root.querySelectorAll('[data-ep-action="event"]'))
      .find(row => row.dataset.epId === eventId) || null;
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
    setRecommendedTagIds([]);
    state.promptDirty = false;
    syncPromptText({force: true});
  }

  function selectSubcategoryContext(context) {
    if (!context?.subcategory) {
      selectContext(null);
      return;
    }
    state.categoryId = context.category.id;
    state.subcategoryId = context.subcategory.id;
    selectContext(context.events?.[0] || null);
  }

  async function selectRandomPresetInCategory() {
    if (state.activeAxis === 'clothes') return selectLuckyClothesFocus();
    if (state.activeAxis === 'expressions') return selectRandomExpressionInSubcategory();
    if (!dataReady()) return false;
    const category = findCategory(state.categoryId);
    const rows = visibleEventContexts(category);
    if (!rows.length) return false;
    const context = rows[randomIndex(rows.length)];
    if (!context?.event) return false;
    selectContext(context);
    state.selectionLoading = true;
    renderAll({preserveScroll: true});
    try {
      const payload = await provider.select(selectedPayload());
      applySelectedPayload(payload.selected || {});
      mergeEventDetail(payload.event);
    } catch (error) {
      state.selectionLoading = false;
      renderAll({preserveScroll: true});
      showToast?.(error?.message || 'Event Preset 선택 데이터를 불러오지 못했습니다.', 'error');
      return false;
    }
    const selectedEvent = selectedContext().event;
    const combos = selectedEvent?.observedCombos || [];
    if (combos.length) state.comboId = combos[randomIndex(combos.length)]?.id || state.comboId;
    state.promptDirty = false;
    syncPromptText({force: true});
    state.selectionLoading = false;
    renderAll({preserveScroll: true});
    focusEventRow(selectedEvent?.id || context.event.id);
    resetAssistListScroll();
    return true;
  }

  function canRandomizeCurrentPreset() {
    if (state.activeAxis === 'clothes') return clothesReady() && typeof provider.clothesLucky === 'function';
    if (state.activeAxis === 'expressions') return expressionRandomPool().length > 0;
    if (!dataReady()) return false;
    return visibleEventContexts(findCategory(state.categoryId)).length > 0;
  }

  function expressionRandomPool() {
    if (!expressionsReady()) return [];
    const context = findExpressionSubcategoryContext();
    if (!context?.subcategory) return [];
    return expressionAllItems(context.subcategory)
      .filter(item => expressionItemMatchesSearch(context.category, context.subcategory, item));
  }

  function selectRandomExpressionInSubcategory() {
    const context = findExpressionSubcategoryContext();
    const pool = expressionRandomPool();
    if (!context?.subcategory || !pool.length) return false;
    const item = pool[randomIndex(pool.length)];
    if (!item?.id) return false;
    state.expressionCategoryId = context.category?.id || state.expressionCategoryId;
    state.expressionSubcategoryId = context.subcategory.id || state.expressionSubcategoryId;
    state.expandedExpressionSubcategoryIds.add(String(context.subcategory.id || ''));
    state.selectedExpressionIds = new Set([String(item.id)]);
    state.promptDirty = false;
    syncPromptText({force: true});
    renderAll({preserveScroll: true});
    return true;
  }

  async function selectLuckyClothesFocus() {
    if (!clothesReady() || typeof provider.clothesLucky !== 'function') return false;
    state.clothesLoading = true;
    renderAll({preserveScroll: true});
    try {
      const payload = await provider.clothesLucky(clothesRequest({action: 'luckyFocus'}));
      const lucky = payload?.lucky || {};
      const tags = Array.isArray(lucky.tags) ? lucky.tags : splitPromptTags(lucky.comboText || '');
      if (!lucky.comboId || !tags.length) return false;
      state.clothesComboId = String(lucky.comboId);
      state.clothesComboText = String(lucky.comboText || tags.join(', '));
      state.clothesComboFocusTags = tags;
      state.clothesLoading = false;
      state.promptDirty = false;
      syncPromptText({force: true});
      renderAll({preserveScroll: true});
      return true;
    } catch (error) {
      state.clothesLoading = false;
      renderAll({preserveScroll: true});
      throw error;
    }
  }

  function ensureVisibleSelection() {
    const visible = currentEventContexts();
    if (visible.some(context => context.event.id === state.eventId)) {
      const selected = visible.find(context => context.event.id === state.eventId);
      state.categoryId = selected.category.id;
      state.subcategoryId = selected.subcategory?.id || '';
      return;
    }
    if (visible.length) {
      selectContext(visible[0]);
      return;
    }
    const fallback = allVisibleEventContexts()[0] || null;
    if (!fallback) {
      selectContext(null);
      return;
    }
    selectContext(fallback);
  }

  function focusEventRow(eventId = state.eventId) {
    const row = eventRowButton(eventId);
    if (!row) return;
    row.focus({preventScroll: true});
    row.scrollIntoView({block: 'nearest'});
  }

  function isEditableKeyTarget(target) {
    if (!target?.closest) return false;
    return !!target.closest('input, textarea, select, [contenteditable="true"], .custom-select, .tag-tooltip, .event-preset-search');
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

  const EXPRESSION_BUCKET_META = {
    smile: {id: 'smile', label: 'Smile'},
    shy: {id: 'shy', label: 'Shy'},
    intense: {id: 'intense', label: 'Intense'},
    surprise: {id: 'surprise', label: 'Surprise'},
    distress: {id: 'distress', label: 'Distress'},
    calm: {id: 'calm', label: 'Calm'},
    other: {id: 'other', label: 'Other'},
  };

  const EXPRESSION_SCAFFOLD = [
    {
      id: 'starter-smile',
      label: 'Smile',
      subcategories: [
        {
          id: 'starter-smile-common',
          label: 'Common',
          items: [
            {id: 'starter-smile', label: 'smile', tag: 'smile', tags: ['smile'], count: 0, source: 'starter'},
            {id: 'starter-happy', label: 'happy', tag: 'happy', tags: ['happy'], count: 0, source: 'starter'},
            {id: 'starter-gentle-smile', label: 'gentle smile', tag: 'gentle smile', tags: ['gentle smile'], count: 0, source: 'starter'},
          ],
        },
      ],
    },
    {
      id: 'starter-calm',
      label: 'Calm',
      subcategories: [
        {
          id: 'starter-calm-common',
          label: 'Common',
          items: [
            {id: 'starter-neutral-expression', label: 'neutral expression', tag: 'neutral expression', tags: ['neutral expression'], count: 0, source: 'starter'},
            {id: 'starter-relaxed', label: 'relaxed', tag: 'relaxed', tags: ['relaxed'], count: 0, source: 'starter'},
            {id: 'starter-closed-eyes', label: 'closed eyes', tag: 'closed eyes', tags: ['closed eyes'], count: 0, source: 'starter'},
          ],
        },
      ],
    },
    {
      id: 'starter-intense',
      label: 'Intense',
      subcategories: [
        {
          id: 'starter-intense-common',
          label: 'Common',
          items: [
            {id: 'starter-serious', label: 'serious', tag: 'serious', tags: ['serious'], count: 0, source: 'starter'},
            {id: 'starter-determined', label: 'determined', tag: 'determined', tags: ['determined'], count: 0, source: 'starter'},
            {id: 'starter-confident', label: 'confident', tag: 'confident', tags: ['confident'], count: 0, source: 'starter'},
          ],
        },
      ],
    },
  ];

  function slugId(value, fallback = 'item') {
    const slug = String(value || '')
      .trim()
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-+|-+$/g, '');
    return slug || fallback;
  }

  function classifyExpressionTag(tag) {
    const text = String(tag || '').toLowerCase();
    if (/(smile|happy|laugh|grin|joy)/.test(text)) return EXPRESSION_BUCKET_META.smile;
    if (/(blush|shy|embarrass|bashful|fluster)/.test(text)) return EXPRESSION_BUCKET_META.shy;
    if (/(angry|serious|focused|determined|confident|shout|glare)/.test(text)) return EXPRESSION_BUCKET_META.intense;
    if (/(surpris|shock|wide eyes|open mouth)/.test(text)) return EXPRESSION_BUCKET_META.surprise;
    if (/(sad|cry|scared|fear|worried|nervous|tear)/.test(text)) return EXPRESSION_BUCKET_META.distress;
    if (/(neutral|expressionless|relaxed|sleepy|closed eyes|calm)/.test(text)) return EXPRESSION_BUCKET_META.calm;
    return EXPRESSION_BUCKET_META.other;
  }

  function expressionItemFromValue(value, fallbackId = 'expression') {
    if (typeof value === 'string') {
      const tag = cleanPromptAtom(value);
      return {
        id: slugId(tag, fallbackId),
        label: tag,
        tag,
        tags: tag ? [tag] : [],
        count: 0,
        source: 'raw',
      };
    }
    const combo = value?.expression_combo || value?.prompt || value?.tag || value?.label || value?.id || '';
    const tags = Array.isArray(value?.tags)
      ? value.tags.map(cleanPromptAtom).filter(Boolean)
      : splitPromptTags(combo);
    const label = value?.label || value?.tag || value?.expression_combo || tags.join(', ');
    return {
      id: String(value?.id || slugId(label || tags.join('-'), fallbackId)),
      label: String(label || fallbackId),
      tag: String(value?.tag || tags[0] || label || ''),
      tags,
      count: Number(value?.count || value?.post_count || value?.frequency || 0) || 0,
      confidence: value?.confidence,
      source: value?.source || 'raw',
    };
  }

  function normalizeExpressionSubcategory(raw, groupId, index) {
    const label = raw?.label || raw?.name || raw?.bucket || raw?.id || `Bucket ${index + 1}`;
    const id = String(raw?.id || `${groupId}-${slugId(label, `bucket-${index + 1}`)}`);
    const rawItems = raw?.items || raw?.expressions || raw?.tags || raw?.children || [];
    return {
      id,
      label: String(label),
      count: Number(raw?.count || rawItems.length || 0) || 0,
      items: (Array.isArray(rawItems) ? rawItems : []).map((item, itemIndex) => expressionItemFromValue(item, `${id}-${itemIndex + 1}`)),
    };
  }

  function normalizeExpressionCategory(raw, index) {
    const label = raw?.label || raw?.name || raw?.group || raw?.id || `Group ${index + 1}`;
    const id = String(raw?.id || slugId(label, `group-${index + 1}`));
    const rawSubcategories = raw?.subcategories || raw?.buckets || raw?.groups || [];
    const directItems = raw?.items || raw?.expressions || raw?.tags || [];
    const subcategories = Array.isArray(rawSubcategories) && rawSubcategories.length
      ? rawSubcategories.map((subcategory, subIndex) => normalizeExpressionSubcategory(subcategory, id, subIndex))
      : [normalizeExpressionSubcategory({id: `${id}-all`, label: 'All', items: directItems}, id, 0)];
    return {
      id,
      label: String(label),
      count: Number(raw?.count || subcategories.reduce((sum, item) => sum + Number(item.count || item.items.length || 0), 0)) || 0,
      subcategories,
    };
  }

  function expressionCatalogFromRaw() {
    const raw = viewData.expressionAxis?.categories
      || viewData.expressionAxis?.groups
      || viewData.expressions?.categories
      || viewData.expressions?.groups
      || viewData.expressionGroups
      || [];
    if (!Array.isArray(raw) || !raw.length) return [];
    return raw.map(normalizeExpressionCategory).filter(category => category.subcategories.some(subcategory => subcategory.items.length));
  }

  function expressionCatalogFromEventAssist() {
    const bucketMap = new Map();
    for (const category of categories()) {
      for (const context of eventContextsForCategory(category)) {
        for (const item of context.event?.slots?.expression || []) {
          const tag = cleanPromptAtom(item?.tag || item?.label || item?.id || '');
          if (!tag) continue;
          const bucket = classifyExpressionTag(tag);
          if (!bucketMap.has(bucket.id)) {
            bucketMap.set(bucket.id, {
              id: bucket.id,
              label: bucket.label,
              subcategories: [{
                id: `${bucket.id}-event-assist`,
                label: 'Event Assist',
                count: 0,
                items: [],
              }],
              _seen: new Map(),
            });
          }
          const group = bucketMap.get(bucket.id);
          const subcategory = group.subcategories[0];
          const key = tag.toLowerCase();
          const existing = group._seen.get(key);
          if (existing) {
            existing.count += Number(item?.count || 0) || 0;
            existing.confidence = Math.max(Number(existing.confidence || 0), Number(item?.confidence || 0));
            continue;
          }
          const normalized = expressionItemFromValue({
            ...item,
            id: `event-assist-${slugId(tag)}`,
            tag,
            label: tag,
            tags: [tag],
            source: 'event-assist',
          });
          group._seen.set(key, normalized);
          subcategory.items.push(normalized);
        }
      }
    }
    return Array.from(bucketMap.values()).map(group => {
      const subcategory = group.subcategories[0];
      subcategory.items.sort((left, right) => Number(right.count || 0) - Number(left.count || 0) || left.label.localeCompare(right.label));
      subcategory.count = subcategory.items.reduce((sum, item) => sum + Number(item.count || 0), 0);
      delete group._seen;
      group.count = subcategory.count;
      return group;
    }).filter(group => group.subcategories[0]?.items?.length);
  }

  function expressionCategories() {
    if (provider.mode === 'server') {
      return state.expressionData?.categories || [];
    }
    const raw = expressionCatalogFromRaw();
    if (raw.length) return raw;
    const fromEvents = expressionCatalogFromEventAssist();
    return fromEvents.length ? fromEvents : EXPRESSION_SCAFFOLD;
  }

  function findExpressionCategory(id = state.expressionCategoryId) {
    return expressionCategories().find(category => category.id === id)
      || expressionCategories()[0]
      || null;
  }

  function expressionSearchActive() {
    return state.expressionSearch.trim().length >= MIN_SEARCH_LENGTH;
  }

  function expressionCategoryLabel(category) {
    return category?.labelKo || category?.label || category?.id || '';
  }

  function expressionSubcategoryLabel(subcategory) {
    return subcategory?.labelKo || subcategory?.label || subcategory?.id || '';
  }

  function expressionPrimaryItems(subcategory) {
    return (subcategory?.items || []).filter(item => item && typeof item === 'object');
  }

  function expressionOverflowItems(subcategory) {
    return (subcategory?.moreItems || []).filter(item => item && typeof item === 'object');
  }

  function expressionAllItems(subcategory) {
    return [...expressionPrimaryItems(subcategory), ...expressionOverflowItems(subcategory)];
  }

  function expressionCategoryItemStats(category) {
    const subcategories = category?.subcategories || [];
    let total = 0;
    let matched = 0;
    for (const subcategory of subcategories) {
      const items = expressionAllItems(subcategory);
      total += items.length;
      matched += items.filter(item => expressionItemMatchesSearch(category, subcategory, item)).length;
    }
    return {total, matched};
  }

  function searchCountLabel(matched, total, unit = 'items') {
    return `${formatCount(matched || 0)} / ${formatCount(total || 0)} ${unit}`;
  }

  function expressionItemMatchesSearch(category, subcategory, item) {
    const query = state.expressionSearch.trim().toLowerCase();
    if (!query || query.length < MIN_SEARCH_LENGTH) return true;
    const haystack = [
      expressionCategoryLabel(category),
      category?.label,
      category?.labelKo,
      expressionSubcategoryLabel(subcategory),
      subcategory?.label,
      subcategory?.labelKo,
      item?.label,
      item?.tag,
      ...(item?.tags || []),
    ].join(' ').toLowerCase();
    return haystack.includes(query);
  }

  function visibleExpressionSubcategoryContexts(category = findExpressionCategory()) {
    const contexts = (category?.subcategories || []).map(subcategory => {
      const allItems = expressionAllItems(subcategory);
      const matchedItems = allItems.filter(item => expressionItemMatchesSearch(category, subcategory, item));
      const searchActive = expressionSearchActive();
      const expanded = searchActive || state.expandedExpressionSubcategoryIds.has(String(subcategory.id || ''));
      const primaryCount = expressionPrimaryItems(subcategory).length;
      const items = expanded ? matchedItems : matchedItems.slice(0, primaryCount);
      const totalItems = Number(subcategory.count || allItems.length);
      const matchCount = matchedItems.length;
      return {
        category,
        subcategory,
        items,
        totalItems,
        matchCount,
        disabled: searchActive && matchCount < 1,
        hiddenCount: searchActive || expanded ? 0 : Math.max(0, matchedItems.length - items.length),
        hasOverflow: expressionOverflowItems(subcategory).length > 0,
        expanded,
      };
    }).filter(context => expressionSearchActive() || context.items.length || context.hiddenCount);
    if (expressionSearchActive()) {
      contexts.sort((a, b) => Number(a.disabled) - Number(b.disabled));
    }
    return contexts;
  }

  function currentExpressionSubcategoryContexts() {
    return visibleExpressionSubcategoryContexts(findExpressionCategory());
  }

  function findExpressionSubcategoryContext(id = state.expressionSubcategoryId) {
    const contexts = currentExpressionSubcategoryContexts();
    return contexts.find(context => context.subcategory.id === id)
      || contexts.find(context => !context.disabled)
      || contexts[0]
      || null;
  }

  function selectFirstMatchingExpressionSearchResult() {
    if (!expressionSearchActive()) return;
    const category = expressionCategories().find(candidate => (
      expressionCategoryItemStats(candidate).matched > 0
    ));
    if (!category) return;
    const contexts = visibleExpressionSubcategoryContexts(category);
    const context = contexts.find(candidate => !candidate.disabled) || contexts[0];
    state.expressionCategoryId = category.id || state.expressionCategoryId;
    state.expressionSubcategoryId = context?.subcategory?.id || '';
  }

  function currentExpressionItems() {
    return findExpressionSubcategoryContext()?.items || [];
  }

  function findExpressionItem(id) {
    for (const category of expressionCategories()) {
      for (const subcategory of category.subcategories || []) {
        const item = expressionAllItems(subcategory).find(candidate => candidate.id === id);
        if (item) return {...item, category, subcategory};
      }
    }
    return null;
  }

  function selectedExpressionItems() {
    return Array.from(state.selectedExpressionIds)
      .map(id => findExpressionItem(id))
      .filter(Boolean);
  }

  function expressionFragmentTags() {
    return selectedExpressionItems().flatMap(item => item.tags || []);
  }

  function focusedClothesCombo() {
    if (!state.clothesComboId) return null;
    const row = (state.clothesData?.comboRows?.rows || []).find(candidate => candidate.id === state.clothesComboId);
    if (row) return row;
    if (state.clothesComboText) {
      return {id: state.clothesComboId, comboText: state.clothesComboText, tags: splitPromptTags(state.clothesComboText)};
    }
    return null;
  }

  function focusedClothesTags() {
    const combo = focusedClothesCombo();
    if (!combo) return [];
    if (state.clothesComboFocusTags.length) return uniqueTags(state.clothesComboFocusTags);
    const tags = Array.isArray(combo.tags) && combo.tags.length
      ? combo.tags
      : splitPromptTags(combo.comboText || combo.prompt || state.clothesComboText);
    return uniqueTags(tags);
  }

  function focusedClothesTagSet() {
    return new Set(focusedClothesTags().map(tagKey).filter(Boolean));
  }

  function ensureExpressionBrowserSelection() {
    const category = findExpressionCategory();
    if (!category) {
      state.expressionCategoryId = '';
      state.expressionSubcategoryId = '';
      return;
    }
    const subcategoryContext = findExpressionSubcategoryContext();
    state.expressionCategoryId = subcategoryContext?.category?.id || category.id;
    state.expressionSubcategoryId = subcategoryContext?.subcategory?.id || '';
  }

  function eventFragmentTags() {
    const {event} = selectedContext();
    if (!event) return [];
    const combo = currentCombo(event);
    const baseTags = combo
      ? (combo.prompt ? splitPromptTags(combo.prompt) : (combo.tags || []))
      : (event.promptAtoms?.length ? event.promptAtoms : [event.tag || event.label || event.id]);
    const recommendedTags = selectedRecommendedTags(event)
      .map(item => item?.tag || item?.id || '')
      .map(cleanPromptAtom)
      .filter(Boolean);
    return uniqueTags([...baseTags, ...recommendedTags]);
  }

  function promptPlan() {
    const stagedClothesTags = state.clothesData?.promptFragment?.tags || [];
    const focusClothesTags = focusedClothesTags();
    const fragments = {
      person: PERSON_TAGS[state.personId] || [],
      rating: RATING_TAGS[state.ratingId] ? [RATING_TAGS[state.ratingId]] : [],
      events: eventFragmentTags(),
      clothes: uniqueTags([...stagedClothesTags, ...focusClothesTags]),
      expressions: expressionFragmentTags(),
      manual: [],
    };
    const finalTags = uniqueTags([
      ...fragments.person,
      ...fragments.rating,
      ...fragments.events,
      ...fragments.clothes,
      ...fragments.expressions,
      ...fragments.manual,
    ]);
    return {
      fragments,
      focus: {
        clothes: focusClothesTags,
      },
      finalPrompt: finalTags.join(', '),
    };
  }

  function compositePayload() {
    const plan = promptPlan();
    return {
      requestId: `preset-${Date.now()}-${Math.random().toString(16).slice(2)}`,
      context: {
        ratingId: state.ratingId,
        personId: state.personId,
      },
      axes: {
        events: {
          enabled: !!selectedContext().event,
          categoryId: state.categoryId,
          subcategoryId: state.subcategoryId,
          eventId: state.eventId,
          comboId: state.comboId,
          search: state.search,
          tags: plan.fragments.events,
        },
        clothes: {
          enabled: !!plan.fragments.clothes.length,
          pairMode: CLOTHES_PAIR_MODE,
          comboId: state.clothesComboId,
          comboText: state.clothesComboText,
          temporaryFocus: !!state.clothesComboId,
          focusComboId: state.clothesComboId,
          focusComboText: state.clothesComboText,
          focusComboTags: focusedClothesTags(),
          tags: plan.fragments.clothes,
          categoryId: state.clothesCategoryId,
          subcategoryId: state.clothesSubcategoryId,
          stagedItems: state.clothesStagedItems,
          amendedItems: state.clothesStagedItems,
        },
        expressions: {
          enabled: !!state.selectedExpressionIds.size,
          items: selectedExpressionItems().map(item => ({
            id: item.id,
            tag: item.tag,
            label: item.label,
            tags: item.tags || [],
            source: item.source || 'direct',
          })),
        },
      },
      promptPlan: plan,
      promptOverride: state.promptDirty || state.clothesComboId ? state.promptText : '',
    };
  }

  function computedPromptPreview() {
    return promptPlan().finalPrompt;
  }

  function syncPromptText({force = false} = {}) {
    if (force || !state.promptDirty) state.promptText = computedPromptPreview();
  }

  function promptPreview() {
    return (state.promptDirty ? state.promptText : computedPromptPreview()).trim();
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

  const AXIS_TABS = [
    {id: 'events', label: 'Events'},
    {id: 'clothes', label: 'Clothes'},
    {id: 'expressions', label: 'Expressions'},
  ];

  function activeSearchValue() {
    if (state.activeAxis === 'expressions') return state.expressionSearch;
    if (state.activeAxis === 'clothes') return state.clothesSearch;
    return state.search;
  }

  function clothesSearchActive() {
    return !!state.clothesData.browser?.searchActive
      || state.clothesSearch.trim().length >= MIN_SEARCH_LENGTH;
  }

  function activeSearchPlaceholder() {
    if (state.activeAxis === 'expressions') return 'search expressions...';
    if (state.activeAxis === 'clothes') return 'search clothes...';
    return 'search events...';
  }

  function renderToolbar() {
    const contextRow = root.querySelector('[data-ep-context-row]');
    const ratingControl = root.querySelector('[data-ep-rating-control]');
    const personControl = root.querySelector('[data-ep-person-control]');
    const ratings = root.querySelector('[data-ep-ratings]');
    const person = root.querySelector('[data-ep-person]');
    const showRating = true;
    const showPerson = true;
    if (contextRow) {
      contextRow.hidden = !(showRating || showPerson);
      contextRow.setAttribute('aria-hidden', showRating || showPerson ? 'false' : 'true');
    }
    if (ratingControl) {
      ratingControl.hidden = !showRating;
      ratingControl.setAttribute('aria-hidden', showRating ? 'false' : 'true');
    }
    if (personControl) {
      personControl.hidden = !showPerson;
      personControl.setAttribute('aria-hidden', showPerson ? 'false' : 'true');
    }
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
      person.disabled = state.activeAxis === 'events' && !dataReady() && provider.mode !== 'fixture';
    }
  }

  function renderAxisTabs() {
    const target = root.querySelector('[data-ep-axis-tabs]');
    if (!target) return;
    target.innerHTML = AXIS_TABS.map(axis => `
      <button type="button"
              class="event-preset-axis-tab ${axis.id === state.activeAxis ? 'active' : ''}"
              data-ep-action="axis-tab"
              data-ep-id="${escapeHtml(axis.id)}"
              aria-pressed="${axis.id === state.activeAxis ? 'true' : 'false'}">${escapeHtml(axis.label)}</button>
    `).join('');
  }

  function renderSearchControl() {
    const input = root.querySelector('[data-ep-search]');
    if (!input) return;
    input.value = activeSearchValue();
    input.placeholder = activeSearchPlaceholder();
  }

  function renderAxisBody() {
    const target = root.querySelector('[data-ep-axis-body]');
    if (!target) return;
    if (target.dataset.activeAxis === state.activeAxis) return;
    target.dataset.activeAxis = state.activeAxis;
    if (state.activeAxis === 'expressions') {
      target.innerHTML = `
        <div class="event-preset-browser event-preset-browser--expressions">
          <section class="event-preset-category-pane">
            <div class="event-preset-pane-title">Group</div>
            <nav class="event-preset-category-rail" data-ep-expression-category-rail aria-label="Expression groups"></nav>
          </section>
          <section class="event-preset-subcategory-pane">
            <div class="event-preset-pane-title">Bucket</div>
            <nav class="event-preset-subcategory-rail" data-ep-expression-subcategory-rail aria-label="Expression buckets"></nav>
          </section>
          <section class="event-preset-event-pane" data-ep-expression-items></section>
        </div>
        <section class="event-preset-expression-selection" data-ep-expression-selection></section>
      `;
      return;
    }
    if (state.activeAxis === 'clothes') {
      target.innerHTML = `
        <section class="event-preset-clothes-panel" data-ep-clothes-hook>
          <section class="event-preset-clothes-browser">
            <div class="event-preset-browser event-preset-browser--clothes">
              <section class="event-preset-category-pane">
                <div class="event-preset-pane-title">Category</div>
                <nav class="event-preset-category-rail" data-ep-clothes-category-rail aria-label="Clothes categories"></nav>
              </section>
              <section class="event-preset-subcategory-pane">
                <div class="event-preset-pane-title">Subcategory</div>
                <nav class="event-preset-subcategory-rail" data-ep-clothes-subcategory-rail aria-label="Clothes subcategories"></nav>
              </section>
              <section class="event-preset-event-pane" data-ep-clothes-items></section>
            </div>
          </section>
        </section>
      `;
      return;
    }
    target.innerHTML = `
      <div class="event-preset-browser event-preset-browser--events">
        <section class="event-preset-category-pane">
          <div class="event-preset-pane-title">Category</div>
          <nav class="event-preset-category-rail" data-ep-category-rail aria-label="Event Preset categories"></nav>
        </section>
        <section class="event-preset-subcategory-pane">
          <div class="event-preset-pane-title">Subcategory</div>
          <nav class="event-preset-subcategory-rail" data-ep-subcategory-rail aria-label="Event Preset subcategories"></nav>
        </section>
        <section class="event-preset-event-pane" data-ep-event-table></section>
      </div>
    `;
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
          <span class="event-preset-category-count">${escapeHtml(formatCount((category.subcategories || []).length || 0))} subcats</span>
        </button>`;
    }).join('');
  }

  function renderSubcategories() {
    const rail = root.querySelector('[data-ep-subcategory-rail]');
    if (!rail) return;
    if (state.dataStatus === 'loading') {
      rail.innerHTML = '<div class="event-preset-empty">데이터를 불러오는 중입니다.</div>';
      return;
    }
    if (!dataReady()) {
      rail.innerHTML = `<div class="event-preset-empty">${escapeHtml(state.dataMessage || 'Event Preset data is not ready.')}</div>`;
      return;
    }
    const contexts = currentSubcategoryContexts();
    if (!contexts.length) {
      rail.innerHTML = '<div class="event-preset-empty">표시할 하위 분류가 없습니다.</div>';
      return;
    }
    rail.innerHTML = contexts.map(context => `
      <button type="button"
              class="event-preset-subcategory ${context.subcategory.id === state.subcategoryId ? 'active' : ''}"
              data-ep-action="subcategory"
              data-ep-id="${escapeHtml(context.subcategory.id)}">
        <span class="event-preset-subcategory-name">${escapeHtml(context.subcategory.label || context.subcategory.id)}</span>
        <span class="event-preset-subcategory-count">${escapeHtml(formatCount(context.events.length || 0))} items</span>
      </button>
    `).join('');
  }

  function renderEvents() {
    const target = root.querySelector('[data-ep-event-table]');
    if (!target) return;
    const category = findCategory();
    const subcategory = findSubcategoryContext();
    const rows = currentEventContexts();
    const title = state.searchShowAll && searchActive()
      ? 'Search'
      : (subcategory?.subcategory?.label || category?.label || '-');
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
          <span class="event-preset-event-name"${tagInfoAttrs(context.event.tag)}>${escapeHtml(context.event.label || context.event.tag)}</span>
          <span class="event-preset-event-count">${escapeHtml(formatCount(context.event.count))}</span>
        </button>`).join('')
      : `<div class="event-preset-empty">${escapeHtml(emptyText)}</div>`;
    target.innerHTML = `
      <div class="event-preset-events-head">
        <span>Main Items (${escapeHtml(title)})</span>
        <span>Count</span>
      </div>
      <div class="event-preset-events-body" tabindex="0">${body}</div>`;
  }

  function renderExpressionCategories() {
    const rail = root.querySelector('[data-ep-expression-category-rail]');
    if (!rail) return;
    if (state.expressionLoading || state.expressionStatus === 'loading') {
      rail.innerHTML = '<div class="event-preset-empty">Expression Preset 데이터를 불러오는 중입니다.</div>';
      return;
    }
    if (!expressionsReady()) {
      rail.innerHTML = `<div class="event-preset-empty">${escapeHtml(state.expressionMessage || 'Expression Preset data is not ready.')}</div>`;
      return;
    }
    const categories = expressionCategories();
    if (!categories.length) {
      rail.innerHTML = '<div class="event-preset-empty">No expression groups.</div>';
      return;
    }
    const searchActive = expressionSearchActive();
    rail.innerHTML = categories.map(category => {
      const stats = expressionCategoryItemStats(category);
      const disabled = searchActive && stats.matched < 1;
      const countText = searchActive
        ? searchCountLabel(stats.matched, stats.total)
        : `${formatCount(category.count || stats.total || 0)} items`;
      return `
      <button type="button"
                class="event-preset-category ${category.id === state.expressionCategoryId ? 'active' : ''} ${disabled ? 'is-zero-match' : ''}"
                data-ep-action="expression-category"
                data-ep-id="${escapeHtml(category.id)}"
                ${disabled ? 'disabled aria-disabled="true"' : ''}>
        <span class="event-preset-category-name">${escapeHtml(expressionCategoryLabel(category))}</span>
        <span class="event-preset-category-count">${escapeHtml(countText)}</span>
      </button>
    `;
    }).join('');
  }

  function renderExpressionSubcategories() {
    const rail = root.querySelector('[data-ep-expression-subcategory-rail]');
    if (!rail) return;
    if (state.expressionLoading || state.expressionStatus === 'loading') {
      rail.innerHTML = '<div class="event-preset-empty">데이터를 불러오는 중입니다.</div>';
      return;
    }
    if (!expressionsReady()) {
      rail.innerHTML = '<div class="event-preset-empty">No expression buckets.</div>';
      return;
    }
    const contexts = currentExpressionSubcategoryContexts();
    if (!contexts.length) {
      rail.innerHTML = '<div class="event-preset-empty">No expression buckets.</div>';
      return;
    }
    const searchActive = expressionSearchActive();
    rail.innerHTML = contexts.map(context => {
      const countText = searchActive
        ? searchCountLabel(context.matchCount, context.totalItems)
        : `${formatCount(context.totalItems || 0)} items`;
      return `
      <button type="button"
              class="event-preset-subcategory ${context.subcategory.id === state.expressionSubcategoryId ? 'active' : ''} ${context.disabled ? 'is-zero-match' : ''}"
              data-ep-action="expression-subcategory"
              data-ep-id="${escapeHtml(context.subcategory.id)}"
              ${context.disabled ? 'disabled aria-disabled="true"' : ''}>
        <span class="event-preset-subcategory-name">${escapeHtml(expressionSubcategoryLabel(context.subcategory))}</span>
        <span class="event-preset-subcategory-count">${escapeHtml(countText)}</span>
      </button>
    `;
    }).join('');
  }

  function renderExpressionItems() {
    const target = root.querySelector('[data-ep-expression-items]');
    if (!target) return;
    if (state.expressionLoading || state.expressionStatus === 'loading') {
      target.innerHTML = `
        <div class="event-preset-events-head">
          <span>Main Items (Expressions)</span>
          <span>Count</span>
        </div>
        <div class="event-preset-events-body" data-ep-expression-items-body tabindex="0">
          <div class="event-preset-empty">데이터를 불러오는 중입니다.</div>
        </div>`;
      return;
    }
    if (!expressionsReady()) {
      target.innerHTML = `
        <div class="event-preset-events-head">
          <span>Main Items (Expressions)</span>
          <span>Count</span>
        </div>
        <div class="event-preset-events-body" data-ep-expression-items-body tabindex="0">
          <div class="event-preset-empty">${escapeHtml(state.expressionMessage || 'Expression Preset data is not ready.')}</div>
        </div>`;
      return;
    }
    const items = currentExpressionItems();
    const subcategory = findExpressionSubcategoryContext();
    const rows = items.length
      ? items.map((item, index) => {
        const active = state.selectedExpressionIds.has(item.id);
        const tags = item.tags?.length ? item.tags.join(', ') : item.tag || item.label;
        return `
          <button type="button"
                  class="event-preset-event-row event-preset-expression-row ${active ? 'active' : ''}"
                  data-ep-action="expression-item"
                  data-ep-id="${escapeHtml(item.id)}"
                  aria-pressed="${active ? 'true' : 'false'}">
            <span class="event-preset-event-index">${index + 1}</span>
            <span class="event-preset-event-name"${tagInfoAttrs(item.tag || tags)}>${renderPromptTagTokens(tags)}</span>
            <span class="event-preset-event-count">${escapeHtml(item.count ? formatCount(item.count) : '+')}</span>
          </button>`;
      }).join('')
      : '';
    const moreRow = subcategory?.hasOverflow && !expressionSearchActive()
      ? `
          <button type="button"
                  class="event-preset-event-row event-preset-expression-more"
                  data-ep-action="expression-toggle-more"
                  data-ep-id="${escapeHtml(subcategory.subcategory.id)}">
            <span class="event-preset-event-index">${subcategory.expanded ? '-' : '+'}</span>
            <span class="event-preset-event-name">${escapeHtml(subcategory.expanded ? '접기' : `더 보기 ${formatCount(subcategory.hiddenCount || 0)} items`)}</span>
            <span class="event-preset-event-count">${escapeHtml(subcategory.expanded ? '' : `+${formatCount(subcategory.hiddenCount || 0)}`)}</span>
          </button>`
      : '';
    const body = rows || moreRow ? `${rows}${moreRow}` : '<div class="event-preset-empty">No expressions.</div>';
    target.innerHTML = `
      <div class="event-preset-events-head">
        <span>Main Items (${escapeHtml(expressionSubcategoryLabel(subcategory?.subcategory) || 'Expressions')})</span>
        <span>Count</span>
      </div>
      <div class="event-preset-events-body" data-ep-expression-items-body tabindex="0">${body}</div>`;
  }

  function renderExpressionSelection() {
    const target = root.querySelector('[data-ep-expression-selection]');
    if (!target) return;
    const selected = selectedExpressionItems();
    target.innerHTML = `
      <div class="event-preset-expression-selection-head">
        <span>Expressions Fragment</span>
        <button type="button" data-ep-action="clear-expressions" ${selected.length ? '' : 'disabled'}>Clear</button>
      </div>
      <div class="event-preset-expression-chips">
        ${selected.length ? selected.map(item => `
          <button type="button"
                  class="event-preset-expression-chip"
                  data-ep-action="expression-remove"
                  data-ep-id="${escapeHtml(item.id)}">
            <span>${escapeHtml((item.tags || []).join(', ') || item.label)}</span>
            <b aria-hidden="true">&times;</b>
          </button>
        `).join('') : '<span class="event-preset-expression-empty">No expression tags selected.</span>'}
      </div>
    `;
  }

  function renderExpressions() {
    ensureExpressionBrowserSelection();
    renderExpressionCategories();
    renderExpressionSubcategories();
    renderExpressionItems();
    renderExpressionSelection();
  }

  function renderClothesCombos(scope = root) {
    const summary = scope.querySelector('[data-ep-clothes-combo-summary]');
    const body = scope.querySelector('[data-ep-clothes-combos]');
    if (!body) return;
    const comboRows = state.clothesData.comboRows || {};
    const rows = comboRows.rows || [];
    const stagedTags = clothesStagedTagSet();
    if (summary) summary.textContent = comboRows.summary || 'Combos';
    if (state.clothesLoading && !rows.length) {
      body.innerHTML = '<div class="event-preset-empty">Clothes 데이터를 불러오는 중입니다.</div>';
      return;
    }
    if (state.clothesStatus !== 'ready') {
      body.innerHTML = `<div class="event-preset-empty">${escapeHtml(state.clothesMessage || 'Clothes Preset data is not ready.')}</div>`;
      return;
    }
    body.innerHTML = rows.length
      ? rows.map((row, index) => `
        <button type="button"
                class="event-preset-event-row ${row.selected ? 'active' : ''}"
                data-ep-action="clothes-combo"
                data-ep-id="${escapeHtml(row.id)}">
          <span class="event-preset-event-index">${index + 1}</span>
          <span class="event-preset-event-name">${renderPromptTagTokens(row.comboText || row.prompt || '', {stagedTags, stageable: true})}</span>
          <span class="event-preset-event-count">${escapeHtml(row.displayCount || formatCount(row.count))}</span>
        </button>
      `).join('')
      : '<div class="event-preset-empty">표시할 의상 조합이 없습니다.</div>';
  }

  function clothesStagedTagSet() {
    const result = new Set();
    for (const tag of state.clothesData?.staged?.tags || []) {
      const key = tagKey(tag);
      if (key) result.add(key);
    }
    for (const item of state.clothesData?.staged?.items || []) {
      const key = tagKey(item?.tag || item?.id || item);
      if (key) result.add(key);
    }
    for (const item of state.clothesStagedItems || []) {
      const key = tagKey(item?.tag || item?.id || item);
      if (key) result.add(key);
    }
    return result;
  }

  function renderClothesCategories() {
    const rail = root.querySelector('[data-ep-clothes-category-rail]');
    if (!rail) return;
    const categories = state.clothesData.browser?.categories || [];
    const searchActive = clothesSearchActive();
    rail.innerHTML = categories.length
      ? categories.map(category => {
        const matchedCount = Number(category.matchedCount || 0);
        const totalCount = Number(category.count || 0);
        const disabled = searchActive && matchedCount < 1;
        const countText = searchActive
          ? searchCountLabel(matchedCount, totalCount)
          : `${formatCount(category.subcategoryCount || 0)} groups`;
        return `
        <button type="button"
                class="event-preset-category ${category.selected || category.id === state.clothesCategoryId ? 'active' : ''} ${disabled ? 'is-zero-match' : ''}"
                data-ep-action="clothes-category"
                data-ep-id="${escapeHtml(category.id)}"
                ${disabled ? 'disabled aria-disabled="true"' : ''}>
          <span class="event-preset-category-name">${escapeHtml(category.label || category.id)}</span>
          <span class="event-preset-category-count">${escapeHtml(countText)}</span>
        </button>
      `;
      }).join('')
      : `<div class="event-preset-empty">${escapeHtml(state.clothesMessage || 'No clothes categories.')}</div>`;
  }

  function renderClothesSubcategories() {
    const rail = root.querySelector('[data-ep-clothes-subcategory-rail]');
    if (!rail) return;
    const subcategories = state.clothesData.browser?.subcategories || [];
    const searchActive = clothesSearchActive();
    rail.innerHTML = subcategories.length
      ? subcategories.map(subcategory => {
        const matchedCount = Number(subcategory.matchedCount || 0);
        const totalCount = Number(subcategory.count || 0);
        const disabled = searchActive && matchedCount < 1;
        const countText = searchActive
          ? searchCountLabel(matchedCount, totalCount)
          : `${formatCount(totalCount)} items`;
        return `
        <button type="button"
                class="event-preset-subcategory ${subcategory.selected || subcategory.id === state.clothesSubcategoryId ? 'active' : ''} ${disabled ? 'is-zero-match' : ''}"
                data-ep-action="clothes-subcategory"
                data-ep-id="${escapeHtml(subcategory.id)}"
                ${disabled ? 'disabled aria-disabled="true"' : ''}>
          <span class="event-preset-subcategory-name">${escapeHtml(subcategory.label || subcategory.id)}</span>
          <span class="event-preset-subcategory-count">${escapeHtml(countText)}</span>
        </button>
      `;
      }).join('')
      : '<div class="event-preset-empty">No clothes subcategories.</div>';
  }

  function renderClothesItems() {
    const target = root.querySelector('[data-ep-clothes-items]');
    if (!target) return;
    const items = state.clothesData.browser?.items || [];
    const selectedSubcategory = (state.clothesData.browser?.subcategories || [])
      .find(subcategory => subcategory.selected || subcategory.id === state.clothesSubcategoryId);
    const title = selectedSubcategory?.label || selectedSubcategory?.id || 'Clothes';
    target.innerHTML = `
      <div class="event-preset-events-head">
        <span>Main Items (${escapeHtml(title)})</span>
        <span>Count</span>
      </div>
      <div class="event-preset-events-body" data-ep-clothes-items-body tabindex="0">
        ${items.length ? items.map((item, index) => `
          <button type="button"
                  class="event-preset-event-row event-preset-clothes-row ${item.selected ? 'active' : ''} ${item.incompatible ? 'incompatible' : ''}"
                  data-ep-action="${item.selected ? 'clothes-remove-item' : 'clothes-item'}"
                  data-ep-id="${escapeHtml(item.id || item.tag)}"
                  data-ep-tag="${escapeHtml(item.tag || item.id || '')}"
                  aria-pressed="${item.selected ? 'true' : 'false'}">
            <span class="event-preset-event-index">${index + 1}</span>
            <span class="event-preset-event-name"${tagInfoAttrs(item.tag)}>${escapeHtml(item.label || item.tag)}</span>
            <span class="event-preset-event-count">${escapeHtml(item.displayCount || formatCount(item.postCount || item.count))}</span>
          </button>
        `).join('') : '<div class="event-preset-empty">No clothes items.</div>'}
      </div>
    `;
  }

  function renderClothesStaged(scope = root) {
    const target = scope.querySelector('[data-ep-clothes-staged]');
    if (!target) return;
    const groups = (state.clothesData.staged?.groups || []).filter(group => (group.items || []).length);
    target.innerHTML = `
      <div class="event-preset-expression-selection-head">
        <span>Staged Items</span>
        <button type="button" data-ep-action="clothes-clear" ${groups.length ? '' : 'disabled'}>Clear</button>
      </div>
      <div class="event-preset-clothes-chip-groups">
        ${groups.length ? groups.map(group => `
          <div class="event-preset-clothes-chip-group">
            <span>${escapeHtml(group.label || group.id)}</span>
            <div class="event-preset-expression-chips">
              ${(group.items || []).map(item => `
                <button type="button"
                        class="event-preset-expression-chip event-preset-clothes-chip ${item.promoted ? 'promoted' : ''}"
                        data-ep-action="clothes-remove-item"
                        data-ep-id="${escapeHtml(item.id || item.tag)}"
                        data-ep-tag="${escapeHtml(item.tag)}">
                  <span>${escapeHtml(item.tag)}</span>
                  <b aria-hidden="true">&times;</b>
                </button>
              `).join('')}
            </div>
          </div>
        `).join('') : '<span class="event-preset-expression-empty">No clothes tags selected.</span>'}
      </div>
    `;
  }

  function renderClothes() {
    renderClothesCategories();
    renderClothesSubcategories();
    renderClothesItems();
  }

  function renderPromptPlan() {
    const target = root.querySelector('[data-ep-prompt-plan]');
    if (!target) return;
    const plan = promptPlan();
    const rows = [
      ['Person / Rating', [...plan.fragments.person, ...plan.fragments.rating]],
      ['Events', plan.fragments.events],
      ['Clothes', plan.fragments.clothes],
      ['Expressions', plan.fragments.expressions],
    ];
    const focusedTags = focusedClothesTagSet();
    const stagedTags = clothesStagedTagSet();
    target.innerHTML = rows.map(([label, tags]) => `
      <div class="event-preset-prompt-plan-row">
        <span>${escapeHtml(label)}</span>
        <p>${tags.length ? tags.map(tag => {
          const isClothesFragment = label === 'Clothes';
          const stagedClass = isClothesFragment && stagedTags.has(tagKey(tag))
            ? ' event-preset-plan-tag--staged'
            : '';
          const focusClass = !stagedClass && isClothesFragment && focusedTags.has(tagKey(tag))
            ? ' event-preset-plan-tag--focus'
            : '';
          const stageable = label === 'Clothes' && state.activeAxis === 'clothes';
          const stageClass = stageable ? ' event-preset-plan-tag--stageable' : '';
          return renderTagToken(
            tag,
            `event-preset-plan-tag${stagedClass}${focusClass}${stageClass}`,
            stageable ? stageableTagAttrs(tag) : '',
          );
        }).join('<span class="event-preset-inline-separator">, </span>') : '<em>empty</em>'}</p>
      </div>
    `).join('');
  }

  function renderSelection() {
    const preview = root.querySelector('[data-ep-prompt-preview]');
    syncPromptText();
    renderPromptPlan();
    if (preview) {
      const fallback = state.selectionLoading
        ? '선택 데이터를 불러오는 중입니다.'
        : (!dataReady() ? (state.dataMessage || 'Event Preset data is not ready.') : 'Select an event preset.');
      const nextValue = state.promptText || '';
      if (document.activeElement !== preview && preview.value !== nextValue) preview.value = nextValue;
      preview.placeholder = fallback;
      preview.disabled = !(dataReady() || clothesReady() || expressionsReady());
    }
    if (typeof onGenerateStateChange === 'function') onGenerateStateChange(canGenerateCurrentPreset());
  }

  function renderDownloadOverlay() {
    const panel = root.querySelector('[data-ep-download-overlay]');
    if (!panel) return;
    if (state.activeAxis !== 'events') {
      panel.hidden = true;
      panel.setAttribute('aria-hidden', 'true');
      panel.innerHTML = '';
      return;
    }
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
          <span class="event-preset-assist-row-name">${options.promptBundle ? renderPromptTagTokens(label) : (renderTagToken(label) || escapeHtml(label))}</span>
          <span>${escapeHtml(formatCount(item.count))}</span>
          ${options.showConfidence ? `<span>${escapeHtml(confidence)}</span>` : ''}
        </button>`;
    }).join('');
  }

  function activeRecommendedTitle() {
    if (state.assistTab === 'combos') return 'EVENT GENERATE TAGS';
    return `Event ${activeAssistMeta().title} Tags`;
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
                <span${tagInfoAttrs(item.tag)}>${escapeHtml(item.tag)}</span>
                <span>${escapeHtml(formatCount(item.count))}</span>
              </button>`;
          }).join('')}
        </div>
      </div>`;
  }

  function renderOverlay() {
    if (state.activeAxis === 'clothes') {
      renderClothesOverlay();
      return;
    }
    if (state.activeAxis !== 'events') {
      overlay.innerHTML = '';
      return;
    }
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
            <strong${tagInfoAttrs(event?.tag)}>${escapeHtml(event?.tag || 'No event')}</strong>
            <em>${renderPromptTagTokens(comboSummary)}</em>
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

  function renderClothesOverlay() {
    const stagedCount = state.clothesData?.staged?.items?.length || 0;
    const title = stagedCount ? `${stagedCount} staged` : 'No staged items';
    overlay.innerHTML = `
      <div class="event-preset-assist-card event-preset-assist-card--clothes">
        <header class="event-preset-assist-head">
          <span>Clothes Preset</span>
          <strong>${escapeHtml(title)}</strong>
        </header>
        <section class="event-preset-assist-list-panel prompt-bundles event-preset-clothes-overlay-combos">
          <div class="event-preset-assist-list-head">
            <span data-ep-clothes-combo-summary>Observed Combos</span>
            <span>Count</span>
          </div>
          <div class="event-preset-assist-list event-preset-events-body" data-ep-clothes-combos tabindex="0"></div>
        </section>
        <section class="event-preset-expression-selection event-preset-clothes-staged event-preset-clothes-overlay-staged" data-ep-clothes-staged></section>
      </div>`;
    renderClothesCombos(overlay);
    renderClothesStaged(overlay);
  }

  function renderAll({preserveScroll = true} = {}) {
    const scrollSnapshot = preserveScroll ? captureScrollState() : null;
    if (dataReady()) ensureVisibleSelection();
    ensureExpressionBrowserSelection();
    renderToolbar();
    renderAxisTabs();
    renderSearchControl();
    renderAxisBody();
    if (state.activeAxis === 'events') {
      renderCategories();
      renderSubcategories();
      renderEvents();
    } else if (state.activeAxis === 'expressions') {
      renderExpressions();
    } else if (state.activeAxis === 'clothes') {
      renderClothes();
    }
    renderSelection();
    renderOverlay();
    renderDownloadOverlay();
    if (scrollSnapshot) restoreScrollState(scrollSnapshot);
  }

  function showOverlay() {
    if (state.activeAxis !== 'events' && state.activeAxis !== 'clothes') {
      hideOverlay();
      return;
    }
    if (!state.activeTab || !rightResultPane?.classList.contains('active')) return;
    overlay.hidden = false;
    overlay.setAttribute('aria-hidden', 'false');
    viewer?.classList.add('event-preset-overlay-active');
  }

  function hideOverlay() {
    hideTagInfoTooltip();
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
      const useComposite = provider.mode === 'server'
        && typeof provider.generateComposite === 'function'
        && (
          state.selectedExpressionIds.size
          || (state.clothesData?.promptFragment?.tags || []).length
          || focusedClothesTags().length
        );
      const requestPayload = useComposite ? compositePayload() : selectedPayload({includeRecommendedTags: true});
      const payload = useComposite
        ? await provider.generateComposite(requestPayload)
        : await provider.generate(requestPayload);
      if (!useComposite) applySelectedPayload(payload.selected || {});
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
      showToast?.(useComposite ? 'Preset 생성 요청을 전달했습니다.' : 'Event Preset 생성 요청을 전달했습니다.', 'success');
      return provider.mode === 'server'
        ? {requestId: String(payload.requestId || requestPayload.requestId || '')}
        : false;
    } catch (error) {
      state.generatePending = false;
      renderAll({preserveScroll: true});
      showToast?.(error?.message || 'Preset 생성 요청에 실패했습니다.', 'error');
      return false;
    }
  }

  function canGenerateCurrentPreset() {
    const plan = promptPlan();
    const hasPresetAxis = !!selectedContext().event
      || !!plan.fragments.clothes.length
      || !!plan.fragments.expressions.length;
    return !!promptPreview()
      && !state.generatePending
      && !state.generating
      && !getGenerating?.()
      && hasPresetAxis
      && (dataReady() || clothesReady() || expressionsReady());
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
    if (action === 'axis-tab') {
      const previousAxis = state.activeAxis;
      state.activeAxis = AXIS_TABS.some(axis => axis.id === id) ? id : 'events';
      if (state.activeAxis === 'expressions') hideOverlay();
      if (state.activeAxis === 'expressions' && state.expressionStatus === 'idle') {
        void loadExpressions({showLoading: true});
      }
      if (state.activeAxis === 'clothes' && state.clothesStatus === 'idle') {
        void loadClothes({showLoading: true});
      }
      if (state.activeAxis === 'events' && previousAxis !== 'events') {
        state.searchShowAll = state.search.trim().length >= MIN_SEARCH_LENGTH;
        shouldBootstrap = true;
      }
    } else if (action === 'rating') {
      state.ratingId = id;
      state.searchShowAll = state.search.trim().length >= MIN_SEARCH_LENGTH;
      state.promptDirty = false;
      if (state.activeAxis === 'events') {
        shouldBootstrap = true;
      } else if (state.activeAxis === 'clothes') {
        syncPromptText({force: true});
        void loadClothes({showLoading: false});
      } else {
        syncPromptText({force: true});
      }
    } else if (action === 'category') {
      state.categoryId = id;
      state.searchShowAll = false;
      selectSubcategoryContext(visibleSubcategoryContexts(findCategory(id))[0] || null);
      shouldSelect = true;
    } else if (action === 'subcategory') {
      const context = currentSubcategoryContexts().find(candidate => candidate.subcategory.id === id);
      selectSubcategoryContext(context);
      shouldSelect = true;
      shouldResetAssistScroll = true;
    } else if (action === 'event') {
      const context = currentEventContexts().find(candidate => candidate.event.id === id);
      selectContext(context);
      shouldSelect = true;
      shouldResetAssistScroll = true;
    } else if (action === 'combo') {
      state.comboId = id;
      state.promptDirty = false;
      syncPromptText({force: true});
      shouldSelect = provider.mode === 'server';
    } else if (action === 'assist-tab') {
      state.assistTab = id || 'combos';
    } else if (action === 'recommended') {
      if (state.recommendedTagIds.has(String(id))) state.recommendedTagIds.delete(String(id));
      else state.recommendedTagIds.add(id);
      state.promptDirty = false;
      syncPromptText({force: true});
      shouldSelect = provider.mode === 'server';
    } else if (action === 'clear-recommended') {
      state.recommendedTagIds = new Set();
      state.promptDirty = false;
      syncPromptText({force: true});
      shouldSelect = provider.mode === 'server';
    } else if (action === 'clear-search') {
      if (state.activeAxis === 'expressions') state.expressionSearch = '';
      else if (state.activeAxis === 'clothes') {
        state.clothesSearch = '';
        scheduleClothesLoad();
      }
      else {
        state.search = '';
        state.searchShowAll = false;
        shouldBootstrap = true;
      }
      const input = root.querySelector('[data-ep-search]');
      if (input) input.value = '';
    } else if (action === 'expression-category') {
      state.expressionCategoryId = id;
      const contexts = visibleExpressionSubcategoryContexts(findExpressionCategory(id));
      const nextContext = contexts.find(context => !context.disabled) || contexts[0];
      state.expressionSubcategoryId = nextContext?.subcategory?.id || '';
    } else if (action === 'expression-subcategory') {
      const context = currentExpressionSubcategoryContexts().find(candidate => candidate.subcategory.id === id);
      state.expressionCategoryId = context?.category?.id || state.expressionCategoryId;
      state.expressionSubcategoryId = context?.subcategory?.id || '';
    } else if (action === 'expression-toggle-more') {
      const key = String(id || '');
      if (state.expandedExpressionSubcategoryIds.has(key)) state.expandedExpressionSubcategoryIds.delete(key);
      else if (key) state.expandedExpressionSubcategoryIds.add(key);
    } else if (action === 'expression-item') {
      state.selectedExpressionIds = state.selectedExpressionIds.has(String(id))
        ? new Set()
        : new Set([String(id)]);
      state.promptDirty = false;
      syncPromptText({force: true});
    } else if (action === 'expression-remove') {
      state.selectedExpressionIds.delete(String(id));
      state.promptDirty = false;
      syncPromptText({force: true});
    } else if (action === 'clear-expressions') {
      state.selectedExpressionIds = new Set();
      state.promptDirty = false;
      syncPromptText({force: true});
    } else if (action === 'clothes-combo') {
      const nextComboId = state.clothesComboId === id ? '' : id;
      state.clothesComboId = nextComboId;
      const row = (state.clothesData?.comboRows?.rows || []).find(candidate => candidate.id === nextComboId);
      state.clothesComboFocusTags = nextComboId && Array.isArray(row?.tags) ? row.tags : [];
      state.clothesComboText = nextComboId ? (row?.comboText || row?.prompt || state.clothesComboText || '') : '';
      state.promptDirty = false;
      syncPromptText({force: true});
      void selectClothes({action: nextComboId ? 'focusCombo' : 'clearComboFocus', comboId: nextComboId, applyComboTags: false});
    } else if (action === 'clothes-category') {
      state.clothesCategoryId = id;
      state.clothesSubcategoryId = '';
      void selectClothes({categoryId: id});
    } else if (action === 'clothes-subcategory') {
      state.clothesSubcategoryId = id;
      void selectClothes({subcategoryId: id});
    } else if (action === 'clothes-item') {
      const tag = button.dataset.epTag || id;
      state.clothesComboId = '';
      state.clothesComboText = '';
      state.clothesComboFocusTags = [];
      void selectClothes({action: 'addItem', comboId: '', item: {tag, source: 'direct'}});
    } else if (action === 'clothes-stage-token') {
      const tag = button.dataset.epTag || id;
      if (tag) {
        void selectClothes({action: 'addItem', comboId: state.clothesComboId, item: {tag, source: 'direct'}});
      }
    } else if (action === 'clothes-remove-item') {
      const tag = button.dataset.epTag || id;
      state.clothesComboId = '';
      state.clothesComboText = '';
      state.clothesComboFocusTags = [];
      void selectClothes({action: 'removeItem', comboId: '', removeTag: tag});
    } else if (action === 'clothes-clear') {
      state.clothesComboId = '';
      state.clothesComboText = '';
      state.clothesComboFocusTags = [];
      state.clothesStagedItems = [];
      void selectClothes({action: 'clearAll', comboId: ''});
    } else if (action === 'start-download') {
      void startDownload();
    } else if (action === 'cancel-download') {
      void cancelDownload();
    }
    renderAll({preserveScroll: !(shouldBootstrap || action === 'category' || action === 'axis-tab')});
    if (action === 'event') focusEventRow(id);
    if (shouldBootstrap) loadBootstrap({showLoading: provider.mode === 'server'});
    else if (shouldSelect) loadSelection({showLoading: false, resetAssistScroll: shouldResetAssistScroll});
  }

  function handleSearchInput(event) {
    const input = event.target.closest('[data-ep-search]');
    if (!input) return;
    if (state.activeAxis === 'expressions') {
      state.expressionSearch = input.value || '';
      selectFirstMatchingExpressionSearchResult();
    } else if (state.activeAxis === 'clothes') {
      state.clothesSearch = input.value || '';
      scheduleClothesLoad();
    } else {
      state.search = input.value || '';
      state.searchShowAll = state.search.trim().length >= MIN_SEARCH_LENGTH;
    }
    renderAll();
    if (state.activeAxis === 'events') scheduleBootstrap();
  }

  function handlePromptInput(event) {
    const input = event.target.closest('[data-ep-prompt-preview]');
    if (!input) return;
    state.promptText = input.value || '';
    state.promptDirty = true;
    if (typeof onGenerateStateChange === 'function') onGenerateStateChange(canGenerateCurrentPreset());
  }

  function handleChange(event) {
    const person = event.target.closest('[data-ep-person]');
    if (!person) return;
    state.personId = person.value || '1girl_solo';
    state.searchShowAll = state.search.trim().length >= MIN_SEARCH_LENGTH;
    state.promptDirty = false;
    syncPromptText({force: true});
    renderAll();
    if (state.activeAxis === 'events') {
      loadBootstrap({showLoading: provider.mode === 'server'});
    }
  }

  function handleEventListKeydown(event) {
    if (event.defaultPrevented) return;
    if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return;
    const target = event.target;
    const inEventTable = !!target.closest?.('[data-ep-event-table]');
    const canUseGlobalNav = state.activeAxis === 'events'
      && state.activeTab
      && rightResultPane?.classList.contains('active')
      && !isEditableKeyTarget(target);
    if (!inEventTable && !canUseGlobalNav) return;
    const rows = currentEventContexts();
    if (!rows.length) return;

    event.preventDefault();
    const direction = event.key === 'ArrowDown' ? 1 : -1;
    const currentIndex = rows.findIndex(context => context.event.id === state.eventId);
    const fallbackIndex = direction > 0 ? 0 : rows.length - 1;
    const nextIndex = currentIndex < 0
      ? fallbackIndex
      : Math.max(0, Math.min(rows.length - 1, currentIndex + direction));
    const nextContext = rows[nextIndex];
    if (!nextContext?.event) return;

    selectContext(nextContext);
    renderAll({preserveScroll: true});
    focusEventRow(nextContext.event.id);
    loadSelection({showLoading: false, resetAssistScroll: true});
  }

  function handleTagInfoPointerOver(event) {
    const anchor = event.target.closest?.('[data-ep-tag-info]');
    if (!anchor || !root.contains(anchor) && !overlay.contains(anchor)) return;
    if (tagInfoHoverTimer) window.clearTimeout(tagInfoHoverTimer);
    tagInfoHoverTimer = window.setTimeout(() => {
      tagInfoHoverTimer = null;
      void showTagInfoTooltip(anchor, event);
    }, 180);
  }

  function handleTagInfoPointerMove(event) {
    if (!tagInfoAnchor) return;
    positionTagInfoTooltip(event);
  }

  function handleTagInfoPointerOut(event) {
    const anchor = event.target.closest?.('[data-ep-tag-info]');
    if (!anchor || event.relatedTarget && anchor.contains(event.relatedTarget)) return;
    hideTagInfoTooltip();
  }

  function renderShell() {
    root.innerHTML = `
      <div class="event-preset-filter-row" data-ep-context-row>
        <div class="event-preset-rating-control" data-ep-rating-control>
          <span class="event-preset-control-label">Rating</span>
          <div class="event-preset-chip-row" data-ep-ratings></div>
        </div>
        <label class="event-preset-person-control" data-ep-person-control>
          <span class="event-preset-control-label">Person</span>
          <select class="event-preset-person-select" data-ep-person></select>
        </label>
      </div>
      <label class="event-preset-search">
        <span class="event-preset-search-icon" aria-hidden="true">&#128269;</span>
        <input type="search" data-ep-search value="${escapeHtml(activeSearchValue())}" placeholder="${escapeHtml(activeSearchPlaceholder())}" autocomplete="off" spellcheck="false">
        <button type="button" class="event-preset-search-clear" data-ep-action="clear-search" aria-label="Clear search">&times;</button>
      </label>
      <div class="event-preset-axis-tabs" data-ep-axis-tabs role="tablist" aria-label="Preset axes"></div>
      <div class="event-preset-axis-body" data-ep-axis-body></div>
      <section class="event-preset-footer">
        <div class="event-preset-prompt-plan" data-ep-prompt-plan></div>
        <textarea class="event-preset-preview-text"
                  data-ep-prompt-preview
                  spellcheck="false"
                  autocomplete="off"></textarea>
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
  root.addEventListener('input', handlePromptInput);
  root.addEventListener('change', handleChange);
  root.addEventListener('keydown', handleEventListKeydown);
  root.addEventListener('pointerover', handleTagInfoPointerOver);
  root.addEventListener('pointermove', handleTagInfoPointerMove);
  root.addEventListener('pointerout', handleTagInfoPointerOut);
  overlay.addEventListener('pointerdown', event => event.stopPropagation());
  overlay.addEventListener('pointerover', handleTagInfoPointerOver);
  overlay.addEventListener('pointermove', handleTagInfoPointerMove);
  overlay.addEventListener('pointerout', handleTagInfoPointerOut);
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
    handleEventListKeydown(event);
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
    canRandomize: canRandomizeCurrentPreset,
    randomizeCurrentCategory: selectRandomPresetInCategory,
    randomizeUnavailableMessage() {
      if (state.activeAxis === 'clothes') return '랜덤 선택 가능한 Clothes Preset 조합이 없습니다.';
      if (state.activeAxis === 'expressions') return '랜덤 선택 가능한 Expression Preset이 없습니다.';
      return '랜덤 선택 가능한 Event Preset이 없습니다.';
    },
    setGeneratingStatus(generating) {
      state.generating = !!generating;
      renderSelection();
    },
    getFixtureState: () => viewData,
  };
}
