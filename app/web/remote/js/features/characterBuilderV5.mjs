// Assets 신 사양(V5) - 캐릭터 제작.
//
// 자작 캐릭터를 일곱 블록(머리 · 눈얼굴 · 신체 · 종족수인 · 의상 · 소품장식 · 소지품)의 부품으로 짓는다.
// 화면은 둘로 갈린다(사용자 승인 2026-10-11):
//   왼쪽  = 메인 프롬프트 자리를 덮는 블록 줄. 고른 부품이 **썸네일 칩**(Interactive 의 `.ia-cell` 그대로)으로 놓인다.
//   오른쪽 = Assets 창의 '신 사양' 탭. 부품 검색 · 축 탭 · 썸네일 그리드 · 시험 생성 · 보관함.
//
// 이 모드는 메인 프롬프트 글에 **쓰지 않는다.** 고른 것은 생성 요청에만 실리고, 고정 사양
// (모델 · scale · 해상도 · 메인 프롬프트 틀)은 서버가 쥔다(`core/character_builder_v5.py`).
// 그래서 Interactive 처럼 원본 프롬프트를 잡아 뒀다 되돌리는 절차가 없다 - 덮개만 걷으면 된다.
//
// 백엔드 계약(docs/ASSETS_V5_BUILDER_BACKEND_SRS_2026_10_11.md):
//   GET  /api/character-parts                    부품 카탈로그(data/character_parts.json)
//   GET  /api/character-asset/v5/spec            고정 사양(해상도 셋 · 유료 여부)
//   POST /api/character-asset/v5/generate        시험 생성
//   POST /api/character-asset/save               target.builder 에 부품 구성을 실어 저장
//   GET  /api/character-asset/list | detail      spec === 'v5' · builder_v5
//   GET  /api/character-asset/v5/candidate-check 결과가 투명 배경인가
//
// 신 사양은 **투명 배경이 전제**다(사용자 결정 2026-10-11 - 구 사양과 갈리는 선). 투명하지 않은 결과가 오면
// 경고한다(다시 생성해야 한다). 저장은 막지 않는다 - 그 그림은 **V4.5 구 사양으로** 저장된다.
// 판정은 서버가 한다(`core/character_builder_v5.transparency`). 저장을 구 사양으로 돌리는 것도 같은 함수라
// 화면의 경고와 실제로 저장되는 자리가 어긋나지 않는다(화면은 저장 응답의 `spec` 을 읽는다).
//
// 검색은 Interactive 와 같은 잣대다: 태그 이름과 한글 설명(TAG_DESC) 양쪽을 본다.
// ⚠️ 아래 import 의 `?v=` 는 interactivePanel.mjs 와 **같은 글자**여야 한다 - 다르면 2MB 모듈을 두 번 받는다.
import {TAG_DESC} from './interactiveAxes.mjs?v=20260913-gap3385';

const BLOCK_ORDER = ['hair', 'face', 'body', 'species', 'outfit', 'accessory', 'item'];
const GENDERS = [['girl', 'Female'], ['boy', 'Male'], ['other', 'Other']];
const RESOLUTION_LABEL = {standard: '표준', high: '고해상도', ultra: '초고해상도'};
const DRAFT_KEY = 'naia.assetsV5.draft';
const CANDIDATE_MAX = 8;       // 시험 생성 후보를 이만큼만 쥔다(가장 오래된 것부터 버린다)
const SEARCH_MAX = 150;        // 검색 결과 칸 수. 넘으면 넘었다고 말한다
const SEARCH_DELAY = 150;

