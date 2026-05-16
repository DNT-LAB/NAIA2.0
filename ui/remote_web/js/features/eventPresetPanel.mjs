import {createEventPresetFixtureState} from './eventPresetFixtures.mjs?v=20260507-event-preset-generate1';

const CLOTHES_SLOT_IDS = new Set(['HEAD_NECK_FACE', 'UPPER_BODY', 'WAIST_HIP', 'ARMS_HANDS', 'LEGS_FEET', 'STYLE']);
const CLOTHES_SLOT_LABEL_KEYS = new Set(['head neck face', 'upper body', 'waist hip', 'arms hands', 'legs feet', 'style']);

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
  getGenerationOverrides,
} = {}) {
  const root = document?.getElementById('eventPresetPanel');
  const overlay = document?.getElementById('eventPresetOverlay');
  const viewer = document?.getElementById('resultViewer') || document?.querySelector('.viewer');
  const rightResultPane = document?.getElementById('rightTabResult');
  if (!root || !overlay) return null;
  const MIN_SEARCH_LENGTH = 2;
  const CLOTHES_PAIR_MODE = 'Balanced';
  const EVENT_SHORTCUT_NOISE_TAGS = new Set([
    'looking at viewer',
    'solo',
    'simple background',
    'white background',
    'transparent background',
    'upper body',
    'portrait',
    'cowboy shot',
    'full body',
  ]);
  const EVENT_SHORTCUT_IDENTITY_TAGS = new Set([
    '1girl',
    '1boy',
    '2girls',
    '2boys',
    'multiple girls',
    'multiple boys',
    'multiple girls multiple boys',
    '1girl 1boy',
  ]);

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

  function decodePresetSegment(value) {
    try {
      return decodeURIComponent(String(value || ''));
    } catch (_) {
      return String(value || '');
    }
  }

  function stripPresetNamespace(value) {
    const raw = String(value || '').trim();
    return raw.includes('::') ? raw.split('::').pop() : raw;
  }

  function normalizePresetMatch(value) {
    return stripPresetNamespace(decodePresetSegment(value))
      .replace(/[_-]+/g, ' ')
      .replace(/\s+/g, ' ')
      .trim()
      .toLowerCase();
  }

  function presetNodeCandidates(node) {
    const rawValues = [
      node?.id,
      node?.tag,
      node?.label,
      node?.labelKo,
      node?.displayLabelKo,
      node?.krDesc,
      node?.krCategory,
    ].filter(value => value != null && value !== '');
    const values = new Set();
    for (const raw of rawValues) {
      const text = String(raw);
      values.add(text);
      values.add(stripPresetNamespace(text));
    }
    return Array.from(values).filter(Boolean);
  }

  function presetNodePathSegment(node) {
    const raw = stripPresetNamespace(node?.id || node?.tag || node?.label || '');
    return raw.replace(/\s+/g, '_').trim();
  }

  function eventPresetAxisPrefix(context = {}) {
    const rating = String(context.ratingId || state.ratingId || 's').trim().toLowerCase() || 's';
    const person = String(context.personId || state.personId || '1girl_solo').trim() || '1girl_solo';
    return `preset:events(${rating}|${person})`;
  }

  function eventPresetPrefixAndTail(token) {
    const base = 'preset:events';
    let raw = String(token || '').trim();
    if (!raw.toLowerCase().startsWith(base)) raw = base;
    let tailStart = base.length;
    if (raw[tailStart] === '(') {
      const close = raw.indexOf(')', tailStart + 1);
      if (close > tailStart) tailStart = close + 1;
    }
    return {
      prefix: raw.slice(0, tailStart) || base,
      tail: raw.slice(tailStart),
    };
  }

  function eventPresetContextFromToken(token) {
    const raw = String(token || '').trim();
    const match = /^preset:events\(([gsqe])\|([^)]+)\)/i.exec(raw);
    if (!match) return {};
    return {
      ratingId: match[1].toLowerCase(),
      personId: match[2],
    };
  }

  function presetPath(axis, segments = []) {
    const encoded = segments
      .map(segment => encodeURIComponent(String(segment || '').trim()))
      .filter(Boolean);
    const prefix = axis === 'events' ? eventPresetAxisPrefix() : `preset:${axis}`;
    return `${prefix}${encoded.length ? '/' + encoded.join('/') : ''}`;
  }

  function presetNodeMatches(node, query) {
    const needle = normalizePresetMatch(query);
    if (!needle) return true;
    return presetNodeCandidates(node).some(candidate => normalizePresetMatch(candidate).includes(needle));
  }

  function findPresetNode(nodes, value) {
    const needle = normalizePresetMatch(value);
    if (!needle) return null;
    return (nodes || []).find(node => presetNodeCandidates(node).some(candidate => normalizePresetMatch(candidate) === needle)) || null;
  }

  function parseEventPresetToken(token) {
    let raw = String(token || '').trim();
    if (!raw.toLowerCase().startsWith('preset:events')) raw = 'preset:events';
    const tail = eventPresetPrefixAndTail(raw).tail;
    const path = tail.startsWith('/') ? tail.slice(1) : tail;
    return {
      raw,
      trailingSlash: path.endsWith('/'),
      segments: path
        ? path.split('/').filter(segment => segment !== '').map(decodePresetSegment)
        : [],
    };
  }

  function parseExpressionPresetToken(token) {
    let raw = String(token || '').trim();
    if (!raw.toLowerCase().startsWith('preset:expressions')) raw = 'preset:expressions';
    const tail = raw.slice('preset:expressions'.length).replace(/^\/+/, '');
    return {
      raw,
      segments: tail
        ? tail.split('/').filter(segment => segment !== '').map(decodePresetSegment)
        : [],
    };
  }

  function clothesTokenTail(token) {
    let raw = String(token || '').trim();
    if (!raw.toLowerCase().startsWith('preset:clothes')) raw = 'preset:clothes';
    let tail = raw.slice('preset:clothes'.length);
    if (tail.startsWith('/')) tail = tail.slice(1);
    return tail;
  }

  function decodeClothesSegment(value) {
    return decodePresetSegment(value).trim();
  }

  function encodeClothesSegment(value) {
    return String(value || '').trim().replace(/&/g, '%26');
  }

  function isClothesSlotSegment(value) {
    const text = String(value || '').trim();
    if (!text) return false;
    if (CLOTHES_SLOT_IDS.has(text.toUpperCase())) return true;
    const normalized = text
      .replace(/[\/_-]+/g, ' ')
      .replace(/\s+/g, ' ')
      .trim()
      .toLowerCase();
    return CLOTHES_SLOT_LABEL_KEYS.has(normalized);
  }

  function canonicalClothesToken(tags, {keepEmpty = false} = {}) {
    const segments = (tags || [])
      .map(tag => encodeClothesSegment(tag))
      .filter((tag, index) => keepEmpty || tag || index < (tags || []).length - 1);
    if (!segments.length) return 'preset:clothes';
    return `preset:clothes/${segments.join('&')}${segments[segments.length - 1] ? '&' : ''}`;
  }

  function parseClothesPresetToken(token, caretOffset = null) {
    let raw = String(token || '').trim();
    if (!raw.toLowerCase().startsWith('preset:clothes')) raw = 'preset:clothes';
    const tail = clothesTokenTail(raw);
    if (!tail.includes('&')) {
      const path = tail ? tail.split('/').filter(Boolean).map(decodeClothesSegment) : [];
      return {
        raw,
        mode: 'browse',
        activeIndex: null,
        activeQuery: path[path.length - 1] || '',
        activePath: path,
        segments: [],
        stagedTags: [],
        resolveTags: [],
        randomizeOnResolve: false,
        resolveMode: 'browse',
      };
    }
    const rawSegments = tail.split('&');
    let activeIndex = rawSegments.length - 1;
    if (Number.isFinite(caretOffset)) {
      const rel = Math.max(0, Math.min(Number(caretOffset) - ('preset:clothes/'.length), tail.length));
      let start = 0;
      rawSegments.some((segment, index) => {
        const end = start + segment.length;
        if (rel >= start && rel <= end) {
          activeIndex = index;
          return true;
        }
        start = end + 1;
        return false;
      });
    }
    if (tail.endsWith('&') && rawSegments.length === 2 && rawSegments[1] === '') {
      activeIndex = 1;
    }
    const segments = rawSegments.map((segment, index) => {
      const decoded = decodeClothesSegment(segment);
      const path = decoded ? decoded.split('/').filter(Boolean).map(part => part.trim()) : [];
      const browse = path.length > 1 || isClothesSlotSegment(decoded);
      return {
        index,
        raw: decoded,
        empty: !decoded,
        browse,
        path,
        tag: decoded && !browse ? decoded : '',
        active: index === activeIndex,
      };
    });
    const active = segments[activeIndex] || null;
    const resolveTags = uniqueTags(segments
      .filter(segment => segment.tag)
      .map(segment => segment.tag));
    const randomizeOnResolve = tail.endsWith('&') && resolveTags.length > 0;
    return {
      raw,
      mode: 'staged',
      activeIndex,
      activeQuery: active?.browse ? (active.path[active.path.length - 1] || '') : (active?.raw || ''),
      activePath: active?.browse ? active.path : [],
      segments,
      stagedTags: uniqueTags(segments
        .filter(segment => !segment.active && segment.tag)
        .map(segment => segment.tag)),
      resolveTags,
      randomizeOnResolve,
      resolveMode: randomizeOnResolve ? 'random_seed' : 'fixed_tags',
    };
  }

  function clothesTokenWithActiveSegment(parsed, value) {
    if (parsed.mode !== 'staged') return `preset:clothes/${encodeClothesSegment(value)}`;
    const segments = parsed.segments.map(segment => segment.raw);
    const activeIndex = Number.isInteger(parsed.activeIndex) ? parsed.activeIndex : Math.max(0, segments.length - 1);
    segments[activeIndex] = value;
    return `preset:clothes/${segments.map(encodeClothesSegment).join('&')}`;
  }

  function dedupeClothesTokenSegments(segments) {
    const seen = new Set();
    const result = [];
    for (const segment of segments || []) {
      const clean = String(segment || '').trim();
      if (!clean) {
        result.push('');
        continue;
      }
      if (isClothesSlotSegment(clean) || clean.includes('/')) {
        result.push(clean);
        continue;
      }
      const key = normalizePresetMatch(clean);
      if (!key || seen.has(key)) continue;
      seen.add(key);
      result.push(clean);
    }
    return result;
  }

  function clothesTokenAfterItemSelection(parsed, tag) {
    const clean = String(tag || '').trim();
    if (!clean) return parsed.raw || 'preset:clothes';
    if (parsed.mode !== 'staged') return canonicalClothesToken([clean]);
    const segments = parsed.segments.map(segment => segment.raw);
    const activeIndex = Number.isInteger(parsed.activeIndex) ? parsed.activeIndex : Math.max(0, segments.length - 1);
    segments[activeIndex] = clean;
    if (segments[segments.length - 1]) segments.push('');
    return `preset:clothes/${dedupeClothesTokenSegments(segments).map(encodeClothesSegment).join('&')}`;
  }

  function comboShortcutTags(combo) {
    if (Array.isArray(combo?.tags) && combo.tags.length) {
      const tags = [];
      combo.tags.forEach(tag => {
        const text = String(tag || '').trim();
        if (!text) return;
        if (text.includes(',')) tags.push(...splitPromptTags(text));
        else tags.push(text);
      });
      if (tags.length) return tags;
    }
    for (const key of ['prompt', 'comboText', 'label', 'tag', 'id']) {
      const value = combo?.[key];
      if (!value) continue;
      const split = splitPromptTags(value);
      return split.length ? split : [String(value).trim()];
    }
    return [];
  }

  function shortcutTagKey(value) {
    return normalizePresetMatch(value);
  }

  function eventAnchorKeys(event) {
    const values = [];
    ['id', 'tag', 'label', 'canonicalLabel', 'prompt'].forEach(key => {
      const value = event?.[key];
      if (!value) return;
      const split = splitPromptTags(value);
      values.push(...(split.length ? split : [String(value)]));
    });
    if (Array.isArray(event?.promptAtoms)) values.push(...event.promptAtoms);
    return new Set(values.map(shortcutTagKey).filter(Boolean));
  }

  function eventComboShortcutProfile(event, combo) {
    const seen = new Set();
    const tagKeys = [];
    comboShortcutTags(combo).forEach(tag => {
      const key = shortcutTagKey(tag);
      if (!key || seen.has(key)) return;
      seen.add(key);
      tagKeys.push(key);
    });
    const anchors = eventAnchorKeys(event || {});
    const anchorHits = tagKeys.filter(tag => anchors.has(tag));
    const noiseHits = tagKeys.filter(tag => EVENT_SHORTCUT_NOISE_TAGS.has(tag) && !anchors.has(tag));
    const identityHits = tagKeys.filter(tag => EVENT_SHORTCUT_IDENTITY_TAGS.has(tag) && !anchors.has(tag));
    const informativeTags = tagKeys.filter(tag => (
      !anchors.has(tag) &&
      !EVENT_SHORTCUT_NOISE_TAGS.has(tag) &&
      !EVENT_SHORTCUT_IDENTITY_TAGS.has(tag)
    ));
    const singleton = tagKeys.length <= 1;
    const count = Number(combo?.count || combo?.postCount || combo?.confidence || 0);
    const score =
      Math.log1p(Math.max(0, Number.isFinite(count) ? count : 0)) +
      informativeTags.length * 4 +
      anchorHits.length * 2 +
      Math.min(tagKeys.length, 6) * 0.2 -
      noiseHits.length * 2.5 -
      identityHits.length * 1.5 -
      (singleton ? 9 : 0) -
      (anchorHits.length ? 0 : 3);
    return {
      score: Math.round(score * 10000) / 10000,
      eligible: tagKeys.length >= 2 && informativeTags.length > 0,
      reason: singleton ? 'single_tag' : (informativeTags.length ? 'shortcut' : 'low_information'),
      tags: tagKeys,
    };
  }

  function rankEventCombosForShortcut(event, combos) {
    return (combos || [])
      .filter(combo => combo && typeof combo === 'object')
      .map((combo, index) => {
        const profile = eventComboShortcutProfile(event, combo);
        return {
          ...combo,
          _shortcutScore: profile.score,
          _shortcutEligible: profile.eligible,
          _shortcutReason: profile.reason,
          _shortcutTags: profile.tags,
          _shortcutOriginalIndex: index,
        };
      })
      .sort((left, right) => {
        const leftEligible = left._shortcutEligible ? 0 : 1;
        const rightEligible = right._shortcutEligible ? 0 : 1;
        if (leftEligible !== rightEligible) return leftEligible - rightEligible;
        if (right._shortcutScore !== left._shortcutScore) return right._shortcutScore - left._shortcutScore;
        if (Number(right.count || 0) !== Number(left.count || 0)) return Number(right.count || 0) - Number(left.count || 0);
        return left._shortcutOriginalIndex - right._shortcutOriginalIndex;
      });
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

  function autocompleteContextPayload() {
    const ratingOptions = Array.isArray(viewData?.ratings) && viewData.ratings.length
      ? viewData.ratings
      : [
        {id: 'g', label: 'G'},
        {id: 's', label: 'S'},
        {id: 'q', label: 'Q'},
        {id: 'e', label: 'E'},
      ];
    const personOptions = Array.isArray(viewData?.persons) && viewData.persons.length
      ? viewData.persons
      : [{id: state.personId || '1girl_solo', label: String(state.personId || '1girl_solo').replace(/_/g, ' ')}];
    return {
      ratingId: state.ratingId || 's',
      personId: state.personId || '1girl_solo',
      ratingOptions,
      personOptions,
    };
  }

  function clothesAutocompleteContextPayload() {
    const context = autocompleteContextPayload();
    return {
      ratingId: context.ratingId,
      ratingOptions: context.ratingOptions,
    };
  }

  function applyAutocompleteContext(context = {}, options = {}) {
    let changed = false;
    const nextRating = String(context.ratingId || state.ratingId || 's').toLowerCase();
    const nextPerson = String(context.personId || state.personId || '1girl_solo');
    if (nextRating && nextRating !== state.ratingId) {
      state.ratingId = nextRating;
      changed = true;
    }
    if (nextPerson && nextPerson !== state.personId) {
      state.personId = nextPerson;
      changed = true;
    }
    if (changed && options.resetSelection) {
      state.categoryId = '';
      state.subcategoryId = '';
      state.eventId = '';
      state.comboId = '';
      state.recommendedTagIds = new Set();
      state.promptDirty = false;
    }
    return changed;
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

  function eventPresetStatusRow(token, message, status = 'preset') {
    return {
      tag: String(status || 'preset'),
      value: token,
      count: 0,
      desc: message || 'Event Preset data is not ready.',
      group: 'preset/events',
      cat: 'status',
      _wc_type: 'preset_status',
      disabled: true,
      axis: 'events',
      stage: 'status',
    };
  }

  function clothesPresetStatusRow(token, message, status = 'preset') {
    return {
      tag: String(status || 'preset'),
      value: token,
      count: 0,
      desc: message || 'Clothes Preset data is not ready.',
      group: 'preset/clothes',
      cat: 'status',
      _wc_type: 'preset_status',
      disabled: true,
      axis: 'clothes',
      stage: 'status',
    };
  }

  function expressionPresetStatusRow(token, message, status = 'preset') {
    return {
      tag: String(status || 'preset'),
      value: token,
      count: 0,
      desc: message || 'Expression Preset data is not ready.',
      group: 'preset/expressions',
      cat: 'status',
      _wc_type: 'preset_status',
      disabled: true,
      axis: 'expressions',
      stage: 'status',
    };
  }

  function eventPresetRowLabel(node) {
    const raw = stripPresetNamespace(node?.label || node?.tag || node?.id || '').replace(/_/g, ' ').trim();
    return raw ? raw.charAt(0).toUpperCase() + raw.slice(1) : '';
  }

  function eventPresetRowLabelKo(node) {
    return String(node?.displayLabelKo || node?.labelKo || '').trim();
  }

  function eventPresetCrumb(node, stage) {
    return {
      id: String(node?.id || node?.tag || node?.label || ''),
      label: eventPresetRowLabel(node),
      labelKo: eventPresetRowLabelKo(node),
      stage,
    };
  }

  function eventPresetRowDesc(node, stage) {
    const labelKo = eventPresetRowLabelKo(node);
    const krDesc = String(node?.krDesc || node?.descKo || '').trim();
    const fallback = (() => {
      if (stage === 'category') return `${(node?.subcategories || []).length} subcategories`;
      if (stage === 'subcategory') return `${(node?.events || []).length} items`;
      if (stage === 'item') return (node?.promptAtoms || []).join(', ');
      return comboPromptText(node);
    })();
    if (krDesc && labelKo && krDesc !== labelKo) return `${labelKo} · ${krDesc}`;
    if (krDesc) return krDesc;
    if (labelKo) return fallback ? `${labelKo} · ${fallback}` : labelKo;
    return fallback;
  }

  function eventPresetRowTags(node, stage, options = {}) {
    if (stage === 'combo') {
      const comboTags = node?.prompt ? splitPromptTags(node.prompt) : (node?.tags || []);
      return eventBaseTags(options.event || {}, comboTags);
    }
    return node?.tags || node?.promptAtoms || [];
  }

  function eventPresetSuggestionRows(nodes, stage, parentSegments, limit, options = {}) {
    const query = String(parentSegments.query || '');
    const pathParents = parentSegments.path || [];
    const sourceNodes = stage === 'combo'
      ? rankEventCombosForShortcut(options.event || {}, nodes || [])
      : (nodes || []);
    return sourceNodes
      .filter(node => presetNodeMatches(node, query))
      .slice(0, limit)
      .map(node => {
        const segment = presetNodePathSegment(node);
        const final = stage === 'combo';
        const value = presetPath('events', [...pathParents, segment]);
        const tags = eventPresetRowTags(node, stage, options);
        const labelKo = eventPresetRowLabelKo(node);
        return {
          tag: eventPresetRowLabel(node),
          value,
          count: Number(node?.count || 0),
          desc: eventPresetRowDesc(node, stage),
          group: 'preset/events',
          cat: stage,
          _wc_type: 'preset_path',
          axis: 'events',
          stage,
          final,
          id: String(node?.id || node?.tag || node?.label || segment),
          rawLabel: node?.label || node?.tag || node?.id || segment,
          labelKo,
          labelEn: node?.labelEn || node?.displayLabel || '',
          krDesc: node?.krDesc || '',
          krCategory: node?.krCategory || '',
          prompt: tags.length ? tags.join(', ') : (comboPromptText(node) || (node?.promptAtoms || []).join(', ')),
          tags,
          shortcutScore: node?._shortcutScore,
          shortcutEligible: node?._shortcutEligible,
          shortcutReason: node?._shortcutReason,
        };
      });
  }

  function syncAutocompleteSelection(category = null, subcategory = null, event = null) {
    let changed = false;
    if (category?.id && state.categoryId !== category.id) {
      state.categoryId = category.id;
      changed = true;
    }
    if (subcategory?.id && state.subcategoryId !== subcategory.id) {
      state.subcategoryId = subcategory.id;
      changed = true;
    } else if (!subcategory && changed) {
      state.subcategoryId = '';
    }
    if (event?.id && state.eventId !== event.id) {
      state.eventId = event.id;
      state.comboId = event.observedCombos?.[0]?.id || '';
      state.recommendedTagIds = new Set();
      changed = true;
    } else if (!event && changed) {
      state.eventId = '';
      state.comboId = '';
    }
    if (changed) {
      state.promptDirty = false;
      renderAll({preserveScroll: true});
    }
  }

  async function ensureAutocompleteEventDetail(context, options = {}) {
    const event = context?.event;
    if (!event?.id) return event || null;
    if (Array.isArray(event.observedCombos) || event._detailLoaded) return event;
    if (typeof provider.select !== 'function') return event;
    const mutateSelection = options.mutateSelection !== false;
    const payload = {
      ...selectedPayload({includeRecommendedTags: false}),
      categoryId: context.category?.id || '',
      subcategoryId: context.subcategory?.id || '',
      eventId: event.id,
      comboId: '',
    };
    const result = await provider.select(payload);
    if (mutateSelection) applySelectedPayload(result?.selected || payload);
    if (result?.event) {
      result.event._detailLoaded = true;
      mergeEventDetail(result.event);
    }
    const merged = findContextInData(viewData, event.id)?.event || result?.event || event;
    merged._detailLoaded = true;
    return merged;
  }

  function markActiveEventRows(rows, event) {
    if (!event) return rows || [];
    const activeEventKeys = new Set([
      event.id,
      event.tag,
      event.label,
      presetNodePathSegment(event),
    ].map(normalizePresetMatch).filter(Boolean));
    (rows || []).forEach(row => {
      const rowKeys = [row.id, row.tag, row.rawLabel, row.value?.split('/').pop()]
        .map(normalizePresetMatch)
        .filter(Boolean);
      row.active = rowKeys.some(key => activeEventKeys.has(key));
    });
    return rows || [];
  }

  async function eventObservedComboRows(category, subcategory, event, eventPath, query, limit) {
    if (!event) return [];
    const detailedEvent = await ensureAutocompleteEventDetail({category, subcategory, event}, {mutateSelection: false});
    return eventPresetSuggestionRows(
      detailedEvent?.observedCombos || [],
      'combo',
      {query, path: eventPath},
      limit,
      {event: detailedEvent || event},
    );
  }

  async function ensureEventPresetAutocompleteData(context = {}) {
    state.activeAxis = 'events';
    const contextChanged = applyAutocompleteContext(context);
    if (contextChanged || !state.loaded) {
      await loadBootstrap({showLoading: true});
    } else {
      renderAll({preserveScroll: true});
    }
  }

  async function ensureClothesPresetAutocompleteData(parsed, limit = 80, inlineSearch = '') {
    state.activeAxis = 'clothes';
    const stagedItems = (parsed.stagedTags || []).map(tag => ({tag, source: 'shortcut'}));
    const comboStagedTags = parsed.mode === 'staged'
      ? (parsed.resolveTags || parsed.stagedTags || [])
      : (parsed.stagedTags || []);
    const activePath = parsed.activePath || [];
    const searchQuery = String(inlineSearch || '').trim();
    const extra = {
      stagedItems,
      comboStagedTags,
      comboLimit: Math.max(80, limit),
      itemLimit: Math.max(160, limit),
    };
    if (activePath.length >= 1) extra.categoryId = activePath[0];
    if (activePath.length >= 2) extra.subcategoryId = activePath[1];
    if (activePath.length >= 3) extra.itemSearch = activePath[2];
    if (parsed.mode === 'staged' && !activePath.length && parsed.activeQuery) {
      extra.itemSearch = parsed.activeQuery;
    }
    if (parsed.mode === 'browse') {
      if (activePath.length >= 1) extra.categoryId = activePath[0];
      if (activePath.length >= 2) extra.subcategoryId = activePath[1];
      if (activePath.length >= 3) extra.itemSearch = activePath[2];
    }
    if (searchQuery) extra.itemSearch = searchQuery;
    await loadClothes({showLoading: state.clothesStatus === 'idle', extra});
  }

  async function buildEventPresetAutocomplete(token, limit = 12, options = {}) {
    const parsed = parseEventPresetToken(token);
    const inlineSearch = String(options.search || '').trim();
    const syncSelection = options.syncSelection === true;
    const allCategories = categories();
    const categorySegment = parsed.segments[0] || '';
    const category = findPresetNode(allCategories, categorySegment);
    if (!category) {
      return {
        stage: 'category',
        crumbs: [],
        rows: eventPresetSuggestionRows(allCategories, 'category', {query: inlineSearch || categorySegment, path: []}, limit),
      };
    }

    const categoryPath = [presetNodePathSegment(category)];
    const categoryCrumbs = [eventPresetCrumb(category, 'category')];
    if (syncSelection) syncAutocompleteSelection(category, null, null);
    if (parsed.segments.length < 2) {
      return {
        stage: 'subcategory',
        crumbs: categoryCrumbs,
        rows: eventPresetSuggestionRows(category.subcategories || [], 'subcategory', {query: inlineSearch, path: categoryPath}, limit),
      };
    }

    const subcategorySegment = parsed.segments[1] || '';
    const subcategory = findPresetNode(category.subcategories || [], subcategorySegment);
    if (!subcategory) {
      return {
        stage: 'subcategory',
        crumbs: categoryCrumbs,
        rows: eventPresetSuggestionRows(category.subcategories || [], 'subcategory', {
          query: inlineSearch || subcategorySegment,
          path: categoryPath,
        }, limit),
      };
    }

    const subcategoryPath = [...categoryPath, presetNodePathSegment(subcategory)];
    const subcategoryCrumbs = [...categoryCrumbs, eventPresetCrumb(subcategory, 'subcategory')];
    if (syncSelection) syncAutocompleteSelection(category, subcategory, null);
    if (parsed.segments.length < 3) {
      const itemQuery = inlineSearch;
      const itemRows = eventPresetSuggestionRows(subcategory.events || [], 'item', {query: itemQuery, path: subcategoryPath}, limit);
      const previewEvent = (subcategory.events || []).find(event => presetNodeMatches(event, itemQuery)) || null;
      markActiveEventRows(itemRows, previewEvent);
      return {
        stage: 'item',
        crumbs: subcategoryCrumbs,
        rows: itemRows,
        secondaryStage: 'combo',
        secondaryCrumbs: previewEvent ? [...subcategoryCrumbs, eventPresetCrumb(previewEvent, 'item')] : subcategoryCrumbs,
        secondaryRows: await eventObservedComboRows(
          category,
          subcategory,
          previewEvent,
          previewEvent ? [...subcategoryPath, presetNodePathSegment(previewEvent)] : subcategoryPath,
          '',
          limit,
        ),
      };
    }

    const eventSegment = parsed.segments[2] || '';
    const event = findPresetNode(subcategory.events || [], eventSegment);
    if (!event) {
      const itemQuery = inlineSearch || eventSegment;
      const matchingEvents = (subcategory.events || []).filter(candidate => presetNodeMatches(candidate, itemQuery));
      const previewEvent = matchingEvents[0] || null;
      const itemRows = eventPresetSuggestionRows(subcategory.events || [], 'item', {
        query: itemQuery,
        path: subcategoryPath,
      }, limit);
      markActiveEventRows(itemRows, previewEvent);
      return {
        stage: 'item',
        crumbs: subcategoryCrumbs,
        rows: itemRows,
        secondaryStage: 'combo',
        secondaryCrumbs: previewEvent ? [...subcategoryCrumbs, eventPresetCrumb(previewEvent, 'item')] : subcategoryCrumbs,
        secondaryRows: await eventObservedComboRows(
          category,
          subcategory,
          previewEvent,
          previewEvent ? [...subcategoryPath, presetNodePathSegment(previewEvent)] : subcategoryPath,
          '',
          limit,
        ),
      };
    }

    if (syncSelection) syncAutocompleteSelection(category, subcategory, event);
    const matchingInlineEvents = inlineSearch
      ? (subcategory.events || []).filter(candidate => presetNodeMatches(candidate, inlineSearch))
      : [];
    const previewEvent = inlineSearch && !presetNodeMatches(event, inlineSearch)
      ? (matchingInlineEvents[0] || event)
      : event;
    const previewChanged = previewEvent !== event;
    const eventPath = [...subcategoryPath, presetNodePathSegment(previewEvent)];
    const itemRows = markActiveEventRows(eventPresetSuggestionRows(
      subcategory.events || [],
      'item',
      {query: inlineSearch, path: subcategoryPath},
      limit,
    ), previewEvent);
    return {
      stage: 'item',
      crumbs: [...subcategoryCrumbs, eventPresetCrumb(previewEvent, 'item')],
      rows: itemRows,
      secondaryStage: 'combo',
      secondaryCrumbs: [...subcategoryCrumbs, eventPresetCrumb(previewEvent, 'item')],
      secondaryRows: await eventObservedComboRows(
        category,
        subcategory,
        previewEvent,
        eventPath,
        previewChanged ? '' : (inlineSearch || parsed.segments[3] || ''),
        limit,
      ),
    };
  }

  function clothesRowLabel(row) {
    return String(row?.label || row?.tag || row?.comboText || row?.prompt || row?.id || '').trim();
  }

  function clothesRowLabelKo(row) {
    return String(row?.displayLabelKo || row?.labelKo || '').trim();
  }

  function clothesDescParts(row, fallbackParts = []) {
    const parts = [];
    const labelKo = clothesRowLabelKo(row);
    const krDesc = String(row?.krDesc || '').trim();
    if (labelKo) parts.push(labelKo);
    if (krDesc && krDesc !== labelKo) parts.push(krDesc);
    for (const part of fallbackParts) {
      const clean = String(part || '').trim();
      if (clean && !parts.includes(clean)) parts.push(clean);
    }
    return parts;
  }

  function renderClothesDisplayLabel(row, label) {
    const labelText = String(label || '').trim();
    const labelKo = clothesRowLabelKo(row);
    return `
      <span class="event-preset-clothes-label-main">${escapeHtml(labelText)}</span>
      ${labelKo ? `<small class="event-preset-ko-label">${escapeHtml(labelKo)}</small>` : ''}
    `;
  }

  function clothesItemTag(row) {
    return String(row?.tag || row?.label || row?.id || '').trim();
  }

  function clothesCrumb(id, label, stage, labelKo = '') {
    return {id: String(id || ''), label: String(label || id || ''), labelKo: String(labelKo || ''), stage};
  }

  function matchingClothesCategoryRows(categories, parsed, limit) {
    return clothesCategoryRows(categories, parsed, limit);
  }

  function clothesInvalidBrowseSearchQuery(activePath) {
    const parts = (activePath || []).map(part => String(part || '').trim()).filter(Boolean);
    if (!parts.length) return '';
    return parts[parts.length - 1] || parts[0] || '';
  }

  async function clothesSearchRowsFromInvalidPath(parsed, query, limit) {
    const searchItems = await collectClothesInlineSearchItems(parsed, query, limit);
    const rowParsed = {
      ...parsed,
      activeQuery: '',
      activePath: [],
    };
    const browser = state.clothesData.browser || {};
    const categoryId = browser.selected?.categoryId || state.clothesCategoryId || '';
    const subcategoryId = browser.selected?.subcategoryId || state.clothesSubcategoryId || '';
    const category = browser.categories?.find(item => item.id === categoryId);
    const subcategory = browser.subcategories?.find(item => item.id === subcategoryId);
    return {
      stage: 'item',
      crumbs: [
        ...(categoryId ? [clothesCrumb(categoryId, category?.label || categoryId, 'category', category?.labelKo)] : []),
        ...(subcategoryId ? [clothesCrumb(subcategoryId, subcategory?.label || subcategoryId, 'subcategory', subcategory?.labelKo)] : []),
      ],
      parsed: rowParsed,
      rows: clothesItemRows(searchItems, rowParsed, categoryId, subcategoryId, limit),
    };
  }

  function clothesCategoryRows(categories, parsed, limit) {
    const query = parsed.mode === 'browse' ? (parsed.activePath[0] || '') : parsed.activeQuery;
    return (categories || [])
      .filter(category => presetNodeMatches({id: category.id, label: category.label}, query))
      .slice(0, limit)
      .map(category => {
        const path = category.id || category.label || '';
        const value = parsed.mode === 'staged'
          ? clothesTokenWithActiveSegment(parsed, path)
          : presetPath('clothes', [path]);
        return {
          tag: category.label || category.id,
          value,
          count: Number(category.count || category.matchedCount || 0),
          desc: clothesDescParts(category, [`${formatCount(category.subcategoryCount || category.matchedSubcategoryCount || 0)} groups`]).join(' · '),
          group: 'preset/clothes',
          cat: 'category',
          _wc_type: 'preset_path',
          axis: 'clothes',
          stage: 'category',
          final: false,
          id: String(category.id || ''),
          rawLabel: category.label || category.id || '',
          labelKo: category.labelKo || '',
          tags: [],
          prompt: '',
        };
      });
  }

  function clothesSubcategoryRows(subcategories, parsed, categoryId, limit) {
    const query = parsed.activePath[1] || '';
    return (subcategories || [])
      .filter(subcategory => presetNodeMatches({id: subcategory.id, label: subcategory.label}, query))
      .slice(0, limit)
      .map(subcategory => {
        const pathSegment = [categoryId, subcategory.id || subcategory.label || ''].filter(Boolean).join('/');
        const value = parsed.mode === 'staged'
          ? clothesTokenWithActiveSegment(parsed, pathSegment)
          : presetPath('clothes', [categoryId, subcategory.id || subcategory.label || '']);
        return {
          tag: subcategory.label || subcategory.id,
          value,
          count: Number(subcategory.count || subcategory.matchedCount || 0),
          desc: clothesDescParts(subcategory, [`${formatCount(subcategory.count || 0)} items`]).join(' · '),
          group: 'preset/clothes',
          cat: 'subcategory',
          _wc_type: 'preset_path',
          axis: 'clothes',
          stage: 'subcategory',
          final: false,
          id: String(subcategory.id || ''),
          rawLabel: subcategory.label || subcategory.id || '',
          labelKo: subcategory.labelKo || '',
          tags: [],
          prompt: '',
        };
      });
  }

  function clothesItemRows(items, parsed, categoryId, subcategoryId, limit) {
    const query = parsed.activePath[2] || (!parsed.activePath.length ? parsed.activeQuery : '');
    const stagedKeys = clothesCommittedTagKeys(parsed);
    return (items || [])
      .filter(item => presetNodeMatches({id: item.id, tag: item.tag, label: item.label}, query))
      .filter(item => !stagedKeys.has(normalizePresetMatch(clothesItemTag(item))))
      .slice(0, limit)
      .map(item => {
        const tag = clothesItemTag(item);
        const pathValue = [categoryId || item.slot || '', subcategoryId || item.group || '', tag].filter(Boolean).join('/');
        const value = parsed.mode === 'staged'
          ? clothesTokenWithActiveSegment(parsed, pathValue)
          : presetPath('clothes', [categoryId || item.slot || '', subcategoryId || item.group || '', tag]);
        const tokenValue = clothesTokenAfterItemSelection(parsed, tag);
        return {
          tag: clothesRowLabel(item) || tag,
          value,
          count: Number(item.postCount || item.count || 0),
          desc: clothesDescParts(item, [
            [item.slotLabelKo || item.slotLabel || item.slot, item.groupLabelKo || item.group].filter(Boolean).join(' / '),
            item.incompatible ? 'incompatible' : '',
          ]).join(' · '),
          group: 'preset/clothes',
          cat: 'item',
          _wc_type: 'preset_path',
          axis: 'clothes',
          stage: 'item',
          final: false,
          id: String(item.id || tag),
          rawLabel: item.label || item.tag || item.id || tag,
          labelKo: item.labelKo || '',
          krDesc: item.krDesc || '',
          krCategory: item.krCategory || '',
          slotLabelKo: item.slotLabelKo || '',
          groupLabelKo: item.groupLabelKo || '',
          clothesTag: tag,
          clothesTokenValue: tokenValue,
          prompt: tag,
          tags: [tag],
          selected: !!item.selected,
          incompatible: !!item.incompatible,
        };
      });
  }

  function clothesCommittedTagKeys(parsed) {
    const activeIndex = Number.isInteger(parsed?.activeIndex) ? parsed.activeIndex : -1;
    const keys = new Set();
    for (const segment of parsed?.segments || []) {
      if (!segment || segment.index === activeIndex) continue;
      const key = normalizePresetMatch(segment.tag || '');
      if (key) keys.add(key);
    }
    if (keys.size) return keys;
    for (const tag of parsed?.stagedTags || []) {
      const key = normalizePresetMatch(tag);
      if (key) keys.add(key);
    }
    return keys;
  }

  function clothesComboRows(rows, limit) {
    return (rows || []).slice(0, limit).map(row => {
      const comboId = String(row?.id || '');
      const tags = Array.isArray(row?.tags) && row.tags.length
        ? row.tags
        : splitPromptTags(row?.prompt || row?.comboText || '');
      const readableToken = canonicalClothesToken(tags);
      return {
        tag: row.comboText || row.prompt || comboId,
        value: readableToken,
        count: Number(row.count || row.postCount || 0),
        desc: clothesDescParts(row, [row.prompt || row.comboText || '']).join(' · '),
        group: 'preset/clothes',
        cat: 'combo',
        _wc_type: 'preset_path',
        axis: 'clothes',
        stage: 'combo',
        final: true,
        comboId,
        labelKo: row.labelKo || '',
        clothesTokenValue: readableToken,
        prompt: tags.join(', '),
        tags,
      };
    });
  }

  function clothesSearchScore(row, query) {
    const needle = String(query || '').trim().toLowerCase();
    const tag = clothesItemTag(row).toLowerCase();
    if (!needle) return 0;
    if (tag === needle) return 0;
    if (tag.startsWith(`${needle} `) || tag.startsWith(`${needle}_`)) return 1;
    if (new RegExp(`(^|[\\s_\\-])${needle.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}([\\s_\\-]|$)`).test(tag)) return 2;
    if (tag.includes(needle)) return 3;
    return 4;
  }

  function sortClothesSearchItems(items, query) {
    return [...(items || [])].sort((a, b) => {
      const score = clothesSearchScore(a, query) - clothesSearchScore(b, query);
      if (score) return score;
      return Number(b?.postCount || b?.count || 0) - Number(a?.postCount || a?.count || 0);
    });
  }

  async function collectClothesInlineSearchItems(parsed, searchQuery, limit) {
    const stagedItems = (parsed.stagedTags || []).map(tag => ({tag, source: 'shortcut'}));
    const seen = new Set();
    const items = [];
    const payload = await provider.clothesBootstrap(clothesRequest({
      stagedItems,
      itemSearch: searchQuery,
      itemLimit: Math.max(160, limit),
      comboLimit: 0,
      searchScope: 'all',
    }));
    for (const item of payload?.browser?.items || []) {
      const tag = clothesItemTag(item);
      const key = tag.toLowerCase();
      if (!key || seen.has(key)) continue;
      seen.add(key);
      items.push(item);
      if (items.length >= limit) break;
    }
    return sortClothesSearchItems(items, searchQuery).slice(0, limit);
  }

  function randomFrom(items) {
    return Array.isArray(items) && items.length ? items[randomIndex(items.length)] : null;
  }

  function clothesItemAlreadyStaged(item, parsed) {
    const tag = clothesItemTag(item);
    const key = normalizePresetMatch(tag);
    if (!key) return true;
    const stagedKeys = new Set((parsed.stagedTags || []).map(normalizePresetMatch).filter(Boolean));
    return stagedKeys.has(key);
  }

  async function getClothesRandomAutocompleteSelection(token, {caretOffset = null, search = '', limit = 500} = {}) {
    const normalized = String(token || '').trim() || 'preset:clothes';
    if (!normalized.toLowerCase().startsWith('preset:clothes')) {
      return {ok: false, message: 'Clothes Preset token is required.'};
    }
    const parsed = parseClothesPresetToken(normalized, caretOffset);
    const activePath = parsed.activePath || [];
    const query = String(search || '').trim()
      || (activePath.length >= 3 ? activePath[2] : '')
      || (parsed.mode === 'staged' && !activePath.length ? parsed.activeQuery : '');
    if (query) {
      const searchItems = await collectClothesInlineSearchItems(parsed, query, Math.max(160, limit));
      const rowParsed = {
        ...parsed,
        activeQuery: '',
        activePath: activePath.length > 2 ? activePath.slice(0, 2) : activePath,
      };
      const itemRows = clothesItemRows(
        searchItems.filter(item => !item?.incompatible && !clothesItemAlreadyStaged(item, parsed)),
        rowParsed,
        '',
        '',
        Math.max(160, limit),
      );
      const row = randomFrom(itemRows);
      if (!row) {
        return {ok: false, message: 'No random Clothes candidates for the current search.'};
      }
      return {
        ok: true,
        axis: 'clothes',
        row,
        token: row.clothesTokenValue || row.value,
      };
    }
    const extra = {
      stagedItems: (parsed.stagedTags || []).map(tag => ({tag, source: 'shortcut'})),
      comboLimit: Math.max(160, limit),
      itemLimit: Math.max(160, limit),
    };
    if (activePath.length >= 1) extra.categoryId = activePath[0];
    if (activePath.length >= 2) extra.subcategoryId = activePath[1];
    if (query) extra.itemSearch = query;
    await loadClothes({showLoading: false, extra});

    const browser = state.clothesData.browser || {};
    const categoryId = browser.selected?.categoryId || activePath[0] || state.clothesCategoryId || '';
    const subcategoryId = browser.selected?.subcategoryId || activePath[1] || state.clothesSubcategoryId || '';
    const itemRows = clothesItemRows(
      (browser.items || []).filter(item => !item?.incompatible && !clothesItemAlreadyStaged(item, parsed)),
      parsed,
      categoryId,
      subcategoryId,
      Math.max(160, limit),
    );
    const row = randomFrom(itemRows);
    if (!row) {
      return {ok: false, message: 'No random Clothes candidates for the current staging.'};
    }
    return {
      ok: true,
      axis: 'clothes',
      row,
      token: row.clothesTokenValue || row.value,
    };
  }

  async function buildClothesPresetAutocomplete(token, limit = 12, caretOffset = null, inlineSearch = '') {
    const parsed = parseClothesPresetToken(token, caretOffset);
    const searchQuery = String(inlineSearch || '').trim();
    if (searchQuery) {
      state.activeAxis = 'clothes';
      if (!clothesReady()) {
        await ensureClothesPresetAutocompleteData(parsed, limit);
      }
    } else {
      await ensureClothesPresetAutocompleteData(parsed, limit);
    }
    const browser = state.clothesData.browser || {};
    const comboRows = state.clothesData.comboRows || {};
    const activePath = parsed.activePath || [];
    const categories = browser.categories || [];
    const categoryId = activePath[0] || browser.selected?.categoryId || state.clothesCategoryId || '';
    const category = categories.find(item => item.id === categoryId) || (activePath[0] ? null : categories[0] || null);
    const subcategories = browser.subcategories || [];
    const subcategoryId = activePath[1] || browser.selected?.subcategoryId || state.clothesSubcategoryId || '';
    const subcategory = subcategories.find(item => item.id === subcategoryId) || (activePath[1] ? null : subcategories[0] || null);

    if (parsed.mode === 'browse' && activePath.length && !category && !String(activePath[0] || '').startsWith('combo-')) {
      if (activePath.length === 1) {
        const categoryRows = matchingClothesCategoryRows(categories, parsed, limit);
        if (categoryRows.length) {
          return {
            stage: 'category',
            crumbs: [],
            parsed,
            rows: categoryRows,
          };
        }
      }
      return clothesSearchRowsFromInvalidPath(parsed, clothesInvalidBrowseSearchQuery(activePath), limit);
    }

    if (searchQuery) {
      const searchItems = await collectClothesInlineSearchItems(parsed, searchQuery, limit);
      const rowParsed = {
        ...parsed,
        activeQuery: '',
        activePath: activePath.length > 2 ? activePath.slice(0, 2) : activePath,
      };
      return {
        stage: 'item',
        crumbs: [
          ...(category
            ? [clothesCrumb(category.id, category.label, 'category')]
            : (categoryId ? [clothesCrumb(categoryId, categoryId, 'category')] : [])),
          ...(subcategory
            ? [clothesCrumb(subcategory.id, subcategory.label, 'subcategory')]
            : (subcategoryId ? [clothesCrumb(subcategoryId, subcategoryId, 'subcategory')] : [])),
        ],
        parsed,
        rows: clothesItemRows(searchItems, rowParsed, categoryId, subcategoryId, limit),
      };
    }

    if (parsed.mode === 'browse' && activePath.length === 1 && String(activePath[0] || '').startsWith('combo-')) {
      const combo = (comboRows.rows || []).find(row => row.id === activePath[0]);
      return {
        stage: 'combo',
        crumbs: [],
        parsed,
        rows: combo ? clothesComboRows([combo], limit) : [],
      };
    }
    if (parsed.mode === 'browse' && !activePath.length) {
      return {
        stage: 'category',
        crumbs: [],
        parsed,
        rows: clothesCategoryRows(categories, parsed, limit),
      };
    }
    if (parsed.mode === 'staged' && !activePath.length && !parsed.activeQuery) {
      return {
        stage: 'category',
        crumbs: [],
        parsed,
        rows: clothesCategoryRows(categories, parsed, limit),
      };
    }
    if (activePath.length < 1 && parsed.activeQuery) {
      return {
        stage: 'item',
        crumbs: [],
        parsed,
        rows: clothesItemRows(browser.items || [], parsed, categoryId, subcategoryId, limit),
      };
    }
    if (activePath.length < 2) {
      return {
      stage: 'subcategory',
      crumbs: category
        ? [clothesCrumb(category.id, category.label, 'category')]
        : (activePath[0] ? [clothesCrumb(activePath[0], activePath[0], 'category')] : []),
      parsed,
      rows: clothesSubcategoryRows(subcategories, parsed, categoryId || activePath[0], limit),
    };
  }
    return {
      stage: 'item',
      crumbs: [
        ...(category
          ? [clothesCrumb(category.id, category.label, 'category')]
          : (activePath[0] ? [clothesCrumb(activePath[0], activePath[0], 'category')] : [])),
        ...(subcategory
          ? [clothesCrumb(subcategory.id, subcategory.label, 'subcategory')]
          : (activePath[1] ? [clothesCrumb(activePath[1], activePath[1], 'subcategory')] : [])),
      ],
      parsed,
      rows: clothesItemRows(browser.items || [], parsed, categoryId || activePath[0], subcategoryId || activePath[1], limit),
    };
  }

  async function getPresetAutocompletePayload(token, {context = {}, limit = 12, caretOffset = null, search = ''} = {}) {
    if (String(token || '').trim().toLowerCase().startsWith('preset:expressions')) {
      const normalized = String(token || '').trim() || 'preset:expressions';
      const loadState = {
        main: state.expressionData?.dataAvailability?.main || state.expressionStatus || '',
        message: state.expressionData?.dataAvailability?.message || state.expressionMessage || '',
      };
      try {
        const payload = await buildExpressionPresetAutocomplete(normalized, limit, context, search);
        const rows = payload.rows?.length
          ? payload.rows
          : [expressionPresetStatusRow(normalized, 'No Expression Preset items for this path.', 'empty')];
        return {
          query: normalized,
          results: rows,
          preset: {
            axis: 'expressions',
            stage: payload.stage || 'category',
            crumbs: payload.crumbs || [],
            parsed: payload.parsed || null,
            detail: payload.detail || null,
            context: autocompleteContextPayload(),
            loadState: {
              main: state.expressionData?.dataAvailability?.main || state.expressionStatus || '',
              message: state.expressionData?.dataAvailability?.message || state.expressionMessage || '',
            },
            dataReady: expressionsReady(),
          },
        };
      } catch (error) {
        return {
          query: normalized,
          results: [expressionPresetStatusRow(normalized, error?.message || loadState.message || 'Expression Preset lookup failed.', 'error')],
          preset: {
            axis: 'expressions',
            stage: 'status',
            context: autocompleteContextPayload(),
            loadState,
            dataReady: false,
          },
        };
      }
    }
    if (String(token || '').trim().toLowerCase().startsWith('preset:clothes')) {
      const normalized = String(token || '').trim() || 'preset:clothes';
      const loadState = {
        main: state.clothesData?.dataAvailability?.main || state.clothesStatus || '',
        message: state.clothesData?.dataAvailability?.message || state.clothesMessage || '',
      };
      try {
        const payload = await buildClothesPresetAutocomplete(normalized, limit, caretOffset, search);
        const rows = payload.rows?.length
          ? payload.rows
          : [clothesPresetStatusRow(normalized, 'No Clothes Preset items for this path.', 'empty')];
        const parsed = payload.parsed || null;
        const secondaryRows = parsed?.mode === 'staged'
          ? clothesComboRows((state.clothesData.comboRows || {}).rows || [], limit)
          : [];
        return {
          query: normalized,
          results: rows,
          secondaryResults: secondaryRows,
          preset: {
            axis: 'clothes',
            stage: payload.stage || 'category',
            crumbs: payload.crumbs || [],
            parsed,
            context: clothesAutocompleteContextPayload(),
            loadState: {
              main: state.clothesData?.dataAvailability?.main || state.clothesStatus || '',
              message: state.clothesData?.dataAvailability?.message || state.clothesMessage || '',
            },
            dataReady: clothesReady(),
          },
        };
      } catch (error) {
        return {
          query: normalized,
          results: [clothesPresetStatusRow(normalized, error?.message || loadState.message || 'Clothes Preset lookup failed.', 'error')],
          preset: {
            axis: 'clothes',
            stage: 'status',
            context: clothesAutocompleteContextPayload(),
            loadState,
            dataReady: false,
          },
        };
      }
    }
    const normalized = String(token || '').trim().toLowerCase().startsWith('preset:events')
      ? String(token || '').trim()
      : 'preset:events';
    const tokenContext = eventPresetContextFromToken(normalized);
    await ensureEventPresetAutocompleteData({...context, ...tokenContext});
    const loadState = {
      main: dataAvailability().main || state.dataStatus || '',
      message: dataAvailability().message || state.dataMessage || '',
    };
    if (!dataReady()) {
      return {
        query: normalized,
        results: [eventPresetStatusRow(normalized, loadState.message || 'Event Preset data is not ready.', loadState.main || 'missing')],
        preset: {
          axis: 'events',
          stage: 'status',
          context: autocompleteContextPayload(),
          loadState,
          dataReady: false,
        },
      };
    }
    const payload = await buildEventPresetAutocomplete(normalized, limit, {search});
    const rows = payload.rows?.length
      ? payload.rows
      : [eventPresetStatusRow(normalized, 'No Event Preset items for this path.', 'empty')];
    const secondaryRows = Array.isArray(payload.secondaryRows) ? payload.secondaryRows : [];
    return {
      query: normalized,
      results: rows,
      secondaryResults: secondaryRows,
        preset: {
          axis: 'events',
          stage: payload.stage || 'category',
          secondaryStage: payload.secondaryStage || '',
          crumbs: payload.crumbs || [],
          secondaryCrumbs: payload.secondaryCrumbs || [],
          context: autocompleteContextPayload(),
          loadState,
          dataReady: true,
      },
    };
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

  async function ensureExpressionPresetAutocompleteData(context = {}) {
    const contextChanged = applyAutocompleteContext(context);
    state.activeAxis = 'expressions';
    if (!expressionsReady() || contextChanged) {
      await loadExpressions({showLoading: state.expressionStatus === 'idle' || contextChanged});
      return;
    }
    renderAll({preserveScroll: true});
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

  function eventPromptAtoms(event) {
    if (Array.isArray(event?.promptAtoms) && event.promptAtoms.length) {
      const atoms = event.promptAtoms.map(cleanPromptAtom).filter(Boolean);
      if (atoms.length) return atoms;
    }
    for (const key of ['tag', 'id', 'label']) {
      const value = cleanPromptAtom(event?.[key]);
      if (value) return [value];
    }
    return [];
  }

  function eventBaseTags(event, baseTags) {
    const base = uniqueTags(baseTags);
    const baseKeys = new Set(base.map(normalizePresetMatch).filter(Boolean));
    const missing = eventPromptAtoms(event).filter(tag => !baseKeys.has(normalizePresetMatch(tag)));
    return uniqueTags([...missing, ...base]);
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

  function expressionItemTitle(item) {
    return item?.displayLabelKo
      || item?.displayLabel
      || item?.canonicalLabel
      || item?.label
      || item?.tag
      || item?.id
      || '';
  }

  function expressionItemTags(item) {
    if (Array.isArray(item?.tags) && item.tags.length) return item.tags;
    if (Array.isArray(item?.coreTags) && item.coreTags.length) return item.coreTags;
    const raw = item?.prompt || item?.tagSummary || item?.canonicalLabel || item?.label || item?.tag || '';
    return String(raw || '')
      .split(',')
      .map(part => part.trim())
      .filter(Boolean);
  }

  function expressionItemTagSummary(item) {
    return expressionItemTags(item).join(', ');
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
      if (subcategory?.isVirtual) continue;
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
      item?.displayLabel,
      item?.displayLabelKo,
      item?.canonicalLabel,
      item?.tagSummary,
      item?.label,
      item?.tag,
      ...(item?.coreTags || []),
      ...(item?.decoratorTags || []),
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

  function expressionNodeCandidates(node) {
    const values = new Set();
    [
      node?.id,
      node?.tag,
      node?.label,
      node?.labelKo,
      node?.displayLabel,
      node?.displayLabelKo,
      node?.canonicalLabel,
      node?.prompt,
      node?.tagSummary,
    ].forEach(value => {
      if (value != null && value !== '') values.add(String(value));
    });
    for (const tag of [
      ...(node?.tags || []),
      ...(node?.coreTags || []),
      ...(node?.decoratorTags || []),
    ]) {
      if (tag != null && tag !== '') values.add(String(tag));
    }
    return Array.from(values).filter(Boolean);
  }

  function expressionNodeMatches(node, query) {
    const needle = normalizePresetMatch(query);
    if (!needle) return true;
    return expressionNodeCandidates(node).some(candidate => normalizePresetMatch(candidate).includes(needle));
  }

  function findExpressionNode(nodes, value) {
    const needle = normalizePresetMatch(value);
    if (!needle) return null;
    return (nodes || []).find(node => expressionNodeCandidates(node).some(candidate => normalizePresetMatch(candidate) === needle)) || null;
  }

  function expressionCrumb(id, label, stage) {
    return {id: String(id || ''), label: String(label || id || ''), stage};
  }

  function expressionItemPath(category, subcategory, item) {
    return [
      category?.id || category?.label || '',
      subcategory?.id || subcategory?.label || '',
      item?.id || item?.tag || item?.label || '',
    ].filter(Boolean);
  }

  function expressionShortcutSegment(item, tags = expressionItemTags(item)) {
    const cleanTags = (tags || [])
      .map(tag => cleanPromptAtom(tag))
      .filter(Boolean);
    const text = cleanTags.length > 1
      ? cleanTags.join(' + ')
      : (cleanTags[0] || expressionItemTitle(item));
    return String(text || '')
      .replace(/\//g, ' ')
      .replace(/\s+/g, ' ')
      .trim();
  }

  function expressionShortcutToken(item, tags = expressionItemTags(item)) {
    const segment = expressionShortcutSegment(item, tags);
    return `preset:expressions${segment ? '/' + segment : ''}`;
  }

  function expressionDirectQueryTags(value) {
    const text = String(value || '').trim();
    if (!text.includes('+')) return [];
    return text.split('+').map(part => cleanPromptAtom(part)).filter(Boolean);
  }

  function expressionItemHasTags(item, tags) {
    const keys = new Set(expressionItemTags(item).map(tag => normalizePresetMatch(tag)).filter(Boolean));
    return (tags || []).every(tag => keys.has(normalizePresetMatch(tag)));
  }

  function findExpressionDirectItemContext(categories, value) {
    const needle = normalizePresetMatch(value);
    if (!needle) return null;
    const requiredTags = expressionDirectQueryTags(value);
    for (const category of categories || []) {
      for (const subcategory of category.subcategories || []) {
        for (const item of expressionAllItems(subcategory)) {
          if (requiredTags.length && expressionItemHasTags(item, requiredTags)) {
            return {category, subcategory, item};
          }
          if (!requiredTags.length && expressionNodeCandidates(item).some(candidate => normalizePresetMatch(candidate) === needle)) {
            return {category, subcategory, item};
          }
        }
      }
    }
    return null;
  }

  function expressionDetailPayload(item, category, subcategory) {
    const tags = expressionItemTags(item);
    const title = expressionItemTitle(item);
    return {
      type: 'item',
      title,
      subtitle: [
        expressionCategoryLabel(category),
        expressionSubcategoryLabel(subcategory),
      ].filter(Boolean).join(' / '),
      count: Number(item?.count || 0) || 0,
      tags,
      prompt: tags.join(', '),
      source: item?.source || '',
    };
  }

  function expressionExampleTagsFromCategories(categories, limit = 12) {
    const tags = [];
    const seen = new Set();
    for (const category of categories || []) {
      for (const subcategory of category.subcategories || []) {
        for (const item of expressionAllItems(subcategory)) {
          for (const tag of expressionItemTags(item)) {
            const clean = cleanPromptAtom(tag);
            const key = clean.toLowerCase();
            if (!clean || seen.has(key)) continue;
            seen.add(key);
            tags.push(clean);
            if (tags.length >= limit) return tags;
          }
        }
      }
    }
    return tags;
  }

  function expressionExampleTagsFromSubcategories(subcategories, limit = 12) {
    return expressionExampleTagsFromCategories([{subcategories: subcategories || []}], limit);
  }

  function expressionSummaryDetail(rows, title, subtitle = '', fallbackTags = []) {
    const tags = [];
    const seen = new Set();
    for (const source of [rows || [], (fallbackTags || []).map(tag => ({tags: [tag]}))]) {
      for (const row of source) {
        for (const tag of row.tags || []) {
          const clean = cleanPromptAtom(tag);
          const key = clean.toLowerCase();
          if (!clean || seen.has(key)) continue;
          seen.add(key);
          tags.push(clean);
          if (tags.length >= 12) break;
        }
        if (tags.length >= 12) break;
      }
      if (tags.length >= 12) break;
    }
    return {
      type: 'summary',
      title,
      subtitle,
      count: rows?.length || 0,
      tags,
      prompt: tags.join(', '),
    };
  }

  function expressionRowsDetail(rows, title, subtitle = '') {
    const tags = [];
    const seen = new Set();
    for (const row of rows || []) {
      for (const tag of row.tags || []) {
        const clean = cleanPromptAtom(tag);
        const key = clean.toLowerCase();
        if (!clean || seen.has(key)) continue;
        seen.add(key);
        tags.push(clean);
        if (tags.length >= 12) break;
      }
      if (tags.length >= 12) break;
    }
    return {
      type: 'summary',
      title,
      subtitle,
      count: rows?.length || 0,
      tags,
      prompt: tags.join(', '),
    };
  }

  function expressionCategoryRows(categories, query, limit) {
    return (categories || [])
      .filter(category => expressionNodeMatches(category, query))
      .slice(0, limit)
      .map(category => {
        const stats = expressionCategoryItemStats(category);
        return {
          tag: expressionCategoryLabel(category),
          value: presetPath('expressions', [category.id || category.label || '']),
          count: Number(category.count || stats.total || 0),
          desc: `${formatCount((category.subcategories || []).length || 0)} buckets`,
          group: 'preset/expressions',
          cat: 'category',
          _wc_type: 'preset_path',
          axis: 'expressions',
          stage: 'category',
          final: false,
          id: String(category.id || ''),
          labelKo: category.labelKo || '',
          tags: [],
          prompt: '',
        };
      });
  }

  function expressionSubcategoryRows(category, query, limit) {
    return (category?.subcategories || [])
      .filter(subcategory => expressionNodeMatches(subcategory, query))
      .slice(0, limit)
      .map(subcategory => {
        const total = expressionAllItems(subcategory).length || Number(subcategory.count || 0) || 0;
        return {
          tag: expressionSubcategoryLabel(subcategory),
          value: presetPath('expressions', [category.id || category.label || '', subcategory.id || subcategory.label || '']),
          count: total,
          desc: `${formatCount(total)} expressions`,
          group: 'preset/expressions',
          cat: 'subcategory',
          _wc_type: 'preset_path',
          axis: 'expressions',
          stage: 'subcategory',
          final: false,
          id: String(subcategory.id || ''),
          labelKo: subcategory.labelKo || '',
          tags: [],
          prompt: '',
        };
      });
  }

  function expressionItemRows(category, subcategory, query, limit, activeItem = null) {
    return expressionAllItems(subcategory)
      .filter(item => expressionNodeMatches(item, query))
      .slice(0, limit)
      .map(item => {
        const tags = expressionItemTags(item);
        const prompt = tags.join(', ');
        const internalPath = presetPath('expressions', expressionItemPath(category, subcategory, item));
        return {
          tag: expressionItemTitle(item),
          value: expressionShortcutToken(item, tags),
          count: Number(item.count || 0),
          desc: prompt || expressionItemTitle(item),
          group: 'preset/expressions',
          cat: 'item',
          _wc_type: 'preset_path',
          axis: 'expressions',
          stage: 'item',
          final: true,
          id: String(item.id || item.tag || ''),
          internalPath,
          rawLabel: item.label || item.tag || item.id || '',
          labelKo: item.displayLabelKo || item.labelKo || '',
          tags,
          prompt,
          insertText: prompt,
          detail: expressionDetailPayload(item, category, subcategory),
          active: !!activeItem && normalizePresetMatch(activeItem.id || activeItem.tag || activeItem.label) === normalizePresetMatch(item.id || item.tag || item.label),
        };
      });
  }

  function expressionGlobalItemRows(categories, query, limit) {
    const rows = [];
    for (const category of categories || []) {
      for (const subcategory of category.subcategories || []) {
        rows.push(...expressionItemRows(category, subcategory, query, Math.max(limit, 1)));
      }
    }
    return rows
      .filter(row => expressionNodeMatches({
        id: row.id,
        label: row.rawLabel || row.tag,
        tag: row.tag,
        tags: row.tags,
        prompt: row.prompt,
        displayLabelKo: row.labelKo,
      }, query))
      .sort((left, right) => Number(right.count || 0) - Number(left.count || 0) || String(left.tag || '').localeCompare(String(right.tag || '')))
      .slice(0, limit);
  }

  async function buildExpressionPresetAutocomplete(token, limit = 12, context = {}, inlineSearch = '') {
    await ensureExpressionPresetAutocompleteData(context);
    const parsed = parseExpressionPresetToken(token);
    const categories = expressionCategories();
    const segments = parsed.segments || [];
    const searchQuery = String(inlineSearch || '').trim();
    if (searchQuery) {
      const rows = expressionGlobalItemRows(categories, searchQuery, limit);
      return {
        stage: 'item',
        crumbs: [],
        parsed,
        rows,
        detail: expressionRowsDetail(rows, `Search: ${searchQuery}`, `${formatCount(rows.length)} matches`),
      };
    }

    const category = findExpressionNode(categories, segments[0] || '');
    const directContext = segments.length === 1 ? findExpressionDirectItemContext(categories, segments[0] || '') : null;
    if (!category && directContext) {
      const rows = expressionItemRows(
        directContext.category,
        directContext.subcategory,
        '',
        limit,
        directContext.item,
      );
      return {
        stage: 'item',
        crumbs: [
          expressionCrumb(directContext.category.id, expressionCategoryLabel(directContext.category), 'category'),
          expressionCrumb(directContext.subcategory.id, expressionSubcategoryLabel(directContext.subcategory), 'subcategory'),
        ],
        parsed,
        rows,
        detail: expressionDetailPayload(directContext.item, directContext.category, directContext.subcategory),
      };
    }
    if (segments.length < 1 || !category) {
      const rows = expressionCategoryRows(categories, segments[0] || '', limit);
      return {
        stage: 'category',
        crumbs: [],
        parsed,
        rows,
        detail: expressionSummaryDetail(rows, 'Expression Preset', `${formatCount(categories.length)} groups`, expressionExampleTagsFromCategories(categories)),
      };
    }

    const categoryCrumbs = [expressionCrumb(category.id, expressionCategoryLabel(category), 'category')];
    const subcategories = category.subcategories || [];
    const subcategory = findExpressionNode(subcategories, segments[1] || '');
    if (segments.length < 2 || !subcategory) {
      const rows = expressionSubcategoryRows(category, segments[1] || '', limit);
      return {
        stage: 'subcategory',
        crumbs: categoryCrumbs,
        parsed,
        rows,
        detail: expressionSummaryDetail(rows, expressionCategoryLabel(category), `${formatCount(subcategories.length)} buckets`, expressionExampleTagsFromSubcategories(subcategories)),
      };
    }

    const subcategoryCrumbs = [...categoryCrumbs, expressionCrumb(subcategory.id, expressionSubcategoryLabel(subcategory), 'subcategory')];
    const items = expressionAllItems(subcategory);
    const activeItem = findExpressionNode(items, segments[2] || '');
    const rows = expressionItemRows(category, subcategory, segments[2] || '', limit, activeItem);
    const detailItem = activeItem || rows[0] && findExpressionNode(items, rows[0].id);
    return {
      stage: 'item',
      crumbs: subcategoryCrumbs,
      parsed,
      rows,
      detail: detailItem
        ? expressionDetailPayload(detailItem, category, subcategory)
        : expressionRowsDetail(rows, expressionSubcategoryLabel(subcategory), `${formatCount(items.length)} expressions`),
    };
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
    const comboTags = combo
      ? (combo.prompt ? splitPromptTags(combo.prompt) : (combo.tags || []))
      : (event.promptAtoms?.length ? event.promptAtoms : [event.tag || event.label || event.id]);
    const baseTags = eventBaseTags(event, comboTags);
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
        const title = expressionItemTitle(item);
        const tags = expressionItemTagSummary(item) || title;
        return `
          <button type="button"
                  class="event-preset-event-row event-preset-expression-row ${active ? 'active' : ''}"
                  data-ep-action="expression-item"
                  data-ep-id="${escapeHtml(item.id)}"
                  aria-pressed="${active ? 'true' : 'false'}">
            <span class="event-preset-event-index">${index + 1}</span>
            <span class="event-preset-event-name event-preset-expression-name"${tagInfoAttrs(item.tag || tags)}>
              <span class="event-preset-expression-title">${escapeHtml(title)}</span>
              <span class="event-preset-expression-tags">${renderPromptTagTokens(tags)}</span>
            </span>
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
            <span>${escapeHtml(expressionItemTitle(item))}</span>
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
          ${category.labelKo ? `<small class="event-preset-ko-label">${escapeHtml(category.labelKo)}</small>` : ''}
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
          ${subcategory.labelKo ? `<small class="event-preset-ko-label">${escapeHtml(subcategory.labelKo)}</small>` : ''}
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
            <span class="event-preset-event-name event-preset-clothes-name"${tagInfoAttrs(item.tag)}>
              ${renderClothesDisplayLabel(item, item.label || item.tag)}
            </span>
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
            <span>
              ${escapeHtml(group.label || group.id)}
              ${group.labelKo ? `<small class="event-preset-ko-label">${escapeHtml(group.labelKo)}</small>` : ''}
            </span>
            <div class="event-preset-expression-chips">
              ${(group.items || []).map(item => `
                <button type="button"
                        class="event-preset-expression-chip event-preset-clothes-chip ${item.promoted ? 'promoted' : ''}"
                        data-ep-action="clothes-remove-item"
                        data-ep-id="${escapeHtml(item.id || item.tag)}"
                        data-ep-tag="${escapeHtml(item.tag)}">
                  <span>${renderClothesDisplayLabel(item, item.tag)}</span>
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
      const generationOverrides = typeof getGenerationOverrides === 'function'
        ? getGenerationOverrides()
        : null;
      if (generationOverrides && Object.keys(generationOverrides).length) {
        const currentOverrides = requestPayload.overrides && typeof requestPayload.overrides === 'object'
          ? requestPayload.overrides
          : {};
        requestPayload.overrides = {...currentOverrides, ...generationOverrides};
      }
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
    getPresetAutocompletePayload,
    getClothesRandomAutocompleteSelection,
    getFixtureState: () => viewData,
  };
}