export function createCharacterBuilderV5({
  document,
  fetchFn = (...args) => globalThis.fetch(...args),
  escHtml,
  showToast,
  showAppDialog = null,
  showPromptDialog = null,
  leftMount,
  rightMount,
  isNai = () => true,
}) {
  if (!leftMount || !rightMount) return null;

  let active = false;            // 덮개가 올라와 있는가(신 사양 탭이 보이는 동안)
  let loading = null;            // 카탈로그 · 사양을 받는 중인 약속
  let loadError = '';
  let catalog = null;
  let spec = null;
  const tagInfo = new Map();     // 태그 -> {block, part(부품 정의), entry(태그 객체)}
  const blockDef = new Map();    // 블록 키 -> 블록 정의

  let draft = emptyDraft();
  let activeBlock = 'hair';
  const activePart = new Map();  // 블록 키 -> 지금 펼친 부품 키
  let query = '';
  let searchTimer = null;

  // 후보는 **객체로** 쥔다(인덱스가 아니라). 새 후보가 앞에 끼어들어도 고른 것이 안 바뀐다.
  let candidates = [];
  let selected = null;
  let seedLock = false;
  let lockedSeed = null;
  let saving = false;

  let store = [];                // 보관함(spec === 'v5' 인 캐릭터)
  let storeSeq = 0;
  let loadedId = '';             // 보관함에서 불러와 고치는 중인 캐릭터

  function emptyDraft() {
    const parts = {};
    for (const key of BLOCK_ORDER) parts[key] = [];
    return {gender: 'girl', resolution: 'standard', parts};
  }

  function newRequestId() {
    try {
      return globalThis.crypto.randomUUID().replace(/-/g, '');
    } catch {
      return `cb${Date.now().toString(36)}${Math.random().toString(36).slice(2, 10)}`;
    }
  }

  // ------------------------------------------------------------------ 통신

  async function getJson(url) {
    const response = await fetchFn(url, {cache: 'no-store'});
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
    return data;
  }

  async function postJson(url, body) {
    const response = await fetchFn(url, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body || {}),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
    return data;
  }

  function ensureLoaded() {
    if (catalog && spec) return Promise.resolve();
    if (loading) return loading;
    loadError = '';
    loading = Promise.all([getJson('/api/character-parts'), getJson('/api/character-asset/v5/spec')])
      .then(([parts, sp]) => {
        catalog = parts;
        spec = sp;
        indexCatalog();
        restoreDraft();
      })
      .catch(error => {
        loadError = String(error?.message || error);
      })
      .finally(() => {
        loading = null;
        if (active) renderAll();
      });
    return loading;
  }

  function indexCatalog() {
    tagInfo.clear();
    blockDef.clear();
    for (const block of catalog?.blocks || []) {
      blockDef.set(block.key, block);
      for (const part of block.parts || []) {
        for (const entry of part.tags || []) tagInfo.set(entry.tag, {block: block.key, part, entry});
      }
      if (!activePart.has(block.key)) activePart.set(block.key, firstGridPart(block)?.key || '');
    }
  }

  /** 블록을 처음 열 때 펼칠 부품. 그림이 있는 축을 먼저 본다 - 색 · 길이는 늘 위에 함께 보이니까. */
  function firstGridPart(block) {
    const parts = block?.parts || [];
    return parts.find(part => part.kind === 'thumb') || parts[0] || null;
  }

  // ------------------------------------------------------------------ 초안

  /** 초안은 이 브라우저에만 남긴다. 탭을 떠났다 와도 고르던 것이 그대로다. */
  function saveDraft() {
    try {
      globalThis.localStorage?.setItem(DRAFT_KEY, JSON.stringify({...draft, loadedId}));
    } catch (_) { /* 사생활 모드 */ }
  }

  function restoreDraft() {
    let raw = null;
    try { raw = JSON.parse(globalThis.localStorage?.getItem(DRAFT_KEY) || 'null'); } catch (_) { raw = null; }
    if (!raw || typeof raw !== 'object') return;
    applyBuilder(raw);
    loadedId = typeof raw.loadedId === 'string' ? raw.loadedId : '';
  }

  /** 저장된 구성(초안 · 보관함)을 지금 카탈로그에 맞춰 받아들인다. 카탈로그에서 사라진 태그는 버린다. */
  function applyBuilder(raw) {
    const next = emptyDraft();
    if (GENDERS.some(([key]) => key === raw.gender)) next.gender = raw.gender;
    if ((spec?.resolutions || []).some(item => item.key === raw.resolution)) next.resolution = raw.resolution;
    for (const key of BLOCK_ORDER) {
      for (const item of (raw.parts && raw.parts[key]) || []) {
        const tag = typeof item === 'string' ? item : String(item?.tag || '');
        const info = tagInfo.get(tag);
        if (info && info.block === key && !next.parts[key].includes(tag)) next.parts[key].push(tag);
      }
    }
    draft = next;
  }

  function builderPayload(source = draft) {
    const parts = {};
    for (const key of BLOCK_ORDER) if (source.parts[key].length) parts[key] = [...source.parts[key]];
    return {version: 1, gender: source.gender, parts, resolution: source.resolution, pose_slot: ''};
  }

  const totalParts = () => BLOCK_ORDER.reduce((n, key) => n + draft.parts[key].length, 0);

  // ------------------------------------------------------------------ 그리기 - 칸

  function tagTip(tag) {
    const desc = (TAG_DESC || {})[tag];
    return desc ? `${tag} · ${desc}` : String(tag);
  }

  function thumbUrl(key) {
    const cut = String(key).indexOf('/');
    return `/api/interactive-thumb?axis=${encodeURIComponent(key.slice(0, cut))}`
      + `&tag=${encodeURIComponent(key.slice(cut + 1))}`;
  }

  /** 칸의 그림 자리. 썸네일이 없는 부품은 둘뿐이다: 색(색 칸) · 단계(글자 칸). */
  function cellMedia(info) {
    const {entry, part} = info;
    if (entry.thumb) {
      return `<img src="${escHtml(thumbUrl(entry.thumb))}" alt="" loading="lazy" decoding="async">`;
    }
    if (entry.hex) return `<span class="cb5-swatch" style="background:${escHtml(entry.hex)}"></span>`;
    return `<span class="cb5-step">${escHtml(part.label)}</span>`;
  }

  /** 썸네일 칩 하나. `chosen` 은 '선택됨' 배지 · 테두리를 켠다(그리드에서만 - 왼쪽 줄은 전부 고른 것이라 안 켠다). */
  function cellHtml(tag, {chosen = false, act = 'on'} = {}) {
    const info = tagInfo.get(tag);
    if (!info) return '';
    const sensitive = !!(info.part.adult || info.entry.adult);
    const cls = `ia-cell cb5-cell${chosen ? ' on' : ''}${sensitive ? ' is-sensitive' : ''}`;
    const label = act === 'on' ? `${tag} 넣기` : `${tag} 빼기`;
    return `<div class="${cls}" data-tag="${escHtml(tag)}" title="${escHtml(tagTip(tag))}">`
      + `<span class="ia-cell-img">${cellMedia(info)}`
      + `${sensitive ? '<span class="ia-cell-veil">보기</span>' : ''}</span>`
      + `<span class="ia-cell-cap"><span class="ia-cell-name">${escHtml(tag)}</span>`
      + `<button type="button" class="ia-cell-act" data-act="${act}" data-cb-toggle="${escHtml(tag)}"`
      + ` aria-label="${escHtml(label)}">${act === 'on' ? '+' : '−'}</button></span></div>`;
  }

  // ------------------------------------------------------------------ 그리기 - 왼쪽

  function renderLeft() {
    if (!catalog) {
      leftMount.innerHTML = `<div class="cb5-empty">${escHtml(loadError
        ? `부품 목록을 불러오지 못했습니다: ${loadError}` : '부품 목록을 불러오는 중...')}</div>`;
      return;
    }
    const genders = GENDERS.map(([key, label]) =>
      `<button type="button" class="cb5-seg-btn${draft.gender === key ? ' is-on' : ''}"`
      + ` data-cb-gender="${key}" aria-pressed="${draft.gender === key}">${label}</button>`).join('');
    const rows = BLOCK_ORDER.map(key => {
      const block = blockDef.get(key);
      if (!block) return '';
      const picks = draft.parts[key];
      const cells = picks.length
        ? picks.map(tag => cellHtml(tag, {act: 'off'})).join('')
        : '<span class="cb5-row-empty">비어 있음</span>';
      return `<div class="cb5-row${key === activeBlock ? ' is-on' : ''}" data-cb-block="${key}">`
        + `<div class="cb5-row-label"><b>${escHtml(block.label)}</b>`
        + `${picks.length ? `<span class="cb5-row-n">${picks.length}</span>` : ''}</div>`
        + `<div class="cb5-row-cells">${cells}</div></div>`;
    }).join('');
    leftMount.innerHTML = `<div class="cb5-head">`
      + `<span class="cb5-title">캐릭터 제작 · V5</span>`
      + `<div class="cb5-seg" role="group" aria-label="인물">${genders}</div>`
      + `<button type="button" class="cb5-btn" data-cb-act="clear"${totalParts() ? '' : ' disabled'}>Clear</button>`
      + `</div><div class="cb5-rows">${rows}</div>`;
  }

  // ------------------------------------------------------------------ 그리기 - 오른쪽

  function matchesQuery(tag, q) {
    if (String(tag).toLowerCase().includes(q)) return true;
    const desc = (TAG_DESC || {})[tag];
    return !!desc && String(desc).toLowerCase().includes(q);
  }

  function chosenSet(blockKey) {
    return new Set(draft.parts[blockKey] || []);
  }

  function partLabel(part) {
    // 신체 블록에는 '피부' 가 둘이다(그림 축과 색 팔레트). 색 쪽을 가려 부른다.
    return part.kind === 'palette' && part.key === 'skin_color' ? '피부 색' : part.label;
  }

  function searchHtml(q) {
    const groups = new Map();
    let total = 0;
    for (const [tag, info] of tagInfo) {
      if (!matchesQuery(tag, q)) continue;
      total += 1;
      if (total > SEARCH_MAX) continue;
      if (!groups.has(info.block)) groups.set(info.block, []);
      groups.get(info.block).push(tag);
    }
    if (!total) return '<div class="cb5-empty">찾는 부품이 없습니다</div>';
    const body = BLOCK_ORDER.filter(key => groups.has(key)).map(key => {
      const chosen = chosenSet(key);
      const cells = groups.get(key).map(tag =>
        cellHtml(tag, {chosen: chosen.has(tag), act: chosen.has(tag) ? 'off' : 'on'})).join('');
      return `<div class="cb5-hit-head">${escHtml(blockDef.get(key)?.label || key)}</div>`
        + `<div class="ia-cell-grid cb5-grid">${cells}</div>`;
    }).join('');
    // 자른 것은 자른다고 말한다 - 안 적으면 이것이 전부인 줄 안다.
    const more = total > SEARCH_MAX
      ? `<div class="cb5-note">${total}개 중 ${SEARCH_MAX}개만 보입니다. 더 좁혀 찾아 주세요.</div>` : '';
    return body + more;
  }

  /** 고른 블록의 그리드. 소분류(부품)는 그리드 오른쪽의 세로 목록이 고른다(사용자 지정 2026-10-11 -
   *  위에 가로로 늘어놓은 탭보다 오른쪽 목록을 선호). 접어 두는 것 없이 전부 보인다. */
  function blockHtml() {
    const block = blockDef.get(activeBlock);
    if (!block) return '';
    const chosen = chosenSet(activeBlock);
    const part = block.parts.find(item => item.key === activePart.get(activeBlock)) || block.parts[0];
    const cells = (part?.tags || []).map(entry =>
      cellHtml(entry.tag, {chosen: chosen.has(entry.tag), act: chosen.has(entry.tag) ? 'off' : 'on'})).join('');
    return `<div class="ia-cell-grid cb5-grid">${cells}</div>`;
  }

  function partsHtml(searching) {
    const block = blockDef.get(activeBlock);
    if (!block) return '';
    const chosen = chosenSet(activeBlock);
    const open = searching ? '' : activePart.get(activeBlock);
    return block.parts.map(part => {
      const picked = part.tags.reduce((n, entry) => n + (chosen.has(entry.tag) ? 1 : 0), 0);
      return `<button type="button" class="cb5-part${part.key === open ? ' is-open' : ''}"`
        + ` data-cb-part="${escHtml(part.key)}" aria-pressed="${part.key === open}">`
        + `<span class="cb5-part-name">${escHtml(partLabel(part))}</span>`
        + `${picked ? `<span class="cb5-part-sel">${picked}</span>` : ''}`
        + `<span class="cb5-part-n">${part.tags.length}</span></button>`;
    }).join('');
  }

  function renderMain() {
    const host = rightMount.querySelector('[data-cb-role="main"]');
    if (!host) return;
    const scroller = host.querySelector('.cb5-main-scroll');
    const top = scroller ? scroller.scrollTop : 0;
    const q = query.trim().toLowerCase();
    const block = blockDef.get(activeBlock);
    const part = block?.parts.find(item => item.key === activePart.get(activeBlock)) || block?.parts[0];
    host.querySelector('[data-cb-role="main-title"]').textContent = q
      ? '검색 결과' : `${block?.label || ''} · ${part ? partLabel(part) : ''}`;
    scroller.innerHTML = q ? searchHtml(q) : blockHtml();
    scroller.scrollTop = top;
    host.querySelector('[data-cb-role="parts"]').innerHTML = partsHtml(!!q);
  }

  function candidateImage(candidate) {
    return `/api/character-asset/candidate/image?history_id=${encodeURIComponent(candidate.historyId)}`;
  }

  function sideHtml() {
    const resolutions = (spec?.resolutions || []).map(item =>
      `<button type="button" class="cb5-seg-btn${draft.resolution === item.key ? ' is-on' : ''}"`
      + ` data-cb-res="${escHtml(item.key)}" aria-pressed="${draft.resolution === item.key}"`
      + ` title="${item.width} x ${item.height}">${escHtml(RESOLUTION_LABEL[item.key] || item.key)}</button>`).join('');
    const current = (spec?.resolutions || []).find(item => item.key === draft.resolution);
    // 금액 숫자는 적지 않는다(사용자 규칙) - 든다는 사실만.
    const paid = current?.paid ? '<span class="cb5-paid">Anlas 소모</span>' : '';
    const size = current ? `<span class="cb5-size">${current.width} x ${current.height}</span>` : '';
    const seedKnown = Number.isFinite(selected?.seed);
    const seedText = seedLock && Number.isFinite(lockedSeed) ? String(lockedSeed) : '';
    let stage = '<span class="cb5-stage-empty">Generate 를 누르면 여기에 그립니다</span>';
    if (selected?.status === 'done') {
      stage = `<img src="${escHtml(candidateImage(selected))}" alt="">`
        + (selected.opaque ? '<span class="cb5-stage-warn">투명 배경이 아닙니다 · 다시 생성해 주세요'
          + '<small>저장하면 V4.5 구 사양으로 저장됩니다</small></span>' : '');
    } else if (selected?.status === 'pending') {
      stage = '<span class="cb5-stage-empty">생성 중...</span>';
    } else if (selected?.status === 'error') {
      stage = `<span class="cb5-stage-empty is-error">${escHtml(selected.message || '생성하지 못했습니다')}</span>`;
    }
    const strip = candidates.map((candidate, index) => {
      const cls = `cb5-cand${candidate === selected ? ' is-on' : ''} is-${candidate.status}`
        + `${candidate.saved ? ' is-saved' : ''}${candidate.opaque ? ' is-opaque' : ''}`;
      const inner = candidate.status === 'done'
        ? `<img src="${escHtml(candidateImage(candidate))}" alt="" loading="lazy">`
        : `<span>${candidate.status === 'pending' ? '...' : '!'}</span>`;
      return `<button type="button" class="${cls}" data-cb-cand="${index}"`
        + ` aria-label="후보 ${index + 1}">${inner}</button>`;
    }).join('');
    // 투명한지 아직 모르는 동안(확인 중)에만 잠깐 막는다 - 어느 사양으로 저장되는지 말할 수 있어야 한다.
    // 투명하지 않은 그림도 저장은 된다(구 사양으로).
    const canSave = selected?.status === 'done' && selected.opaque !== null && !selected.saved && !saving;
    const saveLabel = selected?.saved ? '저장됨' : (selected?.opaque ? '구 사양으로 저장' : '에셋으로 저장');
    // 결과 그림이 이 칸의 주인이다(사용자 지정 2026-10-11 - "생성 결과 이미지가 컸으면"). 조작은 위아래 한 줄씩만.
    return `<div class="cb5-side-top"><span class="cb5-side-label">시험 생성</span>`
      + `<div class="cb5-seg" role="group" aria-label="해상도">${resolutions}</div>${size}${paid}</div>`
      + `<div class="cb5-stage">${stage}</div>`
      + `<div class="cb5-strip">${strip}</div>`
      + `<div class="cb5-side-bottom">`
      + `<label class="cb5-check"><input type="checkbox" data-cb-role="seedlock"`
      + `${seedLock ? ' checked' : ''}${seedKnown || seedLock ? '' : ' disabled'}> 시드 고정</label>`
      + `<span class="cb5-seed">${escHtml(seedText)}</span>`
      + `<button type="button" class="cb5-btn is-primary" data-cb-act="save"${canSave ? '' : ' disabled'}>`
      + `${saveLabel}</button></div>`;
  }

  function renderSide() {
    const host = rightMount.querySelector('[data-cb-role="side"]');
    if (host) host.innerHTML = sideHtml();
  }

  function storeName(item) {
    return String(item.display_name || '').trim() || String(item.id || '').slice(0, 8);
  }

  function renderStore() {
    const host = rightMount.querySelector('[data-cb-role="store"]');
    if (!host) return;
    const cards = store.map(item => {
      const thumb = `/api/character-asset/thumb?id=${encodeURIComponent(item.id)}&size=grid&v=${item.revision || 0}`;
      return `<div class="cb5-card${item.id === loadedId ? ' is-on' : ''}" data-cb-store="${escHtml(item.id)}">`
        + `<button type="button" class="cb5-card-open" data-cb-act="store-open" title="이 캐릭터의 부품 구성을 불러옵니다">`
        + `<img src="${escHtml(thumb)}" alt="" loading="lazy"><span>${escHtml(storeName(item))}</span></button>`
        + `<span class="cb5-card-acts">`
        + `<button type="button" data-cb-act="store-apply" title="캐릭터 슬롯 C1 에 적용합니다">C1</button>`
        + `<button type="button" data-cb-act="store-delete" title="이 캐릭터를 지웁니다">×</button>`
        + `</span></div>`;
    }).join('');
    host.innerHTML = `<div class="cb5-store-head">보관함 · ${store.length}</div>`
      + `<div class="cb5-store-list">${cards || '<span class="cb5-row-empty">저장한 캐릭터가 여기에 모입니다</span>'}</div>`;
  }

  function renderRight() {
    if (!catalog || !spec) {
      rightMount.innerHTML = `<div class="cb5-empty">${escHtml(loadError
        ? `부품 목록을 불러오지 못했습니다: ${loadError}` : '부품 목록을 불러오는 중...')}</div>`;
      return;
    }
    // 뼈대는 한 번만 세운다 - 검색칸을 다시 그리면 치던 글자와 초점이 날아간다.
    if (!rightMount.querySelector('[data-cb-role="main"]')) {
      rightMount.innerHTML = `<div class="cb5-win">`
        + `<section class="cb5-main" data-cb-role="main">`
        + `<input type="text" class="cb5-search" data-cb-role="search" autocomplete="off" spellcheck="false"`
        + ` placeholder="부품 검색 · twintails, 땋은 머리">`
        + `<div class="cb5-main-title" data-cb-role="main-title"></div>`
        + `<div class="cb5-browse"><div class="cb5-main-scroll"></div>`
        + `<nav class="cb5-parts" data-cb-role="parts" aria-label="소분류"></nav></div></section>`
        + `<aside class="cb5-side" data-cb-role="side"></aside></div>`
        + `<section class="cb5-store" data-cb-role="store"></section>`;
      rightMount.querySelector('[data-cb-role="search"]').value = query;
    }
    renderMain();
    renderSide();
    renderStore();
  }

  function renderAll() {
    renderLeft();
    renderRight();
  }

  // ------------------------------------------------------------------ 조작

  function toggleTag(tag) {
    const info = tagInfo.get(tag);
    if (!info) return;
    let list = draft.parts[info.block];
    if (list.includes(tag)) {
      list = list.filter(item => item !== tag);
    } else {
      // 색 · 단계는 하나만 고른다 - 같은 부품의 먼저 고른 것을 밀어낸다.
      if (info.part.kind !== 'thumb') list = list.filter(item => tagInfo.get(item)?.part !== info.part);
      list = [...list, tag];
    }
    draft.parts[info.block] = list;
    saveDraft();
    renderLeft();
    renderMain();
  }

  function setActiveBlock(key) {
    if (!blockDef.has(key) || key === activeBlock) return;
    activeBlock = key;
    // 블록을 고르면 검색을 걷는다 - 검색 결과가 그리드를 덮고 있으면 눌러도 아무 일이 없어 보인다.
    if (query) {
      query = '';
      const input = rightMount.querySelector('[data-cb-role="search"]');
      if (input) input.value = '';
    }
    renderLeft();
    renderMain();
    const scroller = rightMount.querySelector('.cb5-main-scroll');
    if (scroller) scroller.scrollTop = 0;
  }

  async function confirmDialog(title, message, okText) {
    if (typeof showAppDialog !== 'function') return false;
    return showAppDialog('', {
      title, messageHtml: escHtml(message), okText, cancelText: '취소',
    });
  }

  async function clearDraft() {
    if (!totalParts()) return;
    if (!await confirmDialog('캐릭터 제작', '고른 부품을 모두 비웁니다.', '비우기')) return;
    const keep = {gender: draft.gender, resolution: draft.resolution};
    draft = {...emptyDraft(), ...keep};
    loadedId = '';
    saveDraft();
    renderAll();
  }

  // ------------------------------------------------------------------ 시험 생성

  function dropOldCandidates() {
    while (candidates.length > CANDIDATE_MAX) {
      // 고른 것과 아직 오고 있는 것은 버리지 않는다.
      const index = candidates.map((item, i) => [item, i]).reverse()
        .find(([item]) => item !== selected && item.status !== 'pending')?.[1];
      if (index === undefined) break;
      candidates.splice(index, 1);
    }
  }

  /** 메인 Generate 단추가 이 모드에서 부르는 문. 처리했으면 true(= 일반 생성으로 넘기지 마라). */
  function generate() {
    if (!active) return false;
    if (!catalog || !spec) {
      showToast('부품 목록을 아직 불러오지 못했습니다', 'error');
      return true;
    }
    if (!isNai()) {
      showToast('캐릭터 제작은 NAI 모드 전용입니다', 'error');
      return true;
    }
    if (!totalParts()) {
      showToast('부품을 하나 이상 골라 주세요', 'error');
      return true;
    }
    const builder = builderPayload();
    const candidate = {
      requestId: newRequestId(), status: 'pending', historyId: '', seed: null, message: '',
      saved: false,
      // 투명 배경인가. null = 아직 모른다(확인 중) · false = 투명하다 · true = 투명하지 않다(다시 생성해야 한다).
      opaque: null,
      // 저장할 때는 **이 그림을 만든 구성**을 싣는다 - 그 뒤에 고친 초안이 아니라.
      builder,
    };
    candidates.unshift(candidate);
    if (!selected || selected.status !== 'done') selected = candidate;
    dropOldCandidates();
    renderSide();
    postJson('/api/character-asset/v5/generate', {
      request_id: candidate.requestId,
      count: 1,
      gender: builder.gender,
      parts: builder.parts,
      resolution: builder.resolution,
      seed: seedLock && Number.isFinite(lockedSeed) ? lockedSeed : null,
      pose_slot: builder.pose_slot,
    }).then(result => {
      if (result?.ok && (result.accepted || []).length) return;
      const reason = (result?.rejected || [])[0];
      failCandidate(candidate, reason?.message || reason?.error || '요청이 받아들여지지 않았습니다');
    }).catch(error => failCandidate(candidate, String(error?.message || error)));
    return true;
  }

  function failCandidate(candidate, message) {
    if (candidate.status === 'done') return;
    candidate.status = 'error';
    candidate.message = message;
    showToast(`시험 생성 실패: ${message}`, 'error');
    renderSide();
  }

  function handleResultMeta(meta) {
    if (!meta || meta.character_asset_flow !== 'builder_v5') return;
    const candidate = candidates.find(item => item.requestId === String(meta.character_asset_request_id || ''));
    if (!candidate || candidate.status === 'done') return;
    candidate.status = 'done';
    candidate.historyId = String(meta.history_id || '');
    const seed = Number(meta.seed);
    candidate.seed = Number.isFinite(seed) && seed > 0 ? seed : null;
    candidate.builder.seed = candidate.seed;
    // 보고 있던 것이 완성본이 아니면(기다리는 중 · 실패 · 없음) 새 그림으로 옮긴다.
    if (!selected || selected.status !== 'done') selected = candidate;
    renderSide();
    void checkTransparency(candidate);
  }

  /** 신 사양의 그림은 투명 배경이어야 한다. 아니면 경고한다 - 그 그림은 저장할 수 없고 다시 생성해야 한다. */
  async function checkTransparency(candidate) {
    try {
      const report = await getJson(
        `/api/character-asset/v5/candidate-check?history_id=${encodeURIComponent(candidate.historyId)}`);
      candidate.opaque = !report.ok;
    } catch (error) {
      // 확인을 못 했으면 투명하다고 치지 않는다. 저장의 목(서버)이 어차피 같은 판정으로 거절한다.
      candidate.opaque = true;
      showToast(`투명 배경 확인 실패: ${error.message}`, 'error');
      renderSide();
      return;
    }
    if (candidate.opaque) {
      showToast('투명 배경이 아닌 그림이 나왔습니다 - 다시 생성해 주세요 (저장하면 V4.5 구 사양으로 저장됩니다)', 'error');
    }
    renderSide();
  }

  function handleGenerationError(message) {
    const candidate = candidates.find(item => item.requestId === String(message?.requestId || ''));
    if (candidate) failCandidate(candidate, String(message?.message || '생성하지 못했습니다'));
  }

  // ------------------------------------------------------------------ 저장 · 보관함

  async function saveSelected() {
    const candidate = selected;
    if (!candidate || candidate.status !== 'done' || candidate.saved || saving) return;
    let name = '';
    if (typeof showPromptDialog === 'function') {
      const typed = await showPromptDialog('캐릭터 이름을 적어 주세요. 비워 두면 나중에 붙일 수 있습니다.', {
        title: '에셋으로 저장', okText: '저장', cancelText: '취소', defaultValue: '',
      });
      if (typed === null) return;
      name = String(typed || '').trim();
    }
    saving = true;
    renderSide();
    try {
      const result = await postJson('/api/character-asset/save', {
        source: {kind: 'history', history_id: candidate.historyId},
        target: {kind: 'new', builder: candidate.builder},
      });
      const id = String(result?.character_id || '');
      if (id && name) {
        // 이름은 따로 붙인다(저장 라우트는 이름을 받지 않는다). 여기서 실패해도 그림은 이미 저장됐다.
        try { await postJson('/api/character-asset/rename', {id, display_name: name}); }
        catch (error) { showToast(`이름을 붙이지 못했습니다: ${error.message}`, 'error'); }
      }
      candidate.saved = true;
      if (result?.spec === 'v5') {
        loadedId = id;
        saveDraft();
        showToast('새 캐릭터로 저장했습니다', 'success');
      } else {
        // 서버가 구 사양으로 돌렸다(투명 배경이 아니다). 신 사양 보관함에는 안 뜬다 - 구 사양 탭에 있다.
        showToast('투명 배경이 아니어서 V4.5 구 사양으로 저장했습니다 (구 사양 탭에 있습니다)', 'success');
      }
      await loadStore();
    } catch (error) {
      showToast(`저장 실패: ${error.message}`, 'error');
    } finally {
      saving = false;
      renderSide();
    }
  }

  async function loadStore() {
    const seq = ++storeSeq;
    try {
      const data = await getJson('/api/character-asset/list');
      if (seq !== storeSeq) return;       // 더 새로운 요청이 있다
      store = (data.characters || []).filter(item => item && item.spec === 'v5');
    } catch (error) {
      if (seq !== storeSeq) return;
      store = [];
      showToast(`보관함을 불러오지 못했습니다: ${error.message}`, 'error');
    }
    renderStore();
  }

  async function openStored(id) {
    try {
      const detail = await getJson(`/api/character-asset/detail?id=${encodeURIComponent(id)}`);
      if (!detail.builder_v5) {
        showToast('이 캐릭터에는 부품 구성이 없습니다', 'error');
        return;
      }
      if (totalParts() && id !== loadedId
          && !await confirmDialog('캐릭터 제작', '지금 고른 부품을 이 캐릭터의 구성으로 바꿉니다.', '불러오기')) return;
      applyBuilder(detail.builder_v5);
      loadedId = id;
      saveDraft();
      renderAll();
    } catch (error) {
      showToast(`불러오지 못했습니다: ${error.message}`, 'error');
    }
  }

  async function applyStored(id) {
    if (!isNai()) {
      showToast('캐릭터 슬롯 적용은 NAI 모드 전용입니다', 'error');
      return;
    }
    try {
      await postJson('/api/character-asset/apply', {id, variation: '', mode: 'c1'});
      showToast('C1 에 적용했습니다', 'success');
    } catch (error) {
      showToast(`적용 실패: ${error.message}`, 'error');
    }
  }

  async function deleteStored(id) {
    const item = store.find(entry => entry.id === id);
    if (!await confirmDialog('캐릭터 삭제', `${item ? storeName(item) : '이 캐릭터'} - 되돌릴 수 없습니다.`, '삭제')) return;
    try {
      await postJson('/api/character-asset/delete', {id});
      if (loadedId === id) { loadedId = ''; saveDraft(); }
      showToast('캐릭터를 지웠습니다', 'success');
      await loadStore();
    } catch (error) {
      showToast(`삭제 실패: ${error.message}`, 'error');
    }
  }

  // ------------------------------------------------------------------ 이벤트

  function onClick(event) {
    const toggle = event.target.closest('[data-cb-toggle]');
    if (toggle) {
      event.stopPropagation();
      toggleTag(toggle.dataset.cbToggle);
      return;
    }
    const gender = event.target.closest('[data-cb-gender]');
    if (gender) {
      draft.gender = gender.dataset.cbGender;
      saveDraft();
      renderLeft();
      return;
    }
    const res = event.target.closest('[data-cb-res]');
    if (res) {
      draft.resolution = res.dataset.cbRes;
      saveDraft();
      renderSide();
      return;
    }
    const part = event.target.closest('[data-cb-part]');
    if (part) {
      activePart.set(activeBlock, part.dataset.cbPart);
      // 소분류를 누르면 검색을 걷는다 - 검색 결과가 그리드를 덮고 있으면 눌러도 아무 일이 없어 보인다.
      if (query) {
        query = '';
        const input = rightMount.querySelector('[data-cb-role="search"]');
        if (input) input.value = '';
      }
      renderMain();
      const scroller = rightMount.querySelector('.cb5-main-scroll');
      if (scroller) scroller.scrollTop = 0;
      return;
    }
    const cand = event.target.closest('[data-cb-cand]');
    if (cand) {
      selected = candidates[Number(cand.dataset.cbCand)] || selected;
      renderSide();
      return;
    }
    const act = event.target.closest('[data-cb-act]');
    if (act && !act.disabled) {
      const id = act.closest('[data-cb-store]')?.dataset.cbStore || '';
      const name = act.dataset.cbAct;
      if (name === 'clear') void clearDraft();
      else if (name === 'save') void saveSelected();
      else if (name === 'store-open') void openStored(id);
      else if (name === 'store-apply') void applyStored(id);
      else if (name === 'store-delete') void deleteStored(id);
      return;
    }
    const row = event.target.closest('[data-cb-block]');
    if (row) setActiveBlock(row.dataset.cbBlock);
  }

  function onChange(event) {
    const box = event.target.closest('[data-cb-role="seedlock"]');
    if (!box) return;
    seedLock = !!box.checked;
    lockedSeed = seedLock && Number.isFinite(selected?.seed) ? selected.seed : (seedLock ? lockedSeed : null);
    if (seedLock && !Number.isFinite(lockedSeed)) seedLock = false;
    renderSide();
  }

  function onInput(event) {
    const input = event.target.closest('[data-cb-role="search"]');
    if (!input) return;
    query = input.value;
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
      renderMain();
      const scroller = rightMount.querySelector('.cb5-main-scroll');
      if (scroller) scroller.scrollTop = 0;
    }, SEARCH_DELAY);
  }

  leftMount.addEventListener('click', onClick);
  rightMount.addEventListener('click', onClick);
  rightMount.addEventListener('change', onChange);
  rightMount.addEventListener('input', onInput);

  return {
    /** 덮개를 올리고 내린다. 올릴 때 한 번 카탈로그를 받고, 보관함은 올릴 때마다 새로 읽는다. */
    setActive(next) {
      next = !!next;
      if (next === active) return;
      active = next;
      leftMount.hidden = !active;
      if (!active) return;
      renderAll();
      void ensureLoaded().then(() => { if (active && catalog) void loadStore(); });
    },
    isActive: () => active,
    generate,
    handleResultMeta,
    handleGenerationError,
  };
}
